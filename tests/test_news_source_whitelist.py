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
from plugins.bot_unified_runtime.domains.core.shared_pool import get_shared_pool
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


def _row_should_be_wired(source: NewsSource) -> bool:
    """名册行「该不该被真抓」的**独立重推**（②③ 两把老尺与替代锁 ㉑ 共用这一把）。

    判据五件一件件写出来，与产线 ``_wired_sources()`` 同语义但不同路：
    - 准入 ∧ 有端点 ∧ 有类目；
    - 档位**先在册**（在 ``REACHABILITY_TIERS`` 里——新造一个档名结构上接不了线）；
    - 档位**再可接**（在 ``_WIREABLE_REACH`` 里）；
    - 且**没有被 ``wire_block`` 否决**（2026-10-08 三批才真的生效：此前产线只判档位，
      写了否决的 rt/aljazeera/openai/cgtn/tass 五枚一直躺在抓取列表里＝「写了没执法」）。
    任何一件被产线或名册偷偷放宽 ⇒ 腿 ㉑ 的逐枚相等当场红（＝放宽一条腿同批配的替代锁）。
    """
    return bool(
        source.admitted
        and source.endpoint
        and source.category
        and source.reachability in nf.REACHABILITY_TIERS
        and source.reachability in _WIREABLE_REACH
        and not source.wire_block.strip()
    )


def _wired_endpoints(sources: Iterable[NewsSource]) -> set[str]:
    return {source.endpoint for source in sources if _row_should_be_wired(source)}


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
        wired = _row_should_be_wired(source)
        if wired and tier > sa.TIER_MAJOR_MEDIA and tier != sa.TIER_VERTICAL:
            problems.append(f"{source.key}: 已接线但主域名 {source.domains[0]} 档位 {tier} 未登记 ⇒ 无准入依据（不许例外）")
        elif wired and tier == sa.TIER_VERTICAL and not source.note.strip():
            problems.append(f"{source.key}: 垂类档（TIER_VERTICAL）接线必须在行内写死 note 例外理由")
    return problems


