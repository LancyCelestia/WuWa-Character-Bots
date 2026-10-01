"""creation 预留面告警生产者（P5-E3）的回归锁：缺位必须**可见**，且不刷屏、不丢件。

取样口径（本文件最重要的三条判据，逐条有对应用例）：
1. **没配 provider ≠ 故障**：只进状态行、不进告警（防"对预留位每 300s 敲一次运维"把真告警埋掉）；
2. **配了 provider 却拿不到适配器 = 故障**：必须产 pending issue 且能被 flush 投出（禁静默失败）；
3. **入队≠送出**的同类形态在此复现于告警面：sink 抛错时**保留** pending（宁可晚到，不可假投）。

全离线：sink 用手写替身，零网络、零真实告警投递、零 root import（root 可达性用 AST 静态锁）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.creation import reserved_health_alert as alert

_PLUGIN_ROOT = Path("plugins/bot_unified_runtime")


class _Config:
    """最小配置替身：只挂探测表关心的三枚键（缺省＝未配）。"""

    def __init__(
        self,
        *,
        image_provider: str = "",
        tts_provider: str = "",
        tts_api_url: str = "",
        ref_audios: list[str] | None = None,
    ) -> None:
        self.bot_creation_image_provider = image_provider
        self.bot_creation_tts_provider = tts_provider
        self.bot_tts_api_url = tts_api_url
        self.bot_tts_ref_audios = ref_audios if ref_audios is not None else []


class _Sink:
    def __init__(self, *, boom: bool = False) -> None:
        self.received: list[OperationalIssue] = []
        self._boom = boom

    def __call__(self, issue: OperationalIssue) -> None:
        if self._boom:
            raise RuntimeError("告警链坏了")
        self.received.append(issue)


@pytest.fixture(autouse=True)
def _isolate() -> Any:
    alert.install_reserved_alert_sink(None)
    alert.install_execution_presence_probe(None)
    alert.reset_state()
    yield
    alert.install_reserved_alert_sink(None)
    alert.install_execution_presence_probe(None)
    alert.reset_state()


# ------------------------- 判据 1：未配 provider 不告警 -------------------------


def test_unconfigured_provider_is_declared_placeholder_not_incident() -> None:
    assert alert.check_reserved_channels(_Config()) == {}
    assert alert.pending_channels() == ()
    line = alert.creation_status_line(_Config())
    assert "reserved" in line and "未接 provider" in line
    # 绝不冒充可用（禁"预留实现"写成"已支持"）。
    assert "available" not in line and "ok" not in line.lower()


def test_status_line_names_no_sink_when_sink_absent() -> None:
    """没接 sink 时状态行必须显式说 no_sink——"有告警面"不等于"已投递"。"""
    cfg = _Config(image_provider="some-provider")
    alert.check_reserved_channels(cfg)  # 先造 pending，确保走的是"要而不得"分支
    alert.install_reserved_alert_sink(None)
    line = alert.creation_status_line(cfg)
    assert "requested_but_missing" in line and "no_sink" in line


# ------------------------- 判据 2：要而不得必须产告警 -------------------------


def test_requested_but_missing_channel_produces_issue() -> None:
    findings = alert.check_reserved_channels(_Config(image_provider="stub-provider"))
    assert "creation.image" in findings
    assert alert.pending_channels() == ("creation.image",)
    line = alert.creation_status_line(_Config(image_provider="stub-provider"))
    assert "requested_but_missing" in line and "creation.image" in line
    assert "sink_ready" not in line  # 本用例未装 sink，不许假装已就绪


def test_flush_delivers_each_issue_once_and_drains() -> None:
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)
    alert.check_reserved_channels(_Config(image_provider="stub-provider"))
    assert alert.flush_reserved_issues_to_alerts() == 1
    assert len(sink.received) == 1
    # drain 后二次 flush 不得重复投（禁双保险变双刷屏）。
    assert alert.flush_reserved_issues_to_alerts() == 0
    assert len(sink.received) == 1


def test_issue_reuses_existing_kind_and_is_redacted() -> None:
    """kind 复用在册的 ``config_missing``（禁新造），摘要必过打码（AGENTS 铁律 3）。"""
    secretish = "stub?token=BOT_TTS_API_KEY=sk-abcdefghijklmnop"
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)
    alert.check_reserved_channels(_Config(image_provider=secretish))
    assert alert.flush_reserved_issues_to_alerts() == 1
    issue = sink.received[-1]
    assert issue.stage == "creation"
    assert issue.kind == "config_missing"
    assert issue.retryable is True
    assert "sk-abcdefghijklmnop" not in issue.safe_summary
    assert "C:\\" not in issue.safe_summary


def test_stale_issue_is_replaced_not_stuck() -> None:
    """键从"已填"回落到"未填" ⇒ 旧 pending 必须撤回，否则恢复后仍会报旧故障。"""
    alert.check_reserved_channels(_Config(image_provider="stub-provider"))
    assert alert.pending_channels() == ("creation.image",)
    alert.check_reserved_channels(_Config())
    assert alert.pending_channels() == ()


# ------------------------- 判据 3：投递失败不许丢件 -------------------------


def test_flush_without_sink_keeps_pending() -> None:
    alert.install_reserved_alert_sink(None)
    alert.check_reserved_channels(_Config(image_provider="stub-provider"))
    assert alert.flush_reserved_issues_to_alerts() == 0
    assert alert.pending_channels() == ("creation.image",)


def test_raising_sink_keeps_pending_and_does_not_bubble() -> None:
    alert.install_reserved_alert_sink(_Sink(boom=True))
    alert.check_reserved_channels(_Config(image_provider="stub-provider"))
    assert alert.flush_reserved_issues_to_alerts() == 0  # 不冒泡、不算投成
    assert alert.pending_channels() == ("creation.image",)  # 件还在，下次还会投


# ------------------------- 装配可达性（AST 静态锁） -------------------------


def test_root_installs_sink_and_echo_flushes() -> None:
    """生产者存在但没人装 sink/没人 flush＝死件（本仓"装配期绿、跑到没投"的同族形态）。"""
    root_src = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    root_tree = ast.parse(root_src)
    installed = [
        node
        for node in ast.walk(root_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "install_reserved_alert_sink"
    ]
    assert len(installed) == 1, f"root 装配点应恰一处，现={len(installed)}"
    # 共用语音那个 sink（同一个中央告警口），不许另造第二条路。
    arg = installed[0].args[0]
    assert isinstance(arg, ast.Name) and arg.id == "_push_probe_issue"

    echo_src = (_PLUGIN_ROOT / "domains/chat_reply/capabilities/echo.py").read_text(
        encoding="utf-8"
    )
    echo_tree = ast.parse(echo_src)
    flushed = [
        node
        for node in ast.walk(echo_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "flush_reserved_issues_to_alerts"
    ]
    assert len(flushed) == 1, f"flush 生产读者应恰一处，现={len(flushed)}"


def test_status_line_is_emitted_before_pinned_tail_lines() -> None:
    """`test_capability_health_readout` 钉死语音行=lines[-2]、健康行=lines[-1]；
    本席新行插在它们之前——这条锁防后来者把新行挪到末尾顶漂那两条既有判据。"""
    src = (_PLUGIN_ROOT / "domains/chat_reply/capabilities/echo.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    target: ast.List | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "creation_status_line"
            for call in ast.walk(node)
        ):
            target = node
            break
    assert target is not None, "状态行列表里找不到 creation 行＝本锁前提失效"
    names = [
        call.func.id
        for call in target.elts
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]
    assert names.index("creation_status_line") < names.index("voice_status_line"), names
    assert names[-2:] == ["voice_status_line", "_capability_health_line"], names


# --- GAP-CREAT-ALERT-STALE（S37/S50 同点实锤）：语音执行体在场性腿 ---------------------
# S69 现算更正：在场性探针（``has_registered_handler``）只对**语音**是"给不给得出"的有效代理
# （语音执行体经 media 唯一合成口真跑）。绘画 handler 包壳自 P5/S09 恒在册、却只在有适配器时
# 出图，"包壳在场"对绘画是**假信号**（见 test_creation_image_* 三例）——故这三条按语音通道测。


def test_tts_execution_present_leg_suppresses_false_alert() -> None:
    """语音：执行体已在册 ⇒ 绝不再报"实现工厂未接入"（S50 假告警教训）。

    注毒「删掉语音通道的在场性腿」⇒ 本条必红（等于把生产上每次 /bot status
    投一条假 config_missing 的行为放回去）。
    """
    alert.install_execution_presence_probe(lambda _capability_id: True)
    try:
        cfg = _Config(tts_api_url="http://127.0.0.1:9880")
        assert alert.check_reserved_channels(cfg) == {}
        assert "requested_but_missing" not in alert.creation_status_line(cfg)
        assert alert.flush_reserved_issues_to_alerts() == 0
    finally:
        alert.install_execution_presence_probe(None)


def test_tts_missing_probe_still_alerts_but_does_not_claim_unwired() -> None:
    """语音探针未注入＝不可判：宁可吵也不静默，但文案不许断言"未注册/未接入"。"""
    alert.install_execution_presence_probe(None)
    findings = alert.check_reserved_channels(_Config(tts_api_url="http://127.0.0.1:9880"))
    assert "creation.tts" in findings
    assert "probe=missing" in findings["creation.tts"]
    assert "未注册" not in findings["creation.tts"]


def test_tts_execution_absent_leg_still_names_not_wired() -> None:
    """语音探针说"没有" ⇒ 点名 not_wired（证明这条腿不是只朝一个方向偏）。"""
    alert.install_execution_presence_probe(lambda _capability_id: False)
    try:
        findings = alert.check_reserved_channels(_Config(tts_api_url="http://127.0.0.1:9880"))
    finally:
        alert.install_execution_presence_probe(None)
    assert "creation.tts" in findings
    assert "not_wired" in findings["creation.tts"]


# --- S69 主战场：绘画"填了 provider 但无适配器"必须可见（handler 包壳在场不算满足）---------


def test_image_alert_fires_despite_handler_present_when_no_adapter_wired(monkeypatch) -> None:
    """核心验收 (ii)：键已填 + 工厂无适配器 ⇒ 即便生产探针(has_registered_handler)说"在册"，
    绘画仍必须产 pending 告警（旧写法在此静默不告警、状态行还谎报"未接 provider"）。
    """
    from plugins.bot_unified_runtime.domains.creation.image import (
        provider_factory as pf,
    )

    # 钉死"工厂给不出适配器"：默认注册表为空 → unknown_provider，provider=None（不 wired）。
    monkeypatch.setattr(
        pf, "build_image_provider", lambda cfg, **kw: pf.ImageProviderSelection(None, "unknown_provider", "空表")
    )
    # 模拟生产装配：探针=恒真（等价 has_registered_handler 对绘画的回答）。
    alert.install_execution_presence_probe(lambda _capability_id: True)
    try:
        findings = alert.check_reserved_channels(_Config(image_provider="stable-diffusion"))
        assert "creation.image" in findings
        line = alert.creation_status_line(_Config(image_provider="stable-diffusion"))
        # 状态行不得谎报"未接 provider"——她明明填了、只是没适配器。
        assert "requested_but_missing" in line and "creation.image" in line
        sink = _Sink()
        alert.install_reserved_alert_sink(sink)
        assert alert.flush_reserved_issues_to_alerts() == 1  # 真投出去一条 OperationalIssue
        assert sink.received[-1].stage == "creation"
        assert sink.received[-1].kind == "config_missing"
    finally:
        alert.install_execution_presence_probe(None)


def test_image_wired_adapter_suppresses_alert(monkeypatch) -> None:
    """反向腿：工厂真派发 wired（有真实适配器）⇒ 绘画不告警（证明上条不是因为"永远告警"）。"""
    from plugins.bot_unified_runtime.domains.creation.image import engine_provider as ep
    from plugins.bot_unified_runtime.domains.creation.image import (
        provider_factory as pf,
    )

    wired = pf.ImageProviderSelection(ep.MockImageProvider(), "wired", "已接线（测试替身）")
    monkeypatch.setattr(pf, "build_image_provider", lambda cfg, **kw: wired)
    alert.install_execution_presence_probe(lambda _capability_id: False)  # 探针说没有也无妨
    try:
        assert alert.check_reserved_channels(_Config(image_provider="real-adapter")) == {}
        assert alert.pending_channels() == ()
    finally:
        alert.install_execution_presence_probe(None)


def test_image_probe_presence_never_substitutes_factory_leg(monkeypatch) -> None:
    """注毒自证：若有人把绘画腿改回"只信探针"（撤工厂腿），本条当场红——
    探针=True + 工厂不给适配器 = 必须仍告警（正是被 S69 修掉的静默洞）。"""
    from plugins.bot_unified_runtime.domains.creation.image import (
        provider_factory as pf,
    )

    monkeypatch.setattr(
        pf, "build_image_provider", lambda cfg, **kw: pf.ImageProviderSelection(None, "not_configured", "x")
    )
    alert.install_execution_presence_probe(lambda _capability_id: True)
    try:
        findings = alert.check_reserved_channels(_Config(image_provider="whatever"))
    finally:
        alert.install_execution_presence_probe(None)
    assert "creation.image" in findings, "绘画被 handler 在场性糊成已满足＝S69 修掉的洞复发"


def test_root_injects_central_presence_predicate() -> None:
    """根装配真注入了在场性探针，且走的是壳侧谓词、不是自己取 default_invoker()。

    第二 invoker 取用点由 ``tests/test_orchestration_callsite_single.py`` 执法，
    本锁只证"探针接上了"与"接的是册侧唯一谓词"两件事。
    """
    from pathlib import Path as _P

    text = (_P(__file__).resolve().parents[1] / "plugins/bot_unified_runtime/__init__.py").read_text(
        encoding="utf-8"
    )
    assert "install_execution_presence_probe(has_registered_handler)" in text
    assert "default_invoker().handlers" not in text


# ===========================================================================
# S102 巡检波：缺位必须在**周期巡检**可见（此前该生产者唯一驱动点是 /bot status）
#
# 三条判据、逐条有活性用例（不用"函数存在"糊）：
#   ①「键空也可见」：全空配置下 patrol 经 sink 投出一条 creation_not_configured；
#   ②「响一次」：连巡多轮，creation_not_configured 只投一次（config_missing 腿仍每轮现算）；
#   ③「装配晚到不隐身」：无 sink 的巡检不得把缺位标记成已报，接上 sink 后下一轮必须补投一次。
# 分层锁：/bot status（creation_status_line）**绝不**触发 not_configured 腿（既有"预留位不算
# 故障"口径零改动），只有 patrol 触发。
# ===========================================================================


def test_patrol_drives_requested_but_missing_leg_through_sink() -> None:
    """活性①：巡检入口确实驱动「要而不得」腿到 sink（不是只有 /bot status 才投）。"""
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)
    alert.install_execution_presence_probe(lambda _capability_id: False)  # 语音执行体缺席
    try:
        # image 填了无适配器、tts 填了 api_url 但探针说没接 ⇒ 两枚 config_missing。
        delivered = alert.patrol_reserved_health(
            _Config(image_provider="stable-diffusion", tts_api_url="http://127.0.0.1:9880")
        )
        assert delivered == 2
        kinds = [i.kind for i in sink.received]
        assert kinds == ["config_missing", "config_missing"]
    finally:
        alert.install_execution_presence_probe(None)


def test_patrol_makes_unconfigured_channels_visible_once() -> None:
    """活性②：全空配置（她从没碰过）⇒ patrol 投一条 creation_not_configured，且只此一条。"""
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)
    cfg = _Config()  # 两通道 provider 键皆空
    delivered = alert.patrol_reserved_health(cfg)
    assert delivered == 1
    issue = sink.received[-1]
    assert issue.stage == "creation"
    assert issue.kind == alert._NOT_CONFIGURED_KIND == "creation_not_configured"
    assert issue.retryable is False
    assert "creation.image" in issue.safe_summary and "creation.tts" in issue.safe_summary
    # 只响一次：再巡两轮不再重复投缺位（否则对未实现预留位刷屏＝把真告警埋掉）。
    assert alert.patrol_reserved_health(cfg) == 0
    assert alert.patrol_reserved_health(cfg) == 0
    assert alert.has_fired_not_configured() is True
    assert len([i for i in sink.received if i.kind == alert._NOT_CONFIGURED_KIND]) == 1


def test_patrol_not_configured_survives_late_sink_then_fires_once() -> None:
    """活性③：装配晚到不隐身——无 sink 的巡检不得把缺位标成已报，接上 sink 后补投恰一次。"""
    cfg = _Config()
    alert.install_reserved_alert_sink(None)  # 尚未装配 sink
    assert alert.patrol_reserved_health(cfg) == 0
    assert alert.has_fired_not_configured() is False  # 没投出去 ⇒ 不许置 fired
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)  # 装配补上
    assert alert.patrol_reserved_health(cfg) == 1
    assert sink.received[-1].kind == alert._NOT_CONFIGURED_KIND
    assert alert.has_fired_not_configured() is True
    assert alert.patrol_reserved_health(cfg) == 0  # 之后永久只此一次


def test_patrol_not_configured_keeping_on_raising_sink() -> None:
    """活性③同族：sink 抛错时缺位件保留、不置 fired，下轮换好 sink 仍补投（不可静默丢件）。"""
    cfg = _Config()
    alert.install_reserved_alert_sink(_Sink(boom=True))
    assert alert.patrol_reserved_health(cfg) == 0
    assert alert.has_fired_not_configured() is False
    alert.install_reserved_alert_sink(_Sink())  # 修好
    # 注意：坏 sink 那轮的 pending 已被清空过一次吗？——不会：flush 抛错返回 0 且不清桶，
    # 但 check_and_arm 在 fired=False 时会**重新武装**，故这轮仍能投出恰一条。
    assert alert.patrol_reserved_health(cfg) == 1


def test_status_line_never_fires_not_configured_leg() -> None:
    """分层锁：/bot status 面绝不为「从没碰过」的预留位投缺位告警（既有口径零改动）。"""
    sink = _Sink()
    alert.install_reserved_alert_sink(sink)
    cfg = _Config()
    line = alert.creation_status_line(cfg)  # 只读数、不武装 not_configured
    assert "reserved" in line and "未接 provider" in line
    assert alert.flush_reserved_issues_to_alerts() == 0  # 只清 config_missing 桶
    assert alert.has_fired_not_configured() is False  # status 路径不碰一次性口
    assert sink.received == []


def test_not_configured_channels_uses_single_ruler() -> None:
    """not_configured 腿与 provider_configured 反相、同一把尺子：填 image ⇒ 只剩 tts 未配。"""
    cfg = _Config(image_provider="stable-diffusion")
    empty = alert.not_configured_channels(cfg)
    assert empty == ("creation.tts",)  # image 已填 ⇒ 不算缺位
    assert alert.not_configured_channels(_Config()) == ("creation.tts", "creation.image")
    full = _Config(image_provider="x", tts_api_url="http://127.0.0.1:9880")
    assert alert.not_configured_channels(full) == ()


# SEAT-S102-PATROL-WIRE 已落根装配（根 __init__.py 现算 patrol_reserved_health 读点 1 处，
# campus 坐标随之 5356→5396），原挂在此用例上的 xfail(strict=False) 于本批摘牌转真绿。
def test_root_registers_periodic_patrol_driver() -> None:
    """周期驱动真在跑的**根侧**证据：root 必须把 patrol_reserved_health 挂上调度器。

    注毒预期：若 root 从未引用 patrol_reserved_health ⇒ 本条必红（=缺位只经手动 /bot status
    才可见、没有周期驱动）。落根补丁后转绿成为真锁。
    """
    root_src = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    root_tree = ast.parse(root_src)
    called = [
        node
        for node in ast.walk(root_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "patrol_reserved_health"
    ]
    assert len(called) >= 1, "root 未把 patrol_reserved_health 接进任何周期调度＝缺位无周期驱动"


# ===========================================================================
# SEAT-S115 / 代席 SEAT-S132：诊断卡与审计侧的「缺位必须可见」（目标 4 另两条腿）
#
# 判据口径（每条都有真身谓词，禁"字符串在场即算执法"）：
#   ①可归因＝**原因＋待配键的键名**，键名必须命中 ``config.py`` 的 ``Config.model_fields``
#     （在册性现算，不靠本文写死"已登记"）；
#   ②卡片侧＝把信封里携带的**那个异常对象**喂给真身 ``error_report.build_error_report``，
#     断言卡片的 ``exc_message``/文本兜底里真的出现那枚键名——不是"域内某处有这个字符串"；
#   ③审计侧＝经**真 invoker** ``default_invoker().invoke`` 跑一遍，断言 ``AuditHookRegistry``
#     实收的 ``CapabilityAuditRecord`` 带着归因串（invoker 只把 ``detail`` 入审计，
#     ``data`` 不入 ⇒ "载荷在信封里"与"审计看得见"是两件事，必须分开钉）；
#   ④零密钥值＝任何配置**值**都不得出现在文案/卡片里（AGENTS 铁律 3）；
#   ⑤已填的键不许被喊成"待配"（把运维指向错的那扇门＝假归因，与本席要修的洞同型）。
#
# 全离线：无网络、无真实告警投递、无出图；invoker 只跑 provider 门这条零 I/O 分支。
# ===========================================================================

_IMAGE_CID = "creation.image.generate"
_TTS_CID = "creation.tts.synthesize"


def _registered_config_field_names() -> set[str]:
    """真身谓词：``config.py`` 的字段集合（本席禁写 config.py，只读现算对账）。"""
    from plugins.bot_unified_runtime.config import Config

    return set(Config.model_fields)


def _job_payload() -> dict[str, Any]:
    """过契约自验的最小绘图请求（缺位这一支只要求契约先过，才轮到 provider 门说话）。"""
    from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage

    return cimage.ImageJobRequest(
        task="text_to_image",
        prompt="釉瑚风格的云母卡片插画",
        provider="mock-image",
        model="image-model-1",
        size="1024x1024",
        workspace_id="ws_main",
        version="rev-1",
    ).model_dump(mode="json")


def _image_handle_result(config: Any) -> Any:
    """走**真 handler**（不经中央 invoker）拿一枚 provider 门终态信封。"""
    from plugins.bot_unified_runtime.domains.creation.image import (
        engine_provider as ep,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    return ep.handle(
        CapabilityRequest(
            capability_id=_IMAGE_CID,
            payload={"job": _job_payload()},
            context={"config": config},
            principal="s115-offline",
            roles=("user",),
        )
    )


def _tts_handle_result(config: Any) -> Any:
    """语音通道同一形状（本席补的那条腿：此前它连 ``data`` 都不带）。"""
    from plugins.bot_unified_runtime.domains.creation.tts import (
        engine_provider as tep,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
    )

    return tep.handle(
        CapabilityRequest(
            capability_id=_TTS_CID,
            payload={"text": "守岸人的话"},
            context={"config": config},
            principal="s115-offline",
            roles=("user",),
        )
    )


#: 两通道同表遍历用（缺位文案与载荷必须同形，缺一即本席的"对称"是句空话）。
_BOTH_CHANNELS: tuple[tuple[str, Any], ...] = (
    (_IMAGE_CID, _image_handle_result),
    (_TTS_CID, _tts_handle_result),
)


class _ProviderLessConfig:
    """两通道 provider 键全空＝"她从没填过"（缺位态）；``bot_tts_enabled`` 必须真，
    否则语音会先被总开关拦下、测的就不是 provider 门这一支。"""

    bot_creation_image_provider: ClassVar[str] = ""
    bot_creation_tts_provider: ClassVar[str] = ""
    bot_tts_api_url: ClassVar[str] = ""
    bot_tts_ref_audios: ClassVar[list[str]] = []
    bot_tts_enabled: ClassVar[bool] = True


class _FilledButBlindConfig(_ProviderLessConfig):
    """键**已填**且值带密钥形态：用来钉"不许回显值"与"已填不喊待配"两条。"""

    bot_creation_image_provider: ClassVar[str] = (
        "stable-diffusion?token=BOT_TTS_API_KEY=sk-abcdefghijklmnop"
    )
    bot_tts_api_url: ClassVar[str] = "http://user:sekret@127.0.0.1:9880"
    bot_tts_ref_audios: ClassVar[list[str]] = ["C:/Users/LancyCelestia/Secrets/ref.wav"]


def _card_report(exc: BaseException, capability_id: str) -> dict[str, Any]:
    """把异常喂给**卡片真身**（轻量模式，与同步回执同一构造口）。"""
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:s115",
        session_type=SessionType.PRIVATE,
        sender_id="u115",
        # W9 受众分级门（2026-10-01）之后，「异常原文进卡」只在**管理员私聊**档成立
        # （对外档裁掉 exc_message/配置键名）。本锁要证的是「归因串进得了卡面」这条
        # 结构通路，故把触发者建模成中央角色事实里的 admin——只有管理员才改得动
        # 缺位的配置键，归因的收件人本来就是这一档。
        sender_roles=["admin"],
        plain_text="/bot 画一张",
        message_id="m-s115",
    )
    return error_report.build_error_report(
        message,
        capability_id,
        exc,  # type: ignore[arg-type]
        config_getter=lambda _name: None,
        include_env=False,
    )


def _key_names_in(text: str) -> set[str]:
    """从一段文本里现算出**在册配置键名**（按 ``Config.model_fields`` 反查，不写死清单）。"""
    fields = _registered_config_field_names()
    return {name for name in fields if name in text}


# ---- ① 键名在册性 ----------------------------------------------------------


def test_pending_keys_named_for_both_channels_are_registered_config_fields() -> None:
    from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov

    fields = _registered_config_field_names()
    cfg = _ProviderLessConfig()
    for channel, cid in (("creation.image", _IMAGE_CID), ("creation.tts", _TTS_CID)):
        named = rprov.pending_provider_keys(cfg, cid)
        assert named, f"{channel}：缺位文案一个键都没点＝不可归因"
        assert set(named) <= fields, f"{channel}：点了不在册的键 {set(named) - fields}"
        # 点名的键此刻必须**真的还空着**（否则就是"待配"二字说谎）。
        for key in named:
            assert not str(getattr(cfg, key, "") or "").strip() or getattr(cfg, key) == []


def test_filled_keys_are_never_called_pending() -> None:
    """⑤假归因锁：键已填 ⇒ 文案不得再喊"待配键"，而要点名"缺的是适配器登记、非配置面"。

    这正是绘画今天的实况（键可填、``PROVIDER_REGISTRY`` 空）——旧写法把已填的键
    列成"待配"，运维照着填第二遍而真因在注册表（本席取证 §1 第二行）。
    """
    from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov

    cfg = _FilledButBlindConfig()
    detail = rprov.not_wired_detail(cfg, _IMAGE_CID)
    assert "待配键" not in detail, detail
    assert "非配置面" in detail, detail
    assert rprov.pending_provider_keys(cfg, _IMAGE_CID) == ()


# ---- ② 载荷形态：两通道同形、共用单一构造口 --------------------------------


def test_both_provider_gates_carry_one_attributable_issue() -> None:
    """核心锁：两通道的 ``UNAVAILABLE`` 都必须带**一枚可归因异常**，且文本逐字等于
    域内单一构造口 ``not_wired_detail``（各拼一份＝第二真身，一改就漂）。"""
    from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
    from plugins.bot_unified_runtime.domains.creation.reserved_provider import (
        CreationNotWired,
    )
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
        InvocationStatus,
    )

    cfg = _ProviderLessConfig()
    for cid, runner in _BOTH_CHANNELS:
        result = runner(cfg)
        assert result.status is InvocationStatus.UNAVAILABLE, f"{cid}：终态不是 unavailable"
        carried = result.data.get(INVOKER_ERROR_DATA_KEY)
        assert isinstance(carried, CreationNotWired), (
            f"{cid}：缺位没带可归因 issue（收到 {type(carried).__name__}）"
        )
        assert str(carried) == rprov.not_wired_detail(cfg, cid) == result.detail, (
            f"{cid}：信封 detail 与异常文本不同源＝存在第二份文案构造口"
        )
        assert _key_names_in(str(carried)) & set(rprov.provider_key_names(cid)), (
            f"{cid}：issue 文本里点不到任何本通道在册键＝不可归因"
        )


def test_zero_config_values_leak_into_detail_or_exception() -> None:
    """④铁律 3 腿：键已填且值带 token/密码/绝对路径时，文案与异常文本都不许带上**值**。"""
    from plugins.bot_unified_runtime.domains.creation.image import engine_provider as ep
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
    )

    cfg = _FilledButBlindConfig()
    result = _image_handle_result(cfg)
    carried = result.data[INVOKER_ERROR_DATA_KEY]
    assert isinstance(carried, ep.CreationImageNotWired)
    for blob in (
        "sk-abcdefghijklmnop",
        "sekret",
        "ref.wav",
        "LancyCelestia",
        "stable-diffusion?token",
    ):
        assert blob not in result.detail, f"detail 回显了配置值片段 {blob!r}"
        assert blob not in str(carried), f"异常文本回显了配置值片段 {blob!r}"


# ---- ③ 卡片侧真身：把载荷交给真 build_error_report --------------------------


def test_card_builder_reports_the_gap_with_a_registered_key_name() -> None:
    """卡片侧可见性＝**真身构造口吃过这个异常**后仍然点名，不是"某处有字符串"。

    注毒「把 issue 恒置 None」⇒ 本条先红（拿不到异常，喂不进卡片）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
    )

    cfg = _ProviderLessConfig()
    carried = _image_handle_result(cfg).data[INVOKER_ERROR_DATA_KEY]
    assert isinstance(carried, Exception), "卡片只吃 Exception：载荷不是异常＝这条腿断在源头"

    report = _card_report(carried, _IMAGE_CID)
    assert report["exc_type"] == "CreationImageNotWired"
    named = _key_names_in(str(report["exc_message"]))
    assert named, f"卡片 exc_message 没点任何在册配置键：{report['exc_message']!r}"
    assert "待配键" in report["exc_message"]
    # 文本兜底（渲染失败/冷却降级时的唯一人读面）同样点名——两处共用同一 exc_message。
    fallback = _text_fallback(report)
    assert "待配键" in fallback and named & _key_names_in(fallback)


