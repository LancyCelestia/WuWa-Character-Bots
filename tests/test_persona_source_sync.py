"""人格源-运行时副本一致性门测试（同步声明机制）.

离线 8 例（tmp_path，零真实文件写入）：一致绿 / 漂移红 / 副本缺失 skip /
锚定缺失红 / 副本不可读红 / 漂移后 --adopt 复绿 / CLI exit code / 锚定损坏红。
现网 2 例：真实副本×真实锚定的常驻门（副本缺失→skip 不红）；锚定交付物 schema。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.sync_persona_source as sync_mod


def _make_copy(tmp_path: Path, text: str = "守岸人核心人格 v1\n") -> Path:
    copy = tmp_path / "守岸人_核心人格.md"
    copy.write_text(text, encoding="utf-8")
    return copy


def test_check_ok_green(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    anchor = tmp_path / "anchor.json"
    sync_mod.adopt(copy, anchor, note="test")
    result = sync_mod.check(copy, anchor)
    assert result.status == sync_mod.OK
    assert not result.is_red
    assert not result.is_skip


def test_drift_after_copy_edit_red(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    anchor = tmp_path / "anchor.json"
    sync_mod.adopt(copy, anchor)
    copy.write_text("守岸人核心人格 v2 被人单方面改了\n", encoding="utf-8")
    result = sync_mod.check(copy, anchor)
    assert result.status == sync_mod.DRIFT
    assert result.is_red
    assert "--adopt" in result.message


def test_copy_missing_skip(tmp_path: Path) -> None:
    result = sync_mod.check(tmp_path / "不存在.md", tmp_path / "anchor.json")
    assert result.status == sync_mod.SKIP_COPY_MISSING
    assert not result.is_red


def test_anchor_missing_red(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    result = sync_mod.check(copy, tmp_path / "anchor.json")
    assert result.status == sync_mod.ANCHOR_MISSING
    assert result.is_red


def test_anchor_corrupted_red(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    anchor = tmp_path / "anchor.json"
    anchor.write_text("{ 不是 json", encoding="utf-8")
    result = sync_mod.check(copy, anchor)
    assert result.status == sync_mod.ANCHOR_MISSING
    assert result.is_red


def test_copy_unreadable_red(tmp_path: Path) -> None:
    copy_dir = tmp_path / "守岸人_核心人格.md"
    copy_dir.mkdir()  # 目录：read_bytes 抛 OSError 子类
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"copy_sha256": "x" * 64}), encoding="utf-8")
    result = sync_mod.check(copy_dir, anchor)
    assert result.status == sync_mod.COPY_UNREADABLE
    assert result.is_red


def test_adopt_after_drift_returns_green(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    anchor = tmp_path / "anchor.json"
    sync_mod.adopt(copy, anchor)
    copy.write_text("v2 经人工审阅的新版本\n", encoding="utf-8")
    assert sync_mod.check(copy, anchor).status == sync_mod.DRIFT
    sync_mod.adopt(copy, anchor, note="人工审阅 v2")  # 显式重录锚定
    assert sync_mod.check(copy, anchor).status == sync_mod.OK


def test_cli_exit_codes(tmp_path: Path) -> None:
    copy = _make_copy(tmp_path)
    anchor = tmp_path / "anchor.json"
    adopt_args = ["--adopt", "--copy", str(copy), "--anchor", str(anchor)]
    check_args = ["--check", "--copy", str(copy), "--anchor", str(anchor)]
    assert sync_mod.main([*adopt_args, "--note", "t"]) == 0
    assert sync_mod.main(check_args) == 0
    copy.write_text("v3\n", encoding="utf-8")
    assert sync_mod.main(check_args) == 1  # 漂移 → 红
    missing = ["--check", "--copy", str(tmp_path / "无.md"), "--anchor", str(anchor)]
    assert sync_mod.main(missing) == 0  # 副本缺失 → skip 不红


# ---- 现网常驻门（真实路径，只读）----


def test_live_persona_copy_matches_anchor() -> None:
    copy = sync_mod.resolve_copy_path()
    if not copy.exists():
        pytest.skip(f"生产人格副本不存在（bot 未部署/已移除），门跳过：{copy}")
    result = sync_mod.check(copy, sync_mod.ANCHOR_PATH)
    assert result.status == sync_mod.OK, result.message


def test_anchor_deliverable_schema() -> None:
    anchor_path = sync_mod.ANCHOR_PATH
    assert anchor_path.exists(), f"锚定交付物缺失：{anchor_path}（运行 --adopt 生成）"
    data = json.loads(anchor_path.read_text(encoding="utf-8"))
    for key in ("schema", "copy_path", "copy_sha256", "adopted_at", "source_snapshot"):
        assert key in data, f"锚定缺字段 {key}"
    assert len(data["copy_sha256"]) == 64
