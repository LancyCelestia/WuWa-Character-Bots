"""校园自动转发回归（campus，v1 范围：只做自动转发）。

离线验证（不依赖 NoneBot 运行时）：

1. 来源门：enabled ∧ 学校账号 ∧ 群白名单三重与；"*" 通配 = 学校号全部群；
2. 录制去重：同 message_id 只转发一次（SnowLuma 重连重发不双推）；
3. 转发请求：私聊作用域、面向主人日常号、dedupe 按 message_id；
4. 来源门外/空文本：零落库零转发；
5. 保留期裁剪：跨天首条录制时机会性触发，防消息库无界增长；
6. config：默认关闭、名单解析、db 路径重映射进 data 目录。
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.capabilities.campus import (
    _CAMPUS_FORWARD_INTRO,
    _CAMPUS_FORWARD_MAX_CHARS,
    CampusForwardService,
    build_campus_source,
    matches_campus_source,
)
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.sources.campus_store import CampusStore

_NOW = datetime(2026, 9, 15, 21, 30, tzinfo=timezone.utc)
_TODAY = _NOW.date().isoformat()

_SCHOOL_QQ = "2300230562"
_OWNER_QQ = "3865067623"


def _source(**overrides) -> SimpleNamespace:
    base = {
        "enabled": True,
        "self_ids": frozenset({_SCHOOL_QQ}),
        "whitelist": frozenset({"111", "222"}),
        "notify_qq": _OWNER_QQ,
        "push_bot_id": "3958874605",
        "persona_profile_id": "default",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _store(tmp_path: Path) -> CampusStore:
    return CampusStore(str(tmp_path / "campus.sqlite3"))


def _service(tmp_path: Path, **source_overrides) -> CampusForwardService:
    return CampusForwardService(
        store=_store(tmp_path),
        source=_source(**source_overrides),
    )


def _forward(service: CampusForwardService, group_id: str, text: str, *, mid: str = "m1"):
    return service.record(
        bot_id=_SCHOOL_QQ,
        group_id=group_id,
        sender_id="10001",
        sender_name="张三",
        text=text,
        message_id=mid,
        now=_NOW,
    )


# ---------- 来源门 ----------


def test_matches_requires_all_gates() -> None:
    """enabled ∧ 学校账号 ∧ 群白名单三重与；任一不满足即 False。"""
    assert matches_campus_source(_source(), _SCHOOL_QQ, "111")
    assert not matches_campus_source(_source(enabled=False), _SCHOOL_QQ, "111")
    assert not matches_campus_source(_source(), "3958874605", "111")  # 非学校账号
    assert not matches_campus_source(_source(), _SCHOOL_QQ, "333")  # 名单外群
    assert not matches_campus_source(_source(self_ids=frozenset()), _SCHOOL_QQ, "111")
    assert not matches_campus_source(_source(whitelist=frozenset()), _SCHOOL_QQ, "111")


def test_matches_wildcard_whitelist_forwards_all_groups() -> None:
    """白名单含 "*"：学校号全部群放行（显式 opted-in，不算猜群）。"""
    source = _source(whitelist=frozenset({"*"}))
    assert matches_campus_source(source, _SCHOOL_QQ, "any-group")
    assert not matches_campus_source(source, "3958874605", "any-group")


def test_build_campus_source_from_config() -> None:
    """config → source：名单解析、空值安全。"""
    config = SimpleNamespace(
        bot_campus_enabled=True,
        bot_campus_self_ids=[_SCHOOL_QQ],
        bot_campus_group_whitelist=["111"],
        bot_campus_notify_qq=_OWNER_QQ,
        bot_campus_push_bot_id="3958874605",
        bot_persona_profile_id="default",
    )
    source = build_campus_source(config)
    assert source.enabled is True
    assert source.self_ids == frozenset({_SCHOOL_QQ})
    assert source.whitelist == frozenset({"111"})
    assert source.notify_qq == _OWNER_QQ
    assert source.push_bot_id == "3958874605"
    # 全关配置：enabled=False，名单空集合，目标为空。
    empty = build_campus_source(
        SimpleNamespace(
            bot_campus_enabled=False,
            bot_campus_self_ids=[],
            bot_campus_group_whitelist=[],
            bot_campus_notify_qq="",
            bot_campus_push_bot_id="",
            bot_persona_profile_id="default",
        )
    )
    assert empty.enabled is False
    assert empty.self_ids == frozenset()
    assert empty.notify_qq == ""


# ---------- 录制、去重与转发 ----------


def test_record_builds_private_forward_request(tmp_path: Path) -> None:
    """来源门内首条消息 → 转发载荷；正文含群号/成员/原文。

    请求级断言（会话目标/去重/策略）由端到端例
    ``test_complete_enqueues_owner_private_request_end_to_end`` 经真管线承接。
    """
    service = _service(tmp_path)

    payload = _forward(service, "111", "明早八点交表", mid="m1")

    assert payload is not None
    assert payload.message_id == "m1"
    assert payload.group_id == "111"
    assert payload.sender_name == "张三"
    assert payload.text == "明早八点交表"
    body = payload.body
    assert body.startswith(_CAMPUS_FORWARD_INTRO)
    assert "111" in body and "张三" in body and "明早八点交表" in body


def test_record_duplicate_message_not_forwarded_twice(tmp_path: Path) -> None:
    """同 message_id 只转发一次（重连重发不双推）。"""
    service = _service(tmp_path)
    first = _forward(service, "111", "明早八点交表", mid="m1")
    second = _forward(service, "111", "明早八点交表", mid="m1")

    assert first is not None
    assert second is None
    assert len(service.store.list_day(_TODAY)) == 1


def test_record_outside_source_gate_ignored(tmp_path: Path) -> None:
    """来源门外的消息零落库零转发。"""
    service = _service(tmp_path)
    assert (
        service.record(
            bot_id="3958874605",
            group_id="111",
            sender_id="1",
            sender_name="",
            text="闲聊",
            message_id="m9",
            now=_NOW,
        )
        is None
    )
    assert service.store.list_day(_TODAY) == []


def test_record_empty_text_skipped(tmp_path: Path) -> None:
    """纯图片/空文本消息不落库不转发（v1 只处理文本）。"""
    service = _service(tmp_path)
    assert _forward(service, "111", "", mid="m-empty") is None
    assert service.store.list_day(_TODAY) == []


def test_record_long_text_truncated(tmp_path: Path) -> None:
    """超长原文截断，避免单条转发刷屏。"""
    service = _service(tmp_path)
    payload = _forward(service, "111", "长" * 3000, mid="m-long")

    assert payload is not None
    assert len(payload.body) <= _CAMPUS_FORWARD_MAX_CHARS + len(
        _CAMPUS_FORWARD_INTRO
    ) + 60


# ---------- 保留期裁剪 ----------


def test_prune_triggered_on_new_day(tmp_path: Path) -> None:
    """跨天首条录制时机 prune：保留期外旧行被清理。"""
    service = _service(tmp_path)
    store = service.store
    old_day = (_NOW - timedelta(days=120)).date().isoformat()
    store.record_message(
        message_id="old",
        self_id=_SCHOOL_QQ,
        group_id="111",
        sender_id="1",
        sender_name="",
        text="旧消息",
        date_key=old_day,
        occurred_at=f"{old_day}T10:00:00+08:00",
    )

    _forward(service, "111", "今天的消息", mid="m1")
    next_day = _NOW + timedelta(days=1)
    service.record(
        bot_id=_SCHOOL_QQ,
        group_id="111",
        sender_id="1",
        sender_name="张三",
        text="明天的消息",
        message_id="m2",
        now=next_day,
    )

    assert store.list_day(old_day) == []
    assert len(store.list_day(_NOW.date().isoformat())) == 1
    assert len(store.list_day(next_day.date().isoformat())) == 1


def test_prune_keeps_recent_days(tmp_path: Path) -> None:
    """store.prune 只删保留期外的旧行。"""
    store = _store(tmp_path)
    old_day = (_NOW - timedelta(days=120)).date().isoformat()
    for mid, day in (("old", old_day), ("new", _TODAY)):
        store.record_message(
            message_id=mid,
            self_id=_SCHOOL_QQ,
            group_id="111",
            sender_id="1",
            sender_name="",
            text=mid,
            date_key=day,
            occurred_at=f"{day}T10:00:00+08:00",
        )

    assert store.prune(keep_days=90, now=_NOW) == 1
    assert [row["message_id"] for row in store.list_day(_TODAY)] == ["new"]


# ---------- config ----------


def test_config_defaults() -> None:
    """campus 全链路默认关闭；db 默认落在 data 目录。"""
    assert Config().bot_campus_enabled is False
    assert Config().bot_campus_notify_qq == ""
    assert Config().bot_campus_push_bot_id == ""
    assert Config().bot_campus_self_ids == []
    assert Config().bot_campus_group_whitelist == []


def test_config_list_fields_accept_json_and_comma_strings() -> None:
    """名单/账号键接受 JSON 数组串与逗号分隔串。"""
    config = Config(
        bot_campus_self_ids='["2300230562"]',
        bot_campus_group_whitelist="111,222",
    )
    assert config.bot_campus_self_ids == ["2300230562"]
    assert config.bot_campus_group_whitelist == ["111", "222"]


def test_config_db_path_resolves_into_data_dir() -> None:
    """db 路径默认相对 data/，装载后重映射为绝对路径（防写进源码树）。"""
    resolved = Path(Config().bot_campus_db_path)
    assert resolved.is_absolute()
    assert resolved.name == "campus.sqlite3"


@pytest.mark.parametrize("bad", ["24:00", "21:60"])
def test_config_time_keys_still_validated(bad: str) -> None:
    """既有 HH:MM 校验不受新增键不变（回归哨兵）。"""
    with pytest.raises(ValidationError):
        Config(bot_group_digest_push_time=bad)


# ===========================================================================
# U17-CAMPUS-WIRE：转发投递交**既有中央管线**（IngressGateway→RuntimePipeline
# ._prepare 门禁/幂等→能力→_complete 统一入队），删除自建 SendRequest 与裸
# send_queue.submit 旁路。零新框架、零第二 submit 通路。
# ===========================================================================

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "bot_unified_runtime"
_DOMAIN_CAMPUS = _PLUGIN_ROOT / "domains" / "assistant" / "campus" / "campus.py"

_GROUP = "111"


def _legacy_forward_text(group_id: str, sender_name: str, text: str) -> str:
    """现网（改前）转发正文公式的**独立复写**——改后必须逐字节相同。

    抄自改前 ``CampusForwardService._build_forward_request``（本树 git 前状态，
    campus.py:145-148），作为 oracle 与被测实现互证，不做同义反复。
    """
    who = f"{sender_name}：" if sender_name else ""
    prefix = f"【校园转发】群{group_id} {who}"
    budget = max(0, 1500 - len(prefix))
    return prefix + text[:budget] + ("…" if len(text) > budget else "")


def _drop_inline_imports(block: list) -> None:
    """剪除编译单元内的 import：其绑定会遮蔽测试注入的受控接缝（先例同左）。"""
    block[:] = [stmt for stmt in block if not isinstance(stmt, (ast.Import, ast.ImportFrom))]
    for stmt in block:
        for field in ("body", "orelse", "finalbody"):
            value = getattr(stmt, field, None)
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                _drop_inline_imports(value)
        for handler in getattr(stmt, "handlers", None) or []:
            _drop_inline_imports(handler.body)


def _extract_handler(func_name: str, **env):
    """AST 提取根 ``__init__.py`` 内嵌套 handler，在受控命名空间编译成裸函数。

    先例=tests/test_v21_s0_root_collect.py（嵌套 handler 无法直接 import）；
    装饰器与被测面无关故剥离，内嵌 import 剪除以让注入的接缝生效。
    """
    source = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == func_name
    ]
    assert len(matches) == 1, f"{func_name} 应恰一处定义，现={len(matches)}"
    node = matches[0]
    node.decorator_list = []  # .handle() 装配装饰器不属被测面
    _drop_inline_imports(node.body)
    ast.fix_missing_locations(node)
    namespace: dict = {
        "__package__": "plugins.bot_unified_runtime",
        "__name__": f"u17_campus_wire.{func_name}",
        "Any": object,
        "Bot": SimpleNamespace,
        "Event": SimpleNamespace,
    }
    namespace.update(env)
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"<{func_name}>", "exec"), namespace)  # noqa: S102 - 测试受控提取（先例 test_v21_s0_root_collect.py）
    return namespace[func_name]


class _GroupEvent:
    """``isinstance(event, GroupMessageEvent)`` 命中的学校群消息哑元。"""

    def __init__(
        self,
        group_id: str = _GROUP,
        *,
        text: str = "明早八点交表",
        message_id: str = "m1",
        user_id: str = "10001",
        card: str = "张三",
    ) -> None:
        self.group_id = group_id
        self.message_id = message_id
        self._text = text
        self._user_id = user_id
        self.sender = SimpleNamespace(card=card, nickname="小张")

    def get_plaintext(self) -> str:
        return self._text

    def get_user_id(self) -> str:
        return self._user_id


class _NoSubmitQueue:
    """裸 submit 复现锁：任何绕过中央管线的直接入队都当场炸。"""

    def __init__(self) -> None:
        self.calls: list = []

    def submit(self, request):  # pragma: no cover - 命中即测试失败
        self.calls.append(request)
        raise AssertionError("campus 不得再裸调 send_queue.submit（旁路已收编）")


class _PipelineSpy:
    """中央管线接缝替身：记录入口（handle/handle_async）与传入消息/能力。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _record(self, entry: str, message, capability, capability_id) -> None:
        self.calls.append(
            {
                "entry": entry,
                "message": message,
                "capability": capability,
                "capability_id": capability_id,
            }
        )

    def handle(self, message, capability, capability_id=""):
        self._record("handle", message, capability, capability_id)
        return SimpleNamespace(state=SimpleNamespace(value="sent"))

    def handle_async(self, message, capability, capability_id=""):
        self._record("handle_async", message, capability, capability_id)

        async def _done() -> SimpleNamespace:
            return SimpleNamespace(state=SimpleNamespace(value="sent"))

        return _done()


