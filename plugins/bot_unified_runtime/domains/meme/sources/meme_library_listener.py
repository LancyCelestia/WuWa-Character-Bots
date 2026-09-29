"""群聊图片监听：异步下载图片 → MD5 去重入库 → 可选 VLM 打标。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

# SSRF 咽喉：本域**不**自建校验逻辑，直引下载侧唯一护栏真身（v21r2 重组后的
# 权威路径，与 domains/notes 同一入口）；审计 U1-15/U1-10 记录本文件曾零调用。
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
    check_download_url,
)
from plugins.bot_unified_runtime.domains.media import image_guard
from plugins.bot_unified_runtime.domains.meme.sources import shorekeeper_absorb
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

logger = logging.getLogger(__name__)

# 手动逐跳跟随时的一次性上限（与 urllib 默认 10 相比取保守值，超限即弃图）。
_MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

TAG_PROMPT = (
    "你是一个图片分析助手。请分析这张图片并返回JSON格式的标签信息。"
    "请返回以下格式的JSON(不要包含其他内容）："
    '{"is_meme": true, "description":"简短描述图片内容(20字以内）",'
    '"emotion_tags":["情绪标签1","情绪标签2"],'
    '"scene_tags":["场景标签1","场景标签2"],'
    '"persona_hint": "common", "nsfw_score":0.0}'
    "字段说明：is_meme 是否为表情包（带文字/配文的图片、表情包、梗图等），"
    "普通照片/风景/人物写真/截图/二次元/美女填 false；description 简短描述"
    "（先说画面主体是谁/是什么）；emotion_tags 情绪标签；scene_tags 场景标签；"
    "persona_hint 是**画面主体（主角）**的角色归属：仅当某个角色是图片主体时"
    "写其名字（例如守岸人）；主体是别的角色时写那个角色的名字——即使守岸人只是"
    "背景、角落出现或客串，也不要写她；没有角色主体或判不出主体填 common；"
    "nsfw_score 0.0~1.0。只返回JSON，不要有其他文字。"
)

_EXT_BY_CONTENT_TYPE = {
    "image/gif": "gif",
    "image/webp": "webp",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}
_URL_EXT_RE = re.compile(r"\.(gif|webp|png|jpe?g)(?:$|[?#])", re.IGNORECASE)

# 后台打标任务登记表：持有引用防止被 GC，done 回调负责收割异常。
_VLM_TASKS: set[asyncio.Task[None]] = set()


def _spawn_vlm_task(store: Any, config: Any, md5: str, image_bytes: bytes) -> None:
    try:
        task = asyncio.create_task(_tag_with_vlm(store, config, md5, image_bytes))
    except RuntimeError:
        return
    _VLM_TASKS.add(task)

    def _on_done(done: asyncio.Task[None]) -> None:
        _VLM_TASKS.discard(done)
        if done.cancelled():
            return
        # _tag_with_vlm 内部已捕获异常，这里只做兜底收割，避免未检索异常。
        done.exception()

    task.add_done_callback(_on_done)


def _segment_urls(message_segments: list[Any]) -> list[str]:
    urls: list[str] = []
    # B 线 2026-09-16「把所有表情贴纸存下来」：除 image 外收 mface（QQ 商城
    # 表情/贴纸，SnowLuma 段带 url）与 sticker；这些段与普通图片同走下载、
    # MD5 去重、VLM 打标入库，理解面与发送面因此共用同一个表情库。
    accepted_types = {"image", "mface", "sticker"}
    for segment in message_segments or []:
        segment_type = getattr(segment, "type", None)
        if isinstance(segment, dict):
            segment_type = segment.get("type")
        data = getattr(segment, "data", None)
        if isinstance(segment, dict):
            data = segment.get("data", {})
        if (
            str(segment_type or "").strip().lower() not in accepted_types
            or not isinstance(data, dict)
        ):
            continue
        url = str(data.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


async def _download_once(url: str, *, max_bytes: int, proxy: str) -> tuple[bytes, str] | None:
    """取一张图的字节：SSRF 咽喉做「入口 + 每一跳落点」双查（审计 U1-15）。

    与咽喉正例的一致性：URL 由群消息段诱发（任意群成员可发），比归档侧更宽松，
    因此这里取 ``media_archive._GuardedRedirectHandler`` 的**逐跳、发请求前**复查
    形态，而非 ``notes``/``eat`` 的 ``geturl`` 事后复查——手动逐跳（不让 httpx
    自动跟随），每一跳在发出请求之前过同一个 ``check_download_url``。
    校验逻辑一份不造：咽喉调用点在本函数内唯一，入口与落点共用。

    返回形态不变（``None`` = 这张不收）：拒绝不新增异常类型、不静默吞——
    在抛出点 WARNING 留痕（URL 过既有脱敏），单张失败不拖垮整条收库。

    B1 守卫波（2026-09-28）：字节收齐后先过**文件头魔数验真**
    （``image_guard.header_is_image``，内容质检唯一真身）——content-type 说
    ``image/png`` 而字节头对不上登记签名的假图（HTML 改名 .png 这类）在这一步
    就按「这张不收」弃掉，绝不入库、绝不出站。体积/像素下限不在这里（那两把尺
    是配置键，由调用方 ``absorb_event_images`` 读 Config 后现量），空载荷同弃。
    """
    import httpx

    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(12.0, connect=8.0),
        # 逐跳复查见下方循环：绝不把跳转交给客户端自动完成。
        "follow_redirects": False,
        "headers": {"User-Agent": "Mozilla/5.0"},
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    target = url
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            for hop in range(_MAX_REDIRECT_HOPS + 1):
                check_download_url(target)
                async with client.stream("GET", target) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = str(response.headers.get("location") or "").strip()
                        if not location or hop >= _MAX_REDIRECT_HOPS:
                            return None
                        # 相对 Location 按当前跳解析，再交下一轮循环复查落点。
                        target = str(httpx.URL(target).join(location))
                        continue
                    if response.status_code != 200:
                        return None
                    content_type = response.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            return None
                        chunks.append(chunk)
                    if not chunks:
                        return None
                    payload = b"".join(chunks)
                    if not image_guard.header_is_image(payload[:12]):
                        # 假图不进库（B1 守卫波，判据见 image_guard 唯一真身）。
                        return None
                    return payload, content_type
            return None
    except RejectedUrlError as exc:
        # 审查 F-06 同构口径：拒绝信号在抛出点留痕（重定向落点才是真实攻击面），
        # 按「这张取不到」返回，不中断同批其余条目。
        logger.warning(
            "meme library SSRF guard rejected url: %s (url=%s)",
            exc,
            redact_local_secrets(target),
        )
        return None
    except Exception:  # noqa: BLE001 - 下载异常静默返回 None。
        return None


def _pick_vision_entry(
    entries: dict[str, dict[str, Any]],
    *,
    preset_name: str,
    allow_fallback: bool,
) -> dict[str, Any] | None:
    """从「已展平、已筛掉缺 model/base_url」的条目里挑一枚：同组按 priority 最小者。

    组名匹配的是 ``#`` **之前**的那段（真身把列表形态展平成 ``组名#序号``），
    所以 ``myvlm`` 能命中 ``myvlm#1/#2/#3``；展平形态与筛选规则都不在这里重做。
    """
    if not entries:
        return None

    def group_of(entry_id: str) -> str:
        return str(entry_id).split("#", 1)[0]

    def rank(entry_id: str) -> tuple[float, str]:
        try:
            priority = float(entries[entry_id].get("priority", 100))
        except (TypeError, ValueError):
            priority = 100.0
        return (priority, str(entry_id))

    pool = list(entries)
    if preset_name:
        named = [entry_id for entry_id in pool if group_of(entry_id) == preset_name]
        if named:
            return entries[min(named, key=rank)]
    if not allow_fallback or not pool:
        return None
    return entries[min(pool, key=rank)]


def _resolve_vision_config(config: Any) -> dict[str, str]:
    """识图模型预制接口：注册表优先（形态交中央件判），兼容旧三字段；api_key 支持 env:VAR。

    **为什么不在这件里读注册表的结构**：`BOT_VISION_MODEL_REGISTRY` 的合法形态有
    两种——``组名 -> 单条目`` 与 ``组名 -> 条目列表``（生产 ``.env`` 用的是后者：
    ``{"myvlm":[{...},{...},{...}]}``）。「把注册表展平成条目并按 model/base_url
    齐不齐筛掉」这件事在本仓的唯一真身是
    ``domains/media/ingest/vision_describe.py::_flatten_vision_entries``（识图主链
    就走它）。本件此前自己按 dict 形态 ``registry.get(name)`` 读 ⇒ **读的是第二种
    形态、判的是第一种**：生产注册表里明明有可用的视觉组，取回来却是 list，
    ``isinstance(entry, dict)`` 恒 False ⇒ 兜底整个是空操作 ⇒ ``model/base_url``
    双空 ⇒ :func:`_tag_with_vlm` 第一轮就 ``return``。表现是「库里有图但都像随机」
    而不是报错——与「配置键在册却无人读」同型的静默死路。现改为**只在真身之上选组**。

    预设名落空时退到注册表里**真实存在、priority 最小的一条**
    （``bot_meme_library_vlm_fallback_first_preset`` 缺省开；为什么必须有：现网
    ``BOT_MEME_LIBRARY_VLM_PRESET`` 是空串，而注册表里只有 ``myvlm`` 一组）。
    诚实边界：注册表真为空 / 全组都缺端点时照旧不打标（不猜端点、不造第二份默认值）。
    """
    import os

    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        # 有意引私有名：这是「注册表形态」的唯一真身，复制它=立刻产生第二真身，
        # 而它没有公共别名。把它升成公共口归该域 owner（见交接 §5）。
        _flatten_vision_entries,
    )

    preset_name = str(getattr(config, "bot_meme_library_vlm_preset", "deepseek-vision") or "").strip()
    registry = getattr(config, "bot_vision_model_registry", None) or {}
    entries = _flatten_vision_entries(registry, resolve_key=True, config=config)
    preset = _pick_vision_entry(
        entries,
        preset_name=preset_name,
        allow_fallback=bool(getattr(config, "bot_meme_library_vlm_fallback_first_preset", True)),
    )
    model = str((preset or {}).get("model") or getattr(config, "bot_meme_library_vlm_model", "") or "")
    base_url = str((preset or {}).get("base_url") or getattr(config, "bot_meme_library_vlm_base_url", "") or "").rstrip("/")
    api_key = str((preset or {}).get("api_key") or getattr(config, "bot_meme_library_vlm_api_key", "") or "")
    if api_key.startswith("env:"):
        api_key = os.environ.get(api_key[4:].strip(), "")
    return {"model": model, "base_url": base_url, "api_key": api_key}


#: 打标请求的 token 地板（S-VLM-FAILOVER，2026-09-28 现算）：注册表里两条腿是
#: reasoning 模型，旧值 300 档实测 ``content`` 恒空（全文进 ``reasoning_content``，
#: 现网 GLM-4.6V-Flash 605 字 / deepseek-v4-flash-vision-exp 1267 字）⇒ JSON 抽不
#: 出来 ⇒ **兜底腿即使被问到也形同不存在**。600 是实测下限，1200 留裕度。
_VLM_TAG_MAX_TOKENS = 1200

#: 永久失败档：与 ``chat_reply/llm_engine/providers.py::_classify_http_error`` 的
#: ``auth`` 档同口径（401/403）。现网那发 403 的响应体是
#: ``insufficient_user_quota，剩余额度 ￥-0.006180``——换模型名、重试都无用，只有
#: 充值/换 key 才解 ⇒ 逐张重烧纯属空烧（09-28 一轮烧了 20 发）。漂移由
#: ``tests/test_meme_vlm_roster_failover.py`` 的派生覆盖锁拦，不在这里再造分类器。
_VLM_PERMANENT_STATUSES = frozenset({401, 403})

#: 本进程已判死的端点（entry_id）：只增不减，重启重新现算——欠费恢复后第一轮就复活。
_vlm_dead_entry_ids: set[str] = set()


def _vision_candidates(config: Any) -> list[dict[str, str]]:
    """打标道的可用视觉端点名册，按 priority 升序，且首枚恒为 `_resolve_vision_config` 的选择。

    补的洞（S-VLM-FAILOVER）：这条道此前只取**一枚**条目，失败即 ``return``，
    从不问下一条——而同一张注册表在识图主链
    ``domains/media/ingest/vision_describe.py::DynamicVisionProvider.generate``
    里是「按 priority 轮转最多 3 条」的。两种吃法对同一张册，后果就是 09-28 现网：
    钱包欠费的 p1 把整轮 20 发真实调用烧光（``all-failed 清空 0/尝试 20``），
    而册中第三条腿一次都没被问过。本件把这条道接回「问尽名册」的口径。

    口径边界（为什么不另立一把尺子）：
    - 展平形态、``env:`` 解析、缺 model/base_url 的筛除——**全部**交中央真身
      ``_flatten_vision_entries``（同 `_resolve_vision_config` 引它的理由，见其注）；
    - 首枚仍由 `_resolve_vision_config` 定（预制名 / 旧三字段兜底 / 落空退第一条
      的既有语义一律不动，测试替身也仍桩在它身上），本件只在其**之后**补上
      册中其余的腿，并把与首枚同 (model, base_url) 的那条挪到最前，不重排其余；
    - 真身为空或抛错 ⇒ 退化为「只看首枚」，与改动前同形（宁缺不猜端点）。
    """
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        _flatten_vision_entries,
    )

    ordered: list[dict[str, str]] = []
    registry = getattr(config, "bot_vision_model_registry", None) or {}
    try:
        entries = _flatten_vision_entries(registry, resolve_key=True, config=config)
    except Exception as exc:  # noqa: BLE001 - 读不动中央展平器就退回单腿，绝不带崩打标。
        logger.debug("meme vlm roster flatten failed type=%s", type(exc).__name__)
        entries = {}

    def _rank(item: tuple[str, dict[str, Any]]) -> tuple[float, str]:
        try:
            priority = float(item[1].get("priority", 100))
        except (TypeError, ValueError):
            priority = 100.0
        return (priority, item[0])

    for entry_id, entry in sorted(entries.items(), key=_rank):
        model = str(entry.get("model") or "").strip()
        base_url = str(entry.get("base_url") or "").strip().rstrip("/")
        if not model or not base_url:
            continue  # 真身已筛过一次，这里只兜「字段被塞了空白」的病态值。
        ordered.append(
            {
                "entry_id": str(entry_id),
                "model": model,
                "base_url": base_url,
                "api_key": str(entry.get("api_key") or ""),
            }
        )

    head = _resolve_vision_config(config)
    if not (head["model"] and head["base_url"]):
        return ordered
    matched = next(
        (
            index
            for index, candidate in enumerate(ordered)
            if (candidate["model"], candidate["base_url"])
            == (str(head["model"]).strip(), str(head["base_url"]).strip().rstrip("/"))
        ),
        None,
    )
    if matched is None:
        ordered.insert(
            0,
            {
                "entry_id": f"legacy#{head['model']}",
                "model": str(head["model"]),
                "base_url": str(head["base_url"]),
                "api_key": str(head["api_key"]),
            },
        )
    elif matched > 0:
        ordered.insert(0, ordered.pop(matched))
    return ordered


def _quarantine_ledger(store: Any, config: Any) -> Any:
    """内容级隔离墓碑账本：与发送史同库（表情库 db 同目录），拿不到就返回 None。

    ``None`` 只影响「同图重发不复活」这一层（退化为旧行为），绝不因此把整张图
    拒收或把打标带走——增益层不许反噬主链路。
    """
    try:
        from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
            MemeQuarantineLedger,
        )

        db_path = getattr(store, "db_path", None)
        if not db_path:
            return None
        return MemeQuarantineLedger(Path(db_path).parent / "meme_send_history.sqlite3")
    except Exception:  # noqa: BLE001 - 账本不可用诚实降级。
        return None


#: 「永久重启形」两枚总闸（settings.py::RESTART_REQUIRED_KEYS 在册名单登记过：
#: 调用点交的是装配期 plugin Config 原件、不过合并层 ⇒ 运行时覆盖写进 store
#: 也永远到不了执法现场）：env 键 → 装配 Config 字段名。
_RESTART_FORM_KEYS: tuple[tuple[str, str], ...] = (
    ("BOT_MEME_LIBRARY_VLM_ENABLED", "bot_meme_library_vlm_enabled"),
    ("BOT_MEME_LIBRARY_ENABLED", "bot_meme_library_enabled"),
)

#: 本进程是否已查过/点名过「在册未执法」（每键至多一查、至多一行，别刷屏；
#: 重启进程重新来过）。
_restart_gaps_attempted: set[str] = set()
_restart_gaps_announced: set[str] = set()


def _build_runtime_settings_store(config: Any) -> Any:
    """运行时设置 store 真身在 chat_reply 域——本件**只读不写**、不改其名册。

    与 ``shorekeeper_absorb`` 引中央别名口同构：跨域只读取数，不在表情库侧
    自建第二份覆盖存储。独立成一层壳是为了测试可注入替身、且失败口径统一。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
        build_runtime_settings_store,
    )

    return build_runtime_settings_store(config)


