"""出站登记册（outbound_registry）坐标活性棘轮 —— 把「行号是否还对得上」变成机器门。

席位 S47（中央调度收编波，2026-09-24 立）。

被检对象
--------
``plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py``
是一份「出站直发 / matcher / 调度族坐标登记册」，条目以 ``__init__.py:N``、
``__init__.py:N-M``、``__init__.py:N,M,K`` 三种形态登记根装配文件的行号。根文件
每被插入或删除一行，这些数字就整体错位。此前**全树只有一枚坐标**（campus
matcher）有活性锁 ``tests/test_campus_digest.py::
test_outbound_registry_campus_coordinate_is_live``，其余无人复算。

本门做什么
----------
1. **静态解析**（``ast``；绝不 import 被检模块——它会拉起
   ``domains.core.decision`` 包，属装配期副作用）登记册源码里的**每一个字符串
   字面量**，抽出所有 ``__init__.py:`` 坐标位点，逐条现算比对根文件真身。
2. 每个位点恰好归入五态之一（判据唯一真身＝本文件 ``judge_state``，叙述文档
   一律以该函数为准，不许照抄本 docstring）：

   - ``out_of_range``——行号越出 ``[1, 根文件行数]``（含 0 / 负数 / 99999999）；
   - ``blank``       —— 区间任一端落在**空行**（``strip()`` 后为空）上；
   - ``plausible``   —— 该行标识符里出现该条目**自己的锚名**（锚＝条目声明的
     ``name``/``family``/``api`` 字面量及其标识符；命中方式＝与行内 token 全等，
     或锚（长度 ≥5）是行内某 token 的子串，如 ``digest_push`` ⊂
     ``_register_digest_push_scheduler``）；
   - ``mismatch``    —— 有锚名可推、但该行一个都不含；
   - ``unanchored``  —— 拿不到锚名（文件级散文），且该行既未越界也非空行
     ——本门**无法**判其死活。

   事实态（out_of_range / blank）优先于锚判定，且不依赖锚名存在。
   **违规 = out_of_range ∪ blank ∪ mismatch。**
3. **只降不升棘轮**：四本账各一枚手写字面量上限 + ``AUDIT_HISTORY`` 方向锁 +
   「上限三值必须等于最近一次核账值」斥离锁（抬上限得先伪造整条历史，方向锁
   当场红）+ 扫描面下限锁 + 条目覆盖完整性锁（防「缩扫描面」造绿）。
4. **自证两腿**（全部跑真身文本，不测手写夹具）：
   注毒①＝把真身里真实存在且**唯一**的 campus 登记坐标改成
   ``__init__.py:99999999`` ⇒ 该位点判 out_of_range、主账恰 +1；
   注毒②＝改成**现算出来的真实空行行号** ⇒ 判 blank、空行账与主账各恰 +1；
   放行＝未注毒的真身里 campus 那条必须 plausible。注毒走的是与主账同一个
   ``collect_sites``，改的是盘上真字面量。

诚实边界（不得越过去叙述）
--------------------------
- ``plausible`` 只说「该行含该条目自己的锚名」，**不说**「该行就是那个定义」。
  本门拦的是「坐标指向空行 / 越界 / 与锚名毫无关系」这三类确定死号。
- **标签型条目**（``SchedulerEntry.family`` 如 ``unattributed_bare_add_jobs``，
  或 ``api`` 为组合串）的锚名不是源码符号，其 ``mismatch`` 只说明「该行无自证
  锚名」，**不单独构成**「该坐标登记错了」的证据；这类位点在主账里照样计红，
  但报告里单列为「锚名不可推」待重锚。
- 散文（note/evidence）里的行号本就**不该登记**：它们是叙述，随根文件插删
  永久漂移，且多数无可推锚名。本门把它单列一本账，不混主账，免得「主账降了」
  被误读成「登记册健康了」。
- 非根文件坐标（``control_plane/dispatcher.py:162-220``、
  ``domains/meme/reactions/engine.py:754-782``、``sender/onebot.py:444,...`` 等）
  本门**不判态、不进账**，只计入 ``non_root_coordinate_sites`` 一个观察值——
  按本席 mandate 限定，尺子只量 ``__init__.py``。
- 本门是**静态**门：它红了只代表登记册在说谎，不代表线上行为坏了；反过来它
  绿了也**不**证明坐标精确（见上「plausible 不承诺精确定位」）。

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
from dataclasses import dataclass, field
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

# ---------------------------------------------------------------------------
# 坐标形态与判据常量
# ---------------------------------------------------------------------------

#: 一个坐标位点 = 一处 ``__init__.py:`` 前缀 + 其后紧跟的行号列表（可含区间）。
COORD_RE = re.compile(r"__init__\.py:(\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*)")
NUM_TOKEN_RE = re.compile(r"\d+(?:-\d+)?")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: 任何 ``xxx.py:N`` 形态（含非根文件），用于「非根坐标只计数、不判态」。
ANY_COORD_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.py:\d")

#: 锚名做「锚 ⊂ 行内 token」子串命中时锚的最小长度——防 ``eat`` / ``wiki`` /
#: ``chat`` 这类短名在任意长标识符里撞中（短名只准全等命中）。
MIN_ANCHOR_SUBSTRING_LEN = 5

STATE_PLAUSIBLE = "plausible"
STATE_BLANK = "blank"
STATE_MISMATCH = "mismatch"
STATE_OUT_OF_RANGE = "out_of_range"
STATE_UNANCHORED = "unanchored"

ALL_STATES = (
    STATE_PLAUSIBLE,
    STATE_BLANK,
    STATE_MISMATCH,
    STATE_OUT_OF_RANGE,
    STATE_UNANCHORED,
)
#: 违规态 = 两类确定死号 + 「有锚却一行都对不上」
VIOLATION_STATES = frozenset({STATE_BLANK, STATE_OUT_OF_RANGE, STATE_MISMATCH})

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
#        blank_total / unanchored_total
#   命令 见模块 docstring「复跑」段（同一解释器、同一判据、零夹具）
# 现算时刻 **2026-09-23T23:51:14Z（UTC）**（`date -u` 同刻读数 23:51:14；驱动脚本
# 内 `datetime.now(utc)` 读数 23:51:14Z——同一次运行的两个钟）。此后根
# ``__init__.py`` 每被插删一行，本账就会整体变动——那正是「行号登记」这笔债的
# 形状，本门不许它静默。想改下面几枚数字，只有两条诚实路径：
#   ① 把登记册改成按符号名锚定（真降账）→ 复算 → 追加 AUDIT_HISTORY；
#   ② 复算后追加一条只降不升的核账（留痕，方向锁 + 斥离锁双钉）。
# 下面几枚是立门当次的**真值**，不是理想值：违规之所以≈全部位点（79/80），
# 正因为登记册行号几乎全漂（逐条名册见本席报告 §2 与 `compute_ledger()`）。
#
# 2026-09-24T07:11:15Z 席位 S151 复算降账（`date -u` 与驱动脚本
# `datetime.now(utc)` 两钟同读 07:11:15Z；尺＝本件 `compute_ledger()`；
# 命令＝本件 docstring「复跑」段）：**79→76 / 1→1 / 9→…→4→2**。逐枚归因（详见
# `.superpowers/sdd/2026-09-24-central-dispatch/SEAT-S151.md` §1.5/§5）——
# R-4（四条目投递路径只走统一管线，根净 −66 行）造成 5 枚，本席全部修掉、
# 一枚未抬：①campus 5396→5383（实测位移 −13，非工单估算的 −12；主账 −1）；
# ②③④三枚 matcher（cookie_admin/today_history/subscribe_cmd）本来就漂约
# 1000 行（HEAD 侧证据在案），R-4 的位移只把它们从 mismatch 推成 blank，
# 依工单「重定位 4816 之后受影响的条目」按符号重锚 ⇒ 主账各 −1（**含代改
# 成分，不宣称为纯跟随账**）、空行账 −3；⑤direct:send_group_msg 的登记对象
# （欢迎语 call_api 直发块）已被 R-4 删除，坐标改指统一管线后继调用点
# 5977 ⇒ 空行账 −1（主账不变，仍 mismatch）。同时 R-4 的位移把 2 枚原本指
# 空行的坐标挪离了空行（cosmetic 收益，非降账）。**余 76 枚死号是存量债**：
# 真降账要按门注释①把登记册整体改成按符号名锚定，归该门 owner，本席未做。

#: 主账：声明坐标（location / register_location / add_job_locations）违规数上限。
#: 2026-09-24T07:37:51Z S174 复算降账 **76→72**（`date -u` 与驱动脚本
#: `datetime.now(utc)` 两钟同读 07:37:51Z；尺＝本件 `compute_ledger()`；命令＝本件
#: docstring「复跑」段）。−4 枚全部落在同一批四条目上：`outbound_registry.py` 里
#: cookie 到期／入群欢迎／cookie 登录二维码／文档导出上传四枚直发条目——裁定 R-4 已把
#: 它们的「关态走旧直连」第二条路连开关从生产根删净（AST 尺
#: `tests/test_outbound_bypass_prohibition_gate.py::scan_send_bypasses` 全域零命中），
#: 本席逐枚改判 `DirectSendCategory.ABSORBED`、坐标改指该族唯一后继投递调用点、
#: **锚名同步换成在岗符号**（原 api 字面量 send_group_msg/send_private_msg/
#: upload_* 在根文件 AST 判据下命中 0 次 ⇒ 只按历史平台方法锚定则该格永判 mismatch，
#: 换在岗符号才是本门注释的诚实路径①「按符号名锚定」）。四枚新坐标 4823/5977/6284/6104
#: 逐枚现算判 plausible。**扫描面一字未动**：declared_total 仍 80、all_total 仍 82、
#: `MIN_DECLARED_SITES/MIN_ALL_SITES/EXPECTED_MATCHER_ENTRIES` 与三枚散文/空行/无锚上限
#: 全未改 ⇒ 未缩面、未抬基线；本席落码时点余 72 枚死号是存量债（S151 §5 已交账：真降账＝
#: 登记册整体改成按符号名锚定，归该门 owner，本席同样未做）。该四枚的在岗测试面＝
#: tests/test_v21_s0_root_collect.py（本席未改）。
#: 本席这一批**未摘任何条目**：摘牌会把 declared_total 由 80 打到 76 而撞
#: `MIN_DECLARED_SITES=80` 下限——那是缩扫描面不是降账，故四枚一律「改判 + 重锚」，
#: 一条不删（现算 declared_total 80 / all_total 82 逐值未动）。
#: ⚠ 同窗并发（照实记，不冒领也不背锅）：2026-09-24T07:44:44Z／07:53:27Z／08:00:00Z
#: 登记册被本席之外的席三度改写（50 枚 matcher 坐标由 43xx 段整体重锚到 51xx 段并按符号
#: 判 plausible，owner 名 `matcher:weather_cron` 于 07:53–07:54 之间从登记册文本消失＝改名
#: 或换锚（08:06:31Z 现算 matcher 声明坐标仍 50 枚／唯一 owner 50，未破任何下限），主账因此
#: 72→26→18、空行账 2→1→0。**那 −54 枚与空行 −2 枚全是该席的账**，本席只 Own 自己那 −4 枚，
#: 且未逐枚复核该批定位真伪。本枚现按 08:00:41Z 两钟同读的活账 18 落上限（余 18 枚
#: 全部落在 `scheduler:*`，是 S151 §5(B) 那笔存量债的剩余半壁，本席未代改）。
DECLARED_VIOLATION_CEILING = 18

#: 散文账：note/evidence 等条目内其它字符串里的行号违规数上限。
PROSE_VIOLATION_CEILING = 1

#: 空行账：坐标直指空行的位点数上限（最硬、零解释）。
#: 2026-09-24T04:53:14Z 复算降账 **9→4**（同一次运行内 `datetime.now(utc)` 与 `date -u` 两钟同读
#: 04:53:14Z；尺＝本件 `compute_ledger()`；命令＝本件 docstring「复跑」段）。
#: 成因＝本波根 `__init__.py` 多次纯插入把若干声明坐标从空行上挪开/挪离登记面
#: （最近一批＝SEAT-S102-PATROL-WIRE +40 行、campus 5356→5396），非新增豁免、非缩面：
#: `declared_total` 仍 80、`MIN_DECLARED_SITES/MIN_ALL_SITES` 一字未动。
#: ⚠ 本枚此前长期为 9 而现算 6（S84 于 00:53Z 记），那 3 格余量属**上一批落码未追加核账**，
#: 本次一并按现算收严；方向锁（只准降）与斥离锁均不受影响。
#: 2026-09-24T07:11:15Z S151 复算降账 **4→2**（R-4 推上空的 4 枚全部重锚，成因与
#: 归因逐枚见上方 DECLARED_VIOLATION_CEILING 注记）；余 2 枚＝
#: `matcher:commodities=5542` 与 `scheduler:reflection=2643`，两者在 R-4 之前就指
#: 空行（HEAD 侧反查实证），属存量账，本席未代改。
#: 2026-09-24T08:00:41Z S174 复算 **2→0**（两钟同读 08:00:41Z；尺与命令同上）。消失的
#: 两枚＝S151 记下的 `matcher:commodities=5542` 与 `scheduler:reflection=2643`，都由同窗
#: 另一席 07:44:44Z／07:53:27Z／08:00:00Z 三度改写登记册的按符号重锚带走，**均非本席所为**
#: （本席那 −4 枚只动主账，四枚直发坐标此前判 mismatch 不判 blank）。本枚收到 0 ⇒
#: 此后任何一枚坐标指上空行都当场红，零余量。
BLANK_SITE_CEILING = 0

#: 无锚账：判不了死活（非空、未越界、无锚名）的坐标枚数上限。
UNANCHORED_SITE_CEILING = 1

#: 扫描面下限（缩扫描面的反证）：声明位点数 / 全部位点数不许掉到此值以下。
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
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoordSite:
    """登记册里的一处坐标位点（一个 ``__init__.py:`` 前缀 = 一处）。"""

    raw: str
    owner: str
    field_name: str
    role: str
    line_numbers: tuple[int, ...]
    anchors: frozenset[str]
    state: str = field(default=STATE_UNANCHORED)
    #: 承载它的字符串前 60 字（可复核「是谁说的这句话」）
    host: str = ""

    @property
    def is_violation(self) -> bool:
        return self.state in VIOLATION_STATES

    @property
    def label(self) -> str:
        return f"{self.owner}.{self.field_name}={self.raw}→{self.state}"


# ---------------------------------------------------------------------------
# 解析与判态（纯静态，零 import 被检件）
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


def collect_sites(registry_source: str, root_lines: list[str]) -> list[CoordSite]:
    """现算：抽登记册全部 ``__init__.py`` 坐标位点并逐条判态。"""
    tree = ast.parse(registry_source)
    class_fields = _class_field_order(tree)
    func_params = _func_param_order(tree)
    blank_lines = frozenset(
        index + 1 for index, line in enumerate(root_lines) if not line.strip()
    )
    sites: list[CoordSite] = []
    claimed_constant_ids: set[int] = set()

    def record(
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

    for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
        callee_name = _call_name(call)
        if callee_name not in KNOWN_CALLS:
            continue
        fields = _slot_names(callee_name, class_fields, func_params)
        declared_fields = DECLARED_COORD_FIELDS.get(callee_name, frozenset())
        values: dict[str, str] = {}
        slot_leaves: list[tuple[str, list[str]]] = []
        for index, arg in enumerate(call.args):
            slot = fields[index] if index < len(fields) else f"arg{index}"
            leaves = _string_leaves(arg)
            slot_leaves.append((slot, leaves))
            if leaves and slot not in values:
                values[slot] = leaves[0]
        for keyword in call.keywords:
            slot = keyword.arg or "keyword"
            leaves = _string_leaves(keyword.value)
            slot_leaves.append((slot, leaves))
            if leaves and slot not in values:
                values[slot] = leaves[0]

        identity = _entry_identity(fields, values)
        owner = f"{OWNER_PREFIX.get(callee_name, callee_name)}:{identity}"
        anchors = _anchors_for(identity)
        for slot, leaves in slot_leaves:
            role = ROLE_DECLARED if slot in declared_fields else ROLE_PROSE
            for leaf in leaves:
                record(leaf, role, owner, slot, anchors)
        for sub in ast.walk(call):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                claimed_constant_ids.add(id(sub))

    # 未被任何在册构造器覆盖的字符串 = 文件级散文（模块 docstring、注释旁证、
    # TransportEntry 的 evidence 等）：拿不到条目锚名，只判两类事实态。
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in claimed_constant_ids:
                continue
            record(node.value, ROLE_PROSE, "file-level", "file-prose", frozenset())

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

    def declared_sites(self) -> tuple[CoordSite, ...]:
        return tuple(site for site in self.sites if site.role == ROLE_DECLARED)

    def prose_sites(self) -> tuple[CoordSite, ...]:
        return tuple(site for site in self.sites if site.role == ROLE_PROSE)


def count_non_root_coordinates(registry_source: str) -> int:
    """非根文件坐标枚数（只观察、不判态、不进账）。"""
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
    )


# ---------------------------------------------------------------------------
# 主账棘轮（四本账，只准降）
# ---------------------------------------------------------------------------


def test_declared_coordinate_violations_within_ceiling() -> None:
    """主账：登记册「正身坐标」的死号数只准降（blank ∪ mismatch ∪ out_of_range）。"""
    ledger = compute_ledger()
    worst = [site.label for site in ledger.declared_sites() if site.is_violation][:6]
    assert ledger.declared_violations <= DECLARED_VIOLATION_CEILING, (
        f"声明坐标死号 {ledger.declared_violations} > 上限 "
        f"{DECLARED_VIOLATION_CEILING}＝登记册又漂了一批（或有人新增行号坐标）。"
        f"修法：按符号名重定位后刷新登记，并追加 AUDIT_HISTORY（样例：{worst}）"
    )


def test_prose_coordinate_violations_within_ceiling() -> None:
    """散文账（note/evidence 里的行号）另立一本，不混主账、也不许长。"""
    ledger = compute_ledger()
    worst = [site.label for site in ledger.prose_sites() if site.is_violation][:6]
    assert ledger.prose_violations <= PROSE_VIOLATION_CEILING, (
        f"散文坐标死号 {ledger.prose_violations} > 上限 "
        f"{PROSE_VIOLATION_CEILING}＝note/evidence 里的行号又漂一批（样例：{worst}）"
    )


def test_blank_line_coordinates_within_ceiling() -> None:
    """最硬的一类：坐标直指空行。这类数不许长（零解释、不依赖锚名）。"""
    ledger = compute_ledger()
    roster = [site.label for site in ledger.sites if site.state == STATE_BLANK]
    assert ledger.blank_total <= BLANK_SITE_CEILING, (
        f"空行坐标 {ledger.blank_total} > 上限 {BLANK_SITE_CEILING}（名册：{roster}）"
    )


def test_unanchored_sites_within_ceiling() -> None:
    """无锚坐标（判不了死活的）单独钉住枚数——新增一条就红一次。"""
    ledger = compute_ledger()
    roster = [site.label for site in ledger.sites if site.state == STATE_UNANCHORED]
    assert ledger.unanchored_total <= UNANCHORED_SITE_CEILING, (
        f"无处可验的坐标位点 {ledger.unanchored_total} > 上限 "
        f"{UNANCHORED_SITE_CEILING}＝又添了「谁也判不了死活」的行号（名册：{roster}）"
    )


# ---------------------------------------------------------------------------
# 造绿防线：扫描面下限 + 条目覆盖完整性 + 字面量结构锁 + 方向锁 + 斥离锁
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
    """
    ledger = compute_ledger()
    declared = ledger.declared_sites()
    owners = {site.owner for site in ledger.sites}
    assert "file-level" in owners, "文件级散文未入账＝扫描面漏了一层"
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
    - 现算 **>** 上限 ⇒ 又漂了一批坐标（或有人新增行号）＝真债增加；
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
        f"变差→按符号名重锚登记册；变好→复算后降上限并追加 AUDIT_HISTORY。"
        f"样例：{[site.label for site in ledger.declared_sites() if site.is_violation][:5]}"
    )
    assert ledger.unanchored_total <= UNANCHORED_SITE_CEILING


