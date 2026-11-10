"""Offline contract tests for per-request timeout diagnostics.

Only selected source AST is executed. No application package is imported.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import concurrent.futures
import contextvars
import json
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply"


def _deadline_namespace() -> dict:
    path = CHAT_ROOT / "runtime" / "deadline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    namespace = {"__name__": "terra_deadline_test", "__file__": str(path)}
    exec(compile(tree, str(path), "exec"), namespace)  # noqa: S102
    return namespace


def _tool_loop() -> object:
    path = CHAT_ROOT / "capabilities" / "chat.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_generate_with_tool_loop"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            function,
        ],
        type_ignores=[],
    )
    namespace = {
        "__name__": "terra_tool_loop_test",
        "json": json,
        "time": time,
        "_execute_mcp_tool_call": lambda _name, _arguments: "{}",
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)  # noqa: S102
    return namespace["_generate_with_tool_loop"]


def _chatpool(deadline: dict, executor: concurrent.futures.ThreadPoolExecutor) -> tuple:
    path = CHAT_ROOT / "runtime" / "pipeline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {
        "_BoundedSubmissionGate", "_retire_offloaded_task",
        "_capability_timeout_error", "offload_capability",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
        or isinstance(node, ast.ClassDef) and node.name in names
    ]
    assert {node.name for node in functions} == names
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *functions,
        ],
        type_ignores=[],
    )

    class SyntheticCapabilityTimeout(RuntimeError):
        pass

    original_import = builtins.__import__

    def safe_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "plugins.bot_unified_runtime.runtime.capability_protocols":
            return SimpleNamespace(CapabilityTimeout=SyntheticCapabilityTimeout)
        if name == "plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline":
            return SimpleNamespace(**deadline)
        if name.startswith("plugins."):
            raise AssertionError("unexpected application import: " + name)
        return original_import(name, *args, **kwargs)

    safe_builtins = dict(vars(builtins))
    safe_builtins["__import__"] = safe_import
    namespace = {
        **deadline,
        "__name__": "terra_chatpool_test",
        "__builtins__": safe_builtins,
        "asyncio": asyncio,
        "contextvars": contextvars,
        "threading": threading,
        "time": time,
        "logger": logging.getLogger("terra_chatpool_test"),
        "inflight_scope_of": lambda _capability_id: "",
        "capability_hard_timeout_seconds": lambda: 0.5,
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)  # noqa: S102
    gate = namespace["_BoundedSubmissionGate"](4)
    namespace["_get_chat_pool"] = lambda: (executor, gate)
    return namespace["offload_capability"], gate, SyntheticCapabilityTimeout


def _timeout_error_factory() -> object:
    path = CHAT_ROOT / "runtime" / "pipeline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_capability_timeout_error"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            function,
        ],
        type_ignores=[],
    )

    class SyntheticCapabilityTimeout(RuntimeError):
        pass

    original_import = builtins.__import__

    def safe_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "__future__":
            return original_import(name, *args, **kwargs)
        if name == "plugins.bot_unified_runtime.runtime.capability_protocols":
            return SimpleNamespace(CapabilityTimeout=SyntheticCapabilityTimeout)
        raise AssertionError("unexpected application import: " + name)

    safe_builtins = dict(vars(builtins))
    safe_builtins["__import__"] = safe_import
    namespace = {
        "__name__": "terra_pipeline_timeout_test",
        "__builtins__": safe_builtins,
        "logger": SimpleNamespace(debug=lambda *args, **kwargs: None),
    }
    assert original_import is not None
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)  # noqa: S102
    return namespace["_capability_timeout_error"]


def test_inflight_snapshot_uses_existing_budget_and_clears_when_recorded() -> None:
    namespace = _deadline_namespace()
    clock = [10.0]
    namespace["time"] = SimpleNamespace(monotonic=lambda: clock[0])
    budget = namespace["DeadlineBudget"](30.0)

    clock[0] = 11.0
    budget.mark_in_flight("context")
    clock[0] = 12.25
    snapshot = budget.diagnostic_snapshot()

    assert snapshot["in_flight_stage"] == "context"
    assert snapshot["elapsed_ms"] == 2250
    assert snapshot["in_flight_ms"] == 1250

    clock[0] = 13.0
    budget.record_phase("context", 11.0)
    snapshot = budget.diagnostic_snapshot()
    assert snapshot["in_flight_stage"] == "unknown"
    assert snapshot["in_flight_ms"] is None
    assert snapshot["phases_ms"]["context"] == 2000
    assert budget.deadline == 40.0


def test_snapshot_excludes_unapproved_stage_names_and_returns_a_copy() -> None:
    namespace = _deadline_namespace()
    budget = namespace["DeadlineBudget"](30.0)
    budget.mark_in_flight("context")
    budget.record_phase("context", time.monotonic())
    budget.mark_in_flight("private_payload")

    snapshot = budget.diagnostic_snapshot()
    assert snapshot["in_flight_stage"] == "unknown"
    assert "private_payload" not in json.dumps(snapshot)
    snapshot["phases_ms"]["context"] = -1
    assert budget.diagnostic_snapshot()["phases_ms"]["context"] >= 0


def test_snapshot_is_consistent_during_concurrent_phase_updates() -> None:
    namespace = _deadline_namespace()
    budget = namespace["DeadlineBudget"](30.0)
    start = threading.Event()
    failures: list[Exception] = []

    def update() -> None:
        try:
            start.wait(2.0)
            for _ in range(500):
                began = time.monotonic()
                budget.mark_in_flight("context")
                budget.record_phase("context", began)
        except Exception as exc:  # noqa: BLE001
            failures.append(exc)

    worker = threading.Thread(target=update, daemon=True)
    worker.start()
    try:
        start.set()
        for _ in range(500):
            snapshot = budget.diagnostic_snapshot()
            assert snapshot["in_flight_stage"] in {"context", "unknown"}
            assert snapshot["elapsed_ms"] >= 0
            if snapshot["in_flight_stage"] == "unknown":
                assert snapshot["in_flight_ms"] is None
            else:
                assert snapshot["in_flight_ms"] >= 0
    finally:
        worker.join(timeout=3.0)
    assert not worker.is_alive()
    assert not failures


def test_model_calls_mark_llm_again_after_tool_phase() -> None:
    generate = _tool_loop()

    class Budget:
        stage = "unknown"
        deadline = None

        def ensure_available(self, stage: str) -> None:
            pass

        def timeout_for(self, value: object) -> None:
            return None

        def mark_in_flight(self, stage: str) -> None:
            self.stage = stage

        def record_phase(self, stage: str, _started: float) -> None:
            if self.stage == stage:
                self.stage = "unknown"

        def clear_in_flight(self, stage: str) -> None:
            if self.stage == stage:
                self.stage = "unknown"

        def expired(self) -> bool:
            return False

    budget = Budget()
    calls = []

    class Provider:
        def generate(self, _messages: object, **_kwargs: object) -> object:
            calls.append(budget.stage)
            if len(calls) == 1:
                return SimpleNamespace(
                    raw_usage=None,
                    text="",
                    tool_calls=[{
                        "id": "synthetic",
                        "function": {"name": "test_tool", "arguments": "{}"},
                    }],
                )
            return SimpleNamespace(raw_usage=None, text="synthetic", tool_calls=[])

    generate(
        llm_provider=Provider(),
        model_router=None,
        messages=[],
        message_text="",
        override="",
        tools=[{"function": {"name": "test_tool"}}],
        llm_options={},
        request_budget=budget,
    )
    assert calls == ["llm", "llm"]
    assert budget.stage == "unknown"


def test_same_budget_reference_crosses_real_chatpool_worker() -> None:
    namespace = _deadline_namespace()
    budget = namespace["DeadlineBudget"](30.0)
    entered = threading.Event()
    release = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        offload, gate, timeout_class = _chatpool(namespace, executor)

        def task(_message: object, _decision: object) -> str:
            try:
                namespace["publish_timeout_budget"](budget)
                budget.mark_in_flight("context")
                entered.set()
                release.wait(3.0)
                return "synthetic"
            finally:
                entered.set()

        async def exercise() -> None:
            pending = asyncio.create_task(offload(task)(None, SimpleNamespace(capability_id="bot.chat")))
            try:
                assert await asyncio.to_thread(entered.wait, 2.0)
                try:
                    await pending
                except timeout_class as exc:
                    assert "context" in str(exc)
                    assert "elapsed_ms" in str(exc)
                    assert "private_payload" not in str(exc)
                else:
                    raise AssertionError("expected chatpool timeout")
                assert gate.in_flight == 1
            finally:
                release.set()
                await asyncio.gather(pending, return_exceptions=True)
                for _ in range(200):
                    if gate.in_flight == 0:
                        break
                    await asyncio.sleep(0.01)
                assert gate.in_flight == 0

        asyncio.run(exercise())


def test_chatpool_late_completion_cannot_replace_next_request_budget() -> None:
    namespace = _deadline_namespace()
    first_entered, second_entered = threading.Event(), threading.Event()
    first_release, second_release = threading.Event(), threading.Event()
    first_finished = threading.Event()

    def task(stage: str, entered: threading.Event, release: threading.Event) -> object:
        def run(_message: object, _decision: object) -> str:
            budget = namespace["DeadlineBudget"](30.0)
            try:
                namespace["publish_timeout_budget"](budget)
                budget.mark_in_flight(stage)
                entered.set()
                release.wait(3.0)
                budget.record_phase(stage, time.monotonic())
                return "synthetic"
            finally:
                entered.set()
                if stage == "context":
                    first_finished.set()
        return run

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        offload, gate, timeout_class = _chatpool(namespace, executor)

        async def exercise() -> None:
            decision = SimpleNamespace(capability_id="bot.chat")
            first = asyncio.create_task(offload(task("context", first_entered, first_release))(None, decision))
            second = None
            try:
                assert await asyncio.to_thread(first_entered.wait, 2.0)
                try:
                    await first
                except timeout_class as exc:
                    assert "context" in str(exc)
                else:
                    raise AssertionError("expected first timeout")
                second = asyncio.create_task(offload(task("llm", second_entered, second_release))(None, decision))
                assert await asyncio.to_thread(second_entered.wait, 2.0)
                first_release.set()
                assert await asyncio.to_thread(first_finished.wait, 2.0)
                try:
                    await second
                except timeout_class as exc:
                    assert "llm" in str(exc)
                    assert "context" not in str(exc)
                    assert "private_payload" not in str(exc)
                else:
                    raise AssertionError("expected second timeout")
            finally:
                first_release.set()
                second_release.set()
                await asyncio.gather(*(item for item in (first, second) if item is not None), return_exceptions=True)
                for _ in range(200):
                    if gate.in_flight == 0:
                        break
                    await asyncio.sleep(0.01)
                assert gate.in_flight == 0

        asyncio.run(exercise())


def test_concurrent_chatpool_workers_cannot_exchange_budget_references() -> None:
    namespace = _deadline_namespace()
    entered = {stage: threading.Event() for stage in ("context", "llm")}
    release = threading.Event()

    def task(stage: str) -> object:
        def run(_message: object, _decision: object) -> str:
            budget = namespace["DeadlineBudget"](30.0)
            try:
                namespace["publish_timeout_budget"](budget)
                budget.mark_in_flight(stage)
                entered[stage].set()
                release.wait(3.0)
                return "synthetic"
            finally:
                entered[stage].set()
        return run

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        offload, gate, timeout_class = _chatpool(namespace, executor)

        async def exercise() -> None:
            decision = SimpleNamespace(capability_id="bot.chat")
            tasks = {
                stage: asyncio.create_task(offload(task(stage))(None, decision))
                for stage in ("context", "llm")
            }
            try:
                for signal in entered.values():
                    assert await asyncio.to_thread(signal.wait, 2.0)
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                for stage, exc in zip(tasks, results):
                    assert isinstance(exc, timeout_class)
                    assert stage in str(exc)
                    assert ("llm" if stage == "context" else "context") not in str(exc)
                    assert "private_payload" not in str(exc)
            finally:
                release.set()
                await asyncio.gather(*tasks.values(), return_exceptions=True)
                for _ in range(200):
                    if gate.in_flight == 0:
                        break
                    await asyncio.sleep(0.01)
                assert gate.in_flight == 0

        asyncio.run(exercise())


def test_chatpool_queued_timeout_does_not_invent_a_phase() -> None:
    namespace = _deadline_namespace()
    blocker_entered = threading.Event()
    blocker_release = threading.Event()
    worker_entered = threading.Event()

    def block_pool() -> None:
        blocker_entered.set()
        blocker_release.wait(3.0)

    def queued_worker(_message: object, _decision: object) -> str:
        worker_entered.set()
        return "synthetic"

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        blocker = executor.submit(block_pool)
        offload, gate, timeout_class = _chatpool(namespace, executor)

        async def exercise() -> None:
            pending = None
            try:
                assert await asyncio.to_thread(blocker_entered.wait, 2.0)
                pending = asyncio.create_task(
                    offload(queued_worker)(None, SimpleNamespace(capability_id="bot.chat"))
                )
                try:
                    await pending
                except timeout_class as exc:
                    assert "queued" in str(exc)
                    assert "unknown" in str(exc)
                    assert "context" not in str(exc)
                    assert "private_payload" not in str(exc)
                else:
                    raise AssertionError("expected queued timeout")
                assert not worker_entered.is_set()
                assert gate.in_flight == 1
            finally:
                blocker_release.set()
                if pending is not None:
                    await asyncio.gather(pending, return_exceptions=True)
                for _ in range(200):
                    if gate.in_flight == 0:
                        break
                    await asyncio.sleep(0.01)
                assert gate.in_flight == 0

        asyncio.run(exercise())
        blocker.result(timeout=2.0)


def test_timeout_exception_carries_safe_diagnostics_to_existing_consumer() -> None:
    factory = _timeout_error_factory()
    exc = factory(
        "bot.chat",
        400.0,
        diagnostic={
            "execution_state": "started",
            "in_flight_stage": "context",
            "elapsed_ms": 1234,
            "in_flight_ms": 1200,
        },
    )
    message = str(exc)
    assert "context" in message
    assert "1234" in message
    assert "bot.chat" in message
    assert "private_payload" not in message

    path = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "ops" / "monitor" / "error_report.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    builder = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_error_report"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "exc"
        for node in ast.walk(builder)
    )


def test_timeout_exception_never_exports_unapproved_phase_or_extra_fields() -> None:
    factory = _timeout_error_factory()
    exc = factory(
        "bot.chat",
        400.0,
        diagnostic={
            "execution_state": "started",
            "in_flight_stage": "private_payload",
            "elapsed_ms": 1,
            "prompt": "synthetic_private_text",
        },
    )
    assert "private_payload" not in str(exc)
    assert "synthetic_private_text" not in str(exc)


def test_abandoned_worker_keeps_gate_until_late_completion() -> None:
    path = CHAT_ROOT / "runtime" / "pipeline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    retire = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_retire_offloaded_task"
    )
    offload = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "offload_capability"
    )
    assert any(
        isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "BaseException"
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_retire_offloaded_task"
            for call in ast.walk(node)
        )
        for node in ast.walk(offload)
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            retire,
        ],
        type_ignores=[],
    )
    namespace = {
        "__name__": "terra_retire_test",
        "logger": SimpleNamespace(debug=lambda *args, **kwargs: None),
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)  # noqa: S102

    class Task:
        callback = None
        error_reads = 0

        def done(self) -> bool:
            return False

        def add_done_callback(self, callback: object) -> None:
            self.callback = callback

        def cancelled(self) -> bool:
            return False

        def exception(self) -> None:
            self.error_reads += 1

    task = Task()
    released = []
    namespace["_retire_offloaded_task"](task, lambda: released.append(True))
    assert released == []
    assert task.callback is not None
    task.callback(task)
    assert released == [True]
    assert task.error_reads == 1
