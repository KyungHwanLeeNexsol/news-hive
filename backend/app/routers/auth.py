"""인증 API 라우터.

관리자 인증 (/api/auth/login, /api/auth/verify) 과
일반 사용자 이메일/비밀번호 인증 (/api/auth/user/...) 을 모두 제공한다.
"""

import hashlib  # noqa: F401  (향후 사용 가능성 유지)
import hmac
import logging
import random
import secrets
import string
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import EmailVerificationCode, RefreshToken, User
from app.services.email_service import send_verification_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ──────────────────────────────────────────────
# 비밀번호 해싱 컨텍스트 (bcrypt)
# ──────────────────────────────────────────────
# # @MX:ANCHOR: 비밀번호 해싱 전역 컨텍스트 — 전 앱에서 단일 인스턴스를 공유
# # @MX:REASON: passlib CryptContext 는 스레드 안전하며 모듈 로드 시 1회만 초기화해야 함
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 스킴 — 사용자 전용 (Admin 토큰과 구분)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/user/login", auto_error=False)

# ──────────────────────────────────────────────
# 관리자 인증용 인메모리 토큰 스토어
# ──────────────────────────────────────────────
_active_tokens: dict[str, float] = {}  # token → expiry timestamp
TOKEN_TTL = 60 * 60 * 24 * 7  # 7일


# ═══════════════════════════════════════════════════════
# Pydantic 요청/응답 스키마
# ═══════════════════════════════════════════════════════


class LoginRequest(BaseModel):
    """관리자 로그인 요청."""

    password: str


class LoginResponse(BaseModel):
    """관리자 로그인 응답."""

    token: str
    expires_in: int


class RegisterRequest(BaseModel):
    """사용자 회원가입 요청."""

    email: EmailStr
    password: str
    name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")
        return v

    @field_validator("name")
    @classmethod
    def name_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("이름을 입력해 주세요.")
        return v.strip()


class VerifyEmailRequest(BaseModel):
    """이메일 인증 토큰 확인 요청 (하위 호환 유지)."""

    token: str


class ResendVerificationRequest(BaseModel):
    """인증 코드 재발송 요청."""

    email: EmailStr


class UserLoginRequest(BaseModel):
    """사용자 로그인 요청."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT 토큰 응답."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    """액세스 토큰 갱신 요청."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """로그아웃 요청."""

    refresh_token: str


# ═══════════════════════════════════════════════════════
# 헬퍼 함수
# ═══════════════════════════════════════════════════════


def verify_password(plain: str, hashed: str) -> bool:
    """bcrypt 해시와 평문 비밀번호를 비교한다."""
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환한다."""
    return pwd_context.hash(plain)


