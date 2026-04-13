"""KRX 공매도 잔고 크롤러 — pykrx 방식.

## 데이터 취득 방식

pykrx 라이브러리로 data.krx.co.kr에서 공매도 잔고를 수집한다.
JSESSIONID 쿠키를 pykrx 내부 requests.post에 monkey-patch로 주입한다.

시장별 1회 요청 (KOSPI + KOSDAQ = 하루 총 2회 요청).

## 인증 방식

- JSESSIONID: data.krx.co.kr 로그인 후 브라우저 쿠키에서 복사
- 환경변수: KRX_DATA_JSESSIONID
- OCI 서버 재시작 시 .env 파일이 유지되므로 JSESSIONID 갱신 불필요
- 세션 만료 조건:
  - 30분 비활성 → keepalive(20분 간격)로 방지
  - KRX 서버 정기 점검(주말/공휴일) → 월요일 아침 수집 실패 시 갱신 필요

## 세션 keepalive

APScheduler가 20분 간격으로 extendSession.cmd를 호출하여 세션을 유지한다.
서버가 running 상태인 동안은 수동 갱신 없이 평일 내내 유지된다.

업데이트 주기: 매일 18:30 KST (KRX 데이터 공시 후)
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.krx_short_selling import KrxShortSelling
from app.models.stock import Stock

logger = logging.getLogger(__name__)

_KRX_DATA_BASE = "https://data.krx.co.kr"

# pykrx는 동기 라이브러리 → ThreadPoolExecutor에서 실행
# max_workers=1: monkey-patch가 thread-safe하지 않으므로 단일 스레드로 직렬화
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pykrx-krx")


def _get_prev_business_day(target: date | None = None) -> str:
    """전 영업일을 YYYYMMDD 문자열로 반환.

    월요일이면 3일 전(금요일), 일요일이면 2일 전, 그 외는 1일 전.
    """
    d = target or datetime.now(timezone.utc).date()
    delta = {0: 3, 6: 2}.get(d.weekday(), 1)
    prev = d - timedelta(days=delta)
    return prev.strftime("%Y%m%d")


def _find_col(df_columns: list[str], keywords: list[str]) -> str | None:
    """DataFrame 컬럼 목록에서 키워드를 포함하는 첫 컬럼명을 반환한다.

    pykrx 버전마다 컬럼명이 다를 수 있어 유연하게 처리한다.
    """
    for col in df_columns:
        clean = col.replace(" ", "").replace("(", "").replace(")", "")
        for kw in keywords:
            if kw in clean:
                return col
    return None


def _safe_int(val) -> int | None:
    """값을 int로 변환한다. 실패 시 None 반환."""
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _safe_float(val) -> float | None:
    """값을 float으로 변환한다. 실패 시 None 반환."""
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _fetch_shorting_balance_sync(date_str: str, market: str, jsessionid: str):
    """pykrx로 공매도 잔고 DataFrame을 조회한다 (동기).

    pykrx 내부 requests.post에 JSESSIONID 쿠키를 monkey-patch로 주입한 뒤,
    조회 완료 후 원래 함수로 복구한다.

    # @MX:WARN: monkey-patch는 thread-safe하지 않음
    # @MX:REASON: _executor가 max_workers=1이므로 동시 호출 없음. 호출 전후 orig 복구.

    Args:
        date_str: 조회 기준일 (YYYYMMDD)
        market: 시장 구분 ("KOSPI" 또는 "KOSDAQ")
        jsessionid: data.krx.co.kr 세션 쿠키

    Returns:
        공매도 잔고 DataFrame (티커 인덱스), 실패 시 None
    """
    try:
        from pykrx.website.comm import webio as krx_webio
        from pykrx import stock as krx_stock
    except ImportError:
        logger.error(
            "pykrx 미설치. `pip install pykrx` 후 재시작하세요."
        )
        return None

    orig_post = krx_webio.requests.post

    def _patched_post(url, **kwargs):
        if "krx.co.kr" in str(url):
            cookies = dict(kwargs.get("cookies") or {})
            cookies["JSESSIONID"] = jsessionid
            kwargs["cookies"] = cookies
        return orig_post(url, **kwargs)

    krx_webio.requests.post = _patched_post
    try:
        df = krx_stock.get_shorting_balance_by_ticker(date_str, market)
        return df
    except Exception as e:
        logger.warning(
            f"pykrx 공매도 잔고 조회 오류 ({market}, {date_str}): {e}"
        )
        return None
    finally:
        # monkey-patch 복구: 예외 발생 시에도 반드시 실행
        krx_webio.requests.post = orig_post


async def crawl_krx_short_selling(
    db: Session,
    trade_date: date | None = None,
) -> int:
    """KRX 공매도 잔고를 수집하여 DB에 저장한다.

    pykrx로 KOSPI + KOSDAQ 전종목 공매도 잔고를 수집한다 (하루 2회 요청).
    KRX_DATA_JSESSIONID 미설정 시 0을 반환한다.

    # @MX:ANCHOR: scheduler.py에서 매일 18:30 KST 호출
    # @MX:REASON: 공매도 잔고 수집의 단일 진입점 (스케줄러 + 수동 호출)

    Args:
        db: SQLAlchemy 세션
        trade_date: 조회 기준일 (None이면 전 영업일)

    Returns:
        신규 저장된 레코드 수
    """
    if not settings.KRX_DATA_JSESSIONID:
        logger.info(
            "KRX_DATA_JSESSIONID 미설정 — 공매도 잔고 수집 건너뜀. "
            "data.krx.co.kr 로그인 후 JSESSIONID를 .env에 설정하세요."
        )
        return 0

    trade_date_str = (
        trade_date.strftime("%Y%m%d") if trade_date else _get_prev_business_day()
    )

    # DB 종목코드 → stock_id 매핑
    stocks = db.query(Stock.id, Stock.code).all()
    code_to_id: dict[str, int] = {s.code: s.id for s in stocks}
    if not code_to_id:
        logger.warning("stocks 테이블이 비어있어 공매도 잔고를 저장할 수 없습니다.")
        return 0

    # 이미 수집된 stock_id 집합 (중복 방지)
    existing = {
        row[0]
        for row in db.query(KrxShortSelling.stock_id)
        .filter(KrxShortSelling.trade_date == trade_date_str)
        .all()
    }

    trade_date_obj = date(
        int(trade_date_str[:4]),
        int(trade_date_str[4:6]),
        int(trade_date_str[6:]),
    )

    loop = asyncio.get_running_loop()
    saved = 0

    for market in ("KOSPI", "KOSDAQ"):
        df = await loop.run_in_executor(
            _executor,
            _fetch_shorting_balance_sync,
            trade_date_str,
            market,
            settings.KRX_DATA_JSESSIONID,
        )

        if df is None or df.empty:
            logger.warning(
                f"KRX 공매도 잔고 없음 ({market}, {trade_date_str}). "
                "JSESSIONID 만료 또는 해당일 데이터 미공시."
            )
            continue

        logger.info(
            f"KRX 공매도 잔고 조회 완료 ({market}, {trade_date_str}): {len(df)}종목"
        )

        # pykrx 컬럼명 유연 탐색
        # 확인된 컬럼: 공매도잔고, 상장주식수, 공매도금액, 시가총액, 비중
        cols = list(df.columns)
        balance_col = _find_col(cols, ["공매도잔고", "잔고수량"])
        amount_col = _find_col(cols, ["공매도금액", "잔고금액", "공매도잔고금액"])
        ratio_col = _find_col(cols, ["비중", "잔고비율", "공매도잔고비율"])

        if not balance_col:
            logger.warning(
                f"pykrx DataFrame 컬럼 인식 실패 ({market}). "
                f"실제 컬럼: {cols}"
            )
            continue

        for ticker, row in df.iterrows():
            stock_id = code_to_id.get(str(ticker))
            if not stock_id or stock_id in existing:
                continue

            record = KrxShortSelling(
                stock_id=stock_id,
                trade_date=trade_date_obj,
                short_balance=_safe_int(row.get(balance_col)) if balance_col else None,
                short_balance_amount=_safe_int(row.get(amount_col)) if amount_col else None,
                short_ratio=_safe_float(row.get(ratio_col)) if ratio_col else None,
            )
            db.add(record)
            existing.add(stock_id)
            saved += 1

    if saved:
        db.commit()
        logger.info(f"KRX 공매도 잔고 저장 완료 ({trade_date_str}): {saved}건")
    else:
        logger.debug(f"KRX 공매도 잔고 신규 저장 없음 ({trade_date_str})")

    return saved


async def keepalive_krx_session() -> bool:
    """data.krx.co.kr 세션을 연장한다.

    JSESSIONID는 비활성 30분 후 만료된다.
    APScheduler가 20분 간격으로 이 함수를 호출하여 세션을 유지한다.

    OCI 서버 재시작 시 .env에서 JSESSIONID를 다시 읽으므로 자동 복구된다.
    KRX 서버 정기 점검(주말) 이후에는 새 JSESSIONID 갱신이 필요할 수 있다.

    Returns:
        세션 연장 성공 여부
    """
    if not settings.KRX_DATA_JSESSIONID:
        return False

    cookies = {"JSESSIONID": settings.KRX_DATA_JSESSIONID}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd",
        "X-Requested-With": "XMLHttpRequest",
    }
    extend_url = f"{_KRX_DATA_BASE}/contents/MDC/MAIN/main/extendSession.cmd"

    async with httpx.AsyncClient(
        timeout=15,
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    ) as client:
        try:
            resp = await client.post(extend_url)
            if resp.status_code == 200:
                logger.debug("KRX data.krx.co.kr 세션 연장 완료")
                return True
            logger.warning(
                f"KRX 세션 연장 실패 (HTTP {resp.status_code}). "
                "JSESSIONID 만료 가능성 — .env를 갱신하세요."
            )
            return False
        except Exception as e:
            logger.warning(f"KRX 세션 연장 오류: {e}")
            return False


async def fetch_krx_stock_data_for_date(
    trade_date: date | None = None,
) -> list[dict]:
    """KRX Open API REST에서 주식 일별 거래 데이터를 수집한다 (보조 용도).

    openapi.krx.co.kr (AUTH_KEY) 기반 REST API.
    공매도 잔고와 무관한 일별 거래량/거래대금 데이터.

    반환 필드: BAS_DD, ISU_CD, ISU_NM, MKT_NM, TDD_CLSPRC, ACC_TRDVOL, ACC_TRDVAL, MKTCAP

    Args:
        trade_date: 조회 기준일 (None이면 전 영업일)

    Returns:
        주식 일별 거래 딕셔너리 목록
    """
    if not settings.KRX_API_KEY:
        logger.warning("KRX_API_KEY 미설정.")
        return []

    trade_date_str = (
        trade_date.strftime("%Y%m%d") if trade_date else _get_prev_business_day()
    )
    _KRX_STK_TRD_URL = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
    headers = {
        "AUTH_KEY": settings.KRX_API_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                _KRX_STK_TRD_URL,
                headers=headers,
                json={"basDd": trade_date_str},
            )
            resp.raise_for_status()
            rows = resp.json().get("OutBlock_1", [])
            logger.debug(f"KRX 주식 거래 데이터 ({trade_date_str}): {len(rows)}건")
            return rows
        except httpx.HTTPStatusError as e:
            logger.warning(
                f"KRX REST API HTTP 오류 ({trade_date_str}): {e.response.status_code}"
            )
            return []
        except Exception as e:
            logger.warning(f"KRX REST API 오류 ({trade_date_str}): {e}")
            return []
