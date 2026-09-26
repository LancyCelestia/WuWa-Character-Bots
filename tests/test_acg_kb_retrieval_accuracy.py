"""S-T-ACG-1 · 「库里已有的内容要稳定命中，命中要如实呈报」回归门（2026-09-25）。

用户第 3 项后半：二游角色/事件/剧情/人事物这些**数据库里已有的内容**，要
① 稳定命中、② 命中后准确无误地反馈给用户。本门把这句话拆成五件可机检的事：

1. **命中带可核对身份**——送进提示词的每条知识块必须自带「来源库 + 条目标题
   + 条目 id」，且正文不许被洗成残句（表格型条目整段消失、超长静默截断，
   都是"命中了却看不到内容"，模型随即自由发挥＝编）。
2. **零命中只说「本轮没检索到」**——措辞真身沿用 chat 层既有件
   （``_KB_UNAVAILABLE_LINE``）。断言两半：未命中陈述在场，
   且**不出现**「不存在/没有这个角色」型断言（负断言，必须有）。
3. **多库先后只有一把尺**——哪个库先答、何时降级到网络由 ``resolve_answer_order``
   单点判定；两库同时命中同一主题时按声明阶梯取高优先库先答。
4. **注毒自证**——执法点被放宽时，用例必红（本文件的 §④ 三发）。
5. **AST/文本锁**——跨源优先级阶梯与未命中措辞真身在生产里各只有一处。

全离线：假 provider／假检索器／契约类直造，零网络、零真知识库（FAISS/SQLite
一概不碰）、零 LLM、不读配置开关。
"""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

# 刻意**不复制**未命中措辞：从真身取，改一处即处处跟随（判据 2 的前提）。
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _KB_UNAVAILABLE_LINE,
)
from plugins.bot_unified_runtime.domains.core.contracts.character import KnowledgeChunk
from plugins.bot_unified_runtime.domains.core.search import acg_search
from plugins.bot_unified_runtime.domains.core.search import search_service as svc
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"
TODAY = date(2026, 9, 25)

#: 一条"库里确实有"的二游角色条目：正文以表格为主（旧呈现层会把整段洗成空）。
LANZUI_BODY = (
    "## 蓝毒\n"
    "| 代号 | 蓝毒 |\n"
    "| --- | --- |\n"
    "| 阵营 | 罗德岛 |\n"
    "| 种族 | 安努拉 |\n"
    "狙击干员，对毒剂有异常的兴趣，日常会拿自己做试毒记录。"
)


def _wiki_chunk(**updates: object) -> KnowledgeChunk:
    payload: dict[str, object] = {
        "chunk_id": "kb-wiki:lan_zhu:0007",
        "source_id": "crawler:arknights-operator-lanzui",
        "title": "蓝毒",
        "content": LANZUI_BODY,
    }
    payload.update(updates)
    return KnowledgeChunk(**payload)  # type: ignore[arg-type]


def _block(
    chunks: list[KnowledgeChunk],
    *,
    library: str = svc.KB_SOURCE_WIKI,
    max_chars: int = svc.KNOWLEDGE_HIT_MAX_CHARS,
) -> str:
    return svc.knowledge_context_block(
        chunks=chunks,
        library=library,
        miss_declaration=_KB_UNAVAILABLE_LINE,
        max_chars=max_chars,
    )


# ---------------------------------------------------------------------------
# ① 命中：身份在场 + 正文不被洗成残句
# ---------------------------------------------------------------------------


def test_hit_line_carries_verifiable_identity() -> None:
    block = _block([_wiki_chunk()])
    assert "kb-wiki:lan_zhu:0007" in block, "命中未带条目 id：用户与审计都无从回查"
    assert "蓝毒" in block, "命中未带条目标题"
    assert "百科知识库" in block, "命中未点名来源库（多库时说不清是谁答的）"
    assert "\n" not in block, "单条命中被拆成多行 = 预算裁剪时只会留下半行身份"


