"""会话键单一事实源接线锁（FIX5，2026-09-20 spec-audit 修复席）。

缺陷（P1，台账 #33/#29 同根病类第三次）：全仓两个同名 `_is_group_session`
**判据相反**——`chat_reply/capabilities/memory.py` 认 `group:` 冒号形、
`meme/reactions/engine.py` 认 `group_` 下划线形；而生产摄取层的会话键是
NoneBot `get_session_id()` 的**下划线形**（OneBot V11 逐字实测
`f"group_{group_id}_{user_id}"`）。冒号判据落在真实群键上恒 False →
群聊 `memory list` 走不进群门 → 个人敏感度记忆被列进群聊，群守卫文案成死码。

本件六层锁（对齐「机器门九种假绿」自查：门必须扫全量真实路径、中央件必须有
生产落点、可红性必须有变异证据）：

1. **RED→GREEN 行为复现**：生产形态群键下群门必须生效（修复前必红）；
2. **反过度修正锁**：私聊面与合成冒号形不被顺手改坏；
3. **委托锁**（monkeypatch 观测）：两处消费方真的走中央件，不是自持副本；
4. **字节现状锁**：收编前后对**真实输入**逐字节等价，放宽面单独点名；
5. **跨件一致性**：读侧前缀（F4 席修复面）与中央件不得劈叉；
6. **防再犯机器门**：AST 全树扫描，任何人再写「拿字符串键猜群/私聊」的本地判据
   即红（白名单外既有 5 处登记为基线，改好一处基线必须同步缩水，否则报陈旧）。

全离线、零网络、零 config；SQLite 一律 tmp_path（台账 #1 卫生规矩）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    memory as memory_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory import (
    route_memory_command,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory import (
    SQLiteMemoryRepository,
    build_fact_id,
)
from plugins.bot_unified_runtime.domains.core import session_keys
from plugins.bot_unified_runtime.domains.meme.reactions import engine as engine_mod
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    ProactiveGate,
    session_key_from_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"
CENTRAL_FILE = "plugins/bot_unified_runtime/domains/core/session_keys.py"
MEMORY_FILE = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py"
ENGINE_FILE = "plugins/bot_unified_runtime/domains/meme/reactions/engine.py"

GROUP = "1108838060"
SENDER = "3865067623"


class SimpleConfig:
    """最小 config 替身（只给 ``reaction_knobs`` 读的四键，全放行）。"""

    bot_reactions_enabled = True
    bot_reactions_probability = 1.0
    bot_reactions_cooldown_seconds = 0.0
    bot_reactions_max_per_hour = 999


def _seed(db: Path, *, session_id: str, text: str, sensitivity: str) -> None:
    """走生产写入口（SQLiteMemoryRepository.upsert_fact）落一条事实。"""
    SQLiteMemoryRepository(db).upsert_fact(
        fact_id=build_fact_id(SENDER, session_id, text),
        subject_user_id=SENDER,
        session_id=session_id,
        memory_kind="manual",
        text=text,
        confidence=1.0,
        source="manual_command",
        sensitivity=sensitivity,
    )


def _list_body(db: Path, *, session_id: str) -> str:
    return route_memory_command(
        "memory list",
        sender_id=SENDER,
        session_id=session_id,
        db_path=db,
    ).body


# ---------------------------------------------------------------------------
# 1. 行为 bug 复现（修复前必红）
# ---------------------------------------------------------------------------


def test_group_memory_list_never_leaks_personal_facts(tmp_path: Path) -> None:
    """生产形态群键（group_<gid>_<uid>）下 memory list 必须走群门。

    修复前为 RED：冒号判据恒 False ⇒ 个人记忆原文出现在群聊回复里。
    """
    db = tmp_path / "memory.sqlite3"
    group_key = session_key_from_ids(GROUP, SENDER)
    _seed(db, session_id=group_key, text="我只在私聊说过的住址", sensitivity="personal")
    _seed(db, session_id=group_key, text="群公告周末线下聚会", sensitivity="group")

    body = _list_body(db, session_id=group_key)

    assert "我只在私聊说过的住址" not in body
    assert "群公告周末线下聚会" in body


def test_group_memory_list_guard_copy_is_reachable(tmp_path: Path) -> None:
    """群内只有个人记忆时，必须给出群守卫文案（修复前该分支为死码）。"""
    db = tmp_path / "memory.sqlite3"
    group_key = session_key_from_ids(GROUP, SENDER)
    _seed(db, session_id=group_key, text="只私聊可见的画像", sensitivity="personal")

    assert "群聊中没有可公开查看的记忆" in _list_body(db, session_id=group_key)


def test_credentialed_memory_never_listed_in_group(tmp_path: Path) -> None:
    """credentialed 敏感度在群门下一律不外露（群门只放 public/group）。"""
    db = tmp_path / "memory.sqlite3"
    group_key = session_key_from_ids(GROUP, SENDER)
    _seed(db, session_id=group_key, text="某个服务口令", sensitivity="credentialed")
    _seed(db, session_id=group_key, text="可公示口味", sensitivity="public")

    body = _list_body(db, session_id=group_key)

    assert "某个服务口令" not in body
    assert "可公示口味" in body


# ---------------------------------------------------------------------------
# 2. 反过度修正锁（私聊面与合成形态）
# ---------------------------------------------------------------------------


def test_private_memory_list_still_shows_personal_facts(tmp_path: Path) -> None:
    """私聊裸 uid 键：个人记忆照旧可列（收编中央件不得顺手砍掉私聊面）。"""
    db = tmp_path / "memory.sqlite3"
    _seed(db, session_id=SENDER, text="只说给机器人的私话", sensitivity="personal")

    assert "只说给机器人的私话" in _list_body(db, session_id=SENDER)


def test_synthetic_colon_group_key_still_uses_group_gate(tmp_path: Path) -> None:
    """合成/推送路径的 group:<gid> 形态继续走群门（旧行为逐字保持）。"""
    db = tmp_path / "memory.sqlite3"
    colon_key = f"group:{GROUP}"
    _seed(db, session_id=colon_key, text="私聊才想说的地址", sensitivity="personal")
    _seed(db, session_id=colon_key, text="可以群内公示的偏好", sensitivity="public")

    body = _list_body(db, session_id=colon_key)

    assert "可以群内公示的偏好" in body
    assert "私聊才想说的地址" not in body


def test_add_and_delete_still_use_the_raw_session_key(tmp_path: Path) -> None:
    """写侧键形不改：add 落库的 session_id 与入参逐字相同，delete 按同键可删。"""
    db = tmp_path / "memory.sqlite3"
    group_key = session_key_from_ids(GROUP, SENDER)
    added = route_memory_command(
        "memory add 周末要交报告",
        sender_id=SENDER,
        session_id=group_key,
        db_path=db,
    ).body
    fact_id = added.split("fact_id=", 1)[1].splitlines()[0].strip()

    import sqlite3

    with sqlite3.connect(db) as connection:
        stored = connection.execute(
            "SELECT session_id FROM memory_facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()[0]
    assert stored == group_key  # 中央件不参与写侧键形，逐字透传

    deleted = route_memory_command(
        f"memory delete {fact_id}",
        sender_id=SENDER,
        session_id=group_key,
        db_path=db,
    ).body
    assert "已删除记忆" in deleted


# ---------------------------------------------------------------------------
# 3. 委托锁：两处消费方必须经中央件（monkeypatch 可观测，非文本断言）
# ---------------------------------------------------------------------------


def test_memory_capability_delegates_to_central_piece(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """memory 的群判定必须调中央件名（换成哨兵即改判 ⇒ 证明无本地副本）。"""
    calls: list[Any] = []

    def _spy(key: Any) -> bool:
        calls.append(key)
        return True  # 强制走群门，验证判定结果确实被消费

    db = tmp_path / "memory.sqlite3"
    group_key = session_key_from_ids(GROUP, SENDER)
    _seed(db, session_id=group_key, text="个人向私密事实", sensitivity="personal")
    monkeypatch.setattr(memory_mod, "is_group_session_key", _spy)

    body = route_memory_command(
        "memory list",
        sender_id=SENDER,
        session_id=group_key,
        db_path=db,
    ).body

    assert calls == [group_key]
    assert "个人向私密事实" not in body  # 哨兵判群 ⇒ 群门生效


def test_engine_predicate_delegates_to_central_piece(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine._is_group_session 必须是中央件的委托（不再是本地 startswith 副本）。"""
    monkeypatch.setattr(engine_mod, "is_group_session_key", lambda key: "SENTINEL")
    assert engine_mod._is_group_session("group_1_2") == "SENTINEL"


