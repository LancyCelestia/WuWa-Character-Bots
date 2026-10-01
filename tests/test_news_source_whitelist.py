"""今日快报「源白名单门」＋逐源可达性判定＋宣称⊆实装（席 F2，2026-10-02，全离线）。

用户裁定（本席需求书）
--------------------
新闻**只准正规源**（新华社/人民日报/BBC/CNN/联合早报这一类有采编与更正机制的新闻
机构），**不许用自媒体**。⇒ 名册外域名进今日快报＝红，而且是**机械判据**不是散文
约定；对外宣称的源 ⊆ 实装可达的源，**不许宣称没接的源**。

七把尺（每把都配注毒腿＋反向不误伤腿；起点值＝本轮值即判未做）
--------------------------------------------------------------
① 名册白名单门：`_FEEDS` 每行必须落在 `NEWS_SOURCES` 的准入行上，展示名必须等于
   登记名（远端 `<title>` 自称不采信）。
② 档位对账门：判为 `TIER_AGGREGATOR`（自媒体/聚合转载档）的准入行**无条件拒**，
   没有例外通道；**已接线**的行主域名要么在 `source_authority` 里 ≥
   `TIER_MAJOR_MEDIA`，要么恰为 `TIER_VERTICAL` 且行内写死 `note` 例外理由。用户
   点名但未登记的 CNN/联合早报只作政策登记（不发外呼），不许借名册转正自媒体档。
③ 可达性门：只有 `wired_live`/`wired_degraded` 两档准接线；每行必须带实测指针
   `probe`（哪天、哪儿测的）。`unverified`/`frozen_stale`/`structural_absent`/
   `pending_reverify` 即便填了端点也不许被抓取列表收录——**未实测不得接线**。
④ 禁册漂移门：`BANNED_NEWS_HOSTS` 与 `source_authority._AGGREGATOR` 同族那段两侧
   不许漂（一侧删一侧留＝自媒体从后门回来）。
⑤ 存量棘轮门：名册外域名在 `_FEEDS` 的现算违规集合**必须等于手写基线**（本席按
   用户裁定把 V2EX/少数派真除名 ⇒ 基线为空集＝零容忍）。基线为空不等于门空转：
   注毒腿 ⑤b 现算塞一行毒，尺必须咬。
⑥ 宣称⊆实装门（**存量棘轮**）：对外宣称面（`echo._HELP_ENTRIES` 的 快报 topic 与
   `bridge._CARD_TEXT` 的 news 键）里出现的**名册媒体名**必须已被实装接线；
   存量违规走基线（`echo.py` 本席禁写），新增即红。
⑦ 域名匹配等价门：本件私有的 `_host_matches` 与 `source_authority._matches` 逐样本
   等值（含抢注探针 `fake-ithome.com`／`evilpeople.com.cn`）——保证「不抄私名」
   不等于「养第二把尺」。

台账 #12 语义不许改坏：营销条目过滤＋摘要行（⑧⑨ 两腿锁着），单源失败静默跳过、
全部失败给降级文案（⑩ 锁着）。

复跑
----
.. code-block:: bash

    cd ChatBot/ChatBot && mkdir -p "$TEMP/qoder-F2/bt" && \\
    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      -p no:cacheprovider --basetemp="$TEMP/qoder-F2/bt" -q \\
      tests/test_news_source_whitelist.py tests/test_news.py tests/test_sdd7_n4.py

零外呼：网络出口只有 `news_feeds._fetch_feed_text`，本件全部 monkeypatch 它。
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins.bot_unified_runtime.domains.core.search import source_authority as sa
from plugins.bot_unified_runtime.domains.subscribe.feeds import news_feeds as nf
from plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds import (
    _WIREABLE_REACH,
    BANNED_NEWS_HOSTS,
    NEWS_SOURCES,
    NewsSource,
    _host_matches,
)

# ---------------------------------------------------------------------------
# 基线账（手写整数字面量禁则不适用；这里是**集合**：逐枚相等，只降不升）
# ---------------------------------------------------------------------------

#: ⑤ 名册外域名存量违规基线。本席 2026-10-02 按用户裁定把两枚自媒体/论坛形态源
#: （V2EX 论坛、少数派社区投稿平台）真从名册除名 ⇒ 现算违规集合此刻**为空**。
#: 留空集不是空转：门本身是「现算 == 基线」的相等判据，注毒腿 ⑤b 塞一行毒现算即非空。
LEGACY_NON_WHITELISTED_FEED_BASELINE: frozenset[str] = frozenset()

#: ⑥ 宣称面「宣称了没接的源」存量违规基线：`(宣称面标识, 媒体名)` 逐枚登记。
#: `echo.py` 与生成物 `docs/command-catalog.md` 属主会话/别席独占面（SEAT-RULES §禁写
#: 清单），本席只登记不代改 ⇒ 存量走棘轮，新增即红。修法见
#: `patches/F2-NEWS-WHITELIST-20261002.md` §5 请求项 C-1（同批：改 echo.py 文案 →
#: `python scripts/command_catalog.py --write` 再生成）。
CLAIM_OVERSTATEMENT_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {("echo.py:快报", "少数派")}
)

#: ⑥ 的宣称面清单＝**会话里真看得见的东西**（帮助册真身＋卡面文案）。生成物
#: `docs/command-catalog.md`/`docs/route-matrix.md` 由 `echo.py` 投影而来，不重复计入
#: （两份都算会让门变成"同一句话红两次"，反而看不出漂在哪）。历史波次账
#: （`docs/HANDBOOK.md`、`docs/design/v21r2-*`、`docs/acceptance-manual.md`）是过程档
#: 不是对外宣称面，逐行同步清单另列在工单 §5。
_ROSTER_MEDIA_NAMES: frozenset[str] = frozenset(source.media for source in NEWS_SOURCES)


# ---------------------------------------------------------------------------
# 现算尺（判据唯一真身；注毒腿把「被检对象」换成合成输入复跑同一把尺）
# ---------------------------------------------------------------------------


def _whitelist_violations(
    feeds: Iterable[tuple[str, str, str]], sources: Iterable[NewsSource]
) -> list[str]:
    """①＋⑤：`_FEEDS` 行必须命中准入名册行；展示名必须＝登记名；禁域名零容忍。"""
    by_endpoint = {source.endpoint: source for source in sources if source.endpoint}
    banned = tuple(BANNED_NEWS_HOSTS)
    problems: list[str] = []
    for url, media, category in feeds:
        domain = sa.normalize_domain(url)
        if any(_host_matches(domain, host) for host in banned):
            problems.append(f"禁域名（自媒体/论坛形态）出现在抓取列表：{url}")
            continue
        source = by_endpoint.get(url)
        if source is None or not source.admitted:
            problems.append(f"名册外域名进了今日快报：{url}（{media}）")
            continue
        if source.media != media:
            problems.append(f"展示名与名册登记名不符（防换皮）：{url} 声称「{media}」登记「{source.media}」")
        if category != source.category:
            problems.append(f"类目与名册登记不符：{url} 声称「{category}」登记「{source.category}」")
    return problems


def _tier_violations(sources: Iterable[NewsSource]) -> list[str]:
    """②：档位对账。

    - **已接线**的行（端点＋类目＋可达性档位齐，即名册派生的抓取行）：主域名必须
      ≥ `TIER_MAJOR_MEDIA`，或恰为 `TIER_VERTICAL` 且行内写死 `note` 例外理由——
      这是「正规源」的准入凭据。
    - **所有准入行（含未接线的候选）**：判为 `TIER_AGGREGATOR` 一律拒，没有例外通道。
      CNN/联合早报这类「用户点名但 source_authority 未登记」的源允许留在名册里当
      政策登记（它们不发外呼、不进抓取列表），但自媒体档不许借名册转正。
    """
    problems: list[str] = []
    for source in sources:
        if not source.admitted:
            continue
        tier = sa.authority_tier(source.domains[0])
        if tier == sa.TIER_AGGREGATOR:
            problems.append(f"{source.key}: 主域名 {source.domains[0]} 在 source_authority 判自媒体/聚合档，无条件拒")
            continue
        wired = bool(source.endpoint and source.category and source.reachability in _WIREABLE_REACH)
        if wired and tier > sa.TIER_MAJOR_MEDIA and tier != sa.TIER_VERTICAL:
            problems.append(f"{source.key}: 已接线但主域名 {source.domains[0]} 档位 {tier} 未登记 ⇒ 无准入依据（不许例外）")
        elif wired and tier == sa.TIER_VERTICAL and not source.note.strip():
            problems.append(f"{source.key}: 垂类档（TIER_VERTICAL）接线必须在行内写死 note 例外理由")
    return problems


def _reachability_violations(sources: Iterable[NewsSource], feeds: Iterable[tuple[str, str, str]]) -> list[str]:
    """③：被接线的行必须实测可达＋带证据；未实测/冻结/结构性缺席的行不得被抓取。"""
    wired_endpoints = {url for url, _media, _category in feeds}
    problems: list[str] = []
    for source in sources:
        if not source.admitted:
            continue
        if source.endpoint and source.endpoint in wired_endpoints:
            if source.reachability not in _WIREABLE_REACH:
                problems.append(f"{source.key}: 可达性档位 {source.reachability} 不可接线却进了抓取列表")
            if not source.probe.strip():
                problems.append(f"{source.key}: 已接线却没有任何实测证据指针（probe 空）＝宣称没证据")
            if not source.category:
                problems.append(f"{source.key}: 已接线但 category 空（类目归属未裁）")
        elif source.reachability in _WIREABLE_REACH and source.endpoint and source.category:
            problems.append(f"{source.key}: 实测可达＋端点＋类目齐了却没接线（名册与抓取列表漂移）")
    return problems


def _ban_book_violations(sources: Iterable[NewsSource]) -> list[str]:
    """④＋禁册自洽：准入行的任何域名都不得命中禁册；AGGREGATOR 段两侧不许漂。"""
    problems: list[str] = []
    for source in sources:
        if not source.admitted:
            continue
        for domain in source.domains:
            if any(_host_matches(domain, banned) or _host_matches(banned, domain) for banned in BANNED_NEWS_HOSTS):
                problems.append(f"{source.key}: 域名 {domain} 命中禁册却标 admitted")
    # 与 source_authority 的自媒体档对账：那侧登记的聚合域必须在本侧禁册里。
    aggregator_hosts = {
        domain
        for domain in _authority_aggregator_hosts()
        if not any(_host_matches(domain, banned) for banned in BANNED_NEWS_HOSTS)
    }
    for domain in sorted(aggregator_hosts):
        problems.append(f"source_authority 判 TIER_AGGREGATOR 的 {domain} 未进快报禁册＝自媒体能从后门回来")
    return problems


def _authority_aggregator_hosts() -> frozenset[str]:
    """现算 source_authority 的聚合档域名（不抄字面量，防第二真身）。"""
    from plugins.bot_unified_runtime.domains.core.search import source_authority as mod

    return frozenset(mod._AGGREGATOR)


def _claim_faces() -> dict[str, str]:
    """对外宣称面文本：帮助册真身（快报 topic）＋卡面静态文案（news 键）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _HELP_ENTRIES,
    )
    from plugins.bot_unified_runtime.domains.render.card_render.bridge import _CARD_TEXT

    faces: dict[str, str] = {}
    for entry in _HELP_ENTRIES:
        if entry.get("topic") != "快报":
            continue
        blob = "\n".join(
            [
                str(entry.get("index", "")),
                str(entry.get("title_line", "")),
                "\n".join(str(line) for line in entry.get("lines", ())),
                str(entry.get("detail", "")),
            ]
        )
        faces["echo.py:快报"] = blob
    card_blob = "\n".join(
        f"{key}={value}" for key, value in _CARD_TEXT.items() if "news" in key
    )
    faces["bridge._CARD_TEXT:news"] = card_blob
    assert "echo.py:快报" in faces, "帮助册里没有 快报 topic＝宣称面读空，门会空转"
    return faces


