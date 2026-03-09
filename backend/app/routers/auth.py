"""관리자 인증 API."""

import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory token store (sufficient for single-admin use)
_active_tokens: dict[str, float] = {}  # token → expiry timestamp
TOKEN_TTL = 60 * 60 * 24 * 7  # 7 days


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


def _verify_admin_token(token: str) -> bool:
    """Check if a token is valid and not expired."""
    expiry = _active_tokens.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _active_tokens.pop(token, None)
        return False
    return True


@router.post("/login", response_model=LoginResponse)
async def admin_login(req: LoginRequest):
    """관리자 로그인. ADMIN_PASSWORD와 일치하면 토큰 발급."""
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD가 설정되지 않았습니다.")

    if not hmac.compare_digest(req.password, settings.ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")

    token = secrets.token_urlsafe(32)
    _active_tokens[token] = time.time() + TOKEN_TTL

    # Cleanup expired tokens (keep memory clean)
    now = time.time()
    expired = [t for t, exp in _active_tokens.items() if now > exp]
    for t in expired:
        _active_tokens.pop(t, None)

    return LoginResponse(token=token, expires_in=TOKEN_TTL)


@router.get("/verify")
async def verify_token(request: Request):
    """토큰 유효성 확인."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")

    token = auth[7:]
    if not _verify_admin_token(token):
        raise HTTPException(status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다.")

    return {"valid": True}
