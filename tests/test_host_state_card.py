"""需求 5 呈现腿回归：宿主机状态**卡 + 能力入口**（S-T-HOST-2 二段，2026-09-26）。

判据按「会真发生的事」立，不按「函数存在」立（每条各拦一件）：

① 能力返回的是**呈现契约层** ``CapabilityResult``（domains.core.contracts.runtime
   那枚，全仓唯一性由 test_capability_result_unique.py 负责，这里只认它进得出）；
   卡成功才填 ``images=[{"file": path}]``，与 randpic/echo 附块同字段口径。
② 版本各项与 ``importlib.metadata``/中央采集口的**现算值**比对，且能力文件本体
   **不含任何版本号字面形态**（``\\d+\\.\\d+\\.\\d+`` 扫源即拦）。
③ 探针炸了 → 那一行是「采集失败：<类型>」人话，**绝不是被折成的 0**；其余项不陪葬。
④ 占用率行**自带参照系**：CPU 占用点名 200ms 采样窗，内存/磁盘的 % 与
   总/可用同轨出现，能力面逐字透传不但不加戏、也不许把参照系洗掉。
⑤ 卡 HTML 满足渲染契约的可文本化断言（无 meta viewport、body 透明、阴影只在
   登记族、字重 ≤700、.card 根、stats 行全数在场）——用**真渲染口**产出的页面。
⑥ 出图只准走唯一落图口 ``host_card.render_payload_png``（→ render_html_card，
   与诊断卡同路）；渲染后端缺席 → 纯文本 + 点名说明，读数一行不少。
⑦ loop 线程上**零采集零渲染**（tripwire 实证），只吃适配器缓存的降级腿。
⑧ 「读数→payload」的后缀去重循环全仓只准住一处（防 payload 拼装器回潮成两本账）。

测试全离线：psutil / nvidia-smi / 版本采集口 / 渲染后端一律 monkeypatch；
出卡用例只在 ``tmp_path`` 里落盘，不碰生产卡片目录。
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.core.contracts import CapabilityResult
from plugins.bot_unified_runtime.domains.ops import host_metrics as hm
from plugins.bot_unified_runtime.domains.ops.capabilities import host_state
from plugins.bot_unified_runtime.domains.ops.monitor import error_report, host_card

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"
HOST_STATE_SRC = (
    PLUGINS_ROOT / "bot_unified_runtime/domains/ops/capabilities/host_state.py"
)


# ---------------------------------------------------------------------------
# 夹具与缝（与 tests/test_host_metrics.py 同一哲学：patch 取数缝，不 patch 采集器）
# ---------------------------------------------------------------------------


def _fake_ps(*, memory_error: bool = False) -> Any:
    def virtual_memory() -> SimpleNamespace:
        if memory_error:
            raise RuntimeError("内存采集炸了（测试注毒）")
        return SimpleNamespace(
            total=(32 * 1024**3), available=(8 * 1024**3), percent=75.0
        )

    return SimpleNamespace(
        virtual_memory=virtual_memory,
        cpu_count=lambda logical=True: 16 if logical else 8,
        cpu_percent=lambda interval=0.0: 42.5,
        disk_partitions=lambda all=False: [SimpleNamespace(mountpoint="Q:\\")],
        disk_usage=lambda path: SimpleNamespace(
            total=(512 * 1024**3), free=(128 * 1024**3), percent=75.0
        ),
        Process=lambda *a, **k: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=int(1.5 * 1024**3)),
            cpu_times=lambda: SimpleNamespace(user=3661.0, system=30.0),
        ),
        swap_memory=lambda: SimpleNamespace(
            total=(16 * 1024**3), used=(2 * 1024**3), percent=12.5
        ),
        boot_time=lambda: 0.0,  # 与用例内 fake time 无关：值只被用来算差，断言不吃它
    )


def _stub_hardware_seams(
    monkeypatch: pytest.MonkeyPatch, *, ps: Any = None, all_absent: bool = False
) -> None:
    """掐掉一切真机器读数（psutil/注册表/nvidia-smi），版本腿按用例决定真假。"""
    if all_absent:
        monkeypatch.setattr(hm, "_psutil_module", lambda: None)
        monkeypatch.setattr(hm, "_logical_core_count", lambda: None)
        monkeypatch.setattr(hm, "_cpu_model_text", lambda: "")
        monkeypatch.setattr(hm, "_gpu_model_rows", list)
        monkeypatch.setattr(hm, "_stdlib_disk_usage_rows", list)
        # 2026-09-26 三段补齐的四枚**新取数缝**：本用例的判据是「啥都没探到时
        # 卡上不许出现一个数字」，而这四路读的是**装了什么的发行版元数据**与
        # nonebot 在册驱动，不属于「机器遥测」，掐掉旧缝不会自动掐掉它们。
        # 缺这四桩 ⇒ 本机真装的 console/mail/onebot/qq/telegram 版本号合法进卡，
        # 撞的就是那条「无编造数字」断言（夹具没跟上缝表，不是判据过严；
        # 与 tests/test_host_metrics.py 的 `_isolated` 同一批补齐、同一理由）。
        monkeypatch.setattr(hm, "_adapter_version_rows", list)
        monkeypatch.setattr(hm, "_dependency_plugin_rows", list)
        monkeypatch.setattr(hm, "_core_dependency_rows", list)
        monkeypatch.setattr(hm, "_protocol_endpoint_rows", list)
    else:
        monkeypatch.setattr(hm, "_psutil_module", lambda: ps or _fake_ps())
        monkeypatch.setattr(hm, "_cpu_model_text", lambda: "Fake Test CPU")
        monkeypatch.setattr(hm, "_gpu_model_rows", lambda: ["Fake GPU A", "Fake GPU B"])
    monkeypatch.setattr(
        hm, "_query_nvidia_smi", lambda timeout: ("", "测试环境不真调外部命令")
    )


def _stub_version_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hm, "_version_rows_map", dict)


def _message(text: str = "宿主机状态", request_id: str = "req-host-1") -> Any:
    return SimpleNamespace(plain_text=text, request_id=request_id)


def _decision(roles: list[str]) -> Any:
    return SimpleNamespace(actor_roles=roles)


def _run_capability(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "宿主机状态",
    roles: list[str] | None = None,
) -> CapabilityResult:
    capability = host_state.build_host_state_capability(None)
    return capability(_message(text), _decision(roles or ["super_admin"]))


def _synthetic_report() -> hm.HostMetricsReport:
    items = [
        hm.HostMetric(
            "nonebot_version", "NoneBot2", hm.GROUP_VERSIONS, "2.5.0", hm.STATE_OK,
            hm.VERSION_PAIRS_SOURCE,
        ),
        hm.HostMetric("cpu_model", "处理器", hm.GROUP_HARDWARE, "Fake CPU", hm.STATE_OK),
        hm.HostMetric("gpu_model", "显卡", hm.GROUP_HARDWARE, "GPU A", hm.STATE_OK),
        hm.HostMetric("gpu_model", "显卡", hm.GROUP_HARDWARE, "GPU B", hm.STATE_OK),
        hm.HostMetric(
            "memory", "内存", hm.GROUP_HARDWARE, "采集失败：RuntimeError", hm.STATE_FAILED
        ),
        hm.HostMetric(
            "cpu_percent", "CPU 占用", hm.GROUP_USAGE, "42.5%", hm.STATE_OK,
            "psutil.cpu_percent（200ms 窗）",
        ),
        hm.HostMetric(
            "disk", "磁盘 Q:\\", hm.GROUP_USAGE,
            "总 512.0 GB · 可用 128.0 GB · 占用 75.0%", hm.STATE_OK, "psutil.disk_usage",
        ),
    ]
    return hm.HostMetricsReport(items=tuple(items), taken_at="21:30")


class _FakeBackend:
    available = True

    def render_card(self, spec: dict[str, Any]) -> bytes:
        assert str(spec.get("html") or "").strip(), "空 HTML 不该被送去渲染"
        return b"PNG-fake-bytes"


# ---------------------------------------------------------------------------
# ① 能力形状：契约对象 / images 字段 / 卡与文字双出口
# ---------------------------------------------------------------------------


def test_capability_full_path_returns_contract_with_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_hardware_seams(monkeypatch)
    _stub_version_seam(monkeypatch)
    seen: list[dict[str, Any]] = []

    def _recorder(payload: dict[str, Any], **_kw: Any) -> str:
        seen.append(payload)
        return "T:/cards/host_deadbeef12.png"

    monkeypatch.setattr(host_card, "render_payload_png", _recorder)
    result = _run_capability(monkeypatch)
    assert isinstance(result, CapabilityResult)
    assert result.capability_id == host_state.CAPABILITY_ID
    assert result.audit_tags == ["host_state", "card_sent"]
    assert result.images == [{"file": "T:/cards/host_deadbeef12.png"}]
    assert result.audio == [] and result.video == [] and result.files == []
    # 走的是**真身分组文案**（不是 /bot status 附块那套旧标题）——两卡面各自有名。
    assert seen and seen[0]["title"] == hm.CARD_TITLE
    assert seen[0]["stats"]["CPU 占用"] == "42.5%"
    # body 恒为文字账：卡出成图了，读数行也一行不少（图挂了它仍是完整兜底）。
    assert "CPU 占用：42.5%" in result.body
    assert result.body.startswith("宿主机（超管视图，取样 ")


def test_gate_non_super_admin_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _tripwire() -> Any:
        raise AssertionError("非超管不该碰采集器")

    monkeypatch.setattr(hm, "collect_host_metrics_sync", _tripwire)
    result = _run_capability(monkeypatch, roles=["user"])
    assert result.audit_tags == ["host_state", "gate_not_super_admin"]
    assert result.images == []
    assert result.body in [
        t.format(action="看宿主机状态") for t in user_copy.ADMIN_GATE_TEMPLATES
    ]


def test_unrelated_text_silently_skips_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _tripwire() -> Any:
        raise AssertionError("未触发不该碰采集器")

    monkeypatch.setattr(hm, "collect_host_metrics_sync", _tripwire)
    result = _run_capability(monkeypatch, text="今天天气怎么样")
    assert result.send_policy.value == "silent_audit"
    assert result.audit_tags == ["host_state", "skip_no_trigger"]
    assert result.body == ""


@pytest.mark.parametrize(
    "text,expected",
    [
        ("宿主机状态", True),
        ("机器状态", True),
        ("机器配置", True),
        ("宿主机状态！", True),
        ("hoststate", True),
        ("宿主機狀態", True),
        ("宿主机状态库", False),  # 「库」不是边界字：包含关系词不误触发（randpic 同判据）
        ("给我看看机器状态", False),  # 触发词必须在句首
        ("hoststatex", False),  # 字母胶合拒绝
    ],
)
def test_trigger_acceptance_matrix(text: str, expected: bool) -> None:
    assert host_state.is_host_state_command(text) is expected


# ---------------------------------------------------------------------------
# ② 版本腿：现算值比对 + 能力文件零版本字面量
# ---------------------------------------------------------------------------


def test_version_rows_live_from_metadata_and_capability_file_has_no_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_hardware_seams(monkeypatch)  # 硬件全假；**版本腿故意不 stub**——现算比对本身就是判据
    monkeypatch.setattr(host_card, "render_payload_png", lambda payload, **kw: "")
    result = _run_capability(monkeypatch)

    def expected(label: str, raw: str) -> str:
        norm = raw.strip()
        return hm.NOT_PROBED if (not norm or norm in hm._VERSION_MISSING_VALUES) else norm

    nonebot_live = importlib.metadata.version("nonebot2")
    onebot_live = importlib.metadata.version("nonebot-adapter-onebot")
    assert f"NoneBot2：{expected('NoneBot2', nonebot_live)}" in result.body
    assert f"OneBot 适配器：{expected('OneBot 适配器', onebot_live)}" in result.body
    assert (
        f"协议端（SnowLuma）：{expected('协议端（SnowLuma）', error_report._protocol_client_version_label(error_report._default_config_getter))}"
        in result.body
    )
    # 能力文件本体不许出现任何「x.y.z」版本形态——出现即说明有人手抄了版本号。
    src = HOST_STATE_SRC.read_text(encoding="utf-8")
    assert not re.search(r"\d+\.\d+\.\d+", src), "能力文件里出现版本号字面量"


# ---------------------------------------------------------------------------
# ③④ 单项失败与人话 + 占用率参照系
# ---------------------------------------------------------------------------


def test_failing_probe_degrades_to_honest_line_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_hardware_seams(monkeypatch, ps=_fake_ps(memory_error=True))
    _stub_version_seam(monkeypatch)
    monkeypatch.setattr(host_card, "render_payload_png", lambda payload, **kw: "")
    result = _run_capability(monkeypatch)
    lines = dict(
        line.split("：", 1) for line in result.body.splitlines()[1:] if "：" in line
    )
    assert lines["内存"] == "采集失败：RuntimeError"  # 人话点名，不是 0，不是整卡消失
    assert lines["CPU 占用"] == "42.5%"  # 其余项不陪葬
    assert "0.0" not in lines["内存"]


def test_all_unprobed_has_no_fabricated_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_hardware_seams(monkeypatch, all_absent=True)
    _stub_version_seam(monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        host_card,
        "render_payload_png",
        lambda payload, **kw: captured.append(payload) or "",
    )
    result = _run_capability(monkeypatch)
    for line in result.body.splitlines()[1:]:
        if "：" not in line:
            continue  # 卡未出图的说明行不是读数行
        label, _, value = line.partition("：")
        assert value.strip(), f"{label} 出现空值"
        assert not re.search(r"\d", value), f"{label} 掺了编造的数字：{value}"
    stats = captured[0]["stats"]
    assert all(v == hm.NOT_PROBED for v in stats.values())


def test_percentage_rows_carry_their_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_hardware_seams(monkeypatch)
    _stub_version_seam(monkeypatch)
    monkeypatch.setattr(host_card, "render_payload_png", lambda payload, **kw: "")
    result = _run_capability(monkeypatch)
    lines = {
        line.split("：", 1)[0]: line.split("：", 1)[1]
        for line in result.body.splitlines()[1:]
        if "：" in line
    }
    # CPU 占用：全局机器占用率，采样窗必须点名（真身 source 带 200ms 窗口径）。
    assert lines["CPU 占用"] == "42.5%"
    report = hm.collect_host_metrics_sync()
    cpu_item = report.first("cpu_percent")
    assert cpu_item is not None and "200ms" in cpu_item.source
    # 内存/磁盘的 % 与「总/可用」同轨出现——单独一个百分数不带参照系就不许上卡。
    assert lines["内存"] == "总 32.0 GB · 可用 8.0 GB · 占用 75.0%"
    assert lines["磁盘 Q:\\"] == "总 512.0 GB · 可用 128.0 GB · 占用 75.0%"
    assert "常驻内存" in lines["本 bot 进程占用"]


# ---------------------------------------------------------------------------
# ⑤⑥ 卡：渲染契约断言 + 唯一落图口
# ---------------------------------------------------------------------------


def _rendered_host_html() -> str:
    from plugins.bot_unified_runtime.domains.render.card_render import bridge

    payload = hm.build_host_metrics_card_payload(_synthetic_report())
    return bridge.render_universal_card_html(payload)


def test_host_card_html_satisfies_render_contract() -> None:
    html = _rendered_host_html()
    assert '<div class="card"' in html
    assert not re.search(r"<meta[^>]*viewport", html), "渲染铁律：无 meta viewport"
    body_rules = re.findall(r"(?m)^\s*(?:html\s+)?body\s*\{([^}]*)\}", html)
    assert body_rules and any(
        "background: transparent" in rule for rule in body_rules
    ), "body 必须透明（omit_background 依赖）"
    from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
        SHADOW_CSS_VARS,
    )

    allowed = {"none"} | {f"var({name})" for name in SHADOW_CSS_VARS}
    for value in re.findall(r"box-shadow\s*:\s*([^;]+)(?:;|\})", html):
        normalized = re.sub(r"\s+", " ", value).strip()
        assert normalized in allowed, f"族外自造阴影：{normalized!r}"
    weights = {int(v) for v in re.findall(r"font-weight\s*:\s*(\d+)", html)}
    assert weights and max(weights) <= 700
    # 卡上内容：每项属性名与值都在，同名去重后的「显卡 2」也在，失败态原样上卡。
    for probe in (
        "NoneBot2", "2.5.0", "显卡 2", "GPU B", "采集失败：RuntimeError",
        "CPU 占用", "42.5%", "取样时刻 21:30", "宿主机状态",
    ):
        assert probe in html, f"卡 HTML 少了「{probe}」"


def test_card_lands_through_single_render_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build → render_payload_png → render_html_card（诊断卡同一条路）全链走通。"""
    seen: list[str] = []
    real = error_report.render_html_card

    def _spy(html: str, **kwargs: Any) -> str:
        seen.append(html)
        return real(html, **{**kwargs, "card_dir": str(tmp_path)})

    monkeypatch.setattr(error_report, "render_html_card", _spy)
    result = host_state.build_host_state_result(
        _synthetic_report(), request_id="req-1", backend=_FakeBackend(), card_dir=tmp_path
    )
    assert seen, "没走共用出图口＝又抄了一份第二实现"
    assert "宿主机状态" in seen[0] and "CPU 占用" in seen[0]
    assert len(result.images) == 1
    path = Path(result.images[0]["file"])
    assert path.exists() and path.name.startswith("host_")
    assert result.audit_tags == ["host_state", "card_sent"]


