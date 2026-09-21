"""V2.1 §13 autosync 门禁回归（A3 席，2026-09-17）。

锁定三层语义（合同：docs/design/backend-v2-implementation-guide.md §13）：
1. conftest 纯函数 ``is_autosync_enabled``：仅值 ``"1"``（dev.ps1 未显式
   设置时的默认）启用；显式 ``0/false/no/off``（大小写不敏感）及任何其他
   值一律禁用；未设置（裸 pytest/CI）禁用——与历史 ``!= "1"`` 字节级兼容。
2. conftest ``run_autosync``：禁用时零 subprocess 调用，command_catalog /
   doc_sync / verify_hashes 三处 ``--write`` 联动全部跳过；启用时行为与
   现状一致（含哈希基线重录留痕 warning）。
3. ``scripts/dev.ps1::Invoke-Test``：仅当调用方未显式设置 BOT_AUTOSYNC 时
   才默认 1；显式值（含 0/false/no/off）原样透传，绝不被覆盖——否则外层
   设 0 会被改回 1，conftest 自动 ``--write`` 重录预期把真实回归「洗绿」。

全部离线：生成器调用用 fake subprocess，绝不真实写渲染哈希/生成物；
dev.ps1 侧只执行从源码中正则钉出的那一行守卫（进程内设 env 后回显），
零写盘。
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFTEST_PATH = REPO_ROOT / "tests" / "conftest.py"
DEV_PS1_PATH = REPO_ROOT / "scripts" / "dev.ps1"

POWERSHELL = shutil.which("powershell") or shutil.which("powershell.exe")

# dev.ps1 守卫行的源码契约：默认值必须在「未显式设置」条件内。
_GUARD_RE = re.compile(
    r"if\s*\(-not\s*\(Test-Path\s+env:BOT_AUTOSYNC\)\)"
    r"\s*\{\s*\$env:BOT_AUTOSYNC\s*=\s*\"1\"\s*\}"
)
# 旧的缺陷形态：无条件覆盖（整行就是赋值，无任何守卫）。
_BARE_ASSIGN_RE = re.compile(r"^\s*\$env:BOT_AUTOSYNC\s*=\s*\"1\"\s*$", re.MULTILINE)

# 显式关闭口径（大小写不敏感由用例本身覆盖；空值/其他真值拼写一律视为不启用，
# 与历史 `!= "1"` 字节级兼容）。
_OFF_VALUES = ["0", "false", "FALSE", "False", "no", "No", "OFF", "off", "", "true", "yes", "2"]


def _load_conftest():
    """从磁盘加载 tests/conftest.py 的新副本（测的就是被改的文件本身）。"""
    spec = importlib.util.spec_from_file_location("_conftest_autosync_under_test", CONFTEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dev_guard_line() -> str:
    """钉出 dev.ps1 的 BOT_AUTOSYNC 守卫行；契约破坏（退回无条件覆盖）即红。"""
    text = DEV_PS1_PATH.read_text(encoding="utf-8-sig")
    match = _GUARD_RE.search(text)
    assert match, (
        "scripts/dev.ps1 必须保留 BOT_AUTOSYNC 守卫 "
        "(if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = \"1\" })；"
        "V2.1 §13：无条件覆盖会把外层显式 0 改回 1，自动重录洗绿真实回归"
    )
    assert not _BARE_ASSIGN_RE.search(text), (
        "scripts/dev.ps1 不得出现无条件 $env:BOT_AUTOSYNC = \"1\" 覆盖行"
    )
    return match.group(0)


# ---------------------------------------------------------------------------
# 1. 纯函数判定矩阵（conftest 侧）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1", True), (" 1", False), (None, False), *[(v, False) for v in _OFF_VALUES]],
)
def test_is_autosync_enabled_matrix(raw: str | None, expected: bool) -> None:
    assert _load_conftest().is_autosync_enabled(raw) is expected


# ---------------------------------------------------------------------------
# 2. run_autosync：禁用 = 零生成器联动；启用 = 行为与现状一致
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, *_OFF_VALUES])
def test_run_autosync_disabled_never_invokes_generators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str | None
) -> None:
    mod = _load_conftest()
    if raw is None:
        monkeypatch.delenv("BOT_AUTOSYNC", raising=False)
    else:
        monkeypatch.setenv("BOT_AUTOSYNC", raw)
    calls: list[list[str]] = []

    def _boom(cmd, **kwargs):
        calls.append(cmd)
        raise AssertionError("autosync 禁用时不得调用任何生成器子进程")

    # except 元组引用 subprocess.SubprocessError，fake 命名空间必须带全。
    monkeypatch.setattr(
        mod, "subprocess", SimpleNamespace(run=_boom, SubprocessError=subprocess.SubprocessError)
    )
    assert mod.run_autosync(root=tmp_path) == []
    assert calls == []


def test_run_autosync_enabled_invokes_all_write_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_conftest()
    monkeypatch.setenv("BOT_AUTOSYNC", "1")
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        mod, "subprocess", SimpleNamespace(run=_fake_run, SubprocessError=subprocess.SubprocessError)
    )
    assert mod.run_autosync(root=tmp_path) == []
    assert len(calls) == len(mod._AUTOSYNC_STEPS)
    for cmd, (script, _output) in zip(calls, mod._AUTOSYNC_STEPS):
        assert cmd[1].replace(os.sep, "/").endswith(script)
        assert cmd[-1] == "--write"


def test_run_autosync_enabled_reports_hash_baseline_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_conftest()
    monkeypatch.setattr(mod, "_hash_baseline_changed", [])
    monkeypatch.setenv("BOT_AUTOSYNC", "1")

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name
        if script == "verify_hashes.py":
            target = tmp_path / mod._HASH_MANIFEST
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'{"card_a": "deadbeef"}')
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        mod, "subprocess", SimpleNamespace(run=_fake_run, SubprocessError=subprocess.SubprocessError)
    )
    with pytest.warns(UserWarning, match="哈希基线"):
        changed = mod.run_autosync(root=tmp_path)
    assert changed == [mod._HASH_MANIFEST]
    assert mod._hash_baseline_changed == ["card_a"]


# ---------------------------------------------------------------------------
# 3. dev.ps1：守卫契约 + 真实行行为（显式值透传，未设置才默认 1）
# ---------------------------------------------------------------------------


def test_dev_ps1_source_contract() -> None:
    _dev_guard_line()


@pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe not available")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "1"), ("0", "0"), ("false", "false"), ("OFF", "OFF"), ("1", "1")],
)
def test_dev_ps1_guard_respects_explicit_env(
    tmp_path: Path, raw: str | None, expected: str
) -> None:
    line = _dev_guard_line()
    env = {k: v for k, v in os.environ.items() if k.upper() != "BOT_AUTOSYNC"}
    if raw is not None:
        env["BOT_AUTOSYNC"] = raw
    proc = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f'{line}; Write-Output "RESULT=$env:BOT_AUTOSYNC"',
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(tmp_path),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert f"RESULT={expected}" in proc.stdout, proc.stdout
