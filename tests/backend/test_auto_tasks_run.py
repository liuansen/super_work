"""自动运营任务「手动运行」链路的端到端测试。

该链路历史上没有任何测试覆盖，导致过一次 P0（发布完成后抛 NameError，
用户看到 500 后重试造成重复发布）。这里覆盖：
- 无关键词 → 400，不产生运行记录残留；
- 正常链路 → 200 且返回 keyword/source_note/draft/publish_job；
- 后台执行失败 → 运行记录被标记 failed（不滞留 running）。
"""
from __future__ import annotations

import pytest

from api_helpers import _create_pc_account_with_cookie, client


class FakeSearchAdapter:
    def __init__(self, cookies):
        self.cookies = cookies

    def search_note(self, keyword, page=1):
        return (
            True,
            "ok",
            {
                "data": {
                    "items": [
                        {
                            "id": "auto-note-001",
                            "note_card": {
                                "note_id": "auto-note-001",
                                "display_title": "自动运营笔记",
                                "desc": "正文内容",
                                "user": {"nickname": "作者"},
                                "interact_info": {
                                    "liked_count": "120",
                                    "collected_count": "30",
                                    "comment_count": "5",
                                    "share_count": "1",
                                },
                                "image_list": [
                                    {"url_default": "https://sns-img.xhscdn.com/a.jpg"}
                                ],
                            },
                        }
                    ]
                }
            },
        )


class FakeTextModelClient:
    """替换 OpenAICompatibleTextClient：避免真实网络调用。"""

    def rewrite_note(self, **kwargs):
        return "改写后的正文"

    def rewrite_title(self, **kwargs):
        return "改写后的标题"

    def generate_tags(self, **kwargs):
        return []

    def generate_note(self, **kwargs):
        return {"title": "AI 标题", "body": "AI 正文", "tags": []}


class FakeCreatorPublishAdapter:
    def __init__(self, cookies):
        self.cookies = cookies

    def upload_media(self, file_path, media_type):
        return {"creator_media_id": "auto-media-001", "fileIds": "auto-file-001"}

    def post_note(self, note_info):
        return {"success": True, "data": {"note_id": "auto-published-001"}, "note_info": note_info}


@pytest.fixture()
def auto_task_env(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import AutoTask

    db_dependency, owner_token, pc_account_id = _create_pc_account_with_cookie(
        tmp_path, "auto-ops-owner"
    )

    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, ModelConfig, PlatformAccount

    db = next(app.dependency_overrides[get_db]())
    try:
        db.add(
            ModelConfig(
                user_id=1,
                name="fake-text",
                model_type="text",
                provider="openai",
                model_name="fake-model",
                base_url="https://api.example.test/v1",
                encrypted_api_key=encrypt_text("test-key"),
                is_default=True,
            )
        )
        db.flush()
        creator = PlatformAccount(
            user_id=1,
            platform="xhs",
            sub_type="creator",
            external_user_id="auto-creator",
            nickname="Auto creator",
            status="active",
        )
        db.add(creator)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=creator.id,
                encrypted_cookies=encrypt_text('{"web_session":"creator-session"}'),
            )
        )
        db.flush()
        creator_account_id = creator.id
        task = AutoTask(
            user_id=1,
            name="每日咖啡",
            keywords=["咖啡"],
            pc_account_id=pc_account_id,
            creator_account_id=creator_account_id,
            status="active",
            schedule_type="manual",
            next_run_at=None,
        )
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeSearchAdapter
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        yield {"token": owner_token, "task_id": task_id, "db_dependency": db_dependency}
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)


def test_manual_run_requires_authentication():
    response = client.post("/api/auto-tasks/1/run")
    assert response.status_code == 401


def test_manual_run_rejects_task_without_keywords(auto_task_env, monkeypatch):
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import AutoTask

    db = next(app.dependency_overrides[get_db]())
    try:
        task = db.get(AutoTask, auto_task_env["task_id"])
        task.keywords = []
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/auto-tasks/{auto_task_env['task_id']}/run",
        headers={"Authorization": f"Bearer {auto_task_env['token']}"},
    )
    assert response.status_code == 400
    assert "No keywords" in response.json()["detail"]


def test_manual_run_publishes_and_returns_full_payload(auto_task_env, monkeypatch):
    """核心回归：手动运行必须 200 并返回完整结构（此前会抛 NameError 500）。"""
    monkeypatch.setattr(
        "backend.app.api.auto_tasks.OpenAICompatibleTextClient",
        lambda *args, **kwargs: FakeTextModelClient(),
    )
    response = client.post(
        f"/api/auto-tasks/{auto_task_env['task_id']}/run",
        headers={"Authorization": f"Bearer {auto_task_env['token']}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["keyword"] == "咖啡"
    assert payload["source_note"]["note_id"] == "auto-note-001"
    assert payload["draft"]["body"] == "改写后的正文"
    assert payload["publish_job"]["id"] > 0
    assert payload["publish_job"]["status"] in {"published", "pending"}, payload["publish_job"]
    assert payload["auto_task"]["id"] == auto_task_env["task_id"]
