from __future__ import annotations

import base64
import io
import json
import logging
import threading
from weakref import WeakValueDictionary

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.models import LoginSession, PlatformAccount, User
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from xhs_utils.xhs_core.errors import XhsLoginBlockedError
from backend.app.services.account_service import (
    cookie_header_from_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/xhs/login-sessions", tags=["xhs-login-sessions"])

# 同一进程内串行处理每个登录会话，避免并发重复换取凭证。
# 弱引用保证仍有调用方持有锁时不会创建第二把锁，无请求引用后自动清理。
_session_locks: WeakValueDictionary = WeakValueDictionary()
_session_locks_guard = threading.Lock()


def _session_lock(session_id: int) -> threading.Lock:
    with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock


class PcQrCodeRequest(BaseModel):
    sync_creator: bool = False


class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    sync_creator: bool = False


class PhoneConfirmRequest(BaseModel):
    session_id: int
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    sync_creator: bool | None = None


def _dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    return json.loads(value)


def _dump_temp_state(
    cookies: dict,
    *,
    sync_creator: bool = False,
    exchanged: bool = False,
    account_id: int | None = None,
    creator_account_id: int | None = None,
    login_state: dict | None = None,
    login_error: dict | None = None,
) -> str:
    """保存会话临时状态。

    exchanged=True 表示“二维码已换取正式 web_session”，后续轮询必须跳过
    状态校验（二维码只能消费一次，重复换取会被上游拒绝）。
    """
    if sync_creator or exchanged or account_id is not None or login_state is not None or login_error is not None:
        payload: dict = {"cookies": cookies}
        if sync_creator:
            payload["sync_creator"] = True
        if exchanged:
            payload["exchanged"] = True
        if account_id is not None:
            payload["account_id"] = account_id
        if creator_account_id is not None:
            payload["creator_account_id"] = creator_account_id
        if login_state is not None:
            payload["login_state"] = login_state
        if login_error is not None:
            payload["login_error"] = login_error
        return _dump_json(payload)
    return _dump_json(cookies)


def _load_temp_state(value: str | None) -> tuple[dict, bool, bool]:
    payload = _load_json(value)
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), dict):
        return (
            payload["cookies"],
            bool(payload.get("sync_creator")),
            bool(payload.get("exchanged")),
        )
    if isinstance(payload, dict):
        return payload, False, False
    return {}, False, False


def _expire_stale_sessions(db: Session, *, user_id: int, sub_type: str) -> None:
    """同一用户同类型的旧待扫码会话置为 expired。

    前端每次挂载/切换参数都会新建会话，旧会话若保持 pending 会一直
    被轮询（甚至被误扫），也让登录会话表无限增长。
    """
    from sqlalchemy import select

    stale = db.scalars(
        select(LoginSession).where(
            LoginSession.user_id == user_id,
            LoginSession.sub_type == sub_type,
            LoginSession.status.in_(("pending", "scanned")),
        )
    ).all()
    for item in stale:
        item.status = "expired"


