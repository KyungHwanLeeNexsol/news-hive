"""SPEC-AI-088: same_day/near_limit_up_carry 시그널 사전 이동폭(pre_signal_change_pct) 계측 테스트.

AC-088-001 ~ AC-088-009 전체 검증.

DDD ANALYZE-PRESERVE-IMPROVE(재현-우선, CLAUDE.md Rule 4):
- PRESERVE: `_gather_surge_candidates`/`_create_immediate_surge_signal`/
  `detect_near_limit_up_carries` 이 세 대상 함수는 이 SPEC 이전에는 `pre_signal_change_pct`
  키를 어디에도 생성하지 않았다. AC-088-002/004(non-same_day/next_day 경로 키 미포함)는
  이 부재 상태가 IMPROVE 이후에도 그대로 유지되는 [HARD] 백워드 호환 가드다.
- IMPROVE: REQ-AI088-001~003(3개 경로의 pre_signal_change_pct 계산/저장)과
  REQ-AI088-004~005(공유 헬퍼 + API 노출)를 구현하고 AC-088-001/003/005/006/007/008을
  GREEN으로 전환한다. 신규 fetch 비용 0(mock 호출 횟수 assert로 고정).
- REQ-AI088-004/005는 `_is_same_day_event_horizon_signal`/`_is_near_limit_up_carry_signal`
  판별 로직 자체를 절대 변경하지 않는다 — 회귀 assert로 diff 0을 고정한다(AC-088-006/009).
"""

from __future__ import annotations

import json
from datetime import date as date_cls
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services.surge_detector import SurgeCandidate

KST = ZoneInfo("Asia/Seoul")


# ---------------------------------------------------------------------------
# 공통 픽스처 / 헬퍼
# ---------------------------------------------------------------------------

