"""normalize_work / extract_provider_work_id 语义锁定（纯离线，不导入上游网络模块）。"""
from __future__ import annotations

from backend.app.adapters.douyin.real import extract_provider_work_id, normalize_work


def test_normalize_maps_seconds_to_ms_and_keeps_real_zero():
    raw = {
        "aweme_id": "710000000000000001",
        "desc": "标题",
        "create_time": 1_700_000_000,  # 上游是 Unix 秒
        "statistics": {
            "digg_count": 0,        # 真实 0 必须保留 0
            "comment_count": 12,
            "share_count": 0,
            "collect_count": 3,
        },
        "author": {"nickname": "作者", "sec_uid": "sec-x"},
        "video": {"duration": 45_000, "cover": {"url_list": ["http://c/1.jpg"]}},
    }
    snap = normalize_work(raw)
    assert snap.publish_time_ms == 1_700_000_000_000  # 秒 → 毫秒
    assert snap.duration_ms == 45_000
    assert snap.cover_url == "http://c/1.jpg"
    assert snap.stats.digg_count == 0  # 真实 0 不丢
    assert snap.stats.share_count == 0
    assert snap.work_url == "https://www.douyin.com/video/710000000000000001"


def test_normalize_missing_fields_stay_none():
    snap = normalize_work({"aweme_id": "710000000000000009"})
    assert snap.stats.digg_count is None  # 缺失是 None，不是伪造 0
    assert snap.stats.comment_count is None
    assert snap.publish_time_ms is None
    assert snap.duration_ms is None
    assert snap.title == ""


def test_normalize_missing_aweme_id_is_empty_string():
    assert normalize_work({}).provider_work_id == ""


def test_extract_provider_work_id_chains_and_gives_up_honestly():
    assert extract_provider_work_id({"aweme_id": "7101"}) == "7101"
    assert extract_provider_work_id({"data": {"aweme_id": 7102}}) == "7102"
    assert extract_provider_work_id({"data": "not-a-dict"}) is None
    assert extract_provider_work_id(None) is None
    assert extract_provider_work_id({}) is None