def test_backend_unavailable_falls_back_to_text_with_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """渲染后端缺席（本机测试环境实况）→ 无图、有说明、读数一行不少。"""
    monkeypatch.setattr(error_report, "_get_render_backend", lambda: None)
    result = host_state.build_host_state_result(
        _synthetic_report(), request_id="req-1", card_dir=tmp_path
    )
    assert result.images == []
    assert result.audit_tags == ["host_state", "card_missing"]
    assert result.body.endswith(host_state.CARD_FAIL_NOTE)
    for label in ("NoneBot2", "CPU 占用", "内存"):
        assert f"{label}：" in result.body


# ---------------------------------------------------------------------------
# ⑦ loop 线程降级腿：零采集零渲染（tripwire 实证）
# ---------------------------------------------------------------------------


def test_on_loop_capability_never_collects_or_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _tripwire() -> Any:
        raise AssertionError("事件循环线程上不许现取")

    monkeypatch.setattr(hm, "collect_host_metrics_sync", _tripwire)
    monkeypatch.setattr(
        host_card, "render_payload_png", _raise_render_tripwire()
    )
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    host_status.invalidate_cached_snapshot_for_tests()
    capability = host_state.build_host_state_capability(None)

    async def _call() -> CapabilityResult:
        return capability(_message(), _decision(["super_admin"]))

    cold = asyncio.run(_call())  # 冷缓存：诚实说拿不到 + 点名为什么没图
    assert cold.audit_tags == ["host_state", "loop_degraded"]
    assert cold.images == []
    assert host_state.NO_DATA_LINE in cold.body
    assert host_state.LOOP_DEGRADE_NOTE in cold.body

    monkeypatch.setattr(
        host_status,
        "cached_host_snapshot",
        lambda **kw: ({"硬件": [("处理器", "Fake CPU")]}, "21:30"),
    )
    warm = asyncio.run(_call())  # 有缓存：读数照给，取样时刻照标，仍不出卡不现取
    assert warm.audit_tags == ["host_state", "loop_degraded"]
    assert "取样 21:30" in warm.body and "处理器：Fake CPU" in warm.body
    assert host_state.LOOP_DEGRADE_NOTE in warm.body


