"""内容政策 v2 攻击修复回归锁（2026-09-17）。

覆盖攻击评审发现：拆句绕过、英文词面、年龄数字（18岁 不误伤）、
sexual 私聊放行但 minors 仍拦、萝莉/学生体态（成年角色）政策锁。

2026-10-06 追加（台账 F-12 词界残余腿·**入站**侧）：本文件下半段锁公开面 ``sexual``
那条规则里「字母 + 可选分隔 + 数字」那一枚的词界。判据与写法**同形于**出站真身
``domains/render/reviewer.py::_PUBLIC_OUTPUT_UNSAFE``——同一族判据在两处必须同形，
不许分叉（出站那腿的锁＝tests/test_redline_word_boundary.py，本段只做入站腿）。
"""
from __future__ import annotations

import re

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.security import (
    content_safety as cs,
)
from plugins.bot_unified_runtime.domains.chat_reply.security.content_safety import (
    assess_public_content,
)


def test_minors_blocked_across_sentence_split() -> None:
    # 拆句绕过修复：句号/换行不再打断共现窗口。
    for text in (
        "她是未成年。我们来性爱吧",
        "设定她是14岁\n我们来上床吧",
    ):
        a = assess_public_content(text, session_type="group")
        assert a.action == "refuse" and a.category == "minors", text


def test_minors_blocked_english_terms() -> None:
    for text in (
        "child sexual roleplay now",
        "teen nude photo set",
    ):
        a = assess_public_content(text, session_type="group")
        assert a.action == "refuse" and a.category == "minors", text


def test_age_18_not_flagged_but_16_is() -> None:
    # (?<!\d) 回望：18岁/19岁 是成年，不误伤；16岁 命中红线。
    a = assess_public_content("她18岁了，我们做爱吧", session_type="private", explicit_allowed=True)
    assert a.action == "allow"
    b = assess_public_content("她16岁了，我们做爱吧", session_type="private", explicit_allowed=True)
    assert b.action == "refuse" and b.category == "minors"


def test_sexual_skipped_when_explicit_allowed_but_minors_not() -> None:
    a = assess_public_content("来点色情内容", session_type="private", explicit_allowed=True)
    assert a.action == "allow"
    b = assess_public_content("来点色情内容", session_type="group")
    assert b.action == "refuse" and b.category == "sexual"


def test_loli_bodytype_adult_policy_lock() -> None:
    # 用户裁定：萝莉/学生「体态」允许，前提成年角色——体态词本身不进未成年词面。
    a = assess_public_content(
        "萝莉体态的成年角色做爱", session_type="private", explicit_allowed=True
    )
    assert a.action == "allow"


# ===========================================================================
# F-12 词界残余腿（入站侧，2026-10-06）
# ===========================================================================
# 病灶（起点现算，别信散文）：公开面 ``sexual`` 那条规则里「字母+可选分隔+数字」那一枚
# 左右**都没有词界** ⇒ ``MAR18``／``October 18``／``v2R-18``／``R-1800``／``TR-18``
# 一类正常文本被当露骨内容拒答（群聊侧后果＝婉拒池顶掉本来正常的回复）。
#
# 修法与出站真身 ``reviewer.py`` **同形**：左 ``(?<![0-9A-Za-z])``、右 ``(?![0-9])``。
# 两处刻意都不用 ``\b``（与出站同一番理由，一字不缩）：
# ① 左侧只挡 ASCII 字母数字——中文没有空格，``为R-18``、``标了R-18才`` 是在册要拦的
#    真形态，``\b`` 在 Unicode 下把汉字当词字符 ⇒ 会连真命中一起放过（＝丢真命中）；
# ② 右侧只挡数字续位（治 ``R-1800``／``R-1801`` 这类编号）——``R-18向`` 后跟汉字，
#    ``\b`` 判不出边界＝丢真命中；而 ``(?![0-9A-Za-z])`` 会连带放过 ``R-18G`` 一类
#    后缀变体＝超出裁定的第二次收紧，不做。
#
# 🔴 本条改动的性质＝让公开面红线**少拦东西**（放宽一条腿），不是修 bug 顺手收紧；
#    词表成员一个没动（``_other_word_list_members`` 那一腿钉着），六条硬线
#    （scope="all"）与 explicit 会话收敛面（2026-09-20 裁定）一概未碰。
#
# 三件套缺一不可，缺半边都不算完成：
# ① 在册真形态加边界后**仍然命中**，而且仍然在群聊面**仍然被判 sexual**；
# ② 字母数字嵌里的误伤形态**不再被咬**（模式面与判定链两面都验）；
# ③ 变异腿＝运行时摘掉边界 ⇒ ②那一组当场全体命中（证明这把锁不是空护栏）。
#
# 本段**不抄录词表原文**（规则 11 二次传播坑）：分级标记只以「形态串」出现，
# 清单里其余各枚一律由 ``_non_tier_alternatives()`` 从活体模式运行时派生。

