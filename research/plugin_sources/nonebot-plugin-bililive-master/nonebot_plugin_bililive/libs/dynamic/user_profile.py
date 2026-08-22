
from pydantic import BaseModel


class Info(BaseModel):
    """用户信息"""

    uid: int | None
    uname: str | None
    face: str | None
    head_url: str | None
    name: str | None


class LevelInfo(BaseModel):
    """等级信息"""

    current_level: int | None


class Pendant(BaseModel):
    """挂件"""

    pid: int
    name: str
    image: str


class OfficialVerify(BaseModel):
    """账号认证信息"""

    type: int
    desc: str


class Card(BaseModel):
    official_verify: OfficialVerify


class VIP(BaseModel):
    """大会员信息"""

    vipType: int
    nickname_color: str


class UserProfile(BaseModel):
    info: Info
    level_info: LevelInfo | None
    pendant: Pendant | None
    card: Card | None
    vip: VIP | None
