"""触发词无副本棘轮（S33 立账，2026-09-24 首账；中央调度层统一波「指针合法、字面量副本是债」的触发词腿）。

判据册（本门的尺子，逐条有牙，见文末注毒用例）：

- **真身（home）**：``plugins/**`` 里模块级/类级、绑定名命中 ``HOME_NAME_PAT``
  （trigger／verb／_words／触发／词表）的字面量词表（list／tuple／set／frozenset(...) 全 str 元素），
  或这类名字的含竖线的正则串（按字面连续段切词）；另有 ``aliases／triggers_nl／triggers_nickname``
  等帮助别名字段（``_HELP_ENTRIES／_HELP_ENTRY_META`` 的内层 dict）——plugins 内一律按真身形态收。
  真身是登记面的候选形态；``capability_manifest.FACETS[*].trigger_source`` 的指针登记由 G-CM 门
  （``test_capability_manifest_gate.py`` 第④腿）锁「指针可解析」，本门补它没锁的另一半：
  **字面量不许有第二处**。
- **中央件豁免**：``domains/core/text_boundary.py`` 是触发词边界中央真身（字符集与判定件，
  不持词表），整文件不参与本账。
- **规则 A（重复真身）**：同一归一化词集合出现在 ≥2 枚真身位置 → 每多一处记一笔债。
  ~~今天全部命中是 echo 帮助别名 ≡ 能力词表的镜像对~~ **该 blanket 断言已被证伪**（S106 发1／S131 复核）：
  11 簇里 10 簇确是在册镜像对（由帮助别名闭合门与双向覆盖门要求，逐枚进 ``HOME_MIRROR_NOT_DEBT`` 名册），
  第 11 簇 ``订阅/訂閱/subscribe`` 是 ``echo.py``（bot.subscribe）× ``emergency_info.py``
  （bot.emergency_info 群内订阅命令面）**跨两个能力撞词**——既非镜像对、也无门要求它相等。
  **裁定 9 的处置（S137，2026-09-24）＝摘出本账并移交**：本尺量的是「同一份词写了两处」，
  而这一枚根本没有"原处"——两枚各自都是**自己能力**的命令面，重叠是**词义冲突/劫持**、不是副本。
  逐枚登记进 ``HOME_CROSS_CAPABILITY_NOT_DEBT``（带 ``handed_to`` 指回具体门），判据本体写在
  ``tests/test_trigger_spec.py::KNOWN_CROSS_CAPABILITY_CLASHES``；**两本账互锁**（该门一侧的
  `test_handoff_from_copy_ratchet_is_registered_there`）⇒ 本门摘一枚而该门没接 ⇒ 两边同时红，
  **摘牌不等于把红搬没**。
- **规则 B（字面量副本）**：任何非真身位置（tests/**、scripts/**、plugins 函数体内、
  plugins 模块级但名字不命中的表）出现的字面量词集，若**整集 ⊆ 某枚真身词集** → 记一笔债。
  重合但互不包含的表不算副本（那是撞词，归触发冲突体检 ``test_trigger_spec.py`` 管）。
- **不计账名册（S131 落码，2026-09-24）**：ruleB 的「整集 ⊆ 真身」子集口会把**以词为键的结构数据**
  （色→序位表 / 库名→路径表 / 契约字段名信封 / 署名表 / 让路守卫 / ``help_topics=`` 外键字段）
  和**词面本身即验收标的的探针字面量**一并记成债。这两类不是副本，摘除它们**只准逐枚点名＋各写判据**
  （``COPY_NOT_DEBT`` / ``HOME_MIRROR_NOT_DEBT`` / ``HOME_CROSS_CAPABILITY_NOT_DEBT``），
  **严禁写成通用条款**——实证：
  任何「值不像词就不是债」这类结构闸都会连带摘掉
  ``tests/test_emergency_info_sources.py:216``（``{"黄色": 183, …}`` 计数断言表，S106 判 (a) 真债），
  故本门不设形态闸，只设名册。名册的四把牙：①**逐枚活性锁**（每条必须恰命中一枚现算债，虚设即红）；
  ②**逐枚干活的锁**（逐条摘除该条 ⇒ 计账数必升）；③**精确键**（``file``＋``label``＋**词集全等**，
  换词／换文件／镜像簇多出一员 ⇒ 立刻恢复记账）；④**禁条款化**（``words_text`` 非空、词数 ≥2、
  路径必须存在于盘上、正文禁竖线以免本文件自扫成灾）。豁免项**照旧逐条打印在 ``--ledger``**
  （带 ``不计账`` 前缀与 reason）⇒ 扫描面与可见面都不缩，只改计账口径。
- **指针／散文／单词／混合对不记**：``文件#符号`` 指针串、帮助文案里的词、单个词的提及、
  与真身词混写的非标词集合都不是「字面量副本」，一律放行（负样本注毒锁死）。

已知盲区（如实写，不许拿「绿」当「全」）：
  ① 繁简靠词表条目对应，本门按字面串比对，不做繁简折叠（与中央件口径一致）；
  ② 全角竖线分隔的文案不参与正则切词（帮助正文非触发面）；
  ③ 派生表（``tuple(某dict)``、推导式）非字面量，收不到——真身若是派生形态（如 group_info
    ``GROUP_INFO_TRIGGER_WORDS``），其字面原料（``_INTENT_*_WORDS``）仍在账上；
  ④ 词形过滤为「≤24 字符、无句读括号类字符、含汉字或纯小写 ASCII」，任一元素不合词形则整集
    不收（话术池/枚举说明天然出局；``1～2 小写字母＋数字`` 形态的通用优先级键（p0／b2…）从
    词集中剔除，防把「优先级」当「触发词」）；
  ⑤ 正则串只在「字面连续段 ≥2 且整集 ⊆ 真身」时记账；跨形态（列表↔正则）改写词序不追；
  ⑥ 记录集不 recurse：元素本身是字面量容器的容器（如 (主题,词) 对账行、参数组）按结构数据
    处理、整枝不看——「行里的词」不进账，「整表重列」才进账（首账实锤：双向台账 69 行若按
    词集读会淹掉真信号；归一该台账时改从提取器现算，见报告）；
  ⑦ 名册匹配键刻意**不含行号**（行号随任何一次编辑漂移）⇒ 代价是「同一文件同一标签同一词集
    被原地重写」读起来像同一枚：这种改写必须由 ③精确键 与 ④禁条款化 两把锁与 ``--ledger`` 的
    现算位注释共同盯，别指望名册自己发现。

账本纪律（照 ``test_legacy_shim_import_ratchet.py`` 先例）：上限＝**手写字面量**、
与最近一次现算核账值**零余量相等**（``test_zero_slack_ceiling_equals_latest_audit`` 有锁）；
核账记录只准降；扫描面/锚点真身/账本非空/谓词自反四把塌陷锁；归一后降账＝改小上限＋
AUDIT_HISTORY 追加一行（``python tests/test_trigger_word_copy_ratchet.py --bless`` 打建议值、
``--ledger`` 打逐条明细）。注毒全部走「同一取数口吃内存源码」，不往树里写东西；本文件自身
不含任何触发词**字面量容器**（毒词从真身或名册现取，名册里的词面一律以「、」单串存放），
自扫零贡献由 ``test_own_test_file_contributes_no_literals`` 常驻执法。

**降账口径（S131，务必与「取数口」分开读）**：81→43 这一笔**没有**动 tier-1/tier-2 任何取数口、
没有动 ``SCAN_ROOTS``/两个地板/整文件豁免（⇒ 现算 raw 至今仍是 81，`--ledger` 头行两个数并列打印），
只在「现算债 → 计账债」之间插了一层**逐枚点名**的名册。因此本门的「绿」含义是
「记账侧 ≤ 上限 **且** 名册逐枚活着、逐枚干活、词集全等精确命中」，不是「扫描面变小了」。
将来若有人要动取数口（收 values、递归记录集、扩根），那是**视野变大**，必须另立首届新门、
不得拿本门的老上限去换绿（S106 §3.3 同口径）。

全离线、只读源码、不 import 任何插件模块、不写盘。
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Final, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS: Final[tuple[str, ...]] = ("plugins", "scripts", "tests")
#: 中央边界件整文件豁免（它持有字符集与判定件，不持词表——见模块 docstring）。
TEXT_BOUNDARY_REL: Final[str] = "plugins/bot_unified_runtime/domains/core/text_boundary.py"

#: 真身绑定名形态（命中才可能是 home；tests/scripts 里同样的名字也只是副本候选）。
HOME_NAME_PAT: Final[re.Pattern[str]] = re.compile(r"(?i)trigger|verb|_words|触发|词表")
#: 帮助/别名册的字段名：plugins 内出现即真身形态（_HELP_ENTRIES 等嵌套 dict 全靠它收）。
ALIAS_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {"aliases", "alias", "triggers", "triggers_nl", "triggers_nickname"}
)

_CJK_RE: Final[re.Pattern[str]] = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_LOWER_ASCII_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9 _\-]*")
_GENERIC_PRIORITY_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]{1,2}[0-9]")
_WORD_RUN_RE: Final[re.Pattern[str]] = re.compile(
    "[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff ]*[0-9A-Za-z\u4e00-\u9fff]"
    "|[0-9A-Za-z\u4e00-\u9fff]"
)
#: 出现即整元素出局的字符（句读/括号/路径引号类）——把话术池、枚举说明、正则骨架挡在词集外。
_BANNED_CHARS: Final[frozenset[str]] = frozenset(
    "。；？！，、：~～…—·．!?;:()（）[]【】<>《》\"'`/\\{}%+*=&#$@^\n\r\t"
)
MAX_WORD_CHARS: Final[int] = 24
#: 正则串候选长度上限（超长串多半是文案而非词表）。
_MAX_REGEXISH_CHARS: Final[int] = 400
#: 注毒负样本用的保证非标词（任何真身词表都不可能含它）。
_UNEXISTENT_WORD: Final[str] = "zzz查无此触发词zzz"

#: 扫描面地板：低于此＝有人改了 glob/排除（扫描面塌陷），不是「大家都干净了」。
MIN_SCANNED_FILES: Final[int] = 1100
#: 真身表数量地板：低于此＝判据被改瞎（锚点还在但表收不上来）。
MIN_HOME_TABLES: Final[int] = 120

#: **手写字面量**上限（零余量＝等于最近一次现算核账值），只准降。
# 2026-09-24 S33 首账：判据定案后现算 ruleB 副本 70 ＋ ruleA 重复真身超额 11＝81，零余量钉死（明细 --ledger）。
# 核账途中两次判据修正照实记：①tier-2 认领时机从「先认领后判定」改「成表才认领」
# （旧序把双向台账整枝吞掉＝隐形账）；②优先级形键（p0/b2…）从「整集拒收」改「静默剔除后
# 余词照计」（旧序把 _LEVEL_WORDS 档位词族整个打死，颜色副本 7 条隐形）。
# 2026-09-24 S131（补阵亡 S110）**改口径不改扫描面**降账 81 → 43：现算 raw 仍为 81（ruleB 70＋ruleA 超额 11，
# `--ledger` 头行同时打印两个数），其中 38 枚经逐枚点名判为「不该记账」——17 枚结构数据被 ruleB 子集口误吞
# （dictkeys 13 ＋ coll 4：色序位表 2／契约字段名信封 9／署名表 1／库路径表 1／help_topics 外键 2／
# 控制面 aliases 实参 1／让路守卫 1）＋ 21 枚在册设计（ruleA 镜像对 10 簇 ＋ 测试繁體/英文/拼音探针 11）；
# 余 43 枚＝真债或半债 20 枚 (a) ＋ 须先入册再删 9 枚 (b) ＋ 判不了 14 枚 (d)。逐枚判据在名册里，
# 交叉证据＝S106 五态表与本门 `--ledger` 的 `不计账` 行。**未删任何断言、未缩任何 glob、未加 skip/xfail。**
# 2026-09-24 S137（RULINGS-20260924 第 9 项裁定 A）43 → 42：ruleA 第 11 簇「订阅/訂閱/subscribe」
# 两枚真身分属 **bot.subscribe × bot.emergency_info 两个能力**、无门要求相等 ⇒ 它不是"第二处副本"而是
# **词义冲突**，按尺 B 自己的「归属写死」摘出本账、逐枚登记进 ``HOME_CROSS_CAPABILITY_NOT_DEBT``，
# 同一枚在 ``test_trigger_spec.py::KNOWN_CROSS_CAPABILITY_CLASHES`` 立等价判据接住
# （两本账由该门一侧的 `test_handoff_from_copy_ratchet_is_registered_there` 互锁 ⇒ 只删不接＝两边同时红）。
TRIGGER_COPY_CEILING: Final[int] = 42

#: 逐次核账记录（日期, 当时债数），**必须单调不升**，且末项＝当前上限（零余量锁）。
AUDIT_HISTORY: Final[tuple[tuple[str, int], ...]] = (
    ("2026-09-24", 81),
    ("2026-09-24", 43),
    # S137（裁定 9 之 A8）：跨能力撞词 1 簇摘出副本账、移交 test_trigger_spec 等价判据 ⇒ 43→42。
    ("2026-09-24", 42),
)

#: 锚点真身（文件, 标签, 代表词）：这些必须始终被识别为 home——识别器瞎了本条先红。
_ANCHOR_HOMES: Final[tuple[tuple[str, str, str], ...]] = (
    ("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "DEFAULT_TRIGGER_WORDS", "语音合成"),
    ("plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py", "DEFAULT_TRIGGER_WORDS", "随机图"),
    ("plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py", "DEFAULT_TRIGGER_WORDS", "收藏"),
    ("plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py", "_SUBSCRIBE_WORDS", "订阅"),
    ("plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py", "DEFAULT_VERB_MAP#dictkeys", "决策"),
)


class Occ(NamedTuple):
    """一枚词表出现（真身或副本候选）。"""

    file: str
    line: int
    label: str
    words: frozenset[str]


class DebtCopy(NamedTuple):
    """规则 B：一条字面量副本（整集 ⊆ 真身）。"""

    copy: Occ
    home: Occ


class DebtHomeDup(NamedTuple):
    """规则 A：同一词集合的多枚真身。"""

    words: frozenset[str]
    members: tuple[Occ, ...]


#: 名册允许的分类标签（只作账目可读性，**不作判据**——判据永远在逐枚 ``reason`` 里）。
#: 词表用换行单串存放再切分：本文件被自己扫（``SCAN_ROOTS`` 含 tests），
#: 任何「字面量容器」形态都会成为 tier-2 副本候选——连本门的名册也不例外。
_KIND_VOCAB: Final[str] = "结构数据\n探针字面量\n在册镜像"
NOT_DEBT_KINDS: Final[frozenset[str]] = frozenset(_KIND_VOCAB.split("\n"))
#: 名册词集的分隔符。用「、」而非任何会被 tier-2 收为容器的写法：本门源码必须对两本账零贡献
#: （由 ``test_own_test_file_contributes_no_literals`` 常驻执法），故名册里的词面一律以单串存放。
WORD_SEP: Final[str] = "、"


def _words_from_text(text: str) -> frozenset[str]:
    return frozenset(word for word in text.split(WORD_SEP) if word)


class NotDebtCopy(NamedTuple):
    """一枚被逐顶点名的 ruleB 现算债（结构数据／探针字面量），键＝文件＋标签＋**词集全等**。"""

    file: str
    label: str
    words_text: str
    kind: str
    reason: str

    @property
    def words(self) -> frozenset[str]:
        return _words_from_text(self.words_text)


class NotDebtMirror(NamedTuple):
    """一枚被逐顶点名的 ruleA 在册镜像簇，键＝词集＋成员位集合（不含行号，行号会漂）。"""

    words_text: str
    sites: tuple[tuple[str, str], ...]
    reason: str

    @property
    def words(self) -> frozenset[str]:
        return _words_from_text(self.words_text)


class NotDebtHandoff(NamedTuple):
    """一枚**不是副本、而是跨能力撞词**的 ruleA 簇：从本账摘出、移交冲突体检门。

    与 ``NotDebtMirror`` 的区别不是"要不要记账"，而是**归谁判**：镜像簇的相等是别的门要求的
    （删任一侧当场拆门），移交簇的相等没有任何门要求，它是**词义冲突**——按尺 B 的「归属写死」
    归 ``tests/test_trigger_spec.py``。故本类多带一枚 ``handed_to``：交接对象写死成具体门名，
    并由该门一侧的等价锁反向核账（见 ``test_trigger_spec`` 的 ``KNOWN_CROSS_CAPABILITY_CLASHES``）
    ⇒ **只删不接（把红搬走却没人接）在两本账上同时红**。
    """

    words_text: str
    sites: tuple[tuple[str, str], ...]
    handed_to: str
    reason: str

    @property
    def words(self) -> frozenset[str]:
        return _words_from_text(self.words_text)


#: **ruleB 不计账名册（28 枚，逐枚点名＋各写判据；新增/删除都必须带理由，禁止写成条款）**。
#: 判据出处＝S106 五态表（只读席）＋本席 AST 值侧探针复算；`--ledger` 里这 28 枚仍逐条打印。
COPY_NOT_DEBT: Final[tuple[NotDebtCopy, ...]] = (
    NotDebtCopy(
        file="plugins/bot_unified_runtime/control_plane/features.py",
        label="coll",
        words_text="chat、聊天",
        kind="结构数据",
        reason="FeatureDescriptor(aliases=…) 的**关键字实参**：字段名在场即元数据声明（控制面功能树检索别名），不驱动路由；判据取「实参位＝字段声明」而非「像不像词表」",
    ),  # 现算位 106｜真身 echo.py:2093｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/core/board_taxonomy.py",
        label="coll",
        words_text="历史上的今天、快报",
        kind="结构数据",
        reason="help_topics=(…) 的 news 板块格：同字段同语义、另一枚独立引用（快报/历史上的今天），逐枚点名",
    ),  # 现算位 445｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/core/board_taxonomy.py",
        label="coll",
        words_text="功能管理、帮助",
        kind="结构数据",
        reason="help_topics=(…)＝板块声明源按**名字引用**帮助 topic 的外键字段（B02.capability-registry 那一格），改成派生自词表反而把声明源钉在触发面上",
    ),  # 现算位 174｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/divination/capabilities/divination.py",
        label="dictkeys",
        words_text="bazi、iching、tarot",
        kind="结构数据",
        reason="_CARD_AUTHORS：键是卡片来源标签、值是含「·」的署名长句（AST 实证 Constant 含句读）＝署名映射表，整表被当触发词消费的那条边不存在，删键即毁三张卡的署名",
    ),  # 现算位 366｜真身 echo.py:1629｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/emergency_info/sources/nmc_alarm.py",
        label="dictkeys",
        words_text="橙色、红色、蓝色、黄色",
        kind="结构数据",
        reason="ALARM_COLOR_RANK：值＝整数 1/2/3/4（AST 实证）＝预警色序位表，行内注释自陈与 weather.py:112 逐字一致是**口径对齐**而非词表复制；删键即毁颜色定级",
    ),  # 现算位 66｜真身 subscriptions.py:47｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py",
        label="coll",
        words_text="天气、天氣",
        kind="结构数据",
        reason="_DOMAIN_HEAD_PREFIXES 是让路守卫：命中即判「不是萌百实体」（行内注释「帮我查X天气应让路天气能力」）＝与触发词表方向**相反**的负向门，当副本删掉会让萌百劫持天气查询",
    ),  # 现算位 89｜真身 echo.py:1465｜值侧形态见 reason
    NotDebtCopy(
        file="plugins/bot_unified_runtime/domains/weather/capabilities/weather.py",
        label="dictkeys",
        words_text="橙色、红色、蓝色、黄色",
        kind="结构数据",
        reason="_ALARM_COLOR_RANK：值＝整数 1/2/3/4（AST 实证）＝同一序位表的另一枚在册消费点，与订阅档位词 _LEVEL_WORDS 同形不同用（档位词是「词→档码」，此表是「色→序」）",
    ),  # 现算位 112｜真身 subscriptions.py:47｜值侧形态见 reason
    NotDebtCopy(
        file="scripts/knowledge_progress.py",
        label="dictkeys",
        words_text="memory、wiki",
        kind="结构数据",
        reason="STORES：值是含「/」与「.」的 sqlite 路径常量（AST 实证）＝库文件名映射表，键 memory/wiki 与 DEFAULT_VERB_MAP 的动词键纯词面巧合",
    ),  # 现算位 19｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_central_dispatch_matrix.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="CapabilityRequest.context 的**字段名**字典：值形＝IfExp＋SimpleNamespace()（AST 实证）＝调度信封夹具，config/decision 是契约字段名、不是触发词",
    ),  # 现算位 103｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_central_via_identity_and_entry_durability.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具：值形＝两个 SimpleNamespace() 调用（AST 实证），非字符串常量⇒ 语义是对象袋不是词表",
    ),  # 现算位 153｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_help_meta_search_and_tra49_aliases.py",
        label="coll",
        words_text="tianqi、tq、weather、天氣、天氣預報、查天氣",
        kind="探针字面量",
        reason="WEATHER_SEARCH_SAMPLES（拼音+繁體可搜索样例）：行上注释自陈「防看得见搜不到的代表性样例」＝字面量即样例本体",
    ),  # 现算位 47｜真身 echo.py:1465｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_orchestration_callsite_wave3_b.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（wave3_b 第一处）：值形＝Dict＋Name＋DictComp（AST 实证）＝按 _CONTEXT_KEYS 拼信封，与触发词无关",
    ),  # 现算位 326｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_orchestration_callsite_wave3_b.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（wave3_b 第二处）：值形＝Name＋Call＋Name（AST 实证），同一字段名的第二次拼装",
    ),  # 现算位 431｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_pipeline_managed_adapter.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具：值形＝None/None（AST 实证）＝空信封占位，最不像词表的一枚",
    ),  # 现算位 78｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_prepared_adapter_batch1.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（batch1）：值形＝SimpleNamespace()/SimpleNamespace()（AST 实证）",
    ),  # 现算位 79｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_prepared_adapter_batch2.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（batch2）：值形同上；三枚 batch 件各自独立建信封，逐枚点名不合并成条款",
    ),  # 现算位 79｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_prepared_adapter_batch3.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（batch3，行位与 batch1/2 不同）：值形同上",
    ),  # 现算位 92｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_prepared_adapter_canary.py",
        label="dictkeys",
        words_text="config、decision",
        kind="结构数据",
        reason="同上契约字段名夹具（canary 哨兵件）：值形同上；该件是派发哨兵，词面不参与任何断言",
    ),  # 现算位 62｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_traditional_triggers_2.py",
        label="coll",
        words_text="偷圖、表情抽籤、表情隨機、隨機表情、隨機表情包",
        kind="探针字面量",
        reason="繁體触发路由样例（隨機表情族）：parametrize 的入参文本就是被测对象，派生化会让「繁體形是否仍触发」退化成用真身验真身",
    ),  # 现算位 84｜真身 echo.py:1423｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_traditional_triggers_2.py",
        label="coll",
        words_text="steam免費、免費遊戲、遊戲免費",
        kind="探针字面量",
        reason="繁體触发路由样例（steam 免費族）：同上，入参即验收标的",
    ),  # 现算位 106｜真身 echo.py:1929｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_traditional_triggers_2.py",
        label="coll",
        words_text="今日塔羅、命盤、塔羅、塔羅三張、排盤、搖卦",
        kind="探针字面量",
        reason="繁體占卜族（塔羅/搖卦…）：断言 is_divination_command(text) is True ⇒ 词面被钉死才有防回退价值",
    ),  # 现算位 162｜真身 echo.py:1629｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_traditional_triggers_2.py",
        label="coll",
        words_text="暫停、狀態、繼續",
        kind="在册镜像",
        reason="繁體动词族（狀態/暫停/繼續）直接断言 verb in DEFAULT_VERB_MAP：件内已引真身，词面是繁體形对照位（真身只有简体），删词面即删掉「繁體不丢」这一条断言",
    ),  # 现算位 286｜真身 aliases.py:77｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_traditional_triggers_2.py",
        label="regexstr",
        words_text="搜图、搜圖",
        kind="探针字面量",
        reason="源码文本断言：在根 __init__.py 正文里搜「搜图＋竖线＋搜圖」这个字面针——字面量本身就是被搜的对象，派生即让断言失去可搜形态",
    ),  # 现算位 350｜真身 echo.py:1444｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_trigger_english.py",
        label="coll",
        words_text="music、song",
        kind="在册镜像",
        reason="_TOPIC_ALIAS_FLOOR（防英文别名脱册地板表）的第 2 格 tuple 值：该表的存在理由就是**独立于 echo 册**钉住每 topic 必须有英文别名，派生自 echo 即自我循环",
    ),  # 现算位 300｜真身 echo.py:1374｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_trigger_english.py",
        label="coll",
        words_text="stock、stocks",
        kind="在册镜像",
        reason="同表 stocks 格 tuple 值：同上口径，另一枚独立声明单元",
    ),  # 现算位 308｜真身 echo.py:1506｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_trigger_english.py",
        label="coll",
        words_text="bazi、divination、iching、tarot",
        kind="在册镜像",
        reason="同表 占卜 格 tuple 值（4 个英文词）：同上——地板表若从 echo 派生，脱册检查即恒真",
    ),  # 现算位 310｜真身 echo.py:1629｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_trigger_english.py",
        label="coll",
        words_text="eat、food、recipe",
        kind="在册镜像",
        reason="同表 吃什么 格 tuple 值：同上，独立声明单元第 4 格",
    ),  # 现算位 312｜真身 echo.py:1835｜值侧形态见 reason
    NotDebtCopy(
        file="tests/test_trigger_english.py",
        label="coll",
        words_text="today、today in history",
        kind="在册镜像",
        reason="同表 历史上的今天 格 tuple 值：同上，独立声明单元第 5 格",
    ),  # 现算位 313｜真身 echo.py:1725｜值侧形态见 reason
)

#: **ruleA 不计账名册（10 簇在册镜像对；第 11 簇「订阅」跨能力撞词，刻意不入册＝继续记账）**。
HOME_MIRROR_NOT_DEBT: Final[tuple[NotDebtMirror, ...]] = (
    NotDebtMirror(
        words_text="archive、guidang、shoucang、存图、存聊天记录、存记录、归档、收图、收藏",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py", "DEFAULT_TRIGGER_WORDS")),
        reason="媒体归档族 9 词：帮助册 aliases ≡ 能力侧 media_archive.DEFAULT_TRIGGER_WORDS＝双向覆盖门要求的「能力词表必须出现在帮助册」镜像，删任一侧当场拆门",
    ),  # 现算位 49×1858
    NotDebtMirror(
        words_text="config、配置",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="config/配置：echo _HELP_ENTRIES.aliases（:680）≡ _HELP_ENTRY_META.triggers_nickname（:2341）同一 topic 的两个呈现位，帮助别名闭合门要求两册同时在场",
    ),  # 现算位 680×2341
    NotDebtMirror(
        words_text="history、历史、清理历史",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="history/历史/清理历史：同一帮助条目 aliases 位（:775）≡ triggers_nickname 位（:2377）双位镜像",
    ),  # 现算位 775×2377
    NotDebtMirror(
        words_text="laizhangtu、lzt、randpic、sjt、suijitu、來張圖、来张图、随机图、隨機圖",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py", "DEFAULT_TRIGGER_WORDS")),
        reason="随机图族 9 词：同型跨册镜像，且 echo.py:1947 注释明文「隨機圖/來張圖（tra2 波入 DEFAULT_TRIGGER_WORDS）help 同步入册」＝有意同步的盘上铁证",
    ),  # 现算位 29×1949
    NotDebtMirror(
        words_text="memory、记忆",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="memory/记忆：同型镜像对（:508 × :2280）",
    ),  # 现算位 508×2280
    NotDebtMirror(
        words_text="persona、人格",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="persona/人格：同型镜像对（:734 × :2364）",
    ),  # 现算位 734×2364
    NotDebtMirror(
        words_text="readiness、就绪",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="readiness/就绪：同型镜像对（:698 × :2348）",
    ),  # 现算位 698×2348
    NotDebtMirror(
        words_text="roles、角色",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="roles/角色：同型镜像对（:716 × :2355）",
    ),  # 现算位 716×2355
    NotDebtMirror(
        words_text="why、为什么、为啥",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="why/为什么/为啥：同型镜像对（:532 × :2288）",
    ),  # 现算位 532×2288
    NotDebtMirror(
        words_text="我都跟谁聊过、本群信息、本群参与者、本群多大了、本群待办、本群相册、本群谁说过话、本群都有谁、精华消息、群主是谁、群人数、群信息、群公告、群参与者、群待办、群待办列表、群相册、群相册列表、群精华、群资料、群里谁说过话、群里都有谁、谁是群主、跟谁聊过、都有谁说过话",
        sites=(("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"), ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname")),
        reason="群信息族 25 词：同一帮助条目的 aliases ≡ triggers_nickname 双位镜像；"
        "2026-09-25 二批随「群相册/群待办」接线扩 6 词，2026-09-26 随「参与者」腿（S-T-GRP-2）"
        "再扩 9 词（群里都有谁/群参与者/谁说过话/跟谁聊过 一族，真身 group_info._INTENT_WHO_WORDS），"
        "词表不能改派生成跨模块引用——command_catalog.py::_eval_literal 只认同模块简单常量。",
    ),  # 现算位 1880×2820
    NotDebtMirror(
        words_text="hoststate、jiqipeizhi、jiqizhuangtai、jizhuangtai、宿主机状态、宿主機狀態、宿主状态、机器状态、机器配置、機器狀態",
        sites=(
            ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"),
            ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:triggers_nickname"),
            ("plugins/bot_unified_runtime/domains/ops/capabilities/host_state.py", "DEFAULT_TRIGGER_WORDS"),
        ),
        reason="宿主机状态族 10 词（需求 5 超管读卡）：三处镜像＝帮助条目 aliases ≡ "
        "triggers_nickname 双位 ＋ 能力侧 DEFAULT_TRIGGER_WORDS 真身；帮助侧两枚位是"
        "command_catalog::_eval_literal 只认同模块常量所要求的字面量，能力侧那枚才是路由真身，"
        "双向门与触发词单一来源门都要求三者词集相等。",
    ),  # 现算位 echo 1992×3027 × host_state 56
)

#: **ruleA 跨能力撞词移交名册（1 簇，RULINGS-20260924 第 9 项裁定 A／S137 落码 2026-09-24）**：
#: 词集全等但**两枚真身分属两个能力**、且没有任何门要求它们相等 ⇒ 这不是副本、是词义冲突。
#: 从本账摘出的**同时**必须在 ``tests/test_trigger_spec.py`` 的 ``KNOWN_CROSS_CAPABILITY_CLASHES``
#: 登记同一枚（词集＋成员位＋能力对）——该门一侧写有反向等价锁，只删不接两本账同时红。
#: 键含词集全等：两侧同时改词 ⇒ 本条不再命中 ⇒ 立刻恢复记账（要重登记，不许顺手放宽）。
HOME_CROSS_CAPABILITY_NOT_DEBT: Final[tuple[NotDebtHandoff, ...]] = (
    NotDebtHandoff(
        words_text="subscribe、訂閱、订阅",
        sites=(
            ("plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py", "dict:aliases"),
            ("plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py", "_SUBSCRIBE_WORDS"),
        ),
        handed_to="tests/test_trigger_spec.py::test_cross_capability_word_clash_matches_ledger",
        reason="S106 发1 证伪尺 A 的 blanket 宣称那一枚：帮助册 bot.subscribe 的 aliases 位与紧急信息域群内订阅命令面 _SUBSCRIBE_WORDS 共用同三个词，两枚真身分属两个能力、无共同上级册、也无双向门要求相等 ⇒ 属词义冲突/劫持（尺 B 归属写死＝归触发体检门），按裁定 A 移交 test_trigger_spec，不再按副本计账",
    ),  # 现算位 1345×334
)


def _word_shape_ok(w: str) -> bool:
    """词形：短、无句读括号类字符、含汉字或纯小写 ASCII。"""
    if not w or w != w.strip() or len(w) > MAX_WORD_CHARS:
        return False
    if any(ch in _BANNED_CHARS for ch in w):
        return False
    return bool(_CJK_RE.search(w) or _LOWER_ASCII_RE.fullmatch(w))


def _norm_set(words: list[str]) -> frozenset[str] | None:
    """归一化＋整集资格判定：先静默剔除通用优先级键（p0/b2…，非触发词语义），
    剩余元素任一不合词形 → 整集不是词表（话术池天然出局）。"""
    kept = {
        w.strip()
        for w in words
        if w and w.strip() and not _GENERIC_PRIORITY_RE.fullmatch(w.strip())
    }
    if len(kept) < 2 or not all(_word_shape_ok(w) for w in kept):
        return None
    return frozenset(kept)


def _unwrap_container(node: ast.expr) -> ast.expr:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
        and len(node.args) == 1
    ):
        return node.args[0]
    return node


def _str_items(node: ast.expr) -> list[str] | None:
    """全 str 常量的字面量容器（含 frozenset(...) 包裹）→ 元素列表，否则 None。"""
    base = _unwrap_container(node)
    if not isinstance(base, (ast.Tuple, ast.List, ast.Set)):
        return None
    vals: list[str] = []
    for elt in base.elts:
        if isinstance(elt, ast.Starred) or not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
            return None
        vals.append(elt.value)
    return vals


def _dict_str_keys(node: ast.expr) -> list[str] | None:
    base = _unwrap_container(node)
    if not isinstance(base, ast.Dict):
        return None
    return [k.value for k in base.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for e in target.elts for n in _target_names(e)]
    return []


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """模块/类/函数 docstring 常量节点——散文不参与副本判定。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def scan_source(rel: str, src: str) -> tuple[list[Occ], list[Occ]]:
    """单一取数口：一份源码 → (真身表, 副本候选)。全树聚合与注毒共用它（口径不许分叉）。"""
    tree = ast.parse(src, filename=rel)
    homes: list[Occ] = []
    copies: list[Occ] = []
    claimed = _docstring_constant_ids(tree)
    is_plugin = rel.startswith("plugins/")
    if rel == TEXT_BOUNDARY_REL:
        return homes, copies

    def add_home(occ: Occ, claim_root: ast.AST) -> None:
        for sub in ast.walk(claim_root):
            claimed.add(id(sub))
        homes.append(occ)

    def add_copy(occ: Occ, claim_root: ast.AST) -> None:
        for sub in ast.walk(claim_root):
            claimed.add(id(sub))
        copies.append(occ)

    # ---- tier-1：模块级/类级语句的真身形态（仅 plugins；成功成表才认领子树）----
    module_and_class_stmts: list[ast.stmt] = list(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            module_and_class_stmts.extend(node.body)
    for st in module_and_class_stmts:
        if not isinstance(st, (ast.Assign, ast.AnnAssign)):
            continue
        targets = st.targets if isinstance(st, ast.Assign) else [st.target]
        named = [n for t in targets for n in _target_names(t) if HOME_NAME_PAT.search(n)]
        if not (is_plugin and named) or st.value is None:
            continue
        label = ",".join(sorted(named))
        value = st.value
        items = _str_items(value)
        if items is not None:
            words = _norm_set(items)
            if words is not None:
                add_home(Occ(rel, st.lineno, label, words), st)
            continue
        keys = _dict_str_keys(value)
        if keys is not None:
            words = _norm_set(keys)
            if words is not None:
                add_home(Occ(rel, st.lineno, label + "#dictkeys", words), st)
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str) and "|" in value.value:
            words = _norm_set(_WORD_RUN_RE.findall(value.value))
            if words is not None:
                add_home(Occ(rel, st.lineno, label + "#regex", words), st)
                continue

    # ---- 别名册字段：plugins 内 = 真身；scripts/tests 内 = 副本候选 ----
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or id(node) in claimed:
            continue
        for key, val in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value in ALIAS_FIELD_KEYS:
                items = _str_items(val)
                words = _norm_set(items) if items is not None else None
                if words is None:
                    break
                occ = Occ(rel, val.lineno, f"dict:{key.value}", words)
                if is_plugin:
                    add_home(occ, node)
                else:
                    add_copy(occ, node)
                break

    # ---- tier-2：其余字面量容器 / dict 键 / 含竖线短串 = 副本候选 ----
    for node in ast.walk(tree):
        if id(node) in claimed:
            continue
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            if any(isinstance(e, (ast.Tuple, ast.List, ast.Set)) for e in node.elts):
                # 记录集（行=内嵌字面量容器，如 (主题,词) 对账行/参数组）：行数据不是词表，
                # 整枝认领跳过——否则把「结构数据」误读成「字面量副本」（S33 首账实锤 69 行）。
                for sub in ast.walk(node):
                    claimed.add(id(sub))
                continue
            literals = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(literals) == len(node.elts):
                words = _norm_set(literals)
                if words is not None:
                    add_copy(Occ(rel, node.lineno, "coll", words), node)
        elif isinstance(node, ast.Dict):
            words = _norm_set(
                [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            )
            if words is not None:
                add_copy(Occ(rel, node.lineno, "dictkeys", words), node)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "|" in node.value
            and len(node.value) <= _MAX_REGEXISH_CHARS
        ):
            words = _norm_set(_WORD_RUN_RE.findall(node.value))
            if words is not None:
                add_copy(Occ(rel, node.lineno, "regexstr", words), node)
    homes.sort(key=lambda o: (o.file, o.line, o.label))
    copies.sort(key=lambda o: (o.file, o.line, o.label))
    return homes, copies


