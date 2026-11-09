"""vendor/DouYin_Spider 导入层。

全工程唯一允许 import 上游代码的位置。上游使用仓库根绝对导入
（如 ``from utils.dy_util import ...``），因此先把 vendor 根加入 sys.path；
vendor 根必须排在 sys.path 首位，保证 vendor 自带的 utils/static 命名空间
不被工程根的同名目录遮蔽（已核实 backend 进程不 import 工程根的 utils/apis/author）。

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
            sys.path.insert(0, str(_VENDOR_ROOT))
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
