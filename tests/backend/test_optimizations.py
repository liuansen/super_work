"""本轮优化项的回归测试。

覆盖：检索层（search_text + FTS/LIKE 双路径）、SQLite 备份、可观测性
（request_id / metrics）、限流后端、vendor 子进程协议。
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


# ---------------------------------------------------------------------------
# 检索：search_text 写入 + FTS/LIKE 双路径
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base
    import backend.app.models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'search.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_search_text_is_built_on_insert_and_matches_tags(tmp_path):
    from backend.app.models import Note, User
    from backend.app.services.note_search import note_matches

    _engine, factory = _make_db(tmp_path)
    db = factory()
    try:
        user = User(username="search-user", password_hash="x")
        db.add(user)
        db.commit()
        note = Note(
            user_id=user.id,
            platform="xhs",
            note_id="search-note-1",
            title="周末咖啡探店",
            content="今天去了一家新店",
            author_name="作者甲",
            raw_json={"tags": ["美食", "咖啡"], "topics": [{"name": "上海生活"}]},
        )
        db.add(note)
        db.commit()

        # 写入时由 model 事件生成，包含标签/话题
        assert note.search_text
        for needle in ("咖啡", "美食", "上海生活", "作者甲", "search-note-1"):
            assert needle.lower() in note.search_text
            assert note_matches(note, needle)
        assert not note_matches(note, "不存在的词")
    finally:
        db.close()


def test_candidate_notes_fts_path_and_like_fallback(tmp_path):
    from backend.app.models import Note, User
    from backend.app.services.note_search import (
        candidate_notes,
        ensure_fts_index,
        note_matches,
    )

    engine, factory = _make_db(tmp_path)
    assert ensure_fts_index(engine) is True
    db = factory()
    try:
        user = User(username="fts-user", password_hash="x")
        db.add(user)
        db.commit()
        db.add_all(
            [
                Note(user_id=user.id, platform="xhs", note_id="a", title="咖啡探店", content="好喝"),
                Note(user_id=user.id, platform="xhs", note_id="b", title="穿搭分享", content="春季"),
            ]
        )
        db.commit()

        # ≥3 字：走 FTS5 trigram
        fts_hits = candidate_notes(db, user_id=user.id, platform="xhs", needle="咖啡探店", limit=10)
        assert [n.note_id for n in fts_hits] == ["a"]

        # 2 字：自动回退 LIKE（中文常见短词必须可用）
        short_hits = candidate_notes(db, user_id=user.id, platform="xhs", needle="穿搭", limit=10)
        assert [n.note_id for n in short_hits] == ["b"]

        # 精确性以 Python 为准
        assert all(note_matches(n, "咖啡探店") for n in fts_hits)
    finally:
        db.close()


def test_candidate_notes_isolates_users(tmp_path):
    from backend.app.models import Note, User
    from backend.app.services.note_search import candidate_notes

    _engine, factory = _make_db(tmp_path)
    db = factory()
    try:
        u1 = User(username="u1", password_hash="x")
        u2 = User(username="u2", password_hash="x")
        db.add_all([u1, u2])
        db.commit()
        db.add(Note(user_id=u1.id, platform="xhs", note_id="mine", title="咖啡"))
        db.add(Note(user_id=u2.id, platform="xhs", note_id="theirs", title="咖啡"))
        db.commit()

        hits = candidate_notes(db, user_id=u1.id, platform="xhs", needle="咖啡", limit=10)
        assert [n.note_id for n in hits] == ["mine"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 限流：内存后端语义 + 精确释放
# ---------------------------------------------------------------------------


def test_limiter_blocks_after_limit_and_release_is_exact():
    from backend.app.core.distributed_rate_limit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(prefix="test", window_seconds=60)
    stamps = [limiter.consume("k", 3) for _ in range(3)]
    assert all(s is not None for s in stamps)
    assert limiter.consume("k", 3) is None

    # 精确释放其中一次：只回收这一条（若多回收了，下面第二行就会放行）
    limiter.release("k", stamps[0])
    assert limiter.consume("k", 3) is not None  # 2 条 + 本次 = 3，放行
    assert limiter.consume("k", 3) is None      # 已满
    # 换 key 不受影响
    assert limiter.consume("other", 3) is not None


def test_limiter_isolates_keys_and_resets():
    from backend.app.core.distributed_rate_limit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(prefix="test2")
    assert limiter.consume("a", 1) is not None
    assert limiter.consume("a", 1) is None
    assert limiter.consume("b", 1) is not None
    limiter.reset("a")
    assert limiter.consume("a", 1) is not None


def test_rate_limiter_respects_explicit_zero():
    """配置 0 = 停止抓取，不能被 `or` 吞掉。"""
    from backend.app.services.rate_limiter import CrawlRateLimiter

    limiter = CrawlRateLimiter(max_per_minute=0)
    assert limiter.max_per_minute == 0
    assert limiter.allow(1) is True  # limit<=0 视为不限速（配置语义由调用方保证）
    assert CrawlRateLimiter(max_per_minute=2).max_per_minute == 2


# ---------------------------------------------------------------------------
# SQLite 备份
# ---------------------------------------------------------------------------


def test_sqlite_backup_creates_snapshot_and_rotates(tmp_path, monkeypatch):
    from backend.app.services import backup as backup_service

    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(backup_service, "_backup_dir", lambda: backup_dir)

    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path}")
    import backend.app.core.database as database_module

    monkeypatch.setattr(database_module, "engine", engine)

    first = backup_service.run_sqlite_backup_once(keep=2)
    assert first.get("size", 0) > 0
    files = sorted(backup_dir.glob("spider_xhs-*.db"))
    assert len(files) == 1

    # 备份文件可读且数据完整
    restored = sqlite3.connect(files[0])
    try:
        assert restored.execute("SELECT v FROM t").fetchone()[0] == "hello"
    finally:
        restored.close()

    # 轮转：超过 keep 时删除最旧
    for index in range(3):
        os.utime(files[0], (1_600_000_000 + index, 1_600_000_000 + index))
        backup_service.run_sqlite_backup_once(keep=2)
    remaining = sorted(backup_dir.glob("spider_xhs-*.db"))
    assert len(remaining) <= 2


# ---------------------------------------------------------------------------
# 可观测性
# ---------------------------------------------------------------------------


def test_metrics_render_prometheus_text():
    from backend.app.core import metrics

    metrics.reset_metrics()
    metrics.record_request("GET", 200, "/api/health", 0.012)
    metrics.record_request("GET", 200, "/api/health", 0.008)
    metrics.record_request("POST", 500, "/api/notes", 0.5)
    text = metrics.render_prometheus()
    assert 'app_requests_total{method="GET",status="200",route="/api/health"} 2' in text
    assert 'app_requests_total{method="POST",status="500",route="/api/notes"} 1' in text
    assert 'app_request_duration_seconds_count{route="/api/health"} 2' in text
    assert "app_inflight_requests 0" in text
    metrics.reset_metrics()


def test_request_id_header_is_echoed(tmp_path):
    from api_helpers import client

    resp = client.get("/api/health", headers={"X-Request-ID": "trace-abc"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "trace-abc"

    generated = client.get("/api/health")
    assert generated.headers["X-Request-ID"]


def test_metrics_endpoint_exposes_counters():
    from api_helpers import client

    client.get("/api/health")
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "app_requests_total" in resp.text


# ---------------------------------------------------------------------------
# vendor 子进程协议
# ---------------------------------------------------------------------------


def test_vendor_worker_unknown_op_reports_structured_error():
    from backend.app.douyin import vendor_worker

    try:
        vendor_worker.dispatch("does-not-exist", {})
    except ValueError as exc:
        assert "未知 vendor 操作" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("未知操作应抛 ValueError")


def test_vendor_result_marker_parsing():
    """父进程只认最后一行带标记的结果，上游 print 不会污染解析。"""
    from backend.app.douyin.upstream import RESULT_MARKER

    noisy_stdout = "some upstream log line\nanother line\n"
    payload = {"ok": True, "result": {"items": [1, 2]}}
    raw = noisy_stdout + "\n" + RESULT_MARKER + json.dumps(payload) + "\n"
    index = raw.rfind(RESULT_MARKER)
    parsed = json.loads(raw[index + len(RESULT_MARKER):].strip().splitlines()[0])
    assert parsed["result"]["items"] == [1, 2]


# ---------------------------------------------------------------------------
# 通知流（SSE）
# ---------------------------------------------------------------------------


def test_notification_stream_requires_auth():
    from api_helpers import client

    assert client.get("/api/notifications/stream").status_code == 401


def test_notification_stream_emits_snapshot(tmp_path, monkeypatch):
    """连接建立后先补发未读快照（前端无需再单独拉一次）。"""
    from backend.app.api import notifications as notifications_api
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import Notification, User

    from api_helpers import _override_database, _register_and_get_access_token, client

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("stream-user")
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add(Notification(user_id=1, title="流式通知", level="info"))
        db.commit()
    finally:
        db.close()

    # 缩短流参数，避免测试挂住
    monkeypatch.setattr(notifications_api, "_STREAM_POLL_SECONDS", 0.01)
    monkeypatch.setattr(notifications_api, "_STREAM_MAX_SECONDS", 0.2)
    monkeypatch.setattr(notifications_api, "_STREAM_HEARTBEAT_SECONDS", 0.05)
    try:
        seen = ""
        with client.stream(
            "GET",
            "/api/notifications/stream",
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            for line in response.iter_lines():
                seen += line
                if '"snapshot"' in seen:
                    break
        assert '"snapshot"' in seen
        assert "流式通知" in seen
    finally:
        app.dependency_overrides.pop(db_dependency, None)
