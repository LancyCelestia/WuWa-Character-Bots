from __future__ import annotations

import logging
import re

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    ReviewResult,
    RiskLevel,
    SessionType,
)

logger = logging.getLogger(__name__)

_INTERNAL_OUTPUT_MARKERS = (
    "[UNTRUSTED_USER_TEXT]",
    "[/UNTRUSTED_USER_TEXT]",
    "[TRUSTED_SYSTEM]",
    "[/TRUSTED_SYSTEM]",
)

_SECRET_OUTPUT_PATTERNS = (
    re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\btoken\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bcookie\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bauthkey\s*[:=]\s*(?!(?:set|missing|\[redacted\])\b)\S+"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+"),
    re.compile(r"(?i)\bbearer\s+sk-[A-Za-z0-9._-]+"),
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}"),
)


# 分级标记那一枚的**边界**（F-12，用户 2026-10-06 明示「改」）：这条形状原先左右都
# 没有词界，于是 `MAR18`／`v2R-18`／`October 18`／`R-1800`／`TR-18`／`R-1801` 一类
# 正常文本会被当违规洗掉（群聊那支的后果见 §76.9：命中＝逐段涂销）。
# 🔴 这条改动的性质＝**让红线少拦东西**（放宽一条红线腿），不是修 bug 顺手收紧。
# 词表成员一个没动：只给那枚「字母+可选分隔+数字」的形状加边界，中文那几枚一概没碰。
# 边界写法不用 `\b`，两处都是刻意的：
# ①左侧 `(?<![0-9A-Za-z])` 只挡 ASCII 字母数字——中文没有空格，`为R-18`、`标了R-18才`
#   是在册要拦的真形态，`\b` 在 Unicode 下把汉字当词字符，会把它们一起放过（＝丢真命中）；
# ②右侧 `(?![0-9])` 只挡数字续位（治 `R-1800`／`R-1801` 这类编号），同样不用 `\b`：
#   `R-18向`、`R18的` 后面跟汉字，`\b` 判不出边界⇒ 丢真命中；而 `(?![0-9A-Za-z])`
#   会连带放过 `R-18G` 一类后缀变体＝超出裁定的第二次收紧，不做。
# 单一出处：这条清单是群聊出站内容面的**唯一真身**，读点只有本模块的
# `_public_output_hits`（逐段涂销腿）与 BLOCK 腿那一处循环；`output/reviewer.py` 是
# 再导出垫片不是第二副本。执法锁＝tests/test_redline_word_boundary.py（含摘掉边界的变异腿）。
_PUBLIC_OUTPUT_UNSAFE = (
    (
        "sexual output",
        re.compile(
            r"(露骨性行为|性交|色情描写|裸体细节|(?<![0-9A-Za-z])r[- ]?18(?![0-9]))",
            re.IGNORECASE,
        ),
    ),
    ("graphic violence output", re.compile(r"(肢解|虐杀细节|血腥描写|酷刑细节)", re.IGNORECASE)),
    ("harassment output", re.compile(r"(你这个废物|你是个傻逼|公开羞辱|去死吧)", re.IGNORECASE)),
)

# 群内容面命中时**替换那一处词面**用的记号。写法沿用 `plain_text` 那几枚打码占位
# （`<本机路径已隐藏>` / `<已隐藏>`）——用 ASCII 尖括号是有原因的：`naturalize_chat_text`
# 的 `_QUOTES` 会把 `‹›「」《》` 一类引号括号当装饰字符删掉，占位符会糊成一团正文。
# 词面清单一个字没动：降级只改「命中了怎么办」，不改「什么算命中」。
_PUBLIC_OUTPUT_SPAN_PLACEHOLDER = "<已略>"
# 中和之后还得有「要说的话」才允许出门：整条就是违规内容时没有清白长文要保，
# 照旧整条 BLOCK（判据一律不放宽）。
_SUBSTANTIVE_TEXT_RE = re.compile(r"\w")

