"""占卜能力（bot.divination）：八字排盘 / 塔罗牌 / 六十四卦金钱卦。

纯本地计算，无网络、无外部数据。按用户文本分子意图：

- 八字/排盘/四柱/命盘/算命/生辰 → 八字排盘；可从文本解析出生
  日期时间（如「1998年3月2日早上7点」），只给日期不具体到时辰时
  按午时（12:00）排；完全没给日期按当前时点排并附用法提示。
- 塔罗/抽塔罗/塔罗牌 → 塔罗：「每日一抽/今日塔罗」按 (日期, 用户)
  哈希确定同日同牌；带「三张/过去/未来/牌阵」走三张牌阵；
  否则单张指引。
- 占卜/起卦/算卦/摇卦/六十四卦/金钱卦/求签/求籤 → 金钱卦。

能力只返回 ``CapabilityResult``（有图时 kind="mixed"、否则 "divination"），
不直接发送；人格化包装、渲染与发送由管线统一处理。输出为娱乐向文本并附免责
尾注，不含医疗/投资等严肃建议。渲染后端可用时为结果合成 Mica 信息卡图
（复用解析卡的 render_card_png 管线），文本作 caption/兜底——后端缺失或
渲染失败时输出与纯文字版完全一致。
"""

from __future__ import annotations

import random
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
)

# V2.1 S12（W6 席）：抽签持久化与公平性服务。有 draw_store 即启用持久化
# 路径（塔罗抽取落库幂等 + 随机抽取冷却/每日配额 + 每日运势 day_key 幂等）；
# 没有存储只影响「落不落库」，不影响「用哪套算法」——发牌一律走 deck_math。
#
# **WP9 收编（2026-09-21）**：此处注入的 ``draw_store`` 是全域唯一真身
# ``store/draw_store.DrawStore``（``draws`` 表 + 幂等三键 + 写锁事务内配额），
# 算法面唯一真身是 ``data/deck_math.py``，异常全域只有一颗 ``DrawError``——
# 同一次抽牌聊天侧与控制面 REST 侧从此看到同一行。配额/算法版本一律引真身，
# 本文件不留第二份字面量（``_TAROT_*`` 只是给下面读起来顺的别名）。
from plugins.bot_unified_runtime.domains.divination.data.deck_math import (
    DECK_REVISION,
    FORTUNE_ALGORITHM_REVISION,
    FORTUNE_RULE_VERSION,
    TAROT_ALGORITHM_REVISION,
    TAROT_DAILY_ALGORITHM_REVISION,
    SystemPrng,
    card_id_for,
    draw_daily_fortune,
    draw_tarot_cards,
    fortune_day_key,
)
from plugins.bot_unified_runtime.domains.divination.data.draw_store import (
    rebuild_drawn_cards,
)
from plugins.bot_unified_runtime.domains.divination.data.ganzhi import (
    CST,
    STEM_ELEMENTS,
    STEMS,
    BaziChart,
    bazi_chart,
    format_bazi_text,
)
from plugins.bot_unified_runtime.domains.divination.data.iching import (
    cast_hexagram,
    format_cast_text,
)
from plugins.bot_unified_runtime.domains.divination.data.tarot import (
    daily_card,
    format_single_text,
    format_three_text,
)
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    build_interpretation_context,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DEFAULT_TAROT_COOLDOWN_SECONDS,
    DEFAULT_TAROT_DAILY_LIMIT,
    DrawError,
    DrawRecord,
    QuotaPolicy,
    draw_store_from_config,
    fortune_secret_from_config,
)

__all__ = [
    "DivinationIntent",
    "build_divination_capability",
    "build_divination_card_content",
    "hidden_stems_for_branch",
    "hidden_stems_section",
    "parse_divination_intent",
]

# 英文 bazi/tarot/iching/hexagram 为 T-Spec T1.2 英文触发：意图正则与
# 路由词表 _DIVINATION_COMMAND_RE 同步收录（词边界防 enriching 误中
# iching），保证 is_divination_command 命中后 parse_divination_intent 必承接。
# 全拼/缩写（T-Spec T1.5/T1.6 第三批）：拼音分支与英文同用双侧 ASCII 词边界
# （＝独立成词锚定的拼音模拟，qiguai/yaoguai 类近形词被右边界拦住）；
# 长度/URL/惯用语三守卫在 is_divination_command 判定层，拼音天然继承。
# bz（×帮助）/zb（×早报）/sz（×市值/设置）/sm（×说明）真冲突缩写不启用；
# 意图正则与路由词表逐词同步（命中必承接不变式）。
_BAZI_RE = re.compile(
    r"八字|排盘|排盤|四柱|命盘|命盤|算命|生辰|(?<![a-z0-9])bazi(?![a-z0-9])"
    r"|(?<![a-z0-9])(?:paipan|sizhu|mingpan|suanming|pp|mp)(?![a-z0-9])"
)
_TAROT_RE = re.compile(
    r"塔罗|塔羅|(?<![a-z0-9])tarots?(?![a-z0-9])|(?<![a-z0-9])(?:taluo|tl)(?![a-z0-9])"
)
_TAROT_DAILY_RE = re.compile(
    r"每日一抽|每日一簽|每日一签|今日塔罗|今日塔羅|今天塔罗|daily tarot|tarot daily"
)
_TAROT_THREE_RE = re.compile(
    r"三张|三張|过去现在未来|過去現在未來|牌阵|牌陣|three cards|tarot three"
)
# 每日运势（V2.1 S12）：等级抽签（大吉/…/凶），每日一次幂等；不含塔罗词，
# 与 _TAROT_RE 无交集。
# 【词面裁定】运势族词只进意图解析（_FORTUNE_RE → capability 直调面/
# V2.1 服务面完整可用），**不进** is_divination_command 路由判定——
# 触发双向门禁（test_route_to_help_gate_matches_ledger）要求路由词表与
# help 台账逐一对应，而 echo.py 帮助别名不在本席文件域；聊天路由可达性
# 待后续席位与 help/路由词表一次收口（届时同步收录即可，意图侧已就绪）。
_FORTUNE_RE = re.compile(r"今日运势|今日運勢|今天运势|今天運勢|运势|運勢")
_ICHING_RE = re.compile(
    r"占卜|起卦|算卦|搖卦|摇卦|六十四卦|金錢卦|金钱卦|掷卦|擲卦|一卦|求籤|求签"
    r"|(?<![a-z0-9])(?:i-?ching|hexagrams?)(?![a-z0-9])"
    r"|(?<![a-z0-9])(?:zhanbu|qigua|suangua|yaogua|liushisigua|jinqiangua"
    r"|qg|sg|yg|lssg)(?![a-z0-9])"
)

