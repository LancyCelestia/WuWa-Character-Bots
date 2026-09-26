"""运行时读出面分区回归（goal18 第 5/10 项：时间/系统自述/宿主机三块接线）。

三族锁各钉一件会真发生的事：

1. **【当前时间】首行字节不变 + 追加行同源**：追加的时区/偏移/校时/历法明细
   必须与 ``character/temporal.time_partition_extras``、
   ``multi_calendar.rich_calendar_lines`` 现算一致——测试不抄第二份文案，
   比对"分区里出现的行 == 取数口给的行"，任何一侧漂了就红。
2. **空分区不渲染**：【系统自述】【宿主机状态】传空串 ⇒ 标签一个字都不出现；
   传非空 ⇒ 恰好出现一次。
3. **超管门是角色判据不是新键**：``_super_admin_host_partition_text`` 只认
   ``message.sender_roles``；非超管恒空串；读数行过
   ``redact_local_secrets``（盘符路径进不了 prompt）。
"""

from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    TemporalContext,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _super_admin_host_partition_text,
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import temporal as tmod

DATE_LOCAL = "2026-09-25"


def _context() -> ContextBundle:
    return ContextBundle(
        request_id="req-partition",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text="# 角色\n你就是守岸人。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-partition"),
        conversation_history=ConversationHistoryResult(request_id="req-partition"),
        knowledge_results=RetrievalResult(request_id="req-partition"),
        current_message="今天是什么日子",
        sender_id="user-1",
        session_id="private:user-1",
        # 预算给足：分区裁剪是另一族锁的管辖面，本文件要验的是"取数口给的行
        # 逐行进分区"，不能被缺省预算的截断噪声假红。
        context_budget=60000,
        temporal_context=TemporalContext(
            request_id="req-partition",
            now_local="21:00",
            date_local=DATE_LOCAL,
            weekday="星期五",
            timezone="Asia/Shanghai",
        ),
    )


def _system_prompt(**kwargs: str) -> str:
    messages, _ = build_chat_prompt_with_diagnostics(_context(), **kwargs)
    return messages[0]["content"]


# ---------------------------------------------------------------------------
# ①【当前时间】：首行不变 + 追加行与取数口逐字同值（非手写、恒非空）
# ---------------------------------------------------------------------------


def test_time_partition_first_line_unchanged_and_extras_same_source() -> None:
    prompt = _system_prompt()
    assert "【当前时间】2026-09-25 星期五 21:00" in prompt  # 首行字节口径=旧版
    extras = tmod.time_partition_extras(
        SimpleNamespace(timezone="Asia/Shanghai", date_local=DATE_LOCAL)
    )
    assert extras, "追加行不许为空：为空说明历法/校时取数口整段哑了"
    for line in extras:
        assert line in prompt, f"取数口给的行没进分区：{line}"
    # 五历同堂（第 10 项要求面）：公历/农历/伊斯兰历/藏历/东正教历都在分区里。
    for label in ("农历", "伊斯兰历", "藏历", "东正教历"):
        assert label in prompt
    # 手写计数禁则：分区文案里出现"共/总计 N 项"这类手写统计句式即红——
    # 一切数字只准来自现算行本身。
    block = prompt.split("【当前时间】", 1)[1].split("【", 1)[0]
    assert "共" not in block and "总计" not in block


def test_time_partition_fail_open_when_extras_broken(monkeypatch) -> None:
    def _throw(_temporal: object) -> list[str]:
        raise RuntimeError("历法面炸了")

    monkeypatch.setattr(tmod, "time_partition_extras", _throw)
    prompt = _system_prompt()
    assert "【当前时间】2026-09-25 星期五 21:00" in prompt  # 首行不受追加行株连
    assert "农历" not in prompt  # 追加行整段缺席=诚实少块，不是拿旧文案硬凑


# ---------------------------------------------------------------------------
# ② 空分区不渲染 / 非空恰好一次
# ---------------------------------------------------------------------------


def test_empty_readout_partitions_never_render() -> None:
    prompt = _system_prompt(host_status_section="", system_readout_section="")
    assert "【宿主机状态】" not in prompt
    assert "【系统自述】" not in prompt


def test_readout_partitions_render_once_when_nonempty() -> None:
    prompt = _system_prompt(
        host_status_section="取样 21:00\n处理器：X",
        system_readout_section="NoneBot：2.5.0",
    )
    assert prompt.count("【宿主机状态】") == 1
    assert prompt.count("【系统自述】") == 1
    assert "处理器：X" in prompt and "NoneBot：2.5.0" in prompt


