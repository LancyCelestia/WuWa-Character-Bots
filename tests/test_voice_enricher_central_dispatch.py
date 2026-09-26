"""S-VOICE · 自动配音第二出站腿 vs 中央能力调度器（mandate：所有内容走中央调度层，TTS 也不例外）。

事实基线（VOICE-V12 翻面后，2026-09-22）：
- 命令腿 ``bot.tts`` 早已通电中央（capability_registry 路由行 execution.adapter="command"，
  经 runtime/capability_protocols.py::orchestrated_command → default_invoker().invoke）。
- 自动配音腿 ``domains/media/voice_enricher.py``：G-3 起在 pipeline review 批准后（pipeline.py:810-811）
  被调用，历史形态于 ``:175`` **直连 ``synthesize(...)``**（旁路，层 2 不执法），由
  tests/test_orchestration_callsite_wave_media.py 钉为在册直呼。VOICE-V12 已把该直呼段
  换成 ``default_invoker().invoke(CapabilityRequest(capability_id="media.tts.autodub", …))``：
  合成这一步成为 media 族内容契约能力（descriptor + 中央 handler），层 2（权限/健康/90s 超时/
  降级/中央审计）对它执法；门链（该不该配）与取文/政策/硬顶仍留层 1 hook（每条「不配」零合成、零审计行）。

本文件是**常态化正向锁**（不再是旁路判据、不再挂 xfail；判据方向由「合成未走中央」翻成「合成必经
中央、且层 1 不再直呼 synthesize」，强度不降——反而更硬：既测行为、又测结构）：

- ``test_auto_voice_leg_reaches_central_invoker_exactly_once`` —— 行为判据：门链放行的一次配音，
  合成恰经 ``default_invoker().invoke("media.tts.autodub")`` **恰一行**，产物音频挂回呈现结果。
- ``test_auto_voice_leg_no_longer_calls_synthesize_directly`` —— 结构判据：voice_enricher 源码里
  已**无** ``synthesize(...)`` 直呼（AST），且 ``invoke(capability_id="media.tts.autodub")`` **恰一处**；
  真正的 synthesize 落点只剩中央 handler 一处（经 tts 域内 ``synthesize_autodub`` 真身）。

全离线零网络：``synthesize``/``resolve_speech_text``/``should_voice_reply`` 一律 monkeypatch，
落盘只写 tmp_path（合成原语经 context 注入到产出步 seam，与生产同一真身、逐字节等价）。
"""

from __future__ import annotations

import ast
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as v1gate  # 复用直呼/invoker 判据真身（不留第二支扫描器）
import test_v21_s10_protocols as s10  # S135 段复用其自定义注册面夹具（不留第二份测试脚手架）

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
)
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_VE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "voice_enricher.py"
)

#: S270 归位后，产出步的单一组合口（全树唯一 autodub invoke 点）住在 result_transform。
_RT_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "tts"
    / "result_transform.py"
)

_AUTODUB_CID = "media.tts.autodub"
_TRANSFORM_CID = "media.tts.autodub_transform"


# ---------------------------------------------------------------------------
# 离线夹具（与 tests/test_voice_hook_assembly.py::_hook_config 同构，只保留必要键）
# ---------------------------------------------------------------------------


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        group_id="",
        plain_text="今天天气不错",
        message_id="m-1",
        debug_id="dbg-1",
    )


def _decision() -> BotDecision:
    return BotDecision(
        request_id="req-1",
        should_respond=True,
        mode="command",
        trigger="你好",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        decision_reason="test",
    )


