# 超级工作台验证报告

实施日期：2026-11-09
工作目录：`E:/code/super_work`
验证范围：统一入口（登录 → 应用中心 → 小红书运营）的前端实现、前端构建、既有后端回归与匿名浏览器检查。

本报告只记录实际执行的命令与真实输出。未执行的项目在“未覆盖范围”中逐项列明，不以计划期望代替结果。

## 1. 环境版本

| 项目 | 实际值 |
| --- | --- |
| Node.js | v24.18.0 |
| npm | 11.16.0 |
| Python | 3.12.1（`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`） |
| Vite | 7.3.2（构建输出） |
| 工作区 | 非 Git 仓库；未执行 `git init`/`add`/`commit` |

为运行既有后端测试，按 `requirements.txt` 中已声明的名称补装了本机缺失的依赖（未修改 `requirements.txt`）：

```bash
python -m pip install "python-jose[cryptography]"
python -m pip install "pydantic-settings" "passlib[bcrypt]"
python -m pip install loguru qrcode
```

实际结果：三条命令退出码均为 0。安装版本：python-jose 3.5.0、pydantic-settings 2.16.2、passlib 1.7.4、bcrypt 5.0.0、loguru 0.7.3、qrcode 8.2（以及传递依赖 ecdsa、rsa、pyasn1、win32-setctime）。

## 2. 保护基线

- 基线文件：`.workbench-verification/baseline.json`（任务 1 在业务修改前捕获，200 个受保护文件、17 个业务路由绑定、菜单与 KeepAlive 缓存片段）。
- 捕获范围（`scripts/workbench-boundary.cjs` 的 `protectedRoots`）：`backend`、`apis`、`xhs_utils`、`spider`、`static`、`libs`、`sign`、`utils`、`config`、`tests/backend`、`author`、`frontend/src/pages/platforms/xhs`、`frontend/src/lib/api.ts`、`frontend/src/lib/platforms.ts`、`frontend/src/hooks/use-auth.ts`、`frontend/src/types`、`frontend/src/app/providers.tsx`、`frontend/src/global.css`、`frontend/src/components/account`、`frontend/src/components/platforms`、`frontend/src/components/layout/platform-selector.tsx`、`frontend/src/pages/platform-select`、`frontend/src/pages/models`、`frontend/src/pages/settings`、`frontend/src/pages/tasks`、`package.json`、`package-lock.json`、`frontend/package.json`、`frontend/package-lock.json`、`requirements.txt`、`main.py`、`tests/backend`。
- 最终检查（所有测试、构建、浏览器检查结束后）：

```bash
node scripts/workbench-boundary.cjs check .workbench-verification/baseline.json
```

实际输出（退出码 0）：

```
Protected files, menus, cache and all 17 business route bindings unchanged
```

说明：首次在完整后端测试后执行该项检查时，既有后端测试在 `backend/app/storage/exports/` 与 `backend/app/storage/media/` 下生成了 10 个运行产物（6 个导出文件、4 个媒体文件），属于测试运行副作用而非源码改动。确认这些文件均为本轮测试新建后将其删除，再执行上述检查通过。清理后工作区无 `*.db` 文件，未打开或创建真实业务数据库。

锁文件未修改（与任务 1 记录一致）：

```
97f6b446d44436df9efcd75c14dc15c4964335aace70ab0eeaed3e0f19434dec *package-lock.json
a8443ef6af9559856b127a966f4eb4eb73a0601e0c417cd65fba80721e91c3ae *frontend/package-lock.json
```

## 3. 生产源码新增与修改文件

新增：

- `scripts/workbench-boundary.cjs`（保护基线工具）
- `frontend/src/apps/registry.ts`（应用注册表）
- `frontend/src/pages/apps/app-center-page.tsx`（应用中心）
- `frontend/src/pages/apps/app-entry-page.tsx`（应用入口解析）
- `frontend/tests/helpers/render.cjs`（测试专用加载/DOM 助手，不进入构建）
- `frontend/tests/workbench.test.cjs`（测试）

修改：

- `frontend/src/app/router.tsx`
- `frontend/src/components/ui/protected-route.tsx`
- `frontend/src/pages/login/login-page.tsx`
- `frontend/src/components/layout/app-shell.tsx`

本轮新增的本地验证产物：

- `docs/superpowers/verification/2026-11-09-super-workbench.md`（本文件）
- `.claude/launch.json`（此前不存在，按任务简报创建）
- `.workbench-verification/test-config.yaml`
- `.workbench-verification/backend-pytest.log`
- `.workbench-verification/backend-pytest-alembic-no-dburl.log`

