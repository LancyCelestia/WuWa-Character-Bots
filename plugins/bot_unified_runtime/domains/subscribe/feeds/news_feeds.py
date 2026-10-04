"""今日快报数据源：只准**正规新闻机构**的 RSS（用户 2026-10-02 裁定，见名册）。

**源侧硬边界**（席 F2，2026-10-02；执法＝``tests/test_news_source_whitelist.py``）：
今日快报只准「新华社/人民日报/BBC/CNN/联合早报这一类」有采编与更正机制的新闻
机构，**不许用自媒体/论坛/聚合转载形态**。这条是产品边界而不是运维偏好 ⇒ 刻意
**不落配置键、不留开关**（能关掉的门等于没有门）：放开只能改本文件的
``NEWS_SOURCES`` 名册，且必须同批改对外宣称面（帮助册/卡面），否则宣称门红。

名册＝源的唯一真身：``_FEEDS``（抓取用）由名册里「准入 ∧ 有端点 ∧ 可达性档位
可接」的行**派生**，不另立第二份清单。可达性逐源登记在每行的 ``reachability``
与 ``probe``（实测日期＋出处）上——**未实测的候选一律不接线、不宣称**。

历史实测探针（本波**未**复跑外网，逐源复核清单见工单）：

- 2026-09-11 本机直连（旧 docstring）：IT之家 ``www.ithome.com/rss/``、少数派
  ``sspai.com/feed``、V2EX ``v2ex.com/index.xml``（Atom 1.0）、华尔街见闻
  ``dedicated.wallstreetcn.com/rss.xml``、BBC 中文
  ``feeds.bbci.co.uk/zhongwen/simp/rss.xml``（该源实际返回繁体条目）；
- 2026-09-30 席 S05（``patches/S05-NEWS-WIKI-STEAMDB.md`` §2）：新华社/人民日报
  RSS **内容冻结**（2022-12-14 / 2025-06-05）、CNN **结构性无 RSS**（502/SSL 失败）、
  联合早报 ``/rss`` 返 HTML SPA、BBC 中文直连超时且产线首连 15.5s > 6.0s 预算、
  中新社 ``chinanews.com.cn/rss/*.xml`` 当日新鲜；
- 2026-09-11 剔除：36kr ``/feed``、Solidot ``index?rss``、机器之心 ``/rss`` 实测
  返回 HTML 页面（feed 已下线），收录只会制造常态解析失败的静默噪音。

设计（与 market_data / meme_search 同一套底线）：

- 单源失败（超时/HTML 响应/XML 损坏/超限长）静默跳过，绝不上抛；
- 并发抓取类目内全部源（线程池，整类目共享 timeout_seconds 预算，
  最坏耗时 ≈ 单源超时而不是源数 × 超时）；
- 成功结果进进程内 TTL 缓存（按类目分桶，默认 10 分钟，≤64 条），
  失败不缓存，下一次调用立即重试；
- 解析同时支持 RSS 2.0 与 Atom（ElementTree ``{*}`` 通配命名空间），
  标题剥 HTML 标签 + 反转义实体 + 压空白（华尔街见闻 CDATA 标题
  实测带首尾空格）。
"""

from __future__ import annotations

import email.utils
import html as _html
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

# 审查 Q-01：user_copy 为零依赖纯常量池，sources 跨层引用不构成装配环。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.shared_pool import get_shared_pool
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    http_get_text,
)

# 响应体上限：单源 RSS 实测最大约 260KB（华尔街见闻），1MB 已是数倍冗余，
# 只为防异常超大响应撑爆内存。
_MAX_FEED_BYTES = 1024 * 1024
# 进程内缓存上限：先清过期，再按最旧丢弃（长驻进程防无界增长）。
_CACHE_MAX_ENTRIES = 64
_CACHE_TTL_DEFAULT_SECONDS = 600.0
# mix 类目每源最多取若干条（跨类目多样性优先于单源深度）。
_MIX_PER_FEED_CAP = 4
# mix 合并后的总量上限（缓存桶存合并结果，供不同 max_items 切片）。
_MIX_MERGE_CAP = 32


