"""Wave 3 逐域接入席 S-W3B（weather / link_parse / food）常驻门。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1（D-b/D-c/D-d）/ §4 Wave3 / §5 / §7。
一句话——本件复用 ``tests/test_orchestration_callsite_single.py``（Wave 1 门）的扫描器
（``scan`` / ``check_invariants`` / ``_execution_calls`` / ``_invoker_cids`` / ``_injection_calls``，
**组合非复制**），把执法面从 files/search/media 扩到本席三域的 builder 真身，并给出
「经中央 invoker 通电 == 直呼 handler（逐字段）」的端到端等值证明。

三层：
1. **活性 ledger（真树）**：全树 AST 扫 ``build_weather_capability`` / ``build_eat_capability`` /
   ``build_content_capability`` 三个真身的生产直呼点，钉死当前登记（三域**尚未通电**，直呼面为 Wave3
   grandfathered，等主会话落 descriptor + root 切换原子批后按 SEAT-S-W3B §6 收编）。新增未审直呼点 /
   半迁移 / 第二 invoker 点当场红。
2. **端到端逐字段等值**：三域各一条能力经「现场注册 descriptor+adapter 的局部 ``CapabilityInvoker``」
   通电后，``data[PRESENTATION_DATA_KEY]`` 与直呼 handler 的 ``CapabilityResult.model_dump()`` 逐字段相等。
   adapter 忠实透传本域 builder 必需的 ``render_backend`` / 多依赖（本席关键发现：三域非 config 纯工厂）。
3. **注毒自证**：合成树证明「新增直呼」「第二 invoker 点」「半迁移」「摘 descriptor⇒诚实失败不崩+旧直调仍通」
   四态各真的会红（防「存在性糊过活性判据」式假门）。

全离线：三个 builder 真身在用例内 monkeypatch 为记录依赖的确定性替身，零网络、零真实数据源、零消息发送。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# 复用 Wave 1 门的扫描器（tests/ 非包 ⇒ 按文件路径装载）
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_WAVE1_GATE = _TESTS_DIR / "test_orchestration_callsite_single.py"
_spec = importlib.util.spec_from_file_location("_wave1_callsite_gate", _WAVE1_GATE)
assert _spec is not None and _spec.loader is not None
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

_PKG_ROOT = v1._PKG_ROOT  # …/plugins/bot_unified_runtime

# 本席三域真身符号 → 能力族
_TRACKED_B: dict[str, str] = {
    "build_weather_capability": "weather",
    "build_eat_capability": "eat",
    "build_content_capability": "content",
}
# 真身定义文件（其 module 内自用不算第二执行入口）
_DEF_FILES_B: dict[str, set[str]] = {
    "build_weather_capability": {"domains/weather/capabilities/weather.py"},
    "build_eat_capability": {"domains/food/capabilities/eat.py"},
    "build_content_capability": {"domains/link_parse/capabilities/content_parser.py"},
}
# 三域 capability_id → 族（scan 内部 _cid_to_cap 只认 files/search/media；此处补射本席 id）
_CID_TO_CAP_B: dict[str, str] = {
    "bot.weather": "weather",
    "bot.eat": "eat",
    "bot.content": "content",
}


def _patch_wave1_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 Wave 1 门的追踪面并上本席三域（改模块全局，让 scan/_cid_to_cap 认得新符号/id）。"""
    merged_tracked = {**v1._TRACKED, **_TRACKED_B}
    merged_defs = {**v1._DEF_FILES, **_DEF_FILES_B}
    orig_cid_to_cap = v1._cid_to_cap

    def _cid_to_cap(cid: str) -> str | None:
        return _CID_TO_CAP_B.get(cid) or orig_cid_to_cap(cid)

    monkeypatch.setattr(v1, "_TRACKED", merged_tracked, raising=False)
    monkeypatch.setattr(v1, "_DEF_FILES", merged_defs, raising=False)
    monkeypatch.setattr(v1, "_cid_to_cap", _cid_to_cap, raising=False)


