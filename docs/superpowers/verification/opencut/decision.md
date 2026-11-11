# OpenCut 接入决策

- 固定提交：`cf5e79e919144200294fb9fed22a222592a0aeea`（opencut-app/**opencut-classic**；主仓库 `OpenCut-app/OpenCut @ e668010778568641babef2cc40be4703ae6916d6` 处于重写期，不作为集成目标）
- 许可证：MIT —— 允许复制/修改/再分发/集成（含商用），须保留版权与许可声明。**无使用障碍**
- 运行方式：`bun install && bun run dev:web`（apps/web = Next.js 16，默认端口 3000；渲染用 npm 预编译 `opencut-wasm`，无需本地 Rust）；Postgres/Redis 仅为可选的登录与云同步
- 决策：**GO**（工作台侧 Plan A：Task 2-18 立即执行；fork 补丁 Plan B 另行编写，见「后续」）

## 五项能力

| 能力 | 结论（源码级） | 证据 |
| --- | --- | --- |
| 多段视频/图片拼接 | 通过（源码确认多轨时间线 + 场景视图） | `scenes-view.tsx`、`timeline/`、`insert-element.ts` |
| 裁剪首尾 | 通过（split/trim 命令体系） | `split-elements.ts`、属性面板 |
| 背景音乐 | 通过（audio 资产 + 波形缓存 + 导出 includeAudio） | `panels/assets`、`waveform-cache`、`export/index.ts` |
| 字幕/标题 | 通过（SRT 解析插入 + 文本元素 + 可选转录） | `subtitles/parse.ts`、`subtitles/insert.ts` |
| 封面帧 | 通过（缩略图命令 + 首帧渲染） | `commands/`、renderer |
| 导出 MP4 | 通过（浏览器侧渲染 mp4/webm 4 档质量，无需服务端 ffmpeg） | `export/index.ts`、`services/renderer/` |

运行时人工验证（浏览器逐项操作 + 截图）：**待补**（见 evidence/runtime-deps.md）。该缺口不阻塞工作台侧集成——工作台按计划以契约 stub 编辑器开发与验收。

## 桥接可行性

- **素材导入**：`AddMediaAssetCommand`（`commands/media/add-media-asset.ts`）接受结构化 `MediaAsset`，bridge 拉取工作台素材文件后构造并派发即可 —— 可行
- **导出回传**：`ExportResult.buffer` 在导出成功处可得，`downloadBuffer` 是现有落地点；bridge 在此 POST `/api/clip/exports` —— 可行
- **Authorization**：上游无既有凭证 fetch 封装，bridge 自带（与契约 stub 相同方式），不与 better-auth 耦合 —— 可行
- **CORS/Range**：工作台侧已规划 `/api/clip/*` 作用域 CORS（Task 2）与 Range 206 素材流（Task 7），满足浏览器跨域拉流与拖动播放 —— 可行
- **存储**：项目数据 IndexedDB/OPFS（浏览器侧），服务端只管素材下发与成片回传 —— 匹配工作台会话模型
- **新标签页**：`/editor/[project_id]` 无登录重定向，工作台 fragment 传参 + `history.replaceState` 擦除令牌可行

## 后续

GO：按本计划 Task 2 继续（工作台侧 Plan A，契约 stub 编辑器）。OpenCut fork 补丁（Plan B）在以下前置满足后另行编写 `docs/superpowers/plans/2026-11-11-opencut-fork-bridge.md`：
1. 完成 evidence/runtime-deps.md 中的运行时人工验证（五项能力截图）；
2. 针对 `cf5e79e9` 重新固定提交并复核桥接点未漂移。
在 Plan B 完成前，不得声称「OpenCut 已整合完成」；只能声称「工作台侧剪辑链路已通过契约 stub 验证」。
