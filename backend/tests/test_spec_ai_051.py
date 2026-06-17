"""SPEC-AI-051: 볼린저 스퀴즈 탐지기, 공시 키워드 Tier 배수, 갭상승 런너 파이프라인 테스트.

T-010 AC-001 ~ AC-011 전체 검증.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS surge_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
    market_cap: int = 1_000_000_000_000,
    sector_id: int | None = None,
) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성 헬퍼."""
    from app.models.sector import Sector
    from app.models.stock import Stock

    if sector_id is None:
        sector = db.query(Sector).first()
        if sector is None:
            sector = Sector(name="테스트섹터", naver_code="001")
            db.add(sector)
            db.flush()
        sector_id = sector.id

    stock = Stock(
        stock_code=stock_code,
        name=name,
        sector_id=sector_id,
        market_cap=market_cap,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_sector(db: Session, name: str = "반도체") -> "Sector":  # noqa: F821
    """테스트용 Sector 레코드 생성 헬퍼."""
    from app.models.sector import Sector
    sector = Sector(name=name, naver_code="010")
    db.add(sector)
    db.flush()
    return sector


def _make_fund_signal(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
    confidence: float = 0.80,
    created_at: datetime | None = None,
) -> "FundSignal":  # noqa: F821
    """테스트용 FundSignal 레코드 생성 헬퍼."""
    from app.models.fund_signal import FundSignal

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=confidence,
        reasoning="테스트 시그널",
        signal_type=signal_type,
        paper_executed=True,
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_disclosure(**kwargs) -> MagicMock:
    """테스트용 Disclosure MagicMock 생성 헬퍼."""
    defaults = {
        "id": 1,
        "corp_code": "00000000",
        "corp_name": "테스트기업",
        "stock_code": "005930",
        "stock_id": 1,
        "report_name": "사업보고서",
        "report_type": "정기공시",
        "rcept_no": "202400000001",
        "rcept_dt": "20240101",
        "url": "https://dart.fss.or.kr/test/1",
        "ai_summary": None,
        "impact_score": None,
        "baseline_price": None,
        "reflected_pct": None,
        "unreflected_gap": None,
        "ripple_checked": False,
        "disclosed_at": None,
    }
    defaults.update(kwargs)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def _make_price_records(prices: list[float]) -> list[MagicMock]:
    """종가 목록을 PriceRecord MagicMock 목록으로 변환 (최신순)."""
    records = []
    for p in prices:
        r = MagicMock()
        r.close = p
        records.append(r)
    return records


def _make_squeeze_prices(squeeze: bool = True, n: int = 90) -> list[float]:
    """스퀴즈 또는 비스퀴즈 가격 시퀀스 생성 (최신순).

    squeeze=True: 최근 BW가 과거 60일 최솟값 이하 (스퀴즈)
    squeeze=False: 최근 BW가 과거 60일 최솟값 초과 (비스퀴즈)
    """
    if squeeze:
        # 과거(오래된)는 변동성 크게, 최근(최신)은 변동성 작게
        # 최신순이므로 prices[0]이 가장 최신
        # 최신 20일: 좁은 밴드 (100 ± 0.5)
        # 과거 40일: 넓은 밴드 (100 ± 5)
        recent = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(20)]
        mid = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(40)]
        old = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(n - 60)]
        return recent + mid + old
    else:
        # 최신 20일: 넓은 밴드, 과거는 좁은 밴드
        recent = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(20)]
        mid = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(40)]
        old = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(n - 60)]
        return recent + mid + old


# ===========================================================================
# Feature 1: 볼린저 밴드 스퀴즈 함수 단위 테스트
# ===========================================================================