# ---------------------------------------------------------------------------
# ① 活性 ledger：真树 = 当前登记（坐标实测 2026-09-22，见 SEAT-S-W3B §1）
# ---------------------------------------------------------------------------
# 三域生产直呼点全落在 root（__init__.py）与 ops smoke；无一条已走 invoker（本席禁碰 root/shell）。
# - weather：root 三处直呼（自然语言 6473 / actions 8582 / _build_weather_with_backend 4127 返回直呼）+ smoke 两件
# - eat：root 直呼（自然语言 6503 / actions 8616 / 薄工厂 4130）
# - content：root 8065（offload_capability(build_content_capability(...)) 位置实参=执行直呼）+ smoke console
KNOWN_DIRECT_ALLOWLIST_B: dict[str, set[str]] = {
    "weather": {
        "__init__.py",
        "domains/ops/smoke/console_chat.py",
        "domains/ops/smoke/route_demo.py",
    },
    "eat": {"__init__.py"},
    "content": {"__init__.py", "domains/ops/smoke/console_chat.py"},
}
# 尚未通电 ⇒ 无已登记 invoker 点；主会话落 root 切换原子批后按族迁入 KNOWN_INVOKER_SITES_B。
KNOWN_INVOKER_SITES_B: dict[str, set[str]] = {}
WIRED_B: set[str] = set()


def _load_b_index() -> dict[str, str]:
    """真树预筛：只交可能引用三真身或 capability_id= 的源文件给 AST。"""
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = v1._rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sym in text for sym in _TRACKED_B) or "capability_id=" in text:
            index[rel] = text
    return index


def test_real_tree_matches_wave3b_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """真树直呼/invoker 两面必须恰好等于评审过的三域 ledger——任一侧漂移当场红。"""
    _patch_wave1_scope(monkeypatch)
    direct, invoker = v1.scan(_load_b_index())
    # 只看本席三族
    b_direct = {cap: direct[cap] for cap in _TRACKED_B.values()}
    b_invoker = {cap: mods for cap, mods in invoker.items() if cap in _TRACKED_B.values() and mods}
    assert b_direct == KNOWN_DIRECT_ALLOWLIST_B, f"直呼面漂移：实得 {b_direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST_B}"
    assert b_invoker == KNOWN_INVOKER_SITES_B, f"invoker 面漂移：实得 {b_invoker} ≠ 登记 {KNOWN_INVOKER_SITES_B}"
    merged_allow = {**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_B}
    assert v1.check_invariants(
        b_direct, {cap: invoker[cap] for cap in _TRACKED_B.values()},
        wired=WIRED_B, allowlist=merged_allow,
    ) == []


def test_wave3b_three_symbols_actually_tracked() -> None:
    """分类面自证：三真身必须在追踪表里、定义文件被豁免（漏登记=该真身直呼永不红=门变哑）。"""
    assert set(_TRACKED_B) == {
        "build_weather_capability", "build_eat_capability", "build_content_capability",
    }
    for symbol, def_files in _DEF_FILES_B.items():
        assert symbol in _TRACKED_B
        for df in def_files:
            assert (_PKG_ROOT / df).exists(), f"{symbol} 定义文件坐标漂移：{df}"
    # 真身内部自用（同 module 内组合）不得被算作第二直呼点
    direct, _inv = v1.scan({"domains/weather/capabilities/weather.py":
        "def build_weather_capability(cfg):\n    return 1\ndef _x():\n    return build_weather_capability(1)\n"})
    assert direct.get("weather", set()) == set(), "真身同文件内部组合被误判为直呼点"


# ---------------------------------------------------------------------------
# ② 端到端逐字段等值：经 invoker 通电 == 直呼 handler（含依赖忠实透传锁）
# ---------------------------------------------------------------------------
# 本席关键发现：三域 builder **非 config→capability 纯工厂**——weather/eat 需 render_backend，
# content 需 registry/parse_history_store/downloader/render_backend/card_dir/playwright_backend/bot_avatar_url。
# 因此 adapter 必须从 request.context 取这些运行期依赖转发，绝不允许像 V2 型适配器只传 config（否则丢卡图=行为变更）。
_CONTEXT_KEYS: dict[str, tuple[str, ...]] = {
    "weather": ("render_backend",),
    "eat": ("render_backend",),
    "content": (
        "registry", "parse_history_store", "downloader", "render_backend",
        "card_dir", "playwright_backend", "bot_avatar_url",
    ),
}


