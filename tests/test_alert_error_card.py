"""运行时告警 → 完整诊断卡（2026-09-25，澜汐裁定「任何报错出来都需要给我完整的诊断卡」）。

判据来历：改前 `alerts.py` 全文零 `error_report` 引用——LLM 超时、协议端拒收这类
运行时告警只发一行文本，压根不出卡。本件锁的是「告警面也出卡、且卡与异常卡同形」。

覆盖面：
① issue 经 `build_issue_report` 出满 14 项要素（键集与 `build_error_report` 全等）；
② `exc_message` 里的 `sk-…` 与盘符路径必须被打码；
③ 渲染/投递抛异常 ⇒ 文本照发、卡不发、不向上抛（注毒式：让替身 raise）；
④ 冷却闸命中 ⇒ 不发第二张卡（沿用异常卡那本闸，不另立）；
⑤ 开关关 ⇒ 一次渲染都不调（替身调用数为 0）；
⑥ `timeout` / `retcode_failure` 各自的人话主句进 `human_text`，且自查那句带「推测」；
另加：真渲染分支的入队形状（假后端 + 同步池 + 桩队列，证明生产分支不是死码）、
「没有可投递面时不烧冷却闸」、告警链把 `pipeline` 透传到卡这一段的装配可达性锁。

全离线：不联网、不起真渲染（backend/card_dir 一律注入替身）、不读生产 `.env`
（开关断言走 `alerts._resolve_settings` 这个被测试代码真正调用的出口打桩）。
断言一律用 `in`，不把整行文本钉死（既有测试吃过这个亏）。
"""

from __future__ import annotations

import ast
import inspect
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.contracts import (
    IncomingMessage,
    OperationalIssue,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import alerts, error_report
from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
    ErrorCardGate,
    ErrorCardSettings,
    build_error_report,
    build_issue_report,
)

# 卡面上允许为空的三格：告警没有 traceback、没有"触发它的那句话"可回显，头像由
# 装配层另填（与 build_error_report 同口径）。除这三格外的要素必须有值。
_ALLOWED_EMPTY = frozenset({"stack_lines", "trigger_echo", "bot_avatar_url"})

_ELEMENTS = (
    "card_title",
    "exc_type",
    "exc_message",
    "human_text",
    "trigger_echo",
    "stack_lines",
    "method_pairs",
    "self_review_pairs",
    "contact_pairs",
    "config_pairs",
    "version_pairs",
    "env_pairs",
    "id_pairs",
    "help_text",
)


def _issue(
    *,
    stage: str = "llm",
    kind: str = "timeout",
    safe_summary: str = "network chain=17 last=axon-grok-46",
    attempts: int = 2,
    retryable: bool = True,
    elapsed_ms: float | None = 4210.5,
) -> OperationalIssue:
    return OperationalIssue(
        stage=stage,
        kind=kind,
        safe_summary=safe_summary,
        attempts=attempts,
        retryable=retryable,
        elapsed_ms=elapsed_ms,
    )


def _config_values(name: str) -> object:
    return {
        "bot_super_admin_user_ids": ["3865067623"],
        "bot_admin_profiles": {"3865067623": "澜汐"},
        "bot_error_card_enabled": True,
        "bot_error_card_cooldown_seconds": 60,
        "bot_quiet_hours_enabled": False,
        "bot_reminder_enabled": True,
        # 卡面署名 2026-09-28 起跟**生效人格**走（`_persona_signature` 的唯一入参就是
        # 这两枚装配层键）。此前替身 getter 没教它们 ⇒ 载荷 `bot_name` 恒空，撞在
        # 「除栈/回显/头像三格外不得为空」的要素契约上。回落规则只住在渲染侧
        # （`test_error_card_persona_identity` 执法），不许挪进载荷侧。
        # 值与生产 `.env` 同形（在册人格 + 兼容显示名），不在测试里另认名字真身。
        "bot_persona_profile_id": "shorekeeper",
        "bot_persona_display_name": "守岸人",
    }.get(name)


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text="/bot status",
        message_id="m-1",
    )


