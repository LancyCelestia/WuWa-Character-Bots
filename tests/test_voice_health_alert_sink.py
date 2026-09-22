"""S-OBS：语音探针 issue 的**唯一生产消费者**必须接通中央告警链。

背景（Wave G T79 建探针、S-GAPMAP「前 5 刀」第 3 刀记账）：`voice_health_probe`
构造 `tts_service_unreachable` issue 存进模块态、只经 `last_operational_issue()`
暴露，但全树**生产读者为 0**——诊断做出来了却永远到不了运维眼裡。本件把这根断链接上：

- 消费者（`voice_health_alert.flush_probe_issue_to_alerts`）**恰一处**读 `last_operational_issue()`，
  经装配点注入的 sink 交给**既有中央告警链**（禁第三条告警路，禁贴 CapabilityResult——
  见 voice_health_probe docstring / T84）；
- **去重不自造节流**：同窗不重复构造已在探针侧（`_ISSUE_COOLDOWN_SECONDS`），
  投递侧再由中央 `AdminAlertSuppression`（300s）折叠；消费者本身只做「读一次、投递一次、清空」，
  不放第二把时间闸；
- **陈旧不粘滞**：恢复沿清空 `_last_issue`（探针侧），投递后 drain（消费者侧），
  任一都不会把已恢复引擎的旧 issue 反复报出去。

全离线：TCP 全桩、sink 为进程内替身、零消息发送、绝不触碰引擎 ``/control``。
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import OperationalIssue
from plugins.bot_unified_runtime.domains.media import voice_health_probe as probe_mod
from plugins.bot_unified_runtime.domains.media.voice_health_probe import (
    last_operational_issue,
    probe_voice_engine,
)

_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"
_URL = "http://127.0.0.1:9880"


# ---------------------------------------------------------------------------
# 隔离 + 桩（探针进程内全局态，逐例清零；惯例同 test_voice_health_probe）
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from plugins.bot_unified_runtime.domains.media import (
        voice_health_alert as alert_mod,
    )

    probe_mod._reset_state()
    alert_mod.install_probe_alert_sink(None)
    yield
    probe_mod._reset_state()
    alert_mod.install_probe_alert_sink(None)


def _stub_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    ticks = [1000.0]
    monkeypatch.setattr(probe_mod, "_monotonic", lambda: ticks[0])
    return ticks


def _stub_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(host: str, port: int, timeout: float) -> object:
        raise ConnectionRefusedError("[WinError 10061]")

    monkeypatch.setattr(probe_mod, "_tcp_connect", _refuse)


def _stub_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Sock:
        def __enter__(self) -> object:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(probe_mod, "_tcp_connect", lambda h, p, t: _Sock())


# ---------------------------------------------------------------------------
# ① 活性判据：issue 真的到达告警 sink，且投递后 drain（不重投）
# ---------------------------------------------------------------------------
def test_probe_issue_reaches_central_sink_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.bot_unified_runtime.domains.media.voice_health_alert import (
        flush_probe_issue_to_alerts,
        install_probe_alert_sink,
    )

    _stub_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)
    assert isinstance(last_operational_issue(), OperationalIssue)

    delivered: list[OperationalIssue] = []
    install_probe_alert_sink(delivered.append)

    assert flush_probe_issue_to_alerts() is True
    assert len(delivered) == 1
    # drain：同一条 issue 不被第二次 flush 重投（去重靠「投一次清一次」+ 中央抑制，不靠第二把闸）
    assert flush_probe_issue_to_alerts() is False
    assert len(delivered) == 1
    assert last_operational_issue() is None


def test_flush_without_sink_is_noop_and_keeps_issue_for_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.bot_unified_runtime.domains.media.voice_health_alert import (
        flush_probe_issue_to_alerts,
        install_probe_alert_sink,
    )

    _stub_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)

    # 未装配 sink（生产早于装配点注入 / 关闸）→ 无消费者可投，诚实 no-op、不崩、不丢。
    assert flush_probe_issue_to_alerts() is False

    delivered: list[OperationalIssue] = []
    install_probe_alert_sink(delivered.append)
    assert flush_probe_issue_to_alerts() is True  # sink 到位后仍可投出，非被静默吞掉
    assert len(delivered) == 1


def test_sink_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.media.voice_health_alert import (
        flush_probe_issue_to_alerts,
        install_probe_alert_sink,
    )

    _stub_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)

    def _boom(issue: OperationalIssue) -> None:
        raise RuntimeError("告警链坏了")

    install_probe_alert_sink(_boom)
    # 告警链路自身故障绝不冒泡到状态查询（「failure must not recurse」，同 alerts.build_alert_content_sink）
    assert flush_probe_issue_to_alerts() is False


# ---------------------------------------------------------------------------
# ② 陈旧不粘滞：恢复沿必须清空 pending issue（否则旧 issue 被反复投给运维）
# ---------------------------------------------------------------------------
def test_recovery_clears_pending_probe_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.bot_unified_runtime.domains.media.voice_health_alert import (
        flush_probe_issue_to_alerts,
        install_probe_alert_sink,
    )

    _stub_clock(monkeypatch)
    _stub_refused(monkeypatch)
    probe_voice_engine(api_url=_URL)
    assert last_operational_issue() is not None

    _stub_ok(monkeypatch)
    up = probe_voice_engine(api_url=_URL)
    assert up.state == "reachable"
    # 引擎已恢复：探针侧清空 issue；即便此时才 flush 也不会把旧故障报出去
    assert last_operational_issue() is None
    delivered: list[OperationalIssue] = []
    install_probe_alert_sink(delivered.append)
    assert flush_probe_issue_to_alerts() is False
    assert delivered == []


# ---------------------------------------------------------------------------
# ③ 活性锁：`last_operational_issue()` 在生产里**恰有一处**读者（消费者），
#    且该消费者被生产触发点**恰有一处**调用。扫描器纯函数化 ⇒ 可喂合成树注毒。
# ---------------------------------------------------------------------------
def _call_sites(index: dict[str, str], symbol: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for rel, src in index.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        hits = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id == symbol) or (
                isinstance(fn, ast.Attribute) and fn.attr == symbol
            ):
                hits += 1
        if hits:
            out[rel] = out.get(rel, 0) + hits
    return out


def _load_production_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(_PKG_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "last_operational_issue" in text or "flush_probe_issue_to_alerts" in text:
            index[rel] = text
    return index


def test_last_operational_issue_has_exactly_one_production_consumer() -> None:
    sites = _call_sites(_load_production_index(), "last_operational_issue")
    assert sum(sites.values()) == 1, f"探针 issue 生产读者须恰 1 处，实得：{sites}"


def test_flush_is_triggered_from_exactly_one_production_site() -> None:
    index = _load_production_index()
    consumer_file = "domains/media/voice_health_alert.py"
    sites = _call_sites(index, "flush_probe_issue_to_alerts")
    # 消费者模块内定义不算调用；生产触发点（echo status）恰一处。
    assert sum(sites.values()) == 1, f"flush 生产触发点须恰 1 处，实得：{sites}"
    assert consumer_file not in sites, "消费者不得自我触发"


# ---------------------------------------------------------------------------
# ④ 注毒自证：锁真的有牙（读者消失 / 冒第二处 / 自我触发，三种世界分得开）
# ---------------------------------------------------------------------------
def test_reader_lock_has_teeth() -> None:
    with_reader = {"m.py": "def f(p):\n    return p.last_operational_issue()\n"}
    no_reader = {"m.py": "def f(p):\n    return None\n"}
    assert sum(_call_sites(with_reader, "last_operational_issue").values()) == 1
    assert sum(_call_sites(no_reader, "last_operational_issue").values()) == 0  # 删除接线 → 红
    double = {"a.py": "def f(p):\n    return p.last_operational_issue()\n",
              "b.py": "def f(p):\n    return p.last_operational_issue()\n"}
    assert sum(_call_sites(double, "last_operational_issue").values()) == 2  # 第二读者 → 红


def test_trigger_lock_has_teeth() -> None:
    self_fire = {
        "domains/media/voice_health_alert.py": (
            "def flush_probe_issue_to_alerts():\n"
            "    return flush_probe_issue_to_alerts()\n"
        )
    }
    # 消费者内部出现对自己名字的调用（自我触发/递归）会被计入并被生产锁判为异常
    assert "domains/media/voice_health_alert.py" in _call_sites(
        self_fire, "flush_probe_issue_to_alerts"
    )


def test_root_assembly_installs_the_alert_sink_exactly_once() -> None:
    """装配活性锁：生产必须**恰一处**把 sink 注进来，否则本件所有测试都只是在测假人。

    与 `test_orchestration_callsite_single.py::test_production_registers_the_central_audit_sink_exactly_once`
    同族判据——"机制存在"与"装配现场真的接上了"是两件事（本仓已多次被前者糊过后者）。
    """
    import ast
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "bot_unified_runtime"
        / "__init__.py"
    )
    tree = ast.parse(root.read_text(encoding="utf-8"))
    installs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "install_probe_alert_sink"
    ]
    assert len(installs) == 1, (
        f"根装配对 `install_probe_alert_sink` 的调用应为恰一处，实得 {len(installs)}"
        "＝0 处则诊断仍无人投递（回到 S-OBS 修之前的状态），>1 处则一次读落多份告警"
    )
