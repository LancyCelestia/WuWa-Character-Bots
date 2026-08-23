"""缓存策略测试：只删目标目录内文件，按配额与保鲜期清理。"""

import time
from pathlib import Path

from plugins.bot_unified_runtime.runtime.cache_policy import enforce_quota


def test_quota_removes_oldest_inside_directory_only(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "old.txt").write_text("a" * 200)
    old_stat = (cache / "old.txt").stat()
    os_utime = __import__("os").utime
    os_utime(cache / "old.txt", (time.time() - 99999, time.time() - 99999))
    (cache / "new.txt").write_text("b" * 100)

    outside = tmp_path / "outside.txt"
    outside.write_text("keep" * 100)

    result = enforce_quota(cache, max_bytes=150, max_age_days=0)
    assert not (cache / "old.txt").exists()
    assert (cache / "new.txt").exists()
    assert outside.exists()
    assert result["files_removed"] == 1


def test_age_limit_removes_expired_files(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    path = cache / "stale.txt"
    path.write_text("x" * 50)
    __import__("os").utime(path, (time.time() - 10 * 86400, time.time() - 10 * 86400))
    enforce_quota(cache, max_bytes=0, max_age_days=7)
    assert not path.exists()


def test_nonexistent_directory_is_safe(tmp_path):
    result = enforce_quota(tmp_path / "missing", max_bytes=100)
    assert result["files_removed"] == 0