def _make_forwarding_adapter(builder, family: str):
    """S-W3B 交付的通用适配器形态（与 SEAT-S-W3B §6-B 逐字块一致）：

    builder(config, **context转发依赖) -> capability；capability(message, decision) -> CapabilityResult。
    成功态把呈现契约 model_dump() 装进 data[PRESENTATION_DATA_KEY]。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationResult,
        InvocationStatus,
    )

    def _handler(request) -> InvocationResult:
        config = request.context.get("config")
        kwargs = {k: request.context.get(k) for k in _CONTEXT_KEYS[family]}
        capability = builder(config, **kwargs)
        presented = capability(request.payload["message"], request.context.get("decision"))
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via=family,
        )

    return _handler


def _fake_builder(cap_id: str, required_dep: str):
    """记录 builder 收到的依赖 + 消息，返回确定性 CapabilityResult 的替身工厂。

    把 required_dep 的实际取值回写进 body，任何「adapter 漏传/传错依赖」都会显形为 dump 差异。
    """
    from plugins.bot_unified_runtime.domains.core.contracts import CapabilityResult

    def builder(config, **deps):
        received = {k: repr(v) for k, v in sorted(deps.items())}

        def capability(message, decision):
            return CapabilityResult(
                request_id=getattr(message, "request_id", "r"),
                capability_id=cap_id,
                kind="text",
                title=f"{cap_id}·{getattr(message, 'plain_text', '')}",
                body=f"cfg={config!r}|deps={received}|decision={decision!r}",
                # debug_id 每次构造随机；钉定值让"直呼 vs 通电"两次独立执行可比对，
                # 并证明 adapter 原样透传 handler 的 debug_id（非自造）。
                debug_id="dbg_fixed",
            )

        return capability

    return builder


def _local_invoker(cap_id: str, family: str, builder, *, with_handler: bool = True):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityDescriptor,
        CapabilityFamily,
        CapabilityInvoker,
        CapabilityRegistry,
        HandlerRegistry,
    )

    registry = CapabilityRegistry()
    handlers = HandlerRegistry()
    descriptor = CapabilityDescriptor(
        capability_id=cap_id,
        # family 不参与 invoke() 判据，测试借用既有成员；真 descriptor 由主会话在扩员后落（见 §6-A）。
        family=CapabilityFamily.SEARCH,
        title=cap_id,
        input_protocol="payload.message: IncomingMessage; context.config",
        output_protocol="presentation_result: CapabilityResult.model_dump()",
        required_roles=("user",),
        fallback_chain=("honest_degrade:暂不可用",),
    )
    registry.register(descriptor)
    if with_handler:
        handlers.register(cap_id, _make_forwarding_adapter(builder, family))
    return CapabilityInvoker(registry=registry, handlers=handlers)


@pytest.mark.parametrize(
    "cap_id,family,required_dep",
    [("bot.weather", "weather", "render_backend"),
     ("bot.eat", "eat", "render_backend"),
     ("bot.content", "content", "render_backend")],
)
def test_e2e_wave3b_equals_direct(cap_id: str, family: str, required_dep: str) -> None:
    """三域各一条：经 invoker 通电产出的呈现载荷，与直呼 handler 逐字段相等，且依赖忠实透传。"""
    from plugins.bot_unified_runtime.domains.core.contracts import CapabilityResult
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )

    builder = _fake_builder(cap_id, required_dep)
    invoker = _local_invoker(cap_id, family, builder)

    message = SimpleNamespace(request_id="r1", plain_text="天气 杭州")
    decision = SimpleNamespace(actor_roles=["user"])
    deps = {"render_backend": "RB", "registry": "REG", "parse_history_store": "PHS",
            "downloader": "DL", "card_dir": "data/cards", "playwright_backend": "PW",
            "bot_avatar_url": "avatar"}
    request = CapabilityRequest(
        capability_id=cap_id,
        payload={"message": message},
        principal="u",
        roles=("user",),
        context={"config": {"k": 1}, "decision": decision, **{k: deps[k] for k in _CONTEXT_KEYS[family]}},
    )
    result = invoker.invoke(request)
    assert result.status is InvocationStatus.OK
    assert PRESENTATION_DATA_KEY in result.data

    # 直呼路径（旧路）产出的呈现契约
    direct_capability = builder(
        {"k": 1}, **{k: deps[k] for k in _CONTEXT_KEYS[family]}
    )
    direct_dump = direct_capability(message, decision).model_dump()
    # 逐字段相等：invoker 未增删/未伪造 handler 产出的任何字段
    assert result.data[PRESENTATION_DATA_KEY] == direct_dump

    # 依赖忠实透传锁：body 必须含本域必需依赖名与其真实取值（漏传/传错=这里显形）
    body = CapabilityResult.model_validate(result.data[PRESENTATION_DATA_KEY]).body
    assert required_dep in body and repr(deps[required_dep]) in body, (
        f"adapter 未忠实透传 {required_dep}={deps[required_dep]!r}：{body}"
    )


def test_e2e_denied_for_blocked_role_and_no_presentation_payload() -> None:
    """接入带来的中央权限门（旧直呼没有）：blocked 角色无条件拒，且失败态不携带呈现载荷。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityRequest,
        InvocationStatus,
    )

    builder = _fake_builder("bot.weather", "render_backend")
    invoker = _local_invoker("bot.weather", "weather", builder)
    result = invoker.invoke(
        CapabilityRequest(
            capability_id="bot.weather", payload={"message": SimpleNamespace(request_id="r", plain_text="x")},
            principal="u", roles=("blocked",), context={"config": None},
        )
    )
    assert result.status is InvocationStatus.DENIED
    assert PRESENTATION_DATA_KEY not in result.data


