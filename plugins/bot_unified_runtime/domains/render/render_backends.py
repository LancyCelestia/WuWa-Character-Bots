"""渲染后端接口：HTML→图片、卡片渲染的预留接入点。

- ``RenderBackend`` Protocol：接收结构化卡片 payload，返回图片字节；
  渲染失败必须返回 None（由调用方降级文本），不抛异常。
- ``NullRenderBackend``：默认实现，直接返回 None（文本兜底）。
- ``HtmlKitRenderBackend``：可选实现，依赖 nonebot-plugin-htmlkit /
  Playwright；未安装时自动不可用，不影响主链路。
- ``build_render_backend(name)``：按名字选择；未来可加
  cardimg / PIL / 小程序卡等后端，不改调用方。
- Phase-2 渲染开关（perf-optimization-plan §三.1，缺省=字节级现状）：
  ``BOT_RENDER_MAX_CONCURRENCY``（默认 1=串行）、
  ``BOT_RENDER_WAIT_BUDGET_MS``（默认空/0=不启用）；
  解析链 driver config → 进程 env → 缺省。

后续把游戏 wiki 卡、媒体卡接到 ``render_card`` 时，仍然走
``CapabilityResult -> ReviewResult -> RenderedOutput``，渲染只负责
产图，不决定发送。
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)

# Chromium 的 ORB（Opaque Response Blocking）会对部分图床（实测 wx*.sinaimg.cn：
# 微博配图）的 <img> no-cors 请求直接拦断（net::ERR_BLOCKED_BY_ORB，卡上
# 封面/头像全灰）。对命中名单的请求改走 python 侧取回字节再 fulfill，
# 彻底绕开浏览器网络栈；名单**外**的远程请求不代捞（避免每图双重下载），
# 但**仍被拦截器判定过**（F-3/W4：任意 http(s) 请求建连前过中央咽喉）——
# 「不代捞」≠「不判定」，两件事别混着记（W4 口径对齐）。
# 取回用直连 + curl 形态极简头：新浪图床 WAF 对「浏览器 UA 但缺完整浏览器头
# 的请求」与代理出口 IP 均回 403（实测矩阵：curl 极简头直连/代理皆 200）。
_ORB_PRONE_HOST_SUFFIXES = ("sinaimg.cn", "weibocdn.com")
_ORB_FETCH_HEADERS = {"User-Agent": "curl/8.0.1", "Accept": "*/*"}


def _build_orb_fetch_opener() -> urllib.request.OpenerDirector:
    """ORB 代捞腿的 opener：缺省直连 + **逐跳** SSRF 复查（缺口①，2026-09-30 复原波）。

    两件事各管一件，都不许少：
    - ``ProxyHandler({})``＝强制直连。新浪图床 WAF 对代理出口 IP 回 403
      （实测矩阵：curl 极简头直连 200），这是这条腿存在的前提，不动。
    - 逐跳护栏＝复用链上**唯一**的
      ``link_parse.parsers.http_util._GuardedShortLinkRedirectHandler``。旧装配
      只有代理件，urllib 默认 handler 盲跟 30x：图床（或卡里那枚 ``src=``）
      回一跳 302 就能把 bot 的出站请求送进 127.0.0.1:3001 / 169.254.169.254，
      字节还会经 ``route.fulfill`` 变成像素回显在群卡上。F-3 的 ``_orb_route``
      闸只罩「非 ORB 名单」支，名单内这支此前根本没被判据看过。
      现在每一跳落点在**建连之前**过 ``ssrf_guard.check_fetch_landing``
      （判据仍是中央 ``downloader.check_download_url``，本件不造第二套 URL 判据）；
      跨 host 剥凭证的语义随父类一起继承。
      入口域名不查（名单后缀本就不可能指内网，且避免对图床触发 DNS）——
      这条口径与 F-3 席一致，``_orb_route`` 的行为契约零变化。

    拒绝的外在表现仍旧是「取不到字节」：``_fetch_image_bytes`` 吞异常返回 None
    → ``route.abort`` → 模板 ``onerror`` 灰图兜底，渲染降级链零新增故障面。

    已知残余（本席**裁定维持**，不是待办）：这条腿只钉「落点不许是内网」，未装
    连接层解析钉定件（``downloader.build_pinning_handlers``，装配在册清单见该件
    docstring 与 ``tests/test_downloader_connect_pin.py::test_pinning_assembly_roster_is_the_recorded_one``）。
    取舍理由三条：①本腿首行就是 ``ProxyHandler({})`` 强制直连，装了钉定件也不改变
    「谁去连」，只多一次解析；②命中条件是「主机名以 sinaimg.cn/weibocdn.com 结尾」
    的**固定大厂域**，要 rebinding 得先接管该域 DNS，而入口判定本就未做（下面那条
    口径），钉定单点收益近零；③渲染热路径每图一次解析 + 一次选路，代价压在用户
    可感的出卡延迟上。真要铺开，先改的是解析链咽喉 ``http_util._build_opener``
    （口径/坑见 ``build_pinning_handlers`` 装配面段落 a/b 两条），不是这里。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _GuardedShortLinkRedirectHandler,
    )

    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _GuardedShortLinkRedirectHandler()
    )


_ORB_FETCH_OPENER = _build_orb_fetch_opener()


def _orb_prone_url(url: str) -> bool:
    from urllib.parse import urlsplit

    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _ORB_PRONE_HOST_SUFFIXES)


# 卡面「远程资源引用」的形态真身（单一一份，本模块的注册判据与拦截器共用）。
# W4 扩判据（2026-10-01）：旧尺只认 ``src=`` / ``url(`` ⇒ ``<link href>``/
# ``<script href>`` 形态的外链 CSS/JS 根本不触发拦截器注册，Chromium 盲连。
# ``href=`` 一并收进来（宁可多注册一条 ``**/*`` 路由，也不许留「判据看不见
# 所以不拦」的洞）；``url(`` 支保留 CSS 背景图形态。
_HTML_URL_RE = re.compile(
    r"""(?:src=|href=|url\()[\'"]?(https?://[^\'")\s>]+)""",
    re.IGNORECASE,
)