def _result() -> CapabilityResult:
    return CapabilityResult(
        request_id="req-1",
        capability_id="bot.chat",
        kind="text",
        body="潮汐今天很安静。",
        send_policy=SendPolicy.IMMEDIATE,
        audit_tags=["chat"],
    )


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_tts_voice_hook_enabled=True,
        bot_tts_enabled=True,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_gptsovits_dir="",
        bot_tts_ref_audios=[f"{tmp_path / 'ref.wav'}|参考文本|zh"],
        bot_tts_trigger_words=[],
        bot_tts_output_dir=str(tmp_path / "tts_out"),
        bot_tts_preset="shorekeeper",
        bot_tts_max_chars=200,
        bot_tts_hard_max_chars=2000,
        bot_tts_max_audio_bytes=0,
        bot_tts_cache_enabled=False,
        bot_tts_cache_max_bytes=0,
        bot_tts_cache_max_age_days=0,
        bot_tts_timeout_seconds=60.0,
        bot_tts_speed_factor=0.85,
        bot_tts_temperature=0.9,
        bot_tts_top_k=15,
        bot_tts_top_p=1.0,
        bot_tts_text_lang="zh",
        bot_tts_text_split_method="cut5",
        bot_tts_auto_reply_enabled=True,
        bot_tts_auto_reply_scope="private",
        bot_tts_auto_reply_max_chars=120,
        bot_tts_auto_reply_probability=1.0,
        bot_tts_auto_reply_always=True,
    )


