"""守岸人Bot 表情包仓库离线批量导入脚本（幂等、可重复运行）。

从本地表情包目录递归收集图片（gif/webp/png/jpg/jpeg），按 MD5 去重后
拷贝到 data/meme_library/ 并写入 data/meme_library.sqlite3。元数据逻辑复用
plugins.bot_unified_runtime.domains.meme.sources.meme_library.MemeLibraryStore（单一事实源）。

设计约束：
- 只导入图片：视频（.mov/.mp4 等）与说明文本（.txt）不导入——发送管线只支持图片；
- 内容守卫（B1 波，2026-09-28）：0 字节空件与「扩展名对但文件头对不上登记签名」的
  假图**无条件**拒（skipped 记 empty/bad_magic）；CLI 再按短边像素下限拒缩略图/图标
  （--min-side，缺省 MIN_SIDE=300，先例 eat.py _IMG_MIN_SIDE；0=关）。判据唯一真身
  plugins/bot_unified_runtime/domains/media/image_guard.py（路径加载，禁第二魔数表）；
- 幂等：同一 md5 无论重复运行多少次都只入库一次；
- 原子性：先写临时文件再 os.replace，单条记录“先落文件、后写库”，中断后重跑自愈；
- 最小干预：库里已存在的 md5 不打标、不改权重；仅对本次新入库的行写标签；
- 并发安全：Bot 正在运行时也可安全执行，库操作均为短事务（SQLite timeout 15s）。

标签策略：description=原文件名主干；scene_tags=来源“表情包子包/内层文件夹”层级；
persona_hint=common；权重由 store 的 `_score_weight` 按既有规则算（文件名/目录里带
「守岸人／鸣潮／…」会吃 `_PRIORITY_HINTS` 乘子，命中 prefer 词再 ×2.0）。

用法：
    python scripts/import_meme_packs.py --source <表情包目录> [--dry-run]
    python scripts/import_meme_packs.py --source <目录> --db <db> --target <目录>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# 两条路径都要进 sys.path：store 模块内部是 `plugins....` 绝对导入（需仓库根），
# 而 `runtime_paths` 住在 scripts/ 里。此前只靠“脚本启动时 scripts/ 自动在 path 上”
# ⇒ 直接跑炸 ModuleNotFoundError，测试按文件路径加载本模块时同样炸。
for _entry in (str(ROOT), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# runtime_paths 住在 scripts/，必须在上面把两条路径补进 sys.path 之后才导得到。
from runtime_paths import runtime_path

DEFAULT_DB = runtime_path("data/meme_library.sqlite3")
DEFAULT_TARGET = runtime_path("data/meme_library")
#: prefer 名单的真身所在（测试里可临时指向别的 .env，ROOT 本身不许挪——store 源文件按它定位）。
ENV_FILE = ROOT / ".env"
IMAGE_EXTS = {".gif", ".webp", ".png", ".jpg", ".jpeg"}
# B1 内容守卫（2026-09-28）：短边像素下限，先例 domains/food/capabilities/eat.py
# 的 _IMG_MIN_SIDE = 300 —— min 边 < 300 多为图标/占位缩略图，不进表情库。
MIN_SIDE = 300
VIDEO_EXTS = {".mov", ".mp4", ".webm", ".avi", ".mkv"}
#: 仅作 `.env` 缺键时的兜底；真值一律走 :func:`_prefer_terms`，与现网同键同源。
PREFER_FALLBACK = ["守岸人", "岸宝", "鸣潮", "战双帕弥什", "库洛"]

# 权重只在 store.apply_tags 里算，而 prefer 是它的一个乘子（每命中一词 ×2.0）。
# 名单在这里硬编码过一次，现网 BOT_MEME_LIBRARY_PREFER 后来到 10 词 ⇒ 离线导入的
# 新角色图比在线入库的同类图少一档权重（同一张图两种命运）。故 prefer 改读 .env。
def _prefer_terms() -> list[str]:
    try:
        from dotenv import dotenv_values

        raw = str(dotenv_values(ENV_FILE).get("BOT_MEME_LIBRARY_PREFER") or "")
    except Exception as exc:  # noqa: BLE001 - 读不到配置就退回兜底名单，导入不许因此中断
        print(f"WARN prefer 读取失败 type={type(exc).__name__}，使用兜底名单")
        return list(PREFER_FALLBACK)
    if not raw:
        return list(PREFER_FALLBACK)
    try:
        terms = json.loads(raw)
    except ValueError:
        terms = [item.strip() for item in raw.split(",")]
    terms = [str(item).strip() for item in (terms if isinstance(terms, list) else []) if str(item).strip()]
    return terms or list(PREFER_FALLBACK)


def _load_store(db_path: Path, prefer: list[str]) -> Any:
    """按文件路径加载 MemeLibraryStore，避免触发包 __init__ 中的 NoneBot 依赖。"""
    source = (
        ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "meme"
        / "sources"
        / "meme_library.py"
    )
    spec = importlib.util.spec_from_file_location("_meme_library_source", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemeLibraryStore(str(db_path), prefer=prefer)


def _load_image_guard():
    """按文件路径加载内容质检唯一真身（与 _load_store 同一手法，不触包 __init__）。

    B1 守卫波（2026-09-28）：导入面与在线收库、randpic 池子共用同一套判据，
    禁在脚本里另抄魔数表（第二真身）。
    """
    source = (
        ROOT
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "media"
        / "image_guard.py"
    )
    spec = importlib.util.spec_from_file_location("_image_guard_source", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IMAGE_GUARD = _load_image_guard()


def _content_reject(path: Path, *, min_side: int) -> str:
    """单件内容质检：空串=放行，非空=拒绝代号（进 skipped 统计）。

    空件与假图（文件头对不上登记签名）无条件拒；``min_side`` > 0 才付 PIL
    解图头的代价（0 = 关，programmatic 入口的旧默认，见 run 的签名注释）。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return "unreadable"
    if size <= 0:
        return "empty"
    header = IMAGE_GUARD.read_header(path)
    if header is None:
        return "unreadable"
    if not IMAGE_GUARD.header_is_image(header):
        return "bad_magic"
    if min_side > 0:
        side = IMAGE_GUARD.min_side_of_file(path)
        if side is None:
            return "undecodable"
        if side < min_side:
            return "below_min_side"
    return ""


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


