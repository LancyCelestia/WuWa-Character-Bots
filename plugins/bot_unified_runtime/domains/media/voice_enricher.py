"""配音出站 post-review hook（G-3 · M-10 根修 + M-13 自动半；VOICE-V12 收编产出步；
S91 收编整段变换为中央第三形 media.tts.autodub_transform）。

职责（T54 规格 §4.2 冻结接口，落点=本模块而非 tts.py——tts.py 现由 T75 席
独占，G-2（T61）亦未在该文件施工本 hook，见 report-T61 §八；本模块与 tts.py
同属 media 域，只消费其模块级构件）：

- **键开**（``bot_tts_voice_hook_enabled=True``）时由根装配（根 ``__init__.py``
  双态分支）惰性导入构建，经 ``RuntimePipeline.outbound_voice_enricher`` 在
  **review 批准后、render 前**调用——取文口径从「review 前的旧 body」翻正为
  「review 批准后的 body」（M-10 三害根修：被审核拦的正文不再先落盘成音频档案）；
- **整段变换走中央第三形**（S91 · mandate「所有内容走中央调度层，TTS 也不例外」）：
  本 hook 不再自己内联「取文→硬顶→逐块合成→合并→挂回」，而是把前序呈现结果
  ``default_invoker().invoke(CapabilityRequest(capability_id="media.tts.autodub_transform", …))``
  交中央第三形（执行体真身 ``domains/media/tts/result_transform.py``）——层 2（权限/健康/
  180s 超时/降级/中央审计）对「呈现结果→带音频呈现结果」这一步整体执法。产出步
  （一句话→一段音频）仍是 ``media.tts.autodub``，但**由本 hook 的 ``dub`` 闭包改调单一组合口**
  ``result_transform.dub_via_central``（S270 归位：全树唯一一处 autodub 字面 invoke 住在该组合口，
  本 hook 不再自持那份 invoke ⇒ 直呼面清零、"同一能力全树只准一处"结构性成立）。本 hook 只保留三道**廉价前置门**
  （hook 键 / 既有 issue / ``should_voice_reply``）短路"该不该配"的多数否决：门链判否的
  消息**不派中央、零合成**（``should_voice_reply`` 是纯谓词、真身再判一次幂等 ⇒ 无分歧）。
  ⇒ 与退役前差异：门链通过后的"取文/政策/超顶"如今也过一发中央第三形 invoke（多一条
  中央审计行，policy 判定本身转为可审计），门链判否仍是零中央调用；
- **失败可见**（M-13 自动半）：中央返回非成功终态 ⇒ hook 按 status 映射既有
  ``OperationalIssue``（kind 复用 c723904 ``_FAILURE_KINDS`` 码族，禁新造），随 SendRequest
  进中央告警链（300s 抑制）；S64 起 ``INVOKER_ERROR_DATA_KEY`` 消费点前移到 ``dub`` seam
  （``_envelope_failure_reason`` 把主链挂死载荷 ``CapabilityTimeout`` 的异常身份追加进证据串
  ⇒ 产出步故障第二信号仍可归因，经真身透传进 issue）；诊断卡在此腿结构性不可达
  （raise=丢整条过审正文=拖垮回复），钉为 GAP-HOOK-STRUCTURAL-NO-CARD，裁定请求见
  ``tests/test_voice_hook_error_card_leg.py``；**政策拒绝/清洗后为空/超硬顶≠故障**（T54 §4.1#2，
  真身只留 audit_tag、不挂 issue）；
- **群内正文照发**（R-16② 裁定）：hook 挂 issue 发生在 pipeline A-19 分支
  （review 前）之后，不触发「压空正文」——群内降级文案维持交中央 A-19，
  本域不自拼（S8 裁定不回退）。

与旧包装（根 ``_attach_voice_reply``→``maybe_attach_voice``）的关系：**双态
互斥**——键关部署走旧包装（逐字节现状），键开走本 hook。产出步真身已收成
``tts.synthesize_autodub`` 单一真身，本 hook 的 ``dub`` 闭包、中央 handler、旧包装三处
消费边共用它（旧包装退役=V3，另批）。合成产物随件带 ``content_sha256``（M-64/S2）。

**出站体归属（VOICE-CENTRAL-UNBLOCK 2026-09-22 + S91 收编）**：``audio`` 部件与
``tts/auto_reply/preset=/seed=/audio_sha256=`` 标签由中央产出步 ``synthesize_autodub``
一处拼装，经真身 ``result_transform`` 的唯一消费口 ``tts.autodub_presentation_update``
挂回呈现契约；本 hook 现只经中央第三形取回呈现结果（读 ``data[PRESENTATION_DATA_KEY]``
→ ``CapabilityResult.model_validate``），**层 1 不再自拼出站体、不再直呼 ``synthesize``、
不再出现 ``update={"audio": …}`` 形态**（直呼锁 ``not _execution_calls(tree,"synthesize")``
与退役锁 ``test_inline_transform_machinery_retired_from_hook`` 同时成立）。
M-14 有损变换标签在 S91 收编后**由真身补齐**（``transform_presentation`` 向 ``resolve_speech_text``
传 ``audit=`` 并折进标签，偿 PLAN-VOICE2 §0.8 那笔未偿协调债）——这是相对旧内联的一处
"改了就更好"的语义差，非退化。

门链（T54 §4.2 冻结序）：hook 总键 ∧（无既有 issue）∧ ``should_voice_reply``
（总闸∧自动闸∧audio 空∧bot.chat∧scope∧确定性概率门）∧ 内容政策（含在
``resolve_speech_text`` 内，fail-closed）∧ 硬顶。安静时间/好感门/黑白名单
天然在上游 pipeline/policy 层，本 hook 只增不减地继承。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
)
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    _failure_issue,
    _issue,
    should_voice_reply,
    synthesize,
)
from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    PRESENTATION_DATA_KEY,
    CapabilityRequest,
    InvocationResult,
    InvocationStatus,
    default_invoker,
)

logger = logging.getLogger(__name__)

Enricher = Callable[
    [IncomingMessage, BotDecision, CapabilityResult],
    CapabilityResult,
]


def _envelope_failure_reason(invocation: InvocationResult) -> str:
    """非成功信封 → issue 证据串：**单一真身已上收 result_transform**（S270）。

    本函数降为薄委派——中央派发腿（``_enrich_via_central`` 拿非成功 transform 信封）与产出步
    seam（``result_transform.dub_via_central`` 拿非成功 autodub 信封）共用同一段读
    ``INVOKER_ERROR_DATA_KEY``、把异常身份**追加**进证据串的逻辑（S64 GAP-HOOK-TIMEOUT-NO-CARD
    的消费半）。判据本体见 ``rt.envelope_failure_reason``——此处不留第二份实现（禁第二真身），
    只保留 ``voice_enricher._envelope_failure_reason`` 这个既有名字给在册锁与调用点。
    """
    return rt.envelope_failure_reason(invocation)

# 同域消费 tts.py 私有构件（_issue/_failure_issue）：失败分类的唯一真相源仍在
# tts.py，本模块不复刻码表（T58 §2 纪律）。取文/政策/硬顶/无参考音 issue 映射已随
# S91 搬进中央第三形 result_transform（真身 import 同一批 tts 私有构件，仍单一真相源）。
# 注：`synthesize` 在此仅作「合成原语」引用——随中央 media.tts.autodub 请求的 context
# 交给产出步 handler（生产即 tts.synthesize 本体，逐字节等价），本模块从不出现
# `synthesize(...)` 调用点；离线单测在该 seam 注入确定性替身。


def build_voice_enricher(
    config: Any,
    *,
    content_gate: Any = None,
) -> Enricher:
    """构建配音出站 enricher（T54 §4.2 冻结签名）。

    ``content_gate``：冻结接口兼容位。当前中央内容门已内联于
    ``resolve_speech_text``→``speech_block_reason``（fail-closed 单一事实源），
    本参数保留签名形状、暂不旁接；G-2/T75 若引入可注入门再接线。
    """
    del content_gate  # 冻结兼容位（见 docstring）

    def enrich(
        message: IncomingMessage,
        decision: BotDecision,
        result: CapabilityResult,
    ) -> CapabilityResult:
        # 门链第 0/1 道：hook 总键 ∧ 无既有 issue（issue 挂载权属先到者，
        # 不覆盖能力层已挂的故障证据）。
        if not bool(getattr(config, "bot_tts_voice_hook_enabled", False)):
            return result
        if result.operational_issue is not None:
            return result
        # 门链第 2 道：完整门链谓词（总闸∧自动闸∧audio 空∧bot.chat∧scope∧概率门）。
        if not should_voice_reply(config, message, result):
            return result
        try:
            return _enrich_via_central(message, result)
        except Exception as exc:
            logger.warning("tts voice hook failed: %s", exc, exc_info=True)
            return result.model_copy(
                update={
                    "operational_issue": _issue(
                        message,
                        kind="tts_synthesize_failed",
                        retryable=False,
                        detail=f"voice hook failed: {exc}"[:200],
                    )
                }
            )

    def _enrich_via_central(
        message: IncomingMessage,
        result: CapabilityResult,
    ) -> CapabilityResult:
        # 变换走中央第三形（media.tts.autodub_transform，S91 通电 S36 落件）：取文（打码→清洗→
        # 词典→内容门）→文字硬顶→逐块产出步→合并→挂回，整段搬进真身
        # ``result_transform.transform_presentation``。本 hook 不再持第二份变换（退役内联＝删
        # 这半边的旧实现，非"内联留着、中央另加一份"＝第二真身）。
        # 门链前三道（hook 键 / 既有 issue / should_voice_reply）留在 enrich() 现读短路：「该不
        # 该配」的多数否决不派中央、零审计行（should_voice_reply 纯谓词，真身再判一次幂等）。
        def _dub(chunk: str) -> rt.DubOutcome:
            # 产出步改调单一组合口（S270 归位）：全树唯一一处 media.tts.autodub 字面 invoke 住在
            # result_transform.dub_via_central——本 hook 不再自持那份 invoke（改道＝消灭直呼/第二
            # 通路，非"另加一份"）。principal/roles/request_id/session_key 仍按会话侧真人口径交出；
            # synth=synthesize 经 context 交产出步 seam（生产即 tts.synthesize 本体，逐字节等价）。
            return rt.dub_via_central(
                config,
                chunk,
                synth=synthesize,
                principal=str(getattr(message, "sender_id", "") or "anonymous"),
                roles=("user",),
                request_id=str(getattr(message, "request_id", "") or ""),
                session_key=str(getattr(message, "session_key", "") or ""),
            )

        invocation = default_invoker().invoke(
            CapabilityRequest(
                capability_id="media.tts.autodub_transform",
                payload={"message": message, "result": result.model_dump()},
                principal=str(getattr(message, "sender_id", "") or "anonymous"),
                roles=("user",),
                request_id=str(getattr(message, "request_id", "") or ""),
                session_key=str(getattr(message, "session_key", "") or ""),
                context={"config": config, "dub": _dub},
            )
        )
        presented = invocation.data.get(PRESENTATION_DATA_KEY)
        if invocation.status is InvocationStatus.OK and isinstance(presented, dict):
            # 真身经唯一消费口挂回的呈现结果（含出站体/标签，以及"产出步失败已挂的 issue"、
            # "政策拒绝/超顶/清洗为空留的标签"）——层 1 不解析、不改写、不自拼出站体。
            return CapabilityResult.model_validate(presented)
        # 结构故障（正常不达：dub 与 payload 都由本 hook 备好）。失败可见、正文照发
        # （M-10/M-13/R-16②）：不静默、不冒充配音；载荷身份经 _envelope_failure_reason
        # 并进证据串（与产出步 seam 同一真身）。kind 唯一由 tts._FAILURE_KINDS 前缀表裁决。
        return result.model_copy(
            update={
                "operational_issue": _failure_issue(
                    message, _envelope_failure_reason(invocation)
                )
            }
        )

    return enrich
