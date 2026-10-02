"""结构化实体关系册（最小三元组，2026-10-02 现实知识面波 S3 席）。

## 为什么需要它
全仓此前**没有任何实体间关系**：图谱边只有 ``hosts/about/learned_rule/nickname``
（``control_plane/webui_memory_graph.py``），``character/relationships.py`` 管的是
人际关系而非实体关系。于是「守岸人出自哪部作品、那部作品是谁做的」只能靠模型背诵
或联网——而 wiki 语料的现实世界条目为 0，联网回来的又是二手材料。本册补的是
**一跳可查、可审计、离线**那一格。

## 四条硬口径（动本件前先读）
1. **零图数据库依赖**：种子是一份随包 JSON（``entity_relation_seed.json``＝唯一真身），
   读接口是纯函数 + 进程内缓存。不引 networkx/neo4j、不建 SQLite 表、不写运行数据。
   要扩数据 ⇒ 改那份 JSON，不改本件（本件里出现任何具体实体名即违反纪律，
   由 ``tests/test_entity_relations.py`` 的字面锁执法）。
2. ``verified`` 是**每条边/每个实体自带的字段**，不是可选注释：``false`` ＝「按公开资料
   登记但未交叉核实」，消费方必须带着这个状态出去（``unverified_records()`` 供审计面，
   图谱侧按它降权）。**绝不把待核当已确认**——与「非上市公司结构性无价格」同一族红线。
3. **加边集必须同批补门票与消毒**（台账 #67★「给判定行加字段要同批补门票」的同型教训）：
   门票＝``RELATION_TYPES``/``ENTITY_KINDS``（未知关系词与未知类别一律拒收，不落 payload）；
   消毒＝``sanitize_label()``（剥控制字符/零宽/尖括号/markdown 链接/表格字符、限长、单行）。
   两腿都由 ``tests/test_entity_relations.py`` 注毒自证。
4. **缺席即缺席**：种子读不到/形状坏 ⇒ 空册 + WARNING 留痕，不抛、不编造
   （与卡片渲染失败回落纯文本、契约零破坏同一口径）。

## 与相邻真身的分工
- 「这句是不是二游/展会题」＝ ``search_intent.ACG_DOMAIN_TERMS``；本件不判意图。
- 「该不该联网」＝ ``question_intent.classify_question_intent``；本件不参与决策档。
- 「图谱有哪些节点/边」＝ ``control_plane/webui_memory_graph.py``（本件只递边与标签）。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ENTITY_KINDS",
    "MAX_LABEL_CHARS",
    "RELATION_BELONGS_TO_WORK",
    "RELATION_DEVELOPED_BY",
    "RELATION_LOCATED_IN",
    "RELATION_PUBLISHED_BY",
    "RELATION_TYPES",
    "SEED_FILENAME",
    "SEED_PATH",
    "EntityRecord",
    "EntitySeed",
    "SanitizedEntitySeedError",
    "entities",
    "entity",
    "graph_edges",
    "graph_nodes",
    "is_registered_relation",
    "label_of",
    "load_seed",
    "objects_of",
    "one_hop",
    "relation_edges",
    "resolve_chain",
    "sanitize_label",
    "seed_problems",
    "unverified_prefix",
    "unverified_records",
]

#: 种子文件名与路径（随包资产，真身就是这个文件本身）。
SEED_FILENAME = "entity_relation_seed.json"
SEED_PATH = Path(__file__).with_name(SEED_FILENAME)

#: 关系词**门票**：不在册的关系一律拒收（加新关系必须同批改这张表 + 补消毒 + 补锁）。
RELATION_BELONGS_TO_WORK = "belongs_to_work"
RELATION_DEVELOPED_BY = "developed_by"
RELATION_PUBLISHED_BY = "published_by"
RELATION_LOCATED_IN = "located_in"
RELATION_TYPES: frozenset[str] = frozenset(
    {
        RELATION_BELONGS_TO_WORK,  # 角色 → 作品
        RELATION_DEVELOPED_BY,     # 作品 → 研发方；展会语境＝主办方
        RELATION_PUBLISHED_BY,     # 作品 → 发行方
        RELATION_LOCATED_IN,       # 公司/展会 → 城市
    }
)

#: 实体类别门票（图谱与审计按它决定节点形状，不接受自由文本）。
ENTITY_KINDS: frozenset[str] = frozenset({"character", "work", "company", "expo", "city"})

#: 单册上限：超过即视为数据事故（种子被整片塞满会拖慢每一次图谱装配）。
MAX_ENTITIES = 400
MAX_RELATIONS = 800
#: 标签上限（与 ``webui_memory_graph._LABEL_MAX_CHARS`` 的 80 分文：那里管记忆正文，
#: 这里只管实体名——实体名本该短，超上限就是脏数据）。
MAX_LABEL_CHARS = 60

_UNVERIFIED_PREFIX = "待核｜"

# 消毒面：控制字符（含零宽，台账 #11 的 U+F02A 一类幻影字符）、尖括号（防实体名被写成
# 标签）、markdown 链接/图片形态（防二手资料的链接尾巴混进标签）、竖线与反引号
# （防出卡时撑破表格与代码段）。
_CONTROL_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028\u2029\ufeff]")
_ANGLE_RE = re.compile(r"<[^>]{0,80}>?")
_MD_LINK_RE = re.compile(r"!?\[[^\]]{0,80}\]\([^)]{0,200}\)")
_TABLE_CHARS_RE = re.compile(r"[`|]+")
_WHITESPACE_RE = re.compile(r"\s{2,}")


class SanitizedEntitySeedError(ValueError):
    """种子形状不合法（仅供显式校验口使用；读接口本身 fail-open 到空册，不抛）。"""


@dataclass(frozen=True)
class EntityRecord:
    """一个实体条目（名称/类别/别名/核实状态）。"""

    name: str
    kind: str
    aliases: tuple[str, ...] = ()
    verified: bool = True
    note: str = ""


@dataclass(frozen=True)
class RelationTriple:
    """一条有向关系：subject --relation--> object。"""

    subject: str
    relation: str
    object: str
    verified: bool = True
    note: str = ""

    def as_edge(self) -> tuple[str, str, str]:
        return (self.subject, self.relation, self.object)


@dataclass(frozen=True)
class EntitySeed:
    """装载结果（``ok`` 为假时两表为空——诚实缺席，不是「查不到所以编一条」）。"""

    entities: tuple[EntityRecord, ...] = ()
    relations: tuple[RelationTriple, ...] = ()
    ok: bool = False
    errors: tuple[str, ...] = ()

    def names(self) -> frozenset[str]:
        return frozenset(record.name for record in self.entities)

    def by_name(self) -> dict[str, EntityRecord]:
        return {record.name: record for record in self.entities}

    def alias_index(self) -> dict[str, str]:
        """别名 → 正名（本件唯一的取名口，别在外面再拼一张）。"""
        index: dict[str, str] = {}
        for record in self.entities:
            for alias in (record.name, *record.aliases):
                key = _normalize(alias)
                if key and key not in index:
                    index[key] = record.name
        return index


def _normalize(value: object) -> str:
    return str(value or "").strip()


def sanitize_label(value: object) -> str:
    """实体名/标签的唯一消毒口：剥控制字符与标签形态、限长、压成单行。

    纯函数、零 IO。任何进图谱 payload、卡片或提示词的实体名都必须过它——种子今天
    是本席手写的在册数据，但它一旦可被别处（联网结果、词条标题）复用，「二手数据」
    的纪律就立刻生效（规则 11 / ATKLLM-1 同源）。
    """
    text = _CONTROL_RE.sub("", _normalize(value))
    text = _MD_LINK_RE.sub("", text)
    text = _ANGLE_RE.sub("", text)
    text = _TABLE_CHARS_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > MAX_LABEL_CHARS:
        text = text[:MAX_LABEL_CHARS].rstrip()
    return text


def is_registered_relation(value: object) -> bool:
    """门票判定：这个词在册吗？未知关系词绝不进 payload，也不回落成自由文本。"""
    return _normalize(value) in RELATION_TYPES


def _valid_label(value: object) -> bool:
    text = _normalize(value)
    return bool(text) and text == sanitize_label(text) and len(text) <= MAX_LABEL_CHARS


def _parse_entities(raw: Iterable[Any]) -> tuple[list[EntityRecord], list[str]]:
    records: list[EntityRecord] = []
    problems: list[str] = []
    for item in raw or ():
        if not isinstance(item, dict):
            problems.append("entities 元素不是对象")
            continue
        if not _valid_label(item.get("name")):
            problems.append(f"实体名不合法或含待消毒形态（原文不回显）：{type(item.get('name'))}")
            continue
        name = sanitize_label(item.get("name"))
        kind = _normalize(item.get("kind"))
        if kind not in ENTITY_KINDS:
            problems.append(f"实体 {name!r} 的 kind={kind!r} 不在 ENTITY_KINDS 门票内")
            continue
        aliases = tuple(
            dict.fromkeys(
                alias
                for alias in (sanitize_label(a) for a in (item.get("aliases") or ()))
                if alias and alias != name
            )
        )
        records.append(
            EntityRecord(
                name=name,
                kind=kind,
                aliases=aliases,
                verified=bool(item.get("verified", False)),
                note=sanitize_label(item.get("note")),
            )
        )
    return records, problems


def _parse_relations(raw: Iterable[Any], known: frozenset[str]) -> tuple[list[RelationTriple], list[str]]:
    triples: list[RelationTriple] = []
    problems: list[str] = []
    for item in raw or ():
        if not isinstance(item, dict):
            problems.append("relations 元素不是对象")
            continue
        subject = sanitize_label(item.get("subject"))
        relation = _normalize(item.get("relation"))
        target = sanitize_label(item.get("object"))
        if relation not in RELATION_TYPES:
            problems.append(f"关系词 {relation!r} 不在 RELATION_TYPES 门票内（同批补门票才许进）")
            continue
        if not (_valid_label(subject) and _valid_label(target)):
            problems.append(f"三元组端点不合法：{subject!r} -> {target!r}")
            continue
        missing = [name for name in (subject, target) if name not in known]
        if missing:
            problems.append(f"三元组端点没有实体条目：{missing}")
            continue
        triples.append(
            RelationTriple(
                subject=subject,
                relation=relation,
                object=target,
                verified=bool(item.get("verified", False)),
                note=sanitize_label(item.get("note")),
            )
        )
    return triples, problems


def _read_seed(path: Path) -> EntitySeed:
    """读一份种子并过门票；任何一步失败 ⇒ 空册 + 原因留在 ``errors``（绝不抛给链路）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("实体关系种子读不出（%s），按缺席处理", type(exc).__name__)
        return EntitySeed(ok=False, errors=(f"种子读不出：{type(exc).__name__}",))
    if not isinstance(payload, dict):
        return EntitySeed(ok=False, errors=("种子顶层不是对象",))
    entities, entity_problems = _parse_entities(payload.get("entities") or ())
    relations, relation_problems = _parse_relations(
        payload.get("relations") or (), frozenset(record.name for record in entities)
    )
    problems = [*entity_problems, *relation_problems]
    if len(entities) > MAX_ENTITIES or len(relations) > MAX_RELATIONS:
        problems.append("种子规模超过册上限（数据事故，按空册处理而不是硬吃）")
    if problems:
        # 逐条留痕；判词本身已过消毒（坏数据不许变成新的传播载体，规则 11）。
        logger.warning(
            "实体关系册校验留痕 %d 条：%s", len(problems), sanitize_label("; ".join(problems[:5]))
        )
    records = tuple(sorted(entities, key=lambda record: record.name))
    triples = tuple(
        sorted(relations, key=lambda triple: (triple.subject, triple.relation, triple.object))
    )
    return EntitySeed(
        entities=records,
        relations=triples,
        ok=bool(problems) is False and bool(records),
        errors=tuple(sanitize_label(problem) for problem in problems),
    )


