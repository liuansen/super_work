"""小红书上游 payload 规范化（纯函数，无 IO）。

原本这些函数放在 ``api/platforms/xhs/pc.py`` / ``crawl.py`` 里，调度器和
服务层却要 import API 模块的私有符号——API 层任何重构都会静默打断后台
任务。这里下沉为独立模块，依赖方向恢复为 services ← api。

约定：输入永远是上游原始 dict，输出是扁平 dict（字段缺失保持空值，不编造）。
"""
from __future__ import annotations

import re
from typing import Any


def metric(value: Any) -> int:
    """把 "1.2万" / "12,345" / 123 统一解析为整数。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.lower().endswith("w"):
        multiplier = 10000
        text = text[:-1]
    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if not number_match:
        return 0
    return int(float(number_match.group(0)) * multiplier)


def first_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return first_url(value[0])
    if isinstance(value, dict):
        info_list = value.get("info_list")
        if isinstance(info_list, list) and len(info_list) > 1 and isinstance(info_list[1], dict):
            preferred_url = info_list[1].get("url")
            if preferred_url:
                return str(preferred_url)
        for key in ("url_default", "url_pre", "url", "src"):
            if value.get(key):
                return str(value[key])
        for nested in ("info_list", "image_list", "images"):
            if value.get(nested):
                return first_url(value[nested])
    return ""


def all_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            urls.extend(all_urls(item))
        return [url for index, url in enumerate(urls) if url and url not in urls[:index]]
    if isinstance(value, dict):
        direct = first_url(value)
        if direct:
            return [direct]
        urls = []
        for nested in ("info_list", "image_list", "images"):
            if value.get(nested):
                urls.extend(all_urls(value[nested]))
        return [url for index, url in enumerate(urls) if url and url not in urls[:index]]
    return []


def tag_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(item.strip().lstrip("#"))
        elif isinstance(item, dict):
            name = item.get("name") or item.get("tag") or item.get("keyword")
            if isinstance(name, str) and name.strip():
                names.append(name.strip().lstrip("#"))
    return names


def note_url(note_id: str, item: dict[str, Any], card: dict[str, Any]) -> str:
    xsec_token = card.get("xsec_token") or item.get("xsec_token") or ""
    if note_id and xsec_token:
        xsec_source = card.get("xsec_source") or item.get("xsec_source") or "pc_feed"
        return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source={xsec_source}"
    for value in (
        card.get("note_url"),
        card.get("url"),
        card.get("share_url"),
        item.get("note_url"),
        item.get("url"),
        item.get("share_url"),
    ):
        if isinstance(value, str) and value:
            return value
    if not note_id:
        return ""
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def data_items(raw_payload: Any) -> list[dict[str, Any]]:
    """从上游响应里取出条目列表，过滤掉推荐/热搜占位项。"""
    if not isinstance(raw_payload, dict):
        return []
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
    items = data.get("items") or data.get("notes") or data.get("list") or []
    return [
        item
        for item in items
        if isinstance(item, dict) and item.get("model_type") not in ("rec_query", "hot_query")
    ]


def normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    """把搜索/列表条目规范化成前端与业务层共用的扁平结构。"""
    card = item.get("note_card") or item.get("note") or item
    author = card.get("user") or card.get("author") or {}
    interact = card.get("interact_info") or card.get("interaction") or {}
    note_id = card.get("note_id") or card.get("id") or item.get("id") or ""
    timestamp = card.get("time") or card.get("create_time") or item.get("time") or item.get("create_time") or 0
    return {
        "note_id": note_id,
        "note_url": note_url(str(note_id), item, card),
        "title": card.get("display_title") or card.get("title") or "",
        "content": card.get("desc") or card.get("content") or "",
        "author_id": author.get("user_id") or author.get("id") or "",
        "author_name": author.get("nickname") or author.get("name") or "",
        "author_avatar": author.get("avatar") or author.get("avatar_url") or "",
        "cover_url": first_url(card.get("cover") or card.get("image_list") or card.get("images")),
        "image_urls": all_urls(card.get("image_list") or card.get("images") or card.get("cover")),
        "likes": metric(interact.get("liked_count") or interact.get("likes")),
        "collects": metric(interact.get("collected_count") or interact.get("collects")),
        "comments": metric(interact.get("comment_count") or interact.get("comments")),
        "shares": metric(interact.get("share_count") or interact.get("shares")),
        "type": card.get("type") or item.get("model_type") or "",
        "timestamp": timestamp,
        "raw": item,
    }
