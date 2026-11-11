from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession


def _db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'clip-cleanup.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_mark_and_prune_expired_sessions(tmp_path):
    from backend.app.clip.cleanup import mark_expired_clip_sessions, prune_clip_sessions

    db = _db(tmp_path)
    now = shanghai_now()
    expired = ClipSession(
        user_id=1, title="过期", manifest_json="[]", status="issued",
        handoff_jti="j1", handoff_expires_at=now - timedelta(days=10),
        created_at=now - timedelta(days=10),
    )
    kept = ClipSession(
        user_id=1, title="有导出", manifest_json="[]", status="exchanged",
        handoff_jti="j2", handoff_expires_at=now - timedelta(days=10),
        session_expires_at=now - timedelta(days=9), created_at=now - timedelta(days=10),
    )
    db.add_all([expired, kept])
    db.flush()
    db.add(ClipExport(user_id=1, session_id=kept.id, title="成片", file_name="xhs-clip-u1-a.mp4",
                      size_bytes=10, client_export_id="c1", created_at=now))
    db.commit()

    assert mark_expired_clip_sessions(db, now=now) == 2
    assert expired.status == "expired"
    assert kept.status == "expired"
    assert prune_clip_sessions(db, now=now, retention_days=7) == 1
    assert db.get(ClipSession, expired.id) is None
    assert db.get(ClipSession, kept.id) is not None
    db.close()


def test_prune_temp_files_only_old_parts(tmp_path):
    from backend.app.clip.cleanup import prune_clip_temp_files

    directory = tmp_path / "media"
    directory.mkdir()
    old = directory / ".clip-upload-old.part"
    fresh = directory / ".clip-upload-fresh.part"
    other = directory / "keep.mp4"
    for path in (old, fresh, other):
        path.write_bytes(b"x")
    now = 1_800_000_000
    old.touch()
    import os

    os.utime(old, (now - 25 * 3600, now - 25 * 3600))
    os.utime(fresh, (now - 3600, now - 3600))
    assert prune_clip_temp_files(directory, now=now, max_age_hours=24) == 1
    assert not old.exists()
    assert fresh.exists()
    assert other.exists()


def test_completed_session_expires_and_prunes(tmp_path):
    """终审建议：completed 会话按 session_expires_at 流转到 expired。"""
    from backend.app.clip.cleanup import mark_expired_clip_sessions, prune_clip_sessions

    db = _db(tmp_path)
    now = shanghai_now()
    done = ClipSession(
        user_id=1, title="已完成", manifest_json="[]", status="completed",
        handoff_jti="jc", handoff_expires_at=now - timedelta(days=10),
        session_expires_at=now - timedelta(days=9), created_at=now - timedelta(days=10),
    )
    db.add(done)
    db.commit()

    assert mark_expired_clip_sessions(db, now=now) == 1
    assert done.status == "expired"
    assert prune_clip_sessions(db, now=now, retention_days=7) == 1
    assert db.get(ClipSession, done.id) is None
    db.close()
