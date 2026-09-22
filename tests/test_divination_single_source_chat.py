"""S-DIV 回归锁：聊天侧占卜必须跑唯一真身（活性判据，不接受「存在性糊过关」）。

钉三件事（指控与取证全录 ``.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-DIV.md``）：

1. **活性**：按根 ``__init__.py`` 的真实构造法（只传 ``render_backend``）调用能力时，
   实际执行的那一发牌函数是 ``data/deck_math.draw_tarot_cards``，而不是收编前
   ``data/tarot`` 的 rng.sample 老路径；牌面并且真的过了 ``validated_tarot_cards``。
2. **落库落在这张表**：配了在册键之后，抽牌记录确实出现在 ``draws`` 表里——判据是
   回读 sqlite 文件，不是「某函数被调用过」。
3. **导入面**：聊天能力件不许再 import 第二套随机发牌入口（AST 锁）。

注毒由席外执行（改真身文件→跑本件→sha256 核对还原），结果记在席位日志 §4。
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.divination.api.dto import (
    DivinationDrawPayload,
)
from plugins.bot_unified_runtime.domains.divination.api.facet import (
    build_divination_facade_from_config,
)
from plugins.bot_unified_runtime.domains.divination.capabilities import (
    divination as cap_mod,
)
from plugins.bot_unified_runtime.domains.divination.data import deck_math
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DB_PATH_CONFIG_KEY,
    DrawError,
    DrawStore,
    draw_store_from_config,
)

_CAP_FILE = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/divination/capabilities/divination.py"
)
_TAROT_MODULE = "plugins.bot_unified_runtime.domains.divination.data.tarot"
#: 第二套随机发牌入口：聊天侧一旦出现它们的 import，当场红。
_SECOND_SOURCE_DRAWING = ("single_guidance", "three_card_spread", "draw_cards")
#: 允许留在聊天侧的 data.tarot 符号：每日一抽唯一实现 + 两个纯文本渲染器。
_ALLOWED_TAROT_IMPORTS = {"daily_card", "format_single_text", "format_three_text"}
_NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def _message(text: str, *, request_id: str = "req-1", sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        request_id=request_id,
        timestamp=_NOW,
    )


@contextmanager
def _recording(*names: str) -> Iterator[list[str]]:
    """把能力模块全局名换成记录器：记录的是**实际被执行**的那一个。

    能力件按模块全局名解析发牌函数，因此这里 patch 的就是它运行时真正调用的对象，
    不需要读源码猜分支。
    """
    originals = {name: getattr(cap_mod, name) for name in names}
    seen: list[str] = []

    def wrap(name: str, fn: Any) -> Any:
        def inner(*args: Any, **kwargs: Any) -> Any:
            seen.append(name)
            return fn(*args, **kwargs)

        return inner

    for name, fn in originals.items():
        setattr(cap_mod, name, wrap(name, fn))
    try:
        yield seen
    finally:
        for name, fn in originals.items():
            setattr(cap_mod, name, fn)


def _chat_capability(config: Any, **kwargs: Any) -> Any:
    """与根 ``__init__.py:4158`` 同型：render_backend 之外不额外注入任何东西。"""
    return cap_mod.build_divination_capability(config, render_backend=None, **kwargs)


def _draws_rows(db_path: Path) -> list[tuple[str, str, int]]:
    connection = sqlite3.connect(db_path)
    try:
        return list(
            connection.execute(
                "SELECT kind, spread_id, COUNT(*) FROM draws GROUP BY kind, spread_id"
            )
        )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# ① 活性：聊天侧发牌 = 唯一真身，且过完整性门
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["塔罗", "塔罗 三张"])
def test_chat_random_tarot_executes_the_single_source(text: str) -> None:
    with _recording("draw_tarot_cards", "daily_card") as seen:
        result = _chat_capability(SimpleNamespace())(_message(text), None)
    assert seen == ["draw_tarot_cards"], f"聊天侧实际执行的发牌函数={seen}（应为唯一真身）"
    assert result.body, "唯一真身路径必须照常出正文"


def test_chat_ephemeral_path_still_passes_the_integrity_gate() -> None:
    """不过完整性门的「降级」等于第二套渲染面——这条锁的是门真的被穿过。"""
    original = deck_math.validated_tarot_cards
    hits: list[str] = []

    def probe(record: Any) -> Any:
        hits.append(str(record.spread_id))
        return original(record)

    deck_math.validated_tarot_cards = probe
    try:
        _chat_capability(SimpleNamespace())(_message("塔罗 三张"), None)
    finally:
        deck_math.validated_tarot_cards = original
    assert hits == ["past_present_future"], f"聊天未装配路径没过完整性门：{hits}"


def test_chat_daily_card_is_the_single_shared_implementation() -> None:
    """每日一抽两侧同一张牌：落库前后正文逐字相同（不落库≠换算法）。"""
    with _recording("daily_card") as ephemeral_seen:
        ephemeral = _chat_capability(SimpleNamespace())(
            _message("塔罗 每日一抽"), None
        )
    with _recording("daily_card") as persisted_seen:
        persisted = _chat_capability(SimpleNamespace())(_message("塔罗 每日一抽"), None)
    assert ephemeral_seen == persisted_seen == ["daily_card"]
    assert ephemeral.body == persisted.body


# ---------------------------------------------------------------------------
# ② 活性：配了在册键 ⇒ 记录确实落在 draws 表；两侧同一个解析口
# ---------------------------------------------------------------------------


def test_chat_persists_into_the_single_source_table(tmp_path: Path) -> None:
    db_path = tmp_path / "draws.sqlite3"
    config = SimpleNamespace(**{DB_PATH_CONFIG_KEY: str(db_path)})
    capability = _chat_capability(config)
    for index in range(3):  # 每次换 request_id（幂等键），换主体绕开每主体冷却
        capability(
            _message("塔罗", request_id=f"persist-{index}", sender_id=f"u{index}"), None
        )
    assert db_path.exists(), "配了在册键却连库文件都没建 ⇒ 装配口没接上"
    rows = _draws_rows(db_path)
    assert rows == [("tarot", "single", 3)], f"抽牌记录没有落在唯一真身表：{rows}"


def test_chat_and_rest_land_in_the_same_single_table(tmp_path: Path) -> None:
    """「聊天一处、REST 另一处」正是 WP9 要消灭的形态：同一键 ⇒ 同一张 draws 表。"""
    db_path = tmp_path / "draws.sqlite3"
    config = SimpleNamespace(**{DB_PATH_CONFIG_KEY: str(db_path)})
    _chat_capability(config)(_message("塔罗", request_id="same-1"), None)

    facade = build_divination_facade_from_config(config)
    assert facade is not None, "同一个在册键在两侧解析出了不同结论"
    facade.draw(
        "tarot",
        DivinationDrawPayload(
            kind="tarot",
            spread_id="single",
            question="最近运势如何",
            timezone_id="Asia/Shanghai",
            workspace_id="default",
        ),
        "u9",
        "rest-same-1",
    )

    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".sqlite3"] == [
        "draws.sqlite3"
    ], "两侧各建了一个库文件 ⇒ 装配口又分叉了"
    assert _draws_rows(db_path) == [("tarot", "single", 2)], (
        "聊天与 REST 的抽牌没有落在同一张表的同一份记录里"
    )


def test_explicit_injection_wins_over_config_resolution(tmp_path: Path) -> None:
    """注入优先于现读：显式传进来的存储若被架空，就会「两条路各写一处」。"""
    injected = tmp_path / "injected.sqlite3"
    from_config = tmp_path / "from-config.sqlite3"
    capability = cap_mod.build_divination_capability(
        SimpleNamespace(**{DB_PATH_CONFIG_KEY: str(from_config)}),
        render_backend=None,
        draw_store=DrawStore(injected),
    )
    capability(_message("塔罗", request_id="precedence-1"), None)
    assert injected.exists() and not from_config.exists(), "装配优先级漂移"


def test_resolver_fails_closed_without_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置 ⇒ None：绝不猜默认路径（源码树 data/ 红线，也是旧「不注入=不建库」口径）。"""
    monkeypatch.chdir(tmp_path)
    assert draw_store_from_config(SimpleNamespace()) is None
    assert draw_store_from_config(None) is None
    assert list(tmp_path.iterdir()) == [], "未配置键却写出了文件"


