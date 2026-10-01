"""默认讲法腿的**接线锁**（S-DEFAULTLEG-WIRE，2026-09-29 凌晨）。

要防的形态是本仓反复栽过的「键加了、消费缺」：`bot_reply_default_directives` 在
`config.py` 在册、`reply_policy_section_for_turn(config=…)` 也接了参，但**构造链没把
config 交到能力层** ⇒ `getattr(None, "bot_reply_default_directives", "")` 恒空 ⇒
没表过态的用户整段拿不到默认讲法，而代码看着像接好了。同一枚 config 句柄还喂着
`build_chat_capability` 里策略 store 的懒建腿（`chat.py` 的
`if effective_reply_policy_store is None and content_route_config is not None`）⇒
不交参数就是**两条腿一起静默关**。

判据分层（都走真入口，不在测试里直调编排函数、不把生产实参抄一遍）：

① 行为腿：真 `build_chat_capability` → 一轮对话 → provider **实收**的提示词里出现
   块首【对方的长期沟通偏好】且含默认修辞码（这个人从未表过态、库里一行都没有）；
② 消费口腿：`chat` 交给 `reply_policy_section_for_turn` 的 `config=` 必须**就是**装配
   时交进来的那枚 `content_route_config`（对象同一性）——删掉 `chat.py` 的 `config=`
   传参这一条必红；
③ 负例腿：不交 config ⇒ 整块消失（证明①测的是接线，不是恒真）；
④ 懒建腿：不显式注 store 时，store 必须由那枚 config 懒建出来（对照例＝不交 config
   时懒建口一次都不被问）；
⑤ 运维构造链腿：真 `run_backend_unit` 跑一轮，断言渲染口收到 config，且这条离线工具路
   把策略 store 与检索竖源都钉关（否则测试跑它＝写生产库、单跑它＝发外网请求）；
⑥ 构造链名册腿：`plugins/` 下每一处 `build_chat_capability(...)` 构造点都必须交参数
   （含 backend_unit 的 `**capability_kwargs` 形态），注毒自证证明它咬得住；
⑦ 传参形态腿：`chat.py` 渲染口那一行的 `config=` 取值必须是 `content_route_config`
   （AST 判，摘掉那一行的注毒在内存里做，不改 chat.py 本体）。

卫生红线：⚠ `.env` 的 `BOT_RUNTIME_DATA_DIR` 指向**生产** Runtime 根，`tests/conftest.py`
只守源码树 `data/`——凡可能走到 `shared_reply_policy_store` 的例都必须显式 monkeypatch
它，store 一律 tmp_path 自建；本件不碰生产库、不往源码树落文件。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.character import reply_policy as rp
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
    person_reply_policy_key,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = _REPO_ROOT / "plugins"

#: 从没表过态的人 + 与「以后怎么回复我」无关的一句话（既不打判定线也不写库）。
STRANGER = "9000000002"
NEUTRAL_QUESTION = "守岸人与黑海岸是什么关系"

#: 块首真身（唯一事实源在 chat.py，本件只引用不另写一份）。
HEADER = chat.POLICY_SECTION_HEADER
#: 默认讲法的引导行（必须**自报是默认**，见 reply_policy 的 `_DEFAULT_DIRECTIVE_LEAD`）。
DEFAULT_LEAD = rp._DEFAULT_DIRECTIVE_LEAD
#: 生产缺省那份修辞码（`config.py` 的 `bot_reply_default_directives`）。
DEFAULT_CODES = ("literary_prose", "imagery_rich")


class RecordingProvider:
    """录制 provider：记下每次实收的 messages（提示词唯一判据面）。"""

    def __init__(self, text: str = "海边月色很好。") -> None:
        self.text = text
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **kwargs):
        from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
            LLMReply,
        )

        self.calls.append([dict(item) for item in messages])
        return LLMReply(text=self.text, provider="rec", model="rec", confidence=0.0)

    @property
    def prompt(self) -> str:
        if not self.calls:
            return ""
        return "\n".join(str(item.get("content") or "") for item in self.calls[-1])


def _message(sender: str = STRANGER) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="b",
        session_id=f"private_{sender}",
        session_type=SessionType.PRIVATE,
        sender_id=sender,
        plain_text=NEUTRAL_QUESTION,
        mentions_bot=False,
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=message.session_type,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        context_budget=12000,
        decision_reason="default-leg-wiring-lock",
    )


def _hermetic_store(tmp_path: Path) -> ReplyPolicyStore:
    """tmp_path 自建 store（真库文件，只在 tmp 树里）。

    ⚠ 这只解决「显式注 store」的那半；走到懒建口的例必须**另外** monkeypatch
    `rp.shared_reply_policy_store`——`.env` 的 BOT_RUNTIME_DATA_DIR 指生产根，
    conftest 只守源码树 `data/`（本仓 2026-09-28 已踩过一次写进生产库）。
    """
    return ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")


def _config(**overrides: Any) -> Config:
    config = Config(_env_file=None)
    return config.model_copy(update=overrides) if overrides else config


def _run_turn(
    tmp_path: Path,
    *,
    config: Config | None,
    store: ReplyPolicyStore | None = None,
    sender: str = STRANGER,
) -> RecordingProvider:
    """走**真能力入口**跑一轮，返回录制 provider（提示词在它手里）。"""
    provider = RecordingProvider()
    capability = chat.build_chat_capability(
        NullCharacterContextProvider(),
        provider,
        reply_detail="detail",
        reply_policy_store=_hermetic_store(tmp_path) if store is None else store,
        content_route_config=config,
    )
    message = _message(sender)
    capability(message, _decision(message))
    assert provider.calls, "能力根本没走到 provider ⇒ 本例是空跑"
    return provider


# ---------------------------------------------------------------------------
# ① 行为腿：没表过态的人，走真入口也拿到默认讲法
# ---------------------------------------------------------------------------


def test_stranger_gets_default_policy_block_via_real_capability(tmp_path: Path) -> None:
    store = _hermetic_store(tmp_path)
    provider = _run_turn(tmp_path, config=_config(), store=store)
    prompt = provider.prompt

    assert HEADER in prompt, f"默认讲法整段没进提示词 ⇒ 接线断了（块首：{HEADER}）"
    assert DEFAULT_LEAD in prompt, "偏好段没自报是默认＝替模型伪造「这个人说过他喜欢文学化」"
    for code in DEFAULT_CODES:
        assert code in prompt, f"默认修辞码 {code} 没被喂出去"
    # 这块必须来自默认腿，不是来自这个人的行（他从没表过态）。
    assert store.get(person_reply_policy_key(sender_id=STRANGER)) is None, (
        "库里凭空多出这人的行 ⇒ 测的就不是默认腿"
    )
    assert provider.calls and all(
        str(call[0].get("content") or "") != rp.LLM_JUDGMENT_SYSTEM_PROMPT
        for call in provider.calls
    ), "无关句不该花判定调用（本例只测默认腿）"


def test_config_default_for_the_leg_is_registered_on_and_open() -> None:
    """缺省值本身是这条腿存在的前提：键在册、缺省为开。"""
    assert _config().bot_reply_default_directives.strip(), (
        "config.py 的缺省被写成空 ⇒ 默认腿在生产也拿不到指令，本件的判据要跟着改口径"
    )
    assert "bot_reply_default_directives" in Config.model_fields


# ---------------------------------------------------------------------------
# ② 消费口腿：section 构造器实收的 config 必须就是装配交进来那枚
# ---------------------------------------------------------------------------


def test_render_seam_receives_the_assembled_config_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """删掉 `chat.py` 渲染口的 `config=content_route_config` 这一行，本例必红。"""
    config = _config()
    store = _hermetic_store(tmp_path)
    seen: list[dict[str, Any]] = []
    real = rp.reply_policy_section_for_turn

    def spy_section(policy, **kwargs):
        seen.append(kwargs)
        return real(policy, **kwargs)

    monkeypatch.setattr(chat, "reply_policy_section_for_turn", spy_section)
    provider = _run_turn(tmp_path, config=config, store=store)

    assert seen, "渲染口一次都没调用 section 构造器 ⇒ 接线不在本例判据面上"
    got = seen[-1]
    assert got.get("config") is config, (
        f"渲染口收到的 config 不是装配那枚（实收 {type(got.get('config'))}）"
        "⇒ 删了 `config=` 传参或另建了第二份口径"
    )
    assert got.get("store") is store, "store 没同源于装配件"
    assert got.get("person_key") == person_reply_policy_key(sender_id=STRANGER)
    assert HEADER in provider.prompt


# ---------------------------------------------------------------------------
# ③ 负例腿：不交 config ⇒ 整段消失（证明①不是恒真）
# ---------------------------------------------------------------------------


def test_block_disappears_when_config_is_not_passed(tmp_path: Path) -> None:
    """这条是①的对照：把构造链的 `content_route_config=` 摘掉就是这个形状。"""
    provider = _run_turn(tmp_path, config=None, store=_hermetic_store(tmp_path))
    assert HEADER not in provider.prompt, (
        "没交 config 也还有偏好段 ⇒ 另有第二处渲染口，①的判据不再唯一"
    )
    assert DEFAULT_LEAD not in provider.prompt


# ---------------------------------------------------------------------------
# ④ 懒建腿：只交 config、不显式注 store ⇒ store 由同一枚 config 建出来
# ---------------------------------------------------------------------------


def test_lazy_store_is_built_from_the_same_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`chat.py` 的策略 store 懒建腿与默认讲法腿共用同一枚 config 句柄。"""
    real = _hermetic_store(tmp_path)
    received: list[Any] = []

    def fake_shared_store(config: Any) -> ReplyPolicyStore:
        received.append(config)
        return real

    monkeypatch.setattr(rp, "shared_reply_policy_store", fake_shared_store)
    config = _config()
    provider = RecordingProvider()
    capability = chat.build_chat_capability(
        NullCharacterContextProvider(),
        provider,
        reply_detail="detail",
        content_route_config=config,  # 刻意**不**注 reply_policy_store
    )
    message = _message()
    capability(message, _decision(message))

    assert received, "config 在场却没人问过 shared_reply_policy_store ⇒ 懒建腿是死的"
    assert received[0] is config, "懒建 store 用的不是装配那枚 config"
    assert HEADER in provider.prompt


