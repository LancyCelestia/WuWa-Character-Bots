"""显式开档跨重启持久化（2026-10-03 用户裁定 D-1「要：显式开档跨重启持久化」）。

病灶（现算在册，AGENTS 台账 #75 同族／记忆「两处生产阻断」之②）：亲密档态住在
**进程内** LRU（`content_route._SESSION_CAP` + 模块级单例
`SHARED_CONTENT_ROUTE_ENGINE`）⇒ 重启即空；重启后 `capabilities/chat.py` 那两支
自动腿的守卫 `pinned_mode(...) is None` 成立 ⇒ 以 `master_love` / `affinity_tier`
重钉，而这两个来源都不在 `_INTIMATE_NARRATION_SOURCES` 里 ⇒ 她亲手「亲密模式 开」
过的会话拿不回五维叙述。

本文件钉的是修法的**两侧**：

- 放宽侧：本人私聊里显式开过 ⇒ 重启后自动腿重钉时沿用 `manual_command` 源与该档
  （①③⑤⑥）。
- **防过修侧**：ML／好感度那两支自动腿本身**一字不改地继续没有叙述权**（②③⑦），
  群侧两支（管理员钉、群内成员个人钉）**不入库**（④⑤），`intimate_ttl_minutes`
  的语义不变——**重启也不续期**（③），而且**同一进程内不二次放行**（⑥'
  `test_same_process_never_re_honors_a_mark_it_wrote`：这条同时是
  `tests/test_content_route_v3.py`／`test_intimate_slash_command.py` 那批"整份文件共用
  一只 tmp 库 + 重复合成人称键"的用例不被串味的根因面）。

夹具铁律（本仓家规）：
- DATAFIX：涉库键（`bot_addressing_preferences_db_path`）**显式指仓库外 tmp 绝对
  路径**。不指就会走生产 getattr 缺省 `data/addressing_preferences.sqlite3`，把测试
  读写落到运行数据根或源码树 `data/`（先例 `tests/test_rp_style_directives.py:60-64`）。
- 本文件**不碰** `capabilities/chat.py` 与 `/bot reply` 命令面（只驱动引擎与存储），
  故无需 `monkeypatch` `shared_reply_policy_store`；`reply_policy.sqlite3` 一个字节
  都不该被这些用例摸到（验收另以只读 `-wal` mtime 核对）。
- "重启"＝新建引擎实例 **且** `_simulate_restart()`（逐出 providers 的进程级 store
  缓存并关掉连接 + 清掉"本进程写过哪些标记"那本账）：只清内存而留着旧连接与进程账的
  话，测试会凭进程缓存假绿（数据必须从盘上重读，标记也必须像是**上一个进程**留下的）。
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_AFFINITY,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L1,
    INTIMATE_TIER_L2,
    ContentRouteEngine,
    grants_intimate_narration,
    member_session_key,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    group_scope_key,
    private_session_key,
)

MIN = 60.0
# 墙钟基准：与真实"现在"无关，判据只看差值（时钟注入缝 `ContentRouteEngine(wall_clock=…)`）。
WALL0 = 1_800_000_000.0
# 单调钟起点（见 `_Clocks` 的假值陷阱注释）；显式开档就发生在这一刻，标记里的时刻即此值。
CLOCK_BASE_SEC = 1000.0
WALL_AT_OPEN = WALL0 + CLOCK_BASE_SEC
ADDR_DB_NAME = "addressing_preferences.sqlite3"

# 并号（E-1，2026-10-03 裁定「要」）：同一个人两个号共用一份亲密标记。形状照生产
# ``BOT_REPLY_POLICY_PERSON_ALIASES``（**左号并入右号**），号一律用合成值——把她的真实
# 号抄进夹具＝长出第二份真身，且她改一次配置这些用例就假绿。
SIDE_UID = "9600001120"  # 并入方
MAIN_UID = "9600001121"  # 被并入的目标（归并定点）
UNRELATED_UID = "9600001122"  # 表里没有的隔壁号
MERGED_ALIASES: dict[str, str] = {SIDE_UID: MAIN_UID}


class _Clocks:
    """单调钟与墙钟**同源**推进：这样 TTL 惰性过期与跨重启标记判据在同一时间轴上。

    起点刻意不为 0：真实进程的 ``time.monotonic`` 参照点在开机侧，取到聊天轮次时早已
    不是 0.0；而回填 ``activated_at`` 落到 0.0 会被 ``_state`` 那句
    ``and state.activated_at`` 当"没记激活时刻"跳过整条 TTL（假值陷阱，
    引擎侧已下夹 1e-6，这一枚是**两侧都钉**的读数）。
    """

    def __init__(self) -> None:
        self.sec = CLOCK_BASE_SEC

    def monotonic(self) -> float:
        return self.sec

    def wall(self) -> float:
        return WALL0 + self.sec

    def advance(self, minutes: float) -> None:
        self.sec += minutes * MIN


def _config(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        # DATAFIX：仓库外 tmp 绝对路径（见模块 docstring 夹具铁律）。
        "bot_addressing_preferences_db_path": str(tmp_path / ADDR_DB_NAME),
        # 真 ``Config`` 恒有这一枚（缺省空表＝不并号）；夹具跟着在场，才测得到
        # "配置写坏／没配" 与 "配了" 三态分别走哪条腿。
        "bot_reply_policy_person_aliases": {},
        "bot_content_route_enabled": True,
        "bot_content_route_model": "grok-4.6",
        "bot_content_route_order": "grok-4.6,gemini-3.8-flash",
        "bot_content_route_words": "",
        "bot_content_route_intimate_threshold": 60.0,
        "bot_content_route_normal_threshold": 25.0,
        "bot_content_route_context_turns": 4,
        "bot_content_route_max_ttl_minutes": 120.0,
        "bot_content_route_idle_reset_minutes": 10.0,
        "bot_content_route_intimate_ttl_minutes": 60.0,
        "bot_content_route_group_per_user_enabled": True,
        "bot_content_route_group_whitelist": [],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
        "bot_content_route_l1_auto_enabled": True,
        "bot_content_route_l1_auto_min_tier": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _engine(clocks: _Clocks) -> ContentRouteEngine:
    return ContentRouteEngine(clock=clocks.monotonic, wall_clock=clocks.wall)


def _simulate_restart() -> None:
    """把"重启"这件事的三半一起做到位（调用方另需新建引擎实例＝内存清空那一半）。

    ① providers 的进程级 store 缓存：关掉连接再逐出——不逐出的话标记仍能从旧连接
       的进程态里读到，"重启"就只清了引擎内存 ⇒ 假绿。
    ② ``_MARKS_WRITTEN_BY_THIS_PROCESS``：新进程本来就没有这本账（它就是"这枚标记
       是不是上一个进程留下的"的判据）。
    ③（在调用方）新 ``ContentRouteEngine`` 实例：``_sessions`` 是空的。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    with providers._ADDRESSING_STORES_LOCK:
        stale = list(providers._ADDRESSING_STORES.values())
        providers._ADDRESSING_STORES.clear()
    for store in stale:
        with contextlib.suppress(Exception):  # 关不掉只是连接泄漏，不影响判据
            store._conn.close()
    with cr._MARKS_WRITTEN_LOCK:
        cr._MARKS_WRITTEN_BY_THIS_PROCESS.clear()


