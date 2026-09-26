"""S09：creation.image.generate 协议八段补全的离线验收（零网络 / 零真实出图）。

覆盖本席五件落码：①参考图 ``weight``（值域+校验）；②溯源 DTO ``CreationProvenance``
（含 ``ImageAssetRecord.provenance`` 旁车位）；③进度事件"只支持轮询、SSE 未接"的明确
声明（不留死字母）；④ ``ImageProvider`` 适配器协议 + ``MockImageProvider`` + 装配选择
fail-closed；⑤缺位可见（未接 provider 经 ``INVOKER_ERROR_DATA_KEY`` 交回层 1）。

两枚注毒自证锁（摘掉实现即红）：
- ``test_provenance_exif_crosscheck_lock_has_teeth``（①provenance 摘掉仍要红）
- ``test_mock_provider_is_never_billed_as_real``（②mock 被当真实 provider 记账要红）
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pydantic
import pytest

from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
from plugins.bot_unified_runtime.domains.creation._common import contracts as common
from plugins.bot_unified_runtime.domains.creation.image import contracts as cimage
from plugins.bot_unified_runtime.domains.creation.image import engine_provider as ep

_CREATION_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "creation"
)
_MOCK_DIGEST = "0" * 64


def _cp():
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols as cp
    except Exception as exc:  # noqa: BLE001 - 只拦他席在飞把中央装配改崩
        pytest.skip(f"中央 capability_protocols 当前不可导入（他席在飞，非本席面）: {exc}")
    return cp


def _job(**overrides: object) -> cimage.ImageJobRequest:
    payload: dict[str, object] = {
        "task": "text_to_image",
        "prompt": "釉瑚风格的云母卡片插画",
        "provider": "mock-image",
        "model": "image-model-1",
        "size": "1024x1024",
        "workspace_id": "ws_main",
        "version": "rev-1",
    }
    payload.update(overrides)
    return cimage.ImageJobRequest(**payload)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> common.CreationProvenance:
    payload: dict[str, object] = {
        "generator_principal": "user:3865067623",
        "provider": "provider_a",
        "model": "image-model-1",
        "prompt_digest": _MOCK_DIGEST,
        "generated_at": datetime(2026, 9, 24, tzinfo=timezone.utc),
        "license_statement": "可商用（示例）",
        "exif_stripped": True,
    }
    payload.update(overrides)
    return common.CreationProvenance(**payload)  # type: ignore[arg-type]


def _asset(**overrides: object) -> cimage.ImageAssetRecord:
    payload: dict[str, object] = {
        "asset_id": {"asset_id": "asset-2"},
        "width": 1024,
        "height": 1024,
        "real_mime": "image/png",
        "bytes_size": 20480,
        "magic_verified": True,
        "exif_sanitized": True,
        "review_approved": True,
    }
    payload.update(overrides)
    return cimage.ImageAssetRecord(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 参考图权重
# ---------------------------------------------------------------------------


def test_reference_weight_defaults_none_and_respects_range() -> None:
    ref = common.AssetRef(asset_id="in-1")
    assert ref.weight is None  # 不给权重＝沿用 provider 缺省，绝不猜强度
    assert common.AssetRef(asset_id="in-1", weight=0.0).weight == 0.0
    assert common.AssetRef(asset_id="in-1", weight=1.0).weight == 1.0


@pytest.mark.parametrize("bad", [-0.01, 1.01, 5.0])
def test_reference_weight_out_of_range_is_rejected(bad: float) -> None:
    with pytest.raises(pydantic.ValidationError):
        common.AssetRef(asset_id="in-1", weight=bad)


def test_reference_weight_is_nan_inf_free() -> None:
    # 基类 allow_inf_nan=False：权重不得为 NaN/Inf（否则"强度"是哑值却像已配置）。
    with pytest.raises(pydantic.ValidationError):
        common.AssetRef(asset_id="in-1", weight=float("nan"))


def test_weight_is_part_of_request_identity() -> None:
    """改权重＝改请求身份：嵌套进 preimage，两条形同而权重异的请求不得互撞幂等。"""
    a = _job(task="image_to_image", assets=({"asset_id": "in-1", "weight": 0.3},))
    b = _job(task="image_to_image", assets=({"asset_id": "in-1", "weight": 0.9},))
    assert common.idempotency_preimage(a) != common.idempotency_preimage(b)


# ---------------------------------------------------------------------------
# ② 溯源位（含旁车补回 EXIF 语义 + 注毒锁①）
# ---------------------------------------------------------------------------


def test_provenance_prompt_digest_rejects_raw_prompt() -> None:
    # 原文塞不进 64-hex 形态：无论 pattern 还是显式校验，整句提示词一律被拒。
    with pytest.raises(pydantic.ValidationError):
        _provenance(prompt_digest="釉瑚风格的云母卡片插画")


def test_provenance_generated_at_must_be_aware_utc() -> None:
    with pytest.raises(pydantic.ValidationError):
        _provenance(generated_at=datetime(2026, 9, 24))  # noqa: DTZ001 - 故意造 naive，验被拒


def test_provenance_slot_present_on_asset_and_optional() -> None:
    assert "provenance" in cimage.ImageAssetRecord.model_fields
    assert _asset().provenance is None  # 预留态如实"无溯源可报"


def test_provenance_exif_crosscheck_lock_has_teeth() -> None:
    """注毒锁①（provenance 摘掉/放松即红）：嵌入剥净与来源声明必须一致。

    现网 ``exif_sanitized`` 强制 True＝EXIF 已剥；若溯源却标 ``exif_stripped=False``
    （即"来源还在嵌入里"），自相矛盾，必须被拒。删掉 _gates 里那条交叉校验 → 本例转绿=假绿，
    故它反过来正是"摘掉仍要红"的判据。
    """
    with pytest.raises(pydantic.ValidationError):
        _asset(provenance=_provenance(exif_stripped=False))
    # 一致形态放行（证明不是恒拒的假锁）。
    assert _asset(provenance=_provenance(exif_stripped=True)).provenance is not None


# ---------------------------------------------------------------------------
# ③ 进度事件：只支持轮询、SSE 未接、不留死字母
# ---------------------------------------------------------------------------


def test_progress_declares_poll_only_and_sse_not_wired() -> None:
    assert cimage.IMAGE_PROGRESS_TRANSPORT == "poll"
    assert cimage.IMAGE_PROGRESS_SSE_WIRED is False


def test_no_dead_sse_route_left_in_rest_surface() -> None:
    """不许留死字母：路由表里既无 SSE 路由，也不得有未实现的 events/stream 端点。"""
    paths = [path for _m, path in cimage.IMAGE_REST_ROUTES]
    assert not any(tok in p for p in paths for tok in ("sse", "events", "stream"))
    assert any("{id}" in p for p in paths)  # 轮询位在场


# ---------------------------------------------------------------------------
# ④ provider 协议 + mock + 选择 fail-closed
# ---------------------------------------------------------------------------


def test_mock_provider_satisfies_protocol_and_is_offline() -> None:
    mock = ep.MockImageProvider()
    assert isinstance(mock, ep.ImageProvider)
    assert mock.offline_mock is True


def test_mock_provider_is_deterministic() -> None:
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = _job()
    a = ep.MockImageProvider(principal="p", clock=fixed)
    b = ep.MockImageProvider(principal="p", clock=fixed)
    pa = a.poll(a.submit(job)).assets
    pb = b.poll(b.submit(job)).assets
    assert len(pa) == 1 and len(pb) == 1
    assert pa[0].model_dump(mode="json") == pb[0].model_dump(mode="json")


def test_mock_provider_cancel_moves_to_cancelled() -> None:
    mock = ep.MockImageProvider()
    op = mock.submit(_job())
    assert mock.cancel(op) is True
    assert mock.poll(op).state is common.CreationJobState.CANCELLED


def test_select_provider_is_fail_closed_without_config_or_injection() -> None:
    cp = _cp()
    req = cp.CapabilityRequest(capability_id="creation.image.generate", context={"config": SimpleNamespace()})
    # 未注入 provider 且"未来键"未配 → 一律 None（绝不返回 mock、绝不猜有 provider）。
    assert ep.select_image_provider(SimpleNamespace(), req) is None
    assert rprov.provider_configured(SimpleNamespace(), "creation.image") is False


def test_engine_provider_does_not_rehash_or_import_digest() -> None:
    src = (_CREATION_DIR / "image" / "engine_provider.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "hashlib" for a in node.names
        ):
            raise AssertionError("本件在域内 import hashlib＝第二套摘要算法家")
        if isinstance(node, ast.Attribute) and node.attr == "sha256":
            raise AssertionError("本件手抄 sha256 调用")


# ---------------------------------------------------------------------------
# ⑤ handle 终态 + 缺位可见 + 注毒锁②
# ---------------------------------------------------------------------------


def _request(cp_module, *, job, config=None, provider=...) -> object:
    context: dict[str, object] = {"config": config if config is not None else SimpleNamespace()}
    if provider is not ...:
        context["image_provider"] = provider
    return cp_module.CapabilityRequest(
        capability_id="creation.image.generate",
        payload={"job": job},
        context=context,
    )


def test_handle_contract_failure_is_failed() -> None:
    cp = _cp()
    result = ep.handle(_request(cp, job={"task": "text_to_image"}))
    assert result.status is cp.InvocationStatus.FAILED
    assert result.via == "creation_image_contract"


def test_handle_unwired_returns_unavailable_and_carries_card_error() -> None:
    """E5 缺位可见：未接 provider → UNAVAILABLE，且 INVOKER_ERROR_DATA_KEY 带异常交回层 1。"""
    cp = _cp()
    result = ep.handle(_request(cp, job=_job()))
    assert result.status is cp.InvocationStatus.UNAVAILABLE
    assert "绘图对接点未接线" in result.detail
    err = result.data.get(cp.INVOKER_ERROR_DATA_KEY)
    assert isinstance(err, BaseException)  # 层 1 _step 见 BaseException 即 raise → 诊断卡
    assert isinstance(err, ep.CreationImageNotWired)


def test_handle_caps_mismatch_is_limit_exceeded_without_submit() -> None:
    cp = _cp()

    class _NoSquareProvider(ep.MockImageProvider):
        def capabilities(self):  # 只支持 512x512
            from plugins.bot_unified_runtime.domains.creation.image.contracts import (
                ImageProviderCapabilities,
            )

            return ImageProviderCapabilities(
                provider="mock-image",
                max_steps=50,
                sizes=("512x512",),
                supported_tasks=("text_to_image",),
            )

    before = _NoSquareProvider()._seq
    result = ep.handle(_request(cp, job=_job(size="1024x1024"), provider=_NoSquareProvider()))
    assert result.status is cp.InvocationStatus.LIMIT_EXCEEDED
    assert result.via == "creation_image_caps"
    assert before == 0  # 能力交集不过：一次都不提交


def test_mock_provider_is_never_billed_as_real() -> None:
    """注毒锁②：注入的离线 mock 必须记 DEGRADED/via 含 offline，绝不冒充真实成功。

    若有人删掉 handle 里的 ``offline_mock`` 判定、让 mock 直接产 OK/真实计费终态 →
    本例（status==DEGRADED 且 via 含 offline）当场红。
    """
    cp = _cp()
    result = ep.handle(_request(cp, job=_job(), provider=ep.MockImageProvider()))
    assert result.status is cp.InvocationStatus.DEGRADED
    assert "offline" in result.via
    # DEGRADED 不得携带呈现载荷（信封不变量）；mock 快照只走独立普通键。
    assert cp.PRESENTATION_DATA_KEY not in result.data
    snapshot = result.data.get(ep._MOCK_RESULT_DATA_KEY)
    assert isinstance(snapshot, dict)
    assert snapshot["state"] == "succeeded"  # 协议确实跑通了，只是记账面诚实降级


def test_real_provider_success_maps_to_ok() -> None:
    """真实（非 mock）provider 成功 → OK：证明协议腿对真实现是可消费的（生产入口另归控制面）。"""
    cp = _cp()

    class _RealProvider(ep.MockImageProvider):
        @property
        def offline_mock(self) -> bool:
            return False

    result = ep.handle(_request(cp, job=_job(), provider=_RealProvider()))
    assert result.status is cp.InvocationStatus.OK
    assert result.via == "creation_image_engine"


# ---------------------------------------------------------------------------
# 纪律：本件不得被误叙述为"已接生产"
# ---------------------------------------------------------------------------


def test_module_header_declares_production_not_wired() -> None:
    doc = ep.__doc__ or ""
    # 头注必须诚实说"今天出不了图"，且判据要贴真码：键**已在 config.py 登记**（缺省空串）、
    # 缺位的真因是 PROVIDER_REGISTRY 为空（无真实适配器）⇒ 恒 UNAVAILABLE——不是旧叙述说的
    # "键不存在于 config.py"（S69 现算更正：那句已被 config.py:465 打脸，属"未做写成做"的反向
    # 假叙述：把"键没落地"当成缺位理由，掩盖了"键在但没适配器"的真实断层）。
    assert "PROVIDER_REGISTRY" in doc and "UNAVAILABLE" in doc
    assert "已在 ``config.py`` 登记" in doc
    # 绝不冒充已接生产：出现"生产可用/已可出图/重启即出图"式断言即红。
    assert "生产可用" not in doc and "已可出图" not in doc and "重启即出图" not in doc
