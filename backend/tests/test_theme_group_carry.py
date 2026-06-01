"""SPEC-AI-025: 테마 그룹 강세 carry-forward 테스트.

AC-001 ~ AC-005 전체 검증.
RED 단계: detect_theme_group_carry_forward 미구현 상태에서 실패 확인.
"""

from __future__ import annotations

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
            CREATE TABLE IF NOT EXISTS theme_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                anchor_stock_id INTEGER,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (anchor_stock_id) REFERENCES stocks(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_theme_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id INTEGER NOT NULL,
                theme_group_id INTEGER NOT NULL,
                weight FLOAT NOT NULL DEFAULT 1.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_id) REFERENCES stocks(id),
                FOREIGN KEY (theme_group_id) REFERENCES theme_groups(id)
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

def _make_sector(db: Session) -> "Sector":
    from app.models.sector import Sector
    sector = db.query(Sector).first()
    if sector is None:
        sector = Sector(name="테스트섹터", naver_code="001")
        db.add(sector)
        db.flush()
    return sector


def _make_stock(
    db: Session,
    stock_code: str,
    name: str = "테스트주식",
) -> "Stock":
    """테스트용 Stock 레코드 생성."""
    from app.models.stock import Stock

    sector = _make_sector(db)
    stock = Stock(
        stock_code=stock_code,
        name=name,
        sector_id=sector.id,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_theme_group(
    db: Session,
    name: str,
    anchor_stock_id: int | None,
    member_ids: list[int],
) -> "ThemeGroup":
    """테마 그룹 + 멤버 연결 생성."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup

    group = ThemeGroup(name=name, anchor_stock_id=anchor_stock_id)
    db.add(group)
    db.flush()

    for sid in member_ids:
        stg = StockThemeGroup(stock_id=sid, theme_group_id=group.id)
        db.add(stg)
    db.flush()
    return group


def _make_signal_today(db: Session, stock_id: int) -> "FundSignal":
    """오늘 날짜 FundSignal 생성."""
    from app.models.fund_signal import FundSignal

    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.5,
        reasoning="기존 시그널",
        signal_type="surge_candidate",
        paper_executed=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(signal)
    db.flush()
    return signal


def _make_config(**kwargs):
    """ThemeGroupCarryConfig 헬퍼."""
    from app.surge_config.surge_settings import ThemeGroupCarryConfig
    return ThemeGroupCarryConfig(**kwargs)


def _mock_price(change_rate: float) -> dict:
    return {"current_price": 50000, "change_rate": change_rate}


# ---------------------------------------------------------------------------
# AC-001: 앵커 +8% → 피어 시그널 생성, confidence ≈ 0.107
# ---------------------------------------------------------------------------

def test_characterize_theme_group_carry_ac001_anchor_surge_creates_peer_signals(db):
    """AC-001: 앵커 +8% → 피어 종목에 surge_candidate 생성, confidence ≈ 0.107."""
    from app.services.surge_detector import detect_theme_group_carry_forward

    anchor = _make_stock(db, "000010", "앵커주")
    peer1 = _make_stock(db, "000020", "피어1")
    peer2 = _make_stock(db, "000030", "피어2")
    _make_theme_group(db, "테스트그룹", anchor.id, [anchor.id, peer1.id, peer2.id])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(8.0),
    ):
        signals = detect_theme_group_carry_forward(db, cfg)

    # 피어만 생성 (앵커 자신은 제외 또는 이미 급등이므로 동작 여부는 구현에 따름)
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.signal_type == "surge_candidate"
    # confidence = round(8.0 / 30.0 * 0.4, 4) = 0.1067
    assert 0.10 <= sig.confidence <= 0.12

    import json
    metadata = json.loads(sig.surge_metadata or "{}")
    assert "theme_group_carry" in metadata.get("surge_basis", [])


# ---------------------------------------------------------------------------
# AC-002: 앵커 +3% (anchor_surge_min_pct=5.0 미달) → 시그널 없음
# ---------------------------------------------------------------------------

def test_characterize_theme_group_carry_ac002_below_threshold_no_signal(db):
    """AC-002: 앵커 +3% (임계값 미달) → 시그널 생성 안 함."""
    from app.services.surge_detector import detect_theme_group_carry_forward

    anchor = _make_stock(db, "000010", "앵커주")
    peer = _make_stock(db, "000020", "피어")
    _make_theme_group(db, "소폭그룹", anchor.id, [anchor.id, peer.id])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(3.0),
    ):
        signals = detect_theme_group_carry_forward(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-003: 피어가 이미 오늘 시그널 있음 → 스킵
# ---------------------------------------------------------------------------

def test_characterize_theme_group_carry_ac003_peer_already_signaled_skipped(db):
    """AC-003: 피어에 오늘 시그널 이미 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_theme_group_carry_forward

    anchor = _make_stock(db, "000010", "앵커주")
    peer = _make_stock(db, "000020", "피어")
    _make_theme_group(db, "기존시그널그룹", anchor.id, [anchor.id, peer.id])
    _make_signal_today(db, peer.id)

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(8.0),
    ):
        signals = detect_theme_group_carry_forward(db, cfg)

    # peer는 이미 시그널이 있으므로 생성 안 됨
    peer_signals = [s for s in signals if s.stock_id == peer.id]
    assert len(peer_signals) == 0


# ---------------------------------------------------------------------------
# AC-004: anchor_stock_id=NULL → 그룹 스킵
# ---------------------------------------------------------------------------

def test_characterize_theme_group_carry_ac004_null_anchor_skipped(db):
    """AC-004: anchor_stock_id=NULL 그룹 → 스킵, 시그널 없음."""
    from app.services.surge_detector import detect_theme_group_carry_forward

    peer = _make_stock(db, "000010", "피어주")
    _make_theme_group(db, "앵커없는그룹", None, [peer.id])  # anchor_stock_id=None

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=_mock_price(10.0),
    ):
        signals = detect_theme_group_carry_forward(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-005: 내부 예외 → 파이프라인 보존 (빈 리스트 반환)
# ---------------------------------------------------------------------------

def test_characterize_theme_group_carry_ac005_exception_pipeline_intact(db):
    """AC-005: 내부 예외 → 빈 리스트 반환, 파이프라인 보존."""
    from app.services.surge_detector import detect_theme_group_carry_forward

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=RuntimeError("네트워크 오류"),
    ):
        signals = detect_theme_group_carry_forward(db, cfg)

    assert isinstance(signals, list)
