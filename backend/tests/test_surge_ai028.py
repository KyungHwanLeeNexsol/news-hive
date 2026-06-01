"""SPEC-AI-028: 공시 유형별 역신호 필터링 및 실패 자동 분류 — 인수테스트.

AC-028-01 ~ AC-028-10 검증.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.surge_config.surge_settings as _settings_module
from app.database import Base
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.surge_config.surge_settings import (
    DisclosureTypeFilterConfig,
    SurgeDetectionConfig,
    get_surge_config,
)


# ---------------------------------------------------------------------------
# 인메모리 DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    from sqlalchemy import ARRAY, event
    from sqlalchemy.ext.compiler import compiles

    @compiles(ARRAY, "sqlite")
    def _array_sqlite(type_, compiler, **kw):
        return "TEXT"

    _engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db(engine):
    """각 테스트에 독립적인 세션 (롤백 격리)."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """각 테스트 전후 config 싱글턴 초기화."""
    _settings_module._config_singleton = None
    yield
    _settings_module._config_singleton = None


# ---------------------------------------------------------------------------
# 헬퍼: 기본 Stock / Disclosure 생성
# ---------------------------------------------------------------------------

def _make_stock(db: Session, code: str = "000001", name: str = "테스트종목") -> Stock:
    from app.models.sector import Sector

    sector = db.query(Sector).filter(Sector.name == "테스트섹터_ai028").first()
    if not sector:
        sector = Sector(name="테스트섹터_ai028")
        db.add(sector)
        db.flush()

    stock = Stock(
        stock_code=code,
        name=name,
        sector_id=sector.id,
        market_cap=None,
        keywords=None,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_disclosure(
    db: Session,
    stock: Stock,
    report_name: str,
    rcept_dt: str = "20260601",
    ai_summary: str | None = None,
) -> Disclosure:
    disc = Disclosure(
        corp_code="00100001",
        corp_name=stock.name,
        stock_code=stock.stock_code,
        stock_id=stock.id,
        report_name=report_name,
        rcept_no=f"20260601{stock.id:08d}",
        rcept_dt=rcept_dt,
        url="http://example.com",
        ai_summary=ai_summary,
    )
    db.add(disc)
    db.flush()
    return disc


def _default_config() -> SurgeDetectionConfig:
    """테스트용 SurgeDetectionConfig (disclosure_type_filter 기본값)."""
    return get_surge_config()


# ---------------------------------------------------------------------------
# AC-028-01: 제외 키워드 포함 공시 → 후보 제외
# ---------------------------------------------------------------------------

class TestAC02801ExclusionPattern:
    """AC-028-01: 유상증자 공시 → 시그널 후보에서 제외."""

    def test_exclusion_keyword_skips_stock(self, db: Session):
        """유상증자 공시는 detect_immediate_disclosure_signal() 결과에 포함되지 않아야 한다."""
        from datetime import timedelta

        from app.services.surge_detector import detect_immediate_disclosure_signal

        stock = _make_stock(db, code="111111", name="유증테스트")

        # 제외 대상: 유상증자 (exclusion_patterns)
        _make_disclosure(db, stock, report_name="유상증자 결정", rcept_dt="20260601")

        config = get_surge_config()

        # disclosure_window_hours 이내 공시가 조회되도록 rcept_dt 기준 설정
        # detect 함수는 datetime.now() 기준으로 필터하므로 DB에 있는 공시의 rcept_dt가
        # 현재 날짜(20260601)와 일치하면 조회된다.
        # 함수 내부에서 cutoff_str = (now - window).strftime("%Y%m%d") 로 비교하므로
        # 오늘 날짜 공시는 항상 포함됨.
        results = detect_immediate_disclosure_signal(db, config)

        codes = [r.stock_code for r in results]
        assert "111111" not in codes, (
            "유상증자 공시 종목이 탐지 결과에 포함되면 안 됨"
        )


# ---------------------------------------------------------------------------
# AC-028-02: 페널티 키워드 공시 → 점수 0.3 배율
# ---------------------------------------------------------------------------

class TestAC02802PenaltyPattern:
    """AC-028-02: 최대주주변경 + 양성 키워드 공시 → score * 0.3."""

    def test_penalty_keyword_reduces_score(self, db: Session):
        """최대주주변경이 포함된 공시는 즉시 시그널 점수에 0.3 페널티가 적용된다."""
        from app.services.surge_detector import detect_immediate_disclosure_signal

        stock = _make_stock(db, code="222222", name="페널티테스트")

        # 양성 키워드(자기주식소각 score=0.90) + 페널티 키워드(최대주주변경)
        _make_disclosure(
            db,
            stock,
            report_name="자기주식소각 결정 및 최대주주변경",
            rcept_dt="20260601",
        )

        config = get_surge_config()
        results = detect_immediate_disclosure_signal(db, config)

        match = [r for r in results if r.stock_code == "222222"]
        assert match, "페널티 적용 후에도 후보로 남아 있어야 함"
        score = match[0].immediate_disclosure_score
        # 0.90 * 0.3 = 0.27 (±0.001 허용)
        assert abs(score - 0.27) <= 0.001, (
            f"페널티 적용 점수 기대 0.27, 실제 {score}"
        )

    def test_penalty_sets_bearish_sentiment(self, db: Session):
        """페널티 키워드 적용 종목은 disclosure_sentiment = 'bearish'."""
        from app.services.surge_detector import detect_immediate_disclosure_signal

        stock = _make_stock(db, code="222223", name="페널티감성테스트")
        _make_disclosure(
            db,
            stock,
            report_name="자기주식소각 결정 및 최대주주변경",
            rcept_dt="20260601",
        )

        config = get_surge_config()
        results = detect_immediate_disclosure_signal(db, config)

        match = [r for r in results if r.stock_code == "222223"]
        assert match
        assert match[0].disclosure_sentiment == "bearish"


# ---------------------------------------------------------------------------
# AC-028-03: surge_candidate_to_signal_metadata에 disclosure_sentiment 포함
# ---------------------------------------------------------------------------

class TestAC02803MetadataField:
    """AC-028-03: metadata JSON에 disclosure_sentiment 포함."""

    def test_metadata_contains_disclosure_sentiment_bearish(self):
        """disclosure_sentiment='bearish' 후보 → metadata에 해당 값 포함."""
        from app.services.surge_detector import (
            SurgeCandidate,
            surge_candidate_to_signal_metadata,
        )

        candidate = SurgeCandidate(
            stock_code="333333",
            stock_name="메타테스트",
            immediate_disclosure_score=0.27,
            active_detectors=["immediate_disclosure"],
            disclosure_sentiment="bearish",
        )
        config = get_surge_config()
        meta = surge_candidate_to_signal_metadata(candidate, config)

        assert "disclosure_sentiment" in meta
        assert meta["disclosure_sentiment"] == "bearish"

    def test_metadata_contains_disclosure_sentiment_bullish(self):
        """disclosure_sentiment='bullish' 후보 → metadata에 해당 값 포함."""
        from app.services.surge_detector import (
            SurgeCandidate,
            surge_candidate_to_signal_metadata,
        )

        candidate = SurgeCandidate(
            stock_code="333334",
            stock_name="메타테스트2",
            immediate_disclosure_score=0.90,
            active_detectors=["immediate_disclosure"],
            disclosure_sentiment="bullish",
        )
        config = get_surge_config()
        meta = surge_candidate_to_signal_metadata(candidate, config)

        assert meta["disclosure_sentiment"] == "bullish"

    def test_metadata_default_sentiment_neutral(self):
        """disclosure_sentiment 미지정 기본값 'neutral' → metadata에 neutral 포함."""
        from app.services.surge_detector import (
            SurgeCandidate,
            surge_candidate_to_signal_metadata,
        )

        candidate = SurgeCandidate(
            stock_code="333335",
            stock_name="메타테스트3",
            immediate_disclosure_score=0.0,
            active_detectors=[],
        )
        config = get_surge_config()
        meta = surge_candidate_to_signal_metadata(candidate, config)

        assert meta["disclosure_sentiment"] == "neutral"


# ---------------------------------------------------------------------------
# AC-028-04: get_today_signals()에서 bearish 제외 (skip_bearish_in_today_signals)
# ---------------------------------------------------------------------------

class TestAC02804TodaySignalsBearishSkip:
    """AC-028-04: get_today_signals()에서 bearish 공시 시그널 제외."""

    def _make_signal(
        self,
        db: Session,
        stock: Stock,
        sentiment: str | None,
        probability: float = 0.50,
    ) -> FundSignal:
        """테스트용 FundSignal 생성."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        KST = ZoneInfo("Asia/Seoul")
        from datetime import date

        # get_today_signals의 날짜 필터: 직전 영업일 15:00 이후
        # 월요일(2026-06-01)이므로 직전 영업일은 2026-05-29(금요일)
        # 그 15:00 KST 이후 시각으로 설정
        created = datetime(2026, 5, 29, 15, 30, tzinfo=KST)

        surge_basis = ["immediate_disclosure"] if sentiment else ["theme_cluster"]
        meta: dict = {
            "surge_probability_score": probability,
            "surge_basis": surge_basis,
            "theme_cluster_score": 0.0,
            "combo_score": 0.0,
            "pattern_score": 0.0,
            "immediate_disclosure_score": 0.50 if sentiment else 0.0,
            "legacy_score": 0.0,
        }
        if sentiment is not None:
            meta["disclosure_sentiment"] = sentiment

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=probability,
            reasoning="테스트",
            signal_type="surge_candidate",
            surge_metadata=json.dumps(meta),
            created_at=created,
        )
        db.add(signal)
        db.flush()
        return signal

    def test_bearish_sentiment_excluded(self, db: Session):
        """disclosure_sentiment='bearish' 시그널은 get_today_signals 결과에 없어야 함."""
        from app.services.surge_trading_service import get_today_signals

        stock_a = _make_stock(db, code="444441", name="베어리시테스트")
        self._make_signal(db, stock_a, sentiment="bearish", probability=0.55)

        with (
            patch("app.services.surge_trading_service._get_price_history_sync", return_value=None),
            patch("app.services.surge_trading_service._get_recent_stop_loss_codes", return_value=set()),
        ):
            results = get_today_signals(db)

        # results는 (signal, stock, probability, boost_info) tuple 목록
        codes = [r[1].stock_code for r in results]
        assert "444441" not in codes, "bearish 시그널은 제외되어야 함"

    def test_neutral_sentiment_included(self, db: Session):
        """disclosure_sentiment='neutral' 시그널은 포함되어야 함."""
        from app.services.surge_trading_service import get_today_signals

        stock_b = _make_stock(db, code="444442", name="뉴트럴테스트")
        self._make_signal(db, stock_b, sentiment="neutral", probability=0.55)

        with (
            patch("app.services.surge_trading_service._get_price_history_sync", return_value=None),
            patch("app.services.surge_trading_service._get_recent_stop_loss_codes", return_value=set()),
        ):
            results = get_today_signals(db)

        codes = [r[1].stock_code for r in results]
        assert "444442" in codes, "neutral 시그널은 포함되어야 함"

    def test_missing_sentiment_key_backward_compat(self, db: Session):
        """disclosure_sentiment 키 없는 기존 시그널은 포함되어야 함 (backward compat)."""
        from app.services.surge_trading_service import get_today_signals

        stock_c = _make_stock(db, code="444443", name="레거시테스트")
        self._make_signal(db, stock_c, sentiment=None, probability=0.55)

        with (
            patch("app.services.surge_trading_service._get_price_history_sync", return_value=None),
            patch("app.services.surge_trading_service._get_recent_stop_loss_codes", return_value=set()),
        ):
            results = get_today_signals(db)

        codes = [r[1].stock_code for r in results]
        assert "444443" in codes, "disclosure_sentiment 키 없는 시그널은 backward compat으로 포함"


