"""表情包生成能力（bot.meme）：对接本地 meme-generator-rs HTTP API。

协议与 MemeCrafters/meme-generator-rs v0.5.x 一致（MIT，仅自研客户端，
不引用任何插件代码）：

- GET  /meme/version          -> 文本版本
- GET  /meme/keys             -> ["petpet", ...]
- GET  /memes/{key}/info      -> 表情参数信息
- POST /image/upload          {"type":"data","data": base64} -> {"image_id": "..."}
- POST /memes/{key}           {"images":[{"name","id"}],"texts":[...],"options":{}} -> {"image_id": "..."}
- GET  /image/{image_id}      -> PNG 字节

命令（大小写均可、斜杠可省略）：
- /表情 列表                列出可用表情 key
- /表情 <key> <文字…>       生成文字表情（“｜”分隔多段文字）
- /表情 <key>（发图或 @人）  生成图片表情：消息内图片 > @头像 > 发送者头像
- /表情帮助 / /meme help    用法

后端未启动时优雅降级提示，不抛异常；生成图片写入 data/memes/ 后
以图片形式走统一流水线发送。QQ 多媒体签名 URL 第三方抓不到（A-8 同款
结论），需要图片时一律 bot 侧下载后以 data 形式上传。
"""

from __future__ import annotations

import base64
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.media.digest import media_digest

logger = logging.getLogger(__name__)

_COMMAND_RE = re.compile(
    r"^[/!！]?(?:表情|表情包|表情生成|表情包生成|表情制作|表情包制作|"
    # meme(?! (?:random|stats)\b)：裸 meme/memes 不吃「meme random/meme stats」
    # （归 bot.meme_library，见 meme_library._COMMAND_RE/_STATS_RE；触发
    # 规格体检冲突 ×2 清账）。\b 保证只挡这两条短语，meme generate /
    # meme statistics 等其余后继仍归本能力（meme generate 备选在后兜底）。
    # (?! generate[a-z0-9]) / meme generate(?![a-z0-9])：右侧词边界
    # （wiki _alias_hit 先例），generateqq 类胶合不再落入 rest
    # （边界体检清账）；「meme generate」裸词仍走裸 meme 路径（rest 兜底），
    # parse 口径零改动。
    r"表情製作|表情包製作|表情产生|表情產生|表情包產生|"
    # 全拼/缩写（T-Spec T1.5/T1.6 第二批）：biaoqing 族同音覆盖 製作/產生
    # 简繁词；(?![a-z0-9]) 右边界使 biaoqingbaox/bqbcs 类胶合不触发；
    # 帮助/用法/菜单/列表 tail 词族不拼音化（同批一 eat 参数词族先例），
    # 故 bz/cd/lb/yf 缩写一并放弃（bz 另有 八字/帮助 真冲突）。
    r"biaoqingbaoshengcheng(?![a-z0-9])|bqbs(?![a-z0-9])"
    r"|biaoqingbaochansheng(?![a-z0-9])|bqbc(?![a-z0-9])"
    r"|biaoqingbaozhizuo(?![a-z0-9])|bqbz(?![a-z0-9])"
    r"|biaoqingbao(?![a-z0-9])|bqb(?![a-z0-9])"
    r"|biaoqingshengcheng(?![a-z0-9])|bqsc(?![a-z0-9])"
    r"|biaoqingzhizuo(?![a-z0-9])|bqzz(?![a-z0-9])"
    r"|biaoqingchansheng(?![a-z0-9])|bqcs(?![a-z0-9])"
    r"|biaoqing(?![a-z0-9])"
    r"|meme(?! (?:random|stats)\b)(?! generate[a-z0-9])"
    r"|memes(?! (?:random|stats)\b)(?! generate[a-z0-9])|meme generate(?![a-z0-9]))"
    r"(?:\s+(?P<rest>.+)|(?P<tail>帮助|幫助|help|用法|菜单|菜單|列表|list)?$)",
    re.IGNORECASE,
)
_LIST_VERBS = {"列表", "菜单", "全部", "list", "all", "keys"}
_HELP_VERBS = {"帮助", "用法", "help", "?"}

