"""SPEC-AI-024: 임원 자사주 직접 매수 공시 강화 테스트.

AC-001 ~ AC-005 전체 검증.
RED 단계: detect_insider_purchase_signals 미구현 상태에서 실패 확인.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

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
            CREATE TABLE IF NOT EXISTS disclosures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                corp_code VARCHAR(8) NOT NULL,
                corp_name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(6),
                stock_id INTEGER,
                report_name VARCHAR(500) NOT NULL,
                report_type VARCHAR(50),
                rcept_no VARCHAR(20) NOT NULL UNIQUE,
                rcept_dt VARCHAR(10) NOT NULL,
                url VARCHAR(500) NOT NULL,
                ai_summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                impact_score FLOAT,
                baseline_price INTEGER,
                reflected_pct FLOAT,
                unreflected_gap FLOAT,
                ripple_checked BOOLEAN DEFAULT 0,
                disclosed_at DATETIME,
                FOREIGN KEY (stock_id) REFERENCES stocks(id)
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
) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성."""
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
    )
    db.add(stock)
    db.flush()
    return stock


def _make_disclosure(
    db: Session,
    stock_id: int,
    report_name: str,
    rcept_dt: str | None = None,
    rcept_no: str = "20260101000001",
    report_type: str | None = None,
    created_at: datetime | None = None,
) -> "Disclosure":  # noqa: F821
    """테스트용 Disclosure 레코드 생성."""
    from app.models.disclosure import Disclosure

    if rcept_dt is None:
        rcept_dt = datetime.now(timezone.utc).strftime("%Y%m%d")

    disc = Disclosure(
        corp_code="00000001",
        corp_name="테스트기업",
        stock_id=stock_id,
        report_name=report_name,
        report_type=report_type,
        rcept_no=rcept_no,
        rcept_dt=rcept_dt,
        url="https://dart.fss.or.kr/test",
    )
    if created_at is not None:
        disc.created_at = created_at
    db.add(disc)
    db.flush()
    return disc


def _make_signal_today(db: Session, stock_id: int) -> "FundSignal":  # noqa: F821
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
    """InsiderPurchaseConfig 헬퍼."""
    from app.surge_config.surge_settings import InsiderPurchaseConfig
    return InsiderPurchaseConfig(**kwargs)


# ---------------------------------------------------------------------------
# AC-001: "임원" + "취득" 키워드 → surge_candidate 생성, confidence=0.45
# ---------------------------------------------------------------------------

def test_characterize_insider_purchase_ac001_acquisition_keyword_creates_signal(db):
    """AC-001: 임원취득 공시 → surge_candidate 시그널 생성, confidence=0.45."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000010", "임원매수주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == "surge_candidate"
    assert abs(sig.confidence - 0.45) < 0.001
    assert sig.paper_executed is True

    import json
    metadata = json.loads(sig.surge_metadata or "{}")
    assert "insider_purchase" in metadata.get("surge_basis", [])


# ---------------------------------------------------------------------------
# AC-002: 오늘 이미 surge_candidate 있는 종목 → 중복 생성 안 함
# ---------------------------------------------------------------------------

def test_characterize_insider_purchase_ac002_existing_today_signal_no_duplicate(db):
    """AC-002: 오늘 이미 surge_candidate 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000020", "기존시그널주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득)")
    _make_signal_today(db, stock.id)

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-003: "처분" 키워드 포함 → 생성 안 함 (매도 공시 차단)
# ---------------------------------------------------------------------------

