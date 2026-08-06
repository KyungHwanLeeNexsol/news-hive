"""SPEC-AI-036: isotonic 신뢰도 캘리브레이터.

Pool Adjacent Violators (PAV) 알고리즘으로 단조 증가 보정 함수를 학습한다.
numpy / scikit-learn 의존성 없이 순수 Python만 사용한다.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# pickle 파일 저장 경로
_CALIBRATOR_PATH = Path(__file__).parent.parent.parent / "data" / "surge_calibrator.pkl"

# SPEC-AI-107: 섀도우 학습 candidate 아티팩트 + 실행 로그 경로 (active 경로와 분리)
_CANDIDATE_DIR = Path(__file__).parent.parent.parent / "data" / "surge_calibrator"
_RUN_LOG_PATH = _CANDIDATE_DIR / "runs.jsonl"

# 최소 학습 샘플 수 미달 시 identity fallback
_DEFAULT_MIN_CALIBRATION_SAMPLES = 50


@dataclass
class IsotonicModel:
    """Pool Adjacent Violators 학습 결과 모델.

    breakpoints: (raw_confidence, calibrated_confidence) 순서쌍 리스트.
    단조 증가 보장. predict() 호출 시 선형 보간으로 값을 산출한다.
    """

    # (raw, calibrated) 쌍의 단조 증가 리스트
    breakpoints: list[tuple[float, float]] = field(default_factory=list)
    trained_at: str = ""
    sample_count: int = 0
    # 캘리브레이션을 건너뛴 경우 True → predict() = identity
    is_identity: bool = False

    def predict(self, raw: float) -> float:
        """raw confidence → 보정된 confidence (0.0~1.0).

        breakpoints 범위 바깥은 경계값으로 클램프.
        is_identity=True이면 raw 그대로 반환.
        """
        if self.is_identity or not self.breakpoints:
            return max(0.0, min(1.0, raw))

        xs = [bp[0] for bp in self.breakpoints]
        ys = [bp[1] for bp in self.breakpoints]

        # 범위 바깥 클램프
        if raw <= xs[0]:
            return max(0.0, min(1.0, ys[0]))
        if raw >= xs[-1]:
            return max(0.0, min(1.0, ys[-1]))

        # 이진 탐색으로 구간 찾기
        lo, hi = 0, len(xs) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if xs[mid] <= raw:
                lo = mid
            else:
                hi = mid

        # 선형 보간
        x0, y0 = xs[lo], ys[lo]
        x1, y1 = xs[hi], ys[hi]
        if x1 == x0:
            return max(0.0, min(1.0, (y0 + y1) / 2.0))

        t = (raw - x0) / (x1 - x0)
        result = y0 + t * (y1 - y0)
        return max(0.0, min(1.0, result))


def _run_pav(pairs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pool Adjacent Violators (PAV) 알고리즘.

    Args:
        pairs: (raw_confidence, is_correct_float) 정렬된 리스트.
               is_correct_float ∈ {0.0, 1.0}.

    Returns:
        단조 증가 보장된 (raw_confidence, calibrated_prob) 리스트.
        같은 raw 값이 여러 개면 평균으로 대표점 생성.
    """
    if not pairs:
        return []

    # 블록: [sum_y, count, x_representative]
    blocks: list[list[float]] = []
    for x, y in pairs:
        blocks.append([y, 1.0, x])

        # 단조 위반 병합 (역방향)
        while len(blocks) >= 2:
            b1 = blocks[-2]
            b2 = blocks[-1]
            avg1 = b1[0] / b1[1]
            avg2 = b2[0] / b2[1]
            if avg1 <= avg2:
                break
            # 병합
            merged_sum = b1[0] + b2[0]
            merged_cnt = b1[1] + b2[1]
            # x 대표값: 원래 b1의 x (정렬된 pairs에서 b1이 작은 x 범위)
            merged_x = b1[2]
            blocks.pop()
            blocks.pop()
            blocks.append([merged_sum, merged_cnt, merged_x])

    # 블록을 (x, calibrated_prob) 쌍으로 변환
    result: list[tuple[float, float]] = []
    for b in blocks:
        prob = b[0] / b[1]
        x = b[2]
        result.append((x, prob))

    return result


