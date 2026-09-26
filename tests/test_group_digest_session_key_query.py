"""群摘要「查询键形」回归锁（D-7，台账 #33 病根；SEAT-D7-FIX 新立）。

背景：conversation_turns.session_id 写侧键为摄取层 NoneBot
``get_session_id()`` 群形 ``group_<群号>_<发送者>``；台账 #33 的缺陷是旧读侧
按 ``session_id="group:<群号>"`` 等值查——两键永不相交 ⇒ 21:30 群摘要推送
（G-DIGEST）静默空转零行。F4 席已把读侧修为按群前缀 LIKE 聚合；本件补两把
此前无人上的锁（全离线：临时 SQLite + 假队列，不依赖 NoneBot 运行时）：

1. **推送链路端到端查询锁**：真 provider（``build_shared_group_context_provider``）
   接真 ``_push_daily_group_digests``，写侧键入库的内容必须出现在推送正文里；
   库存只有死形态 ``group:<群号>`` 行时一律不推（防「读到死形态」回潮）。
2. **单一判据复用锁**：``shared_group._group_prefix`` 必须直接走全仓唯一权威
   ``domains/core/session_keys.group_session_prefix``（B-2 裁定「修=是」条款：
   禁再造第二套键形）。锁的是**路由本身**（monkeypatch 中央函数验穿透），
   不是值相等——值相等锁挡得住「两处同时改成同一个错形」。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import plugins.bot_unified_runtime as runtime_pkg
from plugins.bot_unified_runtime.domains.chat_reply.character import shared_group
from plugins.bot_unified_runtime.domains.chat_reply.character.history import (
    SQLiteConversationHistoryRepository,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.shared_group import (
    build_shared_group_context_provider,
)
from plugins.bot_unified_runtime.domains.core import session_keys
from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
    build_outbound_gate,
)

_NOW = datetime(2026, 9, 26, 21, 30, tzinfo=timezone.utc)
GROUP = "1108838060"


def _gate() -> object:
    """中央出站闸缺省关闭态（直通），与 test_group_digest_push 同款。"""
    return build_outbound_gate(SimpleNamespace())


class _FakeQueue:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def submit(self, request) -> None:
        self.requests.append(request)


def _push_config(db_path: Path) -> SimpleNamespace:
    """白名单模式的最小真形 config 投影（provider 工厂与推送共用）。"""
    return SimpleNamespace(
        bot_shared_group_context_enabled=True,
        bot_history_db_path=str(db_path),
        bot_group_digest_list_mode="whitelist",
        bot_group_digest_whitelist=[GROUP],
        bot_group_digest_blacklist=[],
        bot_group_digest_llm_enabled=False,
        bot_persona_profile_id="default",
    )


def _write_turn(db: Path, *, session_id: str, sender_id: str, text: str) -> None:
    """走生产写入口落一条（真实 schema、真实键构造口径）。"""
    SQLiteConversationHistoryRepository(db).append_turn(
        request_id=f"req-{session_id}-{text[:4]}",
        platform="qq",
        adapter="onebot-v11",
        bot_id="bot-1",
        session_id=session_id,
        sender_id=sender_id,
        role="user",
        text=text,
        kind="chat",
    )


# ---------------------------------------------------------------------------
# 1. 推送链路端到端：查询侧必须读到写侧键
# ---------------------------------------------------------------------------


def test_push_path_delivers_rows_stored_under_underscore_keys(tmp_path: Path) -> None:
    """主案：按写侧键 group_<gid>_<uid> 入库 → 21:30 推送正文必含该内容。

    台账 #33 病灶的直白复现：旧读侧等值查 "group:<gid>" 在此场景恒零行、
    推送静默空转；修复后必须读到并投递。
    """
    db = tmp_path / "history.sqlite3"
    _write_turn(
        db,
        session_id=session_keys.build_session_key(GROUP, "3865067623"),
        sender_id="3865067623",
        text="今晚九点推版本更新",
    )
    _write_turn(
        db,
        session_id=session_keys.build_session_key(GROUP, "3113533731"),
        sender_id="3113533731",
        text="卡池要换 UP 了",
    )

    config = _push_config(db)
    queue = _FakeQueue()
    provider = build_shared_group_context_provider(config)

    pushed = runtime_pkg._push_daily_group_digests(
        config, queue, provider, _gate(), now=_NOW
    )

    assert pushed == [GROUP]
    assert len(queue.requests) == 1
    body = str(queue.requests[0].content.text_fallback)
    assert "今晚九点推版本更新" in body
    assert "卡池要换 UP 了" in body


def test_push_skips_when_only_dead_colon_form_rows_stored(tmp_path: Path) -> None:
    """死形态防回潮：库里只有 "group:<gid>" 行（生产 0 行形态）时不推送。

    读侧一旦重新消费冒号形（或退化成模糊匹配吞脏键），本锁报红——
    冒号形不属于存储命名空间，正常生产库根本不该有它。
    """
    db = tmp_path / "history.sqlite3"
    _write_turn(
        db,
        session_id=f"{session_keys.LEGACY_GROUP_SCHEME}{GROUP}",
        sender_id="ghost",
        text="不该被消费的死形态内容",
    )

    config = _push_config(db)
    queue = _FakeQueue()
    provider = build_shared_group_context_provider(config)

    pushed = runtime_pkg._push_daily_group_digests(
        config, queue, provider, _gate(), now=_NOW
    )

    assert pushed == []
    assert queue.requests == []


# ---------------------------------------------------------------------------
# 2. 单一判据复用锁：读侧前缀直接走中央件，不留第二套键形
# ---------------------------------------------------------------------------


def test_group_prefix_routes_through_central_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """shared_group._group_prefix 必须穿透 session_keys.group_session_prefix。

    值相等锁（test_session_keys_wiring）挡得住两处其中一处改形，挡不住
    「两处同时改成同一个错形」；本锁把复用本身钉死：换中央件实现，
    读侧行为必随之变。修复前 _group_prefix 用本地字面量拼装 → 此锁为 RED。
    """
    monkeypatch.setattr(
        session_keys, "group_session_prefix", lambda group_id: "SENTINEL_PREFIX_"
    )

    assert shared_group._group_prefix(GROUP) == "SENTINEL_PREFIX_"


def test_no_second_key_form_copy_in_read_side() -> None:
    """禁再造第二套键形：读侧模块内不得再持有 "group_" 前缀字面量副本。

    键形态的唯一权威在 domains/core/session_keys.py；shared_group.py 历史上
    留过镜像常量 _GROUP_SESSION_PREFIX（字节等价但仍是副本，台账 #33 病根
    即「各自只认一种」的副本漂移），本锁要求副本彻底摘除、只余转义口径等
    非键形本地常量。
    """
    namespace = vars(shared_group)
    assert "_GROUP_SESSION_PREFIX" not in namespace
    local_strings = {
        value
        for value in namespace.values()
        if isinstance(value, str)
    }
    assert session_keys.GROUP_SESSION_PREFIX not in local_strings, (
        "shared_group.py 仍持有群键前缀字面量副本——应直接复用中央件常量/函数"
    )
    assert shared_group._group_prefix(GROUP) == (
        f"{session_keys.GROUP_SESSION_PREFIX}{GROUP}_"
    )
