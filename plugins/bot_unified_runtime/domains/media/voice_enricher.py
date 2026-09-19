"""配音出站 post-review hook（G-3 · M-10 根修 + M-13 自动半可观测）。

职责（T54 规格 §4.2 冻结接口，落点=本模块而非 tts.py——tts.py 现由 T75 席
独占，G-2（T61）亦未在该文件施工本 hook，见 report-T61 §八；本模块与 tts.py
同属 media 域，只消费其模块级构件、零改动）：

- **键开**（``bot_tts_voice_hook_enabled=True``）时由根装配（根 ``__init__.py``
  双态分支）惰性导入构建，经 ``RuntimePipeline.outbound_voice_enricher`` 在
  **review 批准后、render 前**调用——取文口径从「review 前的旧 body」翻正为
  「review 批准后的 body」（M-10 三害根修：被审核拦的正文不再先落盘成音频档案）；
- **失败可见**（M-13 自动半）：合成链任一真实故障挂 ``OperationalIssue``
  （kind 复用 c723904 ``_FAILURE_KINDS`` 码族，禁新造），随 SendRequest 进
  中央告警链（300s 抑制）；**政策拒绝/清洗后为空/超硬顶≠故障**（T54 §4.1#2，
  不挂 issue，政策拒绝留 audit_tag）；
- **群内正文照发**（R-16② 裁定）：hook 挂 issue 发生在 pipeline A-19 分支
  （review 前）之后，不触发「压空正文」——群内降级文案维持交中央 A-19，
  本域不自拼（S8 裁定不回退）。

与旧包装（根 ``_attach_voice_reply``→``maybe_attach_voice``）的关系：**双态
互斥**——键关部署走旧包装（逐字节现状），键开走本 hook；退役两步走的第二
步（摘旧包装）落地后本模块成为自动配音唯一路径。合成编排（取文→截断→参
数→选 ref→seed→synthesize）与 ``maybe_attach_voice`` 同构，但失败原因在
本处可见、可分类——这正是 T58 §2 判定「精确挂点必须在失败原因可见处」的
落点。该同构是有意为之的过渡态：两路互斥、不同时运行，第二步退役时旧编
排随之消亡（T75 席改 ``maybe_attach_voice`` 内部时须同步本模块，登记为协
调面）。

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
    _DEFAULT_TIMEOUT_SECONDS,
    HARD_MAX_CHARS_FALLBACK,
    _build_params,
    _failure_issue,
    _issue,
    _no_ref_audio_issue,
    _output_dir,
    _resolve_preset,
    derive_seed,
    pick_ref_audio,
    resolve_speech_text,
    should_voice_reply,
    synthesize,
)

logger = logging.getLogger(__name__)

Enricher = Callable[
    [IncomingMessage, BotDecision, CapabilityResult],
    CapabilityResult,
]

# 同域消费 tts.py 私有构件（_issue/_failure_issue/_no_ref_audio_issue 等）：
# 失败分类的唯一真相源仍在 tts.py，本模块不复刻码表（T58 §2 纪律）。


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
            # 政策拒绝≠故障（T54 §4.1#2）：零 issue，留 audit_tag（对齐命令半
            # blocked_by_policy 口径）；文字回复原样出站。
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
        # 文本硬顶（G2-R3）：超顶=放弃增益（文字照发），不挂 issue 防刷屏
        # （与命令半「拒绝合成+引导文案」不同——自动路无对话对象）。
        hard_cap = (
            int(getattr(config, "bot_tts_hard_max_chars", 0) or 0)
            or HARD_MAX_CHARS_FALLBACK
        )
        if len(speech) > hard_cap:
            logger.info(
                "tts auto reply skipped: over_hard_cap len=%d cap=%d",
                len(speech),
                hard_cap,
            )
            return result
        preset = _resolve_preset(config)
        params = _build_params(config)
        ref = pick_ref_audio(
            getattr(config, "bot_tts_ref_audios", []) or [],
            base_dir=str(getattr(config, "bot_tts_gptsovits_dir", "") or ""),
        )
        if ref is None:
            # F3 确定性失败：对应命令半 _no_ref_audio_issue 同款码。
            return result.model_copy(
                update={"operational_issue": _no_ref_audio_issue(message, config)}
            )
        speech_seed = derive_seed(
            speech,
            ref,
            params,
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            preset_id=preset.preset_id,
        )
        path, reason = synthesize(
            api_url=str(getattr(config, "bot_tts_api_url", "") or ""),
            text=speech,
            ref=ref,
            params=params,
            output_dir=_output_dir(config),
            timeout_seconds=float(
                getattr(config, "bot_tts_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            ),
            cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True)),
            preset_id=preset.preset_id,
            engine_params=dict(preset.params),
            seed=speech_seed,
            max_audio_bytes=int(getattr(config, "bot_tts_max_audio_bytes", 0) or 0),
            quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0),
            quota_max_age_days=int(
                getattr(config, "bot_tts_cache_max_age_days", 0) or 0
            ),
        )
        if path is None:
            # F4：失败原因串在本处可见 → _FAILURE_KINDS 前缀表精确分类。
            return result.model_copy(
                update={"operational_issue": _failure_issue(message, reason)}
            )
        return result.model_copy(
            update={
                "audio": [{"file": str(path), "review_text": speech}],
                "audit_tags": [
                    *result.audit_tags,
                    "tts",
                    "auto_reply",
                    f"preset={preset.preset_id}",
                    f"seed={speech_seed}",
                ],
            }
        )

    return enrich