@dataclass(frozen=True)
class NewsItem:
    """单条新闻标题快照。"""

    title: str
    url: str
    source: str
    published_at: datetime | None = None
    category: str = "tech"
    summary: str = ""  # F9：RSS 描述首句（禁标题党——标题后给真实内容行）


# F9 营销/广告条目过滤（用户实弹点名「求职」「推广」）：标题或摘要命中即弃。
_AD_TITLE_RE = re.compile(
    r"(求职|招聘|急聘|推广|赞助|广告|优惠|折扣|优惠券|薅羊毛|拼团|抽奖|送码|"
    r"众测|内测招募|招商|加盟|带货|限时购|秒杀|白嫖|福利社|好物)",
    re.IGNORECASE,
)


# ==================== 源白名单名册（用户裁定唯一落点）====================
# 档位判定的唯一真身在 ``domains/core/search/source_authority.py``（回答「哪个域名
# 更该先看」）。本名册回答**另一件事**：「哪个主体准进今日快报」——两把尺不同维，
# 但对账是机械的（门②）：名册每枚主域名要么在 source_authority 达到
# ``TIER_MAJOR_MEDIA`` 及以上，要么在本行写死 ``note`` 例外理由；判为
# ``TIER_AGGREGATOR``（自媒体/聚合转载档）者**无条件拒**，永远进不来。
NEWS_TIER_SOURCE_OF_TRUTH = "domains/core/search/source_authority.py"

# 可达性档位（逐源实测才准接线；``probe`` 字段记「哪天、哪儿测的」）。
REACH_WIRED_LIVE = "wired_live"  # 已实测可达且返回可解析条目
REACH_WIRED_DEGRADED = "wired_degraded"  # 已接线但实测踩超时预算/需代理＝常静默失败
REACH_PENDING_REVERIFY = "pending_reverify"  # 他席实测可达、本波未复核 ⇒ 不接线
REACH_FROZEN_STALE = "frozen_stale"  # 端点通但内容冻结 ⇒ 接进来就是播旧闻
REACH_STRUCTURAL_ABSENT = "structural_absent"  # 结构性无 RSS 通道（诚实说拿不到）
REACH_UNVERIFIED = "unverified"  # 从未实测 ⇒ 既不接线也不宣称
#: 只有这两档准接线（其余档位即便填了端点也不会被抓取列表收录，门③ 执法）。
_WIREABLE_REACH = frozenset({REACH_WIRED_LIVE, REACH_WIRED_DEGRADED})


@dataclass(frozen=True)
class NewsSource:
    """名册一行＝一个采编主体（不是「一个 URL」）。

    ``domains`` 首枚＝主域名（用于对 source_authority 的档位对账），其余是该主体
    自有的补充域名（如 feed 主机名与文章主机名不同域）。展示名取 ``media``
    （登记名）而**不取远端 ``<title>`` 自称**——换皮只改站点自报名就跟着改是泄露面。
    """

    key: str
    media: str
    domains: tuple[str, ...]
    admitted: bool
    endpoint: str = ""
    category: str = ""
    reachability: str = REACH_UNVERIFIED
    probe: str = ""
    note: str = ""


