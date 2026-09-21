"""S14 席：SnowlumaTailCollector 离线回归（tail/轮转/脱敏/背压/级别归一）。

全离线：tmp_path 真文件、零线程、poll_once 手动驱动、poll_forever 注入
sleep 干跑。
"""
from __future__ import annotations

from typing import Any

from plugins.bot_unified_runtime.domains.ops.collectors import (
    DEFAULT_MAX_LINE_CHARS,
    SnowlumaTailCollector,
    parse_level,
)


def write(path: Any, text: str) -> None:
    # newline=""：禁 Windows 文本模式 \n→\r\n 翻译，保证字节计数精确。
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(text)


# ----------------------------------------------------------------------
# 基本语义
# ----------------------------------------------------------------------


def test_unconfigured_path_is_lazy_and_honest():
    collector = SnowlumaTailCollector()
    assert collector.poll_once() == 0
    assert collector.state == "not_configured"
    assert collector.snapshot()["path"] is None


def test_first_sight_anchors_at_end_skipping_backlog(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "old-1\nold-2\n")
    collector = SnowlumaTailCollector(path=log)
    assert collector.poll_once() == 0  # 历史积压不读
    assert collector.state == "ok"
    write(log, "new-1\nnew-2\n")
    assert collector.poll_once() == 2
    assert collector.drain() == ["new-1", "new-2"]


def test_from_start_reads_existing_history(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "hist-1\nhist-2\n")
    collector = SnowlumaTailCollector(path=log, from_start=True)
    assert collector.poll_once() == 2
    assert collector.drain() == ["hist-1", "hist-2"]


def test_partial_line_held_until_complete(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "old\n")
    collector = SnowlumaTailCollector(path=log)
    assert collector.poll_once() == 0
    write(log, "hel")
    assert collector.poll_once() == 0  # 半行不交付
    write(log, "lo\n")
    assert collector.poll_once() == 1
    assert collector.drain() == ["hello"]


def test_unicode_lines_survive_byte_offset(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "历史中文行\n")
    collector = SnowlumaTailCollector(path=log)  # 锚末尾跳过
    assert collector.poll_once() == 0
    write(log, "新增中文行[WARN] 2026-09-18\n")
    assert collector.poll_once() == 1
    assert collector.drain() == ["新增中文行[WARN] 2026-09-18"]


def test_missing_file_then_appears(tmp_path):
    log = tmp_path / "ghost.log"
    collector = SnowlumaTailCollector(path=log)
    assert collector.poll_once() == 0
    assert collector.state == "missing"
    assert collector.missing_polls == 1
    write(log, "alive\n")
    assert collector.poll_once() == 0  # 首见锚末尾，旧内容不算新增
    write(log, "fresh\n")
    assert collector.poll_once() == 1
    assert collector.drain() == ["fresh"]


# ----------------------------------------------------------------------
# 轮转与积压
# ----------------------------------------------------------------------


def test_rotation_on_shrink_reopens_from_start(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "line-1\nline-2\n")
    collector = SnowlumaTailCollector(path=log)
    assert collector.poll_once() == 0
    write(log, "fresh-after-rotate\n")
    assert collector.poll_once() == 1
    # 模拟轮转：旧文件被截断重写（尺寸回缩）。
    with open(log, "w", encoding="utf-8", newline="") as fh:
        fh.write("post-rotate\n")
    assert collector.poll_once() == 1
    assert collector.rotations == 1
    assert collector.drain() == ["fresh-after-rotate", "post-rotate"]


def test_huge_backlog_jumps_to_end_with_honest_counter(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "")
    collector = SnowlumaTailCollector(path=log, max_catchup_bytes=64)
    assert collector.poll_once() == 0
    write(log, "x" * 40 + "\n" + "y" * 40 + "\n")  # 82 字节 > 64
    assert collector.poll_once() == 0  # 跳跃追赶，不逐行
    assert collector.dropped_bytes == 82
    assert collector.buffered_lines == 0
    write(log, "after-jump\n")
    assert collector.poll_once() == 1
    assert collector.drain() == ["after-jump"]


# ----------------------------------------------------------------------
# 脱敏与背压
# ----------------------------------------------------------------------


def test_lines_redacted_and_truncated(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "seed\n")
    collector = SnowlumaTailCollector(path=log, max_line_chars=40)
    assert collector.poll_once() == 0
    write(log, "token sk-abcdef123456 in line\n")
    write(log, "L" * 100 + "\n")
    assert collector.poll_once() == 2
    drained = collector.drain()
    assert "sk-abcdef123456" not in drained[0]
    assert len(drained[1]) <= 40 + len("…(已截断)")
    assert drained[1].endswith("…(已截断)")
    assert DEFAULT_MAX_LINE_CHARS == 2000