def _reachability_violations(sources: Iterable[NewsSource], feeds: Iterable[tuple[str, str, str]]) -> list[str]:
    """③：被接线的行必须实测可达＋带证据；未实测/冻结/结构性缺席的行不得被抓取。

    🔴 2026-10-08 三批改写：反向那半把尺原来只判「档位可接＋端点＋类目 ⇒ 必须接线」，
    从不读 ``wire_block`` ⇒ 产线与名册漂移它看不见，写了否决的行反被它咬成「失踪」。
    现在两轴分开判：**该接的没接**＝漂移红；**被否决的没在抓取列表**＝正常，但否决
    必须写明缺哪件（空话/留白由腿 ㉑ 咬）。
    """
    wired_endpoints = {url for url, _media, _category in feeds}
    problems: list[str] = []
    for source in sources:
        if not source.admitted:
            continue
        if source.endpoint and source.endpoint in wired_endpoints:
            if source.reachability not in _WIREABLE_REACH or source.reachability not in nf.REACHABILITY_TIERS:
                problems.append(f"{source.key}: 可达性档位 {source.reachability} 不可接线却进了抓取列表")
            elif source.wire_block.strip():
                problems.append(f"{source.key}: 带接线否决标记却进了抓取列表＝否决没执法")
            if not source.probe.strip():
                problems.append(f"{source.key}: 已接线却没有任何实测证据指针（probe 空）＝宣称没证据")
            if not source.category:
                problems.append(f"{source.key}: 已接线但 category 空（类目归属未裁）")
        elif _row_should_be_wired(source):
            problems.append(
                f"{source.key}: 准入＋端点＋类目＋可接档位齐、且无否决标记，却不在抓取列表"
                "＝名册与抓取列表漂移（静默失踪）"
            )
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
    """`_FEEDS` 必须由名册派生（禁第二份清单）：逐行等值比对。

    🔴 2026-10-08 三批：这把尺自己也得跟着派生式改写——旧写法在这里手抄了
    「准入 ∧ 端点 ∧ 类目 ∧ 档位可接」四件、漏了 ``wire_block``，于是产线补上第五件
    之后它把**正确**的产线判成「有人手写了第二真身」。现改读 ``_row_should_be_wired``
    （五件齐判，与本件其余尺同一把），等值判据本身一字未松。
    """
    derived = tuple(
        (source.endpoint, source.media, source.category)
        for source in NEWS_SOURCES
        if _row_should_be_wired(source)
    )
    assert nf._FEEDS == derived, "抓取列表与名册派生结果不等＝有人手写了第二真身"
    assert _wired_endpoints(NEWS_SOURCES) == {url for url, _m, _c in nf._FEEDS}


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
    """诚实处置：**不可接的档位**与**带否决的行**都必须从「准入未接线」读得出。

    🔴 2026-10-08 三批改写（原判据把「中国新闻网」钉成未接线，她批准放开二批接线后
    那半把已过时）。放宽的同时这把尺变**严**：不再逐枚点名字面，而是**凡档位不可接
    或带否决的行，一枚都不许出现在抓取列表里；凡出现在「未接线」集合里的，都必须
    说得出为什么不可接**（档位字面值仍逐枚钉死，镀档即红）。
    """
    unwired = nf.admitted_unwired_media_names()
    wired = nf.wired_media_names()
    assert not (wired & unwired), "同一枚源既算接线又算未接线＝名册自相矛盾"
    for key, expected in (
        ("cnn", nf.REACH_STRUCTURAL_ABSENT),
        ("zaobao", nf.REACH_STRUCTURAL_ABSENT),
        ("xinhuanet", nf.REACH_FROZEN_STALE),
        ("people", nf.REACH_FROZEN_STALE),
        ("chinanews", nf.REACH_PENDING_REVERIFY),
        ("nhk", nf.REACH_FROZEN_STALE),
        ("voanews", nf.REACH_STRUCTURAL_ABSENT),
    ):
        source = next(row for row in NEWS_SOURCES if row.key == key)
        assert source.reachability == expected, f"{key} 可达性档位被改：{source.reachability}"
    # 不可接档位的行 ⇒ 必须读得出「在册未接线」。
    for media in ("新华社", "人民日报", "CNN", "联合早报", "NHK", "美国之音（VOA）"):
        assert media in unwired, f"{media} 应从「准入未接线」集合里读得出"
    # 档位可接、却被接线否决标住的行同样不许出现在抓取列表（否决＝真的不抓）。
    for source in nf.tier_wireable_but_blocked_sources():
        assert source.media in unwired, f"{source.key}: 有否决标记却不算诚实缺席"
        assert source.endpoint not in {url for url, _m, _c in nf._FEEDS}
    # 中国新闻网：三批起**已接线**（席位出口有读数、无否决），不再是「未接线」样本；
    # 档位仍 pending_reverify——「接线」与「产线证明过」是两轴，本行就是那两轴的活样本。
    assert "中国新闻网" not in unwired, "chinanews 已随三批放开接线，还当未接线＝账没跟上"
    assert "中国新闻网" in wired


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
    """全局拦外呼：本件任何用例都不许真打网络（禁外发＝SEAT-RULES §绝对禁执行面）。

    🔴 2026-10-08 三批补两件事：① 隔离短路账与轮转位（进程内临时态，不清会跨用例串味）；
    ② 收尾把「补投/迟到」那批外呼**收干**——出卡路径不再等第二批，monkeypatch 一还原，
    还在池里排着的后台任务就会打到真网络。收干放在本夹具的 finalizer 里（显式吃
    ``monkeypatch`` ⇒ 比它先退），收不干就直接红，不许带外呼退出。
    """
    calls: list[str] = []

    def _blocked(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        raise AssertionError(f"未打桩的外呼发生了：{url}")

    monkeypatch.setattr(nf, "_fetch_feed_text", _blocked)
    nf.reset_news_cache()
    nf.reset_news_fetch_state()
    yield
    assert nf.wait_for_outstanding_fetches(20.0), "补投/迟到那批没收干＝退出后可能打到真网络"
    nf.reset_news_cache()
    nf.reset_news_fetch_state()


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


# ===========================================================================
# 2026-10-08 澜汐源清单接线波（席 NEWS-LIST-20261008，全离线、零外呼）
# ---------------------------------------------------------------------------
# 清单真身＝她 2026-10-08 的原话：时政/综合 10 源 + AI 内容面（B 站 UP 主橘鸦/黑鸦）
# + AI 厂家重点关注 14 家。本段七把尺只判四件事：
#   ⑧ 清单逐枚在册（覆盖门，配注毒「删一行必红」＋反真空「空册必红」）
#   ⑨ 每行四件齐（稳定 id / 类目 / 取数口或写明缺哪件 / 可达性档位在册）
#   ⑩ 反谎报（shape_ready 行零接线；档位名不许顺手新造）
#   ⑪⑫ 跨源同题折叠可证伪（注毒两发）＋键段禁 `:` 复用紧急域唯一口
#   ⑬ 新类目派生与「新类目不误抓全量」
#   ⑭ 新闻不进 ANN/RAG（AST 导入边界，散文约定不算门）
# 台账 #12/#62 的既有语义（营销过滤、降级文案、七把老尺）由上面的腿继续守着。
# ===========================================================================

#: ⑧ 时政/综合 10 源（按**稳定 id** 对账，展示名可改而 id 不改）。
HER_NEWS_ROSTER_KEYS_20261008: frozenset[str] = frozenset(
    {
        "bbc",  # BBC（BBC中文，已接线 degraded）
        "cnn",  # CNN（结构性无 RSS）
        "voanews",  # 「美国广播电台」＝公开口径 美国之音 VOA
        "nhk",  # NHK
        "zaobao",  # 联合早报
        "rt",  # RT（今日俄罗斯）
        "aljazeera",  # 半岛电视台
        "xinhuanet",  # 新华社
        "people",  # 人民日报
        "cctv",  # 央视新闻
    }
)

#: ⑧ AI 厂家重点关注 14 家（含两枚「主体待点名」占位行）。
HER_AI_VENDOR_KEYS_20261008: frozenset[str] = frozenset(
    {
        "mistral",
        "deepseek",
        "meta_ai",
        "zhipu",  # GLM（智谱）
        "qwen",
        "moonshot",  # Kimi（月之暗面）
        "openai",  # GPT
        "anthropic",  # Claude
        "xai",  # Grok
        "google_ai",  # Gemini
        "minimax",
        "hunyuan",  # 腾讯混元
        "happy-series",  # happy 系列（主体待她点名）
        "bili-own-model",  # B 站自研大模型（主体待她点名）
    }
)

#: ⑧ AI 内容面：B 站两位 UP 主（admitted=False，见下腿 ⑩b 的冲突登记）。
HER_AI_CREATOR_KEYS_20261008: frozenset[str] = frozenset({"bili-up-juya", "bili-up-heiya"})

#: 清单上**册内本来就有**的六枚（2026-10-02 那波已登记；本波只补类目/清账，不动档位）。
_PREEXISTING_ROSTER_KEYS: frozenset[str] = frozenset(
    {"bbc", "cnn", "zaobao", "xinhuanet", "people", "cctv"}
)

#: 本波**新增**的全部行（20 枚）＝「零接线」与「四件齐」判据的适用范围。
#: 🔴 判据刻意只管本波新增行：存量行的形状由上面七把老尺继续审，别把两波账混一把尺。
HER_LIST_KEYS_ALL_20261008: frozenset[str] = (
    HER_NEWS_ROSTER_KEYS_20261008
    | HER_AI_VENDOR_KEYS_20261008
    | HER_AI_CREATOR_KEYS_20261008
)
NEW_WAVE_KEYS_20261008: frozenset[str] = HER_LIST_KEYS_ALL_20261008 - _PREEXISTING_ROSTER_KEYS

#: ⑩ 首批（2026-10-08 清单 20 枚新增行）**真被接线**的 key 基线。
#: 🔴 2026-10-08 三批放开后＝``{"google_ai"}`` 一枚：杠杆只有「``pending_reverify`` 进
#: 可接线索引」这一条，档位一字未动（gemini 那枚二批有席位出口读数、无否决标记）。
#: 其余 13 枚清单行今日仍读不出源：openai/rt/aljazeera 带 ``wire_block``（缺件由她给）、
#: nhk/voanews 档位不可接、其余 shape_ready＝零读数＝结构上接不了线。
#: 新增一枚必须**同批在这里点名**，不点名即红＝「静默放开」被结构抓住（判据永远是
#: 「档位不在索引里 ⇒ 抓不到」，基线只是放开的账）。
NEW_WAVE_WIRED_BASELINE_20261008: frozenset[str] = frozenset({"google_ai"})

#: ⑨ 档位三期的标记词（缺端点的行必须写明缺哪件，不许留白当「以后再说」）。
_TIER_MARKERS: tuple[str, ...] = ("档①", "档②", "档③")
#: ⑨ 无端点行的必填自述里至少命中一枚（＝诚实登记缺哪件，不许留白当「以后再说」）。
_MISSING_PIECE_MARKERS: tuple[str, ...] = (
    "端点留空",
    "取数口",
    "不猜",
    "不编",
    "缺 uid",
    "未点名",
)
#: 未准入行必须写明待谁裁什么（拦「僵尸行」：躺在册里、既不接也没人知道为什么）。
_BLOCKED_REASON_MARKERS: tuple[str, ...] = ("待她", "冲突", "禁册", "待裁", "请她", "点名")

#: ⑭ 边界词：出现这些**导入**即「新闻被喂进向量库」的形态（AST 只判导入、
#: 不判散文——本文件与 news_feeds.py 的头注都要写明 ANN/RAG 字样，判散文必假红）。
_VECTOR_STORE_IMPORT_TOKENS: tuple[str, ...] = (
    "kb_wiki",
    "knowledge",
    "embedding",
    "embed",
    "faiss",
    "ann_index",
    "vector",
)


def _roster_coverage_violations(
    sources: Iterable[NewsSource], expected_keys: Iterable[str]
) -> list[str]:
    """⑧ 现算：清单点名的每一枚都必须有名册行；🔴 空名册即红（反真空腿）。"""
    rows = list(sources)
    if not rows:
        return ["源注册表为空＝覆盖门空转（反真空：空输入必须红，不许『没东西可判』式通过）"]
    keys = {source.key for source in rows}
    missing = sorted(set(expected_keys) - keys)
    return [f"清单点名的源未落进源注册表：{key}" for key in missing]


def _row_shape_violations(sources: Iterable[NewsSource]) -> list[str]:
    """⑨ 全局那半把尺：稳定 id / 登记名 / 域名段 / 类目有真身 / 档位在册 / 接线必带证据。

    适用**全册**（存量行同样不许新造档位名、不许无证据宣称已接通）。
    🔴 反真空：空名册直接判红，不许「没东西可判＝通过」。
    """
    rows = list(sources)
    if not rows:
        return ["源注册表为空＝四件齐判据空转（反真空：空输入必须红）"]
    problems: list[str] = []
    labels = set(nf.CATEGORY_LABELS)
    seen_keys: set[str] = set()
    for source in rows:
        if not source.key.strip():
            problems.append("行缺稳定 id（key 空）")
        if source.key in seen_keys:
            problems.append(f"{source.key}: 稳定 id 重复＝两行抢一个身份")
        seen_keys.add(source.key)
        if not source.media.strip():
            problems.append(f"{source.key}: 缺登记名（media 空）")
        if not source.domains:
            problems.append(f"{source.key}: 缺域名段（news_source_for 判据会 IndexError）")
        if source.category and source.category not in labels:
            problems.append(f"{source.key}: 类目 {source.category} 不在 CATEGORY_LABELS＝归类无真身")
        if source.reachability not in nf.REACHABILITY_TIERS:
            problems.append(
                f"{source.key}: 可达性档位 {source.reachability} 不在 REACHABILITY_TIERS"
                "＝顺手新造档位名（通往『把慢源写成已接通』的后门）"
            )
        # 反谎报：宣称「已实测可达/已降级接线」的行必须拿得出带日期带「测」字的探针。
        if source.reachability in _WIREABLE_REACH and (
            "测" not in source.probe or not re.search(r"\d{4}-\d{2}-\d{2}", source.probe)
        ):
            problems.append(f"{source.key}: 档位 {source.reachability} 却无『日期＋实测』探针＝宣称没证据")
    return problems


def _declared_pieces_violations(sources: Iterable[NewsSource], expected_keys: Iterable[str]) -> list[str]:
    """⑨ 严格那半把尺（只量清单新增行）：取数口引用方式 + 可达性档位 + 缺件自述 + 三档标记。

    新增行的四件＝稳定 id / 类目 / **URL 或取数口引用方式**（有端点，或写明缺哪件）/
    可达性档位。🔴 无端点又不写缺件、或没标档①②③（推进口径失联）一律红。
    """
    rows = list(sources)
    if not rows:
        return ["源注册表为空＝清单四件判据空转（反真空）"]
    by_key = {source.key: source for source in rows}
    problems: list[str] = []
    for key in sorted(set(expected_keys)):
        source = by_key.get(key)
        if source is None:
            problems.append(f"{key}: 清单行缺席（覆盖门另有判据，这里不重复计数）")
            continue
        if not source.category:
            problems.append(f"{key}: 清单行缺类目（时政/国际/AI 厂家/AI 内容 归类无落点）")
        if source.reachability not in nf.REACHABILITY_TIERS:
            problems.append(f"{key}: 档位 {source.reachability} 不在册")
        if not source.endpoint and not any(
            marker in source.note for marker in _MISSING_PIECE_MARKERS
        ):
            problems.append(f"{key}: 无端点却未写明缺哪件（端点留空/取数口/不猜/不编…）")
        if not any(marker in source.note for marker in _TIER_MARKERS):
            problems.append(f"{key}: 未标档①/档②/档③＝三档推进口径失联")
        if not source.admitted and not any(marker in source.note for marker in _BLOCKED_REASON_MARKERS):
            problems.append(f"{key}: 未准入行没写明待谁裁什么＝僵尸行")
    return problems


def _wired_new_wave_keys(sources: Iterable[NewsSource]) -> set[str]:
    """⑩ 现算：清单里的源此刻有几枚真被抓取（＝名册派生的抓取列表，不是宣称）。"""
    wired_endpoints = {url for url, _media, _category in nf._FEEDS}
    return {
        source.key
        for source in sources
        if source.key in NEW_WAVE_KEYS_20261008 and source.endpoint in wired_endpoints
    }


def _topic_fold_problems(items: list[nf.NewsItem]) -> list[str]:
    """⑪ 现算尺：折叠后同题是否只剩一条、出处列表是否保住了全部来源。"""
    folded = nf.fold_same_topic(items)
    problems: list[str] = []
    keyed: dict[str, int] = {}
    for item in folded:
        key = nf.news_topic_key(item.title)
        if not key:
            continue
        keyed[key] = keyed.get(key, 0) + 1
    duplicated = [key for key, count in keyed.items() if count > 1]
    if duplicated:
        problems.append(f"折叠后仍有多条同题：{duplicated}")
    for item in folded:
        if len(item.sources) > 1 and item.source != item.sources[0]:
            problems.append(f"{item.title}: 折叠条目的主源与出处列表首枚不一致")
    return problems


def _imported_module_names(path: Path) -> list[str]:
    """AST 取一个文件里全部**导入**的模块名（只判导入、不判散文）。"""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# ---------------------------------------------------------------------------
# ⑧ 清单在册覆盖（＋注毒＋反真空）
# ---------------------------------------------------------------------------


def test_leg11_20261008_source_list_is_fully_registered() -> None:
    assert _roster_coverage_violations(NEWS_SOURCES, HER_NEWS_ROSTER_KEYS_20261008) == []
    assert _roster_coverage_violations(NEWS_SOURCES, HER_AI_VENDOR_KEYS_20261008) == []
    assert _roster_coverage_violations(NEWS_SOURCES, HER_AI_CREATOR_KEYS_20261008) == []


def test_leg11b_poison_dropping_a_declared_source_turns_red() -> None:
    """注毒：把清单里一枚源从名册删掉 ⇒ 覆盖门必须点名它（防「清单漏接还宣称齐了」）。"""
    for dropped in ("rt", "nhk", "openai", "hunyuan", "bili-up-juya"):
        survivors = tuple(row for row in NEWS_SOURCES if row.key != dropped)
        violations = _roster_coverage_violations(survivors, NEW_WAVE_KEYS_20261008)
        assert any(dropped in problem for problem in violations), f"删掉 {dropped} 没被咬：{violations}"


def test_leg11c_anti_vacuity_empty_roster_turns_red() -> None:
    """反真空腿（硬要求 D）：名册清空时判据必红，绝不许「空输入＝通过」。"""
    assert _roster_coverage_violations([], HER_NEWS_ROSTER_KEYS_20261008), "空名册被判通过"
    assert _row_shape_violations([]), "空名册被判四件齐"
    # 老尺同样不许空转：名册清空 ⇒ ① 白名单门对现存抓取列表必须报「名册外」。
    assert _whitelist_violations(nf._FEEDS, []), "清空名册后门① 没咬＝门只在有东西时才生效"
    assert nf._FEEDS, "抓取列表为空＝名册派生断了（本件全局前提）"


# ---------------------------------------------------------------------------
# ⑨ 每行四件齐 ＋ ⑩ 反谎报（本波零接线）
# ---------------------------------------------------------------------------


def test_leg12_every_row_carries_the_four_required_pieces() -> None:
    assert _row_shape_violations(NEWS_SOURCES) == []
    assert _declared_pieces_violations(NEWS_SOURCES, NEW_WAVE_KEYS_20261008) == []


def test_leg12b_poison_slow_source_marked_live_turns_red() -> None:
    """注毒：把「形状已备待实跑」写成 wired_live（无探针）＝谎报已接通 ⇒ 必红。"""
    slow = next(row for row in NEWS_SOURCES if row.key == "nhk")
    lying = NewsSource(
        key=slow.key,
        media=slow.media,
        domains=slow.domains,
        admitted=True,
        endpoint=slow.endpoint,
        category=slow.category,
        reachability=nf.REACH_WIRED_LIVE,
        probe="",
        note=slow.note,
    )
    assert any("宣称没证据" in problem for problem in _row_shape_violations([lying]))
    assert _row_shape_violations([row for row in NEWS_SOURCES if row is not lying]) == []
    # 新造档位名（把降级偷偷写成新档位）同样必红。
    invented = NewsSource(
        key="sneaky",
        media="某新档源",
        domains=("ithome.com",),
        admitted=True,
        endpoint="https://www.ithome.com/rss/",
        category="tech",
        reachability="kinda_live",
        probe="2026-10-08 本席注毒",
        note="档①",
    )
    assert any("不在 REACHABILITY_TIERS" in problem for problem in _row_shape_violations([invented]))
    # 无端点又不写缺哪件／没标档 ⇒ 红（拦「留白当以后再说」与「登记了但下一步不明」）。
    naked = NewsSource(
        key="naked2",
        media="无端点无自述",
        domains=("example.org",),
        admitted=True,
        category="politics",
        reachability=nf.REACH_SHAPE_READY,
        note="",
    )
    problems = _declared_pieces_violations([naked], ["naked2"])
    assert any("未写明缺哪件" in problem for problem in problems), problems
    assert any("未标档" in problem for problem in problems), problems
    # 僵尸行：未准入又不写待谁裁 ⇒ 红。
    zombie = NewsSource(
        key="zombie",
        media="僵尸行",
        domains=("example.net",),
        admitted=False,
        category="ai_vendor",
        reachability=nf.REACH_SHAPE_READY,
        note="档②。",
    )
    assert any(
        "僵尸行" in problem for problem in _declared_pieces_violations([zombie], ["zombie"])
    ), _declared_pieces_violations([zombie], ["zombie"])
    # 清单行没类目（归类无落点）⇒ 红。
    no_cat = NewsSource(
        key="rt",
        media="RT（今日俄罗斯）",
        domains=("rt.com",),
        admitted=True,
        endpoint="https://www.rt.com/rss/",
        category="",
        reachability=nf.REACH_SHAPE_READY,
        note="档①。",
    )
    assert any(
        "缺类目" in problem for problem in _declared_pieces_violations([no_cat], ["rt"])
    ), _declared_pieces_violations([no_cat], ["rt"])


def test_leg13_new_wave_sources_are_registered_not_wired() -> None:
    """⑩ 首批 20 枚的接线账：只认**点名的基线**，形状判据由「blanket 钉 shape_ready」改为派生式。

    🔴 旧判据「这 20 枚一律 shape_ready 或不准入」在二批跑出读数后就把**正确**的名册
    判成违规（跑过还留着 shape_ready＝档位撒谎，见 google_ai 行注）。放宽的同批这把尺
    变严了两件事：
    ① 真被抓住的首批行必须逐枚登记在 ``NEW_WAVE_WIRED_BASELINE_20261008``（没登记即红）；
    ② 每枚首批行都得说得出「为什么今日读不出源」——档位不可接 ⇒ 有实测或零读数凭证；
      档位可接却没接线 ⇒ ``wire_block`` 必须写明缺哪件（留白由腿 ㉑ 咬）。
    """
    assert _wired_new_wave_keys(NEWS_SOURCES) == set(NEW_WAVE_WIRED_BASELINE_20261008), (
        f"首批新增行里真被抓取的源与放开账不等：现算 {sorted(_wired_new_wave_keys(NEWS_SOURCES))}"
        "（新增一枚要同批点名，别静默放开；少一枚＝接线被吞或基线没跟上）"
    )
    by_key = {row.key: row for row in NEWS_SOURCES}
    wired_urls = {url for url, _m, _c in nf._FEEDS}
    for key in sorted(NEW_WAVE_KEYS_20261008):
        row = by_key[key]
        if key in NEW_WAVE_WIRED_BASELINE_20261008:
            assert row.endpoint in wired_urls, f"{key}: 登记为已放开却读不出源＝基线与产线漂移"
            assert row.reachability in _WIREABLE_REACH, f"{key}: 接了线却没有可接档位凭证"
            continue
        assert row.endpoint not in wired_urls or not row.endpoint, (
            f"{key}: 没登记在放开账里却被抓取＝静默放开"
        )
        # 没接线的首批行必须说得出为什么：不可接档位（有凭证或零读数）／带否决标记／未准入。
        reason = (
            row.reachability not in _WIREABLE_REACH
            or bool(row.wire_block.strip())
            or not row.admitted
            or not row.endpoint
        )
        assert reason, f"{key}: 在册、档位可接、无否决却没接线＝失踪（名册与抓取列表漂移）"
    # 诚实缺席必须读得出：带否决标记与档位不可接的行都在「准入未接线」集合里。
    unwired = nf.admitted_unwired_media_names()
    for media in ("美国之音（VOA）", "NHK", "RT（今日俄罗斯）", "半岛电视台", "GPT（OpenAI）"):
        assert media in unwired, f"{media} 应作为『在册未接线』读得出"
    # 🔴 档位不许为了接线被镀金：首批里已放开的 google_ai 仍是 pending_reverify。
    assert by_key["google_ai"].reachability == nf.REACH_PENDING_REVERIFY, (
        "google_ai 档位被镀成 wired_live＝产线没复跑过却说已接通（台账 #73 点名的谎报形态）"
    )


def test_leg13b_ugc_conflict_is_registered_as_blocked_not_silently_admitted() -> None:
    """B 站两位 UP 主：2026-10-02 UGC 禁册与 2026-10-08 清单正面冲突 ⇒ 本波记 blocked。

    🔴 门④ 令 bilibili.com **不可能**被标 admitted（禁册域名准入即红），所以「接不进
    来」是结构事实不是取舍。这条腿锁的是：不许有人为了让清单『看起来接了』把它改成
    准入，也不许把 UP 主塞进任何豁免表。
    """
    by_key = {row.key: row for row in NEWS_SOURCES}
    for key in sorted(HER_AI_CREATOR_KEYS_20261008):
        row = by_key[key]
        assert row.admitted is False, f"{key} 被改准入＝静默推翻 2026-10-02 禁册裁定"
        assert "bilibili.com" in row.domains
        assert "bilibili_adapter" in row.note, f"{key}: 没写复用哪条取数口＝日后会长出第二条通路"
    assert nf.is_admissible_news_url("https://space.bilibili.com/12345") is False
    # 反向不误伤：禁册外的清单域仍是准入的（未接线≠不准入，两回事）。
    assert nf.is_admissible_news_url("https://www.aljazeera.com/news/x") is True


def test_leg13c_pending_subject_rows_cannot_match_any_real_host() -> None:
    """「happy 系列」「B 站自研大模型」＝主体未点名：占位域结构上不可能命中真实站点。"""
    for key in ("happy-series", "bili-own-model"):
        row = next(r for r in NEWS_SOURCES if r.key == key)
        assert row.admitted is False and row.endpoint == "", f"{key}: 主体没点名就落了端点＝编 URL"
        assert all("pending-subject.invalid" in domain for domain in row.domains)
    assert nf.news_source_for("https://pending-subject.invalid/x") is not None
    assert nf.news_source_for("https://happy-ai.example.com/x") is None


# ---------------------------------------------------------------------------
# ⑪⑫ 跨源同题折叠（注毒两发）＋ 键段禁 `:` 复用唯一口
# ---------------------------------------------------------------------------

_SAME_A = "某厂商发布新一代推理模型 支持百万上下文"
_SAME_B = "  某厂商发布新一代推理模型  支持百万上下文 "  # 只差空白/首尾空格 ⇒ 该折
_ONE_CHAR_DIFF = "某厂商发布新一代推演模型 支持百万上下文"  # 中段差一个字 ⇒ 不该折
_OTHER_CATEGORY = "某厂商发布新一代推理模型 支持百万上下文"


def _item(title: str, source: str, url: str, category: str = "ai_vendor") -> nf.NewsItem:
    return nf.NewsItem(title=title, url=url, source=source, category=category)


def test_leg14_same_title_across_two_sources_folds_and_keeps_outlets() -> None:
    """注毒①（硬要求 C）：两源同题 ⇒ 折成一条**且出处列表保住两家**。"""
    folded = nf.fold_same_topic(
        [
            _item(_SAME_A, "GPT（OpenAI）", "https://openai.com/1"),
            _item(_SAME_B, "Claude（Anthropic）", "https://www.anthropic.com/2"),
        ]
    )
    assert len(folded) == 1, f"同题没折叠：{[item.title for item in folded]}"
    assert folded[0].sources == ("GPT（OpenAI）", "Claude（Anthropic）"), folded[0].sources
    assert folded[0].url == "https://openai.com/1", "折叠条目该保留先到源的链接（点一次进一家）"
    assert _topic_fold_problems([_item(_SAME_A, "A源", "https://a/1"), _item(_SAME_B, "B源", "https://b/2")]) == []
    body = nf.format_news_brief(folded, "AI 厂家")
    assert "GPT（OpenAI）/Claude（Anthropic）" in body, "并列出处没上卡面"


def test_leg14b_one_character_difference_does_not_fold() -> None:
    """注毒②（防过度折叠）：标题差一个字 ⇒ **不**折（两件事不许并成一件）。"""
    folded = nf.fold_same_topic(
        [
            _item(_ONE_CHAR_DIFF, "GPT（OpenAI）", "https://openai.com/1"),
            _item(_SAME_A, "Claude（Anthropic）", "https://www.anthropic.com/2"),
        ]
    )
    assert len(folded) == 2, [item.title for item in folded]
    assert all(item.sources in {("GPT（OpenAI）",), ("Claude（Anthropic）",)} for item in folded)
    # 跨类目同题**照折**（裁定序＝去重先于归类；键带类目会让它永远折不上）。
    cross_category = nf.fold_same_topic(
        [
            _item(_OTHER_CATEGORY, "新华社", "https://xinhuanet.com/1", category="politics"),
            _item(_OTHER_CATEGORY, "GPT（OpenAI）", "https://openai.com/2", category="ai_vendor"),
        ]
    )
    assert len(cross_category) == 1, "跨类目同题没折＝卡面会出现两行同一条新闻"
    assert cross_category[0].category == "politics", "折叠条目没取先到源的类目"
    assert cross_category[0].sources == ("新华社", "GPT（OpenAI）")
    # 反向不误伤：同家媒体重复投递同一 URL 仍由 URL 账吃掉，不该多出一条。
    assert len(nf.fold_same_topic([_item(_SAME_A, "GPT（OpenAI）", "https://openai.com/1")])) == 1


def test_leg14c_folding_runs_inside_fetch_pipeline_offline(monkeypatch) -> None:
    """端到端：mix 轮转合并后经同一把折叠尺（证明折叠不是只活在单测里的纯函数）。"""

    def _fake(url: str, timeout_seconds: float) -> str:
        article_url = {
            "https://www.ithome.com/rss/": "https://www.ithome.com/1/001/052.htm",
            "https://dedicated.wallstreetcn.com/rss.xml": "https://wallstreetcn.com/articles/1",
            "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml": "https://www.bbc.com/news/1",
        }[url]
        return (
            '<rss version="2.0"><channel><title>假源</title>'
            f"<item><title>多家同题：某模型发布新版本</title><link>{article_url}</link>"
            "<description>这条在三家源的标题一字不差。</description></item>"
            "</channel></rss>"
        )

    monkeypatch.setattr(nf, "_fetch_feed_text", _fake)
    nf.reset_news_cache()
    items = nf.fetch_headlines("mix", cache_seconds=0.0, max_items=8)
    assert len(items) == 1, f"同题三投没折成一条：{[item.title for item in items]}"
    assert set(items[0].sources) == {"IT之家", "华尔街见闻", "BBC中文"}, items[0].sources


def test_leg15_topic_key_segments_reuse_the_central_washing_port() -> None:
    """⑫ 键形：段段过紧急域 `is_legal_segment`（禁 `:` 与空白）、整键两段、标题注入冒号不多段。"""
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        is_legal_segment,
    )

    key = nf.news_topic_key(_SAME_A)
    segments = key.split(":")
    assert segments[0] == nf.NEWS_DEDUPE_NAMESPACE == "news", key
    assert len(segments) == 2, f"键段数不是 2＝有人把类目/标题里的分隔符带进键里：{key}"
    assert all(is_legal_segment(segment) for segment in segments), segments

    injected = nf.news_topic_key("新闻:标题:带冒号:与 空白")
    assert len(injected.split(":")) == 2, f"标题里的冒号撑出了额外键段：{injected}"
    assert all(is_legal_segment(segment) for segment in injected.split(":")), injected
    # 同输入恒同输出（幂等）；差一个字符必不同（不过度折叠的结构保证）。
    assert nf.news_topic_key(_SAME_A) == nf.news_topic_key(_SAME_B)
    assert nf.news_topic_key(_ONE_CHAR_DIFF) != nf.news_topic_key(_SAME_A)
    assert nf.news_topic_key("   ") == "", "空标题造出了键＝无标题条目会被误并"