def test_engine_group_gate_refuses_private_session_key() -> None:
    """私聊裸 uid 键不得进群门（台账 #29 私聊派发报错修复的现状保持）。"""
    assert engine_mod._is_group_session(SENDER) is False
    assert engine_mod._is_group_session(f"group_{GROUP}_{SENDER}") is True


def test_builder_symbol_still_exported_from_engine() -> None:
    """``session_key_from_ids`` 名字与语义保留（读侧 shared_group 与 F4 件在引用它）。"""
    assert session_key_from_ids(GROUP, SENDER) == session_keys.build_session_key(
        GROUP, SENDER
    )
    assert session_key_from_ids(GROUP, "") == f"group_{GROUP}_unknown"


# ---------------------------------------------------------------------------
# 4. 字节现状锁：对真实输入零差异，放宽面逐条点名
# ---------------------------------------------------------------------------

# 真实摄取层可能出现的键（OneBot V11 / TG / mail 覆写 / console / 派生成员键）。
_REAL_KEYS: list[str] = [
    f"group_{GROUP}_{SENDER}",
    "group_1076073471_3113533731",
    "group_-1001234567890_5551212",
    "group_123_thread456_789",
    SENDER,
    "1722380002",
    "private_123456",
    "channel_-100987654321",
    "email:someone@example.com",
    f"group_{GROUP}_{SENDER}||u:1722380002",
]


