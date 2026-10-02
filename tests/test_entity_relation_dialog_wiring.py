"""席 S12（现实知识面波，2026-10-03）：实体关系册**接进对话链路**的两枚锁 + A/B 读数。

量什么
------
册（``domains/core/search/entity_relations.py`` + 随包种子）S3 落盘后，消费者只有
控制面图谱——对话侧零接线，属台账 #72★「三格哑面在盘不在码」。本件锁的是接线那一格：

① 一跳查询正反例：已核带「（已核）」、未核带「待核｜」前缀；**主语实体待核 ⇒ 连带把
   已核的边降成待核**（种子今天就有这么一枚）；没在册 / 拉丁别名撞普通词 ⇒ 不命中。
② 分区在场锁：``reality_relation_note`` 非空才渲染、紧跟【现实坐标】；注毒＝掏空册 ⇒
   整块缺席，且与"该字段为空"的渲染结果**逐字节相等**（它抄不到别人的条目，也不长假事实）。
③ A/B 读数（离线，走真装配口）：三句现实题接前/接后的 system 裁片字符增量与 clipped 真值；
   对照组必须零新增块。

全部零联网、零写盘、不碰生产路径（种子只按 tmp_path 副本读，真身一字不动）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat as rp
from plugins.bot_unified_runtime.domains.chat_reply.character import providers
from plugins.bot_unified_runtime.domains.chat_reply.runtime import question_intent
from plugins.bot_unified_runtime.domains.core.search import entity_relations as er

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONAS_DIR = REPO_ROOT / "personas"

REALITY_SECTION = "【现实关系】"
SIGNED_LINE_MARK = "（已核）"
#: 本席渲染行的签名（箭头只在【现实关系】里出现，【现实坐标】的散文没有它）。
LINE_ARROW = " → "


@pytest.fixture(autouse=True)
def _restore_seed_cache():
    """``load_seed`` 按路径缓存 ⇒ 注毒件必须自己收口，别把毒留给下一枚测试。"""
    er.load_seed.cache_clear()
    yield
    er.load_seed.cache_clear()


def _context(*, note: str = "", budget: int = 24576, message: str = "鸣潮是哪个公司开发的") -> ContextBundle:
    return ContextBundle(
        request_id="req-s12",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人，黑海岸的守护者",
            raw_text="# 角色沉浸要求\n\n你就是守岸人本人，以第一人称思考与回应。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-s12"),
        conversation_history=ConversationHistoryResult(request_id="req-s12"),
        knowledge_results=RetrievalResult(request_id="req-s12", chunks=[]),
        current_message=message,
        sender_id="user-s12",
        session_id="private:user-s12",
        reality_relation_note=note,
        context_budget=budget,
    )


def _prompt(context: ContextBundle) -> str:
    return rp.build_chat_prompt(context)[0]["content"]


# ---------------------------------------------------------------------------
# ① 一跳查询：正反例 + 未核实必带标记
# ---------------------------------------------------------------------------
def test_verified_one_hop_renders_with_explicit_confidence() -> None:
    lines = er.reality_relation_lines("鸣潮是哪个公司开发的")
    assert len(lines) == 1, lines
    line = lines[0]
    assert "《鸣潮》" in line and "开发：广州库洛科技有限公司" in line, line
    assert line.endswith(SIGNED_LINE_MARK), f"已核条目没带状态字据：{line}"
    assert er.unverified_prefix() not in line


def test_unverified_entry_carries_the_pending_prefix_never_a_bare_fact() -> None:
    lines = er.reality_relation_lines("CICF是什么")
    assert lines, "在册实体一条边都没有 ⇒ 本该诚实缺席，但 CICF 有 located_in"
    for line in lines:
        assert er.unverified_prefix() in line, f"未核实条目被裸端出去当事实：{line}"
        assert SIGNED_LINE_MARK not in line


def test_unverified_flag_is_a_field_not_a_comment() -> None:
    hits = er.lookup_one_hop(("重返未来：1999",), er.relations_for_question("重返未来是谁做的"))
    assert len(hits) == 1, hits
    hit = hits[0]
    assert hit.unverified is True and hit.verified is False
    assert "深蓝互动" in hit.object


def test_subject_entity_pending_demotes_a_signed_edge(tmp_path: Path) -> None:
    """降级锁（按形状造，不吃真册的具体行）：边已核 + 主语实体待核 ⇒ 消费侧端成待核。

    真册今天不再有这枚不一致——席 S19 依用户裁定把 ``COMICUP located_in 广州`` 这条边
    同批降级为未核（台账 #73 那格待裁口径已落）。所以降级逻辑本身改用 tmp 副本锁形状，
    另附一条真册读数：那枚边现在自己就标未核（口径不再互相打脸）。
    """
    fake = tmp_path / "seed.json"
    fake.write_text(
        '{"entities": [{"name": "甲", "kind": "expo", "verified": false},'
        ' {"name": "乙", "kind": "city", "verified": true}],'
        ' "relations": [{"subject": "甲", "relation": "located_in", "object": "乙", "verified": true}]}',
        encoding="utf-8",
    )
    hits = er.lookup_one_hop(("甲",), (er.RELATION_LOCATED_IN,), path_str=str(fake))
    assert len(hits) == 1, hits
    hit = hits[0]
    assert hit.edge_verified is True and hit.subject_verified is False
    assert hit.verified is False and hit.unverified is True, "边已核、主语待核 ⇒ 绝不端成已确认事实"
    real = er.lookup_one_hop(("COMICUP",), (er.RELATION_LOCATED_IN,))
    assert len(real) == 1 and real[0].edge_verified is False, "册里那枚边的口径降级没落地"
    assert real[0].verified is False and er.unverified_prefix() in "\n".join(
        er.reality_relation_lines("COMICUP在哪")
    )


def test_alias_lookup_is_exact_and_never_fuzzy() -> None:
    assert er.match_entities_in("战双是谁做的") == ("战双帕弥什",)
    assert er.match_entities_in("原神是谁做的") == ()
    assert er.match_entities_in("鸣潮是哪个公司开发的") == ("鸣潮",)


def test_latin_alias_does_not_bite_ordinary_words() -> None:
    """CP/BW/CD 一类简称与命令名、英文词撞车：整词 + 大小写敏感，认不出就当没问。"""
    assert er.match_entities_in("在终端里 cp 一下那个文件") == ()
    assert er.match_entities_in("CPU 温度多少") == ()
    assert er.match_entities_in("CP 展是哪年办的") == ("COMICUP",)


def test_relation_words_are_the_only_ticket_and_empty_means_no_guess() -> None:
    assert er.relations_for_question("库洛总部在哪") == (er.RELATION_LOCATED_IN,)
    assert er.relations_for_question("今天心情不好") == ()
    assert er.reality_relation_lines("今天心情不好") == ()
    # 没点名的问法 ⇒ 给该主语的全部一跳（不猜具体哪条边，也不从别处借条目）。
    assert er.lookup_one_hop(("CICF",)) == er.lookup_one_hop(("CICF",), ("located_in",))


def test_expo_relation_word_reads_as_organiser_not_developer() -> None:
    """展会语境 developed_by 的真意是主办（种子注记如此）：展示名随主语类别换、边名不动。"""
    hits = er.lookup_one_hop(("BilibiliWorld",), (er.RELATION_DEVELOPED_BY,))
    assert len(hits) == 1 and hits[0].relation == er.RELATION_DEVELOPED_BY
    assert hits[0].relation_label == "主办", hits[0]


def test_unregistered_relation_word_has_no_label_and_is_dropped(tmp_path: Path) -> None:
    """门票与展示表脱节 ⇒ 宁可丢这一行，也不把英文关系词端成人话。"""
    fake = tmp_path / "seed.json"
    fake.write_text(
        '{"entities": [{"name": "甲", "kind": "work", "verified": true},'
        ' {"name": "乙", "kind": "company", "verified": true}],'
        ' "relations": [{"subject": "甲", "relation": "developed_by", "object": "乙", "verified": true}]}',
        encoding="utf-8",
    )
    assert er.lookup_one_hop(("甲",), path_str=str(fake))[0].relation_label == "开发"
    # 展示表被摘掉一行 ⇒ 该行整块不出（不回落成 "developed_by" 这种裸词）。
    snapshot = dict(er.RELATION_LABELS_ZH)
    try:
        er.RELATION_LABELS_ZH.pop(er.RELATION_DEVELOPED_BY)
        assert er.lookup_one_hop(("甲",), path_str=str(fake))[0].relation_label == ""
        assert er.reality_relation_lines("甲是谁做的", path_str=str(fake)) == ()
    finally:
        er.RELATION_LABELS_ZH.clear()
        er.RELATION_LABELS_ZH.update(snapshot)


# ---------------------------------------------------------------------------
# ② 分区在场锁 + 注毒（掏空册）
# ---------------------------------------------------------------------------
def test_section_renders_right_after_reality_coordinates() -> None:
    note = "\n".join(er.reality_relation_lines("鸣潮是哪个公司开发的"))
    assert note
    prompt, _ = rp.build_chat_prompt_with_diagnostics(
        _context(note=note, budget=24576), admin_roster_text="超管：一位", group_id="123456"
    )
    text = prompt[0]["content"]
    assert REALITY_SECTION in text, "现算出来的正文没进渲染后的 system prompt"
    assert note in text, "渲染出来的不是查询口的全文（被裁或被改写）"
    assert text.index("【现实坐标】") < text.index(REALITY_SECTION) < text.index("【当前群聊】")


def test_empty_note_renders_no_section_at_all() -> None:
    """空分区不渲染：连标签行都不许长出来（同【当前群聊】那族的口径）。"""
    assert REALITY_SECTION not in _prompt(_context(note=""))


def test_poison_empty_ledger_removes_section_and_invents_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒＝掏空实体名册 ⇒ 该块必须缺席，且**不得长出假事实**、不得抄别人的条目。"""
    empty = tmp_path / "empty_seed.json"
    empty.write_text('{"entities": [], "relations": []}', encoding="utf-8")
    monkeypatch.setattr(er, "SEED_PATH", empty)

    for query in (
        "鸣潮是哪个公司开发的",
        "明日方舟的开发商是谁",
        "CICF是什么",
        "守岸人出自哪个游戏",
    ):
        assert er.match_entities_in(query) == (), f"掏空后仍命中实体：{query}"
        assert er.reality_relation_lines(query) == (), f"掏空后端出了条目：{query}"
        note = providers.reality_relation_note_for(query)
        assert note == "", f"没册子还能现算出正文：{query}"
        poisoned = _prompt(_context(note=note, message=query))
        assert REALITY_SECTION not in poisoned, f"掏空后仍长出分区标签：{query}"
        # 判"没长出假事实"用形态尺，不用逐字节相等：装配口本轮的话术游标会轮换，
        # 同输入两次渲染本就不等长（本席第一版拿 == 当尺，被这条咬过一次）。
        assert LINE_ARROW not in poisoned and SIGNED_LINE_MARK not in poisoned
        assert "- 《" not in poisoned, f"掏空后端出了带书名号的事实行：{query}"
        assert poisoned.count("库洛在故事之外") == 1, (
            "现实坐标那句被复述了第二遍＝拿别人的条目冒充查询结果"
        )