def _campus_handler_env(tmp_path: Path, **overrides):
    """装配 handler 受控命名空间：真服务 + 真工厂 + spy 管线 + 裸 submit 炸锁。"""
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        CampusForwardService,
        build_campus_forward_capability,
        build_campus_forward_message,
    )
    from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import (
        CampusStore,
    )

    source = overrides.pop("source", None) or _source()
    service = overrides.pop("service", None) or CampusForwardService(
        store=CampusStore(str(tmp_path / "campus.sqlite3")), source=source
    )
    env = {
        "campus_service": service,
        "campus_source": source,
        "asyncio": asyncio,
        "GroupMessageEvent": _GroupEvent,
        "pipeline": _PipelineSpy(),
        "send_queue": _NoSubmitQueue(),
        "build_campus_forward_message": build_campus_forward_message,
        "build_campus_forward_capability": build_campus_forward_capability,
        # U17-FIX：handler 消费回执 BLOCK 态（is 比较）每次执行都会求值该名。
        "ReceiptState": ReceiptState,
    }
    env.update(overrides)
    return env


def _run_campus_handler(tmp_path, event, **overrides):
    env = _campus_handler_env(tmp_path, **overrides)
    handler = _extract_handler("_handle_campus_record", **env)
    bot = SimpleNamespace(self_id=_SCHOOL_QQ)
    asyncio.run(handler(bot, event))
    return env


