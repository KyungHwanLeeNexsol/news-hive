"""KOSPI 200 스토캐스틱+이격도 매매 신호 계산 서비스.

SPEC-KS200-001
"""
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 지표 파라미터
STO1 = 12    # %K 기간 (lookback window)
STO2 = 5     # %K 슬로잉 기간 (SMA of %K_raw)
STO3 = 5     # %D 기간 (SMA of %K_slow) — 현재 전략에서는 미사용 (crossover는 %K_slow 기준)
PERIOD3 = 20  # 이격도 이동평균 기간

# 임계값
STOCH_LOWER = 20.0
STOCH_UPPER = 80.0
DISP_LOWER = 97.0
DISP_UPPER = 103.0


@dataclass
class SignalResult:
    """신호 계산 결과."""

    stock_code: str
    signal: str   # "buy" / "sell" / "hold"
    stoch_k: float
    disparity: float
    price: int


def calculate_stochastics_slow(prices_newest_first: list) -> tuple[float | None, float | None]:
    """스토캐스틱 슬로우 %K_slow 현재값과 이전값을 계산한다.

    prices_newest_first: PriceRecord 리스트 (최신순 정렬, fetch_stock_price_history 반환값)
    Returns: (curr_stoch_k, prev_stoch_k) — 데이터 부족 시 (None, None)
    """
    # 최신순 → 과거순으로 변환 (계산 편의)
    prices = list(reversed(prices_newest_first))
    n = len(prices)

    # %K_slow 계산에 필요한 최소 봉 수: STO1 + STO2 - 1 = 16, crossover에 prev 필요 → +1 = 17
    min_bars = STO1 + STO2 - 1 + 1
    if n < min_bars:
        return None, None

    # 각 봉에 대해 raw %K 계산 (STO1 기간 lookback)
    k_raw: list[float] = []
    for i in range(STO1 - 1, n):
        window = prices[i - STO1 + 1 : i + 1]
        lo = min(p.low for p in window)
        hi = max(p.high for p in window)
        if hi == lo:
            # 고가=저가 엣지케이스: 중간값 50으로 설정
            k_raw.append(50.0)
        else:
            k_raw.append((prices[i].close - lo) / (hi - lo) * 100.0)

    # %K_raw에 STO2 기간 SMA 적용 → %K_slow
    if len(k_raw) < STO2:
        return None, None

    k_slow: list[float] = []
    for i in range(STO2 - 1, len(k_raw)):
        k_slow.append(sum(k_raw[i - STO2 + 1 : i + 1]) / STO2)

    # crossover 판단에는 현재값과 이전값 2개 필요
    if len(k_slow) < 2:
        return None, None

    return k_slow[-1], k_slow[-2]  # (curr, prev)


def calculate_disparity(prices_newest_first: list) -> tuple[float | None, float | None]:
    """이격도 현재값과 이전값을 계산한다.

    이격도 = (종가 / MA20) * 100

    Returns: (curr_disparity, prev_disparity) — 데이터 부족 시 (None, None)
    """
    prices = list(reversed(prices_newest_first))
    n = len(prices)

    # MA20 계산에 PERIOD3개 필요, 이전값 계산에 1개 추가 → PERIOD3 + 1 = 21
    if n < PERIOD3 + 1:
        return None, None

    closes = [p.close for p in prices]

    # 현재: 마지막 PERIOD3개 종가의 평균
    ma_curr = sum(closes[-PERIOD3:]) / PERIOD3
    # 이전: 마지막에서 두 번째 PERIOD3개 종가의 평균
    ma_prev = sum(closes[-PERIOD3 - 1 : -1]) / PERIOD3

    if ma_curr == 0 or ma_prev == 0:
        return None, None

    curr_d = closes[-1] / ma_curr * 100.0
    prev_d = closes[-2] / ma_prev * 100.0
    return curr_d, prev_d


def check_signal(prices_newest_first: list) -> SignalResult | None:
    """스토캐스틱+이격도 매매 신호를 판단한다.

    매수 신호: 두 지표 모두 하한 밴드 상향 돌파
    매도 신호: 두 지표 모두 상한 밴드 하향 돌파

    Returns: SignalResult (stock_code는 빈 문자열 — 호출자가 채워야 함),
             데이터 부족 시 None
    """
    if not prices_newest_first:
        return None

    curr_stoch, prev_stoch = calculate_stochastics_slow(prices_newest_first)
    curr_disp, prev_disp = calculate_disparity(prices_newest_first)

    if any(v is None for v in [curr_stoch, prev_stoch, curr_disp, prev_disp]):
        return None

    current_price = prices_newest_first[0].close

    # 매수: 두 지표 모두 하한 밴드 상향 돌파
    buy = (
        prev_stoch < STOCH_LOWER and curr_stoch >= STOCH_LOWER
        and prev_disp < DISP_LOWER and curr_disp >= DISP_LOWER
    )
    # 매도: 두 지표 모두 상한 밴드 하향 돌파
    sell = (
        prev_stoch > STOCH_UPPER and curr_stoch <= STOCH_UPPER
        and prev_disp > DISP_UPPER and curr_disp <= DISP_UPPER
    )

    if buy:
        signal = "buy"
    elif sell:
        signal = "sell"
    else:
        signal = "hold"

    return SignalResult(
        stock_code="",  # 호출자가 채워야 함
        signal=signal,
        stoch_k=curr_stoch,
        disparity=curr_disp,
        price=current_price,
    )


