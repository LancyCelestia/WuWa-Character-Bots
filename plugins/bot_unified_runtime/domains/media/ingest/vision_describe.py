"""图片/表情包/视频识别（VLM）：角色识别 + 文字转写 + 画面简述。

聊天链路在消息携带图片（image/mface 段，QQ 与 Telegram 通用）或视频（video 段）
时调用本模块，把媒体内容转成紧凑的文字描述注入当前消息上下文，让人格模型
"看懂"媒体再回应。

图片来源优先级：SnowLuma 落盘的本机路径（file:// 或绝对路径，直读字节转
base64 data URL）→ http URL 原样透传。NTQQ 的签名 URL 对部分境外 VLM
不可达且会过期，本机字节是最可靠来源。GIF 动图取首帧重编为 JPEG（主流
OpenAI 兼容接口不收 image/gif）；超大图经 PIL 缩到 2048px JPEG，控制在
VLM 的 base64 体积上限内。

识别模型来自 ``BOT_VISION_MODEL_REGISTRY``（OpenAI 兼容多模态接口），支持两种
写法：``id -> 条目``（单模型）与 ``id -> [条目, ...]``（一个供应商挂多个模型，
按条目内 priority 轮询）。运行时注册表（``/bot model vision add ...``）合并于
其上且即时生效；调用失败按优先级转移到下一个候选（最多 3 个）。未启用或未
配置时整条链路零开销跳过，识别失败不阻断聊天。
"""

from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
    LLMReply,
    OpenAICompatibleLLMProvider,
)
from plugins.bot_unified_runtime.domains.media.ingest.image_pixel_budget import (
    ensure_pixel_budget,
)

logger = logging.getLogger(__name__)

_VISION_SYSTEM_PROMPT = (
    "你是图片识别器，为聊天机器人解读用户发来的图片、表情包或照片。"
    "严格按以下三行格式输出，不要输出任何其他内容：\n"
    "角色：<角色名（出处作品名）>；出自真人影视或现实照片则写“非动漫游戏角色”。"
    "无法确定时写“不确定”，并在同行给出最可能的候选与判断依据\n"
    "文字：<逐字转写图中出现的全部文字，保持原文不翻译不改写；没有文字写“无”>\n"
    "画面：<一句话描述画面内容与情绪>"
)
_VIDEO_SYSTEM_PROMPT = (
    "你是视频内容识别器，为聊天机器人解读用户发来的视频（已按时间顺序抽帧）。"
    "严格按以下三行格式输出，不要输出任何其他内容：\n"
    "内容：<一两句话概括视频主体与发生了什么>\n"
    "文字：<画面/字幕中出现的关键文字，逐字转写；没有写“无”>\n"
    "细节：<值得回应的显著细节、动作或情绪>"
)
# 图片段类型：OneBot 用 image/mface；Telegram 用 photo；动图/贴纸按"可看的图"处理
# （此前缺 animation/sticker/photo，Telegram 侧这些一律只剩占位文本，评审需求 4）。
# ⚠ `video_note` 不在本族：它的落盘容器恒为 mp4（`telegram_media.py:61` 兜底后缀），
# PIL 打不开 ⇒ 走图片族时两条支路皆空、零日志（2026-09-23 席位 S7 实跑坐实），
# 归视频族才有下游可接。`animation` 两可（gif 形态图片路有效、mp4 形态同样瞎），
# 一次只改一个语义面，mp4 animation 单列挂账。
#
# 图片族内部再按「能不能整包原生交给模型」分三组（2026-09-23 用户多模态矩阵裁定）：
# 纯图片任何视觉渠道都原生；**表情包与动图只有被声明 `native-animation` 的渠道才原生**，
# 其余渠道必须先经 VLM 转成文字。依据不是推测而是实跑：grok-4.6 的网关对 `image_url`
# 里的 gif 直接 400（`Downloaded response does not contain a valid JPG, PNG, WebP, or
# ICO image`），即动图对它根本不可原生；而 gemini 收到 gif 时 HTTP 200。
_PHOTO_SEGMENT_TYPES = {"image", "photo"}
# ⚠ 组里必须带 `emoji`：QQ 侧 `face`/`mface`/`marketface` 在归一层
# （`domains/chat_reply/ingest/message_context.py:53-56`）就被改写成 `{"type":"emoji"}`，
# 而 `raw_segments` 存的就是归一后的段——只写 mface 等于给 QQ 表情包留了个空列
# （2026-09-23 席位 S26 实跑揭穿，此前测试夹具手写 `mface` 把它锁成绿）。
_STICKER_SEGMENT_TYPES = {"mface", "face", "marketface", "sticker", "emoji"}
_ANIMATION_SEGMENT_TYPES = {"animation"}
_IMAGE_SEGMENT_TYPES = (
    _PHOTO_SEGMENT_TYPES | _STICKER_SEGMENT_TYPES | _ANIMATION_SEGMENT_TYPES
)
# 组名 → 段类型集合：调用方按组取数，禁在调用点重抄段类型字面量（第二真身）。
IMAGE_GROUPS: dict[str, set[str]] = {
    "photo": _PHOTO_SEGMENT_TYPES,
    "sticker": _STICKER_SEGMENT_TYPES,
    "animation": _ANIMATION_SEGMENT_TYPES,
}
DEFAULT_IMAGE_GROUPS: tuple[str, ...] = ("photo", "sticker", "animation")

