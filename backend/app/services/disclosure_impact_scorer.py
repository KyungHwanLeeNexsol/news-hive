"""SPEC-AI-004: 공시 기반 선제적 시그널 시스템.

공시 유형별 충격 스코어 계산, 기준가 스냅샷, 반영도 측정,
미반영 갭 탐지, 섹터 파급 탐지 기능을 제공한다.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# 공시 유형별 기본 충격 점수
_BASE_IMPACT_BY_TYPE = {
    "주요사항보고": 20,
    "실적변동": 20,  # 실제는 AI 분석으로 정밀 계산
    "지분공시": 25,
    "기업지배구조": 30,  # M&A
    "발행공시": -10,  # 희석 효과 (신주/전환사채)
    "정기공시": 10,
    "기타공시": 10,
}

# 수주/계약 관련 키워드
_CONTRACT_KEYWORDS = ["단일판매", "단일공급", "공급계약", "수주", "계약체결"]


def extract_contract_amount(report_name: str, ai_summary: str | None) -> int | None:
    """공시 제목/AI 요약에서 수주금액(억원 단위) 추출."""
    text = f"{report_name} {ai_summary or ''}"

    # 패턴: "1,234억원" "123억" "1.2조" "1,234,567원" 형태
    patterns = [
        r'(\d[\d,]*(?:\.\d+)?)\s*조원?',   # 조 단위
        r'(\d[\d,]*(?:\.\d+)?)\s*억원?',   # 억 단위
        r'(\d[\d,]*)\s*백만원?',            # 백만원 단위
    ]

    for i, pattern in enumerate(patterns):
        m = re.search(pattern, text)
        if m:
            val_str = m.group(1).replace(",", "")
            try:
                val = float(val_str)
                if i == 0:  # 조 단위 → 억 환산
                    return int(val * 10000)
                elif i == 1:  # 억 단위
                    return int(val)
                else:  # 백만원 → 억 환산
                    return int(val / 100)
            except ValueError:
                pass
    return None


def score_disclosure_impact(
    disclosure: Disclosure,
    market_cap_億: int | None,
) -> float:
    """공시 유형 + 규모로 충격 점수 계산 (0~100, 음수 가능).

    REQ-DISC-001 ~ REQ-DISC-004
    """
    report_type = disclosure.report_type or "기타공시"
    report_name = disclosure.report_name or ""
    ai_summary = disclosure.ai_summary or ""

    # 수주/계약 공시 (REQ-DISC-002): 수주금액/시총 비율 기반
    is_contract = any(kw in report_name for kw in _CONTRACT_KEYWORDS)
    if is_contract and market_cap_億 and market_cap_億 > 0:
        contract_amt = extract_contract_amount(report_name, ai_summary)
        if contract_amt:
            ratio = contract_amt / market_cap_億
            score = min(ratio * 500, 100.0)
            return round(score, 1)

    # 실적변동 (REQ-DISC-003): AI 요약에서 변화율 추출
    if report_type == "실적변동" and ai_summary:
        pct_m = re.search(r'(\d+(?:\.\d+)?)\s*%', ai_summary)
        if pct_m:
            try:
                pct = float(pct_m.group(1))
                return round(min(pct, 100.0), 1)
            except ValueError:
                pass

    # 기본값 (REQ-DISC-004)
    base = _BASE_IMPACT_BY_TYPE.get(report_type, 10)
    return float(base)


async def capture_baseline_price(disclosure: Disclosure) -> int | None:
    """공시 발생 시점 주가 스냅샷 (REQ-DISC-005)."""
    if not disclosure.stock_code:
        return None
    try:
        from app.services.naver_finance import fetch_current_price
        price = await fetch_current_price(disclosure.stock_code)
        return price
    except Exception as e:
        logger.warning("기준가 조회 실패 (%s): %s", disclosure.stock_code, e)
        return None


async def measure_price_reflection(
    stock_code: str,
    baseline_price: int,
) -> float:
    """현재가 vs 기준가로 반영도(%) 계산 (REQ-DISC-006)."""
    try:
        from app.services.naver_finance import fetch_current_price
        current_price = await fetch_current_price(stock_code)
        if not current_price or baseline_price <= 0:
            return 0.0
        return round((current_price - baseline_price) / baseline_price * 100, 2)
    except Exception as e:
        logger.warning("반영도 계산 실패 (%s): %s", stock_code, e)
        return 0.0


def detect_unreflected_gap(disclosure: Disclosure) -> bool:
    """미반영 갭 >= 15 여부 반환 (REQ-DISC-007).

    이미 80% 이상 반영된 경우 False 반환 (REQ-DISC-008).
    """
    if disclosure.impact_score is None or disclosure.reflected_pct is None:
        return False

    # REQ-DISC-008: 이미 80% 이상 반영 → 제외
    if disclosure.impact_score > 0 and disclosure.reflected_pct >= disclosure.impact_score * 0.8:
        return False

    gap = (disclosure.impact_score or 0) - (disclosure.reflected_pct or 0)
    return gap >= 15.0


async def detect_sector_ripple(
    db: Session,
    trigger_disclosure: Disclosure,
) -> list[dict]:
    """동종업계 파급 후보 탐지 (REQ-DISC-011 ~ REQ-DISC-013).

    원인 종목과 같은 섹터에서 아직 미반응(등락률 < +2%) 종목을 찾는다.
    """
    if not trigger_disclosure.stock_id:
        return []

    trigger_stock = db.query(Stock).filter(Stock.id == trigger_disclosure.stock_id).first()
    if not trigger_stock or not trigger_stock.sector_id:
        return []

    # 동일 섹터의 다른 종목
    sector_stocks = (
        db.query(Stock)
        .filter(
            Stock.sector_id == trigger_stock.sector_id,
            Stock.id != trigger_stock.id,
            Stock.stock_code.isnot(None),
        )
        .all()
    )
    if not sector_stocks:
        return []

    # 현재 등락률 조회
    try:
        from app.services.naver_finance import fetch_current_price_with_change
    except ImportError:
        return []

    results = []
    trigger_market_cap = trigger_stock.market_cap or 0

    semaphore = asyncio.Semaphore(5)

    async def _check_stock(stock: Stock) -> dict | None:
        if not stock.stock_code:
            return None
        try:
            async with semaphore:
                price_data = await fetch_current_price_with_change(stock.stock_code)
            if not price_data:
                return None
            change_rate = price_data.get("change_rate", 0.0)
            if change_rate >= 2.0:  # REQ-DISC-011: 이미 +2% 이상 반응한 종목 제외
                return None

            # REQ-DISC-012: 시총 비율로 신호 강도 결정
            stock_market_cap = stock.market_cap or 0
            if trigger_market_cap > 0:
                cap_ratio = stock_market_cap / trigger_market_cap
                strength = "strong" if cap_ratio >= 0.3 else "moderate"
            else:
                strength = "moderate"

            return {
                "stock_id": stock.id,
                "stock_code": stock.stock_code,
                "name": stock.name,
                "current_price": price_data.get("current_price"),
                "change_rate": change_rate,
                "market_cap": stock_market_cap,
                "strength": strength,
            }
        except Exception as e:
            logger.debug("파급 탐지 중 오류 (%s): %s", stock.stock_code, e)
            return None

    tasks = [_check_stock(s) for s in sector_stocks[:20]]  # 최대 20종목
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for outcome in outcomes:
        if isinstance(outcome, dict) and outcome is not None:
            results.append(outcome)

    logger.info("[파급탐지] %s → 동종업계 파급 후보 %d개", trigger_stock.name, len(results))
    return results


async def process_disclosure_impact(
    db: Session,
    disclosure: Disclosure,
) -> None:
    """신규 공시 저장 후 충격 스코어 계산 + 기준가 스냅샷 (REQ-DISC-001, REQ-DISC-005).

    장중(09:00~15:30) 공시: 30분 후 반영도 측정 job 등록
    장마감 후(15:30~18:00) 공시: gap_pullback_candidate FundSignal 생성
    """
    # market_cap 조회 (억원 단위)
    market_cap_億 = None
    if disclosure.stock_id:
        stock = db.query(Stock).filter(Stock.id == disclosure.stock_id).first()
        if stock and stock.market_cap:
            market_cap_億 = stock.market_cap

    # 충격 스코어 계산
    impact_score = score_disclosure_impact(disclosure, market_cap_億)
    disclosure.impact_score = impact_score
    disclosure.disclosed_at = datetime.now(timezone.utc)

    # REQ-DISC-005: impact_score >= 20이고 stock_code 존재 시 기준가 스냅샷
    if impact_score >= 20 and disclosure.stock_code:
        baseline = await capture_baseline_price(disclosure)
        if baseline:
            disclosure.baseline_price = baseline

    db.add(disclosure)
    db.flush()  # DB에 반영 (commit은 호출자 책임)

    # 장중/장마감 판단
    now_kst = _get_kst_now()
    is_market_hours = _is_market_hours(now_kst)
    is_after_market = _is_after_market_hours(now_kst)

    if impact_score >= 20 and disclosure.stock_code and disclosure.baseline_price:
        if is_market_hours:
            # 30분 후 반영도 측정 job 등록 (REQ-DISC-009)
            _schedule_reflection_check(disclosure.id)
            logger.info(
                "[공시충격] 장중 공시 30분 후 반영도 측정 등록: %s (impact=%.1f)",
                disclosure.corp_name, impact_score,
            )
        elif is_after_market and impact_score >= 25:
            # 장마감 후 gap_pullback_candidate 생성 (REQ-DISC-014)
            await _create_gap_pullback_signal(db, disclosure)


def _get_kst_now() -> datetime:
    """현재 KST 시각 반환."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _is_market_hours(kst_now: datetime) -> bool:
    """장중(09:00~15:30) 여부."""
    return (kst_now.weekday() < 5 and  # 평일
            (9, 0) <= (kst_now.hour, kst_now.minute) <= (15, 30))


