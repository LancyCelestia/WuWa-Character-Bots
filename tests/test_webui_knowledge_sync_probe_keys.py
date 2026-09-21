"""WebUI 透出闸对 kb-sync 摘要新键 metadata_probed / metadata_with_time 的真读通测试。

判据（上游 S2 席移交，2026-09-20）：kb_wiki 有界窗口探针产出的
``metadata_probed`` / ``metadata_with_time`` 已进落库摘要（``_sync_summary``），
本测试走**真链路**验证 WebUI 侧读得到——用真生产者 ``kb_wiki._sync_summary``
生成 payload、写入 tmp 向量库 ``knowledge_meta``、经 ``KnowledgeCatalogService
.collections()`` 读出——而不是断言白名单里含某字符串（那测的是字面量）。

另含一条棘轮锁：``_sync_summary`` 的每个键必须「已透出」或「在已知缺口名单里」
二者居一——将来生产者再加新键而忘了过白名单，这里直接红，不会再静默漏。
已知缺口名单（属他人刚交付的面，本席只报不加，见 .sdd-reports/
webui-metadata-probe-expose.md §3）里的键若被主会话裁决补进白名单，本测试
仍绿（透出即满足锁）。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.control_plane.webui_knowledge import (
    KnowledgeCatalogService,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki

# _sync_summary 有、但 _KB_SYNC_PUBLIC_FIELDS 有意/暂时无不透出的键。
# public_message 是**有意**排除（自由文本，可能含导出目录路径，见白名单注释）；
# 其余四键是核查发现的漏网项，已上报待主会话裁决（2026-09-20），非本席范围。
_KNOWN_NOT_EXPOSED = frozenset(
    {
        "public_message",
        "chunks",
        "embed_pending",
        "ann_reason",
        "metadata_gaps",
    }
)

# 探针证据样例值：取一组「够判据、不成比例」的整数（231 行探针 / 57 行带字段）。
_PROBE_VALUES = {"metadata_probed": 231, "metadata_with_time": 57}


def _fake_result() -> dict[str, Any]:
    """最小同步结果：只喂 _sync_summary 会读到的观测字段，零 IO。"""
    return {
        "started_at": "2026-09-20T05:00:00+00:00",
        "mode": "incremental",
        "ok": True,
        "error_kind": None,
        "duration_ms": 1234,
        "added": 3,
        "changed": 1,
        "removed": 0,
        "skipped": 0,
        "chunks": 42,
        "embed_done": 3,
        "embed_pending": 0,
        "ann_built": True,
        "ann_reason": "",
        "documents_after": 187,
        "total_after": 999,
        "embedded_after": 187,
        "reconcile_status": "ok",
        "reconcile_missing": 0,
        "reconcile_extra": 0,
        "reconcile_held": 0,
        "metadata_status": "ok",
        "metadata_gaps": 174,
        "metadata_probed": _PROBE_VALUES["metadata_probed"],
        "metadata_with_time": _PROBE_VALUES["metadata_with_time"],
        "metadata_refreshed": 174,
        "generated_at": "2026-09-20T05:00:00+00:00",
        "documents_total": 187,
        "public_message": "本轮同步正常（含 /绝对/路径/样式，不外泄）。",
    }


def _seed_wiki_db(tmp_path: Path, payload: dict[str, Any]) -> Path:
    """把真生产者产出的摘要 JSON 落进 tmp 库 knowledge_meta（不碰生产库）。"""
    path = tmp_path / "kb_wiki_webui_probe.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?)",
            (
                kb_wiki.SYNC_SUMMARY_META_KEY,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return path


def _sync_projection(wiki_db: Path) -> dict[str, Any] | None:
    service = KnowledgeCatalogService(
        glossary_files=[],
        knowledge_db_path="",
        meme_db_path="",
        acg_sources={},
        kb_wiki_db_path=str(wiki_db),
    )
    items = {row["id"]: row for row in service.collections()["data"]["items"]}
    return items["kb_docs"]["sync"]


def test_probe_keys_readable_from_webui_through_real_summary(tmp_path: Path) -> None:
    """真链路：_sync_summary 产 → 落库 → collections() 读，两探针键原值到达。"""
    payload = kb_wiki._sync_summary(_fake_result())
    sync = _sync_projection(_seed_wiki_db(tmp_path, payload))
    assert sync is not None
    assert sync["metadata_probed"] == _PROBE_VALUES["metadata_probed"]
    assert sync["metadata_with_time"] == _PROBE_VALUES["metadata_with_time"]
    # 判据族其余成员同轮到达（status→probed→with_time→refreshed 全链可拼）。
    assert sync["metadata_status"] == "ok"
    assert sync["metadata_refreshed"] == 174


def test_free_text_stays_behind_gate(tmp_path: Path) -> None:
    """白名单的红线面：public_message（含路径形态的自由文本）绝不出现在投影里。"""
    payload = kb_wiki._sync_summary(_fake_result())
    sync = _sync_projection(_seed_wiki_db(tmp_path, payload))
    assert sync is not None
    assert "public_message" not in sync
    dumped = json.dumps(sync, ensure_ascii=False)
    assert "/绝对/路径/" not in dumped


def test_summary_keys_ratchet_gate_has_no_new_holes(tmp_path: Path) -> None:
    """棘轮：生产者每个摘要键必须已透出、或在已知缺口名单——新键裸漏直接红。"""
    payload = kb_wiki._sync_summary(_fake_result())
    sync = _sync_projection(_seed_wiki_db(tmp_path, payload))
    assert sync is not None
    exposed = set(sync)
    assert exposed <= set(payload)
    missing = set(payload) - exposed
    assert missing == _KNOWN_NOT_EXPOSED & set(payload), (
        f"摘要新键未过白名单且未登记缺口：{sorted(missing - _KNOWN_NOT_EXPOSED)}"
    )
