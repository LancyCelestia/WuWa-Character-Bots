"""Bot 本地头像与多实例身份（2026-09-13 用户指令；2026-09-20 AVT1 扩多实例）。

SnowLuma 侧取到 bot QQ 后把头像下载持久化到 Runtime data/avatar/，此后所有
卡片按需取 URI，不再因 BOT_PERSONA_AVATAR_URL 为空而回落"守"字圆点。

单实例（``bot_id`` 省略）优先级：config.bot_persona_avatar_url 显式配置 >
本地缓存（内存登记；内存为空时磁盘兜底发现 avatar/bot_*.png，F3 2026-09-14）
> 空。下载动作由连接钩子触发（__init__ on_bot_connect → refresh_from_qq）；
读取侧（F3）统一走 bot_avatar_uri——本地命中即用，不再周期回源。

多实例（AVT1 2026-09-20 用户裁定「做成多 bot 身份自动取」）：一台机器上
可以并存多个发送方（主号 / 校园号 2300230562 / 推送号 3958874605 …），每张
卡上的**名字与头像必须随实际发送方变化**，不得写死。落点=本模块的
``bot_identity(bot_id, config)``：头像按 ``avatar/bot_<qq>.png`` 既有命名逐实例
取（``refresh_from_qq`` 本就以 bot_id 命名落盘，天然按实例隔离），名字走
「显式登记 → 装配层解析器 → 人格配置名 → 空（由胶囊回落品牌名）」四级。
注册表与既有单实例槽位并存且**互不干扰**：``bot_id`` 为空的路径行为与今天
逐字节一致（tests/test_bot_avatar.py 锁定的三个进程级全局语义不变）。

新增配置键＝零（本波纪律）。第二实例的**名字**目前没有任何既有 config 键
可承载（``bot_persona_display_name`` 是单值人格名），故只提供登记入口
``register_identity`` 与装配层钩子 ``set_identity_resolver``，并登记为待裁点
（见 docs/design/unify-audit-20260919/AVT1-impl.md §七）。

**渲染形态的唯一收口＝``inline_avatar_uri``**（2026-09-26 本席定口径）：本模块
所有交给卡片的头像值一律过它一道闸，出口只可能是 ``data:image/…`` / ``http(s)://…``
/ 空串三种，**不会是裸 ``file:///``**（那种形态在 ``set_content`` 页里被 Chromium
静默拒收＝她点名的空白占位）。模块内仍存路径形态（``_LOCAL_AVATAR_URI``、
``_per_instance_avatar_uri`` 的返回、注册表登记值），那是内部中间值不是渲染输入；
卡面缺图时的「守」字圆点兜底在各模板/胶囊组件里，判据是「值为空串」。
"""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCAL_AVATAR_URI: str = ""
_LOCK = threading.Lock()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShoreKeeperBot/1.0"

# 审查 L-14：头像文件缺失时每张卡都走 glob+stat 磁盘兜底探测——长跑进程
# 无谓重复。负结果（扫描确认缺失）按「解析后的 avatar 目录」键控 TTL 缓存：
# TTL 内直接回空不再探测，过期重探（期间目录里新出现的头像最多延迟 TTL
# 秒生效——观感链路可接受的取舍）。正结果语义零变化：命中即登记
# _LOCAL_AVATAR_URI，内存短路后续调用，天然不经过本缓存。
# 无界防说明（对齐 randpic L-10 先例的判据）：键空间=单一头像目录路径族，
# 生产恒为 config.bot_runtime_data_dir 单键，测试临时目录随 monkeypatch
# 丢弃——键数天然有界，无需 LRU 封顶。
_DISCOVER_MISS_TTL_SECONDS = 300.0
_DISCOVER_MISS_TS: dict[str, float] = {}

