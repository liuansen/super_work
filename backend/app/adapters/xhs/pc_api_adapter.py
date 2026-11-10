from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from backend.app.adapters.xhs.request_env import direct_xhs_request_env


class XhsPcApiAdapter:
    def __init__(self, cookies: str) -> None:
        self.cookies = cookies

    @contextmanager
    def _api(self) -> Iterator[Any]:
        """按调用创建 SDK 客户端，用完显式关闭底层 HTTP 会话。

        curl_cffi Session 没有 __del__，依赖 GC 释放会长期占用连接/句柄。
        """
        from apis.xhs_pc_apis import XHS_Apis
        from xhs_utils.xhs_pc import XHSPcAuth

        auth = XHSPcAuth.from_cookie(self.cookies)
        try:
            yield XHS_Apis(auth)
        finally:
            try:
                auth.close()
            except Exception:
                pass

    def search_note(
        self,
        keyword: str,
        page: int = 1,
        sort_type_choice: int = 0,
        note_type: int = 0,
        note_time: int = 0,
        note_range: int = 0,
        pos_distance: int = 0,
        geo: str = "",
    ) -> Any:
        with direct_xhs_request_env(), self._api() as api:
            return api.search_note(
                query=keyword,
                page=page,
                sort_type_choice=sort_type_choice,
                note_type=note_type,
                note_time=note_time,
                note_range=note_range,
                pos_distance=pos_distance,
                geo=geo,
            )

    def get_note_info(self, url: str) -> Any:
        with direct_xhs_request_env(), self._api() as api:
            return api.get_note_info(url=url)

    def get_note_comments(self, note_url: str) -> Any:
        with direct_xhs_request_env(), self._api() as api:
            return api.get_note_all_comment(url=note_url)

    def get_user_notes(self, user_url: str) -> Any:
        with direct_xhs_request_env(), self._api() as api:
            return api.get_user_all_notes(user_url=user_url)

    def get_self_info(self) -> Any:
        with direct_xhs_request_env(), self._api() as api:
            success, message, res_json = api.get_user_me()
        payload = (res_json or {}).get("data") if isinstance(res_json, dict) else None
        if not success or not payload:
            raise RuntimeError(message or "XHS self profile refresh failed")
        return payload
