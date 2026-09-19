"""Bot 本地头像（2026-09-13 用户指令）：NapCat 侧取到 bot QQ 后把头像
下载持久化到 Runtime data/avatar/，此后所有卡片按需取 file URI，不再因
BOT_PERSONA_AVATAR_URL 为空而回落"守"字圆点。

优先级：config.bot_persona_avatar_url 显式配置 > 本地缓存（内存登记；
内存为空时磁盘兜底发现 avatar/bot_*.png，F3 2026-09-14）> 空。
下载动作由连接钩子触发（__init__ on_bot_connect → refresh_from_qq）；
读取侧（F3）统一走 bot_avatar_uri——本地命中即 file URI，不再周期回源。
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCAL_AVATAR_URI: str = ""
_LOCK = threading.Lock()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShoreKeeperBot/1.0"

# 审查 L-14：头像文件缺失时每张卡都走 glob+stat 磁盘兜底探测——长跑进程
# 无谓重复。负结果（扫描确认缺失）按「解析后的 avatar 目录」键控 TTL 缓存：
# TTL 内直接回空不再探测，过期重探（期间目录里新出现的头像最多延迟 TTL
# 秒生效——观感链路可接受的取舍）。正结果语义零变化：命中即登记
# _LOCAL_AVATAR_URI，内存短路后续调用，天然不经过本缓存。
# 无界防说明（对齐 randpic L-10 先例的判据）：键空间=单一头像目录路径族，
# 生产恒为 config.bot_runtime_data_dir 单键，测试临时目录随 monkeypatch
# 丢弃——键数天然有界，无需 LRU 封顶。
_DISCOVER_MISS_TTL_SECONDS = 300.0
_DISCOVER_MISS_TS: dict[str, float] = {}
# 可注入时钟：测试 monkeypatch 此名推进时间，全离线不真睡。
_MONOTONIC = time.monotonic


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


def _discover_local_uri(config: object | None) -> str:
    """磁盘兜底（F3 2026-09-14）：avatar 目录挑最新的 bot_*.png 登记激活。

    覆盖「重启后 qlogo 拉取失败但上轮文件还在」的边角——文件存在即直接
    用 file URI，无需再回源。目录解析与写入侧（__init__._refresh_local_
    bot_avatar）同口径：config.bot_runtime_data_dir 绝对路径直用，相对路径
    挂工作区根；config 未提供该字段时放弃发现（保持测试/裸调用的确定性）。
    任何失败返回空串，绝不抛。

    审查 L-14：扫描确认缺失时记负结果 TTL 缓存（_DISCOVER_MISS_TS），
    TTL 内的重复调用跳过 glob+stat 直接回空，过期重探。
    """
    global _LOCAL_AVATAR_URI
    data_dir = ""
    if config is not None:
        data_dir = str(getattr(config, "bot_runtime_data_dir", "") or "").strip()
    if not data_dir:
        return ""
    try:
        root = Path(data_dir).expanduser()
        if not root.is_absolute():
            root = Path(__file__).resolve().parents[4] / root
        cache_key = str(root / "avatar")
        now = _MONOTONIC()
        with _LOCK:
            last_miss = _DISCOVER_MISS_TS.get(cache_key)
            miss_fresh = (
                last_miss is not None
                and now - last_miss <= _DISCOVER_MISS_TTL_SECONDS
            )
        if miss_fresh:
            return ""  # TTL 内已知缺失：不再 glob+stat（审查 L-14）
        candidates = sorted(
            (root / "avatar").glob("bot_*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                with _LOCK:
                    _LOCAL_AVATAR_URI = candidate.as_uri()
                    _DISCOVER_MISS_TS.pop(cache_key, None)  # 清陈旧负缓存
                return _LOCAL_AVATAR_URI
        with _LOCK:
            # 扫描确认缺失：记负结果，TTL 内同目录不再探测。
            _DISCOVER_MISS_TS[cache_key] = _MONOTONIC()
    except Exception:  # noqa: BLE001 - 磁盘兜底失败静默（观感降级非功能）。
        return ""
    return ""


def bot_avatar_uri(config: object | None = None) -> str:
    """卡片统一入口：显式配置 > 本地缓存（内存，缺失时磁盘兜底）> 空。"""
    configured = str(getattr(config, "bot_persona_avatar_url", "") or "").strip()
    if configured:
        return configured
    with _LOCK:
        uri = _LOCAL_AVATAR_URI
    return uri or _discover_local_uri(config)