未修改 `package.json`、两个锁文件、`requirements.txt`、后端源码、后端测试、小红书业务页面/接口。

## 4. 前端测试

命令（工作目录 `E:/code/super_work`）：

```bash
node --test frontend/tests/workbench.test.cjs
```

实际结果：退出码 0。

```
ℹ tests 18
ℹ suites 0
ℹ pass 18
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 4184.3643
```

覆盖内容：注册表、应用中心、应用入口、匿名守卫、已认证落点、应用中心选择后的业务路由、深链接、登录/注册落点、外壳应用中心入口。

警告（均来自未修改的既有 antd 用法，非测试失败）：

- `[antd: Statistic] valueStyle is deprecated`
- `[antd: Button] iconPosition is deprecated`
- `[antd: Dropdown] dropdownRender is deprecated`

## 5. 前端生产构建

命令：

```bash
npm --prefix frontend run build
```

实际执行 `tsc && vite build`，退出码 0；TypeScript 类型检查通过，不只是转译。

```
vite v7.3.2 building client environment for production...
✓ 3223 modules transformed.
dist/index.html                  0.54 kB │ gzip:   0.33 kB
dist/assets/index-D0BDiybC.css   1.31 kB │ gzip:   0.58 kB
dist/assets/index-Ce9-UBnD.js  1,797.65 kB │ gzip: 555.10 kB
✓ built in 10.68s
```

构建警告：单个 JS chunk 超过 500 kB（1,797.65 kB），为既有体积提示，不构成失败。

## 6. 后端回归测试

先按任务简报创建本地覆盖配置（不修改 `config/default.yaml`），实际内容：

```
scheduler:
  enabled: false
```

执行命令：

```bash
CONFIG_FILE=.workbench-verification/test-config.yaml SCHEDULER_ENABLED=false DATABASE_URL=sqlite:// python -m pytest tests/backend -q
```

实际结果：退出码 1，耗时 118.11 秒。

```
2 failed, 128 passed, 7 warnings in 118.11s (0:01:58)
```

失败项：

- `tests/backend/test_api.py::test_database_initialization_creates_user_table`
- `tests/backend/test_api.py::test_alembic_initial_migration_creates_all_product_tables`

原因已定位：`backend/alembic/env.py` 的 `_get_url()` 优先读取进程环境变量 `DATABASE_URL`，其次才读取测试通过 `alembic.Config` 设置的 `sqlalchemy.url`。因此简报规定的 `DATABASE_URL=sqlite://` 会使迁移写入进程内存数据库，而测试随后检查的是各自 `tmp_path` 下的临时 SQLite 文件，表中无表。这是“简报规定的环境变量”与既有 alembic 测试的交互，不是本轮工作台代码改动导致；未修改后端代码或测试来规避。

补充验证（仅这两项，去掉 `DATABASE_URL`，保持 `CONFIG_FILE` 关调度器）：

```bash
CONFIG_FILE=.workbench-verification/test-config.yaml SCHEDULER_ENABLED=false python -m pytest "tests/backend/test_api.py::test_database_initialization_creates_user_table" "tests/backend/test_api.py::test_alembic_initial_migration_creates_all_product_tables" -q
```

实际结果：退出码 0，`2 passed, 1 warning in 2.99s`。该补充命令未连接真实业务库（`create_engine` 为惰性连接，这两个测试只迁移各自的 `tmp_path` 文件）；执行后确认工作区没有任何 `*.db` 文件。

隔离性核对：

- 测试使用模块级 `TestClient(app)` 且未以上下文管理器进入 lifespan，服务器与调度器未启动；覆盖配置也显式关闭调度器。
- 需数据库的接口测试通过 `app.dependency_overrides` 使用 `tmp_path` 下的临时 SQLite；采集、监控、登录、发布等测试使用 Fake adapter；唯一的真实网络调用（AI 客户端）被 `monkeypatch` 替换。
- 未运行 `uvicorn`/`main.py`，未启动后端服务，未打开真实业务数据库。

结论：既有后端测试在本环境实际为 **128 通过、2 失败（均为 `DATABASE_URL` 与 alembic 测试的交互）**；这 2 项在各自隔离方式下可单独通过。不能表述为“后端测试全部通过”。

后端警告（非失败）：Starlette 提示 httpx/TestClient 弃用；既有测试中 `datetime.utcnow()` 的 6 条弃用警告。

## 7. 浏览器检查（仅匿名，未启动后端）