def test_no_config_means_no_lazy_store_and_no_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """④的对照：config 缺席时懒建口一次都不被问，块也随之消失。"""
    calls: list[Any] = []
    monkeypatch.setattr(
        rp,
        "shared_reply_policy_store",
        lambda config: calls.append(config) or _hermetic_store(tmp_path),
    )
    provider = _run_turn(tmp_path, config=None)
    assert calls == [], "config 缺席却还去懒建 store ⇒ 本例的对照不成立"
    assert HEADER not in provider.prompt


# ---------------------------------------------------------------------------
# ⑤ 运维构造链腿：backend_unit 交 config，且离线工具路绝不碰生产库
# ---------------------------------------------------------------------------


def _offline_tool_config(tmp_path: Path) -> Config:
    """backend_unit 真链路的离线形状：静态 provider ＋ 数据根指 tmp ＋ 人格档造在 tmp。

    人格档必须**真的读得到且非空**：`context_preflight_errors` 非空时这一轮在提示词之前
    就被兜底话术接管（`context_error:persona_files_empty`），本例要测的渲染口压根走不到。
    """
    persona = tmp_path / "persona.md"
    persona.write_text("# 守岸人（测试人格）\n\n黑海岸的守望者，说话克制、有画面。\n", encoding="utf-8")
    return Config(
        _env_file=None,
        bot_chat_provider="static",
        bot_chat_model="static",
        bot_persona_files=[str(persona)],
        bot_knowledge_files=[],
        bot_memory_enabled=False,
        bot_history_enabled=False,
        bot_audit_log_file="",
        bot_runtime_data_dir=str(tmp_path),
    )


