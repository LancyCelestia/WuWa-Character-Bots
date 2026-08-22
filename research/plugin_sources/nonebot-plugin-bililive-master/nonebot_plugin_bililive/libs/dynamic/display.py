
from pydantic import BaseModel, Json


class TopicDetail(BaseModel):
    topic_name: str
    is_activity: bool


class TopicInfo(BaseModel):
    topic_details: list[TopicDetail]


class EmojiDetail(BaseModel):
    emoji_name: str
    id: int
    text: str
    url: str


class EmojiInfo(BaseModel):
    """emoji 信息"""

    emoji_details: list[EmojiDetail]


class DescFirst(BaseModel):
    text: str


class ReserveAttachCard(BaseModel):
    title: str | None
    desc_first: str | DescFirst | None
    desc_second: str | None
    cover_url: str | None
    head_text: str | None


class AddOnCardInfo(BaseModel):
    add_on_card_show_type: int
    reserve_attach_card: ReserveAttachCard | None
    vote_card: Json | None
    attach_card: ReserveAttachCard | None


class Display(BaseModel):
    topic_info: TopicInfo | None
    emoji_info: EmojiInfo | None
    add_on_card_info: list[AddOnCardInfo] | None
    origin: dict | None
