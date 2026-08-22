
from collections.abc import Mapping
from typing import Any

from nonebot import get_plugin_config, logger
from nonebot.compat import field_validator, model_validator
from pydantic import BaseModel


# 其他地方出现的类似 from .. import config，均是从 __init__.py 导入的 Config 实例
class Config(BaseModel):
    fastapi_reload: bool = False
    bililive_to_me: bool = True
    bililive_live_off_notify: bool = False
    bililive_proxy: str | None = None
    bililive_interval: int = 10
    bililive_live_interval: int = 10
    bililive_dynamic_interval: int = 0
    bililive_dynamic_at: bool = False
    bililive_screenshot_style: str = "mobile"
    bililive_captcha_address: str = "https://captcha-cd.ngworks.cn"
    bililive_captcha_token: str = "bililive"
    bililive_browser_ua: str | None = None
    bililive_chromium_endpoint: str | None = None
    bililive_dynamic_timeout: int = 30
    bililive_dynamic_font_source: str = "system"
    bililive_dynamic_font: str | None = "Noto Sans CJK SC"
    bililive_dynamic_big_image: bool = False
    bililive_command_prefix: str = ""

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_keys(cls, values: Any):
        if not isinstance(values, Mapping):
            return values

        data = dict(values)
        for legacy_key, new_key in {
            "haruka_to_me": "bililive_to_me",
            "haruka_live_off_notify": "bililive_live_off_notify",
            "haruka_proxy": "bililive_proxy",
            "haruka_interval": "bililive_interval",
            "haruka_live_interval": "bililive_live_interval",
            "haruka_dynamic_interval": "bililive_dynamic_interval",
            "haruka_dynamic_at": "bililive_dynamic_at",
            "haruka_screenshot_style": "bililive_screenshot_style",
            "haruka_captcha_address": "bililive_captcha_address",
            "haruka_captcha_token": "bililive_captcha_token",
            "haruka_browser_ua": "bililive_browser_ua",
            "haruka_chromium_endpoint": "bililive_chromium_endpoint",
            "haruka_dynamic_timeout": "bililive_dynamic_timeout",
            "haruka_dynamic_font_source": "bililive_dynamic_font_source",
            "haruka_dynamic_font": "bililive_dynamic_font",
            "haruka_dynamic_big_image": "bililive_dynamic_big_image",
            "haruka_command_prefix": "bililive_command_prefix",
        }.items():
            if new_key not in data and legacy_key in data:
                data[new_key] = data[legacy_key]

        return data

    @field_validator("bililive_interval")
    @classmethod
    def interval_non_negative(cls, value: int):
        return 10 if value < 1 else value

    @field_validator("bililive_live_interval")
    @classmethod
    def live_interval_non_negative(cls, value: int):
        return 10 if value < 1 else value

    @field_validator("bililive_dynamic_interval")
    @classmethod
    def dynamic_interval_non_negative(cls, value: int):
        return 0 if value < 1 else value

    @field_validator("bililive_chromium_endpoint")
    @classmethod
    def chromium_endpoint(cls, value: str | None):
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("bililive_screenshot_style")
    @classmethod
    def screenshot_style(cls, value: str):
        if value != "mobile":
            logger.warning("截图样式目前只支持 mobile，pc 样式现已被弃用")
        return "mobile"


plugin_config = get_plugin_config(Config)
