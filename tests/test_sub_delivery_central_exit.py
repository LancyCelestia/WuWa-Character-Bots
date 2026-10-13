"""SUBDELIVERY-3（F-1 收编中央出口 + BYPASS_SUSPECT 改判 + 幂等键段）补丁预备锁。

在册事实（不改判、不弱化）：`outbound_registry.py` 的
`DirectSendEntry("__init__.py:_deliver_v2_event", …, BYPASS_SUSPECT)` 由
S-FIX-SUB-SEC 登记（该件今天在他席在飞态，HEAD 上还没有这条目——本文件不钉
registry 形状，改判动作写在 patch md 里）。台账 #46★ 的硬线在这里的含义：
`sub_push` 族收编进中央出口后，dedupe 键每一段都必须过 `is_legal_segment`
（段内禁 `:`），脏段在开闸态＝整条静默丢。

两腿两态：
- ①（HEAD 绿）纯逻辑洗段腿：旧冒号形 event_id（f3e2972 前的存量行）与新形
  `sub-<hex>` 拼 `sub_push` 族键，逐段过 `active_push_key_segment` 后必须
  段段合法、近似单射、新形逐字节不变（迁移锁同口径）；
- ②（红，**待裁 Q-2 + 待 root 批**）AST 根锁：根 `_deliver_v2_event` 体内出现
  中央主动推送出口符号 `_push_via_central_exit_now`，且申报
  `dedupe_namespace="sub_push"`——收编真落地才会绿；今天不许为凑绿放宽。

离线：零网络、零 NoneBot、不 import 根件。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    active_push_key_segment,
    is_legal_segment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_SUB_PUSH_NAMESPACE = "sub_push"


def test_sub_push_key_segments_legal_and_near_injective() -> None:
    """①（HEAD 绿）台账 #46★ 键段红线的收编前体检（纯逻辑，不碰生产）。"""
    legacy_event_id = "probe:creator:collide:video:a:b"  # f3e2972 前的冒号拼串形
    new_event_id = "sub-0123456789abcdef0123456789abcdef"  # 规范摘要形
    destination_key = "123"  # subscription_destinations 行 id（自增数字）

    legacy_seg = active_push_key_segment(legacy_event_id)
    assert is_legal_segment(legacy_seg), f"旧冒号形洗完仍非法段：{legacy_seg!r}"
    assert ":" not in legacy_seg
    # 新形零改写：已入生产库的合法键段逐字节不变（迁移锁同一条纪律）
    assert active_push_key_segment(new_event_id) == new_event_id
    # 近似单射：不同旧串不得折成同一段（S184 教训——同段＝共享幂等桶＝继续静默丢）
    siblings = [
        "probe:creator:collide:video:a:b",
        "probe:creator:collide:video:a",
        "probe:creator:collide:video:a:",
        "probe:creator:collide:vide:oa:b",
    ]
    washed = {active_push_key_segment(value) for value in siblings}
    assert len(washed) == len(siblings), f"洗段折叠：{sorted(washed)}"

    key = ":".join(
        [
            active_push_key_segment(_SUB_PUSH_NAMESPACE),
            legacy_seg,
            active_push_key_segment(destination_key),
        ]
    )
    assert key.count(":") == 2 and all(is_legal_segment(part) for part in key.split(":"))


def _root_delivery_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_deliver_v2_event"
        ),
        None,
    )
    assert fn is not None, "根文件里找不到 _deliver_v2_event＝锚点已漂，本锁失明"
    return fn