# 头像内联成 data URI 的常量（根因见 ``inline_avatar_uri`` docstring）。
# 上限是「别把几 MB base64 塞进每张卡」的护栏，不是「头像必须有」的承诺：
# 超限先缩一次再内联（本机现存头像 971 字节走直读路径，缩略分支留给更大的图），
# 缩完仍超限才回空串——圆点兜底。
#
# ⚠ 计量口径（2026-09-26 本席改）：裁的是**编码后**的 base64 字符数，不是原始字节。
# 理由：base64 每 3 字节胀成 4 字符（+33%），旧口径按原图字节放行 ⇒ 一张 250KB 的
# 头像会往**每一张卡**的 HTML 里塞 333KB 文本，护栏形同虚设。现在先按原图大小预判
# 编码长度，可能超限就走缩略腿，缩完仍以编码长度定性。
_AVATAR_INLINE_MAX_BYTES = 256 * 1024
_AVATAR_SHRINK_SIDE = 160  # 卡面头像位最大 46px（胶囊）/60px，160 留足倍图余量
_AVATAR_INLINE_CACHE_MAX = 8
# MIME 不再有「按后缀查表」的映射：真实类型一律由 ``_sniff_image_mime`` 读文件头
# 定（声明与内容不符＝一张解不出来的碎图，与本闸要禁的裸 file:// 同一种观感）。
# 裸 Windows 盘符路径（``C:\x.png`` / ``C:/x.png``）不是 URL：urlsplit 会把盘符
# 读成 scheme="c"，判据必须先认它，否则管理员手填路径永远只剩圆点。
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_AVATAR_INLINE_CACHE: dict[tuple[str, int, int], str] = {}
# 可注入时钟：测试 monkeypatch 此名推进时间，全离线不真睡。
_MONOTONIC = time.monotonic


@dataclass(frozen=True)
class BotIdentity:
    """单实例身份值对象。两侧空串各归各的回落：名字空 → 胶囊回落品牌名
    （``BRAND_THEME.display_name``），头像空 → 胶囊回落首字圆点。"""

    name: str = ""
    avatar_uri: str = ""


# AVT1 多实例槽位（进程级，与 _LOCAL_AVATAR_URI 单实例槽位互不污染）：
# 显式登记表 + 装配层解析器。_LOCK 下存取；解析器**绝不持锁调用**
# （它可能反读本模块读取面，threading.Lock 非重入，持锁回调=自杀）。
_IDENTITY_REGISTRY: dict[str, BotIdentity] = {}
_IDENTITY_RESOLVER: Callable[[str, object], str | None] | None = None


def avatar_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "avatar"


