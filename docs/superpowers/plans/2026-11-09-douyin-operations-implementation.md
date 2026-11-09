# 抖音短视频运营应用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有超级工作台内增加独立抖音运营应用，支持多账号、人工成片、AI辅助、审核后系统发布和真实数据复盘，不影响小红书。

**Architecture:** 抖音页面通过独立API和业务服务调用采集、发布与指标适配层，复用统一认证与部署。新增独立业务表、受保护的文件访问及持久化任务执行机制，不直接套用小红书发布或内存任务逻辑。先通过能力验证门槛，再冻结外部契约和展开生产实现。

**Tech Stack:** React 19、TypeScript、Vite、Ant Design 6、React Router 7、FastAPI、SQLAlchemy 2、Alembic、pytest；延续现有模型配置和部署方式。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-11-09-douyin-operations-design.md`；用户已于2026-11-09在对话中确认。
- “延续当前技术栈和部署方式，不引入微前端、新框架或独立后端服务。”
- “保持现有小红书业务、数据范围、路由与调度行为不变。”
- “当前目录不是Git仓库；本文仅保存到本地，不初始化Git、不创建提交。”执行阶段同样不初始化、不提交；用本地基线和 `git diff --no-index` 审查。
- “同一人审核并发布；首期不新增团队、角色权限或多级审批。”
- “首期支持多个抖音账号，但不包含一键群发。”
- “视频由人工在外部制作；系统提供AI辅助创作，不建设自动成片系统。”
- “采集和发布凭证及适配方式明确，不把未经验证的能力列为已实现。”
- “真实平台发布需要用户对目标账号、具体成片和发布时间的明确授权。确认本需求文档不等于授权执行真实发布。”
- “至少能回收一种真实互动指标；否则暂停并重新确认闭环目标。”
- 定时展示和用户输入按 `Asia/Shanghai` 解释；现有 `shanghai_now()` 返回北京时间无时区datetime，适配边界必须明确转换。
- 不改写现有 `apis/` 和小红书签名文件；不复用其Cookie、原始响应结构或发布管线。
- 前端安装若确有必要：`npm --prefix frontend ci --legacy-peer-deps`。不要无理由更新依赖或锁文件。
- pytest使用独立临时数据库；不得为整个pytest进程导出 `DATABASE_URL`，不得让测试或迁移写入业务数据库。
- 本次交付只有计划文档。下述文件清单为后续拟创建／修改项，不代表已存在或已实现。

---

## 1. 计划分解与执行边界

这是有依赖的完整闭环，不适合在未知外部接口时编造一份可直接复制的生产代码。分成四个有独立验收出口的工作包：

| 工作包 | 交付 | 依赖 | 当前可执行性 |
| --- | --- | --- | --- |
| A 能力验证 | 基线、来源及许可记录、脱敏能力证据、门槛判定、冻结契约 | 用户提供或网络可获取上游资料；真实操作逐项授权 | 详细步骤见同目录 `2026-11-09-douyin-capability-validation.md`；无账号时可完成离线步骤，不能通过门槛 |
| B 账号与创作准备 | 独立应用、账号、参考内容、草稿、AI、成片的纵向流程 | A通过，依赖及外部契约冻结 | 本文给出文件职责、任务顺序和验收；A通过后生成逐步代码计划 |
| C 审核与系统发布 | 审核、幂等任务、发布、定时、恢复及结果对账 | B的账号、成片、草稿和A的发布契约 | 本文给出实现路线；B交付后生成逐步代码计划 |
| D 真实复盘与回归 | 指标快照、复盘、真实闭环与兼容性证据 | C的真实作品和A的指标契约 | 本文给出实现路线；C交付后生成逐步代码计划 |

**强制停止点：** A未通过，不注册已启用的抖音应用，不修改业务数据库、不建设生产发布管线。A报告通过不等于其证据可信，必须人工核对来源、真实作品与指标，用户确认集成决策后才展开B。B、C、D的路线不是已就绪的可复制代码计划；不把“后续展开”隐藏成实现占位，也不声称全流程现已可以直接执行。

后续代码计划应分别保存为：

- `docs/superpowers/plans/2026-11-09-douyin-workspace-creation.md`
- `docs/superpowers/plans/2026-11-09-douyin-reviewed-publishing.md`
- `docs/superpowers/plans/2026-11-09-douyin-review-and-verification.md`

这些后续文件本次不创建；外部SDK名称、鉴权参数、媒体规格、配额和迁移版本号不提前虚构。

## 2. 当前扩展点核对结果

| 现有位置 | 可用事实 | 计划约束 |
| --- | --- | --- |
| `frontend/src/apps/registry.ts` | `WorkbenchApp`、`workbenchApps`、`findWorkbenchApp(id)`；目前只有xhs | 最终增加douyin注册项，交付前不开启空壳入口 |
| `frontend/src/app/router.tsx` | `/apps/:appId`解析与 `ProtectedRoute`；小红书位于自己的AppShell中 | 新增独立DouyinShell路由分支，不改xhs绑定和KeepAlive行为 |
| `frontend/src/lib/api.ts:80-153` | Axios实例 `http` 未导出，已有内存access token和401刷新逻辑 | 经回归测试后仅新增导出 `authenticatedHttp`，抖音模块复用同一实例；不创建第二套token存储或刷新机制 |
| `backend/app/core/deps.py:14` | `get_current_user(token, db) -> User` | 所有抖音API使用现有认证依赖 |
| `backend/app/core/database.py:152` | `get_db()` 生成Session | 所有业务事务复用依赖模式；任务使用单独Session，不共享请求Session |
| `backend/app/core/security.py:119-124` | `encrypt_text(str) -> str`、`decrypt_text(str) -> str` | 可复用加密函数；解密只在适配调用边界发生 |
| `backend/app/core/time.py:9` | `shanghai_now() -> datetime`，返回无时区北京时间 | 前端提交显式带偏移时间；边界转成现有存储规范，不按服务器本地时区解析 |
| `backend/app/api/files.py:149-156` | 现有媒体GET未执行用户认证 | 不作为抖音文件服务；新增按媒体ID和user_id查找的认证端点，不顺带改小红书接口 |
| `backend/app/core/task_runner.py:18-31` | 仅进程内dict保存状态 | 不承担抖音发布、幂等或恢复 |
| `backend/app/services/scheduler_service.py:14,120-125` | 直接依赖XHS适配器，并检查xhs creator账号 | 新增抖音调度服务，不把抖音塞入现有小红书函数 |
| `backend/app/models/__init__.py`、`backend/alembic/env.py` | 模型导入用于迁移metadata；env读取环境 `DATABASE_URL` | 新表必须导入metadata；迁移测试显式隔离连接和环境 |
| `backend/app/core/database.py:64-67` | 有表无alembic_version时直接stamp head | 单独测试旧库接入，不能让新增抖音迁移被stamp跳过；先备份验证，不直接对业务库启动 |
| `tests/backend/test_api.py:341-356` | 临时SQLite、metadata.create_all、get_db覆盖模式 | 新测试使用独立conftest和应用实例；不能仅覆盖get_db后启动会迁移全局engine的真实lifespan |
| `frontend/package.json` | `build` 为 `tsc && vite build`，没有前端测试脚本 | 不假装已有vitest；后端可测契约，交互用浏览器验证；测试依赖如需新增单独说明 |
| `.claude/launch.json` | 已有 `super-workbench-frontend` 预览配置 | 启动服务统一用preview工具；仅在需要验证可运行UI时使用 |

现有文本AI服务使用 `OpenAICompatibleTextClient`，协议位于 `backend/app/services/ai_service.py:11-64`，具备generate_note、generate_titles、generate_tags和polish_text等方法。抖音创作需独立组织提示词和返回校验，不把小红书note结构当作短视频脚本契约。任何复用都先核验配置归属与回归测试，不能调用修改小红书草稿的路由。

## 3. 拟定文件职责图

### 3.1 工作包A

详细内容及代码仅见A计划：

- `tools/douyin_validation/baseline.py`：仅对受保护源码创建哈希基线，拒绝覆盖已有基线。
- `tools/douyin_validation/evidence.py`：检查能力报告完整性、证据哈希及门槛，不访问网络，不执行上游。
- `tests/douyin_validation/test_baseline.py`、`tests/douyin_validation/test_evidence.py`：完全离线工具测试。
- `docs/superpowers/verification/douyin/source-review.md`：来源、版本、许可与依赖审查。
- `docs/superpowers/verification/douyin/capability-report.json`：机器可读验证结果，无凭证。
- `docs/superpowers/verification/douyin/evidence/`：脱敏证据，不放原始账号信息、Token、视频或授权密钥。
- `docs/superpowers/verification/douyin/contracts.md`：经过证据确认的外部接口和内部适配契约。
- `.local/douyin-validation/`：仅本地基线及受控原始材料；不交付、不上传、不在日志展示凭证。

### 3.2 工作包B

| 拟新增路径 | 单一职责 |
| --- | --- |
| `backend/app/douyin/contracts.py` | 与上游解耦的类型、错误分类和适配协议，签名由A冻结 |
| `backend/app/douyin/models/accounts.py` | 抖音账号及凭证版本 |
| `backend/app/douyin/models/references.py` | 来源作品、标签、去重及创作引用 |
| `backend/app/douyin/models/creations.py` | 草稿及版本 |
| `backend/app/douyin/models/media.py` | 视频、封面、不可变版本和文件归属 |
| `backend/app/douyin/models/tasks.py` | 持久化任务与事件记录 |
| `backend/app/douyin/models/__init__.py` | 显式模型导入 |
| `backend/app/douyin/schemas.py` | 独立请求／响应模型，不输出凭证和服务器路径 |
| `backend/app/douyin/accounts.py`、`references.py`、`creations.py`、`media.py` | 各业务事务与owner校验 |
| `backend/app/douyin/ai.py` | 脚本与文案生成、返回校验、配置归属校验 |
| `backend/app/douyin/storage.py`、`safe_fetch.py` | 私有文件存储与受控来源获取，分离本地文件和网络职责 |
| `backend/app/douyin/tasks.py` | 任务持久化、阶段／错误记录和安全重试策略 |
| `backend/app/adapters/douyin/` | A批准的账号、采集、发布、指标实现；具体依赖和文件名由契约确定 |
| `backend/app/api/platforms/douyin/accounts.py`、`references.py`、`creations.py`、`media.py`、`tasks.py`、`__init__.py` | 窄API边界与路由汇总 |
| `frontend/src/features/douyin/types.ts`、`api.ts` | 抖音类型及HTTP调用 |
| `frontend/src/features/douyin/douyin-shell.tsx`、`routes.tsx` | 独立菜单、应用身份和返回入口 |
| `frontend/src/features/douyin/pages/accounts-page.tsx`、`references-page.tsx`、`creation-page.tsx`、`media-page.tsx`、`tasks-page.tsx` | 对应业务页面 |
| `tests/douyin/conftest.py`、`test_accounts.py`、`test_references.py`、`test_creations.py`、`test_ai.py`、`test_media.py`、`test_tasks.py`、`test_migrations.py` | 临时数据库、替代适配器与行为验证 |

仅允许必要的外围修改：`backend/app/main.py`接入抖音路由和生命周期；`backend/app/models/__init__.py`导入抖音metadata；`frontend/src/lib/api.ts`导出已有认证实例；`frontend/src/app/router.tsx`挂载抖音分支。迁移在 `backend/alembic/versions/` 下生成，经实际heads检查后确定revision与down_revision，不手写虚构版本链。

### 3.3 工作包C

- `backend/app/douyin/models/reviews.py`、`publishing.py`：审核快照、发布意图、任务、账号执行锁、作品。
- `backend/app/douyin/reviews.py`：快照摘要、版本校验、审核失效。
- `backend/app/douyin/publishing.py`：任务创建／取消及事务状态控制，不在数据库锁内进行网络调用。
- `backend/app/douyin/worker.py`：任务领取、执行权fencing token、结果落库、超时对账。
- `backend/app/douyin/scheduler.py`：到期扫描、授权阻塞、逾期分类、恢复，不修改小红书调度函数。
- `backend/app/api/platforms/douyin/reviews.py`、`publishing.py`：审核和任务API。
- `frontend/src/features/douyin/pages/publishing-page.tsx`：预览、明确审核与提交、状态／取消操作。
- `tests/douyin/test_reviews.py`、`test_publishing.py`、`test_concurrency.py`、`test_recovery.py`、`test_scheduler.py`：单元、事务、真实独立连接并发和恢复测试。

### 3.4 工作包D

- `backend/app/douyin/models/metrics.py`：指标快照与复盘记录。
- `backend/app/douyin/metrics.py`、`retrospectives.py`：刷新、权限、空值语义与人工复盘。
- `backend/app/api/platforms/douyin/works.py`：作品列表、指标、复盘和本用户总览。
- `frontend/src/features/douyin/pages/works-page.tsx`、`dashboard-page.tsx`：作品、复盘和非模拟总览。
- `tests/douyin/test_metrics.py`、`test_retrospectives.py`、`test_integration_flow.py`、`test_compatibility.py`。
- `docs/superpowers/verification/douyin/acceptance.md`：本地测试、浏览器证据、真实验证与未覆盖项。

不把上述职责集中成一个大型service或页面。除必要metadata、路由和生命周期接入外，不修改现有小红书业务模块。

## 4. 工作包A执行入口

- [ ] 阅读并执行 `docs/superpowers/plans/2026-11-09-douyin-capability-validation.md`。
- [ ] 取得证据门槛报告并人工核对，真实操作按内容与账号逐次确认授权。
- [ ] 用户确认A的集成结论后，再生成B的逐步代码计划；发布／指标门槛失败则停止。

A的协议冻结输出必须覆盖：身份验证、内容获取、媒体规格、上传、发布、查询、取消能力、幂等支持、超时结果语义、指标字段及刷新限制。不能把一个返回dict的通用execute函数作为所有适配接口。

## 5. 工作包B实施路线：账号与创作准备

以下是进入下一份逐步代码计划的任务边界，不直接执行未经展开的生产代码。

### B1：隔离测试与迁移

- [ ] 新增独立 `tests/douyin/conftest.py`，每个测试创建临时SQLite和自己的app，覆盖get_db，替代所有外部适配器；普通API测试不进入真实app lifespan。
- [ ] 单独做lifespan测试，注入Session工厂／调度器，确认不使用业务全局engine；测试结束清理override和线程。
- [ ] 新增账号、来源、创作、媒体及任务模型，并在metadata显式注册。
- [ ] 为新建数据库、已有带revision数据库、已有无revision数据库分别创建迁移测试；升级后小红书表结构及既有行的值不变。
- [ ] 对有表无revision路径，不使用现有stamp head后跳过新表：在迁移工作包设计受控首次接管命令，校验旧库结构匹配已知旧revision，再stamp旧revision并upgrade；不在普通应用启动时猜测版本。此命令仅在备份副本验证后、用户批准下作用于业务库。
- [ ] 迁移只增加douyin表及索引，不自动生成删除／修改既有表的操作。先检查 `python -m alembic -c backend/alembic.ini heads`，再生成并审查迁移。

验收出口：临时库创建、升级、迁移副本回归均通过；无业务数据库写入。

### B2：账号纵向切片

- [ ] 实现账号授权／绑定、身份确认、列举、检查和重新授权，接口形态严格采用A冻结契约；不假定Cookie导入或扫码存在。
- [ ] `(user_id, provider_account_id)`唯一；同用户重新授权更新凭证版本，不重复创建账号；不提供跨用户共享。
- [ ] 序列化仅返回展示字段和授权状态，凭证服务端加密。接口对非owner返回404。
- [ ] 独立抖音工作区内部路由与账号页在开发入口验证，最终应用卡片仍不启用。

验收出口：两个测试账号相互独立；失效、重新授权、越权和日志脱敏用例通过。

### B3：参考内容与持久化采集

- [ ] 链接校验、DNS和每跳重定向检查拒绝内网、loopback、metadata、非HTTPS和未知来源；适配器必须使用受控transport，不能先调用不受控上游下载再补检查。
- [ ] 以 `(user_id, provider_work_id)` 唯一索引实现幂等入库和并发去重，重复采集保留用户标签／备注／创作关联。
- [ ] 耗时采集返回持久化任务ID，刷新后可查询进度；分页、超时和限制用脱敏fixture模拟。
- [ ] 参考库实现筛选、标签、备注及JSON／CSV导出；CSV以 `= + - @` 等公式前缀开头的文本安全转义。

验收出口：链接、入库、刷新状态、导出和越权测试通过；不启用未批准的搜索或作者采集。

### B4：创作与AI辅助

- [ ] 草稿支持人工编辑及多参考关联，保存时采用版本号防止覆盖新编辑。
- [ ] AI请求选择当前用户有权使用的模型配置，发送前展示待发送字段并确认外部处理；请求中不含凭证、原始敏感响应或未经选择的参考全文。
- [ ] 独立生成脚本、标题、描述、标签和封面文案，返回校验后作为候选内容，不自动覆盖用户新编辑，不建立审核或发布任务。
- [ ] 通过fake客户端测试超时、无效响应、配置越权及用户拒绝发送，确认草稿未丢失；真实模型调用另行授权，非普通测试依赖。

验收出口：人工和AI两条编辑路径可用，失败不清空，旧生成结果不覆盖新版本。

### B5：受保护成片和预览

- [ ] 上传流采用生成ID和独立私有目录，限制字节数、检查内容类型与实际容器；按A确认的规格校验媒体。解析采用受限子进程／既有可用库，明确超时和错误，禁止解释执行文件。
- [ ] 视频／封面使用不可变版本，接口只返回媒体ID、必要元数据与认证访问地址，不返回本地绝对路径。
- [ ] 新增按媒体ID、owner查询的下载／预览API，支持浏览器视频Range访问并正确返回206／416。
- [ ] 现有认证用Bearer，HTML video不能直接附带Authorization：前端通过同一认证HTTP客户端取得短效、限定当前媒体、只读的HttpOnly预览会话，限定 `/api/douyin/media/preview/` 路径、SameSite=Strict、生产HTTPS使用Secure；服务端存储会话哈希、用户及到期时间。视频src不携带token，支持Range，退出／过期撤销会话；该会话不能调用其他API。此设计属于同一登录派生的受限媒体访问，不新增用户登录体系。
- [ ] 本地同站点开发允许HTTP下不设置Secure，生产必须Secure；不允许跨域预览。浏览器验证cookie路径、过期、Range、退出后失效和其他用户不可访问。
- [ ] 有有效审核／任务引用的版本不可删除；未引用文件的清理在事务检查后执行，处理失败时记录待清理任务而不是留下伪成功。

验收出口：有效视频可预览、Range正确，越权和过期不可播放，版本不覆盖且删除保护生效。

### B6：任务、提示与基础回归

- [ ] 为采集、上传、AI及校验记录可查询的持久化阶段，用户只能查看自己的任务。
- [ ] 抖音内必要提示独立呈现，不修改小红书通知查询范围。
- [ ] 导出同一Axios实例为 `authenticatedHttp`，所有抖音API使用它；测试401刷新后重试仍使用同一幂等键，禁止新的token存储。
- [ ] 完成B的构建和浏览器验证，但明确“尚未完成发布闭环”。

验收出口：B纵向流程及小红书外围回归通过，提交B验证记录供用户审阅。

## 6. 工作包C实施路线：审核与发布

### C1：不可变快照与审核失效

- [ ] 以账号、视频版本、封面版本、规范化文案、发布方式和计划时间生成规范化快照摘要；存审核人、时间、版本及失效原因。
- [ ] 修改任一审核字段在同一事务中增加发布意图版本、使审核失效、阻止尚未发送的平台请求；不删除历史审核。
- [ ] 审核提交与字段修改使用版本条件更新，防止用户审核旧页面时误审核新内容。
- [ ] 事务中校验关联实体都属于当前用户，且媒体版本通过校验。

验收出口：每个字段分别变更都会重审；非审核字段如复盘备注不会误使审核失效。

### C2：幂等发布意图与持久执行权

- [ ] 使用用户范围的请求幂等键和审核ID／发布意图唯一约束；相同key相同payload返回原任务，相同key不同payload返回409。
- [ ] 任务与账号执行权存数据库，以原子条件更新领取；独立Session并发测试，不用同一内存SQLite连接伪造多进程。
- [ ] 领取时生成fencing token，完成或失败落库必须匹配token；租约过期不自动夺取并重新发送已有远端副作用的任务。
- [ ] 平台请求前持久化 `dispatch_started` 与provider请求标识；超时／崩溃后视为结果不明。释放账号执行权前按平台能力对账；无法对账则锁定该账号相关发布直到明确解决，避免与旧请求并发。
- [ ] 本地幂等不等于上游exactly-once；上游若支持幂等键则映射稳定键，否则对结果不明坚持不重发。

验收出口：重复提交、多个worker、旧worker迟到回写和崩溃边界测试通过，不能以锁超时后重发换取可用性。

### C3：执行与对账

- [ ] 执行阶段分别记录上传、发起发布、结果确认，外部网络调用不持有数据库写锁。
- [ ] 外部请求发起前在同一受控事务中最终检查审核、授权和取消状态，再持久化发送边界；边界之后修改／取消返回“已开始，不能保证取消”，不伪报已阻止。
- [ ] 上传成功不是发布成功；保存平台作品、平台审核与可见性分别对应字段。
- [ ] Timeout进入结果待确认，已知拒绝进入明确失败；查询为unknown不解释成未发布。
- [ ] 未通过审核／文件丢失／授权失效一律不发送；授权恢复后不自动补发过期任务。

验收出口：所有异常由fake适配器确定性复现，真实平台验证独立授权。

### C4：定时、取消与恢复

- [ ] 使用显式北京时间输入和存储转换，注入clock测试，不通过sleep等待计划时间。
- [ ] 独立抖音调度器由app生命周期启动／停止，受配置控制，不修改小红书job的频率或查询条件。
- [ ] 定时任务记录由计划计算的执行窗口；正常运行窗口内到期可领取，停机恢复时对恢复前已到期未领取的任务标记逾期，不用“now大于scheduled_at”把所有正常任务误判逾期。
- [ ] 取消与worker领取通过条件更新竞争：取消成功后不能发起请求；已经越过发送边界则返回真实执行状态。
- [ ] 重启扫描分开处理未来任务、逾期任务、执行不明任务；不对执行不明任务直接设置pending。
- [ ] 一个账号阻塞不影响其他账号；授权失效、失败、未知结果与逾期都有抖音内提示。

验收出口：冻结时间、重启、取消竞争和多账号隔离测试通过。

### C5：审核与发布界面

- [ ] 展示成片、封面、账号、文案和明确北京时间；审核与提交必须是显式操作，不能打开页面就审核。
- [ ] 字段修改即显示需要重审，服务端仍独立强校验。
- [ ] 结果待确认不提供盲重发按钮；取消对已发送状态给出准确说明。
- [ ] 页面刷新后从服务端恢复任务，不把浏览器内存作为发布完成依据。

验收出口：浏览器验证立即／定时／失效／未知／取消路径，未授权时只使用替代适配器，不执行真实发布。

## 7. 工作包D实施路线：指标与完整验收

### D1：真实指标语义与复盘

- [ ] 每个指标返回 `value: number | null`、`availability: available | unsupported | not_collected` 及快照采集时间；刷新错误单独记录，不污染最近成功快照。
- [ ] 有效零值保持0；无权限或不支持为unsupported；未查询为not_collected，禁止 `value || 0`。
- [ ] 按作品和账号校验归属，手动和计划刷新经过限流，频率由A固定；用户重复刷新复用进行中的任务。
- [ ] 复盘结论与后续选题备注独立保存，不改审核快照或发布历史。
- [ ] 总览仅使用当前用户真实记录，无数据展示空状态；首期可用表格／文本，若新增图表先使用dataviz技能，不因总览引入额外分析平台。

验收出口：真实0、未知、不可获取和失败保留旧数据的测试全部覆盖。

### D2：兼容性、安全和迁移回归

- [ ] 对所有抖音实体执行A用户访问B用户的列表／详情／改写／下载／执行／导出测试。
- [ ] 验证SSRF、多跳重定向、DNS解析、路径穿越、超限上传、Range错误、公式注入和日志脱敏。
- [ ] 前后比较小红书路由、模型、API响应、任务和通知归属；旧表结构与既有数据校验不变。
- [ ] 在空库、带revision副本和无revision副本执行迁移／启动测试；在实际声明支持的数据库后端验证原子领取与唯一约束，SQLite测试不能冒充MySQL并发证明。
- [ ] 运行完整现有测试和前端构建；既有失败与新增回归分别记录，不顺手修复无关业务。

验收出口：基线比较、迁移回归和安全用例有明确通过／失败证据，未覆盖项列出。

### D3：授权真实验证与入口交付

- [ ] 请求用户明确批准目标账号、具体成片、封面文案及发布时间；不以本计划的同意代替发布授权。
- [ ] 使用至少两个获授权账号验证隔离；逐次授权真实发布，至少一条作品完成第12.2节闭环，不为验收批量群发。
- [ ] 回收至少一种真实互动指标并记录采集时间，保存人工复盘。
- [ ] 开启 `frontend/src/apps/registry.ts` 的真实douyin入口；如需要反映后端平台状态，仅精确更新Douyin项，并更新明确依赖原占位状态的平台注册测试，不放宽其他断言。
- [ ] 用preview工具检查应用入口、返回、主题、移动布局、媒体和任务交互，错误日志及网络均检查，视觉变更截图留证，测试后恢复桌面视口。
- [ ] 交付 `docs/superpowers/verification/douyin/acceptance.md`，分别报告mock测试、浏览器验证、真实平台结果和未验证限制。

验收出口：只有全部硬门槛和真实闭环通过后，才称完整运营应用交付；否则报告具体阻断点。

## 8. 各工作包测试命令与运行约定

所有命令在工程根目录 `E:/code/super_work` 执行。下列是后续实施验收命令，不表示本次编写计划时已执行。

能力验证工具：

```bash
python -m pytest tests/douyin_validation -v
```

抖音业务测试（仅B开始且独立测试设施就绪后）：

```bash
python -m pytest tests/douyin -v
```

既有后端回归（先核验临时库策略和已知环境约束）：

```bash
python -m pytest tests/backend -q
```

前端生产构建，内含TypeScript检查：

```bash
npm --prefix frontend run build
```

预览统一使用 `.claude/launch.json` 的 `super-workbench-frontend`，通过preview_start启动；后端如需接入，先新增仅使用专用测试数据库、禁用真实任务的预览配置，再使用preview_start。禁止用Bash启动服务，禁止让预览默认连业务库跑迁移。

迁移测试通过程序式Alembic Config指向临时路径，并用monkeypatch移除外部 `DATABASE_URL`；不要给整个pytest导出该变量。模型单测通过 `Base.metadata.create_all(test_engine)`；迁移测试必须另跑真实migration，不能以create_all通过替代迁移通过。

## 9. 规格覆盖矩阵

| 规格章节 | 实施位置／验收 |
| --- | --- |
| 1目标与确认结论 | 全局约束、A门槛、D3真实闭环 |
| 2工程事实 | 本文第2节、B1、B6、D2 |
| 3上游及能力验证 | A计划任务1—5，A失败强制停止 |
| 4方案选择 | 第1、3节独立模块结构 |
| 5入口与架构 | B2、B6、D3，contracts冻结 |
| 6.1账号 | B2、C4多账号隔离 |
| 6.2参考库 | B3 |
| 6.3AI创作 | B4 |
| 6.4成片 | B5 |
| 6.5审核 | C1、C5 |
| 6.6发布与定时 | C2—C5 |
| 6.7指标复盘 | D1、D3 |
| 6.8任务通知 | B3、B6、C4 |
| 7数据与隔离 | B1—B5、C1—C2、D2 |
| 8状态、幂等、恢复 | C1—C4 |
| 9安全与非功能 | 全局约束、B3—B6、C2—C4、D2 |
| 10排除范围 | 全局约束，不增加自动视频生产／团队／群发 |
| 11分阶段交付 | A→B→C→D依赖链 |
| 12.1能力 | A证据门槛 |
| 12.2真实闭环 | D3 |
| 12.3多账号隔离 | B2、C4、D2—D3 |
| 12.4发布调度 | C1—C5 |
| 12.5数据AI | B3—B5、D1 |
| 12.6兼容 | B1、B6、D2 |
| 13验证证据 | A离线／真实分离、B—D自动化与浏览器、D3报告 |
| 14审阅 | 已确认规格，本计划交付后只按用户批准的范围执行 |

## 10. 交付状态与下一步

本次产出为本总体实施路线和A的详细执行计划；无业务实现、数据库迁移、真实采集、AI外发或发布。上游资料当前未核验，不能给出可信的完整开发工期或上游接口代码。

下一步可以执行A的离线工具、来源审查和能力验证准备；外部素材、账号、模型请求和发布按需另外取得授权。执行模式可选：在本会话内逐项执行并设检查点，或经用户选择采用逐任务子代理和审查。当前非Git仓库，不使用worktree，不初始化Git，不提交；涉及同一文件的写入串行执行。
