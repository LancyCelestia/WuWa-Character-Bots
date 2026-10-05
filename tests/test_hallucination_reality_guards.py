"""幻觉根治 + 现实坐标面的席 S2 锁（2026-10-02）。

量什么
------
波次取证的四条实锤，逐条一把锁，**全部离线 mock、不碰生产路径**：

① 现实坐标恒渲染：`addressing.REALITY_COORDINATES_NOTE` 存在、全仓只有一处该字面，
   且渲染口（chat.py）今天拿到的那句就是它自己——没有第二份措辞。
② 反幻觉约束在**渲染后**的 system prompt 里（不是只在常量里躺着）。
③ 【知识库】里的第一人称回忆：非人格家族的块逐行标「他人经历引文」；
   `subject_kind` 列**缺席时照常工作**（S5 席的列今天还不存在），
   列落地后自动升级；包裹层仍是那一套 `_wrap_untrusted_context_block`。
④ 出口窄守门：人格白名单之外的第一人称亲历句被摘掉；白名单内/无形态/**异常**
   三种情况一字不动（fail-open）；并锁住它真接在 `build_chat_result` 的出站链上。

不在本件的账
------------
抽取层（`character/memory_extract.py`）拒收 assistant 自陈——那是别席的在飞面
（该件此刻带着未入库的 W1 改写），本席按文件域互斥没有动它，故此处**不放会红的锁**；
补丁草案与复跑证据见波次简报（席 S2 段）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    KnowledgeChunk,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat as rp
from plugins.bot_unified_runtime.domains.chat_reply.character import addressing

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDRESSING_FILE = (
    REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py"
)
CHAT_FILE = (
    REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
)
PERSONAS_DIR = REPO_ROOT / "personas"

#: 现实坐标文案的**签名句**（在源码里连成一段、可逐字扫；全仓只许有一处）。
#: 刻意不用「广州库洛科技有限公司」当签名——那是 S3 席实体关系册里的**登记项**
#: （`domains/core/search/entity_relations.py` 的取数示例，2026-10-02 现算在册），
#: 拿它当单源判据会把一份正当的实体名册咬成副本。签名句只可能来自这句恒渲染文案。
REALITY_NOTE_SIGNATURE = "库洛在故事之外，不是游戏世界里的组织或势力"
#: 开发主体全称：只查**人格源**有没有抄第二份（代码侧由签名句那条判据管）。
DEVELOPER_LITERAL = "广州库洛科技有限公司"

#: 反幻觉约束那句（席 S2 追加进 `_RUNTIME_ANSWER_RULES` 的唯一一行）。
ANTI_FABRICATION_CLAUSE = (
    "资料里出现的第一人称回忆属于资料所写之人、不属于你，你没被写过的经历不得说成亲历。"
)

#: 「别人的一生」形态（生产事故重放用的两条：一条真·他人回忆、一条设定内）。
_OTHERS_RECITAL = "嘉贝莉娜小时候在枫丹的旧宅里长大，她记得那里的海风。"
_FIRST_PERSON_RECITAL = "我小时候在穗波市的旧港区长大，亲眼见过那场悲鸣之后的静。"

_PERSONA_RAW = (
    "# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。"
    "常驻黑海岸的花房钢琴旁。"
)


def _context(
    *, chunks: list[KnowledgeChunk] | None = None, budget: int = 24576
) -> ContextBundle:
    """私聊形态的最小 ContextBundle（预算取生产私聊档 24576）。"""
    return ContextBundle(
        request_id="req-s2",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人，黑海岸的守护者",
            raw_text=_PERSONA_RAW,
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-s2"),
        conversation_history=ConversationHistoryResult(request_id="req-s2"),
        knowledge_results=RetrievalResult(request_id="req-s2", chunks=chunks or []),
        current_message="你是谁做的？",
        sender_id="user-s2",
        session_id="private:user-s2",
        context_budget=budget,
    )


def _chunk(content: str, library: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=f"chunk-{library}",
        source_id=f"wuwa/{library}/正文/条目__1",
        title="条目",
        content=content,
        source_library=library,
    )


def _system_prompt(context: ContextBundle) -> str:
    return rp.build_chat_prompt(context)[0]["content"]


def _read_text(path: Path) -> str:
    """按字节读再容错解码：人格目录里可能有非 UTF-8 素材，别让解码异常把扫描面缩小。"""
    return path.read_bytes().decode("utf-8", "ignore")


def _literal_hits(paths: list[Path], needle: str) -> list[tuple[str, int]]:
    """判据只写一遍：真树与注毒样本走同一条腿（禁在测试里另起一把尺）。"""
    hits: list[tuple[str, int]] = []
    for path in paths:
        count = _read_text(path).count(needle)
        if count:
            hits.append((path.name, count))
    return hits


# ---------------------------------------------------------------------------
# ① 现实坐标：常量存在 + 全仓单源
# ---------------------------------------------------------------------------
def test_reality_coordinates_constant_and_reader_exist() -> None:
    note = getattr(addressing, "REALITY_COORDINATES_NOTE", None)
    assert isinstance(note, str) and note.strip(), "现实坐标常量缺席＝恒渲染那块根本没有东西"
    for fact in ("鸣潮", DEVELOPER_LITERAL, "KURO GAMES"):
        assert fact in note, f"现实坐标缺了这条事实：{fact}"
    assert note.count("。") <= 3, f"现实坐标超出三行内的口径：{note!r}"
    assert REALITY_NOTE_SIGNATURE in note, "签名句被改写＝下面两条单源判据认不出真身"
    assert addressing.reality_coordinates_note() == note


def test_reality_note_has_exactly_one_source_in_the_tree() -> None:
    """代码面（plugins/**.py）只许有一处这句恒渲染文案——别处再端一份当场红。"""
    scanned_py = list((REPO_ROOT / "plugins").rglob("*.py"))
    assert len(scanned_py) > 500, f"扫描面塌了（{len(scanned_py)} 枚 py 件）＝这把尺在空跑"
    hits = _literal_hits(scanned_py, REALITY_NOTE_SIGNATURE)
    assert hits == [(ADDRESSING_FILE.name, 1)], (
        f"现实坐标签名句出现={hits}，正身应当只有 addressing.py 一处"
    )


def test_personas_do_not_carry_a_second_copy_of_the_reality_note() -> None:
    """人格源零副本（切人格会整份换掉，现实坐标是不变量 ⇒ 只许住在代码里）。"""
    if not PERSONAS_DIR.is_dir():
        pytest.skip("人格源目录不在场＝这台机没有 personas/，判据不适用")
    persona_files = [p for p in PERSONAS_DIR.rglob("*") if p.is_file()]
    assert persona_files, "personas/ 在而扫不到件＝扫描面塌了"
    for needle in (REALITY_NOTE_SIGNATURE, DEVELOPER_LITERAL):
        assert _literal_hits(persona_files, needle) == [], f"personas/ 抄了第二份现实坐标：{needle}"


def test_poison_second_copy_would_be_caught(tmp_path: Path) -> None:
    """注毒腿：别处再抄一份同签名 ⇒ 单源判据必须红（否则那把尺是空跑的）。"""
    fake = tmp_path / "_second_copy.py"
    fake.write_text(f'NOTE = "{REALITY_NOTE_SIGNATURE}。"\n', encoding="utf-8")
    assert _literal_hits([fake], REALITY_NOTE_SIGNATURE) == [(fake.name, 1)], "注毒样本没被读出来＝尺本身失效"
    assert _literal_hits([ADDRESSING_FILE, fake], REALITY_NOTE_SIGNATURE) != [
        (ADDRESSING_FILE.name, 1)
    ], "多一处副本而判据没抓住＝那枚 ==1 是空判"


def test_reality_coordinates_declare_tech_layer_is_knowable() -> None:
    """现实坐标要登记「故事外的技术层她可知」——否则科技名词又只能靠撞检索。"""
    note = addressing.reality_coordinates_note()
    assert "芯片" in note and "模型" in note, "现实坐标没登记技术层 ⇒ 科技名词又只能靠撞检索"
    assert "不描述她是谁" in note or "不描述自己" in note, "缺自指让位条款 ⇒ 概念层又会被读成禁令"


def test_reality_coordinates_not_duplicated_into_personas() -> None:
    """新增那句也不许被抄进 personas/（复用本件既有采集器 _literal_hits，不另起一把尺）。"""
    if not PERSONAS_DIR.is_dir():
        pytest.skip("人格源目录不在场＝这台机没有 personas/，判据不适用")
    persona_files = [p for p in PERSONAS_DIR.rglob("*") if p.is_file()]
    for needle in ("芯片、模型", "那一层世界里"):
        assert _literal_hits(persona_files, needle) == [], f"personas/ 抄了第二份现实坐标：{needle}"


# ---------------------------------------------------------------------------
# ②/接线：恒渲染 + 无第二真身
# ---------------------------------------------------------------------------
def test_reality_section_renders_after_creator_block() -> None:
    prompt = _system_prompt(_context())
    assert "【现实坐标】" in prompt, "现实坐标没有进渲染后的 system prompt"
    note = addressing.reality_coordinates_note().strip()
    assert note in prompt, "渲染出来的不是常量的全文（被裁或被改写）"
    assert prompt.index("【创造者】") < prompt.index("【现实坐标】"), "没有紧跟【创造者】之后"
    # 装配位次的另一半：带齐后续分区（群号/名册）时仍排在它们之前。
    richer, _ = rp.build_chat_prompt_with_diagnostics(
        _context(), admin_roster_text="超管：一位", group_id="123456"
    )
    richer_prompt = richer[0]["content"]
    assert (
        richer_prompt.index("【现实坐标】")
        < richer_prompt.index("【当前群聊】")
        < richer_prompt.index("【管理团队】")
    )


def test_reality_note_has_no_second_producer_in_chat_py(monkeypatch) -> None:
    """改真身 ⇒ 渲染跟着改；真身置空 ⇒ 整块不出现（非空才渲染，空分区不渲染）。"""
    monkeypatch.setattr(addressing, "REALITY_COORDINATES_NOTE", "换成另一枚现实坐标说法")
    prompt = _system_prompt(_context())
    assert "换成另一枚现实坐标说法" in prompt and addressing.CREATOR_NOTE in prompt
    assert "广州库洛科技有限公司" not in prompt, "chat.py 里还留着一份自写的现实坐标文案"

    monkeypatch.setattr(addressing, "REALITY_COORDINATES_NOTE", "")
    assert "【现实坐标】" not in _system_prompt(_context())


def test_anti_fabrication_clause_is_in_rendered_system_prompt() -> None:
    assert ANTI_FABRICATION_CLAUSE in rp._RUNTIME_ANSWER_RULES
    assert ANTI_FABRICATION_CLAUSE in _system_prompt(_context())
    # 「不得改动同区其他条目」的可复核形态：既有条目一字不少。
    for kept in (
        "先直接回应用户最后一条消息的核心意图",
        "不复述检索原文，不编造未被资料支持的内容；资料不足时明确指出缺口。",
    ):
        assert kept in rp._RUNTIME_ANSWER_RULES


# ---------------------------------------------------------------------------
# ③ 他人经历引文标注（schema 无关）
# ---------------------------------------------------------------------------
def test_subject_kind_column_is_absent_today_and_annotation_still_fires() -> None:
    """今天的事实核账：契约里没有 `subject_kind` 这列，本腿必须照常判得出来。"""
    assert not hasattr(_chunk(_FIRST_PERSON_RECITAL, "kb_wiki"), "subject_kind")
    body = rp._knowledge_lines(_context(chunks=[_chunk(_FIRST_PERSON_RECITAL, "kb_wiki")]))
    assert rp._OTHERS_RECITAL_TAG in body, "缺列就不标＝把 S5 的列写成了硬依赖"


def test_non_persona_first_person_recital_is_tagged_in_rendered_prompt() -> None:
    prompt = _system_prompt(_context(chunks=[_chunk(_FIRST_PERSON_RECITAL, "kb_wiki")]))
    assert rp._OTHERS_RECITAL_TAG in prompt
    tagged = [line for line in prompt.splitlines() if rp._OTHERS_RECITAL_TAG in line]
    assert len(tagged) == 1 and "穗波市" in tagged[0], tagged
    assert tagged[0].startswith("- ["), "标注落在了行首＝动了组装口的身份行形"


def test_persona_library_recital_is_never_tagged() -> None:
    """人格家族自己的第一人称经历可以是她的：标成"他人引文"＝把人格读成别人。"""
    body = rp._knowledge_lines(_context(chunks=[_chunk(_FIRST_PERSON_RECITAL, "persona")]))
    assert rp._OTHERS_RECITAL_TAG not in body


def test_third_person_biography_line_is_not_tagged() -> None:
    """反向不误伤：没有「我」的成长叙述不该被标成第一人称引文。"""
    body = rp._knowledge_lines(_context(chunks=[_chunk(_OTHERS_RECITAL, "kb_wiki")]))
    assert rp._OTHERS_RECITAL_TAG not in body


@pytest.mark.parametrize(
    ("kind", "tagged"),
    [("self", False), ("persona", False), ("other", True), ("", True)],
    ids=["self", "persona", "other", "column-absent"],
)
def test_subject_kind_column_upgrades_the_decision_when_present(kind, tagged) -> None:
    """S5 的列落地后自动认列：`self/persona` 不标、`other` 标、读不到退回形态判。

    `model_copy(update=...)` 在 StrictBaseModel 上直接挂属性——正是本腿要的形态：
    列有没有都不炸（判据走 `getattr`，不依赖 schema）。
    """
    chunk = _chunk(_FIRST_PERSON_RECITAL, "kb_wiki")
    if kind:
        chunk = chunk.model_copy(update={"subject_kind": kind})
    body = rp._knowledge_lines(_context(chunks=[chunk]))
    assert (rp._OTHERS_RECITAL_TAG in body) is tagged


def test_misaligned_lines_fall_back_to_content_form() -> None:
    """行与块数目不等 ⇒ 不猜对齐，只按内容判（宁少用一条身份依据）。"""
    chunks = [_chunk(_FIRST_PERSON_RECITAL, "kb_wiki").model_copy(update={"subject_kind": "self"})]
    lines = ["- [a] 第一条", "- [b] " + _FIRST_PERSON_RECITAL]
    marked = rp._mark_others_experience_lines(lines, chunks, "kb_wiki")
    assert rp._OTHERS_RECITAL_TAG not in marked[0]
    assert rp._OTHERS_RECITAL_TAG in marked[1]


def test_annotation_reuses_the_single_untrusted_wrapper() -> None:
    """包裹层零新增：标注前后都只有那一套 `_wrap_untrusted_context_block`。"""
    for chunks in ([], [_chunk(_FIRST_PERSON_RECITAL, "kb_wiki")]):
        body = rp._knowledge_lines(_context(chunks=chunks))
        assert body.startswith(rp._UNTRUSTED_CONTEXT_PREFIX)
        assert body.endswith(rp._UNTRUSTED_CONTEXT_SUFFIX)
        assert body.count(rp._UNTRUSTED_CONTEXT_PREFIX) == 1
        assert body.count(rp._UNTRUSTED_CONTEXT_SUFFIX) == 1


# ---------------------------------------------------------------------------
# ④ 出口窄守门（fail-open）
# ---------------------------------------------------------------------------
def test_outbound_guard_strips_borrowed_recital_outside_persona_whitelist() -> None:
    text = "我听过这件事。" + _FIRST_PERSON_RECITAL + "你怎么看？"
    stripped, hit = rp._strip_borrowed_recital_sentences(text, _PERSONA_RAW)
    assert "穗波市" not in stripped and "你怎么看？" in stripped and "我听过这件事。" in stripped
    assert _FIRST_PERSON_RECITAL in hit and hit, "命中原句没留痕＝审计读不到"


def test_outbound_guard_spares_the_whitelisted_and_the_shapeless() -> None:
    # 白名单内（人格原文里查得到这个地名）＝可能是她自己的设定，一字不动。
    hers = "我在黑海岸港区长大。"
    assert rp._strip_borrowed_recital_sentences(hers, _PERSONA_RAW + "\n黑海岸港区") == (hers, "")
    # 无形态（没有带后缀的专名）不动。
    for text in ("我小时候在海边玩过。", "我们聊过这件事。", "穗波市很美。"):
        assert rp._strip_borrowed_recital_sentences(text, _PERSONA_RAW) == (text, ""), text


def test_outbound_guard_is_fail_open_on_any_exception() -> None:
    """守门腿自己炸 ⇒ 原样放行（异常绝不把回复带走）。"""

    class _Boom:
        def __contains__(self, item) -> bool:
            raise RuntimeError("守门判据被灌了个坏白名单")

    text = _FIRST_PERSON_RECITAL
    assert rp._strip_borrowed_recital_sentences(text, _Boom()) == (text, "")
    assert rp._strip_borrowed_recital_sentences("", _PERSONA_RAW) == ("", "")


def test_outbound_guard_is_wired_into_the_send_chain() -> None:
    """接线锁：守门真在 `build_chat_result` 的出站链上被调，命中进 audit_tags。

    只扫函数体（AST），不看注释——注释里提一句不算接上（#72★「三格哑面在盘不在码」）。
    F-5 乙（2026-10-05）把出站归一化那一段收进 `_finalize_reply_text` 一处（补写的
    那一版必须再过同一段才谈得上"送达"），所以本锁的扫描面＝出站缝 **加上它走的那一段**，
    并显式钉「那一段真的被出站缝调到」——少了这一跳，搬进助手就等於摘掉接线。
    """
    tree = ast.parse(CHAT_FILE.read_text(encoding="utf-8"))

    def body_of(name: str) -> ast.FunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"chat.py 里没有 {name} ⇒ 本件要钉的那段链不在了")

    entry = body_of("build_chat_result")
    finalize = body_of("_finalize_reply_text")
    called = {
        node.func.id
        for scope in (entry, finalize)
        for node in ast.walk(scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_finalize_reply_text" in called, "出站缝不再经过归一化那一段 ⇒ 守门脱管"
    assert "_strip_borrowed_recital_sentences" in called, called
    assert "_persona_recital_whitelist_text" in called, called
    strings = {
        node.value
        for scope in (entry, finalize)
        for node in ast.walk(scope)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "llm_borrowed_recital_stripped" in strings, "命中没有留痕＝被摘掉的那句无处回查"


def test_outbound_guard_predicate_is_not_duplicated_elsewhere() -> None:
    """单源：出站守门的正则只有 chat.py 一处真身，别的模块不许再抄一把判据。"""
    owners = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "plugins").rglob("*.py")
        if "_OUTBOUND_RECITAL_RE" in _read_text(path)
    ]
    assert owners == [CHAT_FILE.relative_to(REPO_ROOT).as_posix()], owners
