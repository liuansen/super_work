from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def direct_xhs_request_env() -> Iterator[None]:
    """兼容占位：XHS 传输层已显式忽略环境代理，这里不再改动 os.environ。

    旧实现会持锁删除进程级 HTTP_PROXY/HTTPS_PROXY 等变量，影响所有并发线程
    （FastAPI 线程池 + 调度器线程）里其他依赖环境代理的请求。现在
    ``BrowserHttpClient`` 以 ``trust_env=False`` 创建 Session，不继承环境
    代理；需要使用代理时由调用方显式传 ``proxies``。
    """
    yield None
