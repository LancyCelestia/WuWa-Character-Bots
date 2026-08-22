"""allcpp（无差别同人站）活动详情深度解析测试。

活动页为服务端渲染，解析只读取 HTML 内嵌变量；HTTP 工具一律用
monkeypatch 替换，测试绝不发真实网络请求。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.sources.parsers import platforms_allcpp
from plugins.bot_unified_runtime.sources.parsers.http_util import ParseHttpError

EVENT_URL = "https://www.allcpp.cn/allcpp/event/event.do?event=6733"
_HTTP_GET_TEXT = "plugins.bot_unified_runtime.sources.parsers.platforms_allcpp.http_get_text"

# 2026-08-22 实测活动页 HTML 内嵌变量的真实片段（无关内容已删减）。
EVENT_HTML = """<html><body><script>
var worksObjId=6733;
var WORKSOBJNAME="星尘·广州JOJO FESTA2026";
var EVENTUSERID=1136855;
eventParam.EID=6733;
eventParam.picUrl="https://imagecdn3.allcpp.cn/upload/2026/4/e292ba03-edff-4c71-9413-33d22685c279.png";//活动封面图
eventParam.enterAddress="西槎路31号西城智汇PARK路演中心1F（鹅掌坦地铁站附近）";//活动地址
eventParam.eventName="星尘·广州JOJO FESTA2026";//活动名字
eventParam.lastDays=1;//距离天数
eventParam.sDate="2026-08-23";//开始时间
eventParam.eDate="2026-08-23";//结束时间
eventParam.eventTag = "JOJO的奇妙冒险|JOJO|JOJOONLY|...|迪奥";//tag
eventParam.desContent ="";//简介
eventParam.isOnly=1;//是否独家 0不是 1是
eventParam.eventType=3;//活动类型
</script></body></html>"""

# sDate / eDate / desContent 均为空串的变体。
EVENT_HTML_WITHOUT_DATES_DESC = """<html><body><script>
var worksObjId=6733;
var WORKSOBJNAME="星尘·广州JOJO FESTA2026";
var EVENTUSERID=1136855;
eventParam.EID=6733;
eventParam.picUrl="https://imagecdn3.allcpp.cn/upload/2026/4/e292ba03-edff-4c71-9413-33d22685c279.png";//活动封面图
eventParam.enterAddress="西槎路31号西城智汇PARK路演中心1F（鹅掌坦地铁站附近）";//活动地址
eventParam.eventName="星尘·广州JOJO FESTA2026";//活动名字
eventParam.lastDays=1;//距离天数
eventParam.sDate="";//开始时间
eventParam.eDate="";//结束时间
eventParam.eventTag = "JOJO的奇妙冒险|JOJO|JOJOONLY|...|迪奥";//tag
eventParam.desContent ="";//简介
eventParam.isOnly=1;//是否独家 0不是 1是
eventParam.eventType=3;//活动类型
</script></body></html>"""


def _stub_http(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    """把模块级 http_get_text 替换为返回内联 HTML 的桩，杜绝真实网络请求。"""
    monkeypatch.setattr(_HTTP_GET_TEXT, lambda url, **kwargs: (url, html))


def test_parse_allcpp_event_extracts_ssr_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(monkeypatch, EVENT_HTML)

    item = platforms_allcpp.parse_allcpp(EVENT_URL)

    assert item.platform == "allcpp"
    assert item.item_kind == "event"
    assert item.item_id == "6733"
    assert item.title == "星尘·广州JOJO FESTA2026"
    assert item.author_name == ""
    assert item.cover_url.startswith("https://imagecdn3.allcpp.cn/upload/")
    assert item.canonical_url == EVENT_URL
    assert item.parse_depth == "deep"
    assert "2026-08-23" in item.summary
    assert "西槎路31号" in item.summary
    assert "ONLY展" in item.summary
    assert "独家活动" in item.summary
    assert "JOJO的奇妙冒险" in item.summary
    assert item.stats == {"距离开始": "1 天"}


def test_parse_allcpp_event_without_dates_and_descontent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_http(monkeypatch, EVENT_HTML_WITHOUT_DATES_DESC)

    item = platforms_allcpp.parse_allcpp(EVENT_URL)

    assert "时间：" not in item.summary
    assert "简介：" not in item.summary
    assert item.title == "星尘·广州JOJO FESTA2026"
    assert "ONLY展" in item.summary


def test_parse_allcpp_missing_event_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_fast(*args: object, **kwargs: object) -> tuple[str, str]:
        raise AssertionError("event id 缺失时应直接报错，不应发起 HTTP 请求")

    monkeypatch.setattr(_HTTP_GET_TEXT, fail_fast)

    with pytest.raises(ParseHttpError):
        platforms_allcpp.parse_allcpp("https://www.allcpp.cn/allcpp/index.do")


def test_parse_allcpp_page_without_event_data_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_http(monkeypatch, "<html><body>没有 eventParam 的普通页面</body></html>")

    with pytest.raises(ParseHttpError):
        platforms_allcpp.parse_allcpp(EVENT_URL)


def test_parse_allcpp_http_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(*args: object, **kwargs: object) -> tuple[str, str]:
        raise ParseHttpError("allcpp page unavailable")

    monkeypatch.setattr(_HTTP_GET_TEXT, raise_http_error)

    with pytest.raises(ParseHttpError):
        platforms_allcpp.parse_allcpp(EVENT_URL)