"""verify_chatbot_env 离线回归：T24 五面假安心的治后矩阵（全 tmp_path 桩，零网络）.

面→例对照（五面对照表全文见 report-T87.md）：
  F1 ROOT 错指   → test_copied_tool_fails_loud（复刻原件搬出仓库即崩的场景，
                    治后须大声 FAIL 而非 ImportError 崩）
  F2 静默缺省   → test_fail_when_no_env_file / test_skip_when_tts_disabled /
                  test_env_prod_overrides_env
  F3 故障面错配 → 未知键 ⑥b / 竖线 ③ / 语种 ④ / 文件缺失 / 池空 ⑧ /
                  空路径静默跳过 / 数值域 ⑦ / 枚举
  F4 空断言     → test_pass_pool_size_not_pinned_to_eight（池大小不钉 ==8）+
                  test_pass_probability_inline_comment（行内注释不假红）
  F5 -O 全绿    → test_optimize_flag_cannot_bypass（子进程 -O 双向锁死）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import verify_chatbot_env as vce

TOOL = PROJECT_ROOT / "scripts" / "verify_chatbot_env.py"


# ---------------------------------------------------------------------------
# 假环境构造
# ---------------------------------------------------------------------------

def make_proj(
    tmp_path: Path,
    *,
    env_lines: list[str] | None = None,
    prod_lines: list[str] | None = None,
    ref_files: tuple[str, ...] = ("ref_a.wav", "ref_b.wav"),
) -> Path:
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    if env_lines is not None:
        (root / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    if prod_lines is not None:
        (root / ".env.prod").write_text("\n".join(prod_lines) + "\n", encoding="utf-8")
    for name in ref_files:
        (root / name).write_bytes(b"RIFFfake" + b"\x00" * 16)
    return root


def ref_json(root: Path, items: list[str]) -> str:
    """把「文件名|文本|语种」条目换成绝对 posix 路径后序列化成 JSON 列表."""
    real: list[str] = []
    for item in items:
        head, sep, tail = item.partition("|")
        resolved = str((root / head).as_posix()) if head else head  # 空路径原样保留
        real.append(resolved + sep + tail)
    return json.dumps(real, ensure_ascii=False)


def base_env(root: Path, **overrides: str) -> list[str]:
    lines = [
        "BOT_TTS_ENABLED=true",
        f"BOT_TTS_GPTSOVITS_DIR={root.as_posix()}",
        f"BOT_TTS_REF_AUDIOS={ref_json(root, ['ref_a.wav|你好呀|zh', 'ref_b.wav'])}",
    ]
    for key, value in overrides.items():
        lines.append(f"{key}={value}")
    return lines


def run_json_capture(root: Path, capsys) -> tuple[int, dict]:
    code = vce.main(["--json", "--project-root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def findings_by_id(payload: dict) -> dict[str, dict]:
    return {f["id"]: f for f in payload["findings"]}


def run_subprocess(
    args: list[str],
    *,
    cwd: Path | None = None,
    optimize: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable]
    if optimize:
        cmd.append("-O")
    cmd += [str(TOOL), *args]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=300,
        check=False,
    )


# ---------------------------------------------------------------------------
# F2 + 正常态
# ---------------------------------------------------------------------------

def test_pass_normal(tmp_path, capsys):
    root = make_proj(tmp_path, env_lines=base_env(root=tmp_path / "proj"))
    code, payload = run_json_capture(root, capsys)
    assert code == 0, payload
    assert payload["exit_code"] == 0
    assert all(f["status"] != vce.FAIL for f in payload["findings"])
    env_source = findings_by_id(payload)["env_source"]
    assert ".env" in env_source["message"]


def test_fail_when_no_env_file(tmp_path, capsys):
    root = make_proj(tmp_path, env_lines=None, prod_lines=None, ref_files=())
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    env_source = findings_by_id(payload)["env_source"]
    assert env_source["status"] == vce.FAIL
    assert "未找到" in env_source["message"]


def test_skip_when_tts_disabled(tmp_path, capsys):
    lines = base_env(tmp_path / "proj")
    lines[0] = "BOT_TTS_ENABLED=false"
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 0
    gate = findings_by_id(payload)["tts_gate"]
    assert gate["status"] == vce.SKIP
    assert "未启用" in gate["message"]


def test_env_prod_overrides_env(tmp_path, capsys):
    prod = base_env(tmp_path / "proj")
    env = ["BOT_TTS_ENABLED=false"]
    root = make_proj(tmp_path, env_lines=env, prod_lines=prod)
    code, payload = run_json_capture(root, capsys)
    assert code == 0
    gate = findings_by_id(payload)["tts_gate"]
    assert gate["status"] != vce.SKIP  # prod 覆盖后 enabled=true，深查应执行
    env_source = findings_by_id(payload)["env_source"]
    assert ".env.prod" in env_source["message"]


# ---------------------------------------------------------------------------
# F3 故障面（生产装载器结构性盲区 + Config 域闸继承）
# ---------------------------------------------------------------------------

def test_fail_unknown_tts_key_with_hint(tmp_path, capsys):
    lines = base_env(tmp_path / "proj", BOT_TTS_API_URK="http://127.0.0.1:9880")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    keys = findings_by_id(payload)["tts_keys"]
    assert keys["status"] == vce.FAIL
    assert "BOT_TTS_API_URK" in keys["message"]
    assert "BOT_TTS_API_URL" in keys["message"]  # difflib 纠错提示


def test_fail_pipe_in_ref_text(tmp_path, capsys):
    lines = base_env(
        tmp_path / "proj",
        BOT_TTS_REF_AUDIOS=ref_json(tmp_path / "proj", ["ref_a.wav|前半句|后半句|zh"]),
    )
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert refs["status"] == vce.FAIL
    assert "段" in refs["message"]


def test_fail_bad_lang(tmp_path, capsys):
    lines = base_env(
        tmp_path / "proj",
        BOT_TTS_REF_AUDIOS=ref_json(tmp_path / "proj", ["ref_a.wav|你好|中文"]),
    )
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert "语种" in refs["message"]


def test_fail_missing_ref_file(tmp_path, capsys):
    lines = base_env(
        tmp_path / "proj",
        BOT_TTS_REF_AUDIOS=ref_json(tmp_path / "proj", ["ghost.wav|你好|zh"]),
    )
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert "不存在" in refs["message"]


def test_fail_empty_pool_but_enabled(tmp_path, capsys):
    lines = base_env(tmp_path / "proj", BOT_TTS_REF_AUDIOS="[]")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert refs["status"] == vce.FAIL


def test_fail_empty_path_item(tmp_path, capsys):
    # 生产 parse_ref_audios 会静默跳过空路径条目——池悄悄缩水，体检器必须拦
    lines = base_env(
        tmp_path / "proj",
        BOT_TTS_REF_AUDIOS=ref_json(tmp_path / "proj", ["|你好|zh", "ref_a.wav|你好|zh"]),
    )
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert "空路径" in refs["message"]


def test_fail_relative_ref_without_base_dir(tmp_path, capsys):
    lines = ["BOT_TTS_ENABLED=true", 'BOT_TTS_REF_AUDIOS=["refs/a.wav|你好|zh"]']
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert "BOT_TTS_GPTSOVITS_DIR" in refs["message"]


def test_fail_range_violation_probability(tmp_path, capsys):
    lines = base_env(tmp_path / "proj", BOT_TTS_AUTO_REPLY_PROBABILITY="2.0")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    load = findings_by_id(payload)["config_load"]
    assert load["status"] == vce.FAIL
    assert "probability" in load["message"]


def test_fail_enum_violation_split_method(tmp_path, capsys):
    lines = base_env(tmp_path / "proj", BOT_TTS_TEXT_SPLIT_METHOD="cut999")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    load = findings_by_id(payload)["config_load"]
    assert load["status"] == vce.FAIL
    assert "cut999" in load["message"]


def test_fail_engine_dir_configured_but_absent(tmp_path, capsys):
    lines = base_env(tmp_path / "proj", BOT_TTS_GPTSOVITS_DIR="Z:/no/such/dir")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 1
    refs = findings_by_id(payload)["tts_refs"]
    assert refs["status"] == vce.FAIL


# ---------------------------------------------------------------------------
# F4 空断言（缺省值抄成期望值的一族）
# ---------------------------------------------------------------------------

def test_pass_pool_size_not_pinned_to_eight(tmp_path, capsys):
    lines = base_env(
        tmp_path / "proj",
        BOT_TTS_REF_AUDIOS=ref_json(tmp_path / "proj", ["ref_a.wav|你好呀|zh"]),
    )
    root = make_proj(tmp_path, env_lines=lines, ref_files=("ref_a.wav",))
    code, payload = run_json_capture(root, capsys)
    assert code == 0, payload  # 合法缩池/扩池都不假红（原件 ==8 假红已除）


def test_pass_probability_inline_comment(tmp_path, capsys):
    # T24 P1-5 ⑥e：生产剥行内注释、原体检器不剥 → 好配置被判坏；治后须一致
    lines = base_env(tmp_path / "proj")
    lines.append("BOT_TTS_AUTO_REPLY_PROBABILITY=0.05  # 五percent")
    root = make_proj(tmp_path, env_lines=lines)
    code, payload = run_json_capture(root, capsys)
    assert code == 0, payload


# ---------------------------------------------------------------------------
# F5 -O 不可绕过 + F1 ROOT 错指
# ---------------------------------------------------------------------------

def test_optimize_flag_cannot_bypass(tmp_path):
    good = make_proj(tmp_path / "g", env_lines=base_env(tmp_path / "g" / "proj"))
    bad_lines = base_env(tmp_path / "b" / "proj", BOT_TTS_AUTO_REPLY_PROBABILITY="2.0")
    bad = make_proj(tmp_path / "b", env_lines=bad_lines)
    ok = run_subprocess(["--project-root", str(good)], optimize=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    fatal = run_subprocess(["--project-root", str(bad)], optimize=True)
    assert fatal.returncode == 1, fatal.stdout + fatal.stderr
    assert "OK" not in fatal.stdout


def test_copied_tool_fails_loud(tmp_path):
    """复刻 T24 P1-1：工具被搬出 scripts/ 后 parents[1] 指错根——治后大声 FAIL."""
    foreign = tmp_path / "elsewhere" / "tools"
    foreign.mkdir(parents=True)
    copied = foreign / "verify_chatbot_env.py"
    shutil.copyfile(TOOL, copied)
    proc = run_subprocess(["--project-root", str(tmp_path)], cwd=tmp_path)
    # 注意：跑的是「复制件」，不是仓内 TOOL——显式断言复制件路径出现/仓内件语义
    cmd = [sys.executable, str(copied), "--project-root", str(tmp_path)]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(tmp_path), env=env, timeout=300, check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "仓库根" in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr  # 不是 ImportError 崩，是人话 FAIL


def test_code_root_points_at_repo():
    assert (vce.CODE_ROOT / "plugins" / "bot_unified_runtime" / "config.py").is_file()


def test_module_has_no_bare_assert():
    """F5 静态锁：工具源码零裸 assert（-O 下断言不消失）."""
    source = TOOL.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("assert "), stripped
