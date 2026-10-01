"""SEAT-IMPL-PERSONA-QQLEG — QQ 腿收口锁（2026-09-27）。

三面判据（H-1 整套切换项「昵称/签名/头像/文本/清单」逐项点名的最后两枚钉子）：

1. **五格腿集完整锁**：``apply_persona_profile`` 的回执项集必须恰覆盖
   ``_ITEM_LABELS_ZH`` 五格（qq_profile / qq_avatar / card_avatar /
   knowledge_list / persona_text）——结构腿（AST 源判据，注毒在内存源码副本）
   ＋行为腿（真件端到端，含 F-C TOCTOU 早退分支）双判。
2. **知识清单腿行为锁**（H-4甲）：在册清单非空 ⇒ ``knowledge_list`` ok 且 detail
   报份数不泄路径（F-B）；册未表态 ⇒ skipped 并点名「基线回落」兼容语义
   （不是半切）；且**本格不新增任何 API 调用**（下发序列仍是两发上界）。
3. **受理≠宣告锁**（ATK 票③-3）：``_handle_persona_command`` switch 分支的
   成功文案禁止「已强制切换」式受理即宣告，必须写明「已受理＋以逐项回执为准」；
   行为面直调同判据。

全离线：fake transport、tmp 人格册、注毒全部在内存源码副本／$TEMP 私有副本，
生产文件零写入（注毒台账见席位报告 §⑤）。
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_REL = (
    "plugins/bot_unified_runtime/domains/chat_reply/character/persona_profile.py"
)
_ADMIN_REL = "plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py"
_PROFILE_SRC = _ROOT / Path(_PROFILE_REL)
_ADMIN_SRC = _ROOT / Path(_ADMIN_REL)

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRecord,
    PersonaProfileRegistry,
    apply_persona_profile,
)

#: H-1 整套切换项五格名册（新增/摘格必须经点名评审改本名册，不许静默漂移）。
RECEIPT_ROSTER = frozenset(
    {"qq_profile", "qq_avatar", "card_avatar", "knowledge_list", "persona_text"}
)


def _record(**kwargs: Any) -> PersonaProfileRecord:
    base: dict[str, Any] = {
        "persona_id": "danya",
        "display_name": "达妮娅",
        "settings_files": ("personas/danya/identity.md",),
    }
    base.update(kwargs)
    return PersonaProfileRecord(**base)


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append((action, params))
        return {"retcode": 0, "data": {}}


def _statuses(receipt: Any) -> dict[str, str]:
    return {item.item: item.status for item in receipt.items}


def _replace_once(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"注毒目标命中 {src.count(old)} 次，判据不唯一"
    out = src.replace(old, new)
    assert out != src, "注毒未生效（等于空跑）"
    return out


# ---------------------------------------------------------------------------
# 1. 五格腿集完整锁——结构腿（AST 源判据＋内存副本注毒）
# ---------------------------------------------------------------------------


def check_roster_locks(source: str) -> None:
    tree = ast.parse(source)
    labels = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_ITEM_LABELS_ZH" for t in node.targets)
    ]
    assert len(labels) == 1, "_ITEM_LABELS_ZH 应恰一枚定义（真身塌陷或第二真身）"
    dicts = [n for n in ast.walk(labels[0].value) if isinstance(n, ast.Dict)]
    assert len(dicts) == 1, "_ITEM_LABELS_ZH 定义位应恰一枚 dict 字面量"
    keys = {
        k.value
        for k in dicts[0].keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert keys == RECEIPT_ROSTER, (
        f"回执项集与 H-1 五格名册漂移（增/摘格必须点名评审）：差集={sorted(keys ^ RECEIPT_ROSTER)}"
    )
    apply_funcs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "apply_persona_profile"
    ]
    assert len(apply_funcs) == 1
    appended = [
        c
        for c in ast.walk(apply_funcs[0])
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Name)
        and c.func.id == "_knowledge_list_receipt"
    ]
    assert len(appended) == 2, (
        f"knowledge_list 腿必须出现在全部 {2} 枚回执出口（含 F-C TOCTOU 早退）；实={len(appended)}"
    )


def test_roster_locks_hold_on_live_source() -> None:
    check_roster_locks(_PROFILE_SRC.read_text(encoding="utf-8"))


def test_poison_dropping_knowledge_append_turns_roster_lock_red() -> None:
    """注毒①（内存副本）：摘掉终路 append（早退口保留）⇒ 出口计数判据必红。"""
    src = _replace_once(
        _PROFILE_SRC.read_text(encoding="utf-8"),
        "    items.append(_knowledge_list_receipt(record))\n    items.append(_persona_text_receipt(record))",
        "    items.append(_persona_text_receipt(record))",
    )
    with pytest.raises(AssertionError):
        check_roster_locks(src)


def test_poison_narrowing_roster_turns_roster_lock_red() -> None:
    """注毒②（内存副本）：从名册 dict 摘 knowledge_list 格 ⇒ 名册比对判据必红。"""
    src = _replace_once(
        _PROFILE_SRC.read_text(encoding="utf-8"),
        '    "knowledge_list": "知识清单",\n',
        "",
    )
    with pytest.raises(AssertionError):
        check_roster_locks(src)


# ---------------------------------------------------------------------------
# 1b. 五格腿集完整锁——行为腿（真件端到端，含早退分支）
# ---------------------------------------------------------------------------


def test_full_record_receipt_covers_all_five_faces(
    tmp_path: Path,
) -> None:
    """外观全表态的 record ⇒ 回执五格齐且无 skipped（H-1 整套逐格可核对）。"""
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        avatar = tmp_path / "avatar.png"
        avatar.write_bytes(b"\x89PNG fake")
        record = _record(
            qq_nickname="达妮娅",
            qq_signature="微光",
            qq_avatar_path=str(avatar),
            knowledge_files=("personas/danya/kb1.md", "personas/danya/kb2.md"),
        )
        transport = _FakeTransport()
        receipt = asyncio.run(
            apply_persona_profile(
                record, call_api=transport, card_avatar_hook=lambda _p: None
            )
        )
    finally:
        paths.set_default_policy(None)
    assert set(_statuses(receipt)) == RECEIPT_ROSTER
    assert receipt.fully_applied is True
    assert receipt.failed == ()
    # 本席增量零新调用：下发序列仍以 set_qq_profile+set_qq_avatar 两发为界
    assert [name for name, _ in transport.calls] == ["set_qq_profile", "set_qq_avatar"]


def test_toctou_early_return_keeps_knowledge_leg(tmp_path: Path) -> None:
    """F-C TOCTOU 早退分支也不许丢清单腿——腿集完整是 H-1 判据前提（同 3b 组文本腿口径）。

    判据确定性：不注入策略＝生产默认出站根（repo+Runtime 数据根），tmp 树在其外
    ⇒ check_sendable 必拒 ⇒ 走早退分支（与 test_persona_hot_switch 同名场景同口径；
    本席 pytest 强制 --basetemp=$TEMP，恒不落允许根内）。
    """
    record = _record(qq_nickname="达妮娅", qq_avatar_path=str(tmp_path / "gone.jpg"))
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
        )
    )
    assert RECEIPT_ROSTER <= set(_statuses(receipt))
    assert _statuses(receipt)["qq_avatar"] == "failed"


# ---------------------------------------------------------------------------
# 2. 知识清单腿行为锁（H-4甲：随册报份数、未表态点名回落、绝不泄路径）
# ---------------------------------------------------------------------------


def test_knowledge_leg_ok_names_count_not_paths() -> None:
    record = _record(
        qq_signature="微光",
        knowledge_files=("personas/danya/秘密知识库.md", "C:\\Sensitive\\kb2.md"),
    )
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
        )
    )
    item = next(i for i in receipt.items if i.item == "knowledge_list")
    assert item.status == "ok"
    assert "2 份" in item.detail
    assert "秘密知识库" not in item.detail and "kb2" not in item.detail


def test_knowledge_leg_unstated_is_skipped_and_names_fallback() -> None:
    """空清单＝兼容语义（吃基线），skipped 点名回落，既不 failed 也不影响"已切换"判定。"""
    record = _record(qq_signature="微光", knowledge_files=())
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
        )
    )
    item = next(i for i in receipt.items if i.item == "knowledge_list")
    assert item.status == "skipped"
    assert "基线" in item.detail
    assert receipt.fully_applied is True
    assert "knowledge_list" not in receipt.landed  # skipped 不进"已落"账


def test_knowledge_leg_count_matches_parsed_register(tmp_path: Path) -> None:
    """回执说的份数==册子现读份数（F-D 锚定解析→record 同册双判据，K4 同型）。"""
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        reg_dir = tmp_path / "registry"
        reg_dir.mkdir()
        anchor = tmp_path / "danya"
        anchor.mkdir()
        for name in ("k1.md", "k2.md", "k3.md"):
            (anchor / name).write_text("知识正文", encoding="utf-8")
        (reg_dir / "danya.json").write_text(
            json.dumps(
                {
                    "persona_id": "danya",
                    "display_name": "达妮娅",
                    "files": {
                        "settings": [],
                        "knowledge": [str(anchor / "k1.md"), str(anchor / "k2.md"), str(anchor / "k3.md")],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        record = PersonaProfileRegistry(reg_dir).get("danya")
        assert record is not None and len(record.knowledge_files) == 3
        receipt = asyncio.run(
            apply_persona_profile(
                record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
            )
        )
    finally:
        paths.set_default_policy(None)
    item = next(i for i in receipt.items if i.item == "knowledge_list")
    assert item.status == "ok" and "3 份" in item.detail


# ---------------------------------------------------------------------------
# 3. 受理≠宣告锁（ATK 票③-3）：switch 成功行措辞＋行为面直调
# ---------------------------------------------------------------------------


def _persona_handler_func(tree: ast.Module) -> ast.FunctionDef:
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_persona_command"
    ]
    assert len(hits) == 1, f"_handle_persona_command 应恰一枚，实={len(hits)}"
    return hits[0]


def check_acceptance_wording(source: str) -> None:
    func = _persona_handler_func(ast.parse(source))
    strings = [
        c.value
        for c in ast.walk(func)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    ]
    assert not any("已强制切换" in s for s in strings), (
        "switch 分支回潮受理即宣告（『已强制切换人格』）——完成判定只许住在逐项回执里"
    )
    # 判据按**单条成文文案**合取（相邻字面量隐式拼接后是一句话；IfExp 两支各算一句），
    # 不许拿另一支的『回执』替本支背书（各行各自闭合）。
    def _flatten(expr: ast.expr) -> str:
        return "".join(
            c.value
            for c in ast.walk(expr)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        )

    return_texts: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            value = node.value
            if isinstance(value, ast.IfExp):
                return_texts.append(_flatten(value.body))
                return_texts.append(_flatten(value.orelse))
            else:
                return_texts.append(_flatten(value))
    assert any("已受理" in t and "回执" in t for t in return_texts), (
        "switch 成功行自身必须同时写明『已受理』并指向『逐项回执』（受理≠完成，同串闭合）"
    )
    assert any("自动模式" in t and "回执" in t for t in return_texts), (
        "switch default 行必须点名外观恢复腿同样以逐项回执为准"
    )


def test_acceptance_wording_holds_on_live_source() -> None:
    check_acceptance_wording(_ADMIN_SRC.read_text(encoding="utf-8"))


def test_poison_restore_eager_claim_turns_wording_lock_red() -> None:
    """注毒③（内存副本）：把成功行改回旧「已强制切换人格」⇒ 措辞锁必红。"""
    src = _replace_once(
        _ADMIN_SRC.read_text(encoding="utf-8"),
        'f"人格切换指令已受理：{target}（持续到下一次 switch default）；"',
        'f"已强制切换人格：{target}（持续到下一次 switch default）。"',
    )
    with pytest.raises(AssertionError):
        check_acceptance_wording(src)


def test_poison_drop_receipt_pointer_turns_wording_lock_red() -> None:
    """注毒④（内存副本）：摘掉 switch 成功行的『逐项回执』指向 ⇒ 同串合取判据必红。"""
    src = _replace_once(
        _ADMIN_SRC.read_text(encoding="utf-8"),
        '"QQ 外观/人格文本/知识清单是否跟随，以逐项回执为准。"',
        '"QQ 外观/人格文本/知识清单是否跟随，以逐项回辙为准。"',
    )
    with pytest.raises(AssertionError):
        check_acceptance_wording(src)


class _WordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.override = ""

    def set_persona_override(self, profile_id: str) -> None:
        self.calls.append(("override", profile_id))
        self.override = (profile_id or "").strip()

    def get_persona_override(self) -> str:
        return self.override

    def get_persona_weights(self) -> dict[str, float]:
        return {}


def test_switch_reply_behavior_level_acceptance_not_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    mod = importlib.import_module(
        "plugins.bot_unified_runtime.domains.ops.admin.runtime_admin"
    )
    spec = SimpleNamespace(display_name="备选人格", weight=0.0, emotions=())
    monkeypatch.setattr(
        pp_mod, "build_effective_alt_personas", lambda config: {"alt1": spec}
    )
    config = SimpleNamespace(
        bot_persona_profile_id="main", bot_persona_display_name="主人格"
    )
    store = _WordingStore()
    body = mod._handle_persona_command(store, config, ["switch", "alt1"])
    assert "已强制切换" not in body
    assert "已受理" in body and "回执" in body
    assert store.calls == [("override", "alt1")]  # 写入口照落（受理事实）
    body_default = mod._handle_persona_command(store, config, ["switch", "default"])
    assert "自动模式" in body_default and "回执" in body_default


# ---------------------------------------------------------------------------
# 4. 增量不伤既有判据：半切态清单格绝不替人背书
# ---------------------------------------------------------------------------


def test_half_switch_summary_unchanged_semantics() -> None:
    """毒头像一发（沿用 3b 组既有病灶）⇒ 五格齐、半切文案不掺"已切换"。"""
    import tempfile

    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    tmp = Path(tempfile.mkdtemp(prefix="qqleg-half-"))
    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp, runtime_data_root=tmp / "data")
    )
    try:
        avatar = tmp / "avatar.png"
        avatar.write_bytes(b"\x89PNG fake")
        record = _record(
            qq_nickname="达妮娅", qq_signature="微光", qq_avatar_path=str(avatar)
        )

        class _FailAvatar(_FakeTransport):
            async def __call__(self, action: str, params: dict) -> dict:
                self.calls.append((action, params))
                if action == "set_qq_avatar":
                    return {"retcode": 1001, "message": "风控拦截"}
                return {"retcode": 0, "data": {}}

        receipt = asyncio.run(
            apply_persona_profile(
                record, call_api=_FailAvatar(), card_avatar_hook=lambda _p: None
            )
        )
    finally:
        paths.set_default_policy(None)
    assert receipt.fully_applied is False
    summary = receipt.summary()
    assert "未完全切换" in summary and "已切换" not in summary
    assert set(_statuses(receipt)) == RECEIPT_ROSTER