async def fetch_kospi200_codes() -> list[str]:
    """KRX 데이터포털에서 KOSPI 200 구성종목 코드 목록을 조회한다.

    KRX API: data.krx.co.kr POST (지수 구성종목 조회)
    실패 시 빈 리스트 반환 — 스캔을 중단하고 로그 경고 출력.
    """
    import httpx
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT00601",
        "indIdx": "1",
        "indIdx2": "028",   # KOSPI 200 인덱스 코드
        "trdDd": today,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020201",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("output", [])
        codes: list[str] = []
        for item in items:
            code = item.get("ISU_SRT_CD") or item.get("isu_srt_cd") or ""
            if code and len(code) == 6:
                codes.append(code.strip())

        logger.info("KOSPI 200 구성종목 %d개 조회 완료", len(codes))
        return codes
    except Exception as e:
        logger.warning("KOSPI 200 구성종목 조회 실패: %s", e)
        return []


async def fetch_excluded_stock_codes() -> set[str]:
    """KRX에서 거래정지/단기과열/투자경고/위험 종목 코드를 조회한다.

    조회 실패 시 빈 세트 반환 — 필터링 없이 전체 종목으로 진행.
    """
    import httpx

    excluded: set[str] = set()
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/",
    }

    # 투자경고/위험/주의 종목 조회
    try:
        payload = {
            "bld": "dbms/MDC/STAT/standard/MDCSTAT03901",
            "mktId": "STK",   # KOSPI 시장
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, data=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("output", []):
                    code = item.get("ISU_SRT_CD", "").strip()
                    if code:
                        excluded.add(code)
    except Exception as e:
        logger.debug("투자경고 종목 조회 실패 (비필수): %s", e)

    logger.info("제외 종목 %d개 (거래정지/경고/과열)", len(excluded))
    return excluded


async def run_daily_signal_scan(db: Session) -> dict:
    """KOSPI 200 전종목 일별 신호 스캔을 실행한다.

    1. KOSPI 200 구성종목 조회
    2. 제외 종목 필터링
    3. 병렬로 가격 이력 조회 및 신호 계산 (세마포어 10개 제한)
    4. buy/sell 신호 DB 저장 (당일 중복 제외)

    Returns: {"scanned": int, "buy_signals": int, "sell_signals": int}
    """
    # @MX:ANCHOR: 일별 신호 스캔 진입점 — 스케줄러와 수동 트리거 모두 이 함수 호출
    # @MX:REASON: scheduler._run_ks200_daily_scan, router.trigger_scan 2개 컴포넌트에서 호출
    # @MX:SPEC: SPEC-KS200-001
    from datetime import datetime, timezone

    from app.models.ks200_trading import KS200Signal
    from app.models.stock import Stock
    from app.services.naver_finance import fetch_stock_price_history

    # 1. KOSPI 200 구성종목 조회
    codes = await fetch_kospi200_codes()
    if not codes:
        logger.warning("KOSPI 200 구성종목 조회 실패 — 신호 스캔 중단")
        return {"scanned": 0, "buy_signals": 0, "sell_signals": 0}

    # 2. 제외 종목 필터링
    excluded = await fetch_excluded_stock_codes()
    valid_codes = [c for c in codes if c not in excluded]
    logger.info(
        "신호 스캔 대상: %d종목 (전체 %d, 제외 %d)",
        len(valid_codes),
        len(codes),
        len(excluded),
    )

    # 3. 종목코드 → stock_id 매핑
    stocks = db.query(Stock).filter(Stock.stock_code.in_(valid_codes)).all()
    code_to_id: dict[str, int] = {s.stock_code.strip(): s.id for s in stocks}

    # 4. 병렬 가격 이력 조회 (세마포어로 동시 요청 10개 제한)
    semaphore = asyncio.Semaphore(10)

    async def _fetch_and_check(code: str) -> SignalResult | None:
        async with semaphore:
            try:
                # pages=3: 약 30거래일 — STO1(12)+STO2(5)-1+1=17봉 충족
                prices = await fetch_stock_price_history(code, pages=3)
                if not prices:
                    return None
                result = check_signal(prices)
                if result is not None:
                    result.stock_code = code
                    result.price = prices[0].close  # 최신 종가
                return result
            except Exception as e:
                logger.debug("신호 계산 실패 (%s): %s", code, e)
                return None

    results = await asyncio.gather(
        *[_fetch_and_check(code) for code in valid_codes],
        return_exceptions=True,
    )

    # 5. 신호 DB 저장
    buy_count = sell_count = 0
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    for result in results:
        if isinstance(result, Exception) or result is None:
            continue
        if result.signal == "hold":
            continue

        # 당일 동일 종목 동일 신호 중복 방지
        existing = (
            db.query(KS200Signal)
            .filter(
                KS200Signal.stock_code == result.stock_code,
                KS200Signal.signal_type == result.signal,
                KS200Signal.signal_date >= today_start,
            )
            .first()
        )
        if existing:
            continue

        signal_obj = KS200Signal(
            stock_code=result.stock_code,
            stock_id=code_to_id.get(result.stock_code),
            signal_type=result.signal,
            stoch_k=result.stoch_k,
            disparity=result.disparity,
            price_at_signal=result.price,
            executed=False,
            signal_date=datetime.now(timezone.utc),
        )
        db.add(signal_obj)

        if result.signal == "buy":
            buy_count += 1
        else:
            sell_count += 1

    db.commit()
    logger.info(
        "신호 스캔 완료: 매수=%d, 매도=%d (스캔=%d)",
        buy_count,
        sell_count,
        len(valid_codes),
    )
    return {
        "scanned": len(valid_codes),
        "buy_signals": buy_count,
        "sell_signals": sell_count,
    }
