"""SPEC-AI-004: 공시 기반 선제적 시그널 시스템.

공시 유형별 충격 스코어 계산, 기준가 스냅샷, 반영도 측정,
미반영 갭 탐지, 섹터 파급 탐지 기능을 제공한다.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.stock import Stock
# SPEC-AI-080 [X-2]: 화이트리스트 키워드만 read-only로 재사용 — 탐지기 로직/상수는 미변경
from app.services.surge_detector import _IMMEDIATE_EVENT_PATTERNS
from app.surge_config.surge_settings import get_surge_config

logger = logging.getLogger(__name__)


async def _set_volatility_context(signal: FundSignal) -> None:
    """시그널에 시장 변동성 레벨을 추가한다.

    공시 기반 시그널은 factor_scores 계산을 거치지 않으므로
    volatility_level 만 보강한다.
    """
    try:
        from app.services.market_context import get_market_volatility
        vol_info = await get_market_volatility()
        signal.volatility_level = vol_info["volatility_level"]
    except Exception as e:
        logger.warning("변동성 컨텍스트 추가 실패: %s", e)

# 공시 유형별 기본 충격 점수
# @MX:NOTE: "기업지배구조"는 M&A부터 정기주총결과까지 혼재 — 기본값은 보수적으로 설정하고
#           M&A 키워드(합병/분할/영업양수도 등)가 감지된 경우에만 _MNA_BONUS 가산
_BASE_IMPACT_BY_TYPE = {
    "주요사항보고": 20,
    "실적변동": 20,  # 실제는 AI 분석으로 정밀 계산
    "지분공시": 25,
    "기업지배구조": 10,  # 기본은 루틴(AGM 등), M&A는 키워드 감지 시 +20 가산
    "발행공시": -10,  # 희석 효과 (신주/전환사채)
    "정기공시": 10,
    "기타공시": 10,
}

# 수주/계약 관련 키워드
_CONTRACT_KEYWORDS = ["단일판매", "단일공급", "공급계약", "수주", "계약체결"]

# @MX:NOTE: 루틴 거버넌스 공시 — 섹터 파급 트리거 대상에서 제외
# 정기주총/소집공고/사외이사 변경/기재정정 단독/기업가치제고계획 재공시 등은
# 시장에 실질 충격을 주지 않으므로 impact_score를 5로 제한하여 파급 임계(30) 미달 처리
_ROUTINE_GOVERNANCE_KEYWORDS = [
    "정기주주총회결과",
    "정기주주총회 소집",
    "주주총회소집공고",
    "주주총회 소집공고",
    "임시주주총회 소집",
    "사외이사의 선임",
    "사외이사의 해임",
    "사외이사의 중도퇴임",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "임원·주요주주특정증권등소유상황보고서",
    "임원 주요주주",
    "기업가치제고계획",
    "주주우선공모",  # 단독 공시는 루틴
]

# @MX:NOTE: M&A/분할/영업양수도 키워드 — "기업지배구조"에 가산점 부여
_MNA_KEYWORDS = [
    "합병",
    "분할",
    "영업양수",
    "영업양도",
    "주식교환",
    "주식이전",
    "포괄적 주식",
    "자산양수",
    "자산양도",
]
_MNA_BONUS = 20

# SPEC-AI-051: 공시 키워드 Tier 배수 사전
# Tier 1 (×2.0): 최고가치 이벤트
_KEYWORD_TIER1 = ["FDA 승인", "세계 최초", "독점 공급", "최대주주 변경", "국가전략기술", "국책사업 선정"]
# Tier 2 (×1.5): 고가치 기업 이벤트
_KEYWORD_TIER2 = ["공급계약 체결", "지분 인수", "합병", "MOU 체결", "수주", "자사주 소각"]
# Tier 3 (×1.2): 중가치 이벤트
_KEYWORD_TIER3 = ["신제품 출시", "신규 수주", "매출 급증", "계열사 지원"]


def _get_keyword_tier_multiplier(report_name: str, ai_summary: str | None) -> float:
    """report_name + ai_summary에서 최고 Tier 키워드 1개의 배수 반환.

    매칭 없으면 1.0 반환 (배수 없음).
    누적 적용 없이 최고 Tier 1개만 사용.
    """
    text = report_name + " " + (ai_summary or "")
    if any(kw in text for kw in _KEYWORD_TIER1):
        return 2.0
    if any(kw in text for kw in _KEYWORD_TIER2):
        return 1.5
    if any(kw in text for kw in _KEYWORD_TIER3):
        return 1.2
    return 1.0


# @MX:NOTE: 지주사 임시 블랙리스트 — 섹터 파급 후보에서 제외
# @MX:REASON: 지주사는 본업 노출이 희석되어 있어 섹터 단위 이벤트에 연동되지 않음.
#             stocks 테이블에 company_type 컬럼 도입 전까지 임시 운영
_HOLDING_COMPANY_CODES: set[str] = {
    # 일반지주
    "034730",  # SK
    "003550",  # LG
    "078930",  # GS
    "282330",  # BGF
    "006120",  # SK디스커버리
    "001740",  # SK네트웍스
    "267250",  # HD현대
    "000150",  # 두산
    "004990",  # 롯데지주
    "097230",  # HJ중공업(한진중공업지주 성격)
    # 금융지주
    "086790",  # 하나금융지주
    "316140",  # 우리금융지주
    "105560",  # KB금융
    "055550",  # 신한지주
    "138040",  # 메리츠금융지주
    "175330",  # JB금융지주
    "139130",  # DGB금융지주
    "071050",  # 한국금융지주
}


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

    # @MX:NOTE: 루틴 거버넌스 공시는 시장 충격 없음 → 5점으로 캡, 섹터 파급 트리거(30) 미달 처리
    #           과거 "정기주주총회결과" "사외이사 선임 신고" 등이 30점을 받아 sector_ripple을 오발시킨 버그 교정
    normalized = report_name.replace(" ", "").replace("·", "")
    if any(kw.replace(" ", "").replace("·", "") in normalized for kw in _ROUTINE_GOVERNANCE_KEYWORDS):
        return 5.0

    # 수주/계약 공시 (REQ-DISC-002): 수주금액/시총 비율 기반
    is_contract = any(kw in report_name for kw in _CONTRACT_KEYWORDS)
    if is_contract and market_cap_億 and market_cap_億 > 0:
        contract_amt = extract_contract_amount(report_name, ai_summary)
        if contract_amt:
            ratio = contract_amt / market_cap_億
            score = min(ratio * 500, 100.0)
            # SPEC-AI-051 REQ-AI051-005: Tier 배수 적용 (루틴 거버넌스 경로 제외)
            score = min(score * _get_keyword_tier_multiplier(report_name, ai_summary), 100.0)
            return round(score, 1)

    # 실적변동 (REQ-DISC-003): AI 요약에서 변화율 추출
    if report_type == "실적변동" and ai_summary:
        pct_m = re.search(r'(\d+(?:\.\d+)?)\s*%', ai_summary)
        if pct_m:
            try:
                pct = float(pct_m.group(1))
                # SPEC-AI-051 REQ-AI051-005: Tier 배수 적용
                multiplied = round(min(pct * _get_keyword_tier_multiplier(report_name, ai_summary), 100.0), 1)
                return multiplied
            except ValueError:
                pass

    # 기본값 (REQ-DISC-004)
    base = _BASE_IMPACT_BY_TYPE.get(report_type, 10)

    # @MX:NOTE: 기업지배구조 공시 중 M&A 키워드 감지 시 +20 가산 (합병/분할/영업양수도 등)
    if report_type == "기업지배구조" and any(kw in report_name for kw in _MNA_KEYWORDS):
        base += _MNA_BONUS

    # SPEC-AI-051 REQ-AI051-005: Tier 배수 적용
    multiplier = _get_keyword_tier_multiplier(report_name, ai_summary)
    return round(min(float(base) * multiplier, 100.0), 1)


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

    # @MX:NOTE: 지주사/우선주/시총 역전 종목은 파급 후보에서 제외 (2026-04 교정)
    # @MX:REASON: 기존 로직은 "석유와가스" 섹터에 SK/GS 등 지주사까지 포함하고,
    #             파급받는 종목이 원인 종목보다 커도 strong 판정 → S-Oil AGM → SK 오매수 발생
    """
    if not trigger_disclosure.stock_id:
        return []

    trigger_stock = db.query(Stock).filter(Stock.id == trigger_disclosure.stock_id).first()
    if not trigger_stock or not trigger_stock.sector_id:
        return []

    # 동일 섹터의 다른 종목 — 우선주 제외(종목코드 말자리 0 아닌 경우)
    sector_stocks = (
        db.query(Stock)
        .filter(
            Stock.sector_id == trigger_stock.sector_id,
            Stock.id != trigger_stock.id,
            Stock.stock_code.isnot(None),
        )
        .all()
    )
    # 우선주 제외 (KRX 종목코드 말자리 5/7/9 는 우선주)
    sector_stocks = [s for s in sector_stocks if s.stock_code and s.stock_code[-1] not in {"5", "7", "9"}]
    # 지주사 제외 (임시 블랙리스트 — 추후 stocks 테이블에 company_type 컬럼 도입 시 교체)
    sector_stocks = [s for s in sector_stocks if s.stock_code not in _HOLDING_COMPANY_CODES]
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
            # @MX:NOTE: cap_ratio 상한 1.5 — 타깃이 원인 종목보다 1.5배 이상 크면 파급 방향 역전 의심 → 제외
            stock_market_cap = stock.market_cap or 0
            if trigger_market_cap > 0:
                cap_ratio = stock_market_cap / trigger_market_cap
                if cap_ratio > 1.5:
                    return None  # 시총 역전 — 파급 대상 부적합
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

    # SPEC-AI-080 REQ-AI080-001~005: 고확신 당일 촉매 즉시 발화 — 30분 반영-갭 게이트
    # (run_reflection_check → detect_unreflected_gap)를 기다리지 않고 DART 수집 시점에
    # recall 집계 가능한 surge_candidate를 즉시 발화한다. 다른 공시 유형의 반영-갭 경로는
    # 아래에 그대로 남아 불변이다([X-3]).
    # @MX:NOTE: [AUTO] SPEC-AI-080 — immediate_surge.enabled=false(기본값)이면 이 분기가
    # 전혀 평가/실행되지 않아 아래 레거시 반영-갭 경로만 동작한다(Scenario 6, rollback 완전성).
    # 발화 시 execute_signal_trade를 호출하지 않는다(REQ-005 — 예측 기록 전용 배선,
    # SPEC-AI-043 페이퍼 트레이딩 비활성 모드와 일관).
    # @MX:SPEC: SPEC-AI-080 REQ-AI080-001
    immediate_cfg = get_surge_config().immediate_surge
    if (
        immediate_cfg.enabled
        and disclosure.stock_id
        and disclosure.stock_code
        and impact_score >= immediate_cfg.min_impact
        and _is_immediate_event_class(disclosure.report_name)
    ):
        horizon = _classify_disclosure_horizon(now_kst, immediate_cfg)
        await _create_immediate_surge_signal(db, disclosure, impact_score, horizon)
        return

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


