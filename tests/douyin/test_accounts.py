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
