"""코스피 대폭락 조기 경보 서비스 (SPEC-AI-064).

선행지표(글로벌 선물·VIX·환율 + 장중 코스피 낙폭)를 읽어
폭락 위험도를 산출하고 텔레그램 경보를 발송하는 순수 모니터링 서비스.

경고: 이 파일은 어떤 매수/매도/포트폴리오 로직도 호출하지 않는다 (REQ-AI-064-009).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import yfinance as yf

from app.models.crash_risk_alert import CrashRiskAlert

logger = logging.getLogger(__name__)

# 위험도 순서 맵 (쿨다운 비교용)
_RISK_ORDER: dict[str, int] = {
    "SAFE": 0,
    "CAUTION": 1,
    "WARNING": 2,
    "DANGER": 3,
}

# @MX:NOTE: [AUTO] 기본 임계값 설정 (REQ-AI-064-001)
# @MX:SPEC: SPEC-AI-064
# 운영 중 조정 가능한 임계값을 모듈 상수로 노출.
# 스캔 진입점에서 config 인자로 주입되므로 단위 테스트에서 직접 오버라이드 가능.
DEFAULT_CONFIG: dict[str, float] = {
    "sp500_close_threshold": -1.5,      # S&P 500 전일 종가 % 변동 (그룹 D)
    "sp500_futures_threshold": -1.5,    # S&P 500 야간 선물 % 변동
    "vix_level_threshold": 25.0,        # VIX 수준 (절대값)
    "vix_change_threshold": 15.0,       # VIX 일일 변동 %
    "nasdaq_threshold": -1.8,           # Nasdaq 선물 % 변동
    "usdkrw_threshold": 1.0,            # USD/KRW 변동 % (원화 약세 = 양수)
    "kospi200_night_threshold": -1.5,   # 코스피200 야간 선물 괴리율
    "kospi_warning_threshold": -1.5,    # 장중 코스피 낙폭 → WARNING 기여
    "kospi_danger_threshold": -2.0,     # 장중 코스피 낙폭 → DANGER 강제
    "basis_threshold": -0.5,            # 코스피200 선물 베이시스 (선택, 그룹 C)
}


# ---------------------------------------------------------------------------
# 데이터 수집 함수
# ---------------------------------------------------------------------------


def fetch_us_close_signal() -> dict[str, float | None]:
    """그룹 D: S&P 500 실제 전일 종가 % 변동 (06:30 KST 스캔용).

    미국 장이 이미 마감된 시점에 전일 실제 종가를 조회한다.
    yfinance ^GSPC 일별 데이터로 최근 2거래일 종가 차이를 산출.

    Returns:
        {"sp500_close_change": float | None}
        실패(빈 DataFrame·예외) 시 None으로 graceful 처리 (REQ-AI-064-007).
    """
    try:
        data = yf.download(
            "^GSPC",
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if data is None or len(data) < 2:
            logger.warning("fetch_us_close_signal: ^GSPC 데이터 부족 (rows=%d)", len(data) if data is not None else 0)
            return {"sp500_close_change": None}

        # 최신 행 날짜 유효성 검사 — 오래된 캐시 데이터 방지 (R6)
        latest_date = data.index[-1]
        if hasattr(latest_date, "date"):
            latest_date = latest_date.date()
        today = datetime.now(timezone.utc).date()
        if (today - latest_date).days > 3:
            logger.warning(
                "fetch_us_close_signal: 최신 데이터가 %d일 전으로 stale — 스킵", (today - latest_date).days
            )
            return {"sp500_close_change": None}

        closes = data["Close"].dropna()
        if len(closes) < 2:
            logger.warning("fetch_us_close_signal: 유효 종가 2개 미만")
            return {"sp500_close_change": None}

        prev_close = float(closes.iloc[-2])
        last_close = float(closes.iloc[-1])
        if prev_close == 0:
            return {"sp500_close_change": None}

        change_pct = round((last_close - prev_close) / prev_close * 100, 4)
        return {"sp500_close_change": change_pct}

    except Exception as exc:
        logger.warning("fetch_us_close_signal 실패: %s", exc)
        return {"sp500_close_change": None}


# @MX:WARN: [AUTO] yfinance 외부 API 의존 — 레이트리밋·빈 DataFrame·심볼 변경 위험
# @MX:REASON: Yahoo Finance 서버 측 사정으로 간헐적 실패. 신호별 try/except로 graceful fallback 구현
# @MX:SPEC: SPEC-AI-064 REQ-AI-064-007
def fetch_global_premarket_signals() -> dict[str, float | None]:
    """그룹 A: 글로벌 장전 선행지표 수집 (08:30 KST 스캔용).

    yfinance로 S&P500 선물, VIX, Nasdaq 선물, USD/KRW 환율을 조회.
    심볼별 try/except — 부분 실패 시 해당 키를 None으로, 스캔 전체 중단 없음.

    Returns:
        {
            "sp500_futures": float | None,   # S&P500 야간 선물 % 변동
            "vix_level": float | None,       # VIX 현재 수준
            "vix_change_pct": float | None,  # VIX 일일 변동 %
            "nasdaq_futures": float | None,  # Nasdaq 야간 선물 % 변동
            "usdkrw_change_pct": float | None,  # USD/KRW 변동 %
        }
    """
    result: dict[str, float | None] = {
        "sp500_futures": None,
        "vix_level": None,
        "vix_change_pct": None,
        "nasdaq_futures": None,
        "usdkrw_change_pct": None,
    }

    symbols = {
        "sp500_futures": "ES=F",
        "nasdaq_futures": "NQ=F",
        "usdkrw": "KRW=X",
        "vix": "^VIX",
    }

    for key, symbol in symbols.items():
        try:
            data = yf.download(
                symbol,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if data is None or len(data) < 2:
                logger.warning("fetch_global_premarket_signals: %s 데이터 부족", symbol)
                continue

            closes = data["Close"].dropna()
            if len(closes) < 2:
                logger.warning("fetch_global_premarket_signals: %s 유효 종가 2개 미만", symbol)
                continue

            prev_val = float(closes.iloc[-2])
            last_val = float(closes.iloc[-1])
            if prev_val == 0:
                continue

            change_pct = round((last_val - prev_val) / prev_val * 100, 4)

            if key == "vix":
                result["vix_level"] = round(last_val, 4)
                result["vix_change_pct"] = change_pct
            elif key == "usdkrw":
                result["usdkrw_change_pct"] = change_pct
            else:
                result[key] = change_pct

        except Exception as exc:
            logger.warning("fetch_global_premarket_signals: %s 조회 실패 — %s", symbol, exc)

    return result


def fetch_kospi200_night_futures() -> float | None:
    """그룹 E: 코스피200 야간 선물 괴리율 조회 (선택, REQ-AI-064-015).

    Naver Finance에서 코스피200 야간 선물 체결가를 가져와
    전일 종가 대비 괴리율(%)을 산출한다.

    Naver 파싱 불안정 이력이 있으므로, 실패 시 None 반환 (graceful fallback).
    스캔에서 None이면 이 신호 기여 없이 그룹 A만으로 동작.

    Returns:
        float: 야간 선물 괴리율 % (예: -1.8), 또는 None
    """
    try:
        import httpx
        from bs4 import BeautifulSoup

        # 코스피200 선물 현재가 페이지 (야간 체결가 포함)
        url = "https://finance.naver.com/item/main.naver?code=101S6000"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": "https://finance.naver.com",
        }
        resp = httpx.get(url, headers=headers, timeout=10.0)
        resp.raise_for_status()

        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        # 현재가와 전일 종가 파싱
        # 네이버 금융 선물 페이지: .today_price 또는 .blind 텍스트로 현재가 추출
        current_el = soup.select_one("p.no_today em.no_up, p.no_today em.no_down, p.no_today em")
        prev_el = soup.select_one("table.tb_asset td")

        if not current_el:
            # 야간선물 데이터가 없을 수 있음 (장중 시간대)
            logger.debug("fetch_kospi200_night_futures: 현재가 파싱 실패 — 야간 세션 데이터 없음")
            return None

        current_text = current_el.get_text(strip=True).replace(",", "")
        try:
            current_price = float(current_text)
        except ValueError:
            logger.debug("fetch_kospi200_night_futures: 현재가 '%s' 변환 실패", current_text)
            return None

        if prev_el:
            prev_text = prev_el.get_text(strip=True).replace(",", "")
            try:
                prev_price = float(prev_text)
            except ValueError:
                prev_price = None
        else:
            prev_price = None

        if not prev_price or prev_price == 0:
            logger.debug("fetch_kospi200_night_futures: 전일 종가 파싱 실패")
            return None

        deviation_pct = round((current_price - prev_price) / prev_price * 100, 4)
        return deviation_pct

    except Exception as exc:
        logger.warning("fetch_kospi200_night_futures 실패: %s", exc)
        return None


async def check_intraday_kospi_drop() -> float | None:
    """그룹 B: 장중 코스피 낙폭 체크 (09:05 KST 스캔용).

    Naver Finance에서 코스피 지수 일별 시세를 가져와 최근 2거래일 종가로
    전일 대비 변동률을 산출한다.

    fetch_index_price_history("KOSPI") 기존 함수를 재사용 (REQ-AI-064-011 준수).

    Returns:
        float: 변동률 % (예: -2.1), 또는 None
    """
    try:
        from app.services.naver_finance import fetch_index_price_history

        rows = await fetch_index_price_history("KOSPI", pages=1)
        if not rows or len(rows) < 2:
            logger.warning("check_intraday_kospi_drop: KOSPI 데이터 부족 (rows=%d)", len(rows) if rows else 0)
            return None

        # fetch_index_price_history는 최신순 정렬: rows[0]=오늘, rows[1]=전일
        today_close = rows[0].get("close")
        prev_close = rows[1].get("close")

        if not today_close or not prev_close or prev_close == 0:
            logger.warning("check_intraday_kospi_drop: 유효 종가 없음")
            return None

        change_pct = round((today_close - prev_close) / prev_close * 100, 4)
        return change_pct

    except Exception as exc:
        logger.warning("check_intraday_kospi_drop 실패: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 위험도 산출 (순수 함수 — I/O 없음)
# ---------------------------------------------------------------------------

# @MX:NOTE: [AUTO] 위험도 분류 비즈니스 규칙 (SPEC-AI-064)
# @MX:SPEC: SPEC-AI-064
# 트리거 0개=SAFE, 1개=CAUTION, 2개+=WARNING, 3개+ 또는 코스피<=-2%=DANGER.
# 순수 함수이므로 모킹 없이 단위 테스트 가능.
def compute_crash_risk_score(
    signals: dict[str, float | None],
    kospi_change: float | None,
    basis: float | None,
    config: dict[str, float],
) -> tuple[str, list[dict]]:
    """폭락 위험도와 트리거된 신호 목록을 산출하는 순수 함수.

    Args:
        signals: 수집된 신호 딕셔너리 (None = 미수집)
        kospi_change: 장중 코스피 낙폭 % (None이면 적용 안 함)
        basis: 코스피200 선물 베이시스 % (None이면 적용 안 함, 선택)
        config: 임계값 설정 딕셔너리

    Returns:
        (risk_level, triggered_signals)
        risk_level: "SAFE" | "CAUTION" | "WARNING" | "DANGER"
        triggered_signals: [{"name": str, "value": float, "threshold": float}, ...]
    """
    triggered: list[dict] = []

    # --- S&P 500 전일 종가 변동 (그룹 D) ---
    sp500_close = signals.get("sp500_close_change")
    if sp500_close is not None and sp500_close <= config.get("sp500_close_threshold", -1.5):
        triggered.append({
            "name": "sp500_close",
            "value": sp500_close,
            "threshold": config.get("sp500_close_threshold", -1.5),
        })

    # --- S&P 500 야간 선물 (그룹 A) ---
    sp500_fut = signals.get("sp500_futures")
    if sp500_fut is not None and sp500_fut <= config.get("sp500_futures_threshold", -1.5):
        triggered.append({
            "name": "sp500_futures",
            "value": sp500_fut,
            "threshold": config.get("sp500_futures_threshold", -1.5),
        })

    # --- VIX 수준 ---
    vix_level = signals.get("vix_level")
    if vix_level is not None and vix_level >= config.get("vix_level_threshold", 25.0):
        triggered.append({
            "name": "vix_level",
            "value": vix_level,
            "threshold": config.get("vix_level_threshold", 25.0),
        })

    # --- VIX 일일 변동 ---
    vix_change = signals.get("vix_change_pct")
    if vix_change is not None and vix_change >= config.get("vix_change_threshold", 15.0):
        triggered.append({
            "name": "vix_change",
            "value": vix_change,
            "threshold": config.get("vix_change_threshold", 15.0),
        })

    # --- Nasdaq 선물 ---
    nasdaq_fut = signals.get("nasdaq_futures")
    if nasdaq_fut is not None and nasdaq_fut <= config.get("nasdaq_threshold", -1.8):
        triggered.append({
            "name": "nasdaq_futures",
            "value": nasdaq_fut,
            "threshold": config.get("nasdaq_threshold", -1.8),
        })

    # --- USD/KRW 환율 변동 (원화 약세) ---
    usdkrw = signals.get("usdkrw_change_pct")
    if usdkrw is not None and usdkrw >= config.get("usdkrw_threshold", 1.0):
        triggered.append({
            "name": "usdkrw",
            "value": usdkrw,
            "threshold": config.get("usdkrw_threshold", 1.0),
        })

    # --- 코스피200 야간 선물 괴리율 (그룹 E) ---
    kospi200_night = signals.get("kospi200_night_futures")
    if kospi200_night is not None and kospi200_night <= config.get("kospi200_night_threshold", -1.5):
        triggered.append({
            "name": "kospi200_night_futures",
            "value": kospi200_night,
            "threshold": config.get("kospi200_night_threshold", -1.5),
        })

    # --- 코스피200 선물 베이시스 (그룹 C, 선택) ---
    if basis is not None and basis <= config.get("basis_threshold", -0.5):
        triggered.append({
            "name": "kospi200_basis",
            "value": basis,
            "threshold": config.get("basis_threshold", -0.5),
        })

    # --- 장중 코스피 낙폭 (WARNING 기여) ---
    if kospi_change is not None and kospi_change <= config.get("kospi_warning_threshold", -1.5):
        triggered.append({
            "name": "kospi_intraday",
            "value": kospi_change,
            "threshold": config.get("kospi_warning_threshold", -1.5),
        })

    # 위험도 분류
    n = len(triggered)
    # DANGER 강제 조건: 코스피 낙폭 -2% 이하 또는 신호 3개 이상
    danger_by_kospi = (
        kospi_change is not None
        and kospi_change <= config.get("kospi_danger_threshold", -2.0)
    )
    if n >= 3 or danger_by_kospi:
        risk_level = "DANGER"
    elif n == 2:
        risk_level = "WARNING"
    elif n == 1:
        risk_level = "CAUTION"
    else:
        risk_level = "SAFE"

    return risk_level, triggered


# ---------------------------------------------------------------------------
# 발송 제어 (쿨다운)
# ---------------------------------------------------------------------------

# @MX:NOTE: [AUTO] 쿨다운 및 에스컬레이션 규칙 (REQ-AI-064-008)
# 동일 위험도 2시간 내 중복 발송 차단. 위험도 상승(escalation)은 쿨다운 무시.
# RISK_ORDER로 숫자 비교: 현재 > 직전 이면 에스컬레이션 → 발송 허용.
def _should_send_alert(db, risk_level: str) -> bool:
    """쿨다운 체크 — 직전 2시간 이내 동일 이상 위험도 발송 시 False 반환.

    Args:
        db: SQLAlchemy 세션
        risk_level: 현재 산출된 위험도

    Returns:
        True: 발송 허용 (신규 또는 에스컬레이션)
        False: 중복 차단 (쿨다운 유효)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    recent = (
        db.query(CrashRiskAlert)
        .filter(
            CrashRiskAlert.telegram_sent.is_(True),
            CrashRiskAlert.created_at >= cutoff,
        )
        .order_by(CrashRiskAlert.created_at.desc())
        .first()
    )

    if recent is None:
        return True  # 직전 발송 없음 → 발송 허용

    prev_order = _RISK_ORDER.get(recent.risk_level, 0)
    curr_order = _RISK_ORDER.get(risk_level, 0)

    if curr_order > prev_order:
        # 에스컬레이션 — 쿨다운 무시하고 발송
        return True

    # 동일 또는 하락 → 쿨다운 차단
    return False


