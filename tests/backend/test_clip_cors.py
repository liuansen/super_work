from api_helpers import *  # noqa: F401,F403

CLIP_ORIGIN = "http://127.0.0.1:3000"


def test_clip_preflight_allows_editor_origin():
    response = client.options(
        "/api/clip/sessions",
        headers={
            "Origin": CLIP_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == CLIP_ORIGIN
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    # 编辑器用 Authorization 头而非 Cookie：契约要求不带 credentials
    assert "access-control-allow-credentials" not in response.headers


def test_clip_cors_does_not_leak_to_other_paths():
    response = client.get("/api/health", headers={"Origin": CLIP_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_clip_health_requires_login(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        assert client.get("/api/clip/health").status_code == 401
        token = _register_and_get_access_token("clip-health")
        response = client.get("/api/clip/health", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
