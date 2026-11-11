# 已知限制（M0）

1. **主仓库不可用作集成目标**：`OpenCut-app/OpenCut` HEAD 处于重写期（Rust core、无可用编辑器 UI）。集成目标固定为 `opencut-classic @ cf5e79e919144200294fb9fed22a222592a0aeea`；fork 补丁计划（Plan B）必须针对该提交。
2. **上游迭代快**：classic 仓库无 release tag（浅克隆取 HEAD）；Plan B 开始前必须重新固定提交并复核桥接点未漂移。
3. **移动端受限**：`apps/web/src/components/editor/mobile-gate.tsx` 对小屏设备有拦截，工作台入口应提示桌面浏览器打开。
4. **字幕/转录依赖浏览器 AI 能力**：`services/transcription` 基于 @huggingface/transformers（浏览器内 wasm 推理），弱设备上转录慢；手动字幕/文本元素不受影响。
5. **导出在浏览器侧完成**：大时间线导出依赖标签页保持前台与内存；2GiB 成片上限（CLIP_MAX_EXPORT_BYTES）是服务端约束，浏览器侧另有 OPFS 配额（`services/storage/quota.ts`）限制，实际可达大小以浏览器为准。
6. **登录/云同步非必需**：better-auth + Postgres 仅服务项目云同步与登录；本地工程走 IndexedDB/OPFS。工作台桥接不依赖其登录态。
7. **运行时人工验证待补**：见 evidence/runtime-deps.md；Plan B（fork 补丁）开工前必须完成五项能力的浏览器验证。
