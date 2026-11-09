"""Offline primary-chat timeout path with real source control flow and event loop."""

from __future__ import annotations

import ast
import asyncio
import builtins
import contextvars
import logging
import re
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "bot_unified_runtime"
CHAT = PACKAGE / "domains" / "chat_reply"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _selected(path: Path, names: set[str], namespace: dict) -> None:
    tree = _tree(path)
    found = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in names
    ]
    assert {node.name for node in found} == names
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *found,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)


def _deadline() -> dict:
    path = CHAT / "runtime" / "deadline.py"
    namespace = {"__name__": "terra_live_deadline", "__file__": str(path)}
    exec(compile(_tree(path), str(path), "exec"), namespace)
    return namespace


def _acg_constants() -> SimpleNamespace:
    path = PACKAGE / "domains" / "core" / "search" / "search_intent.py"
    names = {"ACG_TIER_STRONG", "ACG_TIER_MEDIUM", "ACG_TIER_WEAK", "ACG_DOMAIN_TERMS"}
    nodes = []
    for node in _tree(path).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in names:
                nodes.append(node)
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id in names for target in node.targets):
                nodes.append(node)
    assert len(nodes) == len(names)
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *nodes,
        ],
        type_ignores=[],
    )
    namespace = {"__name__": "terra_acg_constants"}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return SimpleNamespace(
        ACG_DOMAIN_TERMS=namespace["ACG_DOMAIN_TERMS"],
        ACG_TIER_STRONG=namespace["ACG_TIER_STRONG"],
    )


def _imports(deadline: dict, timeout_class: type, acg: object):
    original = builtins.__import__
    roles = SimpleNamespace(ROLE_ADMIN="admin", ROLE_SUPER_ADMIN="super_admin")

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name == "plugins.bot_unified_runtime.runtime.capability_protocols":
            return SimpleNamespace(CapabilityTimeout=timeout_class)
        if name == "plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline":
            return SimpleNamespace(**deadline)
        if name == "plugins.bot_unified_runtime.domains.core.search.search_intent":
            return acg
        if name == "plugins.bot_unified_runtime.domains.chat_reply.policy.roles":
            return roles
        if name == "plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health":
            return SimpleNamespace(PER_HOP_TIMEOUT_FLOOR_SECONDS=1.0)
        if name.startswith("plugins."):
            raise AssertionError("unexpected application import: " + name)
        return original(name, *args, **kwargs)

    result = dict(vars(builtins))
    result["__import__"] = guarded
    return result