def _report(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "source_adapter": "onebot",
        "source_bot": "3958874605",
        "session_type": SessionType.GROUP,
        "headline": (
            "[守岸人告警] 私聊（发出账号 3958874605），我在想怎么回你这句话（模型那一跳）："
            "等回话等超时了。这条还能重试，你不用管。"
        ),
        "capability_id": "bot.chat",
        "config_getter": _config_values,
    }
    kwargs.update(overrides)
    return build_issue_report(_issue(), **kwargs)


class _CardSink:
    """`alerts.alert_card_sink` 的替身：只记账 + 按需抛异常（不碰渲染）。"""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._raises = raises

    def __call__(self, target: Any, report: dict[str, Any]) -> None:
        self.calls.append((target.identity, report))
        if self._raises is not None:
            raise self._raises

    @property
    def count(self) -> int:
        return len(self.calls)


def _target(*, scope: SessionType = SessionType.PRIVATE) -> alerts.AdminTarget:
    """目标号唯一：告警卡冷却走进程级共享闸，测试之间不能互踩。"""
    bot_id = f"bot-{uuid.uuid4().hex[:8]}"
    return alerts.AdminTarget(
        adapter="onebot",
        bot_id=bot_id,
        target_id=uuid.uuid4().hex[:10],
        target_scope=scope,
    )


async def _notify(
    target: alerts.AdminTarget,
    *,
    issue: OperationalIssue | None = None,
    suppression: alerts.AdminAlertSuppression | None = None,
    delivered: list[SendRequest],
    online_bots: dict[str, Any] | None = None,
) -> list[Any]:
    async def delivery(_t: Any, _b: Any, request: SendRequest) -> None:
        delivered.append(request)

    return await alerts.notify_operational_issue(
        issue or _issue(),
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        targets=[target],
        online_bots=(
            online_bots if online_bots is not None else {target.bot_id: object()}
        ),
        delivery=delivery,
        suppression=suppression or alerts.AdminAlertSuppression(),
    )


def _enabled(monkeypatch: pytest.MonkeyPatch, **settings: Any) -> None:
    monkeypatch.setattr(
        alerts,
        "_resolve_settings",
        lambda: ErrorCardSettings(**settings) if settings else ErrorCardSettings(True),
    )


# ==================== ① 载荷形状：14 项要素齐全 ====================
def test_issue_report_key_set_is_identical_to_error_report() -> None:
    """卡载荷唯一组装口：告警卡与异常卡同一套键（禁在 alerts 手搓 dict 的结构锁）。"""
    issue_report = _report()
    exception_report = build_error_report(
        _message(), "bot.chat", ValueError("boom"), config_getter=_config_values
    )
    assert set(issue_report) == set(exception_report)
    for element in _ELEMENTS:
        assert element in issue_report, element


def test_issue_report_fills_every_element_except_stack_and_echo() -> None:
    report = _report()
    for key, value in report.items():
        if key in _ALLOWED_EMPTY:
            continue
        assert value, f"{key} 不得为空"
    labels = {row["label"] for row in report["id_pairs"]}
    assert {"debug_id", "告警时刻", "会话", "发出账号"} <= labels
    assert report["exc_type"] == "llm/timeout"
    assert "chain=17" in report["exc_message"]
    assert report["card_title"] == "运行时告警"
    # ⑨报错原因归类：代号串也要有中文（按异常名写的老表对 `llm/timeout` 失灵）。
    reason = {row["label"]: row["value"] for row in report["method_pairs"]}["原因"]
    assert "超时" in reason


def test_issue_report_honours_include_env_false() -> None:
    assert _report(include_env=False)["version_pairs"] == []


