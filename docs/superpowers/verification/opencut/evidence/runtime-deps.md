# 运行环境与构建方式（以仓库文件为准，非记忆）

来源：`opencut-classic @ cf5e79e919144200294fb9fed22a222592a0aeea`

- 包管理器：bun@1.2.18（根 package.json `packageManager`）
- 工作区：`apps/*`、`packages/*`（bun workspaces）+ `turbo.json`
- Web：`apps/web`，脚本 `dev: next dev --turbopack` / `build: next build` / `start: next start`
- 启动：根目录 `bun run dev:web`（= turbo run dev --filter=@opencut/web），默认端口 3000
- 渲染依赖：`opencut-wasm@^0.2.10`（npm 预编译包，`rust/wasm` 源码仅维护者需要 wasm-pack 构建）
- 可选后端：`docker-compose.yml` = postgres:17 + redis:7 + serverless-redis-http（better-auth 项目同步/云功能用）
- 环境变量样例：`apps/web/.env.example`（`DATABASE_URL`、`BETTER_AUTH_SECRET`、`UPSTASH_REDIS_REST_URL` 等，均为云同步/登录/素材库增强；编辑器本体验证不需要全部）

## 运行时验证状态

- bun 工具链安装与 `bun install` + `bun run dev:web` 启动：在本会话后台进行中（网络受限环境，大型 monorepo 安装耗时）
- 五项能力的人工浏览器验证（截图/录屏）：**待运行时验证完成后补录**；在完成前，能力结论以源码级定位为准（见 source-review.md）
- 该缺口不阻塞工作台侧（Plan A / Task 2-18）：工作台链路按计划以 `tools/clip-editor-stub` 契约编辑器开发与验收，不依赖 OpenCut 运行时
