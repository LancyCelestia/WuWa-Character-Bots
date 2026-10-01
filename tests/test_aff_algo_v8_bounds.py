"""好感度 v8 第二腿·额度与单位纪律锁（S-FIX-AFF-ALGO-R 收编席，2026-09-28）。

对账对象：docs/affinity-design.md §C.2/§C.4 护栏形制 + 实现注释点名
（affinity.py `_clamp_delta_to_rolling_budget` 的 `NOT IN ('v7','v8')` 一行
明文写着「锁 tests/test_aff_algo_v8_bounds.py」——本件即那枚被承诺的锁）。

三族账本互不串币制，是 v7/v8 全部界算术成立的前提：
- v5 滚动预算（分口径 ×100）：只读非 v7/v8 行——一行 z 口径 −0.04 若被
  误读成 −4 分，会把 24h 损失额度（4 分）整段吃掉，v5 用户被 z 行"隔空扣光"；
- v8 滚动位移额度 D（z 口径）：只读 ('v7','v8') 行——flag 切换当日合读更保守
  （只收紧不放宽，§C.4 docstring 在册判据），分口径行绝不计入；
- 窗外（>24h）行两侧都不吃（纯时间窗、重启/跨午夜不重置，v5/v7/v8 同一哲学）。

界与门（v8 执法体）：override 钳 ±κ（权威信号在 v8 下单事件有界语义）；
冷却门 60s 同 v5/v7 语义；refusal 零计分不喂状态；**不设日熔断/兜底帽**
（κ·24h 数学上 ≤ D，堆次数路径已被额度封死——本件 30 连打钉"第 25+ 发照常有位移"）；
终值恒过 `_V8_Z_REPR_DOMAIN` 表示域护栏（近界扫参：只准贴界、绝不过界）。

全部离线：纯 tmp_path 建库 + 注入时钟，不碰 ChatBot_Runtime/，不写源码树 data/。
"""

from __future__ import annotations

import json
import math
import types
from itertools import pairwise

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _INTERACTION_COOLDOWN_SECONDS,
    _V7_CONFIG_FIELDS,
    _V8_CONFIG_FIELDS,
    _V8_DEFAULT_IMPULSE_CAP_Z,
    _V8_Z_REPR_DOMAIN,
    DynamicAffinityStore,
    v7_z_to_display_fraction,
)

_ENV_KEYS = [name.upper() for name, _default in (*_V7_CONFIG_FIELDS, *_V8_CONFIG_FIELDS)]
_TOL = 1e-9
_DAY = 86400.0


@pytest.fixture(autouse=True)
def _isolate_affinity_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _config(**overrides: object) -> types.SimpleNamespace:
    base: dict[str, object] = {}
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _v8_store(tmp_path, clock: _Clock, name: str, **config_over) -> DynamicAffinityStore:
    over = {"bot_affinity_v8_enabled": True}
    over.update(config_over)
    return DynamicAffinityStore(tmp_path / name, clock=clock, config=_config(**over))


def _v5_store(tmp_path, clock: _Clock, name: str) -> DynamicAffinityStore:
    # 空 config ⇒ v7/v8 键走 env 现读（autouse 夹具已剥净）⇒ 代码缺省关 = v5 路。
    return DynamicAffinityStore(tmp_path / name, clock=clock, config=_config())


def _row(store, sender: str):
    with store._lock, store._connect() as connection:
        return connection.execute(
            "SELECT affinity, z_latent, goodwill_anchor, v8_state, day_counters"
            " FROM user_affinity WHERE sender_id = ?",
            (sender,),
        ).fetchone()


def _insert_log(store, sender: str, applied_at: float, delta: float, source: str) -> None:
    with store._lock, store._connect() as connection:
        connection.execute(
            "INSERT INTO affinity_delta_log"
            " (sender_id, bot_id, applied_at, delta, source, source_event_id)"
            " VALUES (?, '', ?, ?, ?, '')",
            (sender, applied_at, delta, source),
        )


