"""v21-R2 席（进程生命周期+适配器韧性）回归。全离线 mock，不启动 NoneBot。

覆盖项（对应实弹问题清单）：
- P2 QQ 未就绪：retcode=1200（ApiNotAvailable）不再终态拒收，改走
  bot_unavailable 挂起（retry_count 不消耗、90s 重探、连接恢复后送出）；
  管理员告警通道对 bot_unavailable 静默。
  **语义翻转记账（T78 席，2026-09-20，T46-N1 连带裁决）**：SnowLuma 下
  1200 只在「stream action dispatched without a sink」（INTERNAL_ERROR，
  config-GJCFWjtq.js:1440）发射，与「适配器无连接」旧 NapCat 语义已漂移
  （report-T46 §3.5 / report-T55 §二.1-§二.2 实复核）；真断线由 NoneBot
  ApiNotAvailable/NetworkError（无 .info.retcode）走瞬时异常路径。原挂起
  语义（R2 修复）对确定性内部错误只会无谓挂起 30 分钟 ⇒ 废除：1200 经
  `_is_final_failure_retcode` 白名单第 1 轮 FAILED_FINAL，混排请求由
  worker W1 文本降级接住文字部件。下方四个 P2 用例已按此改写（原挂起
  断言见 git 历史）；回滚点=恢复 onebot.py 的 1200 拦截分支与本文件原
  断言。队列侧 bot_unavailable 挂起机制仍由 test_bgroup_sender_delivery /
  test_prfix_sender 以手工构造 issue 锁定（防御基建未删）。
- P3 mail UNSEEN 搜索：超时退避重试、耗尽抛回外层重连（重连清早退缓存的
  a3e78a3 修复契约不回退）；mail worker 轮询 sleep 可被停机取消打断。
- P4 停机上限：bot.py 的 _reap_background_threads 在宽限期后对滞留
  非 daemon 线程强制收尾；无滞留时正常返回。
- P5 apscheduler misfire：bot.py 在调度器 start 前补设 job_defaults
  misfire_grace_time=30（AST 契约）。
- P1 TG：getUpdates 网络告警前 3 次逐条、之后每 5 次一条、恢复单条；
  bot.py 日志过滤对 TG setup/poll 失败全栈全量丢弃（AST+函数执行契约）。

运行（直跑纪律，禁 dev.ps1）：
    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
    python -m pytest tests/test_v21r2_lifecycle_r2.py --basetemp=%TEMP%/v21r2-r2 -p no:cacheprovider
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import error_report
from plugins.bot_unified_runtime.domains.transport.mail import mail_adapter
from plugins.bot_unified_runtime.domains.transport.sender import onebot as onebot_sender
from plugins.bot_unified_runtime.mail_adapter import search_unseen_with_backoff
from plugins.bot_unified_runtime.runtime import capability_protocols
from plugins.bot_unified_runtime.sender.queue import SQLiteSendRequestQueue
from plugins.bot_unified_runtime.sender.worker import (
    _notify_operational_issue_safely,
    drain_send_queue_once,
)

telegram_resilience = importlib.import_module("scripts.telegram_resilience")

BOT_PATH = Path(__file__).parents[1] / "bot.py"
MAIL_PATH = Path(mail_adapter.__file__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _send_request(
    request_id: str,
    dedupe_key: str,
    *,
    text: str = "R2 生命周期回归正文",
    content_type: str = "text",
    content_ref: dict[str, Any] | None = None,
) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type=content_type,
        content_ref=content_ref or {"text": text},
        text_fallback=text,
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=rendered,
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


class _ActionFailedLike(Exception):
    """鸭子类型模拟 nonebot ApiNotAvailable/ActionFailed（retcode 藏在 .info）。"""

    def __init__(self, retcode: int, status: str = "failed") -> None:
        super().__init__(f"ActionFailed retcode={retcode}")
        self.info = {"status": status, "retcode": retcode}


# ============================================================================
# P2：QQ 适配器未就绪 → 挂起而非拒收
# ============================================================================


class _ScriptedOneBot:
    """脚本化 fake bot：按序返回结果（Exception 则抛出）。"""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def send_private_msg(self, *, user_id: Any, message: Any) -> Any:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_p2_api_unavailable_exception_returns_final_retcode_failure() -> None:
    """异常形态 retcode=1200：终态化裁决后第 1 次 FAILED_FINAL+retcode_failure。

    语义翻转（2026-09-20 T46-N1，见模块头注）：原锁「挂起回执，绝不
    FAILED_FINAL」随 SnowLuma 1200=INTERNAL_ERROR 语义漂移废除。保留的
    不变量：拒绝分支**不内联三连重试**（重试风暴根修，与 retcode 无关）。
    """
    bot = _ScriptedOneBot([_ActionFailedLike(1200)])
    receipt = asyncio.run(
        onebot_sender.send_onebot_v11(bot, _send_request("req-p2a", "dk-p2a"))
    )
    assert bot.calls == 1, "未就绪拒收不得内联三连重试"
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "retcode_failure"
    assert receipt.operational_issue.retryable is False


def test_p2_failed_dict_retcode_1200_returns_final() -> None:
    """回执 dict 形态 retcode=1200：同样经白名单终态（终态化裁决）。"""
    bot = _ScriptedOneBot([{"status": "failed", "retcode": 1200}])
    receipt = asyncio.run(
        onebot_sender.send_onebot_v11(bot, _send_request("req-p2b", "dk-p2b"))
    )
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "retcode_failure"


def test_p2_chunks_path_retcode_1200_returns_final() -> None:
    """chunks 分片路径单段被拒 1200（零副作用）：同样白名单终态（裁决后）。"""
    request = _send_request(
        "req-p2c",
        "dk-p2c",
        content_type="chunks",
        content_ref={"chunks": ["第一段"]},
    )
    bot = _ScriptedOneBot([{"status": "failed", "retcode": 1200}])
    receipt = asyncio.run(onebot_sender.send_onebot_v11(bot, request))
    assert receipt.state is ReceiptState.FAILED_FINAL
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "retcode_failure"


@pytest.mark.parametrize(
    ("retcode", "expected_state"),
    [
        (-1, ReceiptState.FAILED_RETRYABLE),  # rich media 拒绝：保持既有可重试
        (403, ReceiptState.FAILED_FINAL),  # 明确永久拒绝：保持既有终态
    ],
)
def test_p2_non_unavailable_retcodes_keep_existing_semantics(
    retcode: int, expected_state: ReceiptState
) -> None:
    """回归锁：1200 之外的 retcode 分类零变化（不误伤重试风暴根修）。"""
    bot = _ScriptedOneBot([_ActionFailedLike(retcode)])
    receipt = asyncio.run(
        onebot_sender.send_onebot_v11(bot, _send_request("req-p2r", "dk-p2r"))
    )
    assert receipt.state is expected_state
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "retcode_failure"


@pytest.mark.asyncio
async def test_p2_retcode_1200_finalizes_in_one_round_without_retry(tmp_path: Path) -> None:
    """端到端（终态化裁决）：1200 拒绝第 1 轮 FAILED_FINAL，零重试零挂起。

    语义翻转（2026-09-20 T46-N1，见模块头注）：原锁「未就绪挂起（不烧重试
    预算/不打管理员）→ 恢复后送出」。终态化后对应不变量：第 1 轮终态、
    零重试预算消耗（终态不烧预算）、后续轮零认领零投递。
    """
    queue = SQLiteSendRequestQueue(tmp_path / "queue.sqlite3", InMemoryAuditLogger())
    base = _utc_now()
    # deliver_after=base：声明无内联首投，worker 即刻接管（绕开 submit 默认
    # 60s 内联认领宽限期，否则 drain 在 base+5s 认领不到任何行）。
    queue.submit(_send_request("req-p2e2e", "dk-p2e2e"), now=base, deliver_after=base)

    bot = _ScriptedOneBot([_ActionFailedLike(1200)])
    admin_alerts: list[Any] = []

    async def transport(request: SendRequest) -> Any:
        return await onebot_sender.send_onebot_v11(bot, request)

    audit = InMemoryAuditLogger()
    # pass 1：1200 拒绝 → 白名单第 1 轮终态（不再挂起等待）。
    result1 = await drain_send_queue_once(
        queue,
        transport,
        audit_logger=audit,
        now=base + timedelta(seconds=5),
        operational_notifier=admin_alerts.append,
    )
    assert result1.final_failed == 1
    assert bot.calls == 1, "拒绝分支不内联重试风暴"
    entry = queue._find_entry_by_request_id("req-p2e2e")
    assert entry is not None
    assert entry.retry_count == 0, "第 1 轮终态不消耗重试预算"
    assert entry.state is ReceiptState.FAILED_FINAL
    assert entry.next_retry_at is None, "终态行不再排程"

    # pass 2：终态行不再认领，零新投递。
    result2 = await drain_send_queue_once(
        queue,
        transport,
        audit_logger=audit,
        now=base + timedelta(seconds=120),
        operational_notifier=admin_alerts.append,
    )
    assert result2.checked == 0
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_p2_worker_alert_channel_silent_only_for_bot_unavailable() -> None:
    """bot_unavailable 静默；其余 issue 照常通知（抑制面不扩大）。"""
    pinged: list[str] = []
    hold_issue = OperationalIssue(
        stage="onebot",
        kind="bot_unavailable",
        retryable=True,
        safe_summary="bot_unavailable",
    )
    receipt = DeliveryReceipt(
        request_id="req-x",
        state=ReceiptState.FAILED_RETRYABLE,
        transport="onebot.v11",
        public_message="",
        operational_issue=hold_issue,
    )
    await _notify_operational_issue_safely(pinged.append, _send_request("req-x", "dk-x"), receipt)
    assert pinged == []

    fail_issue = OperationalIssue(
        stage="onebot",
        kind="retcode_failure",
        retryable=True,
        safe_summary="retcode_failure",
    )
    receipt2 = receipt.model_copy(update={"operational_issue": fail_issue})
    await _notify_operational_issue_safely(
        lambda r: pinged.append(str(r.operational_issue.kind)),
        _send_request("req-x", "dk-x"),
        receipt2,
    )
    assert pinged == ["retcode_failure"]


# ============================================================================
# P3：mail UNSEEN 搜索超时退避 + 重连强制重选箱
# ============================================================================


class _ScriptedSearchClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.search_calls = 0

    async def search(self, criteria: str) -> Any:
        self.search_calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _OkResponse:
    result = "OK"
    lines: ClassVar[list[bytes]] = []


@pytest.mark.asyncio
async def test_p3_search_timeout_retries_with_backoff_then_succeeds() -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = _ScriptedSearchClient([TimeoutError("imap timeout"), _OkResponse()])
    response = await search_unseen_with_backoff(
        client,
        attempts=2,
        timeout_seconds=0.05,
        retry_delays=(2.0,),
        sleep=fake_sleep,
    )
    assert response is not None
    assert client.search_calls == 2
    assert sleeps == [2.0], "超时后按退避档重试"


@pytest.mark.asyncio
async def test_p3_search_timeout_exhausted_raises_for_reconnect() -> None:
    """重试预算耗尽仍超时 → 原样抛出（外层整链重连=强制重新 select_mailbox）。"""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = _ScriptedSearchClient([TimeoutError("t1"), TimeoutError("t2")])
    with pytest.raises(TimeoutError):
        await search_unseen_with_backoff(
            client,
            attempts=2,
            timeout_seconds=0.05,
            retry_delays=(2.0,),
            sleep=fake_sleep,
        )
    assert client.search_calls == 2
    assert sleeps == [2.0]


def test_p3_reconnect_forced_reselect_contract_preserved() -> None:
    """a3e78a3 契约：重连路径必须先清 mailbox 早退缓存再真发 SELECT。"""
    source = MAIL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MAIL_PATH))
    check = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_check_mailbox"
    )
    segment = ast.get_source_segment(source, check) or ""
    reset_pos = segment.find("bot.mailbox = None")
    select_pos = segment.find("await bot.select_mailbox()")
    assert reset_pos != -1, "重连必须清 bot.mailbox 早退缓存（a3e78a3）"
    assert select_pos != -1
    assert reset_pos < select_pos, "清缓存必须发生在 select_mailbox 之前"


@pytest.mark.asyncio
async def test_p3_fetch_new_mail_times_out_and_raises_for_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_fetch_new_mail 在搜索持续超时时向上抛出（进入重连路径）。"""
    monkeypatch.setattr(mail_adapter, "_MAIL_SEARCH_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(mail_adapter, "_MAIL_SEARCH_RETRY_DELAYS", (0.0,))
    client = _ScriptedSearchClient([TimeoutError("t1"), TimeoutError("t2")])
    bot = SimpleNamespace(
        self_id="mail-probe",
        mailbox="INBOX",
        readonly=False,
        imap_client=client,
    )
    adapter = object.__new__(mail_adapter.ResilientMailAdapter)
    with pytest.raises(TimeoutError):
        await adapter._fetch_new_mail(bot)
    assert client.search_calls == 2


@pytest.mark.asyncio
async def test_p3_mail_worker_poll_sleep_interruptible_by_shutdown() -> None:
    """停机可中断：mail worker 的轮询 sleep 被外部 cancel 立即退出（<1s）。"""
    adapter = object.__new__(mail_adapter.ResilientMailAdapter)

    class _FakeClient:
        async def logout(self) -> None:
            return None

    async def _true() -> bool:
        return True

    bot = SimpleNamespace(
        self_id="mail-probe",
        bot_info=SimpleNamespace(imap=SimpleNamespace(tls=False, host="x", port=1)),
        imap_client=_FakeClient(),
        mailbox=None,
        readonly=False,
        login=_true,
        select_mailbox=_true,
    )
    adapter._new_imap_client = lambda bot_info: _FakeClient()  # type: ignore[method-assign]
    adapter.bot_connect = lambda bot_: None  # type: ignore[method-assign]
    adapter.bot_disconnect = lambda bot_: None  # type: ignore[method-assign]

    async def _noop_fetch(_bot: Any) -> None:
        return None

    async def _noop_close(_bot: Any) -> None:
        return None

    adapter._fetch_new_mail = _noop_fetch  # type: ignore[method-assign]
    adapter._close_mailbox = _noop_close  # type: ignore[method-assign]

    task = asyncio.create_task(adapter._check_mailbox(bot))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert time.monotonic() - started < 1.0, "轮询 sleep 必须可被停机取消打断"


@pytest.mark.asyncio
async def test_p2_onebot_retry_sleep_interruptible_by_shutdown() -> None:
    """停机可中断：onebot 内联重试 sleep 被 cancel 立即上抛 CancelledError。"""

    async def _always_fail(**_kwargs: Any) -> Any:
        raise OSError("connection lost")

    bot = SimpleNamespace(send_private_msg=_always_fail)

    async def _cancel_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    # 完整 asyncio 影子模块：只换 sleep，其余（wait_for/CancelledError 等）
    # 委托真 asyncio——send 路径的 wait_for 超时包裹必须照常工作。
    shim = ModuleType("asyncio_r2_shim")
    for _attr in dir(asyncio):
        if not _attr.startswith("_"):
            setattr(shim, _attr, getattr(asyncio, _attr))
    shim.sleep = _cancel_sleep  # type: ignore[attr-defined]

    original_sleep = onebot_sender.asyncio
    onebot_sender.asyncio = shim  # type: ignore[assignment]
    try:
        with pytest.raises(asyncio.CancelledError):
            await onebot_sender.send_onebot_v11(
                bot, _send_request("req-p4b", "dk-p4b")
            )
    finally:
        onebot_sender.asyncio = original_sleep  # type: ignore[assignment]


# ============================================================================
# P4：停机宽限上限（bot.py reaper，AST 摘取执行）
# ============================================================================


@pytest.fixture(autouse=True)
def _isolate_module_pools() -> Iterator[None]:
    """测试期收口两个模块级常驻线程池。

    2026-09-18：``test_p4_reaper_returns_cleanly_when_no_stuck_threads`` 断言
    「无滞留非 daemon 线程时 reaper 正常返回」，而下列池的 worker 都是**非 daemon**
    线程、只经 ``atexit.register(...)`` 收口——同批跑过会实例化它们的用例后，
    reaper 扫描就会看到它们，断言随**用例执行顺序**飘（单独跑绿、全量跑红）。

    已定位两个污染源（第二个是**真正的根因**，第一个是同一批次的伴生项）：

    1. ``error_report._RENDER_POOL``（``error-card-render_0``）——由
       ``test_error_card_async`` 一类用例拉起；
    2. ``capability_protocols._EXECUTOR``（``cap-proto_0`` / ``cap-proto_1``）——
       由 ``tests/test_v21_s10_protocols.py`` 拉起。复现：
       ``pytest tests/test_v21_s10_protocols.py tests/test_v21r2_lifecycle_r2.py``
       → ``1 failed``，日志明写
       ``停机宽限 1s 后仍有后台线程未退出（cap-proto_0, cap-proto_1）``。

    产品侧实现是正确的（atexit 收口 + ``wait=True`` 且不取消排队任务，符合
    L-12 审查口径），缺的是测试期 teardown：前置清一次挡前序文件的残留，
    后置清一次不让本文件的残留漏给下一个文件。两个收口钩子都幂等，可重复调用。
    """

    error_report._shutdown_render_pool()
    capability_protocols._shutdown_capability_executor()
    yield
    error_report._shutdown_render_pool()
    capability_protocols._shutdown_capability_executor()


def _load_bot_namespace(names: set[str]) -> dict[str, Any]:
    """从 bot.py 摘取顶层 import + 指定函数到独立命名空间（bot 模块级会
    触发 nonebot.init 与全插件加载，不能整文件 import；同
    tests/test_bot_supervisor.py 的既定模式）。"""
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        )
    ]
    found = {
        node.name
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert names <= found, f"bot.py 缺少预期函数: {names - found}"
    namespace: dict[str, Any] = {"__file__": str(BOT_PATH), "__name__": "bot_r2_under_test"}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BOT_PATH), "exec"), namespace)  # noqa: S102
    return namespace


def test_p4_reaper_forces_exit_after_grace_when_threads_stuck() -> None:
    ns = _load_bot_namespace({"_reap_background_threads"})
    gate = threading.Event()
    stuck = threading.Thread(target=gate.wait, name="r2-stuck-probe", daemon=False)
    stuck.start()
    exits: list[int] = []
    started = time.monotonic()
    try:
        ns["_reap_background_threads"](0.2, _force_exit=exits.append)
        elapsed = time.monotonic() - started
        assert exits == [0], "滞留非 daemon 线程超宽限期必须强制收尾"
        assert elapsed < 5.0, "停机上限必须真正封顶等待时间"
    finally:
        gate.set()
        stuck.join(timeout=5)


def test_p4_reaper_returns_cleanly_when_no_stuck_threads() -> None:
    ns = _load_bot_namespace({"_reap_background_threads"})
    daemon_probe = threading.Thread(target=time.sleep, args=(0.05,), daemon=True)
    daemon_probe.start()
    exits: list[int] = []
    ns["_reap_background_threads"](1.0, _force_exit=exits.append)
    assert exits == [], "无滞留线程时正常返回，不强制退出"
    daemon_probe.join(timeout=5)


def test_p4_main_block_wires_reaper_into_shutdown() -> None:
    """bot.py 的 __main__ 必须经 finally 接入 reaper（KeyboardInterrupt 不逃逸）。"""
    source = BOT_PATH.read_text(encoding="utf-8")
    main_block = source[source.rfind('if __name__ == "__main__":'):]
    assert "finally:" in main_block
    assert "_reap_background_threads()" in main_block
    assert "except KeyboardInterrupt" in main_block


# ============================================================================
# P5：apscheduler misfire grace（AST 契约）
# ============================================================================


def test_p5_misfire_grace_configured_before_scheduler_start() -> None:
    source = BOT_PATH.read_text(encoding="utf-8")
    configure_pos = source.find('job_defaults={"misfire_grace_time": 30}')
    assert configure_pos != -1, "bot.py 必须设置 job_defaults misfire_grace_time=30"
    load_pos = source.find("nonebot.load_from_toml(")
    assert load_pos != -1
    assert configure_pos > load_pos, "configure 必须在插件加载后（scheduler 已创建）"
    # 精确锚定真实主入口块（文件前部另有 supervisor 分叉的
    # `if __name__ == "__main__" and _supervision_requested():`，带后缀，
    # 不含本子串）。
    start_pos = source.find('if __name__ == "__main__":')
    assert start_pos != -1
    assert configure_pos < start_pos, "configure 必须在任何 start 之前（模块导入期）"

    tree = ast.parse(source, filename=str(BOT_PATH))
    configured = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "configure"
        ):
            for keyword in node.keywords:
                if keyword.arg == "job_defaults" and isinstance(keyword.value, ast.Dict):
                    for key, value in zip(keyword.value.keys, keyword.value.values):
                        if (
                            isinstance(key, ast.Constant)
                            and key.value == "misfire_grace_time"
                            and isinstance(value, ast.Constant)
                            and value.value == 30
                        ):
                            configured = True
    assert configured


def test_p4_early_shutdown_hook_registered_before_plugin_load() -> None:
    """早停钩子必须在 load_from_toml 之前注册（先于插件自带的关调度器钩子）。"""
    source = BOT_PATH.read_text(encoding="utf-8")
    hook_pos = source.find("@driver.on_shutdown")
    load_pos = source.find("nonebot.load_from_toml(")
    assert hook_pos != -1 and load_pos != -1
    assert hook_pos < load_pos


# ============================================================================
# P1：TG 告警降频 + 上游全栈丢弃
# ============================================================================


def test_p1_get_updates_alert_throttled_then_single_recovery_line() -> None:
    """前 3 次逐条告警，第 4 次起每 5 次一条；恢复只记一条。"""
    from unittest.mock import AsyncMock, Mock

    class _NE(Exception):
        pass

    outcomes = [_NE("offline") for _ in range(9)] + [[]]
    request = AsyncMock(side_effect=outcomes)

    class _Adapter:
        async def _call_api(self, bot: Any, api: str, **data: Any) -> Any:
            return await request(bot, api, **data)

    logger = SimpleNamespace(warning=Mock(), info=Mock())
    sleep = AsyncMock()
    builder = telegram_resilience.build_resilient_telegram_adapter
    cls = builder(_Adapter, network_error=_NE, logger=logger, sleep=sleep)
    assert asyncio.run(cls()._call_api(object(), "getUpdates")) == []
    assert [call.args[0] for call in sleep.call_args_list] == [3, 6, 12, 24, 48, 60, 60, 60, 60]
    warning_failures = [call.args[2] for call in logger.warning.call_args_list]
    # 实现的 warning 参数序：（格式串, phase, failures, 异常类型名, delay）。
    assert warning_failures == [1, 2, 3, 5], "第 4 次起每 5 次才记一条"
    assert logger.info.call_count == 1, "恢复只记一条"


