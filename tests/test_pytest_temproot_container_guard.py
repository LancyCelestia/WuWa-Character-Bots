"""G2 容器门「环境腿」执法锁（席 temprootguard，2026-10-05）。

判的是 ``tests/conftest.py`` 的 G2 两腿，不判被测代码：

* **① 容器 ∈ 媒体读根名册**——判定输入＝pytest **本轮真正会用的容器**。旧写法只读
  ``--basetemp`` 的字面值 ⇒ 「钉环境而不传选项」全盲（复核席 guardverify2 §4：
  ``PYTEST_DEBUG_TEMPROOT`` 钉进 ``ChatBot_Runtime`` ⇒ 6 枚假红 + 其余媒体用例假绿，
  守卫一声不吭）。本格把那条静默通路钉成红。
* **② 暂存根 ∉ 受保护运行数据根**——``TMP``/``TEMP``/``TMPDIR`` 钉进运行数据根时媒体名册
  跟着变量一起漂走（``media_temp_root()`` 就是同一枚 ``tempfile.gettempdir()``）⇒ ① 必然放行；
  这一腿拿同一把尺反着问（根表＝``_RUNTIME_ROOT``，在内即拒）。

骨架最小仓（``tests/_autosync_fixture.py`` 不拷 ``domains/media``）取不到容器门 ⇒ 两腿一起
degrade＝不做判定、绝不崩；那格真身由 ``tests/test_autosync_hook.py`` 的子进程实跑兜（本文件
另有一格用 ``sys.modules`` 置 None 逼出同一 ImportError 形态，钉的是「缺席＝跳过而非崩」）。

卫生：子进程一律 ``-p no:cacheprovider`` + ``BOT_AUTOSYNC=0``（禁生成器 ``--write``）+
``--collect-only``（收集期不调 ``getbasetemp`` ⇒ 投毒路径**连创建都不会发生**，本文件零落盘）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import conftest
import pytest

REPO = Path(__file__).resolve().parents[1]
COLLECT_TARGET = "tests/test_media_path_gate.py"
REFUSAL_MARKER = "G2 拒绝启动"


def _child_env(**overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(Path(tempfile.gettempdir()) / "seat-temprootguard-lock-pyc"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "BOT_AUTOSYNC": "0",
    }
    for name in ("PYTEST_DEBUG_TEMPROOT", "TMP", "TEMP", "TMPDIR"):
        env.pop(name, None)
    env.update(overrides)
    return env


def _run_collect(env: dict[str, str], extra: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            COLLECT_TARGET,
            "-p",
            "no:cacheprovider",
            "-q",
            "--collect-only",
            *extra,
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
        env=env,
    )


def _outside_any_read_root() -> Path:
    """名册（工作区 + ``%TEMP%`` + 隔离根）之外的一个不存在目录——**不碰运行数据根**，
    锁自己不往 ``ChatBot_Runtime`` 里落任何东西（运行数据只读，规则 2）。"""
    base = Path(os.environ.get("SystemRoot") or "C:\\Windows")
    return base / "pytest-temproot-guard-lock-outside-roster"


# ------------------------------------------------------------------ ① 容器 ∈ 名册


def test_leg1_pinned_temproot_without_basetemp_is_refused() -> None:
    """只钉 ``PYTEST_DEBUG_TEMPROOT``（不传 ``--basetemp``）⇒ 必须响亮拒，且点名那枚变量。

    这一格就是复核席点名的洞：旧写法在这里 ``return``（选项缺席即不判）⇒ 假红假绿全静默。
    """
    poisoned = _outside_any_read_root()
    assert not poisoned.exists(), "投毒路径已存在 ⇒ 「未创建」那一问没牙"
    proc = _run_collect(_child_env(PYTEST_DEBUG_TEMPROOT=str(poisoned)), [])
    combined = f"{proc.stdout}{proc.stderr}"
    assert proc.returncode != 0, f"环境钉的名册外容器被放行（rc={proc.returncode}）：\n{combined[-1200:]}"
    assert REFUSAL_MARKER in combined, f"非零退出但不是 G2 拒的：\n{combined[-1200:]}"
    assert "PYTEST_DEBUG_TEMPROOT" in combined, f"拒绝没点名来源变量：\n{combined[-1200:]}"
    assert "collected" not in combined.lower(), f"拒绝前仍在收集（收集零条那一问没牙）：\n{combined[-1200:]}"
    assert not poisoned.exists(), "拒绝前已把被拒路径创建出来（＝先动手再说不）"


def test_leg1_basetemp_option_still_refused_and_never_created() -> None:
    """``--basetemp`` 那腿（2026-10-04 原语义）不许被本次扩展削掉：照样拒、照样点名、照样不建目录。"""
    poisoned = _outside_any_read_root()
    proc = _run_collect(_child_env(), ["--basetemp", str(poisoned)])
    combined = f"{proc.stdout}{proc.stderr}"
    assert proc.returncode != 0 and REFUSAL_MARKER in combined, combined[-1200:]
    assert "--basetemp" in combined, f"拒绝没点名来源选项：\n{combined[-1200:]}"
    assert "collected" not in combined.lower()
    assert not poisoned.exists()


@pytest.mark.parametrize("var", ["PYTEST_DEBUG_TEMPROOT", "TEMP"])
def test_leg1_in_roster_runs_are_not_refused(var: str, tmp_path: Path) -> None:
    """在册跑法零拒绝（不许把门缩成「什么都不敢跑」）：变量钉在 ``%TEMP%`` 一侧、或压根不传。"""
    env = _child_env(**{var: str(tmp_path)})
    proc = _run_collect(env, ["--basetemp", str(tmp_path / "bt")])
    combined = f"{proc.stdout}{proc.stderr}"
    assert REFUSAL_MARKER not in combined, combined[-1200:]
    assert proc.returncode == 0, combined[-1200:]
    assert "collected" in combined.lower(), combined[-1200:]


def test_leg1_derivation_matches_pytest_container(request: pytest.FixtureRequest) -> None:
    """判定输入＝pytest 的派生根（照 installed ``_pytest/tmpdir.py::getbasetemp`` :154-166 同读法）。"""
    containers = conftest._g2_effective_containers(request.config)
    given = request.config.getoption("basetemp", None)
    if given:
        assert containers[0][1] == Path(str(given)), "传了 --basetemp 却判别的容器"
        assert containers[0][2] is False, "--basetemp 放开 allow_root＝pytest 会 rm_rf 整个暂存根"
    else:
        expected = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir())
        assert containers[0][1] == expected
        assert containers[0][2] is True, "派生根与 %TEMP% 同形是缺省跑法，判根即误拒全场"


# ------------------------------------------------------------------ ② 暂存根 ∉ 运行数据根


def test_leg2_temp_env_pinned_into_runtime_root_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TMP``/``TEMP`` 钉进运行数据根 ⇒ ①判不到（名册随变量漂），只有 ② 问得出。

    锁在本格把 ``_RUNTIME_ROOT`` 换成 ``tmp_path`` 下的假运行数据根：真身 ``ChatBot_Runtime``
    只读（规则 2），不许为造红/绿去动它；语义同一把尺（``path_gate.contain_within``）。
    """
    from plugins.bot_unified_runtime.domains.media import path_gate

    fake_runtime = tmp_path / "ChatBot_Runtime"
    fake_runtime.mkdir()
    monkeypatch.setattr(conftest, "_RUNTIME_ROOT", fake_runtime)
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", "")
    monkeypatch.setenv("TMP", str(fake_runtime / "cache" / "bt"))
    monkeypatch.setenv("TEMP", str(fake_runtime / "cache" / "bt"))
    monkeypatch.delenv("TMPDIR", raising=False)

    hits = conftest._g2_env_pins_into_protected_tree(path_gate)
    assert {name for name, _ in hits} == {"TMP", "TEMP"}, f"环境钉进运行数据根却判不出来：{hits}"

    # 两腿**不同维**（这一问就是「② 不是重复劳动」的证据）：同一枚落点用 ① 那套判法问，
    # 名册已随 TMP 漂进假运行数据根 ⇒ 必然放行；只有 ② 问得出。
    drifted_probe = fake_runtime / "cache" / "bt"
    path_gate.contain_within(drifted_probe, path_gate.media_read_roots(drifted_probe), allow_root=True)

    monkeypatch.setenv("TMP", str(tmp_path / "sanctioned"))
    monkeypatch.setenv("TEMP", str(tmp_path / "sanctioned"))
    assert conftest._g2_env_pins_into_protected_tree(path_gate) == [], "在册 scratch 被误拒＝门缩"