def _log_rows(store, sender: str, source: str) -> list:
    with store._lock, store._connect() as connection:
        return connection.execute(
            "SELECT delta FROM affinity_delta_log WHERE sender_id = ? AND source = ?",
            (sender, source),
        ).fetchall()


# =========================================================================
# A. 单位纪律：v5 分口径预算 ⇄ v7/v8 z 口径行，双向不串
# =========================================================================


def test_v5_rolling_budget_ignores_z_unit_rows(tmp_path) -> None:
    """v5 路（缺省关）的 24h 损失额度=4 分；两行 z 口径负增量（source='v7'/'v8'，
    各 −0.04）若被当分口径误读即 −8 分、足以整段吞掉额度。正确形态：v5 事件
    照常吃到**自身单事件帽**下的全额（−0.02 请求被 v5 的 1 分/事件帽钳成 −0.01，
    这是 v5 既有纪律，不是 z 行串币）。锁 `_clamp_delta_to_rolling_budget` 的
    `COALESCE(source,'') NOT IN ('v7','v8')` 一行。"""
    clock = _Clock()
    store = _v5_store(tmp_path, clock, "v5iso.sqlite3")
    store.observe("u5", "positive", text="谢谢你的陪伴")          # 建档
    clock.advance(700)
    now = float(clock())
    _insert_log(store, "u5", now - 600, -0.04, "v7")
    _insert_log(store, "u5", now - 600, -0.04, "v8")
    before = float(_row(store, "u5")["affinity"])
    store.observe("u5", "negative", delta_override=-0.02, text="烦死了")
    after = float(_row(store, "u5")["affinity"])
    assert after == pytest.approx(before - 0.01, abs=1e-12), (
        "z 口径行串进了 v5 分口径预算（−0.02 应吃满 v5 单事件帽 −0.01，竟被吞成 0）"
    )


def test_v5_budget_tooth_point_unit_rows_do_block(tmp_path) -> None:
    """牙（同一判据的反面）：同幅值但**分口径**（source=''，v5 家族）的 −0.04 行
    = −4 分，恰好吃满 24h 损失额度 ⇒ 随后的 −0.02 事件必须被钳到 0。
    若上一条的过滤被注毒成"全读"，这一条与它同向失真，测试网整体即红。"""
    clock = _Clock()
    store = _v5_store(tmp_path, clock, "v5tooth.sqlite3")
    store.observe("u5", "positive", text="谢谢你的陪伴")
    clock.advance(700)
    now = float(clock())
    _insert_log(store, "u5", now - 600, -0.04, "")                 # 分口径 −4 分
    before = float(_row(store, "u5")["affinity"])
    store.observe("u5", "negative", delta_override=-0.02, text="烦死了")
    after = float(_row(store, "u5")["affinity"])
    assert after == pytest.approx(before, abs=1e-12), (
        "分口径行没咬合预算（额度墙形同虚设 ⇒ 本锁失去对照意义）"
    )


def test_v8_daily_budget_consumed_by_v7_rows(tmp_path) -> None:
    """v8 路 D=0.04 现读 ('v7','v8') 行：窗内一行 v7 +0.04 ⇒ 剩余额度归零
    （合读更保守，flag 切换当日不许两套族各吃一份 D）。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8v7read.sqlite3")
    store.observe("u8", "positive", text="谢谢你陪我，太棒了")      # 建档（v8 路，落 v8 行）
    clock.advance(700)
    now = float(clock())
    _insert_log(store, "u8", now - 600, 0.04, "v7")
    z_before = float(_row(store, "u8")["z_latent"])
    rows_before = len(_log_rows(store, "u8", "v8"))
    store.observe("u8", "positive", text="早上好，辛苦你了")
    z_after = float(_row(store, "u8")["z_latent"])
    assert z_after == pytest.approx(z_before, abs=1e-12), (
        "v7 行未进 v8 滚动额度（两族行可各吃一份 D ⇒ 币制合读判据失守）"
    )
    assert len(_log_rows(store, "u8", "v8")) == rows_before, "被拒事件竟落了日志行"


def test_v8_budget_window_is_rolling_not_daily_bucket(tmp_path) -> None:
    """牙（时间窗形制）：同一条 v7 +0.04 行放在 **窗外**（applied_at=now−86401）
    ⇒ 不吃额度，事件照常位移——钉死「自然日桶清零」的旧排程路不得复活。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8window.sqlite3")
    store.observe("u8", "positive", text="谢谢你陪我，太棒了")
    clock.advance(700)
    now = float(clock())
    _insert_log(store, "u8", now - _DAY - 1.0, 0.04, "v7")
    z_before = float(_row(store, "u8")["z_latent"])
    store.observe("u8", "positive", text="早上好，辛苦你了")
    z_after = float(_row(store, "u8")["z_latent"])
    assert z_after > z_before + 1e-9, "窗外行仍被计入（窗口不是滚动 24h）"


