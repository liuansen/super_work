# 抖音接入能力验证 · 判定与决策门（工作包A · Task 5）

> **【2026-11-10 追记：用户决策已作出，本文件的"停止"不再是现行结论。】**
> 用户于对话中明确指示"把 DouYin_Spider 整合到现有工作台"，即以工程所有者身份批准集成（含对其无 LICENSE 风险的承担）。据此已执行 B 阶段纵向闭环集成：vendor 固定快照 + 适配层 + 账号/参考库/发布/指标 + 独立前端工作区，应用入口已注册。完整证据见 `docs/superpowers/verification/2026-11-10-douyin-integration.md`。下文为闸门期判定的原始存档，其中"真实验证未执行"部分仍然成立：**真实平台操作（采集/发布/指标）尚未执行**，首次使用需绑定真实 Cookie 并逐次授权。

- 判定日期：2026-11-09
- 判定结论：**停止（STOP）**（原文存档，已被用户集成决策覆盖）—— 原结论：不进入工作包B，不编写 `2026-11-09-douyin-workspace-creation.md`，不注册抖音应用，不修改业务数据库，不建设发布管线。
- 交付人：ZCode 代理；本文件连同全部证据交用户人工核验，最终集成决策由用户作出。

## 1. 硬门槛逐项状态

| 门槛项 | 状态 | 证据/原因 |
| --- | --- | --- |
| license | **blocked** | 上游仓库无任何 LICENSE 文件（GitHub API `license=null`，顶层无 LICENSE/COPYING/NOTICE）；README 自述“仅供技术研究与学习使用，请勿用于任何商业用途或非法用途”。`evidence/source-license.md` |
| runtime | unverified | 仅静态记录依赖与环境声明；未安装未运行。`evidence/runtime-deps.md` |
| reference_link | unverified | 未执行真实采集（无授权输入） |
| accounts | unverified | 未提供两个测试账号，未执行 |
| publish | unverified | 未获得发布授权，未执行 |
| reconcile | unverified | 无真实作品可查询，未执行 |
| schedule | unverified | 未执行（依赖账号与发布观察） |
| metrics | unverified | 指标接口存在性静态未确认；无真实作品，未执行——**硬门槛“至少一种真实互动指标”未达成** |
| limits | unverified | 上游自述限制已记录；未真实验证。`evidence/known-limits.md` |

门槛程序输出（2026-11-09）：`evidence.py check` → `BLOCKED`，退出码 2，与上表一致。

## 2. 费用与权限限制

- 未发生任何费用：未调用任何付费服务、未购买代理或账号。
- 权限限制：无抖音平台账号授权、无发布授权、无上游代码使用授权（无许可证）。
- 本工作包全部操作为：本地离线工具开发/测试 + 对 GitHub 的只读 API 读取。未向抖音平台发送任何请求。

## 3. 许可结论

**不可集成。** `cv-cat/DouYin_Spider` 无许可证，默认版权保留；README 明示仅限学习研究。在取得权利人书面授权、或改用有许可的实现/官方开放平台之前，不得复制、修改、分发或集成其任何代码。此为停止理由之一，且单独存在即足以停止。

## 4. 可用 / 不可用能力（静态识别，均未真实验证）

- 静态存在（README+`quick_publish.py`）：采集（作品/评论/用户/直播）、私信、发布视频与图集、扫码/短信/Cookie 登录、签名生成、导出。
- 静态未见确认：发布后结果查询入口（`quick_publish.py` 无）；作品互动指标查询接口（119KB 文件未完成完整审查）。
- 结构性风险：全部能力基于逆向私有接口，上游自述存在风控持续变化与 403 类不稳定。

## 5. 基线是否变化

业务源码基线由 `tools/douyin_validation/baseline.py` 于 2026-11-09 在本工作包开始后捕获，并在交付前复查：

```bash
python -I tools/douyin_validation/baseline.py check . .local/douyin-validation/baseline
# BASELINE MATCH（退出码 0）
```

即 `backend/app`、`backend/alembic`、`frontend/src`、`apis`、`xhs_utils` 及锁定文件等受保护范围在任务 1—5 全程未变；本工作包仅新增 `tools/douyin_validation/`、`tests/douyin_validation/`、`docs/superpowers/verification/douyin/` 与本地 `.local/douyin-validation/`。小红书超级工作台保护基线（`scripts/workbench-boundary.cjs`）亦保持通过。

## 6. 继续 / 停止及理由

**停止。** 理由：

