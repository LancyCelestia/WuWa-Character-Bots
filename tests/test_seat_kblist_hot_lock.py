"""S-IMPL-KBLIST-HOT 活性锁：清单热随人格（真装配缝）＋三腿同册＋get_login_info 扩域。

锁面（坐标＝SEAT-AUDIT-PERSONA-KBLIST / SEAT-ATK-PERSONA-APPEARANCE 现算）：

1. K1 知识文件清单的消费腿**经真装配缝每轮现读**：同进程内入册/改册
   （备用人格 ``files.knowledge`` v1→v2）下一轮即随——装配期 dict 快照
   （审计 1.2 根病，探针 P1 知识清单腿）若回潮，本锁当场红。
   （手工注入 spec 的薄壳锁 ``test_knowledge_file_list_follows_persona`` 盖不住
   装配缝；本锁判据必经 ``build_character_context_provider`` 真缝。）
2. K2 主人格设定清单随册（审计 1.3 次级缺口补位）：在册 ``files.settings``
   表态即随、不表态回落 ``.env`` 基线——两个方向都热、无重启。
3. K3 三腿对 persona「存在性」判定一致（审计 R3：校验热/消费冻曾判定相反）：
   校验视图（``build_effective_alt_personas``，runtime_admin 现算用同款）＝
   文本消费腿（selector）＝外观册（registry.get），新增/删除后仍同册同判。
4. K4 切换回执与消费腿问**同一本册**（H-5乙 不留第二真身；H-1 回执形态）：
   回执 ``persona_text`` 报的在册设定份数 == 消费视图 spec.files 份数。
5. K5 get_login_info 禁读锁扩域（台账 #60 增量，ATK 清单③-6）：
   ``plugins/`` 零豁免逐字节扫；``third_party/`` 例外**逐文件在册点名**
   （在册死腿，禁活体接线）——摘扫描目录或名册漂移即红。

全离线：tmp_path 造人格册与文本文件，fake transport，零真实 personas/、Runtime、QQ。
注毒自证（私有副本）记录于席位报告 SEAT-IMPL-KBLIST-HOT.md。
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
    PersonaProfileRegistry,
    apply_persona_profile,
    build_effective_alt_personas,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 共用件
# ---------------------------------------------------------------------------

def _write_profile(registry_dir: Path, persona_id: str, payload: dict) -> Path:
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"{persona_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _mk(root: Path, name: str, marker: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(f"{marker} 正文一段。\n", encoding="utf-8")
    return path


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append((action, params))
        return {"retcode": 0}


class _StubStore:
    """假 runtime settings：只提供人格 override 现读口与 get_or 兜底。"""

    def __init__(self) -> None:
        self.override = ""

    def get_persona_override(self) -> str:
        return self.override

    def get_or(self, key: str, default):
        return default


def _stub_peripheral_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    """与 test_persona_hot_switch 同口径：无关外围构造器置 None，人格/清单腿保真身。"""
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


def _assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, main_files: list[Path], baseline_kb: list[Path]):
    """经真装配缝造 provider（人格册＝tmp 注入实例，零生产写面）。"""
    _stub_peripheral_builders(monkeypatch)
    reg_dir = tmp_path / "personas" / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    store = _StubStore()
    config = SimpleNamespace(
        bot_affinity_enabled=False,
        bot_persona_profile_id="shorekeeper",
        bot_persona_display_name="守岸人",
        bot_persona_files=main_files,
        bot_knowledge_files=baseline_kb,
        bot_persona_alt_profiles={},
        persona_registry=PersonaProfileRegistry(reg_dir),
    )
    provider = providers_mod.build_character_context_provider(config, runtime_settings=store)
    return provider, store, config, reg_dir


def _knowledge_sources(provider) -> set[str]:
    context = provider.build_context(
        request_id="r", sender_id="u", session_id="s", query_text="聊聊天吧"
    )
    return {chunk.source_id for chunk in context.knowledge_results.chunks}


def _persona_text(provider) -> str:
    context = provider.build_context(
        request_id="r", sender_id="u", session_id="s", query_text="聊聊天吧"
    )
    return context.persona.raw_text


# ---------------------------------------------------------------------------
# K1 知识清单经真装配缝热随人格（入册即随；改册 v1→v2 再随；全程不重启）
# ---------------------------------------------------------------------------

def test_knowledge_list_follows_persona_through_real_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_md = _mk(tmp_path / "main", "main.md", "主人格正文标记MAIN")
    base_kb = _mk(tmp_path / "kb", "base_kb.md", "基线清单")
    provider, store, config, reg_dir = _assembly(
        tmp_path, monkeypatch, main_files=[main_md], baseline_kb=[base_kb]
    )
    danya_dir = tmp_path / "personas" / "danya"  # F-D 锚根＝registry 父目录/danya
    kb_v1 = _mk(danya_dir, "kb_danya_v1.md", "达妮娅知识V1略长一些的内容")
    kb_v2 = _mk(danya_dir, "kb_danya_v2.md", "达妮娅知识V2内容换了")

    # Phase A：主人格无表态 → .env 基线清单。
    assert _knowledge_sources(provider) == {"base_kb"}

    # Phase B：装配**之后**入册带知识清单的备用人格并 switch——
    # 装配期冻结（审计 1.2）在此必红：清单腿应随新人格走。
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "files": {"knowledge": [str(kb_v1)]},
        },
    )
    store.override = "danya"
    assert _knowledge_sources(provider) == {"kb_danya_v1"}

    # Phase C：改册（清单 v1→v2）不重启——下一轮即随（探针 P1 清单冻结腿）。
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "files": {"knowledge": [str(kb_v2)]},
        },
    )
    assert _knowledge_sources(provider) == {"kb_danya_v2"}

    # Phase D：回切 default → 基线恢复（空表态回落兼容位，不是第二真身）。
    store.override = "default"
    assert _knowledge_sources(provider) == {"base_kb"}

    # 校验视图与消费腿同判据（视图新鲜度即装配缝本身，禁再引第二枚快照）。
    view = build_effective_alt_personas(config, registry=provider.persona_registry)
    assert view["danya"].knowledge_files == (str(kb_v2),)


# ---------------------------------------------------------------------------
# K2 主人格设定清单随册（在册表态即随；撤册回基线；两向皆热）
# ---------------------------------------------------------------------------

def test_main_persona_settings_follow_register_hot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_main = _mk(tmp_path / "main", "core_env.md", "基线设定标记ENV_MAIN")
    provider, _store, _config, reg_dir = _assembly(
        tmp_path, monkeypatch, main_files=[base_main], baseline_kb=[]
    )
    assert "ENV_MAIN" in _persona_text(provider)

    # 主人格入册并带 files.settings（F-D 锚＝personas/shorekeeper/）→ 下一轮随册。
    anchor = tmp_path / "personas" / "shorekeeper"
    alt_core = _mk(anchor, "core_register.md", "在册设定标记REGISTER_MAIN")
    _write_profile(
        reg_dir,
        "shorekeeper",
        {
            "persona_id": "shorekeeper",
            "is_main": True,
            "files": {"settings": [str(alt_core)]},
        },
    )
    text = _persona_text(provider)
    assert "REGISTER_MAIN" in text and "ENV_MAIN" not in text

    # 撤册表态（清单改空）→ 回落兼容位基线——回落腿同样热、不重启。
    _write_profile(
        reg_dir,
        "shorekeeper",
        {"persona_id": "shorekeeper", "is_main": True, "files": {"settings": []}},
    )
    text_back = _persona_text(provider)
    assert "ENV_MAIN" in text_back and "REGISTER_MAIN" not in text_back


# ---------------------------------------------------------------------------
# K3 三腿存在性判定一致（校验视图＝文本消费腿＝外观册；新增/删除同刻同判）
# ---------------------------------------------------------------------------

def test_three_legs_agree_on_persona_existence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_md = _mk(tmp_path / "main", "main.md", "主人格正文")
    provider, store, config, reg_dir = _assembly(
        tmp_path, monkeypatch, main_files=[main_md], baseline_kb=[]
    )
    registry = provider.persona_registry

    def _legs(persona_id: str) -> tuple[bool, bool, bool]:
        view = build_effective_alt_personas(config, registry=registry)
        spec = provider.persona_selector.select(override=persona_id)
        return (persona_id in view, spec is not None, registry.get(persona_id) is not None)

    # 未入册：三腿一致判"无"（select 回 None＝主人格继续，绝不在册外强切）。
    assert _legs("ghost") == (False, False, False)

    # 入册：三腿一致判"有"。
    anchor = tmp_path / "personas" / "nova"
    core = _mk(anchor, "core.md", "新人格设定")
    _write_profile(
        reg_dir,
        "nova",
        {"persona_id": "nova", "display_name": "新格", "files": {"settings": [str(core)]}},
    )
    assert _legs("nova") == (True, True, True)
    store.override = "nova"
    assert "新人格设定" in _persona_text(provider)

    # 删除册文件：三腿一致回到"无"（R3 旧病＝外观腿注销、消费腿仍持旧 spec）。
    (reg_dir / "nova.json").unlink()
    assert _legs("nova") == (False, False, False)
    assert "新格" not in _persona_text(provider)  # 消费腿回落主人格，不切到已注销人格


# ---------------------------------------------------------------------------
# K4 切换回执与消费腿问同一本册（份数即判据，不留第二真身）
# ---------------------------------------------------------------------------

def test_receipt_and_consumer_read_same_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_md = _mk(tmp_path / "main", "main.md", "主人格正文")
    provider, _store, config, reg_dir = _assembly(
        tmp_path, monkeypatch, main_files=[main_md], baseline_kb=[]
    )
    registry = provider.persona_registry
    anchor = tmp_path / "personas" / "danya"
    s1 = _mk(anchor, "s1.md", "设定一")
    s2 = _mk(anchor, "s2.md", "设定二")
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "display_name": "达妮娅",
            "qq": {"nickname": "达妮娅", "signature": "微光"},
            "files": {"settings": [str(s1), str(s2)]},
        },
    )
    record = registry.get("danya")
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
        )
    )
    by_item = {item.item: item for item in receipt.items}
    text_item = by_item["persona_text"]
    assert text_item.status == "ok" and "2 份" in text_item.detail

    # 回执说的份数必须==消费腿现读视图的份数（同一本册，无双判据）。
    view = build_effective_alt_personas(config, registry=registry)
    assert len(view["danya"].files) == len(record.settings_files) == 2


# ---------------------------------------------------------------------------
# K5 get_login_info 禁读锁扩域：plugins/ 零豁免＋third_party/ 例外在册点名
# ---------------------------------------------------------------------------

#: 扫描根名册——摘目录必红（ATK 清单③-6 锁形态：名册入册，漂移即红）。
#: 例外登记＝"在册死腿，禁活体接线"：该调用属第三方插件 portrayal，
#: 非本机器人自身昵称事实源；台账 #60 禁的是把 get_login_info 当**自称**读数。
_LOGIN_INFO_REGISTERED_EXCEPTIONS: dict[str, frozenset[str]] = {
    "plugins": frozenset(),
    "third_party": frozenset(
        {str(Path("third_party") / "astrbot_plugin_portrayal" / "main.py")}
    ),
}


def test_get_login_info_ban_lock_with_registered_third_party_exception() -> None:
    # 名册自钉：扫描根清单先钉死——摘根（＝摘执法面）当场红，再查逐根命中。
    assert set(_LOGIN_INFO_REGISTERED_EXCEPTIONS) == {"plugins", "third_party"}, (
        "get_login_info 扫描根名册漂移：扩域/缩域都须经点名评审，不许静默摘目录"
    )
    needles = ('"get_login_info"', "'get_login_info'", "get_login_info(")
    for root, expected in _LOGIN_INFO_REGISTERED_EXCEPTIONS.items():
        root_dir = REPO_ROOT / root
        offenders: set[str] = set()
        for path in root_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(needle in text for needle in needles):
                offenders.add(str(path.relative_to(REPO_ROOT)))
        assert offenders == expected, (
            f"{root}/ 域 get_login_info 读数漂移——新增使用须点名评审，"
            f"注销例外须更新名册（台账 #60：自身身份缓存改后不刷新，禁作自称事实源）。"
            f" 实际命中={sorted(offenders)} 在册={sorted(expected)}"
        )
