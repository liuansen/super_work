"""参考库：采集幂等、用户字段保留、列表过滤、越权。"""
from __future__ import annotations

URL = "https://www.douyin.com/video/710000000000000001"


def _collect(client, headers, account, url=URL):
    return client.post(
        "/api/douyin/references/collect",
        json={"account_id": account, "url": url},
        headers=headers,
    )


def test_collect_normalizes_and_dedupes(client, auth_headers, account_id):
    first = _collect(client, auth_headers, account_id)
    assert first.status_code == 200, first.text
    reference = first.json()["reference"]
    assert reference["provider_work_id"] == "710000000000000001"
    assert reference["title"].startswith("假作品-")
    assert reference["stats"]["digg_count"] > 0

    # 用户字段
    tagged = client.patch(
        f"/api/douyin/references/{reference['id']}",
        json={"tags": ["爆款"], "note": "开头3秒值得学"},
        headers=auth_headers,
    )
    assert tagged.status_code == 200
    assert tagged.json()["tags"] == ["爆款"]

    # 重复采集：同一行，用户字段保留，平台数据刷新
    second = _collect(client, auth_headers, account_id).json()["reference"]
    assert second["id"] == reference["id"]
    assert second["tags"] == ["爆款"]
    assert second["note"] == "开头3秒值得学"


def test_collect_requires_owned_active_account(client, auth_headers, second_auth_headers, account_id):
    # 未登录他人账号 → 404
    assert _collect(client, second_auth_headers, account_id).status_code == 404
    # 不存在的账号 → 404
    assert _collect(client, auth_headers, 99999).status_code == 404
    # 无法解析的链接 → 502（上游错误分类）
    bad = _collect(client, auth_headers, account_id, url="https://www.douyin.com/video/")
    assert bad.status_code == 502


def test_reference_list_filters(client, auth_headers, account_id):
    _collect(client, auth_headers, account_id)
    _collect(client, auth_headers, account_id, url="https://www.douyin.com/video/710000000000000002")

    rows = client.get("/api/douyin/references", headers=auth_headers).json()
    assert len(rows) == 2

    hit = client.get(
        "/api/douyin/references", params={"keyword": rows[0]["title"][:6]}, headers=auth_headers
    ).json()
    assert len(hit) == 1

    client.patch(
        f"/api/douyin/references/{rows[0]['id']}", json={"tags": ["对标"]}, headers=auth_headers
    )
    tagged = client.get("/api/douyin/references", params={"tag": "对标"}, headers=auth_headers).json()
    assert [r["id"] for r in tagged] == [rows[0]["id"]]


def test_references_are_user_scoped(client, auth_headers, second_auth_headers, account_id):
    _collect(client, auth_headers, account_id)
    assert client.get("/api/douyin/references", headers=second_auth_headers).json() == []
    work_id = client.get("/api/douyin/references", headers=auth_headers).json()[0]["id"]
    assert (
        client.patch(
            f"/api/douyin/references/{work_id}", json={"note": "hijack"}, headers=second_auth_headers
        ).status_code
        == 404
    )


def test_decrypt_failure_maps_to_auth_conflict(client, auth_headers, account_id, monkeypatch):
    """密钥轮换等导致的解密失败：统一 409，而不是裸 500。"""
    def boom(_value):
        raise RuntimeError("simulated fernet key rotation")

    monkeypatch.setattr("backend.app.douyin.accounts.decrypt_text", boom)
    response = _collect(client, auth_headers, account_id)
    assert response.status_code == 409
    assert "解密失败" in response.json()["detail"]