def _html_mentions_remote_resource(html: str) -> bool:
    """HTML 是否含任何 http(s) 资源引用（``src=`` / ``href=`` / ``url(`` 形态）。

    SEAT-ATK-RENDER M-1（2026-09-28）+ W4 扩形态（2026-10-01）：``_orb_route``
    的注册判据——闸要罩住「任意远程资源」，不是只罩 ORB 名单，也不是只罩
    ``src=`` 一形。复用 ``_HTML_URL_RE`` 单一形态真身（本模块不写第二套 URL
    判定），无任何 http(s) 引用时返回 False，供渲染路径保留「零路由处理器
    注册」快路径。
    """
    return bool(_HTML_URL_RE.search(html or ""))


# ---- 封面图进程内 LRU 缓存（审查 L-07）----
# 卡片封面/ORB 图每次渲染都经 _fetch_image_bytes 回源 urlopen——同一封面
# URL（重发/重渲染/历史卡片重截）反复重复下载。加进程内 LRU：
# URL → (bytes, content_type)，对齐项目 LRU 惯例（reactions.py OrderedDict
# + move_to_end + 插入序淘汰）。
# 约束：
# - 容量封顶 _IMG_CACHE_MAX_ENTRIES 条；单条超 _IMG_CACHE_MAX_BYTES 的图
#   不缓存只直读（防单张大图挤占整池），返回值契约不变。
# - 只缓存成功结果，不缓存负结果：封面多为内容寻址 CDN URL（sinaimg/
#   weibocdn 图链含内容哈希，同 URL 即同图，故正缓存不设 TTL 也不会陈旧）；
#   短 TTL 负缓存会把瞬时网络故障放大成持续灰图，不如让每次失败都重新
#   走 route.abort → 模板 onerror 兜底一次机会。
# - 线程安全：渲染虽持后端实例锁，但 _fetch_image_bytes 是模块级函数
#   （多后端/测试可能并发进入），OrderedDict 非线程安全，配互斥锁。
_IMG_CACHE_MAX_ENTRIES = 64
_IMG_CACHE_MAX_BYTES = 8 * 1024 * 1024
_IMAGE_BYTES_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_IMAGE_BYTES_CACHE_LOCK = threading.Lock()


def _image_bytes_cache_clear() -> None:
    """测试隔离用：清空封面图 LRU（模块级进程内状态）。"""
    with _IMAGE_BYTES_CACHE_LOCK:
        _IMAGE_BYTES_CACHE.clear()


def _fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    # 审查 L-07：先查进程内 LRU，命中免回源（同 URL 重渲染直接复用字节）。
    with _IMAGE_BYTES_CACHE_LOCK:
        cached = _IMAGE_BYTES_CACHE.get(url)
        if cached is not None:
            _IMAGE_BYTES_CACHE.move_to_end(url)
            return cached
    request = urllib.request.Request(url, headers=_ORB_FETCH_HEADERS)
    try:
        with _ORB_FETCH_OPENER.open(request, timeout=10) as response:
            data = response.read(16 * 1024 * 1024)
            content_type = str(response.headers.get("Content-Type") or "image/jpeg")
            result = (data, content_type.split(";")[0].strip())
    except Exception:  # noqa: BLE001 - 取回失败交给 route.abort，模板 onerror 兜底。
        # 失败不缓存负结果（约束见上方 L-07 注释）：返回契约与失败路径零变化。
        return None
    # 单条超限不缓存只直读：返回值照常交给 route.fulfill，只是不占缓存池。
    if len(data) <= _IMG_CACHE_MAX_BYTES:
        with _IMAGE_BYTES_CACHE_LOCK:
            _IMAGE_BYTES_CACHE[url] = result
            _IMAGE_BYTES_CACHE.move_to_end(url)
            while len(_IMAGE_BYTES_CACHE) > _IMG_CACHE_MAX_ENTRIES:
                _IMAGE_BYTES_CACHE.popitem(last=False)
    return result


# ---- mermaid.min.js 本地供给（素材本地化 F1，2026-09-14）----
# 常驻浏览器每次 new_page 是全新 context、无 HTTP 缓存复用 → 不落盘就每张
# mermaid 卡回源 jsDelivr（~3.4MB），离线吃满 set_content 8s 预算截断（已知
# 问题 #8 根因之一）。模板 script src 保持 CDN URL 不变（mermaid_card.html
# 零分叉），此处渲染期 page.route() 在传输层换血：本地素材校验通过才注册
# 拦截（命中即 fulfill 本地字节），缺失/损坏则不注册、放行走网络（优雅
# 降级回现状）。落盘由 scripts/fetch_mermaid_js.py 一次性完成。
_MERMAID_CDN_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
# 真身 ~3.4MB（11.17.2 实测 3,572,661 B）；低于阈值按截断/错误页拒收。
_MERMAID_MIN_BYTES = 512 * 1024