def _qr_data_url(qr_url: str) -> str:
    import qrcode

    image = qrcode.make(qr_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def get_pc_login_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_login_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


def _mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return f"{phone[:2]}****"
    return f"{phone[:3]}****{phone[-4:]}"


def _sync_creator_account_from_pc_login(
    *,
    db: Session,
    user_id: int,
    pc_cookies: dict,
    creator_adapter: XhsCreatorLoginAdapter,
) -> dict | None:
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(pc_cookies)
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        creator_account, creator_action = _create_account_from_login(
            db=db,
            user_id=user_id,
            sub_type="creator",
            user_info=creator_user_info,
            cookies=creator_result["cookies"],
        )
    except Exception:
        return None
    return serialize_account(creator_account, creator_action)


def _create_account_from_login(
    *,
    db: Session,
    user_id: int,
    sub_type: str,
    user_info: dict,
    cookies: dict,
) -> tuple[PlatformAccount, str]:
    cookies_text = _dump_json(cookies)
    if sub_type == "pc":
        try:
            self_profile = XhsPcApiAdapter(cookie_header_from_text(cookies_text)).get_self_info()
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
    return upsert_platform_account_from_login(
        db=db,
        user_id=user_id,
        platform="xhs",
        sub_type=sub_type,
        user_info=user_info,
        cookies_text=cookies_text,
    )


@router.post("/pc/qrcode")
def pc_qrcode(
    payload: PcQrCodeRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    payload = payload or PcQrCodeRequest()
    try:
        qr_payload = adapter.create_qrcode()
    except XhsLoginBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS PC QR code generation failed: {exc}",
        ) from exc
    _expire_stale_sessions(db, user_id=current_user.id, sub_type="pc")
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        status="pending",
        qr_id=qr_payload["qr_id"],
        code=qr_payload["code"],
        qr_url=qr_payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(
                qr_payload["cookies"],
                sync_creator=payload.sync_creator,
                login_state=qr_payload.get("login_state"),
            )
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.post("/creator/qrcode")
def creator_qrcode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        payload = adapter.create_qrcode()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS Creator QR code generation failed: {exc}",
        ) from exc
    _expire_stale_sessions(db, user_id=current_user.id, sub_type="creator")
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        status="pending",
        qr_id=payload["qr_id"],
        qr_url=payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(_dump_json(payload["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


def _terminal_login_response(db: Session, session: LoginSession) -> dict:
    payload = {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "account": None,
        "creator_account": None,
    }
    if session.status not in {"confirmed", "blocked"}:
        return payload
    try:
        state = _load_json(decrypt_text(session.encrypted_temp_cookies))
    except (InvalidToken, json.JSONDecodeError):
        session.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="登录会话数据已失效，请刷新二维码后重新扫码",
        )
    if session.status == "blocked":
        payload.update(state.get("login_error") or {})
        return payload
    for response_key, state_key in (("account", "account_id"), ("creator_account", "creator_account_id")):
        account_id = state.get(state_key)
        if isinstance(account_id, int):
            account = db.get(PlatformAccount, account_id)
            if account is not None and account.user_id == session.user_id:
                payload[response_key] = serialize_account(account)
    return payload


@router.get("/{session_id}")
def login_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    """轮询登录会话状态。

    注意：本 GET **带有副作用**——它会向上游校验二维码状态、写库并推进会话
    状态机。保留 GET 是因为前端轮询与旧客户端已按此契约实现；代价是
    CDN/链接预取器可能意外触发一次检查（幂等，最多多打一次上游）。
    新调用方请优先使用同一路径的 POST 语义版本（如后续新增）。
    """
    session = db.get(LoginSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    if session.status not in {"confirmed", "expired", "blocked"} and (
        session.sub_type not in {"pc", "creator"} or not session.qr_id
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")

    # 并发轮询复用当前状态：不重复打上游（二维码只能消费一次）
    lock = _session_lock(session.id)
    if not lock.acquire(blocking=False):
        return {
            "session_id": session.id,
            "status": session.status,
            "qr_url": session.qr_url,
            "account": None,
            "creator_account": None,
            "polling": True,
        }

    try:
        # A request may have loaded the row before the preceding poll committed.
        db.refresh(session)
        if session.status in {"confirmed", "expired", "blocked"}:
            return _terminal_login_response(db, session)
        return _poll_login_session(
            session=session,
            current_user=current_user,
            db=db,
            pc_adapter=pc_adapter,
            creator_adapter=creator_adapter,
        )
    finally:
        lock.release()


def _stop_blocked_login(db: Session, session: LoginSession, error: XhsLoginBlockedError) -> dict:
    session.status = "blocked"
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state({}, login_error=error.public_details())
    )
    db.commit()
    logger.warning("XHS login stopped after HTTP 471 session=%s", session.id)
    return _terminal_login_response(db, session)


def _poll_login_session(
    *,
    session: LoginSession,
    current_user: User,
    db: Session,
    pc_adapter: XhsPcLoginAdapter,
    creator_adapter: XhsCreatorLoginAdapter,
) -> dict:
    try:
        temp_state = decrypt_text(session.encrypted_temp_cookies)
        cookies, sync_creator, exchanged = _load_temp_state(temp_state)
        envelope = _load_json(temp_state)
        login_state = envelope.get("login_state") if isinstance(envelope.get("cookies"), dict) else None
    except InvalidToken:
        # SECRET_KEY 变更或数据损坏：无法再解密上游 Cookie，只能让用户重扫
        session.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="登录会话已失效（服务端密钥变更），请刷新二维码后重新扫码",
        )

    account_sub_type = "pc" if session.sub_type == "pc" else "creator"

    # 已完成二维码换取、但上次获取账号信息失败：跳过换取，直接重试拿用户信息
    if not exchanged:
        try:
            if session.sub_type == "pc":
                if not session.code:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unsupported login session",
                    )
                state_options = {"login_state": login_state} if login_state is not None else {}
                result = pc_adapter.check_qrcode_status(session.qr_id, session.code, cookies, **state_options)
            else:
                result = creator_adapter.check_qrcode_status(session.qr_id, cookies)
        except XhsLoginBlockedError as exc:
            return _stop_blocked_login(db, session, exc)
        except HTTPException:
            raise
        except Exception as exc:
            checkpoint = getattr(exc, "login_state", None)
            if checkpoint is not None:
                session.encrypted_temp_cookies = encrypt_text(
                    _dump_temp_state(cookies, sync_creator=sync_creator, login_state=checkpoint)
                )
                db.commit()
            logger.exception("XHS 二维码状态轮询失败 session=%s", session.id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"小红书登录状态校验失败：{exc}。请稍后重试或刷新二维码",
            ) from exc

        status_value = result.get("status") or "pending"
        cookies = result.get("cookies") or cookies
        login_state = result.get("login_state", login_state)
        # 换取成功后先记 scanned + exchanged（而不是直接 confirmed）：
        # 若随后获取账号信息失败，下次轮询还能跳过换取继续重试，
        # 否则会被“confirmed 直接返回”的分支挡住，永远拿不到账号。
        session.status = "scanned" if status_value == "confirmed" else status_value
        session.encrypted_temp_cookies = encrypt_text(
            _dump_temp_state(
                cookies,
                sync_creator=sync_creator,
                exchanged=status_value == "confirmed",
                login_state=login_state,
            )
        )
        db.commit()
        if status_value != "confirmed":
            return {
                "session_id": session.id,
                "status": session.status,
                "qr_url": session.qr_url,
                "account": None,
                "creator_account": None,
            }
        db.refresh(session)
    else:
        # 上次已完成换取：跳过状态校验，直接续跑账号信息获取
        pass

    try:
        state_options = {"login_state": login_state} if login_state is not None else {}
        user_info = (
            pc_adapter.get_user_info(cookies, **state_options)
            if account_sub_type == "pc"
            else creator_adapter.get_user_info(cookies)
        )
        login_state = user_info.pop("login_state", login_state)
    except XhsLoginBlockedError as exc:
        return _stop_blocked_login(db, session, exc)
    except Exception as exc:
        checkpoint = getattr(exc, "login_state", None)
        if checkpoint is not None:
            session.encrypted_temp_cookies = encrypt_text(
                _dump_temp_state(cookies, sync_creator=sync_creator, exchanged=True, login_state=checkpoint)
            )
            db.commit()
        logger.exception("XHS 扫码已确认但获取账号信息失败 session=%s", session.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"扫码已确认，但获取账号信息失败：{exc}。请稍等重试（无需重新扫码）",
        ) from exc

    try:
        account, action = _create_account_from_login(
            db=db,
            user_id=current_user.id,
            sub_type=account_sub_type,
            user_info=user_info,
            cookies=cookies,
        )
        account_payload = serialize_account(account, action)
        creator_account_payload = None
        if account_sub_type == "pc" and sync_creator:
            creator_account_payload = _sync_creator_account_from_pc_login(
                db=db,
                user_id=current_user.id,
                pc_cookies=cookies,
                creator_adapter=creator_adapter,
            )
        # Keep the completed result for retries if the first response is lost.
        session.encrypted_temp_cookies = encrypt_text(
            _dump_temp_state(
                cookies,
                sync_creator=sync_creator,
                exchanged=True,
                account_id=account.id,
                creator_account_id=creator_account_payload["id"] if creator_account_payload else None,
            )
        )
        session.status = "confirmed"
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("XHS 登录账号保存失败 session=%s", session.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"账号信息保存失败：{exc}",
        ) from exc

    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "account": account_payload,
        "creator_account": creator_account_payload,
    }


