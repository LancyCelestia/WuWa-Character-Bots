"""本地图库污染清理（2026-09-13 用户指令：图库被广告图等污染，VLM 复判即删）。

流程：library.sqlite 全量遍历 → 每张图过 VLM（是否食物/菜品照片，JSON 判定）
→ 非食物移入隔离区（%TEMP%/food_quarantine_<日期>/，保留文件可回捞）并删
DB 行与 .source.txt；VLM 判定失败/不可用 → 保守保留（宁留勿删）。

用法：
    python scripts/clean_food_gallery.py --execute   # 真执行
    python scripts/clean_food_gallery.py             # DRY-RUN（只判定不移动）

复用 .env 的 BOT_VISION_MODEL_REGISTRY（与识图同一通道）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_JUDGE_PROMPT = (
    "判断这张图片是否为食物/菜品照片（成品菜、食材、烹饪过程都算食物）。"
    "广告图、证书、文字海报、二维码、截图、风景、人物照都算非食物。"
    '只返回 JSON：{"is_food": true, "reason": "≤15字"}'
)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# is_food 严格解析：字符串只有这些（忽略大小写/首尾空白）才算「食物」。
_TRUTHY_STRINGS = frozenset({"true", "1", "yes"})


def _parse_is_food(payload: object) -> bool | None:
    """严格解析 VLM 的 is_food 字段；无法识别返回 None（保守保留，宁留勿删）。

    防御 JSON 里 is_food 为字符串的形状：bool("false") 是 True，会把污染图
    误判成食物保留。规则：bool 原样用；字符串小写命中白名单判真、其余判假；
    缺键/数字/列表等一律 None 走保守保留。
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("is_food")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_STRINGS
    return None


def _load_config():
    from dotenv import dotenv_values

    from plugins.bot_unified_runtime.config import Config, translate_env_keys

    vals = {
        k: v
        for k, v in dotenv_values(ROOT / ".env").items()
        if k is not None and v is not None
    }
    return Config(**translate_env_keys(vals))


def _build_provider(config):
    from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
        build_vision_provider,
    )

    return build_vision_provider(config)


