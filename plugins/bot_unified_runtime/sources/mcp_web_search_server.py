"""stdio MCP（JSON-RPC 2.0）联网搜索服务器，零第三方依赖、可独立运行。

- 从 stdin 逐条读取请求：兼容“一行一个 JSON”和 ``Content-Length: N\\r\\n\\r\\n``
  两种帧格式；
- 响应逐行写 stdout（``ensure_ascii=False``），日志只写 stderr，绝不污染 stdout；
- 暴露一个工具 ``web_search``，内部复用 ``search_async`` 的 DDG → Bing 异步链式检索；
- 解析失败返回 -32700，未知方法返回 -32601，通知（含 notifications/initialized）忽略。

运行：``python -m plugins.bot_unified_runtime.sources.mcp_web_search_server``
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, BinaryIO, TextIO

try:  # 包内运行/测试导入：python -m plugins.bot_unified_runtime.sources.mcp_web_search_server
    from .web_search import WebSearchHit, search_async
except ImportError:  # 直接作为脚本运行时的兜底导入
    from plugins.bot_unified_runtime.sources.web_search import (  # type: ignore[no-redef]
        WebSearchHit,
        search_async,
    )

SERVER_NAME = "shorekeeper-web-search"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "要检索的查询词"},
        "max_results": {"type": "integer", "default": 6},
    },
    "required": ["query"],
}

_LOGGER = logging.getLogger(__name__)


def _json_line(response: dict[str, Any]) -> str:
    """把响应对象编码为单行 JSON（不转义中文）。"""
    return json.dumps(response, ensure_ascii=False) + "\n"


def _rpc_result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _rpc_error(
    message_id: Any, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _write_line(stdout: TextIO, response: dict[str, Any] | None) -> str | None:
    """把响应写成一行并 flush；无响应（通知）返回 None。

    真实进程 stdout 显式按 UTF-8 字节写出，避免受 Windows 控制台代码页影响；
    测试注入 StringIO 时仍走普通文本写出。
    """
    if response is None:
        return None
    line = _json_line(response)
    buffer = getattr(stdout, "buffer", None)
    if buffer is not None:
        buffer.write(line.encode("utf-8"))
        buffer.flush()
    else:
        stdout.write(line)
        stdout.flush()
    return line


def _coerce_max_results(value: Any) -> int:
    """把 max_results 规整为 1..20 的整数，非法值回退默认 6。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 6
    return max(1, min(parsed, 20))


def _hits_payload(hits: list[WebSearchHit]) -> dict[str, Any]:
    """把搜索命中转换为 tools/call 文本载荷。"""
    return {
        "hits": [
            {
                "title": hit.title,
                "snippet": hit.snippet,
                "url": hit.url,
                "source_domain": hit.source_domain,
            }
            for hit in hits
        ]
    }


def _tool_error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _tools_list_result() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "web_search",
                "description": "联网搜索网页，按来源域名排序并过滤垃圾结果，返回标题、摘要、链接和来源域名。",
                "inputSchema": _TOOL_SCHEMA,
            }
        ]
    }


def _handle_initialize(message: dict[str, Any]) -> dict[str, Any]:
    return _rpc_result(
        message.get("id"),
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


async def _handle_tools_call(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return _tool_error_result("tools/call 缺少 params")
    name = str(params.get("name", "") or "")
    if name != "web_search":
        return _tool_error_result(f"未知工具: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _tool_error_result("arguments 必须是对象")
    query = str(arguments.get("query", "") or "").strip()
    max_results = _coerce_max_results(arguments.get("max_results", 6))
    if not query:
        return _tool_error_result("query 不能为空")
    try:
        hits = await search_async(query, max_results=max_results)
    except Exception as exc:
        _LOGGER.warning("web_search 执行失败: %s", exc)
        return _tool_error_result(f"搜索失败: {exc}")
    payload = _hits_payload(hits)
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
        ],
        "isError": False,
    }


async def handle_request(
    payload: bytes | str, stdout: TextIO | None = None
) -> str | None:
    """处理一条请求并写出响应，返回写出的 JSON 行；通知/空行返回 None。

    此函数把“读一行 → 处理 → 写一行”的核心逻辑独立出来，测试可直接
    注入多行 JSON 与 StringIO 验证往返，无需启动子进程。
    """
    if stdout is None:
        stdout = sys.stdout
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    payload = payload.strip()
    if not payload:
        return None
    try:
        message = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return _write_line(stdout, _rpc_error(None, -32700, "请求不是合法的 JSON"))
    if not isinstance(message, dict):
        return _write_line(stdout, _rpc_error(None, -32700, "JSON-RPC 请求必须是对象"))

    message_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        if "id" in message:
            return _write_line(stdout, _rpc_error(message_id, -32600, "缺少 method"))
        return None
    if method.startswith("notifications/"):
        return None  # notifications/initialized 等通知一律忽略。
    if "id" not in message:
        return None  # JSON-RPC 2.0：不带 id 的请求是通知，不写响应。

    if method == "initialize":
        return _write_line(stdout, _handle_initialize(message))
    if method == "tools/list":
        return _write_line(stdout, _rpc_result(message_id, _tools_list_result()))
    if method == "tools/call":
        result = await _handle_tools_call(message.get("params"))
        return _write_line(stdout, _rpc_result(message_id, result))
    return _write_line(stdout, _rpc_error(message_id, -32601, f"未知方法: {method}"))


async def _read_content_length_payload(
    stdin: BinaryIO, first_line: bytes, loop: asyncio.AbstractEventLoop
) -> bytes:
    """读取 Content-Length 帧：跳过头区空行后按字节数取 JSON 正文。"""
    try:
        length_text = first_line.decode("ascii", "ignore").split(":", 1)[1].strip()
        length = int(length_text)
    except (IndexError, ValueError):
        _LOGGER.warning("Content-Length 头无效，按普通行处理: %r", first_line)
        return first_line
    if length <= 0:
        return b""
    while True:
        line = await loop.run_in_executor(None, stdin.readline)
        if not line or line.strip() == b"":
            break
    return await loop.run_in_executor(None, stdin.read, length)


async def _iter_payloads(stdin: BinaryIO):
    """逐消息产出请求字节串，EOF 时正常结束。"""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, stdin.readline)
        if not line:
            return
        if line.strip().lower().startswith(b"content-length:"):
            payload = await _read_content_length_payload(stdin, line, loop)
            if payload.strip():
                yield payload
            continue
        if line.strip():
            yield line


async def run_stdio(
    stdin: BinaryIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """读一条请求 → 处理 → 写一条响应；stdin/stdout 可注入，便于测试。"""
    if stdin is None:
        stdin = sys.stdin.buffer
    if stdout is None:
        stdout = sys.stdout
    async for payload in _iter_payloads(stdin):
        try:
            await handle_request(payload, stdout)
        except Exception as exc:
            _LOGGER.exception("处理请求失败: %s", exc)
            try:
                _write_line(stdout, _rpc_error(None, -32603, f"内部错误: {exc}"))
            except Exception:
                pass


async def main() -> None:
    """入口：stdio 帧解析 + JSON-RPC 分发；stderr 仅用于日志。"""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await run_stdio()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass