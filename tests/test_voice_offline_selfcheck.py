"""tts_offline_selfcheck 离线回归：编排面（各子命令桩化，全离线零真跑）.

覆盖：三步顺序编排 / PASS+SKIP 放行 / FAIL 透传退出码与处置指引 /
语料门缺文件=SKIP / dry-run 桩化零子进程 / --json 结构。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import tts_offline_selfcheck as tsc


def fake_runner(script_name: str, payload: dict) -> tsc.Runner:
    """造一个桩 runner：只认指定脚本名，其余调用大声失败（防意外真跑）."""

    def run(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        joined = " ".join(args)
        assert script_name in joined, f"意外子进程：{joined}"
        return 0, json.dumps(payload), ""

    return run


PRE_ALL_PASS = {
    "exit_code": 0,
    "results": [
        {"id": "env_paths", "name": ".env 关键路径", "status": "PASS", "message": "ok"},
        {"id": "tts_voice", "name": "音色守望", "status": "PASS", "message": "ok"},
    ],
}

PRE_WITH_SKIP = {
    "exit_code": 0,
    "results": [
        {"id": "env_paths", "name": ".env 关键路径", "status": "PASS", "message": "ok"},
        {"id": "tts_voice", "name": "音色守望", "status": "SKIP", "message": "引擎未启用"},
    ],
}

PRE_WITH_FAIL = {
    "exit_code": 1,
    "results": [
        {"id": "env_paths", "name": ".env 关键路径", "status": "PASS", "message": "ok"},
        {
            "id": "tts_voice",
            "name": "音色守望",
            "status": "FAIL",
            "message": "custom 段权重已不是守岸人",
            "fix_hint": "用钉 CWD 的启动面重启引擎",
        },
    ],
}

VERIFY_ALL_PASS = {
    "exit_code": 0,
    "findings": [
        {"id": "code_root", "name": "仓库根自证", "status": "PASS", "message": "ok"},
        {"id": "tts_refs", "name": "参考池深查", "status": "PASS", "message": "ok"},
    ],
}

VERIFY_WITH_FAIL = {
    "exit_code": 1,
    "findings": [
        {"id": "code_root", "name": "仓库根自证", "status": "PASS", "message": "ok"},
        {
            "id": "tts_gate",
            "name": "TTS 总闸",
            "status": "FAIL",
            "message": "BOT_TTS_ENABLED 未配置",
            "fix_hint": ".env 加 BOT_TTS_ENABLED=true",
        },
    ],
}


# ---------------------------------------------------------------------------
# 编排面
# ---------------------------------------------------------------------------

def test_orchestration_all_pass_exit_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_ALL_PASS))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    # 语料门文件不存在 → SKIP，放行
    rc = tsc.main(["--project-root", str(tmp_path)])
    assert rc == 0


def test_orchestration_skip_passes_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_WITH_SKIP))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    rc = tsc.main(["--project-root", str(tmp_path)])
    assert rc == 0  # SKIP 不假红，放行


def test_pre_restart_fail_propagates_exit_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_WITH_FAIL))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    rc = tsc.main(["--project-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "tts_voice" in out
    assert "用钉 CWD 的启动面重启引擎" in out  # FAIL 项自带处置指引透传


def test_verify_env_fail_propagates_exit_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_ALL_PASS))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_WITH_FAIL))
    rc = tsc.main(["--project-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "tts_gate" in out
    assert "BOT_TTS_ENABLED=true" in out


def test_corpus_gate_missing_is_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_ALL_PASS))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    report = tsc.run_all(project_root=tmp_path)  # tmp 下无 tests/test_tts_corpus_gate.py
    by_id = {s.id: s for s in report.steps}
    assert by_id["corpus_gate"].status == tsc.SKIP
    assert report.exit_code == 0


def test_corpus_gate_fail_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gate_dir = tmp_path / "tests"
    gate_dir.mkdir()
    (gate_dir / "test_tts_corpus_gate.py").write_text("# 语料门\n", encoding="utf-8")

    def runner_for_corpus_gate(
        args: list[str], cwd: Path, timeout: int
    ) -> tuple[int, str, str]:
        joined = " ".join(args)
        if "test_tts_corpus_gate.py" in joined:
            assert "no:cacheprovider" in joined, "语料门必须禁 pytest 缓存"
            assert "--basetemp" in joined, "语料门 basetemp 必须在源码树外"
            return 1, "1 failed", ""
        if "pre_restart_check" in joined:
            return 0, json.dumps(PRE_ALL_PASS), ""
        raise AssertionError(f"意外子进程：{joined}")

    monkeypatch.setattr(tsc, "_run_cmd", runner_for_corpus_gate)
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    report = tsc.run_all(project_root=tmp_path)
    by_id = {s.id: s for s in report.steps}
    assert by_id["corpus_gate"].status == tsc.FAIL
    assert report.exit_code == 1


def test_dry_run_runs_no_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def explode(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
        raise AssertionError("dry-run 不允许真跑子进程")

    monkeypatch.setattr(tsc, "_run_cmd", explode)
    monkeypatch.setattr(tsc, "_run_verify", explode)
    report = tsc.run_all(project_root=tmp_path, dry_run=True)
    assert report.exit_code == 0
    assert [s.id for s in report.steps] == ["pre_restart_check", "verify_env", "corpus_gate"]
    assert all("dry-run" in s.message for s in report.steps)


def test_json_output_structure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tsc, "_run_cmd", fake_runner("pre_restart_check", PRE_ALL_PASS))
    monkeypatch.setattr(tsc, "_run_verify", fake_runner("verify_chatbot_env", VERIFY_ALL_PASS))
    rc = tsc.main(["--project-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["exit_code"] == 0
    assert [s["id"] for s in payload["steps"]] == [
        "pre_restart_check",
        "verify_env",
        "corpus_gate",
    ]
    assert all(s["status"] in {tsc.PASS, tsc.SKIP} for s in payload["steps"])