def train_isotonic(
    pairs: list[tuple[float, int]],
    min_calibration_samples: int = _DEFAULT_MIN_CALIBRATION_SAMPLES,
    min_positive_samples: int | None = None,
) -> IsotonicModel:
    """PAV 알고리즘으로 IsotonicModel을 학습한다.

    Args:
        pairs: (raw_confidence, is_correct) 리스트.
               is_correct ∈ {0, 1} (검증 완료 시그널만 포함해야 함).
        min_calibration_samples: 최소 샘플 수. 미달 시 identity 반환.
        min_positive_samples: SPEC-AI-107 REQ-AI107-007 — 최소 positive 표본 수 가드
            (옵션, 하위 호환). None(기본값)이면 이 SPEC 이전과 완전히 동일하게 동작한다.
            값이 설정되면 표본 수/불균형 체크를 통과한 뒤에도 positive 표본 수가 이
            값 미만이면 identity fallback을 반환한다.

    Returns:
        IsotonicModel. 건너뛴 경우 is_identity=True.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if len(pairs) < min_calibration_samples:
        logger.info(
            "캘리브레이터 학습 스킵 — 샘플 수 부족 (%d < %d)",
            len(pairs),
            min_calibration_samples,
        )
        return IsotonicModel(
            is_identity=True,
            trained_at=now_iso,
            sample_count=len(pairs),
        )

    # positive ratio 검사 (0% 또는 100%이면 스킵)
    n_pos = sum(1 for _, is_c in pairs if is_c == 1)
    pos_ratio = n_pos / len(pairs)
    if pos_ratio == 0.0 or pos_ratio == 1.0:
        logger.info(
            "캘리브레이터 학습 스킵 — positive ratio=%.2f (0%% 또는 100%% 불균형)",
            pos_ratio,
        )
        return IsotonicModel(
            is_identity=True,
            trained_at=now_iso,
            sample_count=len(pairs),
        )

    # SPEC-AI-107 REQ-AI107-007: 최소 positive 표본 수 가드 (옵션, 하위 호환)
    if min_positive_samples is not None and n_pos < min_positive_samples:
        logger.info(
            "캘리브레이터 학습 스킵 — positive 표본 부족 (%d < %d)",
            n_pos,
            min_positive_samples,
        )
        return IsotonicModel(
            is_identity=True,
            trained_at=now_iso,
            sample_count=len(pairs),
        )

    # raw_confidence 기준 정렬
    sorted_pairs = sorted(pairs, key=lambda p: p[0])

    # float 변환
    float_pairs = [(float(raw), float(is_c)) for raw, is_c in sorted_pairs]

    # PAV 실행
    bp = _run_pav(float_pairs)

    logger.info(
        "캘리브레이터 학습 완료 — 샘플=%d breakpoints=%d pos_ratio=%.2f",
        len(pairs),
        len(bp),
        pos_ratio,
    )

    return IsotonicModel(
        breakpoints=bp,
        trained_at=now_iso,
        sample_count=len(pairs),
        is_identity=False,
    )


# ---------------------------------------------------------------------------
# 영속성: 저장 / 로드
# ---------------------------------------------------------------------------

def save_calibrator(model: IsotonicModel, path: Path = _CALIBRATOR_PATH) -> None:
    """IsotonicModel을 pickle로 저장한다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(model, f)
        logger.info("캘리브레이터 저장 완료: %s", path)
    except Exception:
        logger.warning("캘리브레이터 저장 실패", exc_info=True)


