from __future__ import annotations

import atexit
import base64
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    PrivacyLevel,
    RenderedOutput,
    ReviewResult,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.render.plain_text import (
    naturalize_chat_text,
    redact_destructive_commands,
    redact_local_secrets,
)

logger = logging.getLogger(__name__)


# ============ 出站文本「内部标记 + 不可见格式控制」第二道闸（F-G7 / INJ-G4，SEAT-R3-MARKER）============
# 上面那族只做**打码**（盘符 / BOT_XXX= / sk-），它不认两件事：
#   1. 内部边界标记（`[引用回复 层级1 x]` / `[TRUSTED_SYSTEM]`）——渲染腿过去是个
#      **未消毒出口**：`neutralize_internal_markers` 全树消费点里根本没有 `domains/render/*`
#      （INJ-G4 取证）。出站的正文/部件文本里只要残留一枚活标记，卡片/合并转发人读层
#      就能被伪造的块边界「看着是另一回事」。
#   2. RTL 强控 / 零宽 / 格式控制符（U+202E RLO、U+200E LRM、U+200F RLM、U+FEFF BOM 一族）——
#      出卡与出站文本里嵌一枚就把显示顺序倒转、把 `BOT_XXX=` 拆开躲过打码（F-G7）。
# 处置**只用既有中央真身**，本件零新正则、零新码点表（禁第二真身）：
#   - 边界半＝`chat_reply.security.injection.neutralize_internal_markers`
#     （判据唯一住 `ingest/message_context.INTERNAL_MARKER_PATTERN`，单源锁见
#     `tests/test_injection_marker_single_source.py`）；
#   - 伪装半＝`core.safety_exec.attack_surface.strip_display_controls`
#     （码点表唯一住 `_BIDI_CONTROLS`/`_INVISIBLE_CONTROLS`，表情 ZWJ 在册豁免）。
# 顺序刻意：**先打码、后换形/剥除**——`redact_local_secrets` 的行为面一字不动（另一席在
# 这族上有在飞改动，简报红线）；这两步只在打码产物上再做「可见字节对齐真实码点」。
# **Fail-open**：任一中央件抛异常一律原样交回——卡渲染契约的铁律是「失败→纯文本兜底且
# 契约零破坏」，消毒绝不许成为新的故障点或抛点。两枚函数对干净文本都是恒等/幂等，
# 因此正常回复逐字节不变。
def _neutralize_outbound_text(text: str) -> str:
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
            neutralize_internal_markers,
        )
        from plugins.bot_unified_runtime.domains.core.safety_exec import (
            attack_surface as _attack_surface,
        )

        guarded = _attack_surface.strip_display_controls(text or "")
        return neutralize_internal_markers(guarded)
    except Exception:
        logger.warning("renderer outbound marker/display neutralize failed; fail-open", exc_info=True)
        return text


def _redact_outbound_text(text: str) -> str:
    """出站文本咽喉：破坏性命令行内整段打码（需求17 渲染层兜底，围栏豁免），
    再盘符路径 / `BOT_XXX=` / `sk-` / JWT / Bearer 统一打码，
    再过内部标记全角化 + 不可见格式控制剥除（F-G7 / INJ-G4，fail-open）。

    分层分工（需求17，2026-10-03）：chat 回复的危险命令**主裁决**在 chat 层
    （`chat_reply/security/dangerous_command.py`：全文替换＋审计标签）；本咽喉这
    条 `redact_destructive_commands` 是**渲染层兜底**——罩其余能力出站与 chat
    漏网面，行内打码不动全文、围栏代码块豁免。破坏性命令腿必须排在
    `redact_local_secrets` **之前**：密钥打码的路径腿会先吃掉 `of=/dev/...`
    一类目标形态，反序会让命令骨架漏网（两层链式幂等，锁在
    `tests/test_destructive_command_redaction.py` 与 `tests/test_dangerous_command_outbound_wiring.py`）。

    打码幂等由 `redact_local_secrets` 自身保证（替换产物不再被任一形态命中），
    所以 bot.chat 那条已在能力层打过一次的链路重复过一遍零成本、零二次伤害；
    消毒两步对干净文本恒等，经能力层已消毒的链路再过一次零副作用。
    """
    return _neutralize_outbound_text(
        redact_local_secrets(redact_destructive_commands(text or ""))
    )