# ---------------------------------------------------------------------------
# SPEC-AI-080: 동일-당일 고확신 공시 촉매 즉시 급등 시그널 발화
# ---------------------------------------------------------------------------

def _is_immediate_event_class(report_name: str | None) -> bool:
    """REQ-AI080-003: 즉시 발화 대상 고확신 이벤트 클래스 화이트리스트 판정.

    surge_detector._IMMEDIATE_EVENT_PATTERNS(자사주소각/단일판매·공급계약체결/흡수합병 등)
    의 키워드만 read-only로 재사용한다([X-2] — 탐지기 본체 로직/상수 자체는 변경하지
    않음, 별도 화이트리스트를 새로 만들지 않아 단일 출처 유지). 점수(0~1)는 사용하지
    않고 키워드 존재 여부만 판정에 쓴다(REQ-002 — 게이팅은 impact_score 기준, flat 점수
    상수는 재도입하지 않음).
    """
    if not report_name:
        return False
    return any(keyword in report_name for keyword, _score in _IMMEDIATE_EVENT_PATTERNS)


def _classify_disclosure_horizon(kst_now: datetime, cfg) -> str:
    """OQ-2: 접수 시각 기준 recall 편입 지평 분류 (REQ-AI080-004).

    Reception 09:00~batch_cutoff(기본 15:20) KST 평일(배치가 이미 볼 수 있었던 시간대)
    → "same_day"(둘째 규칙 — T-1→T 버킷 배제, 별도 서브지표). 그 외(컷오프 이후/
    장마감후/야간/장전/주말) → "next_day"(첫째 규칙 — T-1→T predicted_set 편입 대상).
    """
    if kst_now.weekday() < 5:
        start = (9, 0)
        cutoff = (cfg.batch_cutoff_hour, cfg.batch_cutoff_minute)
        now_hm = (kst_now.hour, kst_now.minute)
        if start <= now_hm < cutoff:
            return "same_day"
    return "next_day"


