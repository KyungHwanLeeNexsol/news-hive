"""SPEC-AI-087: 시가총액/키워드 데이터 완전성 개선 테스트.

AC-087-001 ~ AC-087-009 전체 검증.

DDD ANALYZE-PRESERVE-IMPROVE:
- PRESERVE(M1): 5개 대상 지점(volume_anomaly 후보 쿼리, group_cascade 계열사 필터 + flagship
  배제, gap_up_runners 섹터 피어 필터, bollinger_squeeze 상위 N 쿼리, 시총 업데이트 페이지
  루프)의 현재(레거시) 출력을 특성화 테스트로 고정한다. AC-087-002/003/007/009는 이 PRESERVE
  안전망을 그대로 재사용하는 [HARD] 백워드 호환 가드다.
- IMPROVE(M2~M5): REQ-001/002(페이지 상한 확장), REQ-003~005(3개 탐지기 NULL 시총 opt-in
  편입), REQ-007/008(키워드 백필 스케줄링)을 구현하고 AC-087-001/004/005/006/008을 GREEN으로
  전환한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# FundSignal은 Disclosure 관계를 가지므로, mapper 초기화를 위해 Disclosure를 import해야 함
from app.models.disclosure import Disclosure  # noqa: F401


# ---------------------------------------------------------------------------
# ARRAY(Text) SQLite 호환 패치 — Stock.keywords 컬럼 테스트에 필요(REQ-007/008)
# ---------------------------------------------------------------------------

def _patch_array_for_sqlite() -> None:
    from sqlalchemy import ARRAY
    from sqlalchemy.ext.compiler import compiles

    @compiles(ARRAY, "sqlite")
    def _compile_array_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN202
        return "TEXT"

    _orig_bind = ARRAY.bind_processor
    _orig_result = ARRAY.result_processor

    def _sqlite_bind(self, dialect):  # noqa: ANN001, ANN202
        if dialect.name == "sqlite":
            def process(value):  # noqa: ANN001, ANN202
                return json.dumps(value) if value is not None else None
            return process
        return _orig_bind(self, dialect)

    def _sqlite_result(self, dialect, coltype):  # noqa: ANN001, ANN202
        if dialect.name == "sqlite":
            def process(value):  # noqa: ANN001, ANN202
                return json.loads(value) if value is not None else None
            return process
        return _orig_result(self, dialect, coltype)

    ARRAY.bind_processor = _sqlite_bind
    ARRAY.result_processor = _sqlite_result


_patch_array_for_sqlite()


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

def _make_sector(db: Session, name: str = "테스트섹터") -> "Sector":  # noqa: F821
    from app.models.sector import Sector
    sector = Sector(name=name, naver_code="001")
    db.add(sector)
    db.flush()
    return sector


def _make_stock(
    db: Session,
    stock_code: str,
    name: str = "테스트주식",
    market_cap: int | None = 1_000_000_000_000,
    sector_id: int | None = None,
) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성 헬퍼."""
    from app.models.sector import Sector
    from app.models.stock import Stock

    if sector_id is None:
        sector = db.query(Sector).first()
        if sector is None:
            sector = _make_sector(db)
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


def _make_fund_signal(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
    confidence: float = 0.80,
    created_at: datetime | None = None,
) -> "FundSignal":  # noqa: F821
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


def _make_surge_result(stock_code: str, name: str, surge_score: float) -> dict:
    return {
        "stock_code": stock_code,
        "name": name,
        "surge_score": surge_score,
        "active_detectors": [],
    }


def _make_fake_price_history(days: int, today_volume_ratio: float) -> list:
    """volume_anomaly 테스트용 가짜 가격 히스토리 생성."""
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


# ===========================================================================
# REQ-AI087-001/002: 시가총액 업데이트 페이지 상한 확장
# ===========================================================================

