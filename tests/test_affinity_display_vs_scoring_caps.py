"""好感度 F-16 拆轴锁：展示限幅侧与评分判据侧的日额度常量各归各吃（2026-10-06 用户裁定甲案）。

背景（台账 F-16 / HANDBOOK §74.2）：`9bdcfc7` 把共享常量 `_V7_DEFAULT_DAILY_MOVE_CAP_Z`
从 0.12 改成 0.04（当时名义＝「消除双源」对齐 v8 展示收紧值），结果**评分判据**也吃这把
展示侧收紧的尺——同日 4 条好评耗光滚动 24h 预算后，一句辱骂的实发 Δz **恰好 0.0**
（本件 RED 腿 ① 复现的正是这一条）。裁定＝拆轴：评分判据侧回到改动前语义 **0.12**；
展示限幅侧保持收紧现值 **0.04z**（≈4 展示分/日，与 `bound_sentiment_display` 的
`_SENTIMENT_DISPLAY_DAILY_DROP_CAP = 4.0` 分数量尺同源同纪律）。数值归属唯一权威＝
`docs/affinity-design.md`（本件 ④ 锁它的在册登记）。

四腿与变异对应（改任一枚常量的指向，必有一枚当场红）：
①行为腿：无配置缺省形态下，4 条好评后辱骂仍有**非零且方向正确**的位移——现红（0.04 把预算吃干）。
②联锁腿：拆轴后评分缺省 = 0.12 **且** 展示限幅仍按 4.0 分生效（拆轴不许把展示放宽）。
③单源腿：两枚常量值互异、各自只被本侧读点引用；源码级点名「V7Settings 缺省/resolve_v7
   兜底 引用 _V7、V8Settings 缺省/resolve_v8 兜底 引用 _V8、bound_sentiment_display 的
   cap_per_day 引用展示尺」；把评分侧写回共享/展示常量 ⇒ 当场红。
④规范册腿：`docs/affinity-design.md` 就地登记两枚常量与归属（数值只住常量与该文件）。

全部离线 tmp_path + 注入时钟；不触碰生产库；env 卫生沿用 v7 系测试的 autouse delenv。
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import types

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import affinity as _aff
from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _SENTIMENT_DISPLAY_DAILY_DROP_CAP,
    _V7_CONFIG_FIELDS,
    _V7_DEFAULT_DAILY_MOVE_CAP_Z,
    _V8_CONFIG_FIELDS,
    _V8_DEFAULT_DAILY_MOVE_CAP_Z,
    DynamicAffinityStore,
    V7Settings,
    V8Settings,
    resolve_v7_settings,
    resolve_v8_settings,
)

_V7_ENV_KEYS = [name.upper() for name, _default in _V7_CONFIG_FIELDS]
_V8_ENV_KEYS = [name.upper() for name, _default in _V8_CONFIG_FIELDS]

# 拆轴裁定的两枚面值（唯一权威 docs/affinity-design.md 同步在册；此处是执法面而非第二真身）。
_SCORING_CAP_Z = 0.12   # 评分判据侧（v7 路滚动 24h 预算缺省）
_DISPLAY_CAP_Z = 0.04   # 展示限幅侧（v8 日额度 ≈ 4 展示分/日）

_PRAISES = [
    "今天也辛苦了，谢谢你陪我",
    "和你聊天挺开心的",
    "嗯嗯，你人真好",
    "谢谢你的安慰",
]
_INSULT = "你就是个废物，滚开"
_INTERVAL = 90.0  # >60s 同事件冷却，逐条都可计分


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _V7_ENV_KEYS + _V8_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _v7_config_without_daily_key(**overrides: object) -> types.SimpleNamespace:
    """v7 开态桩，**不含** `bot_affinity_daily_move_cap_z` ⇒ 读取路径落到代码缺省常量。"""
    base = {
        "bot_affinity_v7_enabled": True,
        "bot_affinity_base_step": 0.10,
        "bot_affinity_novelty_ratio": 0.90,
        "bot_affinity_novelty_halo_days": 21,
        "bot_affinity_rhythm_reference_turns": 8,
        "bot_affinity_negative_event_cap_z": 0.10,
        "bot_affinity_fuse_daily_events": 25,
        "bot_affinity_repair_gain": 1.4,
        "bot_affinity_z_hard_bound": 0.985,
        "bot_affinity_quality_weights": "",
        "bot_affinity_decay_tau_days": "",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _z_of(store: DynamicAffinityStore, sender: str) -> float:
    with sqlite3.connect(str(store.db_path)) as connection:
        row = connection.execute(
            "SELECT z_latent FROM user_affinity WHERE sender_id = ?", (sender,)
        ).fetchone()
    return float(row[0])


def _v7_delta_rows(store: DynamicAffinityStore, sender: str) -> list[float]:
    with sqlite3.connect(str(store.db_path)) as connection:
        rows = connection.execute(
            "SELECT delta FROM affinity_delta_log"
            " WHERE sender_id = ? AND source = 'v7' ORDER BY applied_at",
            (sender,),
        ).fetchall()
    return [float(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# ① 行为腿（RED 主体）：评分预算的缺省语义下，4 条好评之后辱骂必须照计分。
# ---------------------------------------------------------------------------

def test_scoring_budget_default_still_moves_insult_after_four_praises(tmp_path) -> None:
    """现红复现病理：缺省日额度 0.04z 时首条好评即吃满预算，辱骂实发 Δz 恰好 0.0。

    拆轴后（评分缺省 0.12z）同序列必须：五条全落账、辱骂位移**严格为负**（非零且方向正确）。
    """
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "split_scoring.sqlite3", clock=clock,
        config=_v7_config_without_daily_key(),
    )
    for text in _PRAISES:
        store.observe("u1", "positive", text=text)
        clock.advance(_INTERVAL)

    z_before = _z_of(store, "u1")
    store.observe("u1", "insult", text=_INSULT)
    z_after = _z_of(store, "u1")

    rows = _v7_delta_rows(store, "u1")
    assert len(rows) == 5, f"五条消息应逐条计分落账，实际 {len(rows)} 条（日额度被展示尺吃干则现 0.0）"
    assert rows[-1] < 0.0, f"辱骂位移必须非零且方向为负，实发 {rows[-1]!r}"
    assert z_after < z_before, f"辱骂后 z 未下行（{z_before!r} -> {z_after!r}）＝评分吃了展示尺的病灶"


# ---------------------------------------------------------------------------
# ② 联锁腿：拆轴后评分缺省=0.12，而展示限幅**原样** 4.0 展示分（不许顺手放宽）。
# ---------------------------------------------------------------------------

def test_split_keeps_display_bound_at_four_points_and_scoring_at_012(tmp_path) -> None:
    settings = resolve_v7_settings(_v7_config_without_daily_key())
    assert settings.daily_move_cap_z == pytest.approx(_SCORING_CAP_Z), (
        f"评分判据侧无配置缺省应为 {_SCORING_CAP_Z}z，现为 {settings.daily_move_cap_z!r}"
        "（＝9bdcfc7 混轴残留，F-16 拆轴未完成）"
    )
    # 同一形态下 config=None 的 env 兜底读口必须同值（同一条腿，禁第二把尺）。
    assert resolve_v7_settings(None).daily_move_cap_z == pytest.approx(_SCORING_CAP_Z)

    # 展示轴逐字节原样：下行限幅仍是 4.0 展示分（相对 24h 峰值；上行不限）。
    assert _SENTIMENT_DISPLAY_DAILY_DROP_CAP == pytest.approx(4.0)
    clock = _Clock()
    store = DynamicAffinityStore(
        tmp_path / "split_display.sqlite3", clock=clock,
        config=_v7_config_without_daily_key(),
    )
    assert store.bound_sentiment_display("u1", 90.0) == pytest.approx(90.0)
    assert store.bound_sentiment_display("u1", 20.0) == pytest.approx(86.0), (
        "展示限幅被拆轴顺手动过（应为 90-4=86）"
    )
    # 上行不限：回暖即时可见。
    assert store.bound_sentiment_display("u1", 95.0) == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# ③ 单源腿：两枚常量互异且各归各读点；指向一旦被改回共享 ⇒ 当场红。
# ---------------------------------------------------------------------------

def test_two_cap_constants_are_distinct_single_sources() -> None:
    assert _V7_DEFAULT_DAILY_MOVE_CAP_Z != _V8_DEFAULT_DAILY_MOVE_CAP_Z, (
        "两枚日额度常量同值＝双源未拆（F-16 甲案的判据就是各归各吃）"
    )
    assert _V7_DEFAULT_DAILY_MOVE_CAP_Z == pytest.approx(_SCORING_CAP_Z)
    assert _V8_DEFAULT_DAILY_MOVE_CAP_Z == pytest.approx(_DISPLAY_CAP_Z)

    # 冻结视图缺省各自指各自；v8 无键兜底也必须落在展示侧常量（不引评分尺）。
    assert V7Settings().daily_move_cap_z == _V7_DEFAULT_DAILY_MOVE_CAP_Z
    assert V8Settings().daily_move_cap_z == _V8_DEFAULT_DAILY_MOVE_CAP_Z
    assert resolve_v8_settings(
        _v7_config_without_daily_key()
    ).daily_move_cap_z == _V8_DEFAULT_DAILY_MOVE_CAP_Z

    src = pathlib.Path(_aff.__file__).read_text(encoding="utf-8")

    # 源码级指向锁（防「顺手」把评分侧写回展示侧常量＝真身别名）。
    assert "_V7_DEFAULT_DAILY_MOVE_CAP_Z = _V8" not in src
    assert "_V8_DEFAULT_DAILY_MOVE_CAP_Z = _V7" not in src

    v7_block = src[src.index("class V7Settings"):src.index("def coerce_json_list")]
    v8_block = src[src.index("class V8Settings"):src.index("def resolve_v8_settings")]
    r7_block = src[src.index("def resolve_v7_settings"):src.index("def v7_raw_delta_z")]
    r8_block = src[src.index("def resolve_v8_settings"):src.index("def v8_impulse")]

    assert re.search(
        r"^\s*daily_move_cap_z: float = _V7_DEFAULT_DAILY_MOVE_CAP_Z\s*$", v7_block, re.MULTILINE
    ), "V7Settings 评分缺省必须引用 _V7 常量（引用别的＝第二把尺）"
    assert re.search(
        r"^\s*daily_move_cap_z: float = _V8_DEFAULT_DAILY_MOVE_CAP_Z\s*$", v8_block, re.MULTILINE
    ), "V8Settings 展示收紧侧缺省必须引用 _V8 常量"
    assert re.search(
        r"daily_move_cap_z=positive_float\(\s*\"bot_affinity_daily_move_cap_z\","
        r" _V7_DEFAULT_DAILY_MOVE_CAP_Z\)",
        r7_block,
    ), "resolve_v7_settings 的无键兜底必须落在 _V7 常量"
    assert "_V7_DEFAULT_DAILY_MOVE_CAP_Z" not in r8_block, (
        "v8 读取路径引用了评分侧常量＝混轴回潮"
    )

    # 展示限幅的 cap_per_day 只能引展示尺，绝不引任何一枚 z 域日额度常量。
    bound_block = src[src.index("def bound_sentiment_display"):src.index("def snapshot")]
    assert re.search(
        r"cap_per_day: float = _SENTIMENT_DISPLAY_DAILY_DROP_CAP", bound_block
    ), "bound_sentiment_display 的缺省限幅必须引用展示分尺常量"
    for leaked in ("_V7_DEFAULT_DAILY_MOVE_CAP_Z", "_V8_DEFAULT_DAILY_MOVE_CAP_Z"):
        assert leaked not in bound_block, f"展示限幅读口混入了 z 域日额度常量 {leaked}"


# ---------------------------------------------------------------------------
# ④ 规范册腿：数值归属就地写进唯一权威 `docs/affinity-design.md`。
# ---------------------------------------------------------------------------

def test_affinity_design_doc_registers_the_split_axes() -> None:
    doc = (
        pathlib.Path(__file__).resolve().parents[1] / "docs" / "affinity-design.md"
    ).read_text(encoding="utf-8")
    assert "F-16" in doc, "affinity-design.md 未登记 F-16 拆轴裁定"
    lines = doc.splitlines()
    assert any(
        "_V7_DEFAULT_DAILY_MOVE_CAP_Z" in line and "0.12" in line and "评分" in line
        for line in lines
    ), "评分判据侧常量与 0.12 的归属未在册"
    assert any(
        "_V8_DEFAULT_DAILY_MOVE_CAP_Z" in line and "0.04" in line and "展示" in line
        for line in lines
    ), "展示限幅侧常量与 0.04 的归属未在册"