# key 硬白名单（攻击审计 A-3 修复）：key 原样拼进后端 URL（/memes/{key}、
# /memes/{key}/info）与本地文件名（meme_{key}_{digest}.png 后 write_bytes），
# 旧版零清洗——点号/分隔符/编码形态全部直达。非合规键一律拒绝走失败面，
# 绝不静默洗成近似值。代价：含 CJK 的 key（如「文字表情」）不再可达，
# 帮助文案示例同步改为合规键（meme-generator-rs 均有字母键位可用）。
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 可注入的请求函数便于单元测试：request_fn(method, path, json=None) -> (status, body)
RequestFn = Callable[..., tuple[int, Any]]
# 图片抓取注入缝：image_fetch_fn(url) -> bytes | None（None=抓取失败）。
ImageFetchFn = Callable[[str], "bytes | None"]

# 图片下载上限：表情图不需要更大；异常超大响应直接放弃。
_IMAGE_FETCH_MAX_BYTES = 8 * 1024 * 1024


def _collect_image_sources(message: IncomingMessage) -> list[str]:
    """图片来源优先级：消息内图片 URL → @群友 QQ 头像 → 发送者头像（仅 OneBot）。"""
    sources: list[str] = []
    for segment in message.raw_segments or []:
        seg_type = str(segment.get("type", "")).strip().lower()
        data = segment.get("data") or {}
        if seg_type == "image":
            url = str(data.get("url") or "").strip()
            if url.startswith("http"):
                sources.append(url)
        elif seg_type == "at":
            qq = str(data.get("qq") or "").strip()
            if qq and qq != "all":
                sources.append(f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640")
    if not sources and message.platform == "onebot":
        sender = str(message.sender_id or "").strip()
        if sender:
            sources.append(f"https://q1.qlogo.cn/g?b=qq&nk={sender}&s=640")
    return list(dict.fromkeys(sources))


def _default_image_fetch_fn(url: str) -> bytes | None:
    """抓消息图片字节：SSRF 咽喉逐跳受护（攻击审计 A-2 修复）。

    旧实现把跳转整个交给 httpx（``follow_redirects=True``）、且入口也不问过
    咽喉——协议端一条 302 就能把 bot 引向内网/云元数据。修法不造第二套判据：
    沿用 telegram_media/transcribe 的 httpx request 事件钩子形态——每一跳
    （初始请求 + 每个 30x 落点）在 transport 建连之前过同一个
    ``check_download_url``，命中即抛，内网零连接。

    返回形态不变（None = 抓不到、按无图降级），但咽喉拒绝在抛出点 WARNING
    留痕（URL 过既有脱敏），不静默混淆「瞬时失败」（口径同
    meme_library_listener._download_once）。
    """
    import httpx

    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )

    def _guard_hop(request: httpx.Request) -> None:
        # httpx 每一跳在发出请求之前触发本钩子；拒绝即抛 RejectedUrlError。
        check_download_url(str(request.url))

    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            event_hooks={"request": [_guard_hop]},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        ) as client, client.stream("GET", url) as response:
            if response.status_code != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _IMAGE_FETCH_MAX_BYTES:
                    return None
                chunks.append(chunk)
        return b"".join(chunks) or None
    except RejectedUrlError as exc:
        logger.warning(
            "meme image fetch rejected by SSRF guard: %s (url=%s)",
            exc,
            redact_local_secrets(url),
        )
        return None
    except Exception:  # noqa: BLE001 - 图片抓取失败按无图处理。
        return None


def _output_name_rejection(filename: str) -> str | None:
    """落盘文件名过中央写路径判据（攻击审计 A-1 收敛）：拒→人话理由，放→None。

    判定真身 = ``domains/files/sender/restricted_runner.sanitize_write_segments``
    （Win32 设备名「点号前首段」判定的唯一真身，理由出自单表 ``DENY_PLAIN_TEXT``；
    本席只调用、不修改）。key 白名单已挡住点号与分隔符，本判是纵深兜底：
    万一将来拼接形态变化，也不会把 ``nul.txt`` 类设备名写进盘再炸一个
    误导性 OSError。绝不在此复刻点号切分判据（避免第二真身漂移）。
    """
    from plugins.bot_unified_runtime.domains.files.sender import restricted_runner

    try:
        restricted_runner.sanitize_write_segments(filename)
    except Exception as exc:  # noqa: BLE001 - _Rejected 携带代号，转中央人话表
        code = str(getattr(exc, "code", "") or "")
        return restricted_runner.plain_reason(code) if code else f"落盘名被中央路径护栏拒绝（{type(exc).__name__}）"
    return None


