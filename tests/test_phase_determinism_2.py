"""E01 二批：三张 f-string 直拼卡相位钉帧 + finance/market reduced-motion 复活回归。

契约（docs/design/visual-effects-catalog.md §E01 延伸，首批 test_phase_determinism
已覆盖 Jinja 侧 7 入口，本文件覆盖首批遗留的 3 张 Python f-string 卡）：
- echo 帮助卡 / debug LLM 接入卡 / usage 用量卡：相位 = 内容稳定 sha1
  （bridge.payload_phase 单一事实源），同 payload 双渲逐字节一致、页面零 JS；
- 不同 payload 相位不同（概率断言）且连续分布（spread ≥ 0.8，漂移观感不变）；
- 非语义字段不进 digest：debug 卡 config 运行时对象、usage 卡 generated_at
  易变字段（同 bridge._PHASE_VOLATILE_KEYS 口径）不影响相位；
- playwright：同 payload 双渲 computed --phase 一致；finance/market 模板
  prefers-reduced-motion 守卫经特异性修复后真正生效（animationName == none，
  首批报告实测该守卫因 (0,1,0)<(0,2,0) 是死 CSS）；
- mermaid 卡漂移在伪元素上（.card::before/::after），守卫须同特异性且源序
  靠后（静态断言）+ computed animationName 实测关停（首批标记未验项收口）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

# S345 #83 J-1：三门与外层 skipif 共用的唯一判据/唯一 launch 出口住在 test_phase_determinism
# （单一真身，禁三份副本），本文件复用之、不再各写一份。
from test_phase_determinism import _playwright_available, launch_chromium_or_skip

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _help_mica_html,
)
from plugins.bot_unified_runtime.domains.ops.admin.debug import _llm_setup_mica_html
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_finance_card_html,
    render_market_card_html,
    render_mermaid_html,
)
from plugins.bot_unified_runtime.output.card_render.usage_cards import (
    usage_report_mica_html,
)

_PHASE_DECL_RE = re.compile(r"--phase:\s*([0-9]*\.?[0-9]+)\s*;")


def _single_phase(html: str) -> str:
    values = _PHASE_DECL_RE.findall(html)
    assert len(values) == 1, f"期望恰好一处 --phase 声明，实得 {values}"
    assert re.fullmatch(r"[01]\.\d{4}", values[0]), values[0]
    return values[0]


class _StubConfig:
    """debug/usage 卡只读 bot_help_card_color 一个属性。"""

    def __init__(self, color: str = "") -> None:
        self.bot_help_card_color = color


# ==================== 三张 f-string 卡渲染入口（i 只改变语义内容） ====================
def _help_html(i: int) -> str:
    return _help_mica_html(
        f"测试正文{i}",
        is_admin=False,
        sections=[(f"测试模块{i}", [(f"/bot help{i}", f"测试说明{i}")])],
    )


def _llm_setup_payload(i: int, config: Any | None = None) -> dict[str, Any]:
    return {
        "config": _StubConfig() if config is None else config,
        "status_label": f"检查完成{i}",
        "status_kind": "ok",
        "message": f"全部通过{i}",
        "rows": [
            {
                "key": f"BOT_KEY_{i}",
                "desc": "模型供应商",
                "range": "openai 兼容",
                "value": f"axonhub-{i}",
                "ok": "1",
            },
        ],
        "next_step": "无",
    }


def _llm_setup_html(i: int) -> str:
    return _llm_setup_mica_html(_llm_setup_payload(i))


def _usage_html(i: int, *, generated_at: str = "2026-09-13 08:00:00") -> str:
    return usage_report_mica_html(
        _StubConfig(),
        kicker=f"测试 · 模型用量{i}",
        title=f"模型用量账单报告{i}",
        status_label=f"账单 {i}.00 元",
        status_kind="ok",
        window_label="09-12 00:00 至 09-12 23:59",
        generated_at=generated_at,
        totals={
            "prompt_tokens": 100 + i,
            "completion_tokens": 10 + i,
            "total_tokens": 110 + i,
            "cost_text": f"{i}.00",
            "calls": 1 + i,
        },
        model_rows=[
            {
                "model": f"model-{i}",
                "prompt": 100 + i,
                "cache_read": 0,
                "cache_write": 0,
                "completion": 10 + i,
                "cost_text": f"{i}.00",
                "priced": True,
            },
        ],
        note="",
    )


_RENDERERS: dict[str, Callable[[int], str]] = {
    "help_card": _help_html,
    "llm_setup_card": _llm_setup_html,
    "usage_card": _usage_html,
}


# ==================== 确定性验收 ====================
@pytest.mark.parametrize("name", sorted(_RENDERERS))
def test_same_payload_renders_identical_html_and_phase(name: str) -> None:
    build = _RENDERERS[name]
    html1, html2 = build(7), build(7)
    assert "Math.random" not in html1, "E01 后页面必须零 JS 随机源"
    assert "<script" not in html1, "相位钉帧后 f-string 卡应零内联脚本"
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


# ==================== digest 口径（非语义字段不进 digest） ====================
def test_usage_generated_at_does_not_change_phase() -> None:
    # generated_at 是易变字段（同 bridge._PHASE_VOLATILE_KEYS 口径）：
    # 仅生成时间不同 → 同帧（卡面 HTML 会带时间戳，只比相位）。
    h1 = _usage_html(3, generated_at="2026-09-13 08:00:00")
    h2 = _usage_html(3, generated_at="2026-09-13 21:30:00")
    assert h1 != h2, "卡面应如实携带生成时间"
    assert _single_phase(h1) == _single_phase(h2)


def test_llm_setup_config_object_does_not_change_phase() -> None:
    # config 是运行时对象（repr 含内存地址，非卡面语义），被排除在 digest 外：
    # 换任意 config 实例 → 同帧。
    h1 = _llm_setup_mica_html(_llm_setup_payload(5, _StubConfig("#336699")))
    h2 = _llm_setup_mica_html(_llm_setup_payload(5, _StubConfig("#ff8800")))
    assert _single_phase(h1) == _single_phase(h2)


# ==================== playwright 双渲对比（后端缺失时跳过） ====================
# 注：`_playwright_available` / `launch_chromium_or_skip` / `chromium_not_installed` 现由
# test_phase_determinism 单一提供（见顶部 import），本文件不再复制第二份（禁三份副本）。


def _double_render_shots(html: str) -> tuple[list[str], list[str], list[bytes]]:
    """同 payload 渲两页（reduced-motion）：返回 computed --phase / blob
    animationName / 截图字节，供确定性断言。"""
    from playwright.sync_api import sync_playwright

    phases: list[str] = []
    animation_names: list[str] = []
    shots: list[bytes] = []
    with sync_playwright() as p:
        browser = launch_chromium_or_skip(p)
        try:
            for _ in range(2):
                page = browser.new_page(
                    viewport={"width": 900, "height": 1200},
                    device_scale_factor=2,
                    reduced_motion="reduce",
                )
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(120)
                phases.append(
                    str(
                        page.evaluate(
                            "getComputedStyle(document.documentElement)"
                            ".getPropertyValue('--phase')"
                        )
                    ).strip()
                )
                animation_names.append(
                    str(
                        page.evaluate(
                            "getComputedStyle("
                            "document.querySelector('.drift-blob.drift-a')"
                            ").animationName"
                        )
                    ).strip()
                )
                shots.append(
                    page.locator(".card")
                    .first
                    .screenshot(type="png", omit_background=True)
                )
                page.close()
        finally:
            browser.close()
    return phases, animation_names, shots


@pytest.mark.skipif(not _playwright_available(), reason="playwright/Chromium 不可用")
def test_playwright_double_render_help_card_phase_and_pixels_stable() -> None:
    html = _help_html(11)
    expected = _single_phase(html)
    phases, animation_names, shots = _double_render_shots(html)
    # --phase 属性一致：浏览器实际生效相位 == HTML 注入值。
    assert phases[0] == phases[1] == expected
    # f-string 卡守卫本就是 affinity 同款写法（0,2,0 靠后），reduce 下真关停。
    assert animation_names[0] == animation_names[1] == "none"
    # 动画已关停 → 无需 animations="disabled" 双保险，静态构图即逐字节稳定。
    assert shots[0] == shots[1]


@pytest.mark.skipif(not _playwright_available(), reason="playwright/Chromium 不可用")
@pytest.mark.parametrize(
    "html_of",
    [
        pytest.param(
            lambda: render_finance_card_html(
                {"title": "金融速览", "sections": [
                    {"name": "巨头", "rows": [{"label": "NVDA", "value": "100"}]},
                ]}
            ),
            id="finance_card",
        ),
        pytest.param(
            lambda: render_market_card_html(
                {"subtitle": "全球股指", "groups": [
                    {"name": "美股", "rows": [
                        {"name": "标普500", "price": "5000", "pct": "+0.5%",
                         "trend": [1.0, 2.0, 3.0]},
                    ]},
                ], "updated_at": "2026-09-13 08:00:00"}
            ),
            id="market_card",
        ),
    ],
)
def test_playwright_reduced_motion_guard_effective(html_of: Callable[[], str]) -> None:
    """首批报告缺陷回归：finance/market 守卫 `.drift-blob`(0,1,0) 曾被基线
    `.drift-blob.drift-a`(0,2,0) 覆盖成死 CSS；修复后 reduce 下必须真关停。"""
    _, animation_names, _ = _double_render_shots(html_of())
    assert animation_names[0] == "none", (
        "prefers-reduced-motion 守卫仍未生效（死 CSS 回归）"
    )


# ==================== mermaid 伪元素 reduced-motion 守卫（首批标记未验项） ====================
def test_mermaid_reduced_motion_guard_same_specificity_and_later() -> None:
    """mermaid 漂移层是伪元素（.card::before/::after，特异性各 (0,1,1)）：
    守卫选择器必须与基线同级且源序靠后才生效（@media 不加特异性），
    防重演 finance/market 死 CSS（守卫 (0,1,0) 被基线 (0,2,0) 永久覆盖）。"""
    html_text = render_mermaid_html("graph TD;A-->B;")
    base_positions = [
        m.start()
        for m in re.finditer(
            r"\.card::(?:before|after)\s*\{[^}]*animation:\s*mica-drift-", html_text
        )
    ]
    assert len(base_positions) == 2, "mermaid 基线漂移应有 ::before/::after 两处声明"
    guard = re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{(?P<body>.*?)\}\s*\}",
        html_text,
        re.DOTALL,
    )
    assert guard, "mermaid 缺 prefers-reduced-motion 守卫块"
    body = guard.group("body")
    assert ".card::before" in body and ".card::after" in body, (
        "守卫必须点名两个漂移伪元素（与基线同特异性 (0,1,1)）"
    )
    assert re.search(r"animation:\s*none", body), "守卫必须关停 animation"
    assert all(guard.start() > pos for pos in base_positions), (
        "守卫必须声明在基线动画之后（同特异性靠源序取胜）"
    )


@pytest.mark.skipif(not _playwright_available(), reason="playwright/Chromium 不可用")
def test_playwright_mermaid_reduced_motion_guard_effective_on_pseudo_elements() -> None:
    """漂移在伪元素上 → computed 校验须走 ::before/::after 伪元素查询：
    默认偏好下真有动画（证明断言非空转），reduce 下 animationName==none。
    CDN mermaid.js 与 CSS 守卫无关，剥除脚本防网络抖动。"""
    from playwright.sync_api import sync_playwright

    html_text = re.sub(
        r"<script\b.*?</script>",
        "",
        render_mermaid_html("graph TD;A-->B;"),
        flags=re.DOTALL,
    )
    observed: dict[str, tuple[str, str]] = {}
    with sync_playwright() as p:
        browser = launch_chromium_or_skip(p)
        try:
            for mode in ("no-preference", "reduce"):
                page = browser.new_page(
                    viewport={"width": 900, "height": 1200},
                    reduced_motion=mode,
                )
                page.set_content(html_text, wait_until="load")
                page.wait_for_timeout(120)
                observed[mode] = tuple(
                    str(
                        page.evaluate(
                            "getComputedStyle(document.querySelector('.card'), "
                            f"'{pseudo}').animationName"
                        )
                    ).strip()
                    for pseudo in ("::before", "::after")
                )
                page.close()
        finally:
            browser.close()
    assert observed["no-preference"] == ("mica-drift-a", "mica-drift-b"), (
        "无障碍偏好关闭时漂移动画应真实运行（守卫不得误伤默认观感）"
    )
    assert observed["reduce"] == ("none", "none"), (
        "prefers-reduced-motion 下伪元素漂移必须真关停（死 CSS 回归）"
    )