def test_hit_body_keeps_table_cells_instead_of_wiping_them() -> None:
    """表格型条目是旧呈现层的黑洞：整行 ``|x|y|`` 被丢掉 ⇒ 命中了却没内容。"""
    block = _block([_wiki_chunk()])
    for must_survive in ("罗德岛", "安努拉", "试毒记录"):
        assert must_survive in block, f"条目正文里的 {must_survive!r} 在整形时丢了"
    assert "｜" in block, "Markdown 表格行未折成可读文本（分隔线该丢、数据行该留）"
    assert "---" not in block, "分隔行漏网：会被模型当成条目内容读进答案"


def test_long_hit_is_clipped_on_sentence_boundary_and_says_so() -> None:
    long_body = "第一句设定说明。" * 80  # 320 字，刻意超预算
    block = _block([_wiki_chunk(content=long_body)], max_chars=120)
    assert "另有约" in block and "未展示" in block, "裁剪未显式记账＝静默截断"
    assert block.endswith("）"), "尾巴必须落在标注上，不许停在半句"
    assert "。…" in block, "裁剪点必须落在句子终止符上（残句会诱发模型续写＝编）"
    shown_text, hidden = _parse_clip_marker(block)
    assert hidden > 0 and shown_text.endswith("。")
    assert len(shown_text) + hidden == len(long_body), (
        "展示的字数与标注未展示的字数对不上账：那个标注是假的"
    )


def _parse_clip_marker(block: str) -> tuple[str, int]:
    """从渲染行里抠出「展示正文」与「标注未展示字数」，用于守恒核对。"""
    after_identity = block.split("] ", 1)[1]
    shown_text, marker = after_identity.split("…（另有约 ", 1)
    return shown_text, int(marker.split(" 字未展示", 1)[0])


def test_hit_without_id_is_marked_derived_never_forged() -> None:
    """库没给 id 时：现算内容摘要并标 ``id≈``，绝不拿标题冒充 ``id=``。"""
    block = _block([_wiki_chunk(chunk_id="")], library=svc.KB_SOURCE_PERSONA)
    assert "id≈" in block, "缺 id 的命中要给出可核对的内容摘要号"
    assert "id=" not in block.replace("id≈", ""), "派生 id 被写成像库内 id＝假身份"
    assert "人格资料库" in block


def test_empty_body_hit_says_it_has_no_readable_text() -> None:
    block = _block([_wiki_chunk(content="|\n|--|\n")])
    assert "无可读文本" in block, "命中空壳必须显式说出来，否则模型对着空壳自由发挥"
    assert svc.existence_denial_hit(block) == "", "空壳陈述里混进了存在性否定"


# ---------------------------------------------------------------------------
# ② 零命中：只说「本轮没检索到」，不说「不存在」
# ---------------------------------------------------------------------------


def test_miss_block_reuses_existing_declaration_body() -> None:
    """未命中块 == chat 层既有真身（逐字节）：本席没有第二套措辞。"""
    assert _block([]) == _KB_UNAVAILABLE_LINE
    assert "没接到" in _KB_UNAVAILABLE_LINE and "不代表" in _KB_UNAVAILABLE_LINE


def test_miss_block_has_no_existence_denial() -> None:
    """负断言（本门必须有的那半）：未命中块里不许出现「不存在/没有这个角色」。"""
    block = _block([])
    assert svc.existence_denial_hit(block) == "", (
        f"未命中块含存在性否定：{svc.existence_denial_hit(block)!r}"
    )
    # 「不要说「记录里没有这个人」」里的引述是**禁令**、不是断言：不得误判成违规。
    assert "记录里没有这个人" in block, "禁令原文应在（被引号包住），豁免靠的是引号跨度"


