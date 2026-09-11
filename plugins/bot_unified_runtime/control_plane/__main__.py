"""独立启动入口：``python -m plugins.bot_unified_runtime.control_plane``。

总开关默认关；需 ``BOT_CONTROL_PLANE_ENABLED=true`` 才会真正监听。
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from . import serve

    return serve()


if __name__ == "__main__":
    sys.exit(main())