# ==================== 出站文本统一打码咽喉（需求 17 / S-ANTATK，2026-09-27）====
# 此前 `redact_local_secrets` 的**读点全散在能力层自己**：chat 回复在 chat.py 调、
# 校园转发出站调、邮件附件的主题与正文调、creation/cookies 面板各自调——**凡是记得调
# 的才罩**，共用的出站成形口一次都不过。后果是任何一条能力（卡片正文与
# text_fallback、文件与预览回显、账单/状态页、合并转发节点、部件里的 caption）
# 罩没罩，取决于写那条能力的人记不记得。AGENTS 铁律 3 写着「出站前
# plain_text.redact_local_secrets 会打码盘符路径/BOT_XXX=/sk- 形态，不要绕过」，
# 而流程图「output/plain_text → output/renderer」这一步在真码里从来没有统一落点。
# 收在这里的理由：`render_reviewed_output` 是 review 之后、SendRequest 之前
# **唯一**把 CapabilityResult 变成出站形态的函数（现算调用点＝
# runtime/pipeline.py:988 一处），四条返回分支（text / chunks / mixed parts /
# mermaid mixed）都从本函数出；`build_forward_output` 只吃它的 text_fallback，
# 但转发节点自成一型嵌套（node→data→content），通用尺认不到那一层，
# 故本波在它入口也打一次（切分**之前**，改切分策略不会开出新的漏网形态）。
#
# 只打**人读文本**，绝不打部件引用字段：`file` / `url` / `content_sha256` 是
# 传输层要拿去开文件的字节定位符，`_LOCAL_PATH_RE` 一把就会把 `file:///C:/...`
# 洗成占位符 ⇒ 媒体整条发不出去（那是「为安全把功能打断」，本仓纪律是不做
# 这种交换——要拦就拦在**取值处**，见 safety_exec.paths 的落点判据）。
_OUTBOUND_TEXT_KEYS = frozenset({"text", "caption", "prompt", "alt", "title"})


def _redact_outbound_value(value: Any) -> Any:
    """部件字典里的人读文本字段逐个打码，其余键（含 file/url）原样透传。"""
    if not isinstance(value, dict):
        return value
    cleaned = dict(value)
    for key in _OUTBOUND_TEXT_KEYS:
        item = cleaned.get(key)
        if isinstance(item, str) and item:
            cleaned[key] = _redact_outbound_text(item)
    return cleaned


def _redact_rendered_content_ref(content_ref: dict[str, Any]) -> dict[str, Any]:
    """按 content_type 形态打码 content_ref：chunks 逐条、parts 逐部件、text 单条。"""
    cleaned = dict(content_ref)
    chunks = cleaned.get("chunks")
    if isinstance(chunks, list):
        cleaned["chunks"] = [
            _redact_outbound_text(chunk) if isinstance(chunk, str) else chunk
            for chunk in chunks
        ]
    parts = cleaned.get("parts")
    if isinstance(parts, list):
        cleaned["parts"] = [
            {
                **_redact_outbound_value(part),
                **(
                    {"text": _redact_outbound_text(part["text"])}
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                    else {}
                ),
            }
            if isinstance(part, dict)
            else part
            for part in parts
        ]
    text = cleaned.get("text")
    if isinstance(text, str):
        cleaned["text"] = _redact_outbound_text(text)
    return cleaned


