"""신규 종목 자동 등록 서비스.

매일 15:10 KST에 실행되어 상승률 상위 종목 중 DB 미등록 종목을 자동 추가한다.
15:20 KST 급등 시그널 생성 전에 실행되어 당일 급등 후보 종목이 누락되지 않도록 한다.
"""
import logging

import httpx
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.services.naver_finance import HEADERS, fetch_top_movers_codes

logger = logging.getLogger(__name__)

# 2차전지/EV 관련 키워드 → sector_id=23 (전기제품)
_BATTERY_KEYWORDS = {
    "리튬", "배터리", "전지", "이차전지", "양극재", "음극재",
    "전해질", "분리막", "bms", "ev", "전기차", "에너지솔루션",
}

_DEFAULT_SECTOR_ID = 7   # IT서비스 (기타 미분류)
_BATTERY_SECTOR_ID = 23  # 전기제품


def _infer_sector_id(name: str) -> int:
    """종목명 기반으로 섹터 ID 추론."""
    name_lower = name.lower()
    for kw in _BATTERY_KEYWORDS:
        if kw in name_lower:
            return _BATTERY_SECTOR_ID
    return _DEFAULT_SECTOR_ID


def fetch_tracked_stock_codes(db: Session, codes: list[str]) -> set[str] | None:
    # @MX:ANCHOR: [AUTO] SPEC-AI-074 — "앱 stocks 테이블 존재 종목만 유효 후보"라는
    # 분류 규칙의 단일 출처. fan_in>=2: SPEC-AI-071 정답 수집 경로
    # (surge_actual_outcome_service.collect_daily_surge_outcomes, 원래 구현 위치)와
    # SPEC-AI-074 Pool B 후보 정제 경로(surge_detector.build_scan_universe)가 함께 호출한다.
    # @MX:REASON: [AUTO] 분류 로직이 두 곳에 중복 구현되면 드리프트(예: 한쪽만 갱신)로
    # recall/precision이 왜곡될 위험이 있어, SPEC-AI-071에서 최초 구현된 로직을 이 중립
    # 위치로 추출해 단일 출처로 유지한다(SPEC-AI-074 REQ-001 HARD). 반환 계약(`None`=조회
    # 실패 → 호출부 fail-open)은 SPEC-AI-071 EC-1 그대로이며 변경되지 않는다.
    """결합 코드 집합 중 앱 `stocks` 테이블에 존재하는 코드 집합을 반환한다.

    DB 조회 실패 시(SSL 끊김 등) None을 반환하여 호출부가 fail-open으로
    미필터 진행하도록 위임한다(SPEC-AI-071 REQ-AI071-001 EC-1, SPEC-AI-074 REQ-AI074-004가
    동일 계약을 계승).

    호출부:
    - `surge_actual_outcome_service.collect_daily_surge_outcomes` (SPEC-AI-071, 정답 모집단 정제)
    - `surge_detector.build_scan_universe` Pool B (SPEC-AI-074, 거래량 순위 후보 정제 —
      레버리지/인버스 ETF·ETN 등 비-stocks 상품이 절대 거래량 상위를 점유해 genuine
      중·소형주를 밀어내는 크라우딩아웃 방지)

    Args:
        db: SQLAlchemy 동기 세션
        codes: 교집합 대상 코드 목록

    Returns:
        stocks에 존재하는 코드 집합. 조회 실패 시 None.
    """
    try:
        rows = db.query(Stock.stock_code).filter(Stock.stock_code.in_(codes)).all()
        return {row.stock_code for row in rows}
    except Exception as e:
        logger.warning("stocks 교집합 조회 실패 — 미필터 진행 (fail-open): %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


async def _fetch_stock_info(code: str) -> dict | None:
    """네이버 모바일 integration API에서 종목명·시가총액 조회.

    Returns:
        {"name": str, "market_cap": int} 또는 None
    """
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
        data = resp.json()
        stock_info = data.get("stockInfo", {})
        name: str = stock_info.get("stockName", "").strip()
        # 시가총액: 단위 억원 → int 변환 (콤마 제거)
        market_cap_raw: str = stock_info.get("marketValue", "0").replace(",", "")
        try:
            market_cap = int(market_cap_raw)
        except ValueError:
            market_cap = 0
        if name:
            return {"name": name, "market_cap": market_cap}
    except Exception as e:
        logger.debug("종목 정보 조회 실패 (%s): %s", code, e)
    return None


# @MX:ANCHOR: [AUTO] 신규 종목 자동 등록 진입점 — 스케줄러에서 직접 호출
# @MX:REASON: [AUTO] scheduler._run_auto_register_stocks 가 단독 호출하는 퍼블릭 함수
async def register_unknown_stocks(db: Session) -> int:
    """상승률 상위 종목 중 DB 미등록 종목을 자동 추가한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        신규 등록된 종목 수
    """
    # KOSPI + KOSDAQ 상위 30개씩 수집
    kospi_codes = await fetch_top_movers_codes("KOSPI", limit=30)
    kosdaq_codes = await fetch_top_movers_codes("KOSDAQ", limit=30)

    all_codes: dict[str, str] = {}  # code → market
    for code in kospi_codes:
        all_codes[code] = "KOSPI"
    for code in kosdaq_codes:
        all_codes.setdefault(code, "KOSDAQ")

    if not all_codes:
        logger.warning("상승률 상위 종목 조회 결과 없음 — 자동 등록 스킵")
        return 0

    # DB에 이미 등록된 종목 코드 조회
    existing_codes: set[str] = {
        row[0] for row in db.query(Stock.stock_code).all()
    }

    new_codes = {
        code: mkt for code, mkt in all_codes.items() if code not in existing_codes
    }
    if not new_codes:
        logger.debug("신규 등록 대상 종목 없음")
        return 0

    registered = 0
    for code, market in new_codes.items():
        try:
            info = await _fetch_stock_info(code)
            if not info or not info.get("name"):
                logger.debug("종목 정보 없음 — 스킵: %s", code)
                continue

            sector_id = _infer_sector_id(info["name"])
            stock = Stock(
                sector_id=sector_id,
                name=info["name"],
                stock_code=code,
                market=market,
                market_cap=info["market_cap"],
                keywords=[],
            )
            db.add(stock)
            db.flush()
            registered += 1
            logger.info(
                "신규 종목 자동 등록: %s (%s) market=%s sector=%d",
                info["name"], code, market, sector_id,
            )
        except Exception as e:
            logger.error("종목 등록 실패 (%s): %s", code, e)
            db.rollback()
            continue

    if registered > 0:
        db.commit()
        logger.info("자동 종목 등록 완료: %d개", registered)

    return registered
