"""磁盘缓存策略：下载/卡片/表情都受配额与保鲜期约束，防止挤占硬盘。

原则：
- 每个目录有总字节上限（LRU：最旧先删）与最大保留天数；
- 每次落盘后立即执行一次清理，不会越积越多；
- 删除只发生在明确配置的缓存目录内，绝不递归删除目录本身；
- 失败静默降级，不影响下载/渲染主链路。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def enforce_quota(
    directory: str | Path,
    *,
    max_bytes: int = 0,
    max_age_days: int = 0,
) -> dict[str, Any]:
    """按“最旧优先”清理目录至配额内；max_bytes<=0 表示不限制总量。"""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return {"directory": str(root), "files_removed": 0, "bytes_removed": 0}
    files: list[tuple[int, int, Path]] = []
    try:
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append((int(stat.st_mtime), int(stat.st_size), path))
    except OSError:
        return {"directory": str(root), "files_removed": 0, "bytes_removed": 0}

    now = time.time()
    removed = 0
    bytes_removed = 0
    total = sum(item[1] for item in files)

    def drop(path: Path, size: int) -> None:
        nonlocal removed, bytes_removed
        try:
            path.unlink(missing_ok=True)
            removed += 1
            bytes_removed += size
        except OSError:
            return

    if max_age_days > 0:
        for mtime, size, path in files:
            if now - mtime > max_age_days * 86400:
                drop(path, size)
    if max_bytes > 0:
        remaining = total - bytes_removed
        for mtime, size, path in sorted(
            [item for item in files if item[2].exists()], key=lambda item: item[0]
        ):
            if remaining <= max_bytes:
                break
            drop(path, size)
            remaining -= size
    return {
        "directory": str(root),
        "files_removed": removed,
        "bytes_removed": bytes_removed,
    }