_PERSONA_DRIFT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "self_identified_as_generic_ai",
        re.compile(
            r"(?i)(作为|我是|我只是|我仅是)\s*(一个|一名)?\s*"
            r"(chatgpt|openai|ai\s*语言模型|ai\s*助手|人工智能|大语言模型|语言模型)"
        ),
    ),
    (
        "english_generic_ai_identity",
        re.compile(
            r"(?i)\b(as\s+an?\s+|i\s*(am|'m)\s+)"
            r"(ai|chatgpt|large language model|language model|openai)\b"
        ),
    ),
    (
        "refused_configured_persona",
        re.compile(r"(不能|无法).{0,8}(真正)?(成为|扮演|作为).{0,12}(守岸人|角色|人格)"),
    ),
    (
        "denied_persona",
        re.compile(r"(我没有|不具备).{0,8}(人格|角色|人设)"),
    ),
)


def _redact_output_match(value: str) -> str:
    redacted = value
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|cookie|authkey)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}=[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+",
        "authorization=Bearer [redacted]",
        redacted,
    )
    redacted = re.sub(r"(?i)\bbearer\s+sk-[A-Za-z0-9._-]+", "Bearer [redacted]", redacted)
    redacted = re.sub(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]{8,}", "sk-[redacted]", redacted)
    return redacted


def _unsafe_output_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    if any(marker in text for marker in _INTERNAL_OUTPUT_MARKERS):
        reasons.append("unsafe output leakage")

    matched_fragments = [
        _redact_output_match(match.group(0))
        for pattern in _SECRET_OUTPUT_PATTERNS
        for match in pattern.finditer(text)
    ]
    if matched_fragments:
        reasons.append("unsafe output leakage")
        reasons.append(f"redacted fragments: {', '.join(matched_fragments)}")

    deduped: list[str] = []
    for reason in reasons:
        if reason in deduped:
            continue
        deduped.append(reason)
    return deduped


def _persona_drift_reasons(result: CapabilityResult, text: str) -> list[str]:
    if result.capability_id != "bot.chat":
        return []
    return [
        f"persona drift: {name}"
        for name, pattern in _PERSONA_DRIFT_PATTERNS
        if pattern.search(text)
    ]


# 媒体/前置部件里可能承载「会出门的文本」的键。
# 分两档用：泄漏面（密钥、内部标记）扫全部键；内容面（露骨/暴力/辱骂）只扫
# **消息载荷**那几个键——卡片里的 `label`/`description` 常是上游原文（新闻标题、
# 公告摘录），拿内容面去裁它们会把正常卡片误杀。
_META_TEXT_KEYS: tuple[str, ...] = (
    "text", "content", "caption", "alt", "label", "name", "title", "description",
    "review_text",
)
_PAYLOAD_TEXT_KEYS: tuple[str, ...] = ("text", "content", "caption", "alt", "review_text")
_MEDIA_FIELDS: tuple[str, ...] = (
    "images", "audio", "video", "files", "prefix_parts", "actions",
)
# 降级腿按**载体**分面：文字载体（正文 / `text_parts` / `prefix_parts`）出去的就是
# 这串字符，改得掉；媒体载荷（图/音/视频/文件/动作）里那串字符是**内容本身**，
# 中和不掉 ⇒ 那一面照旧整条 BLOCK。两桶由 `_MEDIA_FIELDS` 派生，不另立清单。
_SPAN_TEXT_CARRIER_FIELDS: tuple[str, ...] = ("prefix_parts",)
_SPAN_MEDIA_ONLY_FIELDS: tuple[str, ...] = tuple(
    field for field in _MEDIA_FIELDS if field not in _SPAN_TEXT_CARRIER_FIELDS
)
_ScanHit = tuple[str, re.Pattern[str], str]


def _iter_part_texts(item: object, keys: tuple[str, ...]) -> list[str]:
    if isinstance(item, str):
        return [item] if item.strip() else []
    if not isinstance(item, dict):
        return []
    found: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    return found


