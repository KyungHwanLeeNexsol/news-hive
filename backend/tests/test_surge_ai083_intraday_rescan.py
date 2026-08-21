"""SPEC-AI-083: 장중 고빈도 재스캔 + same-day 지평 귀속 + 뉴스 이벤트 재스캔 활성화.

DDD ANALYZE-PRESERVE-IMPROVE (재현-우선, CLAUDE.md Rule 4):

- PRESERVE(특성화, 현재 거동 고정 — 수정 전/후 모두 GREEN):
  * `TestIntradayRescanBaseline`: 기존 10:00 장중 잡 + 15:20 배치 잡이 그대로 유지되고,
    SPEC-AI-043으로 비활성된 매수/청산 잡이 되살아나지 않는다(R-5, AC-083-007).
  * `TestSameDayHorizonAttribution.test_characterize_next_day_no_horizon_key`: 배치 지평
    (next_day)에서는 horizon 키가 주입되지 않아 기존 배치 메타데이터가 바이트 동일하게
    보존된다(REQ-AI083-011 / [X-4]). 수정 전/후 모두 통과하는 불변 대조군.

- IMPROVE(GREEN 목표, 수정 전 RED — 수정 후에만 통과):
  * `TestIntradayRescanExpansion`: 09:05~BUY_CUTOFF 구간에 10:00 외 추가 재스캔 잡
    (조기 09:10 포함, ~20분 간격, distinct id, max_instances=1/coalesce)이 등록된다
    (AC-083-001/002/003/004).
  * `TestSameDayHorizonAttribution.test_same_day_horizon_injected`: 장중(same_day) 재스캔
    후보에 horizon="same_day"가 주입되고 `_is_same_day_event_horizon_signal`이 이를 별도
    same-day 서브지표로 인식한다(AC-083-004 GREEN, SPEC-AI-080 평가 경로 재사용, 스키마 0).
  * `TestEventRescanActivation`: `catalyst_conviction.event_rescan_enabled`가 true로
    활성화되고 가드(쿨다운 30분/일일 20회)는 값 불변으로 준수된다(AC-083-006).

- 회귀 보호: `TestImmediateSurgeRegression`(공시 즉시발화 활성 상태 불변, AC-083-005),
  `TestCommonInvariants`(배치 크론/콜백 재사용 불변, AC-083-007).

주의: 실제 12~20분 gather HTTP 지연은 재현하지 않는다. 후보 생성 경로는 mock으로 대체해
잡 등록/메타데이터/설정 거동을 결정적으로 검증한다(acceptance.md 서두). same-day 귀속의
시각 의존성은 `_classify_disclosure_horizon`을 patch해 결정적으로 구동한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.services import fund_manager
from app.services.fund_manager import _gather_surge_candidates
from app.services.surge_detector import SurgeCandidate
from app.surge_config.surge_settings import CatalystConvictionConfig, get_surge_config


# ---------------------------------------------------------------------------
# 공통 픽스처 / 헬퍼
# ---------------------------------------------------------------------------

# 새 장중 재스캔 잡 id 접두사 (기존 10:00 잡 id도 이 접두사로 시작한다)
_RESCAN_ID_PREFIX = "surge_signal_generate_intraday"

# SPEC-AI-043으로 비활성(주석 처리)된 매수/청산 잡 id — 되살아나면 안 된다(R-5)
_DISABLED_JOB_IDS = {
    "surge_execute_buys",
    "surge_check_exits",
    "surge_force_max_holding_exit",
}


@pytest.fixture
def sector_ai083(db: Session) -> Sector:
    s = Sector(name="SPEC-AI-083테스트섹터")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def stock_ai083(db: Session, sector_ai083: Sector) -> Stock:
    stock = Stock(
        name="AI083테스트종목",
        stock_code="900083",
        sector_id=sector_ai083.id,
        market_cap=500,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_bypass_candidate(stock: Stock) -> SurgeCandidate:
    """품질 floor를 우회(strong_single_bypass)하는 mock 후보.

    theme_cluster_score>=0.85 + combo_score>0.1 조합은 fund_manager.py 품질 floor 게이트를
    우회한다(test_surge_ai080/082와 동일 패턴 재사용) — 본 테스트의 관심사는 품질 게이트가
    아니라 메타데이터 귀속이므로, 이미 검증된 bypass 조합을 차용해 후보가 반드시 FundSignal로
    영속화되게 한다.
    """
    return SurgeCandidate(
        stock_code=stock.stock_code,
        stock_name=stock.name,
        theme_cluster_score=0.9,
        combo_score=0.9,
        active_detectors=["theme_cluster", "volume_news_combo"],
    )


def _collect_added_jobs() -> list[dict]:
    """start_scheduler()를 mock 스케줄러로 구동해 등록된 잡 목록을 수집한다.

    test_surge_ai038.TestIntradaySchedulerJob 패턴 재사용. 실제 BackgroundScheduler를
    기동하지 않고 add_job(func, trigger, **kwargs) 인자만 포착한다.
    """
    added: list[dict] = []

    def fake_add_job(func, trigger, **kwargs) -> None:
        added.append(
            {
                "func": func,
                "trigger": trigger,
                "id": kwargs.get("id"),
                "hour": kwargs.get("hour"),
                "minute": kwargs.get("minute"),
                "max_instances": kwargs.get("max_instances"),
                "coalesce": kwargs.get("coalesce"),
                "replace_existing": kwargs.get("replace_existing"),
            }
        )

    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = fake_add_job
    mock_scheduler.running = False

    with (
        patch("app.services.scheduler.scheduler", mock_scheduler),
        patch("app.services.scheduler.SessionLocal"),
        patch("app.services.scheduler.asyncio.run"),
    ):
        from app.services.scheduler import start_scheduler

        try:
            start_scheduler()
        except Exception:
            pass  # 잡 등록 이후 예외는 무시(스케줄러 start 등)

    return added


def _rescan_jobs(added: list[dict]) -> list[dict]:
    """장중 재스캔 잡(기존 10:00 + 신규)만 필터링."""
    return [j for j in added if (j.get("id") or "").startswith(_RESCAN_ID_PREFIX)]


def _hm_to_minutes(hour, minute) -> int:
    return int(hour) * 60 + int(minute)


# ---------------------------------------------------------------------------
# PRESERVE (특성화, 불변 대조군) — 수정 전/후 모두 GREEN
# ---------------------------------------------------------------------------

class TestIntradayRescanBaseline:
    """기존 스케줄 잡 불변 + 비활성 매수/청산 잡 미복구를 특성화한다(AC-083-007, R-5)."""

    def test_characterize_existing_1000_intraday_job_preserved(self) -> None:
        """기존 10:00 장중 재탐지 잡(surge_signal_generate_intraday)은 유지되어야 한다."""
        added = _collect_added_jobs()
        job = next((j for j in added if j["id"] == "surge_signal_generate_intraday"), None)
        assert job is not None, "기존 10:00 장중 잡이 사라지면 안 된다(SPEC-AI-038 계승)"
        assert job["hour"] == 10 and job["minute"] == 0, "기존 잡은 10:00에 유지되어야 한다"

    def test_characterize_1520_batch_job_preserved(self) -> None:
        """15:20 T-1→T 배치 잡(surge_signal_generate)은 시각 불변이어야 한다(REQ-011)."""
        added = _collect_added_jobs()
        job = next((j for j in added if j["id"] == "surge_signal_generate"), None)
        assert job is not None, "15:20 배치 잡이 존재해야 한다"
        assert job["hour"] == 15 and job["minute"] == 20, "배치 크론 시각은 변경 금지([X-4])"

    def test_disabled_buy_exit_jobs_not_revived(self) -> None:
        """SPEC-AI-043으로 비활성된 매수/청산 잡이 되살아나면 안 된다(R-5, AC-083-007)."""
        added = _collect_added_jobs()
        registered_ids = {j["id"] for j in added}
        revived = registered_ids & _DISABLED_JOB_IDS
        assert not revived, f"예측 기록 모드 파손 — 비활성 매수/청산 잡 오복구: {revived}"


# ---------------------------------------------------------------------------
# IMPROVE (GREEN 목표) — 09:05~BUY_CUTOFF 다중 재스캔 잡 (AC-083-001/002/003/004)
# ---------------------------------------------------------------------------

class TestIntradayRescanExpansion:
    """단일 10:00 스캔을 09:05~BUY_CUTOFF 다중 재스캔으로 확장(수정 전 RED)."""

    def test_additional_rescan_jobs_registered(self) -> None:
        """AC-083-001: 10:00 외에 최소 2개 이상의 추가 당일 후보 생성 잡이 등록되어야 한다."""
        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        non_1000 = [j for j in rescan if not (j["hour"] == 10 and j["minute"] == 0)]
        assert len(non_1000) >= 2, (
            f"10:00 외 추가 재스캔 잡이 2개 이상이어야 한다. 실제 재스캔 잡: "
            f"{[(j['id'], j['hour'], j['minute']) for j in rescan]}"
        )

    def test_early_scan_before_1000_exists(self) -> None:
        """AC-083-003/REQ-004: 09:00~10:00 사각지대 축소용 조기 스캔(< 10:00)이 있어야 한다."""
        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        early = [j for j in rescan if _hm_to_minutes(j["hour"], j["minute"]) < 10 * 60]
        assert early, (
            "09:00~10:00 사각지대 축소를 위한 조기 스캔(10:00 이전)이 최소 1개 있어야 한다"
        )

    def test_rescan_jobs_have_correct_attributes(self) -> None:
        """AC-083-001/002: 각 재스캔 잡은 max_instances=1/coalesce=True/replace_existing=True,
        distinct id, 기존 콜백(_run_surge_signal_generate) 재사용."""
        from app.services.scheduler import _run_surge_signal_generate

        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        ids = [j["id"] for j in rescan]
        assert len(ids) == len(set(ids)), f"재스캔 잡 id는 distinct해야 한다: {ids}"
        for j in rescan:
            assert j["max_instances"] == 1, f"{j['id']}: max_instances=1(겹침 방지)"
            assert j["coalesce"] is True, f"{j['id']}: coalesce=True(미스파이어 접기)"
            assert j["replace_existing"] is True, f"{j['id']}: replace_existing=True"
            assert j["func"] is _run_surge_signal_generate, (
                f"{j['id']}: 콜백은 후보 생성 전용 _run_surge_signal_generate를 재사용해야 한다"
                "(매수/청산 콜백 미참조, REQ-010/[X-3])"
            )

    def test_rescan_interval_bounded_by_gather_duration(self) -> None:
        """AC-083-002/003/013: 재스캔 시각 간 최소 간격이 gather 정상 소요(12~15분) +
        헤드룸 이상으로 유계여야 한다 — gather 소요보다 짧은 무한 누적 금지."""
        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        times = sorted(_hm_to_minutes(j["hour"], j["minute"]) for j in rescan)
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert gaps, "재스캔 잡이 2개 이상이어야 간격을 검증할 수 있다"
        assert min(gaps) >= 15, (
            f"재스캔 최소 간격이 gather 정상 소요(15분) 미만이면 실행 겹침 위험 — 간격들: {gaps}분"
        )

    def test_all_rescan_jobs_within_market_open_window(self) -> None:
        """AC-083-001: 모든 재스캔 잡은 09:05~BUY_CUTOFF(11:00) 창 내에 있어야 한다."""
        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        window_start = 9 * 60 + 5
        window_end = 11 * 60
        for j in rescan:
            t = _hm_to_minutes(j["hour"], j["minute"])
            assert window_start <= t <= window_end, (
                f"{j['id']} 시각 {j['hour']}:{j['minute']:02d}가 09:05~11:00 창을 벗어남"
            )


# ---------------------------------------------------------------------------
# T-004: 당일 후보 same-day 지평 귀속 (AC-083-004 RED/GREEN)
# ---------------------------------------------------------------------------

class TestSameDayHorizonAttribution:
    """장중 재스캔 당일 후보의 same-day 지평 귀속(SPEC-AI-080 평가 경로 재사용, 스키마 0)."""

    @pytest.mark.asyncio
    async def test_characterize_next_day_no_horizon_key(
        self, db: Session, stock_ai083: Stock
    ) -> None:
        """PRESERVE(불변 대조군, REQ-011/[X-4]): 배치 지평(next_day)에서는 horizon 키가
        주입되지 않아 기존 배치 메타데이터가 바이트 동일하게 보존된다 — 수정 전/후 모두 통과.
        """
        candidate = _make_bypass_candidate(stock_ai083)
        with (
            patch(
                "app.services.disclosure_impact_scorer._classify_disclosure_horizon",
                return_value="next_day",
            ),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                return_value=[candidate],
            ),
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        signal = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_ai083.id,
                FundSignal.signal_type == "surge_candidate",
            )
            .first()
        )
        assert signal is not None, "bypass 후보는 FundSignal로 영속화되어야 한다"
        meta = json.loads(signal.surge_metadata)
        assert "horizon" not in meta, (
            "next_day(배치/장전/장후) 지평에서는 horizon 키를 넣지 않아야 한다 "
            "— 15:20 배치 메타데이터 바이트 동일 보존(REQ-AI083-011)"
        )

    @pytest.mark.asyncio
    async def test_same_day_horizon_injected_and_recognized(
        self, db: Session, stock_ai083: Stock
    ) -> None:
        """GREEN(AC-083-004): 장중(same_day) 재스캔 후보에 horizon="same_day"가 주입되고,
        평가측 `_is_same_day_event_horizon_signal`이 이를 same-day 서브지표로 인식한다.
        수정 전에는 horizon 키가 없어 RED.
        """
        from app.services.surge_evaluation_service import _is_same_day_event_horizon_signal

        candidate = _make_bypass_candidate(stock_ai083)
        with (
            patch(
                "app.services.disclosure_impact_scorer._classify_disclosure_horizon",
                return_value="same_day",
            ),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                return_value=[candidate],
            ),
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        signal = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock_ai083.id,
                FundSignal.signal_type == "surge_candidate",
            )
            .first()
        )
        assert signal is not None, "bypass 후보는 FundSignal로 영속화되어야 한다"
        meta = json.loads(signal.surge_metadata)
        assert meta.get("horizon") == "same_day", (
            "장중(09:00~batch_cutoff) 재스캔 후보는 horizon='same_day'로 귀속되어야 한다"
            "(REQ-AI083-005)"
        )
        assert _is_same_day_event_horizon_signal(signal.surge_metadata) is True, (
            "SPEC-AI-080 평가 경로가 same-day 시그널로 인식해 표준 T-1→T predicted_set에서 "
            "배제하고 별도 서브지표로 집계해야 한다"
        )


# ---------------------------------------------------------------------------
# T-005: 공시 즉시발화 회귀 보호 (AC-083-005)
# ---------------------------------------------------------------------------

class TestImmediateSurgeRegression:
    """이미 활성인 공시 즉시발화(SPEC-AI-080)와 same_day 평가 경로 불변을 고정한다."""

    def test_immediate_surge_enabled_true_unchanged(self) -> None:
        """immediate_surge.enabled는 true(2026-07-16 활성)로 유지되어야 한다(재플립 없음)."""
        cfg = get_surge_config()
        assert cfg.immediate_surge.enabled is True, (
            "공시 즉시발화는 이미 활성 상태 — 본 SPEC은 재활성/변경하지 않는다(REQ-007)"
        )
        assert cfg.immediate_surge.min_impact == 40.0
        assert cfg.immediate_surge.batch_cutoff_hour == 15
        assert cfg.immediate_surge.batch_cutoff_minute == 20

    def test_classify_horizon_at_batch_cutoff_is_next_day(self) -> None:
        """15:20 배치 시각(cutoff)은 next_day로 분류되어야 한다 — 배치 메타 바이트 동일 근거."""
        from app.services.disclosure_impact_scorer import _classify_disclosure_horizon

        cfg = get_surge_config().immediate_surge
        # 평일(월요일) 15:20 = cutoff 경계 → next_day
        monday_1520 = datetime(2026, 7, 20, 15, 20)
        assert _classify_disclosure_horizon(monday_1520, cfg) == "next_day"
        # 평일 장중 10:00 → same_day
        monday_1000 = datetime(2026, 7, 20, 10, 0)
        assert _classify_disclosure_horizon(monday_1000, cfg) == "same_day"


# ---------------------------------------------------------------------------
# T-006: 뉴스 이벤트 재스캔 활성화 + 가드 준수 (AC-083-006)
# ---------------------------------------------------------------------------

class TestEventRescanActivation:
    """catalyst_conviction.event_rescan_enabled false→true 활성화 + 가드 값 불변."""

    def test_event_rescan_enabled_true_in_yaml(self) -> None:
        """AC-083-006: 로드된 설정에서 event_rescan_enabled가 true여야 한다(플래그 플립)."""
        cfg = get_surge_config()
        assert cfg.catalyst_conviction.event_rescan_enabled is True, (
            "surge_detection.yaml의 event_rescan_enabled가 true로 활성화되어야 한다(REQ-008)"
        )

    def test_event_rescan_guard_values_unchanged(self) -> None:
        """AC-083-006/[X-8]: 가드 값(쿨다운 30분/일일 20회)은 변경되지 않아야 한다."""
        cfg = get_surge_config()
        assert cfg.catalyst_conviction.event_rescan_cooldown_minutes == 30, (
            "쿨다운 가드 값 변경 금지 — 플래그만 플립([X-8])"
        )
        assert cfg.catalyst_conviction.max_daily_event_triggers == 20, (
            "일일 상한 가드 값 변경 금지 — 플래그만 플립([X-8])"
        )

    def test_config_model_default_still_false(self) -> None:
        """CatalystConvictionConfig 모델 기본값은 여전히 false여야 한다 — YAML 플립은
        모델 기본값이 아니라 배포 설정만 바꾼다(staged rollout 관례, SPEC-AI-066 회귀 방지)."""
        assert CatalystConvictionConfig().event_rescan_enabled is False, (
            "모델 기본값(staged rollout 기본 OFF)은 불변 — YAML 배포 값만 활성화한다"
        )

    def test_event_rescan_fires_when_enabled_with_guards(
        self, db: Session, sector_ai083: Sector
    ) -> None:
        """AC-083-006: 활성화된 상태에서 고확신 뉴스 도착 시 이벤트 재스캔이 발화하고,
        쿨다운/일일 상한 가드가 그대로 준수된다(인프라 재사용, 신규 구현 없음)."""
        import app.services.scheduler as sched
        from app.models.news import NewsArticle
        from app.models.news_relation import NewsStockRelation

        sched._reset_event_rescan_state()
        try:
            stock = Stock(
                stock_code="900840",
                name="이벤트재스캔종목",
                sector_id=sector_ai083.id,
                market_cap=500,
            )
            db.add(stock)
            db.flush()
            ts = datetime.now() - timedelta(hours=0.5)
            art = NewsArticle(
                title="경영권 인수 M&A 확정 대형 호재",
                content="내용",
                summary="",
                url="http://ex.com/ai083-event",
                source="테스트",
                sentiment="positive",
                collected_at=ts,
                published_at=ts,
            )
            db.add(art)
            db.flush()
            db.add(
                NewsStockRelation(
                    news_id=art.id, stock_id=stock.id, match_type="keyword", relevance="direct"
                )
            )
            db.flush()

            # 활성 설정: 실제 yaml 로드 대신 catalyst_conviction만 활성화한 config 사용
            base = get_surge_config()
            catalyst = CatalystConvictionConfig(
                **{**base.catalyst_conviction.model_dump(), "enabled": True, "event_rescan_enabled": True}
            )
            cfg = base.model_copy(update={"catalyst_conviction": catalyst})

            with patch(
                "app.services.scheduler._run_event_surge_generation", return_value=2
            ) as mock_gen:
                first = sched._maybe_trigger_event_rescan(db, cfg)
                second = sched._maybe_trigger_event_rescan(db, cfg)  # 쿨다운 내 재트리거

            assert first is True, "활성화 + 고확신 뉴스 → 이벤트 재스캔 발화"
            assert second is False, "쿨다운(30분) 내 재트리거는 차단되어야 한다(가드 준수)"
            assert mock_gen.call_count == 1
        finally:
            sched._reset_event_rescan_state()


# ---------------------------------------------------------------------------
# T-007: 공통 불변식 (AC-083-007)
# ---------------------------------------------------------------------------

class TestCommonInvariants:
    """탐지/배치/매매 불변 — 재스캔은 additive일 뿐 기존 경로를 대체하지 않는다."""

    def test_rescan_callback_is_shared_candidate_generator(self) -> None:
        """재스캔 잡의 콜백은 기존 후보 생성 콜백(_run_surge_signal_generate)과 동일해야 한다
        — 매수/청산 콜백을 신규 참조하지 않는다(REQ-010/[X-3])."""
        from app.services.scheduler import _run_surge_signal_generate

        added = _collect_added_jobs()
        rescan = _rescan_jobs(added)
        assert rescan, "재스캔 잡이 존재해야 한다"
        for j in rescan:
            assert j["func"] is _run_surge_signal_generate

    def test_buy_cutoff_unchanged(self) -> None:
        """BUY_CUTOFF(11:00) 값/로직은 불변이어야 한다(REQ-012, 참조만)."""
        from datetime import time as _time

        from app.services.surge_trading_service import BUY_CUTOFF

        assert BUY_CUTOFF == _time(11, 0), "BUY_CUTOFF 값 변경 금지([X-5])"

    def test_gather_timeout_constant_unchanged(self) -> None:
        """gather 타임아웃 상수(간격 산정 근거)는 참조만 — 값 불변.

        SPEC-AI-082가 1200(20분)으로 도입, SPEC-AI-117이 2026-08-19~08-20
        프로덕션 타임아웃 재발(SPEC-AI-096 스캔 유니버스 확대로 07-20 캘리브레이션
        무효화)에 따라 2400(40분)으로 임시 완화했다 — 이 SPEC(SPEC-AI-083)은
        여전히 값을 변경하지 않는다(참조만).
        """
        assert fund_manager._GATHER_TIMEOUT_S == 2400, (
            "gather 타임아웃 상수는 본 SPEC에서 변경하지 않는다(참조만, SPEC-AI-117 소유)"
        )
