"""描写档（narration mode）第三轴的判据锁（席 na1-core，2026-10-04 用户裁定 G-0～G-3）。

要钉住的五件事（裁定原文逐条对上）：

1. **只有两值、缺省只说话**（G-1）：``speech`` / ``scene``，缺省 ``speech``；
   普通模式也能拿 ``scene`` —— 判据**不看亲密档在不在**。
2. **授予面只有一把尺**（G-2）：``narration_pin`` 是 ``_INTIMATE_NARRATION_SOURCES``
   的**第四枚成员**，全仓不长第二张成员表；其余四张来源集（换模型／TTL 豁免／
   缺省浅档／重钉来源）**一个成员都不许跟着动**——本件把这件事单独钉一枚，
   因为它正是台账 #76 立的那条「一枚答两件事」红线。
3. **钉按人不按群**（G-3）：群聊里没钉过的人恒 ``speech``，即便同群有人钉过
   ``scene``，也即便管理员替**整群**拨过亲密档（群作用域键压根没有本人段）。
   写腿的作用域门＝与亲密开关同一个角色集合（群里非管理员拒写），零新表零新键。
4. **跨重启活得住、reset 说得清**（存储面）：两列入现有
   ``addressing_preferences``（owner ``character/addressing.py``），
   「新建引擎实例 + 逐出 providers 缓存」＝重启模拟，先例照
   ``test_intimate_pin_persistence.py`` 的 ``_simulate_restart``。
5. **优先级三格**：本轮明示 > 本人持久钉 > 缺省 ``speech``。本轮那一格不是装饰——
   落库失败（库被占／路径没配）时本轮那句明示仍要生效，钉保持原值（fail-open 面）。

夹具铁律（AGENTS 规则 6／台账 #66★／#76★）：
- 动回复策略 store 的用例一律 monkeypatch ``shared_reply_policy_store`` 到 tmp
  （她的生产偏好库已被别的测试写过两次，再写就是事故）；
- ``bot_addressing_preferences_db_path`` 交**仓库外** tmp 绝对路径；
- ``SHARED_CONTENT_ROUTE_ENGINE._sessions`` 每枚用例换新（进程级单例，群钉会染色）；
- 号全用合成值，绝不抄她的真实 QQ 号。
"""
from __future__ import annotations