# ---------- ① 收编后仍逐字一致的用户可见形态 ----------


def test_forward_text_matches_legacy_bypass_verbatim(tmp_path: Path) -> None:
    """转发正文与改前旁路**逐字节相同**（前缀/群号/发言人/截断/省略号）。"""
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_text,
    )

    cases = [
        (_GROUP, "张三", "明早八点交表"),
        (_GROUP, "", "无名片发言人的闲聊"),
        (_GROUP, "张三", "长" * 3000),  # 截断满额
        (_GROUP, "张三", "多行\n第二行\n\t带制表"),
        # 预算边界附近：群号必须在 _source() 白名单内（原 "999999" 会被来源门
        # 正确拒绝致 record()=None，属用例夹具缺陷，CAMPUS-FIX-9 修正为 "222"）。
        ("222", "李四", "x" * 1480),
    ]
    for index, (group_id, sender_name, text) in enumerate(cases):
        recorded = _recorded_body(
            group_id, sender_name, text, tmp_path=tmp_path, tag=f"c{index}"
        )
        built = build_campus_forward_text(
            group_id=group_id, sender_name=sender_name, text=text
        )
        assert built == _legacy_forward_text(group_id, sender_name, text), text[:20]
        assert built == recorded, "record() 产出的 body 必须与纯格式化函数一致"
    long_text = "长" * 3000
    body = build_campus_forward_text(group_id=_GROUP, sender_name="张三", text=long_text)
    assert body.endswith("…")
    assert len(body) == 1501, f"改前=前缀+1491 字+省略号=1501，现={len(body)}"


def _recorded_body(
    group_id: str, sender_name: str, text: str, *, tmp_path: Path, tag: str
) -> str:
    """经**真服务 record()** 产出转发正文（走独立库文件，与格式化函数互证）。"""
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        CampusForwardService,
    )
    from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import (
        CampusStore,
    )

    service = CampusForwardService(
        store=CampusStore(str(tmp_path / f"body-{tag}.sqlite3")),
        source=_source(),
    )
    payload = service.record(
        bot_id=_SCHOOL_QQ,
        group_id=group_id,
        sender_id="10001",
        sender_name=sender_name,
        text=text,
        message_id=f"once-{tag}",
        now=_NOW,
    )
    assert payload is not None, "来源门内非空文本必须产出转发载荷"
    return payload.body


# ---------- ② 经中央管线，不再裸 submit（行为锁 + 结构锁） ----------


def test_handler_dispatches_through_central_pipeline(tmp_path: Path) -> None:
    """命中来源门 → 恰一次经中央管线、capability_id=bot.campus_forward、
    消息会话=主人私聊；裸 send_queue.submit 零调用（有炸锁）。"""
    env = _run_campus_handler(tmp_path, _GroupEvent())

    pipeline_spy = env["pipeline"]
    assert len(pipeline_spy.calls) == 1, f"应恰一次经中央管线，现={len(pipeline_spy.calls)}"
    call = pipeline_spy.calls[0]
    assert call["entry"] in {"handle", "handle_async"}
    assert call["capability_id"] == "bot.campus_forward"
    assert call["message"].session_id == f"private:{_OWNER_QQ}"
    assert env["send_queue"].calls == []
    # handler 走真实时钟（record() 不传 now），落库日=运行当日而非 _TODAY 钉值。
    today = datetime.now().astimezone().date().isoformat()
    assert env["campus_service"].store.list_day(today), "录制职责不变：仍先落库"


