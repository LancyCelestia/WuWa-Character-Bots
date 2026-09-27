"""解压炸弹像素预算单源回归（攻击者复查 F-V-1 + F-7 同族，2026-09-27 席位 S-FIX-VISBOMB）。

锁定三件事：
1. **像素闸在解码之前**：超预算图（文件极小、头声明亿级像素）必须在任何
   ``load()``/``convert()`` 全分辨率解码之前被拒，失败走既有诚实面（None/丢图），
   绝不静默缩放巨图。
2. **阈值单源**：全仓 ``MAX_IMAGE_PIXELS`` 阈值常量只准定义在
   ``domains/media/ingest/image_pixel_budget.py``；vision 真身内禁第二份副本字面量。
3. **接线名册**：vision 解码点（``_pil_normalize_image`` / ``_gif_strip_from_image``）
   必须按 AST 现算调用 ``ensure_pixel_budget``，注释/文案改不动这把锁。
"""
from __future__ import annotations

import ast
import base64
import io
import re
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

# vision 域真身目录与 plugins 根（由被锁模块自身位置派生，不手写仓库路径）。
_INGEST_DIR = Path(vision_describe.__file__).resolve().parent
_PLUGINS_ROOT = _INGEST_DIR.parents[3]


def _budget():
    """单源件按函数内引用取——RED 阶段模块尚未存在，缺件应记 FAILED 而非收集期 ERROR。"""
    from plugins.bot_unified_runtime.domains.media.ingest import image_pixel_budget

    return image_pixel_budget


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _bomb_png_bytes(width: int, height: int) -> bytes:
    """极小文件 + 超大 IHDR：解压炸弹头形态（65 字节声称 width×height 像素）。"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"", 9))
        + _png_chunk(b"IEND", b"")
    )


class _FakeImage:
    """只带头信息的伪 Image：任何真实解码尝试（convert/load）都被记为入侵。"""

    def __init__(self, width: int, height: int, frames: int = 1) -> None:
        self.width = width
        self.height = height
        self.size = (width, height)
        self.n_frames = frames
        self.decoded: list[str] = []

    def seek(self, index: int) -> None:
        self.decoded.append(f"seek:{index}")

    def thumbnail(self, box: tuple[int, int]) -> None:
        self.decoded.append(f"thumbnail:{box}")

    def convert(self, mode: str):
        self.decoded.append(f"convert:{mode}")
        raise AssertionError(f"full-res decode attempted on {self.size}")


def test_bomb_bytes_rejected_before_any_pixel_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-V-1 核心：100Mpx（PIL 默认阈值的 1x–2x 告警带内）炸弹字节必须被拒，
    且全程不得触到像素解码——用 load 陷阱证明「拒发生在解码之前」。"""
    from PIL import Image

    attempts: list[tuple[int, int]] = []

    def _trap(self, *args: object, **kwargs: object) -> None:
        attempts.append((self.width, self.height))
        raise AssertionError("pixel decode attempted")

    monkeypatch.setattr(Image.Image, "load", _trap)
    data = _bomb_png_bytes(10000, 10000)
    assert vision_describe._image_bytes_to_data_url(data) is None
    assert attempts == []


@pytest.mark.parametrize("frames", [1, 3])
def test_normalize_points_reject_oversize_without_convert(frames: int) -> None:
    """两个 Image 对象核心各自把闸：超预算伪图直接 None，不许摸到 convert/seek/thumbnail。"""
    fake = _FakeImage(10000, 10000, frames=frames)
    if frames == 1:
        out = vision_describe._pil_normalize_image(fake, first_frame_only=False)
    else:
        out = vision_describe._gif_strip_from_image(fake)
    assert out is None
    assert fake.decoded == []


