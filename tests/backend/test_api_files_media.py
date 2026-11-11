"""图片工具与媒体下载 / 媒体来源安全校验测试。

本文件由原 tests/backend/test_api.py 机械拆分而来；测试逻辑、断言、
mock 与 fixture 行为均未改动。
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from api_helpers import *  # noqa: F401,F403

def test_image_utility_routes_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        compose_response = client.post(
            "/api/files/images/compose",
            json={"title": "低卡早餐", "body": "三分钟做完", "width": 720, "height": 960},
        )
        resize_response = client.post(
            "/api/files/images/resize",
            json={"source_file_name": "xhs-image-u1-missing.png", "width": 320, "height": 320},
        )
        download_response = client.get("/api/files/media/xhs-image-u1-missing.png")

        assert compose_response.status_code == 401
        assert resize_response.status_code == 401
        assert download_response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_image_utilities_compose_resize_download_and_enforce_scope(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("image-utility-owner")
        intruder_token = _register_and_get_access_token("image-utility-intruder")

        compose_response = client.post(
            "/api/files/images/compose",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "title": "低卡早餐合集",
                "body": "适合通勤前快速准备的小红书封面",
                "width": 720,
                "height": 960,
                "accent_color": "#111111",
            },
        )

        assert compose_response.status_code == 200
        composed = compose_response.json()
        assert composed["file_name"].startswith("xhs-image-u1-")
        assert composed["file_name"].endswith(".png")
        assert composed["download_url"] == f"/api/files/media/{composed['file_name']}"
        assert composed["width"] == 720
        assert composed["height"] == 960
        assert composed["media_type"] == "image/png"

        download_response = client.get(
            composed["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.headers["content-type"].startswith("image/png")
        assert download_response.content.startswith(b"\x89PNG")

        resize_response = client.post(
            "/api/files/images/resize",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "source_file_name": composed["file_name"],
                "width": 320,
                "height": 320,
                "mode": "cover",
                "format": "jpeg",
                "quality": 82,
            },
        )

        assert resize_response.status_code == 200
        resized = resize_response.json()
        assert resized["file_name"].startswith("xhs-image-u1-")
        assert resized["file_name"].endswith(".jpg")
        assert resized["file_name"] != composed["file_name"]
        assert resized["width"] == 320
        assert resized["height"] == 320
        assert resized["media_type"] == "image/jpeg"

        resized_download_response = client.get(
            resized["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert resized_download_response.status_code == 200
        assert resized_download_response.content.startswith(b"\xff\xd8")

        forbidden_download = client.get(
            composed["download_url"],
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert forbidden_download.status_code == 404

        forbidden_resize = client.post(
            "/api/files/images/resize",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"source_file_name": composed["file_name"], "width": 320, "height": 320},
        )
        assert forbidden_resize.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_asset_rejects_path_traversal_and_off_whitelist_url(tmp_path):
    """P0 回归：发布素材 file_path 不允许任意本地路径 / 非白名单域名 URL。"""
    from backend.app.core.database import get_db

    db_dependency = _override_database(tmp_path)
    try:
        token = _register_and_get_access_token("media-guard-owner")
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {token}"},
            json={"platform": "xhs", "title": "Guard", "body": "Guard"},
        )
        assert draft_response.status_code == 200
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert job_response.status_code == 200, job_response.text
        job_id = job_response.json()["id"]

        for bad_path in (
            "../../etc/passwd",
            "storage/media/cover.png",
            "C:/code/super_work/backend/.env",
            "http://169.254.169.254/latest/meta-data",
            "https://evil.example.com/a.jpg",
        ):
            owned_media = _owned_media_fixture(token)
            response = client.post(
                f"/api/publish/jobs/{job_id}/assets",
                headers={"Authorization": f"Bearer {token}"},
                json={"asset_type": "image", "file_path": bad_path},
            )
            assert response.status_code == 422, bad_path

        # 合法来源：媒体文件名 / 平台 CDN URL
        ok_name = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        assert ok_name.status_code == 200
        ok_cdn = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {token}"},
            json={"asset_type": "image", "file_path": "https://sns-webpic-qc.xhscdn.com/a.jpg"},
        )
        assert ok_cdn.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_media_download_requires_auth_and_owner_prefix(tmp_path):
    """P1 回归：/api/files/media 需要鉴权且校验属主前缀。"""
    db_dependency = _override_database(tmp_path)
    try:
        # 未认证 → 401（注意：TestClient 会保存 cookie，须在任何注册/登录之前检查）
        anonymous = client.get("/api/files/media/whatever.png")
        assert anonymous.status_code == 401

        token = _register_and_get_access_token("media-view-owner")
        other_token = _register_and_get_access_token("media-view-other")

        # 上传一个属主文件
        upload = client.post(
            "/api/files/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("cover.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
        )
        assert upload.status_code == 200
        file_name = upload.json()["file_name"]
        assert file_name.startswith("xhs-upload-u")

        # 属主可读（Bearer）
        owner_resp = client.get(
            f"/api/files/media/{file_name}", headers={"Authorization": f"Bearer {token}"}
        )
        assert owner_resp.status_code == 200
        # 属主可读（media_token cookie，模拟 <img> 场景）
        register_resp = client.post(
            "/api/auth/login", json={"username": "media-view-owner", "password": "secret123"}
        )
        media_cookie = register_resp.cookies.get("media_token")
        assert media_cookie
        cookie_resp = client.get(f"/api/files/media/{file_name}", cookies={"media_token": media_cookie})
        assert cookie_resp.status_code == 200
        # 其他用户 → 404（属主前缀不匹配）
        other_resp = client.get(
            f"/api/files/media/{file_name}", headers={"Authorization": f"Bearer {other_token}"}
        )
        assert other_resp.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_media_source_guard_rejects_arbitrary_paths_and_hosts():
    """P0 回归：素材来源校验（路径穿越 / 非白名单域名 / 协议）。"""
    from backend.app.core.media_source import (
        InvalidMediaSource,
        validate_media_file_name,
        validate_media_source,
    )

    for bad in ("../../etc/passwd", "/etc/passwd", "C:\Windows\win.ini", "storage/media/a.png", ""):
        try:
            validate_media_source(bad)
        except InvalidMediaSource:
            pass
        else:
            raise AssertionError(f"应拒绝: {bad!r}")

    for bad_url in ("ftp://x.com/a.png", "http://127.0.0.1/a.png", "http://169.254.169.254/a.png",
                    "https://evil.example.com/a.png"):
        try:
            validate_media_source(bad_url)
        except InvalidMediaSource:
            pass
        else:
            raise AssertionError(f"应拒绝: {bad_url!r}")

    for good in ("cover.png", "/api/files/media/xhs-upload-u1-a.jpg",
                 "https://sns-img-qc.xhscdn.com/abc.jpg",
                 "https://www.xiaohongshu.com/a.png"):
        validate_media_source(good)

    try:
        validate_media_file_name("../x.png")
    except InvalidMediaSource:
        pass
    else:
        raise AssertionError("文件名不应允许路径成分")
