"""细分开关必须接入真实处理器，而非只生成菜单。"""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    resolve_poke_reply,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
    build_product_descriptors,
)
from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
    ProductFeatureGate,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins/bot_unified_runtime/__init__.py"
ADMIN = Principal("operator", ("super_admin",))


@pytest.fixture
def control(tmp_path):
    store = FeatureStateStore(tmp_path / "state.json", descriptors=build_product_descriptors())
    return store, FeatureControlService(store)


def disable(service, node):
    service.change(node, False, principal=ADMIN, expected_version=service.detail(node)["state"]["version"])


def test_subfeatures_have_executable_references_and_parent_state(control):
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        SUBFEATURE_DESCRIPTORS,
    )

    store, service = control
    assert len(SUBFEATURE_DESCRIPTORS) >= 10
    for descriptor in SUBFEATURE_DESCRIPTORS:
        assert descriptor.implementation_ref
        file, symbol = descriptor.implementation_ref.split("#", 1)
        path = (ROOT / file).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        assert any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol for n in ast.walk(tree))
        assert descriptor.parent_id and descriptor.documentation_refs
        # 缺省态判据从「一律 True」改成「等于自己声明的缺省档」：
        # 2026-09-25 goal-12 波补登记 ``bot.plugin.chat.reactions.meme``（情绪时刻
        # 发一张表情包）时显式 default_enabled=False —— 一条**新增的自动外发腿**
        # 不许未经用户点头就自己上现网。旧断言把那枚合理登记判成失败（原红＝
        # 常驻断言与"新增腿默认关"这条纪律互斥），改成本式后仍然执法两件事：
        # ① 声明 True 的一旦被父链/依赖带关仍会红；② 声明与实况不符也红。
        assert store.get(descriptor.id).effective_enabled == descriptor.default_enabled
        if not descriptor.default_enabled:
            # 默认关 ≠ 打不开：超管必须能把它拨到 True（否则登记是假的）。
            service.change(
                descriptor.id, True, principal=ADMIN,
                expected_version=service.detail(descriptor.id)["state"]["version"],
            )
            assert store.get(descriptor.id).effective_enabled
            service.change(
                descriptor.id, False, principal=ADMIN,
                expected_version=service.detail(descriptor.id)["state"]["version"],
            )
            assert not store.get(descriptor.id).effective_enabled
    disable(service, "bot.ingress")
    assert not store.get("bot.ingress.file_read").effective_enabled
    assert store.get("bot.plugin.chat").effective_enabled


def test_snapshot_is_immutable_and_new_event_sees_hot_change(control):
    _, service = control
    gate = ProductFeatureGate(service)
    before = gate.snapshot()
    disable(service, "bot.ingress.file_read")
    assert before.enabled("bot.ingress.file_read")  # 已开始任务不被强杀
    assert not gate.snapshot().enabled("bot.ingress.file_read")
    assert not before.enabled("unknown.feature")
    with pytest.raises(TypeError):
        before.states["bot.ingress.file_read"] = False


def test_snapshot_failure_is_closed_without_exception_text(control, monkeypatch):
    _, service = control
    def fail():
        raise OSError("Bearer sensitive C:/private/config.db")
    monkeypatch.setattr(service, "state_snapshot", fail)
    snapshot = ProductFeatureGate(service).snapshot()
    assert not snapshot.available
    assert not snapshot.enabled("bot.ingress.file_read")
    assert "sensitive" not in repr(snapshot)


def test_async_snapshot_reads_once_off_event_loop(control, monkeypatch):
    _, service = control
    original = service.state_snapshot
    threads = []
    def read():
        threads.append(threading.get_ident())
        return original()
    monkeypatch.setattr(service, "state_snapshot", read)
    snapshot = asyncio.run(ProductFeatureGate(service).snapshot_async())
    for _ in range(20):
        assert snapshot.enabled("bot.ingress.file_read")
    assert len(threads) == 1 and threads[0] != threading.get_ident()


class Event:
    group_id = None
    message_id = "m"
    sender = SimpleNamespace(nickname="tester")
    def get_plaintext(self): return "文件内容是什么"
    def get_session_id(self): return "private_u"
    def get_user_id(self): return "u"
    def is_tome(self): return True