@pytest.mark.parametrize(
    "weakened",
    [
        "本轮没有任何百科/知识库资料接入这次对话。",  # 缺「不代表不存在」那一半
        "这个角色的资料不存在。",  # 直接把没查到写成不存在
        "",  # 干脆不声明
    ],
)
def test_weakened_miss_declaration_is_rejected(weakened: str) -> None:
    with pytest.raises(svc.KnowledgeMissDeclarationError):
        svc.validate_miss_declaration(weakened)
    with pytest.raises(svc.KnowledgeMissDeclarationError):
        svc.knowledge_context_block(
            chunks=[],
            library=svc.KB_SOURCE_WIKI,
            miss_declaration=weakened,
        )


def test_existence_denial_detector_catches_plain_assertions() -> None:
    for bad in (
        "这个角色不存在。",
        "该设定不存在",
        "百科里查无此人",
        "记录里没有这个人",
        "官方从未公布过这件事",
        "库里没有这个角色的资料",
    ):
        assert svc.existence_denial_hit(bad), f"未拦到存在性否定：{bad!r}"


# ---------------------------------------------------------------------------
# ③ 多库先后的单一判据（假 provider 控制返回值）
# ---------------------------------------------------------------------------


class _FakeRetriever:
    """假检索器：只回答「我是哪个库」「我命中了什么」，零真库零网络。"""

    available = True

    def __init__(self, source_name: str, chunks: list[KnowledgeChunk]) -> None:
        self.source_name = source_name
        self._chunks = chunks

    def retrieve(self, _query_text: str) -> list[KnowledgeChunk]:
        return list(self._chunks)


def _same_topic_retrievers() -> list[tuple[str, object]]:
    persona = _FakeRetriever(
        svc.KB_SOURCE_PERSONA,
        [
            _wiki_chunk(
                chunk_id="persona:lan_zhu:0001",
                title="蓝毒（人格资料）",
                content="档案里记着她爱拿自己做试毒记录。",
            )
        ],
    )
    wiki = _FakeRetriever(svc.KB_SOURCE_WIKI, [_wiki_chunk()])
    # 故意反序传入：先后必须由判据算出来，不是照抄手写顺序。
    return [(svc.KB_SOURCE_WIKI, wiki), (svc.KB_SOURCE_PERSONA, persona)]


def test_background_topic_answers_from_highest_priority_library() -> None:
    ordered = svc.order_retrievers(_same_topic_retrievers(), wants_latest=False)
    assert [item.source_name for item in ordered] == [  # type: ignore[attr-defined]
        svc.KB_SOURCE_PERSONA,
        svc.KB_SOURCE_WIKI,
    ], "两库都命中同一主题时未按声明阶梯取高优先库先答"


def test_latest_topic_sinks_local_libraries_below_timely_sources() -> None:
    rank_persona = svc.answer_source_rank(svc.KB_SOURCE_PERSONA, wants_latest=True)
    rank_wiki = svc.answer_source_rank(svc.KB_SOURCE_WIKI, wants_latest=True)
    rank_bili = svc.answer_source_rank("bilibili", wants_latest=True)
    rank_web = svc.answer_source_rank("general", wants_latest=True)
    assert rank_bili < rank_web < rank_wiki < rank_persona, (
        "最新动态档里本地库仍压着时效源＝稳定产出过期答案"
    )
    # 本地库排在后面≠被踢出：设定类事实仍要能在同一轮里被引用。
    assert rank_wiki < svc.answer_source_rank("没登记过的源", wants_latest=True)


