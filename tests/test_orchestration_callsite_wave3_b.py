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
2. **端到端真身逐字段等值**（S-FIXB 补修，评审 R1 账 1）：三域各一条用例**真 import builder 真身**，
   仅 monkeypatch IO 叶子（NMC 拉取/预警、出图、假 parse_fn、socket DNS），比对「现场注册
   descriptor+adapter 的局部 ``CapabilityInvoker``」通电后与直呼真身的整份
   ``CapabilityResult.model_dump()`` 逐字段相等；等值判据**复用** S-MEDIA 席
   ``_assert_presentation_equals``（pop 唯一随机字段 ``debug_id`` 且点名、断言两路都有），不复制第二份。
   旧「两路皆替身」的 fake-builder 用例如实降级为 ②-a **adapter 形状自证**（只证 context→builder
   接线与 wrap 形状，不对真身产出作任何断言）。
3. **注毒自证**：合成树证明「新增直呼」「第二 invoker 点」「半迁移」「摘 descriptor⇒诚实失败不崩+
   旧直调仍通」四态各真的会红（防「存在性糊过活性判据」式假门）；真等值配常驻杀伤力锁——
   adapter 丢呈现字段/丢转发依赖必红（S-FIXB 新增）。

全离线：真身真调，IO 叶子逐域打桩——weather 打 ``nmc_weather_query``/``fetch_city_alerts``/
垫片消费面 ``render_card_png``；content 走 registry 注入缝（真 ParserRegistry+真 ParserRule+
假 parse_fn=网络叶子）并钉 ``socket.getaddrinfo``；eat **零 mock**（菜谱命中分支=内置 DISHES
纯内存查表）。零网络、零出图、零消息发送、零源码树 ``data/`` 写入。
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

# 复用 S-MEDIA 席门的真等值判据 ``_assert_presentation_equals``（组合非复制，铁律=禁第二套判据）。
_MEDIA_GATE = _TESTS_DIR / "test_orchestration_callsite_wave_media.py"
_mspec = importlib.util.spec_from_file_location("_wave_media_gate", _MEDIA_GATE)
assert _mspec is not None and _mspec.loader is not None
m = importlib.util.module_from_spec(_mspec)
_mspec.loader.exec_module(m)

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


def _local_invoker(
    cap_id: str,
    family: str,
    builder,
    *,
    with_handler: bool = True,
    drop_context_key: str | None = None,
    drop_dump_key: str | None = None,
):
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
        if drop_context_key is None and drop_dump_key is None:
            handlers.register(cap_id, _make_forwarding_adapter(builder, family))
        else:
            handlers.register(cap_id, _sabotaged_adapter(builder, family, drop_context_key, drop_dump_key))
    return CapabilityInvoker(registry=registry, handlers=handlers)