def test_handler_no_forward_outside_source_gate(tmp_path: Path) -> None:
    """三重来源门任一空 = 零转发零入队（收编不回退该硬约束）。"""
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        CampusForwardService,
    )
    from plugins.bot_unified_runtime.domains.assistant.campus.campus_store import (
        CampusStore,
    )

    broken_sources = [
        _source(enabled=False),
        _source(self_ids=frozenset()),
        _source(whitelist=frozenset()),
    ]
    for index, source in enumerate(broken_sources):
        service = CampusForwardService(
            store=CampusStore(str(tmp_path / f"gated-{index}.sqlite3")), source=source
        )
        env = _run_campus_handler(
            tmp_path, _GroupEvent(), service=service, source=source
        )
        assert env["pipeline"].calls == [], f"第 {index} 个坏门仍转发了"
        assert env["send_queue"].calls == []


def test_handler_source_gate_rejects_foreign_group(tmp_path: Path) -> None:
    """名单外群、非学校号：零经管线（三重门与改前同一实现）。"""
    env = _run_campus_handler(tmp_path, _GroupEvent(group_id="333"))
    assert env["pipeline"].calls == [], "白名单外群不得转发"
    handler_env = _campus_handler_env(tmp_path / "foreign-bot")
    handler = _extract_handler("_handle_campus_record", **handler_env)
    asyncio.run(handler(SimpleNamespace(self_id="3958874605"), _GroupEvent()))
    assert handler_env["pipeline"].calls == [], "非学校账号所在群不得转发"


def test_handler_duplicate_message_id_forwards_once(tmp_path: Path) -> None:
    """同 message_id 重发：store 幂等第二层拦住，不再进中央管线。"""
    env = _campus_handler_env(tmp_path)
    handler = _extract_handler("_handle_campus_record", **env)
    bot = SimpleNamespace(self_id=_SCHOOL_QQ)
    asyncio.run(handler(bot, _GroupEvent(message_id="dup-1")))
    asyncio.run(handler(bot, _GroupEvent(message_id="dup-1")))
    assert len(env["pipeline"].calls) == 1, "重复事件必须只转发一次"
    # handler 走真实时钟（record() 不传 now），落库日=运行当日而非 _TODAY 钉值。
    today = datetime.now().astimezone().date().isoformat()
    assert len(env["campus_service"].store.list_day(today)) == 1


def test_handler_isolated_and_send_api_free() -> None:
    """结构锁：handler 不再引用裸队列/自建请求，campus 面零平台发送 API。

    「绝不向学校群发送任何消息」的第二重保障：本域源码里不出现任何出站 API。
    """
    source = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_handle_campus_record"
    )
    names = {node.id for node in ast.walk(handler) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(handler) if isinstance(node, ast.Attribute)}
    assert "submit" not in attrs, "handler 内不得再出现 .submit(...)（旁路已收编）"
    assert "send_queue" not in names, "handler 不再需要裸队列引用"
    assert "pipeline" in names, "handler 必须经中央管线分发"
    assert not attrs & {"call_api", "send_msg", "send_group_msg", "send_private_msg"}, (
        f"handler 出现平台直发面：{sorted(attrs)}"
    )

    domain = _DOMAIN_CAMPUS.read_text(encoding="utf-8")
    for banned in (
        "SendRequest",
        "RenderedOutput",
        "SendPolicy",
        "send_group_msg",
        "send_private_msg",
        "call_api",
    ):
        assert banned not in domain, f"campus 真身不得再出现旁路构件：{banned}"


# ---------- ③ 目标私聊：用既有「按目标会话构造 IncomingMessage」表达 ----------


def test_forward_message_expresses_owner_private_target() -> None:
    """异会话投递既有表达：目标会话写进消息，由中央 _complete 推导出站目标。"""
    from plugins.bot_unified_runtime.contracts import SessionType
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_message,
    )

    payload = SimpleNamespace(
        group_id=_GROUP, sender_name="张三", text="明早八点交表", message_id="m1",
        body=_legacy_forward_text(_GROUP, "张三", "明早八点交表"),
    )
    message = build_campus_forward_message(_source(), payload)
    assert message.session_id == f"private:{_OWNER_QQ}"
    assert message.session_type is SessionType.PRIVATE
    assert message.sender_id == _OWNER_QQ
    assert message.group_id is None, "目标私聊绝不能带上学校群号"
    assert message.bot_id == "3958874605", "push_bot_id 选通道语义必须保持"
    assert message.message_id == "m1", "源消息 id 进消息体=中央幂等 claim 的键来源"
    assert message.privacy_level.value == "personal"


# ---------- ④ 端到端：真 RuntimePipeline + 真 feature gate + 真入队 ----------


def _central_pipeline(tmp_path: Path, *, idempotency_table=None):
    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
    )
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        InMemorySendQueue,
    )
    from plugins.bot_unified_runtime.runtime.pipeline import RuntimePipeline

    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    gate = ProductFeatureGate(
        FeatureControlService(
            FeatureStateStore(
                tmp_path / "features.json", descriptors=build_product_descriptors()
            )
        )
    )
    pipeline = RuntimePipeline(
        feature_gate=gate,
        send_queue=queue,
        audit_logger=audit,
        idempotency_table=idempotency_table,
    )
    return pipeline, queue


def _payload(**overrides):
    values = {
        "group_id": _GROUP,
        "sender_name": "张三",
        "text": "明早八点交表",
        "message_id": "m1",
    }
    values.update(overrides)
    values["body"] = _legacy_forward_text(
        values["group_id"], values["sender_name"], values["text"]
    )
    return SimpleNamespace(**values)


def test_complete_enqueues_owner_private_request_end_to_end(tmp_path: Path) -> None:
    """真管线：门禁放行 → _complete 入队一条主人私聊请求，字段与现网等价。"""
    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        ReceiptState,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )

    pipeline, queue = _central_pipeline(tmp_path)
    source = _source(persona_profile_id="shorekeeper")
    payload = _payload()
    receipt = pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert receipt.state is ReceiptState.SENT, "内存队列 submit 即 SENT（与改前同）"
    assert len(queue.sent_requests) == 1
    request = queue.sent_requests[0]
    assert request.capability_id == "bot.campus_forward"
    assert request.session_id == f"private:{_OWNER_QQ}"
    assert request.target_scope is SessionType.PRIVATE
    assert request.target_id == _OWNER_QQ
    assert request.bot_id == "3958874605"
    assert request.origin_message_id == "m1"
    assert request.content.text_fallback == payload.body
    assert request.content.content_type == "text"
    assert request.content.privacy_level is PrivacyLevel.PERSONAL
    assert request.privacy_level is PrivacyLevel.PERSONAL
    assert request.max_messages == 1
    assert request.persona_profile_id == "shorekeeper", "persona 经 audit_tags 保原值"
    assert "campus" in request.audit_tags and "forward" in request.audit_tags
    assert request.dedupe_key == f"bot.campus_forward:private:{_OWNER_QQ}:m1"


