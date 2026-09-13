"""天气卡片适配回归（Task3 收尾，全离线）。

锁定三态（范式与 tests/test_feature_cards.py 一致）：
- 出图分支：假后端可用 → kind=mixed、PNG 落盘 bot_card_render_dir、
  卡片 html 携带真实拉取的天气报告/预警文本（禁止编造数据）；
- 后端缺失 / 返回 None / 渲染抛异常：输出与无卡片时逐字节一致
  （body 相等、kind=text、images 空、text_only 审计），纯文字契约零破坏
  （原文本行为另由 test_weather_alerts_b10.py / test_weather_nmc_retry_nmcflix.py 锁定）。

NMC/Open-Meteo/预警全部打桩，不触网；不写源码树 data/（卡片落 tmp_path）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.weather import (
    build_weather_capability,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
)

_NMC_REPORT = "【测试天气】晴 25℃"
_OVERSEAS_REPORT = "【海外】Sunny 22°C"

_ALERT_FIXTURE: dict[str, Any] = {
    "data": {
        "page": {
            "list": [
                {
                    "alertid": "a1",
                    "issuetime": "2026/09/12 03:05",
                    "title": "黑龙江省大兴安岭地区呼玛县气象台发布大雾黄色预警信号",
                    "url": "/publish/alarm/a1.html",
                    "pic": "",
                }
            ]
        }
    }
}


class _FakeBackend:
    name = "fake"
    available = True

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def render_card(self, payload: dict) -> bytes | None:
        self.captured.append(payload)
        return b"fake-png"


class _BrokenBackend:
    name = "broken"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        return None


class _RaisingBackend:
    name = "raising"
    available = True

    def render_card(self, payload: dict) -> bytes | None:
        raise RuntimeError("boom")


class _StubConfig:
    def __init__(self, card_dir: str) -> None:
        self.bot_card_render_dir = card_dir


def _private_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _group_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="group:42",
        session_type=SessionType.GROUP,
        sender_id="u1",
        group_id="42",
        plain_text=text,
    )


def _patch_nmc_hit(monkeypatch: pytest.MonkeyPatch, *, alerts: bool) -> None:
    """NMC 主通道命中：报告打桩；预警支路按需给一条呼玛黄色大雾。"""
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
        lambda query, proxy="": _NMC_REPORT,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.http_get_json",
        lambda *args, **kwargs: _ALERT_FIXTURE if alerts else {"data": {"page": {"list": []}}},
    )


def _patch_overseas(monkeypatch: pytest.MonkeyPatch) -> None:
    """NMC 未命中 → Open-Meteo 兜底（海外路径）。"""
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
        lambda query, proxy="": None,
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.open_meteo_query",
        lambda query, proxy="": {"latitude": 35.68, "current": {}},
    )
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.weather.format_open_meteo",
        lambda payload: _OVERSEAS_REPORT,
    )


# ---------------------------------------------------------------------------
# 出图分支。
# ---------------------------------------------------------------------------


class TestWeatherCardRendered:
    def test_nmc_hit_with_backend_is_mixed_and_png_written(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_nmc_hit(monkeypatch, alerts=False)
        backend = _FakeBackend()
        capability = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("天气 黑龙江-呼玛"), None)
        assert result.kind == "mixed"
        assert result.images and result.images[0]["file"]
        png_path = Path(result.images[0]["file"])
        assert png_path.exists()
        assert png_path.read_bytes() == b"fake-png"
        assert "card_rendered" in result.audit_tags
        assert "weather_source:nmc" in result.audit_tags
        # 卡片 html 携带真实拉取的报告与查询词，禁止编造区块。
        html_text = str(backend.captured[0]["html"])
        assert _NMC_REPORT in html_text
        assert "黑龙江-呼玛" in html_text

    def test_alerts_text_also_enters_card_html(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_nmc_hit(monkeypatch, alerts=True)
        backend = _FakeBackend()
        capability = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("天气 黑龙江-呼玛"), None)
        assert result.kind == "mixed"
        assert "气象预警" in result.body  # 文本含预警段
        assert "weather_alerts:1" in result.audit_tags
        html_text = str(backend.captured[0]["html"])
        assert "气象预警" in html_text  # 卡片同步携带预警段
        assert "黄色大雾预警" in html_text

    def test_overseas_open_meteo_with_backend_is_mixed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_overseas(monkeypatch)
        backend = _FakeBackend()
        capability = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("天气 Tokyo"), None)
        assert result.kind == "mixed"
        assert result.images and Path(result.images[0]["file"]).exists()
        assert "card_rendered" in result.audit_tags
        assert "weather_source:open-meteo" in result.audit_tags
        html_text = str(backend.captured[0]["html"])
        assert _OVERSEAS_REPORT in html_text


# ---------------------------------------------------------------------------
# 回退三态：后端缺失 / 坏后端 / 渲染异常 → 与无卡片时逐字节一致。
# ---------------------------------------------------------------------------


class TestWeatherCardFallback:
    @pytest.mark.parametrize("alerts", [False, True])
    def test_failing_backends_keep_body_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, alerts: bool
    ) -> None:
        _patch_nmc_hit(monkeypatch, alerts=alerts)
        baseline = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=None
        )(_private_message("天气 黑龙江-呼玛"), None)
        assert baseline.kind == "text"
        assert baseline.images == []
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = build_weather_capability(
                _StubConfig(str(tmp_path)), render_backend=backend
            )(_private_message("天气 黑龙江-呼玛"), None)
            assert result.kind == "text"
            assert result.images == []
            assert result.body == baseline.body
            assert "text_only" in result.audit_tags

    def test_overseas_fallback_body_identical(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_overseas(monkeypatch)
        baseline = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=None
        )(_private_message("天气 Tokyo"), None)
        assert baseline.kind == "text"
        assert baseline.images == []
        for backend in (_BrokenBackend(), _RaisingBackend()):
            result = build_weather_capability(
                _StubConfig(str(tmp_path)), render_backend=backend
            )(_private_message("天气 Tokyo"), None)
            assert result.kind == "text"
            assert result.images == []
            assert result.body == baseline.body

    def test_city_not_found_never_renders_card(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 群聊查不到城市：静默审计路径（SILENT_AUDIT），任何后端都不出卡。
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
            lambda query, proxy="": None,
        )
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.weather.open_meteo_query",
            lambda query, proxy="": None,
        )
        backend = _FakeBackend()
        capability = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_group_message("天气 Nowhereville"), None)
        assert result.kind == "text"
        assert result.images == []
        assert result.body == ""
        assert result.send_policy == SendPolicy.SILENT_AUDIT
        assert backend.captured == []  # 无数据不出卡、不编造

    def test_all_sources_fail_stays_text_without_card(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("network down")

        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.weather.nmc_weather_query",
            lambda query, proxy="": None,
        )
        monkeypatch.setattr(
            "plugins.bot_unified_runtime.capabilities.weather.open_meteo_query",
            _boom,
        )
        backend = _FakeBackend()
        capability = build_weather_capability(
            _StubConfig(str(tmp_path)), render_backend=backend
        )
        result = capability(_private_message("天气 Tokyo"), None)
        assert result.kind == "text"
        assert result.images == []
        assert "没有查到" in result.body
        assert backend.captured == []
