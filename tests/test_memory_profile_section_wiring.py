"""记忆画像波（席3，2026-10-03）接线锁：画像分区 / 言行账读写腿 / 昵称归属 /
宿主快照分区 / 会话画像注入串。

判据（每条一个测试，断言吃判据不吃计数）：

1. 【用户画像】分区：``compose_person_profile_context``/``render_profile`` 此前
   全树零消费者；本波经 providers 挂进【用户画像】分区的 attitude 载体——
   门（``bot_person_profile_enabled``）、归属门（requester==subject）、敏感面
   拒收与来源置信分档全部住在 person_profile 真身里；**空画像 ⇒ attitude 逐字节
   不追加**（空分区不渲染）。
2. 言行账（person_speech_events）读写腿：抽取侧 ``settle_extracted_facts`` 落账
   （原话→log_event）、画像分区渲染读出；敏感面自动来源拒收照抄真身判据；
   S12 回复形态自指闸语义不破坏（形态要求行不入事实，传记事实照记）。
3. 昵称归属：展示侧＝affinity.nickname（现役注入不动），结构化侧＝person_profile
   的 nickname 格，**两处不互写**（各记各的，冲突时不静默合并）。
4. 宿主快照分区：仅 admin/super_admin 注入；模块缺席（并行期 ImportError）/
   读数失败 fail-open 空串＝分区整块缺席。
5. 会话画像注入串：``conversation_profile.note_text`` 并进 sender_profile_note
   （键=值形状），平台事实段已有的格排除（两份口径不打架）；零 RPC
   （api_available=False，协议格 unprobed）。
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    DynamicAffinityStore,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract import (
    extract_memory_texts,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.person_profile import (
    EVENT_SAID,
    PERSON_EVENT_TABLE,
    SOURCE_DERIVED,
    SOURCE_SELF_REPORT,
    build_person_profile_store,
    compose_person_profile_context,
    person_profile_key,
    settle_extracted_facts,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.providers import (
    FileCharacterContextProvider,
    build_character_context_provider,
)

_PLATFORM = "qq"


def _profile_config(tmp_path: Path, *, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        bot_person_profile_enabled=enabled,
        bot_memory_db_path=str(tmp_path / "wuwa_memory.sqlite3"),
        bot_affinity_enabled=False,
        bot_memory_enabled=False,
    )


def _provider(tmp_path: Path, *, enabled: bool = True) -> FileCharacterContextProvider:
    config = _profile_config(tmp_path, enabled=enabled)

    def _describe(sender_id: str, session_id: str, query_text: str, platform: str) -> str:
        return compose_person_profile_context(
            config,
            requester_id=sender_id,
            subject_user_id=sender_id,
            session_id=session_id,
            query_text=query_text,
            platform_domain="qq" if platform == _PLATFORM else "",
        )

    return FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
        person_profile_describe=_describe,
    )


# ---------------------------------------------------------------------------
# 1. 用户画像分区挂载
# ---------------------------------------------------------------------------


def test_person_profile_section_mounts_into_relationship_attitude(tmp_path) -> None:
    config = _profile_config(tmp_path)
    store = build_person_profile_store(config)
    assert store is not None
    key = person_profile_key("u1", "qq")
    assert store.record(
        person_key=key, facet="hobby", value="我喜欢天文摄影",
        source=SOURCE_SELF_REPORT, session_key="qq:g1",
    ).stored
    provider = _provider(tmp_path)
    bundle = provider.build_context(
        request_id="r1", sender_id="u1", session_id="qq:g1",
        query_text="今晚有什么星星", platform=_PLATFORM,
    )
    attitude = bundle.relationship_context.attitude
    assert "记忆画像" in attitude
    assert "天文摄影" in attitude


def test_empty_profile_renders_nothing(tmp_path) -> None:
    config = _profile_config(tmp_path)
    assert build_person_profile_store(config) is not None
    provider = _provider(tmp_path)
    bundle = provider.build_context(
        request_id="r1", sender_id="nobody", session_id="qq:g1",
        query_text="在吗", platform=_PLATFORM,
    )
    # 空画像 ⇒ attitude 不追加（空分区不渲染；基线 attitude 无「记忆画像」字样）。
    assert "记忆画像" not in bundle.relationship_context.attitude


def test_profile_gate_off_keeps_attitude_untouched(tmp_path) -> None:
    provider = _provider(tmp_path, enabled=False)
    bundle = provider.build_context(
        request_id="r1", sender_id="u1", session_id="qq:g1",
        query_text="在吗", platform=_PLATFORM,
    )
    assert "记忆画像" not in bundle.relationship_context.attitude


def test_profile_renders_only_for_the_person_themselves(tmp_path) -> None:
    """归属门：requester != subject ⇒ 一条不给（判据真身在 render_profile）。"""
    config = _profile_config(tmp_path)
    store = build_person_profile_store(config)
    key = person_profile_key("u1", "qq")
    store.record(
        person_key=key, facet="hobby", value="我喜欢天文摄影",
        source=SOURCE_SELF_REPORT, session_key="qq:g1",
    )
    # 换一个发起人（同域）⇒ 组合口给空串。
    assert (
        compose_person_profile_context(
            config, requester_id="u2", subject_user_id="u1",
            session_id="qq:g1", query_text="他喜欢什么", platform_domain="qq",
        )
        == ""
    )


# ---------------------------------------------------------------------------
# 2. 言行账读写腿
# ---------------------------------------------------------------------------


def test_speech_event_written_by_extraction_leg_and_rendered_back(tmp_path) -> None:
    config = _profile_config(tmp_path)
    store = build_person_profile_store(config)
    key = person_profile_key("u1", "qq")
    settle_extracted_facts(
        store,
        person_key=key,
        session_key="qq:g1",
        facts=["她喜欢天文摄影"],
        original_user_text="我昨天半夜去山顶拍星星了",
    )
    with sqlite3.connect(config.bot_memory_db_path) as connection:
        rows = connection.execute(
            f"SELECT kind, quote FROM {PERSON_EVENT_TABLE} WHERE person_key = ?",
            (key,),
        ).fetchall()
    # 原话只进行为账（模型转述只进画像字段，两来源分开记账是真身语义）。
    assert any(row[0] == EVENT_SAID and "拍星星" in row[1] for row in rows)
    rendered = store.render_profile(
        person_key=key, requester_key=key, session_key="qq:g1", query_text="拍星星",
    )
    assert "你交代过、我留着的话" in rendered
    assert "拍星星" in rendered


def test_sensitive_auto_source_event_refused(tmp_path) -> None:
    """敏感面红线照抄真身（health 词面 × 自动来源 ⇒ 拒收且零落行）。"""
    config = _profile_config(tmp_path)
    store = build_person_profile_store(config)
    key = person_profile_key("u1", "qq")
    assert (
        store.log_event(
            person_key=key, kind=EVENT_SAID, quote="我被确诊了抑郁症在吃药",
            source=SOURCE_DERIVED,
        )
        is None
    )
    with sqlite3.connect(config.bot_memory_db_path) as connection:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {PERSON_EVENT_TABLE} WHERE person_key = ?",
            (key,),
        ).fetchone()[0]
    assert count == 0


class _StubLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, messages: object, **options: object) -> SimpleNamespace:
        return SimpleNamespace(text=self._text)


def test_s12_reply_form_gate_semantics_intact(tmp_path) -> None:
    """S12 回复形态自指闸：形态要求行不入事实；同轮传记事实照记（宁可漏拦不可误拦）。"""
    facts = extract_memory_texts(
        _StubLLM("回复里别再带喵\n我喜欢天文摄影"),
        user_text="以后回复别再带喵，我喜欢天文摄影",
        reply_text="好的呀",
    )
    assert facts == ["我喜欢天文摄影"]


# ---------------------------------------------------------------------------
# 3. 昵称归属：两处各记各的，不互写
# ---------------------------------------------------------------------------


def test_nickname_attribution_two_ledgers_no_crosswrite(tmp_path) -> None:
    profile_config = _profile_config(tmp_path)
    profile_store = build_person_profile_store(profile_config)
    profile_key = person_profile_key("u1", "qq")
    assert profile_store.record(
        person_key=profile_key, facet="nickname", value="小天",
        source=SOURCE_SELF_REPORT, session_key="qq:g1",
    ).stored
    # 结构化侧记了账，展示侧（affinity.nickname）不被代写。
    affinity_store = DynamicAffinityStore(tmp_path / "affinity.sqlite3")
    affinity_store.observe("u1", "positive")
    assert affinity_store.snapshot("u1")["nickname"] == ""
    # 展示侧自己记的小名也不回写结构化侧。
    with sqlite3.connect(tmp_path / "affinity.sqlite3") as connection:
        connection.execute(
            "UPDATE user_affinity SET nickname = ? WHERE sender_id = ?", ("小岸", "u1")
        )
    assert affinity_store.snapshot("u1")["nickname"] == "小岸"
    # 结构化侧只有本人记的那条，展示侧的小名不回写进来（两账零互写）。
    profile_nicknames = [
        item.value for item in profile_store.facets(profile_key, facets=["nickname"])
    ]
    assert profile_nicknames == ["小天"]
    rendered = profile_store.render_profile(
        person_key=profile_key, requester_key=profile_key, session_key="qq:g1",
    )
    assert "小天" in rendered


# ---------------------------------------------------------------------------
# 4. 宿主快照分区（席6 并行件；import 面 fail-open）
# ---------------------------------------------------------------------------

_HOST_SNAPSHOT_MODULE = "plugins.bot_unified_runtime.domains.ops.host_snapshot"


def _fake_host_snapshot_module(behavior: str) -> types.ModuleType:
    module = types.ModuleType(_HOST_SNAPSHOT_MODULE)

    def _section(max_age_seconds: int = 30) -> str:
        if behavior == "ok":
            return "【宿主快照】\n- CPU 占用 3%"
        raise RuntimeError("boom")

    module.host_snapshot_section_text = _section  # type: ignore[attr-defined]
    return module


def _build_context(provider: FileCharacterContextProvider, roles: list[str]):
    return provider.build_context(
        request_id="r1", sender_id="u1", session_id="qq:g1",
        query_text="在吗", platform=_PLATFORM, sender_roles=roles,
    )


def test_host_snapshot_section_injected_for_admin(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, _HOST_SNAPSHOT_MODULE, _fake_host_snapshot_module("ok")
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    bundle = _build_context(provider, roles=["admin"])
    assert "【宿主快照】" in bundle.quirks_section
    bundle = _build_context(provider, roles=["super_admin"])
    assert "【宿主快照】" in bundle.quirks_section


def test_host_snapshot_section_absent_for_plain_user(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, _HOST_SNAPSHOT_MODULE, _fake_host_snapshot_module("ok")
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    assert "【宿主快照】" not in _build_context(provider, roles=["user"]).quirks_section
    assert "【宿主快照】" not in _build_context(provider, roles=[]).quirks_section


def test_host_snapshot_section_missing_module_fails_open(monkeypatch) -> None:
    # 并行期模块未落盘：sys.modules 塞 None ⇒ import 抛 ImportError ⇒ 空串。
    monkeypatch.setitem(sys.modules, _HOST_SNAPSHOT_MODULE, None)
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    assert _build_context(provider, roles=["admin"]).quirks_section == ""


def test_host_snapshot_section_reader_failure_fails_open(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules, _HOST_SNAPSHOT_MODULE, _fake_host_snapshot_module("raise")
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    assert _build_context(provider, roles=["admin"]).quirks_section == ""


# ---------------------------------------------------------------------------
# 5. 会话画像注入串（席2 note_text → sender_profile_note）
# ---------------------------------------------------------------------------


def test_conversation_profile_note_appends_to_sender_profile_note() -> None:
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    bundle = provider.build_context(
        request_id="r1", sender_id="u1", session_id="qq:g1",
        query_text="在吗", platform=_PLATFORM, group_id="g1",
        sender_profile_note="平台角色=member",
    )
    # 平台事实段在前、注入串并进同一段（键=值形状），且平台段已有的格不重复。
    assert bundle.sender_profile_note.startswith("平台角色=member；")
    assert "账号（QQ 号）=u1" in bundle.sender_profile_note
    assert "群号=g1" in bundle.sender_profile_note
    assert "群名片=" not in bundle.sender_profile_note.split("；", 1)[1]


def test_conversation_profile_note_absent_module_fails_open(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "plugins.bot_unified_runtime.domains.chat_reply.runtime.conversation_profile",
        None,
    )
    provider = FileCharacterContextProvider(
        persona_profile_id="default",
        persona_display_name="报存",
        persona_version="0",
        persona_files=[],
        knowledge_files=[],
    )
    bundle = provider.build_context(
        request_id="r1", sender_id="u1", session_id="qq:g1",
        query_text="在吗", platform=_PLATFORM, group_id="g1",
        sender_profile_note="平台角色=member",
    )
    assert bundle.sender_profile_note == "平台角色=member"


# ---------------------------------------------------------------------------
# 6. 装配口接线：build_character_context_provider 真把闭包挂上
# ---------------------------------------------------------------------------


def test_assembly_wires_person_profile_closure(tmp_path) -> None:
    provider = build_character_context_provider(_profile_config(tmp_path))
    assert callable(getattr(provider, "person_profile_describe", None))
    # 门关 ⇒ 空串；门开 + 有账 ⇒ 渲染文本（键形经 platform_domain_of 与写侧同源）。
    assert provider.person_profile_describe("u1", "qq:g1", "在吗", _PLATFORM) == ""
    config = _profile_config(tmp_path)
    store = build_person_profile_store(config)
    key = person_profile_key("u1", "qq")
    store.record(
        person_key=key, facet="hobby", value="我喜欢天文摄影",
        source=SOURCE_SELF_REPORT, session_key="qq:g1",
    )
    section = provider.person_profile_describe("u1", "qq:g1", "星星", _PLATFORM)
    assert "天文摄影" in section
    # 未知平台域 ⇒ 空域段独立桶（fail-closed），读不到 qq 桶的账。
    section_unknown = provider.person_profile_describe("u1", "qq:g1", "星星", "carrier-pigeon")
    assert section_unknown == ""


def test_assembly_gate_off_returns_empty_section(tmp_path) -> None:
    provider = build_character_context_provider(_profile_config(tmp_path, enabled=False))
    assert provider.person_profile_describe("u1", "qq:g1", "在吗", _PLATFORM) == ""


@pytest.mark.parametrize("value", ["", None])
def test_profile_section_never_raises(value: object) -> None:
    """组合口对脏入参诚实给空串（绝不炸对话主链路）。"""
    config = SimpleNamespace(bot_person_profile_enabled=True)
    assert (
        compose_person_profile_context(
            config, requester_id="", subject_user_id="u1",
            session_id="", query_text="", platform_domain="",
        )
        == ""
    )