@router.post("/pc/phone/send-code")
def pc_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    _expire_stale_sessions(db, user_id=current_user.id, sub_type="pc")
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(result["cookies"], sync_creator=payload.sync_creator)
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/pc/phone/confirm")
def pc_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "pc", creator_adapter)


@router.post("/creator/phone/send-code")
def creator_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    _expire_stale_sessions(db, user_id=current_user.id, sub_type="creator")
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(_dump_json(result["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/creator/phone/confirm")
def creator_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "creator", None)


def _confirm_phone_login(
    payload: PhoneConfirmRequest,
    current_user: User,
    db: Session,
    adapter,
    sub_type: str,
    creator_adapter: XhsCreatorLoginAdapter | None,
):
    session = db.get(LoginSession, payload.session_id)
    if (
        session is None
        or session.user_id != current_user.id
        or session.sub_type != sub_type
        or session.login_method != "phone"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    try:
        cookies, stored_sync_creator, _exchanged = _load_temp_state(
            decrypt_text(session.encrypted_temp_cookies)
        )
        result = adapter.confirm_phone_login(payload.phone, payload.code, cookies)
        user_info = adapter.get_user_info(result["cookies"])
    except Exception as exc:
        logger.exception("XHS 手机验证码登录失败 session=%s", session.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"手机验证码登录失败：{exc}",
        ) from exc

    sync_creator = payload.sync_creator if payload.sync_creator is not None else stored_sync_creator
    session.status = "confirmed"
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state(result["cookies"], sync_creator=sync_creator)
    )
    account, action = _create_account_from_login(
        db=db,
        user_id=current_user.id,
        sub_type=sub_type,
        user_info=user_info,
        cookies=result["cookies"],
    )
    creator_account_payload = None
    if sub_type == "pc" and creator_adapter is not None and sync_creator:
        creator_account_payload = _sync_creator_account_from_pc_login(
            db=db,
            user_id=current_user.id,
            pc_cookies=result["cookies"],
            creator_adapter=creator_adapter,
        )
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "account": serialize_account(account, action),
        "creator_account": creator_account_payload,
    }
