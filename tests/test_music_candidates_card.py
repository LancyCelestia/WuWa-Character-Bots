"""点歌多候选 Mica 选择卡：模板渲染 + music 能力接线回归。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.music import (
    build_music_capability,
    clear_music_candidate_sessions,
)
from plugins.bot_unified_runtime.contracts import SessionType, build_parsed_content
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.output import templates as card_templates
from plugins.bot_unified_runtime.output.card_render.bridge import (
    render_song_candidates_html,
)


def _payload(**overrides):
    payload = {
        "query": "晴天remix",
        "platform": "netease_music",
        "platform_name": "网易云",
        "ttl_seconds": 300,
        "candidates": [
            {"index": 1, "name": "晴天 (翻自 周杰伦)", "artist": "路人", "album": ""},
            {"index": 2, "name": "下雨天", "artist": "南拳妈妈", "album": "雨的专辑"},
        ],
    }
    payload.update(overrides)
    return payload


def test_render_html_contains_query_index_ttl_platform() -> None:
    html_text = render_song_candidates_html(_payload())

    assert "找到 2 首「晴天remix」相关歌曲" in html_text
    assert "01" in html_text and "02" in html_text
    assert "300s 内有效" in html_text
    assert "网易云" in html_text
    assert "回复编号直接点" in html_text
    assert "Top" in html_text  # 前 3 名加重视觉
    assert "None" not in html_text


def test_render_html_missing_artist_album_silent_fallback() -> None:
    html_text = render_song_candidates_html(
        _payload(candidates=[{"index": 1, "name": "无名", "artist": "", "album": ""}])
    )

    assert "未知歌手" in html_text
    assert "None" not in html_text


def test_render_html_known_platform_uses_brand_color_via_containment() -> None:
    html_text = render_song_candidates_html(_payload(platform="netease_music"))

    assert "#c20c0c" in html_text


def test_render_html_unknown_platform_falls_back_to_neutral() -> None:
    html_text = render_song_candidates_html(_payload(platform="whatever_fm"))

    assert "#607080" in html_text


def test_templates_reexport_matches_bridge() -> None:
    payload = _payload()

    assert card_templates.render_song_candidates_html(payload) == (
        render_song_candidates_html(payload)
    )


class _FakeBackend:
    name = "fake"

    def __init__(self, *, available: bool = True, png: bytes | None = b"png") -> None:
        self.available = available
        self.png = png
        self.calls: list[dict] = []

    def render_card(self, payload: dict) -> bytes | None:
        self.calls.append(payload)
        return self.png


def _message(text: str, session_id: str = "private:card-u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _item(title: str) -> object:
    return build_parsed_content(
        platform="netease_music",
        item_id="picked-1",
        item_kind="music",
        title=title,
        author_name="周杰伦",
        canonical_url="https://music.163.com/song/picked-1",
    )


def _candidates() -> list[dict[str, str]]:
    return [
        {"provider_track_id": "101", "name": "晴天", "artist": "周杰伦", "album": "叶惠美"},
        {"provider_track_id": "102", "name": "晴天 (翻自 周杰伦)", "artist": "路人", "album": ""},
    ]


def _build(tmp_path: Path, backend):
    config = SimpleNamespace(
        bot_music_candidates_enabled=True,
        bot_music_candidates_ttl_seconds=300.0,
        bot_music_candidates_limit=5,
        bot_card_render_dir=str(tmp_path / "cards"),
    )

    def search_fn(query: str):
        return None if query.isdigit() else _item("第一命中")

    def list_fn(query: str, limit: int = 5) -> list[dict[str, str]]:
        return _candidates()

    def detail_fn(candidate: dict, *, query: str = ""):
        return _item("选中候选")

    capability = build_music_capability(
        config,
        providers=[("netease_music", "网易云", search_fn)],
        candidate_providers={"netease_music": (list_fn, detail_fn)},
        render_backend=backend,
    )
    return capability


def test_card_backend_success_renders_mixed_result_and_session(tmp_path: Path) -> None:
    clear_music_candidate_sessions()
    backend = _FakeBackend()
    capability = _build(tmp_path, backend)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.kind == "mixed"
    assert result.images and result.images[0]["file"].endswith(".png")
    assert Path(str(result.images[0]["file"])).read_bytes() == b"png"
    assert "晴天remix" in result.body and "2 个候选" in result.body
    assert "300 秒内有效" in result.body
    assert "music_candidates_card" in result.audit_tags
    assert "music_candidates" in result.audit_tags
    # 渲染 payload 约定：候选卡画布 1000x900、无远程图 wait_ms=300。
    assert backend.calls and backend.calls[0]["viewport"] == {"width": 1040, "height": 900}
    assert backend.calls[0]["wait_ms"] == 300
    assert "晴天remix" in backend.calls[0]["html"]
    # 候选会话仍写入：随后编号可选中。
    second = capability(_message("点歌 1"), None)
    assert second.title == "选中候选"


def test_backend_none_result_falls_back_to_text_numbered_list(tmp_path: Path) -> None:
    clear_music_candidate_sessions()
    backend = _FakeBackend(png=None)
    capability = _build(tmp_path, backend)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.kind == "text"
    assert "1. 晴天 - 周杰伦" in result.body
    assert "回复编号" in result.body
    assert "music_candidates" in result.audit_tags
    assert "music_candidates_card" not in result.audit_tags
    assert not list(tmp_path.rglob("*.png"))


def test_backend_absent_uses_legacy_text_path(tmp_path: Path) -> None:
    clear_music_candidate_sessions()
    capability = _build(tmp_path, backend=None)

    result = capability(_message("点歌 晴天remix"), None)

    assert result.kind == "text"
    assert "回复编号" in result.body
    assert "music_candidates" in result.audit_tags
    assert "music_candidates_card" not in result.audit_tags
