"""统一接入波 · S-MEDIA 席门：media/TTS 全链「禁第二调用点」+ 端到端逐字段等值。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §2 / §4 Wave1 / §7。
用户原令「所有内容走中央调度层，TTS 也不例外」——本件锁的是 v1 门
（``tests/test_orchestration_callsite_single.py``）覆盖不到的 TTS 执行真空：v1 的
``_TRACKED`` 只含 ingest 原语（describe_images/…），**不含** ``synthesize``/
``build_tts_capability``/``maybe_attach_voice``，故 bot.tts 走没走中央、有没有第二直呼点，
v1 门全瞎。三层执法沿用 v1/U2/V2 同型（**组合复用 v1 门的结构判据，不复制第二扫描器**——铁律 7 禁第三套）：

- **活性 ledger（真树）**：media/TTS 族直呼面 + invoker 面 == 本席实测登记，任一侧漂移当场红。
- **注毒自证（合成树）**：新增直呼点 / 第二 invoker 点 / 半迁移 / 通电后又直呼 四种各真的会红。
- **端到端逐字段等值 + 机制自证**：fixture **局部** ``CapabilityInvoker``（不碰 default_invoker 单例、
  不给生产加旁路）注册 descriptor + adapter（S-MEDIA §B-2 交接块的可执行化身），invoke 产出的
  呈现契约 ``data[PRESENTATION_DATA_KEY]`` 与直呼 ``build_tts_capability`` handler 的
  ``CapabilityResult.model_dump()`` 逐字段相等（命令路 + 合成成功路各一条）；摘 descriptor / 摘 handler
  ⇒ 诚实 FAILED / UNAVAILABLE 不崩、不携带呈现载荷，且旧直呼路径仍全绿（「未接线→回落」判据）。

全离线：零网络、零消息发送、零真实 TTS 调用（绝不打引擎、绝不碰无鉴权的 /control）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 复用 v1 门的结构判据与不变量检查器（同目录顶层导入，pytest 已把 tests/ 放上 sys.path）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as v1gate

_PKG_ROOT = v1gate._PKG_ROOT
_SHELL_REL = "runtime/capability_protocols.py"  # 受控适配器不算「域直呼」（同 v1 门）

# TTS 真身/工厂 + media 呈现能力 builder → (能力族键, 定义文件豁免)。
# 定义文件豁免同 v1：真身在**自己 module 内**自用（如 tts.py capability 调 synthesize）
# 属实现细节，不是「第二能力执行入口」。
_TRACKED_MEDIA: dict[str, tuple[str, str]] = {
    "build_tts_capability": ("bot.tts.command", "domains/media/capabilities/tts.py"),
    "maybe_attach_voice": ("bot.tts.autovoice", "domains/media/capabilities/tts.py"),
    "synthesize": ("bot.tts.synth", "domains/media/capabilities/tts.py"),
    # VOICE-V12 第二出站腿：合成这一步的单一真身（synthesize 直呼的唯一新落点，
    # 只被中央 handler 经 shell（跳过扫描）+ 本定义文件（豁免）消费，跨文件直呼面为空）。
    "synthesize_autodub": ("media.tts.autodub", "domains/media/capabilities/tts.py"),
    "build_image_search_capability": ("bot.image_search", "domains/media/capabilities/image_search.py"),
    "build_media_archive_capability": ("bot.media_archive", "domains/media/capabilities/media_archive.py"),
}
_ALL_CAPS = sorted({cap for cap, _ in _TRACKED_MEDIA.values()})


# ---------------------------------------------------------------------------
# 扫描器（组合复用 v1 门的 _execution_calls / _invoker_cids，可喂真树或合成树）
# ---------------------------------------------------------------------------
def scan(index: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    direct: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS}
    invoker: dict[str, set[str]] = {cap: set() for cap in _ALL_CAPS}
    for rel, src in index.items():
        if rel == _SHELL_REL:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for symbol, (cap, def_file) in _TRACKED_MEDIA.items():
            if rel != def_file and symbol in src and v1gate._execution_calls(tree, symbol):
                direct[cap].add(rel)
        for cid in v1gate._invoker_cids(tree):
            if cid in invoker:
                invoker[cid].add(rel)
    return direct, invoker


def _load_real_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sym in text for sym in _TRACKED_MEDIA) or "capability_id=" in text:
            index[rel] = text
    return index


# ---------------------------------------------------------------------------
# media/TTS ledger（2026-09-22 S-MEDIA 实测登记，逐条见 SEAT-S-MEDIA §A；
#   VOICE-V12 2026-09-22 翻面：bot.tts.synth 跨文件直呼清零 → 改走 media.tts.autodub invoker）
#   bot.tts 命令路：build_tts_capability 作泛型执行器实参（不落 Call）→ 直呼面空（Wave4.1 盲区）。
#   bot.tts 自动配音旧包装：maybe_attach_voice 作 asyncio.to_thread 实参 → 直呼面空。
#   synthesize：VOICE-V12 前唯一跨文件直呼=voice_enricher.py:175，现该直呼段改走
#       default_invoker().invoke(capability_id="media.tts.autodub") → synthesize 直呼面归零。
#   media.tts.autodub：自动配音产出步，直呼面空（真身 synthesize_autodub 只在 tts 定义文件+
#       中央 shell handler 出现，两处均豁免/跳过），invoker 面恰一处=voice_enricher.py → WIRED。
#   bot.image_search / bot.media_archive：各自独立 root handler 直呼 factory（Wave1 可逐能力翻面）。
# ---------------------------------------------------------------------------
KNOWN_DIRECT_ALLOWLIST_MEDIA: dict[str, set[str]] = {
    "bot.tts.command": set(),
    "bot.tts.autovoice": set(),
    "bot.tts.synth": set(),
    "media.tts.autodub": set(),
    "bot.image_search": {"__init__.py"},
    "bot.media_archive": {"__init__.py"},
}
WIRED_MEDIA: set[str] = {"media.tts.autodub"}
KNOWN_INVOKER_SITES_MEDIA: dict[str, set[str]] = {
    "media.tts.autodub": {"domains/media/voice_enricher.py"},
}


def test_real_tree_matches_media_tts_ledger() -> None:
    """活性判据：真树直呼/invoker == 评审过的 media/TTS ledger，任一漂移当场红。"""
    direct, invoker = scan(_load_real_index())
    assert direct == KNOWN_DIRECT_ALLOWLIST_MEDIA, (
        f"直呼面漂移：实得 {direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST_MEDIA}"
    )
    actual_invoker = {cap: mods for cap, mods in invoker.items() if mods}
    assert actual_invoker == KNOWN_INVOKER_SITES_MEDIA, (
        f"invoker 调用点漂移：实得 {actual_invoker} ≠ 登记 {KNOWN_INVOKER_SITES_MEDIA}"
    )
    assert v1gate.check_invariants(
        direct, invoker, wired=WIRED_MEDIA, allowlist=KNOWN_DIRECT_ALLOWLIST_MEDIA
    ) == []


def test_media_tts_symbols_are_actually_tracked() -> None:
    """覆盖面自证：六个真身都在追踪表、定义文件在 media 域，且 tts.py 内自用不算直呼（门不哑）。"""
    assert set(_TRACKED_MEDIA) == {
        "build_tts_capability",
        "maybe_attach_voice",
        "synthesize",
        "synthesize_autodub",
        "build_image_search_capability",
        "build_media_archive_capability",
    }
    for symbol, (_cap, def_file) in _TRACKED_MEDIA.items():
        assert def_file.startswith("domains/media/"), f"{symbol} 定义文件坐标漂移"
    _direct, _invoker = scan({"domains/media/capabilities/tts.py": "def f(c):\n    return synthesize(1)\n"})
    assert _direct["bot.tts.synth"] == set(), "真身同文件自用被误判为第二直呼点"


# ---------------------------------------------------------------------------
# 注毒自证（合成树，非真树；证明每条不变量真的会红，防「存在性糊过活性判据」假门）
# ---------------------------------------------------------------------------
def _poison_direct(mod: str, symbol: str) -> dict[str, str]:
    return {mod: f"from x import {symbol}\ndef f(cfg):\n    return {symbol}(cfg)\n"}


def test_poison_new_direct_site_is_red() -> None:
    """注毒①：allowlist 之外新增一处 synthesize 直呼点 → 「未登记直呼点」红。"""
    direct, invoker = scan(_poison_direct("domains/meme/capabilities/sneaky.py", "synthesize"))
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_MEDIA, allowlist=KNOWN_DIRECT_ALLOWLIST_MEDIA
    )
    assert any("未登记直呼点" in s and "bot.tts.synth" in s for s in v), f"注毒①未被拦：{v}"


def test_poison_second_invoker_site_is_red() -> None:
    """注毒②：两模块各 invoke bot.media_archive → 「第二调用点」红。

    刻意用真实能力 id（=扫描器 invoker 字典的键）而非族键 bot.tts.*——bot.tts 命令路的族键
    不等于能力 id，喂 capability_id="bot.tts" 不进字典（正合泛型执行器盲区：无逐能力翻面点）。
    """
    src = "def f():\n    default_invoker().invoke(CapabilityRequest(capability_id='bot.media_archive'))\n"
    direct, invoker = scan({"m1.py": src, "m2.py": src})
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_MEDIA, allowlist=KNOWN_DIRECT_ALLOWLIST_MEDIA
    )
    assert any("第二调用点" in s and "bot.media_archive" in s for s in v), f"注毒②未被拦：{v}"


def test_poison_half_migration_is_red() -> None:
    """注毒③：同模块既直呼 build_media_archive_capability 又 invoke bot.media_archive → 「半迁移」红。"""
    src = (
        "from plugins.bot_unified_runtime.domains.media.capabilities.media_archive"
        " import build_media_archive_capability\n"
        "def f(cfg):\n"
        "    build_media_archive_capability(cfg)\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='bot.media_archive'))\n"
    )
    direct, invoker = scan({"domains/media/half.py": src})
    v = v1gate.check_invariants(
        direct, invoker, wired=WIRED_MEDIA, allowlist=KNOWN_DIRECT_ALLOWLIST_MEDIA
    )
    assert any("半迁移" in s and "bot.media_archive" in s for s in v), f"注毒③未被拦：{v}"


def test_wired_invariant_binds_after_migration() -> None:
    """注毒④（通电判据的杀伤力）：把已直呼的 bot.image_search 标为通电 → 直呼面存在即红。

    主会话在 Wave1/3 翻 bot.image_search 后须同时把它并入 WIRED，否则忘切直呼不会被抓到。
    """
    direct, invoker = scan(_load_real_index())
    v = v1gate.check_invariants(
        direct, invoker, wired={"bot.image_search"}, allowlist=KNOWN_DIRECT_ALLOWLIST_MEDIA
    )
    assert any("已通电却仍直呼真身" in s and "bot.image_search" in s for s in v), (
        f"通电判据无牙：{v}"
    )


# ---------------------------------------------------------------------------
# 局部 invoker（S-MEDIA §B-2 交接块的可执行化身；不碰 default_invoker 单例、生产零旁路）
# ---------------------------------------------------------------------------
def _local_tts_invoker(*, with_descriptor: bool, with_handler: bool = True):
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        CapabilityDescriptor,
        CapabilityFamily,
        CapabilityInvoker,
        CapabilityRegistry,
        HandlerRegistry,
        InvocationResult,
        InvocationStatus,
    )

    registry = CapabilityRegistry()
    handlers = HandlerRegistry()
    if with_descriptor:
        # 数值零硬编码：limits 留空（顶在 handler 现读 config.bot_tts_*），见 SEAT-S-MEDIA §B-1。
        registry.register(
            CapabilityDescriptor(
                capability_id="bot.tts",
                family=CapabilityFamily.MEDIA,
                title="语音合成（守岸人音色）",
                input_protocol="bot.v1 TtsCommandRequest{message, decision}",
                output_protocol=f"presentation v1 CapabilityResult @ data[{PRESENTATION_DATA_KEY}]",
                required_roles=("user",),
                fallback_chain=("honest_degrade:合成失败=温和降级",),
            )
        )

    def _handle(request) -> InvocationResult:
        from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
            build_tts_capability,
        )

        presented = build_tts_capability(request.context["config"])(
            request.payload["message"], request.payload.get("decision")
        )
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.OK,
            data={PRESENTATION_DATA_KEY: presented.model_dump()},
            via="tts",
        )

    if with_handler:
        handlers.register("bot.tts", _handle)
    return CapabilityInvoker(registry=registry, handlers=handlers)


def _tts_config() -> SimpleNamespace:
    # 能力层全程 getattr(config, ..., 缺省)——最小 SimpleNamespace 即可驱动到确定性分支。
    return SimpleNamespace(
        bot_tts_enabled=True,
        bot_tts_ref_audios=[],
        bot_tts_trigger_words=[],
        bot_tts_max_chars=200,
        bot_tts_hard_max_chars=0,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_timeout_seconds=60.0,
    )


def _tts_message(text: str):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="qq", adapter="onebot11", bot_id="10000",
        session_id="private:20000", session_type=SessionType.PRIVATE,
        sender_id="20000", plain_text=text,
    )


def _assert_presentation_equals(envelope, direct_result) -> None:
    """信封里装的呈现契约与直呼真身返回值逐字段全等（返回体/文案/audit_tags/send_policy
    一字不改——接入只换调用点，不改产出）。唯一豁免 debug_id（每次构造随机对账 id）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        PRESENTATION_DATA_KEY,
        InvocationStatus,
    )

    assert envelope.status is InvocationStatus.OK
    payload = envelope.data[PRESENTATION_DATA_KEY]
    assert isinstance(payload, dict), "呈现载荷必须是 model_dump dict，非活模型对象"
    invoked = dict(payload)
    direct = direct_result.model_dump()
    inv_dbg, dir_dbg = invoked.pop("debug_id", None), direct.pop("debug_id", None)
    assert inv_dbg and dir_dbg, "两路都照常产出 debug_id 对账字段"
    assert invoked == direct, "经 invoker 的呈现契约与直呼真身不逐字段等值"