def test_disabled_file_reader_not_called_in_real_normalizer(control, monkeypatch, tmp_path):
    from plugins.bot_unified_runtime import _incoming_from_nonebot_event
    from plugins.bot_unified_runtime.domains.files.sources import file_reader

    _, service = control
    source = tmp_path / "example.md"
    source.write_text("private-fixture-content", encoding="utf-8")
    calls = []
    original = file_reader.read_supported_file
    def read(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(file_reader, "read_supported_file", read)
    gate = ProductFeatureGate(service)
    kwargs = {"bot_id": "b", "segments": [{"type": "file", "data": {"file": str(source)}}], "reply_chain": []}
    disable(service, "bot.ingress.file_read")
    result = _incoming_from_nonebot_event(Event(), feature_enabled=gate.snapshot().enabled, **kwargs)
    assert calls == [] and "private-fixture-content" not in result.plain_text
    service.change("bot.ingress.file_read", None, principal=ADMIN, expected_version=1)
    result = _incoming_from_nonebot_event(Event(), feature_enabled=gate.snapshot().enabled, **kwargs)
    assert calls == [str(source)] and "private-fixture-content" in result.plain_text


def handler(name, bindings):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    namespace = dict(bindings)
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)  # noqa: S102 - 仅执行仓库固定 handler，非用户输入。
    return namespace[name]


@pytest.mark.parametrize("node", ["bot.plugin.meme_library", "bot.plugin.meme_library.auto_absorb"])
def test_actual_meme_listener_respects_parent_and_child(control, node):
    _, service = control
    absorb = AsyncMock()
    callback = handler("_handle_meme_absorb", {
        "product_feature_gate": ProductFeatureGate(service), "meme_library_store": object(),
        "config": object(), "absorb_event_images": absorb,
    })
    disable(service, node)
    asyncio.run(callback(object(), object()))
    absorb.assert_not_awaited()
    service.change(node, None, principal=ADMIN, expected_version=1)
    asyncio.run(callback(object(), object()))
    absorb.assert_awaited_once()


def test_every_production_normalizer_call_injects_switches():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_incoming_from_nonebot_event"]
    assert len(calls) >= 10
    assert all(any(k.arg == "feature_enabled" for k in call.keywords) for call in calls)


def test_sqlite_peer_change_is_visible_in_next_execution_snapshot(tmp_path):
    from plugins.bot_unified_runtime.control_plane.sqlite_features import (
        SQLiteFeatureStateStore,
    )

    descriptors = build_product_descriptors()
    store = SQLiteFeatureStateStore(tmp_path / "features.sqlite3", descriptors=descriptors)
    peer = SQLiteFeatureStateStore(store.path, descriptors=descriptors)
    gate = ProductFeatureGate(FeatureControlService(store))
    before = gate.snapshot()
    peer.set_enabled("bot.ingress", False, actor="operator", expected_revision=0)
    after = gate.snapshot()
    assert before.enabled("bot.ingress.file_read")
    assert not after.enabled("bot.ingress.file_read")
    assert after.graph_revision == 1


@pytest.mark.parametrize("disabled", ["bot.ingress", "bot.ingress.audio_transcode", "bot.ingress.telegram_media", "bot.ingress.reply_lookup"])
def test_actual_chat_preprocessing_respects_snapshot(control, disabled):
    _, service = control
    disable(service, disabled)
    transcode, enrich, lookup = AsyncMock(), AsyncMock(), AsyncMock(return_value=[])
    local_calls = []

    class Normalized(Exception):
        pass

    def normalize(**kwargs):
        assert kwargs["feature_enabled"]("bot.ingress.file_read") == (disabled != "bot.ingress")
        raise Normalized

    callback = handler("_handle_chat", {
        "time": SimpleNamespace(perf_counter=lambda: 0),
        "_log_runtime_event": lambda *a, **kw: None, "runtime_event_log": None,
        "product_feature_gate": ProductFeatureGate(service),
        "_extract_onebot_raw_segments": lambda _: [{"type": "record"}],
        "_transcode_record_segments": transcode,
        "enrich_telegram_file_segments": enrich,
        "collect_reply_chain_async": lookup,
        "_make_onebot_reply_lookup": lambda _: None,
        "collect_reply_chain": lambda _: local_calls.append(True) or [],
        "_incoming_from_nonebot_event": normalize,
    })
    with pytest.raises(Normalized):
        asyncio.run(callback(SimpleNamespace(self_id="b"), Event()))
    assert transcode.await_count == int(disabled not in {"bot.ingress", "bot.ingress.audio_transcode"})
    assert enrich.await_count == int(disabled not in {"bot.ingress", "bot.ingress.telegram_media"})
    assert lookup.await_count == int(disabled not in {"bot.ingress", "bot.ingress.reply_lookup"})
    assert len(local_calls) == int(disabled in {"bot.ingress", "bot.ingress.reply_lookup"})