def _collect_scan_text(
    result: CapabilityResult,
    primary: str,
    keys: tuple[str, ...],
    *,
    fields: tuple[str, ...] = _MEDIA_FIELDS,
    include_parts: bool = True,
) -> str:
    """把会出门的文本汇成一条待审串。

    ⚠️ 这只喂规则，**不参与 `safe_text`**：`renderer.py` 拿 `safe_text` 当外发正文，
    把媒体文本混进去会让一条音频额外发成一条文字消息。
    `fields` / `include_parts` 是给群聊降级腿分载体用的（默认值＝原有两枚调用点
    的采集面，一字未动）。
    """
    chunks: list[str] = [primary] if primary.strip() else []
    if include_parts:
        for part in result.text_parts or []:
            chunks.extend(_iter_part_texts(part, ("text",)))
    for field in fields:
        for item in getattr(result, field, None) or []:
            chunks.extend(_iter_part_texts(item, keys))
    return "\n".join(dict.fromkeys(chunks))


def _public_output_hits(text: str) -> list[_ScanHit]:
    """群内容面在 `text` 里的命中（清单顺序，条目 = 标签 / 词面 / 命中的那一段）。"""
    hits: list[_ScanHit] = []
    for label, pattern in _PUBLIC_OUTPUT_UNSAFE:
        match = pattern.search(text)
        if match is not None:
            hits.append((label, pattern, match.group(0)))
    return hits


def explicit_output_spans(text: str) -> list[tuple[int, int]]:
    """群侧那把露骨尺的**区间形态**：返回命中词面在 `text` 里的 `(start, end)` 半开区间。

    清单与 `_public_output_hits` 逐字同一枚真身（`_PUBLIC_OUTPUT_UNSAFE`），这里只是
    把"命中了什么"换成"命中在哪"——Telegram 遮罩（用户 2026-10-06 裁「色情、敏感内容
    在 tg 加遮罩，QQ 不拦也不做措施」）要的是坐标，涂销要的是标签，两读点零第二词表。
    方向上是**少包不多包**：三枚模式各只取**第一处**命中（与 `_public_output_hits` 的
    `pattern.search` 同口径），重叠区间合并一次，所以同一词面在一句里出现三次不会罩三段。
    """
    spans: list[tuple[int, int]] = []
    for _label, pattern in _PUBLIC_OUTPUT_UNSAFE:
        match = pattern.search(text)
        if match is not None and match.end() > match.start():
            spans.append((match.start(), match.end()))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _neutralise_public_spans(text: str, hits: list[_ScanHit]) -> str:
    """把命中的**那一处**换成记号，其余字符一个不动（就地中和，不整条丢掉）。

    沿用本模块 `_redact_output_match` 的同一种动作（`re.sub` 打占位），不另起引擎。
    """
    scrubbed = text
    for _label, pattern, _span in hits:
        scrubbed = pattern.sub(_PUBLIC_OUTPUT_SPAN_PLACEHOLDER, scrubbed)
    return scrubbed


def _neutralise_part_payload(item: dict[str, object], hits: list[_ScanHit]) -> dict[str, object]:
    """中和一个字典部件里的外发文本，返回**副本**（原物件不动，落地时机由调用方管）。"""
    scrubbed: dict[str, object] = dict(item)
    for key in _PAYLOAD_TEXT_KEYS:
        value = scrubbed.get(key)
        if isinstance(value, str):
            scrubbed[key] = _neutralise_public_spans(value, hits)
    return scrubbed


