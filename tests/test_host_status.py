"""宿主机状态采集（``domains/ops/monitor/host_status.py``）回归——第 5 项。

三条锁各自对上一件会真发生的事：

1. **实况有数**：本机装了 psutil，所以「一条读数都没有」就是采集口坏了，
   而不是「这台机器特殊」；顺带锁住分组顺序（呈现层按插入序出卡）。
2. **缺数=缺行**：任何读数取不到时那行**不出现**，绝不写「未知」占位、
   更不折算——一排假「未知」比空卡片更坏，它读起来像在看实况。
3. **版本读数只有一个来源**：本模块只调 ``error_report._version_pairs()``，
   形状不合（非二元组、值空）就整条丢；它炸了则这一段缺席，
   但**不许**自己动手拼版本号（那会是第二真身）。
"""

from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.ops.monitor import error_report, host_status

GROUP_ORDER = ["硬件", "占用", "系统与运行时"]


def _snapshot() -> dict[str, list[tuple[str, str]]]:
    return host_status.collect_host_snapshot()


def _assert_shape(groups: dict[str, list[tuple[str, str]]]) -> None:
    assert list(groups.keys()) == GROUP_ORDER, "分组顺序即出卡顺序，漂了就是卡片版式漂了"
    for rows in groups.values():
        for row in rows:
            assert isinstance(row, tuple) and len(row) == 2
            label, value = row
            assert isinstance(label, str) and label.strip()
            assert isinstance(value, str) and value.strip(), f"{label} 的值不能是空串"
            assert "未知" not in value and "unknown" not in value.lower(), (
                f"{label} 拿的是假占位值：{value}"
            )


@pytest.mark.skipif(
    importlib.util.find_spec("psutil") is None, reason="本环境未装 psutil，整面降级由下面的用例锁"
)
def test_live_snapshot_has_real_rows_in_every_group() -> None:
    groups = _snapshot()
    _assert_shape(groups)
    labels = {label for rows in groups.values() for label, _ in rows}
    assert "处理器" in labels
    assert "内存" in labels
    assert {"CPU 规格", "CPU 占用"} & labels
    # 操作系统/Python 由谁给都行，但**只能给一次**——中央版本口在场时
    # 平台探测那两行必须让路（同一事实两处出现迟早漂成两个值）。
    assert {"系统", "操作系统"} & labels
    assert "Python" in labels


def test_os_and_python_are_never_duplicated() -> None:
    """同一事实不许两处出现：Python 全清单里只能有一行。"""
    rows = host_status.host_status_rows()
    python_rows = [row for row in rows if row[0] == "Python"]
    assert len(python_rows) <= 1, rows
    values = [value for _label, value in rows]
    assert len(values) == len(set(values)), f"整表出现重复值=复读行：{rows}"


@pytest.mark.skipif(importlib.util.find_spec("psutil") is None, reason="同上")
def test_gpu_row_is_reported_when_readable() -> None:
    """本机有独显；读不到显卡只可能是取数路径坏，不是「这台机器没显卡」。"""
    assert host_status._gpu_labels(), "显示类注册表读数不应为空"


