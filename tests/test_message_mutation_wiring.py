"""席位 S34 锁：消息编辑/撤回从「坐标册」变成有人调用的能力。

三把锁 + 一条注毒：
① 载荷构造正确 —— ``chat_id``/``message_id`` 在场才发（QQ 侧 delete_msg 不吃
   chat_id，但会话绑定必填；TG 两枚方法都吃 chat_id）。
② 缺 id 时**诚实失败** —— 返回 ``invalid_target``/原因码，且平台一次都没被调用
   （不静默吞、不「先少个参数发发看」）。
③ 越权请求被门拦 —— 陌生人、跨会话、非 bot 自己发的消息、超时限，全部 refusal。
④ 注毒＝把 ``execute_mutation`` 源码里那行门摘掉 ⇒ 必红（AST 锁，不靠人肉记忆）。

另有一枚**活性锁**：``install_message_mutation`` 必须真被根装配文件调用一次
（否则本能力又退回「零 live 调用点」那笔旧账）。

复跑：
.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s34-pyc \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_message_mutation_wiring.py -p no:cacheprovider --basetemp=$TEMP/s34-bt -q
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.transport import message_mutation as mm
from plugins.bot_unified_runtime.domains.transport.message_mutation import (
    MutationActor,
    MutationRequest,
    MutationTarget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPO_ROOT / "plugins/bot_unified_runtime/domains/transport/message_mutation.py"
)
ROOT_INIT_PATH = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"

PLATFORM = "qq"


class DuckConfig:
    """鸭子配置：镜像**已在册**的 Config 形状（两枚字段都在，时限取在册缺省）。

    读点自席 S34b 起改属性直读（三面齐之后 `getattr(..., 缺省)` 就是第二套口径），
    所以鸭子件必须把两枚字段都摆齐，否则测的是"鸭子少长了一格"而不是判据。
    """

    def __init__(self, *, enabled: bool, admins: str = "", window: int | None = None) -> None:
        self.bot_message_mutation_enabled = enabled
        self.bot_admin_user_ids = admins
        self.bot_message_mutation_window_seconds = (
            mm.DEFAULT_MUTATION_WINDOW_SECONDS if window is None else window
        )


class FakeLedger:
    """替身投递账（真身＝``sender/receipts.py`` 的 ``list_receipts()``）。"""

    def __init__(self, rows: list[tuple[str, datetime | str | None]]) -> None:
        self._rows = rows

    def list_receipts(self) -> list[object]:
        out: list[object] = []
        for message_id, created_at in self._rows:
            out.append(
                type(
                    "Receipt",
                    (),
                    {"provider_message_id": message_id, "created_at": created_at},
                )()
            )
        return out


class RecordingBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_api(self, method: str, **params: object) -> dict[str, object]:
        self.calls.append((method, dict(params)))
        return {"message_id": 1}


def _request(
    operation: str = "delete",
    *,
    platform: str = PLATFORM,
    actor_platform: str | None = None,
    session_type: str = "group",
    chat_id: str = "123",
    message_id: str = "987654",
    text: str = "",
    sender_id: str = "42",
    actor_chat: str = "123",
    is_admin: bool = True,
    own_private: bool = False,
    sent_at: datetime | None = None,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        actor=MutationActor(
            platform=actor_platform or platform,
            sender_id=sender_id,
            chat_id=actor_chat,
            is_admin=is_admin,
            own_private_chat=own_private,
        ),
        target=MutationTarget(
            platform=platform,
            session_type=session_type,
            chat_id=chat_id,
            message_id=message_id,
            sent_at=sent_at,
        ),
        text=text,
    )


def _ledger(message_id: str = "987654", created_at: object = None) -> FakeLedger:
    return FakeLedger([(message_id, created_at)])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 载荷构造
# ---------------------------------------------------------------------------


def test_qq_delete_payload_carries_numeric_message_id_only() -> None:
    params = mm.build_mutation_payload(_request("delete"))
    assert params == {"message_id": 987654}


def test_telegram_payload_requires_and_carries_chat_id() -> None:
    params = mm.build_mutation_payload(
        _request("delete", platform="telegram", chat_id="-100123", session_type="channel")
    )
    assert params == {"message_id": 987654, "chat_id": "-100123"}


def test_edit_payload_keeps_text_and_rejects_oversize() -> None:
    params = mm.build_mutation_payload(_request("edit", text="改一下下"))
    assert params["text"] == "改一下下"
    with pytest.raises(mm.MutationRefused) as exc:
        mm.build_mutation_payload(_request("edit", text="长" * (mm.EDIT_TEXT_MAX_CHARS + 1)))
    assert exc.value.reason == "edit_text_too_long"


def test_registry_resolves_platform_method_names_for_both_operations() -> None:
    """方法名来自 TransportRegistry 固定映射（禁拼接）：QQ delete_msg / TG 两枚。"""
    executor = mm.OutboundSideEffectExecutor()
    for platform, session_type, operation, expected in (
        ("qq", "group", "delete", "delete_msg"),
        ("qq", "group", "edit", "edit_msg"),
        ("telegram", "private", "delete", "deleteMessage"),
        ("telegram", "private", "edit", "editMessageText"),
    ):
        request = _request(
            operation,
            platform=platform,
            session_type=session_type,
            chat_id="777",
            actor_chat="777",
            text=("改一下句" if operation == "edit" else ""),
        )
        intent = mm.build_mutation_intent(request, mm.build_mutation_payload(request))
        assert executor._resolve_method(intent) == expected


# ---------------------------------------------------------------------------
# ② 缺 id 诚实失败（不静默吞）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"message_id": ""}, "missing_message_id"),
        ({"message_id": "  "}, "missing_message_id"),
        ({"message_id": "abc123"}, "non_numeric_message_id"),
        ({"chat_id": ""}, "missing_chat_id"),
    ],
)
def test_missing_ids_raise_instead_of_silently_sending(
    kwargs: dict[str, str], reason: str
) -> None:
    with pytest.raises(mm.MutationRefused) as exc:
        mm.build_mutation_payload(_request(**kwargs))
    assert exc.value.reason == reason


def test_execute_with_missing_message_id_reports_honestly_and_calls_nothing() -> None:
    bot = RecordingBot()
    request = _request("delete", message_id="")
    outcome = asyncio.run(
        mm.execute_mutation(
            request,
            config=DuckConfig(enabled=True),
            bot=bot,
            ledger=_ledger(""),
        )
    )
    assert outcome.ok is False
    assert outcome.status == "invalid_target"
    assert outcome.reason == "missing_message_id"
    assert bot.calls == [], "缺 id 却仍打了平台 API＝静默吞"


def test_unregistered_platform_is_honest_not_silent() -> None:
    """邮件/控制台无编辑撤回面 ⇒ 执行器显式回 unregistered_*，绝不编个方法名。"""
    request = _request("delete", platform="telegram", chat_id="7", actor_chat="7")
    intent = mm.build_mutation_intent(request, mm.build_mutation_payload(request))
    intent.target = type(intent.target)(
        platform="mail",
        session_type="email",
        target_id="x@example.com",
        adapter="smtp",
    )
    outcome = asyncio.run(
        mm.execute_mutation(
            request,
            config=DuckConfig(enabled=True),
            bot=RecordingBot(),
            ledger=_ledger(),
            executor=_Prebuilt(intent),
        )
    )
    assert outcome.ok is False
    assert outcome.status in {"unregistered_transport", "unregistered_platform"}


class _Prebuilt:
    def __init__(self, intent: object) -> None:
        self.intent = intent

    async def execute(self, intent: object, *, bot: object = None) -> object:
        from plugins.bot_unified_runtime.control_plane.dispatcher import (
            OutboundSideEffectExecutor,
        )

        real = OutboundSideEffectExecutor()
        try:
            method = real._resolve_method(self.intent)
        except Exception as exc:  # noqa: BLE001
            return type("R", (), {"delivered": False, "status": "unregistered_transport", "reason": str(exc), "method": ""})()
        return type("R", (), {"delivered": True, "status": "delivered", "reason": "", "method": method})()


# ---------------------------------------------------------------------------
# ③ 门禁：越权请求被拦
# ---------------------------------------------------------------------------

ENABLED = DuckConfig(enabled=True)


def test_gate_closed_by_default_even_for_super_admin() -> None:
    """缺省关：开关不拨（本席不许自行开）⇒ 管理员也被拒且零出站。"""
    bot = RecordingBot()
    outcome = asyncio.run(
        mm.execute_mutation(
            _request(), config=DuckConfig(enabled=False), bot=bot, ledger=_ledger()
        )
    )
    assert (outcome.ok, outcome.status, outcome.reason) == (False, "refused", "feature_disabled")
    assert bot.calls == []


def test_missing_config_field_is_loud_not_silently_closed() -> None:
    """三面齐之后：字段被摘掉 ⇒ 读点**响亮地炸**，不再 `getattr` 咽成"门关"。

    旧口径（本枚前身）判的是"缺席⇒读到 False⇒门关＝幽灵字段零新增"，那是
    getattr 容缺省时代的形状；键已在册之后再留那种断言＝把"有人删了在册字段"
    这件事故降级成静默行为变化（本仓点名的 C-09 死开关反方向）。
    """

    class Bare:
        pass

    with pytest.raises(AttributeError):
        mm.mutation_feature_enabled(Bare())
    with pytest.raises(AttributeError):
        mm.mutation_window_seconds(Bare())


def test_window_shape_guard_only_rejects_non_positive() -> None:
    """形状判据只剩"必须为正"：非正回退在册缺省，正数原样透出。"""
    assert mm.mutation_window_seconds(DuckConfig(enabled=True, window=0)) == (
        mm.DEFAULT_MUTATION_WINDOW_SECONDS
    )
    assert mm.mutation_window_seconds(DuckConfig(enabled=True, window=-5)) == (
        mm.DEFAULT_MUTATION_WINDOW_SECONDS
    )
    assert mm.mutation_window_seconds(DuckConfig(enabled=True, window=45)) == 45


@pytest.mark.parametrize(
    ("mutation_request", "reason"),
    [
        (_request(is_admin=False, own_private=False), "not_authorized"),
        (_request(actor_chat="999"), "out_of_session"),
        (_request(chat_id=""), "out_of_session"),
        (_request(actor_platform="telegram"), "cross_platform_target"),
        (_request(operation="rename"), "unknown_operation"),
    ],
)
def test_privilege_escalation_is_denied(mutation_request: MutationRequest, reason: str) -> None:
    assert mm.authorize_mutation(ENABLED, mutation_request, ledger=_ledger()) == reason


def test_stranger_group_member_cannot_recall_bot_message() -> None:
    bot = RecordingBot()
    outcome = asyncio.run(
        mm.execute_mutation(
            _request(is_admin=False), config=ENABLED, bot=bot, ledger=_ledger()
        )
    )
    assert (outcome.status, outcome.reason) == ("refused", "not_authorized")
    assert bot.calls == []


def test_only_messages_the_bot_actually_sent_are_mutable() -> None:
    """回执账里没有这个 message_id ⇒ 不是 bot 发的 ⇒ 拒（别人的消息碰不到）。"""
    assert (
        mm.authorize_mutation(ENABLED, _request(), ledger=_ledger("111"))
        == "not_bot_message"
    )
    assert mm.authorize_mutation(ENABLED, _request(), ledger=None) == "no_send_ledger"


def test_window_expiry_denied_and_private_self_allowed() -> None:
    old = datetime.now(timezone.utc) - timedelta(seconds=3600)
    assert (
        mm.authorize_mutation(
            ENABLED, _request(message_id="987654"), ledger=_ledger("987654", old)
        )
        == "mutation_window_expired"
    )
    self_chat = _request(
        "delete",
        session_type="private",
        chat_id="42",
        actor_chat="42",
        is_admin=False,
        own_private=True,
    )
    assert mm.authorize_mutation(ENABLED, self_chat, ledger=_ledger()) == ""


def test_admin_roster_leg_still_governs_when_flag_open() -> None:
    """门开但名单不含此人 ⇒ 仍拒（不因为开了面就人人可用）。"""
    gated = DuckConfig(enabled=True, admins="")
    request = _request(is_admin=False, own_private=False)
    assert mm.authorize_mutation(gated, request, ledger=_ledger()) == "not_authorized"


def test_happy_path_delivers_with_registry_method() -> None:
    bot = RecordingBot()
    outcome = asyncio.run(
        mm.execute_mutation(_request(), config=ENABLED, bot=bot, ledger=_ledger())
    )
    assert outcome.ok is True
    assert outcome.method == "delete_msg"
    assert bot.calls == [("delete_msg", {"message_id": 987654})]


def test_edit_happy_path_sends_text() -> None:
    bot = RecordingBot()
    outcome = asyncio.run(
        mm.execute_mutation(
            _request("edit", text="刚才那句发错了"),
            config=ENABLED,
            bot=bot,
            ledger=_ledger(),
        )
    )
    assert outcome.ok is True
    assert outcome.method == "edit_msg"
    assert bot.calls[0][1] == {"message_id": 987654, "text": "刚才那句发错了"}


# ---------------------------------------------------------------------------
# ④ 注毒：摘门必红 + 活性锁
# ---------------------------------------------------------------------------


def _execute_mutation_source() -> str:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "execute_mutation":
            return ast.unparse(node)
    raise AssertionError("execute_mutation 定义消失＝本锁素材丢失")


def test_gate_is_called_inside_execute_mutation() -> None:
    assert "authorize_mutation(" in _execute_mutation_source(), "execute_mutation 里不再叫门＝能力裸奔"


def test_poison_removing_the_gate_call_is_caught(tmp_path: Path) -> None:
    """注毒：把真身里那行门换成「永远放行」⇒ AST 锁红 + 陌生人请求直达平台调用。"""
    source = MODULE_PATH.read_text(encoding="utf-8")
    door_call = "authorize_mutation(config, request, ledger=ledger, now=now)"
    door_line = "    verdict = " + door_call + chr(10)
    assert source.count(door_line) == 1, "注毒目标行盘上不唯一"
    poisoned = source.replace(door_line, '    verdict = ""' + chr(10))
    assert poisoned != source, "注毒未落文本＝空跑"
    target_path = tmp_path / "message_mutation_poisoned.py"
    target_path.write_text(poisoned, encoding="utf-8")
    body = ""
    for node in ast.parse(poisoned).body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "execute_mutation":
            body = ast.unparse(node)
    assert door_call not in body, "注毒源码里门仍在＝注毒没打到东西"
    assert "authorize_mutation(" not in body
    namespace: dict[str, object] = {}
    exec(compile(poisoned, str(target_path), "exec"), namespace)  # noqa: S102
    bot = RecordingBot()
    runner = namespace["execute_mutation"]
    outcome = asyncio.run(  # type: ignore[misc]
        runner(_request(is_admin=False), config=ENABLED, bot=bot, ledger=_ledger())
    )
    assert outcome.ok is True and bot.calls, "摘门后仍拦得住＝本锁在补空气"
    assert bot.calls[0][0] == "delete_msg"


def test_root_assembly_actually_installs_the_capability() -> None:
    """活性锁：根装配文件必须真调用 install_message_mutation（否则又退回零调用旧账）。"""
    source = ROOT_INIT_PATH.read_text(encoding="utf-8")
    assert source.count("install_message_mutation(") >= 1, "根里没人调用＝仍是零 live 调用点"
    tree = ast.parse(source)
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "install_message_mutation"
    ]
    assert hits, "AST 里找不到 install_message_mutation 调用点"