@pytest.fixture
def sector_ai088(db: Session) -> Sector:
    s = Sector(name="SPEC-AI-088테스트섹터")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def stock_ai088(db: Session, sector_ai088: Sector) -> Stock:
    stock = Stock(
        name="AI088테스트종목",
        stock_code="900088",
        sector_id=sector_ai088.id,
        market_cap=500,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_bypass_candidate(stock: Stock) -> SurgeCandidate:
    """품질 floor를 우회(strong_single_bypass)하는 mock 후보(test_surge_ai083 패턴 재사용).

    theme_cluster_score>=0.85 + combo_score>0.1 조합은 fund_manager.py 품질 floor 게이트를
    우회한다 — 본 테스트의 관심사는 품질 게이트가 아니라 pre_signal_change_pct 계측이므로,
    이미 검증된 bypass 조합을 차용해 후보가 반드시 FundSignal로 영속화되게 한다.
    """
    return SurgeCandidate(
        stock_code=stock.stock_code,
        stock_name=stock.name,
        theme_cluster_score=0.9,
        combo_score=0.9,
        active_detectors=["theme_cluster", "volume_news_combo"],
    )


def _t1_t2_dates() -> tuple[date_cls, date_cls]:
    """실행 시점 기준 예상 T-1/T-2 KST 거래일을 산출한다(detect_near_limit_up_carries 재사용)."""
    from app.services.surge_trading_service import _get_prev_business_day

    today = datetime.now(KST).date()
    t1 = _get_prev_business_day(today)
    t2 = _get_prev_business_day(t1)
    return t1, t2


def _history_for_near_limit(t1_close: int, t2_close: int) -> list:
    """T-1/T-2 종가를 지정한 최신순(newest-first) PriceRecord 픽스처를 생성한다."""
    from app.services.naver_finance import PriceRecord

    t1, t2 = _t1_t2_dates()
    return [
        PriceRecord(date=t1.strftime("%Y.%m.%d"), close=t1_close),
        PriceRecord(date=t2.strftime("%Y.%m.%d"), close=t2_close),
    ]


# ===========================================================================
# REQ-AI088-001: fund_manager._gather_surge_candidates same_day 경로 (AC-088-001/002)
# ===========================================================================

class TestGatherSurgeCandidatesPreSignalChangePct:
    """REQ-AI088-001: 장중 재스캔 same_day 경로 pre_signal_change_pct 계측."""

    @pytest.mark.asyncio
    async def test_ac088_001_same_day_new_signal_gets_pre_signal_change_pct(
        self, db: Session, stock_ai088: Stock
    ) -> None:
        """AC-088-001: same_day 지평 신규 시그널은 fetch_current_price_with_change_sync가
        이미 반환한 change_rate를 surge_metadata["pre_signal_change_pct"]에 저장하며,
        추가 네트워크 호출을 발생시키지 않는다(mock 호출 1회, 기존과 동일)."""
        from app.services.fund_manager import _gather_surge_candidates

        candidate = _make_bypass_candidate(stock_ai088)
        with (
            patch(
                "app.services.disclosure_impact_scorer._classify_disclosure_horizon",
                return_value="same_day",
            ),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                return_value=[candidate],
            ),
            patch(
                "app.services.naver_finance.fetch_current_price_with_change_sync",
                return_value={"current_price": 12540, "change_rate": 5.91},
            ) as mock_fetch,
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        signal = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_ai088.id,
                FundSignal.signal_type == "surge_candidate",
            )
            .first()
        )
        assert signal is not None, "bypass 후보는 FundSignal로 영속화되어야 한다"
        meta = json.loads(signal.surge_metadata)
        assert meta.get("horizon") == "same_day"
        assert meta.get("pre_signal_change_pct") == 5.91
        assert mock_fetch.call_count == 1, "REQ-001은 신규 네트워크 호출을 발생시키지 않아야 한다"

    @pytest.mark.asyncio
    async def test_ac088_002_non_same_day_no_pre_signal_change_pct_key(
        self, db: Session, stock_ai088: Stock
    ) -> None:
        """AC-088-002 [HARD]: _intraday_horizon != "same_day"(예: 15:20 정기 배치)이면
        change_rate가 조회되더라도 surge_metadata에 pre_signal_change_pct 키를
        포함시키지 않는다 — 기존 horizon 키 생략 패턴(SPEC-AI-083)과 동일하게 유지."""
        from app.services.fund_manager import _gather_surge_candidates

        candidate = _make_bypass_candidate(stock_ai088)
        with (
            patch(
                "app.services.disclosure_impact_scorer._classify_disclosure_horizon",
                return_value="next_day",
            ),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                return_value=[candidate],
            ),
            patch(
                "app.services.naver_finance.fetch_current_price_with_change_sync",
                return_value={"current_price": 12540, "change_rate": 5.91},
            ),
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        signal = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_ai088.id,
                FundSignal.signal_type == "surge_candidate",
            )
            .first()
        )
        assert signal is not None
        meta = json.loads(signal.surge_metadata)
        assert "pre_signal_change_pct" not in meta, (
            "non-same_day 지평에서는 change_rate 가용 여부와 무관하게 키를 생략해야 한다"
        )
        assert "horizon" not in meta

    @pytest.mark.asyncio
    async def test_ac088_001_fetch_returns_none_key_omitted(
        self, db: Session, stock_ai088: Stock
    ) -> None:
        """엣지 케이스: fetch_current_price_with_change_sync가 None(조회 실패)을 반환하면
        same_day 지평이라도 pre_signal_change_pct 키를 생략한다(기존 fail-safe 계승)."""
        from app.services.fund_manager import _gather_surge_candidates

        candidate = _make_bypass_candidate(stock_ai088)
        with (
            patch(
                "app.services.disclosure_impact_scorer._classify_disclosure_horizon",
                return_value="same_day",
            ),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                return_value=[candidate],
            ),
            patch(
                "app.services.naver_finance.fetch_current_price_with_change_sync",
                return_value=None,
            ),
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        signal = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_ai088.id,
                FundSignal.signal_type == "surge_candidate",
            )
            .first()
        )
        assert signal is not None
        meta = json.loads(signal.surge_metadata)
        assert "pre_signal_change_pct" not in meta
        assert meta.get("horizon") == "same_day"


