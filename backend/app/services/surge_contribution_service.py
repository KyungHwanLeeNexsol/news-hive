"""SPEC-AI-070: 탐지기별 기여도 집계, 은퇴 제안, 학습형 타당성 평가.

측정·리포트 전용 계층 — 신호 생성 경로(compute_ensemble_score/gather_surge_candidates/
build_scan_universe)와 매수 로직을 절대 변경하지 않는다. 어떤 함수도 surge_detection.yaml
/ surge_detection.auto.yaml을 쓰지 않으며, 탐지기를 자동으로 추가/제거/비활성화하지
않는다(REQ-004 [HARD]) — 은퇴는 사람이 리포트를 검토해 base yaml을 수동 편집해야만 적용된다.

기여도 정의(설계 근거, plan.md 참조): 탐지기별 component score(theme_cluster_score 등
5종)는 surge_metadata에 부분적으로만 영속화되며(2026-07-02 코드 재확인 정정 — spec.md의
"전혀 영속화되지 않는다"는 서술은 부정확했음, EC-6 참조), standalone/bypass 탐지기의 개별
점수는 전혀 저장되지 않는다. 따라서 "탐지기 D를 빼고 재채점"하는 정밀 counterfactual은
사후 재구성이 불가능하다 — 기여도는 `surge_basis` 멤버십(어떤 탐지기가 발동했는가) ×
scannable 결과(SPEC-AI-068 라벨) attribution으로 근사한다. 모든 탐지기(앙상블 편입 여부와
무관)에 대해 이 근사를 균일하게 적용한다.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date as date_
from typing import Optional

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_detector_contribution import SurgeDetectorContribution
from app.services.surge_backtest import compute_surge_backtest
from app.services.surge_trading_service import _get_prev_business_day

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 탐지기 레지스트리 (REQ-002: (a) 앙상블 weighted_sum 편입 / (b) standalone·bypass 발신 /
# (c) 0-가중치 3분류). 코드 검증 기준(2026-07-02): compute_ensemble_score weighted_sum
# (surge_detector.py:1553-1564), surge_detection.yaml ensemble.weights(:63-73),
# active_detectors/surge_basis 리터럴 문자열 전수 조사(surge_detector.py grep).
# ---------------------------------------------------------------------------

DETECTOR_CATEGORY_ENSEMBLE = "ensemble_weighted_sum"
DETECTOR_CATEGORY_STANDALONE = "standalone_bypass"
DETECTOR_CATEGORY_ZERO_WEIGHT = "zero_weight"


@dataclass(frozen=True)
class DetectorInfo:
    """탐지기 분류 메타데이터 (리포트 빌더 전용, 신호 생성 경로 무관)."""

    category: str
    yaml_weight_key: Optional[str] = None
    note: str = ""


# @MX:NOTE: [AUTO] SPEC-AI-070 REQ-002 — 탐지기 3분류 레지스트리. compute_ensemble_score의
# weighted_sum 항(surge_detector.py:1553-1564)과 surge_detection.yaml ensemble.weights를
# 읽기 참조만 하며 코드/config를 변경하지 않는다. disclosure_pattern/immediate_disclosure는
# best_disclosure_score = max(pattern_score, immediate_disclosure_score)로 동일 가중치
# 버킷을 공유하지만 surge_basis 리터럴은 서로 다르므로 별도 detector 행으로 추적한다.
# @MX:SPEC: SPEC-AI-070 REQ-AI070-002
DETECTOR_REGISTRY: dict[str, DetectorInfo] = {
    # (a) 앙상블 weighted_sum 편입 (가중치 > 0)
    "theme_cluster": DetectorInfo(DETECTOR_CATEGORY_ENSEMBLE, "theme_cluster"),
    "volume_news_combo": DetectorInfo(DETECTOR_CATEGORY_ENSEMBLE, "volume_news_combo"),
    "disclosure_pattern": DetectorInfo(
        DETECTOR_CATEGORY_ENSEMBLE,
        "disclosure_pattern",
        "best_disclosure_score=max(pattern_score, immediate_disclosure_score) 버킷을 "
        "immediate_disclosure와 공유(동일 yaml weight=0.14)",
    ),
    "immediate_disclosure": DetectorInfo(
        DETECTOR_CATEGORY_ENSEMBLE,
        "disclosure_pattern",
        "disclosure_pattern과 동일 weighted_sum 버킷(max 병합) — surge_basis 리터럴만 별도",
    ),
    "news_delayed": DetectorInfo(DETECTOR_CATEGORY_ENSEMBLE, "news_delayed"),
    "volume_breakout": DetectorInfo(DETECTOR_CATEGORY_ENSEMBLE, "volume_breakout"),
    "momentum_continuation": DetectorInfo(DETECTOR_CATEGORY_ENSEMBLE, "momentum_continuation"),
    # (c) 0-가중치: weighted_sum 항은 존재하나 계수 0.00 (surge_basis 리터럴은 "legacy")
    "legacy": DetectorInfo(
        DETECTOR_CATEGORY_ZERO_WEIGHT,
        "legacy_detectors",
        "weighted_sum 가중치 0.00이나 detector_groups['technical'] 멤버십으로 컨센서스 "
        "배율(×1.30/×1.55)을 밀어올려 다른 탐지기의 최종 점수에 기여할 수 있다(EC-5)",
    ),
    # (b) standalone/bypass — signal_type="surge_candidate"로 실제 FundSignal 발신
    "near_limit_up_carry": DetectorInfo(DETECTOR_CATEGORY_STANDALONE),
    "insider_purchase": DetectorInfo(DETECTOR_CATEGORY_STANDALONE),
    "theme_group_carry": DetectorInfo(DETECTOR_CATEGORY_STANDALONE),
    "forum_mention_surge": DetectorInfo(DETECTOR_CATEGORY_STANDALONE),
    "group_cascade": DetectorInfo(DETECTOR_CATEGORY_STANDALONE),
    # (b) standalone으로 분류되나 구조적으로 emission_count가 항상 0에 가깝다(2026-07-02
    # 코드 재확인으로 신규 발견 — spec.md 대비 정정 사항, AC-070-002/EC-4 각주로 표면화):
    "weekend_gap_up": DetectorInfo(
        DETECTOR_CATEGORY_STANDALONE,
        "weekend_gap_up",
        "yaml weight=0.08이나 weighted_sum 미반영(dead config). 추가로 fund_manager.py:4013 "
        "확인 결과 detect_weekend_gap_up_signals()의 dict 결과가 FundSignal로 전혀 영속화되지 "
        "않는다('FundSignal 미생성' 주석) — emission_count는 구조적으로 항상 0.",
    ),
    "bollinger_squeeze": DetectorInfo(
        DETECTOR_CATEGORY_STANDALONE,
        None,
        "detect_bollinger_squeeze_signals() 결과가 FundSignal로 병합/영속화되지 않는다"
        "(scheduler.py:_run_bollinger_squeeze_detect는 로그만 남김) — emission_count 구조적 0.",
    ),
    "gap_up_runners": DetectorInfo(
        DETECTOR_CATEGORY_STANDALONE,
        None,
        "signal_type='gap_up_runners'로 발신되어 signal_type='surge_candidate' 필터"
        "(068/070 predicted_set 공통 정의) 밖에 위치 — 본 측정 범위에서 구조적으로 "
        "emission_count=0(별도 트랙, preday_signal_service가 소비).",
    ),
    "volume_anomaly": DetectorInfo(
        DETECTOR_CATEGORY_STANDALONE,
        None,
        "signal_type='volume_anomaly', surge_metadata=None — surge_basis 자체가 없어 "
        "측정 불가(구조적 emission_count=0).",
    ),
}

# 구조적으로 emission_count가 0에 고정되는 탐지기(코드 검증, EC-4 확장 사례)
STRUCTURAL_ZERO_EMISSION_DETECTORS: frozenset[str] = frozenset(
    {"weekend_gap_up", "bollinger_squeeze", "gap_up_runners", "volume_anomaly"}
)

# 현재 앙상블 가중치 스냅샷(surge_detection.yaml:63-73과 동일, 읽기 참조 전용) — 리포트의
# 재정규화 예시 계산에만 쓰이며 실제 config 파일을 읽거나 쓰지 않는다(하드코딩 스냅샷).
_CURRENT_ENSEMBLE_WEIGHTS: dict[str, float] = {
    "theme_cluster": 0.19,
    "volume_news_combo": 0.25,
    "disclosure_pattern": 0.14,
    "legacy_detectors": 0.00,
    "news_delayed": 0.11,
    "weekend_gap_up": 0.08,
    "volume_breakout": 0.11,
    "momentum_continuation": 0.12,
}

# T-004 은퇴 후보 판정 롤링 윈도 기본값(측정 계층 자체 config — surge_detection.yaml과
# 독립. 표본 부족 오탐(EC-1)을 막기 위한 보수적 기본값)
RETIREMENT_WINDOW_TRADING_DAYS = 10
RETIREMENT_MIN_SIGNALS = 5
BACKTEST_LOOKBACK_DAYS_DEFAULT = 30

# REQ-005 학습형 타당성 평가 최소 관측 거래일 수
LEARNED_FEASIBILITY_MIN_TRADING_DAYS = 30


# ---------------------------------------------------------------------------
# REQ-001/002: 탐지기별 기여도 집계 + 영속화
# ---------------------------------------------------------------------------


@dataclass
class DetectorMetrics:
    """탐지기 1개, 거래일 1개 기준 기여도 지표(순수 계산 결과, DB 미의존)."""

    detector: str
    emission_count: int = 0
    solo_count: int = 0
    solo_tp: int = 0
    coincident_hit_rate: Optional[float] = None
    unique_catch: int = 0


def _parse_surge_basis_raw(surge_metadata_raw: Optional[str]) -> list[str]:
    """FundSignal.surge_metadata(JSON string)에서 surge_basis 리스트를 파싱한다.

    surge_candidate_to_signal_metadata()가 쓰는 "surge_basis" 키를 그대로 읽기만 한다
    (surge_detector.py:2299) — 신호 생성 경로를 변경하지 않는다.
    """
    if not surge_metadata_raw:
        return []
    try:
        meta = json.loads(surge_metadata_raw)
    except (json.JSONDecodeError, TypeError):
        return []
    basis = meta.get("surge_basis", [])
    if not isinstance(basis, list):
        return []
    return [str(b) for b in basis if b]


def _compute_detector_metrics(
    signal_rows: list[tuple[Optional[str], str]],
    scannable_codes: set[str],
) -> dict[str, DetectorMetrics]:
    """REQ-001: surge_basis 멤버십 × scannable 결과로 탐지기별 원시 지표를 계산한다(순수 함수).

    Args:
        signal_rows: (surge_metadata JSON string, stock_code) 튜플 목록 — T-1 surge_candidate
            시그널 전체(evaluate_surge_predictions의 predicted_set 조회와 동일 필터로 얻은 것).
        scannable_codes: T당일 scannable 실제급등주 종목코드 집합(SPEC-AI-068 라벨).

    Returns:
        {detector: DetectorMetrics} — signal_rows에 실제로 등장한 탐지기만 키로 포함한다.
        레지스트리 전체 보완(0-emission 포함)은 호출부(evaluate_detector_contribution)의
        책임이다.
    """
    metrics: dict[str, DetectorMetrics] = {}
    hit_counts: dict[str, int] = {}
    unique_catch_sets: dict[str, set[str]] = {}

    def _get(detector: str) -> DetectorMetrics:
        if detector not in metrics:
            metrics[detector] = DetectorMetrics(detector=detector)
            hit_counts[detector] = 0
            unique_catch_sets[detector] = set()
        return metrics[detector]

    for surge_metadata_raw, stock_code in signal_rows:
        basis = _parse_surge_basis_raw(surge_metadata_raw)
        if not basis:
            continue
        is_hit = stock_code in scannable_codes

        for detector in basis:
            m = _get(detector)
            m.emission_count += 1
            if is_hit:
                hit_counts[detector] += 1

        # solo_count/solo_tp/unique_catch: surge_basis == [D] (D 단독 발동)인 경우만
        if len(basis) == 1:
            solo_detector = basis[0]
            m = _get(solo_detector)
            m.solo_count += 1
            if is_hit:
                m.solo_tp += 1
                unique_catch_sets[solo_detector].add(stock_code)

    # EC-2: 해당 run_date에 scannable 실제급등주가 0이면 hit_rate 계열 지표는 null(측정 불가)
    scannable_denominator_valid = len(scannable_codes) > 0
    for detector, m in metrics.items():
        m.unique_catch = len(unique_catch_sets.get(detector, set()))
        if scannable_denominator_valid and m.emission_count > 0:
            m.coincident_hit_rate = round(hit_counts.get(detector, 0) / m.emission_count, 4)
        else:
            m.coincident_hit_rate = None

    return metrics


# @MX:NOTE: [AUTO] SPEC-AI-070 REQ-001/002 — evaluate_surge_predictions(18:30 KST,
# surge_evaluation_service.py:482)와 완전히 분리된 신규 함수. predicted_set은 종목코드
# 집합만 필요해 surge_basis를 로드하지 않으므로, 이 함수가 T-1 시그널을 별도로 재조회해
# surge_basis × scannable 라벨 attribution을 산출한다. fan_in=1(스케줄러 잡 1곳)이라
# ANCHOR 대상 아님.
# @MX:SPEC: SPEC-AI-070 REQ-AI070-001, REQ-AI070-002
def evaluate_detector_contribution(
    db: Session,
    trading_date: date_,
) -> list[SurgeDetectorContribution]:
    """T-1 surge_basis 멤버십 × T당일 scannable 결과로 탐지기별 기여도를 산출·영속화한다.

    DETECTOR_REGISTRY의 모든 탐지기에 대해 run_date=trading_date 기준 1행씩 upsert한다
    (발신 이력이 없는 탐지기도 emission_count=0 행으로 기록 — REQ-002 "전부를 포함한다").
    retire_candidate는 이 함수에서 건드리지 않는다(assess_retirement_candidates +
    apply_retirement_candidates가 별도로 갱신 — REQ-003/004 관심사 분리).

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 평가 기준 날짜(T당일, evaluate_surge_predictions와 동일 정의)

    Returns:
        저장된 SurgeDetectorContribution 행 목록(레지스트리 탐지기 수만큼)
    """
    prev_business_day = _get_prev_business_day(trading_date)
    logger.info(
        "[탐지기기여도] 계산 시작: T=%s, T-1=%s", trading_date, prev_business_day
    )

    # 1. T-1 surge_candidate 시그널 조회 — evaluate_surge_predictions와 동일 필터
    #    (signal_type/surge_metadata/created_at 날짜), surge_metadata까지 함께 로드한다는
    #    점만 다르다.
    from sqlalchemy import func as sqlfunc

    signal_rows_raw = (
        db.query(FundSignal.surge_metadata, Stock.stock_code)
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.signal_type == "surge_candidate",
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at) == prev_business_day,
        )
        .all()
    )
    signal_rows: list[tuple[Optional[str], str]] = [
        (row.surge_metadata, row.stock_code) for row in signal_rows_raw
    ]

    # 2. T당일 scannable 실제급등주 집합(SPEC-AI-068 라벨) — 유니버스 부재/과거 날짜는
    #    surge_type이 애초에 "scannable"로 채워지지 않으므로 자연히 빈 집합이 된다(EC-3).
    scannable_rows = (
        db.query(SurgeActualOutcome.stock_code)
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.surge_type == "scannable",
        )
        .all()
    )
    scannable_codes: set[str] = {row.stock_code for row in scannable_rows}

    logger.info(
        "[탐지기기여도] T-1 시그널=%d건, T당일 scannable=%d건",
        len(signal_rows), len(scannable_codes),
    )

    metrics = _compute_detector_metrics(signal_rows, scannable_codes)

    # REQ-002: 레지스트리 전체를 포함(발신 이력이 없는 탐지기도 0행으로 기록)
    for detector in DETECTOR_REGISTRY:
        if detector not in metrics:
            metrics[detector] = DetectorMetrics(detector=detector, coincident_hit_rate=None)

    persisted: list[SurgeDetectorContribution] = []
    for detector, m in metrics.items():
        existing = (
            db.query(SurgeDetectorContribution)
            .filter(
                SurgeDetectorContribution.run_date == trading_date,
                SurgeDetectorContribution.detector == detector,
            )
            .first()
        )
        if existing is not None:
            existing.emission_count = m.emission_count
            existing.solo_count = m.solo_count
            existing.solo_tp = m.solo_tp
            existing.coincident_hit_rate = m.coincident_hit_rate
            existing.unique_catch = m.unique_catch
            row = existing
        else:
            row = SurgeDetectorContribution(
                run_date=trading_date,
                detector=detector,
                emission_count=m.emission_count,
                solo_count=m.solo_count,
                solo_tp=m.solo_tp,
                coincident_hit_rate=m.coincident_hit_rate,
                unique_catch=m.unique_catch,
                retire_candidate=False,
            )
            db.add(row)
        persisted.append(row)

    db.flush()
    db.commit()
    for row in persisted:
        db.refresh(row)

    logger.info("[탐지기기여도] %d개 탐지기 행 upsert 완료 (run_date=%s)", len(persisted), trading_date)
    return persisted


# ---------------------------------------------------------------------------
# REQ-003: backtest 검증된 은퇴 제안
# ---------------------------------------------------------------------------


@dataclass
class RetirementBacktestVerdict:
    """탐지기 D의 solo 신호를 제외했을 때 잔여 신호 집합의 backtest 판정."""

    detector: str
    before_total_signals: int
    before_accuracy: float
    after_total_signals: int
    after_accuracy: Optional[float]
    accuracy_did_not_drop: bool
    solo_signals_excluded: int


def _reconstruct_correct_count(accuracy: float, count: int) -> int:
    """by_combination의 반올림된 accuracy로부터 correct 건수를 역산한다.

    compute_surge_backtest가 accuracy = round(correct/count, 4)로 저장하므로, 통상적인
    신호 건수 범위(수십~수백 건)에서는 반올림 왕복이 정확히 복원된다(EC-6과 동일 성격의
    근사 — 정밀 재계산이 아닌 최선 근사임을 명시).
    """
    return round(accuracy * count)


# @MX:NOTE: [AUTO] SPEC-AI-070 REQ-003 — compute_surge_backtest(불변, surge_backtest.py의
# @MX:ANCHOR API 계약)를 fresh 호출만 하고 by_combination에서 D의 solo 조합 통계를 제외한
# 잔여 accuracy를 재계산한다. 매매/신호 생성 로직에는 관여하지 않는다.
# @MX:SPEC: SPEC-AI-070 REQ-AI070-003
def verify_retirement_via_backtest(
    db: Session,
    detector: str,
    *,
    lookback_days: int = BACKTEST_LOOKBACK_DAYS_DEFAULT,
) -> RetirementBacktestVerdict:
    """탐지기 D의 solo 신호를 제외한 잔여 신호 집합의 directional accuracy가
    하락하지 않는지 compute_surge_backtest().by_combination을 재사용해 검증한다.
    """
    result = compute_surge_backtest(db, days=lookback_days)
    solo_stats = result.by_combination.get(detector)

    if not solo_stats or solo_stats.get("count", 0) == 0:
        # D의 solo 신호가 이 lookback 기간에 전혀 없음 — 제외해도 잔여는 원본과 동일
        return RetirementBacktestVerdict(
            detector=detector,
            before_total_signals=result.total_signals,
            before_accuracy=result.directional_accuracy,
            after_total_signals=result.total_signals,
            after_accuracy=result.directional_accuracy,
            accuracy_did_not_drop=True,
            solo_signals_excluded=0,
        )

    solo_count = solo_stats["count"]
    solo_correct = _reconstruct_correct_count(solo_stats["accuracy"], solo_count)
    total_correct = _reconstruct_correct_count(result.directional_accuracy, result.total_signals)

    after_total = result.total_signals - solo_count
    after_correct = total_correct - solo_correct

    if after_total <= 0:
        # D의 solo 신호가 lookback 기간 전체 신호를 구성 — 제외 후 비교 대상 없음.
        # 비교 불가를 "하락 없음"으로 안전측 처리하지 않고, 표본 자체가 D 하나뿐이라는
        # 사실을 그대로 반환한다(호출부가 별도 표본부족 처리를 하도록).
        return RetirementBacktestVerdict(
            detector=detector,
            before_total_signals=result.total_signals,
            before_accuracy=result.directional_accuracy,
            after_total_signals=0,
            after_accuracy=None,
            accuracy_did_not_drop=True,
            solo_signals_excluded=solo_count,
        )

    after_accuracy = round(after_correct / after_total, 4)
    return RetirementBacktestVerdict(
        detector=detector,
        before_total_signals=result.total_signals,
        before_accuracy=result.directional_accuracy,
        after_total_signals=after_total,
        after_accuracy=after_accuracy,
        accuracy_did_not_drop=after_accuracy >= result.directional_accuracy,
        solo_signals_excluded=solo_count,
    )


@dataclass
class RetirementAssessment:
    """REQ-003: 탐지기 1개에 대한 최종 은퇴 후보 판정 결과."""

    detector: str
    is_floor_breach: bool
    insufficient_sample: bool
    backtest_verdict: Optional[RetirementBacktestVerdict]
    retire_candidate: bool
    reason: str


def assess_retirement_candidates(
    db: Session,
    run_date: date_,
    *,
    window_trading_days: int = RETIREMENT_WINDOW_TRADING_DAYS,
    min_signals: int = RETIREMENT_MIN_SIGNALS,
    backtest_lookback_days: int = BACKTEST_LOOKBACK_DAYS_DEFAULT,
) -> dict[str, RetirementAssessment]:
    """REQ-003: 롤링 윈도 기준 floor 미달 + backtest 검증 통과 탐지기를 은퇴 후보로 판정한다.

    floor 미달 = emission_count == 0 (전혀 발신 안 함) OR (solo_tp == 0 AND unique_catch == 0
    이 윈도 동안 지속). EC-1: 관측 유효일이 window_trading_days 미만이면 표본 부족으로
    보류(retire_candidate=False). EC-3: 특정 거래일에 D가 발신했으나 그날 scannable
    분모가 0이라 coincident_hit_rate가 null인 행은 "증거 없음"으로 간주해 유효 관측일
    카운트에서 제외한다(활동량 합산에는 포함하되 판정 근거로는 쓰지 않음).
    """
    assessments: dict[str, RetirementAssessment] = {}

    for detector in DETECTOR_REGISTRY:
        rows = (
            db.query(SurgeDetectorContribution)
            .filter(
                SurgeDetectorContribution.detector == detector,
                SurgeDetectorContribution.run_date <= run_date,
            )
            .order_by(SurgeDetectorContribution.run_date.desc())
            .limit(window_trading_days)
            .all()
        )

        # EC-3: 발신했으나 그날 scannable 분모가 0이라 증거가 없는 행은 유효 관측일에서 제외
        valid_evidence_rows = [
            r for r in rows if not (r.emission_count > 0 and r.coincident_hit_rate is None)
        ]
        valid_evidence_days = len(valid_evidence_rows)

        cumulative_emission = sum(r.emission_count for r in rows)
        cumulative_solo_tp = sum(r.solo_tp for r in rows)
        cumulative_unique_catch = sum(r.unique_catch for r in rows)

        never_fires = cumulative_emission == 0
        fires_but_never_hits = (
            cumulative_emission > 0 and cumulative_solo_tp == 0 and cumulative_unique_catch == 0
        )
        floor_breach = never_fires or fires_but_never_hits

        # EC-1: 유효 관측일 부족 — 표본 부족으로 판정 보류
        if valid_evidence_days < window_trading_days:
            assessments[detector] = RetirementAssessment(
                detector=detector,
                is_floor_breach=floor_breach,
                insufficient_sample=True,
                backtest_verdict=None,
                retire_candidate=False,
                reason=(
                    f"표본 부족(유효 관측 {valid_evidence_days}/{window_trading_days} 거래일) "
                    "— 은퇴 판정 보류"
                ),
            )
            continue

        if not floor_breach:
            assessments[detector] = RetirementAssessment(
                detector=detector,
                is_floor_breach=False,
                insufficient_sample=False,
                backtest_verdict=None,
                retire_candidate=False,
                reason="floor 충족 — 은퇴 후보 아님",
            )
            continue

        # EC-1 (변형): 발신은 하지만 누적 발신 수 자체가 min_signals 미만이면 표본 부족
        if fires_but_never_hits and cumulative_emission < min_signals:
            assessments[detector] = RetirementAssessment(
                detector=detector,
                is_floor_breach=True,
                insufficient_sample=True,
                backtest_verdict=None,
                retire_candidate=False,
                reason=f"표본 부족(누적 발신 {cumulative_emission}/{min_signals}) — 은퇴 판정 보류",
            )
            continue

        verdict = verify_retirement_via_backtest(
            db, detector, lookback_days=backtest_lookback_days
        )
        retire = floor_breach and verdict.accuracy_did_not_drop
        assessments[detector] = RetirementAssessment(
            detector=detector,
            is_floor_breach=True,
            insufficient_sample=False,
            backtest_verdict=verdict,
            retire_candidate=retire,
            reason=(
                "floor 미달 + backtest 검증 통과(제외해도 정확도 하락 없음) — 은퇴 후보"
                if retire
                else "floor 미달이나 backtest 검증 미통과(제외 시 정확도 하락) — 은퇴 보류"
            ),
        )

    return assessments


def apply_retirement_candidates(
    db: Session,
    run_date: date_,
    assessments: Optional[dict[str, RetirementAssessment]] = None,
) -> list[SurgeDetectorContribution]:
    """REQ-003/004: run_date의 SurgeDetectorContribution 행에 retire_candidate 플래그를 반영한다.

    [HARD] 이 함수는 surge_detection.yaml/auto.yaml을 포함해 어떤 config 파일도 쓰지 않는다.
    오직 이미 존재하는 run_date의 DB 행을 갱신할 뿐이다(REQ-004).
    """
    if assessments is None:
        assessments = assess_retirement_candidates(db, run_date)

    rows = (
        db.query(SurgeDetectorContribution)
        .filter(SurgeDetectorContribution.run_date == run_date)
        .all()
    )
    for row in rows:
        assessment = assessments.get(row.detector)
        if assessment is not None:
            row.retire_candidate = assessment.retire_candidate
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


# ---------------------------------------------------------------------------
# REQ-002/004: 리포트 빌더 (3분류 + dead-weight/consensus 뉘앙스 + 재정규화 예시)
# ---------------------------------------------------------------------------


def _renormalization_example(yaml_weight_key: str) -> str:
    """REQ-004 [HARD]: 은퇴 대상 탐지기의 가중치를 0으로 처리했을 때 잔여 가중치를
    합=1.0으로 재정규화하는 예시 문자열을 생성한다.

    이 함수는 계산 결과를 리포트 텍스트로만 반환한다 — surge_detection.yaml을 읽거나
    쓰지 않는다(_CURRENT_ENSEMBLE_WEIGHTS는 하드코딩된 참조 스냅샷).
    """
    if yaml_weight_key not in _CURRENT_ENSEMBLE_WEIGHTS:
        return "재정규화 예시 계산 불가(알 수 없는 가중치 키)"

    remaining = {k: v for k, v in _CURRENT_ENSEMBLE_WEIGHTS.items() if k != yaml_weight_key}
    remaining_sum = sum(remaining.values())
    if remaining_sum <= 0:
        return "재정규화 예시 계산 불가(잔여 가중치 합 0)"

    scale = 1.0 / remaining_sum
    example = ", ".join(f"{k}={round(v * scale, 4)}" for k, v in remaining.items())
    return (
        f"잔여 가중치 재정규화 예시({yaml_weight_key} 제거, 합 {round(remaining_sum, 4)}→1.0 "
        f"스케일 {round(scale, 4)}x): {example}"
    )


def build_contribution_report(
    db: Session,
    run_date: date_,
    contribution_rows: Optional[list[SurgeDetectorContribution]] = None,
    retirement_assessments: Optional[dict[str, RetirementAssessment]] = None,
) -> str:
    """REQ-002/003/004: 탐지기 3분류 + dead-weight/consensus 뉘앙스 + 은퇴 제안(backtest
    판정 포함) + 잔여 가중치 재정규화 예시를 하나의 텍스트 리포트로 조립한다.

    [HARD] 이 함수는 어떤 파일에도 쓰지 않는다 — 순수 조회 + 문자열 조립.
    """
    if contribution_rows is None:
        contribution_rows = (
            db.query(SurgeDetectorContribution)
            .filter(SurgeDetectorContribution.run_date == run_date)
            .all()
        )
    metrics_by_detector = {r.detector: r for r in contribution_rows}

    if retirement_assessments is None:
        retirement_assessments = assess_retirement_candidates(db, run_date)

    lines: list[str] = [f"[SPEC-AI-070] 탐지기 기여도 리포트 — {run_date.isoformat()}", ""]

    category_sections = (
        ("(a) 앙상블 weighted_sum 편입", DETECTOR_CATEGORY_ENSEMBLE),
        ("(b) standalone/bypass 발신", DETECTOR_CATEGORY_STANDALONE),
        ("(c) 0-가중치", DETECTOR_CATEGORY_ZERO_WEIGHT),
    )
    for label, category_key in category_sections:
        lines.append(f"## {label}")
        for detector, info in DETECTOR_REGISTRY.items():
            if info.category != category_key:
                continue
            m = metrics_by_detector.get(detector)
            emission = m.emission_count if m else 0
            solo = m.solo_count if m else 0
            solo_tp = m.solo_tp if m else 0
            hit_rate = m.coincident_hit_rate if m else None
            unique_catch = m.unique_catch if m else 0
            weight_note = f" (yaml weight_key={info.yaml_weight_key})" if info.yaml_weight_key else ""
            structural_note = f" — {info.note}" if info.note else ""
            hit_rate_str = "null" if hit_rate is None else f"{hit_rate:.4f}"
            lines.append(
                f"- {detector}{weight_note}: emission={emission} solo={solo} "
                f"solo_tp={solo_tp} coincident_hit_rate={hit_rate_str} "
                f"unique_catch={unique_catch}{structural_note}"
            )
        lines.append("")

    # 레지스트리 밖 탐지기(방어적 — 신규 탐지기가 레지스트리 갱신 없이 추가된 경우)
    unclassified = [d for d in metrics_by_detector if d not in DETECTOR_REGISTRY]
    if unclassified:
        lines.append("## 미분류(레지스트리 갱신 필요)")
        for detector in sorted(unclassified):
            m = metrics_by_detector[detector]
            lines.append(f"- {detector}: emission={m.emission_count} (DETECTOR_REGISTRY에 없음)")
        lines.append("")

    lines.append("## 은퇴 제안 (069 backtest 검증)")
    any_proposal = False
    for detector, assessment in retirement_assessments.items():
        if not assessment.retire_candidate:
            continue
        any_proposal = True
        v = assessment.backtest_verdict
        before = v.before_accuracy if v else "N/A"
        after = v.after_accuracy if v else "N/A"
        lines.append(
            f"- {detector}: retire_candidate=true — {assessment.reason}. "
            f"backtest before={before} after={after} (제외해도 정확도 하락 없음)"
        )
        info = DETECTOR_REGISTRY.get(detector)
        if info and info.yaml_weight_key:
            # EC-4: weekend_gap_up처럼 weighted_sum에는 미반영이나 yaml weight가
            # validate_ensemble_weights 합계 검증에는 포함되는 경우도 재정규화 예시가 필요하다.
            lines.append(f"  {_renormalization_example(info.yaml_weight_key)}")
            if info.category == DETECTOR_CATEGORY_STANDALONE:
                lines.append(
                    "  참고: weighted_sum에는 미반영이나 yaml weight가 "
                    "validate_ensemble_weights 합계 검증에는 포함되므로, yaml에서 단순 제거 시 "
                    "합=1.0이 깨진다 — 위 재정규화 예시 또는 enabled=false 전환을 권고(EC-4)."
                )
        else:
            lines.append(
                "  적용 방법: standalone 탐지기이므로 surge_detection.yaml에서 해당 항목을 "
                "enabled=false로 수동 전환 권고(자동 적용 없음)."
            )
    if not any_proposal:
        lines.append("- 현재 은퇴 후보 없음")
    lines.append("")

    lines.append(
        "[HARD 안내] 본 리포트는 제안일 뿐이다 — surge_detection.yaml / "
        "surge_detection.auto.yaml은 이 잡에 의해 자동으로 수정되지 않는다. 은퇴 적용은 "
        "운영자가 base yaml을 직접 수동 편집해야만 반영된다(REQ-004)."
    )
    lines.append(
        "[각주 EC-6, 2026-07-02 정정] 탐지기별 component score는 일부만 영속화된다 — "
        "theme_cluster_score/combo_score/pattern_score/immediate_disclosure_score/"
        "legacy_score는 surge_metadata에 저장되지만(surge_detector.py:2291-2306), "
        "standalone/bypass 탐지기의 개별 점수는 저장되지 않는다. 본 리포트의 기여도는 "
        "모든 탐지기에 균일하게 surge_basis 멤버십 attribution을 적용한 근사치이며, "
        "탐지기를 제외한 정밀 재채점(counterfactual)이 아니다."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# REQ-005: 룰기반 → 학습형 앙상블 타당성 평가 (리포트 전용, 모델 미배포)
# ---------------------------------------------------------------------------


@dataclass
class LearnedEnsembleFeasibilityReport:
    """REQ-005 산출물 — 평가 리포트 텍스트 + 판단 메타데이터. 모델 자체는 반환하지 않는다."""

    text: str
    data_sufficiency: str  # "sufficient" | "insufficient"
    observation_count: int
    learned_accuracy: Optional[float] = None
    rule_based_accuracy: Optional[float] = None
    recommend_followup_spec: bool = False


def _sigmoid(x: float) -> float:
    """수치적으로 안정적인 시그모이드(오버플로 방지)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _train_logistic_regression(
    features: list[list[float]],
    labels: list[float],
    *,
    learning_rate: float = 0.1,
    epochs: int = 300,
) -> list[float]:
    """순수 파이썬 배치 경사하강 로지스틱 회귀(numpy/sklearn 미사용, AI-065 오프라인
    로지스틱 시드가 prior art). REQ-005 타당성 평가 전용 — 반환된 가중치는 이 함수
    호출 안에서만 쓰이고 저장·배포되지 않는다.

    Returns:
        [w_1, ..., w_n, bias] — 마지막 원소가 편향(bias)이다.
    """
    n_samples = len(features)
    n_features = len(features[0]) if features else 0
    weights = [0.0] * n_features
    bias = 0.0

    if n_samples == 0 or n_features == 0:
        return weights + [bias]

    for _ in range(epochs):
        grad_w = [0.0] * n_features
        grad_b = 0.0
        for xi, yi in zip(features, labels):
            z = bias + sum(w * x for w, x in zip(weights, xi))
            pred = _sigmoid(z)
            error = pred - yi
            for j in range(n_features):
                grad_w[j] += error * xi[j]
            grad_b += error
        weights = [w - learning_rate * (gw / n_samples) for w, gw in zip(weights, grad_w)]
        bias -= learning_rate * (grad_b / n_samples)

    return weights + [bias]


