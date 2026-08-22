from pydantic import BaseModel, Field


class Config(BaseModel):
    """Plugin Config"""

    bili_query_check_interval_minutes: int = Field(default=5, ge=1)
    """订阅更新检查间隔（分钟）"""
