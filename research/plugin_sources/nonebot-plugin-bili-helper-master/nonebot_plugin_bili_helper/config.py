from typing import List, Literal
from pydantic import BaseModel, Field
from nonebot import get_plugin_config


class Config(BaseModel):
    """Plugin Config Here"""

    analysis_whitelist: list[str] = Field(default_factory=list)
    """B站解析用户白名单"""

    analysis_group_whitelist: list[str] = Field(default_factory=list)
    """B站解析群组白名单"""

    analysis_blacklist: list[str] = Field(default_factory=list)
    """B站解析用户黑名单"""

    analysis_group_blacklist: list[str] = Field(default_factory=list)
    """B站解析群组黑名单"""

    analysis_group_strategies: dict[str, List[
        Literal[
            "detail",
            "link",
            "comments",
        ]
    ]] = Field(default_factory=dict)
    """B站解析群组策略（detail、link、comments）"""

config = get_plugin_config(Config)
