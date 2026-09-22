"""九源检索可用性探针：语料进没进 RAG，看**能不能被检索到并归因回原源**。

为什么需要它：`knowledge_progress.py` 那套收工判据证明的是"账对得上"
（投料数=嵌入数、ANN 应嵌数=库内已嵌数），**不证明可检索**。块行落库、向量齐全，
检索面仍可能因为签名不符、top_k/阈值、或某源的块根本没进 ANN 而拿不到东西。
本探针走生产同一条检索口（`build_kb_wiki_retriever`），
对每个被点名的源打一句只在该源语料里出现的原文，再把命中块**按 doc_id 归因**回源。

只读：不写库、不改语料；Ollama 忙（正在灌库）时别跑，查询编码会排队。
用法：../ChatBot_Runtime/venv/Scripts/python.exe scripts/kb_wiki_retrieval_probe.py [--dump]
      --dump 会把第一条命中的原始形状打出来（命中对象字段名变了就靠它定位）。
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# 每枚探针都是从该源语料里现摘的一句原文（2026-09-22 九源重爬收口时生成），
# 缺省按「命中的块里至少有一块归因回该源」判通过——同一条内容可能在多个源都有，
# 所以不要求 Top-1 必须是它。
PROBES: list[tuple[str, str, str]] = [
    ("明日方舟", "moegirl",
     "Mon3tr是游戏《明日方舟》及其衍生作品《明日方舟:终末地》的登场角色。"),
    ("明日方舟", "wikipedia_zh",
     "以下是2026年的电子游戏业中将预定面世的新电子游戏。"),
    ("重返未来：1999", "huijiwiki_res1999",
     "BATTLE废弃科考站ABANDONED RESEARCH STATION目标GOAL 击败全部敌人"),
    ("战双帕弥什", "bilibili_wiki_zspms",
     "出于方便回顾剧情的目的,我们自己收集编写了战双的剧情回顾(包括战斗部分),希望各位指挥官满意。"),
    ("鸣潮", "bilibili_wiki_wutheringwaves",
     "出于方便回顾剧情的目的,我们自己收集编写了鸣潮的剧情回顾,希望各位漂泊者满意。"),
    ("鸣潮", "fandom_wutheringwaves",
     "Head to Panhua's Restaurant and talk to your friends"),
    ("明日方舟", "prts_arknights",
     "To step into the parts unknown and look for answers"),
]


def hit_source_id(hit: object) -> str:
    """从命中对象里取 doc_id（= 语料相对路径）。形状变了这里最先崩，所以写宽。"""
    for getter in (
        lambda h: h.get("source_id") if isinstance(h, dict) else None,
        lambda h: h.get("doc_id") if isinstance(h, dict) else None,
        lambda h: h.get("file") if isinstance(h, dict) else None,
        lambda h: getattr(h, "source_id", None),
        lambda h: getattr(h, "doc_id", None),
        lambda h: getattr(h, "file", None),
        lambda h: next((x for x in h if isinstance(x, str) and "/" in x), None)
        if isinstance(h, (tuple, list)) else None,
    ):
        value: object = None
        with contextlib.suppress(Exception):
            value = getter(hit)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def source_of(doc_id: str) -> tuple[str, str]:
    """doc_id 的源在 **parts[1]**（parts[2] 是 正文/分类，取它每个源都成"未知"）。"""
    parts = str(doc_id or "").split("/")
    if len(parts) < 2:
        return ("", "")
    return (parts[0], parts[1])


def evaluate(retrieve, probes=PROBES, dump=False):
    """逐探针跑检索，返回 [(topic, source, 命中块数, 归因命中的块数)]。"""
    rows = []
    for topic, source, query in probes:
        hits = list(retrieve(query) or [])
        owners = [source_of(hit_source_id(h)) for h in hits]
        if dump and hits:
            print(f"  [dump] 命中对象形状={type(hits[0]).__name__} 原文={str(hits[0])[:220]}")
            dump = False
        rows.append((topic, source, len(hits), sum(1 for t, s in owners if s == source)))
    return rows


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dump = "--dump" in argv
    # 配置装载走仓内唯一入口（与生产同一条 model_validate 链）；
    # 手搓 dotenv→Config 会在「.env 里写 JSON 列表」这类字段上直接炸装维。
    sys.path.insert(0, str(ROOT / "scripts"))
    from load_runtime_config import load_runtime_config

    from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (
        build_kb_wiki_retriever,
    )

    config = load_runtime_config()
    retriever: Any = build_kb_wiki_retriever(config)
    if not getattr(retriever, "available", False):
        print("检索器不可用（未启用 / 语料缺失 / 嵌入链没就绪）——不猜结果")
        return 2
    rows = evaluate(retriever.retrieve, dump=dump)
    bad = 0
    print(f"{'主题/源':<34}{'命中块':>7}{'归因回本源':>11}")
    for topic, source, n_hits, n_mine in rows:
        flag = "ok" if n_mine else "MISS"
        if not n_mine:
            bad += 1
        print(f"{topic + '/' + source:<34}{n_hits:>7}{n_mine:>11}   [{flag}]")
    print(f"=> {len(rows) - bad}/{len(rows)} 源可检索并归因正确")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