def iter_tree_sources() -> tuple[list[tuple[str, str]], list[str]]:
    """返回 (可解析源码清单, 读不到/解析失败清单)——后者必须为空，否则扫描面有洞。"""
    ok: list[tuple[str, str]] = []
    bad: list[str] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            bad.append(f"<missing root {root}>")
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            try:
                src = path.read_text(encoding="utf-8")
                ast.parse(src, filename=rel)
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                bad.append(f"{rel}: {type(exc).__name__}")
                continue
            ok.append((rel, src))
    return ok, bad


def analyze(homes: list[Occ], copies: list[Occ]) -> tuple[list[DebtCopy], list[DebtHomeDup]]:
    """两本账一次算：ruleB（副本⊆真身）＋ ruleA（同集合多真身）。确定性排序。"""
    ordered_homes = sorted(homes, key=lambda o: (o.file, o.line, o.label))
    rule_b: list[DebtCopy] = []
    for occ in sorted(copies, key=lambda o: (o.file, o.line, o.label)):
        for home in ordered_homes:
            if occ.words <= home.words:
                rule_b.append(DebtCopy(occ, home))
                break
    clusters: dict[frozenset[str], list[Occ]] = defaultdict(list)
    for home in ordered_homes:
        clusters[home.words].append(home)
    rule_a = [
        DebtHomeDup(words, tuple(members))
        for words, members in sorted(clusters.items(), key=lambda kv: (len(kv[0]), sorted(kv[0])))
        if len(members) >= 2
    ]
    return rule_b, rule_a


