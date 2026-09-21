"""V2.1 S2 协议席合同测试：统一 envelope/错误协议 + import 副作用探针。

合同来源（本文件是它们的机器可执行形态之一）：
- docs/design/backend-v2-implementation-guide.md §6（envelope 形状/错误表/严格 DTO/单一错误注册源）
- docs/design/backend-v2-product-extensions.md（补充错误码集中注册段）
- 验收矩阵 V21-CORE-001（DTO/注册 import 无 NoneBot/配置/网络副作用）
- 验收矩阵 V21-API-001（REST envelope/DTO/error 部分）

设计要点：
- 探针一（直载）：importlib.util.spec_from_file_location 直接加载新契约模块，
  断言零 nonebot 模块增量、零线程增量、cwd 零新文件、socket 零调用、builtins.open 零调用。
- 探针二（包内导入现实）：子进程正常 import
  plugins.bot_unified_runtime.contracts.<模块>，记录父包 __init__ 的真实副作用
  （nonebot 是否被拉起、模块增量、耗时、cwd 新文件），结果如实打印为 JSON。
  V21-CORE-001 的真实发现以本探针输出为准，不在此修（父包装配收敛属后续席位）。
- 单元测试全部走直载模块，不依赖父包 import，保证本文件在隔离环境可独立运行。
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = WORKSPACE_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "core" / "contracts"  # 2026-09-18 RET2B-PREP: contracts 六模块垫片退役，直载/源检面改指 canonical
VENV_PYTHON = WORKSPACE_ROOT.parent / "ChatBot_Runtime" / "venv" / "Scripts" / "python.exe"

# 直载用的独立模块名（不与 sys.modules 中真实包名冲突）。
NEW_MODULES: list[tuple[str, str]] = [
    ("v21s2_envelope", "envelope.py"),
    ("v21s2_errors", "errors.py"),
    ("v21s2_request", "request.py"),
]

FORBIDDEN_MODULE_PREFIXES = ("nonebot",)

PROBE_JSON_MARKER = "V21_PROBE_JSON:"


# ---------------------------------------------------------------------------
# 直载与探针基础设施
# ---------------------------------------------------------------------------


def _direct_load(module_name: str, file_name: str) -> Any:
    """普通直载（无探针），供单元测试使用；加载后不留 sys.modules 痕迹。"""
    path = CONTRACTS_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None, f"无法构造 spec: {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _guarded_direct_load(module_name: str, file_name: str) -> Any:
    """探针一：直载 + 五路副作用观测。

    观测面：nonebot 系模块增量 / 线程数增量 / cwd 新文件 / socket 调用 /
    builtins.open 调用。任何一路非零即失败。
    """
    path = CONTRACTS_DIR / file_name
    forbidden_before = {
        name for name in sys.modules if name.startswith(FORBIDDEN_MODULE_PREFIXES)
    }
    threads_before = threading.active_count()
    cwd_before = set(os.listdir(os.getcwd()))
    socket_calls: list[str] = []
    open_calls: list[str] = []

    class _CountingSocket(socket.socket):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            socket_calls.append("socket.socket")
            super().__init__(*args, **kwargs)

    real_open = builtins.open

    def _counting_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        open_calls.append(str(file))
        return real_open(file, *args, **kwargs)

    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses 处理字符串注解时会按 cls.__module__ 反查 sys.modules，
    # 直载必须先注册模块名（Exec 模块的正常姿势）。
    sys.modules[module_name] = module
    with (
        mock.patch.object(socket, "socket", _CountingSocket),
        mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network")
        ),
        mock.patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("dns")
        ),
        mock.patch.object(builtins, "open", _counting_open),
    ):
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)

    forbidden_after = {
        name for name in sys.modules if name.startswith(FORBIDDEN_MODULE_PREFIXES)
    }
    new_forbidden = forbidden_after - forbidden_before
    assert not new_forbidden, f"直载 {file_name} 引入了禁止模块: {sorted(new_forbidden)}"
    assert (
        threading.active_count() == threads_before
    ), f"直载 {file_name} 产生了新线程"
    assert set(os.listdir(os.getcwd())) == cwd_before, f"直载 {file_name} 在 cwd 写了文件"
    assert socket_calls == [], f"直载 {file_name} 发生了 socket 构造: {socket_calls}"
    assert open_calls == [], f"直载 {file_name} 发生了 builtins.open 调用: {open_calls}"
    return module


@pytest.fixture(scope="module")
def envelope_mod() -> Any:
    return _direct_load(*NEW_MODULES[0])


@pytest.fixture(scope="module")
def errors_mod() -> Any:
    return _direct_load(*NEW_MODULES[1])


@pytest.fixture(scope="module")
def request_mod() -> Any:
    return _direct_load(*NEW_MODULES[2])


class TestDirectLoadProbe:
    """探针一：新契约模块必须纯 pydantic+stdlib，零 nonebot/网络/线程/文件副作用。"""

    @pytest.mark.parametrize(("module_name", "file_name"), NEW_MODULES)
    def test_direct_load_has_no_side_effects(self, module_name: str, file_name: str) -> None:
        module = _guarded_direct_load(module_name, file_name)
        assert module is not None

    @pytest.mark.parametrize(("module_name", "file_name"), NEW_MODULES)
    def test_source_has_no_forbidden_imports(
        self, module_name: str, file_name: str
    ) -> None:
        source = (CONTRACTS_DIR / file_name).read_text(encoding="utf-8")
        for needle in ("nonebot", "requests", "httpx", "aiohttp", "urllib.request"):
            assert needle not in source, f"{file_name} 源码出现禁止依赖 {needle}"


class TestPackageImportProbe:
    """探针二：包内导入现实——记录父包 __init__ 的真实副作用（V21-CORE-001 证据）。"""

    def test_submodule_package_import_report(self) -> None:
        probe_target = "plugins.bot_unified_runtime.domains.core.contracts.envelope"
        script = f"""