def test_buffer_backpressure_drops_newest_and_counts(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "")
    collector = SnowlumaTailCollector(path=log, max_buffer=2)
    assert collector.poll_once() == 0
    write(log, "a\nb\nc\nd\n")
    assert collector.poll_once() == 4  # 读到 4 行（2 交付 + 2 丢弃）
    assert collector.dropped_lines == 2
    assert collector.buffered_lines == 2
    assert collector.drain() == ["a", "b"]  # 保旧丢新
    assert collector.drain() == []


def test_sink_rejection_counts_as_drop(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "seed\n")
    collector = SnowlumaTailCollector(path=log, sink=lambda line: False)
    assert collector.poll_once() == 0
    write(log, "r1\nr2\n")
    assert collector.poll_once() == 2
    assert collector.dropped_lines == 2
    assert collector.lines_delivered == 0
    assert collector.buffered_lines == 0


def test_sink_accept_truthy_and_none_deliver(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    seen: list[str] = []

    def sink(line: str) -> bool | None:
        seen.append(line)
        return None if line.endswith("none") else True

    write(log, "ok-one\n")
    collector = SnowlumaTailCollector(path=log, sink=sink)
    assert collector.poll_once() == 0  # 首见锚末尾，历史不交付 sink
    write(log, "a-none\n")
    assert collector.poll_once() == 1
    write(log, "b-ok\n")
    assert collector.poll_once() == 1
    assert seen == ["a-none", "b-ok"]
    assert collector.dropped_lines == 0


def test_sink_exception_counted_and_not_fatal(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    calls = {"n": 0}

    def bad_sink(line: str) -> bool:
        calls["n"] += 1
        raise RuntimeError("sink exploded")

    write(log, "seed\n")
    collector = SnowlumaTailCollector(path=log, sink=bad_sink)
    assert collector.poll_once() == 0
    write(log, "boom\n")
    assert collector.poll_once() == 1
    assert collector.sink_errors == 1
    assert collector.dropped_lines == 1
    assert calls["n"] == 1


# ----------------------------------------------------------------------
# 级别归一与循环
# ----------------------------------------------------------------------


def test_parse_level_snowluma_line_shape():
    """SnowLuma 行形 = ``HH:MM:SS LEVEL [scope] msg``（实测词表 DEBUG/INFO/WARN/ERROR/OK）。"""
    assert parse_level("13:26:49 INFO               [App] SnowLuma starting") == "info"
    assert parse_level("14:20:16 DEBUG              [Bridge] session started: UIN=3958874605") == "debug"
    assert parse_level("14:20:16 WARN  [3958874605] [OneBot.GroupRequests] sender not identified") == "warning"
    assert parse_level("00:16:37 ERROR [3958874605] [OneBot.GroupRequests] group request scan failed") == "error"
    assert parse_level("14:20:16 OK                 [Hook] login detected: PID=80452 UIN=3958874605") == "info"


def test_parse_level_rejects_continuation_and_unknown():
    """堆栈续行与不认得的首字段一律 unknown（不猜）。"""
    assert parse_level("Error: send private message failed: 网络连接异常!") == "unknown"
    assert parse_level("    at Object.<anonymous> (node:internal/modules/cjs/loader:1562:14)") == "unknown"
    assert parse_level("13:26:49 TRACE [App] nonexistent token in this build") == "unknown"
    assert parse_level("plain text no marker") == "unknown"


def test_poll_forever_dry_run_with_injected_sleep(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "l1\nl2\nl3\n")
    slept: list[float] = []
    collector = SnowlumaTailCollector(path=log, from_start=True)
    collector.poll_forever(poll_interval=0.25, sleep=slept.append, max_cycles=3)
    assert slept == [0.25, 0.25, 0.25]
    assert collector.lines_delivered == 3  # 第 1 圈读完，后两圈空转
    assert collector.drain() == ["l1", "l2", "l3"]


def test_poll_forever_stop_flag(tmp_path):
    log = tmp_path / "snowluma-2026-09-20.log"
    write(log, "seed\n")
    collector = SnowlumaTailCollector(path=log)
    collector.poll_once()  # 锚末尾
    write(log, "n1\nn2\n")
    polls = {"n": 0}

    def stop() -> bool:
        return polls["n"] >= 2

    def tick(_seconds: float) -> None:
        polls["n"] += 1

    collector.poll_forever(poll_interval=0.1, stop=stop, sleep=tick)
    assert collector.lines_delivered == 2
    assert collector.snapshot()["state"] == "ok"