# ==================== ② 脱敏 ====================
def test_issue_report_redacts_key_shapes_and_local_paths() -> None:
    leaked = (
        "upstream failed sk-abcdefghijklmnopqrstuvwxyz123456 "
        "db=C:/Users/LancyCelestia/Assistant/private.sqlite3"
    )
    report = build_issue_report(
        _issue(safe_summary=leaked),
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        headline="",
        config_getter=_config_values,
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in report["exc_message"]
    assert "C:/Users/LancyCelestia" not in report["exc_message"]
    assert "private.sqlite3" not in report["exc_message"]
    assert "已隐藏" in report["exc_message"]
    # 整张载荷（含纯文本兜底）也不许带出密钥原文与本机路径。
    blob = repr(report) + alerts.build_text_fallback(report)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in blob
    assert "LancyCelestia" not in blob


def test_issue_codes_are_sanitized_before_hitting_the_card() -> None:
    """kind 有运行期拼出来的形态（`blocked_<transport>` 一族）：上卡面前先洗。"""
    report = build_issue_report(
        _issue(stage="campus", kind="blocked_onebot sk-abcdefghijklmnopqrstuvwxyz123456"),
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        config_getter=_config_values,
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in report["exc_type"]
    assert " " not in report["exc_type"]


# ==================== ③ 渲染/投递失败：保住文本告警 ====================
@pytest.mark.asyncio
async def test_card_failure_keeps_text_alert_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒式：让替身 raise ⇒ 文本结果照样返回、卡不发、异常不外溢。"""
    sink = _CardSink(raises=RuntimeError("renderer exploded"))
    monkeypatch.setattr(alerts, "alert_card_sink", sink)
    _enabled(monkeypatch, enabled=True)
    target = _target()
    delivered: list[SendRequest] = []

    results = await _notify(target, delivered=delivered)

    assert results[0].success is True
    assert len(delivered) == 1
    assert delivered[0].content.content_type == "text"
    assert "运行时告警" in delivered[0].content.text_fallback
    # 替身确实被叫到（卡这一段真的走了），但它炸了也不改变上面的文本结果。
    assert sink.count == 1


@pytest.mark.asyncio
async def test_no_card_when_text_alert_itself_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本都没发出去（无在线账号）⇒ 不追卡。"""
    sink = _CardSink()
    monkeypatch.setattr(alerts, "alert_card_sink", sink)
    _enabled(monkeypatch, enabled=True)
    target = _target()
    delivered: list[SendRequest] = []

    results = await _notify(target, delivered=delivered, online_bots={})

    assert results[0].success is False
    assert results[0].error_kind == "bot_unavailable"
    assert sink.count == 0


# ==================== ④ 冷却闸：不发第二张卡 ====================
@pytest.mark.asyncio
async def test_error_card_gate_suppresses_second_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本抑制窗（300s）已过、卡冷却（设为 3600s）未过 ⇒ 第二条只有文本、没有卡。"""
    sink = _CardSink()
    monkeypatch.setattr(alerts, "alert_card_sink", sink)
    _enabled(monkeypatch, enabled=True, cooldown_seconds=3600)
    target = _target()
    now = [0.0]
    suppression = alerts.AdminAlertSuppression(clock=lambda: now[0])

    first = await _notify(target, suppression=suppression, delivered=[])
    assert first[0].success is True
    assert sink.count == 1

    now[0] = 301.0  # 文本抑制窗已过 → 第二条文本照发
    delivered: list[SendRequest] = []
    second = await _notify(target, suppression=suppression, delivered=delivered)
    assert second[0].suppressed is False
    assert len(delivered) == 1  # 文本发出去了
    assert sink.count == 1  # 卡被同一本 ErrorCardGate 挡住（未新建第二本账）


def test_gate_is_the_shared_error_card_gate_not_a_second_book() -> None:
    """告警卡用的就是异常卡那个进程级闸实例（同一对象＝同一本账）。"""
    gate = alerts._module_gate(60)
    assert isinstance(gate, ErrorCardGate)
    assert gate is alerts._module_gate(60)
    key = alerts.admin_alert_session_id(_target())
    assert gate.allow(key) is True
    assert gate.allow(key) is False
    assert gate.seconds_remaining(key) > 0


# ==================== ⑤ 开关关：零渲染 ====================
@pytest.mark.asyncio
async def test_disabled_switch_calls_no_renderer_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _CardSink()
    monkeypatch.setattr(alerts, "alert_card_sink", sink)
    _enabled(monkeypatch, enabled=False)
    target = _target()
    delivered: list[SendRequest] = []

    results = await _notify(target, delivered=delivered)

    assert results[0].success is True
    assert len(delivered) == 1
    assert sink.count == 0


# ==================== ⑥ 人话主句进卡 + 自查带「推测」 ====================
@pytest.mark.parametrize(
    ("stage", "kind", "plain_fragment"),
    [
        ("llm", "timeout", "等回话等超时了"),
        ("onebot", "retcode_failure", "协议端拒收"),
    ],
)
def test_headline_and_speculative_review_reach_the_card(
    stage: str, kind: str, plain_fragment: str
) -> None:
    issue = _issue(stage=stage, kind=kind, safe_summary=f"{kind} retryable=false")
    headline = alerts._alert_plain_headline(issue)
    report = build_issue_report(
        issue,
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        headline=headline,
        capability_id="bot.chat",
        config_getter=_config_values,
    )
    assert report["exc_type"] == f"{stage}/{kind}"
    assert plain_fragment in report["human_text"]
    assert report["human_text"].startswith("[守岸人告警]")
    review = report["self_review_pairs"][0]["value"]
    assert "推测" in review, review
    assert report["self_review_pairs"][0]["label"] == "大概原因"  # 节标题已含「我自查」，行内不复读


def test_unregistered_kind_falls_back_to_honest_default_review() -> None:
    report = build_issue_report(
        _issue(stage="zephyr_gate", kind="frobnicated"),
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        headline="",
        config_getter=_config_values,
    )
    review = report["self_review_pairs"][0]["value"]
    assert "不猜" in review  # 2026-09-25 措辞评审：不写个人情绪口语
    assert "是因为" not in review  # 认不出就不许写成断言
    labels = {row["label"] for row in report["method_pairs"]}
    # 「未归类（xxx）」只是把代号换个说法再念一遍，没有增量 ⇒ 整行不出（2026-09-25 评审）。
    assert "原因" not in labels, labels
    assert "阶段/代号" in labels, labels


# ==================== 生产分支不是死码（注入假后端/假池/桩队列） ====================
class _FakeBackend:
    def __init__(self, png: bytes | None) -> None:
        self.png = png
        self.payloads: list[dict[str, Any]] = []

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.payloads.append(payload)
        return self.png


class _QueueStub:
    def __init__(self) -> None:
        self.requests: list[tuple[Any, dict[str, Any]]] = []

    def submit(self, send_request: Any, **kwargs: Any) -> None:
        self.requests.append((send_request, kwargs))


class _PipelineStub:
    def __init__(self) -> None:
        self.send_queue = _QueueStub()


class _InlinePool:
    """同步执行池：让「排进渲染线程」这一步在测试里可断言（契约对齐 executor）。"""

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> Future:
        fn(*args, **kwargs)
        done: Future = Future()
        done.set_result(None)
        return done


def test_real_render_path_submits_image_card_to_queue(tmp_path: Path) -> None:
    target = _target(scope=SessionType.GROUP)
    pipeline = _PipelineStub()
    backend = _FakeBackend(b"png-bytes")
    dispatched = alerts._maybe_dispatch_issue_card(
        _issue(stage="onebot", kind="retcode_failure"),
        target,
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.GROUP,
        pipeline=pipeline,
        capability_id="bot.chat",
        settings=ErrorCardSettings(enabled=True, cooldown_seconds=60),
        gate=ErrorCardGate(60.0),
        backend=backend,
        card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert dispatched is True
    assert len(backend.payloads) == 1
    assert len(pipeline.send_queue.requests) == 1
    request, kwargs = pipeline.send_queue.requests[0]
    assert request.content.content_type == "mixed"
    parts = request.content.content_ref["parts"]
    assert parts[0]["type"] == "image"
    assert Path(parts[0]["file"]).is_file()
    assert "运行时告警" in request.content.text_fallback
    # 卡排在文本之后（A-plus 同口径延迟），且投递仍走 bot.error_report 那个出口。
    deliver_after = kwargs.get("deliver_after")
    assert isinstance(deliver_after, datetime)
    assert deliver_after > datetime.now(timezone.utc)
    assert request.capability_id == "bot.error_report"
    # 递归护栏：根装配层按 `admin_alert` 标签短路队列回执通知，漏了它＝告警自我放大。
    assert "admin_alert" in request.audit_tags
    assert request.session_id == alerts.admin_alert_session_id(target)


def test_render_failure_still_delivers_full_text_diagnostic(tmp_path: Path) -> None:
    """出图失败（后端回空）⇒ 不硬凑图，改投全量诊断文本（不发明第二份文本口径）。"""
    target = _target()
    pipeline = _PipelineStub()
    dispatched = alerts._maybe_dispatch_issue_card(
        _issue(),
        target,
        source_adapter="onebot",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
        pipeline=pipeline,
        capability_id="bot.chat",
        settings=ErrorCardSettings(enabled=True, cooldown_seconds=60),
        gate=ErrorCardGate(60.0),
        backend=_FakeBackend(None),
        card_dir=str(tmp_path),
        render_pool=_InlinePool(),
    )
    assert dispatched is True
    request, _kwargs = pipeline.send_queue.requests[0]
    assert request.content.content_type == "text"
    assert "定位与原因" in request.content.text_fallback


def test_no_pipeline_and_no_sink_sends_no_card_and_keeps_the_gate() -> None:
    """既没队列也没替身 ⇒ 不出卡，并且**不烧冷却窗口**（闸留给真能发的那一刻）。"""
    target = _target()
    gate = ErrorCardGate(3600.0)
    assert (
        alerts._maybe_dispatch_issue_card(
            _issue(),
            target,
            source_adapter="onebot",
            source_bot="3958874605",
            session_type=SessionType.PRIVATE,
            pipeline=None,
            settings=ErrorCardSettings(enabled=True, cooldown_seconds=3600),
            gate=gate,
        )
        is False
    )
    assert gate.seconds_remaining(alerts.admin_alert_session_id(target)) == 0.0


# ==================== 装配可达性：告警链把 pipeline 透传到卡 ====================
def test_notify_chain_wires_pipeline_into_the_card() -> None:
    """结构锁：文本发成功后必须按 `pipeline=pipeline` 调卡，否则「接了」是假的。"""
    source = inspect.getsource(alerts.notify_operational_issue)
    tree = ast.parse(source)
    calls = {
        node.func.id: {kw.arg for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_maybe_dispatch_issue_card" in calls
    assert {"pipeline", "capability_id"} <= calls["_maybe_dispatch_issue_card"]
    # 顺序判据：卡这一次调用必须排在 dispatch_admin_alert 之后（先文本后卡）。
    assert source.index("dispatch_admin_alert") < source.index(
        "_maybe_dispatch_issue_card"
    )


def test_alerts_side_has_no_second_card_payload_or_gate() -> None:
    """单一真身：alerts 侧不许出现第二份卡载荷组装，也不另立冷却闸类。"""
    source = inspect.getsource(alerts)
    assert "build_issue_report" in source
    for forbidden in ('"human_text":', '"self_review_pairs":', "class AlertCardGate"):
        assert forbidden not in source, forbidden


def test_issue_stage_ownership_keys_track_alert_stage_plain() -> None:
    """两把尺同域：阶段→归属 的键集必须是 阶段→人话主句 的子集且值非空。

    告警面「哪个模块的哪个功能」靠这张表兜底（告警常无能力 id）。`_STAGE_PLAIN`
    加了新阶段而这里没跟上，就会退回「未归属」——要素⑩当场失效而无人报警。
    """
    ownership = error_report._ISSUE_STAGE_OWNERSHIP
    plain = alerts._STAGE_PLAIN
    assert ownership, "归属表被清空＝卡面定位整列回退"
    # 双向：只查 `ownership - plain` 会漏掉反方向的 13 档（campus/creation/…），
    # 那些正是真卡上「归属=未归属」的来源（E4 现算坐实，2026-09-25）。
    drift = set(ownership) ^ set(plain)
    assert not drift, f"两把尺不同域（差集 {sorted(drift)}）：人话表与归属表必须同档"
    assert all(str(v).strip() and "域" in str(v) for v in ownership.values())


def test_issue_card_locates_module_from_stage_when_capability_unnamed() -> None:
    """要素⑩真判据：无能力 id 的告警也必须落到具体子系统，不许整列 unknown。"""
    report = build_issue_report(
        OperationalIssue(stage="llm", kind="timeout", safe_summary="chain=2跳全败"),
        source_adapter="onebot_v11",
        source_bot="3958874605",
        session_type=SessionType.GROUP,
    )
    rows = {str(r["label"]): str(r["value"]) for r in report["method_pairs"]}
    assert "llm_engine" in rows["归属"], rows
    # 拿不到的行**整行不出**（评审：unknown 占版面），所以这里断言"不在"而不是"等于—"
    assert "函数" not in rows and "路由" not in rows, rows
    assert "unknown" not in " ".join(rows.values()), rows


# ==================== 2026-09-25 二批：E1/E2 指认的跟随锁 ====================


def _issue_rows(report: dict[str, Any]) -> dict[str, str]:
    return {
        str(row["label"]): str(row["value"])
        for key in ("method_pairs", "id_pairs")
        for row in report.get(key) or []
    }


def test_issue_card_carries_detail_text_without_a_stack() -> None:
    """⑧报错内容在告警卡上必须有落点：issue 不带 traceback，详情不单独给一行＝整张
    卡没有任何具体细节（E1 P1-1，图卡上真的看不见，只有纯文本里有）。"""
    report = build_issue_report(
        OperationalIssue(
            stage="llm", kind="timeout", safe_summary="chain=17跳全败 last=axon-grok-46:timeout"
        ),
        source_adapter="onebot_v11",
        source_bot="3958874605",
        session_type=SessionType.GROUP,
    )
    rows = _issue_rows(report)
    # 详情走模板的「报错详情」节（无栈时的表头），载荷不再重复一行
    from plugins.bot_unified_runtime.domains.render.card_render import bridge
    html = bridge.render_error_card_html(report)
    assert "chain=17跳全败" in html, rows
    assert bridge._CARD_TEXT["static_err_30"] in html
    # 默认档建议不许指着一节不存在的东西让她看（E1 P2-4）。
    advice = str((report["self_review_pairs"][1] or {}).get("value", ""))
    assert "栈摘录" not in advice, advice


def test_issue_card_detail_is_redacted() -> None:
    """详情走统一脱敏：safe_summary 里夹的盘符路径与 sk- 形态不得原样上卡。"""
    report = build_issue_report(
        OperationalIssue(
            stage="tts",
            kind="network",
            safe_summary=r"C:\Users\x\.env sk-abcdefghijklmnopqrst failed",
        ),
        source_adapter="onebot_v11",
        source_bot="3958874605",
        session_type=SessionType.PRIVATE,
    )
    from plugins.bot_unified_runtime.domains.render.card_render import bridge
    detail = bridge.render_error_card_html(report)
    assert "sk-abcdefghijklmnopqrst" not in detail and "LancyCelestia" not in detail


def test_issue_card_session_identity_rows_follow_the_caller() -> None:
    """②哪个会话：调用方给了 session_id/group_id/request_id 就必须上卡；
    没给就不写行（不留 unknown 糊弄）。"""
    common = {
        "source_adapter": "onebot_v11",
        "source_bot": "3958874605",
        "session_type": SessionType.GROUP,
    }
    bare = _issue_rows(build_issue_report(OperationalIssue(stage="queue", kind="bot_unavailable"), **common))
    assert "session_id" not in bare and "request_id" not in bare, bare
    assert bare["会话"] == "群聊", bare  # 拿不到群号就只写形态，不再补「未知群」占位
    filled = _issue_rows(
        build_issue_report(
            OperationalIssue(stage="queue", kind="bot_unavailable"),
            group_id="1108838060",
            session_id="group_1108838060_3865067623",
            request_id="req_56a5f6cce102",
            **common,
        )
    )
    assert "群聊 1108838060" in filled["会话"], filled
    assert "group_1108838060_3865067623" in filled["会话"], filled
    assert filled["request_id"] == "req_56a5f6cce102", filled


def test_issue_card_severity_is_plain_chinese() -> None:
    """严重度直出 `medium` 这类英文 token 违反「报错提示用人话」；且枚举加一档
    忘了填人话时必须落「未定级」而不是英文。"""
    rows = _issue_rows(
        build_issue_report(
            OperationalIssue(stage="llm", kind="timeout"),
            source_adapter="onebot_v11",
            source_bot="1",
            session_type=SessionType.PRIVATE,
        )
    )
    assert rows["严重度"].startswith("中"), rows
    assert "medium" not in rows["严重度"], rows


def test_value_error_is_classified_not_unclassified() -> None:
    """E1 P2-3：ValueError 是能力代码最常抛的形态之一，卡面却写「未归类」。"""
    report = build_error_report(
        _message(), "bot.weather", ValueError("bad literal for int()")
    )
    rows = {str(r["label"]): str(r["value"]) for r in report["method_pairs"]}
    assert "未归类" not in rows.get("原因", ""), rows


def test_internal_probe_adapter_has_a_plain_protocol_label() -> None:
    """探针口传的 source_adapter="runtime" 不是协议端，得说人话而不是 unknown。"""
    report = build_issue_report(
        OperationalIssue(stage="tts", kind="tts_service_unreachable"),
        source_adapter="runtime",
        source_bot="tts-probe",
        session_type=SessionType.PRIVATE,
    )
    env = {str(r["label"]): str(r["value"]) for r in report["env_pairs"]}
    assert env["协议"] == "进程内（无协议端）", env
    assert env["通信"] == "进程内（不经网络）", env


def test_production_alert_sites_pass_attribution_facts() -> None:
    """装配活性锁（AST）：根文件四个生产告警口必须把投递依赖与会话事实传进来——
    「形参在册但没人传」＝卡面永远「未记名」（E1 P1-3，与 #49 那把
    gate_feature_id 同型：字段在册、门不执法）。"""
    root = Path("plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(root))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "notify_operational_issue"
    ]
    assert len(calls) == 4, [node.lineno for node in calls]
    kwargs = [{kw.arg for kw in node.keywords if kw.arg} for node in calls]
    assert all("pipeline" in kw for kw in kwargs), kwargs
    assert sum("capability_id" in kw for kw in kwargs) >= 3, kwargs
    assert sum("session_id" in kw for kw in kwargs) >= 2, kwargs




def test_card_avatar_inlines_as_data_uri(tmp_path: Path) -> None:
    """头像必须**内联**成 data URI：渲染后端用 set_content 装页，Chromium 拒绝
    `file://` 子资源 ⇒ 直接给路径就是一个碎图图标（2026-09-25 样张实锤）。"""
    from types import SimpleNamespace

    png = tmp_path / "avatar" / "bot_123.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 32)
    cfg = SimpleNamespace(bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path))
    uri = error_report._card_avatar_uri(lambda name: getattr(cfg, name, None))
    assert uri.startswith("data:image/png;base64,"), uri[:32]
    # 关键不变量：**任何**返回值都不能是 file:// 路径（那是碎图图标），
    # 要么 data URI、要么空串回落「守」字圆点。进程级头像缓存在先跑的用例里
    # 已被登记激活（bot_avatar 的单实例语义），所以这里不能强求空串。
    for probe in (
        SimpleNamespace(bot_persona_avatar_url="", bot_runtime_data_dir=str(tmp_path / "nowhere")),
        SimpleNamespace(bot_persona_avatar_url="", bot_runtime_data_dir=""),
    ):
        def getter_for(config: object, /) -> Callable[[str], object]:
            return lambda name: getattr(config, name, None)

        got = error_report._card_avatar_uri(getter_for(probe))
        assert not got.startswith("file:"), got[:40]
        assert got == "" or got.startswith("data:image/"), got[:40]
    # 超大文件不内联（整页要进 HTML，不能被一张图撑爆）：上限常量必须存在且为正。
    assert error_report._AVATAR_INLINE_MAX_BYTES > 0
