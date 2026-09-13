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
import re
import shutil
import sqlite3
import sys
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
    from plugins.bot_unified_runtime.sources.vision_describe import (
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
    return bool(payload.get("is_food")), str(payload.get("reason") or "")[:40]


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
    quarantine = (
        Path(__import__("os").environ["TEMP"])
        / f"food_quarantine_{datetime.now().astimezone():%Y%m%d}"
    )
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
            target_dir = quarantine / image_path.parent.name
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(image_path), str(target_dir / image_path.name))
            sidecar = image_path.with_suffix(".source.txt")
            if sidecar.is_file():
                shutil.move(str(sidecar), str(target_dir / sidecar.name))
            conn.execute("DELETE FROM food_images WHERE name=?", (name,))
            conn.commit()
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
