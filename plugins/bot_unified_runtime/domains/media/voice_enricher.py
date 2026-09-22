"""配音出站 post-review hook（G-3 · M-10 根修 + M-13 自动半；VOICE-V12 收编中央调度层）。

职责（T54 规格 §4.2 冻结接口，落点=本模块而非 tts.py——tts.py 现由 T75 席
独占，G-2（T61）亦未在该文件施工本 hook，见 report-T61 §八；本模块与 tts.py
同属 media 域，只消费其模块级构件）：

- **键开**（``bot_tts_voice_hook_enabled=True``）时由根装配（根 ``__init__.py``
  双态分支）惰性导入构建，经 ``RuntimePipeline.outbound_voice_enricher`` 在
  **review 批准后、render 前**调用——取文口径从「review 前的旧 body」翻正为
  「review 批准后的 body」（M-10 三害根修：被审核拦的正文不再先落盘成音频档案）；
- **产出步走中央**（VOICE-V12 · mandate「所有内容走中央调度层，TTS 也不例外」）：
  合成这一步（一句话→一段音频）不再直呼 ``tts.synthesize``，而是
  ``default_invoker().invoke(CapabilityRequest(capability_id="media.tts.autodub", …))``，
  层 2（权限/健康/超时/降级/中央审计）对它执法。门链（该不该配）与取文/政策/硬顶
  仍留在本 hook（层 1 本职：每条「不配」零合成、零中央审计行）；
- **失败可见**（M-13 自动半）：中央返回非成功终态 ⇒ hook 按 status 映射既有
  ``OperationalIssue``（kind 复用 c723904 ``_FAILURE_KINDS`` 码族，禁新造），随 SendRequest
  进中央告警链（300s 抑制）；**政策拒绝/清洗后为空/超硬顶≠故障**（T54 §4.1#2，
  不挂 issue、不进中央，政策拒绝留 audit_tag）；
- **群内正文照发**（R-16② 裁定）：hook 挂 issue 发生在 pipeline A-19 分支
  （review 前）之后，不触发「压空正文」——群内降级文案维持交中央 A-19，
  本域不自拼（S8 裁定不回退）。

与旧包装（根 ``_attach_voice_reply``→``maybe_attach_voice``）的关系：**双态
互斥**——键关部署走旧包装（逐字节现状），键开走本 hook。产出步真身已收成
``tts.synthesize_autodub`` 单一真身，本 hook、中央 handler、旧包装三处消费边共用
它（旧包装退役=V3，另批）。合成产物随件带 ``content_sha256``（M-64/S2）。

**出站体归属（VOICE-CENTRAL-UNBLOCK 2026-09-22）**：``audio`` 部件与
``tts/auto_reply/preset=/seed=/audio_sha256=`` 标签由中央产出步 ``synthesize_autodub``
**一处拼装**（那个函数就是刚产出这段字节的地方），本 hook 只经
``tts.autodub_presentation_update`` 把成品挂回呈现契约——层 1 从此不自拼出站体，
也不再出现 ``update={"audio": …}`` 形态（A4「音频来路不明」对本模块空转成立，
直呼锁 ``not _execution_calls(tree,"synthesize")`` 同时保持成立）。
M-14 有损变换标签在本路收编前后**都是空**：本 hook 从不向 ``resolve_speech_text``
传 ``audit=``，故无 lossy 事实可记（本席只搬拼装点，不顺手改这条判定）。

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
    _no_ref_audio_issue,
    autodub_presentation_update,
    resolve_speech_text,
    should_voice_reply,
    synthesize,
)
from plugins.bot_unified_runtime.domains.media.tts_presets import (
    resolve_hard_max_chars,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    CapabilityRequest,
    InvocationStatus,
    default_invoker,
)

logger = logging.getLogger(__name__)

Enricher = Callable[
    [IncomingMessage, BotDecision, CapabilityResult],
    CapabilityResult,
]

# 同域消费 tts.py 私有构件（_issue/_failure_issue/_no_ref_audio_issue 等）：
# 失败分类的唯一真相源仍在 tts.py，本模块不复刻码表（T58 §2 纪律）。
# 注：`synthesize` 在此**直呼已消失**——它只作为「合成原语」引用随中央请求的 context
# 交给 media.tts.autodub handler（生产即 tts.synthesize 本体，逐字节等价），本模块不再
# 出现 `synthesize(...)` 调用点（直呼旁路就此闭合；离线单测在该 seam 注入确定性替身）。


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
            return _enrich_locked(message, result)
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

    def _enrich_locked(
        message: IncomingMessage,
        result: CapabilityResult,
    ) -> CapabilityResult:
        # 取文（M-10 根修）：入参=hook 时点的 result.body——review 批准后的正文。
        # 打码→清洗→词典→内容政策全在 resolve_speech_text 单一口内（fail-closed）。
        max_chars = int(getattr(config, "bot_tts_auto_reply_max_chars", 0) or 0)
        speech, blocked = resolve_speech_text(
            config,
            message,
            result.body or result.summary or "",
            max_chars=max_chars,
        )
        if blocked:
            # 政策拒绝≠故障（T54 §4.1#2）：零 issue、不进中央（连一次终态审计都不该有），
            # 留 audit_tag（对齐命令半 blocked_by_policy 口径）；文字回复原样出站。
            logger.info("tts auto reply blocked by policy: category=%s", blocked)
            return result.model_copy(
                update={
                    "audit_tags": [
                        *result.audit_tags,
                        "tts",
                        "auto_reply",
                        "blocked_by_policy",
                    ]
                }
            )
        if not speech:
            # 清洗后为空：无增益可加，也非故障，零留痕（与旧包装一致）。
            return result
        # 文本硬顶（G2-R3）：超顶=放弃增益（文字照发），不挂 issue 防刷屏、不进中央
        # （与命令半「拒绝合成+引导文案」不同——自动路无对话对象）。
        hard_cap = resolve_hard_max_chars(config)
        if len(speech) > hard_cap:
            logger.info(
                "tts auto reply skipped: over_hard_cap len=%d cap=%d",
                len(speech),
                hard_cap,
            )
            return result
        # 产出步走中央：合成这一步（preset/ref/seed/synthesize/摘要）交
        # media.tts.autodub 能力，层 2 治理（权限/健康/90s 超时/降级/审计）对它执法。
        invocation = default_invoker().invoke(
            CapabilityRequest(
                capability_id="media.tts.autodub",
                payload={"text": speech},
                principal=str(getattr(message, "sender_id", "") or "anonymous"),
                # 门链已保证这是会话侧真人（should_voice_reply 只放 bot.chat 真人回复），
                # 主体恒含 user；层 2 人门据此执法（blocked 主体=1 增量，fail-closed 方向正确）。
                roles=("user",),
                request_id=str(getattr(message, "request_id", "") or ""),
                session_key=str(getattr(message, "session_key", "") or ""),
                context={"config": config, "synthesize": synthesize},
            )
        )
        status = invocation.status
        if status is InvocationStatus.OK:
            # 出站体（音频部件 + tts/auto_reply/preset/seed/audio_sha256 标签）由中央
            # 产出步 ``tts.synthesize_autodub`` **一处拼装**，本层只把它挂回呈现契约
            # （VOICE-CENTRAL-UNBLOCK 2026-09-22：层 1 不再自拼 audio 体，中央路既有
            # synthesize 又交出站体）。字段值与顺序与收编前逐字节一致——同一批值换了拼装点。
            return result.model_copy(
                update=autodub_presentation_update(result, dict(invocation.data))
            )
        if status is InvocationStatus.NOT_CONFIGURED:
            # 无可用参考音频=F3 确定性失败，对应命令半 _no_ref_audio_issue 同款码。
            return result.model_copy(
                update={"operational_issue": _no_ref_audio_issue(message, config)}
            )
        # 其余非成功终态（FAILED/DEGRADED/TIMEOUT/LIMIT_EXCEEDED/DENIED…）=故障面：
        # 不配音、只发文字（M-10/M-13/R-16②/A-19 在册语义逐字保留），挂可分类 issue。
        # 「挂死不出诊断卡」那条缺口（待裁 10/15）在册不执法——本处只映射 issue，不假称已修。
        return result.model_copy(
            update={"operational_issue": _failure_issue(message, invocation.detail)}
        )

    return enrich
