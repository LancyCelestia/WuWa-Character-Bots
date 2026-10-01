"""T-Spec 触发指令规范化——规格无关机械化体检（红点台账制）。

基础设施（scripts/extract_trigger_words.py）从当前源码机械化提取：
RouteRule↔检测函数映射、各 ``is_*`` 函数字面触发素材、help 触发记录、
DEFAULT_VERB_MAP，并做行为级体检（探针实跑，非纸面词表比对）：

1. 映射完整性：每条 RouteRule 有可调用 matcher；命令类路由必有 ``is_*``
   行为检测器；help 每个 topic 必有触发记录（aliases/triggers_nl/
   triggers_nickname 至少其一）。
2. 冲突检测：任一 verified 触发词探针跑全部 ``is_*`` 检测器必须唯一命中
   所属 capability。
3. 词边界纪律：ASCII 触发词按 ``_alias_hit`` 模式（词边界）匹配——
   ``qq<word>`` / ``<word>qq`` 胶合探针不得命中自身能力。
4. **跨能力撞词体检（S137，2026-09-24 自 ``test_trigger_word_copy_ratchet.py`` 的
   ruleA 第 11 簇移交过来）**：两枚字面量真身词集全等、却**分属两个能力**且没有任何门
   要求它们相等 ⇒ 这不是"同一份词抄了两遍"（副本账判的），这是**词义冲突**——按尺 B
   自己写死的归属，它归本门。判据不另起一把尺：成员位与词集都由副本账的**同一个 AST
   取数口**（``scan_tree``/``analyze``）现算，能力归属由中央件
   ``classify_help_topics`` + RouteRule 检测器模块路径派生，零手工清单。

现状红点以**台账制**管理（这是体检不是改造，不改源码凑绿）：
- ``KNOWN_CONFLICT_WORDS`` / ``KNOWN_BOUNDARY_KEYS`` 登记基线实测红点
  （2026-09-12 基线，含并行 T1.2 英文触发在途改动），用例内
  ``pytest.xfail`` 标记，并带双向棘轮：台账条目被修复 → 强制失败提醒清
  台账；台账外新增红点 → 硬断言失败，自动浮出为规范化波工作清单。
- ``KNOWN_CROSS_CAPABILITY_CLASHES`` 同哲学，但它是**静态腿不是行为腿**：A8 那枚
  ``订阅/訂閱/subscribe`` 今天由路由优先级兜底，``is_*`` 探针实测**不**双命中（已现算核实），
  塞进 ``KNOWN_CONFLICT_WORDS`` 会当场撞"红点已修复请清账"那条锁 ⇒ 另立一条静态台账，
  两侧同棘轮：新撞词未登记 → 硬失败；登记在案的撞词已消除 → 强制失败要求清账。
- 规格相关断言（七格矩阵：英文/简体/繁體/全拼/缩写/昵称/自然语言的
  全量覆盖与唯一性）待 T-Spec 终确认后启用，见文末 skip 占位。
"""

from __future__ import annotations

import importlib
from typing import Final, NamedTuple

import pytest

from scripts.extract_trigger_words import (
    _ASCII_WORD_RE,
    _STRUCTURAL_KINDS,
    build_inventory,
    classify_help_topics,
    normalize_trigger_key,
)
from tests.test_trigger_word_copy_ratchet import (  # 单一 AST 取数口：本门不另起第二把尺
    _UNEXISTENT_WORD,
    HOME_CROSS_CAPABILITY_NOT_DEBT,
    HOME_MIRROR_NOT_DEBT,
    Occ,
    _words_from_text,
    account,
    analyze,
    scan_source,
    scan_tree,
)

INV = build_inventory()

# 行为检测器实跑表：capability_id -> [callable]（排序保证确定性）。
_LIVE_DETECTORS: dict[str, list] = {}
_DETECTOR_BY_NAME: dict[tuple[str, str], object] = {}
for _cap in sorted(INV["capabilities"]):
    for _report in INV["capabilities"][_cap]["detectors"]:
        if not _report.get("callable") or not _report["name"].startswith("is_"):
            continue
        _func = getattr(importlib.import_module(_report["module"]), _report["name"])
        _LIVE_DETECTORS.setdefault(_cap, []).append(_func)
        _DETECTOR_BY_NAME[(_cap, _report["name"])] = _func