def _read_back_row(
    tmp_path: Path, sender_id: str, db_name: str = ADDR_DB_NAME
) -> tuple[str, float]:
    """绕开引擎、直接从**盘**上读这一格（用来证明落盘了、或证明没落盘）。"""
    store = AddressingPreferenceStore(tmp_path / db_name)
    try:
        return store.get_intimate_pin(
            session_type="private", session_id="", sender_id=sender_id
        )
    finally:
        store._conn.close()


def _open_explicitly(tmp_path: Path, uid: str, tier: str) -> tuple[_Clocks, SimpleNamespace]:
    """前半段：本人在私聊里显式开档（chat.py 的 manual 腿形状：键＝裸 uid 会话键）。"""
    clocks = _Clocks()
    cfg = _config(tmp_path)
    engine = _engine(clocks)
    assert engine.apply_manual(
        private_session_key(uid), "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=tier
    ) is True
    return clocks, cfg


# ---------------------------------------------------------------- ① 显式开档活过重启


@pytest.mark.parametrize("tier", [INTIMATE_TIER_L1, INTIMATE_TIER_L2])
def test_explicit_open_survives_restart_and_reclaims_narration_right(
    tmp_path: Path, tier: str
) -> None:
    """重启后自动腿重钉 ⇒ 来源回到 `manual_command`、档位回到她开的那一档。

    ①的两条断言各管一件事：`source == manual_command`（**为什么**亲密）与
    `grants_intimate_narration(...) is True`（于是五维叙述回来了）。
    """
    uid = "9600001101"
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, tier)
    # 标记确实在盘上（不是只活在内存里）。
    assert _read_back_row(tmp_path, key) == (tier, WALL_AT_OPEN)

    _simulate_restart()
    restarted = _engine(clocks)  # 新实例＝新进程：`_sessions` 是空的
    assert restarted.pinned_mode(key, cfg) is None, "内存没清空＝这具重启是假的"

    # chat.py 自动腿的重钉调用形状（守卫已过、来源与档位都按"没有标记"交上来）。
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = restarted.route_verdict(key, cfg)
    assert verdict["mode"] == "intimate", verdict
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL, verdict
    assert verdict["tier"] == tier, verdict
    assert grants_intimate_narration(verdict["source"]) is True
    # 深档有权换真实首跳、浅档没有（档位与来源两轴都不许被持久化腿顺手改动）。
    assert bool(verdict["head_models"]) is (tier == INTIMATE_TIER_L2), verdict


