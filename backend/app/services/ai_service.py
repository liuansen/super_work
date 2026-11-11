from __future__ import annotations

import json
import re
from typing import Any, Protocol

import requests

from backend.app.models import ModelConfig

# 匹配“1. / 1、 / 1- / 1) / （1）”等序号前缀（str.strip(chars) 会误删标题两端的数字）
_ORDERED_LIST_PREFIX_RE = re.compile(r"^\s*(?:[（(]?\d{1,3}[.、\-)）]|[•·]\s*|[-*]\s+)+\s*")


class TextAiClient(Protocol):
    def rewrite_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        instruction: str,
    ) -> str:
        ...

    def generate_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        topic: str,
        reference: str,
        instruction: str,
    ) -> dict[str, str]:
        ...

    def generate_titles(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
    ) -> list[str]:
        ...

    def generate_tags(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
    ) -> list[str]:
        ...

    def polish_text(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        text: str,
        instruction: str,
    ) -> str:
        ...


class ImageAiClient(Protocol):
    def generate_cover(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        size: str,
        style: str,
    ) -> dict[str, Any]:
        ...

    def generate_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        reference_images: list[str] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        ...

    def describe_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        image_url: str,
        instruction: str,
    ) -> str:
        ...


def _candidate_response_encodings(response: requests.Response) -> list[str]:
    encodings: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", response.apparent_encoding, response.encoding):
        normalized = (encoding or "").strip()
        if normalized and normalized.lower() not in {item.lower() for item in encodings}:
            encodings.append(normalized)
    return encodings


def _load_json_response(response: requests.Response) -> Any:
    raw = response.content
    last_error: Exception | None = None
    for encoding in _candidate_response_encodings(response):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc

    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        last_error = exc

    raise ValueError("AI response is not valid JSON") from last_error


def _assert_public_model_endpoint(base_url: str) -> None:
    """SEC-5（review P1-5）：AI 请求（带 Authorization）发出前校验端点。

    保存/测试连接时已校验过，但存在 TOCTOU——域名可被解析到内网。
    这里做完整 DNS 解析校验；allow_private_model_endpoints=true（本地
    Ollama 场景）仍放行私网/环回，但无条件拒绝链路本地/保留段。
    """
    from backend.app.core.config import get_settings
    from backend.app.core.net_guard import public_http_url_error

    error = public_http_url_error(
        base_url,
        resolve_dns=True,
        block_private=not getattr(get_settings(), "allow_private_model_endpoints", True),
    )
    if error:
        raise ValueError(f"模型端点被安全策略拒绝: {error}")


# 匹配 "属于某用户的本地媒体文件名"（xhs-<kind>-u<数字>-…），与
# core/media_source._OWNED_MEDIA_RE 同口径；此处仅做形态判断，归属校验
# 仍统一交给 assert_owned_media_name。
_OWNED_MEDIA_NAME_RE = re.compile(r"^xhs-[a-z]+-u\d+-")


def _post_no_redirect(url: str, **kwargs: Any) -> requests.Response:
    """向用户可配置的模型端点发请求时禁止跟随重定向。

    SSRF 校验（_assert_public_model_endpoint）只覆盖 base_url 本身；
    requests 默认 allow_redirects=True，攻击者可让自有域名 302 到内网
    （如 169.254.169.254），从而绕过校验，并把 Authorization 里的
    API Key 一并送给重定向目标。这里拒绝任何重定向响应。
    """
    kwargs.setdefault("allow_redirects", False)
    response = requests.post(url, **kwargs)
    # 用 status_code 判定（而非 is_redirect），便于测试注入的轻量 response 替身
    if 300 <= getattr(response, "status_code", 0) < 400:
        raise ValueError("模型端点返回重定向，已按安全策略拒绝跟随")
    return response


class OpenAICompatibleTextClient:
    def _complete(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> str:
        if not model_config.base_url:
            raise ValueError("Text model base_url is required")
        if not model_config.model_name:
            raise ValueError("Text model_name is required")
        if not api_key:
            raise ValueError("Text model api_key is required")

        endpoint = f"{model_config.base_url.rstrip('/')}/chat/completions"
        _assert_public_model_endpoint(model_config.base_url)
        response = _post_no_redirect(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_config.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = _load_json_response(response)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("AI response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI response content is empty")
        return content.strip()

    def rewrite_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        instruction: str,
    ) -> str:
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书内容运营编辑，负责在保留事实的前提下改写成自然、可发布的种草笔记。",
            user_prompt=(
                f"改写要求：{instruction or '提升表达、增强小红书语感'}\n\n"
                f"标题：{title}\n\n正文：\n{body}"
            ),
        )

    def generate_note(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        topic: str,
        reference: str,
        instruction: str,
    ) -> dict[str, str]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书内容策划，输出可发布的标题和正文。",
            user_prompt=(
                "请生成一篇小红书笔记，格式必须是：\n标题：...\n正文：...\n\n"
                f"选题：{topic}\n参考材料：{reference or '无'}\n要求：{instruction or '自然、有信息密度'}"
            ),
        )
        title = topic
        body = content
        for line in content.splitlines():
            if line.startswith("标题："):
                title = line.replace("标题：", "", 1).strip() or title
                break
        if "正文：" in content:
            body = content.split("正文：", 1)[1].strip()
        return {"title": title, "body": body}

    def generate_titles(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
    ) -> list[str]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书标题优化专家。",
            user_prompt=f"请给出 {count} 个小红书标题，每行一个。\n原标题：{title}\n正文：{body}",
        )
        titles = []
        for line in content.splitlines():
            cleaned = _ORDERED_LIST_PREFIX_RE.sub("", line).strip()
            if cleaned:
                titles.append(cleaned)
        return titles[:count]

    def rewrite_title(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        max_length: int = 15,
    ) -> str:
        """改写单个标题（auto task 使用，避免调用方触达私有 _complete）。"""
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书标题创作专家。",
            user_prompt=f"为以下小红书笔记改写一个吸引人的标题（{max_length}字以内）：\n\n原标题：{title}\n\n正文：{body[:200]}",
            temperature=0.8,
        )
        return content.strip().strip('"').strip("'").strip("《》")

    def generate_tags(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        title: str,
        body: str,
        count: int,
    ) -> list[str]:
        content = self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书 SEO 和话题标签专家。",
            user_prompt=f"请给出 {count} 个小红书话题标签，只输出标签，用逗号或换行分隔。\n标题：{title}\n正文：{body}",
        )
        separators = content.replace("，", ",").replace("\n", ",").split(",")
        return [item.strip().lstrip("#") for item in separators if item.strip()][:count]

    def polish_text(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        text: str,
        instruction: str,
    ) -> str:
        return self._complete(
            model_config=model_config,
            api_key=api_key,
            system_prompt="你是小红书正文润色编辑。",
            user_prompt=f"润色要求：{instruction or '更自然、清晰、有种草感'}\n\n原文：\n{text}",
        )