前置：调用 `run` 技能；确认 `.claude/launch.json` 不存在后按简报创建；使用 `preview_start` 启动 Vite 开发服务器（`npm --prefix frontend run dev -- --host 127.0.0.1`，端口 5173），未用 Bash 启动服务器；未启动后端。

实际检查：

| 路径 | 结果 |
| --- | --- |
| `/apps` | 重定向到 `/login`（`location.pathname === '/login'`） |
| `/apps/xhs` | 重定向到 `/login` |
| `/platform-select` | 重定向到 `/login`；等待 1.5 秒后仍为 `/login`，无跳转循环 |

视口检查：

- 375×812（mobile）：登录页正常渲染，`scrollWidth = clientWidth = 375`，无横向溢出；登录表单可见。
- 1280×800（desktop）：登录页正常渲染，`scrollWidth 1274 / clientWidth 1274`，无横向溢出。
- 主题：模拟 `prefers-color-scheme: light` 后页面仍按应用自身深色主题渲染（`body` 背景 `rgba(20, 20, 20, 0.85)`、卡片背景 `rgb(26, 26, 26)`、标题 `rgb(255, 255, 255)`）；未单独验收应用中心的深浅主题切换。
- 截图：已检查 mobile 与 desktop 登录页截图，布局正常，非空白页。

控制台与网络：

- 控制台仅有 3 条既有 antd 弃用警告（`Statistic valueStyle`、`Button iconPosition`、`Dropdown dropdownRender`），无未捕获运行时错误。
- 网络面板无失败请求（匿名登录页不调用后端；未启动后端也未产生失败 API 请求）。

**已认证页面浏览器视觉验收未执行。** 本轮浏览器工具不具备安全的认证/网络 mock 条件；按任务约束未伪造登录状态、未注入 token、未伪造应用中心 DOM。应用中心的已认证行为、未知/禁用入口、登录注册落点与外壳折叠返回入口由 `frontend/tests/workbench.test.cjs` 的 DOM 集成测试覆盖，不替代真实浏览器视觉验收。

检查结束后已 `preview_stop` 停止预览服务器；确认 5173/8000 无 LISTENING 进程。

## 8. 未覆盖范围

- 未执行真实小红书采集、发布、账号绑定、外部模型调用或定时任务触发。
- 未启动后端服务，未运行真实应用 lifespan。
- 未打开真实业务数据库；工作区最终无 `*.db` 文件。
- 未做已认证页面（应用中心、小红书各业务页）的真实浏览器视觉验收。
- 未实测全部外部小红书功能，不能据此声称所有小红书外部行为已验证。
- 当前目录不是 Git 仓库：未初始化 Git、未创建任何提交或 PR。
- 后端测试有 2 项在简报规定的 `DATABASE_URL=sqlite://` 下因既有 alembic 配置优先级失败；已记录确切原因与隔离补充结果。

## 9. 结论

- 前端：18/18 测试通过，`tsc && vite build` 退出码 0。
- 保护边界：200 个受保护文件、菜单、KeepAlive 缓存与 17 个业务路由绑定全部未变。
- 匿名入口：`/apps`、`/apps/xhs`、`/platform-select` 均安全落到原登录页，无跳转循环；375px 与桌面宽度无横向溢出。
- 后端：既有测试 128 通过、2 失败（环境变量与 alembic 测试交互，非本次功能代码）；补充隔离运行 2/2 通过。
- 已认证页面浏览器视觉验收未执行，外部小红书行为未实测。

## 10. 终审后的文案修正（用户批准）

终审将登录页旧文案列为“计划禁止改动、需用户决定”的项。用户于 2026-11-09 确认修正后，只改动 `frontend/src/pages/login/login-page.tsx:320-322` 的提示句：

- 登录模式：“登录后选择应用，进入对应工作台。”
- 注册模式：“注册后会自动进入应用中心。”

复验（改动后实际执行）：

```bash
node --test frontend/tests/workbench.test.cjs
npm --prefix frontend run build
node scripts/workbench-boundary.cjs check .workbench-verification/baseline.json
```

- 前端测试：18 通过、0 失败。
- 构建：`tsc && vite build` 退出码 0。
- 保护检查：受保护文件、菜单、缓存与 17 条业务路由仍全部未变（登录页不在保护范围，小红书与后端文件未受影响）。

浏览器复验（`preview_start` 启动前端，未启动后端）：`/login` 直接显示新登录文案；点击“注册”后确认密码字段出现并显示新注册文案；页面中不再出现“平台选择页”旧文案。复验后已 `preview_stop`。
