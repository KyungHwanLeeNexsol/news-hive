"""기업 팔로잉 API 라우터 (SPEC-FOLLOW-001).

팔로잉 CRUD, 키워드 관리, 텔레그램 연동, 알림 이력 조회 엔드포인트를 제공한다.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.following import KeywordNotification, StockFollowing, StockKeyword
from app.models.stock import Stock
from app.routers.auth import get_current_user
from app.models.user import User
from app.schemas.following import (
    AddKeywordRequest,
    AIGenerateResponse,
    FollowingListResponse,
    FollowingResponse,
    FollowStockRequest,
    KeywordResponse,
    KeywordsByCategory,
    NotificationHistoryItem,
    NotificationHistoryResponse,
    TelegramLinkResponse,
    TelegramStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/following", tags=["following"])

# 텔레그램 연동 코드 임시 저장 (code → {user_id, expires_at})
# 인메모리 딕셔너리 — 10분 TTL
_link_codes: dict[str, dict] = {}

# 링크 코드 유효 시간 (분)
_LINK_CODE_TTL_MINUTES = 10


def _cleanup_expired_codes() -> None:
    """만료된 텔레그램 연동 코드를 제거한다."""
    now = datetime.now(timezone.utc)
    expired = [code for code, data in _link_codes.items() if data["expires_at"] < now]
    for code in expired:
        del _link_codes[code]


# ---------------------------------------------------------------------------
# 팔로잉 CRUD
# ---------------------------------------------------------------------------


@router.post("/stocks", status_code=status.HTTP_201_CREATED, response_model=FollowingResponse)
def follow_stock(
    payload: FollowStockRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FollowingResponse:
    """종목 팔로잉 추가.

    동일 종목 중복 팔로잉 시 409를 반환한다.
    """
    # 종목 조회
    stock = db.query(Stock).filter(Stock.stock_code == payload.stock_code).first()
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="종목을 찾을 수 없습니다")

    # 중복 팔로잉 확인
    existing = (
        db.query(StockFollowing)
        .filter(
            StockFollowing.user_id == current_user.id,
            StockFollowing.stock_id == stock.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 팔로잉 중인 종목입니다")

    following = StockFollowing(user_id=current_user.id, stock_id=stock.id)
    db.add(following)
    db.commit()
    db.refresh(following)

    return FollowingResponse(
        following_id=following.id,
        stock_code=stock.stock_code,
        stock_name=stock.name,
        keyword_count=0,
        last_notification_at=None,
    )


@router.delete("/stocks/{stock_code}", response_model=dict)
def unfollow_stock(
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """종목 팔로잉 해제.

    팔로잉이 없을 경우 404를 반환한다.
    CASCADE로 연결된 키워드도 자동 삭제된다.
    """
    stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="종목을 찾을 수 없습니다")

    following = (
        db.query(StockFollowing)
        .filter(
            StockFollowing.user_id == current_user.id,
            StockFollowing.stock_id == stock.id,
        )
        .first()
    )
    if not following:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="팔로잉을 찾을 수 없습니다")

    db.delete(following)
    db.commit()
    return {"message": "팔로잉이 해제되었습니다"}


@router.get("/stocks", response_model=FollowingListResponse)
def list_followings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FollowingListResponse:
    """팔로잉 종목 목록 조회.

    각 팔로잉의 키워드 수와 마지막 알림 시각을 함께 반환한다.
    """
    # 팔로잉 + 키워드 수 + 마지막 알림 시각 조인 쿼리
    # KeywordNotification은 keyword_id를 통해 해당 팔로잉의 키워드에만 조인해야
    # count(StockKeyword.id)가 알림 수와 곱해지는 카르테시안 곱 문제를 방지한다.
    from sqlalchemy import distinct
    rows = (
        db.query(
            StockFollowing,
            Stock,
            func.count(distinct(StockKeyword.id)).label("keyword_count"),
            func.max(KeywordNotification.sent_at).label("last_notification_at"),
        )
        .join(Stock, StockFollowing.stock_id == Stock.id)
        .outerjoin(StockKeyword, StockKeyword.following_id == StockFollowing.id)
        .outerjoin(
            KeywordNotification,
            (KeywordNotification.keyword_id == StockKeyword.id)
            & (KeywordNotification.user_id == current_user.id),
        )
        .filter(StockFollowing.user_id == current_user.id)
        .group_by(StockFollowing.id, Stock.id)
        .all()
    )

    items = [
        FollowingResponse(
            following_id=following.id,
            stock_code=stock.stock_code,
            stock_name=stock.name,
            keyword_count=keyword_count,
            last_notification_at=last_notification_at,
        )
        for following, stock, keyword_count, last_notification_at in rows
    ]
    return FollowingListResponse(items=items)


# ---------------------------------------------------------------------------
# 키워드 관리
# ---------------------------------------------------------------------------


@router.get("/stocks/{stock_code}/keywords", response_model=KeywordsByCategory)
def get_keywords(
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KeywordsByCategory:
    """팔로잉 종목의 키워드 목록을 카테고리별로 반환한다."""
    following = _get_following_or_404(stock_code, current_user.id, db)

    keywords = db.query(StockKeyword).filter(StockKeyword.following_id == following.id).all()

    grouped: dict[str, list[KeywordResponse]] = {
        "product": [], "competitor": [], "upstream": [], "market": [], "custom": []
    }
    for kw in keywords:
        cat = kw.category if kw.category in grouped else "custom"
        grouped[cat].append(KeywordResponse.model_validate(kw))

    return KeywordsByCategory(**grouped)


@router.post("/stocks/{stock_code}/keywords", status_code=status.HTTP_201_CREATED, response_model=KeywordResponse)
def add_keyword(
    stock_code: str,
    payload: AddKeywordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KeywordResponse:
    """팔로잉 종목에 수동 키워드를 추가한다.

    중복 키워드 등록 시 409를 반환한다.
    """
    following = _get_following_or_404(stock_code, current_user.id, db)

    # 중복 확인
    existing = (
        db.query(StockKeyword)
        .filter(
            StockKeyword.following_id == following.id,
            StockKeyword.keyword == payload.keyword,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 등록된 키워드입니다")

    kw = StockKeyword(
        following_id=following.id,
        keyword=payload.keyword,
        category="custom",
        source="manual",
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return KeywordResponse.model_validate(kw)


@router.delete("/stocks/{stock_code}/keywords/{keyword_id}", response_model=dict)
def delete_keyword(
    stock_code: str,
    keyword_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """팔로잉 종목의 키워드를 삭제한다."""
    following = _get_following_or_404(stock_code, current_user.id, db)

    kw = (
        db.query(StockKeyword)
        .filter(
            StockKeyword.id == keyword_id,
            StockKeyword.following_id == following.id,
        )
        .first()
    )
    if not kw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="키워드를 찾을 수 없습니다")

    db.delete(kw)
    db.commit()
    return {"message": "키워드가 삭제되었습니다"}


@router.post("/stocks/{stock_code}/keywords/ai-generate", response_model=AIGenerateResponse)
async def ai_generate_keywords(
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AIGenerateResponse:
    """AI를 사용하여 팔로잉 종목의 키워드를 자동 생성한다."""
    from app.services.keyword_generator import generate_keywords

    following = _get_following_or_404(stock_code, current_user.id, db)

    # 종목 정보 조회
    stock = db.query(Stock).filter(Stock.id == following.stock_id).first()
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="종목을 찾을 수 없습니다")

    # 기존 키워드 조회 (중복 제거용)
    existing_keywords = [
        kw.keyword
        for kw in db.query(StockKeyword).filter(StockKeyword.following_id == following.id).all()
    ]

    # AI 키워드 생성
    generated = await generate_keywords(
        stock_code=stock.stock_code,
        company_name=stock.name,
        existing_keywords=existing_keywords,
        db=db,
    )

    # AI 서비스 불가 시 503 반환
    if generated is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI 서비스를 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )

    # 생성된 키워드를 DB에 저장
    new_keywords: dict[str, list[KeywordResponse]] = {
        "product": [], "competitor": [], "upstream": [], "market": [], "custom": []
    }

    for category, kw_list in generated.items():
        if category not in new_keywords:
            continue
        for keyword_text in kw_list:
            try:
                kw = StockKeyword(
                    following_id=following.id,
                    keyword=keyword_text,
                    category=category,
                    source="ai",
                )
                db.add(kw)
                db.flush()  # ID 할당을 위해 flush
                new_keywords[category].append(KeywordResponse.model_validate(kw))
            except Exception:
                # UNIQUE 제약 위반 등 예외 무시
                logger.exception("AI 키워드 저장 실패 (category=%s, keyword=%s)", category, kw_text)
                db.rollback()

    db.commit()

    keyword_count = sum(len(v) for v in new_keywords.values())
    message = f"{keyword_count}개의 키워드가 생성되었습니다" if keyword_count > 0 else "생성된 키워드가 없습니다"

    return AIGenerateResponse(
        keywords=KeywordsByCategory(**new_keywords),
        message=message,
    )


# ---------------------------------------------------------------------------
# 텔레그램 연동
# ---------------------------------------------------------------------------


@router.post("/telegram/link", response_model=TelegramLinkResponse)
def generate_telegram_link_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TelegramLinkResponse:
    """텔레그램 연동용 6자리 코드를 생성한다.

    10분 유효한 코드를 발급하며 사용자는 봇에 해당 코드를 전송하여 연동한다.
    """
    _cleanup_expired_codes()

    code = secrets.token_urlsafe(4)[:6].upper()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_LINK_CODE_TTL_MINUTES)
    _link_codes[code] = {"user_id": current_user.id, "expires_at": expires_at}

    instruction = (
        f"텔레그램 봇에 아래 코드를 전송하면 연동이 완료됩니다.\n"
        f"코드: <b>{code}</b>\n"
        f"유효 시간: {_LINK_CODE_TTL_MINUTES}분"
    )
    return TelegramLinkResponse(code=code, instruction=instruction)


@router.get("/telegram/status", response_model=TelegramStatusResponse)
def get_telegram_status(
    current_user: User = Depends(get_current_user),
) -> TelegramStatusResponse:
    """현재 사용자의 텔레그램 연동 상태를 반환한다."""
    return TelegramStatusResponse(
        linked=current_user.telegram_chat_id is not None,
        chat_id=current_user.telegram_chat_id,
    )


@router.delete("/telegram/link", response_model=dict)
def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """텔레그램 연동을 해제한다."""
    current_user.telegram_chat_id = None
    db.commit()
    return {"message": "텔레그램 연동이 해제되었습니다"}


@router.post("/telegram/webhook", response_model=dict)
async def telegram_webhook(
    payload: dict,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """텔레그램 Bot 웹훅 엔드포인트.

    사용자가 봇에 연동 코드를 전송하면 telegram_chat_id를 저장한다.
    TELEGRAM_WEBHOOK_SECRET 설정 시 X-Telegram-Bot-Api-Secret-Token 헤더 검증.
    """
    from app.config import settings

    # 웹훅 시크릿 검증 (설정된 경우에만)
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")
    from app.services.telegram_service import send_telegram_message, answer_callback_query

    _cleanup_expired_codes()

    try:
        # 인라인 버튼 클릭 처리 (callback_query)
        if "callback_query" in payload:
            cb = payload["callback_query"]
            cb_id = cb.get("id", "")
            cb_data = cb.get("data", "")
            cb_chat_id = str(cb.get("from", {}).get("id", ""))

            if cb_data.startswith("del_kw:") and cb_chat_id:
                try:
                    keyword_id = int(cb_data.split(":", 1)[1])
                    user = db.query(User).filter(User.telegram_chat_id == cb_chat_id).first()
                    if not user:
                        await answer_callback_query(cb_id, "연동된 계정을 찾을 수 없습니다")
                        return {"ok": True}

                    kw = (
                        db.query(StockKeyword)
                        .join(StockFollowing, StockKeyword.following_id == StockFollowing.id)
                        .filter(
                            StockKeyword.id == keyword_id,
                            StockFollowing.user_id == user.id,
                        )
                        .first()
                    )
                    if kw:
                        kw_text = kw.keyword
                        db.delete(kw)
                        db.commit()
                        await answer_callback_query(cb_id, f"'{kw_text}' 키워드가 삭제되었습니다")
                        await send_telegram_message(
                            cb_chat_id,
                            f"✅ <b>{kw_text}</b> 키워드가 삭제되었습니다.",
                        )
                    else:
                        await answer_callback_query(cb_id, "키워드를 찾을 수 없거나 권한이 없습니다")
                except (ValueError, IndexError):
                    await answer_callback_query(cb_id, "잘못된 요청입니다")
            return {"ok": True}

        # 텔레그램 Update 파싱 (연동 코드)
        message = payload.get("message", {})
        text = (message.get("text") or "").strip().upper()
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))

        if not text or not chat_id:
            return {"ok": True}

        # 연동 코드 확인
        if text not in _link_codes:
            await send_telegram_message(
                chat_id,
                "유효하지 않거나 만료된 코드입니다. NewsHive 앱에서 새 코드를 발급받으세요.",
            )
            return {"ok": True}

        code_data = _link_codes[text]
        # 만료 확인
        if code_data["expires_at"] < datetime.now(timezone.utc):
            del _link_codes[text]
            await send_telegram_message(
                chat_id,
                "코드가 만료되었습니다. NewsHive 앱에서 새 코드를 발급받으세요.",
            )
            return {"ok": True}

        # 사용자 telegram_chat_id 저장
        user_id = code_data["user_id"]
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.telegram_chat_id = chat_id
            db.commit()
            del _link_codes[text]
            await send_telegram_message(
                chat_id,
                "텔레그램 연동이 완료되었습니다. 이제 팔로잉 키워드 알림을 받을 수 있습니다.",
            )
        else:
            await send_telegram_message(chat_id, "연동 처리 중 오류가 발생했습니다. 다시 시도해주세요.")

    except Exception as e:
        logger.error(f"텔레그램 웹훅 처리 예외: {e}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# 알림 이력
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationHistoryResponse)
def get_notification_history(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationHistoryResponse:
    """알림 발송 이력을 페이지네이션으로 반환한다."""
    total = (
        db.query(func.count(KeywordNotification.id))
        .filter(KeywordNotification.user_id == current_user.id)
        .scalar()
        or 0
    )

    items = (
        db.query(KeywordNotification)
        .filter(KeywordNotification.user_id == current_user.id)
        .order_by(KeywordNotification.sent_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    return NotificationHistoryResponse(
        items=[NotificationHistoryItem.model_validate(item) for item in items],
        total=total,
    )


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _get_following_or_404(stock_code: str, user_id: int, db: Session) -> StockFollowing:
    """stock_code와 user_id로 팔로잉을 조회한다. 없으면 404 예외를 발생시킨다."""
    stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
    if not stock:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="종목을 찾을 수 없습니다")

    following = (
        db.query(StockFollowing)
        .filter(
            StockFollowing.user_id == user_id,
            StockFollowing.stock_id == stock.id,
        )
        .first()
    )
    if not following:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="팔로잉을 찾을 수 없습니다")

    return following
