"""控制面语音入口的离线回归（中央调度收编波 P4-C4，席 S08）。

四问四答（简报验收四条逐一对应）：
① 路由存在且**只经中央 invoker**——monkeypatch 拦 `CapabilityInvoker.invoke`，
   验 capability_id 字面量与 payload 形状，同时给执行体 `engine_provider.handle`
   挂哨兵，断言它一次都不被碰到（两条各拦一类绕法）。
② 未配 provider 时**绝不 200+空成功**——不拦 invoker，走真实中央路：
   provider 门未配 ⇒ UNAVAILABLE ⇒ HTTP 5xx + 稳定错误码 + 诚实说明。
③ 响应不回显密钥/env 值——把 `sk-`、`BOT_XXX=`、盘符路径塞进失败 detail，
   断言原文一个都不出现在响应体里。
④ 注毒一发——把路由改成直调 engine_provider 的合成源码喂给同一支 AST 尺，
   断言必报违规（证明"唯一入口"锁有牙，不是自证快照）。

全离线：零网络、零引擎调用、零生产配置实例化。
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.domains.creation.tts import contracts as tts_contracts
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

ROOT = {"Authorization": "Bearer s08-root"}
READ = {"Authorization": "Bearer s08-read"}

#: 被测路由真身（AST 尺的输入）。
ROUTE_SOURCE_REL = Path("plugins/bot_unified_runtime/domains/creation/tts/routes.py")

#: 本席钉死的那一枚能力 id——路由改指任何别的 id 都属换路，不是接线。
CID = "creation.tts.synthesize"

#: 禁止出现在路由源码里的"第二条路"符号（import 或属性访问两条形态都覆盖）。
_FORBIDDEN_TOKENS = ("engine_provider", "synthesize_autodub", "capabilities.tts", "media.capabilities")


def _job_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "text": "守岸人在此，说吧。",
        "provider": "gptsovits",
        "model": "v2ProPlus",
        "voice": "shorekeeper",
        "language": "zh",
        "format": "wav",
        "workspace_id": "ws-s08",
        "target": "qq",
        "version": "v1",
    }
    body.update(over)
    return body


@pytest.fixture
def client(tmp_path):
    """无 bot_tts_* 键的配置 ⇒ provider 门恒 False（诚实未配），v1 路由照常装配。

    ⚠ `bot_tts_enabled=True` 是本波总开关落地后补的一格：开关关 ⇒ `handle` 首道就返
    NOT_CONFIGURED（压根不到 provider 门），那就测不到本件要测的"未配 provider"路径了。
    provider 相关键仍一律不给 ⇒ provider 门照旧 False。开关自身的关态由
    `tests/test_tts_creation_gate_reality.py` 专测。
    """
    cfg = SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_tts_enabled=True,
        bot_control_plane_token_sha256=hash_token("s08-read"),
        bot_control_plane_super_admin_token_sha256=hash_token("s08-root"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )
    app = create_control_plane_app(
        cfg, audit_store=ControlPlaneAuditStore(str(tmp_path / "audit.sqlite3")), channel_health_store=object()
    )
    with TestClient(app, base_url="http://127.0.0.1:8742", raise_server_exceptions=False) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# ① 路由在册 + 只经中央 invoker
# ---------------------------------------------------------------------------
def test_tts_job_routes_are_mounted(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json", headers=ROOT).json()["data"]
    assert "/api/v1/tts/jobs" in schema["paths"], "POST 入口未挂进 /api/v1"
    assert "/api/v1/tts/jobs/{job_id}" in schema["paths"], "GET 状态/轮询入口未挂进 /api/v1"


def test_write_routes_reject_read_token(client: TestClient) -> None:
    assert client.post("/api/v1/tts/jobs", headers=READ, json=_job_body()).status_code == 403


def test_post_delegates_to_central_invoker_and_never_to_engine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[cp.CapabilityRequest] = []

    def _fake_invoke(self: Any, request: cp.CapabilityRequest, *, config: Any = None) -> cp.InvocationResult:
        del config
        seen.append(request)
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            data={
                "audio_file": r"C:\secret\Runtime\data\cards\tts-abc.wav",
                "preset_id": "default",
                "seed": 12345,
                "content_sha256": "a" * 64,
                "audio_parts": 1,
                "review_text": "不该回显的正文",
            },
            via="creation_tts_engine",
        )

    def _sentinel(request: cp.CapabilityRequest) -> cp.InvocationResult:
        raise AssertionError(f"路由绕开中央缝直调了执行体：{request.capability_id}")

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", _fake_invoke)
    from plugins.bot_unified_runtime.domains.creation.tts import engine_provider

    monkeypatch.setattr(engine_provider, "handle", _sentinel)

    response = client.post("/api/v1/tts/jobs", headers=ROOT, json=_job_body())

    assert response.status_code == 200, response.text
    assert len(seen) == 1, f"每次 POST 必须恰过一次中央 invoker，实得 {len(seen)}"
    request = seen[0]
    assert request.capability_id == CID
    assert set(request.payload) == {"job"}, "载荷形状漂移：路由自造了第二套入参形态"
    assert isinstance(request.payload["job"], tts_contracts.TTSJobRequest), "契约真身未复用＝第二份校验"
    assert request.payload["job"].text == _job_body()["text"]
    assert request.request_id == "" and request.session_key == ""

    body = response.json()["data"]
    assert body["state"] == "ok" and body["audio_ready"] is True
    assert body["content_sha256"] == "a" * 64
    # 本机绝对路径与正文都不回显（v1 家规：不暴露 Runtime 文件/内部对象）
    assert "audio_file" not in body and "review_text" not in body
    assert "C:\\secret" not in response.text and "tts-abc.wav" not in response.text
    assert "不该回显的正文" not in response.text


@pytest.mark.parametrize(
    "status",
    [
        cp.InvocationStatus.DENIED,
        cp.InvocationStatus.TIMEOUT,
        cp.InvocationStatus.LIMIT_EXCEEDED,
        cp.InvocationStatus.NOT_CONFIGURED,
        cp.InvocationStatus.UNAVAILABLE,
        cp.InvocationStatus.DEGRADED,
        cp.InvocationStatus.FAILED,
    ],
)
def test_every_non_success_terminal_state_is_never_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: cp.InvocationStatus
) -> None:
    def _fake_invoke(self: Any, request: cp.CapabilityRequest, *, config: Any = None) -> cp.InvocationResult:
        del config
        return cp.InvocationResult(capability_id=request.capability_id, status=status, detail="诚实说明")

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", _fake_invoke)
    response = client.post("/api/v1/tts/jobs", headers=ROOT, json=_job_body())
    assert response.status_code >= 400, f"{status.value} 被折叠成 {response.status_code}"
    error = response.json()["error"]
    assert error["code"].startswith("tts_") and error["message"] == "诚实说明"


# ---------------------------------------------------------------------------
# ② 未配 provider：走真实中央路，诚实失败
# ---------------------------------------------------------------------------
def test_unconfigured_provider_fails_honestly_without_calling_engine(client: TestClient) -> None:
    """不拦 invoker ⇒ 真跑中央权限门/契约/provider 门，这才叫"端到端诚实"。"""
    response = client.post("/api/v1/tts/jobs", headers=ROOT, json=_job_body())
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "tts_unavailable"
    assert error["message"].strip(), "honest_degrade：非成功态必须带原因"
    assert response.json()["data"] is None, "失败态不得携带结果体"


def test_contract_violation_is_422_not_silently_dropped(client: TestClient) -> None:
    body = _job_body(text="", approved_reply_id="r-1")  # text 与 reply_id 二选一，契约自验
    response = client.post("/api/v1/tts/jobs", headers=ROOT, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_get_job_state_is_honest_503_and_invents_nothing(client: TestClient) -> None:
    response = client.get("/api/v1/tts/jobs/job-1", headers=ROOT)
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "tts_job_state_unavailable"
    assert payload["data"] is None, "没有状态源就不许端出一个假 job"
    assert "job_id" not in payload and "state" not in payload


# ---------------------------------------------------------------------------
# ③ 零泄漏
# ---------------------------------------------------------------------------
def test_response_never_echoes_secret_or_env_shaped_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaky = (
        r"engine down sk-ABCDEFGHIJKLMNOP1234 BOT_TTS_API_KEY=supersecretvalue "
        r"at C:\Users\LancyCelestia\secret\a.wav"
    )

    def _fake_invoke(self: Any, request: cp.CapabilityRequest, *, config: Any = None) -> cp.InvocationResult:
        del config
        return cp.InvocationResult(capability_id=request.capability_id, status=cp.InvocationStatus.FAILED, detail=leaky)

    monkeypatch.setattr(cp.CapabilityInvoker, "invoke", _fake_invoke)
    response = client.post("/api/v1/tts/jobs", headers=ROOT, json=_job_body())
    text = response.text
    for needle in ("sk-ABCDEFGHIJKLMNOP1234", "supersecretvalue", r"C:\Users\LancyCelestia\secret\a.wav"):
        assert needle not in text, f"泄漏形态未打码：{needle}"
    assert "engine down" in text, "打码不该把可归因的语义一起抹掉"


# ---------------------------------------------------------------------------
# ④ 唯一入口结构锁 + 注毒自证
# ---------------------------------------------------------------------------
def _doc_string_nodes(tree: ast.AST) -> set[int]:
    """模块/类/函数首句文档串的 id 集合——散文里**提到**禁手是教学，不是走了第二条路。

    不摘掉它们，本尺会把本文件自述的「禁直调 engine_provider」这句话判成违规，
    于是真树常红、谁都改不动——那是门的缺陷，不是码的。
    """
    out: set[int] = set()
    holders: list[Any] = [tree]
    holders.extend(n for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
    for holder in holders:
        body = getattr(holder, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            out.add(id(first.value))
    return out


def _route_ast_violations(source: str) -> list[str]:
    """路由源码的"唯一入口"判据（真树与合成注毒共用同一支尺，防判据与被检物两张皮）。"""
    tree = ast.parse(source)
    docstrings = _doc_string_nodes(tree)
    violations: list[str] = []

    invoke_literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "invoke":
            literals = [
                str(sub.value.value)
                for sub in ast.walk(node)
                if isinstance(sub, ast.keyword)
                and sub.arg == "capability_id"
                and isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, str)
            ]
            invoke_literals.extend(literals or ["<non-literal>"])
    if invoke_literals != [CID]:
        violations.append(f"invoke 字面点必须恰为一处且 id 钉死 {CID}，实得 {invoke_literals}")

    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if isinstance(node, ast.ImportFrom):
            blob = f"{node.module or ''} " + " ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            blob = " ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            blob = node.attr
        elif isinstance(node, ast.Name):
            blob = node.id
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            blob = node.value
        else:
            continue
        for token in _FORBIDDEN_TOKENS:
            if token in blob:
                violations.append(f"路由出现第二条路符号 {token!r}：{blob!r}")
    return violations


def test_route_source_keeps_single_central_entry_point() -> None:
    path = Path(__file__).resolve().parents[1] / ROUTE_SOURCE_REL
    assert _route_ast_violations(path.read_text(encoding="utf-8")) == []


def test_single_entry_lock_has_teeth_against_direct_engine_poison() -> None:
    """注毒：把路由改成直调 engine_provider ⇒ 同一支尺必须报（否则锁是空的）。"""
    real = (Path(__file__).resolve().parents[1] / ROUTE_SOURCE_REL).read_text(encoding="utf-8")
    poisoned = real.replace(
        "invocation = default_invoker().invoke(",
        "invocation = engine_provider.handle(",
    )
    assert poisoned != real, "注毒没落到被测语句上＝空跑（同型假绿在册先例）"
    assert _route_ast_violations(real) == [], "真树本该干净，先让尺自证"
    violations = _route_ast_violations(poisoned)
    assert violations, "注毒未被拦＝这把锁没有牙"
    assert any("engine_provider" in v for v in violations), violations
    assert any("invoke 字面点" in v for v in violations), f"invoke 点消失也须点名：{violations}"
