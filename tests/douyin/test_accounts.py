"""账号：绑定/重新授权/隔离/脱敏。"""
from __future__ import annotations

COOKIE = "sessionid=good-cookie; uifid=ABC123"


def test_add_account_returns_sanitized_active_identity(client, auth_headers):
    response = client.post(
        "/api/douyin/accounts", json={"cookie": COOKIE}, headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["nickname"].startswith("测试账号-")
    assert data["provider_account_id"].startswith("sec-")
    # Cookie 绝不出现在响应里
    assert "good-cookie" not in response.text


def test_same_cookie_reauth_updates_same_row(client, auth_headers):
    first = client.post("/api/douyin/accounts", json={"cookie": COOKIE}, headers=auth_headers).json()
    second = client.post("/api/douyin/accounts", json={"cookie": COOKIE}, headers=auth_headers).json()
    assert second["id"] == first["id"]


def test_invalid_cookie_lands_as_invalid_account_with_reason(client, auth_headers):
    response = client.post(
        "/api/douyin/accounts", json={"cookie": "invalid-cookie-value"}, headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "invalid"
    assert "凭证确认失败" in data["status_message"]


def test_check_revalidates_and_delete_removes(client, auth_headers, account_id):
    checked = client.post(f"/api/douyin/accounts/{account_id}/check", headers=auth_headers)
    assert checked.status_code == 200
    assert checked.json()["status"] == "active"

    deleted = client.delete(f"/api/douyin/accounts/{account_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert client.get("/api/douyin/accounts", headers=auth_headers).json() == []


def test_other_user_account_is_404(client, auth_headers, second_auth_headers, account_id):
    response = client.post(
        f"/api/douyin/accounts/{account_id}/check", headers=second_auth_headers
    )
    assert response.status_code == 404
    assert client.delete(f"/api/douyin/accounts/{account_id}", headers=second_auth_headers).status_code == 404
    # 本人不受影响
    assert client.get("/api/douyin/accounts", headers=auth_headers).json()[0]["id"] == account_id


def test_reauth_with_other_bound_account_cookie_conflicts_409(client, auth_headers):
    """重新授权时粘贴了同用户另一已绑定账号的 Cookie：409，而不是撞唯一约束 500。"""
    first = client.post("/api/douyin/accounts", json={"cookie": COOKIE}, headers=auth_headers)
    assert first.status_code == 200
    second_cookie = "sessionid=other-cookie; uifid=DEF456"
    second = client.post(
        "/api/douyin/accounts", json={"cookie": second_cookie}, headers=auth_headers
    )
    assert second.status_code == 200
    second_id = second.json()["id"]
    assert second.json()["provider_account_id"] != first.json()["provider_account_id"]

    # 用第一账号的 Cookie 重新授权第二行：凭证身份冲突
    response = client.post(
        "/api/douyin/accounts",
        json={"cookie": COOKIE, "account_id": second_id},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert "已绑定" in response.json()["detail"]
    # 两行均保持原状
    rows = client.get("/api/douyin/accounts", headers=auth_headers).json()
    by_id = {row["id"]: row for row in rows}
    assert by_id[first.json()["id"]]["provider_account_id"] == first.json()["provider_account_id"]
    assert by_id[second_id]["provider_account_id"] == second.json()["provider_account_id"]


def test_delete_account_with_reference_detaches_and_keeps_reference(client, auth_headers, account_id):
    """删号：参考作品是用户数据，解绑保留而不是外键 500。"""
    collected = client.post(
        "/api/douyin/references/collect",
        json={"account_id": account_id, "url": "https://www.douyin.com/video/1234567890123456789"},
        headers=auth_headers,
    )
    assert collected.status_code == 200

    deleted = client.delete(f"/api/douyin/accounts/{account_id}", headers=auth_headers)
    assert deleted.status_code == 200
    works = client.get("/api/douyin/works", headers=auth_headers)
    assert works.status_code == 200
    assert len(works.json()) == 1
    assert works.json()[0]["provider_work_id"] == "1234567890123456789"
    assert client.get("/api/douyin/accounts", headers=auth_headers).json() == []


def test_delete_account_blocked_by_pending_task_then_allowed_after_cancel(
    client, auth_headers, account_id
):
    """有未终结发布任务时拒删（409）；取消后可删，终态任务随账号删除。"""
    task_response = client.post(
        "/api/douyin/publish/tasks",
        json={
            "account_id": account_id,
            "kind": "video",
            "media_names": ["xhs-upload-u1-fakevideo.mp4"],
            "title": "删除保护",
            "idempotency_key": "del-guard-key-0001",
        },
        headers=auth_headers,
    )
    assert task_response.status_code == 200, task_response.text
    task_id = task_response.json()["task"]["id"]

    blocked = client.delete(f"/api/douyin/accounts/{account_id}", headers=auth_headers)
    assert blocked.status_code == 409
    # 账号与任务都还在
    assert len(client.get("/api/douyin/accounts", headers=auth_headers).json()) == 1
    assert len(client.get("/api/douyin/publish/tasks", headers=auth_headers).json()) == 1

    cancelled = client.post(f"/api/douyin/publish/tasks/{task_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200

    deleted = client.delete(f"/api/douyin/accounts/{account_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert client.get("/api/douyin/accounts", headers=auth_headers).json() == []
    # 终态任务随账号删除
    assert client.get("/api/douyin/publish/tasks", headers=auth_headers).json() == []
