# 抖音上游来源、许可与安全审查（工作包A · Task 3）

- 审查日期：2026-11-09
- 审查方式：**仅只读静态审查**（GitHub REST API `api.github.com` 读取元数据与文件内容）。未克隆仓库、未下载归档、未安装依赖、未执行任何上游代码、未发起对抖音平台的任何请求。
- 审查执行者：ZCode 代理（本记录尚待用户人工核对；`capability-report.json` 的 `reviewed_by` 因此留空）。

## 来源与版本

- 仓库 URL：`https://github.com/cv-cat/DouYin_Spider`（GitHub，提供者 cv-cat）。
- 描述（GitHub API 原文）：“抖音逆向，抖音爬虫，抖音全部api、私信、直播间监听”。
- 默认分支：`master`；提交总数约 146。
- 固定审查版本（master 最新提交，GitHub API `/repos/cv-cat/DouYin_Spider/commits` 于 2026-11-09 查得）：
  - SHA：`d151f9c2980abc304c1ae4918c2272675cd9e4c2`
  - 提交时间：`2026-10-23T03:24:05Z`；消息：“dy_live 更新完整 proto 定义 (#93)”；提交作者：Ardenwick
  - 前两次提交：`17efed895e683ae6c7a1f1b677c5846cc424e2b8`（2026-10-22，“指纹族刷 2026-10-17 现网 / dtrait 逐字节对齐…”）、`fc8b9c2490a9561265425c26058290f01c064eda`（2026-10-08）
- 仓库元数据：`pushed_at=2026-10-23T03:24:05Z`，`size=2938`（KB），`open_issues_count=84`。
- 顶层文件清单（GitHub contents API，16 项）：文件 `.env.example`、`.gitignore`、`Dockerfile`、`README.md`、`main.py`、`pyproject.toml`、`quick_publish.py`、`requirements.txt`；目录 `author`、`builder`、`dy_apis`、`dy_live`、`newsign`、`static`、`tests`、`utils`。
- 未下载任何归档，故无需解包检查；所有引用均基于固定 SHA 的 API 读取。

## 许可证与使用限制

- GitHub API `license` 字段为 **`null`**；顶层清单中**不存在** `LICENSE` / `COPYING` / `NOTICE` 等许可文件。
- README 自述限制（原文摘录）：“本项目仅供技术研究与学习使用，请勿用于任何商业用途或非法用途”；并要求“严格遵守目标网站的服务条款与robots.txt协议，合理控制请求频率”。
- 结论：**无开源许可证**。默认版权保留，权利人未授予使用、修改或再分发许可；且 README 明示仅限学习研究，与本工程“运营工作台”的持续业务用途存在限制冲突。
- 判定：`license` 检查项 = **blocked**（见 `evidence/source-license.md`）。不因“公开 GitHub”推定可用。

## 依赖与环境

`requirements.txt`（832 字节，GitHub blob SHA（sha1）`32fffdd8f3d1e90e3b5f69234b94b427c3a03326`，完整依赖清单见 `evidence/runtime-deps.md`）：

- 直接依赖：aiofiles、lxml、cryptography、ecdsa、loguru、openpyxl、opencv-python-headless、av、pillow、python-dotenv、qrcode、requests、retry、urllib3、websocket-client、websockets
- 指纹/二进制相关：`curl_cffi`（Chrome TLS/HTTP2 指纹模拟，注释标注可选装）、`protobuf>=5.27`、`blackboxprotobuf`、`backports.zstd ; python_version<'3.14'`、`rocksdict==0.3.29`、`jsbeautifier==2.0.3`
- README 声明的运行环境：Python 3.9+；Node.js 18+（**可选**，“推荐，用于执行直播 / 实时弹幕相关的加密逻辑”；更新日志称签名已改为纯 Python 实现，`utils/dtrait_features.py` 为 dtrait 相关 VM 的纯 Python 实现）。
- 版本组合风险（requirements 注释自述）：`blackboxprotobuf` 与 `protobuf==3.10` 组装会触发 `runtime_version` 导入错误，需按 protobuf>=5.27 运行时匹配。
- 本工程未安装以上任何依赖；上述均为静态记录。

## 运行副作用

- 风控对抗定位明确（README 功能列表）：请求签名 API 封装、设备参数与设备指纹生成、proxy 代理支持。
- 浏览器参与：dtrait blob 需用户在浏览器控制台通过 hook（挂接 `window.DTraitUcAesEncrypt.encryptData`）捕获 `DY_DTRAIT_BLOB` 后写入 `.env`——即运行前置依赖一次真实浏览器内的手工操作。
- 可选 Node.js：仅直播/实时弹幕加密推荐使用；核心签名按 README 为纯 Python。
- 子进程、动态下载、安装钩子、未知二进制：**未验证**——本次只读审查未遍历全部源码（如 132KB 的 `dy_apis/douyin_api.py`、119KB 的 `douyin_creator_api.py`），无法确认不存在；获准后在固定副本上做完整静态审查。
- 已知不稳定问题（README 更新日志 2026-10-17 自述）：`create_v2` 发布可能命中 `x-tt-verify-passport-decision`（HTTP 200 但响应体 403）；creator `msToken`（ms_appid=2906）未适配；dtrait 与浏览器指纹检测持续变化，`BROWSER_COOKIE_ORDER` 需手动设置。

## 可见能力

依据 README 功能列表与 `quick_publish.py` 实际源码（固定 SHA）：

| 能力 | 静态证据 | 判定 |
| --- | --- | --- |
| 作品/评论/用户采集 | README：用户信息与作品、视频详情（点赞、评论、分享数）、评论与回复、合集/播放列表/分页 | 存在（未真实执行） |
| 直播采集与 WebSocket 弹幕 | README；`dy_live/server.py` | 存在（未真实执行） |
| 私信（列表/发送/媒体） | README；`dy_apis/douyin_im_media.py` | 存在（未真实执行） |
| 视频发布 | `quick_publish.py` 调用 `DouyinCreatorAPI.post_video(auth, video=..., **kwargs)`；`builder.auth.DouyinAuth` 提供 cookie/扫码/短信三种登录 | 存在（未真实执行） |
| 图集发布 | `quick_publish.py` 调用 `DouyinCreatorAPI.post_images(auth, images=..., **kwargs)` | 存在（未真实执行） |
| 发布参数 | `VISIBILITY`（0 私密 / 1 好友 / 2 公开）、`ALLOW_DOWNLOAD`、TITLE≤20 字 | 存在（未真实执行） |
| 发布后对账/结果查询 | `quick_publish.py` 仅打印发布响应，无后续查询 | 该入口无（未真实执行） |
| 作品数据/互动指标查询 | `douyin_creator_api.py`（119KB）未完成完整静态审查 | **未验证** |
| 登录 | `dy_apis/login_api.py`：扫码、短信；Cookie 导入（需含 `UFIID` 的完整 cookie） | 存在（未真实执行） |

- 凭证形态（README）：`DY_COOKIES` 必须是完整登录 cookie 且含 `UFIID`，`/aweme/v1/web/` 下接口缺失会报 `Uifid Not Found`；`DY_LIVE_COOKIES` 与普通采集不通用；写接口另需 `DY_DTRAIT_BLOB` / `DY_DTRAIT_PROFILE`。
- 平台侧风险：发布走逆向私有接口（非官方开放平台），README 自述存在风控变化与 403 类不稳定；这是“平台随时可能封禁路径”的结构性风险，不是可修复缺陷。

## 证据文件

- `evidence/source-license.md`：许可缺失与 README 限制的原始摘录（对应 `license` 检查项，blocked）。
- `evidence/runtime-deps.md`：固定版本 `requirements.txt` 完整清单与环境声明（对应 `runtime` 检查项，unverified）。
- `evidence/known-limits.md`：上游自述的限制、凭证要求与已知问题（对应 `limits` 检查项，unverified）。
- 三个证据文件均为本次审查写入的脱敏摘录；引用方法（API 端点、固定 SHA、读取日期）记录在各文件内。哈希值写入 `capability-report.json` 对应 evidence 项。

## 允许的验证范围

- 已完成：Task 1/2 离线工具（基线、证据门槛）及全部离线测试；Task 3 只读静态审查（本文件）。
- 未获准/未执行：安装上游依赖、运行上游代码、向抖音平台发起任何请求（含采集、登录、发布、指标查询）、使用任何真实账号。
- Task 4（真实能力验证）依赖：有效许可证或权利人授权、用户提供的两个测试账号及成片/时间授权。当前均未具备。

## 阻断项

1. **许可缺失（blocked）**：仓库无任何 LICENSE 文件，默认版权保留；README 自述“仅供技术研究与学习使用，请勿用于任何商业用途或非法用途”。在取得权利人书面授权或改用有许可的实现之前，不得集成、复制或分发其代码。
2. **用途限制冲突风险**：即使未来获得授权，README 的“学习研究”自述与本工程运营用途的相容性需权利人明确确认。
3. **平台条款与风控**：上游功能以登录态 cookie 逆向私有接口实现；README 自身要求遵守目标网站服务条款。是否可在本工程运营场景使用，属用户决策（本记录不构成法律意见）。
4. **指标接口未确认**：静态审查未能确认上游存在可回收互动指标的接口；该门槛只能由 Task 4 真实验证裁决。
5. **真实账号与发布授权未提供**：Task 4 无输入，保持 unverified。
6. **代码完整性审查未完成**：两个核心大文件（douyin_api.py 132KB、douyin_creator_api.py 119KB）未逐行审查，子进程/动态下载/安装钩子是否存在未确认。
