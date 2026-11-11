"""抖音账号服务：绑定/重新授权/列表/状态检查。

凭证只在服务端存取（加密存储），序列化永不输出 Cookie。
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.douyin.contracts import DouyinAdapter, DouyinAuthError
from backend.app.douyin.models import DouyinAccount


def serialize_account(account: DouyinAccount) -> dict:
    return {
        "id": account.id,
        "provider_account_id": account.provider_account_id,
        "nickname": account.nickname,
        "avatar_url": account.avatar_url,
        "status": account.status,
        "status_message": account.status_message,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


def get_owned_account(db: Session, user_id: int, account_id: int) -> Optional[DouyinAccount]:
    return db.scalar(
        select(DouyinAccount).where(
            DouyinAccount.id == account_id, DouyinAccount.user_id == user_id
        )
    )


def list_accounts(db: Session, user_id: int, limit: int = 200) -> list[DouyinAccount]:
    # review P2：此前无上限，数据增长后响应无界。默认取前 200 个。
    return list(
        db.scalars(
            select(DouyinAccount)
            .where(DouyinAccount.user_id == user_id)
            .order_by(DouyinAccount.id)
            .limit(limit)
        )
    )


def _apply_identity(account: DouyinAccount, identity, cookie: str) -> None:
    account.provider_account_id = identity.provider_account_id
    account.nickname = identity.nickname or account.nickname
    account.avatar_url = identity.avatar_url or account.avatar_url
    account.cookie_encrypted = encrypt_text(cookie)
    account.status = "active"
    account.status_message = ""
    account.profile_json = json.dumps(identity.raw, ensure_ascii=False, default=str)


def upsert_account(
    db: Session, user_id: int, cookie: str, adapter: DouyinAdapter,
    account_id: Optional[int] = None,
) -> DouyinAccount:
    """绑定或重新授权。同一 (user, sec_uid) 只保留一行；确认失败也落库便于用户看到原因。"""
    existing: Optional[DouyinAccount] = None
    if account_id is not None:
        existing = get_owned_account(db, user_id, account_id)
        if existing is None:
            raise LookupError("account not found")
    try:
        identity = adapter.check_account(cookie)
    except DouyinAuthError as error:
        if existing is None:
            # 复用最近一条未确认身份的失效行，避免反复重试堆积垃圾行。
            existing = db.scalar(
                select(DouyinAccount).where(
                    DouyinAccount.user_id == user_id,
                    DouyinAccount.provider_account_id.is_(None),
                    DouyinAccount.status == "invalid",
                )
            )
            if existing is None:
                existing = DouyinAccount(user_id=user_id)
                db.add(existing)
        existing.cookie_encrypted = encrypt_text(cookie)
        existing.status = "invalid"
        existing.status_message = f"凭证确认失败：{error}"
        db.commit()
        db.refresh(existing)
        return existing
    except Exception as error:  # 网络/上游异常：不落库新账号，直接让用户重试
        if existing is not None:
            db.rollback()
        raise

    if existing is None:
        existing = db.scalar(
            select(DouyinAccount).where(
                DouyinAccount.user_id == user_id,
                DouyinAccount.provider_account_id == identity.provider_account_id,
            )
        )
        if existing is None:
            existing = DouyinAccount(user_id=user_id)
            db.add(existing)
    elif identity.provider_account_id:
        # 重新授权时凭证可能属于同用户的另一已绑定账号：提前拒绝，
        # 避免改写本行 provider_account_id 后撞 (user, sec_uid) 唯一约束变成 500。
        conflict = db.scalar(
            select(DouyinAccount).where(
                DouyinAccount.user_id == user_id,
                DouyinAccount.provider_account_id == identity.provider_account_id,
                DouyinAccount.id != existing.id,
            )
        )
        if conflict is not None:
            raise ValueError(
                f"该 Cookie 属于已绑定的账号「{conflict.nickname or conflict.provider_account_id}」，"
                "请直接使用该账号，或先解绑后再绑定"
            )
    _apply_identity(existing, identity, cookie)
    db.commit()
    db.refresh(existing)
    return existing


def recheck_account(
    db: Session, user_id: int, account: DouyinAccount, adapter: DouyinAdapter
) -> DouyinAccount:
    """重新确认已绑定账号的授权状态。"""
    try:
        cookie = decrypt_text(account.cookie_encrypted)
    except Exception as error:
        account.status = "invalid"
        account.status_message = "凭证解密失败，请重新授权"
        db.commit()
        db.refresh(account)
        return account
    try:
        identity = adapter.check_account(cookie)
    except DouyinAuthError as error:
        account.status = "invalid"
        account.status_message = f"凭证失效：{error}"
        db.commit()
        db.refresh(account)
        return account
    except Exception as error:
        account.status_message = f"检查失败（状态未知）：{error}"
        db.commit()
        db.refresh(account)
        return account
    _apply_identity(account, identity, cookie)
    account.updated_at = shanghai_now()
    db.commit()
    db.refresh(account)
    return account


def account_cookie(account: DouyinAccount) -> str:
    """解密账号 Cookie；解密失败统一翻译为授权类错误（调用方按 409/failed 处理）。"""
    try:
        return decrypt_text(account.cookie_encrypted)
    except Exception as error:
        raise DouyinAuthError("凭证解密失败，请删除账号后重新授权") from error