def _redacted(rendered: RenderedOutput) -> RenderedOutput:
    """对一条已成型出站产出做统一打码（model_copy 保留 debug_id 等既成身份）。"""
    return rendered.model_copy(
        update={
            "content_ref": _redact_rendered_content_ref(rendered.content_ref),
            "text_fallback": _redact_outbound_text(rendered.text_fallback),
        }
    )

# ==================== 出站语音部件中央契约（M-19①③，Wave G/T80） ====================
# 裂缝①：type="voice" 曾在渲染层放行、在传输层被丢（OneBot record 分支只认
# record；换装 SnowLuma 后未知段类型更是整条拒发，report-T46 §2.2）⇒ 音频
# 蒸发。归一在渲染入口完成：OneBot V11 语音段标准类型就是 record，voice 是
# 能力层口误别名而非第三种语义，故规范化（而非拒绝）+warning 留痕。
# 裂缝③：audio 曾是自由袋（**audio 全键透传进 mixed 部件），可播性无表达。
# 字段冻结：file 必填（非空 str），duration/bytes 为可选可播性元数据（渲染
# 期校验类型、不上段——线上表达归传输层 record data 白名单={file}，T78）。
# 审查通道键（review_text/text 等）归 reviewer 在 CapabilityResult.audio 上
# 消费，绝不进出站段（test_reviewer_media_visibility.py 的前提由此夯实）。
_AUDIO_VOICE_ALIASES = frozenset({"record", "voice"})
_AUDIO_REVIEW_KEYS = frozenset({"review_text", "text", "content", "caption", "alt"})
_AUDIO_PLAYABILITY_KEYS = frozenset({"duration", "bytes"})
# record 族第三冻结键（S-08 / Wave H T109，蓝图 docs/design/media-digest-layer.md
# §3.2-§3.3）：能力侧合成落盘点挂的字节内容摘要——中央件
# domains/media/digest.py ``media_digest`` 产物，sha256 全长 64 hex 小写。
# 合法 → 上 part（恰三键），随行流经 worker 段级键（canonical JSON 自动纳入）、
# onebot record data 白名单={file} 天然忽略（传输层零改动）；非法 → 剥离+留痕、
# 部件保命（与 duration/bytes 同待遇）；缺省 → absent-digest 逐字节退化（恰两
# 键，T80 现状=兼容性根）。U-107-B 裁定：渲染入口不做兜底补算（零同步 IO）——
# 缺即缺，不读盘。music/file 族两键不变（无本地字节，digest 按杂键剥离）。
_AUDIO_CONTENT_DIGEST_KEY = "content_sha256"
_AUDIO_CONTENT_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def _audio_ref(value: Any) -> str:
    """部件引用字段只收非空 str（Path/None/数字一律视为缺省，防自由袋复辟）。"""
    if isinstance(value, str):
        return value.strip()
    return ""


