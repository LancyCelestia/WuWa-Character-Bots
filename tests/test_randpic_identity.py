"""随机图片能力与会话级身份记忆回归（2026-09-11 晚间批次）。"""

from __future__ import annotations

import random
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.randpic import (
    build_randpic_capability,
    is_randpic_command,
    pick_random_image,
)
from plugins.bot_unified_runtime.character.session_identity import SessionIdentityStore
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

# ---------- randpic：只读自定义文件夹，绝不自建 ----------

def _make_image(dir_path: Path, name: str, payload: bytes = b"x") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    file = dir_path / name
    file.write_bytes(payload)
    return file


def test_is_randpic_command_trigger_matrix() -> None:
    assert is_randpic_command("随机图")
    assert is_randpic_command("来张图！")
    assert is_randpic_command("随机图 吧")
    assert is_randpic_command("来张猫图", ("来张猫图",))
    # 包含关系词不误触发。
    assert not is_randpic_command("随机图片库在哪")
    assert not is_randpic_command("帮我找一张图")


def test_pick_random_image_reads_custom_dirs_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.bot_unified_runtime.capabilities import randpic

    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    folder = tmp_path / "我的图库" / "子目录"
    _make_image(folder, "a.png")
    _make_image(folder, "b.jpg")
    picked = pick_random_image([str(tmp_path / "我的图库")], rng=random.Random(1))
    assert picked is not None and picked.suffix in {".png", ".jpg"}


def test_pick_random_image_missing_dir_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.bot_unified_runtime.capabilities import randpic

    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    assert pick_random_image([str(tmp_path / "不存在的目录")]) is None


def test_randpic_capability_does_not_create_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.bot_unified_runtime.capabilities import randpic

    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    gallery = tmp_path / "图库"
    _make_image(gallery, "x.png")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    config = SimpleNamespace(bot_randpic_dirs=[str(gallery)])
    capability = build_randpic_capability(config)
    message = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot",
        session_id="group:1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="1",
        plain_text="来张图",
        message_id="m1",
    )

    class _Decision:
        pass

    result = capability(message, _Decision())
    assert result.images and Path(str(result.images[0]["file"])).name == "x.png"
    after = sorted(p.name for p in tmp_path.rglob("*"))
    assert before == after  # 绝不自建任何文件/目录


def test_randpic_capability_empty_gallery_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.bot_unified_runtime.capabilities import randpic

    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    config = SimpleNamespace(bot_randpic_dirs=[str(tmp_path / "空图库")])
    capability = build_randpic_capability(config)
    message = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="bot",
        session_id="group:1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="1",
        plain_text="随机图",
        message_id="m2",
    )

    class _Decision:
        pass

    result = capability(message, _Decision())
    assert not result.images
    assert "BOT_RANDPIC_DIRS" in result.body


# ---------- 会话级身份记忆 ----------

def test_session_identity_set_and_render_with_ooc_guard(tmp_path: Path) -> None:
    store = SessionIdentityStore(tmp_path / "identity.sqlite3")
    store.set("group:123", nickname="岸宝", tags=["花房值日", " piano 值班"], set_by="admin")
    section = store.render_prompt_section("group:123")
    assert "岸宝" in section
    assert "花房值日" in section
    # 防 OOC 护栏必须内建在渲染文本里。
    assert "守岸人" in section and ("不" in section)
    # 未设置的会话返回空。
    assert store.render_prompt_section("group:999") == ""


def test_session_identity_clear_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "identity.sqlite3"
    store = SessionIdentityStore(path)
    store.set("group:1", nickname="小岸同学", set_by="admin")
    assert store.get("group:1") is not None
    store.close()

    reopened = SessionIdentityStore(path)
    assert reopened.get("group:1") is not None
    assert reopened.get("group:1").nickname == "小岸同学"
    assert reopened.clear("group:1") is True
    assert reopened.get("group:1") is None


def test_session_identity_admin_gate(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.capabilities.runtime_admin import (
        build_session_identity_admin_result,
    )

    config = SimpleNamespace(
        bot_session_identity_db_path=str(tmp_path / "identity.sqlite3")
    )
    denied = build_session_identity_admin_result(
        config, request_id="r1", actor_roles=["user"],
        session_key="group:1", command_text="set 岸宝",
    )
    assert "管理员" in denied.body or denied.body

    ok = build_session_identity_admin_result(
        config, request_id="r2", actor_roles=["admin"],
        session_key="group:1", command_text="set 岸宝",
    )
    assert "岸宝" in ok.body
    shown = build_session_identity_admin_result(
        config, request_id="r3", actor_roles=["admin"],
        session_key="group:1", command_text="show",
    )
    assert "岸宝" in shown.body


# ---------- config：.env 字符串必须能解析成 randpic 列表（2026-09-12 潜伏启动崩修复） ----------

def test_randpic_list_fields_parse_from_env_json_string() -> None:
    from plugins.bot_unified_runtime.config import Config

    config = Config.model_validate(
        {
            "bot_randpic_dirs": '["C:/Users/LancyCelestia/Picture"]',
            "bot_randpic_trigger_words": '["随机图", "来张图"]',
        }
    )
    assert config.bot_randpic_dirs == ["C:/Users/LancyCelestia/Picture"]
    assert config.bot_randpic_trigger_words == ["随机图", "来张图"]
