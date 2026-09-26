"""S35 · creation 在途任务真身 ``domains/creation/_common/job_store.py`` 的离线回归。

立锁理由（简报 R-2 那一枚洞）：绘画在途分支与 ``GET /api/v1/tts/jobs/{id}`` 今天只能给
DEGRADED/503，因为**没有 job store／reconcile 真身**，handle 拿不出真终态。本件是那枚
真身的回归——**全部走真 SQLite**（``tmp_path`` 落盘），因为本仓为「只用 fake 断言字段
存在」付过两次账：紧急域那枚 ``nmc:A1`` 幂等键 Critical 是**静态可达性锁全绿、端到端
job 用例第一次跑才炸出来**的。fake 会跟着实现一起错，SQLite 不会替谁圆。

一处自证（写给自己，也写给下一个 AI）：本席第一版把「坏行跳过」的取列写在 try
**外面**（行读不出键时 ``TypeError`` 直接上抛）——那正是「一行脏数据带走整轮」的原始
病灶，只是换了个位置。是 ``test_row_without_keyed_access_is_a_bad_row_not_a_crash``
在真库上拿掉 ``row_factory`` 才逼出来的。教训：**测读侧健壮性必须造脏数据，不能只测
干净往返。**

纪律：零网络、零 bot 进程、零 config 读取；SQLite 一律 ``tmp_path``（台账 #1 卫生规矩）。
注毒五发逐发验牙：段委托 / 状态 CHECK / 幂等唯一索引 / 并发守卫 / prune 只裁已终态。
"""

from __future__ import annotations

import ast
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_provider
from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation._common import job_store as js
from plugins.bot_unified_runtime.domains.emergency_info.service import dedupe

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STORE_FILE = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "creation"
    / "_common"
    / "job_store.py"
)

_T0 = datetime(2026, 9, 24, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 9, 24, 0, 5, 0, tzinfo=timezone.utc)
_KEY_A = "a" * 64
_KEY_B = "b" * 64
_TTS = "creation.tts"
_IMAGE = "creation.image"
_COLUMNS = (
    "job_id, channel, state, workspace_id, provider_operation, idempotency_key, "
    "error_code, cancel_requested, cancel_requested_at, created_at, updated_at, "
    "assets_json, usage_json"
)


# ---------------------------------------------------------------------------
# 夹具：真 SQLite + 注入开口（开口纪律见 job_store 模块头「一处刻意的分层」）
# ---------------------------------------------------------------------------


class _CountingConnection:
    """把「打开/提交/关闭」记成计数，句柄泄漏无处藏。"""

    def __init__(self, inner: sqlite3.Connection, owner: _Harness) -> None:
        self._inner = inner
        self._owner = owner
        owner.opens += 1

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        return self._inner.execute(sql, parameters)

    def executescript(self, script: str) -> Any:
        return self._inner.executescript(script)

    def commit(self) -> None:
        self._owner.commits += 1
        self._inner.commit()

    def close(self) -> None:
        self._owner.closes += 1
        self._inner.close()


class _Harness:
    """一个临时库文件 + 可派生多个 store 实例（实例之间必须互相看得见）。"""

    def __init__(self, tmp_path: Path, *, row_factory: bool = True) -> None:
        self.path = tmp_path / "creation_jobs.sqlite3"
        self._row_factory = row_factory
        self.opens = 0
        self.closes = 0
        self.commits = 0

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10)
        if self._row_factory:
            connection.row_factory = sqlite3.Row
        return connection

    def counted(self) -> _CountingConnection:
        return _CountingConnection(self.connect(), self)

    def store(self, *, now: datetime = _T0, counted: bool = False) -> js.CreationJobStore:
        opener: Any = self.counted if counted else self.connect
        return js.CreationJobStore(opener, now=lambda: now)


