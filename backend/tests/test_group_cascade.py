"""SPEC-AI-027: 대기업 그룹 계열사 테마캐리 탐지기 테스트.

AC-001 ~ AC-010 전체 검증.
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

def _make_sector(db: Session) -> "Sector":  # noqa: F821
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
    name: str,
    market_cap: int | None = 10000,
) -> "Stock":  # noqa: F821
    from app.models.stock import Stock
    sector = _make_sector(db)
    stock = Stock(
        stock_code=stock_code,
        name=name,
        sector_id=sector.id,
        market_cap=market_cap,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_signal_today(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
) -> "FundSignal":  # noqa: F821
    from app.models.fund_signal import FundSignal
    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.5,
        reasoning="기존 시그널",
        signal_type=signal_type,
        paper_executed=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(signal)
    db.flush()
    return signal


def _make_surge_result(stock_code: str, name: str, surge_score: float) -> dict:
    return {
        "stock_code": stock_code,
        "name": name,
        "surge_score": surge_score,
        "active_detectors": [],
    }


def _make_config(**kwargs):
    from app.surge_config.surge_settings import GroupCascadeConfig
    return GroupCascadeConfig(**kwargs)


# ---------------------------------------------------------------------------
# AC-001: LG(003550) surge_prob=0.80>=0.70, 계열사 3개 → 시그널 3건
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac001_flagship_prob_cascade_signals(db):
    """AC-001: LG(003550) surge_prob=0.80>=0.70, 계열사 3개 당일 시그널 없음 → 3건 시그널.

    confidence = round(0.80 * 0.7, 4) = 0.56
    surge_basis = ["group_cascade"]
    flagship_stock_code = "003550"
    paper_executed = True
    """
    from app.services.surge_detector import detect_group_cascade_signals

    # 대장주: LG (시총>=50000)
    _flagship = _make_stock(db, "003550", "LG", market_cap=600000)
    # 계열사 3개 (시총>=1000)
    _aff1 = _make_stock(db, "066570", "LG전자", market_cap=100000)
    _aff2 = _make_stock(db, "051910", "LG화학", market_cap=200000)
    _aff3 = _make_stock(db, "011070", "LG이노텍", market_cap=30000)

    surge_results = [_make_surge_result("003550", "LG", 0.80)]
    cfg = _make_config()

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    # 계열사 3개 → 시그널 3건
    assert len(signals) == 3

    for sig in signals:
        assert sig.signal_type == "surge_candidate"
        assert sig.signal == "buy"
        assert sig.paper_executed is True

        meta = json.loads(sig.surge_metadata or "{}")
        assert "group_cascade" in meta.get("surge_basis", [])
        assert meta.get("flagship_stock_code") == "003550"

    # confidence = round(0.80 * 0.7, 4) = 0.56
    confidences = [sig.confidence for sig in signals]
    for c in confidences:
        assert abs(c - 0.56) < 0.0001


# ---------------------------------------------------------------------------
# AC-002: 삼성전기 intraday=23.73%>=12.0 AND 시총>=50000 → flagship 인정
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac002_intraday_flagship(db):
    """AC-002: surge_prob=0.40(<0.70), intraday=23.73%>=12.0 AND 시총>=50000 → flagship 인정."""
    from app.services.surge_detector import detect_group_cascade_signals

    # 삼성전기 (대장주, 시총>=50000)
    _flagship = _make_stock(db, "009150", "삼성전기", market_cap=80000)
    # 계열사 (시총>=1000)
    _aff1 = _make_stock(db, "005930", "삼성전자", market_cap=3000000)

    surge_results = [_make_surge_result("009150", "삼성전기", 0.40)]
    cfg = _make_config()

    # intraday 변동률 23.73% 모킹
    with patch(
        "app.services.surge_detector._fetch_intraday_change_for_cascade",
        return_value=23.73,
    ):
        signals = detect_group_cascade_signals(db, surge_results, cfg)

    # "삼성" 접두사 계열사가 1개 이상 있어야 함 (삼성전자)
    assert len(signals) >= 1
    for sig in signals:
        meta = json.loads(sig.surge_metadata or "{}")
        assert "group_cascade" in meta.get("surge_basis", [])
        assert meta.get("flagship_stock_code") == "009150"


# ---------------------------------------------------------------------------
# AC-003: intraday=23% but market_cap=NULL → flagship 제외, 시그널 0건
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac003_null_market_cap_excluded(db):
    """AC-003: market_cap=NULL → flagship 제외, 시그널 0건, 예외 없음."""
    from app.services.surge_detector import detect_group_cascade_signals

    # market_cap=None 대장주
    _flagship = _make_stock(db, "009150", "삼성전기", market_cap=None)
    _aff1 = _make_stock(db, "005930", "삼성전자", market_cap=3000000)

    surge_results = [_make_surge_result("009150", "삼성전기", 0.40)]
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_intraday_change_for_cascade",
        return_value=23.73,
    ):
        signals = detect_group_cascade_signals(db, surge_results, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# AC-004: 두산 flagship, 계열사 5개 → 상위 3개만 (max_cascade_per_flagship=3)
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac004_max_cascade_per_flagship(db):
    """AC-004: 계열사 5개 매칭 → max_cascade_per_flagship=3으로 상위 3개만."""
    from app.services.surge_detector import detect_group_cascade_signals

    _flagship = _make_stock(db, "000150", "두산", market_cap=200000)
    # 계열사 5개 (시총 내림차순)
    _make_stock(db, "034020", "두산에너빌리티", market_cap=50000)
    _make_stock(db, "042670", "두산밥캣", market_cap=40000)
    _make_stock(db, "241560", "두산로보틱스", market_cap=30000)
    _make_stock(db, "000155", "두산우", market_cap=20000)
    _make_stock(db, "011160", "두산퓨얼셀", market_cap=10000)

    surge_results = [_make_surge_result("000150", "두산", 0.80)]
    cfg = _make_config()

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    # max_cascade_per_flagship=3 → 최대 3건
    assert len(signals) <= 3
    assert len(signals) > 0


# ---------------------------------------------------------------------------
# AC-005: 접두사 1자(min_prefix_len=2 미달) 또는 매칭 0개 → 스킵, 0건
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac005_prefix_too_short_or_no_match(db):
    """AC-005: 대장주 접두사 1자(min_prefix_len=2 미달) 또는 매칭 계열사 0개 → 0건."""
    from app.services.surge_detector import detect_group_cascade_signals

    # 이름이 한 글자인 종목 (접두사 min_prefix_len=2 미달)
    _flagship = _make_stock(db, "000010", "가", market_cap=200000)
    _make_stock(db, "000020", "가나다라", market_cap=10000)

    surge_results = [_make_surge_result("000010", "가", 0.80)]
    cfg = _make_config()  # min_prefix_len=2

    signals = detect_group_cascade_signals(db, surge_results, cfg)
    assert signals == []


def test_characterize_group_cascade_ac005b_no_matching_affiliate(db):
    """AC-005b: 매칭 계열사 0개 → 0건."""
    from app.services.surge_detector import detect_group_cascade_signals

    # 대장주: "유일무이" 접두사가 다른 종목에 없음
    _flagship = _make_stock(db, "000010", "유일무이전자", market_cap=200000)
    _make_stock(db, "000020", "삼성전자", market_cap=3000000)

    surge_results = [_make_surge_result("000010", "유일무이전자", 0.80)]
    cfg = _make_config()

    signals = detect_group_cascade_signals(db, surge_results, cfg)
    assert signals == []


# ---------------------------------------------------------------------------
# AC-006: 계열사 "LG전자"에 당일 surge_candidate 이미 존재 → 해당 후보 스킵
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac006_existing_surge_candidate_skipped(db):
    """AC-006: 계열사에 당일 surge_candidate 이미 존재 → 해당 후보 스킵."""
    from app.services.surge_detector import detect_group_cascade_signals

    _flagship = _make_stock(db, "003550", "LG", market_cap=600000)
    aff1 = _make_stock(db, "066570", "LG전자", market_cap=100000)
    _aff2 = _make_stock(db, "051910", "LG화학", market_cap=200000)
    _aff3 = _make_stock(db, "011070", "LG이노텍", market_cap=30000)

    # LG전자에 오늘 surge_candidate 이미 있음
    _make_signal_today(db, aff1.id, signal_type="surge_candidate")

    surge_results = [_make_surge_result("003550", "LG", 0.80)]
    cfg = _make_config()

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    # LG전자 스킵 → 2건만 생성 (LG화학, LG이노텍)
    assert len(signals) == 2
    signal_stock_ids = {sig.stock_id for sig in signals}
    assert aff1.id not in signal_stock_ids


# ---------------------------------------------------------------------------
# AC-007: 계열사 "LG화학"에 당일 theme_propagation 시그널 존재 → 해당 후보 스킵
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac007_existing_theme_propagation_skipped(db):
    """AC-007: 계열사에 당일 theme_propagation 시그널 → 해당 후보 스킵."""
    from app.services.surge_detector import detect_group_cascade_signals

    _flagship = _make_stock(db, "003550", "LG", market_cap=600000)
    _aff1 = _make_stock(db, "066570", "LG전자", market_cap=100000)
    aff2 = _make_stock(db, "051910", "LG화학", market_cap=200000)
    _aff3 = _make_stock(db, "011070", "LG이노텍", market_cap=30000)

    # LG화학에 오늘 theme_propagation 시그널
    _make_signal_today(db, aff2.id, signal_type="theme_propagation")

    surge_results = [_make_surge_result("003550", "LG", 0.80)]
    cfg = _make_config()

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    # LG화학 스킵 → 2건만 생성
    assert len(signals) == 2
    signal_stock_ids = {sig.stock_id for sig in signals}
    assert aff2.id not in signal_stock_ids


# ---------------------------------------------------------------------------
# AC-008: 동일 계열사를 flagship A(0.75), B(0.90) 양쪽이 지목 → confidence=0.63 단 1건
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac008_dedup_use_highest_flagship_confidence(db):
    """AC-008: 동일 계열사를 두 flagship이 지목 → confidence=round(0.90*0.7,4)=0.63 단 1건.

    두 flagship이 같은 접두사를 공유하고 동일 계열사(LG전자)를 모두 지목할 때,
    더 높은 flagship(0.90) 기준 confidence로 단 1건만 생성한다.
    계열사 LG전자만 존재하도록 구성(max_cascade_per_flagship=3으로 충분히 설정).
    """
    from app.services.surge_detector import detect_group_cascade_signals

    # flagship 두 개는 서로를 cascade 후보로 포함하지 않도록
    # flagship_a, flagship_b 모두 시총이 크고, 계열사는 LG전자(시총 작음)만
    _flagship_a = _make_stock(db, "003550", "LG", market_cap=600000)
    _flagship_b = _make_stock(db, "003560", "LG우", market_cap=600000)
    aff1 = _make_stock(db, "066570", "LG전자", market_cap=5000)

    # 두 대장주 모두 LG 접두사 → LG전자가 양쪽에서 매칭
    # max_cascade_per_flagship=3 이므로 LG → [LG우(600000), LG전자(5000)] 최대 3개
    # LG우 → [LG(600000), LG전자(5000)] 최대 3개
    # 즉 LG전자는 두 flagship 모두에서 cascade 후보가 됨
    surge_results = [
        _make_surge_result("003550", "LG", 0.75),
        _make_surge_result("003560", "LG우", 0.90),
    ]
    cfg = _make_config(max_cascade_per_flagship=3)

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    # LG전자에 대해 단 1건만 생성
    lg_elec_signals = [s for s in signals if s.stock_id == aff1.id]
    assert len(lg_elec_signals) == 1

    sig = lg_elec_signals[0]
    # 높은 flagship(0.90) 기준으로 confidence = round(0.90 * 0.7, 4) = 0.63
    assert abs(sig.confidence - 0.63) < 0.0001


# ---------------------------------------------------------------------------
# AC-009: GroupCascadeConfig(enabled=False) → 빈 리스트, DB add 0회
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac009_disabled_returns_empty(db):
    """AC-009: enabled=False → 빈 리스트 반환, DB add 0회."""
    from app.services.surge_detector import detect_group_cascade_signals

    _flagship = _make_stock(db, "003550", "LG", market_cap=600000)
    _make_stock(db, "066570", "LG전자", market_cap=100000)

    surge_results = [_make_surge_result("003550", "LG", 0.80)]
    cfg = _make_config(enabled=False)

    signals = detect_group_cascade_signals(db, surge_results, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# AC-010: _run_coverage_expansion에서 예외 발생 시 기존 시그널 보존, logger.error 호출
# ---------------------------------------------------------------------------

def test_characterize_group_cascade_ac010_exception_in_coverage_expansion(db):
    """AC-010: detect_group_cascade_signals 예외 → 함수 raise 없음, logger.error 호출."""
    from unittest.mock import patch, MagicMock

    # 기존 시그널 사전 생성
    flagship = _make_stock(db, "003550", "LG", market_cap=600000)
    _make_stock(db, "066570", "LG전자", market_cap=100000)

    existing_signal = _make_signal_today(db, flagship.id, signal_type="surge_candidate")

    surge_results = [_make_surge_result("003550", "LG", 0.80)]

    mock_logger = MagicMock()

    # _run_coverage_expansion 내 group_cascade try 블록이 예외를 잡아야 함
    with patch(
        "app.services.surge_detector.detect_group_cascade_signals",
        side_effect=RuntimeError("테스트 예외"),
    ):
        with patch("app.services.fund_manager.logger", mock_logger):
            from app.services.fund_manager import _run_coverage_expansion
            # 예외가 raise되지 않아야 함
            try:
                _run_coverage_expansion(db, surge_results)
            except Exception as exc:
                pytest.fail(f"_run_coverage_expansion이 예외를 raise했습니다: {exc}")

    # logger.error가 "[group_cascade]..." 로 호출되었는지 확인
    error_calls = [
        call for call in mock_logger.error.call_args_list
        if "[group_cascade]" in str(call)
    ]
    assert len(error_calls) >= 1

    # 기존 시그널 보존 확인
    from app.models.fund_signal import FundSignal
    remaining = db.query(FundSignal).filter(FundSignal.id == existing_signal.id).first()
    assert remaining is not None
