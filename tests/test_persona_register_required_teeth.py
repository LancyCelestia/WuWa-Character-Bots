"""S9 复验锁：人格册「必填化」到底有没有牙（多人格可扩展波 · 单元 5 复核）。

被锁的判据真身＝`persona_profile._parse_profile_file` 的必填段 + 两条切换回执腿
`_persona_text_receipt` / `_knowledge_list_receipt`。五齿：

1. 在册**非主人格**：``files.settings`` / ``files.knowledge`` 既没填也没登记进
   ``files_absent`` ⇒ ``register_defects`` 逐格点名 ⇒ 文本腿与清单腿**一律 failed**，
   绝不塌成"照旧吃 ``.env`` 基线"的假成功；
2. 已登记 ``files_absent`` ⇒ 诚实缺席：文本腿仍 failed（点名这一格没正文），
   清单腿是 skipped（＝当前仍回落基线，缺口 H-9 记账处，见施工图）；
3. **不在册的 persona id** 走消费口 ``main_persona_knowledge_files`` 拿不到主人格的
   knowledge 清单（回空＝不表态，不许借别人家的语料上桌）；
4. 生产在册册子每一格空位都有申报（真册只读、零写）；
5. ``is_main`` 免检面按现状钉住——免检只许落在主人格这一格，将来放宽要显式改锁。

全程离线：tmp_path 造册；不 import 探树；不写 Runtime 任何生产件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRegistry,
    main_persona_knowledge_files,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import paths


@pytest.fixture
def persona_outbound_policy(tmp_path: Path):
    """册内清单锚定判定读 paths.py 缺省策略：把判定根注成本 tmp 树。

    走的是 paths 件**文档化的测试注入口** ``set_default_policy``（teardown 复位 None
    惰性重建），不是放宽守卫——与 tests/test_persona_hot_switch.py 同口径。
    """
    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        yield tmp_path
    finally:
        paths.set_default_policy(None)


def _register(reg_dir: Path, persona_id: str, payload: dict) -> Path:
    """写一册 + 铺一份可锚定的正文（锚根＝``reg_dir.parent / persona_id``，与真身同式）。"""
    reg_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = reg_dir.parent / persona_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    for name in ("settings_core.md", "knowledge_core.md"):
        (asset_dir / name).write_text(f"{persona_id} 的{ name}正文\n", encoding="utf-8")
    path = reg_dir / f"{persona_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _empty_payload(persona_id: str, *, is_main: bool, absent: list[str] | None = None) -> dict:
    payload = {
        "schema": 1,
        "persona_id": persona_id,
        "display_name": persona_id.title(),
        "is_main": is_main,
        "qq": {"nickname": persona_id.title(), "signature": "", "avatar_path": "", "sex": ""},
        "files": {"settings": [], "knowledge": []},
        "voice": {"tts_refs": []},
    }
    if absent is not None:
        payload["files_absent"] = absent
    return payload


def test_alt_persona_empty_undeclared_files_fails_both_legs_and_names_cells(
    persona_outbound_policy: Path,
) -> None:
    """①必填化真有牙：空且未申报 ⇒ register_defects 逐格点名、两腿 failed。"""
    registry = PersonaProfileRegistry(persona_outbound_policy / "registry")
    _register(
        persona_outbound_policy / "registry",
        "novcomer",
        _empty_payload("novcomer", is_main=False),  # 没有 files_absent＝册子写漏
    )
    record = registry.get("novcomer")
    assert record is not None and not record.register_ok
    joined = "；".join(record.register_defects)
    assert "files.settings" in joined and "files.knowledge" in joined

    text_receipt = pp._persona_text_receipt(record)
    list_receipt = pp._knowledge_list_receipt(record)
    assert text_receipt.status == "failed" and "files_absent" in text_receipt.detail
    assert list_receipt.status == "failed" and "files_absent" in list_receipt.detail
    # 牙口验尺：这条 failed 不是"照旧吃基线"的化妆——回执必须自证没随切
    assert "未落" in text_receipt.detail


def test_declared_absence_is_honest_not_silent(persona_outbound_policy: Path) -> None:
    """②空＋已登记 files_absent ⇒ 不算写漏（零 defects），但文本腿仍不判成功。"""
    registry = PersonaProfileRegistry(persona_outbound_policy / "registry")
    _register(
        persona_outbound_policy / "registry",
        "danya",
        _empty_payload("danya", is_main=False, absent=["settings", "knowledge"]),
    )
    record = registry.get("danya")
    assert record is not None and record.register_ok
    assert record.files_absent == ("settings", "knowledge")

    text_receipt = pp._persona_text_receipt(record)
    assert text_receipt.status == "failed" and "files_absent" in text_receipt.detail
    # 🔴 现状锁（缺口 H-9）：诚实缺席的**知识腿**当前是 skipped＝仍吃 .env 基线清单，
    # 与文本腿不同口径。将来把这一格改成 failed / 空清单时，本锁必须一起重写（不许静默漂）。
    list_receipt = pp._knowledge_list_receipt(record)
    assert list_receipt.status == "skipped" and "基线" in list_receipt.detail


def test_unknown_persona_id_cannot_borrow_main_persona_knowledge(
    persona_outbound_policy: Path,
) -> None:
    """③注毒：不在册的 persona id ⇒ 消费口拿不到主人格那份 knowledge 清单。"""
    reg_dir = persona_outbound_policy / "registry"
    registry = PersonaProfileRegistry(reg_dir)
    main_payload = _empty_payload("keeper", is_main=True, absent=["settings"])
    main_payload["files"] = {"settings": [], "knowledge": ["knowledge_core.md"]}
    _register(reg_dir, "keeper", main_payload)

    # 主人格在册清单确实被锚定采纳（否则"拿不到"是假证：分母为空）
    kept = main_persona_knowledge_files("keeper", registry=registry)
    assert len(kept) == 1 and Path(kept[0]).name == "knowledge_core.md"

    # 幽灵人格 id：既非在册项 ⇒ 回空＝不表态，绝不回落到 keeper 那份
    assert main_persona_knowledge_files("ghostwhoisnothere", registry=registry) == ()
    assert registry.get("ghostwhoisnothere") is None
    # 空 persona_id 也不许"顺手"读成主人格清单（resolve 不表态＝缺席申报）
    assert registry.get("") is None


def test_empty_files_key_missing_entirely_is_a_defect(persona_outbound_policy: Path) -> None:
    """③b `files` 段整块缺席 ⇒ 同样进 defects（不是"没写就当作没这回事"）。"""
    reg_dir = persona_outbound_policy / "registry"
    payload = _empty_payload("nokeys", is_main=False, absent=[])
    payload.pop("files")
    _register(reg_dir, "nokeys", payload)
    record = PersonaProfileRegistry(reg_dir).get("nokeys")
    assert record is not None
    assert any("files 段" in d for d in record.register_defects)
    assert any("files.settings" in d for d in record.register_defects)


def test_shipped_registers_declare_every_empty_cell() -> None:
    """④真册只读体检：在册每一格里，空清单必须能在 files_absent 里对上号。

    比 ``register_defects`` 更严一档（那一尺对 ``is_main`` 免检）——新加人格时把
    "没备料"写成散文注释（``_files_note``）一律算没申报。清单条目数以实跑为准。
    """
    records = pp.get_shared_registry().all()
    assert records, "人格册目录读空＝本锁失去分母，先查 personas/registry/ 是否在位"
    for persona_id, record in records.items():
        if record.settings_files:
            assert all(Path(p).is_absolute() for p in record.settings_files)
        else:
            assert "settings" in record.files_absent, (
                f"{persona_id}: files.settings 空且未申报缺席（缺料未申报）"
            )
        if record.knowledge_files:
            assert all(Path(p).is_absolute() for p in record.knowledge_files)
        else:
            assert "knowledge" in record.files_absent, (
                f"{persona_id}: files.knowledge 空且未申报缺席（缺料未申报）"
            )


def test_is_main_exemption_is_scoped_to_the_main_cell(persona_outbound_policy: Path) -> None:
    """⑤现状锁：必填判据的 ``is_main`` 免检面只落在主人格那一格。

    主人格空且未申报 ⇒ **零 defects**（消费腿据此名正言顺回落 ``.env`` 基线，
    见施工图缺口 H-9）。这一格刻意锁住现状：将来若取消免检，本锁必红一次、
    逼改动者显式表态，而不是让免检面悄悄长到第二人格。
    """
    reg_dir = persona_outbound_policy / "registry"
    _register(reg_dir, "mainkeep", _empty_payload("mainkeep", is_main=True))
    main_record = PersonaProfileRegistry(reg_dir).get("mainkeep")
    assert main_record is not None and main_record.register_ok
    # 同一份空册改标非主 ⇒ 立刻有牙（证明免检只认 is_main 这一枚开关）
    _register(reg_dir, "mainkeep2", {**_empty_payload("mainkeep2", is_main=False)})
    alt_record = PersonaProfileRegistry(reg_dir).get("mainkeep2")
    assert alt_record is not None and not alt_record.register_ok