class TestReqAi087001PageLimitExpansion:
    """AC-087-001: 시장당 안전 상한 60페이지까지 순위 페이지를 계속 조회한다."""

    def test_constant_is_60(self) -> None:
        """_MARKET_CAP_UPDATE_MAX_PAGES 상수가 60으로 정의되어 있다."""
        from app.services.scheduler import _MARKET_CAP_UPDATE_MAX_PAGES

        assert _MARKET_CAP_UPDATE_MAX_PAGES == 60

    @patch("app.services.scheduler.SessionLocal")
    def test_ac087_001_page_11_data_reflected_in_cap_map(self, mock_session_cls) -> None:
        """AC-087-001 시나리오(1): 11페이지 이상의 데이터가 cap_map에 반영된다(기존 10페이지
        상한이면 진입조차 못 하던 상황).
        """
        from app.services.naver_finance import NaverStockItem
        from app.services.scheduler import _update_market_caps

        async def _fetch(market: str, page: int, page_size: int = 50):  # noqa: ANN001
            if page > 12:
                return [], 0
            item = NaverStockItem(
                stock_code=f"PAGE{page:03d}",
                name="테스트",
                market_cap=99000 + page,
                market=market,
            )
            return [item], 0

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_stock = MagicMock()
        mock_stock.stock_code = "PAGE011"
        mock_stock.market_cap = 1
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        with patch("app.services.naver_finance.fetch_naver_stock_list", new=_fetch):
            _update_market_caps()

        # 레거시(range(1, 11))라면 페이지 11은 절대 조회되지 않아 market_cap이 1로 남는다.
        assert mock_stock.market_cap == 99000 + 11

    @patch("app.services.scheduler.SessionLocal")
    def test_ac087_001_safety_cap_stops_exactly_at_60_pages(self, mock_session_cls) -> None:
        """AC-087-001 시나리오(2): API가 무한히 비-빈 페이지를 반환해도 정확히 60페이지에서
        종료된다(안전 상한 경계 고정).
        """
        from app.services.naver_finance import NaverStockItem
        from app.services.scheduler import _update_market_caps

        calls: dict[str, int] = {}

        async def _fetch(market: str, page: int, page_size: int = 50):  # noqa: ANN001
            calls[market] = page
            item = NaverStockItem(
                stock_code=f"{market[:1]}{page:04d}",
                name="테스트",
                market_cap=100,
                market=market,
            )
            return [item], 999999  # 절대 비지 않음 — 안전 상한이 없으면 무한 루프

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.services.naver_finance.fetch_naver_stock_list", new=_fetch):
            _update_market_caps()

        assert calls["KOSPI"] == 60
        assert calls["KOSDAQ"] == 60


class TestReqAi087002ExistingCoverageUnchanged:
    """AC-087-002 [HARD]: 페이지 상한 확장 후에도 기존 상위 500위 이내 종목의 market_cap 값과
    갱신 대상 범위(stocks 테이블 교집합)는 불변이다."""

    @patch("app.services.scheduler.SessionLocal")
    def test_ac087_002_top500_stock_value_and_calc_method_unchanged(self, mock_session_cls) -> None:
        from app.services.naver_finance import NaverStockItem
        from app.services.scheduler import _update_market_caps

        async def _fetch(market: str, page: int, page_size: int = 50):  # noqa: ANN001
            if page > 3:
                return [], 0
            item = NaverStockItem(
                stock_code="005930",
                name="삼성전자",
                market_cap=4_000_000 + page,
                market=market,
            )
            return [item], 0

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_stock = MagicMock()
        mock_stock.stock_code = "005930"
        mock_stock.market_cap = 1
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_stock]

        with patch("app.services.naver_finance.fetch_naver_stock_list", new=_fetch):
            _update_market_caps()

        # 계산 방식(마지막 처리 시장의 마지막 페이지 값을 그대로 반영) 불변 — 신규 삽입 없음
        assert mock_stock.market_cap == 4_000_000 + 3
        mock_db.add.assert_not_called()

    @patch("app.services.scheduler.SessionLocal")
    def test_ac087_002_update_scope_stays_within_stocks_table_intersection(self, mock_session_cls) -> None:
        """갱신 대상 종목 집합이 Stock.stock_code.in_(cap_map.keys()) 교집합 밖으로 확장되지 않는다."""
        from app.services.naver_finance import NaverStockItem
        from app.services.scheduler import _update_market_caps

        async def _fetch(market: str, page: int, page_size: int = 50):  # noqa: ANN001
            if page > 2:
                return [], 0
            item = NaverStockItem(stock_code=f"NEW{page:03d}", name="신규", market_cap=1000, market=market)
            return [item], 0

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        # stocks 테이블에 해당 종목이 전혀 없는 상황(추적 종목 아님) — 갱신 0건이어야 함
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.services.naver_finance.fetch_naver_stock_list", new=_fetch):
            _update_market_caps()

        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()  # updated=0 이므로 commit 스킵(기존 로직 유지)


