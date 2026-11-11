"""SQLite 自动备份。

单容器默认用 SQLite + bind mount，此前没有任何备份手段：一次误删或磁盘
损坏就是全部内容库 + 账号配置归零。

策略：调度器每 24 小时执行一次 ``VACUUM INTO``（在线一致性快照，不锁写），
按 ``backup_keep`` 保留最近 N 份。非 SQLite 后端直接跳过（生产 MySQL
应由运维的物理/逻辑备份负责）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _backup_dir() -> Path:
    from backend.app.core.config import get_settings

    configured = (getattr(get_settings(), "backup_dir", "") or "./data/backups").strip()
    path = Path(configured)
    if not path.is_absolute():
        from backend.app.core.config import PROJECT_ROOT

        path = PROJECT_ROOT / path
    return path


def _quote_sqlite_path(path: Path) -> str:
    # VACUUM INTO 不接受绑定参数（部分版本），路径需内联并转义单引号
    return "'" + str(path).replace("'", "''") + "'"


def run_sqlite_backup_once(keep: int | None = None) -> dict[str, object]:
    """执行一次在线备份并轮转旧文件；返回执行摘要。"""
    from backend.app.core.config import get_settings
    from backend.app.core.database import engine

    settings = get_settings()
    if engine.dialect.name != "sqlite":
        return {"skipped": "not-sqlite"}
    if not getattr(settings, "backup_enabled", True):
        return {"skipped": "disabled"}

    keep = keep if keep is not None else int(getattr(settings, "backup_keep", 7) or 7)
    directory = _backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = directory / f"spider_xhs-{stamp}.db"

    try:
        with engine.connect() as conn:
            conn.execute(text(f"VACUUM INTO {_quote_sqlite_path(target)}"))
    except Exception as exc:
        logger.error("SQLite 备份失败: %s", exc)
        return {"error": str(exc)}

    removed = 0
    backups = sorted(
        (p for p in directory.glob("spider_xhs-*.db") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            continue

    size = target.stat().st_size if target.exists() else 0
    logger.info("SQLite 备份完成: %s (%s bytes), 清理 %s 份旧备份", target.name, size, removed)
    return {"file": target.name, "size": size, "removed": removed}