# ---------------------------------------------------------------------------
# 自证两腿：注毒必红 + 已知活体放行（全跑真身文本）
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


def test_known_live_campus_coordinate_is_plausible() -> None:
    """放行腿：未注毒的真身里，campus 那条（全册唯一另有独立活性锁者）判 plausible。"""
    sites = collect_sites(read_registry_source(), read_root_lines())
    campus = _campus_declared_site(sites)
    assert campus.state == STATE_PLAUSIBLE, (
        f"campus 坐标 {campus.raw} 判为 {campus.state}——放行腿失效或该坐标已被顶漂"
    )


def test_poison_out_of_range_coordinate_is_caught() -> None:
    """注毒腿①：真身里真实且唯一存在的 campus 坐标改成越界号 ⇒ 主账恰 +1、态变。

    毒下在**真身文本的真实字面量**上（先断言该字面量在盘上恰出现一次，否则
    归因失效），再用与主账同一个 ``collect_sites`` 重解析——不是手写夹具。
    """
    source = read_registry_source()
    baseline = compute_ledger()
    campus = _campus_declared_site(list(baseline.sites))
    literal = f'"{campus.raw}"'
    occurrences = source.count(literal)
    assert occurrences == 1, (
        f"注毒前提不成立：{literal} 在登记册里出现 {occurrences} 次（应恰 1 次），"
        "本条会失去归因——换目标条目或改判据，别放宽本断言"
    )
    poisoned = source.replace(literal, '"__init__.py:99999999"')
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    ledger = compute_ledger(poisoned, read_root_lines())
    assert _campus_declared_site(list(ledger.sites)).state == STATE_OUT_OF_RANGE, (
        "注毒后该位点未判 out_of_range＝判据没真跑到源码"
    )
    assert ledger.declared_violations == baseline.declared_violations + 1, (
        f"注毒后主账未 +1：{baseline.declared_violations} → {ledger.declared_violations}"
    )
    assert ledger.out_of_range_total == baseline.out_of_range_total + 1
    # 上限不是装饰品：一发毒就顶破棘轮（零余量锁保证这条恒成立）
    assert ledger.declared_violations > DECLARED_VIOLATION_CEILING, (
        f"注毒未顶破上限 {DECLARED_VIOLATION_CEILING}＝上限里藏了余量"
    )


