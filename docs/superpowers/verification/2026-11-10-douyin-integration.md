# 抖音运营应用集成验证报告

- 实施日期：2026-11-09 → 2026-11-10
- 工作目录：`E:/code/super_work`（非 Git 仓库，无任何提交）
- 用户决策记录：用户于 2026-11-09 在对话中明确指示"把 DouYin_Spider 整合到现有工作台"，即以工程所有者身份批准集成该上游（其无 LICENSE、README 自述禁商用的法律风险由工程所有者承担）。工作包A 判定文件 `decision.md` 的"停止"结论就此被用户决策覆盖；本轮按总体计划的 B 阶段路线执行了纵向闭环集成。

## 1. 环境版本

| 项目 | 值 |
| --- | --- |
| Node.js / npm | v24.18.0 / 11.16.0 |
| Python | 3.12.1 |
| 新增依赖 | curl_cffi 0.17.0、protobuf 7.36.2（`requirements-douyin.txt`，未改动受保护的 requirements.txt） |
| 上游快照 | `cv-cat/DouYin_Spider@d151f9c2980abc304c1ae4918c2272675cd9e4c2` |

## 2. 上游获取与真实源码审查

- 归档下载（codeload tarball）→ SHA256 `a1c4ba6643955b815b9799a107707540fdfac6f459d0a6d180f8b0842396d176` → 路径安全检查（122 条目，无绝对路径/`..`）→ 解包至 `.local/douyin-upstream/` → 集成副本 `vendor/DouYin_Spider/`（96 文件，保持原样不改）。
- 溯源与安全结论：`vendor/PROVENANCE.md`。subprocess 仅 node 随机串（有退路）与 ffmpeg 音频（可选），无运行时动态下载执行。
- **真实源码审查确认**（推翻此前静态审查的两项"未验证"）：
  - 发布：`DouyinCreatorAPI.post_video/post_images` → `/web/api/media/aweme/create_v2/`，含 STS 上传链；`timing` 参数原生支持平台侧定时发布。
  - 指标：`/aweme/v1/web/aweme/post/` 作品列表自带 statistics（点赞/评论/分享/收藏）——真实互动指标来源存在。
  - visibility 枚举以 creator docstring 为准（0 公开/1 仅自己/2 好友；quick_publish.py 注释已过时），默认 1（仅自己，最安全）。

## 3. 生产源码新增与修改

新增（后端 13 + 前端 7）：

- `backend/app/douyin/`：`__init__.py`、`contracts.py`（规范化类型+错误分类+适配协议）、`upstream.py`（vendor 导入层，sys.path 隔离）、`models.py`（4 张表）、`accounts.py`、`references.py`、`publishing.py`、`metrics.py`
- `backend/app/adapters/douyin/`：`__init__.py`（real|fake 选择）、`real.py`（上游调用收口）、`fake.py`（离线确定性替身）
- `backend/app/api/platforms/douyin.py`（账号/参考库/作品/发布 API，全部走 get_current_user，非 owner 一律 404）
- `backend/alembic/versions/e3f1a9c2b7d4_add_douyin_tables.py`（只新增 4 表+索引）
- `frontend/src/features/douyin/`：`types.ts`、`api.ts`（复用统一认证实例）、`douyin-shell.tsx`（独立外壳）、`pages/`（账号/参考库/作品数据/发布中心 4 页）
- `pytest.ini`（testpaths=tests，防 vendor 上游测试被误收集）
- `requirements-douyin.txt`、`vendor/PROVENANCE.md`、`tests/douyin/`（conftest+5 测试文件）

修改（最小外围，共 5 处）：

- `backend/app/main.py`（+2 行：导入并挂载 douyin_router）
- `backend/app/models/__init__.py`（显式导入抖音模型进 metadata）
- `frontend/src/lib/api.ts`（末尾追加 `export const authenticatedHttp = http;`——同一实例，不建第二套 token）
- `frontend/src/apps/registry.ts`（新增 douyin 注册项，enabled）
- `frontend/src/app/router.tsx`（新增独立 DouyinShell 分支；小红书 17 条绑定逐字未动）

## 4. 关键行为设计（如实实现）