def mermaid_asset_dir() -> Path:
    """mermaid 素材目录（与平台 logo 同区 card_render_assets/mermaid/）。

    解析序与 bridge._resolve_icon_asset_root 同型：BOT_CARD_ASSET_DIR 显式
    配置 → 祖先目录搜索 ChatBot_Runtime/card_render_assets（支持
    MyWorkspace\\ChatBot 与 Archive\\ChatBot\\ChatBot 两种布局）→ 源码树
    开发兜底。返回目录不保证已存在（fetch 工具负责创建）。
    """
    configured = os.getenv("BOT_CARD_ASSET_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "mermaid"
    for ancestor in Path(__file__).resolve().parents:
        asset_root = ancestor / "ChatBot_Runtime" / "card_render_assets"
        if asset_root.is_dir():
            return asset_root / "mermaid"
    return Path(__file__).resolve().parent / "card_render" / "assets" / "mermaid"


def resolve_mermaid_asset_path() -> Path:
    """mermaid.min.js 本地素材路径（不保证存在，缺失=拦截不启用）。"""
    return mermaid_asset_dir() / "mermaid.min.js"


def validate_mermaid_asset_bytes(data: bytes) -> bytes | None:
    """本地/下载字节的收货校验；不合格返回 None（拒收/放行网络）。

    三道闸：大小阈值（截断防护）、首字节非 ``<``（CDN HTML 错误页防护）、
    前部含 ``mermaid`` 标记（随机大文件误配防护）。
    """
    if len(data) < _MERMAID_MIN_BYTES:
        return None
    if data[:4096].lstrip().startswith(b"<"):
        return None
    if b"mermaid" not in data[:65536].lower():
        return None
    return data


def _mermaid_asset_bytes() -> bytes | None:
    """读取并校验本地 mermaid.min.js；缺失/损坏返回 None（放行网络）。"""
    try:
        return validate_mermaid_asset_bytes(resolve_mermaid_asset_path().read_bytes())
    except OSError:
        return None


# ---- 渲染等待策略（render-pipeline-optimization-spec §2.1b，Phase-1 框架）----
# 预算等待的就绪信号（依次等待、齐即截；仅 ``wait_budget_ms`` 模式启用）：
# ① document.fonts.ready——晚到字体 swap 是截图换字形的直接来源；
# ② 全部 <img> complete 且 naturalWidth 两次采样一致——解码稳定，排除
#    「刚 complete 仍在改布局」的半帧窗口（比既有单次 complete 更强）；
# ③ 双 requestAnimationFrame 帧界——保证至少跨过一个新绘制帧再截图。
_RENDER_READY_SIGNALS: tuple[str, ...] = (
    "async () => { await document.fonts.ready; return true; }",
    (
        "async () => {"
        "const snap = () => Array.from(document.images)"
        ".map(img => img.complete ? img.naturalWidth : -1).join(',');"
        "const first = snap();"
        "await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));"
        "return first === snap();"
        "}"
    ),
    (
        "async () => {"
        "await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));"
        "return true;"
        "}"
    ),
)


def _parse_wait_budget_ms(payload: dict[str, Any]) -> int | None:
    """解析可选 ``wait_budget_ms``；缺省/非法/负值 → None（回落旧固定等待）。"""
    raw = payload.get("wait_budget_ms")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _wait_render_budget(
    page: Any, budget_ms: int, *, clock: Callable[[], float] = time.monotonic
) -> None:
    """预算上限等待（规格 §2.1b）：依次等就绪信号，齐即提前返回。

    与固定 sleep 的差异：信号全部达成时提前截图；未达成则等到预算封顶
    按当前画面截断。不抛错不降级——降级仍由 .card 缺失/截图失败链路承担
    （契约 #7 语义不变）。总等待时间保证 ≤ budget_ms。某信号等待中途抛错
    （超时=预算已耗尽；页面异常=后续渲染步骤会自然失败）即停止追加等待，
    不继续消耗剩余预算。
    """
    deadline = clock() + max(0, int(budget_ms)) / 1000.0
    for signal_js in _RENDER_READY_SIGNALS:
        remaining_ms = max(0, round((deadline - clock()) * 1000))
        if remaining_ms <= 0:
            return
        try:
            page.wait_for_function(signal_js, timeout=remaining_ms)
        except Exception:  # noqa: BLE001 - 预算封顶/页面异常：按已就绪现状继续。
            return


# ---- 截图前动画钉帧（2026-09-18 统一收尾波 ANIM 席）----
# 生产截图路径此前不冻结 CSS 循环动画（漂移色斑 46/52/58s infinite alternate），
# 同 payload 双渲 PNG 字节随墙钟采样漂移（相位 digest 只钉动画初相、不钉采样
# 时刻）——旧样张基线 PNG 字节等值判据失效的根因。
# 排除项：截图参数 animations="disabled" 会把 infinite 动画**取消到基底位**、
# 丢失 --phase 负 delay 钉帧姿态（progress-CORE.md §SAMPLES 取证：disabled
# 截图 == animation:none 基底位、≠ 钉帧参照帧）——破坏 E01 相位设计，不采纳。
# 采纳方案：截图前 WAAPI 钉时——对 .card 子树全部动画 pause() + currentTime=0。
# currentTime=0 与负 delay 联合给出 local time = −delay = 钉帧位（与「加载即
# animation-play-state:paused」参照帧逐字节一致，本席探针实证，含 ::before/
# ::after 伪元素动画）；显式设时与调用时刻无关 → 双渲字节确定。CSS 注入两路
# 均不可用：add_init_script 样式被 set_content 的文档重建抹除（探针实测
# play-state=running）；add_style_tag 在 set_content 之后注入则动画钟已走、
# 冻结在流逝位而非钉帧位（非确定且破坏相位）。
# 失败面 fail-open：evaluate 不可用（测试假页面无此方法）/执行异常 → 跳过
# 钉帧回落今日现状；渲染失败降级链路零新增故障面。mermaid wait_js 流程以
# SVG/JS 为主、无 CSS 动画依赖（全卡面动画仅 mica-drift-* 三族，契约测试
# 锁定），钉帧时机在全部等待之后、截图之前，不影响 wait/解码逻辑。
_PIN_CARD_ANIMATIONS_JS = (
    "() => {"
    "let pinned = 0;"
    "for (const anim of document.getAnimations()) {"
    "const target = anim.effect && anim.effect.target;"
    "if (target && typeof target.closest === 'function' && target.closest('.card')) {"
    "try { anim.pause(); anim.currentTime = 0; pinned += 1; } catch (e) {}"
    "}"
    "}"
    "return pinned;"
    "}"
)


def _pin_card_animations(page: Any) -> None:
    """截图前把 .card 子树 CSS 动画钉在 --phase 定义的相位位（机制见上节注释）。

    只对真实 playwright 页面生效；假页面（无 evaluate）/执行异常一律静默
    跳过（fail-open，不阻断截图）。对元素截图与 full_page 兜底两条路径同
    时生效（同一页面文档，钉帧先于两条路径分叉）。
    """
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return
    try:
        evaluate(_PIN_CARD_ANIMATIONS_JS)
    except Exception:  # noqa: BLE001, S110 - 钉帧失败不阻断截图（回落现状）。
        pass


# ---- Phase-2 渲染并发/等待预算开关（perf-optimization-plan §三.1）----
# 解析链与 decision.resolve_decision_mode 同源模式：driver config（防御式
# import；同时查小写字段名与原始 BOT_* 键，兼容 .env 两种书写）→ 进程 env
# → 缺省。缺省安全：并发=1（=旧全程大锁串行语义）、预算=不启用（None →
# 旧固定等待）——两键不配置时行为与今天逐字节一致。
_RENDER_MAX_CONCURRENCY_CONFIG_KEY = "bot_render_max_concurrency"
_RENDER_MAX_CONCURRENCY_ENV = "BOT_RENDER_MAX_CONCURRENCY"
_RENDER_WAIT_BUDGET_MS_CONFIG_KEY = "bot_render_wait_budget_ms"
_RENDER_WAIT_BUDGET_MS_ENV = "BOT_RENDER_WAIT_BUDGET_MS"


def _render_setting_raw(config_key: str, env_key: str) -> tuple[object, ...]:
    """按解析链收集候选原始值（driver config 两形态 → 进程 env）。"""
    raw_values: list[object] = []
    try:
        import nonebot

        driver_config = nonebot.get_driver().config
        raw_values.append(getattr(driver_config, config_key, None))
        raw_values.append(getattr(driver_config, env_key, None))
    except Exception:  # noqa: BLE001, S110 - 单测/裸脚本无 driver 时静默落下一级。
        pass
    raw_values.append(os.environ.get(env_key))
    return tuple(raw_values)


def _coerce_setting_int(raw: object, *, minimum: int) -> int | None:
    """原始值 → int；缺省/非法/低于下限 → None（保持当前级缺省语义）。

    经 ``str`` 归一后解析：driver config/env 来的值本就是文本形态，
    ``"12.5"`` 等非整数文本一律视为非法（不静默截断）。
    """
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= minimum else None


def resolve_render_max_concurrency() -> int:
    """渲染并发上限：driver config → env ``BOT_RENDER_MAX_CONCURRENCY`` → **1**。

    1 = 现状串行（与旧全程大锁等价）；>1 传给
    ``PlaywrightRenderBackend(max_concurrency=N)`` 放行跨线程并行。
    """
    for raw in _render_setting_raw(
        _RENDER_MAX_CONCURRENCY_CONFIG_KEY, _RENDER_MAX_CONCURRENCY_ENV
    ):
        value = _coerce_setting_int(raw, minimum=1)
        if value is not None:
            return value
    return 1


def resolve_render_wait_budget_ms() -> int | None:
    """单卡等待预算 ms：driver config → env ``BOT_RENDER_WAIT_BUDGET_MS``。

    缺省/空/0/负值/非法 → **None = 不启用**（payload 未带
    ``wait_budget_ms`` 时维持旧固定等待，逐字节现状）。
    """
    for raw in _render_setting_raw(
        _RENDER_WAIT_BUDGET_MS_CONFIG_KEY, _RENDER_WAIT_BUDGET_MS_ENV
    ):
        value = _coerce_setting_int(raw, minimum=1)
        if value is not None:
            return value
    return None


class RenderBackend(Protocol):
    name: str
    available: bool

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        """渲染卡片为图片字节；失败返回 None。"""


class NullRenderBackend:
    name = "null"
    available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        return None


class HtmlKitRenderBackend:
    """HTML/Markdown → 图片（需要 htmlkit + Playwright 浏览器）。"""

    name = "htmlkit"
    available = False
    _html_to_pic: Any = None

    def __init__(self) -> None:
        try:
            from nonebot_plugin_htmlkit import html_to_pic  # type: ignore

            self._html_to_pic = html_to_pic
            self.available = True
        except Exception:  # noqa: BLE001 - htmlkit 不可用时标记为不可用，不抛出。
            self.available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        if not self.available:
            return None
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        try:
            result = self._html_to_pic(
                html,
                viewport=payload.get("viewport") or {"width": 640, "height": 400},
            )
        except Exception:  # noqa: BLE001 - htmlkit 渲染失败按无结果降级。
            return None
        if isinstance(result, bytes):
            return result
        if isinstance(result, (str, Path)):
            try:
                return Path(result).read_bytes()
            except OSError:
                return None
        return None


class PlaywrightRenderBackend:
    """HTML → PNG 图片（直接依赖 playwright + chromium，不依赖 htmlkit）。

    浏览器生命周期借鉴 nonebot-plugin-htmlrender 的常驻模式：懒启动、
    跨渲染复用、信号量限并发、崩溃自动重启——避免每张卡片都付出
    Chromium 冷启动开销（订阅批量推送时尤其明显）。
    线程安全：playwright 的 sync API 必须与事件循环隔离开，调用方应
    在 to_thread 里执行（能力层已 offload）。
    """

    name = "playwright"
    available = False
    # 线程本地常驻浏览器的空闲回收阈值：超过即关旧开新，避免僵死实例常驻。
    _BROWSER_IDLE_SECONDS = 600.0
    # 单页内容加载超时：set_content 就绪等待（load 形态）与后续 wait_for_* 的
    # 页面上限，防止慢资源把锁持有 30s（Playwright 默认）。数值不动，形态口径
    # 见 render_card 内「就绪形态＝load」段（SEAT-G 2026-10-11）。
    _SET_CONTENT_TIMEOUT_MS = 8000
    # 浏览器级故障的特征串：命中才整体重启浏览器，页面级失败只关页面。
    _BROWSER_CRASH_MARKERS = (
        "target closed",
        "browser has been closed",
        "browser has crashed",
        "connection closed",
        "playwright closed",
        "pipeline closed",
    )
    # 连续页面级失败阈值：is_connected()=True 但内核已僵死时，页面级失败
    # （超时/截图失败）永远不满足崩溃标记，浏览器永久卡死、所有渲染降级
    # （2026-09-12 实弹：15:58 出卡正常 → 17:28 起全部发封面）。连续失败
    # 达到阈值即强制丢弃线程常驻实例，下次渲染懒启动新浏览器自愈。
    _MAX_CONSECUTIVE_PAGE_FAILURES = 2

    def __init__(self, *, max_concurrency: int = 1) -> None:
        import threading

        # sync playwright 非线程安全且对象线程绑定：常驻浏览器按线程存放
        # （help/卡片渲染可能来自不同工作线程，各线程复用各自的常驻实例，
        # 仍消除冷启动）。渲染间的互斥/限并发由下面的信号量承担。
        # 并发模型（规格 §3，Phase-1 缺省安全子集）：_lock 属性从全程大锁
        # 升级为 BoundedSemaphore(max_concurrency)——默认 1 = 与旧全程大锁
        # 等价的串行语义（天然回滚位）；>1 时允许至多 N 张卡跨线程并行，
        # 线程本地浏览器复用、懒启动、自愈逻辑零改动，不触碰「同线程任一
        # 时刻至多一个活跃 sync ctx」不变量（并行只来自跨线程）。属性名
        # 保留 _lock：手工装配替身（测试）塞 threading.Lock 同样合法，
        # 仅语义退化为串行。
        self._lock: Any = threading.BoundedSemaphore(max(1, int(max_concurrency)))
        self._local = threading.local()
        self._max_concurrency = max(1, int(max_concurrency))
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            self._sync_playwright: Any = sync_playwright
            self.available = True
        except Exception:  # noqa: BLE001 - Playwright 不可用时标记为不可用，不抛出。
            self._sync_playwright = None
            self.available = False

    def _thread_browser(self) -> tuple[Any, Any]:
        browser = getattr(self._local, "browser", None)
        ctx = getattr(self._local, "playwright_ctx", None)
        return browser, ctx

    def _get_browser(self, *, backoff: Callable[[], None] | None = None) -> Any:
        """懒启动并复用本线程的常驻 Chromium；空闲超限或已死则重建。

        launch 失败重试一次（资源瞬时紧张常见），仍失败才向上抛。
        重试前必须先 ``__exit__`` 掉本次已 start 的 playwright ctx
        （评审 C-1）：泄漏的 start 实例会让同线程下一次 start() 命中
        playwright 的 running-loop 守卫，报 "Sync API inside the asyncio
        loop"，且 thread-local 只在成功后写入、``_close_thread_browser``
        对泄漏实例不可达——该线程渲染永久中毒至进程重启。

        审查 L-13：``backoff`` 是两次 launch attempt 之间的退避动作。
        持槽调用方（render_card）必须注入 ``_release_slot_backoff``，
        把 0.5s 退避 sleep 移出渲染槽位临界区；缺省（无槽位上下文的
        直接调用，如测试）退化为原地 sleep，等待时长与旧实现一致。
        """
        on_backoff = backoff if backoff is not None else self._plain_launch_backoff
        browser, _ctx = self._thread_browser()
        if browser is not None and browser.is_connected():
            last_used = float(getattr(self._local, "last_used", 0.0) or 0.0)
            if last_used and (time.monotonic() - last_used) < self._BROWSER_IDLE_SECONDS:
                return browser
        self._close_thread_browser()
        last_launch_error: Exception | None = None
        for _attempt in range(2):
            playwright_ctx: Any = None
            try:
                playwright_ctx = self._sync_playwright()
                playwright = playwright_ctx.start()
                browser = playwright.chromium.launch()
            except Exception as exc:  # noqa: BLE001 - 启动失败重试一次。
                # C-1：launch 失败时当场正确退出本次已 start 的 ctx（幂等，
                # __enter__ 未走完时内部守卫短路/异常被吞），否则同线程重试
                # 的 start() 必报 Sync-inside-asyncio 且泄漏实例不可达。
                try:
                    exit_ctx = getattr(playwright_ctx, "__exit__", None)
                    if callable(exit_ctx):
                        exit_ctx(None, None, None)
                except Exception:  # noqa: BLE001, S110 - 清理失败不阻断重试。
                    pass
                last_launch_error = exc
                # 审查 L-13：退避只发生在两次 attempt 之间——末次失败后无
                # 重试可服务，不再空睡（旧实现循环结构导致末次失败也睡 0.5s，
                # 纯属浪费；失败仍如实上抛，纯文本兜底契约零变化）。
                if _attempt + 1 < 2:
                    on_backoff()
                continue
            self._local.browser = browser
            self._local.playwright_ctx = playwright_ctx
            return browser
        raise last_launch_error  # type: ignore[misc]

    def _plain_launch_backoff(self) -> None:
        """审查 L-13：无槽位上下文（测试直接调 _get_browser）的退避——原地睡。"""
        time.sleep(0.5)

    def _release_slot_backoff(self) -> None:
        """审查 L-13：launch 退避 sleep 移出渲染槽位临界区（先放槽位再睡）。

        render_card 持 self._lock（BoundedSemaphore 并发槽位）调用
        _get_browser；旧实现在槽位内 time.sleep(0.5)，并发渲染下其它线程
        被这段纯等待无谓阻塞（max_concurrency=1 时整条渲染串行冻结）。
        此处先释放槽位、睡完重新取回：
        - 槽位守恒：release/acquire 严格成对（finally 保证异常路径也取回），
          render_card ``with self._lock:`` 退出时的单次 release 依然配平；
          槽位计数失衡会当场被 BoundedSemaphore 抛 ValueError 暴露。
        - 重查语义：浏览器为 thread-local（_local 仅属主线程读写），睡眠
          窗口内不存在他人可改的共享渲染态；取回槽位后循环从
          sync_playwright()→start()→launch() 全新重试，即对「资源是否仍
          紧张」的复查——仍失败如实上抛，render_card 返回 None 走纯文本
          兜底，契约零变化。
        - 不需代际计数防惊群：各线程只重启自己的 thread-local 浏览器，
          不存在共享单例重启点；且每次 launch() 本身持槽位执行，同时
          发起的 launch 数仍被信号量钳制（只有纯 sleep 窗口让位）。
        - 公平性：信号量唤醒顺序不保证本线程先取回；被其它渲染线程抢先
          仅表现为本线程多等一段，不产生错误。
        """
        lock = self._lock
        lock.release()
        try:
            time.sleep(0.5)
        finally:
            lock.acquire()

    def _close_thread_browser(self) -> None:
        browser, ctx = self._thread_browser()
        self._local.browser = None
        self._local.playwright_ctx = None
        # ctx 是 PlaywrightContextManager：没有 .close()（旧实现调用被静默
        # 吞掉 → 僵尸浏览器的传输掐不断 → 该线程 asyncio loop 永久中毒，
        # 后续 start() 必报 Sync-inside-asyncio）。公开协议是 __exit__；
        # 2026-09-12 实测修复「自愈后同线程永久 None」（评审复测：双
        # __exit__ 幂等 / 正确退出后同线程可重启 / 端到端自愈复用）。
        if ctx is not None:
            try:
                exit_ctx = getattr(ctx, "__exit__", None)
                if callable(exit_ctx):
                    exit_ctx(None, None, None)
                elif hasattr(ctx, "close"):
                    ctx.close()
            except Exception:  # noqa: BLE001, S110 - 关闭失败忽略，下次懒启动重建。
                pass
        if browser is None:
            return
        try:
            browser.close()
        except Exception:  # noqa: BLE001, S110 - 关闭失败忽略，下次懒启动重建。
            pass

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        if not self.available or self._sync_playwright is None:
            return None
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        viewport = payload.get("viewport") or {"width": 672, "height": 480}
        width = int(viewport.get("width", 672))
        height = int(viewport.get("height", 480))
        wait_ms = int(payload.get("wait_ms", 1500))
        # Phase-1（规格 §2.1b）：可选 wait_budget_ms 把该等待从「固定 sleep」
        # 升级为「预算上限」。缺省/非法 → None：维持旧固定地板，不传新键的
        # 调用行为逐字节一致（wait_ms 在预算模式下作为旧值被忽略）。
        # Phase-2（perf-optimization-plan §三.1）：payload 未显式携带时回落
        # 全局预算缺省（driver config / env 注入）；未配置仍是 None——
        # 缺省路径不变，payload 显式值恒优先于全局缺省。
        wait_budget_ms = _parse_wait_budget_ms(payload)
        if wait_budget_ms is None:
            wait_budget_ms = resolve_render_wait_budget_ms()
        try:
            device_scale_factor = int(payload.get("device_scale_factor", 2))
        except (TypeError, ValueError):
            device_scale_factor = 2
        with self._lock:
            page = None
            try:
                # 审查 L-13：持槽调用必须注入 _release_slot_backoff，
                # launch 重试的退避 sleep 才会在槽位临界区外执行。
                browser = self._get_browser(backoff=self._release_slot_backoff)
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=device_scale_factor,
                    )
                except Exception:  # noqa: BLE001 - 浏览器崩溃时重启一次再试。
                    browser = self._get_browser(backoff=self._release_slot_backoff)
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=device_scale_factor,
                    )
                try:
                    def _orb_route(route: Any) -> None:
                        # 拦「任意 http(s) 远程请求」，不止图片（W4 口径对齐，
                        # 2026-10-01）：旧实现首行就把非 image 一律 continue_()，
                        # 而 docstring 与注册判据都自称「罩住任意远程资源」⇒
                        # 外链 CSS/JS/XHR 实际零判定（Chromium 盲连 127.0.0.1:3001）。
                        # 这里两轨分开，一条都不许含糊：
                        # ①ORB 名单图（sinaimg/weibocdn）＝python 侧代捞换字节；
                        # ②其余**任意 http(s)** 请求＝建连前过中央咽喉，拒即 abort。
                        request = route.request
                        url = str(request.url)
                        # 先判 scheme，再谈拒绝：data:/blob:/about:/file: 不是远程
                        # 资源（本地素材与内联图是渲染常态），一律交回浏览器。
                        # 少了这道，纯本地图会被咽喉按「非 http/https 协议」拒掉
                        # ⇒ 无差别 abort ⇒ 卡面图全灰（W4 缺口⑤之二）。
                        if not url.startswith(("http://", "https://")):
                            route.continue_()
                            return
                        # 轨①：ORB 名单图仍走 python 代捞（直连 + curl 头），
                        # 取不到字节才 abort（模板 onerror 灰图兜底）。
                        if (
                            str(getattr(request, "resource_type", "") or "") == "image"
                            and _orb_prone_url(url)
                        ):
                            fetched = _fetch_image_bytes(url)
                            if fetched is None:
                                route.abort()
                                return
                            data, content_type = fetched
                            route.fulfill(
                                status=200, body=data, content_type=content_type
                            )
                            return
                        # 轨②：F-3 收口（2026-09-27 S-ATKFIX-SSRF2）+ W4 扩面。
                        # 建连前先过**中央唯一判据** check_download_url——明确
                        # 拒绝即 abort（灰图/缺资源兜底已有），放行才 continue_()。
                        # 名单内域本就不可能指内网，故代捞支不引咽喉调用（避免对
                        # 图床触发 DNS）这条口径维持不变。
                        from plugins.bot_unified_runtime.domains.files.sources.downloader import (
                            RejectedUrlError,
                            check_download_url,
                        )

                        try:
                            check_download_url(url)
                        except RejectedUrlError:
                            route.abort()
                            return
                        route.continue_()

                    # M-1 收口（SEAT-ATK-RENDER 2026-09-28，S-FIX-RENDER-SSRF）：
                    # 旧判据「仅命中 ORB 名单图才注册」让上面的 SSRF 闸与 ORB
                    # 子集同生同死——不含 sinaimg 图的卡（多数）零拦截器，
                    # 外链图由本机 Chromium 盲连，F-3 判据根本不执行。
                    # 新判据＝「HTML 含任何 http(s) 资源引用」；完全无外链
                    # 仍不注册，保留零处理器开销快路径。拒绝判据本体仍是
                    # 中央咽喉 check_download_url（domains/files/sources/
                    # downloader.py），本件不复制第二套 SSRF 正则。
                    # W4 补守卫（同批改锁，台账 #68★「扩面要文件＋锁同批」）：
                    # ``callable(register_route)`` 这道闸隔壁 mermaid 支本就有，
                    # 上面这条注册却直呼 ``page.route`` ⇒ 无 route 的假 page 测试
                    # 替身当场 AttributeError 被外层吞掉、整卡降级成 None
                    # （test_mermaid_local_asset 三枚红的真身）。注册件一次取回、
                    # 两支共用，判据只此一处。
                    register_route = getattr(page, "route", None)
                    if callable(register_route) and _html_mentions_remote_resource(html):
                        register_route("**/*", _orb_route)
                    # mermaid 本地供给（F1）：模板 src 是 CDN URL，传输层拦截
                    # 换血为本地字节。注册在 ORB 路由之后（Playwright 按注册
                    # 逆序匹配，后注册者优先），精确 URL 模式不碰其他请求。
                    # 本地素材缺失/损坏 → 不注册放行网络；page 无 route（假
                    # page 测试替身）→ 同样跳过，零回归。
                    if _MERMAID_CDN_URL in html:
                        mermaid_js = _mermaid_asset_bytes()
                        if mermaid_js is not None and callable(register_route):

                            def _mermaid_route(route: Any) -> None:
                                route.fulfill(
                                    status=200,
                                    body=mermaid_js,
                                    content_type="text/javascript",
                                )

                            register_route(_MERMAID_CDN_URL, _mermaid_route)
                    # 显式加载超时：Playwright 默认 30s 会长时间持锁阻塞其他
                    # 渲染。用页面级默认超时覆盖 set_content/wait_for_*（页面
                    # 级失败只关页面，浏览器不受影响）。
                    set_default_timeout = getattr(page, "set_default_timeout", None)
                    if callable(set_default_timeout):
                        set_default_timeout(self._SET_CONTENT_TIMEOUT_MS)
                    # 就绪形态＝load（SEAT-G 2026-10-11 实测裁决；反向护栏＝
                    # tests/test_render_wait_budget.py 的三枚 AST 常驻锁）。
                    # 为什么不是 networkidle：它的定义「网络静默满 500ms」在这
                    # 套卡面上是纯白烧——同 HTML/同视口/同 dsf 实跑 n=6 中位
                    # universal 511.9ms、affinity 512.7ms、news_digest 513.3ms，
                    # 换 load 后 20.0/6.5/6.4ms（domcontentloaded 9.7/6.8/7.0ms）。
                    # 覆盖面（同批实跑请求计数；card_render 八张模板＋旧 media_card
                    # 共九张面）：只有 mermaid 那张发出 1 枚 http(s) 请求，而它已被
                    # 上面 page.route 换成本地字节回源 ⇒ 静默窗口等的是「没有东西在
                    # 飞」。affinity 卡里的 http://www.w3.org/2000/svg 是 XML
                    # 命名空间、不发请求。
                    # 为什么不是 domcontentloaded（更快但护栏少一层）：1200ms 延迟
                    # 图的离线对拍下，load 的 set_content 自身就把图取回等完了
                    # （1209.3ms），domcontentloaded 4.9ms 返回、图还要 1205.7ms
                    # 才 ready ⇒ 等图 100% 压在下面 img.complete/预算信号上；阻塞式
                    # 外链脚本（mermaid.min.js）同理只在 load 面保证已执行完。
                    # 字节等值（同一条生产链 set_content→img.complete→预算→钉帧→
                    # .card 元素截图，三形态各渲两次）：universal c7ab971810b7937e
                    # / affinity 393221a2c43729e5 / news_digest ecf830eab5c18475 /
                    # mermaid 402cbd01c260a242，跨形态与跨重渲均逐字节一致。
                    page.set_content(html, wait_until="load")
                    # 封面清晰度关键：等所有 <img> 真正解码完成（load 只保证取回、
                    # 大图可能仍在解码）；再兜底固定等待。本条与预算信号②是
                    # 「图真解码完」的两道闸——换等待形态**不减少等图**，摘掉本条
                    # 必有锁红（test_render_wait_budget 两枚 ＋
                    # tests/test_render_phase2_env_keys.py 的 _legacy_expected_ops）。
                    try:
                        page.wait_for_function(
                            "Array.from(document.images).every(img => img.complete)",
                            timeout=8000,
                        )
                    except Exception:  # noqa: S110, BLE001 - 超时按已加载现状截图。
                        pass
                    # 动态渲染页（mermaid 等）在截图前等待指定 JS 条件成立；
                    # 条件超时/脚本报错视为渲染失败返回 None（调用方降级文本），
                    # 避免把半成品页截成图。不传 wait_js 的既有调用零变化。
                    wait_js = payload.get("wait_js")
                    if isinstance(wait_js, str) and wait_js.strip():
                        try:
                            wait_js_timeout_ms = int(
                                payload.get("wait_js_timeout_ms", 6000)
                            )
                        except (TypeError, ValueError):
                            wait_js_timeout_ms = 6000
                        try:
                            page.wait_for_function(wait_js, timeout=wait_js_timeout_ms)
                        except Exception:  # noqa: BLE001 - 目标条件未达成按失败降级。
                            return None
                    if wait_budget_ms is None:
                        # 缺省路径：固定地板等待，与既有行为逐字节一致。
                        page.wait_for_timeout(wait_ms)
                    else:
                        # 预算上限路径：就绪信号齐即提前截图，超预算封顶截断。
                        _wait_render_budget(page, wait_budget_ms)
                    # 截图前动画钉帧：.card 子树动画冻结在 --phase 相位位
                    # （字节稳定+钉帧位双得；机制/排除项/fail-open 见
                    # _pin_card_animations 注释）。full_page 兜底同文档同益。
                    _pin_card_animations(page)
                    element = page.query_selector(".card")
                    if element is not None:
                        # 元素截图自带裁切范围，不需要 clip 参数。
                        self._local.page_failures = 0
                        return bytes(
                            element.screenshot(type="png", omit_background=True)
                        )
                    self._local.page_failures = 0
                    # C12（2026-09-18 统一收尾波）：.card 缺失的 full_page 兜底
                    # 截图与元素截图同口径补 omit_background——body 透明契约
                    # （渲染契约 §2）对两条截图路径一视同仁，兜底图不再带白底。
                    return bytes(
                        page.screenshot(type="png", full_page=True, omit_background=True)
                    )
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:  # noqa: S110, BLE001 - 页面关闭失败不阻断。
                            pass
            except Exception as exc:  # noqa: BLE001 - 渲染失败按无结果降级。
                # 页面级失败（加载超时/截图失败）只关页面（finally 已关），
                # 浏览器复用不受影响；仅浏览器级错误（Target closed 等）重启。
                failures = int(getattr(self._local, "page_failures", 0) or 0) + 1
                self._local.page_failures = failures
                if self._browser_looks_broken(exc) or failures >= self._MAX_CONSECUTIVE_PAGE_FAILURES:
                    # 僵死浏览器（连接在但内核卡死）不会命中崩溃标记：
                    # 连续页面失败达阈值同样强制丢弃，下次懒启动重建自愈。
                    self._close_thread_browser()
                    _LOGGER.warning(
                        "render browser rebuilt after failure streak (%d): %s",
                        failures,
                        type(exc).__name__,
                    )
                return None
            finally:
                self._local.last_used = time.monotonic()

    def _browser_looks_broken(self, exc: Exception) -> bool:
        browser, _ctx = self._thread_browser()
        try:
            if browser is None or not browser.is_connected():
                return True
        except Exception:  # noqa: BLE001 - 连接状态探测失败按已损坏处理。
            return True
        message = str(exc).lower()
        return any(marker in message for marker in self._BROWSER_CRASH_MARKERS)

    def close(self) -> None:
        self._close_thread_browser()


