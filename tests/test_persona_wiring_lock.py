"""人格热切换「根装配缝」活性锁 + 离线端到端下发证明（席位 S-PERSONA-WIRE）。

两腿缺一不可：

1. **结构腿（AST，零 import 判装配）**：根 ``plugins/bot_unified_runtime/__init__.py``
   的 ``_handle_status`` 里，「``persona switch`` 命令 → 外观下发 helper」这条缝必须
   真实接在共享派发尾 ``receipt = await _run_capability_through_pipeline(...)`` 之后、
   且被 ``capability_id == "bot.runtime"`` ∧ ``receipt.state.value == "sent"`` 双判据
   罩住。装配被摘 = 功能 1 线上零生效而 persona_profile 本体测试照绿（台账 #45/#47/#50
   「机制在但装配落空」同型病；先例锁＝tests/test_coalescing_wiring_lock.py）。
2. **行为腿（fake bot/假 adapter，禁真机）**：直接驱动被接线的那枚
   ``_dispatch_persona_appearance_if_switched``——切 persona→profile 各字段经
   ``bot.call_api`` 落到假通道→再切回 default 按册恢复主人格外观；驳回态静默、
   未入册点名、半切态点名「哪几项已落/没落」（H-1/H-2 裁定逐条钉死）。

注毒全在**内存里的源码字符串副本**上做，真实文件零字节改动；每条变异先自证
"确实改动了"，防注毒退化成空跑。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

HANDLER_NAME = "_handle_status"
HELPER_NAME = "_dispatch_persona_appearance_if_switched"


def _root_source() -> str:
    return ROOT_INIT.read_text(encoding="utf-8")


def _loads(source: str, origin: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(
            f"{origin} 第 {exc.lineno} 行语法错——该件大概率正被别的席半写，"
            "等 60 秒复跑再判定；本锁只读它、不写它"
        ) from exc


def _status_handler(source: str) -> ast.AsyncFunctionDef:
    tree = _loads(source, "根 __init__.py")
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == HANDLER_NAME
    ]
    assert len(found) == 1, f"根里 {HANDLER_NAME} 应恰一枚，实={len(found)}"
    return found[0]


def _seam_call(handler: ast.AsyncFunctionDef) -> ast.Call:
    """定位那枚外观下发缝调用（应恰一枚、被 await、实参全为 Name）。"""
    awaits = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == HELPER_NAME
    ]
    assert len(awaits) == 1, (
        f"{HELPER_NAME} 的 await 缝应恰一处，实={len(awaits)}"
        "（0=装配被摘，线上切人格只切语气不跟外观）"
    )
    call = awaits[0].value
    assert isinstance(call, ast.Call)  # mypy 收窄
    return call


def check_seam_awaited_with_live_args(src: str) -> None:
    """缝必须 await，且把活 bot/event/config/command_text/settings_manager/actor_roles 递进去。

    S-FIX-PERSONA-HS 跟随补丁（2026-09-28 判卷）：HEAD `6a8a97b`（S-ATK-PERSONA P-G1
    角色门）给缝加了 `actor_roles` 一枚，本锁当时仍钉五参形态⇒结构腿假红
    （根因已由 S-CENSUS-PERSONA §三钉死：不是脏树在飞，是锁没跟改）。角色门
    形态本身自此入册——**摘掉 actor_roles 实参＝拆 P-G1 咽喉，本锁必须红**。
    handler 作用域里角色读数活变量名＝`persona_gate_roles`（装配席取中央角色面
    回读，非同名恒等例外），其余实参仍须同名原样接。
    """
    call = _seam_call(_status_handler(src))
    kwargs = {kw.arg for kw in call.keywords if kw.arg is not None}
    assert kwargs == {
        "bot",
        "event",
        "config",
        "command_text",
        "settings_manager",
        "actor_roles",
    }, f"缝的实参形状变了：{sorted(kwargs)}"
    for kw in call.keywords:
        expected = "persona_gate_roles" if kw.arg == "actor_roles" else kw.arg
        assert isinstance(kw.value, ast.Name) and kw.value.id == expected, (
            f"缝实参 {kw.arg} 必须原样接作用域里的 {expected}（写死/换对象=假接线）"
        )


def check_seam_predicate_is_capability_and_sent(src: str) -> None:
    """判据双 conjunct 必须真的在缝外层 If 的 test 里，且不被常量钉死。

    只认 ``capability_id == "bot.runtime"`` ∧ ``receipt.state.value == "sent"``：
    摘掉任一 conjunct 或换成裸常量（永假）都算装配失效——H-2 裁定外观只由
    显式切换命令驱动，而 sent 语义由 helper 的 override 读回兜底（另锁）。
    """
    handler = _status_handler(src)
    call = _seam_call(handler)
    # 取包裹缝调用的**最近**一层 If（lineno 最大的祖先 If ⇒ 最内层判据）
    outer: ast.If | None = None
    best_line = -1
    for node in ast.walk(handler):
        if (
            isinstance(node, ast.If)
            and node.lineno > best_line
            and any(child is call for child in ast.walk(node))
        ):
            outer = node
            best_line = node.lineno
    assert outer is not None, "缝调用不在任何 If 里 = 判据被摘，外观腿会无条件乱发"
    conjs = outer.test.values if isinstance(outer.test, ast.BoolOp) else [outer.test]
    joined = " ".join(ast.unparse(c) for c in conjs).replace("'", '"')
    assert 'capability_id == "bot.runtime"' in joined, (
        f"判据缺 capability_id == bot.runtime：{joined}"
    )
    assert 'receipt.state.value == "sent"' in joined, (
        f"判据缺 receipt.state.value == sent：{joined}"
    )
    for value in conjs:
        assert not isinstance(value, ast.Constant), (
            f"判据里出现裸常量合取项（永真/永假都能骗过存在性检查）：{joined}"
        )
    # 缝必须在共享派发尾 receipt 赋值**之后**（接线点 A 的定义性事实）
    receipt_assigns = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "receipt" for t in node.targets
        )
        and isinstance(node.value, ast.Await)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Name)
        and node.value.value.func.id == "_run_capability_through_pipeline"
    ]
    assert receipt_assigns, "找不到 receipt = await _run_capability_through_pipeline 派发尾"
    assert min(receipt_assigns) < outer.lineno, (
        f"缝（行 {outer.lineno}）不再晚于派发尾（行 {receipt_assigns}）＝接错了位置"
    )


def check_override_confirmation_in_helper() -> None:
    """helper 源里必须有「读回 runtime override 再放行外观腿」的确认（不信 sent 语义）。

    驳回/报错路径的 receipt 同样是 sent——没有这道确认，非管理员的一句
    「runtime persona switch x」被拒后外观照切 = 假随切（H-1 精神违规）。
    """
    import inspect

    import plugins.bot_unified_runtime as root

    source = inspect.getsource(getattr(root, HELPER_NAME))
    assert "get_persona_override" in source, "helper 缺 override 读回确认"
    assert "settings_manager.get" in source, "helper 的确认没走主链同款实例口径"
    # 只钉调用形态（与上一席 test_no_plugin_code_uses_get_login_info 同判据），
    # 文档串里作为散文提及不算违规。
    needles = ('"get_login_info"', "'get_login_info'", "get_login_info(")
    assert not any(needle in source for needle in needles), (
        "外观腿禁读 get_login_info（台账 #60：其自身身份缓存改后不刷新）"
    )


def check_helper_single_dispatch_outlet() -> None:
    """全根 ``apply_persona_profile`` 调用点恰一枚，且出站只经 bot.call_api 形状。"""
    tree = _loads(_root_source(), "根 __init__.py")
    hits = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_persona_profile"
    ]
    assert len(hits) == 1, f"apply_persona_profile 调用点应全根唯一（唯一下发口 H-1），实={hits}"
    helper_def = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == HELPER_NAME
    )
    lam = [
        node
        for node in ast.walk(helper_def)
        if isinstance(node, ast.Lambda)
        and any(
            isinstance(c, ast.Attribute) and c.attr == "call_api"
            for c in ast.walk(node)
        )
    ]
    assert len(lam) == 1, f"helper 里 bot.call_api 适配器应恰一枚 lambda，实={len(lam)}"


# ---------------------------------------------------------------------------
# 结构腿：现网源码逐件在位
# ---------------------------------------------------------------------------


def test_seam_is_wired_with_live_args() -> None:
    check_seam_awaited_with_live_args(_root_source())


def test_seam_predicate_and_position() -> None:
    check_seam_predicate_is_capability_and_sent(_root_source())


def test_helper_confirms_override_before_dispatch() -> None:
    check_override_confirmation_in_helper()


def test_helper_is_the_single_dispatch_caller() -> None:
    check_helper_single_dispatch_outlet()


# ---------------------------------------------------------------------------
# 注毒自证（内存副本，真身零改动）：摘缝/钉假判据 ⇒ 锁必红
# ---------------------------------------------------------------------------


def _drop_seam_call(src: str) -> str:
    """摘掉整枚缝（判据 if 行 + await 调用直至其闭括号行），副本仍是合法源码。"""
    lines = src.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if f"await {HELPER_NAME}(" in line]
    assert len(hits) == 1, f"缝目标命中 {len(hits)} 处，判据不唯一"
    end = hits[0]
    depth = 0
    while end < len(lines):
        depth += lines[end].count("(") - lines[end].count(")")
        if depth <= 0:
            break
        end += 1
    start = hits[0] - 1
    while start >= 0 and not lines[start].lstrip().startswith("if "):
        start -= 1
    assert start >= 0 and 'capability_id == "bot.runtime"' in lines[start], (
        "找不到缝的判据 if 行 = 判据形状变了，注毒归因失效"
    )
    del lines[start : end + 1]
    out = "".join(lines)
    assert f"await {HELPER_NAME}(" not in out, "注毒未生效（等于空跑）"
    return out


def _replace_once(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"注毒目标命中 {src.count(old)} 次，判据不唯一"
    out = src.replace(old, new)
    assert out != src, "注毒未生效（等于空跑）"
    return out


def test_kill_power_dropping_the_seam_turns_lock_red() -> None:
    src = _drop_seam_call(_root_source())
    _loads(src, "注毒①副本")  # 摘句后仍是合法源码：红必须来自判据，不是字符串手术
    with pytest.raises(AssertionError):
        check_seam_awaited_with_live_args(src)
    with pytest.raises(AssertionError):
        check_seam_predicate_is_capability_and_sent(src)


def test_kill_power_constant_pinned_predicate_turns_lock_red() -> None:
    src = _replace_once(
        _root_source(),
        'if capability_id == "bot.runtime" and receipt.state.value == "sent":',
        'if False and capability_id == "bot.runtime" and receipt.state.value == "sent":',
    )
    _loads(src, "注毒②副本")
    with pytest.raises(AssertionError):
        check_seam_predicate_is_capability_and_sent(src)


def test_kill_power_moved_before_receipt_turns_lock_red() -> None:
    """把缝整体搬回派发尾**之前**：判据、调用都在，位置错 ⇒ 位置锁必须红。"""
    src = _root_source()
    lines = src.splitlines(keepends=True)
    seam_start = next(
        i for i, line in enumerate(lines) if line.lstrip().startswith("# ---- PERSONA-HOT 装配腿")
    )
    seam_end = next(
        i for i, line in enumerate(lines) if f"await {HELPER_NAME}(" in line
    )
    while not lines[seam_end].strip().startswith(")"):
        seam_end += 1
    block = lines[seam_start : seam_end + 1]
    del lines[seam_start : seam_end + 1]
    anchor = next(
        i
        for i, line in enumerate(lines)
        if "receipt = await _run_capability_through_pipeline(" in line
        and i > 8000
    )
    lines[anchor:anchor] = block
    out = "".join(lines)
    assert out != src, "注毒未生效（等于空跑）"
    _loads(out, "注毒③副本")
    with pytest.raises(AssertionError):
        check_seam_predicate_is_capability_and_sent(out)


def test_kill_power_dropping_actor_roles_kwarg_turns_lock_red() -> None:
    """S-FIX-PERSONA-HS 跟随补丁（P-G1 角色门入册，2026-09-28）：

    摘掉缝的 ``actor_roles=persona_gate_roles`` 实参＝拆 P-G1 咽喉——helper
    顶部角色门收到 ``None`` 即静默，外观腿线上永不动作，而 persona_profile
    本体测试照绿（台账 #45/#47/#50「机制在但装配落空」同型病）。结构腿
    必须为此而红，不许退化成只数旧五参。
    """
    src = _replace_once(
        _root_source(),
        "                actor_roles=persona_gate_roles,\n",
        "",
    )
    _loads(src, "注毒④副本")
    with pytest.raises(AssertionError):
        check_seam_awaited_with_live_args(src)


# ---------------------------------------------------------------------------
# 行为腿：端到端离线热切换（fake bot 记调用，禁真机外发）
# ---------------------------------------------------------------------------

from plugins.bot_unified_runtime import _dispatch_persona_appearance_if_switched
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRegistry,
)


class _FakeBot:
    """记录 call_api/send 的假 bot：唯一出站口径被录成流水，绝不触网。"""

    def __init__(self, *, fail_actions: tuple[str, ...] = ()) -> None:
        self.api_calls: list[tuple[str, dict]] = []
        self.sent: list[str] = []
        self._fail = set(fail_actions)

    async def call_api(self, api: str, **data: Any) -> dict:
        self.api_calls.append((api, data))
        if api in self._fail:
            return {"retcode": 1001, "message": "模拟拒绝"}
        return {"retcode": 0, "data": {}}

    async def send(self, target: Any, message: str) -> None:
        self.sent.append(message)


class _FakeConfig:
    bot_persona_profile_id = "shorekeeper"
    bot_runtime_instance = ""


class _FakeStore:
    def __init__(self, override: str) -> None:
        self._override = override

    def get_persona_override(self) -> str:
        return self._override


class _FakeManager:
    def __init__(self, override: str) -> None:
        self.got: list[str] = []
        self._store = _FakeStore(override)

    def get(self, instance: str) -> _FakeStore:
        self.got.append(instance)
        return self._store


def _write_profile(registry_dir: Path, persona_id: str, payload: dict) -> Path:
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"{persona_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _tmp_registry(tmp_path: Path, *, avatar_bytes: bool = True) -> PersonaProfileRegistry:
    reg_dir = tmp_path / "registry"
    _write_profile(
        reg_dir,
        "shorekeeper",
        {
            "persona_id": "shorekeeper",
            "display_name": "守岸人",
            "is_main": True,
            "qq": {"nickname": "守岸人", "signature": "因你而有的意义", "avatar_path": ""},
        },
    )
    danya_avatar = ""
    if avatar_bytes:
        avatar = tmp_path / "avatar" / "danya.jpg"
        avatar.parent.mkdir(parents=True, exist_ok=True)
        avatar.write_bytes(b"\xff\xd8fake-jpg")
        danya_avatar = str(avatar)
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "is_main": False,
            "qq": {"nickname": "达妮娅", "signature": "贪恋一小簇微光", "avatar_path": danya_avatar},
            # ②文本腿收编后端到端判据：在册带设定清单 ⇒ 文本腿 ok，"已切换"才成立；
            # 空清单人格的"已切换"谎面由 test_persona_hot_switch 3b 组锁反向钉死。
            "files": {"settings": ["core.md"], "knowledge": []},
        },
    )
    danya_dir = tmp_path / "danya"  # F-D 锚根＝registry 父目录/persona_id
    danya_dir.mkdir(parents=True, exist_ok=True)
    (danya_dir / "core.md").write_text("达妮娅设定正文（测试在册件）。", encoding="utf-8")
    return PersonaProfileRegistry(reg_dir)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture
def persona_outbound_policy(tmp_path: Path) -> Path:
    """S-FIX-PERSONA-R2（F-C）：装载/下发头像问 paths.py 唯一闸。行为锁要钉在
    「闸认可 ⇒ 真的走到下发」这条腿上——用 paths 件文档化的测试注入口
    ``set_default_policy`` 把判定根注成本 tmp 树（teardown 复位 None 惰性重建），
    不是放宽守卫。
    """
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        yield tmp_path
    finally:
        paths.set_default_policy(None)


def test_hot_switch_roundtrip_dispatches_appearance_and_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persona_outbound_policy: Path
) -> None:
    """热切换端到端（离线）：切 danya→profile 各字段真经 bot.call_api 下发→切回 default 恢复主人格外观。"""
    cards: list[str] = []
    monkeypatch.setattr(pp, "_default_card_avatar_hook", cards.append)
    registry = _tmp_registry(tmp_path)
    bot = _FakeBot()
    config = _FakeConfig()

    # 第一腿：switch danya（主链回执已 sent，override 已落 danya）
    # S-FIX-PERSONA-HS 跟随补丁：行为腿一律带 super_admin 角色——不带则 P-G1
    # 角色门先静默，本腿测的就不是下发面而是门（门的专测见文末专腿）。
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=config,
            command_text="runtime persona switch danya",
            settings_manager=_FakeManager("danya"),
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    actions = [name for name, _ in bot.api_calls]
    assert actions == ["set_qq_profile", "set_qq_avatar"], f"下发序列不对：{actions}"
    profile_params = dict(bot.api_calls[0][1])
    assert profile_params == {"nickname": "达妮娅", "personal_note": "贪恋一小簇微光"}
    assert bot.api_calls[1][1]["file"]  # 头像参数带解析后的路径
    assert cards == [bot.api_calls[1][1]["file"]]  # 卡片头像在 QQ 头像落地后跟随
    assert "已切换人格「danya」" in bot.sent[-1]
    assert "人格文本" in bot.sent[-1]  # 四格逐项点名，文本腿在场（H-1）

    # 第二腿：switch default ⇒ 按册恢复主人格（shorekeeper）外观，头像不表态即不切
    bot2 = _FakeBot()
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot2,
            event=object(),
            config=config,
            command_text="runtime persona switch default",
            settings_manager=_FakeManager(""),
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    assert [name for name, _ in bot2.api_calls] == ["set_qq_profile"]
    assert dict(bot2.api_calls[0][1]) == {
        "nickname": "守岸人",
        "personal_note": "因你而有的意义",
    }
    assert "已切换人格「shorekeeper」" in bot2.sent[-1]


def test_denied_switch_keeps_appearance_leg_silent(tmp_path: Path) -> None:
    """非管理员/报错路径的驳回同样回执 sent——override 读不平 ⇒ 外观腿零调用零追加。"""
    registry = _tmp_registry(tmp_path, avatar_bytes=False)
    bot = _FakeBot()
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch danya",
            settings_manager=_FakeManager(""),  # 切换没落地：override 仍是旧值
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    assert bot.api_calls == []
    assert bot.sent == []


def test_unregistered_persona_names_honestly(tmp_path: Path) -> None:
    """override 落了但人格未入册（兼容位老 persona）⇒ 点名「仅切换了语气，外观未改」。"""
    registry = _tmp_registry(tmp_path, avatar_bytes=False)
    bot = _FakeBot()
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch legacy",
            settings_manager=_FakeManager("legacy"),
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    assert bot.api_calls == []
    assert len(bot.sent) == 1 and "未入人格册" in bot.sent[0] and "外观未改" in bot.sent[0]


def test_half_switch_names_landed_and_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persona_outbound_policy: Path
) -> None:
    """头像一发被拒 ⇒ 回执点名「未完全切换——已落地/未落地」，卡片头像绝不跟随（H-1）。"""
    cards: list[str] = []
    monkeypatch.setattr(pp, "_default_card_avatar_hook", cards.append)
    registry = _tmp_registry(tmp_path)
    bot = _FakeBot(fail_actions=("set_qq_avatar",))
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch danya",
            settings_manager=_FakeManager("danya"),
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    assert [name for name, _ in bot.api_calls] == ["set_qq_profile", "set_qq_avatar"]
    assert cards == []
    summary = bot.sent[-1]
    assert "未完全切换" in summary and "QQ头像" in summary
    assert "已切换人格" not in summary  # 半切态绝不宣称成功


def test_non_switch_runtime_commands_never_dispatch(tmp_path: Path) -> None:
    """H-2：list/缺 target/非 persona 命令形一律静默，外观只随显式 switch。"""
    registry = _tmp_registry(tmp_path, avatar_bytes=False)
    manager = _FakeManager("danya")
    for command in (
        "runtime persona list",
        "runtime persona switch",
        "runtime mood set 0.5",
        "status",
    ):
        bot = _FakeBot()
        _run(
            _dispatch_persona_appearance_if_switched(
                bot=bot,
                event=object(),
                config=_FakeConfig(),
                command_text=command,
                settings_manager=manager,
                registry=registry,
                actor_roles=["super_admin"],
            )
        )
        assert bot.api_calls == [] and bot.sent == [], f"命令 {command!r} 不该触发外观腿"
    assert manager.got == []  # 命令形不符时连 override 读回都不该发生


def test_dispatch_failure_names_error_not_silence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """下发腿自身炸了（如头像解析件坏了）也必须点名中断，绝不沉默冒充成功。"""

    registry = _tmp_registry(tmp_path)
    record = registry.get("danya")
    assert record is not None

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("解析器爆炸")

    monkeypatch.setattr(pp, "apply_persona_profile", _boom)
    # helper 里是函数级懒导 apply_persona_profile，直接 patch 模块属性不生效于
    # 已捕获引用？——不是：懒导在**每次调用时**执行 from … import，patch 模块属性
    # 即被重导捕获，故本断言测的就是真实捕获路径。
    bot = _FakeBot()
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch danya",
            settings_manager=_FakeManager("danya"),
            registry=registry,
            actor_roles=["super_admin"],
        )
    )
    assert bot.api_calls == []
    assert len(bot.sent) == 1
    assert "外观下发中断" in bot.sent[0] and "一项未落地" in bot.sent[0]
    assert "已切换" not in bot.sent[0]


# ---------------------------------------------------------------------------
# 行为腿·P-G1 角色门专测（S-ATK-PERSONA 2026-09-27 落码，本席 2026-09-28 上锁）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("roles", (["user"], ["member", "observer"], [], None))
def test_non_admin_roles_gate_is_silent_even_when_fully_qualifying(
    tmp_path: Path, roles: list[str] | None
) -> None:
    """P-G1：一切其余条件都满足（命令形好、override 读回相符、人格在册带头像），
    唯独角色不含 admin/super_admin ⇒ helper 顶部即静默。

    这条腿把「静默」唯一归因到角色门本身：同款状态在 roundtrip 腿里必发
    （test_hot_switch_roundtrip…），此处零 api、零追加回执，且 helper 的门在
    override 读回**之前**——连 settings_manager 都不该被碰（防越权者用复读
    驱动 bot 账号级资料写，台账 #60 同源威胁模型）。
    """
    registry = _tmp_registry(tmp_path)
    bot = _FakeBot()
    manager = _FakeManager("danya")  # override 与命令目标一致：非门因的其它静默都排除
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch danya",
            settings_manager=manager,
            registry=registry,
            actor_roles=roles,
        )
    )
    assert bot.api_calls == [], f"角色 {roles!r} 不该驱动外观下发"
    assert bot.sent == [], f"角色 {roles!r} 不该追加任何回执"
    assert manager.got == [], "P-G1 门应在 override 读回之前静默，绝不触主链实例读数"


def test_admin_role_variant_lowercase_still_passes_gate(
    tmp_path: Path, persona_outbound_policy: Path
) -> None:
    """角色归因反向腿：门是小写归一的——"ADMIN" 同样放行（防止把门锁成大小写敏感
    的假安全：线上角色面若吐大写名，外观腿绝不能因此静默成"没做"）。
    """
    registry = _tmp_registry(tmp_path, avatar_bytes=False)
    bot = _FakeBot()
    _run(
        _dispatch_persona_appearance_if_switched(
            bot=bot,
            event=object(),
            config=_FakeConfig(),
            command_text="runtime persona switch danya",
            settings_manager=_FakeManager("danya"),
            registry=registry,
            actor_roles=["ADMIN"],
        )
    )
    assert [name for name, _ in bot.api_calls] == ["set_qq_profile"]
    assert "已切换人格「danya」" in bot.sent[-1]