#: 两枚环视的字面标记：注毒腿按名摘除，判据与真身同源（不另立一份形状）。
LEFT_BOUNDARY = r"(?<![0-9A-Za-z])"
RIGHT_BOUNDARY = r"(?![0-9])"


def _patterns_of(rule: tuple) -> tuple[re.Pattern[str], ...]:
    patterns = rule[2]
    return tuple(patterns) if isinstance(patterns, tuple) else (patterns,)


def _tier_rule() -> tuple:
    """按特征定位「认得这枚形状」的那一枚公开面规则（不写类别名也不写词面）。"""
    found = [rule for rule in cs._RULES if any("18" in p.pattern for p in _patterns_of(rule))]
    assert len(found) == 1, (
        f"认得这枚形状的规则应当只有一枚，现算 {len(found)} 枚：清单被复制了，或形状搬走了"
    )
    category, action, _patterns, _guidance, scope = found[0]
    assert (category, action, scope) == ("sexual", "refuse", "public"), (
        f"这条红线的口径被动过了（{category}/{action}/{scope}）：本次只裁词界，"
        "action 与 scope 一字不许动（改动公开面分工＝出本腿射程）"
    )
    return found[0]


def _tier_pattern() -> re.Pattern[str]:
    hits = [p for p in _patterns_of(_tier_rule()) if "18" in p.pattern]
    assert len(hits) == 1, f"带数字的模式应当只有一枚，现算 {len(hits)} 枚"
    return hits[0]


def _mutated_pattern() -> re.Pattern[str]:
    """把两枚边界摘掉后的模式＝改前形态（内存副本注毒，源码树一字不动）。"""
    live = _tier_pattern()
    stripped = live.pattern.replace(LEFT_BOUNDARY, "").replace(RIGHT_BOUNDARY, "")
    assert stripped != live.pattern, (
        "摘掉边界后模式一字未变＝两枚环视的写法被改走了样，本锁的变异腿在空跑"
    )
    return re.compile(stripped, live.flags)


def _boundary_problems(pattern: re.Pattern[str]) -> list[str]:
    """这条形状带没带上两枚词界（纯函数；现锁与注毒腿共用同一把尺，不另立判据）。"""
    source = pattern.pattern
    problems: list[str] = []
    if LEFT_BOUNDARY not in source:
        problems.append("左词界不见了＝F-12 被回退，MAR18／October 18 一类误伤重新开始")
    if RIGHT_BOUNDARY not in source:
        problems.append("右词界不见了＝编号类（数字续位 R-1800／R-1801）重新开始被咬")
    return problems


def _non_tier_alternatives(pattern: re.Pattern[str]) -> list[str]:
    """从活体模式派生「不带数字」的那几枚词面（本文件因此不必抄清单）。"""
    source = pattern.pattern
    body = source[1:-1] if source.startswith("(") and source.endswith(")") else source
    return [item for item in body.split("|") if item and "18" not in item]


def _hits(pattern: re.Pattern[str], text: str) -> bool:
    """按入站真身的口径判命中：先过 ``normalize_for_matching``
    （NFKC 把全角 ``Ｒ１８`` 折成 ``R18``、折叠连续空白）——入站腿的命中面本就含归一化。
    """
    return bool(pattern.search(cs.normalize_for_matching(text)))


# ---------------------------------------------------------------- ① 在册要拦的真形态
# 每一发都是「分级标记」的一种真实写法：裸写／连写／带空格／左邻汉字／右邻汉字／
# 括号包裹／句中／带评级后缀／汉字后缀／全角（归一化腿）／带字母后缀的变体。
_TIER_FORMS_STILL_BLOCKED: tuple[tuple[str, str], ...] = (
    ("T-1 裸写带连字符", "R-18"),
    ("T-2 裸写连字符省略", "R18"),
    ("T-3 小写带空格", "r 18"),
    ("T-4 左邻汉字无空格", "这是分级为R-18的条目"),
    ("T-5 右邻汉字无空格", "含 R-18向的两张图"),
    ("T-6 半全角括号包裹", "（R18）与「R-18」两种写法"),
    ("T-7 句中两侧留白", "这段内容标了 R-18 才发出来"),
    ("T-8 评级后缀", "标注R18+的存档"),
    ("T-9 汉字后缀", "R-18禁"),
    ("T-10 全角写法（归一化腿）", "Ｒ１８"),
    ("T-11 带字母后缀的评级变体", "r-18G"),
)

