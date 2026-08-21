"""人格切换：主人格（A）+ 备用人格（B/C）的选择器。

选择顺序（纯规则、不烧 LLM）：

1. **管理员覆盖**：``/bot persona switch <id>`` 写入的强制切换；
   ``default`` 表示回到自动模式。
2. **情绪触发**：当前情绪信号命中某人格的 ``emotions`` 配置
   （例如低能量/需要陪伴 → 温柔型；求助/排查 → 理性型）。
3. **概率切换**：按各人格 ``weight`` 随机抽取（管理员可用
   ``/bot persona probability`` 调整，0 表示不参与随机）。
4. **默认**：主人格（A，``BOT_PERSONA_*`` 指向的文件）。

随机源可注入（测试用固定 seed）；未命中任何规则时返回 None，
调用方继续使用主人格。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AltPersonaSpec:
    profile_id: str
    display_name: str
    files: tuple[str, ...] = ()
    weight: float = 0.0
    emotions: tuple[str, ...] = ()


class PersonaSelector:
    def __init__(self, alt_personas: dict[str, AltPersonaSpec]) -> None:
        self.alt_personas = dict(alt_personas)

    def select(
        self,
        *,
        emotions: list[str] | None = None,
        override: str = "",
        weights: dict[str, float] | None = None,
        rng: random.Random | None = None,
    ) -> AltPersonaSpec | None:
        if override:
            if override == "default":
                return None
            spec = self.alt_personas.get(override.strip())
            if spec is not None:
                return spec
            # 管理员指定了不存在的人格 id：保守地回到主人格，不参与随机。
            return None
        emotion_labels = set(emotions or [])
        for spec in self.alt_personas.values():
            if emotion_labels & set(spec.emotions):
                return spec
        candidates: list[tuple[AltPersonaSpec, float]] = []
        effective_weights = dict(weights or {})
        for spec_id, spec in self.alt_personas.items():
            weight = effective_weights.get(spec_id, spec.weight)
            if weight is None or weight <= 0:
                continue
            candidates.append((spec, min(1.0, float(weight))))
        if not candidates:
            return None
        draw = (rng or random).random()
        accumulated = 0.0
        for spec, weight in candidates:
            accumulated += weight
            if draw < accumulated:
                return spec
        return None


def build_alt_personas(config: object) -> dict[str, AltPersonaSpec]:
    raw = getattr(config, "bot_persona_alt_profiles", {}) or {}
    specs: dict[str, AltPersonaSpec] = {}
    for profile_id, item in raw.items():
        if not isinstance(item, dict):
            continue
        files = item.get("files")
        if isinstance(files, list):
            file_list = tuple(str(path) for path in files)
        elif isinstance(files, str):
            file_list = tuple(
                path.strip() for path in files.split(";") if path.strip()
            )
        else:
            file_list = ()
        if not file_list:
            continue
        emotions = item.get("emotions")
        if isinstance(emotions, list):
            emotion_list = tuple(str(value) for value in emotions)
        elif isinstance(emotions, str):
            emotion_list = tuple(
                value.strip() for value in emotions.split(",") if value.strip()
            )
        else:
            emotion_list = ()
        weight = item.get("weight", 0.0)
        if not isinstance(weight, (int, float)):
            weight = 0.0
        specs[str(profile_id)] = AltPersonaSpec(
            profile_id=str(profile_id),
            display_name=str(item.get("display_name", profile_id)).strip()
            or str(profile_id),
            files=file_list,
            weight=max(0.0, min(1.0, float(weight))),
            emotions=emotion_list,
        )
    return specs
