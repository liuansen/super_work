"""抖音测试设施：每个测试独立临时 SQLite + 独立 app 实例 + 假适配器。

- 不进入真实 app lifespan（不启动调度器、不碰业务库/全局 engine）；
- 适配器依赖注入替换为 FakeDouyinAdapter，测试完全不触网；
- 媒体目录 monkeypatch 到 tmp_path，不污染真实 storage；
- 不为 pytest 进程导出 DATABASE_URL。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.adapters.douyin.fake import FakeDouyinAdapter
from backend.app.api import auth
from backend.app.api.platforms.douyin import adapter_dependency, router as douyin_router
from backend.app.core.database import Base, get_db


@pytest.fixture()
def media_dir(tmp_path, monkeypatch):
    """临时媒体目录 + 本用户可用的媒体文件名。"""
    media = tmp_path / "media"
    media.mkdir()
    (media / "xhs-upload-u1-fakevideo.mp4").write_bytes(b"fake-video-bytes")
    (media / "xhs-upload-u1-fakeimg.jpg").write_bytes(b"fake-image-bytes")
    monkeypatch.setattr(
        "backend.app.douyin.publishing._media_dir_name", lambda: str(media)
    )
    return media


@pytest.fixture()
def client(tmp_path, media_dir, monkeypatch):
    # 抖音套件不测认证限流（SEC-6）：固定用户名 fixture 会在同一进程内多次注册，
    # 必须与进程内存滑动窗口限流器隔离，避免测试结果依赖环境限流配置。
    monkeypatch.setattr(
        "backend.app.api.auth.check_rate_limit", lambda key, limit, now=None: True
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'douyin-test.db'}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    test_app = FastAPI()
    test_app.include_router(auth.router, prefix="/api")
    test_app.include_router(douyin_router, prefix="/api")

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[adapter_dependency] = FakeDouyinAdapter

    with TestClient(test_app) as test_client:  # 上下文管理器仅用于请求生命周期
        yield test_client
    test_app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/api/auth/register", json={"username": "douyin-op", "password": "secret123"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def second_auth_headers(client):
    response = client.post(
        "/api/auth/register", json={"username": "douyin-other", "password": "secret456"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def account_id(client, auth_headers):
    response = client.post(
        "/api/douyin/accounts",
        json={"cookie": "sessionid=good-cookie; uifid=ABC123"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    return response.json()["id"]