# ===========================================================================
# REQ-AI087-003: volume_anomaly NULL 시총 후보 편입(floor quota, 기본 OFF)
# ===========================================================================

class TestReqAi087003VolumeAnomalyFloorQuota:
    """AC-087-003 [HARD] / AC-087-004."""

    def test_ac087_003_default_zero_excludes_null_market_cap(self, db: Session) -> None:
        """AC-087-003 [HARD]: null_cap_min_slots=0(기본값) → 기존 단일 조건 조회와 바이트 동등
        (NULL 시총 종목 미포함)."""
        from app.models.fund_signal import FundSignal
        from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
        from app.surge_config.surge_settings import VolumeAnomalyConfig

        null_stock = _make_stock(db, "900001", "NULL시총종목", market_cap=None)
        non_null_stock = _make_stock(db, "900002", "정상종목", market_cap=500)
        db.commit()

        config = VolumeAnomalyConfig(min_market_cap=300)
        assert config.null_cap_min_slots == 0

        fake_history = _make_fake_price_history(days=60, today_volume_ratio=6.0)
        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=fake_history,
        ):
            detect_volume_anomaly_dormant_stocks(db, config)

        signaled_ids = {
            row[0]
            for row in db.query(FundSignal.stock_id)
            .filter(FundSignal.signal_type == "volume_anomaly")
            .all()
        }
        assert null_stock.id not in signaled_ids
        assert non_null_stock.id in signaled_ids

    def test_ac087_004_floor_quota_includes_null_stocks_up_to_slots(self, db: Session) -> None:
        """AC-087-004: null_cap_min_slots=N(>0) → NULL 시총 종목이 최대 N개까지 후보풀에
        추가 편입된다."""
        from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
        from app.surge_config.surge_settings import VolumeAnomalyConfig

        null_codes = [f"n{i:04d}" for i in range(10)]
        for code in null_codes:
            _make_stock(db, code, f"NULL{code}", market_cap=None)
        non_null = _make_stock(db, "900099", "정상종목", market_cap=500)
        db.commit()

        config = VolumeAnomalyConfig(min_market_cap=300, null_cap_min_slots=5)

        fake_history = _make_fake_price_history(days=60, today_volume_ratio=6.0)
        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=fake_history,
        ) as mock_fetch:
            detect_volume_anomaly_dormant_stocks(db, config)

        fetched_codes = {call.args[0] for call in mock_fetch.call_args_list}
        null_fetched = fetched_codes & set(null_codes)
        assert len(null_fetched) == 5
        assert non_null.stock_code in fetched_codes

    def test_ac087_004_rotation_across_dates(self, db: Session) -> None:
        """AC-087-004: 서로 다른 날짜에 실행 시 NULL 서브셋이 로테이션 offset에 따라 달라진다."""
        from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
        from app.surge_config.surge_settings import VolumeAnomalyConfig

        null_codes = [f"r{i:04d}" for i in range(10)]
        for code in null_codes:
            _make_stock(db, code, f"NULL{code}", market_cap=None)
        db.commit()

        config = VolumeAnomalyConfig(min_market_cap=300, null_cap_min_slots=3)
        fake_history = _make_fake_price_history(days=60, today_volume_ratio=6.0)

        def _run_for_date(fixed_now: datetime) -> set[str]:
            with patch(
                "app.services.surge_detector.datetime",
                wraps=datetime,
                **{"now.return_value": fixed_now},
            ), patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=fake_history,
            ) as mock_fetch:
                detect_volume_anomaly_dormant_stocks(db, config)
            from app.models.fund_signal import FundSignal

            db.query(FundSignal).delete()
            db.commit()
            return {call.args[0] for call in mock_fetch.call_args_list} & set(null_codes)

        d1 = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)

        subset_d1 = _run_for_date(d1)
        subset_d2 = _run_for_date(d2)

        assert len(subset_d1) == 3
        assert len(subset_d2) == 3
        assert subset_d1 != subset_d2