class TestCalculateBollingerBandwidthSqueeze:
    """calculate_bollinger_bandwidth_squeeze 함수 단위 테스트."""

    def test_bollinger_bandwidth_squeeze_detects_squeeze(self):
        """AC-001: 최근 BW ≤ 60일 최솟값이면 squeeze=True."""
        from app.services.technical_indicators import calculate_bollinger_bandwidth_squeeze

        prices = _make_squeeze_prices(squeeze=True, n=90)
        result = calculate_bollinger_bandwidth_squeeze(prices, lookback=60)

        assert result is not None
        assert result["squeeze"] is True
        assert 0.0 <= result["squeeze_score"] <= 1.0
        assert result["current_bw"] > 0
        assert result["min_bw"] > 0

    def test_bollinger_bandwidth_squeeze_no_squeeze(self):
        """AC-002: 최근 BW > 60일 최솟값이면 squeeze=False."""
        from app.services.technical_indicators import calculate_bollinger_bandwidth_squeeze

        prices = _make_squeeze_prices(squeeze=False, n=90)
        result = calculate_bollinger_bandwidth_squeeze(prices, lookback=60)

        assert result is not None
        assert result["squeeze"] is False

    def test_bollinger_bandwidth_squeeze_insufficient_data(self):
        """AC-003: 데이터 부족(< lookback+19) 시 None 반환."""
        from app.services.technical_indicators import calculate_bollinger_bandwidth_squeeze

        # lookback=60 → 최소 78개 필요 (60+20-1=79)
        prices = [100.0] * 70  # 부족
        result = calculate_bollinger_bandwidth_squeeze(prices, lookback=60)

        assert result is None

    def test_bollinger_bandwidth_squeeze_score_clamped(self):
        """squeeze_score는 [0.0, 1.0] 범위 이내."""
        from app.services.technical_indicators import calculate_bollinger_bandwidth_squeeze

        prices = _make_squeeze_prices(squeeze=True, n=90)
        result = calculate_bollinger_bandwidth_squeeze(prices, lookback=60)

        assert result is not None
        assert 0.0 <= result["squeeze_score"] <= 1.0


# ===========================================================================
# Feature 2: 공시 키워드 Tier 배수 테스트
# ===========================================================================

