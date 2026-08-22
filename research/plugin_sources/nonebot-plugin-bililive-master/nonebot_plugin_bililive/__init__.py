from nonebot import require
from nonebot.plugin import PluginMetadata

from .config import Config, plugin_config
from .version import VERSION, __version__

require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")

from .utils import on_startup

on_startup()

from . import plugins  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="BiliLive",
    description="将B站UP主的动态和直播信息推送至QQ",
    usage="发送“帮助”查看命令列表，发送“关注 UID”订阅 UP 主",
    homepage="https://github.com/Akiyy-dev/nonebot-plugin-bililive",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "Akiyy_Lab",
        "version": __version__,
        "priority": 1,
    },
)

__all__ = ["__plugin_meta__", "__version__", "VERSION", "plugin_config"]
