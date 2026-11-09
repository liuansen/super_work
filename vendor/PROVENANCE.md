# vendor/DouYin_Spider 来源与完整性记录

- 来源：https://github.com/cv-cat/DouYin_Spider
- 固定提交：`d151f9c2980abc304c1ae4918c2272675cd9e4c2`（master，2026-10-23T03:24:05Z）
- 下载时间：2026-11-09（本机 curl → codeload.github.com tarball）
- 归档 SHA256：`a1c4ba6643955b815b9799a107707540fdfac6f459d0a6d180f8b0842396d176`
- 归档路径安全检查：122 个条目，无绝对路径、无 `..`（解包前检查通过）
- 解包位置：`.local/douyin-upstream/`（原始留存）；集成副本：本目录 `DouYin_Spider/`（96 文件，与解包结果逐文件一致）

## 集成原则

1. **本目录代码保持上游原样**，不做任何修改；工程通过适配层（`backend/app/adapters/douyin/`）调用。
2. 上游无 LICENSE，README 自述“仅供技术研究与学习使用，请勿用于任何商业用途或非法用途”。将此代码纳入工程为用户 2026-11-09 明确指示的整合决策，风险由工程所有者承担。
3. 升级上游 = 下载新 commit 归档 → 安全检查 → 整目录替换 → 更新本文件 SHA/commit。
4. 运行安全扫描结论（2026-11-09，全量 96 文件）：
   - `subprocess` 仅 2 处：`node -e` 生成 V8 语义随机串（无 Node 自动退路）、`ffmpeg` 提取音频（可选，有退路）；均 `shutil.which` 定位、带超时。
   - 无运行时动态下载执行；`dy_live/protobuf/webcast_proto_re/js2proto.py` 中的 wget 为开发期重建 proto 的注释/文档，非运行路径。
   - 上游部分请求使用 `verify=False`（TLS 校验关闭，风控 TLS 指纹需要）；该风险由适配层文档记录并接受。
5. 依赖：核心路径（认证/采集/发布/指标）需要 `curl_cffi`、`protobuf>=5.27`、`lxml`、`ecdsa`、`requests`、`loguru`、`python-dotenv`、`retry`，见 `requirements-douyin.txt`；`blackboxprotobuf` 仅私信路径使用，未安装（原因见该文件注释）。
