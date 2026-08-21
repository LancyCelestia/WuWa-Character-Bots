"""关系态度层：对当前提问者的设定、好感度、称呼与态度。

- 档案：可选 JSON 文件，按 sender_id 存用户称呼、偏好、关系说明。
- 规则计算：无档案按 stranger 基线；有档案按档案里的 familiarity；
  亲和度 affinity 来自档案或规则默认。
- 注入 prompt 的"对当前用户的态度"分区，并轻微调整语气参数
  （warmth/directness），让回复"认识对方"而不是死板模板。

关系档案属于运营配置（可信），但其中的备注文本仍按不可信事实
处理，防止档案里出现注入内容。该层不决定权限、不决定发送。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from plugins.wuwa_unified_runtime.contracts.character import (
    RelationshipContext,
)

FAMILIARITY_TIERS = frozenset({"stranger", "familiar", "close"})

DEFAULT_ATTITUDE = {
    "stranger": "自然、礼貌，保持角色分寸，不假装熟识",
    "familiar": "温和、有陪伴感，可以记住对方说过的偏好",
    "close": "亲近、体贴，可以更直接地表达关心，但仍不越界",
}


class RelationshipProvider(Protocol):
    def load(self, request_id: str, sender_id: str) -> RelationshipContext:
        """读取对指定发送者的关系上下文。"""


class NullRelationshipProvider:
    def load(self, request_id: str, sender_id: str) -> RelationshipContext:
        return RelationshipContext(request_id=request_id)


class FileRelationshipProvider:
    """从 JSON 档案文件读取用户关系设定。

    格式::

        {
          "users": {
            "<sender_id>": {
              "label": "称呼",
              "familiarity": "stranger|familiar|close",
              "affinity": 0.8,
              "preferences": ["喜欢简短的回复"],
              "notes": ["最近在学鸣潮配队"]
            }
          }
        }
    """

    def __init__(self, profile_file: str | Path) -> None:
        self.profile_file = Path(profile_file).expanduser()

    def _load_users(self) -> dict[str, dict[str, object]]:
        if not self.profile_file.exists():
            return {}
        try:
            payload = json.loads(self.profile_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        users = payload.get("users")
        if not isinstance(users, dict):
            return {}
        return {
            str(key): value
            for key, value in users.items()
            if isinstance(value, dict)
        }

    def load(self, request_id: str, sender_id: str) -> RelationshipContext:
        entry = self._load_users().get(str(sender_id))
        if entry is None:
            return RelationshipContext(request_id=request_id)
        familiarity = str(entry.get("familiarity", "stranger")).strip().lower()
        if familiarity not in FAMILIARITY_TIERS:
            familiarity = "stranger"
        affinity = entry.get("affinity", 0.5)
        if not isinstance(affinity, (int, float)):
            affinity = 0.5
        affinity = max(0.0, min(1.0, float(affinity)))
        preferences = [
            str(item).strip()
            for item in entry.get("preferences", [])
            if isinstance(item, str) and item.strip()
        ]
        notes = [
            str(item).strip()
            for item in entry.get("notes", [])
            if isinstance(item, str) and item.strip()
        ]
        return RelationshipContext(
            request_id=request_id,
            user_label=str(entry.get("label", "用户")).strip() or "用户",
            familiarity=familiarity,
            affinity=affinity,
            preferences=preferences,
            relationship_notes=notes,
            attitude=str(entry.get("attitude", "")).strip()
            or DEFAULT_ATTITUDE[familiarity],
        )


def build_relationship_provider(config: object) -> RelationshipProvider:
    profile_file = str(getattr(config, "wuwa_user_profiles_file", "")).strip()
    if not profile_file:
        return NullRelationshipProvider()
    return FileRelationshipProvider(profile_file)


def apply_relationship_to_tone(
    warmth: float,
    directness: float,
    relationship: RelationshipContext | None,
) -> tuple[float, float]:
    """按关系层级轻微调整语气参数；调整幅度小且可解释。"""
    if relationship is None:
        return warmth, directness
    if relationship.familiarity == "close":
        return min(1.0, warmth + 0.08), max(0.0, directness - 0.05)
    if relationship.familiarity == "familiar":
        return min(1.0, warmth + 0.04), directness
    return warmth, directness
