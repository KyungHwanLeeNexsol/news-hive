"""매크로 리스크 감지 서비스.

뉴스 크롤링 후 리스크 키워드 빈도를 분석하여 임계치 초과 시 MacroAlert를 생성한다.
REQ-AI-010: 키워드 매칭 후 AI NLP 분류로 거짓 양성을 제거하고 심각도를 판단한다.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.macro_alert import MacroAlert
from app.models.news import NewsArticle

logger = logging.getLogger(__name__)

# 리스크 키워드 사전: (키워드, 레벨 기본값)
# 같은 키워드가 여러 표현으로 나올 수 있으므로 그룹핑
RISK_KEYWORD_GROUPS: list[dict] = [
    {
        "name": "전쟁",
        "keywords": ["전쟁", "교전", "포격", "미사일", "공습", "침공", "선전포고", "군사충돌", "군사적 긴장"],
    },
    {
        "name": "계엄",
        "keywords": ["계엄", "비상계엄", "계엄령"],
    },
    {
        "name": "금리인상",
        "keywords": ["금리인상", "금리 인상", "기준금리 인상", "긴축", "매파"],
    },
    {
        "name": "금리인하",
        "keywords": ["금리인하", "금리 인하", "기준금리 인하", "비둘기파"],
    },
    {
        "name": "제재",
        "keywords": ["경제제재", "제재", "수출규제", "수출 규제", "무역전쟁", "무역 전쟁", "관세"],
    },
    {
        "name": "디폴트",
        "keywords": ["디폴트", "채무불이행", "국가부도", "국가 부도", "소버린 디폴트"],
    },
    {
        "name": "폭락",
        "keywords": ["폭락", "증시 급락", "코스피 급락", "코스닥 급락", "지수 급락",
                      "서킷브레이커", "사이드카", "패닉셀", "투매", "블랙먼데이"],
    },
    {
        "name": "지정학",
        "keywords": ["북한 도발", "대만 해협", "중동 긴장", "핵실험", "탄도미사일"],
    },
    {
        "name": "금융위기",
        "keywords": ["금융위기", "뱅크런", "유동성 위기", "시스템 리스크", "신용경색"],
    },
    {
        "name": "환율급등",
        "keywords": ["환율 급등", "원달러 급등", "원화 약세", "달러 강세"],
    },
]

# 긍정적 맥락 키워드 — 이 단어가 포함되면 리스크 뉴스에서 제외
POSITIVE_CONTEXT = [
    "반등", "회복", "안정", "진정", "완화", "해소", "반발 매수", "저가 매수",
    "상승 전환", "낙폭 축소", "우려 해소", "협상 타결", "휴전", "종전",
]

# 개별 기업/비금융 뉴스 제외 패턴 — 시장 전체 리스크가 아닌 개별 이슈
EXCLUDE_CONTEXT = [
    "매장 폐쇄", "폐업", "점포", "체인", "프랜차이즈", "레스토랑", "가구",
    "Chapter 11", "챕터 11", "개인파산", "개인 파산",
    "소송", "재판", "판결", "혐의",
    "게임", "드라마", "영화", "예능",
]

# 설정에서 매크로 리스크 임계치 로드
from app.config import settings

WINDOW_HOURS = settings.MACRO_RISK_WINDOW_HOURS          # 리스크 뉴스 집계 윈도우 (시간)
WARNING_THRESHOLD = settings.MACRO_RISK_WARNING_THRESHOLD  # warning 알림 임계치 (기사 수)
CRITICAL_THRESHOLD = settings.MACRO_RISK_CRITICAL_THRESHOLD  # critical 알림 임계치 (기사 수)
COOLDOWN_HOURS = settings.MACRO_RISK_COOLDOWN_HOURS        # 알림 중복 방지 간격 (시간)


async def _classify_macro_severity(
    articles: list[NewsArticle], group_name: str
) -> dict:
    """AI 기반 매크로 리스크 문맥 분류.

    키워드 매칭된 기사들의 실제 리스크 심각도를 AI로 판단한다.
    거짓 양성(키워드는 있지만 시장 리스크와 무관한 기사)을 걸러낸다.

    Args:
        articles: 키워드 매칭된 뉴스 기사 리스트
        group_name: 리스크 그룹명 (전쟁, 금리인상 등)

    Returns:
        {"severity": str, "context_summary": str, "is_false_positive": bool}
    """
    from app.services.ai_client import ask_ai

    # 기사 제목 + 요약 취합 (최대 5개)
    article_texts = []
    for a in articles[:5]:
        title = a.title or ""
        summary = (a.summary or "")[:100]
        article_texts.append(f"- {title} ({summary})")

    articles_text = "\n".join(article_texts)

    prompt = (
        f'다음 뉴스 기사들이 "{group_name}" 관련 매크로 리스크인지 분석해주세요.\n\n'
        f"기사 목록:\n{articles_text}\n\n"
        "다음 JSON 형식으로만 응답해주세요:\n"
        "{\n"
        '    "severity": "none/low/medium/high/critical 중 하나",\n'
        '    "context_summary": "2-3문장으로 실제 시장 영향 분석",\n'
        '    "is_false_positive": true/false\n'
        "}\n\n"
        "판단 기준:\n"
        '- "none": 해당 키워드가 있지만 시장 리스크와 무관 (거짓 양성)\n'
        '- "low": 뉴스로 보도되었으나 시장 영향 미미\n'
        '- "medium": 특정 섹터에 영향을 줄 수 있는 수준\n'
        '- "high": 시장 전체에 단기적 영향 예상\n'
        '- "critical": 즉각적이고 광범위한 시장 충격 예상\n\n'
        "반드시 JSON만 출력하세요."
    )

    fallback = {"severity": "medium", "context_summary": "", "is_false_positive": False}

    try:
        response = await ask_ai(prompt, max_retries=2)
        if not response:
            return fallback

        # JSON 파싱 — 코드 블록 래핑 제거
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]

        result = json.loads(cleaned)

        valid_severities = {"none", "low", "medium", "high", "critical"}
        if result.get("severity") not in valid_severities:
            result["severity"] = "medium"

        return result
    except Exception as e:
        logger.warning("매크로 NLP 분류 실패: %s", e)
        return fallback


# @MX:NOTE: [AUTO] REQ-AI-010 매크로 NLP 분류 적용 — async 전환
async def detect_macro_risks(db: Session) -> list[MacroAlert]:
    """최근 크롤링된 뉴스에서 매크로 리스크 키워드를 감지하고 알림을 생성한다.

    REQ-AI-010: 키워드 매칭 후 AI NLP 분류로 거짓 양성 제거 및 심각도 판정.
    """
    window_start = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)

    # 최근 윈도우 내 뉴스 가져오기
    recent_articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.collected_at >= window_start)
        .all()
    )

    if not recent_articles:
        return []

    created_alerts: list[MacroAlert] = []

    for group in RISK_KEYWORD_GROUPS:
        group_name = group["name"]
        keywords = group["keywords"]

        # 해당 그룹 키워드가 포함된 기사 찾기 (긍정적 맥락 제외)
        matched_articles = []
        for article in recent_articles:
            title = article.title or ""
            summary = article.summary or ""
            text = f"{title} {summary}"
            if any(kw in text for kw in keywords):
                # 긍정적 맥락이면 리스크 뉴스에서 제외
                if any(pos in text for pos in POSITIVE_CONTEXT):
                    continue
                # 개별 기업/비금융 뉴스 제외
                if any(exc in text for exc in EXCLUDE_CONTEXT):
                    continue
                matched_articles.append(article)

        count = len(matched_articles)
        if count < WARNING_THRESHOLD:
            continue

        # REQ-AI-010: AI NLP 분류로 거짓 양성 필터링 및 심각도 판정
        nlp_result = await _classify_macro_severity(matched_articles, group_name)

        if nlp_result.get("is_false_positive"):
            logger.info("NLP 거짓 양성 판정 — 스킵: %s (%d건)", group_name, count)
            continue

        # AI 심각도를 alert level로 매핑
        ai_severity = nlp_result.get("severity", "medium")
        if ai_severity in ("high", "critical"):
            level = "critical"
        elif ai_severity in ("medium",):
            level = "warning"
        else:
            # "none" 또는 "low" — 키워드 임계치를 넘었지만 AI가 낮게 판단
            logger.info(
                "NLP 낮은 심각도(%s) — 스킵: %s (%d건)", ai_severity, group_name, count
            )
            continue

        # 쿨다운 체크: 같은 키워드로 최근 알림이 있으면 스킵
        cooldown_start = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
        existing = (
            db.query(MacroAlert)
            .filter(
                MacroAlert.keyword == group_name,
                MacroAlert.created_at >= cooldown_start,
            )
            .first()
        )
        if existing:
            # 기존 알림의 레벨이 낮으면 업그레이드
            if existing.level == "warning" and level == "critical":
                existing.level = "critical"
                existing.article_count = count
                context_summary = nlp_result.get("context_summary", "")
                existing.description = _build_description(matched_articles, context_summary)
                db.commit()
                logger.info("Macro alert upgraded to critical: %s (%d articles)", group_name, count)
            continue

        # 알림 생성
        alert_title = _build_title(group_name, count, level)
        context_summary = nlp_result.get("context_summary", "")
        description = _build_description(matched_articles, context_summary)

        alert = MacroAlert(
            level=level,
            keyword=group_name,
            title=alert_title,
            description=description,
            article_count=count,
            is_active=True,
        )
        db.add(alert)
        created_alerts.append(alert)
        logger.info("Macro alert created: [%s] %s (%d articles)", level, group_name, count)

    if created_alerts:
        db.commit()

    return created_alerts


def _build_title(keyword: str, count: int, level: str) -> str:
    """알림 제목 생성."""
    prefix = "긴급" if level == "critical" else "주의"
    return f"[{prefix}] '{keyword}' 관련 뉴스 {count}건 감지"


def _build_description(
    articles: list[NewsArticle], context_summary: str = ""
) -> str:
    """관련 뉴스 제목 나열 + AI 문맥 요약 포함."""
    lines = []
    # AI 문맥 요약이 있으면 상단에 배치
    if context_summary:
        lines.append(f"[AI 분석] {context_summary}")
        lines.append("")
    for a in articles[:5]:  # 최대 5개
        lines.append(f"- {a.title}")
    if len(articles) > 5:
        lines.append(f"외 {len(articles) - 5}건")
    return "\n".join(lines)


def deactivate_old_alerts(db: Session) -> int:
    """24시간이 지난 알림을 비활성화."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = (
        db.query(MacroAlert)
        .filter(MacroAlert.is_active == True, MacroAlert.created_at < cutoff)  # noqa: E712
        .update({"is_active": False})
    )
    if count:
        db.commit()
        logger.info(f"Deactivated {count} old macro alerts")
    return count
