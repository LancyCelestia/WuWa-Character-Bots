"""静态资产压缩回归（W18 R3）。

为什么有这一件（一手证据）：生产入口 `mount_webui_assets` 只挂了 `StaticFiles`，
**没有任何压缩中间件**。实测带 ``Accept-Encoding: gzip, br`` 请求
``/console/assets/vendor-react-*.js`` 得到的响应头是::

    content-type: text/javascript; charset=utf-8
    content-length: 334304          ← 与原始文件字节数完全相等
    etag: "074ad5137d591be620d26a1fafb9ae2a"
    cache-control: public, max-age=31536000, immutable

没有 ``content-encoding``。一次冷加载 731.9 KiB（`webui/scripts/byte-audit.mjs`），
在用户 20GiB/月 的硬约束下只有 28,655 次的余量。

为什么不在完整 `create_control_plane_app` 上验：本机 Python 环境装的是
`nonebot2` 本体，**没有** `nonebot.adapters.onebot.v11`（`plugins/bot_unified_runtime/__init__.py`
在 import 期就拉它）⇒ 整个插件包 import 不了。所以这里分两段：

  · **行为段**：用最小 FastAPI 应用复刻「StaticFiles 挂载 + GZipMiddleware」这一层，
    断言压缩真的生效、且已压缩类型不被二次压、且不接受的客户端拿不到 gzip 体。
  · **接线段**：源码锁——`_app.py` 必须真的注册了 `GZipMiddleware`，且
    `minimum_size` 不小于 1024（太小会压 304/空体，白烧 CPU）。两段缺一，
    「测了但没接上」与「接上了但没测」都会漏。
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PY = REPO_ROOT / "plugins" / "bot_unified_runtime" / "control_plane" / "_app.py"

# 足够大且高度可压：400 行重复文本，gzip 后必远小于原文。
_BIG_JS = "export const shorekeeper = '守岸人';\n" * 400
_BIG_CSS = ".root { color: #fff; }\n" * 400


def _static_app(tmp_path: Path) -> FastAPI:
    """复刻生产入口的静态层：`app.mount('/assets', StaticFiles(...))` + GZip。

    与生产同一份 MIME 注册（`_register_webui_mimetypes`）—— 不注册的话
    ``.woff2`` 会落成 ``application/octet-stream``，既不被压缩名单排除、
    也让浏览器不当它是字体。
    """
    mimetypes.add_type("font/woff2", ".woff2")
    mimetypes.add_type("font/woff", ".woff")
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "index-a1b2c3d4.js").write_bytes(_BIG_JS.encode("utf-8"))
    (assets / "index-a1b2c3d4.css").write_bytes(_BIG_CSS.encode("utf-8"))
    (assets / "clip-a1b2c3d4.mp4").write_bytes(b"\x00" * 4096)
    (assets / "font-a1b2c3d4.woff2").write_bytes(b"wOF2" + b"\x00" * 4092)

    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
    return app


@pytest.mark.parametrize(
    ("asset", "marker", "original"),
    [
        ("/assets/index-a1b2c3d4.js", "javascript", _BIG_JS),
        ("/assets/index-a1b2c3d4.css", "text/css", _BIG_CSS),
    ],
)
def test_compressible_assets_are_gzipped_when_client_accepts(
    tmp_path: Path, asset: str, marker: str, original: str
) -> None:
    app = _static_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(asset, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert marker in response.headers["content-type"]
        assert response.headers.get("content-encoding") == "gzip", (
            f"{asset} 没有 gzip —— 静态资产零压缩，一次冷加载 731.9 KiB"
        )
        # 🔴 httpx 的 TestClient 会**自动解压** response.content，所以
        #    `len(response.content)` 是解压后的原始大小，不能当传输字节数比。
        #    真正代表线上传输量的是 content-length 头（本件实测：101 B vs 11,200 B）。
        sent = int(response.headers["content-length"])
        original_bytes = len(original.encode("utf-8"))
        assert sent < original_bytes, "content-length 不小于原文 —— 没真压"
        # 高度重复的内容 gzip 后至少小一个数量级；给宽容差（3 倍）防脆。
        assert sent * 3 < original_bytes, (
            f"gzip 后 {sent} B 相对原始 {original_bytes} B 压缩比不足"
        )
        # 解压后的内容必须与原文逐字相等（压缩不许改内容）。
        assert response.text == original


def test_no_content_encoding_when_client_does_not_accept_gzip(tmp_path: Path) -> None:
    app = _static_app(tmp_path)
    with TestClient(app) as client:
        # httpx 默认会自己带 accept-encoding；显式覆盖成 identity 才是「不接受的客户端」。
        response = client.get(
            "/assets/index-a1b2c3d4.js", headers={"Accept-Encoding": "identity"}
        )
        assert response.status_code == 200
        assert "content-encoding" not in response.headers, (
            "客户端没说要 gzip，服务端不许压 —— 否则它解不开"
        )
        assert response.text == _BIG_JS


@pytest.mark.parametrize(
    "asset", ["/assets/clip-a1b2c3d4.mp4", "/assets/font-a1b2c3d4.woff2"]
)
def test_already_compressed_types_are_passed_through(
    tmp_path: Path, asset: str
) -> None:
    """已压缩容器必须原样透传。

    🔴 woff2 这条曾经真红过一次，根因不在压缩而在 **MIME**：
    本机 `mimetypes.guess_type('x.woff2')` 返回 ``None``（Python 3.12 的
    Windows 注册表里没有 .woff2）⇒ StaticFiles 回 ``application/octet-stream``
    ⇒ 不在 Starlette 的 `font/woff2` 排除名单里 ⇒ 被 gzip。修法是注册 MIME
    （见 `_app.py` 的 `_register_webui_mimetypes`），顺带修掉「浏览器把字体当
    二进制流、推迟加载」这个更实际的问题。
    """
    app = _static_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(asset, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert "content-encoding" not in response.headers, (
            f"{asset} 已是压缩容器，再压一遍只烧 CPU"
        )


def test_woff2_mime_is_registered_so_it_is_not_mistreated() -> None:
    """接线锁：`_app.py` 必须注册 woff2 的 MIME。

    判据不是「测试里注册了」，而是**生产模块源码里**有这条注册——
    否则测试绿、线上仍然把字体当 octet-stream 并 gzip。
    """
    source = APP_PY.read_text(encoding="utf-8")
    assert "woff2" in source.lower(), (
        "_app.py 没有注册 .woff2 的 MIME —— 字体会以 application/octet-stream 返回并被 gzip"
    )


def test_app_py_actually_registers_gzip_middleware() -> None:
    """接线锁：光有行为测试不够，`_app.py` 必须真的挂上了它。"""
    source = APP_PY.read_text(encoding="utf-8")
    assert "from starlette.middleware.gzip import GZipMiddleware" in source, (
        "_app.py 没有 import GZipMiddleware —— 静态资产压缩没接上"
    )
    match = re.search(r"add_middleware\(\s*GZipMiddleware\s*,\s*minimum_size=(\d+)", source)
    assert match is not None, "_app.py 没有 add_middleware(GZipMiddleware, minimum_size=…)"
    assert int(match.group(1)) >= 1024, (
        f"minimum_size={match.group(1)} 太小：小于 1 KiB 的响应压了反而更大"
    )


def test_compression_runs_inside_the_static_app_not_the_api_layer() -> None:
    """压缩必须在**应用级**（包住 StaticFiles），而不是某个 router 的依赖里。

    判据：`add_middleware` 出现在 `create_control_plane_app` 里、且早于
    `mount_webui_assets`。顺序反了仍会压 API 但不压静态资产——正是原来的症状。
    """
    source = APP_PY.read_text(encoding="utf-8")
    gzip_at = source.index("add_middleware(GZipMiddleware")
    mount_at = source.index("mount_webui_assets(app")
    assert gzip_at < mount_at, (
        "GZipMiddleware 注册在 mount_webui_assets 之后 —— 静态资产仍然不被压"
    )
