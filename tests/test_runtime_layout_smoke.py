"""自测锁：``scripts/runtime_layout_smoke.py`` 的生成物残留扫面（席 R1，2026-10-02）。

台账 #68★ 的口径＝**扩扫面与它的自测锁必须同批**，所以本文件与那次扩面是一件事，
不是后续补充。三条腿：

1. 注毒腿（真跑，不是读源码数字符串）：在 ``tmp_path`` 造出五类残留——字节码、
   工具缓存、树内 venv、树内 pytest basetemp、distribution 元数据壳——逐类断言
   门**必须**报出该类的类别标签；本波实咬的两格（433 枚 ``.pyc`` 落进 ``plugins/**``
   把门打成 FAIL；一枚**空** ``Bot_Character_Bots.egg-info/`` 让 ``importlib.metadata``
   认到一个无 Version 的 distribution 吃掉三枚 ``test_error_report``）各有专腿。
2. 反向不误伤腿：一份"看着像本项目源码树"的合法副本（``.git``、``node_modules``、
   ``site-packages`` 里的 ``*.dist-info``、名为 ``env`` 的普通源码目录、只有两枚
   ``test_*<N>`` 子目录的文档示例目录、空的 ``logs/``）必须**零**命中。
   现算依据：真实树里空目录有 1198 枚 ⇒「空目录」本身绝不能当判据；
   basetemp 内容形状全树只命中 ``cb-w9chk/``（46 枚子目录）⇒ 阈值 3 没有灰区。
3. 端到端腿：把两枚脚本 + 一份假 Runtime 根拷进**仓外**副本，真起子进程跑
   ``main()``——干净副本 rc 0，注毒副本 rc 1 且 stdout 点名是哪两类。
   这一腿同时锁住归因文案：字节码那行必须写着「绕过 dev.ps1」，
   不许把 ``scripts/dev.ps1``（它自己 pin 了 ``PYTHONDONTWRITEBYTECODE`` 与
   ``PYTHONPYCACHEPREFIX``、并把 ruff/mypy 的 ``--cache-dir`` 送到 Runtime）报成凶手。

全部离线、全部只写 ``tmp_path``：本文件不删、不移动、不写真实工作树任何东西。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import runtime_layout_smoke as gate  # 须在 sys.path 补丁之后（门本体住 scripts/）

# 本波两格实咬 + 旧扫面全盲的四类，加上原有字节码那一格。
ALL_CLASSES = (
    gate.RESIDUE_PYTHON_BYTECODE,
    gate.RESIDUE_TOOL_CACHE,
    gate.RESIDUE_IN_TREE_VENV,
    gate.RESIDUE_PYTEST_SCRATCH,
    gate.RESIDUE_DISTRIBUTION_METADATA,
)


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_clean_project(root: Path) -> Path:
    """一棵"合法源码树"骨架：任何残留类都不该在它上面响。"""
    _write(root / "bot.py", "print('ok')\n")
    _write(root / "plugins/bot_unified_runtime/__init__.py", "")
    _write(root / "plugins/bot_unified_runtime/domains/core/config/roles.py", "")
    _write(root / "plugins/bot_unified_runtime/domains/schedule/store/reminders.py", "")
    _write(root / "tests/test_example.py", "def test_example():\n    assert True\n")
    # 被 .gitignore 吞掉但项目明确保留的第三方/岛与空目录：一律不算残留。
    _write(root / ".git/config", "[core]\n")
    _write(root / "webui/node_modules/left-pad/index.js", "")
    _write(root / "site-packages/nonebot-2.0.0.dist-info/METADATA", "Version: 2.0.0\n")
    _write(root / "logs/.keep-placeholder", "")
    (root / "logs").mkdir(exist_ok=True)
    (root / "probes").mkdir(exist_ok=True)
    # 名为 env 的普通源码目录（无 venv 形状）不该被当成虚拟环境。
    _write(root / "env/settings.py", "VALUE = 1\n")
    # 低于 basetemp 形状阈值的目录（2 枚 < 3）不算 scratch。
    (root / "docs/tmp_examples/test_alpha0").mkdir(parents=True)
    (root / "docs/tmp_examples/test_beta1").mkdir(parents=True)
    return root


# --------------------------------------------------------------------------- 注毒器
def _poison_bytecode(root: Path) -> None:
    pycache = root / "plugins/bot_unified_runtime/runtime/__pycache__"
    pycache.mkdir(parents=True)
    _write(pycache / "ingress.cpython-312.pyc", "")
    _write(root / "scripts/stray.pyo", "")


def _poison_tool_cache(root: Path) -> None:
    _write(root / ".mypy_cache/3.12/cache.json", "{}")
    _write(root / ".ruff_cache/CACHEDIR.TAG", "")
    _write(root / "plugins/bot_unified_runtime/.pytest_cache/v/cache/lastfailed", "{}")


def _poison_in_tree_venv(root: Path) -> None:
    _write(root / ".venv/Lib/site-packages/bot_character_bots-0.1.0.dist-info/METADATA",
           "Version: 0.1.0\n")
    (root / ".venv/Scripts").mkdir(parents=True, exist_ok=True)
    # 弱名 env 必须有硬形状才算：这枚带 pyvenv.cfg，所以确实是一棵树内 venv。
    _write(root / "env/pyvenv.cfg", "home = C:/Python312\n")


def _poison_pytest_scratch(root: Path) -> None:
    for name in ("test_absorb_dual_evidence_mark0", "test_admin_can_list_approve_an0",
                 "test_eat_image_quality_0"):
        (root / "cb-w9chk" / name).mkdir(parents=True)
    _write(root / "scratch_root/basetemp/keep.txt", "")
    _write(root / ".pytest_tmp_probe/x.txt", "")


def _poison_distribution_metadata(root: Path) -> None:
    # 本波实咬的那一格：一枚**空**目录，git status 永远看不见。
    (root / "Bot_Character_Bots.egg-info").mkdir(parents=True)
    _write(root / "plugins/another.egg-info/PKG-INFO", "Metadata-Version: 2.1\nName: another\n")


_POISONERS: dict[str, tuple[Callable[[Path], None], tuple[str, ...]]] = {
    gate.RESIDUE_PYTHON_BYTECODE: (
        _poison_bytecode,
        ("plugins/bot_unified_runtime/runtime/__pycache__/", "scripts/stray.pyo"),
    ),
    gate.RESIDUE_TOOL_CACHE: (
        _poison_tool_cache,
        (".mypy_cache/", ".ruff_cache/", "plugins/bot_unified_runtime/.pytest_cache/"),
    ),
    gate.RESIDUE_IN_TREE_VENV: (_poison_in_tree_venv, (".venv/", "env/")),
    gate.RESIDUE_PYTEST_SCRATCH: (
        _poison_pytest_scratch,
        ("cb-w9chk/", "scratch_root/basetemp/", ".pytest_tmp_probe/"),
    ),
    gate.RESIDUE_DISTRIBUTION_METADATA: (
        _poison_distribution_metadata,
        ("Bot_Character_Bots.egg-info/", "plugins/another.egg-info/"),
    ),
}


@pytest.mark.parametrize("class_tag", ALL_CLASSES)
def test_legit_project_layout_is_never_flagged(tmp_path: Path, class_tag: str) -> None:
    """反向不误伤腿（每类各跑一次：注毒前的基线必须是零命中）。"""
    root = _make_clean_project(tmp_path / "repo")
    assert gate.scan_generated_residue(root) == {}, (
        f"legitimate source layout must produce no residue finding for {class_tag}"
    )


@pytest.mark.parametrize("class_tag", ALL_CLASSES)
def test_poisoned_class_is_scanned_out_and_named(tmp_path: Path, class_tag: str) -> None:
    """注毒腿：造出该类残留 ⇒ 门必须红、点名哪一类，且只报这一类（无连带误伤）。"""
    root = _make_clean_project(tmp_path / "repo")
    poisoner, expected_paths = _POISONERS[class_tag]
    poisoner(root)

    findings = gate.scan_generated_residue(root)

    assert class_tag in findings, (
        f"blind spot: {class_tag} residue is not visible to the gate; findings={findings}"
    )
    assert set(findings) == {class_tag}, (
        f"only {class_tag} was planted, but the gate also fired {sorted(set(findings) - {class_tag})}: {findings}"
    )
    reported = "\n".join(findings[class_tag])
    for expected in expected_paths:
        assert expected in reported, f"{expected} must be named under [{class_tag}]: {reported}"


def test_every_residue_class_is_scannable_in_one_tree(tmp_path: Path) -> None:
    """五类同树混注 ⇒ 五格全部现身（扩面覆盖锁，防"加了一类顺手瞎了一类"）。"""
    root = _make_clean_project(tmp_path / "repo")
    for poisoner, _paths in _POISONERS.values():
        poisoner(root)

    findings = gate.scan_generated_residue(root)

    assert set(findings) == set(ALL_CLASSES), f"expected five classes, got {sorted(findings)}"


def test_empty_egg_info_shell_reports_the_importlib_metadata_hazard(tmp_path: Path) -> None:
    """本波实咬格专项：空 ``*.egg-info`` ⇒ 必须说清"无 Version 的 distribution"。"""
    root = _make_clean_project(tmp_path / "repo")
    (root / "Bot_Character_Bots.egg-info").mkdir()

    findings = gate.scan_generated_residue(root)
    lines = gate.format_generated_residue_errors(findings)

    assert len(findings[gate.RESIDUE_DISTRIBUTION_METADATA]) == 1
    text = "\n".join(lines)
    assert "[distribution-metadata]" in text
    assert "Bot_Character_Bots.egg-info" in text
    assert "empty" in text and "Version" in text


def test_metadata_shell_without_version_line_is_named_differently(tmp_path: Path) -> None:
    root = _make_clean_project(tmp_path / "repo")
    _write(root / "Shadowed.egg-info/PKG-INFO", "Metadata-Version: 2.1\nName: shadowed\n")

    lines = gate.format_generated_residue_errors(gate.scan_generated_residue(root))

    assert any("carries no Version:" in line for line in lines), lines


def test_bytecode_attribution_blames_the_bypassed_route_not_dev_ps1(tmp_path: Path) -> None:
    """归因锁：dev.ps1 pin 了缓存外置，红来自**绕过**它的裸跑，文案不许倒果为因。"""
    root = _make_clean_project(tmp_path / "repo")
    _poison_bytecode(root)
    _poison_tool_cache(root)

    lines = gate.format_generated_residue_errors(gate.scan_generated_residue(root))
    text = "\n".join(lines)

    assert "[python-bytecode]" in text and "[tool-cache]" in text
    assert "PYTHONDONTWRITEBYTECODE" in text and "PYTHONPYCACHEPREFIX" in text
    assert "bypassed dev.ps1" in text
    assert "--cache-dir" in text


def test_missing_root_is_not_a_crash(tmp_path: Path) -> None:
    assert gate.scan_generated_residue(tmp_path / "does-not-exist") == {}


def test_islands_are_never_named_as_offenders(tmp_path: Path) -> None:
    """.git / node_modules / site-packages 只剪枝不记账（门不许把自己走进第三方树）。"""
    root = _make_clean_project(tmp_path / "repo")

    findings = gate.scan_generated_residue(root)
    names = [entry for paths in findings.values() for entry in paths]

    assert names == []
    for island in (".git", "node_modules", "site-packages"):
        assert not any(island in entry for entry in names)


# --------------------------------------------------------------------------- 真树腿
def test_real_workspace_scan_is_fully_classified_and_bounded() -> None:
    """对真实工作树跑一次：只允许已知类别、不许越界、不许把门自己拖死。"""
    started = time.monotonic()
    findings = gate.scan_generated_residue(gate.PROJECT_ROOT)
    elapsed = time.monotonic() - started

    assert set(findings) <= set(ALL_CLASSES), f"unknown residue class: {sorted(findings)}"
    for tag, paths in findings.items():
        assert paths, f"empty class must be dropped, not reported: {tag}"
        for entry in paths:
            relative = Path(entry.split("/")[0].split(" ")[0])
            assert (gate.PROJECT_ROOT / relative).exists(), f"finding escapes the tree: {entry}"
    assert elapsed < 120.0, f"residue scan took {elapsed:.1f}s"
    assert all(tag in gate.RESIDUE_ATTRIBUTION for tag in ALL_CLASSES)


# ----------------------------------------------------------------------- 端到端真跑
_REQUIRED_ENV_KEYS = (
    "BOT_RUNTIME_DATA_DIR",
    "BOT_TEST_RUNTIME_DATA_DIR",
    "BOT_TEST_PROCESS",
    "BOT_TEST_FORBIDDEN_RUNTIME_ROOTS",
    "BOT_TEST_RUNTIME_GUARD_MODE",
    "BOT_PERSONA_FILES",
    "BOT_KNOWLEDGE_FILES",
    "BOT_CARD_ASSET_DIR",
    "LOCALSTORE_USE_CWD",
    "LOCALSTORE_CACHE_DIR",
    "LOCALSTORE_CONFIG_DIR",
    "LOCALSTORE_DATA_DIR",
)


def _build_repo_copy(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """把门的本体拷进**仓外**副本，并配一份假 Runtime 根，让 ``main()`` 别的原因全绿。

    拷贝而不是复制粘贴逻辑：副本永远等于当场真身，自测不会随着改门而变陈旧。
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("runtime_paths.py", "runtime_layout_smoke.py"):
        shutil.copy2(SCRIPTS_DIR / name, repo / "scripts" / name)

    runtime_root = tmp_path / "ChatBot_Runtime"
    data_root = runtime_root / "runtime_data"
    data_root.mkdir(parents=True)
    _write(data_root / "knowledge_embeddings.sqlite3", "")
    _write(data_root / "knowledge_faiss.index", "")
    _write(runtime_root / "card_render_assets/shell.svg", "<svg/>")
    persona = _write(repo.parent / "personas/shorekeeper/prompt.md", "守岸人\n")
    knowledge = _write(runtime_root / "knowledge/wiki.md", "# wiki\n")
    for sub in ("cache", "config", "localstore_data"):
        (runtime_root / sub).mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    for key in _REQUIRED_ENV_KEYS:
        env.pop(key, None)
    # ``BOT_PERSONA_FILES`` / ``BOT_KNOWLEDGE_FILES`` 走 JSON 列表口径
    # （``_configured_list`` 先试 ``json.loads``，再退分号）。
    env.update(
        {
            "BOT_RUNTIME_DATA_DIR": str(data_root),
            "BOT_PERSONA_FILES": json.dumps([str(persona)]),
            "BOT_KNOWLEDGE_FILES": json.dumps([str(knowledge)]),
            "BOT_CARD_ASSET_DIR": str(runtime_root / "card_render_assets"),
            "LOCALSTORE_USE_CWD": "false",
            "LOCALSTORE_CACHE_DIR": str(runtime_root / "cache"),
            "LOCALSTORE_CONFIG_DIR": str(runtime_root / "config"),
            "LOCALSTORE_DATA_DIR": str(runtime_root / "localstore_data"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(runtime_root / "pycache"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "BOT_AUTOSYNC": "0",
        }
    )
    return repo, env


def _run_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # 台账 #47★：subprocess.run 不钉 encoding 必崩（中文 stdout 在 Windows 上炸 UnicodeDecodeError）。
    return subprocess.run(
        [sys.executable, "scripts/runtime_layout_smoke.py"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def test_end_to_end_clean_copy_exits_zero(tmp_path: Path) -> None:
    repo, env = _build_repo_copy(tmp_path)
    _write(repo / "plugins/bot_unified_runtime/__init__.py", "")

    proc = _run_gate(repo, env)

    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "runtime-layout: PASS" in proc.stdout
    assert "generated_residue=absent" in proc.stdout


def test_end_to_end_poisoned_copy_exits_nonzero_and_names_both_classes(tmp_path: Path) -> None:
    """注毒端到端腿：仓外副本里造一枚真字节码件 + 一枚空 egg-info ⇒ 门必须红。"""
    repo, env = _build_repo_copy(tmp_path)
    _write(repo / "plugins/bot_unified_runtime/__init__.py", "")
    pycache = repo / "plugins/bot_unified_runtime/domains/render/__pycache__"
    pycache.mkdir(parents=True)
    _write(pycache / "renderer.cpython-312.pyc", "")
    (repo / "Bot_Character_Bots.egg-info").mkdir()

    proc = _run_gate(repo, env)

    assert proc.returncode == 1, f"poison escaped the gate: stdout={proc.stdout}"
    assert "[python-bytecode]" in proc.stdout, proc.stdout
    assert "[distribution-metadata]" in proc.stdout, proc.stdout
    assert "Bot_Character_Bots.egg-info" in proc.stdout
    assert "bypassed dev.ps1" in proc.stdout
    assert "runtime-layout: PASS" not in proc.stdout