@pytest.fixture()
def harness(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


@pytest.fixture()
def store(harness: _Harness) -> js.CreationJobStore:
    instance = harness.store(counted=True)
    instance.ensure_schema()
    return instance


def _job(
    job_id: str = "job-1",
    *,
    state: common.CreationJobState = common.CreationJobState.PENDING,
    key: str | None = None,
    at: datetime = _T0,
    **overrides: Any,
) -> common.CreationJob:
    payload: dict[str, Any] = {"job_id": job_id, "state": state, "updated_at": at}
    if key is not None:
        payload["idempotency_key"] = key
    payload.update(overrides)
    return common.CreationJob(**payload)


def _asset(asset_id: str = "asset-1") -> common.AssetRef:
    return common.AssetRef(asset_id=asset_id)


def _usage() -> tuple[common.UsageLine, ...]:
    return (
        common.UsageLine(
            metric="characters", value=Decimal(7), unit="characters", status="measured"
        ),
    )


def _put(
    store: js.CreationJobStore, job: common.CreationJob, **kwargs: Any
) -> js.RegisterOutcome:
    return store.register(job, channel=kwargs.pop("channel", _TTS), **kwargs)


def _plant(harness: _Harness, **overrides: Any) -> None:
    """绕过本件写一行（造坏行/造旧行用；合法行也走这条路，确保测的是读侧与 SQL 侧）。"""
    row: dict[str, Any] = {
        "job_id": "raw-1",
        "channel": _TTS,
        "state": "pending",
        "workspace_id": "",
        "provider_operation": None,
        "idempotency_key": None,
        "error_code": None,
        "cancel_requested": 0,
        "cancel_requested_at": None,
        "created_at": _T0.isoformat(),
        "updated_at": _T0.isoformat(),
        "assets_json": "[]",
        "usage_json": "[]",
    }
    row.update(overrides)
    connection = harness.connect()
    try:
        connection.execute(
            f"INSERT INTO {js.JOB_TABLE} ({', '.join(row)})"
            f" VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
        connection.commit()
    finally:
        connection.close()


def _raw_delete(harness: _Harness, sql: str, params: tuple[Any, ...]) -> int:
    """旁路 SQL（只做反例/self-proof 用，永不由本件公开）。"""
    connection = harness.connect()
    try:
        cursor = connection.execute(sql, params)
        connection.commit()
        return int(cursor.rowcount)
    finally:
        connection.close()


def _all_ids(harness: _Harness) -> set[str]:
    connection = harness.connect()
    try:
        rows = connection.execute(f"SELECT job_id FROM {js.JOB_TABLE}").fetchall()
    finally:
        connection.close()
    return {str(row["job_id"]) for row in rows}


def _tree() -> ast.Module:
    return ast.parse(_STORE_FILE.read_text(encoding="utf-8"))


def _imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# ---------------------------------------------------------------------------
# 1) 分层纪律：本域受 §9.4 契约形态 lint 约束，本件不偷渡、不去改那把门
# ---------------------------------------------------------------------------


def test_store_does_not_smuggle_forbidden_roots_into_creation_domain() -> None:
    """真身住 ``domains/creation/`` ⇒ §9.4 禁令生效：不得 import sqlite3/os/pathlib。

    刻意**不去改常驻门**换取「域内直连 sqlite」——那是把域隔离判据悄悄放宽。
    连接开口交装配层注入，而提交/关闭的纪律留在本件（见下方三把句柄锁）。
    本席也不用 ``importlib`` 偷渡——那是绕门，不是分层。
    """
    roots = _imported_roots(_tree())
    for forbidden in ("sqlite3", "os", "pathlib", "hashlib", "threading", "subprocess"):
        assert forbidden not in roots, f"job_store 偷渡了 {forbidden}（域内禁令）"


def test_store_delegates_segment_rule_instead_of_copying_it() -> None:
    """键规范唯一家 = ``dedupe``：本件委托它，且不得再抄一份字符集字面量。"""
    text = _STORE_FILE.read_text(encoding="utf-8")
    assert "is_legal_segment" in text, "不再委托中央段规则＝自立第二套键规范"
    strays = [
        node.value
        for node in ast.walk(_tree())
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "A-Za-z0-9_" in node.value
    ]
    assert not strays, f"段字符集出现第二处手抄（改一处必漏一处）：{strays}"


def test_store_declares_no_second_state_machine_or_job_record() -> None:
    """本席交付面的自锁（与既有全域门同向）：不再定义 ``*JobState``/``CreationJob``。"""
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ClassDef):
            assert not node.name.endswith("JobState"), f"第二具状态机：{node.name}"
            assert node.name not in {"CreationJob", "CapabilityResult", "InvocationResult"}, (
                f"冒名契约/中央信封类：{node.name}"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in {
                "creation_result",
                "capability_invoker_error",
            }, f"手抄了中央 data 保留键：{node.value!r}"


# ---------------------------------------------------------------------------
# 2) 派生自契约：状态与通道都不许是第二份名单
# ---------------------------------------------------------------------------


def test_state_check_sql_is_derived_from_contract_enum() -> None:
    """CHECK 清单 == 契约 ``JOB_STATES``：少一枚＝合法态进不了库，多一枚＝第二套词表。"""
    assert js.JOB_STATES == {state.value for state in common.CreationJobState}
    for state in js.JOB_STATES:
        assert f"'{state}'" in js.STATE_CHECK_SQL, f"状态 {state} 没进建表 CHECK"
    assert js.STATE_CHECK_SQL.count("'") == 2 * len(js.JOB_STATES), "CHECK 名单长度漂移"
    assert "teleported" not in js.STATE_CHECK_SQL


def test_channel_check_sql_is_derived_from_reserved_channel_ids() -> None:
    """通道清单派生自本域在册清单（不另立前缀表，否则又是一处第二真身）。"""
    assert set(reserved_provider.CHANNEL_IDS) == {_TTS, _IMAGE}
    for channel in reserved_provider.CHANNEL_IDS:
        assert f"'{channel}'" in js.CHANNEL_CHECK_SQL


def test_schema_builder_is_the_only_sql_and_is_stable() -> None:
    """SQL 只此一份（``job_store_schema_sql`` 是别名口，不是第二处脚本）。"""
    assert js.job_store_schema_sql() == js.build_job_store_schema()
    text = js.job_store_schema_sql()
    assert text.count(f"CREATE TABLE IF NOT EXISTS {js.JOB_TABLE}") == 1
    assert "idx_creation_jobs_idempotency" in text


def test_schema_creation_is_idempotent(harness: _Harness) -> None:
    instance = harness.store()
    instance.ensure_schema()
    instance.ensure_schema()  # 第二次不得抛（IF NOT EXISTS 三处齐）
    _put(instance, _job("twice-1"))
    assert instance.get("twice-1") is not None


# ---------------------------------------------------------------------------
# 3) 写入三道门：坏形态**当场点名**，绝不洗成能用的样子
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    ["nmc:A1", "job 1", "job\t1", "   ", "job/1", "中文任务", "job:1:2"],
    ids=["colon", "space", "tab", "blank", "slash", "cjk", "double-colon"],
)
def test_illegal_job_id_is_refused_by_name(
    harness: _Harness, store: js.CreationJobStore, bad_id: str
) -> None:
    """``nmc:A1`` 就是紧急域那枚 Critical 的原形：写侧必须当场拒，不是投递时才炸。"""
    with pytest.raises(js.JobStoreError, match="job_id"):
        _put(store, _job(bad_id))
    assert _all_ids(harness) == set(), "被拒的写入留下了半行"


def test_identifier_length_cap_matches_the_contract() -> None:
    """长度这一道**契约先挡**（``job_id`` max_length=128），本件只留同值余量。

    刻意不为「超长」再写一条写入用例：那样只会测到 pydantic，看起来是本件的功劳。
    两把尺必须同值，否则就是本件在契约之外偷偷放宽/收紧了身份口径。
    """
    contract_cap = common.CreationJob.model_fields["job_id"].metadata
    limits = [item.max_length for item in contract_cap if hasattr(item, "max_length")]
    assert limits == [js._IDENTIFIER_MAX_CHARS], (
        f"本件长度上限与契约 job_id 上限分叉：契约 {limits} vs 本件 "
        f"{js._IDENTIFIER_MAX_CHARS}"
    )


def test_illegal_provider_operation_is_refused(store: js.CreationJobStore) -> None:
    with pytest.raises(js.JobStoreError, match="provider_operation"):
        _put(store, _job("job-1", provider_operation="op:7"))


def test_legal_identifiers_pass(store: js.CreationJobStore) -> None:
    assert _put(store, _job("op-7.1_A", provider_operation="op-7.1_A")).created is True


def test_unknown_channel_is_refused(store: js.CreationJobStore) -> None:
    with pytest.raises(js.JobStoreError, match="通道"):
        store.register(_job(), channel="creation.fax")


def test_illegal_id_delegation_poison(
    harness: _Harness, store: js.CreationJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒①：把中央段规则换成「永远合法」⇒ 本件的拒绝必须**一起消失**。

    验的是「判据真的走中央件」：若本件私下复制了一份正则，注毒后它照样拒 ⇒ 本格必红。
    两半都断：未注毒必拒、注毒后必收（缺一半就是空跑）。
    """
    with pytest.raises(js.JobStoreError, match="非法段字符"):
        _put(store, _job("nmc:A1"))
    assert _all_ids(harness) == set()
    monkeypatch.setattr(js, "is_legal_segment", lambda _value: True)
    assert js.is_legal_job_identifier("nmc:A1") is True
    assert _put(store, _job("nmc:A1")).created is True
    assert "nmc:A1" in _all_ids(harness)


def test_digest64_is_always_a_legal_segment() -> None:
    """两枚事故的共同根因是「各家自定形态」：契约摘要形态 ⊂ 中央合法段字符集。"""
    for digest in (_KEY_A, _KEY_B, "0123456789abcdef" * 4, "f" * 64):
        assert js.is_legal_job_identifier(digest) is True
        assert dedupe.is_legal_segment(digest) is True


def test_illegal_idempotency_shape_rejected_by_contract() -> None:
    with pytest.raises(pydantic.ValidationError):
        _job("job-1", key="not-a-digest")


# ---------------------------------------------------------------------------
# 4) 幂等：同一请求身份只允许一条任务（UNKNOWN_NEVER_AUTO_REDISPATCH 的落点）
# ---------------------------------------------------------------------------


def test_duplicate_job_id_does_not_overwrite(store: js.CreationJobStore) -> None:
    assert _put(store, _job("job-1", key=_KEY_A)).created is True
    second = _put(store, _job("job-1", state=common.CreationJobState.FAILED, key=_KEY_B))
    assert second.created is False
    read = store.get("job-1")
    assert read is not None and read.state is common.CreationJobState.PENDING, "重复即覆盖"


def test_same_idempotency_key_names_the_existing_job(store: js.CreationJobStore) -> None:
    """核心格：重发方问「这条请求有没有过任务」，必须问得出**那一条的 id**。"""
    assert _put(store, _job("first-job", key=_KEY_A)).created is True
    outcome = _put(store, _job("second-job", key=_KEY_A))
    assert outcome.created is False
    assert outcome.existing_job_id == "first-job"
    found = store.find_by_idempotency_key(_KEY_A)
    assert found is not None and found.job_id == "first-job"
    assert store.get("second-job") is None, "撞键却另起一行＝重发没被拦住"


def test_idempotency_unique_index_poison(
    harness: _Harness, store: js.CreationJobStore
) -> None:
    """注毒②：绕过本件直接对库插两行同键 ⇒ 必须被**部分唯一索引**拦下。

    验的是「拦在库里」而不是「拦在 Python 里」：将来任何旁路写库都过不去同一道。
    """
    _plant(harness, job_id="p1", idempotency_key=_KEY_A)
    assert _plant_raises(harness, job_id="p2", idempotency_key=_KEY_A) is True
    # 反证不空跑：换一个键必须插得进去（否则上一格可能只是「表根本写不进」）。
    _plant(harness, job_id="p3", idempotency_key=_KEY_B)
    assert _all_ids(harness) == {"p1", "p3"}


def _plant_raises(harness: _Harness, **overrides: Any) -> bool:
    try:
        _plant(harness, **overrides)
    except sqlite3.IntegrityError:
        return True
    return False


def test_absent_idempotency_key_never_collides(store: js.CreationJobStore) -> None:
    """没给身份＝诚实「不去重」：两条无键任务必须**都能**登记（partial index 的边界）。"""
    assert _put(store, _job("no-key-1")).created is True
    assert _put(store, _job("no-key-2")).created is True


# ---------------------------------------------------------------------------
# 5) 读回与坏行点名（脏数据不许带走整轮）
# ---------------------------------------------------------------------------


def test_round_trip_preserves_contract_fields(store: js.CreationJobStore) -> None:
    job = _job(
        "job-rt",
        state=common.CreationJobState.SUCCEEDED,
        key=_KEY_A,
        at=_T1,
        assets=(_asset("a-1"), _asset("a-2")),
        usage=_usage(),
        provider_operation="op-9",
        cancel_requested=True,
        cancel_requested_at=_T1,
    )
    assert _put(store, job, workspace_id="ws-7").created is True
    read = store.get("job-rt")
    assert read == job, "读回的契约记录与写入不等值（字段被吞或被改）"
    record = store.get_record("job-rt")
    assert record is not None and record.channel == _TTS
    assert record.workspace_id == "ws-7"
    assert record.created_at is not None and record.created_at.tzinfo is not None


def test_missing_rows_read_as_none(store: js.CreationJobStore) -> None:
    assert store.get("nope") is None
    assert store.get_record("") is None
    assert store.find_by_idempotency_key(None) is None
    assert store.find_by_idempotency_key("坏:键") is None


@pytest.mark.parametrize(
    ("overrides", "expect_in_skips"),
    [
        ({"state": "succeeded", "assets_json": "[]"}, "ValidationError"),
        ({"state": "unknown", "idempotency_key": None}, "ValidationError"),
        ({"state": "pending", "assets_json": "not-json"}, "JSONDecodeError"),
        ({"state": "pending", "created_at": ""}, "ValueError"),
        ({"idempotency_key": "zzz"}, "ValidationError"),
        ({"error_code": "not_a_real_code"}, "ValueError"),
        ({"updated_at": "2026-09-24T00:00:00"}, "ValueError"),
        ({"usage_json": '[{"metric":"characters","value":7,"unit":"wrong"}]'}, "ValidationError"),
    ],
    ids=[
        "fake-success",
        "unknown-without-identity",
        "broken-json",
        "blank-time",
        "bad-digest",
        "ghost-error-code",
        "naive-time",
        "bad-usage-unit",
    ],
)
def test_corrupt_rows_are_named_and_skipped(
    harness: _Harness, store: js.CreationJobStore, overrides: dict[str, Any],
    expect_in_skips: str,
) -> None:
    """坏行：点名 + 跳过，**整轮不带走**（紧急域那枚 Critical 的正面教训）。

    这七型全是**能过 SQL CHECK、却过不了契约**的行——契约外的 state/channel 根本进不了
    库（那是另外一把锁，见 :func:`test_store_rejects_illegal_words_at_sql_level`）。
    """
    _plant(harness, **overrides)
    assert store.get("raw-1") is None, f"{overrides}：坏行被当成好行读回来了"
    assert _put(store, _job("good-1")).created is True
    jobs = store.list_non_terminal()
    assert [job.job_id for job in jobs] == ["good-1"], "坏行带走了整轮"
    assert any(
        label == "raw-1" and reason == expect_in_skips for label, reason in store.recent_skips()
    ), f"坏行没被点名成 {expect_in_skips}：{store.recent_skips()}"


def test_illegal_id_row_does_not_take_down_the_round(
    harness: _Harness, store: js.CreationJobStore
) -> None:
    """库里已有一行 job_id 含冒号（旁路写入留下的）⇒ 扫描照常返回其余行。"""
    _plant(harness, job_id="nmc:A1")
    _plant(harness, job_id="nmc-A2")  # 同族合法形态（`-` 连接符，紧急域定案）
    assert store.get("nmc:A1") is None
    assert store.get("nmc-A2") is not None
    assert [job.job_id for job in store.list_non_terminal()] == ["nmc-A2"]
    assert ("nmc:A1", "illegal_segment") in store.recent_skips()


def test_row_without_keyed_access_is_a_bad_row_not_a_crash(tmp_path: Path) -> None:
    """connect 忘了配 row_factory ⇒ 行是元组：读侧点名跳过，**绝不**抛穿调用方的整轮。"""
    harness = _Harness(tmp_path, row_factory=False)
    keyed = harness.store()
    keyed.ensure_schema()
    assert keyed.register(_job("row-factory-1"), channel=_TTS).created is True
    unkeyed = harness.store()
    assert unkeyed.get("row-factory-1") is None
    assert unkeyed.list_non_terminal() == []
    assert any(
        reason == "TypeError" for _, reason in unkeyed.recent_skips()
    ), f"没点名成坏行：{unkeyed.recent_skips()}"


def test_scan_caps_are_honest(
    store: js.CreationJobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非正 limit 绝不退化成全表扫描；上限是真的在生效（注毒式：改小上限必见变化）。"""
    for index in range(7):
        assert _put(store, _job(f"cap-{index}")).created is True
    assert store.list_non_terminal(limit=0) == []
    assert store.list_non_terminal(limit=-5) == []
    assert len(store.list_non_terminal(limit=5)) == 5
    monkeypatch.setattr(js, "MAX_LIST_LIMIT", 3)
    assert len(store.list_non_terminal(limit=10_000)) == 3


def test_channel_filter_and_unknown_channel(store: js.CreationJobStore) -> None:
    _put(store, _job("tts-1"), channel=_TTS)
    _put(store, _job("img-1"), channel=_IMAGE)
    assert [job.job_id for job in store.list_non_terminal(channel=_IMAGE)] == ["img-1"]
    assert [job.job_id for job in store.list_non_terminal()] == ["img-1", "tts-1"]
    with pytest.raises(js.JobStoreError, match="通道"):
        store.list_non_terminal(channel="creation.fax")


def test_state_counts_cover_whole_contract_enum(store: js.CreationJobStore) -> None:
    _put(store, _job("c-1"))
    _put(store, _job("c-2", state=common.CreationJobState.SUCCEEDED, assets=(_asset(),)))
    counts = store.state_counts()
    assert set(counts) == js.JOB_STATES, "计数面漏档＝回读时那一档永远看不见"
    assert counts["pending"] == 1 and counts["succeeded"] == 1 and counts["cancelled"] == 0


def test_terminal_scan_is_the_complement(store: js.CreationJobStore) -> None:
    _put(store, _job("live-1", state=common.CreationJobState.RUNNING))
    _put(store, _job("done-1", state=common.CreationJobState.CANCELLED))
    live = [job.job_id for job in store.list_non_terminal()]
    done = [job.job_id for job in store.list_terminal()]
    assert live == ["live-1"] and done == ["done-1"]
    assert set(live).isdisjoint(done), "两半有交集＝对账会重复处理同一条"


# ---------------------------------------------------------------------------
# 6) 状态机：迁移问契约，守卫写进 SQL
# ---------------------------------------------------------------------------


def test_legal_transition_moves_and_is_durable(store: js.CreationJobStore) -> None:
    _put(store, _job("adv-1", state=common.CreationJobState.RUNNING))
    outcome = store.advance(
        "adv-1",
        common.CreationJobState.SUCCEEDED,
        assets=(_asset("done-1"),),
        usage=_usage(),
    )
    assert outcome.moved is True and outcome.state is common.CreationJobState.SUCCEEDED
    read = store.get("adv-1")
    assert read is not None and read.state is common.CreationJobState.SUCCEEDED
    assert store.list_terminal(channel=_TTS) and not store.list_non_terminal()


@pytest.mark.parametrize(
    ("start", "target", "extra"),
    [
        (common.CreationJobState.PENDING, common.CreationJobState.SUCCEEDED, {}),
        (common.CreationJobState.RUNNING, common.CreationJobState.PENDING, {}),
        (
            common.CreationJobState.SUCCEEDED,
            common.CreationJobState.RUNNING,
            {"assets": (_asset(),)},
        ),
        (
            common.CreationJobState.UNKNOWN,
            common.CreationJobState.RUNNING,
            {"key": _KEY_A},
        ),
    ],
    ids=["skip-admission", "rewind", "revive-terminal", "revive-unknown"],
)
def test_illegal_transitions_refused_with_reason(
    store: js.CreationJobStore,
    start: common.CreationJobState,
    target: common.CreationJobState,
    extra: dict[str, Any],
) -> None:
    _put(store, _job("bad-adv", state=start, **extra))
    outcome = store.advance("bad-adv", target, assets=(_asset(),), usage=_usage())
    assert outcome.moved is False and "非法迁移" in outcome.reason
    read = store.get("bad-adv")
    assert read is not None and read.state is start, "被拒的推进仍改写了库"


def test_advance_to_unknown_keeps_the_request_identity(store: js.CreationJobStore) -> None:
    """「未知不重发」要能用：unknown 落库仍带身份，读回后还查得到那一条。"""
    _put(store, _job("unk-1", state=common.CreationJobState.RUNNING, key=_KEY_A))
    outcome = store.advance(
        "unk-1", common.CreationJobState.UNKNOWN, error_code="dependency_unavailable"
    )
    assert outcome.moved is True
    read = store.get("unk-1")
    assert read is not None and read.state is common.CreationJobState.UNKNOWN
    assert read.idempotency_key == _KEY_A
    assert read.error_code == "dependency_unavailable"
    found = store.find_by_idempotency_key(_KEY_A)
    assert found is not None and found.job_id == "unk-1"


def test_non_terminal_advance_cannot_smuggle_assets(store: js.CreationJobStore) -> None:
    """未终态带产物＝契约当场拒（半程产物不对外，这条在**写路径**上真的被执行）。"""
    _put(store, _job("semi-1", state=common.CreationJobState.PENDING))
    with pytest.raises(pydantic.ValidationError, match="未终态"):
        store.advance("semi-1", common.CreationJobState.ADMITTED, assets=(_asset(),))
    read = store.get("semi-1")
    assert read is not None and read.state is common.CreationJobState.PENDING


def test_advance_rejects_non_enum_state(store: js.CreationJobStore) -> None:
    _put(store, _job("enum-1", state=common.CreationJobState.RUNNING))
    with pytest.raises(js.JobStoreError, match="契约枚举"):
        store.advance("enum-1", "succeeded")  # type: ignore[arg-type]
    with pytest.raises(js.JobStoreError, match="契约枚举"):
        store.advance(
            "enum-1",
            common.CreationJobState.SUCCEEDED,
            expected_state="running",  # type: ignore[arg-type]
        )


def test_advance_missing_row_is_honest(store: js.CreationJobStore) -> None:
    outcome = store.advance("ghost", common.CreationJobState.RUNNING)
    assert outcome.moved is False and "没有这条任务" in outcome.reason


def test_concurrency_guard_poison(store: js.CreationJobStore) -> None:
    """注毒③：过期的观察值必须被**并发守卫**挡，而不是被状态机顺手挡。

    本席第一版这格是**假绿**：loser 想走 succeeded→failed，状态机本来就判「非法迁移」，
    守卫一次都没单独跑过。现在让 loser 的请求**从库内实况看完全合法**
    （succeeded→succeeded 不合法，但它的观察值 running→succeeded 合法），
    唯一能挡住它的就只有「你看到的已经过期」这一道。
    """
    _put(store, _job("cas-1", state=common.CreationJobState.RUNNING))
    winner = store.advance(
        "cas-1",
        common.CreationJobState.SUCCEEDED,
        assets=(_asset("win"),),
        expected_state=common.CreationJobState.RUNNING,
    )
    loser = store.advance(
        "cas-1",
        common.CreationJobState.SUCCEEDED,
        assets=(_asset("lose"),),
        expected_state=common.CreationJobState.RUNNING,  # 同一份过期快照
    )
    assert winner.moved is True and loser.moved is False
    assert "并发抢先" in loser.reason, f"挡住 loser 的不是并发守卫：{loser.reason}"
    assert loser.state is common.CreationJobState.SUCCEEDED
    read = store.get("cas-1")
    assert read is not None and read.assets
    assert [asset.asset_id for asset in read.assets] == ["win"], "被拒的一方仍把库改了"


def test_concurrency_guard_accepts_a_fresh_snapshot(store: js.CreationJobStore) -> None:
    """反手不空跑：观察值与实况一致时，守卫必须放行（否则它就成了「谁都别想改」）。"""
    _put(store, _job("cas-2", state=common.CreationJobState.RUNNING))
    outcome = store.advance(
        "cas-2",
        common.CreationJobState.FAILED,
        error_code="price_unavailable",
        expected_state=common.CreationJobState.RUNNING,
    )
    assert outcome.moved is True
    read = store.get("cas-2")
    assert read is not None and read.state is common.CreationJobState.FAILED
    assert read.error_code == "price_unavailable"


def test_concurrent_stores_see_each_other(harness: _Harness) -> None:
    """跨实例 + 跨线程可见性（一次操作一条连接的直接后果：没有共享事务可藏写）。"""
    first = harness.store()
    first.ensure_schema()
    second = harness.store()
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            second.register(_job(f"t-{index}"), channel=_TTS)
        except BaseException as exc:  # noqa: BLE001 - 收集后统一断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"并发登记抛错：{errors}"
    ids = {job.job_id for job in first.list_non_terminal(limit=js.MAX_LIST_LIMIT)}
    assert ids == {f"t-{index}" for index in range(8)}, "跨实例写没被看见"


# ---------------------------------------------------------------------------
# 7) 取消只是标记（CANCEL_REQUESTED_IS_NOT_A_STATE）
# ---------------------------------------------------------------------------


def test_cancel_mark_never_changes_state(store: js.CreationJobStore) -> None:
    _put(store, _job("cx-1", state=common.CreationJobState.RUNNING))
    assert store.mark_cancel_requested("cx-1") is True
    read = store.get("cx-1")
    assert read is not None
    assert read.state is common.CreationJobState.RUNNING, "取消请求被写成了状态"
    assert read.cancel_requested is True
    assert read.cancel_requested_at is not None
    assert read.cancel_requested_at.tzinfo is not None


def test_cancel_flag_is_idempotent(store: js.CreationJobStore) -> None:
    """第二次打标记返回 False，且**不覆盖**首次时刻（幂等，不是"每次都成功"的假象）。"""
    _put(store, _job("cx-2", state=common.CreationJobState.RUNNING))
    assert store.mark_cancel_requested("cx-2") is True
    first = store.get("cx-2")
    assert first is not None
    first_at = first.cancel_requested_at
    assert store.mark_cancel_requested("cx-2") is False
    second = store.get("cx-2")
    assert second is not None and second.cancel_requested_at == first_at, "时刻被改写了"


def test_cancel_can_follow_success(store: js.CreationJobStore) -> None:
    """先成功的任务也能补「曾请求取消」，且真产物不被抹掉（取消是事实不是状态）。"""
    _put(store, _job("cx-3", state=common.CreationJobState.RUNNING))
    store.advance("cx-3", common.CreationJobState.SUCCEEDED, assets=(_asset("real"),))
    assert store.mark_cancel_requested("cx-3") is True
    read = store.get("cx-3")
    assert read is not None
    assert read.state is common.CreationJobState.SUCCEEDED
    assert read.cancel_requested is True and read.assets, "补标记把真产物抹掉了"
    assert [asset.asset_id for asset in read.assets] == ["real"]


def test_cancel_missing_row_and_illegal_id(store: js.CreationJobStore) -> None:
    assert store.mark_cancel_requested("ghost") is False
    with pytest.raises(js.JobStoreError, match="job_id"):
        store.mark_cancel_requested("ghost:id")


# ---------------------------------------------------------------------------
# 8) prune：只裁已终态，在途与 unknown 结构性不裁
# ---------------------------------------------------------------------------


def _plant_old(harness: _Harness, job_id: str, state: str, *, days: int) -> None:
    moment = (_T0 - timedelta(days=days)).isoformat()
    _plant(
        harness, job_id=job_id, state=state, created_at=moment, updated_at=moment
    )


def test_prune_removes_old_terminal_only(
    harness: _Harness, store: js.CreationJobStore
) -> None:
    _plant_old(harness, "old-succeeded", "succeeded", days=200)
    _plant_old(harness, "old-failed", "failed", days=200)
    _plant_old(harness, "old-cancelled", "cancelled", days=200)
    _plant_old(harness, "old-pending", "pending", days=200)
    _plant_old(harness, "old-unknown", "unknown", days=200)
    _plant_old(harness, "fresh-succeeded", "succeeded", days=3)
    removed = store.prune(now=_T0)
    assert removed == 3, f"只该裁掉 3 条已终态，实裁 {removed}"
    assert _all_ids(harness) == {
        "old-pending",
        "old-unknown",
        "fresh-succeeded",
    }, "在途/unknown 被裁，或旧终态漏裁"


def test_prune_teeth_are_not_vacuous(harness: _Harness, store: js.CreationJobStore) -> None:
    """非空跑自证：**同一批数据**去掉状态过滤就会连在途一起删光。

    即上一格真能分辨对错，而不是数据碰巧删不到东西。反例走旁路 SQL，不改本件源码
    （不制造「测夹具替实现说话」的假绿）。
    """
    _plant_old(harness, "keep-inflight", "running", days=200)
    _plant_old(harness, "drop-done", "succeeded", days=200)
    cutoff = (_T0 - timedelta(days=js.DEFAULT_KEEP_DAYS)).isoformat()
    blind = _raw_delete(
        harness, f"DELETE FROM {js.JOB_TABLE} WHERE updated_at < ?", (cutoff,)
    )
    assert blind == 2, "反例没删掉在途行 ⇒ 数据造得不对，「只裁终态」那格是空跑"


def test_prune_honours_keep_days_and_clamps(
    harness: _Harness, store: js.CreationJobStore
) -> None:
    _plant_old(harness, "mid", "succeeded", days=45)
    assert store.prune(keep_days=90, now=_T0) == 0
    assert store.prune(keep_days=30, now=_T0) == 1
    assert _all_ids(harness) == set()
    _plant_old(harness, "yesterday", "succeeded", days=2)
    # keep_days<=0 钳到 1 天：不得变成「清空全库」的开关。
    assert store.prune(keep_days=0, now=_T0) == 1


def test_prune_on_empty_store_is_quiet(store: js.CreationJobStore) -> None:
    assert store.prune(now=_T0) == 0


def test_prune_does_not_eat_the_idempotency_ledger(
    harness: _Harness, store: js.CreationJobStore
) -> None:
    """unknown 是「不重发」的账本：老到 200 天也必须在，且幂等查询仍答得出来。"""
    _plant(
        harness,
        job_id="old-unk",
        state="unknown",
        idempotency_key=_KEY_A,
        created_at=(_T0 - timedelta(days=200)).isoformat(),
        updated_at=(_T0 - timedelta(days=200)).isoformat(),
    )
    assert store.prune(keep_days=1, now=_T0) == 0
    found = store.find_by_idempotency_key(_KEY_A)
    assert found is not None and found.job_id == "old-unk"


# ---------------------------------------------------------------------------
# 9) 句柄纪律（Windows 实症：库文件删不掉）
# ---------------------------------------------------------------------------


def test_every_operation_closes_and_commits(harness: _Harness) -> None:
    store = harness.store(counted=True)
    store.ensure_schema()
    _put(store, _job("h-1", state=common.CreationJobState.RUNNING, key=_KEY_A))
    store.get("h-1")
    store.list_non_terminal()
    store.state_counts()
    store.advance("h-1", common.CreationJobState.UNKNOWN, error_code="dependency_unavailable")
    store.mark_cancel_requested("h-1")
    store.prune(now=_T0)
    assert harness.opens == harness.closes, f"开 {harness.opens} / 关 {harness.closes}：泄漏"
    assert harness.commits == harness.opens, "每次开口都该有一次提交（含只读口）"
    assert harness.opens >= 8, f"操作数太少 ⇒ 这一格没真的跑到上面每一条：{harness.opens}"


def test_database_file_is_really_deletable(harness: _Harness) -> None:
    """Windows 上句柄没关 ⇒ unlink 直接 PermissionError。家规的**症状级**锁。"""
    store = harness.store(counted=True)
    store.ensure_schema()
    for index in range(12):
        _put(store, _job(f"dl-{index}"))
        store.get(f"dl-{index}")
        store.list_non_terminal()
    harness.path.unlink()
    assert not harness.path.exists()


def test_failing_operation_still_closes(harness: _Harness) -> None:
    """异常路径同样必关：SQL 报错（表不存在）上抛时，连接也必须已经关闭。"""
    orphan = js.CreationJobStore(harness.counted)
    before_open, before_close = harness.opens, harness.closes
    with pytest.raises(sqlite3.OperationalError):
        orphan.state_counts()
    assert harness.opens - before_open == harness.closes - before_close, "异常路径漏关句柄"
    assert harness.opens - before_open == 1


def test_bad_connection_shape_is_named_and_closed() -> None:
    """connect 给来的东西缺方法 ⇒ 点名缺什么，且不留句柄在外面。"""
    closed: list[str] = []

    class _Half:
        def execute(self, *args: Any, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            closed.append("closed")

    instance = js.CreationJobStore(_Half)
    with pytest.raises(js.JobStoreError, match="缺少必需方法"):
        instance.ensure_schema()
    assert closed == ["closed"], "开口不合格时也没关连接"


def test_non_callable_opener_is_refused_at_construction() -> None:
    with pytest.raises(js.JobStoreError, match="可调用"):
        js.CreationJobStore("not-a-factory")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 10) SQL 侧状态词自锁（注毒②的另一半）
# ---------------------------------------------------------------------------


def test_store_rejects_illegal_words_at_sql_level(harness: _Harness) -> None:
    """注毒②：Python 侧全被绕过时，库自己也收不下契约外的状态词与通道词。

    自证不空跑：随后插一枚**合法**行必须成功，否则这条 CHECK 可能是瞎的（或表没建）。

    如实的覆盖边界（写下来，别让它长成假账）：读侧 ``_row_to_record`` 里
    「state 不在枚举 / channel 不在册」两道分支**今天不可达**——SQL CHECK 比它们更严，
    脏词根本进不了库。它们是纵深防御（日后有人放宽 CHECK 时兜住），不是被测面。
    """
    store = harness.store()
    store.ensure_schema()
    assert _plant_raises(harness, job_id="check-1", state="teleported") is True
    assert _plant_raises(harness, job_id="check-3", channel="creation.fax") is True
    _plant(harness, job_id="check-2", state="pending")
    assert store.get("check-1") is None and store.get("check-3") is None
    assert store.get("check-2") is not None
    assert store.recent_skips() == (), "没进库的行不该被记成坏行（点名面必须准）"


def test_skip_audit_ring_is_bounded(harness: _Harness, store: js.CreationJobStore) -> None:
    """观测面自身不得变成新泄漏：坏行刷满三倍容量，环仍只留容量内的条数。"""
    rows = js.SKIP_AUDIT_CAPACITY * 3
    for index in range(rows):
        # 用「succeeded 却无产物」这一型：过得了 SQL CHECK，过不了契约（上面已钉）。
        _plant(harness, job_id=f"bad-{index}", state="succeeded", assets_json="[]")
    for index in range(rows):
        assert store.get(f"bad-{index}") is None
    skips = store.recent_skips()
    assert len(skips) == js.SKIP_AUDIT_CAPACITY, f"环没装满（或装多了）：{len(skips)}"
    assert {reason for _, reason in skips} == {"ValidationError"}


def test_store_never_rehashes_locally() -> None:
    """域内禁第二套摘要算法家（本席交付面的自锁，与全域门同向）。"""
    assert "hashlib" not in _imported_roots(_tree())
    text = _STORE_FILE.read_text(encoding="utf-8")
    assert ".sha256(" not in text
    assert "media_digest" not in text, "协议层直连中央 digest 件＝取数口越界"
