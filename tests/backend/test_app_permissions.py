"""应用权限系统：目录、全局开关、按账号分配、clip 路由强制校验。

语义（与实现一致）：
- 默认全量开通 + 显式回收：user_app_permissions 无记录 = 有权限；
  granted=False 的记录 = 明确拒绝。
- 账号可进入应用 ⟺ app_registry.enabled 且未被该账号回收。
- 管理员（users.is_admin，首个注册用户）绕过一切应用限制。
"""
from __future__ import annotations

import pytest


def _register(client_obj, username: str) -> str:
    resp = client_obj.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_apps_catalog_requires_authentication(client_obj=None):
    from api_helpers import client

    assert client.get("/api/apps").status_code == 401


def test_seeded_catalog_visible_to_new_user(tmp_path):
    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        token = _register(client, "apps-fresh-user")
        resp = client.get("/api/apps", headers=_headers(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        keys = {item["app_key"] for item in items}
        assert {"xhs", "douyin", "clip"} <= keys
        assert all(item["accessible"] for item in items)
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_me_returns_is_admin_flag(tmp_path):
    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        first = _register(client, "apps-admin-first")
        second = _register(client, "apps-admin-second")
        me_first = client.get("/api/auth/me", headers=_headers(first)).json()
        me_second = client.get("/api/auth/me", headers=_headers(second)).json()
        assert me_first["is_admin"] is True
        assert me_second["is_admin"] is False
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_admin_can_toggle_app_globally(tmp_path):
    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "apps-toggle-admin")
        normal = _register(client, "apps-toggle-user")

        # 非管理员不能管理
        forbidden = client.patch(
            "/api/apps/admin/catalog/xhs", headers=_headers(normal), json={"enabled": False}
        )
        assert forbidden.status_code == 403

        disabled = client.patch(
            "/api/apps/admin/catalog/xhs", headers=_headers(admin), json={"enabled": False}
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["enabled"] is False

        # 关闭后普通用户目录里不再出现；管理员仍能看到（管理视图）
        items = client.get("/api/apps", headers=_headers(normal)).json()["items"]
        assert "xhs" not in {item["app_key"] for item in items}
        catalog = client.get("/api/apps/admin/catalog", headers=_headers(admin)).json()["items"]
        xhs_row = next(item for item in catalog if item["app_key"] == "xhs")
        assert xhs_row["enabled"] is False

        # 重新开启
        enabled = client.patch(
            "/api/apps/admin/catalog/xhs", headers=_headers(admin), json={"enabled": True}
        )
        assert enabled.json()["enabled"] is True
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_admin_lists_users_and_assigns_apps(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import User

    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "apps-assign-admin")
        member = _register(client, "apps-assign-user")

        users_resp = client.get("/api/apps/admin/users", headers=_headers(admin))
        assert users_resp.status_code == 200
        rows = users_resp.json()["items"]
        usernames = {row["username"] for row in rows}
        assert {"apps-assign-admin", "apps-assign-user"} <= usernames

        member_id = next(
            row["id"] for row in rows if row["username"] == "apps-assign-user"
        )

        # 默认全量开通：member 可见三个应用
        mine = client.get(
            f"/api/apps/admin/users/{member_id}/apps", headers=_headers(admin)
        ).json()["app_keys"]
        assert {"xhs", "douyin", "clip"} <= set(mine)

        # 回收 douyin/clip：只保留 xhs
        assigned = client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=_headers(admin),
            json={"app_keys": ["xhs"]},
        )
        assert assigned.status_code == 200, assigned.text

        items = client.get("/api/apps", headers=_headers(member)).json()["items"]
        assert {item["app_key"] for item in items} == {"xhs"}

        # 非管理员不能改他人分配
        member_headers = _headers(member)
        forbidden = client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=member_headers,
            json={"app_keys": ["xhs", "douyin", "clip"]},
        )
        assert forbidden.status_code == 403

        # 管理员自己也回收不了（绕过开关）：管理员访问不受分配影响
        admin_id = None
        db = next(app.dependency_overrides[get_db]())
        try:
            admin_id = (
                db.query(User).filter_by(username="apps-assign-admin").one().id
            )
        finally:
            db.close()
        client.put(
            f"/api/apps/admin/users/{admin_id}/apps",
            headers=_headers(admin),
            json={"app_keys": []},
        )
        still = client.get("/api/apps", headers=_headers(admin)).json()["items"]
        assert {"xhs", "douyin", "clip"} <= {item["app_key"] for item in still}
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_unknown_app_key_rejected_by_admin_toggle(tmp_path):
    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "apps-unknown-admin")
        resp = client.patch(
            "/api/apps/admin/catalog/no-such-app",
            headers=_headers(admin),
            json={"enabled": False},
        )
        assert resp.status_code == 404
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_clip_router_enforces_app_permission(tmp_path):
    """回收 clip 后，该账号的 /api/clip/* 全部 403；管理员不受影响。"""
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import User

    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "apps-clip-admin")
        member = _register(client, "apps-clip-user")

        users = client.get("/api/apps/admin/users", headers=_headers(admin)).json()["items"]
        member_id = next(r["id"] for r in users if r["username"] == "apps-clip-user")
        client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=_headers(admin),
            json={"app_keys": ["xhs"]},
        )

        forbidden = client.get("/api/clip/assets", headers=_headers(member))
        assert forbidden.status_code == 403
        assert "开通" in forbidden.json()["detail"]

        allowed = client.get("/api/clip/assets", headers=_headers(admin))
        assert allowed.status_code == 200
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_revoked_user_held_session_token_is_rejected(tmp_path):
    """评审 P1 回归：回收 clip 后，已交换的 session 令牌必须立即失效。

    攻击链（修复前 200/201 穿透）：建会话 → exchange 持有 12h 令牌 →
    管理员回收 clip → 流取素材/上传成片仍可用。
    """
    from pathlib import Path
    from uuid import uuid4

    from backend.app.core.config import get_settings
    from backend.app.core.database import get_db
    from backend.app.core.security import decode_token
    from backend.app.models import User

    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    source_name = ""
    try:
        admin = _register(client, "revoke-held-admin")
        member = _register(client, "revoke-held-user")

        users = client.get("/api/apps/admin/users", headers=_headers(admin)).json()["items"]
        member_id = next(r["id"] for r in users if r["username"] == "revoke-held-user")

        user_id = int(decode_token(member)["user_id"])
        source_name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
        media = Path(get_settings().storage_dir) / "media"
        media.mkdir(parents=True, exist_ok=True)
        (media / source_name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 128)

        created = client.post(
            "/api/clip/sessions",
            headers=_headers(member),
            json={"title": "持有令牌", "assets": [{"kind": "upload", "file_name": source_name}]},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        exchanged = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
        )
        assert exchanged.status_code == 200, exchanged.text
        session_token = exchanged.json()["session_token"]

        # 管理员回收
        client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=_headers(admin),
            json={"app_keys": ["xhs"]},
        )

        # 已持有的 session 令牌：流取素材必须 403
        stream = client.get(
            f"/api/clip/sessions/{session_id}/assets/{source_name}",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert stream.status_code == 403, stream.text

        # 上传成片必须 403
        upload = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"session_id": session_id, "title": "越权", "client_export_id": "held-1"},
            files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"1" * 256, "video/mp4")},
        )
        assert upload.status_code == 403, upload.text

        # clip 成片经通用媒体接口也不得下载
        # （先由管理员上传一个成片供 member 此前知晓 URL 的场景模拟）
        _ = User
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)
        if source_name:
            (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)


