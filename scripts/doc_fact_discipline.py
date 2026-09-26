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
  该门改用 R4 的三条**结构**判据（机器册/真身路径指针 · 「当时值」且数在真身已不存在 ·
  代码块/行内码）面向叙述件；本模块是 G-T3 的宽尺面。
  **R4（2026-09-23 裁定件 ADDENDUM-USER-RULINGS-20260923 §R4）退役说明**：叙述规则 10
  「裸计数门」的**词法放行本体**是 `test_documentation_consistency.py` 里旧的
  `_AUTHORITY_MARKER_RE`（靠 历史/实测/当时/现值 等词整行放行），已由上述三条结构判据取代、
  不再被引用。本模块的 `AUTHORITY_PHRASE_RE` 是 **G-T3 宽尺**的分段指针摘除器，被
  `spec_gates_census`／板块门／税务门（`test_board_taxonomy_gate.py`、
  `test_taxonomy_spec_gates.py`）依赖其「纯指针句放行」契约，**不在本次退役范围内**（动它会把
  红搬进别席的账、并撕毁它们对合法指针句放行的既有断言）；宽尺改走同一套结构判据属该尺 owner
  的后续工作，本席已在报告「没做什么」如实登记。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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
#: 头界同理（席 S20 N-1 补牙，2026-09-22）：旧 `(?<![\w./§-])` 的 `\w` 含汉字 ⇒
#: 「共47个」「上限100MB」这类**数字紧贴汉字、无空格**的写法整批漏放行（S9 探针实测）。
#: 改挡 ASCII 词字符 `[A-Za-z0-9_]`：§9 / v21r2 / 1.4.3 的粘连仍被 `. / § -` 与 ASCII 字母数字挡住，
#: 但汉字紧邻数字不再当豁免——「让汉字挨着数字也算数」。
FACT_COUNT_RE = re.compile(
    rf"(?<![A-Za-z0-9_./§-])\d{{1,5}}\s*(?:余|约|近)?\s*(?:{_COUNT_NOUNS})(?![A-Za-z0-9_])"
)

#: 阈值/限额：数字 + 度量单位（这些值住代码常量，正文只准指真身）。头界同 FACT_COUNT_RE
#: （席 S20 N-1 补牙：`\w`→ASCII 类，汉字前缀不再豁免，治「上限100MB」漏放行）。
FACT_THRESHOLD_RE = re.compile(
    r"(?<![A-Za-z0-9_./§-])\d+(?:\.\d+)?\s*"
    r"(?:km|KB|MB|GB|KiB|MiB|%|％|℃|°|ms|元|秒|分钟|小时|天|字|行|折|倍)(?![A-Za-z])"
)