# ===========================================================================
# REQ-AI087-004: group_cascade 계열사 후보 NULL 시총 편입(기존 상한 내)
# ===========================================================================

class TestReqAi087004GroupCascadeNullInclusion:
    """AC-087-005."""

    def test_characterize_default_off_excludes_null_market_cap(self, db: Session) -> None:
        """M1 특성화: cascade_include_null_market_cap 기본값(False) → NULL 시총 계열사 제외
        (레거시와 바이트 동등)."""
        from app.models.stock import Stock
        from app.services.surge_detector import detect_group_cascade_signals
        from app.surge_config.surge_settings import GroupCascadeConfig

        _make_stock(db, "000150", "두산", market_cap=200000)
        _make_stock(db, "034020", "두산에너빌리티", market_cap=50000)
        _make_stock(db, "000155", "두산우", market_cap=None)
        db.commit()

        surge_results = [_make_surge_result("000150", "두산", 0.80)]
        cfg = GroupCascadeConfig()
        assert cfg.cascade_include_null_market_cap is False

        signals = detect_group_cascade_signals(db, surge_results, cfg)
        cascaded_codes = {db.get(Stock, s.stock_id).stock_code for s in signals}
        assert "000155" not in cascaded_codes

    def test_ac087_005_null_included_within_existing_cap_lower_priority(self, db: Session) -> None:
        """AC-087-005: cascade_include_null_market_cap=True → 기존 max_cascade_per_flagship
        상한 내에서 NULL 시총 계열사가 non-null 종목보다 낮은 순위로 후보에 포함된다."""
        from app.models.stock import Stock
        from app.services.surge_detector import detect_group_cascade_signals
        from app.surge_config.surge_settings import GroupCascadeConfig

        _make_stock(db, "000150", "두산", market_cap=200000)
        _make_stock(db, "034020", "두산에너빌리티", market_cap=50000)  # non-null 1
        _make_stock(db, "042670", "두산밥캣", market_cap=40000)        # non-null 2
        _make_stock(db, "241560", "두산로보틱스", market_cap=None)     # null 1
        _make_stock(db, "000155", "두산우", market_cap=None)           # null 2
        _make_stock(db, "011160", "두산퓨얼셀", market_cap=None)       # null 3
        db.commit()

        surge_results = [_make_surge_result("000150", "두산", 0.80)]
        cfg = GroupCascadeConfig(cascade_include_null_market_cap=True)  # max_cascade_per_flagship=3(기본)

        signals = detect_group_cascade_signals(db, surge_results, cfg)

        assert len(signals) <= 3
        cascaded_codes = {db.get(Stock, s.stock_id).stock_code for s in signals}
        non_null_codes = {"034020", "042670"}
        null_codes = {"241560", "000155", "011160"}
        assert non_null_codes.issubset(cascaded_codes)
        assert len(cascaded_codes & null_codes) <= 1