def test_v8_budget_ignores_point_unit_rows(tmp_path) -> None:
    """单位纪律的另一半（对称面）：分口径巨幅行（source=''、delta=−0.9）
    绝不计入 v8 的 z 口径额度——否则一行 v5 记账就能把 v8 用户整日冻结。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8ptignore.sqlite3")
    store.observe("u8", "positive", text="谢谢你陪我，太棒了")
    clock.advance(700)
    now = float(clock())
    _insert_log(store, "u8", now - 600, -0.9, "")                  # v5 家族分口径行
    z_before = float(_row(store, "u8")["z_latent"])
    store.observe("u8", "positive", text="早上好，辛苦你了")
    z_after = float(_row(store, "u8")["z_latent"])
    assert z_after > z_before + 1e-9, "分口径行串进了 v8 的 z 口径额度"


# =========================================================================
# B. v8 执法体的界与门
# =========================================================================


def test_v8_override_clamped_to_kappa(tmp_path) -> None:
    """权威信号在 v8 下仍是单事件有界：delta_override=−0.9 ⇒ |Δz| ≤ κ=0.02
    （钳 ±κ 后再乘 γ≤1，只收紧），且真发生了位移（不许钳成空转）。
    override 不喂状态面：v8_state 的 amb 保持零值。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8kappa.sqlite3")
    store.observe("u8", "insult", delta_override=-0.9, text="滚")
    row = _row(store, "u8")
    z_new = float(row["z_latent"])
    z_old = math.atanh(0.1)  # 新用户：v7 惰性映射自 _AFFINITY_BASE=0.1（atanh 单调可逆）
    moved = z_old - z_new
    assert 0.005 < moved <= _V8_DEFAULT_IMPULSE_CAP_Z + _TOL, (
        f"override 位移 {moved} 越出 (0, κ={_V8_DEFAULT_IMPULSE_CAP_Z}]——±κ 钳失效"
    )
    for log_row in _log_rows(store, "u8", "v8"):
        assert abs(float(log_row["delta"])) <= _V8_DEFAULT_IMPULSE_CAP_Z + _TOL
    state = json.loads(str(row["v8_state"]))
    assert float(state["amb"][0]) == 0.0 and float(state["amb"][1]) == 0.0, (
        "override 竟喂了 ambient 状态面（权威信号应零状态副作用）"
    )


