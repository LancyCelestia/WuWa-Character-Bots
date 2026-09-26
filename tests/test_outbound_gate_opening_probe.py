"""出站闸开闸只读探针 `scripts/probe_outbound_gate_opening.py` 的离线用例（席位 S222）。

全离线、零网络、零写文件、零改配置。核心要守住的判断：

- 探针**自带正对照** ⇒ 不许"绿着漏"（一把永远返回 0 的死尺必须被正对照打红）；
- **关闸态跑它也不许假红**（简报硬要求）：闸今天关着，且即便现役目标里掺了脏群号，
  中央出口洗完也不会丢 ⇒ 探针必须报"不丢/咨询"，绝不能因为"构造侧脏"就喊"会丢"——
  那会把一件已经被出口结清的事误报成事故（代理指标型假红）。
- 探针能真的抓到"洗完仍被丢"（比如 daily 族缺日期段）⇒ 证明"会丢"这一路有牙。
- 核心谓词导不进来 ⇒ 退出码 2（不可判），绝不落 0 蒙人。
"""

from __future__ import annotations

import importlib

import pytest

import scripts.probe_outbound_gate_opening as probe
from scripts.probe_outbound_gate_opening import (
    EXIT_ADVISORY,
    EXIT_CLEAN,
    EXIT_HARD_ALARM,
    EXIT_UNDECIDABLE,
    GateNumbers,
    OpenStateVerdict,
    assess_open_state,
    probe_family_raw,
    quiet_window_state,
    render_human,
    run_positive_control,
)

_DATE = "2026-09-24"


def _closed_gate() -> GateNumbers:
    # 手工构一个"关闸态"数值对象，避免单测依赖生产 .env。
    return GateNumbers(
        enabled_today=False,
        enabled_from_config=False,
        env_sets_enabled=False,
        quiet_defer_enabled=True,
        quiet_enabled=True,
        quiet_start="00:00",
        quiet_end="06:00",
        quiet_timezone="UTC",
        config_available=False,
    )


def test_probe_module_loads_and_runs_on_real_tree() -> None:
    """探针在真实树上跑得动、且既不误红也不假判不可判。"""
    g = probe.load_gate_numbers()  # 允许读 Config 失败，只要求不炸
    v = assess_open_state(g, digest_ids=["1108838060"], assist_ids=["3865067623"])
    assert v.undecidable is False
    assert v.positive_control_ok is True
    # 干净目标 ⇒ 不该报"会丢"（3），更不该"不可判"（2）
    assert v.exit_code() in {EXIT_CLEAN, EXIT_ADVISORY}
    assert "线上今天都不生效" in render_human(v)


def test_positive_control_has_teeth() -> None:
    """正对照三事实全真：构造脏 / 洗完过形 / 不洗不过形——缺一即探针失灵。"""
    ok, detail = run_positive_control(_closed_gate())
    assert ok is True, detail
    # 直接证"洗完过形、不洗就不过形"，而不是只信聚合布尔。
    dirty = probe.digest_push_key("湘潭示例群", _DATE)
    assert probe._first_illegal_segment(dirty) is not None
    assert probe._shape_ok(probe.wash_active_push_key(dirty), namespace="digest_push", family="daily")
    assert not probe._shape_ok(dirty, namespace="digest_push", family="daily")


def test_gate_off_state_with_dirty_target_is_not_falsely_red() -> None:
    """关闸态不许假红：闸关着、且现役群号里掺脏中文群号 ⇒ 中央出口洗完不丢 ⇒ 不得判"会丢"。

    这正是简报点名的"代理指标型假红"防线：一个只盯"构造侧脏"就当"开闸必丢"的探针，
    会在今天这个已经结清的理由上喊狼来了。本例锁死：
    · would_drop == 0（洗完都过形）
    · 退出码 != HARD_ALARM
    · 但探针确确实实跑了分析（把脏群号认成了 construction_dirty）——不是"跳过=绿"。
    """
    g = _closed_gate()
    assert g.enabled_today is False  # 前提：今天关着
    v = assess_open_state(
        g,
        digest_ids=["湘潭群", "11 08838060", "9" * 121],
        assist_ids=["用户甲", "user one"],
        today=_DATE,
    )
    assert v.would_drop_count == 0, "洗完仍判会丢 ⇒ 出口洗段没盖住（这才是 3 该响的时机）"
    assert v.construction_dirty_count >= 1, "脏群号没被认出来 ⇒ 探针是空跑的（假绿）"
    assert v.exit_code() == EXIT_ADVISORY
    # 且人话结论把"今天关着不生效"原样写出（未执法不得叙述为已执法）
    text = render_human(v)
    assert "不丢" in text and "线上今天都不生效" in text