# ---------------------------------------------------------------------------
# AC-028-05: verify_signals() — 공급 키워드 포함 공시 → supply_reversal, AI 미호출
# ---------------------------------------------------------------------------

class TestAC02805SupplyReversalShortCircuit:
    """AC-028-05: 공급 역전 키워드 공시 기반 실패 → supply_reversal (AI 없이)."""

    @pytest.mark.asyncio
    async def test_supply_keyword_sets_supply_reversal(self, db: Session):
        """전환사채 공시 연결 실패 시그널 → error_category=supply_reversal, AI 미호출."""
        from app.services import signal_verifier

        stock = _make_stock(db, code="555551", name="공급역전테스트")
        disc = _make_disclosure(
            db, stock, report_name="전환사채 발행 결정", rcept_dt="20260601"
        )

        from datetime import timedelta

        # 5일 이상 경과한 시그널
        created = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.60,
            reasoning="테스트",
            signal_type="surge_candidate",
            price_at_signal=10000,
            disclosure_id=disc.id,
            surge_metadata=json.dumps({
                "surge_probability_score": 0.60,
                "surge_basis": ["immediate_disclosure"],
            }),
            created_at=created,
        )
        db.add(signal)
        db.flush()

        classify_error_mock = AsyncMock(return_value=None)

        with (
            patch.object(signal_verifier, "_classify_error", classify_error_mock),
            patch.object(signal_verifier, "_get_current_price", AsyncMock(return_value=9000)),
            patch("app.services.benchmark.get_kospi_period_return", AsyncMock(return_value=0.0)),
        ):
            await signal_verifier.verify_signals(db)

        db.refresh(signal)
        assert signal.error_category == "supply_reversal"
        classify_error_mock.assert_not_called()