def _discover(pack_root: Path, *, min_side: int = 0) -> tuple[list[tuple[Path, Path]], dict[str, int]]:
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
                # B1 内容守卫：假图/空件/缩略图不进候选（代号并进 skipped 统计）。
                reason = _content_reject(path, min_side=min_side)
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
                else:
                    images.append((path, pack_dir))
            else:
                kind = "video" if ext in VIDEO_EXTS else "other"
                skipped[kind] = skipped.get(kind, 0) + 1
    # 根目录直属图片（罕见）：以 pack_root 自身作为子包。
    for path in sorted(pack_root.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            reason = _content_reject(path, min_side=min_side)
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
            else:
                images.append((path, pack_root))
    return images, skipped


def run(
    *,
    source: Path,
    db_path: Path,
    target: Path,
    dry_run: bool,
    min_side: int = 0,
    pin: bool = False,
) -> dict[str, Any]:
    if not source.is_dir():
        raise SystemExit(f"来源目录不存在：{source}")
    target.mkdir(parents=True, exist_ok=True)

    prefer = _prefer_terms()
    print(f"prefer 名单（与现网同键）：{prefer}")
    store = _load_store(db_path, prefer)
    images, skipped = _discover(source, min_side=min_side)
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
            result = store.add(
                md5=md5, path=str(destination), ext=ext, group_id="", persona_owned=pin
            )
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
    parser.add_argument(
        "--min-side",
        type=int,
        default=MIN_SIDE,
        help="短边像素下限（B1 内容守卫；先例 eat.py _IMG_MIN_SIDE=300；0=关）",
    )
    parser.add_argument(
        "--pin",
        action="store_true",
        help="本次插入的行写 persona_owned=1（本命旗标）：运行时按龄裁剪"
        "（BOT_MEME_LIBRARY_MAX_AGE_DAYS）护住不删（需 protect_from_prune 开着，缺省 True）；"
        "按量上限 max_files 仍生效；库里已存在的行不动（幂等口径不变）",
    )
    args = parser.parse_args()

    report = run(
        source=Path(args.source),
        db_path=Path(args.db),
        target=Path(args.target),
        dry_run=args.dry_run,
        min_side=args.min_side,
        pin=args.pin,
    )
    _print_report(report)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
