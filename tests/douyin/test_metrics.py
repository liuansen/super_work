"""指标：快照语义（真实值/缺失为 None）、最新快照、账号批量刷新、越权。"""
from __future__ import annotations

URL = "https://www.douyin.com/video/710000000000000001"


def test_refresh_writes_new_snapshot_and_works_list_shows_latest(client, auth_headers, account_id):
    reference = client.post(
        "/api/douyin/references/collect",
        json={"account_id": account_id, "url": URL},
        headers=auth_headers,
    ).json()["reference"]

    refreshed = client.post(
        f"/api/douyin/works/{reference['id']}/refresh", json={}, headers=auth_headers
    )
    assert refreshed.status_code == 200, refreshed.text
    snapshot = refreshed.json()
    assert snapshot["availability"] == "available"
    assert snapshot["digg_count"] > 0
    assert snapshot["collected_at"]

    works = client.get("/api/douyin/works", headers=auth_headers).json()
    assert len(works) == 1
    assert works[0]["latest_metrics"]["digg_count"] == snapshot["digg_count"]

    # 再刷一次 → 两条快照，works 展示最新一条
    second = client.post(
        f"/api/douyin/works/{reference['id']}/refresh", json={}, headers=auth_headers
    ).json()
    assert second["digg_count"] == snapshot["digg_count"]  # fake 确定性：同作品同值


def test_refresh_account_creates_references_with_snapshots(client, auth_headers, account_id):
    response = client.post(
        "/api/douyin/works/refresh-account", json={"account_id": account_id}, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    snapshots = response.json()["snapshots"]
    assert len(snapshots) == 3  # fake 每账号 3 个作品

    works = client.get("/api/douyin/works", headers=auth_headers).json()
    assert len(works) == 3
    for work in works:
        assert work["latest_metrics"]["availability"] == "available"
        assert work["author_sec_uid"].startswith("sec-")


def test_metrics_are_user_scoped(client, auth_headers, second_auth_headers, account_id):
    reference = client.post(
        "/api/douyin/references/collect",
        json={"account_id": account_id, "url": URL},
        headers=auth_headers,
    ).json()["reference"]
    assert (
        client.post(
            f"/api/douyin/works/{reference['id']}/refresh", json={}, headers=second_auth_headers
        ).status_code
        == 404
    )
    assert client.get("/api/douyin/works", headers=second_auth_headers).json() == []


def test_refresh_without_usable_account_conflicts(client, auth_headers, second_auth_headers, account_id):
    reference = client.post(
        "/api/douyin/references/collect",
        json={"account_id": account_id, "url": URL},
        headers=auth_headers,
    ).json()["reference"]
    # 其他用户的账号 → 404；不存在账号 → 404/409
    assert (
        client.post(
            f"/api/douyin/works/{reference['id']}/refresh",
            json={"account_id": account_id}, headers=second_auth_headers,
        ).status_code
        == 404
    )


def test_refresh_with_mismatched_work_id_maps_to_400(client, auth_headers, account_id):
    """上游返回的作品 ID 与参考记录不一致：400，而不是裸 500。"""
    from dataclasses import replace

    from backend.app.adapters.douyin.fake import FakeDouyinAdapter
    from backend.app.api.platforms.douyin import adapter_dependency

    class _MismatchAdapter(FakeDouyinAdapter):
        def crawl_work(self, cookie: str, url: str):
            snapshot = super().crawl_work(cookie, url)
            return replace(snapshot, provider_work_id="999999")

    reference = client.post(
        "/api/douyin/references/collect", json={"account_id": account_id, "url": URL},
        headers=auth_headers,
    ).json()["reference"]

    client.app.dependency_overrides[adapter_dependency] = _MismatchAdapter
    try:
        response = client.post(
            f"/api/douyin/works/{reference['id']}/refresh", json={}, headers=auth_headers
        )
        assert response.status_code == 400
        assert "不一致" in response.json()["detail"]
    finally:
        client.app.dependency_overrides[adapter_dependency] = FakeDouyinAdapter