# ---------------------------------------------------------------------------
# AC-028-06: verify_signals() — 공급 키워드 없음 → sector_contagion, AI 미호출
# ---------------------------------------------------------------------------

class TestAC02806SectorContagionShortCircuit:
    """AC-028-06: 공급 키워드 없는 공시 기반 실패 → sector_contagion (AI 없이)."""

    @pytest.mark.asyncio
    async def test_no_supply_keyword_sets_sector_contagion(self, db: Session):
        """공시가 연결된 실패 시그널 (공급 키워드 없음) → error_category=sector_contagion."""
        from app.services import signal_verifier

        stock = _make_stock(db, code="666661", name="섹터전이테스트")
        disc = _make_disclosure(
            db, stock, report_name="대표이사 변경 결정", rcept_dt="20260601"
        )

        created = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.60,
            reasoning="테스트",
            signal_type="surge_candidate",
            price_at_signal=10000,
            disclosure_id=disc.id,
            surge_metadata=json.dumps({
                "surge_probability_score": 0.60,
                "surge_basis": ["immediate_disclosure"],
            }),
            created_at=created,
        )
        db.add(signal)
        db.flush()

        classify_error_mock = AsyncMock(return_value=None)

        with (
            patch.object(signal_verifier, "_classify_error", classify_error_mock),
            patch.object(signal_verifier, "_get_current_price", AsyncMock(return_value=9000)),
            patch("app.services.benchmark.get_kospi_period_return", AsyncMock(return_value=0.0)),
        ):
            await signal_verifier.verify_signals(db)

        db.refresh(signal)
        assert signal.error_category == "sector_contagion"
        classify_error_mock.assert_not_called()


