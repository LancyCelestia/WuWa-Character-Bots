"""B1 导入器波（2026-09-28）：``scripts/import_meme_packs.py`` 的 --pin 与内容守卫回归。

锁三件事（全离线，tmp_path 里造真包目录/真库，零源码树写入）：

1. ``--pin``（CLI 旗标名就是这个）⇒ **本次插入的行**写 ``persona_owned=1``，
   30 天按龄裁剪（protect_persona 开着时）护得住它们；不带 --pin 逐字节旧形态（0）；
   dry-run + --pin 一行都不写。
2. 内容守卫：假 .png（HTML 改名件）与 0 字节空件**无条件**拒；``--min-side``
   （缺省 300）拒缩略图，0 = 关。
3. 判据不在脚本里另造一份——脚本用路径加载的 ``image_guard`` 真身就是本仓唯一魔数表。
"""

from __future__ import annotations

import importlib.util
import io
import sqlite3
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_meme_packs.py"


def _load_importer() -> Any:
    spec = importlib.util.spec_from_file_location("_import_meme_packs_b1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png_bytes(side: int, *, pad_to: int = 0) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (side % 251, 5, 9)).save(buffer, format="PNG")
    data = buffer.getvalue()
    if pad_to > len(data):
        data += b"\x00" * (pad_to - len(data))
    return data


def _persona_owned_of(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {
            str(row[0]): int(row[1])
            for row in connection.execute("SELECT md5, persona_owned FROM memes")
        }
    finally:
        connection.close()


def _pack(tmp_path: Path, *, fake: bool = False, empty: bool = False) -> tuple[Path, list[str]]:
    stage = tmp_path / "stage"
    pack = stage / "测试包"
    pack.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    for index in range(2):
        name = f"sticker-{index}.png"
        # 两枚必须**字节不同**：库按 md5 去重（`memes.md5` 是唯一键），同形两枚会被
        # 正确判成重复件 ⇒ 断言 2 行就永远只能收到 1 行（本席 09-28 踩过：夹具用同一
        # 组参数造两枚，红点看着像导入器漏收，其实是去重腿在守规矩）。
        (pack / name).write_bytes(_png_bytes(320 + 8 * index, pad_to=2_048))
        made.append(name)
    if fake:
        (pack / "fake.png").write_bytes(b"<!DOCTYPE html><html>" + b"nope" * 900)
    if empty:
        (pack / "empty.png").write_bytes(b"")
    return stage, made


def test_pin_writes_persona_owned_on_inserted_rows(tmp_path: Path) -> None:
    module = _load_importer()
    stage, _made = _pack(tmp_path)
    db_path = tmp_path / "lib.sqlite3"
    report = module.run(
        source=stage,
        db_path=db_path,
        target=tmp_path / "library",
        dry_run=False,
        pin=True,
    )
    assert report["failed"] == []
    assert len(report["imported"]) == 2
    owned = _persona_owned_of(db_path)
    assert owned and set(owned.values()) == {1}, "--pin 后新行必须 persona_owned=1"


def test_without_pin_rows_stay_unpinned(tmp_path: Path) -> None:
    module = _load_importer()
    stage, _made = _pack(tmp_path)
    db_path = tmp_path / "lib.sqlite3"
    report = module.run(
        source=stage, db_path=db_path, target=tmp_path / "library", dry_run=False
    )
    assert len(report["imported"]) == 2
    owned = _persona_owned_of(db_path)
    assert owned and set(owned.values()) == {0}


def test_dry_run_with_pin_writes_nothing(tmp_path: Path) -> None:
    module = _load_importer()
    stage, _made = _pack(tmp_path)
    db_path = tmp_path / "lib.sqlite3"
    report = module.run(
        source=stage,
        db_path=db_path,
        target=tmp_path / "library",
        dry_run=True,
        pin=True,
    )
    assert len(report["imported"]) == 2, "DRY-RUN 仍要如实列出会入库的行"
    if db_path.exists():  # store 建表即落文件（既有语义），锁的是**行**为空
        assert _persona_owned_of(db_path) == {}
    assert not any((tmp_path / "library").glob("*.png")), "DRY-RUN 一张图都不许拷进库目录"


def test_cli_flag_name_is_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() 的 argparse 真吃 ``--pin`` 这个名字（旗标名漂移当场红）。"""
    module = _load_importer()
    # prefer 名单从假 .env 读（与既有 prefer 用例同一手法），本测试不碰真实 .env。
    (tmp_path / ".env").write_text("BOT_MEME_LIBRARY_PREFER=[]\n", encoding="utf-8")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    stage, _made = _pack(tmp_path)
    db_path = tmp_path / "lib.sqlite3"
    argv = [
        "import_meme_packs.py",
        "--source",
        str(stage),
        "--db",
        str(db_path),
        "--target",
        str(tmp_path / "library"),
        "--pin",
        "--min-side",
        "0",
    ]
    monkeypatch.setattr("sys.argv", argv)
    assert module.main() == 0
    owned = _persona_owned_of(db_path)
    assert owned and set(owned.values()) == {1}


def test_content_guards_reject_fake_and_empty(tmp_path: Path) -> None:
    module = _load_importer()
    stage, _made = _pack(tmp_path, fake=True, empty=True)
    db_path = tmp_path / "lib.sqlite3"
    report = module.run(
        source=stage, db_path=db_path, target=tmp_path / "library", dry_run=False
    )
    assert len(report["imported"]) == 2, "两枚真贴纸照收"
    skipped = report["skipped_by_kind"]
    assert skipped.get("bad_magic") == 1, "假 .png（HTML 改名件）必须被魔数闸拒"
    assert skipped.get("empty") == 1, "0 字节空件必须被拒"
    assert "fake.png" not in {Path(item["file"]).name for item in report["imported"]}


def test_min_side_floor_rejects_thumbnails_only_when_on(tmp_path: Path) -> None:
    module = _load_importer()
    stage = tmp_path / "stage"
    pack = stage / "缩略图包"
    pack.mkdir(parents=True)
    (pack / "thumb.png").write_bytes(_png_bytes(16, pad_to=4_096))
    db_path = tmp_path / "lib.sqlite3"
    report = module.run(
        source=stage,
        db_path=db_path,
        target=tmp_path / "library",
        dry_run=False,
        min_side=300,
    )
    assert report["imported"] == []
    assert report["skipped_by_kind"].get("below_min_side") == 1
    assert not db_path.exists() or _persona_owned_of(db_path) == {}
    # 关掉下限（min_side=0）同一枚图就收：开关语义的另一腿。
    db_path2 = tmp_path / "lib2.sqlite3"
    report2 = module.run(
        source=stage, db_path=db_path2, target=tmp_path / "library2", dry_run=False
    )
    assert len(report2["imported"]) == 1


def test_importer_uses_the_central_image_guard_not_a_second_one() -> None:
    """禁第二真身：脚本的魔数判定必须来自 domains/media/image_guard.py 那一枚文件本体。

    ⚠ 判据**不是**函数对象同一性：脚本是按路径 `spec_from_file_location` 加载真身的
    （它不能 `import plugins.bot_unified_runtime...`——那枚包的 `__init__.py` 会把
    NoneBot 整套依赖拖进一个离线脚本），两次加载必然得到两个模块对象，`is` 永远假。
    真正要钉死的是两件事：①读的就是那一枚文件；②脚本自己没再抄一份魔数表。
    """
    module = _load_importer()
    from plugins.bot_unified_runtime.domains.media import image_guard

    assert Path(module.IMAGE_GUARD.__file__).resolve() == Path(image_guard.__file__).resolve(), (
        "导入器的图片判定不是中央 image_guard 那一枚文件 ⇒ 第二真身"
    )
    script_source = SCRIPT.read_text(encoding="utf-8")
    smuggled = [
        marker
        for marker in (r"\xff\xd8", r"\x89PNG", "GIF8", "RIFF")
        if marker in script_source
    ]
    assert not smuggled, f"脚本里抄了魔数字面 {smuggled} ⇒ 判据长成两份"
    # 注毒自证：这把尺在真身上扫得到同一批字面 ⇒ 它不是空跑的。
    central = Path(image_guard.__file__).read_text(encoding="utf-8")
    assert any(marker in central for marker in (r"\xff\xd8", r"\x89PNG")), (
        "中央魔数表里扫不到这些字面 ⇒ 上面那条断言永远不会咬，尺是装饰"
    )