# ===========================================================================
# REQ-AI087-005: gap_up_runners 섹터 피어 후보 NULL 시총 편입(기존 상한 내)
# ===========================================================================

class TestReqAi087005GapUpRunnersNullInclusion:
    """AC-087-006."""

    def test_characterize_default_off_excludes_null_market_cap(self, db: Session) -> None:
        """M1 특성화: runner_include_null_market_cap 기본값(False) → NULL 시총 피어 제외
        (레거시와 바이트 동등)."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        sector = _make_sector(db, "반도체")
        leader = _make_stock(db, "000010", "리더주식", market_cap=5_000_000_000_000, sector_id=sector.id)
        _make_stock(db, "000020", "NULL피어", market_cap=None, sector_id=sector.id)

        _make_fund_signal(db, leader.id, signal_type="surge_candidate", confidence=0.85)
        db.commit()

        cfg = GapUpRunnersConfig(min_leader_confidence=0.75, confidence_decay=0.7)
        assert cfg.runner_include_null_market_cap is False

        with patch("app.services.surge_detector._fetch_price_change_sync", return_value={"current_price": 50000}), \
             patch("app.services.surge_trading_service.get_open_position", return_value=None):
            signals = detect_gap_up_runners(db, cfg)

        # 섹터 피어가 NULL 시총 1개뿐이며 기본 필터에서 제외되므로 런너 0건
        assert len(signals) == 0

    def test_ac087_006_null_included_within_existing_limits_lower_priority(self, db: Session) -> None:
        """AC-087-006: runner_include_null_market_cap=True → 기존 섹터 피어 상한(.limit(5)) 및
        런너 선정([:2]) 내에서 NULL 시총 피어가 non-null 종목보다 낮은 순위로 포함될 수 있다."""
        from app.services.surge_detector import detect_gap_up_runners
        from app.surge_config.surge_settings import GapUpRunnersConfig

        sector = _make_sector(db, "바이오")
        leader = _make_stock(db, "000010", "리더주식", market_cap=5_000_000_000_000, sector_id=sector.id)
        non_null_peer = _make_stock(
            db, "000020", "정상피어", market_cap=3_000_000_000_000, sector_id=sector.id
        )
        for i in range(4):
            _make_stock(db, f"00003{i}", f"NULL피어{i}", market_cap=None, sector_id=sector.id)

        _make_fund_signal(db, leader.id, signal_type="surge_candidate", confidence=0.85)
        db.commit()

        cfg = GapUpRunnersConfig(
            min_leader_confidence=0.75, confidence_decay=0.7, runner_include_null_market_cap=True
        )

        with patch("app.services.surge_detector._fetch_price_change_sync", return_value={"current_price": 50000}), \
             patch("app.services.surge_trading_service.get_open_position", return_value=None):
            signals = detect_gap_up_runners(db, cfg)

        assert len(signals) == 2  # [:2] 상한 불변
        from app.models.stock import Stock
        runner_codes = {db.get(Stock, s.stock_id).stock_code for s in signals}
        assert non_null_peer.stock_code in runner_codes  # non-null이 항상 우선 포함


# ===========================================================================
# REQ-AI087-006: 편입 대상 경계 명시(회귀) [HARD]
# ===========================================================================

class TestReqAi087006RegressionBoundary:
    """AC-087-007 [HARD]."""

    def test_ac087_007_flagship_exclusion_unaffected(self, db: Session) -> None:
        """AC-087-007: cascade_include_null_market_cap=True여도 flagship NULL 시총 제외
        로직은 무변경(대장주 자체가 NULL 시총이면 여전히 제외)."""
        from app.services.surge_detector import detect_group_cascade_signals
        from app.surge_config.surge_settings import GroupCascadeConfig

        _make_stock(db, "009150", "삼성전기", market_cap=None)
        _make_stock(db, "005930", "삼성전자", market_cap=3000000)
        db.commit()

        surge_results = [_make_surge_result("009150", "삼성전기", 0.40)]
        cfg = GroupCascadeConfig(cascade_include_null_market_cap=True)

        with patch(
            "app.services.surge_detector._fetch_intraday_change_for_cascade",
            return_value=23.73,
        ):
            signals = detect_group_cascade_signals(db, surge_results, cfg)

        assert signals == []

    def test_ac087_007_bollinger_squeeze_top_n_query_unaffected(self, db: Session) -> None:
        """AC-087-007: bollinger_squeeze 상위 N 쿼리는 REQ-003~005와 무관하게
        market_cap.isnot(None) 필터를 그대로 유지한다."""
        from app.services.surge_detector import detect_bollinger_squeeze_signals
        from app.surge_config.surge_settings import BollingerSqueezeConfig

        null_stock = _make_stock(db, "700001", "NULL스퀴즈종목", market_cap=None)
        _make_stock(db, "700002", "정상스퀴즈종목", market_cap=100000)
        db.commit()

        b_cfg = BollingerSqueezeConfig(max_stocks_to_check=200)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=[],
        ) as mock_fetch:
            detect_bollinger_squeeze_signals(db, b_cfg)

        fetched_codes = {call.args[0] for call in mock_fetch.call_args_list}
        assert null_stock.stock_code not in fetched_codes


# ===========================================================================
# REQ-AI087-007/008: 키워드 백필 정기 스케줄링 + 백워드 호환
# ===========================================================================

class TestReqAi087007KeywordBackfillScheduling:
    """AC-087-008."""

    def test_ac087_008_backfill_job_registered_in_start_scheduler(self) -> None:
        """AC-087-008: backfill_stock_keywords가 start_scheduler()에 정기 잡으로 등록된다."""
        added_jobs: list[dict] = []

        def fake_add_job(func, trigger, **kwargs):  # noqa: ANN001, ANN202
            added_jobs.append({"id": kwargs.get("id"), "func": func})

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = fake_add_job
        mock_scheduler.running = False

        with patch("app.services.scheduler.scheduler", mock_scheduler), \
             patch("app.services.scheduler.SessionLocal"), \
             patch("app.services.scheduler.asyncio.run"):
            from app.services.scheduler import start_scheduler
            try:
                start_scheduler()
            except Exception:
                pass  # 잡 등록 이후 예외는 이 테스트의 관심사가 아님

        job_ids = [j["id"] for j in added_jobs]
        assert "keyword_backfill" in job_ids

    def test_ac087_008_backfill_scans_null_and_preserves_existing(self, db: Session) -> None:
        """AC-087-008: keywords=NULL 종목은 갱신 시도(스캔)되고, 기존 값이 있는 종목은
        불변이다(backfill_stock_keywords 기존 멱등 계약 그대로 소비)."""
        from app.services.keyword_tagging_service import backfill_stock_keywords

        stock_a = _make_stock(db, "800001", "종목A", market_cap=1000)
        stock_a.keywords = None
        stock_b = _make_stock(db, "800002", "종목B", market_cap=1000)
        stock_b.keywords = ["기존값"]
        db.commit()

        result = backfill_stock_keywords(db)

        db.refresh(stock_b)
        assert result.stocks_scanned == 2
        assert result.stocks_skipped_existing == 1
        assert stock_b.keywords == ["기존값"]


class TestReqAi087008BackwardCompat:
    """AC-087-009 [HARD]: 신규 설정 필드가 모두 기본값일 때 탐지 결과가 바이트 동등하다."""

    def test_new_config_fields_default_to_backward_compat_values(self) -> None:
        from app.surge_config.surge_settings import GapUpRunnersConfig, GroupCascadeConfig, VolumeAnomalyConfig

        assert VolumeAnomalyConfig().null_cap_min_slots == 0
        assert GroupCascadeConfig().cascade_include_null_market_cap is False
        assert GapUpRunnersConfig().runner_include_null_market_cap is False