def _text_fallback(report: dict[str, Any]) -> str:
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    return error_report.build_text_fallback(report)


def test_card_config_snapshot_cannot_cover_creation_so_message_must_name_the_key() -> None:
    """为什么"键名进文案"不是锦上添花：卡片的 ``config_pairs`` 前缀由 capability_id 派生
    （``bot.<module>_``），``creation.image.generate`` 派生出 ``bot_creation_image_generate_``
    ⇒ **永远零命中**。快照指望不上，文案就必须点名（这条锁防后来者把键名从文案里删掉）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        INVOKER_ERROR_DATA_KEY,
    )

    values = {"bot_creation_image_provider": "filled-somewhere-else"}
    # 键已填（工厂仍派不出适配器 ⇒ 走"非配置面"那一支）。用 SimpleNamespace 而不是往
    # ClassVar 实例上赋值：mypy 当场拦"经实例赋值类变量"（本席首版就挨了一发）。
    cfg = SimpleNamespace(**values)
    carried = _image_handle_result(cfg).data[INVOKER_ERROR_DATA_KEY]
    report = error_report_build_with_values(carried, values)
    labels = {row["label"] for row in report["config_pairs"]}
    assert not any(label.startswith("bot_creation_image_generate_") for label in labels)
    assert "bot_creation_image_provider" not in labels, (
        "快照若能覆盖到就该点名——本锁的前提是它覆盖不到，前提变了要一起改"
    )
    # 覆盖不到 ⇒ 归因只能靠文案，而文案此刻确实点到了真因（缺的是注册表、非配置面）。
    assert "非配置面" in str(report["exc_message"])


def error_report_build_with_values(exc: BaseException, values: dict[str, str]) -> dict[str, Any]:
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType
    from plugins.bot_unified_runtime.domains.ops.monitor import error_report

    message = IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="private:s115",
        session_type=SessionType.PRIVATE,
        sender_id="u115",
        # 同 `_card_report`：本锁证的是「快照覆盖不到 ⇒ 归因只能进文案」这条通路，
        # 而文案进卡属管理员私聊档（W9 受众分级门），非管理态那张卡看不到键名。
        sender_roles=["admin"],
        plain_text="/bot 画一张",
        message_id="m-s115b",
    )
    return error_report.build_error_report(
        message, _IMAGE_CID, exc, config_getter=values.get, include_env=False  # type: ignore[arg-type]
    )


# ---- ④ 审计侧真身：经中央 invoker 跑一遍，实收 CapabilityAuditRecord --------


def test_central_invoker_audit_row_names_the_missing_key() -> None:
    """审计侧＝``AuditHookRegistry`` 实收记录里有归因串（含在册键名），且载荷不被洗掉。

    这一条同时钉两件"看起来一样、其实不同"的事：
    - invoker **只把 ``detail`` 写进审计**，``data`` 不入 ⇒ 所以可归因串必须在 detail 里；
    - 载荷穿过 invoker 仍在 ⇒ 才有 caller 一侧出卡的可能。
    """
    from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    invoker = cp.default_invoker()
    original_hooks = invoker.audit_hooks
    fresh = cp.AuditHookRegistry()
    rows: list[Any] = []
    fresh.register(lambda record: rows.append(record))
    invoker.audit_hooks = fresh
    try:
        result = invoker.invoke(
            cp.CapabilityRequest(
                capability_id=_IMAGE_CID,
                payload={"job": _job_payload()},
                principal="s115-offline",
                roles=("user",),
                context={"config": _ProviderLessConfig()},
                request_id="req-s115",
                session_key="private_s115",
            )
        )
    finally:
        invoker.audit_hooks = original_hooks

    assert result.status is cp.InvocationStatus.UNAVAILABLE, result.status
    assert rows, "中央审计口一行都没收到＝执行不留痕（S-TTSPIPE 同型洞）"
    row = rows[-1]
    assert row.capability_id == _IMAGE_CID and row.status is cp.InvocationStatus.UNAVAILABLE
    named = _key_names_in(row.detail)
    assert named, f"审计 detail 没点任何在册配置键：{row.detail!r}"
    assert named & set(rprov.provider_key_names("creation.image"))
    assert isinstance(result.data.get(cp.INVOKER_ERROR_DATA_KEY), rprov.CreationNotWired), (
        "载荷在中央被洗掉 ⇒ caller 侧永远出不了卡"
    )
    assert row.request_id == "req-s115" and row.session_key == "private_s115"


# ---- ⑤ 可达性诚实账：在册未执法不许被叙述成已执法 --------------------------


def test_creation_ids_are_not_command_or_prepared_adapters_today() -> None:
    """现算真值：两枚 creation 能力**不在** ``_route_execution_adapters()`` 里
    ⇒ 层 1 ``_step`` 那条 ``raise`` 腿今天对它们不可达（直接注册的 handler，非路由命令形）。

    这条锁钉的是"事实"而不是"愿望"：谁把 creation 接成命令形（caller 落地），
    本条会红 ⇒ 必须同时把下面那条 xfail 摘牌、并改文案里"→诊断卡"的口径。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        _KNOWN_ADAPTERS,
        _route_execution_adapters,
    )

    adapters = _route_execution_adapters()
    for cid in (_IMAGE_CID, _TTS_CID):
        assert adapters.get(cid) not in _KNOWN_ADAPTERS, (
            f"{cid} 已成 {adapters.get(cid)} 形 ⇒ 诊断卡 raise 腿可达了，"
            "本锁与 SEAT-S115-CARD-WIRE 那条 xfail 要一起转真绿"
        )


