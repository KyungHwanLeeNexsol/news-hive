"""SPEC-AI-041: 급등예측 탐지기별 적중률 기반 파라미터 자동 개선 서비스.

T-011: 5거래일 롤링 적중률을 기반으로 앙상블 가중치와 min_score_for_signal을
자동 조정하고 SurgeAutoImprovementLog에 기록한다.

T-012: 텔레그램용 일일 리포트 생성 및 발송.
"""

from __future__ import annotations

# @MX:NOTE: [AUTO] SPEC-AI-041 — 탐지기별 5거래일 롤링 적중률 기반 앙상블 가중치 자동 조정
# @MX:SPEC: SPEC-AI-041 REQ-AI041-003

import hashlib
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.improvement_log import ImprovementLog
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.surge_config.surge_settings import get_surge_config, reload_surge_config

logger = logging.getLogger(__name__)

# surge_detection.yaml 경로 (참조용 — 직접 수정하지 않음)
_YAML_PATH = Path(__file__).parent.parent / "surge_config" / "surge_detection.yaml"
# 자동 개선 오버라이드 파일 (git reset --hard에서 보호, .gitignore 등록됨)
_AUTO_YAML_PATH = Path(__file__).parent.parent / "surge_config" / "surge_detection.auto.yaml"

# 탐지기 이름 목록 (YAML 가중치 키와 동일) — 자동 개선 대상 탐지기
# @MX:NOTE: [AUTO] SPEC-AI-050 REQ-5 — weekend_gap_up은 커버리지 확장 탐지기로 자동 개선(가중치 조정) 제외
_DETECTORS = ["theme_cluster", "volume_news_combo", "disclosure_pattern", "legacy_detectors", "news_delayed"]

# 가중치 합산 검증 시 포함할 전체 탐지기 목록 (weekend_gap_up + volume_breakout 포함)
# volume_breakout은 자동 개선 대상 외 고정 가중치 — weekend_gap_up과 동일하게 취급
_ALL_WEIGHT_KEYS = [*_DETECTORS, "weekend_gap_up", "volume_breakout"]

# SPEC-AI-063 REQ-063-005: volume_breakout_bypass_threshold 자동 조정 클램프 범위
# max_score=0.50이므로 상한 0.45 이하, 하한 0.20 이상으로 제한
_VB_BYPASS_CLAMP_MIN: float = 0.20
_VB_BYPASS_CLAMP_MAX: float = 0.45


def _parse_detector_contributions(surge_metadata: dict[str, Any]) -> set[str]:
    """surge_metadata에서 기여한 탐지기 집합을 반환한다.

    surge_basis 리스트와 각 탐지기 점수 키를 모두 확인한다.
    KeyError 방지를 위해 .get()만 사용한다 (R4.3).
    """
    active: set[str] = set()
    surge_basis = surge_metadata.get("surge_basis", [])

    # theme_cluster
    if "theme_cluster" in surge_basis or (surge_metadata.get("theme_cluster_score", 0) or 0) > 0:
        active.add("theme_cluster")

    # volume_news_combo
    if "volume_news_combo" in surge_basis or (surge_metadata.get("combo_score", 0) or 0) > 0:
        active.add("volume_news_combo")

    # disclosure_pattern
    if "disclosure_pattern" in surge_basis or (surge_metadata.get("pattern_score", 0) or 0) > 0:
        active.add("disclosure_pattern")
    # immediate_disclosure_score도 disclosure_pattern으로 취급 (max 사용)
    if (surge_metadata.get("immediate_disclosure_score", 0) or 0) > 0:
        active.add("disclosure_pattern")

    # legacy_detectors
    if "legacy" in surge_basis or (surge_metadata.get("legacy_score", 0) or 0) > 0:
        active.add("legacy_detectors")

    # news_delayed
    if "news_delayed" in surge_basis or (surge_metadata.get("news_delayed_score", 0) or 0) > 0:
        active.add("news_delayed")

    return active


