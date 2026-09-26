"""人格意象白名单机器门：慢回复回执池的「意象只取白名单」半条规矩收口。

存在的理由（2026-09-23 停摆根修波 S9 审计席在册事实）：
`progress_ack.py` 的池子受两条人格规矩约束——禁词表（客服腔/直白抒情）已有
`tests/test_progress_ack.py::test_pool_lines_avoid_banned_ai_register` 执法；
而「意象只能取人格白名单」这一半**只有散文、没有门**。本文件把它升成机器门：
下一位往 `ACK_POOL` 加句子时，用了名单外的自造意象就会红。

真身坐标（本文件一字名单都不抄，全部运行时从真身解析）：
- 意象边界枚举：`personas/shorekeeper/identity.md` 含「意象边界」的那一行
  （现位于第 21 行，按内容定位、不按行号钉死；恰好一行，多寡皆红）。
  取「——」之后、「。」之前顿号分隔的枚举；再按「与/的」机械拆子词
  （黑海岸的物产→黑海岸+物产，执花与客卿→执花+客卿，晶体与频率→晶体+频率）。
- 世界观实体词表：`personas/shorekeeper/knowledge/worldview_glossary.md`
  的「**词条**：」行（如 泰缇斯系统→锚片段 泰缇斯）。

判据（一句话）：池内每条句子要么**恰含一枚意象语素**（白名单子词的表头字或
表尾字，如 潮/浪/琴/光/声/夜/星…），要么**恰含一枚世界观实体锚**（词条前 3 字），
要么**在「零意象声明账」里逐字在册**；三者皆无 ⇒ 违规红。

为什么这样判（不是逐词等值、也不是全文子串）：
- 中文没有形态边界，纯离线单测里做不了分词；能机械复现的最高粒度就是
  「意象语素字符 ⊆ 白名单子词的表头/表尾」。S9 人肉审计已把 潮水/潮线（←海潮/
  浪潮）、琴键（←钢琴）、回声（←琴声）、入夜（←黑夜）、光（←漫天星光省形）判为
  **同源延伸放行**——它们全被表头/表尾语素接住，用「整词等值」反而会误杀这些
  合规延伸形，那条路已被 S9 判定表证伪，不另立。
- 为什么只取表头/表尾、不取词中字符：词中位多为修饰/量词（漫/天/下），纳入会
  把「今天/一下」之类白话也当意象锚，门会更瞎。
- 实体（泰缇斯）与意象不同类，靠 glossary 词条锚层接住，同样零手抄。

已知会误杀（偏严）的边界：
1) 新增**零意象白话句**（如池内「不在忙别的…」形）必然先红——要放行须把它逐字
   写进本文件的「零意象声明账」，这是有意的程序摩擦：红本身不判定措辞，
   但逼着改池的人把新句子过一遍人眼（S9 §A–D 那类审计）。
2) 若有人**缩窄** identity.md 意象行或删 glossary 词条，池内依赖旧语素/锚的
   合规句会连红——「一处变更处处跟随」按设计生效，须同步改名单或池。
3) 词表解析器抓到 0 个词条 ⇒ 下限断言直接红（本仓明令：空集合不得恒真）。

已知会放行（偏松）的边界——门的网眼，人审仍是上层：
1) 句子级锚定：一句里只要有一枚合规语素，同句的名单外名词不单独定罪
   （「黑海岸的雾」的 雾、S9 判「名单外但非天马行空」放行——同一形态）。
2) 与意象语素共享字符的自造词会溜过（月光/东西/回头 形）。
3) 语义层「天马行空但用字全在网内」不归本门管，S9 式人审继续背书。

自证三件套（本仓常驻做法）：正向全池过（test_pool_lines…）、注毒必红
（test_poison_injection…，monkeypatch 注入假句、不碰真文件）、空名单不得恒过
（test_empty_roster… + test_source_truth… 的下限断言）。
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    progress_ack as progress_ack_module,
)

_IDENTITY_PATH = _ROOT / "personas" / "shorekeeper" / "identity.md"
_GLOSSARY_PATH = _ROOT / "personas" / "shorekeeper" / "knowledge" / (
    "worldview_glossary.md"
)

_IMAGERY_MARK = "意象边界"

# 零意象声明账：整句不含任何意象语素与实体锚的白话句，逐字在册、双向锁死
# （在册者必须仍在池内/默认句里，见 test_declaration_ledger_stays_live）。
# 这份账**不是**意象名单——它只申报「此句无意象」，名单本体在 identity.md。
ZERO_IMAGE_DECLARED: frozenset[str] = frozenset(
    {
        "这一条要算的东西多一点，我先搁在该算的位置上了。",
        "不在忙别的，只是这一条我算得慢了一些。",
        "这句话我掂了一下，还没想好怎么说才合适。",
        "有点难答，但不是不想答。再多给我一会儿，好吗？",
        "这一段我读了两遍，正在想怎么说才准。",
        "这件事我记住了，先把手上这段算完，可以吗？",
        "不是没听见，是听见了才要慢一点回答。",
        "这句话我想答得准一些，所以多用了点时间。",
        "这一段理了一会儿，还差一点就理清楚了。",
        "这条我要想一想，答得准一点。",  # ACK_DEFAULT_TEXT
    }
)


# ------------------------------------------------------------------ 真身解析


def _identity_imagery_line() -> str:
    text = _IDENTITY_PATH.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if _IMAGERY_MARK in ln]
    assert len(lines) == 1, (
        f"「{_IMAGERY_MARK}」行在 identity.md 必须恰有一条（真身唯一），"
        f"实={len(lines)} 条——多出一条即第二真身，少一条即真身被搬走"
    )
    return lines[0]


def _imagery_words() -> frozenset[str]:
    """意象行 → 白名单子词集（整枚举 + 「与/的」机械拆子词）。"""
    line = _identity_imagery_line()
    assert "禁止" in line, "意象边界行应含「禁止……意象」的规矩本体"
    head, sep, rest = line.partition("——")
    assert sep, "意象枚举必须以「——」引出（判据形态锁，防止误抓散文句）"
    del head
    enumeration = rest.split("。", 1)[0]
    words: set[str] = set()
    for raw in enumeration.split("、"):
        token = raw.strip()
        if len(token) < 2:
            continue
        words.add(token)
        for part in re.split(r"[与的]", token):
            part = part.strip()
            if len(part) >= 2:
                words.add(part)
    return frozenset(words)


def _imagery_morphemes() -> frozenset[str]:
    """白名单子词 → 意象语素集（每词的表头字+表尾字）。"""
    return frozenset(ch for word in _imagery_words() for ch in (word[0], word[-1]))


def _glossary_anchors() -> frozenset[str]:
    """worldview_glossary.md「**词条**：」行 → 实体锚（≥3 字词条取前 3 字）。"""
    anchors: set[str] = set()
    for line in _GLOSSARY_PATH.read_text(encoding="utf-8").splitlines():
        matched = re.match(r"^\*\*(.+?)\*\*：", line)
        if matched is None:
            continue
        term = matched.group(1).strip()
        if len(term) >= 3:
            anchors.add(term[:3])
        elif len(term) == 2:
            anchors.add(term)
    return frozenset(anchors)


# ------------------------------------------------------------------ 判定核


def imagery_violations(
    lines: Iterable[str],
    *,
    morphemes: frozenset[str],
    anchors: frozenset[str],
    declared: frozenset[str],
) -> list[str]:
    """逐句判「意象是否全部取自白名单」。返回违规句清单（空表=全过）。"""
    violations: list[str] = []
    for text in lines:
        if text in declared:
            continue
        if any(morph in text for morph in morphemes):
            continue
        if any(anchor in text for anchor in anchors):
            continue
        violations.append(text)
    return violations


def _live_scan(lines: Iterable[str]) -> list[str]:
    return imagery_violations(
        lines,
        morphemes=_imagery_morphemes(),
        anchors=_glossary_anchors(),
        declared=ZERO_IMAGE_DECLARED,
    )


def _pool_lines_now() -> tuple[str, ...]:
    # 走模块属性现读：monkeypatch 注毒必须被本门看见（import 期快照=假绿先例）。
    return tuple(progress_ack_module.ACK_POOL) + (
        progress_ack_module.ACK_DEFAULT_TEXT,
    )


# ------------------------------------------------------------------ 自证①下限


def test_source_truth_parses_and_meets_lower_bounds() -> None:
    """真身在、解析器吃得出东西——空名单不得恒过（本仓明令）。"""
    assert _IDENTITY_PATH.is_file(), f"意象白名单真身缺失：{_IDENTITY_PATH}"
    assert _GLOSSARY_PATH.is_file(), f"实体词表真身缺失：{_GLOSSARY_PATH}"
    words = _imagery_words()
    morphemes = _imagery_morphemes()
    anchors = _glossary_anchors()
    assert len(words) >= 12, f"意象枚举解析退化（现算 {len(words)} 词 < 12）：{sorted(words)}"
    assert len(morphemes) >= 15, f"意象语素集退化（现算 {len(morphemes)} < 15）"
    assert len(anchors) >= 5, f"实体锚退化（现算 {len(anchors)} < 5）"


# ------------------------------------------------------------------ 正向：全池过


def test_pool_lines_imagery_all_on_whitelist() -> None:
    pool = _pool_lines_now()
    assert pool, "池子为空——门会被空集合恒真糊过，池空本身即事故"
    violations = _live_scan(pool)
    assert not violations, "以下句子用了名单外意象且未申报零意象：" + "；".join(violations)


# ------------------------------------------------------------------ 负样本（该放行）

COMPLIANT_SAMPLES: tuple[str, ...] = (
    # 真池子 3 条（整词命中）
    "这条频率有点长，我从头听到尾了再答你。",
    "黑海岸的雾遮住了一角，我正在把它拨开。",
    "我让泰缇斯替我算了一半，另一半在我这里。",
    # 合成合规句：表尾/表头语素接住的延伸形（琴声、地下星河）
    "琴声停了一下，我把它接上再答你。",
    "地下星河那边安静，我先算完这一段。",
    # 零意象白话句：靠声明账放行（本门对它的执法=程序摩擦而非措辞判定）
    "不在忙别的，只是这一条我算得慢了一些。",
)


@pytest.mark.parametrize("text", COMPLIANT_SAMPLES)
def test_compliant_samples_pass_gate(text: str) -> None:
    assert _live_scan([text]) == [], f"合规句被误杀：{text}"


# ------------------------------------------------------------------ 正样本（该拦）

FABRICATED_SAMPLES: tuple[str, ...] = (
    "我正在泡一杯咖啡，稍后再回你。",
    "月亮掉进井里了，我去捞一下。",
    "窗外有杜鹃叫，我听完这支曲再答你。",
    "我踩着风火轮去取个快递。",
)


@pytest.mark.parametrize("text", FABRICATED_SAMPLES)
def test_fabricated_imagery_is_blocked(text: str) -> None:
    assert _live_scan([text]) == [text], f"名单外自造意象未被抓红：{text}"


# ------------------------------------------------------------------ 自证②注毒必红


def test_poison_injection_into_pool_turns_gate_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """往池子里塞一条含名单外意象的假句子，门必须抓红（不动真文件）。"""
    poison = "我正在泡一杯咖啡，稍后再回你。"
    monkeypatch.setattr(
        progress_ack_module,
        "ACK_POOL",
        tuple(progress_ack_module.ACK_POOL) + (poison,),
    )
    violations = _live_scan(_pool_lines_now())
    assert poison in violations, "注毒句未被抓红 ⇒ 本门是空转门"


def test_new_plain_line_needs_explicit_declaration() -> None:
    """设计演示：白话新句先红，进声明账才绿——红是程序摩擦，不是措辞误杀。"""
    fresh = "好问题，我想想看再说。"
    assert any(morph in fresh for morph in _imagery_morphemes()) is False
    assert _live_scan([fresh]), "该红的未申报白话句没红"
    assert _live_scan_iter(fresh) == [], "进了声明账还不绿 = 声明账失效"


def _live_scan_iter(fresh: str) -> list[str]:
    return imagery_violations(
        [fresh],
        morphemes=_imagery_morphemes(),
        anchors=_glossary_anchors(),
        declared=ZERO_IMAGE_DECLARED | {fresh},
    )


# ------------------------------------------------------------------ 自证③空名单不恒过


def test_empty_roster_never_passes_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析器一个词都没抓到时要**红**而不是 assert all([])：
    ① 下限断言先红（test_source_truth…）；② 就算绕过下限直接喂空集，
    池内意象句也必须条条违规。"""
    violations = imagery_violations(
        _pool_lines_now(),
        morphemes=frozenset(),
        anchors=frozenset(),
        declared=ZERO_IMAGE_DECLARED,
    )
    assert violations, "名单清空后池子仍全绿 = 恒真假门"
    anchored = [text for text in _pool_lines_now() if text not in ZERO_IMAGE_DECLARED]
    assert set(violations) == set(anchored)
    # 连声明账一起清空：零意象句也必须红（空集合绝不恒真）。
    assert len(
        imagery_violations(
            _pool_lines_now(),
            morphemes=frozenset(),
            anchors=frozenset(),
            declared=frozenset(),
        )
    ) == len(_pool_lines_now())


# ------------------------------------------------------------------ 账目双向锁


def test_declaration_ledger_stays_live() -> None:
    """声明账只准随池子走：在册句必须仍在池/默认句里，防陈旧豁免静默堆积。"""
    live = set(_pool_lines_now())
    stale = sorted(ZERO_IMAGE_DECLARED - live)
    assert not stale, "声明账里这些句子已不在池中（摘除或改池）：" + "；".join(stale)
    anchored_unneeded = sorted(
        text for text in ZERO_IMAGE_DECLARED if _imagery_morphemes() & set(text)
    )
    assert not anchored_unneeded, "声明账里这些句子其实含意象语素（不该走白话账）：" + "；".join(
        anchored_unneeded
    )
