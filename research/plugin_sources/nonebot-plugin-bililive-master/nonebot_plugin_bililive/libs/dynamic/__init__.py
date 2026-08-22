from nonebot.adapters.onebot.v11.message import Message, MessageSegment
from pydantic import BaseModel, model_validator

# from pydantic import Json
from .desc import Desc

# from .card import Card
# from .display import Display


class Dynamic(BaseModel):
    desc: Desc
    # card: Json[Card]  # type: ignore
    # extend_json: Json[Dict] # 不知道干什么的
    # display: Display

    type: int = 0
    id: int = 0
    url: str = ""
    time: int = 0
    uid: int = 0
    name: str = ""
    message: Message | None

    @model_validator(mode="after")
    def set_args(self):
        self.type = self.desc.type
        self.id = self.desc.dynamic_id
        self.url = f"https://t.bilibili.com/{self.id}"
        self.time = self.desc.timestamp
        self.uid = self.desc.user_profile.info.uid
        self.name = self.desc.user_profile.info.uname
        return self

    async def format(self, img):
        type_msg = {
            0: "发布了新动态",
            1: "转发了一条动态",
            8: "发布了新投稿",
            16: "发布了短视频",
            64: "发布了新专栏",
            256: "发布了新音频",
        }
        self.message = (
            f"{self.name} "
            + f"{type_msg.get(self.type, type_msg[0])}：\n"
            + f"{self.url}\n"
            + MessageSegment.image(f"base64://{img}")
        )