def _claim_overstatements(faces: dict[str, str], wired: frozenset[str]) -> set[tuple[str, str]]:
    """⑥ 现算：宣称面里出现的**名册媒体名**，凡未实装即违规。"""
    violations: set[tuple[str, str]] = set()
    for face_id, text in faces.items():
        for media in _ROSTER_MEDIA_NAMES:
            if media in text and media not in wired:
                violations.add((face_id, media))
    return violations


# ---------------------------------------------------------------------------
# ① ⑤ 名册白名单门（＋注毒、反向不误伤）
# ---------------------------------------------------------------------------


def test_leg1_feed_roster_whitelist_is_clean() -> None:
    assert nf._FEEDS, "抓取列表为空＝名册派生断了"
    assert _whitelist_violations(nf._FEEDS, NEWS_SOURCES) == []


def test_leg1b_poison_non_whitelisted_host_in_feed_list_turns_red() -> None:
    """注毒：塞一行名册外域名（聚合档）＋一行未登记域名 ⇒ 尺必须各咬一次。"""
    poisoned = (*nf._FEEDS, ("https://www.toutiao.com/rss/index.xml", "头条", "tech"))
    problems = _whitelist_violations(poisoned, NEWS_SOURCES)
    assert any("禁域名" in problem for problem in problems), f"聚合档毒行没被咬：{problems}"

    unknown = (*nf._FEEDS, ("https://some-unknown-blog.example.org/feed", "无名博客", "tech"))
    problems = _whitelist_violations(unknown, NEWS_SOURCES)
    assert any("名册外域名进了今日快报" in problem for problem in problems), f"未登记域名没被咬：{problems}"

    renamed = (*nf._FEEDS, ("https://www.ithome.com/rss/", "IT之家换皮号", "tech"))
    problems = _whitelist_violations(renamed, NEWS_SOURCES)
    assert any("展示名与名册登记名不符" in problem for problem in problems), f"换皮展示名没被咬：{problems}"