#: 名册（源的唯一真身）。``_FEEDS`` 由本表派生，不手写第二份清单。
NEWS_SOURCES: tuple[NewsSource, ...] = (
    # ---------------- 准入且已接线 ----------------
    NewsSource(
        key="ithome",
        media="IT之家",
        domains=("ithome.com",),
        admitted=True,
        endpoint="https://www.ithome.com/rss/",
        category="tech",
        reachability=REACH_WIRED_LIVE,
        probe="2026-09-11 本机直连实测 200/RSS2.0（旧 docstring；2026-10-02 本席未复跑）",
        note="持牌科技新闻编辑室；source_authority 判 TIER_MAJOR_MEDIA。",
    ),
    NewsSource(
        key="wallstreetcn",
        media="华尔街见闻",
        domains=("wallstreetcn.com",),
        admitted=True,
        endpoint="https://dedicated.wallstreetcn.com/rss.xml",
        category="finance",
        reachability=REACH_WIRED_LIVE,
        probe="2026-09-11 本机直连实测 200/RSS2.0（旧 docstring；2026-10-02 本席未复跑）",
        note=(
            "例外档：source_authority 判 TIER_VERTICAL——那是**排序档**不是**自媒体判定**"
            "（该表 TIER_AGGREGATOR 才是自媒体/聚合档）。华尔街见闻是自有采编的持牌财经"
            "编辑室，本席判为正规源；若按最严口径（只准国家级通讯社与主流大报）则本行"
            "出局、finance 类目见底 ⇒ 待用户复核（工单 §5 裁定项 R-1）。"
        ),
    ),
    NewsSource(
        key="bbc",
        media="BBC中文",
        domains=("bbc.com", "bbc.co.uk", "bbci.co.uk"),
        admitted=True,
        endpoint="https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
        category="world",
        reachability=REACH_WIRED_DEGRADED,
        probe=(
            "2026-09-11 直连 200；2026-09-30 席 S05 复测＝直连超时、产线 301→/zhongwen/trad "
            "首连 15.5s > bot_news_timeout_seconds=6.0 ⇒ world 类目此刻大概率静默为空"
        ),
        note=(
            "主域名取文章域 bbc.com（TIER_MAJOR_MEDIA）；feed 主机 feeds.bbci.co.uk 落 "
            "bbci.co.uk，**该域未登记进 source_authority**（工单 §5 请求项 C-1）。"
            "该 feed 实测返回繁体条目，对外类目仍标「国际」。"
        ),
    ),
    # ---------------- 准入但未接线（可达性不达标或未复核）----------------
    NewsSource(
        key="chinanews",
        media="中国新闻网",
        domains=("chinanews.com.cn", "chinanews.com"),
        admitted=True,
        endpoint="https://www.chinanews.com.cn/rss/world.xml",
        category="",
        reachability=REACH_PENDING_REVERIFY,
        probe="2026-09-30 席 S05 实测 200/0.1s（直连与产线均通），条目日期＝当日（唯一实测新鲜的国内权威源）",
        note=(
            "中国新闻社（国家级通讯社）＝TIER_MAJOR_MEDIA。待主会话复跑探针后把 "
            "reachability 改成 wired_live 并补 category 才真接线。rss/{china,world,"
            "importnews}.xml 三支的**类目归属本席未逐支实测**，不许替它拍（工单 §6 待验 V-2）。"
        ),
    ),
    NewsSource(
        key="xinhuanet",
        media="新华社",
        domains=("xinhuanet.com", "news.cn"),
        admitted=True,
        endpoint="https://www.xinhuanet.com/politics/news_politics.xml",
        category="",
        reachability=REACH_FROZEN_STALE,
        probe="2026-09-30 席 S05 实测 200/text/xml 但条目冻在 2022-12-14，且无 <pubDate>（时间戳是元素外裸文本）",
        note="TIER_FIRST_PARTY。接进来＝把四年前的旧闻当「今日快报」播 ⇒ 必须先有新鲜度门（阈值待用户拍，S05 §9.3）。",
    ),
    NewsSource(
        key="people",
        media="人民日报",
        domains=("people.com.cn", "peopleapp.com"),
        admitted=True,
        endpoint="http://www.people.com.cn/rss/politics.xml",
        category="",
        reachability=REACH_FROZEN_STALE,
        probe="2026-09-30 席 S05 实测 200/text/xml 但条目 pubDate 全为 2025-06-05",
        note="TIER_FIRST_PARTY。同新华社：新鲜度门前不接线。端点是明文 http，接线同批要评估升级 https（工单 §6 待验 V-3）。",
    ),
    NewsSource(
        key="cnn",
        media="CNN",
        domains=("cnn.com",),
        admitted=True,
        reachability=REACH_STRUCTURAL_ABSENT,
        probe="2026-09-30 席 S05 实测：rss.cnn.com 经代理 502、直连 SSL 失败；cnn.com/services/rss/ 无通道",
        note="用户点名源之一，但**结构性无 RSS** ⇒ 诚实说拿不到（第四部分「非上市/无源」同一口径），不许用估算或转载冒充。",
    ),
    NewsSource(
        key="zaobao",
        media="联合早报",
        domains=("zaobao.com", "wanbao.com"),
        admitted=True,
        reachability=REACH_STRUCTURAL_ABSENT,
        probe="2026-09-30 席 S05 实测：/rss 返回 text/html SPA 壳（无日期串），产线 SSL UNEXPECTED_EOF",
        note="用户点名源之一。要接只能自建 HTML→清单解析器（成本高、且先解决 SSL 截断）⇒ 列入候选不排期。",
    ),
    NewsSource(
        key="cctv",
        media="央视新闻",
        domains=("cctv.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_FIRST_PARTY。RSS 端点从未实测 ⇒ 不接线、不宣称。",
    ),
    NewsSource(
        key="thepaper",
        media="澎湃新闻",
        domains=("thepaper.cn",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_MAJOR_MEDIA。端点未实测。",
    ),
    NewsSource(
        key="caixin",
        media="财新",
        domains=("caixin.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_MAJOR_MEDIA。端点未实测（且有付费墙口径待裁）。",
    ),
    NewsSource(
        key="reuters",
        media="路透社",
        domains=("reuters.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_FIRST_PARTY（国际通讯社）。端点未实测。",
    ),
    NewsSource(
        key="apnews",
        media="美联社",
        domains=("apnews.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_FIRST_PARTY（国际通讯社）。端点未实测。",
    ),
    NewsSource(
        key="afp",
        media="法新社",
        domains=("afp.com",),
        admitted=True,
        reachability=REACH_UNVERIFIED,
        note="TIER_FIRST_PARTY（国际通讯社）。端点未实测。",
    ),
    # ---------------- 除名（2026-10-02 用户裁定：自媒体/论坛形态不准进快报）----------------
    NewsSource(
        key="v2ex",
        media="V2EX",
        domains=("v2ex.com",),
        admitted=False,
        note="论坛（用户发帖，无采编与更正机制）。2026-09-12 席 N4 接入、2026-10-02 席 F2 按用户裁定除名。",
    ),
    NewsSource(
        key="sspai",
        media="少数派",
        domains=("sspai.com",),
        admitted=False,
        note="社区投稿平台（内容主要由注册用户投）。同日同因除名；帮助册仍写着它＝宣称面违规，见门⑤ 棘轮。",
    ),
)

#: 名册外的硬禁域名（**零容忍**，不给棘轮通道）：UGC 平台形态 +
#: source_authority 的 TIER_AGGREGATOR（自媒体/聚合转载档）。
#: 判据：这三处任一命中即拒——① 不得作为名册行的 ``admitted=True`` 主域名；
#: ② 不得出现在抓取列表里；③ 条目 URL 指向这些域一律丢（运行期出站门）。
BANNED_NEWS_HOSTS: dict[str, str] = {
    "v2ex.com": "论坛 UGC（2026-10-02 除名）",
    "sspai.com": "社区投稿平台（2026-10-02 除名）",
    "zhihu.com": "问答社区 UGC",
    "weibo.com": "微博 UGC",
    "weixin.qq.com": "公众号＝自媒体主阵地",
    "douyin.com": "短视频 UGC",
    "xiaohongshu.com": "社区笔记 UGC",
    "bilibili.com": "UP 主投稿平台",
    "kurobbs.com": "游戏社区 UGC",
    "oschina.net": "开源社区投稿",
    # 与 source_authority._AGGREGATOR 同族（门④ 锁两侧不漂移）。
    "baijiahao.baidu.com": "百家号＝自媒体",
    "mbd.baidu.com": "手机百度信息流聚合",
    "360kuai.com": "快资讯聚合",
    "ixigua.com": "西瓜视频聚合",
    "toutiao.com": "今日头条聚合",
    "sohu.com": "搜狐号自媒体",
}

# ==================== 名册读口与准入判定 ====================


def _host_matches(domain: str, registered: str) -> bool:
    """整段相等或末段后缀命中（与 source_authority._matches 同语义，锁见门⑦）。

    刻意**不**复用那枚私名：跨包抓私函数＝把别席的改名权接到本件上。等价性由测试
    现算比对（含抢注探针 ``fake-ithome.com``／``evilpeople.com.cn`` 必须不命中），
    漂移当场红，所以这不是「第二把尺」而是「同一把尺的两次证明」。
    """
    return domain == registered or domain.endswith("." + registered)


def _news_domain(value: str) -> str:
    """URL/裸域名 → 可比较的裸域名（复用 source_authority 的归一，禁第二把尺）。"""
    from plugins.bot_unified_runtime.domains.core.search.source_authority import (
        normalize_domain,
    )

    return normalize_domain(value)


def news_source_for(url: str) -> NewsSource | None:
    """URL 归属到名册的哪个采编主体；不在名册（含被禁域）一律 ``None``。"""
    domain = _news_domain(url)
    if not domain:
        return None
    for source in NEWS_SOURCES:
        if any(_host_matches(domain, registered) for registered in source.domains):
            return source
    return None


def is_banned_news_url(url: str) -> bool:
    """该 URL 是否落在硬禁域名表上（UGC/自媒体聚合形态）。"""
    domain = _news_domain(url)
    return bool(domain) and any(_host_matches(domain, host) for host in BANNED_NEWS_HOSTS)


def is_admissible_news_url(url: str) -> bool:
    """准不准进快报：硬禁域一律拒；其余要求「名册内 ∧ admitted」。

    未登记域名同样判 False——快报是**点名要正规源**的场景，与检索侧「未登记不丢弃」
    的取向刻意相反（那侧怕误伤，这侧怕越界；差异理由写在这里，别顺手放宽）。
    """
    if is_banned_news_url(url):
        return False
    source = news_source_for(url)
    return bool(source and source.admitted)


def _wired_sources() -> tuple[NewsSource, ...]:
    """名册 → 真被抓取的行：准入 ∧ 有端点 ∧ 有类目 ∧ 可达性档位可接。

    可达性档位是硬门：``pending_reverify``/``frozen_stale``/``structural_absent``/
    ``unverified`` 即便填了端点也不会被收录（门③ 执法「未实测不得接线」）。
    """
    return tuple(
        source
        for source in NEWS_SOURCES
        if source.admitted
        and source.endpoint
        and source.category
        and source.reachability in _WIREABLE_REACH
    )


# (url, 展示名, 类目)；类目取值见 CATEGORY_LABELS。**由名册派生，勿在此手写行**。
_FEEDS: tuple[tuple[str, str, str], ...] = tuple(
    (source.endpoint, source.media, source.category) for source in _wired_sources()
)


def wired_media_names() -> frozenset[str]:
    """实装（真会抓）的源登记名——对外宣称的唯一合法集合。"""
    return frozenset(source.media for source in _wired_sources())


def admitted_unwired_media_names() -> frozenset[str]:
    """名册内准入但**没接线**的媒体名：这些名字出现在任何对外宣称面即红。"""
    return frozenset(
        source.media
        for source in NEWS_SOURCES
        if source.admitted and source not in _wired_sources()
    )

# 类目 → 中文标签（对外展示与缓存分桶共用这一组键）。
CATEGORY_LABELS: dict[str, str] = {
    "tech": "科技",
    "finance": "财经",
    "world": "国际",
    "mix": "综合",
}

# 审查 Q-01：数据源失败文案统一入 user_copy 池（守岸人语气轮换），不再硬编码。
def _empty_degraded_text() -> str:
    return random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(reason="快报暂时拉不到")

# 进程内缓存：按类目分桶，缓存最后一次成功抓取（monotonic 时间戳, 快照）。
_CACHE: dict[str, tuple[float, tuple[NewsItem, ...]]] = {}


def reset_news_cache() -> None:
    """清空进程内快报缓存（测试与运维手动刷新用）。"""
    _CACHE.clear()


def _fetch_feed_text(url: str, timeout_seconds: float) -> str:
    """单点网络出口：测试 monkeypatch 本函数即可拦截全部外呼。"""
    _, text = http_get_text(
        url,
        timeout=max(1.0, float(timeout_seconds)),
        max_bytes=_MAX_FEED_BYTES,
    )
    return text


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_title(raw: str) -> str:
    """标题清洗：剥 HTML 标签、反转义实体、压空白（CDATA 常带首尾空格）。"""
    text = _HTML_TAG_RE.sub(" ", raw or "")
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_datetime(raw: str) -> datetime | None:
    """RSS pubDate（RFC 822）与 Atom updated/published（ISO 8601）都能解。"""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _entry_link(node: ET.Element) -> str:
    """条目链接：Atom 取 href 属性（优先 rel=alternate），RSS 取文本。"""
    first = ""
    for link_el in node.findall("{*}link"):
        href = (link_el.get("href") or link_el.text or "").strip()
        if not href:
            continue
        if not first:
            first = href
        if (link_el.get("rel") or "alternate").strip() == "alternate":
            return href
    return first


def _entry_date(node: ET.Element) -> str:
    """条目时间：RSS pubDate / Atom published|updated / RSS1 dc:date。"""
    for tag in ("pubDate", "published", "updated", "date"):
        raw = node.findtext("{*}" + tag)
        if raw and raw.strip():
            return raw
    return ""


def _entry_summary(node: ET.Element, *, max_chars: int = 80) -> str:
    """条目摘要：RSS description / Atom summary|content 的首段纯文本。

    F9 禁标题党：标题之下必须给真实内容行。剥 HTML 标签/实体，截 80 字。
    """
    for tag in ("description", "summary", "content"):
        raw = node.findtext("{*}" + tag)
        if not raw or not raw.strip():
            continue
        text = _HTML_TAG_RE.sub(" ", raw)
        text = _html.unescape(text)
        text = _WS_RE.sub(" ", text).strip()
        # 常见 boilerplate 前缀（全图：(图)/图片来自网络 等）跳过
        if len(text) < 8:
            continue
        return text[:max_chars].rstrip() + ("…" if len(text) > max_chars else "")
    return ""


def parse_feed(text: str, *, source: str, category: str) -> list[NewsItem]:
    """解析单源 XML（RSS 2.0 / Atom / RDF 均可）；坏 XML 返回 []。

    缺标题的条目跳过，缺链接/时间的条目保留（字段尽力而为）。
    F9：营销/广告条目（求职/推广/优惠 等）直接过滤；摘要入 NewsItem。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    # {*}` 通配命名空间：RSS2 的 item 在 channel 下、RDF 的 item 在根下、
    # Atom 是 entry，全部用后代轴一网打尽。
    nodes = root.findall(".//{*}item") or root.findall(".//{*}entry")
    items: list[NewsItem] = []
    for node in nodes:
        title = _clean_title(node.findtext("{*}title") or "")
        if not title:
            continue
        summary = _entry_summary(node)
        if _AD_TITLE_RE.search(title) or _AD_TITLE_RE.search(summary):
            continue
        items.append(
            NewsItem(
                title=title,
                url=_entry_link(node),
                source=source,
                published_at=_parse_datetime(_entry_date(node)),
                category=category,
                summary=summary,
            )
        )
    return items


def _feeds_for(category: str) -> list[tuple[str, str, str]]:
    """类目 → 源列表；mix 或未知类目回退全部源。

    再过一道**名册准入门**（纵深防御）：``_FEEDS`` 本已由名册派生，但它是私名且
    可被 monkeypatch/后续改动，所以运行时不信任它的形状——名册外端点在这里就掉，
    不进线程池、不发外呼。
    """
    rows = (
        [feed for feed in _FEEDS if feed[2] == category]
        if category in ("tech", "finance", "world")
        else list(_FEEDS)
    )
    return [feed for feed in rows if is_admissible_news_url(feed[0])]


def _fetch_single_feed(
    url: str,
    source: str,
    category: str,
    per_feed_cap: int,
    timeout_seconds: float,
) -> list[NewsItem]:
    """抓取并解析单源；任何失败静默返回 []，不给整体拖后腿。

    名册对 ≠ 条目对：RSS 里的转载链可以指向别处，所以解析后、进合并/缓存之前
    再对每条 ``item.url`` 过一次准入门（席 F2 运行期出站门）。**无 URL 的条目保留**
    ——它的来源已是名册登记名，没有可判定的域名，宁缺不假。
    """
    try:
        text = _fetch_feed_text(url, timeout_seconds)
    except Exception:  # noqa: BLE001 - 单源失败静默跳过，快报绝不抛异常。
        return []
    items = parse_feed(text, source=source, category=category)
    admitted = [item for item in items if not item.url or is_admissible_news_url(item.url)]
    return admitted[:per_feed_cap]


def _merge_dedup(lists: list[list[NewsItem]], *, interleave: bool, cap: int) -> list[NewsItem]:
    """合并 + 按 URL 去重；mix 用轮转合并保证类目多样性，其余保源序。"""
    merged: list[NewsItem] = []
    seen_urls: set[str] = set()
    if interleave:
        pools = [list(feed_items) for feed_items in lists]
        while len(merged) < cap and any(pools):
            for pool in pools:
                if len(merged) >= cap:
                    break
                if not pool:
                    continue
                item = pool.pop(0)
                if item.url and item.url in seen_urls:
                    continue
                if item.url:
                    seen_urls.add(item.url)
                merged.append(item)
        return merged
    for feed_items in lists:
        for item in feed_items:
            if item.url and item.url in seen_urls:
                continue
            if item.url:
                seen_urls.add(item.url)
            merged.append(item)
            if len(merged) >= cap:
                return merged
    return merged


def _evict_cache(ttl_seconds: float) -> None:
    """缓存上限治理：先清过期，再按最旧丢弃（≤64 条）。"""
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    now = time.monotonic()
    expired = [
        key
        for key, (cached_at, _snapshot) in _CACHE.items()
        if now - cached_at > ttl_seconds
    ]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def fetch_headlines(
    category: str = "mix",
    *,
    timeout_seconds: float = 6.0,
    cache_seconds: float = _CACHE_TTL_DEFAULT_SECONDS,
    max_items: int = 8,
) -> list[NewsItem]:
    """按类目抓取今日头条列表；全部源失败返回 []，绝不抛异常。

    - 类目：tech / finance / world / mix（mix 跨类目轮转各取若干，未知
      类目按 mix 处理）；
    - timeout_seconds 是整类目的并发总预算（每源各自享受该超时，线程池
      并发，最坏耗时 ≈ 单源超时）；
    - 成功结果按类目进进程内 TTL 缓存（默认 600s），命中直接切片返回；
      失败不缓存，下一次调用立即重试。
    """
    key = category if category in CATEGORY_LABELS else "mix"
    ttl = max(0.0, float(cache_seconds))
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] <= ttl:
        return list(cached[1])[: max(1, int(max_items))]

    feeds = _feeds_for(key)
    if not feeds:
        return []
    per_feed_cap = _MIX_PER_FEED_CAP if key == "mix" else 20
    timeout = max(1.0, float(timeout_seconds))
    # P2 减量波：逐次新建池 → 共享有界池（原上限 min(len(feeds),8) ≤ 8，
    # 独跑时并发度不变）。逐个 future.result() 阻塞收齐＝「返回前所有
    # futures 已完成」，与旧 with 退出 join 语义一致。
    pool = get_shared_pool()
    futures = [
        pool.submit(_fetch_single_feed, url, source, feed_category, per_feed_cap, timeout)
        for url, source, feed_category in feeds
    ]
    per_feed_lists: list[list[NewsItem]] = []
    for future in futures:
        try:
            per_feed_lists.append(future.result())
        except Exception:  # noqa: BLE001 - 单源线程异常同样静默跳过。
            per_feed_lists.append([])

    merged = _merge_dedup(per_feed_lists, interleave=key == "mix", cap=_MIX_MERGE_CAP)
    if merged:
        _CACHE[key] = (now, tuple(merged))
        _evict_cache(ttl)
    return merged[: max(1, int(max_items))]


def format_news_brief(items: Sequence[NewsItem], category_label: str) -> str:
    """渲染纯文本快报：首行日期+类目，正文 ``1. 标题（来源）``＋摘要行。

    F9：有摘要的条目标题下缩进给真实内容行（禁标题党——用户要求把真实
    内容写在里面）；无摘要的只上标题。
    """
    if not items:
        return _empty_degraded_text()
    # 本地时区日期（astimezone 使 aware，规避 DTZ005）。
    date_text = datetime.now().astimezone().strftime("%Y-%m-%d")
    lines = [f"今日快报 · {date_text} · {category_label}"]
    for index, item in enumerate(items, 1):
        source_text = f"（{item.source}）" if item.source else ""
        lines.append(f"{index}. {item.title}{source_text}")
        if item.summary:
            lines.append(f"    {item.summary}")
    return "\n".join(lines)
