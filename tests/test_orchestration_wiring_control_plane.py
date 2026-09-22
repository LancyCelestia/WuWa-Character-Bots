"""S-CP 席判定锚：control_plane/api/platform.py 三族直呼（files.read / media.vision /
media.asr）**翻点=0（全不等值）**，本件用一手实跑钉死四处 platform 特有分叉，供主会话据以补中央件后重估。

与 SEAT-S-WIRE-CHAT（chat.py）同哲学但**根因不同**：chat 的决定性障碍是 provider 身份
（root 装配带 dynamic_registry/settings_store、中央重建省略）；**platform 不受此障**——
platform 自己就单参 `build_vision_provider(config)`/`build_asr_provider(config)`（:398/:412/:427），
与中央 handler（capability_protocols.py:810/847/936）同一退化形态。platform 真正撞上的：
①中央权限门把控制面 Principal（roles=("admin",)/("super_admin","admin")）对 required_roles=("user",)
的**朴素 set 交集**判空 → DENIED（直呼无路）；②标量来源分叉（platform 吃 describe_images/transcribe_audio
模块默认 2/500/20/300，中央吃 config，非缺省时截断不同）；③SSRF/限额/NOT_CONFIGURED 前置拦截是平台
只读端点的**新语义**；④状态→HTTP 重映射破坏既有 `/api/v1` 响应契约（missing→404、任意 kind、path 键）。

全离线：中央 handler 真跑，仅在真身边界 monkeypatch IO 叶子（build_*_provider / describe_images /
transcribe_audio / read_supported_file）作**入参记录仪**，绝不用返回值拼两路相等（那是 W1B §五-2 定罪的假绿）。
判据复用 v1 门 `scan`/`check_invariants`（import，不复制）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# 复用（不复制）v1 门的纯扫描判据与在册 ledger——§7 禁第二套判据。
import test_orchestration_callsite_single as v1gate

_PLATFORM_SRC = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "control_plane"
    / "api"
    / "platform.py"
)

_VISION_MODULE = "plugins.bot_unified_runtime.domains.media.ingest.vision_describe"
_TRANSCRIBE_MODULE = "plugins.bot_unified_runtime.domains.media.ingest.transcribe"
_FILEREADER_MODULE = "plugins.bot_unified_runtime.domains.files.sources.file_reader"


def _central_invoke(cid: str, payload: dict[str, Any], *, roles=("user",), config: Any = None):
    """真跑中央 handler（经 default_invoker），返回 InvocationResult。"""
    import importlib

    cp = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    cp.default_invoker()  # 触发 descriptor→_DESCRIPTOR_VIEW 回填
    request = cp.CapabilityRequest(
        capability_id=cid,
        payload=payload,
        principal="bearer-admin",
        roles=tuple(roles),
        context={"config": config} if config is not None else {},
    )
    return cp.default_invoker().invoke(request), cp


# ---------------------------------------------------------------------------
# ① 中央权限门对控制面 Principal 判空 → DENIED（platform 直呼面根本没有这道门）
# ---------------------------------------------------------------------------
def test_control_plane_admin_principal_passes_user_floor_gate() -> None:
    """C-CP-1 已由中央根修（2026-09-21）：权限门改走 **ROLE_ORDER 层级最低门槛**。

    本席首稿把「admin∩(user,)=∅ → DENIED」当成翻点障碍记录；主会话判定那是
    **权限门反装**（平坦求交会把管理员挡在自己的能力外，角色模型是叠加式），
    已改 `roles_satisfy` 而非让 platform 伪造 roles=("user",)。本用例即该根修的回归锁。
    """
    for admin_roles in (("admin",), ("super_admin", "admin")):
        result, _cp = _central_invoke(
            "media.vision.image",
            {"image_urls": ["data:image/png;base64,AAAA"], "query_text": "x"},
            roles=admin_roles,
        )
        assert result.status.value != "denied", (admin_roles, result.status)
    # 反向锁：blocked 主体仍无条件拒（层级修复不得顺手放宽这一条）。
    blocked, _ = _central_invoke(
        "media.vision.image",
        {"image_urls": ["data:image/png;base64,AAAA"]},
        roles=("blocked",),
        config=SimpleNamespace(),
    )
    assert blocked.status.value == "denied", blocked.status
    # 对照：显式 roles=("user",) 同样过门（层级修复后不再是"必须把真实 Principal 降级"）。
    passed_gate, _ = _central_invoke(
        "media.vision.image",
        {"image_urls": ["data:image/png;base64,AAAA"]},
        roles=("user",),
        config=SimpleNamespace(),  # provider 走 build→None→NOT_CONFIGURED，但至少证明已过权限门
    )
    assert passed_gate.status.value != "denied"


# ---------------------------------------------------------------------------
# ② media.vision：SSRF 是新增拦截面（platform 现对 http 图 URL 直入 describe_images）
# ---------------------------------------------------------------------------
def test_media_vision_ssrf_is_new_interception(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    seen: list[tuple] = []
    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg: object())
    monkeypatch.setattr(
        vision,
        "describe_images",
        lambda provider, **kw: seen.append(kw) or "should-not-run",
    )
    result, _ = _central_invoke(
        "media.vision.image",
        {"image_urls": ["http://127.0.0.1/secret.png"], "query_text": "x"},
        roles=("user",),
        config=SimpleNamespace(),
    )
    # 中央：SSRF 前置于 describe_images，内网 http URL 直接 FAILED、真身零调用。
    assert result.status.value == "failed", result.status
    assert result.via == "ssrf_guard"
    assert seen == [], "中央 handler 竟在 SSRF 前调了 describe_images"
    # platform 现契约：analyze_media 对 image_urls 无任何 SSRF 门（源码只 import describe_images
    # 后直送），翻点即新增此拦截 = 行为变更（C-CP-3）。
    assert "ssrf" not in _PLATFORM_SRC.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# ③ 标量来源分叉：中央传 config 值，platform 不传（吃函数默认）
# ---------------------------------------------------------------------------
def test_media_vision_scalar_source_divergence(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    seen: dict[str, Any] = {}

    def _rec(provider, **kw):
        seen.update(kw)
        return "TEXT"

    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg: object())
    monkeypatch.setattr(vision, "describe_images", _rec)
    cfg = SimpleNamespace(bot_vision_max_images=4, bot_vision_max_chars=2000)
    _result, _ = _central_invoke(
        "media.vision.image",
        {"image_urls": ["data:image/png;base64,AAAA"], "query_text": "你好"},
        roles=("user",),
        config=cfg,
    )
    # 中央 handler 用 config 值喂真身。
    assert seen["max_images"] == 4
    assert seen["max_chars"] == 2000
    # platform 直呼**不传** max_images/max_chars → 真身吃模块默认 2/500（describe_images 签名），
    # config≠缺省时两路截断/取图数不同 → 不等值。
    platform_kwargs = _call_kwargs_of("describe_images", _PLATFORM_SRC)
    assert "max_images" not in platform_kwargs and "max_chars" not in platform_kwargs, (
        f"platform 直呼应不传标量（吃默认 2/500），实得 {platform_kwargs}"
    )


def test_media_asr_scalar_source_divergence(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    transcribe = importlib.import_module(_TRANSCRIBE_MODULE)
    seen: dict[str, Any] = {}

    def _rec(provider, **kw):
        seen.update(kw)
        return "ASR"

    monkeypatch.setattr(transcribe, "build_asr_provider", lambda cfg: object())
    monkeypatch.setattr(transcribe, "transcribe_audio", _rec)
    cfg = SimpleNamespace(bot_asr_timeout_seconds=45.0, bot_asr_max_chars=1000)
    _result, _ = _central_invoke(
        "media.asr.speech",
        {"audio_source": "data:audio/wav;base64,AAAA"},
        roles=("user",),
        config=cfg,
    )
    assert seen["timeout_seconds"] == 45.0
    assert seen["max_chars"] == 1000
    platform_kwargs = _call_kwargs_of("transcribe_audio", _PLATFORM_SRC)
    assert "timeout_seconds" not in platform_kwargs and "max_chars" not in platform_kwargs, (
        f"platform 直呼 audio 不传 timeout/max_chars（吃默认 20/300），实得 {platform_kwargs}"
    )


# ---------------------------------------------------------------------------
# ④ platform 源码 AST 佐证：直呼调用点确实不带那些标量关键字
# ---------------------------------------------------------------------------
def _call_kwargs_of(symbol: str, src_path: Path) -> set[str]:
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            hit = (isinstance(fn, ast.Name) and fn.id == symbol) or (
                isinstance(fn, ast.Attribute) and fn.attr == symbol
            )
            if hit:
                names.update(k.arg for k in node.keywords if k.arg)
    return names


# ---------------------------------------------------------------------------
# ⑤ NOT_CONFIGURED 是新增可观测终态（platform 现 describe_images(None)→""→200 "unknown"）
# ---------------------------------------------------------------------------
def test_provider_none_maps_differently(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    vision = importlib.import_module(_VISION_MODULE)
    monkeypatch.setattr(vision, "build_vision_provider", lambda cfg: None)
    # describe_images 仍为真身（不 mock）：证 provider None 时真身返回 ""（平台当前 200 "unknown" 的来源）。
    assert vision.describe_images(None, image_urls=["data:image/png;base64,AAAA"]) == ""
    result, _ = _central_invoke(
        "media.vision.image",
        {"image_urls": ["data:image/png;base64,AAAA"]},
        roles=("user",),
        config=SimpleNamespace(),
    )
    # 中央：provider None → NOT_CONFIGURED（诚实态），端点若要维持既有 HTTP 形态需显式映射（C-CP-3）。
    assert result.status.value == "not_configured", result.status


# ---------------------------------------------------------------------------
# ⑥ files.read：无通用 any-kind 成员 + missing→FAILED(非404) + 任意 kind 与 expected_kinds 冲突
# ---------------------------------------------------------------------------
def test_files_read_has_no_generic_any_kind_member() -> None:
    import importlib

    cp = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    cp.default_invoker()
    members = {cid for cid in cp._DESCRIPTOR_VIEW if cid.startswith("files.read")}
    assert "files.read.any" not in members
    # platform `/files/read` 收**任意**受支持 kind（现按 result.kind 原样回报），
    # 而成员按 expected_kinds 拆分：用 code 成员读 pdf-kind 结果 → 中央判 FAILED(kind 不匹配)。
    assert members, members


def test_files_read_kind_mismatch_is_failed_not_200(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    filereader = importlib.import_module(_FILEREADER_MODULE)
    parsed = SimpleNamespace(
        kind="pdf", title="doc", text="hello", path=Path("/tmp/doc.pdf"), metadata={}
    )
    monkeypatch.setattr(
        filereader, "read_supported_file", lambda p, **kw: parsed
    )
    result, _ = _central_invoke(
        "files.read.code", {"path": "/tmp/doc.pdf"}, roles=("user",)
    )
    # 中央 code 成员 expected_kinds=("code","text")；pdf → FAILED。
    assert result.status.value == "failed", result.status
    # platform 现契约：read_supported_file 返回任意 kind，只要 kind∉{missing,unknown} 即 200 + path 键。
    assert "path" not in (result.data or {}), "中央 data 不带 path，platform envelope 带 path → 端点需重组"


def test_files_read_blocked_principal_denied_admin_passes() -> None:
    """中央权限门：blocked 无条件拒；admin 满足 user 低门槛（层级语义回归锁）。"""
    admin, _ = _central_invoke("files.read.code", {"path": "/tmp/a.py"}, roles=("admin",))
    assert admin.status.value != "denied", admin.status
    blocked, _ = _central_invoke("files.read.code", {"path": "/tmp/a.py"}, roles=("blocked",))
    assert blocked.status.value == "denied", blocked.status


# ---------------------------------------------------------------------------
# ⑦ 复用 v1 门 scan/check_invariants：证明「半迁移 / 通电却仍直呼 / 第二调用点」对 platform 真会红
# ---------------------------------------------------------------------------
def _poison_platform(src: str) -> dict[str, str]:
    return {"control_plane/api/platform.py": src}


def test_poison_half_migration_on_platform_is_red() -> None:
    src = (
        "from ...sources.vision_describe import describe_images\n"
        "def f():\n"
        "    describe_images(None, image_urls=['x'])\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='media.vision.image'))\n"
    )
    direct, invoker = v1gate.scan(_poison_platform(src))
    v = v1gate.check_invariants(
        direct, invoker, wired=v1gate.WIRED, allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST
    )
    assert any("半迁移" in s and "media.vision" in s for s in v), v


def test_poison_wired_but_still_direct_on_platform_is_red() -> None:
    # 假设 media.vision 已通电（WIRED）却 platform 仍直呼 describe_images → 必红。
    src = "from ...sources.vision_describe import describe_images\ndef f():\n    return describe_images(None, image_urls=['x'])\n"
    direct, invoker = v1gate.scan(_poison_platform(src))
    v = v1gate.check_invariants(
        direct, invoker, wired=set(v1gate.WIRED) | {"media.vision"},
        allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST,
    )
    assert any("已通电却仍直呼" in s and "media.vision" in s for s in v), v


def test_poison_second_asr_invoker_site_is_red() -> None:
    src = (
        "def f():\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='media.asr.speech'))\n"
    )
    direct, invoker = v1gate.scan({"control_plane/api/platform.py": src, "domains/x.py": src})
    v = v1gate.check_invariants(
        direct, invoker, wired=v1gate.WIRED, allowlist=v1gate.KNOWN_DIRECT_ALLOWLIST
    )
    assert any("第二调用点" in s and "media.asr" in s for s in v), v