async def _send_crash_alert(
    risk_level: str,
    triggered: list[dict],
    kospi_change: float | None,
    scan_type: str,
) -> bool:
    """텔레그램 경보 발송.

    Args:
        risk_level: 위험도 문자열
        triggered: 트리거된 신호 목록
        kospi_change: 장중 코스피 변동률 (None 가능)
        scan_type: 스캔 종류 (메시지 헤더 맥락 결정)

    Returns:
        True: 발송 성공, False: 미설정·발송 실패 (REQ-AI-064-010)
    """
    from app.services.telegram_service import send_telegram_message

    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not chat_id:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID 미설정 — 폭락 경보 발송 스킵")
        return False

    # 스캔 종류별 헤더 맥락
    if scan_type == "us_close":
        header = "⚠️ [미국 장마감 경보] 내일 코스피 하락 주의"
    elif scan_type == "intraday":
        header = "🚨 [장중 코스피 급락]"
    else:
        header = "⚠️ [코스피 폭락 경보]"

    risk_emoji = {"SAFE": "✅", "CAUTION": "🟡", "WARNING": "🟠", "DANGER": "🔴"}.get(risk_level, "❓")

    # 신호 목록 포맷
    signal_lines = []
    for sig in triggered:
        signal_lines.append(
            f"• {sig['name']}: {sig['value']:.2f}% (임계 {sig['threshold']:.1f}%)"
        )

    signals_text = "\n".join(signal_lines) if signal_lines else "• (없음)"

    # 코스피 장중 낙폭 라인
    kospi_line = ""
    if kospi_change is not None:
        kospi_line = f"\n코스피 현재: 전일 대비 {kospi_change:.2f}%"

    text = (
        f"<b>{header}</b>\n"
        f"위험도: <b>{risk_emoji} {risk_level}</b>\n"
        f"\n트리거된 신호:\n{signals_text}"
        f"{kospi_line}"
    )

    try:
        sent = await send_telegram_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return sent
    except Exception as exc:
        logger.error("폭락 경보 텔레그램 발송 예외: %s", exc)
        return False