def load_calibrator(path: Path = _CALIBRATOR_PATH) -> IsotonicModel:
    """pickle에서 IsotonicModel을 로드한다.

    파일 없음 / 손상 시 identity fallback (예외 전파 없음).
    """
    try:
        with open(path, "rb") as f:
            model = pickle.load(f)
        if not isinstance(model, IsotonicModel):
            raise TypeError(f"예상과 다른 타입: {type(model)}")
        logger.info(
            "캘리브레이터 로드 완료 (학습=%s, 샘플=%d)",
            model.trained_at,
            model.sample_count,
        )
        return model
    except FileNotFoundError:
        logger.info("캘리브레이터 파일 없음 — identity fallback 사용")
    except Exception:
        logger.warning("캘리브레이터 로드 실패 — identity fallback 사용", exc_info=True)

    return IsotonicModel(is_identity=True)


# ---------------------------------------------------------------------------
# 앱 수준 싱글턴 (startup 시 로드)
# ---------------------------------------------------------------------------

_calibrator: IsotonicModel | None = None


def get_calibrator() -> IsotonicModel:
    """현재 캘리브레이터를 반환한다. 초기화 안 된 경우 파일에서 로드."""
    global _calibrator  # noqa: PLW0603
    if _calibrator is None:
        _calibrator = load_calibrator()
    return _calibrator


def get_calibrator_status() -> dict:
    """캘리브레이터의 현재 유효성 상태를 반환한다 (SPEC-AI-069 REQ-AI069-005).

    # @MX:NOTE: [AUTO] SPEC-AI-069 REQ-005 — pkl 부재로 인한 identity fallback(무효 보정) 상태를
    # 조용히 방치하지 않고 일일 리포트/로그에 표면화하기 위한 조회 함수.
    # 표면화만 구현(surfacing-only): 학습 스케줄 잡을 추가하지 않고, calibrate_confidence 연결도
    # 끊지 않는다 — 무효 상태 자체만 가시화한다(REQ-005 최소 요건 충족).
    # (fund_manager.py:1382-1387 calibrate_confidence 호출부 주석 참조).
    # @MX:SPEC: SPEC-AI-069 REQ-AI069-005

    Returns:
        {"is_identity": bool, "trained_at": str, "sample_count": int}
    """
    model = get_calibrator()
    return {
        "is_identity": model.is_identity,
        "trained_at": model.trained_at,
        "sample_count": model.sample_count,
    }


def calibrate_confidence(raw: float) -> float:
    """raw confidence를 캘리브레이션 모델로 보정한다.

    모델 미로드 시 raw 그대로 반환 (예외 전파 없음).

    # @MX:NOTE: SPEC-AI-036 surge 경로의 핵심 캘리브레이션 함수. fund_manager.py 신호 생성 시
    # 직접 호출되어 confidence를 isotonic 보정된 값으로 변환한다.
    """
    try:
        return get_calibrator().predict(raw)
    except Exception:
        logger.warning("calibrate_confidence 실패 — raw 반환", exc_info=True)
        return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# 재학습 진입점 (스케줄러 / 수동 호출)
# ---------------------------------------------------------------------------

def retrain_calibrator(db: object) -> IsotonicModel:
    """DB에서 학습 데이터를 수집하고 캘리브레이터를 재학습한다.

    SPEC-AI-036 REQ-036-005 주간 재학습 훅.

    # @MX:NOTE: 스케줄러에서 주 1회 호출되는 캘리브레이터 재학습 진입점.
    # 모든 예외를 catch하고 기존 모델 반환 → 시그널 생성 파이프라인 중단 방지.

    Args:
        db: SQLAlchemy Session (또는 SessionLocal 인스턴스).

    Returns:
        새로 학습된 IsotonicModel.
    """
    global _calibrator  # noqa: PLW0603

    try:
        from app.services.signal_verifier import get_surge_calibration_pairs

        pairs = get_surge_calibration_pairs(db)
        model = train_isotonic(pairs)
        save_calibrator(model)
        _calibrator = model
        logger.info("캘리브레이터 재학습 완료 — 샘플=%d", len(pairs))
        return model
    except Exception:
        logger.warning("캘리브레이터 재학습 실패", exc_info=True)
        return get_calibrator()