def _load_filter_namespace() -> dict[str, Any]:
    """摘取 bot.py 的 TG 日志过滤函数与其状态（隔离执行）。"""
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    wanted = {"_rate_limited_log_filter"}
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    body.append(node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id.startswith("_POLL_FAILURE"):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    namespace: dict[str, Any] = {
        "default_filter": lambda record: True,  # 上游默认过滤的桩：全放行
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BOT_PATH), "exec"), namespace)  # noqa: S102
    return namespace


def test_p1_tg_setup_and_poll_failure_full_stacks_are_dropped() -> None:
    ns = _load_filter_namespace()
    log_filter = ns["_rate_limited_log_filter"]

    def _record(message: str) -> dict[str, str]:
        return {"message": message}

    # 连续多条（模拟重试风暴期上游每轮打 ERROR+栈）：全量丢弃。
    for _ in range(5):
        assert log_filter(_record("Setup for bot 8887340775 failed: NetworkError ...")) is False
        assert log_filter(_record("Get updates for bot 8887340775 failed ...")) is False
    assert ns["_POLL_FAILURE_STATE"]["suppressed"] == 10


def test_p1_onebot_reconnect_keeps_cooldown_and_other_logs_pass() -> None:
    ns = _load_filter_namespace()
    log_filter = ns["_rate_limited_log_filter"]

    def _record(message: str) -> dict[str, str]:
        return {"message": message}

    assert log_filter(_record("Error while setup websocket ...")) is True
    assert log_filter(_record("Error while setup websocket ...")) is False
    assert log_filter(_record("Application startup complete")) is True