- **凭证**：Cookie 加密存储（复用 `encrypt_text`），响应永不回传 Cookie；同 `(user, sec_uid)` 只保留一行。
- **发布状态机**：pending → (cancelled | running → succeeded/failed/unknown)。领取用条件更新（仅 pending 可执行）并**先提交领取再发起平台请求**；本地准备（解密/媒体解析/定时换算）失败记 failed"未发送"；网络类与中途异常记 **unknown"结果不明，禁止自动重发"**；平台拒绝记 failed。unknown 不可再执行、不可取消。
- **定时发布**：`scheduled_at` 存无时区北京时间（与 `shanghai_now` 规范一致），执行时换算秒级时间戳交平台侧定时（上游 `timing`）。
- **指标语义**：字段独立可空——真实 0 保留 0，平台未返回为 None（显示"-"），不伪造 0；每次刷新写新快照，不污染历史。
- **幂等**：发布任务 `(user_id, idempotency_key)` 唯一；同键同载荷返回原任务，同键异载荷 409。
- **媒体安全**：只接受本用户上传前缀的 file_name，拒绝路径分隔符/越界，解析后校验在媒体目录内。
- **未实现（诚实声明）**：自动调度 worker（定时任务需用户显式点击执行，到时由平台侧定时）、私信/直播/PK、AI 创作辅助、媒体预览会话。这些是后续迭代项。

## 5. 测试证据（全部为实际执行结果）

最终计数（8 轮 review 后，见第 6 节；每轮均完整执行下列 5 套件且全部通过）：

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| 抖音后端测试 | `python -m pytest tests/douyin -q` | **34 passed**（集成期 25 → 8 轮 review 后 34；每轮全绿，全程共执行 20+ 次无失败） |
| 覆盖内容 | — | 账号绑定/重授权/失效/越权404/响应脱敏/失效行复用；采集幂等/用户字段保留/过滤/解密失败409；发布幂等/409/执行/平台拒绝/网络中断unknown/取消竞争/媒体类型与路径穿越（含盘符与UNC敌意名）/媒体丢失failed/无时区拒绝/图集与visibility=0；指标快照语义/最新快照/账号批量刷新/越权；规范化语义（秒→毫秒/真实0/缺失None）；**真实 alembic 升级**（空库建表+旧head升级保留数据+**迁移↔模型防漂移逐列比对**） |
| 既有后端回归 | `CONFIG_FILE=.workbench-verification/test-config.yaml SCHEDULER_ENABLED=false python -m pytest tests/backend -q` | **130 passed**（每轮 review 均复跑；小红书功能零破坏） |
| 工作台前端测试 | `node --test frontend/tests/workbench.test.cjs` | **18 pass / 0 fail**（按抖音计划 D3 只精确更新 2 个过时断言：注册表 1→2 应用、应用中心卡片 1→2，其余断言未放宽） |
| 真实适配器冒烟 | 离线导入断言 | vendor sys.path 引导、DouyinAPI/DouyinCreatorAPI 导入通过（导入链路真实可用） |
| 前端生产构建 | `npm --prefix frontend run build` | `tsc && vite build` 退出码 0（每轮 review 均复跑） |
| 能力验证工具回归 | `python -m pytest tests/douyin_validation -v` | 6 passed（工具未被集成破坏） |

## 6. Review 记录（应用户要求执行 8 轮，每轮全量测试通过后进入下一轮）