# ---------------------------------------------------------------------------
# DB 저장
# ---------------------------------------------------------------------------

def _save_alert_record(
    db,
    scan_type: str,
    risk_level: str,
    triggered: list[dict],
    kospi_change: float | None,
    telegram_sent: bool,
) -> None:
    """폭락 위험도 스캔 결과를 crash_risk_alerts 테이블에 저장."""
    triggered_json = json.dumps(triggered, ensure_ascii=False) if triggered else None
    record = CrashRiskAlert(
        scan_type=scan_type,
        risk_level=risk_level,
        triggered_signals=triggered_json,
        kospi_change_pct=kospi_change,
        telegram_sent=telegram_sent,
    )
    db.add(record)
    db.commit()


# ---------------------------------------------------------------------------
# 거래일 판별 유틸
# ---------------------------------------------------------------------------


def _is_krx_trading_day() -> bool:
    """오늘이 한국 거래일(공휴일·주말 제외)인지 확인한다.

    holidays 패키지 미설치 시 fail-open(거래일로 간주) 처리.
    """
    today = datetime.now(tz=timezone(timedelta(hours=9))).date()
    if today.weekday() >= 5:  # 토요일=5, 일요일=6
        return False
    try:
        import holidays as holidays_lib

        return today not in holidays_lib.country_holidays("KR", years=today.year)
    except ImportError:
        logger.warning("holidays 패키지 미설치 — 공휴일 체크 스킵, 거래일로 간주")
        return True