def _predict_logistic(weights_and_bias: list[float], xi: list[float]) -> float:
    *weights, bias = weights_and_bias
    z = bias + sum(w * x for w, x in zip(weights, xi))
    return _sigmoid(z)


# @MX:NOTE: [AUTO] SPEC-AI-070 REQ-005 — 평가 전용 함수. 여기서 학습된 로지스틱 가중치는
# 이 함수 호출 범위를 벗어나지 않으며 운영 앙상블(compute_ensemble_score)에 절대 연결되지
# 않는다. AI-065의 1회성 오프라인 로지스틱 시드가 prior art.
# @MX:SPEC: SPEC-AI-070 REQ-AI070-005
def assess_learned_ensemble_feasibility(db: Session) -> LearnedEnsembleFeasibilityReport:
    """REQ-005: 학습형 앙상블(오프라인 로지스틱)이 현행 룰기반 고정 가중치 대비
    scannable 정확도를 능가할 잠재력이 있는지 평가 리포트를 산출한다.

    피처: T-1 surge_candidate 시그널의 탐지기 멤버십 one-hot(레지스트리 앙상블 편입
    탐지기 기준). 라벨: 해당 종목이 T당일 scannable 실제급등주였는지(0/1).
    비교 기준(rule_based_accuracy): 현재 시스템이 실제로 발신한 모든 신호 중 scannable
    적중 비율(이미 임계값을 통과한 신호들의 실측 정밀도) — 로지스틱 모델의 in-sample
    분류 정확도(learned_accuracy)와 비교한다.

    [HARD] 어디에도 모델을 저장/배포/연결하지 않는다 — 텍스트 리포트만 반환.
    """
    from sqlalchemy import func as sqlfunc

    ensemble_detectors = sorted(
        d for d, info in DETECTOR_REGISTRY.items() if info.category == DETECTOR_CATEGORY_ENSEMBLE
    )

    # 관측 거래일 수 = surge_detector_contribution에 이미 축적된 run_date 종류 수
    observed_dates = {
        r.run_date
        for r in db.query(SurgeDetectorContribution.run_date).distinct().all()
    }
    observation_count = len(observed_dates)

    if observation_count < LEARNED_FEASIBILITY_MIN_TRADING_DAYS:
        text = (
            "[SPEC-AI-070 REQ-005] 학습형 앙상블 타당성 평가\n\n"
            f"데이터 충분성: 불충분 ({observation_count}/{LEARNED_FEASIBILITY_MIN_TRADING_DAYS} "
            "거래일 누적)\n"
            "예상 이득/손실: 산출 불가(표본 부족).\n"
            "권고: 후속 SPEC 불필요 — surge_detector_contribution 이력이 "
            f"{LEARNED_FEASIBILITY_MIN_TRADING_DAYS}거래일 이상 축적된 뒤 재평가할 것. "
            "현재는 룰기반 고정 가중치 유지를 권고한다."
        )
        return LearnedEnsembleFeasibilityReport(
            text=text,
            data_sufficiency="insufficient",
            observation_count=observation_count,
            recommend_followup_spec=False,
        )

    # 피처/라벨 구성: SurgeActualOutcome이 존재하는 모든 trading_date에 대해 T-1 신호를 순회
    outcome_dates = sorted({r.trading_date for r in db.query(SurgeActualOutcome.trading_date).distinct().all()})

    features: list[list[float]] = []
    labels: list[float] = []
    rule_correct = 0
    rule_total = 0

    for trading_date in outcome_dates:
        prev_business_day = _get_prev_business_day(trading_date)
        scannable_codes = {
            r.stock_code
            for r in db.query(SurgeActualOutcome.stock_code)
            .filter(
                SurgeActualOutcome.trading_date == trading_date,
                SurgeActualOutcome.surge_type == "scannable",
            )
            .all()
        }
        signal_rows = (
            db.query(FundSignal.surge_metadata, Stock.stock_code)
            .join(Stock, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.surge_metadata.isnot(None),
                sqlfunc.date(FundSignal.created_at) == prev_business_day,
            )
            .all()
        )
        for surge_metadata_raw, stock_code in signal_rows:
            basis = set(_parse_surge_basis_raw(surge_metadata_raw))
            if not basis:
                continue
            xi = [1.0 if d in basis else 0.0 for d in ensemble_detectors]
            is_hit = stock_code in scannable_codes
            yi = 1.0 if is_hit else 0.0
            features.append(xi)
            labels.append(yi)
            rule_total += 1
            if is_hit:
                rule_correct += 1

    if rule_total == 0:
        text = (
            "[SPEC-AI-070 REQ-005] 학습형 앙상블 타당성 평가\n\n"
            f"데이터 충분성: 불충분 (관측 거래일={observation_count}이나 매칭되는 "
            "surge_candidate 시그널 0건)\n"
            "예상 이득/손실: 산출 불가.\n"
            "권고: 후속 SPEC 불필요 — 신호 발신 이력이 축적된 뒤 재평가할 것."
        )
        return LearnedEnsembleFeasibilityReport(
            text=text,
            data_sufficiency="insufficient",
            observation_count=observation_count,
            recommend_followup_spec=False,
        )

    rule_based_accuracy = round(rule_correct / rule_total, 4)

    weights_and_bias = _train_logistic_regression(features, labels)
    learned_correct = 0
    for xi, yi in zip(features, labels):
        pred = 1.0 if _predict_logistic(weights_and_bias, xi) >= 0.5 else 0.0
        if pred == yi:
            learned_correct += 1
    learned_accuracy = round(learned_correct / rule_total, 4)

    delta = round(learned_accuracy - rule_based_accuracy, 4)
    recommend_followup = delta > 0.05  # 5%p 이상 개선 시에만 후속 SPEC 검토 권고

    text = (
        "[SPEC-AI-070 REQ-005] 학습형 앙상블 타당성 평가\n\n"
        f"데이터 충분성: 충분 (관측 {observation_count}거래일, 신호 {rule_total}건)\n"
        f"현행 룰기반 고정 가중치 실측 정밀도(rule_based_accuracy): {rule_based_accuracy}\n"
        f"학습형(오프라인 로지스틱, in-sample) 분류 정확도(learned_accuracy): {learned_accuracy}\n"
        f"예상 이득/손실(delta): {delta:+.4f}\n"
        "[한계] in-sample 근사치이며 교차검증(held-out)을 수행하지 않았다 — 엄밀한 "
        "성능 비교를 위해서는 후속 SPEC에서 시계열 분할 검증이 필요하다. 모델은 이 "
        "평가 범위에서만 존재하며 어디에도 저장/배포되지 않았다.\n"
        + (
            f"권고: delta={delta:+.4f} > 0.05 — 후속 SPEC(학습형 앙상블 프로토타입 + "
            "held-out 검증)을 검토할 가치가 있다."
            if recommend_followup
            else f"권고: delta={delta:+.4f} <= 0.05 — 현재는 룰기반 고정 가중치 유지를 "
            "권고한다. 후속 SPEC 불필요."
        )
    )

    return LearnedEnsembleFeasibilityReport(
        text=text,
        data_sufficiency="sufficient",
        observation_count=observation_count,
        learned_accuracy=learned_accuracy,
        rule_based_accuracy=rule_based_accuracy,
        recommend_followup_spec=recommend_followup,
    )
