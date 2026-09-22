"""G-T3 判据真身：一次性事实禁止裸写在正文（席 T-GATES，2026-09-22）。

一句话：**会随代码漂移的事实（计数 / 阈值 / 枚举 / 运行数据路径）只能出现在
`auto:` 现算段或「指向真身」的指针句里**，其余一律是债。
指针放行是**分段**的：只摘除指针短语自己承担的片段，同行残余裸事实照判
（席 S3 2026-09-22 治 F-3「整行橡皮章」）；机器本地绝对路径（盘符/UNC/家目录/
`%VAR%`）属隐私+可移植双重红线，指针句不豁免、一律红。

- 词表与正则**只住本文件**（AST 锁 `test_fact_rulers_have_a_single_home` 执法；
  在测试件里再抄一套词表=红——本仓「第二真身」实锤族）。
- 管辖面的人写区由 `human_zone()` 统一剥离：`BOARD-AUTO` / `TEMPLATE-AUTO` 机器段、
  围栏代码块、front-matter 都不算人写正文。
- 判据函数 `fact_findings()` 收「行 + 词表」纯参数：**全树与注毒共用同一支**
  （内存喂样本即可证门有牙，不往源码树写一个字）。
- 与 `tests/test_documentation_consistency.py`（叙述文档面）的关系：同一把尺子的两面，
  该门仍用其旧窄词表面向叙述件；本模块是 G-T3 的宽尺面。两把尺子同名不同面，
  未合并的那半（叙述面改走本模块）记在席报告「没做什么」里。
"""

from __future__ import annotations

import re

AUTO_MARKERS: tuple[tuple[str, str], ...] = (
    ("<!-- BOARD-AUTO:BEGIN -->", "<!-- BOARD-AUTO:END -->"),
    ("<!-- TEMPLATE-AUTO:BEGIN -->", "<!-- TEMPLATE-AUTO:END -->"),
)

_COUNT_NOUNS = (
    "字段|主题|板块|入口|能力|模板|别名|路由席位|席位|功能|域|库|表|交付物|用例|测试|文件"
    "|页|条|项|枚|张|个|批|次|键"
)

#: 会漂移的计数：数字 + （量词） + 名词。前置排除 §9 / v21r2 / 1.4.3 这类粘连。
#: 尾界只挡 ASCII 词字符（旧尺子的 `(?!\w)` 在中文里等于「名词后不许接任何汉字」，
#: 会把「47 个能力入口」这类最该抓的写法放过去——本席注毒当场抓到）。
FACT_COUNT_RE = re.compile(
    rf"(?<![\w./§-])\d{{1,5}}\s*(?:余|约|近)?\s*(?:{_COUNT_NOUNS})(?![A-Za-z0-9_])"
)

#: 阈值/限额：数字 + 度量单位（这些值住代码常量，正文只准指真身）。
FACT_THRESHOLD_RE = re.compile(
    r"(?<![\w./§-])\d+(?:\.\d+)?\s*"
    r"(?:km|KB|MB|GB|KiB|MiB|%|％|℃|°|ms|元|秒|分钟|小时|天|字|行|折|倍)(?![A-Za-z])"
)

#: 运行数据/本机路径：这类事实住 `scripts/runtime_paths.py` 与配置真身，正文写死即漂移+泄漏。
FACT_PATH_RE = re.compile(
    r"(?:(?<![\w/-])(?:data|ChatBot_Runtime|ChatBot_Archive)/|[A-Za-z]:[\\/]|\\\\[A-Za-z0-9])"
)

#: 权威指针（放行词表唯一真身，别处禁抄第二份）：AGENTS 规则 10 的合法形态 + 参数引用。
AUTHORITY_MARKER_RE = re.compile(
    r"以(?:生成物|机器册|本文件自身|该文件|真身|为准|实测)|为准|当时值|现值|真身|现算|"
    r"以最近一次|以 `?dev\.ps1|以该测试为准|派生自|以反查为准"
)

#: 指针短语整段（席 S3 2026-09-22 治 F-3「整行橡皮章」）：`以…为准` 不跨小句的完整
#: 短语 + 上表各指针词。判据**先摘除这些短语、再对残余文本执法**——指针只允许豁免
#: 它自己承担的那部分语义，同行指针之外的裸计数/裸阈值/裸枚举仍须红。
AUTHORITY_PHRASE_RE = re.compile(r"以[^。．，,；;！!？]{0,48}?为准|" + AUTHORITY_MARKER_RE.pattern)