def _raise_render_tripwire() -> Any:
    def _boom(*_a: Any, **_kw: Any) -> str:
        raise AssertionError("loop 线程上不许出卡（渲染是秒级阻塞活）")

    return _boom


# ---------------------------------------------------------------------------
# ⑧ payload 拼装去重锁：后缀循环全仓只住一处 + 旧卡面逐字节保真
# ---------------------------------------------------------------------------


def test_stats_suffix_loop_lives_in_exactly_one_place() -> None:
    hits: list[str] = []
    for path in sorted(PLUGINS_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if "while key in stats" in path.read_text(encoding="utf-8", errors="replace"):
            hits.append(path.relative_to(PLUGINS_ROOT).as_posix())
    assert hits == ["bot_unified_runtime/domains/ops/host_metrics.py"], (
        "「读数→payload」拼装回潮成多本账：" + str(hits)
    )


def test_host_card_payload_delegation_is_byte_identical() -> None:
    """旧 `/bot status` 卡面（echo 在吃）经委托后**逐字节**不许漂——含旧导语与旧标题。"""
    groups = {
        "硬件": [("处理器", "Intel i9"), ("显卡", "RTX 4060"), ("显卡", "UHD Graphics")],
        "占用": [("CPU 占用", "28.6%"), ("磁盘 C:\\", "94.9%")],
        "系统与运行时": [("NoneBot", "2.5.0")],
        "空组": [],
    }
    payload = host_card.build_host_card_payload(groups, taken_at="2026-09-26 21:30")
    assert payload == {
        "page_type": "universal",
        "title": "这台机器现在什么样",
        "badge": "超管视图",
        "summary": (
            "取样时刻 2026-09-26 21:30；硬件——配置（开机时自检到的那套）"
            " · 占用——此刻用量（现取，没有缓存） · 系统与运行时——软件与版本"
        ),
        "stats": {
            "处理器": "Intel i9",
            "显卡": "RTX 4060",
            "显卡 2": "UHD Graphics",
            "CPU 占用": "28.6%",
            "磁盘 C:\\": "94.9%",
            "NoneBot": "2.5.0",
        },
        "feature_label": "宿主机状态",
    }
    # 活性半边：它得**真的**在调唯一拼装器（只测输出会被「又抄一份同构逻辑」骗过——
    # 那由上一条全仓扫描拦，这一条拦「干脆不调、写死一份」的第三种形态）。
    assert "assemble_card_payload" in inspect.getsource(
        host_card.build_host_card_payload
    )
