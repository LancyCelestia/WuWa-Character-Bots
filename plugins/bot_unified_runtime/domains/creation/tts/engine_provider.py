"""creation.tts 引擎适配器：把 job 形合成请求落到 media 域**唯一合成口**（S03 施工图 C1）.

域归属：本件住 ``domains/creation/tts/``，是 creation 域自己的引擎适配层；
它**不实现**语音，只做「形态映射 + 委派」，使 ``creation.tts.synthesize`` 具备
被中央注册表（``runtime/capability_protocols.py``）登记为 handler 的执行面。

四条铁律（越界即假绿，本席按此自锁，见 ``tests/test_creation_tts_engine_provider.py``）：

1. **零第二条引擎路**——合成只经单一组合口
   :func:`~...domains.media.tts.result_transform.dub_via_central`（它内部再走中央能力
   ``media.tts.autodub`` → tts 域唯一合成口 ``synthesize_autodub``→``synthesize``）。本文件
   **不直呼** ``synthesize_autodub``（S270 归位：直呼即造第二通路，被 wave 门直呼面钉死）。
   本文件不建 HTTP 客户端、不落盘、不拼请求参数、不碰缓存目录。
2. **零第二把尺子**——文本硬顶只经 ``domains/media/tts_presets.resolve_hard_max_chars``
   现读（0=不限由 config 显式值语义承担，禁配无界时取预设表内置常量）；产物字节顶
   在 ``synthesize`` 真身内把守（``resolve_max_audio_bytes``），本文件**不复制**该判定，
   也不出现 2000 / 8 MiB / 0.85 / 131 任一数值字面量。
3. **零第二份缓存键**——缓存键四维（identity_version/engine/ref/preset+text）与
   ``content_sha256`` 由既有真身产出后**原样透传**；域内不重算哈希、不拼第二个键、
   不自造 seed。同句恒同音色沿用 ``derive_seed``（seed=缓存键派生，M-72/U-25）。
4. **零冒充成功**——非 ``ok`` 产出码一律映射为非成功终态并带诚实说明
   （HONEST_DEGRADE 口径：detail 必过 ``redact_local_secrets``、不含密钥与本机路径）。
   政策拒绝映射 DENIED（≠故障，不挂 issue）；未知产出码按失败记账，绝不折算成成功。

provider 门：不在本域另立探测，唯一判据复用
``domains/creation/reserved_provider.provider_configured``。S69 现算更正旧"未来键不存在 ⇒ 恒
False ⇒ 恒 UNAVAILABLE"的叙述：该判据今天走的是 ``bot_tts_api_url``／``bot_tts_ref_audios``
（CM-P-3 甲案：与 ``bot.tts`` 同一判定源，非另立口径），二者是**真实在产配置**；
``bot_creation_tts_provider`` 也已登记于 ``config.py``（缺省空串，填了=显式指定选择器）。
⇒ 配好参考音/引擎地址时 provider 门**放行**，本件把 job 形请求落到 media 域唯一合成口
（``synthesize_autodub``→``synthesize``），可产出真音频；门未过（无引擎/无参考音）才诚实
``UNAVAILABLE``／``NOT_CONFIGURED``。**不得**反向叙述成"语音恒不可用"，也**不得**在合成口
真返非 ``ok`` 时代成功（铁律 4）。

依赖方向：本件只被中央注册表回调；中央执行信封类型在函数体内延迟 import
（与 ``domains/media/capabilities/image_search.py`` 同惯例），避免域件与 runtime 壳
装配期环依赖。描述符的**构造**仍唯一住中央壳，本模块不出第二份描述符。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅注解用：运行期不在模块期触碰中央层
    from collections.abc import Callable

    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationResult,
        InvocationStatus,
    )

# 「缺位」异常基类住域内单一真身（``reserved_provider``，纯叶子件）：两通道共用同一族，
# 卡片/审计的读者才可能拿到同形载荷。继承必须在 class 语句执行前就位 ⇒ 模块期 import。
from ..reserved_provider import CreationNotWired

__all__ = [
    "CreationTtsNotWired",
    "handle",
    "resolve_job_text",
    "synthesize_via_engine",
]


class CreationTtsNotWired(CreationNotWired):
    """语音对接点未配 provider（"缺位必须可见"用；与绘画 :class:`CreationImageNotWired` 同族）。

    SEAT-S115 补的正是这一枚：**此前**本通道 provider 门只回一句 ``detail`` 文本、信封 ``data``
    全空 ⇒ 绘画那条"把缺位交回层 1"的通道在语音侧**根本不存在**，两通道不对称。
    终态仍是不新增的 ``UNAVAILABLE``，只是多挂一条可归因异常。

    ⚠ 可达性与绘画同账（别读成"卡一定出"）：本能力今天唯一的真调用者是控制面 HTTP
    （``domains/creation/tts/routes.py``，由 ``control_plane/api/v1.py`` 挂载），它把 ``detail`` 原样回给调用方、**不**把异常冒成诊断卡；
    层 1 ``_step`` 的 raise 腿只服务命令/预备形能力。⇒ 现役可见性＝审计 ``detail`` ＋
    巡检告警 ＋ 控制面响应体；``raise`` 腿等的是 caller，补丁文本见 SEAT-S115/S132 §3。
    """


def _tts_module() -> Any:
    """延迟取语音真身模块（唯一合成口与唯一分类口都住在那里）。"""
    from plugins.bot_unified_runtime.domains.media.capabilities import tts

    return tts


def resolve_job_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    """从请求载荷取「已定稿文本」，返回 ``(text, 错误说明)``；错误说明非空即不合成。

    只认两种在册形态：

    - ``payload["job"]``：交 ``TTSJobRequest`` **自己**过契约（``text`` 与
      ``approved_reply_id`` 二选一、SSML 剥拒、枚举名消毒、长度顶——唯一判据在
      契约件 :meth:`...TTSJobRequest._text_xor_reply`，本函数**不抄第二份**）；
    - ``payload["text"]``：调用方已定稿的纯文本（与 ``media.tts.autodub`` 同一载荷形状）。

    只给 ``approved_reply_id`` 时诚实失败：取「已过 Review 稿件正文」的口在装配层
    尚未落地，本席不猜文本、不拿 id 当文本去合成。
    """
    from pydantic import ValidationError

    from plugins.bot_unified_runtime.domains.creation.tts import (
        contracts as tts_contracts,
    )

    raw_job = payload.get("job")
    if raw_job is not None:
        try:
            if isinstance(raw_job, tts_contracts.TTSJobRequest):
                job = raw_job
            else:
                job = tts_contracts.TTSJobRequest.model_validate(raw_job)
        except (TypeError, ValidationError) as exc:
            return "", f"job 形请求未过契约自验：{type(exc).__name__}"
        if job.text is None:
            return "", (
                "job 只给了 approved_reply_id：取过审稿件正文的口未落地，"
                "不猜文本、不合成（诚实失败）"
            )
        return str(job.text), ""

    raw_text = payload.get("text")
    text = str(raw_text).strip() if raw_text is not None else ""
    if not text:
        return "", "缺少 text：job 形只收已定稿文本（或经契约自验的 job）"
    return text, ""


def synthesize_via_engine(
    config: Any,
    text: str,
    *,
    message: Any = None,
    synth: Callable[..., tuple[Any, str]] | None = None,
    audit: dict[str, Any] | None = None,
    principal: str = "creation-tts-job",
    roles: tuple[str, ...] = ("user",),
    request_id: str = "",
    session_key: str = "",
) -> tuple[str, dict[str, Any]]:
    """一段定稿文本 → 一条音频资产：把 job 形请求落到 media 域唯一产出步。

    返回值与 ``tts.synthesize_autodub`` 同一分类族、**不新增第三种结果类型**：
    ``(code, payload)``，``code`` ∈ ``ok`` / ``no_ref`` / ``blocked`` / ``over_cap``
    / ``failed``（未知产出码归 ``failed``）。``payload`` 在成功态即产出步的出站体
    （``audio_file``/``review_text``/``content_sha256``/``preset_id``/``seed``…）
    原样透传。

    ``message``：有会话主体时才走唯一取文口 ``resolve_speech_text``
    （打码前置→清洗→词典→**会话内容门**）。job 形无会话主体时**不**复制会话内容门
    ——``speech_block_reason`` 是会话侧判定，此处的把关归契约层（``TTSJobRequest``
    +出站审核），本函数只做打码与清洗两步（同为既有唯一口，不新建第三份）。

    ``synth``：合成原语注入缝，随 ``dub_via_central`` 经中央 context 交到产出步 seam，
    与旧直呼 ``synthesize_autodub`` 的 seam 同一含义（缺省=真身 ``synthesize``；离线单测注入
    确定性替身，生产零改变）。``principal``/``roles``/``request_id``/``session_key`` 交组合口
    构造中央 ``media.tts.autodub`` 请求（审计关联与层 2 人门据此执法）。
    """
    from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt
    from plugins.bot_unified_runtime.domains.media.tts_presets import (
        resolve_hard_max_chars,
    )
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )

    tts = _tts_module()

    if message is not None:
        speech, refusal = tts.resolve_speech_text(config, message, text, audit=audit)
    else:
        # 顺序与 resolve_speech_text 一致：先打码后清洗（反过来会把 `BOT_X=` 洗成
        # 不可识别形态，密钥随音频出门——M-03 的根因，此处不重犯）。
        # 不传 ``max_chars``＝用真身缺省，而缺省正是既有「0=不限」语义：本件因此
        # 零数值字面量，长度顶只有 ``resolve_hard_max_chars`` 这一把尺。
        speech = tts.clean_for_speech(redact_local_secrets(str(text or "")))
        refusal = ""
    if refusal:
        # 政策拒绝≠引擎故障：不挂 issue、不计退避，只给诚实原因。
        return "blocked", {"reason": str(refusal)}
    if not speech:
        return "failed", {"reason": "清洗后无可朗读正文：不合成、不空发"}

    hard_max = resolve_hard_max_chars(config)
    if len(speech) > hard_max:
        return "over_cap", {
            "reason": f"文本 {len(speech)} 字超生效硬顶 {hard_max} 字：整条拒发、不拆条（U-29=A）",
            "hard_max_chars": hard_max,
        }

    # 产出步改调单一组合口（S270 归位）：全树唯一一处 media.tts.autodub 字面 invoke 住在
    # result_transform.dub_via_central——本适配层不再直呼 tts.synthesize_autodub（直呼即第二
    # 通路，被 wave 门直呼面钉死）。三态码（dubbed/no_ref/failed）经 dub_outcome 投影回本件的
    # (code, payload) 分类族；blocked/over_cap 仍由本函数前置判定（政策/硬顶不达产出步）。
    outcome = rt.dub_via_central(
        config,
        speech,
        synth=synth,
        principal=principal,
        roles=roles,
        request_id=request_id,
        session_key=session_key,
    )
    if outcome.code == rt.OUTCOME_DUBBED:
        data = dict(outcome.data)
        if not data.get("audio_file"):
            return "failed", {
                "reason": "产出步返回 ok 却无 audio_file：按失败记账，不冒充成功",
                "kind": str(tts._failure_kind_tag("ok 但无产物")),
            }
        return "ok", data
    if outcome.code == rt.OUTCOME_NO_REF:
        # 确定性失败（无可用参考音频），对应 tts_no_ref_audio 码族；两档 config-aware 文案经
        # 中央 handler 透传进 detail（S267 现算的语义代价①已修），本件不再判一遍。
        return "no_ref", {"reason": outcome.detail or str(tts._no_ref_audio_hint(config))}

    # 失败族（含未知产出码被中央折叠成"无产物 ok"后由上面 audio_file 分支接住的残余形态）。
    reason = outcome.detail or "failed"
    kind = str(tts._failure_kind_tag(reason))
    return "failed", {
        "reason": redact_local_secrets(reason)[: int(tts._ISSUE_SUMMARY_MAX_CHARS)],
        "kind": kind,
        "retryable": bool(tts._failure_retryable(reason)),
    }


def _envelope(
    request: CapabilityRequest,
    status: InvocationStatus,
    *,
    data: dict[str, Any] | None = None,
    detail: str = "",
    via: str,
) -> InvocationResult:
    """构造执行信封（延迟 import 中央类型；非成功态必带诚实说明＝信封构造期不变量）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        InvocationResult,
        InvocationStatus,
    )

    text = str(detail or "").strip()
    if status is not InvocationStatus.OK and not text:
        # 走到这里说明上游漏给原因——宁可说一句"没做成、原因没给"，绝不静默假成功。
        text = "非成功终态但未给出原因（不应发生：诚实说明缺失）"
    return InvocationResult(
        capability_id=request.capability_id,
        status=status,
        data=dict(data or {}),
        detail=text,
        via=via,
    )


