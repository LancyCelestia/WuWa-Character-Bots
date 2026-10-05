"""分级标记那枚形状的**词界**锁（台账 F-12，用户 2026-10-06 明示「改」）。

真身＝`domains/render/reviewer.py::_PUBLIC_OUTPUT_UNSAFE` 里带数字那枚条目中的
「字母 + 可选分隔 + 数字」形状。改前它左右都没有词界（起点现算，别信散文：
`test_misfire_forms_bite_once_the_boundaries_are_stripped` 在运行时把两枚环视摘掉，
就复现出改前那一手，不需要考古 git 历史）。

🔴 这条改动的性质＝**让红线少拦东西**（放宽一条红线腿），不是修 bug 顺手收紧；
用户 2026-10-06 回「改」＝知情批准。所以本文件两半都必须有牙，缺半边都不算完成：

① 在册要拦的真形态在加边界之后**仍然命中**，而且**仍然走得到涂销/审计那一手**
   （`_TIER_FORMS_STILL_BLOCKED` 11 发 + 真判据链那一腿）；
② 字母数字嵌里的误伤形态**不再被咬**（`_ALPHANUMERIC_MISFIRES` 11 发）；
③ 变异腿＝运行时摘掉边界 ⇒ ②那一组当场全体命中（证明这把锁不是空护栏，
   同时证明「数字紧邻那一枚」的失手是**边界造成的**、不是别的东西）。

写法由来（为什么不用 `\b`，两处都是刻意的）：
- 左侧只挡 ASCII 字母数字：中文没有空格，`为R-18`、`标了R-18才` 是在册要拦的真形态，
  `\b` 在 Unicode 下把汉字当词字符 ⇒ 会连真命中一起放过；
- 右侧只挡数字续位（治编号类 `…1800`／`…1801`）：`R-18向` 后面跟汉字，`\b` 判不出边界；
  而右侧连字母一起挡会多放过带后缀的变体＝超出裁定的第二次收紧，不做。

本文件**不抄录词表原文**（二次传播坑，规则 11）：分级标记只以「形态串」出现，
清单里其余各枚一律由 `_non_tier_alternatives()` 从活体模式运行时派生，文件里一个字没有。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    PrivacyLevel,
    ReviewAction,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render import reviewer as reviewer_module

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"

# 两枚环视的字面标记：变异腿按名摘除，判据与真身同源（不另立一份形状）。
LEFT_BOUNDARY = r"(?<![0-9A-Za-z])"
RIGHT_BOUNDARY = r"(?![0-9])"


def _tier_entry() -> tuple[str, re.Pattern[str]]:
    """从活体清单里取「带数字的那一枚」条目（按特征定位，不写标签也不写词面）。"""
    found = [
        (label, pattern)
        for label, pattern in reviewer_module._PUBLIC_OUTPUT_UNSAFE
        if "18" in pattern.pattern
    ]
    assert len(found) == 1, f"带数字的条目应当只有一枚，现算 {len(found)} 枚：清单被复制了"
    return found[0]


def _tier_pattern() -> re.Pattern[str]:
    return _tier_entry()[1]


def _mutated_pattern() -> re.Pattern[str]:
    """把两枚边界摘掉后的模式＝改前形态（变异腿用，运行时现算不落盘）。"""
    source = _tier_pattern().pattern
    stripped = source.replace(LEFT_BOUNDARY, "").replace(RIGHT_BOUNDARY, "")
    assert stripped != source, (
        "摘掉边界后模式一字未变＝两枚环视的写法被改走了样，本锁的变异腿在空跑"
    )
    return re.compile(stripped, _tier_pattern().flags)


def _non_tier_alternatives(pattern: re.Pattern[str]) -> list[str]:
    """从活体模式派生「不带数字」的那几枚词面（本文件因此不必抄清单）。"""
    source = pattern.pattern
    body = source[1:-1] if source.startswith("(") and source.endswith(")") else source
    return [item for item in body.split("|") if item and "18" not in item]


# ---------------------------------------------------------------- ① 在册要拦的真形态
# 每一发都是「分级标记」的一种真实写法：裸写／连写／带空格／左邻汉字／右邻汉字／
# 括号包裹／句中／带评级后缀／生产人格指令文案里那一枚／带「禁」后缀。
_TIER_FORMS_STILL_BLOCKED: tuple[tuple[str, str], ...] = (
    ("T-1 裸写带连字符", "R-18"),
    ("T-2 裸写连字符省略", "R18"),
    ("T-3 小写带空格", "r 18"),
    ("T-4 左邻汉字无空格", "这是分级为R-18的条目"),
    ("T-5 右邻汉字无空格", "含 R-18向的两张图"),
    ("T-6 半全角括号包裹", "（R18）与「R-18」两种写法"),
    ("T-7 句中两侧留白", "这段内容标了 R-18 才发出来"),
    ("T-8 评级后缀", "标注R18+的存档"),
    ("T-9 生产人格指令文案那一枚", "（含 R-18 向）"),
    ("T-10 混排句", "写一段露骨的 R18 标签"),
    ("T-11 汉字后缀", "R-18禁"),
)

# ---------------------------------------------------------------- ② 误伤形态
# 每一发改前都被咬（现算证据＝③的变异腿，以及本席 2026-10-06 的改前探针读数）。
# 类别：月份缩写拼日期／构建号／英文月日（月名末字母 + 空格 + 日）／ISO 时间戳里夹的
# 英文月日／固件号／产品型号／表格编号／房间号／以 r 结尾的英文词后面跟编号。
_ALPHANUMERIC_MISFIRES: tuple[tuple[str, str], ...] = (
    ("F-1 月份缩写+日号", "会议定在 MAR18 出结果。"),
    ("F-2 构建号", "这版标签是 v2R-18，构建号照着走。"),
    ("F-3 英文月日", "我把事记在 October 18 那天。"),
    ("F-4 英文月日（另一个以 r 收尾的月名）", "September 18 起换新值班表。"),
    ("F-5 ISO 8601 串里夹的英文月日", "截止 2026-10-18T18:30:00Z（ISO 8601），落款 October 18。"),
    ("F-6 固件号", "固件 v3R18 已发布。"),
    ("F-7 产品型号（数字续位）", "型号 R-1800 已停产。"),
    ("F-8 表格编号", "表格编号 TR-18 那一列。"),
    ("F-9 房间号（数字续位）", "房间号 R-1801 住户报修。"),
    ("F-10 以 r 收尾的自造词+空格+编号", "usercenterr 18 号样本"),
    ("F-11 英文词 worker + 编号", "worker 18 号线程"),
)

# 改前改后都不咬的那一类：纯 ISO 时间戳里没有「字母紧邻数字」的形状。
# 诚实记账＝它**不是**本条红线的 RED 原文，只是回归护栏（别哪天把日期面改坏了）。
_ALWAYS_CLEAN: tuple[tuple[str, str], ...] = (
    ("C-1 纯 ISO 时间戳", "时间戳 2026-10-06T18:20:00+08:00"),
    ("C-2 版本号点分", "固件 v1.18 与 18.3 的差值"),
    ("C-3 时刻", "18:30 开潮，十八分钟后收。"),
)

# 裁定代价（单变量归因）：数字紧邻那枚标记改前咬、改后不咬。
# 「18」前面是数字 ⇒ 它和 F-2/F-6 同一类（嵌在字母数字串里），不是在册的裸标记写法，
# 因此按**裁定的代价**记在这里，而不是当漏拦。
_DOCUMENTED_COST: tuple[tuple[str, str], ...] = (
    ("X-1 数字前缀紧邻标记", "18R-1818"),
)


# ================================================================ ① 真命中不丢（反证）


@pytest.mark.parametrize("name,text", _TIER_FORMS_STILL_BLOCKED)
def test_registered_tier_forms_still_hit(name: str, text: str) -> None:
    assert _tier_pattern().search(text), f"加了词界后在册真形态被放过＝红线被多放宽了：{name}"


@pytest.mark.parametrize("name,text", _DOCUMENTED_COST)
def test_documented_cost_forms_do_not_hit(name: str, text: str) -> None:
    """这一枚的失手**只**由边界造成（③里同一枚摘掉边界就命中）⇒ 属裁定的代价，不是漏网。"""
    assert not _tier_pattern().search(text), f"代价清单里这一枚现在又命中了，账面要重记：{name}"


def test_the_tier_entry_carries_both_boundaries() -> None:
    source = _tier_pattern().pattern
    assert LEFT_BOUNDARY in source, "左词界不见了＝F-12 被回退，误伤会重新开始"
    assert RIGHT_BOUNDARY in source, "右词界不见了＝编号类（数字续位）重新开始被咬"


def test_scrub_and_audit_still_fire_on_a_registered_tier_form() -> None:
    """判据链那一手：真命中在群聊面**仍然**被涂销、仍然留审计记号。

    只验正则命中不算数——F-12 之后如果涂销腿或审计记号被顺手放掉，上面那些
    单元断言照样绿。这里跑 `review_capability_result` 本体（群作用域）。
    """
    label, _pattern = _tier_entry()
    body = f"先说结论：潮汐窗口在四点前后。\n\n你要的那段 {_TIER_FORMS_STILL_BLOCKED[0][1]} 我不会写。"
    result = CapabilityResult(
        request_id="req-f12-1",
        capability_id="bot.chat",
        kind="text",
        body=body,
        privacy_level=PrivacyLevel.GROUP,
    )
    decision = BotDecision(
        request_id="req-f12-1",
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )

    review = reviewer_module.review_capability_result(result, decision)

    assert review.approved is True, f"真命中应当走降级（涂销）而不是被整条吃掉：{review.reasons}"
    assert review.action is ReviewAction.REWRITE, review.action
    assert not _tier_pattern().search(review.safe_text), "命中面没被中和＝涂销腿失效"
    assert f"public output span neutralised: {label}" in review.reasons, review.reasons
    for keep in ("先说结论：潮汐窗口在四点前后。", "我不会写。"):
        assert keep in review.safe_text, f"清白正文被吞了：{keep}"


# ================================================================ ② 误伤消失（正证）


@pytest.mark.parametrize("name,text", _ALPHANUMERIC_MISFIRES)
def test_alphanumeric_embedded_forms_are_not_bitten(name: str, text: str) -> None:
    assert not _tier_pattern().search(text), f"正常文本仍被当违规洗掉＝词界没生效：{name}"


@pytest.mark.parametrize("name,text", _ALWAYS_CLEAN)
def test_clean_texts_stay_clean(name: str, text: str) -> None:
    assert not _tier_pattern().search(text), f"这一枚本来就不该咬：{name}"


# ================================================================ ③ 变异腿（锁有牙）


@pytest.mark.parametrize(
    "name,text",
    _ALPHANUMERIC_MISFIRES + _DOCUMENTED_COST,
)
def test_misfire_forms_bite_once_the_boundaries_are_stripped(name: str, text: str) -> None:
    """摘掉两枚边界＝改前形态当场复现 ⇒ 上面②的绿是真绿，不是空护栏。"""
    assert _mutated_pattern().search(text), (
        f"摘掉边界后仍不命中＝这一枚的干净不是边界给的，②的证据要重记：{name}"
    )


def test_mutation_is_single_variable() -> None:
    """变异只动边界：同一枚摘掉边界后必须命中、装回去必须不命中（单变量归因）。"""
    live, mutated = _tier_pattern(), _mutated_pattern()
    for name, text in _DOCUMENTED_COST + _ALPHANUMERIC_MISFIRES:
        assert mutated.search(text) and not live.search(text), f"不是单变量差异：{name}"
    # 反向：在册真形态在两种形状下都命中 ⇒ 放宽的只有「嵌在字母数字串里」那一类。
    for name, text in _TIER_FORMS_STILL_BLOCKED:
        assert live.search(text) and mutated.search(text), f"真形态差异不该出现：{name}"


# ============================================ 清单其余成员未被顺手改动（边界之外零改动）


def test_other_list_members_are_untouched_and_still_effective() -> None:
    """词表成员一个没动：每一枚（活体派生，本文件不抄）都还能命中自己。

    这条同时是「不许顺手扩/缩词表」的护栏：若有人把某枚删掉，`_non_tier_alternatives`
    对其它枚仍绿，但清单条目数会掉——所以另加一发「至少还有 3 枚条目」的活性下限。
    """
    entries = list(reviewer_module._PUBLIC_OUTPUT_UNSAFE)
    assert len(entries) >= 3, f"清单条目数掉到 {len(entries)}：分级之外的面被动过了"
    checked = 0
    for label, pattern in entries:
        for alternative in _non_tier_alternatives(pattern):
            checked += 1
            assert pattern.search(alternative), f"词面 {label} 命中不了自己的成员＝形状被改坏了"
    assert checked >= 8, f"活体派生出的成员只有 {checked} 枚，本条在空跑"


# =============================================== 单一出处锁：这条形状只准住在一处


def _compiled_literals(path: Path) -> list[str]:
    """文件里 `re.*` 调用第 0 位的模式串（AST 提取，零 import 被扫件）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
            and func.attr in {"compile", "search", "match", "fullmatch", "sub", "subn", "findall"}
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found.append(node.args[0].value)
    return found