# 出生日期：「1998年3月2日」「1998-03-02」「1998/3/2」。
_DATE_RE = re.compile(
    r"(?P<year>\d{4})[年\-/.](?P<month>\d{1,2})[月\-/.](?P<day>\d{1,2})[日号]?"
)
# 时辰词与时刻：「早上7点」「晚上9点05分」「21:51」「早上7点半」。
_PERIOD_RE = re.compile(r"早上|上午|中午|下午|傍晚|晚上|夜里|深夜|凌晨")
_TIME_RE = re.compile(r"(?P<hour>\d{1,2})[点时:：]\s*(?:(?P<minute>\d{1,2})分|半)?")

_BAZI_HINT = "提示：带上出生时间可以排得更准，例如「八字 1998年3月2日早上7点」。"

# ---------------------------------------------------------------------------
# 地支藏干（纯历法数据，离线可测）：branch_index → ((stem_index, 权重%), …)，
# 首位为本气、其后为中气/余气；权重用通行子平口径（单支合计 100），
# 只用于排盘展示，不参与任何断语。
# ---------------------------------------------------------------------------
_HIDDEN_STEMS: tuple[tuple[tuple[int, int], ...], ...] = (
    ((9, 100),),                  # 子：癸
    ((5, 60), (9, 30), (7, 10)),  # 丑：己癸辛
    ((0, 60), (2, 30), (4, 10)),  # 寅：甲丙戊
    ((1, 100),),                  # 卯：乙
    ((4, 60), (1, 30), (9, 10)),  # 辰：戊乙癸
    ((2, 60), (6, 30), (4, 10)),  # 巳：丙庚戊
    ((3, 70), (5, 30)),           # 午：丁己
    ((5, 60), (3, 30), (1, 10)),  # 未：己丁乙
    ((6, 60), (8, 30), (4, 10)),  # 申：庚壬戊
    ((7, 100),),                  # 酉：辛
    ((4, 60), (7, 30), (3, 10)),  # 戌：戊辛丁
    ((8, 70), (0, 30)),           # 亥：壬甲
)
_PILLAR_LABELS = ("年柱", "月柱", "日柱", "时柱")
_ELEMENT_ORDER = ("木", "火", "土", "金", "水")


def hidden_stems_for_branch(branch_index: int) -> tuple[tuple[str, int], ...]:
    """地支藏干与权重（本气在前，权重合计 100）；序号按 12 取模防越界。"""
    return tuple(
        (STEMS[stem_index], weight)
        for stem_index, weight in _HIDDEN_STEMS[branch_index % 12]
    )


def hidden_stems_section(chart: BaziChart) -> str:
    """渲染藏干区块：逐柱「藏干」一行 + 全盘加权五行统计一行。"""
    weighted: dict[str, float] = {name: 0.0 for name in _ELEMENT_ORDER}
    parts: list[str] = []
    for label, pillar in zip(_PILLAR_LABELS, chart.pillars):
        stems = hidden_stems_for_branch(pillar.branch_index)
        parts.append(
            f"{label}{pillar.branch} "
            + "".join(f"{stem}{weight}" for stem, weight in stems)
        )
        for stem_index, weight in _HIDDEN_STEMS[pillar.branch_index]:
            weighted[STEM_ELEMENTS[stem_index]] += weight / 100.0
    summary = "　".join(
        f"{name}{weighted[name]:.1f}" for name in _ELEMENT_ORDER
    )
    return "藏干：" + "　".join(parts) + "\n藏干五行（加权）：" + summary


@dataclass(frozen=True)
class DivinationIntent:
    """占卜子意图解析结果。"""

    kind: str  # "bazi" | "tarot" | "iching" | "fortune"
    target: str = ""  # tarot: "single" | "three" | "daily"
    when: datetime | None = None  # bazi 解析出的时点；None=用当前时间
    date_given: bool = False  # 用户是否显式给了日期
    error: str = ""  # 日期解析失败时的用户可读提示