def test_characterize_insider_purchase_ac003_disposal_keyword_blocked(db):
    """AC-003: 처분 키워드 포함 공시 → 시그널 생성 안 함."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000030", "임원매도주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의처분)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-004: enabled=False → 빈 리스트 반환
# ---------------------------------------------------------------------------

def test_characterize_insider_purchase_ac004_disabled_returns_empty(db):
    """AC-004: enabled=False → 즉시 빈 리스트 반환."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000040", "비활성주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득)")

    cfg = _make_config(enabled=False)
    signals = detect_insider_purchase_signals(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# AC-005: 내부 예외 → 파이프라인 보존 (빈 리스트 반환)
# ---------------------------------------------------------------------------

def test_characterize_insider_purchase_ac005_exception_pipeline_intact(db):
    """AC-005: 내부 예외 → 빈 리스트 반환, 파이프라인 보존."""
    from app.services.surge_detector import detect_insider_purchase_signals
    from unittest.mock import patch

    cfg = _make_config()
    with patch("app.services.surge_detector.Disclosure", side_effect=RuntimeError("DB 장애")):
        signals = detect_insider_purchase_signals(db, cfg)

    assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# BUGFIX 재현 테스트 (SPEC-AI-024 spec.md 대비 구현 불일치)
# ---------------------------------------------------------------------------

def test_bugfix_ai024_disclosure_id_is_set(db):
    """BUG: surge_metadata에 disclosure_id가 설정되지 않음 (REQ-AI024-001 추적성 요구).

    Given: 임원 취득 공시 1건
    When: detect_insider_purchase_signals 호출
    Then: 생성된 FundSignal.disclosure_id == 공시.id (기존 구현은 None으로 방치됨)
    """
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000210", "추적성주")
    disc = _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    assert signals[0].disclosure_id == disc.id


def test_bugfix_ai024_reasoning_has_spec_prefix(db):
    """BUG: reasoning에 SPEC이 요구하는 "[SPEC-AI-024 임원자사주매수]" 접두사가 없음."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000220", "접두사주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    assert signals[0].reasoning.startswith("[SPEC-AI-024 임원자사주매수]")


def test_bugfix_ai024_negative_keyword_maegak_blocked(db):
    """BUG: 음성 키워드에 "매각"이 누락되어 매각 공시가 차단되지 않음."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000230", "매각주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득 후 매각)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 0


def test_bugfix_ai024_negative_keyword_gamso_blocked(db):
    """BUG: 음성 키워드에 "감소"가 누락되어 지분감소 공시가 차단되지 않음."""
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000240", "감소주")
    _make_disclosure(db, stock.id, "임원ㆍ주요주주특정증권등소유상황보고서(취득 후 지분감소)")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 0


def test_bugfix_ai024_report_type_dot_variant_without_officer_in_name(db):
    """BUG(AC-006): report_name에 "임원"이 없어도 report_type의 중간점(·) 변형 매칭으로
    시그널이 생성되어야 하나, 기존 구현은 report_type을 전혀 조회하지 않아 누락됨.
    """
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000250", "타입매칭주")
    _make_disclosure(
        db,
        stock.id,
        report_name="보통주식 1,000주 취득",
        report_type="임원·주요주주특정증권등소유상황보고서",  # 중간점 · 변형
    )

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    assert signals[0].stock_id == stock.id


def test_bugfix_ai024_positive_match_is_order_independent(db):
    """BUG: 양성 매칭이 ilike("%임원%취득%")로 "임원"이 반드시 앞에 와야 하지만,
    SPEC은 순서 무관 AND 조건("임원" AND ("취득" OR "매수"))을 요구한다.
    """
    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000260", "순서무관주")
    # "취득"이 "임원"보다 앞에 위치 — 기존 ilike("%임원%취득%")는 매칭 실패
    _make_disclosure(db, stock.id, "주식 취득 관련 임원 보고")

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    assert signals[0].stock_id == stock.id


def test_bugfix_ai024_dedup_uses_most_recent_disclosure(db):
    """BUG: 종목당 1건 dedup 시 "가장 최근 공시" 기준이 적용되지 않음(순서 미보장)."""
    from datetime import timedelta

    from app.services.surge_detector import detect_insider_purchase_signals

    stock = _make_stock(db, "000270", "복수공시주")
    now = datetime.now(timezone.utc)

    old_disc = _make_disclosure(
        db,
        stock.id,
        "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득, 구건)",
        rcept_no="20260101000010",
        created_at=now - timedelta(hours=5),
    )
    new_disc = _make_disclosure(
        db,
        stock.id,
        "임원ㆍ주요주주특정증권등소유상황보고서(주식등의취득, 최신건)",
        rcept_no="20260101000011",
        created_at=now - timedelta(minutes=1),
    )

    cfg = _make_config()
    signals = detect_insider_purchase_signals(db, cfg)

    assert len(signals) == 1
    assert signals[0].disclosure_id == new_disc.id
    assert signals[0].disclosure_id != old_disc.id
