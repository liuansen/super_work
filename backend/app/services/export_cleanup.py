"""导出文件清理。

每次导出都会在 storage/exports 下新建一个文件，此前没有任何清理，
磁盘只增不减。策略：每个用户每类导出（notes / report）保留最近 N 个，
更早的文件在写新文件时删除。
"""
from __future__ import annotations

from pathlib import Path

# 每用户每类导出保留的文件数
KEEP_PER_USER = 10


def prune_user_exports(export_dir: Path, user_id: int, kind: str, keep: int = KEEP_PER_USER) -> int:
    """删除该用户该类导出中除最近 keep 个之外的文件，返回删除数量。"""
    if not export_dir.is_dir():
        return 0
    prefix = f"xhs-{kind}-u{user_id}-"
    files = sorted(
        (p for p in export_dir.iterdir() if p.is_file() and p.name.startswith(prefix)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for stale in files[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            continue
    return removed
