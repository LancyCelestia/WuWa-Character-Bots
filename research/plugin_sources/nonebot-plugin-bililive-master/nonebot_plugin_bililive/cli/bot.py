import sys
from os import path

import nonebot
from nonebot import logger
from nonebot.adapters.onebot.v11 import Adapter
from nonebot.log import default_format

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(Adapter)
app = nonebot.get_asgi()

# 删除插件缓存导入，否则 nonebot 导入时会忽略
for module_name in (
    "nonebot_plugin_bililive",
    "bililive",
):
    sys.modules.pop(module_name, None)
nonebot.load_plugin("nonebot_plugin_bililive")

# Modify some config / config depends on loaded configs
#
# config = nonebot.get_driver().config
# do something...

logger.add(
    path.join("log", "error.log"),
    rotation="00:00",
    retention="1 week",
    diagnose=False,
    level="ERROR",
    format=default_format,
    encoding="utf-8",
)


def run():
    nonebot.run(app="nonebot_plugin_bililive.cli.bot:app")