def test_psutil_absent_degrades_to_empty_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _no_psutil(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "psutil":
            raise ImportError("psutil missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    groups = host_status.collect_host_snapshot()
    _assert_shape(groups)
    assert all(rows == [] for rows in groups.values()), "没有 psutil 就整面空，不硬凑半份数据"
    assert host_status.host_status_text(empty_line="这台机器的读数这会儿拿不到。") == (
        "这台机器的读数这会儿拿不到。"
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ([], []),
        ([{"label": "NoneBot", "value": "2.5.0"}], [("NoneBot", "2.5.0")]),
        (
            [
                {"label": "ok", "value": "1"},
                {"label": "", "value": "x"},
                {"label": "y", "value": "  "},
                {"label": "z"},
                "flat",
                {"label": "a", "value": "b", "extra": 3},
            ],
            [("ok", "1"), ("a", "b")],
        ),
        (None, []),
        ("not a list", []),
        ([{"label": "a", "value": "  spaced  "}], [("a", "spaced")]),
    ],
)
def test_runtime_versions_only_accepts_the_real_shape(
    monkeypatch: pytest.MonkeyPatch, payload: Any, expected: list[tuple[str, str]]
) -> None:
    """真身契约 ``_version_pairs(getter) -> list[{"label","value"}]``（``error_report:1167``）。

    首版按「无参、返回二元组列表」写，``TypeError`` 被 except 咽掉 ⇒
    整段版本读数静默为空——形态像降级、实为死读点。本用例锁住「getter 必传」
    与「只认 label/value 字典」两件事。
    """
    module = importlib.import_module(
        "plugins.bot_unified_runtime.domains.ops.monitor.error_report"
    )
    seen: list[Any] = []

    def _fake(getter: Any) -> Any:
        seen.append(getter)
        return payload

    monkeypatch.setattr(module, "_version_pairs", _fake)
    assert host_status._runtime_versions() == expected
    assert seen == [module._dist_version], "getter 必须是同一份 _dist_version，不许传别的"


def test_runtime_versions_absent_when_source_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(
        "plugins.bot_unified_runtime.domains.ops.monitor.error_report"
    )

    def _boom() -> list[tuple[str, str]]:
        raise RuntimeError("版本采集口炸了")

    monkeypatch.setattr(module, "_version_pairs", _boom)
    assert host_status._runtime_versions() == []


def test_host_status_text_is_label_colon_value_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文本版每行「标签：值」，一行一条事实——超管在群里读纯文本也不能丢属性名。"""
    monkeypatch.setattr(
        host_status,
        "collect_host_snapshot",
        lambda: {"硬件": [("处理器", "X"), ("内存", "Y")], "占用": [], "系统与运行时": []},
    )
    assert host_status.host_status_text() == "处理器：X\n内存：Y"


def test_psutil_is_imported_lazily_not_at_module_level() -> None:
    """模块级不许 ``import psutil``——否则精简环境连「诚实说拿不到」这条路都走不到。"""
    tree = ast.parse(Path(host_status.__file__).read_text(encoding="utf-8"))
    module_level = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert "psutil" not in module_level, module_level


# ---------------------------------------------------------------------------
# ⑦ 宿主机状态卡（第 5 项出图半边）：只组装、零新模板、失败交回空串
# ---------------------------------------------------------------------------

_GROUPS = {
    "硬件": [("处理器", "Intel i9"), ("显卡", "RTX 4060"), ("显卡", "UHD Graphics")],
    "占用": [("CPU 占用", "28.6%"), ("磁盘 C:\\", "94.9%")],
    "系统与运行时": [("NoneBot", "2.5.0"), ("协议端", "@snowluma/runtime 1.14.19")],
}


def test_card_payload_keeps_every_row_and_disambiguates_labels() -> None:
    """同名属性跨行不许互相吃掉——两块盘/两张卡都要在卡上，静默覆盖=少一行数。"""
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    payload = host_card.build_host_card_payload(_GROUPS, taken_at="2026-09-25 21:30")
    stats = payload["stats"]
    assert stats["处理器"] == "Intel i9"
    assert stats["显卡"] == "RTX 4060"
    assert stats["显卡 2"] == "UHD Graphics"
    assert stats["磁盘 C:\\"] == "94.9%"
    assert len(stats) == 7, stats
    assert payload["badge"] == host_card.HOST_CARD_BADGE
    assert "取样时刻 2026-09-25 21:30" in payload["summary"]
    # 空组不进说明行，也不该造出光秃秃的分隔符
    assert "——" in payload["summary"]


def test_empty_groups_never_render_a_blank_card(tmp_path: Any) -> None:
    """全空读数不出图：一张空白卡比不出卡更像谎报「我查了」。"""
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    class _BoomBackend:
        available = True

        def render_card(self, _spec: Any) -> bytes:
            raise AssertionError("空读数不该走到出图")

    assert (
        host_card.render_host_card_png(
            {"硬件": [], "占用": [], "系统与运行时": []},
            backend=_BoomBackend(),
            card_dir=str(tmp_path),
        )
        == ""
    )


def test_card_digest_is_stable_and_renders_through_shared_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """同读数→同文件名（覆盖不喂爆目录）；出图必须走与诊断卡同一条落盘口。"""
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    payload = host_card.build_host_card_payload(_GROUPS)
    assert host_card.host_card_digest(payload) == host_card.host_card_digest(dict(payload))
    other = host_card.build_host_card_payload({**_GROUPS, "占用": [("CPU 占用", "99%")]})
    assert host_card.host_card_digest(other) != host_card.host_card_digest(payload)

    html_seen: list[str] = []

    class _FakeBackend:
        available = True

        def render_card(self, spec: dict[str, Any]) -> bytes:
            assert str(spec.get("html") or "").strip(), "空 HTML 不该被送去渲染"
            return b"PNG-fake-bytes"

    real = error_report.render_html_card

    def _spy(html: str, **kwargs: Any) -> str:
        html_seen.append(html)
        return real(html, **{**kwargs, "card_dir": str(tmp_path)})

    monkeypatch.setattr(error_report, "render_html_card", _spy)
    path = host_card.render_host_card_png(_GROUPS, backend=_FakeBackend())
    assert html_seen, "没走共用出图口＝又抄了一份第二实现"
    assert path and Path(path).exists() and Path(path).name.startswith("host_")


# ---------------------------------------------------------------------------
# ⑧ TTL 缓存口（第 5 项接线：loop/线程池两档消费）
# ---------------------------------------------------------------------------


def _fake_groups() -> dict[str, list[tuple[str, str]]]:
    return {"硬件": [("处理器", "X")], "占用": [], "系统与运行时": []}


def test_cached_snapshot_cold_nonblocking_never_computes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """冷缓存 + 不许阻塞 ⇒ 一个读数的活都不干（首版漏腿=200ms 采样压上 loop）。"""
    host_status.invalidate_cached_snapshot_for_tests()
    calls: list[int] = []
    monkeypatch.setattr(
        host_status,
        "collect_host_snapshot",
        lambda: (calls.append(1), _fake_groups())[1],
    )
    groups, taken = host_status.cached_host_snapshot(allow_blocking=False)
    assert all(rows == [] for rows in groups.values())
    assert taken == "" and calls == [], "loop 档冷启动绝不许现取"
    groups, taken = host_status.cached_host_snapshot(allow_blocking=True)
    assert groups["硬件"] == [("处理器", "X")] and taken and len(calls) == 1
    groups, _t = host_status.cached_host_snapshot(allow_blocking=False)
    assert groups["硬件"] == [("处理器", "X")] and len(calls) == 1, "TTL 内不许重取"
    # 把缓存戳拨老（单调钟同刻度下 ttl=0 测不出过期，直接改账本最稳）。
    host_status._SNAPSHOT_CACHE["wall_clock"] -= 10_000
    groups, _t = host_status.cached_host_snapshot(allow_blocking=True)
    assert len(calls) == 2, "过期且允许阻塞 ⇒ 现取"
    host_status._SNAPSHOT_CACHE["wall_clock"] -= 10_000
    groups, _t = host_status.cached_host_snapshot(allow_blocking=False)
    assert len(calls) == 2, "过期但不许阻塞 ⇒ 端旧份（取样时刻标签已声明保质期）"
    assert groups["硬件"] == [("处理器", "X")]
    host_status.invalidate_cached_snapshot_for_tests()


# ---------------------------------------------------------------------------
# ⑨ /bot status 接线半（echo.build_status_result）：超管附行附图、非超管逐字节不变
# ---------------------------------------------------------------------------


def _status_echo():
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    return echo


def test_non_super_admin_status_body_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归锁：非超管输出与接线前一致——管理员 body 恰等基线文本、images 空；
    被管理员门拒的档位拿的仍是既有拒绝话术（本改动没碰门）。"""
    echo = _status_echo()
    host_status.invalidate_cached_snapshot_for_tests()
    monkeypatch.setattr(echo, "_build_status_body", lambda *_a, **_k: "BASE")
    monkeypatch.setattr(host_status, "collect_host_snapshot", _fake_groups)
    result = echo.build_status_result(request_id="r", actor_roles=["admin", "user"])
    assert result.body == "BASE"
    assert list(result.images) == []
    for roles in (["user"], ["trusted"], ["Admin"], None):
        denied = echo.build_status_result(request_id="r", actor_roles=roles)
        assert "宿主机" not in denied.body
        assert list(denied.images) == []
    host_status.invalidate_cached_snapshot_for_tests()


def test_super_admin_status_appends_rows_and_card_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    echo = _status_echo()
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    host_status.invalidate_cached_snapshot_for_tests()
    monkeypatch.setattr(echo, "_build_status_body", lambda *_a, **_k: "BASE")
    monkeypatch.setattr(host_status, "collect_host_snapshot", _fake_groups)
    monkeypatch.setattr(
        host_card, "render_host_card_png", lambda _g, **_kw: "T:/cards/host_x.png"
    )
    result = echo.build_status_result(request_id="r", actor_roles=["admin", "super_admin"])
    assert result.body.startswith("BASE\n宿主机（超管视图，取样")
    assert "处理器：X" in result.body
    assert list(result.images) == [{"file": "T:/cards/host_x.png"}]
    # 超管判据自带小写归一；普通 admin（含大小写变体）蹭不上这趟车
    # （大写 "Admin" 连既有管理员门都过不了，属上游大小写敏感口径，非本接线面）。
    plain_admin = echo.build_status_result(request_id="r", actor_roles=["admin"])
    assert "宿主机" not in plain_admin.body and list(plain_admin.images) == []
    host_status.invalidate_cached_snapshot_for_tests()


def test_status_host_block_on_event_loop_does_no_blocking_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """loop 线程消费时：不现取、不渲染，只端缓存并如实标注没接线程池。"""
    import asyncio

    echo = _status_echo()
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    host_status.invalidate_cached_snapshot_for_tests()
    monkeypatch.setattr(host_status, "collect_host_snapshot", _fake_groups)
    renders: list[int] = []
    monkeypatch.setattr(
        host_card,
        "render_host_card_png",
        lambda _g, **_kw: (renders.append(1), "")[1],
    )
    # 先在 off-loop 把缓存喂热（这条腿允许现取+渲染）。
    echo._host_status_extension(["super_admin"])
    assert renders == [1]

    def _collect_boom() -> dict[str, list[tuple[str, str]]]:
        raise AssertionError("事件循环线程上绝不现取（psutil 200ms 采样）")

    monkeypatch.setattr(host_status, "collect_host_snapshot", _collect_boom)
    monkeypatch.setattr(echo, "_build_status_body", lambda *_a, **_k: "BASE")

    async def _go():
        return echo.build_status_result(request_id="r", actor_roles=["admin", "super_admin"])

    result = asyncio.run(_go())
    assert "尚未接入线程池" in result.body, "loop 档必须点名为什么只见字不见图"
    assert list(result.images) == []
    assert renders == [1], "loop 档一次渲染都不许发起"
    host_status.invalidate_cached_snapshot_for_tests()


def test_status_card_render_failure_fails_open_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    echo = _status_echo()
    from plugins.bot_unified_runtime.domains.ops.monitor import host_card

    host_status.invalidate_cached_snapshot_for_tests()
    monkeypatch.setattr(echo, "_build_status_body", lambda *_a, **_k: "BASE")
    monkeypatch.setattr(host_status, "collect_host_snapshot", _fake_groups)
    monkeypatch.setattr(host_card, "render_host_card_png", lambda _g, **_kw: "")
    result = echo.build_status_result(request_id="r", actor_roles=["admin", "super_admin"])
    assert "宿主机卡未出图" in result.body and list(result.images) == []
    assert "处理器：X" in result.body, "图挂了文本读数照给——命令绝不因渲染失败而报错"
    host_status.invalidate_cached_snapshot_for_tests()
