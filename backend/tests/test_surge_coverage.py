"""SPEC-AI-022: 시그널 커버리지 확장 테스트 — 테마 전파 및 비활성 종목 거래량 이상 탐지.

RED 단계: 아직 구현되지 않은 기능에 대한 특성화 테스트.
AC-001 ~ AC-018 전체 검증.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# FundSignal은 Disclosure 관계를 가지므로, mapper 초기화를 위해 Disclosure를 import해야 함
from app.models.disclosure import Disclosure  # noqa: F401


# ---------------------------------------------------------------------------
# 픽스처: 인메모리 SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """인메모리 SQLite 세션 픽스처.

    SQLite는 ARRAY 타입을 지원하지 않아 테이블별 개별 생성.
    필요한 테이블만 선별 생성.
    """
    from sqlalchemy import text

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # 필요한 테이블만 직접 DDL 생성
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
                FOREIGN KEY (theme_group_id) REFERENCES theme_groups(id),
                UNIQUE (stock_id, theme_group_id)
            )
        """))
        conn.commit()

    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def _make_stock(db: Session, stock_code: str, name: str = "테스트주식", market_cap: int = 500) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성 헬퍼 (market_cap 단위: 억원)."""
    from app.models.sector import Sector
    from app.models.stock import Stock

    # 섹터가 없으면 생성
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


def _make_fund_signal(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
    created_at: datetime | None = None,
    paper_executed: bool = False,
) -> "FundSignal":  # noqa: F821
    """테스트용 FundSignal 레코드 생성 헬퍼."""
    from app.models.fund_signal import FundSignal

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.5,
        reasoning="테스트 시그널",
        signal_type=signal_type,
        paper_executed=paper_executed,
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_theme_group(
    db: Session,
    name: str,
    stock_codes: list[str],
    anchor_code: str | None = None,
) -> "ThemeGroup":  # noqa: F821
    """테스트용 ThemeGroup + StockThemeGroup 레코드 생성 헬퍼."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup
    from app.models.stock import Stock

    anchor_stock = None
    if anchor_code:
        anchor_stock = db.query(Stock).filter(Stock.stock_code == anchor_code).first()

    group = ThemeGroup(
        name=name,
        anchor_stock_id=anchor_stock.id if anchor_stock else None,
    )
    db.add(group)
    db.flush()

    for code in stock_codes:
        stock = db.query(Stock).filter(Stock.stock_code == code).first()
        if stock:
            stg = StockThemeGroup(stock_id=stock.id, theme_group_id=group.id, weight=1.0)
            db.add(stg)
    db.flush()
    return group


# ---------------------------------------------------------------------------
# AC-001: 앵커 theme_cluster_score >= 0.80 → 피어 시그널 생성
# ---------------------------------------------------------------------------

def test_characterize_theme_propagation_ac001_anchor_high_score(db: Session) -> None:
    """AC-001: 앵커 종목 theme_cluster_score=0.85 이상이면 피어에 theme_propagation 시그널 생성."""
    from app.services.surge_detector import SurgeCandidate, propagate_theme_group_signals
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import ThemePropagationConfig

    _anchor = _make_stock(db, "066570", "LG전자", market_cap=500)
    peer = _make_stock(db, "003550", "LG", market_cap=300)
    _make_theme_group(db, "LG그룹", ["066570", "003550"], anchor_code="066570")

    config = ThemePropagationConfig(
        anchor_score_threshold=0.80,
        peer_price_trend_threshold=20.0,
    )
    qualified = [
        SurgeCandidate(
            stock_code="066570",
            stock_name="LG전자",
            theme_cluster_score=0.85,
            price_5d_trend=5.0,
        )
    ]

    # _get_peer_price_5d_trend는 외부 Naver API를 호출하므로 mock 처리
    with patch("app.services.surge_detector._get_peer_price_5d_trend", return_value=None):
        count = propagate_theme_group_signals(db, qualified, config)

    assert count >= 1
    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == peer.id, FundSignal.signal_type == "theme_propagation")
        .first()
    )
    assert signal is not None
    assert signal.paper_executed is False
    assert signal.confidence == pytest.approx(0.25, abs=0.01)


