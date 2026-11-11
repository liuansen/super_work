# 剪辑工坊验收记录

- 日期：2026-11-12
- 分支/工作区：E:/code/super_work（master，未提交工作区）
- 后端测试：`python -m pytest` → 见下方回归表
- 前端测试：`cd frontend && npm run test:all`（vitest + node:test；playwright 见已知限制）
- 构建：`cd frontend && npm run build`
- 契约编辑器：`docker compose up -d editor`

## 功能验收

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 应用中心出现「剪辑工坊」 | 通过（自动化） | `tests/workbench.test.cjs` 注册表 3 应用断言 |
| 小红书菜单进入剪辑工坊 | 通过（自动化） | `tests/clip-workbench.test.cjs` shell 断言 |
| 抖音菜单进入剪辑工坊 | 通过（自动化） | 同上 |
| 原「视频工坊」路径跳转 | 通过（自动化） | video-studio-page → `/clip?from=xhs` 断言 |
| 选择内容库/草稿/上传素材 | 通过（接口级） | `tests/backend/test_clip_assets.py`（三类来源 + 过滤 + 搜索 + 跨用户隔离） |
| 创建会话并打开编辑器 | 通过（接口级） | `tests/backend/test_clip_sessions.py`（201 + editor_url + handoff_token） |
| 会话素材读取 | 通过（接口级） | `tests/backend/test_clip_stream.py`（200 + Range 206 + 404 + 401 + 410） |
| 回传 MP4 成片 | 通过（接口级） | `tests/backend/test_clip_exports.py`（幂等重试 201/200 + 类型/超限 400/413 + 配额 413） |
| 刷新后成片仍在 | 通过（接口级） | 成片列表持久化于 clip_exports 表 |
| 送入小红书草稿 | 通过（接口级） | `tests/backend/test_clip_draft_handoff.py`（幂等创建 + 删除草稿释放引用回归） |
| 抖音发布页预选成片 | 通过（自动化） | `preselect.test.ts` + publishing-page 接线断言 |
| 跨用户不可见 | 通过（接口级） | 素材目录/成片列表/删除/转草稿的跨用户用例 |
| 过期/重放令牌被拒绝 | 通过（接口级） | 410（握手过期/会话过期）、409（exchange 重放，条件更新防并发）、401（ver 不匹配） |
| 超大小/类型不符被拒绝 | 通过（接口级） | 413 / 400（ftyp 魔数校验） |
| 删除成片保护 | 通过（接口级） | 关联草稿 409；通用媒体删除接口对 xhs-clip- 前缀 409 |

## 回归

| 套件 | 结果 |
| --- | --- |
| `tests/backend` + `tests/douyin` + `tests/douyin_validation` | 329 passed（终审后） |
| frontend vitest | 10 passed（含 clip 单测 3 + preselect 2） |
| 五轮评审回归 | 每轮修复后全量重跑；新增回归测试 10 条（FK 释放/重放 409/ver 吊销/配额/越权/删除保护/孤儿草稿/completed 过期/unlink 容错/凭据头） |
| frontend node:test | workbench 18 / clip-workbench 4 / qr-login 4 / editor-contract 1，全部通过 |
| frontend build | 通过 |
| frontend playwright | 见「已知限制」 |

## 浏览器人工验收（M1/M2 契约链路）

待执行（需要桌面浏览器 + 本地起服务）：

```bash
docker compose up -d editor          # 或任何静态服务器伺服 tools/clip-editor-stub
python main.py --with-frontend       # 工作台 + API
```

1. 登录工作台 → 应用中心 → 剪辑工坊；
2. 填写标题、选择素材（内容库/草稿/上传）→ 新建剪辑 → 新标签页打开 stub 编辑器；
3. stub 内确认「会话已就绪」→ 点击素材链接验证读取 → 选择本地 MP4 → 回传成片；
4. 回到工作台成片库刷新 → 成片可见 → 送入小红书草稿 / 用于抖音发布。

## 已知限制

- 首期工程只存浏览器本地；关闭编辑器标签页后需重新创建会话。
- OpenCut fork 尚未替换契约 stub；替换后需重跑本表（Plan B 前置：完成 M0 运行时人工验证，见 decision.md）。
- Playwright e2e 需要先 `npx playwright install chromium`（本机网络下载超时，CI 已配置自动安装）。
