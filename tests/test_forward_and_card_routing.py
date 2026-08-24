"""卡片/HTML 链接与合并转发读取辅助函数测试。"""


from plugins.bot_unified_runtime import (
    _effective_route_text,
    _urls_from_message_segments,
)


class _FakeEvent:
    def __init__(self, text, segments):
        self.text = text
        self.segments = segments

    def get_plaintext(self):
        return self.text

    def get_message(self):
        return self.segments


def test_json_card_urls_are_extracted():
    segments = [
        {
            "type": "json",
            "data": {
                "data": '{"meta":{"detail":{"url":"https://www.bilibili.com/video/BV1xx"}}}'
            },
        }
    ]
    assert "https://www.bilibili.com/video/BV1xx" in _urls_from_message_segments(segments)


def test_effective_route_text_includes_card_url():
    event = _FakeEvent(
        "",
        [
            {
                "type": "json",
                "data": {"data": '{"url":"https://space.bilibili.com/3577566"}'},
            }
        ],
    )
    text = _effective_route_text(event)
    assert "https://space.bilibili.com/3577566" in text