def test_backend_unit_chain_feeds_the_default_leg_and_stays_hermetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """运维单跑链（backend_unit）走真 `run_backend_unit`：

    摘掉 `"content_route_config": config` 那一行 ⇒ 第一段断言必红；
    摘掉同件里 `bot_reply_policy_enabled=False` 那一行 ⇒ 第二段断言必红
    （离线一次性工具路会按 `.env` 的 Runtime 根去懒建进程级 store，测试跑它就写生产库）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.pipeline import backend_unit

    seen: list[dict[str, Any]] = []
    asked: list[Any] = []
    real_section = rp.reply_policy_section_for_turn

    def spy_section(policy, **kwargs):
        seen.append(kwargs)
        return real_section(policy, **kwargs)

    monkeypatch.setattr(chat, "reply_policy_section_for_turn", spy_section)
    monkeypatch.setattr(
        rp,
        "shared_reply_policy_store",
        lambda config: asked.append(config) or None,
    )
    result = backend_unit.run_backend_unit(
        NEUTRAL_QUESTION, config=_offline_tool_config(tmp_path)
    )
    assert result["receipt_state"] == "sent", f"链路本身没走通，本例判据失效：{result}"
    assert "context_error" not in result["audit_tags"], (
        f"这一轮在提示词之前就被兜底话术接管，渲染口判据走不到：{result['audit_tags']}"
    )

    assert seen, "backend_unit 这条链压根没渲染偏好段 ⇒ content_route_config 没接进去"
    assert seen[-1].get("config") is not None, (
        "偏好段渲染口收到 config=None ⇒ 默认讲法在这条链上是静默关的"
    )
    assert asked, "config 在场却没问过懒建口 ⇒ 本例第二段的判据没落到真实路径上"
    assert not bool(getattr(asked[-1], "bot_reply_policy_enabled", True)), (
        "离线一次性工具路仍要懒建进程级 store ⇒ 会按 .env 落到**生产** reply_policy 库"
    )
    # 检索面同判据：ACG 竖源判定在 config 在场后改读 Config 字段（.env 现 true），
    # 不钉死就等于给「离线单跑」开一条外网腿。
    assert not bool(getattr(asked[-1], "bot_search_acg_enabled", True)), (
        "backend_unit 交了 config 却没关 ACG 竖源 ⇒ 离线工具路会发外网请求"
    )


# ---------------------------------------------------------------------------
# ⑥ 构造链名册腿：plugins/ 下每一处 build_chat_capability 都必须交这个参数
# ---------------------------------------------------------------------------

_BUILD_CALL = "build_chat_capability"


def _label_of(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST | None:
    cur: ast.AST | None = node
    while cur is not None and not isinstance(
        cur, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        cur = parents.get(id(cur))
    return cur


def _build_calls(tree: ast.AST) -> list[tuple[ast.AST | None, ast.Call]]:
    """每一处 `build_chat_capability(...)` 调用 ＋ 它所在函数（None＝模块级）。

    定义件不在此列（那是 `def`，不是 Call），所以 chat.py 自己不会被误判成构造点。
    """
    parents = _parent_map(tree)
    found: list[tuple[ast.AST | None, ast.Call]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _label_of(node.func) == _BUILD_CALL:
            found.append((_enclosing_function(node, parents), node))
    return found


def _chain_violations(source: str, *, rel: str) -> list[str]:
    tree = ast.parse(source)
    problems: list[str] = []
    for scope, call in _build_calls(tree):
        if any(kw.arg == "content_route_config" for kw in call.keywords):
            continue
        if any(kw.arg is None for kw in call.keywords):
            # `**capability_kwargs` 形态（backend_unit）：参数住在同函数的 dict 字面量里，
            # 于是判「这个键名还在不在同一层作用域」——摘掉那一行即消失。
            haystack = scope if scope is not None else tree
            if any(
                isinstance(node, ast.Constant) and node.value == "content_route_config"
                for node in ast.walk(haystack)
            ):
                continue
            problems.append(
                f"{rel}#{getattr(scope, 'name', '<module>')}: "
                "build_chat_capability(**kwargs) 的 kwargs 里没有 content_route_config"
                " ⇒ 该链默认讲法腿整段静默关"
            )
            continue
        scope_name = getattr(scope, "name", "<module>")
        problems.append(
            f"{rel}#{scope_name}: 第 {call.lineno} 行 build_chat_capability(...) 未交 "
            "content_route_config ⇒ 该链默认讲法腿与策略 store 懒建腿整段静默关"
        )
    return problems


def _construction_sites() -> list[Path]:
    """`plugins/` 下**构造**能力（调用 build_chat_capability）的文件。"""
    hits: list[Path] = []
    for path in sorted(PLUGINS_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            continue
        if _build_calls(tree):
            hits.append(path)
    return hits


def _strip_wiring_line(source: str, line: str) -> str:
    """注毒：把某一行接线整行摘掉（＝「删掉 config= 传参」的真实形态），并确认摘动了。"""
    assert line in source, f"注毒锚点不存在，毒没注进去：{line}"
    return source.replace(line + "\n", "", 1)


def test_every_construction_chain_passes_content_route_config() -> None:
    sites = _construction_sites()
    assert sites, "名册为空＝本例是空跑的（构造点一处都没找到）"
    # 定义件（chat.py 自己）不参与判据：它只提供参数，不构造能力。
    chat_py = (
        PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "chat_reply"
        / "capabilities" / "chat.py"
    )
    assert chat_py not in sites, f"chat.py 被当成构造点了：{sites}"
    violations = [
        problem for path in sites for problem in _chain_violations(
            path.read_text(encoding="utf-8"),
            rel=path.relative_to(_REPO_ROOT).as_posix(),
        )
    ]
    assert not violations, "有构造链没交 config：" + "; ".join(violations)
    # 名册必须覆盖到生产根 + 三条运维链（少一条就是名单漏了，不是链没问题）。
    rels = {p.relative_to(_REPO_ROOT).as_posix() for p in sites}
    for expected in (
        "plugins/bot_unified_runtime/__init__.py",
        "plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py",
        "plugins/bot_unified_runtime/domains/ops/smoke/smoke.py",
        "plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py",
    ):
        assert expected in rels, f"构造链名册少了 {expected}（该文件被搬走或判据失效）"


# ---------------------------------------------------------------------------
# ⑦ 渲染口 forwarding 锁：chat.py 必须把装配那枚 config 真交给 section 构造器
# ---------------------------------------------------------------------------

CHAT_PY = (
    PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "chat_reply"
    / "capabilities" / "chat.py"
)


def _section_call_kwargs(source: str) -> list[dict[str, str]]:
    """找出 `reply_policy_section_for_turn(...)` 调用，给出每个关键字的**取值表达式**。"""
    out: list[dict[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if _label_of(node.func) != "reply_policy_section_for_turn":
            continue
        out.append({kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg})
    return out


def test_render_seam_forwards_the_assembled_config_in_source() -> None:
    """本例锁的是**传参**那一行：摘掉 `config=content_route_config` 必红。"""
    calls = _section_call_kwargs(CHAT_PY.read_text(encoding="utf-8"))
    assert calls, "chat.py 里没有任何 reply_policy_section_for_turn 调用 ⇒ 渲染口被搬走"
    for kwargs in calls:
        assert kwargs.get("config") == "content_route_config", (
            f"渲染口 config 取的不是装配件 content_route_config：{kwargs}"
        )
        # 同一枚句柄也必须喂给 store 懒建腿的下游（store/person_key 同源）。
        assert kwargs.get("store") == "effective_reply_policy_store", kwargs
        assert "person_reply_policy_key" in kwargs.get("person_key", ""), kwargs


def test_render_seam_lock_bites_when_the_config_argument_is_dropped() -> None:
    """注毒自证（内存里摘行，不改 chat.py 本体）：摘掉 config= 就必须判红。"""
    source = CHAT_PY.read_text(encoding="utf-8")
    assert _section_call_kwargs(source)
    anchor = (
        "            # 不许在渲染口再写一份「没策略就塞文学化」。\n"
        "            config=content_route_config,\n"
    )
    poisoned = source.replace(anchor, "", 1)
    assert poisoned != source, "注毒锚点不存在＝毒没注进去"
    after = _section_call_kwargs(poisoned)
    assert any("config" not in kwargs for kwargs in after), (
        "摘掉 config= 传参后判据仍全绿＝这道锁是空跑的"
    )


def test_chain_roster_gate_bites_on_poisoned_sources() -> None:
    """注毒自证：把接线那一行摘掉（关键字形态与 **kwargs 形态各一），名册腿必须点名。"""
    root_src = (PLUGINS_ROOT / "bot_unified_runtime" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert _chain_violations(root_src, rel="__init__.py") == []
    poisoned_root = _strip_wiring_line(
        root_src,
        "            content_route_config=_config_with_runtime_overrides("
        "config, runtime_settings),",
    )
    violations_root = _chain_violations(poisoned_root, rel="__init__.py")
    assert violations_root, "摘掉根装配的关键字而门不红＝这道门是空跑的"
    assert "content_route_config" in violations_root[0]

    unit_py = (
        PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "chat_reply"
        / "pipeline" / "backend_unit.py"
    )
    unit_src = unit_py.read_text(encoding="utf-8")
    assert _chain_violations(unit_src, rel="backend_unit.py") == []
    poisoned_unit = _strip_wiring_line(unit_src, '        "content_route_config": config,')
    assert _chain_violations(poisoned_unit, rel="backend_unit.py"), (
        "**kwargs 形态被摘掉而门不红＝名册只覆盖了直传形态"
    )