def create_access_token(user_id: int) -> str:
    """사용자 ID로 JWT 액세스 토큰을 생성한다 (유효기간: ACCESS_TOKEN_EXPIRE_MINUTES).

    페이로드: { sub: user_id, type: "access", exp }
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token_db(user_id: int, db: Session) -> str:
    """리프레시 토큰을 생성하고 DB에 저장한 뒤 토큰 문자열을 반환한다.

    토큰 값은 URL-safe random string 이다.
    """
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    db_token = RefreshToken(
        user_id=user_id,
        token=token_value,
        expires_at=expires_at,
    )
    db.add(db_token)
    db.commit()
    return token_value


def _generate_verification_token() -> str:
    """URL-safe 랜덤 인증 토큰을 생성한다 (43자)."""
    return secrets.token_urlsafe(32)


# # @MX:ANCHOR: 사용자 인증 의존성 — 보호된 사용자 API 전반에서 사용됨
# # @MX:REASON: OAuth2 Bearer 토큰 검증의 단일 진입점이므로 변경 시 전체 보안에 영향
async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """JWT 액세스 토큰을 검증하고 해당 User 객체를 반환한다.

    FastAPI Depends 로 주입되는 의존성 함수.
    """
    if token is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        token_type: str | None = payload.get("type")
        user_id_str: str | None = payload.get("sub")

        if token_type != "access" or user_id_str is None:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다.")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    return user


def _verify_admin_token(token: str) -> bool:
    """관리자 토큰이 유효하고 만료되지 않았는지 확인한다."""
    expiry = _active_tokens.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _active_tokens.pop(token, None)
        return False
    return True


# ═══════════════════════════════════════════════════════
# 관리자 인증 엔드포인트 (기존 유지)
# ═══════════════════════════════════════════════════════


@router.post("/login", response_model=LoginResponse)
async def admin_login(req: LoginRequest) -> LoginResponse:
    """관리자 로그인. ADMIN_PASSWORD와 일치하면 토큰 발급."""
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD가 설정되지 않았습니다.")

    if not hmac.compare_digest(req.password, settings.ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")

    token = secrets.token_urlsafe(32)
    _active_tokens[token] = time.time() + TOKEN_TTL

    # 만료된 토큰 정리 (메모리 누수 방지)
    now = time.time()
    expired = [t for t, exp in _active_tokens.items() if now > exp]
    for t in expired:
        _active_tokens.pop(t, None)

    return LoginResponse(token=token, expires_in=TOKEN_TTL)


@router.get("/verify")
async def verify_token(request: Request) -> dict:
    """관리자 토큰 유효성 확인."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")

    token = auth[7:]
    if not _verify_admin_token(token):
        raise HTTPException(status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다.")

    return {"valid": True}


# ═══════════════════════════════════════════════════════
# 사용자 인증 엔드포인트 (신규)
# ═══════════════════════════════════════════════════════


@router.post("/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """사용자 회원가입.

    이메일 중복 확인 → bcrypt 해시 저장 → 인증 코드 이메일 발송.
    """
    # 이메일 중복 확인
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

    # 비밀번호 해시 및 사용자 생성
    new_user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        email_verified=False,
    )
    db.add(new_user)
    db.flush()  # user.id 확보 (commit 전)

    # 인증 토큰 생성 및 저장 (24시간 유효)
    token = _generate_verification_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    verification = EmailVerificationCode(
        user_id=new_user.id,
        code=token,
        expires_at=expires_at,
    )
    db.add(verification)
    db.commit()

    # 인증 링크 생성 후 이메일 발송 (실패해도 회원가입은 완료된 것으로 처리)
    verify_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify?token={token}"
    try:
        await send_verification_email(req.email, verify_link)
    except Exception:
        logger.exception("회원가입 인증 이메일 발송 실패: %s", req.email)

    return {"message": "이메일을 확인하세요", "user_id": new_user.id}


@router.get("/verify-email")
async def verify_email(token: str, db: Session = Depends(get_db)) -> dict:
    """이메일 인증 링크 클릭 처리.

    URL 쿼리 파라미터로 전달된 토큰을 검증하고 user.email_verified = True 처리.
    """
    now = datetime.now(timezone.utc)
    verification = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.code == token,
            EmailVerificationCode.used.is_(False),
            EmailVerificationCode.expires_at > now,
        )
        .first()
    )
    if verification is None:
        raise HTTPException(
            status_code=400, detail="인증 링크가 올바르지 않거나 만료되었습니다."
        )

    user = verification.user
    verification.used = True
    user.email_verified = True
    db.commit()

    return {"message": "이메일 인증 완료"}


@router.post("/resend-verification")
async def resend_verification(
    req: ResendVerificationRequest, db: Session = Depends(get_db)
) -> dict:
    """인증 코드 재발송.

    마지막 코드 생성 후 60초 이내에는 재발송을 거부한다 (속도 제한).
    """
    user = db.query(User).filter(User.email == req.email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if user.email_verified:
        raise HTTPException(status_code=400, detail="이미 인증된 이메일입니다.")

    # 60초 이내 코드 존재 여부 확인 (속도 제한)
    rate_limit_threshold = datetime.now(timezone.utc) - timedelta(seconds=60)
    recent = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.created_at > rate_limit_threshold,
        )
        .first()
    )
    if recent:
        raise HTTPException(
            status_code=429, detail="잠시 후 다시 시도해 주세요. (60초 대기)"
        )

    # 새 토큰 생성 (24시간 유효)
    token = _generate_verification_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    verification = EmailVerificationCode(
        user_id=user.id,
        code=token,
        expires_at=expires_at,
    )
    db.add(verification)
    db.commit()

    verify_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify?token={token}"
    try:
        await send_verification_email(req.email, verify_link)
    except Exception:
        logger.exception("인증 링크 재발송 실패: %s", req.email)
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다.")

    return {"message": "인증 링크를 재발송했습니다"}


@router.post("/user/login", response_model=TokenResponse)
async def user_login(req: UserLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """사용자 로그인.

    이메일 인증 완료 + bcrypt 검증 → JWT 액세스/리프레시 토큰 발급.
    """
    user = db.query(User).filter(User.email == req.email).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    if not user.email_verified:
        raise HTTPException(
            status_code=403, detail="이메일 인증이 완료되지 않았습니다. 인증 메일을 확인해 주세요."
        )

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token_db(user.id, db)

    # 마지막 로그인 시각 업데이트
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user={"id": user.id, "email": user.email, "name": user.name},
    )


@router.post("/user/refresh")
async def refresh_access_token(req: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    """액세스 토큰 갱신.

    유효한 리프레시 토큰을 검증하고 새 액세스 토큰을 발급한다.
    """
    now = datetime.now(timezone.utc)
    db_token = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == req.refresh_token,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > now,
        )
        .first()
    )
    if db_token is None:
        raise HTTPException(
            status_code=401, detail="리프레시 토큰이 유효하지 않거나 만료되었습니다."
        )

    new_access_token = create_access_token(db_token.user_id)
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/user/logout")
async def logout(
    req: LogoutRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """로그아웃.

    Bearer 액세스 토큰을 검증하고 리프레시 토큰을 폐기한다.
    """
    # 액세스 토큰으로 사용자 신원 확인
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")

    access_token = auth_header[7:]
    try:
        payload = jwt.decode(
            access_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        token_type = payload.get("type")
        user_id_str = payload.get("sub")
        if token_type != "access" or user_id_str is None:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다.")

    # 해당 사용자의 리프레시 토큰 폐기
    db_token = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == req.refresh_token,
            RefreshToken.user_id == user_id,
        )
        .first()
    )
    if db_token:
        db_token.revoked = True
        db.commit()

    return {"message": "로그아웃 완료"}


@router.get("/user/me")
async def get_me(current_user: User = Depends(get_current_user)) -> dict:
    """현재 로그인한 사용자 정보 반환."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "email_verified": current_user.email_verified,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }
