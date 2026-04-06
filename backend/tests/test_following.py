"""SPEC-FOLLOW-001 기업 팔로잉 API 통합 테스트.

팔로잉 CRUD, 키워드 관리, 텔레그램 연동, 알림 이력 조회 엔드포인트를 검증한다.
get_current_user 의존성을 Mock으로 대체하여 인증 없이 테스트한다.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.stock import Stock
from app.models.following import KeywordNotification, StockFollowing, StockKeyword


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user(db: Session) -> User:
    """테스트용 사용자 픽스처."""
    from app.routers.auth import hash_password

    user = User(
        email="test@example.com",
        password_hash=hash_password("password123"),
        name="테스트유저",
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def test_stock(db: Session, make_stock) -> Stock:
    """테스트용 종목 픽스처 (종목코드 고정)."""
    return make_stock(name="삼성전자", stock_code="005930")


@pytest.fixture
def auth_client(client: TestClient, test_user: User) -> TestClient:
    """get_current_user를 Mock으로 대체한 인증된 TestClient."""
    from app.routers.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: test_user
    yield client
    # 오버라이드 정리는 client 픽스처의 clear()가 처리


@pytest.fixture
def test_following(db: Session, test_user: User, test_stock: Stock) -> StockFollowing:
    """테스트용 팔로잉 픽스처."""
    following = StockFollowing(user_id=test_user.id, stock_id=test_stock.id)
    db.add(following)
    db.flush()
    return following


# ---------------------------------------------------------------------------
# 팔로잉 CRUD 테스트
# ---------------------------------------------------------------------------


def test_follow_stock_success(auth_client: TestClient, test_stock: Stock) -> None:
    """종목 팔로잉 추가 성공 — 201 반환."""
    resp = auth_client.post("/api/following/stocks", json={"stock_code": "005930"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["stock_code"] == "005930"
    assert data["stock_name"] == "삼성전자"
    assert data["keyword_count"] == 0
    assert "following_id" in data


def test_follow_stock_duplicate_409(
    auth_client: TestClient,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """이미 팔로잉 중인 종목 재등록 시 409 반환."""
    resp = auth_client.post("/api/following/stocks", json={"stock_code": "005930"})
    assert resp.status_code == 409
    assert "이미 팔로잉" in resp.json()["detail"]


def test_follow_stock_not_found_404(auth_client: TestClient) -> None:
    """존재하지 않는 종목 코드로 팔로잉 시 404 반환."""
    resp = auth_client.post("/api/following/stocks", json={"stock_code": "999999"})
    assert resp.status_code == 404
    assert "종목을 찾을 수 없습니다" in resp.json()["detail"]


def test_unfollow_stock_success(
    auth_client: TestClient,
    db: Session,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """팔로잉 해제 성공 — 200 반환 및 키워드 CASCADE 삭제 확인."""
    # 키워드 추가 후 삭제가 CASCADE 되는지 확인
    kw = StockKeyword(
        following_id=test_following.id,
        keyword="반도체",
        category="product",
        source="manual",
    )
    db.add(kw)
    db.flush()

    resp = auth_client.delete(f"/api/following/stocks/005930")
    assert resp.status_code == 200
    assert "해제" in resp.json()["message"]

    # DB에서 팔로잉이 삭제되었는지 확인
    db.expire_all()
    deleted = db.query(StockFollowing).filter(StockFollowing.id == test_following.id).first()
    assert deleted is None

    # CASCADE로 키워드도 삭제되었는지 확인
    deleted_kw = db.query(StockKeyword).filter(StockKeyword.id == kw.id).first()
    assert deleted_kw is None


def test_list_followings(
    auth_client: TestClient,
    db: Session,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """팔로잉 목록 조회 — keyword_count 포함 반환."""
    # 키워드 2개 추가
    for keyword in ["반도체", "메모리"]:
        kw = StockKeyword(
            following_id=test_following.id,
            keyword=keyword,
            category="product",
            source="manual",
        )
        db.add(kw)
    db.flush()

    resp = auth_client.get("/api/following/stocks")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["stock_code"] == "005930"
    assert items[0]["keyword_count"] >= 2


# ---------------------------------------------------------------------------
# 키워드 관리 테스트
# ---------------------------------------------------------------------------


def test_add_keyword_manual(
    auth_client: TestClient,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """수동 키워드 추가 성공 — 201 반환, category=custom."""
    resp = auth_client.post(
        "/api/following/stocks/005930/keywords",
        json={"keyword": "갤럭시"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["keyword"] == "갤럭시"
    assert data["category"] == "custom"
    assert data["source"] == "manual"
    assert "id" in data


def test_add_keyword_duplicate_409(
    auth_client: TestClient,
    db: Session,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """중복 키워드 추가 시 409 반환."""
    kw = StockKeyword(
        following_id=test_following.id,
        keyword="반도체",
        category="product",
        source="manual",
    )
    db.add(kw)
    db.flush()

    resp = auth_client.post(
        "/api/following/stocks/005930/keywords",
        json={"keyword": "반도체"},
    )
    assert resp.status_code == 409
    assert "이미 등록된" in resp.json()["detail"]


def test_delete_keyword(
    auth_client: TestClient,
    db: Session,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """키워드 삭제 성공 — 200 반환."""
    kw = StockKeyword(
        following_id=test_following.id,
        keyword="DRAM",
        category="product",
        source="manual",
    )
    db.add(kw)
    db.flush()
    kw_id = kw.id

    resp = auth_client.delete(f"/api/following/stocks/005930/keywords/{kw_id}")
    assert resp.status_code == 200
    assert "삭제" in resp.json()["message"]

    # DB에서 키워드 삭제 확인
    db.expire_all()
    assert db.query(StockKeyword).filter(StockKeyword.id == kw_id).first() is None


def test_get_keywords_by_category(
    auth_client: TestClient,
    db: Session,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """카테고리별 키워드 조회 — 그룹핑 확인."""
    keywords_data = [
        ("DRAM", "product"),
        ("SK하이닉스", "competitor"),
        ("탄소나노튜브", "upstream"),
    ]
    for kw_text, cat in keywords_data:
        db.add(StockKeyword(
            following_id=test_following.id,
            keyword=kw_text,
            category=cat,
            source="ai",
        ))
    db.flush()

    resp = auth_client.get("/api/following/stocks/005930/keywords")
    assert resp.status_code == 200
    data = resp.json()

    # 카테고리별 키워드 확인
    assert any(k["keyword"] == "DRAM" for k in data["product"])
    assert any(k["keyword"] == "SK하이닉스" for k in data["competitor"])
    assert any(k["keyword"] == "탄소나노튜브" for k in data["upstream"])


# ---------------------------------------------------------------------------
# 텔레그램 연동 테스트
# ---------------------------------------------------------------------------


def test_telegram_link_code(
    auth_client: TestClient,
    test_stock: Stock,
) -> None:
    """텔레그램 연동 코드 발급 — 6자리 코드 반환."""
    resp = auth_client.post("/api/following/telegram/link")
    assert resp.status_code == 200
    data = resp.json()
    assert "code" in data
    assert len(data["code"]) == 6
    assert "instruction" in data


def test_telegram_status_unlinked(
    auth_client: TestClient,
    test_user: User,
) -> None:
    """텔레그램 미연동 상태 조회 — linked=false 반환."""
    # 테스트 유저는 telegram_chat_id가 None
    assert test_user.telegram_chat_id is None

    resp = auth_client.get("/api/following/telegram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["linked"] is False
    assert data["chat_id"] is None


def test_telegram_status_linked(
    auth_client: TestClient,
    db: Session,
    test_user: User,
) -> None:
    """텔레그램 연동 상태 조회 — linked=true 반환."""
    test_user.telegram_chat_id = "123456789"
    db.flush()

    resp = auth_client.get("/api/following/telegram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["linked"] is True
    assert data["chat_id"] == "123456789"


# ---------------------------------------------------------------------------
# 알림 이력 테스트
# ---------------------------------------------------------------------------


def test_notification_history_empty(
    auth_client: TestClient,
    test_user: User,
) -> None:
    """알림 이력 조회 — 빈 목록 반환."""
    resp = auth_client.get("/api/following/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_notification_history(
    auth_client: TestClient,
    db: Session,
    test_user: User,
    test_stock: Stock,
    test_following: StockFollowing,
) -> None:
    """알림 이력 조회 — 페이지네이션 포함."""
    # 알림 이력 3건 생성
    for i in range(3):
        notif = KeywordNotification(
            user_id=test_user.id,
            content_type="news",
            content_id=i + 1,
            content_title=f"테스트 뉴스 {i + 1}",
            content_url=f"https://example.com/news/{i + 1}",
            channel="telegram",
        )
        db.add(notif)
    db.flush()

    resp = auth_client.get("/api/following/notifications?page=1&size=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2  # size=2 이므로 2개만 반환
    assert data["items"][0]["content_type"] == "news"
    assert "content_title" in data["items"][0]
    assert "sent_at" in data["items"][0]
