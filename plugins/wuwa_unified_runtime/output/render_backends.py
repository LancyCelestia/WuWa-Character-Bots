"""渲染后端接口：HTML→图片、卡片渲染的预留接入点。

- ``RenderBackend`` Protocol：接收结构化卡片 payload，返回图片字节；
  渲染失败必须返回 None（由调用方降级文本），不抛异常。
- ``NullRenderBackend``：默认实现，直接返回 None（文本兜底）。
- ``HtmlKitRenderBackend``：可选实现，依赖 nonebot-plugin-htmlkit /
  Playwright；未安装时自动不可用，不影响主链路。
- ``build_render_backend(name)``：按名字选择；未来可加
  cardimg / PIL / 小程序卡等后端，不改调用方。

后续把游戏 wiki 卡、媒体卡接到 ``render_card`` 时，仍然走
``CapabilityResult -> ReviewResult -> RenderedOutput``，渲染只负责
产图，不决定发送。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class RenderBackend(Protocol):
    name: str
    available: bool

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        """渲染卡片为图片字节；失败返回 None。"""


class NullRenderBackend:
    name = "null"
    available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        return None


class HtmlKitRenderBackend:
    """HTML/Markdown → 图片（需要 htmlkit + Playwright 浏览器）。"""

    name = "htmlkit"
    available = False
    _html_to_pic: Any = None

    def __init__(self) -> None:
        try:
            from nonebot_plugin_htmlkit import html_to_pic  # type: ignore

            self._html_to_pic = html_to_pic
            self.available = True
        except Exception:
            self.available = False

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        if not self.available:
            return None
        html = payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        try:
            result = self._html_to_pic(
                html,
                viewport=payload.get("viewport") or {"width": 640, "height": 400},
            )
        except Exception:
            return None
        if isinstance(result, bytes):
            return result
        if isinstance(result, (str, Path)):
            try:
                return Path(result).read_bytes()
            except OSError:
                return None
        return None


def build_render_backend(name: str = "") -> RenderBackend:
    normalized = (name or "").strip().lower()
    if normalized == "htmlkit":
        return HtmlKitRenderBackend()
    return NullRenderBackend()
