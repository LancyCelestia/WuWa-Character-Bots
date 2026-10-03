"""人格禁令溯源门（2026-10-03 科技话题闭嘴波，台账 #75；判据两改=G3b 重铸版）。

三件事：
① 形态门——「你不知道"X"这些概念」这种**封概念**句式全树禁用（源与生产副本同尺）：
   它封的不是"承认自己是 AI"，而是"知道这个概念"本身，会把整族词汇变成不可谈。
   （本腿判据体一字未动——它有牙，且咬的正是本案主犯形状。）
② 溯源门——生产副本里每一条**规范行**（含 绝不/不得/不许/禁止/不要/只能/必须），
   源侧 `personas/**` 必须有其关键内容的原文：与源侧全文的最长公共子串（CJK 按字计）
   ≥4 判"有源"，<4 判游离。**为什么这么改（G3b 2026-10-03 实测）：**
   - 检测腿换形：旧 `_BAN_LINE_RE`（禁令词＋40 字内引号短语）在副本里只命中 3 行，
     规范行实有 10 枚——其余 7 枚门根本没在看，"防绕过源改副本"这条判据名不符实。
   - 比法换义：溯源要问的是"**这条禁令的意思源侧有没有原文**"，不是"源侧那句话
     长得像不像禁令"。同形比法下副本 L86（模板式拒绝带 "I cannot fulfill" 引号示例）
     与源侧同义规则（identity.md 亲密边界腿）永远配不上，属误伤；而 L93 底线节即便
     逐字回流，旧尺也从没把它当禁令行看——"走正腿"是句空话。
   - 粒度代价如实记账：整行 LCS≥4 会放行"大半同行、内嵌一小句漂移"的行
     （旧副本 L3 即此形，实算 LCS=20）——clause 级漂移由①形态门兜底；
     **整行新增**的无源禁令必被②咬住（③注毒腿给新形状下的有效性证明）。
   病根：`sync_persona_source.py` 只防"改源忘副本"，**从不防绕过源改副本**，
   重锚时 `--note` 写句非空自由文本就能把新禁令盖成"已人工审阅"。
③ 注毒自证——往临时副本塞一条与源侧几乎零重叠的新规范行（实算 LCS=3＜阈值 4），
   ②必红、且游离计数恰 +1（证明这杆尺在新形状下仍有牙，不是永真）。
副本缺席时优雅跳过（与 `tests/test_copy_redline_gate.py` 同口径），**但跳过必须显式声明**。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONAS_DIR = REPO_ROOT / "personas"
# 与 `tests/test_copy_redline_gate.py:65-67` 同一构造：相对仓库上一级的确定性路径、
# 不读 `.env`，保证 CI（无 Runtime）下行为可预测——存在则入尺，缺失显式跳过。
RUNTIME_COPY_PATH = (
    REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "persona" / "守岸人_核心人格.md"
)

_CONCEPT_BAN_RE = re.compile(
    r"你不知道[\u201c\u201d\"'][^\u201c\u201d\"']{2,40}[\u201c\u201d\"']这些概念"
    r"|[这些]些概念不在你的"
    r"|你[没无]有关于[\u201c\u201d\"'][^\u201c\u201d\"']{2,40}[\u201c\u201d\"']的知识"
)
# 检测腿＝规范行：副本里凡是承载行为规范的句子（七个规范词任一）全部纳入射程。
_NORM_LINE_RE = re.compile("绝不|不得|不许|禁止|不要|只能|必须")
# 有源阈值：与源侧全文的最长公共子串长度（CJK 按字计）。
_MIN_PROVENANCE_LCS = 4


def _lcs_len(line: str, corpus: str) -> int:
    """line 与 corpus 的最长公共子串长度（字符计）。单调性：某长度配不上则更长必配不上。"""
    best = 0
    n = len(line)
    for i in range(n):
        hi = n - i
        if hi <= best:
            continue
        lo, top, cur = 1, hi, 0
        while lo <= top:
            m = (lo + top) // 2
            if line[i : i + m] in corpus:
                cur, lo = m, m + 1
            else:
                top = m - 1
        best = max(best, cur)
    return best


def _matches_exempt(line: str, pattern: str) -> bool:
    return pattern in line


def _copy_text() -> str:
    if not RUNTIME_COPY_PATH.exists():
        pytest.skip("生产副本缺席（CI 无 Runtime）——本门跳过，非通过")
    return RUNTIME_COPY_PATH.read_text(encoding="utf-8", errors="ignore")


def _source_text() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted(PERSONAS_DIR.rglob("*"))
        if p.is_file()
    )


def _stray_ban_lines(copy_text: str, source_text: str, exempt: tuple[str, ...]) -> list[str]:
    """溯源门的唯一判据体（②与③共用，禁第二把尺；旧 `_BAN_LINE_RE` 已随重铸删除）。

    游离＝副本里的规范行（含七个规范词任一），与源侧全文最长公共子串 <4 字，
    且不命中存量豁免表的任何字面片段。
    """
    return [
        line.strip()[:60]
        for line in copy_text.splitlines()
        if _NORM_LINE_RE.search(line)
        and _lcs_len(line, source_text) < _MIN_PROVENANCE_LCS
        and not any(_matches_exempt(line, pat) for pat in exempt)
    ]


def test_concept_ban_shape_is_absent_everywhere():
    """① 形态门：封概念句式全树零容忍。"""
    haystacks = {"生产副本": _copy_text(), "源码树": _source_text()}
    bad = {name: hits for name, text in haystacks.items() if (hits := _CONCEPT_BAN_RE.findall(text))}
    assert not bad, f"出现封概念句式（会把整族词变成不可谈）：{bad}"


def test_every_copy_ban_line_has_source_provenance():
    """② 溯源门：副本规范行的关键内容必须在源侧有原文；豁免只准缩短。"""
    from tests._persona_ban_legacy_exempt import LEGACY_EXEMPT

    strays = _stray_ban_lines(_copy_text(), _source_text(), LEGACY_EXEMPT)
    assert not strays, f"副本单方面新增禁令、源码树无对应原文：{strays}"


def test_exempt_list_only_shrinks():
    """豁免表上限＝2026-10-03 G3b 现算游离枚数（1）。加条目即红——回流才是修法。"""
    from tests._persona_ban_legacy_exempt import LEGACY_EXEMPT

    assert len(LEGACY_EXEMPT) <= 1, "豁免清单变长了——回流才是修法，加豁免不是"


def test_poison_proves_the_provenance_gate_has_teeth(tmp_path: Path):
    """③ 注毒：源侧几乎零重叠的新规范行必须被②咬住（新形状下的有效性证明）。

    只往 `tmp_path` 的副本写毒，**绝不写生产件**——本仓有过注毒测试崩在写毒之后、
    把生产副本留在中毒态的先例。
    """
    from tests._persona_ban_legacy_exempt import LEGACY_EXEMPT

    source = _copy_text()
    source_tree = _source_text()
    poison_line = "- 绝不采信玆醲龘麤。"
    poisoned_text = source + "\n" + poison_line + "\n"

    # 毒先是"有效毒"（新判据体＝规范行＋整行 LCS）：
    # (a) 被检测腿看见——含规范词；
    assert _NORM_LINE_RE.search(poison_line), "注毒行不是规范行＝毒无效"
    # (b) 与源侧的公共子串低于有源阈值——实算应为 3（"绝不采"），远低于任何语义重叠。
    lcs = _lcs_len(poison_line, source_tree)
    assert lcs < _MIN_PROVENANCE_LCS, f"注毒行与源侧原文重叠已达 {lcs}≥{_MIN_PROVENANCE_LCS}＝毒不新鲜"

    # 落盘到仓库外的临时副本，再按②的真判据体跑一遍（不是另起一把尺）。
    poisoned_copy = tmp_path / "守岸人_核心人格.md"
    poisoned_copy.write_text(poisoned_text, encoding="utf-8")
    baseline = _stray_ban_lines(source, source_tree, LEGACY_EXEMPT)
    after = _stray_ban_lines(poisoned_copy.read_text(encoding="utf-8"), source_tree, LEGACY_EXEMPT)

    assert poison_line.strip()[:60] in after, f"②溯源门没咬住注毒行＝永真的尺：{after}"
    assert len(after) == len(baseline) + 1, f"注毒应只多出一枚游离，实得 before={baseline} after={after}"
