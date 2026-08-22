
from pydantic import BaseModel, Json

from .user_profile import Info, UserProfile


class Picture(BaseModel):
    img_src: str
    img_height: int
    img_width: int


class Item(BaseModel):
    at_control: Json | str | None
    description: str | None
    upload_time: int | None
    content: str | None
    ctrl: Json | str | None
    pictures: str | list[Picture] | None


class Vest(BaseModel):
    content: str


class APISeasonInfo(BaseModel):
    title: str | None
    type_name: str


class Card(BaseModel):
    item: Item | None
    dynamic: str | None
    pic: str | None
    title: str | None
    origin: Json | None
    image_urls: list | None
    summary: str | None
    vest: Vest | None
    origin_user: UserProfile | None

    duration: int | None

    user: Info | None
    owner: Info | None
    author: Info | None

    cover: str | None
    area_v2_name: str | None

    apiSeasonInfo: APISeasonInfo | None

    new_desc: str | None