# ===========================================================================
# REQ-AI088-002: disclosure_impact_scorer._create_immediate_surge_signal (AC-088-003/004)
# ===========================================================================

def _make_disclosure(**kwargs) -> MagicMock:
    """테스트용 Disclosure MagicMock 생성 헬퍼(기존 test_disclosure_impact_scorer_immediate_surge 패턴)."""
    defaults = {
        "id": 42,
        "corp_name": "SPEC-AI-088테스트기업",
        "stock_code": "005930",
        "stock_id": 7,
        "report_name": "단일판매ㆍ공급계약체결 500억원",
        "rcept_dt": "20260727",
        "baseline_price": 48000,
    }
    defaults.update(kwargs)
    d = MagicMock()
    for k, v in defaults.items():
        setattr(d, k, v)
    return d


def _make_immediate_db(existing=None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    return db


class TestCreateImmediateSurgeSignalPreSignalChangePct:
    """REQ-AI088-002: 즉시발화 same_day 경로 pre_signal_change_pct 계측."""

    @pytest.mark.asyncio
    async def test_ac088_003_same_day_horizon_stores_pre_signal_change_pct(self) -> None:
        """AC-088-003: horizon="same_day"일 때 fetch_current_price_with_change()로 교체된
        호출의 반환값에서 current_price는 기존과 동일 코드 경로로 price_at_signal에,
        change_rate는 신규로 surge_metadata["pre_signal_change_pct"]에 저장된다. Naver
        fetch 호출 횟수는 1회(교체 전과 동일, 1콜→1콜)로 유지된다."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure()
        db = _make_immediate_db()

        with (
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 12540, "change_rate": 5.91},
            ) as mock_fetch,
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=82.0, horizon="same_day"
            )

        assert signal is not None
        assert signal.price_at_signal == 12540, "current_price는 기존과 동일한 경로로 저장되어야 한다"
        meta = json.loads(signal.surge_metadata)
        assert meta.get("pre_signal_change_pct") == 5.91
        assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_ac088_004_next_day_horizon_no_pre_signal_change_pct_key(self) -> None:
        """AC-088-004: horizon="next_day"이면 surge_metadata에 pre_signal_change_pct
        키를 포함시키지 않는다(change_rate 가용 여부와 무관)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure()
        db = _make_immediate_db()

        with (
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 12540, "change_rate": 5.91},
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=82.0, horizon="next_day"
            )

        meta = json.loads(signal.surge_metadata)
        assert "pre_signal_change_pct" not in meta

    def test_ac088_003_fallback_endpoint_delta_documented(self) -> None:
        """AC-088-003 폴백 엔드포인트 델타(plan.md R-2, plan-auditor iteration 1 D2 지적 반영):
        REQ-002가 교체하는 fetch_current_price(구)의 모바일 폴백은 문서화된 폐기 엔드포인트
        (/integration)를, 교체 대상 fetch_current_price_with_change(신)의 모바일 폴백은
        수정된 (/price) 엔드포인트를 사용함을 소스 코드로 재확인한다 — 판정 로직과 무관한
        의도된 계측 정확도 개선(회귀 아님)."""
        import inspect

        from app.services import naver_finance

        old_src = inspect.getsource(naver_finance.fetch_current_price)
        new_src = inspect.getsource(naver_finance.fetch_current_price_with_change)
        assert "stock_code}/integration" in old_src, "구 함수는 폐기된 /integration 엔드포인트를 폴백으로 사용한다"
        assert "stock_code}/price" in new_src, "신 함수는 수정된 /price 엔드포인트를 폴백으로 사용한다"
        # new_src는 마이그레이션 이력을 설명하는 주석에서만 "/integration" 문자열을 언급한다
        # (실제 폴백 URL로는 사용하지 않음) — URL 리터럴로만 좁혀 확인한다.
        assert "stock_code}/integration" not in new_src, "신 함수는 폐기된 엔드포인트를 URL로 참조하지 않아야 한다"

    @pytest.mark.asyncio
    async def test_price_fetch_failure_falls_back_to_baseline_price_key_omitted(self) -> None:
        """엣지 케이스: fetch_current_price_with_change 예외 발생 시 기존과 동일하게
        disclosure.baseline_price로 폴백하고(price 폴백 의미 불변, plan.md R-2a),
        change_rate 자체가 없으므로 pre_signal_change_pct 키는 생략된다."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal

        disclosure = _make_disclosure(baseline_price=48000)
        db = _make_immediate_db()

        with (
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock, side_effect=Exception("네트워크 오류"),
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=90.0, horizon="same_day"
            )

        assert signal is not None
        assert signal.price_at_signal == 48000, "폴백 의미(baseline_price)는 변경되지 않아야 한다"
        meta = json.loads(signal.surge_metadata)
        assert "pre_signal_change_pct" not in meta

    @pytest.mark.asyncio
    async def test_oq5_marker_not_misidentified_after_change(self) -> None:
        """회귀: pre_signal_change_pct 추가 후에도 OQ-5 마커(즉시발화)가
        _is_near_limit_up_carry_signal에 오판되지 않아야 한다(SPEC-AI-080 불변)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal
        from app.services.surge_evaluation_service import _is_near_limit_up_carry_signal

        disclosure = _make_disclosure(report_name="흡수합병결정")
        db = _make_immediate_db()

        with (
            patch(
                "app.services.naver_finance.fetch_current_price_with_change",
                new_callable=AsyncMock,
                return_value={"current_price": 12540, "change_rate": 5.91},
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock, return_value={"volatility_level": "normal"},
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=70.0, horizon="same_day"
            )

        assert _is_near_limit_up_carry_signal(signal.surge_metadata) is False


# ===========================================================================
# REQ-AI088-003: surge_detector.detect_near_limit_up_carries 불변식 (AC-088-005)
# ===========================================================================

class TestNearLimitUpCarryPreSignalChangePct:
    """REQ-AI088-003: near_limit_up_carry 경로 pre_signal_change_pct 불변식(항상 0.0)."""

    def test_ac088_005_pre_signal_change_pct_is_always_zero(
        self, db: Session, make_stock
    ) -> None:
        """AC-088-005: price_at_signal==t1_close라는 기존 불변식(SPEC-AI-072/075)의
        직접적 결과로 surge_metadata["pre_signal_change_pct"]는 항상 정확히 0.0이며,
        추가 데이터 조회나 계산을 요구하지 않는다(기존 이력 조회 호출 횟수 불변)."""
        from app.services.surge_detector import detect_near_limit_up_carries
        from app.surge_config.surge_settings import NearLimitUpConfig

        make_stock(name="근접상한가주", stock_code="900190", market_cap=500)
        cfg = NearLimitUpConfig()

        # 10000 * 1.20 = 12000 → T-1 종가-대-종가 +20.0% (near_limit_up 밴드 15.0~29.99% 충족)
        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=_history_for_near_limit(12000, 10000),
        ) as mock_fetch:
            signals = detect_near_limit_up_carries(db, cfg)

        assert len(signals) == 1
        sig = signals[0]
        assert sig.price_at_signal == 12000
        meta = json.loads(sig.surge_metadata)
        assert meta.get("pre_signal_change_pct") == 0.0
        assert "near_limit_up_carry" in meta.get("surge_basis", [])
        # 기존 키 보존 확인(부가 전용 원칙)
        assert meta.get("yesterday_change_pct") == 20.0
        assert mock_fetch.call_count == 1, "REQ-003은 신규 fetch를 요구하지 않아야 한다(1콜 불변)"

    def test_ac088_005_zero_value_survives_json_round_trip(
        self, db: Session, make_stock
    ) -> None:
        """R-4: 0.0 리터럴은 JSON 직렬화(0 또는 0.0으로 표현 가능) 후 역직렬화해도
        수치 비교로 정확히 0.0과 동일하다."""
        from app.services.surge_detector import detect_near_limit_up_carries
        from app.surge_config.surge_settings import NearLimitUpConfig

        make_stock(name="라운드트립검증주", stock_code="900199", market_cap=500)
        cfg = NearLimitUpConfig()

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            return_value=_history_for_near_limit(11500, 10000),
        ):
            signals = detect_near_limit_up_carries(db, cfg)

        assert len(signals) == 1
        raw_json = signals[0].surge_metadata
        assert '"pre_signal_change_pct": 0.0' in raw_json or '"pre_signal_change_pct": 0' in raw_json
        meta = json.loads(raw_json)
        assert meta["pre_signal_change_pct"] == 0.0
        assert isinstance(meta["pre_signal_change_pct"], (int, float))