def split_animated_segments(
    raw_segments: list[dict[str, Any]] | None,
    *,
    groups: tuple[str, ...] = DEFAULT_IMAGE_GROUPS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按容器把图片段分成 (动画, 静态) 两堆——两堆都是原段的子集，顺序稳定。

    调用方据此决定"哪堆可以原样进模型、哪堆必须先转译"，判据与 `requires_native_animation`
    同源，不在任何调用点复制后缀表。
    """
    wanted: set[str] = set()
    for name in groups:
        wanted |= set(IMAGE_GROUPS.get(str(name), ()))
    animated: list[dict[str, Any]] = []
    static: list[dict[str, Any]] = []
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in wanted:
            continue
        data = segment.get("data")
        data = data if isinstance(data, dict) else {}
        refs = [data.get(key) for key in ("url", "file", "path")]
        bucket = animated if any(requires_native_animation(ref) for ref in refs) else static
        bucket.append(segment)
    return animated, static


_VIDEO_SEGMENT_TYPES = {"video", "video_note"}
_DEFAULT_MAX_IMAGES = 2
_DEFAULT_MAX_CHARS = 500
_MAX_VISION_FAILOVER_ATTEMPTS = 3
# base64 后约 4.8MB，主流 OpenAI 兼容 VLM（含 GLM-4V 5MB 限制）均可收。
_MAX_DIRECT_IMAGE_BYTES = 3_500_000
# 本地图输入上限：与远程图上限同口径（2026-09-18 用户裁定「图片大小放宽到
# 25MB」）。超过上限不再尝试转 data URL/PIL 重编，直接走既有降级（跳过该图）。
# 内存安全说明：本路径只有 ≤ _MAX_DIRECT_IMAGE_BYTES 时才 path.read_bytes()，
# 更大文件一律交给 _pil_normalize（PIL 惰性打开 + thumbnail，JPEG 走 draft
# 缩放），不会把 25MB 原始位图整读进内存。
_MAX_LOCAL_IMAGE_INPUT_BYTES = 25_000_000
_PIL_MAX_SIDE = 2048
_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
# 动图的字面容器后缀。此前 "gif" 在盘上有三处独立拼写（本模块的 `.gif` 判定、
# 本模块的 `image/gif` 字面量、路由器裁件的 `data:image/gif`），改一处即让裁件
# 静默瞎掉而两侧各自仍绿（评审席 S32 贰-2）。后缀真身收在本模块，路由器只读判据。
_GIF_SUFFIX = ".gif"
_GIF_MIME = "image/gif"


def _animation_container_suffixes() -> frozenset[str]:
    """动图族容器后缀：gif + **全部**已登记的视频容器。

    视频容器不在这里重抄——真身是 `video_understanding._VIDEO_SUFFIX_MIME`，
    惰性 import 而非模块级：那个模块本来就 import 本模块，模块级互引会成环。
    """
    from plugins.bot_unified_runtime.domains.media.ingest.video_understanding import (
        _VIDEO_SUFFIX_MIME,
    )

    return frozenset({_GIF_SUFFIX}) | frozenset(_VIDEO_SUFFIX_MIME)


def requires_native_animation(url: object) -> bool:
    """这个图片源属不属于"渠道没声明 `native-animation` 就不能原样发"的动图族。

    判据真身只在此处：装配门按**段组**（`IMAGE_GROUPS` 的 sticker+animation）
    决定挂不挂，裁件按**载荷形态**决定裁不裁，两边若各写一张容器表就是第二真身
    （评审席 S32 贰-2 复现的那副差集：`animation` 段的 http URL 被原样透传成
    `.mp4`，只认 gif 的裁件看不见它 ⇒ 未声明动画的一跳照旧收到必败请求）。

    - data URL：容器写在 MIME 里。本模块只产 `_SUFFIX_MIME` 登记过的静态图与
      gif 原字节，故"不在静态图表里"即动图族（`data:video/…` 同理），无需新表。
    - http/裸路径：按路径尾判定（查询串/片段里出现后缀不算）。**认不出的后缀
      不算动图**——QQ 图片签名 URL 常无扩展名，退化成"未知即动图"会把纯照片一起
      从非声明那一跳上裁掉（那是误伤，不是收窄）。
    """
    text = str(url or "").strip()
    if not text:
        return False
    head = text.split(";", 1)[0].strip().lower()
    if head.startswith("data:"):
        return head[len("data:") :].strip() not in set(_SUFFIX_MIME.values())
    path = text.split("?", 1)[0].split("#", 1)[0].strip().lower()
    return any(path.endswith(suffix) for suffix in _animation_container_suffixes())



def _local_path_from_value(value: str) -> Path | None:
    """file:// 前缀或本机绝对路径 → 已存在的文件；其余（含裸文件名）返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file:"):
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
        if not path:
            return None
        candidate = Path(path)
        # Windows 上 file:///C:/x 解析出 /C:/x，需剥掉盘符前的斜杠。
        if candidate.drive == "" and re.match(r"^/[A-Za-z]:[/\\]", path):
            candidate = Path(path[1:])
    else:
        if "://" in text:
            return None
        candidate = Path(text)
    try:
        if candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def _encode_image_bytes(data: bytes, mime: str) -> str:
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def _pil_normalize(path: Path, *, first_frame_only: bool) -> str | None:
    """经 PIL 重编图片：GIF 取首帧转 PNG，超大图缩边转 JPEG；失败返回 None。"""

    try:
        from PIL import Image

        with Image.open(path) as image:
            return _pil_normalize_image(image, first_frame_only=first_frame_only)
    except Exception:
        logger.debug("vision_describe fail-open guard", exc_info=True)
        return None


def _pil_normalize_image(image: Any, *, first_frame_only: bool) -> str | None:
    """PIL 重编的 Image 对象核心（供本机路径与远程字节两路复用）。

    攻击者复查 F-V-1（2026-09-27 席位 S-FIX-VISBOMB）：≤25MB 的 PNG 可在文件头
    声明上亿像素（解压炸弹），而旧顺序 ``convert()`` 先于 ``thumbnail()`` 意味着
    全分辨率解码已经发生——闸必须在任何 load/convert 之前施加。超限图**拒绝**并
    走既有诚实失败面（返回 None=按无图降级），不静默缩放巨图。降采样改在**未
    load 的原图上**进行（JPEG 走 draft、块解码缩放），兑现模块头部 :122 的内存
    安全注释原意。判据真身在 image_pixel_budget 单源，此处不写阈值。
    """
    from io import BytesIO

    try:
        ensure_pixel_budget(image)
        if first_frame_only:
            image.seek(0)
        if max(image.size) > _PIL_MAX_SIDE:
            image.thumbnail((_PIL_MAX_SIDE, _PIL_MAX_SIDE))
        frame = image.convert("RGB")
        buffer = BytesIO()
        frame.save(buffer, format="JPEG", quality=85)
    except Exception:
        logger.debug("vision_describe fail-open guard", exc_info=True)
        return None
    return _encode_image_bytes(buffer.getvalue(), "image/jpeg")


def _gif_filmstrip_data_url(path: Path) -> str | None:
    """动图抽 ≤3 帧拼成横向长条（单图预算内表达运动过程）；失败返回 None。"""

    try:
        from PIL import Image

        with Image.open(path) as image:
            return _gif_strip_from_image(image)
    except Exception:
        logger.debug("vision_describe fail-open guard", exc_info=True)
        return None


def _gif_strip_from_image(image: Any) -> str | None:
    """动图拼条的 Image 对象核心（供本机路径与远程字节两路复用）。

    F-V-1 同族：逐帧 ``convert()`` 会全分辨率驻留（帧尺寸=逻辑屏），故对基帧一次
    像素预算闸、超限即拒（GIF 各帧不超逻辑屏，单闸覆盖全族）；拼条峰值=3 帧×
    预算内驻留，较旧面的无界窗口（PIL 默认 1x–2x 告警带照常解码）已收敛。
    """
    from io import BytesIO

    try:
        from PIL import Image

        ensure_pixel_budget(image)
        frame_count = int(getattr(image, "n_frames", 1) or 1)
        if frame_count <= 1:
            return _pil_normalize_image(image, first_frame_only=True)
        picks = sorted({
            min(frame_count - 1, round(index * (frame_count - 1) / 2))
            for index in range(3)
        })
        tiles: list = []
        for frame_index in picks:
            image.seek(frame_index)
            tile = image.convert("RGB")
            tile.thumbnail((512, 256))
            tiles.append(tile)
        height = min(tile.height for tile in tiles)
        tiles = [
            tile.resize((max(1, round(tile.width * height / tile.height)), height))
            for tile in tiles
        ]
        strip = Image.new(
            "RGB",
            (sum(tile.width for tile in tiles) + 4 * (len(tiles) - 1), height),
            (255, 255, 255),
        )
        offset = 0
        for tile in tiles:
            strip.paste(tile, (offset, 0))
            offset += tile.width + 4
        buffer = BytesIO()
        strip.save(buffer, format="JPEG", quality=85)
    except Exception:
        logger.debug("vision_describe fail-open guard", exc_info=True)
        return None
    return _encode_image_bytes(buffer.getvalue(), "image/jpeg")


def _image_file_to_data_url(
    file_ref: str, *, keep_animation_raw: bool = False
) -> str | None:
    """本机图片文件 → data URL；GIF 取首帧，超大/未知格式经 PIL 重编。

    ``keep_animation_raw``：gif 不再拼静态条，原字节直发。动图本身就是帧序列，
    PIL 再拼一次是**二次有损**（时序与帧数全丢，模型只看见并排的四格）。
    超过 ``_MAX_DIRECT_IMAGE_BYTES`` 仍回退拼条——宁可读不到"它在动"，
    也不发一发必败的请求体。
    """
    path = _local_path_from_value(file_ref)
    if path is None:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > _MAX_LOCAL_IMAGE_INPUT_BYTES:
        logger.debug(
            "vision: local image too large for data url bytes=%s name=%s",
            size,
            path.name,
        )
        return None
    suffix = path.suffix.lower()
    if suffix == _GIF_SUFFIX:
        if keep_animation_raw:
            try:
                raw = path.read_bytes()
            except OSError:
                raw = b""
            if raw and len(raw) <= _MAX_DIRECT_IMAGE_BYTES:
                return _encode_image_bytes(raw, _GIF_MIME)
        return _gif_filmstrip_data_url(path) or _pil_normalize(
            path, first_frame_only=True
        )
    try:
        if size <= _MAX_DIRECT_IMAGE_BYTES and suffix in _SUFFIX_MIME:
            return _encode_image_bytes(path.read_bytes(), _SUFFIX_MIME[suffix])
    except OSError:
        return None
    return _pil_normalize(path, first_frame_only=False)


# ---------- 远程图片 bot 侧转 data URL（直传与 OCR 双分支共用） ----------
# QQ 多媒体签名 URL（multimedia.nt.qq.com.cn / gchat.qpic.cn）对第三方 AI
# 服务商不可达：直传分支原样透传 URL 时模型侧取不到图，OCR 分支同样依赖
# 服务商侧抓取——两条分支一起瞎。必须 bot 侧先下载转 data URL 再进请求体。

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_MAX_REMOTE_IMAGE_BYTES = 25_000_000
_REMOTE_DOWNLOAD_TIMEOUT = 25.0
# 2026-09-18 大图读取修复：手机高分辨率照片常见 5-15MB，旧上限 8MB/超时 10s
# 造成「大图读不了、小图正常」。上限两度放宽——8MB→20MB→25MB（后者为
# 2026-09-18 用户裁定「图片大小放宽到25MB」）。PIL 会先缩边 2048 再编码，
# 实际进 VLM 的 data URL 仍 <5MB；超时 25s 保持不变（QQ 多媒体服务器大图
# 下载偏慢，10s 常超时降级）。
# FIFO 缓存：同一张图多轮追问/双分支复用不重复下载。
_REMOTE_DATA_URL_CACHE: dict[str, str] = {}
_REMOTE_DATA_URL_CACHE_ORDER: list[str] = []
_REMOTE_DATA_URL_CACHE_CAP = 32


def _guarded_image_opener() -> urllib.request.OpenerDirector:
    """取图护栏 opener（攻击者复查 F-1，2026-09-27 席位 S-ATKFIX-SSRF1）。

    urlopen 默认 opener 自动跟随 30x、逐跳落点零复查：图片 URL 一跳指进
    内网/云元数据时，内网字节会经 PIL → data URL → VLM 描述回显给群成员。
    这里复用短链链上唯一的逐跳护栏形态 ``_GuardedShortLinkRedirectHandler``
    （每一跳落点先过 ssrf_guard.check_fetch_landing，判据仍是中央
    ``check_download_url``——不造第二套 URL 判据）：命中内网/整型 IP/畸形
    落点即在建连之前抛 ParseHttpError，「落点拒绝即弃图」与
    ``media_archive._fetch_url_media`` 同口径；跨 host 剥凭证的
    ``_CredentialScrubbingRedirectHandler`` 语义随之继承。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _GuardedShortLinkRedirectHandler,
    )

    return urllib.request.build_opener(_GuardedShortLinkRedirectHandler())


def _download_image_bytes(
    url: str,
    *,
    max_bytes: int = _MAX_REMOTE_IMAGE_BYTES,
) -> bytes | None:
    """远程取图字节。判据口径（WP1 背景点4 + 攻击者复查 F-1/F-2）：

    - 入口先过中央咽喉 ``check_download_url``（内网/保留段/畸形一律拒）。
      **明确拒绝不再吞成 None，而是原样上抛**——调用方据此区分「咽喉
      拒绝」与「瞬时失败」（审查 F-2：拒绝=丢图不回透，瞬时失败=保留
      原 URL 兜底）。
    - 30x 重定向走 ``_guarded_image_opener`` 逐跳落点复查（审查 F-1），
      落点拒绝抛 ParseHttpError，同样上抛。
    - 返回 None 只发生在「公网判定成立但瞬时下载失败/超限/读失败」。
    """
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        ParseHttpError,
    )

    check_download_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": _DESKTOP_UA})
    host = urlparse(url).hostname or ""
    try:
        with _guarded_image_opener().open(
            request, timeout=_REMOTE_DOWNLOAD_TIMEOUT
        ) as response:
            payload = response.read(max_bytes + 1)
    except (RejectedUrlError, ParseHttpError):
        # SSRF 护栏拒绝（入口咽喉 / 逐跳落点）是透明信号——绝不降级成
        # 「瞬时失败」返回 None，否则调用方会把内网 URL 原样回透给 provider。
        raise
    except Exception as exc:  # noqa: BLE001 - 下载失败要给上游统一降级语义，warning 已带上下文。
        logger.warning(
            "vision: remote image download failed host=%s err=%s", host, exc
        )
        return None
    if len(payload) > max_bytes:
        logger.warning(
            "vision: remote image too large bytes=%s host=%s", len(payload), host
        )
        return None
    return payload


def _image_bytes_to_data_url(data: bytes) -> str | None:
    """图片字节 → data URL：GIF/动图抽帧条，其余缩边 JPEG；失败返回 None。"""
    from io import BytesIO

    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            if (image.format or "").lower() == "gif":
                strip = _gif_strip_from_image(image)
                if strip:
                    return strip
                return _pil_normalize_image(image, first_frame_only=True)
            return _pil_normalize_image(image, first_frame_only=False)
    except Exception:
        logger.debug("vision_describe fail-open guard", exc_info=True)
        return None


def prepare_vision_image_urls(
    urls: list[str],
    *,
    limit: int = _DEFAULT_MAX_IMAGES,
) -> list[str]:
    """把远程 http 图片 URL 转成 data URL（bot 侧下载）；本地/data URL 原样。

    审查 F-2（2026-09-27 席位 S-ATKFIX-SSRF1）——拒绝分支 fail-closed：
    SSRF 咽喉**明确拒绝**的 URL（入口 ``RejectedUrlError`` / 重定向落点
    ``ParseHttpError``，判据仍为中央 check_download_url）一律**丢该图不回透**——
    本机构架的 VLM provider 若自取 image_url，透传原内网 URL 等于让它替我们
    连内网。仅「公网判定成立但瞬时下载失败」（``_download_image_bytes`` 返回
    None）保留原 URL 兜底（个别服务商侧或许能取到），并已在下载腿留 warning。
    拒绝原因文案不含 URL 形态（咽喉固定文案），日志只记「丢图」不回显地址。
    """
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
    )
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        ParseHttpError,
    )

    prepared: list[str] = []
    for url in (urls or [])[: max(1, limit)]:
        if not url.startswith("http"):
            prepared.append(url)
            continue
        cached = _REMOTE_DATA_URL_CACHE.get(url)
        if cached:
            prepared.append(cached)
            continue
        try:
            data = _download_image_bytes(url)
        except (RejectedUrlError, ParseHttpError):
            logger.warning("vision: image dropped by SSRF guard, not forwarded to provider")
            continue
        converted = _image_bytes_to_data_url(data) if data else None
        if converted is None:
            prepared.append(url)
            continue
        _REMOTE_DATA_URL_CACHE[url] = converted
        _REMOTE_DATA_URL_CACHE_ORDER.append(url)
        while len(_REMOTE_DATA_URL_CACHE_ORDER) > _REMOTE_DATA_URL_CACHE_CAP:
            evicted = _REMOTE_DATA_URL_CACHE_ORDER.pop(0)
            _REMOTE_DATA_URL_CACHE.pop(evicted, None)
        prepared.append(converted)
    return prepared


def extract_image_urls(
    raw_segments: list[dict[str, Any]] | None,
    *,
    groups: tuple[str, ...] = DEFAULT_IMAGE_GROUPS,
    keep_animation_raw: bool = False,
) -> list[str]:
    """从消息原始段提取图片源：本机路径（file://、绝对路径）转 data URL，http URL 透传。

    image 与 mface（QQ 表情包）都算；GIF 取首帧。解析不了的段静默跳过。

    ``groups`` 只取 ``IMAGE_GROUPS`` 的组名（缺省三组全取=旧行为逐字节不变）：
    调用方按「这张图能不能原样给模型」选组，段类型字面量不留第二份副本。
    ``keep_animation_raw`` 见 `_image_file_to_data_url`。
    """
    wanted: set[str] = set()
    for name in groups:
        types = IMAGE_GROUPS.get(str(name))
        if types:
            wanted |= set(types)
    urls: list[str] = []
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in wanted:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        candidates = [
            str(data.get(key) or "").strip() for key in ("url", "file", "path")
        ]
        if not any(candidates):
            # mface/表情商城段常见无 url 形态：图拿不到是"读不到图"类报障的
            # 高频来源，留 debug 观测点（ SnowLuma 侧字段变化时此处最先显形）。
            logger.debug(
                "vision: %s segment without url/file/path keys=%s",
                segment.get("type"),
                sorted(data.keys()),
            )
            continue
        local_url = ""
        http_url = ""
        for candidate in candidates:
            if not candidate:
                continue
            if candidate.startswith("http") and not http_url:
                http_url = candidate
                continue
            if not local_url:
                local_url = (
                    _image_file_to_data_url(
                        candidate, keep_animation_raw=keep_animation_raw
                    )
                    or ""
                )
        resolved = local_url or http_url
        if resolved and resolved not in urls:
            urls.append(resolved)
    return urls


def extract_video_source(raw_segments: list[dict[str, Any]] | None) -> str | None:
    """取第一个可解析的视频段来源：本机路径优先，其次 http URL。"""
    for segment in raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _VIDEO_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        for key in ("url", "file", "path"):
            value = str(data.get(key) or "").strip()
            if not value:
                continue
            if value.startswith("http"):
                return value
            local = _local_path_from_value(value)
            if local is not None:
                return str(local)
        # video 段存在但三键全空：视频理解静默失效的高频来源，留观测点。
        logger.debug(
            "vision: video segment without resolvable source keys=%s",
            sorted(data.keys()),
        )
    return None


def _find_ffmpeg_locate() -> str:
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        _find_ffmpeg,
    )

    return _find_ffmpeg()


def _http_input_opts(source: str) -> list[str]:
    """http 视频源加桌面 UA（QQ 视频直链对 ffmpeg 默认 UA 返回 403，实测）。"""
    if str(source or "").startswith("http"):
        return ["-user_agent", _DESKTOP_UA]
    return []


def _probe_video_duration(ffmpeg: str, source: str, timeout_seconds: float) -> float:
    """用 ffmpeg -i 的 stderr 解析时长；解析失败返回 0（调用方给默认窗口）。"""
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", *_http_input_opts(source), "-i", source],
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0.0
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        result.stderr.decode("utf-8", errors="replace"),
    )
    if not match:
        return 0.0
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _extract_video_frames(
    video_source: str,
    count: int,
    out_dir: str,
    timeout_seconds: float = 30.0,
) -> list[Path]:
    """ffmpeg 均匀抽帧落盘为 JPEG；ffmpeg 缺失或失败返回空列表。

    攻击者复查残余收口（2026-09-27 席位 S-ATKFIX-SSRF2）：http 源由 ffmpeg
    自带网络栈自取、绕开 Python 咽喉（与 yt-dlp F-5 同类）。在把源交给 ffmpeg
    （含 ``_probe_video_duration``）之前，先过**中央唯一判据** ``check_download_url``
    ——明确拒绝即按「无帧」降级返回 ``[]``（与 ffmpeg 缺失同口径），绝不把内网
    地址下发给 ffmpeg；本机文件路径不受影响。ffmpeg 自身跟随的重定向落点属
    连接级残余（同 F-5/F-8），登记不堵（见席位报告）。
    """
    source = str(video_source or "")
    if source.startswith(("http://", "https://")):
        from plugins.bot_unified_runtime.domains.files.sources.downloader import (
            RejectedUrlError,
            check_download_url,
        )

        try:
            check_download_url(source)
        except RejectedUrlError:
            logger.warning("vision: video frame source rejected by SSRF guard")
            return []
    ffmpeg = _find_ffmpeg_locate()
    if not ffmpeg:
        logger.info("video frames skipped: ffmpeg not found")
        return []
    duration = _probe_video_duration(ffmpeg, video_source, timeout_seconds)
    # 时长未知时按 10s 窗口抽帧，保证短视频仍然均匀、长视频至少覆盖开头。
    fps = count / (duration if duration > 0 else 10.0)
    command = [
        ffmpeg,
        "-nostdin",
        "-y",
        *_http_input_opts(video_source),
        "-i",
        video_source,
        "-vf",
        f"fps={fps:.5f},scale=854:-2",
        "-frames:v",
        str(count),
        "-qscale:v",
        "3",
        str(Path(out_dir) / "frame_%03d.jpg"),
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("video frame extraction failed type=%s", type(exc).__name__)
        return []
    return sorted(Path(out_dir).glob("frame_*.jpg"))[:count]


def _flatten_vision_entries(
    registry: Any,
    *,
    resolve_key: bool = False,
    config: object = None,
) -> dict[str, dict[str, Any]]:
    """把注册表统一展平成 id -> 条目；id 支持单条目或条目列表。

    列表形态按 ``id#序号`` 展开；resolve_key 时把 env: 引用解析成真实密钥。
    """
    # 2026-09-29 席 S-FIX-SHIM-REFS：旧布局垫片 `llm/model_router` ⇒ 改指真身（`_resolve_api_key`
    # 真身 :652 在册）；账见 `domains/core/board_shim_ledger.py` SHIM_ROWS。
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.model_router import (
        _resolve_api_key,
    )

    flattened: dict[str, dict[str, Any]] = {}
    if not isinstance(registry, dict):
        return flattened
    for group_id, value in registry.items():
        group = str(group_id)
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            model = str(item.get("model", "")).strip()
            base_url = str(item.get("base_url", "")).strip()
            if not model or not base_url:
                continue
            entry_id = f"{group}#{index}" if isinstance(value, list) else group
            entry = dict(item)
            if resolve_key:
                entry["api_key"] = _resolve_api_key(
                    str(entry.get("api_key", "")), config
                )
            flattened[entry_id] = entry
    return flattened


class DynamicVisionProvider:
    """视觉模型动态提供器：env 注册表 + 运行时注册表合并，按优先级故障转移。"""

    def __init__(
        self,
        config: object,
        *,
        dynamic_registry: Any = None,
        settings_store: Any = None,
    ) -> None:
        self._config = config
        self._dynamic_registry = dynamic_registry
        self._settings_store = settings_store
        self._providers: dict[tuple[str, str, str], Any] = {}
        self.last_attempts: list[str] = []

    def is_enabled(self) -> bool:
        if self._settings_store is not None:
            try:
                return bool(
                    self._settings_store.get_or(
                        "BOT_VISION_ENABLED",
                        bool(getattr(self._config, "bot_vision_enabled", False)),
                    )
                )
            except (KeyError, OSError, TypeError, ValueError):  # 开关读取失败回退 .env 值。
                logger.debug("vision enabled flag read failed; falling back to env")
        return bool(getattr(self._config, "bot_vision_enabled", False))

    def _merged_entries(self) -> dict[str, dict[str, Any]]:
        merged = _flatten_vision_entries(
            getattr(self._config, "bot_vision_model_registry", None),
            resolve_key=True,
            config=self._config,
        )
        if self._dynamic_registry is not None:
            try:
                dynamic = self._dynamic_registry() or {}
            except Exception:
                logger.debug("vision_describe fail-open guard", exc_info=True)
                dynamic = {}
            merged.update(
                _flatten_vision_entries(dynamic, resolve_key=True, config=self._config)
            )
        return merged

    def _provider_for(self, entry_id: str, entry: dict[str, Any]) -> Any | None:
        api_key = str(entry.get("api_key", "")).strip()
        model = str(entry.get("model", "")).strip()
        base_url = str(entry.get("base_url", "")).strip()
        if not api_key or not model or not base_url:
            return None
        fingerprint = (model, base_url, api_key)
        if fingerprint not in self._providers:
            self._providers[fingerprint] = OpenAICompatibleLLMProvider(
                api_key=api_key,
                model=model,
                base_url=base_url,
                proxy=str(getattr(self._config, "bot_download_proxy", "") or ""),
                timeout_seconds=float(
                    getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
                ),
            )
        return self._providers[fingerprint]

    def _caption_cache(self) -> Any | None:
        """取图片描述缓存实例（每次现读 config，支持「空串=关闭」的即时语义）。

        真身＝``domains/media/registry/vision_caption_cache.py``。这里只调用、不
        实现任何哈希或建表逻辑——内容身份的算法咽喉在 ``domains/media/digest.py``
        （``tests/test_media_identity_single_source_ratchet.py`` 执法，禁第二份）。
        任何异常按「没有缓存」处理：识图绝不能因为缓存坏了而读不到图。
        """
        try:
            from plugins.bot_unified_runtime.domains.media.registry import (
                vision_caption_cache,
            )

            return vision_caption_cache.build_vision_caption_cache(self._config)
        except Exception:
            logger.debug("vision caption cache unavailable", exc_info=True)
            return None

    def generate(self, messages: list[dict[str, Any]], **kwargs: object) -> Any:
        self.last_attempts = []
        # 描述缓存腿（MM-VIS-1，2026-09-29）：同一批图第二次进来直接复用上一次的
        # 描述，省掉一次真实 VLM 账单。键由**图片内容**推导（不是 URL、不是问题），
        # 取不到字节就没有键＝照常调用，行为与改动前逐字节一致。
        cache = self._caption_cache()
        cache_key = ""
        if cache is not None:
            try:
                from plugins.bot_unified_runtime.domains.media.registry import (
                    vision_caption_cache,
                )

                cache_key = vision_caption_cache.caption_key_for_messages(messages)
            except Exception:
                logger.debug("vision_describe fail-open guard", exc_info=True)
                cache_key = ""
        if cache_key and cache is not None:
            cached = cache.lookup(cache_key)
            if cached:
                self.last_attempts.append("vision_caption_cache:hit")
                logger.info(
                    "vision describe vision_cache_hit=1 key=%s", cache_key[:16]
                )
                return LLMReply(
                    text=cached,
                    provider="vision_caption_cache",
                    model="vision_caption_cache",
                )
        candidates = sorted(
            self._merged_entries().items(),
            key=lambda kv: (
                kv[1].get("priority", 100)
                if isinstance(kv[1].get("priority", 100), int)
                else 100,
                kv[0],
            ),
        )
        started = time.monotonic()
        deadline = float(
            getattr(self._config, "bot_vision_timeout_seconds", 20.0) or 20.0
        ) * 2
        last_error: LLMProviderError | None = None
        for entry_id, entry in candidates[:_MAX_VISION_FAILOVER_ATTEMPTS]:
            if last_error is not None and (time.monotonic() - started) > deadline:
                self.last_attempts.append("vision:deadline")
                break
            provider = self._provider_for(entry_id, entry)
            if provider is None:
                last_error = LLMProviderError(
                    f"vision model {entry_id} is missing key/model/base_url",
                    error_kind="config_missing",
                )
                self.last_attempts.append(f"{entry_id}:config_missing")
                continue
            try:
                reply = provider.generate(messages, **kwargs)
            except LLMProviderError as exc:
                last_error = exc
                self.last_attempts.append(f"{entry_id}:{exc.error_kind}")
                continue
            except Exception as exc:
                logger.debug("vision_describe fail-open guard", exc_info=True)
                last_error = LLMProviderError(
                    f"vision model {entry_id} failed: {type(exc).__name__}",
                    error_kind="provider_error",
                )
                self.last_attempts.append(f"{entry_id}:provider_error")
                continue
            self.last_attempts.append(f"{entry_id}:success")
            if cache_key and cache is not None:
                # 只存真拿到了文字的这一次：空回复不建条目，否则下一次命中一份
                # 空白描述，等于把"没看清"缓存成永久事实。
                cache.put(
                    cache_key,
                    str(getattr(reply, "text", "") or "").strip(),
                    str(getattr(reply, "model", "") or entry_id),
                )
            return reply
        if last_error is not None:
            raise last_error
        raise LLMProviderError(
            "no vision model available",
            error_kind="provider_not_configured",
        )


def build_vision_provider(
    config: object,
    *,
    dynamic_registry: Any = None,
    settings_store: Any = None,
) -> DynamicVisionProvider | None:
    """组装动态视觉 provider；注册表完全为空时返回 None（零开销跳过）。

    开关（BOT_VISION_ENABLED）在每次调用时读取，支持运行时热切换。
    """
    has_env = bool(_flatten_vision_entries(
        getattr(config, "bot_vision_model_registry", None)
    ))
    has_dynamic = False
    if dynamic_registry is not None:
        try:
            has_dynamic = bool(_flatten_vision_entries(dynamic_registry() or {}))
        except Exception:
            logger.debug("vision_describe fail-open guard", exc_info=True)
            has_dynamic = False
    if not has_env and not has_dynamic:
        return None
    return DynamicVisionProvider(
        config,
        dynamic_registry=dynamic_registry,
        settings_store=settings_store,
    )


def _clip(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1]}…"


def describe_images_with_status(
    provider: Any,
    *,
    image_urls: list[str],
    query_text: str = "",
    max_images: int = _DEFAULT_MAX_IMAGES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> tuple[str, str]:
    """识别图片并**如实报告这一趟属于哪一类结果**：`(文本, kind)`。

    治的账（审计缺陷 5）：旧口只回字符串，「没开识别」「本轮没图」「模型挂了」
    三件事在调用方眼里长得一模一样（都是空串），于是失败全静默——用户发一张
    糊图追问三遍，bot 一句"没看清"都没有，看起来像装看不见。

    ``kind`` 四值（判据就这三条，别再细分出第二套口径）：
    - ``"disabled"``：没有 provider（识别整件没开）——**不是失败**，不该道歉；
    - ``"empty"``：本轮没有图，或模型回了个空文本——同上，不道歉；
    - ``"failed"``：有图、且这一趟真的没读成（护栏把图全丢了 / provider 抛错）
      ——只有这一类值得给用户一句人话。
    - ``"ok"``：拿到描述文本。

    诚实边界：本函数只报"这一腿的结果类别"，不重试、不改调用链、也不决定
    要不要道歉（那是调用方的事），所以既有只关心文本的消费点可以照旧用
    ``describe_images``（它就是本函数的文本投影）。
    """
    if provider is None:
        return "", "disabled"
    if not image_urls:
        return "", "empty"
    limit = max(1, int(max_images))
    # QQ 多媒体签名 URL 服务商侧取不到：bot 侧先下载转 data URL（见 §14.6.4）。
    image_urls = prepare_vision_image_urls(list(image_urls), limit=limit)
    if not image_urls:
        # 审查 F-2 连锁：全部图被护栏丢弃（入口/落点拒绝）时没有图可描述，
        # 直接返回空——不发「用户附带了图片」却无图可看的空跑请求误导模型。
        # 类别＝failed：用户那边是真发了图的，只是我们一张都没能读成。
        return "", "failed"
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "用户附带了图片。用户随图消息："
                f"{_clip(query_text, 200) or '（无文字）'}"
            ),
        }
    ]
    for url in image_urls[:limit]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]
    try:
        reply = provider.generate(messages, temperature=0.1, max_tokens=400)
    except LLMProviderError as exc:
        logger.warning(
            "vision describe failed kind=%s attempts=%s",
            exc.error_kind,
            getattr(provider, "last_attempts", []),
        )
        return "", "failed"
    except Exception:
        logger.exception("vision describe failed")
        return "", "failed"
    text = str(getattr(reply, "text", "") or "").strip()
    if not text:
        return "", "empty"
    return _clip(text, max(80, int(max_chars))), "ok"


def describe_images(
    provider: Any,
    *,
    image_urls: list[str],
    query_text: str = "",
    max_images: int = _DEFAULT_MAX_IMAGES,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """调用视觉模型输出紧凑识别结果；任何失败返回空串，绝不阻断主回复。

    文本投影口（既有签名与调用点零改动）。需要区分"失败/没开/没图"的调用方
    直接用 ``describe_images_with_status``，别在这里再猜一次。
    """
    text, _kind = describe_images_with_status(
        provider,
        image_urls=image_urls,
        query_text=query_text,
        max_images=max_images,
        max_chars=max_chars,
    )
    return text


def describe_video(
    provider: Any,
    *,
    video_source: str,
    query_text: str = "",
    frames: int = 4,
    max_chars: int = _DEFAULT_MAX_CHARS,
    timeout_seconds: float = 30.0,
) -> str:
    """视频抽帧 → 单次 VLM 调用输出紧凑摘要；任何失败返回空串，绝不阻断主回复。"""
    if provider is None or not video_source:
        return ""
    frame_dir = tempfile.mkdtemp(prefix="bot_video_frames_")
    try:
        frame_paths = _extract_video_frames(
            video_source,
            max(1, int(frames)),
            frame_dir,
            timeout_seconds,
        )
        if not frame_paths:
            return ""
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "用户附带了一个视频（以下为按时间顺序抽取的关键帧）。"
                    f"用户随视频消息：{_clip(query_text, 200) or '（无文字）'}"
                ),
            }
        ]
        for frame in frame_paths:
            try:
                data = frame.read_bytes()
            except OSError:
                continue
            content.append(
                {"type": "image_url", "image_url": {"url": _encode_image_bytes(data, "image/jpeg")}}
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _VIDEO_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            reply = provider.generate(messages, temperature=0.1, max_tokens=500)
        except LLMProviderError as exc:
            logger.warning(
                "vision video describe failed kind=%s attempts=%s",
                exc.error_kind,
                getattr(provider, "last_attempts", []),
            )
            return ""
        except Exception:  # 识别失败不阻断聊天。
            logger.exception("vision video describe failed")
            return ""
        text = str(getattr(reply, "text", "") or "").strip()
        if not text:
            return ""
        return _clip(text, max(80, int(max_chars)))
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


def describe_subscription_item(
    provider: Any,
    payload: dict[str, Any],
    *,
    max_images: int = 1,
    max_chars: int = 200,
) -> str:
    """订阅推送的 vision 增强：无文本条目补一行图片描述；任何失败返回空串。

    调用方负责按 BOT_VISION_ENABLED 等开关决定是否传入 provider。
    """
    if provider is None or not isinstance(payload, dict):
        return ""
    urls: list[str] = []
    for media in payload.get("media") or []:
        if isinstance(media, dict):
            url = str(media.get("preview_image_url") or media.get("url") or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        for key in ("cover", "image", "thumbnail"):
            url = str(payload.get(key) or "")
            if url.startswith("http"):
                urls.append(url)
    if not urls:
        return ""
    # SUB-4 腿1（S-ATK-SUBSCRIBE，2026-09-27）：远端标题以 query_text 身份直进
    # 视觉模型 prompt，且旧名单里没有订阅链路——改走二手消毒单一真身
    # `guard_secondhand_text`（全角化+成对边界+定性引导），禁手拼包裹字面量。
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        guard_secondhand_text,
    )

    guarded_title = guard_secondhand_text(
        str(payload.get("title") or ""), source_label="订阅条目标题"
    )
    return describe_images(
        provider,
        image_urls=urls,
        query_text=guarded_title,
        max_images=max_images,
        max_chars=max_chars,
    )