def _matches_tier_shape(source: str) -> bool:
    """这段模式串是否**认得分级标记本身**（命中的跨度必须含字母且带数字）。

    跨度长度门槛是为「只认裸数字 18 的模式不算副本」设的：`18px`、以及只认两位数字的
    那一类模式，与这条红线无关，把它当副本会让本锁天天假红。
    """
    probe = f"你要的那段 {_TIER_FORMS_STILL_BLOCKED[0][1]} 我不会写"
    for flags in (0, re.IGNORECASE):
        try:
            compiled = re.compile(source, flags)
        except re.error:
            continue
        for match in compiled.finditer(probe):
            span = match.group(0)
            if "18" in span and any(char.isalpha() for char in span):
                return True
    return False


def _tier_shape_owners(files: list[Path]) -> dict[str, int]:
    """按「谁认得这条形状」给文件分组计数（仓库外文件回退用文件名，注毒腿要用）。"""
    owners: dict[str, int] = {}
    for path in files:
        hits = sum(1 for source in _compiled_literals(path) if _matches_tier_shape(source))
        if hits:
            try:
                key = path.resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                key = f"<outside-tree>/{path.name}"
            owners[key] = owners.get(key, 0) + hits
    return owners


def _outbound_chain_files() -> list[Path]:
    scan_roots = [RUNTIME_PKG / "domains" / "render", RUNTIME_PKG / "output"]
    files = [path for root in scan_roots for path in sorted(root.rglob("*.py"))]
    files.append(RUNTIME_PKG / "domains" / "chat_reply" / "capabilities" / "chat.py")
    return [path for path in files if path.exists()]


