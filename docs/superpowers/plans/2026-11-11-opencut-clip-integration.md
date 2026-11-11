# 剪辑工坊（OpenCut）工作台侧实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在工作台内落地「剪辑工坊」：素材选择、一次性令牌进入独立编辑器、成片回传、成片送入小红书草稿或抖音发布中心。

**Architecture:** FastAPI 新增 `/api/clip/*`，用一次性握手令牌和短期会话令牌把素材下发给独立编辑器，再接收导出的 MP4。前端新增 `/clip` 单页应用，通过应用注册和两个工作台菜单进入。编辑器先由本地契约 stub 容器承载，OpenCut fork 完成后替换同一镜像入口，工作台接口不变。

**Tech Stack:** Python 3.10+、FastAPI、SQLAlchemy 2.0、Alembic、SQLite/MySQL；React 19、TypeScript、Vite、Ant Design 6、React Router 7；Docker Compose。

## Global Constraints

- 当前项目位置：`E:/code/super_work`。所有路径相对于项目根目录。
- 延续现有技术栈与目录约定，不引入新的前端框架、状态库、UI 库或后端服务框架。
- 现有小红书、抖音业务页面、接口、数据范围、调度行为不得改变；只增加剪辑入口和发布素材前缀兼容。
- 所有用户可见文案使用中文；错误信息必须可读，不返回服务器绝对路径或令牌。
- 所有工作台接口必须鉴权。素材与成片必须按用户隔离，文件名必须带 `xhs-*-u{user_id}-` 归属前缀。
- 成片文件前缀固定为 `xhs-clip-u{user_id}-`，扩展名首期固定 `.mp4`。
- 普通上传的 100MB 上限不变；成片上传使用独立上限 `CLIP_MAX_EXPORT_BYTES`，默认 2GiB。
- 握手令牌 5 分钟、一次性；会话令牌默认 12 小时、仅限单次会话。
- 令牌只能通过 URL fragment 传给编辑器，不得出现在查询参数、日志或错误信息中。
- 不新增前端依赖；不引入 iframe 内嵌，编辑器在新标签页打开。
- **提交策略：** 本项目用户在 2026-11-09 明确要求 super-workbench 工作不执行 `git init`、不提交、不创建 PR。本计划每个任务以「检查点：运行相关测试并记录结果」结束，不包含 `git commit`。若执行时用户明确授权提交，再按任务标题补提交。
- **计划范围：** 本计划覆盖 M0 能力验证与工作台侧（Plan A）。OpenCut fork 的真实补丁（Plan B）在 M0 决策为 GO 后，依据 `docs/superpowers/verification/opencut/decision.md` 和实际源码结构单独编写。本计划用 `tools/clip-editor-stub` 实现同一编辑器契约，使工作台侧可以独立开发、测试和验收。

---

## File Structure

### 后端

| 文件 | 责任 |
| --- | --- |
| `backend/app/models/clip.py` | `ClipSession`、`ClipExport` 两个 ORM 模型 |
| `backend/app/clip/schemas.py` | 请求/响应 Pydantic 模型 |
| `backend/app/clip/assets.py` | 素材目录查询与选择解析 |
| `backend/app/clip/sessions.py` | 会话创建、令牌交换、会话素材读取 |
| `backend/app/clip/exports.py` | 成片上传、幂等、配额、列表、删除、草稿对接 |
| `backend/app/clip/cleanup.py` | 过期会话与临时文件清理 |
| `backend/app/api/clip.py` | `/api/clip/*` 路由 |
| `backend/app/core/clip_cors.py` | 只作用于 `/api/clip/*` 的 CORS 中间件 |
| `backend/alembic/versions/a9c1e2f3b4d5_add_clip_tables.py` | 建表迁移 |
| `tests/backend/test_clip_*.py` | 后端测试 |

### 前端

| 文件 | 责任 |
| --- | --- |
| `frontend/src/features/clip/types.ts` | 剪辑工坊类型 |
| `frontend/src/features/clip/api.ts` | 剪辑工坊 API 客户端 |
| `frontend/src/features/clip/session-url.ts` | 生成带 fragment 令牌的编辑器地址 |
| `frontend/src/features/clip/asset-selection.ts` | 素材选择纯函数 |
| `frontend/src/features/clip/components/asset-picker.tsx` | 素材选择弹窗 |
| `frontend/src/features/clip/components/export-list.tsx` | 成片列表与操作 |
| `frontend/src/features/clip/clip-page.tsx` | `/clip` 页面 |
| `frontend/src/features/douyin/preselect.ts` | 抖音发布预选参数解析 |
| `frontend/tests/clip-workbench.test.cjs` | 前端接线测试 |
| `frontend/src/features/clip/session-url.test.ts` | 编辑器地址单元测试 |

### 验证与部署

| 文件 | 责任 |
| --- | --- |
| `tools/clip-editor-stub/index.html` | 契约测试编辑器 |
| `tools/clip-editor-stub/Dockerfile` | stub 容器镜像 |
| `docs/superpowers/verification/opencut/` | M0 证据与验收记录 |
| `docker-compose.yml` | 新增 `editor` 服务 |
| `.env.example` / `README.md` | 配置与部署说明 |

---

## Task 1: M0 OpenCut 能力验证（闸门）

**Files:**
- Create: `docs/superpowers/verification/opencut/source-review.md`
- Create: `docs/superpowers/verification/opencut/capability-report.json`
- Create: `docs/superpowers/verification/opencut/decision.md`
- Create: `docs/superpowers/verification/opencut/evidence/runtime-deps.md`
- Create: `docs/superpowers/verification/opencut/evidence/known-limits.md`

**Interfaces:**
- Consumes: 无。
- Produces: `decision.md` 中的结论 `GO` 或 `NO-GO`、固定提交号、运行方式、可用导入/导出挂载点、编辑器公共地址；后续任务只在 `GO` 时执行。

- [ ] **Step 1: 克隆并固定上游版本**

```bash
mkdir -p .local/opencut-validation
cd .local/opencut-validation
git clone --depth 1 https://github.com/OpenCut-app/OpenCut.git
cd OpenCut
git rev-parse HEAD
```

把输出的 40 位提交号写入 `docs/superpowers/verification/opencut/source-review.md` 的「固定提交」一节。

- [ ] **Step 2: 记录许可证与使用限制**

```bash
cd .local/opencut-validation/OpenCut
find . -maxdepth 3 \( -iname "LICENSE*" -o -iname "COPYING*" \) -type f
cat LICENSE 2>/dev/null || true
```

把许可证名称、原文链接、允许/禁止的使用范围逐条写入 `source-review.md`。若许可证不允许当前使用方式，直接写 `NO-GO` 并停止后续任务。

- [ ] **Step 3: 记录运行环境与构建方式**

```bash
cd .local/opencut-validation/OpenCut
ls
cat package.json
find . -maxdepth 3 -name "package.json" -not -path "*/node_modules/*"
find . -maxdepth 2 \( -name "Dockerfile*" -o -name "compose*.yml" -o -name "README*" \)
```

把包管理器、Node/Bun 版本要求、构建命令、启动命令、默认端口写入 `evidence/runtime-deps.md`。不要根据记忆填写，以文件内容为准。

- [ ] **Step 4: 启动并验证五项首期能力**

按上一步记录的命令启动编辑器，用桌面浏览器逐项验证并截图/录屏保存到 `evidence/`：

1. 多段视频/图片拼接；
2. 裁剪首尾；
3. 背景音乐；
4. 字幕/标题；
5. 封面帧；
6. 导出 MP4。

把每项的「通过/不通过、操作路径、截图文件名」写入 `capability-report.json`。任一项不通过时，在该文件写明缩减范围或替代方案。

- [ ] **Step 5: 验证工作台桥接所需的扩展点**

在源码中定位并记录：

```bash
cd .local/opencut-validation/OpenCut
grep -RIn "export" --include="*.ts" --include="*.tsx" . | grep -iE "render|download|ffmpeg|export" | head -80
grep -RIn "import" --include="*.ts" --include="*.tsx" . | grep -iE "media|file|asset|upload" | head -80
grep -RIn "indexedDB\|OPFS\|storage" --include="*.ts" --include="*.tsx" . | head -40
```

把结论写入 `source-review.md`：

- 素材导入函数名与文件路径；
- 导出完成回调函数名与文件路径；
- 是否支持在请求中附加 `Authorization` 头；
- 本地存储类型与容量限制；
- 新标签页访问是否有登录/来源限制。

- [ ] **Step 6: 写决策记录**

`decision.md` 必须包含以下四节，且没有空项：

```markdown
# OpenCut 接入决策

- 固定提交：<40 位哈希>
- 许可证：<名称与结论>
- 运行方式：<命令与端口>
- 决策：GO / NO-GO

## 五项能力
<逐项结论>

## 桥接可行性
<导入、导出、Authorization、CORS/Range、存储>

## 后续
GO：按本计划 Task 2 继续，并另行编写 fork 补丁计划。
NO-GO：停止，重新评审自研轻剪辑器方案。
```

- [ ] **Step 7: 检查点**

Run: `cat docs/superpowers/verification/opencut/decision.md`

Expected: 包含 `决策：GO` 或 `决策：NO-GO`，且没有 `<...>` 占位符。`NO-GO` 时停止，不执行后续任务。

---

## Task 2: 剪辑配置、作用域 CORS 与路由骨架

**Files:**
- Modify: `backend/app/core/config.py:149-220`
- Modify: `.env.example`
- Create: `backend/app/core/clip_cors.py`
- Create: `backend/app/api/clip.py`
- Modify: `backend/app/main.py:20-30, 155-180`
- Test: `tests/backend/test_clip_cors.py`

**Interfaces:**
- Consumes: 无。
- Produces: `Settings.clip_editor_public_base_url`、`clip_editor_allowed_origins`、`clip_max_export_bytes`、`clip_session_ttl_hours`、`clip_max_active_sessions`、`clip_user_export_quota_bytes`；`GET /api/clip/health`；只对 `/api/clip/*` 生效的 CORS。

- [ ] **Step 1: 写失败的 CORS 与健康检查测试**

Create `tests/backend/test_clip_cors.py`:

```python
from api_helpers import *  # noqa: F401,F403

CLIP_ORIGIN = "http://127.0.0.1:3000"


def test_clip_preflight_allows_editor_origin():
    response = client.options(
        "/api/clip/sessions",
        headers={
            "Origin": CLIP_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == CLIP_ORIGIN
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_clip_cors_does_not_leak_to_other_paths():
    response = client.get("/api/health", headers={"Origin": CLIP_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_clip_health_requires_login(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        assert client.get("/api/clip/health").status_code == 401
        token = _register_and_get_access_token("clip-health")
        response = client.get("/api/clip/health", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_cors.py -v`

Expected: FAIL，`/api/clip/health` 返回 404，CORS 头不存在。

- [ ] **Step 3: 增加设置项**

在 `backend/app/core/config.py` 的 `Settings` 中、`frontend_build_dir` 之后加入：

```python
    # Clip studio (OpenCut)
    clip_editor_public_base_url: str = "http://127.0.0.1:3000"
    clip_editor_allowed_origins: str = "http://127.0.0.1:3000"
    clip_max_export_bytes: int = 2 * 1024 * 1024 * 1024
    clip_session_ttl_hours: int = 12
    clip_max_active_sessions: int = 3
    clip_user_export_quota_bytes: int = 10 * 1024 * 1024 * 1024
```

在 `.env.example` 末尾加入：

```bash
# 剪辑工坊（OpenCut）
CLIP_EDITOR_PUBLIC_BASE_URL=http://127.0.0.1:3000
CLIP_EDITOR_ALLOWED_ORIGINS=http://127.0.0.1:3000
CLIP_MAX_EXPORT_BYTES=2147483648
CLIP_SESSION_TTL_HOURS=12
CLIP_MAX_ACTIVE_SESSIONS=3
CLIP_USER_EXPORT_QUOTA_BYTES=10737418240
```

- [ ] **Step 4: 实现作用域 CORS 中间件**

Create `backend/app/core/clip_cors.py`:

```python
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
        for key, value in self._headers(origin).items():
            response.headers[key] = value
        return response
```

- [ ] **Step 5: 增加路由骨架并注册中间件**

Create `backend/app/api/clip.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.core.deps import get_current_user
from backend.app.models import User

router = APIRouter(prefix="/clip", tags=["clip"])


@router.get("/health")
def clip_health(current_user: User = Depends(get_current_user)):
    return {"status": "ok", "user_id": current_user.id}
```

在 `backend/app/main.py` 的 API import 行加入 `clip`：

```python
from backend.app.api import accounts, ai, auth, auto_tasks, clip, drafts, files, keyword_groups, login_sessions, model_configs, notes, notifications, publish, tags, tasks
```

在 `create_app()` 中、现有 CORS 中间件之后加入：

