"""认证注册 / 登录 / 刷新 / me 接口测试。

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

def test_auth_register_login_me_and_refresh_use_real_tokens(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        register_response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "secret123"},
        )
        assert register_response.status_code == 200
        registered = register_response.json()
        assert registered["token_type"] == "bearer"
        assert registered["access_token"]
        # SEC-7：refresh token 改为 HttpOnly Cookie，默认不再进响应体
        assert registered["refresh_token"] is None
        assert register_response.cookies.get("refresh_token")
        assert registered["user"]["username"] == "operator"

        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered['access_token']}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "operator"

        login_response = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "secret123"},
        )
        assert login_response.status_code == 200
        logged_in = login_response.json()
        assert logged_in["access_token"]
        assert logged_in["refresh_token"] is None
        assert login_response.cookies.get("refresh_token")

        # Cookie 流程刷新（模拟浏览器）：需要 X-Requested-With 头，无需 body
        refresh_response = client.post(
            "/api/auth/refresh",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["token_type"] == "bearer"
        assert refreshed["access_token"]
    finally:
        app.dependency_overrides.pop(get_db, None)

def test_auth_rejects_duplicate_user_and_bad_credentials(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "secret123"},
        )
        assert response.status_code == 200

        duplicate_response = client.post(
            "/api/auth/register",
            json={"username": "operator", "password": "different123"},
        )
        assert duplicate_response.status_code == 400

        bad_login_response = client.post(
            "/api/auth/login",
            json={"username": "operator", "password": "wrong-password"},
        )
        assert bad_login_response.status_code == 401

        missing_auth_response = client.get("/api/auth/me")
        assert missing_auth_response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
