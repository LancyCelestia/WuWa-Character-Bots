"""H-9d 体检牙：persona 腿第二判据「在册头像存在性点名」（全离线）.

背景：`pre_restart_check.py` 的 persona 格此前只查副本与锚定一致，不查在册
`qq.avatar_path` 指向的文件是否真在盘上 ⇒ danya 那种「册里写着头像路径、盘上
根本没有」要到下发腿才红（卡片腿 FileNotFoundError）。判据面：
① 非空 avatar_path 缺件 → FAIL 点名 persona 与确切路径，且给两条出路；
② 文件实存 → 沿用副本腿状态（PASS）并带 xN 实存计数；
③ 空 avatar_path ＝ 不切头像项，不算缺件、不进计数；
④ 人格册目录缺席（开发/假环境）→ 不假红；
⑤ 副本腿本身 SKIP 也掩盖不住头像缺件（照样 FAIL）；
⑥ 副本腿 FAIL 时修复指引必须同时留 --adopt 与头像两条出路（旧锁认 --adopt）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import pre_restart_check as prc

PASS, SKIP, FAIL = prc.PASS, prc.SKIP, prc.FAIL

AVATAR_REL = "data/avatar/persona_avatar_danya_1080.jpg"


def _project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """假项目根 + 假运行时数据根（env 直接传，不读生产 .env）."""
    root = tmp_path / "proj"
    (root / "personas" / "registry").mkdir(parents=True)
    rt = tmp_path / "rt_data"
    (rt / "avatar").mkdir(parents=True)
    return root, {"BOT_RUNTIME_DATA_DIR": str(rt)}


def _register(root: Path, persona_id: str, avatar_path: str) -> None:
    (root / "personas" / "registry" / f"{persona_id}.json").write_text(
        json.dumps({"persona_id": persona_id, "qq": {"avatar_path": avatar_path}}, ensure_ascii=False),
        encoding="utf-8",
    )


def _patch_run_cmd(monkeypatch: pytest.MonkeyPatch, rc: int, out: str) -> None:
    monkeypatch.setattr(prc, "run_cmd", lambda args, cwd, timeout=600: (rc, out, ""))


def test_missing_avatar_fails_by_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, env = _project(tmp_path)
    _register(root, "danya", AVATAR_REL)
    _patch_run_cmd(monkeypatch, 0, "[绿] 副本与锚定一致 sha256=ab12")
    result = prc.check_persona_sync(env, root)
    assert result.status == FAIL
    assert "danya" in result.message and AVATAR_REL.rsplit("/", 1)[-1] in result.message
    assert str(tmp_path / "rt_data") in result.message  # 点名的是解析后的确切落点
    assert "要落" in result.fix_hint and "按实申报未落" in result.fix_hint


def test_present_avatar_stays_pass_and_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, env = _project(tmp_path)
    _register(root, "danya", AVATAR_REL)
    (tmp_path / "rt_data" / "avatar" / Path(AVATAR_REL).name).write_text("jpg", encoding="utf-8")
    _patch_run_cmd(monkeypatch, 0, "[绿] 副本与锚定一致 sha256=ab12")
    result = prc.check_persona_sync(env, root)
    assert result.status == PASS and "在册头像 x1 实存" in result.message


def test_empty_avatar_path_is_not_a_defect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, env = _project(tmp_path)
    _register(root, "shorekeeper", "")
    _patch_run_cmd(monkeypatch, 0, "[绿] 副本与锚定一致 sha256=ab12")
    result = prc.check_persona_sync(env, root)
    assert result.status == PASS and "在册头像 x0 实存" in result.message


def test_registry_dir_absent_does_not_fake_red(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _patch_run_cmd(monkeypatch, 0, "[SKIP] 生产人格副本不存在")
    result = prc.check_persona_sync({}, root)
    assert result.status == SKIP and "未扫" in result.message


def test_skip_copy_leg_still_fails_on_missing_avatar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, env = _project(tmp_path)
    _register(root, "danya", AVATAR_REL)
    _patch_run_cmd(monkeypatch, 0, "[SKIP] 生产人格副本不存在")
    result = prc.check_persona_sync(env, root)
    assert result.status == FAIL and "缺件" in result.message


def test_sync_fail_hint_keeps_adopt_and_adds_avatar_roads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, env = _project(tmp_path)
    _register(root, "danya", AVATAR_REL)
    _patch_run_cmd(monkeypatch, 1, "[红] 生产人格副本被单方面改动")
    result = prc.check_persona_sync(env, root)
    assert result.status == FAIL
    assert "--adopt" in result.fix_hint and "要落" in result.fix_hint
    assert "副本被单方面改动" in result.message and "在册头像缺件" in result.message


def test_unreadable_registry_is_named_not_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, env = _project(tmp_path)
    (root / "personas" / "registry" / "broken.json").write_text("{", encoding="utf-8")
    _patch_run_cmd(monkeypatch, 0, "[绿] 副本与锚定一致 sha256=ab12")
    result = prc.check_persona_sync(env, root)
    assert result.status == FAIL and "不可读" in result.message