import json, sys, time, threading, os
target = {probe_target!r}
report = {{"probe": "package_import", "target": target}}
before = set(sys.modules)
threads_before = threading.active_count()
cwd_before = set(os.listdir(os.getcwd()))
t0 = time.perf_counter()
try:
    mod = __import__(target, fromlist=["__doc__"])
    report["ok"] = True
    report["module_usable"] = hasattr(mod, "SCHEMA_VERSION")
except BaseException as exc:
    report["ok"] = False
    report["error_type"] = type(exc).__name__
    report["error"] = f"{{type(exc).__name__}}: {{exc}}"[:500]
report["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
after = set(sys.modules)
report["parent_imported"] = "plugins.bot_unified_runtime" in after
report["nonebot_loaded"] = any(
    n == "nonebot" or n.startswith("nonebot.") for n in after
)
report["delta_modules"] = len(after - before)
report["threads_before"] = threads_before
report["threads_after"] = threading.active_count()
report["cwd_new_files"] = sorted(set(os.listdir(os.getcwd())) - cwd_before)[:20]
print({PROBE_JSON_MARKER!r}, json.dumps(report, ensure_ascii=False))
"""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        env["BOT_AUTOSYNC"] = "0"
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", script],
            cwd=str(WORKSPACE_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,  # 探针如实记录失败形态，不以返回码判死
        )
        marker_line = next(
            (ln for ln in proc.stdout.splitlines() if PROBE_JSON_MARKER in ln), None
        )
        assert marker_line is not None, (
            "子进程未产出探针 JSON。\nstdout 尾部:\n"
            + "\n".join(proc.stdout.splitlines()[-20:])
            + "\nstderr 尾部:\n"
            + "\n".join(proc.stderr.splitlines()[-20:])
        )
        report = json.loads(marker_line.split(PROBE_JSON_MARKER, 1)[1])
        # 结构硬断言：探针本身必须可信。
        assert report["probe"] == "package_import"
        assert isinstance(report["ok"], bool)
        assert report["cwd_new_files"] == [], "包内导入在 cwd 产生了新文件"
        if report["ok"]:
            assert report["parent_imported"] is True, "子模块导入必然经过父包 __init__"
            assert report["module_usable"] is True
        # 副作用事实（nonebot_loaded/delta_modules/elapsed_ms）如实落日志，
        # 不在此断言具体值：父包装配收敛属后续席位，本席只取证。


# ---------------------------------------------------------------------------
# 错误注册表（单一注册源）
# ---------------------------------------------------------------------------

# 期望码表：来自主规范 §6 错误表 + 扩展文档补充注册段（code -> (http, retryable 默认)）。
# delivery_unknown 按规范以任务/part 状态暴露，http=None。
EXPECTED_ERROR_CODES: dict[str, tuple[int | None, bool]] = {
    # §6 主错误表
    "unauthenticated": (401, False),
    "permission_denied": (403, False),
    "resource_not_found": (404, False),
    "validation_error": (422, False),
    "unsupported_parameter": (422, False),
    "content_rejected": (422, False),
    "unsupported_format": (415, False),
    "version_conflict": (409, False),
    "idempotency_conflict": (409, False),
    "confirmation_required": (409, False),
    "confirmation_expired": (409, False),
    "feature_disabled": (409, False),
    "cancel_not_supported": (409, False),
    "rate_limited": (429, True),
    "capacity_exceeded": (429, True),
    "dependency_unavailable": (503, True),
    "sandbox_unavailable": (503, True),
    "provider_auth_failed": (503, False),
    "storage_unavailable": (503, True),
    "provider_rate_limited": (503, True),
    "resource_limit_exceeded": (503, True),
    "integrity_mismatch": (503, False),
    "reload_failed": (503, True),
    "rollback_failed": (503, False),
    "deadline_exceeded": (504, True),
    "output_contract_violation": (502, False),
    "delivery_unknown": (None, False),
    # 扩展补充码（backend-v2-product-extensions.md）
    "usage_inconsistent": (502, False),
    "price_unavailable": (503, False),
    "budget_exceeded": (429, False),
    "affinity_unit_mismatch": (422, False),
    "affinity_evidence_missing": (409, False),
    "invalid_spread": (422, False),
    "deck_integrity_mismatch": (503, False),
    "schedule_cycle": (422, False),
    "missing_calendar": (409, False),
    "ambiguous_local_time": (422, False),
    "schedule_conflict": (409, False),
    "occurrence_expired": (409, False),
    "unsupported_platform_capability": (422, False),
    "acceptance_authorization_expired": (403, False),
}

# 人话模板不得出现内部细节形态（栈/路径/内部端点/库名/环境引用）。
LEAK_PATTERNS = (
    "Traceback",
    "Exception",
    ".py",
    "C:\\",
    "/api/v1",
    "sqlite",
    ".env",
    "axonhub",
    "NoneBot",
)


class TestErrorRegistry:
    def test_registry_covers_expected_codes_exactly(
        self, errors_mod: Any
    ) -> None:
        registered = set(errors_mod.iter_error_codes())
        expected = set(EXPECTED_ERROR_CODES)
        assert registered == expected, (
            f"缺失: {sorted(expected - registered)}; "
            f"多出: {sorted(registered - expected)}"
        )

    @pytest.mark.parametrize("code", sorted(EXPECTED_ERROR_CODES))
    def test_spec_matches_contract(self, errors_mod: Any, code: str) -> None:
        spec = errors_mod.get_error_spec(code)
        expected_http, expected_retryable = EXPECTED_ERROR_CODES[code]
        assert spec.http_status == expected_http
        assert spec.retryable is expected_retryable

    @pytest.mark.parametrize("code", sorted(EXPECTED_ERROR_CODES))
    def test_message_templates_humanized(
        self, errors_mod: Any, code: str
    ) -> None:
        template = errors_mod.get_error_spec(code).message_template
        assert template.strip(), f"{code} 模板为空"
        assert len(template) <= 80, f"{code} 模板过长: {template!r}"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in template), (
            f"{code} 模板应为人话中文: {template!r}"
        )
        lowered = template.lower()
        for pattern in LEAK_PATTERNS:
            assert pattern.lower() not in lowered, (
                f"{code} 模板疑似泄露内部细节: {pattern} in {template!r}"
            )

    @pytest.mark.parametrize("code", sorted(EXPECTED_ERROR_CODES))
    def test_every_code_builds_valid_envelope(
        self, errors_mod: Any, envelope_mod: Any, code: str
    ) -> None:
        payload = errors_mod.error_envelope(
            code, request_id="req_fixed", trace_id="trace_fixed"
        )
        envelope = envelope_mod.ApiEnvelope.model_validate(payload)
        assert envelope.data is None
        assert envelope.error is not None
        assert envelope.error.code == code
        assert isinstance(envelope.error.retryable, bool)
        assert envelope.error.debug_id.startswith("dbg_")
        # request_id / trace_id 传播：error 与 meta 一致且等于显式传入值。
        assert envelope.error.request_id == "req_fixed"
        assert envelope.error.trace_id == "trace_fixed"
        assert envelope.meta.request_id == "req_fixed"
        assert envelope.meta.trace_id == "trace_fixed"
        assert envelope.meta.schema_version == "v1"
        assert envelope.meta.generated_at.tzinfo is not None
        # 序列化形态也必须是合法 JSON（isoformat UTC）。
        raw = json.dumps(payload, ensure_ascii=False)
        assert "NaN" not in raw and "Infinity" not in raw

    def test_unknown_code_rejected(self, errors_mod: Any) -> None:
        with pytest.raises(errors_mod.UnknownErrorCodeError):
            errors_mod.error_envelope("definitely_not_a_code")
        with pytest.raises(errors_mod.UnknownErrorCodeError):
            errors_mod.get_error_spec("definitely_not_a_code")

    def test_legacy_alias_interface(self, errors_mod: Any) -> None:
        # 旧码兼容映射留接口：dict[str, str]，目标必须在注册表内（导入期自检）。
        assert isinstance(errors_mod.LEGACY_CODE_ALIASES, dict)
        for target in errors_mod.LEGACY_CODE_ALIASES.values():
            assert target in set(errors_mod.iter_error_codes())
        assert errors_mod.resolve_code("validation_error") == "validation_error"

    def test_retryable_override_and_field_errors(
        self, errors_mod: Any, envelope_mod: Any
    ) -> None:
        payload = errors_mod.error_envelope(
            "rate_limited",
            request_id="req_o",
            trace_id="trace_o",
            retryable=False,
            field_errors=[{"field": "limit", "message": "超出单次上限"}],
        )
        envelope = envelope_mod.ApiEnvelope.model_validate(payload)
        assert envelope.error is not None
        assert envelope.error.retryable is False
        assert envelope.error.field_errors[0].field == "limit"
        assert envelope.error.field_errors[0].message == "超出单次上限"

    def test_message_override_and_template_interpolation(
        self, errors_mod: Any
    ) -> None:
        custom = errors_mod.error_envelope(
            "unauthenticated", request_id="r", trace_id="t", message="请先登录再试。"
        )
        assert custom["error"]["message"] == "请先登录再试。"
        # 模板插值：占位符由 **fields 提供；缺失占位符保持字面量，不抛 KeyError。
        with_fields = errors_mod.error_envelope(
            "version_conflict",
            request_id="r",
            trace_id="t",
            expected_version="7",
        )
        assert "7" in with_fields["error"]["message"]
        missing = errors_mod.error_envelope(
            "version_conflict", request_id="r", trace_id="t"
        )
        assert "expected_version" in missing["error"]["message"]

    def test_generated_ids_format(self, errors_mod: Any) -> None:
        payload = errors_mod.error_envelope("rate_limited")
        assert payload["meta"]["request_id"].startswith("req_")
        assert payload["meta"]["trace_id"].startswith("trace_")
        assert payload["error"]["debug_id"].startswith("dbg_")
        assert payload["meta"]["schema_version"] == "v1"


# ---------------------------------------------------------------------------
# envelope 严格模型
# ---------------------------------------------------------------------------


class TestEnvelopeModels:
    def test_success_round_trip(self, envelope_mod: Any) -> None:
        data = {"feature_id": "weather", "enabled": True, "count": 3}
        payload = envelope_mod.success_envelope(
            data, request_id="req_rt", trace_id="trace_rt"
        )
        raw = json.dumps(payload, ensure_ascii=False)
        envelope = envelope_mod.ApiEnvelope.model_validate(json.loads(raw))
        assert envelope.data == data
        assert envelope.error is None
        assert envelope.meta.request_id == "req_rt"
        assert envelope.meta.trace_id == "trace_rt"
        assert envelope.meta.schema_version == "v1"
        # 再序列化保持稳定（往返一致性）。
        again = json.loads(envelope.model_dump_json())
        assert again["meta"]["request_id"] == "req_rt"
        assert again["meta"]["schema_version"] == "v1"

    def test_success_envelope_defaults_generate_ids(
        self, envelope_mod: Any
    ) -> None:
        payload = envelope_mod.success_envelope({"ok": True})
        assert payload["meta"]["request_id"].startswith("req_")
        assert payload["meta"]["trace_id"].startswith("trace_")
        assert payload["error"] is None
        assert payload["data"] == {"ok": True}

    def test_unknown_field_rejected_on_meta(
        self, envelope_mod: Any
    ) -> None:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            envelope_mod.ResponseMeta.model_validate(
                {
                    "request_id": "req_x",
                    "trace_id": "trace_x",
                    "schema_version": "v1",
                    "generated_at": "2026-09-17T00:00:00+00:00",
                    "unexpected": "nope",
                }
            )

    def test_unknown_field_rejected_on_envelope(
        self, envelope_mod: Any
    ) -> None:
        payload = envelope_mod.success_envelope(None)
        payload["surprise"] = 1
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.ApiEnvelope.model_validate(payload)

    def test_unknown_field_rejected_on_error_body(
        self, errors_mod: Any, envelope_mod: Any
    ) -> None:
        payload = errors_mod.error_envelope("rate_limited", request_id="r", trace_id="t")
        payload["error"]["internal_stack"] = "nope"
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.ApiEnvelope.model_validate(payload)

    def test_nan_and_infinity_rejected(self, envelope_mod: Any) -> None:
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.RetryHint(retry_after_seconds=float("nan"))
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.RetryHint(retry_after_seconds=float("inf"))
        ok = envelope_mod.RetryHint(retry_after_seconds=1.5)
        assert ok.retry_after_seconds == 1.5

    def test_schema_version_literal_locked(self, envelope_mod: Any) -> None:
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.ResponseMeta(
                request_id="req_x",
                trace_id="trace_x",
                schema_version="v2",
                generated_at=datetime.now(timezone.utc),
            )

    def test_generated_at_naive_rejected_and_normalized(
        self, envelope_mod: Any
    ) -> None:
        with pytest.raises(Exception):  # noqa: B017
            envelope_mod.ResponseMeta(
                request_id="req_x",
                trace_id="trace_x",
                # naive datetime 本身就是被测拒绝对象
                generated_at=datetime(2026, 9, 17, 12, 0, 0),  # noqa: DTZ001
            )
        meta = envelope_mod.ResponseMeta(
            request_id="req_x",
            trace_id="trace_x",
            generated_at=datetime(2026, 9, 17, 20, 0, 0, tzinfo=timezone(timedelta(hours=8))),
        )
        assert meta.generated_at.utcoffset() == timedelta(0)
        assert meta.generated_at.hour == 12

    def test_request_id_propagation_in_success_envelope(
        self, envelope_mod: Any
    ) -> None:
        payload = envelope_mod.success_envelope(
            {"k": "v"}, request_id="req_p", trace_id="trace_p"
        )
        assert payload["meta"]["request_id"] == "req_p"
        assert payload["meta"]["trace_id"] == "trace_p"


# ---------------------------------------------------------------------------
# request 严格 DTO
# ---------------------------------------------------------------------------


class TestRequestDTOs:
    def test_pagination_defaults_and_bounds(self, request_mod: Any) -> None:
        page = request_mod.PaginationQuery()
        assert page.limit == 50
        assert page.cursor is None
        with pytest.raises(Exception):  # noqa: B017
            request_mod.PaginationQuery(limit=0)
        with pytest.raises(Exception):  # noqa: B017
            request_mod.PaginationQuery(limit=201)
        assert request_mod.PaginationQuery(limit=200).limit == 200

    def test_write_expectation_version_semantics(self, request_mod: Any) -> None:
        assert request_mod.WriteExpectation(expected_version=0).expected_version == 0
        with pytest.raises(Exception):  # noqa: B017
            request_mod.WriteExpectation(expected_version=-1)

    def test_idempotency_ref_shape(self, request_mod: Any) -> None:
        ref = request_mod.IdempotencyRef(
            key="order-20260917-1",
            payload_sha256="a" * 64,
        )
        assert ref.key == "order-20260917-1"
        for bad_key in ("-bad", "has space", "x" * 200):
            with pytest.raises(Exception):  # noqa: B017
                request_mod.IdempotencyRef(key=bad_key, payload_sha256="a" * 64)
        with pytest.raises(Exception):  # noqa: B017
            request_mod.IdempotencyRef(key="ok-key", payload_sha256="xyz")

    def test_confirmation_ref_binding_and_ttl(self, request_mod: Any) -> None:
        now = datetime.now(timezone.utc)
        ref = request_mod.ConfirmationRef(
            token="tok_123",
            actor="admin-1",
            target="workspace/send:42",
            expected_version=3,
            content_sha256="b" * 64,
            issued_at=now,
            expires_at=now + timedelta(seconds=119),
        )
        assert ref.expected_version == 3
        # 超过 120s TTL 拒绝
        with pytest.raises(Exception):  # noqa: B017
            request_mod.ConfirmationRef(
                token="tok_123",
                actor="admin-1",
                target="workspace/send:42",
                expected_version=3,
                content_sha256="b" * 64,
                issued_at=now,
                expires_at=now + timedelta(seconds=121),
            )
        # 过期时刻早于签发时刻拒绝
        with pytest.raises(Exception):  # noqa: B017
            request_mod.ConfirmationRef(
                token="tok_123",
                actor="admin-1",
                target="workspace/send:42",
                expected_version=3,
                content_sha256="b" * 64,
                issued_at=now,
                expires_at=now - timedelta(seconds=1),
            )
        # naive 时间拒绝（naive 是被测行为）
        with pytest.raises(Exception):  # noqa: B017
            request_mod.ConfirmationRef(
                token="tok_123",
                actor="admin-1",
                target="workspace/send:42",
                expected_version=3,
                content_sha256="b" * 64,
                issued_at=datetime(2026, 9, 17, 12, 0, 0),  # noqa: DTZ001
                expires_at=datetime(2026, 9, 17, 12, 1, 0),  # noqa: DTZ001
            )

    def test_principal_ref_shape(self, request_mod: Any) -> None:
        principal = request_mod.PrincipalRef(
            subject="admin-1", roles=["admin"], scopes=["features:write"]
        )
        assert principal.roles == ["admin"]
        with pytest.raises(Exception):  # noqa: B017
            request_mod.PrincipalRef(subject="", roles=["admin"])

    def test_request_dtos_reject_unknown_fields(self, request_mod: Any) -> None:
        with pytest.raises(Exception):  # noqa: B017
            request_mod.PaginationQuery.model_validate({"limit": 10, "from_client": True})
        with pytest.raises(Exception):  # noqa: B017
            request_mod.WriteExpectation.model_validate(
                {"expected_version": 1, "principal": {"subject": "spoof"}}
            )
