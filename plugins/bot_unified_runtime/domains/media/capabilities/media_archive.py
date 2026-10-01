"""媒体归档能力（bot.media_archive）：发媒体+指令 → VLM 分析 → 类别×IP 分类落盘。

产品裁定（2026-09-13，用户四答）：
- 指令形态：同条消息（媒体+指令）与回复媒体消息发指令，两种都支持（回复媒体
  由 handler 层 enrich 注入 ``reply_media_segments``/``chat_record_text``）。
- 落盘：类别 × IP（作品来源）双层目录——cosplay/二次元插图等按内容归类，
  IP 判不出落「未识别」；指令可显式覆盖（分类=/IP=/角色=），管理员可加 子路径=。
- 视频：轻量抽帧（ffmpeg 复用 vision_describe 的抽帧器），不做 ASR 转写。
- 权限：``bot_media_archive_min_role`` 默认 super_admin（归档落到本机磁盘），
  配置改 user 即放开全员（配额/冷却照常）。

安全护栏：SSRF（check_download_url）+ magic bytes 质检 + 单文件/每日限额 +
sha256 幂等去重 + 目录名消毒（防穿越）。VLM 关闭/失败 → 按媒体类型降级归类
并在回执诚实标注「未分析」。
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
    check_download_url,
)
from plugins.bot_unified_runtime.domains.media.archive.media_archive import (
    CATEGORIES,
    FALLBACK_CATEGORY_BY_TYPE,
    UNKNOWN_IP,
    ArchiveReservedNameError,
    MediaArchiveStore,
    sanitize_dirname,
)
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

# 触发词（T-Spec 八层裁剪）：CJK 词天然词界安全；英文 archive 语义独占；
# 全拼 shoucang/guidang。save 裸词会劫持英文口语（"save me"）——刻意不收。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "收藏",
    "归档",
    "存图",
    "收图",
    "存聊天记录",
    "存记录",
    "archive",
    "shoucang",
    "guidang",
)

_ROLE_RANK: dict[str, int] = {
    "user": 0,
    "trusted": 1,
    "enterprise": 2,
    "admin": 3,
    "super_admin": 4,
}

_MEDIA_SEGMENT_TYPES = frozenset({"image", "photo", "sticker", "mface", "animation"})
_GIF_SEGMENT_TYPES = frozenset({"animation"})
_VIDEO_SEGMENT_TYPES = frozenset({"video", "video_note"})

_ARCHIVE_PROMPT = (
    "你是媒体归档助手。分析用户发来的媒体（图片/动图/视频关键帧），"
    "只返回一个 JSON 对象，不要任何多余文字：\n"
    '{"category": "cosplay|二次元插图|表情包|截图|照片|风景|人物|动图 之一",\n'
    ' "ip_source": "作品来源（游戏/动画/漫画名或画师名；判不出写 未识别）",\n'
    ' "character": "角色名，判不出写空字符串",\n'
    ' "description": "不超过20字的画面描述",\n'
    ' "tags": ["标签1", "标签2"],\n'
    ' "nsfw_score": 0.0}\n'
    "规则：真人角色扮演照归 cosplay 并在 ip_source 写角色所属作品；二次元插画/"
    "漫画彩页归 二次元插图；游戏或应用画面归 截图；真人随手拍归 照片；"
    "表情包/梗图归 表情包。ip_source 优先写具体作品名（如 原神/鸣潮/碧蓝航线）。"
)

_ARG_RE = re.compile(
    r"(?P<key>分类|category|ip|IP|作品|角色|character|子路径|subpath)[=：]\s*(?P<value>\S+)"
)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShoreKeeperBot/1.0"

logger = logging.getLogger(__name__)


# 词尾边界字（Wave G T66 收编）：判定循环上收 domains/core/text_boundary.py
# 的 is_trigger，本文件只剩取值登记。逐字节=现行手抄串（比 TRIGGER 少 　\t、
# 比 PARTICLE 少 哦嘛咯哇；「=」参数边界经 extra_boundary_chars 显式组合——
# 统一加宽属行为变更，本波不做，diff 见
# .superpowers/sdd/2026-09-19-unify-audit/report-T66.md 披露表）。
_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈～~"


def is_media_archive_command(
    text: str, trigger_words: list[str] | tuple[str, ...] | None = None
) -> bool:
    """触发词判定：整句等于触发词，或触发词后跟标点/空白/参数边界。

    与 randpic 同哲学的保守边界：避免「收藏夹」「归档表」类包含词误触发；
    触发词后允许直接跟 分类=/IP= 参数。换行先归一为空格——「收藏\\n分类=x」
    是最自然的多行输入形态（评审 I-3）。判定逻辑收编中央件（Wave G T66）：
    换行归一/裸词/现行字符集经显式传参逐字节保持。
    """
    triggers = tuple(trigger_words) if trigger_words else DEFAULT_TRIGGER_WORDS
    return is_trigger(
        text,
        triggers,
        case_insensitive=False,
        bare_word=True,
        newline_as_space=True,
        boundary_chars=_BOUNDARY_CHARS,
        extra_boundary_chars="=",
    )


def parse_archive_args(text: str) -> dict[str, str]:
    """解析指令参数：分类=/IP=/作品=/角色=/子路径=（值取到空白为止）。"""
    args: dict[str, str] = {}
    for match in _ARG_RE.finditer(text or ""):
        key = match.group("key").strip().lower()
        value = match.group("value").strip().strip('"「」')
        if not value:
            continue
        if key in ("分类", "category"):
            args["category"] = value
        elif key in ("ip", "作品"):
            args["ip"] = value
        elif key in ("角色", "character"):
            args["character"] = value
        elif key in ("子路径", "subpath"):
            args["subpath"] = value
    return args


def _role_at_least(sender_roles: list[str], min_role: str) -> bool:
    required = _ROLE_RANK.get(str(min_role).strip().lower(), 4)
    return max((_ROLE_RANK.get(role, -1) for role in sender_roles), default=-1) >= required


def _extract_archive_items(
    raw_segments: list[dict[str, Any]],
    reply_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从消息段与回复注入段提取待归档媒体项。

    返回 ``{"kind": "image"|"gif"|"video", "url": str, "path": str}``；
    image/gif 共用图片下载链，动画段（animation）判为 gif。
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment in [*raw_segments, *reply_segments]:
        if not isinstance(segment, dict):
            continue
        seg_type = str(segment.get("type", "")).lower()
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        url = str(data.get("url") or "").strip()
        local = str(data.get("file") or data.get("path") or "").strip()
        if local.startswith("file://"):
            local = local.removeprefix("file://")
        if seg_type in _VIDEO_SEGMENT_TYPES and (url or local):
            key = f"video:{url or local}"
            if key not in seen:
                seen.add(key)
                items.append({"kind": "video", "url": url, "path": local})
            continue
        if seg_type in _MEDIA_SEGMENT_TYPES and (url or local):
            kind = "gif" if seg_type in _GIF_SEGMENT_TYPES else "image"
            key = f"{kind}:{url or local}"
            if key not in seen:
                seen.add(key)
                items.append({"kind": kind, "url": url, "path": local})
    return items


def _read_local_media(path_text: str, max_bytes: int) -> bytes | None:
    path = Path(path_text)
    # 防御纵深（评审 M-3）：段内路径只收绝对路径（SnowLuma 供给形态），
    # 相对路径会相对进程 CWD 解析，一律拒收。
    if not path.is_absolute() or not path.is_file():
        return None
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_bytes()
    except OSError:
        return None


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向逐跳复查 SSRF（评审 I-1）：urlopen 默认自动跟随 30x，
    重定向目标若指向内网/元数据地址必须就地拒绝。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_download_url(str(newurl))
        except RejectedUrlError as exc:
            # 审查 F-06：拒绝信号在抛出点留痕（重定向目标才是真实攻击面，
            # 原始 URL 看不出这一跳）；URL 形态过既有脱敏再进日志。
            # 异常继续上抛，由 _fetch_url_media 的捕获点收口为跳过该条。
            logger.warning(
                "media archive SSRF guard rejected redirect: %s (url=%s)",
                exc,
                redact_local_secrets(str(newurl)),
            )
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_GuardedRedirectHandler())


def _fetch_url_media(url: str, max_bytes: int) -> bytes | None:
    """bot 侧下载媒体字节：SSRF 护栏（含重定向逐跳）+ 大小上限（超限即拒）。"""
    try:
        check_download_url(url)
    except RejectedUrlError as exc:
        # 审查 F-06：入口拒绝同样 WARNING 留痕（脱敏后 URL 形态），
        # 随后按「取不到内容」处理，不中断同批其余条目。
        logger.warning(
            "media archive SSRF guard rejected url: %s (url=%s)",
            exc,
            redact_local_secrets(url),
        )
        return None
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with _OPENER.open(request, timeout=20.0) as response:
            if not response.readable():
                return None
            # 攻击审计 A-4：截断不得谎报——读限额+1 字节探边，探满即超限，
            # 回 None 走既有「没能取到内容（…超限…）」拒绝分支：不写文件、
            # 不留截断件（截断件的 sha256/去重/回执也都失真）。旧形态
            # ``read(max_bytes + 1)[:max_bytes]`` 把「超限即断」实现成了
            # 「截断不拒」并照常回「✔ 已归档」。反向语义：恰好 max_bytes
            # 的合法文件原样收，不收紧。
            data = response.read(max_bytes + 1)
            if len(data) >= max_bytes + 1:
                return None
            return data
    except (OSError, ValueError, http.client.HTTPException, RejectedUrlError):
        # 审查 F-06：重定向逐跳复查抛出的 RejectedUrlError 继承 Exception
        # 而非 OSError，不补进元组就会从 open() 逃逸本函数、炸掉调用方的
        # 整批循环——一票坏重定向拖垮全部待归档条目。此处的拒绝已在
        # _GuardedRedirectHandler 抛出点记过 WARNING，不再重复留痕。
        return None


def _acquire_bytes(item: dict[str, Any], max_bytes: int) -> bytes | None:
    if item.get("path"):
        data = _read_local_media(str(item["path"]), max_bytes)
        if data:
            return data
    if item.get("url"):
        return _fetch_url_media(str(item["url"]), max_bytes)
    return None


def _parse_vlm_json(text: str) -> dict[str, Any] | None:
    match = _JSON_OBJ_RE.search(text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _analyze_media(
    provider: Any,
    *,
    kind: str,
    data: bytes,
    video_frames: int,
    vision_timeout: float,
) -> dict[str, Any] | None:
    """VLM 分类分析：图片直发 / 视频抽帧；任何失败返回 None（调用方降级）。"""
    if provider is None:
        return None
    content: list[dict[str, Any]] = [{"type": "text", "text": "归档这张媒体。"}]
    if kind == "video":
        # 局部导入：复用 vision_describe 的 ffmpeg 抽帧与编码器（同包内部件）。
        import tempfile

        from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
            _encode_image_bytes,
            _extract_video_frames,
        )

        frame_dir = tempfile.mkdtemp(prefix="bot_archive_frames_")
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(data)
            tmp_video = handle.name
        try:
            frame_paths = _extract_video_frames(
                tmp_video, max(1, int(video_frames)), frame_dir, vision_timeout
            )
        except Exception:  # noqa: BLE001 - 抽帧失败按降级处理。
            return None
        finally:
            try:
                Path(tmp_video).unlink(missing_ok=True)
            except OSError:
                pass
            # 帧目录整树清理（评审 M-2）：只删临时视频会把抽出的帧留在 tmp。
            shutil.rmtree(frame_dir, ignore_errors=True)
        if not frame_paths:
            return None
        for frame in frame_paths[: max(1, int(video_frames))]:
            try:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _encode_image_bytes(frame.read_bytes(), "image/jpeg")},
                    }
                )
            except OSError:
                continue
    else:
        from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
            _image_bytes_to_data_url,
        )

        data_url = _image_bytes_to_data_url(data)
        if not data_url:
            return None
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    messages = [
        {"role": "system", "content": _ARCHIVE_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        reply = provider.generate(messages, temperature=0.1, max_tokens=300)
    except Exception:  # noqa: BLE001 - VLM 失败一律降级，不阻断归档。
        return None
    return _parse_vlm_json(str(getattr(reply, "text", "") or ""))


def _summarize_text(provider: Any, text: str) -> str:
    """聊天记录归档的一句话摘要；失败返回空串（纯文本归档不受影响）。"""
    if provider is None or not text.strip():
        return ""
    messages = [
        {
            "role": "system",
            "content": "把聊天记录概括成一句话（不超过30字），直接输出，不要前言。",
        },
        {"role": "user", "content": text[:3000]},
    ]
    try:
        reply = provider.generate(messages, temperature=0.2, max_tokens=80)
    except Exception:  # noqa: BLE001 - 摘要失败静默。
        return ""
    return str(getattr(reply, "text", "") or "").strip()[:80]


def build_media_archive_capability(
    config: Any | None = None,
    *,
    vision_provider: Any = None,
    store: MediaArchiveStore | None = None,
) -> Any:
    """构建媒体归档能力；store/vision_provider 可注入（测试）或按 config 构建。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        enabled = getattr(config, "bot_media_archive_enabled", True)
        text = message.plain_text or ""
        if not enabled or not is_media_archive_command(text):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.media_archive",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["media_archive", "skip_no_trigger"],
            )
        if not _role_at_least(list(message.sender_roles), str(getattr(config, "bot_media_archive_min_role", "super_admin"))):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.media_archive",
                kind="text",
                title="媒体归档",
                # 审查 Q-02：去卖萌语气、自称统一第三人称；超管门槛语义特殊
                # （写「管理员」会失实），豁免不入管理员门禁池（登记见 user_copy.py）。
                body="这个归档功能暂时只对超管开放，这份心意守岸人先记下了。",
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=["media_archive", "denied_role"],
            )

        archive_store = store or MediaArchiveStore(
            getattr(config, "bot_media_archive_db_path", "data/media_archive.sqlite3"),
            getattr(config, "bot_media_archive_dir", "data/media_archive"),
        )
        max_bytes = int(getattr(config, "bot_media_archive_max_file_mb", 100)) * 1024 * 1024
        daily_limit = int(getattr(config, "bot_media_archive_daily_limit", 50))
        per_message_limit = int(getattr(config, "bot_media_archive_per_message_limit", 4))
        args = parse_archive_args(text)
        roles = list(message.sender_roles)
        is_admin = _role_at_least(roles, "admin")

        lines: list[str] = []
        audit: list[str] = ["media_archive"]

        # ---- 聊天记录分支：只信 handler enrich 注入的转写文本（评审 M-1）----
        # 【合并转发内容】标记仅在 chat 链路注入，本路由的 plain_text 里出现
        # 该标记只可能是用户手打伪造；同条消息的转发由 enrich 反查补齐。
        record_text = str(getattr(message, "chat_record_text", "") or "")[:200000]
        if record_text:
            remaining = daily_limit - archive_store.count_today()
            if remaining <= 0:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.media_archive",
                    kind="text",
                    title="媒体归档",
                    body=f"今天已经归档 {daily_limit} 件了，额度用完啦，明天再来吧。",
                    send_policy=SendPolicy.IMMEDIATE,
                    audit_tags=[*audit, "quota_exhausted"],
                )
            summary = ""
            if getattr(config, "bot_media_archive_summary_enabled", True):
                summary = _summarize_text(vision_provider, record_text)
            body_text = f"# 聊天记录归档\n\n- 归档时间：{message.timestamp:%Y-%m-%d %H:%M}\n- 会话：{message.session_id}\n"
            if summary:
                body_text += f"- 一句话：{summary}\n"
            body_text += f"\n---\n\n{record_text}\n"
            record, _chat_target, _dup = archive_store.save_text(
                body_text,
                record_kwargs={
                    "platform": message.platform,
                    "session_id": message.session_id,
                    "sender_id": message.sender_id,
                    "description": summary or "聊天记录归档",
                },
            )
            lines.append(f"✔ 聊天记录 → {record.rel_path}" + (f"\n  一句话：{summary}" if summary else ""))
            audit.append("chat_saved")
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.media_archive",
                kind="text",
                title="媒体归档",
                body="\n".join(lines),
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=audit,
            )

        # ---- 媒体分支：图片/动图/视频 ----
        items = _extract_archive_items(
            list(message.raw_segments), list(getattr(message, "reply_media_segments", []) or [])
        )
        if not items:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.media_archive",
                kind="text",
                title="媒体归档",
                # 审查 Q-03 扩展：失败类文案（no_media 分支）统一去拖尾语气符
                # 「～」，句号收尾——守岸人语气温和但不拖尾音（同 meme_library
                # 64efadf 口径；相邻额度用尽分支本就句号收尾）。
                body=(
                    "把要归档的图片/动图/视频和「收藏」放在同一条消息发给我，"
                    "或者回复那条媒体说「收藏」就行。聊天记录就回复它说「存聊天记录」。"
                ),
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=[*audit, "no_media"],
            )

        remaining = daily_limit - archive_store.count_today()
        if remaining <= 0:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.media_archive",
                kind="text",
                title="媒体归档",
                body=f"今天已经归档 {daily_limit} 件了，额度用完啦，明天再来吧。",
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=[*audit, "quota_exhausted"],
            )
        budget = min(remaining, per_message_limit, len(items))

        video_frames = int(getattr(config, "bot_media_archive_video_frames", 5))
        vision_timeout = float(getattr(config, "bot_vision_timeout_seconds", 20.0))
        saved = 0
        for item in items[:budget]:
            kind = str(item["kind"])
            data = _acquire_bytes(item, max_bytes)
            if data is None:
                lines.append(f"× 有一件{kind}没能取到内容（链接失效/超限/内网地址已拦），跳过了。")
                audit.append(f"skip_{kind}")
                continue
            analysis = _analyze_media(
                vision_provider,
                kind=kind,
                data=data,
                video_frames=video_frames,
                vision_timeout=vision_timeout,
            )
            if analysis:
                category = str(analysis.get("category") or "").strip()
                category = category if category in CATEGORIES else FALLBACK_CATEGORY_BY_TYPE.get(kind, "照片")
                ip_source = str(analysis.get("ip_source") or "").strip() or UNKNOWN_IP
                character = str(analysis.get("character") or "").strip()
                description = str(analysis.get("description") or "").strip()
                tags = [str(t).strip() for t in (analysis.get("tags") or []) if str(t).strip()][:6]
                nsfw = float(analysis.get("nsfw_score") or 0.0)
                analyzed = True
            else:
                category = FALLBACK_CATEGORY_BY_TYPE.get(kind, "照片")
                ip_source = UNKNOWN_IP
                character = ""
                description = ""
                tags = []
                nsfw = 0.0
                analyzed = False
            # 指令显式覆盖 VLM 判定（用户意图最优先）。消毒与落盘同护栏：
            # 覆盖参数/VLM 产出/管理员子路径里的保留设备名都在此格收口
            # （sanitize_dirname 抛错点全部在 try 内，不逃逸炸整批）。
            try:
                if args.get("category"):
                    category = sanitize_dirname(args["category"], fallback=category)
                if args.get("ip"):
                    ip_source = sanitize_dirname(args["ip"], fallback=UNKNOWN_IP)
                if args.get("character"):
                    character = args["character"]
                subpath = ""
                if args.get("subpath") and is_admin:
                    subpath = sanitize_dirname(args["subpath"], fallback="")
                record, _target, duplicated = archive_store.save(
                    data,
                    media_type=kind,
                    category=category,
                    ip_source=ip_source,
                    subpath=subpath,
                    record_kwargs={
                        "character_name": character,
                        "description": description,
                        "tags": tags,
                        "nsfw_score": nsfw,
                        "original_name": Path(str(item.get("path") or item.get("url") or "")).name[:120],
                        "platform": message.platform,
                        "session_id": message.session_id,
                        "sender_id": message.sender_id,
                    },
                )
            except ArchiveReservedNameError as exc:
                # 攻击审计 A-1：目录段名撞 Win32 保留设备名——拒走失败面，
                # 理由出自中央人话表（含「保留设备名」字样），不洗名近似、
                # 不写文件；本分支必须排在通用 ValueError 之前（它是子类）。
                lines.append(f"× 有一件媒体没能落盘（{exc}）跳过了。")
                audit.append(f"skip_reserved_name_{kind}")
                continue
            except (ValueError, OSError):
                # ValueError=格式不识别（unsupported_media_type/保留名已由上方
                # 专支点名）；OSError=磁盘异常（评审 M-4）。
                lines.append("× 有一件媒体没能落盘（格式未识别或写入失败），跳过了。")
                audit.append(f"skip_format_{kind}")
                continue
            if duplicated:
                lines.append(f"↺ 这件已经归档过啦（{record.rel_path}），没有重复保存。")
                audit.append("dedup")
                continue
            note = f"｜{description}" if description else ""
            flag = "" if analyzed else "（VLM 未分析，按类型归类）"
            lines.append(f"✔ {record.category}/{record.ip_source} → {record.rel_path}{note}{flag}")
            saved += 1
            audit.append(f"saved_{kind}")

        if not lines:
            body = "这次没能归档任何内容……检查一下媒体还能不能打开？"
        else:
            body = "\n".join(lines)
            if saved:
                body += f"\n今天已归档 {archive_store.count_today()}/{daily_limit} 件。"
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.media_archive",
            kind="text",
            title="媒体归档",
            body=body,
            send_policy=SendPolicy.IMMEDIATE,
            audit_tags=audit,
        )

    return capability