def _question_module(imports: dict) -> types.ModuleType:
    path = CHAT / "runtime" / "question_intent.py"
    module = types.ModuleType("terra_live_question_intent")
    module.__file__ = str(path)
    module.__dict__["__builtins__"] = imports
    sys.modules[module.__name__] = module
    try:
        exec(compile(_tree(path), str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(module.__name__, None)
        raise
    return module


def _report_builder(imports: dict) -> object:
    path = PACKAGE / "domains" / "ops" / "monitor" / "error_report.py"
    namespace = {
        "__name__": "terra_live_report",
        "__builtins__": imports,
        "logger": logging.getLogger("terra_live_report"),
        "AUDIENCE_PUBLIC": "public",
        "AUDIENCE_ADMIN_FULL": "admin_full",
        "_GROUP_FACING_SESSION_VALUES": {"group", "channel"},
        "_PUBLIC_METHOD_LABELS": (),
        "_PUBLIC_ID_LABELS": (),
        "_HELP_TEXT_PUBLIC": "",
        "_FALLBACK_HELP_TEXT_PUBLIC": "",
        "_HELP_TEXT": "",
        "_FALLBACK_HELP_TEXT": "",
        "_default_config_getter": lambda _key: None,
        "redact_local_secrets": lambda text: text,
        "_stack_excerpt": lambda *_args: [],
        "_self_review": lambda *_args: ("", ""),
        "_rows": lambda rows: rows,
        "_kv": lambda label, value: {"label": label, "value": str(value or "")},
        "_trigger_time_label": lambda _message: "",
        "_session_label": lambda _message: "",
        "_persona_signature": lambda _getter: ("", ""),
        "_persona_text": lambda *_args: "",
        "_trigger_echo": lambda _message: "",
        "_innermost_frame_name": lambda _lines: "",
        "_route_kind_label": lambda _capability: "",
        "_module_ownership": lambda _capability: "",
        "_reason_label": lambda *_args: "",
        "_admin_contact_pairs": lambda *_args, **_kwargs: [],
        "_config_snapshot": lambda *_args: [],
        "_version_pairs": lambda *_args: [],
        "_protocol_label": lambda _adapter: "",
        "_connection_mode": lambda _adapter: "",
        "_card_avatar_uri": lambda _getter: "",
        "public_tier_leaks": lambda _text: [],
        "build_text_fallback": lambda _report: "",
    }
    _selected(
        path,
        {"_session_is_group_facing", "_sender_is_admin", "_audience_tier",
         "_keep_named_rows", "_apply_audience", "build_error_report"},
        namespace,
    )
    return namespace["build_error_report"]


def _factory(deadline: dict, question: types.ModuleType, imports: dict) -> object:
    class NullMemeSearchProvider:
        pass

    class NullWebSearchProvider:
        pass

    namespace = {
        **deadline,
        "__name__": "terra_live_chat",
        "__builtins__": imports,
        "time": time,
        "logger": logging.getLogger("terra_live_chat"),
        "NullMemeSearchProvider": NullMemeSearchProvider,
        "NullWebSearchProvider": NullWebSearchProvider,
        "_resolve_web_ratio": lambda value, **_kwargs: value,
        "InjectionCheckInput": SimpleNamespace,
        "InjectionAction": SimpleNamespace(BLOCK="block", ALLOW="allow"),
        "check_prompt_injection": lambda item: SimpleNamespace(
            request_id=item.request_id,
            action="allow",
            detected_patterns=[],
            sanitized_text=item.plain_text,
            reasons=[],
            risk_level="low",
            privacy_level="personal",
            debug_id="dbg_synthetic",
        ),
        "_media_gate_session_key": lambda *_args, **_kwargs: "",
        "_pending_intimate_head_switch": lambda **_kwargs: False,
        "split_animated_segments": lambda _segments: ([], []),
        "extract_image_urls": lambda _segments: [],
        "_reply_chain_image_urls": lambda *_args, **_kwargs: [],
        "extract_video_source": lambda _segments: "",
        "extract_audio_source": lambda _segments: "",
        "extract_meme_query": lambda _text: "",
        "PrivacyLevel": SimpleNamespace(GROUP="group", PERSONAL="personal"),
        "SessionType": SimpleNamespace(GROUP="group"),
        "classify_question_intent": question.classify_question_intent,
        "llm_timely_domain_hint": question.llm_timely_domain_hint,
        "_context_error_result": lambda **_kwargs: "synthetic_finished",
    }
    _selected(CHAT / "capabilities" / "chat.py", {"build_chat_capability"}, namespace)
    return namespace["build_chat_capability"]


def _pipeline(deadline: dict, imports: dict, pool: ThreadPoolExecutor) -> tuple[object, object]:
    namespace = {
        **deadline,
        "__name__": "terra_live_pipeline",
        "__builtins__": imports,
        "asyncio": asyncio,
        "contextvars": contextvars,
        "threading": threading,
        "time": time,
        "logger": logging.getLogger("terra_live_pipeline"),
        "inflight_scope_of": lambda _capability_id: "",
        "capability_hard_timeout_seconds": lambda: 0.5,
    }
    _selected(
        CHAT / "runtime" / "pipeline.py",
        {"_BoundedSubmissionGate", "_retire_offloaded_task",
         "_capability_timeout_error", "offload_capability"},
        namespace,
    )
    gate = namespace["_BoundedSubmissionGate"](2)
    namespace["_get_chat_pool"] = lambda: (pool, gate)
    return namespace["offload_capability"], gate


def _run_live_case(block_stage: str) -> None:
    deadline = _deadline()
    timeout_ns = {"__name__": "terra_live_timeout"}
    _selected(PACKAGE / "runtime" / "capability_protocols.py", {"CapabilityTimeout"}, timeout_ns)
    timeout_class = timeout_ns["CapabilityTimeout"]
    imports = _imports(deadline, timeout_class, _acg_constants())
    question = _question_module(imports)
    entered = threading.Event()
    release = threading.Event()

    class StopAfterRelease(Exception):
        pass

    class Context:
        def model_copy(self, **_kwargs: object) -> object:
            return self

    class ContextProvider:
        def build_context(self, **_kwargs: object) -> object:
            if block_stage == "context":
                entered.set()
                release.wait(3.0)
                raise StopAfterRelease()
            return Context()

    class Router:
        def generate(self, *_args: object, **_kwargs: object) -> object:
            entered.set()
            release.wait(3.0)
            raise StopAfterRelease()

    message = SimpleNamespace(
        request_id="req_synthetic", debug_id="dbg_synthetic", sender_id="synthetic",
        session_id="synthetic", session_type="private", platform="qq", adapter="onebot",
        bot_id="synthetic", group_id=None, message_id="synthetic", sender_roles=["admin"],
        plain_text="synthetic ordinary question?", raw_segments=[],
    )
    decision = SimpleNamespace(
        capability_id="bot.chat", risk_level="low", privacy_level="personal", context_budget=2048,
    )
    report_builder = _report_builder(imports)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="terra-live-context")
    try:
        factory = _factory(deadline, question, imports)
        capability = factory(
            character_provider=ContextProvider(),
            llm_provider=SimpleNamespace(),
            model_router=Router() if block_stage == "intent" else None,
            request_budget_seconds=20.0,
        )
        offload, gate = _pipeline(deadline, imports, pool)

        async def exercise() -> None:
            task = asyncio.create_task(offload(capability)(message, decision))
            try:
                assert await asyncio.to_thread(entered.wait, 2.0), "target stage was not reached"
                try:
                    await task
                except timeout_class as exc:
                    caught = exc
                    payload = report_builder(
                        message, "bot.chat", exc, config_getter=lambda _key: None,
                        include_env=False,
                    )
                else:
                    raise AssertionError("expected actual offload timeout")
                assert block_stage in payload["exc_message"]
                assert re.search(r"elapsed_ms[=:]\s*\d+", payload["exc_message"])
                assert message.plain_text not in payload["exc_message"]
                public = SimpleNamespace(**{**vars(message), "sender_roles": []})
                assert report_builder(
                    public, "bot.chat", caught, config_getter=lambda _key: None,
                    include_env=False,
                )["exc_message"] == ""
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                for _ in range(200):
                    if gate.in_flight == 0:
                        break
                    await asyncio.sleep(0.01)
                assert gate.in_flight == 0

        asyncio.run(exercise())
    finally:
        release.set()
        pool.shutdown(wait=True)
        sys.modules.pop(question.__name__, None)


def test_real_chat_context_timeout_reaches_admin_report() -> None:
    _run_live_case("context")


def test_real_chat_intent_hint_timeout_reaches_admin_report() -> None:
    _run_live_case("intent")