def test_shape_has_exactly_one_owner_in_the_outbound_review_chain() -> None:
    """群聊出站内容面的这条形状**只准住一处**（在册教训＝内部标记消毒正则曾双真身逃逸）。

    扫的是真身与它的读点：`domains/render/**`（含 reviewer / plain_text / renderer）
    ＋ `output/reviewer.py` 再导出垫片 ＋ `chat.py` 群聊那一支。命中数必须是
    「reviewer.py 恰一枚、其余零枚」——多一处＝静默分叉，少一处＝这条形状搬家了。
    ⚠ 范围**不含** `security/content_safety.py`：那是 2026-09-17 内容政策那本账的
      公开面规则（入站判定腿），形状同族但另册另裁，F-12 没裁到它（本席未动，
      已在报告里点名待用户裁）。
    """
    files = _outbound_chain_files()
    assert len(files) >= 8, f"扫描面只剩 {len(files)} 件＝坐标失效，本锁在空跑"

    owners = _tier_shape_owners(files)
    reviewer_rel = "plugins/bot_unified_runtime/domains/render/reviewer.py"
    assert owners == {reviewer_rel: 1}, (
        f"这条形状的真身应当只有 reviewer.py 一处，现算＝{owners}（多一处＝第二副本静默分叉；"
        "少一处＝形状搬家，读点还指旧地方会静默失效）"
    )


