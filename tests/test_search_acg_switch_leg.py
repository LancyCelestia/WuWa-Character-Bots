"""S-ACG-SWITCH（2026-09-26）：ACG 竖源开关腿的活性锁——「开关在册、路走不到」。

病状（生产同构实算钉死，见本席日志 §复现）：生产 `.env` 里
`BOT_SEARCH_ACG_ENABLED=true`（装载链 `load_runtime_config()` 读进 Config 为 True，根
`__init__.py:5083` 交给 `build_chat_capability` 的合并件 content_route_config 也为 True），
但 `chat.py` 的 ACG 判定用 `runtime_settings.get_or("BOT_SEARCH_ACG_ENABLED", False)` 取值，
而 `get_or` 真身只查覆盖册、**完全不碰 Config/.env**，生产覆盖册九枚里没有本族键 ⇒ 该腿恒
False、竖源一次都没跑过。同一枚开关的另一腿（`capability_protocols._handle_search_acg`）
读的是 Config——一个开关名、两个取数口，这就是「开关是 True 但路永远走不到」的完整形态。

修法（本锁钉住的现行形状）：`get_or` 的缺省改从 content_route_config 的同名**字段**取
（覆盖在册仍赢；Config 未注入的 smoke/console/backend_unit 工具路走 config.py 声明缺省），
六枚键逐枚经 `_acg_leg_config_default`。

四把锁全部是**活性**（真驱 `capability()` 闭包、断言竖源派发口真被走到/真没被走到），
不是存在性：
① `.env`=True（同构 Config 在场）且覆盖册无键 ⇒ 腿判开（修复前必红＝本席 RED 证据）；
② 覆盖册显式 false ⇒ 腿判关（覆盖仍赢）；此锁同时实证六枚键真进了 `SETTABLE_KEYS`
   ——未登记时 `set_override` 直接 ValueError，今天就是这么红的第二格；
③ AST 形态锁：ACG 判据里不许再出现把硬缺省字面量当第二真身的写法
   （`get_or("BOT_SEARCH_ACG_*", True/False/数字)` 一律违规），六枚缺省实参必须逐枚是
   `_acg_leg_config_default(content_route_config, "<对得上的小写字段名>")`；
④ content_route_config 已注入却缺本族字段 ⇒ 按 config.py 声明缺省关腿，但必须打出
   一行点名 warning（分叉可见；#53 preview 路实证注入面可以是部分形状，炸穿它不是
   执法）；注入件里**在**的字段照读（①级优先）。

全离线：不 import 生产 .env（夹具交合成 Config）、store 落 tmp_path、
`search_acg_verticals` 换 spy ⇒ Bangumi/萌百/B 站零外网请求。开腿后的真机验收另列
（重启由用户提权执行）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    chat as chat_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_capability,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    NullCharacterContextProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    StaticLLMProvider,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    classify_question_intent,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
    SETTABLE_KEYS,
    RuntimeSettingsStore,
)
from plugins.bot_unified_runtime.domains.core.search import acg_search
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    acg_search_allowed,
    detect_acg_intent,
)

CHAT_PY = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
)

ACG_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("BOT_SEARCH_ACG_ENABLED", "bot_search_acg_enabled"),
    ("BOT_SEARCH_ACG_BANGUMI_ENABLED", "bot_search_acg_bangumi_enabled"),
    ("BOT_SEARCH_ACG_MOEGIRL_ENABLED", "bot_search_acg_moegirl_enabled"),
    ("BOT_SEARCH_ACG_BILIBILI_ENABLED", "bot_search_acg_bilibili_enabled"),
    ("BOT_SEARCH_ACG_TIMEOUT_SECONDS", "bot_search_acg_timeout_seconds"),
    ("BOT_SEARCH_ACG_MAX_PER_SOURCE", "bot_search_acg_max_per_source"),
)

ACG_QUERY = "芙莉莲第三季出了吗"  # is_acg=True、reason=general_static_knowledge、安全面放行


def _message(text: str):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _decision(message: Any):
    from plugins.bot_unified_runtime.contracts import BotDecision, SessionType

    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="private",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


def _fresh_store(tmp_path: Path) -> RuntimeSettingsStore:
    """真 store、空覆盖册、落 tmp（不碰生产 JSON/SQLite，也不写源码树）。"""
    return RuntimeSettingsStore(tmp_path / "runtime_settings_test.json", instance="acg-leg")


def _run_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    content_route_config: Any,
) -> list[dict[str, Any]]:
    """驱一次真 `capability()`，回收 `search_acg_verticals` 收到的调用（0 次＝腿没跑）。"""
    calls: list[dict[str, Any]] = []

    def _spy(query: str, intent: Any, **kwargs: Any) -> tuple[list, list]:
        calls.append({"query": query, "intent": intent, **kwargs})
        return ([], [])

    monkeypatch.setattr(acg_search, "search_acg_verticals", _spy)
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="好的"),
        runtime_settings=_fresh_store(tmp_path),
        content_route_config=content_route_config,
    )
    message = _message(ACG_QUERY)
    capability(message, _decision(message))
    return calls


# 前提自证：这条问句今天就在意图门与安全放行面之内（腿不开不能赖给意图判定）。
def test_prereq_intent_and_safety_gate_would_allow() -> None:
    intent = detect_acg_intent(ACG_QUERY)
    question_intent = classify_question_intent(ACG_QUERY)
    assert intent.is_acg is True
    assert acg_search_allowed(question_intent.reason) is True


# ---------------------------------------------------------------- 锁① 开腿活性
def test_env_true_with_empty_override_registry_opens_the_leg(tmp_path, monkeypatch) -> None:
    """`.env` 同构 Config=True + 覆盖册无键 ⇒ 竖源派发口必须真被走到。

    修复前必红：`get_or` 只看覆盖册，缺省硬编码 False ⇒ 这条腿今天恒关。
    """
    cfg = Config(bot_search_acg_enabled=True)
    calls = _run_turn(tmp_path, monkeypatch, content_route_config=cfg)
    assert calls, (
        "BOT_SEARCH_ACG_ENABLED=True（Config 侧，即 .env 同构值）且覆盖册为空，"
        "腿却没开——search_acg_verticals 一次都没被调用"
    )
    kwargs = calls[0]
    # 六枚键的缺省必须整体来自 Config 字段，不许残留第二套硬编码值。
    assert kwargs["enabled_sources"] == {"bangumi": True, "moegirl": True, "bilibili": True}
    assert kwargs["timeout_seconds"] == cfg.bot_search_acg_timeout_seconds
    assert kwargs["max_per_source"] == cfg.bot_search_acg_max_per_source


def test_env_false_keeps_the_leg_closed(tmp_path, monkeypatch) -> None:
    """反向格（防过修成恒开）：Config 侧 False、覆盖册无键 ⇒ 腿必须关、派发口零调用。"""
    cfg = Config(bot_search_acg_enabled=False)
    calls = _run_turn(tmp_path, monkeypatch, content_route_config=cfg)
    assert calls == []


def test_per_source_toggles_and_limits_flow_from_config(tmp_path, monkeypatch) -> None:
    """四枚竖源细键（三源开关+条数上限）必须逐枚从 Config 字段走到派发口。"""
    cfg = Config(
        bot_search_acg_enabled=True,
        bot_search_acg_bangumi_enabled=False,
        bot_search_acg_moegirl_enabled=True,
        bot_search_acg_bilibili_enabled=False,
        bot_search_acg_max_per_source=1,
    )
    calls = _run_turn(tmp_path, monkeypatch, content_route_config=cfg)
    assert calls, "开关与细键都在 Config 里，腿却没开"
    assert calls[0]["enabled_sources"] == {
        "bangumi": False,
        "moegirl": True,
        "bilibili": False,
    }
    assert calls[0]["max_per_source"] == 1


# ---------------------------------------------------------------- 锁② 覆盖仍赢
def test_registry_override_false_beats_config_true(tmp_path, monkeypatch) -> None:
    """覆盖册显式 false ⇒ 腿判关（覆盖仍赢）；set 能落册本身实证六枚键已登记 SETTABLE。

    修复前这一格红在两处：`set_override` 因未登记直接 ValueError（SETTABLE 面缺这六枚），
    且即便手改 JSON 落册，旧腿也只是把 False 换成硬 False、语义上是巧合不是执法。
    """
    for env_key, _field in ACG_ENV_KEYS:
        assert env_key in SETTABLE_KEYS, f"{env_key} 未登记 SETTABLE_KEYS ⇒ 覆盖面无入口，热改永远不可达"
    store = _fresh_store(tmp_path)
    store.set_override("BOT_SEARCH_ACG_ENABLED", "false", actor="s-acg-switch")
    cfg = Config(bot_search_acg_enabled=True)
    calls: list[dict[str, Any]] = []

    def _spy(query: str, intent: Any, **kwargs: Any) -> tuple[list, list]:
        calls.append(kwargs)
        return ([], [])

    monkeypatch.setattr(acg_search, "search_acg_verticals", _spy)
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="好的"),
        runtime_settings=store,
        content_route_config=cfg,
    )
    message = _message(ACG_QUERY)
    capability(message, _decision(message))
    assert calls == [], "覆盖册显式 false 却没压过 Config 的 True ⇒ 覆盖面没赢"


def test_registry_override_wins_on_numeric_and_source_keys(tmp_path, monkeypatch) -> None:
    """数值/名单面的覆盖同样赢：timeout=1.5、max=1、bilibili=false 覆盖 Config 的宽值。"""
    store = _fresh_store(tmp_path)
    store.set_override("BOT_SEARCH_ACG_TIMEOUT_SECONDS", "1.5", actor="s-acg-switch")
    store.set_override("BOT_SEARCH_ACG_MAX_PER_SOURCE", "1", actor="s-acg-switch")
    store.set_override("BOT_SEARCH_ACG_BILIBILI_ENABLED", "false", actor="s-acg-switch")
    cfg = Config(bot_search_acg_enabled=True)
    calls: list[dict[str, Any]] = []

    def _spy(query: str, intent: Any, **kwargs: Any) -> tuple[list, list]:
        calls.append(kwargs)
        return ([], [])

    monkeypatch.setattr(acg_search, "search_acg_verticals", _spy)
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="好的"),
        runtime_settings=store,
        content_route_config=cfg,
    )
    message = _message(ACG_QUERY)
    capability(message, _decision(message))
    assert calls, "总开关在 Config=True，覆盖只改细键，腿不应关"
    assert calls[0]["timeout_seconds"] == 1.5
    assert calls[0]["max_per_source"] == 1
    assert calls[0]["enabled_sources"]["bilibili"] is False
    assert calls[0]["enabled_sources"]["moegirl"] is True


# ---------------------------------------------------------------- 锁③ AST 形态
def _acg_shape_violations(source: str) -> list[str]:
    """chat.py 源码 → ACG 判定缺省形态违规清单（纯谓词，喂合成源码即可测牙）。

    判据：对每个 `acg_config_get("<BOT_SEARCH_ACG_*>"[, default])` 调用——
    · 只有 1 个实参 ⇒ 缺省被吞（更糟，直接吃 get_or 的 None/隐式路）；
    · 第 2 实参不是 `_acg_leg_config_default(content_route_config, "<对应小写字段>")`
      调用 ⇒ 违规（硬字面量、别的函数、指错字段，全算）。
    """
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "acg_config_get" or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        env_key = str(first.value)
        if not env_key.startswith("BOT_SEARCH_ACG_"):
            continue
        expected_field = env_key.lower()
        if len(node.args) < 2:
            violations.append(f"{node.lineno}: {env_key} 没有缺省实参")
            continue
        default = node.args[1]
        ok = (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "_acg_leg_config_default"
            and len(default.args) == 2
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id == "content_route_config"
            and isinstance(default.args[1], ast.Constant)
            and default.args[1].value == expected_field
        )
        if not ok:
            violations.append(
                f"{node.lineno}: {env_key} 的缺省不是 "
                f"_acg_leg_config_default(content_route_config, {expected_field!r})"
            )
    return violations


def test_acg_gate_reads_no_hardcoded_defaults_in_chat_py() -> None:
    """现行真树必须 0 违规，且六枚键全部在场（防「把整段删了也算合规」）。"""
    source = CHAT_PY.read_text(encoding="utf-8")
    violations = _acg_shape_violations(source)
    assert not violations, "ACG 判据里又长出第二真身缺省：" + "；".join(violations)
    tree = ast.parse(source)
    seen_keys = {
        str(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "acg_config_get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and str(node.args[0].value).startswith("BOT_SEARCH_ACG_")
    }
    assert seen_keys == {env for env, _f in ACG_ENV_KEYS}, (
        f"ACG 六枚键的 get_or 判据集合漂了：{sorted(seen_keys)}"
    )


# 注毒台（锁③）：旧「硬字面量缺省」形状与「指错字段」半修形状必须被抓；合规形状放行。
_LEGACY_SHAPE_SRC = '''
def _cap(content_route_config, acg_config_get):
    acg_enabled = bool(acg_config_get("BOT_SEARCH_ACG_ENABLED", False))
    acg_timeout = float(acg_config_get("BOT_SEARCH_ACG_TIMEOUT_SECONDS", 4.0))
    acg_sources = bool(acg_config_get("BOT_SEARCH_ACG_BILIBILI_ENABLED", True))
    return acg_enabled, acg_timeout, acg_sources
'''
_HALF_FIXED_SRC = '''
def _cap(content_route_config, acg_config_get):
    return bool(
        acg_config_get(
            "BOT_SEARCH_ACG_ENABLED",
            _acg_leg_config_default(content_route_config, "bot_search_acg_bangumi_enabled"),
        )
    )
'''
_GOOD_SHAPE_SRC = '''
def _cap(content_route_config, acg_config_get):
    return bool(
        acg_config_get(
            "BOT_SEARCH_ACG_ENABLED",
            _acg_leg_config_default(content_route_config, "bot_search_acg_enabled"),
        )
    )
'''


def test_acg_shape_predicate_bites_poison_shapes() -> None:
    """锁③的牙：先自证真树锚点在（不是空跑），再逐形判。"""
    assert _acg_shape_violations(_GOOD_SHAPE_SRC) == [], "合规形状被判违规 ⇒ 常驻锁迟早被调松"
    legacy = _acg_shape_violations(_LEGACY_SHAPE_SRC)
    assert len(legacy) == 3, f"旧硬缺省形态竟抓到 {len(legacy)} 枚：" + "；".join(legacy)
    half = _acg_shape_violations(_HALF_FIXED_SRC)
    assert len(half) == 1 and "BOT_SEARCH_ACG_ENABLED" in half[0], (
        f"缺省指错字段（enabled 位上读成 bangumi）的半修形状必须被抓：{half}"
    )
    # 真树锚点自证：判据读的是真 chat.py 里真在跑的六枚（否则常驻腿在空跑）。
    live = _acg_shape_violations(CHAT_PY.read_text(encoding="utf-8"))
    assert live == [], f"真树自身仍有违规（常驻腿没绿）：{live}"


# ---------------------------------------------------------------- 锁④ 分叉可见
def test_injected_config_missing_acg_field_warns_and_stays_closed(
    tmp_path, monkeypatch, caplog
) -> None:
    """content_route_config 已注入却缺本族字段 ⇒ 腿按声明缺省关，且必须留下一行点名 warning。

    静默退回「关腿」就是把本病从「值读不到」改写成「字段丢了也不知道」；这里既不吃
    AttributeError 炸穿别的波次的合法鸭子注入（#53 preview 路实证会交部分形状），
    也绝不无声——caplog 抓到 `bot_search_acg_enabled` 才算过。
    """
    bare = SimpleNamespace(bot_content_route_enabled=False)  # 故意不含任何 bot_search_acg_* 字段
    monkeypatch.setattr(acg_search, "search_acg_verticals", lambda *a, **k: ([], []))
    capability = build_chat_capability(
        NullCharacterContextProvider(),
        StaticLLMProvider(text="好的"),
        runtime_settings=_fresh_store(tmp_path),
        content_route_config=bare,
    )
    message = _message(ACG_QUERY)
    with caplog.at_level("WARNING"):
        capability(message, _decision(message))  # 不得炸
    warnings = [r.getMessage() for r in caplog.records if "acg_leg_config_default" in r.getMessage()]
    assert any("bot_search_acg_enabled" in w for w in warnings), (
        f"注入件缺字段却没打点名行（静默降级＝本病复发）：{warnings}"
    )


def test_partial_injected_object_fields_are_honored(tmp_path, monkeypatch) -> None:
    """注入件**有**的字段必须照读（对象在场优先于声明缺省），只给缺的那几枚打点。"""
    partial = SimpleNamespace(bot_search_acg_enabled=True)  # 其余五枚缺席→声明缺省
    calls = _run_turn(tmp_path, monkeypatch, content_route_config=partial)
    assert calls, "注入件里 enabled=True 却没开腿 ⇒ ① 级取值没生效"
    assert calls[0]["max_per_source"] == Config().bot_search_acg_max_per_source


# ---------------------------------------------------------------- 注毒台（行为腿①②）
def test_poison_literal_default_helper_reopens_the_disease(tmp_path, monkeypatch) -> None:
    """注毒①：把缺省口换成「硬字面量第二真身」（病本体），锁①必须当场失去开腿判定。

    先验锚点：不打毒时锁①判据必须真能开腿（否则本毒在空跑）。
    """
    cfg = Config(bot_search_acg_enabled=True)
    assert _run_turn(tmp_path, monkeypatch, content_route_config=cfg), "锚点空跑：正例今天就不开"

    def _poisoned(_config: Any, _name: str) -> Any:
        return False  # 模拟旧硬缺省：覆盖册与 Config 一概不看真值

    monkeypatch.setattr(chat_module, "_acg_leg_config_default", _poisoned)
    calls = _run_turn(tmp_path / "poison1", monkeypatch, content_route_config=cfg)
    monkeypatch.undo()
    assert calls == [], "注毒后腿竟还开着 ⇒ 锁①判据没吃这个缺省口（毒在空跑）"
    # 还原自证：undo 后复绿（缺此步则毒可能已经焊进环境，红不是它该红的样子）。
    assert _run_turn(tmp_path / "restore1", monkeypatch, content_route_config=cfg)


def test_poison_override_ignored_by_registry_read(tmp_path, monkeypatch) -> None:
    """注毒②：把覆盖册取数口架空（`get_or` 无视在册覆盖、只回缺省），锁②必红。

    毒打在**读覆盖册那一步**上——「覆盖仍赢」这条腿的活性正在于此：谁哪天把缺省口
    换成真值、却不再查 registry，这一发就当场揭穿。
    """
    store = _fresh_store(tmp_path)
    store.set_override("BOT_SEARCH_ACG_ENABLED", "false", actor="s-acg-switch")
    cfg = Config(bot_search_acg_enabled=True)

    def _collect() -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def _spy(query: str, intent: Any, **kwargs: Any) -> tuple[list, list]:
            calls.append(kwargs)
            return ([], [])

        monkeypatch.setattr(acg_search, "search_acg_verticals", _spy)
        capability = build_chat_capability(
            NullCharacterContextProvider(),
            StaticLLMProvider(text="好的"),
            runtime_settings=store,
            content_route_config=cfg,
        )
        message = _message(ACG_QUERY)
        capability(message, _decision(message))
        return calls

    assert _collect() == [], "锚点空跑：未注毒时覆盖 false 就没压住 ⇒ 锁②本身不成立"
    monkeypatch.setattr(
        RuntimeSettingsStore,
        "get_or",
        lambda self, key, default: default,
    )
    poisoned = _collect()
    monkeypatch.undo()
    assert poisoned, "注毒后覆盖 false 仍生效 ⇒ 锁②判据没吃 registry 这一步（毒在空跑）"
    assert _collect() == [], "还原后未复绿"


if __name__ == "__main__":  # 手工排障入口
    raise SystemExit(pytest.main([__file__, "-q"]))
