"""tts_retcode_collect 离线回归：retcode 解析矩阵（全离线，样例日志字符串）.

覆盖：正常行/时间戳提取/空日志/乱码行/多码分布/白名单与预判集判定/
缺文件退出码/--json 结构。零网络、不连 SnowLuma、不启引擎。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import tts_retcode_collect as trc


def write_log(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 解析矩阵
# ---------------------------------------------------------------------------

def test_parse_normal_lines_counts_and_time_bounds(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        "nonebot.out.log",
        [
            (
                "09-20 01:00:01 [WARNING] bot.transport.onebot | onebot send rejected by "
                "platform retcode=1400 inline_retry_skipped=true request_id=r1"
            ),
            (
                "09-20 01:02:03 [WARNING] bot.transport.onebot | onebot send rejected by "
                "platform retcode=1400 inline_retry_skipped=true request_id=r2"
            ),
            (
                "09-20 01:05:06 [INFO] bot.transport.onebot | chunk rejected after partial "
                "delivery retcode=100 request_id=r3"
            ),
        ],
    )
    report = trc.collect([log])
    by_code = {c["retcode"]: c for c in report["codes"]}
    assert by_code[1400]["count"] == 2
    assert by_code[1400]["first"] == "09-20 01:00:01"
    assert by_code[1400]["last"] == "09-20 01:02:03"
    assert by_code[100]["count"] == 1
    assert by_code[100]["first"] == "09-20 01:05:06"
    assert report["retcode_hits"] == 3
    assert report["malformed_hits"] == 0


def test_parse_empty_log_and_zero_retcode_records(tmp_path: Path) -> None:
    empty = write_log(tmp_path, "empty.log", [])
    plain = write_log(tmp_path, "plain.log", ["09-20 01:00:00 [INFO] bot | 一条普通日志行"])
    report = trc.collect([empty, plain])
    assert report["codes"] == []
    assert report["retcode_hits"] == 0
    assert "零 retcode" in report["verdict"]


def test_parse_malformed_retcode_lines(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        "m.log",
        [
            "09-20 02:00:00 [ERROR] bot | send failed retcode=None request_id=r1",
            "09-20 02:00:01 [ERROR] bot | send failed retcode=abc",
            "09-20 02:00:02 [ERROR] bot | send failed retcode=",
            "09-20 02:00:03 [ERROR] bot | 回执形态 retcode: 1400（无等号形态不采）",
        ],
    )
    report = trc.collect([log])
    assert report["codes"] == []
    assert report["malformed_hits"] == 3
    assert len(report["malformed_samples"]) == 3


def test_parse_multicode_distribution_and_new_form(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        "multi.log",
        [
            "09-20 03:00:00 [WARNING] bot | rejected retcode=1400",
            "09-20 03:00:10 [WARNING] bot | rejected retcode=1400",
            "09-20 03:01:00 [WARNING] bot | rejected retcode=100",
            "09-20 03:02:00 [ERROR] bot | legacy napcat retcode=-1 rich media transfer failed",
            "09-20 03:03:00 [ERROR] bot | unknown form retcode=4242",
        ],
    )
    report = trc.collect([log])
    codes = report["codes"]
    assert [c["retcode"] for c in codes] == [1400, -1, 100, 4242]  # 计数降序，同计数按码升序
    by_code = {c["retcode"]: c for c in codes}
    assert by_code[1400]["in_whitelist"] is True
    assert by_code[100]["in_snowluma_set"] is True
    assert by_code[-1]["in_whitelist"] is False
    assert by_code[4242]["in_whitelist"] is False
    assert by_code[4242]["in_snowluma_set"] is False
    assert report["new_codes"] == [4242]
    assert "新形态" in report["verdict"]


def test_traceback_line_without_timestamp_still_counted(tmp_path: Path) -> None:
    log = write_log(
        tmp_path,
        "err.log",
        [
            "09-20 04:00:00 [ERROR] bot | transport failed",
            "Traceback (most recent call last):",
            "ChunkRejectedError: chunk rejected retcode=1400",
        ],
    )
    report = trc.collect([log])
    assert report["retcode_hits"] == 1
    entry = report["codes"][0]
    assert entry["retcode"] == 1400
    assert entry["first"] is None  # 无时间戳行：首末时间为空但不丢计数
    assert any("chunk rejected retcode=1400" in s for s in entry["samples"])


def test_samples_are_capped_and_trimmed(tmp_path: Path) -> None:
    lines = [
        f"09-20 05:{m:02d}:00 [WARNING] bot | rejected retcode=1200 x{'A' * 300}"
        for m in range(5)
    ]
    log = write_log(tmp_path, "s.log", lines)
    report = trc.collect([log], max_samples=2)
    entry = report["codes"][0]
    assert entry["count"] == 5
    assert len(entry["samples"]) == 2
    assert all(len(s) <= trc._SAMPLE_MAX_CHARS for s in entry["samples"])


# ---------------------------------------------------------------------------
# 判定提示与 CLI
# ---------------------------------------------------------------------------

def test_verdict_subset_closes_open_item(tmp_path: Path) -> None:
    log = write_log(tmp_path, "ok.log", ["09-20 06:00:00 [W] bot | rejected retcode=1400"])
    report = trc.collect([log])
    assert report["new_codes"] == []
    assert "T55" in report["verdict"]


def test_main_json_structure_and_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = write_log(tmp_path, "j.log", ["09-20 07:00:00 [W] bot | rejected retcode=1400"])
    rc = trc.main([str(log), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["scanned_files"] == 1
    assert payload["missing_files"] == []
    assert payload["lines_scanned"] >= 1
    assert payload["predicted_snowluma_set"] == [100, 1200, 1400, 1404]
    assert payload["codes"][0]["retcode"] == 1400
    assert "verdict" in payload


def test_main_missing_all_files_exit_one_with_p6_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = trc.main([str(tmp_path / "nope.log")])
    out = capsys.readouterr().out
    assert rc == 1
    assert "P-6" in out


def test_default_paths_point_to_runtime_logs(tmp_path: Path) -> None:
    paths = trc.default_log_paths(project_root=tmp_path)
    assert paths == [
        tmp_path.parent / "ChatBot_Runtime" / "logs" / "nonebot.out.log",
        tmp_path.parent / "ChatBot_Runtime" / "logs" / "nonebot.err.log",
    ]
