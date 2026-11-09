# 证据：来源许可审查（license 检查项 · blocked）

- 观察日期：2026-11-09（UTC）
- 来源 URL：`https://github.com/cv-cat/DouYin_Spider`
- 固定版本：master `d151f9c2980abc304c1ae4918c2272675cd9e4c2`（pushed_at 2026-10-23T03:24:05Z）
- 获取方式：只读 GitHub REST API（api.github.com），未下载归档、未执行任何上游代码。
- 授权引用：本地静态审查记录 `docs/superpowers/verification/douyin/source-review.md`（无凭证内容）。

## 观察事实

1. GitHub API `GET /repos/cv-cat/DouYin_Spider` 返回 `"license": null`（2026-11-09 查询，固定 ref `d151f9c2980abc304c1ae4918c2272675cd9e4c2`）。
2. GitHub API 顶层目录清单（同 ref，共 16 项）中不存在 `LICENSE`、`LICENSE.txt`、`LICENSE.md`、`COPYING`、`NOTICE` 任何许可文件。顶层项目：`.env.example`、`.gitignore`、`Dockerfile`、`README.md`、`main.py`、`pyproject.toml`、`quick_publish.py`、`requirements.txt`，目录 `author`、`builder`、`dy_apis`、`dy_live`、`newsign`、`static`、`tests`、`utils`。
3. README（同 ref）自述限制原文摘录：
   - “本项目仅供技术研究与学习使用，请勿用于任何商业用途或非法用途”
   - “严格遵守目标网站的服务条款与robots.txt协议，合理控制请求频率，避免对目标服务器造成不必要的负担。”

## 判定

**blocked**：无许可证文件，默认版权保留；README 明示仅限学习研究。在取得权利人授权或更换来源前，不允许集成其代码，`license` 门槛不通过。

## 限制

- 本证据为只读 API 观察；未检索仓库 git 历史中是否曾有 LICENSE 被删除（不影响当前 ref 判定）。
- 未与权利人联系；授权状态未知。
