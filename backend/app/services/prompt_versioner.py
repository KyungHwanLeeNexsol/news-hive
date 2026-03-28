"""프롬프트 A/B 테스트 서비스.

프롬프트 버전을 관리하고, 동일 종목에 대해 두 버전으로
병렬 시그널을 생성하여 통계적으로 비교한다.
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.prompt_version import PromptABResult, PromptVersion

logger = logging.getLogger(__name__)

# 기본 프롬프트 버전 이름
DEFAULT_VERSION = "v1.0-baseline"


def get_current_version(db: Session, template_key: str = "signal") -> str:
    """현재 활성 프롬프트 버전을 반환한다.

    Args:
        db: SQLAlchemy 세션
        template_key: 프롬프트 유형 (briefing / signal)

    Returns:
        활성 버전 이름 (없으면 기본 버전)
    """
    version = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.template_key == template_key,
            PromptVersion.is_active == True,  # noqa: E712
            PromptVersion.is_control == True,  # noqa: E712
        )
        .first()
    )
    return version.version_name if version else DEFAULT_VERSION


def get_ab_versions(
    db: Session, template_key: str = "signal"
) -> tuple[str, str | None]:
    """A/B 테스트 대조군과 실험군 버전을 반환한다.

    Returns:
        (control_version, treatment_version) -- 실험군이 없으면 (control, None)
    """
    versions = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.template_key == template_key,
            PromptVersion.is_active == True,  # noqa: E712
        )
        .order_by(PromptVersion.is_control.desc())
        .limit(2)
        .all()
    )

    if not versions:
        return (DEFAULT_VERSION, None)

    control = versions[0].version_name
    treatment = versions[1].version_name if len(versions) > 1 else None
    return (control, treatment)


def evaluate_ab_test(db: Session, days: int = 30) -> dict | None:
    """A/B 테스트 결과를 통계적으로 평가한다.

    최근 ``days`` 일간 검증 완료된 시그널을 대조군/실험군으로 분리하여
    적중률 차이의 통계적 유의성을 z-test 로 판정한다.

    Returns:
        평가 결과 dict 또는 데이터 부족 시 None.
        dict 키: version_a, version_b, accuracy_a, accuracy_b,
                 trials_a, trials_b, p_value, winner
    """
    control, treatment = get_ab_versions(db)
    if not treatment:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 대조군/실험군 검증 완료 시그널 조회
    signals_a = (
        db.query(FundSignal)
        .filter(
            FundSignal.prompt_version == control,
            FundSignal.verified_at.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    signals_b = (
        db.query(FundSignal)
        .filter(
            FundSignal.prompt_version == treatment,
            FundSignal.verified_at.isnot(None),
            FundSignal.created_at >= cutoff,
        )
        .all()
    )

    # 최소 표본 크기 충족 여부
    min_samples = 10
    if len(signals_a) < min_samples or len(signals_b) < min_samples:
        logger.info(
            "A/B 테스트 데이터 부족: A=%d, B=%d (최소 %d건 필요)",
            len(signals_a),
            len(signals_b),
            min_samples,
        )
        return None

    correct_a = sum(1 for s in signals_a if s.is_correct)
    correct_b = sum(1 for s in signals_b if s.is_correct)

    acc_a = correct_a / len(signals_a) * 100
    acc_b = correct_b / len(signals_b) * 100

    # z-test for proportions (scipy 의존성 없이 구현)
    p1 = correct_a / len(signals_a)
    p2 = correct_b / len(signals_b)
    p_pool = (correct_a + correct_b) / (len(signals_a) + len(signals_b))

    if p_pool == 0 or p_pool == 1:
        p_value = 1.0
    else:
        se = math.sqrt(
            p_pool * (1 - p_pool) * (1 / len(signals_a) + 1 / len(signals_b))
        )
        z = abs(p1 - p2) / se if se > 0 else 0
        # 근사적 양측 p-value (표준정규분포)
        p_value = max(0.001, 2 * (1 - _normal_cdf(z)))

    winner = None
    if p_value < 0.05:
        winner = control if acc_a > acc_b else treatment

    result = {
        "version_a": control,
        "version_b": treatment,
        "accuracy_a": round(acc_a, 1),
        "accuracy_b": round(acc_b, 1),
        "trials_a": len(signals_a),
        "trials_b": len(signals_b),
        "p_value": round(p_value, 4),
        "winner": winner,
    }

    # 결과 DB 저장
    ab_result = PromptABResult(
        version_a=control,
        version_b=treatment,
        total_trials=len(signals_a) + len(signals_b),
        accuracy_a=acc_a,
        accuracy_b=acc_b,
        p_value=p_value,
        winner=winner,
    )
    db.add(ab_result)
    db.commit()

    # 통계적 유의성이 있고 실험군이 승리하면 자동 승격
    if winner and winner == treatment:
        _promote_version(db, treatment, control)

    return result


def _promote_version(db: Session, winner: str, loser: str) -> None:
    """승자 버전을 대조군으로 승격하고 패자를 비활성화한다."""
    winner_ver = (
        db.query(PromptVersion)
        .filter(PromptVersion.version_name == winner)
        .first()
    )
    loser_ver = (
        db.query(PromptVersion)
        .filter(PromptVersion.version_name == loser)
        .first()
    )

    if winner_ver:
        winner_ver.is_control = True
    if loser_ver:
        loser_ver.is_active = False
        loser_ver.is_control = False

    db.commit()
    logger.info("A/B 테스트 승격: %s -> 대조군, %s -> 비활성", winner, loser)


def _normal_cdf(x: float) -> float:
    """표준정규분포 CDF 근사 (Abramowitz & Stegun)."""
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422804014327
    p = d * math.exp(-x * x / 2.0) * (
        t
        * (
            0.3193815
            + t
            * (
                -0.3565638
                + t * (1.781478 + t * (-1.821256 + t * 1.330274))
            )
        )
    )
    return 1.0 - p if x > 0 else p