def test_no_outbound_request_ever_targets_school_group(tmp_path: Path) -> None:
    """负锁①：任何情况下都不产生以学校群为目标的出站请求。

    两半：(a) 误把源群会话喂进中央管线 → 中央 review 认定「PERSONAL 正文不得进群」
    直接 BLOCK，零入队（结构上不可能向学校群发）；(b) 正常收编路径产出的唯一
    请求目标是主人私聊。
    """
    from plugins.bot_unified_runtime.contracts import (
        IncomingMessage,
        ReceiptState,
        SessionType,
    )
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )

    pipeline, queue = _central_pipeline(tmp_path)
    source = _source()
    payload = _payload()
    group_message = IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id=source.push_bot_id,
        session_id=f"group:{_GROUP}",
        session_type=SessionType.GROUP,
        sender_id="10001",
        group_id=_GROUP,
        plain_text="明早八点交表",
        message_id="m1",
    )
    blocked = pipeline.handle(
        group_message,
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert blocked.state is ReceiptState.BLOCKED
    assert queue.sent_requests == [], "以学校群为目标的出站请求必须为零"

    pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert len(queue.sent_requests) == 1
    for request in queue.sent_requests:
        assert request.target_id != _GROUP
        assert request.session_id != f"group:{_GROUP}"
        assert request.target_scope is not SessionType.GROUP


def test_quiet_hours_and_rate_limit_do_not_swallow_campus_forward(tmp_path: Path) -> None:
    """负锁②：收编后校园转发不被安静时间/限流吞（现网「来一条转一条」保持）。

    锁的是**门语义事实**——quiet_hours 只拦 bot.chat/bot.content、限流只统计
    CHAT_CAPABILITY_IDS；handler 里没有任何豁免标记或绕管线代码。
    """
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.policy import QuietHoursSettings

    pipeline, queue = _central_pipeline(tmp_path)
    pipeline.quiet_hours_checker._settings_source = lambda: QuietHoursSettings(
        enabled=True,
        start_time="00:00",
        end_time="23:59",
        timezone_name="UTC",
        session_types=["private", "group"],
        bypass_roles=[],
    )
    source = _source()
    payload = _payload(message_id="qm-1")
    receipt = pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert receipt.state is ReceiptState.SENT, "安静时间全天开启仍必须转发（现网行为保持）"
    assert len(queue.sent_requests) == 1


def test_central_claim_adds_second_idempotency_layer(tmp_path: Path) -> None:
    """双保险：中央幂等表开启时重复事件第二次零入队（store 之外再多一层）。"""
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.event_idempotency import (
        EventIdempotencyTable,
    )

    pipeline, queue = _central_pipeline(
        tmp_path, idempotency_table=EventIdempotencyTable(ttl_seconds=600)
    )
    source = _source()
    payload = _payload()
    first = pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    second = pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert first.state is ReceiptState.SENT
    assert second.state is ReceiptState.BLOCKED
    assert len(queue.sent_requests) == 1


# ---------- ⑤ 注册册/登记表收口 ----------


def test_campus_forward_registered_for_feature_gate(tmp_path: Path) -> None:
    """bot.campus_forward 在能力注册册真实登记，且实网关放行（未登记即 BLOCKED）。"""
    from plugins.bot_unified_runtime.control_plane.features import FeatureStateStore
    from plugins.bot_unified_runtime.control_plane.services import FeatureControlService
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_message,
    )
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        build_product_descriptors,
        capability_feature_bindings,
    )
    from plugins.bot_unified_runtime.domains.ops.features.feature_gate import (
        ProductFeatureGate,
    )
    from plugins.bot_unified_runtime.runtime.capability_registry import (
        CONTROLLED_INTERNAL_CAPABILITIES,
    )

    assert "bot.campus_forward" in CONTROLLED_INTERNAL_CAPABILITIES
    bindings = capability_feature_bindings()
    assert bindings.get("bot.campus_forward") == "bot.plugin.campus_forward"
    gate = ProductFeatureGate(
        FeatureControlService(
            FeatureStateStore(
                tmp_path / "features.json", descriptors=build_product_descriptors()
            )
        )
    )
    access = gate(build_campus_forward_message(_source(), _payload()), "bot.campus_forward")
    assert access.allowed, f"注册后网关必须放行，现 reason={access.reason}"


def test_campus_capability_id_literals_all_registered() -> None:
    """campus 面上的 capability_id 字面量零漏登（根文件一致性门的 campus 定向版）。"""
    from plugins.bot_unified_runtime.domains.ops.features.feature_catalog import (
        capability_feature_bindings,
    )

    targets = [_PLUGIN_ROOT / "__init__.py", _DOMAIN_CAMPUS]
    found: set[str] = set()
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "capability_id"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                found.add(node.value.value)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "capability_id"
                        and isinstance(node.value, ast.Constant)
                    ):
                        found.add(node.value.value)
    campus_ids = {value for value in found if "campus" in value}
    assert campus_ids == {"bot.campus_forward"}, f"campus 能力 id 漂移：{campus_ids}"
    assert campus_ids <= set(capability_feature_bindings())


def _campus_matcher_coordinate() -> int:
    source = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8").splitlines()
    hits = [
        index + 1
        for index, line in enumerate(source)
        if "campus_record_matcher = on_message(" in line
    ]
    assert len(hits) == 1, f"campus matcher 定义应恰一处，现={hits}"
    return hits[0]


