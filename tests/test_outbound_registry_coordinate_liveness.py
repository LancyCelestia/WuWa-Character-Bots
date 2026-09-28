"""出站登记册（outbound_registry）坐标活性棘轮 —— 把「坐标是否还对得上」变成机器门。

席位 S47（中央调度收编波，2026-09-24 立）；锚层 2026-09-28 S-FIX-COORD-REANCHOR
（主任务板 #33 复锚批）按门首注记里诚实路径①把登记册整体改成**按符号名锚定**，
本门的判据真身随之扩为两层。

被检对象
--------
``plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py``
是一份「出站直发 / matcher / 调度族坐标登记册」。2026-09-28 复锚后，其**声明槽位**
（``location`` / ``register_location`` / ``add_job_locations``）一律登记符号锚，
形态 ``<relpath>::<symbol>[:<callee>]``：

- ``relpath`` 相对插件根 ``plugins/bot_unified_runtime/``（根装配文件即
  ``__init__.py``）；散文（note/evidence）里的行号只作「当时值」注记，不再作坐标。
- ``symbol`` 命中集＝目标文件 AST 里的 ``FunctionDef``/``AsyncFunctionDef``/
  ``ClassDef`` 名 ∪ ``Assign``/``AnnAssign`` 左值 ``Name``。
- 可选 ``callee`` 调用腿＝symbol 候选节点子树内存在 ≥1 个 ``Call``，其函数尾名
  （``Attribute.attr`` 或 ``Name.id``）等于 ``callee``，或其参数里出现常量字符串
  恰等于 ``callee``。

判据真身分两层：**行号坐标**的唯一真身＝本文件 ``judge_state``（五态），**符号锚**
的唯一真身＝本文件 ``resolve_anchor``（三态）；叙述文档一律以这两个函数为准，
不许照抄本 docstring。

本门做什么
----------
1. **静态解析**（``ast``；绝不 import 被检模块——它会拉起 ``domains.core.decision``
   包，属装配期副作用）登记册源码里的每一个字符串字面量：
   - 声明槽位按 ``ANCHOR_RE`` 抽符号锚位点，逐枚对被锚文件现算解析；
   - 全部位点（含散文）仍按 ``COORD_RE`` 抽 ``__init__.py:`` 行号位点，逐条现算
     比对根文件真身（旧行号机器整体保留，作遗留形态与注毒通路的活性证据）。
2. 行号位点五态（优先级：越界 > 空行 > 无锚 > 命中 > 不符）：

   - ``out_of_range``——行号越出 ``[1, 根文件行数]``（含 0 / 负数 / 99999999）；
   - ``blank``       —— 区间任一端落在**空行**（``strip()`` 后为空）上；
   - ``plausible``   —— 该行标识符里出现该条目**自己的锚名**（锚＝条目声明的
     ``name``/``family``/``api`` 字面量及其标识符；命中方式＝与行内 token 全等，
     或锚（长度 ≥5）是行内某 token 的子串，如 ``digest_push`` ⊂
     ``_register_digest_push_scheduler``）；
   - ``mismatch``    —— 有锚名可推、但该行一个都不含；
   - ``unanchored``  —— 拿不到锚名（文件级散文），且该行既未越界也非空行
     ——本门**无法**判其死活。

   符号锚位点三态：

   - ``anchor_resolved``   —— 目标文件存在、symbol 命中集（经 callee 腿过滤后）**恰一**；
   - ``anchor_unresolved`` —— 目标文件缺失/解析失败、或命中集为空（typo 名、无调用腿）；
   - ``anchor_ambiguous``  —— 命中集 ≥2（同名多定义且 callee 腿无法去歧义）。

   **违规 = out_of_range ∪ blank ∪ mismatch ∪ anchor_unresolved ∪ anchor_ambiguous。**
3. **只降不升棘轮**：四本账各一枚手写字面量上限 + ``AUDIT_HISTORY`` 方向锁 +
   「上限三值必须等于最近一次核账值」斥离锁（抬上限得先伪造整条历史，方向锁
   当场红）+ 扫描面下限锁 + 条目覆盖完整性锁（防「缩扫描面」造绿）+
   声明槽位全覆盖锁（声明槽里再出现行号坐标当场红。2026-09-29 S-FIX-COORD-POISON
   收紧：残差腿把「锚位点覆盖不到的任意 ``xxx.py:数字`` 形态」逐枚点名——旧
   行号机器只认 ``__init__.py:`` 前缀，非根文件行号坐标塞进声明槽曾对全部账与
   派生锁失明（注毒⑨），该豁免自此关闭）。
4. **族级派生腿**：每个调度族 register 锚的被锚 def 子树里 ``add_job`` 调用数必须
   恰等于该族登记的 jobs 锚枚数，且每枚 jobs 锚＝register 锚 + ``:add_job``；
   matcher 锚必须逐枚等于派生式 ``f"__init__.py::{name}:{matcher_type}"``。
   这两条把「登记」与「代码形状」的同步义务钉在门侧。
5. **自证九腿**（全部跑真身文本，不测手写夹具）：
   注毒①＝把真身里真实且**唯一**的 campus 符号锚的 symbol 改错 ⇒ 该位点判
   ``anchor_unresolved``、主账恰 +1、顶破上限；
   注毒②＝把其 callee 腿改成不存在的调用名 ⇒ 同样 ``anchor_unresolved`` +1；
   注毒③＝把整枚锚替换成**现算出来的根文件二命中符号名**（不写死）⇒ 判
   ``anchor_ambiguous`` +1；
   注毒④＝把整枚锚替换成 ``__init__.py:99999999``（旧行号形态）⇒ 旧判据判
   ``out_of_range`` +1——证明行号机器仍在线；
   注毒⑤＝替换成**现算出来的真实空行行号** ⇒ 判 ``blank``、空行账与主账各恰 +1；
   注毒⑥（漂移免疫腿）＝根文件现读文本**前插一行**再复算 ⇒ 声明账逐值不动、
   活账仍等于上限——符号锚不随根插删漂移，这正是本批复锚的卖点；
   注毒⑦（等式锁腿）＝campus location 换成另一枚**可解析**的 matcher 锚 ⇒ 主账
   不动（0 违规），派生等式锁恰点一枚失同步——等式锁是主账之外的独立陷阱；
   注毒⑧（count 锁腿）＝send_queue 族 jobs 锚复制一枚 ⇒ 两锚各自 resolved、主账
   不动，族级 count 腿恰点一处断链——拦「同串重复」形态下的枚数失同步。
   注毒⑨（盲区补锁腿，2026-09-29 S-FIX-COORD-POISON）＝直发条目 location 锚整枚
   换成**非根行号坐标**（``file_gateway.py:<现算空行>``）⇒ 旧行号机器只认
   ``__init__.py:``、此形态在声明槽造不出任何位点（三账全 0、anchor_total −1
   而无一红、派生锁亦管不到直发槽）——全覆盖锁的残差腿必须恰点一枚并归属该条
   目；真身残差必须为空（盘上已脏则本腿先红）。
   放行腿＝未注毒的真身里 campus 那条必须 ``anchor_resolved``。

诚实边界（不得越过去叙述）
--------------------------
- ``anchor_resolved`` 只说「该符号在目标文件里恰有一个可去歧义的绑定」，**不说**
  「被锚节点就是那个语义真身」；它拦的是 typo、悬空腿、同名歧义这三类确定病。
- 同族多枚 ``:add_job`` 锚串允许**逐字重复**（一次 def 子树＝多处观察），区分义务
  由族级 count 派生腿承担，不许造伪区分符。
- **标签型条目**（``SchedulerEntry.family`` 如 ``unattributed_bare_add_jobs``）在
  行号判据下曾永判「锚名不可推」；符号锚按被锚函数名解析，标签只作身份不作锚。
- 散文（note/evidence）里的行号本就**不该登记**：本批把它们全部改成裸数字
  「当时值」注记（不带 ``__init__.py:`` 前缀），散文账现为零；再往散文里写
  ``__init__.py:N`` 形态坐标会被旧机器当场计红。
- 非根文件的**行号**坐标（``sender/onebot.py:444`` 一类历史注记）本门不判态、
  不进账，只计入 ``non_root_coordinate_sites`` 一个观察值；非根文件的**符号锚**
  （声明槽里的 ``domains/...py::x`` 形态）则照常解析、照常进账——尺子随登记册
  换锚而变强，不是变窄。此豁免只对散文注记成立：非根行号坐标若出现在**声明槽**
  （2026-09-29 前的真实盲区），由全覆盖锁残差腿当场点名（注毒⑨）。
- 本门是**静态**门：它红了只代表登记册在说谎，不代表线上行为坏了；反过来它
  绿了也**不**证明锚点语义精确（见上 ``anchor_resolved`` 的边界）。

复跑
----
.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s47-pyc \\
      ../ChatBot_Runtime/venv/Scripts/python.exe \\
      -m pytest tests/test_outbound_registry_coordinate_liveness.py \\
      -p no:cacheprovider --basetemp=$TEMP/s47-bt -q
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与被检件（尺身份）
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    REPO_ROOT
    / "plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py"
)
ROOT_INIT_PATH = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
#: 符号锚的 relpath 以此为根（``__init__.py`` 即根装配文件）。
PLUGIN_ROOT = REPO_ROOT / "plugins/bot_unified_runtime"

# ---------------------------------------------------------------------------
# 坐标形态与判据常量
# ---------------------------------------------------------------------------

#: 一个行号坐标位点 = 一处 ``__init__.py:`` 前缀 + 其后紧跟的行号列表（可含区间）。
COORD_RE = re.compile(r"__init__\.py:(\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*)")
#: 一个符号锚位点 = ``<relpath>::<symbol>[:<callee>]``（只在声明槽扫描）。
ANCHOR_RE = re.compile(
    r"([A-Za-z0-9_./-]+\.py)::([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_][A-Za-z0-9_]*))?"
)
NUM_TOKEN_RE = re.compile(r"\d+(?:-\d+)?")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: 任何 ``xxx.py:N`` 形态（含非根文件），用于「非根行号坐标只计数、不判态」。
ANY_COORD_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.py:\d")

#: 锚名做「锚 ⊂ 行内 token」子串命中时锚的最小长度——防 ``eat`` / ``wiki`` /
#: ``chat`` 这类短名在任意长标识符里撞中（短名只准全等命中）。
MIN_ANCHOR_SUBSTRING_LEN = 5

STATE_PLAUSIBLE = "plausible"
STATE_BLANK = "blank"
STATE_MISMATCH = "mismatch"
STATE_OUT_OF_RANGE = "out_of_range"
STATE_UNANCHORED = "unanchored"
STATE_ANCHOR_RESOLVED = "anchor_resolved"
STATE_ANCHOR_UNRESOLVED = "anchor_unresolved"
STATE_ANCHOR_AMBIGUOUS = "anchor_ambiguous"

ALL_STATES = (
    STATE_PLAUSIBLE,
    STATE_BLANK,
    STATE_MISMATCH,
    STATE_OUT_OF_RANGE,
    STATE_UNANCHORED,
    STATE_ANCHOR_RESOLVED,
    STATE_ANCHOR_UNRESOLVED,
    STATE_ANCHOR_AMBIGUOUS,
)
#: 违规 = 两类行号事实态 + 「有锚却一行都对不上」 + 两类锚解析失败态
VIOLATION_STATES = frozenset(
    {
        STATE_BLANK,
        STATE_OUT_OF_RANGE,
        STATE_MISMATCH,
        STATE_ANCHOR_UNRESOLVED,
        STATE_ANCHOR_AMBIGUOUS,
    }
)

ROLE_DECLARED = "declared"
ROLE_PROSE = "prose"

# ---------------------------------------------------------------------------
# 登记册构造器槽位（声明坐标字段 = 条目的「正身」坐标）
# ---------------------------------------------------------------------------

#: 构造器 → 承载坐标的字段名集合（字段名由登记册自身 AST 现推，另有结构锁比对）。
DECLARED_COORD_FIELDS: dict[str, frozenset[str]] = {
    "MatcherEntry": frozenset({"location"}),
    "DirectSendEntry": frozenset({"location"}),
    "SchedulerEntry": frozenset({"register_location", "add_job_locations"}),
    "sched": frozenset({"register_location", "add_job_locations"}),
}

#: ``sched(family, register, jobs, note)`` 形参 → 语义字段名。
SCHED_PARAM_TO_FIELD = {
    "family": "family",
    "register": "register_location",
    "jobs": "add_job_locations",
    "note": "note",
}

#: 条目身份字段（拼 owner 与锚名集合用；元组顺序即优先级）。
IDENTITY_FIELDS = ("name", "family", "api")

#: 构造器 → owner 前缀。
OWNER_PREFIX = {
    "MatcherEntry": "matcher",
    "DirectSendEntry": "direct",
    "SchedulerEntry": "scheduler",
    "sched": "scheduler",
    "RouteGroupEntry": "route_group",
}

#: 会被本门按槽位归类的构造器名（其余字符串一律算文件级散文）。
KNOWN_CALLS = frozenset({"MatcherEntry", "DirectSendEntry", "RouteGroupEntry", "sched"})

# ---------------------------------------------------------------------------
# 账本（手写字面量，只准降；任何改动须同批追加 AUDIT_HISTORY 且不得回升）
# ---------------------------------------------------------------------------
# 尺身份三元组（读数离开这三样就不成立）：
#   件   tests/test_outbound_registry_coordinate_liveness.py
#   函数 compute_ledger → Ledger.declared_violations / prose_violations /
#        blank_total / unanchored_total（2026-09-28 起 declared_violations 含锚态违规）
#   命令 见模块 docstring「复跑」段（同一解释器、同一判据、零夹具）
# 立门当次现算时刻 **2026-09-23T23:51:14Z（UTC）**（两钟同读，见 AUDIT_HISTORY
# 首行注）。此后根 ``__init__.py`` 每被插删一行，行号账就会整体变动——2026-09-28
# 复锚批按门首注记的诚实路径①把登记册声明槽改成符号锚，真降账到 (0, 0, 0)，
# 行号账自此只作遗留判据（散文中行号一律写「当时值」裸数字，不再成账）。
#
# 历史降账逐枚归因原样保留在下面各上限注记与 AUDIT_HISTORY 里（18/1/0 是
# 2026-09-27 SCHED-DRIFT 收编波留下的行号时代终账；本批把那 18 枚结构性
# label-type mismatch 全部换成可按符号自证的锚，−18 为本席复锚的账）。

#: 主账：声明坐标（location / register_location / add_job_locations）违规数上限。
#: 2026-09-24T07:37:51Z S174 复算降账 **76→72** 的注记原文保留在 AUDIT_HISTORY；
#: 2026-09-24T08:00:41Z 活账 18（余账全落 ``scheduler:*``，结构性 label-type）。
#: 2026-09-28 S-FIX-COORD-REANCHOR 复锚批降账 **18→0**（诚实路径①「按符号名锚
#: 定」）：登记册 50 枚 matcher、12 族 32 枚调度锚、25 枚直发锚共 107 处声明槽
#: 位点换成 ``file::symbol[:callee]`` 派生式，行号坐标整体退为附注；那 18 枚
#: 「坐标正确、锚名不可推」的 add_job/register 位点自此按被锚函数名解析、逐枚
#: anchor_resolved。⚠ 在飞免责（照实记）：落码当日根 __init__.py 被并发席持续
#: 改写（当日脏度 241/32 量级、HEAD 从 1815cc3 推进到 a4b1dbe），行号账若保留
#: 只会更烂；符号锚按**当前盘**解析且免后续漂移——本上限 0 是锚层的账，不是把
#: 行号层的债藏起来：行号机器整体在线（注毒④⑤仍走旧判据），散文行号已清为
#: 「当时值」注记。复算凭据见 AUDIT_HISTORY 末行（两钟同读）。
DECLARED_VIOLATION_CEILING = 0

#: 散文账：note/evidence 等条目内其它字符串里的行号违规数上限。
#: 历史原为 1（transport/dispatcher 两枚 ``__init__.py:5683-5750`` 叙述坐标之一
#: 判违规）。2026-09-28 S-FIX-COORD-REANCHOR 复锚批把散文里的行号改写为裸数字
#: 「当时值」注记（规则 10：历史值写「当时值」，不冒充现坐标），散文账 1→0。
#: 此后往散文写 ``__init__.py:N`` 形态＝当场红（注毒④演示旧机器仍在线）。
PROSE_VIOLATION_CEILING = 0

#: 空行账：坐标直指空行的位点数上限（最硬、零解释）。
#: 2026-09-24T08:00:41Z 起为 0（逐枚归因见下方原文注与 AUDIT_HISTORY）。
#: 2026-09-28 复锚批后声明槽不再有行号坐标，空行账只能由「新增行号坐标」或
#: 注毒⑤触发——本枚保持 0，零余量。
BLANK_SITE_CEILING = 0

#: 无锚账：判不了死活（非空、未越界、无锚名）的行号坐标枚数上限。
#: 2026-09-28 复锚批清光全部 ``__init__.py:`` 行号位点后 1→0：此后任何一条
#: 「谁也判不了死活」的行号坐标（含散文）都会当场红一次。
UNANCHORED_SITE_CEILING = 0

#: 扫描面下限（缩扫描面的反证）：声明位点数 / 全部位点数不许掉到此值以下。
#: 2026-09-28 复锚批只换坐标**形态**不摘条目：声明位点由 80 枚行号换为 107 枚
#: 符号锚（+26 来自复合锚展开），下限 80/82 一字未动、也未抬——锚面 ≥ 旧行号面
#: 即「未缩扫描面」的实证。
MIN_DECLARED_SITES = 80
MIN_ALL_SITES = 82

#: 登记册 matcher 条目数下限（完整性锁用：条目增减要显式同步本门）。
EXPECTED_MATCHER_ENTRIES = 50

#: 核账历史：(UTC 时刻, 主账违规, 散文账违规, 空行数)，逐列只准降。
AUDIT_HISTORY: tuple[tuple[str, int, int, int], ...] = (
    ("2026-09-23T23:51:14Z", 79, 1, 9),
    # 中央调度收编波根改动窗：主账/散文账逐列不动（79/1 即"几乎全漂"这笔债的原形），
    # 空行账 9→4 系本波根 `__init__.py` 多次纯插入后按现算收严。复算凭据见
    # `BLANK_SITE_CEILING` 上方注释（两钟同读 2026-09-24T04:53:14Z）。
    ("2026-09-24T04:53:14Z", 79, 1, 4),
    # R-4 随迁（S151）：主账 79→76（−1 纯跟随＝campus 按符号重锚；−3 枚含代改成分
    # ＝本来就漂约 1000 行的 matcher 被 R-4 推上空行后按符号重锚）、散文账 1→1、
    # 空行账 4→2（重锚 4 枚 + 后继改指 1 枚；余 2 枚为 R-4 之前的存量空行，未代改）。
    # 两钟同读 2026-09-24T07:11:15Z；尺＝本件 compute_ledger()；命令＝docstring「复跑」段。
    ("2026-09-24T07:11:15Z", 76, 1, 2),
    # R-4 后半刀（S174）：四枚直发条目（cookie 到期／入群欢迎／cookie 二维码／文档导出）
    # 改判 ABSORBED ⇒ 主账 76→72（−4 枚逐格由 mismatch 转 plausible：4823/5977/6284/6104，
    # 坐标改指唯一后继投递调用点 + 锚名换成在岗管线符号）。散文账 1→1、空行账 2→2、
    # 无锚账 1→1 一字未动；扫描面 80/82 未缩（未摘任何条目——摘牌会把 declared_total
    # 打到 76 而撞 MIN_DECLARED_SITES=80 下限，那是缩面不是降账）。
    # 两钟同读 2026-09-24T07:37:51Z；尺＝本件 compute_ledger()；命令＝docstring「复跑」段。
    ("2026-09-24T07:37:51Z", 72, 1, 2),
    # S174 复算收口（本席四枚落码后、同窗另一席的 matcher 按符号重锚也已在盘上时复量）：
    # 主账 72→18、散文账 1→1、空行账 2→0。**逐列归属**——本席只占 07:37:51Z 那 −4 枚
    # （四枚直发条目改判 ABSORBED + 坐标改指唯一后继调用点 4823/5977/6284/6104 + 锚名
    # 换成在岗管线符号，逐格现算 plausible 且在 08:00:41Z 复核仍在）；其后的 −54 枚与
    # 空行账 −2 枚（`matcher:commodities=5542`／`scheduler:reflection=2643`）**归同窗
    # 另一席**（登记册 mtime 07:44:44Z／07:53:27Z／08:00:00Z 三度被本席之外写入，
    # `matcher:weather_cron` 的 owner 名同期从登记册文本消失（改名或换锚，非删除——
    # 08:06:31Z 现算 matcher 声明坐标仍 50 枚／唯一 owner 50），18 枚余账现在全落
    # `scheduler:*`），本席不冒领、也未逐枚复核其定位真伪。扫描面 80/82 逐值未动。
    # ⚠ 若该批继续降账，本行之后仍会出现「上限 > 活账」⇒ `test_ceilings_have_no_reserved_slack`
    # 红一次，由该席按本件 docstring「复跑」段复算后自行追加（方向锁只准降，不拦）。
    # 两钟同读 2026-09-24T08:00:41Z；尺＝本件 compute_ledger()；命令＝docstring「复跑」段。
    ("2026-09-24T08:00:41Z", 18, 1, 0),
    # 批次归属自证（S181，续锚 S151 §5 存量死号的那一席）：上条 08:00:41Z 由门 owner
    # S174 记录，其 −54 主账 / −2 空行「归同窗另一席、未逐枚复核」——那一席即本席。现按
    # 两钟同读 2026-09-24T08:06:06Z 复量活账＝(18, 1, 0) 与上限逐值相等，追加此线认领该批并
    # 补方法学留痕（尺＝本件 compute_ledger()；命令＝docstring「复跑」段；全离线零夹具）。
    # 归属：46 枚 matcher 坐标（43xx/5xxx 段→51xx–86xx 段）按 AST 赋值左值 `NAME =
    # on_message/on_command/on_notice` 唯一命中重锚 ⇒ 45 mismatch→plausible ＋ commodities
    # 5542→6667 消一枚空行；scheduler 9 族 register 重锚 `_register_<family>_scheduler` 定义行
    # （6 族家族 token 内嵌函数名⇒plausible），add_job 重锚真 `scheduler.add_job(` 行、
    # reflection add_job 2643（空行）→2853 消另一枚空行；direct delete_msg→5371（call_api 撤回
    # 行）、read_path 六枚读 API 符号→真身调用行 ⇒ 两枚 plausible。**余 18 枚全落 scheduler:\*，
    # 系结构性 label-type mismatch**（add_job 单行为多调用的 `scheduler.add_job(`、家族标签在下
    # 一行；send_queue_worker/reminder_delivery/unattributed_bare_add_jobs 家族字面量非函数名
    # token，后两者全根 0 命中）——坐标均已校正到真身、按单行判据取不到家族锚名，本席**未**去撞
    # `id="bot_send_queue_worker"` 一类字符串行刷 plausible（裸串命中＝本波已证伪形态）。扫描面
    # 80/82 逐值未动、未摘任何条目、未抬任何基线；登记值为落码后盘上真值，非预填。
    ("2026-09-24T08:06:06Z", 18, 1, 0),
    # SCHED-DRIFT 收编波（席位 S-REANCHOR-SCHED，2026-09-27 安静窗单席一次性重锚，只动登记册调度区
    # 24 枚 __init__.py 坐标字面量＋注记，零根改动）：调度族坐标随 ed802d3／5a85a5c 两波根位移整体
    # 漂移（1621–2004 段声明=真身+1、2821–4873 段声明=真身−3），现算活账 21 超上限 18、本门两试转红
    # （前读数与逐枚差集见 .superpowers/sdd/2026-09-27-fullload/reports/SCHED-DRIFT-AUDIT.md §1/§3）。
    # 按门修法（方案甲，附丙之留痕）逐枚按符号名现读重锚：register→`_register_*_scheduler` FunctionDef
    # 行（credential_check/today_history/kb_wiki_sync/reflection/digest_push/daily_assist 六枚回
    # def 行自证 plausible ⇒ 主账 −6）；add_job→该族 `scheduler.add_job(` 调用起始行（12 枚漂号校直、
    # 态不变）；unattributed 三枚→_register_nonebot_handlers 作用域内自由 add_job 行 4810/4873（实读
    # 首参 _channel_health_job／_cookie_expiry_reminder_job，全根 def 名册核对不隶属任何 _register_*）；
    # 另 reflection 2860/2875、digest_push 3367 三枚「漂 +1 恰落含家族 token 参数行」的侥幸位点一并
    # 校直到调用起始行⇒改判结构性 mismatch ⇒ 主账 +3。21−6+3=**18**＝现判据下不可再降的结构性地板
    # （15 枚 add_job 行无家族锚名＋3 枚家族标签非函数名 token 的 register，归属与裁决同 S181 行注）。
    # 无符号消失⇒无摘牌；散文账 1→1、空行账 0→0、无锚账 1→1、扫描面 declared_total 80／all_total 82
    # 逐值未动；**上限 18 一枚未抬**（现算==上限，零余量锁、方向锁、斥离锁、时序锁全数复位）。
    # 前后读数原文：复算前活账 (21,1,0)（SCHED-DRIFT-AUDIT §1 实跑 2 failed 原文）；复算后活账
    # (18,1,0)（17 passed）。尺＝本件 compute_ledger()；命令＝本件 docstring「复跑」段；全离线零夹具。
    # 两钟同读：`date -u` 与驱动脚本 `datetime.now(utc)` 同一次运行读数 2026-09-27T00:28:38Z／
    # 00:28:39Z（相邻秒，同一本账现算）。
    ("2026-09-27T00:28:39Z", 18, 1, 0),
    # S-FIX-COORD-REANCHOR 复锚批（2026-09-28，主任务板 #33；只动登记册声明槽字面量＋
    # 散文注记与本门，零根改动、零条目摘除）：按门首注记诚实路径①把登记册整体改为按符号名
    # 锚定——50 枚 matcher（派生式 __init__.py::<name>:<matcher_type>）、12 族 register+jobs
    # （__init__.py::_register_<x>_scheduler[...]:add_job，非根三族按各自文件符号）、
    # 13 枚直发 25 锚（含 onebot 5 锚、读路径 9 锚复合串，" + " 分隔）共 107 处声明位点；
    # 散文里 2 枚 __init__.py:5683-5750 改写为裸数字「当时值」注记。现算活账
    # (18,1,0)→**(0,0,0)**：18 枚结构性 label-type mismatch 由符号锚按被锚函数名自证
    # （anchor_resolved）；散文 1→0；空行 0、无锚 1→0（行号位点清零）。扫描面 declared_total
    # 107／all_total 107 ≥ 下限 80/82，未缩；EXPECTED_MATCHER_ENTRIES 50 未动。新锁随批：
    # ANCHOR_RE 解析层＋三态＋VIOLATION、声明槽全覆盖锁、matcher 派生等式锁、族级 add_job
    # count 派生锁、注毒七腿＋漂移免疫腿（①typo②callee③动态歧义④旧越界⑤旧空行
    # ⑦等式锁⑧count 锁，逐条见本文件测试区）。⚠ 在飞免责：复算当日根
    # __init__.py 与登记册本体被并发席持续改写（登记册脏度 167/92 量级含并发注记），本批
    # 读数按落码瞬间当前盘现算，符号锚免后续漂移。尺＝本件 compute_ledger()；命令＝本件
    # docstring「复跑」段；全离线零夹具。两钟同读：`date -u` 与驱动脚本
    # `datetime.now(utc)` 同一次运行读数 2026-09-28T10:22:56Z／2026-09-28T10:22:56Z
    # （同秒；declared_total 107／all_total 107／anchor_total 107，违规三值 0/0/0，
    # 无锚 0——现算==落码==复跑三值留痕）。
    ("2026-09-28T10:22:56Z", 0, 0, 0),
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoordSite:
    """登记册里的一处坐标位点（一个 ``__init__.py:`` 前缀或一枚符号锚 = 一处）。"""

    raw: str
    owner: str
    field_name: str
    role: str
    line_numbers: tuple[int, ...]
    anchors: frozenset[str]
    state: str = STATE_UNANCHORED
    #: 承载它的字符串前 60 字（可复核「是谁说的这句话」）
    host: str = ""
    #: 符号锚三元组（行号位点为空串）
    anchor_relpath: str = ""
    anchor_symbol: str = ""
    anchor_callee: str = ""

    @property
    def is_violation(self) -> bool:
        return self.state in VIOLATION_STATES

    @property
    def label(self) -> str:
        return f"{self.owner}.{self.field_name}={self.raw}→{self.state}"


# ---------------------------------------------------------------------------
# 符号锚解析（纯静态，零 import 被检件）
# ---------------------------------------------------------------------------


def _build_anchor_index(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """符号命中集＝def/class 名 ∪ Assign/AnnAssign 左值 Name（含嵌套节点）。"""
    index: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            index.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    index.setdefault(target.id, []).append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            index.setdefault(node.target.id, []).append(node)
    return index


def _call_tail_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _has_call_leg(node: ast.AST, callee: str) -> bool:
    """callee 腿：节点子树内存在 ≥1 个 Call，尾名相等或参数常量字符串相等。"""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if _call_tail_name(sub) == callee:
            return True
        for arg in list(sub.args) + [kw.value for kw in sub.keywords]:
            if isinstance(arg, ast.Constant) and arg.value == callee:
                return True
    return False


def _anchor_index_for(path: Path, cache: dict[Path, dict[str, list[ast.AST]] | None]):
    if path in cache:
        return cache[path]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        cache[path] = None
        return None
    index = _build_anchor_index(tree)
    cache[path] = index
    return index


def resolve_anchor(
    relpath: str,
    symbol: str,
    callee: str,
    cache: dict[Path, dict[str, list[ast.AST]] | None] | None = None,
) -> str:
    """符号锚三态判据唯一真身。

    优先级：目标文件缺失/解析失败 ⇒ unresolved；symbol 命中集（经 callee 腿
    过滤后）恰一 ⇒ resolved；空 ⇒ unresolved；≥2 ⇒ ambiguous。
    """
    shared = cache if cache is not None else {}
    index = _anchor_index_for(PLUGIN_ROOT / relpath, shared)
    if index is None:
        return STATE_ANCHOR_UNRESOLVED
    candidates = index.get(symbol, [])
    if callee:
        candidates = [node for node in candidates if _has_call_leg(node, callee)]
    if len(candidates) == 1:
        return STATE_ANCHOR_RESOLVED
    if not candidates:
        return STATE_ANCHOR_UNRESOLVED
    return STATE_ANCHOR_AMBIGUOUS


# ---------------------------------------------------------------------------
# 行号判据（遗留层，保留作注毒通路与历史证据）
# ---------------------------------------------------------------------------


def _strip_lineno(text: str) -> tuple[int, ...]:
    """把 ``4440-4444`` / ``949,1014`` 展成行号元组（区间取两端，够用且可判）。"""
    numbers: list[int] = []
    for token in NUM_TOKEN_RE.findall(text):
        if "-" in token:
            start, _, end = token.partition("-")
            numbers.extend([int(start), int(end)])
        else:
            numbers.append(int(token))
    return tuple(numbers)


def _anchors_for(*values: str) -> frozenset[str]:
    """条目自证锚名集合 = 条目自己声明的身份串 + 其中的标识符。"""
    anchors: set[str] = set()
    for value in values:
        text = (value or "").strip()
        if not text:
            continue
        anchors.add(text)
        anchors.update(IDENT_RE.findall(text))
    anchors.discard("")
    return frozenset(anchors)


def judge_state(
    numbers: tuple[int, ...],
    anchors: frozenset[str],
    root_lines: list[str],
    blank_lines: frozenset[int],
) -> str:
    """五态判据唯一真身（顺序即优先级：越界 > 空行 > 无锚 > 命中 > 不符）。"""
    total = len(root_lines)
    if any(number < 1 or number > total for number in numbers):
        return STATE_OUT_OF_RANGE
    if any(number in blank_lines for number in numbers):
        return STATE_BLANK
    if not anchors or not numbers:
        return STATE_UNANCHORED
    for number in numbers:
        tokens = set(IDENT_RE.findall(root_lines[number - 1]))
        for anchor in anchors:
            if anchor in tokens:
                return STATE_PLAUSIBLE
            if len(anchor) >= MIN_ANCHOR_SUBSTRING_LEN and any(
                anchor in token for token in tokens
            ):
                return STATE_PLAUSIBLE
    return STATE_MISMATCH


def _class_field_order(tree: ast.Module) -> dict[str, list[str]]:
    """从登记册自身 AST 推 dataclass 字段顺序（槽位表不许凭记忆写）。"""
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names: list[str] = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.append(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    names.extend(t.id for t in stmt.targets if isinstance(t, ast.Name))
            out[node.name] = names
    return out


def _func_param_order(tree: ast.Module) -> dict[str, list[str]]:
    return {
        node.name: [arg.arg for arg in node.args.args]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _string_leaves(node: ast.AST) -> list[str]:
    """取一个表达式里的全部字符串字面量（含元组 / 隐式拼接 / 括号包裹）。"""
    return [
        sub.value
        for sub in ast.walk(node)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
    ]


def _call_name(call: ast.Call) -> str:
    callee = call.func
    if isinstance(callee, ast.Name):
        return callee.id
    if isinstance(callee, ast.Attribute):
        return callee.attr
    return ""


def _slot_names(
    callee_name: str,
    class_fields: dict[str, list[str]],
    func_params: dict[str, list[str]],
) -> list[str]:
    """构造器位置参数 → 语义字段名（sched 走形参映射，dataclass 走字段顺序）。"""
    if callee_name == "sched":
        return [SCHED_PARAM_TO_FIELD.get(p, p) for p in func_params.get("sched", [])]
    return list(class_fields.get(callee_name, []))


def _entry_identity(fields: list[str], values: dict[str, str]) -> str:
    for key in IDENTITY_FIELDS:
        if values.get(key):
            return values[key]
    if fields and values.get(fields[0]):
        return values[fields[0]]
    return "unknown"


def _collect_slot_leaves(
    call: ast.Call, fields: list[str]
) -> tuple[dict[str, list[list[str]]], dict[str, str]]:
    """位置+关键字参统一成 槽位→叶子串列表；values 取每槽首叶（身份用）。"""
    by_slot: dict[str, list[list[str]]] = {}
    values: dict[str, str] = {}
    for index, arg in enumerate(call.args):
        slot = fields[index] if index < len(fields) else f"arg{index}"
        leaves = _string_leaves(arg)
        by_slot.setdefault(slot, []).extend(leaves)
        if leaves and slot not in values:
            values[slot] = leaves[0]
    for keyword in call.keywords:
        slot = keyword.arg or "keyword"
        leaves = _string_leaves(keyword.value)
        by_slot.setdefault(slot, []).extend(leaves)
        if leaves and slot not in values:
            values[slot] = leaves[0]
    return by_slot, values


def collect_sites(registry_source: str, root_lines: list[str]) -> list[CoordSite]:
    """现算：抽登记册全部坐标位点（符号锚 + 遗留行号）并逐条判态。"""
    tree = ast.parse(registry_source)
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)
    blank_lines = frozenset(
        index + 1 for index, line in enumerate(root_lines) if not line.strip()
    )
    anchor_cache: dict[Path, dict[str, list[ast.AST]] | None] = {}
    sites: list[CoordSite] = []
    claimed_constant_ids: set[int] = set()

    def record_lines(
        value: str,
        role: str,
        owner: str,
        field_name: str,
        anchors: frozenset[str],
    ) -> None:
        for match in COORD_RE.finditer(value):
            numbers = _strip_lineno(match.group(1))
            sites.append(
                CoordSite(
                    raw=match.group(0),
                    owner=owner,
                    field_name=field_name,
                    role=role,
                    line_numbers=numbers,
                    anchors=anchors,
                    state=judge_state(numbers, anchors, root_lines, blank_lines),
                    host=value[:60],
                )
            )

    def record_anchors(
        value: str,
        role: str,
        owner: str,
        field_name: str,
        anchors: frozenset[str],
    ) -> None:
        for match in ANCHOR_RE.finditer(value):
            relpath, symbol, callee = match.group(1), match.group(2), match.group(3) or ""
            sites.append(
                CoordSite(
                    raw=match.group(0),
                    owner=owner,
                    field_name=field_name,
                    role=role,
                    line_numbers=(),
                    anchors=anchors,
                    state=resolve_anchor(relpath, symbol, callee, anchor_cache),
                    host=value[:60],
                    anchor_relpath=relpath,
                    anchor_symbol=symbol,
                    anchor_callee=callee,
                )
            )

    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        callee_name = _call_name(call)
        if callee_name not in KNOWN_CALLS:
            continue
        fields = _slot_names(callee_name, class_fields, func_params)
        declared_fields = DECLARED_COORD_FIELDS.get(callee_name, frozenset())
        by_slot, values = _collect_slot_leaves(call, fields)
        identity = _entry_identity(fields, values)
        owner = f"{OWNER_PREFIX.get(callee_name, callee_name)}:{identity}"
        anchors = _anchors_for(identity)
        for slot, leaves in by_slot.items():
            role = ROLE_DECLARED if slot in declared_fields else ROLE_PROSE
            for leaf in leaves:
                if slot in declared_fields:
                    record_anchors(leaf, role, owner, slot, anchors)
                record_lines(leaf, role, owner, slot, anchors)
        for sub in ast.walk(call):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                claimed_constant_ids.add(id(sub))

    # 未被任何在册构造器覆盖的字符串 = 文件级散文（模块 docstring、注释旁证、
    # TransportEntry 的 evidence 等）：拿不到条目锚名，只判两类事实态。
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in claimed_constant_ids:
                continue
            record_lines(node.value, ROLE_PROSE, "file-level", "file-prose", frozenset())

    return sites


def read_registry_source() -> str:
    return REGISTRY_PATH.read_text(encoding="utf-8")


def read_root_lines() -> list[str]:
    return ROOT_INIT_PATH.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# 账目
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ledger:
    declared_total: int
    declared_violations: int
    prose_violations: int
    unanchored_total: int
    blank_total: int
    out_of_range_total: int
    all_total: int
    non_root_coordinate_sites: int
    state_counts: dict[str, int]
    sites: tuple[CoordSite, ...]
    anchor_total: int = 0
    anchor_violations: int = 0

    def declared_sites(self) -> tuple[CoordSite, ...]:
        return tuple(site for site in self.sites if site.role == ROLE_DECLARED)

    def prose_sites(self) -> tuple[CoordSite, ...]:
        return tuple(site for site in self.sites if site.role == ROLE_PROSE)


def count_non_root_coordinates(registry_source: str) -> int:
    """非根文件**行号**坐标枚数（只观察、不判态、不进账；锚层不进此账）。"""
    total = 0
    for value in _string_leaves(ast.parse(registry_source)):
        total += max(0, len(ANY_COORD_RE.findall(value)) - len(COORD_RE.findall(value)))
    return total


def compute_ledger(
    registry_source: str | None = None,
    root_lines: list[str] | None = None,
) -> Ledger:
    """把真身（或注毒后的真身副本）算成一本可复算的账。"""
    source = read_registry_source() if registry_source is None else registry_source
    lines = read_root_lines() if root_lines is None else root_lines
    sites = collect_sites(source, lines)
    declared = [site for site in sites if site.role == ROLE_DECLARED]
    prose = [site for site in sites if site.role == ROLE_PROSE]
    anchors = [site for site in sites if site.anchor_symbol]
    state_counts: dict[str, int] = {state: 0 for state in ALL_STATES}
    for site in sites:
        state_counts[site.state] = state_counts.get(site.state, 0) + 1
    return Ledger(
        declared_total=len(declared),
        declared_violations=sum(1 for site in declared if site.is_violation),
        prose_violations=sum(1 for site in prose if site.is_violation),
        unanchored_total=state_counts[STATE_UNANCHORED],
        blank_total=state_counts[STATE_BLANK],
        out_of_range_total=state_counts[STATE_OUT_OF_RANGE],
        all_total=len(sites),
        non_root_coordinate_sites=count_non_root_coordinates(source),
        state_counts=state_counts,
        sites=tuple(sites),
        anchor_total=len(anchors),
        anchor_violations=sum(1 for site in anchors if site.is_violation),
    )


# ---------------------------------------------------------------------------
# 主账棘轮（四本账，只准降）
# ---------------------------------------------------------------------------


def test_declared_coordinate_violations_within_ceiling() -> None:
    """主账：登记册「正身坐标」的违规数只准降（行号三态 ∪ 锚解析两态）。"""
    ledger = compute_ledger()
    worst = [site.label for site in ledger.declared_sites() if site.is_violation][:6]
    assert ledger.declared_violations <= DECLARED_VIOLATION_CEILING, (
        f"声明坐标违规 {ledger.declared_violations} > 上限 "
        f"{DECLARED_VIOLATION_CEILING}＝又漂/又坏了（符号失效、同名歧义或新增行号死坐标）。"
        f"修法：按符号名重定位后刷新登记，并追加 AUDIT_HISTORY（样例：{worst}）"
    )


def test_prose_coordinate_violations_within_ceiling() -> None:
    """散文账（note/evidence 里的行号）另立一本，不混主账、也不许长。"""
    ledger = compute_ledger()
    worst = [site.label for site in ledger.prose_sites() if site.is_violation][:6]
    assert ledger.prose_violations <= PROSE_VIOLATION_CEILING, (
        f"散文坐标死号 {ledger.prose_violations} > 上限 "
        f"{PROSE_VIOLATION_CEILING}＝note/evidence 里又写了行号坐标（应写裸数字当时值）"
        f"（样例：{worst}）"
    )


def test_blank_line_coordinates_within_ceiling() -> None:
    """最硬的一类：坐标直指空行。这类数不许长（零解释、不依赖锚名）。"""
    ledger = compute_ledger()
    roster = [site.label for site in ledger.sites if site.state == STATE_BLANK]
    assert ledger.blank_total <= BLANK_SITE_CEILING, (
        f"空行坐标 {ledger.blank_total} > 上限 {BLANK_SITE_CEILING}（名册：{roster}）"
    )


def test_unanchored_sites_within_ceiling() -> None:
    """无锚坐标（判不了死活的行号位点）单独钉住枚数——新增一条就红一次。"""
    ledger = compute_ledger()
    roster = [site.label for site in ledger.sites if site.state == STATE_UNANCHORED]
    assert ledger.unanchored_total <= UNANCHORED_SITE_CEILING, (
        f"无处可验的行号坐标位点 {ledger.unanchored_total} > 上限 "
        f"{UNANCHORED_SITE_CEILING}＝又添了「谁也判不了死活」的行号（名册：{roster}）"
    )


def test_anchor_violations_within_declared_ceiling() -> None:
    """锚层单账：符号解析失败（unresolved ∪ ambiguous）全落在声明槽，逐值对齐上限。"""
    ledger = compute_ledger()
    assert ledger.anchor_violations == ledger.declared_violations, (
        f"锚违规 {ledger.anchor_violations} ≠ 主账 {ledger.declared_violations}"
        "＝声明槽里混进了行号死坐标（覆盖锁会另红，此处防两本账互相藏污）"
    )


# ---------------------------------------------------------------------------
# 造绿防线：扫描面下限 + 条目覆盖完整性 + 声明槽全覆盖 + 派生形状锁
# ---------------------------------------------------------------------------


def test_scan_scope_did_not_collapse() -> None:
    """坐标位点总数不许掉——掉＝扫描面被改窄，而不是账变好了。"""
    ledger = compute_ledger()
    assert ledger.declared_total >= MIN_DECLARED_SITES, (
        f"声明坐标位点只剩 {ledger.declared_total} < 下限 {MIN_DECLARED_SITES}"
        "＝扫描面被缩（正则 / 角色面改窄），或登记条目被整批删除而未同步本门"
    )
    assert ledger.all_total >= MIN_ALL_SITES, (
        f"全部坐标位点只剩 {ledger.all_total} < 下限 {MIN_ALL_SITES}＝扫描面被缩"
    )


def test_every_entry_is_reached_by_the_scan() -> None:
    """扫描面完整性：三类在册构造器都得到过坐标，且没有任何声明位点无归属。

    漏一类构造器 = 那本条目永不进账；这不会被下限锁抓到（总数够大也会漏），
    所以按 owner 前缀逐类点名，并加一条「分类必须穷尽声明账」的闭合断言。
    复锚后登记册正文里可能已无文件级行号散文位点，故「文件级那一层存在性」
    改用一次微探测证明扫描通道在线（合成源串只验通路，不进任何账）。
    """
    ledger = compute_ledger()
    declared = ledger.declared_sites()
    probe = collect_sites('x = ("__init__.py:1")', ["first line"])
    assert any(site.owner == "file-level" for site in probe), (
        "文件级散文层在本门扫描里漏了＝有人改了 collect_sites 而没同步本锁"
    )
    matcher_sites = [site for site in declared if site.owner.startswith("matcher:")]
    assert len(matcher_sites) >= EXPECTED_MATCHER_ENTRIES, (
        f"matcher 声明坐标位点 {len(matcher_sites)} < 下限 "
        f"{EXPECTED_MATCHER_ENTRIES}＝有 matcher 坐标没被扫到（扫描面被缩）；"
        f"若登记册确实删了条目，请同步 EXPECTED_MATCHER_ENTRIES 并留注说明"
    )
    assert len({site.owner for site in matcher_sites}) == len(matcher_sites), (
        "两个 matcher 条目同名 → owner 冲撞，账不再可归因（登记册需给出唯一 name）"
    )
    scheduler_sites = [s for s in declared if s.owner.startswith("scheduler:")]
    direct_sites = [s for s in declared if s.owner.startswith("direct:")]
    assert scheduler_sites, "调度族声明坐标一条都没扫到＝扫描面漏了一整类"
    assert direct_sites, "直发条目声明坐标一条都没扫到＝扫描面漏了一整类"
    unclassified = [
        site
        for site in declared
        if not site.owner.startswith(("matcher:", "scheduler:", "direct:"))
    ]
    assert not unclassified, (
        f"声明账里出现无归属 owner：{[site.label for site in unclassified]}"
        "＝DECLARED_COORD_FIELDS 扩了新构造器而扫描未跟上"
    )


def _declared_line_coord_residue(registry_source: str) -> list[str]:
    """声明槽残差探测（2026-09-29 S-FIX-COORD-POISON 加的腿）：任何未被
    ``ANCHOR_RE`` 位点跨度覆盖的 ``xxx.py:数字`` 坐标＝「该是锚位点而不再是锚」。

    旧行号机器只认 ``__init__.py:`` 前缀（COORD_RE），声明槽里混进
    ``domains/...py:N`` 一类非根行号坐标时**造不出任何位点**，三账、派生锁与
    原 leftovers 判据全体失明（注毒⑨钉住本判据的牙）。本腿走与 collect_sites
    同一套槽位原语（构造器表/形参表/身份字段/两枚正则全部复用本文件常量），
    不另立第二口径；只准收紧、不许反向豁免。
    """
    tree = ast.parse(registry_source)
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)
    offenders: list[str] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        callee_name = _call_name(call)
        if callee_name not in KNOWN_CALLS:
            continue
        declared_fields = DECLARED_COORD_FIELDS.get(callee_name, frozenset())
        if not declared_fields:
            continue
        fields = _slot_names(callee_name, class_fields, func_params)
        by_slot, values = _collect_slot_leaves(call, fields)
        identity = _entry_identity(fields, values)
        owner = f"{OWNER_PREFIX.get(callee_name, callee_name)}:{identity}"
        for slot, leaves in by_slot.items():
            if slot not in declared_fields:
                continue
            for leaf in leaves:
                covered = bytearray(len(leaf))
                for anchor in ANCHOR_RE.finditer(leaf):
                    covered[anchor.start() : anchor.end()] = b"\x01" * (
                        anchor.end() - anchor.start()
                    )
                stray = [
                    match.group(0)
                    for match in ANY_COORD_RE.finditer(leaf)
                    if not all(covered[match.start() : match.end()])
                ]
                if stray:
                    offenders.append(f"{owner}.{slot}={stray}")
    return offenders


def test_declared_slots_are_fully_symbol_anchored() -> None:
    """全覆盖锁：声明槽里只准有符号锚——出现**任何文件**的行号坐标当场红。

    复锚批把「行号登记」这笔债从结构上关掉：这条锁防此后有人图省事往声明槽塞
    回行号（那会绕过 resolve_anchor 的同名歧义检查，把债重新点着）。
    2026-09-29 收紧（S-FIX-COORD-POISON）：原版只点名「已成位点的行号坐标」，
    对 COORD_RE 不认的非根形态（``domains/...py:N``）结构性失明——现加残差腿，
    锚位点跨度盖不住的 ``.py:数字`` 逐枚点名；只变严、未放松任何既有判据。
    """
    declared = compute_ledger().declared_sites()
    leftovers = [site.label for site in declared if not site.anchor_symbol]
    assert not leftovers, (
        f"声明槽混入行号坐标（复锚批后禁止）：{leftovers}＝请把该行号改成 "
        f"file::symbol[:callee] 派生式，行号只作「当时值」注记"
    )
    residue = _declared_line_coord_residue(read_registry_source())
    assert not residue, (
        f"声明槽出现锚外的行号坐标（旧行号机器盲区形态，残差腿已封口）：{residue}"
        "＝改成 ``file::symbol[:callee]`` 锚形态；裸「当时值」注记不该住在声明槽"
    )
    assert all(site.role == ROLE_DECLARED for site in declared)


def _matcher_derivation_mismatches(registry_source: str) -> tuple[list[str], int]:
    """matcher 派生等式检查体（锁与注毒腿共用同一判据真身）。"""
    tree = ast.parse(registry_source)
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)
    failures: list[str] = []
    checked = 0
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call) != "MatcherEntry":
            continue
        fields = _slot_names("MatcherEntry", class_fields, func_params)
        by_slot, _values = _collect_slot_leaves(call, fields)
        name_leaves = by_slot.get("name", [])
        location_leaves = by_slot.get("location", [])
        matcher_leaves = by_slot.get("matcher_type", [])
        assert len(name_leaves) == 1 and len(location_leaves) == 1, (
            "MatcherEntry 的 name/location 槽应恰一枚字符串叶"
        )
        expected = f"__init__.py::{name_leaves[0]}:{matcher_leaves[0]}"
        if location_leaves[0] != expected:
            failures.append(
                f"matcher `{name_leaves[0]}` location={location_leaves[0]!r} ≠ "
                f"派生式 {expected!r}"
            )
        checked += 1
    return failures, checked


def test_matcher_locations_equal_derived_anchor() -> None:
    """matcher 形状派生锁：每枚 location 必须恰等于 ``__init__.py::{name}:{matcher_type}``。

    等式由登记侧与门侧共同持有：改 name 或改 matcher_type 而不改 location，
    本条当场红——「登记-代码同步义务」不靠人肉记忆。
    """
    failures, checked = _matcher_derivation_mismatches(read_registry_source())
    assert not failures, f"location 与派生式失同步＝name/matcher_type 改了没跟 location：{failures}"
    assert checked == EXPECTED_MATCHER_ENTRIES, (
        f"MatcherEntry 枚数 {checked} ≠ {EXPECTED_MATCHER_ENTRIES}＝条目增减未同步本门"
    )


def _sched_family_count_failures(registry_source: str) -> tuple[list[str], int]:
    """族级 add_job count 检查体（锁与注毒腿共用同一判据真身）。"""
    tree = ast.parse(registry_source)
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)
    anchor_cache: dict[Path, dict[str, list[ast.AST]] | None] = {}
    failures: list[str] = []
    families = 0
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call) != "sched":
            continue
        fields = _slot_names("sched", class_fields, func_params)
        by_slot, _values = _collect_slot_leaves(call, fields)
        family = (by_slot.get("family", ["?"]))[0]
        register_leaves = by_slot.get("register_location", [])
        job_leaves = by_slot.get("add_job_locations", [])
        if len(register_leaves) != 1:
            failures.append(f"调度族 `{family}` register 槽非恰一枚字符串")
            families += 1
            continue
        register = register_leaves[0]
        match = ANCHOR_RE.fullmatch(register)
        if not match:
            failures.append(f"调度族 `{family}` register 锚非标准派生式：{register!r}")
            families += 1
            continue
        relpath, symbol = match.group(1), match.group(2)
        index = _anchor_index_for(PLUGIN_ROOT / relpath, anchor_cache)
        if index is None:
            failures.append(f"调度族 `{family}` 被锚文件缺失/解析失败：{relpath}")
            families += 1
            continue
        candidates = index.get(symbol, [])
        if len(candidates) != 1:
            failures.append(
                f"调度族 `{family}` register 锚 `{register}` 命中 {len(candidates)} 处（应恰一）"
            )
            families += 1
            continue
        add_job_calls = sum(
            1
            for sub in ast.walk(candidates[0])
            if isinstance(sub, ast.Call) and _call_tail_name(sub) == "add_job"
        )
        if add_job_calls != len(job_leaves):
            failures.append(
                f"调度族 `{family}` add_job 调用数 {add_job_calls} ≠ 登记 jobs 锚枚数 "
                f"{len(job_leaves)}＝族级派生断链（添/删 job 未同步登记册）"
            )
        for leaf in job_leaves:
            if leaf != f"{register}:add_job":
                failures.append(
                    f"调度族 `{family}` jobs 锚 {leaf!r} ≠ register 锚 + ':add_job'"
                )
        families += 1
    return failures, families


def test_scheduler_family_add_job_counts() -> None:
    """族级派生锁：每调度族 register 锚 def 子树里 add_job 调用数 == jobs 锚枚数，
    且每枚 jobs 锚逐字等于 register 锚 + ":add_job"。

    同族多枚 add_job 的锚串**允许逐字重复**（一次 AST 解析＝多处观察）；区分
    义务由本条的 count 腿承担。add_job 计数用 ``_call_tail_name`` 口径
    （``scheduler.add_job(...)``），不匹配字符串常量腿（家族标签 id= 一类）。
    """
    failures, families = _sched_family_count_failures(read_registry_source())
    assert not failures, f"族级 add_job 派生断链：{failures}"
    assert families == 12, f"调度族枚数 {families} ≠ 12＝族增减未同步本门"


def _own_module_assigned_values() -> dict[str, ast.expr]:
    source = Path(__file__).resolve().read_text(encoding="utf-8")
    assigned: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                assigned[target.id] = node.value
    return assigned


def test_ceilings_are_hand_written_literals() -> None:
    """结构锁：上限 / 下限必须是字面量整数，不许写成派生表达式。

    派生上限（``= compute_ledger().declared_violations``）会让本门结构性失效：
    被检对象动、上限跟着动，永远绿。
    """
    assigned = _own_module_assigned_values()
    for key in (
        "DECLARED_VIOLATION_CEILING",
        "PROSE_VIOLATION_CEILING",
        "BLANK_SITE_CEILING",
        "UNANCHORED_SITE_CEILING",
        "MIN_DECLARED_SITES",
        "MIN_ALL_SITES",
        "EXPECTED_MATCHER_ENTRIES",
    ):
        node = assigned.get(key)
        assert isinstance(node, ast.Constant) and isinstance(node.value, int), (
            f"{key} 被改成非字面量＝上限跟着被检对象动，本门失效"
        )
    history = assigned.get("AUDIT_HISTORY")
    assert isinstance(history, ast.Tuple) and len(history.elts) >= 1, (
        "AUDIT_HISTORY 必须留在本文件里且非空——它是「只准降」的对账凭据"
    )


def test_audit_history_never_rises() -> None:
    """方向锁：核账历史三列逐条非升。"""
    assert AUDIT_HISTORY, "核账历史不许为空"
    for index in range(1, len(AUDIT_HISTORY)):
        previous = AUDIT_HISTORY[index - 1]
        current = AUDIT_HISTORY[index]
        assert current[1:] <= previous[1:], (
            f"核账记录出现回升（方向锁）：{previous} → {current}"
        )


def test_audit_history_is_append_only_chronology() -> None:
    """时序锁：历史按时刻递增排列＝只能往后追加，不许往前插一条"更大的账"。

    没有这条，「在表头插一条 2027 年、违规 200 的记录、再把上限抬到 200」可以
    同时骗过方向锁与「上限不超过首届核账」锁。时刻格式固定 ISO-8601 UTC
    （``YYYY-MM-DDTHH:MM:SSZ``），字符串序即时间序。
    """
    stamps = [entry[0] for entry in AUDIT_HISTORY]
    assert stamps == sorted(stamps), (
        f"核账历史时刻不是递增（疑似表头插入或改写）：{stamps}"
    )
    assert len(set(stamps)) == len(stamps), f"核账时刻重复，账不可归因：{stamps}"


def test_ceilings_do_not_exceed_first_audit() -> None:
    """斥离锁之一：任何上限都不许高过首届核账值＝抬高上限换绿当场红。"""
    first = AUDIT_HISTORY[0]
    assert DECLARED_VIOLATION_CEILING <= first[1], (
        f"主账上限 {DECLARED_VIOLATION_CEILING} 超过首届核账 {first[1]}＝调大换绿"
    )
    assert PROSE_VIOLATION_CEILING <= first[2], (
        f"散文账上限 {PROSE_VIOLATION_CEILING} 超过首届核账 {first[2]}＝调大换绿"
    )
    assert BLANK_SITE_CEILING <= first[3], (
        f"空行账上限 {BLANK_SITE_CEILING} 超过首届核账 {first[3]}＝调大换绿"
    )


def test_ceilings_equal_latest_audit() -> None:
    """斥离锁之二：上限三值必须等于**最近一次**核账值。

    想动上限就得先追加一条核账，而追加受方向锁管——「悄悄把主账上限调大让新红
    过关」这条路要么缺记录、要么记录回升，两条都红。
    """
    latest = AUDIT_HISTORY[-1]
    ceiling_triple = (
        DECLARED_VIOLATION_CEILING,
        PROSE_VIOLATION_CEILING,
        BLANK_SITE_CEILING,
    )
    assert ceiling_triple == latest[1:], (
        f"上限三值 {ceiling_triple} 与最近一次核账 {latest[1:]} 不等"
        "＝改上限未同步核账（要么真降账、要么补记录，两条都得留痕）"
    )


def test_ceilings_have_no_reserved_slack() -> None:
    """零余量锁：上限必须等于**此刻现算**的违规数——预填宽裕基线当场红。

    这是唯一能拦住「改写历史那唯一一条记录 + 同步抬高上限」的锁：两者一起改
    能骗过方向锁 / 时序锁 / 等值锁，但骗不过"上限 == 活账"。

    本条在两个方向都会红，红法是设计的一部分：
    - 现算 **>** 上限 ⇒ 又坏了一批坐标（符号失效、歧义或新增行号死号）＝真债增加；
    - 现算 **<** 上限 ⇒ 登记册被降了账（好事），但必须复算后把上限改小并在
      ``AUDIT_HISTORY`` 末尾追加一条只降不升的记录，否则这本账就失去"当前值"
      的含义。复算命令＝模块 docstring「复跑」段。
    """
    ledger = compute_ledger()
    measured = (
        ledger.declared_violations,
        ledger.prose_violations,
        ledger.blank_total,
    )
    ceiling_triple = (
        DECLARED_VIOLATION_CEILING,
        PROSE_VIOLATION_CEILING,
        BLANK_SITE_CEILING,
    )
    assert measured == ceiling_triple, (
        f"活账 {measured} 与上限 {ceiling_triple} 不等（主账/散文账/空行账）。"
        f"变差→修锚；变好→复算后降上限并追加 AUDIT_HISTORY。"
        f"样例：{[site.label for site in ledger.declared_sites() if site.is_violation][:5]}"
    )
    assert ledger.unanchored_total <= UNANCHORED_SITE_CEILING


# ---------------------------------------------------------------------------
# 自证八腿：注毒必红 + 漂移免疫 + 派生锁注毒 + 已知活体放行（全跑真身文本）
# ---------------------------------------------------------------------------


def _campus_declared_site(sites: list[CoordSite]) -> CoordSite:
    matches = [
        site
        for site in sites
        if site.owner == "matcher:campus_record_matcher"
        and site.role == ROLE_DECLARED
        and site.field_name == "location"
    ]
    assert len(matches) == 1, f"campus 声明坐标应恰一处，现={len(matches)}"
    return matches[0]


def _poison_campus_literal(replacement: str) -> tuple[str, str]:
    """把真身里唯一的 campus 锚字面量换成 replacement，返回 (注毒源, 目标字面量)。"""
    source = read_registry_source()
    campus = _campus_declared_site(collect_sites(source, read_root_lines()))
    literal = f'"{campus.raw}"'
    assert source.count(literal) == 1, (
        f"注毒前提不成立：{literal} 在登记册里出现 {source.count(literal)} 次（应恰 1 次），"
        "本条会失去归因——换目标条目或改判据，别放宽本断言"
    )
    poisoned = source.replace(literal, f'"{replacement}"')
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    return poisoned, literal


def _assert_one_more_violation_breaks_ceiling(
    poisoned: str, expected_state: str
) -> None:
    baseline = compute_ledger()
    ledger = compute_ledger(poisoned, read_root_lines())
    assert _campus_declared_site(list(ledger.sites)).state == expected_state, (
        f"注毒后该位点未判 {expected_state}＝判据没真跑到源码"
    )
    assert ledger.declared_violations == baseline.declared_violations + 1, (
        f"注毒后主账未 +1：{baseline.declared_violations} → {ledger.declared_violations}"
    )
    assert ledger.declared_violations > DECLARED_VIOLATION_CEILING, (
        f"注毒未顶破上限 {DECLARED_VIOLATION_CEILING}＝上限里藏了余量"
    )


def test_known_live_campus_coordinate_is_anchor_resolved() -> None:
    """放行腿：未注毒的真身里，campus 那条（全册另有独立活性读者锁的那枚）判
    ``anchor_resolved``。"""
    sites = collect_sites(read_registry_source(), read_root_lines())
    campus = _campus_declared_site(sites)
    assert campus.state == STATE_ANCHOR_RESOLVED, (
        f"campus 锚 {campus.raw} 判为 {campus.state}——放行腿失效或该符号已改名/歧义"
    )


def test_poison_bad_symbol_is_caught() -> None:
    """注毒腿①（符号维度）：campus 锚 symbol 改错 ⇒ anchor_unresolved、主账恰 +1。"""
    poisoned, _literal = _poison_campus_literal(
        "__init__.py::campus_record_matcher_TYPO_BY_S58:on_message"
    )
    _assert_one_more_violation_breaks_ceiling(poisoned, STATE_ANCHOR_UNRESOLVED)


def test_poison_bad_callee_leg_is_caught() -> None:
    """注毒腿②（调用腿维度）：symbol 对、callee 改成不存在的调用名 ⇒ unresolved +1。

    ①验索引查空，②验 callee 腿过滤归零——两条走 resolve_anchor 的不同分支。
    """
    poisoned, _literal = _poison_campus_literal(
        "__init__.py::campus_record_matcher:on_flamingo_not_a_registrar"
    )
    _assert_one_more_violation_breaks_ceiling(poisoned, STATE_ANCHOR_UNRESOLVED)


def test_poison_ambiguous_symbol_is_caught() -> None:
    """注毒腿③（同名歧义维度）：campus 锚整枚换成**现算出来的**根文件二命中符号名
    （不写死，随根演化自更新）⇒ anchor_ambiguous、主账恰 +1。"""
    index = _anchor_index_for(ROOT_INIT_PATH, {})
    assert index, "根文件解析失败，注毒腿③失去素材"
    duplicates = sorted(name for name, nodes in index.items() if len(nodes) >= 2)
    assert duplicates, "根文件里找不到二命中符号名——本腿素材消失，请核查根解析"
    poisoned, _literal = _poison_campus_literal(f"__init__.py::{duplicates[0]}")
    _assert_one_more_violation_breaks_ceiling(poisoned, STATE_ANCHOR_AMBIGUOUS)


def test_poison_out_of_range_line_coordinate_is_still_caught() -> None:
    """注毒腿④（旧行号机器在线证据）：campus 锚整枚换成越界行号 ⇒ 旧判据仍红。

    复锚批没有拆行号机器——它保留作遗留/注毒通路。本腿同时证明「往声明槽塞回
    行号死坐标」会被抓到（全覆盖锁也会另红一次）。
    """
    poisoned, _literal = _poison_campus_literal("__init__.py:99999999")
    _assert_one_more_violation_breaks_ceiling(poisoned, STATE_OUT_OF_RANGE)
    baseline = compute_ledger()
    ledger = compute_ledger(poisoned, read_root_lines())
    assert ledger.out_of_range_total == baseline.out_of_range_total + 1


def test_poison_blank_line_coordinate_is_still_caught() -> None:
    """注毒腿⑤（旧空行判据在线证据）：campus 锚换成**现算出来的真实空行行号**
    ⇒ 判 blank、空行账与主账各恰 +1。空行号从根文件现算（不写死）。"""
    root_lines = read_root_lines()
    blank_numbers = [
        index + 1 for index, line in enumerate(root_lines) if not line.strip()
    ]
    assert blank_numbers, "根文件里没有空行，注毒腿⑤失去素材"
    poisoned, _literal = _poison_campus_literal(f"__init__.py:{blank_numbers[0]}")
    baseline = compute_ledger()
    ledger = compute_ledger(poisoned, root_lines)
    assert _campus_declared_site(list(ledger.sites)).state == STATE_BLANK
    assert ledger.blank_total == baseline.blank_total + 1, (
        f"注毒后空行账未 +1：{baseline.blank_total} → {ledger.blank_total}"
    )
    assert ledger.declared_violations == baseline.declared_violations + 1
    assert ledger.declared_violations > DECLARED_VIOLATION_CEILING, (
        f"注毒未顶破上限 {DECLARED_VIOLATION_CEILING}＝上限里藏了余量"
    )
    assert ledger.blank_total > BLANK_SITE_CEILING, (
        f"空行账未顶破上限 {BLANK_SITE_CEILING}＝该账上限藏了余量"
    )


def test_symbol_anchors_are_drift_immune() -> None:
    """漂移免疫腿：根文件现读文本前插一行（内存演算，不落盘）⇒ 声明账逐值不动、
    活账仍等于上限。行号时代「插一行、满盘红」的债，符号锚不还。"""
    base = compute_ledger()
    shifted = ["# drift probe (in-memory only, never written to disk)"] + read_root_lines()
    moved = compute_ledger(read_registry_source(), shifted)
    assert moved.anchor_total == base.anchor_total, "插一行就掉锚＝扫描面随根漂移"
    assert (
        moved.declared_violations
        == base.declared_violations
        == DECLARED_VIOLATION_CEILING
    ), "根插删一行即破坏活账＝复锚未生效（符号锚应免漂移）"
    assert (moved.prose_violations, moved.blank_total) == (
        base.prose_violations,
        base.blank_total,
    ), "散文/空行账随根漂移——散文里不该再有行号坐标"


def test_poison_matcher_derived_equality_is_caught() -> None:
    """注毒腿⑦（等式锁自证）：campus location 换成**另一枚可解析**的 matcher 锚
    ⇒ 主账抓不到（锚本身 resolved、违规 0），只准派生等式锁抓到恰一枚失同步。

    本腿证明等式锁是主账之外的**独立陷阱**：「指对别家的真坐标」这类登记错乱
    不进违规账，但破坏 name↔location 派生关系，等式锁当场点名。
    """
    source = read_registry_source()
    baseline = compute_ledger()
    campus = _campus_declared_site(list(baseline.sites))
    literal = f'"{campus.raw}"'
    assert source.count(literal) == 1, "注毒目标字面量在盘上不唯一"
    poisoned = source.replace(literal, '"__init__.py::dirty_guard_matcher:on_message"')
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    ledger = compute_ledger(poisoned, read_root_lines())
    assert (
        _campus_declared_site(list(ledger.sites)).state == STATE_ANCHOR_RESOLVED
        and ledger.declared_violations == baseline.declared_violations == 0
    ), "前提失真：换锚后本应仍可解析（主账 0），否则本腿没在验等式锁而在验主账"
    failures, checked = _matcher_derivation_mismatches(poisoned)
    assert len(failures) == 1 and checked == EXPECTED_MATCHER_ENTRIES, (
        f"等式锁未恰点一枚失同步（现={failures}）＝派生锁失效"
    )


def test_poison_family_add_job_count_is_caught() -> None:
    """注毒腿⑧（族级 count 锁自证）：send_queue 族 jobs 锚复制一枚（2 锚 vs 子树
    1 调用）⇒ 两锚各自 resolved、主账不动，只准 count 腿抓到恰一处断链。

    本腿证明 count 锁不是等式锁的复读：它拦的是「同串重复」形态下的**枚数**
    失同步（登记 2 枚而真身只挂 1 job / 反向漏登）。
    """
    source = read_registry_source()
    jobs_literal = '"__init__.py::_register_send_queue_scheduler:add_job"'
    assert source.count(jobs_literal) == 1, (
        f"注毒前提不成立：{jobs_literal} 现算 {source.count(jobs_literal)} 次命中（应恰 1）"
    )
    poisoned = source.replace(jobs_literal, f"{jobs_literal}, {jobs_literal}")
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    baseline = compute_ledger()
    ledger = compute_ledger(poisoned, read_root_lines())
    assert ledger.declared_violations == baseline.declared_violations == 0, (
        "前提失真：复制锚应仍全部 resolved（主账 0）"
    )
    failures, families = _sched_family_count_failures(poisoned)
    assert len(failures) == 1 and families == 12, (
        f"count 锁未恰点一处族级断链（现={failures}）＝族级派生锁失效"
    )


def test_poison_non_root_line_coordinate_in_declared_slot_is_caught() -> None:
    """注毒腿⑨（盲区补锁自证，2026-09-29 S-FIX-COORD-POISON）：直发条目的
    file_gateway 锚整枚换成**非根行号坐标**（``file_gateway.py:<现算空行号>``）。

    旧机器对该形态全体失明：COORD_RE 只认 ``__init__.py:`` 前缀、ANCHOR_RE 要
    ``::``，于是声明槽里这一枚坐标**造不出任何位点**——三账不动、matcher 等式锁
    与 sched count 锁都管不到直发槽。本腿先钉「失明属实」（前提失真说明补的是
    空气牙），再钉残差腿恰点一枚且归因到 ``direct:`` 条目；注毒只打内存副本，
    生产文件零接触。
    """
    source = read_registry_source()
    literal = '"domains/transport/sender/file_gateway.py::_deliver_onebot:call_api"'
    assert source.count(literal) == 1, "注毒前提不成立：直发 file_gateway 锚字面量盘上不唯一"
    root_lines = read_root_lines()
    blank_numbers = [
        index + 1 for index, line in enumerate(root_lines) if not line.strip()
    ]
    assert blank_numbers, "根文件没有空行，注毒⑨失去素材（与注毒⑤同材同源）"
    poisoned = source.replace(
        literal, f'"domains/transport/sender/file_gateway.py:{blank_numbers[0]}"'
    )
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    baseline = compute_ledger()
    ledger = compute_ledger(poisoned, root_lines)
    assert (
        ledger.declared_violations
        == ledger.prose_violations
        == ledger.blank_total
        == baseline.declared_violations
        == 0
    ), "前提失真：旧账应看不见这枚坐标；若旧账已能抓＝残差腿在补空气，删本腿前先复核"
    vanished = [
        site
        for site in ledger.declared_sites()
        if f"file_gateway.py:{blank_numbers[0]}" in site.raw
    ]
    assert not vanished, "前提失真：注毒位点仍造出位点＝失明前提不成立"
    assert ledger.anchor_total == baseline.anchor_total - 1, (
        f"锚面未随注毒恰减一枚（{baseline.anchor_total} → {ledger.anchor_total}）＝"
        "该位点根本不在锚面上，注毒目标已漂移，请重选直发锚"
    )
    offenders = _declared_line_coord_residue(poisoned)
    assert len(offenders) == 1 and offenders[0].startswith("direct:"), (
        f"残差腿未恰点一枚并归因直发条目（现={offenders}）＝2026-09-29 收紧未生效"
    )
    assert not _declared_line_coord_residue(source), (
        "真身残差非空＝盘上声明槽已混进锚外行号坐标，先修登记册再来谈注毒"
    )


def test_parser_slot_maps_match_registry_source() -> None:
    """结构锁：本门凭以归位的「构造器槽位表」必须与登记册自身定义一致。

    槽位表写错＝把 location 读成 note（或反向），整本账会静默错位，注毒腿甚至
    可能正好打在被错读的那一格上而看不出来。
    """
    tree = ast.parse(read_registry_source())
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)

    assert "location" in class_fields.get("MatcherEntry", []), (
        f"MatcherEntry 字段表漂移：{class_fields.get('MatcherEntry')}"
    )
    assert "location" in class_fields.get("DirectSendEntry", []), (
        f"DirectSendEntry 字段表漂移：{class_fields.get('DirectSendEntry')}"
    )
    assert set(class_fields.get("SchedulerEntry", [])) >= {
        "register_location",
        "add_job_locations",
    }, f"SchedulerEntry 字段表漂移：{class_fields.get('SchedulerEntry')}"
    assert func_params.get("sched") == ["family", "register", "jobs", "note"], (
        f"sched() 形参表漂移，SCHED_PARAM_TO_FIELD 需同步：{func_params.get('sched')}"
    )
    for callee, slots in DECLARED_COORD_FIELDS.items():
        available = _slot_names(callee, class_fields, func_params)
        assert available, f"登记册里找不到构造器 {callee} 的槽位表"
        assert slots <= set(available), (
            f"{callee} 的声明坐标字段 {sorted(slots)} 不在槽位表 {available} 里"
        )


def test_ledger_state_partition_is_recomputable() -> None:
    """每条坐标恰好一态，八态之和 == 位点总数；各账与逐条名册现数自洽。"""
    ledger = compute_ledger()
    assert sum(ledger.state_counts.values()) == ledger.all_total, (
        f"状态分区不闭合：{ledger.state_counts} vs 总数 {ledger.all_total}"
    )
    assert set(ledger.state_counts) == set(ALL_STATES), (
        f"状态值集合与本门声明不符：{sorted(set(ledger.state_counts))}"
    )
    declared = ledger.declared_sites()
    assert (
        sum(1 for site in declared if site.is_violation) == ledger.declared_violations
    ), "主账与逐条名册不自洽"
    assert (
        ledger.declared_total + len(ledger.prose_sites()) == ledger.all_total
    ), "角色分区不闭合（declared ∪ prose != 全部）"
    assert (
        sum(1 for site in ledger.prose_sites() if site.is_violation)
        == ledger.prose_violations
    ), "散文账与逐条名册不自洽"
    assert (
        ledger.state_counts[STATE_ANCHOR_RESOLVED]
        + ledger.state_counts[STATE_ANCHOR_UNRESOLVED]
        + ledger.state_counts[STATE_ANCHOR_AMBIGUOUS]
        == ledger.anchor_total
    ), "锚层三态不闭合"