def test_leg1c_feed_list_is_derived_from_roster_not_hand_written() -> None:
    """`_FEEDS` 必须由名册派生（禁第二份清单）：逐行等值比对。"""
    derived = tuple(
        (source.endpoint, source.media, source.category)
        for source in NEWS_SOURCES
        if source.admitted and source.endpoint and source.category and source.reachability in _WIREABLE_REACH
    )
    assert nf._FEEDS == derived, "抓取列表与名册派生结果不等＝有人手写了第二真身"


def test_leg5_legacy_non_whitelisted_feeds_equal_empty_baseline() -> None:
    """⑤ 存量棘轮：现算违规主机集 == 手写基线（此刻为空集＝零容忍）。"""
    measured = frozenset(
        sa.normalize_domain(url)
        for url, _media, _category in nf._FEEDS
        if _whitelist_violations([(url, _media, _category)], NEWS_SOURCES)
    )
    assert measured == LEGACY_NON_WHITELISTED_FEED_BASELINE, (
        f"名册外域名存量违规现算 {sorted(measured)} ≠ 基线 {sorted(LEGACY_NON_WHITELISTED_FEED_BASELINE)}"
        "（涨了＝新增自媒体；降了＝有人除名没复算改账）"
    )


def test_leg5b_ugc_hosts_removed_by_user_ruling_stay_unreachable() -> None:
    """除名必须是真的：V2EX/少数派既不在抓取列表，也不在准入名册行。"""
    urls = " ".join(url for url, _m, _c in nf._FEEDS)
    assert "v2ex.com" not in urls and "sspai.com" not in urls, "自媒体/论坛源回潮"
    for key in ("v2ex", "sspai"):
        source = next((row for row in NEWS_SOURCES if row.key == key), None)
        assert source is not None, f"名册里查无 {key}＝除名账丢了"
        assert source.admitted is False, f"{key} 被改回准入＝用户裁定被静默推翻"