def _patch_yaml_values(yaml_path: str, updates: dict[str, float]) -> None:
    """YAML 파일의 특정 키 값을 라인 단위로 수정한다 (주석 보존).

    # @MX:WARN: [AUTO] surge_detection.yaml 직접 수정. sum==1.0 사전 검증 필수
    # @MX:REASON: YAML 자동 쓰기는 설정 손상 시 전체 시스템 영향

    updates 형식: {"ensemble.weights.theme_cluster": 0.25, "min_score_for_signal": 0.45}
    탐색 전략: 점 표기법 경로를 순차적으로 내려가며 indent 기반으로 키를 찾는다.
    """
    with open(yaml_path, encoding="utf-8") as f:
        lines = f.readlines()

    for dot_path, new_val in updates.items():
        parts = dot_path.split(".")
        result_lines = _replace_yaml_value(lines, parts, new_val)
        lines = result_lines

    with open(yaml_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _replace_yaml_value(lines: list[str], parts: list[str], new_val: float) -> list[str]:
    """라인 리스트에서 dot-path 경로에 해당하는 값을 교체한다."""
    result = list(lines)
    depth = 0  # 현재 탐색 중인 parts 인덱스
    # 각 parts 항목이 매칭된 라인의 indent 레벨을 추적
    parent_indent = -1  # 최상위 루트

    i = 0
    while i < len(result) and depth < len(parts):
        line = result[i]
        stripped = line.lstrip()

        # 빈 라인이나 주석 라인 건너뜀
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        current_indent = len(line) - len(stripped)
        target_key = parts[depth]

        # 현재 depth의 부모 indent보다 작거나 같은 indent 레벨로 돌아오면 탐색 범위 벗어남
        if depth > 0 and current_indent <= parent_indent:
            # 탐색 실패
            break

        # 키 매칭 확인
        if stripped.startswith(target_key + ":"):
            if depth == len(parts) - 1:
                # 최종 키 — 값 교체
                key_part = target_key + ":"
                # 인라인 주석 보존
                rest = stripped[len(key_part):]
                comment_idx = rest.find(" #")
                if comment_idx >= 0:
                    comment = rest[comment_idx:]
                else:
                    comment = ""
                # SPEC-AI-050 REQ-3: int 타입은 정수 포맷, float은 소수점 4자리
                if isinstance(new_val, int) and not isinstance(new_val, bool):
                    new_val_str = str(new_val)
                else:
                    new_val_str = f"{new_val:.4f}"
                new_line = line[: len(line) - len(stripped)] + f"{key_part} {new_val_str}{comment}\n"
                result[i] = new_line
                return result
            else:
                # 중간 키 — 다음 depth로 진입
                parent_indent = current_indent
                depth += 1
        i += 1

    logger.warning("YAML 패치 실패: 경로 '%s'를 찾을 수 없음", ".".join(parts))
    return result


def _write_auto_yaml(updates: dict[str, float]) -> None:
    """auto.yaml에 mutable 설정값을 누적 저장한다 (배포 후에도 유지됨).

    # @MX:NOTE: [AUTO] 메인 YAML 대신 auto.yaml에만 기록. git reset --hard에서 보호됨.

    updates 형식: {"ensemble.weights.theme_cluster": 0.25, "ensemble.min_score_for_signal": 0.43}
    dot-path는 surge_detection 아래 경로 (surge_detection 키 제외).
    기존 auto.yaml의 값을 로드한 후 덮어쓰는 방식으로 누적 저장한다.
    """
    # 기존 auto.yaml 로드 (없으면 빈 dict)
    auto_data: dict = {}
    if _AUTO_YAML_PATH.exists():
        with open(_AUTO_YAML_PATH, encoding="utf-8") as f:
            auto_data = yaml.safe_load(f) or {}

    # dot-path 업데이트: "ensemble.weights.theme_cluster" → surge_detection.ensemble.weights.theme_cluster
    for dot_path, new_val in updates.items():
        parts = ["surge_detection"] + dot_path.split(".")
        target = auto_data
        for key in parts[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[parts[-1]] = round(float(new_val), 4)

    with open(_AUTO_YAML_PATH, "w", encoding="utf-8") as f:
        f.write("# surge_detection.auto.yaml — 자동 생성 파일 (수동 편집 금지)\n")
        f.write("# 배포 시 git reset --hard에서 보호됨 (.gitignore). 자동개선 누적 설정.\n")
        yaml.dump(auto_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("auto.yaml 업데이트: %s", list(updates.keys()))


def _compute_param_set_hash(param_updates: dict[str, float]) -> str:
    """파라미터 업데이트 딕셔너리를 정렬된 JSON으로 직렬화하여 sha256 해시 앞 16자를 반환한다.

    # @MX:NOTE: [AUTO] SPEC-AI-061 — 롤백 진자현상 방지용 파라미터 집합 동일성 검사 함수
    # @MX:SPEC: SPEC-AI-061 REQ-AI061-A01
    """
    serialized = json.dumps(param_updates, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _check_rollback_guard(
    db: Session,
    trading_date: date,
    rollback_updates: dict[str, float],
    config: Any,
) -> tuple[bool, str | None]:
    """롤백 허용 여부를 검사한다. 진자현상 방지 가드.

    # @MX:WARN: [AUTO] SPEC-AI-061 — 롤백 가드: 두 가지 조건 중 하나라도 걸리면 롤백 차단
    # @MX:REASON: 진자현상(A→B→A 무한 반복) 방지. cooldown 및 연속 횟수 제한이 없으면
    #             recall≈0 상태에서 두 파라미터 집합 간 무한 진동이 발생함 (2026-06-19/22 실증)
    # @MX:SPEC: SPEC-AI-061 REQ-AI061-A02

    Returns:
        (allowed, suppression_reason) — allowed=False 시 suppression_reason이 설정됨.
    """
    # config 객체에서 설정값 추출 (없으면 안전 기본값 사용)
    rollback_cooldown_days: int = getattr(config, "rollback_cooldown_days", None) or 5
    consecutive_rollback_limit: int = getattr(config, "consecutive_rollback_limit", None) or 2

    incoming_hash = _compute_param_set_hash(rollback_updates)

    # 검사 1 (해시): 최근 rollback_cooldown_days 평가일에서 auto_rollback으로 적용된 파라미터 집합이
    # 입력 rollback_updates와 동일한지 확인
    from sqlalchemy import desc as _desc

    # 최근 N일치 auto_rollback 로그 조회 (날짜 기준 내림차순)
    recent_rollback_logs = (
        db.query(SurgeAutoImprovementLog)
        .filter(SurgeAutoImprovementLog.rationale == "auto_rollback")
        .order_by(_desc(SurgeAutoImprovementLog.evaluation_date))
        .limit(rollback_cooldown_days * 10)  # 넉넉하게 조회 후 날짜 필터링
        .all()
    )

    # 평가 날짜별 롤백 적용값 집합 계산 후 해시 비교
    from collections import defaultdict
    date_to_updates: dict[date, dict[str, float]] = defaultdict(dict)
    for log in recent_rollback_logs:
        date_to_updates[log.evaluation_date][log.parameter_path] = log.new_value

    # 최근 rollback_cooldown_days 개 평가일만 검사
    distinct_dates = sorted(date_to_updates.keys(), reverse=True)[:rollback_cooldown_days]
    for prev_date in distinct_dates:
        prev_hash = _compute_param_set_hash(date_to_updates[prev_date])
        if prev_hash == incoming_hash:
            logger.warning(
                "롤백 가드(해시): 최근 %d일 내 동일 파라미터 집합 롤백 시도 감지 (prev_date=%s). 차단.",
                rollback_cooldown_days,
                prev_date,
            )
            return False, "rollback_suppressed_pendulum"

    # 검사 2 (연속 횟수): 최근 평가일에서 연속으로 롤백 관련 rationale이 발생했는지 확인
    consecutive_rationales = {
        "auto_rollback",
        "rollback_suppressed_pendulum",
        "rollback_frozen_escalation",
    }
    # 가장 최근 평가 날짜들을 내림차순 조회
    all_recent = (
        db.query(SurgeAutoImprovementLog.evaluation_date)
        .filter(SurgeAutoImprovementLog.rationale.in_(list(consecutive_rationales)))
        .distinct()
        .order_by(_desc(SurgeAutoImprovementLog.evaluation_date))
        .limit(consecutive_rollback_limit + 1)
        .all()
    )
    # trading_date보다 이전인 날짜만 카운트
    consecutive_count = sum(
        1 for row in all_recent if row.evaluation_date < trading_date
    )
    if consecutive_count >= consecutive_rollback_limit:
        logger.warning(
            "롤백 가드(연속): %d일 연속 롤백/억제 감지 (limit=%d). 롤백 동결.",
            consecutive_count,
            consecutive_rollback_limit,
        )
        return False, "rollback_frozen_escalation"

    return True, None


# @MX:ANCHOR: [AUTO] SPEC-AI-061 — analyze_and_improve: 자동 개선 메인 진입점. scheduler, 복구 스크립트, 테스트 등 3곳 이상에서 호출됨
# @MX:NOTE: [AUTO] SPEC-AI-061 — EV가드: 기대값 음수 시 min_score 상향
def _compute_rolling_ev(
    db: Session, ev_window_days: int = 5
) -> tuple[float | None, int]:
    """최근 N개 failure_aggregation 로그에서 롤링 기대값(EV)을 계산한다.

    각 행의 details JSON에서 accuracy_rate, avg_return_correct,
    avg_return_incorrect를 파싱하여 EV를 계산한다:
        ev = accuracy_rate * avg_return_correct + (1 - accuracy_rate) * avg_return_incorrect

    Args:
        db: SQLAlchemy 세션
        ev_window_days: 조회할 최근 행 수 (기본값: 5)

    Returns:
        (mean_ev, n_samples) 튜플.
        - mean_ev: 파싱 성공한 행들의 EV 평균. 유효 행 없으면 None.
        - n_samples: details의 total_verified 합계 (없으면 파싱 성공 행 수).
    """
    import json as _json  # noqa: PLC0415 — 로컬 임포트로 최상위 네임스페이스 오염 방지

    rows = (
        db.query(ImprovementLog)
        .filter(ImprovementLog.action_type == "failure_aggregation")
        .order_by(ImprovementLog.id.desc())
        .limit(ev_window_days)
        .all()
    )

    ev_list: list[float] = []
    n_samples = 0

    for row in rows:
        if not row.details:
            continue
        try:
            d = _json.loads(row.details)
            accuracy_rate = float(d["accuracy_rate"])
            avg_return_correct = float(d["avg_return_correct"])
            avg_return_incorrect = float(d["avg_return_incorrect"])
        except (KeyError, TypeError, ValueError) as exc:
            # 파싱 실패 행은 조용히 건너뜀
            logger.debug("EV 계산 행 파싱 실패 (id=%s): %s", row.id, exc)
            continue

        ev_i = accuracy_rate * avg_return_correct + (1 - accuracy_rate) * avg_return_incorrect
        ev_list.append(ev_i)

        # total_verified 키가 있으면 신호 수로 집계, 없으면 행 1개로 카운트
        n_samples += int(d.get("total_verified", 1))

    if not ev_list:
        return None, 0

    mean_ev = sum(ev_list) / len(ev_list)
    return mean_ev, n_samples


# @MX:ANCHOR: [AUTO] analyze_and_improve — 파라미터 변경·DB 커밋·YAML 기록을 단일 트랜잭션으로 수행
# @MX:REASON: 파라미터 변경 + DB 커밋 + YAML 기록 + config 리로드를 단일 트랜잭션 내에서 수행.
#             시그니처 또는 반환 타입 변경 시 모든 호출자 동시 업데이트 필수
# @MX:SPEC: SPEC-AI-041 REQ-AI041-003
def analyze_and_improve(
    db: Session, trading_date: date
) -> list[SurgeAutoImprovementLog]:
    """평가 결과를 분석하여 앙상블 가중치와 min_score_for_signal을 자동 조정한다.

    Returns:
        생성된 SurgeAutoImprovementLog 목록. 변경 없으면 [].
    """
    logs: list[SurgeAutoImprovementLog] = []

    # ---------------------------------------------------------------------------
    # Step 1 — R11 Gate: 최소 5거래일 평가 필요
    # ---------------------------------------------------------------------------
    eval_count = (
        db.query(sqlfunc.count(SurgePredictionEvaluation.evaluation_date))
        .filter(SurgePredictionEvaluation.evaluation_date <= trading_date)
        .scalar()
        or 0
    )

    if eval_count < 5:
        logger.info(
            "R11 게이트: 평가 데이터 부족 (%d/5거래일) — 자동 개선 스킵", eval_count
        )
        return []

    # ---------------------------------------------------------------------------
    # Step 2 — 롤링 5거래일 탐지기별 적중률 계산 (R4)
    # ---------------------------------------------------------------------------
    last_5_evals = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date <= trading_date)
        .order_by(SurgePredictionEvaluation.evaluation_date.desc())
        .limit(5)
        .all()
    )

    eval_dates = [e.evaluation_date for e in last_5_evals]

    # 5거래일의 T-1 시그널(FundSignal + surge_metadata) 조회
    from app.services.surge_trading_service import _get_prev_business_day

    # 각 평가일에 대응하는 T-1 날짜
    t_minus_1_dates = [_get_prev_business_day(d) for d in eval_dates]

    # T-1 surge 시그널 전체 조회 (해당 날짜 범위)
    signal_rows = (
        db.query(FundSignal.stock_id, Stock.stock_code, FundSignal.surge_metadata,
                 sqlfunc.date(FundSignal.created_at).label("signal_date"))
        .join(Stock, FundSignal.stock_id == Stock.id)
        .filter(
            FundSignal.surge_metadata.isnot(None),
            sqlfunc.date(FundSignal.created_at).in_(t_minus_1_dates),
        )
        .all()
    )

    # 실제 급등주 조회 (5거래일 기간)
    actual_rows = (
        db.query(SurgeActualOutcome.stock_code, SurgeActualOutcome.trading_date)
        .filter(
            SurgeActualOutcome.trading_date.in_(eval_dates),
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )

    # 날짜별 실제 급등주 집합
    actual_by_date: dict[date, set[str]] = {}
    for row in actual_rows:
        actual_by_date.setdefault(row.trading_date, set()).add(row.stock_code)

    # T-1 날짜 → 평가일 매핑
    t1_to_eval: dict[date, date] = {t1: ev for t1, ev in zip(t_minus_1_dates, eval_dates)}

    # 탐지기별 (기여 시그널 수, TP 시그널 수) 집계
    detector_total: dict[str, int] = {d: 0 for d in _DETECTORS}
    detector_tp: dict[str, int] = {d: 0 for d in _DETECTORS}

    for row in signal_rows:
        signal_date = row.signal_date
        if isinstance(signal_date, str):
            from datetime import date as date_cls
            signal_date = date_cls.fromisoformat(signal_date)

        eval_date = t1_to_eval.get(signal_date)
        if eval_date is None:
            continue

        actual_surges = actual_by_date.get(eval_date, set())
        is_tp = row.stock_code in actual_surges

        # surge_metadata 파싱
        try:
            if isinstance(row.surge_metadata, str):
                metadata = json.loads(row.surge_metadata)
            else:
                metadata = row.surge_metadata or {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        active_detectors = _parse_detector_contributions(metadata)

        for det in active_detectors:
            if det in detector_total:
                detector_total[det] += 1
                if is_tp:
                    detector_tp[det] += 1

    # 탐지기별 적중률 계산
    hit_rates: dict[str, float] = {}
    for det in _DETECTORS:
        total = detector_total[det]
        hit_rates[det] = detector_tp[det] / total if total > 0 else 0.0

    logger.info("탐지기별 적중률: %s", hit_rates)

    # ---------------------------------------------------------------------------
    # Step 3 — 가중치 비례 조정 (R5)
    # ---------------------------------------------------------------------------
    cfg = get_surge_config()
    current_weights = {
        "theme_cluster": cfg.ensemble.weights.theme_cluster,
        "volume_news_combo": cfg.ensemble.weights.volume_news_combo,
        "disclosure_pattern": cfg.ensemble.weights.disclosure_pattern,
        "legacy_detectors": cfg.ensemble.weights.legacy_detectors,
        "news_delayed": cfg.ensemble.weights.news_delayed,
    }

    # 모든 적중률이 0이면 가중치 조정 스킵
    if sum(hit_rates.values()) == 0.0:
        logger.info("모든 탐지기 적중률 0 — 가중치 조정 스킵")
        # min_score 조정만 수행하기 위해 계속 진행
        final_weight = dict(current_weights)
    else:
        # 비례 조정
        raw: dict[str, float] = {
            d: current_weights[d] * hit_rates[d] for d in _DETECTORS
        }
        raw_total = sum(raw.values())

        if raw_total == 0.0:
            final_weight = dict(current_weights)
        else:
            # 정규화
            normalized = {d: raw[d] / raw_total for d in _DETECTORS}

            # 클램프 [0.05, 0.45]
            clamped = {d: max(0.05, min(0.45, normalized[d])) for d in _DETECTORS}

            # 클램핑 후 재정규화
            clamped_total = sum(clamped.values())
            renorm = {d: clamped[d] / clamped_total for d in _DETECTORS}

            # 일일 변동폭 ±0.05 캡 (R5.4)
            daily_capped = {
                d: max(current_weights[d] - 0.05, min(current_weights[d] + 0.05, renorm[d]))
                for d in _DETECTORS
            }

            # 마지막 재정규화: weekend_gap_up(고정) 제외 비율로 스케일링
            # _DETECTORS 5개 합산 목표 = 1.0 - weekend_gap_up - volume_breakout (고정 가중치 제외)
            _fixed_weight = (
                cfg.ensemble.weights.weekend_gap_up
                + cfg.ensemble.weights.volume_breakout
            )
            _wgu_target = 1.0 - _fixed_weight
            cap_total = sum(daily_capped.values())
            final_weight = {d: daily_capped[d] / cap_total * _wgu_target for d in _DETECTORS}

    # 사전 검증 (CRITICAL): _DETECTORS + weekend_gap_up + volume_breakout(고정) 합산 = 1.0
    # weekend_gap_up, volume_breakout은 자동 개선 대상 외 → 현재 YAML 값 유지
    _fixed_total = (
        cfg.ensemble.weights.weekend_gap_up
        + cfg.ensemble.weights.volume_breakout
    )
    weight_sum = sum(final_weight.values()) + _fixed_total
    assert abs(weight_sum - 1.0) <= 0.001, (
        f"앙상블 가중치 합산 오류: {weight_sum:.6f} (1.0이어야 함)"
    )

    # ---------------------------------------------------------------------------
    # Step 4 — min_score_for_signal 조정 (R6)
    # ---------------------------------------------------------------------------
    today_eval = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .first()
    )

    current_min_score = cfg.ensemble.min_score_for_signal
    new_min_score = current_min_score

    if today_eval is not None:
        recall = today_eval.recall or 0.0
        precision = today_eval.precision or 0.0

        if recall < 0.30:
            delta = -0.02
        elif recall > 0.60 or precision < 0.20:
            delta = +0.02
        else:
            delta = 0.0

        new_min_score = max(0.35, min(0.65, current_min_score + delta))
        logger.info(
            "min_score 조정: %.3f → %.3f (recall=%.3f, precision=%.3f, delta=%+.2f)",
            current_min_score, new_min_score, recall, precision, delta,
        )

    # ---------------------------------------------------------------------------
    # Step 4.3 — SPEC-AI-063 REQ-063-005: volume_breakout_bypass_threshold 자동 조정
    # recall 기반으로 threshold를 [0.20, 0.45] 범위 내에서 조정
    # recall 낮음 → threshold 하향(더 많은 bypass 허용), 높고 precision 낮음 → threshold 상향
    # @MX:NOTE: [AUTO] SPEC-AI-063 — [0.20, 0.45] 클램프 근거: max_score=0.50이므로 상한 0.45 이하
    # @MX:SPEC: SPEC-AI-063 REQ-063-005
    # ---------------------------------------------------------------------------
    _VB_BYPASS_DELTA: float = 0.02
    current_vb_bypass: float = float(
        getattr(cfg.volume_breakout, "volume_breakout_bypass_threshold", 0.30) or 0.30
    )
    new_vb_bypass = current_vb_bypass

    if today_eval is not None:
        recall_vb = today_eval.recall or 0.0
        precision_vb = today_eval.precision or 0.0

        if recall_vb < 0.30:
            # recall 낮음 → threshold 낮춰 더 많은 거래량 폭발 종목 bypass 허용
            new_vb_bypass = max(_VB_BYPASS_CLAMP_MIN, current_vb_bypass - _VB_BYPASS_DELTA)
        elif recall_vb > 0.60 or precision_vb < 0.20:
            # recall 과다 또는 precision 낮음 → threshold 높여 bypass 제한
            new_vb_bypass = min(_VB_BYPASS_CLAMP_MAX, current_vb_bypass + _VB_BYPASS_DELTA)

        if abs(new_vb_bypass - current_vb_bypass) > 1e-6:
            logger.info(
                "volume_breakout_bypass_threshold 조정: %.3f → %.3f "
                "(recall=%.3f, precision=%.3f)",
                current_vb_bypass, new_vb_bypass, recall_vb, precision_vb,
            )

    # ---------------------------------------------------------------------------
    # Step 4.5 — SPEC-AI-061 REQ-AI061-C01~C04: EV 가드
    # 롤링 기대값(EV)이 음수이면 min_score_for_signal을 상향하여 저품질 신호 필터링
    # ---------------------------------------------------------------------------
    _ev_window_days: int = int(getattr(cfg, "ev_window_days", None) or 5)
    _ev_min_samples: int = int(getattr(cfg, "ev_min_samples", None) or 20)
    _ev_floor: float = float(getattr(cfg, "ev_floor", None) or 0.0)
    _ev_penalty_step: float = float(getattr(cfg, "ev_penalty_step", None) or 0.02)

    _mean_ev, _n_samples = _compute_rolling_ev(db, ev_window_days=_ev_window_days)

    if _mean_ev is None:
        logger.debug(
            "EV 가드: failure_aggregation 데이터 없음 — 가드 스킵 (window=%d)",
            _ev_window_days,
        )
    elif _n_samples < _ev_min_samples:
        logger.debug(
            "EV 가드: 샘플 수 부족 (%d < %d) — 가드 스킵 (mean_ev=%.3f)",
            _n_samples,
            _ev_min_samples,
            _mean_ev,
        )
    elif _mean_ev < _ev_floor:
        # EV가 floor 미만 → min_score 상향
        _ev_current_score = get_surge_config().ensemble.min_score_for_signal
        _ev_new_score = min(0.65, _ev_current_score + _ev_penalty_step)
        _write_auto_yaml({"ensemble.min_score_for_signal": _ev_new_score})
        reload_surge_config()

        _ev_log = SurgeAutoImprovementLog(
            evaluation_date=trading_date,
            parameter_path="ensemble.min_score_for_signal",
            old_value=round(_ev_current_score, 6),
            new_value=round(_ev_new_score, 6),
            rationale=f"ev_guard: EV={_mean_ev:.3f}<{_ev_floor:.3f}",
            rolling_window_days=_ev_window_days,
        )
        db.add(_ev_log)
        db.commit()
        logs.append(_ev_log)

        # 이후 min_score 변경 비교에도 반영
        new_min_score = _ev_new_score

        logger.info(
            "EV 가드 발동: EV=%.3f < floor=%.3f → min_score %.3f → %.3f (n_samples=%d)",
            _mean_ev,
            _ev_floor,
            _ev_current_score,
            _ev_new_score,
            _n_samples,
        )
    else:
        logger.debug(
            "EV 가드: EV=%.3f >= floor=%.3f (n_samples=%d) — 가드 불필요",
            _mean_ev,
            _ev_floor,
            _n_samples,
        )

    # ---------------------------------------------------------------------------
    # Step 5 — R12 자동 롤백 검사
    # ---------------------------------------------------------------------------
    recall_values = [e.recall or 0.0 for e in last_5_evals]
    rolling_avg_recall = sum(recall_values) / len(recall_values) if recall_values else 0.0

    # 이전 날짜 평가
    prev_eval = last_5_evals[1] if len(last_5_evals) >= 2 else None

    if (
        prev_eval is not None
        and prev_eval.recall is not None
        and rolling_avg_recall > 0.0
        and prev_eval.recall < rolling_avg_recall * 0.80
    ):
        # 전날 적용된 로그 조회
        prev_logs = (
            db.query(SurgeAutoImprovementLog)
            .filter(SurgeAutoImprovementLog.evaluation_date == prev_eval.evaluation_date)
            .all()
        )

        if prev_logs:
            logger.warning(
                "R12 자동 롤백 발동: prev_recall=%.3f < rolling_avg*0.80=%.3f",
                prev_eval.recall, rolling_avg_recall * 0.80,
            )

            # ---------------------------------------------------------------------------
            # SPEC-AI-061 REQ-AI061-A03: 롤백 실행 전 진자현상 가드 검사
            # ---------------------------------------------------------------------------
            # 롤백 대상 파라미터 값 미리 계산 (가드 검사용)
            rollback_updates: dict[str, float] = {
                prev_log.parameter_path: prev_log.old_value
                for prev_log in prev_logs
            }
            _guard_cfg = get_surge_config()
            _allowed, _suppression_reason = _check_rollback_guard(
                db, trading_date, rollback_updates, _guard_cfg
            )

            if not _allowed:
                # 가드에 의해 롤백 차단: 억제 로그만 기록하고 반환
                logger.warning(
                    "롤백 가드 작동으로 롤백 차단 (reason=%s). auto.yaml 변경 없음.",
                    _suppression_reason,
                )
                for prev_log in prev_logs:
                    _suppressed_log = SurgeAutoImprovementLog(
                        evaluation_date=trading_date,
                        parameter_path=prev_log.parameter_path,
                        old_value=prev_log.new_value,
                        new_value=prev_log.old_value,
                        rationale=_suppression_reason,
                        rolling_window_days=5,
                    )
                    db.add(_suppressed_log)
                    logs.append(_suppressed_log)
                db.commit()
                return logs

            for prev_log in prev_logs:
                rollback_log = SurgeAutoImprovementLog(
                    evaluation_date=trading_date,
                    parameter_path=prev_log.parameter_path,
                    old_value=prev_log.new_value,
                    new_value=prev_log.old_value,
                    rationale="auto_rollback",
                    rolling_window_days=5,
                )
                db.add(rollback_log)
                logs.append(rollback_log)

            db.commit()

            # 롤백 값을 auto.yaml에 적용 (메인 YAML은 수정하지 않음)
            _write_auto_yaml(rollback_updates)
            reload_surge_config()

            return logs

    # ---------------------------------------------------------------------------
    # Step 5.5 — SPEC-AI-050 REQ-3: 3일 연속 recall=0 + 탐지기 기여=0 → 윈도우 확장
    # ---------------------------------------------------------------------------
    # 탐지기별 기여율 (detector_hit_rates: 탐지기명 → 기여율, 단 0분모이면 0.0)
    detector_hit_rates: dict[str, float] = dict(hit_rates)

    recent_3_recalls = recall_values[:3] if len(recall_values) >= 3 else []
    all_zero_recall = len(recent_3_recalls) == 3 and all(r == 0.0 for r in recent_3_recalls)
    all_zero_contrib = all(v == 0.0 for v in detector_hit_rates.values())

    if all_zero_recall and all_zero_contrib:
        # 현재 시장 레짐 조회 (가장 최근 평가일 기준)
        _current_cfg = get_surge_config()
        # BEAR 레짐 우선 (보수적), 없으면 SIDEWAYS
        _candidate_regimes = list(_current_cfg.regime_detector_params.keys())
        _current_regime = _candidate_regimes[0] if _candidate_regimes else "BEAR"

        _regime_param = _current_cfg.regime_detector_params.get(_current_regime)
        if _regime_param is not None:
            current_window = _regime_param.news_window_hours
            if current_window >= 48:
                logger.info(
                    "[REQ-3] 윈도우 상한 48h 도달 (%d) — 추가 확장 없음",
                    current_window,
                )
            else:
                new_window = min(48, current_window + 12)
                regime_key = f"regime_detector_params.{_current_regime}.news_window_hours"
                _write_auto_yaml({regime_key: float(new_window)})
                reload_surge_config()
                _window_log = SurgeAutoImprovementLog(
                    evaluation_date=trading_date,
                    parameter_path=regime_key,
                    old_value=float(current_window),
                    new_value=float(new_window),
                    rationale="recall=0 3일 연속 + 탐지기 기여=0 → coverage gap 보완 윈도우 확장",
                    rolling_window_days=3,
                )
                db.add(_window_log)
                logs.append(_window_log)
                logger.info(
                    "[REQ-3] 3일 연속 recall=0 + 탐지기 기여=0: %s %dh → %dh",
                    regime_key,
                    current_window,
                    new_window,
                )

    # ---------------------------------------------------------------------------
    # Step 6 — YAML 대상 업데이트 (주석 보존 라인 패치)
    # ---------------------------------------------------------------------------
    yaml_updates: dict[str, float] = {}

    # 가중치 변경분
    for det in _DETECTORS:
        old_w = current_weights[det]
        new_w = final_weight[det]
        if abs(new_w - old_w) > 1e-6:
            yaml_updates[f"ensemble.weights.{det}"] = new_w

    # min_score 변경분
    if abs(new_min_score - current_min_score) > 1e-6:
        yaml_updates["ensemble.min_score_for_signal"] = new_min_score

    # SPEC-AI-063 REQ-063-005: volume_breakout_bypass_threshold 변경분
    # dot-path: volume_breakout.volume_breakout_bypass_threshold (surge_detection 아래)
    if abs(new_vb_bypass - current_vb_bypass) > 1e-6:
        yaml_updates["volume_breakout.volume_breakout_bypass_threshold"] = new_vb_bypass

    # SPEC-AI-050 REQ-2 클램프: BEAR.news_window_hours < 24이면 24로 강제 조정
    for key, val in list(yaml_updates.items()):
        if "BEAR.news_window_hours" in key and val < 24:
            logger.warning(
                "[REQ-2 클램프] BEAR.news_window_hours %s < 24 → 24로 클램프",
                val,
            )
            yaml_updates[key] = 24

    if yaml_updates:
        _write_auto_yaml(yaml_updates)
        reload_surge_config()
        logger.info("auto.yaml 업데이트 완료: %s", list(yaml_updates.keys()))

    # ---------------------------------------------------------------------------
    # Step 7 — 로그 기록 (R7)
    # ---------------------------------------------------------------------------
    for det in _DETECTORS:
        old_w = current_weights[det]
        new_w = final_weight[det]
        if abs(new_w - old_w) <= 1e-6:
            continue  # R7.2: 변경 없으면 로그 미생성

        log = SurgeAutoImprovementLog(
            evaluation_date=trading_date,
            parameter_path=f"ensemble.weights.{det}",
            old_value=round(old_w, 6),
            new_value=round(new_w, 6),
            rationale=(
                f"5거래일 롤링 적중률 기반 조정: hit_rate={hit_rates[det]:.3f}"
                f" (기여={detector_total[det]}회, TP={detector_tp[det]}회)"
            ),
            rolling_window_days=5,
        )
        db.add(log)
        logs.append(log)

    if abs(new_min_score - current_min_score) > 1e-6:
        log = SurgeAutoImprovementLog(
            evaluation_date=trading_date,
            parameter_path="ensemble.min_score_for_signal",
            old_value=round(current_min_score, 6),
            new_value=round(new_min_score, 6),
            rationale=(
                f"recall/precision 기반 조정: recall={today_eval.recall if today_eval else 'N/A':.3f}"
                if today_eval and today_eval.recall is not None
                else "recall/precision 기반 조정"
            ),
            rolling_window_days=5,
        )
        db.add(log)
        logs.append(log)

    # SPEC-AI-063 REQ-063-005: volume_breakout_bypass_threshold 변경 로그
    if abs(new_vb_bypass - current_vb_bypass) > 1e-6:
        _vb_log = SurgeAutoImprovementLog(
            evaluation_date=trading_date,
            parameter_path="volume_breakout.volume_breakout_bypass_threshold",
            old_value=round(current_vb_bypass, 6),
            new_value=round(new_vb_bypass, 6),
            rationale=(
                f"recall/precision 기반 volume_breakout bypass threshold 조정: "
                f"recall={today_eval.recall if today_eval else 'N/A'}"
                if today_eval and today_eval.recall is not None
                else "recall/precision 기반 조정"
            ),
            rolling_window_days=5,
        )
        db.add(_vb_log)
        logs.append(_vb_log)

    if logs:
        db.commit()
        logger.info("자동 개선 로그 %d건 저장 완료", len(logs))
    else:
        logger.info("파라미터 변경 없음 — 개선 로그 없음")

    return logs


def format_telegram_report(
    evaluation: SurgePredictionEvaluation,
    improvements: list[SurgeAutoImprovementLog],
    missed_top3: list[dict],
) -> str:
    """일일 급등 예측 평가 결과 텔레그램 리포트 문자열을 생성한다.

    Args:
        evaluation: SurgePredictionEvaluation 인스턴스
        improvements: 오늘 적용된 SurgeAutoImprovementLog 목록
        missed_top3: 놓친 종목 상위 3개 (dict with stock_name, change_rate)

    Returns:
        한국어 리포트 문자열
    """
    has_rollback = any(imp.rationale == "auto_rollback" for imp in improvements)

    lines = [
        f"[급등 예측 평가] {evaluation.evaluation_date}",
        "",
        f"정밀도(Precision): {evaluation.precision:.3f}" if evaluation.precision is not None else "정밀도: N/A",
        f"재현율(Recall): {evaluation.recall:.3f}" if evaluation.recall is not None else "재현율: N/A",
        f"F1 Score: {evaluation.f1_score:.3f}" if evaluation.f1_score is not None else "F1: N/A",
        "",
        f"TP(적중): {evaluation.true_positive}  FP(오예측): {evaluation.false_positive}  FN(미탐지): {evaluation.false_negative}",
        f"실제 급등주 수: {evaluation.actual_surge_count}",
        "",
    ]

    if missed_top3:
        lines.append("놓친 종목 상위 3:")
        for item in missed_top3:
            name = item.get("stock_name", item.get("stock_code", "?"))
            rate = item.get("change_rate", 0.0)
            lines.append(f"  - {name} (+{rate:.1f}%)")
        lines.append("")

    if improvements:
        lines.append("파라미터 변경:")
        for imp in improvements:
            lines.append(f"  {imp.parameter_path}: {imp.old_value:.3f} → {imp.new_value:.3f}")
        if has_rollback:
            lines.append("")
            lines.append("⚠️ 자동 롤백 적용됨")
    else:
        lines.append("파라미터 변경 없음")

    return "\n".join(lines)


async def run_daily_report(db: Session, trading_date: date) -> None:
    """일일 평가 결과 리포트를 생성하고 텔레그램으로 발송한다.

    Args:
        db: SQLAlchemy 동기 세션
        trading_date: 리포트 기준 날짜
    """
    # 1. 평가 결과 조회
    evaluation = (
        db.query(SurgePredictionEvaluation)
        .filter(SurgePredictionEvaluation.evaluation_date == trading_date)
        .first()
    )
    if evaluation is None:
        logger.info("평가 결과 없음 (date=%s) — 리포트 스킵", trading_date)
        return

    # 2. 오늘 적용된 개선 로그 조회
    improvements = (
        db.query(SurgeAutoImprovementLog)
        .filter(SurgeAutoImprovementLog.evaluation_date == trading_date)
        .all()
    )

    # 3. 놓친 종목 상위 3개 조회
    # T-1 예측 집합 구성
    from app.services.surge_trading_service import _get_prev_business_day

    prev_day = _get_prev_business_day(trading_date)

    predicted_codes = {
        row.stock_code
        for row in (
            db.query(Stock.stock_code)
            .join(FundSignal, FundSignal.stock_id == Stock.id)
            .filter(
                FundSignal.surge_metadata.isnot(None),
                sqlfunc.date(FundSignal.created_at) == prev_day,
            )
            .all()
        )
    }

    missed_rows = (
        db.query(
            SurgeActualOutcome.stock_code,
            SurgeActualOutcome.stock_name,
            SurgeActualOutcome.change_rate,
        )
        .filter(
            SurgeActualOutcome.trading_date == trading_date,
            SurgeActualOutcome.was_surge.is_(True),
        )
        .all()
    )

    missed_top3 = sorted(
        [
            {"stock_code": r.stock_code, "stock_name": r.stock_name, "change_rate": r.change_rate}
            for r in missed_rows
            if r.stock_code not in predicted_codes
        ],
        key=lambda x: x["change_rate"],
        reverse=True,
    )[:3]

    # 4. 리포트 생성
    report_text = format_telegram_report(evaluation, improvements, missed_top3)

    # 5. 텔레그램 발송
    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not chat_id:
        logger.info("TELEGRAM_ADMIN_CHAT_ID 미설정, 리포트 전송 스킵")
        return

    from app.services.telegram_service import send_telegram_message

    success = await send_telegram_message(chat_id, report_text)
    if success:
        logger.info("일일 급등 예측 리포트 발송 완료 (date=%s)", trading_date)
    else:
        logger.warning("일일 급등 예측 리포트 발송 실패 (date=%s)", trading_date)