def _is_playability_value(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def canonicalize_audio_parts(
    audio_items: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """把 ``CapabilityResult.audio`` 收口为出站 mixed 部件唯一形态。

    返回 ``(parts, anomalies)``；anomalies 非空时由调用方 warning 留痕
    （禁静默吞）。类型白名单与归一规则：

    - 缺省/``record``/``voice`` → ``{"type":"record","file":<非空str>}``；
      file 缺失=拒绝该部件（旧自由袋会造出没有 file 的空 record 段）。
    - ``music`` → ``{"type":"music","music_type":…,"music_id":…}``（点歌
      CQ:music 卡片，music.py 现行出站形态，保持不回归）。
    - ``file`` → ``{"type":"file","file":<非空str>}``（点歌 file 模式同上）。
    - 其余类型=显式拒绝+留痕（传输层本就会丢弃，蒸发面收口到渲染入口）。
    - 散键（含审查通道键与冗余 url）一律剥离；可播性键 duration/bytes 类型
      非法时剥离并留痕，部件本体不受影响。
    - ``content_sha256``（S-08/Wave H）：合法（64 hex 小写，中央件
      ``media_digest`` 产物）上 record part 第三冻结键（内容身份随行）；
      非法剥离留痕、部件保命；缺省=absent-digest 逐字节退化（恰两键）。
      渲染入口不兜底读盘补算（U-107-B，零同步 IO）。
    """
    parts: list[dict[str, Any]] = []
    anomalies: list[str] = []
    for index, item in enumerate(audio_items or []):
        if not isinstance(item, dict):
            anomalies.append(f"audio[{index}] non-dict item dropped")
            continue
        part_type = str(item.get("type") or "record").strip().lower()
        part: dict[str, Any] | None = None
        redundant = _AUDIO_REVIEW_KEYS | {"url"}
        if part_type in _AUDIO_VOICE_ALIASES:
            file_ref = _audio_ref(item.get("file"))
            if file_ref:
                if part_type != "record":
                    anomalies.append(f"audio[{index}] type=voice normalized to record")
                part = {"type": "record", "file": file_ref}
                redundant = redundant | _AUDIO_PLAYABILITY_KEYS
                if _AUDIO_CONTENT_DIGEST_KEY in item:
                    content_digest = item.get(_AUDIO_CONTENT_DIGEST_KEY)
                    digest_ok = isinstance(content_digest, str) and (
                        _AUDIO_CONTENT_DIGEST_RE.fullmatch(content_digest) is not None
                    )
                    if digest_ok:
                        part[_AUDIO_CONTENT_DIGEST_KEY] = content_digest
                    else:
                        anomalies.append(
                            f"audio[{index}] "
                            f"{_AUDIO_CONTENT_DIGEST_KEY} invalid value stripped"
                        )
                        # 已留痕即不再计 stray（单次留痕，禁双记）。
                        redundant = redundant | {_AUDIO_CONTENT_DIGEST_KEY}
            else:
                anomalies.append(f"audio[{index}] {part_type} part without file dropped")
        elif part_type == "music":
            music_type = _audio_ref(item.get("music_type"))
            music_id = _audio_ref(item.get("music_id"))
            if music_type and music_id:
                part = {
                    "type": "music",
                    "music_type": music_type,
                    "music_id": music_id,
                }
            else:
                anomalies.append(
                    f"audio[{index}] music part without music_type/music_id dropped"
                )
        elif part_type == "file":
            file_ref = _audio_ref(item.get("file")) or _audio_ref(item.get("url"))
            if file_ref:
                part = {"type": "file", "file": file_ref}
            else:
                anomalies.append(f"audio[{index}] file part without file/url dropped")
        else:
            anomalies.append(f"audio[{index}] unsupported type={part_type} dropped")
        if part is None:
            continue
        for key in _AUDIO_PLAYABILITY_KEYS:
            if key in item and not _is_playability_value(item.get(key)):
                anomalies.append(f"audio[{index}] {key} invalid value stripped")
        stray = sorted(
            key
            for key in item
            if key not in part and key not in redundant and key not in _AUDIO_PLAYABILITY_KEYS
        )
        if stray:
            anomalies.append(f"audio[{index}] stray keys stripped: {','.join(stray)}")
        parts.append(part)
    return parts, anomalies

# ==================== Mermaid 流程图（G-MERMAID） ====================
# bot 回复文本里的 ```mermaid 围栏块 → PNG 随消息发出。检测必须在
# naturalize_chat_text 之前：自然化会剥掉围栏行，之后就无法识别块了。
_MERMAID_FENCE_RE = re.compile(
    r"```[ \t]*mermaid\b[^\n]*\n(.*?)\n?[ \t]*```",
    re.IGNORECASE | re.DOTALL,
)
# 护栏：单块源码超长不渲染、单条消息最多渲染张数、整体时间预算。
MERMAID_MAX_SOURCE_CHARS = 8000
MERMAID_MAX_BLOCKS = 3
_MERMAID_PLACEHOLDER = "【流程图见下图】"
_MERMAID_CALL_TIMEOUT_S = 20.0
_MERMAID_TOTAL_BUDGET_S = 22.0

_mermaid_executor: ThreadPoolExecutor | None = None
_mermaid_executor_lock = threading.Lock()
# 审查 L-12：atexit 注册只许一次（模块级布尔防 shutdown 后重建池导致的重复
# 注册堆积；钩子读全局，一次注册覆盖此后所有池实例）。
_mermaid_shutdown_hook_registered = False


def _shutdown_mermaid_executor() -> None:
    """模块级关闭钩子（审查 L-12，与 pipeline._shutdown_chat_pool /
    error_report._shutdown_render_pool 同模式）：wait=True 且不取消排队任务
    （cancel_futures=False）——已提交的 mermaid 渲染在进程退出前跑完再收
    线程（worker 非守护态本就会被解释器隐式 join，显式回收把时序摆上台面；
    渲染自带超时预算，不会无限挂住）。"""
    global _mermaid_executor
    with _mermaid_executor_lock:
        pool, _mermaid_executor = _mermaid_executor, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=False)


def _get_mermaid_executor() -> ThreadPoolExecutor:
    """mermaid 渲染专用单线程池：playwright sync API 与事件循环互斥，
    且其浏览器实例线程绑定，固定 worker 才能跨渲染复用常驻浏览器。"""
    global _mermaid_executor, _mermaid_shutdown_hook_registered
    with _mermaid_executor_lock:
        if _mermaid_executor is None:
            _mermaid_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="mermaid-render",
            )
            if not _mermaid_shutdown_hook_registered:
                atexit.register(_shutdown_mermaid_executor)
                _mermaid_shutdown_hook_registered = True
        return _mermaid_executor


