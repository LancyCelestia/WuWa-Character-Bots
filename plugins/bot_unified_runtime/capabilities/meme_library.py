"""群聊表情包能力（bot.meme_library）：/偷表情 按权重随机发送入库表情。

权重策略（来源 meme_library.py）：
- VLM 判定非表情/普通图片降权；NSFW≥0.2 再降权，≥0.8 永不发送；
- 守岸人/岸宝 最优先，其次 鸣潮/战双帕弥什/库洛，再次 ACG，最后普通；
- 支持关键词/情绪标签过滤；带冷却时间防刷屏风控；
- N4 情绪档：bot 心情低落（valence ≤ -0.25，与 mood.py 低落档同阈值）时
  少推吵闹梗——命中吵闹标签的候选有限次重抽，全部吵闹也照发（只调
  倾向，绝不硬开关）；心情未接入/中性时行为不变。
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)

_COMMAND_RE = re.compile(
    # meme random(?![a-z0-9]) / steal meme(?![a-z0-9])：ASCII 短语右侧词边界
    # （wiki _alias_hit 先例），randomqq/memeqq 类胶合不触发（边界体检 ×2 清账）。
    # steal(?!\S)(?! meme[a-z0-9])：裸「steal」精确命中（帮助别名 'steal' 的
    # 实际触发，T-Spec T1.2）之外，再挡「steal memeqq」借道裸 steal 把胶合
    # 吃进 arg；stealing/steal a car 等不触发。
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：toutu/toubiaoqing 族同音覆盖
    # 偷圖/偷图 简繁词；(?![a-z0-9]) 右边界同边界纪律（toutuq/tbqq 类胶合
    # 不触发）；sjbq 为 随机表情/随机表情包 同能力双词共享缩写（变体对口径
    # 启用一次）；bqsj/tbq 与 bot.meme 的 bqb 族前缀不同串、零冲突。
    r"^[/!！]?(?:偷表情|偷表情包|表情随机|随机表情|随机表情包|"
    r"表情抽签|表情隨機|隨機表情|隨機表情包|表情抽籤|"
    r"toubiaoqingbao(?![a-z0-9])|tbqb(?![a-z0-9])"
    r"|toubiaoqing(?![a-z0-9])|tbq(?![a-z0-9])"
    r"|suijibiaoqingbao(?![a-z0-9])|suijibiaoqing(?![a-z0-9])|sjbq(?![a-z0-9])"
    r"|biaoqingsuiji(?![a-z0-9])|bqsj(?![a-z0-9])"
    r"|biaoqingchouqian(?![a-z0-9])|bqcq(?![a-z0-9])"
    r"|toutu(?![a-z0-9])|tt(?![a-z0-9])"
    r"|memes? random(?![a-z0-9])|steal meme(?![a-z0-9])"
    r"|steal(?!\S)(?! meme[a-z0-9])|偷圖|偷图|偷表情包)\s*(?P<arg>.*)$",
    re.IGNORECASE,
)
_STATS_RE = re.compile(
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：biaoqingku/biaoqingtongji 同
    # 表情库/表情统计；\s*$ 结构天然成界。memes? stats(?![a-z0-9]) 兜底
    # 「memes stats」复数误拼（同 _COMMAND_RE 的 memes? random 款）；
    # bot.meme 侧 meme/memes 双裸词均带 (?! (?:random|stats)\b) 负向前瞻，
    # 本变体不被表情生成抢匹配。
    r"^[/!！]?(?:表情库统计|biaoqingtongji(?![a-z0-9])|bqtj(?![a-z0-9])"
    r"|表情统计|表情库|biaoqingku(?![a-z0-9])|bqk(?![a-z0-9])"
    r"|memes? stats(?![a-z0-9]))\s*$",
    re.IGNORECASE,
)

# 冷却登记 LRU 上限：会话数极大时防止 dict 无界慢泄漏（审计 #30）。
_COOLDOWN_CAP = 4096

# ---- N4 情绪档：低落时少推吵闹梗 ----
# 阈值与 character/mood.py 的低落档（_V_NEGATIVE）同源，改值需两处同步。
_MOOD_LOW_VALENCE = -0.25
# 吵闹标签（VLM emotion/scene/description 常见口径的保守子集）。
_NOISY_MEME_TERMS = (
    "搞笑", "沙雕", "整活", "鬼畜", "爆笑", "疯狂", "抽象", "玩梗", "兴奋", "吵闹",
)
# 心情低落时对吵闹候选的最大重抽次数（含首次）；重抽是倾向不是硬开关。
_MOOD_REPICK_ATTEMPTS = 3


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        [
            str(candidate.get("description", "") or ""),
            str(candidate.get("emotion_tags", "") or ""),
            str(candidate.get("scene_tags", "") or ""),
        ]
    ).lower()


def _is_noisy_meme(candidate: dict[str, Any]) -> bool:
    text = _candidate_text(candidate)
    return any(term in text for term in _NOISY_MEME_TERMS)


def _pick_with_mood(
    store: Any,
    *,
    keyword: str,
    nsfw_max: float,
    mood_muted: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """加权挑选；心情低落时对吵闹候选做有限次重抽（软偏置）。

    返回 (候选|None, 是否发生过吵闹回避)。候选耗尽/全部吵闹时照常返回，
    绝不因情绪档把空手结果放大。
    """
    picked = store.weighted_pick(keyword=keyword, nsfw_max=nsfw_max)
    if not mood_muted or picked is None or not _is_noisy_meme(picked):
        return picked, False
    avoided = False
    for _ in range(_MOOD_REPICK_ATTEMPTS - 1):
        alternative = store.weighted_pick(keyword=keyword, nsfw_max=nsfw_max)
        if alternative is None:
            break
        if not _is_noisy_meme(alternative):
            return alternative, True
        avoided = True
    return picked, avoided


def is_meme_library_command(text: str) -> bool:
    stripped = (text or "").strip()
    return _COMMAND_RE.match(stripped) is not None or _STATS_RE.match(stripped) is not None


def parse_meme_library_command(text: str) -> tuple[str, str]:
    """返回 (动作, 参数)。动作：pick / stats。"""
    stripped = (text or "").strip()
    match = _STATS_RE.match(stripped)
    if match:
        return "stats", ""
    match = _COMMAND_RE.match(stripped)
    if not match:
        raise ValueError("not a meme library command")
    return "pick", (match.group("arg") or "").strip()


def build_meme_library_capability(
    store: Any,
    config: Any | None = None,
    *,
    mood_valence_fn: Callable[[], float] | None = None,
) -> Any:
    cooldown: OrderedDict[str, float] = OrderedDict()
    cooldown_seconds = int(getattr(config, "bot_meme_library_cooldown_seconds", 20) or 20)
    nsfw_max = float(getattr(config, "bot_meme_library_nsfw_max", 0.2) or 0.2)

    def _mood_muted() -> bool:
        """bot 心情是否低落到该收敛语气档；未接入/读取失败一律 False。"""
        if mood_valence_fn is None:
            return False
        try:
            return float(mood_valence_fn()) <= _MOOD_LOW_VALENCE
        except Exception:  # noqa: BLE001 - 心情读取失败按中性处理。
            return False

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        try:
            action, arg = parse_meme_library_command(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                body="用法：偷表情 [关键词|情绪标签|私聊]；表情库统计 查看数量。",
                audit_tags=["meme_library", "usage"],
            )
        if action == "stats":
            stats = store.stats()
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                title="表情库",
                body=(
                    f"已收藏 {stats['total']} 张，累计发送 {stats['used_total']} 次，"
                    f"高危拦截 {stats['nsfw_blocked']} 张。"
                ),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "stats"],
            )

        # 冷却：同一会话防刷屏，避免 QQ 风控。
        key = f"{message.session_id}:{message.sender_id}"
        now = time.monotonic()
        # 有界化（审计重发现）：会话键无界增长，超阈值先清过期再裁最旧。
        if len(cooldown) > 512:
            for stale in [k for k, ts in cooldown.items() if now - ts >= cooldown_seconds]:
                cooldown.pop(stale, None)
            while len(cooldown) > 512:
                cooldown.popitem(last=False)
        if key in cooldown:
            cooldown.move_to_end(key)
            if now - cooldown[key] < cooldown_seconds:
                remaining = int(cooldown_seconds - (now - cooldown[key])) + 1
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme_library",
                    kind="text",
                    # 审查 Q-03：失败/限流类文案统一去语气符「～」（守岸人语气
                    # 温和但不拖尾音，与 user_copy.py 池内句式口径一致）。
                    body=f"表情包还在冷却中，请 {remaining} 秒后再来偷。",
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PERSONAL,
                    audit_tags=["meme_library", "cooldown"],
                )

        keyword = "" if arg.lower() in {"私聊", "私聊我", "private", "私"} else arg
        picked, avoided_noisy = _pick_with_mood(
            store, keyword=keyword, nsfw_max=nsfw_max, mood_muted=_mood_muted()
        )
        if picked is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme_library",
                kind="text",
                # 审查 Q-04：自称统一第三人称「守岸人」（原为第一人称自称，旧句已废）。
                # 审查 Q-03：失败类文案去语气符「～」（正常发送回执「给你偷来一张
                # 表情～」属正常对话类，不在本项范围，保留原样）。
                body="表情库还是空的（或没有匹配的表情）。多发点图给守岸人收藏吧。",
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme_library", "empty"],
            )
        cooldown[key] = now
        cooldown.move_to_end(key)
        while len(cooldown) > _COOLDOWN_CAP:
            cooldown.popitem(last=False)
        tags = ["meme_library", "pick", f"weight:{picked.get('weight')}"]
        if avoided_noisy:
            tags.append("mood_muted")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.meme_library",
            kind="mixed",
            title="表情包",
            body="给你偷来一张表情～",
            images=[{"file": str(picked["path"])}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=tags,
        )

    return capability
