"""G-MERMAID：bot 回复内 ```mermaid 块渲染成 PNG 的离线单测。

只覆盖检测/占位/护栏/混合部件组装与渲染成功、失败两态（渲染器全部
mock），另用假 page 驱动 render_backends 的 wait_js 截图码路径；
不起真实浏览器、不访问网络。跑法：

PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_mermaid_reply_render.py \
    --basetemp="$TEMP/sdd6_a3" -p no:cacheprovider
"""
from __future__ import annotations

import base64

import pytest

from plugins.bot_unified_runtime.contracts import CapabilityResult, ReviewResult
from plugins.bot_unified_runtime.output import renderer
from plugins.bot_unified_runtime.output.card_render import bridge

FENCE = "```mermaid\ngraph TD\nA --> B\n```"


def _chat_result(body: str) -> CapabilityResult:
    return CapabilityResult(request_id="r1", capability_id="bot.chat", kind="text", body=body)


def _review() -> ReviewResult:
    return ReviewResult(request_id="r1", approved=True)


# ==================== 检测 ====================
def test_find_mermaid_blocks_matches_fences_only() -> None:
    text = f"前文\n{FENCE}\n后文 ```python\nprint(1)\n```"
    matches = renderer.find_mermaid_blocks(text)
    assert len(matches) == 1
    assert matches[0].group(1).strip() == "graph TD\nA --> B"


def test_find_mermaid_blocks_ignores_unterminated_and_other_langs() -> None:
    text = "```mermaid\ngraph TD\nA --> B\n"  # 没有闭合围栏
    assert renderer.find_mermaid_blocks(text) == []
    assert renderer.find_mermaid_blocks("```python\nx=1\n```") == []
    assert renderer.find_mermaid_blocks("```mermaidish\nx\n```") == []


# ==================== 替换/占位/顺序 ====================
def test_apply_success_replaces_block_and_orders_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: b"PNG")
    text = f"开头\n{FENCE}\n结尾"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert new_text == "开头\n【流程图见下图】\n结尾"
    assert [part["type"] for part in parts] == ["text", "image", "text"]
    assert parts[0]["text"] == "开头\n【流程图见下图】"
    assert parts[2]["text"] == "\n结尾"
    assert parts[1]["file"] == "base64://" + base64.b64encode(b"PNG").decode("ascii")


def test_apply_success_multiple_blocks_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: b"PNG")
    text = f"{FENCE}\n中间\n{FENCE}"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert new_text.count("【流程图见下图】") == 2
    assert [part["type"] for part in parts] == ["text", "image", "text", "image"]
    assert parts[2]["text"] == "\n中间\n【流程图见下图】"


def test_apply_chat_naturalizes_surroundings_keeps_placeholder_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: b"PNG")
    text = f"**开头**\n{FENCE}\n结尾"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=True)
    assert "开头" in new_text and "**" not in new_text
    assert "【流程图见下图】" in new_text
    assert any(part["type"] == "image" for part in parts)


# ==================== 失败态：原样保留，绝不丢内容 ====================
def test_apply_failure_keeps_block_verbatim_and_returns_empty_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: None)
    text = f"前\n{FENCE}\n后"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert (new_text, parts) == (text, [])
    assert "```mermaid" in new_text and "graph TD" in new_text


def test_apply_partial_failure_keeps_failed_block_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_render(code: str) -> bytes | None:
        return b"PNG" if "B --> C" in code else None

    monkeypatch.setattr(renderer, "_render_mermaid_png", fake_render)
    text = f"{FENCE}\n中间\n```mermaid\ngraph TD\nB --> C\n```"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert "【流程图见下图】" in new_text
    assert "```mermaid\ngraph TD\nA --> B\n```" in new_text  # 失败块原样保留
    assert sum(1 for part in parts if part["type"] == "image") == 1


def test_apply_renderer_raising_never_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(code: str) -> bytes | None:
        raise RuntimeError("render exploded")

    monkeypatch.setattr(renderer, "_render_mermaid_png", boom)
    new_text, parts = renderer.apply_mermaid_blocks(f"x\n{FENCE}", is_chat=False)
    assert parts == [] and new_text == f"x\n{FENCE}"


