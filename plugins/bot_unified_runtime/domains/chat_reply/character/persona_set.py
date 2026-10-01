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
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AltPersonaSpec:
    profile_id: str
    display_name: str
    files: tuple[str, ...] = ()
    weight: float = 0.0
    emotions: tuple[str, ...] = ()
    # 人格自带的**静态知识清单**（H-4甲：切人格只换这一份文本清单，向量库不碰）。
    # 空元组＝该 persona 不表态，由 providers 回落 .env 基线清单（不制造第二真身）。
    knowledge_files: tuple[str, ...] = ()


class PersonaSelector:
    """备用人格选择器。入参是**可调用视图**（单一形态，不收 dict 快照）。

    为什么不收 dict：装配期一次性快照会把人格册冻结在构造瞬间——启动后入册/
    改册的人格永远读不到（SEAT-ATK-PERSONA-APPEARANCE 探针 P1 实证的根病，
    H-5乙热读的消费腿缺口）。唯一构造点在 providers 装配工厂处以
    ``lambda: build_effective_alt_personas(...)`` 适配，每次 ``select()`` 现读，
    与校验腿（runtime_admin 现算）同册同速。dict 形态**不接受**（禁双形态分支）。
    """

    def __init__(
        self, alt_personas: Callable[[], Mapping[str, AltPersonaSpec]]
    ) -> None:
        # 单一形态硬闸：构造时即拒收非可调用对象（dict 快照当场 TypeError，
        # 不是"两形态都收"的分支——唯一合法形态就是可调用视图，绝不静默冻结）。
        if not callable(alt_personas):
            raise TypeError(
                "PersonaSelector 只收可调用视图 Callable[[], Mapping[str, AltPersonaSpec]]；"
                "装配期 dict 快照正是被治的半切根病，禁止回潮"
            )
        self._alt_personas_view = alt_personas

    def _current(self) -> dict[str, AltPersonaSpec]:
        """每轮现读视图：一次 select() 内取一次快照，保证同轮判定一致。"""
        return dict(self._alt_personas_view())

    def select(
        self,
        *,
        emotions: list[str] | None = None,
        override: str = "",
        weights: dict[str, float] | None = None,
        rng: random.Random | None = None,
    ) -> AltPersonaSpec | None:
        alt_personas = self._current()
        if override:
            if override == "default":
                return None
            spec = alt_personas.get(override.strip())
            if spec is not None:
                return spec
            # 管理员指定了不存在的人格 id：保守地回到主人格，不参与随机。
            return None
        emotion_labels = set(emotions or [])
        for spec in alt_personas.values():
            if emotion_labels & set(spec.emotions):
                return spec
        candidates: list[tuple[AltPersonaSpec, float]] = []
        effective_weights = dict(weights or {})
        for spec_id, spec in alt_personas.items():
            weight = effective_weights.get(spec_id, spec.weight)
            if weight is None or weight <= 0:
                continue
            candidates.append((spec, min(1.0, float(weight))))
        if not candidates:
            return None
        # 权重按总和归一化抽样：不归一化时累计权重超过 1.0 会把排在
        # 后面的人格永远截胡（三个 0.6 → 第三个 draw<1.8 恒不可达）。
        total_weight = sum(weight for _, weight in candidates)
        draw = (rng or random).random() * total_weight
        accumulated = 0.0
        for spec, weight in candidates:
            accumulated += weight
            if draw < accumulated:
                return spec
        return candidates[-1][0]


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
        knowledge_files = _coerce_tuple(item.get("knowledge_files"))
        specs[str(profile_id)] = AltPersonaSpec(
            profile_id=str(profile_id),
            display_name=str(item.get("display_name", profile_id)).strip()
            or str(profile_id),
            files=file_list,
            weight=max(0.0, min(1.0, float(weight))),
            emotions=emotion_list,
            knowledge_files=knowledge_files,
        )
    return specs


def _coerce_tuple(value: object) -> tuple[str, ...]:
    """清单字段兼容 list / 分号串 / 缺失三态，统一成去空字符串元组。"""
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return tuple(part.strip() for part in value.split(";") if part.strip())
    return ()