@lru_cache(maxsize=8)
def load_seed(path_str: str | None = None) -> EntitySeed:
    """唯一取数口（按路径缓存；缺省吃随包种子）。缓存键是**路径字符串**，不认内容 mtime ⇒
    同进程原地改文件必须 ``load_seed.cache_clear()``（与 config 门族同一条已知边界）。"""
    return _read_seed(Path(path_str) if path_str else SEED_PATH)


def seed_problems(path_str: str | None = None) -> tuple[str, ...]:
    """册的自检读数（审计/巡检用，不参与任何判定）。"""
    seed = load_seed(path_str)
    if seed.ok:
        return ()
    return seed.errors or ("实体关系册为空或缺席",)


def _resolve_name(seed: EntitySeed, value: object) -> str | None:
    """别名 → 正名。**只认逐字等值**：不做前缀/词干/模糊匹配（那等于给猜测发身份证）。"""
    raw = _normalize(value)
    if not raw:
        return None
    if raw in seed.names():
        return raw
    return seed.alias_index().get(raw)


def entity(name: object, path_str: str | None = None) -> EntityRecord | None:
    """按名或别名取实体条目；查不到返回 None（诚实缺席）。"""
    seed = load_seed(path_str)
    resolved = _resolve_name(seed, name)
    return None if resolved is None else seed.by_name().get(resolved)


