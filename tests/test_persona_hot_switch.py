"""人格热切换离线测试（SEAT-PERSONA-HOT）。

覆盖面（对应任务四条硬断言，全部 fake transport，禁真机下发）：
1. 人格册 (mtime,size) 热读——改 profile 文件下一轮即生效，无需重启；
2. 半切态回执点名——一项成功一项失败时，receipt 说清哪几项已落/哪几项没落，
   且 ``fully_applied`` 为 False、``summary()`` 绝不写"已切换"（H-1）；
3. 知识清单随人格（H-4甲）——切到备用人格后静态兜底腿取该人格的清单，向量库不碰；
4. 兼容位 vs 真身优先级唯一（H-5乙）——同一 persona 在册则以册子为准，无双真身；
5. get_login_info 防回归锁（台账 #60）——任何 plugins/ 源码都不得把 get_login_info
   当自称事实源；
6. 人格文本腿回执（S-FIX-PERSONA-TEXT ②）——切换回执逐项点名文本是否落地，
   空清单＝「未落」，外观全绿也不许称"已切换"；
7. 真装配活性锁（S-FIX-PERSONA-TEXT ③）——经 build_character_context_provider
   真缝：同进程入册/改册 ⇒ 文本腿现读跟随（治装配期快照冻结，探针 P1 根病）。

全离线：tmp_path 造人格册与文本文件，call_api 用 fake，零真实 personas/、Runtime、QQ。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    providers as providers_mod,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRecord,
    PersonaProfileRegistry,
    apply_persona_profile,
    build_effective_alt_personas,
    current_bot_nickname,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_set import (
    AltPersonaSpec,
    PersonaSelector,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_profile(registry_dir: Path, persona_id: str, payload: dict) -> Path:
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"{persona_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _record(**kwargs) -> PersonaProfileRecord:
    base = {"persona_id": "danya", "display_name": "达妮娅",
            # ②文本腿后补全在册形态：外观面锁的语义不变（全落=四格全落）。
            "settings_files": ("personas/danya/identity.md",)}
    base.update(kwargs)
    return PersonaProfileRecord(**base)


@pytest.fixture
def persona_outbound_policy(tmp_path: Path):
    """S-FIX-PERSONA-R2（F-C）：头像装载/下发闸读 paths.py 缺省策略。

    行为锁的 tmp 树头像要判 allowed，必须把判定根注成本 tmp 树——走的是
    paths 件**文档化的测试注入口** ``set_default_policy``（teardown 复位 None
    惰性重建，不污染同进程其它测试），不是放宽守卫。
    """
    from plugins.bot_unified_runtime.domains.core.safety_exec import paths

    paths.set_default_policy(
        paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path / "data")
    )
    try:
        yield tmp_path
    finally:
        paths.set_default_policy(None)


# ---------------------------------------------------------------------------
# 1. 人格册热读：改 profile 文件 → 下一读即变（(mtime,size) 签名，不重启）
# ---------------------------------------------------------------------------

def test_persona_register_hot_reads_on_edit(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "qq": {"nickname": "达妮娅", "signature": "旧签名", "avatar_path": ""},
        },
    )
    registry = PersonaProfileRegistry(reg_dir)
    assert registry.get("danya").qq_signature == "旧签名"

    # 追加内容 → size 必变、mtime_ns 亦变；热读加载器不重启即认到新值
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "qq": {"nickname": "达妮娅", "signature": "新签名已生效", "avatar_path": ""},
        },
    )
    assert registry.get("danya").qq_signature == "新签名已生效"


def test_persona_register_picks_up_new_and_removed_files(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    reg_dir.mkdir(parents=True)
    registry = PersonaProfileRegistry(reg_dir)
    assert registry.persona_ids() == ()
    _write_profile(reg_dir, "danya", {"persona_id": "danya", "qq": {"nickname": "达妮娅"}})
    assert "danya" in registry.persona_ids()
    (reg_dir / "danya.json").unlink()
    assert registry.persona_ids() == ()


# ---------------------------------------------------------------------------
# 2. 半切态回执：昵称/签名一发成功、头像一发失败 → 点名，绝不说"已切换"
# ---------------------------------------------------------------------------

class _FakeTransport:
    """记录调用、按动作脚本化返回的 fake QQ 下发通道（离线，不碰真机）。"""

    def __init__(self, *, fail_actions=(), raise_actions=()) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail = set(fail_actions)
        self._raise = set(raise_actions)

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append((action, params))
        if action in self._raise:
            raise RuntimeError("rate limited")
        if action in self._fail:
            return {"retcode": 1001, "message": "风控拦截"}
        return {"retcode": 0, "data": {}}


def test_switch_receipt_names_landed_and_missing(
    tmp_path: Path, persona_outbound_policy: Path
) -> None:
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"\x89PNG fake")
    record = _record(qq_nickname="达妮娅", qq_signature="微光", qq_avatar_path=str(avatar))
    transport = _FakeTransport(fail_actions={"set_qq_avatar"})
    cards: list[str] = []
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=cards.append)
    )
    # 昵称/签名一发成功、头像一发失败 ⇒ 半切态
    assert "qq_profile" in receipt.landed
    assert "qq_avatar" in receipt.failed
    assert receipt.fully_applied is False
    summary = receipt.summary()
    assert "未完全切换" in summary
    assert "已切换" not in summary  # 绝不宣称"已切换"
    assert "QQ头像" in summary
    # 头像一发失败 ⇒ 卡片头像不跟随（不误登记）
    assert cards == []


def test_switch_all_ok_marks_fully_applied(
    tmp_path: Path, persona_outbound_policy: Path
) -> None:
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"\x89PNG fake")
    record = _record(qq_nickname="达妮娅", qq_signature="微光", qq_avatar_path=str(avatar))
    transport = _FakeTransport()
    cards: list[str] = []
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=cards.append)
    )
    assert receipt.fully_applied is True
    assert receipt.failed == ()
    assert "已切换人格" in receipt.summary()
    assert cards == [str(avatar)]  # 卡片头像走既有登记面
    assert {name for name, _ in transport.calls} == {"set_qq_profile", "set_qq_avatar"}


def test_switch_skips_unstated_items() -> None:
    # 昵称空、无头像 ⇒ 只签名一发；未表态项标 skipped 不算失败
    record = _record(qq_signature="只有签名")
    transport = _FakeTransport()
    receipt = asyncio.run(apply_persona_profile(record, call_api=transport, card_avatar_hook=lambda _p: None))
    profile_call = dict(transport.calls[0][1])
    assert "personal_note" in profile_call and "nickname" not in profile_call
    by_item = {item.item: item.status for item in receipt.items}
    assert by_item["qq_avatar"] == "skipped" and by_item["card_avatar"] == "skipped"
    assert receipt.fully_applied is True


def test_resolved_avatar_uses_central_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """锁：注册表 ``data/...`` 相对头像路径必须经 scripts/runtime_paths 中央件解析。

    口径：相对路径交 ``runtime_path()`` 重映射到配置的数据根（.env/env
    ``BOT_RUNTIME_DATA_DIR``，此处 monkeypatch 注入）；绝对路径原样；空值空串。
    注毒自证：解析改回 ``_REPO_ROOT`` 兜底，本锁必红（仓库根不是配置数据根，
    结果不落在 tmp 数据根上）；还原后转绿。
    """
    data_dir = tmp_path / "rt" / "data"
    avatar = data_dir / "avatar" / "persona_avatar_x_1080.jpg"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"\xff\xd8fake-jpg")
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(data_dir))

    record = _record(qq_avatar_path="data/avatar/persona_avatar_x_1080.jpg")
    assert record.resolved_avatar == str(avatar.resolve())
    # 解析结果须是可判空且命中的真身路径（下发腿据此点名/跳过分明）
    assert Path(record.resolved_avatar).is_file()
    # 绝对路径原样、空值空串（回归守卫）
    assert _record(qq_avatar_path=str(avatar)).resolved_avatar == str(avatar)
    assert _record().resolved_avatar == ""


# ---------------------------------------------------------------------------
# 3. 知识清单随人格切换（H-4甲：只换静态清单，向量库不碰）
# ---------------------------------------------------------------------------

def _mk(provider_root: Path, name: str, marker: str) -> Path:
    path = provider_root / name
    path.write_text(f"{marker} 正文一段。\n", encoding="utf-8")
    return path


def test_knowledge_file_list_follows_persona(tmp_path: Path) -> None:
    base_kb = _mk(tmp_path, "base_kb.md", "基线")
    persona_kb = _mk(tmp_path, "persona_kb.md", "达妮娅专属")
    main_identity = _mk(tmp_path, "main.md", "守岸人身份")

    danya_spec = AltPersonaSpec(
        profile_id="danya", display_name="达妮娅", files=(), knowledge_files=(str(persona_kb),)
    )

    def _build(override: str) -> FileCharacterContextProvider:
        return FileCharacterContextProvider(
            persona_profile_id="shorekeeper",
            persona_display_name="守岸人",
            persona_version="0",
            persona_files=[main_identity],
            knowledge_files=[base_kb],
            # 薄壳面保留：PersonaSelector 收敛为可调用视图单一形态（①）后，
            # 本锁仍锁**消费缝**对 spec 的响应；生产装配缝活性由
            # test_text_leg_follows_register_through_real_assembly 把守。
            persona_selector=PersonaSelector(lambda: {"danya": danya_spec}),
            persona_override_provider=(lambda: override),
            persona_registry=None,
        )

    switched = _build("danya").build_context(
        request_id="r1", sender_id="u", session_id="s", query_text="聊聊天吧"
    )
    base = _build("").build_context(
        request_id="r2", sender_id="u", session_id="s", query_text="聊聊天吧"
    )
    assert {chunk.source_id for chunk in switched.knowledge_results.chunks} == {"persona_kb"}
    assert {chunk.source_id for chunk in base.knowledge_results.chunks} == {"base_kb"}


def test_main_persona_knowledge_follows_register(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    # F-D 锚定：在册清单条目必须落在 personas/<id>/ 子树（锚根＝registry 父目录/<persona_id>）。
    anchor = tmp_path / "shorekeeper"
    anchor.mkdir(parents=True, exist_ok=True)
    reg_kb = _mk(anchor, "reg_main_kb.md", "在册主人格清单")
    _write_profile(
        reg_dir,
        "shorekeeper",
        {
            "persona_id": "shorekeeper",
            "is_main": True,
            "qq": {"nickname": "守岸人"},
            "files": {"knowledge": [str(reg_kb)]},
        },
    )
    registry = PersonaProfileRegistry(reg_dir)
    base_kb = _mk(tmp_path, "base_kb.md", "基线")
    provider = FileCharacterContextProvider(
        persona_profile_id="shorekeeper",
        persona_display_name="守岸人",
        persona_version="0",
        persona_files=[_mk(tmp_path, "main2.md", "x")],
        knowledge_files=[base_kb],
        persona_registry=registry,
    )
    result = provider.build_context(
        request_id="r", sender_id="u", session_id="s", query_text="随便说点什么"
    )
    assert {chunk.source_id for chunk in result.knowledge_results.chunks} == {"reg_main_kb"}


# ---------------------------------------------------------------------------
# 3b. 人格文本腿回执（②：缺腿必报"未落"，绝不默认成功；H-1 逐项点名）
# ---------------------------------------------------------------------------

def _statuses(receipt) -> dict[str, str]:
    return {item.item: item.status for item in receipt.items}


def test_switch_receipt_text_leg_missing_names_it() -> None:
    """外观全落＋在册设定清单为空（M3 零判据面）⇒ 文本腿 failed、禁称"已切换"。"""
    record = _record(qq_nickname="达妮娅", qq_signature="微光", settings_files=())
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None)
    )
    by_item = _statuses(receipt)
    assert by_item["persona_text"] == "failed"
    assert by_item["qq_profile"] == "ok"
    assert receipt.fully_applied is False  # 判定必须吃进文本腿（旧"双回执皆绿"缝隙）
    assert receipt.landed == ("qq_profile",)
    summary = receipt.summary()
    assert "未完全切换" in summary and "人格文本" in summary
    assert "已切换" not in summary  # 半切态绝不宣称完成


def test_switch_receipt_text_leg_landed_reports_manifest_count() -> None:
    record = _record(qq_signature="微光", settings_files=("a.md", "b.md"))
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None)
    )
    assert _statuses(receipt)["persona_text"] == "ok"
    assert receipt.fully_applied is True
    summary = receipt.summary()
    assert "已切换人格" in summary and "人格文本" in summary
    detail = next(item.detail for item in receipt.items if item.item == "persona_text")
    assert "2 份" in detail


def test_switch_receipt_default_marks_text_leg_by_override_readback() -> None:
    """回切主人格：override 已由主链读回确认清空，文本腿每轮现读主人格清单 ⇒ ok。"""
    record = _record(
        persona_id="shorekeeper", display_name="守岸人", is_main=True,
        qq_nickname="守岸人", settings_files=(),
    )
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None)
    )
    assert _statuses(receipt)["persona_text"] == "ok"
    assert receipt.fully_applied is True
    detail = next(item.detail for item in receipt.items if item.item == "persona_text")
    assert "主人格" in detail


def test_text_leg_receipt_survives_avatar_gate_early_return(tmp_path: Path) -> None:
    """F-C TOCTOU 早退分支也不许丢文本腿——腿集完整是 H-1 判据的前提。"""
    record = _record(qq_nickname="达妮娅", qq_avatar_path=str(tmp_path / "gone.jpg"))
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None)
    )
    assert {"qq_profile", "qq_avatar", "card_avatar", "persona_text"} <= set(_statuses(receipt))


# ---------------------------------------------------------------------------
# 3c. 真装配活性锁（③：判据经 build_character_context_provider 真缝，禁手工 selector）
# ---------------------------------------------------------------------------

def _stub_peripheral_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    """把人格装配无关的外围 provider 构造器置 None（同 test_persona_injection_v21 口径），
    只留人格/文本/知识腿为真身——FileCharacterContextProvider 本体**不**被替换。"""
    for name in (
        "build_memory_read_provider",
        "build_reflection_memory_provider",
        "build_conversation_history_provider",
        "build_emotion_provider",
        "build_trend_provider",
        "build_temporal_provider",
        "build_glossary_provider",
    ):
        monkeypatch.setattr(providers_mod, name, lambda config: None)
    monkeypatch.setattr(providers_mod, "_shared_affinity_store", lambda config: None)
    monkeypatch.setattr(providers_mod, "_shared_addressing_preferences", lambda config: None)
    monkeypatch.setattr(
        providers_mod,
        "build_relationship_provider",
        lambda config, interaction_counts=None: None,
    )
    monkeypatch.setattr(
        providers_mod,
        "build_shared_group_context_provider",
        lambda config, llm_provider=None: None,
    )
    monkeypatch.setattr(
        providers_mod,
        "build_keyword_knowledge_provider",
        lambda config: SimpleNamespace(available=False),
    )


class _OverrideStore:
    """假 runtime settings：只提供 override 现读口，其余经工厂内兜底吞掉。"""

    def __init__(self) -> None:
        self.override = ""

    def get_persona_override(self) -> str:
        return self.override


def test_persona_selector_rejects_snapshot_shape() -> None:
    """①单一形态禁回潮锁：dict 快照形态构造当场 TypeError——可调用视图是唯一形态，
    不存在"dict 与 callable 双形态都接受"的旁支分支。"""
    snapshot = {"danya": AltPersonaSpec(profile_id="danya", display_name="达妮娅")}
    with pytest.raises(TypeError):
        PersonaSelector(snapshot)  # type: ignore[arg-type]
    ok = PersonaSelector(lambda: snapshot)
    assert ok.select(override="danya") is snapshot["danya"]


def test_text_leg_follows_register_through_real_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同进程「入册新人格 → switch → 文本腿取到新设定」端到端锁（M1/M2 根病灶）。

    判据必经 ``build_character_context_provider`` 真装配缝——手工注入 selector 的
    薄壳锁（test_knowledge_file_list_follows_persona）盖不住装配期快照。旧病
    （providers.py 装配时一次性 build_effective_alt_personas 冻结）若回潮，
    Phase B（启动后入册）当场红；清单改册冻结（探针 P1 files 腿）由 Phase C 将红。
    注毒自证记录于席位报告（摘除①接线⇒本锁红）。
    """
    _stub_peripheral_builders(monkeypatch)

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    danya_dir = tmp_path / "danya"  # F-D 锚根＝registry 父目录/persona_id
    danya_dir.mkdir()
    (danya_dir / "core_v1.md").write_text("达妮娅设定V1标记DANYA_V1", encoding="utf-8")
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "display_name": "达妮娅", "files": {"settings": ["core_v1.md"]}},
    )
    main_md = _mk(tmp_path, "main.md", "主人格正文标记MAIN")

    config = SimpleNamespace(
        bot_affinity_enabled=False,
        bot_persona_profile_id="shorekeeper",
        bot_persona_display_name="守岸人",
        bot_persona_files=[main_md],
        bot_knowledge_files=[],
        bot_persona_alt_profiles={},
        persona_registry=PersonaProfileRegistry(reg_dir),
    )
    store = _OverrideStore()
    provider = providers_mod.build_character_context_provider(config, runtime_settings=store)

    def _persona_text() -> str:
        return provider.build_context(
            request_id="r", sender_id="u", session_id="s", query_text="聊聊天吧"
        ).persona.raw_text

    # Phase A：装配前已在册的 danya——基础随切。
    store.override = "danya"
    assert "DANYA_V1" in _persona_text()

    # Phase B：装配**之后**新入册的人格——装配期快照在这一步必红（M1）。
    xiao_dir = tmp_path / "xiao"
    xiao_dir.mkdir()
    (xiao_dir / "core_v2.md").write_text("新人格设定V2标记XIAO_V2", encoding="utf-8")
    _write_profile(
        reg_dir,
        "xiao",
        {"persona_id": "xiao", "display_name": "宵", "files": {"settings": ["core_v2.md"]}},
    )
    store.override = "xiao"
    text_b = _persona_text()
    assert "XIAO_V2" in text_b, "启动后入册的人格文本腿未跟随（装配期冻结回潮）"
    assert "MAIN" not in text_b

    # Phase C：同名人格**改清单**（v2→v3）——清单冻结在这一步必红（M2/探针P1 files 腿）。
    (xiao_dir / "core_v3.md").write_text("改册清单V3标记XIAO_V3", encoding="utf-8")
    _write_profile(
        reg_dir,
        "xiao",
        {"persona_id": "xiao", "display_name": "宵", "files": {"settings": ["core_v3.md"]}},
    )
    text_c = _persona_text()
    assert "XIAO_V3" in text_c and "XIAO_V2" not in text_c

    # Phase D：回切 default——主人格文本热回归。
    store.override = "default"
    text_d = _persona_text()
    assert "MAIN" in text_d and "XIAO" not in text_d


