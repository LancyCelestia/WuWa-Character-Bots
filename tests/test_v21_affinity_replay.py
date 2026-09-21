"""V21-AFFINITY-002 历史误扣重放与具名补偿回归（全离线 tmp_path，零生产库）。

覆盖合同五面：
1. 政策差额层——refuse 事件旧扣新零（误扣机制 10 分/条）、非关系 reason_code
   同理、allow 普通事件零差额；
2. 账本重放层——已验证 source 族（poke）零差额、source 空 → unknown 不猜；
3. 只读保证——引擎唯一入库方式 mode=ro（写必被拒）+ 全流程跑完文件字节不变；
4. 补偿提案——已证多扣聚合成具名提案、事件集指纹幂等（重复生成不重复计）、
   unknown 结构性排除；
5. 与真实 DynamicAffinityStore 落库形态兼容（schema/内部值口径）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.character.affinity import (
    _BEHAVIOR_DELTA,
    DynamicAffinityStore,
)
from plugins.bot_unified_runtime.domains.chat_reply import affinity_replay as ar


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ------------------------------------------------------------ 1. 政策差额层


def test_refuse_event_old_insult_new_zero_diff_ten_points() -> None:
    """误扣机制钉死：refuse 旧=insult(-10 分) 新=refusal(0) → 差额 +10 分。

    一晚 40+ 分事故 = 4 条 refuse × 10 分（旧时代无预算钳制）的机制复现。
    """
    diff = ar.event_policy_diff("随便聊聊这个话题", safety_action="refuse")
    assert diff.old_behavior == "insult"
    assert diff.new_behavior == "refusal"
    assert diff.old_points == -10.0
    assert diff.new_points == 0.0
    assert diff.diff_points == 10.0
    assert diff.over_deducted


def test_non_relationship_reason_code_old_deducted_new_neutral() -> None:
    """非关系 reason_code：旧 policy 不消费该通道（照走正文启发式扣分），
    新 policy 零计分——引用辱骂/授权测试都是同款误扣证据。"""
    for reason in ("quoted_abuse", "authorized_test", "provider_error"):
        text = "你就是个蠢货" if reason != "provider_error" else "谢谢你陪我"
        diff = ar.event_policy_diff(text, reason_code=reason)
        assert diff.new_points == 0.0, (reason, diff)
        if reason == "provider_error":
            # 旧判 positive(+2) vs 新 0：差额 -2（旧更大方）——绝不倒扣回来。
            assert diff.diff_points == -2.0
            assert not diff.over_deducted
        else:
            assert diff.old_behavior == "insult"
            assert diff.diff_points == 10.0
            assert diff.over_deducted


def test_allow_plain_event_policy_invariant() -> None:
    """allow 普通事件两代判定一致 → 零差额（本轮政策变更不触及）。"""
    diff = ar.event_policy_diff("你就是个蠢货")
    assert diff.old_behavior == diff.new_behavior == "insult"
    assert diff.diff_points == 0.0
    assert not diff.over_deducted


def test_behavior_delta_points_single_source_with_drift_lock() -> None:
    """分口径 = _BEHAVIOR_DELTA ×100（唯一换算口）；表值漂移即测试红。"""
    assert _BEHAVIOR_DELTA["insult"] == pytest.approx(-0.10)
    assert ar.behavior_delta_points("insult") == pytest.approx(-10.0)
    assert ar.behavior_delta_points("negative") == pytest.approx(-5.0)
    assert ar.behavior_delta_points("positive") == pytest.approx(2.0)
    assert ar.behavior_delta_points("refusal") == 0.0  # 表外行为=0（新语义零计分）
    assert ar.behavior_delta_points("不存在的行为") == 0.0


# ------------------------------------------------------------ 2. 账本重放层


def _event(
    *,
    event_id: str = "rowid-1",
    sender: str = "1001",
    bot: str = "",
    applied_at: float = 1_700_000_100.0,
    applied_delta: float = -0.01,
    source: str = "",
    source_event_id: str = "",
) -> ar.LedgerEvent:
    return ar.LedgerEvent(
        event_id=event_id,
        sender_id=sender,
        bot_id=bot,
        applied_at=applied_at,
        applied_delta=applied_delta,
        source=source,
        source_event_id=source_event_id,
    )


def test_replay_verified_poke_family_is_policy_invariant() -> None:
    """poke=唯一已验证族：覆写路径不经判定层 → 旧新一致零差额。"""
    verdicts = ar.replay_ledger([_event(source="poke", applied_delta=0.001)])
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.verdict == ar.VERDICT_POLICY_INVARIANT
    assert verdict.diff_points == 0.0
    assert verdict.evidence_kind == "source_family:poke"


def test_replay_sourceless_rows_are_unknown_not_guessed() -> None:
    """source 空的被动感知行：旧判/新判/差额一律 None（不猜），不计补偿。"""
    verdicts = ar.replay_ledger(
        [_event(applied_delta=-0.01), _event(applied_delta=0.02, event_id="rowid-2")]
    )
    for verdict in verdicts:
        assert verdict.verdict == ar.VERDICT_UNKNOWN
        assert verdict.old_behavior is None
        assert verdict.new_behavior is None
        assert verdict.diff_points is None
        assert verdict.evidence_kind == "insufficient_classification_evidence"


def test_replay_custom_family_over_deduction_flows_to_verdict() -> None:
    """注入一个「旧扣新零」的已验证族（模拟未来事件服务证据形态）：
    重放产出 over_deducted 判定，差额=10 分/条。"""
    families = {
        "legacy_event": ar.SourceFamily(
            old_behavior="insult",
            new_behavior="refusal",
            note="测试族：旧 refuse→insult 语义下落的已验证事件形态",
        )
    }
    verdicts = ar.replay_ledger(
        [_event(source="legacy_event", applied_delta=-0.01)], source_families=families
    )
    assert verdicts[0].verdict == ar.VERDICT_OVER_DEDUCTED
    assert verdicts[0].diff_points == pytest.approx(10.0)


# ------------------------------------------------------------ 3. 只读保证


def _build_store_db(db_path: Path) -> None:
    """用真实 store 建库+落两笔（与生产 schema 同构；全离线 tmp_path）。"""
    clock = _Clock()
    store = DynamicAffinityStore(db_path, clock=clock)
    store.observe("1001", "positive", text="谢谢你陪我")  # 被动行 source=''
    clock.advance(3600.0)
    store.observe_points("1001", points=0.5, behavior="positive", source="poke")
    connection = sqlite3.connect(db_path)
    rows = connection.execute("SELECT COUNT(*) FROM affinity_delta_log").fetchone()[0]
    connection.close()
    assert rows == 2


def test_engine_connection_is_readonly(tmp_path: Path) -> None:
    """引擎唯一入库方式 mode=ro：写操作必须被 SQLite 拒绝。"""
    db_path = tmp_path / "aff.sqlite3"
    _build_store_db(db_path)
    connection = ar.open_readonly_connection(db_path)
    with pytest.raises(sqlite3.OperationalError):
        connection.execute(
            "INSERT INTO affinity_delta_log (sender_id, bot_id, applied_at, delta,"
            " source, source_event_id) VALUES ('9999', '', 0, 0, '', '')"
        )
    connection.close()


def test_full_replay_leaves_db_bytes_unchanged(tmp_path: Path) -> None:
    """全流程（重放+计数证据+报告渲染）跑完，库文件字节级不变。"""
    db_path = tmp_path / "aff.sqlite3"
    _build_store_db(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    connection = ar.open_readonly_connection(db_path)
    try:
        result = ar.run_replay(connection)
        report = ar.build_text_report(result, db_label=str(db_path))
    finally:
        connection.close()
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert before == after
    assert "V21-AFFINITY-002" in report


def test_missing_tables_raise_clear_schema_error(tmp_path: Path) -> None:
    """早于 V2.1 §2.3 的库没有账本表 → 明确报错（不静默当作空账）。"""
    db_path = tmp_path / "ancient.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE other (x INTEGER)")
    connection.commit()
    wrapper = ar.open_readonly_connection(db_path)
    with pytest.raises(ar.LedgerSchemaError):
        ar.load_ledger_events(wrapper)
    wrapper.close()
    connection.close()


# ------------------------------------------------------------ 4. 补偿提案层


def _over_deducted_verdicts(count: int, *, sender: str = "1001") -> list[ar.ReplayVerdict]:
    families = {
        "legacy_event": ar.SourceFamily(
            old_behavior="insult", new_behavior="refusal", note="测试族"
        )
    }
    events = [
        _event(
            event_id=f"rowid-{index}",
            sender=sender,
            applied_at=1_700_000_000.0 + index * 3600.0,
            applied_delta=-0.01,
            source="legacy_event",
        )
        for index in range(1, count + 1)
    ]
    return list(ar.replay_ledger(events, source_families=families))


def test_proposals_named_aggregation_with_evidence() -> None:
    """已证多扣 → 具名提案：用户/金额/依据事件数/证据指针齐全。"""
    proposals, duplicates = ar.build_compensation_proposals(
        _over_deducted_verdicts(4)
    )
    assert duplicates == []
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.sender_id == "1001"
    assert proposal.total_points == pytest.approx(40.0)  # 4 × 10 分
    assert proposal.event_count == 4
    assert len(proposal.event_ids) == 4
    assert "delta_log" in proposal.basis


def test_unknown_and_invariant_structurally_excluded_from_proposals() -> None:
    """unknown / 零差额事件不存在混入提案的路径（无证据不猜的结构保证）。"""
    verdicts = ar.replay_ledger(
        [
            _event(applied_delta=-0.01, source=""),  # unknown
            _event(applied_delta=0.001, source="poke", event_id="rowid-9"),  # 零差额
        ]
    )
    proposals, duplicates = ar.build_compensation_proposals(verdicts)
    assert proposals == []
    assert duplicates == []


def test_fingerprint_stable_for_same_set_and_distinct_for_different_sets() -> None:
    base = _over_deducted_verdicts(3)
    events_a = [v.event for v in base]
    events_b = [v.event for v in _over_deducted_verdicts(3)]
    assert ar.compensation_fingerprint(events_a) == ar.compensation_fingerprint(events_b)
    changed = list(events_a)
    changed[0] = ar.LedgerEvent(
        event_id=changed[0].event_id,
        sender_id=changed[0].sender_id,
        bot_id=changed[0].bot_id,
        applied_at=changed[0].applied_at + 0.5,  # 任何字段不同 → 指纹必不同
        applied_delta=changed[0].applied_delta,
        source=changed[0].source,
        source_event_id=changed[0].source_event_id,
    )
    assert ar.compensation_fingerprint(changed) != ar.compensation_fingerprint(events_a)
    assert ar.compensation_fingerprint(events_a).startswith("affcomp-v1:")


def test_duplicate_fingerprints_not_recounted() -> None:
    """幂等：指纹已登记 → 提案进 duplicates，不重复计总量。"""
    verdicts = _over_deducted_verdicts(3)
    first, dup_first = ar.build_compensation_proposals(verdicts)
    assert len(first) == 1 and dup_first == []
    known = {first[0].fingerprint}
    second, dup_second = ar.build_compensation_proposals(verdicts, known_fingerprints=known)
    assert second == []  # 新补偿总量为零
    assert len(dup_second) == 1
    assert dup_second[0].fingerprint == first[0].fingerprint
    assert dup_second[0].total_points == pytest.approx(30.0)


def test_registry_entry_roundtrip() -> None:
    proposals, _ = ar.build_compensation_proposals(_over_deducted_verdicts(2))
    entry = proposals[0].to_registry_entry(generated_at="2026-09-18T00:00:00Z")
    known = ar.parse_known_fingerprints([entry, {"fingerprint": None}, "junk", 42])
    assert proposals[0].fingerprint in known
    assert len(known) == 1
    _, duplicates = ar.build_compensation_proposals(
        _over_deducted_verdicts(2), known_fingerprints=known
    )
    assert len(duplicates) == 1


# ------------------------------------------------------------ 5. 报告与汇总


def test_replay_result_summary_and_report_honesty(tmp_path: Path) -> None:
    db_path = tmp_path / "aff.sqlite3"
    _build_store_db(db_path)
    connection = ar.open_readonly_connection(db_path)
    try:
        result = ar.run_replay(connection)
    finally:
        connection.close()
    counts = result.verdict_counts()
    # store 落的两行：positive 被动行（source=''→unknown）+ poke 行（零差额）
    assert counts.get(ar.VERDICT_UNKNOWN, 0) == 1
    assert counts.get(ar.VERDICT_POLICY_INVARIANT, 0) == 1
    assert result.proven_over_deduction_points() == 0.0
    # 聚合证据指针：positive 用户无负向计数 → 不进表
    assert result.counters == ()
    proposals, _ = ar.build_compensation_proposals(result.verdicts)
    report = ar.build_text_report(
        result,
        db_label=str(db_path),
        proposals=proposals,
        duplicates=[],
    )
    assert "零提案" in report  # 无证据 → 明说零提案，不美化
    assert "不构成补偿依据" in report
    assert "手工补偿规程" in report
    assert "unknown" in report


def test_counter_evidence_named_readonly(tmp_path: Path) -> None:
    """insult/negative 计数用户进证据指针表（具名，含口无遮拦打标时间）。"""
    db_path = tmp_path / "aff.sqlite3"
    clock = _Clock()
    store = DynamicAffinityStore(db_path, clock=clock)
    store.observe("2002", "insult", text="闭嘴")
    connection = ar.open_readonly_connection(db_path)
    try:
        counters = ar.load_counter_evidence(connection)
    finally:
        connection.close()
    assert len(counters) == 1
    counter = counters[0]
    assert counter.sender_id == "2002"
    assert counter.insult_count == 1
    assert counter.last_insult_at != ""
    assert isinstance(counter.affinity_points, float)  # 分口径（内部值×100）


def test_report_event_listing_includes_unknown_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "aff.sqlite3"
    _build_store_db(db_path)
    connection = ar.open_readonly_connection(db_path)
    try:
        result = ar.run_replay(connection)
    finally:
        connection.close()
    report = ar.build_text_report(result, db_label=str(db_path))
    assert "| rowid-" in report  # 逐事件清单带稳定事件 id
    assert "48h prune" in report  # 账本滚动窗口径写明


def test_time_format_is_utc_iso() -> None:
    assert ar._fmt_utc(0.0) == "1970-01-01T00:00:00Z"
    assert ar._fmt_utc(1_700_000_000.0) == time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(1_700_000_000.0)
    )


def test_registry_json_shape_for_script(tmp_path: Path) -> None:
    """脚本登记表读写形状（纯 JSON，引擎层不碰文件——此处只验数据形状）。"""
    proposals, _ = ar.build_compensation_proposals(_over_deducted_verdicts(1))
    entry = proposals[0].to_registry_entry(generated_at="t")
    payload = json.dumps({"entries": [entry]}, ensure_ascii=False)
    assert "fingerprint" in payload and "total_points" in payload
