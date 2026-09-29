r"""主动投递「就地送 ⇔ submit 同在事件循环」设计前提的执法件（席位 S264 新建）。

## 本件锁的是什么

`PROPOSAL-inline-delivery.md` §2 更正③ 论证出的设计前提：

> **要就地送就必须连 `submit` 一起搬进事件循环。**

两条实测/读码依据（本件不复述其推导，只执法其结论）：

1. 队列的内联认领台账 `_register_inline_claim`（真身
   `domains/transport/sender/queue.py:381-392`）**只在有运行中事件循环时才登记**——
   线程里 submit 拿不到硬互斥，只剩 `max(60s, 3×传输超时)` 的时间宽限。
2. 反过来做成「线程里 submit ＋ 回主循环就地送」的半吊子，会**同时**拿到两条最坏
   性质：台账没登记（在线程里 submit）＋ 内联耗时可超宽限期（`#50` 实测事件循环
   停顿 140–395s）。

⇒ 判据不是「谁长得像 async」，而是**一条调用链不得跨线程边界携带 submit 或就地送**。

## 三条腿 + 两把行为锁（缺一即本件不完整）

- 腿①（结构）`test_inline_delivery_frames_are_all_coroutine_functions`
- 腿②（结构）`test_submit_is_never_carried_across_a_thread_boundary`
- 腿③（结构）`test_scheduler_jobs_that_deliver_inline_are_registered_as_coroutines`
- 腿④（名册）`test_active_push_inline_delivery_ledger_matches_derivation`
  ——六族名册的 `inline_delivered` 声明必须与 AST 派生值**双向相等**：写谎（声明 True
  而实不真）与回潮（偷偷加了就地送却不改名册）都当场红。§3 补丁落地时**必须与名册同批
  翻转**，这就是"一处变更处处跟随"。
- 腿⑤（行为）`test_inline_claim_ledger_only_exists_inside_an_event_loop`
  ——真造 `SQLiteSendRequestQueue`，分别在「无线程循环」与「协程内」提交，实测认领台账
  登记与 `claim_due` 否决的差别（含"提交任务终结后清簿放行"这一半，免得被读成永久阻塞）。
- 腿⑥（现状）`test_worker_path_is_the_only_delivery_route_for_the_three_families`
  + `test_queue_sent_receipt_is_not_proof_of_delivery`
  ——群摘要／日常助理／紧急三族今天**只入队**，且缺省配置下没有任何人投递；
  `InMemorySendQueue.submit` 回的 SENT 是**假回执**，不可当送达证据。

## 本件的自我防护（为什么不是又一把空跑锁）

- **同一份判据既扫真文件也扫注毒源**：所有规则都是 `_index(sources)` 上的纯函数，
  真文件与合成注毒走同一条代码路径（禁第二真身）。注毒台先自试：每把毒都必须当场
  咬出违规，且**同一把毒打在还原态上必须不咬**——否则该用例本身作废。
- **帧归属自证**（`test_nested_frame_calls_are_not_attributed_to_the_enclosing_frame`）：
  本席写第一版探针时把「嵌套 `async def` 体内的调用」算进了外层同步函数，直接造出
  14 处幻影违规（`_register_nonebot_handlers` 被记成就地送者）。该缺陷已由这条锁钉住：
  外层同步帧不得认领内层协程的调用，反之真在外层帧的调用不得漏记。
- **绝不在测试内 import 生产根** `plugins/bot_unified_runtime/__init__.py`：该模块
  导入即执行 `_register_nonebot_handlers()`（注册 matcher/调度器），本件只按文本 AST 解析它。

## 现算读数（本席 2026-09-25T19:5xZ 真跑，非转述；漂移即由地板/名册翻红）

- 直接 await `_deliver_transport_send_request` 的帧：14 帧，全部 `async def`。
- 直接调用中央出口 `submit_active_push` 的帧：5 帧（root 4 + `emg_push` 1）。
- 三族 job：`_digest_push_job` / `_meal_job` / `_morning_job` / `_evening_job` /
  `_emergency_info_collect_job` 全部为**同步** def ⇒ APScheduler
  （`nonebot_plugin_apscheduler` 的 AsyncIOScheduler）把它们丢进线程池；
  已过杠三族的 job（`_reminder_job` / `_cookie_expiry_reminder_job`）是 `async def`。
  ⇒ 现算出处见
  `.superpowers/sdd/2026-09-24-central-dispatch/probes/s264-ledger-probe.py`。
"""

from __future__ import annotations