def test_normal_image_still_normalized() -> None:
    """诚实失败面只关巨图：正常小图路径逐字节行为不回归（仍出 JPEG data URL）。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (7, 84, 110)).save(buffer, format="PNG")
    out = vision_describe._image_bytes_to_data_url(buffer.getvalue())
    assert out is not None and out.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(out.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as result:
        assert result.size == (64, 48)


def test_large_but_legal_image_still_capped_to_max_side() -> None:
    """预算内的普通大图（7.5Mpx）仍须缩到 _PIL_MAX_SIDE 长边——顺序改造不误伤正常缩放腿。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (3000, 2500), (20, 40, 60)).save(buffer, format="PNG")
    out = vision_describe._image_bytes_to_data_url(buffer.getvalue())
    assert out is not None
    raw = base64.b64decode(out.split(",", 1)[1])
    with Image.open(io.BytesIO(raw)) as result:
        assert max(result.size) == vision_describe._PIL_MAX_SIDE


def test_library_ceiling_pinned_to_single_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """闸被调用时必须顺手把 PIL 库默认阈值收成单源值（漏检点的第二层保险）。"""
    from PIL import Image

    module = _budget()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None, raising=False)
    fake = _FakeImage(64, 64)
    vision_describe._pil_normalize_image(fake, first_frame_only=False)
    assert Image.MAX_IMAGE_PIXELS == module.MAX_IMAGE_PIXELS
    assert module.MAX_IMAGE_PIXELS == 40_000_000


def test_budget_boundary_and_error_shape() -> None:
    """单源谓词判据：恰好 40M 放行、+1 拒绝；PixelBudgetError 属 ValueError 族。"""
    module = _budget()
    ok = SimpleNamespace(width=8000, height=5000)
    bomb = SimpleNamespace(width=40_000_001, height=1)
    module.ensure_pixel_budget(ok)  # 不抛即通过
    with pytest.raises(module.PixelBudgetError):
        module.ensure_pixel_budget(bomb)
    assert issubclass(module.PixelBudgetError, ValueError)


def test_vision_decode_points_wired_by_ast() -> None:
    """接线名册（AST 现算）：两个解码核心必须各自调用 ensure_pixel_budget，缺一只红。"""
    source = Path(vision_describe.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"_pil_normalize_image", "_gif_strip_from_image"}
    found: dict[str, bool] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            callees = {
                call.func.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            found[node.name] = "ensure_pixel_budget" in callees
    assert found == {"_pil_normalize_image": True, "_gif_strip_from_image": True}


def test_no_second_pixel_threshold_constant_in_plugins() -> None:
    """单源锁：全 plugins 树只有 image_pixel_budget.py 允许定义/指派 MAX_IMAGE_PIXELS。"""
    single_source = (_INGEST_DIR / "image_pixel_budget.py").resolve()
    pattern = re.compile(r"\bMAX_IMAGE_PIXELS\s*=(?!=)")
    offenders: list[str] = []
    for py in _PLUGINS_ROOT.rglob("*.py"):
        if py.resolve() == single_source:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(text):
            offenders.append(str(py))
    assert offenders == []


def test_vision_describe_carries_no_local_threshold_copy() -> None:
    """副本锁：vision 真身里不许出现与单源同值的字面量阈值（40_000_000/40000000）。"""
    source = Path(vision_describe.__file__).read_text(encoding="utf-8")
    assert re.search(r"40_000_000|40000000", source) is None


def test_image_stitch_decode_point_wired_by_ast() -> None:
    """接线名册扩员（主代理落 VISBOMB §7 补丁的跟随锁，F-7/2026-09-27）：
    image_stitch.try_stitch_strip 的单图解码腿必须调 ensure_pixel_budget，
    且调用排在 load() 之前——摘一行或挪到 load 之后都当场红。"""
    path = _PLUGINS_ROOT / "bot_unified_runtime" / "domains" / "link_parse" / "parsers" / "image_stitch.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "try_stitch_strip"
    )
    gate_line = min(
        (
            node.lineno
            for node in ast.walk(target)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ensure_pixel_budget"
        ),
        default=-1,
    )
    load_line = min(
        (
            node.func.attr
            and node.lineno
            for node in ast.walk(target)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "load"
        ),
        default=-1,
    )
    assert gate_line != -1, "try_stitch_strip 未接单源像素闸（§7 补丁被撤？）"
    assert load_line == -1 or gate_line < load_line, "像素闸被挪到 load() 之后＝失效"