# ---------------------------------------------------------------------------
# ③ 超管门：角色判据 + 脱敏，非超管恒空
# ---------------------------------------------------------------------------


def _message(roles: list[str]) -> SimpleNamespace:
    return SimpleNamespace(sender_roles=roles)


def test_host_partition_empty_for_non_super_admin() -> None:
    assert _super_admin_host_partition_text(_message(["user"])) == ""
    assert _super_admin_host_partition_text(_message(["admin"])) == ""
    assert _super_admin_host_partition_text(_message([])) == ""


def test_host_partition_super_admin_rows_are_redacted(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    monkeypatch.setattr(
        host_status,
        "cached_host_snapshot",
        lambda **_kw: (
            {
                "硬件": [("处理器", "Intel 某型")],
                "占用": [("磁盘 C:\\", "90%")],
                "系统与运行时": [("Python", "3.12.10")],
            },
            "21:00",
        ),
    )
    text = _super_admin_host_partition_text(_message(["super_admin", "admin"]))
    assert "【宿主机状态】" not in text  # 正文不带标签——标签归装配处，防双重出现
    assert "取样 21:00" in text and "处理器：Intel 某型" in text
    # 盘符路径进不了 prompt（redact_local_secrets 打码盘符形态）。
    assert "磁盘 C:\\" not in text


def test_host_partition_empty_rows_render_nothing(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    monkeypatch.setattr(
        host_status,
        "cached_host_snapshot",
        lambda **_kw: ({"硬件": [], "占用": [], "系统与运行时": []}, ""),
    )
    assert _super_admin_host_partition_text(_message(["super_admin"])) == ""


# ---------------------------------------------------------------------------
# ④ 校时/偏移读出：只读公开属性、诚实三态、坏时区回空
# ---------------------------------------------------------------------------


def test_clock_sync_readout_three_states(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync as ts

    monkeypatch.setattr(ts, "_SHARED", None)
    assert "未绑定" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=False, offset_seconds=None))
    assert "未启用" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=True, offset_seconds=None))
    assert "还没成功校准" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=True, offset_seconds=0.021))
    assert "+21" in tmod.clock_sync_readout()


def test_utc_offset_label_known_and_unknown() -> None:
    assert tmod.utc_offset_label("Asia/Shanghai") == "UTC+08:00"
    assert tmod.utc_offset_label("UTC") == "UTC+00:00"
    assert tmod.utc_offset_label("Mars/Phobos") == ""


# ---------------------------------------------------------------------------
# ⑤ 更新历史：git 不可用诚实缺席；成功路径走缓存不重复起子进程
# ---------------------------------------------------------------------------


def test_recent_update_lines_fail_open_without_git(monkeypatch) -> None:
    import subprocess

    tmod.clear_update_history_cache_for_tests()
    monkeypatch.setattr(tmod, "_repo_root", lambda: None)
    assert tmod.recent_update_lines() == []

    calls: list[object] = []

    def _boom(*_args, **_kwargs):
        calls.append(1)
        raise OSError("git 不存在")

    tmod.clear_update_history_cache_for_tests()  # 上一段的"无 git"已回填缓存，须清零再验子进程路径
    monkeypatch.setattr(tmod, "_repo_root", lambda: __import__("pathlib").Path("."))
    monkeypatch.setattr(subprocess, "run", _boom)
    assert tmod.recent_update_lines() == []
    assert len(calls) == 1  # 失败也回填缓存：坏 git 不被每条消息重试一遍
    assert tmod.recent_update_lines() == []
    assert len(calls) == 1
    tmod.clear_update_history_cache_for_tests()


def test_system_readout_lines_on_this_machine_non_empty() -> None:
    tmod.clear_update_history_cache_for_tests()
    lines = tmod.system_readout_lines()
    assert any(line.startswith("NoneBot") for line in lines), lines
    # 分区体不内嵌"共 N 项"式手写计数。
    assert all("共" not in line for line in lines)


def test_build_chat_prompt_entry_keeps_default_no_sections() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_prompt,
    )

    system_prompt = build_chat_prompt(_context())[0]["content"]
    assert "【宿主机状态】" not in system_prompt
    assert "【系统自述】" not in system_prompt
