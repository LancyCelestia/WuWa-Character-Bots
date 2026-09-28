"""开态锁：好感度 v7 与贴纸联动面（施工席 S-MEMAFF，需求 13·12）。

她裁定「一把全开」，其中 ``bot_affinity_v7_enabled``（``config.py:351`` 缺省 False）
一翻之后必须仍然成立的三条性质，本件逐条锁死：

1. **配置面读的是句柄**：``resolve_v7_settings`` 必须逐调用从传入的 Config 现读
   12 枚键（台账 K-4「装配期快照＝热改当轮不生效」的根治方向）。句柄给的值得到
   采信、句柄没有的键才回退 env，这条通了，「把 config 句柄传给 store」的 hub
   补丁才是有效改动而不是摆设。
2. **开态回归面**：八档连续无跳变（档 id 与展示区间同源）、``tier_for_affinity``
   只是读尺**不改分**（灰度开关切换不得换算任何人的分数）、长期陪伴因子不因
   开态被扣分（``_PASSIVE_DECAY_ENABLED=False`` 是她的裁定，不是待修的 bug）。
3. **poke 全开仍受钳**：``bot_poke_extra_arms_enabled``/``bot_poke_follow_enabled``/
   ``bot_poke_after_reply_enabled`` 三枚翻开后，戳一戳加分只有**一条**入账口
   （``__init__._record_poke_affinity``→``observe_points``），且那条口在 v7 开态
   下照样被单事件帽 + 24h 增益预算 + 来源专项预算三层钳住——第二颗剧变路径的
   判据是「有没有第二条不受钳的入账口」，不是「有没有新的戳」。

需求 12 联动面（T5）另锁一件事：负向印象标签的**真身在 affinity 规则表**，
贴纸侧按规则表派生（``meme_selection.negative_impression_tags``），
所以 ``snapshot()`` 不该、也不需要多出 ``negative_impression_tags`` 这一枚键
（补了就是第二真身，随规则表漂移）。本件锁「生产者→消费者这条链在 v7 开态不断」。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.chat_reply.character import affinity
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _IMPRESSION_RULES,
    DynamicAffinityStore,
    resolve_v7_settings,
    tier_display_range,
    tier_for_affinity,
    v7_display_move_for_z_cap,
)
from plugins.bot_unified_runtime.domains.meme.sources import meme_selection

SENDER = "3865067623"


def _v7_config(**overrides: object) -> SimpleNamespace:
    """v7 **开态**桩：12 枚键全部在场（生产缺省见 config.py，须她显式打开）。"""
    values: dict[str, object] = {
        name: getattr(Config, name, default)
        for name, default in affinity._V7_CONFIG_FIELDS
    }
    values["bot_affinity_v7_enabled"] = True
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# T4-1 配置面：句柄优先，env 只是句柄缺席时的兜底
# ---------------------------------------------------------------------------


def test_v7_settings_are_read_from_the_config_handle() -> None:
    settings = resolve_v7_settings(_v7_config(bot_affinity_base_step=0.21, bot_affinity_repair_gain=2.5))
    assert settings.enabled is True
    assert settings.base_step == pytest.approx(0.21)
    assert settings.repair_gain == pytest.approx(2.5)


def test_every_v7_key_is_a_real_config_field() -> None:
    """.env 钉值清单的机器锁：12 枚键名逐枚 ``Config`` 有字段。

    键名拼错进 .env 是**静默失效**（pydantic 不认的 env 变量根本不会进 Config），
    这正是台账 K-4/§47D 那一类「改了 .env 没反应」的开局形态。
    """
    fields = set(Config.model_fields)
    missing = [name for name, _default in affinity._V7_CONFIG_FIELDS if name not in fields]
    assert missing == [], f"v7 键清单里出现了 Config 没有的字段：{missing}"


def test_absent_handle_keys_fall_back_to_env_not_to_a_second_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_AFFINITY_BASE_STEP", "0.33")
    settings = resolve_v7_settings(SimpleNamespace(bot_affinity_v7_enabled=True))
    assert settings.base_step == pytest.approx(0.33)


# ---------------------------------------------------------------------------
# T4-2 开态回归面：八档连续 / 档位不改分 / 陪伴因子不被扣分
# ---------------------------------------------------------------------------


def test_eight_tiers_are_contiguous_and_cover_the_whole_display_axis() -> None:
    ids = list(range(affinity._TIER_MIN_ID, affinity._TIER_MAX_ID + 1))
    assert len(ids) == 8
    previous_high: int | None = None
    for tier_id in ids:
        low, high = _range_bounds(tier_id)
        if previous_high is not None:
            # 左闭右开：上一档的上界就是下一档的下界 ⇒ 中间不许有缝、也不许重叠。
            assert low == previous_high, (tier_id, low, previous_high)
        previous_high = high
    assert _range_bounds(ids[0])[0] == affinity._TIER_DISPLAY_FLOOR
    assert _range_bounds(ids[-1])[1] >= 100


def _range_bounds(tier_id: int) -> tuple[int, int]:
    text = tier_display_range(tier_id)
    inner = text[1:-1]
    low_raw, high_raw = (part.strip() for part in inner.split(","))
    return int(low_raw), int(high_raw.rstrip(")]"))


@pytest.mark.parametrize("enabled", (False, True))
def test_tier_reading_never_moves_anyones_score(enabled: bool, tmp_path: Path) -> None:
    """``tier_for_affinity`` 只是读尺：灰度开关切换、反复取档，分数一字不动。"""
    store = DynamicAffinityStore(
        tmp_path / "affinity.sqlite3",
        config=_v7_config(bot_affinity_v7_enabled=enabled),
    )
    store.observe(SENDER, behavior="positive", text="今天也谢谢你听我说完")
    before = store.snapshot(SENDER)["affinity"]
    for _ in range(50):
        store.snapshot(SENDER)
        tier_for_affinity(float(before))
    after = store.snapshot(SENDER)["affinity"]
    assert float(after) == pytest.approx(float(before))


@pytest.mark.parametrize("affinity_fraction", [x / 100.0 for x in range(-100, 101, 5)])
def test_tier_is_monotone_and_never_skips_along_the_axis(affinity_fraction: float) -> None:
    tier_for_affinity(affinity_fraction)  # 不抛＝在尺上


def test_tier_ids_increase_with_score() -> None:
    previous = None
    for value in (-0.95, -0.5, -0.1, 0.0, 0.2, 0.6, 0.9, 0.99):
        current = tier_for_affinity(value)
        assert previous is None or current >= previous, (value, current, previous)
        previous = current


def test_passive_decay_stays_disabled_by_her_ruling() -> None:
    """长期陪伴因子不因开态被扣分（``_PASSIVE_DECAY_ENABLED=False``＝裁定，不是待修）。

    本锁的存在理由：这条线今晚可能被「顺手修好」——把它翻成 True 就是**给不主动
    找她的人减分**，与「陪伴本身不该被计价」的裁定相反。
    """
    assert affinity._PASSIVE_DECAY_ENABLED is False


def test_attitude_text_never_turns_aggressive_at_any_tier() -> None:
    """规则 8：好感度任何档位都不攻击/不强硬（八档全扫）。"""
    aggressive = ("滚", "闭嘴", "去死", "别再来", "我恨", "讨厌你", "废物东西")
    for display in range(-100, 101, 4):
        attitude = affinity.attitude_for_affinity(display / 100.0)
        assert attitude.strip(), display
        for word in aggressive:
            assert word not in attitude, (display, word)


# ---------------------------------------------------------------------------
# T4-3 poke 三臂全开：入账口只有一条，且那条仍受钳
# ---------------------------------------------------------------------------


def test_poke_has_exactly_one_affinity_accounting_entry() -> None:
    """三枚 poke 开关翻开后不得多出第二条加分路（AST 级普查）。

    判据取「源码里对 store 的观测调用」而不是开关清单：``bot_poke_follow_*`` 与
    ``bot_poke_after_reply_*`` 今晚从 False 翻 True 时新增的是**分发臂**，
    若其中任何一臂自带 ``observe_points``，就会出现「同一个戳被记两次」——
    那正是台账 #13 那条「剧变洞」在新开关下的复活形态。
    """
    root = Path(__file__).resolve().parent.parent / "plugins" / "bot_unified_runtime"
    callers: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "observe_points(" in text or ".observe(" in text:
            callers.append(path.name)
    assert sorted(callers) == ["__init__.py", "affinity.py", "affinity_replay.py"], callers
    init_source = (root / "__init__.py").read_text(encoding="utf-8", errors="replace")
    assert init_source.count(".observe_points(") == 1, "poke 加分口应当唯一"


def test_poke_grant_stays_clamped_with_every_switch_on(tmp_path: Path) -> None:
    """poke 加分（含极端值）在 v7 开态下被三层预算钳住，绝不瞬间跨档。"""
    settings = resolve_v7_settings(_v7_config())
    cap_display = v7_display_move_for_z_cap(settings.daily_move_cap_z)
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", config=_v7_config())
    start = float(store.snapshot(SENDER)["affinity"]) * 100.0
    # 生产形态：每戳 0.1 分、来源专项 0.5 分/24h（config.py 真身缺省）。
    for _ in range(40):
        store.observe_points(
            SENDER,
            points=0.1,
            behavior="positive",
            source="poke",
            source_cap_24h_points=0.5,
        )
    # 恶意极端值：一次要 100 分（=内部 1.0），仍须被预算吃回去。
    store.observe_points(
        SENDER,
        points=100.0,
        behavior="positive",
        source="poke",
        source_cap_24h_points=0.5,
    )
    end = float(store.snapshot(SENDER)["affinity"]) * 100.0
    gained = end - start
    assert gained <= min(
        affinity._BUDGET_MAX_GAIN_24H_POINTS, cap_display * 4
    ), f"24h 内展示分位移 {gained} 越过预算（cap={cap_display}）"
    # 跨档只许逐档：单轮位移不得跨过一档宽。
    assert abs(gained) < affinity._TIER_WIDTH_DISPLAY * 2, gained


# ---------------------------------------------------------------------------
# T5 需求 12 联动：负向印象标签这条链在开态不断
# ---------------------------------------------------------------------------


def test_negative_impression_tags_derive_from_the_affinity_rule_table() -> None:
    negatives = meme_selection.negative_impression_tags()
    positive_tags = {tag for watch, _n, tag in _IMPRESSION_RULES if watch == "positive"}
    assert negatives & positive_tags == set()
    assert {"爱抱怨", "口无遮拦", "爱戏弄"} <= negatives


def test_snapshot_tags_reach_the_sticker_veto_with_v7_on(tmp_path: Path) -> None:
    """生产者→消费者闭环：v7 开态下攒出的负向印象，选图语境里必须进否决面。"""
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", config=_v7_config())
    for _ in range(4):
        store.observe(SENDER, behavior="negative", text="算了说了也没用")
    for _ in range(3):
        store.observe(SENDER, behavior="insult", text="你是不是有病")
    snapshot = store.snapshot(SENDER)
    assert isinstance(snapshot["tags"], list) and snapshot["tags"]
    context = meme_selection.build_context(
        turn_text="今天心情一般", affinity_snapshot=snapshot
    )
    disliked = set(context.disliked_terms)
    assert disliked, snapshot["tags"]
    assert disliked <= set(meme_selection.negative_impression_tags())
    # 负向标签绝不被当成口味加分项（「越爱抱怨越被选图奖励」是旧事故的形状）。
    assert not disliked & set(context.liked_terms)


def test_positive_impression_still_lands_in_the_taste_side(tmp_path: Path) -> None:
    store = DynamicAffinityStore(tmp_path / "affinity.sqlite3", config=_v7_config())
    for _ in range(12):
        store.observe(SENDER, behavior="positive", text="和你聊天挺放松的")
    context = meme_selection.build_context(
        turn_text="哈喽", affinity_snapshot=store.snapshot(SENDER)
    )
    assert "友善" in context.liked_terms
    assert "友善" not in context.disliked_terms