#: 参数/占位引用（放行）：`{{fact:KEY}}` 由渲染器现算，G-T4 校验 KEY 在 schema 内。
#: 同样按**片段**摘除，不再一行买断（F-3 例：`{{fact:count}} 条入口，另外 47 个能力`）。
PLACEHOLDER_RE = re.compile(r"\{\{fact:[a-z][a-z0-9_]*\}\}")

#: 机器本地绝对路径（盘符 / UNC / git-bash 盘符根 / 家目录 / 环境变量占位）：
#: 隐私 + 可移植双重红线，**指针句不豁免、一律红**（AGENTS 规则 3 打码面之外的一层；
#: 这类事实只准住配置真身）。`https://` 等 URL scheme 被字母前置否定挡住，不误伤。
FACT_MACHINE_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[A-Za-z0-9]"
    r"|(?i:(?<![\w./-])/(?:c/Users|Users|home)/)|(?<![A-Za-z0-9_])~/|(?i:%[A-Za-z_][A-Za-z0-9_]*%))"
)

_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ENUM_SPLIT_RE = re.compile(r"[、/／,，]")
_CJK_RE = re.compile(r"[一-鿿]")

#: 并列枚举判据：一行里出现 ≥6 枚并列成员（顿号/斜杠分隔）且与某个声明源词表相交
#: ≥2 枚 ⇒ 这份清单的正确居所是声明源，不是正文。GATE-PLAN §G-T3「照抄 doc_link 事件源判据形态」。
ENUM_MIN_MEMBERS = 6
ENUM_MIN_VOCAB_HITS = 2


def strip_auto_zones(text: str) -> str:
    """剥掉机器段（AUTO/TEMPLATE-AUTO 标记之间），只留人写区。"""
    out = text
    for begin, end in AUTO_MARKERS:
        while begin in out and end in out:
            head, rest = out.split(begin, 1)
            _mid, tail = rest.split(end, 1)
            out = head + tail
    return out


def human_lines(text: str) -> list[str]:
    """管辖面「人写区」逐行：剥 front-matter、剥机器段、剥围栏代码块。"""
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        start = end + 1 if end else 0
    body = strip_auto_zones("\n".join(lines[start:]))
    out: list[str] = []
    infence = False
    for ln in body.splitlines():
        if _FENCE_RE.match(ln):
            infence = not infence
            continue
        if not infence:
            out.append(ln)
    return out


def enum_members(line: str) -> list[str]:
    """取一行里最长的一段并列成员（顿号/斜杠分隔，成员含 CJK 才算）。"""
    best: list[str] = []
    for run in re.split(r"[\s:：|（(]+", line):
        parts = [p.strip(" `*（）()") for p in _ENUM_SPLIT_RE.split(run) if p.strip()]
        parts = [p for p in parts if _CJK_RE.search(p)]
        if len(parts) > len(best):
            best = parts
    return best


def fact_findings(
    lines: list[str], *, vocab: set[str] | None = None, check_enum: bool = True
) -> list[str]:
    """纯判据：给人写区行，返回违规描述（喂真页与注毒同一支）。

    分段判据（席 S3 2026-09-22 治 F-3，只加严）：
    - **机器本地路径**先行判红，指针词不豁免（一律红）；
    - 其余四类：先摘除 `{{fact:…}}` 占位与指针短语整段，四把尺子对**残余**执法——
      一行里指针词与裸事实混写时，指针只豁免它自己承担的那部分语义。
    """
    hits: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if FACT_MACHINE_PATH_RE.search(s):
            hits.append(f"裸机器本地路径：{s[:90]}")
            continue
        residual = AUTHORITY_PHRASE_RE.sub(" ", PLACEHOLDER_RE.sub(" ", s))
        if FACT_COUNT_RE.search(residual):
            hits.append(f"裸计数：{s[:90]}")
        elif FACT_THRESHOLD_RE.search(residual):
            hits.append(f"裸阈值：{s[:90]}")
        elif FACT_PATH_RE.search(residual):
            hits.append(f"裸路径：{s[:90]}")
        elif check_enum and vocab:
            members = enum_members(residual)
            if len(members) >= ENUM_MIN_MEMBERS:
                known = sum(1 for m in members if m in vocab or m.strip("`") in vocab)
                if known >= ENUM_MIN_VOCAB_HITS:
                    hits.append(f"裸枚举清单（{len(members)} 枚并列、命中声明源 {known} 枚）：{s[:90]}")
    return hits