# ---------------------------------------------------------------------------
# ⑬ 新类目派生（时政 / AI 厂家 / AI 内容）
# ---------------------------------------------------------------------------


def test_leg16_new_categories_are_derived_and_never_fall_back_to_all_feeds(
    monkeypatch,
) -> None:
    """新增类目必须①有真身标签 ②有名册行 ③精确取源（不误当「未知类目」抓全量）。

    旧 `_feeds_for` 硬编码过 ("tech","finance","world")：新增类目会掉进「未知类目
    ⇒ 回退全量」那一路，于是「时政」读出来是全体源混合轮转——归类维度被静默吃掉。

    🔴 2026-10-08 三批改写：原判据把 politics/ai_vendor/ai_content **三类一律钉成空集**，
    她批准放开二批接线后 ai_vendor 有了实装源（google_ai），空集判据遂把正确产线判红。
    放宽同批配的更严替代锁＝腿 ㉓「**类目为空即红、且逐枚写明缺哪件与由谁裁**」，加上
    本腿新加的「有源类目必须精确只取自己那几枚」（读得出源却抓了全量同样红）。
    空态不再逐枚字面钉死，改由 ㉓ 的登记基线**双向**判：该空的读得出源＝红；不该空的
    被登记成空＝红。
    """
    for category in ("politics", "ai_vendor", "ai_content"):
        assert category in nf.CATEGORY_LABELS, f"{category} 类目无标签真身"
        assert category in nf._EXACT_CATEGORIES, f"{category} 未进精确类目派生＝会误抓全量"
        assert any(row.category == category for row in NEWS_SOURCES), f"{category} 类目没有一行归属"
    assert nf._EXACT_CATEGORIES == frozenset(nf.CATEGORY_LABELS) - {"mix"}, "精确类目又硬编码了一份"

    calls: list[str] = []

    def _record(url: str, timeout_seconds: float) -> str:
        calls.append(url)
        return (
            '<rss version="2.0"><channel><title>假源</title>'
            "<item><title>某题第一条</title><link>https://www.ithome.com/1/001/052.htm</link>"
            "<description>假源的真实内容行。</description></item></channel></rss>"
        )

    monkeypatch.setattr(nf, "_fetch_feed_text", _record)
    # ① 登记为诚实缺席的类目：派生读空、外呼零发生（读空却没登记 ⇒ 腿 ㉓ 红）。
    for category in sorted(HONEST_EMPTY_CATEGORIES_20261008):
        nf.reset_news_cache()
        calls.clear()
        assert nf._feeds_for(category) == [], (
            f"{category} 登记为诚实缺席却读出了源＝基线与产线漂移（要放开同批改 ㉓）"
        )
        assert nf.fetch_headlines(category, cache_seconds=0.0) == []
        assert calls == [], f"{category} 零实装源却发了外呼：{calls}"
    # ② 有实装源的类目：精确只取自己那几枚，绝不回退全量。
    nf.reset_news_cache()
    calls.clear()
    vendor_rows = nf._feeds_for("ai_vendor")
    assert vendor_rows, "ai_vendor 读空＝三批放开的 google_ai 没进抓取列表（先查腿 ㉑ 的漂移判据）"
    assert {row[2] for row in vendor_rows} == {"ai_vendor"}
    assert len(vendor_rows) < len(nf._FEEDS), "ai_vendor 竟覆盖全部源＝又掉进『未知类目抓全量』老路"
    nf.fetch_headlines("ai_vendor", cache_seconds=0.0)
    assert set(calls) == {row[0] for row in vendor_rows}
    # ③ 反向不误伤：真正有实装源的旧类目照旧精确取源（不是回退全量）。
    for category in ("tech", "finance", "world"):
        rows = nf._feeds_for(category)
        assert rows, f"{category} 竟读不出源＝实装清单派生断了"
        assert {row[2] for row in rows} == {category}


# ---------------------------------------------------------------------------
# ⑭ 新闻不进 ANN/RAG（2026-10-08 Q-3 裁定；AST 只判导入）
# ---------------------------------------------------------------------------


def test_leg17_news_plane_never_imports_the_vector_store() -> None:
    """🔴 裁定边界：快报面只做去重/归类/卡面，不许通往向量库与索引重建链。

    判据形态＝AST 扫这两个文件的导入名（散文里写 ANN/RAG 是注释、不算违规）；
    这条腿同时拦住「顺手在 feeds 层加一行 `... import kb_wiki`」把新闻喂进 RAG。
    `kb_wiki` 同步链与 23:40 调度键本波一字未动，此腿就是那件「没动」的门。
    """
    root = PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "subscribe"
    targets = [
        root / "feeds" / "news_feeds.py",
        root / "capabilities" / "news.py",
    ]
    offenders: list[str] = []
    for target in targets:
        assert target.exists(), f"边界门读不到真身：{target}（改名要同批改这条腿，别让它空转）"
        for name in _imported_module_names(target):
            lowered = name.lower()
            if any(token in lowered for token in _VECTOR_STORE_IMPORT_TOKENS):
                offenders.append(f"{target.name} 导入了向量库面：{name}")
    assert offenders == [], offenders
    # 反向不误杀：本件自己的既有依赖（渲染/共享池/HTTP 出口）不该被这把尺咬。
    own = _imported_module_names(targets[0])
    assert any("shared_pool" in name for name in own), "快报面自身的依赖形状变了，先看清再改门"


# ===========================================================================
# 2026-10-08 二批接线波（席 NEWS-WAVE2-20261008）：**只追加**，上面任何一条腿一字未改
# -------------------------------------------------------------------------
# 为什么长在本件末尾而不是新文件：``scripts/doc_sync.py`` 按 ``glob("test_*.py")``
# 现算「测试文件数」投影进 ``docs/auto-facts.md``，新建 ``tests/test_*.py`` 当场漂。
# 本段三件事：
#   ⑮ 新锁一「可达性档位不许自证」：wired_live/wired_degraded 每行必须同时给得出
#      「日期」「测」字与「**哪儿测的**」出口标记——摘掉任一件必红（注毒腿 ⑮b）。
#      与既有腿 ⑨ 的差别＝那把只查日期＋测字，看不见「哪儿测的」（台账 #71 代理面：
#      同一枚端点经不同出口读数完全不同，「实测通过」不写出口等于没写）。
#   ⑯ 新锁二「去重折叠幂等」：同一批条目折两次结果逐字相同，且条数＝去重后的**题数**
#      （拦两种假账：幂等假账、以及「去重把两件事并成一件」）。
#   ⑰ 二批清单覆盖＋去重留痕：她列 33 项（NYT/WSJ/The Times/Asahi 各两次）必须逐枚
#      映射到名册行，且去重后恰 29 枚实体、同一实体只许一行（media 登记名全局唯一）。
# ===========================================================================

#: ⑰ 她 2026-10-08 二批**原话清单**（33 项，含重复项），逐项映射到名册稳定 id。
#: 🔴 这张表就是「去重留痕」的真身：重复列出的 NYT／WSJ／The Times／Asahi 各两次，
#: 映射到**同一个 key**，册内各只一枚行。
HER_RAW_ITEMS_20261008_W2: tuple[tuple[str, str], ...] = (
    ("美联社 AP", "apnews"),
    ("路透社 Reuters", "reuters"),
    ("法新社 AFP", "afp"),
    ("新华社", "xinhuanet"),
    ("《纽约时报》NYT", "nyt"),
    ("《纽约时报》NYT（她列第二次）", "nyt"),
    ("《华尔街日报》WSJ", "wsj"),
    ("《华尔街日报》WSJ（她列第二次）", "wsj"),
    ("CNN", "cnn"),
    ("BBC News", "bbc"),
    ("日本广播协会 NHK", "nhk"),
    ("CCTV", "cctv"),
    ("CGTN", "cgtn"),
    ("人民日报", "people"),
    ("半岛电视台 Al Jazeera", "aljazeera"),
    ("《时代》TIME", "time"),
    ("《新闻周刊》Newsweek", "newsweek"),
    ("泰晤士报 The Times", "times-uk"),
    ("泰晤士报 The Times（她列第二次）", "times-uk"),
    ("朝日新闻 Asahi Shimbun", "asahi"),
    ("朝日新闻 Asahi Shimbun（她列第二次）", "asahi"),
    ("TVB News", "tvb"),
    ("韩联社 Yonhap", "yonhap"),
    ("朝鲜中央通讯社 KCNA", "kcna"),
    ("RT 今日俄罗斯", "rt"),
    ("联合早报", "zaobao"),
    ("德新社 DPA", "dpa"),
    ("金融时报 FT", "ft"),
    ("塔斯社 TASS", "tass"),
    ("乌克兰国家通讯社 Ukrinform", "ukrinform"),
    ("环球报（按《环球时报》/Global Times 登记）", "globaltimes"),
    ("格拉玛报（古巴 Granma）", "granma"),
    ("共同社 Kyodo", "kyodo"),
)