def _apply_period(hour: int, period: str) -> int:
    """按时辰词归一化小时（24 小时制）。

    下午/傍晚/晚上/夜里/深夜：小于 12 加 12，「晚上12点」按午夜 0 点；
    凌晨：「凌晨12点」按 0 点；早上/上午原样；中午按正午 12 点带 12。
    """
    if period in ("下午", "傍晚", "晚上", "夜里", "深夜"):
        return 0 if hour == 12 else (hour + 12 if hour < 12 else hour)
    if period == "凌晨":
        return 0 if hour == 12 else hour
    if period == "中午":
        return hour if hour >= 12 else hour + 12
    return hour


def _parse_bazi_when(text: str) -> tuple[datetime | None, bool, str]:
    """从文本解析出生时点：返回 (时点|None, 是否给了日期, 错误提示)。"""
    date_match = _DATE_RE.search(text)
    if date_match is None:
        return None, False, ""
    year = int(date_match.group("year"))
    month = int(date_match.group("month"))
    day = int(date_match.group("day"))
    # 只给日期不具体到时辰时按午时（12:00）排，传统排盘的通行默认。
    hour, minute = 12, 0
    after = text[date_match.end():]
    before = text[: date_match.start()]
    time_match = _TIME_RE.search(after) or _TIME_RE.search(before)
    if time_match is not None:
        window = after if time_match.string is after else before
        period_match = _PERIOD_RE.search(
            window[max(time_match.start() - 6, 0): time_match.end()]
        )
        hour = int(time_match.group("hour"))
        minute = int(time_match.group("minute") or 0)
        if period_match is not None:
            hour = _apply_period(hour, period_match.group(0))
    try:
        return datetime(year, month, day, hour, minute, tzinfo=CST), True, ""
    except ValueError as exc:
        return None, True, f"这个日期好像不太对（{exc}），检查一下再试试？"