def test_root_delivery_goes_through_central_exit() -> None:
    """②（红·两态见 docstring）F-1 收编落地的 AST 哨兵。**待裁 Q-2**。

    修前红＝现状在册（BYPASS_SUSPECT 注记「F-1 落地后随迁改判」）；
    修后绿＝根腿经 `_push_via_central_exit_now(..., dedupe_namespace="sub_push")`。
    收编若被裁定为「另立波」，本锁保持红到那一波落地，期间由
    `test_subscription_per_destination_ledger_sub2.py` +
    `test_sub_delivery_pending_filter.py` 守逐目的地台账面。
    """
    fn = _root_delivery_fn()
    names = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_push_via_central_exit_now" in names, (
        "订阅投递仍走 pipeline→_deliver_transport_send_request 直落传输段"
        "＝BYPASS_SUSPECT 在册事实未翻正（F-1）"
    )
    declared = {
        keyword.value.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if isinstance(keyword.arg, str) and keyword.arg == "dedupe_namespace"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    assert _SUB_PUSH_NAMESPACE in declared, (
        "收编必须申报 sub_push 命名空间——漏报回落 emg 口径＝开闸态整链静默丢（R-CENTRAL C-1）"
    )


def test_central_exit_same_family_key_never_lands_a_second_row(tmp_path: Path) -> None:
    """③（行为锁）F-1 反双发：管线按 `sub_push` 族键落库后，中央出口**同键**二次
    submit 被队列 `ON CONFLICT(dedupe_key)` 吸收 ⇒ 库里恒一行；`mark_sent(request_id)`
    终结的就是它，worker 无第二行可投。

    为什么必须实测这一条（不是靠散文）：F-1 收编若让「根建键」与「管线建键」各成
    一枚不同的键，队列会按整串各存一行，而 `mark_sent` 只按 request_id 终结**一行**
    （`queue._resolve_update_identity_in` 取单行）⇒ 另一行留 QUEUED、worker 稍后照投
    ＝真双发（本锁要挡的正是这条事故）。三段键逐段过 `active_push_key_segment`
    （台账 #46★：段内禁 `:`）后，中央出口的 `wash_active_push_key` 对它是**恒等映射**，
    「两边逐字节同键」这个前提本身也被本用例覆盖——键形一漂，`ON CONFLICT` 立刻失效、
    QUEUED 计数变 2，本锁当场红。
    """
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.core.contracts import (
        PrivacyLevel,
        ReceiptState,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.ops.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        build_outbound_gate,
        submit_active_push,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        SQLiteSendRequestQueue,
    )

    queue = SQLiteSendRequestQueue(
        tmp_path / "sub_push_queue.sqlite3", InMemoryAuditLogger()
    )
    # 与根 `_deliver_v2_event` 同一把尺：族名 + 事件段 + 目的地段，逐段过洗段口。
    key = ":".join(
        [
            active_push_key_segment(_SUB_PUSH_NAMESPACE),
            active_push_key_segment("sub-0123456789abcdef0123456789abcdef"),
            active_push_key_segment("123"),
        ]
    )
    request = SendRequest(
        request_id="req-sub-push-1",
        session_id="group:123",
        target_scope=SessionType.GROUP,
        target_id="123",
        capability_id="bot.subscribe",
        content=RenderedOutput(
            request_id="req-sub-push-1",
            content_type="text",
            content_ref={},
            text_fallback="订阅更新",
            privacy_level=PrivacyLevel.PUBLIC,
        ),
        send_policy=SendPolicy.QUEUED,
        priority="normal",
        max_messages=1,
        dedupe_key=key,
        cooldown_key="sub_push:123",
        privacy_level=PrivacyLevel.PUBLIC,
        persona_profile_id="default",
    )

    # ① 管线先落库（等价 handle_async 用同一键 submit）：恰一行 QUEUED。
    assert queue.submit(request).state is ReceiptState.QUEUED
    assert queue.safe_summary()[ReceiptState.QUEUED.value] == 1

    # ② 中央出口同键再 submit（闸缺省关＝与裸 submit 同形的 passthrough）：
    #    被吸收，回 SKIPPED，绝不落第二行。
    gate = build_outbound_gate(SimpleNamespace())
    outcome = submit_active_push(
        queue, request, gate, dedupe_family="once", dedupe_namespace="sub_push"
    )
    assert outcome.receipt is not None
    assert outcome.receipt.state is ReceiptState.SKIPPED
    assert outcome.receipt.public_message == "duplicate dedupe_key"
    summary = queue.safe_summary()
    assert summary[ReceiptState.QUEUED.value] == 1, (
        f"中央出口同键二次 submit 落了第二行＝真双发病根：{summary}"
    )

    # ③ 内联投递成功 → mark_sent(request_id) 只终结这一行；worker 越过内联宽限后
    #    再认领＝零行（无第二行可投）。
    queue.mark_sent("req-sub-push-1")
    far_future = datetime.now(timezone.utc) + timedelta(seconds=3600)
    assert queue.claim_due(now=far_future, limit=10) == [], (
        "终结后仍有可认领行＝存在第二行（真双发）"
    )
    assert queue.safe_summary()[ReceiptState.QUEUED.value] == 0