#: ⑰ 二批**新增行**（册内此前没有的那 17 枚）；既有 12 枚走上面的老尺与本段的读数检查。
HER_LIST_KEYS_20261008_W2: frozenset[str] = frozenset(
    {
        "nyt", "wsj", "ft", "time", "newsweek", "asahi", "cgtn", "tass", "ukrinform",
        "times-uk", "tvb", "yonhap", "kcna", "dpa", "globaltimes", "granma", "kyodo",
    }
)
#: ⑰ 二批接线**放开账**（2026-10-08 三批，逐枚点名＝她批准的接线动作落在这里）。
#: 🔴 判据不是「档位镀金」：这七枚的档位仍是 ``pending_reverify``（席位出口读数，升
#: ``wired_live`` 只认产线出口复跑），杠杆只有「``pending_reverify`` 进可接线索引」。
#: 其余二批行读不出源各有原因且逐枚写在名册里：cgtn/tass 带 ``wire_block``（政策复核
#: ＋source_authority 登记由她裁）、times-uk/tvb/yonhap/kcna/dpa/globaltimes/granma/
#: kyodo＝structural_absent（这个出口拿不到 feed，端点留空不猜 URL）。
#: 基线是**逐枚相等**的判据：多一枚（静默放开）红、少一枚（接线被吞）也红。
W2_WIRED_BASELINE_20261008: frozenset[str] = frozenset(
    {"nyt", "wsj", "ft", "time", "newsweek", "asahi", "ukrinform"}
)

#: ㉑ 全册接线基线（现算 ``_FEEDS`` 的 key 集必须与它逐枚相等）＝存量棘轮的正面形态：
#: 「在册留脏」不算收口，**放开必须点名、失踪也必须点名**。
WIRED_KEYS_BASELINE_20261008: frozenset[str] = frozenset(
    {
        "ithome", "wallstreetcn", "bbc", "chinanews",  # 2026-10-02 那波已在册
        "nyt", "wsj", "ft", "time", "newsweek", "asahi", "ukrinform",  # 二批放开
        "google_ai",  # 首批放开（AI 厂家类目第一枚实装）
    }
)

#: ㉓ 诚实缺席的类目 → **缺的那件由谁给**（逐枚写死理由；新类目读空却没登记在此＝红）。
#: 🔴 「类目为空」不是「门把类目关空」也不是「以后再补」：必须点名缺件与裁定人，
#: 这才是她立的规矩（不接受「在册留脏」当收口）。
HONEST_EMPTY_CATEGORIES_20261008: dict[str, str] = {
    "politics": (
        "新华社/人民日报＝frozen_stale（端点通、条目冻在 2022-12-14 / 2025-06-05），"
        "央视新闻＝structural_absent（四形全无 feed）⇒ 新鲜度门阈值与第五形取数口都由她给"
    ),
    "ai_content": (
        "橘鸦/黑鸦两枚 B 站空间号 admitted=False（2026-10-02 UGC 禁册裁定），落点＝订阅链"
        "（bilibili_adapter 的 mid→动态腿）不走快报；禁册一字不摘，要进快报得她先裁禁册冲突"
    ),
}

#: ⑮ 「哪儿测的」合法标记（＝取数出口，不是「测过了」三个字）。
_PROBE_LOCUS_MARKERS: tuple[str, ...] = ("本机", "直连", "产线", "代理", "出口")


def _tier_selfproof_violations(sources: Iterable[NewsSource]) -> list[str]:
    """⑮ 现算尺：接线档位的三件证据（日期／测字／出口标记）缺一即红。"""
    problems: list[str] = []
    for source in sources:
        if source.reachability not in _WIREABLE_REACH:
            continue
        probe = source.probe or ""
        if not re.search(r"\d{4}-\d{2}-\d{2}", probe):
            problems.append(f"{source.key}: 档位 {source.reachability} 探针没有日期")
        if "测" not in probe:
            problems.append(f"{source.key}: 档位 {source.reachability} 探针没写「测」")
        if not any(marker in probe for marker in _PROBE_LOCUS_MARKERS):
            problems.append(
                f"{source.key}: 档位 {source.reachability} 探针没写「哪儿测的」"
                f"（缺出口标记 {'/'.join(_PROBE_LOCUS_MARKERS)} 之一）＝档位自证"
            )
    return problems


def _fold_idempotency_problems(items: list[nf.NewsItem]) -> list[str]:
    """⑯ 现算尺：折叠幂等（折两次逐字相同）＋ 条数＝去重后的题数（防并成一件）。"""
    once = nf.fold_same_topic(items)
    twice = nf.fold_same_topic(once)
    shape = (
        lambda rows: [
            (row.title, row.url, row.source, row.category, row.summary, row.sources)
            for row in rows
        ]
    )
    problems: list[str] = []
    if shape(once) != shape(twice):
        problems.append(
            f"折叠不幂等：一折 {len(once)} 条、二折 {len(twice)} 条，逐字比对已变"
        )
    topic_keys: set[str] = set()
    keyless = 0
    for item in items:
        topic_key = nf.news_topic_key(item.title)
        if not topic_key:
            keyless += 1
        else:
            topic_keys.add(topic_key)
    expected = len(topic_keys) + keyless
    if len(once) != expected:
        problems.append(
            f"折叠条数 ≠ 题数：{len(once)} 条 vs 期望 {expected} 题"
            "（少了＝把两件事并成一件；多了＝同题没折上）"
        )
    # 出处守恒：每条的 sources 必须恰等于「该题在输入里出现过的源」（按到达序、去重；
    # 输入自带折叠出处时也要并进来——否则二折的合法出处会被这把尺当成漂移）。
    outlets_by_key: dict[str, list[str]] = {}
    for item in items:
        topic_key = nf.news_topic_key(item.title)
        if not topic_key:
            continue
        bucket = outlets_by_key.setdefault(topic_key, [])
        for outlet in tuple(item.sources) or ((item.source,) if item.source else ()):
            if outlet and outlet not in bucket:
                bucket.append(outlet)
    for row in once:
        topic_key = nf.news_topic_key(row.title)
        if not topic_key:
            continue
        expected_outlets = tuple(outlets_by_key.get(topic_key, ()))
        actual = tuple(row.sources or ((row.source,) if row.source else ()))
        if actual != expected_outlets:
            problems.append(
                f"{row.title}: 出处列表漂了——折叠给 {actual}，输入里的源是 {expected_outlets}"
            )
    return problems


def _w2_registration_violations(sources: Iterable[NewsSource]) -> list[str]:
    """⑰ 现算尺：二批清单逐枚在册＋同一实体只一行＋二批行必带实测读数。"""
    rows = list(sources)
    if not rows:
        return ["源注册表为空＝二批覆盖门空转（反真空：空输入必须红）"]
    by_key = {row.key: row for row in rows}
    problems: list[str] = []
    for label, key in HER_RAW_ITEMS_20261008_W2:
        if key not in by_key:
            problems.append(f"二批清单点名的「{label}」在名册查无行 key＝{key}")
    mapped = {key for _label, key in HER_RAW_ITEMS_20261008_W2}
    if len(HER_RAW_ITEMS_20261008_W2) != 33 or len(mapped) != 29:
        problems.append(
            f"二批去重留痕形不符：原话 {len(HER_RAW_ITEMS_20261008_W2)} 项应映射到 "
            f"{len(mapped)} 枚实体（判据写死 33→29，改清单要同批改这条）"
        )
    seen_media: dict[str, str] = {}
    for row in rows:
        if row.media in seen_media:
            problems.append(
                f"{row.media}: 两行抢一个登记名（{seen_media[row.media]} 与 {row.key}）"
                "＝同一媒体实体被列了两次，去重没做"
            )
        seen_media[row.media] = row.key
    for key in sorted(HER_LIST_KEYS_20261008_W2):
        row = by_key.get(key)
        if row is None:
            continue
        probe = row.probe or ""
        if not re.search(r"\d{4}-\d{2}-\d{2}", probe) or "测" not in probe:
            problems.append(f"{key}: 二批行没有『日期＋实测』探针＝这批没跑过却说在册")
        if not any(marker in probe for marker in _PROBE_LOCUS_MARKERS):
            problems.append(f"{key}: 二批行探针没写「哪儿测的」")
        if "字节" not in probe and not re.search(r"(HTTP \d{3}|40[34]|URLError|Invalid url)", probe):
            problems.append(
                f"{key}: 二批行探针既无体积读数也无状态码/错误名＝没留下可读的实测证据"
            )
        if _row_should_be_wired(row) and key not in W2_WIRED_BASELINE_20261008:
            problems.append(
                f"{key}: 二批行真被抓取却没登记在放开账（W2_WIRED_BASELINE_20261008）里＝静默放开"
            )
        if key in W2_WIRED_BASELINE_20261008 and not _row_should_be_wired(row):
            problems.append(f"{key}: 登记为已放开却读不出源＝二批账与产线漂移")
        if (
            row.reachability in _WIREABLE_REACH
            and row.endpoint
            and row.category
            and not row.wire_block.strip()
            and not _row_should_be_wired(row)
        ):
            problems.append(f"{key}: 二批行档位可接、无否决却没接线＝在册静默失踪")
    return problems


def _wired_w2_keys(sources: Iterable[NewsSource]) -> set[str]:
    """⑰ 现算：二批的源此刻有几枚真被抓取（名册派生的抓取列表，不是宣称）。"""
    wired_endpoints = {url for url, _media, _category in nf._FEEDS}
    return {
        source.key
        for source in sources
        if source.key in HER_LIST_KEYS_20261008_W2 and source.endpoint in wired_endpoints
    }


# ---------------------------------------------------------------------------
# ⑮ 新锁一：档位不许自证（＋注毒：摘日期／摘测字／摘出口／清空探针）
# ---------------------------------------------------------------------------


def test_leg18_wired_tiers_cannot_self_prove() -> None:
    assert _tier_selfproof_violations(NEWS_SOURCES) == [], _tier_selfproof_violations(NEWS_SOURCES)
    wired = [row for row in NEWS_SOURCES if row.reachability in _WIREABLE_REACH]
    assert wired, "抓取列表里没有接线行＝本锁空转（前提：名册派生至少一枚 wired）"


def test_leg18b_poison_probe_strip_turns_red() -> None:
    """注毒：真接线行逐件摘掉证据（日期／测字／出口），尺每摘一次必咬一次。"""
    from dataclasses import replace

    live = next(row for row in NEWS_SOURCES if row.reachability == nf.REACH_WIRED_LIVE)
    assert _tier_selfproof_violations([live]) == []
    stripped = (
        replace(live, probe="本机直连实测可达，条目当日"),  # 摘日期
        replace(live, probe="2026-10-08 本机 200、38 条、1.0s"),  # 摘「测」
        replace(live, probe="2026-10-08 实测 200、38 条、1.0s、当日"),  # 摘「哪儿测的」
        replace(live, probe=""),  # 全摘
    )
    bites = [len(_tier_selfproof_violations([poisoned])) for poisoned in stripped]
    assert all(count > 0 for count in bites), f"摘证据没被咬：{bites}"
    # 反向不误伤：非接线档位（shape_ready/pending_reverify/…）不归这把尺管。
    shape = next(row for row in NEWS_SOURCES if row.reachability == nf.REACH_SHAPE_READY)
    assert _tier_selfproof_violations([shape]) == []


# ---------------------------------------------------------------------------
# ⑯ 新锁二：去重折叠幂等（＋注毒两发：吞条目／不幂等）
# ---------------------------------------------------------------------------

_W2_FOLD_INPUT: tuple[nf.NewsItem, ...] = (
    nf.NewsItem(title="两国元首在首尔会晤", url="https://a.com/1", source="纽约时报", category="world"),
    nf.NewsItem(title="  两国元首在首尔会晤 ", url="https://b.com/2", source="华尔街日报", category="world"),
    nf.NewsItem(title="两国元首在首尔会晤", url="https://c.com/3", source="NHK", category="world"),
    nf.NewsItem(title="两国元首在首尔会谈", url="https://d.com/4", source="朝日新闻", category="world"),
    nf.NewsItem(title="央行宣布降息 25 个基点", url="https://e.com/5", source="金融时报", category="finance"),
    nf.NewsItem(title="央行宣布降息25个基点", url="https://f.com/6", source="CGTN", category="world"),
)


def test_leg19_topic_folding_is_idempotent_and_lossless() -> None:
    items = list(_W2_FOLD_INPUT)
    assert _fold_idempotency_problems(items) == [], _fold_idempotency_problems(items)
    folded = nf.fold_same_topic(items)
    # 现算形状：三题（「会晤」三源折一条、「会谈」差一字另算一条、降息两种空白形折一条）。
    assert len(folded) == 3, [row.title for row in folded]
    assert folded[0].sources == ("纽约时报", "华尔街日报", "NHK"), folded[0].sources
    assert folded[-1].sources == ("金融时报", "CGTN"), folded[-1].sources
    assert _fold_idempotency_problems(nf.fold_same_topic(folded)) == []


def test_leg19b_poison_non_idempotent_or_over_folding_turns_red(monkeypatch) -> None:
    """注毒两发：① 二折吞掉一条（不幂等）② 全并成一条（过度折叠）⇒ 尺必咬。"""
    items = list(_W2_FOLD_INPUT)
    assert _fold_idempotency_problems(items) == []
    real_fold = nf.fold_same_topic

    def _drains_once(rows):  # 每次折叠都少一条 ⇒ 一折≠二折
        return real_fold(rows)[:-1] if len(rows) > 2 else real_fold(rows)

    monkeypatch.setattr(nf, "fold_same_topic", _drains_once)
    problems = _fold_idempotency_problems(items)
    assert any("不幂等" in problem or "题数" in problem for problem in problems), problems

    def _merges_everything(rows):  # 把不同题并成一件
        folded = real_fold(rows)
        if len(folded) > 1:
            outlets = []
            for row in folded:
                outlets.extend(row.sources or (row.source,))
            return [folded[0].__class__(**{**vars(folded[0]), "sources": tuple(dict.fromkeys(outlets))})]
        return folded

    monkeypatch.setattr(nf, "fold_same_topic", _merges_everything)
    problems = _fold_idempotency_problems(items)
    assert any("≠ 题数" in problem or "出处列表漂" in problem for problem in problems), problems
    monkeypatch.setattr(nf, "fold_same_topic", real_fold)
    assert _fold_idempotency_problems(items) == []


