"""离线导入器的 prefer 名单必须与现网同键同源（BOT_MEME_LIBRARY_PREFER）。

背景锁：导入脚本曾硬编码 5 词名单，而现网已扩到 10 词 ⇒ 同一张「爱弥斯」图，
在线入库吃 ×2.0、离线导入不吃，权重差一档（库内同类图两种命运）。
本文件锁两件事：① 名单真身来自配置键而非脚本自带；② 命中名单的行确实拿到乘子。
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_meme_packs.py"


def _load_importer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("_import_meme_packs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 只挪「名单真身所在文件」的定位；ROOT 本身不动——store 源文件按 ROOT 找。
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    return module


def test_prefer_terms_read_the_config_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        'BOT_MEME_LIBRARY_PREFER=["爱弥斯", "达妮娅", "守岸人"]\n', encoding="utf-8"
    )
    module = _load_importer(monkeypatch, tmp_path)
    assert module._prefer_terms() == ["爱弥斯", "达妮娅", "守岸人"]


def test_prefer_terms_tolerates_comma_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "BOT_MEME_LIBRARY_PREFER=爱弥斯,达妮娅\n", encoding="utf-8"
    )
    module = _load_importer(monkeypatch, tmp_path)
    assert module._prefer_terms() == ["爱弥斯", "达妮娅"]


def test_prefer_terms_falls_back_when_key_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("BOT_OTHER=1\n", encoding="utf-8")
    module = _load_importer(monkeypatch, tmp_path)
    assert module._prefer_terms() == list(module.PREFER_FALLBACK)


def test_new_rows_get_the_prefer_multiplier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """命中 prefer 的新行必须拿到 ×2.0——名单换源后权重才不脱钩。"""
    (tmp_path / ".env").write_text('BOT_MEME_LIBRARY_PREFER=["爱弥斯"]\n', encoding="utf-8")
    module = _load_importer(monkeypatch, tmp_path)

    source = tmp_path / "stage" / "爱弥斯"
    source.mkdir(parents=True)
    # B1 守卫波修正：旧写法把 base64 **文本原文**当字节落盘（文件头成 R0lGO…，并非图），
    # 新魔数闸按假图拦下。这里解码成真 GIF87a 字节——本用例锁的是 prefer 乘子，不是假扩展名。
    payload = base64.b64decode("R0lGODdhAQABAIAAAP8AAAAAACwAAAAAAQABAAACAkQBADs=")
    (source / "爱弥斯_眨眼.gif").write_bytes(payload)

    db_path = tmp_path / "meme_library.sqlite3"
    target = tmp_path / "library"
    report = module.run(
        source=tmp_path / "stage",
        db_path=db_path,
        target=target,
        dry_run=False,
    )
    assert report["failed"] == []
    assert len(report["imported"]) == 1
    row = sqlite3.connect(str(db_path)).execute(
        "select weight, scene_tags, description from memes"
    ).fetchone()
    assert row is not None
    weight, scene_tags, description = row
    assert json.loads(scene_tags) == ["爱弥斯"]
    assert "爱弥斯" in description
    assert weight >= 2.0, f"命中 prefer 却未拿到乘子：weight={weight}"