def is_meme_command(text: str) -> bool:
    return _COMMAND_RE.match(text.strip()) is not None


def parse_meme_command(text: str) -> tuple[str, str, list[str]]:
    """返回 (动作, key, texts)。动作：help / list / render。"""
    match = _COMMAND_RE.match(text.strip())
    if not match:
        raise ValueError("not a meme command")
    rest = (match.group("rest") or "").strip()
    tail = (match.groupdict().get("tail") or "").strip().lower()
    if tail in _LIST_VERBS:
        return "list", "", []
    if not rest or rest.lower() in _HELP_VERBS:
        return "help", "", []
    first, _, remainder = rest.partition(" ")
    if not remainder.strip():
        # “表情 列表”这种整体是关键词。
        if first.lower() in _LIST_VERBS:
            return "list", "", []
        # 纯 key（无文字）：可能是零文字的图片表情（如 petpet），
        # 也可能只是打错了 key——由能力层按 info 的 min_texts 区分。
        return "render", first, []
    if first.lower() in _LIST_VERBS:
        return "list", "", []
    texts = [item.strip() for item in remainder.split("｜") if item.strip()] or [
        remainder.strip()
    ]
    return "render", first, texts


def _usage_body() -> str:
    return (
        "表情包用法：\n"
        "1. /表情 列表 —— 列出可用表情 key\n"
        "2. /表情 <key> <文字> —— 生成表情，如『/表情 petpet 可爱』\n"
        "   多段文字用 ｜ 分隔：『/表情 5000choyen 你好｜世界』\n"
        "3. 需要图片的表情（如 petpet）：发图或 @ 群友后输命令，"
        "不带图时会用你的头像\n"
        "4. /表情帮助 —— 查看本说明\n"
        "需要本地运行 meme-generator-rs（默认 http://127.0.0.1:2233）。"
    )


_HTTP_CLIENTS: dict[tuple[str, float], Any] = {}
_HTTP_CLIENTS_LOCK = threading.Lock()


def _default_request_fn(base_url: str, timeout_seconds: float) -> RequestFn:
    import httpx

    key = (base_url.rstrip("/"), float(timeout_seconds))
    with _HTTP_CLIENTS_LOCK:
        client = _HTTP_CLIENTS.get(key)
        if client is None:
            # 进程内按 (base_url, timeout) 复用连接池——此前每次调用新建
            # Client 且从不 close，表情命令洪峰下泄漏连接。
            client = httpx.Client(base_url=key[0], timeout=timeout_seconds)
            _HTTP_CLIENTS[key] = client

    def request(method: str, path: str, json: dict | None = None) -> tuple[int, Any]:
        try:
            response = client.request(method.upper(), path, json=json)
        except httpx.HTTPError:
            return 0, None
        body: Any = None
        content_type = response.headers.get("content-type", "")
        try:
            if "json" in content_type:
                body = response.json()
            else:
                body = response.content
        except Exception:  # noqa: BLE001
            body = response.content
        return response.status_code, body

    return request


