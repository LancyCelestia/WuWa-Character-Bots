"""Telegram 网络恢复边界，不导入 Bot 插件、不修改上游类、不重复出站。

NoneBot Telegram 的 poll 内部自行捕获 getUpdates 异常，故仅在 poll 外层
重试无法覆盖运行中断线。用子类在只读 getUpdates 请求边界重试 NetworkError；
保留上游 offset、事件解析、连接登记与 shutdown 语义。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


def is_transient_telegram_error(exc: Exception) -> bool:
    """只重试传输故障、429 与 5xx；上游也把 409 等包装成 NetworkError。"""
    from httpx import RequestError

    if isinstance(getattr(exc, "__cause__", None), (RequestError, OSError)):
        return True
    message = getattr(exc, "msg", None)
    prefix = "Received unexpected "
    if not isinstance(message, str) or not message.startswith(prefix):
        return False
    code = message[len(prefix):len(prefix) + 3]
    return code == "429" or (code.isascii() and code.isdigit() and 500 <= int(code) <= 599)


# 鉴权 401/403 与 getUpdates 实例冲突 409 不是临时故障：重试只会烧穿退避
# 预算，409 更会形成两实例互相踢 token 的死循环（V2.1 风险 6；合同见
# docs/design/backend-v2-implementation-guide.md §7：仅网络/TLS 临时错误/
# 429/5xx 退避）。上游把它们也包装成 NetworkError（msg="Received unexpected
# NNN ..."），只能从消息前缀取三位码判别；消息体可能含 token，绝不落原文。
_PERMANENT_STATUSES = frozenset({"401", "403", "409"})


def permanent_telegram_status(exc: Exception) -> str | None:
    """返回该异常对应的「不可重试」状态码（401/403/409），否则 None。"""
    message = getattr(exc, "msg", None)
    prefix = "Received unexpected "
    if not isinstance(message, str) or not message.startswith(prefix):
        return None
    code = message[len(prefix):len(prefix) + 3]
    return code if code in _PERMANENT_STATUSES else None


def build_resilient_telegram_adapter(
    adapter_type: type,
    *,
    network_error: type[Exception],
    logger: Any,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    retryable: Callable[[Exception], bool] | None = None,
) -> type:
    async def retry(
        operation: Callable[[], Awaitable[Any]],
        phase: str,
        *,
        catch_all: bool = False,
        permanent: Callable[[Exception], str | None] | None = None,
    ) -> Any:
        """网络故障指数退避重试；``catch_all``（startup 专用）把任意异常都
        挡在本层——2026-09-16 实测：TG 代理抖动时 setup 异常会沿启动链
        逃逸（__cause__ 链丢失导致 is_transient 误判 False），连带进程级
        启动失败，QQ 侧一并吞消息。启动阶段绝不允许逃逸。

        ``permanent``（与 catch_all 搭配，poll 阶段专用）：先于退避分类，
        命中 401/403/409 等不可重试状态码时记定向告警并**停止本层轮询**
        （返回 None 结束，不上抛）——鉴权失败重试无意义、409 重试是两实例
        互踢 token，且按合同不得把它们称作"网络暂不可用"；同时保持
        2026-09-16 的不变量：异常仍不沿启动链逃逸炸掉整个进程。
        其余未知异常（代理抖动等形态不定的临时故障）维持 catch_all 退避。
        """
        failures = 0
        delay = 3.0
        while True:
            try:
                result = await operation()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not catch_all:
                    if not isinstance(exc, network_error):
                        raise
                    if retryable is not None and not retryable(exc):
                        raise
                elif permanent is not None and (status := permanent(exc)) is not None:
                    reason = (
                        "实例冲突（另一实例正在 getUpdates，停止争抢）"
                        if status == "409"
                        else "鉴权失败（token 无效或被吊销，暂停重试）"
                    )
                    logger.warning(  # noqa: PLE1205 - NoneBot 使用 Loguru 的花括号格式。
                        "Telegram {} 检测到非临时故障：HTTP {}，{}。"
                        "这不是网络问题，已停止本层重试；请处理后重启进程。",
                        phase, status, reason,
                    )
                    return None
                failures += 1
                # R2（2026-09-17 实弹降噪）：前 3 次每条都记（快速可见），
                # 之后每 5 次记一条（退避已封顶 60s，5 次 ≈ 5 分钟，持续
                # 断网期不刷屏）；恢复时只在下方记一条「已恢复」。断网期
                # 的完整堆栈由 bot.py 日志过滤丢弃（上游每轮 poll 打的
                # ERROR+栈对本层重试无增量信息）。
                if failures <= 3 or failures % 5 == 0:
                    # 只记异常类型名，不记 message/cause——错误文本可能含 token。
                    logger.warning(  # noqa: PLE1205 - NoneBot 使用 Loguru 的花括号格式。
                        "Telegram {} 网络暂不可用；这是适配器重试，不是 NoneBot 启动失败。"
                        "请检查代理与 Telegram 连通性；累计失败 {} 次（{}），{:.0f}s 后重试。",
                        phase, failures, type(exc).__name__, delay,
                    )
                await sleep(delay)
                delay = min(delay * 2.0, 60.0)
            else:
                if failures:
                    logger.info("Telegram {} 已恢复，累计重试 {} 次。", phase, failures)  # noqa: PLE1205 - Loguru 格式。
                return result

    class ResilientTelegramAdapter(adapter_type):
        async def poll(self, bot: Any) -> Any:
            original = super().poll
            # V2.1 风险 6：poll 不再无条件按"网络故障"退避——401/403/409
            # 先经 permanent 分类停轮询+定向告警，其余异常保持 catch_all
            # 退避（启动链不容逃逸）；offset/事件解析/取消语义全在上游
            # original(bot) 内，本层不触碰。
            return await retry(
                lambda: original(bot),
                "startup",
                catch_all=True,
                permanent=permanent_telegram_status,
            )

        async def _call_api(self, bot: Any, api: str, **data: Any) -> Any:
            original = super()._call_api
            # 仅轮询读取可无限重试；sendMessage 等出站失败的结果可能 UNKNOWN，
            # 必须留给统一 SendQueue/Receipt，不在此层偷偷重放。
            if api in {"get_updates", "getUpdates"}:
                return await retry(lambda: original(bot, api, **data), "getUpdates")
            return await original(bot, api, **data)

    return ResilientTelegramAdapter
