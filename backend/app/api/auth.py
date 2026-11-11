from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth_throttle import (
    auth_attempt_key,
    check_rate_limit,
    consume_ip_rate_limit,
    release_ip_rate_limit_at,
)
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
REFRESH_COOKIE_NAME = "refresh_token"
# 用户名字符集：字母/数字/点/下划线/连字符，strip 后 3-80 位（SEC-6）
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,80}$")


class AuthCredentials(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=128)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        # 先 strip 再校验：空格用户名在 min_length 之前无法拦截（P1-11）
        stripped = value.strip()
        if not _USERNAME_RE.match(stripped):
            raise ValueError("用户名需为 3-80 位字母、数字、点、下划线或连字符")
        return stripped


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
    return {"id": user.id, "username": user.username, "is_admin": bool(user.is_admin)}


def _cookie_secure() -> bool:
    # Secure cookie 在纯 HTTP 本地开发环境会无法携带，按环境开关
    return get_settings().environment == "production"


def _set_refresh_cookie(response: Response, user: User) -> None:
    """SEC-7：refresh token 改为 HttpOnly Cookie，浏览器 JS 不可读。"""
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        create_refresh_token(user.id, user.token_version),
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")


def _set_media_cookie(response: Response, user: User) -> None:
    """下发媒体读取专用 HttpOnly cookie（<img> 标签无法带 Authorization 头）。"""
    response.set_cookie(
        MEDIA_COOKIE_NAME,
        create_media_token(user.id, user.token_version),
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/api/files",
    )


def _token_response(user: User, response: Response) -> dict:
    _set_media_cookie(response, user)
    _set_refresh_cookie(response, user)
    settings = get_settings()
    return {
        "access_token": create_access_token(user.id, user.token_version),
        # SEC-7：默认不再把 refresh token 放进响应体（XSS 无法窃取长期凭证）；
        # include_refresh_in_body=true 仅用于兼容尚未升级的旧客户端
        "refresh_token": (
            create_refresh_token(user.id, user.token_version)
            if settings.include_refresh_in_body
            else None
        ),
        "token_type": "bearer",
        "user": _serialize_user(user),
    }


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _auth_ip_gate(request: Request) -> float | None:
    """PBKDF2 之前的硬闸门：只按 IP 维度限流。

    这是防 CPU DoS 的关键位——超限的请求绝不能再跑一次 26 万轮哈希。
    只按 IP 维度（而非 IP+用户名）是为了保住「正确密码总能登录」的语义：
    攻击者刷他人账号到 429 时，受害者本人仍可通过。

    返回本次占用的窗口时间戳（供登录成功后精确退还）；超限返回 None。
    """
    settings = get_settings()
    client_ip = _client_ip(request)
    return consume_ip_rate_limit(client_ip, max(settings.auth_rate_limit_per_minute * 5, 50))


def _auth_ip_gate_exceeded(request: Request) -> bool:
    """布尔语义的入口闸门（不退还场景使用，如注册）。"""
    return _auth_ip_gate(request) is None


def _auth_rate_limit_exceeded(request: Request, username: str) -> bool:
    """失败尝试计数（IP+用户名 维度），超限返回 True。

    IP 维度的兜底完全由入口闸门（_auth_ip_gate）承担，本函数不再涉及。
    """
    settings = get_settings()
    client_ip = _client_ip(request)
    user_key = auth_attempt_key(client_ip, username)
    return not check_rate_limit(user_key, settings.auth_rate_limit_per_minute)


def _auth_rate_limit_refund(request: Request, gate_timestamp: float) -> None:
    """登录成功时**精确**退还本次入口占用的 IP 名额。

    早期版本弹队列尾部，并发下会误删其它请求的记录——攻击者可用
    「成功登录 + 换名失败」交替把 IP 闸门净消耗洗成 0（换名喷洒不再
    受 IP 上限约束）。按时间戳精确移除后，成功登录只回收自己的名额。
    """
    release_ip_rate_limit_at(_client_ip(request), gate_timestamp)


def _raise_throttled() -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="尝试过于频繁，请稍后再试",
    )


