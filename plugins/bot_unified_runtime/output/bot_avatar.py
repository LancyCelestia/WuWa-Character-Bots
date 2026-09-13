"""Bot 本地头像（2026-09-13 用户指令）：NapCat 侧取到 bot QQ 后把头像
下载持久化到 Runtime data/avatar/，此后所有卡片按需取 file URI，不再因
BOT_PERSONA_AVATAR_URL 为空而回落"守"字圆点。

优先级：config.bot_persona_avatar_url 显式配置 > 本地缓存文件 > 空。
下载动作由连接钩子触发（__init__ on_bot_connect → refresh_from_qq）。
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCAL_AVATAR_URI: str = ""
_LOCK = threading.Lock()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShoreKeeperBot/1.0"


def avatar_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "avatar"


def refresh_from_qq(bot_id: str, data_dir: str | Path, *, timeout: float = 8.0) -> str:
    """从 qlogo 下载 bot 头像落本地并激活；返回 file URI（失败返回 ""）。

    任意失败都不抛——头像缺失只影响观感，绝不能影响卡片渲染链路。
    """
    global _LOCAL_AVATAR_URI
    qq = str(bot_id or "").strip()
    if not qq.isdecimal():
        return ""
    target_dir = avatar_dir(data_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"bot_{qq}.png"
        request = urllib.request.Request(
            f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640",
            headers={"User-Agent": _UA},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(8 * 1024 * 1024)
        if not payload.startswith(b"\x89PNG"):
            return ""
        target.write_bytes(payload)
        with _LOCK:
            _LOCAL_AVATAR_URI = target.as_uri()
        return _LOCAL_AVATAR_URI
    except Exception:  # noqa: BLE001 - 头像下载失败静默（观感降级非功能）。
        logger.debug("bot avatar download failed qq=%s***", qq[-2:])
        return ""


def set_local_path(path: str | Path) -> None:
    """测试/外部注入：直接登记本地头像文件。"""
    global _LOCAL_AVATAR_URI
    candidate = Path(path)
    if candidate.is_file():
        with _LOCK:
            _LOCAL_AVATAR_URI = candidate.as_uri()


def bot_avatar_uri(config: object | None = None) -> str:
    """卡片统一入口：显式配置 > 本地缓存 > 空（调用方自行回落圆点）。"""
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        return configured
    with _LOCK:
        return _LOCAL_AVATAR_URI