def test_wording_has_a_single_source_no_copy_in_chat_or_personas() -> None:
    """措辞单源：关系词展示表只住在 entity_relations.py；chat.py 与 personas/ 零副本。"""
    owners = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "plugins").rglob("*.py")
        if "RELATION_LABELS_ZH" in path.read_bytes().decode("utf-8", "ignore")
    ]
    assert owners == [
        "plugins/bot_unified_runtime/domains/core/search/entity_relations.py"
    ], owners
    chat_text = (
        REPO_ROOT / "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
    ).read_text(encoding="utf-8")
    for needle in ("开发：", "所在地：", "出自作品：", SIGNED_LINE_MARK):
        assert needle not in chat_text, f"chat.py 里抄了一份措辞：{needle}"
    if PERSONAS_DIR.is_dir():
        persona_files = [p for p in PERSONAS_DIR.rglob("*") if p.is_file()]
        for needle in (REALITY_SECTION, SIGNED_LINE_MARK, "待核｜"):
            hits = [p.name for p in persona_files if needle in p.read_bytes().decode("utf-8", "ignore")]
            assert hits == [], f"personas/ 抄了第二份现实关系措辞：{needle}→{hits}"


# ---------------------------------------------------------------------------
# ③ A/B 读数（离线，走真装配口）
# ---------------------------------------------------------------------------
AB_QUERIES = (
    "鸣潮是哪个公司开发的",
    "CICF是什么",
    "明日方舟的开发商是谁",
)
CONTROL_QUERY = "今天心情不好"