def refresh_from_qq(bot_id: str, data_dir: str | Path, *, timeout: float = 8.0) -> str:
    """从 qlogo 下载 bot 头像落本地并激活；返回 file URI（失败返回 ""）。

    返回值是**进程内登记形态**（路径，稳定、可跨 TTL 比对），不是卡片输入——
    交给卡片前必须过 ``inline_avatar_uri`` 这道闸。生产唯一调用方
    （``__init__._log_bot_connect`` → ``_refresh_local_bot_avatar``）取的是副作用
    （文件落盘 + 内存槽位激活），本就丢弃该返回值。

    任意失败都不抛——头像缺失只影响观感，绝不能影响卡片渲染链路。
    """
    global _LOCAL_AVATAR_URI
    qq = str(bot_id or "").strip()
    if not qq.isdecimal():
        return ""
    target_dir = avatar_dir(data_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"bot_{qq}.png"
        request = urllib.request.Request(
            f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640",
            headers={"User-Agent": _UA},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(8 * 1024 * 1024)
        if not payload.startswith(b"\x89PNG"):
            return ""
        target.write_bytes(payload)
        with _LOCK:
            _LOCAL_AVATAR_URI = target.as_uri()
        return _LOCAL_AVATAR_URI
    except Exception:  # noqa: BLE001 - 头像下载失败静默（观感降级非功能）。
        logger.debug("bot avatar download failed qq=%s***", qq[-2:])
        return ""


def set_local_path(path: str | Path) -> None:
    """测试/外部注入：直接登记本地头像文件。"""
    global _LOCAL_AVATAR_URI
    candidate = Path(path)
    if candidate.is_file():
        with _LOCK:
            _LOCAL_AVATAR_URI = candidate.as_uri()


def _data_root(config: object | None) -> Path | None:
    """data 目录绝对根（AVT1 自 _discover_local_uri 原样提级，口径零改动）：
    config.bot_runtime_data_dir 绝对路径直用，相对路径挂工作区根；
    未提供该字段返回 None（保持测试/裸调用的确定性）。"""
    data_dir = (
        "" if config is None
        else str(getattr(config, "bot_runtime_data_dir", "") or "").strip()
    )
    if not data_dir:
        return None
    root = Path(data_dir).expanduser()
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[4] / root
    return root


def _discover_local_uri(config: object | None) -> str:
    """磁盘兜底（F3 2026-09-14）：avatar 目录挑最新的 bot_*.png 登记激活。

    覆盖「重启后 qlogo 拉取失败但上轮文件还在」的边角——文件存在即直接登记激活，
    无需再回源；登记的仍是路径形态（``_LOCAL_AVATAR_URI`` 与内存槽位同形），
    交给卡片前由 ``inline_avatar_uri`` 统一过闸。目录解析（AVT1 提级为
    _data_root）与写入侧（__init__._refresh_local_bot_avatar）同口径：config 未提供
    该字段时放弃发现（保持测试/裸调用的确定性）。任何失败返回空串，绝不抛。

    审查 L-14：扫描确认缺失时记负结果 TTL 缓存（_DISCOVER_MISS_TS），
    TTL 内的重复调用跳过 glob+stat 直接回空，过期重探。
    """
    global _LOCAL_AVATAR_URI
    root = _data_root(config)
    if root is None:
        return ""
    try:
        cache_key = str(root / "avatar")
        now = _MONOTONIC()
        with _LOCK:
            last_miss = _DISCOVER_MISS_TS.get(cache_key)
            miss_fresh = (
                last_miss is not None
                and now - last_miss <= _DISCOVER_MISS_TTL_SECONDS
            )
        if miss_fresh:
            return ""  # TTL 内已知缺失：不再 glob+stat（审查 L-14）
        candidates = sorted(
            (root / "avatar").glob("bot_*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                with _LOCK:
                    _LOCAL_AVATAR_URI = candidate.as_uri()
                    _DISCOVER_MISS_TS.pop(cache_key, None)  # 清陈旧负缓存
                return _LOCAL_AVATAR_URI
        with _LOCK:
            # 扫描确认缺失：记负结果，TTL 内同目录不再探测。
            _DISCOVER_MISS_TS[cache_key] = _MONOTONIC()
    except Exception:  # noqa: BLE001 - 磁盘兜底失败静默（观感降级非功能）。
        return ""
    return ""


def _sniff_image_mime(blob: bytes) -> str:
    """按**文件头**定 MIME；认不出的形态回空串（不猜）。

    为什么不信后缀：data URI 的 MIME 是浏览器拿去选解码器的东西，「后缀说 png、
    内容不是 png」就是一张解不出来的碎图——和裸 ``file://`` 同一种「看着有、其实
    没有」。本模块自家写入侧（``refresh_from_qq``）本来就校验过 PNG 魔数，走那条
    路进来的文件两者必然一致；会不一致的是管理员手填的路径与别的波次落盘的文件，
    所以判据取魔数。副作用是诚实的：文本文件改名 ``.png`` 只会被判「不是图」而回
    空串（卡片走圆点），不会出一张碎图；同理 ICO/AVIF/SVG 这类本函数没登记的编码
    也不猜，宁可圆点。
    """
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob.startswith(b"BM"):
        return "image/bmp"
    return ""


def _local_avatar_target(raw: str) -> Path | None:
    """把「本地形态」的头像值解成 Path；不是本地形态回 None。

    认三种写法：``file:///C:/x/a.png``（``Path.as_uri()`` 的产物）、
    ``file://localhost/C:/x/a.png``、以及裸路径 ``C:\\x\\a.png``。
    ``as_uri()`` 会把非 ASCII 段百分号编码（中文目录名/用户名），所以必须先
    ``unquote`` 再拼 Path——否则解出来的路径里带一串 ``%E4%B8%AD``，
    ``is_file()`` 永远为假，头像莫名其妙变圆点。

    ⚠ **Windows 盘符不是 URL scheme**（本席第一版就栽在这里，被
    tests/test_bot_avatar.py 的 9 条存量锁当场打回）：``urlsplit("C:\\x\\a.png")``
    解出 ``scheme="c"``——按 scheme 判"不是本地形态"就会把管理员手填的裸路径
    一律判空、卡片永远只剩圆点。故盘符形态先短路，绝不交给 urlsplit 定性。
    """
    if _WINDOWS_DRIVE_PATH_RE.match(raw):
        try:
            return Path(raw)
        except ValueError:
            return None
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.lower() == "file":
        if parts.netloc not in ("", "localhost"):
            return None  # 指向别的主机的 file: 不是本机文件，卡片更加载不到
        path = urllib.parse.unquote(parts.path)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]  # Windows：as_uri 给的是 /C:/…，去掉打头的斜杠
        try:
            return Path(path) if path else None
        except ValueError:
            return None
    if parts.scheme:
        return None  # http(s) 等远程形态由调用侧原样放行，不进本地分支
    try:
        return Path(raw)
    except ValueError:
        return None


def _encode_data_uri(blob: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


def _b64_payload_length(raw_size: int) -> int:
    """原始字节数 → base64 编码后字符数（不实际编码，纯算）。

    上限要裁的是「塞进每张卡 HTML 的那串字符」，而 base64 每 3 字节胀成 4 字符，
    所以判超限必须先换算，不能拿原图大小当量。``(n + 2) // 3 * 4`` 与
    ``len(base64.b64encode(...))`` 逐例等值（标准库无换行时的定义式）。
    """
    return (raw_size + 2) // 3 * 4


def _shrink_to_data_uri(path: Path) -> str:
    """超限头像缩到 ``_AVATAR_SHRINK_SIDE`` 见方再内联；缩不动/仍超限回空串。

    PIL 在本仓是既有依赖（识图/拼图/图库都在惰性用它），这里同样惰性导入并
    fail-open：任何异常都只回空串（卡片回落「守」字圆点），绝不抛——头像只关
    观感，不该有炸渲染链路的能力。重编码一律按 PNG 声明（缩略图就是 PNG，
    声明与内容同源，不存在「按原后缀声明」的错配风险）。
    """
    try:
        import io

        from PIL import Image

        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        image.thumbnail((_AVATAR_SHRINK_SIDE, _AVATAR_SHRINK_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        blob = buffer.getvalue()
        # 与闸门同口径：这里比的也是编码后长度（旧写法比原图字节，等于放行 1.33 倍）。
        if not blob or _b64_payload_length(len(blob)) > _AVATAR_INLINE_MAX_BYTES:
            return ""
        return _encode_data_uri(blob, "image/png")
    except Exception:  # noqa: BLE001 - 观感件：缩图失败=回圆点，不抛。
        return ""


def inline_avatar_uri(source: object) -> str:
    """头像 → **卡片可渲染形态**的唯一闸门：data URI／http(s)／空串，仅此三种。

    为什么必须在进渲染器之前内联（2026-09-26 本席自证，非转述）：卡片走
    ``render_backends`` 的 ``page.set_content(html)`` 装页，实测该页
    ``location.origin`` 是 ``null``（href 为 ``about:blank``），Chromium 在这种
    origin 下**拒收 ``file://`` 子资源**——同一张图在真 ``file://`` 页面里
    ``naturalWidth=8``，塞进 ``set_content`` 页就变 ``0`` 并触发 ``onerror``，
    且无异常、console 无错，静默。于是「左上角头像没加载出来，成了空白占位」。
    换 ``data:image/png;base64,…`` 同页实测 ``naturalWidth=8``。
    （对照实验：``file://`` 页面 + 相对路径 → 8；``set_content`` + ``file:///`` → 0。）

    三条出口语义（缺一不可，第三条是本闸门的意义所在）：

    1. 本地文件读得到 → ``data:<嗅探出的 MIME>;base64,…``；
    2. ``http(s)://`` / ``data:image/`` 原样透传（管理员显式配的远程图与已内联值
       不归本闸裁）；**其余 ``data:`` 形态不透传**——非图片 MIME 进 ``<img src>``
       就是一张解不出来的碎图，与裸 ``file://`` 同一种观感；
    3. 其余一律**空串**——包括读不到的本地路径、超限又缩不动的文件、以及
       根本不是图片的字节。**绝不回一个注定加载失败的 ``file:///``**：那种形态
       在卡上连「守」字圆点都替不掉（``<img onerror>`` 直接把图 hide 掉），
       回空串才让模板走既有圆点兜底腿。

    尺寸上限是护栏不是裁切，且**量的是编码后的字符数**（base64 胀 4/3）：
    按原图大小预判编码长度，可能超限先缩略、缩完仍超限才回空串。按
    (路径, mtime_ns, 字节数) 缓存，头像文件换了自动失效；本函数幂等
    （对已内联的值再调一次返回同值），所以各级链路过它多次无副作用。
    """
    raw = str(source or "").strip()
    if not raw:
        return ""
    if raw.startswith(("data:image/", "http://", "https://")):
        return raw
    candidate = _local_avatar_target(raw)
    if candidate is None:
        return ""
    try:
        stat = candidate.stat()
        if not candidate.is_file() or stat.st_size == 0:
            return ""
        cache_key = (str(candidate), stat.st_mtime_ns, stat.st_size)
        with _LOCK:
            cached = _AVATAR_INLINE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        oversized = _b64_payload_length(stat.st_size) > _AVATAR_INLINE_MAX_BYTES
        if oversized:
            # 原图太大不塞卡：先缩略重编码（缩完仍超限或解不开→空串→圆点）。
            uri = _shrink_to_data_uri(candidate)
        else:
            blob = candidate.read_bytes()
            mime = _sniff_image_mime(blob)
            # 内容不是登记在册的图片编码：不猜、不拿后缀充数，回空串走圆点。
            uri = _encode_data_uri(blob, mime) if mime else ""
        with _LOCK:
            # 只留最近几张，防跨实例长期累积（键含 mtime，换文件即新键）。
            _AVATAR_INLINE_CACHE[cache_key] = uri
            while len(_AVATAR_INLINE_CACHE) > _AVATAR_INLINE_CACHE_MAX:
                _AVATAR_INLINE_CACHE.pop(next(iter(_AVATAR_INLINE_CACHE)))
        return uri
    except OSError:
        return ""


def bot_avatar_uri(config: object | None = None) -> str:
    """卡片统一入口：显式配置 > 本地缓存（内存，缺失时磁盘兜底）> 空。

    **三条出口一律经 ``inline_avatar_uri`` 这一道闸**（根因见其 docstring：卡片
    走 ``set_content`` 装页，裸 ``file://`` 子资源被 Chromium 静默拒收），所以本
    入口只可能回三种形态：``data:image/…;base64,…``、``http(s)://…``、空串。

    显式配置这一级的口径变更（2026-09-26 本席）：``BOT_PERSONA_AVATAR_URL`` 在
    ``docs/config-catalog-full.md`` 里登记的合法取值就是「URL 或本地路径」，而旧
    实现把它**原样**交给卡片——填 URL 正常，填路径就正好踩进同一枚碎图坑（她按
    台账 P3-1「可提供头像图路径后配置」去填，就会得到一张空白占位）。现在路径会被
    内联成 data URI；配置值指向的文件读不到时**顺延下一级**（内存登记→磁盘兜底），
    而不是把一个渲染不出来的值交出去——顺延比"配错一次就整卡丢头像"更诚实。
    """
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        renderable = inline_avatar_uri(configured)
        if renderable:
            return renderable
    with _LOCK:
        uri = _LOCAL_AVATAR_URI
    return inline_avatar_uri(uri or _discover_local_uri(config))


# --- AVT1 多实例身份（2026-09-20 用户裁定「做成多 bot 身份自动取」） -------


def register_identity(bot_id: str, *, name: str = "", avatar_uri: str = "") -> None:
    """显式登记实例身份（名字链第一级 + 头像链第一级）。

    - 空白 bot_id 拒绝入库（空键=单实例路径，绝不允许被登记面污染）；
    - **整条替换**：再次登记未带字段即清空旧值，不做隐式继承——登记面
      状态单调用可推（tests/test_bot_avatar.py ⑤ 语义锁）；
    - 字段空串=该字段不表态，解析时顺延下一级。
    """
    key = str(bot_id or "").strip()
    if not key:
        return
    with _LOCK:
        _IDENTITY_REGISTRY[key] = BotIdentity(
            name=str(name or "").strip(), avatar_uri=str(avatar_uri or "").strip()
        )


def set_identity_resolver(
    resolver: Callable[[str, object], str | None] | None,
) -> None:
    """装配层挂名字解析器（名字链第二级）；传 None 摘除。

    生产接线建议（接入计划步骤三，见 AVT1-impl.md §五）：装配期注册一次，
    按 bot_id 查平台身份表（如 snowluma 平台登记/校园配置键归组），
    不识别的 bot_id 返回空串放行。
    """
    global _IDENTITY_RESOLVER
    with _LOCK:
        _IDENTITY_RESOLVER = resolver


def _persona_display_name(config: object | None) -> str:
    """名字链第三级：人格配置中文名（config.py:150，实例可配面貌字段）。"""
    return str(getattr(config, "bot_persona_display_name", "") or "").strip()


def _per_instance_avatar_uri(bot_id: str, config: object | None) -> str:
    """头像链第二级：``avatar/bot_<qq>.png`` 逐实例直取（AVT1）。

    refresh_from_qq 本就以该命名落盘，逐实例天然隔离；纯数字 QQ 号 +
    文件存在且非空才命中（0 字节视同缺失，对齐 _discover_local_uri 口径）。
    返回值是**路径形态的内部中间值**（与 ``_LOCAL_AVATAR_URI`` 同形，锁
    tests/test_bot_avatar.py::test_no_public_getter_ever_returns_file_uri 钉住
    「内部槽位不许被顺手改成 data URI」）：唯一消费点 ``bot_identity`` 必须再过一
    次闸门才交给卡片，本函数自己不作为渲染出口存在。
    不加负结果 TTL：单次 is_file+stat 远廉于整目录 glob+stat（审查 L-14
    的成本前提不成立），每卡重探代价可忽略。任何失败返回空串，绝不抛。
    """
    qq = str(bot_id or "").strip()
    if not qq.isdecimal():  # 非 QQ 形态（tg:xx 等）无落盘命名约定，跳过
        return ""
    root = _data_root(config)
    if root is None:
        return ""
    try:
        candidate = root / "avatar" / f"bot_{qq}.png"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.as_uri()
    except Exception:  # noqa: BLE001 - 观感降级非功能。
        return ""
    return ""


def bot_identity(bot_id: str = "", config: object | None = None) -> BotIdentity:
    """卡面身份统一入口：按实际发送方解析中文名与头像（AVT1 单一落点）。

    - ``bot_id`` 为空（含纯空白）＝单实例旧口径：头像**逐字节等于**
      ``bot_avatar_uri(config)``，名字=人格配置名；注册表、解析器、逐实例
      磁盘探测一律不经过（回归锁 tests/test_bot_avatar.py ①）。
    - 非空 ``bot_id``：名字「显式登记 → 装配层解析器 → 人格配置名 → 空
      （胶囊回落品牌名）」四级；头像「登记 → ``avatar/bot_<qq>.png`` →
      旧全局链」三级。末级回落到全局链=「不比今天差」原则：接入前所有卡
      本就共用同一枚头像/品牌名，逐实例信息缺失时维持该观感，绝不塌陷。
    - 解析器不持锁调用（可安全反读本模块读取面）、抛异常 fail-safe 落
      下一级；本函数任何输入都不抛（头像/名字只关观感，不炸渲染链路）。
    """
    key = str(bot_id or "").strip()
    if not key:
        return BotIdentity(
            name=_persona_display_name(config),
            avatar_uri=bot_avatar_uri(config),
        )
    with _LOCK:
        entry = _IDENTITY_REGISTRY.get(key)
        resolver = _IDENTITY_RESOLVER
    registered = entry if entry is not None else BotIdentity()
    name = registered.name
    if not name and resolver is not None:
        try:
            name = str(resolver(key, config) or "").strip()
        except Exception:  # 解析器炸了不塌卡面：fail-safe 顺延人格配置名。
            logger.debug(
                "bot identity resolver failed bot_id=%s***", key[-2:], exc_info=True
            )
            name = ""
    if not name:
        name = _persona_display_name(config)
    avatar = (
        # 第一级（显式登记）＝**登记什么读出什么**：登记面是身份数据不是渲染输入，
        # 读不到的值也必须原样回（AVT1 ⑤ 注册表隔离锁 + 锁
        # tests/test_bot_avatar.py::test_registered_value_that_cannot_be_inlined_survives
        # 明写不许把登记值抹成空串）。能读到就必须是卡片可用的形态，所以先过闸。
        inline_avatar_uri(registered.avatar_uri)
        or registered.avatar_uri
        # 第二级起是**文件面**：只有闸门认可的形态才有资格交给卡片。缩不动的超大图
        # 在此顺延到全局链（别的实例可能读得到），而不是把一个 file:/// 塞进卡——
        # 那东西在卡上连圆点都顶不掉（模板 ``<img onerror>`` 直接把图 hide）。
        or inline_avatar_uri(_per_instance_avatar_uri(key, config))
        or bot_avatar_uri(config)  # 第三级：入口自己已过闸
    )
    return BotIdentity(name=name, avatar_uri=avatar)
