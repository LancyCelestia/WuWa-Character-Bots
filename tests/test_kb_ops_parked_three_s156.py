"""SEAT-S156：S139 §7「在册未做」三条的回归锁（全离线，不碰生产库）。

三条对号（简报=席位任务书，坐标本文件现算）：

1. **内存门告警收件名单与运行态告警同源**：根 `__init__.py` 的
   S139-KBSYNC-ALERT-SINK 装配块旧版自己读 `bot_super_admin_user_ids`
   ——与运行态告警（`_operational_alert_targets` 的 QQ 腿读
   `bot_admin_user_ids`）各持一本名单账。本锁钉：装配块读的字段必须与
   `_operational_alert_targets` 的 QQ 收件字段是**同一枚**，且行为面 exec
   真身块时收件人来自 `bot_admin_user_ids`（超管字段在场也不吃）。
2. **越门轮计数语义「算不算被挡一次」**：结论=**不算**（人工放行不是门又
   挡一夜），S139 把结论写进了常量块注释；本波坐实两件事——①结论已带
   裁定标记写进 `_ANN_MEMORY_SKIP_*` 常量块注释（文本锁）；②补上 S139
   没锁住的半维：越门轮**没走到 publish**（被取消等早退）时计数
   **既不加也不清**（旧锁只经由"越门+成功"路径，publish 清零把"不清"
   这一维洗成了不可判别）。反证腿：把越门分支注成"清连续" ⇒ 本场景
   可判别值必须翻转，证明锁吃这一维。
3. **knowledge-sync 的 operator 落旗入口**：`--kb-cancel` 此前只在
   kb-sync（wiki 库）分支生效，knowledge-sync 进程的旗只有 bot 内函数或
   人工落文件一条路。本锁钉：`smoke.py knowledge-sync --kb-cancel` 点名
   可落；落点与消费端**同一条旗路径真身**（`kb_sync_cancel_flag_path` ×
   同一次 db 路径派生），否则"落了的旗"与"被消费的旗"两本账、旗 inert；
   端到端行为=先落旗再起跑的那轮在批边界真被取消；零新增 config 键。

行号会漂，本文件按符号/文本区/行为断言，不钉行号。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
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
from plugins.bot_unified_runtime.domains.ops.monitor import alerts as alerts_mod
from plugins.bot_unified_runtime.domains.ops.smoke import smoke

_GIB = 1024**3
_SINK_SENTINEL_BEGIN = "# >>> S139-KBSYNC-ALERT-SINK BEGIN"
_SINK_SENTINEL_END = "# <<< S139-KBSYNC-ALERT-SINK END"
_RUNTIME_FIELD = "bot_admin_user_ids"  # 运行态告警的 QQ 收件真源（现算见下方区域锁）
_OLD_FIELD = "bot_super_admin_user_ids"


@pytest.fixture(autouse=True)
def _restore_globals():
    yield
    kb_wiki.set_kb_sync_alert_sink(None)
    kb_wiki._SYNC_CANCEL_EVENT.clear()
    kb_wiki._set_kb_sync_cancel_flag_path(None)


def _root_init_text() -> str:
    return (PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py").read_text(
        encoding="utf-8"
    )


# ================================================================ 条1：名单同源


def sink_block_region(body: str) -> str:
    """抽出根件 S139 哨兵块全文（判据可被注毒副本复用——§4 注毒台吃它）。"""
    start = body.find(_SINK_SENTINEL_BEGIN)
    end = body.find(_SINK_SENTINEL_END)
    assert start != -1 and end != -1 and end > start, "S139 哨兵块缺失（注入点没了）"
    return body[start:end]


def operational_targets_region(body: str) -> str:
    """运行态告警收件派生函数的源码区（`_operational_alert_targets` 起 10 行）。"""
    start = body.find("def _operational_alert_targets")
    assert start != -1, "运行态告警收件函数不见了——同源判据失去锚点"
    return "\n".join(body[start:].splitlines()[:10])


def roster_fields_agree(body: str) -> bool:
    """两条告警收件路径必须读同一枚字段：装配块只读 `_RUNTIME_FIELD`，
    且运行态派生函数确实读它。回潮读超管字段 ⇒ False。"""
    block = sink_block_region(body)
    if _OLD_FIELD in block:
        return False
    return _RUNTIME_FIELD in block and _RUNTIME_FIELD in operational_targets_region(body)


def test_memory_alert_roster_shares_operational_field() -> None:
    """结构面：内存门告警名单与运行态告警同源（今天做不到 ⇒ 改前红）。"""
    assert roster_fields_agree(_root_init_text()), (
        "内存门告警的收件名单没走运行态告警同一枚字段"
        f"（应为 {_RUNTIME_FIELD}，旧口径 {_OLD_FIELD} 已裁定作废）"
    )


def test_sink_recipients_come_from_operational_field(monkeypatch) -> None:
    """行为面：exec 装配块真身 ⇒ 注入的收件人来自 `bot_admin_user_ids`。

    替身里两枚名单故意不同值：块若还读超管字段，captured 会是哨兵值、
    本判据当场红——不靠注释自觉。
    """
    captured: dict = {}

    def _factory(pipeline, admin_ids, **kwargs):  # 替身签名宽松（本仓未启用 ANN 族）
        captured["pipeline"] = pipeline
        captured["admin_ids"] = list(admin_ids)
        return lambda alert: None

    monkeypatch.setattr(alerts_mod, "build_alert_content_sink", _factory)
    code = sink_block_region(_root_init_text()).splitlines()
    code = "\n".join(code[1:])  # 首行是哨兵注释本体
    import textwrap

    config = SimpleNamespace(
        bot_kb_wiki_enabled=True,
        bot_kb_wiki_root="D:/whatever/crawl_wiki",
        bot_admin_user_ids=["111", "222"],
        bot_super_admin_user_ids=["999-super-should-not-receive"],
    )
    namespace = {
        "config": config,
        "pipeline": object(),
        "logging": logging,
        "__name__": "s156_roster_probe",
    }
    exec(textwrap.dedent(code), namespace)  # noqa: S102
    assert captured.get("admin_ids") == ["111", "222"], (
        f"内存门告警收件人没吃运行态名单（got {captured.get('admin_ids')!r}）"
    )
    assert callable(kb_wiki.current_kb_sync_alert_sink())


def test_sink_not_injected_when_operational_roster_empty(monkeypatch) -> None:
    """负例：运行态名单为空 ⇒ 不注入——超管名单非空也**不**算有收件人
    （旧口径下这条必红：块读超管字段会照样注入=第二本名单账）。"""
    injected: list = []
    monkeypatch.setattr(
        alerts_mod,
        "build_alert_content_sink",
        lambda *a, **k: injected.append(a) or (lambda alert: None),
    )
    import textwrap

    code = textwrap.dedent("\n".join(sink_block_region(_root_init_text()).splitlines()[1:]))
    config = SimpleNamespace(
        bot_kb_wiki_enabled=True,
        bot_kb_wiki_root="D:/whatever",
        bot_admin_user_ids=[],
        bot_super_admin_user_ids=["999-super-only"],
    )
    exec(code, {"config": config, "pipeline": object(), "logging": logging,  # noqa: S102
                "__name__": "s156_empty_roster"})
    assert kb_wiki.current_kb_sync_alert_sink() is None
    assert not injected, "空运行态名单仍被注入 ⇒ 内存门告警自立了一本名单账"


# ================================================================ 条2：越门轮计数


def _make_store(tmp_path: Path) -> vk.SqliteVectorKnowledgeStore:
    class _FakeProvider:
        dimensions = 8
        active_base_url = "http://127.0.0.1:1"
        signature = "test|s156"

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [
                [b / 255.0 for b in hashlib.sha1(t.encode("utf-8")).digest()[:8]]
                for t in texts
            ]

    return vk.SqliteVectorKnowledgeStore(
        db_path=tmp_path / "kb_wiki_embeddings.sqlite3",
        embed_provider=_FakeProvider(),
        chunk_chars=800,
        top_k=4,
        signature="test|s156",
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
            "source": "s156",
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


def constants_block_text() -> str:
    """`_ANN_MEMORY_SKIP_CONSECUTIVE_KEY` 起、到升格阈值常量前的注释区。"""
    src = Path(vk.__file__).read_text(encoding="utf-8")
    start = src.find("_ANN_MEMORY_SKIP_CONSECUTIVE_KEY")
    assert start != -1, "计数常量不见了"
    end = src.find("_ANN_MEMORY_SKIP_ESCALATION_ROUNDS", start)
    assert end != -1
    return src[start:end]


def constants_ruling_present(text: str) -> bool:
    """常量块必须**直接回答**「越门那一轮算不算被挡一次」：不算，且不加也不清。"""
    return (
        "不算" in text
        and "被挡一次" in text
        and "不加也不清" in text
    )


def test_constants_block_records_forced_round_ruling() -> None:
    """裁定文本锁：结论写进常量块注释（S156 裁定的落点）。"""
    assert constants_ruling_present(constants_block_text()), (
        "常量块没把『越门轮算不算被挡一次』的结论写死（应为：不算，不加也不清）"
    )


def _run_blocked_then_forced_cancel(tmp_path, monkeypatch) -> dict:
    """场景：一夜被挡（1/1）→ operator 越门开火、批边界被取消（never publish）。"""
    monkeypatch.setattr(vk, "_available_physical_memory_bytes", lambda: _GIB // 8)
    store = _make_store(tmp_path)
    _seed(store, 24)
    blocked = store.build_ann_index()
    assert blocked["built"] is False and blocked["memory_gate"]["consecutive_skips"] == 1
    kb_wiki._SYNC_CANCEL_EVENT.set()
    with pytest.raises(kb_wiki.KbSyncCancelled):
        store.build_ann_index(
            on_progress=kb_wiki._cancel_aware_progress(None), force_low_memory=True
        )
    return _read_gate_meta(store)


def test_forced_round_without_publish_neither_adds_nor_clears(tmp_path, monkeypatch) -> None:
    """条2主锁：越门轮**不算被挡一次**——没走到 publish 时计数原样（不加、不清）。

    S139 的旧锁只走「越门+成功」路径，publish 清零把「不清」这一维洗成不可
    判别；本用例走「越门+取消」路径，两维都可观测：最后一行是越门留痕
    （forced=True，证据保留），计数停在被挡轮的 1/1。
    """
    meta = _run_blocked_then_forced_cancel(tmp_path, monkeypatch)
    assert meta.get("forced") is True, "越门轮必须另记痕（证据不能因取消而丢）"
    assert meta[vk._ANN_MEMORY_SKIP_CONSECUTIVE_KEY] == 1, (
        "越门轮被计成/清成别的值 ⇒ 「不算被挡一次」的裁定失守"
    )
    assert meta[vk._ANN_MEMORY_SKIP_TOTAL_KEY] == 1


def test_forced_clear_poison_is_discriminable_by_this_scenario(tmp_path, monkeypatch) -> None:
    """反证腿（注毒在进程内，不触盘）：把越门分支注成「清连续」⇒ 同场景值翻转。

    证明条2主锁真的吃「不清」这一维；若本反证与主锁观察值相同，主锁就是空转。
    """
    real = vk.SqliteVectorKnowledgeStore._record_ann_memory_skip

    def _poisoned(self, verdict, *, forced, stage):
        payload = real(self, verdict, forced=forced, stage=stage)
        if forced:
            payload = dict(payload)
            payload[vk._ANN_MEMORY_SKIP_CONSECUTIVE_KEY] = 0
            self.set_meta(vk._ANN_MEMORY_SKIP_META_KEY, json.dumps(payload))
        return payload

    monkeypatch.setattr(
        vk.SqliteVectorKnowledgeStore, "_record_ann_memory_skip", _poisoned
    )
    meta = _run_blocked_then_forced_cancel(tmp_path, monkeypatch)
    assert meta[vk._ANN_MEMORY_SKIP_CONSECUTIVE_KEY] == 0, (
        "毒没翻转场景值 ⇒ 本场景对『越门即清零』无杀伤力，主锁为空转"
    )


# ================================================================ 条3：operator 落旗入口


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
        bot_knowledge_db_path=str(tmp_path / "know" / "knowledge_embeddings.sqlite3"),
        bot_kb_wiki_db_path=str(tmp_path / "wiki" / "kb_wiki_embeddings.sqlite3"),
        bot_knowledge_files=[],
        bot_knowledge_chunk_chars=900,
        bot_knowledge_top_k=4,
    )


def test_run_kb_cancel_knowledge_target_lands_flag_on_knowledge_side(tmp_path) -> None:
    """点名 knowledge-sync 的落旗：旗落 knowledge 库目录，wiki 目录零沾染。"""
    cfg = _cli_config(tmp_path)
    out = smoke.run_kb_cancel(cfg, target="knowledge-sync")
    flag = kb_wiki.kb_sync_cancel_flag_path(cfg.bot_knowledge_db_path)
    assert Path(out["flag_path"]) == flag
    assert flag.is_file() and "operator-cli" in flag.read_text(encoding="utf-8")
    wiki_flag = kb_wiki.kb_sync_cancel_flag_path(cfg.bot_kb_wiki_db_path)
    assert not wiki_flag.exists(), "knowledge 目标的旗落到了 wiki 侧 ⇒ 两本账"


def test_run_kb_cancel_wiki_target_keeps_today_behavior(tmp_path) -> None:
    """缺省 target 逐字节保持旧行为（旗仍落 wiki 库目录）。"""
    cfg = _cli_config(tmp_path)
    out = smoke.run_kb_cancel(cfg)
    assert Path(out["flag_path"]) == kb_wiki.kb_sync_cancel_flag_path(
        cfg.bot_kb_wiki_db_path
    )
    assert Path(out["flag_path"]).is_file()
    know_flag = kb_wiki.kb_sync_cancel_flag_path(cfg.bot_knowledge_db_path)
    assert not know_flag.exists()


def test_run_kb_cancel_unknown_target_fails_closed(tmp_path) -> None:
    cfg = _cli_config(tmp_path)
    with pytest.raises(ValueError):
        smoke.run_kb_cancel(cfg, target="telepathy")
    for db in (cfg.bot_knowledge_db_path, cfg.bot_kb_wiki_db_path):
        assert not kb_wiki.kb_sync_cancel_flag_path(db).exists()


def test_dropped_flag_path_equals_consumed_flag_path(tmp_path, monkeypatch) -> None:
    """同源锁：operator 落的旗路径 == knowledge-sync 重建段登记的消费路径。

    两者若各派生各的（不同 db 路径写法/不同目录），旗落了也没人吃——
    与 S112「存在性糊过活性判据」同型。判据取真身：spy 在 build_ann_index
    里现读 `current_kb_sync_cancel_flag_path()`。
    """
    cfg = _cli_config(tmp_path)
    out = smoke.run_kb_cancel(cfg, target="knowledge-sync")
    dropped = Path(out["flag_path"])
    kb_wiki._SYNC_CANCEL_EVENT.clear()  # 模拟另一进程：只留文件

    class _SpyStore:
        def __init__(self) -> None:
            self.observed: Path | None = None

        def embed_pending(self, files, on_progress=None):
            return 0, 0

        def stats(self):
            return {"total": 24, "embedded": 24}

        def build_ann_index(self, on_progress=None, *, force_low_memory=False):
            self.observed = kb_wiki.current_kb_sync_cancel_flag_path()
            return {"built": True, "vectors": 24, "reason": ""}

        def certify_expected_vector_count(self, **kw):
            return 24

    spy = _SpyStore()
    monkeypatch.setattr(smoke, "SqliteVectorKnowledgeStore", lambda **kw: spy)
    result = smoke.run_knowledge_sync(cfg)
    assert result["ok"], result
    assert spy.observed == dropped, (
        f"落点 {dropped} ≠ 消费点 {spy.observed} ⇒ 两本账，旗 inert"
    )


def test_operator_flag_cancels_running_knowledge_sync_round(tmp_path, monkeypatch) -> None:
    """端到端：先落旗再起跑的那轮 knowledge-sync 在 ANN 批边界真被取消。"""
    cfg = _cli_config(tmp_path)
    Path(cfg.bot_knowledge_db_path).parent.mkdir(parents=True, exist_ok=True)
    smoke.run_kb_cancel(cfg, target="knowledge-sync")
    kb_wiki._SYNC_CANCEL_EVENT.clear()

    class _ForwardStore:
        def embed_pending(self, files, on_progress=None):
            return 0, 0

        def stats(self):
            return {"total": 24, "embedded": 24}

        def build_ann_index(self, on_progress=None, *, force_low_memory=False):
            assert on_progress is not None
            on_progress(1024)  # 真身每批打一次点：这一发必须吃到旗
            return {"built": True, "vectors": 24, "reason": ""}

        def certify_expected_vector_count(self, **kw):
            raise AssertionError("取消轮不许做 certify 补戳")

    monkeypatch.setattr(smoke, "SqliteVectorKnowledgeStore", lambda **kw: _ForwardStore())
    result = smoke.run_knowledge_sync(cfg)
    assert result["error_kind"] == "cancelled", result
    flag = kb_wiki.kb_sync_cancel_flag_path(smoke._knowledge_sync_db_path(cfg))
    assert not flag.exists(), "一次性消费：旗必须被删"


def knowledge_sync_branch_text() -> str:
    body = Path(str(smoke.__file__)).read_text(encoding="utf-8")
    start = body.find('if args.task == "knowledge-sync":')
    assert start != -1, "knowledge-sync 分支不见了"
    end = body.find('if args.task == "kb-sync":', start)
    assert end != -1
    return body[start:end]


def test_cli_names_the_knowledge_cancel_entry() -> None:
    """点名锁：`smoke.py knowledge-sync --kb-cancel` 在分支里真接线（不跑、只落旗）。"""
    branch = knowledge_sync_branch_text()
    assert "args.kb_cancel" in branch, "knowledge-sync 分支不认 --kb-cancel"
    assert 'run_kb_cancel(config, target="knowledge-sync")' in branch, (
        "分支里的落旗没点名 knowledge-sync 目标"
    )
    help_text = Path(str(smoke.__file__)).read_text(encoding="utf-8")
    flag_start = help_text.find('"--kb-cancel"')
    assert "knowledge-sync" in help_text[flag_start : flag_start + 700], (
        "--kb-cancel 帮助文本没覆盖新目标（operator 无从点名）"
    )


def test_db_path_derivation_is_single_source() -> None:
    """落旗与消费的 db 路径派生必须走同一个函数（两本账的根在派生处）。"""
    body = Path(str(smoke.__file__)).read_text(encoding="utf-8")
    assert "def _knowledge_sync_db_path(" in body
    start = body.find("def run_knowledge_sync(")
    end = body.find("def main(", start)
    assert "_knowledge_sync_db_path(config)" in body[start:end]
    cstart = body.find("def run_kb_cancel(")
    cend = body.find("def run_knowledge_sync(", cstart)
    assert "_knowledge_sync_db_path(config)" in body[cstart:cend]


def test_no_new_config_key_for_knowledge_cancel() -> None:
    """禁新增 config 键：S156 没往 Config 里塞任何 kb_cancel/knowledge_cancel 字段。"""
    cfg_src = (
        PROJECT_ROOT / "plugins" / "bot_unified_runtime" / "config.py"
    ).read_text(encoding="utf-8")
    for banned in ("kb_cancel", "cancel_target", "ann_force"):
        assert banned not in cfg_src, f"config.py 出现了禁入键形态：{banned}"


# ================================================================ 时间戳（防呆自证）


def test_fixture_clock_sanity() -> None:
    assert time.time() > 1_700_000_000