def parse_divination_intent(text: str) -> DivinationIntent | None:
    """把用户文本解析成占卜子意图；不属于占卜域返回 None。

    日期解析失败时仍返回意图（kind=bazi），``error`` 带用户可读提示，
    由能力层优雅回复而不是静默忽略。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None

    if _BAZI_RE.search(stripped):
        when, date_given, error = _parse_bazi_when(stripped)
        return DivinationIntent(
            kind="bazi", when=when, date_given=date_given, error=error
        )

    # 每日一抽/每日一签 不含「塔罗」子串，路由词表整词收录后须在此承接
    # （头注释不变式：is_divination_command 命中 ⇒ 本函数必返回意图）。
    # 每日运势承接（V2.1 S12）：路由层命中后意图必承接的「命中必承接」
    # 不变式不受影响（运势族词当前不在路由词表，见 _FORTUNE_RE 处裁定）；
    # 放在塔罗分支之前——两词表无交集，取序无关。
    if _FORTUNE_RE.search(stripped):
        return DivinationIntent(kind="fortune")

    if _TAROT_RE.search(stripped) or _TAROT_DAILY_RE.search(stripped):
        if _TAROT_DAILY_RE.search(stripped):
            return DivinationIntent(kind="tarot", target="daily")
        if _TAROT_THREE_RE.search(stripped):
            return DivinationIntent(kind="tarot", target="three")
        return DivinationIntent(kind="tarot", target="single")

    if _ICHING_RE.search(stripped):
        return DivinationIntent(kind="iching")

    return None


# ── 路由触发判定（probe-hijack-report §① 8/8 劫持修复；只收紧此处）──
# 守卫次序（惯用语优先级最高，先于前缀白名单）：
# ①惯用语排除表——「八字还没一撇」等俗语一票否决（白名单也不豁免）；
# ②长度 + URL 守卫——>32 字或含 http(s) 链接不触发（对齐 stocks/market 的
#   _MAX_TRIGGER_LEN/_URL_HINT_RE 模式，链接让位内容解析）；
# ③独立成词锚定——中文触发词前后不贴 CJK 字符（「塔罗牌在哪买」的塔罗
#   贴着牌 → 不触发；「塔罗」「八字 1998年3月2日」裸短词照常），复合命令
#   （今日塔罗/塔罗三张/生辰八字/金钱卦/每日一抽…）与口语「X一卦」整词
#   显式收录；
# ④良性前缀白名单——「帮我/求/来/想」等口语引导豁免「前贴」否决（恢复
#   帮我占卜/来个塔罗类口语命令；简繁双表，繁體「幫我占卜/幫我搖一卦」同
#   款可达），中贴/后贴锚定照旧；否定/负面词（别/不/少/骗子…）一律不入表，
#   维持落 chat。
# 不变式维持：路由命中 ⇒ parse_divination_intent 必承接（每日一抽等
# 不含「塔罗」子串的独立触发已由意图解析的 _TAROT_DAILY_RE 分支承接，
# 「X一卦」由 _ICHING_RE 的 一卦 分支承接）。
_CJK_CHAR = r"\u4e00-\u9fff\u3400-\u4dbf"
_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 32
_DIVINATION_IDIOM_RE = re.compile("八字还没一撇|八字没一撇|八字還沒一撇|八字沒一撇")
_DIVINATION_COMMAND_RE = re.compile(
    rf"(?<![{_CJK_CHAR}])(?:八字|排盘|排盤|四柱|命盘|命盤|算命|生辰八字|塔罗|塔羅|占卜|起卦|算卦|摇卦|搖卦"
    rf"|六十四卦|金钱卦|金錢卦|今日塔罗|今天塔罗|今日塔羅|今天塔羅|塔罗三张|塔羅三張|每日一抽|每日一签|每日一簽"
    rf"|一卦|算一卦|起一卦|摇一卦|搖一卦|掷一卦|擲一卦|占一卦|求籤|求签)"
    rf"(?![{_CJK_CHAR}])"
    r"|(?<![a-z0-9])(?:divination|tarots?|bazi|i-?ching|hexagrams?)(?![a-z0-9])"
    # 全拼/缩写（T-Spec T1.5/T1.6 第三批）：与上方意图正则逐词同步（命中必承接）。
    r"|(?<![a-z0-9])(?:zhanbu|taluo|paipan|sizhu|mingpan|suanming|qigua|suangua"
    r"|yaogua|liushisigua|jinqiangua|tl|pp|mp|qg|sg|yg|lssg)(?![a-z0-9])"
)

# 良性前缀白名单（前贴口语恢复）：触发词前的常见口语引导，命中后剥掉前缀
# 再查锚定触发。表内刻意不含 算/起/摇/占 等触发词单字头（剥字会吃掉
# 「算命/起卦」的动词头，对应口语改以「X一卦」整词收录，见上）；「X个」
# 量词框架不受此限（个字隔断触发词头，算个≠算命前缀），故 算个/起个/占个
# 可入表。也不含任何否定/负面词。仅锚定字符串开头（match），不从句中剥
# （不重开句中劫持）。简繁双表同款语义：繁體新词（幫我/幫忙/請/麻煩/給我/
# 來個/來/問個/問/測個/測/搖個/擲個 及 X個 族）与简体一一对应；简繁同形词
# （求/抽/想/我想要/想要/我想/我要）只收一份。同族长词先于短词（來個 先于
# 來，剥短会留 個 隔断锚定）。
_DIVINATION_BENIGN_PREFIX_RE = re.compile(
    r"(?:请|請|麻烦|麻煩|帮我|幫我|幫忙|给我|給我|我想要|想要|我想|我要"
    r"|来个|來個|抽个|抽個|算个|算個|起个|起個|占个|占個"
    r"|摇个|搖个|搖個|掷个|擲个|擲個|问个|問個|测个|測個"
    r"|来|來|求|抽|问|問|测|測|想)+"
)
# 前缀豁免只放宽前贴；句尾语气/程度词同步豁免后贴（帮我占卜一下/来一卦吧），
# 其余后贴 CJK（塔罗牌/占卜小店）仍被锚定拦住。
_DIVINATION_SOFT_TAIL_RE = re.compile(
    r"(?:一下|一回|试试|玩玩|[呗啦吧呀嘛吗呢哦喔哈咯])+$"
)


def is_divination_command(text: str) -> bool:
    """显式玄学触发词（娱乐向）：惯用语/长度/URL/独立成词守卫 + 前缀白名单。

    含触发词的普通聊天句（塔罗牌在哪买/这事八字还没一撇呢/推荐个八字APP）
    不被占卜劫持、落回聊天；否定语境（别给我算命/少来这套迷信）不进白名单，
    照落 chat；裸短词、复合命令与白名单前缀口语命令（帮我占卜/来一卦/
    幫我搖一卦/想算命…，简繁双表）照常触发。
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    # 惯用语排除表优先级高于白名单：俗语在任何前缀下都一票否决。
    if _DIVINATION_IDIOM_RE.search(stripped):
        return False
    if _DIVINATION_COMMAND_RE.search(stripped):
        return True
    prefix = _DIVINATION_BENIGN_PREFIX_RE.match(stripped)
    if prefix is None:
        return False
    residual = _DIVINATION_SOFT_TAIL_RE.sub("", stripped[prefix.end():])
    # 残串复用同一锚定词表：前贴已被白名单豁免，中贴/后贴锚定原样生效。
    return bool(residual) and bool(_DIVINATION_COMMAND_RE.search(residual))


# 卡片来源署名：全部为本地计算，无外部数据源。
_CARD_AUTHORS = {
    "bazi": "干支历法 · 本地排盘",
    "tarot": "七十八张塔罗 · 本地抽取",
    "iching": "六十四卦金钱卦 · 本地起卦",
}

# ── V2.1 S12 持久化路径常量（全部引真身，本文件不存第二份字面量）──
# 塔罗随机抽取默认配额（合同 §3.2：每主体冷却 60 秒、每天 20 次）。
_TAROT_COOLDOWN_SECONDS = DEFAULT_TAROT_COOLDOWN_SECONDS
_TAROT_DAILY_LIMIT = DEFAULT_TAROT_DAILY_LIMIT
_TAROT_ALGO_REVISION = TAROT_ALGORITHM_REVISION
_TAROT_DAILY_ALGO_REVISION = TAROT_DAILY_ALGORITHM_REVISION
_FORTUNE_ALGO_REVISION = FORTUNE_ALGORITHM_REVISION
# 聊天面在工作区维度上的身份：与 REST 面（workspace=default / 客户端自报）
# 天然分池，两侧各自 20 次/日的配额互不挤占。
_CHAT_WORKSPACE = "chat"
_CHAT_TIMEZONE_ID = "Asia/Shanghai"

