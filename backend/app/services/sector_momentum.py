"""섹터 모멘텀 추적 및 로테이션 감지 서비스.

SPEC-AI-002 Phase 2:
- REQ-AI-016: 섹터별 자금 흐름 추적
- REQ-AI-017: 섹터 로테이션 패턴 인식
- REQ-AI-019: 동일 섹터 시그널 중복 제거
"""

import logging
from datetime import date, timedelta

from sqlalchemy import and_, func as sa_func
from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.sector_momentum import SectorMomentum
from app.models.sector_rotation_event import SectorRotationEvent

logger = logging.getLogger(__name__)

# --- REQ-AI-016 상수 ---
MOMENTUM_DAYS = 5          # 평균 등락률 계산 기간
MOMENTUM_THRESHOLD = 2.0   # 시장 대비 +2%p 이상이면 모멘텀 섹터
CAPITAL_INFLOW_DAYS = 3    # 연속 거래대금 증가 + 양의 수익률 체크 기간

# --- REQ-AI-017 상수 ---
ROTATION_CONFIDENCE_ADJUSTMENT = -0.15  # 로테이션 시 이전 섹터 confidence 조정

# --- REQ-AI-019 상수 ---
MAX_SIGNALS_PER_SECTOR = 2  # 같은 섹터 내 최대 시그널 수


# @MX:ANCHOR: [AUTO] 섹터 모멘텀 일간 기록 — 스케줄러에서 매일 호출
# @MX:REASON: 스케줄러 + 브리핑 등 3개 이상 호출처
async def record_daily_sector_performance(db: Session) -> int:
    """모든 섹터의 당일 등락률을 DB에 저장한다.

    네이버 금융 API에서 섹터별 등락률을 가져와서
    sector_momentum 테이블에 일간 레코드를 생성한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        저장된 레코드 수
    """
    today = date.today()

    # 이미 오늘 데이터가 있으면 스킵
    existing = db.query(SectorMomentum).filter(
        SectorMomentum.date == today
    ).first()
    if existing:
        logger.info("오늘(%s) 섹터 모멘텀 데이터 이미 존재 — 스킵", today)
        return 0

    try:
        from app.services.naver_finance import fetch_sector_performances
        performances = await fetch_sector_performances(force=True)
    except Exception as e:
        logger.error("섹터 퍼포먼스 수집 실패: %s", e)
        return 0

    if not performances:
        logger.warning("섹터 퍼포먼스 데이터 없음")
        return 0

    # DB에 등록된 섹터들의 naver_code 매핑
    sectors = db.query(Sector).filter(Sector.naver_code.isnot(None)).all()
    sector_map = {s.naver_code: s for s in sectors}

    count = 0
    for naver_code, perf in performances.items():
        sector = sector_map.get(naver_code)
        if not sector:
            continue

        momentum = SectorMomentum(
            sector_id=sector.id,
            date=today,
            daily_return=perf.change_rate,
        )
        db.add(momentum)
        count += 1

    if count:
        db.commit()
        logger.info("섹터 모멘텀 일간 데이터 %d건 저장", count)

    return count


def calculate_sector_momentum(db: Session, days: int = MOMENTUM_DAYS) -> list[dict]:
    """섹터별 N일 평균 등락률을 계산한다.

    Args:
        db: SQLAlchemy 세션
        days: 평균 계산 기간 (기본 5일)

    Returns:
        [{"sector_id": int, "sector_name": str, "avg_return": float, "records": int}, ...]
    """
    cutoff = date.today() - timedelta(days=days)

    results = (
        db.query(
            SectorMomentum.sector_id,
            Sector.name,
            sa_func.avg(SectorMomentum.daily_return).label("avg_return"),
            sa_func.count(SectorMomentum.id).label("record_count"),
        )
        .join(Sector, Sector.id == SectorMomentum.sector_id)
        .filter(SectorMomentum.date > cutoff)
        .group_by(SectorMomentum.sector_id, Sector.name)
        .all()
    )

    return [
        {
            "sector_id": r.sector_id,
            "sector_name": r.name,
            "avg_return": round(float(r.avg_return), 4),
            "records": r.record_count,
        }
        for r in results
    ]


def detect_momentum_sectors(db: Session) -> list[dict]:
    """시장 대비 +2%p 이상 모멘텀 섹터를 식별한다.

    REQ-AI-016: 5일 평균 등락률이 전체 시장 대비 +2%p 이상 → "momentum_sector" 태그.

    Args:
        db: SQLAlchemy 세션

    Returns:
        모멘텀 섹터 리스트 [{"sector_id": int, "sector_name": str, "avg_return": float, "excess_return": float}]
    """
    momentum_data = calculate_sector_momentum(db)
    if not momentum_data:
        return []

    # 전체 시장 평균 계산 (모든 섹터의 5일 평균의 평균)
    market_avg = sum(m["avg_return"] for m in momentum_data) / len(momentum_data)

    momentum_sectors = []
    for m in momentum_data:
        excess = m["avg_return"] - market_avg
        if excess >= MOMENTUM_THRESHOLD:
            momentum_sectors.append({
                "sector_id": m["sector_id"],
                "sector_name": m["sector_name"],
                "avg_return": m["avg_return"],
                "excess_return": round(excess, 4),
            })

            # DB에 모멘텀 태그 업데이트 (오늘 데이터)
            today_record = db.query(SectorMomentum).filter(
                and_(
                    SectorMomentum.sector_id == m["sector_id"],
                    SectorMomentum.date == date.today(),
                )
            ).first()
            if today_record:
                today_record.momentum_tag = "momentum_sector"
                today_record.avg_return_5d = m["avg_return"]

    if momentum_sectors:
        db.commit()
        logger.info(
            "모멘텀 섹터 %d개 감지: %s",
            len(momentum_sectors),
            [s["sector_name"] for s in momentum_sectors],
        )

    return momentum_sectors