def entities(kind: str | None = None, path_str: str | None = None) -> tuple[EntityRecord, ...]:
    """全部实体，或按类别过滤（类别不在门票内 ⇒ 空，不返回"未知类别"的东西）。"""
    seed = load_seed(path_str)
    if kind is None:
        return seed.entities
    wanted = _normalize(kind)
    if wanted not in ENTITY_KINDS:
        return ()
    return tuple(record for record in seed.entities if record.kind == wanted)


def relation_edges(
    subject: object = None,
    relation: str | None = None,
    object_: object = None,
    path_str: str | None = None,
) -> tuple[RelationTriple, ...]:
    """按端点/关系词过滤三元组（三者全 None ⇒ 整册）。"""
    seed = load_seed(path_str)
    wanted_relation = _normalize(relation)
    resolved_subject = _resolve_name(seed, subject) if subject is not None else None
    resolved_object = _resolve_name(seed, object_) if object_ is not None else None
    out: list[RelationTriple] = []
    for triple in seed.relations:
        if wanted_relation and triple.relation != wanted_relation:
            continue
        if resolved_subject is not None and triple.subject != resolved_subject:
            continue
        if resolved_object is not None and triple.object != resolved_object:
            continue
        out.append(triple)
    return tuple(out)


def objects_of(subject: object, relation: str, path_str: str | None = None) -> tuple[str, ...]:
    """一跳取数：``objects_of("守岸人", "belongs_to_work")`` → ``("鸣潮",)``。"""
    return tuple(triple.object for triple in relation_edges(subject, relation, path_str=path_str))


