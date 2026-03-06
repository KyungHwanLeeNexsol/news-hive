"""매크로 리스크 감지 서비스.

뉴스 크롤링 후 리스크 키워드 빈도를 분석하여 임계치 초과 시 MacroAlert를 생성한다.
"""
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
        "keywords": ["디폴트", "채무불이행", "부도", "파산"],
    },
    {
        "name": "폭락",
        "keywords": ["폭락", "급락", "서킷브레이커", "사이드카", "패닉셀", "투매", "블랙먼데이"],
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

# 임계치: 최근 N시간 내 뉴스 기사 수
WINDOW_HOURS = 1  # 1시간 윈도우
WARNING_THRESHOLD = 3  # 3건 이상 → warning
CRITICAL_THRESHOLD = 7  # 7건 이상 → critical
# 같은 키워드로 알림을 중복 생성하지 않는 최소 간격 (시간)
COOLDOWN_HOURS = 6


def detect_macro_risks(db: Session) -> list[MacroAlert]:
    """최근 크롤링된 뉴스에서 매크로 리스크 키워드를 감지하고 알림을 생성한다."""
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
                matched_articles.append(article)

        count = len(matched_articles)
        if count < WARNING_THRESHOLD:
            continue

        level = "critical" if count >= CRITICAL_THRESHOLD else "warning"

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
                existing.description = _build_description(matched_articles)
                db.commit()
                logger.info(f"Macro alert upgraded to critical: {group_name} ({count} articles)")
            continue

        # 알림 생성
        title = _build_title(group_name, count, level)
        description = _build_description(matched_articles)

        alert = MacroAlert(
            level=level,
            keyword=group_name,
            title=title,
            description=description,
            article_count=count,
            is_active=True,
        )
        db.add(alert)
        created_alerts.append(alert)
        logger.info(f"Macro alert created: [{level}] {group_name} ({count} articles)")

    if created_alerts:
        db.commit()

    return created_alerts


def _build_title(keyword: str, count: int, level: str) -> str:
    """알림 제목 생성."""
    prefix = "긴급" if level == "critical" else "주의"
    return f"[{prefix}] '{keyword}' 관련 뉴스 {count}건 감지"


def _build_description(articles: list[NewsArticle]) -> str:
    """관련 뉴스 제목 나열."""
    lines = []
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