# ---------------------------------------------------------------------------
# 4. 兼容位 vs 真身优先级唯一（H-5乙：入册即以册子为准，不留第二真身）
# ---------------------------------------------------------------------------

def _compat_config(alt: dict) -> object:
    class _Cfg:
        bot_persona_profile_id = "shorekeeper"
        bot_persona_display_name = "报存"
        bot_persona_alt_profiles = alt

    return _Cfg()


def test_register_wins_over_env_compat_slot(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "display_name": "达妮娅（册子真身）", "qq": {"nickname": "达妮娅"}},
    )
    registry = PersonaProfileRegistry(reg_dir)
    config = _compat_config({"danya": {"display_name": "旧兼容名", "files": ["a.md"]}})
    specs = build_effective_alt_personas(config, registry=registry)
    assert specs["danya"].display_name == "达妮娅（册子真身）"  # 册子遮蔽兼容位


def test_compat_slot_only_for_unregistered_personas(tmp_path: Path) -> None:
    registry = PersonaProfileRegistry(tmp_path / "empty")  # 无目录/无文件
    config = _compat_config({"legacy": {"display_name": "旧人格", "files": ["x.md"]}})
    specs = build_effective_alt_personas(config, registry=registry)
    assert "legacy" in specs and specs["legacy"].display_name == "旧人格"