@pytest.fixture()
def armed_enricher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """构建「门链全通、合成经中央 seam、invoker 被监视」的 enricher。

    返回 (enricher, synth_calls, invoker_calls)。合成经 default_invoker().invoke →
    media.tts.autodub handler → tts.synthesize_autodub(synth=ve.synthesize 注入替身) 落回 seam，
    故 synth_calls 记录被执行的文本、invoker_calls 记录中央被调 capability_id。
    """
    import plugins.bot_unified_runtime.domains.media.tts.result_transform as rt
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    (tmp_path / "ref.wav").write_bytes(b"RIFFref")
    wav = tmp_path / "fake.wav"
    wav.write_bytes(b"RIFFfake")

    synth_calls: list[str] = []

    def fake_synthesize(**kwargs: object):
        synth_calls.append(str(kwargs.get("text")))
        return wav, ""

    # 隔离门链谓词（本件只测「是否经中央 invoker」，不重测 T75 在飞改造的门链）。
    # 收编后取文/门链在中央第三形真身 result_transform 的命名空间里跑（不再是 hook 内联），
    # 故 resolve_speech_text/should_voice_reply 的替身要同时钉在 ve（hook 前门）与 rt（真身）
    # 两处：should_voice_reply 是纯谓词、生产两处同函数天然幂等；测试分别钉以隔离他席在飞。
    monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    monkeypatch.setattr(rt, "should_voice_reply", lambda *a, **k: True)
    monkeypatch.setattr(
        rt, "resolve_speech_text", lambda *a, **k: ("潮汐今天很安静。", "")
    )
    # 合成原语在产出步 seam 注入确定性替身（生产传的是同一 tts.synthesize 本体，逐字节等价）。
    monkeypatch.setattr(ve, "synthesize", fake_synthesize)

    invoker_calls: list[str] = []
    real_invoke = cp.CapabilityInvoker.invoke

    def spy_invoke(self: object, request: object, *a: object, **k: object):
        invoker_calls.append(getattr(request, "capability_id", "<unknown>"))
        return real_invoke(self, request, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", spy_invoke)

    config = _config(tmp_path)
    return ve.build_voice_enricher(config), synth_calls, invoker_calls


# ---------------------------------------------------------------------------
# 行为正向锁：合成恰经中央 invoker 恰一行、产物挂回
# ---------------------------------------------------------------------------


def test_auto_voice_leg_reaches_central_invoker_exactly_once(
    armed_enricher: tuple,
) -> None:
    enricher, synth_calls, invoker_calls = armed_enricher

    enriched = enricher(_message(), _decision(), _result())

    # 前置自证：门链放行、合成确已发生（否则「中央两腿」是空断言）。
    assert synth_calls == ["潮汐今天很安静。"], synth_calls
    assert enriched.audio, "合成产物应已挂回呈现结果"

    # 承重判据（S91 收编后加强，方向从「合成必经中央一行」翻成「变换＋合成都必经中央、
    # 且先变换后合成」）：hook 派中央第三形 media.tts.autodub_transform（呈现结果→带音频
    # 结果）一次，其内产出步 dub 再派 media.tts.autodub 一次 ⇒ 恰两行、顺序固定。
    # 任一腿退回直呼（少一行）或另造第二通路（多一行/顺序乱）都会打红本锁。
    assert invoker_calls == [_TRANSFORM_CID, _AUTODUB_CID], (
        "自动配音须经中央『变换→合成』两行、顺序固定（实得 "
        f"{invoker_calls}）——旁路回潮、双调用或换序都会打红本锁"
    )


# ---------------------------------------------------------------------------
# 结构正向锁：层 1 不再直呼 synthesize；中央 invoke 站点恰一处
# ---------------------------------------------------------------------------


def test_auto_voice_leg_no_longer_calls_synthesize_directly() -> None:
    src = _VE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # ①直呼旁路已闭合：voice_enricher 内不存在 ``synthesize(...)`` 执行直呼
    #   （synthesize 只作为可注入原语随请求 context 交中央，不再在本模块被调用）。
    assert not v1gate._execution_calls(tree, "synthesize"), (
        "voice_enricher 重新直呼 synthesize ⇒ 自动配音腿回退为旁路，本锁必红"
    )

    # ②产出步的 media.tts.autodub 中央 invoke 恰一处（S270 归位后落在单一组合口
    #   result_transform.dub_via_central，不再在 hook 里）：计数走 AST，文档字符串里的同名
    #   字面量不算调用点（literal 计数会被 docstring 骗，本仓「存在性糊过活性」变体）。
    #   hook 侧改为**零处**（它只调 rt.dub_via_central，不再自持那份 invoke）⇒ 两处必须
    #   同时成立才叫"归位而非另加一份"（组合口恰一处 + 退役旧点位），强度不降反升。
    ve_sites = _autodub_invoke_sites(tree)
    assert ve_sites == 0, (
        "voice_enricher 仍自持 media.tts.autodub 的 invoke ⇒ 产出步没归位到单一组合口、"
        f"与 result_transform 那处并存＝第二通路（实得 {ve_sites}）"
    )
    rt_sites = _autodub_invoke_sites(ast.parse(_RT_SOURCE.read_text(encoding="utf-8")))
    assert rt_sites == 1, (
        "media.tts.autodub 的唯一 invoke 点须在单一组合口 result_transform.dub_via_central"
        f"（恰一处，实得 AST 计数={rt_sites}）——零处=没归位，两处=第二通路"
    )


def _autodub_invoke_sites(tree: ast.AST) -> int:
    """``….invoke(CapabilityRequest(capability_id="media.tts.autodub", …))`` 的调用点个数。"""
    total = 0
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "invoke"
        ):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(node, ast.Call)
                and isinstance(sub, ast.keyword)
                and sub.arg == "capability_id"
                and isinstance(sub.value, ast.Constant)
                and sub.value.value == _AUTODUB_CID
            ):
                total += 1
                break
    return total


# ---------------------------------------------------------------------------
# S91 收编：中央第三形（result_transform）已接线，且内联变换已退役（只有一份真身）
# ---------------------------------------------------------------------------


def _cid_invoke_sites(tree: ast.AST, cid: str) -> int:
    """``….invoke(CapabilityRequest(capability_id=<cid>, …))`` 的调用点个数（参数化）。"""
    total = 0
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "invoke"
        ):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.keyword)
                and sub.arg == "capability_id"
                and isinstance(sub.value, ast.Constant)
                and sub.value.value == cid
            ):
                total += 1
                break
    return total


