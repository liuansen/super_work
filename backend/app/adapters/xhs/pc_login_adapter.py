from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env

logger = logging.getLogger(__name__)

# SDK check_qrcode_status 的固定文案（codeStatus 0/1/2/3）
# 优先精确匹配；子串匹配仅作文案微调时的兜底
_QR_STATUS_EXACT = {
    "请扫描二维码": "pending",
    "请确认登录": "scanned",
    "验证成功": "confirmed",
    "二维码已过期": "expired",
}


def _qr_status_from_message(success: bool, message: str) -> str:
    exact = _QR_STATUS_EXACT.get(str(message or "").strip())
    if exact is not None:
        return exact
    text = str(message or "")
    lowered = text.lower()
    if "过期" in text or "expired" in lowered:
        return "expired"
    if "确认" in text or "confirm" in lowered:
        return "scanned"
    if success:
        return "confirmed"
    logger.warning(f"XHS PC 二维码状态文案无法识别，按 pending 处理: {message!r}")
    return "pending"


class XhsPcLoginAdapter:
    @contextmanager
    def _login_api(self, cookies=None, login_state=None):
        from apis.xhs_pc_login_apis import XHSLoginApi

        with direct_xhs_request_env():
            api = XHSLoginApi()
            try:
                if login_state is not None:
                    api.restore_login_state(cookies, login_state)
                yield api
            except Exception as exc:
                exc.login_state = api.export_login_state()
                raise
            finally:
                api.close()

    def create_qrcode(self) -> dict[str, Any]:
        with self._login_api() as api:
            cookies = api.generate_init_cookies()
            success, message, payload = api.generate_qrcode(cookies)
            if not success or not payload:
                raise RuntimeError(message)
            cookies = payload["cookies"]
            # Follow the SDK's complete QR flow before displaying the code.
            ready, message, cookies = api.check_qrcode_status(payload["qr_id"], payload["code"], cookies)
            if ready or message != "请扫描二维码":
                raise RuntimeError("二维码预检查未通过，请重新生成二维码")
            api.ensure_webprofile(cookies)
            return {
                "cookies": cookies,
                "qr_id": payload["qr_id"],
                "code": payload["code"],
                "qr_url": payload["qr_url"],
                "login_state": api.export_login_state(),
            }

    def check_qrcode_status(self, qr_id: str, code: str, cookies: dict[str, Any], *, login_state=None) -> dict[str, Any]:
        with self._login_api(cookies, login_state) as api:
            success, message, updated_cookies = api.check_qrcode_status(qr_id, code, cookies)
            status = _qr_status_from_message(success, message)
            return {"status": status, "cookies": updated_cookies, "login_state": api.export_login_state()}

    def get_user_info(self, cookies: dict[str, Any], *, login_state=None) -> dict[str, Any]:
        with self._login_api(cookies, login_state) as api:
            success, data, _ = api.get_user_info(cookies)
            if not success or not isinstance(data, dict) or data.get("guest") is not False or not data.get("user_id"):
                raise RuntimeError("小红书尚未返回已登录的正式账号信息")
            return {
                "external_user_id": data.get("user_id", ""),
                "nickname": data.get("nickname", ""),
                "avatar_url": data.get("images") or data.get("imageb") or "",
                "login_state": api.export_login_state(),
                "profile": {
                    "red_id": data.get("red_id") or data.get("redId") or "",
                    "followers": data.get("fans") or data.get("followers") or data.get("follower_count"),
                    "following": data.get("follows") or data.get("following") or data.get("following_count"),
                    "likes": data.get("liked_count") or data.get("likes") or data.get("like_count"),
                    "raw": data,
                },
            }

    def create_phone_session(self, phone: str) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi

            api = XHSLoginApi()
            cookies = api.generate_init_cookies()
            success, message, _ = api.send_phone_code(phone, cookies)
        if not success:
            raise RuntimeError(message)
        return {"cookies": cookies, "message": message or "sent"}

    def confirm_phone_login(self, phone: str, code: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi

            api = XHSLoginApi()
            success, message, payload = api.login_by_phone(phone, code, cookies)
        if not success or not payload:
            raise RuntimeError(message)
        return {"status": "confirmed", "cookies": payload["cookies"]}