import contextlib
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp_module,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
    AddressingPreferenceStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.reply_policy import (
    ReplyPolicyStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import content_route as cr
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    intimate_control as ic,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.content_route import (
    INTIMATE_SOURCE_ADMIN_PIN,
    INTIMATE_SOURCE_AFFINITY,
    INTIMATE_SOURCE_CONTENT_SIGNAL,
    INTIMATE_SOURCE_MANUAL,
    INTIMATE_SOURCE_MASTER_LOVE,
    INTIMATE_SOURCE_NONE,
    INTIMATE_TIER_L2,
    MODE_INTIMATE,
    MODE_NORMAL,
    SHARED_CONTENT_ROUTE_ENGINE,
    ContentRouteEngine,
    grants_intimate_narration,
    member_session_key,
    resolve_intimate_context,
)
from plugins.bot_unified_runtime.domains.core.session_keys import (
    build_session_key,
    group_scope_key,
    person_scope_key,
    private_session_key,
)

ADDR_DB_NAME = "narration_addressing.sqlite3"
_HER_UID = "9600002201"  # 钉了 scene 的人
_BYSTANDER_UID = "9600002202"  # 同群、从没钉过的人
_GROUP = "700000220"
# 🔴 跨平台同号那一族（席 na-review B-1／B-2）：TG 超级群 chat.id 是**负数**，
# 逐成员群键即 `group_-1001…_<tg uid>`；QQ 私聊键是**裸 uid**。两侧同号＝两个人。
_TG_GROUP = "-1001960000220"
_TG_UID = "9600002299"  # TG 上钉的人
_QQ_SAME_UID = _TG_UID  # QQ 上 uin 恰好同号的**另一个人**（QQ 号可自选，实锤攻击面）


# ---------------------------------------------------------------- 夹具


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """进程级单例逐枚用例换新 + 策略 store 结构性指 tmp（绝不碰生产库）。"""
    monkeypatch.setattr(SHARED_CONTENT_ROUTE_ENGINE, "_sessions", OrderedDict())
    store = ReplyPolicyStore(tmp_path / "reply_policy.sqlite3")
    monkeypatch.setattr(rp_module, "shared_reply_policy_store", lambda _config: store)
    with cr._MARKS_WRITTEN_LOCK:
        cr._MARKS_WRITTEN_BY_THIS_PROCESS.clear()


def _config(**overrides: object) -> SimpleNamespace:
    """配置替身（形状照 `test_intimate_pin_persistence._config`，库路径由调用方指 tmp）。"""
    base: dict[str, object] = {
        "bot_addressing_preferences_db_path": "",
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
        "bot_content_route_group_whitelist": [_GROUP],
        "bot_content_route_group_blacklist": [],
        "bot_content_route_private_whitelist": [],
        "bot_content_route_private_blacklist": [],
        "bot_content_route_l1_auto_enabled": False,
        "bot_content_route_l1_auto_min_tier": 1,
        "bot_master_love_enabled": False,
        "bot_master_love_admins": [],
        "bot_reply_policy_enabled": True,
        "bot_reply_detail": "detail",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _addr_config(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    return _config(bot_addressing_preferences_db_path=str(tmp_path / ADDR_DB_NAME), **overrides)


def _restart() -> None:
    """重启模拟：逐出 providers 的进程级 store 缓存（新引擎实例由调用方各造各的）。

    不逐出的话钉仍能从旧连接的进程态里读到，"重启"只清了引擎内存 ⇒ 假绿
    （先例 `test_intimate_pin_persistence._simulate_restart`）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    with providers._ADDRESSING_STORES_LOCK:
        stale = list(providers._ADDRESSING_STORES.values())
        providers._ADDRESSING_STORES.clear()
    for store in stale:
        with contextlib.suppress(Exception):
            store._conn.close()
    with cr._MARKS_WRITTEN_LOCK:
        cr._MARKS_WRITTEN_BY_THIS_PROCESS.clear()


def _disk_pin(
    tmp_path: Path,
    sender: str,
    *,
    session_type: str = "private",
    session_id: str = "",
) -> tuple[str, float]:
    """绕开引擎与共享缓存，直接从**盘**上读那一格（证明真落盘／真清盘）。

    作用域两格由调用方**写死字面量**交进来（I-2 之后钉按 (平台域, 会话, 人) 落行）：
    量具不许反手去叫生产那把取键口要什么三元组——那样它只能证明"自己和自己一致"，
    钉错行这一族就永远看不见。
    """
    store = AddressingPreferenceStore(tmp_path / ADDR_DB_NAME)
    try:
        return store.get_narration_pin(
            session_type=session_type, session_id=session_id, sender_id=sender
        )
    finally:
        store._conn.close()


def _resolve(
    cfg: SimpleNamespace,
    *,
    sender: str = _HER_UID,
    session_key: str = "",
    session_type: str = "private",
    group_id: str = "",
    turn: str = "",
    platform: str = "",
    engine: ContentRouteEngine | None = None,
) -> dict[str, Any]:
    """读数口正身：缺省拿"本人私聊键"，群侧的逐成员键由中央件构造。

    `platform` 缺席＝**没接线的那一面**（今日 `chat.py` 的三个调用点都拿不到平台事实）⇒
    取键口必须 fail-closed，绝不反解群键。
    """
    key = session_key or (
        build_session_key(group_id, sender)
        if session_type == "group"
        else private_session_key(sender)
    )
    return resolve_intimate_context(
        engine or SHARED_CONTENT_ROUTE_ENGINE,
        session_type=session_type,
        group_id=group_id,
        sender_id=sender,
        session_key=key,
        config=cfg,
        turn_narration_mode=turn,
        platform=platform,
    )


def _narration_leg(
    sub: str,
    cfg: SimpleNamespace,
    *,
    sender: str = _HER_UID,
    session_type: str = "private",
    group_id: str = "",
    roles: list[str] | None = None,
    platform: str = "",
    session_key: str = "",
) -> Any:
    """命令面真入口（`/bot narration` 那一族：剥掉前缀后的参数串）。"""
    key = session_key or (
        build_session_key(group_id, sender)
        if session_type == "group"
        else private_session_key(sender)
    )
    return ic.build_narration_control_result(
        config=cfg,
        request_id=f"req-narration-{sub or 'bare'}-{sender}",
        subcommand=sub,
        session_type=session_type,
        session_key=key,
        sender_id=sender,
        group_id=group_id,
        sender_roles=list(roles if roles is not None else ["user", "admin", "super_admin"]),
        platform=platform,
    )


# ---------------------------------------------------------------- ① 值轴与归一


def test_narration_mode_axis_has_exactly_two_values_and_defaults_to_speech() -> None:
    """两值轴＋缺省：只有 speech/scene 两格，缺省是「只说出口的话」。"""
    assert cr.NARRATION_MODE_DEFAULT == cr.NARRATION_MODE_SPEECH
    assert set(cr.NARRATION_MODES) == {cr.NARRATION_MODE_SPEECH, cr.NARRATION_MODE_SCENE}
    assert cr.NARRATION_MODE_SPEECH != cr.NARRATION_MODE_SCENE


def test_normalize_narration_mode_never_raises() -> None:
    """归一腿：大小写／空白容忍，认不出与空的都落缺省，**绝不抛**。"""
    assert cr.normalize_narration_mode(None) == cr.NARRATION_MODE_DEFAULT
    assert cr.normalize_narration_mode("") == cr.NARRATION_MODE_DEFAULT
    assert cr.normalize_narration_mode("   ") == cr.NARRATION_MODE_DEFAULT
    assert cr.normalize_narration_mode("SPEECH ") == cr.NARRATION_MODE_SPEECH
    assert cr.normalize_narration_mode(" Scene") == cr.NARRATION_MODE_SCENE
    assert cr.normalize_narration_mode("整段场景描写") == cr.NARRATION_MODE_DEFAULT
    assert cr.normalize_narration_mode(12345) == cr.NARRATION_MODE_DEFAULT


# ---------------------------------------------------------------- ② 授予面只有一把尺


def test_narration_pin_is_the_fourth_member_of_the_single_grant_ruler() -> None:
    """``narration_pin`` 进**那张唯一**的授予集，判据照旧只有 `grants_intimate_narration`。"""
    assert cr.INTIMATE_SOURCE_NARRATION_PIN == "narration_pin"
    assert cr.INTIMATE_SOURCE_NARRATION_PIN in cr._INTIMATE_NARRATION_SOURCES
    assert len(cr._INTIMATE_NARRATION_SOURCES) == 4
    assert grants_intimate_narration(cr.INTIMATE_SOURCE_NARRATION_PIN) is True
    # 既有三支一字不动（裁定的"加入第四枚"，不是"换成一枚新的尺"）。
    for source in (INTIMATE_SOURCE_MANUAL, INTIMATE_SOURCE_ADMIN_PIN, INTIMATE_SOURCE_CONTENT_SIGNAL):
        assert grants_intimate_narration(source) is True
    assert cr.grants_intimate_narration is cr.grants_intimate_narration  # 判据本体只有一处


def test_other_four_source_axes_are_untouched_by_the_new_member() -> None:
    """分离锁（台账 #76★／#76 那一族「一枚答两件事」红线）：新成员只进叙述轴。

    换模型／TTL 豁免／缺省浅档／重钉四张集合里**都不许出现** ``narration_pin``：
    钉了描写档不等于换首跳、不等于免 TTL、不等于自动浅档、不等于跨重启沿用。
    """
    pin = cr.INTIMATE_SOURCE_NARRATION_PIN
    assert pin not in cr._MODEL_SWITCH_SOURCES
    assert pin not in cr._MAX_TTL_EXEMPT_SOURCES
    assert pin not in cr._SHALLOW_DEFAULT_SOURCES
    assert pin not in cr._EXPLICIT_PIN_REPIN_SOURCES
    # 四张轴仍是互不相同的对象（没被顺手并成一枚）。
    axes = [
        cr._INTIMATE_NARRATION_SOURCES,
        cr._MODEL_SWITCH_SOURCES,
        cr._MAX_TTL_EXEMPT_SOURCES,
        cr._SHALLOW_DEFAULT_SOURCES,
        cr._EXPLICIT_PIN_REPIN_SOURCES,
    ]
    for i, mine in enumerate(axes):
        for j, other in enumerate(axes):
            if i < j:
                assert mine is not other, f"两轴被并成同一对象：{i}／{j}"
    # 自动腿两支照旧无叙述权（防过修：放宽只走"人亲手钉"这一枚）。
    assert grants_intimate_narration(INTIMATE_SOURCE_MASTER_LOVE) is False
    assert grants_intimate_narration(INTIMATE_SOURCE_AFFINITY) is False
    assert grants_intimate_narration(INTIMATE_SOURCE_NONE) is False


# ---------------------------------------------------------------- ③ 缺省格


def test_default_axis_reading_is_speech_and_grants_nothing(tmp_path: Path) -> None:
    """没钉过也没本轮明示 ⇒ ``speech`` + 不授予（缺省＝只说出口的话）。"""
    cfg = _addr_config(tmp_path)
    ctx = _resolve(cfg)
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SPEECH, ctx
    assert ctx["narration_source"] == INTIMATE_SOURCE_NONE, ctx
    assert grants_intimate_narration(ctx["narration_source"]) is False


def test_resolve_always_carries_both_new_keys_even_when_no_store(tmp_path: Path) -> None:
    """配置没点名这本库 ⇒ 持久腿不存在，但两个键**永远在场**（读侧不许 KeyError）。"""
    ctx = _resolve(_config())
    assert ctx["narration_mode"] == cr.NARRATION_MODE_DEFAULT
    assert ctx["narration_source"] == INTIMATE_SOURCE_NONE
    assert ctx["mode"] == MODE_NORMAL


# ---------------------------------------------------------------- ④ G-1：普通模式也能 scene


def test_scene_pin_grants_narration_with_intimate_mode_off(tmp_path: Path) -> None:
    """G-1：亲密档**关着**也能拿五维——授予来自叙述轴，不看档在不在。"""
    cfg = _addr_config(tmp_path)
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
        )
        is True
    )
    ctx = _resolve(cfg)
    assert ctx["mode"] == MODE_NORMAL, ctx  # 亲密档没开
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SCENE, ctx
    assert ctx["narration_source"] == cr.INTIMATE_SOURCE_NARRATION_PIN, ctx
    assert grants_intimate_narration(ctx["narration_source"]) is True


def test_speech_pin_does_not_grant_even_under_an_intimate_admin_pin(tmp_path: Path) -> None:
    """钉在、但钉的是 ``speech`` ⇒ 交给尺的来源必须是不授予的那一枚（模式写进来源）。"""
    cfg = _addr_config(tmp_path)
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SPEECH, config=cfg
        )
        is True
    )
    ctx = _resolve(cfg)
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SPEECH, ctx
    assert grants_intimate_narration(ctx["narration_source"]) is False
    # 亲密档与叙述档是两轴：管理员的整群钉只上亲密档，描写仍跟着本人的钉走。
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        group_scope_key(build_session_key(_GROUP, _HER_UID)),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_ADMIN_PIN,
        tier=INTIMATE_TIER_L2,
    )
    again = _resolve(cfg)
    assert again["narration_mode"] == cr.NARRATION_MODE_SPEECH, again
    assert grants_intimate_narration(again["narration_source"]) is False


# ---------------------------------------------------------------- ⑤ 跨重启与 reset


def test_pin_survives_a_fresh_engine_instance_and_reset_clears_it(tmp_path: Path) -> None:
    """重启模拟（新引擎实例 + 逐出 store 缓存）钉还在；``reset`` 把它放回缺省。"""
    cfg = _addr_config(tmp_path)
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
        )
        is True
    )
    mode, updated_at = _disk_pin(tmp_path, _HER_UID)
    assert mode == cr.NARRATION_MODE_SCENE and updated_at > 0.0, (mode, updated_at)

    _restart()
    restarted = _resolve(cfg, engine=ContentRouteEngine())
    assert restarted["narration_mode"] == cr.NARRATION_MODE_SCENE, restarted
    assert restarted["narration_source"] == cr.INTIMATE_SOURCE_NARRATION_PIN, restarted

    assert cr.clear_narration_pin(private_session_key(_HER_UID), config=cfg) is True
    assert _disk_pin(tmp_path, _HER_UID) == ("", 0.0)
    after = _resolve(cfg, engine=ContentRouteEngine())
    assert after["narration_mode"] == cr.NARRATION_MODE_DEFAULT, after
    assert grants_intimate_narration(after["narration_source"]) is False


def test_write_and_clear_follow_the_person_within_one_conversation(
    tmp_path: Path,
) -> None:
    """**同一会话**的几种键形必须落进同一格；**跨会话**则各归各（I-2 之后这是两问）。

    🔴 本件初稿把"私聊侧也读到群里那枚钉"当成"按人"的证明——I-2（2026-10-04 21:0x
    「换了会话就需要重新激发」）判的正是那一格 ⇒ 此处**翻向**：私聊与群是两行，不再互认。
    照旧成立的是 **#33★ 那一族**：同一会话里群会话键与成员派生键（`||u:`）必须相交，
    否则就是"写在群键、读在私聊键"两形永不相交。
    ⚠ "跨会话形状归到同一个人"仍只在**平台事实已知**时才存在（把群键反解成裸号＝
    跨平台同号互串，席 na-review B-1）；平台未知时取键口 fail-closed，见 ⑨ 那一节。
    """
    cfg = _addr_config(tmp_path)
    group_key = build_session_key(_GROUP, _HER_UID)
    assert (
        cr.write_narration_pin(
            group_key,
            mode=cr.NARRATION_MODE_SCENE,
            sender_id=_HER_UID,
            config=cfg,
            platform="qq",
        )
        is True
    )
    assert _disk_pin(
        tmp_path,
        person_scope_key("qq", _HER_UID),
        session_type="group",
        session_id=_GROUP,
    )[0] == cr.NARRATION_MODE_SCENE
    # 私聊那一行**没有**这枚钉（I-2：换会话要重开），私聊读数因此落回缺省。
    assert _disk_pin(tmp_path, person_scope_key("qq", _HER_UID)) == ("", 0.0)
    assert (
        _resolve(cfg, platform="qq")["narration_mode"] == cr.NARRATION_MODE_SPEECH
    ), _resolve(cfg, platform="qq")
    # 同一会话的成员派生键（||u:）⇒ 必须读到同一枚钉：拆段只经既有 `split_member_session_key`。
    member_key = member_session_key(group_key, _HER_UID)
    ctx = _resolve(
        cfg, session_type="group", group_id=_GROUP, session_key=member_key, platform="qq"
    )
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SCENE, ctx
    # 同会话的另一形（群会话键本身，不带 `||u:`）⇒ 同一枚钉。两形不相交＝#33★ 复发。
    same = _resolve(
        cfg,
        session_type="group",
        group_id=_GROUP,
        sender=_HER_UID,
        session_key=group_key,
        platform="qq",
    )
    assert same["narration_mode"] == cr.NARRATION_MODE_SCENE, same


# ---------------------------------------------------------------- ⑥ 优先级三格


def test_this_turn_command_beats_the_durable_pin(tmp_path: Path) -> None:
    """本轮明示压过持久钉（两个方向都钉：scene 钉 + 本轮 speech；speech 钉 + 本轮 scene）。"""
    cfg = _addr_config(tmp_path)
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
        )
        is True
    )
    downgraded = _resolve(cfg, turn=cr.NARRATION_MODE_SPEECH)
    assert downgraded["narration_mode"] == cr.NARRATION_MODE_SPEECH, downgraded
    assert grants_intimate_narration(downgraded["narration_source"]) is False

    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SPEECH, config=cfg
        )
        is True
    )
    upgraded = _resolve(cfg, turn=cr.NARRATION_MODE_SCENE)
    assert upgraded["narration_mode"] == cr.NARRATION_MODE_SCENE, upgraded
    assert grants_intimate_narration(upgraded["narration_source"]) is True
    # 本轮那一格认不出＝不表态，不许把钉悄悄顶成缺省（这一枚钉的是 scene）。
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
        )
        is True
    )
    shrug = _resolve(cfg, turn="随便写点什么吧")
    assert shrug["narration_mode"] == cr.NARRATION_MODE_SCENE, shrug
    assert shrug["narration_source"] == cr.INTIMATE_SOURCE_NARRATION_PIN, shrug


def test_turn_command_without_any_store_leg_still_takes_effect(tmp_path: Path) -> None:
    """落库腿不存在（配置没给库路径）时本轮明示仍生效——写失败不许升级成"这一轮不算"。"""
    ctx = _resolve(_config(), turn=cr.NARRATION_MODE_SCENE)
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SCENE, ctx
    assert grants_intimate_narration(ctx["narration_source"]) is True


def test_pin_beats_default(tmp_path: Path) -> None:
    """钉 > 缺省：没本轮明示时，持久钉决定读数。"""
    cfg = _addr_config(tmp_path)
    assert _resolve(cfg)["narration_mode"] == cr.NARRATION_MODE_DEFAULT
    assert (
        cr.write_narration_pin(
            private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
        )
        is True
    )
    assert _resolve(cfg)["narration_mode"] == cr.NARRATION_MODE_SCENE


# ---------------------------------------------------------------- ⑦ G-3：群里按人、不广播


def test_group_member_who_never_pinned_gets_speech(tmp_path: Path) -> None:
    """同群两个人：钉过的人 scene、没钉过的人恒 speech（钉按人，不是全群广播）。"""
    cfg = _addr_config(tmp_path)
    assert (
        cr.write_narration_pin(
            build_session_key(_GROUP, _HER_UID),
            mode=cr.NARRATION_MODE_SCENE,
            sender_id=_HER_UID,
            config=cfg,
            platform="qq",
        )
        is True
    )
    hers = _resolve(
        cfg, session_type="group", group_id=_GROUP, sender=_HER_UID, platform="qq"
    )
    bystander = _resolve(
        cfg, session_type="group", group_id=_GROUP, sender=_BYSTANDER_UID, platform="qq"
    )
    assert hers["narration_mode"] == cr.NARRATION_MODE_SCENE, hers
    assert bystander["narration_mode"] == cr.NARRATION_MODE_SPEECH, bystander
    assert grants_intimate_narration(bystander["narration_source"]) is False
    # 管理员替**整群**拨亲密档 ⇒ 也不广播描写档：群作用域键没有本人段，读不到任何钉。
    SHARED_CONTENT_ROUTE_ENGINE.apply_manual(
        group_scope_key(build_session_key(_GROUP, _BYSTANDER_UID)),
        MODE_INTIMATE,
        cfg,
        source=INTIMATE_SOURCE_ADMIN_PIN,
        tier=INTIMATE_TIER_L2,
    )
    still = _resolve(
        cfg, session_type="group", group_id=_GROUP, sender=_BYSTANDER_UID, platform="qq"
    )
    assert still["narration_mode"] == cr.NARRATION_MODE_SPEECH, still
    assert grants_intimate_narration(still["narration_source"]) is False


# ---------------------------------------------------------------- ⑧ 命令面


def test_match_narration_subcommand_three_states_and_show_stays_out() -> None:
    """解析口三态：两值／reset（空串）／认不出（None）；``show`` 有意不在词表里。"""
    assert cr.match_narration_subcommand("scene") == cr.NARRATION_MODE_SCENE
    assert cr.match_narration_subcommand(" SPEECH ") == cr.NARRATION_MODE_SPEECH
    assert cr.match_narration_subcommand("reset") == ""  # 空串＝收回钉，与 None 分家
    assert cr.match_narration_subcommand("show") is None  # 只读：给它任何档＝顺手改档
    assert cr.match_narration_subcommand("xu") is None
    assert cr.match_narration_subcommand("") is None
    # 词面纪律（G-0 乙）：**只有英文子命令**，中文整句不在这张表里——开关面那两族的
    # docstring 都写明"命令面走英文子命令、人格口语面走中文整句，两套词面互不引用"，
    # 给描写档另塞中文别名＝新造第三族词面（本波未裁词面，做了就是越权）。
    assert cr.match_narration_subcommand("只说话") is None
    assert cr.match_narration_subcommand("场景") is None


def test_scene_source_is_the_new_member_and_never_borrows_manual(tmp_path: Path) -> None:
    """G-2 的负面清单：本轮明示与持久钉都交 `narration_pin`，**绝不借 `manual_command`**。

    借了就是把"本轮说了描写"与"本轮开了亲密"混成一件事，而分离锁只比集合成员、
    看不见是谁把哪枚塞进去的 ⇒ 全绿也不会响（席 narrlock 点名过的"假保证"）。
    """
    cfg = _addr_config(tmp_path)
    turn = _resolve(cfg, turn=cr.NARRATION_MODE_SCENE)
    assert turn["narration_source"] == cr.INTIMATE_SOURCE_NARRATION_PIN, turn
    assert cr.write_narration_pin(
        private_session_key(_HER_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
    ) is True
    pinned = _resolve(cfg)
    assert pinned["narration_source"] == cr.INTIMATE_SOURCE_NARRATION_PIN, pinned
    assert turn["narration_source"] == pinned["narration_source"]
    assert INTIMATE_SOURCE_MANUAL not in {
        turn["narration_source"],
        pinned["narration_source"],
    }



def test_command_leg_writes_the_pin_and_show_is_read_only(tmp_path: Path) -> None:
    """开关腿落钉＋回执说人话；``show`` 只读（回显模式/依据/授予），一个字都不改。"""
    cfg = _addr_config(tmp_path)
    scene = _narration_leg("scene", cfg)
    assert scene is not None and "narration_pin" not in scene.body, scene
    assert cr.read_narration_pin(private_session_key(_HER_UID), config=cfg) == (
        cr.NARRATION_MODE_SCENE
    )

    shown = _narration_leg("show", cfg)
    assert "scene" not in shown.body, shown.body  # 内部码串绝不外端（命令面红线①）
    # `show` 必须回三格：当前档＋依据＋授予开没开（裁定 G-0 乙那一格的原文要求）。
    assert "描写档：" in shown.body and "依据：" in shown.body, shown.body
    assert "细节描写：已开" in shown.body, shown.body
    assert cr.read_narration_pin(private_session_key(_HER_UID), config=cfg) == (
        cr.NARRATION_MODE_SCENE
    )
    assert "slash_narration:show" in (shown.audit_tags or [])

    reset = _narration_leg("reset", cfg)
    assert "slash_narration:reset" in (reset.audit_tags or [])
    assert cr.read_narration_pin(private_session_key(_HER_UID), config=cfg) == ""

    # 认不出：回"不认得"＋用法，什么都不改（绝不拿一个错字悄悄顶成某一格）。
    unknown = _narration_leg("xu", cfg)
    assert "slash_narration:unknown" in (unknown.audit_tags or []), unknown
    assert "xu" in unknown.body and "没认出" in unknown.body, unknown.body
    assert cr.read_narration_pin(private_session_key(_HER_UID), config=cfg) == ""
    bare = _narration_leg("", cfg)
    assert "slash_narration:usage" in (bare.audit_tags or []), bare
    assert ic.INTIMATE_HELP_POINTER in bare.body, bare.body


def test_non_admin_in_group_cannot_write_the_pin(tmp_path: Path) -> None:
    """G-3 的写腿门＝亲密开关同一个角色集合：群里非管理员一律拒，钉不落库。"""
    cfg = _addr_config(tmp_path)
    refused = _narration_leg(
        "scene", cfg, sender=_BYSTANDER_UID, session_type="group", group_id=_GROUP,
        roles=["user"], platform="qq",
    )
    assert "slash_narration_refused" in (refused.audit_tags or []), refused
    assert refused.body and "narration_pin" not in refused.body
    assert cr.read_narration_pin(
        build_session_key(_GROUP, _BYSTANDER_UID),
        sender_id=_BYSTANDER_UID,
        config=cfg,
        platform="qq",
    ) == ""
    ctx = _resolve(
        cfg, session_type="group", group_id=_GROUP, sender=_BYSTANDER_UID, platform="qq"
    )
    assert ctx["narration_mode"] == cr.NARRATION_MODE_SPEECH, ctx
    # 同一条命令换成管理员就上得到（群里"她自己开的"这一格才是门后那条路）。
    allowed = _narration_leg(
        "scene", cfg, sender=_HER_UID, session_type="group", group_id=_GROUP,
        roles=["user", "admin"], platform="qq",
    )
    assert "slash_narration_refused" not in (allowed.audit_tags or []), allowed
    assert cr.read_narration_pin(
        build_session_key(_GROUP, _HER_UID),
        sender_id=_HER_UID,
        config=cfg,
        platform="qq",
    ) == cr.NARRATION_MODE_SCENE


def test_private_self_service_needs_no_admin_role(tmp_path: Path) -> None:
    """G-3 只收群侧：私聊里本人给自己钉，不吃角色门（自助偏好仅本人，同 #66 口径）。"""
    cfg = _addr_config(tmp_path)
    leg = _narration_leg("scene", cfg, roles=["user"])
    assert "slash_narration_refused" not in (leg.audit_tags or []), leg
    assert cr.read_narration_pin(private_session_key(_HER_UID), config=cfg) == (
        cr.NARRATION_MODE_SCENE
    )


def test_narration_authority_predicate_is_the_group_only_gate() -> None:
    """作用域判据只一枚：群侧看角色、非群侧放开（命令面不许自己再抄一份 set 判断）。"""
    assert cr.narration_write_allowed(session_type="group", sender_roles=["user"]) is False
    assert cr.narration_write_allowed(session_type="group", sender_roles=["admin"]) is True
    assert (
        cr.narration_write_allowed(session_type="group", sender_roles=["super_admin"]) is True
    )
    assert cr.narration_write_allowed(session_type="group", sender_roles=None) is False
    assert cr.narration_write_allowed(session_type="private", sender_roles=["user"]) is True
    assert cr.narration_write_allowed(session_type="private", sender_roles=None) is True


# ---------------------------------------------------------------- ⑨ 取键口按平台分桶
#
# 席 na-review（2026-10-04）B-1／B-2 的回归锁。病根＝`_narration_person_key` 的群分支
# 拿 `private_session_key(uid)` **反解**重拼本人键：TG 群键 `group_-1001_<uid>` 与 QQ
# 私聊裸键 `<uid>` 折成同一段 ⇒ 两个平台上同号的**陌生人**共用一枚钉、且谁也清不掉自己
# 那枚（清的是同一只桶）。这是本项目在册的两条老账合咬：
# `project-platform-scoped-privilege-judgment`（判定按 (平台域, sender_id)，缺平台＝
# fail-closed 当普通用户）与台账 #76/T-1 `project-t1-intimate-pin-keying-20260927`
# （键形只准复用 `domains/core/session_keys` 的单一构造，禁在任何域内自拼第二形）。
# 同文件 `_explicit_pin_person_key` 的 docstring 逐字写过"不反解"这一条。


def test_platform_blind_group_key_fails_closed_and_never_folds_into_bare_uid(
    tmp_path: Path,
) -> None:
    """拿不到平台事实时**绝不反解**：群侧取不到本人键＝没有这条腿，而不是折成裸号。

    平台未知时唯一允许的键形＝私聊会话键本身（D-1 那一口）。把群键的 user_id 段折成
    裸号＝跨平台同号互串，正是 B-1 的成因，所以这一支必须整体拒绝（fail-closed）。
    """
    cfg = _addr_config(tmp_path)
    tg_group_key = build_session_key(_TG_GROUP, _TG_UID)  # group_-1001…_<tg uid>
    # ① 群键（无平台）写不下去 ⇒ 不存在"悄悄落在别人的裸号桶上"
    assert cr.write_narration_pin(
        tg_group_key, mode=cr.NARRATION_MODE_SCENE, sender_id=_TG_UID, config=cfg
    ) is False
    # ② QQ 上同号的另一个人（裸私聊键）读不到任何东西
    assert cr.read_narration_pin(private_session_key(_QQ_SAME_UID), config=cfg) == ""
    # ③ 反向同判：QQ 裸键上钉着（私聊面合法）⇒ 群侧无平台读数**不许**继承那一枚
    assert cr.write_narration_pin(
        private_session_key(_QQ_SAME_UID), mode=cr.NARRATION_MODE_SCENE, config=cfg
    ) is True
    assert cr.read_narration_pin(tg_group_key, sender_id=_TG_UID, config=cfg) == ""
    assert (
        _resolve(
            cfg,
            session_type="group",
            group_id=_TG_GROUP,
            sender=_TG_UID,
            session_key=tg_group_key,
        )["narration_mode"]
        == cr.NARRATION_MODE_SPEECH
    )


def test_cross_platform_same_uid_never_shares_a_narration_bucket(tmp_path: Path) -> None:
    """平台事实齐备时也只认同域：TG 群里钉的档，QQ 上同号的另一个人读不到、也清不掉。"""
    cfg = _addr_config(tmp_path)
    tg_group_key = build_session_key(_TG_GROUP, _TG_UID)
    assert cr.write_narration_pin(
        tg_group_key,
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) is True
    assert _disk_pin(
        tmp_path, person_scope_key("telegram", _TG_UID), session_type="group", session_id=_TG_GROUP
    )[0] == (cr.NARRATION_MODE_SCENE)
    # QQ 同号者：平台域不同 ⇒ 两只桶，互不可见（授予面也就绝不被她"继承"）。
    assert cr.read_narration_pin(
        private_session_key(_QQ_SAME_UID), config=cfg, platform="qq"
    ) == ""
    assert (
        _resolve(cfg, sender=_QQ_SAME_UID, platform="qq")["narration_source"]
        == INTIMATE_SOURCE_NONE
    )
    # 她 reset 只清自己那只桶：TG 那位仍然铺开着（"谁也清不掉自己那枚"这一格就此闭合）。
    assert cr.clear_narration_pin(
        private_session_key(_QQ_SAME_UID), config=cfg, platform="qq"
    ) is True
    assert cr.read_narration_pin(
        tg_group_key, sender_id=_TG_UID, config=cfg, platform="telegram"
    ) == cr.NARRATION_MODE_SCENE


def test_pin_is_keyed_by_conversation_and_person_not_by_person_alone(
    tmp_path: Path,
) -> None:
    """I-2（2026-10-04 21:0x，**覆盖本件初稿的 B-2 推论**）：钉的键形＝(平台域, 会话, 这个人)。

    她原话：「'跟着人走'的意思就是，在这个会话里面跟着这个人走，A 和 B 采取不同的措施……
    换了会话就需要重新激发。比如在群 A，用户 A 跟 BOT 说'开场景模式'；到了群 B，用户 A
    就还得再问一次、再开一次。」
    ⇒ 本件初稿钉的那条"同一人同平台的两枚会话形状归一把桶"（私聊钉 ⇒ 她自己的群读得到）
    被这条裁定**推翻**——那是"开一次处处跟随"的会话级扩散，正是她要收掉的一格。
    ⚠ 只翻**会话**这一腿：平台域那一腿（B-1 的跨平台同号隔离）一字未动，仍由上面两枚用例钉着。
    """
    cfg = _addr_config(tmp_path)
    tg_private = f"private_{_TG_UID}"  # TG 私聊键形＝private_<chat.id>（中央件 docstring）
    assert cr.write_narration_pin(
        tg_private, mode=cr.NARRATION_MODE_SCENE, sender_id=_TG_UID, config=cfg,
        platform="telegram",
    ) is True
    # 私聊里钉的那一格，只在私聊这一路读得到（本人自助那条腿不许被会话腿带丢）。
    assert cr.read_narration_pin(
        tg_private, sender_id=_TG_UID, config=cfg, platform="telegram"
    ) == cr.NARRATION_MODE_SCENE
    # 她自己的 TG 群 ⇒ **读不到**：换了会话，就得在群里重开一次（换掉的正是"归一把桶"那一格）。
    assert cr.read_narration_pin(
        build_session_key(_TG_GROUP, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == ""
    # 群 A 开了 ⇒ 同一个人到群 B 仍要重开（两把群键＝两个会话桶）。
    other_tg_group = "-1001960000221"
    assert cr.write_narration_pin(
        build_session_key(_TG_GROUP, _TG_UID),
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) is True
    assert cr.read_narration_pin(
        build_session_key(other_tg_group, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == ""
    # 同一个人**回群 A** ⇒ 照旧读得到（会话内跟着人走，不是逐轮失效）。
    assert cr.read_narration_pin(
        build_session_key(_TG_GROUP, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == cr.NARRATION_MODE_SCENE
    # 群 B 里重开一次 ⇒ 群 B 从此也有（"再问一次、再开一次"就是这条路）。
    assert cr.write_narration_pin(
        build_session_key(other_tg_group, _TG_UID),
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) is True
    assert cr.read_narration_pin(
        build_session_key(other_tg_group, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == cr.NARRATION_MODE_SCENE
    # 收回也是按会话收：清群 B 不许把群 A 与私聊那两格一起带走（写/读/清三段同轴）。
    assert cr.clear_narration_pin(
        build_session_key(other_tg_group, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) is True
    assert cr.read_narration_pin(
        build_session_key(other_tg_group, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == ""
    assert cr.read_narration_pin(
        build_session_key(_TG_GROUP, _TG_UID),
        sender_id=_TG_UID,
        config=cfg,
        platform="telegram",
    ) == cr.NARRATION_MODE_SCENE
    assert cr.read_narration_pin(
        tg_private, sender_id=_TG_UID, config=cfg, platform="telegram"
    ) == cr.NARRATION_MODE_SCENE


def test_admin_group_write_pins_the_person_argument_never_the_actor(tmp_path: Path) -> None:
    """写权限轴与取键轴同轴：键**恒随"那个人"**走，绝不悄悄落到操作者自己名下（T-1 病根）。

    G-3 的裁定是"钉按人不按群"：命令面上的 `sender_id` 就是被钉的人（生产接线由
    `message.sender_id` 交进来），所以"管理员替旁人钉"这条路只在她显式交出旁人号时才存在，
    且落的是**旁人**那一格；管理员自己那格纹丝不动。非管理员仍旧一律被角色门挡在写腿外。
    """
    cfg = _addr_config(tmp_path)
    tg_group_key = build_session_key(_TG_GROUP, _BYSTANDER_UID)
    # 管理员在群里，命令面对象是旁人 ⇒ 落旁人的桶，不落管理员自己
    assert cr.write_narration_pin(
        tg_group_key,
        mode=cr.NARRATION_MODE_SCENE,
        sender_id=_BYSTANDER_UID,
        config=cfg,
        platform="telegram",
    ) is True
    assert _disk_pin(
        tmp_path,
        person_scope_key("telegram", _BYSTANDER_UID),
        session_type="group",
        session_id=_TG_GROUP,
    )[0] == (cr.NARRATION_MODE_SCENE)
    assert _disk_pin(
        tmp_path,
        person_scope_key("telegram", _HER_UID),
        session_type="group",
        session_id=_TG_GROUP,
    ) == ("", 0.0)
    # 命令面：群里非管理员还是写不下去（门只看人，与键形无关）
    refused = _narration_leg(
        "scene", cfg, sender=_BYSTANDER_UID, session_type="group", group_id=_TG_GROUP,
        roles=["user"], platform="telegram", session_key=tg_group_key,
    )
    assert "slash_narration_refused" in (refused.audit_tags or []), refused
    assert _disk_pin(
        tmp_path,
        person_scope_key("telegram", _BYSTANDER_UID),
        session_type="group",
        session_id=_TG_GROUP,
    )[0] == (
        cr.NARRATION_MODE_SCENE
    ), "被拒的写腿把旁人的钉顶掉了＝门后还有第二条写路"


def test_narration_person_key_uses_the_central_constructor_and_normalizer(tmp_path: Path) -> None:
    """键形只准出自 `session_keys.person_scope_key`；平台写法归一只准用 `roles.platform_domain_of`。

    这枚是"别再长第五种键形／别写第四张别名表"的形状锁（#76★／#68★ 那族）：
    同域的各种写法（`tg`/`Telegram`）必须归一到同一把键，未知写法一律 fail-closed。
    """
    tg_group_key = build_session_key(_TG_GROUP, _TG_UID)
    expected = person_scope_key("telegram", _TG_UID)
    assert cr._narration_person_key(tg_group_key, _TG_UID, None, platform="telegram") == (
        expected
    )
    assert cr._narration_person_key(tg_group_key, _TG_UID, None, platform="tg") == expected
    assert cr._narration_person_key(tg_group_key, _TG_UID, None, platform=" Telegram ") == (
        expected
    )
    # 未知平台写法＝空域＝不反解（群侧回空串，私聊侧回到 D-1 那一口的会话键本身）。
    assert cr._narration_person_key(tg_group_key, _TG_UID, None, platform="matrix") == ""
    assert cr._narration_person_key("777", "", None, platform="") == "777"
    assert cr._narration_person_key("777", "", None, platform="qq") == person_scope_key(
        "qq", "777"
    )
    # 群作用域键（整群那把）**本身没有本人段** ⇒ 交不出人＝读不出任何钉（G-3 的落点：
    # 管理员替整群拨的亲密档永不广播描写档）。⚠ 这句只在"调用方不传 sender_id"时为真
    # （席 na-review B-2 点名的文档/机理不符）——传了人号就是"按人"那一支，正是钉的语义。
    assert cr._narration_person_key(
        group_scope_key(tg_group_key), "", None, platform="telegram"
    ) == ""
    assert cr._narration_person_key(
        group_scope_key(tg_group_key), "", None, platform=""
    ) == ""


# ---------------------------------------------------------------- ⑪ channel 归群侧
#
# 裁定（用户 2026-10-06「telegram：群侧」）：`channel` 会话形态（Telegram 频道/超级组，
# 会话键形 `channel_<chat.id>`；QQ 频道另一形 `guild_<g>_channel_<c>`）**按群侧判**，
# 不再落进"非群即本人自助"那一支。三处同轴：写腿角色门、I-2 的会话齿、I-3 的公共空间界线。


def test_channel_sessions_are_judged_group_side() -> None:
    """写腿门：channel 与 group 同侧（要 admin/super_admin），private/console 仍本人自助。"""
    assert cr.narration_write_allowed(session_type="group", sender_roles=["user"]) is False
    assert cr.narration_write_allowed(session_type="channel", sender_roles=["user"]) is False
    assert cr.narration_write_allowed(session_type="channel", sender_roles=["admin"]) is True
    assert (
        cr.narration_write_allowed(session_type="channel", sender_roles=["super_admin"]) is True
    )
    assert cr.narration_write_allowed(session_type="private", sender_roles=["user"]) is True
    assert cr.narration_write_allowed(session_type="console", sender_roles=None) is True


def test_channel_pin_gets_its_own_conversation_bucket(tmp_path: Path) -> None:
    """会话齿：频道那一格不与私聊同桶、也不与别的频道同桶（换会话要重开延伸到群侧）。"""
    cfg = _addr_config(tmp_path)
    ch_a = "channel_-1001960000220"
    ch_b = "channel_-1001960000999"
    assert cr.write_narration_pin(
        ch_a, mode=cr.NARRATION_MODE_SCENE, sender_id=_HER_UID, config=cfg,
        platform="telegram",
    ) is True
    assert cr.read_narration_pin(
        ch_a, sender_id=_HER_UID, config=cfg, platform="telegram"
    ) == cr.NARRATION_MODE_SCENE
    # 另一个频道读不到（不同会话＝不同桶）
    assert cr.read_narration_pin(
        ch_b, sender_id=_HER_UID, config=cfg, platform="telegram"
    ) == ""
    # 🔴 私聊读不到频道那一格——修前同一把 ("private","") 桶，这条就是泄漏面
    assert cr.read_narration_pin(
        private_session_key(_HER_UID), config=cfg, platform="telegram"
    ) == ""
    assert cr.clear_narration_pin(
        ch_a, sender_id=_HER_UID, config=cfg, platform="telegram"
    ) is True
    assert cr.read_narration_pin(
        ch_a, sender_id=_HER_UID, config=cfg, platform="telegram"
    ) == ""