def _sabotaged_adapter(builder, family: str, drop_context_key: str | None, drop_dump_key: str | None):
    """交付 adapter 的故意破坏变体（杀伤力常驻锁用）：丢一枚转发依赖或丢一个呈现字段，
    真等值必须当场抓住——抓不住即证明 ②-b 是假绿。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationResult,
        InvocationStatus,
    )

    def _handler(request) -> InvocationResult:
        config = request.context.get("config")
        kwargs = {k: request.context.get(k) for k in _CONTEXT_KEYS[family] if k != drop_context_key}
        presented = builder(config, **kwargs)(
            request.payload["message"], request.context.get("decision")
        )
        dump = presented.model_dump()
        if drop_dump_key is not None:
            dump.pop(drop_dump_key, None)
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: dump},
            via=family,
        )

    return _handler


# ---- ②-a adapter 形状自证（fake builder 两路皆替身）：只证 context→builder 接线与信封 wrap。
# 本用例旧账名叫「端到端逐字段等值」，评审 R1 判假绿（两路从不碰真身，属实）——S-FIXB
# 如实降级为形状自证：fake builder 把收到的依赖取值回写 body，证 adapter 逐键转发
# ``_CONTEXT_KEYS``；真身产出的断言在下面 ②-b，此处不作任何真身声明。
@pytest.mark.parametrize(
    "cap_id,family,required_dep",
    [("bot.weather", "weather", "render_backend"),
     ("bot.eat", "eat", "render_backend"),
     ("bot.content", "content", "render_backend")],
)
def test_adapter_shape_forwards_context_deps_to_builder(cap_id: str, family: str, required_dep: str) -> None:
    """形状自证：context 各键经 adapter 忠实落到 builder kwargs，信封 wrap 不增删字段。"""
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


# ---- ②-b 端到端真身逐字段等值（S-FIXB）：真 import builder 真身，只桩 IO 叶子，判据复用 S-MEDIA 席。
def _e2e_message(text: str):
    """真 IncomingMessage 契约（非假消息）；两路共用同一份消息体，只差执行入口。"""
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="onebot", adapter="onebot.v11", bot_id="bot",
        session_id="private:u1", session_type=SessionType.PRIVATE,
        sender_id="u1", plain_text=text,
    )


def _real_spec(family: str, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """返回 (builder 真身, config, 逐字转给 builder 的 context 依赖, 消息)，并打好本域 IO 叶子。"""
    if family == "weather":
        # 叶子=nmc_weather_query（NMC HTTP）/fetch_city_alerts（预警 HTTP）/render_card_png
        # （weather 函数级 import 消费的真身属性=出图）。码表/变体链/报告文本/审计 tags 全真。
        # ⚠ 补丁点必须是**真身** `domains/link_parse/capabilities/content_parser`：
        #    `domains/weather/capabilities/weather.py:298` 那条函数级 import 取的就是真身名，
        #    打在旧布局垫片 `capabilities/content_parser` 上＝垫片自己多一个绑定、真身未动
        #    ⇒ 桩根本不生效（2026-09-29 主树还原波把这一枚从真身形回退成垫片形，本批改回）。
        import plugins.bot_unified_runtime.domains.weather.capabilities.weather as weather_mod
        from plugins.bot_unified_runtime.domains.link_parse.capabilities import (
            content_parser as card_body,
        )

        # 🔴 桩形必须与真身同签：`nmc_weather_query(query, *, proxy="", timeout=None)`
        # （S-FIX-WX-T6 加了 timeout 逐次透传，锁＝tests/test_wx_t6_timeout_plumbing.py）。
        # 本桩此前只收 (query, proxy) ⇒ 生产侧透传 timeout 时 TypeError 被吞成 DEGRADED，
        # 表现为"e2e 不等值"假缺陷（2026-10-07 现算：错文＝`<lambda>() got an unexpected
        # keyword argument 'timeout'`，真身 `nmc_weather.py:190` 是收 timeout 的）。
        monkeypatch.setattr(weather_mod, "nmc_weather_query",
                            lambda query, proxy="", timeout=None: f"【{query}天气】晴 25℃")
        monkeypatch.setattr(weather_mod, "fetch_city_alerts", lambda query, proxy="": [])
        monkeypatch.setattr(card_body, "render_card_png",
                            lambda backend, item, **kw: {"file": str(tmp_path / "weather.png")})
        config = SimpleNamespace(bot_download_proxy="", bot_card_render_dir=str(tmp_path / "cards"))
        deps = {"render_backend": SimpleNamespace(available=True, name="stub-renderer")}
        return weather_mod.build_weather_capability, config, deps, _e2e_message("天气 北京")
    if family == "eat":
        # 零 mock：「菜谱 番茄炒蛋」命中分支=真 builder+内置 DISHES 纯内存查表，
        # render_backend=None 走文本兜底——全链无 IO，是最强形态的真等值。
        import plugins.bot_unified_runtime.domains.food.capabilities.eat as eat_mod

        config = SimpleNamespace(bot_card_render_dir="", bot_card_cache_max_bytes=0)
        return eat_mod.build_eat_capability, config, {"render_backend": None}, _e2e_message("菜谱 番茄炒蛋")
    if family == "content":
        # 叶子=假 parse_fn（唯一网络取数点，经 registry 注入缝，先例 test_parser_ssrf_guard）
        # +socket.getaddrinfo（SSRF 护栏的 DNS）；registry/规则/候选选择/正文渲染全真。
        import socket

        from plugins.bot_unified_runtime.domains.core.contracts.media import (
            ParserRule,
            build_parsed_content,
        )
        from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
            build_content_capability,
        )
        from plugins.bot_unified_runtime.sources.registry import ParserRegistry

        def fake_parse(url_arg):
            return build_parsed_content(
                platform="generic", item_id="1", item_kind="post",
                title="公开标题", canonical_url=url_arg,
            )

        registry = ParserRegistry()
        registry.register(ParserRule(
            parser_id="generic", source_id="通用", url_patterns=[r"xiaohongshu\.com"], priority=1,
        ))

        def fake_dns(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", int(port or 0)))]

        monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
        config = SimpleNamespace(bot_media_analyze_enabled=False)
        deps = {
            "registry": {"registry": registry, "parsers": {"generic": fake_parse}},
            "parse_history_store": None, "downloader": None, "render_backend": None,
            "card_dir": str(tmp_path / "cards"), "playwright_backend": None, "bot_avatar_url": "",
        }
        return (build_content_capability, config, deps,
                _e2e_message("https://www.xiaohongshu.com/explore/abc123"))
    raise AssertionError(f"未知 family {family!r}")


def _e2e_request(cap_id: str, config, deps: dict, message):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    return CapabilityRequest(
        capability_id=cap_id, payload={"message": message}, principal="u1", roles=("user",),
        context={"config": config, "decision": SimpleNamespace(actor_roles=["user"]), **deps},
    )


def _assert_real_equality(cap_id: str, family: str, builder, config, deps: dict, message):
    """invoker 通电信封 vs 直呼真身：整份 ``model_dump()`` 逐字段。判据=S-MEDIA
    ``_assert_presentation_equals``（唯一豁免随机字段 ``debug_id``，pop 点名且断言两路都有）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationStatus,
    )

    envelope = _local_invoker(cap_id, family, builder).invoke(_e2e_request(cap_id, config, deps, message))
    assert envelope.status is InvocationStatus.OK
    direct = builder(config, **deps)(message, SimpleNamespace(actor_roles=["user"]))
    m._assert_presentation_equals(envelope, direct)
    return direct


