"""配音出站「结果变换形」执行体（前序呈现契约 → 带音频的呈现契约）。

席位 S36 · 中央调度收编波（2026-09-24）。目标第 3 项挂账（自动配音第二条腿）的
**形态半边**：中央 Wave 4 的执行面只有 ``command`` 与 ``prepared`` 两形
（``runtime/capability_protocols.py::_KNOWN_ADAPTERS``），两形的执行体都是
``(message, decision) -> CapabilityResult``，**没有「前序结果」通道**
（``_make_prepared_handler`` 也只跑两参）。自动配音是 review 批准后、render 前的
一次「拿已装配的呈现结果 → 变换出音频附件」，两形都装不下 ⇒ 缺第三形。
口径来源：``docs/boards/_meta/code-quality-findings-20260921.md`` P1-18 与
``.superpowers/sdd/2026-09-21-unify-wave/decisions/VOICE-AUTO-DUB-CENTRAL-LEG-PLAN-20260922.md``
§1 候选 A′（信封贯穿形）。

**通电状态（2026-09-24 S91 收编后现算、S253B 复核；S261 只跟随措辞，零行为改动）**：
本件**已进中央注册册**——``runtime/capability_protocols.py`` 里那枚
``CapabilityDescriptor(capability_id="media.tts.autodub_transform")`` 加
``handlers.register`` 的薄委派（handler 体内惰性 import 后 ``return handle(request)``，
中央不建第二路）。根装配点在根 ``__init__.py``：按 ``bot_tts_voice_hook_enabled``
决定装不装 ``domains/media/voice_enricher.py`` 那条 hook，hook 过门链后才派本件。
生产侧**唯一消费点**＝该 hook 里那一处字面 ``invoke``，"恰一处"由
``tests/test_voice_enricher_central_dispatch.py::test_auto_voice_leg_dispatches_central_transform_exactly_once``
钉住；**活性**（不是"函数存在"）由同件
``::test_central_transform_dispatch_reaches_registered_handle`` 真跑到本件 ``handle``
一次、并把带音频的呈现结果读回为证。

**但「已通电」≠「已生效」**：现网 ``bot_tts_voice_hook_enabled`` 缺省 False 且生产
``.env`` 里根本没有这一行、``bot_tts_auto_reply_enabled=false`` ⇒ 今天这条腿**关态不可达**、
零中央调用、生产行为逐字节不变；两枚键任一翻真还须**重启**（装配期读死，不可热改）。
本席（S36）落件当时写的「未接根装配、未进中央注册册」＝**过期口径**，两侧待落补丁文本
见报告 ``SEAT-S36.md`` §7（S91 已按该文本落码，故此处不再是待办）。
``TRANSFORM_SHAPE`` 只是**形态名**，不是 ``_KNOWN_ADAPTERS`` 的成员——本形与
``pipeline_managed`` 同判据：不进路由行、不进适配器谱系，因此不计入
「未通电缺口」（该账现算见 ``tests/test_descriptor_wiredness_ledger.py``）。

**与 ``media.tts.autodub`` 的分工 + 单一组合口（S270 归位）**（产出步 ≠ 变换形）：那枚在册能力是
「一句话→一段音频」的**内容契约产出步**（VOICE-V12 已通电）；本件是它上游的**呈现变换**。
自 S270 起，本件另立**产出步单一组合口** :func:`dub_via_central`——它是全树**唯一**一处对
``media.tts.autodub`` 的字面中央 ``invoke``（``AUTODUB_SOURCE_STEP`` 的家）。两个消费方
（``voice_enricher`` 的 ``dub`` 闭包 / ``creation.tts`` 的 ``synthesize_via_engine``）都改为调本组合口，
不再各自持一份字面 invoke 或直呼 ``synthesize_autodub`` ⇒ 「同一能力全树只准一处 invoker 调用点」
（D-b）结构性成立，直呼面清零。**旧注释"本件不构造中央请求"自本批作废**——改措辞与改行为同批。
这样归位的两条理由，都是本仓踩过的坑：

1. 直呼面零新增：``tests/test_orchestration_callsite_wave_media.py`` 的活性 ledger
   （``KNOWN_INVOKER_SITES_MEDIA``）把唯一 invoker 点归到本件，直呼面 ``set()``；
2. 能力 id 的字面量留在**执行体调用点（即本组合口）**：把 id 参数化传进 ``invoke`` ＝给 AST
   普查门造盲区（``_invoker_cids`` 只认字面常量），那才是真的"第二通路"。故 ``dub_via_central``
   内 ``capability_id="media.tts.autodub"`` 必须是**字面常量**，不得写成变量名 ``AUTODUB_SOURCE_STEP``。

**五条纪律（逐条有锁，见 ``tests/test_tts_result_transform.py``）**

① **生效顶一律现读中央件、本件零数值字面量**：文字硬顶走
   ``tts_presets.resolve_hard_max_chars``；单产物字节顶与落盘配额的家在
   ``synthesize``/``media.tts.autodub`` 产出步，本件**不重读、不传值**（抄第二份＝
   分叉点）。自动配音的两个长度键只按名字读，**键缺席就诚实放弃增益**——
   绝不在此抄一个「看起来一样」的缺省数（M-43 同因）。
② **取文只经唯一取文口** ``tts.resolve_speech_text``（打码→清洗→词典→内容门全在
   它内部，fail-closed）；本件不碰 ``clean_for_speech``/``redact_local_secrets``。
③ **缓存键 / ``content_sha256`` / seed 原样透传**：本件不改文本（取文交出的
   就是交给产出步的那段）、不派 seed、不摘要；出站体与标签全部经唯一消费口
   ``tts.autodub_presentation_update`` 挂回 ⇒「同句恒同音色」在结构上不可能被本件破坏。
④ **失败不静默**：产出步故障（含无参考音）⇒ 挂既有 ``OperationalIssue``
   （kind 走 ``tts`` 域 ``_FAILURE_KINDS`` 前缀表，禁新造），文字照发；
   政策拒绝/清洗后为空/过硬顶 ≠ 故障 ⇒ 只留机读标签（M-14 口径），不挂 issue。
⑤ **hook 关态逐字节同形**：``bot_tts_voice_hook_enabled`` 为假 ⇒ 原样交回**同一个
   对象**（连 ``model_copy`` 都不做）、零产出步调用、零标签。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    CapabilityResult,
    IncomingMessage,
)
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    _failure_issue,
    _no_ref_audio_issue,
    _skip_voice_with_tags,
    autodub_presentation_update,
    lossy_transform_tags,
    resolve_speech_text,
    should_voice_reply,
    split_speech_chunks,
)
from plugins.bot_unified_runtime.domains.media.tts_presets import (
    resolve_hard_max_chars,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    INVOKER_ERROR_DATA_KEY,
    PRESENTATION_DATA_KEY,
    CapabilityRequest,
    InvocationResult,
    InvocationStatus,
    default_invoker,
)

logger = logging.getLogger(__name__)

#: 本件所属的**执行形态名**（散文字典用词，不是 ``_KNOWN_ADAPTERS`` 成员，
#: 也不进路由行——见模块 docstring「通电状态」）。
TRANSFORM_SHAPE = "result_transform"

#: 本件的在册能力 id（S91 已注册：descriptor + ``handlers.register`` 在
#: ``runtime/capability_protocols.py``，名册认领在 ``domains/core/capability_manifest.py``）。
#: 符号名仍叫 ``PROPOSED_CAPABILITY_ID`` 且仍在 ``__all__`` 里＝**既有导出面**，
#: 改名会动 API 与测试引用（S261 只改这段注释措辞，零行为改动）。
PROPOSED_CAPABILITY_ID = "media.tts.autodub_transform"

#: 产出步单一真身的在册 id（作 provenance 写在文案里；``dub_via_central`` 的 ``invoke``
#: 用的是同值的**字面常量**，不是本符号——见模块 docstring「单一组合口」理由 2）。
AUTODUB_SOURCE_STEP = "media.tts.autodub"

# 结果码（变换这一步"发生了什么"的机读词汇，进信封 detail 与审计，
# 不进呈现契约的 audit_tags——留痕词族沿用 tts 既有那套，禁第二本账）。
OUTCOME_DUBBED = "dubbed"
OUTCOME_HOOK_DISABLED = "hook_disabled"
OUTCOME_GATE_REFUSED = "gate_refused"
OUTCOME_POLICY_BLOCKED = "blocked_by_policy"
OUTCOME_EMPTY_AFTER_CLEAN = "empty_after_clean"
OUTCOME_OVER_HARD_CAP = "over_hard_cap"
OUTCOME_SIZING_MISSING = "auto_reply_sizing_missing"
OUTCOME_NO_REF = "no_ref"
OUTCOME_FAILED = "failed"

#: 自动配音的两个长度键（**只按名字读**，值与缺省都不落在本件里）。
_AUTO_REPLY_MAX_CHARS_KEY = "bot_tts_auto_reply_max_chars"
_AUTO_REPLY_SPLIT_MAX_CHARS_KEY = "bot_tts_auto_reply_split_max_chars"

#: ``media.tts.autodub`` 三态码（与 ``tts.synthesize_autodub`` 的返回码族、
#: 中央 handler 的状态映射同源同词，本件不新增第四态）。
_NO_REF_STATUSES = (InvocationStatus.NOT_CONFIGURED,)
_SUCCESS_STATUSES = (InvocationStatus.OK, InvocationStatus.FALLBACK_OK)


@dataclass(frozen=True)
class DubOutcome:
    """产出步的一次结果（``code`` 用 ``OUTCOME_*`` 三态词，``data`` 原样交回）。

    ``data`` 就是中央载荷的**原样引用**（``audio_parts``/``audit_tags_delta``/
    ``preset_id``/``seed``/``content_sha256``）——本件不解析、不改写、不补字段。
    """

    code: str
    data: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


#: 产出步注入缝：「一段干净文本 → 一次配音结果」。生产由装配现场用中央 invoke 包；
#: 离线单测注入确定性替身（与生产同一 seam 语义，不新增第二引擎路）。
DubStep = Callable[[str], DubOutcome]


def dub_outcome_from_invocation(invocation: Any) -> DubOutcome:
    """把一次 ``media.tts.autodub`` 的中央终态投影成 :class:`DubOutcome`。

    三态映射与 ``domains/media/voice_enricher.py`` 现行口径逐字一致（禁新造第四态）：
    成功族 → ``dubbed``；``NOT_CONFIGURED`` → ``no_ref``；**其余一切非成功终态**
    （FAILED/DEGRADED/TIMEOUT/LIMIT_EXCEEDED/DENIED/UNAVAILABLE…）→ ``failed``。
    载荷只从 ``data`` 原样取，本函数不读 config、不碰数值。
    """
    status = getattr(invocation, "status", None)
    raw_data = getattr(invocation, "data", None)
    data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
    detail = str(getattr(invocation, "detail", "") or "")
    if status in _SUCCESS_STATUSES:
        return DubOutcome(OUTCOME_DUBBED, data, detail)
    if status in _NO_REF_STATUSES:
        return DubOutcome(OUTCOME_NO_REF, {}, detail)
    return DubOutcome(OUTCOME_FAILED, {}, detail)


def envelope_failure_reason(invocation: InvocationResult) -> str:
    """非成功信封 → 证据串：中央 detail 原文 + 载荷异常身份（单一真身，S270 自 hook 上收）。

    invoker 已把主链原始异常（含 ``CapabilityTimeout``）经 ``INVOKER_ERROR_DATA_KEY`` 放进
    非成功终态的 ``data``；旧 hook 直呼 autodub 时由本段读它、把 ``类型名: 消息`` **追加**进
    证据串——"挂死满预算"的第二信号不丢。kind/retryable 仍唯一由 ``tts._FAILURE_KINDS`` 前缀表
    裁决（追加在 detail 头部之后、不改写 ⇒ 分类语义逐字不变）。载荷缺席/键形不对 ⇒ 诚实退化
    detail（fail-open）。``voice_enricher._envelope_failure_reason`` 与产出步 seam 共用这一真身。
    """
    reason = str(invocation.detail or "")
    primary_error = invocation.data.get(INVOKER_ERROR_DATA_KEY)
    if isinstance(primary_error, BaseException):
        identity = f"{type(primary_error).__name__}: {primary_error}"
        if identity not in reason:
            reason = f"{reason}｜invoker载荷 {identity}" if reason else f"invoker载荷 {identity}"
    return reason


def dub_via_central(
    config: Any,
    text: str,
    *,
    synth: Any = None,
    principal: str = "anonymous",
    roles: tuple[str, ...] = ("user",),
    request_id: str = "",
    session_key: str = "",
) -> DubOutcome:
    """产出步单一组合口：一段干净文本 → 一次 ``media.tts.autodub`` 中央终态投影成 :class:`DubOutcome`。

    **全树唯一一处对 ``media.tts.autodub`` 的字面中央 invoke**（直呼面因此清零、invoker 面恰一处，
    见模块 docstring「单一组合口」）。``voice_enricher.dub`` 与 ``creation.tts.synthesize_via_engine``
    都经本口，不再各持一份 invoke 或直呼 ``synthesize_autodub``——消灭 S267 实跑证的「改道即造第二通路」。

    - ``synth`` 合成原语经 ``context`` 交产出步 seam（生产＝``tts.synthesize`` 本体，逐字节等价；
      离线单测注入确定性替身），本口不重造引擎路；
    - 非成功终态把 ``envelope_failure_reason``（含 invoker 载荷异常身份）并进 ``detail``，
      与退役前 hook seam 口径逐字一致；成功态原样透传 ``data``。
    - 阻塞式合成由 invoker 卸载到 cap-proto 线程池并施加 descriptor 超时安全网（90s），本口不自建
      线程、不设第二个超时。
    """
    invocation = default_invoker().invoke(
        CapabilityRequest(
            # 字面常量（非 AUTODUB_SOURCE_STEP 变量）：AST 普查门只认字面量，见模块 docstring。
            capability_id="media.tts.autodub",
            payload={"text": text},
            principal=principal,
            # 门链已保证这是会话侧真人（should_voice_reply 只放 bot.chat 真人回复），主体恒含
            # user；层 2 人门据此执法（blocked 主体=1 增量，fail-closed 方向正确）。
            roles=roles,
            request_id=request_id,
            session_key=session_key,
            context={"config": config, "synthesize": synth},
        )
    )
    outcome = dub_outcome_from_invocation(invocation)
    if outcome.code != OUTCOME_DUBBED:
        return DubOutcome(outcome.code, outcome.data, envelope_failure_reason(invocation))
    return outcome


def transform_presentation(
    config: Any,
    message: IncomingMessage,
    result: CapabilityResult,
    *,
    dub: DubStep,
) -> tuple[CapabilityResult, str]:
    """结果变换形的执行体：前序呈现结果 → （尽量）带音频的呈现结果。

    门链序（与 T54 §4.2 冻结序同构，只增不减地继承上游）：
    hook 总键 ∧ 无既有 issue ∧ ``should_voice_reply`` ∧ 取文（含内容门）∧ 文字硬顶 ∧
    产出步。返回 ``(呈现结果, 结果码)``——**结果码只进审计**，呈现侧留痕沿用
    tts 域既有标签词族（``auto_reply_skipped`` / ``over_hard_cap`` / ``blocked_by_policy``
    / 产出步交回的 ``tts``/``auto_reply``/``preset=``/``seed=``/``audio_sha256=``
    与 M-14 有损标签）。

    任何"不配"都不动正文；任何产出步故障都挂 ``OperationalIssue``（④失败不静默），
    半程故障（拆条已出若干块后失败）不挂 issue、只记 ``split=a/b`` 缺角——
    与 ``voice_enricher`` 在册语义逐字保留。
    """
    # 门链第 0 道：hook 总键。关 ⇒ 交回**同一个对象**，零改动（纪律⑤）。
    if not bool(getattr(config, "bot_tts_voice_hook_enabled", False)):
        return result, OUTCOME_HOOK_DISABLED
    # 门链第 1 道：issue 挂载权属先到者，不覆盖能力层已挂的故障证据。
    if result.operational_issue is not None:
        return result, OUTCOME_GATE_REFUSED
    # 门链第 2 道：完整谓词（总闸∧自动闸∧audio 空∧bot.chat∧scope∧名单∧概率门）。
    if not should_voice_reply(config, message, result):
        return result, OUTCOME_GATE_REFUSED

    raw_max_chars = getattr(config, _AUTO_REPLY_MAX_CHARS_KEY, None)
    if raw_max_chars is None:
        # 键缺席＝装配不完整。本件不猜"不限"、不抄第二份缺省数（纪律①）：
        # 诚实放弃增益并点名（配音是增益，这条路的任何不确定都不该动正文）。
        logger.warning(
            "tts result transform skipped: config key %s absent",
            _AUTO_REPLY_MAX_CHARS_KEY,
        )
        return result, OUTCOME_SIZING_MISSING
    try:
        lossy_audit: dict[str, Any] = {}
        # 取文唯一口（纪律②）：入参=本时点 body（review 批准后的正文）。
        speech, blocked = resolve_speech_text(
            config,
            message,
            result.body or result.summary or "",
            max_chars=int(raw_max_chars),
            audit=lossy_audit,
        )
        if blocked:
            logger.info("tts auto reply blocked by policy: category=%s", blocked)
            return (
                _skip_voice_with_tags(result, OUTCOME_POLICY_BLOCKED),
                OUTCOME_POLICY_BLOCKED,
            )
        if not speech:
            return (
                _skip_voice_with_tags(
                    result, OUTCOME_EMPTY_AFTER_CLEAN, *lossy_transform_tags(lossy_audit)
                ),
                OUTCOME_EMPTY_AFTER_CLEAN,
            )
        # 文字硬顶现读中央件（纪律①）：超顶=放弃增益、正文照发，不挂 issue（防刷屏）。
        hard_cap = resolve_hard_max_chars(config)
        if len(speech) > hard_cap:
            logger.info(
                "tts auto reply skipped: over_hard_cap len=%d cap=%d",
                len(speech),
                hard_cap,
            )
            return (
                _skip_voice_with_tags(
                    result,
                    OUTCOME_OVER_HARD_CAP,
                    f"len={len(speech)}",
                    f"cap={hard_cap}",
                    *lossy_transform_tags(lossy_audit),
                ),
                OUTCOME_OVER_HARD_CAP,
            )
        # 拆条真身仍在 tts 域；本件只按名字读那枚键，键缺席⇒不拆（不抄第二份缺省数）。
        chunks = _speech_chunks(config, speech)
        ok_data: list[dict[str, Any]] = []
        failed_code = ""
        failed_detail = ""
        for chunk in chunks:
            outcome = dub(chunk)
            if outcome.code == OUTCOME_DUBBED:
                ok_data.append(dict(outcome.data))
                continue
            failed_code, failed_detail = outcome.code, outcome.detail
            break
        if not ok_data:
            # 首块即败=整幅失败面：交回**挂了 issue 的原正文**（不静默、不假称配音成功）。
            issue = (
                _no_ref_audio_issue(message, config)
                if failed_code == OUTCOME_NO_REF
                else _failure_issue(message, failed_detail or failed_code)
            )
            return result.model_copy(update={"operational_issue": issue}), (
                failed_code or OUTCOME_FAILED
            )
        if failed_code:
            # 半程故障：已合成块照发、剩余块放弃；配音是增益，不挂 issue（与
            # 「政策拒绝≠故障」同口径），缺角如实记 split=a/b。
            logger.info(
                "tts auto dubbing interrupted at chunk %d/%d: code=%s",
                len(ok_data),
                len(chunks),
                failed_code,
            )
        audio_parts: list[Any] = [
            part for data in ok_data for part in (data.get("audio_parts") or [])
        ]
        audit_tags_delta: list[str] = [
            tag for data in ok_data for tag in (data.get("audit_tags_delta") or [])
        ]
        if len(chunks) > len(ok_data):
            audit_tags_delta.append(f"split={len(ok_data)}/{len(chunks)}")
        # M-14 有损留痕在此补齐（PLAN-VOICE2 §0.8 那笔未偿协调债）：hook 形此前
        # 既不记 content_sha256（真身已记，见出站体透传）也不记 lossy 标签。
        audit_tags_delta.extend(lossy_transform_tags(lossy_audit))
        merged: dict[str, Any] = {
            "audio_parts": audio_parts,
            "audit_tags_delta": audit_tags_delta,
        }
        # 唯一消费口挂回呈现契约（纪律③）：本件不自拼出站体、不造字段。
        return result.model_copy(update=autodub_presentation_update(result, merged)), OUTCOME_DUBBED
    except Exception as exc:  # 本域 logger 不在生产日志树上，`exc_info` 落一条是一条。
        logger.warning("tts voice transform failed: %s", exc, exc_info=True)
        return (
            result.model_copy(
                update={
                    "operational_issue": _failure_issue(message, f"voice transform failed: {exc}")
                }
            ),
            OUTCOME_FAILED,
        )


def handle(request: Any) -> InvocationResult:
    """中央注册用的信封体（**本席未注册**；注册补丁文本见报告 §7）。

    在册契约（与 ``command``/``prepared`` 两形并列的第三形）：

    - 载荷侧**用户数据走 payload**：``{"message": IncomingMessage, "result": 呈现契约
      ``model_dump()``（dict）}``；**运行期依赖走 context**：``{"config":…, "dub":…}``
      （口径与 ``_make_command_handler`` 的裁决一致）。
    - 交付：``OK`` + ``data[PRESENTATION_DATA_KEY]=变换后呈现 dump``，``detail`` 带结果码。
      产出步故障时呈现载荷**仍在**（正文照发 + issue 已挂）——这是变换形与命令形的
      根本差别：变换的合法产物就是"这次没加成"，把它伪造成非成功终态会逼信封丢载荷、
      进而逼调用方自己再造一份 issue 真身（第二真身，禁）。
    - 拿不到执行体/载荷形状不合 ⇒ ``UNAVAILABLE``/``FAILED`` + 诚实 detail、
      **绝不带呈现载荷**（``_check_envelope_invariants`` 结构上拦死假成功）。
    """
    payload = request.payload if isinstance(request.payload, Mapping) else {}
    context = request.context if isinstance(request.context, Mapping) else {}
    message = payload.get("message")
    presented = payload.get("result")
    dub = context.get("dub")
    if not isinstance(message, IncomingMessage) or not isinstance(presented, dict):
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.FAILED,
            detail="payload 需带 message 与 result（呈现契约 model_dump 的 dict）",
            via=TRANSFORM_SHAPE,
        )
    if not callable(dub):
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.UNAVAILABLE,
            detail=(
                "结果变换形未交产出步（dub）——在册真身是 "
                f"{AUTODUB_SOURCE_STEP} 的中央调用，须由装配现场注入；"
                "不猜、不重建、不回退直呼"
            ),
            via=TRANSFORM_SHAPE,
        )
    try:
        prior = CapabilityResult.model_validate(presented)
    except Exception as exc:  # noqa: BLE001 - 形状不合=诚实失败，不带载荷
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.FAILED,
            detail=f"呈现载荷不可装载：{exc}",
            via=TRANSFORM_SHAPE,
        )
    config = context.get("config")
    enriched, outcome_code = transform_presentation(config, message, prior, dub=dub)
    return InvocationResult(
        capability_id=request.capability_id,
        status=InvocationStatus.OK,
        data={PRESENTATION_DATA_KEY: enriched.model_dump()},
        detail=f"{TRANSFORM_SHAPE}:{outcome_code}",
        via=TRANSFORM_SHAPE,
    )


def _speech_chunks(config: Any, speech: str) -> list[str]:
    """按名字读拆条键并交真身；键缺席⇒整段不拆（本件不写任何数值）。"""
    raw_split = getattr(config, _AUTO_REPLY_SPLIT_MAX_CHARS_KEY, None)
    if raw_split is None:
        return [speech]
    return split_speech_chunks(speech, int(raw_split)) or [speech]


__all__ = [
    "AUTODUB_SOURCE_STEP",
    "PROPOSED_CAPABILITY_ID",
    "TRANSFORM_SHAPE",
    "DubOutcome",
    "DubStep",
    "dub_outcome_from_invocation",
    "dub_via_central",
    "envelope_failure_reason",
    "handle",
    "transform_presentation",
]
