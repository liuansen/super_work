"""只对 /api/clip/* 生效的 CORS。

工作台主站继续使用原有 backend_cors_origins，不为编辑器扩大权限。
编辑器使用 Authorization 头，不使用 Cookie，因此不返回
Access-Control-Allow-Credentials。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CLIP_PATH_PREFIX = "/api/clip/"


class ClipCorsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = {origin for origin in allowed_origins if origin}

    def _headers(self, origin: str) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
        }

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        if not request.url.path.startswith(CLIP_PATH_PREFIX) or origin not in self.allowed_origins:
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=self._headers(origin))
        response = await call_next(request)
        # 显式移除内层全局 CORS 可能加上的 credentials 头：
        # 编辑器用 Authorization 头而非 Cookie，契约要求不带 credentials
        response.headers.pop("access-control-allow-credentials", None)
        for key, value in self._headers(origin).items():
            if key == "Vary":
                # 合并而非覆盖，保留路由已设置的 Vary（如 Accept-Encoding）
                existing = response.headers.get(key)
                response.headers[key] = f"{existing}, {value}" if existing else value
            else:
                response.headers[key] = value
        return response