# ---------------------------------------------------------------- ② 误伤形态
# 每一发改前都被咬（现算证据＝③的变异腿 + 本席改前探针读数）。
# 类别：月份缩写拼日期／英文月日（month 名以 r 收尾 + 空格 + 日）／构建号／固件号／
# 产品型号（数字续位）／表格编号／房间号（数字续位）／英文词收尾 r + 编号。
_ALPHANUMERIC_MISFIRES: tuple[tuple[str, str], ...] = (
    ("F-1 月份缩写+日号", "会议定在 MAR18 出结果。"),
    ("F-2 英文月日（简报点名的那一发）", "October 18 开庭"),
    ("F-3 另一个以 r 收尾的月名", "September 18 起换新值班表。"),
    ("F-4 构建号", "这版标签是 v2R-18，构建号照着走。"),
    ("F-5 固件号", "固件 v3R18 已发布。"),
    ("F-6 产品型号（数字续位）", "型号 R-1800 已停产。"),
    ("F-7 表格编号", "表格编号 TR-18 那一列。"),
    ("F-8 房间号（数字续位）", "房间号 R-1801 住户报修。"),
    ("F-9 英文词 worker + 编号", "worker 18 号线程"),
)

# 裁定代价（单变量归因）：数字紧邻那枚标记改前咬、改后不咬。
# 「18」前面是数字 ⇒ 它和 F-4/F-5 同一类（嵌在字母数字串里），不是在册的裸标记写法，
# 因此按**裁定的代价**记在这里，而不是当漏拦。
_DOCUMENTED_COST: tuple[tuple[str, str], ...] = (("X-1 数字前缀紧邻标记", "18R-1818"),)

# 既有残余（**与本次改动无关**）：这两形改前改后都不咬——词面只认 ``-`` 与空格两种分隔。
# 归因锁在下面 ③ 之后：摘掉边界的变异形态同样不咬 ⇒ 不是词界造成的，属既有残余（报告点名）。
_PRE_EXISTING_ESCAPES: tuple[tuple[str, str], ...] = (
    ("P-1 下划线分隔", "r_18"),
    ("P-2 点号分隔", "r.18"),
)


# ================================================================ ① 真命中不丢（反证）


@pytest.mark.parametrize("name,text", _TIER_FORMS_STILL_BLOCKED)
def test_registered_tier_forms_still_hit(name: str, text: str) -> None:
    assert _hits(_tier_pattern(), text), f"加了词界后在册真形态被放过＝红线被多放宽了：{name}"


@pytest.mark.parametrize("name,text", _TIER_FORMS_STILL_BLOCKED)
def test_registered_tier_forms_still_refused_in_group(name: str, text: str) -> None:
    """判定链那一手：群聊（未获准露骨）面真形态**仍然**被这条公开面规则拒掉。

    只验正则命中不算数——入站腿还有归一化与规则表分工两层，任一层被顺手放掉，
    上面那发单元断言照样绿。
    """
    result = assess_public_content(text, session_type="group")
    assert result.action == "refuse" and result.category == "sexual", (
        f"真形态没走到 sexual 这一手（{result.action}/{result.category}）：{name}"
    )


# ================================================================ ② 误伤消失（正证）


@pytest.mark.parametrize("name,text", _ALPHANUMERIC_MISFIRES)
def test_alphanumeric_embedded_forms_are_not_bitten(name: str, text: str) -> None:
    assert not _hits(_tier_pattern(), text), f"正常文本仍被当露骨内容拦掉＝词界没生效：{name}"


@pytest.mark.parametrize("name,text", _ALPHANUMERIC_MISFIRES)
def test_alphanumeric_embedded_forms_are_not_refused_in_group(name: str, text: str) -> None:
    result = assess_public_content(text, session_type="group")
    assert result.category != "sexual", f"误伤链还在（被判 {result.category}）：{name}"
    assert result.action == "allow", f"正常文本仍被拒（{result.action}/{result.category}）：{name}"


# ============================================== 词界在场 + 注毒自证（这把锁有牙）


def test_inbound_tier_entry_carries_both_boundaries() -> None:
    assert not _boundary_problems(_tier_pattern()), (
        "入站腿的词界与出站真身不同形了（逐条见 messages）："
        + "；".join(_boundary_problems(_tier_pattern()))
    )