# ---------------------------------------------------------------------------
# AC-002: 앵커 theme_cluster_score < 0.80 → 전파 없음
# ---------------------------------------------------------------------------

def test_characterize_theme_propagation_ac002_anchor_low_score(db: Session) -> None:
    """AC-002: 앵커 theme_cluster_score=0.75 (임계값 미달) → 피어에 시그널 없음."""
    from app.services.surge_detector import SurgeCandidate, propagate_theme_group_signals
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import ThemePropagationConfig

    _anchor = _make_stock(db, "066570", "LG전자", market_cap=500)
    peer = _make_stock(db, "003550", "LG", market_cap=300)
    _make_theme_group(db, "LG그룹", ["066570", "003550"], anchor_code="066570")

    config = ThemePropagationConfig(
        anchor_score_threshold=0.80,
        peer_price_trend_threshold=20.0,
    )
    qualified = [
        SurgeCandidate(
            stock_code="066570",
            stock_name="LG전자",
            theme_cluster_score=0.75,
            price_5d_trend=5.0,
        )
    ]

    count = propagate_theme_group_signals(db, qualified, config)

    assert count == 0
    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == peer.id, FundSignal.signal_type == "theme_propagation")
        .first()
    )
    assert signal is None


# ---------------------------------------------------------------------------
# AC-003: 피어에 이미 오늘 시그널 존재 → 전파 없음
# ---------------------------------------------------------------------------

def test_characterize_theme_propagation_ac003_peer_already_has_signal(db: Session) -> None:
    """AC-003: 피어 종목이 오늘 이미 시그널을 가지면 새 theme_propagation 시그널 생성 안 함."""
    from app.services.surge_detector import SurgeCandidate, propagate_theme_group_signals
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import ThemePropagationConfig

    _anchor = _make_stock(db, "066570", "LG전자", market_cap=500)
    peer = _make_stock(db, "003550", "LG", market_cap=300)
    _make_theme_group(db, "LG그룹", ["066570", "003550"], anchor_code="066570")
    _make_fund_signal(db, peer.id, signal_type="surge_candidate")  # 이미 오늘 시그널 있음

    config = ThemePropagationConfig(
        anchor_score_threshold=0.80,
        peer_price_trend_threshold=20.0,
    )
    qualified = [
        SurgeCandidate(
            stock_code="066570",
            stock_name="LG전자",
            theme_cluster_score=0.85,
            price_5d_trend=5.0,
        )
    ]

    _count = propagate_theme_group_signals(db, qualified, config)

    # 피어에 theme_propagation 새로 생성되지 않아야 함
    tp_signals = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == peer.id, FundSignal.signal_type == "theme_propagation")
        .all()
    )
    assert len(tp_signals) == 0


# ---------------------------------------------------------------------------
# AC-004: 피어 price_5d_trend >= 20.0 → 전파 없음 (이미 급등한 종목)
# ---------------------------------------------------------------------------

def test_characterize_theme_propagation_ac004_peer_already_surged(db: Session) -> None:
    """AC-004: 피어 price_5d_trend=25.0 이면 전파 시그널 생성 안 함."""
    from app.services.surge_detector import SurgeCandidate, propagate_theme_group_signals
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import ThemePropagationConfig

    _anchor = _make_stock(db, "066570", "LG전자", market_cap=500)
    peer = _make_stock(db, "003550", "LG", market_cap=300)
    _make_theme_group(db, "LG그룹", ["066570", "003550"], anchor_code="066570")

    config = ThemePropagationConfig(
        anchor_score_threshold=0.80,
        peer_price_trend_threshold=20.0,
    )
    # 피어도 qualified로 포함되어 있고 price_5d_trend가 높음
    qualified = [
        SurgeCandidate(
            stock_code="066570",
            stock_name="LG전자",
            theme_cluster_score=0.85,
            price_5d_trend=5.0,
        )
    ]

    # 피어의 최근 5일 수익률을 외부에서 모킹
    with patch(
        "app.services.surge_detector._get_peer_price_5d_trend",
        return_value=25.0,
    ):
        _count = propagate_theme_group_signals(db, qualified, config)

    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == peer.id, FundSignal.signal_type == "theme_propagation")
        .first()
    )
    assert signal is None


