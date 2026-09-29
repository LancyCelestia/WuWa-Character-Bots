"""图片**内容质检**唯一真身（B1 池子守卫波，2026-09-28）。

为什么单独一件：randpic 池子扫描、表情库在线吸收（``meme_library_listener``）、
离线导入脚本（``scripts/import_meme_packs.py``）三处都要回答同一个问题——
「这坨字节/这个文件，是不是真的、够格发的图」。三处各抄一份魔数表＝本仓
「禁第二真身」点名的形态（同 ``domains/media/digest.py`` 的收口先例，蓝图 §3.1）。

口径（与全仓「我不知道 ≠ 它没有」一致）：

- ``read_header`` / ``min_side_of_*`` 拿不到证据时返回 ``None``＝**不知道**，
  由调用侧决定记哪本账（stat 失败、坏件、还是放行后交给出站闸）；本件绝不
  把「读不出」折成「它不是图」。
- ``header_is_image`` 只认登记的五族签名（JPEG/PNG/GIF/WEBP/BMP，与
  ``randpic._IMAGE_EXTENSIONS`` 同一集合）。HEIC/HEIF/AVIF **刻意不收**：
  QQ 客户端侧不保证解码，发出去就是坏件，登记只会给假通过开路。
- PIL 惰性 import（先例 ``domains/food/capabilities/eat.py:253``）：只做头部
  判定的调用侧不为一枚魔数检查付 Pillow 的 import 代价。
"""

from __future__ import annotations

import io
from pathlib import Path

#: 文件头魔数前缀表（peek 前 12 字节即可判全；WEBP 需要 RIFF + 偏移 8 的 WEBP 四字节）。
_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG（八字节完整签名）
    b"GIF8",                    # GIF87a / GIF89a
    b"BM",                      # BMP
)
_RIFF = b"RIFF"
_WEBP = b"WEBP"
_HEADER_BYTES = 12

#: 登记五族的**扩展名面**（与上面魔数表同一集合的另一种写法）。
#: 为什么放在本件：``randpic._IMAGE_EXTENSIONS`` 住在能力层、离线导入脚本住在
#: scripts/，两处各自持一份扩展名清单＝本件开头点名的「三处各抄一份」形态。
#: 配对锁 = ``tests/test_image_guard_extension_parity.py``（判据与真身逐元素相等，
#: 任何一侧偷偷加一族 ⇒ 当场红）。
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})


def header_is_image(header: bytes) -> bool:
    """魔数判定：文件头对得上登记五族签名之一才算真图（假扩展名在这一步被拦）。"""
    if not header:
        return False
    if any(header.startswith(prefix) for prefix in _MAGIC_PREFIXES):
        return True
    return len(header) >= 12 and header[:4] == _RIFF and header[8:12] == _WEBP


def read_header(path: str | Path, *, n: int = _HEADER_BYTES) -> bytes | None:
    """偷读文件头 ``n`` 字节；读不到（权限/被占用/ vanished）返回 ``None``＝不知道。"""
    try:
        with open(str(path), "rb") as handle:
            return handle.read(n)
    except OSError:
        return None


def min_side_of_bytes(data: bytes) -> int | None:
    """字节流的短边像素；PIL 解不开（截断/损坏/伪造）返回 ``None``＝不知道。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 - PIL 的失败形态杂（UnidentifiedImageError/OSError/ValueError），一律按「解不开」记。
        return None
    if width <= 0 or height <= 0:
        return None
    return min(int(width), int(height))


def min_side_of_file(path: str | Path) -> int | None:
    """文件的短边像素（PIL 只解图头，不读全量字节）；解不开返回 ``None``＝不知道。"""
    try:
        from PIL import Image

        with Image.open(str(path)) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 - 同上：解码失败不等于「它小」，交调用侧记账。
        return None
    if width <= 0 or height <= 0:
        return None
    return min(int(width), int(height))