# ---------------------------------------------------------------------------
# ② 档位对账（source_authority 是唯一档位真身）
# ---------------------------------------------------------------------------


def test_leg2_authority_tier_crosscheck() -> None:
    assert _tier_violations(NEWS_SOURCES) == []


def test_leg2b_poison_aggregator_tier_is_refused_without_exception_channel() -> None:
    """注毒：把聚合档域名写成准入行 ⇒ 无条件拒（note 也救不了）。"""
    poisoned = NewsSource(
        key="poison",
        media="毒源",
        domains=("sohu.com",),
        admitted=True,
        endpoint="https://www.sohu.com/rss/",
        category="tech",
        reachability=nf.REACH_WIRED_LIVE,
        probe="2026-10-02 本席注毒",
        note="带了理由也不准：聚合档没有例外通道",
    )
    assert any("无条件拒" in problem for problem in _tier_violations([poisoned]))
    # 反向不误伤：名册里真准入的正规行不该被这把尺咬。
    assert not any(row.media == "毒源" for row in NEWS_SOURCES)
    assert _tier_violations([row for row in NEWS_SOURCES if row.admitted]) == []


def test_leg2c_vertical_tier_admission_must_carry_written_reason() -> None:
    """注毒：垂类档准入但不写理由 ⇒ 红（拦「顺手放一家不认识的平台进来」）。"""
    naked = NewsSource(
        key="naked",
        media="无名垂类",
        domains=("wallstreetcn.com",),
        admitted=True,
        endpoint="https://dedicated.wallstreetcn.com/rss.xml",
        category="finance",
        reachability=nf.REACH_WIRED_LIVE,
        probe="2026-09-11 实测",
        note="   ",
    )
    assert any("写死 note 例外理由" in problem for problem in _tier_violations([naked]))
    # 档位读数是判据的前提：华尔街见闻确实在 source_authority 是 VERTICAL（不是自媒体档）。
    assert sa.authority_tier("wallstreetcn.com") == sa.TIER_VERTICAL