# ==================== 护栏 ====================
def test_guardrail_renders_at_most_three_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_render(code: str) -> bytes | None:
        calls.append(code)
        return b"PNG"

    monkeypatch.setattr(renderer, "_render_mermaid_png", fake_render)
    text = "\n中间\n".join([FENCE] * 5)
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert len(calls) == 3  # 只渲染前 3 块
    assert new_text.count("【流程图见下图】") == 3
    assert new_text.count("```mermaid") == 2  # 其余保留文本
    assert sum(1 for part in parts if part["type"] == "image") == 3


def test_guardrail_oversize_block_kept_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        renderer,
        "_render_mermaid_png",
        lambda code: calls.append(code) or b"PNG",
    )
    big_source = "graph TD\n" + "A --> B\n" * 2000  # > 8000 字符
    oversize = f"```mermaid\n{big_source}```"
    text = f"{FENCE}\n{oversize}"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert len(calls) == 1  # 超长块未送渲染
    assert oversize in new_text
    assert sum(1 for part in parts if part["type"] == "image") == 1


def test_guardrail_all_oversize_leaves_text_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: b"PNG")
    big_source = "graph TD\n" + "A --> B\n" * 2000
    text = f"```mermaid\n{big_source}```"
    new_text, parts = renderer.apply_mermaid_blocks(text, is_chat=False)
    assert (new_text, parts) == (text, [])


# ==================== renderer 全链路（mixed 组装） ====================
def test_render_reviewed_output_mixed_with_mermaid_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: b"PNG")
    rendered = renderer.render_reviewed_output(_chat_result(f"看图\n{FENCE}"), _review())
    assert rendered.content_type == "mixed"
    parts = rendered.content_ref["parts"]
    assert [part["type"] for part in parts] == ["text", "image"]
    assert "【流程图见下图】" in rendered.text_fallback
    assert "graph TD" not in rendered.text_fallback  # 已渲染块不再重复正文


def test_render_reviewed_output_text_fallback_when_render_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, "_render_mermaid_png", lambda code: None)
    rendered = renderer.render_reviewed_output(_chat_result(f"看图\n{FENCE}"), _review())
    assert rendered.content_type == "text"
    assert "graph TD" in rendered.content_ref["text"]  # 代码内容未丢


def test_render_reviewed_output_ignores_text_without_mermaid() -> None:
    rendered = renderer.render_reviewed_output(_chat_result("普通回复"), _review())
    assert rendered.content_type == "text"
    assert rendered.content_ref["text"] == "普通回复"


def test_render_reviewed_output_never_raises_on_broken_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(code: str) -> bytes | None:
        raise RuntimeError("boom")

    monkeypatch.setattr(renderer, "_render_mermaid_png", boom)
    rendered = renderer.render_reviewed_output(_chat_result(f"看图\n{FENCE}"), _review())
    assert rendered.content_type == "text"


# ==================== bridge：HTML 组装与 PNG 入口 ====================
def test_render_mermaid_html_mica_and_escapes() -> None:
    html_text = bridge.render_mermaid_html('graph TD\nA["<script>alert(1)</script>"] --> B')
    # Mica 铁律
    assert "<meta viewport" not in html_text
    assert "fit-content" in html_text
    assert "background: transparent" in html_text
    assert html_text.count("box-shadow") == 1  # 单一柔光阴影 token
    assert "--pc: #607080" in html_text
    assert 'class="card"' in html_text
    # CDN + startOnLoad
    assert "https://cdn.jsdelivr.net/npm/mermaid" in html_text
    assert "startOnLoad: true" in html_text
    # 代码经转义注入，无裸 <script> 注入面
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;" in html_text
    assert "graph TD" in html_text


def test_render_mermaid_png_empty_code_is_none() -> None:
    assert bridge.render_mermaid_png("   \n") is None


def test_render_mermaid_png_uses_backend_and_failure_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class _FakeBackend:
        name = "playwright"
        available = True

        def render_card(self, payload: dict) -> bytes | None:
            captured.update(payload)
            return b"PNG"

    class _NullBackend:
        name = "null"
        available = False

        def render_card(self, payload: dict) -> bytes | None:
            return None

    monkeypatch.setattr(bridge, "_MERMAID_BACKEND", _FakeBackend())
    assert bridge.render_mermaid_png("graph TD\nA --> B") == b"PNG"
    assert captured["wait_js_timeout_ms"] == 6000
    assert "wait_js" in captured and "document.querySelector" in captured["wait_js"]
    assert "cdn.jsdelivr.net/npm/mermaid" in captured["html"]

    monkeypatch.setattr(bridge, "_MERMAID_BACKEND", _NullBackend())
    assert bridge.render_mermaid_png("graph TD\nA --> B") is None