#: 运行数据/本机路径：这类事实住 `scripts/runtime_paths.py` 与配置真身，正文写死即漂移+泄漏。
#: 盘符分支与下方机器尺**同构带字母守卫**（席 S1 2026-09-22 收尾补正）：`https://`/`file://`
#: 这类 URL scheme 的末字母+`://` 曾被无守卫的 `[A-Za-z]:[\\/]` 当成本机路径整行记红——
#: 外部端点 URL 不是「运行数据/本机路径」类事实（机器尺用例亦明证 URL 无罪），属判据误伤。
FACT_PATH_RE = re.compile(
    r"(?:(?<![\w/-])(?:data|ChatBot_Runtime|ChatBot_Archive)/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[A-Za-z0-9])"
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

#: 参数/占位引用：`{{fact:KEY}}` 由渲染器在**机器段**现算，G-T4 校验 KEY 在 schema 内。
#: 同样按**片段**摘除，不再一行买断（F-3 例：`{{fact:count}} 条入口，另外 47 个能力`）。
#:
#: ⚠ 席 S106（2026-09-22，治 S40 交回的 W-1「免检摘除洞」）：**摘除改为有条件**——旧口径对
#: 人写区任意 `{{fact:KEY}}` 无条件摘除，而在册校验原本只发生在模板渲染区
#: （`doc_template_sync.parse_schema_text`），于是「正文随手写一个不存在的占位符」就能免检
#: = 准绳一禁的**假指针**。现口径：仅当 KEY 在「该页 front-matter 所声明模板的 `@schema`
#: 在册参数」内才摘除；不在册 ⇒ **不摘除**（片段留在残余里照常按四把尺子记账）并另记一条
#: `UNKNOWN_FACT_KEY`。在册参数取数口唯一：`declared_fact_keys()` 复用既有
#: `doc_template_sync.load_schemas()/parse_front_matter()`，本模块**不建第二套参数表**。
#: 未传在册参数（`known_fact_keys=None`）时逐字保持旧行为——现有两处调用点
#: （`spec_gates_census.py` G-T3 面A、`doc_template_sync.naked_fact_findings`）仍在传旧形态，
#: 让它们吃到加严需各改一行，属别席在飞面 ⇒ 已成交回工单（见席报告 §交回）。
PLACEHOLDER_RE = re.compile(r"\{\{fact:[a-z][a-z0-9_]*\}\}")

#: 占位符**形**检测尺（席 S106，只用于点名、不参与摘除）：`PLACEHOLDER_RE` 只认规范小写形，
#: 大写键 / `{{ fact:x }}` / 空键这类「看着像占位符」的写法既不匹配规范形、也不被渲染器消费
#: （`doc_template_sync._PLACEHOLDER_RE` 同认规范形）⇒ 它们是彻底的假指针，旧口径两头都漏
#: （不摘除、也不报）。本尺把这些形态一律收进 `UNKNOWN_FACT_KEY` 点名面。
PLACEHOLDER_LIKE_RE = re.compile(r"\{\{\s*fact:([^{}\s]*)\s*\}\}")

#: 独立 finding 名（逐条点名 + 可对账）。
UNKNOWN_FACT_KEY = "UNKNOWN_FACT_KEY"

_PLACEHOLDER_HEAD = "{{fact:"


def _placeholder_key(match: re.Match[str]) -> str:
    """从规范形匹配里取 KEY（复用同一支 `PLACEHOLDER_RE`，不另立第二份形态）。"""
    return match.group(0)[len(_PLACEHOLDER_HEAD) : -2]


def declared_fact_keys(
    page_text: str = "",
    *,
    template: str | None = None,
    schemas: Mapping[str, Any] | None = None,
) -> set[str]:
    """某页所声明模板的 `@schema` 在册参数键（取数口唯一、只读）。

    模板身份有两种给法（调用方手上是哪种就用哪种）：
    - `template="xxx"`：直接给模板 id——`PageInfo.fm` 要经 `doc_template_sync.annotate()`
      才填（裸 `walk_content_pages()` 的 `fm` 恒 None），页侧声明已由门解析过时直接传最省；
    - `template=None`：回落到从 `page_text` 现读 front-matter（`walk_content_pages()` 给的
      `text` 是整页原文、含 front-matter，故这条路本身也走得通）；
    - `template=""`：显式声明「本页无在册模板」⇒ 空集（正文占位符一律按假指针点名）。

    另两种空集情形：页未声明模板 / 声明的模板不在册。
    `schemas` 省略时按模板目录现读；批量调用方自备一次装载结果（避免逐页读盘）。
    解析件缺 `params` 字段 ⇒ 直接抛错，绝不静默退化成「空集把全树判红」或「放行」。
    """
    import doc_template_sync as dts

    resolved = dts.load_schemas() if schemas is None else schemas
    tid = template
    if tid is None:
        fm = dts.parse_front_matter(page_text)
        tid = None if fm is None else fm.template
    if not tid or tid not in resolved:
        return set()

    params = getattr(resolved[tid], "params", None)
    if params is None:
        raise TypeError(
            f"@schema 解析件缺 params 字段（类型 {type(resolved[tid]).__name__}）："
            "在册参数取数口变了形，宁可抛错也不静默判红/放行"
        )
    return {str(p.key) for p in params}



def unknown_fact_keys(line: str, known: set[str] | frozenset[str]) -> list[str]:
    """一行里「占位符形但 KEY 不在该页在册参数内」的键（同键去重、按出现序）。"""
    out: list[str] = []
    for m in PLACEHOLDER_LIKE_RE.finditer(line):
        key = m.group(1)
        if PLACEHOLDER_RE.fullmatch(m.group(0)) and key in known:
            continue
        if key not in out:
            out.append(key)
    return out


def strip_registered_placeholders(
    line: str, known: set[str] | frozenset[str]
) -> str:
    """只摘除**在册**规范形占位符；不在册的原样留在文本里（照常参与四把尺子）。"""
    return PLACEHOLDER_RE.sub(
        lambda m: " " if _placeholder_key(m) in known else m.group(0), line
    )


def page_fact_findings(
    page_text: str,
    *,
    vocab: set[str] | None = None,
    check_enum: bool = True,
    template: str | None = None,
    schemas: Mapping[str, Any] | None = None,
) -> list[str]:
    """整页判据（加严后的页级入口）：人写区 + 该页在册参数 ⇒ 有条件摘除。

    `page_text` 喂整页原文（`walk_content_pages()` 给的就是原文，含 front-matter）；
    只喂**去过 front-matter 的正文**时必须把 `template=<页声明的模板 id>` 传进来
    （门的四把尺子看到的正是 `human_lines()` 的产物，而 `PageInfo.fm` 要经 `annotate()`
    才填），否则「在册」无从判定——此时按空集处理＝正文占位符一律点名，
    绝不静默退回旧口径（那是本席要堵的同一个洞的另一种犯法）。
    """

    return fact_findings(
        human_lines(page_text),
        vocab=vocab,
        check_enum=check_enum,
        known_fact_keys=declared_fact_keys(
            page_text, template=template, schemas=schemas
        ),
    )


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

#: 行内码剥除（席 S46 任务2，2026-09-22，治 S23R 148 枚假阳）：`human_lines()` 旧只剥
#: 围栏不剥行内 `` `…` ``，代码片段里的 `://`、`P95`、命令示例被当成人写裸事实。
#: 剥除发生在**入判据之前**（管辖面不变、只精修内容形态）；围栏外逐行替换为空格，
#: 行数与行序一字不动。代价如实记：真裸事实若被作者用反引号包起来会随之脱管——
#: 这层残余记进席报告 PARKED，指向「指针/参数引用才是正写」的既有纪律。
_INLINE_CODE_RE = re.compile(r"``[^`\n]+``|`[^`\n]+`")

#: 测量与成语预剥带（席 S46 任务3，2026-09-22，治 S25 PARKED-B 与补录 R2-2 的假阳）：
#: 下列数字形态是**观测统计 / 人工操作步骤频次 / 「N 秒/N 分钟版」标签构词**，
#: 不是住在代码常量里的可漂移事实，不判计数/阈值尺。只按词形限定，**无按页/按节/按目录豁免**；
#: 每形的「注毒必红＋还原必绿」在 `tests/test_taxonomy_spec_gates.py`（S46 段）执法。
#: 反例守卫：`超时 30 秒` `上限 110%` `共 5 次` 均不带本带形态，照样红。
MEASURE_IDIOM_RE = re.compile(
    r"P\d{1,3}\s*\d+(?:[.,]\d+)?\s*(?:ms|%|％|秒|分钟|小时|天)"
    r"|[+−]\s*\d+(?:[.,]\d+)?\s*[%％]"
    r"|(?:说|重复|连说|试|点|按|敲|输入|跑|执行)\s*(?:了)?\s*[一二两三四五六七八九十半\d]{1,3}\s*(?:次|遍|回)"
    r"|\d+(?:\.\d+)?\s*(?:分钟|小时|秒)版"
)

#: 标题行以「N 秒」收尾＝阅读时长标签（如「项目 30 秒」），是成语不是阈值（席 S46 任务3）。
_HEADING_READTIME_RE = re.compile(r"^\s*#{1,6}\s.*?\d+\s*秒\s*$")
_HEADING_TRAIL_SEC_RE = re.compile(r"\d+\s*秒(?=\s*$)")


#: 并列枚举判据：一行里出现 ≥6 枚并列成员（顿号/斜杠分隔）且与某个声明源词表相交
#: ≥2 枚 ⇒ 这份清单的正确居所是声明源，不是正文。GATE-PLAN §G-T3「照抄 doc_link 事件源判据形态」。
ENUM_MIN_MEMBERS = 6
ENUM_MIN_VOCAB_HITS = 2


def strip_auto_zones(text: str) -> str:
    """剥掉机器段（AUTO/TEMPLATE-AUTO 标记之间），只留人写区。

    ⚠ 席 S20 K-1（2026-09-22）：本函数**只是提取人写正文的辅助**，不得被当作
    「机器段=可信已生成」的证据。谁嵌一对 `BOARD-AUTO`/`TEMPLATE-AUTO` 注释就能把
    裸事实藏进被剥掉的段里（S10 内存注毒实证 8 条→0 条）。真正的「标记须经写盘口
    现算校验」执法在 `spec_gates_census.compute()`（`UNVERIFIED_AUTO_ZONE`），
    用下面 `auto_zone_contents` 拿到段内文本后比对，不再无条件信任。
    """
    out = text
    for begin, end in AUTO_MARKERS:
        while begin in out and end in out:
            head, rest = out.split(begin, 1)
            _mid, tail = rest.split(end, 1)
            out = head + tail
    return out


def auto_zone_contents(text: str) -> list[tuple[str, str]]:
    """返回每个机器段的 `(起始标记字面量, 段内文本)`（K-1 的取数腿，不剥不判只取形）。

    与 `strip_auto_zones` 用同一份 `AUTO_MARKERS`（词表只住本文件的铁律）。空对/未闭合
    的标记形也会被抓：只见到 BEGIN 没见到 END 时该段不计入（交给 compute 侧按「无写盘口
    的标记形」判红）。
    """
    out: list[tuple[str, str]] = []
    for begin, end in AUTO_MARKERS:
        rest = text
        while begin in rest:
            _head, rest = rest.split(begin, 1)
            if end not in rest:
                break
            mid, rest = rest.split(end, 1)
            out.append((begin, mid))
    return out



def human_lines(text: str) -> list[str]:
    """管辖面「人写区」逐行：剥 front-matter、剥机器段、剥围栏代码块、剥行内码（席 S46）。"""
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
            out.append(_INLINE_CODE_RE.sub(" ", ln))
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
    lines: list[str],
    *,
    vocab: set[str] | None = None,
    check_enum: bool = True,
    known_fact_keys: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """纯判据：给人写区行，返回违规描述（喂真页与注毒同一支）。

    分段判据（席 S3 2026-09-22 治 F-3，只加严）：
    - **机器本地路径**先行判红，指针词不豁免（一律红）；
    - 其余四类：先摘除 `{{fact:…}}` 占位与指针短语整段，四把尺子对**残余**执法——
      一行里指针词与裸事实混写时，指针只豁免它自己承担的那部分语义。

    占位符摘除的条件化（席 S106 2026-09-22 治 W-1，只加严）：
    - `known_fact_keys=None`（缺省）＝旧行为，无条件摘除，**既有调用点逐字不变**；
    - 传集合（哪怕空集）＝只摘除在册规范形，不在册者**留在残余里照常记账**并另记
      `UNKNOWN_FACT_KEY`。页级取数走 `page_fact_findings()`，参数只从 `@schema` 来。
    """
    hits: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # 补录 R2-2（席 S46 拆分，治「一行同含阈值＋路径时后判被 elif 遮蔽」）：
        # 五把尺各自独立执法，一行多违规逐条记；机器本地路径仍是指针不豁免的一条尺。
        if FACT_MACHINE_PATH_RE.search(s):
            hits.append(f"裸机器本地路径：{s[:90]}")
        if known_fact_keys is None:
            dephrased = PLACEHOLDER_RE.sub(" ", s)
        else:
            for key in unknown_fact_keys(s, known_fact_keys):
                hits.append(
                    f"{UNKNOWN_FACT_KEY}：占位符 {{{{fact:{key}}}}} 不在该页声明模板的"
                    f" @schema 在册参数内（假指针）：{s[:90]}"
                )
            dephrased = strip_registered_placeholders(s, known_fact_keys)
        residual = AUTHORITY_PHRASE_RE.sub(" ", dephrased)

        residual_measure = MEASURE_IDIOM_RE.sub(" ", residual)
        if _HEADING_READTIME_RE.match(line):
            residual_measure = _HEADING_TRAIL_SEC_RE.sub(" ", residual_measure)
        if FACT_COUNT_RE.search(residual_measure):
            hits.append(f"裸计数：{s[:90]}")
        if FACT_THRESHOLD_RE.search(residual_measure):
            hits.append(f"裸阈值：{s[:90]}")
        if FACT_PATH_RE.search(residual):
            hits.append(f"裸路径：{s[:90]}")
        if check_enum and vocab:
            members = enum_members(residual)
            if len(members) >= ENUM_MIN_MEMBERS:
                known = sum(1 for m in members if m in vocab or m.strip("`") in vocab)
                if known >= ENUM_MIN_VOCAB_HITS:
                    hits.append(f"裸枚举清单（{len(members)} 枚并列、命中声明源 {known} 枚）：{s[:90]}")
    return hits