def test_v8_cooldown_gate(tmp_path) -> None:
    """冷却门（v5/v7 同语义）：距上次实际计分 <60s ⇒ 记 0；出窗 ⇒ 照计分。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8cool.sqlite3")
    store.observe("u8", "positive", text="谢谢你陪我，太棒了")
    z0 = float(_row(store, "u8")["z_latent"])
    clock.advance(_INTERACTION_COOLDOWN_SECONDS - 30.0)             # 30s：窗内
    store.observe("u8", "positive", text="早上好呀，辛苦你了")
    z1 = float(_row(store, "u8")["z_latent"])
    assert z1 == pytest.approx(z0, abs=1e-12), "冷却窗内仍计分（刷分路径未封）"
    clock.advance(130.0)                                            # 距上次计分 160s
    store.observe("u8", "positive", text="晚安，谢谢你，抱抱")
    z2 = float(_row(store, "u8")["z_latent"])
    assert z2 > z1 + 1e-9, "出冷却窗后事件空转（冷却门误杀正常计分）"


def test_v8_refusal_is_unscored_and_unlogged(tmp_path) -> None:
    """refusal≠信号（V2.1 §2.2 零计分族同源）：不移动 z、不落 v8 日志、不喂状态。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8refuse.sqlite3")
    store.observe("u8", "positive", text="谢谢你陪我，太棒了")
    clock.advance(700)
    before = _row(store, "u8")
    n_before = len(_log_rows(store, "u8", "v8"))
    store.observe("u8", "refusal", text="这个话题我回应不了")
    after = _row(store, "u8")
    assert float(after["z_latent"]) == pytest.approx(float(before["z_latent"]), abs=1e-12)
    assert str(after["v8_state"]) == str(before["v8_state"]), "refusal 竟改写了状态面"
    assert len(_log_rows(store, "u8", "v8")) == n_before


def test_v8_has_no_daily_fuse_day_counters_observe_only(tmp_path) -> None:
    """§C.4 在册豁免：v8 **不设日熔断/兜底帽**——同类 positive 30 连打（D 放宽到
    域钳上限 0.5 以隔离额度因素），第 25 发之后照常有位移（v7 路 fuse=25 会掐死）；
    day_counters 仅观测落账（与 v7 同步律），绝不参与执法。"""
    clock = _Clock()
    store = _v8_store(
        tmp_path, clock, "v8nofuse.sqlite3", bot_affinity_daily_move_cap_z=0.5
    )
    zs: list[float] = []
    for i in range(30):
        store.observe("u8", "positive", text=f"第{i}次陪你聊天太棒了，请多指教，谢谢你")
        zs.append(float(_row(store, "u8")["z_latent"]))
        clock.advance(61.0)
    assert all(b > a + 1e-9 for a, b in pairwise(zs)), (
        "v8 路出现同类掐断（熔断/兜底帽复活——30 发应全部有位移）"
    )
    assert len(_log_rows(store, "u8", "v8")) == 30
    counters = json.loads(str(_row(store, "u8")["day_counters"]))
    assert int(counters.get("positive", 0)) == 30, "day_counters 观测账本失同步"


def test_v8_repr_domain_guard_near_boundary_sweep(tmp_path) -> None:
    """表示域护栏扫参：z 贴界（域内 1e-6/1e-3/0.05）再吃正向 override，
    终值只准贴界 `_V8_Z_REPR_DOMAIN`、绝不过界；展示值 tanh 恒 <1。"""
    clock = _Clock()
    store = _v8_store(tmp_path, clock, "v8domain.sqlite3")
    for idx, offset in enumerate((1e-6, 1e-3, 0.05)):
        sender = f"d{idx}"
        store.observe(sender, "positive", text="谢谢你陪我，太棒了")   # 建档
        z_seed = _V8_Z_REPR_DOMAIN - offset
        with store._lock, store._connect() as connection:
            connection.execute(
                "UPDATE user_affinity SET z_latent = ?, affinity = ? WHERE sender_id = ?",
                (z_seed, v7_z_to_display_fraction(z_seed), sender),
            )
        clock.advance(43201.0)                                        # 出冷却+出建档行的 24h 窗
        store.observe(sender, "positive", delta_override=0.02, text="太棒了")
        row = _row(store, sender)
        z_final = float(row["z_latent"])
        assert z_final <= _V8_Z_REPR_DOMAIN + 1e-12, (
            f"offset={offset}：z 越过表示域 {z_final} > {_V8_Z_REPR_DOMAIN}"
        )
        if offset < _V8_DEFAULT_IMPULSE_CAP_Z:
            # 界内残余 < 单事件最大位移 ⇒ 必被钳到界上（护栏真的在执法，不是摆设）。
            assert z_final == pytest.approx(_V8_Z_REPR_DOMAIN, abs=1e-12)
        assert float(row["affinity"]) < 1.0