def test_poke_capability_is_registered_for_unified_pipeline(control):
    _, service = control
    gate = ProductFeatureGate(service)
    assert gate(None, "bot.poke").allowed
    disable(service, "bot.plugin.poke")
    assert not gate(None, "bot.poke").allowed


def _make_poke_back_dispatcher():
    """与生产 __init__.py poke 段同构的真实出站链（V21-DISPATCH-001）：
    route→review→send 门面周期 + 统一出站执行器（固定映射解析 friend_poke）。"""
    from plugins.bot_unified_runtime.control_plane.dispatcher import (
        OutboundSideEffectExecutor,
        PokeInteractionService,
        build_interaction_dispatcher,
    )
    from plugins.bot_unified_runtime.domains.core.decision.outbound import (
        OutboundIntent,
        OutboundOperation,
        OutboundPart,
        OutboundTarget,
        build_default_transport_registry,
        derive_dedupe_key,
    )

    def route_intent(payload):
        group = bool(payload.get("group"))
        group_id = int(payload.get("group_id") or 0)
        user_id = int(payload.get("user_id") or 0)
        dedupe_key = derive_dedupe_key(
            "qq",
            f"pokeback.{'group' if group else 'private'}.{group_id}.{user_id}",
            "direct",
        )
        return OutboundIntent(
            operation=OutboundOperation.POKE,
            target=OutboundTarget(
                platform="qq",
                session_type="group" if group else "private",
                target_id=str(group_id if group else user_id),
                bot_id=str(payload.get("bot_id") or ""),
                adapter="onebot",
            ),
            parts=[
                OutboundPart(
                    part_id=f"poke-back.{dedupe_key}",
                    kind="poke",
                    content_ref={
                        "api_params": (
                            {"group_id": group_id, "user_id": user_id}
                            if group
                            else {"user_id": user_id}
                        )
                    },
                )
            ],
            feature_id="bot.plugin.poke.poke_back",
            policy_revision="legacy-poke-v2",
            dedupe_key=dedupe_key,
            trace_id="test-pokeback",
        )

    executor = OutboundSideEffectExecutor(
        transport_registry=build_default_transport_registry(),
    )
    service = PokeInteractionService(
        dispatch=build_interaction_dispatcher(executor, route_intent=route_intent),
    )

    async def dispatch_poke_back(bot, event, *, group):
        await service.handle(
            {
                "bot": bot,
                "bot_id": str(getattr(bot, "self_id", "") or ""),
                "group": group,
                "group_id": getattr(event, "group_id", 0),
                "user_id": getattr(event, "user_id", 0),
            }
        )

    return dispatch_poke_back


@pytest.mark.parametrize("disabled", ["bot.plugin.poke", "bot.plugin.poke.reply", "bot.plugin.poke.poke_back"])
def test_actual_poke_handler_respects_fine_switches(control, disabled):
    _, service = control
    disable(service, disabled)
    dispatcher_calls = []
    def build(*args, **kwargs):
        dispatcher_calls.append(True)
        # poke v2：mode 字段驱动回复形态（fixed=固定话术，无外部依赖）。
        return SimpleNamespace(active=True, poke_back=True, reply="fixture", group=False, mode="fixed", audit_tags=("poke", "poke_group", "poke_mode:fixed"))
    bot = SimpleNamespace(self_id="b", call_api=AsyncMock())
    send = AsyncMock()
    callback = handler("_handle_poke_notice", {
        "product_feature_gate": ProductFeatureGate(service),
        "_poke_dispatcher": SimpleNamespace(build_poke_reaction=build),
        "_dispatch_poke_back": _make_poke_back_dispatcher(),
        "_config_with_runtime_overrides": lambda *args: None,
        "config": None, "runtime_settings": None,
        "asyncio": asyncio,
        "resolve_poke_reply": resolve_poke_reply,
        "_record_poke_affinity": lambda *args, **kwargs: "",
        "_poke_llm_reply": AsyncMock(return_value=""),
        "_pick_poke_meme": lambda *args, **kwargs: None,
        "meme_library_store": None,
        "model_router": None,
        "_send_parts_through_unified_pipeline": send,
    })
    asyncio.run(callback(bot, SimpleNamespace(user_id=1)))
    assert len(dispatcher_calls) == int(disabled != "bot.plugin.poke")
    assert bot.call_api.await_count == int(disabled == "bot.plugin.poke.reply")
    assert send.await_count == int(disabled == "bot.plugin.poke.poke_back")