# ---------------------------------------------------------------------------
# ⑰ 二批清单覆盖＋去重留痕＋零接线
# ---------------------------------------------------------------------------


def test_leg20_wave2_list_is_registered_deduped_and_wired_per_baseline() -> None:
    """⑰ 二批清单：覆盖＋去重留痕＋**放开账**（三批起不再是「零接线」）。

    🔴 旧名 ``..._and_unwired`` 与旧判据「二批行档位是可接档＝违反零接线裁定」已被她的
    接线裁定取代；放宽同批这把尺变严：放开的七枚**逐枚登记**、档位仍须是
    ``pending_reverify``（不许镀成 wired_live）、且探针必须带「哪儿测的」出口标记。
    """
    assert _w2_registration_violations(NEWS_SOURCES) == [], _w2_registration_violations(NEWS_SOURCES)
    assert _wired_w2_keys(NEWS_SOURCES) == set(W2_WIRED_BASELINE_20261008), (
        f"二批放开账与现算不等：现算 {sorted(_wired_w2_keys(NEWS_SOURCES))}"
        "（多一枚＝静默放开；少一枚＝接线被吞或账没跟上）"
    )
    by_key = {row.key: row for row in NEWS_SOURCES}
    unwired = nf.admitted_unwired_media_names()
    wired = nf.wired_media_names()
    for key in sorted(W2_WIRED_BASELINE_20261008):
        row = by_key[key]
        assert row.media in wired, f"{key}: 登记为已放开却不在实装集合"
        assert row.media not in unwired, f"{key}: 同一枚源既算接线又算未接线＝名册自相矛盾"
        # 🔴 档位轴与接线轴分离：放开接线**不许**把席位出口读数镀成产线实测。
        assert row.reachability == nf.REACH_PENDING_REVERIFY, (
            f"{key}: 档位被改成 {row.reachability}＝产线出口没复跑过却说已接通"
        )
    # 二批点名却拿不到的行：仍须作为「在册未接线」读得出（诚实缺席不许静默失踪）。
    for key in ("tass", "cgtn", "times-uk", "tvb", "yonhap", "kcna", "dpa", "granma", "kyodo"):
        assert by_key[key].media in unwired, f"{key}: 未放开的二批行应作为『在册未接线』读得出"
    # 主域名登记＝接线的机械前置件（门② 咬「档位未登记」）；放开账里每一枚都得有凭据。
    for key in sorted(W2_WIRED_BASELINE_20261008):
        domain = by_key[key].domains[0]
        assert sa.authority_tier(domain) <= sa.TIER_MAJOR_MEDIA, f"{key}: 主域名 {domain} 无准入凭据"
    assert {
        "time.com", "newsweek.com", "asahi.com", "ukrinform.net"
    } <= set(_major_media_hosts()), "三批放开的四枚主域名没登记进 source_authority＝接线凭据缺失"


def test_leg20b_poison_wave2_row_claimed_wired_turns_red() -> None:
    """注毒（三批改写）：二批里**没登记放开**的行被写成可接档⇒ 放开账必咬；
    登记了放开却被产线读不出源⇒ 同样咬；档位镀金⇒ 两处咬。"""
    from dataclasses import replace

    # ① 未登记的二批行（times-uk：structural_absent）被偷偷写成可接档＋落进抓取列表。
    times_uk = next(row for row in NEWS_SOURCES if row.key == "times-uk")
    smuggled = replace(
        times_uk,
        endpoint="https://www.thetimes.co.uk/rss",
        reachability=nf.REACH_PENDING_REVERIFY,
        probe="2026-10-08 本机直连实测 200、20 条、1.0s",
    )
    problems = _w2_registration_violations([smuggled])
    assert any("静默放开" in problem for problem in problems), problems

    # ② 登记了放开却被吞（把 nyt 的端点抹掉＝抓取列表里读不出它）。
    vanished = replace(
        next(row for row in NEWS_SOURCES if row.key == "nyt"),
        endpoint="",
        note="档①。端点留空、不猜 URL（本席注毒）。",
    )
    problems = _w2_registration_violations([vanished])
    assert any("读不出源" in problem for problem in problems), problems

    # ③ 镀档：席位出口读数被写成产线实测，且探针不写取数出口 ⇒ ⑮ 咬。
    nyt = next(row for row in NEWS_SOURCES if row.key == "nyt")
    naked = replace(
        nyt,
        reachability=nf.REACH_WIRED_LIVE,
        probe="2026-10-08 实测 200、18 条、1.0s、当日",
    )
    assert any(
        "哪儿测的" in problem for problem in _tier_selfproof_violations([naked])
    ), _tier_selfproof_violations([naked])
    # ④ 否决标记留白（空话）当「不接线」用 ⇒ ㉑ 咬（详见 test_leg21b）。
    lying = replace(nyt, reachability=nf.REACH_WIRED_LIVE, probe="2026-10-08 本机直连实测 200")
    assert _wired_new_wave_keys([lying]) == set()  # nyt 不属首批 20 枚（两波账分开）
    feeds = (*nf._FEEDS, (lying.endpoint, lying.media, lying.category))
    assert _reachability_violations([lying], feeds) == []  # 接线且证据齐 ⇒ ③ 不咬
    assert any(
        "不可接线却进了抓取列表"
        in problem
        for problem in _reachability_violations(
            [replace(nyt, reachability=nf.REACH_UNVERIFIED)], feeds
        )
    )


# ===========================================================================
# 2026-10-08 三批接线波（席 NEWS-WIRE3）：**放宽三把钉尺，同批配三把更严的替代锁**
# -------------------------------------------------------------------------
# 她批准把二批「已实测却零接线」的那批源接进抓取清单，硬约束＝禁止高延迟。宿主件
# ``tests/test_news.py`` 的逐枚 URL 钉尺与本册腿 ⑯ 的空集钉尺随之改成派生式（那两件的
# 改写与延迟墙钟实测都在宿主件里）。本段是**替代锁**，一把比原尺严：
#   ㉑ 派生完备性＝「新行没登记档位即红 ∧ 可接档无否决却没接线即红 ∧ 否决留白即红 ∧
#      抓取列表里每枚都必须五件齐＋证据齐（日期／测字／取数出口）」；
#   ㉒ 延迟预算＝「出卡路径等待批不得超过共享池宽度（读真身、抄字面量即红）∧ 派发必须
#      完整（既不等也不补投＝静默丢投递）∧ 预算模型只准等一波 ∧ 反真空」；
#   ㉓ 类目空态＝「读空的类目必须逐枚登记缺哪件与由谁裁；登记了却读得出源＝漂移也红」。
# 注毒一律只换**被检对象**（合成名册/合成派发），尺本身复用同一把。
# ===========================================================================

#: ㉑ 否决标记的「缺哪件」自述里至少命中一枚（空话/留白即红，拦「以后再说」式否决）。
_BLOCK_PIECE_MARKERS: tuple[str, ...] = ("缺", "未登记", "待她", "由她", "她裁", "请她")
_BLOCK_MIN_CHARS = 20


def _major_media_hosts() -> frozenset[str]:
    """现算 source_authority 的主流媒体档域名（与 ``_authority_aggregator_hosts`` 同规）。"""
    from plugins.bot_unified_runtime.domains.core.search import source_authority as mod

    return frozenset(mod._MAJOR_MEDIA)


def _derivation_completeness_violations(
    sources: Iterable[NewsSource], feeds: Iterable[tuple[str, str, str]]
) -> list[str]:
    """㉑ 现算尺：名册 ↔ 抓取列表 双向逐枚相等 ∧ 接线证据齐 ∧ 否决必须写明缺哪件。"""
    rows = list(sources)
    feed_rows = list(feeds)
    problems: list[str] = []
    if not rows:
        return ["源注册表为空＝派生完备性判据空转（反真空：空输入必须红）"]
    if not feed_rows:
        return ["抓取列表为空＝派生完备性判据空转（反真空：读不到实装源别当通过）"]
    wired_endpoints = {url for url, _media, _category in feed_rows}
    expected = {source.endpoint for source in rows if _row_should_be_wired(source)}
    for url in sorted(wired_endpoints - expected):
        problems.append(f"{url}: 在抓取列表却推不出「该接线」＝第二真身或档位/否决没登记")
    for url in sorted(expected - wired_endpoints):
        problems.append(f"{url}: 名册判「该接线」却不在抓取列表＝派生漂移（静默失踪）")
    for source in rows:
        if source.reachability not in nf.REACHABILITY_TIERS:
            problems.append(
                f"{source.key}: 可达性档位 {source.reachability!r} 没登记进 REACHABILITY_TIERS"
                "＝新行没档位（既接不了线也没人知道它是什么）"
            )
        if not source.admitted:
            continue
        if source.endpoint in wired_endpoints:
            if not source.probe.strip():
                problems.append(f"{source.key}: 已接线却无探针")
            elif not any(marker in source.probe for marker in _PROBE_LOCUS_MARKERS):
                problems.append(f"{source.key}: 已接线但探针没写「哪儿测的」＝档位自证")
            if source.wire_block.strip():
                problems.append(f"{source.key}: 带否决标记却仍被抓取＝否决没执法")
        elif source.reachability in _WIREABLE_REACH and source.endpoint and source.category:
            block = source.wire_block.strip()
            if not block:
                problems.append(
                    f"{source.key}: 档位可接＋端点＋类目齐却没接线，又没写 wire_block"
                    "＝既不接线也不说为什么（在册留脏不收口）"
                )
            elif len(block) < _BLOCK_MIN_CHARS or not any(
                marker in block for marker in _BLOCK_PIECE_MARKERS
            ):
                problems.append(
                    f"{source.key}: wire_block 没写明缺哪件/由谁裁"
                    f"（须 ≥{_BLOCK_MIN_CHARS} 字且命中 {'/'.join(_BLOCK_PIECE_MARKERS)} 之一）＝空话否决"
                )
    if not [source for source in rows if source.wire_block.strip()]:
        problems.append("全册没有一枚带接线否决标记＝否决腿空转（反真空，前提级）")
    return problems


def _latency_budget_violations(
    feeds_by_category: dict[str, list[tuple[str, str, str]]],
    *,
    budget_seconds: float,
    plan=None,
) -> list[str]:
    """㉒ 现算尺：出卡路径只等一波 ∧ 派发完整 ∧ 天花板没被锯（预算＝调用方给的）。

    ``plan`` 缺省＝产线的 ``nf.split_dispatch``；注毒时传「旧写法（全批 join）」或
    「吞掉补投批」的合成派发，同一把尺必须咬。
    """
    splitter = nf.split_dispatch if plan is None else plan
    problems: list[str] = []
    width = nf.dispatch_wave_width()
    # 波宽的**独立对照**＝进程级共享池的实际容量（不是再读一遍那枚常量：常量被改、
    # 池子却没跟着变的形态，只有从池子本身问才看得见）。
    live_width = max(
        1,
        int(
            getattr(
                get_shared_pool(),
                "_max_workers",
                nf.shared_pool.SHARED_POOL_MAX_WORKERS,
            )
        ),
    )
    if width != live_width:
        problems.append(
            f"波宽 {width} ≠ 共享池实际容量 {live_width}＝宽度与池脱钩（抄字面量或改了常量没改池）"
        )
    if nf.budget_bound_worst_case_seconds(budget_seconds) > budget_seconds:
        problems.append(
            f"新口径最坏墙钟 {nf.budget_bound_worst_case_seconds(budget_seconds)}s > 预算 "
            f"{budget_seconds}s＝把等待预算锯大来掩盖排队（不是压无用功）"
        )
    crossed_waves = 0
    for category, rows in sorted(feeds_by_category.items()):
        if not rows:
            continue
        blocking, detached = splitter(list(rows))
        if len(blocking) > width:
            problems.append(
                f"{category}: 出卡路径等待 {len(blocking)} 枚 > 一波宽度 {width}"
                f"＝最坏 {nf.join_all_worst_case_seconds(len(blocking), timeout_seconds=budget_seconds):.1f}s"
                f" > 预算 {budget_seconds}s（禁止高延迟）"
            )
        if len(blocking) + len(detached) != len(rows):
            problems.append(
                f"{category}: 派发不完整（等 {len(blocking)} + 补投 {len(detached)} ≠ 全量 {len(rows)}）"
                "＝有源既不出卡也不补投＝静默丢投递"
            )
        if nf.join_all_worst_case_seconds(len(rows), timeout_seconds=budget_seconds) > budget_seconds:
            crossed_waves += 1
    if crossed_waves == 0:
        problems.append(
            "反真空：按名册现算没有任何类目会跨两波＝这把延迟尺今日空转（接线账变了要重看判据）"
        )
    return problems


def _empty_category_violations(
    feeds_by_category: dict[str, list[tuple[str, str, str]]],
    sources: Iterable[NewsSource],
    declared: dict[str, str],
) -> list[str]:
    """㉓ 现算尺：读空的类目必须登记「缺哪件＋由谁裁」；登记了却读得出源＝漂移也红。"""
    rows = list(sources)
    problems: list[str] = []
    if not rows:
        return ["源注册表为空＝类目空态判据空转（反真空）"]
    for category, feeds in sorted(feeds_by_category.items()):
        if category == "mix":
            if not feeds:
                problems.append("mix 读空＝实装清单派生断了（综合类目不许空）")
            continue
        if not feeds:
            reason = declared.get(category)
            if not reason:
                problems.append(
                    f"{category}: 类目为空却没在基线里登记缺哪件＝静默空态"
                    "（不接受「在册留脏」当收口）"
                )
                continue
            if not any(marker in reason for marker in ("她", "待裁", "请她", "由她", "待拍")):
                problems.append(f"{category}: 空态登记没写由谁裁＝僵尸类目")
            if not any(source.category == category for source in rows):
                problems.append(f"{category}: 既无实装源也无名册行＝类目无归属（僵尸键）")
    drift = sorted(
        category
        for category, feeds in feeds_by_category.items()
        if category != "mix" and category in declared and feeds
    )
    if drift:
        problems.append(f"登记为空却读得出源：{drift}＝诚实缺席基线与产线漂移（放开要同批点名）")
    if not declared:
        problems.append("诚实缺席登记为空＝这把尺空转（反真空）")
    return problems


