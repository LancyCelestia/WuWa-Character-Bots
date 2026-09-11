"""统一戳一戳（poke）reaction 分发；适配器中立，独立实现。

所有适配器（OneBot / 未来 mail、telegram 等）把各自的通知事件归一成
``PokeEvent``（或任意带同名属性的普通对象）后，统一调
``PokeDispatcher.build_poke_reaction`` 拿到 ``PokeReaction``：

- 回戳（``bot_poke_poke_back``，默认关）：由适配器按平台 API 执行，
  分发器只给出意图；
- 话术（``bot_poke_group_text`` / ``bot_poke_private_text``，空=内置默认）；
- 冷却/概率/开关（既有 bot_poke_* 配置，语义不变）。

分发器不导入 NoneBot，可离线单测。
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# 戳一戳冷却登记 LRU 上限：防群/会话数增长导致 _last 慢泄漏（审计 #30）。
_POKE_LAST_CAP = 4096


@dataclass
class PokeLimiter:
    clock: Callable[[], float]
    _last: OrderedDict[tuple[str, str], float] = field(default_factory=OrderedDict)
    def accept(self, event: Any, bot_id: str, enabled: bool, cooldown: float, group_cooldown: float, probability: float = 1.0) -> bool:
        if not enabled or str(getattr(event, "target_id", "")) != str(bot_id): return False
        import hashlib
        group = str(getattr(event, "group_id", "") or "private")
        sender = str(getattr(event, "user_id", "") or "unknown")
        now = self.clock()
        if now - self._last.get((group, sender), -1e9) < max(0.0, cooldown): return False
        if now - self._last.get((group, "*"), -1e9) < max(0.0, group_cooldown): return False
        if probability < 1.0:
            digest = int(hashlib.sha256(f"{group}:{sender}:{int(now // max(1.0, group_cooldown))}".encode()).hexdigest()[:8],16) / 0xFFFFFFFF
            if digest > probability: return False
        for key in ((group, sender), (group, "*")):
            self._last[key] = now
            self._last.move_to_end(key)
        while len(self._last) > _POKE_LAST_CAP:
            self._last.popitem(last=False)
        return True


def build_poke_text(*, group: bool, nickname: str = "") -> str:
    if group:
        return f"{nickname}，我收到你的轻轻一碰了。岸边的潮声还在，不必一直戳我。"
    return "我收到你的轻轻一碰了。嗯，我在这里。"


# ------------------------------------------------------------- 统一分发入口


@dataclass(frozen=True)
class PokeEvent:
    """适配器中立的通知事件：各适配器把自己的 notice 归一成它。"""

    target_id: str = ""
    user_id: str = ""
    group_id: str = ""  # 空=私聊
    sub_type: str = "poke"

    @classmethod
    def from_notice(cls, event: Any, bot_id: str = "") -> PokeEvent | None:
        """把 OneBot 风格 notice 事件归一成 PokeEvent；非 poke 通知返回 None。

        接受任意带同名属性的对象（NoneBot Event、SimpleNamespace 均可），
        便于未来其他适配器零成本复用。
        """
        notice_type = str(getattr(event, "notice_type", "") or "")
        sub_type = str(getattr(event, "sub_type", "") or "")
        if notice_type and (notice_type != "notify" or sub_type != "poke"):
            return None
        if not notice_type and sub_type != "poke":
            return None
        target = str(getattr(event, "target_id", "") or "")
        user = str(getattr(event, "user_id", "") or "")
        group = str(getattr(event, "group_id", "") or "")
        if not target and bot_id:
            target = bot_id  # 私聊戳一戳部分协议端不带 target_id。
        return cls(target_id=target, user_id=user, group_id=group, sub_type=sub_type or "poke")


@dataclass(frozen=True)
class PokeReaction:
    """分发决定：适配器按字段执行（发话术 / 回戳），两者可同时成立。"""

    reply: str = ""
    poke_back: bool = False
    group: bool = False
    audit_tags: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.reply) or self.poke_back


class PokeDispatcher:
    """统一入口：开关/目标/冷却/概率门控 + 话术与回戳意图组装。"""

    def __init__(self, clock: Callable[[], float], limiter: PokeLimiter | None = None) -> None:
        self.clock = clock
        self.limiter = limiter if limiter is not None else PokeLimiter(clock=clock)

    @staticmethod
    def _knobs(config: Any) -> dict[str, Any]:
        return {
            "enabled": bool(getattr(config, "bot_poke_enabled", True)),
            "private_cooldown": float(getattr(config, "bot_poke_private_cooldown_seconds", 30.0)),
            "group_cooldown": float(getattr(config, "bot_poke_group_cooldown_seconds", 10.0)),
            "probability": float(getattr(config, "bot_poke_probability", 1.0)),
            "reply_enabled": bool(getattr(config, "bot_poke_reply_enabled", True)),
            "poke_back": bool(getattr(config, "bot_poke_poke_back", False)),
            "group_text": str(getattr(config, "bot_poke_group_text", "") or ""),
            "private_text": str(getattr(config, "bot_poke_private_text", "") or ""),
        }

    def build_poke_reaction(
        self,
        event: Any,
        *,
        bot_id: str,
        config: Any | None = None,
    ) -> PokeReaction | None:
        """唯一分发点。被抑制（关/非戳我/冷却/概率未中）返回 None。

        ``event`` 接受已归一的 ``PokeEvent``，也接受原始 OneBot notice
        对象（内部先 ``PokeEvent.from_notice`` 兜底归一）。
        """
        poke = event if isinstance(event, PokeEvent) else PokeEvent.from_notice(event, bot_id=str(bot_id))
        if poke is None:
            return None
        knobs = self._knobs(config)
        passthrough = SimplePokeView(poke)
        if not self.limiter.accept(
            passthrough,
            str(bot_id),
            knobs["enabled"],
            knobs["private_cooldown"],
            knobs["group_cooldown"],
            knobs["probability"],
        ):
            return None
        group = bool(poke.group_id)
        tags = ["poke", "poke_group" if group else "poke_private"]
        if knobs["poke_back"]:
            tags.append("poke_back")
        reply = ""
        if knobs["reply_enabled"]:
            reply = (knobs["group_text"] if group else knobs["private_text"]) or build_poke_text(
                group=group
            )
        return PokeReaction(reply=reply, poke_back=knobs["poke_back"], group=group, audit_tags=tuple(tags))


class SimplePokeView:
    """PokeEvent → PokeLimiter.accept 需要的属性视图（零拷贝）。"""

    __slots__ = ("group_id", "target_id", "user_id")

    def __init__(self, poke: PokeEvent) -> None:
        self.target_id = poke.target_id
        self.user_id = poke.user_id
        self.group_id = poke.group_id