def handle(request: CapabilityRequest) -> InvocationResult:
    """中央注册表回调口（签名对齐 ``HandlerFn``/``_handle_media_tts_autodub`` 信封）。

    终态三态以上、逐条诚实（禁「未执法却称已执法」）：

    - 契约不过 / 缺文本 → ``FAILED``；
    - **TTS 总开关 ``bot_tts_enabled`` 关 → ``NOT_CONFIGURED``**（首道查、不打引擎；
      与命令路 ``domains/media/capabilities/tts.py:1078`` 同一读法 ``getattr(config, …, False)``
      ⇒ 缺键＝关＝fail-closed，绝不"读不到就照发"）；
    - provider 未配（在册键全空）→ ``UNAVAILABLE``＋``INVOKER_ERROR_DATA_KEY``：
      原因点名**待配键的键名**（不静默、绝不带值——密钥可能就在这些键里）；
    - 无可用参考音频 → ``NOT_CONFIGURED``（确定性失败，同 autodub 腿口径）；
    - 政策拒绝 → ``DENIED``；超生效硬顶 → ``LIMIT_EXCEEDED``（不打引擎）；
    - 引擎失败/未知产出码 → ``FAILED``（detail=``kind：原因``，已过打码）；
    - 只有产出步真返 ``ok`` 且带 ``audio_file`` 才 ``OK``，``data`` 即产出体透传。

    阻塞式合成由 invoker 卸载到 cap-proto 线程池并施加 descriptor 超时安全网
    （与 ``media.tts.autodub`` 同型），本函数自身不建线程、不设第二个超时。
    """
    from plugins.bot_unified_runtime.domains.creation import reserved_provider
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
        InvocationStatus,
    )

    config = request.context.get("config")
    capability_id = request.capability_id

    text, contract_error = resolve_job_text(request.payload or {})
    if contract_error:
        return _envelope(
            request, InvocationStatus.FAILED, detail=contract_error, via="creation_tts_contract"
        )

    if not bool(getattr(config, "bot_tts_enabled", False)):
        # 总开关关＝**首道**拒绝，绝不打引擎。读法与命令路 `tts.py:1078` 逐字同构
        # （``getattr(…, False)`` ⇒ 缺键即关，fail-closed），两路共用一条语义、不各判一遍。
        return _envelope(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail="TTS 总开关 bot_tts_enabled=False ⇒ 本能力诚实不可用（未打引擎）",
            via="creation_tts_killswitch",
        )

    if not reserved_provider.provider_configured(config, capability_id):
        # 可归因串的唯一构造口在 reserved_provider（与绘画通道同一把尺子，禁各拼一份）：
        # 原因 + **待配键名**（键名出自 PROVIDER_PRESENCE_KEYS，值一律不入文案＝铁律 3）。
        detail = reserved_provider.not_wired_detail(config, capability_id)
        return _envelope(
            request,
            InvocationStatus.UNAVAILABLE,
            detail=detail,
            via="creation_tts_provider_gate",
            # SEAT-S115：把缺位异常交回同一条已落地通道（此前本分支 data 全空，
            # "未接 provider 必带可归因 issue"在语音侧不成立）。可达性见 CreationTtsNotWired。
            data={INVOKER_ERROR_DATA_KEY: CreationTtsNotWired(detail)},
        )

    code, payload = synthesize_via_engine(
        config,
        text,
        message=(request.payload or {}).get("message"),
        synth=request.context.get("synthesize"),
        principal=request.principal,
        roles=request.roles,
        request_id=request.request_id,
        session_key=request.session_key,
    )
    reason = str(payload.get("reason", ""))
    if code == "ok":
        return _envelope(request, InvocationStatus.OK, data=payload, via="creation_tts_engine")
    if code == "blocked":
        return _envelope(
            request, InvocationStatus.DENIED, detail=reason or "内容门拒绝", via="creation_tts_engine"
        )
    if code == "over_cap":
        return _envelope(
            request,
            InvocationStatus.LIMIT_EXCEEDED,
            detail=reason or "超生效硬顶",
            via="creation_tts_engine",
        )
    if code == "no_ref":
        return _envelope(
            request,
            InvocationStatus.NOT_CONFIGURED,
            detail=reason or "无可用参考音频",
            via="creation_tts_engine",
        )
    kind = str(payload.get("kind", "")).strip()
    detail = f"{kind}：{reason}" if kind and reason else (reason or kind or "合成失败")
    return _envelope(request, InvocationStatus.FAILED, detail=detail, via="creation_tts_engine")