def test_poison_blank_line_coordinate_is_caught() -> None:
    """注毒腿②：campus 坐标改成**现算出来的真实空行行号** ⇒ 判 blank、两账各 +1。

    空行号从根文件现算（不写死），免随根文件插删而腐烂成假绿 / 假红。
    """
    root_lines = read_root_lines()
    blank_numbers = [
        index + 1 for index, line in enumerate(root_lines) if not line.strip()
    ]
    assert blank_numbers, "根文件里没有空行，注毒腿②失去素材"
    source = read_registry_source()
    baseline = compute_ledger()
    campus = _campus_declared_site(list(baseline.sites))
    literal = f'"{campus.raw}"'
    assert source.count(literal) == 1, "注毒目标字面量在盘上不唯一"
    poisoned = source.replace(literal, f'"__init__.py:{blank_numbers[0]}"')
    assert poisoned != source, "注毒未落到真身文本＝空跑"
    ledger = compute_ledger(poisoned, root_lines)
    assert _campus_declared_site(list(ledger.sites)).state == STATE_BLANK
    assert ledger.blank_total == baseline.blank_total + 1, (
        f"注毒后空行账未 +1：{baseline.blank_total} → {ledger.blank_total}"
    )
    assert ledger.declared_violations == baseline.declared_violations + 1
    # 上限不是装饰品：改成空行号同样一发顶破棘轮
    assert ledger.declared_violations > DECLARED_VIOLATION_CEILING, (
        f"注毒未顶破上限 {DECLARED_VIOLATION_CEILING}＝上限里藏了余量"
    )
    assert ledger.blank_total > BLANK_SITE_CEILING, (
        f"空行账未顶破上限 {BLANK_SITE_CEILING}＝该账上限藏了余量"
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
    """每条坐标恰好一态，五态之和 == 位点总数；各账与逐条名册现数自洽。"""
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