def debt_total(rule_b: list[DebtCopy], rule_a: list[DebtHomeDup]) -> int:
    return len(rule_b) + sum(len(cluster.members) - 1 for cluster in rule_a)


class Accounting(NamedTuple):
    """同一份现算债的两层读数：**raw 永不缩**，accounted 才与上限对账。"""

    raw_total: int
    accounted_total: int
    kept_copies: tuple[DebtCopy, ...]
    exempt_copies: tuple[tuple[DebtCopy, NotDebtCopy], ...]
    kept_clusters: tuple[DebtHomeDup, ...]
    exempt_clusters: tuple[tuple[DebtHomeDup, NotDebtMirror], ...]
    #: ruleA 跨能力撞词簇：不在本账判，移交 ``test_trigger_spec``（交接对象逐枚写死）。
    exempt_handoffs: tuple[tuple[DebtHomeDup, NotDebtHandoff], ...]
    #: 名册里没命中任何现算债的条目＝虚设豁免（债已归一却还占着名 ⇒ 必须红，见活性锁）。
    stale_copy_entries: tuple[NotDebtCopy, ...]
    stale_mirror_entries: tuple[NotDebtMirror, ...]
    stale_handoff_entries: tuple[NotDebtHandoff, ...]

    @property
    def exempt_count(self) -> int:
        return (
            len(self.exempt_copies)
            + sum(len(c.members) - 1 for c, _e in self.exempt_clusters)
            + sum(len(c.members) - 1 for c, _e in self.exempt_handoffs)
        )


