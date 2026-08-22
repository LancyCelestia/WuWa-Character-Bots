"""parser 纯函数测试：UID / BV / URL / b23 短链解析"""
from nonebot_plugin_bili_query.parser import (
    parse_uid,
    parse_bv,
    parse_b23_url,
    parse_video_url,
)


class TestParseUid:
    def test_pure_number(self):
        assert parse_uid("123456") == "123456"

    def test_space_url(self):
        assert parse_uid("https://space.bilibili.com/123456") == "123456"
        assert parse_uid("空间 https://space.bilibili.com/946974 ") == "946974"

    def test_with_keyword(self):
        assert parse_uid("uid: 123456") == "123456"
        assert parse_uid("UP主123456") == "123456"

    def test_short_number_rejected(self):
        assert parse_uid("123") is None

    def test_garbage(self):
        assert parse_uid("hello world") is None


class TestParseBv:
    def test_pure_bv(self):
        assert parse_bv("BV1xx411c7mD") == "BV1xx411c7mD"

    def test_bv_in_url(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD?p=1"
        assert parse_bv(url) == "BV1xx411c7mD"

    def test_no_bv_returns_none(self):
        assert parse_bv("https://www.bilibili.com/video/av170001") is None
        assert parse_bv("看看这个视频") is None

    def test_b23_returns_none_not_whole_text(self):
        # 回归：b23.tv 短链时 parse_bv 不得返回整段文本（会导致短链解析分支不可达）
        text = "看看这个 https://b23.tv/AbCdEf 好活"
        assert parse_bv(text) is None


class TestParseB23Url:
    def test_extract_short_url(self):
        assert parse_b23_url("看看这个 https://b23.tv/AbCdEf 好活") == "https://b23.tv/AbCdEf"

    def test_extract_bare_short_url(self):
        assert parse_b23_url("b23.tv/AbCdEf") == "b23.tv/AbCdEf"

    def test_none(self):
        assert parse_b23_url("https://www.bilibili.com/video/BV1xx411c7mD") is None
        assert parse_b23_url("hello") is None


class TestParseVideoUrl:
    def test_video_url(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        assert parse_video_url(url) == url

    def test_none(self):
        assert parse_video_url("https://example.com") is None