class OpenAICompatibleImageClient:
    def _validate(self, *, model_config: ModelConfig, api_key: str) -> None:
        if not model_config.base_url:
            raise ValueError("Image model base_url is required")
        if not model_config.model_name:
            raise ValueError("Image model_name is required")
        if not api_key:
            raise ValueError("Image model api_key is required")

    def generate_cover(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        size: str,
        style: str,
    ) -> dict[str, Any]:
        # BE-11：size 需要真正写入请求体（此前被静默丢弃）
        return self.generate_image(
            model_config=model_config,
            api_key=api_key,
            prompt=f"{prompt}\nStyle: {style or 'clean XHS cover'}",
            size=size,
        )

    def generate_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        prompt: str,
        reference_images: list[str] | None = None,
        size: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        self._validate(model_config=model_config, api_key=api_key)
        endpoint = f"{model_config.base_url.rstrip('/')}/images/generations"
        _assert_public_model_endpoint(model_config.base_url)
        body: dict[str, Any] = {
            "model": model_config.model_name,
            "prompt": prompt,
            "response_format": "url",
        }
        if size:
            body["size"] = size
        if reference_images:
            resolved = [self._resolve_image_ref(url, user_id=user_id) for url in reference_images]
            if len(resolved) == 1:
                body["image"] = resolved[0]
            else:
                body["image"] = resolved
                body["sequential_image_generation"] = "disabled"
            body["watermark"] = False
        try:
            response = _post_no_redirect(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                error_payload = _load_json_response(exc.response) if exc.response else {}
                detail = error_payload.get("error", {}).get("message", "") if isinstance(error_payload, dict) else ""
            except Exception:
                pass
            raise ValueError(f"图片生成失败: {detail or exc}") from exc
        payload = _load_json_response(response)
        try:
            item = payload["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Image response missing data[0]") from exc
        image_ref = item.get("url") or item.get("b64_json")
        if not isinstance(image_ref, str) or not image_ref:
            raise ValueError("Image response missing url or b64_json")
        return {"url": image_ref, "raw": payload}

    @staticmethod
    def _resolve_image_ref(url: str, *, user_id: int | None = None) -> str:
        if url.startswith(("http://", "https://", "data:")):
            return url
        if url.startswith("/api/files/media/") or _OWNED_MEDIA_NAME_RE.match(url):
            # 本地媒体（带 /api/files/media/ 前缀或裸文件名两种形态）：
            # 必须归属当前用户，否则会把他人素材 base64 外发给用户自选的
            # 第三方模型端点（SEC-2）。口径与 creator 上传端点一致。
            import base64
            from pathlib import Path
            from backend.app.core.media_source import assert_owned_media_name
            from backend.app.core.media_storage import media_path

            file_name = url.rsplit("/", 1)[-1]
            if user_id is None:
                raise ValueError("引用本地素材时必须提供用户身份")
            assert_owned_media_name(file_name, user_id)
            local = media_path(file_name)
            if local.is_file():
                raw = local.read_bytes()
                ext = local.suffix.lower().lstrip(".")
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
                return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
            raise ValueError(f"参考图文件不存在: {file_name[:64]}")
        return url

    def describe_image(
        self,
        *,
        model_config: ModelConfig,
        api_key: str,
        image_url: str,
        instruction: str,
    ) -> str:
        self._validate(model_config=model_config, api_key=api_key)
        endpoint = f"{model_config.base_url.rstrip('/')}/chat/completions"
        _assert_public_model_endpoint(model_config.base_url)
        response = _post_no_redirect(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model_config.model_name,
                "messages": [
                    {"role": "system", "content": "你是小红书图片分析助手。"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": instruction or "描述这张图片适合的小红书卖点。"},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = _load_json_response(response)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("AI response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI image description is empty")
        return content.strip()