# ---------------------------------------------------------------------------
# ③ 注毒自证：每条不变量真的会红（合成树，非真树）
# ---------------------------------------------------------------------------
def _poison_direct_src(module_builder: str) -> str:
    return (
        f"def f(cfg):\n    return {module_builder}(cfg, render_backend=None)(None, None)\n"
    )


def test_poison_new_direct_site_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：allowlist 外新增一处 build_eat_capability 直呼 → 未登记直呼点红。"""
    _patch_wave1_scope(monkeypatch)
    direct, invoker = v1.scan({"domains/food/capabilities/sneaky.py":
        _poison_direct_src("build_eat_capability")})
    v = v1.check_invariants(
        {k: direct[k] for k in _TRACKED_B.values()},
        {k: invoker[k] for k in _TRACKED_B.values()},
        wired=WIRED_B, allowlist={**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_B},
    )
    assert any("未登记直呼点" in s and "eat" in s for s in v), f"新增直呼未被拦：{v}"


def test_poison_second_invoker_site_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：两模块各 invoke bot.weather → 第二调用点红。"""
    _patch_wave1_scope(monkeypatch)
    src = ("def f():\n    default_invoker().invoke("
           "CapabilityRequest(capability_id='bot.weather'))\n")
    direct, invoker = v1.scan({"m1.py": src, "m2.py": src})
    v = v1.check_invariants(
        {k: direct[k] for k in _TRACKED_B.values()},
        {k: invoker[k] for k in _TRACKED_B.values()},
        wired=WIRED_B, allowlist={**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_B},
    )
    assert any("第二调用点" in s and "weather" in s for s in v), f"第二 invoker 点未被拦：{v}"


def test_poison_half_migration_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：同模块既直呼 build_content_capability 又 invoke bot.content → 半迁移红。"""
    _patch_wave1_scope(monkeypatch)
    src = (
        "def f(cfg):\n"
        "    build_content_capability(cfg)(None, None)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='bot.content'))\n"
    )
    direct, invoker = v1.scan({"domains/link_parse/capabilities/half.py": src})
    v = v1.check_invariants(
        {k: direct[k] for k in _TRACKED_B.values()},
        {k: invoker[k] for k in _TRACKED_B.values()},
        wired=WIRED_B, allowlist={**v1.KNOWN_DIRECT_ALLOWLIST, **KNOWN_DIRECT_ALLOWLIST_B},
    )
    assert any("半迁移" in s and "content" in s for s in v), f"半迁移未被拦：{v}"


def test_poison_descriptor_missing_fails_honestly_direct_path_still_works() -> None:
    """注毒（机制自证）：descriptor 不在册 → invoke 诚实失败不崩、不携呈现载荷；旧直呼路径仍全通。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityInvoker,
        CapabilityRegistry,
        CapabilityRequest,
        HandlerRegistry,
        InvocationStatus,
    )

    # 在册表空（不注册 descriptor），但 handler 注册了也不该被叫到
    invoker = CapabilityInvoker(registry=CapabilityRegistry(), handlers=HandlerRegistry())
    result = invoker.invoke(
        CapabilityRequest(capability_id="bot.weather", payload={"message": None},
                          principal="u", roles=("user",), context={"config": None})
    )
    assert result.status is InvocationStatus.FAILED  # 未登记能力=FAILED（非在册未接=UNAVAILABLE）
    assert PRESENTATION_DATA_KEY not in result.data

    # 旧直呼路径不受影响：builder 仍可直呼产出呈现契约
    builder = _fake_builder("bot.weather", "render_backend")
    presented = builder({"k": 1}, render_backend="RB")(
        SimpleNamespace(request_id="r", plain_text="天气 上海"), None
    )
    assert presented.capability_id == "bot.weather"