# ---------------------------------------------------------------------------
# ㉑ 派生完备性（＋注毒：没档位／可接却失踪／否决留白／否决没执法）
# ---------------------------------------------------------------------------


def test_leg21_derivation_is_complete_and_two_axis() -> None:
    assert _derivation_completeness_violations(NEWS_SOURCES, nf._FEEDS) == [], (
        _derivation_completeness_violations(NEWS_SOURCES, nf._FEEDS)
    )
    # 接线名册基线逐枚相等：放开必须点名，被吞也必须点名。
    wired_endpoints = {url for url, _m, _c in nf._FEEDS}
    wired_keys = {source.key for source in NEWS_SOURCES if source.endpoint in wired_endpoints}
    assert wired_keys == set(WIRED_KEYS_BASELINE_20261008), (
        f"实装 key 与放开账不等：多 {sorted(wired_keys - set(WIRED_KEYS_BASELINE_20261008))}"
        f"／少 {sorted(set(WIRED_KEYS_BASELINE_20261008) - wired_keys)}"
    )
    # 🔴 档位轴与接线轴分离：除历史三枚（产线/旧直连实测过）外，一枚都不许被镀成 wired_live。
    gold_plated = [
        source.key
        for source in NEWS_SOURCES
        if source.key in wired_keys
        and source.reachability == nf.REACH_WIRED_LIVE
        and source.key not in {"ithome", "wallstreetcn", "bbc"}
    ]
    assert gold_plated == [], f"这些行档位被镀成 wired_live 却没有产线出口凭证：{gold_plated}"
    # 否决腿的反真空前提：全册确有带 wire_block 的行，且它们都读得出「缺哪件」。
    blocked = nf.tier_wireable_but_blocked_sources()
    assert blocked, "全册没有一枚带接线否决标记＝否决判据空转"
    for source in blocked:
        assert source.media in nf.admitted_unwired_media_names(), f"{source.key}: 否决了却不算诚实缺席"


def test_leg21b_poison_derivation_gaps_turn_red() -> None:
    """注毒：① 新行没登记档位 ② 可接档无否决却失踪 ③ 否决写空话 ④ 否决没执法 ⇒ ㉑ 逐条咬。"""
    from dataclasses import replace

    base = next(row for row in NEWS_SOURCES if row.key == "nyt")
    feeds = list(nf._FEEDS)

    no_tier = replace(base, reachability="pretty_live")
    problems = _derivation_completeness_violations([no_tier], feeds)
    assert any("没登记进 REACHABILITY_TIERS" in problem for problem in problems), problems

    poisoned_feeds = [row for row in feeds if row[0] != base.endpoint]
    problems = _derivation_completeness_violations([base], poisoned_feeds)
    assert any("派生漂移（静默失踪）" in problem for problem in problems), problems
    assert any("既不接线也不说为什么" in problem for problem in problems), problems

    empty_block = replace(base, wire_block="以后再说")
    problems = _derivation_completeness_violations([empty_block], poisoned_feeds)
    assert any("空话否决" in problem for problem in problems), problems

    blocked_but_fetched = replace(
        base, wire_block="缺她的政策复核：这家按哪一档给、准不准进快报由她裁（注毒）"
    )
    problems = _derivation_completeness_violations([blocked_but_fetched], feeds)
    assert any("否决没执法" in problem for problem in problems), problems

    naked_probe = replace(base, probe="2026-10-08 实测 200、18 条、1.0s")
    problems = _derivation_completeness_violations([naked_probe], feeds)
    assert any("哪儿测的" in problem for problem in problems), problems

    # 反向不误伤：真名册＋真抓取列表复跑同一把尺仍为空（上面 ㉑ 已断言，这里再核一次）。
    assert _derivation_completeness_violations(NEWS_SOURCES, nf._FEEDS) == []


# ---------------------------------------------------------------------------
# ㉒ 延迟预算（＋注毒三发：全批 join／吞掉补投批／波宽脱钩池真身）
# ---------------------------------------------------------------------------


def _production_news_budget_seconds() -> float:
    """生产缺省预算的真身（``config.py``，本席禁写只准读）——不在测试里抄 6.0 当第二真身。"""
    from plugins.bot_unified_runtime.config import Config

    return float(Config.model_fields["bot_news_timeout_seconds"].default)


def test_leg22_latency_budget_never_exceeds_one_wave() -> None:
    """㉒ 结构读数：任一候选类目按生产预算换算，出卡路径最坏只等一波。"""
    budget = _production_news_budget_seconds()
    assert budget > 0.0, "读不到生产预算真身＝这把尺的基准没了"
    feeds_by_category = {category: nf._feeds_for(category) for category in nf.CATEGORY_LABELS}
    assert _latency_budget_violations(feeds_by_category, budget_seconds=budget) == [], (
        _latency_budget_violations(feeds_by_category, budget_seconds=budget)
    )
    crossing = [
        category
        for category, rows in feeds_by_category.items()
        if nf.join_all_worst_case_seconds(len(rows), timeout_seconds=budget) > budget
    ]
    assert crossing, "没有任何类目按旧口径会超预算＝接线账与这把尺都对不上（反真空）"
    assert nf.budget_bound_worst_case_seconds(budget) == budget, "新口径不等于预算本身＝天花板被动过"
    for category in crossing:
        rows = feeds_by_category[category]
        waves, _ = divmod(len(rows) - 1, nf.dispatch_wave_width())
        assert (
            nf.join_all_worst_case_seconds(len(rows), timeout_seconds=budget) == (waves + 1) * budget
        ), f"{category}: 旧口径的波数模型与池宽对不上"
        assert len(nf.split_dispatch(rows)[1]) > 0, f"{category}: 会跨两波却没切出补投批"


def test_leg22b_poison_latency_plans_turn_red() -> None:
    """注毒：① 全批 join ② 波宽外的源不派发 ③ 波宽与池宽脱钩 ⇒ ㉒ 必咬。"""
    from plugins.bot_unified_runtime.domains.core import shared_pool as sp

    budget = _production_news_budget_seconds()
    feeds_by_category = {category: nf._feeds_for(category) for category in nf.CATEGORY_LABELS}

    def _join_everything(rows):  # 退役写法：出卡路径等全部源
        return list(rows), []

    problems = _latency_budget_violations(feeds_by_category, budget_seconds=budget, plan=_join_everything)
    assert any("禁止高延迟" in problem for problem in problems), problems

    def _drops_the_overflow(rows):  # 只等一波、波宽外**不派发**＝丢投递
        return list(rows[: nf.dispatch_wave_width()]), []

    problems = _latency_budget_violations(feeds_by_category, budget_seconds=budget, plan=_drops_the_overflow)
    assert any("派发不完整" in problem for problem in problems), problems

    original = sp.SHARED_POOL_MAX_WORKERS
    sp.SHARED_POOL_MAX_WORKERS = original + 4
    try:
        problems = _latency_budget_violations(feeds_by_category, budget_seconds=budget)
        assert any("共享池实际容量" in problem for problem in problems), (
            f"波宽与池容量脱钩却没被咬＝宽度被字面量焊死了：{problems}"
        )
    finally:
        sp.SHARED_POOL_MAX_WORKERS = original
    # 还原后同一把尺复跑仍为空（注毒不留痕）。
    assert _latency_budget_violations(feeds_by_category, budget_seconds=budget) == []


# ---------------------------------------------------------------------------
# ㉓ 类目空态诚实登记（＋注毒：没登记的空类目／登记却读得出源／没写由谁裁）
# ---------------------------------------------------------------------------


def test_leg23_empty_categories_are_declared_not_dirty() -> None:
    feeds_by_category = {category: nf._feeds_for(category) for category in nf.CATEGORY_LABELS}
    assert _empty_category_violations(
        feeds_by_category, NEWS_SOURCES, HONEST_EMPTY_CATEGORIES_20261008
    ) == [], _empty_category_violations(
        feeds_by_category, NEWS_SOURCES, HONEST_EMPTY_CATEGORIES_20261008
    )
    # 今日实装非空的类目集合（放开/收缩都要在这里点名）。
    assert {category for category, rows in feeds_by_category.items() if rows} == {
        "tech",
        "finance",
        "world",
        "ai_vendor",
        "mix",
    }
    # 诚实缺席的类目必须仍然「有名册行、无实装源」（缺的那件由她给，见登记文本）。
    for category in HONEST_EMPTY_CATEGORIES_20261008:
        assert any(row.category == category for row in NEWS_SOURCES), f"{category} 行都没了"
        assert not feeds_by_category[category], f"{category} 竟读得出源"


def test_leg23b_poison_empty_and_drifting_categories_turn_red() -> None:
    """注毒：① 空类目没登记 ② 登记为空却有源 ③ 登记没写由谁裁 ④ mix 空 ⑤ 僵尸类目。"""
    from dataclasses import replace

    feeds_by_category = {category: nf._feeds_for(category) for category in nf.CATEGORY_LABELS}

    emptied = dict(feeds_by_category)
    emptied["politics"] = []
    problems = _empty_category_violations(emptied, NEWS_SOURCES, {})
    assert any("没在基线里登记" in problem for problem in problems), problems
    assert any("这把尺空转" in problem for problem in problems), problems

    # ② **登记为空却有源**（world 现算仍读得出 8 枚，却被写进诚实缺席基线）⇒ 漂移红。
    drifted = dict(feeds_by_category)
    problems = _empty_category_violations(
        drifted,
        NEWS_SOURCES,
        {"world": "缺她的裁定：新行待她点名", **HONEST_EMPTY_CATEGORIES_20261008},
    )
    assert any("登记为空却读得出源" in problem for problem in problems), problems

    no_who = {**feeds_by_category, "politics": []}
    problems = _empty_category_violations(
        no_who,
        NEWS_SOURCES,
        {**HONEST_EMPTY_CATEGORIES_20261008, "politics": "端点还没找"},
    )
    assert any("没写由谁裁" in problem for problem in problems), problems

    mix_empty = {**feeds_by_category, "mix": []}
    problems = _empty_category_violations(
        mix_empty, NEWS_SOURCES, {"politics": "由她裁新鲜度门", "ai_content": "禁册冲突待她裁"}
    )
    assert any("综合类目不许空" in problem for problem in problems), problems

    orphan_rows = [replace(row, category="world") for row in NEWS_SOURCES if row.key == "nyt"]
    all_empty = {category: [] for category in nf.CATEGORY_LABELS if category != "mix"}
    all_empty["mix"] = list(nf._FEEDS)
    problems = _empty_category_violations(all_empty, orphan_rows, {"ai_vendor": "待她给取数口"})
    assert any("既无实装源也无名册行" in problem for problem in problems), problems

    real = {category: nf._feeds_for(category) for category in nf.CATEGORY_LABELS}
    assert _empty_category_violations(real, NEWS_SOURCES, HONEST_EMPTY_CATEGORIES_20261008) == []


# ==================== 主人逐枚点名的创作者号豁免（2026-10-08 裁定）====================
# 判据来历：她先（2026-10-02）把 bilibili.com 整档写进硬禁册（UP 主投稿＝UGC），后
# （2026-10-08）逐枚点名三枚空间号「可以作为新闻账号使用，有权威性，可以作为 ai 领域
# 的快报」。两裁定在此正面冲突，她的后一条只**点名到账号**，没说过站点解禁——所以
# 豁免只能是按 mid 精确命中的名册。本组锁执法的就是这条边界：
# 🔴 第四枚未点名 mid 混进来必红；写成按 host 放行必红。
_NAMED_MID_URLS = (
    "https://space.bilibili.com/285286947",
    "https://space.bilibili.com/3706929260006322",
    "https://space.bilibili.com/39030790",
)


def test_named_creator_exceptions_admit_exactly_the_pinned_uids() -> None:
    """三枚点名的空间号准入；同站其他任何路径一律仍拒（豁免不是站点解禁）。"""
    for url in _NAMED_MID_URLS:
        assert nf.named_creator_news_exception(url), url
        assert nf.is_admissible_news_url(url) is True, url
        assert nf.is_banned_news_url(url) is False, url

    # 未点名的第四枚 mid：结构上与三枚同类，但没被点过名 ⇒ 必须照旧拒。
    assert nf.is_admissible_news_url("https://space.bilibili.com/999999999") is False
    # 同站别的形态（视频页/首页）也一律拒——豁免只覆盖 `space/<mid>` 这一形。
    for other in (
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://space.bilibili.com/",
        "https://bilibili.com",
    ):
        assert nf.is_admissible_news_url(other) is False, other
    # 名册里躺着 host 形（＝有人把豁免写成整站放行）⇒ 当场红。
    for key in nf.NAMED_CREATOR_NEWS_EXCEPTIONS:
        assert "/" in key, f"豁免键必须是 host/mid 两截，实得 {key!r}＝整站放行"


def test_named_creator_exception_survives_url_shapes() -> None:
    """她粘来的原样地址（带 `?spm_id_from=…`）与尾斜杠写法必须算同一枚。

    归一若只做整串相等，带查询串的那一枚会静默不豁免＝"看着有牙其实咬空"。
    """
    shapes = (
        "https://space.bilibili.com/39030790?spm_id_from=0.0.0.0",
        "space.bilibili.com/39030790/",
        "https://SPACE.bilibili.com/39030790#anchor",
    )
    for url in shapes:
        assert nf.named_creator_news_exception(url), url
        assert nf.is_admissible_news_url(url) is True, url


def test_banned_host_register_is_untouched_by_the_exception() -> None:
    """禁册一字未删：`bilibili.com` 仍在 `BANNED_NEWS_HOSTS` 里（豁免走名册，不走删册）。"""
    assert "bilibili.com" in BANNED_NEWS_HOSTS
    # 名册不得反向变成"从禁册里摘域"的通道：禁册键集与名册键的 host 段互不覆盖。
    # 名册不得反向变成"从禁册里摘域"的通道：豁免键的宿主必须**仍被禁册覆盖**
    # （`space.bilibili.com` 要按末段后缀对上 `bilibili.com`，用真身的比对口，禁另写一套）。
    for key in nf.NAMED_CREATOR_NEWS_EXCEPTIONS:
        host = key.split("/")[0]
        assert any(
            nf._host_matches(host, banned) for banned in BANNED_NEWS_HOSTS
        ), f"豁免键 {key!r} 的宿主域不在禁册覆盖内＝豁免名册被当成加禁/删禁的旁路用"


