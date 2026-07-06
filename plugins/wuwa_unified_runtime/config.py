from __future__ import annotations

from pydantic import BaseModel


class Config(BaseModel):
    wuwa_runtime_enabled: bool = True
    wuwa_runtime_default_persona: str = "default"
    wuwa_runtime_group_command_prefix: str = "/wuwa"
