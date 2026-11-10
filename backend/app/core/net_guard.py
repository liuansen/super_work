"""内网地址访问防护（SSRF guard）。

用于校验“用户可任意填写的 URL”在服务端发起请求前的目标地址。
- 无条件封禁：链路本地（含云元数据 169.254.169.254）、保留段、
  多播、未指定地址；
- 可选封禁（block_private=True）：环回与私网段。多租户部署应开启；
  单机自部署场景本地 LLM（Ollama 等）是合法端点，默认放行。
DNS 解析后逐一检查所有返回的 IP，防止域名指向内网 IP 的绕过。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _ip_forbidden(ip_text: str, *, block_private: bool) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    if ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return True
    if block_private and (ip.is_loopback or ip.is_private):
        return True
    return False


def public_http_url_error(url: str, *, resolve_dns: bool = True, block_private: bool = False) -> str | None:
    """校验 http(s) URL。合法返回 None，否则返回错误文案。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"仅允许 http/https 地址: {parsed.scheme or '(空)'}"
    host = parsed.hostname or ""
    if not host:
        return "URL 缺少主机名"

    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            return f"域名解析失败: {host} ({exc})"
        seen_ips: set[str] = set()
        for info in infos:
            ip_text = info[4][0]
            if ip_text in seen_ips:
                continue
            seen_ips.add(ip_text)
            # IPv6 字面量可能带 zone；去掉再判断
            if _ip_forbidden(ip_text.split("%")[0], block_private=block_private):
                return f"不允许访问保留/内网地址: {host} -> {ip_text}"
    return None