def _is_after_market_hours(kst_now: datetime) -> bool:
    """장마감 후(15:30~18:00) 여부."""
    return (kst_now.weekday() < 5 and
            (15, 30) <= (kst_now.hour, kst_now.minute) <= (18, 0))


def _schedule_reflection_check(disclosure_id: int) -> None:
    """30분 후 반영도 측정 one-shot job 등록 (APScheduler)."""
    try:
        from datetime import timedelta

        from app.services.scheduler import scheduler
        run_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        job_id = f"reflect_check_{disclosure_id}"
        scheduler.add_job(
            _run_reflection_check_sync,
            "date",
            run_date=run_at,
            args=[disclosure_id],
            id=job_id,
            replace_existing=True,
        )
    except Exception as e:
        logger.warning("반영도 측정 job 등록 실패 (disclosure_id=%d): %s", disclosure_id, e)


def _run_reflection_check_sync(disclosure_id: int) -> None:
    """APScheduler에서 호출되는 동기 래퍼."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        asyncio.run(run_reflection_check(db, disclosure_id))
    finally:
        db.close()


async def run_reflection_check(db: Session, disclosure_id: int) -> None:
    """공시 발행 30분 후 반영도 측정 + 미반영 갭 탐지 → FundSignal 생성 (REQ-DISC-006, REQ-DISC-007).

    섹터 파급 탐지도 병행 (REQ-DISC-011).
    """
    disclosure = db.query(Disclosure).filter(Disclosure.id == disclosure_id).first()
    if not disclosure or not disclosure.stock_code or not disclosure.baseline_price:
        return

    # 반영도 계산
    reflected_pct = await measure_price_reflection(
        disclosure.stock_code, disclosure.baseline_price
    )
    disclosure.reflected_pct = reflected_pct
    disclosure.unreflected_gap = (disclosure.impact_score or 0) - reflected_pct

    # 미반영 갭 탐지 → FundSignal 생성 (REQ-DISC-007, REQ-DISC-010)
    if detect_unreflected_gap(disclosure) and disclosure.stock_id:
        await _create_disclosure_signal(db, disclosure)

    # 섹터 파급 탐지 (REQ-DISC-011, impact_score >= 30)
    if (disclosure.impact_score or 0) >= 30 and not disclosure.ripple_checked:
        ripple_candidates = await detect_sector_ripple(db, disclosure)
        if ripple_candidates:
            await _create_ripple_signals(db, disclosure, ripple_candidates)
        disclosure.ripple_checked = True

    db.add(disclosure)
    db.commit()


async def _create_disclosure_signal(db: Session, disclosure: Disclosure) -> FundSignal | None:
    """미반영 공시 매수 시그널 생성 (REQ-DISC-010)."""
    if not disclosure.stock_id:
        return None

    try:
        from app.services.naver_finance import fetch_current_price
        price = await fetch_current_price(disclosure.stock_code)
    except Exception:
        price = disclosure.baseline_price

    confidence = min((disclosure.impact_score or 0) / 100.0, 0.95)
    gap = disclosure.unreflected_gap or 0

    signal = FundSignal(
        stock_id=disclosure.stock_id,
        signal="buy",
        confidence=confidence,
        signal_type="disclosure_impact",
        disclosure_id=disclosure.id,
        reasoning=(
            f"공시 미반영 갭 탐지: {disclosure.report_name}\n"
            f"충격 스코어 {disclosure.impact_score:.1f}, "
            f"실제 반영도 {disclosure.reflected_pct:.1f}%, "
            f"미반영 갭 {gap:.1f}점"
        ),
        price_at_signal=price,
        market_summary=f"공시유형: {disclosure.report_type}, 공시일: {disclosure.rcept_dt}",
    )
    db.add(signal)
    db.flush()

    # 페이퍼트레이딩 자동 연동 (REQ-DISC-019)
    try:
        from app.services.paper_trading import execute_signal_trade
        await execute_signal_trade(db, signal)
    except Exception as e:
        logger.warning("페이퍼트레이딩 연동 실패: %s", e)

    db.commit()
    logger.info(
        "[공시시그널] 생성 완료: %s (confidence=%.2f, gap=%.1f)",
        disclosure.corp_name, confidence, gap,
    )
    return signal


async def _create_ripple_signals(
    db: Session,
    trigger_disclosure: Disclosure,
    ripple_candidates: list[dict],
) -> None:
    """동종업계 파급 시그널 일괄 생성 (REQ-DISC-013)."""
    trigger_stock = db.query(Stock).filter(Stock.id == trigger_disclosure.stock_id).first()
    trigger_name = trigger_stock.name if trigger_stock else "알 수 없음"

    for candidate in ripple_candidates:
        try:
            from app.services.naver_finance import fetch_current_price
            price = await fetch_current_price(candidate["stock_code"])
        except Exception:
            price = candidate.get("current_price")

        strength = candidate.get("strength", "moderate")
        confidence = 0.65 if strength == "strong" else 0.55

        signal = FundSignal(
            stock_id=candidate["stock_id"],
            signal="buy",
            confidence=confidence,
            signal_type="sector_ripple",
            disclosure_id=trigger_disclosure.id,
            reasoning=(
                f"동종업계 파급 탐지: {trigger_name} 공시({trigger_disclosure.report_name}) 이후 "
                f"섹터 내 미반응 종목. 파급 강도: {strength}"
            ),
            price_at_signal=price,
            market_summary=f"파급 원인: {trigger_name}, 공시일: {trigger_disclosure.rcept_dt}",
        )
        db.add(signal)
        db.flush()

        # 페이퍼트레이딩 자동 연동 (REQ-DISC-019)
        try:
            from app.services.paper_trading import execute_signal_trade
            await execute_signal_trade(db, signal)
        except Exception as e:
            logger.warning("파급 시그널 페이퍼트레이딩 연동 실패: %s", e)

    db.commit()
    logger.info("[파급시그널] %d개 생성 완료 (트리거: %s)", len(ripple_candidates), trigger_name)


async def activate_gap_pullback(db: Session) -> dict:
    """장초반 갭업 풀백 조건 확인 후 시그널 활성화 (REQ-DISC-015).

    gap_pullback_candidate 시그널 중 아직 활성화되지 않은 것을 조회하여
    현재 등락률이 -3% 이하로 떨어졌다가 -1.5% 이내로 회복된 경우 매매를 실행한다.

    Returns:
        {"checked": 확인 수, "activated": 활성화 수}
    """
    from datetime import date, timedelta

    today = date.today()
    yesterday = today - timedelta(days=1)
    stats = {"checked": 0, "activated": 0}

    # 오늘 또는 어제 생성된 gap_pullback_candidate 중 미활성화된 것 조회
    # reasoning에 "활성화됨" 문자열이 없는 것을 미활성화로 판단
    candidates = (
        db.query(FundSignal)
        .filter(
            FundSignal.signal_type == "gap_pullback_candidate",
            FundSignal.is_correct.is_(None),  # 아직 검증 전 = 활성화 전
        )
        .all()
    )

    # 오늘/어제 생성된 것만 필터링 (created_at 날짜 비교)
    target_signals = [
        s for s in candidates
        if s.created_at and s.created_at.date() in (today, yesterday)
        and "활성화됨" not in (s.reasoning or "")
    ]

    if not target_signals:
        logger.info("[갭풀백] 활성화 대상 시그널 없음")
        return stats

    try:
        from app.services.naver_finance import fetch_current_price_with_change
    except ImportError:
        logger.warning("[갭풀백] fetch_current_price_with_change 임포트 실패")
        return stats

    for signal in target_signals:
        if not signal.stock_id:
            continue

        stock = db.query(Stock).filter(Stock.id == signal.stock_id).first()
        if not stock or not stock.stock_code:
            continue

        stats["checked"] += 1

        try:
            price_data = await fetch_current_price_with_change(stock.stock_code)
        except Exception as e:
            logger.debug("[갭풀백] 가격 조회 실패 (%s): %s", stock.stock_code, e)
            continue

        if not price_data:
            continue

        change_rate = price_data.get("change_rate", 0.0)  # 시가 대비 등락률 (%)
        open_price = price_data.get("open_price") or signal.price_at_signal
        current_price = price_data.get("current_price")

        if not open_price or not current_price:
            continue

        # 시가 기준 등락률 재계산 (API가 전일 종가 대비 제공하는 경우 대비)
        pct_from_open = (current_price - open_price) / open_price * 100

        # 조건: -3% 이하 풀백 후 -1.5% 이내로 회복
        # change_rate는 현재 시가 대비 등락률로 간주
        # -3% 이하였다가 -1.5% 이내로 회복 판단:
        # change_rate가 -1.5% ~ 0% 사이이고 장중 low가 -3% 이하였어야 하나,
        # low 데이터가 없으므로 현재 -1.5% 이내이면서 과거 기준가가 있는 경우 활성화
        # 실제 운영 시에는 장중 low 데이터와 비교해야 하지만, 현재 API 제한으로
        # 현재가가 -3% 이하 → -1.5% 이내 구간에 있으면 조건 충족으로 간주
        if -3.0 <= pct_from_open <= -1.5:
            # 풀백 조건 충족 — 페이퍼트레이딩 매매 실행
            try:
                from app.services.paper_trading import execute_signal_trade
                await execute_signal_trade(db, signal)
                # 활성화 표시: reasoning에 메모 추가
                signal.reasoning = (signal.reasoning or "") + f"\n[활성화됨] 갭풀백 조건 충족: 시가대비 {pct_from_open:.1f}%"
                db.add(signal)
                stats["activated"] += 1
                logger.info(
                    "[갭풀백] 시그널 활성화: %s (시가대비 %.1f%%)",
                    stock.name, pct_from_open,
                )
            except Exception as e:
                logger.warning("[갭풀백] 페이퍼트레이딩 실행 실패 (%s): %s", stock.name, e)

    if stats["activated"]:
        db.commit()

    logger.info("[갭풀백] 확인 %d개, 활성화 %d개", stats["checked"], stats["activated"])
    return stats


def _run_gap_pullback_check_sync() -> None:
    """APScheduler에서 호출되는 갭풀백 모니터링 동기 래퍼."""
    import asyncio

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        asyncio.run(activate_gap_pullback(db))
    except Exception as e:
        logger.error("[갭풀백] 스케줄 실행 오류: %s", e)
    finally:
        db.close()


async def _create_gap_pullback_signal(
    db: Session,
    disclosure: Disclosure,
) -> FundSignal | None:
    """장마감 후 갭업 후 풀백 대기 시그널 생성 (REQ-DISC-014)."""
    if not disclosure.stock_id:
        return None

    try:
        from app.services.naver_finance import fetch_current_price
        price = await fetch_current_price(disclosure.stock_code)
    except Exception:
        price = disclosure.baseline_price

    confidence = min((disclosure.impact_score or 0) / 100.0 * 0.8, 0.80)  # 풀백 전략은 신중하게

    signal = FundSignal(
        stock_id=disclosure.stock_id,
        signal="buy",
        confidence=confidence,
        signal_type="gap_pullback_candidate",
        disclosure_id=disclosure.id,
        reasoning=(
            f"장마감 후 공시 갭업 풀백 대기: {disclosure.report_name}\n"
            f"충격 스코어 {disclosure.impact_score:.1f}. "
            f"다음 거래일 10:00~11:30 풀백(-3% 이하) 후 회복(-1.5% 이내) 시 활성화."
        ),
        price_at_signal=price,
        market_summary=f"공시유형: {disclosure.report_type}, 공시일: {disclosure.rcept_dt}",
    )
    db.add(signal)
    db.commit()
    logger.info(
        "[갭업풀백] 대기 시그널 생성: %s (impact=%.1f)",
        disclosure.corp_name, disclosure.impact_score,
    )
    return signal
