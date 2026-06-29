"""SPEC-AI-065 REQ-4: 오프라인 앙상블 가중치 재보정 스크립트.

순수 Python 로지스틱 회귀(경사하강법)로 과거 탐지기 점수 → 실제 급등 여부
데이터를 학습하여 surge_detection.auto.yaml 권장 가중치를 출력한다.

사용법:
    cd backend
    uv run python scripts/recalibrate_ensemble_weights.py [--output surge_detection.auto.yaml]

출력:
    surge_detection.auto.yaml의 ensemble.weights 섹션 권장값 (YAML 형식)

주의:
    - 이 스크립트는 ONE-TIME 오프라인 초기 시드용이다.
    - 온라인 자동 개선은 SPEC-AI-041 surge_auto_improver.py가 담당한다.
    - numpy/scipy/sklearn 미사용 — 순수 Python 경사하강법 구현.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# backend/ 디렉터리를 sys.path에 추가 (로컬 실행 지원)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 탐지기 이름 (7개 — legacy_detectors는 0이므로 제외, momentum_continuation 포함)
_DETECTOR_NAMES = [
    "theme_cluster",
    "volume_news_combo",
    "disclosure_pattern",
    "news_delayed",
    "weekend_gap_up",
    "volume_breakout",
    "momentum_continuation",
]

# 현재 YAML 가중치 (초기값, 이 스크립트가 갱신할 대상)
_CURRENT_WEIGHTS: dict[str, float] = {
    "theme_cluster": 0.19,
    "volume_news_combo": 0.25,
    "disclosure_pattern": 0.14,
    "legacy_detectors": 0.00,
    "news_delayed": 0.11,
    "weekend_gap_up": 0.08,
    "volume_breakout": 0.11,
    "momentum_continuation": 0.12,
}


# ---------------------------------------------------------------------------
# 순수 Python 수치 유틸
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """수치 안정적인 sigmoid 함수."""
    if x >= 0:
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    else:
        e = math.exp(x)
        return e / (1.0 + e)


def _dot(a: list[float], b: list[float]) -> float:
    """벡터 내적."""
    return sum(x * y for x, y in zip(a, b))


def _softmax_normalize(weights: list[float]) -> list[float]:
    """가중치를 합산=1.0으로 정규화한다 (음수 클램핑 후)."""
    clamped = [max(0.0, w) for w in weights]
    total = sum(clamped)
    if total <= 0:
        n = len(clamped)
        return [1.0 / n] * n
    return [w / total for w in clamped]


# ---------------------------------------------------------------------------
# 데이터 로딩
# ---------------------------------------------------------------------------

def load_training_data(db_url: str, lookback_days: int = 90) -> list[tuple[list[float], int]]:
    """DB에서 (탐지기 점수 벡터, was_surge) 학습 데이터를 로딩한다.

    FundSignal.surge_metadata JSON에서 각 탐지기 점수를 추출하고,
    SurgeActualOutcome.was_surge로 레이블을 결정한다.

    Args:
        db_url: SQLAlchemy DB URL
        lookback_days: 학습 데이터 기간 (과거 N일)

    Returns:
        [(score_vector, label)] 목록
        score_vector 순서: _DETECTOR_NAMES와 동일
    """
    import json

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    samples: list[tuple[list[float], int]] = []
    cutoff = date.today() - timedelta(days=lookback_days)

    try:
        # T-1 surge_candidate 시그널과 T 당일 실제 급등 여부 조인
        from app.models.fund_signal import FundSignal
        from app.models.stock import Stock
        from app.models.surge_actual_outcome import SurgeActualOutcome
        from sqlalchemy import func as sqlfunc

        rows = (
            db.query(
                FundSignal.surge_metadata,
                SurgeActualOutcome.was_surge,
            )
            .join(Stock, FundSignal.stock_id == Stock.id)
            .join(
                SurgeActualOutcome,
                SurgeActualOutcome.stock_code == Stock.stock_code,
            )
            .filter(
                FundSignal.signal_type == "surge_candidate",
                FundSignal.surge_metadata.isnot(None),
                sqlfunc.date(FundSignal.created_at) >= cutoff,
            )
            .all()
        )

        for row in rows:
            try:
                meta = json.loads(row.surge_metadata)
                label = 1 if row.was_surge else 0

                # surge_metadata에서 탐지기 점수 추출
                scores_map: dict[str, float] = {
                    "theme_cluster": float(meta.get("theme_cluster_score", 0.0)),
                    "volume_news_combo": float(meta.get("combo_score", 0.0)),
                    "disclosure_pattern": float(
                        max(
                            meta.get("pattern_score", 0.0),
                            meta.get("immediate_disclosure_score", 0.0),
                        )
                    ),
                    "news_delayed": float(meta.get("news_delayed_score", 0.0)),
                    "weekend_gap_up": float(meta.get("weekend_gap_up_score", 0.0)),
                    "volume_breakout": float(meta.get("volume_breakout_score", 0.0)),
                    "momentum_continuation": float(
                        meta.get("momentum_continuation_score", 0.0)
                    ),
                }
                vector = [scores_map.get(d, 0.0) for d in _DETECTOR_NAMES]
                samples.append((vector, label))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        logger.info(
            "학습 데이터 로딩: %d개 샘플 (positive=%d, negative=%d)",
            len(samples),
            sum(1 for _, y in samples if y == 1),
            sum(1 for _, y in samples if y == 0),
        )
    finally:
        db.close()

    return samples


# ---------------------------------------------------------------------------
# 로지스틱 회귀 (순수 Python 경사하강법)
# ---------------------------------------------------------------------------

def logistic_regression(
    samples: list[tuple[list[float], int]],
    learning_rate: float = 0.01,
    epochs: int = 500,
    l2_lambda: float = 0.01,
) -> list[float]:
    """로지스틱 회귀 경사하강법으로 최적 가중치를 학습한다.

    intercept(bias) 없음 — 가중치만 학습 (합산=1.0 제약은 사후 정규화로 처리).

    Args:
        samples: [(score_vector, label)] 학습 데이터
        learning_rate: 학습률
        epochs: 학습 에포크 수
        l2_lambda: L2 정규화 강도

    Returns:
        _DETECTOR_NAMES 순서의 최적 가중치 리스트 (정규화 전)
    """
    n_features = len(_DETECTOR_NAMES)
    weights = [1.0 / n_features] * n_features  # 균등 초기화

    for epoch in range(epochs):
        grad = [0.0] * n_features
        total_loss = 0.0

        for x, y in samples:
            pred = _sigmoid(_dot(weights, x))
            error = pred - y
            for i in range(n_features):
                grad[i] += error * x[i]
            # Binary cross-entropy loss
            total_loss += -(y * math.log(max(pred, 1e-10)) + (1 - y) * math.log(max(1 - pred, 1e-10)))

        n = len(samples)
        for i in range(n_features):
            # 경사 + L2 정규화
            weights[i] -= learning_rate * (grad[i] / n + l2_lambda * weights[i])

        if (epoch + 1) % 100 == 0:
            avg_loss = total_loss / max(n, 1)
            logger.info("epoch=%d loss=%.4f weights=%s", epoch + 1, avg_loss,
                        [f"{w:.3f}" for w in weights])

    return weights


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="앙상블 가중치 재보정 스크립트")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL DB URL (기본: DATABASE_URL 환경변수)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="학습 데이터 기간 (과거 N일, 기본: 90)",
    )
    parser.add_argument(
        "--output",
        default=str(_BACKEND_DIR / "app" / "surge_config" / "surge_detection.auto.yaml"),
        help="출력 파일 경로 (기본: surge_detection.auto.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일 저장 없이 권장 가중치만 출력",
    )
    args = parser.parse_args()

    if not args.db_url:
        logger.error("DATABASE_URL이 설정되지 않았습니다. --db-url 또는 환경변수로 지정하세요.")
        sys.exit(1)

    logger.info("학습 데이터 로딩 중... (lookback=%d일)", args.lookback_days)
    samples = load_training_data(args.db_url, lookback_days=args.lookback_days)

    if len(samples) < 30:
        logger.warning(
            "샘플 수 부족 (%d개). 최소 30개 필요. 현재 가중치 유지를 권장합니다.", len(samples)
        )
        logger.info("현재 가중치: %s", _CURRENT_WEIGHTS)
        sys.exit(0)

    logger.info("로지스틱 회귀 학습 중...")
    raw_weights = logistic_regression(
        samples,
        learning_rate=0.005,
        epochs=1000,
        l2_lambda=0.005,
    )

    # 정규화: 합산=1.0, legacy_detectors=0.0 고정
    normalized = _softmax_normalize(raw_weights)

    # legacy_detectors=0 고정 (항상), 정규화 재적용
    result: dict[str, float] = {}
    for i, det_name in enumerate(_DETECTOR_NAMES):
        result[det_name] = round(normalized[i], 4)

    # 합계 보정: 부동소수점 오차를 가장 큰 가중치에 흡수
    total = sum(result.values())
    if abs(total - 1.0) > 0.0001:
        largest_key = max(result, key=lambda k: result[k])
        result[largest_key] = round(result[largest_key] + (1.0 - total), 4)

    # legacy_detectors는 항상 0
    result["legacy_detectors"] = 0.00

    final_weights = {**result, "legacy_detectors": 0.00}
    final_sum = sum(final_weights.values())

    logger.info("===== 권장 가중치 =====")
    for det, w in sorted(final_weights.items(), key=lambda x: -x[1]):
        current = _CURRENT_WEIGHTS.get(det, 0.0)
        delta = w - current
        sign = "+" if delta >= 0 else ""
        logger.info("  %-30s %.4f  (현재=%.4f, %s%.4f)", det, w, current, sign, delta)
    logger.info("  합계: %.4f", final_sum)

    yaml_content = f"""# SPEC-AI-065 REQ-4: 로지스틱 회귀 재보정 가중치
# 생성 일자: {date.today().isoformat()}
# 학습 샘플 수: {len(samples)}개 (lookback={args.lookback_days}일)
surge_detection:
  ensemble:
    weights:
      theme_cluster: {final_weights.get('theme_cluster', 0.19):.4f}
      volume_news_combo: {final_weights.get('volume_news_combo', 0.25):.4f}
      disclosure_pattern: {final_weights.get('disclosure_pattern', 0.14):.4f}
      legacy_detectors: 0.0000
      news_delayed: {final_weights.get('news_delayed', 0.11):.4f}
      weekend_gap_up: {final_weights.get('weekend_gap_up', 0.08):.4f}
      volume_breakout: {final_weights.get('volume_breakout', 0.11):.4f}
      momentum_continuation: {final_weights.get('momentum_continuation', 0.12):.4f}
"""

    if args.dry_run:
        logger.info("--dry-run 모드: 파일 저장 생략")
        print(yaml_content)
    else:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_content, encoding="utf-8")
        logger.info("권장 가중치를 %s에 저장했습니다.", output_path)
        logger.info("적용 후 config 재로드: from app.surge_config.surge_settings import reload_surge_config; reload_surge_config()")


if __name__ == "__main__":
    main()
