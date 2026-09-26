"""S07 · C1 引擎适配器 `domains/creation/tts/engine_provider.py` 的离线回归。

全离线纪律：**零网络、零引擎调用**——合成原语一律经 ``synthesize_autodub`` 既有注入缝
（``synth=`` / ``request.context["synthesize"]``）交确定性替身；参考音频用 tmp 目录里的
占位文件只为过 ``pick_ref_audio`` 的「文件存在」判定，不被任何 HTTP 读取。

两组注毒自证（本席的「有牙」判据，见 ``test_two_poison_locks_have_teeth`` 的分解用例）：

- 把 provider 改成「总返成功」→ 失败面四例必红（静音陷阱/超限/引擎失败/未知产出码）；
- 把缓存键或硬顶改成手写常量 → 结构锁必红（本件零数值字面量、零哈希自算、
  零对 ``content_sha256``/``seed`` 的写入）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.creation.tts import engine_provider
from plugins.bot_unified_runtime.domains.media.capabilities import tts
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    INVOKER_ERROR_DATA_KEY,
    CapabilityRequest,
    InvocationStatus,
)

PROVIDER_PATH = (
    Path("plugins/bot_unified_runtime/domains/creation/tts/engine_provider.py")
    .resolve()
)

#: 「未来键」——今天不存在于 config.py；测试里显式挂上只为让 provider 门放行，
#: 生产仍恒 False（诚实 UNAVAILABLE，见 test_provider_gate_* 两例）。
PROVIDER_KEY = "bot_creation_tts_provider"


class _FakeConfig:
    """鸭子配置：只给本件与产出步真身会读的键，缺键由 ``_build_params`` 回预设表。"""

    #: 类级注解（不赋值）：只为让静态检查认识测试里真读的两枚键。
    bot_tts_api_url: str
    bot_tts_output_dir: str

    def __init__(self, **overrides: Any) -> None:
        base: dict[str, Any] = {
            PROVIDER_KEY: "gpt-sovits",
            # 本波新增的**首道**总开关（`engine_provider.handle` 读 `bot_tts_enabled`，缺键即关＝
            # fail-closed）。本件的用例都是"开关开着、往下走"的产出/映射面，故这里显式给 True；
            # "关了就什么都不发"那一格由 `test_tts_creation_gate_reality.py` 专测，不在本件混测。
            "bot_tts_enabled": True,
            "bot_tts_api_url": "http://127.0.0.1:9/never-dialed",
            "bot_tts_gptsovits_dir": "",
            "bot_tts_ref_audios": [],
            "bot_tts_output_dir": "",
            "bot_tts_preset": "",
            "bot_tts_hard_max_chars": 0,
            "bot_tts_max_audio_bytes": 0,
            "bot_tts_max_chars": 0,
            "bot_tts_cache_enabled": True,
            "bot_tts_cache_max_bytes": 0,
            "bot_tts_cache_max_age_days": 0,
            "bot_tts_timeout_seconds": 5.0,
        }
        base.update(overrides)
        self.__dict__.update(base)


def _ref_config(tmp_path: Path, **overrides: Any) -> _FakeConfig:
    """带一条「文件确实存在」的参考音频的配置（``pick_ref_audio`` 只判 is_file）。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-reference-audio")
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "bot_tts_ref_audios": [f"{ref}|这段是参考干声说的话|zh"],
        "bot_tts_output_dir": str(out),
    }
    values.update(overrides)  # 允许逐例覆盖（含把参考音换成读不到的路径）
    return _FakeConfig(**values)


def _fake_synth(payload: Path | None, reason: str = "") -> Any:
    """合成原语替身：记录被调用事实，返回 ``(路径, 失败原因)`` 既有二元形状。"""
    calls: list[dict[str, Any]] = []

    def _synth(**kwargs: Any) -> tuple[Any, str]:
        calls.append(kwargs)
        return (payload, reason)

    _synth.calls = calls  # type: ignore[attr-defined]
    return _synth