def test_e2e_weather_real_builder_equals_direct(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder, config, deps, message = _real_spec("weather", tmp_path, monkeypatch)
    direct = _assert_real_equality("bot.weather", "weather", builder, config, deps, message)
    # 分支证明：必须走到「码表命中→NMC 报告→渲染出卡」（坠降级空分支则等值没营养）
    assert direct.kind == "mixed" and direct.images and "晴 25℃" in direct.body


def test_e2e_eat_real_builder_equals_direct(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder, config, deps, message = _real_spec("eat", tmp_path, monkeypatch)
    direct = _assert_real_equality("bot.eat", "eat", builder, config, deps, message)
    assert direct.kind == "text" and "番茄炒蛋" in direct.body and "做法" in direct.body


def test_e2e_content_real_builder_equals_direct(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder, config, deps, message = _real_spec("content", tmp_path, monkeypatch)
    direct = _assert_real_equality("bot.content", "content", builder, config, deps, message)
    assert "公开标题" in direct.body and "content_parse" in direct.audit_tags


@pytest.mark.parametrize(
    ("family", "drop_key"),
    [("weather", "title"), ("weather", "audit_tags"), ("eat", "images"), ("content", "body")],
)
def test_poison_real_equality_dropping_presentation_field_is_red(
    family: str, drop_key: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒（常驻）：adapter 丢任何一个呈现字段 ⇒ 真等值必红——②-b 杀伤力自证。"""
    builder, config, deps, message = _real_spec(family, tmp_path, monkeypatch)
    cap_id = f"bot.{family}"
    envelope = _local_invoker(cap_id, family, builder, drop_dump_key=drop_key).invoke(
        _e2e_request(cap_id, config, deps, message)
    )
    direct = builder(config, **deps)(message, SimpleNamespace(actor_roles=["user"]))
    with pytest.raises(AssertionError):
        m._assert_presentation_equals(envelope, direct)


def test_poison_weather_adapter_losing_render_backend_is_red(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒（常驻）：adapter 丢 render_backend 转发 ⇒ weather 静默降级 text-only 卡
    （kind/images 不等值）必红——S-W3B「多依赖忠实透传」自此由真身产出把关，不再靠替身自证。"""
    builder, config, deps, message = _real_spec("weather", tmp_path, monkeypatch)
    envelope = _local_invoker("bot.weather", "weather", builder, drop_context_key="render_backend").invoke(
        _e2e_request("bot.weather", config, deps, message)
    )
    direct = builder(config, **deps)(message, SimpleNamespace(actor_roles=["user"]))
    assert direct.kind == "mixed"  # 对照：完整转发确实出卡，差异不是两路都没跑到
    with pytest.raises(AssertionError):
        m._assert_presentation_equals(envelope, direct)


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
