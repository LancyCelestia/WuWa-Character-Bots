"""共享 prompt 模板层（W1，2026-10-02）：送进 provider 的文本只有一个装配口。

## 本件解决什么
`chat.py` 主腿的 prompt 走「分区注入 + 反注入包裹」中央咽喉；但后台抽取腿
（记忆抽取、反思归纳、媒体归档、课表识别、日程草稿、文档生成）各自
`f"..."` 自拼 messages 再直呼 `provider.generate` ——反注入包裹与分区渲染对它们
**结构性不存在**：一条 `[TRUSTED_SYSTEM] …` 能在媒体归档摘要、反思转写、日程草稿里
原样进模型，而同一句话在主对话腿会被全角化并关进不可信块。本件把「装配」收成
一枚真身：**模板 = 静态骨架 + 具名槽位 + 槽位信任级**，provider-bound 文本只能由
`render_messages()` 产出。

## 三条硬口径（改本件前先读）
1. **统一 ≠ 行为改写**。收编一条腿的验收判据是「除包裹层以外逐字节不变」，
   所以渲染必须可关包裹：`render_messages(values, raw=True)` 产出**与本件落地前
   完全相同**的骨架文本（锁在 `tests/test_prompt_template_layer_w1.py`，golden 取自
   HEAD 现跑录制）。`raw=True` 只准测试用；生产面出现即红
   （`tests/test_prompt_throat_ast_gate_w1.py` 反绕过腿）。
2. **消毒零新尺**。`WRAP` = `security/injection.guard_secondhand_text`，
   `MARKERS` = `neutralize_internal_markers`，`NONE` = 原样。本件**不带任何**正则、
   边界标记名或引导句——自己写一份包裹就是把第二把消毒尺请进门（台账 #49★/#72★
   那条「禁第二真身」），而中央件的检测腿刚改成吃归一视图（W8），本件只是消费者。
3. **槽位名册双向核账**。空文本在 `WRAP` 下渲染成空串（`guard_secondhand_text`
   的在册语义：空进空出，绝不谎报「读到了东西」）；缺槽或多传名册外槽 ⇒ 抛
   `PromptSlotMissing`，绝不静默补空/静默忽略——静默补空会把「漏传一段上下文」
   洗成「模型本来就没看到」，静默忽略会把「调用方在发第五段」洗成「没有第五段」。

## 分区渲染的边界（本批刻意不做）
主对话腿的「空分区不渲染」在这里**不开**：这些腿旧行为是空值也照打锚点
（`回复：` 后面空着照旧发），改成丢弃＝行为改写，与口径 1 冲突。要开就得按腿
逐条证明并另立判据，留给后续批（工单 `patches/W1-PROMPT-TEMPLATE-LAYER-20261002.md`）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PromptGuard(str, Enum):
    """槽位信任级：决定该段文本进模型前过哪一道中央消毒口。"""

    NONE = "none"  # 代码自产的静态文本（锚点、当前时间、JSON 契约说明）
    MARKERS = "markers"  # 逐条注入档：只做边界标记全角化，不吃包裹开销
    WRAP = "wrap"  # 二手材料档：全角化 + 成对边界 + 一句定性引导


class PromptSlotMissing(KeyError):
    """渲染时缺槽位（含值不在名册内）⇒ 硬失败，绝不静默补空。"""


@dataclass(frozen=True)
class PromptSlot:
    """一个具名文本槽：`prefix` 是锚点字面量（逐字节保留旧拼法），`guard` 是信任级。"""

    name: str
    prefix: str = ""
    guard: PromptGuard = PromptGuard.NONE
    source_label: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("PromptSlot.name 不能为空")
        if self.guard is PromptGuard.WRAP and not self.source_label.strip():
            raise ValueError(f"槽 {self.name}：WRAP 必须给 source_label（引导行要说清来源）")


def _guarded(text: str, slot: PromptSlot, guard: PromptGuard) -> str:
    """按槽位信任级处置一段文本；消毒口唯一真身＝``security/injection``（零新尺）。"""
    if guard is PromptGuard.NONE or not text:
        return text
    # 局部导入：与 chat_reply 装配链的模块级循环是死路，口径同
    # ``domains/core/search/native_tools.py``（它也是就地取 guard_secondhand_text）。
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        guard_secondhand_text,
        neutralize_internal_markers,
    )

    if guard is PromptGuard.MARKERS:
        return neutralize_internal_markers(text)
    return guard_secondhand_text(text, source_label=slot.source_label)


class _BaseTemplate:
    """两型模板的共同底座：key 与 system 静态文本（普通类，不用 frozen dataclass
    ——子类要往实例上挂 `slots`/`lead`，frozen 底座会把赋值打成 FrozenInstanceError）。"""

    def __init__(self, *, key: str, system: str) -> None:
        if not key.strip():
            raise ValueError("模板 key 不能为空")
        if not system.strip():
            raise ValueError(f"模板 {key}：system 文本不能为空")
        self.key = key
        self.system = system


class PromptTemplate(_BaseTemplate):
    """文本腿模板：system 静态文本 + 若干 user 槽位拼成一条 user 消息。"""

    def __init__(
        self,
        *,
        key: str,
        system: str,
        slots: Sequence[PromptSlot],
        join: str = "\n",
    ) -> None:
        super().__init__(key=key, system=system)
        names = [slot.name for slot in slots]
        if len(names) != len(set(names)):
            raise ValueError(f"模板 {key}：槽位名重复 {names}")
        self.slots: tuple[PromptSlot, ...] = tuple(slots)
        self.join = join

    def render_text(self, values: Mapping[str, object], *, raw: bool = False) -> str:
        """渲染 user 侧文本（不包裹时＝旧 f-string 的逐字节等价体）。

        槽位名册是**双向**判据：少传＝那段上下文静默缺席，多传＝调用方以为自己在
        发东西而模板根本不认——两边都比「模型少看了一段」更坏，一律硬失败。
        """
        declared = {slot.name for slot in self.slots}
        missing = sorted(declared - set(values))
        extra = sorted(set(values) - declared)
        if missing or extra:
            raise PromptSlotMissing(
                f"模板 {self.key}：缺槽 {missing} / 多名册外槽 {extra}"
            )
        pieces: list[str] = []
        for slot in self.slots:
            text = str(values[slot.name] or "")
            guard = PromptGuard.NONE if raw else slot.guard
            pieces.append(f"{slot.prefix}{_guarded(text, slot, guard)}")
        return self.join.join(pieces)

    def render_messages(
        self, values: Mapping[str, object], *, raw: bool = False
    ) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.render_text(values, raw=raw)},
        ]


class PromptPartsTemplate(_BaseTemplate):
    """多模态腿模板：静态引导文本 + 调用方备好的 content parts（图像段原样透传）。

    图像字节不是文本，反注入包裹对它无意义 ⇒ 本件的增量只在「装配收口」，
    该腿收编前后**零字节差**（这正是判据 1 想要的形态）。
    """

    def __init__(self, *, key: str, system: str, lead: PromptSlot) -> None:
        super().__init__(key=key, system=system)
        self.lead = lead

    def render_messages(
        self, values: Mapping[str, object], *, raw: bool = False
    ) -> list[dict[str, Any]]:
        if "lead" not in values or "parts" not in values:
            raise PromptSlotMissing(f"模板 {self.key} 需要 lead 与 parts 两枚槽位")
        lead_text = str(values["lead"] or "")
        guard = PromptGuard.NONE if raw else self.lead.guard
        parts = values["parts"]
        if not isinstance(parts, list):
            raise PromptSlotMissing(f"模板 {self.key}：parts 必须是 list，收到 {type(parts).__name__}")
        return [
            {"role": "system", "content": self.system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _guarded(lead_text, self.lead, guard)},
                    *parts,
                ],
            },
        ]


_REGISTRY: dict[str, Any] = {}


def register_prompt_template(template: Any) -> Any:
    """登记模板真身；同 key 二次登记＝起了第二份骨架，硬失败。"""
    key = getattr(template, "key", "")
    if not isinstance(key, str) or not key:
        raise ValueError("只准登记带非空 key 的模板对象")
    if key in _REGISTRY:
        raise ValueError(f"prompt 模板 key 重复：{key}（禁第二份骨架）")
    _REGISTRY[key] = template
    return template


def get_prompt_template(key: str) -> Any:
    return _REGISTRY[key]


def prompt_template_keys() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