def test_current_bot_nickname_reads_register_not_login_info(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    _write_profile(reg_dir, "danya", {"persona_id": "danya", "qq": {"nickname": "达妮娅"}})
    registry = PersonaProfileRegistry(reg_dir)
    assert current_bot_nickname("danya", registry=registry) == "达妮娅"
    # 未在册 → 回落兼容显示名（仍不读 get_login_info）
    assert current_bot_nickname("ghost", registry=registry, config=_compat_config({})) == "报存"


# ---------------------------------------------------------------------------
# 5. get_login_info 防回归锁（台账 #60：自身身份缓存改后不刷新，禁作自称事实源）
# ---------------------------------------------------------------------------

def test_no_plugin_code_uses_get_login_info() -> None:
    # 只钉"调用形态"（作为动作名传进去 / 直接调方法），文档里作为散文提及不算违规。
    needles = ('"get_login_info"', "'get_login_info'", "get_login_info(")
    offenders: list[str] = []
    for path in (REPO_ROOT / "plugins").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(needle in text for needle in needles):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        "人格自称必须以人格册为唯一事实源（current_bot_nickname），"
        f"下列源码把改后不刷新的 get_login_info 当调用/自称事实源：{offenders}"
    )


# ---------------------------------------------------------------------------
# 自证锁：唯一下发口只经传入通道，绝不 import 任何真 bot / 不新建第二出站通路
# ---------------------------------------------------------------------------

def test_dispatch_outlet_is_transport_agnostic() -> None:
    import inspect

    import plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile as pp

    source = inspect.getsource(pp.apply_persona_profile)
    assert "bot." not in source and "nonebot" not in source.lower()
    # 下发只经注入的 call_api 通道（以 _call_status(call_api, ...) 转发），不在下发口里直连具体驱动
    assert "call_api" in source and "_call_status(call_api" in source