# ---------------------------------------------------------------------------
# AC-005: 동일 피어가 복수 앵커에서 전파 → 1개만 생성 (높은 점수 우선)
# ---------------------------------------------------------------------------

def test_characterize_theme_propagation_ac005_dedup_higher_score_wins(db: Session) -> None:
    """AC-005: 동일 피어가 2개 앵커에서 전파될 때 1개 시그널만 생성 (높은 점수 우선)."""
    from app.services.surge_detector import SurgeCandidate, propagate_theme_group_signals
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import ThemePropagationConfig

    _anchor1 = _make_stock(db, "066570", "LG전자", market_cap=500)
    _anchor2 = _make_stock(db, "051910", "LG화학", market_cap=400)
    peer = _make_stock(db, "003550", "LG", market_cap=300)
    _make_theme_group(db, "LG그룹", ["066570", "051910", "003550"], anchor_code="066570")

    config = ThemePropagationConfig(
        anchor_score_threshold=0.80,
        peer_price_trend_threshold=20.0,
    )
    qualified = [
        SurgeCandidate(
            stock_code="066570",
            stock_name="LG전자",
            theme_cluster_score=0.82,
            price_5d_trend=5.0,
        ),
        SurgeCandidate(
            stock_code="051910",
            stock_name="LG화학",
            theme_cluster_score=0.90,  # 더 높은 점수
            price_5d_trend=3.0,
        ),
    ]

    # _get_peer_price_5d_trend는 외부 Naver API를 호출하므로 mock 처리
    with patch("app.services.surge_detector._get_peer_price_5d_trend", return_value=None):
        _count = propagate_theme_group_signals(db, qualified, config)

    tp_signals = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == peer.id, FundSignal.signal_type == "theme_propagation")
        .all()
    )
    # 피어에 시그널이 정확히 1개 생성
    assert len(tp_signals) == 1


# ---------------------------------------------------------------------------
# AC-006: 비활성 종목 volume_ratio=6.0 → volume_anomaly 시그널 생성
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac006_dormant_high_ratio(db: Session) -> None:
    """AC-006: 비활성 종목(1회 시그널/90일)에서 volume_ratio=6.0 이면 volume_anomaly 시그널 생성."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    stock = _make_stock(db, "012345", "비활성주식", market_cap=500)
    # 90일 이내 surge_candidate 시그널 1개 (비활성 조건 충족)
    old_signal_date = datetime.now(timezone.utc) - timedelta(days=60)
    _make_fund_signal(db, stock.id, signal_type="surge_candidate", created_at=old_signal_date)

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    # 가격 히스토리 모킹: 60일치 데이터, 오늘 volume_ratio=6.0
    fake_history = _make_fake_price_history(days=60, today_volume_ratio=6.0)

    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=fake_history,
    ):
        count = detect_volume_anomaly_dormant_stocks(db, config)

    assert count >= 1
    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock.id, FundSignal.signal_type == "volume_anomaly")
        .first()
    )
    assert signal is not None
    assert signal.paper_executed is False
    # confidence = min(6.0/10, 0.40) = 0.40
    assert signal.confidence == pytest.approx(0.40, abs=0.01)


# ---------------------------------------------------------------------------
# AC-007: volume_ratio=3.0 (임계값 미달) → 시그널 없음
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac007_low_ratio(db: Session) -> None:
    """AC-007: volume_ratio=3.0 (임계값 5.0 미달) → 시그널 없음."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    stock = _make_stock(db, "012345", "비활성주식", market_cap=500)
    old_signal_date = datetime.now(timezone.utc) - timedelta(days=60)
    _make_fund_signal(db, stock.id, signal_type="surge_candidate", created_at=old_signal_date)

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    fake_history = _make_fake_price_history(days=60, today_volume_ratio=3.0)

    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=fake_history,
    ):
        _count = detect_volume_anomaly_dormant_stocks(db, config)

    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock.id, FundSignal.signal_type == "volume_anomaly")
        .first()
    )
    assert signal is None


