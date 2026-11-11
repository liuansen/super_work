from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.app.api import accounts, ai, auth, auto_tasks, clip, drafts, files, keyword_groups, login_sessions, model_configs, notes, notifications, publish, tags, tasks
from backend.app.api.apps import router as apps_router
from backend.app.api.platforms import registry
from backend.app.api.platforms.douyin import router as douyin_router
from backend.app.api.platforms.xhs import analytics, crawl, creator, monitoring, pc
from backend.app.core.config import get_settings
from backend.app.core.database import get_db, init_db
from backend.app.services.scheduler_service import (
    reconcile_stale_publish_jobs,
    shutdown_due_publish_scheduler,
    start_due_publish_scheduler,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 安全断言先行：生产环境使用占位密钥时直接拒绝启动（见 SEC-1）
    get_settings().assert_runtime_safety()
    # 复核 P3：DOUYIN_ADAPTER=fake 在生产会被拒绝，此前只在首个请求时
    # 报 500；启动期前置断言，把误配提前暴露为启动失败。
    if get_settings().environment == "production":
        from backend.app.adapters.douyin import get_adapter

        get_adapter()
    init_db()
    # 日志配置放在迁移之后：避免 alembic 的 logging 配置覆盖应用日志设置
    # （LOG_JSON=1 输出 JSON 行，所有日志自动带 request_id）
    from backend.app.core.observability import configure_logging

    configure_logging()
    # 检索索引：SQLite 上幂等创建 FTS5（不可用时自动回退 LIKE）
    from backend.app.services.note_search import ensure_fts_index

    ensure_fts_index()
    # 启动对账：把进程崩溃/重启时滞留在中间态的任务复位，避免永久卡死
    reconcile_stale_publish_jobs()
    from backend.app.douyin.publishing import reconcile_stale_tasks

    reconcile_stale_tasks()
    settings = get_settings()
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = start_due_publish_scheduler(settings.scheduler_interval_seconds)
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        shutdown_due_publish_scheduler(scheduler)
        # 长任务线程池：优雅退出（等待排队任务完成）
        from backend.app.services import job_runner

        job_runner.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, lifespan=lifespan)

    origins = [origin.strip() for origin in settings.backend_cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 剪辑工坊作用域 CORS：只对 /api/clip/* 生效，编辑器用 Authorization 头
    from backend.app.core.clip_cors import ClipCorsMiddleware

    clip_origins = [o.strip() for o in settings.clip_editor_allowed_origins.split(",") if o.strip()]
    app.add_middleware(ClipCorsMiddleware, allowed_origins=clip_origins)

    # 可观测性：请求 ID（日志串联）+ 指标累计。放在 CORS 之后注册，
    # 中间件按注册逆序执行，保证响应头一定被补上。
    from backend.app.core import metrics as app_metrics
    from backend.app.core.observability import (
        REQUEST_ID_HEADER,
        new_request_id,
        request_id_var,
    )

    access_logger = logging.getLogger("backend.app.access")

    @app.middleware("http")
    async def _observability(request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        token = request_id_var.set(request_id)
        app_metrics.inc_inflight()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            app_metrics.dec_inflight()
            # 路由模板（/notes/{id}）而非原始路径，避免指标维度爆炸
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            app_metrics.record_request(request.method, status_code, route, duration)
            # 自带访问日志：uvicorn 的 access log 在中间件之后由协议层输出，
            # 拿不到本请求的 request_id；这里补一条可关联的结构化访问日志。
            access_logger.info(
                "%s %s -> %s %.1fms",
                request.method,
                request.url.path,
                status_code,
                duration * 1000,
            )
            request_id_var.reset(token)

    @app.get("/api/metrics", tags=["health"], include_in_schema=False)
    def metrics_endpoint() -> Response:
        """Prometheus 文本格式指标（零依赖实现，见 core/metrics.py）。"""
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(
            app_metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "spider-xhs"}

    @app.get("/api/health/ready", tags=["health"])
    def health_ready(db: Session = Depends(get_db)) -> dict:
        """INF-3：readiness 探测——数据库可达（SELECT 1）+ 迁移表存在。

        liveness（/api/health）只表示进程存活；Docker/compose 的
        healthcheck 应使用本端点，数据库不可用时容器标记为 unready。
        """
        from sqlalchemy import inspect as sa_inspect, text

        try:
            db.execute(text("SELECT 1"))
            migrated = "alembic_version" in sa_inspect(db.bind).get_table_names()
        except Exception as exc:
            # review P3：未认证端点不回显数据库异常原文（可能含主机/端口/路径等拓扑信息）
            logger.exception("readiness check failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not ready",
            ) from exc
        return {"status": "ready", "database": "ok", "migrated": migrated}

    app.include_router(registry.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(login_sessions.router, prefix="/api")
    app.include_router(notes.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(drafts.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    app.include_router(model_configs.router, prefix="/api")
    app.include_router(tags.router, prefix="/api")
    app.include_router(notifications.router, prefix="/api")
    app.include_router(keyword_groups.router, prefix="/api")
    app.include_router(publish.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(pc.router, prefix="/api")
    app.include_router(creator.router, prefix="/api")
    app.include_router(crawl.router, prefix="/api")
    app.include_router(monitoring.router, prefix="/api")
    app.include_router(auto_tasks.router, prefix="/api")
    app.include_router(clip.router, prefix="/api")
    app.include_router(apps_router, prefix="/api")
    app.include_router(douyin_router, prefix="/api")

    # Serve pre-built frontend in production / Docker
    if settings.frontend_serve_static:
        frontend_dist = Path(settings.frontend_build_dir)
        if frontend_dist.is_dir():
            from starlette.responses import FileResponse

            # Serve index.html for SPA client-side routing (non-API, non-file paths)
            @app.middleware("http")
            async def _spa_fallback(request, call_next):
                response = await call_next(request)
                path = request.url.path
                if (
                    response.status_code == 404
                    and not path.startswith("/api")
                    and "." not in path.split("/")[-1]
                ):
                    return FileResponse(str(frontend_dist / "index.html"))
                return response

            app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
