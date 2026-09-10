"""全库重审计（2026-09-11）域内修复回归：人格/安全/能力层域。

覆盖本轮修复：
- 小名「叫我就好」语气词回溯成名字的拒绝（affinity.extract_learned_nickname）
- persona_set 概率权重归一化（总权重>1 时后面人格不再被截胡）
- content_safety 零宽字符黑名单扩充（U+2060 WORD JOINER / U+00AD 软连字符等）
- /bot status 管理员门（echo.build_status_result actor_roles）
- 订阅 v2：群内 add 需管理员；pause/resume/remove 按目的地粒度生效
"""

from __future__ import annotations

import random
import re
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.echo import build_status_result
from plugins.bot_unified_runtime.capabilities.subscribe_v2 import (
    build_subscribe_capability_v2,
)
from plugins.bot_unified_runtime.character.affinity import extract_learned_nickname
from plugins.bot_unified_runtime.character.persona_set import (
    AltPersonaSpec,
    PersonaSelector,
)
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
    SubscriptionDestinationV2,
)
from plugins.bot_unified_runtime.contracts.subscription import SubscriptionTarget
from plugins.bot_unified_runtime.security.content_safety import normalize_for_matching
from plugins.bot_unified_runtime.sources.subscription_store_v2 import (
    SubscriptionStoreV2,
)

# ---------------------------------------------------------------- 小名


def test_nickname_suffix_particle_not_learned() -> None:
    # 「叫我就好/叫我就行」无名字，非贪婪回溯曾把「就好/就行」当名字学进去。
    assert extract_learned_nickname("叫我就好") is None
    assert extract_learned_nickname("叫我就行") is None
    assert extract_learned_nickname("以后叫我就好") is None
    # 正常教名不受影响。
    assert extract_learned_nickname("叫我小岸就好") == "小岸"


# ---------------------------------------------------------------- 人格权重


def test_persona_probability_weights_normalized() -> None:
    specs = {
        "a": AltPersonaSpec(profile_id="a", display_name="甲", weight=0.6),
        "b": AltPersonaSpec(profile_id="b", display_name="乙", weight=0.6),
        "c": AltPersonaSpec(profile_id="c", display_name="丙", weight=0.6),
    }
    selector = PersonaSelector(specs)
    # 总权重 1.8：归一化后 draw=0.9 应落在第三人格（旧实现恒被前两个截胡）。
    picked = selector.select(rng=random.Random(0), weights={"a": 0.6, "b": 0.6, "c": 0.6})
    # 用确定采样验证可达性：draw∈(1.2,1.8] 区间必然命中 c。
    hits_c = 0
    for seed in range(200):
        if selector.select(rng=random.Random(seed), weights={"a": 0.6, "b": 0.6, "c": 0.6}) is specs["c"]:
            hits_c += 1
    assert hits_c > 0
    assert picked is not None


# ---------------------------------------------------------------- 零宽绕过


def test_zero_width_normalization_covers_word_joiner_and_soft_hyphen() -> None:
    for ch in ("\u2060", "\u00ad", "\u180e", "\u2063"):
        normalized = normalize_for_matching(f"色{ch}情")
        assert normalized == "色情", (hex(ord(ch)), normalized)


# ---------------------------------------------------------------- status 管理员门


def test_status_requires_admin() -> None:
    denied = build_status_result(request_id="r1", actor_roles=["user"])
    assert "管理员" in denied.body
    allowed = build_status_result(request_id="r1", actor_roles=["admin", "user"])
    assert "管理员" not in allowed.body
    # 未传角色（旧调用方）= 拒绝，避免任何漏传路径绕过门禁。
    legacy = build_status_result(request_id="r1")
    assert "管理员" in legacy.body


# ---------------------------------------------------------------- 订阅 v2 权限与目的地粒度


def _target(target_id: str) -> SubscriptionTarget:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return SubscriptionTarget(
        id=target_id,
        platform=target_id.split(":", 1)[0],
        target_kind="channel",
        target_key=target_id.rsplit(":", 1)[-1],
        base_interval_seconds=300,
        jitter_ratio=0.20,
        next_poll_at=now,
        created_at=now,
        updated_at=now,
        display_name="测试频道",
    )


def _group_message(text: str, *, group_id: str, sender_id: str, roles: list[str] | None = None) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"group:{group_id}",
        session_type=SessionType.GROUP,
        group_id=group_id,
        sender_id=sender_id,
        sender_roles=roles if roles is not None else ["user"],
        plain_text=text,
    )


class _ResolveAdapter:
    platform = "youtube"

    async def resolve_target(self, raw_target: str, ctx: dict):
        slug = re.sub(r"\W", "", raw_target)[:20]
        target = _target(f"youtube:channel:{slug}")
        return target


def test_subscribe_add_requires_group_admin(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    config = SimpleNamespace(bot_admin_user_ids=["999"])
    capability = build_subscribe_capability_v2(store=store, adapters=[_ResolveAdapter()], config=config)

    denied = capability(
        _group_message("订阅 add https://youtube.com/@demo", group_id="g1", sender_id="111"),
        None,
    )
    assert "管理员" in denied.body
    assert not store.list_targets()

    allowed = capability(
        _group_message(
            "订阅 add https://youtube.com/@demo", group_id="g1", sender_id="999", roles=["admin", "user"]
        ),
        None,
    )
    assert "已添加" in allowed.body
    assert store.list_targets()
    store.close()


def test_subscribe_pause_and_remove_are_destination_scoped(tmp_path) -> None:
    store = SubscriptionStoreV2(str(tmp_path / "subscriptions.sqlite3"))
    config = SimpleNamespace(bot_admin_user_ids=["999"])
    capability = build_subscribe_capability_v2(store=store, adapters=[], config=config)
    target_id = "youtube:channel:UC1"
    store.upsert_target(_target(target_id))
    for group_id in ("g1", "g2"):
        store.add_destination(
            SubscriptionDestinationV2(
                id="", target_id=target_id, transport="onebot.v11",
                scope="group", destination_id=group_id, bot_id="bot",
            )
        )

    # g1 管理员 pause：只停 g1 的目的地行，g2 不受牵连。
    paused = capability(
        _group_message(f"订阅 pause {target_id}", group_id="g1", sender_id="999", roles=["admin", "user"]),
        None,
    )
    assert "仅本目的地" in paused.body
    enabled_by_group = {
        dest.destination_id: dest.enabled for dest in store.list_destinations(target_id)
    }
    assert enabled_by_group == {"g1": False, "g2": True}

    # g1 管理员 resume 恢复。
    capability(
        _group_message(f"订阅 resume {target_id}", group_id="g1", sender_id="999", roles=["admin", "user"]),
        None,
    )
    assert all(dest.enabled for dest in store.list_destinations(target_id))

    # g1 remove：target 保留（g2 还在）；g2 再 remove 才删 target。
    first = capability(
        _group_message(f"订阅 remove {target_id}", group_id="g1", sender_id="999", roles=["admin", "user"]),
        None,
    )
    assert "其他目的地保留" in first.body
    assert store.get_target(target_id) is not None
    second = capability(
        _group_message(f"订阅 remove {target_id}", group_id="g2", sender_id="999", roles=["admin", "user"]),
        None,
    )
    assert "已删除订阅" in second.body
    assert store.get_target(target_id) is None
    store.close()