def _legacy_engine_rule(key: str) -> bool:
    """修复前 engine 判据的逐字内联副本（内联规格重述锚，同 report-T66 手法）。"""
    return str(key or "").startswith("group_")


def _legacy_memory_rule(session_id: str) -> bool:
    """修复前 memory 判据的逐字内联副本。"""
    return session_id.strip().lower().startswith("group:")


@pytest.mark.parametrize("key", _REAL_KEYS, ids=repr)
def test_engine_behaviour_identical_on_real_keys(key: str) -> None:
    assert engine_mod._is_group_session(key) is _legacy_engine_rule(key)


@pytest.mark.parametrize(
    "key", [k for k in _REAL_KEYS if not session_keys.is_group_session_key(k)], ids=repr
)
def test_engine_still_refuses_every_private_shaped_real_key(key: str) -> None:
    """真实私聊键一个都不能被放宽误判成群（判成群=私聊派发=生产报错面）。"""
    assert engine_mod._is_group_session(key) is False


@pytest.mark.parametrize(
    "key", [k for k in _REAL_KEYS if k.startswith("group_")], ids=repr
)
def test_memory_now_agrees_with_engine_on_group_keys(key: str) -> None:
    """同名两判据收编后必须同值——这正是本缺陷的正面反证。"""
    assert session_keys.is_group_session_key(key) is True
    assert _legacy_memory_rule(key) is False  # 旧 memory 判据在这些键上恒 False（病根）


def test_widening_surface_is_exactly_the_documented_set() -> None:
    """放宽面 = 大写形 / 两端空白形 / 冒号合成形，仅此三类（逐条点名，不许悄悄扩）。"""
    widened = [
        f"GROUP_{GROUP}_{SENDER}",
        f"  group_{GROUP}_{SENDER}  ",
        f"group:{GROUP}",
    ]
    for key in widened:
        assert session_keys.is_group_session_key(key) is True
        assert _legacy_engine_rule(key) is False
    for key in _REAL_KEYS:
        assert session_keys.is_group_session_key(key) is _legacy_engine_rule(key)