def account(
    rule_b: list[DebtCopy],
    rule_a: list[DebtHomeDup],
    *,
    copy_entries: tuple[NotDebtCopy, ...] = COPY_NOT_DEBT,
    mirror_entries: tuple[NotDebtMirror, ...] = HOME_MIRROR_NOT_DEBT,
    handoff_entries: tuple[NotDebtHandoff, ...] = HOME_CROSS_CAPABILITY_NOT_DEBT,
) -> Accounting:
    """按**逐枚点名**的名册把现算债分成「记账／不计账」两堆。

    匹配键刻意不含行号（行号会随任何一次编辑漂移），但**必须词集全等**：
    换一批词、换一个文件、给镜像簇多加一员 ⇒ 都不再命中 ⇒ 立刻恢复记账。
    ``copy_entries``/``mirror_entries``/``handoff_entries`` 形参只为注毒锁存在
    （摘掉某条 ⇒ 该枚必回账），生产调用一律走缺省名册。
    每条名册条目至多消费一枚现算债（多重集语义，不许一条糊两枚）。
    ruleA 簇先按在册镜像匹配、再按移交名册匹配：两本名册对同一枚簇**互斥**
    （镜像＝别的门要求它相等；移交＝没有任何门要求它相等，是词义冲突）。
    """
    spare_copies = list(copy_entries)
    kept_copies: list[DebtCopy] = []
    exempt_copies: list[tuple[DebtCopy, NotDebtCopy]] = []
    for item in rule_b:
        hit = next(
            (
                i
                for i, entry in enumerate(spare_copies)
                if entry.file == item.copy.file
                and entry.label == item.copy.label
                and entry.words == item.copy.words
            ),
            None,
        )
        if hit is None:
            kept_copies.append(item)
        else:
            exempt_copies.append((item, spare_copies.pop(hit)))

    spare_mirrors = list(mirror_entries)
    spare_handoffs = list(handoff_entries)
    kept_clusters: list[DebtHomeDup] = []
    exempt_clusters: list[tuple[DebtHomeDup, NotDebtMirror]] = []
    exempt_handoffs: list[tuple[DebtHomeDup, NotDebtHandoff]] = []
    for cluster in rule_a:
        sites = frozenset((m.file, m.label) for m in cluster.members)
        hit = next(
            (
                i
                for i, entry in enumerate(spare_mirrors)
                if entry.words == cluster.words and frozenset(entry.sites) == sites
            ),
            None,
        )
        if hit is not None:
            exempt_clusters.append((cluster, spare_mirrors.pop(hit)))
            continue
        hit = next(
            (
                i
                for i, entry in enumerate(spare_handoffs)
                if entry.words == cluster.words and frozenset(entry.sites) == sites
            ),
            None,
        )
        if hit is None:
            kept_clusters.append(cluster)
        else:
            exempt_handoffs.append((cluster, spare_handoffs.pop(hit)))

    return Accounting(
        raw_total=debt_total(rule_b, rule_a),
        accounted_total=debt_total(kept_copies, kept_clusters),
        kept_copies=tuple(kept_copies),
        exempt_copies=tuple(exempt_copies),
        kept_clusters=tuple(kept_clusters),
        exempt_clusters=tuple(exempt_clusters),
        exempt_handoffs=tuple(exempt_handoffs),
        stale_copy_entries=tuple(spare_copies),
        stale_mirror_entries=tuple(spare_mirrors),
        stale_handoff_entries=tuple(spare_handoffs),
    )