def _render_mermaid_png(code: str) -> bytes | None:
    """渲染一块 mermaid 源码为 PNG 字节；失败/超时返回 None，绝不抛异常。

    实际渲染在专用线程执行（render_reviewed_output 可能被 handle_async
    直接调在事件循环线程上，playwright sync API 在那里会拒绝启动）。
    """
    try:
        from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
            render_mermaid_png,
        )
    except Exception:  # noqa: BLE001 - 桥接不可用按渲染失败降级。
        return None
    try:
        future = _get_mermaid_executor().submit(render_mermaid_png, code)
        return future.result(timeout=_MERMAID_CALL_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - 超时/线程异常一律按渲染失败降级。
        return None


def find_mermaid_blocks(text: str) -> list[re.Match[str]]:
    """找出文本里所有 ```mermaid 围栏块（含开闭围栏整段）。"""
    if not text:
        return []
    try:
        return list(_MERMAID_FENCE_RE.finditer(text))
    except Exception:  # noqa: BLE001 - 正则异常时按无块处理。
        return []


def _naturalize_keeping_edges(segment: str) -> str:
    """自然化分段但保留两端换行，保证占位/围栏始终独立成行。"""
    if not segment.strip():
        return segment
    stripped = segment.strip("\n")
    if not stripped:
        return segment
    lead = segment[: len(segment) - len(segment.lstrip("\n"))]
    trail = segment[len(segment.rstrip("\n")) :]
    return lead + naturalize_chat_text(stripped) + trail


def apply_mermaid_blocks(
    text: str,
    *,
    is_chat: bool,
) -> tuple[str, list[dict]]:
    """把 ```mermaid 围栏块替换为一行占位并产出 PNG 图片部件（G-MERMAID）。

    返回 (新文本, 阅读顺序交错的 text/image 部件)。护栏：单块源码
    >8000 字符不渲染；单条消息最多渲染前 3 块；渲染总耗时超预算后
    其余块保留文本。渲染失败/无网的块原样保留代码文本——绝不丢内容、
    绝不抛异常；一张都没渲染成功时返回原文本与空列表（调用方继续走
    既有纯文本管线，行为与未挂钩完全一致）。
    """
    try:
        return _apply_mermaid_blocks_inner(text, is_chat=is_chat)
    except Exception:  # noqa: BLE001 - mermaid 挂钩绝不阻断出站管线。
        return text, []


def _apply_mermaid_blocks_inner(
    text: str,
    *,
    is_chat: bool,
) -> tuple[str, list[dict]]:
    matches = find_mermaid_blocks(text)
    if not matches:
        return text, []
    # 先渲染再动文本：全部失败时对文本零改动，保持既有管线逐字节一致。
    deadline = time.monotonic() + _MERMAID_TOTAL_BUDGET_S
    rendered: list[bytes | None] = []
    success_count = 0
    for match in matches:
        source = match.group(1).replace("\r\n", "\n").strip("\n")
        if (
            success_count >= MERMAID_MAX_BLOCKS
            or len(source) > MERMAID_MAX_SOURCE_CHARS
            or time.monotonic() >= deadline
        ):
            rendered.append(None)
            continue
        png = _render_mermaid_png(source)
        rendered.append(png)
        if png:
            success_count += 1
    if not any(rendered):
        return text, []
    ordered: list[dict] = []
    new_text_chunks: list[str] = []
    cursor = 0
    for match, png in zip(matches, rendered):
        before = text[cursor : match.start()]
        if is_chat:
            before = _naturalize_keeping_edges(before)
        chunk = before + (
            _MERMAID_PLACEHOLDER if png else text[match.start() : match.end()]
        )
        new_text_chunks.append(chunk)
        if chunk:
            ordered.append({"type": "text", "text": chunk})
        if png:
            ordered.append(
                {
                    "type": "image",
                    "file": "base64://" + base64.b64encode(png).decode("ascii"),
                }
            )
        cursor = match.end()
    tail = text[cursor:]
    if is_chat:
        tail = _naturalize_keeping_edges(tail)
    if tail:
        new_text_chunks.append(tail)
        ordered.append({"type": "text", "text": tail})
    return "".join(new_text_chunks), ordered


def render_reviewed_output(
    result: CapabilityResult,
    review: ReviewResult,
) -> RenderedOutput:
    """出站咽喉：能力产出 → 出站形态，**四条返回分支一律过统一打码**。

    打码收在包装层而不是逐分支插，是为了让「以后多加一条返回分支」这件事
    不可能悄悄绕过咽喉——分支少了会红（存量用例），分支多了不脱管。
    """
    return _redacted(_render_reviewed_output_inner(result, review))


def _render_reviewed_output_inner(
    result: CapabilityResult,
    review: ReviewResult,
) -> RenderedOutput:
    text = review.safe_text or result.body or result.summary or result.title
    is_chat = result.capability_id == "bot.chat"
    # G-MERMAID：检测/渲染先于自然化（naturalize 会剥掉围栏行导致无法
    # 识别块）；没有任何块渲染成功时返回原文本，行为与未挂钩完全一致。
    mermaid_text, mermaid_parts = apply_mermaid_blocks(text, is_chat=is_chat)
    if mermaid_parts:
        text = mermaid_text
    elif is_chat:
        text = naturalize_chat_text(text)
    # 能力层声明的图片/语音直链在审核通过后原样透传（内容来自平台
    # 官方接口，不是用户输入）；transport 不支持时按 text_fallback 降级。
    media_parts: list[dict] = []
    # 前置部件（戳一戳 v2 群聊 @ 段等）：无论正文形态如何都拼在最前；
    # 仅有 prefix而无媒体时也走 mixed（at+text），text_fallback 诚实降级丢 @。
    leading_parts: list[dict] = [
        part for part in (result.prefix_parts or []) if isinstance(part, dict)
    ]
    for image in result.images or []:
        if not isinstance(image, dict):
            continue
        # 贴纸路由（Task B 接线，2026-09-29）：能力层在 images 条目上打
        # ``kind="sticker"`` ⇒ 部件类型标成 ``sticker``，onebot 出站腿据此走
        # ``_sticker_segment``（原生 mface 优先、image 兜底）；没打 kind 的
        # 仍是普通 ``image`` 部件——/随机图 等照片通路逐字节不变。
        # 贴纸条目允许只带 ``emoji_id`` 不带文件（原生表情回投无需再传图），
        # 三样都没有才是空载荷，照旧丢弃不出站。
        if str(image.get("kind") or "").strip().lower() == "sticker":
            if (
                image.get("file")
                or image.get("url")
                or str(image.get("emoji_id") or "").strip()
            ):
                media_parts.append({"type": "sticker", **image})
            continue
        if image.get("file") or image.get("url"):
            media_parts.append({"type": "image", **image})
    # M-19①③：audio 出站唯一形态收口（voice→record 归一/散键剥离/拒绝留痕）。
    audio_parts, audio_anomalies = canonicalize_audio_parts(result.audio)
    if audio_anomalies:
        logger.warning(
            "renderer audio contract applied request_id=%s anomalies=%s",
            result.request_id,
            audio_anomalies,
        )
    media_parts.extend(audio_parts)
    for video in result.video or []:
        if isinstance(video, dict) and (video.get("file") or video.get("url")):
            media_parts.append({"type": "video", **video})
    for file_item in result.files or []:
        if isinstance(file_item, dict) and (file_item.get("file") or file_item.get("url")):
            media_parts.append({"type": "file", **file_item})
    if not media_parts and not mermaid_parts and result.text_parts and len(result.text_parts) > 1:
        chunks = [str(part).strip() for part in result.text_parts if str(part).strip()]
        if is_chat:
            chunks = [clean for part in chunks if (clean := naturalize_chat_text(part))]
        if chunks:
            return RenderedOutput(
                request_id=result.request_id,
                content_type="chunks",
                content_ref={"chunks": chunks},
                text_fallback="\n\n".join(chunks),
                size_estimate=sum(len(chunk) for chunk in chunks),
                risk_level=review.risk_level,
                privacy_level=review.privacy_level,
            )
    if mermaid_parts:
        # 流程图已渲染：mermaid_parts 是阅读顺序交错的 text/image 部件
        # （占位行与配图相邻）；能力层自带媒体仍排在最前（与既有 mixed
        # 形态一致，聊天回复通常没有 media_parts）。text_fallback 保留
        # 占位后的全文，transport 不支持图片时按文本降级不丢内容。
        parts = [*media_parts, *mermaid_parts]
        return RenderedOutput(
            request_id=result.request_id,
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback=text,
            size_estimate=len(text),
            risk_level=review.risk_level,
            privacy_level=review.privacy_level,
        )
    if leading_parts or media_parts:
        parts = [*leading_parts, *media_parts]
        if text.strip():
            parts.append({"type": "text", "text": text})
        return RenderedOutput(
            request_id=result.request_id,
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback=text,
            size_estimate=len(text),
            risk_level=review.risk_level,
            privacy_level=review.privacy_level,
        )
    return RenderedOutput(
        request_id=result.request_id,
        content_type="text",
        content_ref={"text": text},
        text_fallback=text,
        size_estimate=len(text),
        risk_level=review.risk_level,
        privacy_level=review.privacy_level,
    )


def _safe_break_index(paragraph: str, limit: int) -> int:
    """优先在句末标点/空白处断行，避免把颜文字从中间切开。"""
    if limit <= 0:
        return 0
    break_chars = "。！？…~!?；;，, 　	"
    for index in range(limit - 1, max(0, limit - 40), -1):
        if paragraph[index] in break_chars:
            return index + 1
    return limit


def split_text_chunks(
    text: str,
    *,
    node_chars: int = 900,
    max_nodes: int = 0,
) -> list[str]:
    """按段落把长文本切成合并转发节点，超长段落优先在标点处断开。"""
    normalized = (text or "").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in normalized.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            if current:
                chunks.append(current)
                current = ""
            continue
        while len(paragraph) > node_chars:
            if current:
                chunks.append(current)
                current = ""
            break_at = _safe_break_index(paragraph, node_chars)
            chunks.append(paragraph[:break_at])
            paragraph = paragraph[break_at:]
        if current and len(current) + len(paragraph) + 1 > node_chars:
            chunks.append(current)
            current = paragraph
            continue
        current = paragraph if not current else f"{current}\n{paragraph}"
    if current:
        chunks.append(current)
    # 0/负数表示不人为限制转发节点数；只有 node_chars 作为传输硬长度边界。
    if max_nodes > 0:
        while len(chunks) > max_nodes:
            overflow = chunks.pop()
            merged = f"{chunks[-1]}\n{overflow}" if chunks else overflow
            if chunks:
                chunks[-1] = merged
            else:
                chunks.append(merged)
        # 溢出反复合并会突破 node_chars 硬边界：对尾块按边界二次切分，
        # 代价是块数可能临时超过 max_nodes（硬长度边界优先于节点数上限）。
        tail = chunks[-1]
        if len(tail) > node_chars:
            chunks[-1:] = [
                tail[index : index + node_chars]
                for index in range(0, len(tail), node_chars)
            ]
    return chunks


def build_forward_output(
    request_id: str,
    text: str,
    *,
    node_chars: int = 900,
    max_nodes: int = 0,
    sender_name: str = "",
    risk_level: RiskLevel = RiskLevel.LOW,
    privacy_level: PrivacyLevel = PrivacyLevel.PUBLIC,
) -> RenderedOutput:
    """把超长文本渲染成合并转发消息（OneBot node 格式），带文本兜底。

    如果 transport 不支持 forward，会按 ``text_fallback`` 降级。

    入站文本先过统一打码：转发节点由这段文本切出来，节点里的 `data.text`
    形态与本函数的切分策略强耦合（`_redact_rendered_content_ref` 认的是
    chunks/parts/text 三种通用形态，不认 node 嵌套）。在**切分之前**打一次，
    比在切分之后逐节点补一遍更稳——以后改切分策略不会开出新的漏网形态。
    幂等：经 `render_reviewed_output` 的正常链路是第二次过，零二次伤害。
    """
    text = _redact_outbound_text(text)
    chunks = split_text_chunks(text, node_chars=node_chars, max_nodes=max_nodes)
    nodes = [
        {
            "type": "node",
            "data": {
                "name": sender_name or "消息",
                "uin": "0",
                "content": [{"type": "text", "data": {"text": chunk}}],
            },
        }
        for chunk in chunks
    ]
    return RenderedOutput(
        request_id=request_id,
        content_type="forward",
        content_ref={"messages": nodes},
        text_fallback=text,
        size_estimate=len(text),
        risk_level=risk_level,
        privacy_level=privacy_level,
    )


def should_forward_long_text(
    text: str,
    *,
    min_chars: int = 1500,
) -> bool:
    """min_chars<=0 表示不按字数拆转发。"""
    if min_chars <= 0:
        return False
    return bool(text) and len(text.strip()) >= max(1, min_chars)


def should_forward_by_node_count(
    text: str,
    *,
    node_chars: int = 900,
    min_nodes: int = 4,
    max_nodes: int = 0,
) -> bool:
    """按**条数**判断是否合并转发：切分后条数达到 min_nodes 即合并。

    用户口径："需要发送的消息 > 3 条（不含 3 条）就合并转发"，即切分后
    **≥4 条**才合并。min_nodes<=0 表示该规则关闭。
    比按字数判断更贴近真实体验：4 条以上刷屏时收进一条合并转发，3 条以内照常直发。
    """
    if min_nodes <= 0 or not text:
        return False
    chunks = split_text_chunks(text, node_chars=node_chars, max_nodes=max_nodes)
    return len(chunks) >= min_nodes