# verified 触发词探针全集：(capability_id, word, probe, detector_name)。
_VERIFIED_CASES: list[tuple[str, str, str, str]] = sorted(
    (_cap, _word, _info["probe"], _info["detector"])
    for _cap, _item in INV["capabilities"].items()
    for _word, _info in _item["verified_triggers"].items()
)

# ASCII 词边界探针全集：(capability_id, word, side, glued_probe, detector)。
_BOUNDARY_CASES: list[tuple[str, str, str, str, str]] = sorted(
    (
        _cap,
        _word,
        _side,
        _glued,
        INV["capabilities"][_cap]["verified_triggers"][_word]["detector"],
    )
    for _cap, _item in INV["capabilities"].items()
    for _word in sorted(_item["verified_triggers"])
    if len(_word.strip()) >= 2 and _ASCII_WORD_RE.fullmatch(_word.strip())
    for _side, _glued in (("left", "qq" + _word.strip()), ("right", _word.strip() + "qq"))
)


def _probe_hits_all(probe: str) -> list[str]:
    """探针跑全部 is_* 检测器，返回命中的 capability_id 列表（排序）。"""
    return sorted(
        cap for cap in sorted(_LIVE_DETECTORS) if any(func(probe) for func in _LIVE_DETECTORS[cap])
    )


# ---------------------------------------------------------------------------
# 现状红点台账（2026-09-12 基线；规范化波工作清单，修复后必须同步清账）
# ---------------------------------------------------------------------------

# 跨能力触发冲突：同一探针命中多个 capability（当前由路由优先级兜底，词表层未收敛）。
# 已全部清账（2026-09-13 RF 波，xfail 11→0）：music_mode ×4（点歌模式/點歌模式/
# music mode/song mode）裸词由 music._COMMAND_RE 加 mode 负前瞻整体让渡，
# 裸词唯一命中 music_mode；带歌名/参数后继形态保持双命中让路对（既有形态）。
# 详见 .superpowers/sdd/2026-09-12-shorekeeper-global-audit/fix-rf-report.md。
# 2026-09-14 群信息能力（B-01/B-04）：「群主是谁」是任务书点名的口语触发词，
# 词形天然撞 moegirl 实体问句（剥「是谁」剩「群主」过 _ENTITY_MIN_LEN=2）——
# 运行时由路由优先级兜底（group_info 41 < moegirl_question 46，群信息稳定先接），
# 词表层双命中让路对登记于此（与 music_mode/music 让路对同形态）。
KNOWN_CONFLICT_WORDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("bot.group_info", "群主是谁"),
        # 2026-10-01 T25 现算：「待审」是**两能力各自独立的只读队列头**——
        # emergency_info._PENDING_WORDS（人工报料待审）与 meme_library 审批正则
        # （表情库待审档，S-MEME2-REVIEW 有意「命令前缀可省，裸词也认」）。
        # 运行时由路由优先级兜底：meme_library 22 < emergency_info 44 ⇒ 裸「待审」
        # 稳定先由表情库这一面接（该腿另有管理判定门）；BOT_MEME_LIBRARY_ENABLED=false
        # 时 meme_library_match 早退，这一句落到紧急信息。两侧词面都要收敛须改命令面
        # 词表＝行为变更（重启验收），本波不动，故按既有让路对形态登记两枚。
        ("bot.emergency_info", "待审"),
        ("bot.meme_library", "待审"),
    }
)

# ASCII 词边界违规：胶合探针命中自身能力（_alias_hit 纪律：ASCII 词须词边界）。
# 已全部清账（2026-09-13，两波）：
# ①对账波（fix-ratchet-report.md）：bot.stocks openai/anthropic/bytedance
#   left/right ×6 死账移除——HIJACK-FIX 后裸英文公司名已非 verified 触发词，
#   对应参数化用例不再生成，靠人工对账清除。
# ②RF 波（fix-rf-report.md，xfail 11→0）：affinity/meme/meme_library ×2/
#   music/weather ×7 右胶合已补词边界（IGNORECASE 正则用 (?![a-z0-9])，
#   weather 无 IGNORECASE 用 (?![A-Za-z0-9])）。
KNOWN_BOUNDARY_KEYS: frozenset[tuple[str, str, str]] = frozenset()


