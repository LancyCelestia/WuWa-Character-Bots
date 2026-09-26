"""v21r2 SEARCH 席：ACG 竖源与时效加权融合测试（全离线，mock transport，零真实网络）。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.character import WebSearchHit
from plugins.bot_unified_runtime.domains.core.search import acg_search
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
    ParseHttpError,
)

TODAY = date(2026, 9, 17)


# ---------------------------------------------------------------------------
# Bangumi 竖源
# ---------------------------------------------------------------------------


def test_bangumi_search_parses_payload() -> None:
    captured: dict = {}

    def transport(url: str, payload: object, **kwargs: object) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        captured["ua"] = kwargs.get("user_agent", "")
        return {
            "data": [
                {
                    "id": 425998,
                    "name": "Sousou no Frieren",
                    "name_cn": "葬送的芙莉莲",
                    "date": "2026-07-05",
                    "score": 9.1,
                    "summary": "勇者一行的魔导使……",
                }
            ]
        }

    results = acg_search.bangumi_search("芙莉莲", transport=transport)
    assert len(results) == 1
    hit = results[0]
    assert hit.source == "bangumi"
    assert hit.title == "葬送的芙莉莲"
    assert hit.date == "2026-07-05"
    assert hit.url == "https://bgm.tv/subject/425998"
    assert "评分9.1" in hit.extra
    assert "原名 Sousou no Frieren" in hit.extra
    # Bangumi v0 API 强制自定义 UA（默认 UA 403）。
    assert "shorekeeper" in str(captured["ua"])
    assert str(captured["payload"]).find("芙莉莲") >= 0


def test_bangumi_search_empty_and_garbage() -> None:
    assert acg_search.bangumi_search("", transport=lambda *a, **k: {}) == []
    assert acg_search.bangumi_search("x", transport=lambda *a, **k: None) == []
    assert acg_search.bangumi_search("x", transport=lambda *a, **k: {"data": "bad"}) == []


# ---------------------------------------------------------------------------
# 萌娘百科竖源（复用既有 sources/moegirl，monkeypatch 注入）
# ---------------------------------------------------------------------------


def test_moegirl_lookup_reuses_existing_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.location.data import (
        moegirl as moegirl_module,
    )

    def fake_moegirl_search(query: str, *, limit: int, timeout_seconds: float):
        assert query == "硬控"
        assert limit == 3
        return [
            SimpleNamespace(
                title="硬控",
                snippet="网络流行语，指……",
                url="https://zh.moegirl.org.cn/硬控",
                pageid=1,
            )
        ]

    monkeypatch.setattr(moegirl_module, "moegirl_search", fake_moegirl_search)
    results = acg_search.moegirl_lookup("硬控")
    assert len(results) == 1
    assert results[0].source == "moegirl"
    assert results[0].title == "硬控"


def test_moegirl_lookup_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.location.data import (
        moegirl as moegirl_module,
    )

    def boom(query: str, **kwargs: object):
        raise ParseHttpError("waf blocked")

    monkeypatch.setattr(moegirl_module, "moegirl_search", boom)
    with pytest.raises(ParseHttpError):
        acg_search.moegirl_lookup("硬控")


# ---------------------------------------------------------------------------
# B站竖源
# ---------------------------------------------------------------------------


def test_bilibili_search_parses_video_pubdate() -> None:
    def transport(url: str, **kwargs: object) -> dict:
        assert "search_type=video" in url
        assert kwargs.get("referer") == "https://www.bilibili.com/"
        return {
            "code": 0,
            "data": {
                "result": [
                    {
                        "title": "<em class=\"keyword\">芙莉莲</em> 第三季 PV",
                        "description": "新 PV 发布",
                        "pubdate": 1789449600,  # 2026-09-16（本地时区相关，仅断言有日期）
                        "author": "某UP",
                        "arcurl": "https://www.bilibili.com/video/BV1xx",
                    }
                ]
            },
        }

    results = acg_search.bilibili_search("芙莉莲", transport=transport)
    assert len(results) == 1
    hit = results[0]
    assert hit.title == "芙莉莲 第三季 PV"  # <em> 标签已剥
    assert hit.date != ""  # pubdate 已转日期
    assert hit.extra == "UP主 某UP"
    assert hit.url == "https://www.bilibili.com/video/BV1xx"


def test_bilibili_search_blocked_code_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    # -412 风控（无 cookie 常见）：诚实降级为空。
    results = acg_search.bilibili_search(
        "x", transport=lambda url, **k: {"code": -412, "message": "请求被拦截"}
    )
    assert results == []
    assert acg_search.bilibili_search("x", transport=lambda url, **k: "not-a-dict") == []
    assert acg_search.bilibili_search("x", transport=lambda url, **k: {"code": 0}) == []


# ---------------------------------------------------------------------------
# 竖源并发编排：降级不阻断
# ---------------------------------------------------------------------------


def test_verticals_all_sources_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        acg_search,
        "bangumi_search",
        lambda q, **k: [acg_search.AcgResult("bangumi", "条目", "摘要", "u", "2026-08-01")],
    )
    monkeypatch.setattr(
        acg_search,
        "moegirl_lookup",
        lambda q, **k: [acg_search.AcgResult("moegirl", "萌百条", "释义", "u")],
    )
    monkeypatch.setattr(
        acg_search,
        "bilibili_search",
        lambda q, **k: [acg_search.AcgResult("bilibili", "视频", "简介", "u", "2026-09-10")],
    )
    intent = detect_acg_intent("芙莉莲第三季出了吗")
    results, errors = acg_search.search_acg_verticals("芙莉莲", intent)
    assert errors == []
    assert [r.source for r in results] == ["bangumi", "moegirl", "bilibili"]


def test_verticals_single_source_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(q: str, **k: object) -> list:
        raise ParseHttpError("waf")

    monkeypatch.setattr(acg_search, "bangumi_search", boom)
    monkeypatch.setattr(
        acg_search,
        "moegirl_lookup",
        lambda q, **k: [acg_search.AcgResult("moegirl", "萌百条", "释义", "u")],
    )
    monkeypatch.setattr(acg_search, "bilibili_search", lambda q, **k: [])
    intent = detect_acg_intent("芙莉莲")
    results, errors = acg_search.search_acg_verticals("芙莉莲", intent)
    assert [r.source for r in results] == ["moegirl"]
    assert errors == ["acg:bangumi:ParseHttpError"]


def test_verticals_disabled_sources_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(q: str, **k: object) -> list:
        raise AssertionError("disabled source must not be called")

    for name in ("bangumi_search", "moegirl_lookup", "bilibili_search"):
        monkeypatch.setattr(acg_search, name, unexpected)
    intent = detect_acg_intent("芙莉莲")
    results, errors = acg_search.search_acg_verticals(
        "芙莉莲",
        intent,
        enabled_sources={"bangumi": False, "moegirl": False, "bilibili": False},
    )
    assert results == []
    assert errors == []


def test_verticals_budget_timeout_records_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    def slow(q: str, **k: object) -> list:
        _time.sleep(0.8)
        return []

    monkeypatch.setattr(acg_search, "bangumi_search", slow)
    monkeypatch.setattr(
        acg_search,
        "moegirl_lookup",
        lambda q, **k: [acg_search.AcgResult("moegirl", "萌百条", "释义", "u")],
    )
    monkeypatch.setattr(acg_search, "bilibili_search", lambda q, **k: [])
    intent = detect_acg_intent("芙莉莲")
    results, errors = acg_search.search_acg_verticals(
        "芙莉莲", intent, max_total_seconds=0.15
    )
    assert [r.source for r in results] == ["moegirl"]
    assert "acg:timeout" in errors


def test_verticals_non_acg_intent_noop() -> None:
    intent = detect_acg_intent("今天天气怎么样")
    results, errors = acg_search.search_acg_verticals("天气", intent)
    assert (results, errors) == ([], [])


# ---------------------------------------------------------------------------
# 时效加权融合（纯函数）
# ---------------------------------------------------------------------------


def _acg(source: str, title: str, date_str: str = "") -> acg_search.AcgResult:
    return acg_search.AcgResult(source=source, title=title, snippet="摘要", url="u", date=date_str)


def test_fuse_latest_recency_boost() -> None:
    intent = detect_acg_intent("芙莉莲第三季出了吗")
    web = [WebSearchHit(title="旧网页", snippet="s", url="u", source_domain="example.com")]
    acg = [
        _acg("bangumi", "新条目", "2026-09-15"),  # ≤7 天 → 1.6
        _acg("bilibili", "中旧视频", "2026-08-20"),  # ≤30 天 → 1.3
        _acg("bilibili", "老视频", "2026-01-01"),  # 旧 → 0.8
    ]
    fused = acg_search.fuse_into_web_hits(intent, web, acg, today=TODAY)
    order = [hit.title for hit in fused]
    assert order.index("[Bangumi] 新条目") < order.index("[B站] 中旧视频")
    assert order.index("[B站] 中旧视频") < order.index("[B站] 老视频")
    assert order.index("[B站] 老视频") < order.index("旧网页")  # 0.8 > 0.7


def test_fuse_latest_unknown_date_annotated_and_downweighted() -> None:
    intent = detect_acg_intent("原神卡池")
    web = [WebSearchHit(title="w", snippet="s", url="u", source_domain="d")]
    acg = [_acg("moegirl", "无日期条目", "")]
    fused = acg_search.fuse_into_web_hits(intent, web, acg, today=TODAY)
    # 最新档无日期 ×0.7 与 web 同权 → 稳定序 web 在前（同等不优待）。
    assert [hit.title for hit in fused] == ["w", "[萌娘百科] 无日期条目"]
    # 最新档：来源与日期必须显式可见（日期未知也要如实标注）。
    assert "萌娘百科" in fused[1].snippet
    assert "日期未知" in fused[1].snippet


def test_fuse_latest_dated_beats_undated_web() -> None:
    intent = detect_acg_intent("原神卡池")
    web = [WebSearchHit(title="w", snippet="s", url="u", source_domain="d")]
    acg = [_acg("bilibili", "昨天的视频", "2026-09-16")]
    fused = acg_search.fuse_into_web_hits(intent, web, acg, today=TODAY)
    assert fused[0].title == "[B站] 昨天的视频"
    assert "（B站·2026-09-16）" in fused[0].snippet


def test_fuse_background_authority_order() -> None:
    intent = detect_acg_intent("芙莉莲的声优是谁")
    web = [WebSearchHit(title="w", snippet="s", url="u", source_domain="d")]
    acg = [
        _acg("bilibili", "b站", ""),
        _acg("bangumi", "bgm", ""),
        _acg("moegirl", "萌百", ""),
    ]
    fused = acg_search.fuse_into_web_hits(intent, web, acg, today=TODAY)
    titles = [hit.title for hit in fused]
    # 萌百(1.2) > Bangumi(1.1) > web(1.0, 先传序在前) == B站(1.0, 稳定序随后)
    assert titles == ["[萌娘百科] 萌百", "[Bangumi] bgm", "w", "[B站] b站"]
    # 背景档未知日期不标「日期未知」（权威度优先，日期缺失不制造焦虑）。
    assert "日期未知" not in fused[0].snippet
    assert "（萌娘百科）" in fused[0].snippet


def test_parse_result_date() -> None:
    assert acg_search.parse_result_date("2026-07-05") == date(2026, 7, 5)
    assert acg_search.parse_result_date("2026-07-05T12:00:00") == date(2026, 7, 5)
    assert acg_search.parse_result_date("unknown") is None
    assert acg_search.parse_result_date("") is None


def test_timeliness_note_format() -> None:
    from datetime import datetime, timedelta, timezone

    note = acg_search.timeliness_section_note(
        datetime(2026, 9, 17, 21, 30, tzinfo=timezone(timedelta(hours=8)))
    )
    assert note == "检索截至 2026-09-17 21:30"


def test_honesty_line_constant() -> None:
    # 守岸人口径：不装新，过时就明说。
    assert "过时" in acg_search.TIMELINESS_HONESTY_LINE
    assert "来源" in acg_search.TIMELINESS_HONESTY_LINE


# ---------------------------------------------------------------------------
# chat 渲染面：_web_search_lines 时效口径（鸭子类型注入，避免重型夹具）
# ---------------------------------------------------------------------------


def test_web_search_lines_carries_timeliness_note() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
        chat as chat_module,
    )

    context = SimpleNamespace(
        web_search_context=SimpleNamespace(
            hits=[
                WebSearchHit(
                    title="[B站] 名场面",
                    snippet="（B站·2026-09-10）简介",
                    url="https://www.bilibili.com/video/BV1",
                    source_domain="bilibili.com",
                )
            ]
        )
    )
    rendered = chat_module._web_search_lines(context)  # type: ignore[arg-type]
    assert "检索截至" in rendered
    assert acg_search.TIMELINESS_HONESTY_LINE in rendered
    assert "[bilibili.com]" in rendered
    assert "[B站] 名场面" in rendered


def test_web_search_lines_no_hits_unchanged() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
        chat as chat_module,
    )

    context = SimpleNamespace(web_search_context=SimpleNamespace(hits=[]))
    rendered = chat_module._web_search_lines(context)  # type: ignore[arg-type]
    assert rendered == "- 本轮未按需联网检索现实时效信息"