def test_outbound_registry_campus_coordinate_is_live() -> None:
    """出站登记表 campus 一条改为收编后真实坐标（同波审计：整册 0/50 命中）。"""
    from plugins.bot_unified_runtime.domains.core.decision.outbound import (
        build_default_takeover_registry,
    )

    reg = build_default_takeover_registry()
    entries = [e for e in reg.matchers if e.name == "campus_record_matcher"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.location == f"__init__.py:{_campus_matcher_coordinate()}", (
        f"登记坐标必须与真行号一致，现={entry.location}"
    )
    assert entry.matcher_type == "on_message"
    assert entry.priority == 8, "priority=8/block=False 是 campus matcher 的真实形态"
    assert "U17-CAMPUS-WIRE" in entry.note and "中央管线" in entry.note


# ---------- ⑤ U17-FIX：泄拦面打码前置 + BLOCK 可观测（关 I1/I2） ----------


def test_forward_body_redacts_secret_shapes_before_review(tmp_path: Path) -> None:
    """I1 前半：源群文本含 BOT_XXX=/盘符路径/裸 sk- 形态 → 出站正文进 review
    门之前已打码（打码标记存在、原文不存在）。

    这三类形态 reviewer 本就不拦（改前原文裸奔直达主人）；打码后主人收打码版
    而非原文，信息流与安全兼得。键值词干（token=/cookie= 等）打码后仍命中
    review 词面被拦（设计如此），该路径的可观测由下一例覆盖。
    """
    from plugins.bot_unified_runtime.domains.render.reviewer import (
        _unsafe_output_reasons,
    )

    secret_text = (
        "配置如下：BOT_WEATHER_KEY=abc123456\n"
        r"日志在 C:\Users\lan\AppData\Roaming\bot\config.yaml" + "\n"
        "备用 key：sk-abcdefghijklmnop1234"
    )
    payload = _forward(_service(tmp_path), "111", secret_text, mid="m-secret")
    assert payload is not None
    body = payload.body
    # 前缀与正文骨架仍在（只打码敏感形态，不是丢弃消息）。
    assert body.startswith(f"{_CAMPUS_FORWARD_INTRO}群111 张三：")
    assert "BOT_WEATHER_KEY=<已隐藏>" in body
    assert "abc123456" not in body
    assert "<本机路径已隐藏>" in body
    assert "Users" not in body and "AppData" not in body
    assert "sk-abcdefghijklmnop1234" not in body
    assert "sk-<已隐藏>" in body
    # 打码产物不再命中 review 泄漏面：这三类形态不再 BLOCK，主人收得到。
    assert _unsafe_output_reasons(body) == []


def test_handler_review_block_emits_observable_alert(tmp_path: Path) -> None:
    """I1 后半 + I2：review/门禁 BLOCK 不得完全静默——既有运行时告警通道
    恰触发一次可观测告警（capability/拦截类别/目标会话，绝不含源文本原文）。

    BLOCK 语义=store 已记账、同 id 重放不再进管线（该条永久丢失）；主人侧
    至少「有一条校园消息因安全门未送达」可事后从告警与日志知晓。
    """
    import logging

    from plugins.bot_unified_runtime.contracts import (
        OperationalIssue,
        ReceiptState,
        RiskLevel,
    )
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
        AdminAlertSuppression,
        AdminTarget,
        notify_operational_issue,
    )

    secret_text = "公告 token=abcd1234efgh 明早交表"

    class _BlockedPipeline:
        """回执替身：review BLOCK 态（transport=reviewer，与真管线同形）。"""

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def handle_async(self, message, capability, capability_id=""):
            self.calls.append({"message": message, "capability_id": capability_id})

            async def _done():
                return SimpleNamespace(
                    state=ReceiptState.BLOCKED,
                    transport="reviewer",
                    public_message="输出未通过安全或隐私检查。",
                )

            return _done()

    deliveries: list = []

    async def _fake_delivery(target, bot, request):
        deliveries.append(request)
        return SimpleNamespace(state=ReceiptState.SENT)

    blocked_pipeline = _BlockedPipeline()
    env = _campus_handler_env(
        tmp_path,
        pipeline=blocked_pipeline,
        logging=logging,
        OperationalIssue=OperationalIssue,
        RiskLevel=RiskLevel,
        notify_operational_issue=notify_operational_issue,
        _operational_alert_targets=lambda: [
            AdminTarget(adapter="onebot", bot_id="push-bot", target_id=_OWNER_QQ)
        ],
        _all_online_bots=lambda: {"push-bot": SimpleNamespace()},
        _deliver_admin_alert=_fake_delivery,
        operational_alert_suppression=AdminAlertSuppression(),
    )
    handler = _extract_handler("_handle_campus_record", **env)
    bot = SimpleNamespace(self_id=_SCHOOL_QQ)
    asyncio.run(handler(bot, _GroupEvent(text=secret_text, message_id="blk-1")))

    assert len(blocked_pipeline.calls) == 1, "前提：消息确实进了中央管线"
    # 打码前置对真管线入口同样生效：进 review 的正文已无敏感原文。
    entered = blocked_pipeline.calls[0]["message"]
    assert "abcd1234efgh" not in entered.plain_text
    assert "token=<已隐藏>" in entered.plain_text
    # 永久丢失前提留证：store 已记账（同 id 重放不再进管线）。
    today = datetime.now().astimezone().date().isoformat()
    assert env["campus_service"].store.list_day(today), "store 先于管线记账"
    # BLOCK 不再静默：恰一次告警投递，结构化字段齐、源文本零携带。
    assert len(deliveries) == 1, "review BLOCK 必须触发一次可观测告警投递"
    alert_text = deliveries[0].content.text_fallback
    assert "capability=bot.campus_forward" in alert_text
    assert "blocked_reviewer" in alert_text
    assert f"private:{_OWNER_QQ}" in alert_text
    assert "abcd1234efgh" not in alert_text, "告警绝不携带源文本原文"


# ---------- ⑥ CAMPUS-TESTHARD：U17-REVIEW-3 弱点清单补钉（M2/M3/M4 + I1 边界） ----------
# 依据 docs/design/v21r5-U17REVIEW-log.md 攻击面⑦逐例弱点 + 移交清单 #5。
# 每条强化前均以测试空间变异探针证明「弱点真实存在」，探针实录见
# docs/design/v21r5-CAMPUSTH-log.md；既有 31 例断言零触碰。


def test_outbound_registry_campus_entry_capability_hint_pinned() -> None:
    """registry 面：campus 条目的 capability 提示（route_kind_hint）补钉。

    变异探针实证：route_kind_hint 誊录成他功能名（"chat"）时，既有断言
    （location/matcher_type/priority/note）全数仍绿——capability 语义零哨兵。
    note/priority 断言既有坐标棘轮例已锁（U17 批），本例只补真缺口。
    """
    from plugins.bot_unified_runtime.domains.core.decision.outbound import (
        build_default_takeover_registry,
    )

    reg = build_default_takeover_registry()
    entry = next(e for e in reg.matchers if e.name == "campus_record_matcher")
    assert entry.route_kind_hint == "campus"