1. **许可硬阻断**：无 LICENSE + README 用途限制，不允许集成其代码（§3）。
2. **真实验证无输入**：Task 4 需要的测试账号、作品链接、成片/封面/文案与发布时间授权均未提供；按计划“无输入则保持 unverified”，且“手工构造的 JSON、静态 fixture 不能当作真实成功证据”。
3. **指标硬门槛未达成**：无法确认存在可回收互动指标的接口，更未回收真实指标。
4. 按总体计划强制停止点：“A未通过，不注册已启用的抖音应用，不修改业务数据库、不建设生产发布管线。”

## 7. 用户需决定的事项

1. **来源决策**：a) 向上游权利人取得书面使用授权；b) 评估抖音官方开放平台/其他有许可方案；c) 放弃上游路线。任一路径确定后，工作包A 从 Task 3/4 重新展开。
2. **平台合规确认**：即便解决代码许可，逆向私有接口用于运营是否可接受属用户决策（本报告不构成法律意见）；官方开放平台是规避风控风险的替代路径。
3. **测试资源**：若继续，需提供两个有权运营的测试账号、可研究作品链接、授权成片/封面/文案及计划时间（按 Task 4 Step 1—2 逐次确认，不提前授权）。
4. **是否需要完整静态审查**：获准固定副本后补做两个大文件（douyin_api.py 132KB、douyin_creator_api.py 119KB）的逐行审查与子进程/动态下载/安装钩子排查。

## 8. 已完成与未完成清单

**已完成（可交付）：**

- 离线工具 `tools/douyin_validation/baseline.py`、`evidence.py` 及 6 个离线测试（TDD，RED→GREEN，各测试 ≥3 遍通过）。
- 诚实初始报告 `capability-report.json`（init→BLOCKED 校验通过）。
- 静态来源审查 `source-review.md` + 3 份脱敏证据（哈希已录入报告）。
- 契约状态 `contracts.md`（未冻结，含冻结流程）。
- 本判定文件 `decision.md`。
- 业务基线 BASELINE MATCH；未运行迁移；未提交任何 Git 操作（当前非 Git 仓库）。

**未完成（诚实声明）：**

- 全部真实平台能力验证（reference_link/accounts/publish/reconcile/schedule/metrics）未执行。
- 契约未冻结；B/C/D 工作包未展开（按计划不得展开）。
- 未验证 ≠ 不存在：以上均为“当前证据不足”，不是对上游能力的最终否定。

## 9. 恢复条件

同时满足以下条件时可重启工作包A 的 Task 4：① 来源许可问题解决（新来源或授权）；② 用户明确提供测试账号与授权范围；③ 重新捕获基线后 `BASELINE MATCH`。届时从 Task 4 Step 1（收齐最小输入）与 Step 2（执行前确认方案）开始，发布操作按账号、内容、时间逐次获得用户确认。

## 附录：执行与测试记录（2026-11-09）

按“每项任务至少测试三遍、代码review至少两轮、修改后再测两遍”的执行约定记录实际运行：

- **Task 1（baseline.py）**：RED（2 failed，文件缺失）→ GREEN（2 passed）→ 完成测试 3 遍（3×2 passed）→ 基线捕获+check 退出 0。
- **Task 2（evidence.py）**：RED（4 failed，文件缺失）→ GREEN（4 passed）→ 完成测试 3 遍（3×4 passed）→ init 报告创建，check=BLOCKED/退出 2（正确未验证状态）。
- **Task 3**：只读网络审查完成；3 份证据文件哈希独立复算一致（脚本断言通过）；报告 JSON 有效性、SHA 格式、未验证项完整性断言全部通过。
- **Review 第 1 轮**：两工具源码与计划逐行比对一致；发现并修正 2 处文档问题（contracts.md 发布接口笔误 post_video→post_images；SHA 标注歧义澄清为 GitHub blob SHA sha1）。
- **Review 第 2 轮**：全量文件清单与计划文件地图比对（无缺漏、无多余）；异常路径走查（JSON 解析、非 dict checks、路径逃逸、naive 时间、重复 capture 拒绝）确认正确拦截；代码无需修改。
- **修改后回归 2 遍**：2×（6 passed + gate exit 2 + baseline exit 0）。
- **终检**：`python -m pytest tests/douyin_validation -v` → 6 passed；`baseline.py check` → BASELINE MATCH；工作台保护边界 `workbench-boundary.cjs check` → 全部未变。
- 全程未运行任何上游代码、未向抖音平台发送请求、未初始化 Git、未创建提交。