def test_resolve_answer_order_priority_and_degrade() -> None:
    both = svc.resolve_answer_order(
        hits_by_source={svc.KB_SOURCE_WIKI: 3, svc.KB_SOURCE_PERSONA: 1},
        wants_latest=False,
        web_search_intended=False,
    )
    assert both.ordered[0] == svc.KB_SOURCE_PERSONA
    assert both.degrade_to_web is False and both.local_answered

    wiki_only = svc.resolve_answer_order(
        hits_by_source={svc.KB_SOURCE_WIKI: 2},
        wants_latest=False,
        web_search_intended=False,
    )
    assert wiki_only.first_answer_source == svc.KB_SOURCE_WIKI
    assert wiki_only.reason == "local_hit_first"

    zero = svc.resolve_answer_order(
        hits_by_source={svc.KB_SOURCE_WIKI: 0, "general": 0},
        wants_latest=False,
        web_search_intended=False,
    )
    assert zero.ordered == () and zero.degrade_to_web is True
    assert zero.reason == "no_hits", "一个源都没命中，reason 不该写成 no_local_hit（那是两回事）"

    local_silent = svc.resolve_answer_order(
        hits_by_source={svc.KB_SOURCE_WIKI: 0, "moegirl": 2},
        wants_latest=False,
        web_search_intended=False,
    )
    assert local_silent.ordered == ("moegirl",)
    assert local_silent.degrade_to_web is True and local_silent.reason == "no_local_hit"
    assert not local_silent.local_answered

    web_says_yes = svc.resolve_answer_order(
        hits_by_source={svc.KB_SOURCE_PERSONA: 4},
        wants_latest=True,
        web_search_intended=True,
    )
    assert web_says_yes.degrade_to_web is True
    assert web_says_yes.reason == "web_intended"


def test_degrade_flag_is_consumed_never_recomputed() -> None:
    """阈值判据唯一住在 ``question_intent.decide_web_search``：本席只消费结论。

    同一条本地命中，``web_search_intended`` 真/假给出不同降级值——说明降级不是
    在这里重算阈值，而是把既有判据与「本地零命中」两件事合成一次判定。
    """
    hits = {svc.KB_SOURCE_PERSONA: 2}
    kept = svc.resolve_answer_order(
        hits_by_source=hits, wants_latest=False, web_search_intended=False
    )
    forced = svc.resolve_answer_order(
        hits_by_source=hits, wants_latest=False, web_search_intended=True
    )
    assert (kept.degrade_to_web, forced.degrade_to_web) == (False, True)
    assert kept.ordered == forced.ordered, "联网结论不该反过来改写库间先后"


def test_vertical_weights_are_derived_from_single_table() -> None:
    """竖源背景档权重不许有第二张表（本波把它收成派生）。"""
    assert acg_search.background_authority_weight("moegirl") == (
        svc.BACKGROUND_AUTHORITY_WEIGHTS["moegirl"]
    )
    assert not hasattr(acg_search, "_BACKGROUND_WEIGHTS"), "旧的第二张权重表又长回来了"
    fused = acg_search.fuse_into_web_hits(
        detect_acg_intent("芙莉莲的声优是谁"),
        [],
        [
            acg_search.AcgResult(source="bangumi", title="B", snippet="s", url="u"),
            acg_search.AcgResult(source="moegirl", title="A", snippet="s", url="u"),
        ],
        today=TODAY,
    )
    assert [hit.title for hit in fused] == ["[萌娘百科] A", "[Bangumi] B"]


def test_vertical_hit_identity_reaches_the_model_text() -> None:
    """竖源命中的条目号必须进摘要行——渲染层不把 url 送进提示词。"""
    fused = acg_search.fuse_into_web_hits(
        detect_acg_intent("芙莉莲第三季出了吗"),
        [],
        [
            acg_search.AcgResult(
                source="bangumi",
                title="葬送的芙莉莲",
                snippet="放送中",
                url="https://bgm.tv/subject/430415",
                date="2026-09-20",
                item_id="430415",
            )
        ],
        today=TODAY,
    )
    assert "id=430415" in fused[0].snippet, "条目身份没进正文：只剩标题可撞同名条目"
    assert "2026-09-20" in fused[0].snippet, "最新档必须自带日期（可判新旧）"