import ast
import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.transport.sender.queue import (
    InMemorySendQueue,
    SQLiteSendRequestQueue,
)

# --------------------------------------------------------------------------- 尺与常量

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 本件的扫描面。**只读文本**，绝不 import（生产根导入即注册 matcher）。
SCANNED_FILES: dict[str, Path] = {
    "root": PLUGIN_ROOT / "__init__.py",
    "emg_push": PLUGIN_ROOT / "domains" / "emergency_info" / "service" / "push.py",
}

#: 就地投递的唯一真身符号（root `__init__.py:2476` 定义）。
INLINE_DELIVERY_SYMBOL = "_deliver_transport_send_request"
#: 主动投递的唯一出口符号（`domains/transport/sender/outbound_gate.py`）。
CENTRAL_EXIT_SYMBOL = "submit_active_push"

#: 跨线程执行包装（被这些包住的实参如果携带 submit/就地送，即 §2 更正③ 的半吊子形状）。
_THREAD_OFFLOAD_SYMBOLS = frozenset(
    {
        "asyncio.to_thread",
        "to_thread",
        "loop.run_in_executor",
        "run_in_executor",
        "asyncio.run_coroutine_threadsafe",
    }
)
#: 在别的线程里另起事件循环（比 offload 更糟：submit 与投递彻底分家且无认领台账）。
_NEW_LOOP_SYMBOLS = frozenset({"asyncio.run", "asyncio.new_event_loop"})

#: 地板（现算 14，2026-09-25）：只防「扫描器瞎了」，不当「精确等值」用。
_MIN_INLINE_DELIVERY_FRAMES = 5
_MIN_CENTRAL_EXIT_FRAMES = 4


# --------------------------------------------------------------------------- AST 索引