# ---------------------------------------------------------------------------
# SPEC-AI-107: 섀도우 학습 (walk-forward 분할 + Brier 게이트 + 실행 로그)
#
# active data/surge_calibrator.pkl은 이 섹션의 어떤 함수도 건드리지 않는다
# (REQ-AI107-002). 프로모션(promote_candidate)은 섀도우 학습 잡에서 절대
# 호출되지 않으며, 사람 또는 후속 SPEC이 plan.md §C 절차를 따라 수동으로만
# 호출한다.
# ---------------------------------------------------------------------------


def split_walk_forward(
    triples: list[tuple[float, int, datetime]],
    holdout_fraction: float = 0.3,
) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    """created_at 기준 시간순 walk-forward 분할 (무작위 분할 아님).

    시계열 금융 데이터의 lookahead bias를 방지하기 위해 가장 최근
    holdout_fraction 비율을 검증(holdout) 구간으로 분리하고, 나머지를 학습
    구간으로 반환한다.

    Args:
        triples: (raw_confidence, is_correct, created_at) 리스트.
        holdout_fraction: holdout 비율 (0.0~1.0).

    Returns:
        (training_set, holdout_set) — 각각 (raw_confidence, is_correct) 쌍 리스트.
    """
    sorted_triples = sorted(triples, key=lambda t: t[2])
    n = len(sorted_triples)
    holdout_count = int(n * holdout_fraction)

    if holdout_count == 0:
        train_triples = sorted_triples
        holdout_triples: list[tuple[float, int, datetime]] = []
    else:
        train_triples = sorted_triples[:-holdout_count]
        holdout_triples = sorted_triples[-holdout_count:]

    training_set = [(raw, is_c) for raw, is_c, _ in train_triples]
    holdout_set = [(raw, is_c) for raw, is_c, _ in holdout_triples]
    return training_set, holdout_set


def compute_brier_score(pairs: list[tuple[float, int]]) -> float:
    """Brier 점수 계산 — mean((예측확률 - 실제결과)^2). 낮을수록 좋음.

    numpy/scikit-learn 의존성 없이 순수 Python으로 계산한다.

    Args:
        pairs: (predicted_prob, actual) 쌍 리스트. actual ∈ {0, 1}.

    Returns:
        Brier 점수.
    """
    return sum((p - a) ** 2 for p, a in pairs) / len(pairs)


@dataclass
class ShadowTrainingRun:
    """섀도우 학습 1회 실행 결과 레코드.

    runs.jsonl 실행 로그의 한 행에 대응한다(REQ-AI107-003).
    """

    run_date: str
    sample_count: int
    positive_count: int
    sufficient_data: bool
    brier_raw: float | None
    brier_calibrated: float | None
    gate_passed: bool
    candidate_path: str | None