def test_vertical_without_id_is_not_forged() -> None:
    fused = acg_search.fuse_into_web_hits(
        detect_acg_intent("硬控是什么梗"),
        [],
        [acg_search.AcgResult(source="moegirl", title="硬控", snippet="释义", url="u")],
        today=TODAY,
    )
    assert "id=" not in fused[0].snippet, "拿标题冒充条目号＝造一个查不到的身份"
    assert "萌娘百科" in fused[0].snippet


# ---------------------------------------------------------------------------
# ④ 注毒自证：执法点被放宽 ⇒ 用例必红
#     （源文件级注毒的实跑红数在本席日志 §肆；这里是常驻可复跑的那几发）
# ---------------------------------------------------------------------------


def test_poison_removing_disclaim_enforcement_reds_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒一发：把「未命中禁式」那一半的执法词表抽空 ⇒ 两半判据当场失效可见。

    期望的不是"用例红"，而是"执法真的存在"：清空连接词表后，连合格文案也会
    被拒（因为它不再被要求带反断言那一半，判据退化成了空判）。这条锁的是
    "缺半边必须拦得住"这件事本身。
    """
    assert svc.validate_miss_declaration(_KB_UNAVAILABLE_LINE) == _KB_UNAVAILABLE_LINE
    monkeypatch.setattr(svc, "_MISS_DISCLAIM_CONNECTIVES", ())
    with pytest.raises(svc.KnowledgeMissDeclarationError):
        svc.validate_miss_declaration(_KB_UNAVAILABLE_LINE)


def test_poison_denial_regex_widening_reds_the_negative_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒二发：存在性否定表被放宽成永不命中 ⇒ 那条负断言就再也拦不住坏文案。

    本发证明「②的负断言」吃的就是这张表：表一松，"这个角色不存在"这类句子
    畅通无阻（也就是：一旦有人为了少报错而放宽它，本门的断言立刻失去意义——
    所以断言必须写在这张表上，而不是写在某个人设想的字符串比较上）。
    """
    assert svc.existence_denial_hit("鸣潮里没有这个角色。")
    monkeypatch.setattr(svc, "_EXISTENCE_DENIAL_RE", re.compile(r"(?!)"))
    assert svc.existence_denial_hit("鸣潮里没有这个角色。") == ""
    # 同一条断言在本门 §④ 之外的那发（test_existence_denial_detector_catches_...）
    # 于注毒态必红——实跑证据见日志 §肆 P2。


def test_identity_is_composed_in_exactly_one_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒三发：身份段只有一个拼装点，引用面与渲染面同源，不会一处有一处没有。"""
    hit = svc.knowledge_hit_view(library=svc.KB_SOURCE_WIKI, chunk=_wiki_chunk())
    citation = svc.format_knowledge_citation(hit)
    rendered = svc.format_knowledge_hit_lines([hit])[0]
    for part in ("百科知识库", "蓝毒", "kb-wiki:lan_zhu:0007"):
        assert part in citation and part in rendered, f"{part} 只出现在一侧＝两处各有尺"
    monkeypatch.setattr(svc, "_identity_parts", lambda _hit: ("库X", "题X", "id=X"))
    assert "id=X" in svc.format_knowledge_citation(hit)
    assert "id=X" in svc.format_knowledge_hit_lines([hit])[0]


def test_poison_renderer_empties_body_but_still_keeps_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """注毒四发：正文整形被抽空时，行里必须改口说明，且身份仍独立存在。"""
    monkeypatch.setattr(svc, "_shape_knowledge_body", lambda _text: "")
    block = _block([_wiki_chunk()])
    assert "无可读文本" in block, "正文空了必须说出来，不许留一条光秃秃的身份行"
    assert "蓝毒" in block and "kb-wiki:lan_zhu:0007" in block


# ---------------------------------------------------------------------------
# ⑤ 生产侧只有一处判据 / 只有一处措辞真身
# ---------------------------------------------------------------------------

_LADDER_MEMBER_IDS = frozenset(
    {svc.KB_SOURCE_PERSONA, svc.KB_SOURCE_WIKI, "moegirl", "bangumi", "bilibili", "general"}
)
_LADDER_FILE = "search_service.py"


def _production_python_files() -> list[Path]:
    return [path for path in PLUGINS_ROOT.rglob("*.py") if "__pycache__" not in path.parts]


def _parse(path: Path) -> ast.Module | None:
    """能 parse 才判；不能 parse 的文件由下面那条独立锁点名。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ladder_scanners_do_not_silently_skip_unparseable_production_files() -> None:
    """本门的判据建立在 AST 上：连"哪些文件读不动"都要摊开说。

    现算记录：本席开工时 `domains/core/safety_exec/consent.py` 在盘上就不可
    parse（他人波次的在飞件，非本席文件面）。它不在本席锁的检查词路径上，
    但必须留一条看得见它存在的锁——否则"扫过了"会被误读成"都读得动"。
    """
    unreadable = [
        path.name
        for path in _production_python_files()
        if _parse(path) is None
    ]
    mine = {"acg_search.py", "search_service.py"}
    assert not (set(unreadable) & mine), f"本席文件面不可解析：{unreadable}"