# ===========================================================================
# REQ-AI088-004: surge_trading._extract_pre_signal_change_pct 공유 헬퍼 (AC-088-006)
# ===========================================================================

class TestExtractPreSignalChangePctHelper:
    """REQ-AI088-004 [HARD]: 부가 전용 계약 — 하위 호환 안전 파싱 헬퍼."""

    def test_none_returns_none(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        assert _extract_pre_signal_change_pct(None) is None

    def test_empty_string_returns_none(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        assert _extract_pre_signal_change_pct("") is None

    def test_missing_key_returns_none(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"surge_basis": ["theme_cluster"]})
        assert _extract_pre_signal_change_pct(meta) is None

    def test_pre_spec_near_limit_up_carry_metadata_returns_none(self) -> None:
        """이 SPEC 이전에 생성된 near_limit_up_carry 레코드(신규 키 부재) — 백필 없음(Out of Scope)."""
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"surge_basis": ["near_limit_up_carry"], "near_limit_up_carry": True})
        assert _extract_pre_signal_change_pct(meta) is None

    def test_pre_spec_same_day_metadata_returns_none(self) -> None:
        """이 SPEC 이전에 생성된 same_day horizon 레코드(신규 키 부재)."""
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"horizon": "same_day"})
        assert _extract_pre_signal_change_pct(meta) is None

    def test_theme_news_carry_uncovered_path_returns_none(self) -> None:
        """§Out of Scope: detect_theme_news_carry가 생성한 same_day 시그널(미커버 경로)."""
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"horizon": "same_day", "theme_news_carry": True})
        assert _extract_pre_signal_change_pct(meta) is None

    def test_malformed_json_returns_none(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        assert _extract_pre_signal_change_pct("not json at all") is None

    def test_non_dict_json_returns_none(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        assert _extract_pre_signal_change_pct("[1, 2, 3]") is None

    def test_present_key_returns_value(self) -> None:
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"pre_signal_change_pct": 5.91})
        assert _extract_pre_signal_change_pct(meta) == 5.91

    def test_zero_value_returns_zero_not_none(self) -> None:
        """0.0은 falsy이지만 near_limit_up_carry 불변식 값(0.0)과 미탑재(None)를 구분해야 한다."""
        from app.routers.surge_trading import _extract_pre_signal_change_pct

        meta = json.dumps({"pre_signal_change_pct": 0.0})
        value = _extract_pre_signal_change_pct(meta)
        assert value == 0.0
        assert value is not None


