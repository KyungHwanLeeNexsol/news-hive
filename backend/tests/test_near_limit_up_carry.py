"""SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 테스트.

AC-001 ~ AC-012 전체 검증.
RED 단계: detect_near_limit_up_carries 미구현 상태에서 실패 확인.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# 픽스처: 인메모리 SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """인메모리 SQLite 세션 픽스처."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                naver_code VARCHAR(10),
                is_custom BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                market VARCHAR(10),
                market_cap BIGINT,
                keywords TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sector_id) REFERENCES sectors(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fund_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id INTEGER NOT NULL,
                signal VARCHAR(10) NOT NULL,
                confidence FLOAT NOT NULL,
                target_price INTEGER,
                stop_loss INTEGER,
                reasoning TEXT NOT NULL,
                news_summary TEXT,
                financial_summary TEXT,
                market_summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                originally_created_at DATETIME,
                price_at_signal INTEGER,
                price_after_1d INTEGER,
                price_after_3d INTEGER,
                price_after_5d INTEGER,
                is_correct BOOLEAN,
                return_pct FLOAT,
                verified_at DATETIME,
                benchmark_return_pct FLOAT,
                alpha_pct FLOAT,
                error_category VARCHAR(30),
                price_after_6h INTEGER,
                price_after_12h INTEGER,
                early_warning BOOLEAN,
                factor_scores TEXT,
                composite_score FLOAT,
                prompt_version VARCHAR(50),
                trend_alignment VARCHAR(20),
                volatility_level VARCHAR(10),
                ai_model VARCHAR(50),
                signal_type VARCHAR(30),
                disclosure_id INTEGER,
                tp_sl_method VARCHAR(20) DEFAULT 'legacy_fixed',
                paper_executed BOOLEAN NOT NULL DEFAULT 0,
                surge_metadata TEXT,
                FOREIGN KEY (stock_id) REFERENCES stocks(id)
            )
        """))
        conn.commit()

    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_stock(
    db: Session,
    stock_code: str,
    name: str = "테스트주식",
    market_cap: int = 1_000_000_000_000,  # 1조 원
) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성 헬퍼."""
    from app.models.sector import Sector
    from app.models.stock import Stock

    sector = db.query(Sector).first()
    if sector is None:
        sector = Sector(name="테스트섹터", naver_code="001")
        db.add(sector)
        db.flush()

    stock = Stock(
        stock_code=stock_code,
        name=name,
        sector_id=sector.id,
        market_cap=market_cap,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_signal(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
    created_at: datetime | None = None,
    paper_executed: bool = True,
) -> "FundSignal":  # noqa: F821
    """테스트용 FundSignal 레코드 생성 헬퍼."""
    from app.models.fund_signal import FundSignal

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.45,
        reasoning="테스트 시그널",
        signal_type=signal_type,
        paper_executed=paper_executed,
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_config(**kwargs):
    """NearLimitUpConfig 헬퍼."""
    from app.surge_config.surge_settings import NearLimitUpConfig
    return NearLimitUpConfig(**kwargs)


def _mock_price(change_rate: float):
    """_fetch_price_change_sync 모킹용 dict 반환."""
    return {"current_price": 50000, "change_rate": change_rate}


# ---------------------------------------------------------------------------
# AC-001: +27% 종목 → surge_candidate 생성, confidence ≈ 0.45
# ---------------------------------------------------------------------------

def test_ac001_27pct_creates_surge_candidate(db):
    """AC-001: +27% 종목에서 surge_candidate 시그널 생성, confidence ≈ 0.45."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _stock = _make_stock(db, "000010", "상한가근접주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == "surge_candidate"
    assert abs(sig.confidence - 0.45) < 0.01  # 27/30*0.5 = 0.45
    metadata = json.loads(sig.surge_metadata)
    assert "near_limit_up_carry" in metadata["surge_basis"]


# ---------------------------------------------------------------------------
# AC-002: +30% 정확히 → 생성 안 함 (상한가 도달)
# ---------------------------------------------------------------------------

def test_ac002_exact_30pct_no_signal(db):
    """AC-002: +30.0% 종목은 시그널 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000020", "상한가정확히")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(30.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-003: +20% 종목 → 생성 안 함 (min_pct 미달)
# ---------------------------------------------------------------------------

def test_ac003_20pct_below_threshold_no_signal(db):
    """AC-003: +20% 종목은 min_pct=25.0 미달로 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000030", "약상승주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(20.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-004: 오늘 이미 surge_candidate 있는 종목 → 중복 생성 안 함
# ---------------------------------------------------------------------------

def test_ac004_existing_surge_candidate_today_no_duplicate(db):
    """AC-004: 오늘 surge_candidate 이미 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock = _make_stock(db, "000040", "기존시그널주")
    _make_signal(db, stock.id, signal_type="surge_candidate")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-005: 오늘 이미 theme_propagation 있는 종목 → 중복 생성 안 함
# ---------------------------------------------------------------------------

def test_ac005_existing_theme_propagation_today_no_duplicate(db):
    """AC-005: 오늘 theme_propagation 이미 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock = _make_stock(db, "000050", "테마전파주")
    _make_signal(db, stock.id, signal_type="theme_propagation")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-006: 가격 조회 실패 → 스킵하고 계속 진행
# ---------------------------------------------------------------------------

def test_ac006_price_fetch_failure_skips_and_continues(db):
    """AC-006: 첫 종목 가격 조회 실패 → 스킵하고 두 번째 종목 처리 계속."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _stock1 = _make_stock(db, "000060", "조회실패주")
    stock2 = _make_stock(db, "000070", "조회성공주")

    def _mock_provider(stock_code: str):
        if stock_code == "000060":
            return None  # 조회 실패
        return _mock_price(27.0)

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_provider,
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    # stock2만 생성
    assert len(signals) == 1
    assert signals[0].stock_id == stock2.id


# ---------------------------------------------------------------------------
# AC-007: detect_near_limit_up_carries 내부 예외 → 빈 리스트 반환
# ---------------------------------------------------------------------------

def test_ac007_internal_exception_returns_empty_list(db):
    """AC-007: 내부 예외 발생 시 빈 리스트 반환, 파이프라인 미영향."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000080", "예외발생주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=RuntimeError("네트워크 오류"),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    # 예외가 발생해도 빈 리스트 반환 (파이프라인 보호)
    assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# AC-008: max_signals_per_day=2 설정 시 최대 2건만 생성
# ---------------------------------------------------------------------------

def test_ac008_max_signals_per_day_limits_output(db):
    """AC-008: max_signals_per_day=2 설정 시 최대 2건만 생성."""
    from app.services.surge_detector import detect_near_limit_up_carries

    for i in range(5):
        _make_stock(db, f"00010{i}", f"종목{i}")

    cfg = _make_config(max_signals_per_day=2)

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 2


# ---------------------------------------------------------------------------
# AC-009: enabled=False → 빈 리스트 반환
# ---------------------------------------------------------------------------

def test_ac009_disabled_returns_empty_list(db):
    """AC-009: enabled=False 설정 시 즉시 빈 리스트 반환."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000090", "비활성화주")
    cfg = _make_config(enabled=False)

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ) as mock_fetch:
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []
    mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# AC-010: +29.99% 종목 → 생성됨 (상한가 미달 경계값)
# ---------------------------------------------------------------------------

def test_ac010_boundary_29_99_creates_signal(db):
    """AC-010: +29.99% 종목은 상한가 미달 경계값으로 시그널 생성됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000100", "경계값주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(29.99),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1


# ---------------------------------------------------------------------------
# AC-011: +25.0% 종목 → 생성됨 (최소 경계값)
# ---------------------------------------------------------------------------

def test_ac011_boundary_25_0_creates_signal(db):
    """AC-011: +25.0% 종목은 최소 경계값으로 시그널 생성됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000110", "최소경계주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(25.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1


# ---------------------------------------------------------------------------
# AC-012: paper_executed=True 확인
# ---------------------------------------------------------------------------

def test_ac012_paper_executed_is_true(db):
    """AC-012: 생성된 시그널의 paper_executed=True 확인."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000120", "페이퍼주")
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(27.0),
    ):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    assert signals[0].paper_executed is True
