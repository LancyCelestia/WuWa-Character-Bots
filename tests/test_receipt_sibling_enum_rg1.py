"""R-G1（S-ATK-RECEIPTS）：`/bot receipt` 展示层必须枚举同 request_id 兄弟回执。

生产实锤（SEAT-ATK-RECEIPTS §1）：error_report 的 ack/card 两行**设计内共享**
request_id，而展示层 `find()` 只回「最新一行」⇒ 管理员把「卡已发、ack 被吞」
读成整体失败（反向亦然）。写侧扇出归 S-FIX-QKEY；本锁管读侧：多回执共 id 时
全部兄弟必须见光（有上限，超限点名「另有 N 条未列出」），单回执路径逐字节不变。
"""

from __future__ import annotations

from plugins.bot_unified_runtime.contracts import DeliveryReceipt, ReceiptState
from plugins.bot_unified_runtime.domains.ops.admin.debug import (
    build_receipt_query_result,
)
from plugins.bot_unified_runtime.domains.transport.sender.receipts import (
    InMemoryReceiptRepository,
)

_ADMIN = ["admin"]


def _receipt(state: ReceiptState, debug_id: str, request_id: str = "req_rg1_shared") -> DeliveryReceipt:
    return DeliveryReceipt(request_id=request_id, state=state, transport="onebot", debug_id=debug_id)


def test_single_receipt_body_unchanged():
    repo = InMemoryReceiptRepository()
    repo.record(_receipt(ReceiptState.SENT, "dbg_only"))
    result = build_receipt_query_result(repo, actor_roles=_ADMIN, query="req_rg1_shared")
    assert "failed_final" not in result.body
    assert "条兄弟回执" not in result.body  # 单回执不加兄弟头
    assert "state=sent" in result.body


def test_sibling_receipts_all_visible():
    repo = InMemoryReceiptRepository()
    repo.record(_receipt(ReceiptState.FAILED_FINAL, "dbg_ack"))
    repo.record(_receipt(ReceiptState.SENT, "dbg_card"))
    result = build_receipt_query_result(repo, actor_roles=_ADMIN, query="req_rg1_shared")
    body = result.body
    assert "dbg_ack" in body and "dbg_card" in body  # 两行 debug_id 都见光
    assert "failed_final" in body and "sent" in body  # 双向谎报都被拆穿
    assert "2" in body.splitlines()[0]  # 首行点名共 2 条


def test_sibling_enum_by_debug_id_token():
    repo = InMemoryReceiptRepository()
    repo.record(_receipt(ReceiptState.FAILED_FINAL, "dbg_ack"))
    repo.record(_receipt(ReceiptState.SENT, "dbg_card"))
    result = build_receipt_query_result(repo, actor_roles=_ADMIN, query="dbg_ack")
    # 用兄弟任一 debug_id 查询也要把整组枚举出来
    assert "dbg_card" in result.body and "failed_final" in result.body


def test_sibling_display_capped_with_honest_note():
    repo = InMemoryReceiptRepository()
    for i in range(7):
        repo.record(_receipt(ReceiptState.SENT, f"dbg_{i}"))
    result = build_receipt_query_result(repo, actor_roles=_ADMIN, query="req_rg1_shared")
    body = result.body
    assert "另有 2 条未列出" in body
    assert "dbg_0" not in body  # 只展示最新 5 条（dbg_2..dbg_6）
    assert "dbg_2" in body


def test_not_found_path_unchanged():
    repo = InMemoryReceiptRepository()
    result = build_receipt_query_result(repo, actor_roles=_ADMIN, query="req_absent")
    assert "未找到发送回执" in result.body