# ---- 进程级共享渲染后端登记（审查 L-04，2026-09-14）----
# 背景：bridge._get_mermaid_backend 历史上经 build_render_backend("auto")
# 自建第二个 PlaywrightRenderBackend 常驻实例，与 __init__.py 装配态的主
# 渲染后端并存。主实例存于装配闭包、无既有单例可供 bridge 引用，故以本
# 工厂为会合点：每次产出**可用** playwright 后端时按「先到先得」登记为
# 进程级共享实例——插件装配先于任何渲染调用，先到者即主后端；bridge 侧
# 优先取用，同一进程至多一个后端实例同时承载主卡渲染与 mermaid 渲染。
# 线程安全语义不变：后端浏览器仍按线程 thread-local 存放（mermaid 专用
# 线程在共享实例上懒启动自己的常驻浏览器，互不越线程），渲染互斥仍由
# 实例内信号量承担；生命周期归属首个装配方，bridge 只借用引用、从不
# close。登记是被动记录：既有调用方（__init__.py / console_chat）不经
# get_shared_render_backend 取用，行为零变化。
_SHARED_RENDER_BACKEND: Any = None
_SHARED_RENDER_BACKEND_LOCK = threading.Lock()


def get_shared_render_backend() -> Any:
    """返回进程级共享 playwright 渲染后端；未登记时返回 None（不惰性创建）。"""
    with _SHARED_RENDER_BACKEND_LOCK:
        return _SHARED_RENDER_BACKEND