class TestEvaluationPredicatesUnchangedByNewKey:
    """AC-088-006/009 [HARD]: 신규 키 추가가 기존 판별 함수 결과에 영향을 주지 않음(diff 0)."""

    @pytest.mark.parametrize(
        "meta_dict",
        [
            {"surge_basis": ["near_limit_up_carry"], "near_limit_up_carry": True},
            {"horizon": "same_day"},
            {"horizon": "next_day"},
            {"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8},
        ],
    )
    def test_is_near_limit_up_carry_signal_identical_with_and_without_new_key(
        self, meta_dict: dict
    ) -> None:
        from app.services.surge_evaluation_service import _is_near_limit_up_carry_signal

        without_key = json.dumps(meta_dict)
        with_key = json.dumps({**meta_dict, "pre_signal_change_pct": 0.0})
        assert _is_near_limit_up_carry_signal(without_key) == _is_near_limit_up_carry_signal(
            with_key
        )

    @pytest.mark.parametrize(
        "meta_dict",
        [
            {"surge_basis": ["near_limit_up_carry"], "near_limit_up_carry": True},
            {"horizon": "same_day"},
            {"horizon": "next_day"},
            {"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8},
        ],
    )
    def test_is_same_day_event_horizon_signal_identical_with_and_without_new_key(
        self, meta_dict: dict
    ) -> None:
        from app.services.surge_evaluation_service import _is_same_day_event_horizon_signal

        without_key = json.dumps(meta_dict)
        with_key = json.dumps({**meta_dict, "pre_signal_change_pct": 5.91})
        assert _is_same_day_event_horizon_signal(without_key) == _is_same_day_event_horizon_signal(
            with_key
        )

    def test_none_and_malformed_inputs_unaffected(self) -> None:
        """None/손상 JSON 입력에 대한 두 판별 함수의 기존 fail-safe 반환값(False)은 불변이다."""
        from app.services.surge_evaluation_service import (
            _is_near_limit_up_carry_signal,
            _is_same_day_event_horizon_signal,
        )

        for bad_input in (None, "", "not json", "[1,2,3]"):
            assert _is_near_limit_up_carry_signal(bad_input) is False
            assert _is_same_day_event_horizon_signal(bad_input) is False


# ===========================================================================
# REQ-AI088-005: surge_trading.py API 노출 (AC-088-007/008)
# ===========================================================================

class TestSignalDetailsForDateExposesPreSignalChangePct:
    """REQ-AI088-005: GET /evaluation/{date_str}의 signal_details 노출 (AC-088-007)."""

    def test_ac088_007_signal_details_includes_pre_signal_change_pct(
        self, client, db: Session, make_stock
    ) -> None:
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        eval_date = date_cls(2026, 7, 20)
        stock = make_stock(name="AI088평가상세종목", stock_code="900195")
        db.add(SurgePredictionEvaluation(evaluation_date=eval_date))
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.7,
            reasoning="테스트 시그널",
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day", "pre_signal_change_pct": 5.91}),
            created_at=datetime(2026, 7, 20, 10, 0),
        )
        db.add(signal)
        db.commit()

        response = client.get(f"/api/surge-trading/evaluation/{eval_date.isoformat()}")
        assert response.status_code == 200
        data = response.json()
        matching = [d for d in data["signal_details"] if d["stock_code"] == stock.stock_code]
        assert len(matching) == 1
        assert matching[0]["pre_signal_change_pct"] == 5.91

    def test_ac088_007_missing_key_returns_null(
        self, client, db: Session, make_stock
    ) -> None:
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation

        eval_date = date_cls(2026, 7, 21)
        stock = make_stock(name="AI088평가상세미탑재종목", stock_code="900196")
        db.add(SurgePredictionEvaluation(evaluation_date=eval_date))
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.7,
            reasoning="테스트 시그널",
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["theme_cluster"]}),
            created_at=datetime(2026, 7, 21, 10, 0),
        )
        db.add(signal)
        db.commit()

        response = client.get(f"/api/surge-trading/evaluation/{eval_date.isoformat()}")
        assert response.status_code == 200
        data = response.json()
        matching = [d for d in data["signal_details"] if d["stock_code"] == stock.stock_code]
        assert len(matching) == 1
        assert matching[0]["pre_signal_change_pct"] is None