def one_hop(subject: object, relation: str, path_str: str | None = None) -> tuple[tuple[str, str], ...]:
    """一跳取数并保留关系词：``(("belongs_to_work", "鸣潮"),)``。"""
    return tuple(
        (triple.relation, triple.object)
        for triple in relation_edges(subject, relation, path_str=path_str)
    )


def resolve_chain(start: object, relations: Sequence[str], path_str: str | None = None) -> tuple[str, ...]:
    """沿关系词链逐跳，返回 ``(*中间节点, 终点)``；任一跳转不动 ⇒ 空元组（不猜下一跳）。

    多值时按**字典序取第一枚**（册内排序已确定 ⇒ 同输入同输出，可复现）；要全量请逐跳用
    ``objects_of``。例：``resolve_chain("守岸人", ("belongs_to_work", "developed_by"))``
    → ``("鸣潮", "广州库洛科技有限公司")``。
    """
    seed = load_seed(path_str)
    current = _resolve_name(seed, start)
    if current is None or not relations:
        return ()
    trail: list[str] = []
    for relation in relations:
        nxt = objects_of(current, relation, path_str=path_str)
        if not nxt:
            return ()
        hop = nxt[0]
        trail.append(hop)
        current = hop
    return tuple(trail)


def label_of(name: object, path_str: str | None = None) -> str:
    """实体展示名（已过消毒；未在册的名字同样消毒后返回，不编造类别）。"""
    del path_str  # 取名不查册：这一口只保证消毒，保证不了"它在册"
    return sanitize_label(name)