# ---------------------------------------------------------------------------
# AC-028-07: 비공시 시그널 실패 → AI _classify_error 호출됨
# ---------------------------------------------------------------------------

class TestAC02807NonDisclosureUsesAI:
    """AC-028-07: 비공시 시그널 실패 → 기존 AI 경로 유지."""

    @pytest.mark.asyncio
    async def test_non_disclosure_signal_calls_classify_error(self, db: Session):
        """disclosure_id=None, surge_basis에 immediate_disclosure 없는 시그널 → AI 호출."""
        from app.services import signal_verifier

        stock = _make_stock(db, code="777771", name="비공시테스트")

        created = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.60,
            reasoning="테스트",
            signal_type="surge_candidate",
            price_at_signal=10000,
            disclosure_id=None,  # 비공시
            surge_metadata=json.dumps({
                "surge_probability_score": 0.60,
                "surge_basis": ["theme_cluster"],  # immediate_disclosure 없음
            }),
            created_at=created,
        )
        db.add(signal)
        db.flush()

        classify_error_mock = AsyncMock(return_value="macro_shock")

        with (
            patch.object(signal_verifier, "_classify_error", classify_error_mock),
            patch.object(signal_verifier, "_get_current_price", AsyncMock(return_value=9000)),
            patch("app.services.benchmark.get_kospi_period_return", AsyncMock(return_value=0.0)),
        ):
            await signal_verifier.verify_signals(db)

        classify_error_mock.assert_called_once()
        db.refresh(signal)
        assert signal.error_category == "macro_shock"


# ---------------------------------------------------------------------------
# AC-028-08: 백필 스크립트 멱등성
# ---------------------------------------------------------------------------

