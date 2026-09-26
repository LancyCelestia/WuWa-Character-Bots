"""reserved: creation 对接点的 provider 配置探测与诚实可用性说明（统一接入波 U3）。

`reserved: 依赖外部 provider 配置，未实现`。本模块只提供 creation 域**自己的**两件
事，绝不 import 中央执行协议（`runtime.capability_protocols` 是「仅测试导入」的中央
层，域→中央的反向依赖会破坏依赖方向）：

1. ``provider_configured``——只读在册键（``getattr`` 缺省 None），键不存在/未配
   一律 False，绝不猜有 provider。**绘画这一枚在册键名唯一走真身册读**
   （``domains/core.capability_manifest.config_keys_for("creation.image.generate")``，
   见 :func:`image_presence_keys`）：本域不再自写字面量，杜绝"探测表/工厂/描述符"三处各抄
   一遍而后漂移（中央调度收编波 S151 目标 5「禁第二处手抄」）。**在册键名是否在 ``config.py``
   登记仍不由本文案断言**（AGENTS 规则 10：这类事实几天就过期），由
   ``tests/test_creation_provider_key_single_source.py`` 现算真身册 ⇄ ``Config.model_fields``
   ⇄ 本域探测表三方对账。语音（creation.tts）保持自列三枚"在场性指示键"——那是与
   "能力读了哪些键"不同的**在场判据**（含 ``bot_tts_ref_audios``），刻意不并入真身册读，
   故本条只覆盖绘画。
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

from plugins.bot_unified_runtime.domains.core.capability_manifest import config_keys_for

#: 「provider 已配」的判据键。**在册性不写死在文案里**（AGENTS 规则 10：这类事实几天就过期）；
#: 每一枚都必须是 ``config.py`` 的真字段，由本席常驻锁拿 ``Config.model_fields`` 现算对账——
#: 点一枚不存在的键，比不点名更坏（运维照着改配置而配置面根本没有）。
#: 历史（保留作判据来历，非现值断言）：creation.tts 的现役载体是本机 GPT-SoVITS，
#: 判定源与 ``bot.tts`` 同一（``bot_tts_api_url``／``bot_tts_ref_audios``，禁另立口径）；
#: 旧写法只认 ``bot_creation_tts_provider`` 时语音即使接完执行体也永远诚实不可用
#: （中央调度收编波 CM-P-3 甲案，2026-09-23T20:0xZ 现算）。显式选择器键仍列在末尾。
#: 绘画对接点的**中央描述符调用面 id**——真身册 ``config_keys_for`` 的取数键。
#: 本域注册面用 stable_id（``creation.image``），描述符/册用调用面 id
#: （``creation.image.generate``）；在册键声明住在后者名下（``capability_manifest.FACETS``）。
_IMAGE_DESCRIPTOR_ID = "creation.image.generate"


def image_presence_keys() -> tuple[str, ...]:
    """绘画"已配"判据的**在册键名**——唯一真身＝中央能力册 ``config_keys_for``（目标 5）。

    三态诚实：
    - 册声明了恰好一枚键 ⇒ 原样返回（现网值＝``("bot_creation_image_provider",)``）；
    - 册返回空 ⇒ **抛错**（fail-closed）：探测表若悄悄退化成空，``provider_configured``
      会恒判"未配"、缺位告警永不触发——那是把"没接线"洗成"永远不用报"的静默黑洞，
      宁可装配期炸，也不留一条永不太平的告警腿；
    - 册返回多于一枚 ⇒ 同样抛错：绘画选择器只认单个 env（``BOT_CREATION_IMAGE_PROVIDER``），
      多义时不自作主张挑第一枚（那等于在本域偷偷再造判据）。

    本函数在调用时**现读** ``config_keys_for``（模块全局名），故活性锁可直接 monkeypatch
    该名验证"值确实来自册、不是一份等值副本"。
    """
    keys = tuple(config_keys_for(_IMAGE_DESCRIPTOR_ID))
    if not keys:
        raise RuntimeError(
            f"真身册未声明 {_IMAGE_DESCRIPTOR_ID} 的 provider 键：绘画在场性判据失去唯一来源，"
            "拒绝退化为空表（空表会让缺位告警永不太平）"
        )
    if len(keys) > 1:
        raise RuntimeError(
            f"真身册为 {_IMAGE_DESCRIPTOR_ID} 声明了 {len(keys)} 枚键，"
            "绘画选择器只认单枚 env，多义时不猜第一枚"
        )
    return keys


PROVIDER_PRESENCE_KEYS: dict[str, tuple[str, ...]] = {
    "creation.tts": (
        "bot_tts_api_url",
        "bot_tts_ref_audios",
        "bot_creation_tts_provider",
    ),
    # 绘画这枚不在这里手写字面量——它现读真身册（见 :func:`image_presence_keys`）。
    "creation.image": image_presence_keys(),
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
    """provider 是否已显式配置：只认非空「在册键」，缺省/空值一律 False（绝不猜有）。"""
    channel = reserved_channel_for(capability_id)
    if channel is None:
        return False
    for key in PROVIDER_PRESENCE_KEYS.get(channel, ()):
        if _is_filled(getattr(config, key, None)):
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


class CreationNotWired(RuntimeError):
    """creation 预留面「缺位」异常基类：诊断卡通道（``INVOKER_ERROR_DATA_KEY``）的载荷**形态**。

    为什么住本件（而不是各通道自己 ``class ... (RuntimeError)`` 一处一份）：
    层 1 的读者（``orchestrated_command._step``）只按 ``BaseException`` 判，
    于是"有没有一张能归因的卡"取决于**异常文本**；把文本的唯一构造口放这里，
    两通道才可能真的同形（此前绘画有、语音一句都没有，见 SEAT-S115 取证）。

    本类**不 import 中央层**（同模块头纪律）：中央键名 ``INVOKER_ERROR_DATA_KEY``
    仍由各通道的 ``engine_provider`` 在函数体内延迟 import 后塞进信封——
    "载荷放哪"归中央，"载荷说什么"归本域。
    """


def _is_filled(value: object) -> bool:
    """「这枚键算不算被填过」的唯一尺子：非空字符串（去空白）或非空其它值。

    ``provider_configured`` 与下面的「待配键点名」共用它——否则会出现
    "判定说已配、文案说待配" 这种自相矛盾的第二把尺子。
    """
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def provider_key_names(capability_id: str) -> tuple[str, ...]:
    """该通道在册的**全部** provider 配置键名（非探测表未列时为空表，不猜）。"""
    channel = reserved_channel_for(capability_id)
    if channel is None:
        return ()
    return tuple(PROVIDER_PRESENCE_KEYS.get(channel, ()))


def pending_provider_keys(config: Any, capability_id: str) -> tuple[str, ...]:
    """现算该通道**此刻真的还空着**的键名（＝运维能动手的那几枚）。

    与 ``provider_configured`` 同一条判据（都走 :func:`_is_filled`），所以
    "已填却被点名为待配" 这种谎话在这扇门里构造不出来——被测试当作真身谓词钉死。
    """
    return tuple(
        key
        for key in provider_key_names(capability_id)
        if not _is_filled(getattr(config, key, None))
    )


def not_wired_detail(config: Any, capability_id: str) -> str:
    """「缺位」可归因说明的唯一构造口：原因（复用在册真身）＋ 缺哪几枚配置键的**键名**。

    三条硬口径（目标 4「缺位必须可见」对文案的要求，逐条有锁）：
    ① **只写键名、绝不写值**——配置值里可能带 token/密码/本机路径，写值即违反铁律 3；
    ② 键名一律出自 :data:`PROVIDER_PRESENCE_KEYS`（在册表），不手写字符串，
       所以"探测表改了、文案还在点旧键"这种漂移会被测试抓到；
    ③ 键**已填齐**时不再喊"待配键"，改点名「缺的是适配器登记、非配置面」——
       把已填的键说成待配，等于把运维指向错的那扇门。
    """
    reason = reserved_availability_reason(config, capability_id)
    keys = provider_key_names(capability_id)
    if not keys:
        return reason
    pending = pending_provider_keys(config, capability_id)
    if pending:
        return f"{reason}｜待配键：{'，'.join(pending)}"
    return (
        f"{reason}｜配置键已填（{'，'.join(keys)}）："
        "缺的是适配器登记（provider_factory 注册表），非配置面"
    )


__all__ = [
    "CHANNEL_IDS",
    "PROVIDER_PRESENCE_KEYS",
    "RESERVED_REASON",
    "CreationNotWired",
    "image_presence_keys",
    "not_wired_detail",
    "pending_provider_keys",
    "provider_configured",
    "provider_key_names",
    "reserved_availability_reason",
    "reserved_channel_for",
]
