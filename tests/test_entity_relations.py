"""实体关系册（三元组种子）的读接口锁、门票腿、消毒腿与图谱接线锁（S3 席）。

四件常驻判据，全部零 IO 之外的副作用（种子只读、图谱只读连接、注毒只喂合成数据）：

① **一跳可查**——`守岸人 → belongs_to_work → developed_by` 必须给出「鸣潮 → 广州库洛科技有限公司」；
   六款点名二游各自 作品→研发（→发行）都可反查。
② **禁第二真身字面锁**——生产件 `entity_relations.py` 里不得出现任何种子实体名（AST 判，
   docstring 除外）：数据只许住在 JSON 里，代码一旦抄了名字，改数据就漏改代码。
③ **门票**——未知关系词/未知类别一律拒收并进留痕；图谱侧 `add_edge` 的第二道门票同批验牙。
④ **消毒**——`sanitize_label` 幂等，且控制字符/零宽/尖括号/markdown 链接/表格字符都剥得掉；
   图谱 payload 里出现不了它们（这条是「报告本身变成新载体」那类病的预防，规则 11）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.bot_unified_runtime.control_plane.webui_memory_graph import (
    GRAPH_EDGE_KINDS,
    MemoryGraphService,
)
from plugins.bot_unified_runtime.domains.core.search import (
    entity_relations as er,
)

MODULE_PY = ROOT / "plugins/bot_unified_runtime/domains/core/search/entity_relations.py"
SEED_JSON = ROOT / "plugins/bot_unified_runtime/domains/core/search/entity_relation_seed.json"

SIX_WORKS: tuple[str, ...] = (
    "鸣潮",
    "崩坏：星穹铁道",
    "重返未来：1999",
    "战双帕弥什",
    "明日方舟",
    "明日方舟：终末地",
)


# ---------------------------------------------------------------------------
# ① 一跳 / 一链
# ---------------------------------------------------------------------------


def test_seed_loads_and_is_clean() -> None:
    assert er.load_seed().ok is True, er.seed_problems()
    assert er.seed_problems() == ()


def test_one_hop_character_to_work_to_developer() -> None:
    """简报点名的验收：守岸人 → 作品 → 开发商。"""
    assert er.objects_of("守岸人", er.RELATION_BELONGS_TO_WORK) == ("鸣潮",)
    chain = er.resolve_chain(
        "守岸人", (er.RELATION_BELONGS_TO_WORK, er.RELATION_DEVELOPED_BY)
    )
    assert chain == ("鸣潮", "广州库洛科技有限公司"), chain


@pytest.mark.parametrize("work", SIX_WORKS)
def test_each_named_game_resolves_to_a_developer(work: str) -> None:
    developers = er.objects_of(work, er.RELATION_DEVELOPED_BY)
    assert developers, f"{work} 反查不到研发方"
    for developer in developers:
        record = er.entity(developer)
        assert record is not None and record.kind == "company", developer


def test_alias_lookup_is_exact_and_never_fuzzy() -> None:
    assert er.entity("BW") is not None
    assert er.entity("终末地") is not None
    # 逐字等值：近似名不许命中（"明日方舟：" 这种半截名字必须拿 None，不许猜）。
    assert er.entity("明日方舟：终") is None
    assert er.entity("") is None


def test_missing_hop_returns_empty_not_a_guess() -> None:
    """跳转不动 ⇒ 空元组（诚实缺席），绝不半条链蒙成结果。"""
    assert er.resolve_chain("CICF", (er.RELATION_LOCATED_IN, er.RELATION_DEVELOPED_BY)) == ()
    assert er.resolve_chain("守岸人", ()) == ()
    assert er.resolve_chain("不存在的人", (er.RELATION_BELONGS_TO_WORK,)) == ()


def test_expo_entities_exist_and_carry_a_verified_flag() -> None:
    for name in ("BilibiliWorld", "COMICUP", "CICF", "ComiDay", "HKACG"):
        record = er.entity(name)
        assert record is not None and record.kind == "expo", name
        assert isinstance(record.verified, bool), name
    # 简报点名的六个不确定实体必须**在场且标待核**（缺席或冒充已确认都算红）。
    for name in ("CQ", "世界线", "梦乡"):
        record = er.entity(name)
        assert record is not None, f"{name} 连条目都没登记 ⇒ 消费方无法区分'没这个词'与'没核实'"
        assert record.verified is False, f"{name} 未核实却标了 verified=True"


def test_unverified_records_are_named_not_hidden() -> None:
    pending = er.unverified_records()
    assert set(pending) == {"entities", "relations"}
    # 「待核」必须真在数（否则整册假装全核实过）。
    assert pending["relations"], "一条待核关系都没有 ⇒ 册在冒充已确认"
    assert all(not triple.verified for triple in er.load_seed().relations
               if f"{triple.subject} {triple.relation} {triple.object}" in pending["relations"])


# ---------------------------------------------------------------------------
# ② 禁第二真身：代码里不许抄实体名
# ---------------------------------------------------------------------------


def _non_docstring_constants(source: str) -> list[str]:
    tree = ast.parse(source)
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstring_nodes.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]


def test_production_module_hardcodes_no_entity_names() -> None:
    """数据只住 JSON：本件出现任何在册实体名/关系端点＝抄了第二真身。"""
    names = {record.name for record in er.load_seed().entities}
    aliases = {alias for record in er.load_seed().entities for alias in record.aliases}
    banned = {name for name in (names | aliases) if len(name) >= 3}  # 两字母短名会撞普通标识符
    offenders = [
        (constant, sorted(name for name in banned if name in constant))
        for constant in _non_docstring_constants(MODULE_PY.read_text(encoding="utf-8"))
        if any(name in constant for name in banned)
    ]
    assert not offenders, f"生产件里抄了实体名（改数据会漏改代码）：{offenders}"


def test_seed_is_the_only_source_of_truth() -> None:
    """种子文件与读接口逐字节同源：解析器没偷加、没偷删任何条目。"""
    payload = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    assert len(payload["entities"]) == len(er.load_seed().entities)
    assert len(payload["relations"]) == len(er.load_seed().relations)


# ---------------------------------------------------------------------------
# ③ 门票
# ---------------------------------------------------------------------------


def test_relation_types_are_the_ticket() -> None:
    assert er.RELATION_TYPES == frozenset(
        {"belongs_to_work", "developed_by", "published_by", "located_in"}
    )
    assert er.is_registered_relation("developed_by") is True
    assert er.is_registered_relation("fought_with") is False
    assert er.is_registered_relation("") is False


def test_graph_edge_kinds_cover_both_faces() -> None:
    """图谱门票 ⊇ 行为侧五枚 ∪ 关系册四枚（少一枚就是某条腿的边被静默丢掉）。"""
    for kind in er.RELATION_TYPES:
        assert kind in GRAPH_EDGE_KINDS, kind
    for kind in ("speaks_in", "hosts", "about", "learned_rule", "nickname"):
        assert kind in GRAPH_EDGE_KINDS, kind


def _write_sandbox_seed(tmp_path: Path, payload: dict[str, object]) -> Path:
    copy = tmp_path / "seed_poison.json"
    copy.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    er.load_seed.cache_clear()
    return copy


@pytest.fixture()
def _restore_seed_cache() -> object:
    yield
    er.load_seed.cache_clear()


def test_unknown_relation_word_is_refused_and_named(
    tmp_path: Path, _restore_seed_cache: None
) -> None:
    """注毒 1：塞一枚未在册关系词 ⇒ 不落 payload **且**点名（恒空即恒绿的反面）。"""
    payload = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    payload["relations"] = [
        *payload["relations"],
        {"subject": "鸣潮", "relation": "fought_with", "object": "明日方舟", "verified": True},
    ]
    copy = _write_sandbox_seed(tmp_path, payload)
    seed = er.load_seed(str(copy))
    assert seed.ok is False, "未在册关系词居然带着问题过了自检"
    assert any("fought_with" in problem for problem in seed.errors), seed.errors
    assert all(triple.relation != "fought_with" for triple in seed.relations)
    assert not any(edge[2] == "fought_with" for edge in er.graph_edges(str(copy)))


def test_unknown_entity_kind_is_refused(tmp_path: Path, _restore_seed_cache: None) -> None:
    """注毒 2：类别不在门票内 ⇒ 点名并丢弃（不接受自由文本类别）。"""
    payload = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    payload["entities"] = [
        *payload["entities"],
        {"name": "注毒实体", "kind": "whatever", "verified": True, "note": ""},
    ]
    copy = _write_sandbox_seed(tmp_path, payload)
    seed = er.load_seed(str(copy))
    assert seed.ok is False
    assert any("kind=" in problem and "门票" in problem for problem in seed.errors), seed.errors
    assert er.entity("注毒实体", str(copy)) is None


def test_dangling_endpoint_is_refused(tmp_path: Path, _restore_seed_cache: None) -> None:
    """注毒 3：边的端点没有实体条目 ⇒ 红（防"边挂在一个不存在的名字上"）。"""
    payload = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    payload["relations"] = [
        *payload["relations"],
        {"subject": "鸣潮", "relation": "developed_by", "object": "没登记的公司", "verified": True},
    ]
    copy = _write_sandbox_seed(tmp_path, payload)
    seed = er.load_seed(str(copy))
    assert seed.ok is False
    assert any("端点没有实体条目" in problem for problem in seed.errors), seed.errors


# ---------------------------------------------------------------------------
# ④ 消毒
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("守岸人", "守岸人"),
        ("  鸣潮  ", "鸣潮"),
        ("鸣\n潮", "鸣潮"),  # 控制字符直接剥掉（不补空格：实体名里换行就是脏数据）
        ("库洛\u200b科技", "库洛科技"),  # 零宽（U+200B）
        ("<script>alert(1)</script>", "alert(1)"),
        ("[鸣潮](https://example.invalid/x)", ""),
        ("![图](http://e.invalid)", ""),
        ("a|b`c", "a b c"),
        (" 行", "行"),
    ],
)
def test_sanitize_label_strips_dangerous_shapes(raw: str, expected: str) -> None:
    assert er.sanitize_label(raw) == expected


def test_sanitize_label_is_idempotent_and_length_capped() -> None:
    for value in ("鸣潮", "<b>x</b>", "a" * 200, "\u200b"):
        once = er.sanitize_label(value)
        assert er.sanitize_label(once) == once, "消毒不幂等 ⇒ 二次消费会翻出原文"
    assert len(er.sanitize_label("x" * 500)) <= er.MAX_LABEL_CHARS


def test_broken_seed_fails_open_to_empty_not_a_crash(
    tmp_path: Path, _restore_seed_cache: None
) -> None:
    """种子坏/缺席 ⇒ 空册 + 原因，不抛（诚实缺席，链路零破坏）。"""
    missing = tmp_path / "not_here.json"
    seed = er.load_seed(str(missing))
    assert seed.ok is False and seed.entities == () and seed.relations == ()
    assert seed.errors and "种子读不出" in seed.errors[0]
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert er.load_seed(str(broken)).ok is False
    assert er.graph_edges(str(broken)) == ()
    assert er.resolve_chain("守岸人", (er.RELATION_BELONGS_TO_WORK,), str(broken)) == ()


# ---------------------------------------------------------------------------
# ⑤ 图谱接线：缺省零变化 + 开关一开就有边 + 门票/消毒真咬得住
# ---------------------------------------------------------------------------


def _service(tmp_path: Path) -> MemoryGraphService:
    return MemoryGraphService(
        history_db_path=str(tmp_path / "absent_history.sqlite3"),
        memory_db_path=str(tmp_path / "absent_memory.sqlite3"),
        quirks_db_path=str(tmp_path / "absent_quirks.sqlite3"),
        affinity_db_path=str(tmp_path / "absent_affinity.sqlite3"),
    )


def test_default_payload_shape_is_untouched(tmp_path: Path) -> None:
    """缺省关 ⇒ payload 键集与四源读数逐字节等于改前（既有 12 节点/9 边断言零破坏的依据）。"""
    data = _service(tmp_path).graph(window="24h")["data"]
    assert set(data) == {
        "window",
        "max_nodes",
        "truncated",
        "nodes_total",
        "stats",
        "nodes",
        "edges",
        "sources",
    }
    assert set(data["sources"]) == {"history", "memory", "quirks", "affinity"}
    assert not any(str(node["id"]).startswith("entity:") for node in data["nodes"])
    assert all(edge["kind"] not in er.RELATION_TYPES for edge in data["edges"])


def test_entity_leg_opt_in_adds_nodes_and_four_edge_kinds(tmp_path: Path) -> None:
    result = _service(tmp_path).graph(window="24h", include_entities=True)
    data = result["data"]
    assert data["sources"]["entities"] == "ok", data["sources"]
    assert result["status"] == "ok", "库全缺席时实体册在场 ⇒ 不该报 all_sources_missing"
    kinds = {edge["kind"] for edge in data["edges"]}
    assert kinds >= er.RELATION_TYPES, kinds
    ids = {node["id"] for node in data["nodes"]}
    assert "entity:守岸人" in ids and "entity:广州库洛科技有限公司" in ids
    # 已核实边 weight=2、待核边 weight=1（降权不是藏起来）。
    verified_weights = {edge["weight"] for edge in data["edges"] if edge["kind"] in er.RELATION_TYPES}
    assert verified_weights == {1, 2}, verified_weights
    assert data["entities"]["unverified_relations"] > 0
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_include_entities_coerces_non_bool_to_off(tmp_path: Path) -> None:
    """开关只认严格 True（fail-closed）：任何别的形状都不长出新格。"""
    for value in ("true", 1, None, object()):
        data = _service(tmp_path).graph(window="24h", include_entities=value)["data"]  # type: ignore[arg-type]
        assert "entities" not in data, repr(value)
        assert set(data["sources"]) == {"history", "memory", "quirks", "affinity"}


def test_graph_refuses_edge_kinds_outside_the_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒 4（第二道门票）：册侧漏网的未知关系词，图谱侧必须拒收并留痕。"""
    module = "plugins.bot_unified_runtime.control_plane.webui_memory_graph"
    monkeypatch.setattr(
        f"{module}._entity_graph_edges",
        lambda *a, **kw: (("鸣潮", "明日方舟", "fought_with", 2),),
    )
    data = _service(tmp_path).graph(window="24h", include_entities=True)["data"]
    assert all(edge["kind"] != "fought_with" for edge in data["edges"]), "门票被旁路 ⇒ 自由文本边类型进图"
    assert data["entities"]["refused_edge_kinds"] == ["fought_with"], data["entities"]


def test_graph_sanitizes_entity_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒 5（消毒腿）：册侧塞带标签/零宽的边端点 ⇒ payload 里必须看不到它们。"""
    module = "plugins.bot_unified_runtime.control_plane.webui_memory_graph"
    monkeypatch.setattr(
        f"{module}._entity_graph_edges",
        lambda *a, **kw: (("鸣\u200b潮", "<script>库洛</script>", er.RELATION_DEVELOPED_BY, 2),),
    )
    data = _service(tmp_path).graph(window="24h", include_entities=True)["data"]
    blob = json.dumps(data, ensure_ascii=False)
    assert "<script>" not in blob and "\u200b" not in blob, "消毒腿旁路 ⇒ 图谱里长出可执行形态"
