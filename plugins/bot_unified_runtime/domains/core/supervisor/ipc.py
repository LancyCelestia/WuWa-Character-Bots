"""受控 IPC —— 长度前缀 JSON 帧协议（后端 V2.1 规范 §3）。

协议形态：4 字节小端无符号长度前缀 + UTF-8 JSON 帧体。

硬性约束（违反即 ``ProtocolViolation``，绝不静默容错）：
- 单帧 ≤ 1MiB（发送端编码后校验；接收端先验长度前缀再读帧体，防资源耗尽）；
- JSON 嵌套深度 ≤ 32（编码/解码两侧都查）；
- 只允许 JSON——pickle 等任何二进制反序列化通道在本模块不存在，
  非 UTF-8 JSON 字节一律拒绝；
- 帧体必须是完整信封（字段校验见 ``validate_envelope``）。

信封字段（规范 §3 固定十字段）：
protocol_version / request_id / trace_id / plugin_id / plugin_release /
operation / invocation_id / deadline_remaining_ms / input / asset_refs

二进制资产不进帧：只传 asset_id（string），资产本体经 AssetBroker 通道交换。
本模块只依赖标准库，导入零副作用（contracts 层纪律）。
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any

# 协议版本（破坏性变更必须升版并在 validate_envelope 拒绝旧版）
PROTOCOL_VERSION = 1

# 单帧上限：1MiB（规范 §3）
MAX_FRAME_BYTES = 1024 * 1024

# JSON 嵌套深度上限：32（容器嵌套层数，标计 0 层）
MAX_NESTING_DEPTH = 32

# 4 字节小端长度前缀
_LENGTH_PREFIX = struct.Struct("<I")

# 信封必填字符串字段（非空）
_REQUIRED_STR_FIELDS = (
    "request_id",
    "trace_id",
    "plugin_id",
    "plugin_release",
    "operation",
    "invocation_id",
)

# 允许的整型字段（非布尔、非负）
_NONNEG_INT_FIELDS = ("deadline_remaining_ms",)


class ProtocolViolation(Exception):
    """帧协议被违反：超限、深度超限、非 JSON、帧截断或信封字段不合法。

    本异常是协议层唯一失败形态；调用方必须以"对端违约"处置（断开/审计），
    不允许捕获后继续复用该连接。
    """


# ---------------------------------------------------------------------------
# 信封构造与校验
# ---------------------------------------------------------------------------

def make_envelope(
    *,
    request_id: str,
    trace_id: str,
    plugin_id: str,
    plugin_release: str,
    operation: str,
    invocation_id: str,
    input: Any,
    deadline_remaining_ms: int | None = None,
    asset_refs: list[str] | None = None,
) -> dict:
    """构造一帧完整信封（protocol_version 自动带当前版本）。"""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "trace_id": trace_id,
        "plugin_id": plugin_id,
        "plugin_release": plugin_release,
        "operation": operation,
        "invocation_id": invocation_id,
        "deadline_remaining_ms": deadline_remaining_ms,
        "input": input,
        "asset_refs": list(asset_refs) if asset_refs is not None else [],
    }


def validate_envelope(frame: Any) -> None:
    """信封字段校验；不合法即抛 ``ProtocolViolation``。"""
    if not isinstance(frame, dict):
        raise ProtocolViolation("信封必须是 JSON object")
    version = frame.get("protocol_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProtocolViolation("protocol_version 必须是整数")
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(f"protocol_version 不支持：{version}")
    for field in _REQUIRED_STR_FIELDS:
        value = frame.get(field)
        if not isinstance(value, str) or not value:
            raise ProtocolViolation(f"字段 {field} 必须是非空字符串")
    deadline = frame.get("deadline_remaining_ms")
    if deadline is not None and (
        isinstance(deadline, bool) or not isinstance(deadline, int) or deadline < 0
    ):
        raise ProtocolViolation("deadline_remaining_ms 必须是非负整数或 null")
    asset_refs = frame.get("asset_refs")
    if not isinstance(asset_refs, list) or any(
        not isinstance(item, str) for item in asset_refs
    ):
        raise ProtocolViolation("asset_refs 必须是字符串列表（只传 asset_id，不传资产本体）")


# ---------------------------------------------------------------------------
# 深度检查
# ---------------------------------------------------------------------------

def _measure_depth(value: Any) -> int:
    """迭代式测深：容器嵌套层数（标量 0 层）。超过上限立即抛违约，防深结构拖垮解析。"""
    max_seen = 0
    # (子值, 已累计层数) 栈；容器自身记 1 层
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, level = stack.pop()
        if isinstance(current, dict):
            depth = level + 1
            if depth > MAX_NESTING_DEPTH:
                raise ProtocolViolation(f"嵌套深度超限：{depth} > {MAX_NESTING_DEPTH}")
            max_seen = max(max_seen, depth)
            for child in current.values():
                stack.append((child, depth))
        elif isinstance(current, (list, tuple)):
            depth = level + 1
            if depth > MAX_NESTING_DEPTH:
                raise ProtocolViolation(f"嵌套深度超限：{depth} > {MAX_NESTING_DEPTH}")
            max_seen = max(max_seen, depth)
            for child in current:
                stack.append((child, depth))
    return max_seen


# ---------------------------------------------------------------------------
# 编码 / 解码
# ---------------------------------------------------------------------------

def encode_frame(envelope: Any) -> bytes:
    """信封 → 长度前缀帧字节。深度/字段/大小任一超限即 ``ProtocolViolation``。"""
    validate_envelope(envelope)
    _measure_depth(envelope)
    try:
        body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation(f"信封不可 JSON 序列化：{exc}") from exc
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolViolation(f"单帧超限：{len(body)} > {MAX_FRAME_BYTES} 字节")
    return _LENGTH_PREFIX.pack(len(body)) + body


def decode_frame(data: bytes) -> dict:
    """帧体字节（不含长度前缀）→ 信封 dict。只认 JSON，pickle 等一律拒绝。"""
    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolViolation("帧体必须是字节")
    if len(data) > MAX_FRAME_BYTES:
        raise ProtocolViolation(f"单帧超限：{len(data)} > {MAX_FRAME_BYTES} 字节")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        # 非 UTF-8（含 pickle 等二进制通道）一律违约：本协议不存在任何反序列化旁路
        raise ProtocolViolation(f"帧体不是合法 UTF-8（禁 pickle，只认 JSON）：{exc}") from exc
    try:
        frame = json.loads(text)
    except RecursionError as exc:
        raise ProtocolViolation("JSON 嵌套过深导致解析递归溢出") from exc
    except ValueError as exc:
        raise ProtocolViolation(f"帧体不是合法 JSON：{exc}") from exc
    _measure_depth(frame)
    validate_envelope(frame)
    return frame


# ---------------------------------------------------------------------------
# socket 收发
# ---------------------------------------------------------------------------

def send_frame(sock: socket.socket, envelope: Any) -> None:
    """发送一帧；超限在发送前拒绝（不会发出半帧）。"""
    sock.sendall(encode_frame(envelope))


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """精确读 count 字节；对端中断/截断按协议违约处理。"""
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise ProtocolViolation(f"帧截断：预期 {count} 字节，实收 {count - remaining}")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock: socket.socket) -> dict:
    """接收一帧。先验长度前缀（超限不读帧体，直接违约），再读体并全量校验。"""
    header = _recv_exact(sock, _LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length > MAX_FRAME_BYTES:
        raise ProtocolViolation(f"长度前缀超限：{length} > {MAX_FRAME_BYTES} 字节（拒绝读帧体）")
    return decode_frame(_recv_exact(sock, length))
