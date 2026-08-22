from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot import require

require("nonebot_plugin_htmlrender")
require("nonebot_plugin_localstore")

from .config import Config
from .handlers import bili_helper

__plugin_meta__ = PluginMetadata(
    name="B站解析助手",
    description="主要功能：\n"
                "1. 提取分享小程序/图文卡片的视频链接\n"
                "2. 预览视频热评\n",
    usage="1. 分享B站小程序或图文卡片到群聊或私聊即可触发\n"
          "2. 管理员私聊发送“设置B站Cookie XXX”可设置请求的Cookie\n",
    config=Config,
    homepage="https://github.com/krimeshu/nonebot-plugin-bili-helper",
    type="application",
    supported_adapters={"~onebot.v11"},
)