def detect_capital_inflow(db: Session) -> list[dict]:
    """3일 연속 양의 수익률 섹터를 감지한다 (자금 유입 추정).

    REQ-AI-016: 3일 연속 거래대금 증가 + 양의 수익률 → "capital_inflow".
    (네이버 데이터에 거래대금이 없으므로, 양의 수익률 연속을 대리 지표로 사용)

    Args:
        db: SQLAlchemy 세션

    Returns:
        자금 유입 감지 섹터 리스트
    """
    today = date.today()
    cutoff = today - timedelta(days=CAPITAL_INFLOW_DAYS)

    # 섹터별 최근 3일 데이터 조회
    sectors = db.query(Sector).all()
    inflow_sectors = []

    for sector in sectors:
        recent = (
            db.query(SectorMomentum)
            .filter(
                and_(
                    SectorMomentum.sector_id == sector.id,
                    SectorMomentum.date > cutoff,
                )
            )
            .order_by(SectorMomentum.date.desc())
            .limit(CAPITAL_INFLOW_DAYS)
            .all()
        )

        if len(recent) < CAPITAL_INFLOW_DAYS:
            continue

        # 3일 연속 양의 수익률 확인
        all_positive = all(r.daily_return > 0 for r in recent)
        if all_positive:
            # DB에 capital_inflow 플래그 설정 (최신 레코드)
            recent[0].capital_inflow = True
            inflow_sectors.append({
                "sector_id": sector.id,
                "sector_name": sector.name,
                "consecutive_positive_days": CAPITAL_INFLOW_DAYS,
                "avg_daily_return": round(
                    sum(r.daily_return for r in recent) / len(recent), 4
                ),
            })

    if inflow_sectors:
        db.commit()
        logger.info(
            "자금 유입 감지 섹터 %d개: %s",
            len(inflow_sectors),
            [s["sector_name"] for s in inflow_sectors],
        )

    return inflow_sectors


