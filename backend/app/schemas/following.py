"""팔로잉 시스템 Pydantic 스키마 (SPEC-FOLLOW-001)."""

from datetime import datetime

from pydantic import BaseModel, field_validator


class FollowStockRequest(BaseModel):
    """종목 팔로잉 요청 스키마."""

    stock_code: str

    @field_validator("stock_code")
    @classmethod
    def validate_stock_code(cls, v: str) -> str:
        """종목 코드는 6자리 숫자여야 한다."""
        v = v.strip()
        if len(v) != 6 or not v.isdigit():
            raise ValueError("종목 코드는 6자리 숫자여야 합니다")
        return v


class FollowingResponse(BaseModel):
    """팔로잉 항목 응답 스키마."""

    following_id: int
    stock_code: str
    stock_name: str
    keyword_count: int
    last_notification_at: datetime | None = None

    model_config = {"from_attributes": True}


class FollowingListResponse(BaseModel):
    """팔로잉 목록 응답 스키마."""

    items: list[FollowingResponse]


class AddKeywordRequest(BaseModel):
    """수동 키워드 추가 요청 스키마."""

    keyword: str

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, v: str) -> str:
        """키워드 길이 검증 (2~100자)."""
        v = v.strip()
        if len(v) < 2:
            raise ValueError("키워드는 최소 2자 이상이어야 합니다")
        if len(v) > 100:
            raise ValueError("키워드는 최대 100자까지 입력 가능합니다")
        return v


class BulkDeleteKeywordsRequest(BaseModel):
    """키워드 일괄 삭제 요청 스키마."""

    keyword_ids: list[int]

    @field_validator("keyword_ids")
    @classmethod
    def validate_keyword_ids(cls, v: list[int]) -> list[int]:
        """삭제 대상 키워드 ID 목록 검증."""
        if not v:
            raise ValueError("삭제할 키워드를 하나 이상 선택하세요")
        if len(v) > 100:
            raise ValueError("한번에 최대 100개까지 삭제할 수 있습니다")
        return v


class KeywordResponse(BaseModel):
    """키워드 응답 스키마."""

    id: int
    keyword: str
    category: str
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class KeywordsByCategory(BaseModel):
    """카테고리별 키워드 그룹 응답 스키마."""

    product: list[KeywordResponse] = []
    competitor: list[KeywordResponse] = []
    upstream: list[KeywordResponse] = []
    market: list[KeywordResponse] = []
    custom: list[KeywordResponse] = []


class AIGenerateResponse(BaseModel):
    """AI 키워드 생성 응답 스키마."""

    keywords: KeywordsByCategory
    message: str = ""


class TelegramLinkResponse(BaseModel):
    """텔레그램 연동 코드 응답 스키마."""

    code: str
    instruction: str


class TelegramStatusResponse(BaseModel):
    """텔레그램 연동 상태 응답 스키마."""

    linked: bool
    chat_id: str | None = None


class NotificationHistoryItem(BaseModel):
    """알림 이력 항목 스키마."""

    id: int
    content_type: str
    content_title: str
    content_url: str
    sent_at: datetime
    channel: str

    model_config = {"from_attributes": True}


class NotificationHistoryResponse(BaseModel):
    """알림 이력 목록 응답 스키마 (페이지네이션 포함)."""

    items: list[NotificationHistoryItem]
    total: int