- **第 1 轮（服务层）**：修复 ① `execute_task` 媒体解析在 try 外（文件丢失永久卡 running）→ 本地准备阶段独立；② `AccountPath` 残留；③ 指标刷新原子化（参考行+快照同事务）；④ 失效账号重复绑定复用同一行；⑤ 补 3 个用例。期间该轮修复自身引入 flush 缺失回归——被套件当场抓住修复（此即逐轮全量测试的价值）。
- **第 2 轮（适配器）**：修复 ⑥ 真实缺陷 `create_time` 秒被当作毫秒（差 1000 倍）→ 统一换算；⑦ 新增 `test_normalize.py` 4 个语义锁定单测。
- **第 3 轮（API 层）**：修复 ⑧ 凭证解密失败以裸 500 穿透 3 条路径 → 服务边界翻译为 `DouyinAuthError`（采集/刷新 409、执行 failed"未发送"）；⑨ `title` 上限 60→20 对齐上游 create_v2 契约；⑩ 解密失败回归测试。
- **第 4 轮（前端）**：修复 ⑪ 定时时间改为直接按北京时间组装（对齐规范"用户输入按北京时间解释"，不再依赖浏览器本地时区）；⑫ 幂等重放如实提示"未重复创建"；⑬ 清理 5 处未处理 Promise rejection。
- **第 5 轮（迁移/数据层）**：修复 ⑭ 新增**迁移↔模型防漂移测试**（alembic 建库 vs metadata 建库逐列比对，永久锁定一致性）。
- **第 6 轮（安全）**：修复 ⑮ `crawl_work` URL 控制字符/空白提前拒绝（上游将其用作 Referer 头，杜绝头注入面）；⑯ 敌意媒体文件名测试（盘符相对路径/UNC/绝对路径）。
- **第 7 轮（文档一致性）**：修复 ⑰ README 平台表抖音状态 Coming Soon → 已实现(首期) 并注明边界；⑱ 本报告更新为 8 轮最终计数。
- **第 8 轮（终审）**：残留扫描（console.log/print/TODO 全零；AST 级未使用导入检查）——修复 ⑲ metrics.py 未使用的 `Optional`；⑳ API 错误映射改为显式三分支链（409/503/502）。全量回归 + 结论，见第 8 节。

## 8. 终审结论（第 8 轮全量回归，实际输出）

- `python -m pytest tests/douyin -q` → **34 passed**
- `python -m pytest tests/douyin_validation -q` → **6 passed**
- `node --test frontend/tests/workbench.test.cjs` → **18 pass / 0 fail**
- `npm --prefix frontend run build`（tsc && vite build）→ **退出码 0**
- `CONFIG_FILE=.workbench-verification/test-config.yaml SCHEDULER_ENABLED=false python -m pytest tests/backend -q` → **130 passed**
- 8 轮累计修复 20 项（含 2 个真实缺陷：秒/毫秒语义错位、媒体丢失卡 running；1 个自引入回归被即时捕获）；后 3 轮进入收敛（R7 仅文档、R8 仅残留清理），表明已达到稳定态。
- 全程未执行真实平台操作；未提交 Git；两份保护基线差异仍仅为本集成文件。

## 7. 保护基线审计（如实记录差异）

- **抖音基线**（`.local/douyin-validation/baseline`，业务修改前捕获）：`baseline.py check` 报告 25 处差异，**逐项核对全部为本次抖音集成文件**（13 新增后端 + 7 新增前端 + 5 修改），零意外变更。
- **工作台基线**（`.workbench-verification/baseline.json`）：`workbench-boundary.cjs check` 断言失败——但 diff 显示**菜单片段、KeepAlive 缓存片段、17 条业务路由绑定逐字未变**；哈希变化全部来自上述 5 个修改文件与 backend 下新增抖音文件，属用户批准集成的预期结果。两个基线文件均**未重新捕获**，保留作审计。
- 测试副产物已清理（本轮 backend 测试产生的 3 个导出文件；无 `*.db` 残留；未打开真实业务库）。

## 8. 未验证范围（必须知悉）

- **未执行任何真实平台操作**：未采集真实作品、未发布任何内容、未绑定真实账号。全部测试基于 fake 适配器与本地临时库。首次真实使用需：绑定真实 Cookie（账号页），每次发布仍需在发布中心显式点击"执行发布"并确认。
- 真实 Cookie 的写接口依赖上游 dtrait/设备参数链路，可能需按上游 README 在浏览器捕获 `DY_DTRAIT_BLOB`；真实可用性只能由真实账号验证。
- 上游部分请求 `verify=False`（TLS 校验关闭，风控指纹需要）——风险已在 `vendor/PROVENANCE.md` 记录并接受。
- 自动调度 worker 未建设：定时发布依赖平台侧 `timing`，创建后需人工执行。
- 上游无 LICENSE 的法律风险由用户拍板承担（见第 0 节决策记录）。
