"""超时改造 C1-c（2026-09-28）：`llm / deadline_exceeded` 不再被静默掐掉管理员告警。

被拆掉的早退住在根 `__init__.py` 的运营告警终账器 `_notify_operational_receipt` 里，原注释
写的是「常态降级、不值得私聊管理员」。同一件事这条线已经记过两次账：

- 台账 #49「在册未执法」——件存在、没人看得见，于是永远没人修；
- 台账 #51「没检索禁写『它没有』」——把一类故障从可见面摘掉，等于替它写了"不会发生"。

**不刷屏这件事本来就有负责的那件**：`domains/ops/monitor/alerts.py::AdminAlertSuppression`
（缺省 300s 窗，llm 族按 stage 折叠，窗口内每个目标最多一条）。局部早退是给同一个问题装
第二道闸，还把第一道闸的判据变成摆设——所以修法＝拆早退，抑制窗原样保留并**当场验它有牙**。

本文件两腿：
① 静态腿（AST）：终账器体内不许再出现「判到 deadline_exceeded 就裸 return」的形状，
   且必须真的调用中央告警口 `notify_operational_issue`（断线也算回归）。
   注毒自证＝把那句早退塞回**内存副本**（零碰真树）⇒ 判据必须点名红；
   干净对照＝同一把尺量真树必须为空（防"抽谁都红"的假牙）。
② 行为腿：中央告警口对 `deadline_exceeded` **真投递一次**，同窗内第二次被
   `AdminAlertSuppression` 抑制 ⇒ 证明"不刷屏"由抑制窗兜住，不需要摘可见面。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import alerts
from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
    AdminAlertSuppression,
    AdminTarget,
    notify_operational_issue,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_PY = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
FINALIZER = "_notify_operational_receipt"
KIND = "deadline_exceeded"
_POISON_MARK = "c1c-poison-early-return"


# ---------------------------------------------------------------------------
# 取数口（AST，不 import 根文件——根文件是装配现场，导入它等于起半个 bot）
# ---------------------------------------------------------------------------
def _finalizer_node(source: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == FINALIZER:
            return node
    raise AssertionError(
        f"{FINALIZER} 不在 __init__.py（改名/搬走＝本锁失效，必须重钉到新真身）"
    )


def _silences_this_kind(node: ast.AST) -> list[ast.Return]:
    """体内「这一类被判到就裸 return」的语句＝把一类故障从可见面摘掉的形状。"""
    hits: list[ast.Return] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.If):
            continue
        if f"'{KIND}'" not in ast.dump(child.test):
            continue
        hits.extend(
            stmt
            for stmt in child.body
            if isinstance(stmt, ast.Return) and stmt.value is None
        )
    return hits


def _calls_central_alert(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "notify_operational_issue"
        for call in ast.walk(node)
    )


# ---------------------------------------------------------------------------
# ① 静态腿
# ---------------------------------------------------------------------------


def test_finalizer_no_longer_silences_deadline_exceeded() -> None:
    source = INIT_PY.read_text(encoding="utf-8")
    node = _finalizer_node(source)

    assert _calls_central_alert(node), (
        f"{FINALIZER} 不再调 notify_operational_issue ⇒ 告警线整条断（比本波要修的更坏）"
    )
    assert not _silences_this_kind(node), (
        f"C1-c 回潮：{FINALIZER} 体内又有按 {KIND} 裸 return 的分支"
        "（刷屏该由 AdminAlertSuppression 兜，不该摘可见面）"
    )


def test_static_lock_has_teeth_on_injected_poison() -> None:
    """注毒自证：把那句早退塞回**整份内存副本** ⇒ 判据必须点名红；真树同尺必须为空。

    做法＝按终账器的行区间把早退三行插进 `__init__.py` 的内存字符串，再整份重解析。
    刻意不碰磁盘（规则：只读取证、零写他人热面），也刻意不用"手搓一段假函数体"
    ——那测的是我以为的形状，不是真身形状（在册≠已接的同族病）。
    """
    source = INIT_PY.read_text(encoding="utf-8")
    node = _finalizer_node(source)
    anchor = "        targets = _operational_alert_targets()\n"
    body_segment = ast.get_source_segment(source, node) or ""
    assert anchor in body_segment, "注毒锚点在终账器体内失配＝现状已变，先现算再动锁"

    lines = source.splitlines(keepends=True)
    insert_at = next(
        index
        for index, line in enumerate(lines[node.lineno - 1 : node.end_lineno], node.lineno - 1)
        if line == anchor
    )
    poisoned_lines = [
        *lines[:insert_at],
        f"        # {_POISON_MARK}\n",
        (
            '        if getattr(issue, "stage", "") == "llm" and '
            f'getattr(issue, "kind", "") == "{KIND}":\n'
        ),
        "            return\n",
        *lines[insert_at:],
    ]
    poisoned_source = "".join(poisoned_lines)
    assert poisoned_source != source, "注毒没打进去＝这一发在空跑"

    # 干净对照（同一把尺量真树）：必须为空，否则判据是"抽谁都红"的假牙。
    assert _silences_this_kind(_finalizer_node(source)) == []
    # 毒发对照：注入后的真身必须被点名，且中央告警口那条腿仍认得出来。
    poisoned_node = _finalizer_node(poisoned_source)
    assert _silences_this_kind(poisoned_node), "注毒后判据仍不红＝这把门是装饰"
    assert _calls_central_alert(poisoned_node), (
        "判据尺连「调了中央告警口」都读不出来＝AST 面已瞎"
    )


# ---------------------------------------------------------------------------
# ② 行为腿：中央告警口真投递，抑制窗仍在
# ---------------------------------------------------------------------------


def _issue() -> OperationalIssue:
    return OperationalIssue(
        stage="llm",
        kind=KIND,
        retryable=False,
        debug_id="dbg-c1c",
        safe_summary=f"{KIND} chain=3",
    )


async def _deliver(
    target: AdminTarget,
    suppression: AdminAlertSuppression,
    sink: list[tuple[str, str]],
) -> list[Any]:
    async def fake_delivery(
        alert_target: AdminTarget, _bot: object, request: SendRequest
    ) -> DeliveryReceipt:
        sink.append((alert_target.target_id, str(request.content.text_fallback)))
        return DeliveryReceipt(
            request_id=request.request_id,
            state=ReceiptState.SENT,
            transport="fake",
            public_message="sent",
        )

    return await notify_operational_issue(
        _issue(),
        source_adapter="onebot",
        source_bot="10000",
        session_type=SessionType.PRIVATE,
        targets=[target],
        online_bots={target.bot_id: object()},
        delivery=fake_delivery,
        suppression=suppression,
        # pipeline 缺省 None＝诊断卡腿诚实跳过（本文件只管告警可见性，绝不起渲染）。
    )


def test_deadline_exceeded_reaches_admin_once_and_is_then_suppressed() -> None:
    """一次投递＋同窗第二次被抑制：两半同时成立才叫"C1-c 修对了"。"""
    target = AdminTarget(adapter="onebot", bot_id="qq-bot", target_id="10001")
    suppression = AdminAlertSuppression(window_seconds=300.0)
    sink: list[tuple[str, str]] = []

    first = _run(_deliver(target, suppression, sink))
    assert len(first) == 1
    assert first[0].success is True, first[0]
    assert first[0].suppressed is False, first[0]
    assert len(sink) == 1
    assert KIND in sink[0][1], f"告警文本没带代号：{sink[0][1]}"

    second = _run(_deliver(target, suppression, sink))
    assert second[0].suppressed is True, second[0]
    assert len(sink) == 1, "抑制窗没兜住＝拆早退把管理员灌爆（那才是早退存在过的理由）"
    assert second[0].suppressed_count >= 1


def test_other_llm_kinds_are_untouched_by_this_wave() -> None:
    """对照面：同 stage 的另一种 kind 本来就在告警面上（本波只拆一种，别顺手改判定）。"""
    target = AdminTarget(adapter="onebot", bot_id="qq-bot", target_id="10002")
    sink: list[tuple[str, str]] = []

    async def deliver() -> list[Any]:
        async def fake_delivery(
            alert_target: AdminTarget, _bot: object, request: SendRequest
        ) -> DeliveryReceipt:
            sink.append((alert_target.target_id, str(request.content.text_fallback)))
            return DeliveryReceipt(
                request_id=request.request_id,
                state=ReceiptState.SENT,
                transport="fake",
                public_message="sent",
            )

        return await notify_operational_issue(
            OperationalIssue(
                stage="llm", kind="timeout", retryable=True, safe_summary="timeout chain=1"
            ),
            source_adapter="onebot",
            source_bot="10000",
            session_type=SessionType.PRIVATE,
            targets=[target],
            online_bots={target.bot_id: object()},
            delivery=fake_delivery,
            suppression=AdminAlertSuppression(window_seconds=300.0),
        )

    results = _run(deliver())
    assert results[0].success is True
    assert "timeout" in sink[0][1]


@pytest.fixture(autouse=True)
def _no_real_card_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """全离线保底：本文件绝不让诊断卡真渲染/真入队。"""

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("C1-c 测试不得触达卡渲染/入队")

    monkeypatch.setattr(alerts, "schedule_issue_card", _boom)


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)
