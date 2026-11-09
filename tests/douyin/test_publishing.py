"""发布任务：幂等、显式执行、失败/未知结果、取消与越权。"""
from __future__ import annotations

GOOD_COOKIE = "sessionid=good-cookie; uifid=ABC123"


def _create(client, headers, account, *, key, kind="video", title="第一条视频", media=None, **overrides):
    payload = {
        "account_id": account,
        "kind": kind,
        "media_names": media if media is not None else ["xhs-upload-u1-fakevideo.mp4"],
        "title": title,
        "description": "描述内容",
        "visibility": 1,
        "allow_download": True,
        "idempotency_key": key,
        **overrides,
    }
    return client.post("/api/douyin/publish/tasks", json=payload, headers=headers)


def test_create_is_pending_and_idempotent(client, auth_headers, account_id):
    first = _create(client, auth_headers, account_id, key="idem-key-0001")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True
    assert body["task"]["status"] == "pending"

    again = _create(client, auth_headers, account_id, key="idem-key-0001")
    assert again.json()["created"] is False
    assert again.json()["task"]["id"] == body["task"]["id"]

    conflict = _create(client, auth_headers, account_id, key="idem-key-0001", title="不同的标题")
    assert conflict.status_code == 409


def test_create_validates_media_and_visibility(client, auth_headers, account_id):
    assert (
        _create(client, auth_headers, account_id, key="key-bad-media-01", media=["../etc/passwd"]).status_code
        == 400
    )
    assert (
        _create(client, auth_headers, account_id, key="key-bad-media-02", media=["xhs-upload-u2-other.mp4"]).status_code
        == 400
    )
    # 敌意文件名：Windows 盘符相对路径、隐藏路径分隔、绝对路径
    for hostile in ("C:evil.mp4", "\\\\server\\share\\v.mp4", "xhs-upload-u1-..\\..\\x.mp4", "/abs/v.mp4"):
        assert (
            _create(client, auth_headers, account_id, key=f"key-hostile-{abs(hash(hostile)) % 10**8}", media=[hostile]).status_code
            == 400
        ), hostile
    # visibility 越界 → pydantic 校验 422
    assert (
        _create(client, auth_headers, account_id, key="key-bad-vis-01", visibility=5).status_code
        == 422
    )
    # kind 与媒体类型不符 → 服务层 400
    assert (
        _create(
            client, auth_headers, account_id, key="key-bad-kind-01", kind="images",
            media=["xhs-upload-u1-fakevideo.mp4"],
        ).status_code
        == 400
    )
    assert (
        _create(
            client, auth_headers, account_id, key="key-bad-kind-02", kind="video",
            media=["xhs-upload-u1-fakeimg.jpg"],
        ).status_code
        == 400
    )


def test_execute_succeeds_and_records_provider_work(client, auth_headers, account_id):
    task = _create(client, auth_headers, account_id, key="exec-ok-00001").json()["task"]
    executed = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers)
    assert executed.status_code == 200
    data = executed.json()
    assert data["status"] == "succeeded"
    assert data["provider_work_id"]
    assert data["dispatched_at"]


def test_execute_platform_rejection_is_failed(client, auth_headers, account_id):
    task = _create(
        client, auth_headers, account_id, key="exec-fail-0001", title="boom 内容不合规"
    ).json()["task"]
    data = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).json()
    assert data["status"] == "failed"
    assert "拒绝" in data["error_message"]


def test_execute_network_error_is_unknown_never_succeeded(client, auth_headers):
    # pubnetfail：身份确认正常（授权有效），但发布阶段网络中断 → 结果不明
    account = client.post(
        "/api/douyin/accounts", json={"cookie": "pubnetfail-cookie"}, headers=auth_headers
    )
    assert account.status_code == 200
    assert account.json()["status"] == "active"
    task = _create(client, auth_headers, account.json()["id"], key="exec-net-0001").json()["task"]
    data = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).json()
    assert data["status"] == "unknown"
    assert "结果不明" in data["error_message"]
    # unknown 状态不可再执行（禁止自动重发语义：须人工处置）
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).status_code
        == 409
    )


def test_cancel_and_execute_state_race(client, auth_headers, account_id):
    task = _create(client, auth_headers, account_id, key="cancel-0000001").json()["task"]
    cancelled = client.post(f"/api/douyin/publish/tasks/{task['id']}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # cancelled 不可再执行；也不可再取消
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).status_code
        == 409
    )
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/cancel", headers=auth_headers).status_code
        == 409
    )


def test_execute_with_missing_media_fails_not_stuck_running(client, auth_headers, account_id, media_dir):
    task = _create(client, auth_headers, account_id, key="gonefile-0001").json()["task"]
    (media_dir / "xhs-upload-u1-fakevideo.mp4").unlink()  # 执行前媒体文件丢失
    data = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).json()
    assert data["status"] == "failed"
    assert "未发送" in data["error_message"]
    # 不允许把 failed 再当 pending 重复执行
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).status_code
        == 409
    )


def test_execute_twice_conflicts(client, auth_headers, account_id):
    task = _create(client, auth_headers, account_id, key="twice-0000001").json()["task"]
    assert client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).status_code == 200
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).status_code
        == 409
    )


def test_tasks_are_user_scoped(client, auth_headers, second_auth_headers, account_id):
    task = _create(client, auth_headers, account_id, key="scope-0000001").json()["task"]
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=second_auth_headers).status_code
        == 404
    )
    assert (
        client.post(f"/api/douyin/publish/tasks/{task['id']}/cancel", headers=second_auth_headers).status_code
        == 404
    )
    assert client.get("/api/douyin/publish/tasks", headers=second_auth_headers).json() == []
    assert len(client.get("/api/douyin/publish/tasks", headers=auth_headers).json()) == 1


def test_scheduled_task_carries_timing(client, auth_headers, account_id):
    task = _create(
        client, auth_headers, account_id, key="sched-0000001",
        scheduled_at="2026-11-10T09:30:00+08:00",
    ).json()["task"]
    assert task["scheduled_at"] == "2026-11-10T09:30:00"
    executed = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers)
    assert executed.status_code == 200
    assert executed.json()["status"] == "succeeded"


def test_scheduled_at_without_timezone_is_rejected(client, auth_headers, account_id):
    response = _create(
        client, auth_headers, account_id, key="sched-naive-001",
        scheduled_at="2026-11-10T09:30:00",
    )
    assert response.status_code == 400
    assert "时区" in response.json()["detail"]


def test_images_publish_happy_path_and_visibility_public(client, auth_headers, account_id):
    task = _create(
        client, auth_headers, account_id, key="images-ok-0001", kind="images",
        media=["xhs-upload-u1-fakeimg.jpg"], visibility=0,
    ).json()["task"]
    assert task["visibility"] == 0
    data = client.post(f"/api/douyin/publish/tasks/{task['id']}/execute", headers=auth_headers).json()
    assert data["status"] == "succeeded"
    assert data["provider_work_id"].startswith("7300")  # fake 图集 ID 前缀


def test_repeated_invalid_bind_reuses_single_row(client, auth_headers):
    first = client.post("/api/douyin/accounts", json={"cookie": "invalid-cookie-aaaa"}, headers=auth_headers).json()
    second = client.post("/api/douyin/accounts", json={"cookie": "invalid-cookie-bbbb"}, headers=auth_headers).json()
    assert first["id"] == second["id"]
    assert "bbbb" not in str(first)  # 响应不含 cookie
    rows = client.get("/api/douyin/accounts", headers=auth_headers).json()
    assert len(rows) == 1