# 每日运势等级→人话一句话（温和娱乐向，不装神棍、不给"决定"）。
_FORTUNE_GRADE_TEXTS = {
    "大吉": "整体顺遂的一天，适合把搁置的事往前推一把。",
    "中吉": "平稳偏好的日子，按自己的节奏走就很顺。",
    "小吉": "小确幸藏在日常里，留意身边的小善意。",
    "平": "不好不坏的一天，稳住自己的节奏就是赢。",
    "小凶": "可能有点小磕绊，慢一点反而更稳。",
    "凶": "今天适合保守行事，大事缓一缓，先照顾好自己。",
}


def _card_dir_token(raw: str) -> str:
    """去重键 → 安全目录名：只留 ``[0-9A-Za-z_-]``，空则回退随机串。"""
    token = re.sub(r"[^0-9A-Za-z_-]", "", str(raw or ""))[:64]
    return token or uuid.uuid4().hex[:12]


def _prune_card_dirs(root: Path, *, keep: int = 120) -> int:
    """按 mtime 只保留 ``root`` 下最新 ``keep`` 个子目录，淘汰更旧的。

    占卜卡每抽落独立子目录，``cache_policy.prune_prefixed`` 的平铺文件
    前缀语义不适用；这里只删直接子目录（整棵子树），不碰散落文件。
    失败由调用方吞掉——配额清理绝不阻塞出图。
    """
    if keep <= 0 or not root.is_dir():
        return 0
    entries: list[tuple[int, Path]] = []
    for child in root.iterdir():
        try:
            if child.is_dir():
                entries.append((int(child.stat().st_mtime), child))
        except OSError:
            continue
    entries.sort(reverse=True)
    for _, stale in entries[max(0, keep):]:
        shutil.rmtree(stale, ignore_errors=True)
    return max(0, len(entries) - max(0, keep))


def build_divination_card_content(kind: str, title: str, body: str) -> Any:
    """占卜结果 → 通用卡 payload（纯构造，无 IO；能力层与测试共用）。

    ``summary`` 只承载已算出的正文文本（截 1200 字），不编造任何区块；
    ``canonical_url`` 恒为 ``about:blank``（F10 约定：无真实来源的卡不渲染
    页脚，评审 C2——内部去重键不得经 footer 泄漏给用户）。每次抽牌的
    落盘唯一性由 ``_render_card`` 的 card_dir 子目录承载，与本字段解耦。
    """
    from plugins.bot_unified_runtime.contracts import build_parsed_content

    return build_parsed_content(
        platform="divination",
        item_id=kind,
        item_kind="article",
        title=title,
        author_name=_CARD_AUTHORS.get(kind, "本地玄学计算"),
        summary=body[:1200],
        canonical_url="about:blank",
        parse_depth="deep",
    )