```python
    from backend.app.core.clip_cors import ClipCorsMiddleware

    clip_origins = [o.strip() for o in settings.clip_editor_allowed_origins.split(",") if o.strip()]
    app.add_middleware(ClipCorsMiddleware, allowed_origins=clip_origins)
```

在 `include_router` 列表中加入：

```python
    app.include_router(clip.router, prefix="/api")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_cors.py -v`

Expected: 3 passed。

- [ ] **Step 7: 检查点**

Run: `python -m pytest tests/backend/test_api_smoke.py tests/backend/test_clip_cors.py -v`

Expected: 全部通过。

---

## Task 3: 剪辑数据模型与迁移

**Files:**
- Create: `backend/app/models/clip.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/a9c1e2f3b4d5_add_clip_tables.py`
- Test: `tests/backend/test_clip_migrations.py`

**Interfaces:**
- Consumes: 现有 `Base`、`shanghai_now`、`f6a7b8c9d0e1` 迁移头。
- Produces: `ClipSession`（`id, user_id, title, manifest_json, status, handoff_jti, handoff_expires_at, session_expires_at, exchanged_at, created_at`）与 `ClipExport`（`id, user_id, session_id, title, file_name, mime, size_bytes, duration_ms, status, linked_draft_id, client_export_id, created_at`）。

- [ ] **Step 1: 写失败的迁移测试**

Create `tests/backend/test_clip_migrations.py`:

```python
"""剪辑工坊迁移：真实 Alembic upgrade 建出两张表。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _run_upgrade(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "clip-migration.db"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path}")
    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    return db_path


def test_upgrade_creates_clip_tables(tmp_path, monkeypatch):
    db_path = _run_upgrade(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"clip_sessions", "clip_exports"} <= tables
    engine.dispose()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_migrations.py -v`

Expected: FAIL，表不存在。

- [ ] **Step 3: 定义模型**

Create `backend/app/models/clip.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class ClipSession(Base):
    __tablename__ = "clip_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    manifest_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True)
    handoff_jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    handoff_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    session_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exchanged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class ClipExport(Base):
    __tablename__ = "clip_exports"
    __table_args__ = (
        UniqueConstraint("session_id", "client_export_id", name="uq_clip_exports_session_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("clip_sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    file_name: Mapped[str] = mapped_column(String(180), unique=True)
    mime: Mapped[str] = mapped_column(String(64), default="video/mp4")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="available")
    linked_draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_drafts.id"), nullable=True)
    client_export_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
```

在 `backend/app/models/__init__.py` 加入导入与 `__all__`：

```python
from backend.app.models.clip import ClipExport, ClipSession
```

```python
    "ClipExport",
    "ClipSession",
```

- [ ] **Step 4: 写迁移**

Create `backend/alembic/versions/a9c1e2f3b4d5_add_clip_tables.py`:

```python
"""add clip_sessions and clip_exports

Revision ID: a9c1e2f3b4d5
Revises: f6a7b8c9d0e1
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e2f3b4d5"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clip_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("manifest_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="issued"),
        sa.Column("handoff_jti", sa.String(length=64), nullable=False),
        sa.Column("handoff_expires_at", sa.DateTime(), nullable=False),
        sa.Column("session_expires_at", sa.DateTime(), nullable=True),
        sa.Column("exchanged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_clip_sessions_user_id", "clip_sessions", ["user_id"])
    op.create_index("ix_clip_sessions_status", "clip_sessions", ["status"])
    op.create_index("ix_clip_sessions_handoff_jti", "clip_sessions", ["handoff_jti"], unique=True)
    op.create_index("ix_clip_sessions_handoff_expires_at", "clip_sessions", ["handoff_expires_at"])

    op.create_table(
        "clip_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("clip_sessions.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(length=180), nullable=False, unique=True),
        sa.Column("mime", sa.String(length=64), nullable=False, server_default="video/mp4"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
        sa.Column("linked_draft_id", sa.Integer(), sa.ForeignKey("ai_drafts.id"), nullable=True),
        sa.Column("client_export_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "client_export_id", name="uq_clip_exports_session_client"),
    )
    op.create_index("ix_clip_exports_user_id", "clip_exports", ["user_id"])
    op.create_index("ix_clip_exports_session_id", "clip_exports", ["session_id"])


def downgrade() -> None:
    op.drop_table("clip_exports")
    op.drop_table("clip_sessions")
```

- [ ] **Step 5: 运行迁移测试确认通过**

Run: `python -m pytest tests/backend/test_clip_migrations.py -v`

Expected: 1 passed。

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/douyin/test_migrations.py tests/backend/test_clip_migrations.py -v`

Expected: 全部通过，旧迁移链未被破坏。

---

## Task 4: 剪辑令牌助手

**Files:**
- Modify: `backend/app/core/security.py:84-91`
- Test: `tests/backend/test_clip_tokens.py`

**Interfaces:**
- Consumes: 现有 `_sign_token`、`decode_token`、`get_settings().secret_key`。
- Produces: `create_clip_handoff_token(user_id, session_id, jti, ttl_minutes=5)`、`create_clip_session_token(user_id, session_id, ttl_hours)`、`decode_clip_token(token, expected_type)`。

- [ ] **Step 1: 写失败的令牌测试**

Create `tests/backend/test_clip_tokens.py`:

```python
import pytest
from fastapi import HTTPException

from backend.app.core.security import (
    create_clip_handoff_token,
    create_clip_session_token,
    decode_clip_token,
)


def test_handoff_token_roundtrip_and_scope():
    token = create_clip_handoff_token(7, 42, "jti-1")
    payload = decode_clip_token(token, "clip_handoff")
    assert payload["user_id"] == 7
    assert payload["session_id"] == 42
    assert payload["jti"] == "jti-1"
    with pytest.raises(HTTPException):
        decode_clip_token(token, "clip_session")


def test_session_token_carries_session_id_and_expires():
    token = create_clip_session_token(7, 42, ttl_hours=-1)
    with pytest.raises(HTTPException):
        decode_clip_token(token, "clip_session")


def test_tampered_token_rejected():
    token = create_clip_handoff_token(7, 42, "jti-1")
    with pytest.raises(HTTPException):
        decode_clip_token(token + "x", "clip_handoff")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_tokens.py -v`

Expected: FAIL，`ImportError` 或函数不存在。

- [ ] **Step 3: 实现令牌助手**

在 `backend/app/core/security.py` 的 `create_media_token` 之后加入：

```python
def create_clip_handoff_token(
    user_id: int, session_id: int, jti: str, ttl_minutes: int = 5
) -> str:
    """剪辑会话的一次性握手令牌，只能用于交换会话令牌。"""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    return _sign_token(
        {
            "user_id": user_id,
            "token_type": "clip_handoff",
            "session_id": int(session_id),
            "jti": jti,
            "exp": int(expires_at.timestamp()),
        }
    )


def create_clip_session_token(user_id: int, session_id: int, ttl_hours: int) -> str:
    """剪辑会话令牌，只能访问该会话的素材和成片上传接口。"""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    return _sign_token(
        {
            "user_id": user_id,
            "token_type": "clip_session",
            "session_id": int(session_id),
            "exp": int(expires_at.timestamp()),
        }
    )