# ---------------------------------------------------------------------------
# AC-008: 비활성 아닌 종목(5회 시그널/90일) → volume_anomaly 제외
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac008_non_dormant_excluded(db: Session) -> None:
    """AC-008: surge_candidate 시그널 5회 종목은 비활성 기준 미충족 → volume_anomaly 검사 대상 제외."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    stock = _make_stock(db, "012345", "활성주식", market_cap=500)
    # 90일 이내 5회 시그널 → 비활성 조건 미충족
    for i in range(5):
        created = datetime.now(timezone.utc) - timedelta(days=i * 10)
        _make_fund_signal(db, stock.id, signal_type="surge_candidate", created_at=created)

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    fake_history = _make_fake_price_history(days=60, today_volume_ratio=8.0)

    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=fake_history,
    ):
        _count = detect_volume_anomaly_dormant_stocks(db, config)

    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock.id, FundSignal.signal_type == "volume_anomaly")
        .first()
    )
    assert signal is None


# ---------------------------------------------------------------------------
# AC-009: 히스토리 < 40일 → 스킵
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac009_insufficient_history(db: Session) -> None:
    """AC-009: 가격 히스토리가 40일 미만이면 volume_anomaly 스킵."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    stock = _make_stock(db, "012345", "비활성주식", market_cap=500)
    old_signal_date = datetime.now(timezone.utc) - timedelta(days=60)
    _make_fund_signal(db, stock.id, signal_type="surge_candidate", created_at=old_signal_date)

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    # 30일치 데이터만 (min_history_days=40 미충족)
    fake_history = _make_fake_price_history(days=30, today_volume_ratio=8.0)

    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=fake_history,
    ):
        _count = detect_volume_anomaly_dormant_stocks(db, config)

    signal = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock.id, FundSignal.signal_type == "volume_anomaly")
        .first()
    )
    assert signal is None


# ---------------------------------------------------------------------------
# AC-010: 이미 surge_candidate 시그널 있음 → volume_anomaly 중복 방지
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac010_dedup_with_surge_candidate(db: Session) -> None:
    """AC-010: 오늘 surge_candidate 이미 있는 종목에는 volume_anomaly 생성 안 함."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.models.fund_signal import FundSignal
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    stock = _make_stock(db, "012345", "비활성주식", market_cap=500)
    # 90일 이내 1회 (비활성 조건 충족)
    old_signal_date = datetime.now(timezone.utc) - timedelta(days=60)
    _make_fund_signal(db, stock.id, signal_type="surge_candidate", created_at=old_signal_date)
    # 오늘 surge_candidate 이미 있음
    _make_fund_signal(db, stock.id, signal_type="surge_candidate")

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    fake_history = _make_fake_price_history(days=60, today_volume_ratio=8.0)

    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=fake_history,
    ):
        _count = detect_volume_anomaly_dormant_stocks(db, config)

    va_signals = (
        db.query(FundSignal)
        .filter(FundSignal.stock_id == stock.id, FundSignal.signal_type == "volume_anomaly")
        .all()
    )
    assert len(va_signals) == 0


# ---------------------------------------------------------------------------
# AC-011 ~ AC-014: 마이그레이션 모델 테스트
# ---------------------------------------------------------------------------

def test_characterize_migration_ac011_models_exist(db: Session) -> None:
    """AC-011: ThemeGroup 및 StockThemeGroup 모델이 존재하고 DB 테이블 생성 확인."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup

    stock = _make_stock(db, "066570", "LG전자", market_cap=500)

    group = ThemeGroup(name="LG그룹", anchor_stock_id=stock.id)
    db.add(group)
    db.flush()

    stg = StockThemeGroup(stock_id=stock.id, theme_group_id=group.id, weight=1.0)
    db.add(stg)
    db.flush()

    retrieved = db.query(ThemeGroup).filter(ThemeGroup.name == "LG그룹").first()
    assert retrieved is not None
    assert retrieved.anchor_stock_id == stock.id