# ---------------------------------------------------------------- ② 防过修：自动腿照旧无叙述权


@pytest.mark.parametrize("auto_source", [INTIMATE_SOURCE_MASTER_LOVE, INTIMATE_SOURCE_AFFINITY])
def test_auto_leg_without_a_mark_stays_exactly_where_it_is(
    tmp_path: Path, auto_source: str
) -> None:
    """没标记者重钉＝今日行为：来源不变、档位不变、**叙述权仍为 False**。

    这条是"别把 ML 一起放宽"的锁：修法只许凭"她亲手开过"这一枚凭据放行，
    不许把 `_INTIMATE_NARRATION_SOURCES` 整张表扩宽。
    """
    uid = "9600001102"
    key = private_session_key(uid)
    clocks = _Clocks()
    cfg = _config(tmp_path)
    engine = _engine(clocks)
    assert (
        engine.apply_manual(
            key, "intimate", cfg, source=auto_source, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = engine.route_verdict(key, cfg)
    assert verdict["mode"] == "intimate", verdict
    assert verdict["source"] == auto_source, verdict
    assert verdict["tier"] == INTIMATE_TIER_L1, verdict
    assert grants_intimate_narration(verdict["source"]) is False
    assert verdict["head_models"] == []
    # 自动腿不是显式腿：它不许顺手把标记写进库（那等于"自动"熬成"亲手"）。
    assert _read_back_row(tmp_path, key) == ("", 0.0)


def test_a_mark_never_leaks_to_the_person_who_never_opened_it(tmp_path: Path) -> None:
    """标记按人归人：隔壁没说过那句话的人重启后照旧 `master_love`（不共享、不串号）。"""
    holder = "9600001103"
    bystander = "9600001104"
    clocks, cfg = _open_explicitly(tmp_path, holder, INTIMATE_TIER_L2)
    _simulate_restart()
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            private_session_key(bystander),
            "intimate",
            cfg,
            source=INTIMATE_SOURCE_MASTER_LOVE,
            tier=INTIMATE_TIER_L1,
        )
        is True
    )
    verdict = restarted.route_verdict(private_session_key(bystander), cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert grants_intimate_narration(verdict["source"]) is False


# ---------------------------------------------------------------- ③ TTL 到了仍要清


def test_expired_mark_is_not_honored(tmp_path: Path) -> None:
    """TTL（60 分钟）已过 ⇒ 标记不再被沿用，落回今日缺省（ML 浅档、无叙述权）。"""
    uid = "9600001105"
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, INTIMATE_TIER_L2)
    clocks.advance(61)  # 墙钟一起走：距首次显式开启 61 分钟
    _simulate_restart()
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = restarted.route_verdict(key, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert verdict["tier"] == INTIMATE_TIER_L1, verdict
    assert grants_intimate_narration(verdict["source"]) is False


def test_restart_does_not_renew_the_ttl_window(tmp_path: Path) -> None:
    """**重启也不续期**：沿用标记上钉时把 TTL 起算点回填，窗口仍是"首次显式开启 +60 分钟"。

    这是 S40-D2 那条教训（会话活跃不续期）的对称面：旧写法若让重钉把
    `activated_at` 归零，重启一次就白送一整段 TTL ⇒ "开一次、重启一次、永远在档"。
    """
    uid = "9600001106"
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, INTIMATE_TIER_L1)
    clocks.advance(59)  # 距首次显式开启 59 分钟：还在窗口内
    _simulate_restart()
    restarted = _engine(clocks)
    assert restarted.pinned_mode(key, cfg) is None
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_AFFINITY, tier=INTIMATE_TIER_L1
        )
        is True
    )
    assert restarted.route_verdict(key, cfg)["source"] == INTIMATE_SOURCE_MANUAL

    clocks.advance(2)  # 绝对时刻＝距首次显式开启 61 分钟
    expired = restarted.route_verdict(key, cfg)
    assert expired["mode"] == "normal", expired
    assert expired["source"] == INTIMATE_SOURCE_NONE, expired
    assert grants_intimate_narration(expired["source"]) is False
    # 到点之后再来的自动腿也救不回来：标记不能复活档，只回答"该以什么来源重钉"。
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_AFFINITY, tier=INTIMATE_TIER_L1
        )
        is True
    )
    assert restarted.route_verdict(key, cfg)["source"] == INTIMATE_SOURCE_AFFINITY


