"""SEAT-S139：ANN 运维/观测五件缺陷的回归锁（全离线）。

登记来源：`.superpowers/sdd/2026-09-26-kb-recovery/SEAT-MAIN-STATUS.md` §3.4
（S126 观测五件）。逐件对号：

1. **件1 文案口径**：`_ANN_BUILD_MIN_AVAILABLE_BYTES`(4.5 GiB) 是 S85 在
   n=766,126 标定点上的**经验合价（标定）**，需求式是全比例模型、不设绝对门槛
   ——五要素卡与 observed 话术旧版把它写成"绝对下限/下限+余量"的组成式。
   本锁判"宣称形态"（`绝对下限 {floor值}` / `（下限 {floor值}` / `按绝对下限判`）
   不出现，且"标定"点名在场——并拿旧句式自证判据有牙。
2. **件2 sink 零注入点**：`kb_wiki.set_kb_sync_alert_sink` 此前全树仅测试调用
   ⇒ 内存门拒建那张卡今天根本投不出去。本锁按哨兵抽出根 `__init__.py` 装配块
   **真身文本 exec 一遍**（注入可达活性判据，先例=WP10 哨兵/test_sync_drift_activation），
   并跑"总闸关/pipeline 缺位/超管名单空 ⇒ 不注入"三条负例。
3. **件3 只写不读**：`ann_build_last_memory_skip` 的真读者=重启预检第 13 项
   `ann_pair`（S141 落地，S139 补齐缺的"规模"与计数呈现）。本锁用真库形
   （tmp sqlite + knowledge_meta）驱动真身 `inspect_ann_generation_pair`。
4. **件4 无累计、无升格**：`_record_ann_memory_skip` 写行即计
   （未越门 +1 / 越门不动 / publish 成功清零，清零写点唯一在 `_publish_ann_pair`）；
   告警在 `consecutive_skips ≥ _ANN_MEMORY_SKIP_ESCALATION_ROUNDS` 时升 critical
   并点名"连续 N 轮"。行为链 + AST 结构锁 + 反证（计数缺席 ⇒ 不升格）。
5. **件5 越门轮不可取消**：operator CLI 的 knowledge-sync 重建调用此前不传
   `on_progress` ⇒ 取消事件在该路径无人消费。本锁 AST 钉"旗+on_progress 两腿
   同在"，行为面驱动 `run_knowledge_sync`（假 store 忠实转发）验证
   **越门轮照样在批边界被取消**、取消轮不做 certify 补戳、旗路径出口归还。

行号会漂，本文件一律按符号与行为断言，不钉行号。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    vector_knowledge as vk,
)
from plugins.bot_unified_runtime.domains.location.knowledge import kb_wiki
from scripts import pre_restart_check as prc

_GIB = 1024**3
_SINK_SENTINEL_BEGIN = "# >>> S139-KBSYNC-ALERT-SINK BEGIN"
_SINK_SENTINEL_END = "# <<< S139-KBSYNC-ALERT-SINK END"


class _FakeProvider:
    dimensions = 8
    active_base_url = "http://127.0.0.1:1"
    signature = "test|s139"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            out.append([byte / 255.0 for byte in digest[:8]])
        return out


def _make_store(tmp_path: Path) -> vk.SqliteVectorKnowledgeStore:
    return vk.SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature="test|s139",
        auto_reset=True,
        ann_index_path=str(tmp_path / "kb_wiki_faiss.index"),
        ann_order_path=str(tmp_path / "kb_wiki_faiss.order.json"),
    )


def _seed(store: vk.SqliteVectorKnowledgeStore, docs: int) -> None:
    rows = [
        {
            "id": f"topic/doc-{index}",
            "hash": hashlib.sha1(f"doc{index}".encode()).hexdigest(),
            "topic": "topic",
            "source": "s139",
            "title": f"doc-{index}",
            "chunks": [f"内容{index}" * 40],
        }
        for index in range(docs)
    ]
    store.sync_documents(iter(rows), removed_ids=(), full=True)
    store.embed_pending(None)


def _read_gate_meta(store: vk.SqliteVectorKnowledgeStore) -> dict:
    raw = store.get_meta(vk._ANN_MEMORY_SKIP_META_KEY)
    assert raw, "内存门没有留下 knowledge_meta 观测行"
    parsed = json.loads(str(raw))
    assert isinstance(parsed, dict)
    return parsed


def _claims_floor_is_absolute(text: str, floor_token: str) -> bool:
    """「把标定说成物理下限」的宣称形态（旧口径 2026-09-26 前真身原句）。"""
    return (
        f"绝对下限 {floor_token}" in text
        or f"（下限 {floor_token}" in text
        or "按绝对下限判" in text
    )


# ================================================================ 件1：文案口径


def test_alert_card_names_calibration_not_absolute_floor() -> None:
    """五要素卡：floor 必须以"标定"点名，"绝对下限 {floor值}"的组成式必须消失。"""
    result = {
        "mode": "incremental",
        "ann_reason": "insufficient_memory",
        "ann_memory_gate": {
            "available": "1.62GiB",
            "required": "4.50GiB",
            "floor": "4.5GiB",
            "headroom": "1.0GiB",
            "expected_vectors": 740996,
            "dim": 1024,
            "probe_failed": False,
            "consecutive_skips": 1,
            "total_skips": 1,
        },
    }
    body = kb_wiki.build_ann_memory_alert_content(result).format_message()
    assert not _claims_floor_is_absolute(body, "4.5GiB"), "卡面把标定合价说成了绝对下限"
    assert "标定" in body, "没点名 4.5GiB 的真实性质（S85 标定合价）"
    # 三条硬要求一个字不许丢（S112 原口径）：实算 / 需求 / 放行通路。
    assert "1.62GiB" in body and "4.50GiB" in body
    assert "--ann-force-low-memory" in body
    assert "暴力扫描" in body


def test_alert_card_scale_unknown_says_live_floor() -> None:
    """规模未知分支："按绝对下限判"改口"按活体下限判"（真身=headroom+批副本）。"""
    result = {
        "mode": "incremental",
        "ann_reason": "memory_probe_unavailable",
        "ann_memory_gate": {
            "available": "unknown",
            "required": "0.3GiB",
            "floor": "4.5GiB",
            "headroom": "128MiB",
            "expected_vectors": None,
            "dim": 1024,
            "probe_failed": True,
            "consecutive_skips": 0,
            "total_skips": 0,
        },
    }
    body = kb_wiki.build_ann_memory_alert_content(result).format_message()
    assert "活体下限" in body, "规模未知分支还在说绝对下限"
    assert "按绝对下限判" not in body
    assert "取不到数" in body and "不可判定" in body, "S112 的探针不可判定话术不许丢"


def test_wording_judge_has_teeth_on_old_head_sentence() -> None:
    """判据自证：拿 HEAD（2026-09-26 前）真身旧句式喂判据，必判为「宣称」。

    旧句原文（git show HEAD 的 kb_wiki.py 拼接结果形态）：
    "本轮需要 4.50GiB（绝对下限 4.5GiB + 观察余量 1.0GiB …" 与 "…规模无从估定，按绝对下限判）。"
    若本例红 ⇒ 判据写松了，上面的"没宣称"断言全是空谈。
    """
    old_claim_a = "本轮需要 4.50GiB（绝对下限 4.5GiB + 观察余量 1.0GiB，按 740996 条 × 1024 维估）"
    old_claim_b = "本轮需要 0.3GiB（绝对下限 4.5GiB + 观察余量 128MiB，规模无从估定，按绝对下限判）"
    assert _claims_floor_is_absolute(old_claim_a, "4.5GiB")
    assert _claims_floor_is_absolute(old_claim_b, "4.5GiB")


def test_observed_public_message_wording_follows(tmp_path, monkeypatch) -> None:
    """run_kb_sync_task 出口 observed 行同口径：floor 以"标定合价"点名、
    "（下限 " 组成式消失、连续计数在场。
    """
    monkeypatch.setattr(
        kb_wiki,
        "sync_kb_wiki",
        lambda store, config, **kw: {
            "added": 3,
            "changed": 0,
            "removed": 0,
            "skipped": 0,
            "chunks": 3,
        },
    )

    class _StoreStub:
        def __init__(self, tmp: Path) -> None:
            self.embed_provider = SimpleNamespace(name="normal-provider")
            self.db_path = str(tmp / "kb_wiki_embeddings.sqlite3")
            # ANN 文件"在位"（本测试文件冒充）——同 S112 替身手法，避开 healing 分支。
            self.ann_index_path = str(Path(__file__))
            self.ann_order_path = str(Path(__file__))
            self.meta: dict[str, str] = {}

        def sync_documents(self, docs, *, removed_ids=(), full=False, on_progress=None):
            return {"added": 3, "changed": 0, "removed": 0, "skipped": 0, "chunks": 3}

        def embed_pending(self, files, on_progress=None, *, batch_size=None):
            return 0, 0

        def stats(self):
            return {"total": 24, "embedded": 24}

        def document_count(self):
            return 24

        def get_meta(self, key):
            return self.meta.get(key, "")

        def set_meta(self, key, value):
            self.meta[key] = value

        def build_ann_index(self, on_progress=None, *, force_low_memory=False):
            return {
                "built": False,
                "reason": "insufficient_memory",
                "memory_gate": {
                    "available": "1.62GiB",
                    "required": "3.90GiB",
                    "floor": "4.5GiB",
                    "headroom": "128MiB",
                    "expected_vectors": 24,
                    "dim": 8,
                    "probe_failed": False,
                    "consecutive_skips": 2,
                    "total_skips": 5,
                },
            }

    config = SimpleNamespace(bot_kb_wiki_db_path=str(tmp_path / "kb_wiki_embeddings.sqlite3"))
    result = kb_wiki.run_kb_sync_task(
        config, store=_StoreStub(tmp_path), embed=False
    )
    msg = str(result.get("public_message") or "")
    assert "ANN 本轮未重建（内存门" in msg, result
    assert "标定合价" in msg and "不是绝对下限" in msg
    assert not _claims_floor_is_absolute(msg, "4.5GiB")
    assert "已连续 2 轮被挡" in msg, "累计计数没进 observed 话术"


# ================================================================ 件2：sink 注入可达


def _extract_root_sink_block() -> str:
    body = (PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py").read_text(
        encoding="utf-8"
    )
    start = body.find(_SINK_SENTINEL_BEGIN)
    end = body.find(_SINK_SENTINEL_END)
    assert start != -1 and end != -1 and end > start, (
        "根 __init__.py 的 S139 哨兵块缺失——注入点又没了（正是本锁要拦的形态）"
    )
    block = body[start:end]
    lines = block.splitlines()
    # 首行从 "# >>>" 起是哨兵注释本体，整块丢掉；END 行的 "# <<<" 不在切片内。
    return textwrap.dedent("\n".join(lines[1:]))


def _exec_sink_block(*, enabled: bool, pipeline: object, admins: list[str]) -> None:
    """在替身命名空间里 exec 装配块真身文本（活性判据：注入可达，不是 grep 存在）。"""
    code = _extract_root_sink_block()
    config = SimpleNamespace(
        bot_kb_wiki_enabled=enabled,
        bot_kb_wiki_root="D:/whatever/crawl_wiki" if enabled else "",
        bot_super_admin_user_ids=admins,
    )
    namespace = {
        "config": config,
        "pipeline": pipeline,
        "logging": logging,
        "__name__": "s139_block_probe",
    }
    exec(compile(code, "<s139-sink-block>", "exec"), namespace)  # noqa: S102


@pytest.fixture(autouse=True)
def _restore_globals():
    yield
    kb_wiki.set_kb_sync_alert_sink(None)
    if kb_wiki._SYNC_TASK_MUTEX.locked():
        kb_wiki._SYNC_TASK_MUTEX.release()
    kb_wiki._SYNC_CANCEL_EVENT.clear()
    kb_wiki._set_kb_sync_cancel_flag_path(None)


def test_root_assembly_block_imports_and_calls_the_only_sink_factory() -> None:
    """结构面：块里直呼 `set_kb_sync_alert_sink(`，出口复用中央件、零新开告警通道。"""
    block = _extract_root_sink_block()
    assert "set_kb_sync_alert_sink(" in block
    # 直呼经 import-as 别名 ⇒ 判"中央件名在场 + 别名直呼在场"，不钉死括号连写形态。
    assert "build_alert_content_sink" in block, (
        "没复用唯一既有告警口（alerts.build_alert_content_sink）——禁止另开通道"
    )
    assert "_build_kb_sync_alert_sink(" in block, "import 了中央件却没当场构造注入"
    for banned in ("report_operational_issue", "alert_card_sink", "send_msg"):
        assert banned not in block, f"注入了第二本账/第二通道形态：{banned}"


def test_sink_injection_is_reachable() -> None:
    """行为面：exec 装配块 ⇒ kb-sync 告警从此走 sink；旧 WARNING-only 形态结束。"""
    assert kb_wiki.current_kb_sync_alert_sink() is None, "前置：全局 sink 应为空"
    _exec_sink_block(enabled=True, pipeline=object(), admins=["3865067623"])
    assert callable(kb_wiki.current_kb_sync_alert_sink()), (
        "装配块跑了却没把 sink 注进 kb_wiki——注册性假绿"
    )


def test_sink_not_injected_without_gate_pipeline_or_admins() -> None:
    """负例三条：总闸关 / pipeline 缺位 / 超管名单空 ⇒ 都不注入。

    门与 kb_wiki 调度器注册同源（bot_kb_wiki_enabled ∧ root 非空）；缺件回到
    "只打日志"的旧形态，绝不拿 None pipeline 造半个 sink。
    """
    _exec_sink_block(enabled=False, pipeline=object(), admins=["1"])
    assert kb_wiki.current_kb_sync_alert_sink() is None
    _exec_sink_block(enabled=True, pipeline=None, admins=["1"])
    assert kb_wiki.current_kb_sync_alert_sink() is None
    _exec_sink_block(enabled=True, pipeline=object(), admins=[])
    assert kb_wiki.current_kb_sync_alert_sink() is None


def test_alert_flows_through_sink_on_memory_skip() -> None:
    """端到端半程：内存门跳过 → _emit_sync_alert 把五要素卡喂给注入的 sink。"""
    captured: list = []
    kb_wiki.set_kb_sync_alert_sink(captured.append)
    result = {
        "mode": "incremental",
        "ok": True,
        "error_kind": "none",
        "ann_reason": "insufficient_memory",
        "ann_memory_gate": {
            "available": "1.62GiB",
            "required": "3.90GiB",
            "floor": "4.5GiB",
            "headroom": "128MiB",
            "expected_vectors": 24,
            "dim": 8,
            "probe_failed": False,
            "consecutive_skips": 1,
            "total_skips": 1,
        },
    }
    kb_wiki._emit_sync_alert(result)
    assert len(captured) == 1, "门跳过的卡没投递（sink 在场也丢）"
    assert "内存门" in captured[0].title


# ================================================================ 件3：真读者


def _make_wiki_db_with_skip(tmp_path: Path, payload: dict) -> Path:
    """短装代次（戳 24 > ntotal 20、成对文件体积相符）+ 内存门留痕 ⇒ MEMORY_SKIP。

    库形照真身：knowledge_meta 四行 + 同目录两枚 ANN 文件。
    """
    data_root = tmp_path / "rt"
    data_root.mkdir(parents=True, exist_ok=True)
    db = data_root / "kb_wiki_embeddings.sqlite3"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
    )
    sig = "bge-m3|http://127.0.0.1:11434"
    con.executemany(
        "INSERT INTO knowledge_meta (key, value) VALUES (?, ?)",
        [
            ("ann_expected_vector_count", "24"),
            ("ann_signature", sig),
            ("embedding_signature", sig),
            (
                "ann_pair_attestation",
                json.dumps(
                    {
                        "ntotal": 20,
                        "count": 20,
                        "signature": sig,
                        "index_bytes": 9,
                        "order_bytes": 7,
                    }
                ),
            ),
            (vk._ANN_MEMORY_SKIP_META_KEY, json.dumps(payload, ensure_ascii=False)),
        ],
    )
    con.commit()
    con.close()
    (data_root / "kb_wiki_faiss.index").write_bytes(b"i" * 9)
    (data_root / "kb_wiki_faiss.order.json").write_text("x" * 7, encoding="utf-8")
    return db


def test_pre_restart_reader_reports_scale_counters_and_calibration(tmp_path) -> None:
    """`ann_build_last_memory_skip` 的程序读者（重启预检 ann_pair 项）读出：
    规模（条数×dim）、标定口径（不是绝对下限）、连续/累计计数、阶段与原因。
    """
    db = _make_wiki_db_with_skip(
        tmp_path,
        {
            "available": "1.62GiB",
            "required": "3.90GiB",
            "floor": "4.5GiB",
            "headroom": "128MiB",
            "expected_vectors": 741428,
            "dim": 1024,
            "probe_failed": False,
            "forced": False,
            "stage": "pre",
            "at_unix": 1790000000,
            "consecutive_skips": 3,
            "total_skips": 7,
        },
    )
    verdict = prc.inspect_ann_generation_pair(
        {"BOT_KB_WIKI_DB_PATH": str(db)}, tmp_path
    )
    joined = "\n".join(verdict.facts)
    assert verdict.state == prc.ANN_STATE_MEMORY_SKIP
    assert "内存门留痕：上一轮 ANN 重建被挡" in joined
    assert "可用 1.62GiB < 需要 3.90GiB" in joined, "被挡原因（实算 vs 需求）没读出来"
    assert "规模 741428 条" in joined, "读者没报被挡时的规模（S139 缺陷 3 的补齐项）"
    assert "连续被挡 3 轮/累计 7 轮" in joined, "读者没报累计计数（长期饿死不可见）"
    assert "标定合价 4.5GiB" in joined
    assert not _claims_floor_is_absolute(joined, "4.5GiB")


# ================================================================ 件4：累计 + 升格


def test_counters_accumulate_skip_rounds(tmp_path, monkeypatch) -> None:
    """两夜连续被挡 ⇒ consecutive=2/total=2；结果字典随行带回计数（告警吃得到）。"""
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: _GIB // 8)
    store = _make_store(tmp_path)
    _seed(store, 24)
    first = store.build_ann_index()
    assert first["memory_gate"]["consecutive_skips"] == 1, "结果字典没带回计数"
    meta = _read_gate_meta(store)
    assert (meta["consecutive_skips"], meta["total_skips"]) == (1, 1)
    store.build_ann_index()
    meta = _read_gate_meta(store)
    assert (meta["consecutive_skips"], meta["total_skips"]) == (2, 2)


def test_forced_round_never_moves_counters_publish_resets_consecutive(
    tmp_path, monkeypatch
) -> None:
    """计数链全形态：挡×2 → 越门开火成功（越门记录计数不动）→ publish 清零连续。"""
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: _GIB // 8)
    store = _make_store(tmp_path)
    _seed(store, 24)
    store.build_ann_index()
    store.build_ann_index()
    result = store.build_ann_index(force_low_memory=True)
    assert result["built"] is True, result
    meta = _read_gate_meta(store)
    assert meta["forced"] is True, "最后一行应仍是越门记录（越门另记痕语义保持）"
    assert meta["consecutive_skips"] == 0, "publish 成功没清连续数"
    assert meta["total_skips"] == 2, "total 只增不减（历史总量被清零=说谎）"
    # 旧度量一个字不藏：清零的是"连续"，不是"上次被挡的规模与原因"。
    assert meta["available"] and meta["expected_vectors"]


def test_midway_abort_counts_as_a_blocked_round(tmp_path, monkeypatch) -> None:
    """中途收火也算一轮被挡（pre/midway 同一本账，计数随行交回结果字典）。"""
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: 64 * _GIB)
    store = _make_store(tmp_path)
    _seed(store, 24)
    assert store.build_ann_index()["built"] is True
    for path in (store.ann_index_path, store.ann_order_path):
        Path(path).unlink()
    reads = {"n": 0}

    def _fake_available() -> int:
        reads["n"] += 1
        return 64 * _GIB if reads["n"] == 1 else 1

    monkeypatch.setattr(vk, "_available_physical_memory_bytes", _fake_available)
    monkeypatch.setattr(vk, "_ANN_BUILD_BATCH_SIZE", 8)
    monkeypatch.setattr(vk, "_ANN_BUILD_MEMORY_RECHECK_VECTORS", 8)
    result = store.build_ann_index()
    assert result["reason"] == "insufficient_memory_midway"
    assert result["memory_gate"]["consecutive_skips"] == 1
    meta = _read_gate_meta(store)
    assert meta["stage"] == "midway"
    assert meta["consecutive_skips"] == 1


def test_escalation_upgrades_alert_and_names_streak() -> None:
    """consecutive ≥ 阈值 ⇒ level 升 critical + 卡面点名"连续第 N 轮"；阈值下 warning。"""
    threshold = vk._ANN_MEMORY_SKIP_ESCALATION_ROUNDS
    assert threshold >= 2, (
        "升格阈值不许低到一次被挡即 critical——一次被挡是当夜水位的可自愈事件"
        "（S105 实测抖动是十分钟级、次夜自愈常态，见真身常量注释）"
    )

    def _alert(consecutive: int):
        return kb_wiki.build_ann_memory_alert_content(
            {
                "mode": "incremental",
                "ann_reason": "insufficient_memory",
                "ann_memory_gate": {
                    "available": "1.62GiB",
                    "required": "3.90GiB",
                    "floor": "4.5GiB",
                    "headroom": "128MiB",
                    "expected_vectors": 24,
                    "dim": 8,
                    "probe_failed": False,
                    "consecutive_skips": consecutive,
                    "total_skips": consecutive,
                },
            }
        )

    low = _alert(threshold - 1)
    high = _alert(threshold)
    assert low.level == "warning"
    assert high.level == "critical", "连续被挡到阈值仍按 warning 的音量混=升格不存在"
    assert f"连续第 {threshold} 轮" in high.format_message()


def test_alert_falls_back_gracefully_without_counter_keys() -> None:
    """缺计数键（旧版本盘上留下的行/别的写者）⇒ 按 0 处理：不炸、不假升格。"""
    alert = kb_wiki.build_ann_memory_alert_content(
        {
            "mode": "incremental",
            "ann_reason": "insufficient_memory",
            "ann_memory_gate": {"available": "1.62GiB", "required": "3.9GiB"},
        }
    )
    assert alert.level == "warning"
    assert "3.9GiB" in alert.format_message()

    garbage = kb_wiki.build_ann_memory_alert_content(
        {
            "mode": "incremental",
            "ann_reason": "insufficient_memory",
            "ann_memory_gate": {"consecutive_skips": "nonsense"},
        }
    )
    assert garbage.level == "warning"


def test_publish_reset_is_the_only_clear_point_and_skip_never_clears() -> None:
    """结构锁：清零唯一挂在 `_publish_ann_pair`；`build_ann_index` 体内不许出现清零。

    注毒两发各红一格：①摘掉 publish 里的清零 ⇒ 第一断言红；
    ②在 build_ann_index 体内顺手清零 ⇒ 第二断言红（跳过分支自清账=连续数永远
    被洗成 0/1，长期饿死重新隐身——与 S112「跳过不许碰落戳」同一族禁令）。
    """
    import ast

    tree = ast.parse(Path(vk.__file__).read_text(encoding="utf-8"))

    def _attr_calls(fname: str) -> set[str]:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == fname:
                return {
                    call.func.attr
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                }
        raise AssertionError(f"找不到 {fname}，本锁失效")

    assert "_reset_ann_memory_skip_counters" in _attr_calls("_publish_ann_pair")
    assert "_reset_ann_memory_skip_counters" not in _attr_calls("build_ann_index")
    assert "_record_ann_memory_skip" in _attr_calls("build_ann_index")


def test_counterfactual_missing_counters_keep_warning(tmp_path, monkeypatch) -> None:
    """反证：计数腿被摘（payload 回到只写度量的旧形态）⇒ 告警停在 warning。

    证明升格判据真的吃 `consecutive_skips`，不是别的信号恰好在升账。
    """

    def _no_counters(self, verdict, *, forced, stage):
        payload = dict(verdict.as_meta())
        payload["forced"] = forced
        payload["stage"] = stage
        payload["at_unix"] = int(time.time())
        self.set_meta(
            vk._ANN_MEMORY_SKIP_META_KEY, json.dumps(payload, ensure_ascii=False)
        )
        return payload

    monkeypatch.setattr(
        vk.SqliteVectorKnowledgeStore, "_record_ann_memory_skip", _no_counters
    )
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: _GIB // 8)
    store = _make_store(tmp_path)
    _seed(store, 24)
    first = store.build_ann_index()
    store.build_ann_index()
    assert "consecutive_skips" not in first["memory_gate"]
    alert = kb_wiki.build_ann_memory_alert_content(
        {
            "mode": "incremental",
            "ann_reason": "insufficient_memory",
            "ann_memory_gate": first["memory_gate"],
        }
    )
    assert alert.level == "warning", (
        "计数缺席也能升格 ⇒ 升格不吃这枚计数，上面的升格锁是空转"
    )


# ================================================================ 件5：CLI 越门轮可取消


def test_knowledge_sync_build_call_carries_flag_and_on_progress() -> None:
    """AST 腿：knowledge-sync 的 build_ann_index 调用必须同时带
    `force_low_memory`（S112 四腿原有）与 `on_progress`（S139 第五腿）——
    只锁存在性会放过"旗接了、取消通道没接"的半死形态。
    """
    import ast

    from plugins.bot_unified_runtime.domains.ops.smoke import smoke as _smoke

    tree = ast.parse(Path(str(_smoke.__file__)).read_text(encoding="utf-8"))
    builds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "build_ann_index"
    ]
    assert builds, "smoke 里没有 build_ann_index 调用点，本锁失效"
    for call in builds:
        kwargs = {kw.arg for kw in call.keywords}
        assert "force_low_memory" in kwargs, "越门旗丢了（S112 四腿同生被破坏）"
        assert "on_progress" in kwargs, (
            "重建调用没挂进度回调 = 取消事件在这条分钟级路径上无人消费"
            "（S139 缺陷 5 回潮）"
        )
    attr_names = {
        call.func.attr
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert "_set_kb_sync_cancel_flag_path" in attr_names, (
        "重建段没登记旗路径 ⇒ 进程外落的旗永远 inert（S112 同型教训回潮）"
    )


class _CliSpyStore:
    """knowledge-sync CLI 用最小 store 替身；build_ann_index 忠实转发 on_progress
    （真身 `_build_ann_index_locked` 每批打一次点），于是"取消检查点有没有延伸到
    建索引批边界"可判定。
    """

    def __init__(self, tmp_path: Path, *, flag_appears_midbuild: bool) -> None:
        self.db_path = str(tmp_path / "knowledge_embeddings.sqlite3")
        self._flag_appears_midbuild = flag_appears_midbuild
        self.build_calls: list[dict] = []
        self.certify_calls = 0

    def embed_pending(self, files, on_progress=None):
        return 0, 0

    def stats(self):
        return {"total": 24, "embedded": 24}

    def build_ann_index(self, on_progress=None, *, force_low_memory=False):
        self.build_calls.append(
            {"on_progress": on_progress, "force_low_memory": force_low_memory}
        )
        if on_progress is not None and self._flag_appears_midbuild:
            kb_wiki.kb_sync_cancel_flag_path(self.db_path).write_text(
                "mid-build\n", encoding="utf-8"
            )
        if on_progress is not None:
            on_progress(1024)  # 真身每批一次；这一发必须把取消吃到。
        return {"built": True, "vectors": 24, "reason": ""}

    def certify_expected_vector_count(self, **kw):
        self.certify_calls += 1
        return 24


def _cli_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_embedding_model="m",
        bot_embedding_base_url="http://127.0.0.1:1/v1",
        bot_embedding_api_key="k",
        bot_embedding_timeout_seconds=5.0,
        bot_embedding_dimensions=8,
        bot_embedding_local_enabled=False,
        bot_embedding_local_models="",
        bot_embedding_local_base_url="",
        bot_embedding_local_timeout_seconds=5.0,
        bot_knowledge_db_path=str(tmp_path / "knowledge_embeddings.sqlite3"),
        bot_knowledge_files=[],
        bot_knowledge_chunk_chars=900,
        bot_knowledge_top_k=4,
    )


def test_forced_round_is_still_cancellable(tmp_path, monkeypatch) -> None:
    """**件 5 主断言**：`--ann-force-low-memory` 越门轮照样在批边界被取消；
    取消轮不做 certify 补戳（半程状态不做完备背书）、旗路径出口归还。
    """
    from plugins.bot_unified_runtime.domains.ops.smoke import smoke

    spy = _CliSpyStore(tmp_path, flag_appears_midbuild=True)
    monkeypatch.setattr(smoke, "SqliteVectorKnowledgeStore", lambda **kw: spy)
    result = smoke.run_knowledge_sync(_cli_config(tmp_path), force_low_memory=True)
    assert spy.build_calls and spy.build_calls[0]["force_low_memory"] is True
    assert spy.build_calls[0]["on_progress"] is not None, "越门轮没挂取消通道"
    assert result["error_kind"] == "cancelled", (
        "旗落了越门轮照跑到底：协作式可取消在越门分支失效（本缺陷原形）"
    )
    assert result["ann_index_built"] is False
    assert "取消" in str(result.get("public_message") or "")
    assert spy.certify_calls == 0, "取消轮还在做 certify 补戳"
    assert not kb_wiki.kb_sync_cancel_flag_path(spy.db_path).exists(), "一次性消费：旗必须被删"
    assert kb_wiki.current_kb_sync_cancel_flag_path() is None, "旗路径没归还"


def test_unforced_round_completes_and_certifies(tmp_path, monkeypatch) -> None:
    """对照组：无旗时重建正常跑完并走 certify（取消面没把主路径挡死）。"""
    from plugins.bot_unified_runtime.domains.ops.smoke import smoke

    spy = _CliSpyStore(tmp_path, flag_appears_midbuild=False)
    monkeypatch.setattr(smoke, "SqliteVectorKnowledgeStore", lambda **kw: spy)
    result = smoke.run_knowledge_sync(_cli_config(tmp_path), force_low_memory=False)
    assert spy.build_calls[0]["force_low_memory"] is False
    assert spy.build_calls[0]["on_progress"] is not None
    assert result["error_kind"] != "cancelled", result
    assert spy.certify_calls == 1
    assert kb_wiki.current_kb_sync_cancel_flag_path() is None


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
