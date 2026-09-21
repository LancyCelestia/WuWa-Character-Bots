"""2026-09-21 深读波 D1 小面修复回归锁（配额记账 / 落盘留痕 / 死分支）。

三条各是一行级修法，但都属于「失败路径把真实状态洗成成功」这一族，逐条上锁：

- **D1-3 `runtime/cache_policy.py`**：LRU 清理里 ``drop()`` 内部 ``except OSError:
  return``（删除失败静默、不加 ``bytes_removed``），调用方却紧接无条件
  ``remaining -= size`` ⇒ 文件被占用（Windows 锁/只读）时账面上「已腾出」，
  提前 ``break``，目录**实际超配额却判为达标**，且零告警。
- **D1-10 `runtime/settings.py::_save`**：``except OSError: return`` 连一行日志都不打，
  而内存态与监听通知在落盘**之前**已完成 ⇒ 管理员 ``/bot runtime set`` 看到「成功」、
  当轮即时生效，重启后该覆盖静默丢失。同文件读侧损坏路径是 warning + ``*.corrupt``
  保全，持久化失败反而比读损坏更隐身。
- **D1-11 `runtime/settings.py::_load`**：``if not isinstance(payload, dict)`` 出现两次，
  第二次被第一次完全遮蔽＝不可达残骸；若有人日后误删第一块，第二块会变成
  「静默吞掉非对象设置文件、既不保全现场也不告警」的降级路径。删除后行为必须不变。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.runtime import cache_policy
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    settings as settings_mod,
)

# ---------------------------------------------------------------------------
# D1-3
# ---------------------------------------------------------------------------


def _make_files(root: Path, sizes: dict[str, int]) -> None:
    """按名字顺序造文件并钉死 mtime 递增（LRU＝最旧先删）。"""
    now = time.time()
    total = len(sizes)
    for index, (name, size) in enumerate(sizes.items()):
        path = root / name
        path.write_bytes(b"x" * size)
        stamp = now - (total - index) * 100
        os.utime(path, (stamp, stamp))


def test_failed_delete_is_not_counted_toward_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "cache"
    root.mkdir()
    _make_files(root, {"oldest": 100, "middle": 100, "newest": 100})

    real_unlink = Path.unlink

    def flaky_unlink(self: Path, **kwargs: object) -> None:
        if self.name == "oldest":
            raise OSError("simulated Windows file lock")
        real_unlink(self, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    result = cache_policy.enforce_quota(root, max_bytes=100)

    # 修前：oldest 删失败仍扣账 → remaining=200→删 middle→100 → break，
    # newest 留下、盘上实剩 oldest+newest=200B，却对外报「已进配额」。
    assert result["files_removed"] == 2, result
    assert result["bytes_removed"] == 200, result
    assert (root / "oldest").exists(), "删不掉的 oldest 理应仍在"
    assert not (root / "middle").exists() and not (root / "newest").exists()
    on_disk = sum(path.stat().st_size for path in root.iterdir())
    assert on_disk == 100, f"目录实际 {on_disk}B 却报达标＝本锁要拦的假绿"


# ---------------------------------------------------------------------------
# D1-10
# ---------------------------------------------------------------------------


def test_persist_failure_is_logged_and_not_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    path = tmp_path / "runtime_settings.json"
    store = settings_mod.RuntimeSettingsStore(path)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(settings_mod.os, "replace", boom)

    with caplog.at_level("ERROR"):
        assert store.set_override("BOT_VISION_MODE", "direct") is not None

    messages = [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]
    assert any("failed to persist" in message for message in messages), messages
    assert any("LOST on restart" in message for message in messages), (
        "日志必须把『重启即失效』说破，运维才看得懂后果"
    )


def test_successful_save_still_leaves_no_error_log(tmp_path: Path, caplog) -> None:
    path = tmp_path / "runtime_settings.json"
    store = settings_mod.RuntimeSettingsStore(path)
    with caplog.at_level("ERROR"):
        store.set_override("BOT_VISION_MODE", "direct")
    assert not [r for r in caplog.records if r.levelname == "ERROR"], "正常落盘不得误报"
    assert json.loads(path.read_text(encoding="utf-8"))["overrides"]["BOT_VISION_MODE"]


# ---------------------------------------------------------------------------
# D1-11：删掉不可达分支后，「非对象设置文件」仍走保全 + 告警
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [[1, 2, 3], "plain string", 42, None])
def test_non_object_settings_file_is_quarantined(
    tmp_path: Path, payload: object, caplog
) -> None:
    path = tmp_path / "runtime_settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with caplog.at_level("WARNING"):
        store = settings_mod.RuntimeSettingsStore(path)

    assert store.list_overrides() == {}
    assert not path.exists(), "非对象设置文件必须被移走（*.corrupt 保全），不得原地静默读空"
    assert list(tmp_path.glob("runtime_settings.json.corrupt*")), list(tmp_path.iterdir())
    assert any("not a JSON object" in record.getMessage() for record in caplog.records), [
        record.getMessage() for record in caplog.records
    ]