def unverified_records(path_str: str | None = None) -> dict[str, tuple[str, ...]]:
    """待核读数：``{"entities": (名字…), "relations": ("S rel O"…)}``。"""
    seed = load_seed(path_str)
    return {
        "entities": tuple(record.name for record in seed.entities if not record.verified),
        "relations": tuple(
            f"{triple.subject} {triple.relation} {triple.object}"
            for triple in seed.relations
            if not triple.verified
        ),
    }


def unverified_prefix() -> str:
    """待核标签前缀的唯一真身（调用方拼展示名时用它，别各处手写）。"""
    return _UNVERIFIED_PREFIX


def graph_edges(path_str: str | None = None) -> tuple[tuple[str, str, str, int], ...]:
    """给图谱用的边 ``(source, target, kind, weight)``：端点已消毒、关系词已过门票。

    权重口径（**如实降权**而不是藏起来）：已核实＝2、待核＝1。
    """
    seed = load_seed(path_str)
    edges: list[tuple[str, str, str, int]] = []
    for triple in seed.relations:
        source = sanitize_label(triple.subject)
        target = sanitize_label(triple.object)
        if not source or not target or triple.relation not in RELATION_TYPES:
            continue
        edges.append((source, target, triple.relation, 2 if triple.verified else 1))
    return tuple(edges)


def graph_nodes(path_str: str | None = None) -> tuple[tuple[str, str, str], ...]:
    """节点 ``(name, kind, label)``（id 前缀由调用方加——本件不知道别人的 id 空间）。"""
    seed = load_seed(path_str)
    return tuple((record.name, record.kind, sanitize_label(record.name)) for record in seed.entities)


# ===========================================================================
# 对话链路读接口（席 S12，现实知识面波 2026-10-03）
# 只加函数：上面既有语义（含 ``objects_of`` / ``one_hop`` / ``resolve_chain``）一字未动。
# ===========================================================================

#: 关系词的中文展示名——**措辞唯一真身**：对话分区、卡片、审计都从这里取，
#: 禁在 ``chat.py`` 或 ``personas/`` 抄第二份（【现实坐标】的单源口径，席 S2 先例）。
RELATION_LABELS_ZH: dict[str, str] = {
    RELATION_BELONGS_TO_WORK: "出自作品",
    RELATION_DEVELOPED_BY: "开发",
    RELATION_PUBLISHED_BY: "发行",
    RELATION_LOCATED_IN: "所在地",
}

#: 展示名按**主语类别**分档：种子里 ``developed_by`` 在展会语境登记的是主办方
#: （见 ``entity_relation_seed.json`` 的注记）。边名不动、说法随主语类别换——
#: 图谱侧仍认 ``developed_by``，这里只管人话。
RELATION_LABELS_ZH_BY_SUBJECT_KIND: dict[str, dict[str, str]] = {
    "expo": {RELATION_DEVELOPED_BY: "主办"},
}

#: 加书名号的类别（只为可读性，不承载任何判定）。
_TITLE_QUOTE_KINDS: frozenset[str] = frozenset({"work"})

#: 问句里的关系诉求词 → 关系词。词表在此单源：新增问法要同批改这张表并补锁，
#: 调用方各拼一份词表就是第二真身（规则 10 同型）。
RELATION_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    RELATION_BELONGS_TO_WORK: ("出自", "哪部作品", "什么作品", "哪个游戏", "哪款游戏"),
    RELATION_DEVELOPED_BY: ("开发商", "开发", "研发", "制作方", "主办方", "主办", "谁做", "做的", "哪家公司"),
    RELATION_PUBLISHED_BY: ("发行", "代理商", "谁运营"),
    RELATION_LOCATED_IN: ("在哪", "所在地", "总部", "哪个城市", "地址", "地点"),
}

