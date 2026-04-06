"""키워드 매칭 및 알림 발송 서비스 (SPEC-FOLLOW-001).

신규 뉴스/공시에서 사용자 팔로잉 키워드를 매칭하고 알림을 발송한다.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 모듈 수준 상태: 마지막 실행 시각 (첫 실행 시 None)
_last_run: datetime | None = None


def match_keywords_and_notify(db: Session) -> dict:
    """마지막 실행 이후 신규 뉴스/공시에서 사용자 키워드를 매칭하고 알림을 발송한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        실행 통계 딕셔너리.
        예: {"matched": 5, "notified": 3, "skipped_duplicates": 2}
    """
    global _last_run

    from app.models.news import NewsArticle
    from app.models.disclosure import Disclosure
    from app.models.following import StockFollowing, StockKeyword, KeywordNotification
    from app.models.user import User

    stats = {"matched": 0, "notified": 0, "skipped_duplicates": 0}

    # 마지막 실행 이후 기간 결정 (첫 실행이면 최근 1시간)
    since = _last_run if _last_run else datetime.now(timezone.utc) - timedelta(hours=1)

    try:
        # 신규 뉴스 조회
        recent_news = (
            db.query(NewsArticle)
            .filter(NewsArticle.collected_at > since)
            .all()
        )

        # 신규 공시 조회
        recent_disclosures = (
            db.query(Disclosure)
            .filter(Disclosure.created_at > since)
            .all()
        )

        # 활성 키워드를 user_id별로 그룹화
        # {user_id: [(keyword_id, keyword, stock_id), ...]}
        keyword_rows = (
            db.query(StockKeyword, StockFollowing.user_id, StockFollowing.stock_id)
            .join(StockFollowing, StockKeyword.following_id == StockFollowing.id)
            .all()
        )

        user_keywords: dict[int, list[tuple[int, str, int]]] = {}
        for kw, user_id, stock_id in keyword_rows:
            user_keywords.setdefault(user_id, []).append((kw.id, kw.keyword, stock_id))

        if not user_keywords:
            # 팔로잉 키워드가 없으면 스킵
            _last_run = datetime.now(timezone.utc)
            return stats

        # 뉴스 매칭
        for article in recent_news:
            # 검색 텍스트: 제목 + (ai_summary 또는 content) 최대 500자
            extra = (article.ai_summary or article.content or "")[:500]
            search_text = (article.title + " " + extra).lower()

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, _stock_id in kw_list:
                    # 최소 2자 이상 키워드만 매칭
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "news",
                            KeywordNotification.content_id == article.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break  # 동일 뉴스에 이미 알림 발송됨

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="news",
                        content_id=article.id,
                        content_title=article.title,
                        content_url=article.url,
                        keyword_text=keyword,
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break  # 사용자당 뉴스 1건에 첫 매칭 키워드만 사용

        # 공시 매칭
        for disclosure in recent_disclosures:
            extra = (disclosure.ai_summary or "")[:500]
            search_text = (disclosure.report_name + " " + disclosure.corp_name + " " + extra).lower()

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, _stock_id in kw_list:
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "disclosure",
                            KeywordNotification.content_id == disclosure.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="disclosure",
                        content_id=disclosure.id,
                        content_title=disclosure.report_name,
                        content_url=disclosure.url,
                        keyword_text=keyword,
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break

        # 리포트 매칭 (SPEC-FOLLOW-002)
        from app.models.securities_report import SecuritiesReport

        recent_reports = (
            db.query(SecuritiesReport)
            .filter(SecuritiesReport.collected_at > since)
            .all()
        )
        for report in recent_reports:
            search_text = (
                report.title + " " + report.company_name + " " + (report.opinion or "")
            ).lower()

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, _stock_id in kw_list:
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "report",
                            KeywordNotification.content_id == report.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="report",
                        content_id=report.id,
                        content_title=report.title,
                        content_url=report.url,
                        keyword_text=keyword,
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break

        db.commit()

    except Exception as e:
        logger.error(f"키워드 매칭 실패: {e}")
        db.rollback()
    finally:
        _last_run = datetime.now(timezone.utc)

    return stats


def _dispatch_notification(
    db: Session,
    user_id: int,
    keyword_id: int,
    content_type: str,
    content_id: int,
    content_title: str,
    content_url: str,
    keyword_text: str,
) -> str:
    """알림을 발송하고 채널명을 반환한다.

    Args:
        db: SQLAlchemy 세션
        user_id: 알림 수신 사용자 ID
        keyword_id: 매칭된 키워드 ID
        content_type: 콘텐츠 유형 (news|disclosure)
        content_id: 콘텐츠 ID
        content_title: 콘텐츠 제목
        content_url: 콘텐츠 URL
        keyword_text: 매칭된 키워드 텍스트

    Returns:
        사용된 채널명: "telegram" | "web_push" | "none"
    """
    from app.models.following import KeywordNotification
    from app.models.user import User
    from app.models.user import PushSubscription

    channel = "none"

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return channel

    # 알림 메시지 구성 (SPEC-FOLLOW-002: 리포트 타입 추가)
    type_label = {"news": "뉴스", "disclosure": "공시", "report": "리포트"}.get(content_type, "알림")
    message = (
        f"<b>[키워드 알림] {keyword_text}</b>\n\n"
        f"<b>{type_label}</b>: {content_title}\n"
        f"<a href='{content_url}'>자세히 보기</a>"
    )

    # 텔레그램 우선 발송
    if user.telegram_chat_id:
        try:
            from app.services.telegram_service import send_telegram_message

            # BackgroundScheduler는 동기 컨텍스트이므로 asyncio.run() 사용
            success = asyncio.run(send_telegram_message(user.telegram_chat_id, message))
            if success:
                channel = "telegram"
        except Exception as e:
            logger.error(f"텔레그램 발송 실패 (user={user_id}): {e}")

    # 텔레그램 미발송 시 Web Push 폴백
    if channel == "none":
        subscriptions = (
            db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        )
        if subscriptions:
            from app.services.push_service import send_push_notification

            for sub in subscriptions:
                try:
                    success = asyncio.run(
                        send_push_notification(
                            endpoint=sub.endpoint,
                            p256dh_key=sub.p256dh_key,
                            auth_key=sub.auth_key,
                            title=f"[키워드 알림] {keyword_text}",
                            body=content_title,
                            url=content_url,
                        )
                    )
                    if success:
                        channel = "web_push"
                        break
                except Exception as e:
                    logger.error(f"Web Push 발송 실패 (user={user_id}): {e}")

    if channel == "none":
        return channel

    # 알림 이력 저장
    try:
        notification = KeywordNotification(
            user_id=user_id,
            keyword_id=keyword_id,
            content_type=content_type,
            content_id=content_id,
            content_title=content_title[:500],
            content_url=content_url[:1000],
            channel=channel,
        )
        db.add(notification)
        # 커밋은 호출자(match_keywords_and_notify)가 일괄 처리
    except Exception as e:
        logger.error(f"알림 이력 저장 실패 (user={user_id}): {e}")

    return channel
