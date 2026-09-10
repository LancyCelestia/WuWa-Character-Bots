"""竖切横图拼接还原。

互联网常见玩法：把一张横图竖切成多块（例如 4 块）当多张竖图一起发布，
在推特/小红书等竖屏信息流里利用更多垂直空间。本模块把这类图片组识别出来
并拼接还原成完整横图：

- 判定条件（全部满足才拼）：张数 2..N、各张宽高一致（±2px 容差）、
  单张为竖图、拼接后总宽高比 >= 1.0（横向长条）。
- 不匹配或任何一张下载失败时原样返回 URL 列表（绝不丢图）。
- 拼接结果落盘 Runtime ``data/media_stitch/``（BOT_RUNTIME_DATA_DIR
  重映射；env 未设置时禁用，避免往源码树写文件）。
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from PIL import Image, ImageFile

from plugins.bot_unified_runtime.sources.parsers.http_util import http_get

_RUNTIME_DATA_ENV = "BOT_RUNTIME_DATA_DIR"

# 截断/损坏的 JPEG 允许宽容解码（切片图常见轻微截断）。
ImageFile.LOAD_TRUNCATED_IMAGES = True

_MAX_STRIP_IMAGES = 10
_DIM_TOLERANCE = 2
# 单张最小宽度：低于此值大概率是表情/图标九宫格而非切片。
_MIN_STRIP_WIDTH = 240
# 单张竖图最小高宽比（正方形九宫格不拼）。
_MIN_SINGLE_ASPECT = 1.12
# 拼接后最大总宽/总高：超过视为碰巧同尺寸的普通图集。
_MAX_TOTAL_ASPECT = 4.0
# 串行下载整体预算（秒）：超时放弃拼接保持原图组，绝不阻塞整条解析链。
_TOTAL_BUDGET_SECONDS = 20.0
# 拼接画布像素上限（40MP，RGB 峰值约 120MB）。
_MAX_CANVAS_PIXELS = 40_000_000
# 缓存配额：超出保留最新 200 个（同 data/cards 的 prune_prefixed 口径）。
_CACHE_KEEP = 200


def _stitch_cache_dir() -> Path | None:
    """Runtime media_stitch 目录；数据根未配置时返回 None（禁用）。"""
    raw = os.getenv(_RUNTIME_DATA_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw.replace("\\", "/")).expanduser()
    if not path.is_absolute():
        # 与 cookies.py 同规则：相对路径按项目根（包结构上溯四级）解析。
        path = Path(__file__).resolve().parents[4] / path
    return (path / "media_stitch").resolve()


def _prune_stitch_cache(cache_dir: Path) -> None:
    """缓存配额：只保留最新 _CACHE_KEEP 个拼接产物（防目录无界增长）。"""
    try:
        files = sorted(
            (
                item
                for item in cache_dir.glob("strip_*.jpg")
                if item.is_file()
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in files[_CACHE_KEEP:]:
        try:
            stale.unlink()
        except OSError:  # 并发占用等删除失败留待下轮。
            pass


def _looks_like_vertical_strip(sizes: list[tuple[int, int]]) -> bool:
    """竖切横图判定：同尺寸竖图组、拼接后呈横向长条。"""
    count = len(sizes)
    if count < 2 or count > _MAX_STRIP_IMAGES:
        return False
    widths = [width for width, _ in sizes]
    heights = [height for _, height in sizes]
    if max(widths) - min(widths) > _DIM_TOLERANCE:
        return False
    if max(heights) - min(heights) > _DIM_TOLERANCE:
        return False
    width, height = widths[0], heights[0]
    if width < _MIN_STRIP_WIDTH:
        return False
    if height / width < _MIN_SINGLE_ASPECT:
        return False
    total_aspect = (width * count) / height
    return 1.0 <= total_aspect <= _MAX_TOTAL_ASPECT


def try_stitch_strip(
    urls: list[str],
    *,
    cookie_header: str = "",
    proxy: str = "",
    referer: str = "",
) -> tuple[list[str], str]:
    """识别并拼接竖切横图；返回 ``(最终图片引用列表, 拼接图本地路径)``。

    命中时返回 ``([本地拼接图路径], 本地拼接图路径)``；未命中/下载失败/
    数据根未配置时返回 ``(原列表, "")``。调用方据此决定是否替换 detail
    里的图片组。
    """
    candidates = [str(url or "") for url in urls if str(url or "").strip()]
    if len(candidates) < 2:
        return list(urls), ""
    cache_dir = _stitch_cache_dir()
    if cache_dir is None:
        return list(urls), ""
    import time

    # 整体预算：串行下载最坏会阻塞整条解析链（每图 8s 超时 × N 张），
    # 超预算即放弃拼接保持原图组——拼图是锦上添花，不是必需品。
    deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS
    images: list[Image.Image] = []
    for url in candidates[:_MAX_STRIP_IMAGES]:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            return list(urls), ""
        try:
            _, payload = http_get(
                url,
                timeout=max(1.0, min(8.0, remaining)),
                cookie=cookie_header,
                proxy=proxy,
                referer=referer,
            )
            image = Image.open(io.BytesIO(payload))
            image.load()
        except Exception:  # noqa: BLE001 - 任一图失败即放弃拼接，保持原图组。
            return list(urls), ""
        images.append(image)
    sizes = [(image.width, image.height) for image in images]
    if not _looks_like_vertical_strip(sizes):
        return list(urls), ""
    width = min(size[0] for size in sizes)
    height = min(size[1] for size in sizes)
    # 内存护栏：拼接画布像素总量封顶（RGB 三字节，40MP≈120MB 峰值）。
    if width * len(images) * height > _MAX_CANVAS_PIXELS:
        return list(urls), ""
    canvas = Image.new("RGB", (width * len(images), height))
    for index, source_image in enumerate(images):
        frame: Image.Image = (
            source_image.convert("RGB")
            if source_image.mode in ("RGBA", "LA", "P")
            else source_image
        )
        canvas.paste(frame, (index * width, 0))
    digest = hashlib.sha1(canvas.tobytes()).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"strip_{digest}.jpg"
    if not out_path.is_file():
        canvas.save(out_path, "JPEG", quality=90)
    _prune_stitch_cache(cache_dir)
    local = str(out_path)
    return [local], local