def test_handler_dispatch_entry_pinned_to_handle_async(tmp_path: Path) -> None:
    """M3：dispatch entry 旧断言 ``in {"handle", "handle_async"}`` 对「退回同步
    handle」的变异仍绿（探针实证 mutant='handle': old=True）。补钉死唯一真实
    形态 handle_async——生产 handler 恒 ``await pipeline.handle_async(...)``。
    """
    env = _run_campus_handler(tmp_path, _GroupEvent())

    calls = env["pipeline"].calls
    assert len(calls) == 1, f"应恰一次经中央管线，现={len(calls)}"
    assert calls[0]["entry"] == "handle_async", (
        f"campus 分发必须钉死 handle_async，现={calls[0]['entry']}"
    )


def test_forward_message_pins_platform_fields_and_verbatim_plain_text(
    tmp_path: Path,
) -> None:
    """M2：builder 产物 plain_text/platform/adapter/raw_segments 补钉。

    变异探针实证：builder 若把 plain_text 写成未截断/未打码原文（变异体
    plain_text=payload.text），31 例无一能抓（既有断言对该字段零引用）。
    补钉后：plain_text 恒等于 payload.body（截断+打码后的出站正文——审计/
    幂等 fallback 面与用户可见形态同源），raw_segments 与 body 逐字节同源，
    platform/adapter 钉收编实现字面。长文（截断面）与含密形态（打码面）
    双变异样本。
    """
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_message,
    )

    service = _service(tmp_path)
    long_payload = _forward(service, "111", "长" * 3000, mid="th-long")
    assert long_payload is not None
    message = build_campus_forward_message(_source(), long_payload)
    assert message.platform == "nonebot"
    assert message.adapter == "onebot.v11"
    assert message.plain_text == long_payload.body
    assert message.plain_text != long_payload.text, "未截断原文不得进 plain_text"
    assert message.raw_segments == [
        {"type": "text", "data": {"text": long_payload.body}}
    ]

    secret_payload = _forward(
        service, "111", "公告 token=abcd1234efgh 明早交表", mid="th-sec"
    )
    assert secret_payload is not None
    secret_message = build_campus_forward_message(_source(), secret_payload)
    assert secret_message.plain_text == secret_payload.body
    assert "abcd1234efgh" not in secret_message.plain_text, (
        "未打码原文不得经 plain_text 外泄（审计/幂等面）"
    )


def test_forward_request_carries_adapter_and_bot_semantics(tmp_path: Path) -> None:
    """M2（SendRequest 平台/适配器语义）：e2e 例未钉 request.adapter/bot_id。

    SendRequest 的 adapter/bot_id 是发送队列在无原始 Event 时选适配器与 Bot
    的唯一依据（contracts/runtime.py 字段注释）；campus 消息的 onebot.v11 /
    push_bot_id 必须经中央 _complete 带出，否则主人私聊投递选错通道。
    """
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )

    pipeline, queue = _central_pipeline(tmp_path)
    source = _source()
    payload = _payload(message_id="th-adapter")
    receipt = pipeline.handle(
        build_campus_forward_message(source, payload),
        build_campus_forward_capability(source, payload),
        capability_id="bot.campus_forward",
    )
    assert receipt.state is ReceiptState.SENT
    assert len(queue.sent_requests) == 1
    request = queue.sent_requests[0]
    assert request.adapter == "onebot.v11"
    assert request.bot_id == source.push_bot_id


def test_real_pipeline_blocks_stem_shaped_body_with_zero_enqueue(
    tmp_path: Path,
) -> None:
    """移交 #5①（I1 后半·真管线版）：键值词干（token=）打码后仍命中 review
    词面 → 真 reviewer BLOCK + 零入队。

    既有 BLOCK 告警例用的是回执替身（假管线不跑真 reviewer）；本例用真管线
    锁「键值词干打码后仍被拦（设计如此）」的设计声称——否则该声称零测试背书。
    """
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )

    payload = _forward(
        _service(tmp_path), "111", "公告 token=abcd1234efgh 明早交表", mid="th-block"
    )
    assert payload is not None
    pipeline, queue = _central_pipeline(tmp_path)
    receipt = pipeline.handle(
        build_campus_forward_message(_source(), payload),
        build_campus_forward_capability(_source(), payload),
        capability_id="bot.campus_forward",
    )
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "reviewer"
    assert queue.sent_requests == [], "命中 review 词面的出站请求必须零入队"


def test_runtime_pause_blocks_forward_and_message_is_unrecoverable(
    tmp_path: Path,
) -> None:
    """移交 #5②（I2 永久丢失语义）：runtime 暂停 → BLOCKED（transport=policy）
    + 零入队；且 store 先行记账 + 同 message_id 重放 record()=None——暂停窗口
    内的校园消息**不可恢复重放**。store 幂等既有例锁的是转发面，本例把
    「暂停丢的这条捡不回来」钉死。"""
    from plugins.bot_unified_runtime.contracts import ReceiptState
    from plugins.bot_unified_runtime.domains.assistant.campus.campus import (
        build_campus_forward_capability,
        build_campus_forward_message,
    )

    service = _service(tmp_path)
    payload = _forward(service, "111", "暂停窗口里的教务通知", mid="th-pause")
    assert payload is not None
    pipeline, queue = _central_pipeline(tmp_path)
    pipeline.runtime_enabled = False
    receipt = pipeline.handle(
        build_campus_forward_message(_source(), payload),
        build_campus_forward_capability(_source(), payload),
        capability_id="bot.campus_forward",
    )
    assert receipt.state is ReceiptState.BLOCKED
    assert receipt.transport == "policy"
    assert receipt.public_message == "统一运行时已暂停。"
    assert queue.sent_requests == []
    # 永久丢失：store 已记账，同 id 重放不再产出载荷（永不再进管线）。
    assert _forward(service, "111", "暂停窗口里的教务通知", mid="th-pause") is None


class _PruneBrokenStore(CampusStore):
    """prune 必炸替身：签名与 CampusStore.prune 全同（keyword-only）。"""

    def prune(self, *, keep_days: int = 90, now: datetime | None = None) -> int:
        raise RuntimeError("prune exploded")