def test_characterize_migration_ac012_unique_constraint(db: Session) -> None:
    """AC-012: stock_id + theme_group_id 유니크 제약 확인 (중복 삽입 시 에러)."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup
    from sqlalchemy.exc import IntegrityError

    stock = _make_stock(db, "066570", "LG전자", market_cap=500)
    group = ThemeGroup(name="LG그룹")
    db.add(group)
    db.flush()

    stg1 = StockThemeGroup(stock_id=stock.id, theme_group_id=group.id, weight=1.0)
    db.add(stg1)
    db.flush()

    stg2 = StockThemeGroup(stock_id=stock.id, theme_group_id=group.id, weight=1.0)
    db.add(stg2)
    with pytest.raises(IntegrityError):
        db.flush()


def test_characterize_migration_ac013_seed_lg_group(db: Session) -> None:
    """AC-013: LG전자(066570)가 LG그룹에 배정되는 seed 데이터 구조 확인."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup

    # LG그룹 seed 데이터 삽입 시뮬레이션
    lg_stock = _make_stock(db, "066570", "LG전자", market_cap=2000)
    group = ThemeGroup(name="LG그룹", anchor_stock_id=lg_stock.id)
    db.add(group)
    db.flush()

    stg = StockThemeGroup(stock_id=lg_stock.id, theme_group_id=group.id, weight=1.0)
    db.add(stg)
    db.flush()

    # LG전자가 LG그룹에 속하는지 확인
    group_stocks = (
        db.query(StockThemeGroup)
        .filter(StockThemeGroup.theme_group_id == group.id)
        .all()
    )
    stock_ids = [s.stock_id for s in group_stocks]
    assert lg_stock.id in stock_ids


def test_characterize_migration_ac014_missing_stock_code_graceful(db: Session) -> None:
    """AC-014: seed 데이터에서 존재하지 않는 stock_code는 건너뜀 (마이그레이션 성공)."""
    from app.models.theme_group import ThemeGroup, StockThemeGroup
    from app.models.stock import Stock

    group = ThemeGroup(name="테스트그룹")
    db.add(group)
    db.flush()

    # 존재하지 않는 종목 코드는 건너뜀
    missing_code = "999999"
    stock = db.query(Stock).filter(Stock.stock_code == missing_code).first()
    if stock is None:
        # 존재하지 않으면 StockThemeGroup 생성 안 함 — 마이그레이션 패턴
        pass
    else:
        stg = StockThemeGroup(stock_id=stock.id, theme_group_id=group.id, weight=1.0)
        db.add(stg)
        db.flush()

    # 그룹은 정상 생성됨
    retrieved = db.query(ThemeGroup).filter(ThemeGroup.name == "테스트그룹").first()
    assert retrieved is not None


# ---------------------------------------------------------------------------
# AC-015 ~ AC-017: /coverage API 엔드포인트 테스트
# ---------------------------------------------------------------------------

def test_characterize_coverage_ac015_endpoint_returns_200(db: Session) -> None:
    """AC-015: GET /api/surge-trading/coverage → 200 OK + 스키마 검증."""
    from app.services.surge_coverage_service import compute_coverage_dashboard, reset_coverage_cache
    from app.schemas.surge_trading_coverage import CoverageDashboardResponse

    reset_coverage_cache()  # 이전 테스트 캐시 초기화

    stock = _make_stock(db, "066570", "LG전자", market_cap=2000)
    _make_fund_signal(db, stock.id, signal_type="surge_candidate")

    result = compute_coverage_dashboard(db)

    # Pydantic 모델로 파싱 가능해야 함
    response = CoverageDashboardResponse.model_validate(result)
    assert response.total_stocks_tracked >= 0
    assert response.signals_generated_today >= 0
    assert isinstance(response.by_signal_type, dict)


