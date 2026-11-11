"""vendor/DouYin_Spider 导入层。

全工程唯一允许 import 上游代码的位置。上游使用仓库根绝对导入
（如 ``from utils.dy_util import ...``），因此先把 vendor 根加入 sys.path。

review P3：这里用 append 而不是 insert(0)——vendor 根含 utils/static/author/tests
等通用顶层名，插到 sys.path 首位会让它们在整个进程中遮蔽工程同名模块
（vendor 升级或新增同名包即静默改变 import 解析）。工程根没有 dy_apis/builder/
dy_live，因此追加到末尾同样能找到上游模块。

所有 import 延迟到首次调用，保证无 vendor 环境（或离线测试）不会在模块导入期失败。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_VENDOR_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "DouYin_Spider"
_lock = threading.Lock()
_bootstrapped = False


def vendor_root() -> Path:
    return _VENDOR_ROOT


def _bootstrap() -> None:
    global _bootstrapped
    with _lock:
        if _bootstrapped:
            return
        if not _VENDOR_ROOT.is_dir():
            raise RuntimeError(
                f"vendor/DouYin_Spider 不存在: {_VENDOR_ROOT}；"
                "请按 vendor/PROVENANCE.md 恢复上游快照"
            )
        if str(_VENDOR_ROOT) not in sys.path:
            sys.path.append(str(_VENDOR_ROOT))
        _bootstrapped = True


def douyin_auth_cls():
    _bootstrap()
    from builder.auth import DouyinAuth  # noqa: PLC0415  上游固定快照，延迟导入

    return DouyinAuth


def douyin_api_cls():
    _bootstrap()
    from dy_apis.douyin_api import DouyinAPI  # noqa: PLC0415

    return DouyinAPI


def douyin_creator_api_cls():
    _bootstrap()
    from dy_apis.douyin_creator_api import DouyinCreatorAPI  # noqa: PLC0415

    return DouyinCreatorAPI


def auth_from_cookie(cookie: str):
    """从完整 Cookie 构造上游 Auth 对象（含 creator 子域初始化）。"""
    return douyin_auth_cls().from_cookie(cookie)


# ---------------------------------------------------------------------------
# 子进程隔离调用（默认启用）
# ---------------------------------------------------------------------------
# DOUYIN_VENDOR_INPROCESS=1 时退回同进程调用（排障/本地调试用）。
# 子进程模式带来两点保证：上游崩溃不拖垮 backend；调用有硬性总时长上限。

import json as _json
import os as _os
import subprocess as _subprocess

from backend.app.douyin.vendor_worker import RESULT_MARKER

# 各操作的默认超时（秒）：采集短、发布长（视频上传可能很慢）
_DEFAULT_TIMEOUTS = {
    "check_account": 45,
    "crawl_work": 90,
    "list_own_works": 300,
    "publish_video": 900,
    "publish_images": 900,
}


class VendorCallTimeout(RuntimeError):
    """子进程调用超时（结果未知，调用方不得盲目重试发布）。"""


class VendorCallFailed(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def call_vendor(op: str, payload: dict, timeout: float | None = None) -> dict:
    """在子进程里执行一次上游调用，返回 result dict。

    失败统一抛 VendorCallFailed(kind=...)，超时抛 VendorCallTimeout。
    """
    if not _VENDOR_ROOT.is_dir():
        raise RuntimeError(
            f"vendor/DouYin_Spider 不存在: {_VENDOR_ROOT}；"
            "请按 vendor/PROVENANCE.md 恢复上游快照"
        )

    limit = timeout if timeout is not None else _DEFAULT_TIMEOUTS.get(op, 120)
    request = _json.dumps({"op": op, "payload": payload}, ensure_ascii=False)

    if (_os.getenv("DOUYIN_VENDOR_INPROCESS", "") or "").strip() in {"1", "true", "yes"}:
        from backend.app.douyin.vendor_worker import dispatch

        return dispatch(op, payload)

    try:
        completed = _subprocess.run(
            [sys.executable, "-m", "backend.app.douyin.vendor_worker"],
            input=request,
            capture_output=True,
            text=True,
            timeout=limit,
            cwd=str(_project_root()),
            env={**_os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except _subprocess.TimeoutExpired as exc:
        raise VendorCallTimeout(
            f"{op} 超时（>{limit}s），上游结果未知"
        ) from exc
    except OSError as exc:
        raise VendorCallFailed("upstream", f"{op} 子进程启动失败: {exc}") from exc

    stdout = completed.stdout or ""
    marker_index = stdout.rfind(RESULT_MARKER)
    if marker_index < 0:
        tail = (completed.stderr or stdout)[-800:]
        raise VendorCallFailed("upstream", f"{op} 子进程无结果输出: {tail}")

    raw = stdout[marker_index + len(RESULT_MARKER):].strip()
    try:
        response = _json.loads(raw.splitlines()[0] if raw.splitlines() else "{}")
    except _json.JSONDecodeError as exc:
        raise VendorCallFailed("upstream", f"{op} 子进程返回非法 JSON: {raw[:200]}") from exc

    if not response.get("ok"):
        raise VendorCallFailed(
            str(response.get("kind") or "upstream"),
            str(response.get("message") or f"{op} 失败"),
        )
    return response.get("result") or {}