def _image_data_url(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def _judge(provider, image_url: str) -> tuple[bool | None, str]:
    """VLM 判定；返回 (is_food|None, reason)。None=无法判定（保守保留）。"""
    content: list[dict] = [
        {"type": "text", "text": "判断这张图。"},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    try:
        reply = provider.generate(
            [
                {"role": "system", "content": _JUDGE_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0.0,
            max_tokens=120,
        )
    except Exception as exc:  # noqa: BLE001 - 判定失败保守保留。
        return None, f"vlm_error:{type(exc).__name__}"
    text = str(getattr(reply, "text", "") or "")
    match = _JSON_RE.search(text)
    if not match:
        return None, "vlm_bad_json"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, "vlm_bad_json"
    return _parse_is_food(payload), str(payload.get("reason") or "")[:40]


def _quarantine_dir() -> Path:
    """隔离区根目录：<临时目录>/food_quarantine_<日期>。

    依次取 TEMP/TMP/TMPDIR 环境变量（活读，不缓存），全缺时落到
    tempfile.gettempdir() 平台兜底——TEMP 缺失不再 KeyError 炸脚本。
    """
    env_temp = next(
        (os.environ[v] for v in ("TEMP", "TMP", "TMPDIR") if os.environ.get(v)),
        None,
    )
    root = Path(env_temp) if env_temp else Path(tempfile.gettempdir())
    return root / f"food_quarantine_{datetime.now().astimezone():%Y%m%d}"


def _execute_removal(
    conn: sqlite3.Connection, name: str, image_path: Path, quarantine: Path
) -> str:
    """真执行单项清理，保证文件与 DB 行一致（P3-14 缺陷③）。

    顺序：先移文件入隔离区（成功后记录回捞清单），再删 DB 行。
    任一步失败：按回捞清单逆序把文件移回原位（此时行未删，无孤儿）；
    回捞也不彻底 → 返回 "corrupt" 由调用方如实报错退出非零。
    返回："removed" | "restored"（失败已回捞干净）| "corrupt"。
    """
    moved: list[tuple[Path, Path]] = []
    try:
        target_dir = quarantine / image_path.parent.name
        target_dir.mkdir(parents=True, exist_ok=True)
        quarantined = target_dir / image_path.name
        shutil.move(str(image_path), str(quarantined))
        moved.append((image_path, quarantined))
        sidecar = image_path.with_suffix(".source.txt")
        if sidecar.is_file():
            quarantined_sidecar = target_dir / sidecar.name
            shutil.move(str(sidecar), str(quarantined_sidecar))
            moved.append((sidecar, quarantined_sidecar))
        conn.execute("DELETE FROM food_images WHERE name=?", (name,))
        conn.commit()
    except (OSError, sqlite3.Error) as exc:
        # 行是否仍存活：查不动时按存活处理（保守回捞文件）。
        try:
            row_alive = (
                conn.execute(
                    "SELECT 1 FROM food_images WHERE name=?", (name,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error:
            row_alive = True
        if not row_alive:
            # 行已删而文件在隔离区=预期终态（无孤儿），按成功记账。
            return "removed"
        restore_failures: list[str] = []
        for origin, quarantined in reversed(moved):
            try:
                shutil.move(str(quarantined), str(origin))
            except OSError as rollback_exc:
                restore_failures.append(
                    f"{quarantined} -> {origin}: {rollback_exc}"
                )
        if restore_failures:
            for line in restore_failures:
                print(f"  !! 回捞失败需人工处理：{line}")
            return "corrupt"
        print(f"  ! {name} 清理执行失败（{type(exc).__name__}），已回捞本项跳过。")
        return "restored"
    return "removed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="食物图库污染清理（VLM 复判）")
    parser.add_argument("--execute", action="store_true", help="真执行（缺省 DRY-RUN）")
    parser.add_argument("--limit", type=int, default=0, help="最多判定 N 张（0=全部）")
    args = parser.parse_args(argv)

    config = _load_config()
    provider = _build_provider(config)
    if provider is None:
        print("vision provider 不可用（registry 未配置）——无法复判，退出。")
        return 2

    from scripts.runtime_paths import runtime_path

    db_path = Path(runtime_path(str(getattr(config, "bot_food_image_dir", "data/food_images"))))
    library_db = db_path / "library.sqlite"
    if not library_db.is_file():
        print(f"library.sqlite 不存在：{library_db}")
        return 2
    quarantine = _quarantine_dir()
    quarantine.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(library_db))
    rows = conn.execute(
        "SELECT name, path, source_url FROM food_images ORDER BY name"
    ).fetchall()
    print(f"图库共 {len(rows)} 项；模式={'EXECUTE' if args.execute else 'DRY-RUN'}")

    kept, removed, unknown = [], [], []
    for name, rel_path, source_url in rows:
        if args.limit and len(removed) + len(kept) + len(unknown) >= args.limit:
            break
        image_path = Path(rel_path)
        if not image_path.is_file():
            unknown.append((name, "file_missing"))
            continue
        data_url = _image_data_url(image_path)
        if data_url is None:
            unknown.append((name, "unreadable"))
            continue
        is_food, reason = _judge(provider, data_url)
        if is_food is True:
            kept.append((name, reason))
            continue
        if is_food is None:
            unknown.append((name, reason))
            continue
        removed.append((name, reason, str(image_path)))
        if args.execute:
            status = _execute_removal(conn, name, image_path, quarantine)
            if status == "corrupt":
                print(f"\n!! {name} 清理失败且回捞不彻底——中止退出，请人工核查。")
                return 1
            if status == "restored":
                # 文件已回捞、行仍在：不算移出，记为无法判定。
                removed.pop()
                unknown.append((name, "execute_failed(已回捞)"))
        time.sleep(0.2)

    conn.close()
    print(f"\n食物保留 {len(kept)}；污染移出 {len(removed)}；无法判定 {len(unknown)}")
    for name, reason, path in removed[:20]:
        print(f"  ✗ {name}（{reason}）{Path(path).name}")
    for name, reason in unknown[:10]:
        print(f"  ? {name}（{reason}）")
    if removed and not args.execute:
        print("\nDRY-RUN：未移动任何文件；加 --execute 真执行。")
    if args.execute:
        print(f"隔离区（可回捞）：{quarantine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
