from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.following import KeywordNotification, StockFollowing, StockKeyword
from app.models.news import NewsArticle
from app.models.user import User
from app.services.keyword_matcher import _find_existing_notification
from app.services.scheduler import _cleanup_old_articles


def test_find_existing_notification_by_url(db, make_stock) -> None:
    user = User(
        email="dedup@example.com",
        password_hash="hashed",
        email_verified=True,
        telegram_chat_id="123456",
    )
    db.add(user)
    db.flush()

    stock = make_stock()
    following = StockFollowing(user_id=user.id, stock_id=stock.id)
    db.add(following)
    db.flush()

    keyword = StockKeyword(
        following_id=following.id,
        keyword="반도체",
        category="custom",
        source="manual",
    )
    db.add(keyword)
    db.flush()

    existing = KeywordNotification(
        user_id=user.id,
        keyword_id=keyword.id,
        content_type="news",
        content_id=101,
        content_title="기존 기사",
        content_url="https://example.com/article/1",
        channel="telegram",
    )
    db.add(existing)
    db.commit()

    found = _find_existing_notification(
        db,
        user_id=user.id,
        content_type="news",
        content_id=202,
        content_url="https://example.com/article/1",
    )

    assert found is not None
    assert found.id == existing.id


def test_unique_constraint_blocks_duplicate_notification(db, make_stock) -> None:
    """UniqueConstraint(user_id, content_type, content_id)로 DB 레벨 중복 삽입이 차단되는지 검증."""
    user = User(
        email="uc_dedup@example.com",
        password_hash="hashed",
        email_verified=True,
        telegram_chat_id="654321",
    )
    db.add(user)
    db.flush()

    stock = make_stock()
    following = StockFollowing(user_id=user.id, stock_id=stock.id)
    db.add(following)
    db.flush()

    keyword = StockKeyword(
        following_id=following.id,
        keyword="배터리",
        category="custom",
        source="manual",
    )
    db.add(keyword)
    db.flush()

    first = KeywordNotification(
        user_id=user.id,
        keyword_id=keyword.id,
        content_type="news",
        content_id=500,
        content_title="기사 제목",
        content_url="https://example.com/500",
        channel="telegram",
    )
    db.add(first)
    db.commit()

    # 동일 (user_id, content_type, content_id) — SAVEPOINT로 격리된 롤백 후 외부 트랜잭션 유지 확인
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            duplicate = KeywordNotification(
                user_id=user.id,
                keyword_id=keyword.id,
                content_type="news",
                content_id=500,
                content_title="기사 제목 (중복)",
                content_url="https://example.com/500",
                channel="telegram",
            )
            db.add(duplicate)

    # SAVEPOINT 롤백 후 외부 세션이 유효한지 — 정상 조회 가능해야 함
    count = db.query(KeywordNotification).filter(
        KeywordNotification.user_id == user.id,
        KeywordNotification.content_id == 500,
    ).count()
    assert count == 1  # 중복 삽입이 차단되고 원본 1개만 존재


def test_cleanup_old_articles_keeps_recent_null_published_at(db, make_news) -> None:
    now = datetime.utcnow()
    recent_without_published = make_news(
        title="recent-null-published",
        published_at=None,
        collected_at=now,
    )
    stale_without_published = make_news(
        title="stale-null-published",
        published_at=None,
        collected_at=now - timedelta(days=8),
    )
    stale_with_published = make_news(
        title="stale-with-published",
        published_at=now - timedelta(days=8),
        collected_at=now - timedelta(days=8),
    )
    recent_id = recent_without_published.id
    stale_null_id = stale_without_published.id
    stale_published_id = stale_with_published.id

    _cleanup_old_articles(db)

    remaining_ids = {
        row[0]
        for row in db.query(NewsArticle.id).all()
    }

    assert recent_id in remaining_ids
    assert stale_null_id not in remaining_ids
    assert stale_published_id not in remaining_ids
