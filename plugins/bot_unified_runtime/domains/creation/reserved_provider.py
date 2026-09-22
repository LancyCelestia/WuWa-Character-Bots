"""reserved: creation 对接点的 provider 配置探测与诚实可用性说明（统一接入波 U3）。

`reserved: 依赖外部 provider 配置，未实现`。本模块只提供 creation 域**自己的**两件
事，绝不 import 中央执行协议（`runtime.capability_protocols` 是「仅测试导入」的中央
层，域→中央的反向依赖会破坏依赖方向）：

1. ``provider_configured``——只读「未来键」（``getattr`` 缺省 None），键不存在/未配
   一律 False，绝不猜有 provider；未来真键由 U4/主会话在 config.py 落地并登记，
   本处仅预留读点（**不新增 config 键、不碰 config.py**）。
2. ``reserved_availability_reason``——未接线通道的诚实原因串（honest degrade 口径）。
3. ``reserved_channel_for``——把「域内 stable_id（``creation.image``）」与「中央描述符
   调用面 id（``creation.image.generate``）」两种在册写法归一到一个通道（2026-09-21
   统一波 S-CREATE 补：不归一则装配层传中央 id 时本域表查不中、诚实终态说错话）。

中央 orchestrator（U4 装配缝）用这两个函数把 creation 对接点注册为 handler：未配
provider 时返回 ``InvocationResult(status=UNAVAILABLE, detail=reason)``，**不新增第三
种结果类型**；DTO 作为成功态 ``data[PRESENTATION_DATA_KEY]`` 的呈现载荷流转，其形态
由 ``tests/test_creation_tts_drift_gate.py`` 直接构造 ``InvocationResult`` 验证（测试
可自由 import 中央层）。

占位纪律：零 import 副作用、零网络、零线程、零文件 I/O、零生产配置实例化读取。
"""

from __future__ import annotations

from typing import Any

#: 「未来键」探测表：capability_id → 判定 provider 是否已配置的 Config 属性名。
#: 这些键当前**不存在**于 config.py，getattr 恒返回 None ⇒ 探测恒 False（诚实未接线）。
#: 真键命名/落地是 U4/主会话的 config 面决定，本席只预留读点并交接。
PROVIDER_PRESENCE_KEYS: dict[str, tuple[str, ...]] = {
    "creation.tts": ("bot_creation_tts_provider",),
    "creation.image": ("bot_creation_image_provider",),
}

#: 各对接点的诚实原因串（未接线 = not_wired；协议≠可用）。
RESERVED_REASON: dict[str, str] = {
    "creation.tts": (
        "TTS 生成对接点未接线（reserved：依赖外部 provider 配置），"
        "诚实 unavailable，不盲重合成"
    ),
    "creation.image": (
        "AI 绘图对接点未接线（reserved：零现载体），"
        "诚实 unavailable，未知任务不重发"
    ),
}

#: 通道 id（本域注册面 stable_id）的**唯一**清单。
CHANNEL_IDS: tuple[str, ...] = ("creation.tts", "creation.image")

#: 中央描述符 id → 本域通道 id 的归一口。
#: 事实（实证）：本域注册表用 stable_id（``creation.image``），中央
#: ``_creation_descriptors()`` 用调用面 id（``creation.image.generate``/
#: ``creation.tts.synthesize``）。**两串都可能在装配期落到本函数的入参位置**，
#: 而中央 handler 的诚实 detail 只能由本域给（invoker 自己那句是通用「能力未接线
#: （not_wired）」，不区分绘画/TTS，也不点名 provider 是否已配）。
#: 不归一 ⇒ 装配层传中央 id 时本域两张表都查不中、恒返回「非 creation 预留面」，
#: 于是「诚实终态」在真实调用形态下悄悄说错话。归一口只此一处，禁装配层再抄一份；
#: 通道清单只读 ``CHANNEL_IDS``（不另立前缀表，否则又是一处第二真身）。
def reserved_channel_for(capability_id: str) -> str | None:
    """把任一在册写法归一成本域通道 id；非 creation 预留面返回 None（不猜）。"""
    if capability_id in CHANNEL_IDS:
        return capability_id
    for channel in CHANNEL_IDS:
        if capability_id.startswith(f"{channel}."):
            return channel
    return None


def provider_configured(config: Any, capability_id: str) -> bool:
    """provider 是否已显式配置：只认非空「未来键」，缺省/空值一律 False。"""
    channel = reserved_channel_for(capability_id)
    if channel is None:
        return False
    for key in PROVIDER_PRESENCE_KEYS.get(channel, ()):
        value = getattr(config, key, None)
        if isinstance(value, str):
            if value.strip():
                return True
        elif value:
            return True
    return False


def reserved_availability_reason(config: Any, capability_id: str) -> str:
    """未接线通道的诚实说明；provider 已配但实现工厂未接入也如实标注。"""
    channel = reserved_channel_for(capability_id)
    if channel is None:
        return f"{capability_id}：非 creation 预留面"
    if provider_configured(config, channel):
        return (
            f"{channel}：provider 已配置但实现工厂未接入"
            "（reserved：协议≠可用），诚实 unavailable"
        )
    return RESERVED_REASON[channel]


__all__ = [
    "CHANNEL_IDS",
    "PROVIDER_PRESENCE_KEYS",
    "RESERVED_REASON",
    "provider_configured",
    "reserved_availability_reason",
    "reserved_channel_for",
]
