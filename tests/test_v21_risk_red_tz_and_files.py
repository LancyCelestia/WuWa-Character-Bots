"""V2.1 A5 取证席 RED 测试——风险域 7/8（节日表跨年复用、提醒时区口径、旧 Office 伪装解析）。

2026-09-17 A13 修复席：风险 7/8 四条已修复并转正为回归测试（原
`@pytest.mark.xfail(strict=True)` 标记移除，转正后恒绿即回归锁）。

- 风险 7a（已修）：character/temporal.py 节日表加年份维度——农历节日
  （近似换算）仅 2026 成立，其余年份仅公历固定节日复用；
- 风险 7b（已修）：character/reminders.py 全链路统一配置时区
  （config.bot_timezone，缺省 Asia/Hong_Kong），naive 按配置时区解释、
  aware 一律换算到配置时区做墙钟推算与落库；
- 风险 8（已修）：sources/file_reader.py .xls/.ppt 拆独立分支诚实降级
  （{"status": "parser_unavailable"}，对齐 .pdf 先例），现代 OOXML 分支
  另捕 InvalidFileException/PackageNotFoundError/BadZipFile 防包级异常逃逸。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

# ==================== 风险 7：节日表跨年 / 提醒时区 ====================


def test_risk7_holiday_table_not_reused_across_years() -> None:
    """转正回归（V21-risk-7a 修复，2026-09-17）：节日表带年份维度——农历
    节日仅表内年份（2026）成立，2027-02-17 不再错报"春节"。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.temporal import (
        holiday_of,
    )

    assert holiday_of(datetime(2026, 2, 17)) == "春节"  # noqa: DTZ001 - naive 意图：holiday_of 只看年/月日维度
    assert holiday_of(datetime(2027, 2, 17)) == ""  # noqa: DTZ001 - 同上：表外年份仅公历节日


def test_risk7_reminder_wallclock_follows_config_timezone() -> None:
    """转正回归（V21-risk-7b 修复，2026-09-17）：墙钟推算统一配置时区。"""
    from zoneinfo import ZoneInfo

    from plugins.bot_unified_runtime.character.reminders import parse_reminder_intent

    bot_tz = ZoneInfo("Asia/Hong_Kong")  # config.py:254 默认值
    # 香港 2026-09-18 02:30（UTC 09-17 18:30）说"明天9点" → 应为香港 09-19 09:00。
    now = datetime(2026, 9, 17, 18, 30, tzinfo=ZoneInfo("UTC"))
    intent = parse_reminder_intent("明天9点提醒我喝水", now=now)
    assert intent is not None
    expected = datetime(2026, 9, 19, 9, 0, tzinfo=bot_tz)
    assert intent.remind_at.astimezone(timezone.utc) == expected.astimezone(
        timezone.utc
    ), f"实际 {intent.remind_at}（修复前按注入时刻时区/进程本地时区推墙钟）"


# ==================== 风险 8：.xls/.ppt 伪装 OOXML 解析 ====================

_OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512


@pytest.mark.parametrize(
    ("filename", "kind"),
    [("legacy.xls", "spreadsheet"), ("legacy.ppt", "presentation")],
)
def test_risk8_legacy_office_not_misparsed(
    tmp_path: Path, filename: str, kind: str
) -> None:
    """转正回归（V21-risk-8 修复，2026-09-17）：旧 OLE 二进制诚实降级
    （parser_unavailable），绝不抛包级异常伪装可读/崩读取链。"""
    from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
        read_supported_file,
    )

    path = tmp_path / filename
    path.write_bytes(_OLE2_MAGIC)
    result = read_supported_file(path)
    # 期望：诚实降级（标注 parser_unavailable/unsupported），绝不抛异常伪装可读。
    assert result.kind in {kind, "unsupported"}
    assert result.metadata is None or "unavailable" in str(result.metadata)