def _try_neutralise_group_output(
    result: CapabilityResult,
    output_text: str,
) -> tuple[str, list[str]] | None:
    """群聊命中面降级腿：中和文字载体里的那一处，其余正文/部件/媒体照旧出门。

    返回 `(中和后的正文, 审计记号)`；以下情形一律返回 `None` ⇒ 调用方退回改前
    那一手（整条 BLOCK，一字不变）：
    ①文字载体里根本没命中；②命中的是改不掉的媒体载荷；③中和后没剩下要说的话；
    ④本腿内部出错（fail-open：坏掉只退回旧形态，绝不放行未中和的文本）。
    """
    try:
        text_hits = _public_output_hits(
            _collect_scan_text(
                result,
                output_text,
                _PAYLOAD_TEXT_KEYS,
                fields=_SPAN_TEXT_CARRIER_FIELDS,
            )
        )
        if not text_hits:
            return None
        if _public_output_hits(
            _collect_scan_text(
                result,
                "",
                _PAYLOAD_TEXT_KEYS,
                fields=_SPAN_MEDIA_ONLY_FIELDS,
                include_parts=False,
            )
        ):
            return None
        scrubbed_primary = _neutralise_public_spans(output_text, text_hits)
        scrubbed_parts = (
            [_neutralise_public_spans(part, text_hits) for part in result.text_parts]
            if result.text_parts is not None
            else None
        )
        scrubbed_prefixes = [
            _neutralise_part_payload(part, text_hits)
            for part in (result.prefix_parts or [])
        ]
        # 中和后还剩话可说吗？（记号本身不算——「整条就是违规内容」要照旧拦。）
        residue = [scrubbed_primary, *(scrubbed_parts or [])]
        residue.extend(
            text for part in scrubbed_prefixes for text in _iter_part_texts(part, _PAYLOAD_TEXT_KEYS)
        )
        if not any(
            _SUBSTANTIVE_TEXT_RE.search(value.replace(_PUBLIC_OUTPUT_SPAN_PLACEHOLDER, ""))
            for value in residue
        ):
            return None
        # 全部算完才落地：正文与部件一起换，不留「改了一半」的中间态。
        if scrubbed_parts is not None:
            result.text_parts = scrubbed_parts
        if result.prefix_parts:
            result.prefix_parts = scrubbed_prefixes  # type: ignore[assignment]
        markers = [
            f"public output span neutralised: {label}" for label, _pattern, _span in text_hits
        ]
        # 记号里**只有规则名**：命中的那一段是回复原文，`_redact_output_match` 只脱
        # 密钥不脱内容，而这一串如今会经 `ReviewResult.reasons` 落进审计行
        # （`pipeline._complete` 的 `stage="review"`）⇒ 原文一律不落盘，判据不变。
        return scrubbed_primary, markers
    except Exception:  # 降级腿坏了就退回旧形态，不许带出新删除/新泄露
        logger.warning(
            "group output downgrade leg failed request_id=%s",
            getattr(result, "request_id", ""),
            exc_info=True,
        )
        return None