# ---------------------------------------------------------------------------
# ③ 逐源可达性判定（未实测不得接线）
# ---------------------------------------------------------------------------


def test_leg3_wired_feeds_carry_measured_probe_evidence() -> None:
    assert _reachability_violations(NEWS_SOURCES, nf._FEEDS) == []
    # 每行都必须有日期（「哪天测的」是可达性判定的最低可核形态）。
    for source in NEWS_SOURCES:
        if source.endpoint and source.reachability in _WIREABLE_REACH:
            assert re.search(r"\d{4}-\d{2}-\d{2}", source.probe), f"{source.key} 探针没有日期"


def test_leg3b_unverified_or_frozen_candidates_are_not_wired() -> None:
    """诚实处置：新华社/人民日报（内容冻结）、CNN/联合早报（结构性无 RSS）、中新社（他席实测、本波未复核）
    都在名册里，但都不在抓取列表里。"""
    unwired = nf.admitted_unwired_media_names()
    for media in ("新华社", "人民日报", "CNN", "联合早报", "中国新闻网"):
        assert media in unwired, f"{media} 应从「准入未接线」集合里读得出"
    wired = nf.wired_media_names()
    assert not (wired & unwired), "同一枚源既算接线又算未接线＝名册自相矛盾"
    for key, expected in (
        ("cnn", nf.REACH_STRUCTURAL_ABSENT),
        ("zaobao", nf.REACH_STRUCTURAL_ABSENT),
        ("xinhuanet", nf.REACH_FROZEN_STALE),
        ("people", nf.REACH_FROZEN_STALE),
        ("chinanews", nf.REACH_PENDING_REVERIFY),
    ):
        source = next(row for row in NEWS_SOURCES if row.key == key)
        assert source.reachability == expected, f"{key} 可达性档位被改：{source.reachability}"


