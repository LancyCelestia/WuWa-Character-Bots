"""A2 修复席配套锁（2026-09-27）：群提醒 per-sender 子闸 + 列表/取消隐私面。

对应审计 ``.superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-SCHEDULE.md``
A2【会错】：①群会话 ≤20 待办配额无 per-sender 子闸（单成员连发不同正文
可占满整组预算，24h 正文去重键含正文、逐条换词即绕）；②「提醒列表」向
全群回显他人提醒原文与可取消 id 前缀，取消面无归属校验（凭列表抄前缀即可
撤他人提醒）。

本锁五面钉死：
- per-sender 霸占被拒（能力层第 6 条踩子闸，回执说明满的是**你自己**的额度）；
- 群列表不泄他人原文/id 前缀（用群内他人提醒造样本）；
- 他人 id 取消被拒（他人提醒仍挂账、回执不带 cancelled 口径）；
- 本人取消/列表照常（回归面）；
- 管理员/群主例外沿用既有角色面 ``sender_platform_role``（可撤他人，但
  回执不复述他人原文；列表面无例外，管理员也只列本人）。
另附 store 层两闸判据单元测试（session_full 优先于 sender_full；不传子闸
参数=行为不变）与注毒锚点（把能力层归属过滤/子闸入参摘掉，本文件必红）。

    BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$TEMP/gr-pyc" \
    PYTHONIOENCODING=utf-8 ../ChatBot_Runtime/venv/Scripts/python.exe \
    -m pytest tests/test_sched_a2_quota_privacy.py -p no:cacheprovider \
    --basetemp="$TEMP/sched-a2-$$" -q
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime.domains.schedule.capabilities.reminder as reminder_cap_mod
import plugins.bot_unified_runtime.domains.schedule.store.reminders as reminders_store_mod
from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
from plugins.bot_unified_runtime.domains.schedule.capabilities.reminder import (
    build_reminder_capability,
    clear_checkoff_pending_for_tests,
)
from plugins.bot_unified_runtime.domains.schedule.store.reminders import (
    MAX_PENDING_PER_SENDER,
    ReminderStore,
)

_TZ = timezone(timedelta(hours=8))

# 他人提醒的隐私样本（吃药/复诊类）：这些原文一旦出现在群回复里即为泄露。
_PRIVATE_TEXT_U2 = "下午3点去社区医院复诊取报告"
_PRIVATE_TEXT_U3 = "晚上10点吃降压药"


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    """store 缓存、24h 去重表、勾选追问状态都是进程级单例：逐例清零防泄漏。"""
    monkeypatch.setattr(reminders_store_mod, "_STORES", {})
    monkeypatch.setattr(reminder_cap_mod, "_RECENT_BODIES", {})
    clear_checkoff_pending_for_tests()
    yield
    reminder_cap_mod._RECENT_BODIES.clear()
    clear_checkoff_pending_for_tests()


def _config(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_reminder_db_path=str(tmp_path / "r.sqlite3"),
        bot_notes_enabled=False,
    )


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    session_id: str = "group:1",
    session_type: SessionType = SessionType.GROUP,
    platform_role: str | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq", adapter="nonebot", bot_id="bot-1",
        session_id=session_id, session_type=session_type, sender_id=sender_id,
        group_id="1" if session_type is SessionType.GROUP else None,
        sender_platform_role=platform_role,
        plain_text=text, message_id="m1",
    )


def _seed(store: ReminderStore, sender_id: str, text: str, *, hours_ahead: int) -> str:
    """直构入库一条（绕开能力层正文去重），返回其 reminder_id。"""
    reminder = store.add(
        session_key="group:1", sender_id=sender_id, target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=datetime.now(timezone.utc) + timedelta(hours=hours_ahead),
        text=text,
    )
    assert reminder is not None
    return reminder.reminder_id


def _future_text(index: int) -> str:
    # 相对时刻（不受真实钟点影响）+ 正文互不相同：既绕 24h 去重，也避 id 撞前缀。
    return f"{20 + index}分钟后提醒我办事项{index}号"


# ---------------------------------------------------------------------------
# ① per-sender 子闸：群会话内单人霸占被拒，他人不受牵连
# ---------------------------------------------------------------------------


def test_group_sender_hogging_rejected_others_unaffected(tmp_path) -> None:
    """单成员连发不同正文到子闸上限后被拒；第 21 条之前的会话预算不再被
    一人独占——他人（含“12点提醒我吃药”）照常能记。"""
    capability = build_reminder_capability(_config(tmp_path))
    # 用足子闸额度：正好 MAX_PENDING_PER_SENDER 条成功。
    for index in range(MAX_PENDING_PER_SENDER):
        result = capability(_message(_future_text(index)), object())
        assert "added" in result.audit_tags, f"第 {index + 1} 条应在子闸内放行"
    hog = capability(_message("90分钟后提醒我办占位号"), object())
    assert "reminder_sender_full" in hog.audit_tags, "越界须走子闸拒绝分支"
    assert "排满" not in hog.body, "满的是个人额度，不得谎报会话排满"
    assert str(MAX_PENDING_PER_SENDER) in hog.body and "你自己" in hog.body, (
        "超限回执要可操作：说明是谁的额度满了"
    )
    assert "提醒列表" in hog.body, "回执给出取消旧条的行动指引"
    # 同群他人不受牵连：新发送者第一条照常记。
    other = capability(_message("70分钟后提醒我取快递", sender_id="u2"), object())
    assert "added" in other.audit_tags


def test_store_two_layer_quota_semantics(tmp_path) -> None:
    """store 层判据：不传子闸参数=既有行为逐字不变；传了则按人计数；
    两闸同踩满时 session_full 优先（更大的闸更可行动）。"""
    store = ReminderStore(tmp_path / "store.sqlite3")
    base = datetime.now(timezone.utc) + timedelta(hours=1)

    def _add(sender: str, index: int):
        return store.add(
            session_key="group:1", sender_id=sender, target_scope="group",
            target_id="1", adapter="nonebot", bot_id="bot",
            remind_at=base + timedelta(minutes=index), text=f"事{sender}{index}",
        )

    # 无子闸入参：单人 20 条照旧全收（A-07 既有语义回归锁）。
    for index in range(store.max_pending):
        assert _add("u1", index) is not None
    assert len(store.list_pending("group:1", limit=50)) == store.max_pending
    # 满会话 → session_full（即便同时踩满子闸也报会话层）。
    reminder, reason = store.add_checked(
        session_key="group:1", sender_id="u1", target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=base + timedelta(minutes=99), text="挤不进的一条",
        max_pending_for_sender=1,
    )
    assert reminder is None and reason == "session_full"

    # 干净库：子闸按人计数、不串号；不传子闸则第 2 条也放行。
    store2 = ReminderStore(tmp_path / "store2.sqlite3")
    r1, reason = store2.add_checked(
        session_key="group:1", sender_id="u9", target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=base, text="甲", max_pending_for_sender=1,
    )
    assert r1 is not None and reason == ""
    blocked, reason = store2.add_checked(
        session_key="group:1", sender_id="u9", target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=base + timedelta(minutes=1), text="乙", max_pending_for_sender=1,
    )
    assert blocked is None and reason == "sender_full"
    peer, reason = store2.add_checked(
        session_key="group:1", sender_id="u8", target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=base + timedelta(minutes=2), text="丙", max_pending_for_sender=1,
    )
    assert peer is not None and reason == "", "子闸按 sender 计数，不得串号"
    legacy = store2.add(
        session_key="group:1", sender_id="u9", target_scope="group",
        target_id="1", adapter="nonebot", bot_id="bot",
        remind_at=base + timedelta(minutes=3), text="丁（无子闸老调用面）",
    )
    assert legacy is not None, "add() 不传子闸参数=既有行为不变"


def test_private_session_no_sub_gate(tmp_path) -> None:
    """私聊桶只有本人：不设子闸，记满 MAX_PENDING_PER_SENDER 条后仍放行
    （配额只受会话总量闸约束）。"""
    capability = build_reminder_capability(_config(tmp_path))

    def _priv(index: int):
        return capability(
            _message(
                _future_text(index),
                sender_id="u1", session_id="u1", session_type=SessionType.PRIVATE,
            ),
            object(),
        )

    for index in range(MAX_PENDING_PER_SENDER + 1):
        result = _priv(index)
        assert "added" in result.audit_tags, f"私聊第 {index + 1} 条不该被子闸拦"


# ---------------------------------------------------------------------------
# ② 列表隐私：群内只列本人，他人原文/id 前缀零出现
# ---------------------------------------------------------------------------


def test_group_list_does_not_leak_others(tmp_path) -> None:
    """他人提醒（含健康/就诊类隐私）的原文与可取消 id 前缀不得出现在
    群回复里；本人条目照常可见可撤。"""
    capability = build_reminder_capability(_config(tmp_path))
    store = reminders_store_mod.build_reminder_store(_config(tmp_path))
    id_u2 = _seed(store, "u2", _PRIVATE_TEXT_U2, hours_ahead=3)
    id_u3 = _seed(store, "u3", _PRIVATE_TEXT_U3, hours_ahead=4)
    mine = capability(_message("35分钟后提醒我交周报"), object())
    assert "added" in mine.audit_tags

    listed = capability(_message("提醒列表", sender_id="u1"), object())
    assert "listed" in listed.audit_tags
    assert "交周报" in listed.body, "本人条目照常可见"
    for text in (_PRIVATE_TEXT_U2, _PRIVATE_TEXT_U3):
        assert text not in listed.body, f"他人提醒原文泄露进群回复：{text}"
    for rid in (id_u2, id_u3):
        assert rid[:6] not in listed.body, "他人可取消 id 前缀不得进群回复"
    # 管理员列表面同样无例外：也只列本人（本例管理员 u9 无自挂条目）。
    admin_list = capability(
        _message("提醒列表", sender_id="u9", platform_role="admin"), object()
    )
    assert "目前没有待办的提醒" in admin_list.body
    for text in (_PRIVATE_TEXT_U2, _PRIVATE_TEXT_U3):
        assert text not in admin_list.body


def test_owner_list_unchanged(tmp_path) -> None:
    """私聊列表整会话可见照旧（桶即本人，无隐私邻面）。"""
    capability = build_reminder_capability(_config(tmp_path))
    result = capability(
        _message(
            "25分钟后提醒我写作业", sender_id="u1", session_id="u1",
            session_type=SessionType.PRIVATE,
        ),
        object(),
    )
    assert "added" in result.audit_tags
    listed = capability(
        _message(
            "提醒列表", sender_id="u1", session_id="u1",
            session_type=SessionType.PRIVATE,
        ),
        object(),
    )
    assert "写作业" in listed.body


# ---------------------------------------------------------------------------
# ③ 取消归属校验：他人 id 撤不动；本人照常；管理员/群主例外（不复述原文）
# ---------------------------------------------------------------------------


def test_cancel_others_reminder_rejected_own_still_works(tmp_path) -> None:
    capability = build_reminder_capability(_config(tmp_path))
    store = reminders_store_mod.build_reminder_store(_config(tmp_path))
    id_u2 = _seed(store, "u2", _PRIVATE_TEXT_U2, hours_ahead=3)
    mine = _seed(store, "u1", "交周报", hours_ahead=5)

    # 直接抄他人 id 前缀取消：被拒（本人无挂账 → cancel_empty；有挂账 → 0 条歧义）。
    rejected = capability(
        _message(f"取消提醒 {id_u2[:6]}", sender_id="u1"), object()
    )
    assert "cancelled" not in rejected.audit_tags, "他人提醒不得被取消"
    assert store.list_pending("group:1", sender_id="u2") != [], "他人条目必须仍挂账"
    assert _PRIVATE_TEXT_U2 not in rejected.body, "拒绝回执也不得复述他人原文"

    # 本人取消自己：照常成功（回归面）。
    ok = capability(_message(f"取消提醒 {mine[:6]}", sender_id="u1"), object())
    assert "cancelled" in ok.audit_tags and "交周报" in ok.body
    assert store.list_pending("group:1", sender_id="u1") == []


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_platform_staff_can_cancel_others_without_text_echo(tmp_path, role) -> None:
    """管理员/群主例外沿用既有角色面 ``sender_platform_role``：可跨归属取消，
    但全群回执不复述他人原文；群内普通成员（role=member）不得。"""
    capability = build_reminder_capability(_config(tmp_path))
    store = reminders_store_mod.build_reminder_store(_config(tmp_path))
    id_u2 = _seed(store, "u2", _PRIVATE_TEXT_U2, hours_ahead=3)

    denied = capability(
        _message(
            f"取消提醒 {id_u2[:6]}", sender_id="u5", platform_role="member"
        ),
        object(),
    )
    assert "cancelled" not in denied.audit_tags, "member 头衔不得获得跨归属取消权"

    ok = capability(
        _message(f"取消提醒 {id_u2[:6]}", sender_id="u9", platform_role=role),
        object(),
    )
    assert "cancelled" in ok.audit_tags
    assert store.list_pending("group:1", sender_id="u2") == [], "管理员取消应真实落库"
    assert _PRIVATE_TEXT_U2 not in ok.body, "撤他人条目回执不得复述其原文"