# ---------------------------------------------------------------------------
# 5. 跨件一致性：读侧前缀（F4 席修复面）与中央件不得劈叉
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group_id", [GROUP, "631785829", "123456", "1234567", f"  {GROUP}  ", None, ""])
def test_central_prefix_matches_read_side_prefix(group_id: Any) -> None:
    """`shared_group._group_prefix`（读侧）与中央 `group_session_prefix` 同值。

    0/False 这类「falsy 但非 None」群号是两侧唯一理论差异：读侧历史实现
    ``str(0)`` 会造出 ``group_0_``，中央件按 falsy 归零不给前缀。QQ 群号无 0，
    本表不纳入该值，中央口径由 ``test_session_keys_central`` 单独钉。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character import shared_group

    assert shared_group._group_prefix(group_id) == session_keys.group_session_prefix(
        group_id
    )


def test_central_builder_key_lands_in_read_side_prefix() -> None:
    """写侧键 ⊆ 读侧前缀（F4 席反证锁的中央件版本：换形必红，杜绝第三次静默分叉）。"""
    assert session_keys.build_session_key(GROUP, SENDER).startswith(
        session_keys.group_session_prefix(GROUP)
    )


# ---------------------------------------------------------------------------
# 6. 防再犯机器门（AST 全树扫描）
# ---------------------------------------------------------------------------

# 白名单外既有「拿字符串键猜群/私聊」站点基线：(相对路径, 规则族, 去空白源码行)。
# 每条都是 FIX5 取证登记、本席无权修的存量（根 __init__/echo 系禁改面；
# shared_export、meme_library_listener 在白名单外）。修法=改读契约字段或调中央件。
# **只许缩水不许长大**：某条不再命中即报陈旧，逼后来者删条目。
_LEGACY_SHAPE_GUESS_BASELINE: frozenset[tuple[str, str, str]] = frozenset(
    {
        # 2026-09-27 S-FIX-INGEST（审计 A-ING-3）：根 `_build_memory_writer` 提醒腿的
        # `session_id.partition(":")` 已收编（作用域派生改调中央
        # `session_keys.parse_session_key`，消费者零自拆），回潮由
        # `tests/test_reminder_scope_session_keys.py` 三形态锁钉死。
        # 按本门自订规程「该处已收编⇒把条目从基线删掉」摘牌。
        (
            "plugins/bot_unified_runtime/__init__.py",
            "membership",
            'elif "group" in session_id:',
        ),
        (
            "plugins/bot_unified_runtime/__init__.py",
            "membership",
            'SessionType.GROUP if "group" in session_id else SessionType.PRIVATE',
        ),
        # 2026-09-21 深读波 F-9：shared_export 的 `startswith("group:")` 已收编
        # （逐行分类改调 is_group_session_key，SQL 侧两形并列由中央件常量派生），
        # 按本门自订规程「该处已收编⇒把条目从基线删掉」摘牌。同文件的
        # `LIKE 'group:%'` SQL 半边本就在 AST 扫描面之外（V2-8 记的形态盲区），
        # 一并由 F-9 关闭；扩扫描面到 SQL 字面量是 R2-10，另案。
        (
            "plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py",
            "membership",
            'if "group" not in session_id:',
        ),
    }
)

_PREFIX_METHODS = frozenset({"startswith", "endswith", "removeprefix", "removesuffix"})
_SPLIT_METHODS = frozenset({"split", "partition", "rsplit", "rpartition"})
_LOCAL_PREDICATE_NAMES = frozenset({"_is_group_session", "is_group_session"})
_CENTRAL_PREDICATE = "is_group_session_key"  # 唯一合法判据名

# 变量名带 "session" 但指的是**会话类型/种类/范围**而非键本身——对它做等值比较
# 正是本席推荐的契约字段路（``message.session_type == "group"``），不是猜键。
_NON_KEY_SESSION_WORDS = ("type", "kind", "scope", "value", "name", "label")


def _bare_session_names(node: ast.AST) -> set[str]:
    """表达式里出现的**裸键变量名**（``session_id`` / ``session_key`` / 含二者片段）。

    属性链不计——``message.session_type`` 这类**读契约字段**是本席推荐正解
    （``rate_limit.is_group_session(message)`` 即此路），把它们一并咬红只会逼
    后来者放宽门，反而失去执法面；同理排除 ``*_type`` / ``*_kind`` / ``*_scope`` /
    ``*_value`` 这类「类型值」局部变量。
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Name):
            continue
        lowered = child.id.lower()
        if "session" not in lowered:
            continue
        if any(word in lowered for word in _NON_KEY_SESSION_WORDS):
            continue
        names.add(lowered)
    return names


def _is_group_literal(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("group")


def _scan_shape_guesses(tree: ast.AST, lines: list[str]) -> list[tuple[str, str]]:
    """返回 [(规则族, 该行源码去空白)]；三族都是「对一个裸 session_* 键做群字面量运算」。"""
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        rule: str | None = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _PREFIX_METHODS
            and node.args
            and _is_group_literal(getattr(node.args[0], "value", None))
            and _bare_session_names(node.func.value)
        ):
            rule = "prefix"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SPLIT_METHODS
            and _bare_session_names(node.func.value)
            and any(getattr(arg, "value", None) == ":" for arg in node.args)
        ):
            rule = "split"
        elif isinstance(node, ast.Compare) and _bare_session_names(node) and any(
            _is_group_literal(getattr(operand, "value", None))
            for operand in (node.left, *node.comparators)
        ):
            # 覆盖 ``"group" in session_id`` 与 ``session_id == "group…"`` 两种写法。
            rule = "membership"
        if rule:
            text = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else "?"
            found.append((rule, text))
    return found


