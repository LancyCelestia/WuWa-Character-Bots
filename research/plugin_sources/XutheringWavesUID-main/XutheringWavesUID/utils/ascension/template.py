import json

import aiofiles

from ..resource.RESOURCE_PATH import MAP_PATH

CHAR_TEMPLATE_PATH = MAP_PATH / "templata.json"


async def get_template_data():
    async with aiofiles.open(CHAR_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return json.loads(await f.read())