def test_record_survives_prune_failure(tmp_path: Path) -> None:
    """M4①（域服务面）：裁剪失败只记 debug，不影响录制与转发（_maybe_prune
    的 except Exception）。变异探针实证：吞异常移除（测试空间变异体）时
    record() 当场 RuntimeError——本例锁定「裁剪炸不丢录制转发」。"""

    service = CampusForwardService(
        store=_PruneBrokenStore(str(tmp_path / "prune-boom.sqlite3")),
        source=_source(),
    )
    payload = _forward(service, "111", "裁剪会炸但录制不能丢", mid="th-prune")
    assert payload is not None, "裁剪失败不得吞掉录制与转发"
    assert len(service.store.list_day(_TODAY)) == 1


class _BrokenPlaintextEvent(_GroupEvent):
    """get_plaintext 必炸替身：适配器实现差异的极端形态。"""

    def get_plaintext(self) -> str:
        raise RuntimeError("adapter quirk")


def test_handler_survives_get_plaintext_failure(tmp_path: Path) -> None:
    """M4②（handler 面）：适配器 get_plaintext 炸 → 兜底空文本，监听主链路
    不炸、零落库零转发（handler 内 except Exception 分支；逃逸面=asyncio.run
    外抛，变异探针实证未处理异常必逃逸）。"""

    env = _run_campus_handler(tmp_path, _BrokenPlaintextEvent())
    assert env["pipeline"].calls == [], "空文本不得进管线"
    today = datetime.now().astimezone().date().isoformat()
    assert env["campus_service"].store.list_day(today) == [], "空文本零落库"


def test_handler_survives_pipeline_failure_and_keeps_recording(
    tmp_path: Path,
) -> None:
    """M4③（handler 面）：中央管线炸（handle_async raise）→ 吞异常记日志，
    监听主链路不炸；录制已先行完成（录库仍成功——吞异常不丢主流程）。"""
    import logging

    class _ExplodingPipeline:
        def __init__(self) -> None:
            self.calls: list = []

        async def handle_async(self, message, capability, capability_id=""):
            self.calls.append(capability_id)
            raise RuntimeError("pipeline exploded")

    exploding = _ExplodingPipeline()
    # except 分支引用模块级 logging（生产为全局名，提取命名空间须显式注入）。
    env = _run_campus_handler(tmp_path, _GroupEvent(), pipeline=exploding, logging=logging)
    assert exploding.calls == ["bot.campus_forward"], "前提：消息确实进了管线入口"
    today = datetime.now().astimezone().date().isoformat()
    assert env["campus_service"].store.list_day(today), "管线失败不得抹掉先行录制"


def test_handler_survives_alert_delivery_failure(tmp_path: Path) -> None:
    """M4④（handler 面）：BLOCK 告警投递炸（notify 链任一环）→ best-effort
    吞异常，监听主链路不反噬（_notify_campus_block 内层 except Exception）。"""
    import logging

    from plugins.bot_unified_runtime.contracts import (
        OperationalIssue,
        ReceiptState,
        RiskLevel,
    )
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
        AdminAlertSuppression,
        AdminTarget,
    )

    class _BlockedPipeline:
        """回执替身：恒 BLOCKED（与既有告警例同形）。"""

        def handle_async(self, message, capability, capability_id=""):
            async def _done():
                return SimpleNamespace(
                    state=ReceiptState.BLOCKED,
                    transport="reviewer",
                    public_message="输出未通过安全或隐私检查。",
                )

            return _done()

    async def _exploding_notify(*args, **kwargs):
        raise RuntimeError("alert channel down")

    env = _campus_handler_env(
        tmp_path,
        pipeline=_BlockedPipeline(),
        logging=logging,
        OperationalIssue=OperationalIssue,
        RiskLevel=RiskLevel,
        notify_operational_issue=_exploding_notify,
        _operational_alert_targets=lambda: [
            AdminTarget(adapter="onebot", bot_id="push-bot", target_id=_OWNER_QQ)
        ],
        _all_online_bots=lambda: {"push-bot": SimpleNamespace()},
        operational_alert_suppression=AdminAlertSuppression(),
    )
    handler = _extract_handler("_handle_campus_record", **env)
    bot = SimpleNamespace(self_id=_SCHOOL_QQ)
    # 告警链在 BLOCK 分支内必炸：handler 仍正常返回（asyncio.run 未外抛即断言面）。
    asyncio.run(handler(bot, _GroupEvent(text="公告 token=abcd1234efgh", message_id="th-alert")))
    today = datetime.now().astimezone().date().isoformat()
    assert env["campus_service"].store.list_day(today), "告警失败不得影响先行录制"


def test_forward_body_identity_for_secret_word_shapes_without_key_form(
    tmp_path: Path,
) -> None:
    """弱点4（I1 打码边界）：敏感词「字样」≠密钥「形态」——纯文本含中文「密码」、
    键干邻字母（monkey=）、键干无分隔符（password 词）时打码器必须**恒等**
    （verbatim 契约延伸面），且产物过 review 干净（主人原样收到）。

    变异探针（实跑）实证：三样本 identity=True + reviewer_clean=[]；对照组真
    键值形态 password=abcd1234efgh → 'password=<已隐藏>'（identity=False）——
    证明样本族非恒真：去掉词干边界（(?<![A-Za-z])）或分隔符要求的回归都会被
    本例抓住。无哨兵形态恒等的主锁在
    ``test_forward_text_matches_legacy_bypass_verbatim``（oracle 三方互证），
    本例只补边界样本，不重写既有契约。
    """
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        redact_local_secrets,
    )
    from plugins.bot_unified_runtime.domains.render.reviewer import (
        _unsafe_output_reasons,
    )

    boundary_samples = [
        "教室门禁密码周五统一更换",  # 中文「密码」无任何 ASCII 哨兵
        "monkey=12345678",  # 键干 key 左侧邻字母 → 词面边界不得误伤（值满 8 字有牙）
        "password 政策下周更新",  # 键干出现但无键值分隔符
    ]
    for index, sample in enumerate(boundary_samples):
        payload = _forward(
            _service(tmp_path / f"boundary-{index}"),
            "111",
            sample,
            mid=f"th-boundary-{index}",
        )
        assert payload is not None
        assert payload.body == _legacy_forward_text("111", "张三", sample), (
            f"非密钥形态必须打码恒等：{sample!r} → {payload.body!r}"
        )
        assert _unsafe_output_reasons(payload.body) == [], (
            f"边界样本不得被 review 误拦：{sample!r}"
        )
    # 对照组（有牙证明）：真键值形态必须被打码——本例与「永不打码」无关。
    assert redact_local_secrets("password=abcd1234efgh") == "password=<已隐藏>"
