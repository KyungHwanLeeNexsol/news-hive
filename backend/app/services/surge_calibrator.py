"""SPEC-AI-036: isotonic 신뢰도 캘리브레이터.

Pool Adjacent Violators (PAV) 알고리즘으로 단조 증가 보정 함수를 학습한다.
numpy / scikit-learn 의존성 없이 순수 Python만 사용한다.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# pickle 파일 저장 경로
_CALIBRATOR_PATH = Path(__file__).parent.parent.parent / "data" / "surge_calibrator.pkl"

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
) -> IsotonicModel:
    """PAV 알고리즘으로 IsotonicModel을 학습한다.

    Args:
        pairs: (raw_confidence, is_correct) 리스트.
               is_correct ∈ {0, 1} (검증 완료 시그널만 포함해야 함).
        min_calibration_samples: 최소 샘플 수. 미달 시 identity 반환.

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


def calibrate_confidence(raw: float) -> float:
    """raw confidence를 캘리브레이션 모델로 보정한다.

    모델 미로드 시 raw 그대로 반환 (예외 전파 없음).
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
