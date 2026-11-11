"""在独立进程中执行 vendor/DouYin_Spider 调用。

为什么需要：上游是「整目录快照」形态的第三方代码，此前用 ``sys.path``
同进程 import。上游一旦抛未捕获异常、起线程、改全局状态或阻塞不返回，
都会直接污染 backend 进程（且无法设置总时长上限）。

协议：父进程用 JSON over stdin 传 ``{"op": ..., "payload": {...}}``，
子进程在 stdout 的**最后一行**输出 ``__VENDOR_RESULT__{json}`` 结果。
用标记行而不是整个 stdout，是因为上游会 print。

子进程只做「调用上游 + 原样返回 dict」，所有规范化/校验仍在父进程，
因此 normalize_work 等逻辑可被单元测试直接覆盖。
"""
from __future__ import annotations

import json
import sys
from typing import Any

RESULT_MARKER = "__VENDOR_RESULT__"


def _kind_of(exc: Exception) -> str:
    from backend.app.douyin.contracts import DouyinAuthError, DouyinNetworkError

    if isinstance(exc, DouyinAuthError):
        return "auth"
    if isinstance(exc, DouyinNetworkError):
        return "network"
    text = str(exc).lower()
    if any(m in text for m in ("timeout", "timed out", "connection", "getaddrinfo", "ssl", "proxy")):
        return "network"
    if any(m in text for m in ("cookie", "登录", "uifid", "auth", "unauthorized", "401", "403")):
        return "auth"
    return "upstream"


def dispatch(op: str, payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次上游调用，返回可 JSON 序列化的 dict。"""
    from backend.app.douyin import upstream

    if op == "check_account":
        api = upstream.douyin_api_cls()
        auth = upstream.auth_from_cookie(payload["cookie"])
        sec_uid = api.get_my_sec_uid(auth)
        if not sec_uid:
            from backend.app.douyin.contracts import DouyinAuthError

            raise DouyinAuthError("身份确认：上游未返回 sec_uid，Cookie 可能已失效")
        info = api.get_user_info(auth, f"https://www.douyin.com/user/{sec_uid}")
        return {"sec_uid": str(sec_uid), "info": info if isinstance(info, dict) else {}}

    if op == "crawl_work":
        api = upstream.douyin_api_cls()
        auth = upstream.auth_from_cookie(payload["cookie"])
        return {"raw": api.get_work_info(auth, payload["url"])}

    if op == "list_own_works":
        api = upstream.douyin_api_cls()
        auth = upstream.auth_from_cookie(payload["cookie"])
        user_url = f"https://www.douyin.com/user/{payload['sec_uid']}"
        cursor = "0"
        collected: list[dict[str, Any]] = []
        for _ in range(max(1, int(payload.get("max_pages") or 1))):
            page = api.get_user_work_info(auth, user_url, cursor)
            items = page.get("aweme_list") if isinstance(page, dict) else None
            if isinstance(items, list):
                collected.extend(item for item in items if isinstance(item, dict))
            if not isinstance(page, dict) or page.get("has_more") != 1:
                break
            cursor = str(page.get("max_cursor") or "0")
        return {"items": collected}

    if op == "publish_video":
        creator = upstream.douyin_creator_api_cls()
        auth = upstream.auth_from_cookie(payload["cookie"])
        ok, message, result = creator.post_video(
            auth,
            payload["path"],
            title=payload.get("title", ""),
            desc=payload.get("desc", ""),
            visibility=int(payload.get("visibility", 0)),
            allow_download=bool(payload.get("allow_download")),
            timing=payload.get("timing"),
        )
        return {"ok": bool(ok), "message": str(message or ""), "result": result if isinstance(result, dict) else {}}

    if op == "publish_images":
        creator = upstream.douyin_creator_api_cls()
        auth = upstream.auth_from_cookie(payload["cookie"])
        ok, message, result = creator.post_images(
            auth,
            list(payload.get("paths") or []),
            title=payload.get("title", ""),
            desc=payload.get("desc", ""),
            visibility=int(payload.get("visibility", 0)),
            allow_download=bool(payload.get("allow_download")),
            timing=payload.get("timing"),
        )
        return {"ok": bool(ok), "message": str(message or ""), "result": result if isinstance(result, dict) else {}}

    raise ValueError(f"未知 vendor 操作: {op}")


def main() -> int:
    try:
        request = json.load(sys.stdin)
        result = dispatch(request.get("op", ""), request.get("payload") or {})
        response = {"ok": True, "result": result}
    except Exception as exc:  # 任何上游异常都翻译成结构化结果，不污染父进程
        response = {"ok": False, "kind": _kind_of(exc), "message": str(exc)[:2000]}
    # 上游可能污染 stdout：结果固定放在最后一行并带标记
    sys.stdout.write("\n" + RESULT_MARKER + json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
