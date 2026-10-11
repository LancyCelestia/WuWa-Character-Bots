"""超时改造 C1（2026-09-28）：管线能力单次执行硬超时 ⇒ 挂死必须出卡。

钉住的缺陷链（前席取证，逐处 file:line 见 AGENTS 第四部分「统一错误报告卡」行与
台账 #49★「未执法」条）：

- `offload_capability`（真身 `domains/chat_reply/runtime/pipeline.py`）改动前
  **没有任何逐任务时限**（在册 M-4，位置＝
  `docs/design/audit-20260920-unify-U4-dispatch.md:168`）；
- 全管线唯一的 `wait_for` 在 `_await_with_progress_ack`，它套着 `asyncio.shield`
  ⇒ 连"先回执"那条路都不会杀真实任务，且该键缺省关；
- 中央 invoker 有逐次预算并把 `concurrent.futures.TimeoutError` 包成
  `CapabilityTimeout`（`runtime/capability_protocols.py:753-776`），但 **bot.chat 的根
  不经过它**（根 `__init__.py` 直呼 `pipeline.handle_async`）。

三者合起来的现网形态＝能力挂死 ⇒ 这一轮永远 awaits ⇒ 用户白等、卡也不出。

本文件的判据（全离线，零端口零网络零 QQ）：

1. 到点抛的必须是 `CapabilityTimeout`（复用中央那一枚，禁第二族）；
2. 异常必须走到 `_internal_error` ⇒ `_maybe_send_error_card` 被触达（哨兵，不真渲染）；
3. 闸位（`_BoundedSubmissionGate` 许可）**不得在 worker 还占着时提前归还**——
   提前还会把有界池写成无界队列，挂死风暴时排队无上限，比"这一轮白等"更坏；
4. 正常返回路径零行为变化（快能力照旧立即归还闸位）；
5. 缺省值与解析链（driver config → env → Config 声明默认）+「必须严格高于请求预算」
   的抬底判据各有锁；缺省关不到 0（0 会把每条聊天都判成挂死）。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState, SendPolicy
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.user_copy import (
    PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    pipeline as pipeline_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline import (
    _BoundedSubmissionGate,
    _pipeline_busy_result,
    _resolve_capability_hard_timeout_seconds,
    capability_hard_timeout_seconds,
    offload_capability,
    set_capability_hard_timeout_seconds,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.monitor import (
    error_report as error_report_module,
)
from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_HANG_EVENT_TIMEOUT = 20.0  # 看护上限：只防测试挂死，不参与任何断言（真判据是 0.05s 硬超时）


class _NullAuditLogger:
    def append(self, record: object) -> None:
        return


def _message(session_id: str = "private:c1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u-c1",
        plain_text="潮汐很安静",
        message_id="m-c1",
    )


def _decision(capability_id: str = "bot.chat") -> BotDecision:
    return BotDecision(
        request_id="req-c1",
        should_respond=True,
        mode="command",
        trigger="潮汐很安静",
        capability_id=capability_id,
        target_scope=SessionType.PRIVATE,
        decision_reason="c1",
    )


def _installed_pool(
    max_workers: int,
) -> tuple[ThreadPoolExecutor, _BoundedSubmissionGate, tuple[Any, Any]]:
    """向 pipeline 模块注入独立测试池，返回（池, 闸, 原状）供 finally 还原。"""
    pool = ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="c1-test-pool"
    )
    gate = _BoundedSubmissionGate(max_workers * 2)
    original = (pipeline_module._chat_pool, pipeline_module._chat_pool_gate)
    pipeline_module._chat_pool = pool
    pipeline_module._chat_pool_gate = gate
    return pool, gate, original


@pytest.fixture()
def card_tripwire(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, BaseException]]:
    """error_report 卡钩子的哨兵：记录每次触达，绝不真渲染/真投递。"""
    calls: list[tuple[str, BaseException]] = []

    def _spy(
        _pipeline: Any, _message_arg: Any, capability_id: str, exc: BaseException, **_kw: Any
    ) -> None:
        calls.append((capability_id, exc))

    monkeypatch.setattr(error_report_module, "maybe_submit_error_card", _spy)
    return calls


@pytest.fixture(autouse=True)
def _restore_globals() -> Any:
    """硬超时覆盖与解析缓存逐用例归零（防跨用例污染出"看起来时好时坏"的假象）。"""
    set_capability_hard_timeout_seconds(None)
    yield
    set_capability_hard_timeout_seconds(None)


async def _drain_loop(times: int = 6) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# ① 挂死 ⇒ 抛 CapabilityTimeout ⇒ 出卡（用户可见面的正面对撞用例）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hung_capability_raises_capability_timeout_and_fires_error_card(
    card_tripwire: list[tuple[str, BaseException]],
) -> None:
    """改动前这一发必然白等：capability 永不返回 ⇒ 无任何终态。

    现在：0.05s 到点 ⇒ `CapabilityTimeout` ⇒ `handle_async` 的 except ⇒
    `_internal_error` ⇒ `_maybe_send_error_card`（哨兵记到一次）。
    """
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        release.wait(_HANG_EVENT_TIMEOUT)
        return None  # 永远等不到这里（测试里由 finally 放行，只为让线程干净退出）

    pool, _gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    pipeline = pipeline_module.RuntimePipeline(
        send_queue=InMemorySendQueue(audit_logger=_NullAuditLogger()),
        audit_logger=_NullAuditLogger(),
    )
    try:
        wrapped = offload_capability(hanging_capability)
        receipt = await pipeline.handle_async(_message(), wrapped, "bot.chat")

        assert receipt.state is ReceiptState.FAILED_FINAL, receipt.state
        assert receipt.operational_issue is not None
        # `_internal_error` 的 safe_summary＝`<capability_id>:<异常类名>`：这一行
        # 就是"挂死"与"抛异常"共用同一张卡的证据（异常身份必须上告警链）。
        assert receipt.operational_issue.safe_summary == "bot.chat:CapabilityTimeout"
        assert len(card_tripwire) == 1, "挂死仍不出卡＝M-4 未关账"
        capability_id, exc = card_tripwire[0]
        assert capability_id == "bot.chat"
        assert isinstance(exc, cp.CapabilityTimeout), type(exc)
        assert "硬超时" in str(exc)
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_offload_timeout_propagates_capability_timeout_directly() -> None:
    """裸 offload 出口也必须抛（不靠管线兜住）：判据＝异常类型 + __cause__ 是真 TimeoutError。"""
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        release.wait(_HANG_EVENT_TIMEOUT)
        return "late"

    pool, _gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    try:
        with pytest.raises(cp.CapabilityTimeout) as raised:
            await offload_capability(hanging_capability)(_message(), _decision())
        assert isinstance(raised.value.__cause__, TimeoutError)
        assert "bot.chat" in str(raised.value)
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# ② 闸位账：超时不许把有界池写成无界队列
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_permit_held_while_hung_worker_still_running() -> None:
    """超时只解调用方的白等，**不**谎报 worker 已空出。

    提前还许可 ⇒ 挂死任务仍在跑却腾出了额度 ⇒ 提交不再被有界闸挡住 ⇒ 排队无上限。
    这一发钉住"延后归还"：线程真退出前 `in_flight` 保持占用，退出后才归零。
    """
    started = threading.Event()
    release = threading.Event()

    def hanging_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        started.set()
        release.wait(_HANG_EVENT_TIMEOUT)
        return "done"

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(0.05)
    try:
        wrapper = offload_capability(hanging_capability)
        with pytest.raises(cp.CapabilityTimeout):
            await wrapper(_message(), _decision())
        # 线程仍在 wait（started 已置位、release 未置位）⇒ 闸位必须还占着。
        assert started.wait(2) is True
        assert gate.in_flight == 1, (
            f"超时即还闸位＝把有界池改成无界队列（挂死风暴会无限排队）：{gate.in_flight}"
        )
        release.set()
        # 线程退出后由 done 回调归还；回调经 loop.call_soon 派发，要泵几下。
        for _ in range(200):
            await _drain_loop(2)
            await asyncio.sleep(0.01)
            if gate.in_flight == 0:
                break
        assert gate.in_flight == 0, "延后归还没落地＝闸位永久泄漏（池被钉死成 busy）"
    finally:
        release.set()
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_fast_capability_path_unchanged_by_hard_timeout() -> None:
    """预算内的正常回复零行为变化：结果原样返回、闸位当场归还（不许"顺手多等一会"）。"""

    def fast_capability(message: IncomingMessage, decision: BotDecision) -> str:
        return "ok"

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(30.0)
    try:
        value = await offload_capability(fast_capability)(_message(), _decision())
        assert value == "ok"
        assert gate.in_flight == 0
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_capability_exception_still_releases_gate() -> None:
    """能力抛异常（非超时）同口径：闸位归零、异常原样向外走（旧语义不许被 shield 吞掉）。"""

    def failing_capability(message: IncomingMessage, decision: BotDecision) -> Any:
        raise RuntimeError("boom")

    pool, gate, original = _installed_pool(1)
    set_capability_hard_timeout_seconds(30.0)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await offload_capability(failing_capability)(_message(), _decision())
        await _drain_loop(4)
        assert gate.in_flight == 0
    finally:
        pipeline_module._chat_pool, pipeline_module._chat_pool_gate = original
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# ③ 数字面：缺省、解析链、以及"必须严格高于请求预算"的抬底
# ---------------------------------------------------------------------------


def test_config_defaults_keep_hard_timeout_above_request_budget() -> None:
    config = Config()
    assert config.bot_pipeline_capability_hard_timeout_seconds == 400.0
    # 外部闸不得抢在内部 deadline 前砍回复：硬超时必须严格大于请求预算。
    assert (
        config.bot_pipeline_capability_hard_timeout_seconds
        > config.bot_request_budget_seconds
    )


def test_resolver_chain_env_then_config_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """单元测试环境 nonebot 未初始化 ⇒ 解析链自动落到 os.environ → Config 声明默认。"""
    monkeypatch.delenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("BOT_REQUEST_BUDGET_SECONDS", raising=False)
    assert _resolve_capability_hard_timeout_seconds() == 400.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "1000")
    assert _resolve_capability_hard_timeout_seconds() == 1000.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "abc")
    assert _resolve_capability_hard_timeout_seconds() == 400.0

    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "0")
    # 0/负数不参与取值（0 会把每一条聊天立刻判成挂死），退回声明默认。
    assert _resolve_capability_hard_timeout_seconds() == 400.0


def test_resolver_raises_floor_above_request_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """.env 把硬超时调到请求预算之下 ⇒ 抬到「预算 + 余量」，不静默抢跑、也不拒绝启动。"""
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "100")
    monkeypatch.setenv("BOT_REQUEST_BUDGET_SECONDS", "300")
    assert _resolve_capability_hard_timeout_seconds() == 360.0


def test_resolver_clamps_absurd_values_but_still_above_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "999999")
    monkeypatch.setenv("BOT_REQUEST_BUDGET_SECONDS", "300")
    assert _resolve_capability_hard_timeout_seconds() == 3600.0


def test_capability_hard_timeout_seconds_uses_override_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """override 在场 ⇒ 每次现算且不写缓存；清除后回到解析链（生产读法不变）。"""
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "500")
    set_capability_hard_timeout_seconds(0.25)
    assert capability_hard_timeout_seconds() == 0.25
    set_capability_hard_timeout_seconds(None)
    first = capability_hard_timeout_seconds()
    assert first == 500.0
    # 缓存生效：改 env 不再影响本进程（改 .env 需重启，已登 RESTART_REQUIRED_KEYS）。
    monkeypatch.setenv("BOT_PIPELINE_CAPABILITY_HARD_TIMEOUT_SECONDS", "700")
    assert capability_hard_timeout_seconds() == first


def test_busy_private_send_policy_is_not_silent() -> None:
    """C1-d 的载体判据（与 test_pipeline_review_fixes 同锁互证）：私聊超载快败
    必须走 IMMEDIATE 出站，群/频道仍 SILENT_AUDIT。"""
    private = _pipeline_busy_result(_message(), _decision())
    assert private.send_policy is SendPolicy.IMMEDIATE
    assert private.body in PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES
    assert private.operational_issue is not None
    assert private.operational_issue.kind == "pipeline_busy"

    group_message = _message("group:c1").model_copy(
        update={"session_type": SessionType.GROUP, "group_id": "g1"}
    )
    group = _pipeline_busy_result(
        group_message,
        _decision().model_copy(
            update={"capability_id": "bot.chat", "target_scope": SessionType.GROUP}
        ),
    )
    assert group.send_policy is SendPolicy.SILENT_AUDIT
    assert group.body == ""


# ---------------------------------------------------------------------------
# Q-1 循环导入根治（两腿锁）：`runtime/pipeline.py` 的 policy 符号一律从**具体子模块**
# 直取，不许经 `...chat_reply.policy` 包出口转手。
# 为什么要锁：包 `__init__.py` 第一条语句是 `from .gate import …`，gate 又 import
# `runtime.mentions` ⇒ 触发 `runtime/__init__.py` 的 `from .pipeline import …` ⇒ 回到
# 还没绑任何名的 pipeline/policy。生产单树那套装载序恰好把它绕开了（所以 bot 一直
# 正常），装载序一变（分库共装、新入口）就当场 `ImportError: cannot import name
# 'InMemoryRateLimiter'`——「bot 不回消息」级。
# 两向实跑判据（同毒跑未修版，席报留痕）：把该包换成「module_from_spec、不
# exec_module」的空壳并清掉 `policy.*` 子模块后 reload(pipeline)——改前抛、改后不抛。
# ---------------------------------------------------------------------------

_POLICY_PKG = "plugins.bot_unified_runtime.domains.chat_reply.policy"

# 逐枚住址按 AST 现算过（不是照 `policy/__init__.py` 的转手表抄）：
# gate.py 里有 PolicySettings/evaluate_policy，rate_limit.py 里有那三枚限流符号与
# redrive_wait_seconds，quiet_hours/reply_budget/roles 各自一枚。
_POLICY_SYMBOL_HOME = {
    "InMemoryRateLimiter": "rate_limit",
    "PolicySettings": "gate",
    "QuietHoursChecker": "quiet_hours",
    "RateLimiter": "rate_limit",
    "RedriveSettings": "rate_limit",
    "ReplyBudgetSettings": "reply_budget",
    "RoleSettings": "roles",
    "decide_reply_budget": "reply_budget",
    "evaluate_policy": "gate",
    "redrive_wait_seconds": "rate_limit",
}


def _pipeline_import_from_policy_nodes() -> list[ast.ImportFrom]:
    source = Path(
        inspect.getsourcefile(pipeline_module)
        or Path(pipeline_module.__file__).with_suffix(".py")
    ).read_text(encoding="utf-8")
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith(_POLICY_PKG)
    ]


def test_pipeline_never_takes_policy_names_through_the_package() -> None:
    """形状尺①：不许出现「从包出口 import 名字」那一型（循环的唯一入口）。"""
    via_package = [
        (node.lineno, alias.name)
        for node in _pipeline_import_from_policy_nodes()
        for alias in node.names
        if node.module == _POLICY_PKG
    ]
    assert via_package == [], f"pipeline 仍在经包出口取符号：{via_package}"


def test_pipeline_policy_symbol_sources_are_the_exact_submodules() -> None:
    """形状尺②：十枚符号各从**真身子模块**直取（住址错了＝第二份构造的前兆）。"""
    got: dict[str, str] = {}
    for node in _pipeline_import_from_policy_nodes():
        if node.module == _POLICY_PKG:
            continue
        submodule = node.module.rsplit(".", 1)[-1]
        for alias in node.names:
            got[alias.name] = submodule
    misplaced = {
        name: (got.get(name), home)
        for name, home in _POLICY_SYMBOL_HOME.items()
        if got.get(name) != home
    }
    assert misplaced == {}, f"符号住址与真身不符（取到＝缺 / 期望＝子模块）：{misplaced}"


def test_policy_symbols_are_the_very_objects_the_package_exports() -> None:
    """行为零变更：直取到的、包出口转手的、pipeline 手里的是**同一枚对象**。

    `id` 全等 ⇒ 修法没造出第二份构造（各取一次会各有其状态，闸门/限流会分家）。
    顺带断言十枚互不相同，防「名字接错到同一枚」被 `is` 蒙过去。
    """
    import importlib

    pkg = importlib.import_module(_POLICY_PKG)
    ids: dict[str, int] = {}
    for name, submodule in _POLICY_SYMBOL_HOME.items():
        direct = getattr(importlib.import_module(f"{_POLICY_PKG}.{submodule}"), name)
        assert direct is getattr(pkg, name), f"{name}：子模块与包出口不是同一枚对象"
        assert direct is getattr(pipeline_module, name), f"{name}：pipeline 手里换了对象"
        ids[name] = id(direct)
    assert len(set(ids.values())) == len(ids), "两枚符号指向同一对象＝接线接串了"


# ==================== 包出口「抢名形」全树普查尺（同一族残余的执法腿） ====================
# ca9c62d 只把 pipeline 的**十枚 policy 符号**改成直取，上面那三把尺也只罩 policy 一家。
# 同一坏形状在活图里另有若干处（`transport.sender`／`output`／`core.contracts`／`security`／
# `ops.audit`／`character`／`llm_engine`／`chat_reply.runtime`），裁定①「组合可导入」的装载序
# 下照样撞环。本段把判据从「一枚包＋一个文件」扩成「活图＋全体抢名表」，并把本波治好的
# 坐标钉成零容忍。
#
# 判据与 `_pipeline_import_from_policy_nodes` 同口径，只去掉包名限定：
#   `from <PKG> import <NAME>`，<PKG> 带 `__init__.py`，且 <NAME> 既不在 <PKG>/__init__.py
#   顶层定义、也不是 <PKG> 的子模块 ⇒ 这枚名字是**转手来的**，取它必须先把整张表跑完
#   ＝一条 eager 导入边。
#
# 🔴 为什么「只改消费者 import」不够（本波现算实锤）：导入子模块**必先到父包**，所以
# `from …policy.gate import PolicySettings` 冷启照样炸（单跑 `import …policy.gate` 现算
# ImportError）。环的活边在**表自身**——`chat_reply/runtime/__init__.py` 旧第 6 行
# `from .pipeline import …` 才是 policy ⇄ runtime 那一环的唯一 eager 边。故第 3 把尺罩的是
# 表的形状（惰性＝合格），不只是消费者；同族的 `plugins/bot_unified_runtime/runtime/__init__.py`
# 早已因此改惰性并留注「别改回抢名形」，本尺防的就是这里被改回去。

_LIVE_SCAN_ROOTS = ("plugins", "scripts")
_REPO_ROOT = Path(__file__).resolve().parents[1]

# 棘轮地板＝本波入库时的现算读数（92 枚／22 个文件；净减 67 枚）。规则 10：会随代码漂的数
# 只准由尺现算，所以这里存的是**上限**不是统计——新增一枚抢名取用即红，清掉只会更松。
# 要下调请按 #68 现算复录，别顺手改小。
_PASS_THROUGH_CEILING = 92

# 本波治好的坐标：抢名取用必须恒为 0（防回潮）。
_CURED_MODULES = frozenset(
    {
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/__init__.py",
        "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py",
        "plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py",
        "plugins/bot_unified_runtime/domains/ops/smoke/diagnostics.py",
        "plugins/bot_unified_runtime/domains/ops/smoke/smoke.py",
        "plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py",
        "plugins/bot_unified_runtime/domains/ops/admin/debug.py",
        "scripts/e2e_acceptance.py",
    }
)

# pipeline 里 sender/output 两族的真身住址（逐枚按 AST 现算，非照抄转手表）。
_PIPELINE_SENDER_OUTPUT_HOME = {
    "InMemoryReceiptRepository": (
        "plugins.bot_unified_runtime.domains.transport.sender.receipts",
        "plugins.bot_unified_runtime.domains.transport.sender",
    ),
    "ReceiptRepository": (
        "plugins.bot_unified_runtime.domains.transport.sender.receipts",
        "plugins.bot_unified_runtime.domains.transport.sender",
    ),
    "SendQueue": (
        "plugins.bot_unified_runtime.domains.transport.sender.queue",
        "plugins.bot_unified_runtime.domains.transport.sender",
    ),
    "build_forward_output": (
        "plugins.bot_unified_runtime.domains.render.renderer",
        "plugins.bot_unified_runtime.output",
    ),
    "render_reviewed_output": (
        "plugins.bot_unified_runtime.domains.render.renderer",
        "plugins.bot_unified_runtime.output",
    ),
    "should_forward_by_node_count": (
        "plugins.bot_unified_runtime.domains.render.renderer",
        "plugins.bot_unified_runtime.output",
    ),
    "should_forward_long_text": (
        "plugins.bot_unified_runtime.domains.render.renderer",
        "plugins.bot_unified_runtime.output",
    ),
    "review_capability_result": (
        "plugins.bot_unified_runtime.domains.render.reviewer",
        "plugins.bot_unified_runtime.output",
    ),
}

_LAZY_RUNTIME_NAMES = ("RuntimeControlState", "RuntimePipeline", "offload_capability")


def _live_tree_sources() -> list[Path]:
    out: list[Path] = []
    for root in _LIVE_SCAN_ROOTS:
        base = _REPO_ROOT / root
        if not base.is_dir():
            continue
        out.extend(
            p
            for p in sorted(base.rglob("*.py"))
            if p.is_file() and "__pycache__" not in p.parts
        )
    return out


def _dotted(path: Path) -> str | None:
    parts = list(path.relative_to(_REPO_ROOT).parts)
    if parts[-1] == "__init__.py":
        parts.pop()
        if not parts:
            return None
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts)


def _resolve_import_source(
    module: str | None, current: str, is_pkg: bool, level: int
) -> str | None:
    """绝对 dotted 名。level 1 == 当前模块所属的那个包（包 __init__ 即其自身）。"""
    if level == 0:
        return module
    container = current if is_pkg else current.rsplit(".", 1)[0]
    parts = container.split(".") if container else []
    drop = level - 1
    if drop > len(parts):
        return None
    if drop:
        parts = parts[: len(parts) - drop]
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base or None


def _package_tables(
    parsed: dict[str, ast.Module],
) -> dict[str, tuple[set[str], set[str]]]:
    """pkg -> (在 __init__ 顶层定义的名字, 被**模块级** import 抢进来的名字)。"""
    tables: dict[str, tuple[set[str], set[str]]] = {}
    for name, tree in parsed.items():
        own: set[str] = set()
        bound: set[str] = set()
        for st in tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                own.add(st.name)
            elif isinstance(st, ast.Assign):
                own.update(t.id for t in st.targets if isinstance(t, ast.Name))
            elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                own.add(st.target.id)
            elif isinstance(st, ast.ImportFrom):
                if st.module == "__future__":
                    continue
                # 🔴 只认模块级语句：藏在 `__getattr__` 里的取名不是 eager 边（惰性 remedy 的
                # 本体）。认了就等于把「改成惰性」判成「还在抢名」，尺会把正确修法当红。
                bound.update(a.asname or a.name for a in st.names if a.name != "*")
            elif isinstance(st, ast.Import):
                bound.update(a.asname or a.name.split(".")[0] for a in st.names)
        tables[name] = (own, bound)
    return tables


def _pass_through_takes() -> list[tuple[str, int, str, str]]:
    """活图里每一处「从包出口取转手符号」＝(相对文件, 行号, 包, 名字)。"""
    modules: dict[str, Path] = {}
    for p in _live_tree_sources():
        dn = _dotted(p)
        if dn:
            modules[dn] = p
    parsed: dict[str, ast.Module] = {}
    for dn, p in modules.items():
        try:
            parsed[dn] = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):  # pragma: no cover
            continue
    inits = {dn for dn, p in modules.items() if p.name == "__init__.py"}
    tables = _package_tables({dn: parsed[dn] for dn in inits if dn in parsed})

    hits: list[tuple[str, int, str, str]] = []
    for dn, path in sorted(modules.items()):
        tree = parsed.get(dn)
        if tree is None:
            continue
        is_pkg = path.name == "__init__.py"
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.names:
                continue
            src = _resolve_import_source(node.module, dn, is_pkg, node.level)
            if src is None or src not in tables:
                continue
            own, bound = tables[src]
            for a in node.names:
                if a.name == "*" or a.name in own:
                    continue  # 表自己定义的名字：不是转手
                if f"{src}.{a.name}" in modules:
                    continue  # 取子模块本身：合法
                if a.name in bound:
                    hits.append(
                        (
                            str(path.relative_to(_REPO_ROOT)).replace("\\", "/"),
                            node.lineno,
                            src,
                            a.name,
                        )
                    )
    return hits


def test_live_tree_pass_through_takes_within_ratchet_ceiling() -> None:
    """棘轮：包出口抢名取用总数不得高于入库读数（本波 159→92，净减 67 枚）。"""
    hits = _pass_through_takes()
    assert len(hits) <= _PASS_THROUGH_CEILING, (
        f"新增「从包出口取符号」命中 {len(hits)} 枚 > 上限 {_PASS_THROUGH_CEILING}。"
        "抢名表＝一条 eager 导入边，裁定①组合序下会撞成部分初始化 ⇒ cannot import name。"
        f"样例：{sorted(hits)[:6]}"
    )


def test_cured_modules_take_no_symbols_through_a_package() -> None:
    """零容忍：本波治好的坐标一枚抢名取用都不许回来。"""
    relapsed = [h for h in _pass_through_takes() if h[0] in _CURED_MODULES]
    assert relapsed == [], f"这些坐标又开始经包出口取符号了：{relapsed}"


def test_pipeline_takes_sender_output_symbols_from_defining_modules() -> None:
    """形状尺（sender/output 两族）：住址必须是真身子模块，且不走任何包出口。"""
    source = Path(
        inspect.getsourcefile(pipeline_module)
        or Path(pipeline_module.__file__).with_suffix(".py")
    ).read_text(encoding="utf-8")
    bound_from: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for a in node.names:
            if a.name in _PIPELINE_SENDER_OUTPUT_HOME:
                bound_from[a.name] = node.module
    wrong = {
        n: (bound_from.get(n), home)
        for n, (home, _pkg) in _PIPELINE_SENDER_OUTPUT_HOME.items()
        if bound_from.get(n) != home
    }
    assert wrong == {}, f"sender/output 符号住址与真身不符（None＝还没取）：{wrong}"


def test_pipeline_sender_output_symbols_are_the_very_objects_the_package_exports() -> None:
    """行为零变更：直取到的、包出口转手的、pipeline 手里的是同一枚对象。"""
    import importlib

    ids: dict[str, int] = {}
    for name, (home, pkg_name) in _PIPELINE_SENDER_OUTPUT_HOME.items():
        direct = getattr(importlib.import_module(home), name)
        assert direct is getattr(importlib.import_module(pkg_name), name), (
            f"{name}：子模块与包出口不是同一枚对象（改出了第二份构造？）"
        )
        assert direct is getattr(pipeline_module, name), f"{name}：pipeline 手里换了对象"
        ids[name] = id(direct)
    assert len(set(ids.values())) == len(ids), "两枚符号指向同一对象＝接线接串了"


def test_chat_reply_runtime_package_stays_lazy() -> None:
    """锁住断开 policy ⇄ runtime 环的那条边：本包出口必须保持惰性。

    旧第 6 行 `from .pipeline import RuntimeControlState, …` 是那一环的唯一 eager 边：
    任一入口 → `chat_reply.policy`（表首句 `from .gate import PolicySettings`）→ gate 第 16 行
    经 `runtime.mentions` 进本包 → 抢名 ⇒ 此刻 gate 只跑到第 16 行、`PolicySettings` 定义在
    第 47 行尚未绑定 ⇒ ImportError（本波现算复现并实测：改成惰性后 5 座判 HAS-INIT 的库转 OK）。
    公开面不许变：三枚名字照旧可取、且必须仍是 pipeline 里那同一批对象。
    """
    import importlib

    init = (
        _REPO_ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/runtime/__init__.py"
    )
    tree = ast.parse(init.read_text(encoding="utf-8"))
    eager = [
        a.asname or a.name
        for st in tree.body  # 只看模块级：__getattr__ 内的取名不算抢名
        if isinstance(st, (ast.Import, ast.ImportFrom))
        for a in st.names
        if (a.asname or a.name.split(".")[0]) in _LAZY_RUNTIME_NAMES
    ]
    assert eager == [], f"chat_reply/runtime 又开始模块级抢 pipeline 的名字了：{eager}"

    rt = importlib.import_module(
        "plugins.bot_unified_runtime.domains.chat_reply.runtime"
    )
    pl = importlib.import_module(
        "plugins.bot_unified_runtime.domains.chat_reply.runtime.pipeline"
    )
    for name in _LAZY_RUNTIME_NAMES:
        assert getattr(rt, name) is getattr(pl, name), f"{name}：公开面换了对象"
        assert name in dir(rt), f"{name}：dir() 不再列出这枚在册名字"
    assert set(rt.__all__) == set(_LAZY_RUNTIME_NAMES)
    assert bool(rt.__path__), "split-package 的 __path__ 被吃掉＝组合共装当场失效"
