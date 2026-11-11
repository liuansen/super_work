"""媒体目录生命周期治理。

下载/上传的素材（``xhs-image-`` / ``xhs-asset-`` / ``xhs-upload-``）此前
没有任何清理路径，磁盘只增不减。这里提供按年龄 + 容量的清理函数，
由调度器定期执行。

安全约束：只处理形如 ``xhs-<kind>-u<数字>-`` 的文件，绝不删除用户手动
放进 media 目录的其它文件。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 默认保留策略
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB

# 成片（xhs-clip-u）是用户显式管理的资产，只通过剪辑工坊删除，
# 不参与按年龄/容量自动清理；加入 _PREFIXES 会导致成片被误删。
_PREFIXES = ("xhs-image-u", "xhs-asset-u", "xhs-upload-u")


def _is_managed_media(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name
    if not name.startswith(_PREFIXES):
        return False
    # 前缀后必须紧跟数字用户 id 与分隔符，避免误删形似文件
    rest = name.split("-", 2)
    if len(rest) < 3:
        return False
    owner = rest[2]
    user_id, _, _tail = owner.partition("-")
    return user_id.startswith("u") and user_id[1:].isdigit()


def prune_media_dir(
    media_dir: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    now: float | None = None,
) -> dict[str, int]:
    """按年龄与总容量清理媒体目录，返回 {"removed": n, "freed_bytes": n}。"""
    if not media_dir.is_dir():
        return {"removed": 0, "freed_bytes": 0}

    current = now if now is not None else time.time()
    cutoff = current - max_age_days * 86400
    removed = 0
    freed = 0
    survivors: list[tuple[float, int, Path]] = []

    for path in media_dir.iterdir():
        if not _is_managed_media(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            try:
                path.unlink()
                removed += 1
                freed += stat.st_size
            except OSError:
                continue
        else:
            survivors.append((stat.st_mtime, stat.st_size, path))

    total = sum(size for _, size, _ in survivors)
    if total > max_total_bytes:
        # 从最旧的开始删，直到降到配额以内
        for _mtime, size, path in sorted(survivors):
            if total <= max_total_bytes:
                break
            try:
                path.unlink()
                removed += 1
                freed += size
                total -= size
            except OSError:
                continue

    if removed:
        logger.info("媒体清理完成：删除 %s 个文件，释放 %s 字节", removed, freed)
    return {"removed": removed, "freed_bytes": freed}


def run_media_prune_once(media_dir: Path | None = None) -> dict[str, int]:
    """调度器入口：清理配置的 storage/media 目录。"""
    if media_dir is None:
        from backend.app.core.media_storage import media_dir as resolve_media_dir

        media_dir = resolve_media_dir()
    return prune_media_dir(media_dir)