# ---------------------------------------------------------------------------
# 스캔 진입점 (스케줄러 래퍼에서 호출)
# ---------------------------------------------------------------------------

# @MX:ANCHOR: [AUTO] run_us_close_crash_scan — 06:30 KST 스케줄러 진입점
# @MX:REASON: 스케줄러 래퍼 _run_us_close_crash_scan에서 호출 (fan_in >= 1, 확장 예상)
# @MX:SPEC: SPEC-AI-064 REQ-AI-064-014
async def run_us_close_crash_scan(db) -> None:
    """그룹 D: 미국 장마감 후 S&P 500 전일 종가 스캔 (06:30 KST).

    코스피 개장 약 2.5시간 전, 가장 선행적인 경보를 제공한다.
    """
    if not _is_krx_trading_day():
        logger.info("run_us_close_crash_scan: 오늘은 한국 공휴일 — 스킵")
        return
    logger.info("run_us_close_crash_scan 시작 (06:30 KST)")
    signals = fetch_us_close_signal()
    risk_level, triggered = compute_crash_risk_score(
        signals=signals,
        kospi_change=None,
        basis=None,
        config=DEFAULT_CONFIG,
    )
    logger.info("run_us_close_crash_scan 위험도=%s 트리거=%d개", risk_level, len(triggered))

    telegram_sent = False
    if risk_level in ("WARNING", "DANGER") and _should_send_alert(db, risk_level):
        telegram_sent = await _send_crash_alert(
            risk_level=risk_level,
            triggered=triggered,
            kospi_change=None,
            scan_type="us_close",
        )

    _save_alert_record(
        db=db,
        scan_type="us_close",
        risk_level=risk_level,
        triggered=triggered,
        kospi_change=None,
        telegram_sent=telegram_sent,
    )


