"""知识库 topic 命名的机器门：命名出事时，最坏情况必须是「不补」而不是「误删」。

背景（2026-09-20 取证）：语料即将从 15 域扩到约 30 主题。doc_id 的形态是
``<topic>/<source>/.../<title>__<id>``，而 ``_id_topic`` **只按 ASCII '/'** 切第一段。
于是两个命名陷阱：

  ① topic 名里含 ASCII '/'（例如把主题命名成 ``Fate/Grand Order``）→ 白名单永远
     匹配不到任何 doc_id → 对账被整域滤空 → **该域静默永不补投**；
  ② topic 名里含 '_' 或 '%' → 若将来用 LIKE 做 topic 过滤而忘了 ESCAPE，
     名字本身会变成通配符。

①②都属本波反复根治的那一族缺陷：「静默成功掩盖实际空手」（prts unknown_source、
检 537 抓 0、moegirl.uk 空成功冻结镜像、providers 死导入）。本文件不新增行为，
而是把**现有降级语义钉成断言**——尤其是「滤空时绝不删数据」这条，因为它决定了
误命名的爆炸半径是「少一批内容」还是「清掉一整域」。
"""
from __future__ import annotations

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    _escape_like,
)
from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
    _RECONCILE_REMOVE_SUSPENDED,
    _id_topic,
    manifest_index,
    reconcile_with_manifest,
)


class _LedgerStore:
    """对账只需要 store.document_ledger()，用鸭子类型喂它，不碰任何真库。"""

    def __init__(self, ledger: dict[str, str]):
        self._ledger = dict(ledger)

    def document_ledger(self) -> dict[str, str]:
        return dict(self._ledger)


def _manifest(entries: dict[str, str], *, documents: int | None = None, **extra):
    manifest = {"entries": entries}
    manifest["documents"] = len(entries) if documents is None else documents
    manifest.update(extra)
    return manifest


# --------------------------------------------------------------- _id_topic

def test_id_topic_splits_on_ascii_slash_only():
    assert _id_topic("鸣潮/bilibili_wiki/角色/卡穆__1") == "鸣潮"
    # 全角冒号是 topic 名的一部分，不得被当成结构分隔符
    assert _id_topic("明日方舟：终末地/skland_endfield/干员__2") == "明日方舟：终末地"


def test_id_topic_with_ascii_slash_inside_the_topic_name_misplits():
    """命名陷阱①的正身：topic 名含 '/' 时，第一段被切错，永不等于配置里的名字。"""
    assert _id_topic("Fate/Grand Order/fgo/主线__3") == "Fate"


# ------------------------------------------------- 滤空时的爆炸半径（核心）

def test_slash_bearing_whitelist_starves_the_domain_but_deletes_nothing():
    """配了个含 '/' 的白名单 → 该域取不到任何条目（静默不补，已知代价）；
    但**绝不能因此把台账里已有的整域删掉**——那才是不可逆事故。"""
    entries = {"Fate/Grand Order/fgo/主线__3": "h3"}
    store = _LedgerStore({"Fate/Grand Order/fgo/主线__3": "h3"})

    index = manifest_index(_manifest(entries), ["Fate/Grand Order"])
    assert index == {}, "命名含 '/' 时白名单匹配不到任何 doc_id（本测试的前提）"

    stats, missing, removable = reconcile_with_manifest(
        store, _manifest(entries), ["Fate/Grand Order"],
    )
    assert stats["reconcile_status"] == "skipped_manifest_incomplete"
    assert missing == set() and removable == set()


def test_truncated_manifest_never_drives_deletion():
    """documents 与 entries 条数不一致=清单半截，此时既不能补也不能删。"""
    entries = {"鸣潮/bwiki/角色/卡穆__1": "h1"}
    manifest = _manifest(entries, documents=999)
    stats, missing, removable = reconcile_with_manifest(
        _LedgerStore({"鸣潮/bwiki/角色/卡穆__1": "stale"}), manifest, [],
    )
    assert stats["reconcile_status"] == "skipped_manifest_incomplete"
    assert removable == set()
    assert missing == set(), "清单不可信时连补投也不该做"


def test_partial_coverage_domain_deletions_are_suspended_not_applied():
    """清单只覆盖 A 域、台账里还有 B 域：B 的条目**必须挂起**，不能因为
    「本轮清单里没有」就被当成已删除清掉——爬虫支持按 topic 子集导出。"""
    entries = {"鸣潮/bwiki/角色/卡穆__1": "h1"}
    ledger = {
        "鸣潮/bwiki/角色/卡穆__1": "h1",
        "战双帕弥什/bwiki/章节__2": "h2",   # 清单没覆盖这个域
    }
    stats, _missing, removable = reconcile_with_manifest(
        _LedgerStore(ledger), _manifest(entries), [],
    )
    assert "战双帕弥什/bwiki/章节__2" not in removable
    assert stats["reconcile_held"] == 1
    assert stats["reconcile_status"] == _RECONCILE_REMOVE_SUSPENDED