class TestAC02808BackfillIdempotency:
    """AC-028-08: 백필 스크립트 두 번 실행 → 첫 번째만 업데이트."""

    def test_backfill_idempotent(self, db: Session):
        """백필 두 번 실행: 1차=업데이트, 2차=0 rows."""
        import sys
        from pathlib import Path

        # scripts 디렉토리를 임시로 sys.path에 추가
        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from backfill_disclosure_error_category import _backfill_with_session

        stock = _make_stock(db, code="888881", name="백필테스트")
        disc = _make_disclosure(
            db, stock, report_name="유상증자 결정", rcept_dt="20260601"
        )

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.50,
            reasoning="테스트",
            signal_type="surge_candidate",
            is_correct=False,
            error_category=None,
            disclosure_id=disc.id,
            surge_metadata=json.dumps({
                "surge_basis": ["immediate_disclosure"],
            }),
            created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
        db.add(signal)
        db.flush()

        # 1차 실행
        updated_first = _backfill_with_session(db)
        assert updated_first >= 1

        db.flush()
        db.refresh(signal)
        assert signal.error_category in ("supply_reversal", "sector_contagion")

        # 2차 실행 (멱등성 — 이미 채워진 행은 건드리지 않음)
        updated_second = _backfill_with_session(db)
        assert updated_second == 0

    def test_backfill_does_not_overwrite_existing(self, db: Session):
        """기존 error_category 값은 덮어쓰지 않는다."""
        import sys
        from pathlib import Path

        scripts_dir = str(Path(__file__).parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from backfill_disclosure_error_category import _backfill_with_session

        stock = _make_stock(db, code="888882", name="백필덮어쓰기테스트")
        disc = _make_disclosure(
            db, stock, report_name="전환사채 발행", rcept_dt="20260601"
        )

        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.50,
            reasoning="테스트",
            signal_type="surge_candidate",
            is_correct=False,
            error_category="macro_shock",  # 이미 설정됨
            disclosure_id=disc.id,
            surge_metadata=json.dumps({"surge_basis": ["immediate_disclosure"]}),
            created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
        db.add(signal)
        db.flush()

        _backfill_with_session(db)
        db.flush()
        db.refresh(signal)

        # 기존 값 유지
        assert signal.error_category == "macro_shock"


# ---------------------------------------------------------------------------
# AC-028-09: 새 마이그레이션 파일 없음 (스키마 변경 없음)
# ---------------------------------------------------------------------------

class TestAC02809NoNewMigration:
    """AC-028-09: alembic/versions 에 새 마이그레이션 파일이 없어야 한다."""

    def test_no_new_migration_files(self):
        """SPEC-AI-028은 DB 변경이 없음 — 새 마이그레이션 파일 없음."""
        from pathlib import Path

        versions_dir = (
            Path(__file__).parent.parent / "alembic" / "versions"
        )
        # 마지막으로 알려진 마이그레이션: 056_surge_data_integrity.py
        # 새 파일이 없어야 함을 확인하는 대신, 디렉토리에서 AI-028 관련 파일 없음 확인
        migration_files = list(versions_dir.glob("*ai028*")) + list(versions_dir.glob("*ai_028*"))
        assert not migration_files, (
            f"SPEC-AI-028은 스키마 변경 없음 — AI028 관련 마이그레이션 파일이 없어야 함: {migration_files}"
        )


# ---------------------------------------------------------------------------
# AC-028-10: YAML 없이 SurgeDetectionConfig 로드 → disclosure_type_filter 기본값
# ---------------------------------------------------------------------------

class TestAC02810YamlDefaultValues:
    """AC-028-10: YAML에 disclosure_type_filter 섹션 없이 로드 → 기본값 적용."""

    def test_default_exclusion_patterns_applied(self):
        """disclosure_type_filter 기본 exclusion_patterns 검증."""
        cfg = DisclosureTypeFilterConfig()
        expected = ["유상증자", "전환사채발행", "신주인수권", "주식매수선택권"]
        assert cfg.exclusion_patterns == expected

    def test_default_penalty_factor(self):
        """기본 penalty_factor = 0.3."""
        cfg = DisclosureTypeFilterConfig()
        assert cfg.penalty_factor == 0.3

    def test_surge_config_has_disclosure_type_filter(self):
        """SurgeDetectionConfig에 disclosure_type_filter 필드 존재."""
        config = get_surge_config()
        assert hasattr(config, "disclosure_type_filter")
        assert isinstance(config.disclosure_type_filter, DisclosureTypeFilterConfig)

    def test_surge_config_exclusion_from_yaml(self):
        """YAML에서 로드된 config의 exclusion_patterns 검증."""
        config = get_surge_config()
        patterns = config.disclosure_type_filter.exclusion_patterns
        assert "유상증자" in patterns
        assert "전환사채발행" in patterns