def test_single_source_detector_is_not_running_empty(tmp_path: Path) -> None:
    """注毒自证：探测器本身有牙（否则上面那条「只有一处」可能只是因为谁都认不出来）。"""
    # ① 现真身必须被认出（认不出＝owners 恒空＝假绿）。
    assert _matches_tier_shape(_tier_pattern().pattern), "探测器认不出真身＝本锁在空跑"
    # ② 旧形状（摘掉边界的同族写法）也必须被认出＝副本无论加没加词界都逃不掉。
    assert _matches_tier_shape(_mutated_pattern().pattern), "副本用旧写法就探测不到＝面有洞"
    # ③ 无关的裸数字模式不许当副本（否则本锁天天假红）。
    assert not _matches_tier_shape("18px")
    assert not _matches_tier_shape(r"(?:\d{1,2})")
    # ④ 坏模式串不许把门崩掉。
    assert not _matches_tier_shape("(?:")
    # ⑤ 真注毒：往扫描语义下再落一件副本，`_tier_shape_owners` 必须点名两处。
    twin = tmp_path / "plain_text_twin.py"
    twin.write_text(
        "import re\n"
        f"TWIN = re.compile(r{_tier_pattern().pattern!r}, re.IGNORECASE)\n"
        "OTHER = re.compile(r'18px')\n",
        encoding="utf-8",
    )
    owners = _tier_shape_owners([RUNTIME_PKG / "domains" / "render" / "reviewer.py", twin])
    assert len(owners) == 2, f"注进去的副本没被点名＝单一出处锁是空护栏：{owners}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