def build_divination_capability(
    config: Any | None = None,
    *,
    render_backend: Any | None = None,
    draw_store: Any | None = None,
    fortune_key: bytes | None = None,
    clock: Any | None = None,
) -> Any:
    """构建占卜能力：与 eat 等能力一致，返回 (message, decision) -> 结果。

    ``render_backend`` 可选：传入可用渲染后端时结果合成卡片图（kind 变
    mixed），不传或渲染失败时保持纯文字输出（行为与旧版完全一致）。

    V2.1 S12 注入面（全部可选；不传时**由域内解析口从 Config 取**，见下）：
    - ``draw_store``：全域唯一真身 ``domains.divination.store.draw_store.DrawStore``
      实例（WP9 收编后聊天与控制面 REST 共用同一个 ``draws`` 表）；有存储时塔罗抽取
      落库（draw_id/幂等键/day_key 三键幂等）、随机抽取受每主体冷却与每日配额、
      解读与渲染只消费持久行（篡改 → deck_integrity_mismatch 温和兜底）。
    - ``fortune_key``：每日运势 HMAC 密钥（服务端保管，测试注入）。
    - ``clock``：注入时钟（callable -> aware datetime），配额/日期可测。

    **S-DIV 收编（2026-09-22）**：装配半边此前无人负责——根 ``__init__.py`` 只传
    ``render_backend``，于是现网聊天跑的是收编前 ``data/tarot`` 的 rng.sample 老路径、
    一行都不落（取证 SEAT-S-DIV §1b）。现在缺省由 ``draw_store_from_config`` 现读
    在册键补齐，两侧同键同文件；键未配置 ⇒ 依旧不建库（绝不猜路径），但**发牌
    一律走唯一真身** ``deck_math`` 并过 ``validated_tarot_cards`` 完整性门。
    """

    store: Any | None = (
        draw_store if draw_store is not None else draw_store_from_config(config)
    )
    secret: bytes | None = (
        fortune_key if fortune_key is not None else fortune_secret_from_config(config)
    )

    def _current_time(message: IncomingMessage) -> datetime:
        # 注入时钟优先（配额/本地日期可测）；缺省用消息时间戳（与 bazi 口径一致）。
        return clock() if clock is not None else message.timestamp

    def _tarot_error_result(exc: DrawError, message: IncomingMessage, tags: list[str]) -> CapabilityResult:
        """抽牌失败面（持久/非持久两路共用一份文案，不留第二套说法）。"""
        if exc.code == "rate_limited":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                body=(
                    "你刚刚才抽过塔罗，先让牌面的指引沉淀一下，"
                    "稍等一分钟再来问吧。"
                ),
                audit_tags=[*tags, "divination:rate_limited"],
            )
        if exc.code == "deck_integrity_mismatch":
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                body=(
                    "这次占卜的记录好像被意外改动过，为了不给你误导的"
                    "解读，先收回这条结果。换个说法再抽一次试试？"
                ),
                audit_tags=[*tags, "divination:integrity_mismatch"],
            )
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.divination",
            kind="divination",
            body="占卜的小抽屉好像卡住了，稍后再试试好吗？",
            audit_tags=[*tags, "divination:store_error"],
        )

    def _tarot_with_store(
        intent: DivinationIntent, message: IncomingMessage, tags: list[str]
    ) -> CapabilityResult:
        """塔罗持久化路径：抽取落库幂等 + 配额 + 只按持久行出牌面。

        落库走唯一真身 ``DrawStore.persist_draw_once``，返回 ``(record, created)``；
        ``created`` 决定这轮是「新抽」还是「同一请求重放」，重放不改牌面、
        只在审计与提示上如实标注（不再靠 ``INSERT OR IGNORE`` 猜是否新建）。
        """
        if store is None:  # pragma: no cover - 调用方分支已保证非空
            raise DrawError("feature_disabled", "抽签存储未装配")
        moment = _current_time(message)
        bot_id = str(getattr(message, "bot_id", "") or "")
        sender = str(message.sender_id or "anonymous")
        local_day = moment.astimezone(CST).date()
        local_day_iso = local_day.isoformat()
        replay: list[str] = []
        try:
            if intent.target == "daily":
                # 每日一抽：draw_id/dedupe_key 含主体+本地日期 → 同日重读/重启/
                # 并发都命中同一持久行（幂等重读，不占随机抽取配额）。
                draw_id = f"tarot-daily:{bot_id}:{sender}:{local_day_iso}"
                record = store.get_draw(draw_id)
                created = False
                if record is None:
                    drawn = daily_card(local_day, sender)
                    record, created = store.persist_draw_once(
                        DrawRecord(
                            draw_id=draw_id,
                            kind="tarot",
                            principal_id=sender,
                            bot_id=bot_id,
                            workspace_id=_CHAT_WORKSPACE,
                            idempotency_key=draw_id,
                            dedupe_key=draw_id,
                            spread_id="single",
                            timezone_id=_CHAT_TIMEZONE_ID,
                            cards=(
                                {
                                    "card_id": card_id_for(drawn.card),
                                    "position_id": "",
                                    "orientation": (
                                        "reversed" if drawn.is_reversed else "upright"
                                    ),
                                },
                            ),
                            algorithm_revision=_TAROT_DAILY_ALGO_REVISION,
                            deck_revision=DECK_REVISION,
                            local_day=local_day_iso,
                            occurred_at=moment.isoformat(),
                            occurred_epoch=moment.timestamp(),
                        ),
                        quota=None,
                    )
                if not created:
                    # 幂等命中（读面已有 / 并发输者）：牌面不变，审计如实标注重放。
                    replay.append("divination:replay")
                spread = rebuild_drawn_cards(record)
                body = (
                    f"☀️ {local_day_iso} 的每日一抽（今天全天不变哦）：\n\n"
                    f"{format_single_text(spread[0])}"
                )
                title, extra = "今日塔罗", "divination:daily"
            else:
                # 随机抽取：request_id 作幂等键（同消息重试不重抽、不重复计数），
                # 配额（冷却/每日上限，与 REST 侧同一组真身缺省值）在写锁事务内判定。
                spread_id = (
                    "past_present_future" if intent.target == "three" else "single"
                )
                request_ref = str(message.request_id or "") or uuid.uuid4().hex
                draw_id = f"tarot:{request_ref}"
                record = store.get_draw(draw_id)
                created = False
                if record is None:
                    record, created = store.persist_draw_once(
                        DrawRecord(
                            draw_id=draw_id,
                            kind="tarot",
                            principal_id=sender,
                            bot_id=bot_id,
                            workspace_id=_CHAT_WORKSPACE,
                            idempotency_key=draw_id,
                            spread_id=spread_id,
                            timezone_id=_CHAT_TIMEZONE_ID,
                            cards=draw_tarot_cards(spread_id, SystemPrng()),
                            algorithm_revision=_TAROT_ALGO_REVISION,
                            deck_revision=DECK_REVISION,
                            local_day=local_day_iso,
                            occurred_at=moment.isoformat(),
                            occurred_epoch=moment.timestamp(),
                        ),
                        quota=QuotaPolicy(
                            cooldown_seconds=_TAROT_COOLDOWN_SECONDS,
                            daily_limit=_TAROT_DAILY_LIMIT,
                        ),
                    )
                if not created:
                    replay.append("divination:replay")
                # 展示与解读都从持久行校验重建——函数上不可能换牌/换朝向。
                build_interpretation_context(record)  # 篡改防线（解读桩位：LLM 解读由后续席位接入）
                spread = rebuild_drawn_cards(record)
                if len(spread) == 3:
                    body = format_three_text(spread)
                    title = "塔罗三张牌阵"
                else:
                    body = format_single_text(spread[0])
                    title = "塔罗指引"
                extra = "divination:persisted"
        except DrawError as exc:
            return _tarot_error_result(exc, message, tags)
        card = _render_card("tarot", title, body, message.request_id or "")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.divination",
            kind="mixed" if card else "divination",
            title=title,
            body=body,
            images=[{"file": card}] if card else [],
            audit_tags=[
                *tags,
                extra,
                *replay,
                "card_rendered" if card else "text_only",
            ],
        )

    def _tarot_without_store(
        intent: DivinationIntent, message: IncomingMessage, tags: list[str]
    ) -> CapabilityResult:
        """未装配存储时的降级面：发牌仍是唯一真身 ``deck_math``，只少那一行落库。

        牌面先组一条**不入库**的 ``DrawRecord``，再走与持久路径同一颗
        ``rebuild_drawn_cards``（内含 ``validated_tarot_cards``）——聊天正文与控制面
        解读因此过同一道完整性门，不存在「降级=换回 rng.sample 老算法」的第二条路。
        """
        moment = _current_time(message)
        bot_id = str(getattr(message, "bot_id", "") or "")
        sender = str(message.sender_id or "anonymous")
        local_day = moment.astimezone(CST).date()
        local_day_iso = local_day.isoformat()
        cards: tuple[dict[str, str], ...]
        try:
            if intent.target == "daily":
                # 每日一抽的确定性种子全域只有一处实现（tarot.daily_card），
                # 持久路径同样调它 ⇒ 这里不是第二套算法，而是同一张牌少落一次库。
                spread_id = "single"
                drawn = daily_card(local_day, sender)
                cards = (
                    {
                        "card_id": card_id_for(drawn.card),
                        "position_id": "",
                        "orientation": "reversed" if drawn.is_reversed else "upright",
                    },
                )
                algorithm_revision = _TAROT_DAILY_ALGO_REVISION
            else:
                spread_id = (
                    "past_present_future" if intent.target == "three" else "single"
                )
                cards = draw_tarot_cards(spread_id, SystemPrng())
                algorithm_revision = _TAROT_ALGO_REVISION
            spread = rebuild_drawn_cards(
                DrawRecord(
                    draw_id=f"tarot:ephemeral:{message.request_id or uuid.uuid4().hex}",
                    kind="tarot",
                    principal_id=sender,
                    bot_id=bot_id,
                    workspace_id=_CHAT_WORKSPACE,
                    idempotency_key="",
                    spread_id=spread_id,
                    timezone_id=_CHAT_TIMEZONE_ID,
                    cards=cards,
                    algorithm_revision=algorithm_revision,
                    deck_revision=DECK_REVISION,
                    local_day=local_day_iso,
                    occurred_at=moment.isoformat(),
                    occurred_epoch=moment.timestamp(),
                )
            )
            if intent.target == "daily":
                body = (
                    f"☀️ {local_day_iso} 的每日一抽（今天全天不变哦）：\n\n"
                    f"{format_single_text(spread[0])}"
                )
                title, extra = "今日塔罗", "divination:daily"
            elif len(spread) == 3:
                body = format_three_text(spread)
                title, extra = "塔罗三张牌阵", "divination:three"
            else:
                body = format_single_text(spread[0])
                title, extra = "塔罗指引", "divination:ephemeral"
        except DrawError as exc:
            return _tarot_error_result(exc, message, tags)
        card = _render_card("tarot", title, body, message.request_id or "")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.divination",
            kind="mixed" if card else "divination",
            title=title,
            body=body,
            images=[{"file": card}] if card else [],
            audit_tags=[*tags, extra, "card_rendered" if card else "text_only"],
        )

    def _render_card(kind: str, title: str, body: str, dedupe_key: str) -> str:
        """占卜结果合成 Mica 卡图；后端不可用或任何失败返回空串。

        去重键只进落盘目录（``card_dir`` 的每抽唯一子目录），不进
        canonical_url——占卜卡文件名互不覆写，footer 零内部信息。
        """
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
                render_card_png,
            )

            item = build_divination_card_content(kind, title, body)
            base_dir = str(
                getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
            )
            divination_root = Path(base_dir) / "divination"
            payload = render_card_png(
                render_backend,
                item,
                config=config,
                card_dir=str(divination_root / _card_dir_token(dedupe_key)),
                feature_label="占卜",
            )
            if isinstance(payload, dict) and payload.get("file"):
                try:
                    _prune_card_dirs(divination_root, keep=120)
                except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
                    pass
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本结果。
            return ""
        return str(payload.get("file") or "") if isinstance(payload, dict) else ""

    def capability(message: IncomingMessage, _decision: BotDecision) -> CapabilityResult:
        intent = parse_divination_intent(message.plain_text or "")
        if intent is None:  # pragma: no cover - 路由命中后才进入，理论不可达
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                body="想试试八字排盘、塔罗或金钱卦吗？直接说「塔罗」「占卜」或「排盘」。",
                audit_tags=["capability:divination", "divination:noop"],
            )
        tags = ["capability:divination", f"divination:{intent.kind}"]
        try:
            if intent.kind == "fortune":
                # 每日运势：等级抽签，day_key（主体+bot+本地日期+rule_version）
                # 幂等——同日重读/重启/密钥轮换都不重抽。store/key 未装配时
                # 温和提示功能未启用，绝不写默认路径（源码树 data/ 红线）。
                if store is None or not secret:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.divination",
                        kind="divination",
                        body=(
                            "每日运势还在整理中，先让塔罗牌陪陪你吧——"
                            "直接说「塔罗」就能抽一张。"
                        ),
                        audit_tags=[*tags, "divination:fortune_disabled"],
                    )
                moment = _current_time(message)
                bot_id = str(getattr(message, "bot_id", "") or "")
                sender = str(message.sender_id or "anonymous")
                local_date = moment.astimezone(CST).date().isoformat()
                day_key = fortune_day_key(
                    sender, bot_id, local_date, FORTUNE_RULE_VERSION
                )
                record = store.find_by_dedupe("fortune", day_key)
                created = False
                replay: list[str] = []
                if record is None:
                    outcome = draw_daily_fortune(
                        secret, sender, bot_id, local_date, FORTUNE_RULE_VERSION
                    )
                    fortune_draw_id = f"fortune:{day_key}"
                    record, created = store.persist_draw_once(
                        DrawRecord(
                            draw_id=fortune_draw_id,
                            kind="fortune",
                            principal_id=sender,
                            bot_id=bot_id,
                            workspace_id=_CHAT_WORKSPACE,
                            idempotency_key=fortune_draw_id,
                            dedupe_key=day_key,
                            timezone_id=_CHAT_TIMEZONE_ID,
                            fortune_grade=outcome.grade,
                            algorithm_revision=_FORTUNE_ALGO_REVISION,
                            key_id=outcome.key_id,
                            seed_digest=outcome.seed_digest,
                            local_day=local_date,
                            occurred_at=moment.isoformat(),
                            occurred_epoch=moment.timestamp(),
                        ),
                        quota=None,
                    )
                if not created:
                    # 读面命中或并发输者：同日等级唯一不变，审计如实标注重放。
                    replay.append("divination:replay")
                grade = str(record.fortune_grade)
                body = (
                    f"☀️ {local_date} 的每日运势（今天全天不变哦）：\n\n"
                    f"【{grade}】"
                    f"{_FORTUNE_GRADE_TEXTS.get(grade, '平稳的一天，按自己的节奏来就好。')}\n\n"
                    "（每日运势仅供娱乐，别拿它做重要决定哦。）"
                )
                card = _render_card(
                    "tarot", "今日运势", body, message.request_id or ""
                )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.divination",
                    kind="mixed" if card else "divination",
                    title="今日运势",
                    body=body,
                    images=[{"file": card}] if card else [],
                    audit_tags=[
                        *tags,
                        "divination:fortune_persisted",
                        *replay,
                        "card_rendered" if card else "text_only",
                    ],
                )
            if intent.kind == "bazi":
                if intent.error:
                    return CapabilityResult(
                        request_id=message.request_id,
                        capability_id="bot.divination",
                        kind="divination",
                        title="八字排盘",
                        body=f"{intent.error}\n{_BAZI_HINT}",
                        audit_tags=[*tags, "divination:invalid_date"],
                    )
                when = intent.when if intent.when is not None else (
                    message.timestamp.astimezone(CST)
                )
                chart = bazi_chart(when)
                # 藏干区块插在免责尾注之前（format_bazi_text 末行固定为尾注）。
                rendered = format_bazi_text(chart)
                head, sep, tail = rendered.rpartition("\n")
                body = (
                    f"{head}\n{hidden_stems_section(chart)}\n{tail}"
                    if sep
                    else f"{rendered}\n{hidden_stems_section(chart)}"
                )
                if not intent.date_given:
                    body = f"{body}\n（未带出生时间，按当前时点排盘。{_BAZI_HINT}）"
                card = _render_card(
                    "bazi", "八字排盘", body, message.request_id or ""
                )
                return CapabilityResult(
                    request_id=message.request_id,
                    capability_id="bot.divination",
                    kind="mixed" if card else "divination",
                    title="八字排盘",
                    body=body,
                    images=[{"file": card}] if card else [],
                    audit_tags=[*tags, "card_rendered" if card else "text_only"],
                )
            if intent.kind == "tarot":
                if store is not None:
                    return _tarot_with_store(intent, message, tags)
                return _tarot_without_store(intent, message, tags)
            cast = cast_hexagram(random.Random())
            body = format_cast_text(cast)
            card = _render_card("iching", "金钱卦", body, message.request_id or "")
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="mixed" if card else "divination",
                title="金钱卦",
                body=body,
                images=[{"file": card}] if card else [],
                audit_tags=[*tags, "divination:cast", "card_rendered" if card else "text_only"],
            )
        except ValueError as exc:
            # 超出支持区间等计算错误：优雅降级为提示，不抛给管线。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.divination",
                kind="divination",
                title="占卜",
                body=(
                    f"这个时点超出了可排盘的范围（{exc}），"
                    "换个 1900-2100 年之间的时间试试？"
                ),
                audit_tags=[*tags, "divination:out_of_range"],
            )

    return capability
