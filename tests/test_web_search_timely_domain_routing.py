"""检索分域（第 3 项）的回归锁：垂直域判据、按域权威源排序、扩展词不再串域。

三条各对应一种实测塌法：
① 金融/时政被当成 ACG 话题补「萌娘百科」扩展词（实测时效检索 47% 空手而归）；
② 来源优先级只有一张表，任何查询的第一名都让给萌百；
③ 本地已知的二游话题被推到通用新闻源，反而不稳定。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _WEB_SOURCE_PRIORITY,
    _sort_web_hits,
    _source_priority_for,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    TimelyDomain,
    classify_timely_domain,
    is_encyclopedic_domain,
)

_CHAT_PY = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
)


class _Hit:
    """够用的替身：_sort_web_hits 只读 source_domain。"""

    def __init__(self, domain: str) -> None:
        self.source_domain = domain
        self.title = domain

    def __repr__(self) -> str:  # pragma: no cover - 断言失败时好看点
        return f"<Hit {self.source_domain}>"


# --------------------------------------------------------------------------
# ① 分域判据
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("今天美联储加息了吗", TimelyDomain.FINANCE),
        ("美元兑人民币汇率多少", TimelyDomain.FINANCE),
        ("英伟达最新财报营收多少", TimelyDomain.FINANCE),
        ("沪深300指数今天怎么样", TimelyDomain.FINANCE),
        ("国务院出台什么新政策", TimelyDomain.CURRENT_AFFAIRS),
        ("中美关税谈判有什么进展", TimelyDomain.CURRENT_AFFAIRS),
        ("刚刚新闻里说的那场地震几级", TimelyDomain.CURRENT_AFFAIRS),
        ("OpenAI 发布了什么新模型", TimelyDomain.TECH),
        ("华为新款手机芯片是几纳米", TimelyDomain.TECH),
        ("今天有什么头条新闻", TimelyDomain.NEWS),
        ("守岸人是谁", TimelyDomain.ANIME_LORE),
        ("维里奈剧情讲的什么", TimelyDomain.ANIME_LORE),
        ("你好呀", TimelyDomain.GENERAL),
        ("", TimelyDomain.GENERAL),
    ],
)
def test_timely_queries_land_in_the_right_vertical_domain(
    text: str, expected: TimelyDomain
) -> None:
    assert classify_timely_domain(text) == expected.value


def test_local_game_topic_beats_every_timely_signal() -> None:
    """「鸣潮新版本卡池更新了什么」既有时间词又有游戏词：本地域必须先判。

    判错的后果是把自家世界观问题推去问通用新闻站——正是"取数不稳"那一半。
    本地锚点由函数自己查 DOMAIN_TERMS，所以传不传旗标都该得到同一个答案。
    """
    text = "鸣潮新版本卡池更新了什么"
    assert classify_timely_domain(text) == TimelyDomain.ANIME_LORE.value
    assert (
        classify_timely_domain(text, in_local_domain=True)
        == TimelyDomain.ANIME_LORE.value
    )


def test_finance_is_decided_before_the_broader_domains() -> None:
    """三域共用"公司/发布/价格"这类词，越具体的先判，否则被宽域抢走。"""
    assert classify_timely_domain("腾讯公司最新股价和财报") == TimelyDomain.FINANCE.value
    assert is_encyclopedic_domain(TimelyDomain.ANIME_LORE.value) is True
    assert is_encyclopedic_domain(TimelyDomain.FINANCE.value) is False


# --------------------------------------------------------------------------
# ② 按域的权威源
# --------------------------------------------------------------------------


def test_finance_query_no_longer_puts_moegirl_first() -> None:
    """金融题的第一名必须是财经权威源，不再是萌百。

    表外域名同分后按域名字典序 tie-break（"random-blog" < "zh.moegirl"），
    所以这里钉的是"该信的排第一、萌百不再排第一"，不去猜表外两条谁先谁后——
    那个顺序没有语义，钉死只会变成下次改表时的假红。
    """
    hits = [_Hit("zh.moegirl.org.cn"), _Hit("caixin.com"), _Hit("random-blog.example")]
    ordered = _sort_web_hits(hits, TimelyDomain.FINANCE.value)  # type: ignore[arg-type]
    assert ordered[0].source_domain == "caixin.com"
    assert [hit.source_domain for hit in ordered].index("zh.moegirl.org.cn") > 0


def test_anime_query_still_prefers_the_encyclopedia() -> None:
    hits = [_Hit("caixin.com"), _Hit("zh.moegirl.org.cn")]
    ordered = _sort_web_hits(hits, TimelyDomain.ANIME_LORE.value)  # type: ignore[arg-type]
    assert ordered[0].source_domain == "zh.moegirl.org.cn"


def test_no_domain_means_the_old_single_table_byte_for_byte() -> None:
    """未分域（含分域函数没跑到的路径）⇒ 回到既有那张表，不改一个字节。"""
    assert _source_priority_for(None) is _WEB_SOURCE_PRIORITY
    hits = [_Hit("bilibili.com"), _Hit("caixin.com")]
    assert _sort_web_hits(hits)[0].source_domain == "bilibili.com"  # type: ignore[call-arg]


def test_unknown_domain_falls_back_instead_of_crashing() -> None:
    assert _source_priority_for("not-a-real-domain") is _WEB_SOURCE_PRIORITY


def test_timely_tables_cover_the_official_channels() -> None:
    """三张时效表都必须含官方发布口——她要的是"最新、最权威"，不是"最新的小道"。"""
    for domain in (
        TimelyDomain.FINANCE,
        TimelyDomain.CURRENT_AFFAIRS,
        TimelyDomain.NEWS,
    ):
        table = _source_priority_for(domain.value)
        assert table is not _WEB_SOURCE_PRIORITY, f"{domain} 没有专属权威表"
        assert any("gov.cn" in entry for entry in table), f"{domain} 缺官方口径源"
        assert "zh.moegirl.org.cn" not in table, f"{domain} 仍把萌百当权威源"


# --------------------------------------------------------------------------
# ③ 检索扩展词不得串域（结构锁：直接读 chat.py 的源码树）
# --------------------------------------------------------------------------


def _do_web_block_source() -> str:
    tree = ast.parse(_CHAT_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "do_web"
        ):
            return ast.unparse(node)
    raise AssertionError("chat.py 找不到 `if do_web:` 检索块")


@pytest.mark.parametrize(
    "branch_marker",
    ["TimelyDomain.FINANCE.value", "TimelyDomain.CURRENT_AFFAIRS.value"],
)
def test_timely_expansion_branches_do_not_carry_moegirl(branch_marker: str) -> None:
    """金融/时政那条分支里出现「萌娘百科」就是本次改造的倒退。

    锁源码而不是锁输出，是因为扩展词只在真发网络请求时才落地；离线断言取不到，
    而"以后有人顺手加回去"这件事只有结构锁拦得住。
    """
    block = _do_web_block_source()
    start = block.index(branch_marker)
    # 取该分支到下一条 elif 之间的片段。
    tail = block[start:]
    nxt = tail.find("elif")
    fragment = tail if nxt < 0 else tail[:nxt]
    assert "萌娘百科" not in fragment, f"{branch_marker} 分支仍补萌百扩展词"
    assert "萌百" not in fragment


def test_local_lore_branch_still_carries_moegirl() -> None:
    """反向格：ANIME_LORE 那条**必须**还留着萌百——不然就是把另一半改坏了。"""
    block = _do_web_block_source()
    start = block.index("TimelyDomain.ANIME_LORE.value")
    tail = block[start:]
    nxt = tail.find("elif")
    fragment = tail if nxt < 0 else tail[:nxt]
    assert "萌娘百科" in fragment


def test_every_expansion_branch_keeps_the_bare_query_as_backstop() -> None:
    """每条分支都要留一条原样查询：加了限定词反而不如原句时，得有退路。

    `ast.unparse` 会把列表压成一行、末项不带逗号，所以两种写法都要认。
    """
    block = _do_web_block_source()
    backstop = re.compile(r"base_query[,\]]")
    for marker in (
        "TimelyDomain.ANIME_LORE.value",
        "TimelyDomain.FINANCE.value",
        "TimelyDomain.TECH.value",
    ):
        start = block.index(marker)
        tail = block[start:]
        nxt = tail.find("elif")
        fragment = tail if nxt < 0 else tail[:nxt]
        assert backstop.search(fragment), f"{marker} 分支缺原句退路"


def test_domain_is_tagged_for_auditability() -> None:
    """分了域就要留痕，否则"分对了没有"只能靠猜（回执那条今天就是这么瞎的）。"""
    source = _CHAT_PY.read_text(encoding="utf-8")
    assert '"web_domain:{timely_domain}"' in source or "web_domain:" in source
