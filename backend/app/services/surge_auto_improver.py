"""SPEC-AI-041: 급등예측 탐지기별 적중률 기반 파라미터 자동 개선 서비스.

T-011: 5거래일 롤링 적중률을 기반으로 앙상블 가중치와 min_score_for_signal을
자동 조정하고 SurgeAutoImprovementLog에 기록한다.

T-012: 텔레그램용 일일 리포트 생성 및 발송.
"""

from __future__ import annotations

# @MX:NOTE: [AUTO] SPEC-AI-041 — 탐지기별 5거래일 롤링 적중률 기반 앙상블 가중치 자동 조정
# @MX:SPEC: SPEC-AI-041 REQ-AI041-003

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_auto_improvement_log import SurgeAutoImprovementLog
from app.models.surge_prediction_evaluation import SurgePredictionEvaluation
from app.surge_config.surge_settings import get_surge_config, reload_surge_config

logger = logging.getLogger(__name__)

# surge_detection.yaml 경로
_YAML_PATH = Path(__file__).parent.parent / "surge_config" / "surge_detection.yaml"

# 탐지기 이름 목록 (YAML 가중치 키와 동일)
_DETECTORS = ["theme_cluster", "volume_news_combo", "disclosure_pattern", "legacy_detectors", "news_delayed"]


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
                # 소수점 4자리로 포맷
                new_line = line[: len(line) - len(stripped)] + f"{key_part} {new_val:.4f}{comment}\n"
                result[i] = new_line
                return result
            else:
                # 중간 키 — 다음 depth로 진입
                parent_indent = current_indent
                depth += 1
        i += 1

    logger.warning("YAML 패치 실패: 경로 '%s'를 찾을 수 없음", ".".join(parts))
    return result


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

            # 마지막 재정규화
            cap_total = sum(daily_capped.values())
            final_weight = {d: daily_capped[d] / cap_total for d in _DETECTORS}

    # 사전 검증 (CRITICAL)
    weight_sum = sum(final_weight.values())
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

            # 롤백 값을 실제 YAML에 적용
            rollback_updates: dict[str, float] = {}
            for prev_log in prev_logs:
                rollback_updates[prev_log.parameter_path] = prev_log.old_value

            _patch_yaml_values(str(_YAML_PATH), rollback_updates)
            reload_surge_config()

            return logs

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

    if yaml_updates:
        _patch_yaml_values(str(_YAML_PATH), yaml_updates)
        reload_surge_config()
        logger.info("YAML 업데이트 완료: %s", list(yaml_updates.keys()))

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