# ==================== render_backends：wait_js 码路径（假 page） ====================
class _FakeElement:
    def screenshot(self, **kwargs: object) -> bytes:
        return b"SHOT"


class _FakePage:
    """按脚本模拟 set_content→wait→截图链路；wait_js 由 scenario 控制。"""

    def __init__(self, *, wait_js_ok: bool) -> None:
        self.wait_js_ok = wait_js_ok
        self.wait_calls: list[tuple[str, int]] = []

    def set_default_timeout(self, ms: int) -> None:
        pass

    def set_content(self, html: str, wait_until: str) -> None:
        pass

    def wait_for_function(self, expression: str, timeout: int = 0) -> None:
        self.wait_calls.append((expression, timeout))
        if len(self.wait_calls) == 1:
            return  # 既有 images-complete 等待直接通过
        if not self.wait_js_ok:
            raise TimeoutError("wait_js timeout")

    def query_selector(self, selector: str) -> _FakeElement | None:
        return _FakeElement() if selector == ".card" else None

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def new_page(self, **kwargs: object) -> _FakePage:
        return self._page

    def is_connected(self) -> bool:
        return True


def _make_backend(monkeypatch: pytest.MonkeyPatch, page: _FakePage):
    from plugins.bot_unified_runtime.output.render_backends import (
        PlaywrightRenderBackend,
    )

    backend = PlaywrightRenderBackend()
    if not backend.available:
        pytest.skip("playwright 未安装，跳过 wait_js 码路径验证")
    monkeypatch.setattr(backend, "_get_browser", lambda: _FakeBrowser(page))
    return backend


def test_playwright_backend_wait_js_success(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(wait_js_ok=True)
    backend = _make_backend(monkeypatch, page)
    payload = {
        "html": "<div class='card'>x</div>",
        "wait_js": "() => true",
        "wait_js_timeout_ms": 6000,
    }
    assert backend.render_card(payload) == b"SHOT"
    assert len(page.wait_calls) == 2  # images-complete + wait_js
    assert page.wait_calls[1][1] == 6000


def test_playwright_backend_wait_js_timeout_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(wait_js_ok=False)
    backend = _make_backend(monkeypatch, page)
    payload = {"html": "<div class='card'>x</div>", "wait_js": "() => false"}
    assert backend.render_card(payload) is None  # 失败降级，不抛异常


def test_playwright_backend_without_wait_js_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(wait_js_ok=False)  # 即使第二类等待会超时，也不该被调用
    backend = _make_backend(monkeypatch, page)
    assert backend.render_card({"html": "<div class='card'>x</div>"}) == b"SHOT"
    assert len(page.wait_calls) == 1


# ==================== 发送段适配：base64:// 图片部件可被 OneBot 段化 ====================
def test_mixed_image_part_maps_to_onebot_segment() -> None:
    from plugins.bot_unified_runtime.sender.onebot import _segment_from_mixed_part

    part = {
        "type": "image",
        "file": "base64://" + base64.b64encode(b"PNG").decode("ascii"),
    }
    segment = _segment_from_mixed_part(part)
    assert segment is not None
    assert segment["type"] == "image"
    assert segment["data"]["file"].startswith("base64://")


# ==================== 真实渲染烟测（默认跳过；BOT_MERMAID_NET_TESTS=1 启用） ====================
def test_render_mermaid_png_real_network_smoke() -> None:
    """真实浏览器 + CDN 全链路：render_mermaid_png 非 None 且 PNG > 10000 字节。

    门控先例与 test_finance_data 的 BOT_FINANCE_NET_TESTS 一致：默认跳过，
    设 BOT_MERMAID_NET_TESTS=1 才跑；无网/上游受限环境不算失败。
    """
    import os

    if os.environ.get("BOT_MERMAID_NET_TESTS", "") != "1":
        pytest.skip("真实渲染烟测默认跳过（BOT_MERMAID_NET_TESTS=1 启用）")
    png = bridge.render_mermaid_png("graph TD;A-->B;")
    assert png is not None
    assert len(png) > 10000
