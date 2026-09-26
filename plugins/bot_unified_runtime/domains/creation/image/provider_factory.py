"""creation.image 绘图 provider **工厂**（中央调度收编波 S49：配置值 → 适配器实例）。

一句话：本件是「把 ``BOT_CREATION_IMAGE_PROVIDER`` 的值变成 ``ImageProvider`` 适配器
实例」的**唯一派发口**。它不做执行、不建 HTTP 客户端、不出图——执行体腿在
``engine_provider.handle``，契约在 ``contracts``，本件只管**选谁**。

四条家规（逐条有测试执法，见 ``tests/test_creation_image_provider_factory.py``）：

1. **fail-closed 诚实缺位**——未配置/空白/未知选择器名一律 ``provider=None`` +
   可操作理由（点名待配键 ``bot_creation_image_provider`` 与唯一注册表
   :data:`PROVIDER_REGISTRY`）。"是否已配"的判定**只调用** reserved_provider 的
   单一真身 :func:`~plugins.bot_unified_runtime.domains.creation.reserved_provider.provider_configured`，
   本件不立第二把尺子。
2. **生产派发表永不含离线 mock**（S09 铁律 3 的工厂侧执行）——即使有人把
   ``MockImageProvider`` 注册进表，:func:`build_image_provider` 也按 ``offline_mock``
   判别位拒收；mock 唯一合法通道仍是测试经 ``context["image_provider"]`` 显式注入。
3. **禁第二真身数值**——硬顶/参数域的唯一家在 ``contracts``（IMAGE_MAX_* 一族），
   缓存/摘要/seed 派生的唯一家在 Wave G/H 契约层（``domains/media/digest`` 与
   ``tts_presets`` 同族纪律）；本件零 ``hashlib``、零 ``sha256(``、零数值上限抄写。
4. **依赖方向不反转**——中央层（``runtime.capability_protocols``）与兄弟件
   ``engine_provider`` 一律函数体内延迟 import（``TYPE_CHECKING`` 只作注解），
   模块期零副作用、零网络、零线程、零文件 I/O、零生产配置实例化。

⚠ 在册事实（S69 现算收口 2026-09-24 更新）：**生产选择链已引用本件**——
``engine_provider.select_image_provider`` 在"键已配"分支现委派本工厂，工厂判 ``wired`` 才给
适配器（此前工厂是死件＝简报断点①，S49 残项由 S69 接线）。但**接上委派 ≠ 出图可用**：
``PROVIDER_REGISTRY`` 今天仍为空（全仓无真实绘图后端客户端载体），故填了
``BOT_CREATION_IMAGE_PROVIDER`` 仍派发出 ``unknown_provider`` ⇒ handler 诚实 ``UNAVAILABLE``。
"填键重启即出图"要等有人把真实适配器登记进本表（家规 2 除外 mock）才成立。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅注解：运行期不在模块期触碰执行体/中央层（离线导入探针纪律）
    from .engine_provider import ImageProvider

__all__ = [
    "PROVIDER_REGISTRY",
    "ImageProviderSelection",
    "build_image_provider",
    "provider_selector_config_key",
]


def provider_selector_config_key() -> str:
    """绘画选择器键（Config 属性名）——**唯一真身＝真身册，禁本件手抄字面量**（目标 5）。

    取数只走 :func:`reserved_provider.image_presence_keys`（其本体现读
    ``capability_manifest.config_keys_for("creation.image.generate")``），故本件与描述符侧
    共读同一枚在册键、不再有第二处手抄。键的 env 形态（大写名）在 ``RESTART_REQUIRED_KEYS``
    登记：装配期烘进描述符/健康探针，改值须重启——理由串点名，免得管理员填了等热改。
    册返回空/多义时 ``image_presence_keys`` 会抛错（fail-closed），本件不就地兜成"猜一枚"。
    """
    from .. import reserved_provider

    return reserved_provider.image_presence_keys()[0]

#: 「选择器名 → 适配器构造器」的**唯一**生产派发表。
#:
#: 事实：本表今天为空——全仓没有任何真实绘图后端客户端实现（SD/Flux/comfyui 一类
#: 均无载体），协议八段虽齐，实现腿缺位。接真适配器时**只准**在此登记（或测试经
#: :func:`build_image_provider` 的 ``registry`` 形参显式交表），**禁**在别处再写一份
#: if/elif 派发（第二真身）。构造器接收 ``config``（供读取端点/密钥引用等非敏感
#: 装配参数）并返回 ``ImageProvider`` 形态对象；离线 mock 依家规 2 永不得入本表。
PROVIDER_REGISTRY: Mapping[str, Callable[[Any], Any]] = MappingProxyType({})

#: 派发终态的封闭集：``wired`` 之外全部是「未接线」家族，``provider`` 必为 ``None``。
_VALID_STATES = frozenset(
    {"wired", "not_configured", "unknown_provider", "constructor_failed", "mock_rejected",
     "protocol_mismatch"}
)


@dataclass(frozen=True)
class ImageProviderSelection:
    """一次派发的完整结论：适配器（或 ``None``）+ 终态 + 可操作理由。

    构造期不变量（与中央信封「非成功必带诚实说明」同一哲学）：理由永远非空，
    ``provider`` 只在 ``wired`` 态出现——把"没配好却说接上了"堵在类型层。
    """

    provider: ImageProvider | None
    state: str
    reason: str

    def __post_init__(self) -> None:
        if self.state not in _VALID_STATES:
            raise ValueError(f"未知派发终态 {self.state!r}（合法集见 _VALID_STATES）")
        if self.state == "wired":
            if self.provider is None:
                raise ValueError("wired 态必须携带 provider；None+ready 是假账")
        elif self.provider is not None:
            raise ValueError(f"{self.state} 属未接线终态，禁止携带 provider")
        if not str(self.reason or "").strip():
            raise ValueError("未给出理由的派发结论不可归因，拒绝构造（诚实说明缺失）")


def _registry_names(registry: Mapping[str, Callable[[Any], Any]]) -> str:
    """把在册选择器名折成人读串（空表明说为空，不装作"还有别的"）。"""
    names = sorted({str(key).strip().casefold() for key in registry if str(key).strip()})
    return "、".join(names) if names else "（注册表当前为空，无任何已登记适配器）"


def build_image_provider(
    config: Any,
    *,
    registry: Mapping[str, Callable[[Any], Any]] = PROVIDER_REGISTRY,
) -> ImageProviderSelection:
    """按配置值派发绘图适配器；一切拿不到适配器的形态都诚实给"未接线"+理由。

    判定顺序（每步的 reason 都可操作）：

    1. reserved_provider 判「是否已配」→ 未配/空白 ⇒ ``not_configured``；
    2. 选择器名在 ``registry`` 查注 ⇒ 查不到 ⇒ ``unknown_provider``（点名在册名册）；
    3. 构造器抛异常 ⇒ ``constructor_failed``（只回显异常**类型名**，不回显参数值，
       防把 env 形态密钥带进理由串）；
    4. 返回对象 ``offline_mock`` 为真 ⇒ ``mock_rejected``（家规 2，S09 铁律 3）；
    5. 返回对象不合 ``ImageProvider`` 协议面 ⇒ ``protocol_mismatch``；
    6. 全过 ⇒ ``wired``。
    """
    from .. import reserved_provider

    # 选择器键名现读真身册（禁本件手抄，见 provider_selector_config_key）。键"名"与配置
    # "值"是否填过无关——not_configured 文案也要点名它，故在判"已配"之前先把它算出来。
    selector_key = provider_selector_config_key()

    if not reserved_provider.provider_configured(config, "creation.image"):
        return ImageProviderSelection(
            provider=None,
            state="not_configured",
            reason=(
                f"未配置：{selector_key}（env: {selector_key.upper()}）为空或不存在。"
                f"接法：先有一个真实适配器登记进 provider_factory.PROVIDER_REGISTRY"
                f"（当前{_registry_names(registry)}），再把选择器名填入该键；"
                f"该键在 RESTART_REQUIRED_KEYS，填后需重启生效。"
                f"离线 mock 只可测试注入，不是生产接法。"
            ),
        )

    raw = getattr(config, selector_key, None)
    name = str(raw or "").strip().casefold()
    if not name:
        # provider_configured 对非字符串真值也会判"已配"（如误填列表）：到这里就是形态不认。
        return ImageProviderSelection(
            provider=None,
            state="unknown_provider",
            reason=(
                f"{selector_key} 的值 {type(raw).__name__} 形不是选择器名（须为非空字符串）。"
                f"在册选择器：{_registry_names(registry)}。"
            ),
        )

    constructor: Callable[[Any], Any] | None = None
    for key, candidate in registry.items():
        if str(key).strip().casefold() == name:
            constructor = candidate
            break
    if constructor is None:
        return ImageProviderSelection(
            provider=None,
            state="unknown_provider",
            reason=(
                f"选择器 {name[:64]!r} 未注册适配器。唯一注册表 provider_factory.PROVIDER_REGISTRY，"
                f"当前在册：{_registry_names(registry)}。未知值不放行、不猜近似名（fail-closed）。"
            ),
        )

    try:
        provider = constructor(config)
    except Exception as exc:  # noqa: BLE001 - 构造失败面必须收敛成诚实终态，不许裸抛穿中央
        return ImageProviderSelection(
            provider=None,
            state="constructor_failed",
            reason=(
                f"选择器 {name[:64]!r} 的适配器构造器抛出 {type(exc).__name__}"
                "（原因不回显，防配置值外泄）。修适配器或其依赖后重试；本件不放行半残对象。"
            ),
        )

    if bool(getattr(provider, "offline_mock", False)):
        return ImageProviderSelection(
            provider=None,
            state="mock_rejected",
            reason=(
                f"选择器 {name[:64]!r} 解析出的是离线 mock（S09 铁律 3）：mock 永不进生产派发链，"
                "其唯一合法通道是测试经 context[\"image_provider\"] 显式注入。"
                "生产要的是真实适配器。"
            ),
        )

    from .engine_provider import ImageProvider as _Protocol

    if not isinstance(provider, _Protocol):
        return ImageProviderSelection(
            provider=None,
            state="protocol_mismatch",
            reason=(
                f"选择器 {name[:64]!r} 的构造器返回 {type(provider).__name__}，"
                "不合 ImageProvider 协议面（capabilities/submit/poll/cancel/offline_mock）。"
                "不合规对象不放行——宁缺毋滥。"
            ),
        )

    return ImageProviderSelection(
        provider=provider,
        state="wired",
        reason=(
            f"已按 {selector_key}={name[:64]!r} 经 PROVIDER_REGISTRY 派发适配器 "
            f"{type(provider).__name__}。选择器在装配期烘入（RESTART_REQUIRED_KEYS），改值须重启。"
        ),
    )
