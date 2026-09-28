"""按需联网检索提供器（意图判定见 runtime/question_intent.py）。

- 默认关闭（BOT_WEB_SEARCH_ENABLED=false）；
- 支持代理（BOT_DOWNLOAD_PROXY，例如 http://127.0.0.1:7890），外网检索走代理；
- Tavily → You.com → LangSearch API 链式回退；TinyFish 可选用于正文抓取；不接 Bing；
- 传输层统一使用 httpx：同步路径用 ``httpx.Client``（keep-alive 连接池），
  异步路径用 ``httpx.AsyncClient``，供 stdio MCP 服务器等异步调用方使用；
- 单次超时短、失败静默降级为空，绝不拖慢对话。
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_query_recency,
)
from plugins.bot_unified_runtime.domains.core.search.source_authority import (
    order_key,
)
from plugins.bot_unified_runtime.domains.core.temporal_words import TODAY_ADVERB_WORDS

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# 注释与隐藏块（含 head 元信息）是间接 Prompt 注入的常见载体，正文入 Prompt 前先剥离。
_HTML_HIDDEN_BLOCK_RE = re.compile(
    r"<(script|style|noscript|template|iframe|object|embed|svg)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_HTML_HEAD_BLOCK_RE = re.compile(r"<head[^>]*>.*?</head>", re.DOTALL | re.IGNORECASE)
# 未闭合残段兜底：抓取到的页面常被截断，闭合标签配对不上时上面的闭合
# 正则剥不掉 <script>... / <!--... 残段，注入载荷会泄漏进正文；这里把
# 从残段起点到文本末尾的内容一并剥离（代价是残段之后的合法正文丢失，
# 对注入防护而言是安全侧倾斜）。
_HTML_UNCLOSED_COMMENT_RE = re.compile(r"<!--.*\Z", re.DOTALL)
# 剩除比例护栏：兜底剥离若吃掉大半页面，说明命中的更可能是 void/畸形标签
# 而非真截断残段——记 warning 以便现场可观测（行为不变，安全侧倾斜保留）。
_HTML_STRIP_RATIO_WARN = 0.5
_HTML_UNCLOSED_HIDDEN_RE = re.compile(
    r"<(?:script|style|noscript|template|iframe|object|svg)[^>]*>.*\Z",
    re.DOTALL | re.IGNORECASE,
)
# nav/footer/aside/form/dialog 是导航/页脚/侧栏/表单类样板块（去广告向），与注入隐藏块分开剥。
_HTML_BOILERPLATE_BLOCK_RE = re.compile(
    r"<(nav|footer|aside|form|dialog)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class WebSearchHit:
    title: str
    snippet: str
    url: str
    source_domain: str = ""


class WebSearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        """返回过滤后的搜索命中；失败/超时返回空列表。"""


class NullWebSearchProvider:
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        return []


def _proxy_value(proxy: str) -> str | None:
    """返回统一代理地址；httpx 0.28 起 proxy 参数用单值覆盖所有 scheme。"""
    proxy = str(proxy or "").strip()
    return proxy or None


class _SSRFBlockedError(RuntimeError):
    """抓取被中央 SSRF 咽喉拦下（内网 / 云元数据 / 保留网段 / 非法协议）。


    只在进程内传播：``_fetch`` 的兜底 ``except`` 捕获后静默降级为空，
    绝不把内网响应内容带回正文，也不向上抛网络异常。
    """


def _ssrf_rejection_for_fetch(url: str) -> str | None:
    """入口咽喉（**确定性**判定）：命中内网 / 保留段 / 整型混淆 / 非法协议 / 黑名单主机名才拒。

    中央真身 = ``domains/files/sources/downloader.check_download_url``（简报点名的咽喉本体），
    整型/十六进制/八进制 IP 先借同族 ``link_parse/parsers/ssrf_guard._normalize_integer_ip_host``
    归一（inet_aton 语义，与 ``guard_user_url`` 同一条中央真身，非第二套 URL 判定）。
    **唯一刻意收窄**：当且仅当「本机 DNS 解析不了该域名」时，入口**不下结论**、返回 None，
    放行给逐跳钩子（连接前作「解析失败=拒绝」的权威判定）——解析不了的域名根本连不出去，
    且这样不误伤「假域名 + 桩 _fetch 验 HTML 解析」的既有用例；能解析但解析到内网者（rebind）
    仍在此处拒。惰性 import 规避包初始化期循环导入。
    """
    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )
    from plugins.bot_unified_runtime.domains.link_parse.parsers.ssrf_guard import (
        _MalformedUrlError,
        _normalize_integer_ip_host,
    )

    try:
        candidate = _normalize_integer_ip_host(url)
    except _MalformedUrlError:
        return "URL 形态非法，已拒绝"
    try:
        check_download_url(candidate)
    except RejectedUrlError as exc:
        if isinstance(exc.__cause__, OSError):
            # 仅「DNS 解析不了」→ 入口不定论，交给逐跳钩子兜底（生产连不出去 / 测试放行给桩）。
            return None
        return str(exc)
    return None


def _ssrf_request_guard(request: httpx.Request) -> None:
    """httpx request 事件钩子：逐跳（含 302 重定向之后）作**权威严格**复查。

    走中央消费向包装 ``ssrf_guard.guard_user_url``（内部即 ``check_download_url`` + inet_aton
    归一 +「解析失败=拒绝」全语义），比入口更严。httpx 对初始请求与每一跳重定向都会回调本钩子，
    因此公网结果 URL 经 302 跳向内网 / 元数据地址、或解析到内网的域名，都在该跳真正发出前被拦下
    抛错，由 ``_fetch`` 兜底 ``except`` 静默降级为空。这是「抓取路径」的 SSRF 逐跳收口（对照
    link_parse 侧 urllib 的 ``_GuardedShortLinkRedirectHandler``；本模块走 httpx 故用事件钩子实现同型语义）。
    """
    from plugins.bot_unified_runtime.domains.link_parse.parsers import ssrf_guard

    if ssrf_guard.guard_user_url(str(request.url)) is not None:
        raise _SSRFBlockedError("page fetch blocked by SSRF guard")


def _build_sync_client(
    proxy: str, timeout_seconds: float, *, ssrf_guard: bool = False
) -> httpx.Client:
    """构建带 keep-alive 连接池的同步 httpx 客户端。

    测试可通过 monkeypatch 本函数注入假 transport 或伪造网络错误。
    ``ssrf_guard=True`` 时挂上逐跳 SSRF 事件钩子（抓取第三方结果 URL 正文的路径用），
    初始请求与每一跳重定向发出前都过中央咽喉；缺省 ``False`` 保持既有行为（各搜索提供器
    打固定引擎域、非用户可控，不需要逐跳复查）。
    """
    if ssrf_guard:
        return httpx.Client(
            headers=dict(_DEFAULT_HEADERS),
            timeout=httpx.Timeout(float(timeout_seconds)),
            follow_redirects=True,
            proxy=_proxy_value(proxy),
            event_hooks={"request": [_ssrf_request_guard]},
        )
    return httpx.Client(
        headers=dict(_DEFAULT_HEADERS),
        timeout=httpx.Timeout(float(timeout_seconds)),
        follow_redirects=True,
        proxy=_proxy_value(proxy),
    )


def _build_async_client(proxy: str, timeout_seconds: float) -> httpx.AsyncClient:
    """构建带 keep-alive 连接池的异步 httpx 客户端（测试可 monkeypatch 注入）。"""
    return httpx.AsyncClient(
        headers=dict(_DEFAULT_HEADERS),
        timeout=httpx.Timeout(float(timeout_seconds)),
        follow_redirects=True,
        proxy=_proxy_value(proxy),
    )


def _fetch(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    client: httpx.Client | None = None,
    ssrf_guard: bool = False,
) -> str | None:
    """同步抓取页面文本；失败/超时静默返回 None，绝不向上抛网络异常。

    ``ssrf_guard=True`` 且未传入 ``client`` 时，自建客户端会挂逐跳 SSRF 钩子
    （抓取第三方结果 URL 正文的路径用）。传入现成 ``client`` 时护栏由调用方负责
    （各搜索提供器打固定引擎域、非用户可控，不需要逐跳复查）。
    """
    if not url:
        return None
    owns_client = client is None
    try:
        if client is None:
            client = _build_sync_client(
                proxy, timeout_seconds, ssrf_guard=ssrf_guard
            )
        response = client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:  # noqa: BLE001 - 请求失败静默返回 None。
        return None
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


async def _fetch_async(
    url: str,
    *,
    proxy: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """异步抓取页面文本；失败/超时静默返回 None。传入的 client 由调用方负责关闭。"""
    if not url:
        return None
    owns_client = client is None
    try:
        if client is None:
            client = _build_async_client(proxy, timeout_seconds)
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except Exception:  # noqa: BLE001 - 请求失败静默返回 None。
        return None
    finally:
        if owns_client and client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


_JUNK_DOMAINS = frozenset(
    {
        "hgcha.com", "hanyuguoxue.com", "zidian.gushici.net",
        "zdic.net", "dict.cn", "xh.5156edu.com",
    }
)
# 永不构成「实体证据」的问句词。**这张表的成因不是中文本身，而是查询装饰**：
# 时效四域的检索式由 `domains/chat_reply/capabilities/chat.py:4421-4477` 在原始
# 问句尾部追加「最新 消息 / 官方 发布 公告 / 来源 数据 / 维基百科 / {year}」拼出来，
# 这些词几乎每页都含，按旧判据它们与真实体同权——实测就是靠它们凑够地板，
# 把「中国地图-八九网」放进「个人所得税起征点」的结果块（席报告 §3.3 F2）。
# 因此这里删的是**装饰词**，不是话题词；话题归属的唯一真身仍是
# `question_intent.classify_timely_domain`（core 层不反向 import，见
# `source_authority.py` 头注同一理由）。新增词只准来自那张装饰表里出现过的字面。
_QUERY_STOP_TOKENS = frozenset(
    {
        "百科", "最新", "更新", "版本", "内容", "公司", "官方", "游戏", "什么", "是",
        "查询", "介绍", "背景",
        # chat.py 时效装饰实际追加、且信息量趋零的形态：
        "消息", "动态", "进展", "公布", "参数", "发布", "公告", "来源", "数据",
        "通知", "时间", "情况", "简介", "成立", "作品", "发展历程", "全文",
        "维基百科", "萌娘百科", "动漫", "番剧", "放送", "剧情", "设定", "连载",
        "前瞻", "信息", "资讯", "平台", "网页", "网站", "官网",
    }
)

# --- 中文实体化（2026-09-26 S-T-SEARCHQ-1）------------------------------------
# 旧判据只按空白/逗号切 token 并要求**整枚 token 作为子串**出现在结果里。
# 中文问句不带空格（装饰只加在尾部），于是「美联储最新利率决议」这枚 8 字串
# 永远匹配不上任何真实标题，实测 11 个 Bing 查询里 9 个整批判空、55 条命中
# 丢掉 51 条，其中财联社/腾讯/央视三张**又新又对**的议息页被一起丢掉
# （席报告 §3.2、§3.3 F1）。这一节把「整枚子串」换成「实体形态集合」：
# 问句 token 先剥脚手架、再按段，长段允许滑窗三元组成证据。
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# 单字脚手架：只登记「粘在实体上不成词」的字。刻意**不含** 中/个/和/与/有/等——
# 它们参与构词（中国/个人/中央），切开了就把真实体切碎。
_CJK_SCAFFOLD_CHARS = "的了是吗呢吧啊呀嘛就都很还也被把对为以之者么着"
_CJK_SCAFFOLD_RE = re.compile(f"[{_CJK_SCAFFOLD_CHARS}]")
# 多字脚手架（疑问/量度/客套/时间副词形态）：整串优先剥离，再剥单字。
# 时间副词必须进来（实测逼出来的）：「今天黄金价格多少钱一克」剥掉「今天」后段是
# 「黄金价格」；不剥就派生出「今天黄」这枚三元组，把「今日**黄**历宜忌查询」那家
# 黄历站判成相关——与 2026-09-11 旧注释里「「今天的黄金价格」⊃「今天+黄历」」是
# 同一形态（旧代码防的是逗号切，本表防的是三元组派生，同一陷阱的两个方向）。
# 「今天/今日」这对字形与 time_window 的时间窗解析共享单一真身（S-TRIG 收编 2026-09-26，
# 成因见 domains/core/temporal_words.py 头注）：此处只引用、不手抄，成品逐字不变。
# S-TRIG 收编（2026-09-26）：本表拆成三段各自成模块级常量，成品的内容与消费语义**逐字不变**
# （消费点按长度倒序排，声明顺序零依赖）。拆表的目的＝把「今天/今日」这对字形收编到唯一真身
# domains/core/temporal_words.py，与 time_window 的时间窗解析共享——D2 债的根因正是旧版整表
# 42 词整体手抄一份，使 time_window 2026-09-13 的旧正则 `(?:今天|今日)` 被整表追认为第二副本
# （副本棘轮门 44>42 之一，S-R-TRIGDEBT-44 §贰）。三段绑定名都含 _WORDS、全部留在两本触发词
# 尺的真身视野内，扫描面不缩；重复的只把那两枚词形换成引用，其余词各仍只登记一处。
_CJK_SCAFFOLD_QUERY_WORDS = (
    "多少", "什么", "哪些", "哪个", "哪里", "怎么", "怎样", "如何",
    "为什么", "何时", "多久", "几点", "是不是", "有没有", "可不可以", "能不能",
    "时候", "一下", "意思", "出自", "介绍一下", "告诉我", "请问", "麻烦",
    "帮我", "什么时候", "多少钱", "几天", "几号",
)
_CJK_SCAFFOLD_TIME_WORDS = (
    "昨天", "今年", "本年", "最近", "近期", "目前", "现在", "此刻",
    "本周", "本月", "最新",
)
_CJK_SCAFFOLD_WORDS = _CJK_SCAFFOLD_QUERY_WORDS + TODAY_ADVERB_WORDS + _CJK_SCAFFOLD_TIME_WORDS
_GRAM_SIZE = 3            # 三元组：2 字太松（「中国」能救回任何页面），4 字太严
# 段≥这个长度才派生滑窗三元组。5 是席 S-T-SEARCHQ-1 的原值，实测被自己的锁推翻：
# 「今天黄金价格多少钱一克」按多字脚手架**切**开后段是「黄金价格」（4 字），
# 5 的门槛让它只留整段、派生不出「黄金价」，页面写「黄金 价格」空格变体即判无关。
# 放到 4 后在 88 条真实命中上复跑：与 5 的取舍结果**逐格相同**（席报告 §4 变体 C/D），
# 也就是这枚旋钮不是本病的那根杠杆，改它的唯一理由是让上面那条空格变体不再判无关。
_GRAM_MIN_SEGMENT = 4
_MIN_EVIDENCE_CHARS = 2
# --- 相关性地板的分值表（2026-09-26 S-T-SEARCHQ-2 定稿）--------------------------
# 量纲：一枚实体整名对上算强证据，只对上派生形态（滑窗三元组/去脚手架段）算弱证据，
# 每枚查询实体至多计一次分。地板按实体枚数分两级：
#   实体 ≤3 枚 ⇒ 3 分 = 允许「一枚强」**或**「两枚弱」（主代理代补时写的这条规则，
#                量纲换成 3/2 之后仍然逐字成立）
#   实体 ≥4 枚 ⇒ 4 分（问句越具体，两条不相干的短词偶然对上越不该放行）
# 为什么单枚 2 字弱形态（「中国」「每月」）永远不够：实测「中国个人所得税起征点是
# 多少 2026」唯一被旧闸门留下的就是靠「中国」对上标题的「中国地图 - 八九网」
# （席 S-T-SEARCHQ-1 §3.3 F2），而 2 字串在中文页面上几乎必然出现。
# 为什么严档的门槛是 4 枚而不是 3 枚：`tests/test_search_chinese_relevance.py` 两处
# 实测锁同时要求「3 枚实体的问句地板印 3」与「两枚 2 字弱实体（降准+落地）必须留住」，
# 3 枚就切严档会当场把后一条打红——档位边界由既有实测夹具钉着，不是拍的。
# ⚠ 本块曾有两份定义（本席与主代理 02:07 的代补各写一份，同名静默覆盖＝同型事故
# 二次发生，台账 #53 已记过一次）。此处只留一份；代补那组值（2/1/2/4 且严档 3 枚起）
# 与上述两把锁不相容，已由本席量化轮复核后替换。
_STRONG_EVIDENCE = 3
_WEAK_EVIDENCE = 2
_RICH_TOKEN_COUNT = 4       # 实体数达到这个量就用严档地板
_FLOOR_SHORT = 3
_FLOOR_RICH = 4
# 审计行的长度上限（只影响日志条数，不影响任何判定）。
_AUDIT_MAX_RECORDS = 8
_AUDIT_MAX_FORMS = 3
# --- 有向别名表：同一个命名实体的「问句里这么写 / 页面里那么写」-------------------
# 为什么需要：中文时效问句常写简称（综指/央行/美联储），权威页面写全称（指数/
# 中国人民银行/联邦储备）。地板量的是字面形态，简称对不上全称 ⇒ 实测 8 条全判 2 分
# 未达地板，其中 5 条恰恰是正解（东方财富/新浪/雪球/百度财经的上证指数行情页，
# 见席 S-T-SEARCHQ-2 §4 手工标注）。这条损失与「闸门太严」无关，是**词形通道缺失**。
# 三条自律（越界就把表害成第二真身）：
#   ① **有向**：只登记「简称 ⇒ 它的全称」，反向不放（问句写「指数」绝不用「综指」凑，
#      因为消费者价格指数不是综合指数）；
#   ② 只收**同一命名实体**的书写差异，不收"话题相近"（「银行」「行情」「指数」这类
#      通用词一律不做别名目标——那会把任何财经页放回来）；
#   ③ 别名只**追加形态**，不改地板、不改低质规则，且在审计行里以 `问句词~别名`
#      的形态显式留名（用了哪条别名一目了然，不是静默放宽）。
_QUERY_ALIAS_FORMS: dict[str, tuple[str, ...]] = {
    "综指": ("指数",),
    "央行": ("人民银行", "中央银行"),
    "美联储": ("联邦储备",),
    "道指": ("道琼斯",),
    "纳指": ("纳斯达克",),
    "标普": ("标准普尔",),
    "证监会": ("证券监督管理委员会",),
    "科创板": ("科创版",),
}
_MIN_ALIAS_CHARS = 2


def _with_alias_forms(
    strong: tuple[str, ...], weak: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """把已有形态查表扩出别名形态（≥3 字进强档、2 字进弱档，与原生形态同一量纲）。"""
    extra: list[str] = []
    for form in (*strong, *weak):
        for target in _QUERY_ALIAS_FORMS.get(form, ()):
            if len(target) >= _MIN_ALIAS_CHARS:
                extra.append(target)
    if not extra:
        return strong, weak
    return (
        tuple(dict.fromkeys((*strong, *(t for t in extra if len(t) >= 3)))),
        tuple(dict.fromkeys((*weak, *(t for t in extra if len(t) == 2)))),
    )
_DATE_STAMP_RES = (
    # 结果页/摘要里的显式日期（Bing 免 key 摘要实测就带 "1 天前 ·"／"2026年9月17日 ·"）
    re.compile(r"20[0-9]{2}\s*[-/年]\s*[0-1]?[0-9]\s*[-/月]\s*[0-3]?[0-9]"),
    re.compile(r"20[0-9]{2}\s*[-/年]\s*[0-1]?[0-9]\s*月?"),
    re.compile(r"(?:/|_)(?:20[0-9]{2})[-/]?(?:0[1-9]|1[0-2])(?:[-/]?(?:[0-2][0-9]|3[01]))?(?:/|_)"),
    re.compile(r"[0-1]?\d\s*(?:小时|分钟|day|days)\s*(?:前|之前|ago)", re.IGNORECASE),
    re.compile(r"[0-3]?\d\s*(?:天|周|月)\s*(?:前|之前)", re.IGNORECASE),
)
_DDG_CHALLENGE_MARKERS = (
    "please complete the following challenge",
    "confirm this search was made by a human",
    "select all squares containing a duck",
)
_DDG_BLOCK_WARN_COOLDOWN_SECONDS = 600.0
_ddg_block_last_warned = 0.0


def _query_tokens(query: str) -> list[str]:
    """按空白与中文标点切 token（只做切分，不做判断）。"""
    tokens = re.split(r"[\s，,、。；;：:！!？?（）()「」『』\"']+", query or "")
    return [token for token in tokens if len(token) >= _MIN_EVIDENCE_CHARS]


def _scaffold_split(run: str) -> list[str]:
    """把一个中文连串剥成实体段：先剥多字脚手架，再按单字脚手架切开。

    多字表**按字面长度降序**应用：``什么时候`` 必须先于 ``什么``/``时候`` 剥掉，
    否则先切短的会把串撕成 ``候发布`` 这类拼出来的假段。
    """
    pieces = [run]
    for word in sorted(_CJK_SCAFFOLD_WORDS, key=len, reverse=True):
        pieces = [part for piece in pieces for part in piece.split(word)]
    pieces = [part for piece in pieces for part in _CJK_SCAFFOLD_RE.split(piece)]
    return [piece for piece in pieces if len(piece) >= _MIN_EVIDENCE_CHARS]


def _token_evidence_forms(token: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """一枚查询 token 的实体形态：`(强形态, 弱形态)`（都已 casefold）。

    中文侧：先剥脚手架成段，段≥3 字算强形态，段≥5 字再加滑窗三元组（治「实体
    嵌在整串问句里」——实测就是这么丢掉的财联社/央视议息页）；段恰好 2 字算弱形态。
    ASCII 侧：≥4 字符算强，2-3 字符算弱；纯数字（年份装饰）永不构成形态。
    整枚都是脚手架（「是多少」「什么」）或落在装饰词表里 ⇒ 两个空表 ⇒ 该 token
    **既不加分也不参与地板档位的计算**。
    """
    cleaned = str(token or "").strip().casefold()
    if not cleaned or cleaned in _QUERY_STOP_TOKENS:
        return (), ()
    strong: list[str] = []
    weak: list[str] = []
    cjk = "".join(_CJK_CHAR_RE.findall(cleaned))
    if cjk and cjk not in _QUERY_STOP_TOKENS:
        for segment in _scaffold_split(cjk):
            if len(segment) >= _GRAM_MIN_SEGMENT:
                strong.append(segment)
                strong.extend(
                    segment[start : start + _GRAM_SIZE]
                    for start in range(len(segment) - _GRAM_SIZE + 1)
                )
            elif len(segment) >= 3:
                strong.append(segment)
            elif len(segment) == _MIN_EVIDENCE_CHARS:
                weak.append(segment)
    for bit in re.split(r"[^0-9a-z.\-+/_%]+", cleaned):
        if not bit or bit.isdigit() or bit in _QUERY_STOP_TOKENS:
            continue
        if len(bit) >= 4:
            strong.append(bit)
        elif len(bit) >= _MIN_EVIDENCE_CHARS:
            weak.append(bit)
    return _with_alias_forms(tuple(dict.fromkeys(strong)), tuple(dict.fromkeys(weak)))


def _query_entity_forms(query: str) -> list[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]]:
    """`(token, (强形态, 弱形态))` 列表，只保留拿得出实体的 token。"""
    out: list[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]] = []
    for token in _query_tokens(query):
        forms = _token_evidence_forms(token)
        if forms[0] or forms[1]:
            out.append((token, forms))
    return out


def _clean_text(value: str) -> str:
    """解码 HTML 实体并把所有连续空白归一为单个空格。"""
    return " ".join(html.unescape(value or "").split())


def _hit_text(hit: WebSearchHit) -> str:
    return _clean_text(f"{hit.title} {hit.snippet}")


def _hit_comparable_text(hit: WebSearchHit) -> str:
    """参与实体比对的文本（casefold）：ASCII 实体不再大小写敏感。"""
    return _hit_text(hit).casefold()


def _domain_priority(hit: WebSearchHit, query: str = "") -> tuple[int, str]:
    """来源域名排序键（数值越小越靠前）；真身见 ``source_authority``。

    2026-09-25 第 3 项接线：此前只认识百科域名，非百科结果一律同档、再按**域名
    字母序**定序，于是 ``blog.example.com`` 会排在 ``federalreserve.gov`` 前面。
    """
    return order_key(hit.source_domain, query)


def _hit_is_dated(hit: WebSearchHit) -> bool:
    """这条命中带不带**可核对的发表日期**（标题/摘要/URL 任一处）。

    只判形态、不解析成时刻，因此不读时钟、无跨日漂移；「带日期」在这里的含义是
    「上层与用户能据此判断这条有多新」，不是「本席算出了它新」。
    """
    blob = f"{hit.url} {_hit_text(hit)}"
    return any(pattern.search(blob) for pattern in _DATE_STAMP_RES)


def _relevance_evidence(
    text: str,
    forms: list[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]],
) -> tuple[int, list[str]]:
    """一条命中对整条问句的实体证据：`(分数, 对上的实体名)`，每枚 token 至多计一次分。

    第二项是为**可审计**而存在的：地板丢件时必须能说清「丢的是哪条、为什么」，
    只报一个计数等于没报（席 S-T-SEARCHQ-1 §3.2 那次 55 条丢 51 条，现场一行看不见，
    是靠事后手写探针才复现出来的）。
    """
    score = 0
    matched: list[str] = []
    for token, (strong, weak) in forms:
        hit_strong = next((form for form in strong if form in text), None)
        if hit_strong is not None:
            score += _STRONG_EVIDENCE
            matched.append(f"{token}~{hit_strong}")
            continue
        hit_weak = next((form for form in weak if form in text), None)
        if hit_weak is not None:
            score += _WEAK_EVIDENCE
            matched.append(f"{token}~{hit_weak}")
    return score, matched


def _relevance_score(text: str, forms: list[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]]) -> int:
    """实体证据分（只要数值的那条腿，排序与探针都用它）。"""
    return _relevance_evidence(text, forms)[0]


def _audit_trail(
    hits: list[WebSearchHit],
    forms: list[tuple[str, tuple[tuple[str, ...], tuple[str, ...]]]],
    *,
    floor: int,
    junk: frozenset[int],
) -> str:
    """把这一批每一条的命运写成一行可 grep 的账：`分数/裁决/对上的实体`。

    裁决字母：``k`` 留下、``f`` 未达地板、``x`` 低质域剔除、``fx`` 两者都不过。
    **本函数只描述，不改变任何判定**——它读的是既有判据的输入输出，不新建第二套
    相关性标准（同 `source_authority` 只做域名阶梯、不碰相关性那条纪律）。
    条数与实体名都限量，防止一条超长问句把日志撑爆；截断时显式写 ``+N``，
    不假装列全了。
    """
    records: list[str] = []
    for index, hit in enumerate(hits):
        score, matched = _relevance_evidence(_hit_comparable_text(hit), forms)
        is_junk = index in junk
        if is_junk:
            verdict = "fx" if score < floor else "x"
        else:
            verdict = "f" if score < floor else "k"
        shown = ",".join(matched[:_AUDIT_MAX_FORMS]) or "-"
        records.append(
            f"{hit.source_domain or '?'}|{score}{verdict}|{shown}"
            + (f"+{len(matched) - _AUDIT_MAX_FORMS}" if len(matched) > _AUDIT_MAX_FORMS else "")
        )
    head = records[:_AUDIT_MAX_RECORDS]
    tail = f"+{len(records) - len(head)}" if len(records) > len(head) else ""
    return " ".join(head) + tail


def _order_for_reading(hits: list[WebSearchHit], query: str) -> list[WebSearchHit]:
    """权威档为主序；问句要新时，同档内带日期的先给模型看。

    两半各守一条不变量：**时效永不越过权威档**（一手源的无日期页仍排在
    无名站的有日期页前面），**权威也永不把无关结果抬进块里**（这一函数只在
    过了地板的集合内部排序）。排序键全是既有件：档级真身
    ``source_authority.order_key``，时效信号真身 ``search_intent.detect_query_recency``。
    """
    wants_latest = detect_query_recency(query).wants_latest
    # Python 排序稳定：同键结果保持抓取顺序，整体确定、可测试。
    return sorted(
        hits,
        key=lambda hit: (
            *_domain_priority(hit, query),
            0 if (wants_latest and _hit_is_dated(hit)) else 1,
        ),
    )


def _filter_relevant(hits: list[WebSearchHit], query: str) -> list[WebSearchHit]:
    """相关性地板：剥掉装饰后按**实体证据分**判定，整批不达地板就当没查到。

    与旧实现的三处差别，各由席报告里一条实测支撑：
    ① 中文连串按段/三元组取证（旧写法要求整枚 8-13 字串原样出现在标题里，
       真实页面永远不这么写 ⇒ 又新又对的页被整批判空，§3.3 F1）；
    ② 年份与时效装饰不再算实体证据（旧写法靠它们凑地板 ⇒ 「中国地图」进了
       个税问题的块，§3.3 F2）；
    ③ 丢件**逐条**进日志审计行（此前 55 条丢 51 条、9/11 查询整批判空，现场一行
       看不见，只能靠事后手写探针复现——现在 `audit=` 里每条都有分数与裁决）。
    拿不到实体（英文单名、极短问句）时不抬门槛＝fail-open，行为与旧一致。
    """
    junk = _junk_positions(hits)
    kept = [hit for position, hit in enumerate(hits) if position not in junk]
    junk_dropped = len(junk)
    forms = _query_entity_forms(query)
    if not forms:
        if junk_dropped:
            logger.info(
                "relevance gate: no entity extractable, kept %d hit(s) after junk filter only",
                len(kept),
            )
        return _order_for_reading(kept, query)
    floor = _FLOOR_RICH if len(forms) >= _RICH_TOKEN_COUNT else _FLOOR_SHORT
    scores = [_relevance_score(_hit_comparable_text(hit), forms) for hit in hits]
    matched = [
        hit
        for position, hit in enumerate(hits)
        if position not in junk and scores[position] >= floor
    ]
    # 两把镜头量的是同一批、但**不互斥**：`dropped_as_junk` 只数域名/字典标记命中的，
    # `dropped_by_floor` 数整批里不达地板的（含同时是低质域的那些）。交集才是最有信息量
    # 的那一格——「既是个字典农场、又跟问句无关」，两把各自都能指出来。
    floor_dropped = sum(1 for score in scores if score < floor)
    audit = _audit_trail(hits, forms, floor=floor, junk=junk)
    if floor_dropped or junk_dropped:
        logger.info(
            "relevance gate: entities=%d floor=%d kept=%d dropped_by_floor=%d "
            "dropped_as_junk=%d audit=%s query=%r",
            len(forms),
            floor,
            len(matched),
            floor_dropped,
            junk_dropped,
            audit,
            query[:60],
        )
    elif hits:
        # 一条没丢时账目降到 DEBUG：留着「这条为什么被选上」的可取回路径，
        # 但不在常态检索上刷 INFO。
        logger.debug(
            "relevance gate: entities=%d floor=%d kept=%d audit=%s query=%r",
            len(forms),
            floor,
            len(matched),
            audit,
            query[:60],
        )
    if not matched:
        # 一条实体都对不上 ⇒ 当没查到，由上层既有披露路径老实说「本轮未检索到相关内容」。
        # 旧写法在中文连串上必然走到这里（§3.3 F1），是 47% 空手而归的一半成因。
        return []
    return _order_for_reading(matched, query)


def _note_ddg_challenge(html_text: str) -> None:
    """链头 DuckDuckGo 交回**人机验证页**时点名一次（600s 抑制，防刷屏）。

    实测成因（席报告 §3.1）：`html.duckduckgo.com` 对 11/11 个中文时效查询都回
    同一张 "Please complete the following challenge … Select all squares
    containing a duck" 页面，`result__a` 出现 0 次 ⇒ 解析器永远返回空表。
    这不是解析 bug，加 `kl`/`df` 一类的参数也救不回来，所以本函数**只观测不改行为**：
    返回空表照旧由链回退到下一家，但「链头这家今天是死的」第一次变得在日志里看得见。
    抑制窗口与运维告警同量级；判定只用既有页面的英文字面标记，不再新建第二套判据。
    """
    global _ddg_block_last_warned  # 单进程观测节流，刻意全局
    if not html_text:
        return
    lowered = html_text[:20000].lower()
    if not any(marker in lowered for marker in _DDG_CHALLENGE_MARKERS):
        return
    now = time.monotonic()
    if now - _ddg_block_last_warned < _DDG_BLOCK_WARN_COOLDOWN_SECONDS:
        return
    _ddg_block_last_warned = now
    logger.warning(
        "key-free engine ddg returned an anti-bot challenge page instead of results; "
        "every search falls through to the next provider (cooldown %.0fs)",
        _DDG_BLOCK_WARN_COOLDOWN_SECONDS,
    )


def _is_junk(hit: WebSearchHit) -> bool:
    domain = (hit.source_domain or "").lower()
    if domain in _JUNK_DOMAINS:
        return True
    text = _hit_text(hit)
    return any(
        marker in text
        for marker in ("汉语汉字", "拼音", "笔顺", "部首", "新华字典")
    )


def _junk_positions(hits: list[WebSearchHit]) -> frozenset[int]:
    """低质条目在批内的下标（``_is_junk`` 一条只算一次，判定与审计共用同一份）。"""
    return frozenset(position for position, hit in enumerate(hits) if _is_junk(hit))


def fetch_page_text(
    url: str,
    *,
    proxy: str = "",
    timeout_seconds: float = 6.0,
    max_chars: int = 800,
) -> str:
    """打开最相关结果页面并抽取正文（去标签），失败返回空串。

    安全：入参 URL 来自第三方搜索结果（可被上游响应替换、可 302），属用户可控面。
    抓取前必须过中央 SSRF 咽喉——拒绝内网 / 云元数据（169.254.169.254）/ 保留网段 /
    非法协议（file:// 等），含整型 IP 归一与「解析失败=拒绝」；并挂逐跳重定向复查钩子，
    公网 URL 跳向内网亦在发出前拦下。被拦或失败一律静默返回空串，绝不回显内网响应。
    """
    if not url:
        return ""
    if _ssrf_rejection_for_fetch(url) is not None:
        return ""
    html_text = _fetch(
        url, proxy=proxy, timeout_seconds=timeout_seconds, ssrf_guard=True
    )
    if not html_text:
        return ""
    text = _HTML_COMMENT_RE.sub(" ", html_text)
    text = _HTML_HIDDEN_BLOCK_RE.sub(" ", text)
    text = _HTML_UNCLOSED_COMMENT_RE.sub(" ", text)
    text = _HTML_UNCLOSED_HIDDEN_RE.sub(" ", text)
    # 可观测护栏：兜底剥离吃掉大半页面时记 warning（评审 M1）。多数情况意味着
    # 命中的是畸形/void 标签而非真截断残段，便于现场发现"正文莫名变空"。
    # 注意：字面 `%` 必须写成 `%%`——logging 走的是 `%` 式惰性格式化。
    if html_text and len(text) < len(html_text) * (1.0 - _HTML_STRIP_RATIO_WARN):
        logger.warning(
            "page text stripped more than %d%%: url=%s before=%d after=%d",
            int(_HTML_STRIP_RATIO_WARN * 100),
            url,
            len(html_text),
            len(text),
        )
    text = _HTML_BOILERPLATE_BLOCK_RE.sub(" ", text)
    text = _HTML_HEAD_BLOCK_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub("\n", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 12]
    return "\n".join(lines)[:max_chars]


class DuckDuckGoWebSearchProvider:
    """免费 DuckDuckGo HTML 搜索（无 key）。"""

    name = "ddg"

    def __init__(
        self,
        *,
        timeout_seconds: float = 3.0,
        proxy: str = "",
        ssrf_guard: bool = False,
    ) -> None:
        """`ssrf_guard` 缺省 **False**＝既有行为逐字节不变。

        置 True 时复用席 W18 的逐跳咽喉（`_build_sync_client(..., ssrf_guard=True)`
        → `_ssrf_request_guard` → 中央 `guard_user_url`），初始请求与每一跳重定向
        发出前都过中央判定；本仓不新建第二套 URL 判据。仅 config 链尾的免 key
        兜底（`GuardedKeyFreeWebSearchProvider`）会置 True。
        """
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.proxy = str(proxy or "")
        self._ssrf_guard = bool(ssrf_guard)
        self._client: httpx.Client | None = None

    def _url_for(self, term: str) -> str:
        return "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(term)

    def _get_client(self) -> httpx.Client:
        """惰性创建并复用同步客户端，保持 keep-alive 连接池。"""
        if self._client is None or self._client.is_closed:
            self._client = _build_sync_client(
                self.proxy, self.timeout_seconds, ssrf_guard=self._ssrf_guard
            )
        return self._client

    def close(self) -> None:
        """释放内部连接池；幂等，关闭后下次检索会重建。"""
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = _fetch(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=self._get_client(),
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        _note_ddg_challenge(html_text)
        return _filter_relevant(
            _extract_ddg_hits(html_text, max_results=max_results), term
        )

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索；复用调用方传入的 AsyncClient 以共享连接池。"""
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = await _fetch_async(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=client,
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        _note_ddg_challenge(html_text)
        return _filter_relevant(
            _extract_ddg_hits(html_text, max_results=max_results), term
        )


class BingWebSearchProvider:
    """Bing 国际版 HTML 搜索（无 key，作为 DDG 不可用时的备份）。"""

    name = "bing"

    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        proxy: str = "",
        ssrf_guard: bool = False,
    ) -> None:
        """`ssrf_guard` 语义与 `DuckDuckGoWebSearchProvider` 同源（缺省 False＝现状）。"""
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.proxy = str(proxy or "")
        self._ssrf_guard = bool(ssrf_guard)
        self._client: httpx.Client | None = None

    def _url_for(self, term: str) -> str:
        return (
            "https://www.bing.com/search?q="
            + urllib.parse.quote(term)
            + "&setlang=zh-cn&count=10"
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = _build_sync_client(
                self.proxy, self.timeout_seconds, ssrf_guard=self._ssrf_guard
            )
        return self._client

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = _fetch(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=self._get_client(),
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_bing_hits(html_text, max_results=max_results), term
        )

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索（DDG 失败后的 Bing 兜底同样支持）。"""
        term = (query or "").strip()
        if not term:
            return []
        try:
            html_text = await _fetch_async(
                self._url_for(term),
                proxy=self.proxy,
                timeout_seconds=self.timeout_seconds,
                client=client,
            )
        except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
            return []
        if not html_text:
            return []
        return _filter_relevant(
            _extract_bing_hits(html_text, max_results=max_results), term
        )



# 搜索结果质量过滤（对标 tavily 插件社区的"污染源"处理思路）：
# 低质域名直接剔除；snippet 过短的结果降权排后而非丢弃（保序稳定过滤）。
_LOW_QUALITY_URL_RE = re.compile(
    r"(?:pinterest\.|csdn\.net/.*/(login|vip)|quora\.com/(?!Profile)|answers\.microsoft\.com|"
    r"baidu\.com/(?:link|s\?)|so\.com/link|verydemo|fx361|docin|doc88|renrendoc|book118)",
    re.IGNORECASE,
)
_MIN_SNIPPET_CHARS = 24


def _drop_ssrf_rejected_hits(
    hits: list[WebSearchHit], *, provider_name: str
) -> list[WebSearchHit]:
    """免 key 路径的结果 URL 出口咽喉：**逐条**过中央判定后再发布。

    复用席 W18 的入口包装 `_ssrf_rejection_for_fetch`（其真身是
    `domains/files/sources/downloader.check_download_url` + `ssrf_guard` 同族
    inet_aton 归一），本函数不做任何自己的 URL 判据、不新建第二套真身。
    为什么免 key 路径需要这一层：DDG/Bing 的命中来自 **HTML 解析**，`url` 字段
    完全由第三方响应文本决定（可被上游替换、可写 `http://169.254.169.254/`、
    可写十进制混淆 `http://2130706433/`）；key 类提供器走 JSON 契约
    （`normalize_search_results`），两者信任面不同。
    被拒者剔除并计数记一条 warning（只报数量与提供器名，绝不回显 URL 内容）。
    """
    kept: list[WebSearchHit] = []
    dropped = 0
    for hit in hits:
        if _ssrf_rejection_for_fetch(hit.url or "") is not None:
            dropped += 1
            continue
        kept.append(hit)
    if dropped:
        logger.warning(
            "key-free search provider %s dropped %d SSRF-rejected result url(s)",
            provider_name,
            dropped,
        )
    return kept


class GuardedKeyFreeWebSearchProvider:
    """config 链尾的免 key 兜底形态：内层原样提供器 + 结果 URL 中央咽喉过滤。

    只做两件事，且都**委托**既有中央件（禁第二真身的自我约束）：
    ① 内层提供器以 `ssrf_guard=True` 构造 ⇒ 引擎请求逐跳过 `_ssrf_request_guard`；
    ② 返回的 hits 逐条过 `_ssrf_rejection_for_fetch` ⇒ 内网/元数据/混淆地址形态
      的结果 URL 不会作为「可抓取目标」进入下游（下游 `fetch_page_text` 那一腿
      本就有同一咽喉，这里是把拒绝点提前到「发布结果」之前，同一判据不是新增判据）。

    `name` 透传内层，保证 `ChainedWebSearchProvider.last_provider_name` 的
    可观测口径不变（仍是 `ddg` / `bing`）。**不用于** config 缺失的 MCP 直调路径
    （那条路今天的形态逐字节保持，见 `_build_chained_provider` 的 `config is None` 分支）。
    """

    def __init__(self, inner: WebSearchProvider) -> None:
        self._inner = inner
        self.name = f"{getattr(inner, 'name', 'keyfree')}"
        self.timeout_seconds = float(getattr(inner, "timeout_seconds", 0.0) or 0.0)
        self.proxy = str(getattr(inner, "proxy", "") or "")

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        return _drop_ssrf_rejected_hits(
            self._inner.search(query, max_results=max_results),
            provider_name=self.name,
        )

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索同样过滤（异步链是本兜底的消费面之一，不留缺口）。"""
        method = getattr(self._inner, "search_async", None)
        if callable(method):
            hits = await method(query, max_results=max_results, client=client)
        else:
            hits = self._inner.search(query, max_results=max_results)
        return _drop_ssrf_rejected_hits(hits, provider_name=self.name)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()


def filter_search_hits(hits: list[WebSearchHit]) -> list[WebSearchHit]:
    """剔除低质域名与无摘要命中；保持原相对顺序。"""
    kept: list[WebSearchHit] = []
    deferred: list[WebSearchHit] = []
    for hit in hits:
        url = hit.url or ""
        if _LOW_QUALITY_URL_RE.search(url):
            continue
        snippet = (hit.snippet or "").strip()
        if len(snippet) < _MIN_SNIPPET_CHARS and not hit.title:
            continue
        if len(snippet) < _MIN_SNIPPET_CHARS:
            deferred.append(hit)
        else:
            kept.append(hit)
    return kept + deferred


def gate_chain_hits(hits: list[WebSearchHit], query: str) -> list[WebSearchHit]:
    """链级唯一执法口：低质/短摘要剔除 + 相关性闸门 + 域名加权。

    为什么放在链上而不是逐个供应商里补：此前 `_filter_relevant` 只接在 DuckDuckGo
    与 Bing（免 key 两家）里，**生产链走的 Tavily/You/LangSearch 一条都没过**；
    而链的异步出口连 `filter_search_hits` 都没走。同一不变量补在 N 个点必然漏一个，
    故统一收到链的唯一出口——各家自备的过滤保持幂等（同一函数二次调用结果不变）。
    """
    return _filter_relevant(filter_search_hits(hits), query)


class ChainedWebSearchProvider:
    """按顺序尝试多个提供器，任一命中即返回；记录命中的提供器名。

    同步 search 结果带 TTL 缓存：时效/百科类问题常被反复追问，而
    检索链最坏 5 查询×3 源全计费计时；600s 内同查询直接复用（与
    meme 梗检索 DDG 缓存同量级）。异步路径（工具循环）不缓存。
    """

    _CACHE_TTL_SECONDS = 600.0
    _CACHE_MAX_ENTRIES = 256

    def __init__(
        self,
        providers: list[WebSearchProvider],
        *,
        timeout_seconds: float = 5.0,
        proxy: str = "",
        page_fetcher: object | None = None,
        latest_time_range: str = "",
    ) -> None:
        self.providers = providers
        self.timeout_seconds = timeout_seconds
        self.proxy = proxy
        self.page_fetcher = page_fetcher
        self.last_provider_name = ""
        # 请求级时效窗（WEBCFG-AUDIT E-3）：仅当**非空**且查询被认出**明示**
        # 时效词、且 provider 声明 ``accepts_extra_body`` 时，才在该次请求
        # 追加 ``{"time_range": ...}``；缺省空＝整层不通电，链行为与改前逐字节一致。
        self._latest_time_range = str(latest_time_range or "").strip()
        self._search_cache: dict[tuple[str, int], tuple[float, list[WebSearchHit]]] = {}
        self._search_cache_lock = threading.Lock()

    def _extra_body_for(self, provider: object, query: str) -> dict[str, str] | None:
        """本次请求要不要带时效窗、带多少——三重闸，任一不满足即 None（现状）。

        判据刻意分三层（注毒自证锁 ``tests/test_webcfg_e3_latest_time_range.py``
        逐闸钉死）：开关值非空；查询**明示**要最新（裸年份的历史题绝不在列——
        ``wants_latest`` 不等价于 ``explicit_latest``，把 2019 票房题锁进周窗是错的）；
        provider 自声明吃得下 ``extra_body``（免 key 引擎结构上无此参数）。
        """
        if not self._latest_time_range:
            return None
        if not getattr(provider, "accepts_extra_body", False):
            return None
        if not detect_query_recency(query).explicit_latest:
            return None
        return {"time_range": self._latest_time_range}

    def _invoke_search(
        self,
        provider: WebSearchProvider,
        query: str,
        max_results: int,
        extra_body: dict[str, str] | None,
    ) -> list[WebSearchHit]:
        """按家调用同步 search；extra_body 非 None 时开请求级追加层通道。

        Protocol 面（``WebSearchProvider``）不声明 ``extra_body``——只有经
        ``_extra_body_for`` 三闸验明 ``accepts_extra_body`` 的形态才走到这条路，
        类型面上以局部 Any 收窄，绝不放宽 Protocol 本体签名（免 key 引擎们
        结构上没有该参数，Protocol 加进去反而撒谎）。
        """
        if extra_body is not None:
            targeted: Any = provider
            return list(targeted.search(query, max_results=max_results, extra_body=extra_body))
        return provider.search(query, max_results=max_results)

    def _cache_get(self, key: tuple[str, int]) -> list[WebSearchHit] | None:
        now = time.monotonic()
        with self._search_cache_lock:
            hit = self._search_cache.get(key)
        if hit is None or now - hit[0] >= self._CACHE_TTL_SECONDS:
            return None
        return list(hit[1])

    def _cache_put(self, key: tuple[str, int], hits: list[WebSearchHit]) -> None:
        with self._search_cache_lock:
            if len(self._search_cache) >= self._CACHE_MAX_ENTRIES:
                self._search_cache.clear()
            self._search_cache[key] = (time.monotonic(), list(hits))

    def fetch_page_text(self, url: str, *, max_chars: int = 800) -> str:
        fetcher = self.page_fetcher
        method = getattr(fetcher, "fetch_page_text", None)
        if callable(method):
            text = str(method(url, max_chars=max_chars) or "")
            if text:
                return text

        return fetch_page_text(
            url,
            proxy=self.proxy,
            timeout_seconds=self.timeout_seconds,
            max_chars=max_chars,
        )
    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        cache_key = (query, max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        for provider in self.providers:
            extra_body = self._extra_body_for(provider, query)
            try:
                hits = self._invoke_search(provider, query, max_results, extra_body)
            except Exception:  # noqa: BLE001 - 单提供器失败回退下一提供器。
                hits = []
            filtered = gate_chain_hits(hits, query) if hits else []
            if filtered:
                # 只有"过闸后仍非空"才算这家命中：全被相关性闸门判无关时继续回退下一家，
                # 而不是把空结果当成功返回（旧写法 if hits 会在无关结果上就地收兵）。
                self.last_provider_name = str(getattr(provider, "name", "unknown"))
                self._cache_put(cache_key, filtered)
                return filtered
        return []

    async def search_async(
        self,
        query: str,
        *,
        max_results: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> list[WebSearchHit]:
        """异步检索链；语义与同步 ``search`` 逐条对齐（同一唯一执法口、同样按家回退）。

        旧写法这里**直接返回原始 hits**——既没过低质剔除也没过相关性闸门，
        是"同一个不变量在两条路径上一处执法一处不执法"的半程形。
        """
        for provider in self.providers:
            extra_body = self._extra_body_for(provider, query)
            try:
                method = getattr(provider, "search_async", None)
                if callable(method):
                    hits = await method(query, max_results=max_results, client=client)
                else:
                    hits = self._invoke_search(provider, query, max_results, extra_body)
            except Exception:  # noqa: BLE001 - 单提供器失败回退下一提供器。
                hits = []
            filtered = gate_chain_hits(hits, query) if hits else []
            if filtered:
                self.last_provider_name = str(getattr(provider, "name", "unknown"))
                return filtered
        return []

    def close(self) -> None:
        """关闭内部各提供器的连接池（幂等）。"""
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001, S110 - 关闭失败忽略。
                    pass


__all__ = [
    "LangSearchWebSearchProvider",
    "TavilyWebSearchProvider",
    "TinyFishFetchProvider",
    "TinyFishWebSearchProvider",
    "YouSearchProvider",
]

from plugins.bot_unified_runtime.domains.core.search.search_api import (
    LangSearchWebSearchProvider,
    TavilyWebSearchProvider,
    TinyFishFetchProvider,
    TinyFishWebSearchProvider,
    YouSearchProvider,
    build_api_search_provider,
)

_KEYFREE_TAIL_CONFIG_FIELD = "bot_web_search_keyfree_fallback_enabled"
_LATEST_TIME_RANGE_CONFIG_FIELD = "bot_web_search_tavily_time_range"


def resolve_latest_time_range(config: object | None) -> str:
    """请求级时效窗开关的**唯一**读点（缺省空＝不通电）。

    与 ``keyfree_fallback_enabled`` 同款读法：``getattr(config, <字段名>, "")``
    ⇒ 字段缺席恒为空串，链逐字节现状（反向锁 ``tests/test_webcfg_e3_latest_time_range.py``）。
    值本身沿用装配期既有配置面 ``bot_web_search_tavily_time_range``（day/week/month/year），
    不新建第二枚键；通电与否由调用方（链构造）决定，本函数只读不做判断。
    """
    if config is None:
        return ""
    return str(getattr(config, _LATEST_TIME_RANGE_CONFIG_FIELD, "") or "").strip()


def keyfree_fallback_enabled(config: object | None) -> bool:
    """免 key 尾部兜底的**唯一**开关读点（缺省关）。

    读法是刻意的：`getattr(config, <字段名>, False)` ⇒ 字段尚未落进 `config.py`
    之前恒为 False，本格落地后生产链构造结果与改前逐字节一致（反向锁
    `tests/test_web_search_keyfree_fallback.py` 锁死）。真要通电，由主会话把
    `_KEYFREE_TAIL_CONFIG_FIELD` 这一枚字段按「四处同生」落进配置面（交接段见
    席报告 §5）。开关只在装配期读一次（链一旦构造即固化），属「需重启」语义面。
    """
    if config is None:
        return False
    return bool(getattr(config, _KEYFREE_TAIL_CONFIG_FIELD, False))


def _build_keyfree_fallback_providers(
    timeout_seconds: float, proxy: str
) -> list[WebSearchProvider]:
    """构造 config 链尾的免 key 兜底（DDG → Bing，顺序即优先级）。

    超时沿用链的 `timeout_seconds`（与 `config is None` 那条既有分支同一口径），
    不引入第二个超时真身；`ssrf_guard=True` 是**新增路径专属**的加严，
    缺省构造（MCP 直调、`search_async`）仍是 False＝现状。
    """
    return [
        GuardedKeyFreeWebSearchProvider(
            DuckDuckGoWebSearchProvider(
                timeout_seconds=timeout_seconds, proxy=proxy, ssrf_guard=True
            )
        ),
        GuardedKeyFreeWebSearchProvider(
            BingWebSearchProvider(
                timeout_seconds=timeout_seconds, proxy=proxy, ssrf_guard=True
            )
        ),
    ]


def _compose_chain_providers(
    key_providers: Sequence[WebSearchProvider],
    config: object | None,
    timeout_seconds: float,
    proxy: str,
) -> list[WebSearchProvider]:
    """**唯一**的「key 链 + 免 key 尾兜」拼接真身（顺序与开关都只在这里决定）。

    不变量（各由一条锁钉死，见 `tests/test_web_search_keyfree_fallback.py`）：
    ① 缺省（配置面尚无该字段）⇒ 原样返回 key 链，一条元素都不多＝逐字节现状；
    ② 开态 ⇒ 免 key 兜底**只追加在尾部**，绝不插到 key 家之前（key 是主力）；
    ③ 兜底内部顺序恒为 ddg → bing。
    """
    chain = list(key_providers)
    if keyfree_fallback_enabled(config):
        # 尾部兜底：恒定追加在 key 类提供器**之后**（key 仍是主力，不并行抢跑、不改序）。
        # 动机＝`build_api_search_provider` 对缺 key 的供应商静默跳过，最坏情形
        # 「开关开着、链是空的」；三家任一配额耗尽/网络故障时这里还有一层不花钱的落点。
        chain.extend(_build_keyfree_fallback_providers(timeout_seconds, proxy))
    if not chain:
        # 空链=每条检索都静默返回空表，是可观测性黑洞；这里点名一次（不猜配置值）。
        logger.warning(
            "web search chain is empty: no key provider configured and key-free "
            "tail fallback is disabled (field %s)",
            _KEYFREE_TAIL_CONFIG_FIELD,
        )
    return chain


def _build_chained_provider(
    timeout_seconds: float,
    proxy: str,
    config: object | None = None,
) -> ChainedWebSearchProvider:
    """Build the configured API chain: Tavily, You.com, LangSearch, optional TinyFish.

    无 config 上下文（如 MCP web_search 工具直调 search_async）时装配免 key
    的 DuckDuckGo → Bing 兜底链，而不是空 provider 链（空链会让每次检索
    都返回空结果）；key 类提供器在 build_api_search_provider 里按缺失 key
    自然跳过。

    config 那条链默认**只有** key 类提供器（逐字节现状）。仅当开关
    `keyfree_fallback_enabled(config)` 为真时，才在链**尾**追加免 key 兜底
    （DDG → Bing，包一层 `GuardedKeyFreeWebSearchProvider`）：key 家仍是主力，
    兜底只在前序全灭（缺 key / 配额耗尽 / 网络故障 / 返回空）时才被走到。
    """
    if config is None:
        return ChainedWebSearchProvider(
            [
                DuckDuckGoWebSearchProvider(timeout_seconds=timeout_seconds, proxy=proxy),
                BingWebSearchProvider(timeout_seconds=timeout_seconds, proxy=proxy),
            ],
            timeout_seconds=timeout_seconds,
            proxy=proxy,
        )
    providers, fetcher = build_api_search_provider(
        config,
        timeout_seconds=timeout_seconds,
        proxy=proxy,
    )
    return ChainedWebSearchProvider(
        _compose_chain_providers(list(providers), config, timeout_seconds, proxy),
        timeout_seconds=timeout_seconds,
        proxy=proxy,
        page_fetcher=fetcher,
        latest_time_range=resolve_latest_time_range(config),
    )


def build_web_search_provider(config: object | None = None) -> WebSearchProvider:
    """Build the configured API provider chain; disabled or unconfigured means no search."""
    enabled = bool(getattr(config, "bot_web_search_enabled", False)) if config else False
    if not enabled or config is None:
        return NullWebSearchProvider()
    timeout = float(getattr(config, "bot_web_search_timeout_seconds", 6.0) or 6.0)
    proxy = str(getattr(config, "bot_download_proxy", "") or "").strip()
    return _build_chained_provider(timeout, proxy, config)


async def search_async(
    query: str,
    *,
    max_results: int = 3,
    timeout_seconds: float = 3.0,
    proxy: str = "",
) -> list[WebSearchHit]:
    """异步联网搜索：DDG 优先、Bing 兜底；失败/超时静默返回空列表。"""
    provider = _build_chained_provider(timeout_seconds, proxy)
    client: httpx.AsyncClient | None = None
    try:
        client = _build_async_client(proxy, timeout_seconds)
        async with client:
            return await provider.search_async(
                query, max_results=max_results, client=client
                )
    except Exception:  # noqa: BLE001 - 搜索失败静默返回空结果。
        return []
    finally:
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001, S110 - 连接关闭失败忽略。
                pass


_DDG_REDIRECT_HOSTS = frozenset({"duckduckgo.com", "www.duckduckgo.com"})


def _resolve_ddg_redirect(url: str) -> str:
    """解出 DDG 命中链接重定向壳里的真实地址。

    实测 html 版结果页的 result__a href 形如
    ``//duckduckgo.com/l/?uddg=<URL编码的真实链接>``（含相对 ``/l/?uddg=``），
    旧实现直接当目标 URL 用，导致域名判定与白名单过滤全部落空。
    非 DDG 壳的链接原样返回。
    """
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if "uddg=" not in (parts.query or ""):
        return url
    if parts.netloc and (parts.netloc or "").lower() not in _DDG_REDIRECT_HOSTS:
        return url
    targets = urllib.parse.parse_qs(parts.query).get("uddg")
    return targets[0] if targets and targets[0] else url


def _extract_ddg_hits(html_text: str, *, max_results: int = 3) -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    blocks = re.split(r'class="result"|class="result ', html_text)[1:]
    for block in blocks:
        title_match = re.search(
            r'class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL
        )
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', block, re.DOTALL
        )
        # 真实 DDG 命中链接是 //duckduckgo.com/l/?uddg=… 重定向壳（协议相对），
        # 旧正则要求 https?:// 开头导致永远匹配不到——放宽到 uddg/绝对 URL 两形。
        link_match = re.search(r'href="([^"]*(?:uddg=[^"]+|https?://[^"]+))"', block)
        if not title_match or not link_match:
            continue
        title = _clean_text(_HTML_TAG_RE.sub("", title_match.group(1)))
        snippet = (
            _clean_text(_HTML_TAG_RE.sub("", snippet_match.group(1)))
            if snippet_match
            else ""
        )
        url = _resolve_ddg_redirect(link_match.group(1))
        domain = urllib.parse.urlsplit(url).netloc
        hits.append(
            WebSearchHit(title=title, snippet=snippet, url=url, source_domain=domain)
        )
        if len(hits) >= max_results:
            break
    return hits


def _extract_bing_hits(html_text: str, *, max_results: int = 3) -> list[WebSearchHit]:
    hits: list[WebSearchHit] = []
    blocks = re.split(r'<li class="b_algo"', html_text)[1:]
    for block in blocks:
        title_match = re.search(r"<h2[^>]*><a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.DOTALL)
        if not title_match:
            continue
        url = title_match.group(1)
        title = _clean_text(_HTML_TAG_RE.sub("", title_match.group(2)))
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
        snippet = (
            _clean_text(_HTML_TAG_RE.sub("", snippet_match.group(1)))
            if snippet_match
            else ""
        )
        domain = urllib.parse.urlsplit(url).netloc
        hits.append(
            WebSearchHit(title=title, snippet=snippet, url=url, source_domain=domain)
        )
        if len(hits) >= max_results:
            break
    return hits