def accounted_debt() -> Accounting:
    """现算 → 计账（唯一口径；上限只与这个数对账，raw 同时留档在 --ledger 头行）。"""
    _total, rule_b, rule_a = current_debt()
    return account(rule_b, rule_a)


@lru_cache(maxsize=1)
def scan_tree() -> tuple[int, tuple[Occ, ...], tuple[Occ, ...]]:
    ok, bad = iter_tree_sources()
    assert not bad, (
        f"扫描面有洞（{len(bad)} 个文件读不到/解析失败，前几个：{bad[:3]}）——不许带洞记账"
    )
    homes: list[Occ] = []
    copies: list[Occ] = []
    for rel, src in ok:
        h, c = scan_source(rel, src)
        homes.extend(h)
        copies.extend(c)
    homes.sort(key=lambda o: (o.file, o.line, o.label))
    copies.sort(key=lambda o: (o.file, o.line, o.label))
    return len(ok), tuple(homes), tuple(copies)


def current_debt() -> tuple[int, list[DebtCopy], list[DebtHomeDup]]:
    _files, homes, copies = scan_tree()
    rule_b, rule_a = analyze(list(homes), list(copies))
    return debt_total(rule_b, rule_a), rule_b, rule_a


def _synth_table_src(name: str, words: set[str] | frozenset[str], wrapper: str = "") -> str:
    """用真账现算的词生成一份可解析源码（注毒专用；本文件因此自身零词面字面量）。"""
    body = ", ".join('"' + w + '"' for w in sorted(words))
    if wrapper:
        return f"{name} = {wrapper}({{{body}}})\n"
    return f"{name} = ({body},)\n"


# ---------------------------------------------------------------------------
# 账
# ---------------------------------------------------------------------------


def test_copy_debt_within_ceiling() -> None:
    acct = accounted_debt()
    anchor_files = sorted({d.home.file for d in acct.kept_copies})[:5]
    assert acct.accounted_total <= TRIGGER_COPY_CEILING, (
        f"触发词字面量债 {acct.accounted_total} > 上限 {TRIGGER_COPY_CEILING}＝又长了新副本"
        f"（现算 raw {acct.raw_total}，其中逐枚点名豁免 {acct.exempt_count}）。"
        f"修法：副本位置改为引用真身/登记指针（记账侧 ruleB {len(acct.kept_copies)} 条、"
        f"ruleA {len(acct.kept_clusters)} 簇；锚点真身大户：{anchor_files}）；明细跑 --ledger"
    )


def test_zero_slack_ceiling_equals_latest_audit() -> None:
    """零余量锁：上限必须恰等于最近一次现算核账值——想留余量，先把真实账降下去。"""
    assert TRIGGER_COPY_CEILING == AUDIT_HISTORY[-1][1], (
        "上限≠最近核账值＝偷偷留了余量（或降了账没刷历史）"
    )


def test_ceiling_is_hand_written_literal() -> None:
    """结构锁：上限与核账历史必须是本文件里的手写字面量，不许与被检对象联动。"""
    assigned: dict[str, ast.expr | None] = {}
    for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            assigned[node.target.id] = node.value
    ceiling = assigned.get("TRIGGER_COPY_CEILING")
    assert isinstance(ceiling, ast.Constant) and isinstance(ceiling.value, int), (
        "TRIGGER_COPY_CEILING 被改成派生表达式＝账跟着被检对象一起动，本门结构性失效"
    )
    history = assigned.get("AUDIT_HISTORY")
    assert isinstance(history, (ast.Tuple, ast.List)) and len(history.elts) >= 1, (
        "AUDIT_HISTORY 必须留在本文件且非空——它是「只准降」的对账凭据"
    )


