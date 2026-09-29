"""S-FIX-ATK-DIVRNG 票②：randpic 窗账桶键单源（群场景三腿同账）合成锁。

窗账的「窗内不重发 / 并发防双发」只在同桶内成立。三坐标现算（root 装配文件本席
只读取证，行号为 2026-09-28 现算）：

- 被戳臂（root ~:6272-6280）：``session_key=f"group_{poker_group}_{poker_id}"``
  ——按人建桶，直入 ``pick_gallery_image``；
- 自动腿（root ~:6186-6191 ``_maybe_dispatch_randpic``）：``session_key=message.session_id``
  ——群消息桶为 ``group_{G}``（``event.get_session_id()``，root ~:1300）；
- 指令腿（randpic 能力 ``_pick_for_command``）：``message.session_id`` → ``group_{G}``。

修复前群场景被戳臂与两条后腿是**两本账**：同一张图在 ``group_{G}_{U}`` 与
``group_{G}`` 各可占坑一次＝窗内双发，「防双发/窗内不重发」承诺在群内互相看不见。

本锁执法在账本入口（``canonical_bucket_key`` / ``RecentImageWindow``，本席可写面）：
root 被戳臂改判为 ``group_{G}``（可粘贴 diff 见
``.superpowers/sdd/2026-09-27-fullload/logs/SEAT-FIX-ATK-DIVRNG.md`` §待主代理落盘）
之前与之后都应全绿——断言只依赖**账本语义**（两种写法落同一本账），不依赖调用方
入参形状，故为合成锁。私聊 ``private_{U}`` 两臂本会同桶，锁一并看住不被并桶。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    RecentImageWindow,
    canonical_bucket_key,
    pick_fresh_outcome,
    pick_gallery_image_outcome,
)

_WINDOW = 3600.0


# ---------------------------------------------------------------------------
# 形状规则：只收敛「群键+发送者数字后缀」，其余原样。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("group_123_456", "group_123"),   # 被戳臂旧形状 → 群账
        ("group_123", "group_123"),       # 后腿形状 → 不动（root 改判后即为入参）
        ("private_42", "private_42"),     # 私聊带人，语义上不可并桶
        ("group_1_2_3", "group_1_2_3"),   # 非本形状：原样透传
        ("group_-7_42", "group_-7_42"),   # 非纯数字群号（他适配器形状）：不动
        ("telegram:group:123", "telegram:group:123"),  # 其它适配器：不动
        ("", ""),
    ],
)
def test_canonical_bucket_key_shape_rules(raw: str, expected: str) -> None:
    assert canonical_bucket_key(raw) == expected


# ---------------------------------------------------------------------------
# 账本语义：两种写法必须落同一本账。
# ---------------------------------------------------------------------------

def test_poke_shape_claim_blocks_group_shape_leg() -> None:
    # 被戳臂按旧形状占坑后，自动腿（群键形状）必须看不见第二次的机会。
    window = RecentImageWindow()
    assert window.try_claim("group_7_42", "idA", window_seconds=_WINDOW) is True
    assert window.try_claim("group_7", "idA", window_seconds=_WINDOW) is False


def test_group_shape_claim_blocks_poke_shape_leg() -> None:
    # 反向：后腿先占群账，被戳臂旧形状再来必须让开（并发防双发不分先来后到）。
    window = RecentImageWindow()
    assert window.try_claim("group_7", "idA", window_seconds=_WINDOW) is True
    assert window.try_claim("group_7_42", "idA", window_seconds=_WINDOW) is False


def test_record_and_reads_share_one_bucket_across_shapes() -> None:
    window = RecentImageWindow()
    window.record("group_7", "idB", window_seconds=_WINDOW, size=111, path="x/b.png")
    # 群账写，旧形状读 ⇒ 必须读得到（recent_keys / recent_sizes / least_recent / newest / hint）。
    assert "idB" in window.recent_keys("group_7_42", window_seconds=_WINDOW)
    sizes, unknown = window.recent_sizes("group_7_42", window_seconds=_WINDOW)
    assert sizes == frozenset({111}) and unknown is False
    assert window.least_recent_key("group_7_42", window_seconds=_WINDOW) == "idB"
    assert window.newest_path("group_7_42", window_seconds=_WINDOW) == "x/b.png"
    assert window.path_hint_for("group_7_42", "idB", window_seconds=_WINDOW) == "x/b.png"


def test_different_people_and_groups_do_not_merge_where_wrong() -> None:
    window = RecentImageWindow()
    # 同群不同人的旧形状 ⇒ 同一本群账（这正是统一语义）。
    assert window.try_claim("group_7_42", "idA", window_seconds=_WINDOW) is True
    assert window.try_claim("group_7_43", "idA", window_seconds=_WINDOW) is False
    # 不同群不并桶。
    assert window.try_claim("group_8_42", "idA", window_seconds=_WINDOW) is True
    # 私聊不同人各记各账（绝不误并）。
    assert window.try_claim("private_42", "idZ", window_seconds=_WINDOW) is True
    assert window.try_claim("private_43", "idZ", window_seconds=_WINDOW) is True


# ---------------------------------------------------------------------------
# 端到端合成：单图池，被戳臂先占，自动腿必须不发；指令腿只许「刻意复发」记档。
# root 改判前后（poke_key 两种形状）都必须绿。
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("poke_key", ["group_7_42", "group_7"])
def test_group_double_send_prevented_end_to_end(
    tmp_path: Path, poke_key: str
) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    window = RecentImageWindow()

    first = pick_fresh_outcome(
        [str(tmp_path)], session_key=poke_key, window=window,
        window_seconds=_WINDOW, seed="poke-randpic:42:7", allow_exhausted=False,
    )
    assert first.sent, "首腿应占到这张图"

    second = pick_fresh_outcome(
        [str(tmp_path)], session_key="group_7", window=window,
        window_seconds=_WINDOW, seed="randpic-dispatch:group_7:msg1",
        allow_exhausted=False,
    )
    # 桶分裂修复前：这里会各发一次同一张（双发）。修复后必须整库在窗 → 主动腿不发。
    assert second.path is None
    assert second.reason == "held_pool_exhausted"

    # 指令腿（用户开口要图）：允许刻意复发，但依据代号必须是 recycled 而非 picked。
    command = pick_fresh_outcome(
        [str(tmp_path)], session_key="group_7", window=window,
        window_seconds=_WINDOW, seed="randpic-cmd:msg2", allow_exhausted=True,
    )
    assert command.sent and command.reason.startswith("recycled")


def test_via_default_singleton_entry_point(tmp_path: Path) -> None:
    # 走 root 真正进入的唯一取图口（默认单例账本），用高段唯一群号避免串扰。
    img = tmp_path / "b.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 64)
    config = SimpleNamespace(
        bot_randpic_dirs=[str(tmp_path)],
        bot_randpic_no_repeat_window_seconds=int(_WINDOW),
        bot_randpic_max_file_mb=0,
    )
    poke_key, leg_key = "group_9100001_42", "group_9100001"
    first = pick_gallery_image_outcome(
        config, session_key=poke_key, seed="poke-randpic:42:9100001",
        allow_exhausted=False,
    )
    assert first.sent
    second = pick_gallery_image_outcome(
        config, session_key=leg_key, seed="randpic-dispatch:group_9100001:m1",
        allow_exhausted=False,
    )
    assert second.path is None and second.reason == "held_pool_exhausted"
