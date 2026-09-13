"""卡面样张脚本回归（scripts/render_card_samples.py，全离线不真开浏览器）。

覆盖：
- 18 张样张 payload 构造函数逐卡非空断言（HTML 体量/守岸人署名/视口键）；
- 关键卡面内容抽查（平台主题色、渠道子行、脏数据归一、非上市红线等）；
- --list 输出包含全部登记卡型（main(["--list"]) 返回 0，纯离线）；
- 渲染函数在假后端下的调用路径：payload 透传 / 文件名含卡型 / 单卡失败
  不中断其余卡 / 汇总表标注 FAIL 与原因 / 未知卡型退出码。

PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_render_card_samples.py \
    --basetemp="$TEMP/sample" -p no:cacheprovider
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest

from scripts import render_card_samples as rcs

# ==================== 假后端 ====================


def _tiny_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (49, 140, 231)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeBackend:
    """记录 render_card 入参并返回固定 PNG 的假后端（契约同 Protocol）。"""

    name = "fake"
    available = True

    def __init__(self, *, png: bytes | None = None, fail_keys: set[str] | None = None):
        self.png = png if png is not None else _tiny_png()
        self.fail_keys = fail_keys or set()
        self.calls: list[dict[str, Any]] = []

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls.append(payload)
        html = str(payload.get("html", ""))
        for key in self.fail_keys:
            if key in html:
                return None
        return self.png


# ==================== 1. payload 构造逐卡非空 ====================


@pytest.mark.parametrize("card", rcs.CARDS, ids=[card.key for card in rcs.CARDS])
def test_payload_builder_renders_nonempty_html(card: rcs.SampleCard) -> None:
    payload = card.build()
    assert isinstance(payload, dict)
    html = payload.get("html")
    assert isinstance(html, str) and len(html) > 500, f"{card.key} HTML 过短"
    assert re.search(r'class="[^"]*\bcard\b[^"]*"', html), f"{card.key} 缺 .card 根"
    assert payload.get("device_scale_factor") == 2
    viewport = payload.get("viewport")
    if card.key != "media_archive":  # 媒体卡沿用后端缺省视口（同生产）。
        assert isinstance(viewport, dict) and viewport.get("width", 0) > 0


@pytest.mark.parametrize("card", rcs.CARDS, ids=[card.key for card in rcs.CARDS])
def test_payload_builder_has_shorekeeper_signature(card: rcs.SampleCard) -> None:
    html = str(card.build().get("html", ""))
    if card.key == "mermaid_flow":
        assert "守岸人" in html  # mermaid 卡 bot_name 直出。
    else:
        assert "守岸人" in html, f"{card.key} 缺守岸人署名"


# ==================== 2. 关键卡面内容抽查 ====================


def test_universal_bilibili_video_content() -> None:
    html = rcs.build_universal_bilibili_video()["html"]
    assert "#fb7299" in html  # bilibili accent。
    assert "AV 112874701" in html  # 页脚媒体 ID（av 优先）。
    assert "152\u2009万" in html  # fmt_count 数量级格式化（1520000 → 152 万）。
    assert "data:image/png;base64," in html  # 封面/头像离线 data URI。


def test_universal_bgv_has_music_credit() -> None:
    html = rcs.build_universal_bilibili_bgv()["html"]
    assert "Iris" in html
    assert "music-credit" in html


def test_universal_search_gallery_images_offline() -> None:
    html = rcs.build_universal_default_search()["html"]
    assert "image-gallery" in html
    assert html.count("data:image/png;base64,") >= 3


def test_universal_netease_music_uses_netease_accent() -> None:
    html = rcs.build_universal_netease_music()["html"]
    assert "#c20c0c" in html  # netease accent。
    assert "music-credit" in html


def test_market_index_has_groups_and_sparkline() -> None:
    html = rcs.build_market_index()["html"]
    assert "上证指数" in html and "莫斯科指数" in html
    assert "<polyline" in html  # trend 序列真折线。
    assert "暂无历史走势数据" in html  # 无走势行的 trend_note 分支。


def test_market_commodities_bond_northbound_titles() -> None:
    assert "大宗商品速览" in rcs.build_market_commodities()["html"]
    bond = rcs.build_market_bond()["html"]
    assert "中美国债收益率速览" in bond
    assert "10Y−2Y 期限利差" in bond
    assert "北向资金速览" in rcs.build_market_northbound()["html"]


def test_finance_stocks_unlisted_redline_and_trend_svg() -> None:
    html = rcs.build_finance_stocks()["html"]
    assert "非上市" in html  # OpenAI/字节非上市红线口径上卡。
    assert "<svg" in html  # line_chart_svg 折线（内部生成整段 svg 放行）。


def test_affinity_private_and_group_contents() -> None:
    private = rcs.build_affinity_private()["html"]
    assert "澜汐" in private and "亲近" in private
    group = rcs.build_affinity_group()["html"]
    assert "澜汐" in group and "霞月" in group


def test_affinity_dirty_normalized_no_none_leak() -> None:
    html = rcs.build_affinity_dirty()["html"]
    body = html.split("<body>", 1)[-1]
    assert "None" not in body  # vis5 归一：缺省分数按 0.0 渲染。
    assert "守岸人" in html


def test_song_candidates_content() -> None:
    html = rcs.build_song_candidates()["html"]
    assert "晴天" in html and "#c20c0c" in html


def test_mermaid_payload_matches_production_ready_gate() -> None:
    payload = rcs.build_mermaid()
    assert payload["wait_js"] == bridge_ready_js()
    assert "graph TD" in payload["html"]
    assert "cdn.jsdelivr.net/npm/mermaid@11" in payload["html"]  # 模板 URL（传输层拦截换血）。


def bridge_ready_js() -> str:
    from plugins.bot_unified_runtime.output.card_render.bridge import (
        _MERMAID_READY_JS,
    )

    return _MERMAID_READY_JS


def test_usage_report_has_channel_subrows() -> None:
    html = rcs.build_usage_report()["html"]
    assert '<div class="crow glass">' in html  # 渠道子行。
    assert "axonhub-main" in html and "axonhub-backup" in html
    assert "未计价" in html


def test_media_archive_card_content() -> None:
    html = rcs.build_media_archive()["html"]
    assert "媒体归档" in html and "cosplay" in html
    assert "原神" in html


def test_error_card_red_accent_and_full_sections() -> None:
    from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
        ERROR_ACCENT,
    )

    html = rcs.build_error_card()["html"]
    assert f"--pc: {ERROR_ACCENT}" in html  # 红强调（ERROR_THEME 注入，非平台色）。
    for marker in (
        "运行异常",
        "RUNTIME DIAGNOSTIC",
        "触发回显",
        "栈摘录",
        "触发方法",
        "配置快照",
        "版本与构建",
        "平台与协议",
        "IDs 与时间",
        "TimeoutError",
        "weather.py:120",
        "bot_weather_api_key",
    ):
        assert marker in html, f"缺分区/内容: {marker}"
    assert re.search(r'class="shell card"', html)  # 元素截图契约根。
    payload = rcs.build_error_card()
    assert payload["viewport"] == {"width": 1160, "height": 1800}  # 同生产 render_error_card_png。


# ==================== 3. --list 模式 ====================


def test_list_mode_prints_all_registered_keys(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = rcs.main(["--list"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for card in rcs.CARDS:
        assert card.key in out, f"--list 缺卡型 {card.key}"


def test_registry_has_no_duplicate_keys() -> None:
    keys = [card.key for card in rcs.CARDS]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 17


# ==================== 4. 假后端渲染路径（≥6 例） ====================


def _run(out_dir: Path, keys: list[str] | None = None, **fake_kwargs: Any):
    backend = FakeBackend(**fake_kwargs)
    results = rcs.render_samples(out_dir, keys=keys, backend=backend)
    return backend, results


def test_render_samples_all_cards_through_fake_backend(tmp_path: Path) -> None:
    backend, results = _run(tmp_path)
    assert len(results) == len(rcs.CARDS)
    assert len(backend.calls) == len(rcs.CARDS)
    assert all(result.ok for result in results)


def test_render_samples_writes_png_named_by_card_key(tmp_path: Path) -> None:
    keys = ["market_index", "affinity_group", "usage_report"]
    _backend, results = _run(tmp_path, keys=keys)
    assert [result.key for result in results] == keys
    for index, result in enumerate(results, start=1):
        assert result.path is not None
        assert result.path.parent == tmp_path
        assert result.key in result.path.name  # 文件名含卡型。
        assert result.path.name.startswith(f"{index:02d}_")
        assert result.path.read_bytes()  # PNG 落盘非空。
        assert result.dimensions == "4x4"
        assert result.elapsed_ms >= 0


def test_render_samples_single_failure_does_not_stop_others(tmp_path: Path) -> None:
    keys = ["market_index", "affinity_dirty", "song_candidates"]
    # affinity_dirty 的 HTML 落「脏」样张文本 → 该卡后端返回 None。
    backend, results = _run(tmp_path, keys=keys, fail_keys={"乙"})
    assert [result.ok for result in results] == [True, False, True]
    assert "RuntimeError" in results[1].error
    assert results[0].path is not None and results[2].path is not None
    assert len(backend.calls) == 3  # 失败卡也走过后端（不中断）。


def test_render_samples_empty_backend_result_recorded_as_failure(tmp_path: Path) -> None:
    class EmptyBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            super().render_card(payload)
            return None

    backend = EmptyBackend()
    results = rcs.render_samples(tmp_path, keys=["finance_stocks"], backend=backend)
    assert not results[0].ok
    assert "None" in results[0].error or "空" in results[0].error
    assert results[0].path is None


def test_render_samples_builder_exception_isolated(tmp_path: Path) -> None:
    class BoomBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            raise RuntimeError("boom")

    results = rcs.render_samples(tmp_path, keys=["usage_report"], backend=BoomBackend())
    assert not results[0].ok
    assert "boom" in results[0].error


def test_main_only_filter_and_unknown_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = rcs.main(["--out", str(tmp_path), "--only", "market_bond,media_archive"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "market_bond" in out and "media_archive" in out
    assert "2/2 张成功" in out

    exit_code = rcs.main(["--out", str(tmp_path), "--only", "no_such_key"])
    assert exit_code == 2


def test_main_reports_failure_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            super().render_card(payload)
            return None

    monkeypatch.setattr(rcs, "build_render_backend", lambda name="": FailBackend())
    exit_code = rcs.main(["--out", str(tmp_path), "--only", "market_index"])
    assert exit_code == 1  # 有卡失败 → 退出码 1，但流程完整打印汇总。