def _is_public_space_scope(scope: object) -> bool:
    """这一轮的作用域是不是**公共空间**（「旁人也在看」）——群与频道同侧。

    本函数**不设判据**，只做两件事：把契约枚举收成规范值字符串、转述轴心那把唯一的尺
    （`domains/chat_reply/runtime/content_route.is_public_space_session`；成员表只住它
    那一处，这里再抄一份就是第二把尺，本仓的门与裁定都不认）。

    🔴 必须取 `.value` 再交，不能裸交枚举：`SessionType` 是 `str` 混入枚举，而
    `str(SessionType.GROUP)` 得到的是 `"SessionType.GROUP"` 不是 `"group"`（Py 3.12
    现算）——那一交会让判据对**每一个**会话都回假，正好把本波要收紧的那一格又静默松开
    （形态同台账 #68「三面齐、缺一必红」里「接线在盘、判据哑」那一型）。
    口径同 `capabilities/chat.py` 的 `_session_type_value = str(getattr(..., "value", ""))`。

    懒 import（不在模块头）：`domains/chat_reply/runtime/__init__` 会拉起 `pipeline`，
    而 `pipeline` 回头 import 本模块 ⇒ 模块级导入成环；同目录 `renderer.py` 引
    chat_reply 走的也是这一手，先例在册。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
        is_public_space_session,
    )

    raw = getattr(scope, "value", scope)
    return is_public_space_session(str(raw) if isinstance(raw, str) else "")


def review_capability_result(
    result: CapabilityResult,
    decision: BotDecision,
) -> ReviewResult:
    reasons: list[str] = []
    action = ReviewAction.ALLOW
    approved = True
    output_text = result.body or result.summary or result.title
    # 泄漏面（密钥/内部标记）与内容面（露骨/暴力/辱骂）各扫各的文本集：
    # 过去两者都只看 body→summary→title，媒体能力把这三样留空 ⇒ 审核恒无输入。
    leak_text = _collect_scan_text(result, output_text, _META_TEXT_KEYS)
    payload_text = _collect_scan_text(result, output_text, _PAYLOAD_TEXT_KEYS)
    # 外发正文：默认就是原文，只有公共空间（群/频道）那支降级腿会把它换成中和后的版本。
    # persona 审与内容审一律看**原文**——降级只改「出去的是什么」，不改「判据读到什么」。
    outbound_text = output_text

    if result.risk_level is RiskLevel.CRITICAL:
        approved = False
        action = ReviewAction.BLOCK
        reasons.append("critical risk is blocked")

    unsafe_reasons = _unsafe_output_reasons(leak_text)
    if unsafe_reasons:
        approved = False
        action = ReviewAction.BLOCK
        reasons.extend(unsafe_reasons)

    if _is_public_space_scope(decision.target_scope):
        # 不再限定 `bot.chat`：任何能力把不安全内容发进群都该拦（媒体能力免检
        # 是 M-02 的中央半）。persona 审仍只看 chat 自己的话——语音命令的正文
        # 是用户原文，不该被当成「守岸人自述」。
        # 2026-10-04 降级波（席 grpfix）：词面**只落在可改字节的文字载体**时不再
        # 整条吃掉——中和那一处、其余正文/部件/媒体照发，审计记一行降级记号
        # （事件名 `ReviewAction.REWRITE`；落盘面＝`pipeline._complete` 里那枚
        # `stage="review"` 的 AuditRecord，与 BLOCK **同一条**通道——2026-10-04 席
        # auditrow 补的就是这一手，改前该行**从未写出**，锁 ⑥ 那一腿跑真管线）。
        # 命中在媒体载荷 / 中和后没剩下要说的话 / 本腿内部出错 ⇒ 一律退回下面
        # 那一手（＝改前形态，一字不变）。
        # 2026-10-06 公共空间归侧（用户裁「telegram 频道＝群侧」）：这一支的作用域
        # 判据由 `target_scope is SessionType.GROUP` **单值**改为转述轴心那把尺
        # （见 `_is_public_space_scope`），`channel` 自此与 `group` 过**同一道**闸。
        # 🔴 方向只有变严：词面清单、两种退回 BLOCK 的情形、私聊/控制台/邮件三面
        # 一字未动（本波没放宽任何一条腿）。改前频道轮**根本不过这道闸**——命中面
        # 原样出门，锁＝`tests/test_reviewer_group_downgrade.py` 第⑦节。
        downgrade = _try_neutralise_group_output(result, output_text) if approved else None
        if downgrade is not None:
            outbound_text, neutralised_markers = downgrade
            action = ReviewAction.REWRITE
            reasons.extend(neutralised_markers)
        else:
            for label, pattern in _PUBLIC_OUTPUT_UNSAFE:
                if pattern.search(payload_text):
                    approved = False
                    action = ReviewAction.BLOCK
                    reasons.append(label)

    persona_drift_reasons = _persona_drift_reasons(result, output_text)
    if persona_drift_reasons:
        approved = False
        action = ReviewAction.BLOCK
        reasons.extend(persona_drift_reasons)

    if (
        result.privacy_level in {PrivacyLevel.PERSONAL, PrivacyLevel.CREDENTIALED}
        and decision.target_scope is SessionType.GROUP
    ):
        approved = False
        if action is not ReviewAction.BLOCK:
            action = ReviewAction.MOVE_PRIVATE
        reasons.append("personal output cannot be sent to group")

    return ReviewResult(
        request_id=result.request_id,
        approved=approved,
        action=action,
        risk_level=result.risk_level,
        privacy_level=result.privacy_level,
        reasons=reasons,
        safe_text=outbound_text,
        debug_id=result.debug_id,
    )