def test_audit_history_never_rises() -> None:
    counts = [count for _, count in AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{AUDIT_HISTORY}"
    assert TRIGGER_COPY_CEILING <= counts[0], "上限超过首届核账值＝调大换绿，本门不允许"


def test_scan_scope_did_not_collapse() -> None:
    """塌陷锁：扫描面、真身识别、账本非空、谓词自反——四把都攥住才许谈绿。"""
    files, homes, copies = scan_tree()
    assert files >= MIN_SCANNED_FILES, f"只扫到 {files} 个文件（地板 {MIN_SCANNED_FILES}）＝扫描面塌陷"
    assert len(homes) >= MIN_HOME_TABLES, f"只认出 {len(homes)} 枚真身表（地板 {MIN_HOME_TABLES}）＝判据被改瞎"
    assert copies, "一条副本候选都没收到＝tier-2 取数口坏了，不是全树干净"
    for anchor_file, anchor_label, rep_word in _ANCHOR_HOMES:
        hit = [h for h in homes if h.file == anchor_file and h.label == anchor_label]
        assert hit, f"锚点真身没被认出：{anchor_file}:{anchor_label}"
        assert any(rep_word in h.words for h in hit), f"锚点 {anchor_label} 里代表词丢失：{rep_word}"
    rule_b, rule_a = analyze(list(homes), list(copies))
    assert rule_b or rule_a, "债务账为空——若真全部归一，请删本门并留说明，别留空转锁"
    for item in rule_b:
        assert item.copy.words <= item.home.words, "ruleB 记账未过子集谓词＝两本口径分叉"
    for cluster in rule_a:
        assert len(cluster.members) >= 2, "ruleA 单成员成簇＝判据写错"
        assert all(m.words == cluster.words for m in cluster.members), "ruleA 成员词集不等＝聚合逻辑坏"


def test_not_debt_register_is_live_and_closed() -> None:
    """名册活性与守恒锁：豁免数＝名册条数（不许一条糊两枚）、无虚设条目、raw＝计账＋豁免。

    「虚设豁免」＝有人已把这枚债归一、名册却还占着一格：它会在下一枚同形新债上**静默放行**，
    所以必须当场红，而不是留着当保险。
    """
    acct = accounted_debt()
    assert not acct.stale_copy_entries, f"ruleB 名册虚设（盘上已无此债）：{acct.stale_copy_entries}"
    assert not acct.stale_mirror_entries, f"ruleA 名册虚设（盘上已无此簇）：{acct.stale_mirror_entries}"
    assert not acct.stale_handoff_entries, (
        f"移交名册虚设（盘上已无此撞词簇，或该簇已换词/换位不再命中）：{acct.stale_handoff_entries}"
    )
    assert len(acct.exempt_copies) == len(COPY_NOT_DEBT), (
        f"ruleB 豁免 {len(acct.exempt_copies)} 枚 ≠ 名册 {len(COPY_NOT_DEBT)} 条＝有条目吞了多枚债或没命中"
    )
    assert len(acct.exempt_clusters) == len(HOME_MIRROR_NOT_DEBT), (
        f"ruleA 豁免 {len(acct.exempt_clusters)} 簇 ≠ 名册 {len(HOME_MIRROR_NOT_DEBT)} 条"
    )
    assert len(acct.exempt_handoffs) == len(HOME_CROSS_CAPABILITY_NOT_DEBT), (
        f"移交豁免 {len(acct.exempt_handoffs)} 簇 ≠ 名册 {len(HOME_CROSS_CAPABILITY_NOT_DEBT)} 条"
    )
    assert not {
        frozenset((m.file, m.label) for m in c.members)
        for c, _e in acct.exempt_clusters
    } & {
        frozenset((m.file, m.label) for m in c.members)
        for c, _e in acct.exempt_handoffs
    }, "同一枚簇既进在册镜像又进移交名册＝两本名册必须互斥"
    assert acct.raw_total == acct.accounted_total + acct.exempt_count, (
        f"账不守恒：raw {acct.raw_total} ≠ accounted {acct.accounted_total} ＋ 豁免 {acct.exempt_count}"
    )
    assert acct.raw_total >= acct.accounted_total, "豁免算出负数＝计数口径坏"


def test_not_debt_register_is_not_a_blanket_clause() -> None:
    """禁条款化锁：每条豁免都必须**指到一枚具体的盘上债**，且各写各的判据。

    ① 文件必须真实存在（路径写错＝静默永不命中，等价于把判据改成「凡此类别一律不计」）；
    ② ``words_text`` 至少两词（单词或空串就是通配的雏形）；
    ③ ``kind`` 只许取词表内三个可读标签，**kind 从不参与匹配**（匹配只看 file/label/words）；
    ④ reason 互不相同且够长——两条共用一句话即退化为一条 blanket 条款。
    """
    reasons: list[str] = []
    for entry in COPY_NOT_DEBT:
        assert (REPO_ROOT / entry.file).is_file(), f"名册指向不存在的文件：{entry.file}"
        assert entry.label, f"名册 label 为空＝按文件整片豁免的雏形：{entry.file}"
        assert len(entry.words) >= 2, f"名册词集不足两枚＝条款化：{entry.file}:{entry.label}"
        assert entry.kind in NOT_DEBT_KINDS, f"未知分类标签：{entry.kind}"
        assert "|" not in entry.file + entry.label + entry.words_text + entry.kind + entry.reason, (
            f"名册正文含竖线会被本门 tier-2 的 regexstr 口扫成灾：{entry.file}"
        )
        reasons.append(entry.reason)
    for mirror in HOME_MIRROR_NOT_DEBT:
        assert len(mirror.sites) >= 2, "镜像簇名册不足两员＝条款化"
        for site_file, site_label in mirror.sites:
            assert (REPO_ROOT / site_file).is_file(), f"镜像簇名册路径不存在：{site_file}"
            assert site_label, f"镜像簇名册 label 为空：{site_file}"
        assert len(mirror.words) >= 2, f"镜像簇词集不足两枚＝条款化：{mirror.words_text}"
        assert "|" not in mirror.words_text and "|" not in mirror.reason
        reasons.append(mirror.reason)
    for handoff in HOME_CROSS_CAPABILITY_NOT_DEBT:
        assert len(handoff.sites) >= 2, "移交簇名册不足两员＝条款化"
        for site_file, site_label in handoff.sites:
            assert (REPO_ROOT / site_file).is_file(), f"移交簇名册路径不存在：{site_file}"
            assert site_label, f"移交簇名册 label 为空：{site_file}"
        assert len(handoff.words) >= 2, f"移交簇词集不足两枚＝条款化：{handoff.words_text}"
        assert "|" not in handoff.words_text and "|" not in handoff.reason
        #: 交接对象必须指到**盘上真实存在的门与用例名**——写个不存在的门名＝把"有人接"写成空话，
        #: 本枚就变成只删不接。用例名的存在性由对面门自己那条互锁负责核对（此处核对文件与符号）。
        target_file, _, target_test = handoff.handed_to.partition("::")
        assert (REPO_ROOT / target_file).is_file(), f"移交对象文件不存在：{handoff.handed_to}"
        assert target_test.startswith("test_"), f"移交对象不是用例：{handoff.handed_to}"
        assert target_test in (REPO_ROOT / target_file).read_text(encoding="utf-8"), (
            f"移交对象用例不存在：{handoff.handed_to}＝这枚摘牌没人接"
        )
        reasons.append(handoff.reason)
    assert all(len(r) >= 20 for r in reasons), "有豁免条目 reason 短于 20 字符＝没写判据"
    assert len(set(reasons)) == len(reasons), "两条豁免共用一句判据＝这就是被禁的 blanket 条款"


# ---------------------------------------------------------------------------
# 注毒自证（内存源码喂同一取数口，绝不往树里写东西；逐发验牙）
# ---------------------------------------------------------------------------


def _debt_with_virtual(rel: str, src: str) -> int:
    _files, homes, copies = scan_tree()
    extra_homes, extra_copies = scan_source(rel, src)
    rule_b, rule_a = analyze(list(homes) + extra_homes, list(copies) + extra_copies)
    return debt_total(rule_b, rule_a)


def _accounting_with_virtual(rel: str, src: str) -> Accounting:
    """同一取数口吃虚拟源 ⇒ 同时给 raw 与 accounted 两层读数（豁免不许被虚拟源骗到）。"""
    _files, homes, copies = scan_tree()
    extra_homes, extra_copies = scan_source(rel, src)
    rule_b, rule_a = analyze(list(homes) + extra_homes, list(copies) + extra_copies)
    return account(rule_b, rule_a)


def _synth_dict_src(name: str, words: set[str] | frozenset[str], value_src: str) -> str:
    """合成一份**模块级 dict 字面量**源码（真债伪装成 dictkeys 形态用）。"""
    body = ", ".join('"' + w + '": ' + value_src for w in sorted(words))
    return f"{name} = {{{body}}}\n"


#: 注毒用的词集一律**从名册现取**（不在本文件里重列字面量容器，见 ``_KIND_VOCAB`` 同条理由）。
_COLOR_TABLE_ENTRY: Final[NotDebtCopy] = next(
    entry for entry in COPY_NOT_DEBT if entry.file.endswith("domains/weather/capabilities/weather.py")
)
_ENVELOPE_ENTRY: Final[NotDebtCopy] = next(
    entry
    for entry in COPY_NOT_DEBT
    if entry.file.endswith("tests/test_pipeline_managed_adapter.py")
)
_MIRROR_PROBE_ENTRY: Final[NotDebtMirror] = min(
    HOME_MIRROR_NOT_DEBT, key=lambda entry: (len(entry.words), entry.words_text)
)


def test_poison_real_debt_disguised_as_exempted_dictkeys_is_counted() -> None:
    """注毒⑤（简报点名必含的一发）：**真债伪装成已被豁免的 dictkeys 形态，仍必须被记账**。

    合成一份与 `ALARM_COLOR_RANK`／`_ALARM_COLOR_RANK` **同形态同词集**的色→整数表，
    放在一个**没进名册**的新位置 ⇒ 名册不许顺着「像不像序位表」外推，raw 与 accounted 各 +1。
    这条锁的存在理由：本门刻意**不设**「值不像词就不算债」的结构闸——那条通用规则会连带摘掉
    `tests/test_emergency_info_sources.py:216` 那枚 ``{"黄色": 183, …}`` 真债（S106 判 (a)）。
    """
    base = accounted_debt()
    rel = "plugins/bot_unified_runtime/domains/ops/_s131_poison_virtual_rank_dict.py"
    src = _synth_dict_src("S131_POISON_COLOR_ORDER", _COLOR_TABLE_ENTRY.words, "1")
    acct = _accounting_with_virtual(rel, src)
    assert acct.raw_total == base.raw_total + 1, "dictkeys 形态的真债连 raw 都没进＝tier-2 取数口失明"
    assert acct.accounted_total == base.accounted_total + 1, (
        "同形态同词集的新副本被名册顺带豁免＝逐枚点名退化成 blanket 条款"
    )
    assert len(acct.exempt_copies) == len(COPY_NOT_DEBT), "豁免数被这发注毒改动＝匹配不精确"


def test_poison_second_contract_context_dict_at_new_path_is_counted() -> None:
    """注毒⑥：再来一发同形态豁免外推——``{"config": None, "decision": None}`` 出现在新文件。

    9 枚契约字段名信封都在名册上，靠的是「这个文件的这一处是夹具」这一具体事实；
    换一个文件复用同一词集 ⇒ 必须照常记账（两本账各 +1）。
    """
    base = accounted_debt()
    rel = "tests/_s131_poison_virtual_envelope.py"
    acct = _accounting_with_virtual(
        rel, _synth_dict_src("S131_POISON_ENVELOPE", _ENVELOPE_ENTRY.words, "None")
    )
    assert acct.raw_total == base.raw_total + 1, "信封形态没进 raw＝tier-2 dict 口被改坏"
    assert acct.accounted_total == base.accounted_total + 1, "豁免顺着词集外推到别的文件＝条款化"


def test_poison_third_member_of_exempted_mirror_cluster_revives_debt() -> None:
    """注毒⑦：在册镜像簇**多出一员** ⇒ 该簇立刻从豁免回到记账，且按 3 员计超额（+2）。

    豁免只承认「这两枚位置互为镜像」这一具体结构；第三处抄同样的词就是真的第二副本＋1。
    """
    base = accounted_debt()
    mirror = _MIRROR_PROBE_ENTRY
    rel = "plugins/bot_unified_runtime/domains/ops/_s131_poison_virtual_third.py"
    src = _synth_table_src("S131_POISON_TRIGGER_WORDS", set(mirror.words))
    acct = _accounting_with_virtual(rel, src)
    assert acct.accounted_total == base.accounted_total + 2, (
        f"镜像簇被加员后仍享受原豁免＝按名册词集通配匹配（应 file+label 精确）："
        f"{base.accounted_total}→{acct.accounted_total}"
    )
    assert not any(entry is mirror for _c, entry in acct.exempt_clusters), "被加员的簇还在豁免堆里"
    assert mirror in acct.stale_mirror_entries, "原两员豁免此刻应转为虚设（活性锁同日会点名）"


#: 移交桶注毒用的条目（同样从名册现取，本文件因此继续零词面字面量）。
_HANDOFF_PROBE_ENTRY: Final[NotDebtHandoff] = HOME_CROSS_CAPABILITY_NOT_DEBT[0]


def test_poison_third_member_of_handoff_cluster_revives_debt() -> None:
    """注毒⑨（S137 新腿）：**已移交**的撞词簇多出一员 ⇒ 精确键不再命中 ⇒ 回到本账计超额（+2）。

    移交豁免只承认「这两枚位置分属两个能力、构成词义冲突」这一具体结构；
    第三处抄同一批词＝真的又多了一处第二真身，本门必须重新记账，
    不许因为"这一簇已经移交给别人"就连新副本一起放行。
    """
    base = accounted_debt()
    assert base.exempt_handoffs, "前提：移交桶今天确实挡着一枚（否则本条是空跑）"
    rel = "plugins/bot_unified_runtime/domains/ops/_s137_poison_virtual_third.py"
    src = _synth_table_src("S137_POISON_TRIGGER_WORDS", set(_HANDOFF_PROBE_ENTRY.words))
    acct = _accounting_with_virtual(rel, src)
    assert acct.accounted_total == base.accounted_total + 2, (
        f"移交簇被加员后仍享受豁免＝按名册词集通配匹配（应 sites 精确）："
        f"{base.accounted_total}→{acct.accounted_total}"
    )
    assert not any(entry is _HANDOFF_PROBE_ENTRY for _c, entry in acct.exempt_handoffs), (
        "被加员的簇还在移交堆里＝移交匹配没吃到成员位集合"
    )
    assert _HANDOFF_PROBE_ENTRY in acct.stale_handoff_entries, "原两员移交此刻应转为虚设（活性锁点名）"


def test_poison_exemption_is_word_exact_within_exempted_file() -> None:
    """注毒⑧：**已在册豁免的文件**里再抄一批别的词 ⇒ 必须记账（键含词集全等，不含行号）。"""
    base = accounted_debt()
    tts_home = _home_by("domains/media/capabilities/tts.py", "DEFAULT_TRIGGER_WORDS")
    rel = "plugins/bot_unified_runtime/domains/weather/capabilities/weather.py"  # 该文件已有一枚豁免
    assert any(entry.file == rel for entry in COPY_NOT_DEBT), "前提：weather.py 确实有一枚在册豁免"
    src = _synth_dict_src("S131_POISON_WEATHER_EXTRA", set(sorted(tts_home.words)[:3]), '"x"')
    acct = _accounting_with_virtual(rel, src)
    assert acct.accounted_total == base.accounted_total + 1, (
        "同文件不同词集被一并豁免＝按文件整片放行"
    )


def test_every_register_entry_pulls_its_own_weight() -> None:
    """逐枚干活的锁：把任意一条豁免从名册里摘掉 ⇒ 计账数恰回升该条当日挡着的债数（无一装饰件）。

    这是对「写了名册但那条其实没在挡任何债」的正面否决——它同时是给 S33 首账的 81 枚
    与 S131 降账后的 43 枚之间的差额做的**逐枚**交代，不是一句「以下类别不计」。
    """
    base = accounted_debt()
    # 守恒按「恒等式」写而不按「名册条数」写：豁免桶将来再加（S137 已加过移交桶），
    # 这条前置锁不必跟着改口径。
    assert base.raw_total == base.accounted_total + base.exempt_count, (
        f"账不守恒：raw {base.raw_total} ≠ accounted {base.accounted_total} ＋ 豁免 {base.exempt_count}"
    )
    raw_b = list(base.kept_copies) + [c for c, _e in base.exempt_copies]
    raw_a = (
        list(base.kept_clusters)
        + [c for c, _e in base.exempt_clusters]
        + [c for c, _e in base.exempt_handoffs]
    )
    for index in range(len(COPY_NOT_DEBT)):
        trimmed_copies = COPY_NOT_DEBT[:index] + COPY_NOT_DEBT[index + 1 :]
        fewer = account(
            raw_b, raw_a, copy_entries=trimmed_copies, mirror_entries=HOME_MIRROR_NOT_DEBT
        )
        assert fewer.accounted_total == base.accounted_total + 1, (
            f"摘掉第 {index} 条 ruleB 豁免而计账数没动＝该条是装饰件：{COPY_NOT_DEBT[index]}"
        )
    #: 过秤期望值按「该条当日挡几枚」现算：ruleA 簇挡的是超额数 len(members)-1
    #: （两员镜像挡 1、三员镜像挡 2）。旧写死 +1 是按历史上「镜像对＝恰好两员」的形态
    #: 写的，需求 5 宿主机状态三员镜像簇（echo aliases ≡ triggers_nickname ≡ host_state
    #: DEFAULT_TRIGGER_WORDS，词集相等由双向/帮助闭合门强制）被它误判成装饰件——
    #: 2026-09-25 两席独立复算同判（S-R-TRIGDEBT-44 §叁／S-R-TRIGWORD-2RED §4），
    #: S-R-TRIGDEBT-EXEC §叁 穷举四态：条目在→旧锁红／条目摘→上限红／破成员相等→双向门红。
    #: 期望值从当轮现算命中的簇反查，比「反正会涨」的放宽**更严**：多挡一格同样红；
    #: 挡零枚的条目另由 test_not_debt_register_is_live_and_closed 的虚设锁当场点名。
    mirror_expected = {
        id(entry): len(cluster.members) - 1 for cluster, entry in base.exempt_clusters
    }
    for index in range(len(HOME_MIRROR_NOT_DEBT)):
        trimmed_mirrors = HOME_MIRROR_NOT_DEBT[:index] + HOME_MIRROR_NOT_DEBT[index + 1 :]
        fewer = account(raw_b, raw_a, copy_entries=COPY_NOT_DEBT, mirror_entries=trimmed_mirrors)
        expected = mirror_expected[id(HOME_MIRROR_NOT_DEBT[index])]
        assert fewer.accounted_total == base.accounted_total + expected, (
            f"摘掉第 {index} 条 ruleA 豁免而未恰回升 {expected} 枚该挡之债＝该条没在干活"
            f"或匹配多消费了别簇：{HOME_MIRROR_NOT_DEBT[index]}"
        )
    #: 移交桶同样逐枚过秤（期望值现算同上）：摘掉它 ⇒ 该簇立刻按超额数回到本账，
    #: 且当场不在豁免堆里。「移交」在本门一侧只是**不重复计账**，接住与否由对面门的
    #: 互锁另判（只删不接＝两边红）。
    handoff_expected = {
        id(entry): len(cluster.members) - 1 for cluster, entry in base.exempt_handoffs
    }
    for index in range(len(HOME_CROSS_CAPABILITY_NOT_DEBT)):
        trimmed_handoffs = (
            HOME_CROSS_CAPABILITY_NOT_DEBT[:index] + HOME_CROSS_CAPABILITY_NOT_DEBT[index + 1 :]
        )
        fewer = account(
            raw_b,
            raw_a,
            copy_entries=COPY_NOT_DEBT,
            mirror_entries=HOME_MIRROR_NOT_DEBT,
            handoff_entries=trimmed_handoffs,
        )
        expected = handoff_expected[id(HOME_CROSS_CAPABILITY_NOT_DEBT[index])]
        assert fewer.accounted_total == base.accounted_total + expected, (
            f"摘掉第 {index} 条移交豁免而未恰回升 {expected} 枚该挡之债＝该条没在干活："
            f"{HOME_CROSS_CAPABILITY_NOT_DEBT[index]}"
        )
        assert not any(
            entry is handoff for _c, entry in fewer.exempt_handoffs
            for handoff in HOME_CROSS_CAPABILITY_NOT_DEBT
        ), "摘掉名册条目后该簇仍在移交堆里＝匹配没吃到这条"


def _home_by(file_part: str, label: str) -> Occ:
    _files, homes, _copies = scan_tree()
    for h in homes:
        if file_part in h.file and h.label == label:
            return h
    raise AssertionError(f"注毒前置：找不到真身 {file_part}:{label}（先查判据是否被改坏）")


def test_poison_test_side_subset_is_caught() -> None:
    """注毒①（规则 B·tests 侧子集）：语音词表在测试里重列三个词 → 恰 +1 笔，锚到 tts 真身。"""
    base, _b, _a = current_debt()
    tts_home = _home_by("domains/media/capabilities/tts.py", "DEFAULT_TRIGGER_WORDS")
    subset = set(sorted(tts_home.words)[:3])  # 排序确定性，非取最小语义
    rel = "tests/_s33_poison_virtual_a.py"
    assert _debt_with_virtual(rel, _synth_table_src("S33_POISON_TRIGGERS", subset)) == base + 1, (
        "tests 里重列触发词子集没进账＝取数口对规则 B 失明"
    )


def test_poison_plugin_side_literal_copy_is_caught() -> None:
    """注毒②（规则 B·plugins 侧非真身位置）：模块级不命名命中的全量抄表 → 恰 +1 笔。"""
    base, _b, _a = current_debt()
    archive_home = _home_by("domains/media/capabilities/media_archive.py", "DEFAULT_TRIGGER_WORDS")
    rel = "plugins/bot_unified_runtime/domains/ops/_s33_poison_virtual_b.py"
    src = _synth_table_src("S33_POISON_SAMPLES", archive_home.words, wrapper="frozenset")
    assert _debt_with_virtual(rel, src) == base + 1, (
        "生产代码里抄整表没进账＝第二真身对本门隐形"
    )


def test_poison_duplicate_home_table_is_caught() -> None:
    """注毒③（规则 A·重复真身）：命名命中＋词集与既有真身全等 → 恰 +1 笔。"""
    base, _b, _a = current_debt()
    archive_home = _home_by("domains/media/capabilities/media_archive.py", "DEFAULT_TRIGGER_WORDS")
    rel = "plugins/bot_unified_runtime/domains/ops/_s33_poison_virtual_c.py"
    src = _synth_table_src("S33_POISON_TRIGGER_WORDS", archive_home.words)
    _files, homes, copies = scan_tree()
    extra_homes, extra_copies = scan_source(rel, src)
    assert extra_homes and extra_homes[0].words == archive_home.words, (
        "注毒③没被认成第二枚真身＝tier-1 命名形态识别失效"
    )
    assert not extra_copies, "注毒③被双计（home 之外又进 copy 账）＝认领机制坏"
    rule_b, rule_a = analyze(list(homes) + extra_homes, list(copies))
    assert debt_total(rule_b, rule_a) == base + 1, "同集合双真身不是恰 +1＝ruleA 计数口径漂移"


def test_pointer_prose_and_mixed_forms_are_not_debt() -> None:
    """注毒④（反向）：指针串/散文/单词/真词＋非标词的混合对/长句池 → 零进账。"""
    base, _b, _a = current_debt()
    tts_home = _home_by("domains/media/capabilities/tts.py", "DEFAULT_TRIGGER_WORDS")
    one_trigger = min(tts_home.words)
    src = (
        "TRIGGER_SOURCE_POINTER = \"domains/media/capabilities/tts.py#DEFAULT_TRIGGER_WORDS\"\n"
        "PROSE = \"用户把想说的话发过来，守岸人会轻声复述一遍\"\n"
        "SINGLE = \"" + one_trigger + "\"\n"
        "MIXED_PAIR = (\"" + one_trigger + "\", \"" + _UNEXISTENT_WORD + "\")\n"
        "LONG_POOL = (\"这句话远远超过了二十四个字符的长度上限所以它不可能是任何触发词表里的条目\",)\n"
    )
    rel = "tests/_s33_poison_virtual_d.py"
    extra_homes, extra_copies = scan_source(rel, src)
    assert not extra_homes, f"指针/散文被认成真身＝tier-1 过宽：{extra_homes}"
    # 混合对会进「候选」视野（这是扫描面完整性的要求），但 ⊄ 任何真身 → 必须零入账：
    assert all(not any(c.words <= h.words for h in scan_tree()[1]) for c in extra_copies), (
        f"合法形态被判成副本：{extra_copies}"
    )
    assert _debt_with_virtual(rel, src) == base, "合法形态进账＝负样本无牙"


def test_own_test_file_contributes_no_literals() -> None:
    """自证：本门自身的源码对两本账零贡献（毒词全部现算合成，不留字面量在盘上）。"""
    _files, _homes, _copies = scan_tree()
    rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    homes_here, copies_here = scan_source(rel, Path(__file__).read_text(encoding="utf-8"))
    assert not homes_here, f"本门文件自己不该有真身形态：{homes_here}"
    base_b, base_a = analyze(list(_homes), list(_copies))
    stripped_homes = tuple(h for h in _homes if h.file != rel)
    stripped_copies = tuple(c for c in _copies if c.file != rel)
    alt_b, alt_a = analyze(list(stripped_homes), list(stripped_copies))
    assert debt_total(base_b, base_a) == debt_total(alt_b, alt_a), (
        f"摘掉本门文件前后债数不等＝本门在给自己的账添字面量：copies_here={copies_here}"
    )


# ---------------------------------------------------------------------------
# CLI：--ledger 逐条明细（人读）／ --bless 打建议上限与历史行（归一后刷账用）
# ---------------------------------------------------------------------------


def render_ledger() -> list[str]:
    _raw, rule_b, rule_a = current_debt()
    acct = account(rule_b, rule_a)
    copy_marks: dict[tuple[str, int], NotDebtCopy] = {
        (item.copy.file, item.copy.line): entry for item, entry in acct.exempt_copies
    }
    cluster_marks: dict[frozenset[tuple[str, int]], NotDebtMirror] = {
        frozenset((m.file, m.line) for m in cluster.members): entry for cluster, entry in acct.exempt_clusters
    }
    handoff_marks: dict[frozenset[tuple[str, int]], NotDebtHandoff] = {
        frozenset((m.file, m.line) for m in cluster.members): entry
        for cluster, entry in acct.exempt_handoffs
    }
    lines = [
        (
            f"触发词字面量债：现算 raw {acct.raw_total}（ruleB 副本 {len(rule_b)} ＋ ruleA 重复真身超额 "
            f"{sum(len(c.members) - 1 for c in rule_a)}）｜计账 {acct.accounted_total}"
            f"（逐枚点名豁免 {acct.exempt_count}：ruleB {len(acct.exempt_copies)} 枚 ＋ ruleA 簇超额 "
            f"{sum(len(c.members) - 1 for c, _e in acct.exempt_clusters)} ＋ 移交他门簇超额 "
            f"{sum(len(c.members) - 1 for c, _e in acct.exempt_handoffs)}）｜上限 {TRIGGER_COPY_CEILING}"
        )
    ]
    for cluster in rule_a:
        pos = frozenset((m.file, m.line) for m in cluster.members)
        mirror_entry = cluster_marks.get(pos)
        handoff_entry = handoff_marks.get(pos)
        mark = (
            "不计账·在册镜像"
            if mirror_entry is not None
            else "不计账·跨能力撞词（移交）"
            if handoff_entry is not None
            else "记账"
        )
        lines.append(f"[{mark}] ruleA 同集合真身：" + " ｜ ".join(f"{m.file}:{m.line}:{m.label}" for m in cluster.members))
        lines.append("    词：" + "、".join(sorted(cluster.words)))
        if mirror_entry is not None:
            lines.append("    判据：" + mirror_entry.reason)
        if handoff_entry is not None:
            lines.append(f"    判据：本尺不判，移交 {handoff_entry.handed_to}")
            lines.append("    理由：" + handoff_entry.reason)
    for item in rule_b:
        copy_entry = copy_marks.get((item.copy.file, item.copy.line))
        mark = "不计账" if copy_entry is not None else "记账"
        lines.append(
            f"[{mark}] ruleB 副本：{item.copy.file}:{item.copy.line}:{item.copy.label}"
            f" ⊆ 真身 {item.home.file}:{item.home.line}:{item.home.label}"
        )
        lines.append("    词：" + "、".join(sorted(item.copy.words)))
        if copy_entry is not None:
            lines.append(f"    判据（{copy_entry.kind}）：" + copy_entry.reason)
    return lines


def main(argv: list[str]) -> int:
    if "--ledger" in argv:
        for line in render_ledger():
            print(line)
        return 0
    acct = accounted_debt()
    if "--bless" in argv:
        print(f"现算 raw = {acct.raw_total}；计账 = {acct.accounted_total}（豁免 {acct.exempt_count}）")
        print(
            f'建议：TRIGGER_COPY_CEILING = {acct.accounted_total} 且 AUDIT_HISTORY 追加 '
            f'("<今日YYYY-MM-DD>", {acct.accounted_total}),'
        )
        print("⚠ 刷账前先看 --ledger：豁免数变了就是有枚债被换了形态或换了位置，逐枚改判据、别改条款。")
        return 0
    print(
        f"计账债数 = {acct.accounted_total}（现算 raw {acct.raw_total}，豁免 {acct.exempt_count}；"
        f"上限 {TRIGGER_COPY_CEILING}）；--ledger 看明细，--bless 看刷账建议"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
