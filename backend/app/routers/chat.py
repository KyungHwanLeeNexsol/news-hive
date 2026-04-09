"""AI 채팅 분석 API 라우터.

사용자가 종목에 대해 질문하면, 관련 컨텍스트(현재가, 뉴스, 기술지표 등)를
자동 수집하여 Gemini에 전달하고 분석 응답을 반환한다.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stock_code: str | None = None
    history: list[dict] | None = None  # 프론트엔드 localStorage 대화 이력


class ChatResponse(BaseModel):
    reply: str
    context_used: list[str]
    session_id: str
    ai_model: str | None = None


# ---------------------------------------------------------------------------
# 인메모리 세션 저장소
# 구조: {session_id: {"messages": [...], "last_access": float}}
# 최대 10 메시지, 30분 미사용 시 자동 만료
# ---------------------------------------------------------------------------
_sessions: dict[str, dict] = {}
_SESSION_MAX_MESSAGES = 10
_SESSION_EXPIRE_SECONDS = 30 * 60  # 30분


def _cleanup_sessions() -> None:
    """만료된 세션 정리."""
    now = time.time()
    expired = [
        sid for sid, data in _sessions.items()
        if now - data["last_access"] > _SESSION_EXPIRE_SECONDS
    ]
    for sid in expired:
        del _sessions[sid]


def _get_or_create_session(session_id: str | None) -> tuple[str, list[dict]]:
    """세션 조회 또는 새로 생성. (session_id, messages) 반환."""
    _cleanup_sessions()
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session["last_access"] = time.time()
        return session_id, session["messages"]

    new_id = session_id or str(uuid.uuid4())
    _sessions[new_id] = {"messages": [], "last_access": time.time()}
    return new_id, _sessions[new_id]["messages"]


def _add_message(session_id: str, role: str, content: str) -> None:
    """세션에 메시지 추가. 최대 개수 초과 시 오래된 메시지부터 제거."""
    if session_id not in _sessions:
        return
    messages = _sessions[session_id]["messages"]
    messages.append({"role": role, "content": content})
    if len(messages) > _SESSION_MAX_MESSAGES:
        _sessions[session_id]["messages"] = messages[-_SESSION_MAX_MESSAGES:]
    _sessions[session_id]["last_access"] = time.time()


# ---------------------------------------------------------------------------
# 종목 감지
# ---------------------------------------------------------------------------


def _detect_stock(message: str, stock_code: str | None, db: Session) -> tuple[int | None, str | None]:
    """메시지에서 종목을 감지한다. (stock_id, stock_name) 반환.

    1) 명시적 stock_code가 있으면 DB 직접 조회
    2) KeywordIndex로 메시지 내 종목명 매칭
    """
    from app.models.stock import Stock

    # 명시적 종목코드
    if stock_code:
        stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
        if stock:
            return stock.id, stock.name

    # KeywordIndex로 종목명 매칭
    from app.services.ai_classifier import get_or_build_index
    idx = get_or_build_index(db)

    # 종목명 직접 매칭 (긴 이름부터 매칭하여 부분 매칭 방지)
    for name in sorted(idx.stock_names.keys(), key=len, reverse=True):
        if name in message:
            stock_id, _ = idx.stock_names[name]
            return stock_id, name

    # 키워드 매칭
    message_lower = message.lower()
    for kw, pairs in idx.stock_keywords.items():
        if kw in message_lower and pairs:
            stock_id, _ = pairs[0]
            stock = db.query(Stock).filter(Stock.id == stock_id).first()
            if stock:
                return stock.id, stock.name

    return None, None


# ---------------------------------------------------------------------------
# 컨텍스트 수집
# ---------------------------------------------------------------------------


async def _gather_context(stock_id: int, stock_name: str, db: Session) -> tuple[str, list[str]]:
    """종목 관련 컨텍스트를 수집하여 (프롬프트 텍스트, 사용된 소스 목록)을 반환한다."""
    from app.models.stock import Stock
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation
    from app.models.fund_signal import FundSignal

    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        return "", []

    context_parts: list[str] = []
    sources_used: list[str] = []

    # 1) 현재가 (네이버 금융)
    try:
        from app.services.naver_finance import fetch_stock_fundamentals
        fundamentals = await fetch_stock_fundamentals(stock.stock_code)
        if fundamentals:
            context_parts.append(
                f"[현재 시세]\n"
                f"현재가: {fundamentals.current_price:,}원\n"
                f"전일비: {fundamentals.price_change:+,}원 ({fundamentals.change_rate:+.2f}%)\n"
                f"거래량: {fundamentals.volume:,}"
            )
            sources_used.append("naver_finance")
    except Exception as e:
        logger.warning(f"현재가 조회 실패: {e}")

    # 2) 최근 뉴스 (DB에서 최근 5건)
    try:
        recent_news = (
            db.query(NewsArticle)
            .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
            .filter(NewsStockRelation.stock_id == stock_id)
            .order_by(NewsArticle.published_at.desc().nullslast())
            .limit(5)
            .all()
        )
        if recent_news:
            news_lines = []
            for n in recent_news:
                date_str = n.published_at.strftime("%m/%d") if n.published_at else "N/A"
                sentiment_str = f" [{n.sentiment}]" if n.sentiment else ""
                news_lines.append(f"- {date_str}{sentiment_str} {n.title}")
            context_parts.append("[최근 뉴스]\n" + "\n".join(news_lines))
            sources_used.append("recent_news")
    except Exception as e:
        logger.warning(f"뉴스 조회 실패: {e}")

    # 3) 기술적 지표
    try:
        from app.services.naver_finance import fetch_stock_price_history
        from app.services.technical_indicators import calculate_technical_indicators, format_technical_for_prompt

        prices = await fetch_stock_price_history(stock.stock_code, pages=3)
        if prices:
            ta = calculate_technical_indicators(prices)
            current_price = prices[0].close if prices else None
            ta_text = format_technical_for_prompt(ta, current_price)
            if ta_text:
                context_parts.append(f"[기술적 지표]\n{ta_text}")
                sources_used.append("technical_indicators")
    except Exception as e:
        logger.warning(f"기술지표 조회 실패: {e}")

    # 4) 재무 데이터
    try:
        from app.services.financial_scraper import fetch_stock_financials
        financials = await fetch_stock_financials(stock.stock_code)
        annual = financials.get("annual", [])
        if annual:
            latest = annual[-1]  # 가장 최근 연간 데이터
            parts = [f"기간: {latest.period}"]
            if latest.revenue:
                parts.append(f"매출: {latest.revenue:,.0f}억")
            if latest.operating_profit:
                parts.append(f"영업이익: {latest.operating_profit:,.0f}억")
            if latest.roe:
                parts.append(f"ROE: {latest.roe:.1f}%")
            if latest.eps:
                parts.append(f"EPS: {latest.eps:,.0f}원")
            context_parts.append("[재무 데이터]\n" + " | ".join(parts))
            sources_used.append("financial_data")
    except Exception as e:
        logger.warning(f"재무 데이터 조회 실패: {e}")

    # 5) 섹터 정보
    if stock.sector:
        context_parts.append(f"[섹터] {stock.sector.name}")
        sources_used.append("sector_info")

    # 6) 최근 AI 시그널 (있으면)
    try:
        latest_signal = (
            db.query(FundSignal)
            .filter(FundSignal.stock_id == stock_id)
            .order_by(FundSignal.created_at.desc())
            .first()
        )
        if latest_signal:
            sig_date = latest_signal.created_at.strftime("%m/%d") if latest_signal.created_at else "N/A"
            context_parts.append(
                f"[최근 AI 시그널] {sig_date}\n"
                f"판단: {latest_signal.signal.upper()} (신뢰도: {latest_signal.confidence:.0%})\n"
                f"근거: {latest_signal.reasoning[:200]}"
            )
            sources_used.append("fund_signal")
    except Exception as e:
        logger.warning(f"시그널 조회 실패: {e}")

    full_context = "\n\n".join(context_parts) if context_parts else "관련 데이터 없음"
    return full_context, sources_used


async def _gather_market_context(db: Session) -> tuple[str, list[str]]:
    """종목 미특정 시장 전체 질문용 컨텍스트를 수집한다.

    오늘의 AI 브리핑 + 최근 뉴스 헤드라인을 주입하여
    AI가 현재 시장 상황 기반으로 답변하도록 한다.
    """
    from datetime import date as date_type
    from app.models.daily_briefing import DailyBriefing
    from app.models.news import NewsArticle

    context_parts: list[str] = []
    sources_used: list[str] = []

    # 1) 오늘의 AI 브리핑 (있으면)
    try:
        today = date_type.today()
        briefing = db.query(DailyBriefing).filter(DailyBriefing.briefing_date == today).first()
        if not briefing:
            # 가장 최근 브리핑 사용 (최대 2일 이내)
            from datetime import timedelta
            briefing = (
                db.query(DailyBriefing)
                .filter(DailyBriefing.briefing_date >= today - timedelta(days=2))
                .order_by(DailyBriefing.briefing_date.desc())
                .first()
            )
        if briefing:
            parts = [f"[AI 브리핑 — {briefing.briefing_date}]"]
            if briefing.market_overview:
                parts.append(f"시장 전망: {briefing.market_overview[:600]}")
            if briefing.risk_assessment:
                parts.append(f"리스크 평가: {briefing.risk_assessment[:300]}")
            if briefing.strategy:
                parts.append(f"전략: {briefing.strategy[:300]}")
            context_parts.append("\n".join(parts))
            sources_used.append("daily_briefing")
    except Exception as e:
        logger.warning(f"브리핑 컨텍스트 조회 실패: {e}")

    # 2) 최근 뉴스 헤드라인 (12시간 이내, 최대 10건)
    try:
        from datetime import datetime as dt, timezone as tz, timedelta
        cutoff = dt.now(tz.utc) - timedelta(hours=12)
        recent_news = (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(10)
            .all()
        )
        if recent_news:
            lines = ["[최근 뉴스 헤드라인 — 최근 12시간]"]
            for n in recent_news:
                sentiment_label = {"positive": "긍정", "negative": "부정"}.get(
                    getattr(n, "sentiment", ""), "중립"
                )
                pub = n.published_at.strftime("%H:%M") if n.published_at else ""
                lines.append(f"• [{sentiment_label}] {n.title} ({pub})")
            context_parts.append("\n".join(lines))
            sources_used.append("recent_news")
    except Exception as e:
        logger.warning(f"최근 뉴스 컨텍스트 조회 실패: {e}")

    full_context = "\n\n".join(context_parts) if context_parts else ""
    return full_context, sources_used


# ---------------------------------------------------------------------------
# 프롬프트 구성
# ---------------------------------------------------------------------------


def _build_prompt(
    message: str,
    context: str,
    stock_name: str | None,
    history: list[dict],
) -> str:
    """Gemini 호출용 프롬프트를 구성한다."""
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y년 %m월 %d일")
    has_data = bool(context and context != "관련 데이터 없음")

    system = (
        f"오늘 날짜: {today} (KST)\n\n"
        "## 역할\n"
        "당신은 운용자산 5천억 규모 헤지펀드의 수석 퀀트 트레이더입니다.\n"
        "코스피·코스닥 수급 분석, 모멘텀 팩터, 기술적 패턴, 섹터 로테이션을 통합하여\n"
        "실행 가능한 매매 판단을 내립니다. 오늘 날짜 기준으로 모든 시간 표현을 사용합니다.\n\n"
        "## 제공 데이터 구조\n"
        "종목이 특정되면 [분석 대상 컨텍스트]에 다음 실시간 데이터가 포함됩니다:\n"
        "• [현재 시세]: 현재가, 전일비, 등락률, 거래량\n"
        "• [최근 뉴스]: 날짜·감성 레이블(긍정/부정/중립)·헤드라인\n"
        "• [기술적 지표]: RSI, MACD, 볼린저밴드, 5·20·60일 이동평균, 거래량 추세\n"
        "• [재무 데이터]: 매출, 영업이익, ROE, EPS\n"
        "• [최근 AI 시그널]: 이전 AI 매매 판단 및 신뢰도\n\n"
        "## 데이터 활용 의무\n"
        "컨텍스트가 제공된 경우 — 반드시 수치를 직접 인용하고 해석한다:\n"
        "  예) 'RSI 74 → 단기 과매수 구간', '5일선이 20일선 돌파 → 단기 골든크로스'\n"
        "  예) '뉴스 3건 부정 → 투자심리 악화, 수급 이탈 가능성'\n"
        "  기술적 지지/저항선과 현재가의 위치, 뉴스 감성과 가격 흐름의 일치·괴리를 분석한다.\n"
        "컨텍스트가 없는 경우 — 거시 지표(금리·달러·유가), 섹터 로테이션, 역사적 패턴으로 완성한다.\n\n"
        "## 종목 질문 답변 구조\n"
        "① 핵심 판단: 매수 / 매도 / 관망 + 확신도(1~10)\n"
        "② 기술적 근거: 지표 수치 직접 인용\n"
        "③ 수급·뉴스 팩터: 감성 흐름과 수급 추정\n"
        "④ 리스크: 주요 하방 시나리오\n"
        "⑤ 액션 플랜: 진입가 / 목표가 / 손절가\n\n"
        "## 시장·거시 질문 답변 구조\n"
        "① 핵심 판단: 방향성과 예상 시기\n"
        "② 근거: 기술적 레벨 + 거시 지표 + 섹터 흐름\n"
        "③ 시나리오: 반등 조건 vs 추가 하락 조건\n\n"
        "## 절대 금지\n"
        "• '데이터가 없어서', '확인이 어렵습니다', '개인 판단에 따라' → 사용 금지\n"
        "• '~할 수 있습니다', '~인 것 같습니다', '~로 보입니다' → 단정적으로 표현\n"
        "• 면책 조항, 투자 위험 경고 문구 → 포함 금지\n"
        "• 오늘 날짜 이전을 '미래'로 표현 → 금지"
    )

    parts = [system]

    if has_data:
        stock_label = f" ({stock_name})" if stock_name else " (시장 전체)"
        parts.append(f"\n[분석 대상{stock_label} 컨텍스트]\n{context}")

    # 이전 대화 이력 (최근 4건만)
    if history:
        recent = history[-4:]
        conv_lines = []
        for msg in recent:
            role_label = "사용자" if msg["role"] == "user" else "AI"
            conv_lines.append(f"{role_label}: {msg['content'][:300]}")
        parts.append("\n[이전 대화]\n" + "\n".join(conv_lines))

    parts.append(f"\n[사용자 질문]\n{message}")

    # 데이터 유무에 따라 trailing instruction 분기
    if has_data:
        parts.append(
            "\n컨텍스트의 수치를 직접 인용하며 매매 판단(매수/매도/관망, 확신도)을 첫 줄에 제시하고, "
            "기술적·수급·펀더멘털 분석 순으로 근거를 구체적으로 제시하세요. "
            "액션 플랜(진입가/목표가/손절가)으로 마무리합니다."
        )
    else:
        parts.append(
            "\n거시 지표와 시장 구조 분석을 기반으로 핵심 판단을 첫 줄에 제시하고, "
            "구체적인 가격 레벨·예상 시기·핵심 조건을 포함하여 설명하세요."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API 엔드포인트
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    """AI 채팅 분석 엔드포인트.

    사용자 메시지에서 종목을 감지하고, 관련 데이터를 수집하여
    Gemini에게 분석을 요청한 후 응답을 반환한다.
    """
    # 무료 키 전용 — 유료 키(key 0)는 키워드 알림·생성 전용으로 예약됨
    from app.services.ai_client import ask_ai_with_openai_fallback as ask_ai_with_model

    # 세션 관리
    session_id, history = _get_or_create_session(req.session_id)

    # 세션이 비어있고 프론트엔드에서 이전 대화 이력을 전달한 경우 복원
    if not history and req.history:
        valid_roles = {"user", "assistant"}
        for msg in req.history[-_SESSION_MAX_MESSAGES:]:
            if isinstance(msg, dict) and msg.get("role") in valid_roles and isinstance(msg.get("content"), str):
                history.append({"role": msg["role"], "content": msg["content"][:1000]})
        _sessions[session_id]["last_access"] = time.time()

    # 종목 감지
    stock_id, stock_name = _detect_stock(req.message, req.stock_code, db)

    # 컨텍스트 수집
    context_text = ""
    sources_used: list[str] = []
    if stock_id and stock_name:
        context_text, sources_used = await _gather_context(stock_id, stock_name, db)
    else:
        # 종목 미특정 시장 전체 질문 → 브리핑·최근뉴스 주입
        context_text, sources_used = await _gather_market_context(db)

    # 프롬프트 구성
    prompt = _build_prompt(req.message, context_text, stock_name, history)

    # AI 호출
    ai_model_used: str | None = None
    try:
        reply, ai_model_used = await ask_ai_with_model(prompt, free_only=True)
        if not reply:
            reply = "죄송합니다. AI 응답을 생성하지 못했습니다. 잠시 후 다시 시도해주세요."
    except Exception as e:
        logger.error(f"AI 채팅 호출 실패: {e}")
        reply = f"AI 서비스 오류가 발생했습니다: {type(e).__name__}"

    # 세션에 대화 기록 추가
    _add_message(session_id, "user", req.message)
    _add_message(session_id, "assistant", reply)

    return ChatResponse(
        reply=reply,
        context_used=sources_used,
        session_id=session_id,
        ai_model=ai_model_used,
    )