def test_probe_detects_real_drop_when_shape_still_fails_after_wash() -> None:
    """'会丢'这一路必须有牙：daily 族缺日期段 ⇒ 洗完段都合法但过不了形 ⇒ would_drop True。"""
    # 少了末段 YYYY-MM-DD 的 daily 键：每段都合法，但 daily 族要求末段是日期
    fp = probe_family_raw(family="digest_push", namespace="digest_push", raw_key="digest_push:grp123")
    assert fp.construction_dirty is False  # 段本身不脏（都是 ASCII）
    assert fp.would_drop is True  # 但过不了 daily 形门 ⇒ 真会被闸 skip
    g = _closed_gate()
    v = OpenStateVerdict(
        gate=g, quiet={}, now_utc=_DATE, families=[fp],
        positive_control_ok=True, positive_control_detail="n/a",
    )
    assert v.exit_code() == EXIT_HARD_ALARM


def test_namespace_mismatch_is_advisory_not_silent_drop() -> None:
    """漏报/错报 namespace（首段 != 申报值）⇒ 会回落比对不过 ⇒ 计入未申报，但经出口仍过形⇒不丢。"""
    # 键首段是 daily_assist，却按 digest_push 申报 ⇒ namespace 不匹配
    fp = probe_family_raw(
        family="digest_push", namespace="digest_push",
        raw_key=f"daily_assist:morning:3865067623:{_DATE}",
    )
    assert fp.namespace_matches_first_segment is False
    assert fp.would_drop is True  # 首段不等 digest_push ⇒ 开闸态这条会被 skip
    g = _closed_gate()
    v = OpenStateVerdict(
        gate=g, quiet={}, now_utc=_DATE, families=[fp],
        positive_control_ok=True, positive_control_detail="n/a",
    )
    # 会丢 ⇒ 硬警（这正是 CM-P-55 说的"漏一族=漏一条静默丢路径"）
    assert v.exit_code() == EXIT_HARD_ALARM


def test_quiet_window_wrap_and_now() -> None:
    """安静窗镜像：跨午夜窗口 + 当前是否在窗内 + 顺延到窗尾。"""
    g = _closed_gate()
    g.quiet_start, g.quiet_end, g.quiet_timezone = "23:00", "07:00", "UTC"
    from datetime import datetime, timezone

    inside = quiet_window_state(g, datetime(2026, 9, 24, 2, 30, tzinfo=timezone.utc))
    assert inside["enabled"] is True and inside["in_window_now"] is True
    assert inside["defer_until_utc"] is not None
    outside = quiet_window_state(g, datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc))
    assert outside["in_window_now"] is False
    # quiet_defer 关 ⇒ 开闸也不因静默窗顺延
    g2 = _closed_gate()
    g2.quiet_defer_enabled = False
    assert quiet_window_state(g2, datetime(2026, 9, 24, 2, 30, tzinfo=timezone.utc))["enabled"] is False


def test_undecidable_when_predicates_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """核心谓词导不进来 ⇒ 退出码 2（不可判），绝不落 0 蒙人。"""
    monkeypatch.setattr(probe, "_PREDICATE_IMPORT_ERROR", "ImportError: simulated")
    v = assess_open_state(_closed_gate(), digest_ids=["x"], assist_ids=["y"])
    assert v.undecidable is True
    assert v.exit_code() == EXIT_UNDECIDABLE
    text = render_human(v)
    assert "不可判" in text


def test_human_output_declares_prediction_not_enforcement() -> None:
    """人话结论必须自证"这是预测、不是现状执法"（未执法不许写成已执法）。"""
    v = assess_open_state(_closed_gate(), digest_ids=["1"], assist_ids=["2"], today=_DATE)
    text = render_human(v)
    assert "若开闸" in text or "离线预测" in text
    assert "顺延 / 每主体限流 / 键形核验 / 闸审计" in text


@pytest.mark.parametrize(
    "mod,key_builder",
    [("digest_push", lambda: probe.digest_push_key("中文", _DATE)),
     ("daily_assist", lambda: probe.daily_assist_key("morning", "用户甲", _DATE))],
)
def test_families_route_through_single_central_wash(mod: str, key_builder) -> None:
    """探针只调用中央 `wash_active_push_key`（唯一真身），不自己长第二套洗段。"""
    src = importlib.reload(probe)
    # 探针里没有本地正则洗段：只有 import 中央 wash 与调用它，绝无 re.sub 洗段的第二实现。
    import inspect

    body = inspect.getsource(src)
    assert "wash_active_push_key" in body
    assert "import re" not in body.split("def ")[0]  # 探针文件头不引 re（不自己写正则洗段）
    # 探针判定确实经中央 wash：构造脏→洗完过形
    fp = probe_family_raw(family=mod, namespace=mod, raw_key=key_builder())
    assert fp.namespace_matches_first_segment is True
    assert fp.construction_dirty is True and fp.would_drop is False