# @MX:ANCHOR: [AUTO] run_premarket_crash_scan — 08:30 KST 스케줄러 진입점
# @MX:REASON: 스케줄러 래퍼 _run_premarket_crash_scan에서 호출 (fan_in >= 1)
# @MX:SPEC: SPEC-AI-064 REQ-AI-064-003, REQ-AI-064-015
async def run_premarket_crash_scan(db) -> None:
    """그룹 A + E: 장전 글로벌 선물·VIX·환율 + 코스피200 야간 선물 스캔 (08:30 KST)."""
    if not _is_krx_trading_day():
        logger.info("run_premarket_crash_scan: 오늘은 한국 공휴일 — 스킵")
        return
    logger.info("run_premarket_crash_scan 시작 (08:30 KST)")

    # 그룹 A: 글로벌 장전 신호
    signals = fetch_global_premarket_signals()

    # 그룹 E: 코스피200 야간 선물 (선택, 실패 시 신호 기여 없음)
    night_futures = fetch_kospi200_night_futures()
    if night_futures is not None:
        signals["kospi200_night_futures"] = night_futures

    risk_level, triggered = compute_crash_risk_score(
        signals=signals,
        kospi_change=None,
        basis=None,
        config=DEFAULT_CONFIG,
    )
    logger.info("run_premarket_crash_scan 위험도=%s 트리거=%d개", risk_level, len(triggered))

    telegram_sent = False
    if risk_level in ("WARNING", "DANGER") and _should_send_alert(db, risk_level):
        telegram_sent = await _send_crash_alert(
            risk_level=risk_level,
            triggered=triggered,
            kospi_change=None,
            scan_type="premarket",
        )

    _save_alert_record(
        db=db,
        scan_type="premarket",
        risk_level=risk_level,
        triggered=triggered,
        kospi_change=None,
        telegram_sent=telegram_sent,
    )