def test_e2e_bot_tts_no_ref_audio_equals_direct() -> None:
    """命令路逐字段等值：无参考音频的确定性降级分支（零 HTTP），invoker vs 直呼全等。"""
    from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
        build_tts_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    msg = _tts_message("说 今天的潮汐很安静")
    inv = _local_tts_invoker(with_descriptor=True)
    envelope = inv.invoke(
        CapabilityRequest(
            capability_id="bot.tts",
            payload={"message": msg},
            principal="u1",
            roles=("user",),
            context={"config": _tts_config()},
        )
    )
    direct = build_tts_capability(_tts_config())(msg, None)
    assert "参考音频" in direct.body  # 两路同打这条确定性无-ref 分支
    _assert_presentation_equals(envelope, direct)


def test_e2e_bot_tts_success_audio_path_equals_direct(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """合成成功路逐字段等值：monkeypatch pick_ref_audio + synthesize → 产 audio 部件+摘要，
    证明「带音频的呈现契约」也经信封 byte-identical 流转（真实成功路径，不只是降级分支）。"""
    import plugins.bot_unified_runtime.domains.media.capabilities.tts as tts_mod
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    wav = tmp_path / "tts-out.wav"
    wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    ref = tts_mod.RefAudio(path=str(tmp_path / "ref.wav"), text="", lang="zh")
    monkeypatch.setattr(tts_mod, "pick_ref_audio", lambda *a, **k: ref)
    monkeypatch.setattr(tts_mod, "synthesize", lambda **kw: (wav, ""))

    msg = _tts_message("说 你好")
    inv = _local_tts_invoker(with_descriptor=True)
    envelope = inv.invoke(
        CapabilityRequest(
            capability_id="bot.tts",
            payload={"message": msg},
            principal="u1",
            roles=("user",),
            context={"config": _tts_config()},
        )
    )
    direct = tts_mod.build_tts_capability(_tts_config())(msg, None)
    assert direct.audio, "成功路应带 audio 部件（否则此用例没测到关键分支）"
    _assert_presentation_equals(envelope, direct)


def test_descriptor_or_handler_missing_falls_back_honestly() -> None:
    """摘 descriptor ⇒ FAILED；descriptor 在册但 handler 未接线 ⇒ UNAVAILABLE。
    两者都带诚实 detail、不携带呈现载荷，且旧直呼路径照旧全绿（「未接线→回落」判据）。"""
    from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
        build_tts_capability,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
    )

    msg = _tts_message("说 你好")

    def _req() -> CapabilityRequest:
        return CapabilityRequest(
            capability_id="bot.tts", payload={"message": msg},
            principal="u1", roles=("user",), context={"config": _tts_config()},
        )

    no_desc = _local_tts_invoker(with_descriptor=False).invoke(_req())
    assert no_desc.status is InvocationStatus.FAILED  # 未登记能力：诚实拒绝而非静默
    assert no_desc.detail.strip() and "presentation_result" not in no_desc.data

    no_handler = _local_tts_invoker(with_descriptor=True, with_handler=False).invoke(_req())
    assert no_handler.status is InvocationStatus.UNAVAILABLE
    assert no_handler.detail.strip() and "presentation_result" not in no_handler.data

    # 回落自证：descriptor/handler 缺席时，旧直呼路径仍产出（本席生产码零切换的证据）。
    legacy = build_tts_capability(_tts_config())(msg, None)
    assert legacy.body


def test_default_invoker_governs_bot_tts_from_route_execution_facet() -> None:
    """本席首稿锁的是「bot.tts 尚未在册」——主会话落 A 案（注册册 execution 面）后
    前提过期，按本席原注释「届时应改写而非默默放行」改写为**正向真值锁**：

    ① bot.tts 在唯一表且有信封 handler；② 表内**不持有任何 TTS 数值**（limits 空，
    生效顶唯一家仍是 tts_presets.resolve_*）；③ 载荷缺失 ⇒ 诚实 FAILED，不再伪装成功。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    invoker = cp.default_invoker()
    row = cp._DESCRIPTOR_VIEW.get("bot.tts")
    assert row is not None, "A 案派生描述符消失（注册册 execution 面被摘？）"
    assert row.limits == {}, f"表内又拿数值当天花板：{row.limits}"
    assert invoker.handlers.get("bot.tts") is not None, "在册却无信封 handler=假可执行"
    result = invoker.invoke(
        cp.CapabilityRequest(capability_id="bot.tts", payload={}, principal="u1", roles=("user",))
    )
    assert result.status is cp.InvocationStatus.FAILED
    assert "payload.message" in result.detail