# ---------------------------------------------------------------------------
# 映射完整性（规格无关，硬断言）
# ---------------------------------------------------------------------------


def test_route_registry_matches_live_route_rules() -> None:
    """AST 提取的规则表必须与运行时 ROUTE_RULES 同构（防提取器脱册）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router import (
        ROUTE_RULES,
    )

    live = sorted(
        (rule.kind.name, rule.capability_id, rule.priority) for rule in ROUTE_RULES
    )
    extracted = sorted(
        (rule["kind"], rule["capability_id"], rule["priority"])
        for rule in INV["route_rules"]
    )
    assert extracted == live
    assert all(rule.matcher is not None and callable(rule.matcher) for rule in ROUTE_RULES)


def test_command_rules_have_behavioral_detector() -> None:
    """命令类路由（非结构类）必须至少挂一个 is_* 行为检测器。"""
    weak = [
        rule["capability_id"]
        for rule in INV["route_rules"]
        if rule["kind"] not in _STRUCTURAL_KINDS
        and not any(name.startswith("is_") for name in rule["detectors"])
    ]
    assert weak == []


def test_all_behavioral_detectors_callable() -> None:
    broken = [
        (cap, report["name"])
        for cap, item in INV["capabilities"].items()
        for report in item["detectors"]
        if report["name"].startswith("is_") and not report.get("callable")
    ]
    assert broken == []


def test_structural_rules_are_classified() -> None:
    """结构类路由（别名/管理员/自然语言/链接/聊天）登记在案，防漏分诊。"""
    structural = sorted(set(INV["structural_rule_kinds"]))
    assert structural == ["ADMIN", "ALIAS", "CHAT", "CONTENT", "NATURAL_COMMAND"]


def test_help_topics_have_trigger_records() -> None:
    """help 每个 topic 必有触发记录（aliases / triggers_nl / triggers_nickname）。"""
    assert INV["help_topics_missing_trigger_records"] == []


def test_help_topics_have_capability_ref() -> None:
    missing = [
        topic
        for topic, info in INV["help_topics"].items()
        if not info["capability"]
    ]
    assert missing == []


def test_default_verb_map_registered() -> None:
    """DEFAULT_VERB_MAP 非空且逐条指向能力 id（昵称命令动词映射基线）。"""
    groups = INV["verb_map_groups"]
    assert groups
    assert all(verb for verbs in groups.values() for verb in verbs)


# ---------------------------------------------------------------------------
# 冲突检测：verified 触发词探针必须唯一命中所属能力（台账制棘轮）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cap,word,probe,_detector", _VERIFIED_CASES, ids=lambda x: str(x))
def test_verified_trigger_hits_owner_capability(cap: str, word: str, probe: str, _detector: str) -> None:
    hits = _probe_hits_all(probe)
    if (cap, word) in KNOWN_CONFLICT_WORDS:
        if hits == [cap]:
            pytest.fail(
                f"红点已修复：{word!r} 不再跨能力冲突，请从 KNOWN_CONFLICT_WORDS 移除 {(cap, word)}"
            )
        pytest.xfail(f"现状红点（台账已登记）：{word!r} 同时命中 {hits}")
    assert hits == [cap], f"新增跨能力冲突（未登记台账）：{word!r} 探针 {probe!r} 命中 {hits}"


# ---------------------------------------------------------------------------
# 词边界纪律：ASCII 触发词胶合探针不得命中（_alias_hit 模式，台账制棘轮）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cap,word,side,glued,detector_name", _BOUNDARY_CASES, ids=lambda x: str(x)
)
def test_ascii_trigger_word_boundary(
    cap: str, word: str, side: str, glued: str, detector_name: str
) -> None:
    func = _DETECTOR_BY_NAME[(cap, detector_name)]
    violated = bool(func(glued))
    if (cap, word, side) in KNOWN_BOUNDARY_KEYS:
        if not violated:
            pytest.fail(
                f"红点已修复：{word!r} {side} 侧已词边界，请从 KNOWN_BOUNDARY_KEYS 移除"
            )
        pytest.xfail(
            f"现状红点（台账已登记）：{detector_name} 对胶合探针 {glued!r} 仍裸子串命中"
        )
    assert not violated, (
        f"新增 ASCII 词边界违规（未登记台账）：{cap} {detector_name} 命中 {glued!r}"
    )


# ---------------------------------------------------------------------------
# 跨能力撞词体检（S137，2026-09-24：副本账 ruleA 第 11 簇按裁定 9 移交至此）
# ---------------------------------------------------------------------------

#: 帮助册三个触发位的字段名。写成换行单串再切分：本文件在 ``SCAN_ROOTS`` 的 ``tests`` 里，
#: 任何「字面量容器」都会成为副本账的 tier-2 候选（与 ``_KIND_VOCAB`` 同一条自扫纪律）。
_HELP_TRIGGER_FIELD_VOCAB: Final[str] = "aliases\ntriggers_nl\ntriggers_nickname"
_HELP_TRIGGER_FIELDS: Final[tuple[str, ...]] = tuple(_HELP_TRIGGER_FIELD_VOCAB.split("\n"))

#: 真身文件 → 能力集合：RouteRule 的 ``is_*`` 检测器住在哪个模块，那个模块的模块级词表
#: 就是那个能力的命令面（中央件派生，零手工清单）。
_CAPS_BY_MODULE_FILE: Final[dict[str, frozenset[str]]] = {}
for _cap_id, _item in INV["capabilities"].items():
    for _report in _item["detectors"]:
        _rel = _report["module"].replace(".", "/") + ".py"
        _CAPS_BY_MODULE_FILE[_rel] = _CAPS_BY_MODULE_FILE.get(_rel, frozenset()) | {_cap_id}

#: 帮助册**单个字段**的词集 → 该 topic 归属的能力集合。刻意按字段级比对而不是 topic 合并级：
#: 副本账认出的一枚真身恰好就是一个字段位（``dict:aliases``），合并集永远不相等。
_CAPS_BY_HELP_FIELD: Final[dict[frozenset[str], frozenset[str]]] = {}
_CLASSIFIED_HELP: Final[dict[str, dict]] = classify_help_topics(INV["help_topics"])
for _topic, _info in INV["help_topics"].items():
    _topic_caps: frozenset[str] = frozenset(
        _CLASSIFIED_HELP[_topic]["caps"] | _CLASSIFIED_HELP[_topic]["admin_caps"]
    )
    for _field in _HELP_TRIGGER_FIELDS:
        _keys = frozenset(
            key for word in _info.get(_field) or () if (key := normalize_trigger_key(word))
        )
        if _keys:
            _CAPS_BY_HELP_FIELD[_keys] = _CAPS_BY_HELP_FIELD.get(_keys, frozenset()) | _topic_caps


def _capabilities_of(occ: Occ) -> frozenset[str]:
    """一枚真身词表归属哪些能力（模块路径 ∪ 帮助册字段位）。"""
    module_caps = _CAPS_BY_MODULE_FILE.get(occ.file, frozenset())
    keys = frozenset(key for word in occ.words if (key := normalize_trigger_key(word)))
    return frozenset(module_caps | _CAPS_BY_HELP_FIELD.get(keys, frozenset()))


class WordClash(NamedTuple):
    """现算出的一枚跨能力撞词：词集＋成员位（不含行号，行号会漂）＋涉及能力。"""

    words: frozenset[str]
    sites: frozenset[tuple[str, str]]
    caps: frozenset[str]


class KnownClash(NamedTuple):
    """台账条目：与 ``WordClash`` 同键（词集全等＋成员位集合），另写死应当涉及的能力与判据。"""

    words_text: str
    sites: tuple[tuple[str, str], ...]
    caps: tuple[str, ...]
    reason: str

    @property
    def words(self) -> frozenset[str]:
        return _words_from_text(self.words_text)

    def matches(self, clash: WordClash) -> bool:
        return self.words == clash.words and frozenset(self.sites) == clash.sites


#: **跨能力撞词台账**（自副本账移交的那一枚在此接住；新增必须逐枚点名＋写判据，禁止条款化）。
#: 现算口径：全树字面量真身里「词集全等、成员分属 ≥2 个能力、且该能力对别的名册成员不成立」的簇。
#: 2026-09-24 现算值＝1 簇（本台账 1 条），其余 10 簇成员归属同一能力＝在册镜像、由副本账豁免。
KNOWN_CROSS_CAPABILITY_CLASHES: Final[tuple[KnownClash, ...]] = (
    KnownClash(
        words_text="subscribe、訂閱、订阅",
        sites=(
            ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"),
            ("plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py", "_SUBSCRIBE_WORDS"),
        ),
        caps=("bot.emergency_info", "bot.subscribe"),
        reason="裁定 9 之 A8：帮助册 bot.subscribe 的 aliases 位与紧急信息域群内订阅命令面 _SUBSCRIBE_WORDS 词集全等，两枚真身分属两个能力、无共同上级册、也无双向门要求它们相等 ⇒ 属词义冲突而非副本。行为侧今天由路由优先级兜底（实测 is_* 探针不双命中，故另立静态腿而非塞进 KNOWN_CONFLICT_WORDS）；要消除本条须改两侧命令面词（行为变更，须重启验收），不许删本条换绿",
    ),
)


def compute_cross_capability_clashes(
    extra_homes: tuple[Occ, ...] = (),
) -> tuple[list[WordClash], list[Occ]]:
    """现算跨能力撞词（＋归属空位清单）。取数口＝副本账那把尺，判据腿长在本门。"""
    _files, homes, _copies = scan_tree()
    _rule_b, rule_a = analyze(list(homes) + list(extra_homes), [])
    clashes: list[WordClash] = []
    holes: list[Occ] = []
    for cluster in rule_a:
        per_member = [_capabilities_of(member) for member in cluster.members]
        holes += [member for member, caps in zip(cluster.members, per_member) if not caps]
        union = frozenset().union(*per_member) if per_member else frozenset[str]()
        exclusive = {
            cap
            for index, own in enumerate(per_member)
            for cap in own
            if all(cap not in other for j, other in enumerate(per_member) if j != index)
        }
        if exclusive:
            clashes.append(
                WordClash(
                    words=frozenset(cluster.words),
                    sites=frozenset((m.file, m.label) for m in cluster.members),
                    caps=union,
                )
            )
    return clashes, holes


def _clash_ledger_violations(
    clashes: list[WordClash], ledger: tuple[KnownClash, ...]
) -> list[str]:
    """台账与现算的双向比对（同一函数既服务生产断言也服务注毒）。"""
    problems: list[str] = []
    spare = list(ledger)
    for clash in clashes:
        hit = next((i for i, entry in enumerate(spare) if entry.matches(clash)), None)
        if hit is None:
            problems.append(
                f"新增跨能力撞词（未登记台账）：词 {sorted(clash.words)} 于 "
                f"{sorted(clash.sites)}，涉及能力 {sorted(clash.caps)}"
            )
            continue
        entry = spare.pop(hit)
        if frozenset(entry.caps) != clash.caps:
            problems.append(
                f"台账把涉及能力写错了：词 {sorted(clash.words)} 现算 {sorted(clash.caps)}"
                f" ≠ 登记 {sorted(entry.caps)}"
            )
    for entry in spare:
        problems.append(
            f"台账条目在盘上已不成立（撞词已消除、或换了位置/换了词集），请清账或重登记："
            f"{entry.words_text}｜{sorted(entry.sites)}"
        )
    return problems


def _handoff_lock_violations(
    roster: tuple[object, ...], ledger: tuple[KnownClash, ...]
) -> list[str]:
    """两本账互锁（**不许只删不接**）：副本账摘出的每一枚都必须在这里登记，反之亦然。

    键＝(词集全等, 成员位集合)——同一枚事实只在一本账上记一次：
    副本账摘了而本门没接 ⇒ 本门红；本门登记了而副本账还在计账 ⇒ 同一枚红两遍，也算失衡。
    """
    roster_keys = {(entry.words, frozenset(entry.sites)) for entry in roster}  # type: ignore[attr-defined]
    ledger_keys = {(entry.words, frozenset(entry.sites)) for entry in ledger}
    problems: list[str] = []
    for words, sites in sorted(roster_keys - ledger_keys, key=lambda k: (sorted(k[0]), sorted(k[1]))):
        problems.append(
            f"副本账把这一枚摘成了「不计账」，本门却没有登记＝红被搬走了没人接：词 {sorted(words)}"
            f"｜成员位 {sorted(sites)}"
        )
    for words, sites in sorted(ledger_keys - roster_keys, key=lambda k: (sorted(k[0]), sorted(k[1]))):
        problems.append(
            f"本门登记了跨能力撞词，副本账却没把它摘出＝同一枚记两遍（或名册已漂移）："
            f"词 {sorted(words)}｜成员位 {sorted(sites)}"
        )
    return problems


def test_cross_capability_word_clash_matches_ledger() -> None:
    """跨能力撞词双向棘轮：新撞词未登记即硬失败；登记在案的已消除则强制失败要求清账。"""
    clashes, holes = compute_cross_capability_clashes()
    assert not holes, (
        "能力归属出现空位＝判据被改瞎（「归不到能力」绝不允许被读成「没有冲突」）："
        + "、".join(f"{h.file}:{h.line}:{h.label}" for h in holes)
    )
    problems = _clash_ledger_violations(clashes, KNOWN_CROSS_CAPABILITY_CLASHES)
    assert problems == [], "跨能力撞词体检失配：\n  " + "\n  ".join(problems)


def test_cross_capability_clash_ledger_is_not_empty_by_accident() -> None:
    """台账自证：本门今天必须真的算出过撞词，且现算枚数与台账条数同量级可核对。

    空台账＋空现算＝这条腿可能已经瞎了（判据被改、或能力归属表整体失效）。
    故这里既核对非空，也核对「现算值 == 登记值」这一当前读数（漂移即红，逼一次复核）。
    """
    clashes, _holes = compute_cross_capability_clashes()
    assert clashes, "一枚跨能力撞词都没算出——先查归属表与取数口，别当成「大家都干净了」"
    assert len(clashes) == len(KNOWN_CROSS_CAPABILITY_CLASHES), (
        f"现算 {len(clashes)} 簇 ≠ 台账 {len(KNOWN_CROSS_CAPABILITY_CLASHES)} 条"
        "（逐条内容另有双向棘轮核对，本条只拦「整块失踪」）"
    )


def test_handoff_from_copy_ratchet_is_registered_there() -> None:
    """两本账互锁：A8 从副本账摘出的同时必须在本门登记，且副本账此刻确实没再计它。"""
    problems = _handoff_lock_violations(HOME_CROSS_CAPABILITY_NOT_DEBT, KNOWN_CROSS_CAPABILITY_CLASHES)
    assert problems == [], "副本账与本门的交接不对账：\n  " + "\n  ".join(problems)
    _files, homes, copies = scan_tree()
    rule_b, rule_a = analyze(list(homes), list(copies))
    acct = account(rule_b, rule_a)
    kept_sites = {frozenset((m.file, m.label) for m in cluster.members) for cluster in acct.kept_clusters}
    for entry in KNOWN_CROSS_CAPABILITY_CLASHES:
        assert frozenset(entry.sites) not in kept_sites, (
            f"本门已登记，副本账却仍在计账＝同一枚记两遍：{entry.words_text}"
        )
    assert len(acct.exempt_handoffs) == len(KNOWN_CROSS_CAPABILITY_CLASHES), (
        "副本账的移交豁免簇数与本门台账条数不等＝交接面漂移"
    )
    assert not acct.stale_handoff_entries, f"副本账移交名册虚设：{acct.stale_handoff_entries}"
    assert rule_b or rule_a, "副本账两本账全空＝取数口坏了，本锁已无意义"


# ---- 注毒自证（虚拟源喂同一个取数口，绝不往树里写东西；本文件因此零词面字面量）----


def _virtual_home_src(rel: str, words: frozenset[str]) -> tuple[str, str]:
    name = "S137_POISON_" + ("TRIGGER_WORDS" if "plugins/" in rel else "SAMPLE_WORDS")
    body = ", ".join('"' + word + '"' for word in sorted(words))
    return rel, f"{name} = ({body},)\n"


def test_poison_unregistered_cross_capability_clash_is_red() -> None:
    """注毒①（新撞词必浮出）：把媒体归档族的词整表抄进随机图能力的命令面 ⇒ 本门必红。

    两枚真身分属 bot.media_archive 与 bot.randpic、词集全等、无门要求相等 ⇒ 这是一枚
    **新的**跨能力撞词，台账里没有 ⇒ `_clash_ledger_violations` 必须点名"新增"。
    """
    archive = next(
        entry
        for entry in HOME_MIRROR_NOT_DEBT
        if any("media_archive" in site_file for site_file, _label in entry.sites)
    )
    rel, src = _virtual_home_src(
        "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py", archive.words
    )
    extra_homes, _extra_copies = scan_source(rel, src)
    assert extra_homes, "注毒前提：虚拟真身没被认成 home（tier-1 命名口失效）"
    clashes, _holes = compute_cross_capability_clashes(extra_homes=tuple(extra_homes))
    problems = _clash_ledger_violations(clashes, KNOWN_CROSS_CAPABILITY_CLASHES)
    assert any("新增跨能力撞词" in p for p in problems), (
        f"抄进另一个能力的命令面却没算出新撞词＝归属判据对本门隐形：{problems}"
    )


def test_poison_resolved_clash_must_be_cleared_from_ledger() -> None:
    """注毒②（反向棘轮）：撞词在盘上已不存在 ⇒ 台账条目必须被点名要求清账，不许静默绿。"""
    problems = _clash_ledger_violations([], KNOWN_CROSS_CAPABILITY_CLASHES)
    assert len(problems) == len(KNOWN_CROSS_CAPABILITY_CLASHES), (
        f"清空现算却没逐条点名＝只删不查：{problems}"
    )
    assert all("请清账" in p for p in problems), problems


def test_poison_unwired_handoff_is_red() -> None:
    """注毒③（只删不接必红）：副本账摘了、本门台账清空 ⇒ 互锁必须红。"""
    assert HOME_CROSS_CAPABILITY_NOT_DEBT, "前提：副本账今天确实摘了一枚移交（名册非空）"
    problems = _handoff_lock_violations(HOME_CROSS_CAPABILITY_NOT_DEBT, ())
    assert problems, "副本账摘了移交而本门空台账却不红＝互锁是装饰件"
    assert any("没有登记" in p for p in problems), problems
    reversed_problems = _handoff_lock_violations((), KNOWN_CROSS_CAPABILITY_CLASHES)
    assert reversed_problems and all("记两遍" in p for p in reversed_problems), (
        f"反方向（本门登记、副本账未摘）没牙：{reversed_problems}"
    )


def test_poison_attribution_hole_is_red() -> None:
    """注毒④（判据不许装瞎）：真身归不到任何能力 ⇒ 必须进 holes，不能被读成「没有冲突」。

    词面刻意用**任何能力都没有**的孤儿词（含 `_UNEXISTENT_WORD`，保证不被帮助册字段位捞走），
    并在两个无名模块各抄一枚 ⇒ 成簇但零归属。首版写法（拿在册撞词的词抄进无名模块）会被
    帮助册字段位捞出 `bot.subscribe`，测的其实是另一件事——这一版才真打到归属空洞。
    """
    orphan_words = frozenset({_UNEXISTENT_WORD, "zzz孤儿触发词甲", "zzz孤儿触发词乙"})
    extra_homes: list[Occ] = []
    orphan_files: list[str] = []
    for suffix in ("a", "b"):
        rel, src_text = _virtual_home_src(
            f"plugins/bot_unified_runtime/domains/ops/_s137_poison_virtual_orphan_{suffix}.py",
            orphan_words,
        )
        homes_here, _copies = scan_source(rel, src_text)
        assert homes_here, f"注毒前提：虚拟孤儿真身没被认成 home（{rel}）"
        extra_homes += homes_here
        orphan_files.append(rel)
    clashes, holes = compute_cross_capability_clashes(extra_homes=tuple(extra_homes))
    assert {h.file for h in holes} == set(orphan_files), (
        "无名模块的词表归属不到任何能力却没进 holes＝归属空洞会被读成「全干净」："
        f"{[h.file for h in holes]}"
    )
    assert not any(c.words == orphan_words for c in clashes), (
        "归不到能力却被算成撞词＝holes 与 clashes 两条判据串了位"
    )


# ---------------------------------------------------------------------------
# T-Spec 七格矩阵（规格相关，待用户终确认后启用）
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="待 T-Spec 七格触发矩阵终确认后启用：英文/简体/繁體/昵称/自然语言全量覆盖与唯一性断言")
def test_seven_grid_spec_coverage() -> None:
    raise AssertionError("placeholder")


@pytest.mark.skip(reason="待 T-Spec 终确认且 PYN 拼音表落地后启用：全拼/缩写格覆盖断言")
def test_pinyin_abbreviation_grid_coverage() -> None:
    raise AssertionError("placeholder")