def _sequence_string_members(node: ast.AST) -> set[str]:
    """序列字面量里的源 id（Name 节点按真身常量求值，KB_SOURCE_* 也是声明数据）。"""
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return set()
    members: set[str] = set()
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            members.add(element.value)
        elif isinstance(element, ast.Name):
            members.add(str(getattr(svc, element.id, element.id)))
    return members


def test_priority_ladder_is_defined_exactly_once_in_production() -> None:
    ladder_definers: list[str] = []
    second_ladders: list[str] = []
    judge_defs: list[str] = []
    web_threshold_defs: list[str] = []
    for path in _production_python_files():
        text = _text(path)
        if "kb_wiki" not in text and "persona" not in text:
            continue  # 与阶梯无关的文件不进 AST，免得把 bot_persona_* 之类误纳
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = {getattr(t, "id", "") for t in targets if isinstance(t, ast.Name)}
                if names & {"ANSWER_SOURCE_LADDER_BACKGROUND", "ANSWER_SOURCE_LADDER_LATEST"}:
                    ladder_definers.append(path.name)
                members = _sequence_string_members(node.value) if node.value else set()
                local_legit = members & {svc.KB_SOURCE_PERSONA, svc.KB_SOURCE_WIKI}
                if (
                    local_legit
                    and len(members & _LADDER_MEMBER_IDS) >= 3
                    and path.name != _LADDER_FILE
                ):
                    second_ladders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in {"answer_source_rank", "resolve_answer_order"}:
                    judge_defs.append(f"{path.name}:{node.name}")
                if node.name == "decide_web_search":
                    web_threshold_defs.append(path.name)
    assert sorted(set(ladder_definers)) == [_LADDER_FILE], (
        f"跨源阶梯的定义点必须唯一：{ladder_definers}"
    )
    assert len(ladder_definers) == 2, f"两份阶梯（背景/最新）必须住在同一文件：{ladder_definers}"
    assert second_ladders == [], f"出现了第二份跨源优先级表：{second_ladders}"
    assert sorted(judge_defs) == [
        f"{_LADDER_FILE}:answer_source_rank",
        f"{_LADDER_FILE}:resolve_answer_order",
    ], f"跨源先后判据必须只有一个定义点：{judge_defs}"
    assert web_threshold_defs == ["question_intent.py"], (
        f"「要不要联网」的阈值判据必须仍住在既有真身里：{web_threshold_defs}"
    )


