"""S-FIX-GOAL18-REST2（2026-09-28）——第 20 项相邻族收件箱两腿修复的行为锁。

上游票面（全部现算复核后实施）：
- ``SEAT-ATK-SCHEDULE.md`` 会错 A1：``archive_inbox`` 锁外读快照→锁内整段清空，
  并发速记「既没进归档、也被抹掉」两头无痕（前席探针实锤 竞态条目B 静默丢失=True）。
  修法：快照读→写归档→清空**全程持 ``_INBOX_APPEND_LOCK``**（锁非可重入，
  清空改为假定持锁的 ``_clear_pending_locked``，唯一上锁点收进 archive 头部）。
- 同票 A3a：速记面零速率闸——任意群友可无限灌 owner 共享收件箱，
  毒杀次日早报（超长全量发送失败＝合法条目随沉）。修法：能力面 capture 腿挂
  per-sender 滑窗闸（常量、不加 config 键，先例 reminders.MAX_PENDING_PER_SENDER）。
- 同票 A3b：``build_morning_brief`` 收件箱段无总长帽。修法：帽住展示、
  超限**显式标注「另有 N 行未列出」**（先例 reminders ``_receipt_items_label``），
  归档仍全量——无信息湮灭。

注毒靶（各锁各腿）：
① 还原 archive 为锁外读 → ``test_archive_snapshot_read_holds_append_lock`` 红；
② 摘除 capture 腿速率闸 → ``test_capture_leg_denies_and_never_writes_when_saturated`` 红；
③ 帽枚举还原为全量 extend（无标注）→ ``test_morning_brief_flood_capped_and_labeled`` 红。
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.domains.assistant.daily.capabilities import (
    daily_assist as cap_module,
)
from plugins.bot_unified_runtime.domains.assistant.daily.capabilities.daily_assist import (
    _CAPTURE_DENIED_VARIANTS,
    _INBOX_RATE_MAX_PER_WINDOW,
    _INBOX_RATE_WINDOW_SECONDS,
    _inbox_rate_allowed,
    build_daily_assist_capability,
    reset_inbox_rate_state,
)
from plugins.bot_unified_runtime.domains.assistant.daily.store import (
    daily_assist as store_module,
)
from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
    _MORNING_BRIEF_INBOX_MAX_CHARS,
    append_inbox_line,
    archive_inbox,
    build_morning_brief,
    daily_archive_dir,
    inbox_path,
    read_pending_inbox,
)


def _make_config(tmp_path):
    return SimpleNamespace(
        bot_daily_assist_enabled=True,
        bot_daily_assist_dir="data/daily_assist",
        bot_daily_assist_push_user_ids=["10001"],
        bot_persona_profile_id="default",
    )


@pytest.fixture()
def assist_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_path_domain_policy():
    """路径域守卫进程级缺省策略逐测复位（test_daily_assist 同型夹具义务）。"""
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(None)
    yield
    paths.set_default_policy(None)


@pytest.fixture(autouse=True)
def _reset_rate_state():
    """速率闸进程内态逐测复位——本件不欠账，也不给别的文件留脏桶。"""
    reset_inbox_rate_state()
    yield
    reset_inbox_rate_state()


def _run_capability(
    config,
    text: str,
    *,
    sender_id: str = "10001",
    session_type: Any = SessionType.PRIVATE,
):
    message = SimpleNamespace(
        plain_text=text,
        request_id="req-g18r2",
        sender_id=sender_id,
        session_type=session_type,
    )
    return build_daily_assist_capability(config)(message, None)


# ---------------------------------------------------------------------------
# A1：归档原子性
# ---------------------------------------------------------------------------


def test_archive_snapshot_read_holds_append_lock(assist_env, tmp_path, monkeypatch) -> None:
    """核心锁（确定性、无真实线程）：archive 的快照读必须发生在锁内。

    ``threading.Lock`` 非可重入——同线程已持锁时 ``acquire(blocking=False)``
    返回 False 是「此刻锁被本线程持有」的现算判据。旧写法（锁外读）下
    此刻锁是空的 ⇒ acquire 成功 ⇒ 本锁当场红（即注毒天然靶①）。
    """
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    now = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    append_inbox_line(inbox, "锁位探针条目", now=now)

    original = store_module.read_pending_inbox
    held_flags: list[bool] = []

    def _probe(path):
        acquired = store_module._INBOX_APPEND_LOCK.acquire(blocking=False)
        if acquired:
            store_module._INBOX_APPEND_LOCK.release()
        held_flags.append(not acquired)  # True = 快照读时锁已被本线程持有
        return original(path)

    monkeypatch.setattr(store_module, "read_pending_inbox", _probe)
    archived = archive_inbox(inbox, daily_archive_dir(config), now=now)
    assert archived, "基线：确有条目被归档"
    assert held_flags and all(held_flags), "快照读不在锁内＝A1 竞态窗口重现"


def test_archive_rounds_never_lose_entries(assist_env, tmp_path) -> None:
    """零丢失端到端：append A → archive → append B → archive。

    两回合归档并集恰为 {A,B}、pending 终空；B 不属于第一回合（前一归档
    不吞后到速记，反向同证「归档=快照」而非「归档=运气」）。
    """
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    t1 = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 15, 8, 5, tzinfo=timezone.utc)
    append_inbox_line(inbox, "条目A", now=t1)
    round1 = archive_inbox(inbox, daily_archive_dir(config), now=t1)
    append_inbox_line(inbox, "条目B", now=t2)
    round2 = archive_inbox(inbox, daily_archive_dir(config), now=t2)
    assert [i for i in round1 if "条目A" in i] and not any("条目B" in i for i in round1)
    assert [i for i in round2 if "条目B" in i]
    assert read_pending_inbox(inbox) == []
    text = (daily_archive_dir(config) / "2026-09-15.md").read_text(encoding="utf-8")
    assert "条目A" in text and "条目B" in text


def test_archive_clear_keeps_other_sections(assist_env, tmp_path) -> None:
    """锁上提不许改清空语义：非待处理段原样保留（既有行为回归位）。"""
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(
        "# 收件箱（Inbox）\n\n## 待处理\n\n- [2026-09-14 09:00] 旧条目\n\n## 已处理规则\n\n- 别动我\n",
        encoding="utf-8",
    )
    archive_inbox(inbox, daily_archive_dir(config), now=datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc))
    text = inbox.read_text(encoding="utf-8")
    assert "旧条目" not in text and "## 已处理规则" in text and "别动我" in text


# ---------------------------------------------------------------------------
# A3a：速记滑窗闸
# ---------------------------------------------------------------------------


def test_rate_gate_window_semantics_unit() -> None:
    """判据锁：窗口内放满即拒、滑窗过后放行、不同 sender 互不占用、空号共享桶。"""
    t0 = 1_000_000.0
    assert all(_inbox_rate_allowed("90001", now=t0) for _ in range(_INBOX_RATE_MAX_PER_WINDOW))
    assert not _inbox_rate_allowed("90001", now=t0 + 1.0), "超限必须拒"
    assert _inbox_rate_allowed("90002", now=t0), "他人桶不受影响"
    assert _inbox_rate_allowed("90001", now=t0 + _INBOX_RATE_WINDOW_SECONDS + 1), "滑窗应放行"
    assert all(_inbox_rate_allowed("", now=t0 + 60) for _ in range(_INBOX_RATE_MAX_PER_WINDOW))
    assert not _inbox_rate_allowed(None, now=t0 + 61), "空号与缺失号必须同共享桶（fail-closed）"


def test_rate_gate_denial_does_not_record() -> None:
    """超限拒**不记账**——被拒的洪泛不许消耗后续窗口（只计成功落盘）。"""
    t0 = 2_000_000.0
    for _ in range(_INBOX_RATE_MAX_PER_WINDOW):
        assert _inbox_rate_allowed("90003", now=t0)
    for _ in range(5):
        assert not _inbox_rate_allowed("90003", now=t0 + 1)
    # 再滑一格，最早一条过期 ⇒ 恰好放行一条。
    assert _inbox_rate_allowed("90003", now=t0 + _INBOX_RATE_WINDOW_SECONDS)


def test_capture_leg_denies_and_never_writes_when_saturated(assist_env, tmp_path) -> None:
    """端到端闸位锁：饱和后「收件箱 X」不落盘、不透额度、audit 打标；
    同一腿未饱和时照常可写（降档只降超限、不杀功能）。"""
    config = _make_config(tmp_path)
    inbox = inbox_path(config)
    cap_module._INBOX_RATE_HITS["91001"] = deque(
        [time.time()] * _INBOX_RATE_MAX_PER_WINDOW, maxlen=1000
    )
    denied = _run_capability(config, "收件箱 淹没守岸人", sender_id="91001")
    assert denied.body in _CAPTURE_DENIED_VARIANTS
    assert "capture_rate_limited" in denied.audit_tags
    assert not inbox.exists() or "淹没守岸人" not in inbox.read_text(encoding="utf-8")
    if inbox.exists():
        assert read_pending_inbox(inbox) == []
    # 未饱和发送者（不同桶）照记——闸不许把功能整体打死。
    ok = _run_capability(config, "收件箱 正常一条", sender_id="91002")
    assert "正常一条" in ok.body and "capture" in ok.audit_tags


def test_capture_denied_pool_tone_guard() -> None:
    """文案纪律：拒答池守岸人语气、变体 ≥6、不透剩余条数、违禁词零命中。"""
    assert len(_CAPTURE_DENIED_VARIANTS) >= 6
    joined = "\n".join(_CAPTURE_DENIED_VARIANTS)
    assert "守岸人" in joined
    for token in ("～", "系统", "提示词", "脚本", "注入", "作为AI", "值得注意的是", "综上所述", "还剩", "条额度"):
        assert token not in joined, f"拒答文案命中违禁/漏额度字样：{token}"


# ---------------------------------------------------------------------------
# A3b：早报收件箱段总长帽
# ---------------------------------------------------------------------------


def test_morning_brief_flood_capped_and_labeled() -> None:
    """洪泛帽锁：40 条 ×100 字 ⇒ 收件箱段列面 ≤ 帽 + 标注行，且**显式**「另有 N 行」
    N=真实未列数（不许静默截断）。注毒靶③：还原全量 extend ⇒ 本锁红。"""
    pending = [f"[2026-09-15 08:00] {'泛' * 100}{i}" for i in range(40)]
    brief = build_morning_brief(pending, {}, "")
    lines = brief.splitlines()
    assert "【收件箱】" in lines
    start = lines.index("【收件箱】") + 1
    note = [ln for ln in lines if "另有" in ln and "行未列出" in ln]
    assert len(note) == 1, "超限必须恰好一枚显式标注（禁静默截断）"
    shown = [ln for ln in lines[start:] if ln.startswith(tuple("123456789"))]
    listed = sum(len(ln) for ln in shown)
    assert listed <= _MORNING_BRIEF_INBOX_MAX_CHARS, f"列面 {listed} 字越帽"
    omitted = 40 - len(shown)
    assert f"另有 {omitted} 行未列出" in brief
    assert 0 < len(shown) < 40, "帽不许将列面清零（0<N<全量）"


def test_morning_brief_small_input_unchanged() -> None:
    """帽内零改变：小清单早报不得出现标注行（既有 test_daily_assist 文案位回归向）。"""
    brief = build_morning_brief(["[2026-09-15 08:00] 买牛奶"], {"进行中": ["写周报"]}, "")
    assert "买牛奶" in brief and "写周报" in brief
    assert "行未列出" not in brief
