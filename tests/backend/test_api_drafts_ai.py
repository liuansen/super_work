"""草稿、模型配置与 AI 改写 / 文本 / 图片路由测试。

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

def test_drafts_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/drafts",
            json={"platform": "xhs", "title": "草稿标题", "body": "草稿正文"},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_drafts_api_creates_from_owned_note_and_lists_current_user_only(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-owner")
    intruder_token = _register_and_get_access_token("draft-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "draft-source-note",
                        "title": "源笔记标题",
                        "content": "源笔记正文",
                        "author_name": "源作者",
                        "raw": {"source": "draft"},
                    }
                ],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]

        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id, "intent": "rewrite"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["platform"] == "xhs"
        assert created["title"] == "源笔记标题"
        assert created["body"] == "源笔记正文"
        assert created["source_note_id"] == source_note_id

        owner_list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["id"] == created["id"]

        intruder_list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        db = next(app.dependency_overrides[get_db]())
        try:
            draft = db.query(AiDraft).one()
            assert draft.source_note_id == source_note_id
            assert draft.title == "源笔记标题"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_drafts_api_rejects_cross_user_source_note(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-source-owner")
    intruder_token = _register_and_get_access_token("draft-source-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "foreign-source", "title": " чужая", "content": "nope"}],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]

        response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id, "intent": "publish"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_drafts_update_persists_owned_changes_and_rejects_cross_user(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "draft-update-owner")
    intruder_token = _register_and_get_access_token("draft-update-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "update-source", "title": "旧标题", "content": "旧正文"}],
            },
        )
        source_note_id = save_response.json()["items"][0]["id"]
        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "source_note_id": source_note_id},
        )
        draft_id = create_response.json()["id"]

        update_response = client.patch(
            f"/api/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "新标题", "body": "新正文"},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "新标题"
        assert updated["body"] == "新正文"

        list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        listed = list_response.json()["items"][0]
        assert listed["id"] == draft_id
        assert listed["title"] == "新标题"
        assert listed["body"] == "新正文"

        intruder_response = client.patch(
            f"/api/drafts/{draft_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"title": "攻击标题", "body": "攻击正文"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_model_configs_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/model-configs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_model_configs_create_list_filter_and_encrypt_api_key(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import ModelConfig

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-owner")
    intruder_token = _register_and_get_access_token("model-intruder")
    try:
        create_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "OpenAI Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-secret-text",
                "is_default": True,
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "OpenAI Text"
        assert created["model_type"] == "text"
        assert created["model_name"] == "gpt-test"
        assert created["has_api_key"] is True
        assert "api_key" not in created
        assert "encrypted_api_key" not in created

        image_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Image Model",
                "model_type": "image",
                "provider": "openai-compatible",
                "model_name": "image-test",
                "base_url": "",
                "api_key": "",
                "is_default": False,
            },
        )
        assert image_response.status_code == 200

        owner_list_response = client.get(
            "/api/model-configs?model_type=text",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["id"] == created["id"]
        assert owner_payload["items"][0]["model_type"] == "text"

        intruder_list_response = client.get(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        db = next(app.dependency_overrides[get_db]())
        try:
            config = db.query(ModelConfig).filter(ModelConfig.name == "OpenAI Text").one()
            assert config.encrypted_api_key != "sk-secret-text"
            assert decrypt_text(config.encrypted_api_key) == "sk-secret-text"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_text_model_config_defaults_to_gpt_54_when_model_name_omitted(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-default-owner")
    try:
        response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-default",
                "is_default": True,
            },
        )

        assert response.status_code == 200
        assert response.json()["model_name"] == "gpt-5.4"
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_model_configs_update_and_set_default_are_owner_scoped(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("model-update-owner")
    intruder_token = _register_and_get_access_token("model-update-intruder")
    try:
        first_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Text One",
                "model_type": "text",
                "provider": "provider-a",
                "model_name": "model-a",
                "base_url": "https://a.example.test",
                "api_key": "secret-a",
                "is_default": True,
            },
        )
        second_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Text Two",
                "model_type": "text",
                "provider": "provider-b",
                "model_name": "model-b",
                "base_url": "https://b.example.test",
                "api_key": "secret-b",
                "is_default": False,
            },
        )
        first_id = first_response.json()["id"]
        second_id = second_response.json()["id"]

        update_response = client.patch(
            f"/api/model-configs/{second_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Text Two Updated", "api_key": "secret-b2"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Text Two Updated"
        assert update_response.json()["has_api_key"] is True

        intruder_update_response = client.patch(
            f"/api/model-configs/{second_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "stolen"},
        )
        assert intruder_update_response.status_code == 404

        default_response = client.post(
            f"/api/model-configs/{second_id}/set-default",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert default_response.status_code == 200
        assert default_response.json()["is_default"] is True

        list_response = client.get(
            "/api/model-configs?model_type=text",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        listed = {item["id"]: item for item in list_response.json()["items"]}
        assert listed[first_id]["is_default"] is False
        assert listed[second_id]["is_default"] is True

        intruder_default_response = client.post(
            f"/api/model-configs/{second_id}/set-default",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_default_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_rewrite_note_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/rewrite-note", json={"draft_id": 1})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_rewrite_note_requires_owned_draft_and_default_text_model(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-rewrite-owner")
    intruder_token = _register_and_get_access_token("ai-rewrite-intruder")
    try:
        create_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Original title", "body": "Original body"},
        )
        draft_id = create_response.json()["id"]

        no_model_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"draft_id": draft_id},
        )
        assert no_model_response.status_code == 400
        assert "Default text model" in no_model_response.json()["detail"]

        intruder_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"draft_id": draft_id},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_rewrite_note_uses_default_text_model_and_updates_owned_draft(tmp_path):
    from backend.app.api.ai import get_text_ai_client

    class FakeTextAiClient:
        def __init__(self):
            self.calls = []

        def rewrite_note(self, *, model_config, api_key, title, body, instruction):
            self.calls.append(
                {
                    "model_name": model_config.model_name,
                    "api_key": api_key,
                    "title": title,
                    "body": body,
                    "instruction": instruction,
                }
            )
            return f"改写结果：{title} / {instruction}"

    fake_client = FakeTextAiClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-rewrite-success")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: fake_client

        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-rewrite-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-rewrite-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "爆款标题", "body": "原始正文"},
        )
        draft_id = draft_response.json()["id"]

        rewrite_response = client.post(
            "/api/ai/rewrite-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"draft_id": draft_id, "instruction": "更适合小红书种草"},
        )
        assert rewrite_response.status_code == 200
        rewritten = rewrite_response.json()
        assert rewritten["id"] == draft_id
        assert rewritten["body"] == "改写结果：爆款标题 / 更适合小红书种草"
        assert fake_client.calls == [
            {
                "model_name": "gpt-rewrite-test",
                "api_key": "sk-rewrite-secret",
                "title": "爆款标题",
                "body": "原始正文",
                "instruction": "更适合小红书种草",
            }
        ]

        list_response = client.get(
            "/api/drafts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.json()["items"][0]["body"] == "改写结果：爆款标题 / 更适合小红书种草"

        tasks_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tasks_response.status_code == 200
        task_payload = tasks_response.json()
        assert task_payload["total"] == 1
        task = task_payload["items"][0]
        assert task["task_type"] == "ai_rewrite"
        assert task["status"] == "completed"
        assert task["progress"] == 100
        assert task["payload"]["draft_id"] == draft_id
        assert task["payload"]["model_config_id"] == model_response.json()["id"]
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_text_generation_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/generate-note", json={"topic": "低卡早餐"})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_text_generation_endpoints_use_default_model_and_create_tasks(tmp_path):
    from backend.app.api.ai import get_text_ai_client

    class FakeTextGenerationClient:
        def __init__(self):
            self.calls = []

        def rewrite_note(self, *, model_config, api_key, title, body, instruction):
            raise AssertionError("rewrite_note should not be called")

        def generate_note(self, *, model_config, api_key, topic, reference, instruction):
            self.calls.append(("generate_note", model_config.model_name, api_key, topic, reference, instruction))
            return {"title": f"{topic} 标题", "body": f"{topic} 正文 {reference} {instruction}".strip()}

        def generate_titles(self, *, model_config, api_key, title, body, count):
            self.calls.append(("generate_titles", model_config.model_name, api_key, title, body, count))
            return ["标题 A", "标题 B"][:count]

        def generate_tags(self, *, model_config, api_key, title, body, count):
            self.calls.append(("generate_tags", model_config.model_name, api_key, title, body, count))
            return ["低卡", "早餐", "通勤"][:count]

        def polish_text(self, *, model_config, api_key, text, instruction):
            self.calls.append(("polish_text", model_config.model_name, api_key, text, instruction))
            return f"润色：{text} / {instruction}"

    fake_client = FakeTextGenerationClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-generate-owner")
    try:
        app.dependency_overrides[get_text_ai_client] = lambda: fake_client
        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Text",
                "model_type": "text",
                "provider": "openai-compatible",
                "model_name": "gpt-generate-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-generate-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        generate_response = client.post(
            "/api/ai/generate-note",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "topic": "低卡早餐", "reference": "参考笔记", "instruction": "更具体"},
        )
        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["title"] == "低卡早餐 标题"
        assert generated["body"] == "低卡早餐 正文 参考笔记 更具体"

        titles_response = client.post(
            "/api/ai/generate-title",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "旧标题", "body": "正文", "count": 2},
        )
        assert titles_response.status_code == 200
        assert titles_response.json()["items"] == ["标题 A", "标题 B"]

        tags_response = client.post(
            "/api/ai/generate-tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "早餐", "body": "低卡早餐正文", "count": 3},
        )
        assert tags_response.status_code == 200
        assert tags_response.json()["items"] == ["低卡", "早餐", "通勤"]

        polish_response = client.post(
            "/api/ai/polish-text",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"text": "原文", "instruction": "更自然"},
        )
        assert polish_response.status_code == 200
        assert polish_response.json()["text"] == "润色：原文 / 更自然"

        tasks_response = client.get("/api/tasks?platform=xhs", headers={"Authorization": f"Bearer {owner_token}"})
        assert tasks_response.status_code == 200
        task_types = [item["task_type"] for item in tasks_response.json()["items"]]
        assert task_types == ["ai_polish_text", "ai_generate_tags", "ai_generate_title", "ai_generate_note"]
        assert fake_client.calls[0] == (
            "generate_note",
            "gpt-generate-test",
            "sk-generate-secret",
            "低卡早餐",
            "参考笔记",
            "更具体",
        )
    finally:
        app.dependency_overrides.pop(get_text_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_image_routes_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/ai/images/generate-cover", json={"prompt": "低卡早餐封面"})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_image_routes_use_default_model_store_assets_and_enforce_scope(tmp_path):
    from backend.app.api.ai import get_image_ai_client

    class FakeImageAiClient:
        def __init__(self):
            self.calls = []

        def generate_cover(self, *, model_config, api_key, prompt, size, style):
            self.calls.append(("generate_cover", model_config.model_name, api_key, prompt, size, style))
            return {"url": "https://cdn.example.test/cover.png", "raw": {"seed": 1}}

        def describe_image(self, *, model_config, api_key, image_url, instruction):
            self.calls.append(("describe_image", model_config.model_name, api_key, image_url, instruction))
            return "这是一张低卡早餐封面"

    fake_client = FakeImageAiClient()
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("ai-image-owner")
    intruder_token = _register_and_get_access_token("ai-image-intruder")
    try:
        app.dependency_overrides[get_image_ai_client] = lambda: fake_client
        model_response = client.post(
            "/api/model-configs",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "name": "Default Image",
                "model_type": "image",
                "provider": "openai-compatible",
                "model_name": "image-generate-test",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-image-secret",
                "is_default": True,
            },
        )
        assert model_response.status_code == 200

        generate_response = client.post(
            "/api/ai/images/generate-cover",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"prompt": "低卡早餐封面", "size": "1024x1024", "style": "clean"},
        )
        assert generate_response.status_code == 200
        generated = generate_response.json()
        assert generated["file_path"] == "https://cdn.example.test/cover.png"
        assert generated["prompt"] == "低卡早餐封面"
        assert generated["model_name"] == "image-generate-test"

        list_response = client.get("/api/ai/images/assets", headers={"Authorization": f"Bearer {owner_token}"})
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == generated["id"]

        intruder_list_response = client.get("/api/ai/images/assets", headers={"Authorization": f"Bearer {intruder_token}"})
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        describe_response = client.post(
            "/api/ai/images/describe",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"image_url": generated["file_path"], "instruction": "描述卖点"},
        )
        assert describe_response.status_code == 200
        assert describe_response.json()["text"] == "这是一张低卡早餐封面"

        tasks_response = client.get("/api/tasks?platform=xhs", headers={"Authorization": f"Bearer {owner_token}"})
        assert tasks_response.status_code == 200
        task_types = [item["task_type"] for item in tasks_response.json()["items"]]
        assert task_types == ["ai_image_describe", "ai_image_generate_cover"]
        assert fake_client.calls == [
            ("generate_cover", "image-generate-test", "sk-image-secret", "低卡早餐封面", "1024x1024", "clean"),
            ("describe_image", "image-generate-test", "sk-image-secret", "https://cdn.example.test/cover.png", "描述卖点"),
        ]
    finally:
        app.dependency_overrides.pop(get_image_ai_client, None)
        app.dependency_overrides.pop(db_dependency, None)