def _override_truthy(value: Any) -> bool:
    """覆盖值判真：口径对齐 settings.py 的 ``_bool_converter`` 真值档。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "开", "是"}


def _log_restart_required_gaps(config: Any) -> None:
    """「在册未执法」可见性：运行时覆盖为 true 而装配装载为 false ⇒ 说破需重启。

    立票缘由（S-VLM-OBS，2026-09-27）：这两枚闸按 ``set`` 翻 true 后，控制面
    读视图与台账都显示"已开"，但执法现场（本 listener）拿的是装配期 Config
    原件 ⇒ 链子一寸都没动，日志里也一个字都没有——与台账「键在册却无人读」
    同型的假绿，只是这次"册"是覆盖库。现按键各点名一次（进程级去重）：

    ``meme switch BOT_MEME_LIBRARY_VLM_ENABLED 配置在册为 true、本进程装载为 false（需重启）``

    诚实边界：①"在册"信号只认运行时覆盖 store 里**真实存在**的 true——库代码
    不读 .env 文件（eat.py:287 先例：运行时读 .env 会把生产开关泄进测试进程），
    所以"改了 .env 没重启"这一型仍由装配面负责（本报告移交装配席）；
    ②store 读不到/抛异常 ⇒ 整段哑火，绝不影响打标主链（增益层不反噬）；
    ③ 装载为 true 的一侧本来就执法，无话可说。
    """
    for env_key, field_name in _RESTART_FORM_KEYS:
        if env_key in _restart_gaps_attempted:
            continue
        if bool(getattr(config, field_name, False)):
            continue  # 装载即执法 ⇒ 无"未执法"可报（也免去覆盖库读）。
        _restart_gaps_attempted.add(env_key)  # 每键至多一查：读崩也不许每条消息重开 store。
        try:
            roster = _build_runtime_settings_store(config).get(env_key, config)
        except Exception:  # noqa: BLE001 - 覆盖读不动就闭嘴；本进程不再重试。
            return
        # store.get 无覆盖时回退装配值（=false），那不算"在册"；只有覆盖真为 true 才点名。
        if _override_truthy(roster):
            _restart_gaps_announced.add(env_key)
            logger.warning(
                "meme switch %s 配置在册为 true、本进程装载为 false（需重启：永久重启形键，运行时覆盖到不了装配期 Config）",
                env_key,
            )


async def _tag_with_vlm(store: Any, config: Any, md5: str, image_bytes: bytes) -> Any:
    """异步打标（失败可继续，但**不静默**）：更新描述/标签/NSFW 与权重；高危 NSFW 删除并立墓碑。

    四种服务层失败形态（HTTP 非 200 / 请求异常 / 无 JSON / JSON 解析炸）各留一行
    可归因 WARNING（S-VLM-OBS，2026-09-27，修法票 V-1..V-4）。留痕红线与台账 #59
    KQ-7 前半同口径：**只记类型/状态码/长度/md5/模型名**——绝不记正文、Bearer、
    URL query、api_key；异常一律只取 ``type(exc).__name__``（异常文本可能携带
    端点 URL 与凭据）。参照正例：根装配 ``meme_backfill_failed`` 那条留痕。
    """
    import httpx

    candidates = _vision_candidates(config)
    # 视觉打标使用与聊天相同的 OpenAI-compatible 直连接口。
    # 表情库识图仅在显式配置有效端点时运行；空配置保持静默。
    if not candidates:
        return
    live = [item for item in candidates if item["entry_id"] not in _vlm_dead_entry_ids]
    if not live:
        # 全册都被永久档判死 ⇒ 这张连问都不问（09-28 现网就是对着欠费钱包把
        # 一整批 20 发烧光的）。留痕一字不改地交回 backfill 那侧点名收轮。
        return
    data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
    content: str = ""
    reached_any = False
    for candidate in live:
        if candidate["entry_id"] in _vlm_dead_entry_ids:
            # 片内并发时，同批另几张可能刚把这枚腿判死 ⇒ 逐条复查，别再问一遍。
            continue
        model = candidate["model"]
        base_url = candidate["base_url"]
        api_key = candidate["api_key"]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TAG_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": _VLM_TAG_MAX_TOKENS,
        }
        try:
            async with httpx.AsyncClient(timeout=float(getattr(config, "bot_meme_library_vlm_timeout_seconds", 20) or 20)) as client:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if response.status_code != 200:
                    # V-1（L4）：服务层非 200（401/404/5xx…）与「开关关」此前不可分辨。
                    # 只记状态码与模型名——响应体可能回显凭据/URL，一律不入日志。
                    # S-VLM-FAILOVER：永久档（auth＝401/403，多为欠费/废 key）进熔断
                    # 名册，本进程后续图不再问它；瞬时档（5xx/超时）不入册，下轮照问。
                    if response.status_code in _VLM_PERMANENT_STATUSES:
                        _vlm_dead_entry_ids.add(candidate["entry_id"])
                    logger.warning(
                        "meme vlm http md5=%s status=%s model=%s",
                        md5,
                        response.status_code,
                        model,
                    )
                    continue
                body = response.json()
                content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        except Exception as exc:  # noqa: BLE001 - 放弃本条腿但留痕：异常只取类型名（文本可能含端点 URL/密钥）。
            # V-2（L5）：网络/超时/非 JSON 响应体等全在这一支——此前一发都不留。
            logger.warning("meme vlm request failed md5=%s type=%s", md5, type(exc).__name__)
            continue
        reached_any = True
        break
    if not reached_any:
        # 名册里每条腿都没给出可读应答（各档原因已在上面逐条留痕）。
        # 注：答非 JSON / JSON 解析炸（L6/L7）不在这条轮转里——那是「这张图问不出
        # 标签」而不是「这条腿坏了」，跨端点重问只会把三份成本与三行日志都换来
        # 同一个结论，故维持逐张单问的旧口径。
        return
    match: re.Match[str] | None = None
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            # V-3（L6）：模型答非 JSON（拒答/纯文字）——只记长度，不记原文。
            logger.warning(
                "meme vlm unparseable md5=%s content_len=%d model=%s",
                md5,
                len(str(content or "")),
                model,
            )
            return None
        tags = json.loads(match.group(0))
    except Exception as exc:  # noqa: BLE001 - 打标返回不可解析按放弃本张处理，留痕只记类型/长度。
        # V-4（L7）：有 {…} 形状但 json.loads 炸（截断/尾逗号等）——与 L6 分档归因。
        logger.warning(
            "meme vlm json error md5=%s type=%s raw_len=%d",
            md5,
            type(exc).__name__,
            len(match.group(0)) if match else len(str(content or "")),
        )
        return None
    from plugins.bot_unified_runtime.domains.meme.sources import shorekeeper_absorb

    delete_threshold = float(getattr(config, "bot_meme_library_nsfw_delete", 0.8) or 0.8)
    decision = shorekeeper_absorb.apply_tagged_outcome(
        store=store,
        ledger=_quarantine_ledger(store, config),
        md5=md5,
        content_sha256_value=shorekeeper_absorb.content_sha256(image_bytes),
        tags=tags if isinstance(tags, dict) else {},
        nsfw_delete=delete_threshold,
        persona_terms=shorekeeper_absorb.persona_subject_terms(config),
        persona_absorb_enabled=bool(
            getattr(config, "bot_meme_shorekeeper_absorb_enabled", True)
        ),
    )
    # 「不标」不是静默事：三种真因（主体是别人/判不出/开关关）随结论代号进日志，
    # 事后能回答「这张为什么没成她的收藏」。只记 md5 与代号——不记描述原文、
    # 不记用户内容（出站打码红线在入库侧同样成立）。
    logger.info(
        "meme absorb outcome md5=%s action=%s persona_owned=%s audit=%s",
        md5,
        decision.action,
        decision.persona_owned,
        ",".join(decision.audit),
    )
    return decision


async def _backfill_one(store: Any, config: Any, row: Any) -> str:
    """补标的单张工序：返回 ``skip``（没发请求）/``fail``（发了没成）/``ok``（补上了）。

    拆出来只为了给 ``backfill_meme_tags`` 的分片并发当单元；单张语义逐字不变——
    读盘失败/文件不在盘＝``skip``（不计入 attempted，也不许冒充"处理过"，L9 留痕），
    只有走通 ``apply_tagged_outcome`` 才算 ``ok``。
    """
    before = str(row.get("md5", ""))
    path = store._resolve_media_path(row.get("path", ""))
    try:
        if not path.is_file():
            # L9 留痕：文件不在盘 = 用户导入的源图丢了，静默跳过会让这批图
            # 永远"待标"却没人说为什么。只记 md5（路径可能含用户目录名，不记）。
            logger.warning("meme backfill skip missing file md5=%s", before)
            return "skip"
        image_bytes = path.read_bytes()
    except OSError as exc:
        logger.warning(
            "meme backfill skip read failed md5=%s type=%s", before, type(exc).__name__
        )
        return "skip"
    if not image_bytes:
        return "skip"
    decision = await _tag_with_vlm(store, config, before, image_bytes)
    return "ok" if decision is not None else "fail"


async def backfill_meme_tags(
    store: Any, config: Any, *, limit: int = 20, concurrency: int = 3
) -> int:
    """启动补标：给描述为空的图库图补 VLM 打标（用户导入表情包场景）。

    每轮最多 limit 张防打爆；逐张读文件 → 复用 _tag_with_vlm（含 NSFW
    删除语义）。**返回值口径（S-VLM-OBS，修法票 V-5）：本轮打标成功张数**
    （``_tag_with_vlm`` 走通到 ``apply_tagged_outcome`` 才算成功），不再是尝试
    张数——旧口径把失败也计成"处理过"，于是**全失败轮表现与"清空"完全一样**
    （L13）：循环按尝试数判"还剩没剩"，同一批打不标的图每 10 分钟重烧一发真实
    视觉调用，而日志里一个字都没有。现每轮 ``attempted``/``tagged`` 两个数都
    进日志；全失败轮额外点名「清空 0/尝试 N」。未配置视觉端点/开关关时直接
    返回 0（开关关另有 _log_restart_required_gaps 的在册可见性）。

    **开关归属（S-T-STK-2，2026-09-26 现算实锤）**：本函数此前只看「端点能不能
    解析」，不吃 ``bot_meme_library_vlm_enabled``——而它唯一的调用方（根装配 on_
    bot_connect 注册的 ``backfill_meme_tags_loop``）又只被 ``bot_meme_library_enabled``
    门控。goal-12 修好注册表形态解析（F-1）之后，这条补标道在**总开关关着**的
    现网真实跑起来了（盘上 description 计数以约每张/分钟内递增、SQLite 只读复核）。
    「开关关而路在跑」＝台账里那族最贵的假绿反例，且每补一张=一发真实视觉调用
    （花费与 NSFW 自动删除权都在她那句「开关在她手」的裁定里）。现把开关补成
    本函数的第一道门：**关 ⇒ 直接 0 张**，循环拿到 0<batch 自然收束。开不起打标
    不再是缺省态的副作用；她要开，就开 BOT_MEME_LIBRARY_VLM_ENABLED（零新键、
    不改任何缺省值）。
    """
    if not bool(getattr(config, "bot_meme_library_vlm_enabled", False)):
        return 0
    candidates = _vision_candidates(config)
    if not candidates:
        return 0
    try:
        pending = store.list_untagged(limit=limit)
    except Exception as exc:  # noqa: BLE001 - 队列查询失败按无待标处理，但**不留白**：这轮返回 0 是"查不动"不是"清空了"。
        logger.warning("meme backfill list_untagged failed type=%s", type(exc).__name__)
        return 0
    attempted = 0
    tagged_ok = 0
    # 提速（S-VLM-SPEED，2026-09-28 实测）：一发打标 7–19s（均值 ~13s，随图体积涨），
    # 旧形态「串行 20 张 + 睡 600s」⇒ 约 84 张/小时，现网 7423 张待标要排 ~88 小时。
    # 瓶颈是延迟不是批量，所以按分片并发跑：每片至多 concurrency 张同时问，片间复查熔断。
    # 为什么必须分片而不是整批 gather：整批会在第一条腿被判永久死的瞬间把剩下的
    # 待发全部烧出去——那正是 S-VLM-FAILOVER 刚堵掉的空烧。
    chunk_size = max(1, int(concurrency))
    for offset in range(0, len(pending), chunk_size):
        chunk = pending[offset : offset + chunk_size]
        outcomes = await asyncio.gather(
            *(_backfill_one(store, config, row) for row in chunk),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                # 分片内炸穿（结构性故障，非单张失败）：留痕后停止本轮，交上层按旧口径收束。
                logger.warning("meme backfill chunk task failed type=%s", type(outcome).__name__)
                continue
            if outcome == "skip":
                continue
            attempted += 1
            if outcome == "ok":
                tagged_ok += 1
        if candidates and all(item["entry_id"] in _vlm_dead_entry_ids for item in candidates):
            # 收轮点名（S-VLM-FAILOVER）：整册都被永久档判死时，剩余待标图继续问
            # 只会把「一张都没补上」重演 N 遍——09-28 现网就是这么烧的 20 发。
            # 这一行必须与「清空 0/尝试 N」长得不一样：前者是端点坏了要人看一眼，
            # 后者是图库真的没货。
            logger.warning(
                "meme backfill round aborted：视觉端点全部永久失败（%d/%d 已熔断），"
                "本轮剩余 %d 张不再重烧——属欠费/鉴权档，重试无用，得有人看一眼",
                len(candidates),
                len(candidates),
                max(0, len(pending) - attempted),
            )
            break
    logger.info("meme backfill round attempted=%d tagged=%d", attempted, tagged_ok)
    if attempted and not tagged_ok:
        # 全失败轮不许长得像"清空"：点名给巡检/人看，逐张原因见上方 meme vlm 留痕。
        logger.warning(
            "meme backfill round all-failed 清空 0/尝试 %d（一张都没补上，逐张原因见 meme vlm 留痕）",
            attempted,
        )
    return tagged_ok


async def backfill_meme_tags_loop(
    store: Any,
    config: Any,
    *,
    batch: int = 40,
    interval_seconds: float = 60.0,
    concurrency: int = 2,
    max_rounds: int = 200,
) -> None:
    """周期补标循环：直到图库无待标图为止（每批 batch 张，片内并发 concurrency 张）。

    防打爆设计：批间休眠 + 片内有限并发；视觉端点未配置时立即退出。
    缺省值提速（S-VLM-SPEED，2026-09-28 实测）：旧「batch=20 / 睡 600s / 全串行」
    在 7–19s 的单张延迟下只有 ~84 张/小时，现网 7423 张要 ~88 小时；现
    并发档回落（2026-09-28 串行复测实锤）：免费 GLM 腿**单发串行**都吃 429——智谱回
    `code 1305 该模型当前访问量过大`（模型级拥塞）与 `code 1302 账户已达速率限制`，8 发
    里 4 发失败。故「batch=100 / 4 并发」这个曾以为的提速档实际是 429 制造机，现回落到
    「batch=40 / 睡 60s / 2 并发」，圈数上限抬到 200 保排空。429 属瞬时档不进熔断，
    下一轮照问。并发是**有界**的：
    免费视觉档撞速率限流时回 429，属瞬时档（不进熔断名册），下一片/下一轮照问。
    **退出判据（S-VLM-SPEED 改，2026-09-28 16:3x 现算）：有进展就续跑，零进展才收。**
    旧判据是「整批 batch 张全部补标成功才继续」（V-5，为了堵当时那条"全失败轮也能
    凑满 batch ⇒ 无限重烧"）。熔断与诚实计数都已就位后，这条判据反过来咬人：
    现网 batch=60 时任何一张偶发失败（速率限流/单张超时/NSFW 删除）都会让整轮
    提前收摊 ⇒ 实测 10 小时只补了 139 张。V-5 要防的"零进展空烧"现在由两处专门挡：
    ``tagged_ok == 0``（本轮一张没补上，含队列查不动）与熔断收轮时
    ``backfill_meme_tags`` 返回的 0 —— 都在下面这一句里收。
    """
    # 域内启动可见性：这两枚总闸是永久重启形（settings.py::RESTART_REQUIRED_KEYS
    # 在册名单 596-629），运行时覆盖到不了装配期 Config——「配置在册 true、
    # 本进程装载 false」必须在这一行日志里说破，不许演成"什么都没发生"。
    _log_restart_required_gaps(config)
    if not _vision_candidates(config):
        return
    rounds = 0
    while True:
        rounds += 1
        if rounds > max_rounds:
            # 有界护栏（本判据改配套）：「有进展就续圈」把收束寄托在队列真的缩短上，
            # 而队列是否缩短由落库决定。一旦出现「本轮报成功、下一轮同一张又回来」
            # （落库半通、description 仍空之类），零进展判据永远等不到 ⇒ 无限重烧真实
            # 视觉调用。V-5 当年防的是这个，这里用圈数上限继续防它，且**留痕说破**，
            # 不许静默收摊。
            logger.warning(
                "meme backfill loop 收束于圈数上限 %d（末轮 attempted/tagged 见上一行）——"
                "若队列仍有货，说明有图反复报成功却没落库，得有人看一眼",
                max_rounds,
            )
            return
        try:
            tagged_ok = await backfill_meme_tags(
                store, config, limit=batch, concurrency=concurrency
            )
        except Exception:  # noqa: BLE001 - 循环体异常不外泄（单张异常已被吃掉，走到这是结构性故障）。
            return
        if tagged_ok == 0:
            # 零进展＝（大概率）队列已清空，或本轮一张都没补上——两种都已在
            # backfill_meme_tags 里各自点名（attempted/tagged 行、all-failed 行、熔断收轮行）。
            return
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return


def _absorb_size_guard_reason(
    image_bytes: bytes, *, min_bytes: int, min_side: int
) -> str:
    """收库下限守卫：返回空串=放行，非空=拒绝代号（进 ``skipped`` 观测账）。

    判据口径与 randpic 池子守卫同源（``domains/media/image_guard.py`` 唯一真身）：

    - 空字节流＝拒（无条件；``_download_once`` 真路已先拦，这里防替换桩/旁路）；
    - ``min_bytes``/``min_side`` **任一 > 0 才启用**内容判定，0 = 关 = B1 前
      逐字节同形（离线桩 config 读不到键即落此态）；
    - 启用时**再过文件头魔数闸**（``guard_not_image_magic``）：真路里
      ``_download_once`` 已经拦过一次，这里再拦一道是防「下载口被替换桩/未来旁路」
      绕过（假 .png/HTML 改名件绝不入库）；短边用 PIL 解图头判定，**解不开按坏件拒**
      （``guard_undecodable``）——只剩「截断/损坏」一种解释，发出去就是坏件，不收。
    """
    if not image_bytes:
        return "guard_empty_payload"
    if min_bytes <= 0 and min_side <= 0:
        return ""
    if min_bytes > 0 and len(image_bytes) < min_bytes:
        return "guard_below_min_bytes"
    if not image_guard.header_is_image(image_bytes[:12]):
        return "guard_not_image_magic"
    if min_side > 0:
        side = image_guard.min_side_of_bytes(image_bytes)
        if side is None:
            return "guard_undecodable"
        if side < min_side:
            return "guard_below_min_side"
    return ""


async def absorb_event_images(bot: Any, event: Any, config: Any, store: Any) -> dict[str, Any]:
    """监听事件中的图片：异步下载、MD5 去重、入库、可选打标。"""
    enabled = bool(getattr(config, "bot_meme_library_enabled", False))
    if not enabled:
        return {"handled": False, "reason": "disabled"}
    session_id = str(getattr(event, "get_session_id", lambda: "")() or "")
    if "group" not in session_id:
        return {"handled": False, "reason": "not_group"}
    group_id = str(getattr(event, "group_id", "") or "")
    allowlist = [str(item) for item in (getattr(config, "bot_meme_library_group_allowlist", []) or [])]
    denylist = [str(item) for item in (getattr(config, "bot_meme_library_group_denylist", []) or [])]
    if denylist and group_id in denylist:
        return {"handled": False, "reason": "group_denied"}
    if allowlist and group_id not in allowlist:
        return {"handled": False, "reason": "group_not_allowed"}

    try:
        segments = list(event.get_message())
    except Exception:  # noqa: BLE001 - 消息提取失败按无图片处理。
        segments = []
    urls = _segment_urls(segments)
    if not urls:
        return {"handled": False, "reason": "no_image"}

    target_dir = Path(str(getattr(config, "bot_meme_library_dir", "data/meme_library") or ""))
    max_bytes = int(getattr(config, "bot_meme_library_max_file_bytes", 5242880) or 5242880)
    proxy = str(getattr(config, "bot_meme_library_proxy", "") or "")
    # ---- B1 收库内容守卫（2026-09-28）：下限两把尺读 Config，0 = 关 ----
    # 「把所有表情贴纸存下来」mandate 的字面意图收窄为**真贴纸**：截图尺寸的
    # 大图照收，1KB 图标/缩略图拒收（先例 eat.py 短边 300 与 randpic 池子守卫）。
    # 读不到配置键（离线桩 config、装配期外裸调用）回 0 = 关，旧行为逐字节同形。
    min_bytes = int(getattr(config, "bot_meme_library_min_file_kb", 0) or 0) * 1024
    min_side = int(getattr(config, "bot_meme_library_min_side", 0) or 0)

    saved = 0
    downloaded: list[tuple[str, str, bytes]] = []  # (md5, ext, image_bytes)
    skipped: list[str] = []
    for url in urls[:4]:
        result = await _download_once(url, max_bytes=max_bytes, proxy=proxy)
        if not result:
            continue
        image_bytes, content_type = result
        guard_reason = _absorb_size_guard_reason(
            image_bytes, min_bytes=min_bytes, min_side=min_side
        )
        if guard_reason:
            # 与墓碑/去重同一本 skipped 账（返回值观测位），代号 guard_* 分家。
            skipped.append(guard_reason)
            continue
        md5 = hashlib.md5(image_bytes).hexdigest()
        ext = _EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
        if not ext:
            match = _URL_EXT_RE.search(url)
            ext = (match.group(1) if match else "png").lower()
        downloaded.append((md5, ext, image_bytes))

    def _admit() -> list[tuple[str, str, bytes]]:
        """准入判定整段离环跑：sha256(全图字节) + 墓碑查 + ``store.exists`` 都是同步 IO。

        顺序不变（**落盘之前**先判：墓碑优先、其次内容去重；被隔离过的图不写盘、
        不入库、不打标——写盘后再删会留一次可观测的 IO 抖动，也更难解释）。
        变只有一处：这一段从前在事件循环上跑（本函数其余的写盘/裁剪都已 ``to_thread``），
        于是每张图最坏 5MB 的哈希 + 两次 SQLite 读（含墓碑库首次建表的
        ``executescript``）**压在 bot 的主循环上**——群聊连发四张图就是四次串行阻塞，
        与「吸收/下载绝不占事件循环」这条硬约束相抵。放线程池里做，判定语义逐字不变。
        """
        ledger = _quarantine_ledger(store, config)
        admitted: list[tuple[str, str, bytes]] = []
        for md5, ext, image_bytes in downloaded:
            intake = shorekeeper_absorb.decide_intake(
                store=store, ledger=ledger, md5=md5, data=image_bytes
            )
            if intake.action != "accepted":
                skipped.append(intake.action)
                continue
            admitted.append((md5, ext, image_bytes))
        return admitted

    pending: list[tuple[str, str, bytes]] = await asyncio.to_thread(_admit) if downloaded else []
    if pending:

        def _persist() -> list[tuple[str, bytes]]:
            # 写盘 + SQLite 入库是同步 IO，挪到线程池避免占用事件循环。
            # 目录创建也在这一段的线程里：它同样是文件系统写。
            target_dir.mkdir(parents=True, exist_ok=True)
            saved_items: list[tuple[str, bytes]] = []
            for md5, ext, image_bytes in pending:
                if store.exists(md5):
                    continue
                path = target_dir / f"{md5}.{ext}"
                try:
                    path.write_bytes(image_bytes)
                except OSError:
                    continue
                store.add(
                    md5=md5,
                    path=str(path),
                    ext=ext,
                    group_id=group_id,
                    content_sha256=shorekeeper_absorb.content_sha256(image_bytes),
                )
                saved_items.append((md5, image_bytes))
            return saved_items

        saved_items = await asyncio.to_thread(_persist)
        saved = len(saved_items)
        if getattr(config, "bot_meme_library_vlm_enabled", False):
            for md5, image_bytes in saved_items:
                _spawn_vlm_task(store, config, md5, image_bytes)

    def _cleanup() -> None:
        store.cleanup(
            max_files=int(getattr(config, "bot_meme_library_max_files", 20000) or 0),
            max_age_days=int(getattr(config, "bot_meme_library_max_age_days", 30) or 0),
            protect_persona=bool(
                getattr(config, "bot_meme_shorekeeper_protect_from_prune", True)
            ),
        )
        history = getattr(store, "history", None)
        if history is not None:
            # 发送史只裁「库里已经没有的图」，不裁仍在线的账 ⇒ 反重复不随时间松动。
            try:
                history.prune(live_hashes=store.live_content_hashes())
            except Exception:  # noqa: BLE001, S110 - 裁剪失败不影响收库结果。
                pass

    try:
        await asyncio.to_thread(_cleanup)
    except Exception:  # noqa: BLE001, S110 - 清理失败不影响入库结果。
        pass
    return {"handled": True, "reason": "saved", "saved": saved, "skipped": skipped}