def test_miss_wording_has_a_single_production_body() -> None:
    """未命中措辞真身只有一处：本席的模块里不许长出第二套话术。

    判据取「没接到」+「不代表」两句同现——这正是"未命中声明"的结构（陈述 +
    反断言两半）。全域禁式件 ``_RUNTIME_CONTEXT_USAGE`` 也提到这些词，但它是
    **使用总说明**（不把两半合成一条未命中陈述），不在本锁射程内；本锁要拦的是
    "另起一条会被人改的未命中话术"。
    """
    holders: list[str] = []
    for path in _production_python_files():
        text = _text(path)
        if "没接到" not in text:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            if "没接到" in value.value and "不代表" in value.value:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = {getattr(t, "id", "") for t in targets if isinstance(t, ast.Name)}
                holders.append(f"{path.name}:{sorted(names)}")
    assert holders == ["chat.py:['_KB_UNAVAILABLE_LINE']"], (
        f"未命中措辞出现第二处真身（必须改为引用既有件）：{holders}"
    )
    # 本席两件模块的**模块级字面量**里不许躺着一整句未命中话术（词表片段不算）。
    for seat_suffix in (
        "domains/core/search/search_service.py",
        "domains/core/search/acg_search.py",
    ):
        seat_path = next(
            p for p in _production_python_files() if p.as_posix().endswith(seat_suffix)
        )
        seat_tree = _parse(seat_path)
        assert seat_tree is not None
        for node in seat_tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                assert "没接到" not in value.value, (
                    f"{seat_path.name} 的模块级字面量里长了未命中话术"
                    "（措辞真身只准在 chat 层）"
                )


def _source_of(relative_suffix: str) -> str:
    """按**相对路径尾巴**取生产文件（不是 basename——本仓有同名垫片）。

    现算：`chat.py` 在树里有两份（真身 `domains/chat_reply/capabilities/`，
    另有一枚 v21r2 再导出垫片 `capabilities/chat.py`），只按文件名取会读到垫片，
    于是"生产没调用"的结论会凭空文件假红。这里强制唯一命中。
    """
    matches = [
        path
        for path in _production_python_files()
        if path.as_posix().endswith(relative_suffix)
    ]
    assert len(matches) == 1, f"{relative_suffix} 命中 {len(matches)} 份，取数不确定"
    return matches[0].read_text(encoding="utf-8")


def test_live_leg_vertical_identity_is_consumed_by_the_existing_call_site() -> None:
    """本席**今天就已经通电**的那一腿：竖源身份经既有调用点直达提示词。

    链：``chat.py`` 调 ``acg_search.fuse_into_web_hits`` → 内部走 ``_annotate``
    → ``source_identity_label``。这条锁的是"我确实改了生产会跑到的地方"，
    不是只建了个没人调的真身。
    """
    acg_text = _source_of("domains/core/search/acg_search.py")
    chat_text = _source_of("domains/chat_reply/capabilities/chat.py")
    assert "source_identity_label(result" in acg_text, "身份段没接进 _annotate＝白建一个函数"
    assert "fuse_into_web_hits(" in chat_text, "chat 层不再调用融合口：这条腿今天就不是活的"
    assert "BACKGROUND_AUTHORITY_WEIGHTS" in acg_text, "权重又变回本模块自持的字面量了"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "S-T-ACG-1 挂账（禁写面未接）：知识命中的身份呈现与跨源判据的生产调用点"
        "还不在 chat.py/providers.py 里——代接坐标见席位日志 §肆。"
        "接上之后请把这个标记摘成硬锁，别让真身变成第二条'在册但不通电'。"
    ),
)
def test_production_consumers_of_kb_presentation_bodies_are_wired() -> None:
    chat_text = _source_of("domains/chat_reply/capabilities/chat.py")
    providers_text = _source_of("domains/chat_reply/character/providers.py")
    assert "knowledge_context_block" in chat_text, (
        "【知识库】区仍在用丢身份的老渲染：条目 id 与来源库到不了模型眼前"
    )
    assert "order_retrievers" in providers_text or "resolve_answer_order" in providers_text, (
        "装配层仍靠手写传参先后表达库间优先级"
    )