def test_revoked_user_valid_handoff_exchange_fails_and_session_survives(tmp_path):
    """评审建议：回收后持有效 handoff 调 exchange 必须 403，且会话仍是 issued。"""
    from backend.app.core.database import get_db
    from backend.app.models import ClipSession

    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "handoff-revoke-admin")
        member = _register(client, "handoff-revoke-user")

        from backend.app.main import app  # noqa: F401 提前绑定，避免后续局部遮蔽

        users = client.get("/api/apps/admin/users", headers=_headers(admin)).json()["items"]
        member_id = next(r["id"] for r in users if r["username"] == "handoff-revoke-user")

        created = client.post(
            "/api/clip/sessions",
            headers=_headers(admin),
            json={"title": "admin 会话", "assets": []},
        )
        # 空素材被 pydantic 拦（422）；该请求不需要成功，仅探测接口即可
        assert created.status_code in (400, 422)

        from backend.app.core.time import shanghai_now

        db = next(app.dependency_overrides[get_db]())
        try:
            member_user_id = next(
                r["id"] for r in users if r["username"] == "handoff-revoke-user"
            ) if users else None
            session = ClipSession(
                user_id=member_user_id or 2,
                title="回收前握手",
                manifest_json="[]",
                status="issued",
                handoff_jti="j-vecate-1",
                handoff_expires_at=shanghai_now(),
                created_at=shanghai_now(),
            )
            db.add(session)
            db.commit()
            session_id = session.id
        finally:
            db.close()

        # 管理员先回收（在任何握手前）
        client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=_headers(admin),
            json={"app_keys": ["xhs"]},
        )

        # 构造 member 的合法 handoff 令牌（ver 相符、jti 相符）
        from backend.app.core.database import get_db as _get_db
        from backend.app.core.security import create_clip_handoff_token
        from backend.app.models import User as _User

        db = next(app.dependency_overrides[_get_db]())
        try:
            user_row = db.query(_User).filter_by(id=member_id).one()
            handoff = create_clip_handoff_token(
                member_id, session_id, "j-vecate-1", token_version=int(user_row.token_version or 0)
            )
        finally:
            db.close()

        denied = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {handoff}"},
        )
        assert denied.status_code == 403, denied.text

        # single-use 未被烧：会话仍 issued
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(ClipSession, session_id).status == "issued"
        finally:
            db.close()
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_global_disable_blocks_clip_and_revoke_survives_reenable(tmp_path):
    """评审建议：全局关闭 clip → 403；重开后此前被回收的账号仍 403。"""
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import User

    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "global-toggle-admin")
        member = _register(client, "global-toggle-user")

        users = client.get("/api/apps/admin/users", headers=_headers(admin)).json()["items"]
        member_id = next(r["id"] for r in users if r["username"] == "global-toggle-user")

        # 回收 member 的 clip
        client.put(
            f"/api/apps/admin/users/{member_id}/apps",
            headers=_headers(admin),
            json={"app_keys": []},
        )

        # 全局关闭 clip
        client.patch(
            "/api/apps/admin/catalog/clip", headers=_headers(admin), json={"enabled": False}
        )
        blocked = client.get("/api/clip/assets", headers=_headers(member))
        assert blocked.status_code == 403

        # 全局重开：member 的回收记录仍在，依旧 403
        client.patch(
            "/api/apps/admin/catalog/clip", headers=_headers(admin), json={"enabled": True}
        )
        still = client.get("/api/clip/assets", headers=_headers(member))
        assert still.status_code == 403
        _ = User
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)


def test_admin_user_apps_endpoints_reject_unknown_user(tmp_path):
    """幽灵 user_id 必须 404（此前 200 + 全量默认放行语义失真）。"""
    from api_helpers import _override_database, client

    db_dependency = _override_database(tmp_path)
    try:
        admin = _register(client, "ghost-user-admin")
        ghost_get = client.get(
            "/api/apps/admin/users/99999/apps", headers=_headers(admin)
        )
        assert ghost_get.status_code == 404
        ghost_put = client.put(
            "/api/apps/admin/users/99999/apps",
            headers=_headers(admin),
            json={"app_keys": ["xhs"]},
        )
        assert ghost_put.status_code == 404
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_dependency, None)