def _register_shared_render_backend(backend: Any) -> None:
    """按「先到先得」登记共享后端；已有登记时不覆盖（装配态先于渲染调用）。"""
    global _SHARED_RENDER_BACKEND
    with _SHARED_RENDER_BACKEND_LOCK:
        if _SHARED_RENDER_BACKEND is None:
            _SHARED_RENDER_BACKEND = backend


def build_render_backend(name: str = "") -> RenderBackend:
    normalized = (name or "").strip().lower()
    if normalized not in {"playwright", "htmlkit", "auto"}:
        # 配置拼错等场景：静默降级成 Null 会让卡片功能整体消失且无诊断线索。
        _LOGGER.warning(
            "unknown render backend name %r, falling back to null renderer",
            name,
        )
    if normalized in {"playwright", "htmlkit", "auto"}:
        # Phase-2：并发上限由 driver config / env ``BOT_RENDER_MAX_CONCURRENCY``
        # 解析；未配置 = 1 = 旧串行语义（字节级现状）。
        backend = PlaywrightRenderBackend(
            max_concurrency=resolve_render_max_concurrency()
        )
        if backend.available:
            # 审查 L-04：登记为进程级共享实例（先到先得，注释见登记段），
            # 供 bridge._get_mermaid_backend 复用，消灭第二个常驻后端实例。
            _register_shared_render_backend(backend)
            return backend
        if normalized == "htmlkit":
            return HtmlKitRenderBackend()
        _LOGGER.warning("playwright backend unavailable; cards fall back to text")
    return NullRenderBackend()