# @MX:ANCHOR: [AUTO] run_intraday_crash_check — 09:05 KST 스케줄러 진입점
# @MX:REASON: 스케줄러 래퍼 _run_intraday_crash_check에서 호출 (fan_in >= 1)
# @MX:SPEC: SPEC-AI-064 REQ-AI-064-004
async def run_intraday_crash_check(db) -> None:
    """그룹 B: 장중 코스피 낙폭 체크 (09:05 KST).

    코스피 낙폭이 -2% 이상이면 DANGER 긴급 경보를 발송한다.
    """
    if not _is_krx_trading_day():
        logger.info("run_intraday_crash_check: 오늘은 한국 공휴일 — 스킵")
        return
    logger.info("run_intraday_crash_check 시작 (09:05 KST)")

    kospi_change = await check_intraday_kospi_drop()
    risk_level, triggered = compute_crash_risk_score(
        signals={},
        kospi_change=kospi_change,
        basis=None,
        config=DEFAULT_CONFIG,
    )
    logger.info(
        "run_intraday_crash_check 코스피변동=%.2f%% 위험도=%s 트리거=%d개",
        kospi_change if kospi_change is not None else 0.0,
        risk_level,
        len(triggered),
    )

    telegram_sent = False
    if risk_level in ("WARNING", "DANGER") and _should_send_alert(db, risk_level):
        telegram_sent = await _send_crash_alert(
            risk_level=risk_level,
            triggered=triggered,
            kospi_change=kospi_change,
            scan_type="intraday",
        )

    _save_alert_record(
        db=db,
        scan_type="intraday",
        risk_level=risk_level,
        triggered=triggered,
        kospi_change=kospi_change,
        telegram_sent=telegram_sent,
    )