class TestPredictionHistoryExposesPreSignalChangePct:
    """REQ-AI088-005: GET /prediction-history 양쪽 분기 노출 (AC-088-008)."""

    def test_ac088_008_today_unevaluated_branch_includes_key(
        self, client, db: Session, make_stock
    ) -> None:
        """"오늘 미평가" 분기(SurgePredictionEvaluation 레코드 없음) item dict에
        pre_signal_change_pct가 포함된다."""
        stock = make_stock(name="AI088이력미평가종목", stock_code="900197")
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.7,
            reasoning="테스트 시그널",
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"horizon": "same_day", "pre_signal_change_pct": 3.2}),
            created_at=datetime.now(),
        )
        db.add(signal)
        db.commit()

        response = client.get("/api/surge-trading/prediction-history?days=5")
        assert response.status_code == 200
        data = response.json()
        today_row = next((r for r in data if r.get("actual_surge_count") is None), None)
        assert today_row is not None, "오늘 미평가 분기 행이 존재해야 한다"
        matching = [
            s for s in today_row["surge_signals"] if s["stock_code"] == stock.stock_code
        ]
        assert len(matching) == 1
        assert matching[0]["pre_signal_change_pct"] == 3.2

    def test_ac088_008_past_evaluated_branch_missing_key_returns_null(
        self, client, db: Session, make_stock
    ) -> None:
        """"과거 평가완료" 분기(SurgePredictionEvaluation 레코드 존재) item dict에도
        pre_signal_change_pct 키가 포함되며(하위호환 케이스는 null)."""
        from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
        from app.services.surge_trading_service import _get_prev_business_day

        eval_date = date_cls(2026, 6, 10)
        signal_date = _get_prev_business_day(eval_date)

        db.add(SurgePredictionEvaluation(evaluation_date=eval_date))
        stock = make_stock(name="AI088이력평가완료종목", stock_code="900198")
        signal = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.7,
            reasoning="테스트 시그널",
            signal_type="surge_candidate",
            surge_metadata=json.dumps({"surge_basis": ["theme_cluster"]}),
            created_at=datetime.combine(signal_date, datetime.min.time()).replace(hour=10),
        )
        db.add(signal)
        db.commit()

        response = client.get("/api/surge-trading/prediction-history?days=90")
        assert response.status_code == 200
        data = response.json()
        past_row = next(
            (r for r in data if r.get("trading_date") == str(signal_date)), None
        )
        assert past_row is not None, "과거 평가완료 분기 행이 존재해야 한다"
        matching = [
            s for s in past_row["surge_signals"] if s["stock_code"] == stock.stock_code
        ]
        assert len(matching) == 1
        assert matching[0]["pre_signal_change_pct"] is None


