"""usage/钱包（模型用量账单）卡片回归（Task3 收尾，全离线）。

锁定三件事：
- 视觉 token 单一来源：usage_cards 的 accent/加深/wash 四 token 全部消费
  theme_tokens（本模块不再持有私有 hex 副本）；html 中的 --wash-* 与
  derive_wash_tokens(accent) 逐键一致（brief 第 4 条的机器可执行形态）；
- 出图分支：假后端可用 → PNG 落盘 card_dir（prefix 命名），路径返回非空；
- 回退三态：后端缺失 / 不可用 / 返回 None / 渲染抛异常 / 空 html →
  一律返回空串，调用方（usage_monitor / echo 链）回退纯文本（零破坏铁律）。

HTML 基线顺带锁定渲染契约红线：无 meta viewport、body 透明、.card 截图根、
两枚阴影 token、字重 ≤700——契约测试不扫描本模块（templates 白名单制），
此处补上等价断言。全部离线，不写源码树 data/。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    derive_wash_tokens,
)
from plugins.bot_unified_runtime.output.card_render.usage_cards import (
    render_usage_card_png,
    usage_card_accent,
    usage_report_mica_html,
)

_ACCENT = "#318ce7"


class _StubConfig:
    def __init__(self, card_color: str = _ACCENT) -> None:
        self.bot_help_card_color = card_color


_AGGREGATE = {
    "prompt_tokens": 1200,
    "cache_read_tokens": 300,
    "cache_write_tokens": 400,
    "completion_tokens": 560,
    "total_tokens": 2460,
    "calls": 12,
    "cost_milli": 1500,
    "unpriced_calls": 0,
}

_MODEL_ROWS = [
    {
        "model": "model-alpha",
        "prompt": 1000,
        "cache_read": 300,
        "cache_write": 400,
        "completion": 500,
        "cost_text": "1.50",
        "priced": True,
    },
    {
        "model": "model-beta",
        "prompt": 200,
        "cache_read": 0,
        "cache_write": 0,
        "completion": 60,
        "cost_text": "未计价",
        "priced": False,
    },
]


def _html(**overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "kicker": "定时报告 · 模型用量",
        "title": "模型用量账单报告",
        "status_label": "账单 1.50 元",
        "status_kind": "ok",
        "window_label": "09-12 13:00 至 09-12 18:00",
        "generated_at": "2026-09-12 18:00:00",
        "totals": dict(_AGGREGATE),
        "model_rows": [dict(row) for row in _MODEL_ROWS],
    }
    kwargs.update(overrides)
    return usage_report_mica_html(_StubConfig(), **kwargs)


class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self, png: bytes | None = b"fake-usage-png") -> None:
        self._png = png
        self.captured: list[dict] = []

    def render_card(self, payload: dict) -> bytes | None:
        self.captured.append(payload)
        return self._png


class _UnavailableBackend:
    name = "unavailable"
    available = False

    def render_card(self, payload: dict) -> bytes | None:
        raise AssertionError("unavailable backend must not be called")


class _RaisingBackend:
    name = "raising"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# token 单一来源（brief 第 4 条）。
# ---------------------------------------------------------------------------


class TestUsageCardTokens:
    def test_accent_derives_from_config_color(self) -> None:
        assert usage_card_accent(_StubConfig("#318ce7"))[0] == "#318ce7"

    def test_accent_empty_config_falls_back_neutral_gray(self) -> None:
        accent, ink = usage_card_accent(object())
        assert accent == "#607080"  # 与 theme_tokens.UNKNOWN_PLATFORM_COLOR 同源
        assert ink == "#4c5966"  # int(0x60*.8)=4c, int(0x70*.8)=59, int(0x80*.8)=66
        assert ink != accent

    def test_html_wash_tokens_match_theme_tokens_derivation(self) -> None:
        html_text = _html()
        accent, _ink = usage_card_accent(_StubConfig())
        expected = derive_wash_tokens(accent)
        for css_key, token_key in (
            ("wash-1", "wash_1"),
            ("wash-2", "wash_2"),
            ("wash-3", "wash_3"),
            ("wash-mist", "wash_mist"),
        ):
            match = re.search(rf"--{css_key}:(#[0-9a-f]{{6}})", html_text)
            assert match is not None, css_key
            assert match.group(1) == expected[token_key], css_key

    def test_html_carries_brand_shell_contract_basics(self) -> None:
        html_text = _html()
        low = html_text.lower()
        # 无 meta viewport（playwright viewport 由后端控制）。
        assert "name=\"viewport\"" not in low and "<meta viewport" not in low
        # body 透明（omit_background 截图依赖）。
        assert "background:transparent" in low
        # .card 截图根存在。
        assert 'class="stage card"' in html_text
        # 恰好两枚阴影 token，各定义一次。
        assert html_text.count("--mica-shadow:") == 1
        assert html_text.count("--mica-shadow-soft:") == 1
        # 字重 ≤ 700。
        for banned in ("font-weight:8", "font-weight:9", "font-weight: 8", "font-weight: 9"):
            assert banned not in low


# ---------------------------------------------------------------------------
# 内容承载：真实聚合数据上卡，不编造。
# ---------------------------------------------------------------------------


class TestUsageCardContent:
    def test_totals_and_model_rows_enter_html(self) -> None:
        html_text = _html()
        assert "模型用量账单报告" in html_text
        assert "model-alpha" in html_text
        assert "2,460" in html_text  # 总 token 千分位
        assert "1.50" in html_text  # 账单
        assert "12" in html_text  # 调用次数

    def test_unpriced_note_shown_only_when_present(self) -> None:
        assert "未配置价格" not in _html()
        html_text = _html(totals={**_AGGREGATE, "unpriced_calls": 3})
        assert "3 次调用未配置价格，未计入账单" in html_text

    def test_custom_note_text_enters_html(self) -> None:
        assert "只有管理员能看到这份报告" in _html(note="只有管理员能看到这份报告")


# ---------------------------------------------------------------------------
# render_usage_card_png 三态：出图 / 后端缺失与坏后端 / 渲染异常 → 空串。
# ---------------------------------------------------------------------------


class TestUsageCardRenderFallback:
    def test_fake_backend_writes_png_file(self, tmp_path: Path) -> None:
        backend = _FakeBackend()
        path = render_usage_card_png(
            backend,
            "<html><body>x</body></html>",
            card_dir=str(tmp_path),
            request_id="req-usage-1",
            prefix="usage_report",
        )
        assert path
        png_path = Path(path)
        assert png_path.exists()
        assert png_path.read_bytes() == b"fake-usage-png"
        assert png_path.name.startswith("usage_report_")
        assert png_path.parent == tmp_path

    def test_missing_or_unavailable_backend_returns_empty(self, tmp_path: Path) -> None:
        html_text = "<html><body>x</body></html>"
        assert render_usage_card_png(
            None, html_text, card_dir=str(tmp_path), request_id="r"
        ) == ""
        assert render_usage_card_png(
            _UnavailableBackend(), html_text, card_dir=str(tmp_path), request_id="r"
        ) == ""
        assert list(tmp_path.iterdir()) == []  # 不落任何文件

    def test_broken_png_and_exception_return_empty(self, tmp_path: Path) -> None:
        html_text = "<html><body>x</body></html>"
        # 后端返回 None（渲染失败契约）。
        assert render_usage_card_png(
            _FakeBackend(png=None),
            html_text,
            card_dir=str(tmp_path),
            request_id="r",
        ) == ""
        # 后端抛异常 → 空串，调用方回退纯文本。
        assert render_usage_card_png(
            _RaisingBackend(), html_text, card_dir=str(tmp_path), request_id="r"
        ) == ""
        # 空 html → 空串。
        assert render_usage_card_png(
            _FakeBackend(), "", card_dir=str(tmp_path), request_id="r"
        ) == ""
        assert list(tmp_path.iterdir()) == []  # 失败路径零落盘
