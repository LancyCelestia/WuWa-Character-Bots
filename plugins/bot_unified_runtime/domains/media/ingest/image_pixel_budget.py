"""图像解码像素预算单一真身（decompression bomb 闸）。

出处：攻击者复查 F-V-1（SEAT-ATK-VISION）与 F-7（SEAT-ATK-LINKPARSE），同族一改。
一张 ≤25MB 的 PNG 可以在 IHDR 里声明上亿像素（压缩比 >100:1）；PIL 默认阈值
``Image.MAX_IMAGE_PIXELS = 89,478,485`` 在超限 1x–2x 带**只发一次性 Warning 并照常
解码**（>2x 才抛错），而解码点若把 ``convert()``/``load()`` 放在任何闸之前，一条
消息即可吃下数百 MB 堆、并发即 OOM。

本模块把判据收在一处，全仓**只准这一份阈值常量**：

- ``MAX_IMAGE_PIXELS``：像素预算唯一真身（40M px，RGB 驻留峰值约 120MB/张；
  2048px 长边的缩放目标仍绰绰有余）。
- ``ensure_pixel_budget(image)``：在 ``Image.open()`` 之后（PIL 只读了头、未解压）、
  任何 ``load()``/``convert()`` 之前调用；超限抛 ``PixelBudgetError``——各解码点
  沿各自既有诚实失败面处理（返回 None / 放弃该图），绝不静默缩放巨图。
- ``apply_library_ceiling()``：把 PIL 库默认阈值同值收口（兜住漏调谓词的解码点：
  PIL 在 load 时自会抛 DecompressionBombError）。

叶模块、零项目内依赖、PIL 只在函数内惰性 import——跨域（media/ingest、
link_parse）复用不成环、import 本模块不拖 PIL。执法锁见
``tests/test_image_pixel_budget.py``（AST 接线名册 + 全树禁第二份阈值）。
"""
from __future__ import annotations

from typing import Any

# 全仓唯一像素预算阈值。改数只改这里；任何域另写字面量即触单源锁（副本锁）。
MAX_IMAGE_PIXELS = 40_000_000


class PixelBudgetError(ValueError):
    """图超像素预算：解码点必须走既有诚实失败面拒绝，不得继续解压。"""


def apply_library_ceiling() -> None:
    """把 PIL 进程级默认阈值收成单源值（幂等；第二层保险，不是主闸）。"""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def ensure_pixel_budget(image: Any) -> None:
    """头级（零解压）像素预算校验；超限抛 ``PixelBudgetError``。

    ``Image.open()`` 只解析文件头，``width``/``height`` 不触发 ``load()``；
    谓词因此能在任何像素驻留之前拒掉炸弹。调用点必须位于 load/convert 之前
    （AST 接线锁执法）。顺手收口库级阈值，漏检点由 PIL 自身在 load 时兜底。
    """
    apply_library_ceiling()
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        raise PixelBudgetError(
            f"image {width}x{height} ({pixels}px) exceeds pixel budget {MAX_IMAGE_PIXELS}px"
        )
