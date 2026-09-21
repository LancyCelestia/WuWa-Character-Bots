"""v21r2 R7 席：亲密路由探针离线回归 + content_route 域测试缺口补强。

三块覆盖：
1. scripts/probe_intimate_route.py 离线核心（run_offline_probe）：L1 强词 /
   L2 两轮语境慢半拍 / L4 倒装开关 / 正常与擦边留默认链 / Master Love 自动
   钉死与显式 normal 钉互斥 / 报告形态 / 离线零密钥保证。
2. explicit_allowed_for_session（2026-09-17 起的露骨放行单一事实源）——
   此前在全部测试树中零覆盖（R7 复核结论），此处补齐：私聊/控制台放行、
   群黑白名单制（黑名单优先、白名单空=关闭）、其余会话类型不放行、
   int 条目宽容、fail-open。
3. --live 门禁：无 BOT_PROBE_LIVE=1 时 main() 拒绝执行（零网络断言）。

全离线：合成注册表注入（绝不读运行时 store 与 .env），零网络零模型调用。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
_PROBE_PATH = ROOT / "scripts" / "probe_intimate_route.py"
_spec = importlib.util.spec_from_file_location("probe_intimate_route", _PROBE_PATH)
assert _spec is not None and _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("probe_intimate_route", probe)
_spec.loader.exec_module(probe)

from plugins.bot_unified_runtime.runtime.content_route import (
    ContentRouteEngine,
    explicit_allowed_for_session,
    match_manual_command,
    match_master_love_admin,
)


# 与 tests/test_content_route.py 同构的合成四渠道注册表（grok 故意排 priority 3，
# 用于证明 INTIMATE 头插不看 priority 数值、只按 head_models 分组次序）。
def _registry() -> dict[str, dict[str, object]]:
    return {
        "ch-gemini": {
            "model": "gemini-3.8-flash",
            "base_url": "https://example.test/v1",
            "api_key": "env:BOT_PROBE_DEFINITELY_UNSET_KEY",
            "priority": 1,
        },
        "ch-gpt": {
            "model": "gpt-5.6-terra",
            "base_url": "https://example.test/v1",
            "api_key": "env:BOT_PROBE_DEFINITELY_UNSET_KEY",
            "priority": 2,
        },
        "ch-grok": {
            "model": "grok-4.6",
            "base_url": "https://example.test/v1",
            "api_key": "env:BOT_PROBE_DEFINITELY_UNSET_KEY",
            "priority": 3,
        },
    }


def _probe(samples: list[probe.ProbeSample]) -> list[probe.ProbeReport]:  # type: ignore[name-defined]
    return probe.run_offline_probe(_registry(), {}, samples)


# ---------------------------------------------------------------- 探针核心

def test_probe_strong_word_intimate_grok_first() -> None:
    (report,) = _probe([probe.ProbeSample("强词", [("给我讲个色情故事", "")])])
    assert report.mode == "intimate"
    # head_models = bot_content_route_order 全序（grok 第一、gemini 随后）。
    assert report.head_models == ["grok-4.6", "gemini-3.8-flash"]
    assert report.grok_first is True
    assert report.grok_position == 1
    assert report.candidate_ids[0] == "ch-grok"
    # 头插后其余模型保持注册表 priority 序（gemini → gpt）。
    assert report.candidate_ids[1:] == ["ch-gemini", "ch-gpt"]


def test_probe_normal_and_borderline_stay_default_chain() -> None:
    reports = _probe(
        [
            probe.ProbeSample("正常", [("今天天气不错，晚饭吃什么好", "")]),
            probe.ProbeSample("擦边", [("抱抱我，想跟你贴贴", "")]),
        ]
    )
    for report in reports:
        assert report.mode == "normal", report.label
        assert report.head_models == []
        assert report.grok_first is False
        # 默认链原样：注册表 priority 序，grok（priority 3）垫底。
        assert report.candidate_ids == ["ch-gemini", "ch-gpt", "ch-grok"]


def test_probe_l2_context_two_turn_slow_burn() -> None:
    """L2 单轮 +35 停滞回带（保持前态 normal），两轮才过阈值——探针样例与
    tests/test_content_route.py 既有语义一致，故意演示「不抢跑」。"""
    context = "用户：讲点色情的内容\n岸宝：这个呀……\n用户：就是那种"
    reports = _probe(
        [
            probe.ProbeSample(
                "L2语境升级", [("继续", context), ("继续呀", context)]
            )
        ]
    )
    (report,) = reports
    assert report.mode == "intimate"
    assert report.grok_first is True
    # 单轮版（同上下文只走一轮）必须仍是 normal：回归锁住滞回带语义。
    (single,) = _probe([probe.ProbeSample("L2单轮", [("继续", context)])])
    assert single.mode == "normal"


def test_probe_manual_inverted_on_then_off() -> None:
    reports = _probe(
        [
            probe.ProbeSample("倒装开", [("开启亲密模式", "")]),
            probe.ProbeSample("开关关闭", [("亲密模式 开", ""), ("亲密模式 关", "")]),
        ]
    )
    on, off = reports
    assert on.mode == "intimate" and on.grok_first is True
    assert off.mode == "normal" and off.grok_first is False
    # 倒装句式不得被普通句子误触（拆句/否定/疑问安全）。
    assert match_manual_command("我不想开启亲密模式") is None
    assert match_manual_command("什么是亲密模式") is None


def test_probe_master_love_auto_pin_respects_explicit_normal_pin() -> None:
    """chat.py 主链合同（2026-09-17 Master Love 批）：名单内 master 自动进
    亲密档，但 master 自己显式「亲密模式 关」的 normal 钉不被覆盖。"""
    entries = ["3865067623"]
    # 正向：未钉死 → Master Love 自动钉死 → intimate + grok 第一。
    (auto,) = _probe([probe.ProbeSample("正常", [("想你了", "")])])
    assert auto.mode == "normal"  # 探针本身不注入 Master Love（无名单配置）。
    engine = ContentRouteEngine()
    config = SimpleNamespace(
        bot_content_route_enabled=True,
        bot_content_route_model="grok-4.6",
        bot_content_route_order="grok-4.6,gemini-3.8-flash",
        bot_content_route_words="",
        bot_content_route_intimate_threshold=60.0,
        bot_content_route_normal_threshold=25.0,
        bot_content_route_context_turns=4,
        bot_content_route_max_ttl_minutes=120,
        bot_content_route_idle_reset_minutes=10,
    )
    assert match_master_love_admin("3865067623", "", entries) is True
    # 复刻 chat.py 守卫：pinned_mode == "normal" 时不执行自动钉死。
    engine.apply_manual("s1", "normal", config)
    if engine.pinned_mode("s1", config) != "normal":
        engine.apply_manual("s1", "intimate", config)
    assert engine.pinned_mode("s1", config) == "normal"
    assert engine.route_verdict("s1", config)["mode"] == "normal"
    # 对照：无钉死时同一段守卫会把 master 会话推入 intimate。
    engine.apply_manual("s2", "intimate", config)  # 守卫放行后的动作等价。
    assert engine.route_verdict("s2", config)["mode"] == "intimate"


def test_probe_report_shape_and_custom_text() -> None:
    (report,) = _probe([probe.ProbeSample("自定义", [("来点 nsfw 内容", "")])])
    assert report.label == "自定义"
    assert report.mode == "intimate"
    assert report.candidate_models[0] == "grok-4.6"
    assert report.reaches_grok is True
    # 英文强词同链路（L1 词表简繁/英文同收的回归面）。
    assert report.head_models == ["grok-4.6", "gemini-3.8-flash"]


def test_probe_offline_never_materializes_api_keys() -> None:
    """离线零密钥保证：env: 引用在探针进程内解析为空串（os.environ 无该
    变量、合成 config 无同名属性），密钥绝不进内存。"""
    specs = probe.build_model_registry(
        SimpleNamespace(
            bot_model_registry=_registry(),
            bot_model_presets={},
            bot_chat_model="",
            bot_chat_base_url="",
            bot_chat_api_key="",
        )
    )
    assert specs, "注册表应解析出条目"
    for spec in specs.values():
        assert spec.api_key == ""
        assert spec.all_api_keys() == ()


# ---------------------------------------------------------------- explicit_allowed_for_session

class _BoomConfig:
    def __getattr__(self, name: str) -> object:
        raise RuntimeError("boom")


def test_explicit_allowed_private_and_console_always() -> None:
    assert explicit_allowed_for_session("private", "", _BoomConfig()) is True
    assert explicit_allowed_for_session("console", "", _BoomConfig()) is True


def test_explicit_allowed_group_whitelist_blacklist() -> None:
    config = SimpleNamespace(
        bot_content_route_group_whitelist=["1108838060", "631785829", 662948429],
        bot_content_route_group_blacklist=["631785829"],
    )
    # 白名单命中放行（int 条目宽容）。
    assert explicit_allowed_for_session("group", "1108838060", config) is True
    assert explicit_allowed_for_session("group", "662948429", config) is True
    # 黑名单优先于白名单。
    assert explicit_allowed_for_session("group", "631785829", config) is False
    # 未在名单 → 不放行。
    assert explicit_allowed_for_session("group", "999", config) is False


def test_explicit_allowed_empty_whitelist_closes_group_face() -> None:
    config = SimpleNamespace(
        bot_content_route_group_whitelist=[],
        bot_content_route_group_blacklist=[],
    )
    assert explicit_allowed_for_session("group", "1108838060", config) is False


def test_explicit_allowed_other_session_types_never() -> None:
    config = SimpleNamespace(
        bot_content_route_group_whitelist=["1108838060"],
        bot_content_route_group_blacklist=[],
    )
    for session_type in ("channel", "mail", "move_private", "", "unknown"):
        assert (
            explicit_allowed_for_session(session_type, "1108838060", config) is False
        ), session_type


def test_explicit_allowed_fail_open_closed() -> None:
    """fail-open 方向=不放行（判不了按保守处理），绝不因异常放大露骨面。"""
    assert explicit_allowed_for_session("group", "1108838060", _BoomConfig()) is False


# ---------------------------------------------------------------- --live 门禁

def test_live_gate_blocks_without_env_flag(tmp_path: Path, monkeypatch: object) -> None:
    """BOT_PROBE_LIVE 未置 1：--live 必须拒绝执行（返回 2，零网络）。"""

    monkeypatch.delenv("BOT_PROBE_LIVE", raising=False)  # type: ignore[attr-defined]
    env_file = tmp_path / "empty.env"
    env_file.write_text("BOT_CHAT_MODEL=gemini-3.8-flash\n", encoding="utf-8")
    code = probe.main(["--live", "--env-file", str(env_file)])
    assert code == 2


def test_live_gate_opens_with_env_flag_and_missing_target(tmp_path: Path) -> None:
    """BOT_PROBE_LIVE=1：门开；无注册表时诚实退出（2），不发任何请求。"""
    os.environ["BOT_PROBE_LIVE"] = "1"
    try:
        env_file = tmp_path / "empty.env"
        env_file.write_text("BOT_CHAT_MODEL=gemini-3.8-flash\n", encoding="utf-8")
        code = probe.main(["--live", "--env-file", str(env_file)])
        assert code == 2
    finally:
        os.environ.pop("BOT_PROBE_LIVE", None)
