"""维基知识库检索质量回归锁（S-KB-QUALITY 量尺波，2026-09-26）。

背景：kb_wiki 库的 FTS5 trigram 关键词通道（`knowledge_chunks_fts`，行数以
真库/机器册为准）2026-09-26 刚被接通；本文件把「接通后应有的行为」钉成常驻
回归，全部离线：tmp_path 合成微型语料 + 确定性零向量假嵌入（向量通道恒 0 分
= 嵌入链退化的最坏形态），绝不触碰 ChatBot_Runtime 真库、零网络。

锁死的行为面（与真库量尺结论一一对应，量尺数字在报告
.superpowers/sdd/2026-09-26-goal18-second/logs/S-KB-QUALITY.md）：
①专名在场时词条页排第一（词条置顶 + bm25 融合，泛 3-gram 噪声翻不过去）；
②正文提及能被关键词腿召回（词条名不在标题里也只能靠它——kb-sync 补建
   FTS 这条链路的正当性本体）；
③整条查询无任何词面命中且向量零分时诚实回空（不硬凑答案）；
④search_scored 的 channels 可按腿归因（keyword/entry/vector 三态可判别）；
⑤已知缺陷以 xfail 挂账：纯数字版本号进不了词表，跨游戏同号版本页会顶替
   本游戏页（真库实测「鸣潮2.0版本更新时间」返回别的游戏的 2.0 页）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

# 语料：三条 wiki 式标题页 + 一条无「蓝溪」标题、只在正文提及的杂项页，
# 外加一条跨游戏的「2.0版本」页与一条含大量泛词（是/什么）的干扰页。
_ROWS = [
    (
        "doc-lanxi-1",
        "bilibili_wiki_lanxi",
        "共鸣者蓝溪·B站wiki",
        "蓝溪是韵表内的共鸣者，擅长琴艺，延奏技能为队友提供蓝溪协奏加成。" * 4,
    ),
    (
        "doc-lanxi-2",
        "kurobbs_mc_lanxi",
        "蓝溪·kurobbs_mc",
        "蓝溪，游戏角色，命名为蓝溪，属于黑石舰队后裔。" * 4,
    ),
    (
        "doc-story",
        "bilibili_wiki_story",
        "任务回顾雾峡旧影·B站wiki",
        "雾峡旧影是主线第三章的幕间事件，玩家在此见到蓝溪的兄长。" * 4,
    ),
    (
        "doc-misc-bodyonly",
        "kurobbs_mc_misc",
        "杂项·kurobbs_mc",
        "冷知识汇总：关于蓝溪的延奏技能倍率，社区测试为每秒提升百分之十二。" * 4,
    ),
    (
        "doc-other-game-version",
        "fandom_other",
        "Version 2.0·fandom_other",
        "2.0版本更新公告：新增玩法、地图与系统，上线时间为当年八月。" * 4,
    ),
    (
        "doc-noise-generic",
        "bilibili_wiki_noise",
        "这是什么地方·B站wiki",
        "这是什么地方呢，是谁在说话，是什么声音，还是说只是梦。" * 6,
    ),
]


class _ZeroEmbedder:
    """恒零向量：norm=0 ⇒ 向量通道让路（retrieve 走 ([],0.0) 分支），
    检索结果只由关键词腿与词条腿决定——正是「嵌入链退化」要兜的底。"""

    def embed_texts(self, texts):
        return [[0.0] * 64 for _ in texts]


def _seed_store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    store = SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb-quality.sqlite3",
        embed_provider=_ZeroEmbedder(),
        chunk_chars=800,
        top_k=4,
        signature="test|fake-embedder",
        auto_reset=False,
        fts_auto_rebuild=False,  # 与生产 kb_wiki._build_store 同参
    )
    with store._connect() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO knowledge_chunks "
            "(chunk_id, source_id, title, content, content_hash, vector_json) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            [
                (
                    cid,
                    src,
                    title,
                    content,
                    hashlib.sha1(cid.encode("utf-8")).hexdigest(),
                )
                for cid, src, title, content in _ROWS
            ],
        )
        connection.commit()
    # 微型库：显式 force 建 FTS（模拟 kb-sync 收尾的那一发幂等重建）。
    assert store.ensure_fts_index(force=True) is True
    return store


@pytest.fixture()
def store(tmp_path: Path) -> SqliteVectorKnowledgeStore:
    return _seed_store(tmp_path)


def test_entity_query_puts_entity_page_first(store: SqliteVectorKnowledgeStore) -> None:
    """①专名在场：top1 必须是词条页，泛词干扰页不得登顶。"""
    chunks = store.retrieve("蓝溪是谁")
    assert chunks, "关键词腿接通后专名查询不应为空"
    assert "蓝溪" in chunks[0].title
    assert all("这是什么地方" != c.title for c in chunks[:2])


def test_body_only_mention_is_recalled_by_keyword_leg(
    store: SqliteVectorKnowledgeStore,
) -> None:
    """②正文提及：目标页标题里没有查询词，只能靠 BM25 正文腿召回。"""
    chunks = store.retrieve("蓝溪的延奏技能倍率")
    titles = [c.title for c in chunks]
    assert any("杂项" in t for t in titles), (
        "正文腿接不通 = kb-sync 的 FTS 补建没生效，此为回归红线"
    )


def test_total_miss_returns_empty_not_invented_rows(
    store: SqliteVectorKnowledgeStore,
) -> None:
    """③查无此文 + 向量零分 ⇒ 诚实回空（宁可不答，不硬凑）。"""
    chunks = store.retrieve("qqzzxxww 是谁")
    assert chunks == []


def test_search_scored_channels_are_leg_attributable(
    store: SqliteVectorKnowledgeStore,
) -> None:
    """④三通道排名可判别：正文腿命中的块 keyword 有名次、entry 为空。"""
    scored = store.search_scored("蓝溪的延奏技能倍率", sync_files=False)
    misc = [s for s in scored if "杂项" in s.chunk.title]
    assert misc, "search_scored 与 retrieve 同链，正文腿命中必须可见"
    row = misc[0]
    assert row.channels["keyword"] is not None
    assert row.channels["entry"] is None  # 标题不含「蓝溪」→ 词条腿不该命中
    assert set(row.channels) == {"vector", "keyword", "entry"}


@pytest.mark.xfail(
    strict=False,
    reason=(
        "KQ-VERSION-CROSSTALK：纯数字版本号（如「2.0」）不满足 _ALNUM_RE 的 "
        ">=3 门槛、也不在 CJK 滑窗内，游戏限定词又切不出版本页——真库实测"
        "「鸣潮2.0版本更新时间」top4 全是别的游戏的 2.0 页（跨游戏张冠李戴）。"
        "理想行为=回空或至少不误供他游页；修法见 S-KB-QUALITY 报告 §6 票 KQ-2。"
    ),
)
def test_version_query_does_not_cross_games(store: SqliteVectorKnowledgeStore) -> None:
    """⑤（挂账缺陷）溯光游戏没有任何 2.0 版本页，查询不得返回他游版本页。"""
    chunks = store.retrieve("溯光2.0版本更新时间")
    titles = [c.title for c in chunks]
    assert not any("Version 2.0" in t for t in titles), (
        f"跨游戏顶替：{titles}"
    )


# ---------------------------------------------------------------------------
# ⑥ KQ-7：检索「故障」与「库里没有」必须可判别 —— 降级照旧，但不许零痕迹
# ---------------------------------------------------------------------------

_WIKI_LOGGER = "plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki"


class _BrokenStore:
    """存储层直接抛异常的替身（模拟 disk I/O error / 库被独占）。"""

    def retrieve(self, query_text: str, *, files=None, embed_backlog: bool = False):
        raise OSError("database disk image is malformed")


class _BrokenRetriever:
    available = True

    def retrieve(self, query_text: str) -> list:
        raise RuntimeError("persona leg exploded")


def _wiki_records(caplog) -> list[str]:
    return [
        f"{rec.name}:{rec.getMessage()}"
        for rec in caplog.records
        if rec.name == _WIKI_LOGGER
    ]


def test_store_failure_is_logged_instead_of_becoming_invisible(
    caplog, monkeypatch
) -> None:
    """`KBWikiRetriever.retrieve` 的 except 旧写法一句日志不打。

    那是「检索故障」伪装成「库里没有」的第一现场：返回 [] 与诚实零命中逐字节同形，
    运维只能等用户来报「它说没这个人」才反推。本锁只钉一件事——**必须留痕且降级不破**：
    返回仍是 []（不阻断对话这条语义不许改），但日志里要点名异常类型。
    杀伤力＝摘掉那行 logger.warning 当场红（断言吃的是记录本身，不是返回值）。
    """
    import logging

    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    retriever = kb_wiki.KBWikiRetriever(_BrokenStore())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        assert retriever.retrieve("某个会炸的查询") == []  # 降级语义不破
    lines = _wiki_records(caplog)
    assert any(
        "kb wiki retrieval degraded" in line and "type=OSError" in line
        for line in lines
    ), f"存储层炸了却没有任何留痕：{lines}"
    # 用户内容不进日志：查询正文只以长度形态出现。
    assert not any("某个会炸的查询" in line for line in lines), (
        f"查询正文被写进日志（应只记长度）：{lines}"
    )


def test_merged_leg_failure_names_the_failing_leg(caplog) -> None:
    """合并检索器旧写法只把失败腿换成 []，连「哪一路挂了」都不说。

    两路 owner 不同（人格库 / 维基库）、库文件不同、重建命令不同，只报"合并降级"
    等于让运维去查一条本来好好的腿。同时钉：健康那一路的结果必须照常上桌。
    """
    import logging
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

    class _HealthyRetriever:
        available = True

        def retrieve(self, query_text: str) -> list:
            return [SimpleNamespace(chunk_id="ok-1", title="健康腿")]

    merged = kb_wiki.MergedKnowledgeRetriever(
        [_BrokenRetriever(), _HealthyRetriever()]
    )
    with caplog.at_level(logging.WARNING):
        out = merged.retrieve("任意查询")
    assert [c.chunk_id for c in out] == ["ok-1"], (
        f"一路故障带走了另一路的结果（不该断链）：{out}"
    )
    lines = _wiki_records(caplog)
    assert any(
        "leg=_BrokenRetriever" in line and "type=RuntimeError" in line
        for line in lines
    ), f"故障没被归因到具体那一路：{lines}"