#: 拉丁别名的命中判定要词边界 + **区分大小写**：``CP`` 若按大小写无关咬住
#: 「cp 命令」「CPU」就是把用户的话接到展会身上。中文别名按子串命中。
_ASCII_ALIAS_RE = re.compile(r"[A-Za-z0-9]+")

#: 一跳行数的默认帽（对话分区只给"这一轮问到的那几条"；少给不叫编造，多给才叫）。
DEFAULT_MAX_RELATION_LINES = 3


@dataclass(frozen=True)
class RelationHit:
    """一跳查询的一条命中：**核实状态是字段，不是注释**。

    ``verified`` ＝ 这条陈述整体可当事实的程度，取「边 ∧ 主语实体 ∧ 宾语实体」三者之与：
    任一方标 ``false`` 都不许端成已确认事实（种子今天就有这么一枚——展会侧边标已核、
    主语实体标待核，本字段把它如实降成待核）。``unverified`` 是同值的显式反面，
    消费方照它拼「待核」前缀，绝不由 ``note`` 文本反推。
    """

    subject: str
    subject_kind: str
    relation: str
    relation_label: str
    object: str
    object_kind: str
    edge_verified: bool
    subject_verified: bool
    object_verified: bool
    verified: bool
    unverified: bool
    note: str = ""


def match_entities_in(text: object, path_str: str | None = None) -> tuple[str, ...]:
    """从一句自然问句里挑出**在册**实体的正名（长名优先，被长名包含的短别名让位）。

    取名口只有这一个：正名来自 ``EntitySeed.alias_index``，判定＝逐字命中；不做词干、
    模糊、近义（那等于给猜测发身份证，与 ``_resolve_name`` 同一口径）。册缺席 ⇒ 空元组。
    拉丁别名区分大小写并按整词命中（``_ASCII_ALIAS_RE``），中文别名按子串。
    """
    seed = load_seed(path_str)
    hay = _normalize(text)
    if not hay or not seed.entities:
        return ()
    index = seed.alias_index()
    matched_keys: list[str] = []
    names: list[str] = []
    for key in sorted(index, key=lambda item: (-len(item), item)):
        if any(key in longer for longer in matched_keys):
            continue
        hit = key in hay if not _ASCII_ALIAS_RE.fullmatch(key) else _whole_word_hit(key, hay)
        if hit:
            matched_keys.append(key)
            canonical = index[key]
            if canonical not in names:
                names.append(canonical)
    return tuple(names)


def _whole_word_hit(key: str, text: str) -> bool:
    """拉丁别名整词命中（大小写敏感）：``CP`` 咬得住「CP 展」，咬不住「cp 命令」「CPU」。

    边界只认 **ASCII** 字母数字——CJK 的 ``.isalnum()`` 也是真，拿它当边界会把
    「CICF是什么」判成"词被切开"，于是真·简称全树查不到（本席第一版就是这么瞎的）。
    """
    start = 0
    width = len(key)
    while True:
        at = text.find(key, start)
        if at < 0:
            return False
        before = text[at - 1] if at > 0 else ""
        after = text[at + width] if at + width < len(text) else ""
        glued = any(ch.isascii() and ch.isalnum() for ch in (before, after))
        if not glued:
            return True
        start = at + 1


def relations_for_question(text: object) -> tuple[str, ...]:
    """问句 ↔ 在册关系词：只认 ``RELATION_QUERY_TERMS`` 登记过的诉求词。

    一个都不命中 ⇒ 空元组，语义是「问句没点名要哪条边」，由调用方决定给不给全量一跳；
    本件不猜下一条边（猜出来的关系词就是编造）。
    """
    hay = _normalize(text)
    if not hay:
        return ()
    return tuple(
        relation
        for relation, terms in RELATION_QUERY_TERMS.items()
        if relation in RELATION_TYPES and any(term in hay for term in terms)
    )