# ---------------------------------------------------------------- ④ 群侧两支都不入库


def test_same_process_never_re_honors_a_mark_it_wrote(tmp_path: Path) -> None:
    """跨进程的凭据不在进程内二次放行：本进程刚写过的标记，换一具引擎也不沿用。

    锁住"标记只活过重启、不当进程内的复活符"这条边界：同一进程里权威是内存那枚钉。
    反过来写就会串味——``tests/test_content_route_v3.py`` 整份文件共用一只 tmp 库、
    又反复用同一个合成人称键 ``private:u1``，同进程复活会把 ML 自动钉抬成 ``manual``
    ⇒ ``_MAX_TTL_EXEMPT_SOURCES`` 的豁免面被撑大、``max_ttl`` 硬上限那条锁当场失效
    （本波实测过这条红，故把它钉成用例而不是靠改别人的夹具）。
    """
    uid = "9600001114"
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, INTIMATE_TIER_L2)
    assert _read_back_row(tmp_path, key) == (INTIMATE_TIER_L2, WALL_AT_OPEN)

    second = _engine(clocks)  # 同一"进程"里的另一具引擎：**不**调 _simulate_restart
    assert second.pinned_mode(key, cfg) is None
    assert (
        second.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = second.route_verdict(key, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert verdict["tier"] == INTIMATE_TIER_L1, verdict
    assert grants_intimate_narration(verdict["source"]) is False

    # 真重启（进程账清空）之后，同一份盘上的数据就够格被沿用了——差的只有"新进程"。
    _simulate_restart()
    third = _engine(clocks)
    assert (
        third.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    assert third.route_verdict(key, cfg)["source"] == INTIMATE_SOURCE_MANUAL


def test_group_admin_pin_is_not_persisted(tmp_path: Path) -> None:
    """管理员替全群拨的钉＝**当场**授权，不该活过重启（群作用域键连一行都不写）。"""
    uid = "9600001107"
    group_id = "9600001040"
    scope_key = group_scope_key(build_session_key(group_id, uid))
    assert scope_key.startswith("group:")  # 中央件收拢后的整群作用域键
    clocks = _Clocks()
    cfg = _config(tmp_path)
    engine = _engine(clocks)
    assert (
        engine.apply_manual(
            scope_key, "intimate", cfg, source=INTIMATE_SOURCE_ADMIN_PIN, tier=INTIMATE_TIER_L2
        )
        is True
    )
    assert _read_back_row(tmp_path, scope_key) == ("", 0.0)
    assert _read_back_row(tmp_path, private_session_key(uid)) == ("", 0.0)

    _simulate_restart()
    restarted = _engine(clocks)
    assert restarted.pinned_mode(scope_key, cfg) is None
    assert (
        restarted.apply_manual(
            scope_key, "intimate", cfg, source=INTIMATE_SOURCE_ADMIN_PIN, tier=INTIMATE_TIER_L2
        )
        is True
    )
    # 重钉照旧成功、来源照旧是 admin_pin（本波没给群侧加任何"沿用"）。
    assert restarted.route_verdict(scope_key, cfg)["source"] == INTIMATE_SOURCE_ADMIN_PIN


def test_group_member_personal_pin_is_not_persisted(tmp_path: Path) -> None:
    """群内成员的个人钉（成员派生键）也不入库：本波裁定面写的是"私聊里显式说过"。"""
    member_id = "9600001108"
    group_id = "9600001040"
    derived = member_session_key(build_session_key(group_id, member_id), member_id)
    clocks = _Clocks()
    cfg = _config(tmp_path)
    engine = _engine(clocks)
    assert (
        engine.apply_manual(
            derived, "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L2
        )
        is True
    )
    assert _read_back_row(tmp_path, derived) == ("", 0.0)
    assert _read_back_row(tmp_path, private_session_key(member_id)) == ("", 0.0)

    _simulate_restart()
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            derived, "intimate", cfg, source=INTIMATE_SOURCE_AFFINITY, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = restarted.route_verdict(derived, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_AFFINITY, verdict
    assert grants_intimate_narration(verdict["source"]) is False


def test_explicit_off_survives_restart_too(tmp_path: Path) -> None:
    """「亲密模式 关」也跨重启：只清内存不清库＝重启后凭旧标记把刚关掉的档又"沿用"回来。"""
    uid = "9600001109"
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, INTIMATE_TIER_L2)
    engine = _engine(clocks)
    assert engine.apply_manual(key, "normal", cfg, source=INTIMATE_SOURCE_MANUAL) is True
    assert _read_back_row(tmp_path, key) == ("", 0.0)  # 标记已收回

    _simulate_restart()
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = restarted.route_verdict(key, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert verdict["tier"] == INTIMATE_TIER_L1, verdict


# ---------------------------------------------------------------- 存储层契约：别碰邻居列


def test_intimate_columns_do_not_disturb_the_other_preferences(tmp_path: Path) -> None:
    """同表不同列：写/收亲密标记不得改称谓，`/bot identity` 的部分更新也不得洗掉标记。"""
    uid = "9600001110"
    key = private_session_key(uid)
    path = tmp_path / ADDR_DB_NAME
    store = AddressingPreferenceStore(path)
    try:
        store.set(
            session_type="private", session_id="", sender_id=key, addressing_preference="小岸"
        )
        assert store.set_relationship(
            session_type="private", session_id="", sender_id=key, relationship="恋人"
        ) == "lover"
        store.set_intimate_pin(
            session_type="private", session_id="", sender_id=key, tier=INTIMATE_TIER_L2,
            explicit_at=WALL0,
        )
        assert store.get(session_type="private", session_id="", sender_id=key) == (
            "小岸",
            "unknown",
        )
        assert store.get_relationship(session_type="private", session_id="", sender_id=key) == (
            "lover"
        )
        assert store.get_intimate_pin(
            session_type="private", session_id="", sender_id=key
        ) == (INTIMATE_TIER_L2, WALL0)
        # 收回标记：只清那两格，称谓与关系档一个字节都不动（`clear()` 才是整行删除）。
        store.clear_intimate_pin(session_type="private", session_id="", sender_id=key)
        assert store.get_intimate_pin(
            session_type="private", session_id="", sender_id=key
        ) == ("", 0.0)
        assert store.get(session_type="private", session_id="", sender_id=key)[0] == "小岸"
        # 反过来：邻居写自己的列（含"未指定字段保留原值"的部分更新）也不该洗掉标记。
        store.set_intimate_pin(
            session_type="private", session_id="", sender_id=key, tier=INTIMATE_TIER_L1,
            explicit_at=WALL0 + 5,
        )
        store.set(session_type="private", session_id="", sender_id=key, gender_identity="female")
        assert store.get_intimate_pin(
            session_type="private", session_id="", sender_id=key
        ) == (INTIMATE_TIER_L1, WALL0 + 5)
    finally:
        store._conn.close()


# ---------------------------------------------------------------- fail-open / 惰性面


def test_engine_without_a_declared_store_stays_exactly_on_todays_behavior(
    tmp_path: Path,
) -> None:
    """配置没点名这本库 ⇒ 持久化腿整条不存在（纯离线引擎单测就是这一形）。"""
    uid = "9600001111"
    key = private_session_key(uid)
    clocks = _Clocks()
    cfg = _config(tmp_path)
    del cfg.bot_addressing_preferences_db_path  # SimpleNamespace 上摘掉这一枚
    engine = _engine(clocks)
    assert engine.apply_manual(
        key, "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L2
    ) is True
    _simulate_restart()
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = restarted.route_verdict(key, cfg)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert grants_intimate_narration(verdict["source"]) is False
    assert not (tmp_path / ADDR_DB_NAME).exists()  # 连库都不该建出来


def test_unreadable_store_never_breaks_the_pin(tmp_path: Path) -> None:
    """库打不开（路径指到目录上）⇒ 持久化腿静默缺席，但钉照旧上、判定照旧给。

    家规：读失败 fail-open，绝不因为"记不住"把这一轮回复炸掉。
    """
    uid = "9600001112"
    key = private_session_key(uid)
    clocks = _Clocks()
    cfg = _config(tmp_path, bot_addressing_preferences_db_path=str(tmp_path))
    engine = _engine(clocks)
    assert (
        engine.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MANUAL, tier=INTIMATE_TIER_L1
        )
        is True
    )
    verdict = engine.route_verdict(key, cfg)
    assert verdict["mode"] == "intimate", verdict
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL, verdict


# ---------------------------------------------------------------- ⑤ 注毒自证


def test_poisoning_the_read_leg_turns_case_one_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """摘掉持久化**读腿**（写腿照旧）⇒ ①必红：证明那条断言真的靠读腿活着。

    只毒读腿、不毒写腿是这条自证的要点：库里那一行**确实写进去了**（下面先证一次），
    于是红只能归因到"重钉时没去读"，而不是"数据没落盘"。
    """
    uid = "9600001113"
    tier = INTIMATE_TIER_L2
    key = private_session_key(uid)
    clocks, cfg = _open_explicitly(tmp_path, uid, tier)
    assert _read_back_row(tmp_path, key) == (tier, WALL_AT_OPEN), "写腿没落盘＝自证无效"
    _simulate_restart()

    monkeypatch.setattr(
        ContentRouteEngine, "_honored_explicit_pin", lambda self, **_kw: None
    )  # 毒：读腿熄火
    restarted = _engine(clocks)
    assert (
        restarted.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    poisoned = restarted.route_verdict(key, cfg)
    assert poisoned["source"] == INTIMATE_SOURCE_MASTER_LOVE, poisoned
    assert grants_intimate_narration(poisoned["source"]) is False
    # ①的两条主断言在这一具"没有读腿"的引擎上必须立不起来。
    with pytest.raises(AssertionError):
        assert poisoned["source"] == INTIMATE_SOURCE_MANUAL
    with pytest.raises(AssertionError):
        assert grants_intimate_narration(poisoned["source"]) is True

    # 解毒后同一条路自己就绿了（证明毒是真凶，而不是环境被写坏）。
    monkeypatch.undo()
    _simulate_restart()
    revived = _engine(clocks)
    assert (
        revived.apply_manual(
            key, "intimate", cfg, source=INTIMATE_SOURCE_MASTER_LOVE, tier=INTIMATE_TIER_L1
        )
        is True
    )
    assert revived.route_verdict(key, cfg)["source"] == INTIMATE_SOURCE_MANUAL


# ---------------------------------------------------------------- 键门判据只住中央件


def test_member_and_group_key_forms_never_yield_a_persistable_person_key() -> None:
    """键门本身：只有中央件判为私聊的键才配入库（判据不另立一套）。"""
    assert cr._explicit_pin_person_key(private_session_key("9600001199")) == "9600001199"
    assert cr._explicit_pin_person_key("private_999") == "private_999"
    assert cr._explicit_pin_person_key(build_session_key("9600001040", "111")) == ""
    assert cr._explicit_pin_person_key(group_scope_key(build_session_key("9600001040", "1"))) == ""
    assert (
        cr._explicit_pin_person_key(member_session_key(build_session_key("9600001040", "1"), "2"))
        == ""
    )
    assert cr._explicit_pin_person_key("") == ""


# ---------------------------------------------------------------- 并号（E-1，2026-10-03 裁定）
#
# 她裁「要」：`.env` 里那枚并号别名（左号并入右号）要接到亲密标记这一侧 ⇒ 换个号说话
# 不必重开一次档。四格各钉一件事：①两侧同键（A 开 B 恢复 / B 开 A 恢复）②防过修＝防
# 串档（表里没有的号互不恢复）③**权限向**（并号绝不抬任何闸）④注毒自证（摘掉归并腿
# ⇒ ①必红）。归并算法不在这里重写：那枚真身住 ``reply_policy``，本件只验"接上了没有"。


def _merged_cfg(tmp_path: Path, db_name: str, aliases: dict[str, str] | None = None) -> SimpleNamespace:
    """带别名表的配置面（库另指一只：毒跑／健跑各留一份盘账，互不洗证据）。"""
    return _config(
        tmp_path,
        bot_addressing_preferences_db_path=str(tmp_path / db_name),
        bot_reply_policy_person_aliases=dict(aliases if aliases is not None else MERGED_ALIASES),
    )


def _open_under(cfg: SimpleNamespace, uid: str, tier: str) -> _Clocks:
    """前半段：某号在私聊里显式开档（``chat.py`` 的 manual 腿形状）。"""
    clocks = _Clocks()
    assert _engine(clocks).apply_manual(
        private_session_key(uid),
        "intimate",
        cfg,
        source=INTIMATE_SOURCE_MANUAL,
        tier=tier,
    ) is True
    return clocks


def _restore_under(cfg: SimpleNamespace, clocks: _Clocks, uid: str) -> dict[str, object]:
    """后半段："新进程"里那支自动腿重钉（调用方先 ``_simulate_restart()``）→ 判定读数。"""
    engine = _engine(clocks)
    key = private_session_key(uid)
    assert engine.pinned_mode(key, cfg) is None, "内存没清空＝这具重启是假的"
    assert engine.apply_manual(
        key,
        "intimate",
        cfg,
        source=INTIMATE_SOURCE_MASTER_LOVE,
        tier=INTIMATE_TIER_L1,
    ) is True
    return engine.route_verdict(key, cfg)


@pytest.mark.parametrize(
    "opener,restorer",
    [(SIDE_UID, MAIN_UID), (MAIN_UID, SIDE_UID)],
)
def test_merged_numbers_share_the_mark_across_restart(
    tmp_path: Path, opener: str, restorer: str
) -> None:
    """A 开、B 恢复 ⇒ 沿用；反向同一条格：标记全库只有一行，两个号都读到它。"""
    cfg = _merged_cfg(tmp_path, ADDR_DB_NAME)
    clocks = _open_under(cfg, opener, INTIMATE_TIER_L2)
    # 读写同口：落盘键＝归并后那一把（主号）；侧号键下不许有第二行（第二真身＝撤销只撤一半）。
    assert _read_back_row(tmp_path, private_session_key(MAIN_UID)) == (
        INTIMATE_TIER_L2,
        WALL_AT_OPEN,
    )
    assert _read_back_row(tmp_path, private_session_key(SIDE_UID)) == ("", 0.0)

    _simulate_restart()
    verdict = _restore_under(cfg, clocks, restorer)
    assert verdict["source"] == INTIMATE_SOURCE_MANUAL, verdict
    assert verdict["tier"] == INTIMATE_TIER_L2, verdict
    assert grants_intimate_narration(str(verdict["source"])) is True


def test_unmerged_numbers_never_recover_each_others_mark(tmp_path: Path) -> None:
    """防过修＝防串档：别名表里没有的号，谁也不许凭对方的标记进档。"""
    cfg = _merged_cfg(tmp_path, ADDR_DB_NAME)
    clocks = _open_under(cfg, SIDE_UID, INTIMATE_TIER_L2)
    _simulate_restart()
    verdict = _restore_under(cfg, clocks, UNRELATED_UID)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    assert grants_intimate_narration(str(verdict["source"])) is False
    assert _read_back_row(tmp_path, private_session_key(UNRELATED_UID)) == ("", 0.0)


def test_merging_numbers_grants_no_privilege(tmp_path: Path) -> None:
    """并号只并"标记存到哪一行"：露骨放行/黑名单/键门一律按**原始 sender 号**判。"""
    cfg = _merged_cfg(
        tmp_path,
        ADDR_DB_NAME,
        {SIDE_UID: MAIN_UID},
    )
    cfg.bot_content_route_private_whitelist = [SIDE_UID]
    assert cr.explicit_allowed_for_session("private", "", cfg, sender_id=SIDE_UID) is True
    assert cr.explicit_allowed_for_session("private", "", cfg, sender_id=MAIN_UID) is False
    # 反过来：名单里放主号，侧号也不因此放行（权限面单向都不许）。
    other = _merged_cfg(tmp_path, "other.sqlite3")
    other.bot_content_route_private_whitelist = [MAIN_UID]
    assert cr.explicit_allowed_for_session("private", "", other, sender_id=SIDE_UID) is False
    # 黑名单仍按原始号压住；键门不因并号放大（群作用域键并完仍回空串）。
    blocked = _merged_cfg(tmp_path, "blocked.sqlite3")
    blocked.bot_content_route_private_blacklist = [MAIN_UID]
    assert cr.explicit_allowed_for_session("private", "", blocked, sender_id=MAIN_UID) is False
    group_key = group_scope_key(build_session_key("9600001040", SIDE_UID))
    assert cr._explicit_pin_person_key(group_key, cfg) == ""


def test_canonicalization_is_idempotent_chain_safe_and_fails_open(tmp_path: Path) -> None:
    """形状账：链走到底、定点幂等、认不出/写坏一律原样用（不跨平台折号、不拿脏值猜）。"""
    cfg = _merged_cfg(
        tmp_path,
        ADDR_DB_NAME,
        {"a": "b", "b": "c", "x": "x", "y": "  ", "z": "unknown"},
    )
    assert cr._canonical_person_key("a", cfg) == "c"
    assert cr._canonical_person_key("b", cfg) == "c"
    assert cr._canonical_person_key("c", cfg) == "c"  # 定点：不造出第三种键形
    assert cr._canonical_person_key(cr._canonical_person_key("a", cfg), cfg) == "c"  # 幂等
    assert cr._canonical_person_key("x", cfg) == "x"  # A→A 不自吞
    assert cr._canonical_person_key("y", cfg) == "y"  # 目标为空＝没并
    assert cr._canonical_person_key("z", cfg) == "z"  # 脏目标兜底成 unknown ⇒ 没并（防串档）
    assert cr._canonical_person_key("private_999", cfg) == "private_999"  # 认不出＝原样
    assert cr._canonical_person_key("a", None) == "a"  # 配置缺席
    assert cr._canonical_person_key("", cfg) == ""
    assert cr._canonical_person_key("a", "not-a-config") == "a"  # 读不到表＝原样
    broken = _merged_cfg(tmp_path, "broken.sqlite3", {})
    broken.bot_reply_policy_person_aliases = "not-a-mapping"
    assert cr._canonical_person_key("a", broken) == "a"
    # 键门接的是同一口：表里没有的号原样交回（不因为旁边那两条链被顺手改形状）
    assert cr._explicit_pin_person_key(private_session_key(SIDE_UID), cfg) == SIDE_UID
    merged = _merged_cfg(tmp_path, "merged.sqlite3")
    assert cr._explicit_pin_person_key(private_session_key(SIDE_UID), merged) == MAIN_UID
    assert cr._explicit_pin_person_key(private_session_key(MAIN_UID), merged) == MAIN_UID
    plain = _config(tmp_path)
    del plain.bot_reply_policy_person_aliases
    assert cr._explicit_pin_person_key(private_session_key(SIDE_UID), plain) == SIDE_UID


def test_poisoning_the_merge_leg_turns_the_merged_case_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒自证：摘掉**归并腿** ⇒ 并号那格必红（写落在侧号键、读不再并到主号＝永不相交）。

    毒只熄火归并那一脚，读写两腿照旧落盘，于是红只能归因到"两把键没收成一把"。解毒后
    同一条路自己就绿；表里没有的两个号摘毒前后读数一样（隔壁号没被牵连）。
    """
    monkeypatch.setattr(cr, "_canonical_person_key", lambda person_key, _cfg: person_key)
    poisoned = _merged_cfg(tmp_path, "poisoned.sqlite3")
    clocks = _open_under(poisoned, SIDE_UID, INTIMATE_TIER_L2)
    assert _read_back_row(tmp_path, private_session_key(SIDE_UID), "poisoned.sqlite3") == (
        INTIMATE_TIER_L2,
        WALL_AT_OPEN,
    ), "毒跑没落盘＝自证无效"
    assert _read_back_row(tmp_path, private_session_key(MAIN_UID), "poisoned.sqlite3") == ("", 0.0)
    _simulate_restart()
    verdict = _restore_under(poisoned, clocks, MAIN_UID)
    assert verdict["source"] == INTIMATE_SOURCE_MASTER_LOVE, verdict
    with pytest.raises(AssertionError):
        assert verdict["source"] == INTIMATE_SOURCE_MANUAL

    monkeypatch.undo()
    healthy = _merged_cfg(tmp_path, "healthy.sqlite3")
    hclocks = _open_under(healthy, SIDE_UID, INTIMATE_TIER_L2)
    _simulate_restart()
    assert _restore_under(healthy, hclocks, MAIN_UID)["source"] == INTIMATE_SOURCE_MANUAL
    # 对照：别名表空着的两个号，归并腿在不在都一样（本腿只动"存到哪一行"）。
    plain = _merged_cfg(tmp_path, "plain.sqlite3", {})
    pclocks = _open_under(plain, SIDE_UID, INTIMATE_TIER_L2)
    _simulate_restart()
    assert _restore_under(plain, pclocks, UNRELATED_UID)["source"] == INTIMATE_SOURCE_MASTER_LOVE

