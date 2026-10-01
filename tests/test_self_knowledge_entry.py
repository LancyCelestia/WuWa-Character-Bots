"""需求 10：确定性「自我认知」装配层的离线测试。

全部 mock：不联网、不读真机 git（版本腿 monkeypatch 成交替常量）、不碰生产库。
钉死时刻，断言装配面**齐**（四历法 + 框架/适配器/插件 + 功能 + 更新历史 + 插件装载），
并锁住三条纪律：naive 时刻诚实降级（不猜）、非管理员不漏管理面、出图前脱敏。
最后一组反副本锁证明本装配没有第二套历法/版本实现（AGENTS 规则 10 + 第二真身红线）。
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import temporal
from plugins.bot_unified_runtime.domains.core.contracts.runtime import CapabilityResult
from plugins.bot_unified_runtime.domains.ops.self_knowledge import entry as ek

# 一个明确落在东八区同一日的瞬间（2026-09-29 08:30 北京），UTC=00:30 同日。
_PINNED = datetime(2026, 9, 29, 0, 30, tzinfo=timezone.utc)
_TZ = "Asia/Shanghai"


def _stub_versions() -> list[str]:
    return ["NoneBot：2.5.0", "Python：3.12.10", "系统：Windows 11", "构建：abc1234"]


@pytest.fixture
def offline_sources(monkeypatch, tmp_path: Path):
    """把版本腿/功能腿换成确定常量，并把根指向空 tmp（更新历史=未接入，离线）。"""
    monkeypatch.setattr(temporal, "system_readout_lines", _stub_versions, raising=True)
    monkeypatch.setattr(
        temporal,
        "capability_index_lines",
        lambda *, is_admin: ["我能做的事（本会话可见 3 项，按帮助注册表现算）：天气、点歌、帮助"],
        raising=True,
    )
    return tmp_path


def test_self_knowledge_lines_carries_all_required_faces(offline_sources):
    text = "\n".join(
        ek.self_knowledge_lines(
            now=_PINNED,
            timezone_name=_TZ,
            system_now=_PINNED,
            root=offline_sources,
            is_admin=True,
        )
    )
    for face in ("农历", "伊斯兰历", "藏历", "东正教历"):
        assert face in text, f"缺历法面：{face}"
    # 日期/时间面：UTC 时刻 + 配置时区 + 历法日界三面都在。
    for clock_face in ("UTC 时刻", "配置时区", "历法日界"):
        assert clock_face in text, f"缺时刻面：{clock_face}"
    # 软件框架/适配器/插件/功能/更新历史。
    assert "NoneBot：2.5.0" in text and "构建：" in text
    assert "我能做的事" in text
    assert "更新历史" in text
    assert "【NoneBot 插件装载】" in text


def test_self_knowledge_is_deterministic_for_pinned_instant(offline_sources):
    args = {
        "now": _PINNED,
        "timezone_name": _TZ,
        "system_now": _PINNED,
        "root": offline_sources,
        "is_admin": True,
    }
    first = ek.self_knowledge_lines(**args)
    second = ek.self_knowledge_lines(**args)
    assert first == second


def test_naive_instant_degrades_honestly_not_fabricated(offline_sources):
    naive = datetime(2026, 9, 29, 8, 30)  # noqa: DTZ001 - 故意造 naive 钟，测诚实拒绝路径
    text = "\n".join(
        ek.self_knowledge_lines(
            now=naive, timezone_name=_TZ, root=offline_sources, is_admin=True
        )
    )
    # 历法块拿不到 → 写「未接入」，而不是拿今天公历硬凑一个农历日期。
    assert "【自我历法】：未接入" in text
    assert ek._UNPROBED in text
    # 其余子块不受株连（fail-open 不 fail 成整段空）。
    assert "NoneBot：2.5.0" in text and "我能做的事" in text


def test_bad_timezone_name_does_not_crash(offline_sources):
    text = "\n".join(
        ek.self_knowledge_lines(
            now=_PINNED,
            timezone_name="Not/AZone",
            system_now=_PINNED,
            root=offline_sources,
        )
    )
    # 认不出的时区标「未探测」，不抛、不硬凑日期。
    assert "未探测" in text


def test_plugin_inventory_reports_loaded_names(monkeypatch):
    import nonebot

    fake = [SimpleNamespace(name="nonebot_plugin_console", id="a"), SimpleNamespace(name="dummy", id="b")]
    monkeypatch.setattr(nonebot, "get_loaded_plugins", lambda: fake, raising=False)
    lines = ek.plugin_inventory_lines()
    body = "\n".join(lines)
    assert "装载 2 个" in body and "nonebot_plugin_console" in body and "dummy" in body


def test_plugin_inventory_degrades_offline(monkeypatch):
    import nonebot

    def _boom() -> list:
        raise RuntimeError("driver not initialized")

    monkeypatch.setattr(nonebot, "get_loaded_plugins", _boom, raising=False)
    assert any("未探测" in line for line in ek.plugin_inventory_lines())


def test_output_is_redacted_before_returning(monkeypatch, tmp_path: Path):
    # 版本腿若漏出盘符路径，装配层最终脱敏必须把它洗掉（铁律 3 纵深防御）。
    # 注：ledger #55★ 记着 redact_local_secrets 不认「嵌词 sk-」，故这里只钉
    # 它确实会打码的盘符路径面，不用 sk- 形态去假设有第二把尺。
    monkeypatch.setattr(
        temporal,
        "system_readout_lines",
        lambda: ["配置目录 C:\\Users\\lancycelestia\\secret\\app.json"],
        raising=True,
    )
    monkeypatch.setattr(
        temporal, "capability_index_lines", lambda *, is_admin: [], raising=True
    )
    text = "\n".join(
        ek.self_knowledge_lines(now=_PINNED, timezone_name=_TZ, root=tmp_path)
    )
    assert "lancycelestia" not in text
    assert "C:\\Users\\lancycelestia" not in text


def test_capability_builder_shape_and_roles(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(temporal, "system_readout_lines", _stub_versions, raising=True)
    captured: dict[str, bool] = {}

    def _record(*, is_admin: bool) -> list[str]:
        captured["is_admin"] = is_admin
        return ["功能：x"]

    monkeypatch.setattr(temporal, "capability_index_lines", _record, raising=True)

    run = ek.build_self_knowledge_capability(SimpleNamespace(bot_timezone=_TZ))
    result = run(SimpleNamespace(request_id="req-42", sender_roles=["user"]), None)
    assert isinstance(result, CapabilityResult)
    assert result.kind == "text"
    assert result.capability_id == ek.SELF_KNOWLEDGE_CAPABILITY_ID
    assert result.request_id == "req-42"
    assert result.body and "【NoneBot 插件装载】" in result.body
    assert captured["is_admin"] is False

    run(SimpleNamespace(request_id="req-2", sender_roles=["admin"]), None)
    assert captured["is_admin"] is True


def test_non_admin_does_not_leak_admin_feature_topics():
    # 用真实功能腿：非管理员面里管理类主题（admin_only）一个都不该出现。
    text = "\n".join(
        ek.self_knowledge_lines(now=_PINNED, timezone_name=_TZ, is_admin=False)
    )
    # 「宿主机状态」是 HELP_TOPIC_DECLARATIONS 里 admin_only=True 的主题。
    assert "宿主机状态" not in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/bot self", True),
        ("/bot self_info 今天", True),
        ("自我认知", True),
        ("今天农历", True),
        ("现在几点", True),
        # 自然问句必须交回聊天腿（宽触发会从 bot.chat 抢走并绕过人格）。
        ("今天农历是什么日子呀", False),
        ("你最近都改了些什么呢", False),
        ("帮我看看机器状态", False),
        ("", False),
        (None, False),
    ],
)
def test_predicate_only_fires_on_explicit_forms(text, expected):
    assert ek.is_self_info_command(text) is expected


# ---------------------------------------------------------------------------
# 反副本锁：本装配必须是「装配」，不许藏第二套历法/版本实现（第二真身红线）。
# ---------------------------------------------------------------------------

_FORBIDDEN_ASTRONOMICAL_TOKENS = (
    "2451550",  # Meeus 朔纪元（住 multi_calendar）
    "1948440",  # Kuwaiti 伊斯兰历纪元（住 multi_calendar）
    "10631",  # 伊斯兰历 30 年周期天数
    "29.5305",  # 朔望月周期
    "0.215891",  # 朔级数系数
    "epact",  # 复活节月龄（住 multi_calendar）
)


def _entry_source() -> str:
    return Path(ek.__file__).read_text(encoding="utf-8")


def test_entry_holds_no_second_calendar_constants():
    source = _entry_source()
    for token in _FORBIDDEN_ASTRONOMICAL_TOKENS:
        assert token not in source, f"装配层出现历法常数 {token}＝第二套换算"


def test_entry_does_not_reimplement_versions_or_clock():
    tree = ast.parse(_entry_source())
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    # 不许自己造 _version_pairs / _runtime_versions / now 读取等真身函数。
    for banned in ("_version_pairs", "_runtime_versions", "_new_moon", "_pascha", "now"):
        assert banned not in defined
    # 模块顶层不读钟（同 self_calendar 包级锁的同型判据）：源码里不该有 datetime.now( / date.today(。
    source = _entry_source()
    assert "datetime.now(" not in source
    assert "date.today(" not in source
