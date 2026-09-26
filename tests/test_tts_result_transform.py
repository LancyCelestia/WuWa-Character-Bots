"""S36 · 「结果变换形」执行体 ``domains/media/tts/result_transform.py`` 的锁。

被检件的分工（读绿之前先记住）：本件**已在册、已通电**（S36 落件时的旧口径
「未接根装配、未进中央注册册」被 S91 收编推翻、S253B 现算复核 ⇒ 判据方向随之翻面：
``test_this_shape_is_wired_into_central_dispatch_now`` 钉「descriptor + handler + hook
唯一 invoke 点 + 根仍零直连」四判）。但"通电"不等于"生效"：现网
``bot_tts_voice_hook_enabled`` 缺省 False 且 ``.env`` 未设、
``bot_tts_auto_reply_enabled=false`` ⇒ 今天该腿**关态不可达**、生产行为逐字节不变。
它补的是中央 Wave 4 缺的第三执行形态：``command``/``prepared`` 的执行体都是
``(message, decision) -> 呈现结果``，**没有「前序结果」通道**，而自动配音是
review 批准后的一次「呈现结果 → 带音频的呈现结果」。

五把承重锁（对应简报五条纪律，逐条可归因）：

1. **形状变换正确性** —— ``test_transform_*`` / ``test_envelope_*``：正文零改动、
   音频经唯一消费口挂回、信封只经 ``PRESENTATION_DATA_KEY`` 交呈现 dump。
2. **硬顶现读（写死必红）** —— ``test_module_has_no_numeric_literals``（AST：本件源码
   里 int/float 常量**一个都不许有**）＋ ``test_text_hard_cap_is_read_live_not_hardcoded``
   （把 ``bot_tts_hard_max_chars`` 配成比任何写死值都小的数 ⇒ 必须改判；两者合起来
   才是"现读"的正反两腿：只测行为会放过"恰好相等"的巧合绿，只测源码会放过"读了但不用"）。
3. **同句恒同音色不被破坏** —— ``test_same_sentence_keeps_same_seed_and_digest``
   （两次变换 ⇒ ``seed=``/``content_sha256`` 与出站体逐字段等值）＋
   ``test_module_never_touches_seed_or_digest_machinery``（本件不派 seed、不算摘要、
   不改文本：把"透传"钉成结构判据，谁在此加一枚 seed 覆盖就红）。
4. **失败不静默** —— ``test_synthesis_failure_attaches_issue_*`` / ``test_no_ref_maps_*``
   （挂既有 issue、kind 走 tts 前缀表）＋ ``test_policy_and_oversize_are_tags_not_faults``
   （政策拒绝/超顶/清洗为空≠故障：只留痕、不挂 issue、零中央调用）。
5. **关态逐字节同形** —— ``test_hook_disabled_returns_the_same_object``
   （连 ``model_copy`` 都不做：同一实例 + dump 等值 + 零产出步调用）。

另附**门的自证**（反向毒饵一律走内存合成源码，不往源码树写一个字）：
AST 判据必须看得见注毒形态，否则"零命中"只是尺子瞎。

全离线零网络：产出步用确定性替身注入（与生产同一个 ``dub`` seam）；取文口的
内容门 ``speech_block_reason`` 在 tts 命名空间被 stub（政策判定不是本件的职责面），
清洗/截断/词典那段仍走真身，保证"取文唯一口"是被真跑出来的、不是被 mock 掉的说法。
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.tts import result_transform as rt
from plugins.bot_unified_runtime.runtime import capability_protocols as cp

_PKG_ROOT = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "tts"
    / "result_transform.py"
)
_ROOT_INIT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime" / "__init__.py"
_SHELL = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "runtime"
    / "capability_protocols.py"
)


# ---------------------------------------------------------------------------
# AST 判据（参数收源码，毒饵走合成内存）
# ---------------------------------------------------------------------------
def _tree(source: str) -> ast.Module:
    return ast.parse(source)


def _numeric_literals(tree: ast.Module) -> list[ast.Constant]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float, complex))
        and not isinstance(node.value, bool)
    ]


def _invoke_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "invoke"
    ]


def _literal_capability_ids(tree: ast.Module) -> set[str]:
    """``….invoke(CapabilityRequest(capability_id="x"))`` 形态的字面 id（与 S0/S1 门同尺）。"""
    found: set[str] = set()
    for call in _invoke_calls(tree):
        for sub in ast.walk(call):
            if (
                isinstance(sub, ast.keyword)
                and sub.arg == "capability_id"
                and isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, str)
            ):
                found.add(sub.value.value)
    return found


def _call_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _keyword_names(tree: ast.Module) -> set[str]:
    return {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and isinstance(node.arg, str)
    }


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _message(*, group_id: str = "", sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id=f"group_{group_id}_{sender_id}" if group_id else f"private:{sender_id}",
        session_type=SessionType.GROUP if group_id else SessionType.PRIVATE,
        sender_id=sender_id,
        group_id=group_id,
        plain_text="今天天气不错",
        message_id="m-1",
        debug_id="dbg-1",
    )


def _result(body: str = "潮汐今天很安静。", **over: Any) -> CapabilityResult:
    payload: dict[str, Any] = {
        "request_id": "req-1",
        "capability_id": "bot.chat",
        "kind": "text",
        "body": body,
        "send_policy": SendPolicy.IMMEDIATE,
        "audit_tags": ["chat"],
    }
    payload.update(over)
    return CapabilityResult(**payload)


def _config(tmp_path: Path, **over: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "bot_tts_voice_hook_enabled": True,
        "bot_tts_enabled": True,
        "bot_tts_auto_reply_enabled": True,
        "bot_tts_auto_reply_scope": "private",
        "bot_tts_auto_reply_max_chars": 120,
        "bot_tts_auto_reply_split_max_chars": 0,
        "bot_tts_api_url": "http://127.0.0.1:9880",
        "bot_tts_gptsovits_dir": "",
        "bot_tts_ref_audios": [f"{tmp_path / 'ref.wav'}|参考文本|zh"],
        "bot_tts_output_dir": str(tmp_path / "tts_out"),
        "bot_tts_preset": "shorekeeper",
        "bot_tts_max_chars": 200,
        "bot_tts_hard_max_chars": 2000,
        "bot_tts_max_audio_bytes": 0,
        "bot_tts_cache_enabled": False,
        "bot_tts_cache_max_bytes": 0,
        "bot_tts_cache_max_age_days": 0,
        "bot_tts_timeout_seconds": 60.0,
        "bot_tts_auto_reply_probability": 1.0,
        "bot_tts_auto_reply_always": True,
    }
    values.update(over)
    return SimpleNamespace(**values)


def _dub_ok(text: str) -> rt.DubOutcome:
    """确定性配音替身：seed 与摘要都只由**文本**派生（生产同一形状：seed=cache_key 派生）。

    因此"同句恒同音色"可断言，而本件若改动交下来的文本、或私自覆盖 seed，
    两次结果就会不一致 ⇒ 锁红。
    """
    derived = hashlib.sha256(text.encode("utf-8")).hexdigest()
    part = {
        "file": f"/fake/tts-{derived[:8]}.wav",
        "review_text": text,
        "content_sha256": f"sha256:{derived}",
    }
    return rt.DubOutcome(
        rt.OUTCOME_DUBBED,
        {
            "audio_parts": [part],
            "audit_tags_delta": [
                "tts",
                "auto_reply",
                "preset=shorekeeper",
                f"seed={derived[:12]}",
                f"audio_sha256={derived[:16]}",
            ],
        },
    )


@pytest.fixture()
def open_policy(monkeypatch: pytest.MonkeyPatch):
    """放行内容门（政策判定不是本件职责面），清洗/截断/词典仍走真身。"""
    monkeypatch.setattr(tts_mod, "speech_block_reason", lambda *a, **k: "")


@pytest.fixture()
def gates_pass(monkeypatch: pytest.MonkeyPatch):
    """门链谓词放行（本件不重测 should_voice_reply 的七道门）。"""
    monkeypatch.setattr(rt, "should_voice_reply", lambda *a, **k: True)


# ---------------------------------------------------------------------------
# 纪律⑤：关态逐字节同形
# ---------------------------------------------------------------------------
def test_hook_disabled_returns_the_same_object(tmp_path: Path, gates_pass: None) -> None:
    config = _config(tmp_path, bot_tts_voice_hook_enabled=False)
    original = _result()
    calls: list[str] = []

    enriched, code = rt.transform_presentation(
        config, _message(), original, dub=lambda text: calls.append(text) or _dub_ok(text)
    )
    assert code == rt.OUTCOME_HOOK_DISABLED
    # 承重：同一实例（连 model_copy 都没发生）⇒ 关态与接入本件前逐字节同形。
    assert enriched is original
    assert calls == []


def test_preexisting_issue_is_never_overwritten(tmp_path: Path, gates_pass: None) -> None:
    original = _result(
        operational_issue=tts_mod._issue(
            _message(), kind="chat_failed", retryable=False, detail="先到的证据"
        )
    )
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), original, dub=_dub_ok
    )
    assert code == rt.OUTCOME_GATE_REFUSED
    assert enriched is original


def test_gate_predicate_refuses_without_any_dub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt, "should_voice_reply", lambda *a, **k: False)
    calls: list[str] = []
    original = _result()
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), original, dub=lambda t: calls.append(t) or _dub_ok(t)
    )
    assert code == rt.OUTCOME_GATE_REFUSED
    assert enriched is original and calls == []


# ---------------------------------------------------------------------------
# 锁 1：形状变换正确性
# ---------------------------------------------------------------------------
def test_transform_attaches_audio_and_leaves_body_untouched(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    original = _result("潮汐今天很安静。")
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), original, dub=_dub_ok
    )
    assert code == rt.OUTCOME_DUBBED
    assert enriched.body == original.body and enriched.summary == original.summary
    assert enriched.operational_issue is None
    assert len(enriched.audio) == len(_dub_ok("潮汐今天很安静。").data["audio_parts"])
    assert enriched.audio[0]["review_text"] == "潮汐今天很安静。"
    # 既有标签在前、增量在后（顺序=出站契约在册口径）。
    assert enriched.audit_tags[:1] == ["chat"]
    assert "tts" in enriched.audit_tags and "auto_reply" in enriched.audit_tags


def test_text_handed_to_dub_is_exactly_what_intake_returned(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """纪律②③：本件不改文本——取文口交出的那段，就是交给产出步的那段。"""
    raw_shape = "  潮汐**很**安静（笑了笑）\n第二行  "
    seen: list[str] = []

    def fake_intake(config: Any, message: Any, text: Any, **kw: Any) -> tuple[str, str]:
        kw.get("audit", {}).update({"raw_len": 1})
        return raw_shape, ""

    def dub(text: str) -> rt.DubOutcome:
        seen.append(text)
        return _dub_ok(text)

    monkeypatch.setattr(rt, "resolve_speech_text", fake_intake)
    config = _config(tmp_path)
    # 拆条键缺席 ⇒ 本件不拆、也不许"顺手 strip/清洗"第二遍：交出的就是取文口出的那段。
    delattr(config, "bot_tts_auto_reply_split_max_chars")
    enriched, code = rt.transform_presentation(
        config, _message(), _result("anything"), dub=dub
    )
    assert code == rt.OUTCOME_DUBBED
    assert seen == [raw_shape], "产出步收到的文本必须与取文口出参逐字节相同（无二次加工）"
    assert enriched.audio[0]["review_text"] == raw_shape

    # 拆条键在场 ⇒ 切块由真身 `split_speech_chunks` 裁决，本件只转交它的答案。
    seen.clear()
    cap_config = _config(tmp_path, bot_tts_auto_reply_split_max_chars=8)
    rt.transform_presentation(cap_config, _message(), _result("anything"), dub=dub)
    assert seen == tts_mod.split_speech_chunks(raw_shape, 8)


def test_intake_is_the_single_speech_source_and_is_actually_called(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """取文唯一口＝活性判据：本件不走它就拿不到文本（stub 成拒绝 ⇒ 零配音）。"""
    monkeypatch.setattr(rt, "resolve_speech_text", lambda *a, **k: ("", ""))
    calls: list[str] = []
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), _result(), dub=lambda t: calls.append(t) or _dub_ok(t)
    )
    assert code == rt.OUTCOME_EMPTY_AFTER_CLEAN
    assert calls == [] and enriched.audio == []
    assert "auto_reply_skipped" in enriched.audit_tags
    assert "empty_after_clean" in enriched.audit_tags


# ---------------------------------------------------------------------------
# 锁 2：硬顶现读，写死必红
# ---------------------------------------------------------------------------
def test_text_hard_cap_is_read_live_not_hardcoded(tmp_path: Path, gates_pass: None, open_policy: None) -> None:
    body = "潮汐今天很安静。" * 8  # 远小于任何 conceivable 写死值（2000），但大于 1
    calls: list[str] = []

    def dub(text: str) -> rt.DubOutcome:
        calls.append(text)
        return _dub_ok(text)

    tight, code_tight = rt.transform_presentation(
        _config(tmp_path, bot_tts_hard_max_chars=1, bot_tts_auto_reply_max_chars=0),
        _message(),
        _result(body),
        dub=dub,
    )
    assert code_tight == rt.OUTCOME_OVER_HARD_CAP and calls == []
    assert "over_hard_cap" in tight.audit_tags
    assert any(tag.startswith("len=") for tag in tight.audit_tags)
    assert any(tag.startswith("cap=") for tag in tight.audit_tags)
    # 顶放宽（仍走现读）⇒ 同一条文本就该配出来。
    _loose, code_loose = rt.transform_presentation(
        _config(tmp_path, bot_tts_hard_max_chars=len(body), bot_tts_auto_reply_max_chars=0),
        _message(),
        _result(body),
        dub=dub,
    )
    assert code_loose == rt.OUTCOME_DUBBED and len(calls) == 1


def test_module_has_no_numeric_literals() -> None:
    """纪律①的源码腿：生效顶只许现读中央件 ⇒ 本件源码里 int/float 常量必须为 0 枚。

    这是"写死 2000"那发注毒的直接杀手：任何硬编码阈值（含 0 这样的哨兵）都会被抓。
    行为腿见上一条——两腿合起来才叫"现读"。
    """
    offenders = _numeric_literals(_tree(_PKG_ROOT.read_text(encoding="utf-8")))
    assert not offenders, (
        f"结果变换形出现 {len(offenders)} 处数值字面量（生效顶必须现读中央件）："
        f"{[(n.lineno, n.value) for n in offenders]}"
    )


def test_numeric_literal_checker_fires_on_synthetic_poison() -> None:
    """自证：上面那把尺子看得见硬编码（否则"零命中"只是尺子瞎）。"""
    assert _numeric_literals(_tree("HARD = 2000\n"))
    assert _numeric_literals(_tree("if len(x) > 2000:\n    pass\n"))
    assert not _numeric_literals(_tree("CAP = resolve_hard_max_chars(config)\n"))


# ---------------------------------------------------------------------------
# 锁 3：同句恒同音色（透传），本件不碰 seed/摘要机器
# ---------------------------------------------------------------------------
def test_same_sentence_keeps_same_seed_and_digest(tmp_path: Path, gates_pass: None, open_policy: None) -> None:
    config = _config(tmp_path)
    first, code_first = rt.transform_presentation(config, _message(), _result(), dub=_dub_ok)
    second, code_second = rt.transform_presentation(
        config, _message(sender_id="u2", group_id=""), _result(), dub=_dub_ok
    )
    assert code_first == code_second == rt.OUTCOME_DUBBED
    seed_first = [t for t in first.audit_tags if t.startswith("seed=")]
    seed_second = [t for t in second.audit_tags if t.startswith("seed=")]
    assert seed_first == seed_second and seed_first, "同句必须同 seed 标签（音色锚）"
    assert first.audio[0]["content_sha256"] == second.audio[0]["content_sha256"]
    # 出站体逐字段原样透传（本件不裁、不补、不改名）。
    assert first.audio[0] == _dub_ok(first.audio[0]["review_text"]).data["audio_parts"][0]


def test_module_never_touches_seed_or_digest_machinery() -> None:
    """结构腿：seed/摘要/缓存键的家在产出步，本件只透传。"""
    tree = _tree(_PKG_ROOT.read_text(encoding="utf-8"))
    names = _call_names(tree)
    keywords = _keyword_names(tree)
    banned_calls = {
        "derive_seed",
        "synthesize",
        "synthesize_autodub",
        "clean_for_speech",
        "_clean_for_speech_tracked",
        "redact_local_secrets",
        "sha256",
        "hashlib",
    }
    assert not (names & banned_calls), f"结果变换形触碰了产出步机器：{sorted(names & banned_calls)}"
    assert "seed" not in keywords, "本件不得给产出步塞 seed 覆盖（同句恒同音色锚会被打断）"


def test_seed_override_poison_is_visible_to_the_checker() -> None:
    """自证：上面那把尺子对"偷偷覆盖 seed"有牙。"""
    poison = (
        "from plugins.bot_unified_runtime.domains.media.capabilities.tts import derive_seed\n"
        "def f(cfg, text):\n"
        "    return dub(text, seed=derive_seed(text))\n"
    )
    tree = _tree(poison)
    assert "derive_seed" in _call_names(tree)
    assert "seed" in _keyword_names(tree)


# ---------------------------------------------------------------------------
# 锁 4：失败不静默 / 非故障不冒充故障
# ---------------------------------------------------------------------------
def test_synthesis_failure_attaches_issue_and_keeps_text(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    original = _result()
    enriched, code = rt.transform_presentation(
        _config(tmp_path),
        _message(),
        original,
        dub=lambda t: rt.DubOutcome(rt.OUTCOME_FAILED, {}, "服务不可达：连接被拒绝"),
    )
    assert code == rt.OUTCOME_FAILED
    issue = enriched.operational_issue
    assert issue is not None, "合成失败必须可见（禁静默）"
    assert issue.kind == "tts_service_unreachable"  # 既有前缀表分类，禁新造 kind
    assert enriched.body == original.body and enriched.audio == []


def test_generic_failure_detail_falls_back_to_synthesize_failed_kind(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    enriched, code = rt.transform_presentation(
        _config(tmp_path),
        _message(),
        _result(),
        dub=lambda t: rt.DubOutcome(rt.OUTCOME_FAILED, {}, "引擎回了个没见过的东西"),
    )
    assert code == rt.OUTCOME_FAILED
    assert enriched.operational_issue is not None
    assert enriched.operational_issue.kind == "tts_synthesize_failed"


def test_no_ref_maps_to_existing_deterministic_issue_code(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), _result(), dub=lambda t: rt.DubOutcome(rt.OUTCOME_NO_REF)
    )
    assert code == rt.OUTCOME_NO_REF
    issue = enriched.operational_issue
    assert issue is not None and issue.kind == "tts_no_ref_audio"
    assert issue.retryable is False


def test_transform_crash_is_visible_not_swallowed(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> tuple[str, str]:
        raise RuntimeError("取文口炸了")

    monkeypatch.setattr(rt, "resolve_speech_text", boom)
    original = _result()
    enriched, code = rt.transform_presentation(_config(tmp_path), _message(), original, dub=_dub_ok)
    assert code == rt.OUTCOME_FAILED
    assert enriched.operational_issue is not None
    assert enriched.body == original.body  # 正文照发


def test_policy_and_oversize_are_tags_not_faults(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(rt, "resolve_speech_text", lambda *a, **k: ("", "minors"))
    original = _result()
    enriched, code = rt.transform_presentation(
        _config(tmp_path), _message(), original, dub=lambda t: calls.append(t) or _dub_ok(t)
    )
    assert code == rt.OUTCOME_POLICY_BLOCKED
    assert enriched.operational_issue is None, "政策拒绝≠故障（在册裁定）"
    assert "blocked_by_policy" in enriched.audit_tags
    assert calls == [], "政策拦下就不该进产出步（零合成、零中央审计行）"


# ---------------------------------------------------------------------------
# 拆条：多块合并与半程故障
# ---------------------------------------------------------------------------
def test_multi_chunk_merge_keeps_every_part_and_labels_the_count(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt, "resolve_speech_text", lambda *a, **k: ("甲乙丙丁", ""))
    config = _config(tmp_path, bot_tts_auto_reply_split_max_chars=2)
    enriched, code = rt.transform_presentation(config, _message(), _result(), dub=_dub_ok)
    assert code == rt.OUTCOME_DUBBED
    assert len(enriched.audio) > 1, "拆条后各块音频部件都要挂回同一条回复"
    assert any(tag.startswith("seed=") for tag in enriched.audit_tags)


def test_partial_failure_keeps_delivered_parts_and_labels_missing_tail(
    tmp_path: Path, gates_pass: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt, "resolve_speech_text", lambda *a, **k: ("甲乙丙丁", ""))
    seen: list[str] = []

    def dub(text: str) -> rt.DubOutcome:
        seen.append(text)
        if len(seen) > 1:
            return rt.DubOutcome(rt.OUTCOME_FAILED, {}, "服务返回空音频")
        return _dub_ok(text)

    config = _config(tmp_path, bot_tts_auto_reply_split_max_chars=2)
    enriched, code = rt.transform_presentation(config, _message(), _result(), dub=dub)
    assert len(enriched.audio) == 1
    assert enriched.operational_issue is None, "半程故障不挂 issue（防刷屏，增益面在册口径）"
    assert any(tag.startswith("split=") for tag in enriched.audit_tags), "缺角必须如实记账"
    assert code == rt.OUTCOME_DUBBED


# ---------------------------------------------------------------------------
# 信封面（结果变换形对中央的形状）
# ---------------------------------------------------------------------------
def _request(payload: dict[str, Any], context: dict[str, Any]) -> cp.CapabilityRequest:
    return cp.CapabilityRequest(
        capability_id=rt.PROPOSED_CAPABILITY_ID,
        payload=payload,
        principal="u1",
        roles=("user",),
        request_id="req-1",
        session_key="private:u1",
        context=context,
    )


def test_envelope_returns_presentation_dump_under_the_single_channel(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    original = _result()
    result = rt.handle(
        _request(
            {"message": _message(), "result": original.model_dump()},
            {"config": _config(tmp_path), "dub": _dub_ok},
        )
    )
    assert result.status is cp.InvocationStatus.OK
    assert result.detail.startswith(f"{rt.TRANSFORM_SHAPE}:")
    payload = result.data[cp.PRESENTATION_DATA_KEY]
    assert isinstance(payload, dict) and payload["audio"], "只经唯一跨层通道交呈现 dump"
    assert CapabilityResult.model_validate(payload).audit_tags == rt.transform_presentation(
        _config(tmp_path), _message(), original, dub=_dub_ok
    )[0].audit_tags


def test_envelope_without_dub_step_is_unavailable_and_carries_no_payload(
    tmp_path: Path, gates_pass: None, open_policy: None
) -> None:
    result = rt.handle(
        _request(
            {"message": _message(), "result": _result().model_dump()},
            {"config": _config(tmp_path)},
        )
    )
    assert result.status is cp.InvocationStatus.UNAVAILABLE
    assert cp.PRESENTATION_DATA_KEY not in result.data, "未通电不得冒充产出了结果"
    assert result.detail.strip(), "非成功终态必须给诚实说明"


def test_envelope_rejects_malformed_payload_without_payload(
    tmp_path: Path,
) -> None:
    result = rt.handle(_request({"message": _message()}, {"config": _config(tmp_path), "dub": _dub_ok}))
    assert result.status is cp.InvocationStatus.FAILED
    assert result.data == {}
    bad_shape = rt.handle(
        _request(
            {"message": _message(), "result": {"nope": 1}},
            {"config": _config(tmp_path), "dub": _dub_ok},
        )
    )
    assert bad_shape.status is cp.InvocationStatus.FAILED and bad_shape.data == {}


def test_status_to_code_mapping_reuses_existing_terminal_family() -> None:
    """中央终态 → 本件三态码，词族不新增第四态（与 voice_enricher 现行口径同字）。"""
    cases = {
        cp.InvocationStatus.OK: rt.OUTCOME_DUBBED,
        cp.InvocationStatus.FALLBACK_OK: rt.OUTCOME_DUBBED,
        cp.InvocationStatus.NOT_CONFIGURED: rt.OUTCOME_NO_REF,
        cp.InvocationStatus.FAILED: rt.OUTCOME_FAILED,
        cp.InvocationStatus.DEGRADED: rt.OUTCOME_FAILED,
        cp.InvocationStatus.TIMEOUT: rt.OUTCOME_FAILED,
        cp.InvocationStatus.DENIED: rt.OUTCOME_FAILED,
        cp.InvocationStatus.LIMIT_EXCEEDED: rt.OUTCOME_FAILED,
        cp.InvocationStatus.UNAVAILABLE: rt.OUTCOME_FAILED,
    }
    for status, expected in cases.items():
        invocation = SimpleNamespace(status=status, data={"audio_parts": []}, detail="d")
        assert rt.dub_outcome_from_invocation(invocation).code == expected, status


# ---------------------------------------------------------------------------
# 通电常态化锁（S91 收编：旁路判据翻成常态正向锁，强度不降——见 S36 §6.2 约定）
# ---------------------------------------------------------------------------
def test_this_shape_is_wired_into_central_dispatch_now() -> None:
    """第三形已并入中央派发谱：壳注册 media.tts.autodub_transform + voice_enricher 派它，
    而根仍不直接引用本件（收编走 hook+壳薄委派，根零改动）。判据方向从"不许出现"
    翻成"必须出现 descriptor+handler+invoke 点"，并新增 root 侧仍零引用（防旁路复活）。
    """
    root_source = _ROOT_INIT.read_text(encoding="utf-8")
    shell_source = _SHELL.read_text(encoding="utf-8")
    ve_source = (
        _PKG_ROOT.parents[1] / "voice_enricher.py"
    ).read_text(encoding="utf-8")

    # ①壳注册第三形（handler 注册行 + descriptor id 都在 capability_protocols 里）。
    assert "media.tts.autodub_transform" in shell_source, (
        "中央派发谱没注册第三形 = 简报『能派到』落空（在册未执法）"
    )
    assert 'handlers.register("media.tts.autodub_transform"' in shell_source
    assert "result_transform" in shell_source, "壳未薄委派到域内执行体"
    # ②voice_enricher 派这一形（唯一 invoke 点，退役内联）。
    assert 'capability_id="media.tts.autodub_transform"' in ve_source, (
        "voice_enricher 未走中央第三形 = 内联未退役/旁路复活"
    )
    # ③根仍零直接引用（收编不碰根；根若直连=第二通路/绕壳）。
    assert "result_transform" not in root_source, (
        "根装配开始直接引用本件 = 绕过壳薄委派（第二通路），须回到 hook+壳路"
    )
    # ④派发谱真认（descriptor + handler 都能被 default_invoker 取到）。
    invoker = cp.default_invoker()
    assert invoker.registry.get(rt.PROPOSED_CAPABILITY_ID) is not None
    assert invoker.handlers.get(rt.PROPOSED_CAPABILITY_ID) is not None


def test_module_opens_no_new_direct_or_invoker_callsite() -> None:
    """S270 归位后：本件是产出步**单一组合口**——全树唯一一处 ``media.tts.autodub`` 字面 invoke
    住在 ``dub_via_central``。原判据「本件零 invoke / 无 default_invoker」（id 字面量留在 hook
    调用点那一版）的前提被本批正当推翻：组合口落在此件，调用点即此件。

    强度不降反升，四条一起才叫"归位而非另加一份"：
    ①恰一处中央 invoke；②capability_id 是**字面常量** media.tts.autodub（写成变量＝普查门
    盲区＝真第二通路，见 ``_literal_capability_ids`` 只认 Constant）；③经 default_invoker 派
    中央；④**不得直呼**任何合成原语（synthesize/synthesize_autodub 都不许被本件调用）。
    """
    source = _PKG_ROOT.read_text(encoding="utf-8")
    tree = _tree(source)
    assert len(_invoke_calls(tree)) == 1, (
        f"单一组合口须恰一处中央 invoke（全树唯一 autodub invoker 点），实得 {len(_invoke_calls(tree))}"
    )
    assert _literal_capability_ids(tree) == {"media.tts.autodub"}, (
        "invoke 的 capability_id 必须是字面常量 media.tts.autodub（写成变量 AUTODUB_SOURCE_STEP"
        "＝普查门失明＝第二通路）"
    )
    assert "default_invoker" in source, "组合口须经 default_invoker 派中央，缺席即没归位"
    names = _call_names(tree)
    assert "synthesize_autodub" not in names, "组合口不得直呼 synthesize_autodub（直呼即第二通路）"
    assert "synthesize" not in names, "组合口只经 context 交出合成 seam，不持合成原语调用"


def test_shape_name_is_not_claimed_as_a_route_adapter() -> None:
    """形态名不是适配器：路由行派生与缺口账都不许因本件变动。"""
    assert rt.TRANSFORM_SHAPE not in cp._KNOWN_ADAPTERS
    assert cp._KNOWN_ADAPTERS == frozenset({"command", "prepared"})


def test_shape_name_is_not_admitted_to_known_adapters_by_accident() -> None:
    """自证：这条判据有牙——把形态名当适配器塞进去就会被它点名（合成数据，不落盘）。"""
    poisoned = frozenset(cp._KNOWN_ADAPTERS | {rt.TRANSFORM_SHAPE})
    assert rt.TRANSFORM_SHAPE in poisoned and poisoned != cp._KNOWN_ADAPTERS


def test_config_sizing_keys_are_read_by_name_only(tmp_path: Path, gates_pass: None) -> None:
    """装配不完整（键缺席）⇒ 诚实放弃增益并点名，绝不在此抄第二份缺省数。"""
    bare = SimpleNamespace(bot_tts_voice_hook_enabled=True, bot_tts_hard_max_chars=2000)
    calls: list[str] = []
    original = _result()
    enriched, code = rt.transform_presentation(
        bare, _message(), original, dub=lambda t: calls.append(t) or _dub_ok(t)
    )
    assert code == rt.OUTCOME_SIZING_MISSING
    assert calls == []
    assert enriched is original, "缺键必须零改动交回（连标签都不加，等装配补齐）"


def test_module_imports_no_second_source_of_hard_caps() -> None:
    """生效顶的唯一家：本件只 import `resolve_hard_max_chars`，字节顶/配额不重读。"""
    source = _PKG_ROOT.read_text(encoding="utf-8")
    assert "resolve_hard_max_chars" in source
    assert "resolve_max_audio_bytes" not in source, (
        "字节顶的家在 synthesize/产出步，此处重读＝第二个分叉点（M-35/G2-R3 收口判据）"
    )