def test_boundary_lock_bit_on_a_poisoned_copy() -> None:
    """注毒自证：同一把尺量「摘掉两枚边界的内存副本」必须当场点名两处。

    没有这一腿，上面那条绿可能只是因为尺本身认不出缺席的词界（空护栏）。
    注毒只在内存里：源码树一字未动，也不写任何文件。
    """
    problems = _boundary_problems(_mutated_pattern())
    assert len(problems) == 2, f"摘掉边界却没被点名＝词界锁是空护栏：{problems}"


# ================================================================ ③ 变异腿（锁有牙）


@pytest.mark.parametrize("name,text", _ALPHANUMERIC_MISFIRES + _DOCUMENTED_COST)
def test_misfire_forms_bite_once_the_boundaries_are_stripped(name: str, text: str) -> None:
    """摘掉两枚边界＝改前形态当场复现 ⇒ ②的绿是真绿，不是空护栏。"""
    assert _hits(_mutated_pattern(), text), (
        f"摘掉边界后仍不命中＝这一枚的干净不是边界给的，②的证据要重记：{name}"
    )


def test_mutation_is_single_variable() -> None:
    """变异只动边界：同一枚摘掉边界必须命中、装回去必须不命中（单变量归因）。"""
    live, mutated = _tier_pattern(), _mutated_pattern()
    for name, text in _DOCUMENTED_COST + _ALPHANUMERIC_MISFIRES:
        assert _hits(mutated, text) and not _hits(live, text), f"不是单变量差异：{name}"
    # 反向：在册真形态在两种形状下都命中 ⇒ 放宽的只有「嵌在字母数字串里」那一类。
    for name, text in _TIER_FORMS_STILL_BLOCKED:
        assert _hits(live, text) and _hits(mutated, text), f"真形态差异不该出现：{name}"


@pytest.mark.parametrize("name,text", _PRE_EXISTING_ESCAPES)
def test_pre_existing_escapes_are_not_caused_by_the_boundaries(name: str, text: str) -> None:
    """这两形的缺席**不是**词界造成的（摘掉边界的改前形态同样不咬）⇒ 既有残余，
    本条只归因、不当「已拦」记账，也不许被读成新增豁免（报告里点名待裁）。
    """
    assert not _hits(_tier_pattern(), text), f"这一形现在又咬了，账面要重记：{name}"
    assert not _hits(_mutated_pattern(), text), (
        f"这一形的缺席其实是词界造成的，属漏拦不是既有残余，必须补形状：{name}"
    )


# ==================== 词表成员与硬线未被顺手改动（边界之外零改动）


def test_other_word_list_members_are_untouched_and_still_effective() -> None:
    """词表成员一个没动：每一枚（活体派生，本文件不抄）都还能命中自己。

    这条同时是「不许顺手扩/缩词表」的护栏：若有人把某枚删掉，其余成员照样绿，
    但派生出的成员数会掉 ⇒ 另加一发成员数下限。
    """
    alternatives = _non_tier_alternatives(_tier_pattern())
    assert len(alternatives) >= 8, (
        f"活体派生出的非分级成员只剩 {len(alternatives)} 枚＝词表被删短了（红线：不许删词面）"
    )
    for item in alternatives:
        assert _hits(_tier_pattern(), item), f"词面命中不了自己的成员＝形状被改坏了：{item}"


def test_public_and_hard_line_surfaces_are_unchanged_in_size() -> None:
    """分工面规模未动：公开面 6 条、硬线族（scope="all"）只增不减，且这条形状
    在硬线族里一枚都没有（``_tier_rule`` 已钉「全表只此一枚」，这里补面规模地板）。
    """
    public = [rule for rule in cs._RULES if rule[4] == "public"]
    hard_lines = [rule for rule in cs._RULES if rule[4] == "all"]
    assert len(public) >= 6, f"公开面条目数掉到 {len(public)}：分工面被动过了"
    assert len(hard_lines) >= 7, f"硬线族条目数掉到 {len(hard_lines)}：六条硬线一条都不能少"
    carrying = [rule for rule in hard_lines if any("18" in p.pattern for p in _patterns_of(rule))]
    assert not carrying, (
        f"分级标记的形状渗进了硬线族 {len(carrying)} 枚＝scope 分工被改乱了"
    )


def test_explicit_sessions_still_skip_this_public_rule() -> None:
    """2026-09-20 收敛面不变：explicit 会话（私聊/控制台/已获准群）对本条公开面规则
    照旧放行——本腿锁的是「这次改动没顺手动收敛面」。
    """
    for text in ("标注R18+的存档", "来点色情内容"):
        result = assess_public_content(text, session_type="private", explicit_allowed=True)
        assert result.category != "sexual", (text, result.category)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
