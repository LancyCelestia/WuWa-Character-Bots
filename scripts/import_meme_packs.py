"""守岸人Bot 表情包仓库离线批量导入脚本（幂等、可重复运行）。

从本地表情包目录递归收集图片（gif/webp/png/jpg/jpeg），按 MD5 去重后
拷贝到 data/meme_library/ 并写入 data/meme_library.sqlite3。元数据逻辑复用
plugins.bot_unified_runtime.sources.meme_library.MemeLibraryStore（单一事实源）。

设计约束：
- 只导入图片：视频（.mov/.mp4 等）与说明文本（.txt）不导入——发送管线只支持图片；
- 幂等：同一 md5 无论重复运行多少次都只入库一次；
- 原子性：先写临时文件再 os.replace，单条记录“先落文件、后写库”，中断后重跑自愈；
- 最小干预：库里已存在的 md5 不打标、不改权重；仅对本次新入库的行写标签；
- 并发安全：Bot 正在运行时也可安全执行，库操作均为短事务（SQLite timeout 15s）。

标签策略：description=原文件名主干；scene_tags=来源“表情包子包/内层文件夹”层级；
persona_hint=common；权重由 store 按既有规则计算（这些图不含优先级提示词，权重保持 1.0）。

用法：
    python scripts/import_meme_packs.py --source <表情包目录> [--dry-run]
    python scripts/import_meme_packs.py --source <目录> --db <db> --target <目录>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from runtime_paths import runtime_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = runtime_path("data/meme_library.sqlite3")
DEFAULT_TARGET = runtime_path("data/meme_library")
IMAGE_EXTS = {".gif", ".webp", ".png", ".jpg", ".jpeg"}
VIDEO_EXTS = {".mov", ".mp4", ".webm", ".avi", ".mkv"}
PREFER = ["守岸人", "岸宝", "鸣潮", "战双帕弥什", "库洛"]


def _load_store(db_path: Path) -> Any:
    """按文件路径加载 MemeLibraryStore，避免触发包 __init__ 中的 NoneBot 依赖。"""
    source = ROOT / "plugins" / "bot_unified_runtime" / "sources" / "meme_library.py"
    spec = importlib.util.spec_from_file_location("_meme_library_source", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemeLibraryStore(str(db_path), prefer=PREFER)


def _md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_tags(pack_dir: Path, file_path: Path) -> list[str]:
    """来源文件夹层级作为场景标签：内层文件夹 + 表情包子包名，去重限长。"""
    tags: list[str] = []
    parent = file_path.parent
    if parent != pack_dir:
        tags.append(parent.name.strip())
    tags.append(pack_dir.name.strip())
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        tag = tag[:40]
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result[:6]


def _discover(pack_root: Path) -> tuple[list[tuple[Path, Path]], dict[str, int]]:
    """返回 ([(文件, 所属表情包子包), ...], 跳过统计)。子包即顶层一级目录。"""
    images: list[tuple[Path, Path]] = []
    skipped: dict[str, int] = {}
    for pack_dir in sorted(
        (path for path in pack_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        for path in sorted(pack_dir.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in IMAGE_EXTS:
                images.append((path, pack_dir))
            else:
                kind = "video" if ext in VIDEO_EXTS else "other"
                skipped[kind] = skipped.get(kind, 0) + 1
    # 根目录直属图片（罕见）：以 pack_root 自身作为子包。
    for path in sorted(pack_root.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            images.append((path, pack_root))
    return images, skipped


def run(
    *,
    source: Path,
    db_path: Path,
    target: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if not source.is_dir():
        raise SystemExit(f"来源目录不存在：{source}")
    target.mkdir(parents=True, exist_ok=True)

    store = _load_store(db_path)
    images, skipped = _discover(source)
    report: dict[str, Any] = {
        "source": str(source),
        "db": str(db_path),
        "target": str(target),
        "images_seen": len(images),
        "skipped_by_kind": skipped,
        "imported": [],
        "duplicate_existing": [],
        "duplicate_in_batch": [],
        "failed": [],
        "dry_run": dry_run,
    }

    known_md5: set[str] = set()
    for path, pack_dir in images:
        try:
            md5 = _md5_of(path)
        except OSError as exc:
            report["failed"].append({"file": str(path), "error": f"hash: {exc}"})
            continue
        if store.exists(md5):
            report["duplicate_existing"].append(str(path))
            continue
        if md5 in known_md5:
            report["duplicate_in_batch"].append(str(path))
            continue
        known_md5.add(md5)

        ext = path.suffix.lower().lstrip(".") or "gif"
        destination = target / f"{md5}.{ext}"
        if dry_run:
            report["imported"].append(
                {
                    "file": str(path),
                    "pack": pack_dir.name,
                    "md5": md5,
                    "ext": ext,
                    "bytes": path.stat().st_size,
                }
            )
            continue

        try:
            if not destination.exists():
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{md5}.", suffix=f".{ext}", dir=str(target)
                )
                tmp_path = Path(tmp_name)
                try:
                    with os.fdopen(fd, "wb") as out, path.open("rb") as handle:
                            shutil.copyfileobj(handle, out, 1024 * 1024)
                    os.replace(tmp_path, destination)
                except BaseException:
                    tmp_path.unlink(missing_ok=True)
                    raise
            if _md5_of(destination) != md5:
                raise OSError("拷贝后校验失败（md5 不一致）")
        except OSError as exc:
            report["failed"].append({"file": str(path), "error": f"copy: {exc}"})
            continue

        try:
            result = store.add(md5=md5, path=str(destination), ext=ext, group_id="")
            inserted = bool(result["inserted"])
        except Exception as exc:  # noqa: BLE001
            report["failed"].append({"file": str(path), "error": f"db add: {exc}"})
            continue
        if not inserted:
            # 与在线监听器并发撞库：保留监听器刚写入的记录，不覆盖其标签。
            report["duplicate_existing"].append(str(path))
            continue

        try:
            description = path.stem.strip()[:120]
            store.apply_tags(
                md5,
                is_meme=True,
                description=description,
                emotion_tags=[],
                scene_tags=_scene_tags(pack_dir, path),
                persona_hint="common",
                nsfw_score=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            # 行已写入且文件已就位，标签失败不破坏可用性；记录并继续。
            report["failed"].append({"file": str(path), "error": f"tags: {exc}"})
        report["imported"].append(
            {
                "file": str(path),
                "pack": pack_dir.name,
                "md5": md5,
                "ext": ext,
                "bytes": path.stat().st_size,
            }
        )
    return report


def _print_report(report: dict[str, Any]) -> None:
    mode = "（DRY-RUN，未写入）" if report["dry_run"] else "（已执行）"
    print(f"来源：{report['source']} {mode}")
    print(f"数据库：{report['db']}")
    print(f"图片目录：{report['target']}")
    print(f"图片文件：{report['images_seen']}")
    for kind, count in sorted(report["skipped_by_kind"].items()):
        print(f"跳过({kind})：{count}")
    print(f"本次入库：{len(report['imported'])}")
    print(f"库里已存在（md5 去重）：{len(report['duplicate_existing'])}")
    print(f"本次批次内重复：{len(report['duplicate_in_batch'])}")
    print(f"失败：{len(report['failed'])}")
    for item in report["failed"]:
        print(f"  FAIL {item['file']} -> {item['error']}")
    total_bytes = sum(int(item.get("bytes") or 0) for item in report["imported"])
    print(f"入库字节数：{total_bytes}")


def main() -> int:
    parser = argparse.ArgumentParser(description="守岸人Bot 表情包仓库批量导入")
    parser.add_argument("--source", required=True, help="表情包来源目录")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 元数据库路径")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="图片落盘目录")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写入")
    args = parser.parse_args()

    report = run(
        source=Path(args.source),
        db_path=Path(args.db),
        target=Path(args.target),
        dry_run=args.dry_run,
    )
    _print_report(report)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
