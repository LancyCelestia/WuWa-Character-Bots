"""P14 波「随机发图派发」离线回归：窗内不重发 + 三触发里的自动腿 + 降级。

全部离线：图库指向 ``tmp_path`` 里造的假图片（零网络、零源码树写入）。
判据分三层——取图口（``pick_fresh_image`` / 能力本体）、门链（关态一条不发、
blocked/安静时间）、以及根装配段的 AST 活性锁（缺接线即红，注毒验过杀伤力）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    proactive_action_allowed,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.meme.reactions.engine import ProactiveGate

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"


def _gallery(tmp_path: Path, count: int) -> str:
    """造一个只有 .png 的图库目录（**每张内容互不相同**）。

    内容必须逐张不同：ITEM 15(b) 把「同一张图」的判据从路径换成**内容摘要**，
    旧夹具那句「内容无所谓——只读清单不读字节」正是被这条推翻的前提——
    三张同字节的假图在摘要口径下只是一张，窗内不重发那条腿就测不到了。
    """
    root = tmp_path / "gallery"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (root / f"pic-{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([index]) * 8)
    return str(root)


def _config(**overrides):
    base = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [],
        "bot_randpic_trigger_words": [],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_no_repeat_window_seconds": 0.0,
        "bot_randpic_dispatch_enabled": False,
        "bot_randpic_dispatch_probability": 1.0,
        "bot_randpic_dispatch_cooldown_seconds": 600.0,
        "bot_randpic_dispatch_max_per_hour": 2,
        "bot_quiet_hours_enabled": False,
        "bot_quiet_hours_start": "00:00",
        "bot_quiet_hours_end": "06:00",
        "bot_quiet_hours_timezone": "UTC",
        "bot_quiet_hours_session_types": ["group"],
        "bot_quiet_hours_bypass_roles": ["admin"],
        "bot_blocked_user_ids": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _window() -> randpic.RecentImageWindow:
    return randpic.RecentImageWindow()


def _message(text: str = "随机图", *, session_id: str = "private_7"):
    return SimpleNamespace(
        request_id="req-1",
        plain_text=text,
        session_id=session_id,
        message_id="m-1",
    )


@pytest.fixture(autouse=True)
def _clean_scan_cache():
    """目录清单 TTL 缓存是模块级状态——逐例清空，否则跨例串味。"""
    randpic._SCAN_CACHE.clear()
    yield
    randpic._SCAN_CACHE.clear()


# ------------------------------------------------------------------ 关态旧行为
def test_window_zero_keeps_legacy_path_untouched(tmp_path) -> None:
    """窗=0（缺省）：不建窗账、不改排序，取图口退化成旧的那一步。"""
    dirs = [_gallery(tmp_path, 3)]
    config = _config(bot_randpic_dirs=dirs)
    assert randpic.no_repeat_window_seconds(config) == 0.0
    picked = randpic.pick_gallery_image(config, session_key="private_7")
    assert picked is not None and picked.exists()


def test_command_result_shape_is_unchanged(tmp_path) -> None:
    dirs = [_gallery(tmp_path, 2)]
    capability = randpic.build_randpic_capability(_config(bot_randpic_dirs=dirs))
    result = capability(_message(), None)
    assert result.capability_id == "bot.randpic"
    assert result.title == "" and result.body == ""
    assert [str(Path(item["file"]).name) for item in result.images]


# ------------------------------------------------------------------ 窗内不重发
def test_no_repeat_window_walks_whole_gallery_then_stops(tmp_path) -> None:
    dirs = [_gallery(tmp_path, 3)]
    window = _window()
    seen: list[str] = []
    for index in range(3):
        picked = randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=3600.0,
            seed=f"seed-{index}",
        )
        assert picked is not None
        seen.append(str(picked))
    assert len(set(seen)) == 3, f"窗内出现了重样：{seen}"
    # 整库都在窗内 → 主动路宁可不发。
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=3600.0,
            seed="seed-3",
            allow_exhausted=False,
        )
        is None
    )


def test_exhausted_window_still_serves_the_command_path(tmp_path) -> None:
    """指令路：用户开口要图，绝不因防重复而拒不发——退「最久没发」那张。"""
    dirs = [_gallery(tmp_path, 1)]
    picked = randpic.pick_fresh_image(
        dirs,
        session_key="private_7",
        window=_window(),
        window_seconds=3600.0,
        seed="s1",
    )
    again = randpic.pick_fresh_image(
        dirs,
        session_key="private_7",
        window=_window(),
        window_seconds=3600.0,
        seed="s2",
        allow_exhausted=True,
    )
    assert picked is not None and again == picked


def test_window_is_per_session(tmp_path) -> None:
    dirs = [_gallery(tmp_path, 1)]
    window = _window()
    first = randpic.pick_fresh_image(
        dirs,
        session_key="private_7",
        window=window,
        window_seconds=3600.0,
        seed="a",
        allow_exhausted=False,
    )
    other = randpic.pick_fresh_image(
        dirs,
        session_key="group_42_9",
        window=window,
        window_seconds=3600.0,
        seed="b",
        allow_exhausted=False,
    )
    assert first is not None and other is not None
    # 同会话再来一次就撞窗（另一会话不受影响）。
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=3600.0,
            seed="c",
            allow_exhausted=False,
        )
        is None
    )


def test_window_expiry_releases_the_file(tmp_path) -> None:
    dirs = [_gallery(tmp_path, 1)]
    window = randpic.RecentImageWindow(clock=lambda: 100.0)
    randpic.pick_fresh_image(
        dirs,
        session_key="private_7",
        window=window,
        window_seconds=10.0,
        seed="a",
        allow_exhausted=False,
    )
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=10.0,
            seed="b",
            allow_exhausted=False,
        )
        is None
    )
    # 把钟推到窗外（缓存 TTL 也同时过期，重扫目录）。
    window.clock = lambda: 200.0  # type: ignore[assignment]
    randpic._SCAN_CACHE.clear()
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=window,
            window_seconds=10.0,
            seed="c",
            allow_exhausted=False,
        )
        is not None
    )


def test_picking_is_deterministic_for_same_seed(tmp_path) -> None:
    dirs = [_gallery(tmp_path, 5)]
    first = randpic.deterministic_choice(
        sorted(randpic.list_gallery_images(dirs), key=str), "seed-x"
    )
    second = randpic.deterministic_choice(
        sorted(randpic.list_gallery_images(dirs), key=str), "seed-x"
    )
    assert first == second
    spread = {
        randpic.deterministic_choice(
            sorted(randpic.list_gallery_images(dirs), key=str), f"seed-{i}"
        )
        for i in range(200)
    }
    assert len(spread) == 5, "确定性取图把某些张永远遮住了"


# ---------------------------------------------------------------------- 降级
def test_missing_dir_yields_none_not_crash(tmp_path) -> None:
    dirs = [str(tmp_path / "no-such-gallery")]
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=_window(),
            window_seconds=60.0,
            seed="s",
        )
        is None
    )


def test_empty_dir_yields_none(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    config = _config(
        bot_randpic_dirs=[str(empty)], bot_randpic_no_repeat_window_seconds=60.0
    )
    assert (
        randpic.pick_gallery_image(config, session_key="private_7", seed="s") is None
    )
    result = randpic.build_randpic_capability(config)(_message(), None)
    assert "gallery_empty" in result.audit_tags
    assert not result.images


def test_gone_file_after_scan_is_not_picked(tmp_path) -> None:
    """缓存 TTL 内文件被移走 → 不挑死引用（宁可按空库降级）。"""
    dirs = [_gallery(tmp_path, 2)]
    randpic.list_gallery_images(dirs)  # 先填缓存
    for path in Path(dirs[0]).glob("*.png"):
        path.unlink()
    assert (
        randpic.pick_fresh_image(
            dirs,
            session_key="private_7",
            window=_window(),
            window_seconds=60.0,
            seed="s",
        )
        is None
    )


def test_non_image_files_are_ignored(tmp_path) -> None:
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "note.txt").write_text("x", encoding="utf-8")
    (root / "clip.mp4").write_bytes(b"0")
    assert (
        randpic.pick_fresh_image(
            [str(root)],
            session_key="private_7",
            window=_window(),
            window_seconds=60.0,
            seed="s",
        )
        is None
    )


def test_capability_does_not_create_folders(tmp_path) -> None:
    missing = tmp_path / "never-created"
    config = _config(
        bot_randpic_dirs=[str(missing)], bot_randpic_no_repeat_window_seconds=60.0
    )
    randpic.build_randpic_capability(config)(_message(), None)
    randpic.pick_gallery_image(config, session_key="private_7", seed="s")
    assert not missing.exists()


# -------------------------------------------------------------------- 门链
def _dispatch_config(**overrides):
    base = {
        "bot_randpic_dispatch_enabled": True,
        "bot_randpic_dispatch_probability": 1.0,
        "bot_randpic_dispatch_cooldown_seconds": 600.0,
        "bot_randpic_dispatch_max_per_hour": 2,
    }
    base.update(overrides)
    return _config(**base)


def test_dispatch_off_by_default() -> None:
    assert not proactive_action_allowed(
        _config(),
        prefix="bot_randpic_dispatch_",
        gate=ProactiveGate(clock=lambda: 10.0),
        session_key="private_7",
        message_key="randpic:m1",
        user_id="7",
    )


def test_dispatch_probability_zero_and_one() -> None:
    gate = ProactiveGate(clock=lambda: 10.0)
    assert not proactive_action_allowed(
        _dispatch_config(bot_randpic_dispatch_probability=0.0),
        prefix="bot_randpic_dispatch_",
        gate=gate,
        session_key="private_7",
        message_key="randpic:m1",
        user_id="7",
    )
    assert proactive_action_allowed(
        _dispatch_config(),
        prefix="bot_randpic_dispatch_",
        gate=gate,
        session_key="private_7",
        message_key="randpic:m2",
        user_id="7",
    )


def test_dispatch_cooldown_and_hourly_ceiling() -> None:
    state = {"now": 100.0}
    gate = ProactiveGate(clock=lambda: state["now"])
    config = _dispatch_config(bot_randpic_dispatch_cooldown_seconds=600.0)

    def fire(message_key: str) -> bool:
        return proactive_action_allowed(
            config,
            prefix="bot_randpic_dispatch_",
            gate=gate,
            session_key="private_7",
            message_key=f"randpic:{message_key}",
            user_id="7",
        )

    assert fire("m1")
    state["now"] = 200.0
    assert not fire("m2")  # 冷却窗内
    state["now"] = 800.0
    assert fire("m3")
    state["now"] = 900.0
    assert not fire("m4")  # 每小时上限=2 用满


def test_dispatch_blocked_wins_and_quiet_hours_blocks_group() -> None:
    assert not proactive_action_allowed(
        _dispatch_config(bot_blocked_user_ids=["7"], bot_quiet_hours_enabled=False),
        prefix="bot_randpic_dispatch_",
        gate=ProactiveGate(clock=lambda: 10.0),
        session_key="private_7",
        message_key="randpic:m1",
        user_id="7",
    )
    # 群内、整天都是安静窗（start==end 即恒在窗内）⇒ 概率 1.0 也不发。
    assert not proactive_action_allowed(
        _dispatch_config(
            bot_quiet_hours_enabled=True,
            bot_quiet_hours_start="03:00",
            bot_quiet_hours_end="03:00",
        ),
        prefix="bot_randpic_dispatch_",
        gate=ProactiveGate(clock=lambda: 10.0),
        session_key="group_42_9",
        message_key="randpic:m1",
        group_id="42",
        user_id="9",
    )


# ---------------------------------------------------------- 根装配段活性锁
def test_root_dispatch_wiring_reaches_gate_gallery_and_send() -> None:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_maybe_dispatch_randpic"
    )
    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
    for name in (
        "proactive_action_allowed",
        "pick_gallery_image",
        "_send_parts_through_unified_pipeline",
    ):
        assert name in names, f"派发腿缺 {name}＝门/取图/投递有一环没接"

    # 门必须在取图之前：先过门再挑图，不许先挑中一张、被门拦下、白记一笔窗账。
    def _first_line(name: str) -> int:
        return min(
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id == name
        )

    assert _first_line("proactive_action_allowed") < _first_line("pick_gallery_image")
    assert _first_line("pick_gallery_image") < _first_line(
        "_send_parts_through_unified_pipeline"
    )


def test_root_no_second_gallery_scanner_outside_randpic() -> None:
    """除 randpic 件本身，根装配文件里不许出现第二份 walk/图片扩展名扫描。"""
    source = ROOT_INIT.read_text(encoding="utf-8-sig")
    assert "os.walk" not in source, "根文件自造第二套目录扫描"
    assert ".webp" not in source, "根文件手抄图片扩展名表"