class TestDisclosureImpactTierMultiplier:
    """score_disclosure_impact Tier 배수 적용 테스트."""

    def test_score_disclosure_impact_tier1_multiplier(self):
        """AC-004: Tier 1 키워드('FDA 승인') → 기본 점수 ×2.0."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        # 기본값 경로(기타공시=10점)에서 FDA 승인 키워드 → 10 * 2.0 = 20
        disclosure = _make_disclosure(
            report_type="기타공시",
            report_name="FDA 승인 획득 공시",
            ai_summary="당사 신약이 FDA 승인을 받았습니다.",
        )
        score = score_disclosure_impact(disclosure, market_cap_億=None)
        # 기본 10 * 2.0 = 20.0
        assert score == pytest.approx(20.0, abs=0.5)

    def test_score_disclosure_impact_tier2_multiplier(self):
        """AC-005: Tier 2 키워드('합병') → 기본 점수 ×1.5."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        disclosure = _make_disclosure(
            report_type="기업지배구조",
            report_name="주요 기업 합병 결정",
            ai_summary="",
        )
        # 기업지배구조 기본 10, M&A 키워드('합병') +20 → base=30, ×1.5=45
        score = score_disclosure_impact(disclosure, market_cap_億=None)
        assert score == pytest.approx(45.0, abs=0.5)

    def test_score_disclosure_impact_tier3_multiplier(self):
        """AC-006: Tier 3 키워드('신제품 출시') → 기본 점수 ×1.2."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        disclosure = _make_disclosure(
            report_type="주요사항보고",
            report_name="신제품 출시 관련 공시",
            ai_summary="",
        )
        # 주요사항보고 기본 20 * 1.2 = 24.0
        score = score_disclosure_impact(disclosure, market_cap_億=None)
        assert score == pytest.approx(24.0, abs=0.5)

    def test_score_disclosure_impact_routine_governance_no_multiplier(self):
        """AC-007: 루틴 거버넌스 공시 → Tier 배수 미적용, 5.0 고정."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        # '정기주주총회결과'는 루틴 거버넌스 → 5.0 반환, Tier 배수 무시
        disclosure = _make_disclosure(
            report_type="기업지배구조",
            report_name="정기주주총회결과 FDA 승인",  # Tier 1 키워드 포함해도 5.0
            ai_summary="",
        )
        score = score_disclosure_impact(disclosure, market_cap_億=None)
        assert score == 5.0

    def test_score_disclosure_impact_caps_at_100(self):
        """AC-008: Tier 1 배수 적용 후 100 초과 시 100.0으로 캡."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        # 실적변동 + AI 요약 80% 변화율 * Tier 1(2.0) = 160 → 100으로 캡
        disclosure = _make_disclosure(
            report_type="실적변동",
            report_name="FDA 승인 포함 실적 변동",
            ai_summary="매출이 80% 증가하였습니다.",
        )
        score = score_disclosure_impact(disclosure, market_cap_億=1000)
        assert score == 100.0

    def test_score_disclosure_impact_no_keyword_multiplier_is_1(self):
        """키워드 없으면 배수 1.0 (점수 변화 없음)."""
        from app.services.disclosure_impact_scorer import score_disclosure_impact

        disclosure = _make_disclosure(
            report_type="정기공시",
            report_name="사업보고서",
            ai_summary="",
        )
        score = score_disclosure_impact(disclosure, market_cap_億=None)
        # 정기공시 기본 10 * 1.0 = 10
        assert score == pytest.approx(10.0, abs=0.5)


# ===========================================================================
# Feature 3: 갭상승 런너 파이프라인 테스트
# ===========================================================================

class TestDetectGapUpRunners:
    """detect_gap_up_runners 함수 테스트 (SQLite 인메모리 DB)."""

    def test_detect_gap_up_runners_creates_signals(self, db: Session):
        """AC-009: 리더 시그널 존재 시 gap_up_runners FundSignal 생성."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        # 섹터 + 리더 종목 + 피어 2개 생성
        sector = _make_sector(db, "반도체")
        leader = _make_stock(db, "000010", "리더주식", market_cap=5_000_000_000_000, sector_id=sector.id)
        _make_stock(db, "000020", "피어주식1", market_cap=3_000_000_000_000, sector_id=sector.id)
        _make_stock(db, "000030", "피어주식2", market_cap=2_000_000_000_000, sector_id=sector.id)

        # 당일 리더 시그널 등록
        _make_fund_signal(db, leader.id, signal_type="surge_candidate", confidence=0.85)
        db.commit()

        cfg = GapUpRunnersConfig(min_leader_confidence=0.75, confidence_decay=0.7)

        with patch("app.services.surge_detector._fetch_price_change_sync", return_value={"current_price": 50000}), \
             patch("app.services.surge_detector.detect_gap_up_runners.__wrapped__" if False else
                   "app.services.surge_trading_service.get_open_position", return_value=None):
            signals = detect_gap_up_runners(db, cfg)

        assert len(signals) >= 1
        assert all(s.signal_type == "gap_up_runners" for s in signals)

    def test_detect_gap_up_runners_excludes_open_positions(self, db: Session):
        """AC-010: 오픈 포지션 보유 종목은 런너에서 제외."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        sector = _make_sector(db, "반도체")
        leader = _make_stock(db, "000010", "리더주식", market_cap=5_000_000_000_000, sector_id=sector.id)
        _make_stock(db, "000020", "피어주식1", market_cap=3_000_000_000_000, sector_id=sector.id)

        _make_fund_signal(db, leader.id, signal_type="surge_candidate", confidence=0.85)
        db.commit()

        cfg = GapUpRunnersConfig(min_leader_confidence=0.75, confidence_decay=0.7)

        # 모든 피어에 오픈 포지션이 있는 상황 모킹
        mock_position = MagicMock()
        mock_position.status = "open"

        with patch("app.services.surge_detector._fetch_price_change_sync", return_value={"current_price": 50000}), \
             patch("app.services.surge_trading_service.get_open_position", return_value=mock_position):
            signals = detect_gap_up_runners(db, cfg)

        # 오픈 포지션 있으므로 런너 0건
        assert len(signals) == 0

    def test_gap_up_runners_confidence_is_decayed(self, db: Session):
        """AC-011: 런너 confidence = leader.confidence * confidence_decay."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        sector = _make_sector(db, "바이오")
        leader = _make_stock(db, "000010", "리더주식", market_cap=5_000_000_000_000, sector_id=sector.id)
        _make_stock(db, "000020", "피어주식1", market_cap=3_000_000_000_000, sector_id=sector.id)

        _make_fund_signal(db, leader.id, signal_type="surge_candidate", confidence=0.80)
        db.commit()

        decay = 0.7
        cfg = GapUpRunnersConfig(min_leader_confidence=0.75, confidence_decay=decay)

        with patch("app.services.surge_detector._fetch_price_change_sync", return_value={"current_price": 50000}), \
             patch("app.services.surge_trading_service.get_open_position", return_value=None):
            signals = detect_gap_up_runners(db, cfg)

        assert len(signals) >= 1
        expected_confidence = round(0.80 * decay, 4)
        assert signals[0].confidence == pytest.approx(expected_confidence, abs=0.001)

    def test_detect_gap_up_runners_disabled_returns_empty(self, db: Session):
        """enabled=False 이면 빈 리스트 반환."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        cfg = GapUpRunnersConfig(enabled=False)
        signals = detect_gap_up_runners(db, cfg)
        assert signals == []

    def test_detect_gap_up_runners_no_leader_signals(self, db: Session):
        """리더 시그널 없으면 빈 리스트 반환."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        cfg = GapUpRunnersConfig(min_leader_confidence=0.75)
        signals = detect_gap_up_runners(db, cfg)
        assert signals == []
