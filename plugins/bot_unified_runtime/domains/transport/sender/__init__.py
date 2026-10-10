# 分库共装（split package，主人 2026-10-11 裁定①「组合可导入」）：生产单树时 no-op。
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from .onebot import (
    ONEBOT_V11_TRANSPORT,
    OneBotMessageSegment,
    OneBotV11Bot,
    build_onebot_message_segments,
    send_onebot_v11,
)
from .queue import (
    InMemorySendQueue,
    QueuedSendRequest,
    SendQueue,
    SQLiteSendRequestQueue,
    build_send_queue,
)
from .receipts import (
    InMemoryReceiptRepository,
    ReceiptRepository,
    SQLiteReceiptRepository,
    blocked_receipt,
    build_receipt_repository,
    sent_receipt,
    skipped_receipt,
)
from .worker import (
    SEND_QUEUE_WORKER_TRANSPORT,
    DrainableSendQueue,
    SendQueueWorkerResult,
    SendTransport,
    drain_send_queue_once,
)

__all__ = [
    "ONEBOT_V11_TRANSPORT",
    "SEND_QUEUE_WORKER_TRANSPORT",
    "DrainableSendQueue",
    "InMemoryReceiptRepository",
    "InMemorySendQueue",
    "OneBotMessageSegment",
    "OneBotV11Bot",
    "QueuedSendRequest",
    "ReceiptRepository",
    "SQLiteReceiptRepository",
    "SQLiteSendRequestQueue",
    "SendQueue",
    "SendQueueWorkerResult",
    "SendTransport",
    "blocked_receipt",
    "build_onebot_message_segments",
    "build_receipt_repository",
    "build_send_queue",
    "drain_send_queue_once",
    "send_onebot_v11",
    "sent_receipt",
    "skipped_receipt",
]