def _wav(tmp_path: Path, name: str = "tts-fake.wav", body: bytes = b"RIFFfakepayload") -> Path:
    path = tmp_path / "cards" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _request(config: Any, payload: dict[str, Any], *, synth: Any = None) -> CapabilityRequest:
    context: dict[str, Any] = {"config": config}
    if synth is not None:
        context["synthesize"] = synth
    return CapabilityRequest(
        capability_id="creation.tts.synthesize", payload=payload, roles=("user",), context=context
    )


# ---------------------------------------------------------------------------
# ① 成功路径：只委派、只透传
# ---------------------------------------------------------------------------


def test_success_delegates_to_single_synthesis_port_and_passes_payload(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    audio = _wav(tmp_path)
    synth = _fake_synth(audio)

    code, payload = engine_provider.synthesize_via_engine(config, "守岸人在这里。", synth=synth)

    assert code == "ok"
    assert len(synth.calls) == 1
    called = synth.calls[0]
    # 产出步交下来的参数全部来自真身（preset/config），本席不拼第二份。
    assert called["text"] == "守岸人在这里。"
    assert called["api_url"] == config.bot_tts_api_url
    assert called["output_dir"] == Path(config.bot_tts_output_dir)
    assert payload["audio_file"] == str(audio)
    assert payload["preset_id"]


def test_success_envelope_carries_result_body_and_via_attribution(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    audio = _wav(tmp_path)
    synth = _fake_synth(audio)

    result = engine_provider.handle(_request(config, {"text": "今天风很轻"}, synth=synth))

    assert result.status is InvocationStatus.OK
    assert result.capability_id == "creation.tts.synthesize"
    assert result.via == "creation_tts_engine"
    assert result.data["audio_file"] == str(audio)
    assert result.detail == ""


# ---------------------------------------------------------------------------
# ② 静音陷阱绝不冒充成功
# ---------------------------------------------------------------------------


def test_silence_trap_maps_to_failed_and_never_ok(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    synth = _fake_synth(
        None, "服务不可达：引擎以 200 返回静音伪装产物（静音陷阱：恰好 1 秒空帧）"
    )

    code, payload = engine_provider.synthesize_via_engine(config, "这句本该有声音", synth=synth)
    assert code == "failed"
    assert payload["kind"] == "tts_service_unreachable"
    assert payload["retryable"] is True

    result = engine_provider.handle(_request(config, {"text": "这句本该有声音"}, synth=synth))
    assert result.status is InvocationStatus.FAILED
    assert result.status is not InvocationStatus.OK
    assert "静音" in result.detail
    assert result.data == {}  # 无结果却不带结果体＝冒充成功，信封禁止


# ---------------------------------------------------------------------------
# ③ 超限拒发（且一次都不打引擎）
# ---------------------------------------------------------------------------


def test_over_hard_cap_refuses_without_touching_engine(tmp_path: Path) -> None:
    cap = tts.resolve_hard_max_chars(_FakeConfig(bot_tts_hard_max_chars=6))
    config = _ref_config(tmp_path, bot_tts_hard_max_chars=6)
    synth = _fake_synth(_wav(tmp_path))

    code, payload = engine_provider.synthesize_via_engine(
        config, "这一句远远超过了六个字的生效硬顶", synth=synth
    )

    assert code == "over_cap"
    assert synth.calls == []  # 拒发＝不发：不新增第二条打引擎的路
    assert payload["hard_max_chars"] == cap  # 顶值来自中央唯一家，非本件写死

    result = engine_provider.handle(
        _request(config, {"text": "这一句远远超过了六个字的生效硬顶"}, synth=synth)
    )
    assert result.status is InvocationStatus.LIMIT_EXCEEDED
    assert result.data == {}


# ---------------------------------------------------------------------------
# ④ 失败枚举可归因（带引擎原因串、不含密钥）
# ---------------------------------------------------------------------------


def test_failure_detail_is_attributable_and_secret_free(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    synth = _fake_synth(
        None,
        "服务返回 500：Authorization: Bearer sk-abcdefghij123456 参考 C:/Users/x/.env",
    )

    result = engine_provider.handle(_request(config, {"text": "说点什么"}, synth=synth))

    assert result.status is InvocationStatus.FAILED
    assert result.detail.startswith("tts_service_rejected：")  # 归因来自唯一分类口
    assert "sk-abcdefghij123456" not in result.detail  # 密钥不外泄
    assert "C:/Users/x/.env" not in result.detail  # 本机路径不外泄


def test_no_ref_audio_maps_not_configured_without_calling_engine(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.wav"
    config = _ref_config(tmp_path, bot_tts_ref_audios=[f"{missing}|参考|zh"])
    synth = _fake_synth(_wav(tmp_path))

    code, payload = engine_provider.synthesize_via_engine(config, "有字没有声", synth=synth)

    assert code == "no_ref"
    assert synth.calls == []
    assert payload["reason"]  # 诚实说明来自真身唯一文案口，非空转

    result = engine_provider.handle(_request(config, {"text": "有字没有声"}, synth=synth))
    assert result.status is InvocationStatus.NOT_CONFIGURED


def test_unknown_produce_code_is_never_folded_into_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _ref_config(tmp_path)
    monkeypatch.setattr(tts, "synthesize_autodub", lambda *a, **k: ("weird", "引擎说了句怪话"))

    code, payload = engine_provider.synthesize_via_engine(config, "这句要看出诚实度")

    assert code == "failed"
    assert payload["kind"] == tts._failure_kind_tag(payload["reason"])

    result = engine_provider.handle(_request(config, {"text": "这句要看出诚实度"}))
    assert result.status is InvocationStatus.FAILED
    assert result.data == {}


def test_ok_without_audio_file_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产出步自称 ok 却拿不出产物 → 仍判失败（不拿别人的 ok 当自己的成功）。"""
    config = _ref_config(tmp_path)
    monkeypatch.setattr(tts, "synthesize_autodub", lambda *a, **k: ("ok", {"preset_id": "x"}))

    code, payload = engine_provider.synthesize_via_engine(config, "空口无凭")

    assert code == "failed"
    assert "不冒充成功" in payload["reason"]


# ---------------------------------------------------------------------------
# 内容门与取文：只委派唯一口，不抄第二份
# ---------------------------------------------------------------------------


def test_session_content_gate_is_delegated_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _ref_config(tmp_path)
    seen: dict[str, Any] = {}

    def _fake_resolve(cfg: Any, message: Any, raw: str, **kwargs: Any) -> tuple[str, str]:
        seen["cfg"] = cfg
        seen["message"] = message
        seen["raw"] = raw
        return "", "会话内容门：这句不适合念出来"

    monkeypatch.setattr(tts, "resolve_speech_text", _fake_resolve)
    message = object()

    code, payload = engine_provider.synthesize_via_engine(
        config, "随便一句", message=message, synth=_fake_synth(_wav(tmp_path))
    )

    assert code == "blocked"
    assert seen["message"] is message and seen["raw"] == "随便一句"
    assert payload["reason"].startswith("会话内容门")

    result = engine_provider.handle(
        _request(config, {"text": "随便一句", "message": message}, synth=_fake_synth(_wav(tmp_path)))
    )
    assert result.status is InvocationStatus.DENIED


def test_job_form_goes_through_contract_self_validation(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    audio = _wav(tmp_path)
    job = {
        "text": "这是契约自验过的定稿文本",
        "provider": "gpt-sovits",
        "model": "v2ProPlus",
        "voice": "shorekeeper",
        "language": "zh",
        "format": "wav",
        "workspace_id": "ws-1",
        "target": "qq",
        "version": "1",
    }

    result = engine_provider.handle(_request(config, {"job": job}, synth=_fake_synth(audio)))
    assert result.status is InvocationStatus.OK
    assert result.data["audio_file"] == str(audio)

    both = dict(job, approved_reply_id="reply-1")
    denied = engine_provider.handle(_request(config, {"job": both}, synth=_fake_synth(audio)))
    assert denied.status is InvocationStatus.FAILED
    assert "契约自验" in denied.detail

    reply_only = {k: v for k, v in job.items() if k != "text"} | {"approved_reply_id": "reply-1"}
    honest = engine_provider.handle(_request(config, {"job": reply_only}, synth=_fake_synth(audio)))
    assert honest.status is InvocationStatus.FAILED
    assert "不猜文本" in honest.detail


# ---------------------------------------------------------------------------
# provider 门：未落地键 ⇒ 诚实 UNAVAILABLE（现网今天就是这一态）
# ---------------------------------------------------------------------------


def test_provider_gate_unconfigured_is_honest_unavailable(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    delattr(config, PROVIDER_KEY)
    # 中央调度收编波 P4-甲案后，「provider 已配」认的是引擎现役配置键
    # （bot_tts_api_url / bot_tts_ref_audios，与 bot.tts 同一判定源）⇒
    # 「门关着」这一形必须三把键一起关，否则测的是"半开的门"。
    config.bot_tts_api_url = ""
    config.bot_tts_ref_audios = []
    synth = _fake_synth(_wav(tmp_path))

    result = engine_provider.handle(_request(config, {"text": "门关着就不该打引擎"}, synth=synth))

    assert result.status is InvocationStatus.UNAVAILABLE
    assert PROVIDER_KEY in result.detail  # 点名待配的键，不静默
    # 改因（S209 现算跟随真值，非放宽）：中央调度收编波 #49/语音 P4-甲案已把诚实
    # UNAVAILABLE 的「缺 provider」终态定成【仍不新增状态】，但按 INVOKER_ERROR_DATA_KEY
    # 多挂一条可归因异常交回层 1 出诊断卡——真身白纸黑字：engine_provider.handle docstring
    # 「provider 未配（在册键全空）→ UNAVAILABLE＋INVOKER_ERROR_DATA_KEY」与
    # CreationTtsNotWired 类注「终态仍是不新增的 UNAVAILABLE，只是多挂一条可归因异常」。
    # 旧断言 `result.data == {}` 与该在册契约直接冲突（账实不符），故按真值改判为：
    # data 只准带这一枚诊断异常键（诚实态不混入任何结果体），且异常类型必须是
    # CreationTtsNotWired。前后值：`{} → {INVOKER_ERROR_DATA_KEY: CreationTtsNotWired(...)}`。
    # 复跑：../ChatBot_Runtime/venv/Scripts/python.exe -m pytest "tests/test_creation_tts_engine_provider.py::test_provider_gate_unconfigured_is_honest_unavailable" -p no:cacheprovider --basetemp=<私有唯一目录> -q
    assert set(result.data) == {INVOKER_ERROR_DATA_KEY}, (
        f"未接线诚实态只准带诊断异常一枚键，实际 data 键集={sorted(result.data)}"
        "（混入结果体＝冒充已产出，信封禁止）"
    )
    assert "audio_file" not in result.data  # 无结果却不带结果体＝冒充成功
    assert isinstance(result.data[INVOKER_ERROR_DATA_KEY], engine_provider.CreationTtsNotWired)
    assert synth.calls == []


# ---------------------------------------------------------------------------
# 同句恒同音色 + 缓存身份只透传（沿用既有 seed 派生实现）
# ---------------------------------------------------------------------------


def test_same_text_keeps_same_seed_and_real_digest(tmp_path: Path) -> None:
    config = _ref_config(tmp_path)
    audio = _wav(tmp_path)

    _, first = engine_provider.synthesize_via_engine(
        config, "同一句话应当同一个音色", synth=_fake_synth(audio)
    )
    _, second = engine_provider.synthesize_via_engine(
        config, "同一句话应当同一个音色", synth=_fake_synth(audio)
    )
    _, other = engine_provider.synthesize_via_engine(
        config, "另一句不同的话会换一张脸", synth=_fake_synth(audio)
    )

    assert first["seed"] == second["seed"]
    assert first["seed"] != other["seed"]
    # 摘要与落盘字节同源同值：由真身 _content_digest_for 现算，本件不改写。
    assert first["content_sha256"] == tts._content_digest_for(Path(audio))


# ---------------------------------------------------------------------------
# ⑤ 结构锁：本件零数值字面量、零第二条引擎路、零缓存键自算
# ---------------------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))


def test_provider_has_no_numeric_literals_at_all() -> None:
    """任何数值顶/键/时长一旦写死即红（生效顶唯一家=tts_presets 现读）。"""
    offenders: list[str] = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(
            node.value, bool
        ):
            offenders.append(f"{node.lineno}:{node.value!r}")
    assert offenders == []


def test_provider_never_builds_its_own_cache_identity_or_engine_call() -> None:
    banned_attrs = {
        "sha256",
        "_cache_key",
        "_cache_identity",
        "_ref_fingerprint",
        "derive_seed",
        "media_digest_file",
        "digest_file",
        "write_bytes",
        "mkdir",
        "urlopen",
    }
    banned_imports = {"hashlib", "httpx", "requests", "socket", "urllib", "uuid"}
    hits_attr = {
        node.attr
        for node in ast.walk(_tree())
        if isinstance(node, ast.Attribute) and node.attr in banned_attrs
    }
    hits_import: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            hits_import |= {str(alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            hits_import.add(node.module.split(".")[0])
    assert hits_attr == set()
    assert hits_import & banned_imports == set()


def test_provider_never_writes_content_sha256_or_seed_by_hand() -> None:
    """缓存身份/seed 只准透传产出步的成品：出现写入手/常量即红。"""
    tree = _tree()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            name = (
                target.id
                if isinstance(target, ast.Name)
                else (
                    target.slice.value  # type: ignore[union-attr]
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                    else ""
                )
            )
            if str(name) in {"content_sha256", "seed", "cache_key"}:
                offenders.append(f"{getattr(node, 'lineno', 0)}:{name!s}")
    assert offenders == []
    # 64 位十六进制字面量＝手写摘要，出现即红。
    hexish = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) == 64
        and all(ch in "0123456789abcdef" for ch in node.value)
    ]
    assert hexish == []


def test_provider_module_is_offline_import_clean() -> None:
    """模块期零副作用：不 import 中央壳、不 import http 客户端（延迟导入在函数体内）。"""
    top = [
        (node.module or "") if isinstance(node, ast.ImportFrom) else node.names[0].name
        for node in _tree().body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
    ]
    module_level = [str(name) for name in top if "capability_protocols" in str(name)]
    assert module_level == []
    assert "collections.abc" in [str(name) for name in top]


def test_two_poison_locks_have_teeth(tmp_path: Path) -> None:
    """两发注毒的「有牙」判据（本用例只证断言方向，不在盘上真改代码）。

    - 若 provider 改成总返成功：失败面必红——此处以「ok 却无产物」这条最窄注毒面
      直接构造（产出步返回 ``ok`` + 空 data），断言仍判失败。
    - 若缓存键改成手写常量：结构锁 ``test_provider_never_writes_content_sha256_or_seed_by_hand``
      与 ``test_provider_has_no_numeric_literals_at_all`` 的判据均为「出现即红」，
      其杀伤力由 ``test_provider_*`` 两例的负样本逻辑（同一 AST 路径遍历）保证。
    """
    config = _ref_config(tmp_path)

    def _poisoned_autodub(*_a: Any, **_k: Any) -> tuple[str, Any]:
        return "ok", {"preset_id": "poisoned"}  # 注毒形：自称成功、拿不出产物

    original = tts.synthesize_autodub
    tts.synthesize_autodub = _poisoned_autodub  # type: ignore[assignment]
    try:
        code, payload = engine_provider.synthesize_via_engine(config, "注毒探针")
        assert code == "failed"
        assert "不冒充成功" in payload["reason"]
        assert engine_provider.handle(_request(config, {"text": "注毒探针"})).status is (
            InvocationStatus.FAILED
        )
    finally:
        tts.synthesize_autodub = original  # type: ignore[assignment]