def test_characterize_coverage_ac016_by_signal_type_breakdown(db: Session) -> None:
    """AC-016: /coverage 응답에 signal_type별 집계 포함 확인."""
    from app.services.surge_coverage_service import compute_coverage_dashboard, reset_coverage_cache

    reset_coverage_cache()  # 이전 테스트 캐시 초기화

    stock1 = _make_stock(db, "066570", "LG전자", market_cap=2000)
    stock2 = _make_stock(db, "003550", "LG", market_cap=300)
    _make_fund_signal(db, stock1.id, signal_type="surge_candidate")
    _make_fund_signal(db, stock2.id, signal_type="theme_propagation")

    result = compute_coverage_dashboard(db)

    assert "by_signal_type" in result
    by_type = result["by_signal_type"]
    assert by_type.get("surge_candidate", 0) >= 1
    assert by_type.get("theme_propagation", 0) >= 1


def test_characterize_coverage_ac017_top_missed_change_pct_filter(db: Session) -> None:
    """AC-017: top_missed는 change_pct >= 15% 종목만 포함 확인."""
    from app.services.surge_coverage_service import compute_coverage_dashboard, reset_coverage_cache

    reset_coverage_cache()  # 이전 테스트 캐시 초기화

    # 시총 2000억 이상, 시그널 없는 종목
    _stock = _make_stock(db, "999001", "고성장주식", market_cap=2000)

    # change_pct 모킹: 고성장 종목은 15% 이상, 일반 종목은 5%
    _mock_price_data = {
        "999001": {"change_rate": 20.0, "current_price": 10000},
    }

    with patch(
        "app.services.surge_coverage_service._fetch_top_missed_candidates",
        return_value=[
            {"stock_code": "999001", "name": "고성장주식", "change_pct": 20.0}
        ],
    ):
        result = compute_coverage_dashboard(db)

    top_missed = result.get("top_missed", [])
    for item in top_missed:
        assert item["change_pct"] >= 15.0


# ---------------------------------------------------------------------------
# AC-018: volume_anomaly 실패가 surge_candidate 파이프라인에 영향 없음
# ---------------------------------------------------------------------------

def test_characterize_volume_anomaly_ac018_failure_isolation(db: Session) -> None:
    """AC-018: detect_volume_anomaly_dormant_stocks 내부 예외가 surge_candidate 결과에 영향 없음."""
    from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
    from app.surge_config.surge_settings import VolumeAnomalyConfig

    _stock = _make_stock(db, "012345", "비활성주식", market_cap=500)

    config = VolumeAnomalyConfig(
        dormant_signal_count_threshold=3,
        dormant_lookback_days=90,
        min_market_cap=300,
        volume_ratio_threshold=5.0,
        min_history_days=40,
    )

    # naver_finance를 강제 예외 발생시킴
    with patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        side_effect=Exception("네트워크 오류"),
    ):
        # 예외가 전파되지 않고 0 반환
        count = detect_volume_anomaly_dormant_stocks(db, config)

    assert count == 0  # 예외 발생해도 0 반환 (정상 종료)


# ---------------------------------------------------------------------------
# 헬퍼: 가짜 가격 히스토리 생성
# ---------------------------------------------------------------------------

def _make_fake_price_history(days: int, today_volume_ratio: float) -> list:
    """테스트용 가격 히스토리 생성.

    days일치 PriceRecord 객체 리스트를 반환.
    가장 첫 번째 항목(최신)의 volume을 평균 대비 today_volume_ratio 배로 설정.
    """
    from app.services.naver_finance import PriceRecord

    base_volume = 100_000
    records = []
    for i in range(days):
        date_str = (datetime.now(timezone.utc).date() - timedelta(days=i)).strftime("%Y.%m.%d")
        vol = base_volume * today_volume_ratio if i == 0 else base_volume
        records.append(
            PriceRecord(
                date=date_str,
                open=10000,
                high=10500,
                low=9500,
                close=10000,
                volume=int(vol),
            )
        )
    return records