def decode_clip_token(token: str, expected_type: str) -> dict:
    payload = decode_token(token)
    if payload.get("token_type") != expected_type or not isinstance(payload.get("session_id"), int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid clip token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_tokens.py -v`

Expected: 3 passed。

- [ ] **Step 5: 检查点**

Run: `python -m pytest tests/backend/test_api_auth.py tests/backend/test_clip_tokens.py -v`

Expected: 全部通过，现有认证未回归。

---

## Task 5: 素材目录与选择解析

**Files:**
- Create: `backend/app/clip/__init__.py`
- Create: `backend/app/clip/schemas.py`
- Create: `backend/app/clip/assets.py`
- Modify: `backend/app/api/clip.py`
- Test: `tests/backend/test_clip_assets.py`

**Interfaces:**
- Consumes: `NoteAsset`、`Note`、`DraftAsset`、`AiDraft`、`assert_owned_media_name`、`media_dir()`。
- Produces: `list_clip_assets(db, user_id, q, asset_type, source, limit) -> list[dict]`；`resolve_clip_asset(db, user_id, kind, ref_id, file_name) -> tuple[str, int]`；`GET /api/clip/assets`。

- [ ] **Step 1: 写失败的素材目录测试**

Create `tests/backend/test_clip_assets.py`:

```python
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from api_helpers import *  # noqa: F401,F403


def _write_media(name: str, content: bytes) -> None:
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(content)


def test_asset_catalog_lists_owned_sources_and_filters(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        token = _register_and_get_access_token("clip-assets-owner")
        from backend.app.core.security import decode_token
        from backend.app.core.database import get_db
        from backend.app.models import AiDraft, DraftAsset, Note, NoteAsset

        user_id = decode_token(token)["user_id"]
        upload_name = _owned_media_fixture(token)
        note_name = f"xhs-asset-u{user_id}-{uuid4().hex}.mp4"
        draft_name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
        _write_media(note_name, b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        _write_media(draft_name, b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        db = next(app.dependency_overrides[get_db]())
        try:
            note = Note(user_id=user_id, platform="xhs", note_id="note-1", title="参考笔记")
            db.add(note)
            db.flush()
            db.add(NoteAsset(note_id=note.id, asset_type="video", url="", local_path=note_name))
            draft = AiDraft(user_id=user_id, platform="xhs", title="草稿一")
            db.add(draft)
            db.flush()
            db.add(DraftAsset(draft_id=draft.id, asset_type="video", local_path=draft_name, sort_order=0))
            db.commit()
        finally:
            db.close()

        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/clip/assets", headers=headers)
        assert response.status_code == 200
        items = response.json()["items"]
        assert {item["source"] for item in items} == {"note", "draft", "upload"}
        assert {item["file_name"] for item in items} == {upload_name, note_name, draft_name}
        assert all(item["preview_url"].startswith("/api/files/media/") for item in items)

        video = client.get("/api/clip/assets?type=video&source=note", headers=headers).json()["items"]
        assert [item["file_name"] for item in video] == [note_name]

        searched = client.get("/api/clip/assets?q=参考", headers=headers).json()["items"]
        assert [item["file_name"] for item in searched] == [note_name]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for name in (upload_name, note_name, draft_name):
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_asset_catalog_isolated_between_users(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        owner = _register_and_get_access_token("clip-assets-user-a")
        other = _register_and_get_access_token("clip-assets-user-b")
        _owned_media_fixture(owner)
        response = client.get("/api/clip/assets", headers={"Authorization": f"Bearer {other}"})
        assert response.status_code == 200
        assert response.json()["items"] == []
    finally:
        app.dependency_overrides.pop(db_dependency, None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_assets.py -v`

Expected: FAIL，`/api/clip/assets` 返回 404。

- [ ] **Step 3: 定义请求模型**

Create `backend/app/clip/__init__.py`:

```python
"""剪辑工坊服务层。"""
```

Create `backend/app/clip/schemas.py`:

```python
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClipAssetSelection(BaseModel):
    kind: Literal["note_asset", "draft_asset", "upload"]
    id: Optional[int] = None
    file_name: Optional[str] = None


class ClipSessionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    assets: list[ClipAssetSelection] = Field(min_length=1, max_length=50)
```

- [ ] **Step 4: 实现素材目录与解析**

Create `backend/app/clip/assets.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.media_source import InvalidMediaSource, assert_owned_media_name
from backend.app.core.media_storage import media_dir
from backend.app.models import AiDraft, DraftAsset, Note, NoteAsset

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac"}


def asset_type_for(name: str) -> Optional[str]:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def _existing_owned(name: str, user_id: int) -> Optional[tuple[str, int]]:
    try:
        assert_owned_media_name(name, user_id)
    except InvalidMediaSource:
        return None
    path = media_dir() / name
    if not path.is_file():
        return None
    return name, path.stat().st_size


def list_clip_assets(
    db: Session,
    user_id: int,
    *,
    q: str = "",
    asset_type: str = "",
    source: str = "",
    limit: int = 200,
) -> list[dict]:
    needle = q.strip().lower()
    limit = max(1, min(int(limit), 200))
    items: dict[str, dict] = {}

    def add(name: str, kind: str, ref_id: str, title: str) -> None:
        checked = _existing_owned(name, user_id)
        if checked is None or name in items:
            return
        detected = asset_type_for(name)
        if detected is None:
            return
        if asset_type and detected != asset_type:
            return
        display = (title or name).strip()
        if needle and needle not in display.lower() and needle not in name.lower():
            return
        items[name] = {
            "id": f"{kind}:{ref_id}",
            "kind": kind,
            "ref_id": ref_id,
            "file_name": name,
            "asset_type": detected,
            "source": "note" if kind == "note_asset" else "draft" if kind == "draft_asset" else "upload",
            "title": display,
            "size_bytes": checked[1],
            "preview_url": f"/api/files/media/{name}",
        }

    if source in ("", "note"):
        rows = db.execute(
            select(NoteAsset, Note)
            .join(Note, Note.id == NoteAsset.note_id)
            .where(Note.user_id == user_id)
            .order_by(NoteAsset.id.desc())
        ).all()
        for asset, note in rows:
            add(Path(asset.local_path or "").name, "note_asset", str(asset.id), note.title)

    if source in ("", "draft"):
        rows = db.execute(
            select(DraftAsset, AiDraft)
            .join(AiDraft, AiDraft.id == DraftAsset.draft_id)
            .where(AiDraft.user_id == user_id)
            .order_by(DraftAsset.id.desc())
        ).all()
        for asset, draft in rows:
            add(Path(asset.local_path or "").name, "draft_asset", str(asset.id), draft.title)

    if source in ("", "upload"):
        directory = media_dir()
        if directory.is_dir():
            prefixes = (f"xhs-upload-u{user_id}-", f"xhs-image-u{user_id}-")
            for path in directory.iterdir():
                if path.is_file() and path.name.startswith(prefixes):
                    add(path.name, "upload", path.name, "")

    return list(items.values())[:limit]


def resolve_clip_asset(
    db: Session,
    user_id: int,
    *,
    kind: str,
    ref_id: Optional[int] = None,
    file_name: Optional[str] = None,
) -> tuple[str, int]:
    if kind == "note_asset" and ref_id is not None:
        asset = db.get(NoteAsset, ref_id)
        note = db.get(Note, asset.note_id) if asset else None
        name = Path(asset.local_path or "").name if asset and note and note.user_id == user_id else ""
    elif kind == "draft_asset" and ref_id is not None:
        asset = db.get(DraftAsset, ref_id)
        draft = db.get(AiDraft, asset.draft_id) if asset else None
        name = Path(asset.local_path or "").name if asset and draft and draft.user_id == user_id else ""
    elif kind == "upload" and file_name:
        name = Path(file_name).name
    else:
        raise InvalidMediaSource("无效的素材选择")

    if not name:
        raise InvalidMediaSource("素材不存在或不属于当前用户")
    checked = _existing_owned(name, user_id)
    if checked is None:
        raise InvalidMediaSource("素材不存在或不属于当前用户")
    return checked
```

- [ ] **Step 5: 增加素材目录接口**

在 `backend/app/api/clip.py` 中加入：

```python
from typing import Optional

from fastapi import Query

from backend.app.clip.assets import list_clip_assets


@router.get("/assets")
def get_clip_assets(
    q: str = "",
    asset_type: str = Query(default="", alias="type"),
    source: str = "",
    limit: int = Query(default=200, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "items": list_clip_assets(
            db,
            current_user.id,
            q=q,
            asset_type=asset_type,
            source=source,
            limit=limit,
        )
    }
```

并在文件顶部补充 `Session`、`get_db` 导入：

```python
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_assets.py -v`

Expected: 2 passed。

- [ ] **Step 7: 检查点**

Run: `python -m pytest tests/backend/test_api_files_media.py tests/backend/test_clip_assets.py -v`

Expected: 全部通过。

---

## Task 6: 会话创建与令牌交换

**Files:**
- Create: `backend/app/clip/sessions.py`
- Modify: `backend/app/api/clip.py`
- Test: `tests/backend/test_clip_sessions.py`

**Interfaces:**
- Consumes: `ClipSession`、`ClipAssetSelection`、`create_clip_handoff_token`、`create_clip_session_token`、`decode_clip_token`、`resolve_clip_asset`。
- Produces: `create_clip_session(db, user_id, payload, settings)`、`exchange_clip_session(db, session_id, token, ttl_hours)`、`load_active_clip_session(db, session_id, token)`；`POST /api/clip/sessions`、`POST /api/clip/sessions/{id}/exchange`。

- [ ] **Step 1: 写失败的会话测试**

Create `tests/backend/test_clip_sessions.py`:

```python
import json
from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403


def _video_for(token: str) -> str:
    from backend.app.core.security import decode_token

    user_id = decode_token(token)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 128)
    return name


def test_create_and_exchange_session_once(tmp_path):
    db_dependency = _override_database(tmp_path)
    name = ""
    try:
        token = _register_and_get_access_token("clip-session-owner")
        name = _video_for(token)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/clip/sessions",
            headers=headers,
            json={"title": "开箱视频", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["editor_url"].startswith("http://")
        assert payload["handoff_token"]
        session_id = payload["session_id"]

        exchanged = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {payload['handoff_token']}"},
        )
        assert exchanged.status_code == 200, exchanged.text
        body = exchanged.json()
        assert body["session_token"]
        assert body["assets"][0]["file_name"] == name
        assert body["assets"][0]["download_path"].endswith(name)

        replay = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {payload['handoff_token']}"},
        )
        assert replay.status_code == 409
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        if name:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_expired_handoff_token_returns_410(tmp_path):
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import ClipSession

    db_dependency = _override_database(tmp_path)
    name = ""
    try:
        token = _register_and_get_access_token("clip-session-expired")
        name = _video_for(token)
        created = client.post(
            "/api/clip/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "过期", "assets": [{"kind": "upload", "file_name": name}]},
        )
        session_id = created.json()["session_id"]
        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(ClipSession, session_id)
            session.handoff_expires_at = shanghai_now() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()

        response = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
        )
        assert response.status_code == 410
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        if name:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_session_rejects_foreign_asset_and_enforces_active_limit(tmp_path, monkeypatch):
    db_dependency = _override_database(tmp_path)
    names = []
    try:
        owner = _register_and_get_access_token("clip-session-a")
        other = _register_and_get_access_token("clip-session-b")
        name = _video_for(owner)
        names.append(name)
        headers_owner = {"Authorization": f"Bearer {owner}"}
        headers_other = {"Authorization": f"Bearer {other}"}

        foreign = client.post(
            "/api/clip/sessions",
            headers=headers_other,
            json={"title": "越权", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert foreign.status_code == 400

        from backend.app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "clip_max_active_sessions", 2)
        for index in range(2):
            response = client.post(
                "/api/clip/sessions",
                headers=headers_owner,
                json={"title": f"会话{index}", "assets": [{"kind": "upload", "file_name": name}]},
            )
            assert response.status_code == 201
        over = client.post(
            "/api/clip/sessions",
            headers=headers_owner,
            json={"title": "超限", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert over.status_code == 409
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for name in names:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_sessions.py -v`

Expected: FAIL，接口不存在。

- [ ] **Step 3: 实现会话服务**

Create `backend/app/clip/sessions.py`:

```python
from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.app.clip.assets import asset_type_for, resolve_clip_asset
from backend.app.clip.schemas import ClipSessionCreateRequest
from backend.app.core.config import Settings
from backend.app.core.media_source import InvalidMediaSource
from backend.app.core.security import (
    create_clip_handoff_token,
    create_clip_session_token,
    decode_clip_token,
)
from backend.app.core.time import shanghai_now
from backend.app.models import ClipSession

HANDOFF_TTL_MINUTES = 5


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _active_session_count(db: Session, user_id: int) -> int:
    now = shanghai_now()
    return int(
        db.scalar(
            select(func.count())
            .select_from(ClipSession)
            .where(
                ClipSession.user_id == user_id,
                ClipSession.status.in_(("issued", "exchanged")),
                or_(
                    ClipSession.session_expires_at > now,
                    and_(
                        ClipSession.session_expires_at.is_(None),
                        ClipSession.handoff_expires_at > now,
                    ),
                ),
            )
        )
        or 0
    )


def create_clip_session(
    db: Session, user_id: int, payload: ClipSessionCreateRequest, settings: Settings
) -> tuple[ClipSession, str]:
    if _active_session_count(db, user_id) >= settings.clip_max_active_sessions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="进行中的剪辑会话过多，请先完成或放弃旧会话")

    manifest: list[dict] = []
    seen: set[str] = set()
    for item in payload.assets:
        try:
            file_name, size_bytes = resolve_clip_asset(
                db, user_id, kind=item.kind, ref_id=item.id, file_name=item.file_name
            )
        except InvalidMediaSource as exc:
            raise _bad_request(str(exc)) from exc
        if file_name in seen:
            continue
        seen.add(file_name)
        manifest.append(
            {
                "file_name": file_name,
                "asset_type": asset_type_for(file_name) or "video",
                "size_bytes": size_bytes,
            }
        )
    if not manifest:
        raise _bad_request("至少选择一个有效素材")

    now = shanghai_now()
    jti = uuid4().hex
    title = payload.title.strip()
    if not title:
        raise _bad_request("会话标题不能为空")

    session = ClipSession(
        user_id=user_id,
        title=title,
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        status="issued",
        handoff_jti=jti,
        handoff_expires_at=now + timedelta(minutes=HANDOFF_TTL_MINUTES),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, create_clip_handoff_token(user_id, session.id, jti)


def exchange_clip_session(
    db: Session, session_id: int, token: str, ttl_hours: int
) -> tuple[ClipSession, str, list[dict]]:
    payload = decode_clip_token(token, "clip_handoff")
    if int(payload["session_id"]) != int(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    session = db.get(ClipSession, session_id)
    if session is None or session.user_id != payload["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    now = shanghai_now()
    if session.status != "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="剪辑会话已交换或已结束")
    if session.handoff_jti != payload.get("jti"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid clip token")
    if session.handoff_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="剪辑会话已过期，请返回工作台重新进入")

    session.status = "exchanged"
    session.exchanged_at = now
    session.session_expires_at = now + timedelta(hours=ttl_hours)
    db.commit()
    db.refresh(session)
    return (
        session,
        create_clip_session_token(session.user_id, session.id, ttl_hours),
        json.loads(session.manifest_json),
    )


def load_active_clip_session(
    db: Session, session_id: int, token: str
) -> tuple[ClipSession, list[dict]]:
    payload = decode_clip_token(token, "clip_session")
    if int(payload["session_id"]) != int(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    session = db.get(ClipSession, session_id)
    if session is None or session.user_id != payload["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    now = shanghai_now()
    if session.status not in ("exchanged", "completed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="剪辑会话不可用")
    if session.session_expires_at is None or session.session_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="剪辑会话已过期，请返回工作台重新进入")
    return session, json.loads(session.manifest_json)
```

- [ ] **Step 4: 增加会话接口**

在 `backend/app/api/clip.py` 中加入：

```python
from fastapi import Header

from backend.app.clip.schemas import ClipSessionCreateRequest
from backend.app.clip.sessions import create_clip_session, exchange_clip_session
from backend.app.core.config import get_settings


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization[7:].strip()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ClipSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, handoff_token = create_clip_session(db, current_user.id, payload, settings)
    return {
        "session_id": session.id,
        "editor_url": settings.clip_editor_public_base_url.rstrip("/"),
        "handoff_token": handoff_token,
        "handoff_expires_at": session.handoff_expires_at.isoformat(),
    }


@router.post("/sessions/{session_id}/exchange")
def exchange_session(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, session_token, manifest = exchange_clip_session(
        db, session_id, _bearer_token(authorization), settings.clip_session_ttl_hours
    )
    return {
        "session_token": session_token,
        "session_expires_at": session.session_expires_at.isoformat(),
        "assets": [
            {
                "file_name": item["file_name"],
                "asset_type": item["asset_type"],
                "size_bytes": item["size_bytes"],
                "download_path": f"/api/clip/sessions/{session.id}/assets/{item['file_name']}",
            }
            for item in manifest
        ],
    }
```

补充顶部导入：

```python
from fastapi import HTTPException, status
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_sessions.py -v`

Expected: 3 passed。

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/backend/test_clip_tokens.py tests/backend/test_clip_sessions.py -v`

Expected: 全部通过。

---

## Task 7: 会话素材流式读取

**Files:**
- Modify: `backend/app/clip/sessions.py`
- Modify: `backend/app/api/clip.py`
- Test: `tests/backend/test_clip_stream.py`

**Interfaces:**
- Consumes: `load_active_clip_session`、`media_dir()`、`FileResponse`。
- Produces: `get_session_asset_path(db, session_id, token, file_name) -> Path`；`GET /api/clip/sessions/{id}/assets/{file_name}`，支持 Range 206。

- [ ] **Step 1: 写失败的流式读取测试**

Create `tests/backend/test_clip_stream.py`:

```python
from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403


def _prepare(tmp_path):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    token = _register_and_get_access_token("clip-stream-owner")
    user_id = decode_token(token)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0123456789")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/clip/sessions",
        headers=headers,
        json={"title": "流测试", "assets": [{"kind": "upload", "file_name": name}]},
    )
    handoff = created.json()["handoff_token"]
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {handoff}"},
    )
    return db_dependency, token, name, session_id, exchanged.json()["session_token"]


def test_stream_asset_supports_range_and_rejects_unknown_name(tmp_path):
    db_dependency, token, name, session_id, session_token = _prepare(tmp_path)
    try:
        url = f"/api/clip/sessions/{session_id}/assets/{name}"
        full = client.get(url, headers={"Authorization": f"Bearer {session_token}"})
        assert full.status_code == 200
        assert full.headers["cache-control"] == "private, no-store"

        partial = client.get(
            url,
            headers={"Authorization": f"Bearer {session_token}", "Range": "bytes=0-3"},
        )
        assert partial.status_code == 206
        assert partial.content == b"\x00\x00\x00\x18"
        assert partial.headers["content-range"].startswith("bytes 0-3/")

        missing = client.get(
            f"/api/clip/sessions/{session_id}/assets/xhs-upload-u1-missing.mp4",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert missing.status_code == 404

        no_token = client.get(url)
        assert no_token.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_expired_session_token_returns_410(tmp_path):
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import ClipSession

    db_dependency, token, name, session_id, session_token = _prepare(tmp_path)
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(ClipSession, session_id)
            session.session_expires_at = shanghai_now() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        response = client.get(
            f"/api/clip/sessions/{session_id}/assets/{name}",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert response.status_code == 410
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_stream.py -v`

Expected: FAIL，接口不存在。

- [ ] **Step 3: 实现素材路径解析**

在 `backend/app/clip/sessions.py` 末尾加入：

```python
from pathlib import Path

from backend.app.core.media_source import assert_owned_media_name
from backend.app.core.media_storage import media_dir


def get_session_asset_path(
    db: Session, session_id: int, token: str, file_name: str
) -> Path:
    session, manifest = load_active_clip_session(db, session_id, token)
    allowed = {item["file_name"] for item in manifest}
    if file_name not in allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    try:
        assert_owned_media_name(file_name, session.user_id)
    except InvalidMediaSource as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from exc
    path = media_dir() / file_name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return path
```

- [ ] **Step 4: 增加流式接口**

在 `backend/app/api/clip.py` 中加入：

```python
from fastapi.responses import FileResponse

from backend.app.clip.sessions import get_session_asset_path


@router.get("/sessions/{session_id}/assets/{file_name}")
def stream_session_asset(
    session_id: int,
    file_name: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    path = get_session_asset_path(db, session_id, _bearer_token(authorization), file_name)
    media_type = "video/mp4" if file_name.lower().endswith(".mp4") else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_stream.py -v`

Expected: 2 passed，Range 请求返回 206，过期会话返回 410。

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/backend/test_clip_stream.py tests/backend/test_api_files_media.py -v`

Expected: 全部通过。

---

## Task 8: 成片上传、列表、删除与配额

**Files:**
- Create: `backend/app/clip/exports.py`
- Modify: `backend/app/api/clip.py`
- Test: `tests/backend/test_clip_exports.py`

**Interfaces:**
- Consumes: `load_active_clip_session`、`media_dir()`、`ClipExport`、`ClipSession`、`get_settings()`。
- Produces: `save_clip_export(...)`、`list_clip_exports(db, user_id, limit)`、`delete_clip_export(db, user_id, export_id)`；`POST/GET/DELETE /api/clip/exports`。

- [ ] **Step 1: 写失败的成片测试**

Create `tests/backend/test_clip_exports.py`:

```python
from pathlib import Path
from uuid import uuid4

import pytest

from api_helpers import *  # noqa: F401,F403

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"1" * 1024


def _session_token(tmp_path, username="clip-export-owner"):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    login = _register_and_get_access_token(username)
    user_id = decode_token(login)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(MP4)
    created = client.post(
        "/api/clip/sessions",
        headers={"Authorization": f"Bearer {login}"},
        json={"title": "成片测试", "assets": [{"kind": "upload", "file_name": name}]},
    )
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
    )
    return db_dependency, login, session_id, exchanged.json()["session_token"], name


def _upload(session_id, session_token, client_export_id="exp-1"):
    return client.post(
        "/api/clip/exports",
        headers={"Authorization": f"Bearer {session_token}"},
        data={
            "session_id": session_id,
            "title": "成片一",
            "client_export_id": client_export_id,
        },
        files={"file": ("clip.mp4", MP4, "video/mp4")},
    )


def test_upload_export_is_idempotent_and_listed(tmp_path):
    db_dependency, login, session_id, session_token, source_name = _session_token(tmp_path)
    try:
        first = _upload(session_id, session_token)
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["file_name"].startswith("xhs-clip-u1-")
        assert (Path(get_settings().storage_dir) / "media" / body["file_name"]).is_file()

        second = _upload(session_id, session_token)
        assert second.status_code == 200
        assert second.json()["id"] == body["id"]

        # 列表使用登录态而不是会话令牌
        rows = client.get("/api/clip/exports", headers={"Authorization": f"Bearer {login}"})
        assert rows.status_code == 200
        assert [item["id"] for item in rows.json()["items"]] == [body["id"]]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_upload_rejects_bad_type_and_oversize(tmp_path, monkeypatch):
    db_dependency, login, session_id, session_token, source_name = _session_token(tmp_path)
    try:
        bad = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"title": "假视频", "client_export_id": "bad-1"},
            files={"file": ("clip.mp4", b"not-an-mp4", "video/mp4")},
        )
        assert bad.status_code == 400

        from backend.app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "clip_max_export_bytes", 16)
        big = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"title": "过大", "client_export_id": "big-1"},
            files={"file": ("clip.mp4", MP4, "video/mp4")},
        )
        assert big.status_code == 413
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_exports.py -v`

Expected: FAIL，接口不存在。

- [ ] **Step 3: 实现成片服务**

Create `backend/app/clip/exports.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.media_storage import media_dir
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession

CHUNK_SIZE = 1024 * 1024


def serialize_export(export: ClipExport) -> dict:
    return {
        "id": export.id,
        "title": export.title,
        "file_name": export.file_name,
        "mime": export.mime,
        "size_bytes": export.size_bytes,
        "duration_ms": export.duration_ms,
        "status": export.status,
        "linked_draft_id": export.linked_draft_id,
        "created_at": export.created_at.isoformat(),
        "download_url": f"/api/files/media/{export.file_name}",
    }


def list_clip_exports(db: Session, user_id: int, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    rows = db.scalars(
        select(ClipExport)
        .where(ClipExport.user_id == user_id)
        .order_by(ClipExport.created_at.desc(), ClipExport.id.desc())
        .limit(limit)
    ).all()
    return [serialize_export(row) for row in rows]


async def save_clip_export(
    db: Session,
    session: ClipSession,
    upload: UploadFile,
    *,
    title: str,
    client_export_id: str,
    duration_ms: Optional[int],
    settings: Settings,
) -> tuple[ClipExport, bool]:
    existing = db.scalar(
        select(ClipExport).where(
            ClipExport.session_id == session.id,
            ClipExport.client_export_id == client_export_id,
        )
    )
    if existing is not None:
        return existing, False

    ext = Path(upload.filename or "").suffix.lower()
    if ext != ".mp4":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="首期只支持 MP4 成片")

    directory = media_dir()
    directory.mkdir(parents=True, exist_ok=True)
    tmp_path = directory / f".clip-upload-{uuid4().hex}.part"
    total = 0
    try:
        with tmp_path.open("wb") as output:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.clip_max_export_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"成片超过 {settings.clip_max_export_bytes} 字节上限",
                    )
                output.write(chunk)

        with tmp_path.open("rb") as check:
            head = check.read(12)
        if len(head) < 8 or head[4:8] != b"ftyp":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件不是有效的 MP4")

        used = int(
            db.scalar(
                select(func.coalesce(func.sum(ClipExport.size_bytes), 0)).where(
                    ClipExport.user_id == session.user_id
                )
            )
            or 0
        )
        if used + total > settings.clip_user_export_quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="成片总容量超过配额，请先删除旧成片",
            )

        final_name = f"xhs-clip-u{session.user_id}-{uuid4().hex}.mp4"
        final_path = directory / final_name
        os.replace(tmp_path, final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    export = ClipExport(
        user_id=session.user_id,
        session_id=session.id,
        title=title.strip(),
        file_name=final_name,
        mime="video/mp4",
        size_bytes=total,
        duration_ms=duration_ms,
        status="available",
        client_export_id=client_export_id,
        created_at=shanghai_now(),
    )
    try:
        db.add(export)
        session.status = "completed"
        db.commit()
        db.refresh(export)
    except IntegrityError:
        db.rollback()
        final_path.unlink(missing_ok=True)
        existing = db.scalar(
            select(ClipExport).where(
                ClipExport.session_id == session.id,
                ClipExport.client_export_id == client_export_id,
            )
        )
        if existing is None:
            raise
        return existing, False
    return export, True


def delete_clip_export(db: Session, user_id: int, export_id: int) -> None:
    export = db.get(ClipExport, export_id)
    if export is None or export.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成片不存在")
    if export.linked_draft_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="成片已关联草稿，请先解除草稿引用")
    path = media_dir() / export.file_name
    db.delete(export)
    db.commit()
    path.unlink(missing_ok=True)
```

- [ ] **Step 4: 增加成片接口**

在 `backend/app/api/clip.py` 中加入：

```python
from fastapi import File, Form, Response, UploadFile

from backend.app.clip.exports import (
    delete_clip_export,
    list_clip_exports,
    save_clip_export,
    serialize_export,
)
from backend.app.clip.sessions import load_active_clip_session


@router.post("/exports", status_code=status.HTTP_201_CREATED)
async def upload_export(
    response: Response,
    session_id: int = Form(...),
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=120),
    client_export_id: str = Form(..., min_length=1, max_length=64),
    duration_ms: Optional[int] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, _manifest = load_active_clip_session(db, session_id, _bearer_token(authorization))
    export, created = await save_clip_export(
        db,
        session,
        file,
        title=title,
        client_export_id=client_export_id,
        duration_ms=duration_ms,
        settings=settings,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return serialize_export(export)


@router.get("/exports")
def get_exports(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": list_clip_exports(db, current_user.id, limit)}


@router.delete("/exports/{export_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_export(
    export_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_clip_export(db, current_user.id, export_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_exports.py -v`

Expected: 2 passed。

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/backend/test_clip_exports.py tests/backend/test_api_files_media.py -v`

Expected: 全部通过。

---

## Task 9: 成片送入小红书草稿与媒体前缀兼容

**Files:**
- Modify: `backend/app/clip/exports.py`
- Modify: `backend/app/api/clip.py`
- Modify: `backend/app/api/files.py:54-61, 220-230`
- Modify: `backend/app/douyin/publishing.py:53-73`
- Modify: `backend/app/services/media_cleanup.py:20`
- Test: `tests/backend/test_clip_draft_handoff.py`

**Interfaces:**
- Consumes: `ClipExport`、`AiDraft`、`DraftAsset`、`resolve_media_paths`、`prune_media_dir`。
- Produces: `create_draft_from_clip_export(db, user_id, export_id) -> tuple[AiDraft, bool]`；`POST /api/clip/exports/{id}/draft`；`xhs-clip-u` 前缀可通过文件接口与抖音发布校验。

- [ ] **Step 1: 写失败的草稿与兼容测试**

Create `tests/backend/test_clip_draft_handoff.py`:

```python
from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"2" * 512


def _export_for(tmp_path, username="clip-draft-owner"):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    login = _register_and_get_access_token(username)
    user_id = decode_token(login)["user_id"]
    source = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / source).write_bytes(MP4)
    created = client.post(
        "/api/clip/sessions",
        headers={"Authorization": f"Bearer {login}"},
        json={"title": "草稿来源", "assets": [{"kind": "upload", "file_name": source}]},
    )
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
    )
    export = client.post(
        "/api/clip/exports",
        headers={"Authorization": f"Bearer {exchanged.json()['session_token']}"},
        data={"session_id": session_id, "title": "成片标题", "client_export_id": "draft-1"},
        files={"file": ("clip.mp4", MP4, "video/mp4")},
    )
    return db_dependency, login, user_id, source, export.json()


def test_export_creates_one_xhs_draft_and_links_it(tmp_path):
    db_dependency, login, user_id, source, export = _export_for(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {login}"}
        first = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert first.status_code == 200, first.text
        draft_id = first.json()["draft_id"]

        second = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert second.status_code == 200
        assert second.json()["draft_id"] == draft_id
        assert second.json()["created"] is False

        blocked = client.delete(f"/api/clip/exports/{export['id']}", headers=headers)
        assert blocked.status_code == 409

        from backend.app.core.database import get_db
        from backend.app.models import AiDraft, DraftAsset

        db = next(app.dependency_overrides[get_db]())
        try:
            draft = db.get(AiDraft, draft_id)
            assert draft.user_id == user_id
            assert draft.platform == "xhs"
            assets = db.query(DraftAsset).filter_by(draft_id=draft_id).all()
            assert len(assets) == 1
            assert assets[0].asset_type == "video"
            assert assets[0].local_path == export["file_name"]
        finally:
            db.close()

        download = client.get(f"/api/files/media/{export['file_name']}", headers=headers)
        assert download.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)


def test_clip_prefix_is_accepted_by_douyin_and_ignored_by_cleanup(tmp_path):
    db_dependency, login, user_id, source, export = _export_for(tmp_path, "clip-prefix-owner")
    try:
        from backend.app.douyin.publishing import resolve_media_paths
        from backend.app.services.media_cleanup import prune_media_dir

        resolved = resolve_media_paths(user_id, [export["file_name"]])
        assert Path(resolved[0]).name == export["file_name"]

        temp_media = tmp_path / "prune-media"
        temp_media.mkdir()
        keep = temp_media / export["file_name"]
        keep.write_bytes(b"x")
        prune_media_dir(temp_media, max_age_days=0, max_total_bytes=0)
        assert keep.exists()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_draft_handoff.py -v`

Expected: FAIL，草稿接口不存在；文件接口和抖音校验拒绝 `xhs-clip-u`。

- [ ] **Step 3: 实现草稿对接**

在 `backend/app/clip/exports.py` 末尾加入：

```python
from backend.app.models import AiDraft, DraftAsset


def create_draft_from_clip_export(
    db: Session, user_id: int, export_id: int
) -> tuple[AiDraft, bool]:
    export = db.get(ClipExport, export_id)
    if export is None or export.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成片不存在")

    if export.linked_draft_id:
        existing = db.get(AiDraft, export.linked_draft_id)
        if existing is not None:
            return existing, False
        export.linked_draft_id = None
        export.status = "available"

    draft = AiDraft(user_id=user_id, platform="xhs", title=export.title, body="")
    db.add(draft)
    db.flush()
    db.add(
        DraftAsset(
            draft_id=draft.id,
            asset_type="video",
            local_path=export.file_name,
            sort_order=0,
        )
    )
    export.linked_draft_id = draft.id
    export.status = "linked"
    db.commit()
    db.refresh(draft)
    return draft, True
```

- [ ] **Step 4: 增加草稿接口**

在 `backend/app/api/clip.py` 中加入：

```python
from backend.app.clip.exports import create_draft_from_clip_export


@router.post("/exports/{export_id}/draft")
def export_to_xhs_draft(
    export_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft, created = create_draft_from_clip_export(db, current_user.id, export_id)
    return {"draft_id": draft.id, "created": created}
```

- [ ] **Step 5: 增加媒体前缀兼容**

`backend/app/api/files.py` 的 `_validate_owner_media_name`：

```python
    valid_prefixes = (
        _owner_media_prefix(current_user),
        f"xhs-asset-u{current_user.id}-",
        f"xhs-upload-u{current_user.id}-",
        f"xhs-clip-u{current_user.id}-",
    )
```

同文件 `list_user_images` 附近的下载前缀元组加入：

```python
        f"xhs-clip-u{viewer.id}-",
```

`backend/app/douyin/publishing.py::resolve_media_paths`：

```python
    allowed = (
        f"xhs-upload-u{user_id}-",
        f"xhs-image-u{user_id}-",
        f"xhs-clip-u{user_id}-",
    )
```

`backend/app/services/media_cleanup.py` 的 `_PREFIXES` 保持只含原有三项，并补注释：

```python
# 成片（xhs-clip-u）是用户显式管理的资产，只通过剪辑工坊删除，
# 不参与按年龄/容量自动清理；加入 _PREFIXES 会导致成片被误删。
_PREFIXES = ("xhs-image-u", "xhs-asset-u", "xhs-upload-u")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_draft_handoff.py -v`

Expected: 2 passed。

- [ ] **Step 7: 检查点**

Run: `python -m pytest tests/backend/test_clip_draft_handoff.py tests/backend/test_api_drafts_ai.py tests/backend/test_api_files_media.py -v`

Expected: 全部通过。

---

## Task 10: 过期会话与临时文件清理

**Files:**
- Create: `backend/app/clip/cleanup.py`
- Modify: `backend/app/services/scheduler_service.py:1023-1093`
- Test: `tests/backend/test_clip_cleanup.py`

**Interfaces:**
- Consumes: `ClipSession`、`ClipExport`、`SessionLocal`、`media_dir()`。
- Produces: `mark_expired_clip_sessions(db, now=None)`、`prune_clip_sessions(db, now=None, retention_days=7)`、`prune_clip_temp_files(now=None, max_age_hours=24)`、`run_clip_cleanup_once()`；调度器每 6 小时执行一次。

- [ ] **Step 1: 写失败的清理测试**

Create `tests/backend/test_clip_cleanup.py`:

```python
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'clip-cleanup.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_mark_and_prune_expired_sessions(tmp_path):
    from backend.app.clip.cleanup import mark_expired_clip_sessions, prune_clip_sessions

    db = _db(tmp_path)
    now = shanghai_now()
    expired = ClipSession(
        user_id=1, title="过期", manifest_json="[]", status="issued",
        handoff_jti="j1", handoff_expires_at=now - timedelta(days=10),
        created_at=now - timedelta(days=10),
    )
    kept = ClipSession(
        user_id=1, title="有导出", manifest_json="[]", status="exchanged",
        handoff_jti="j2", handoff_expires_at=now - timedelta(days=10),
        session_expires_at=now - timedelta(days=9), created_at=now - timedelta(days=10),
    )
    db.add_all([expired, kept])
    db.flush()
    db.add(ClipExport(user_id=1, session_id=kept.id, title="成片", file_name="xhs-clip-u1-a.mp4",
                      size_bytes=10, client_export_id="c1", created_at=now))
    db.commit()

    assert mark_expired_clip_sessions(db, now=now) == 2
    assert expired.status == "expired"
    assert kept.status == "expired"
    assert prune_clip_sessions(db, now=now, retention_days=7) == 1
    assert db.get(ClipSession, expired.id) is None
    assert db.get(ClipSession, kept.id) is not None
    db.close()


def test_prune_temp_files_only_old_parts(tmp_path):
    from backend.app.clip.cleanup import prune_clip_temp_files

    directory = tmp_path / "media"
    directory.mkdir()
    old = directory / ".clip-upload-old.part"
    fresh = directory / ".clip-upload-fresh.part"
    other = directory / "keep.mp4"
    for path in (old, fresh, other):
        path.write_bytes(b"x")
    now = 1_800_000_000
    old.touch()
    import os

    os.utime(old, (now - 25 * 3600, now - 25 * 3600))
    os.utime(fresh, (now - 3600, now - 3600))
    assert prune_clip_temp_files(directory, now=now, max_age_hours=24) == 1
    assert not old.exists()
    assert fresh.exists()
    assert other.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/backend/test_clip_cleanup.py -v`

Expected: FAIL，`backend.app.clip.cleanup` 不存在。

- [ ] **Step 3: 实现清理**

Create `backend/app/clip/cleanup.py`:

```python
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.core.media_storage import media_dir
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession


def mark_expired_clip_sessions(db: Session, now: Optional[datetime] = None) -> int:
    current = now or shanghai_now()
    changed = 0
    rows = db.scalars(
        select(ClipSession).where(ClipSession.status.in_(("issued", "exchanged")))
    ).all()
    for session in rows:
        if session.status == "issued" and session.handoff_expires_at <= current:
            session.status = "expired"
            changed += 1
        elif (
            session.status == "exchanged"
            and session.session_expires_at is not None
            and session.session_expires_at <= current
        ):
            session.status = "expired"
            changed += 1
    if changed:
        db.commit()
    return changed


def prune_clip_sessions(
    db: Session, now: Optional[datetime] = None, retention_days: int = 7
) -> int:
    cutoff = (now or shanghai_now()) - timedelta(days=retention_days)
    rows = db.scalars(
        select(ClipSession).where(
            ClipSession.status == "expired",
            ClipSession.handoff_expires_at < cutoff,
        )
    ).all()
    removed = 0
    for session in rows:
        exports = int(
            db.scalar(
                select(func.count())
                .select_from(ClipExport)
                .where(ClipExport.session_id == session.id)
            )
            or 0
        )
        if exports:
            continue
        db.delete(session)
        removed += 1
    if removed:
        db.commit()
    return removed


def prune_clip_temp_files(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    max_age_hours: int = 24,
) -> int:
    target = directory or media_dir()
    if not target.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed = 0
    for path in target.iterdir():
        if not path.is_file() or not path.name.startswith(".clip-upload-") or not path.name.endswith(".part"):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def run_clip_cleanup_once() -> dict[str, int]:
    db = SessionLocal()
    try:
        expired = mark_expired_clip_sessions(db)
        pruned = prune_clip_sessions(db)
        temp = prune_clip_temp_files()
        return {"expired": expired, "pruned": pruned, "temp_files": temp}
    finally:
        db.close()
```

- [ ] **Step 4: 注册调度任务**

在 `backend/app/services/scheduler_service.py` 的 `_run_media_prune` 之后加入：

```python
def _run_clip_cleanup() -> None:
    from backend.app.clip.cleanup import run_clip_cleanup_once

    try:
        run_clip_cleanup_once()
    except Exception as exc:
        logger.error(f"clip cleanup failed: {exc}")
```

在 `build_due_publish_scheduler` 中、`media_pruner` 任务之后加入：

```python
    scheduler.add_job(
        _run_clip_cleanup,
        "interval",
        hours=6,
        id="clip_cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/backend/test_clip_cleanup.py -v`

Expected: 2 passed。

- [ ] **Step 6: 检查点**

Run: `python -m pytest tests/backend/test_clip_cleanup.py tests/backend/test_api_publish_scheduler.py -v`

Expected: 全部通过。

---

## Task 11: 前端剪辑类型、API 与地址构造

**Files:**
- Create: `frontend/src/features/clip/types.ts`
- Create: `frontend/src/features/clip/api.ts`
- Create: `frontend/src/features/clip/session-url.ts`
- Test: `frontend/src/features/clip/session-url.test.ts`
- Test: `frontend/src/features/clip/asset-selection.test.ts`（Task 12 创建）
- Modify: `frontend/package.json:41`（`test` 已覆盖 `src`，无需改）

**Interfaces:**
- Consumes: `authenticatedHttp`。
- Produces: `ClipAsset`、`ClipExport`、`ClipSelection`、`ClipSessionCreated`；`fetchClipAssets`、`createClipSession`、`fetchClipExports`、`createClipDraft`、`deleteClipExport`；`buildEditorUrl(base, token, sessionId)`。

- [ ] **Step 1: 写失败的地址构造测试**

Create `frontend/src/features/clip/session-url.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildEditorUrl } from "./session-url";

describe("buildEditorUrl", () => {
  it("把令牌放进 fragment 并对参数编码", () => {
    const url = buildEditorUrl("http://127.0.0.1:3000/", "a+b/c=", 42);
    expect(url).toBe("http://127.0.0.1:3000/#handoff=a%2Bb%2Fc%3D&session=42");
    expect(url).not.toContain("?handoff=");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/features/clip/session-url.test.ts`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 创建类型**

Create `frontend/src/features/clip/types.ts`:

```ts
export type ClipAssetKind = "note_asset" | "draft_asset" | "upload";
export type ClipAssetType = "image" | "video" | "audio";

export type ClipAsset = {
  id: string;
  kind: ClipAssetKind;
  ref_id: string;
  file_name: string;
  asset_type: ClipAssetType;
  source: "note" | "draft" | "upload";
  title: string;
  size_bytes: number;
  preview_url: string;
};

export type ClipSelection = {
  kind: ClipAssetKind;
  id?: number;
  file_name?: string;
};

export type ClipSessionCreated = {
  session_id: number;
  editor_url: string;
  handoff_token: string;
  handoff_expires_at: string;
};

export type ClipExport = {
  id: number;
  title: string;
  file_name: string;
  mime: string;
  size_bytes: number;
  duration_ms: number | null;
  status: "available" | "linked" | string;
  linked_draft_id: number | null;
  created_at: string;
  download_url: string;
};
```

- [ ] **Step 4: 创建 API 与地址构造**

Create `frontend/src/features/clip/session-url.ts`:

```ts
export function buildEditorUrl(base: string, handoffToken: string, sessionId: number): string {
  const url = new URL(base);
  url.hash = new URLSearchParams({
    handoff: handoffToken,
    session: String(sessionId),
  }).toString();
  return url.toString();
}
```

Create `frontend/src/features/clip/api.ts`:

```ts
import { authenticatedHttp } from "../../lib/api";
import type {
  ClipAsset,
  ClipExport,
  ClipSelection,
  ClipSessionCreated,
} from "./types";

export async function fetchClipAssets(params: {
  q?: string;
  type?: string;
  source?: string;
} = {}): Promise<ClipAsset[]> {
  const response = await authenticatedHttp.get<{ items: ClipAsset[] }>("/clip/assets", { params });
  return response.data.items;
}

export async function createClipSession(payload: {
  title: string;
  assets: ClipSelection[];
}): Promise<ClipSessionCreated> {
  const response = await authenticatedHttp.post<ClipSessionCreated>("/clip/sessions", payload);
  return response.data;
}

export async function fetchClipExports(limit = 50): Promise<ClipExport[]> {
  const response = await authenticatedHttp.get<{ items: ClipExport[] }>("/clip/exports", {
    params: { limit },
  });
  return response.data.items;
}

export async function createClipDraft(exportId: number): Promise<{ draft_id: number; created: boolean }> {
  const response = await authenticatedHttp.post<{ draft_id: number; created: boolean }>(
    `/clip/exports/${exportId}/draft`,
  );
  return response.data;
}

export async function deleteClipExport(exportId: number): Promise<void> {
  await authenticatedHttp.delete(`/clip/exports/${exportId}`);
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/features/clip/session-url.test.ts`

Expected: 1 passed。

- [ ] **Step 6: 检查点**

Run: `cd frontend && npm run typecheck`

Expected: 通过。

---

## Task 12: 素材选择纯函数与选择器组件

**Files:**
- Create: `frontend/src/features/clip/asset-selection.ts`
- Create: `frontend/src/features/clip/asset-selection.test.ts`
- Create: `frontend/src/features/clip/components/asset-picker.tsx`

**Interfaces:**
- Consumes: `ClipAsset`、`ClipSelection`、`fetchClipAssets`。
- Produces: `assetKey(asset)`、`toSelections(assets)`、`AssetPicker`（props：`open, onCancel, onConfirm`）。

- [ ] **Step 1: 写失败的选择纯函数测试**

Create `frontend/src/features/clip/asset-selection.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { assetKey, toSelections } from "./asset-selection";
import type { ClipAsset } from "./types";

const noteAsset: ClipAsset = {
  id: "note_asset:7", kind: "note_asset", ref_id: "7", file_name: "xhs-asset-u1-a.mp4",
  asset_type: "video", source: "note", title: "参考笔记", size_bytes: 10,
  preview_url: "/api/files/media/xhs-asset-u1-a.mp4",
};
const uploadAsset: ClipAsset = {
  ...noteAsset, id: "upload:xhs-upload-u1-b.mp4", kind: "upload",
  ref_id: "xhs-upload-u1-b.mp4", file_name: "xhs-upload-u1-b.mp4", source: "upload",
};

describe("asset selection", () => {
  it("为每项生成稳定 key", () => {
    expect(assetKey(noteAsset)).toBe("note_asset:7");
    expect(assetKey(uploadAsset)).toBe("upload:xhs-upload-u1-b.mp4");
  });

  it("转换为后端选择结构", () => {
    expect(toSelections([noteAsset, uploadAsset])).toEqual([
      { kind: "note_asset", id: 7 },
      { kind: "upload", file_name: "xhs-upload-u1-b.mp4" },
    ]);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/features/clip/asset-selection.test.ts`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现纯函数**

Create `frontend/src/features/clip/asset-selection.ts`:

```ts
import type { ClipAsset, ClipSelection } from "./types";

export function assetKey(asset: ClipAsset): string {
  return `${asset.kind}:${asset.ref_id}`;
}

export function toSelections(assets: ClipAsset[]): ClipSelection[] {
  return assets.map((asset) =>
    asset.kind === "upload"
      ? { kind: "upload", file_name: asset.ref_id }
      : { kind: asset.kind, id: Number(asset.ref_id) },
  );
}
```

- [ ] **Step 4: 实现素材选择弹窗**

Create `frontend/src/features/clip/components/asset-picker.tsx`:

```tsx
import { FileImageOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Empty, Input, List, Modal, Segmented, Space, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { fetchClipAssets } from "../api";
import { assetKey } from "../asset-selection";
import type { ClipAsset } from "../types";

const { Text } = Typography;

type SourceFilter = "all" | "note" | "draft" | "upload";

const SOURCE_LABELS: Record<SourceFilter, string> = {
  all: "全部",
  note: "内容库",
  draft: "草稿",
  upload: "本地上传",
};

export function AssetPicker(props: {
  open: boolean;
  onCancel: () => void;
  onConfirm: (assets: ClipAsset[]) => void;
}) {
  const [source, setSource] = useState<SourceFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<ClipAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Record<string, ClipAsset>>({});

  useEffect(() => {
    if (!props.open) return;
    let cancelled = false;
    setLoading(true);
    fetchClipAssets({ q: keyword, source: source === "all" ? undefined : source })
      .then((list) => { if (!cancelled) setItems(list); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [props.open, keyword, source]);

  useEffect(() => {
    if (!props.open) {
      setSelected({});
      setKeyword("");
      setSource("all");
    }
  }, [props.open]);

  const selectedAssets = useMemo(() => Object.values(selected), [selected]);

  return (
    <Modal
      open={props.open}
      title="选择素材"
      width={720}
      okText={`加入剪辑（${selectedAssets.length}）`}
      okButtonProps={{ disabled: selectedAssets.length === 0 }}
      onCancel={props.onCancel}
      onOk={() => props.onConfirm(selectedAssets)}
      destroyOnClose
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Segmented
          value={source}
          onChange={(value) => setSource(value as SourceFilter)}
          options={(Object.keys(SOURCE_LABELS) as SourceFilter[]).map((value) => ({
            value,
            label: SOURCE_LABELS[value],
          }))}
        />
        <Input.Search placeholder="按标题或文件名搜索" allowClear onSearch={setKeyword} />
        <List
          loading={loading}
          style={{ maxHeight: 420, overflowY: "auto" }}
          dataSource={items}
          locale={{ emptyText: <Empty description="没有可用素材，请先到内容库下载或上传文件" /> }}
          renderItem={(asset) => {
            const key = assetKey(asset);
            const checked = Boolean(selected[key]);
            return (
              <List.Item
                actions={[
                  <a key="toggle" onClick={() => setSelected((prev) => {
                    const next = { ...prev };
                    if (next[key]) delete next[key]; else next[key] = asset;
                    return next;
                  })}>
                    {checked ? "已选择" : "选择"}
                  </a>,
                ]}
              >
                <List.Item.Meta
                  avatar={asset.asset_type === "image"
                    ? <FileImageOutlined style={{ fontSize: 24 }} />
                    : <VideoCameraOutlined style={{ fontSize: 24 }} />}
                  title={<Text strong>{asset.title}</Text>}
                  description={
                    <Space size={8} wrap>
                      <Tag color={checked ? "blue" : undefined}>{SOURCE_LABELS[asset.source]}</Tag>
                      <Tag>{asset.asset_type}</Tag>
                      <Text type="secondary">{asset.file_name}</Text>
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      </Space>
    </Modal>
  );
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/features/clip/asset-selection.test.ts src/features/clip/session-url.test.ts`

Expected: 3 passed。

- [ ] **Step 6: 检查点**

Run: `cd frontend && npm run typecheck`

Expected: 通过。

---

## Task 13: 剪辑工坊页面与成片列表

**Files:**
- Create: `frontend/src/features/clip/components/export-list.tsx`
- Create: `frontend/src/features/clip/clip-page.tsx`

**Interfaces:**
- Consumes: `fetchClipExports`、`createClipDraft`、`deleteClipExport`、`createClipSession`、`buildEditorUrl`、`AssetPicker`、`toSelections`。
- Produces: `ClipPage`，路径 `/clip`；`ExportList`（props：`items, loading, onRefresh`）。

- [ ] **Step 1: 写失败的前端接线测试**

Create `frontend/tests/clip-workbench.test.cjs`:

```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function read(relative) {
  return fs.readFileSync(path.join(__dirname, '..', relative), 'utf8');
}

test('clip page wires session creation and editor opening', () => {
  const page = read('src/features/clip/clip-page.tsx');
  assert.match(page, /剪辑工坊/);
  assert.match(page, /新建剪辑/);
  assert.match(page, /createClipSession/);
  assert.match(page, /buildEditorUrl/);
  assert.match(page, /window\.open/);
});

test('export list renders download, draft, douyin and delete actions', () => {
  const list = read('src/features/clip/components/export-list.tsx');
  assert.match(list, /下载/);
  assert.match(list, /送入小红书草稿/);
  assert.match(list, /用于抖音发布/);
  assert.match(list, /删除/);
  assert.match(list, /createClipDraft/);
  assert.match(list, /\/platforms\/douyin\/publish/);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && node --test tests/clip-workbench.test.cjs`

Expected: FAIL，文件不存在。

- [ ] **Step 3: 实现成片列表**

Create `frontend/src/features/clip/components/export-list.tsx`:

```tsx
import { DeleteOutlined, DownloadOutlined, SendOutlined } from "@ant-design/icons";
import { Button, Empty, List, Popconfirm, Space, Tag, Typography, message } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createClipDraft, deleteClipExport } from "../api";
import type { ClipExport } from "../types";

const { Text } = Typography;

export function ExportList(props: {
  items: ClipExport[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [busyId, setBusyId] = useState<number | null>(null);

  async function sendToDraft(item: ClipExport) {
    setBusyId(item.id);
    try {
      const result = await createClipDraft(item.id);
      message.success(result.created ? "已创建小红书草稿" : "该成片已关联草稿");
      navigate("/platforms/xhs/drafts");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(item: ClipExport) {
    setBusyId(item.id);
    try {
      await deleteClipExport(item.id);
      message.success("成片已删除");
      props.onRefresh();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <List
      loading={props.loading}
      dataSource={props.items}
      locale={{ emptyText: <Empty description="还没有成片，完成一次剪辑后会出现在这里" /> }}
      renderItem={(item) => (
        <List.Item
          actions={[
            <a key="download" href={item.download_url} target="_blank" rel="noreferrer">
              <DownloadOutlined /> 下载
            </a>,
            <Button
              key="draft"
              size="small"
              type="primary"
              loading={busyId === item.id}
              onClick={() => void sendToDraft(item)}
            >
              送入小红书草稿
            </Button>,
            <Button
              key="douyin"
              size="small"
              onClick={() => navigate(
                `/platforms/douyin/publish?media=${encodeURIComponent(item.file_name)}&title=${encodeURIComponent(item.title)}`,
              )}
            >
              <SendOutlined /> 用于抖音发布
            </Button>,
            <Popconfirm
              key="delete"
              title="删除这个成片？"
              description="已关联草稿的成片不能删除。"
              onConfirm={() => void remove(item)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} loading={busyId === item.id}>
                删除
              </Button>
            </Popconfirm>,
          ]}
        >
          <List.Item.Meta
            title={<Text strong>{item.title || "未命名成片"}</Text>}
            description={
              <Space size={8} wrap>
                <Tag color={item.linked_draft_id ? "green" : "default"}>
                  {item.linked_draft_id ? "已关联草稿" : "未关联"}
                </Tag>
                <Text type="secondary">{item.file_name}</Text>
                <Text type="secondary">{Math.round(item.size_bytes / 1024 / 1024)} MB</Text>
                <Text type="secondary">{new Date(item.created_at).toLocaleString("zh-CN")}</Text>
              </Space>
            }
          />
        </List.Item>
      )}
    />
  );
}
```

- [ ] **Step 4: 实现剪辑工坊页面**

Create `frontend/src/features/clip/clip-page.tsx`:

```tsx
import { AppstoreOutlined, PlusOutlined, ScissorOutlined } from "@ant-design/icons";
import { Button, Card, Input, Layout, Space, Tabs, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../../hooks/use-auth";
import { createClipSession, fetchClipExports } from "./api";
import { toSelections } from "./asset-selection";
import { AssetPicker } from "./components/asset-picker";
import { ExportList } from "./components/export-list";
import { buildEditorUrl } from "./session-url";
import type { ClipAsset, ClipExport } from "./types";

const { Content } = Layout;
const { Title, Paragraph, Text } = Typography;

export function ClipPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const from = searchParams.get("from");
  const [exports, setExports] = useState<ClipExport[]>([]);
  const [loading, setLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedAssets, setSelectedAssets] = useState<ClipAsset[]>([]);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const backPath = from === "douyin"
    ? "/platforms/douyin/accounts"
    : from === "xhs"
      ? "/platforms/xhs/dashboard"
      : "/apps";
  const backLabel = from === "douyin" ? "返回抖音运营" : from === "xhs" ? "返回小红书运营" : "返回应用中心";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setExports(await fetchClipExports());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load().catch(() => {/* 统一错误提示由请求层处理 */});
  }, [load]);

  const selectedSummary = useMemo(
    () => selectedAssets.map((asset) => asset.title || asset.file_name).join("、"),
    [selectedAssets],
  );

  async function startEditing() {
    if (!title.trim()) {
      message.warning("请先填写成片标题");
      return;
    }
    if (selectedAssets.length === 0) {
      message.warning("请至少选择一个素材");
      return;
    }
    setCreating(true);
    try {
      const session = await createClipSession({
        title: title.trim(),
        assets: toSelections(selectedAssets),
      });
      const url = buildEditorUrl(session.editor_url, session.handoff_token, session.session_id);
      window.open(url, "_blank", "noopener,noreferrer");
      message.success("已打开剪辑器；导出后成片会回到这里");
      setTitle("");
      setSelectedAssets([]);
    } finally {
      setCreating(false);
    }
  }

  const editorTab = (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="新建剪辑">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Input
            placeholder="成片标题，例如：新品开箱 30 秒"
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Space wrap>
            <Button icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
              选择素材
            </Button>
            <Button type="primary" icon={<ScissorOutlined />} loading={creating} onClick={() => void startEditing()}>
              新建剪辑
            </Button>
            <Button onClick={() => navigate(backPath)}>{backLabel}</Button>
          </Space>
          {selectedSummary && <Text type="secondary">已选：{selectedSummary}</Text>}
        </Space>
      </Card>
      <Card title="最近成片" extra={<Button size="small" onClick={() => void load()}>刷新</Button>}>
        <ExportList items={exports.slice(0, 5)} loading={loading} onRefresh={() => void load()} />
      </Card>
    </Space>
  );

  const exportsTab = (
    <Card title="成片库" extra={<Button size="small" onClick={() => void load()}>刷新</Button>}>
      <ExportList items={exports} loading={loading} onRefresh={() => void load()} />
    </Card>
  );

  return (
    <Layout style={{ minHeight: "100vh", background: "var(--app-bg, #0a0a0a)" }}>
      <Content style={{ width: "100%", maxWidth: 1080, margin: "0 auto", padding: "32px 24px" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <div>
            <Text type="secondary">独立应用</Text>
            <Title level={1} style={{ margin: "8px 0" }}>剪辑工坊</Title>
            <Paragraph type="secondary" style={{ margin: 0 }}>
              从内容库、草稿或本地上传中选择素材，拼接成片后送入小红书或抖音发布。
            </Paragraph>
          </div>
          <Space>
            <Tag>{auth.user?.username ?? "用户"}</Tag>
            <Button icon={<AppstoreOutlined />} onClick={() => navigate("/apps")}>应用中心</Button>
          </Space>
        </Space>
        <Tabs
          style={{ marginTop: 24 }}
          items={[
            { key: "editor", label: "剪辑台", children: editorTab },
            { key: "exports", label: "成片库", children: exportsTab },
          ]}
        />
      </Content>
      <AssetPicker
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        onConfirm={(assets) => {
          setSelectedAssets(assets);
          setPickerOpen(false);
          if (!title.trim() && assets[0]) setTitle((assets[0].title || "新成片").slice(0, 120));
        }}
      />
    </Layout>
  );
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && node --test tests/clip-workbench.test.cjs`

Expected: 2 passed。

- [ ] **Step 6: 检查点**

Run: `cd frontend && npm run typecheck && node --test tests/clip-workbench.test.cjs`

Expected: 全部通过。

---

## Task 14: 路由、应用注册、两个工作台菜单与视频工坊入口

**Files:**
- Modify: `frontend/src/apps/registry.ts`
- Modify: `frontend/src/app/router.tsx:20-30, 145-160`
- Modify: `frontend/src/components/layout/app-shell.tsx:56-70`
- Modify: `frontend/src/features/douyin/douyin-shell.tsx:1-35`
- Modify: `frontend/src/pages/platforms/xhs/video-studio-page.tsx`
- Modify: `frontend/tests/workbench.test.cjs:9-24`
- Modify: `frontend/tests/clip-workbench.test.cjs`

**Interfaces:**
- Consumes: `ClipPage`。
- Produces: 应用注册项 `clip`；受保护的 `/clip` 路由；小红书和抖音菜单入口；`/platforms/xhs/video-studio` 重定向到 `/clip?from=xhs`。

- [ ] **Step 1: 写失败的接线测试**

在 `frontend/tests/clip-workbench.test.cjs` 末尾追加：

```js
test('clip app is registered and reachable from both shells', () => {
  const registry = read('src/apps/registry.ts');
  assert.match(registry, /id: 'clip'/);
  const router = read('src/app/router.tsx');
  assert.match(router, /path="\/clip"/);
  const xhsShell = read('src/components/layout/app-shell.tsx');
  assert.match(xhsShell, /剪辑工坊/);
  assert.match(xhsShell, /"\/clip"/);
  const douyinShell = read('src/features/douyin/douyin-shell.tsx');
  assert.match(douyinShell, /剪辑工坊/);
  assert.match(douyinShell, /"\/clip"/);
  const videoStudio = read('src/pages/platforms/xhs/video-studio-page.tsx');
  assert.match(videoStudio, /Navigate/);
  assert.match(videoStudio, /\/clip\?from=xhs/);
});
```

同时修改 `frontend/tests/workbench.test.cjs`：

```js
test('registry exposes the real XHS, douyin and clip apps and never falls back for unknown IDs', () => {
  const { workbenchApps, findWorkbenchApp } = load('src/apps/registry.ts');
  assert.equal(workbenchApps.length, 3);
  assert.deepEqual(workbenchApps[0], {
    id: 'xhs', name: '小红书运营', description: '采集、内容管理、创作与发布的一站式运营工作台',
    icon: '/logo.jpg', entryPath: '/platforms/xhs/dashboard', enabled: true
  });
  assert.deepEqual(workbenchApps[1], {
    id: 'douyin', name: '抖音运营', description: '多账号采集参考、审核发布与真实数据复盘',
    icon: '/logo.jpg', entryPath: '/platforms/douyin/accounts', enabled: true
  });
  assert.deepEqual(workbenchApps[2], {
    id: 'clip', name: '剪辑工坊', description: '从内容库选素材，剪辑成片并送入小红书或抖音发布',
    icon: '/logo.jpg', entryPath: '/clip', enabled: true
  });
  assert.equal(findWorkbenchApp('clip'), workbenchApps[2]);
  for (const id of [undefined, '', 'missing', '__proto__', 'constructor']) {
    assert.equal(findWorkbenchApp(id), undefined);
  }
});
```

同文件的应用中心测试中，把 `assert.equal(view.container.querySelectorAll('[data-app-id]').length, 2)` 改为 `3`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && node --test tests/workbench.test.cjs tests/clip-workbench.test.cjs`

Expected: FAIL，注册表仍为 2 项，路由和菜单不存在。

- [ ] **Step 3: 注册应用**

在 `frontend/src/apps/registry.ts` 的 `workbenchApps` 数组末尾加入：

```ts
  {
    id: 'clip',
    name: '剪辑工坊',
    description: '从内容库选素材，剪辑成片并送入小红书或抖音发布',
    icon: '/logo.jpg',
    entryPath: '/clip',
    enabled: true
  }
```

- [ ] **Step 4: 增加受保护路由**

在 `frontend/src/app/router.tsx` 的懒加载声明区加入：

```tsx
const ClipPage = lazy(
  () => import("../features/clip/clip-page").then((m) => ({ default: m.ClipPage }))
);
```

在顶层受保护路由中、`/apps/:appId` 之后加入（不要放进 `AppShell` 路由组，剪辑工坊是独立应用，不显示小红书侧栏）：

```tsx
          <Route path="/clip" element={<ProtectedRoute>{lazyPage(<ClipPage />)}</ProtectedRoute>} />
```

- [ ] **Step 5: 增加两个工作台菜单入口**

`frontend/src/components/layout/app-shell.tsx` 的图标导入加入 `ScissorOutlined`，并在 `mainNavItems` 的「图片工坊」之前加入：

```tsx
  { key: "/clip", icon: <ScissorOutlined />, label: "剪辑工坊" },
```

`frontend/src/features/douyin/douyin-shell.tsx` 的图标导入加入 `ScissorOutlined`，并在 `mainNavItems` 的「发布中心」之前加入：

```tsx
  { key: "/clip", icon: <ScissorOutlined />, label: "剪辑工坊" },
```

- [ ] **Step 6: 把视频工坊改为跳转**

Replace `frontend/src/pages/platforms/xhs/video-studio-page.tsx` with:

```tsx
import { Navigate } from "react-router-dom";

/**
 * 兼容旧入口：视频工坊已升级为平台无关的「剪辑工坊」。
 * 保留原路径，直接跳到新应用，避免旧书签和菜单失效。
 */
export function XhsVideoStudioPage() {
  return <Navigate to="/clip?from=xhs" replace />;
}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd frontend && node --test tests/workbench.test.cjs tests/clip-workbench.test.cjs`

Expected: 全部通过。

- [ ] **Step 8: 检查点**

Run: `cd frontend && npm run typecheck && npm run build`

Expected: 类型检查与构建通过。

---

## Task 15: 抖音发布预选成片

**Files:**
- Create: `frontend/src/features/douyin/preselect.ts`
- Create: `frontend/src/features/douyin/preselect.test.ts`
- Modify: `frontend/src/features/douyin/pages/publishing-page.tsx:40-75`
- Modify: `frontend/tests/clip-workbench.test.cjs`

**Interfaces:**
- Consumes: `useSearchParams`、`form.setFieldValue`、`setUploads`。
- Produces: `readDouyinPreselect(params: URLSearchParams)`；发布页读取 `media`/`title` 后打开弹窗并预选视频。

- [ ] **Step 1: 写失败的预选解析测试**

Create `frontend/src/features/douyin/preselect.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { readDouyinPreselect } from "./preselect";

describe("readDouyinPreselect", () => {
  it("读取 media 与 title", () => {
    const params = new URLSearchParams("media=xhs-clip-u1-a.mp4&title=%E5%BC%80%E7%AE%B1");
    expect(readDouyinPreselect(params)).toEqual({
      media: "xhs-clip-u1-a.mp4",
      title: "开箱",
    });
  });

  it("缺少 media 时返回空", () => {
    expect(readDouyinPreselect(new URLSearchParams("title=x"))).toEqual({
      media: null,
      title: null,
    });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npx vitest run src/features/douyin/preselect.test.ts`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现解析函数**

Create `frontend/src/features/douyin/preselect.ts`:

```ts
export function readDouyinPreselect(params: URLSearchParams): {
  media: string | null;
  title: string | null;
} {
  const media = params.get("media");
  if (!media) {
    return { media: null, title: null };
  }
  return { media, title: params.get("title") };
}
```

- [ ] **Step 4: 接入发布页**

在 `frontend/src/features/douyin/pages/publishing-page.tsx` 的 react-router 导入中加入 `useSearchParams`：

```tsx
import { useSearchParams } from "react-router-dom";
```

在 `DouyinPublishingPage` 的状态声明后加入：

```tsx
  const [searchParams, setSearchParams] = useSearchParams();
```

在现有账号加载 `useEffect` 之后加入：

```tsx
  useEffect(() => {
    const preselect = readDouyinPreselect(searchParams);
    if (!preselect.media) return;
    setKind("video");
    setUploads([
      {
        file_name: preselect.media,
        download_url: `/api/files/media/${preselect.media}`,
        asset_type: "video",
        size: 0,
      },
    ]);
    if (preselect.title) form.setFieldValue("title", preselect.title);
    setOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("media");
    next.delete("title");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, form]);
```

并在文件顶部导入：

```tsx
import { readDouyinPreselect } from "../preselect";
```

- [ ] **Step 5: 增加前端接线断言**

在 `frontend/tests/clip-workbench.test.cjs` 末尾追加：

```js
test('douyin publishing page consumes clip preselect params', () => {
  const page = read('src/features/douyin/pages/publishing-page.tsx');
  assert.match(page, /readDouyinPreselect/);
  assert.match(page, /setUploads/);
  assert.match(page, /setOpen\(true\)/);
});
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd frontend && npx vitest run src/features/douyin/preselect.test.ts && node --test tests/clip-workbench.test.cjs`

Expected: 全部通过。

- [ ] **Step 7: 检查点**

Run: `cd frontend && npm run typecheck`

Expected: 通过。

---

## Task 16: 前端回归与对话转录（M2 完成检查）

**Files:**
- Modify: `frontend/tests/workbench.test.cjs`（已改）
- Test: `frontend/tests/clip-workbench.test.cjs`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Consumes: 前五个前端任务的全部产物。
- Produces: 前端回归结果，供 M2 验收。

- [ ] **Step 1: 运行完整前端测试**

Run: `cd frontend && npm run test:all`

Expected: vitest、node:test、playwright 全部通过。若 playwright 需要后端，先启动本地后端；失败时把失败用例与日志记录到 `docs/superpowers/verification/opencut/acceptance.md`。

- [ ] **Step 2: 运行类型检查与构建**

Run: `cd frontend && npm run typecheck && npm run build`

Expected: 通过，构建产物生成在 `frontend/dist`。

- [ ] **Step 3: 检查点**

Run: `cd frontend && npm run lint`

Expected: 通过或只报告与本次改动无关的既有告警；本次新增文件不得有 lint 错误。

---

## Task 17: 契约 stub 编辑器与编辑器服务

**Files:**
- Create: `tools/clip-editor-stub/index.html`
- Create: `tools/clip-editor-stub/Dockerfile`
- Modify: `docker-compose.yml:5-40`
- Modify: `.env.example`
- Test: `frontend/tests/clip-editor-contract.test.cjs`

**Interfaces:**
- Consumes: `POST /api/clip/sessions/{id}/exchange`、`GET /api/clip/sessions/{id}/assets/{name}`、`POST /api/clip/exports`。
- Produces: 可在 `http://127.0.0.1:3000` 打开的工作台契约编辑器，用于 M1/M2 端到端验证；OpenCut fork 完成后替换同一入口。

- [ ] **Step 1: 写失败的契约源码测试**

Create `frontend/tests/clip-editor-contract.test.cjs`:

```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('stub editor implements exchange, asset download and export upload', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'clip-editor-stub', 'index.html'), 'utf8');
  assert.match(html, /\/api\/clip\/sessions\/.*\/exchange/);
  assert.match(html, /\/api\/clip\/sessions\/.*\/assets\//);
  assert.match(html, /\/api\/clip\/exports/);
  assert.match(html, /history\.replaceState/);
  assert.match(html, /Authorization/);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && node --test tests/clip-editor-contract.test.cjs`

Expected: FAIL，文件不存在。

- [ ] **Step 3: 实现 stub 编辑器**

Create `tools/clip-editor-stub/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>剪辑工坊 · 契约测试编辑器</title>
  <style>
    body { font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; background: #141414; color: #e6e6e6; }
    main { max-width: 960px; margin: 0 auto; padding: 32px 24px; }
    h1 { font-size: 24px; margin: 0 0 8px; }
    p { color: #a6a6a6; }
    section { background: #1f1f1f; border: 1px solid #303030; border-radius: 8px; padding: 20px; margin: 16px 0; }
    button, input[type=file] { font: inherit; }
    button { background: #1668dc; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
    button:disabled { background: #333; color: #777; cursor: not-allowed; }
    ul { padding-left: 20px; }
    code { color: #9ecbff; word-break: break-all; }
    #result { white-space: pre-wrap; background: #0a0a0a; padding: 12px; border-radius: 6px; }
  </style>
</head>
<body>
<main>
  <h1>剪辑工坊 · 契约测试编辑器</h1>
  <p>这不是生产编辑器。它只验证工作台的会话交换、素材读取和成片回传契约；OpenCut fork 完成后替换同一入口。</p>
  <section>
    <p id="status">正在读取会话…</p>
    <ul id="assets"></ul>
    <p><label>选择一个 MP4 作为“导出的成片”：<input id="file" type="file" accept="video/mp4" disabled /></label></p>
    <p><button id="upload" disabled>回传成片</button></p>
    <pre id="result"></pre>
  </section>
</main>
<script>
  const apiBase = new URLSearchParams(location.search).get("api") || "http://127.0.0.1:8000";
  const hash = new URLSearchParams(location.hash.slice(1));
  const handoff = hash.get("handoff");
  const sessionId = hash.get("session");
  history.replaceState(null, "", location.pathname + location.search);

  const statusEl = document.getElementById("status");
  const assetsEl = document.getElementById("assets");
  const fileEl = document.getElementById("file");
  const uploadEl = document.getElementById("upload");
  const resultEl = document.getElementById("result");

  let sessionToken = null;

  function authHeaders() {
    return { Authorization: `Bearer ${sessionToken}` };
  }

  async function exchange() {
    if (!handoff || !sessionId) {
      statusEl.textContent = "缺少会话参数，请从工作台重新进入。";
      return;
    }
    const response = await fetch(`${apiBase}/api/clip/sessions/${sessionId}/exchange`, {
      method: "POST",
      headers: { Authorization: `Bearer ${handoff}` },
    });
    if (!response.ok) {
      statusEl.textContent = `会话交换失败（${response.status}）：${await response.text()}`;
      return;
    }
    const data = await response.json();
    sessionToken = data.session_token;
    statusEl.textContent = `会话已就绪，共 ${data.assets.length} 个素材。`;
    for (const asset of data.assets) {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = `${asset.file_name}（${asset.asset_type}，${asset.size_bytes} 字节）`;
      link.onclick = async (event) => {
        event.preventDefault();
        const fileResponse = await fetch(`${apiBase}${asset.download_path}`, { headers: authHeaders() });
        if (!fileResponse.ok) {
          resultEl.textContent = `素材读取失败：${fileResponse.status}`;
          return;
        }
        const blob = await fileResponse.blob();
        const blobUrl = URL.createObjectURL(blob);
        window.open(blobUrl, "_blank", "noopener,noreferrer");
      };
      li.appendChild(link);
      assetsEl.appendChild(li);
    }
    fileEl.disabled = false;
    uploadEl.disabled = false;
  }

  uploadEl.onclick = async () => {
    const file = fileEl.files && fileEl.files[0];
    if (!file) {
      resultEl.textContent = "请先选择一个 MP4 文件。";
      return;
    }
    uploadEl.disabled = true;
    try {
      const form = new FormData();
      form.append("session_id", sessionId);
      form.append("file", file, file.name);
      form.append("title", file.name.replace(/\.mp4$/i, ""));
      form.append("client_export_id", crypto.randomUUID());
      const response = await fetch(`${apiBase}/api/clip/exports`, {
        method: "POST",
        headers: authHeaders(),
        body: form,
      });
      resultEl.textContent = `${response.status}\n${await response.text()}`;
    } finally {
      uploadEl.disabled = false;
    }
  };

  exchange().catch((error) => {
    statusEl.textContent = `会话交换异常：${error}`;
  });
</script>
</body>
</html>
```

- [ ] **Step 4: 创建容器镜像**

Create `tools/clip-editor-stub/Dockerfile`:

```dockerfile
FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html

EXPOSE 80
```

在 `docker-compose.yml` 的 `app` 服务之后加入：

```yaml
  # --------------------------------------------------------------------------
  # 剪辑工坊契约编辑器（仅用于 M1/M2 验证；OpenCut fork 完成后替换同一入口）
  # --------------------------------------------------------------------------
  editor:
    build:
      context: ./tools/clip-editor-stub
    container_name: clip-editor-stub
    ports:
      - "${CLIP_EDITOR_BIND_ADDR:-127.0.0.1}:3000:80"
    restart: unless-stopped
```

在 `.env.example` 的剪辑配置段加入：

```bash
CLIP_EDITOR_BIND_ADDR=127.0.0.1
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd frontend && node --test tests/clip-editor-contract.test.cjs`

Expected: 1 passed。

- [ ] **Step 6: 手动契约验收**

Run: `SECRET_KEY=test docker compose up -d editor`

Expected: 容器启动，`http://127.0.0.1:3000` 可打开。

启动后端（若尚未启动）：

```bash
python main.py --with-frontend
```

在工作台创建会话并打开编辑器，按页面提示完成「素材读取 → 选择 MP4 → 回传成片」。把结果记录到 `docs/superpowers/verification/opencut/acceptance.md`，至少包含：会话创建、素材读取、成片上传、成片列表可见。

- [ ] **Step 7: 检查点**

Run: `SECRET_KEY=test docker compose config`

Expected: 配置可解析，`editor` 服务存在。

---

## Task 18: 配置文档、验收清单与全量回归

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/verification/opencut/acceptance.md`
- Modify: `docs/superpowers/specs/2026-11-11-opencut-clip-integration-design.md`（仅在实现与规格不一致时更新状态说明）

**Interfaces:**
- Consumes: 前 17 个任务的全部产物。
- Produces: 可复现的部署说明、验收记录、全量测试结果。

- [ ] **Step 1: 写验收清单**

Create `docs/superpowers/verification/opencut/acceptance.md`:

```markdown
# 剪辑工坊验收记录

- 日期：
- 分支/工作区：
- 后端测试：`python -m pytest`
- 前端测试：`cd frontend && npm run test:all`
- 构建：`cd frontend && npm run build`
- 契约编辑器：`docker compose up -d editor`

## 功能验收

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 应用中心出现「剪辑工坊」 | 待填 | 截图 |
| 小红书菜单进入剪辑工坊 | 待填 | 截图 |
| 抖音菜单进入剪辑工坊 | 待填 | 截图 |
| 原「视频工坊」路径跳转 | 待填 | URL |
| 选择内容库/草稿/上传素材 | 待填 | 截图 |
| 创建会话并打开编辑器 | 待填 | 截图 |
| 会话素材读取 | 待填 | 截图 |
| 回传 MP4 成片 | 待填 | 成片库截图 |
| 刷新后成片仍在 | 待填 | 截图 |
| 送入小红书草稿 | 待填 | 草稿页截图 |
| 抖音发布页预选成片 | 待填 | 截图 |
| 跨用户不可见 | 待填 | 接口响应 |
| 过期/重放令牌被拒绝 | 待填 | 接口响应 |
| 超大小/类型不符被拒绝 | 待填 | 接口响应 |

## 回归

| 套件 | 结果 |
| --- | --- |
| `tests/backend` | 待填 |
| `tests/douyin` | 待填 |
| `frontend` vitest | 待填 |
| `frontend` node:test | 待填 |
| `frontend` playwright | 待填 |
| `frontend` build | 待填 |

## 已知限制

- 首期工程只存浏览器本地；关闭编辑器标签页后需重新创建会话。
- OpenCut fork 尚未替换契约 stub；替换后需重跑本表。
```

- [ ] **Step 2: 更新 README**

在 `README.md` 的「Web 运营平台」功能表之后加入：

````markdown
### 剪辑工坊（OpenCut）

独立应用 `/clip`，把内容库、草稿和本地上传素材送到独立编辑器，导出 MP4 后回到工作台，可送入小红书草稿或抖音发布中心。

- 编辑器地址：`CLIP_EDITOR_PUBLIC_BASE_URL`（默认 `http://127.0.0.1:3000`）
- 允许的编辑器来源：`CLIP_EDITOR_ALLOWED_ORIGINS`
- 成片大小上限：`CLIP_MAX_EXPORT_BYTES`（默认 2GiB）
- 会话有效期：`CLIP_SESSION_TTL_HOURS`（默认 12 小时）
- 活跃会话上限：`CLIP_MAX_ACTIVE_SESSIONS`（默认 3）
- 每用户成片配额：`CLIP_USER_EXPORT_QUOTA_BYTES`

M1/M2 验证阶段使用 `tools/clip-editor-stub` 契约编辑器：

```bash
docker compose up -d editor
python main.py --with-frontend
```

OpenCut fork 完成后，将 `docker-compose.yml` 中 `editor` 服务的构建上下文替换为 fork 镜像，工作台接口不变。
````

- [ ] **Step 3: 运行全量后端测试**

Run: `python -m pytest`

Expected: 全部通过。失败时记录到 `acceptance.md` 并修复。

- [ ] **Step 4: 运行全量前端测试与构建**

Run: `cd frontend && npm run test:all && npm run build`

Expected: 全部通过。

- [ ] **Step 5: 运行迁移检查**

Run: `python -m pytest tests/douyin/test_migrations.py tests/backend/test_clip_migrations.py -v`

Expected: 全部通过。

- [ ] **Step 6: 检查点**

Run: `cd frontend && npm run lint && npm run typecheck`

Expected: 通过，本次新增文件无 lint 错误。

---

## 附录：Task 1 之后的分支计划

M0 决策为 `GO` 后，另写 `docs/superpowers/plans/2026-11-11-opencut-fork-bridge.md`，内容至少包括：

1. 用 M0 记录的固定提交创建 `vendor/OpenCut` 或独立镜像构建上下文；
2. 实现 `workbenchBridge`：读取 fragment、交换令牌、批量导入素材、导出后回传；
3. 在 OpenCut 的素材库与导出完成回调处接入 bridge；
4. 用 Task 17 的契约验收相同的四项接口行为；
5. 替换 `docker-compose.yml` 中 `editor` 服务的构建上下文，保留端口与环境变量；
6. 重跑 `docs/superpowers/verification/opencut/acceptance.md`。

在 Plan B 完成前，不得声称「OpenCut 已整合完成」；只能声称「工作台侧剪辑链路已通过契约 stub 验证」。
