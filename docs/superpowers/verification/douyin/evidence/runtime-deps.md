# 证据：运行环境与依赖静态记录（runtime 检查项 · unverified）

- 观察日期：2026-11-09（UTC）
- 来源 URL：`https://github.com/cv-cat/DouYin_Spider`
- 固定版本：master `d151f9c2980abc304c1ae4918c2272675cd9e4c2`
- 获取方式：只读 GitHub REST API 读取 `requirements.txt`（832 字节，GitHub blob SHA（sha1）`32fffdd8f3d1e90e3b5f69234b94b427c3a03326`）与 README。
- 授权引用：本地静态审查记录 `docs/superpowers/verification/douyin/source-review.md`。

## 观察事实

`requirements.txt` 完整依赖清单（固定 ref，逐项照录）：

```
aiofiles
lxml
cryptography
ecdsa
loguru
openpyxl
opencv-python-headless
av
pillow
python-dotenv
qrcode
requests
retry
urllib3
websocket-client
websockets
curl_cffi
protobuf>=5.27
blackboxprotobuf
backports.zstd ; python_version<'3.14'
rocksdict==0.3.29
jsbeautifier==2.0.3
```

- `curl_cffi`：文件内注释标注“如需使用自带 utils/http_client.py（curl_cffi 模拟 Chrome 的 TLS/HTTP2 指纹），可选装”。
- `protobuf>=5.27` 与 `blackboxprotobuf`：文件内注释自述存在版本组合问题（`protobuf==3.10` 组合会触发 `runtime_version` 导入错误）。
- README 环境声明：Python 3.9+；Node.js 18+（可选，“推荐，用于执行直播 / 实时弹幕相关的加密逻辑”）；更新日志称签名已“完全移除对 Python 扩展的依赖，无需安装 Node.js”（2026-07-26 条目）。
- 二进制/指纹类依赖：`curl_cffi`（TLS 指纹）、`opencv-python-headless`、`av`、`rocksdict==0.3.29`（RocksDB 绑定）、`jsbeautifier==2.0.3`（钉版）。

## 判定

**unverified**：以上仅为上游自述与固定版本文件的静态记录。本工程未安装任何依赖、未运行上游代码，不能声称运行时可用或已验证。

## 限制

- 未核对这些依赖的各自开源许可证及其与集成用途的相容性（上游本身无 LICENSE，此项随 license 阻断一并冻结）。
- 未验证 Python 3.9+/Node 18+ 声明的真实可运行性。
