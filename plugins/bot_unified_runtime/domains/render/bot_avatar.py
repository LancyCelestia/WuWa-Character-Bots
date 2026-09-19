"""Bot 本地头像与多实例身份（2026-09-13 用户指令；2026-09-20 AVT1 扩多实例）。

SnowLuma 侧取到 bot QQ 后把头像下载持久化到 Runtime data/avatar/，此后所有
卡片按需取 URI，不再因 BOT_PERSONA_AVATAR_URL 为空而回落"守"字圆点。

单实例（``bot_id`` 省略）优先级：config.bot_persona_avatar_url 显式配置 >
本地缓存（内存登记；内存为空时磁盘兜底发现 avatar/bot_*.png，F3 2026-09-14）
> 空。下载动作由连接钩子触发（__init__ on_bot_connect → refresh_from_qq）；
读取侧（F3）统一走 bot_avatar_uri——本地命中即用，不再周期回源。

多实例（AVT1 2026-09-20 用户裁定「做成多 bot 身份自动取」）：一台机器上
可以并存多个发送方（主号 / 校园号 2300230562 / 推送号 3958874605 …），每张
卡上的**名字与头像必须随实际发送方变化**，不得写死。落点=本模块的
``bot_identity(bot_id, config)``：头像按 ``avatar/bot_<qq>.png`` 既有命名逐实例
取（``refresh_from_qq`` 本就以 bot_id 命名落盘，天然按实例隔离），名字走
「显式登记 → 装配层解析器 → 人格配置名 → 空（由胶囊回落品牌名）」四级。
注册表与既有单实例槽位并存且**互不干扰**：``bot_id`` 为空的路径行为与今天
逐字节一致（tests/test_bot_avatar.py 锁定的三个进程级全局语义不变）。

新增配置键＝零（本波纪律）。第二实例的**名字**目前没有任何既有 config 键
可承载（``bot_persona_display_name`` 是单值人格名），故只提供登记入口
``register_identity`` 与装配层钩子 ``set_identity_resolver``，并登记为待裁点
（见 docs/design/unify-audit-20260919/AVT1-impl.md §七）。
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BotIdentity:
    """单实例身份值对象。两侧空串各归各的回落：名字空 → 胶囊回落品牌名
    （``BRAND_THEME.display_name``），头像空 → 胶囊回落首字圆点。"""

    name: str = ""
    avatar_uri: str = ""


# AVT1 多实例槽位（进程级，与 _LOCAL_AVATAR_URI 单实例槽位互不污染）：
# 显式登记表 + 装配层解析器。_LOCK 下存取；解析器**绝不持锁调用**
# （它可能反读本模块读取面，threading.Lock 非重入，持锁回调=自杀）。
_IDENTITY_REGISTRY: dict[str, BotIdentity] = {}
_IDENTITY_RESOLVER: Callable[[str, object], str | None] | None = None


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


def _data_root(config: object | None) -> Path | None:
    """data 目录绝对根（AVT1 自 _discover_local_uri 原样提级，口径零改动）：
    config.bot_runtime_data_dir 绝对路径直用，相对路径挂工作区根；
    未提供该字段返回 None（保持测试/裸调用的确定性）。"""
    data_dir = (
        "" if config is None
        else str(getattr(config, "bot_runtime_data_dir", "") or "").strip()
    )
    if not data_dir:
        return None
    root = Path(data_dir).expanduser()
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[4] / root
    return root


def _discover_local_uri(config: object | None) -> str:
    """磁盘兜底（F3 2026-09-14）：avatar 目录挑最新的 bot_*.png 登记激活。

    覆盖「重启后 qlogo 拉取失败但上轮文件还在」的边角——文件存在即直接
    用 file URI，无需再回源。目录解析（AVT1 提级为 _data_root）与写入侧
    （__init__._refresh_local_bot_avatar）同口径：config 未提供该字段时
    放弃发现（保持测试/裸调用的确定性）。任何失败返回空串，绝不抛。

    审查 L-14：扫描确认缺失时记负结果 TTL 缓存（_DISCOVER_MISS_TS），
    TTL 内的重复调用跳过 glob+stat 直接回空，过期重探。
    """
    global _LOCAL_AVATAR_URI
    root = _data_root(config)
    if root is None:
        return ""
    try:
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


# --- AVT1 多实例身份（2026-09-20 用户裁定「做成多 bot 身份自动取」） -------


def register_identity(bot_id: str, *, name: str = "", avatar_uri: str = "") -> None:
    """显式登记实例身份（名字链第一级 + 头像链第一级）。

    - 空白 bot_id 拒绝入库（空键=单实例路径，绝不允许被登记面污染）；
    - **整条替换**：再次登记未带字段即清空旧值，不做隐式继承——登记面
      状态单调用可推（tests/test_bot_avatar.py ⑤ 语义锁）；
    - 字段空串=该字段不表态，解析时顺延下一级。
    """
    key = str(bot_id or "").strip()
    if not key:
        return
    with _LOCK:
        _IDENTITY_REGISTRY[key] = BotIdentity(
            name=str(name or "").strip(), avatar_uri=str(avatar_uri or "").strip()
        )


def set_identity_resolver(
    resolver: Callable[[str, object], str | None] | None,
) -> None:
    """装配层挂名字解析器（名字链第二级）；传 None 摘除。

    生产接线建议（接入计划步骤三，见 AVT1-impl.md §五）：装配期注册一次，
    按 bot_id 查平台身份表（如 snowluma 平台登记/校园配置键归组），
    不识别的 bot_id 返回空串放行。
    """
    global _IDENTITY_RESOLVER
    with _LOCK:
        _IDENTITY_RESOLVER = resolver


def _persona_display_name(config: object | None) -> str:
    """名字链第三级：人格配置中文名（config.py:150，实例可配面貌字段）。"""
    return str(getattr(config, "bot_persona_display_name", "") or "").strip()


def _per_instance_avatar_uri(bot_id: str, config: object | None) -> str:
    """头像链第二级：``avatar/bot_<qq>.png`` 逐实例直取（AVT1）。

    refresh_from_qq 本就以该命名落盘，逐实例天然隔离；纯数字 QQ 号 +
    文件存在且非空才命中（0 字节视同缺失，对齐 _discover_local_uri 口径）。
    不加负结果 TTL：单次 is_file+stat 远廉于整目录 glob+stat（审查 L-14
    的成本前提不成立），每卡重探代价可忽略。任何失败返回空串，绝不抛。
    """
    qq = str(bot_id or "").strip()
    if not qq.isdecimal():  # 非 QQ 形态（tg:xx 等）无落盘命名约定，跳过
        return ""
    root = _data_root(config)
    if root is None:
        return ""
    try:
        candidate = root / "avatar" / f"bot_{qq}.png"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate.as_uri()
    except Exception:  # noqa: BLE001 - 观感降级非功能。
        return ""
    return ""


def bot_identity(bot_id: str = "", config: object | None = None) -> BotIdentity:
    """卡面身份统一入口：按实际发送方解析中文名与头像（AVT1 单一落点）。

    - ``bot_id`` 为空（含纯空白）＝单实例旧口径：头像**逐字节等于**
      ``bot_avatar_uri(config)``，名字=人格配置名；注册表、解析器、逐实例
      磁盘探测一律不经过（回归锁 tests/test_bot_avatar.py ①）。
    - 非空 ``bot_id``：名字「显式登记 → 装配层解析器 → 人格配置名 → 空
      （胶囊回落品牌名）」四级；头像「登记 → ``avatar/bot_<qq>.png`` →
      旧全局链」三级。末级回落到全局链=「不比今天差」原则：接入前所有卡
      本就共用同一枚头像/品牌名，逐实例信息缺失时维持该观感，绝不塌陷。
    - 解析器不持锁调用（可安全反读本模块读取面）、抛异常 fail-safe 落
      下一级；本函数任何输入都不抛（头像/名字只关观感，不炸渲染链路）。
    """
    key = str(bot_id or "").strip()
    if not key:
        return BotIdentity(
            name=_persona_display_name(config),
            avatar_uri=bot_avatar_uri(config),
        )
    with _LOCK:
        entry = _IDENTITY_REGISTRY.get(key)
        resolver = _IDENTITY_RESOLVER
    registered = entry if entry is not None else BotIdentity()
    name = registered.name
    if not name and resolver is not None:
        try:
            name = str(resolver(key, config) or "").strip()
        except Exception:  # 解析器炸了不塌卡面：fail-safe 顺延人格配置名。
            logger.debug(
                "bot identity resolver failed bot_id=%s***", key[-2:], exc_info=True
            )
            name = ""
    if not name:
        name = _persona_display_name(config)
    avatar = (
        registered.avatar_uri
        or _per_instance_avatar_uri(key, config)
        or bot_avatar_uri(config)
    )
    return BotIdentity(name=name, avatar_uri=avatar)