def test_auto_voice_leg_dispatches_central_transform_exactly_once() -> None:
    """结构正向锁：voice_enricher 恰好派一次中央第三形 media.tts.autodub_transform。"""
    src = _VE_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert _cid_invoke_sites(tree, _TRANSFORM_CID) == 1, (
        "media.tts.autodub_transform 的 invoke 调用点须恰一处（实得 "
        f"{_cid_invoke_sites(tree, _TRANSFORM_CID)}）——零处=没接第三形，两处=第二通路"
    )


def test_inline_transform_machinery_retired_from_hook() -> None:
    """退役证明（两存即第二真身，一票否决）：voice_enricher 源码里不得再出现被搬进
    中央真身 result_transform 的变换机器（取文/硬顶/拆条/出站挂回/无参考音 issue）的调用。

    只查 AST 里的**函数调用/属性访问**（文档字符串的同名散文不算——那是 Constant 节点，
    不是 Name/Attribute 调用），避免"存在性糊过活性"的旧坑反向变成"文档骗锁"。
    """
    tree = ast.parse(_VE_SOURCE.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    banned = {
        "resolve_speech_text",
        "autodub_presentation_update",
        "resolve_hard_max_chars",
        "split_speech_chunks",
        "_no_ref_audio_issue",
    }
    leaked = sorted(called & banned)
    assert not leaked, (
        f"voice_enricher 又直呼被搬进中央真身的变换机器（第二真身/未退役）：{leaked}"
    )


def test_central_transform_dispatch_reaches_registered_handle(
    armed_enricher: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """活性判据（简报"证明三件事"之二，非"函数存在"）：

    ① 中央派发谱真认这第三形——default_invoker 里有 descriptor + handler；
    ② voice_enricher 走的是**注册执行体的 handle**——真跑到 result_transform.handle 恰一次，
       且经它交回的呈现结果被 hook 读回（不是旁路、不是"函数存在"就算）。
    """
    from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt

    invoker = cp.default_invoker()
    # ①在册且可派到：descriptor + handler 都在（缺任一 ⇒ invoke 得 FAILED/UNAVAILABLE）。
    assert invoker.registry.get(_TRANSFORM_CID) is not None, "第三形未在册 descriptor"
    assert invoker.handlers.get(_TRANSFORM_CID) is not None, "第三形未接线 handler（在册未执行）"

    # ②真跑到注册执行体的 handle：包一层哨兵（记录后原样委派真身），断言恰调一次。
    handle_calls: list[str] = []
    real_handle = rt.handle

    def spy_handle(request: object):
        handle_calls.append(getattr(request, "capability_id", "<unknown>"))
        return real_handle(request)

    monkeypatch.setattr(rt, "handle", spy_handle)

    enricher, synth_calls, _invoker_calls = armed_enricher
    enriched = enricher(_message(), _decision(), _result())

    assert handle_calls == [_TRANSFORM_CID], (
        f"注册的 result_transform.handle 须经中央派发恰跑到一次（实得 {handle_calls}）"
    )
    assert synth_calls == ["潮汐今天很安静。"], "handle 内产出步确已执行（非空跑到）"
    assert enriched.audio, "handle 交回的带音频呈现结果被 hook 读回（贯穿闭合）"


# ---------------------------------------------------------------------------
# 注毒自证（不落盘改生产件；合成源码/内存替身，证明锁真有牙）
# ---------------------------------------------------------------------------
def test_retire_lock_fires_on_synthetic_reinlined_transform() -> None:
    """毒①自证（"改回内联那份变换⇒活性锁必红"）：把退役判据喂一份"重新内联"的合成源码，
    断言它判红——否则"退役锁零命中"可能只是尺子瞎（本仓踩过的"存在性糊过活性"变体）。"""
    reinlined = (
        "from x import autodub_presentation_update, resolve_speech_text\n"
        "def _enrich_locked(result, config, message):\n"
        "    speech, blocked = resolve_speech_text(config, message, result.body)\n"
        "    return result.model_copy(update=autodub_presentation_update(result, {}))\n"
    )
    tree = ast.parse(reinlined)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    banned = {
        "resolve_speech_text",
        "autodub_presentation_update",
        "resolve_hard_max_chars",
        "split_speech_chunks",
        "_no_ref_audio_issue",
    }
    assert called & banned, '退役判据看不见「重新内联」形态＝尺子瞎，本自证失守'
    # 现盘 voice_enricher 用同一判据必须是零命中（否则正锁早该红）。
    real = ast.parse(_VE_SOURCE.read_text(encoding="utf-8"))
    real_called: set[str] = set()
    for node in ast.walk(real):
        if isinstance(node, ast.Call):
            real_called.add(
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
    assert not (real_called & banned), f"退役锁对现盘失守（现盘竟仍有内联机器）：{real_called & banned}"


def test_enrich_treats_ok_envelope_without_payload_as_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒③（"变换形自称 ok 却无产物"⇒ 不许当成功）：注入一枚 OK 但缺 PRESENTATION_DATA_KEY
    的信封 ⇒ hook 必须诚实挂 issue（不静默把"没产出"当"配好了"）。
    """
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    (tmp_path / "ref.wav").write_bytes(b"RIFFref")

    class _FakeLiarInvoker:
        def invoke(self, request: object) -> cp.InvocationResult:
            return cp.InvocationResult(
                capability_id=getattr(request, "capability_id", "?"),
                status=cp.InvocationStatus.OK,  # 自称成功，却不带呈现载荷
                detail="result_transform:FAKE",
                data={},
            )

    monkeypatch.setattr(ve, "default_invoker", lambda: _FakeLiarInvoker())
    monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    enricher = ve.build_voice_enricher(_ok_config(tmp_path))
    original = _result()
    enriched = enricher(_message(), _decision(), original)

    assert enriched.operational_issue is not None, (
        "OK 却无产物的信封被当成配音成功静默放行＝造绿（假产物不许 OK）"
    )
    assert enriched.audio == [] and enriched.body == original.body, (
        "假产物下正文照发、不得凭空出音频"
    )


def _ok_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_tts_voice_hook_enabled=True,
        bot_tts_enabled=True,
        bot_tts_api_url="http://127.0.0.1:9880",
        bot_tts_gptsovits_dir="",
        bot_tts_ref_audios=[f"{tmp_path / 'ref.wav'}|参考文本|zh"],
        bot_tts_output_dir=str(tmp_path / "tts_out"),
        bot_tts_hard_max_chars=2000,
        bot_tts_auto_reply_max_chars=0,
    )

# ===========================================================================
# S135 · 一次配音在 cap-proto 池只占一枚
# （RULINGS-20260924.md 第 7 项＝「改 V2 只接层 1」；索引 CM-P-45 ① / 背景 SEAT-S91 §2 差异⑤）
#
# 口径：中央第三形 media.tts.autodub_transform 的**在册与派发都不动**（层 1 呈现变换仍由
# 中央执行、层 2 门与审计照旧）；改的是**嵌套那一档的占位**——内层产出步 media.tts.autodub
# 从「再向共享池要一枚 worker」变成「跑在外层同一枚 worker 上」。
# 本段四把锁各钉一件事，少一把就有一个失败形态能静默过关：
# ①占用账（一次配音只提交一次池）②吞吐账（现算池宽那么多条配音同时在飞，防"降成串行"）
# ③内联≠绕中央件（嵌套那枚仍过角色门、仍落审计行）④两头都钉（顶层仍进池、标记逐任务回退）。
# ===========================================================================

#: 现算池宽（写死数字＝把账本搬进测试，池一改宽这批锁就失真）。
_POOL_WIDTH = cp._MAX_WORKERS


class _CountingPool(ThreadPoolExecutor):
    """数得清的池：提交次数 / 同时在飞高水位 / 真正跑过任务的线程名。

    只在本段测试里替换 ``cp._get_capability_executor``，不碰生产单例
    （``_EXECUTOR`` 全程保持 ``None``，与 conftest 的模块边界收口判据不冲突）。
    线程前缀刻意**不叫** ``cap-proto``：那是 tests/test_render_pool_hygiene.py 的扫描口径。
    """

    def __init__(self, max_workers: int) -> None:
        super().__init__(max_workers=max_workers, thread_name_prefix="s135-pool")
        self._gate = threading.Lock()
        self.submits = 0
        self.inflight = 0
        self.high_water = 0
        self.ran_threads: list[str] = []

    def submit(  # type: ignore[override]
        self, fn: Callable[..., object], *args: object, **kwargs: object
    ) -> Future[object]:
        with self._gate:
            self.submits += 1

        def _counted() -> object:
            with self._gate:
                self.inflight += 1
                self.high_water = max(self.high_water, self.inflight)
                self.ran_threads.append(threading.current_thread().name)
            try:
                return fn(*args, **kwargs)
            finally:
                with self._gate:
                    self.inflight -= 1

        return super().submit(_counted)


def _voice_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pool: _CountingPool,
    *,
    dub_barrier: threading.Barrier | None = None,
) -> tuple:
    """装配「门链全通、合成经中央、池换成可数池」的配音链，返回 ``(enricher, 线程账)``。

    两笔取样：``outer``=中央第三形执行体内（transform handler 那枚 worker）、
    ``synth``=产出步 seam 内（内层 autodub 那一步）。两档同枚 ⇒ 嵌套确已内联。
    """
    import plugins.bot_unified_runtime.domains.media.tts.result_transform as rt
    import plugins.bot_unified_runtime.domains.media.voice_enricher as ve

    (tmp_path / "ref.wav").write_bytes(b"RIFFref")
    wav = tmp_path / "fake.wav"
    wav.write_bytes(b"RIFFfake")

    lock = threading.Lock()
    seen: dict[str, list[str]] = {"outer": [], "synth": []}

    def fake_resolve(*a: object, **k: object) -> tuple[str, str]:
        with lock:
            seen["outer"].append(threading.current_thread().name)
        return "潮汐今天很安静。", ""

    def fake_synthesize(**kwargs: object):
        if dub_barrier is not None:
            dub_barrier.wait(timeout=10.0)
        with lock:
            seen["synth"].append(threading.current_thread().name)
        return wav, ""

    monkeypatch.setattr(ve, "should_voice_reply", lambda *a, **k: True)
    monkeypatch.setattr(rt, "should_voice_reply", lambda *a, **k: True)
    monkeypatch.setattr(rt, "resolve_speech_text", fake_resolve)
    monkeypatch.setattr(ve, "synthesize", fake_synthesize)
    monkeypatch.setattr(cp, "_get_capability_executor", lambda: pool)
    return ve.build_voice_enricher(_config(tmp_path)), seen


def test_single_dubbing_takes_exactly_one_pool_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """占用账：一次完整配音向共享池**只提交一次**、同时在飞只有一枚。

    改前实算＝2 枚（外层 transform 一枚 + 内层 autodub 一枚，外层在内层跑完前不放手）。
    ``submits``/``high_water`` 一旦变大即红＝双占位回潮。
    """
    pool = _CountingPool(_POOL_WIDTH)
    try:
        enricher, seen = _voice_chain(tmp_path, monkeypatch, pool)
        enriched = enricher(_message(), _decision(), _result())

        # 前置自证：配音真完成了，否则"只占一枚"是空断言。
        assert enriched.audio and not enriched.operational_issue, enriched
        assert seen["synth"] == seen["outer"], (
            f"内层产出步没跑在外层那一枚 worker 上：{seen}"
        )
        assert pool.submits == 1, (
            f"一次配音在池里提交 {pool.submits} 次，应为 1 次"
            "（嵌套那枚须内联，不得再要第二枚 worker）"
        )
        assert pool.high_water == 1, f"同时在飞 {pool.high_water} 枚，应为 1"
    finally:
        pool.shutdown(wait=True)


def test_concurrent_dubbings_up_to_pool_width_all_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """吞吐账（防"把并发降成串行"）：**现算池宽**条配音同时在飞、彼此不等。

    判据不取墙钟而是确定性栅栏：每条配音的合成步都要等齐 ``_POOL_WIDTH`` 条才放行。
    一旦被串行化（或每条仍占 >1 枚），栅栏永远等不齐 ⇒ BrokenBarrierError ⇒ 该条挂
    issue、无音频。另钉 ``submits==宽度``（每条恰一枚，而非 2×宽度）与
    ``high_water==宽度``（真并行，不是 1）。
    """
    width = _POOL_WIDTH
    pool = _CountingPool(width)
    try:
        barrier = threading.Barrier(width)
        enricher, seen = _voice_chain(tmp_path, monkeypatch, pool, dub_barrier=barrier)
        results: list = []
        errors: list[BaseException] = []

        def _one() -> None:
            try:
                results.append(enricher(_message(), _decision(), _result()))
            except BaseException as exc:  # noqa: BLE001 - 记账后由主线程揭破，不静默
                errors.append(exc)

        threads = [threading.Thread(target=_one) for _ in range(width)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        assert not errors, errors
        assert len(results) == width, f"{len(results)}/{width} 条配音没跑完"
        assert all(r.audio and not r.operational_issue for r in results), (
            "并发下有人没出音频＝栅栏没等齐 ⇒ 配音被串行化或仍在双占位"
        )
        assert len(seen["synth"]) == width and len(set(seen["synth"])) == width, seen
        assert pool.submits == width, (
            f"{width} 条配音共提交 {pool.submits} 次，应恰 {width} 次（每条一枚 worker）"
        )
        assert pool.high_water == width, (
            f"同时在飞仅 {pool.high_water} 枚（池宽 {width}）⇒ 并发被压低＝趋近串行"
        )
    finally:
        pool.shutdown(wait=True)


def _nested_pair_invoker(
    monkeypatch: pytest.MonkeyPatch, pool: _CountingPool
) -> tuple:
    """造「外层执行体内再 invoke 一次内层」的自定义注册面（与配音链同构、零域外依赖）。"""
    invoker = s10._mini_invoker()
    audit: list = []
    invoker.audit_hooks.register(audit.append)
    seen: dict[str, object] = {}

    def inner(request: cp.CapabilityRequest) -> cp.InvocationResult:
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            data={"inner": 1},
            via="s135-inner",
        )

    def outer(request: cp.CapabilityRequest) -> cp.InvocationResult:
        seen["outer_thread"] = threading.current_thread().name
        nested = invoker.invoke(
            cp.CapabilityRequest(
                capability_id="s135.inner", principal="u1", roles=("user",), payload={}
            )
        )
        gated = invoker.invoke(
            cp.CapabilityRequest(
                capability_id="s135.gated", principal="u1", roles=("user",), payload={}
            )
        )
        seen["nested_status"] = nested.status
        seen["gated_status"] = gated.status
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            data={"outer": 1},
            via="s135-outer",
        )

    s10._register_custom(invoker, "s135.inner", inner, timeout=5.0)
    # 内层要求 super_admin 而嵌套请求只带 user ⇒ 仍须被拒（门不因内联而失效）。
    s10._register_custom(
        invoker, "s135.gated", inner, roles=("super_admin",), timeout=5.0
    )
    s10._register_custom(invoker, "s135.outer", outer, timeout=5.0)
    monkeypatch.setattr(cp, "_get_capability_executor", lambda: pool)
    return invoker, seen, audit


def test_nested_leg_still_enforces_gates_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内联≠绕中央件：嵌套那一枚仍过层 2 的角色门、仍落自己的审计行。

    专防"把内联做成直呼 handler"——那会静默丢掉权限执法与可观测性（本仓反复踩的
    第二通路形态）。
    """
    pool = _CountingPool(_POOL_WIDTH)
    try:
        invoker, seen, audit = _nested_pair_invoker(monkeypatch, pool)
        invoker.invoke(
            cp.CapabilityRequest(
                capability_id="s135.outer", principal="u1", roles=("user",), payload={}
            )
        )

        assert seen["nested_status"] is cp.InvocationStatus.OK, seen
        assert seen["gated_status"] is cp.InvocationStatus.DENIED, (
            "内联那档绕过了角色门 ⇒ 层 2 执法出现第二通路"
        )
        ids = [getattr(r, "capability_id", "") for r in audit]
        assert ids == ["s135.inner", "s135.gated", "s135.outer"], (
            f"审计序不对（内联那枚必须照常落行）：{ids}"
        )
        assert pool.submits == 1, (
            f"整条嵌套链应只提交 1 次池任务，实得 {pool.submits}"
        )
    finally:
        pool.shutdown(wait=True)


def test_worker_marker_releases_on_success_and_on_exception() -> None:
    """标记契约（P4 注毒逼出来的一把）：`_mark_capability_worker` 只是**任务期间**的记账。

    本席首版把这层判据写成「顶层连发两次仍各自进池」——那只管住主线程，**抓不到**
    worker 侧计数不回退（池线程上「此后一律内联」恰与本席想保的方向一致，泄漏于是隐身）。
    所以判据得直接钉契约本体：正常返回与抛异常两条路出来都必须回到未标记态，
    否则同一条 worker 被复用时的行为不再由「此刻是否正在跑能力」决定，而是由
    历史偶然决定（嵌套面被动扩大，且将来任何"按标记分流"的新判据都会跟着失真）。
    """

    def _probe_within() -> cp.InvocationResult:
        return cp.InvocationResult(
            capability_id="s135.probe",
            status=cp.InvocationStatus.OK,
            data={"in_worker": cp._in_capability_worker()},
            via="s135-probe",
        )

    marked = cp._mark_capability_worker(_probe_within)
    assert cp._in_capability_worker() is False, "主线程不该被算作 worker"
    assert marked().data["in_worker"] is True, (
        "任务执行期间必须自认在 worker 内（嵌套那枚才走内联）"
    )
    assert cp._in_capability_worker() is False, "任务返回后标记未回退＝粘滞"

    def _boom() -> cp.InvocationResult:
        raise RuntimeError("s135 poison probe")

    raised = False
    try:
        cp._mark_capability_worker(_boom)()
    except RuntimeError:
        raised = True
    assert raised, "前置自证：异常路径确实走到（否则本锁是空断言）"
    assert cp._in_capability_worker() is False, "异常路径标记未回退＝粘滞（finally 被改动）"


def test_top_level_still_pooled_and_marker_releases_after_each_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """顶层那一头仍走池：不是一刀切全内联（否则中央线程池名存实亡）。

    ⚠ 本锁只管**调用线程**这一侧（连发两次仍各自进池 ⇒ 主线程永不被误判为 worker）；
    它**抓不到** worker 侧计数不回退——那是 P4 注毒当场揭穿的空档（首版把两件事写在同一把
    锁的标题里，读数却只覆盖一半），故粘滞判据另立 `test_worker_marker_releases_on_success_and_on_exception`。
    """
    pool = _CountingPool(_POOL_WIDTH)
    try:
        invoker, _seen, _audit = _nested_pair_invoker(monkeypatch, pool)
        main_thread = threading.current_thread().name
        for expected in (1, 2):
            result = invoker.invoke(
                cp.CapabilityRequest(
                    capability_id="s135.inner",
                    principal="u1",
                    roles=("user",),
                    payload={},
                )
            )
            assert result.status is cp.InvocationStatus.OK
            assert pool.submits == expected, pool.submits
        assert pool.ran_threads and main_thread not in pool.ran_threads, (
            "顶层调用没跑在池线程上 ⇒ 被整体内联，池名存实亡"
        )
        assert cp._in_capability_worker() is False, "调用线程被误判为 worker"
    finally:
        pool.shutdown(wait=True)