def _append_run_log(run: ShadowTrainingRun, path: Path = _RUN_LOG_PATH) -> None:
    """ShadowTrainingRun을 JSONL 실행 로그에 1줄 append한다 (기존 행은 보존)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(run), ensure_ascii=False) + "\n")


def run_shadow_training(
    db: object,
    min_calibration_samples: int | None = None,
    min_positive_samples: int = 15,
    holdout_fraction: float = 0.3,
) -> ShadowTrainingRun:
    """SPEC-AI-107: 캘리브레이터 섀도우 학습 오케스트레이션.

    walk-forward 분할로 학습/검증 세트를 나누고, 검증(holdout) 세트에서 Brier
    점수로 "보정이 원시값보다 실제로 개선되는가"를 측정한다. active
    data/surge_calibrator.pkl은 절대 덮어쓰지 않으며(REQ-AI107-002), 학습
    결과는 날짜별 candidate 아티팩트로 별도 저장한다.

    # @MX:NOTE: [AUTO] SPEC-AI-107 — 이 함수는 자체 예외 처리를 하지 않는다.
    # 예외 격리는 호출부(scheduler._run_surge_calibrator_shadow_training)의
    # 책임이다(REQ-AI107-008).
    # @MX:SPEC: SPEC-AI-107 REQ-AI107-001

    Args:
        db: SQLAlchemy Session.
        min_calibration_samples: 표본 수 floor. None이면
            SurgeEnsembleConfig.min_calibration_samples를 읽어 사용한다
            (REQ-AI107-009).
        min_positive_samples: 최소 positive 표본 수 floor.
        holdout_fraction: walk-forward holdout 비율.

    Returns:
        ShadowTrainingRun.
    """
    from app.services.signal_verifier import get_surge_calibration_pairs_with_time

    run_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    if min_calibration_samples is None:
        from app.surge_config.surge_settings import get_surge_config

        floor = get_surge_config().min_calibration_samples
    else:
        floor = min_calibration_samples

    triples = get_surge_calibration_pairs_with_time(db)
    sample_count = len(triples)
    positive_count = sum(1 for _, is_c, _ in triples if is_c == 1)

    sufficient = sample_count >= floor and positive_count >= min_positive_samples

    training_set: list[tuple[float, int]] = []
    holdout_set: list[tuple[float, int]] = []
    if sufficient:
        training_set, holdout_set = split_walk_forward(triples, holdout_fraction=holdout_fraction)
        if not holdout_set:
            # Edge case (acceptance.md): holdout이 0개가 되는 극단적 경계는
            # 데이터 부족 경로로 흡수한다 — compute_brier_score([])의
            # ZeroDivisionError를 방지.
            sufficient = False

    if not sufficient:
        run = ShadowTrainingRun(
            run_date=run_date,
            sample_count=sample_count,
            positive_count=positive_count,
            sufficient_data=False,
            brier_raw=None,
            brier_calibrated=None,
            gate_passed=False,
            candidate_path=None,
        )
        _append_run_log(run, path=_RUN_LOG_PATH)
        return run

    # SPEC-AI-107 plan.md TASK-002 step 6: floor와 min_positive_samples 모두를
    # 명시적 키워드 인자로 전달한다 — floor 생략 시 train_isotonic()이 자신의
    # 독립적인 기본값(_DEFAULT_MIN_CALIBRATION_SAMPLES=50)을 사용하게 되어
    # REQ-AI107-009가 의도한 설정 기반 floor가 조용히 무시된다(AC-107-011).
    model = train_isotonic(
        training_set,
        min_calibration_samples=floor,
        min_positive_samples=min_positive_samples,
    )

    candidate_path = _CANDIDATE_DIR / f"candidate_{run_date}.pkl"
    save_calibrator(model, path=candidate_path)

    brier_raw = compute_brier_score(holdout_set)
    brier_calibrated = compute_brier_score(
        [(model.predict(raw), is_c) for raw, is_c in holdout_set]
    )
    gate_passed = brier_calibrated < brier_raw

    run = ShadowTrainingRun(
        run_date=run_date,
        sample_count=sample_count,
        positive_count=positive_count,
        sufficient_data=True,
        brier_raw=brier_raw,
        brier_calibrated=brier_calibrated,
        gate_passed=gate_passed,
        candidate_path=str(candidate_path),
    )
    _append_run_log(run, path=_RUN_LOG_PATH)
    return run


def promote_candidate(candidate_path: Path, active_path: Path = _CALIBRATOR_PATH) -> None:
    """candidate 파일을 active 경로로 복사한다 (수동 프로모션 전용).

    이 함수는 섀도우 학습 잡(run_shadow_training)에서 절대 호출되지 않는다.
    plan.md §C 절차를 따르는 사람(또는 후속 SPEC)이 수동으로만 호출한다.

    Args:
        candidate_path: candidate .pkl 파일 경로.
        active_path: 교체할 active 경로 (기본: data/surge_calibrator.pkl).
    """
    import shutil

    active_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_path, active_path)
    logger.info("캘리브레이터 프로모션 완료: %s → %s", candidate_path, active_path)