def _display_safe_name(value: str) -> str:
    """表情名（后端 key）进用户可见文案前的显示伪装处置（ANTIATTACK P2-d）。

    后端 `/meme/keys` 返回的名字既不由 bot 生成、也不在任何入站话术门里，一枚带
    反向覆写或全角近似形的 key 就是「显示面零扫描」的现成入口。判据零副本：真身住
    `core/safety_exec/attack_surface`，处置口住
    `chat_reply/security/injection::render_safe_display_name`；**局部导入**——meme
    域对 chat_reply 只做函数级复用（先例：`meme/reactions/sentiment_selector.py`
    局部导入 `guard_secondhand_text`），不开模块级跨域依赖。空进空出，合法名逐字节
    不变（守岸人语感：干净的名字照常念，只在骗眼肉的那一格才收口）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        render_safe_display_name,
    )

    return render_safe_display_name(value)


def build_meme_capability(
    config: Any | None = None,
    *,
    request_fn: RequestFn | None = None,
    output_dir: str | None = None,
    image_fetch_fn: ImageFetchFn | None = None,
) -> Any:
    enabled = bool(getattr(config, "bot_meme_api_enabled", False)) if config else False
    base_url = (
        str(getattr(config, "bot_meme_api_base_url", "http://127.0.0.1:2233") or "")
        .strip()
        .rstrip("/")
        if config
        else "http://127.0.0.1:2233"
    )
    timeout = float(getattr(config, "bot_meme_api_timeout_seconds", 15.0) or 15.0) if config else 15.0
    out_dir = Path(output_dir or (str(getattr(config, "bot_meme_api_output_dir", "data/memes") or "") if config else "data/memes"))

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        if not enabled:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body="表情包功能还没开，等管理员把它打开就能玩了。",
                audit_tags=["meme", "meme_disabled"],
            )
        try:
            action, key, texts = parse_meme_command(message.plain_text)
        except ValueError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body=_usage_body(),
                audit_tags=["meme", "meme_missing_query"],
            )
        if action == "help":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                title="表情包帮助",
                body=_usage_body(),
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme", "meme_help"],
            )

        requester = request_fn or _default_request_fn(base_url, timeout)
        if action == "list":
            status, body = requester("GET", "/meme/keys")
            if status != 200 or not isinstance(body, list) or not body:
                return _service_down_result(message, requester, base_url)
            # P2-d：外部服务返回的名字是攻击者可控显示面——逐个过显示伪装处置
            # （剥不可见伪装 / 折同形角色词 / 折不动的整格屏蔽）。这里**不**改
            # `[:200]` 有界化与 `meme_keys:{len(body)}` 计数口径：两者都以
            # **原始 body** 为准，屏蔽只影响肉眼看到的那一格。
            preview = "、".join(_display_safe_name(str(item)) for item in body[:200])
            tail = f"\n…共 {len(body)} 个" if len(body) > 200 else f"\n共 {len(body)} 个"
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                title="可用表情",
                body=f"{preview}{tail}",
                risk_level=RiskLevel.LOW,
                privacy_level=PrivacyLevel.PUBLIC,
                audit_tags=["meme", f"meme_keys:{len(body)}"],
            )

        # 硬白名单（攻击审计 A-3）：key 会拼进后端 URL 与本地文件名，
        # 非合规形态在触碰任何端点之前即拒绝，走帮助失败面。
        if not _KEY_RE.match(key):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body=_usage_body(),
                audit_tags=["meme", "meme_invalid_key"],
            )

        # 图片表情：按 info 的参数决定是否带图（info 拿不到时按纯文字处理，
        # 与旧版行为兼容）。图片一律 bot 侧下载后转 data 上传——QQ 多媒体
        # 签名 URL 服务端抓不到。
        image_fetch = image_fetch_fn or _default_image_fetch_fn
        min_images = max_images = min_texts = 0
        info_ok = False
        status, info = requester("GET", f"/memes/{key}/info")
        if status == 200 and isinstance(info, dict):
            params = info.get("params") or {}
            if isinstance(params, dict):
                try:
                    min_images = max(0, int(params.get("min_images") or 0))
                    max_images = max(0, int(params.get("max_images") or 0))
                    min_texts = max(0, int(params.get("min_texts") or 0))
                    info_ok = True
                except (TypeError, ValueError):
                    min_images = max_images = min_texts = 0

        # 纯 key 无文字：确属零文字表情才渲染；否则当打错 key 回帮助。
        if not texts and not (info_ok and min_texts == 0):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body=_usage_body(),
                audit_tags=["meme", "meme_missing_query"],
            )

        image_params: list[dict[str, str]] = []
        if max_images > 0 or min_images > 0:
            sources = _collect_image_sources(message)
            for source in sources[:max(1, max_images)]:
                payload = image_fetch(source)
                if not payload:
                    continue
                status, uploaded = requester(
                    "POST",
                    "/image/upload",
                    json={"type": "data", "data": base64.b64encode(payload).decode()},
                )
                if status == 200 and isinstance(uploaded, dict) and uploaded.get("image_id"):
                    image_params.append(
                        {"name": f"img{len(image_params)}.png", "id": str(uploaded["image_id"])}
                    )
            if len(image_params) < min_images:
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme",
                    kind="text",
                    body=(
                        f"表情『{key}』需要 {min_images} 张图片：把图片和命令发在同一条"
                        "消息里，或 @ 一位群友（我会用 Ta 的头像）。"
                    ),
                    risk_level=RiskLevel.LOW,
                    privacy_level=PrivacyLevel.PUBLIC,
                    audit_tags=["meme", "meme_need_images"],
                )

        status, body = requester(
            "POST",
            f"/memes/{key}",
            json={"images": image_params, "texts": texts, "options": {}},
        )
        if status != 200 or not isinstance(body, dict) or not body.get("image_id"):
            # 服务端错误体为 {"code":…,"message":"…"}（meme-generator-rs 实测），
            # 透传 message 让用户知道是缺文字/缺图还是 key 不存在。
            detail = ""
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("detail") or "").strip()[:160]
            return _service_down_result(message, requester, base_url, key=key, detail=detail)
        image_id = str(body["image_id"])
        status, content = requester("GET", f"/image/{image_id}")
        if status != 200 or not isinstance(content, (bytes, bytearray)):
            return _service_down_result(message, requester, base_url, key=key)
        # [:12] 截短是消费侧缓存文件名决定（蓝图 §3.1：算法不截短）。
        digest_prefix = media_digest(bytes(content))[:12]
        try:
            suffix = ".gif" if bytes(content)[:3] == b"GIF" else ".png"
            filename = f"meme_{key}_{digest_prefix}{suffix}"
            # A-1 纵深兜底：写盘前最后一道用中央判据（判定不过=拒写并留痕，
            # 不洗名、不写近似文件）。放在 mkdir 之前，拒绝路径零文件系统副作用。
            denied_reason = _output_name_rejection(filename)
            if denied_reason is not None:
                logger.warning("meme output name rejected by central path guard: %s", denied_reason)
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.meme",
                    kind="text",
                    body="表情生成成功，但保存名未通过安全护栏，已拒绝落盘。",
                    audit_tags=["meme", "meme_save_failed"],
                )
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / filename
            path.write_bytes(bytes(content))
            try:
                from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                    enforce_quota,
                )

                enforce_quota(
                    out_dir,
                    max_bytes=int(getattr(config, "bot_meme_cache_max_bytes", 0) or 0),
                )
            except Exception:  # noqa: S110, BLE001 - 缓存配额清理失败不影响主链路。
                pass
        except OSError:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.meme",
                kind="text",
                body="表情生成成功，但本地保存失败（磁盘不可写）。",
                audit_tags=["meme", "meme_save_failed"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.meme",
            kind="mixed",
            title=f"表情包 {key}",
            body=f"已生成表情『{key}』（{len(texts)} 段文字）。",
            images=[{"file": str(path)}],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=["meme", f"meme_key:{key}", "meme_render"],
        )

    return capability


def _service_down_result(
    message: IncomingMessage,
    requester: RequestFn,
    base_url: str,
    *,
    key: str | None = None,
    detail: str = "",
) -> CapabilityResult:
    status, version = requester("GET", "/meme/version")
    if status == 200 and isinstance(version, (str, bytes)):
        hint = f"表情『{key}』参数不对或生成失败。" if key else "表情服务异常。"
        if detail and key:
            hint += f"原因：{detail}"
    else:
        hint = (
            f"表情包服务未启动或不可达（{base_url}）。"
            "请先启动 meme-generator-rs，再试一次。"
        )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.meme",
        kind="text",
        body=hint,
        audit_tags=["meme", "meme_backend_unavailable"],
    )

