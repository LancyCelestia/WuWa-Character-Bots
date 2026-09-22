"""`scripts/kb_wiki_retrieval_probe.py` 的离线锁（不碰 Ollama、不碰生产库）。

立锁缘由：探针的**归因**这一步最容易悄悄失效——
① `doc_id` 的源在 `parts[1]`，取 `parts[2]` 会让每个源都归因成"未知"，
   于是"命中若干块、本源 0 块"，看着像没爬进来（2026-09-22 收口表就踩过这条）；
② 命中对象的形状（dict / dataclass / tuple）一改，取 id 的口子就断，
   断了以后所有探针都退化成"零命中"——那是探针坏，不是检索坏。
所以取 id 与归因这两件必须是纯函数，并各有正反例。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kb_wiki_retrieval_probe as probe


class _Hit:
    def __init__(self, doc_id):
        self.doc_id = doc_id


def test_命中对象三种形状都能取出_doc_id():
    doc = "明日方舟/prts_arknights/正文/12F干员密录1__25113"
    assert probe.hit_source_id({"source_id": doc}) == doc
    assert probe.hit_source_id(_Hit(doc)) == doc
    assert probe.hit_source_id(("chunkhash", doc, 0.81)) == doc
    assert probe.hit_source_id(object()) == "", "取不到 id 要返回空串，不能抛穿整轮"


def test_归因取第二段而不是正文目录():
    topic, source = probe.source_of("鸣潮/fandom_wutheringwaves/正文/4½__68736")
    assert (topic, source) == ("鸣潮", "fandom_wutheringwaves")
    assert probe.source_of("单段路径") == ("", "")
    assert probe.source_of("") == ("", "")


def test_探针按本源命中计数且区分零命中():
    fake = [
        {"source_id": "鸣潮/fandom_wutheringwaves/正文/A__1"},
        {"source_id": "FGO/fgo/正文/B__2"},
    ]
    rows = probe.evaluate(lambda q: fake, probes=[("X", "fandom_wutheringwaves", "q")])
    assert rows == [("X", "fandom_wutheringwaves", 2, 1)]
    none_rows = probe.evaluate(lambda q: [], probes=[("X", "y", "q")])
    assert none_rows[0][2:] == (0, 0), "零命中要如实记 0，不许靠异常蒙过去"
