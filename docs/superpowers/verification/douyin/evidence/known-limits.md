# 证据：上游自述限制与已知问题（limits 检查项 · unverified）

- 观察日期：2026-11-09（UTC）
- 来源 URL：`https://github.com/cv-cat/DouYin_Spider`
- 固定版本：master `d151f9c2980abc304c1ae4918c2272675cd9e4c2`（README 该版本内容）
- 获取方式：只读 GitHub REST API。
- 授权引用：本地静态审查记录 `docs/superpowers/verification/douyin/source-review.md`。

## 观察事实（均为上游 README 自述，未经本工程真实验证）

### 凭证与授权要求

- `DY_COOKIES`：必须是“完整”登录 cookie 且包含 `UFIID` 字段；`/aweme/v1/web/` 下接口缺失该字段报 `Uifid Not Found`；`UFIID` 为“登录态生成的重要唯一标识”。
- `DY_LIVE_COOKIES`：直播弹幕专用凭据，“与普通采集不通用”。
- 写接口（发布等）需要 dtrait 相关参数：用户需在浏览器控制台通过 hook（挂接 `window.DTraitUcAesEncrypt.encryptData`）捕获 `DY_DTRAIT_BLOB` 写入 `.env`，或提供 `DY_DTRAIT_PROFILE`。
- 手机号短信登录取得的 cookie 自述“不适用于私信”。
- 已知问题（README 2026-10-17 自述）：短信登录存在 `err_code=16`（cookie 过期或未登录）类问题。

### 发布路径限制

- `create_v2` 发布可能命中 `x-tt-verify-passport-decision`：HTTP 状态 200 但响应体 403（README 2026-10-17 自述）。
- creator `msToken`（ms_appid=2906）未适配（README 2026-10-17 自述）。
- dtrait 与浏览器指纹检测持续变化，`BROWSER_COOKIE_ORDER` 需手动设置（README 自述）。
- `quick_publish.py` 仅打印发布响应，无发布后结果查询；发布后对账能力未在该入口实现。

### 频率与稳定性

- README 要求“合理控制请求频率”；未给出具体配额数字。
- 直播/弹幕链路历史上存在连接不稳定，更新日志多条记录重试/断线重连修复（2026-04-09、2026-09-27）。
- 未观察到任何官方配额、Token 有效期、媒体大小/时长/分辨率限制的确切数字——这些只能由 Task 4 真实验证取得。

## 判定

**unverified**：全部条目为上游自述；本工程未执行任何真实平台操作，无法确认这些限制在当前时点的真实边界。

## 限制

- 本证据不含任何凭证、cookie、账号信息或完整原始响应。
- 上游 README 随提交变化；本记录仅对固定 SHA 负责。
