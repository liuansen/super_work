"""后端测试全局夹具。

认证限流是进程内存状态（见 backend/app/core/auth_throttle.py）。整个测试
会话共用同一个 ``testclient`` IP，若不在用例之间重置，累计的登录/注册调用
会触发 429，导致与限流逻辑无关的用例随机失败。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_auth_throttle():
    from backend.app.core import auth_throttle

    auth_throttle.reset_all()

    yield

    auth_throttle.reset_all()
