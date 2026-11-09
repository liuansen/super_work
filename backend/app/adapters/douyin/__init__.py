"""抖音适配器入口。

环境变量 DOUYIN_ADAPTER=real|fake 选择实现，默认 real。
测试通过依赖注入直接使用 FakeDouyinAdapter，不触发网络。
"""
from __future__ import annotations

import os

from backend.app.douyin.contracts import DouyinAdapter
from backend.app.adapters.douyin.fake import FakeDouyinAdapter
from backend.app.adapters.douyin.real import RealDouyinAdapter

_ADAPTERS = {"real": RealDouyinAdapter, "fake": FakeDouyinAdapter}


def get_adapter() -> DouyinAdapter:
    name = os.getenv("DOUYIN_ADAPTER", "real").strip().lower()
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"未知 DOUYIN_ADAPTER: {name}（可选 real|fake）")
    return cls()


__all__ = ["get_adapter", "FakeDouyinAdapter", "RealDouyinAdapter"]