@pytest.mark.xfail(
    strict=False,
    reason=(
        "SEAT-S115-CARD-WIRE：缺位异常已进信封且穿过 invoker，但全树没有任何读者"
        "会为 creation 两通道 raise ⇒「未接 provider ⇒ 诊断卡」这句散文今天不成立。"
        "摘牌条件＝caller 侧 raise 腿落地（补丁文本见 SEAT-S115/S132 §3）后删除本装饰器。"
    ),
)
def test_a_layer_one_consumer_actually_raises_for_creation_gap() -> None:
    """愿望侧的活性锁（今天必红＝诚实挂账，不是造绿）：拿信封喂层 1 的读者，应真的抛。

    判据不吃"字段在场"：真去调用 ``orchestrated_command`` 造出的 ``_step``，
    断言它把载荷里的异常 raise 回来。今天它对未在册 adapter 的能力**直接原样执行旧路**
    ⇒ 不 raise ⇒ 本条红。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    carried = _image_handle_result(_ProviderLessConfig()).data[cp.INVOKER_ERROR_DATA_KEY]

    def _fake_capability(*_args: Any, **_kwargs: Any) -> Any:
        # 用 SimpleNamespace 而非内联 class：class 体里引用外层函数的局部变量在
        # 某些作用台下会指歪（本席首版就踩了一次），显式传值最稳。
        return SimpleNamespace(data={cp.INVOKER_ERROR_DATA_KEY: carried})

    step = cp.orchestrated_command(_IMAGE_CID, _fake_capability, _ProviderLessConfig())

    message = SimpleNamespace(sender_id="u115", request_id="req-s115", session_key="private_s115")
    decision = SimpleNamespace(actor_roles=("user",))

    # 不写 `raises(BaseException)`（B017 盲断言）：本载荷的在册父类就是 RuntimeError
    # （``CreationNotWired``），断准这一层才不会把"任意一种崩"当"接上了"。
    with pytest.raises(RuntimeError):
        step(message, decision)


