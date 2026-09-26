"""群资料进程内 TTL 缓存（bot.group_info 专用，审查 B-01/B-04 配套）。

OneBot V11/SnowLuma 的群 API（get_group_info / get_group_member_list /
get_group_notice / get_essence_msg_list）单次调用不便宜，而群资料/成员名单/
公告属于低频变化数据——同一群短时间内反复被问不该反复打协议。这里给一个
进程内、线程安全、按 (数据类, 群号) 键控的 TTL 缓存：

- 群资料 600s / 成员列表 900s / 公告 600s / 精华 600s（常量可调）；
- 只缓存**成功**的载荷：能力层对失败返回 None 时不落缓存（下次可重试，
  「接口失败」与「接口没数据」都不被旧值或失败态钉死）；
- 时钟可注入（默认 time.monotonic），TTL 过期语义可离线确定性测试；
- ttl<=0 视为「不缓存」（get 恒 miss，put 恒 no-op），便于关缓存排障。

只做缓存，不做协议调用、不持有 bot 引用——跨 loop 与测试环境安全。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

# TTL 常量（秒）：群资料/公告/精华 600s，成员列表 900s（任务书口径）。
PROFILE_TTL_SECONDS = 600.0
MEMBER_TTL_SECONDS = 900.0
NOTICE_TTL_SECONDS = 600.0
ESSENCE_TTL_SECONDS = 600.0
#: 群待办的 TTL **刻意比其余两类短**：待办是「刚由谁设了什么」这种强时效内容，
#: 沿用 600s 会让超管设完立刻问出来的那一句读到旧表——那已经不是缓存而是谎报。
TODO_TTL_SECONDS = 120.0
ALBUM_TTL_SECONDS = 600.0
#: 参与者读数的 TTL **刻意最短**：它读的是机器人自己的会话记忆，而记忆每轮都在长——
#: 刚说过话的人若 600s 内不出现在回答里，那已经不是缓存而是把人漏掉。
#: 底下是一次本地 SQLite 聚合（不是协议往返），缓存只为防同群反复问扫同一窗口，
#: 不值得为它牺牲新鲜度。
PARTICIPANT_TTL_SECONDS = 60.0

# 缓存数据类（kind 键）：群资料 / 成员列表 / 公告 / 精华。
KIND_PROFILE = "profile"
KIND_MEMBERS = "members"
KIND_NOTICE = "notice"
KIND_ESSENCE = "essence"
#: 群相册与群待办（第 4 项二批接线；动作名在册，见 group_info 模块 docstring）。
KIND_ALBUM = "album"
KIND_TODO = "todo"
#: 参与者（按记忆算的那条腿）：键是**作用域串**（群前缀或会话键），不是群号——
#: 私聊与群共用同一份读数件，用群号当键会把两个作用域混进同一条缓存。
KIND_PARTICIPANTS = "participants"
#: Telegram 侧专用几类（与 KIND_MEMBERS 分开键：同一 group_id 下装的是不同载荷，
#: 混用会让「成员名单」与「我自己的那一行」互相覆盖）。
KIND_MEMBER_COUNT = "member_count"
KIND_SELF_MEMBER = "self_member"
#: Telegram 群主与管理员（``get_chat_administrators`` 回的是 ChatMember 列表，
#: 与 QQ 侧 get_group_member_list 的全量成员表**形态不同**，也必须分键——
#: 混进 KIND_MEMBERS 会让两协议的载荷在同一键位下互相冒充）。
KIND_ADMINS = "tg_admins"
#: Telegram 私聊对端资料（``get_chat`` 在私聊里回的是对方的 ChatFullInfo：
#: 昵称/签名 bio），与群作用的 KIND_PROFILE 同动作不同载荷，必须分键。
KIND_PEER_PROFILE = "tg_peer_profile"

_DEFAULT_TTL_BY_KIND: dict[str, float] = {
    KIND_PROFILE: PROFILE_TTL_SECONDS,
    KIND_MEMBERS: MEMBER_TTL_SECONDS,
    KIND_NOTICE: NOTICE_TTL_SECONDS,
    KIND_ESSENCE: ESSENCE_TTL_SECONDS,
    KIND_ALBUM: ALBUM_TTL_SECONDS,
    KIND_TODO: TODO_TTL_SECONDS,
    KIND_PARTICIPANTS: PARTICIPANT_TTL_SECONDS,
    # 未登记 kind 的缺省 TTL 是 0（= 永不缓存），所以新类别必须在这里落一行。
    KIND_MEMBER_COUNT: MEMBER_TTL_SECONDS,
    KIND_SELF_MEMBER: MEMBER_TTL_SECONDS,
    # 管理员变动比资料更慢频（900s 与成员表同档）；私聊对端资料 600s 与群资料同档。
    KIND_ADMINS: MEMBER_TTL_SECONDS,
    KIND_PEER_PROFILE: PROFILE_TTL_SECONDS,
}

# 条目上限（防异常群号风暴撑爆进程内存；超限丢最旧条目）。
DEFAULT_MAX_ENTRIES = 512


class GroupInfoCache:
    """按 (kind, group_id) 键控的进程内 TTL 缓存（线程安全）。

    ``clock`` 可注入用于离线测试 TTL 过期；生产默认 time.monotonic
    （单调钟不受系统改钟影响，与 base_router 路由缓存同口径）。
    """

    def __init__(
        self,
        *,
        ttl_by_kind: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._ttl = dict(_DEFAULT_TTL_BY_KIND)
        if ttl_by_kind:
            self._ttl.update({str(k): float(v) for k, v in ttl_by_kind.items()})
        self._clock = clock
        self._max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()
        # key -> (stored_at, value)；dict 插入序即「最旧在前」。
        self._entries: dict[tuple[str, str], tuple[float, Any]] = {}

    def get(self, kind: str, group_id: str) -> tuple[bool, Any]:
        """命中且未过 TTL 返回 (True, value)；否则 (False, None)。"""
        key = (str(kind), str(group_id))
        ttl = self._ttl.get(str(kind), 0.0)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False, None
            stored_at, value = entry
            if ttl <= 0 or now - stored_at >= ttl:
                # 过期即弃：惰性删除，等下次 put 覆盖。
                self._entries.pop(key, None)
                return False, None
            return True, value

    def put(self, kind: str, group_id: str, value: Any) -> None:
        """写入缓存；ttl<=0 的数据类为 no-op（不缓存语义）。"""
        if value is None:
            return  # 失败载荷绝不落缓存（诚实降级原则）。
        key = (str(kind), str(group_id))
        with self._lock:
            if self._ttl.get(str(kind), 0.0) <= 0:
                return
            if len(self._entries) >= self._max_entries:
                oldest = next(iter(self._entries), None)
                if oldest is not None:
                    self._entries.pop(oldest, None)
            self._entries.pop(key, None)  # 重写时保持插入序新鲜。
            self._entries[key] = (self._clock(), value)

    def clear(self) -> None:
        """清空全部缓存（测试与运维用）。"""
        with self._lock:
            self._entries.clear()