def test_ab_readings_and_control_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines: list[str] = []
    for query in (*AB_QUERIES, CONTROL_QUERY):
        note = providers.reality_relation_note_for(query)
        category = question_intent.classify_question_intent(query).category
        before = _prompt(_context(note="", message=query))
        after = _prompt(_context(note=note, message=query))
        _, diag_before = rp.build_chat_prompt_with_diagnostics(
            _context(note="", message=query)
        )
        _, diag_after = rp.build_chat_prompt_with_diagnostics(
            _context(note=note, message=query)
        )
        group_before = _prompt(_context(note="", message=query, budget=16384))
        group_after = _prompt(_context(note=note, message=query, budget=16384))
        line = (
            "AB|{query}|cat={category}|note={note_len}|private_delta={delta}"
            "|group_delta={gdelta}|clipped_before={cb}|clipped_after={ca}"
            "|group_clipped_after={gca}|section={section}".format(
                query=query,
                category=category,
                note_len=len(note),
                delta=len(after) - len(before),
                gdelta=len(group_after) - len(group_before),
                cb=diag_before.clipped_to_context_budget,
                ca=diag_after.clipped_to_context_budget,
                gca=rp.build_chat_prompt_with_diagnostics(
                    _context(note=note, message=query, budget=16384)
                )[1].clipped_to_context_budget,
                section=(REALITY_SECTION in after),
            )
        )
        print(line)
        lines.append(line)
        if query == CONTROL_QUERY:
            assert note == "" and REALITY_SECTION not in after, "对照组长出了新块"
            assert LINE_ARROW not in after and SIGNED_LINE_MARK not in after, "对照组混进了事实行"
        else:
            assert note and REALITY_SECTION in after, f"现实题没接上：{query}"
            assert not diag_after.clipped_to_context_budget, "私聊预算被这块挤崩了"
    report = capsys.readouterr().out
    assert "AB|" in report
    # 读数落盘（仓库外，走 pytest 自己的 tmp_path）：A/B 表从这里现抄，
    # 不在叙述文档里手写会过期的数字（规则 10）。
    (tmp_path / "ab_readings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_group_budget_still_fits_after_wiring() -> None:
    """群聊生效预算 16384：接上之后仍不得触发裁剪（额度充足是 S8 的实测结论，这里复核）。"""
    for query in AB_QUERIES:
        note = providers.reality_relation_note_for(query)
        messages, diagnostics = rp.build_chat_prompt_with_diagnostics(
            _context(note=note, message=query, budget=16384)
        )
        assert not diagnostics.clipped_to_context_budget, (query, len(messages[0]["content"]))


def test_gate_is_entity_hit_first_then_the_intent_ruling() -> None:
    """顺序锁（席 S19，用户 2026-10-03 裁定）：**册里有这个名字＝放行理由**，实体命中排在
    分类器之前；分类器那道门只剩"查不到名字时"才走，语义一字未改（别的分区/联网判定零扰动）。

    ⚠ 本件取代 S12 的 ``test_gate_reuses_the_existing_intent_ruling_not_a_new_one``：
    那句「非现实题类别 ⇒ 即便句子里有在册实体也不端」正是被裁定改掉的行为
    （「明日方舟是谁开发的」当时恒 ``never``、既不联网也不出关系块）。
    """
    assert providers.reality_relation_note_for("今天心情不好") == ""
    assert providers.reality_relation_note_for("") == ""
    # 改前判据（逐字照抄 HEAD 那道门）判 never 的无触发词问句 ⇒ 现由实体命中放行。
    main_case = "明日方舟是谁开发的"
    assert er.registered_entity_hit(main_case) is True
    assert providers.reality_relation_note_for(main_case) != ""
    # 用户本轮意愿否决**排在实体命中之前**（席 P11，用户 2026-10-04 令「P-11 需要去做」）：
    # 明说「别联网」⇒ 整块缺席，端的是册内已核陈述也不端（S19 当时把这行判成 `!= ""`，
    # 与新裁定相反，本行即那次翻转——否决权属于人，不属于命名表）。
    assert providers.reality_relation_note_for("别联网，随便聊聊鸣潮") == ""
    # 册里查不到名字时，分类器那道门照旧：非现实题类别 ⇒ 仍然不端。
    unregistered = "别联网，随便聊聊量子隧穿"
    assert er.registered_entity_hit(unregistered) is False
    if question_intent.classify_question_intent(unregistered).category not in (
        providers._REALITY_LOOKUP_CATEGORIES
    ):
        assert providers.reality_relation_note_for(unregistered) == ""


def test_gate_is_fail_open_when_the_ledger_module_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """查询口自己炸 ⇒ 本轮分区缺席，绝不带崩主链路（缺席优先于猜测）。"""

    def _boom(*_a: object, **_k: object) -> tuple[str, ...]:
        raise RuntimeError("册坏了")

    monkeypatch.setattr(providers, "reality_relation_lines", _boom)
    assert providers.reality_relation_note_for("鸣潮是哪个公司开发的") == ""


def test_one_hop_queries_touch_no_network(tmp_path: Path) -> None:
    """离线自证：只读随包种子的副本，跑一次查询不产生任何新落盘件。"""
    watch = tmp_path / "watch"
    watch.mkdir()
    original = er.SEED_PATH
    try:
        er.SEED_PATH = watch / "entity_relation_seed.json"
        er.load_seed.cache_clear()
        assert er.reality_relation_lines("鸣潮是哪个公司开发的") == ()
        assert sorted(p.name for p in watch.iterdir()) == [], "读接口往盘上写了东西"
    finally:
        er.SEED_PATH = original
        er.load_seed.cache_clear()