def _dotted(node: ast.AST) -> str:
    """`a.b.c` 形态的调用名；非 Name/Attribute 返回空串。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _leaf(name: str) -> str:
    return name.rpartition(".")[2]


@dataclass(frozen=True)
class _Frame:
    """一个函数帧（含嵌套 def）：本帧自有调用、别名绑定、跨线程实参与异步性。"""

    key: str
    name: str
    qualname: str
    lineno: int
    is_async: bool
    calls: frozenset[str] = field(default_factory=frozenset)
    offloaded: frozenset[str] = field(default_factory=frozenset)
    loop_hops: frozenset[str] = field(default_factory=frozenset)
    #: 形如 `deliver = deliver_fn or _deliver_transport_send_request` 的别名目标名。
    #: 生产里确有这一手（`__init__.py:3098` cookie 到期族），不认别名就等于尺瞎。
    delivery_aliases: frozenset[str] = field(default_factory=frozenset)

    @property
    def id(self) -> str:  # 语义即「文件键 + 限定名」身份（不是 builtin shadow，A003 未启用）
        return f"{self.key}:{self.qualname}"


def _own_nodes(fn: ast.AST) -> list[ast.AST]:
    """本帧自有节点：嵌套 def/lambda/class 的**整棵子树**都不算（帧归属自证的目标）。

    第一版写成「跳过是函数类型的 child」，但 `walk(node)` 先 append 再下钻，
    于是 `fn.body` 里直接放的嵌套 `async def` 仍被展开 ⇒ 14 处幻影违规。
    现在把类型判定放在**递归入口**，并单独立锁钉住（见
    `test_nested_frame_calls_are_not_attributed_to_the_enclosing_frame`）。
    """

    out: list[ast.AST] = []

    def walk(node: ast.AST) -> None:
        out.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
            ):
                continue
            walk(child)

    for stmt in getattr(fn, "body", []):
        if isinstance(
            stmt,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        walk(stmt)
    for deco in getattr(fn, "decorator_list", []):
        walk(deco)
    return out


def _mentions_symbol(node: ast.AST) -> bool:
    """表达式里是否**提到**就地送符号（Name 或 `x._deliver_transport_send_request`）。"""

    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == INLINE_DELIVERY_SYMBOL:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == INLINE_DELIVERY_SYMBOL:
            return True
    return False


def _delivery_alias_names(own: list[ast.AST]) -> set[str]:
    """本帧把就地送符号**绑成别名**的目标名（`deliver = fn or _deliver_...`）。

    真身例证：`__init__.py:3098`（cookie 到期族的投递口经 `deliver_fn` 注入缝取默认值）。
    不认这一手，腿①/③/④ 对 cookie 一族就是瞎的——本席第一版正瞎在此，被腿④ 的名册
    双向相等当场打回（派生 False vs 声明 True）。
    """

    out: set[str] = set()
    for node in own:
        if not isinstance(node, ast.Assign) or not _mentions_symbol(node.value):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out.add(target.id)
    return out


def _build_frame(key: str, prefix: str, fn: ast.AST) -> _Frame:
    qualname = f"{prefix}.{fn.name}" if prefix else fn.name  # type: ignore[attr-defined]
    own = _own_nodes(fn)
    calls = {
        _dotted(node.func)
        for node in own
        if isinstance(node, ast.Call) and _dotted(node.func)
    }
    offloaded: set[str] = set()
    loop_hops: set[str] = set()
    for node in own:
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if not name:
            continue
        first: ast.AST | None = node.args[0] if node.args else None
        # `run_coroutine_threadsafe(_deliver(), loop)` 这类写法：第一实参是**协程调用**
        # 而非函数名，必须把被调的那个数也认下来（否则半吊子形状正好从尺下漏掉）。
        target_name = ""
        if isinstance(first, ast.Call):
            target_name = _dotted(first.func)
        elif first is not None:
            target_name = _dotted(first)
        if name in _THREAD_OFFLOAD_SYMBOLS and target_name:
            offloaded.add(target_name)
        if name in _NEW_LOOP_SYMBOLS:
            loop_hops.add(name)
            if target_name:
                offloaded.add(target_name)
    return _Frame(
        key=key,
        name=fn.name,  # type: ignore[attr-defined]
        qualname=qualname,
        lineno=fn.lineno,  # type: ignore[attr-defined]
        is_async=isinstance(fn, ast.AsyncFunctionDef),
        calls=frozenset(calls),
        offloaded=frozenset(o for o in offloaded if o),
        loop_hops=frozenset(loop_hops),
        delivery_aliases=frozenset(_delivery_alias_names(own)),
    )


def _index(sources: dict[str, str]) -> _Graph:
    """把「文件键 → 源码文本」解析成调用图（含嵌套 def；qualname 记路径）。"""

    frames: list[_Frame] = []

    def descend(key: str, prefix: str, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                frames.append(_build_frame(key, prefix, child))
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                descend(key, qualname, child)
                continue
            if isinstance(child, ast.ClassDef):
                descend(key, f"{prefix}.{child.name}" if prefix else child.name, child)
                continue
            descend(key, prefix, child)

    for key, text in sources.items():
        tree = ast.parse(text, filename=f"<{key}>")
        descend(key, "", tree)
    return _Graph(frames=frames)


@dataclass
class _Graph:
    """帧表 + 调用边解析（同名歧义时**保守当作未知叶子**，不猜）。"""

    frames: list[_Frame]
    _edges: dict[str, list[_Frame]] = field(default_factory=dict)

    def by_name(self, name: str, key: str | None = None) -> list[_Frame]:
        same_file = [f for f in self.frames if f.name == name and (key is None or f.key == key)]
        if same_file:
            return same_file
        across = [f for f in self.frames if _leaf(f.name) == _leaf(name) or f.name == name]
        unique = {f.id for f in across}
        return across if len(unique) == len(across) and len(across) <= 1 else []

    def callees(self, frame: _Frame) -> list[_Frame]:
        out: list[_Frame] = []
        for call in frame.calls:
            out.extend(self.by_name(_leaf(call), key=frame.key))
        return out

    def reaches(
        self, start: _Frame, predicate, *, limit: int = 6
    ) -> tuple[_Frame, ...]:
        """start 之后（含 start 自己）可达且满足 predicate 的帧（深度限幅 + 环保护）。"""

        found: list[_Frame] = []
        seen: set[str] = set()

        def visit(frame: _Frame, depth: int) -> None:
            if frame.id in seen or depth > limit:
                return
            seen.add(frame.id)
            if predicate(frame):
                found.append(frame)
            for callee in self.callees(frame):
                visit(callee, depth + 1)

        visit(start, 0)
        return tuple(found)

    def offload_targets(self, frame: _Frame) -> list[_Frame]:
        out: list[_Frame] = []
        for name in frame.offloaded:
            out.extend(self.by_name(_leaf(name), key=frame.key))
        return out


def _is_deliverer(frame: _Frame) -> bool:
    """本帧是否做就地投递：直呼符号，或经本帧自己绑定的别名调用（两条都算）。"""

    if any(_leaf(call) == INLINE_DELIVERY_SYMBOL for call in frame.calls):
        return True
    return any(_leaf(call) in frame.delivery_aliases for call in frame.calls)


def _is_submitter(frame: _Frame) -> bool:
    return any(_leaf(call) == CENTRAL_EXIT_SYMBOL for call in frame.calls)


def _add_job_targets(sources: dict[str, str]) -> list[tuple[str, int]]:
    """`<...>.add_job(<ident>, ...)` 的实参符号名与行号（只认直接标识符）。"""

    out: list[tuple[str, int]] = []
    for text in sources.values():
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and _leaf(_dotted(node.func)) == "add_job"
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                out.append((node.args[0].id, node.lineno))
    return out


# --------------------------------------------------------------------------- 名册（腿④）


@dataclass(frozen=True)
class Family:
    """一族主动投递的在册事实。

    `inline_delivered` 是**声明**，必须等于由 AST 派生的值——本件不许声明与实况脱钩。
    """

    family_id: str
    entry_frames: tuple[str, ...]
    submits_from: tuple[str, ...]
    inline_delivered: bool


ACTIVE_PUSH_FAMILIES: tuple[Family, ...] = (
    Family(
        family_id="reminder",
        entry_frames=("_reminder_job",),
        submits_from=("_push_via_central_exit_now",),
        inline_delivered=True,
    ),
    Family(
        family_id="cookie_expiry",
        entry_frames=("_cookie_expiry_reminder_job",),
        submits_from=("_push_via_central_exit_now",),
        inline_delivered=True,
    ),
    Family(
        family_id="progress_ack",
        entry_frames=("_submit_progress_ack",),
        submits_from=("_submit_progress_ack",),
        inline_delivered=True,
    ),
    Family(
        family_id="group_digest",
        entry_frames=("_digest_push_job",),
        submits_from=("_push_daily_group_digests",),
        inline_delivered=False,
    ),
    Family(
        family_id="daily_assist",
        entry_frames=("_meal_job", "_morning_job", "_evening_job"),
        submits_from=("_push_daily_assist_private",),
        inline_delivered=False,
    ),
    Family(
        family_id="emergency_info",
        entry_frames=("_emergency_info_collect_job",),
        submits_from=("deliver_emergency",),
        inline_delivered=False,
    ),
)


# --------------------------------------------------------------------------- 规则（纯函数）


def rule_inline_frames_are_coroutines(graph: _Graph) -> list[str]:
    """腿①：直接 await 就地送符号的帧必须是协程函数（同步帧里 `await` 连编译都过不去，
    但**不 await 直接调用**同样错——返回值是协程对象，等于根本没投）。"""

    return [
        f"{frame.id}@:{frame.lineno} 调用了 {INLINE_DELIVERY_SYMBOL} 却不是 async def"
        for frame in graph.frames
        if _is_deliverer(frame) and not frame.is_async
    ]


def rule_no_thread_boundary_carries_submit_or_delivery(graph: _Graph) -> list[str]:
    """腿②：跨线程包装（to_thread / run_in_executor / run_coroutine_threadsafe /
    asyncio.run）的第一实参**不得携带 submit 或就地送**——这正是 §2 更正③ 点名的
    「同时拿到两条最坏性质」的两种写法。"""

    violations: list[str] = []
    for frame in graph.frames:
        for name in sorted(frame.offloaded):
            if _leaf(name) in {CENTRAL_EXIT_SYMBOL, INLINE_DELIVERY_SYMBOL}:
                violations.append(
                    f"{frame.id}@:{frame.lineno} 把 {name} 整个丢进别的线程/循环"
                )
            for target in graph.by_name(_leaf(name), key=frame.key):
                if target.id == frame.id:
                    continue
                submitters = graph.reaches(target, _is_submitter)
                deliverers = graph.reaches(target, _is_deliverer)
                if submitters:
                    violations.append(
                        f"{frame.id}@:{frame.lineno} 经 {name} offload 的调用链携带中央出口 "
                        f"submit（{sorted({s.id for s in submitters})}）⇒ 认领台账静默不登记"
                    )
                if deliverers:
                    violations.append(
                        f"{frame.id}@:{frame.lineno} 经 {name} offload 的调用链携带就地投递"
                        f"（{sorted({d.id for d in deliverers})}）"
                    )
        if frame.loop_hops and (_is_submitter(frame) or graph.reaches(frame, _is_deliverer)):
            violations.append(
                f"{frame.id}@:{frame.lineno} 在携带 submit/就地送的路径上另起事件循环 "
                f"{sorted(frame.loop_hops)}"
            )
    return violations


def rule_jobs_that_deliver_inline_are_coroutines(
    graph: _Graph, sources: dict[str, str]
) -> list[str]:
    """腿③：凡经 `scheduler.add_job(<ident>)` 注册、且（可达地）做就地送的 job，
    其 callable 必须是 `async def`（同步 job 会被 AsyncIOScheduler 丢进线程池）。"""

    violations: list[str] = []
    for name, lineno in _add_job_targets(sources):
        for frame in graph.by_name(name):
            if graph.reaches(frame, _is_deliverer) and not frame.is_async:
                violations.append(
                    f"{frame.id}@:{frame.lineno} 是同步 job 却做就地投递"
                    f"（add_job@:{lineno}）"
                )
    return violations


def derive_inline_delivered(graph: _Graph, family: Family) -> bool:
    """由 AST 派生：该族入口是否可达就地投递（含入口自身）。"""

    for name in family.entry_frames:
        for frame in graph.by_name(name):
            if frame is None:
                continue
            if _is_deliverer(frame) or graph.reaches(frame, _is_deliverer):
                return True
    return False


def rule_ledger_matches_derivation(graph: _Graph) -> list[str]:
    """腿④双向相等：声明 True 而派生 False＝谎报；声明 False 而派生 True＝偷偷加了
    就地送却不更名册（§3 补丁落地必须与名册同批翻转）。"""

    violations: list[str] = []
    for family in ACTIVE_PUSH_FAMILIES:
        missing = [
            name
            for name in (*family.entry_frames, *family.submits_from)
            if not graph.by_name(name)
        ]
        if missing:
            violations.append(f"{family.family_id} 名册点不到帧：{sorted(missing)}")
            continue
        derived = derive_inline_delivered(graph, family)
        if derived != family.inline_delivered:
            violations.append(
                f"{family.family_id} 名册声明 inline_delivered="
                f"{family.inline_delivered} 与派生值 {derived} 不符"
            )
        submits_reachable = any(
            graph.reaches(frame, _is_submitter)
            for name in family.entry_frames
            for frame in graph.by_name(name)
        )
        if not submits_reachable:
            violations.append(
                f"{family.family_id} 从入口可达不到中央出口 {CENTRAL_EXIT_SYMBOL}"
                "（绕过唯一出口＝第二条通路，本仓零容忍）"
            )
    return violations


# --------------------------------------------------------------------------- 用例：真文件


def test_index_scans_every_declared_file() -> None:
    for key, path in SCANNED_FILES.items():
        assert path.exists(), f"扫描面缺件：{key} → {path}"
        assert path.read_text(encoding="utf-8").strip(), f"扫描面空件：{key}"


def test_inline_delivery_ledger_is_not_blind(graph_and_frames) -> None:
    """扫描器没瞎：本仓确实存在「就地送」帧，且已知的几枚必在账上。

    没有这一条，腿①②③ 都可能因为「一帧都没扫到」而空跑成全绿假锁。
    """

    graph, _frames = graph_and_frames
    deliverers = {frame.name for frame in graph.frames if _is_deliverer(frame)}
    submitters = {frame.name for frame in graph.frames if _is_submitter(frame)}
    assert len(deliverers) >= _MIN_INLINE_DELIVERY_FRAMES, sorted(deliverers)
    assert len(submitters) >= _MIN_CENTRAL_EXIT_FRAMES, sorted(submitters)
    assert {
        "_deliver_due_reminders",
        "_submit_progress_ack",
        "_run_capability_through_pipeline",
    } <= deliverers, sorted(deliverers)
    assert {"_push_via_central_exit_now", "deliver_emergency"} <= submitters, sorted(
        submitters
    )


def test_inline_delivery_frames_are_all_coroutine_functions(graph_and_frames) -> None:
    graph, _frames = graph_and_frames
    assert rule_inline_frames_are_coroutines(graph) == []


def test_submit_is_never_carried_across_a_thread_boundary(graph_and_frames) -> None:
    graph, _frames = graph_and_frames
    assert rule_no_thread_boundary_carries_submit_or_delivery(graph) == []


def test_scheduler_jobs_that_deliver_inline_are_registered_as_coroutines(
    real_sources, graph_and_frames
) -> None:
    graph, _frames = graph_and_frames
    assert rule_jobs_that_deliver_inline_are_coroutines(graph, real_sources) == []


def test_active_push_inline_delivery_ledger_matches_derivation(graph_and_frames) -> None:
    graph, _frames = graph_and_frames
    assert rule_ledger_matches_derivation(graph) == []


def test_nested_frame_calls_are_not_attributed_to_the_enclosing_frame() -> None:
    """帧归属自证（本席第一版探针在这里翻过车，14 处幻影违规）。"""

    poisoned = _SYNTHETIC_NESTED_SOURCE.replace("__MODE__", "async def")
    graph = _index({"synthetic": poisoned})
    outer = [f for f in graph.frames if f.name == "_register_like_monster"]
    inner = [f for f in graph.frames if f.name == "_inner"]
    assert len(outer) == 1 and len(inner) == 1
    assert not _is_deliverer(outer[0]), "嵌套协程的调用被错记到外层同步帧（扫描器会误报）"
    assert _is_deliverer(inner[0]), "真帧漏记：内层协程的调用没进账（扫描器会漏报）"


def test_three_families_today_submit_without_inline_delivery(graph_and_frames) -> None:
    """现状与名册同行可读：三族 inline_delivered=False 是「今天只入队」，不是漏写。"""

    graph, _frames = graph_and_frames
    for family in ACTIVE_PUSH_FAMILIES:
        assert derive_inline_delivered(graph, family) is family.inline_delivered
    today_queue_only = {
        f.family_id for f in ACTIVE_PUSH_FAMILIES if not f.inline_delivered
    }
    assert today_queue_only == {"group_digest", "daily_assist", "emergency_info"}, (
        "只入队族集合变了：§3 补丁落地或名册漂移，两处必须一起跟随"
    )


# --------------------------------------------------------------------------- 用例：注毒台
# 每把毒都先用**同一份规则函数**打在自己的合成源上（先自试），断言「必须咬到」；
# 还原态（把符号换成注释）再断言「不咬」——否则毒是空跑的，锁是假的。

_SYNTHETIC_NESTED_SOURCE = '''
def _register_like_monster() -> None:
    __MODE__ _inner():
        _deliver_transport_send_request(bot, None, request, None, None, None)

    scheduler.add_job(_inner, "cron")
'''

_SYNTHETIC_HALF_BAKED_JOB = '''
import asyncio

def _digest_push_job() -> None:
    _push_daily_group_digests(config, queue, gate)
    asyncio.run_coroutine_threadsafe(_deliver(), loop)

def _push_daily_group_digests(config, queue, gate) -> None:
    submit_active_push(queue, request, gate)

async def _deliver() -> None:
    await _deliver_transport_send_request(bot, None, request, None, None, None)

scheduler.add_job(_digest_push_job, "cron")
'''

_SYNTHETIC_OFFLOADED_SUBMIT = '''
import asyncio

async def _digest_push_job() -> None:
    await asyncio.to_thread(_push_daily_group_digests, config, queue, gate)
    await _deliver_transport_send_request(bot, None, request, None, None, None)

def _push_daily_group_digests(config, queue, gate) -> None:
    submit_active_push(queue, request, gate)

scheduler.add_job(_digest_push_job, "cron")
'''

_SYNTHETIC_SYNC_DELIVERER = '''
def _bad_frame() -> None:
    _deliver_transport_send_request(bot, None, request, None, None, None)
'''

_SYNTHETIC_CLEAN_BASELINE = '''
async def _digest_push_job() -> None:
    await _push_daily_group_digests(config, queue, gate)

async def _push_daily_group_digests(config, queue, gate) -> None:
    submit_active_push(queue, request, gate)
    receipt = await _deliver_transport_send_request(bot, None, request, None, None, None)

scheduler.add_job(_digest_push_job, "cron")
'''


def _violations_for(source: str) -> list[str]:
    graph = _index({"synthetic": source})
    return (
        rule_inline_frames_are_coroutines(graph)
        + rule_no_thread_boundary_carries_submit_or_delivery(graph)
        + rule_jobs_that_deliver_inline_are_coroutines(graph, {"synthetic": source})
    )


def test_poison_half_baked_shape_is_caught() -> None:
    """毒①「线程里 submit ＋ 回主循环就地送」：本件的立件理由，必须当场咬。"""

    hits = _violations_for(_SYNTHETIC_HALF_BAKED_JOB)
    assert hits, "半吊子形状没被咬到 ⇒ 本件是空跑锁"
    assert any("offload" in h or "另起事件循环" in h for h in hits), hits
    # 还原态对照：同一族改成「整链留在循环里」即不咬（证明咬的是形状、不是族名）。
    assert _violations_for(_SYNTHETIC_CLEAN_BASELINE) == []


def test_poison_offloaded_submit_is_caught() -> None:
    """毒②job 是协程、但把 submit 丢进 to_thread ⇒ 台账不登记，必须咬。"""

    hits = _violations_for(_SYNTHETIC_OFFLOADED_SUBMIT)
    assert any("携带中央出口" in h for h in hits), hits
    assert _violations_for(_SYNTHETIC_CLEAN_BASELINE) == []


def test_poison_sync_deliverer_is_caught() -> None:
    """毒③同步帧「调用」就地送（拿到协程对象却从不 await＝没投），必须咬。"""

    hits = rule_inline_frames_are_coroutines(_index({"synthetic": _SYNTHETIC_SYNC_DELIVERER}))
    assert hits, hits
    assert _violations_for(_SYNTHETIC_CLEAN_BASELINE) == []


def test_poison_nested_attribution_is_two_sided() -> None:
    """毒④把内层协程改成 `def` ⇒ 咬「非协程帧做就地送」，但不许把账记到外层帧上。"""

    poisoned = _SYNTHETIC_NESTED_SOURCE.replace("__MODE__", "def")
    graph = _index({"synthetic": poisoned})
    hits = rule_inline_frames_are_coroutines(graph)
    assert hits, "内层同步帧调用就地送没被咬到 ⇒ 腿①空跑"
    assert all("_register_like_monster@" not in h for h in hits), (
        f"违规被记到外层同步帧（帧归属尺又瞎了）：{hits}"
    )
    assert any("_register_like_monster._inner@" in h for h in hits), hits


# --------------------------------------------------------------------------- 行为锁：队列


def _send_request(request_id: str) -> SendRequest:
    rendered = RenderedOutput(
        request_id=request_id,
        content_type="text",
        content_ref={"text": "S264 认领台账行为锁正文"},
        text_fallback="S264 认领台账行为锁正文",
        privacy_level=PrivacyLevel.PERSONAL,
    )
    return SendRequest(
        request_id=request_id,
        session_id=f"private:{request_id}",
        target_scope=SessionType.PRIVATE,
        target_id="10001",
        capability_id="bot.group_digest_push",
        content=rendered,
        send_policy=SendPolicy.QUEUED,
        priority="normal",
        max_messages=1,
        dedupe_key=f"daily:s264:{request_id}",
        cooldown_key=f"s264:{request_id}",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


@pytest.fixture()
def sqlite_queue(tmp_path: Path) -> SQLiteSendRequestQueue:
    return SQLiteSendRequestQueue(
        tmp_path / "s264-queue.sqlite3",
        audit_logger=InMemoryAuditLogger(),
    )


def test_inline_claim_ledger_only_exists_inside_an_event_loop(
    sqlite_queue: SQLiteSendRequestQueue,
) -> None:
    """腿⑤：设计前提的**物理**证据——认领台账只在有运行中事件循环时登记。

    线程提交（三族 job 今天的形状）⇒ 台账空 ⇒ `claim_due` 不否决 ⇒ 只有 60–90s 时间
    宽限、没有硬互斥；协程内提交 ⇒ 台账登记 ⇒ 跨任务认领被否决（内联在途不双发）；
    提交任务终结后台账清簿放行（互斥只在「在途」窗口内，不是永久阻塞）。
    """

    base = datetime.now(timezone.utc).replace(microsecond=0)
    due_later = base + timedelta(hours=1)

    # ① 线程提交：无台账、无互斥。
    thread_request = _send_request("s264-from-thread")
    outcome: dict[str, object] = {}

    def _submit_in_thread() -> None:
        outcome["receipt"] = sqlite_queue.submit(thread_request, now=base)

    worker_thread = threading.Thread(target=_submit_in_thread)
    worker_thread.start()
    worker_thread.join(timeout=30)
    assert not worker_thread.is_alive(), "线程提交挂死：本用例的前提（无事件循环）没造出来"
    # SEAT-FIX-QKEY（Q-G6）跟随：认领台账槽键从 request_id 收口为行身份
    # dedupe_key（兄弟行各占各槽），本腿的「登记了吗」判定同步换尺。
    assert thread_request.dedupe_key not in sqlite_queue._inline_claims, (
        "线程提交竟然登记了认领台账 ⇒ 本件立论（台账只在循环内）已被现实推翻，"
        "必须回来改设计而不是改期望值"
    )
    claimed_from_thread = sqlite_queue.claim_due(now=due_later, limit=5)
    assert [entry.send_request.request_id for entry in claimed_from_thread] == [
        thread_request.request_id
    ], "线程提交行应可被立即认领（今天三族只有时间宽限，没有硬互斥）"
    sqlite_queue.mark_sent(thread_request.request_id, now=due_later)

    # ② 协程内提交：登记台账，跨任务认领被否决；任务终结后清簿放行。
    loop_request = _send_request("s264-from-loop")

    async def _submit_on_loop() -> bool:
        sqlite_queue.submit(loop_request, now=base)
        # SEAT-FIX-QKEY（Q-G6）跟随：槽键＝行身份 dedupe_key。
        registered = loop_request.dedupe_key in sqlite_queue._inline_claims
        # 认领者换成「另一个执行体」（线程/别的任务）＝生产 worker 的身份关系。
        claimed = await asyncio.to_thread(
            sqlite_queue.claim_due, now=due_later, limit=5
        )
        assert claimed == [], (
            f"内联在途却被认领＝双发窗口又开了：{[e.send_request.request_id for e in claimed]}"
        )
        return registered

    assert asyncio.run(_submit_on_loop()) is True, "协程内提交未登记认领台账"
    # 协程已结束 ⇒ 提交任务终结 ⇒ 死认领清簿，行重新可认领（不是永久阻塞）。
    recovered = sqlite_queue.claim_due(now=due_later, limit=5)
    assert [entry.send_request.request_id for entry in recovered] == [
        loop_request.request_id
    ], recovered
    sqlite_queue.mark_sent(loop_request.request_id, now=due_later)


# --------------------------------------------------------------- 行为锁：缺省配置下的三族


def test_worker_path_is_the_only_delivery_route_for_the_three_families(
    graph_and_frames,
) -> None:
    """腿⑥：更正① 的执法面——三族今天唯一的送达指望是「别人」（队列 worker）。

    三段判据：
    ① 三族名册 `inline_delivered=False` 与派生值相等（本件腿④已钉，这里再点一次名）；
    ② 缺省 `bot_send_queue_enabled=False`/`bot_send_queue_worker_enabled=False`
      （现读 `Config.model_fields`，不猜）⇒ 新建部署没有任何 worker；
    ③ 缺省队列实现 `InMemorySendQueue` 不提供 worker 认领面（`list_due`/`mark_sent`
      等）⇒ 生产根的 `_send_queue_is_drainable`（真身
      `__init__.py:1510`，四件 hasattr 的与判据）必然判 False。
      本用例断**事实**（属性不存在），不复制那份判据。

    §3 补丁落地（三族改就地送）后 ① 会翻红——那是**设计要的效果**：翻转名册与本段
    名表必须与补丁同批，谁偷懒谁红。
    """

    _graph, _frames = graph_and_frames
    queue_only = sorted(
        f.family_id for f in ACTIVE_PUSH_FAMILIES if not f.inline_delivered
    )
    assert queue_only == ["daily_assist", "emergency_info", "group_digest"], queue_only

    defaults = Config.model_fields
    assert defaults["bot_send_queue_enabled"].default is False, (
        "缺省值变了 ⇒ 更正① 的「缺省配置下三族彻底不送达」这条判定要重新现算"
    )
    assert defaults["bot_send_queue_worker_enabled"].default is False

    in_memory = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    for drain_method in ("list_due", "mark_sent", "mark_retryable_failure", "mark_final_failure"):
        assert not hasattr(in_memory, drain_method), (
            f"InMemory 队列长出了 worker 认领面 {drain_method}："
            "缺省部署「没人投递」这条现状锁的前提变了，须重新现算"
        )


def test_queue_sent_receipt_is_not_proof_of_delivery() -> None:
    """腿⑥伴生：`InMemorySendQueue.submit` 回的是**假 SENT**（零网络调用）。

    这条存在的理由：`submit_active_push` 的返回值一路被当「投递结论」读，而它证明的
    只是「入队成功」。任何拿队列回执宣称「已送达」的代码都是把这条读反了。
    """

    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    receipt = queue.submit(_send_request("s264-fake-sent"))
    assert receipt.state is ReceiptState.SENT
    assert receipt.transport != "nonebot", "假回执连 transport 都是队列自己的，别当真实通道"
    assert queue.safe_summary()[ReceiptState.SENT.value] == 1, (
        "队列侧「已 SENT」计数与真实网络投递毫无关系，这枚数字不许被叙述成送达数"
    )


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def real_sources() -> dict[str, str]:
    return {key: path.read_text(encoding="utf-8") for key, path in SCANNED_FILES.items()}


@pytest.fixture(scope="module")
def graph_and_frames(real_sources) -> tuple[_Graph, list[_Frame]]:
    graph = _index(real_sources)
    return graph, graph.frames