def test_covered_domain_orphan_is_really_really_removable():
    """反向锁：清单确实覆盖了该域、且台账条目不在清单里时，删除**要**发生。
    否则上面那条「挂起」会被误当成永不删除的免死金牌，语料只增不减。"""
    entries = {"鸣潮/bwiki/角色/卡穆__1": "h1"}
    ledger = {
        "鸣潮/bwiki/角色/卡穆__1": "h1",
        "鸣潮/bwiki/角色/已删活动__9": "h9",
    }
    stats, _missing, removable = reconcile_with_manifest(
        _LedgerStore(ledger), _manifest(entries), [],
    )
    assert removable == {"鸣潮/bwiki/角色/已删活动__9"}
    assert stats["reconcile_extra"] == 1 and stats["reconcile_held"] == 0


def test_changed_hash_on_covered_doc_is_a_backfill_not_a_delete():
    """台账 hash 与清单不同=内容变了却没进本轮 updates.jsonl（一天两档导出、
    Bot 只读一档时被覆盖的那部分）：应进「待补」，不是「待删」。"""
    entries = {"鸣潮/bwiki/角色/卡穆__1": "NEW"}
    doc = "鸣潮/bwiki/角色/卡穆__1"
    stats, missing, removable = reconcile_with_manifest(
        _LedgerStore({doc: "OLD"}), _manifest(entries), [],
    )
    assert missing == {doc} and removable == set()
    assert stats["reconcile_missing"] == 1


# ------------------------------------------------------------- LIKE 命名门

def test_escape_like_neutralizes_topic_name_wildcards():
    """命名陷阱②：将来若按 source_id 前缀做 LIKE 过滤，topic 名里的 '_'/'%'
    必须先经 _escape_like，否则自身变成通配符、跨域误召回。"""
    for term in ("5周年庆典", "100%_传说", "a_b%"):
        escaped = _escape_like(term)
        assert "%" not in escaped.replace("\\%", "")
        assert "_" not in escaped.replace("\\_", "")
    assert _escape_like("鸣潮") == "鸣潮", "普通中文名不该被改写"


# ------------------------------------- topics 子集授权护栏（整域误删修复锁）

def test_subset_topics_hold_every_unauthorized_domain_even_when_stats_cover_it():
    """RED 锁（2026-09-20 整域误删漏洞）：manifest 的 topics 统计是全量 15 域，
    本地只授权 topics=["鸣潮"] 一个子集——其余 14 域属「本轮未覆盖」，
    它们的台账行（清一色**活文档**，因为子集过滤后根本进不了对账索引）
    一条都不许进 removable，全部计入 reconcile_held 并挂起。
    修复前：corpus_topics 取清单全量统计、不跟 topics 收窄，14 域整域连块
    带台账被误判「可删」。"""
    all_topics = ["鸣潮"] + [f"域{n}" for n in range(2, 16)]
    entries: dict[str, str] = {}
    for topic in all_topics:
        for i in (1, 2):
            entries[f"{topic}/bwiki/词条_{topic}_{i}"] = f"h-{topic}-{i}"
    # 爬虫侧 per-topic 统计永远是全量的——这正是漏洞的输入形态。
    manifest = _manifest(entries, topics={t: {"documents": 2} for t in all_topics})
    deleted_in_authorized = "鸣潮/bwiki/已删词条_鸣潮_9"
    ledger = dict(entries)
    ledger[deleted_in_authorized] = "h-gone"

    stats, _missing, removable = reconcile_with_manifest(
        _LedgerStore(ledger), manifest, ["鸣潮"],
    )
    foreign_orphans = {doc for doc in ledger if _id_topic(doc) != "鸣潮"}
    assert len(foreign_orphans) == 28, "前提：14 个未授权域的活文档全在台账孤儿集里"
    assert removable == {deleted_in_authorized}, (
        "授权域内的真删除照常生效；授权域之外一条都不许删"
    )
    assert foreign_orphans.isdisjoint(removable)
    assert stats["reconcile_extra"] == 1
    assert stats["reconcile_held"] == len(foreign_orphans)
    assert stats["reconcile_missing"] == 0
    assert stats["reconcile_status"] == _RECONCILE_REMOVE_SUSPENDED


def test_empty_topics_full_sync_path_is_untouched_field_by_field():
    """负向锁：topics=[]（空=全部）必须与改动前逐字段一致，防止把全量路径
    也顺手收紧。含「清单 topics 统计里有该域、entries 里一条都没有」的孤儿
    ——全量口径下该域**算被覆盖**，删除照旧生效（stats 全量统计是覆盖判据，
    不是 entries 推导）。"""
    entries = {"鸣潮/bwiki/卡穆_1": "h1", "战双/bwiki/露娜_1": "h2"}
    manifest = _manifest(
        entries,
        topics={"鸣潮": {"documents": 1}, "战双": {"documents": 1},
                "废都": {"documents": 0}},
    )
    ledger = {
        **entries,
        "鸣潮/bwiki/已删_9": "h9",
        "废都/bwiki/残卷_7": "h7",  # 统计覆盖、零条目：仍算覆盖→可删
    }
    stats, missing, removable = reconcile_with_manifest(
        _LedgerStore(ledger), manifest, [],
    )
    assert removable == {"鸣潮/bwiki/已删_9", "废都/bwiki/残卷_7"}
    assert stats == {
        "reconcile_status": "ok",
        "reconcile_missing": 0,
        "reconcile_extra": 2,
        "reconcile_held": 0,
    }
    assert missing == set()
