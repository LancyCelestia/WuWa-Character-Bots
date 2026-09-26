"""v21r2 RWPA1 席：creation 生成域骨架门（§9.1 契约草案 + §9.3 注册面 + §9.4 门禁）。

合同来源（本文件是它们的机器可执行形态之一）：
- docs/design/v21r2-reorg-plan.md §9.1（TTS/绘图字段级 DTO 契约草案）、
  §9.3（注册表开放条目 + 四步接入）、§9.4（占位目录存在性 / reserved
  docstring / 契约形态 lint / 注册表一致性）
- docs/design/backend-v2-implementation-guide.md §6/§7/§10/§11
- docs/design/backend-v2-product-extensions.md §1
- 验收矩阵 V21-CORE-001（import 副作用探针纪律）、L51/L52（TTS/绘图预留态）

测试全部走 importlib 直载（fake 顶层包名 + 真实目录 __path__），不 import
plugins.bot_unified_runtime 真包——真包父级装配会拉起 nonebot，属父包现实，
与本域叶子纯净断言分离；真包现实由子进程探针如实记录（不冒充、不遮掩）。
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import ModuleType
from typing import Any
from unittest import mock

import pydantic
import pytest

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATION_DIR = os.path.join(
    WORKSPACE_ROOT, "plugins", "bot_unified_runtime", "domains", "creation"
)
VENV_PYTHON = os.path.join(
    os.path.dirname(WORKSPACE_ROOT), "ChatBot_Runtime", "venv", "Scripts", "python.exe"
)

FAKE_PKG = "v21_wpa1_creation"
PROBE_MARKER = "V21_WPA1_PROBE:"
FORBIDDEN_MODULE_PREFIXES = ("nonebot",)

#: §9.4 契约形态 lint：reserved 模块禁 import 的模块（零网络/零线程/零框架）。
FORBIDDEN_IMPORTS = frozenset(
    {
        "nonebot",
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        "socket",
        "threading",
        "subprocess",
        "asyncio",
        "concurrent",
        "sqlite3",
        "os",
        "pathlib",
        "path",
    }
)
FORBIDDEN_CALL_NAMES = frozenset({"open", "eval", "exec", "compile"})

#: §9.4 占位首行 docstring 规则：`^reserved:`。
RESERVED_PLACEHOLDER_INITS: tuple[str, ...] = (
    "__init__.py",
    "tts/__init__.py",
    "image/__init__.py",
    "extensions/__init__.py",
    "_common/__init__.py",
)


# ---------------------------------------------------------------------------
# 直载基础设施（fake 顶层包 + 真实目录 __path__，相对导入照常解析）
# ---------------------------------------------------------------------------


def _ensure_fake_root() -> ModuleType:
    """sys.modules 里先备好 fake 顶层包壳（不执行域根 __init__）。

    相对导入（`from .._common.contracts import ...`）经 import 机制解析时需要
    顶层包在 sys.modules 且带 __path__；壳不执行根 __init__，保证各叶子契约
    模块可被探针独立直载。
    """
    root = sys.modules.get(FAKE_PKG)
    if root is None:
        root = ModuleType(FAKE_PKG)
        root.__path__ = [CREATION_DIR]  # type: ignore[attr-defined]
        sys.modules[FAKE_PKG] = root
    return root


def _load_module(rel: str) -> ModuleType:
    """直载 creation 域模块；rel="" 表示域根 __init__。带缓存。"""
    parts = rel.split(".") if rel else []
    if not parts:
        name = FAKE_PKG
        cached = sys.modules.get(name)
        if cached is not None and getattr(cached, "__spec__", None) is not None:
            return cached
        spec = importlib.util.spec_from_file_location(
            name,
            os.path.join(CREATION_DIR, "__init__.py"),
            submodule_search_locations=[CREATION_DIR],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    _ensure_fake_root()
    name = f"{FAKE_PKG}.{rel}"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    target = os.path.join(CREATION_DIR, *parts)
    if os.path.isdir(target):
        file = os.path.join(target, "__init__.py")
        spec = importlib.util.spec_from_file_location(
            name, file, submodule_search_locations=[target]
        )
    else:
        file = target + ".py"
        spec = importlib.util.spec_from_file_location(name, file)
    assert spec is not None and spec.loader is not None, f"无法构造 spec: {rel}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _probe_load(rel: str) -> ModuleType:
    """带副作用探针的直载：零 nonebot 拉起、零线程、零 socket、零 open。"""
    before = set(sys.modules)
    before_threads = threading.active_count()

    real_thread = threading.Thread
    created: list[threading.Thread] = []

    def spy_thread(*args: Any, **kwargs: Any) -> threading.Thread:
        thread = real_thread(*args, **kwargs)
        created.append(thread)
        raise AssertionError("reserved 契约模块禁止起线程")

    def spy_socket(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reserved 契约模块禁止网络调用")

    def spy_open(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reserved 契约模块禁止文件 I/O")

    with (
        mock.patch.object(threading, "Thread", spy_thread),
        mock.patch.object(socket, "socket", spy_socket),
        mock.patch.object(builtins, "open", spy_open),
    ):
        module = _load_module(rel)

    new_forbidden = [
        name for name in set(sys.modules) - before if name.startswith(FORBIDDEN_MODULE_PREFIXES)
    ]
    assert not new_forbidden, f"import 拉起了禁止模块: {new_forbidden}"
    assert threading.active_count() == before_threads, "import 改变了线程数"
    assert not created, "import 创建了线程"
    return module


def _common() -> ModuleType:
    return _probe_load("_common.contracts")


def _tts() -> ModuleType:
    return _probe_load("tts.contracts")


def _image() -> ModuleType:
    return _probe_load("image.contracts")


def _registry() -> ModuleType:
    return _probe_load("")


# ---------------------------------------------------------------------------
# §9.4 骨架存在性 + reserved docstring + 注册表一致性
# ---------------------------------------------------------------------------


def test_skeleton_directories_exist() -> None:
    for sub in ("tts", "image", "extensions", "_common"):
        assert os.path.isdir(os.path.join(CREATION_DIR, sub)), f"缺子包: {sub}"
    for mod in ("tts/contracts.py", "image/contracts.py", "_common/contracts.py"):
        assert os.path.isfile(os.path.join(CREATION_DIR, mod)), f"缺契约模块: {mod}"


@pytest.mark.parametrize("rel", RESERVED_PLACEHOLDER_INITS)
def test_placeholder_docstring_starts_with_reserved(rel: str) -> None:
    path = os.path.join(CREATION_DIR, rel)
    tree = ast.parse(open(path, encoding="utf-8").read())  # noqa: SIM115
    doc = ast.get_docstring(tree)
    assert doc is not None, f"{rel} 缺 docstring"
    assert doc.startswith("reserved:"), f"{rel} 首行 docstring 必须匹配 ^reserved:"
    assert "未实现" in doc, f"{rel} docstring 必须显式声明未实现"


def test_reserved_entries_match_placeholder_dirs() -> None:
    """§9.4 ④：注册表 dormant 条目与占位目录一一对应（防「目录在、册上无」）。"""
    registry_mod = _registry()
    registry = registry_mod.RESERVED_REGISTRY
    entries = {entry.stable_id: entry for entry in registry.entries()}
    assert set(entries) == {"creation.tts", "creation.image", "creation.extensions"}
    for stable_id, sub in (
        ("creation.tts", "tts"),
        ("creation.image", "image"),
        ("creation.extensions", "extensions"),
    ):
        entry = entries[stable_id]
        assert entry.gate_state == "dormant"
        assert entry.default_enabled is False
        assert os.path.isdir(os.path.join(CREATION_DIR, sub))


# ---------------------------------------------------------------------------
# §9.4 契约形态 lint（静态 AST：禁 import/禁危险调用）
# ---------------------------------------------------------------------------


def _iter_creation_sources() -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for root, _dirs, files in os.walk(CREATION_DIR):
        for fname in sorted(files):
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, CREATION_DIR)
                with open(fpath, encoding="utf-8") as handle:
                    sources.append((rel, handle.read()))
    return sources


def test_reserved_modules_forbidden_imports() -> None:
    for rel, source in _iter_creation_sources():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".")[0]
                    assert root_name not in FORBIDDEN_IMPORTS, (
                        f"{rel}: 禁止 import {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    continue  # 域内相对导入允许
                assert node.module is not None
                root_name = node.module.split(".")[0]
                assert root_name not in FORBIDDEN_IMPORTS, f"{rel}: 禁止 from {node.module}"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_CALL_NAMES, (
                    f"{rel}: 禁止调用 {node.func.id}()"
                )


def test_contract_modules_import_without_side_effects() -> None:
    """探针一直载：contracts 包 import 不拉 nonebot/不起线程/不建连接/不读文件。"""
    for rel in ("_common.contracts", "tts.contracts", "image.contracts", ""):
        _probe_load(rel)


def test_real_package_import_probe_subprocess() -> None:
    """探针二（子进程真实包路径）：相对导入在真实包上下文可解析；本域模块
    命名空间零禁止符号。父包（插件装配）可能拉起 nonebot 属父包现实，如实
    记录不遮掩（parent_nonebot 字段），不作为本域断言。"""
    if not os.path.isfile(VENV_PYTHON):
        pytest.skip(f"venv 解释器不存在: {VENV_PYTHON}")
    code = "\n".join(
        [
            "import json, sys",
            f"sys.path.insert(0, {WORKSPACE_ROOT!r})",
            "import plugins.bot_unified_runtime.domains.creation as creation",
            (
                "from plugins.bot_unified_runtime.domains.creation._common "
                "import contracts as common_c"
            ),
            "from plugins.bot_unified_runtime.domains.creation.tts import contracts as tts_c",
            (
                "from plugins.bot_unified_runtime.domains.creation.image "
                "import contracts as image_c"
            ),
            (
                "mods = [('creation', creation), ('common', common_c), "
                "('tts', tts_c), ('image', image_c)]"
            ),
            (
                "FORB = ('nonebot', 'httpx', 'requests', 'socket', 'threading', "
                "'subprocess', 'os', 'pathlib')"
            ),
            (
                "hits = sorted(m + '.' + k for m, mod in mods for k in vars(mod) "
                "if k.split('.')[0] in FORB)"
            ),
            (
                "print(" + repr(PROBE_MARKER) + " + json.dumps({"
                "'forbidden': hits, "
                "'entries': len(creation.RESERVED_REGISTRY.entries()), "
                "'parent_nonebot': 'nonebot' in sys.modules}))"
            ),
        ]
    )
    env = dict(os.environ)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "BOT_AUTOSYNC": "0"})
    proc = subprocess.run(
        [VENV_PYTHON, "-c", code],
        cwd=WORKSPACE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"真实包 import 失败:\n{proc.stderr[-2000:]}"
    payload_line = next(
        (line for line in proc.stdout.splitlines() if line.startswith(PROBE_MARKER)), None
    )
    assert payload_line is not None, f"探针无输出:\n{proc.stdout[-2000:]}"
    payload = json.loads(payload_line[len(PROBE_MARKER) :])
    assert payload["forbidden"] == [], f"本域模块命名空间出现禁止符号: {payload['forbidden']}"
    assert payload["entries"] == 3


# ---------------------------------------------------------------------------
# §9.1 共用件：任务状态机 / 取消语义 / 计量 / 资产引用 / 错误目录
# ---------------------------------------------------------------------------


def test_job_state_machine_transitions() -> None:
    mod = _common()
    State = mod.CreationJobState
    assert mod.can_transition(State.PENDING, State.ADMITTED)
    assert mod.can_transition(State.ADMITTED, State.RUNNING)
    assert mod.can_transition(State.RUNNING, State.SUCCEEDED)
    assert mod.can_transition(State.RUNNING, State.UNKNOWN)
    assert not mod.can_transition(State.RUNNING, State.PENDING)
    assert not mod.can_transition(State.PENDING, State.RUNNING)
    for terminal in (State.SUCCEEDED, State.FAILED, State.CANCELLED, State.UNKNOWN):
        assert not mod.can_transition(terminal, State.RUNNING), "终态不得复活"
        assert terminal in mod.TERMINAL_JOB_STATES
    assert len(mod.TERMINAL_JOB_STATES) == 4
    assert mod.CANCEL_REQUESTED_IS_NOT_A_STATE
    assert mod.CANCEL_MAY_KEEP_COST
    assert mod.UNKNOWN_NEVER_AUTO_REDISPATCH
    assert "cancel_requested" not in mod.JOB_STATES


def test_error_catalog_statuses() -> None:
    mod = _common()
    catalog = mod.CREATION_ERROR_CATALOG
    assert catalog["unsupported_parameter"] == 422
    assert catalog["dependency_unavailable"] == 503
    assert catalog["price_unavailable"] == 503
    assert catalog["budget_exceeded"] == 429


def test_usage_line_invariants() -> None:
    mod = _common()
    Line = mod.UsageLine
    line = Line(metric="characters", value=Decimal(1200), unit="characters", status="measured")
    assert line.value == Decimal(1200)
    with pytest.raises(pydantic.ValidationError, match="Token"):
        Line(metric="total_tokens", value=Decimal(1), unit="tokens", status="measured")
    with pytest.raises(pydantic.ValidationError):
        Line(metric="characters", value=None, unit="characters", status="measured")
    with pytest.raises(pydantic.ValidationError):
        Line(
            metric="characters",
            value=Decimal(1),
            unit="characters",
            status="not_applicable",
        )
    with pytest.raises(pydantic.ValidationError):
        Line(metric="characters", value="NaN", unit="characters", status="measured")
    with pytest.raises(pydantic.ValidationError):
        Line(metric="characters", value=Decimal(-1), unit="characters", status="measured")
    with pytest.raises(pydantic.ValidationError, match="单位"):
        Line(metric="characters", value=Decimal(1), unit="seconds", status="measured")
    with pytest.raises(pydantic.ValidationError):
        Line(metric="audio_seconds", value=Decimal(1), unit="seconds", status="measured", resolution_tier="hd")


def test_usage_line_rejects_float_money() -> None:
    mod = _common()
    with pytest.raises(pydantic.ValidationError, match="浮点"):
        mod.UsageLine(metric="requests", value=1.0, unit="requests", status="measured")
    cost = mod.CostAmount(amount=Decimal("0.018"), currency="CNY")
    assert cost.amount == Decimal("0.018")
    with pytest.raises(pydantic.ValidationError, match="浮点"):
        mod.CostAmount(amount=0.018, currency="CNY")
    with pytest.raises(pydantic.ValidationError):
        mod.CostAmount(amount=Decimal("-0.01"), currency="CNY")


def test_asset_ref_rejects_paths_and_urls() -> None:
    mod = _common()
    ok = mod.AssetRef(asset_id="asset_abc123")
    assert ok.asset_id == "asset_abc123"
    for bad in ("../etc/passwd", "a/b", "a\\b", "https://x/y", "C:\\evil"):
        with pytest.raises(pydantic.ValidationError):
            mod.AssetRef(asset_id=bad)
    assert mod.IMAGE_MAX_INPUT_PIXELS == 20_000_000
    with pytest.raises(pydantic.ValidationError):
        mod.AssetRef(asset_id="a", pixel_count=20_000_001)
    assert mod.AssetRef(asset_id="a", pixel_count=20_000_000).pixel_count == 20_000_000


# ---------------------------------------------------------------------------
# §9.1.1 TTS 契约
# ---------------------------------------------------------------------------


def _tts_request(tts_mod: ModuleType, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "text": "漂泊者，晚上好。",
        "provider": "provider_a",
        "model": "voice-model-1",
        "voice": "alloy",
        "language": "zh",
        "format": "mp3",
        "workspace_id": "ws_main",
        "target": "session_1",
        "version": "rev-1",
    }
    payload.update(overrides)
    return tts_mod.TTSJobRequest(**payload)


def test_tts_request_valid_and_defaults() -> None:
    tts_mod = _tts()
    req = _tts_request(tts_mod)
    assert req.speed == 1.0
    assert req.approved_reply_id is None
    assert tts_mod.TTS_MAX_TEXT_CHARS == 2000
    assert tts_mod.TTS_MAX_ASSET_BYTES == 8 * 1024 * 1024
    assert tts_mod.TTS_MAX_DURATION_SECONDS == tts_mod.TTS_MAX_ASSET_BYTES / 64000


def test_tts_request_text_xor_reply() -> None:
    tts_mod = _tts()
    with pytest.raises(pydantic.ValidationError, match="二选一"):
        _tts_request(tts_mod, approved_reply_id="reply_1")
    with pytest.raises(pydantic.ValidationError, match="二选一"):
        payload = _tts_request(tts_mod).model_dump()
        payload.pop("text")
        tts_mod.TTSJobRequest(**payload)
    reply_only = _tts_request(tts_mod, text=None, approved_reply_id="reply_1")
    assert reply_only.text is None


def test_tts_request_bounds() -> None:
    tts_mod = _tts()
    # 文本顶收敛到中央 2000 字：2000 过、2001 拒。
    with pytest.raises(pydantic.ValidationError):
        _tts_request(tts_mod, text="字" * 2001)
    assert _tts_request(tts_mod, text="字" * 2000).text is not None
    # speed 域收敛到中央引擎域 0.6..1.65：域外拒、边界过。
    for bad_speed in (0.55, 0.59, 1.66, 2.0):
        with pytest.raises(pydantic.ValidationError):
            _tts_request(tts_mod, speed=bad_speed)
    assert _tts_request(tts_mod, speed=0.6).speed == 0.6
    assert _tts_request(tts_mod, speed=1.65).speed == 1.65
    with pytest.raises(pydantic.ValidationError):
        _tts_request(tts_mod, speed=float("nan"))


def test_tts_request_rejects_registry_path_and_ssml() -> None:
    tts_mod = _tts()
    for field in ("provider", "model", "voice"):
        for bad in ("../voices/x", "http://x", "a/b"):
            with pytest.raises(pydantic.ValidationError):
                _tts_request(tts_mod, **{field: bad})
    with pytest.raises(pydantic.ValidationError, match="SSML"):
        _tts_request(tts_mod, text="<speak>hi</speak>")
    with pytest.raises(pydantic.ValidationError, match="extra"):
        _tts_request(tts_mod, workflow="arbitrary_code")


def test_tts_provider_capabilities_intersection() -> None:
    tts_mod = _tts()
    with pytest.raises(pydantic.ValidationError):
        tts_mod.TTSProviderCapabilities(
            provider="p", speed_min=0.9, speed_max=0.8, formats=("mp3",)
        )
    caps = tts_mod.TTSProviderCapabilities(
        provider="p", speed_min=0.8, speed_max=1.2, formats=("mp3", "wav")
    )
    assert tts_mod.speed_in_provider_intersection(1.0, caps)
    assert tts_mod.speed_in_provider_intersection(0.8, caps)
    assert not tts_mod.speed_in_provider_intersection(1.25, caps)
    assert tts_mod.format_supported("mp3", caps)
    assert not tts_mod.format_supported("ogg", caps)
    with pytest.raises(pydantic.ValidationError):
        tts_mod.TTSProviderCapabilities(
            provider="p", speed_min=0.55, speed_max=1.0, formats=("mp3",)
        )


def test_tts_usage_no_fake_tokens() -> None:
    tts_mod = _tts()
    common = _common()
    usage = tts_mod.TTSUsage(
        quantities=[
            common.UsageLine(
                metric="characters", value=Decimal(1200), unit="characters", status="measured"
            ),
            common.UsageLine(
                metric="audio_seconds", value=Decimal(30), unit="seconds", status="measured"
            ),
            common.UsageLine(metric="requests", value=Decimal(1), unit="requests", status="measured"),
        ]
    )
    assert usage.token_status == "not_applicable"
    with pytest.raises(pydantic.ValidationError, match="越界"):
        tts_mod.TTSUsage(
            quantities=[
                common.UsageLine(
                    metric="images", value=Decimal(1), unit="images", status="measured"
                )
            ]
        )
    with pytest.raises(pydantic.ValidationError, match="真报"):
        tts_mod.TTSUsage(token_status="measured", token_provider_reported=False)
    measured = tts_mod.TTSUsage(token_status="measured", token_provider_reported=True)
    assert measured.token_status == "measured"


def _tts_asset(tts_mod: ModuleType, common: ModuleType, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "asset_id": {"asset_id": "asset_tts_1"},
        "duration_seconds": 30.0,
        "bytes_size": 1024 * 512,
        "mime": "audio/mpeg",
        "provider_operation": "tts.create_speech",
        "usage": tts_mod.TTSUsage(
            quantities=[
                common.UsageLine(
                    metric="characters",
                    value=Decimal(1200),
                    unit="characters",
                    status="measured",
                )
            ]
        ),
        "review_approved": True,
    }
    payload.update(overrides)
    return tts_mod.TTSAssetRecord(**payload)


def test_tts_asset_record_caps_and_review_gate() -> None:
    tts_mod = _tts()
    common = _common()
    asset = _tts_asset(tts_mod, common)
    assert asset.fallback_to_file is False
    with pytest.raises(pydantic.ValidationError):
        _tts_asset(tts_mod, common, duration_seconds=132.0)
    with pytest.raises(pydantic.ValidationError):
        _tts_asset(tts_mod, common, bytes_size=8 * 1024 * 1024 + 1)
    with pytest.raises(pydantic.ValidationError, match="Review"):
        _tts_asset(tts_mod, common, review_approved=False)
    assert _tts_asset(tts_mod, common, duration_seconds=131.0).duration_seconds == 131.0
    costed = _tts_asset(tts_mod, common, cost={"amount": "0.018", "currency": "CNY"})
    assert costed.cost is not None and costed.cost.amount == Decimal("0.018")


def test_tts_outbound_plan_no_fake_voice() -> None:
    tts_mod = _tts()
    base: dict[str, Any] = {"asset_id": {"asset_id": "asset_tts_1"}}
    ok_voice = tts_mod.TTSOutboundPlan(
        tag="voice", native_voice_verified=True, review_approved=True, via_render_transport=True, **base
    )
    assert ok_voice.tag == "voice"
    with pytest.raises(pydantic.ValidationError, match="原生 voice"):
        tts_mod.TTSOutboundPlan(
            tag="voice", native_voice_verified=False, review_approved=True, via_render_transport=True, **base
        )
    file_fallback = tts_mod.TTSOutboundPlan(
        tag="file", native_voice_verified=False, review_approved=True, via_render_transport=True, **base
    )
    assert file_fallback.tag == "file"
    with pytest.raises(pydantic.ValidationError, match="旁路"):
        tts_mod.TTSOutboundPlan(
            tag="file", review_approved=True, via_render_transport=False, **base
        )
    with pytest.raises(pydantic.ValidationError, match="Review"):
        tts_mod.TTSOutboundPlan(
            tag="file", review_approved=False, via_render_transport=True, **base
        )


def test_tts_rest_routes_static_before_parametric() -> None:
    tts_mod = _tts()
    routes = tts_mod.TTS_REST_ROUTES
    paths = [path for _method, path in routes]
    assert paths[0] == "/tts/providers"
    assert paths.index("/tts/jobs/{id}") > paths.index("/tts/jobs")
    assert paths.index("/tts/jobs/{id}/cancel") == len(paths) - 1
    assert all(path.startswith("/tts") for path in paths)
    assert ("POST", "/tts/preview") in routes
    assert tts_mod.TTS_ERROR_CATALOG["unsupported_parameter"] == 422


# ---------------------------------------------------------------------------
# §9.1.2 绘图契约
# ---------------------------------------------------------------------------


def _image_request(image_mod: ModuleType, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "task": "text_to_image",
        "prompt": "釉瑚风格的云母卡片插画",
        "provider": "provider_a",
        "model": "image-model-1",
        "size": "1024x1024",
        "workspace_id": "ws_main",
        "version": "rev-1",
    }
    payload.update(overrides)
    return image_mod.ImageJobRequest(**payload)


def test_image_request_valid_and_defaults() -> None:
    image_mod = _image()
    req = _image_request(image_mod)
    assert req.count == 1
    assert req.steps is None and req.seed is None
    assert image_mod.IMAGE_MAX_PROMPT_CHARS == 4000
    assert image_mod.IMAGE_MAX_COUNT == 2
    assert image_mod.IMAGE_MAX_STEPS == 50
    assert image_mod.CONFIRM_TTL_SECONDS == 120


def test_image_request_bounds() -> None:
    image_mod = _image()
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, prompt="图" * 4001)
    assert _image_request(image_mod, prompt="图" * 4000).prompt
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, negative_prompt="杂" * 2001)
    for bad_count in (0, 3):
        with pytest.raises(pydantic.ValidationError):
            _image_request(image_mod, count=bad_count)
    assert _image_request(image_mod, count=2).count == 2
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, steps=51)
    assert _image_request(image_mod, steps=50).steps == 50
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, guidance=0)
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, seed=-1)
    with pytest.raises(pydantic.ValidationError):
        _image_request(image_mod, size="1024X1024")
    with pytest.raises(pydantic.ValidationError, match="extra"):
        _image_request(image_mod, workflow="arbitrary")


def test_image_request_task_shape() -> None:
    image_mod = _image()
    with pytest.raises(pydantic.ValidationError, match="assets"):
        _image_request(image_mod, task="image_to_image")
    ref = {"asset_id": "asset_in_1"}
    ok_i2i = _image_request(image_mod, task="image_to_image", assets=(ref,))
    assert ok_i2i.assets[0].asset_id == "asset_in_1"
    with pytest.raises(pydantic.ValidationError, match="mask"):
        _image_request(image_mod, task="inpaint", assets=(ref,))
    ok_inpaint = _image_request(image_mod, task="inpaint", assets=(ref,), mask={"asset_id": "asset_mask"})
    assert ok_inpaint.mask is not None
    with pytest.raises(pydantic.ValidationError, match="mask"):
        _image_request(image_mod, mask={"asset_id": "asset_mask"})


def test_image_provider_capabilities() -> None:
    image_mod = _image()
    caps = image_mod.ImageProviderCapabilities(
        provider="p",
        max_steps=30,
        sizes=("1024x1024", "512x512"),
        resolution_tiers=("standard", "hd"),
        supported_tasks=("text_to_image", "image_to_image"),
    )
    assert image_mod.steps_supported(30, caps)
    assert not image_mod.steps_supported(31, caps)
    assert not image_mod.steps_supported(50, caps)
    assert image_mod.size_supported("1024x1024", caps)
    assert not image_mod.size_supported("2048x2048", caps)
    assert image_mod.task_supported("text_to_image", caps)
    assert not image_mod.task_supported("inpaint", caps)
    with pytest.raises(pydantic.ValidationError):
        image_mod.ImageProviderCapabilities(
            provider="p", max_steps=51, sizes=("1024x1024",), supported_tasks=("text_to_image",)
        )


def test_image_safety_hook_protocol() -> None:
    image_mod = _image()

    class DenyAll:
        def check(self, request: Any) -> Any:
            return image_mod.SafetyCheckResult(passed=False, categories=("minors",), reason="硬红线")

    hook = DenyAll()
    assert isinstance(hook, image_mod.SafetyCheckHook)
    result = hook.check(_image_request(image_mod))
    assert not image_mod.asset_issuable(result)
    with pytest.raises(pydantic.ValidationError):
        image_mod.SafetyCheckResult(passed=False)


def test_image_usage_metrics_subset() -> None:
    image_mod = _image()
    common = _common()
    ok = image_mod.ImageUsage(
        quantities=[
            common.UsageLine(
                metric="images",
                value=Decimal(2),
                unit="images",
                status="measured",
                resolution_tier="hd",
            ),
            common.UsageLine(metric="requests", value=Decimal(1), unit="requests", status="measured"),
        ]
    )
    assert ok.quantities[0].resolution_tier == "hd"
    with pytest.raises(pydantic.ValidationError, match="越界"):
        image_mod.ImageUsage(
            quantities=[
                common.UsageLine(
                    metric="audio_seconds", value=Decimal(1), unit="seconds", status="measured"
                )
            ]
        )
    with pytest.raises(pydantic.ValidationError, match="真报"):
        image_mod.ImageUsage(token_status="measured")


def _image_asset(image_mod: ModuleType, **overrides: Any) -> Any:
    payload: dict[str, Any] = {
        "asset_id": {"asset_id": "asset_img_1"},
        "width": 1024,
        "height": 1024,
        "real_mime": "image/png",
        "bytes_size": 800_000,
        "magic_verified": True,
        "exif_sanitized": True,
        "review_approved": True,
    }
    payload.update(overrides)
    return image_mod.ImageAssetRecord(**payload)


def test_image_asset_record_gates() -> None:
    image_mod = _image()
    asset = _image_asset(image_mod)
    assert asset.frames == 1
    with pytest.raises(pydantic.ValidationError, match="magic"):
        _image_asset(image_mod, magic_verified=False)
    with pytest.raises(pydantic.ValidationError, match="EXIF"):
        _image_asset(image_mod, exif_sanitized=False)
    with pytest.raises(pydantic.ValidationError, match="Review"):
        _image_asset(image_mod, review_approved=False)
    multi = _image_asset(image_mod, frames=4)
    assert multi.frames == 4


def _confirm_token(image_mod: ModuleType, **overrides: Any) -> Any:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "token_id": "confirm_1",
        "actor": "user_1",
        "target": "session_1",
        "workspace_version": "rev-1",
        "payload_digest": "a" * 64,
        "issued_at": now,
        "expires_at": now + timedelta(seconds=120),
    }
    payload.update(overrides)
    return image_mod.ConfirmToken(**payload)


def test_image_confirm_token_and_delivery_plan() -> None:
    image_mod = _image()
    token = _confirm_token(image_mod)
    assert not image_mod.confirm_expired(token, datetime.now(timezone.utc))
    assert image_mod.confirm_expired(
        token, datetime.now(timezone.utc) + timedelta(seconds=121)
    )
    assert image_mod.confirm_reusable(token)
    consumed = _confirm_token(image_mod, consumed=True)
    assert not image_mod.confirm_reusable(consumed)
    with pytest.raises(pydantic.ValidationError):
        _confirm_token(image_mod, payload_digest="short")
    with pytest.raises(pydantic.ValidationError):
        _confirm_token(
            image_mod,
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    with pytest.raises(pydantic.ValidationError):
        # 下一条 naive datetime 是被测拒绝面（DTZ001 有意触发）
        _confirm_token(image_mod, issued_at=datetime(2026, 1, 1))  # noqa: DTZ001

    ref = {"asset_id": "asset_img_1"}
    preview = image_mod.ImageDeliveryPlan(
        asset_ids=(ref,), mode="preview", review_approved=True
    )
    assert preview.confirm is None
    with pytest.raises(pydantic.ValidationError, match="确认 token"):
        image_mod.ImageDeliveryPlan(
            asset_ids=(ref,), mode="confirmed_send", review_approved=True
        )
    with pytest.raises(pydantic.ValidationError, match="消费"):
        image_mod.ImageDeliveryPlan(
            asset_ids=(ref,),
            mode="confirmed_send",
            confirm=_confirm_token(image_mod, consumed=True).model_dump(),
            review_approved=True,
        )
    ok_send = image_mod.ImageDeliveryPlan(
        asset_ids=(ref,),
        mode="confirmed_send",
        confirm=token,
        review_approved=True,
    )
    assert ok_send.confirm is token


def test_image_rest_routes_static_before_parametric() -> None:
    image_mod = _image()
    routes = image_mod.IMAGE_REST_ROUTES
    paths = [path for _method, path in routes]
    assert paths[0] == "/image-generation/providers"
    assert paths.index("/image-generation/jobs/{id}") > paths.index("/image-generation/jobs")
    assert all(path.startswith("/image-generation") for path in paths)
    assert image_mod.IMAGE_ERROR_CATALOG["budget_exceeded"] == 429


# ---------------------------------------------------------------------------
# §9.3 注册面：未注册不可实例化 / dormant 门 / 四步接入
# ---------------------------------------------------------------------------


def test_registry_unregistered_rejected() -> None:
    registry_mod = _registry()
    tts_mod = _tts()
    registry = registry_mod.CreationCapabilityRegistry()
    req = _tts_request(tts_mod)
    with pytest.raises(registry_mod.UnregisteredCapabilityError):
        registry.instantiate("creation.nope", req)


def test_registry_dormant_gate_blocks_instantiation() -> None:
    registry_mod = _registry()
    tts_mod = _tts()
    registry = registry_mod.CreationCapabilityRegistry()
    entry = registry_mod.CreationCapabilityEntry(
        stable_id="creation.tts", kind="tts", label="TTS", contract_dto=tts_mod.TTSJobRequest
    )
    registry.register(entry)
    assert registry.get("creation.tts") is not None
    with pytest.raises(registry_mod.CapabilityGateClosedError):
        registry.instantiate("creation.tts", _tts_request(tts_mod))


def test_registry_default_enabled_false_is_pinned() -> None:
    registry_mod = _registry()
    with pytest.raises(pydantic.ValidationError):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.tts",
            kind="tts",
            label="TTS",
            default_enabled=True,
        )
    with pytest.raises(pydantic.ValidationError):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.tts", kind="tts", label="TTS", gate_state="enabled"
        )


def test_registry_entry_validation() -> None:
    registry_mod = _registry()
    with pytest.raises(pydantic.ValidationError):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.video", kind="video", label="x"
        )
    with pytest.raises(pydantic.ValidationError):
        registry_mod.CreationCapabilityEntry(stable_id="other.tts", kind="tts", label="x")
    with pytest.raises(pydantic.ValidationError, match="DTO"):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.tts",
            kind="tts",
            label="x",
            integration_step=registry_mod.STEP_PROTOCOL,
        )
    with pytest.raises(pydantic.ValidationError, match="extensions"):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.ext.x", kind="extensions", label="x", contract_dto=_tts().TTSJobRequest
        )
    with pytest.raises(pydantic.ValidationError, match="projection"):
        registry_mod.CreationCapabilityEntry(
            stable_id="creation.tts",
            kind="tts",
            label="x",
            contract_dto=_tts().TTSJobRequest,
            integration_step=2,
            projection_complete=True,
        )


def test_registry_duplicate_and_four_step_flow() -> None:
    registry_mod = _registry()
    image_mod = _image()
    registry = registry_mod.CreationCapabilityRegistry()
    entry = registry_mod.CreationCapabilityEntry(
        stable_id="creation.image",
        kind="image",
        label="绘图",
        contract_dto=image_mod.ImageJobRequest,
    )
    registry.register(entry)
    with pytest.raises(ValueError, match="重复"):
        registry.register(entry)

    full = registry_mod.CreationCapabilityEntry(
        stable_id="creation.image",
        kind="image",
        label="绘图",
        contract_dto=image_mod.ImageJobRequest,
        integration_step=registry_mod.STEP_PROJECTED,
        projection_complete=True,
    )
    no_factory = registry_mod.CreationCapabilityRegistry()
    no_factory.register(full)
    with pytest.raises(registry_mod.CapabilityNotImplementedError):
        no_factory.instantiate("creation.image", _image_request(image_mod))

    with_factory = registry_mod.CreationCapabilityRegistry()
    marker: dict[str, Any] = {}
    with_factory.register(full, factory=lambda payload: marker.setdefault("payload", payload))
    result = with_factory.instantiate("creation.image", _image_request(image_mod))
    assert result is marker["payload"]
    assert result.count == 1  # type: ignore[attr-defined]

    wrong = _tts_request(_tts())
    with pytest.raises(TypeError, match="契约不匹配"):
        with_factory.instantiate("creation.image", wrong)


def test_manifest_registration_blockers_honest() -> None:
    registry_mod = _registry()
    tts_mod = _tts()
    entry = registry_mod.CreationCapabilityEntry(
        stable_id="creation.tts", kind="tts", label="TTS", contract_dto=tts_mod.TTSJobRequest
    )
    blockers = registry_mod.manifest_registration_blockers(entry)
    assert "route_kind" in blockers and "implementation_ref" in blockers
    assert registry_mod.NODE_REQUIRED_FIELDS
    assert set(registry_mod.REGISTRY_OPEN_NODE_KINDS) == {
        "feature",
        "sub_feature",
        "command",
        "help",
        "scheduled_job",
        "control_action",
        "config",
    }
    assert registry_mod.RESERVED_REGISTRY.get("creation.tts") is not None
