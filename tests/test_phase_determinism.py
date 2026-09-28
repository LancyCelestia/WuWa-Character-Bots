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

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _help_mica_html,
)
from plugins.bot_unified_runtime.domains.ops.admin.debug import _llm_setup_mica_html
from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
    digest_phase,
    payload_phase,
    render_affinity_card_html,
    render_error_card_html,
    render_finance_card_html,
    render_market_card_html,
    render_mermaid_html,
    render_song_candidates_html,
    render_universal_card_html,
    stable_payload_digest,
)
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import (
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.domains.render.templates import render_media_card_html

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


class _PhaseStubConfig:
    """debug/usage builder 只读 bot_help_card_color 一个属性。"""

    bot_help_card_color = ""


def _error_payload(i: int) -> dict[str, Any]:
    return {
        "human_text": f"能力执行遇到异常，已留档{i}",
        "exc_type": f"RuntimeError{i}",
        "exc_message": f"模拟异常{i}",
        "trigger_echo": f"/bot status {i}",
        "help_text": "稍后再试",
    }


def _debug_llm_setup_html(i: int) -> str:
    payload: dict[str, Any] = {
        "config": _PhaseStubConfig(),
        "status_label": "检查完成",
        "status_kind": "ok",
        "message": f"全部通过{i}",
        "rows": [
            {
                "key": "BOT_CHAT_PROVIDER",
                "desc": "模型供应商",
                "range": "openai 兼容",
                "value": "axonhub",
                "ok": "1",
            },
        ],
        "next_step": f"无{i}",
    }
    return _llm_setup_mica_html(payload)


def _usage_report_html(i: int) -> str:
    return usage_report_mica_html(
        _PhaseStubConfig(),
        kicker=f"测试{i} · 模型用量",
        title=f"模型用量账单报告{i}",
        status_label="账单 0.00 元",
        status_kind="ok",
        window_label=f"09-18 0{i}:00 至 09-18 23:59",
        generated_at="2026-09-18 23:59:00",
        totals={
            "prompt_tokens": 100,
            "cache_read_tokens": 10,
            "cache_write_tokens": 20,
            "completion_tokens": 30,
            "total_tokens": 160,
            "calls": 3,
            "cost_text": "0.00",
            "unpriced_calls": 0,
        },
        model_rows=[
            {
                "model": f"model-{i}",
                "prompt": 100,
                "cache_read": 10,
                "cache_write": 20,
                "completion": 30,
                "cost_text": "0.00",
                "priced": True,
            }
        ],
    )


def _echo_help_html(i: int) -> str:
    return _help_mica_html(
        f"测试正文{i}",
        is_admin=False,
        sections=[(f"测试模块{i}", [(f"/bot help {i}", "测试说明")])],
    )


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
    # 2026-09-18 v21r3 渲染统一：+= error/usage/echo/debug 四入口（同既有假
    # 后端模式；error 走 bridge.render_error_card_html，相位=payload digest）。
    "error_card": lambda i: render_error_card_html(_error_payload(i)),
    "usage_report": _usage_report_html,
    "echo_help": _echo_help_html,
    "debug_llm_setup": _debug_llm_setup_html,
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
    from plugins.bot_unified_runtime.domains.render.render_backends import (
        build_render_backend,
    )

    backend = build_render_backend("playwright")
    return bool(getattr(backend, "available", False))


# ---- S345 #83 J-1：三门与外层 skipif 共用的**唯一**「能否真启动」判据 + 唯一 launch 出口 ----
# 单一事实源。此前 :302/:197/:329 三处各写一份 `except Exception: pytest.skip(类名)`，
# 于是「包能导入而二进制坏了 / 参数写错 / 磁盘满」被塌成一句 `Chromium 启动失败（ValueError）`
# 后静默 skip——视觉确定性整面能在零红下永久停摆（见 SILENT-EXCEPT-AUDIT-20260925.md #8–#10）。
# 判据只认「环境确实没装」这一种可诚实 skip 的形态；其余异常**一律上抛=明红**。
# 生产根零接触、不新建任何告警出口（S345 简报红线：需新出口就停下报候选，不自己造第二条路）。
_CHROMIUM_MISSING_MARKERS: tuple[str, ...] = (
    "Executable doesn't exist",
    "Please run `playwright install",
    "playwright install chromium",
)


def chromium_not_installed(exc: BaseException) -> bool:
    """唯一判据：区分「环境没装 Chromium」(→可 skip) 与「坏了/参数错/磁盘满」(→必须明红)。

    三门与外层 skipif 共用它；禁三份副本。判据本身由永不 skip 的
    `test_chromium_launch_criterion_is_discriminating` 哨兵守着（有人把它改成恒 True
    ⇒ 三门集体静默 ⇒ 该哨兵当场红）。
    """
    text = str(exc)
    return any(marker in text for marker in _CHROMIUM_MISSING_MARKERS)


def launch_chromium_or_skip(pw: Any) -> Any:
    """唯一 launch 出口：真启动一次。

    - 「没装」→ `pytest.skip`，**reason 必带异常原文** `str(exc)`（J-3：不许只留类名）；
    - 其余异常 → 照上抛 → 调用该测试**明红**，绝不静默消失。
    """
    try:
        return pw.chromium.launch(headless=True)
    except Exception as exc:
        # 只有「确实没装」才 skip（且 reason 带 str(exc)），其余异常一律上抛=明红，见 chromium_not_installed。
        if chromium_not_installed(exc):
            pytest.skip(
                f"Chromium 未安装，无法启动（{type(exc).__name__}: {exc}）"
            )
        raise


def test_chromium_launch_criterion_is_discriminating() -> None:
    """永不 skip 的判据哨兵：喂合成异常，钉死「没装」与「坏了」必须分家。

    把 `chromium_not_installed` 注毒成恒 True ⇒ 三门会集体静默 ⇒ 本条必红（J-1 牙）。
    """
    assert chromium_not_installed(
        RuntimeError("BrowserType.launch: Executable doesn't exist at /x/chrome.exe")
    ) is True
    assert chromium_not_installed(
        RuntimeError("Please run `playwright install chromium`")
    ) is True
    # 「坏了/参数错/磁盘满」绝不能被判成「没装」——否则又回到静默消失。
    assert chromium_not_installed(ValueError("invalid launch argument")) is False
    assert chromium_not_installed(OSError("disk full or permission denied")) is False


def test_playwright_chromium_launch_canary_is_never_silent() -> None:
    """永不 skip 的 launch 哨兵：真起一次 Chromium。缺位即红（宁红不静默），

    证明「截图字节等值 / --phase 钉帧 / reduced-motion 伪元素守卫」这一整面没在
    零红下停摆。本函数**既无 skipif、体内也无 pytest.skip**（结构锁
    `test_render_launch_guards_share_single_criterion_and_canary_is_loud` 执法）。
    真缺浏览器环境下它会红——这是刻意设计的一次性显形（S335 §6-4「可接受方向」）。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 900, "height": 1200},
                device_scale_factor=2,
                reduced_motion="reduce",
            )
            page.set_content(
                "<html><body><div class='card'>canary</div></body></html>",
                wait_until="load",
            )
            page.wait_for_timeout(60)
            shot = page.locator(".card").first.screenshot(type="png")
            page.close()
        finally:
            browser.close()
    assert isinstance(shot, (bytes, bytearray)) and len(shot) > 100, (
        f"哨兵截图异常短（{len(shot)} 字节）＝渲染面没真跑起来"
    )


@pytest.mark.skipif(not _playwright_available(), reason="playwright/Chromium 不可用")
def test_playwright_double_render_phase_and_pixels_stable() -> None:
    from playwright.sync_api import sync_playwright

    html = render_finance_card_html(_finance_payload(11))
    expected = _single_phase(html)
    computed: list[str] = []
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