# ===========================================================================
# AC-088-009 [HARD]: cross-cutting 부가 전용(additive-only) 설계 원칙
# ===========================================================================

class TestAdditiveOnlyDesignPrinciple:
    """AC-088-009: 이 SPEC이 다루지 않는 기존 판별/평가 경로는 이 SPEC 적용 전후로 동일하다.

    전체 백엔드 스위트 무회귀 + `ruff check .` 통과는 M5에서 orchestrator가 read-only
    verification batch로 별도 검증한다(본 파일 내에서 pytest를 재귀 실행하는 것은
    안티패턴이므로 하지 않는다).
    """

    def test_evaluation_predicate_functions_remain_pure_functions(self) -> None:
        """동일 입력을 반복 호출해도 두 판별 함수의 결과가 항상 동일하다(순수 함수 확인,
        pre_signal_change_pct 도입이 숨은 상태를 만들지 않았음을 재확인)."""
        from app.services.surge_evaluation_service import (
            _is_near_limit_up_carry_signal,
            _is_same_day_event_horizon_signal,
        )

        meta = json.dumps(
            {
                "surge_basis": ["near_limit_up_carry"],
                "near_limit_up_carry": True,
                "pre_signal_change_pct": 0.0,
            }
        )
        assert len({_is_near_limit_up_carry_signal(meta) for _ in range(3)}) == 1
        assert len({_is_same_day_event_horizon_signal(meta) for _ in range(3)}) == 1