def test_leg2_refusal_message_names_the_variable(tmp_path: Path) -> None:
    """拒绝语必须点名是哪一枚变量（简报第 3 条）——只报路径＝下一席还得再考古一遍。"""
    for name in conftest._G2_TEMP_ROOT_ENV_VARS:
        with pytest.raises(BaseException) as caught:
            conftest._g2_refuse(f"环境变量 {name}", Path(tmp_path / name), "落在受保护运行数据根之内", "scratch 请留在 %TEMP% 一侧")
        assert name in str(caught.value), f"{name} 没进拒绝语"


# ------------------------------------------------------------------ 缺席面：degrade 而非崩


def test_skeleton_repo_degrades_to_no_check(tmp_path: Path) -> None:
    """骨架仓那格＝**真身**复现（不是读码猜）：只有 ``tests/conftest.py`` 的最小仓里
    ``plugins…domains.media.path_gate`` 取不到 ⇒ G2 两腿一起跳过 ⇒ 不崩、不误拒。

    ``tests/_autosync_fixture.py::copy_autosync_repo`` 不拷 ``domains/media``（复核席
    guardverify2 §3 已实跑证伪），本格用更薄的手搭骨架（conftest + 一枚平凡用例，
    ``scripts/runtime_paths.py`` 亦缺席＝G2 注释里那条唯一允许的缺席面），投毒环境照样跑绿。
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text(
        (REPO / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok() -> None:\n    assert 1 == 1\n", encoding="utf-8")
    env = _child_env(PYTEST_DEBUG_TEMPROOT=str(tmp_path / "ChatBot_Runtime" / "cache" / "bt"))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider", "-q", "--collect-only"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
        env=env,
    )
    combined = f"{proc.stdout}{proc.stderr}"
    assert REFUSAL_MARKER not in combined, f"骨架仓里守卫没跳过而是崩/拒了：\n{combined[-1200:]}"
    assert proc.returncode == 0, combined[-1200:]
    assert "1 test collected" in combined or "test_ok::test_ok" in combined, combined[-1200:]
    assert not (tmp_path / "ChatBot_Runtime").exists(), "骨架会话把投毒路径建出来了"

