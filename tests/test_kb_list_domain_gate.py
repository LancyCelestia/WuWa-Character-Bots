"""库侧在册主题 ↔ 本地域词表：需求 3「稳定获取」这条腿的同源门（T1 后半，2026-09-28）。

病根：``question_intent.DOMAIN_TERMS`` 与维基库**实际收录**的主题名单是两份各写各的
东西。库里收了某一域的整套语料、词表却没有该域锚点，于是那一域的题既不判
LOCAL_KNOWLEDGE、也走不到"本地优先、低置信才补网"——资料明明躺着，模型却被推去联网。

本文件不新增话术，只把"名单只准有一个真身"钉成判据：

- 在册主题真身＝**库侧现算**（``kb_wiki.iter_corpus_topic_names`` 读爬虫导出，
  源码里不登第二份名单——规则 10）；
- 本地域锚点真身＝``question_intent.DOMAIN_TERMS``（它自己由检索登记表现取）；
- 缺口判据＝``kb_wiki.topics_without_local_domain_anchor``。
"""
from __future__ import annotations

import json
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.runtime.question_intent import (
    DOMAIN_TERMS,
)
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    ACG_DOMAIN_TERMS,
    ACG_TIER_STRONG,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki


def _write_corpus(tmp_path: Path, topics: list[str]) -> Path:
    """造一份最小导出快照：documents.jsonl 每行 ``{"id","topic"}``，不碰任何真库。"""
    lines = [
        json.dumps(
            {"id": f"{topic}/moegirl/条目__1", "topic": topic, "title": "条目"},
            ensure_ascii=False,
        )
        for topic in topics
    ]
    (tmp_path / "documents.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------ 库侧现算名单


def test_corpus_topic_names_are_computed_from_the_export(tmp_path: Path) -> None:
    kb_dir = _write_corpus(tmp_path, ["鸣潮", "原神", "鸣潮"])
    assert list(kb_wiki.iter_corpus_topic_names(kb_dir)) == ["鸣潮", "原神"]


def test_topic_name_falls_back_to_the_doc_id_prefix(tmp_path: Path) -> None:
    """旧导出没有 ``topic`` 字段时，退回与 ``_id_topic`` 同一口径（不许静默丢域）。"""
    (tmp_path / "documents.jsonl").write_text(
        json.dumps({"id": "明日方舟：终末地/skland_endfield/干员__2"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert list(kb_wiki.iter_corpus_topic_names(tmp_path)) == ["明日方舟：终末地"]


def test_scan_limit_bounds_the_probe(tmp_path: Path) -> None:
    """诊断路径不许退化成全表扫（与元数据探针同一纪律）。"""
    kb_dir = _write_corpus(tmp_path, [f"域{i}" for i in range(5)])
    assert len(list(kb_wiki.iter_corpus_topic_names(kb_dir, scan_limit=2))) == 2


# ------------------------------------------------------------ 同源门本体


def test_in_library_topic_missing_from_the_vocabulary_is_red() -> None:
    """失败锁本体：库里在册、词表缺项 ⇒ 必红（简报点名要的那枚"缺谁红谁"）。"""
    gaps = kb_wiki.topics_without_local_domain_anchor(
        ["鸣潮", "原神", "某新游戏域甲"], domain_terms=DOMAIN_TERMS
    )
    assert gaps == ["某新游戏域甲"], f"缺口判据没抓到不在词表的在册主题：{gaps}"
    # 反向自证：同一批在册主题，只是把锚点从词表里摘掉，就必须报缺（判据真在读词表）
    trimmed = tuple(term for term in DOMAIN_TERMS if term != "原神")
    assert kb_wiki.topics_without_local_domain_anchor(["原神"], domain_terms=trimmed) == ["原神"]
    assert kb_wiki.topics_without_local_domain_anchor(["原神"], domain_terms=DOMAIN_TERMS) == []


def test_every_registry_game_domain_is_locally_routable() -> None:
    """接线自证：登记表强专名档的每一域，拿它当在册主题都不该报缺口。"""
    registry_topics = list(ACG_DOMAIN_TERMS["game"][ACG_TIER_STRONG])
    gaps = kb_wiki.topics_without_local_domain_anchor(registry_topics)
    assert gaps == [], f"检索侧认这些是二游题、本地域词表却不认：{gaps}"


def test_anchor_side_defers_to_the_single_source() -> None:
    """库侧不许养第二份锚点名单：默认取的就是 ``question_intent.DOMAIN_TERMS`` 本身。"""
    assert kb_wiki.local_domain_anchor_terms() == tuple(DOMAIN_TERMS)


def test_kb_wiki_does_not_hand_copy_any_game_names() -> None:
    """规则 10 反手抄锁：库侧源码里出现任何具体游戏名＝它开始自己养名单了。"""
    source = Path(kb_wiki.__file__).read_text(encoding="utf-8")
    offenders = [term for term in ACG_DOMAIN_TERMS["game"][ACG_TIER_STRONG] if term in source]
    assert offenders == [], f"kb_wiki 里手抄了这些域名：{offenders}"
