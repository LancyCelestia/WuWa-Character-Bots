"""E01 漂移相位策展（D2→D1）确定性回归——全离线（playwright 用本地 Chromium，零网络）。

契约（docs/design/visual-effects-catalog.md §E01）：
- 相位单一来源：payload 稳定序列化 sha1 → [0,1)（bridge.payload_phase 单点）；
- 同一 payload 两次渲染 --phase 完全一致；页面零 JS（无 Math.random 脚本）；
- 不同 payload 相位不同（概率断言）；多 payload 相位连续分布（宽松断言
  覆盖 ≥80% 区间宽度，漂移观感不变）；
- digest 剥离易变字段（updated_at 等）：仅刷新时间不同的两次渲染同帧；
- playwright 双渲对比：同 payload 两页 computed --phase 一致，且
  reduced-motion 下两次截图字节一致。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest

from plugins.bot_unified_runtime.output.card_render.bridge import (
    digest_phase,
    payload_phase,
    render_affinity_card_html,
    render_finance_card_html,
    render_market_card_html,
    render_mermaid_html,
    render_song_candidates_html,
    render_universal_card_html,
    stable_payload_digest,
)
from plugins.bot_unified_runtime.output.templates import render_media_card_html

_PHASE_DECL_RE = re.compile(r"--phase:\s*([0-9]*\.?[0-9]+)\s*;")


def _phases(html: str) -> list[str]:
    return _PHASE_DECL_RE.findall(html)


def _single_phase(html: str) -> str:
    values = _phases(html)
    assert len(values) == 1, f"期望恰好一处 --phase 声明，实得 {values}"
    assert re.fullmatch(r"[01]\.\d{4}", values[0]), values[0]
    return values[0]


# ==================== 各渲染入口 payload 工厂（i 只改变语义内容） ====================
def _media_payload(i: int) -> dict[str, Any]:
    return {
        "title": f"视频标题{i}",
        "platform": "bilibili",
        "author": f"UP主{i}",
        "stats": {"likes": 100 + i},
        "summary": f"简介正文{i}",
    }


def _universal_payload(i: int) -> dict[str, Any]:
    return {
        "platform": "bilibili",
        "item_id": f"BV1xx{i}",
        "title": f"视频{i}",
        "summary": f"正文{i}",
        "stats": {"views": 1000 + i},
    }


def _market_payload(i: int) -> dict[str, Any]:
    return {
        "subtitle": f"全球股指{i}",
        "groups": [
            {
                "name": "美股",
                "rows": [
                    {"name": "标普500", "price": str(5000 + i), "pct": "+0.5%",
                     "trend": [1.0, 2.0, 3.0, float(i)]},
                ],
            },
        ],
        "updated_at": "2026-09-13 08:00:00",
    }


def _finance_payload(i: int) -> dict[str, Any]:
    return {
        "title": f"金融速览{i}",
        "sections": [
            {"name": "巨头", "rows": [{"label": "NVDA", "value": str(100 + i)}]},
        ],
    }


def _song_payload(i: int) -> dict[str, Any]:
    return {
        "query": f"关键词{i}",
        "platform": "netease_music",
        "candidates": [{"index": 1, "name": f"歌曲{i}", "artist": "歌手"}],
    }


def _affinity_payload(i: int) -> dict[str, Any]:
    return {
        "mode": "private",
        "bot_to_user": {"score": float(i), "tier": "友善", "bar": float(i)},
    }


_RENDERERS: dict[str, Callable[[int], str]] = {
    # 旧媒体卡（templates.py，__PHASE__ 占位注入）
    "media_card": lambda i: render_media_card_html(_media_payload(i)),
    # 六张 Jinja 卡（bridge phase 变量注入）
    "universal_card": lambda i: render_universal_card_html(_universal_payload(i)),
    "market_card": lambda i: render_market_card_html(_market_payload(i)),
    "finance_card": lambda i: render_finance_card_html(_finance_payload(i)),
    "song_candidates": lambda i: render_song_candidates_html(_song_payload(i)),
    "affinity_card": lambda i: render_affinity_card_html(_affinity_payload(i)),
    # mermaid：digest 直接取源码
    "mermaid_card": lambda i: render_mermaid_html(f"graph TD; A{i}-->B{i}"),
}


# ==================== 确定性验收 ====================
@pytest.mark.parametrize("name", sorted(_RENDERERS))
def test_same_payload_renders_identical_html_and_phase(name: str) -> None:
    build = _RENDERERS[name]
    html1, html2 = build(7), build(7)
    assert "Math.random" not in html1, "E01 后页面必须零 JS 随机源"
    assert html1 == html2, "同一 payload 两次渲染 HTML 必须完全一致"
    assert _single_phase(html1) == _single_phase(html2)


@pytest.mark.parametrize("name", sorted(_RENDERERS))
def test_different_payloads_get_different_phases(name: str) -> None:
    build = _RENDERERS[name]
    phases = {_single_phase(build(i)) for i in range(24)}
    # 概率断言：24 个不同 payload 落 10000 桶，碰撞到 <12 个不同值的概率可忽略。
    assert len(phases) >= 12, f"不同 payload 相位几乎全相同：{sorted(phases)}"


@pytest.mark.parametrize("name", sorted(_RENDERERS))
def test_phase_distribution_covers_interval(name: str) -> None:
    build = _RENDERERS[name]
    values = [float(_single_phase(build(i))) for i in range(120)]
    spread = max(values) - min(values)
    # 视觉无损：相位连续分布而非固定单值（120 点覆盖 ≥80% 区间宽度，
    # 均匀假设下失败概率 <1e-9）。
    assert spread >= 0.8, f"相位分布过窄（spread={spread:.4f}）"


# ==================== digest 口径 ====================
def test_volatile_fields_do_not_change_phase() -> None:
    base: dict[str, Any] = {"platform": "x", "title": "t", "stats": {"views": 1}}
    assert payload_phase({**base, "updated_at": "2026-09-13 08:00:00"}) == (
        payload_phase({**base, "updated_at": "2026-09-13 21:30:00"})
    )
    assert payload_phase({**base, "fetched_at": 1}) == payload_phase(base)


def test_market_card_same_content_different_updated_at_same_phase() -> None:
    h1 = render_market_card_html(
        {**_market_payload(3), "updated_at": "2026-09-13 08:00:00"}
    )
    h2 = render_market_card_html(
        {**_market_payload(3), "updated_at": "2026-09-13 21:00:00"}
    )
    assert _single_phase(h1) == _single_phase(h2)


def test_digest_phase_unit_contract() -> None:
    assert re.fullmatch(r"0\.\d{4}", digest_phase("a" * 40))
    assert digest_phase("a" * 40) == digest_phase("a" * 40)
    distinct = {digest_phase(f"digest-{i}") for i in range(200)}
    assert len(distinct) >= 150


def test_stable_payload_digest_serialization() -> None:
    # 键序无关 + 非 JSON 原生对象走 default=str 仍稳定。
    assert stable_payload_digest({"a": 1, "b": 2}) == (
        stable_payload_digest({"b": 2, "a": 1})
    )
    stamp = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
    assert stable_payload_digest({"t": stamp}) == stable_payload_digest({"t": stamp})


# ==================== playwright 双渲对比（后端缺失时跳过） ====================
def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    from plugins.bot_unified_runtime.output.render_backends import (
        build_render_backend,
    )

    backend = build_render_backend("playwright")
    return bool(getattr(backend, "available", False))


@pytest.mark.skipif(not _playwright_available(), reason="playwright/Chromium 不可用")
def test_playwright_double_render_phase_and_pixels_stable() -> None:
    from playwright.sync_api import sync_playwright

    html = render_finance_card_html(_finance_payload(11))
    expected = _single_phase(html)
    computed: list[str] = []
    shots: list[bytes] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - 浏览器二进制缺失 → 跳过不失败。
            pytest.skip(f"Chromium 启动失败（{exc.__class__.__name__}）")
        try:
            for _ in range(2):
                page = browser.new_page(
                    viewport={"width": 900, "height": 1200},
                    device_scale_factor=2,
                    reduced_motion="reduce",
                )
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(120)
                computed.append(
                    str(
                        page.evaluate(
                            "getComputedStyle(document.documentElement)"
                            ".getPropertyValue('--phase')"
                        )
                    ).strip()
                )
                shots.append(
                    page.locator(".card").first.screenshot(
                        type="png", omit_background=True, animations="disabled"
                    )
                )
                page.close()
        finally:
            browser.close()
    # --phase 属性一致：浏览器实际生效相位 == HTML 注入值。
    assert computed[0] == computed[1] == expected
    # 同 payload 两次截图字节一致：截图时 animations="disabled" 取消循环动画
    # （reduced-motion 关停在 finance/market 模板因选择器特异性
    # `.drift-blob` < `.drift-blob.drift-a` 不生效——既有缺陷，另行登记；
    # playwright 截图动画取消与页面相位注入双保险后，静态构图逐字节稳定）。
    assert shots[0] == shots[1]