# ---------------------------------------------------------------------------
# ③ 导入面：AST 锁死「聊天侧不 import 第二套」
# ---------------------------------------------------------------------------


def _imported_from(capability_source: str, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(capability_source)):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


def test_chat_capability_does_not_import_the_second_drawing_algorithm() -> None:
    source = _CAP_FILE.read_text(encoding="utf-8")
    imported = _imported_from(source, _TAROT_MODULE)
    assert imported, "聊天能力件对 data.tarot 的 import 面消失，本锁需随之重判"
    assert not imported & set(_SECOND_SOURCE_DRAWING), (
        f"聊天侧又 import 了第二套随机发牌入口：{sorted(imported & set(_SECOND_SOURCE_DRAWING))}"
    )
    assert imported <= _ALLOWED_TAROT_IMPORTS, f"聊天侧 data.tarot import 面越界：{sorted(imported)}"


def test_chat_capability_defines_no_second_drawing_logic() -> None:
    """算法面真锁：能力件里不该出现「自己抽牌」的写法（rng.sample / rng.random）。"""
    source = _CAP_FILE.read_text(encoding="utf-8")
    for token in ("rng.sample(", ".sample(DECK", "rng.random()"):
        assert token not in source, f"聊天能力件内出现自备发牌逻辑：{token}"


# ---------------------------------------------------------------------------
# ④ 现网构造法不崩（fail-open 面：唯一真身之外没有第二条路）
# ---------------------------------------------------------------------------


def test_chat_capability_still_answers_every_tarot_shape() -> None:
    capability = _chat_capability(SimpleNamespace())
    for index, text in enumerate(("塔罗", "塔罗 三张", "塔罗 每日一抽")):
        result = capability(_message(text, request_id=f"shape-{index}"), None)
        assert result.kind == "divination"
        assert ("（正位）" in result.body) or ("（逆位）" in result.body), text


def test_store_unavailable_falls_back_to_the_gentle_line(tmp_path: Path) -> None:
    """存储被改成不可用 ⇒ 温和兜底，而不是回落第二套算法（第二套已无处可回）。"""
    config = SimpleNamespace(**{DB_PATH_CONFIG_KEY: str(tmp_path / "draws.sqlite3")})
    capability = _chat_capability(config)
    original = DrawStore.persist_draw_once

    def explode(self: DrawStore, *args: Any, **kwargs: Any) -> Any:
        raise DrawError("deck_integrity_mismatch", "注入故障")

    DrawStore.persist_draw_once = explode
    try:
        result = capability(_message("塔罗", request_id="boom-1"), None)
    finally:
        DrawStore.persist_draw_once = original
    assert "divination:integrity_mismatch" in result.audit_tags
    with _recording("draw_tarot_cards", "daily_card") as seen:
        assert capability(_message("塔罗", request_id="boom-2"), None)
    assert seen == ["draw_tarot_cards"]
