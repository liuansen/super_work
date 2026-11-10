from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_media_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_legacy_password_hash,
    verify_password,
)
from backend.app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

MEDIA_COOKIE_NAME = "media_token"


class AuthCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    id: int
    username: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserResponse] = None


def _serialize_user(user: User) -> dict:
    return {"id": user.id, "username": user.username}


def _set_media_cookie(response: Response, user: User) -> None:
    """下发媒体读取专用 HttpOnly cookie（<img> 标签无法带 Authorization 头）。"""
    response.set_cookie(
        MEDIA_COOKIE_NAME,
        create_media_token(user.id),
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/api/files",
    )


def _token_response(user: User, response: Response) -> dict:
    _set_media_cookie(response, user)
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user": _serialize_user(user),
    }


@router.post("/register")
def register(credentials: AuthCredentials, response: Response, db: Session = Depends(get_db)):
    if not get_settings().registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="注册已关闭，请联系管理员")
    username = credentials.username.strip()
    existing_user = db.scalar(select(User).where(User.username == username))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")

    user = User(username=username, password_hash=hash_password(credentials.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user, response)


@router.post("/login")
def login(credentials: AuthCredentials, response: Response, db: Session = Depends(get_db)):
    username = credentials.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if is_legacy_password_hash(user.password_hash):
        # 无盐 SHA-256 旧格式：验证通过后立即升级为 pbkdf2
        user.password_hash = hash_password(credentials.password)
        db.add(user)
        db.commit()
    return _token_response(user, response)


@router.post("/refresh")
def refresh_token(payload: RefreshRequest, response: Response, db: Session = Depends(get_db)):
    decoded = decode_token(payload.refresh_token)
    if decoded.get("token_type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(User, decoded["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    _set_media_cookie(response, user)
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(MEDIA_COOKIE_NAME, path="/api/files")
    return {"status": "ok"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return _serialize_user(current_user)
