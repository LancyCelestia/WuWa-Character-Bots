"""S49：绘图 provider 工厂的离线验收（零网络 / 零真实出图 / 零生产配置实例）。

被检件＝``domains/creation/image/provider_factory.py``。两臂按简报口径：

- **没配 ⇒ UNAVAILABLE**：真跑中央 handler ``engine_provider.handle``（未注入
  provider 的缺省形态），断言诚实 ``UNAVAILABLE`` + ``INVOKER_ERROR_DATA_KEY``
  带 ``CreationImageNotWired``（缺位可见三通道之一的腿，不回归即可）。
- **配了 provider ⇒ 出结果件契约对象**：两节真身各自实跑、测试拼链——
  ① 工厂层：注入式 registry + 选择器值 ⇒ ``wired`` 并拿到适配器实例；
  ② 执行层：该实例经 S09 在册合法注入缝（``context["image_provider"]``）进
  ``handle`` ⇒ 信封呈现载荷可被 ``CreationJob`` 契约**回读验证**。
  ⚠ 本文件同时钉住**在册事实**（``test_production_selection_chain_delegates_to_factory``）：
  生产选择链 ``select_image_provider`` 现**已委派工厂**（S49 §5 残项由 S69 接线），但注册表
  今天仍空 ⇒ 填键重启**仍不出图**（工厂给不出适配器 ⇒ handler 诚实 UNAVAILABLE）；工厂一旦
  登记真实适配器，select 即把该适配器交回执行面。

牙（注毒自证，逐发在席报告登记 sha 对）：
- ``test_factory_never_hands_out_offline_mock``：删工厂的 mock 判别闸 ⇒ 本例红；
- ``test_selection_invariant_rejects_wired_without_provider`` / 构造失败/协议不合三例：
  工厂把失败面放宽成放行 ⇒ 对应例红；
- ``test_factory_defers_to_reserved_provider_presence_ruler``：工厂自立第二把"已配"
  尺子（绕过 reserved_provider）⇒ 本例红。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.image import engine_provider as ep
from plugins.bot_unified_runtime.domains.creation.image import provider_factory as pf

_FACTORY_PATH = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "creation"
    / "image"
    / "provider_factory.py"
)


def _cp():
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦他席在飞把中央装配改崩
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非本席面）: {exc}")
    return cp


def _job(**overrides: object) -> cimage.ImageJobRequest:
    payload: dict[str, object] = {
        "task": "text_to_image",
        "prompt": "海平面尽头的灯塔，釉瑚色",
        "provider": "test-offline",
        "model": "image-model-1",
        "size": "1024x1024",
        "workspace_id": "ws_s49",
        "version": "rev-1",
    }
    payload.update(overrides)
    return cimage.ImageJobRequest(**payload)  # type: ignore[arg-type]


def _request(cp_module: Any, *, job: Any, config: Any, provider: Any = ...) -> Any:
    context: dict[str, Any] = {"config": config}
    if provider is not ...:
        context["image_provider"] = provider
    return cp_module.CapabilityRequest(
        capability_id="creation.image.generate",
        payload={"job": job},
        context=context,
    )


class _NonMockProvider(ep.MockImageProvider):
    """测试替身：声明 offline_mock=False 以走"真实适配器"协议面（同 S09 先例
    ``test_real_provider_success_maps_to_ok``——判别位由替身自报，本席只验工厂/链路）。"""

    @property
    def offline_mock(self) -> bool:  # type: ignore[override]
        return False


# ---------------------------------------------------------------------------
# 臂二前置：工厂缺位面（未配置 / 空白 / 未知 / 非字符串）
# ---------------------------------------------------------------------------


def test_missing_key_is_not_configured_with_actionable_reason() -> None:
    sel = pf.build_image_provider(SimpleNamespace())
    assert sel.provider is None
    assert sel.state == "not_configured"
    # 理由必须可操作：点名待配键、唯一注册表、mock 不是生产接法。
    assert "bot_creation_image_provider" in sel.reason
    assert "PROVIDER_REGISTRY" in sel.reason
    assert "mock" in sel.reason
    # 单一尺子同源：工厂判"未配"与 reserved_provider 判定一致。
    assert rprov.provider_configured(SimpleNamespace(), "creation.image") is False


def test_blank_value_is_not_configured() -> None:
    sel = pf.build_image_provider(SimpleNamespace(bot_creation_image_provider="   "))
    assert sel.provider is None
    assert sel.state == "not_configured"


def test_unknown_selector_rejected_and_registry_emptiness_named() -> None:
    sel = pf.build_image_provider(SimpleNamespace(bot_creation_image_provider="stable-diffusion"))
    assert sel.provider is None
    assert sel.state == "unknown_provider"
    # 今天的真相：生产注册表为空——理由必须明说，不许含糊成"稍后再试"。
    assert "当前为空" in sel.reason or "（注册表当前为空" in sel.reason


def test_non_string_selector_value_is_unknown_not_guessed() -> None:
    sel = pf.build_image_provider(SimpleNamespace(bot_creation_image_provider=["sd"]))
    assert sel.provider is None
    assert sel.state == "unknown_provider"


def test_factory_defers_to_reserved_provider_presence_ruler() -> None:
    """单一"已配"尺子锁：工厂内部必须调用 reserved_provider.provider_configured。

    若有人把工厂改成自己 getattr 判空（第二把尺子，语义漂移的分岔口），AST 当场红。
    """
    src = _FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "provider_configured"
    ]
    assert calls, "工厂未调用 reserved_provider.provider_configured＝自立第二把已配尺子"


# ---------------------------------------------------------------------------
# 臂一：配了 provider（注入式注册表）⇒ 工厂出适配器；拼 handle ⇒ 结果件契约对象
# ---------------------------------------------------------------------------


def test_registered_selector_dispatches_provider_instance() -> None:
    config = SimpleNamespace(bot_creation_image_provider=" Test-Offline ")  # 归一：strip+casefold
    registry = {"test-offline": lambda cfg: _NonMockProvider()}
    sel = pf.build_image_provider(config, registry=registry)
    assert sel.state == "wired"
    assert isinstance(sel.provider, _NonMockProvider)
    assert "bot_creation_image_provider" in sel.reason


def test_configured_arm_produces_job_contract_object() -> None:
    """简报臂一：「配了 provider ⇒ 出结果件契约对象」两节真身拼链（口径见模块 docstring）。"""
    cp = _cp()
    config = SimpleNamespace(bot_creation_image_provider="test-offline")
    sel = pf.build_image_provider(config, registry={"test-offline": lambda cfg: _NonMockProvider()})
    assert sel.state == "wired" and sel.provider is not None

    result = ep.handle(_request(cp, job=_job(), config=config, provider=sel.provider))
    assert result.status is cp.InvocationStatus.OK
    assert result.via == "creation_image_engine"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict)
    # 「结果件契约对象」按契约**回读**验证，不是看个 dict 形状就放行。
    job_dto = common.CreationJob.model_validate(presented)
    assert job_dto.state is common.CreationJobState.SUCCEEDED
    assert job_dto.job_id  # mock 替身的 operation 身份透传


def test_unconfigured_arm_handle_returns_unavailable() -> None:
    """简报臂二：「没配 ⇒ UNAVAILABLE」——经中央 handler 真跑（无注入、键为空）。"""
    cp = _cp()
    config = SimpleNamespace(bot_creation_image_provider="")
    result = ep.handle(_request(cp, job=_job(), config=config))
    assert result.status is cp.InvocationStatus.UNAVAILABLE
    err = result.data.get(cp.INVOKER_ERROR_DATA_KEY)
    assert isinstance(err, ep.CreationImageNotWired)
    assert "bot_creation_image_provider" in result.detail  # 待配键点名（可操作）


def test_production_selection_chain_delegates_to_factory(monkeypatch) -> None:
    """S69 接线（S49 §5 残项落地）：键配了，生产选择链**现委派工厂**。

    两半各钉一条，避免"看着接线其实永不生效"或"接线把工厂拆了迁就旧断言"两种假账：
    ① 工厂给不出适配器（今天实况：注册表空）⇒ select 仍 None ⇒ handler 诚实 UNAVAILABLE；
    ② 工厂真派发 wired ⇒ select 把该适配器交回 handle ⇒ 能进执行面。
    """
    cp = _cp()
    config = SimpleNamespace(bot_creation_image_provider="test-offline")
    assert rprov.provider_configured(config, "creation.image") is True  # 键"已配"

    # ① 默认空注册表：工厂 unknown_provider ⇒ select None（填了键但无适配器仍诚实缺位）。
    request = cp.CapabilityRequest(capability_id="creation.image.generate", context={"config": config})
    assert ep.select_image_provider(config, request) is None

    # ② 工厂派发 wired：select 必须把适配器交回（证明它真的引用了工厂，而非永远 None）。
    wired = pf.ImageProviderSelection(_NonMockProvider(), "wired", "已接线（测试替身）")
    monkeypatch.setattr(pf, "build_image_provider", lambda cfg, **kw: wired)
    assert ep.select_image_provider(config, request) is wired.provider


def test_selection_chain_never_leaks_offline_mock_via_factory(monkeypatch) -> None:
    """铁律 3 的选择链侧牙：即便有人把 mock 伪装成 wired 结果塞回工厂，选择链仍不返回它。

    工厂本体的 mock 闸由 ``test_factory_never_hands_out_offline_mock`` 钉；本例钉的是
    select 这一环**只认 provider 非空**，而 wired+mock 违反工厂构造期不变量（造不出来），
    故 select 永不可能经工厂拿到 mock。注毒把 select 改成"返回 selection 里的任何东西"
    也拿不到 mock——这里断言的是"经工厂这条路 mock 不泄漏"。
    """
    cp = _cp()
    config = SimpleNamespace(bot_creation_image_provider="mock-image")
    request = cp.CapabilityRequest(capability_id="creation.image.generate", context={"config": config})
    # 用真实工厂 + 注入含 mock 的注册表：工厂判 mock_rejected（provider=None）⇒ select None。
    sel = pf.build_image_provider(config, registry={"mock-image": lambda cfg: ep.MockImageProvider()})
    assert sel.state == "mock_rejected" and sel.provider is None
    assert ep.select_image_provider(config, request) is None


# ---------------------------------------------------------------------------
# 缺位面加固：构造失败 / mock 判别闸 / 协议不合
# ---------------------------------------------------------------------------


def test_constructor_failure_is_honest_and_bare() -> None:
    def _boom(cfg: Any) -> Any:
        raise RuntimeError("secret-ish value must not leak: BOT_XXX=sk-dummy")

    sel = pf.build_image_provider(
        SimpleNamespace(bot_creation_image_provider="boom"), registry={"boom": _boom}
    )
    assert sel.provider is None
    assert sel.state == "constructor_failed"
    assert "RuntimeError" in sel.reason
    # 异常原文不得进理由串（防把配置值/密钥形态外带）。
    assert "sk-dummy" not in sel.reason


def test_factory_never_hands_out_offline_mock() -> None:
    """S09 铁律 3 的工厂侧牙锁：mock 进了注册表也照拒（注毒点①的常驻形态）。"""
    sel = pf.build_image_provider(
        SimpleNamespace(bot_creation_image_provider="mock-image"),
        registry={"mock-image": lambda cfg: ep.MockImageProvider()},
    )
    assert sel.provider is None
    assert sel.state == "mock_rejected"
    assert "铁律" in sel.reason or "注入" in sel.reason


def test_protocol_mismatch_is_rejected() -> None:
    sel = pf.build_image_provider(
        SimpleNamespace(bot_creation_image_provider="duck"),
        registry={"duck": lambda cfg: SimpleNamespace(offline_mock=False)},
    )
    assert sel.provider is None
    assert sel.state == "protocol_mismatch"
    assert "ImageProvider" in sel.reason


def test_selection_invariant_rejects_wired_without_provider() -> None:
    """构造期不变量：wired 无 provider / 未接线带 provider / 空理由，三型假账都造不出来。"""
    with pytest.raises(ValueError):
        pf.ImageProviderSelection(provider=None, state="wired", reason="x")
    fake = _NonMockProvider()
    with pytest.raises(ValueError):
        pf.ImageProviderSelection(provider=fake, state="unknown_provider", reason="x")
    with pytest.raises(ValueError):
        pf.ImageProviderSelection(provider=None, state="not_configured", reason="   ")


# ---------------------------------------------------------------------------
# 纪律锁：零第二真身数值、依赖方向、模块期零副作用
# ---------------------------------------------------------------------------


def test_factory_does_not_rehash_or_copy_hard_caps() -> None:
    src = _FACTORY_PATH.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "hashlib" for a in node.names
        ):
            raise AssertionError("工厂 import hashlib＝第二套摘要算法家（Wave G/H 契约层已有一处）")
        if isinstance(node, ast.Attribute) and node.attr == "sha256":
            raise AssertionError("工厂手抄 sha256 调用")
    # 硬顶数值抄写锁：IMAGE_MAX_* 常量族的字面量值不得在工厂重现（4000/2000/50 一族）。
    for literal in ast.walk(ast.parse(src)):
        if isinstance(literal, ast.Constant) and literal.value in (4000, 2000):
            raise AssertionError("工厂抄写 prompt/negative 硬顶字面量＝第二真身")


def test_factory_module_time_imports_stay_domain_pure() -> None:
    """模块期依赖纪律：顶层只准 stdlib/typing；中央层与兄弟执行体一律函数体内延迟 import。"""
    tree = ast.parse(_FACTORY_PATH.read_text(encoding="utf-8"))
    stdlib_from = {"__future__", "collections.abc", "dataclasses", "types", "typing"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
            assert roots <= {"typing", "types"}, roots
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                assert node.module in stdlib_from, node.module
                continue
            # 相对导入只准藏在 TYPE_CHECKING 守卫里（engine_provider 仅注解引用）
            assert node.module == "engine_provider" and node.level == 1
            guarded = any(
                isinstance(t, ast.If)
                and isinstance(t.test, ast.Name)
                and t.test.id == "TYPE_CHECKING"
                and any(sub is node for sub in t.body)
                for t in tree.body
            )
            assert guarded, "工厂在模块期真实 import 了兄弟执行体（依赖面提前绑死）"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or ""
            names = [str(a.name) for a in node.names]
            assert "capability_protocols" not in mod and not any(
                "capability_protocols" in n for n in names
            ), "工厂 import 中央层＝依赖方向反转（域→中央只准经执行体回调，不准成边）"