# ===========================================================================
# ㉔–㉞ 出口守门（``SRC=`` 四值闭集 + P4 一票否决）｜席 S，2026-10-11
# ===========================================================================
# 主人裁定＝高管个人号「**进正文，但只有官方消息才进，个人互动不得进**」。判据草案＝
# 名册席 ``anime-and-wiz-2026-10-11.md`` §三：``进正文 ⇔ P0∧P1∧P2∧P3∧¬P4``，每条必带
# 一枚 ``SRC=``，取值闭集 ``ORG-PRIMARY / EXEC-ON-NAMEROOM / EXEC-PERSONAL / UNVERIFIED``。
# 判据真身住 ``domains/core/search/source_authority.py``（本组腿验**接线**，不在测试里
# 重推一遍判据）；名册数据走 Runtime 侧数据面，源码树里一枚账号都不许硬编。
# 夹具四枚按草案 F1–F4；注毒两发＝摘掉 P4 否决 / 把 SRC 写成自由文本，都必须真红。
# 全部离线：外呼被本件 autouse 夹具拦着，且绝不碰生产名册文件（夹具只喂内存行）。

_NAMEROOM_SUBJECT = "OpenAI"


def _exec_row(**overrides: object) -> sa.AccountRow:
    """一枚**已取一手**的个人号行（绑定行齐、体量相称）；逐字段可覆写。"""
    base: dict[str, object] = {
        "handle": "thsottiaux",
        "platform": "x",
        "kind": sa.ACCOUNT_KIND_PERSON,
        "subject_full_name": _NAMEROOM_SUBJECT,
        "display_name": "Thibault Sottiaux",
        "bio_domain": "openai.com",
        "profile_url": "https://x.com/thsottiaux",
        "post_count": 1800,
        "joined_year": 2025,
        "follower_count": 250000,
        "binding_company": _NAMEROOM_SUBJECT,
        "binding_title": "Head of Codex and ChatGPT",
        "binding_valid_from": "2024-01-01",
        "binding_source": sa.BINDING_SOURCE_BIO,
    }
    base.update(overrides)
    return sa.AccountRow(**base)


def _post(**overrides: object) -> sa.PostSignals:
    base: dict[str, object] = {
        "handle": "thsottiaux",
        "display_name": "Thibault Sottiaux",
        "self_domain": "openai.com",
        "is_root": True,
        "quote_depth": 0,
    }
    base.update(overrides)
    return sa.PostSignals(**base)


def _personal_item(
    title: str, text: str, *, url: str = "https://x.com/thsottiaux/1", **post_kw: object
) -> nf.NewsItem:
    return nf.NewsItem(
        title=title,
        url=url,
        source="@thsottiaux",
        category="ai_vendor",
        post=_post(text=text, **post_kw),
    )


def _org_item(
    title: str, *, url: str = "https://www.ft.com/home", source: str = "金融时报"
) -> nf.NewsItem:
    return nf.NewsItem(title=title, url=url, source=source, category="finance")


def _use_roster(monkeypatch: pytest.MonkeyPatch, *rows: sa.AccountRow) -> None:
    """把名册读数换成夹具行（生产读口 ``load_account_roster`` 是唯一注入点）。"""
    frozen = tuple(rows)
    monkeypatch.setattr(nf, "load_account_roster", lambda *a, **k: frozen)


# ---------------------------------------------------------------------------
# ㉔ 取值闭集 + 门票 + 消毒（判定行加字段必同批补门票与消毒，台账 #67★）
# ---------------------------------------------------------------------------


def test_leg24_src_values_are_a_closed_set_with_shape_gate() -> None:
    assert sa.SRC_LABELS == frozenset(
        {"ORG-PRIMARY", "EXEC-ON-NAMEROOM", "EXEC-PERSONAL", "UNVERIFIED"}
    )
    # 进正文资格只含两枚：EXEC-PERSONAL / UNVERIFIED 永远拿不到正文位。
    assert sa.BODY_SRC_LABELS == frozenset({"ORG-PRIMARY", "EXEC-ON-NAMEROOM"})
    for label in sa.SRC_LABELS:
        assert sa.is_valid_src_field(f"SRC={label}"), label
        assert sa.src_marker(label) == f"SRC={label}", label
    # 闭集外：门票拒、造标回落、正文资格拒（三处同判，不留「像标就算标」的缝）。
    for bogus in ("ORG-BEST-EFFORT", "exec-personal", "", "UNVERIFIED 附注", "随手一写"):
        assert not sa.is_valid_src_field(f"SRC={bogus}"), bogus
        assert sa.src_marker(bogus) == "SRC=UNVERIFIED", bogus
        assert not sa.body_admits_src(bogus), bogus
    # 门票正则不许被空值拼成恒真分支（#67★ 续行 `|` 空分支＝恒真的旧病）。
    with pytest.raises(ValueError):
        sa._build_src_line_re(frozenset({"ORG-PRIMARY", ""}))


def test_leg24b_poison_free_text_src_turns_red() -> None:
    """注毒（形状层面）：把标写成自由文本 ⇒ 闭集/门票/正文资格三处当场不认。"""
    forged = nf.NewsItem(
        title="某厂发布新模型",
        url="https://openai.com/news/1",
        source="GPT（OpenAI）",
        category="ai_vendor",
        src="ORG-PRIMARY-BUT-FREE",
    )
    assert not sa.is_src_label(forged.src)
    assert not sa.body_admits_src(forged.src)
    line = nf.format_news_brief([forged], "AI 厂家")
    assert "SRC=ORG-PRIMARY-BUT-FREE" not in line, line
    assert "SRC=UNVERIFIED" in line, line
    # 没过门/门判不合格的条目一律不进正文（fail-closed，空标也不当成 ORG）。
    assert nf._keep_body_only([forged]) == []
    assert nf._keep_body_only([forged.__class__(**{**forged.__dict__, "src": ""})]) == []


def test_leg24c_outbound_sanitizer_clamps_any_src_token() -> None:
    """消毒接线：出站咽喉（``redact_local_secrets``）只认闭集，伪造一枚即涂掉。"""
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )

    smuggled = "1. 某厂发布新模型（某社） SRC=I-DECIDE-IT"
    out = redact_local_secrets(smuggled)
    assert "SRC=UNVERIFIED" in out, out
    assert "SRC=I-DECIDE-IT" not in out, out
    # 闭集值幂等（原样放回，二次调用逐字不变）。
    honest = "1. 标题（新华社） SRC=ORG-PRIMARY"
    once = redact_local_secrets(honest)
    assert once == redact_local_secrets(once) == honest, once
    # 哨兵登记：只含 ``SRC=`` 的文本也必须走慢路径（快路径漏判＝消毒形同虚设）。
    assert redact_local_secrets("前缀 SRC=NOT-A-LABEL 后缀").endswith("SRC=UNVERIFIED 后缀")


# ---------------------------------------------------------------------------
# ㉕ F1 双面样本：官方公告形进正文、个人互动形一票否决
# ---------------------------------------------------------------------------


def test_leg25_f1_two_sided_sample_only_official_form_enters_body(monkeypatch) -> None:
    _use_roster(monkeypatch, _exec_row())
    official = _personal_item(
        "GPT-5.1 is now available officially",
        "Announcing GPT-5.1 now available officially",
        link_urls=("https://openai.com/news/gpt-5-1",),
    )
    banter = _personal_item("lol", "lol \U0001F602\U0001F602", url="https://x.com/thsottiaux/2")
    speculation = _personal_item(
        "关于下周放量的闲聊",
        "我觉得下周大概会放开 4o 的额度，hopefully soon 吧",
        url="https://x.com/thsottiaux/3",
    )
    mixed = _personal_item(
        "Sora 发布公告（同条里夹了一句回复）",
        "Announcing Sora now available officially\n回复 @devfriend：哈哈",
        url="https://x.com/thsottiaux/4",
        link_urls=("https://openai.com/news/sora",),
    )
    kept = nf.gate_news_items([official, banter, speculation, mixed])
    # 门里：玩梗与推测闲聊判不出锚 ⇒ 丢（UNVERIFIED）；夹了回复段的公告 ⇒ EXEC-PERSONAL。
    assert [(item.title, item.src) for item in kept] == [
        (official.title, sa.SRC_EXEC_ON_NAMEROOM),
        (mixed.title, sa.SRC_EXEC_PERSONAL),
    ], [(item.title, item.src) for item in kept]
    # 正文里：🔴 只有官方公告形那一段进，夹个人互动段的整条不进（一票否决）。
    body = nf._fold_to_body(kept)
    assert [item.title for item in body] == [official.title], [item.title for item in body]
    assert mixed.title not in nf.format_news_brief(body, "AI 厂家")
    # 进正文那一枚：署名两件套上屏，句子仍是原句（没被改写成公司主语）。
    line = nf.format_news_brief(kept, "AI 厂家")
    assert official.title in line, line
    assert sa.build_exec_signature(_exec_row()) in line, line
    assert "SRC=EXEC-ON-NAMEROOM" in line, line
    assert sa.is_exec_signature(kept[0].source), kept[0].source


def test_leg25b_p4_veto_is_the_only_thing_between_banter_and_body(monkeypatch) -> None:
    """注毒（行为层面）：摘掉 P4 否决 ⇒ 玩梗条立刻拿到正文位 ⇒ 上一把尺必然咬。"""
    row = _exec_row()
    # 拿一枚**有官方锚**、同条里又夹了个人互动段的样本：P4 在场判不进正文，摘掉就翻。
    banter = _personal_item(
        "GPT-5.1 公告夹一句回复",
        "Announcing GPT-5.1 now available officially\n回复 @devfriend：哈哈",
        link_urls=("https://openai.com/news/gpt-5-1",),
    )
    real = sa.p4_personal_interaction_hits
    monkeypatch.setattr(sa, "p4_personal_interaction_hits", lambda *a, **k: ())
    try:
        poisoned = sa.judge_account_src(
            row, banter.post, subject_admitted=nf.is_admissible_news_url
        )
    finally:
        monkeypatch.setattr(sa, "p4_personal_interaction_hits", real)
    assert poisoned == sa.SRC_EXEC_ON_NAMEROOM, "摘掉 P4 后仍拒＝那把尺是空转的假绿"
    # 真判据在场时同一枚只拿到 EXEC-PERSONAL（P3 命中、P4 一票否决），正文资格为假。
    real_label = sa.judge_account_src(
        row, banter.post, subject_admitted=nf.is_admissible_news_url
    )
    assert real_label == sa.SRC_EXEC_PERSONAL, real_label
    assert not sa.body_admits_src(real_label), real_label


def test_leg25c_quote_depth_and_reply_chain_are_personal_interaction(monkeypatch) -> None:
    """同一条里公告形与个人互动形**各一段** ⇒ 整条不进正文（P4 优先于 P3，一票否决）。"""
    _use_roster(monkeypatch, _exec_row())
    deep_quote = _personal_item(
        "转引三段外的公告",
        "Announcing GPT-5.1 now available officially",
        link_urls=("https://openai.com/news/gpt-5-1",),
        quote_depth=2,
        quote_target_handle="someoneelse",
    )
    reply = _personal_item(
        "回一句",
        "Announcing GPT-5.1 now available officially",
        link_urls=("https://openai.com/news/gpt-5-1",),
        is_reply=True,
        in_reply_to_handle="devfriend",
    )
    mixed = _personal_item(
        "公告夹一句闲聊",
        "Announcing GPT-5.1 now available officially\n大概下周全量",
        link_urls=("https://openai.com/news/gpt-5-1",),
    )
    kept = nf.gate_news_items([deep_quote, reply, mixed])
    # 三枚都拿过标（P3 命中、P4 否决 ⇒ EXEC-PERSONAL），🔴 但没有一枚进得了正文。
    assert [item.src for item in kept] == [sa.SRC_EXEC_PERSONAL] * 3, [
        (item.title, item.src) for item in kept
    ]
    assert nf._keep_body_only(nf.fold_same_topic(kept)) == []
    assert nf._keep_body_only(kept) == []


# ---------------------------------------------------------------------------
# ㉖ F2 名录绑定黄金模板：绑定行只靠机构社媒名录就该成立
# ---------------------------------------------------------------------------


def test_leg26_f2_nameroom_binding_alone_satisfies_p1() -> None:
    """NASA 那一形：``OFFICE`` + ``binding_source=nameroom`` ⇒ P1 成立（不问 bio 自述）。"""
    office = _exec_row(
        handle="nasaadmin",
        kind=sa.ACCOUNT_KIND_OFFICE,
        subject_full_name="美国国家航空航天局",
        display_name="Jared Isaacman",
        bio_domain="nasa.gov",
        profile_url="https://x.com/nasaadmin",
        binding_company="美国国家航空航天局",
        binding_title="Administrator",
        binding_source=sa.BINDING_SOURCE_NAMEROOM,
    )
    assert sa.p1_binding_holds(office) is True
    post = _post(
        handle="nasaadmin",
        display_name="Jared Isaacman",
        self_domain="nasa.gov",
        text="Announcing the Artemis II crew now available officially",
        link_urls=("https://www.nasa.gov/news-release/artemis2",),
    )
    assert (
        sa.judge_account_src(office, post, subject_admitted=lambda v: "nasa.gov" in v)
        == sa.SRC_EXEC_ON_NAMEROOM
    )
    # 名录之外的绑定来源（第三方数据库/维基一类）永不构成绑定行。
    assert sa.p1_binding_holds(_exec_row(binding_source="wikipedia")) is False
    # 职位过期＝整条不成立（D1：离职/换岗 ⇒ 转「只作关注」＝拿不到正文位）。
    assert sa.p1_binding_holds(_exec_row(binding_valid_to="2025-01-01")) is False
    # 生效期还没到 / 认不了的写法 ⇒ 同样不成立（fail-closed 不认「大概有效」）。
    assert sa.p1_binding_holds(_exec_row(binding_valid_from="2999-01-01")) is False
    assert sa.p1_binding_holds(_exec_row(binding_valid_from="去年三月")) is False


