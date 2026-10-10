"""`/bot 描写 …` 中文词头的**别名归一腿**判据锁（席 aliasgap，2026-10-04）。

席 na3-declare 把中文同义词头**硬写进派发条件式**（它那件 REPORT §缺格 A 自记的正是
这一格），理由写在 `__init__.py` 的注释里：`aliases.py` 不在它的文件域。本件把词头
搬进中央别名册，判据钉的是三件事：

1. **词面只住一处**（AGENTS 铁律：禁第二真身）：中文词头的声明位＝
   `domains/chat_reply/runtime/aliases.py::MODULE_ALIASES` 那一格（同 `功能管理 → feature`
   的在册先例）；根 `__init__.py` 的派发那一支**不许**再点名它。
2. **归一腿真在派发路径上**：`normalize_command_text` 不是只喂帮助册的文案件——
   它就是 `__init__.py` 里 `command_text` 的来源（现算：全仓只有 `__init__.py:8589` 一个
   消费者）。本件因此判「原始文本 → 归一 → 生产条件式原文 → 生产剥词头算式原文」
   这条**真链路**，测试里不写第二份解析逻辑。
3. **两支词头逐字同形**：英文正形与中文同义归一后交给 handler 的子命令串完全一致。

不开 handler、不碰库（判据只到派发面），生产库零写入。

**2026-10-08 起本件同时是「命令面三轴同级」的判据锁**（席 CMD-PINYIN-UNIFY；用户裁
「英文大小写同级／中文简繁同级／拼音全拼·首字母·大小写同级，不统一的全改过来」）：
上面三节守词头机制，末尾六节守三轴——判域全部从 `MODULE_ALIASES` 现派生（配对＝`zhconv`
折形、读音＝`scripts/gen_trigger_pinyin.py`），本文件不写一份词面清单（AGENTS 规则 10），
且三把尺都返回 problems 清单，注毒腿只改内存副本就能验牙。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from zhconv import convert as _zhconvert

from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    MODULE_ALIASES,
    PINYIN_FORMS_WITHHELD,
    normalize_command_text,
)
from scripts import gen_trigger_pinyin as gp

# 取的都是真身、不是副本：
# * `_zhconvert`＝繁简折形真身（`zhconv`，`pyproject.toml` 在册运行时依赖，出处见
#   `docs/THIRD_PARTY_NOTICES.md` §5）。库在而 locale 写错 ⇒ 原样返回（静默 no-op，
#   `content_safety` 为此专门立过探针），所以本件的「库到底折不折形」探针**不自造样本**，
#   直接从 MODULE_ALIASES 现派生一枚简繁对来验。
# * `gp`＝读音真身（pypinyin ＋ 多音字覆写表 ＋ `ABBR_MAX_LEN` 全在
#   `scripts/gen_trigger_pinyin.py` 里），本件只引用、不另实现——另实现＝第二真身。

_ROOT = Path(__file__).resolve().parents[1]
_INIT_SRC_PATH = _ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_ALIASES_SRC_PATH = (
    _ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "aliases.py"
)

_EN_HEAD = "narration"
_CN_HEAD = "描写"


# ------------------------------------------------ 生产派发那一支（AST 原文抽取）


def _handle_status_tree() -> ast.AsyncFunctionDef:
    tree = ast.parse(_INIT_SRC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_status":
            return node
    raise AssertionError("根 __init__.py 里找不到 _handle_status（命令面已搬家？）")


def narration_branch() -> tuple[str, str]:
    """返回「体内调用 build_narration_control_result」那一支的（条件式原文, 剥词头赋值句原文）。

    零命中＝接线缺席；多于一支＝第二通路。
    """
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    hits: list[tuple[str, str]] = []
    for node in ast.walk(_handle_status_tree()):
        if not isinstance(node, ast.If):
            continue
        for stmt in node.body:
            if not _calls_named(stmt, "build_narration_control_result"):
                continue
            assign = _strip_stmt(node.body, src)
            hits.append((ast.get_source_segment(src, node.test) or "", assign))
            break
    if len(hits) > 1:
        raise AssertionError(f"描写档命令面出现 {len(hits)} 支通路（只准一支）")
    if not hits:
        raise AssertionError("根 __init__.py 里没有派发到 build_narration_control_result 的那一支")
    return hits[0]


def _calls_named(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(call, ast.Call)
        and (
            (isinstance(call.func, ast.Name) and call.func.id == name)
            or (isinstance(call.func, ast.Attribute) and call.func.attr == name)
        )
        for call in ast.walk(node)
    )


def _strip_stmt(body: list[ast.stmt], src: str) -> str:
    for stmt in body:
        if not isinstance(stmt, ast.Assign) or not stmt.targets:
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id.endswith("_command")):
            continue
        seg = ast.get_source_segment(src, stmt)
        if seg and "command_text" in seg:
            return seg
    raise AssertionError("派发那一支里没有剥词头的赋值")


def dispatch(raw_command_args: str) -> tuple[bool, str]:
    """真链路：原始参数文本先过 `normalize_command_text`（生产就是这么喂条件式的），
    再把**生产条件式与剥词头算式的原文** exec 一遍。"""
    test_src, assign_src = narration_branch()
    var_name = assign_src.split("=", 1)[0].strip()
    probe = (
        "def probe(command_text):\n"
        f"    if {test_src}:\n"
        f"        {assign_src}\n"
        f"        return True, {var_name}\n"
        "    return False, ''\n"
    )
    ns: dict[str, Any] = {}
    exec(compile(probe, "<dispatch-probe>", "exec"), ns)  # noqa: S102 - 跑仓库自己的生产算式原文
    return ns["probe"](normalize_command_text(raw_command_args))


def _str_literals(path: Path) -> list[str]:
    return [
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# ---------------------------------------------------------------- ① 词面只住一处


def test_chinese_head_is_declared_in_the_module_alias_map() -> None:
    """中文词头是 `MODULE_ALIASES` 的一格，值＝英文正形（`功能管理 → feature` 同先例）。"""
    assert MODULE_ALIASES.get(_CN_HEAD) == _EN_HEAD, (
        "描写 不在中央别名册里 ⇒ 派发条件式只能自己点名它＝词面第二处声明位"
    )


def test_chinese_head_is_declared_in_exactly_one_file() -> None:
    """字面量 `"描写"` 作为字符串常量：**别名册一枚、派发段零枚**（总账＝1）。"""
    in_aliases = _str_literals(_ALIASES_SRC_PATH).count(_CN_HEAD)
    in_init = _str_literals(_INIT_SRC_PATH).count(_CN_HEAD)
    assert in_aliases == 1, f"中央别名册里中文词头出现 {in_aliases} 次（应为 1）"
    assert in_init == 0, (
        f"根 __init__.py 仍有 {in_init} 处硬写中文词头 ⇒ 与 MODULE_ALIASES 构成两处声明位"
    )


def test_dispatch_condition_names_only_the_canonical_head() -> None:
    """条件式与剥词头算式里都不出现中文词头字面量（只读 canonical 名）。"""
    test_src, assign_src = narration_branch()
    for segment, label in ((test_src, "条件式"), (assign_src, "剥词头算式")):
        assert _CN_HEAD not in segment, f"派发那支的{label}仍点名中文词头：{segment}"
        assert _EN_HEAD in segment, f"派发那支的{label}里连英文正形都不在了：{segment}"


# ---------------------------------------------------------------- ② 归一腿真在派发路径上


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("描写", "narration"),
        ("描写 scene", "narration scene"),
        ("描写 speech", "narration speech"),
        ("描写 reset", "narration reset"),
        ("描写 show", "narration show"),
        ("narration scene", "narration scene"),
    ],
)
def test_normalize_command_text_maps_the_head(raw: str, expected: str) -> None:
    assert normalize_command_text(raw) == expected


def test_normalize_is_the_producer_of_the_dispatch_variable() -> None:
    """归一口不是只喂帮助册文案：它唯一消费者就是命令面的 `command_text`。"""
    src = _INIT_SRC_PATH.read_text(encoding="utf-8")
    assert src.count("normalize_command_text(") >= 1
    assert 'command_text = normalize_command_text(' in src, (
        "command_text 不再由 normalize_command_text 产出 ⇒ 别名册不在派发路径上，"
        "本件的修法前提失效，请回退为条件式自带词头"
    )


# ---------------------------------------------------------------- ③ 两支词头同形到达


@pytest.mark.parametrize("arg", ["speech", "scene", "reset", "show", "scen", ""])
def test_both_heads_reach_the_same_handler_argument(arg: str) -> None:
    raw_en = f"{_EN_HEAD} {arg}".strip()
    raw_cn = f"{_CN_HEAD} {arg}".strip()
    hit_en, en_sub = dispatch(raw_en)
    hit_cn, cn_sub = dispatch(raw_cn)
    assert hit_en, f"/bot {raw_en} 派不到 handler"
    assert hit_cn, f"/bot {raw_cn} 派不到 handler（中文同义未走别名册）"
    assert en_sub == cn_sub == arg.strip(), (en_sub, cn_sub, arg)


@pytest.mark.parametrize(
    "text", ["intimate on", "亲密 scene", "帮助", "help 描写", "reply scene", "描写scene"]
)
def test_neighbour_heads_are_not_stolen(text: str) -> None:
    """近形与「亲密」那一族不被描写档吞（`亲密` 无词头别名＝本波未裁，维持缺席）。"""
    hit, _sub = dispatch(text)
    assert not hit, f"{text} 被描写档那一支吞了"


# ---------------------------------------------------------------- ④ 在册先例的一致性


def test_feature_head_precedent_is_the_same_mechanism() -> None:
    """`功能管理 → feature` 是同一先例：中文词头住别名册、派发段只读 canonical。"""
    assert MODULE_ALIASES.get("功能管理") == "feature"
    assert normalize_command_text("功能管理 get bot.x") == "feature get bot.x"


def test_intimate_head_has_no_chinese_alias_yet() -> None:
    """开关面 `intimate` 至今**没有**中文词头（`亲密` 不在册）⇒ 描写 是第二格走中央册的
    中文词头，两族从此同一机制；本件不顺手给 intimate 造词面（未裁＝越权）。"""
    assert "亲密" not in MODULE_ALIASES
    assert MODULE_ALIASES.get("亲密") is None


# ══════════════════════════════════════════════════════════════════════════
# 命令面三轴同级（席 CMD-PINYIN-UNIFY，2026-10-08）
#
# 主人的裁定口径：英文＝**大写/小写同级**、中文＝**简中/繁中同级**、拼音＝**全拼/首字母/
# 大小写同级**。三轴的判域全部**从 `MODULE_ALIASES` 现派生**，本文件一律不写词面清单
# （AGENTS 规则 10：手写清单＝会漂移的计数；在册先例＝`nickname_verbs_for` 的「只筛不造」）。
# 读音真身＝`scripts/gen_trigger_pinyin.py`（pypinyin ＋ 多音字覆写表 ＋ `ABBR_MAX_LEN`），
# 折形真身＝`zhconv`——本件只引用、不另实现（另实现＝第二真身，正是这一波在治的病）。
#
# 三把尺都走「纯函数返回 problems 清单 ⇒ 断言清单为空」的形状，注毒腿因此可以只改
# **一张内存副本**就把牙验出来（下面 ⑥），不必去动盘上的生产件。
# ══════════════════════════════════════════════════════════════════════════

#: 合成余文：不是任何一族的词头，免得判据被「第二枚 token 也被归一」这件事污染。
_REST = "zz qq"
_SIMPLIFIED_LOCALE = "zh-cn"
_TRADITIONAL_LOCALE = "zh-tw"


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _ascii_faces(table: dict[str, str]) -> list[str]:
    """大小写轴的判域＝表内全部 ASCII **键** ∪ 全部**正形**（值）。"""
    return sorted({k for k in table if not _has_cjk(k)} | set(table.values()))


def _cjk_heads(table: dict[str, str]) -> list[str]:
    return sorted(k for k in table if _has_cjk(k))


# ---------------------------------------------------------------- 轴 1 大小写


def case_fold_problems(table: dict[str, str]) -> list[str]:
    """每一枚 ASCII 词面的 lower/upper/capitalize/title/swapcase 必须折到**同一**正形。

    机理真身在 `normalize_command_text`（查表前对 `parts[0]` 做 `.lower()`），所以这一轴
    天然同级——本腿判的是「它今天确实同级」且「以后有人往表里塞一枚大写键把它顶坏时当场红」。
    """
    problems: list[str] = []
    for face in _ascii_faces(table):
        expected = table.get(face.lower(), face.lower())
        for variant in (face.lower(), face.upper(), face.capitalize(), face.title(), face.swapcase()):
            if normalize_command_text(f"{variant} {_REST}") != f"{expected} {_REST}":
                problems.append(
                    f"{variant} 折出的不是 {expected}（判域 {face}）"
                )
    return problems


def uppercase_head_faces(table: dict[str, str]) -> list[str]:
    """表里的 ASCII 键必须一律存小写正形。

    为什么单独立一条：查表前已经 `.lower()` ⇒ **一枚大写键永远查不到**＝死格（写了等于没写，
    而「词面只住这一格」的纪律会以为它已经入表）。这一条比 case_fold 更狠：它抓的是
    「键的面本身不再是正形」，那种形不同在 case_fold 里会被 `.lower()` 兜成绿。
    """
    return sorted(k for k in table if not _has_cjk(k) and k != k.lower())


def test_case_axis_upper_and_lower_are_same_rank() -> None:
    assert not case_fold_problems(MODULE_ALIASES), "；".join(case_fold_problems(MODULE_ALIASES))


def test_case_axis_judgment_domain_is_not_empty() -> None:
    """尺读空先报警：判域一个 ASCII 词面都没有＝表搬家了，本腿不许静默绿。"""
    assert _ascii_faces(MODULE_ALIASES), "MODULE_ALIASES 里连一枚 ASCII 词面都取不到 ⇒ 判据失效"
    assert {"music", "MUSIC", "Diange", "DIANGE"} <= {
        v for face in _ascii_faces(MODULE_ALIASES) for v in (face.lower(), face.upper(), face.capitalize())
    }, "大小写判域没够到 `/bot MUSIC`／`/bot Diange` 这两族形"


def test_case_axis_head_faces_are_stored_lowercase() -> None:
    assert not uppercase_head_faces(MODULE_ALIASES), (
        f"表里出现非小写 ASCII 键 {uppercase_head_faces(MODULE_ALIASES)} ⇒ 查表前 .lower() "
        "让它永不被命中＝死格"
    )


# ---------------------------------------------------------------- 轴 2 简繁


def traditional_pair_of(head: str) -> str | None:
    """简体词头的繁體形（zhconv 现算）。返回 None＝该形简繁同形或折形不可逆（**不判**）。

    不可逆一律跳过是刻意的：`zh-cn → zh-tw` 是一对多（`日志→日誌`／`后→後`），硬派生会造出
    主人格上没要的繁体词头，还会把「同音不同字」当「同字不同繁」记债。宁缺毋滥。
    """
    if not _has_cjk(head):
        return None
    trad = _zhconvert(head, _TRADITIONAL_LOCALE)
    if trad == head:
        return None
    if _zhconvert(trad, _SIMPLIFIED_LOCALE) != head:
        return None
    return trad


def traditional_pairs(table: dict[str, str]) -> dict[str, str]:
    return {h: t for h in _cjk_heads(table) if (t := traditional_pair_of(h))}


def traditional_problems(table: dict[str, str]) -> list[str]:
    """正向（简体在册 ⇒ 繁體在册且同正形）＋ 反向（繁體在册 ⇒ 简体在册且同正形）双向闭合。"""
    problems: list[str] = []
    for simp, trad in sorted(traditional_pairs(table).items()):
        got = table.get(trad)
        if got is None:
            problems.append(f"{simp} 的繁體形 {trad} 不在册 ⇒ 简繁不同级")
        elif got != table[simp]:
            problems.append(f"{trad} 折到 {got}，与 {simp} 的正形 {table[simp]} 不同")
    for trad in _cjk_heads(table):
        simp = _zhconvert(trad, _SIMPLIFIED_LOCALE)
        if simp == trad or _zhconvert(simp, _TRADITIONAL_LOCALE) != trad:
            continue
        got = table.get(simp)
        if got is None:
            problems.append(f"繁體词头 {trad} 的简体形 {simp} 不在册")
        elif got != table[trad]:
            problems.append(f"{simp} 折到 {got}，与 {trad} 的正形 {table[trad]} 不同")
    return problems


def test_zhconv_actually_folds_and_the_probe_comes_from_the_table() -> None:
    """库可用性探针**不自造样本**：拿表内现派生的一枚简繁对验「它真的在折形」。

    zhconv 的静默陷阱是「locale 没注册 ⇒ 原样返回」（`content_safety` 为此专门立过探针），
    所以这里断的是「折得动」而不是「import 成功」。表里若一枚简繁对都没有，本腿当场红。
    """
    pairs = traditional_pairs(MODULE_ALIASES)
    assert pairs, "MODULE_ALIASES 里取不到任何简繁对 ⇒ 折形轴没有判域（尺瞎）"
    simp, trad = min(pairs.items())
    assert _zhconvert(trad, _SIMPLIFIED_LOCALE) == simp, (
        f"zhconv 没把 {trad} 折回 {simp}＝折形面在静默 no-op，本件的简繁判据全部失效"
    )


def test_traditional_axis_every_simplified_head_has_its_traditional_twin() -> None:
    problems = traditional_problems(MODULE_ALIASES)
    assert not problems, "；".join(problems)


def test_traditional_axis_pair_set_is_derived_not_hand_written() -> None:
    """配对清单必须能从表 + zhconv 现算派生（规则 10）：本腿把「派生结果」与「表内实际
    成对的简繁键」当成同一个集合来判——手写清单会在这里显形（派生集比手写集大或不同）。"""
    derived = {(s, t) for s, t in traditional_pairs(MODULE_ALIASES).items()}
    in_table = {
        (s, t)
        for t in _cjk_heads(MODULE_ALIASES)
        if (s := _zhconvert(t, _SIMPLIFIED_LOCALE)) in MODULE_ALIASES and s != t
    }
    assert derived == in_table, f"派生集与表内实际成对集不等：只在派生侧={sorted(derived - in_table)}"


# ---------------------------------------------------------------- 轴 3 拼音


def pinyin_face_targets(table: dict[str, str]) -> dict[str, set[str]]:
    """中文词头 → {全拼, 缩写} 的 token→正形集（读音一律现问 `gen_trigger_pinyin`）。"""
    by_token: dict[str, set[str]] = {}
    for head in _cjk_heads(table):
        entry = gp.build_entry(head, {"MODULE_ALIASES"})
        for token in (str(entry["full"]), str(entry["abbr"])):
            if token:
                by_token.setdefault(token, set()).add(table[head])
    return by_token


def ambiguous_pinyin_tokens(table: dict[str, str]) -> set[str]:
    """同一 token 指向 ≥2 枚正形＝歧义形，按裁定**一枚都不许入表**。"""
    return {t for t, targets in pinyin_face_targets(table).items() if len(targets) > 1}


def pinyin_problems(
    table: dict[str, str], withheld: dict[str, str] | None = None
) -> list[str]:
    """拼音轴的账：无冲突形必须在册**或**在缺席册里留了名，歧义形两边都不许在正册。

    `withheld`＝`MODULE_ALIASES` 同格的 `PINYIN_FORMS_WITHHELD`（申报缺席册）。为什么要有
    这一手：本波的裁是「缩写也要同级」，但项目里已经钉着几条**在册裁定**把某些缩写否了
    （台账 #27★ 的「永不启用」、规格九形态行的 `慎`/`不建议→—`、divination 的「真冲突缩写
    不启用」）。缺席不留名 ⇒ 判据要么把好形一起拖红、要么被读成「这活还没干」；留名才可反查。
    """
    absent = dict(withheld or {})
    problems: list[str] = []
    for token, targets in sorted(pinyin_face_targets(table).items()):
        if len(targets) > 1:
            if token in table:
                problems.append(f"歧义拼音形 {token} 却在正册（它指向 {sorted(targets)} 两枚正形）")
            continue
        want = next(iter(targets))
        if token in table and table[token] != want:
            problems.append(f"拼音形 {token} 折到 {table[token]}，应为 {want}")
        if token not in table and token not in absent:
            problems.append(f"无冲突拼音形 {token}（正形 {want}）既不在册、也没申报缺席 ⇒ 悄悄缩水")
    for token in absent:
        if token in table:
            problems.append(f"缺席册里的 {token} 又进了正册＝两本账同时在场")
    return problems


def test_pinyin_axis_full_pinyin_and_abbr_fold_to_one_canonical() -> None:
    problems = pinyin_problems(MODULE_ALIASES, PINYIN_FORMS_WITHHELD)
    assert not problems, "；".join(problems)


def test_pinyin_axis_ambiguity_leg_has_a_real_victim() -> None:
    """「有歧义所以刻意没入表」必须是真的有受害者：歧义集为空＝这条判据在空转。"""
    victims = ambiguous_pinyin_tokens(MODULE_ALIASES)
    assert victims, "拼音歧义集为空 ⇒ 撞车门在空转（要么表里全是撞车形，要么词头面搬家了）"
    for token in sorted(victims):
        assert token not in MODULE_ALIASES, f"歧义缩写 {token} 被塞进表里了"


#: 缺席册的原因必须**指向一条在册裁定**，否则「申报缺席」就成了想少加就少加的挡箭牌。
#: 判语口径取自 `docs/design/v21r2-command-spec-entries-1.md` 头注（未标注＝既有原样归位／
#: `建议`＝待评审／`慎`＝日常语义高危／`不建议`·`—`＝过生僻诚实缺位／`禁`·`永不启用`＝撞台账
#: #27 清单），外加 `domains/divination/capabilities/divination.py:107` 的「真冲突缩写不启用」
#: 与「表内同一缩写指向两枚正形」这一条。
_WITHHELD_REASON_MARKERS = (
    "永不启用", "不建议", "真冲突", "慎", "观察", "歧义", "两枚正形", "撞缩写",
)


def test_withheld_pinyin_registry_is_real_and_explainable() -> None:
    """缺席册三条同时判：①每枚确实是某枚中文词头机械折出来的拼音形（不是随手挖的洞）；
    ②每枚真的不在正册；③原因点得到在册判语或点名了撞的是谁。"""
    derived = set(pinyin_face_targets(MODULE_ALIASES))
    assert PINYIN_FORMS_WITHHELD, "缺席册为空 ⇒ 拼音轴的每一次「没加」都没留名"
    for token, reason in sorted(PINYIN_FORMS_WITHHELD.items()):
        assert token in derived, f"缺席册登记了 {token}，但它不是任何中文词头折出的拼音形＝凭空造洞"
        assert token not in MODULE_ALIASES, f"缺席册里的 {token} 其实已在正册＝两本账同时在场"
        assert str(reason).strip(), f"{token} 的缺席原因是空白"
        assert any(m in reason for m in _WITHHELD_REASON_MARKERS), (
            f"{token} 的原因没引用任何在册判语/撞车对象：{reason}"
        )


def test_withheld_and_ambiguous_forms_stay_unrouted() -> None:
    """被否掉的拼音形（在册裁定否掉的缩写＋表内歧义形）逐枚现问归一口：绝不认它们。"""
    rest_head = _REST.split(maxsplit=1)
    for token in sorted(set(PINYIN_FORMS_WITHHELD) | ambiguous_pinyin_tokens(MODULE_ALIASES)):
        for variant in (token, token.upper(), token.capitalize()):
            got = normalize_command_text(f"{variant} {_REST}")
            assert got == " ".join([variant.lower(), *rest_head]), (
                f"{variant} 被归一成 {got}，但它按在册裁定/表内歧义刻意没入表"
            )


@pytest.mark.parametrize("text", ["song 晴天", "亲密 scene", "区縣 浙江"])
def test_unregistered_neighbour_faces_stay_unrouted(text: str) -> None:
    """三枚**表外**近形不许被吞：`song`＝帮助册点歌条目里的英文别名，命令面从未裁过这枚词头
    （补它属扩功能、不属三轴同级）；`亲密`＝开关面至今没有中文词头；`区縣`＝半简半繁混写，
    表里只有纯简/纯繁两形——本轴的同级是「简↔繁」，不是「任意混写」。
    """
    head, rest = text.split(maxsplit=1)
    assert normalize_command_text(text) == f"{head.lower()} {rest}", f"{head} 被归一了，但它不在裁定范围内"


@pytest.mark.parametrize("token", sorted(pinyin_face_targets(MODULE_ALIASES)))
def test_pinyin_axis_token_reaches_its_own_canonical(token: str) -> None:
    """逐枚现问归一口：入表的全拼/缩写折到中文词头的同一正形（大小写两形一起验）；
    没入表的两类（表内歧义形、在册裁定否掉的缩写）反过来钉它**不被**归一。"""
    targets = pinyin_face_targets(MODULE_ALIASES)[token]
    if len(targets) > 1 or token in PINYIN_FORMS_WITHHELD:
        assert token not in MODULE_ALIASES, f"{token} 该缺席（歧义或在册裁定否掉），却进了正册"
        return
    want = next(iter(targets))
    for variant in (token, token.upper(), token.capitalize()):
        assert normalize_command_text(f"{variant} {_REST}") == f"{want} {_REST}"


# ---------------------------------------------------------------- ④ 派发实证


def accepted_root_heads() -> tuple[set[str], str]:
    """根链**真受理**的词头集（现算，禁靠「应该有」）：E1 字面分支 ∪ 落点册 ∪ 在册兜底形。"""
    from tests.test_claims_subset_implementation_gate import (
        dispatch_literals,
        landing_evidence,
    )
    from tests.test_trigger_bidirectional_gate import _registered_fallback_forms

    _full, heads = dispatch_literals()
    return (
        set(heads) | set(landing_evidence()) | set(_registered_fallback_forms()),
        "E1 字面分支 ∪ landing_evidence ∪ 兜底形白名单",
    )


def new_axis_faces(table: dict[str, str]) -> list[str]:
    """本波新入表的两族词头：拼音形（无冲突全拼/缩写）＋ 繁體形——全部现派生，不手写。"""
    faces = {t for t in pinyin_face_targets(table) if t in table and not _has_cjk(t)}
    faces |= set(traditional_pairs(table))
    return sorted(faces)


@pytest.mark.parametrize("face", new_axis_faces(MODULE_ALIASES))
def test_new_head_faces_land_on_a_real_root_branch(face: str) -> None:
    """新词头不许只把归一腿做绿：折出的正形必须在根链上有真落点。"""
    accepted, evidence = accepted_root_heads()
    canonical = normalize_command_text(f"{face} {_REST}").split(maxsplit=1)[0]
    assert canonical in accepted, (
        f"/bot {face} 归一到 {canonical}，但它不在根链受理集合（判据＝{evidence}）＝悬空宣称"
    )


def test_new_axis_faces_are_not_a_vacuous_set() -> None:
    faces = new_axis_faces(MODULE_ALIASES)
    assert len(faces) >= 3, f"本波新入表词头只现算出 {len(faces)} 枚 ⇒ 派发实证腿没够到实物"


# ---------------------------------------------------------------- ⑤ 三轴之外的邻面不吞


# ---------------------------------------------------------------- ⑥ 注毒自证


def _table_copy() -> dict[str, str]:
    return dict(MODULE_ALIASES)


def test_poison_fabricated_traditional_pair_is_caught() -> None:
    """注毒①：造一枚**假繁體配对**（把繁體形折到另一枚正形）⇒ 简繁尺必红。"""
    simp, trad = min(traditional_pairs(MODULE_ALIASES).items())
    poisoned = _table_copy()
    poisoned[trad] = "wiki" if poisoned[simp] != "wiki" else "model"
    assert traditional_problems(poisoned), "造假简繁配对没被抓＝这把尺是摆设"


def test_poison_dropped_traditional_form_is_caught() -> None:
    """注毒②：把一枚在册繁體形摘掉 ⇒ 简繁尺必红（正向缺配）。"""
    victims = sorted(
        trad
        for trad in _cjk_heads(MODULE_ALIASES)
        if (simp := _zhconvert(trad, _SIMPLIFIED_LOCALE)) != trad
        and simp in MODULE_ALIASES
        and _zhconvert(simp, _TRADITIONAL_LOCALE) == trad
    )
    assert victims, "注毒前提失效：表里没有繁體形可摘"
    poisoned = _table_copy()
    del poisoned[victims[0]]
    assert traditional_problems(poisoned), f"摘掉繁體形 {victims[0]} 没被抓＝这把尺是摆设"


def test_poison_ambiguous_pinyin_admitted_is_caught() -> None:
    """注毒③：把歧义缩写（现算出来的那一枚，不是手写名单）塞进正册 ⇒ 拼音尺必红。"""
    token = min(ambiguous_pinyin_tokens(MODULE_ALIASES))
    poisoned = _table_copy()
    poisoned[token] = min(pinyin_face_targets(MODULE_ALIASES)[token])
    assert pinyin_problems(poisoned, PINYIN_FORMS_WITHHELD), (
        f"歧义拼音形 {token} 入表没被抓＝撞车门是摆设"
    )


def test_poison_dropped_pinyin_form_is_caught() -> None:
    """注毒④：摘掉一枚在册拼音形、又不在缺席册里留名 ⇒ 拼音尺必红（轴不许悄悄缩回去）。"""
    keepers = sorted(
        t for t, targets in pinyin_face_targets(MODULE_ALIASES).items()
        if len(targets) == 1 and t in MODULE_ALIASES
    )
    assert keepers, "注毒前提失效：表里没有无冲突拼音形"
    poisoned = _table_copy()
    del poisoned[keepers[0]]
    assert pinyin_problems(poisoned, PINYIN_FORMS_WITHHELD), (
        f"摘掉拼音形 {keepers[0]} 没被抓＝这把尺是摆设"
    )


def test_poison_silent_absence_is_caught() -> None:
    """注毒④b（缺席册的另一半牙）：一枚在册拼音形被摘掉、缺席册也没登记 ⇒ 必红；
    反过来，只在缺席册留名 ⇒ 放行。这条判的是「申报缺席」到底是不是空话。"""
    token = next(
        t for t, targets in pinyin_face_targets(MODULE_ALIASES).items()
        if len(targets) == 1 and t in MODULE_ALIASES
    )
    unreported = _table_copy()
    del unreported[token]
    assert pinyin_problems(unreported, {}), f"悄悄摘掉 {token} 且不留名，尺却没红＝申报缺席这半边没牙"
    reported = _table_copy()
    del reported[token]
    assert not pinyin_problems(
        reported, {**PINYIN_FORMS_WITHHELD, token: "注毒样本：在册裁定把这一枚否掉了"}
    ), "留了名还被判红＝缺席册没被读，正册与缺席册变成互相打架的两把尺"


def test_poison_uppercase_head_key_is_caught() -> None:
    """注毒⑤：往表里塞一枚只靠大小写区分的键 ⇒ 死格尺必红。"""
    face = next(k for k in _ascii_faces(MODULE_ALIASES) if k == k.lower() and k.isascii())
    poisoned = _table_copy()
    poisoned[face.upper()] = poisoned.get(face, face)
    assert uppercase_head_faces(poisoned), f"大写键 {face.upper()} 没被抓＝正形书写纪律是摆设"


def test_poison_case_sensitive_lookup_is_caught() -> None:
    """注毒⑥：把「查表前 .lower()」这一步的产物当第二正形用——同一枚 ASCII 键改指另一枚正形，
    大小写尺必须红（否则「大写小写同级」其实没人判）。"""
    face = next(k for k in _ascii_faces(MODULE_ALIASES) if k in MODULE_ALIASES)
    other = next(v for v in set(MODULE_ALIASES.values()) if v != MODULE_ALIASES[face])
    poisoned = _table_copy()
    poisoned[face] = other
    assert case_fold_problems(poisoned), f"{face} 改指 {other} 没被抓＝大小写轴是摆设"

