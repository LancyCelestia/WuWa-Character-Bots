"""X4b：管线「能力正文无条件下放线程池」的判据锁（2026-10-02 收尾席）。

背景需求（治事件循环被同步腿冻住）
--------------------------------
根汇口过去按一张「可下放名单」（``__init__.OFFLOADED_CAPABILITY_IDS``）决定这一轮走
``RuntimePipeline.handle_async``（正文下放线程池）还是走 ``RuntimePipeline.handle``
（正文与完成腿都在**调用线程**上直呼）。名单外的一枚同步命令只要正文里有阻塞件
（SQLite / 文件 / subprocess / Playwright），冻住的就不是那一条命令，而是整片会话。
低频管理命令 ``/bot recent``（多份 SQLite 反查）、``/bot queue``、``/bot logs``、
``/bot runtime``（热改态 os.replace 落盘）、``/bot setup llm``（引导卡渲染）都不在名单上。

X4 波把「要不要下放」从**名单决定**改成**能力正文自己决定**：``handle_async`` 顶部
``capability = ensure_offloaded(capability)``——只有本身就是协程的 callable 留在循环上
（那是它唯一不占循环的形态），其余一律经 ``offload_capability`` 进管线专用有界池。

本锁钉住四件事（全离线，零端口零网络零 QQ；完成腿与幂等认领序不许被误伤）：

1. 下放决定权已从名单转移到「是不是协程」——``handle_async`` 里 ``ensure_offloaded``
   是**无条件**顶层语句（不套 ``if id in <名单>``），且只作用在 ``capability`` 上，
   **绝不作用在完成腿 ``_complete`` 上**（A-22 在册坑：``SendQueue.submit`` 的认领台账
   按 ``current_task()`` 记账，把 ``_complete`` 搬进线程会静默吃掉登记）。
2. 下放机不是空转：``ensure_offloaded → offload_capability`` 真接到线程执行器
   （``run_in_executor``/``to_thread`` 两形都认——⚠ 接线 AST 锁只认直呼形会把「在」
   读成「无人调用」，这是在册教训）。
3. 行为面（运行时现算）：同步命令正文经 ``handle_async`` 跑在**非循环线程**上；
   原生协程正文**留在循环上、绝不被多包一层线程**（反向不误伤）。
4. 注毒自证：把某枚同步命令的执行路径合成改回「直呼循环」⇒ 正文就钉在循环线程上，
   即第 3 点正向断言必红——证明该断言是有牙的，不是恒绿快照。

幂等认领序（A-18）与超时抛法（``CapabilityTimeout``）一字未动：``ensure_offloaded``
排在 ``self._prepare`` **之前**只是给 callable 换装，门禁/限流/claim 全在 ``_prepare``
内部按原序发生（claim 仍在 ``_prepare`` 的全部门禁之后），超时抛法住
``offload_capability.wrapped``。这些语义由 ``tests/test_pipeline_hard_timeout.py`` 与本席
复跑共同守住。

⚠ 完成度告警（写进工单，不在本锁假装绿）：本锁只覆盖**管线层**。名单真正失去执行路径
决定权还要求**根汇口**（``__init__.py`` 的 ``_run_capability_through_pipeline``）不再按
名单二选一 ``handle``/``handle_async``；那一面属别席（本席禁写 ``__init__.py``），见
``patches/X4b-PIPELINE-OFFLOAD-20261002.md``。
"""

from __future__ import annotations

import ast
import asyncio
import functools
import inspect
import logging
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    pipeline as pipeline_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    RuntimePipeline,
    _BoundedSubmissionGate,
    ensure_offloaded,
    is_native_async_callable,
    offload_capability,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(session_id: str = "private:x4b") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u-x4b",
        plain_text="潮汐很安静",
        message_id="m-x4b",
    )


def _result() -> CapabilityResult:
    return CapabilityResult(request_id="req-x4b", kind="text", body="我在。")


def _installed_pool(
    max_workers: int,
) -> tuple[ThreadPoolExecutor, _BoundedSubmissionGate, tuple[Any, Any]]:
    """向 pipeline 注入独立测试池，返回（池, 闸, 原状）供 finally 还原。"""
    pool = ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="x4b-test-pool"
    )
    gate = _BoundedSubmissionGate(max_workers * 2)
    original = (pipeline_module._chat_pool, pipeline_module._chat_pool_gate)
    pipeline_module._chat_pool = pool
    pipeline_module._chat_pool_gate = gate
    return pool, gate, original


def _make_pipeline() -> RuntimePipeline:
    return RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )


def _record_execution(obs: dict[str, Any]) -> None:
    """在能力正文里现场取证：跑在哪个线程、那个线程上有没有在转的事件循环。

    循环线程 = ``asyncio.get_running_loop()`` 能取到 loop 的那个线程（pytest 把测试
    协程跑在它上面）；线程池 worker 没有运行中的循环 ⇒ ``get_running_loop`` 抛
    RuntimeError。据此可无歧义区分「留在循环上」与「下放线程池」。
    """
    try:
        asyncio.get_running_loop()
        on_loop = True
    except RuntimeError:
        on_loop = False
    obs["ran"] = True
    obs["on_loop"] = on_loop
    obs["thread_ident"] = threading.get_ident()
    obs["thread_name"] = threading.current_thread().name


async def _loop_thread_ident() -> int:
    """取测试事件循环所在线程的 ident（与被测正文的执行线程对照）。"""
    return threading.get_ident()


# ===========================================================================
# ① 单元层：「是不是协程」决定下放，幂等且绝不二次包装
# ===========================================================================


def test_is_native_async_callable_classification() -> None:
    """下放判据＝「正文本身是不是协程」，不是「在不在名单上」。"""

    def sync_cap(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return _result()

    async def async_cap(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return _result()

    class _AsyncCall:  # 带 ``async def __call__`` 的可调用对象
        async def __call__(self, message: Any, decision: Any) -> CapabilityResult:
            return _result()

    class _SyncCall:  # 带同步 ``__call__`` 的可调用对象（潜在阻塞件）
        def __call__(self, message: Any, decision: Any) -> CapabilityResult:
            return _result()

    assert is_native_async_callable(async_cap) is True
    assert is_native_async_callable(functools.partial(async_cap)) is True
    assert is_native_async_callable(_AsyncCall()) is True, "补的 __call__ 那格不许退化"
    assert is_native_async_callable(sync_cap) is False
    assert is_native_async_callable(_SyncCall()) is False
    assert is_native_async_callable(functools.partial(sync_cap)) is False


def test_ensure_offloaded_passes_through_native_async() -> None:
    """协程正文原样返回（逐字节现状）：既不多包一层线程，也不换掉这枚 callable。"""

    async def async_cap(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return _result()

    assert ensure_offloaded(async_cap) is async_cap


def test_ensure_offloaded_wraps_sync_once_and_is_idempotent() -> None:
    """同步正文包成协程；对产物再包一次必须短路（包两层＝有界闸各占一格＝池容量减半）。"""

    def sync_cap(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        return _result()

    once = ensure_offloaded(sync_cap)
    assert once is not sync_cap
    assert is_native_async_callable(once) is True, "下放产物必须是协程函数（第二层短路的前提）"

    twice = ensure_offloaded(once)
    assert twice is once, "二次包装＝把有界池容量悄悄砍半；ensure_offloaded 必须幂等"


# ===========================================================================
# ② 接线层（AST，认直呼形 + 认 to_thread/run_in_executor 两形）
# ===========================================================================


def _attr_call_names(tree: ast.AST) -> set[str]:
    """收集所有 ``x.attr(...)`` 形式调用的属性名（``loop.run_in_executor`` /
    ``asyncio.to_thread`` 都属此形）。只认 ``Name`` 直呼会漏掉它们 ⇒ 见文件头教训。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _bare_call_names(tree: ast.AST) -> set[str]:
    """收集所有直呼形 ``name(...)`` 的函数名（``ensure_offloaded(capability)``）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _func_node(source_owner: Any, qualname_leaf: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    src = textwrap.dedent(inspect.getsource(source_owner))
    module = ast.parse(src)
    if isinstance(source_owner, type):
        for node in ast.walk(module):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname_leaf:
                return node
        raise AssertionError(f"{qualname_leaf} 未在 {source_owner.__name__} 里找到")
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == qualname_leaf:
            return node
    raise AssertionError(f"顶层函数 {qualname_leaf} 未找到")


def test_handle_async_offloads_unconditionally_only_capability_never_complete() -> None:
    """下放收口的形状锁：``capability = ensure_offloaded(capability)`` 必须是

    - 函数体**顶层语句**（不在任何 ``if`` 分支里 ⇒ 名单对它不再有决定权）；
    - 排在 ``self._prepare`` 之前（redrive 存的就是这枚已换装的 callable）；
    - 参数只能是 ``capability``，**绝不**作用在完成腿 ``_complete`` 上（A-22）。
    """
    fn = _func_node(RuntimePipeline, "handle_async")
    body = fn.body

    # 顶层直接子语句里出现 ensure_offloaded 的赋值 ⇒ 无条件（非嵌套在 If/Try 里）。
    top_assign = next(
        (
            stmt
            for stmt in body
            if isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "ensure_offloaded"
        ),
        None,
    )
    assert top_assign is not None, (
        "handle_async 顶层没有 `... = ensure_offloaded(...)` 的无条件下放语句 ⇒ "
        "要么下放又被塞回名单/条件分支（名单重新拿回执行路径决定权），要么收口被删。"
    )
    call = top_assign.value
    assert len(call.args) == 1 and isinstance(call.args[0], ast.Name) and call.args[0].id == "capability", (
        "ensure_offloaded 的参数必须是 capability 本身；若把它用在完成腿上就踩了 A-22。"
    )

    # 完成腿 _complete 不得被 ensure_offloaded 包裹（全函数内 ensure_offloaded 只此一处）。
    wrapped_targets = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ensure_offloaded"
    ]
    assert len(wrapped_targets) == 1, "ensure_offloaded 只准出现在下放收口这一处"

    # 顺序：ensure_offloaded 早于 self._prepare。
    prepare_line = next(
        (
            node.lineno
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_prepare"
        ),
        None,
    )
    assert prepare_line is not None
    assert top_assign.lineno < prepare_line, (
        "下放必须排在 _prepare 之前；否则 redrive_capability 存的是未下放形态。"
    )

    # 名单不再参与 handle_async 的执行路径判定（函数体内不出现该名单名）。
    assert "OFFLOADED_CAPABILITY_IDS" not in {
        n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
    } | _attr_call_names(fn), (
        "handle_async 里重新引用 OFFLOADED_CAPABILITY_IDS ⇒ 名单又拿回了执行路径决定权。"
    )


def test_offload_machine_reaches_a_thread_executor() -> None:
    """下放机不是空转：``ensure_offloaded`` 直呼 ``offload_capability``，后者真落到
    线程执行器。执行器一形 ``loop.run_in_executor``、一形 ``asyncio.to_thread``，
    两形都认（只认直呼形会把它读成「无人调用」）。
    """
    ensure_fn = _func_node(ensure_offloaded, "ensure_offloaded")
    assert "offload_capability" in _bare_call_names(ensure_fn), (
        "ensure_offloaded 不再直呼 offload_capability ⇒ 起了第二份线程池通路或收口塌了。"
    )

    offload_fn = _func_node(offload_capability, "offload_capability")
    attrs = _attr_call_names(offload_fn)
    executor_forms = {"run_in_executor", "to_thread"} & attrs
    assert executor_forms, (
        "offload_capability 没有把正文交给线程执行器（run_in_executor/to_thread 皆无）"
        f"⇒ 下放成了一句空话，同步腿照样冻住循环。实际调用形：{sorted(attrs)}"
    )


# ===========================================================================
# ③ 行为层（运行时现算）
# ===========================================================================


@pytest.mark.asyncio
async def test_sync_command_body_runs_off_the_event_loop() -> None:
    """正向核心：一枚**名单外**的同步命令正文经 handle_async 必须跑在非循环线程上。

    这正是 X4 要消灭「低频同步命令冻住整片会话」的正身——名单外 ``bot.recent`` 一类
    同步正文现在也被下放，``OFFLOADED_CAPABILITY_IDS`` 对管线执行路径不再有决定权。
    """
    obs: dict[str, Any] = {}

    def blocking_sync_body(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        _record_execution(obs)
        return _result()

    pool, _gate, original = _installed_pool(2)
    try:
        pipeline = _make_pipeline()
        loop_ident = await _loop_thread_ident()
        await pipeline.handle_async(_message(), blocking_sync_body, "bot.recent")

        assert obs.get("ran") is True, "正文没被执行（前置门禁把它拦在能力之前？复核用例入参）"
        assert obs["on_loop"] is False, (
            f"同步正文仍钉在事件循环线程＝X4 未落地：{obs}"
        )
        assert obs["thread_ident"] != loop_ident, (
            f"执行线程就是循环线程：{obs}"
        )
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_native_async_body_stays_on_loop_not_double_wrapped() -> None:
    """反向不误伤：协程正文必须留在循环线程上（ensure_offloaded 原样返回，绝不多包一层）。"""
    obs: dict[str, Any] = {}

    async def native_async_body(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        _record_execution(obs)
        return _result()

    # 故意注入一枚会被「误下放」就暴露的池：留在循环上＝池 worker 永不派生。
    pool, _gate, original = _installed_pool(2)
    try:
        pipeline = _make_pipeline()
        loop_ident = await _loop_thread_ident()
        await pipeline.handle_async(_message(), native_async_body, "bot.chat")

        assert obs.get("ran") is True, "协程正文没被执行（门禁拦截？复核入参）"
        assert obs["on_loop"] is True, (
            f"协程正文被多包了一层线程＝把唯一不占循环的形态反而塞进池里：{obs}"
        )
        assert obs["thread_ident"] == loop_ident, f"协程正文跑离了循环线程：{obs}"
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_poisoned_direct_loop_shape_flips_the_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒自证：把执行路径合成改回「直呼循环」⇒ 同一枚观测（正文所在线程）必翻到循环上。

    本腿是 ``test_sync_command_body_runs_off_the_event_loop`` 的反证：证明那条正向断言
    「正文在非循环线程」是**有牙**的——一旦谁把 ``handle_async`` 的下放退回直呼循环
    （删掉/短路 ``ensure_offloaded``，或让根汇口对同步命令改回直呼 ``handle``），
    那条断言就会在此处翻红。合成毒形＝用一个「在循环线程上直接调用同步正文」的
    async 外壳替换真实 ``ensure_offloaded``（等价于 pre-X4 的直呼形态）。
    """

    def _as_direct_loop(capability: Any) -> Any:
        async def _wrapper(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
            return capability(message, decision)  # 直呼：同步正文在调用（=循环）线程上执行

        return _wrapper

    obs: dict[str, Any] = {}

    def blocking_sync_body(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        _record_execution(obs)
        return _result()

    monkeypatch.setattr(pipeline_module, "ensure_offloaded", _as_direct_loop)
    pipeline = _make_pipeline()
    loop_ident = await _loop_thread_ident()
    await pipeline.handle_async(_message(), blocking_sync_body, "bot.recent")

    assert obs.get("ran") is True
    assert obs["on_loop"] is True, (
        "注毒未生效：直呼循环形态里正文却没钉在循环线程上——毒形没构造对，"
        "也就无法证明正向断言有牙。"
    )
    assert obs["thread_ident"] == loop_ident


# ===========================================================================
# ④ 可见面：同步直呼腿（handle）落在循环线程上必须留痕（不哑兜底，非静默放行）
# ===========================================================================


@pytest.mark.asyncio
async def test_handle_on_loop_thread_emits_visible_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``handle`` 在事件循环线程上被调用＝X4 要消灭的形状：必须留一次 WARNING。

    这是「不哑兜底」那条腿——真正的修法在根汇口（把同步命令也走 handle_async），
    在根汇口尚未收编前，至少命中时要能被现算看见。
    """
    snapshot = set(pipeline_module._loop_thread_sync_reported)
    poisoned_id = "bot.x4b_probe_freeze"
    try:
        pipeline_module._loop_thread_sync_reported.discard(poisoned_id)

        def body(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
            return _result()

        with caplog.at_level(logging.WARNING, logger=pipeline_module.logger.name):
            await _loop_thread_ident()  # 确认此刻确在循环线程（handle 同步直呼即钉住它）
            pipeline = _make_pipeline()
            pipeline.handle(_message(), body, capability_id=poisoned_id)

        assert poisoned_id in pipeline_module._loop_thread_sync_reported, (
            "循环线程上直呼 handle 却没记账 ⇒ _report_loop_thread_sync_call 的可见面失效。"
        )
        assert any(
            poisoned_id in rec.getMessage() and rec.levelno == logging.WARNING
            for rec in caplog.records
        ), "同步直呼冻住循环却没有 WARNING（静默放行＝事故查不到）。"
    finally:
        pipeline_module._loop_thread_sync_reported.clear()
        pipeline_module._loop_thread_sync_reported.update(snapshot)


def test_report_skipped_when_no_running_loop() -> None:
    """非循环线程（console/smoke/脚本/离线测试）直呼 handle＝既有同步用法现状，零噪声。"""
    snapshot = set(pipeline_module._loop_thread_sync_reported)
    probe_id = "bot.x4b_probe_offthread"
    try:
        pipeline_module._loop_thread_sync_reported.discard(probe_id)
        # 本用例是同步函数：此刻没有运行中的事件循环 ⇒ 记账必须保持干净。
        pipeline_module._report_loop_thread_sync_call(probe_id)
        assert probe_id not in pipeline_module._loop_thread_sync_reported, (
            "无运行循环时仍记账＝把既有同步用法误报成事故，制造噪声。"
        )
    finally:
        pipeline_module._loop_thread_sync_reported.clear()
        pipeline_module._loop_thread_sync_reported.update(snapshot)
