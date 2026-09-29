"""贴纸外发的**唯一取池喉**（S-STICKER-POOLS，2026-09-29）。

治的是「三条发贴纸腿各自去吸收池捞图」这条结构性缺陷：``_maybe_send_reaction_meme``
（P3 情绪时刻发图）、戳一戳的 ``meme`` 臂、``/偷表情`` 指令，此前全部经
``select_sticker_for_turn`` → ``MemeLibraryStore.weighted_pick``，也就是**同一盘
群聊吸收来的截图**。用户实弹点名的两件事因此同时成立不了——① 主动腿不该把别人
群里偷来的截图甩出去（P3 缺陷清单），② 管理员自己登记的贴纸包（红猪包一类）
在现网**一张都发不出来**（扫池腿 ``sticker_pool.py`` 已就位，发腿没接线）。

本件把「这一轮到底从哪个池子拿图」收成一个判据口，三条腿共用：

* :func:`pool_available` —— 池子在不在场（**开关的读点在 ``sticker_packs`` 自家**，
  本件不立第二判据口：关掉池子＝``list_sticker_images`` 交回空 ⇒ 本函数 False。
  在这里再读一遍 ``bot_sticker_enabled`` 就是第二真身，两枚开关会漂）；
* :func:`pick_from_packs` —— 拿一张（拿不到就是拿不到，**绝不回退吸收池**由调用方
  决定，见下面的 ``pool_policy``）；
* :func:`remember_pool` / :func:`last_pool_for` —— 按会话记「上一张来自哪个池」，
  这是审计轨（``/偷表情 pool`` 那一类的读数来源），不落盘、进程内有界；
* :func:`social_gates_allow` / :func:`sticker_feature_enabled` —— 主动外发前必须过
  的三道硬门（blocked 名单 / 安静时间 / ``bot.plugin.sticker_packs`` 特性开关）。

**缺席即诚实缺席**：``sticker_packs`` 件不在（未落盘、导入失败）时本件一律报
「池子不可用」，绝不假装挑到了一张、也绝不因此抛异常打断主链路。

全离线纯判定：不联网、不写库、不碰 ``ChatBot_Runtime``。
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ 池标识
#: 管理员登记的贴纸包（``sticker_packs`` 件的地盘）。
POOL_STICKER_PACKS = "sticker_packs"
#: 群聊吸收来的表情库（``MemeLibraryStore`` 的地盘，只在**指令路**允许兜底）。
POOL_MEME_LIBRARY = "meme_library"
#: 哪都没拿到（主动腿的正确结局＝不发）。
POOL_NONE = "none"

# -------------------------------------------------------------- 兜底方向（两态）
#: 只准用贴纸池：拿不到就**整条不发**，绝不回退吸收池（主动腿＝P3 与戳一戳发图）。
POOL_POLICY_PACKS_ONLY = "packs_only"
#: 先池后库：池子在场时从池子拿，池子拿空/不在场 ⇒ 回退既有表情库加权腿（指令路）。
POOL_POLICY_PACKS_THEN_LIBRARY = "packs_then_library"
POOL_POLICIES = (POOL_POLICY_PACKS_ONLY, POOL_POLICY_PACKS_THEN_LIBRARY)

#: 贴纸池的特性开关 id。**未登记 ⇒ ``enabled()`` 恒 False ⇒ 主动腿结构性不发**
#: （``runtime/feature_gate.py`` 对未知 id 的既有口径），所以登记前一律按「不开」算。
STICKER_PACKS_FEATURE_ID = "bot.plugin.sticker_packs"

#: 审计轨的会话上限（有界，防无界增长；超了先清最旧）。
_MAX_TRACKED_SESSIONS = 512

_LAST_POOL: OrderedDict[str, str] = OrderedDict()
_LAST_POOL_LOCK = threading.Lock()


def sticker_packs_module() -> Any | None:
    """懒引 ``sticker_packs`` 真身；引不到＝诚实缺席（返回 ``None``）。

    为什么懒引：本件被根装配与 ``domains/meme`` 两侧同时引，而 ``sticker_packs``
    是同期新件——顶层 import 会把「件还没落盘」变成整包导入失败（现网级事故）。
    """
    try:
        from . import sticker_packs
    except Exception:
        logger.debug("sticker_packs module unavailable", exc_info=True)
        return None
    return sticker_packs


def configured_sticker_dir(config: Any) -> Path | None:
    """登记的贴纸包目录（真身在 ``sticker_packs``）；没登记/件缺席 ⇒ ``None``。"""
    module = sticker_packs_module()
    if module is None or config is None:
        return None
    try:
        return module.configured_sticker_dir(config)
    except Exception:
        logger.debug("configured_sticker_dir failed", exc_info=True)
        return None


def list_pack_images(config: Any) -> list[Path]:
    """贴纸池当前候选（件缺席/读失败 ⇒ 空表，绝不抛）。"""
    module = sticker_packs_module()
    if module is None or config is None:
        return []
    try:
        return list(module.list_sticker_images(config) or [])
    except Exception:
        logger.debug("list_sticker_images failed", exc_info=True)
        return []


def pool_available(config: Any) -> bool:
    """贴纸池是否**真的**能拿出东西：件在场 ∧ 发送闸开 ∧ 目录里有候选。

    发送闸走 ``sticker_packs.sticker_send_enabled`` 那枚**自家读点**（本件绝不
    再去 ``getattr(config, "bot_sticker_enabled")``——同键两读＝两真身，会漂）。
    自家读点缺席时按「闸开着」算，只看清单：那样最坏是多问一次 ``pick_sticker``，
    而它自己第一行就把关了，不会误发。

    注意本函数**只是读数口**（给审计/文案答「池子在不在场」）：取图腿走
    :func:`pick_from_packs` 一次扫描就出结论，不在它前面再扫一遍目录。
    """
    module = sticker_packs_module()
    if module is None:
        return False
    checker = getattr(module, "sticker_send_enabled", None)
    if callable(checker):
        try:
            if not bool(checker(config)):
                return False
        except Exception:
            logger.debug("sticker_send_enabled probe failed", exc_info=True)
    return bool(list_pack_images(config))


def pool_verdict(config: Any) -> str:
    """降级原因代号（审计用；真身在 ``sticker_packs.StickerFacts.verdict``）。

    本件不自己拼第三套判据：能问真身就问真身，问不到（件缺席）才报 ``absent``。
    """
    module = sticker_packs_module()
    if module is None:
        return "module_absent"
    facts_fn = getattr(module, "sticker_facts", None)
    if not callable(facts_fn):
        return "unknown"
    try:
        facts = facts_fn(config)
        return str(getattr(facts, "verdict", "") or "unknown")
    except Exception:  # 探针不许炸：问不到真身就报 unknown。
        logger.debug("sticker_facts probe failed", exc_info=True)
        return "unknown"


def pick_from_packs(
    config: Any,
    *,
    session_key: str = "",
    seed: str = "",
    allow_exhausted: bool = True,
    persona_names: Any = (),
    prefer_tags: Any = (),
    locked_subdirs: Any = (),
) -> Path | None:
    """从贴纸池挑一张；挑不出＝``None``（**这里不做任何兜底**）。

    兜不兜底由调用方的 ``pool_policy`` 决定（见
    ``domains/meme/capabilities/meme_library.select_sticker_for_turn``）：主动腿
    ``packs_only`` 拿到 ``None`` 就整条不发，指令路才允许退回吸收池。把「回退」放
    在调用方而不是这里，是因为这两条腿的回退方向**相反**且都必须锁死。

    ``allow_exhausted``：整库都落在「窗内不重发」账里时怎么办——``True``（指令路，
    她开口要的东西不该拿「怕重复」当拒因）退最久没发那张；``False``（主动路）本轮
    不发。主动腿一律传 ``False``，判据真身在 ``sticker_packs.pick_sticker`` 那侧。

    ``persona_names`` / ``prefer_tags`` / ``locked_subdirs``：人格册名候选（只准
    从现役人格同名子目录取，缺册＝拿不到）、语境标签（命中子目录者排前）、锁定
    子目录（S4 好感档未解锁的 ``私藏`` 一类，整条剔除）——三枚都是透传，判据
    真身与缺省语义全在 ``sticker_packs.pick_sticker``，本件零自造。
    """
    module = sticker_packs_module()
    if module is None or config is None:
        return None
    try:
        picked = module.pick_sticker(
            config,
            session_key=str(session_key or ""),
            seed=str(seed or ""),
            allow_exhausted=bool(allow_exhausted),
            persona_names=tuple(persona_names or ()),
            prefer_tags=tuple(prefer_tags or ()),
            locked_subdirs=tuple(locked_subdirs or ()),
        )
    except TypeError:
        # 替身/旧签名不认新关键字 ⇒ 按简报给的调用形逐字重试一次；
        # 只对「签名不接受该关键字」回退，其余异常原样落到下面的 except。
        try:
            picked = module.pick_sticker(
                config,
                session_key=str(session_key or ""),
                seed=str(seed or ""),
                allow_exhausted=bool(allow_exhausted),
            )
        except Exception:
            logger.debug("pick_sticker failed", exc_info=True)
            return None
    except Exception:
        logger.debug("pick_sticker failed", exc_info=True)
        return None
    if picked is None:
        return None
    try:
        return Path(str(picked))
    except (TypeError, ValueError):  # 形如空气的路径当没拿到。
        return None


# ------------------------------------------------------------------ 审计轨
def remember_pool(session_key: str, pool: str) -> None:
    """按会话记「上一张贴纸来自哪个池」（进程内、有界；空会话键不记）。"""
    key = " ".join(str(session_key or "").split()).strip()
    if not key:
        return
    with _LAST_POOL_LOCK:
        _LAST_POOL[key] = str(pool or POOL_NONE)
        _LAST_POOL.move_to_end(key)
        while len(_LAST_POOL) > _MAX_TRACKED_SESSIONS:
            _LAST_POOL.popitem(last=False)


def last_pool_for(session_key: str) -> str:
    """该会话上一张的池标识；没记过 ⇒ ``none``（诚实缺席，不猜）。"""
    key = " ".join(str(session_key or "").split()).strip()
    if not key:
        return POOL_NONE
    with _LAST_POOL_LOCK:
        return _LAST_POOL.get(key, POOL_NONE)


def pool_audit_tag(pool: str) -> str:
    """池标识 → 审计标签（进 ``audit_tags``，不进用户可见文案）。"""
    return f"sticker_pool:{pool or POOL_NONE}"


def reset_pool_audit() -> None:
    """清空审计轨（测试用；生产不调）。"""
    with _LAST_POOL_LOCK:
        _LAST_POOL.clear()


# ------------------------------------------------------------------ 三道硬门
def sticker_feature_enabled(feature_enabled: Callable[[str], bool] | None) -> bool:
    """``bot.plugin.sticker_packs`` 特性门。**没给查询口＝按不通过算**（fail-closed）。

    为什么不在这里自造一个「拿快照」的读法：快照的生死权在装配层（``switches``
    每条消息取一次），本件只吃注入的判定函数——第二份取快照的路子就是第二真身。
    """
    if feature_enabled is None:
        return False
    try:
        return bool(feature_enabled(STICKER_PACKS_FEATURE_ID))
    except Exception:  # 没快照=按不通过，宁可少发。
        logger.debug("feature_enabled probe failed", exc_info=True)
        return False


def social_gates_allow(config: Any, *, group_id: str = "", user_id: str = "") -> bool:
    """blocked 名单 + 安静时间（判据真身在 ``capabilities/poke.py``，本件零重写）。

    与 ``proactive_action_allowed`` 的分工：那一枚是「开关→有目标→名单→窗→五层
    门」的**带提交**组合（``gate.allow`` 返回 True 就同时记冷却/滑窗/去重），主动
    腿该用它；本函数是**无副作用**的两道名单门，给「过不了就退回纯文本、不写任何
    门账」的腿（戳一戳发表情包）用。两者共用同一把尺，不是两套判据。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
        is_blocked_target,
        quiet_hours_active,
    )

    target = str(user_id or "").strip()
    if config is None or not target:
        return False
    if is_blocked_target(config, target):
        return False
    return not quiet_hours_active(
        config, session_scope="group" if str(group_id or "").strip() else "private"
    )


__all__ = [
    "POOL_MEME_LIBRARY",
    "POOL_NONE",
    "POOL_POLICIES",
    "POOL_POLICY_PACKS_ONLY",
    "POOL_POLICY_PACKS_THEN_LIBRARY",
    "POOL_STICKER_PACKS",
    "STICKER_PACKS_FEATURE_ID",
    "configured_sticker_dir",
    "last_pool_for",
    "list_pack_images",
    "pick_from_packs",
    "pool_audit_tag",
    "pool_available",
    "pool_verdict",
    "remember_pool",
    "reset_pool_audit",
    "social_gates_allow",
    "sticker_feature_enabled",
    "sticker_packs_module",
]