def _all_plugin_files() -> list[Path]:
    files = sorted(PLUGINS_ROOT.rglob("*.py"))
    assert len(files) > 300, f"扫描路径退化（仅 {len(files)} 文件），机器门失去执法面"
    return files


def _relpath(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_no_new_string_key_shape_guesses_outside_central_piece() -> None:
    """全仓扫描：再写「字符串键猜群/私聊」的本地判据即红（含根 __init__ 与垫片）。"""
    offenders: set[tuple[str, str, str]] = set()
    for path in _all_plugin_files():
        rel = _relpath(path)
        if rel == CENTRAL_FILE:
            continue  # 唯一合法判据所在地
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for rule, text in _scan_shape_guesses(ast.parse(source), lines):
            offenders.add((rel, rule, text))
    fresh = offenders - _LEGACY_SHAPE_GUESS_BASELINE
    stale = _LEGACY_SHAPE_GUESS_BASELINE - offenders
    assert not fresh, (
        "新增本地键形态判据（必须改调 "
        f"domains/core/session_keys.py::{_CENTRAL_PREDICATE}）：{sorted(fresh)}"
    )
    assert not stale, f"基线已陈旧（该处已收编，请把条目从基线删掉）：{sorted(stale)}"


def test_audited_consumers_hold_zero_local_shape_tests() -> None:
    """两条案发文件必须零命中——本席修复的正面反证（回潮即红）。"""
    for rel in (MEMORY_FILE, ENGINE_FILE):
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        hits = _scan_shape_guesses(ast.parse(source), source.splitlines())
        assert hits == [], f"{rel} 又长出本地键形态判据：{hits}"


def test_local_predicate_definitions_must_delegate() -> None:
    """首参名含 session/key 的 `_is_group_session` 定义，只许在中央件或由它委托。"""
    offenders: list[str] = []
    for path in _all_plugin_files():
        rel = _relpath(path)
        if rel == CENTRAL_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _LOCAL_PREDICATE_NAMES:
                continue
            first = [a.arg for a in (*node.args.posonlyargs, *node.args.args)][:1]
            if not first or not (
                "session" in first[0].lower() or "key" in first[0].lower()
            ):
                continue  # 契约字段路（rate_limit.is_group_session(message)），另一族
            referenced = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            if _CENTRAL_PREDICATE not in referenced:
                offenders.append(f"{rel}:{node.lineno} {node.name}")
    assert offenders == [], f"本地群键谓词未委托中央件：{offenders}"


def test_both_audited_files_import_the_central_piece() -> None:
    """中央件必须有生产落点（防「专属测试背书的死模块」）。"""
    for rel in (MEMORY_FILE, ENGINE_FILE):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        imported = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "plugins.bot_unified_runtime.domains.core.session_keys" in imported, (
            f"{rel} 未接中央件"
        )
        assert _CENTRAL_PREDICATE in names or "build_session_key" in names, (
            f"{rel} 导入了中央件却没取谓词/构造器"
        )


def test_engine_group_gate_end_to_end_still_refuses_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：私聊会话键过 `maybe_react_on_message` 必须 False 且绝不触达派发。"""
    calls: list[Any] = []

    async def _spy_react(bot: Any, *, message_id: str, emoji_id: int) -> bool:
        calls.append((message_id, emoji_id))
        return True

    monkeypatch.setattr(engine_mod, "react_to_message", _spy_react)
    verdict = asyncio.run(
        engine_mod.maybe_react_on_message(
            object(),
            session_key=SENDER,  # 私聊裸 uid
            user_message_id="1234",
            text="今天有点难过",
            config=SimpleConfig(),
            trigger="after_reply",
            gate=ProactiveGate(),
        )
    )
    assert verdict is False
    assert calls == []


def test_engine_group_gate_end_to_end_allows_group_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端正例：群键必须能过群门并触达派发（防「两边一起判死」的假绿）。"""
    calls: list[Any] = []

    async def _spy_react(bot: Any, *, message_id: str, emoji_id: int) -> bool:
        calls.append((message_id, emoji_id))
        return True

    monkeypatch.setattr(engine_mod, "react_to_message", _spy_react)
    verdict = asyncio.run(
        engine_mod.maybe_react_on_message(
            object(),
            session_key=f"group_{GROUP}_{SENDER}",
            user_message_id="1234",
            text="这条进度已经推上去了",  # 非悲伤词族（after_reply 的 C1 悲伤门会另判否）
            config=SimpleConfig(),
            trigger="after_reply",
            gate=ProactiveGate(),
        )
    )
    assert verdict is True
    assert calls == [("1234", calls[0][1])]