async def _create_immediate_surge_signal(
    db: Session,
    disclosure: Disclosure,
    impact_score: float,
    horizon: str,
) -> FundSignal | None:
    """SPEC-AI-080 REQ-AI080-001~006: 고확신 당일 촉매 즉시 급등-집계 시그널 발화.

    signal_type="surge_candidate" + surge_metadata(non-None, surge_basis에
    "immediate_disclosure" 포함, OQ-5)로 발화하여 evaluate_surge_predictions()의
    predicted_set 필터(surge_evaluation_service.py:553-555)에 편입 가능하게 한다.
    execute_signal_trade는 절대 호출하지 않는다(REQ-005 — 예측 기록 전용).

    REQ-006/Scenario 5: 기존 5역일 네이티브 업서트 조회 키(stock_id +
    signal_type=="surge_candidate" + created_at>=5일전, fund_manager.py:1437-1445)에
    정합하는 사전 조회를 여기서도 수행해 배치와의 중복 INSERT를 피한다 — 기존 행이
    있으면 UPDATE, 없으면 신규 INSERT.
    """
    if not disclosure.stock_id:
        return None

    try:
        from app.services.naver_finance import fetch_current_price
        price = await fetch_current_price(disclosure.stock_code)
    except Exception:
        price = disclosure.baseline_price

    confidence = min(max(impact_score, 0.0) / 100.0, 0.95)
    matched_class = next(
        (kw for kw, _score in _IMMEDIATE_EVENT_PATTERNS if kw in (disclosure.report_name or "")),
        None,
    )
    now_utc = datetime.now(timezone.utc)

    # OQ-5: (a) non-None이어야 recall 필터(surge_metadata.isnot(None))를 통과하고,
    # (b) surge_basis에 near_limit_up_carry를 포함하지 않아 _is_near_limit_up_carry_signal에
    # 오판되지 않으며, (c) fund_manager.py의 마커 인지형 스킵이 이 마커로 즉시 발화 행을
    # 식별해 created_at·마커를 보존할 수 있어야 한다(DP-1).
    metadata = {
        "surge_basis": ["immediate_disclosure"],
        "immediate_disclosure": True,
        "surge_probability_score": round(confidence, 4),
        "event_class": matched_class,
        "impact_score": impact_score,
        "disclosure_id": disclosure.id,
        "horizon": horizon,
        "rcept_dt": disclosure.rcept_dt,
    }
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    reasoning = (
        f"[SPEC-AI-080 즉시발화] {disclosure.report_name} — "
        f"impact={impact_score:.1f}, horizon={horizon}"
    )

    five_days_ago = now_utc - timedelta(days=5)
    existing = (
        db.query(FundSignal)
        .filter(
            FundSignal.stock_id == disclosure.stock_id,
            FundSignal.signal_type == "surge_candidate",
            FundSignal.created_at >= five_days_ago,
        )
        .first()
    )

    if existing:
        existing.confidence = confidence
        existing.surge_metadata = metadata_json
        existing.reasoning = reasoning
        if existing.originally_created_at is None:
            existing.originally_created_at = existing.created_at
        existing.created_at = now_utc
        if existing.price_at_signal is None and price is not None:
            existing.price_at_signal = price
        signal = existing
    else:
        signal = FundSignal(
            stock_id=disclosure.stock_id,
            signal="buy",
            confidence=confidence,
            signal_type="surge_candidate",
            surge_metadata=metadata_json,
            disclosure_id=disclosure.id,
            reasoning=reasoning,
            originally_created_at=now_utc,
            created_at=now_utc,
            price_at_signal=price,
        )
        db.add(signal)

    db.flush()
    await _set_volatility_context(signal)
    db.commit()

    logger.info(
        "[즉시발화] %s 생성/갱신 완료 (impact=%.1f, confidence=%.2f, horizon=%s)",
        disclosure.corp_name, impact_score, confidence, horizon,
    )
    return signal


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

    await _set_volatility_context(signal)

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

        await _set_volatility_context(signal)

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
        # SSL 연결 끊김 시 rollback/close 자체가 에러를 던져 APScheduler로 전파되므로 방어
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


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
    db.flush()
    await _set_volatility_context(signal)
    db.commit()
    logger.info(
        "[갭업풀백] 대기 시그널 생성: %s (impact=%.1f)",
        disclosure.corp_name, disclosure.impact_score,
    )
    return signal
