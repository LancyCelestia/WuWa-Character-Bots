"""S-FIX-NOTES-QUOTA（2026-09-27）——笔记图片两条护栏的对抗锁（票 T6-5）。

对着 SEAT-ATK-NOTES 审计报告 T6-5 的两条实锤下锁（全离线、tmp 夹具，不触网）：

- 腿①（聚合配额）：``_save_note_images`` 落盘前按**会话总量**现算闸
  （张数 ``_MAX_SESSION_IMAGE_FILES`` / 字节 ``_MAX_SESSION_IMAGE_BYTES``，
  每消息限额之上）。触顶=诚实拒绝：本单新图全回滚、笔记整条不记、
  回人话短句——不静默丢图谎称记好；没图要落盘时闸不碍文字笔记。
- 腿②（路径域门）：``_read_local_image`` 读本地段前问唯一真身
  ``safety_exec.paths.check_sendable``，fail-closed——只认 ``allowed``，
  域外/禁触名册（允许根内的 ``.env`` 也拦）/判定失灵一律拒读，
  拒读只回 None 不落判定细节。

策略注入走 ``paths._default_policy`` 假根（monkeypatch 自动复位），
测试绝不依赖真实仓库/运行数据目录。
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from types import SimpleNamespace

import plugins.bot_unified_runtime.domains.notes.capabilities.notes as notes_mod
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.core.safety_exec import paths as safety_paths
from plugins.bot_unified_runtime.domains.notes.capabilities.notes import (
    build_notes_capability,
)
from plugins.bot_unified_runtime.domains.notes.store import (
    notes_store as notes_store_mod,
)
from plugins.bot_unified_runtime.domains.notes.store.notes_store import (
    reset_stores_for_tests,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_notes_db_path=str(tmp_path / "n.sqlite3"),
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
    )


def _message(text: str, *, segments: list | None = None) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id="group:1", session_type=SessionType.GROUP, sender_id="u1",
        group_id="1", plain_text=text, message_id="m1",
        raw_segments=segments or [],
    )


def _image_file(base: Path, name: str, size: int) -> Path:
    """造一枚过魔数检查的假图（总字节 = size，PNG 头打头）。"""
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    payload = PNG_MAGIC + b"x" * max(0, size - len(PNG_MAGIC))
    path.write_bytes(payload)
    return path


def _chat_dir(tmp_path, session_id: str = "group:1") -> Path:
    return tmp_path / "imgs" / sha1(session_id.encode()).hexdigest()[:12]


def _setup(tmp_path, monkeypatch, *, readable_root: Path | None = None) -> Path:
    """图片根指到 tmp；并把 readable_root（默认 tmp_path 全体）登记为允许根。

    路径域门（T6-5 腿②）上线后，本地段读取须落在允许根内；假根策略经
    ``paths._default_policy`` 注入口给，monkeypatch 自动复位不泄漏。
    """
    reset_stores_for_tests()
    monkeypatch.setattr(notes_mod, "_images_root", lambda _config: tmp_path / "imgs")
    monkeypatch.setattr(
        safety_paths,
        "_default_policy",
        safety_paths.build_policy(workspace_root=readable_root or tmp_path),
    )
    return tmp_path


def _image_segment(path: Path) -> dict:
    return {"type": "image", "data": {"file": str(path), "url": ""}}


# ---------- 腿②：本地读路径域门（fail-closed） ----------

def test_local_read_allowed_inside_registered_root(tmp_path, monkeypatch) -> None:
    """正例：允许根内的正常图片文件照读照存——闸门不是把所有读都焊死。"""
    _setup(tmp_path, monkeypatch)
    source = _image_file(tmp_path / "raws", "ok.png", 2048)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 看图", segments=[_image_segment(source)]), object()
    )
    assert "记下了" in result.body and "附图 1 张" in result.body
    assert len(list(_chat_dir(tmp_path).iterdir())) == 1


def test_local_read_denied_outside_allowed_roots(tmp_path, monkeypatch) -> None:
    """负例：允许根外的本地段路径拒读——笔记仍记、图不收、零字节外泄。"""
    allowed = tmp_path / "allowed"
    _setup(tmp_path, monkeypatch, readable_root=allowed)
    leak = _image_file(tmp_path / "outside_secret", "leak.png", 2048)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 看这张图", segments=[_image_segment(leak)]), object()
    )
    assert "记下了" in result.body and "附图" not in result.body
    # 域外文件一个字节都没被复制进会话目录（目录应为空或不存在）。
    chat_dir = _chat_dir(tmp_path)
    assert not chat_dir.exists() or list(chat_dir.iterdir()) == []


def test_local_read_denied_for_forbidden_roster_inside_root(tmp_path, monkeypatch) -> None:
    """负例：禁触名册压在最外一层——允许根内的 .env（哪怕伪装 PNG 魔数）也拒读。"""
    _setup(tmp_path, monkeypatch)
    decoy = _image_file(tmp_path / "keys", "app.env", 2048)  # .env 在禁触后缀名册。
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 看这张图", segments=[_image_segment(decoy)]), object()
    )
    assert "附图" not in result.body
    chat_dir = _chat_dir(tmp_path)
    assert not chat_dir.exists() or list(chat_dir.iterdir()) == []


def test_local_read_gate_fail_closed_on_policy_blindness(tmp_path, monkeypatch) -> None:
    """负例：判定件失灵（根解析不出等）按拒读收——fail-closed 不猜。

    构造：策略无任何登记根（build_policy 空根）→ 一切落点判 denied/undetermined
    ⇒ 连允许位置的文件也不读。锁死「判定挂了就当没事发生」的回潮形态。
    """
    reset_stores_for_tests()
    monkeypatch.setattr(notes_mod, "_images_root", lambda _config: tmp_path / "imgs")
    monkeypatch.setattr(
        safety_paths, "_default_policy", safety_paths.build_policy()
    )
    source = _image_file(tmp_path / "raws", "ok.png", 2048)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 看图", segments=[_image_segment(source)]), object()
    )
    assert "附图" not in result.body


# ---------- 腿①：会话聚合配额（张数/字节，触顶诚实拒绝+回滚） ----------

def test_session_file_count_quota_refuses_honestly(tmp_path, monkeypatch) -> None:
    """张数触顶：拒整条带图笔记（不记、不留图），回话点名上限与出路。"""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_FILES", 2)
    chat_dir = _chat_dir(tmp_path)
    chat_dir.mkdir(parents=True)
    for i in range(2):
        (chat_dir / f"old{i}.png").write_bytes(PNG_MAGIC + b"0" * 64)
    source = _image_file(tmp_path / "raws", "new.png", 2048)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 再来一张", segments=[_image_segment(source)]), object()
    )
    assert "存满了" in result.body and "这条先没记上" in result.body
    assert "记下了" not in result.body, "拒绝必须真拒绝：不许记半条"
    assert "2" in result.body  # 上限数字与常量同源出现在回话里。
    store = notes_store_mod.build_notes_store(_config(tmp_path))
    assert store.list_notes("group:1") == [], "被拒笔记不得入库"
    assert len(list(chat_dir.iterdir())) == 2, "旧图一张不许动"


def test_session_bytes_quota_blocks_partial_batch_and_rolls_back(
    tmp_path, monkeypatch
) -> None:
    """字节触顶发生在本单中途：先前已写的图整单回滚，磁盘不留残件。"""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_FILES", 100)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_BYTES", 60)
    first = _image_file(tmp_path / "raws", "a.png", 40)
    second = _image_file(tmp_path / "raws", "b.png", 40)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message(
            "笔记 记 两张一起",
            segments=[_image_segment(first), _image_segment(second)],
        ),
        object(),
    )
    assert "存满了" in result.body and "这条先没记上" in result.body
    chat_dir = _chat_dir(tmp_path)
    assert not chat_dir.exists() or list(chat_dir.iterdir()) == [], "回滚不留孤儿文件"


def test_quota_under_limit_still_saves(tmp_path, monkeypatch) -> None:
    """正例：限额之内照常落盘入库（配额闸不把好用的路堵死）。"""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_FILES", 3)
    source = _image_file(tmp_path / "raws", "ok.png", 2048)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(
        _message("笔记 记 一张就好", segments=[_image_segment(source)]), object()
    )
    assert "记下了" in result.body and "附图 1 张" in result.body


def test_quota_never_blocks_text_only_notes(tmp_path, monkeypatch) -> None:
    """边界：配额只管图——零限额下文字笔记照记（不殃及无图请求）。"""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_FILES", 0)
    monkeypatch.setattr(notes_mod, "_MAX_SESSION_IMAGE_BYTES", 0)
    capability = build_notes_capability(_config(tmp_path))
    result = capability(_message("笔记 记 纯文字一条"), object())
    assert "记下了" in result.body


# ---------- 跟随面：默认常量保守在册（数字改了必须过明面） ----------

def test_default_quota_constants_are_conservative() -> None:
    """常量口径锁：会话帽必须显著小于「200 条 × 4 张 × 20MB ≈ 16GB」最坏值。"""
    assert notes_mod._MAX_SESSION_IMAGE_FILES < 200 * 4
    assert notes_mod._MAX_SESSION_IMAGE_BYTES < 200 * 4 * 20 * 1024 * 1024
    # 单会话字节帽取「百 MB 量级」：容得下 10 张顶格 20MB 图，不放开到 GB。
    assert notes_mod._MAX_SESSION_IMAGE_BYTES <= 1024 * 1024 * 1024