def lookup_one_hop(
    names: Sequence[str],
    relations: Sequence[str] = (),
    path_str: str | None = None,
) -> tuple[RelationHit, ...]:
    """一跳查询（纯离线、零网络零写盘）：按正名/别名解析主语，取该主语的在册出边。

    ``relations`` 为空 ⇒ 返回该主语**全部**一跳边（「CICF是什么」这类没点名的问法）；
    非空 ⇒ 只取其中这几条。定序沿用册内排序 ⇒ 同输入同输出，可复跑对账。
    """
    seed = load_seed(path_str)
    by_name = seed.by_name()
    wanted = {word for word in (relations or ()) if word in RELATION_TYPES}
    resolved: list[str] = []
    for name in names or ():
        canonical = _resolve_name(seed, name)
        if canonical and canonical not in resolved:
            resolved.append(canonical)
    hits: list[RelationHit] = []
    for triple in seed.relations:
        if triple.subject not in resolved:
            continue
        if wanted and triple.relation not in wanted:
            continue
        subject_record = by_name.get(triple.subject)
        object_record = by_name.get(triple.object)
        subject_verified = bool(subject_record and subject_record.verified)
        object_verified = bool(object_record and object_record.verified)
        verified = bool(triple.verified and subject_verified and object_verified)
        hits.append(
            RelationHit(
                subject=triple.subject,
                subject_kind=subject_record.kind if subject_record else "",
                relation=triple.relation,
                relation_label=relation_label_for(
                    triple.relation, subject_record.kind if subject_record else ""
                ),
                object=triple.object,
                object_kind=object_record.kind if object_record else "",
                edge_verified=bool(triple.verified),
                subject_verified=subject_verified,
                object_verified=object_verified,
                verified=verified,
                unverified=not verified,
                note=triple.note,
            )
        )
    return tuple(hits)


def relation_label_for(relation: str, subject_kind: str) -> str:
    """关系词的展示名（措辞单源口）。认不出 ⇒ 空串，调用方据此**丢掉这一行**，
    不把英文关系词当人话端给模型，也不现编一个中文说法。"""
    wanted = _normalize(relation)
    override = RELATION_LABELS_ZH_BY_SUBJECT_KIND.get(_normalize(subject_kind), {})
    if wanted in override:
        return override[wanted]
    return RELATION_LABELS_ZH.get(wanted, "")


def _titled(name: str, kind: str) -> str:
    return f"《{name}》" if _normalize(kind) in _TITLE_QUOTE_KINDS else name


def reality_relation_lines(
    text: object,
    *,
    max_lines: int = DEFAULT_MAX_RELATION_LINES,
    path_str: str | None = None,
) -> tuple[str, ...]:
    """对话分区正文的唯一渲染口：问句 → 在册实体 → 一跳边 → 一行一条事实。

    形态：``- 《鸣潮》→ 开发：广州库洛科技有限公司（已核）``；
    未核实：``- CICF → 所在地：待核｜广州``（前缀真身＝``unverified_prefix()``）。
    已核的行先给、待核的行排后面再受 ``max_lines`` 帽（同主语内保持册内定序）。
    查不到任何一条 ⇒ **空元组**：调用方按"空分区不渲染"处理，本件不塞占位句、
    不端别人家的条目顶上（缺席就是缺席）。
    """
    names = match_entities_in(text, path_str=path_str)
    if not names:
        return ()
    hits = lookup_one_hop(names, relations_for_question(text), path_str=path_str)
    ordered = [hit for hit in hits if hit.verified] + [hit for hit in hits if not hit.verified]
    lines: list[str] = []
    for hit in ordered:
        if not hit.relation_label:
            continue
        object_text = hit.object if hit.verified else f"{unverified_prefix()}{hit.object}"
        suffix = "（已核）" if hit.verified else ""
        lines.append(f"- {_titled(hit.subject, hit.subject_kind)} → {hit.relation_label}：{object_text}{suffix}")
        if len(lines) >= max(1, int(max_lines)):
            break
    return tuple(lines)