def test_leg3c_poison_unmeasured_source_wired_anyway_turns_red() -> None:
    """注毒：未实测（unverified）却填了端点＋类目 ⇒ 现算尺必须报「档位不可接线」。"""
    jump = NewsSource(
        key="jump",
        media="抢跑源",
        domains=("example.org",),
        admitted=True,
        endpoint="https://example.org/rss",
        category="tech",
        reachability=nf.REACH_UNVERIFIED,
        probe="",
        note="没测就接",
    )
    feeds = (*nf._FEEDS, (jump.endpoint, jump.media, jump.category))
    problems = _reachability_violations([jump], feeds)
    assert any("不可接线却进了抓取列表" in problem for problem in problems), problems
    assert any("实测证据指针" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# ④ 禁册与 source_authority 的对账
# ---------------------------------------------------------------------------


def test_leg4_ban_book_is_consistent() -> None:
    assert _ban_book_violations(NEWS_SOURCES) == []
    assert _authority_aggregator_hosts() <= frozenset(BANNED_NEWS_HOSTS), (
        "source_authority 的自媒体/聚合档域名没全部进快报禁册＝那侧加一档这侧不知道"
    )


def test_leg4b_poison_banned_host_back_into_roster_turns_red() -> None:
    """注毒：论坛域（v2ex.com）被写成准入行 ⇒ 禁册自洽尺必须咬。"""
    revived = NewsSource(
        key="v2ex-again",
        media="V2EX论坛",
        domains=("v2ex.com",),
        admitted=True,
        endpoint="https://www.v2ex.com/index.xml",
        category="tech",
        reachability=nf.REACH_WIRED_LIVE,
        probe="2026-09-12 旧实测",
        note="回潮",
    )
    assert any("命中禁册却标 admitted" in problem for problem in _ban_book_violations([revived]))


def test_leg4c_banned_host_can_never_be_admitted_even_without_domain_check() -> None:
    """`is_admissible_news_url` 侧：禁域名一律 False（含子域与大小写/全 URL 形态）。"""
    for url in (
        "https://www.v2ex.com/t/1241462#reply0",
        "HTTPS://SSPAI.COM/post/114384",
        "http://baijiahao.baidu.com/s?id=1",
        "https://m.toutiao.com/feed/x",
        "https://weibo.com/1234/AbCd",
    ):
        assert nf.is_banned_news_url(url) is True, f"禁册漏读：{url}"
        assert nf.is_admissible_news_url(url) is False, f"自媒体从准入判定回来：{url}"


# ---------------------------------------------------------------------------
# ⑥ 宣称 ⊆ 实装（帮助册/卡面不许宣称没接的源）
# ---------------------------------------------------------------------------


def test_leg6_declared_sources_are_subset_of_implemented() -> None:
    violations = _claim_overstatements(_claim_faces(), nf.wired_media_names())
    assert violations == CLAIM_OVERSTATEMENT_BASELINE, (
        f"宣称面违规现算 {sorted(violations)} ≠ 基线 {sorted(CLAIM_OVERSTATEMENT_BASELINE)}"
        "（涨了＝新宣称没接的源；降了＝文案已修但没复算降账）"
    )


def test_leg6b_poison_unwired_media_claimed_turns_red() -> None:
    """注毒：帮助册文案写进「新华社/CNN」而它们没接线 ⇒ 必须红。"""
    faces = {
        "echo.py:快报": "国内可达 RSS 聚合（IT之家/华尔街见闻/BBC中文/新华社/CNN），进程内缓存。",
        "bridge._CARD_TEXT:news": "static_news_71=条目取自新华社与 CNN 的公开订阅源。",
    }
    violations = _claim_overstatements(faces, nf.wired_media_names())
    assert ("echo.py:快报", "新华社") in violations
    assert ("echo.py:快报", "CNN") in violations
    assert ("bridge._CARD_TEXT:news", "新华社") in violations
    # 反向不误伤：只写实装源名的文案不该被咬。
    honest = {"echo.py:快报": "国内可达 RSS 聚合（IT之家/华尔街见闻/BBC中文）。"}
    assert _claim_overstatements(honest, nf.wired_media_names()) == set()


def test_leg6c_banned_media_claimed_is_a_violation_not_a_pass() -> None:
    """已除名的自媒体若被重新写进宣称面＝违规（它同时也不在实装集合里）。"""
    faces = {"echo.py:快报": "国内可达 RSS 聚合（IT之家/V2EX/少数派）。"}
    violations = _claim_overstatements(faces, nf.wired_media_names())
    assert {("echo.py:快报", "V2EX"), ("echo.py:快报", "少数派")} <= violations


# ---------------------------------------------------------------------------
# ⑦ 域名匹配与 source_authority 等价（不抄私名 ≠ 养第二把尺）
# ---------------------------------------------------------------------------

_MATCH_SAMPLES: tuple[tuple[str, str], ...] = (
    ("ithome.com", "ithome.com"),
    ("www.ithome.com", "ithome.com"),
    ("feeds.bbci.co.uk", "bbci.co.uk"),
    ("fake-ithome.com", "ithome.com"),
    ("evilpeople.com.cn", "people.com.cn"),
    ("sthnews.cn", "news.cn"),
    ("news.cn", "news.cn"),
    ("a.b.c.people.com.cn", "people.com.cn"),
    ("wallstreetcn.com", "dedicated.wallstreetcn.com"),
    ("", "ithome.com"),
)


def test_leg7_host_matcher_matches_source_authority_semantics() -> None:
    for left, right in _MATCH_SAMPLES:
        assert _host_matches(left, right) == sa._matches(left, right), (
            f"两把尺对 ({left}, {right}) 判定不同＝域名匹配漂了"
        )


def test_leg7b_hijack_probes_are_refused() -> None:
    """抢注探针：`fake-ithome.com` / `evilpeople.com.cn` 不得冒领准入。"""
    assert nf.is_admissible_news_url("https://fake-ithome.com/x") is False
    assert nf.is_admissible_news_url("https://evilpeople.com.cn/x") is False
    assert nf.is_admissible_news_url("https://www.ithome.com/1/001/052.htm") is True


# ---------------------------------------------------------------------------
# 运行期出站门（名册对 ≠ 条目对）＋ 台账 #12 语义没改坏
# ---------------------------------------------------------------------------

_TECH_FEED = nf._FEEDS[0][0] if nf._FEEDS else "https://www.ithome.com/rss/"

_MIXED_LINK_RSS = """<rss version="2.0"><channel><title>混合链</title>
  <item><title>正规源条目</title><link>https://www.ithome.com/1/001/052.htm</link>
    <description>这条链向名册内的正规源。</description></item>
  <item><title>转载去头条</title><link>https://www.toutiao.com/a700000/</link>
    <description>这条链向聚合转载档。</description></item>
  <item><title>转载去百家号</title><link>https://baijiahao.baidu.com/s?id=9</link>
    <description>这条链向自媒体。</description></item>
  <item><title>论坛帖回潮</title><link>https://www.v2ex.com/t/1241462</link>
    <description>这条链向论坛 UGC。</description></item>
  <item><title>不认识的博客</title><link>https://randomblog.example.org/post</link>
    <description>名册外域名按白名单口径同样拒。</description></item>
  <item><title>没有链接的条目</title><description>无 URL 时来源取登记名，保留。</description></item>
</channel></rss>
"""

_MARKETING_RSS = """<rss version="2.0"><channel><title>营销夹具</title>
  <item><title>【推广】某厂急聘 Java 工程师</title><link>https://www.ithome.com/1/002/001.htm</link>
    <description>求职推广条目，台账 #12 必须丢。</description></item>
  <item><title>拼团薅羊毛：限时购三件套</title><link>https://www.ithome.com/1/002/002.htm</link>
    <description>营销条目，标题命中即弃。</description></item>
  <item><title>某部发布新一代旗舰芯片</title><link>https://www.ithome.com/1/002/003.htm</link>
    <description>正规条目，摘要要作为第二行上屏。</description></item>
</channel></rss>
"""


@pytest.fixture(autouse=True)
def _no_egress_and_clean_cache(monkeypatch) -> Iterable[None]:
    """全局拦外呼：本件任何用例都不许真打网络（禁外发＝SEAT-RULES §绝对禁执行面）。"""
    calls: list[str] = []

    def _blocked(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        raise AssertionError(f"未打桩的外呼发生了：{url}")

    monkeypatch.setattr(nf, "_fetch_feed_text", _blocked)
    nf.reset_news_cache()
    yield
    nf.reset_news_cache()


def test_leg8_runtime_gate_drops_non_whitelisted_item_links(monkeypatch) -> None:
    """条目 URL 指向名册外/自媒体 ⇒ 丢；名册内与无 URL 条目 ⇒ 留（反向不误伤）。"""
    seen: list[str] = []

    def _fake(url: str, timeout_seconds: float) -> str:
        seen.append(url)
        return _MIXED_LINK_RSS

    monkeypatch.setattr(nf, "_fetch_feed_text", _fake)
    items = nf.fetch_headlines("tech", cache_seconds=0.0, max_items=20)

    titles = [item.title for item in items]
    assert titles == ["正规源条目", "没有链接的条目"], f"运行期出站门漏判或误伤：{titles}"
    assert seen == [_TECH_FEED], "tech 类目应只抓名册内那一枚端点"


def test_leg8b_runtime_feed_gate_refuses_rogue_feed_row(monkeypatch) -> None:
    """注毒：有人往 `_FEEDS` 塞一行禁域名 ⇒ 运行期 `_feeds_for` 就不给它发外呼。"""
    calls: list[str] = []

    def _record(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return _MIXED_LINK_RSS

    monkeypatch.setattr(nf, "_fetch_feed_text", _record)
    monkeypatch.setattr(
        nf,
        "_FEEDS",
        (*nf._FEEDS, ("https://www.v2ex.com/index.xml", "V2EX", "tech")),
    )
    nf.reset_news_cache()
    items = nf.fetch_headlines("tech", cache_seconds=0.0, max_items=20)
    assert "https://www.v2ex.com/index.xml" not in calls, "毒行被真-fetch＝名册门只在测试里生效"
    assert items and all(not nf.is_banned_news_url(item.url) for item in items)


def test_leg9_marketing_filter_and_summary_line_survive_the_gate(monkeypatch) -> None:
    """台账 #12 语义没改坏：营销条目仍被丢、真实摘要行仍在（准入门不得把这两格吃掉）。"""

    def _fake(url: str, timeout_seconds: float) -> str:
        return _MARKETING_RSS

    monkeypatch.setattr(nf, "_fetch_feed_text", _fake)
    items = nf.fetch_headlines("tech", cache_seconds=0.0, max_items=20)

    assert [item.title for item in items] == ["某部发布新一代旗舰芯片"], "营销过滤语义被改动"
    assert items[0].summary.startswith("正规条目")
    body = nf.format_news_brief(items, "科技")
    assert "    正规条目，摘要要作为第二行上屏。" in body, "摘要行（禁标题党）没进纯文本快报"


def test_leg9b_degraded_paths_untouched(monkeypatch) -> None:
    """既有降级语义一字不许变：全源失败＝[]（不抛）、部分失败＝条目变少。"""

    def _boom(url: str, timeout_seconds: float) -> str:
        raise OSError("network down")

    monkeypatch.setattr(nf, "_fetch_feed_text", _boom)
    nf.reset_news_cache()
    assert nf.fetch_headlines("mix") == []
    assert nf.fetch_headlines("world") == []
    body = nf.format_news_brief([], "综合")
    assert "快报暂时拉不到" in body, "空态降级文案被改动"


def test_leg10_whitelist_never_empties_every_category_silently() -> None:
    """准入门生效后，每个对外类目仍必须至少有一枚实装源（拦「门把类目关空」这一手）。

    读数来源＝名册派生，不是硬编码期望：类目集合与标签集共用 `CATEGORY_LABELS`。
    """
    for category in ("tech", "finance", "world", "mix"):
        feeds = nf._feeds_for(category)
        assert feeds, f"类目 {category} 过门后零源＝对外会静默空态，需要接线或改宣称"