def test_leg26b_production_subject_register_is_the_news_roster(monkeypatch) -> None:
    """接线读数：产线那一路的「主体在册」＝快报名册准入（``is_admissible_news_url``）。

    NASA 不在快报名册里 ⇒ 同形个人号在生产上判 ``UNVERIFIED`` 丢弃——个人号不许把
    快报取源带进没登记的主体（与「填错主体＝长期从错的嘴里取消息」同一风险面）。
    """
    office = _exec_row(
        handle="nasaadmin",
        kind=sa.ACCOUNT_KIND_OFFICE,
        subject_full_name="美国国家航空航天局",
        display_name="Jared Isaacman",
        bio_domain="nasa.gov",
        profile_url="https://x.com/nasaadmin",
        binding_company="美国国家航空航天局",
        binding_title="Administrator",
        binding_source=sa.BINDING_SOURCE_NAMEROOM,
    )
    _use_roster(monkeypatch, office)
    item = nf.NewsItem(
        title="Artemis II crew announced now available officially",
        url="https://x.com/nasaadmin/9",
        source="@nasaadmin",
        category="world",
        post=_post(
            handle="nasaadmin",
            display_name="Jared Isaacman",
            self_domain="nasa.gov",
            text="Announcing the Artemis II crew now available officially",
            link_urls=("https://www.nasa.gov/news-release/artemis2",),
        ),
    )
    assert nf.src_label_for_item(item) == sa.SRC_UNVERIFIED


# ---------------------------------------------------------------------------
# ㉗ F3 零发帖冒名位：P0 必须挡住它（挡不住＝整套口径作废）
# ---------------------------------------------------------------------------

_GHOST_ROW = _exec_row(
    handle="WutheringWaves",
    display_name="Waves MOD",
    subject_full_name="库洛游戏",
    binding_company="库洛游戏",
    bio_domain="kurogames.com",
    profile_url="https://x.com/WutheringWaves",
    post_count=0,
    joined_year=2022,
    follower_count=772,
    verified_badge=True,
)


def test_leg27_f3_zero_post_impersonation_is_blocked_by_p0() -> None:
    assert sa.p0_attribution_holds(_GHOST_ROW, subject_admitted=lambda _v: True) is False
    # 🔴 认证标永久不作证据（D3）：翻 True/翻 False 判据读数逐字相同。
    no_badge = sa.AccountRow(**{**_GHOST_ROW.__dict__, "verified_badge": False})
    assert sa.p0_attribution_holds(no_badge, subject_admitted=lambda _v: True) is False
    assert (
        sa.judge_account_src(
            _GHOST_ROW,
            _post(text="Announcing kurogame v2.0 now available officially"),
            subject_admitted=lambda _v: True,
        )
        == sa.SRC_UNVERIFIED
    )
    # 三件缺任何一件都不成立（主体全名／自家域名／体量），补上认证标照样缺。
    for missing in ("subject_full_name", "bio_domain"):
        assert (
            sa.p0_attribution_holds(
                sa.AccountRow(**{**_GHOST_ROW.__dict__, missing: ""}),
                subject_admitted=lambda _v: True,
            )
            is False
        ), missing
    assert (
        sa.p0_attribution_holds(
            sa.AccountRow(**{**_GHOST_ROW.__dict__, "post_count": sa.P0_MIN_POST_COUNT}),
            subject_admitted=lambda _v: True,
        )
        is True
    )


def test_leg27b_zero_post_item_never_reaches_the_line(monkeypatch) -> None:
    _use_roster(monkeypatch, _GHOST_ROW)
    before = nf.unverified_drop_count()
    item = _personal_item(
        "鸣潮新版本公告",
        "Announcing Wuthering Waves 3.1 now available officially",
        url="https://x.com/WutheringWaves/1",
        handle="WutheringWaves",
        display_name="Waves MOD",
        self_domain="kurogames.com",
        link_urls=("https://kurogames.com/news/3-1",),
    )
    assert nf.gate_news_items([item]) == []
    assert nf.unverified_drop_count() - before == 1


# ---------------------------------------------------------------------------
# ㉘ F4 一手未取的号：判不出＝丢弃（并计入未核实）
# ---------------------------------------------------------------------------


def test_leg28_f4_unregistered_handle_is_dropped(monkeypatch) -> None:
    """名册里没有这枚号（一手未取）⇒ 个人号路判 ``UNVERIFIED`` ⇒ 丢，不留正文位。"""
    _use_roster(monkeypatch)  # 空名册
    claimed = _personal_item(
        "黄仁勋首帖联署公开信",
        "Announcing a joint letter open letter now available officially",
        url="https://x.com/jensenhuang/1",
        handle="jensenhuang",
        display_name="Jensen Huang",
        link_urls=("https://nvidia.com/news/joint-letter",),
    )
    before = nf.unverified_drop_count()
    assert nf.gate_news_items([claimed]) == []
    assert nf.unverified_drop_count() - before == 1
    # 名册缺席（默认关）：带帖形的个人条一条都进不了正文，连标都拿不到。
    assert nf.src_label_for_item(claimed) == sa.SRC_UNVERIFIED


def test_leg28b_roster_is_data_not_source_code() -> None:
    """名册数据不落源码：落点在数据面（``data/...`` 经唯一路径件重映射），源码树零账号。"""
    assert nf.ACCOUNT_ROSTER_DATA_PATH.startswith("data/")
    assert not (PROJECT_ROOT / nf.ACCOUNT_ROSTER_DATA_PATH).exists()
    corpus = (
        PROJECT_ROOT / "plugins/bot_unified_runtime/domains/core/search/source_authority.py"
    ).read_text(encoding="utf-8") + (
        PROJECT_ROOT / "plugins/bot_unified_runtime/domains/subscribe/feeds/news_feeds.py"
    ).read_text(encoding="utf-8")
    for handle in ("thsottiaux", "nasaadmin", "WutheringWaves", "jensenhuang", "SatyaNadella"):
        assert handle not in corpus, f"句柄 {handle} 被硬编进源码＝名册数据落了 .py"


def test_leg28c_roster_reader_is_fail_closed_on_any_bad_shape(tmp_path) -> None:
    """名册读口的 fail-closed：缺席/空文件/坏 JSON/根节点错型 ⇒ 一律空表，不抛。"""
    missing = tmp_path / "nope.json"
    assert nf.load_account_roster(missing) == ()
    empty = tmp_path / "empty.json"
    empty.write_text("   ", encoding="utf-8")
    assert nf.load_account_roster(empty) == ()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert nf.load_account_roster(broken) == ()
    wrong_root = tmp_path / "root.json"
    wrong_root.write_text("[1, 2]", encoding="utf-8")
    assert nf.load_account_roster(wrong_root) == ()
    wrong_accounts = tmp_path / "accounts.json"
    wrong_accounts.write_text('{"accounts": {"handle": "x"}}', encoding="utf-8")
    assert nf.load_account_roster(wrong_accounts) == ()
    no_handle = tmp_path / "nohandle.json"
    no_handle.write_text('{"accounts": [{"platform": "x"}]}', encoding="utf-8")
    assert nf.load_account_roster(no_handle) == ()
    good = tmp_path / "good.json"
    good.write_text(
        '{"accounts": [{"handle": "DemoHandle", "platform": "x", "kind": "person",'
        ' "subject_full_name": "OpenAI", "display_name": "D", "bio_domain": "openai.com",'
        ' "post_count": 30, "joined_year": 2023, "follower_count": 10,'
        ' "binding_company": "OpenAI", "binding_title": "Eng",'
        ' "binding_valid_from": "2024-01-01", "binding_source": "nameroom"}]}',
        encoding="utf-8",
    )
    rows = nf.load_account_roster(good)
    assert len(rows) == 1 and rows[0].slot == "x/demohandle", rows


# ---------------------------------------------------------------------------
# ㉙ 正文不变量：每条带闭集标、句子逐字不改、个人条降佐证不占条目数
# ---------------------------------------------------------------------------


def test_leg29_every_body_item_carries_a_closed_label_and_title_is_untouched(
    monkeypatch,
) -> None:
    _use_roster(monkeypatch, _exec_row())
    official = _personal_item(
        "GPT-5.1 is now available officially",
        "Announcing GPT-5.1 now available officially",
        link_urls=("https://openai.com/news/gpt-5-1",),
    )
    org = _org_item("央行宣布降息 25 个基点")
    kept = nf.gate_news_items([official, org])
    assert all(sa.is_src_label(item.src) for item in kept), [
        (item.title, item.src) for item in kept
    ]
    # 🔴 禁改主语：门只动 ``src`` 与出处署名，正文句子（标题/摘要）逐字不变。
    by_title = {item.title: item for item in kept}
    assert by_title[official.title].title == official.title
    assert by_title[official.title].summary == ""
    assert by_title[org.title].src == sa.SRC_ORG_PRIMARY
    assert by_title[org.title].source == org.source == "金融时报"
    lines = [line for line in nf.format_news_brief(kept, "综合").splitlines() if line[:2].rstrip(".").isdigit()]
    assert len(lines) == len(kept)
    for line in lines:
        assert sa.is_valid_src_field("SRC=" + line.rsplit(" SRC=", 1)[1]), line


def test_leg30_personal_item_folds_into_corroboration_not_a_body_row(monkeypatch) -> None:
    """ORG 已发同一题 ⇒ 个人条转佐证位、不占条目数（草案 B 的抑制规则）。"""
    _use_roster(monkeypatch, _exec_row())
    shared = "某厂发布新一代推理模型 支持百万上下文"
    org = _org_item(shared)
    personal = _personal_item(
        shared,
        "Announcing 某厂发布新一代推理模型 now available officially\n回复 @x：哈哈",
        link_urls=("https://openai.com/news/reasoning",),
    )
    kept = nf.gate_news_items([org, personal])
    assert [item.src for item in kept] == [sa.SRC_ORG_PRIMARY, sa.SRC_EXEC_PERSONAL], [
        (item.title, item.src) for item in kept
    ]
    body = nf._fold_to_body(kept)
    assert len(body) == 1, [(item.title, item.src) for item in body]
    assert body[0].src == sa.SRC_ORG_PRIMARY
    assert any("个人号佐证" in outlet for outlet in body[0].sources), body[0].sources
    assert "回复" not in body[0].title  # 正文句子没被改写
    # 没有同题正文条时：个人条既不占条目数，也不硬塞进别的条。
    orphan = _personal_item(
        "孤条：无同题正文",
        "Announcing Sora now available officially\n回复 @x：哈哈",
        link_urls=("https://openai.com/news/sora",),
    )
    other = _org_item("另一件事")
    assert nf.src_label_for_item(orphan) == sa.SRC_EXEC_PERSONAL
    body = nf._fold_to_body(nf.gate_news_items([other, orphan]))
    assert [item.src for item in body] == [sa.SRC_ORG_PRIMARY], [
        (item.title, item.src) for item in body
    ]
    assert body[0].title == "另一件事"
    assert all("孤条" not in item.title for item in body), [item.title for item in body]


def test_leg30b_org_row_survives_when_personal_item_arrives_first(monkeypatch) -> None:
    """个人条先到也不许把在册 ORG 条挤掉：同题主位归合格标（题同＝一条信息）。"""
    _use_roster(monkeypatch, _exec_row())
    shared = "某厂开源新模型 权重已发布"
    personal = _personal_item(
        shared,
        "Announcing 某厂开源新模型 now available officially\n回复 @x：嗯",
        link_urls=("https://openai.com/news/open-weights",),
    )
    org = _org_item(shared)
    body = nf._fold_to_body(nf.gate_news_items([personal, org]))
    assert [item.src for item in body] == [sa.SRC_ORG_PRIMARY], [(i.title, i.src) for i in body]
    assert body[0].title == shared, "同题正文条被个人条挤掉了（在册≠已执法的反向形态）"
    assert any("个人号佐证" in outlet for outlet in body[0].sources), body[0].sources
    # 纯个人条（无同题正文）单独成批 ⇒ 正文为空，绝不因为「有内容」就放行。
    assert nf._fold_to_body(nf.gate_news_items([personal])) == []


def test_leg30c_no_second_judgement_outlet_in_the_render_path() -> None:
    """判一次：渲染口与卡面只读 ``item.src``，不再判一遍（防第二通路）。"""
    feeds = (
        PROJECT_ROOT / "plugins/bot_unified_runtime/domains/subscribe/feeds/news_feeds.py"
    ).read_text(encoding="utf-8")
    capability = (
        PROJECT_ROOT / "plugins/bot_unified_runtime/domains/subscribe/capabilities/news.py"
    ).read_text(encoding="utf-8")
    # 定义一处 + 抓取出口调用一处；再多一处＝第二条通路。
    assert len(re.findall(r"(?<!def )gate_news_items\(", feeds)) == 1, "出口守门被接到第二处"
    assert feeds.count("def gate_news_items(") == 1
    assert "judge_account_src" not in capability, "渲染侧自己判了一遍"
    assert "src_label_for_item" not in capability, "渲染侧自己判了一遍"


# ---------------------------------------------------------------------------
# ㉞ 抓取出口贴标：产线（RSS）条目在行上必带一枚合法标
# ---------------------------------------------------------------------------

_SRC_RSS = """<rss version="2.0"><channel><title>贴标夹具</title>
  <item><title>某部发布新一代旗舰芯片</title><link>https://www.ithome.com/1/003/001.htm</link>
    <description>名册内正规源条目，带标上屏。</description></item>
  <item><title>没有链接的条目</title><description>无 URL 时来源取登记名，也要带标。</description></item>
</channel></rss>
"""


def test_leg34_fetched_items_reach_the_line_with_a_valid_marker(monkeypatch) -> None:
    _use_roster(monkeypatch)

    def _fake(url: str, timeout_seconds: float) -> str:
        return _SRC_RSS

    monkeypatch.setattr(nf, "_fetch_feed_text", _fake)
    nf.reset_news_cache()
    items = nf.fetch_headlines("tech", cache_seconds=0.0, max_items=20)
    assert items, "贴标门把类目关空了（台账 #12/leg10 的类目非空语义不许被破坏）"
    assert all(item.src == sa.SRC_ORG_PRIMARY for item in items), [
        (item.title, item.src) for item in items
    ]
    body = nf.format_news_brief(items, "科技")
    numbered = [line for line in body.splitlines() if re.match(r"^\d+\. ", line)]
    assert numbered and all(" SRC=ORG-PRIMARY" in line for line in numbered), body
    assert sa.sanitize_src_markers(body) == body, "产线出来的标必须本来就过消毒（幂等）"