@router.post("/register")
def register(credentials: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.registration_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="注册已关闭，请联系管理员")
    # 注册对所有尝试限流（防批量灌号）：先过 IP 硬闸门，再按 IP+用户名计数
    if _auth_ip_gate_exceeded(request) or _auth_rate_limit_exceeded(request, credentials.username):
        _raise_throttled()
    if len(credentials.password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"密码长度至少 {settings.password_min_length} 位",
        )

    username = credentials.username.strip()
    existing_user = db.scalar(select(User).where(User.username == username))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")

    user = User(username=username, password_hash=hash_password(credentials.password))
    # 应用权限管理：首个注册用户自动成为管理员
    #（迁移负责把存量库的最低 id 用户置位；全新库在这里兜底）
    is_first_user = (
        db.scalar(select(func.count()).select_from(User)) or 0
    ) == 0
    if is_first_user:
        user.is_admin = True
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发同名注册：唯一约束兜底（P1-11），而不是 500
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
        ) from exc
    db.refresh(user)
    if user.is_admin:
        # 并发注册对账（review P2）：两个并发首注册都可能读到 count=0 而双置
        # is_admin。提交后收敛为「最低 id 唯一管理员」。
        other_admins = (
            db.scalar(
                select(func.count()).select_from(User).where(
                    User.is_admin == True,  # noqa: E712
                    User.id != user.id,
                )
            )
            or 0
        )
        if other_admins and user.id > (
            db.scalar(select(func.min(User.id)).where(User.is_admin == True)) or 0  # noqa: E711,E712
        ):
            user.is_admin = False
            db.commit()
            db.refresh(user)
    return _token_response(user, response)


@router.post("/login")
def login(credentials: AuthCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    username = credentials.username.strip()
    # SEC-6（review P1）：昂贵的 PBKDF2 校验之前必须先过 IP 硬闸门，
    # 否则被限流的请求仍会完整消耗一次 26 万轮哈希，限流挡不住 CPU DoS。
    gate_timestamp = _auth_ip_gate(request)
    if gate_timestamp is None:
        _raise_throttled()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(credentials.password, user.password_hash):
        # 失败尝试按 IP+用户名计数（成功登录不算失败，见下方 refund）
        if _auth_rate_limit_exceeded(request, username):
            _raise_throttled()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    # 成功登录：只退还本次自己占用的 IP 名额（精确到时间戳）
    _auth_rate_limit_refund(request, gate_timestamp)
    if is_legacy_password_hash(user.password_hash):
        # 无盐 SHA-256 旧格式：验证通过后立即升级为 pbkdf2
        user.password_hash = hash_password(credentials.password)
        db.add(user)
        db.commit()
    return _token_response(user, response)


@router.post("/refresh")
def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    payload: Optional[RefreshRequest] = None,
):
    """刷新 access token。

    凭证来源：显式 body（API 客户端过渡兼容）优先，其次 HttpOnly Cookie（浏览器）。
    仅使用 Cookie 时要求 ``X-Requested-With: XMLHttpRequest`` 自定义头作为
    CSRF 防线（SameSite=Lax 之外的第二道）。
    """
    body_token = payload.refresh_token if payload else None
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if body_token:
        token = body_token
    elif cookie_token:
        if request.headers.get("x-requested-with", "").lower() != "xmlhttprequest":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing CSRF header",
            )
        token = cookie_token
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    decoded = decode_token(token)
    if decoded.get("token_type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(User, decoded["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # review P2：令牌版本不一致说明该 refresh token 已被吊销（logout-all）
    if int(decoded.get("ver") or 0) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    _set_media_cookie(response, user)
    _set_refresh_cookie(response, user)  # 轮换：每次刷新下发新 refresh token
    return {"access_token": create_access_token(user.id, user.token_version), "token_type": "bearer"}


@router.post("/logout")
def logout(request: Request, response: Response):
    _clear_refresh_cookie(response)
    response.delete_cookie(MEDIA_COOKIE_NAME, path="/api/files")
    return {"status": "ok"}


@router.post("/logout-all")
def logout_all(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """吊销该用户已签发的全部令牌（所有设备）。

    无状态 JWT 的轮换/登出此前只是清浏览器 cookie，已泄露的 refresh token
    仍可用满 7 天。自增 token_version 后，旧 token 的 ver 声明不再匹配。
    """
    # 原子自增：read-modify-write 在并发 logout-all 下会丢失更新
    # （方向安全——只会少加、旧 token 依然失效，但版本号会漂移）
    db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(token_version=User.token_version + 1)
    )
    db.commit()
    db.refresh(current_user)
    _clear_refresh_cookie(response)
    response.delete_cookie(MEDIA_COOKIE_NAME, path="/api/files")
    return {"status": "ok", "token_version": current_user.token_version}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return _serialize_user(current_user)