def detect_sector_rotation(db: Session) -> list[SectorRotationEvent]:
    """섹터 로테이션 이벤트를 감지한다.

    REQ-AI-017: 이전 모멘텀 섹터 → 새 모멘텀 섹터 전환 감지.
    어제와 오늘의 모멘텀 섹터를 비교하여 변화가 있으면 로테이션 이벤트를 기록한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        새로 생성된 SectorRotationEvent 리스트
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 어제의 모멘텀 섹터
    prev_momentum = (
        db.query(SectorMomentum.sector_id)
        .filter(
            and_(
                SectorMomentum.date == yesterday,
                SectorMomentum.momentum_tag == "momentum_sector",
            )
        )
        .all()
    )
    prev_ids = {r.sector_id for r in prev_momentum}

    # 오늘의 모멘텀 섹터
    curr_momentum = (
        db.query(SectorMomentum.sector_id)
        .filter(
            and_(
                SectorMomentum.date == today,
                SectorMomentum.momentum_tag == "momentum_sector",
            )
        )
        .all()
    )
    curr_ids = {r.sector_id for r in curr_momentum}

    if not prev_ids or not curr_ids:
        return []

    # 이전에는 있었지만 지금은 없는 섹터 → 새 섹터로 로테이션
    lost_sectors = prev_ids - curr_ids
    new_sectors = curr_ids - prev_ids

    events = []
    for from_id in lost_sectors:
        for to_id in new_sectors:
            # 이미 동일 로테이션 이벤트가 오늘 등록되었는지 확인
            existing = db.query(SectorRotationEvent).filter(
                and_(
                    SectorRotationEvent.from_sector_id == from_id,
                    SectorRotationEvent.to_sector_id == to_id,
                    sa_func.date(SectorRotationEvent.detected_at) == today,
                )
            ).first()
            if existing:
                continue

            event = SectorRotationEvent(
                from_sector_id=from_id,
                to_sector_id=to_id,
                confidence=0.5,  # 기본 신뢰도
            )
            db.add(event)
            events.append(event)

    if events:
        db.commit()
        logger.info("섹터 로테이션 %d건 감지", len(events))

    return events


def get_rotation_adjusted_confidence(
    db: Session,
    sector_id: int,
    original_confidence: float,
) -> float:
    """로테이션 이벤트에 의한 confidence 조정값을 반환한다.

    REQ-AI-017: 로테이션 시 이전 섹터 매수 시그널 confidence -0.15.

    Args:
        db: SQLAlchemy 세션
        sector_id: 확인할 섹터 ID
        original_confidence: 원본 confidence 값

    Returns:
        조정된 confidence 값 (최소 0.0)
    """
    today = date.today()

    # 오늘 이 섹터가 "이전 모멘텀 섹터"(from_sector)로 기록되었는지 확인
    rotation = db.query(SectorRotationEvent).filter(
        and_(
            SectorRotationEvent.from_sector_id == sector_id,
            sa_func.date(SectorRotationEvent.detected_at) == today,
        )
    ).first()

    if rotation:
        adjusted = max(0.0, original_confidence + ROTATION_CONFIDENCE_ADJUSTMENT)
        logger.info(
            "섹터 로테이션으로 confidence 조정: sector_id=%d, %.2f → %.2f",
            sector_id, original_confidence, adjusted,
        )
        return adjusted

    return original_confidence


def deduplicate_sector_signals(
    signals: list[dict],
    max_per_sector: int = MAX_SIGNALS_PER_SECTOR,
) -> tuple[list[dict], list[dict]]:
    """동일 섹터 내 매수 시그널을 중복 제거한다.

    REQ-AI-019: 같은 섹터 내 3개+ 매수 시그널 → 최대 2개로 제한.
    우선순위:
      1) composite_score 상위
      2) trend_alignment == "aligned" 우선
      3) volume_spike 감지 종목 우선

    Args:
        signals: 시그널 리스트 [{"stock_name": str, "sector_id": int,
                 "composite_score": float, "trend_alignment": str,
                 "volume_spike": bool, ...}, ...]
        max_per_sector: 섹터당 최대 시그널 수

    Returns:
        (선정_시그널, 제외_시그널) 튜플
    """
    if not signals:
        return [], []

    # 섹터별 그룹핑
    sector_groups: dict[int, list[dict]] = {}
    for sig in signals:
        sid = sig.get("sector_id")
        if sid is None:
            continue
        sector_groups.setdefault(sid, []).append(sig)

    selected: list[dict] = []
    excluded: list[dict] = []

    for sector_id, group in sector_groups.items():
        if len(group) <= max_per_sector:
            selected.extend(group)
            continue

        # 정렬 기준: composite_score 내림차순 → aligned 우선 → volume_spike 우선
        sorted_group = sorted(
            group,
            key=lambda s: (
                s.get("composite_score", 0.0),
                1 if s.get("trend_alignment") == "aligned" else 0,
                1 if s.get("volume_spike", False) else 0,
            ),
            reverse=True,
        )

        selected.extend(sorted_group[:max_per_sector])
        excluded.extend(sorted_group[max_per_sector:])

    if excluded:
        logger.info(
            "섹터 시그널 중복 제거: %d개 시그널 중 %d개 선정, %d개 제외",
            len(signals), len(selected), len(excluded),
        )

    return selected, excluded


def format_sector_momentum_for_briefing(
    momentum_data: list[dict],
    inflow_data: list[dict] | None = None,
    rotation_events: list[SectorRotationEvent] | None = None,
    db: Session | None = None,
) -> str:
    """섹터 모멘텀 분석 결과를 브리핑용 텍스트로 포맷팅한다.

    Args:
        momentum_data: detect_momentum_sectors() 결과
        inflow_data: detect_capital_inflow() 결과
        rotation_events: detect_sector_rotation() 결과
        db: 섹터명 조회용 세션 (로테이션 이벤트 표시 시 필요)

    Returns:
        브리핑에 삽입할 섹터 모멘텀 분석 텍스트
    """
    lines = ["## 섹터 모멘텀 분석"]

    # 모멘텀 섹터
    if momentum_data:
        lines.append("\n### 모멘텀 섹터 (시장 대비 +2%p 이상)")
        for m in momentum_data:
            lines.append(
                f"  - {m['sector_name']}: 5일 평균 등락률 {m['avg_return']:.2f}% "
                f"(시장 대비 +{m['excess_return']:.2f}%p)"
            )
    else:
        lines.append("\n현재 뚜렷한 모멘텀 섹터가 없습니다.")

    # 자금 유입
    if inflow_data:
        lines.append("\n### 자금 유입 감지 (3일 연속 상승)")
        for inf in inflow_data:
            lines.append(
                f"  - {inf['sector_name']}: {inf['consecutive_positive_days']}일 연속 상승, "
                f"일평균 +{inf['avg_daily_return']:.2f}%"
            )

    # 섹터 로테이션
    if rotation_events and db:
        lines.append("\n### 섹터 로테이션 알림")
        for event in rotation_events:
            from_name = db.query(Sector.name).filter(Sector.id == event.from_sector_id).scalar() or "?"
            to_name = db.query(Sector.name).filter(Sector.id == event.to_sector_id).scalar() or "?"
            lines.append(
                f"  - {from_name} → {to_name} 로테이션 감지 "
                f"(이전 섹터 매수 시그널 confidence -0.15 조정)"
            )

    return "\n".join(lines)
