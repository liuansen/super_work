# OpenCut 源码评审（M0）

- 评审日期：2026-11-12
- 评审人：工作台侧自动化评审（ZCode 会话）

## 候选仓库

| 仓库 | 固定提交 | 结论 |
| --- | --- | --- |
| `OpenCut-app/OpenCut`（主仓库） | `e668010778568641babef2cc40be4703ae6916d6` | **不适用**：README 自述「正在从零重写」（Rust core + Moon 工作区），无可用编辑器。上一代可用版本指向 `opencut-app/opencut-classic` |
| `opencut-app/opencut-classic`（本 M0 评审对象） | `cf5e79e919144200294fb9fed22a222592a0aeea` | **适用**：opencut.app 当前线上运行的编辑器 |

## 固定提交（评审对象）

`cf5e79e919144200294fb9fed22a222592a0aeea`（opencut-classic，浅克隆 HEAD，2026-11-12）

## 许可证

- 文件：仓库根 `LICENSE`
- 类型：**MIT**（"Permission is hereby granted, free of charge... to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies"）
- 结论：允许复制、修改、再分发、集成进本工作台（含商业用途），须保留版权声明。**无使用方式障碍。**
- 上游 96 文件级依赖（apps/web/package.json）中含第三方库，各自许可证（MIT/Apache 系为主）不改变"作为整体 fork 使用"的 MIT 结论；fork 补丁计划（Plan B）落地时需复核生成字体精灵等脚本产物的字体许可。

## 运行环境（以仓库文件为准）

- 包管理器：**bun@1.2.18**（根 package.json `packageManager` 字段；`bunfig.toml` 设 `minimumReleaseAge=7d`）
- 工作区：bun workspaces（`apps/*`、`packages/*`）+ turbo
- Web 应用：Next.js 16（`apps/web`，`next dev --turbopack`，默认端口 3000）
- 渲染：`opencut-wasm@^0.2.10`（**已发布到 npm 的预编译 wasm**，本地无需 Rust/wasm-pack 即可运行）
- 可选服务：docker-compose 提供 postgres:17（better-auth 项目云同步）+ redis + serverless-redis-http；**编辑与导出本身是浏览器侧能力（IndexedDB/OPFS 存储），本地跑编辑器不强制数据库**
- 构建/启动：`bun install` → `bun run dev:web`（turbo 转发到 apps/web 的 next dev）

## 桥接扩展点（源码定位）

| 需求 | 位置 | 结论 |
| --- | --- | --- |
| 素材导入函数 | `apps/web/src/commands/media/add-media-asset.ts` → `AddMediaAssetCommand({ projectId, asset: Omit<MediaAsset,"id"> })`；媒体文件处理在 `apps/web/src/media/`（use-paste-media 等） | fork bridge 拉取工作台素材后构造 `MediaAsset` 并派发该命令即可进时间线素材库 |
| 导出完成回调 | `apps/web/src/export/index.ts` → `ExportResult { success, buffer }`；`downloadBuffer({buffer, filename, mimeType})`；导出 UI 在 `apps/web/src/components/editor/export-button.tsx` | 在导出成功、`buffer` 可用处接入 bridge：POST 到 `/api/clip/exports` |
| 请求附加 Authorization | 全 src 无既有带凭证的 fetch 封装（grep `Authorization` 无命中） | bridge 需自带 fetch 封装（与契约 stub 相同做法）；不与 better-auth 会话耦合 |
| 本地存储 | `apps/web/src/services/storage/`：`IndexedDBAdapter` + `OPFSAdapter` + `quota.ts` | 项目/媒体存浏览器侧；关闭标签页后工程可恢复（按 project_id），素材源文件在 OPFS |
| 新标签页访问限制 | `apps/web/src/app/editor/[project_id]/page.tsx` 无登录重定向；编辑器按 `project_id` 从本地存储装载 | 从工作台新标签页直达编辑器可行；云同步/登录（better-auth）为可选功能 |

## 五项能力（源码级定位，运行时验证见 evidence/runtime-deps.md）

| 能力 | 源码证据 | 源码结论 |
| --- | --- | --- |
| 多段视频/图片拼接 | `apps/web/src/components/editor/scenes-view.tsx`、`timeline/`（多轨时间线）、`commands/timeline/element/insert-element.ts` | 有 |
| 裁剪首尾 | `commands/timeline/element/split-elements.ts`、trim 类命令与属性面板 | 有 |
| 背景音乐 | 素材面板支持 audio 资产、`services/waveform-cache`、`export` 的 `includeAudio` 选项 | 有 |
| 字幕/标题 | `subtitles/parse.ts`、`subtitles/insert.ts`（SRT 解析/插入）、text 元素与 `services/transcription` | 有 |
| 封面帧 | thumbnail 相关命令与导出选项 | 有 |
| 导出 MP4 | `export/index.ts`（mp4/webm + 4 档质量）+ `services/renderer/`（wasm-compositor + gpu-renderer） | 有（浏览器侧渲染，无需服务端 ffmpeg） |

## 已知限制

见 `evidence/known-limits.md`。
