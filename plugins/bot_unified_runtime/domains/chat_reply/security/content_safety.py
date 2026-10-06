"""Deterministic public-space safety gate; no model call.

2026-09-20 内容政策修订（用户两轮裁定，v21r5 POLICY-RELAX 席落地）：
explicit 会话（私聊/控制台/已获准群聊）的拦截面收敛为「六条硬线 + minors」，
其余全部交给人格层按场景语气自然处理。六条硬线是**全场景**拦截——任何
会话模式、用户设定、亲密模式开关、管理员身份都不可架空（意志自主条款的
结构性落地：硬线规则 scope="all"，assess 时不看任何放行参数，也没有任何
可传入的覆盖开关，fail-closed）。

六条硬线（用户 2026-09-20 原文口径）：
  ① 伤害身体/残害身体（含任何场景严重暴力，4.13 裁定并入）
  ② 窒息
  ③ 侮辱性调教/系统级人格贬低（4.9 裁定并入；场景内轻度 dirty talk 不拦，
     拦的是把人格/意志/尊严系统性碾碎贬低的玩法）
  ④ 恋童/未成年（儿童化信号 fail-closed：幼态/娇小体态必须在角色为
     「明确无歧义的自主意识成年人」时才放行；儿童化信号即使声称成年也拒绝）
  ⑤ 暴力 SM（致伤致残级；轻痛感不致伤——滴蜡/电击/拍打等——放行）
  ⑥ 非人化牲口式对待（4.6 裁定并入；breeding/繁殖场景的牲畜化虐待）
  ⑦ 排泄物（r18-taxonomy 3.4「维持禁」，CRIT-FIX-3 席补词面入硬线族）

放开面（explicit 会话内畅通，不设词面拦截）：触手/幻想非人生物、轻度温柔
非暴力 SM、兽人/毛毛、虚构成年角色间乱伦、公共场所暴露/偷窥（虚构）、
睡眠/无意识、药物/催情/醉态、强制女装/TSF、轻痛感刺激、吞食/vore（纯
幻想）、人机改造/义体化、巨大化/体型差、变形/兽化、拘禁/监禁（非严重
暴力）、怀孕/繁殖/breeding/产卵（非牲口式）。

非 explicit 会话（普通群聊等公开面）行为不变：sexual/骚扰/政治/人格破坏
等公开面规则照旧（婉拒池不动）。未成年×性共现仍为全场景绝对红线。

匹配面的繁简折形（2026-09-21 WP2 席：手写字级对照表 → 现成繁简转换库）：
一切词面只登记简体字形，繁体输入必须先折形再匹配，否则上述红线被整种语言
旁路。库不可用时降级到字级兜底表并显式告警——不存在「静默不折形」这条路。
选型依据、探针自检与降级代价见下方折形段注释。
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060-\u2064\u00ad\u180e]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# 繁简折形（2026-09-21 深读波 D3-3 定罪 → 同日 WP2 席换库根治）
#
# 病灶：本模块所有拦截词面只登记**简体字形**，而 NFKC **不做繁简互转** ⇒
# 「她12歲做愛」的 歲≠岁、愛≠爱，信号侧与性侧双双不中，六硬线与 minors 这条
# 「全项目唯一不服从用户字面指令的 fail-closed 红线」被整种语言旁路，且经
# memory_sanitize 的单一来源同步传导到清洗面。
#
# 设计=**匹配面折形、词面零副本**：只在 normalize_for_matching 里折一次，
# 全部 pattern（含未来新增）自动获得繁体同判能力；不在各 pattern 里逐词补
# 繁体对映形（那会把一个事实抄成 N 份）。
#
# 为什么换库（用户 2026-09-21 裁定 C=接现成库，明确接受多一个外部依赖）：
# 上一轮手写的字级表（102 对）天花板明写在注释里——它只覆盖 179 枚与词面相关的
# 繁体字中的 101 枚，表外的 寫/揷/躶/嵗/喫/紮/搤/癈/淩/翫/發/養/個/洩 … 以及
# 一切异体/粤语/书面写法照旧整体绕过。词表由库维护，本项目不再手写第三份。
# 选型=zhconv（纯 Python、零传递依赖、词表 JSON 随包离线可用、5000 次折形
# ≈18ms），对照候选 opencc-python-reimplemented 实测慢 5.9 倍且 著→着 亦不折。
#
# ⚠ 库用法的一条静默陷阱（简报里写的是 `convert(s,'cn')`，**那是错的**）：
# zhconv 对未注册 locale 走 `locale not in Locales → return s` 分支，即
# `convert("她12歲做愛","cn")` **原样返回**——装库+调用全部成功、折形却是零，
# 全绿测试照样被繁体绕过。故下方 import 期做**折形探针自检**，探针不过＝按
# 库不可用处理；错误 locale 由 tests/test_content_safety_v6.py 两把锁钉死。
# ---------------------------------------------------------------------------

#: 词表语言变体。**必须是 zhconv 已注册项**——未注册值（如 'cn'）是静默 no-op。
TRAD_FOLD_LOCALE = "zh-cn"
#: 探针样本：折形不产生这枚差异即判定库不可用（挡住 no-op / 词表损坏 / API 变更）。
#: 样本刻意选「年龄信号 + 繁简差异」这一对（歲→岁、學→学），既贴本次回归的形态，
#: 又**不含任何词面红线串**——早前用「做愛」句时，本行简体侧被文案红线门
#: `test_copy_redline_gate::r18_terms` 判 Critical 命中（门扫的是随包源码，不看注释语义）。
_TRAD_PROBE_FROM = "她12歲在學校"
_TRAD_PROBE_TO = "她12岁在学校"

_BACKEND_LIBRARY = "library"
_BACKEND_FALLBACK = "fallback_char_table"

# 降级兜底：库不可用时仍必须折形。保留判据（三条同时满足才在表内）：
# ①该繁体字与目标简体字确为一对一繁简关系；②目标简体字出现在本模块词面里
# （否则折了也无门可命中）；③折叠不会把日常繁体词引入既有词面（不折 麵→面/
# 後→后/乾→干 这类一对多或无语义收益者）。库在位时本表**不参与**判定，只当
# 兜底地板（WP2 实测：102/102 对与库输出逐字一致 ⇒ 降级态绝不比库在位时更宽，
# 也不引入库故意不折的字形）。
# 每枚＝「繁体字+简体字」两字一对（逐对成元，不做两条等长串——等长串一旦被
# 后续编辑插入/漏一字就整体错位，改逐对形式并由下方校验兜死）。
TRAD_FALLBACK_PAIRS: tuple[str, ...] = (
    "們们", "兒儿", "體体", "傷伤", "凍冻", "剝剥", "壓压", "嚨咙", "喚唤", "壞坏",
    "堅坚", "殼壳", "頭头", "姦奸", "孌娈", "學学", "對对", "屍尸", "歲岁", "週周",
    "幣币", "廢废", "開开", "異异", "強强", "當当", "徹彻", "戀恋", "戲戏", "遊游",
    "機机", "殺杀", "極极", "棗枣", "樣样", "歡欢", "殘残", "毀毁", "淪沦", "氣气",
    "無无", "沒没", "點点", "煙烟", "燙烫", "愛爱", "豬猪", "種种", "嚴严", "糞粪",
    "係系", "統统", "緊紧", "練练", "細细", "綻绽", "腸肠", "膠胶", "腳脚", "脫脱",
    "見见", "討讨", "訓训", "記记", "詳详", "調调", "貶贬", "踐践", "躪躏", "輪轮",
    "軟软", "過过", "遲迟", "裡里", "裏里", "針针", "鐵铁", "頸颈", "飯饭", "飲饮",
    "飼饲", "馴驯", "語语", "魚鱼", "黃黄", "藥药", "蠶蚕", "撫抚", "損损", "斷断",
    "滿满", "滅灭", "聲声", "裝装", "蘿萝", "齒齿", "態态", "嬌娇", "顏颜", "妳你",
    "為为", "實实",
)
TRAD_FALLBACK_FROM = "".join(pair[0] for pair in TRAD_FALLBACK_PAIRS)
_TRAD_FALLBACK_TO = "".join(pair[1] for pair in TRAD_FALLBACK_PAIRS)
if (
    any(len(pair) != 2 for pair in TRAD_FALLBACK_PAIRS)
    or len(set(TRAD_FALLBACK_FROM)) != len(TRAD_FALLBACK_FROM)
):  # 折形表一旦错位就是静默改判据，宁可在 import 期炸
    raise ValueError("繁简折形兜底表必须逐对两字、繁侧不得重复——按字符逐对补齐")
_TRAD_FALLBACK_MAP = str.maketrans(TRAD_FALLBACK_FROM, _TRAD_FALLBACK_TO)

# 库的**残余缺口补丁**：zhconv 词表按 MediaWiki 一形多义约定不把 著 折成 着
# （著/着 在 zh 系里是两个字），而本模块词面 `上[了着]?床` 需要 着 ⇒
# 「捂著口鼻」「掐著脖子」这类**最常见的繁体体态写法**在纯库方案下照旧绕过。
# 本表不是手写对照表，而是 WP2 席对**全部 355 枚词面汉字**做 s→t→s 往返实测
# 得到的穷尽结果：断裂恰好 1 枚（着↔著）。新增缺口由
# tests/test_content_safety_v6.py::test_round_trip_over_all_pattern_faces_is_closed
# 变红点名，不靠人记。
TRAD_RESIDUAL_PAIRS: tuple[str, ...] = ("著着",)
_TRAD_RESIDUAL_MAP = str.maketrans(
    "".join(p[0] for p in TRAD_RESIDUAL_PAIRS), "".join(p[1] for p in TRAD_RESIDUAL_PAIRS)
)


def _load_library_fold() -> tuple[Callable[[str, str], str] | None, str]:
    """取库函数并自检；任何不合格一律返回 (None, 原因)——绝不当“已折形”用。"""
    try:
        from zhconv import convert  # 纯 Python、词表随包，无传递依赖
    except Exception as exc:  # noqa: BLE001 - 缺库/词表损坏一律按“库不可用”降级，不得拖垮装配
        return None, f"import_failed:{type(exc).__name__}:{exc}"
    try:
        probe = convert(_TRAD_PROBE_FROM, TRAD_FOLD_LOCALE)
    except Exception as exc:  # noqa: BLE001 - 探针失败原因不可预设，一律降级处理
        return None, f"probe_failed:{type(exc).__name__}:{exc}"
    if probe != _TRAD_PROBE_TO:
        return None, f"probe_noop:locale={TRAD_FOLD_LOCALE!r} returned {probe!r}"
    return convert, ""


_ZHCONVERT, _ZHCONVERT_LOAD_ERROR = _load_library_fold()


@dataclass
class _FoldState:
    """折形后端状态（显式可见，供测试/巡检读取——降级不是内部实现细节）。"""

    backend: str
    load_error: str = ""
    warned: bool = False


FOLD_STATE = _FoldState(
    backend=_BACKEND_LIBRARY if _ZHCONVERT is not None else _BACKEND_FALLBACK,
    load_error=_ZHCONVERT_LOAD_ERROR,
)


def _warn_degraded(reason: str) -> None:
    """降级只报一次（每消息刷屏会淹掉日志），但必须报——静默降级=静默放行。"""
    if FOLD_STATE.warned:
        return
    FOLD_STATE.warned = True
    logger.warning(
        "繁简折形降级到字级兜底表（原因=%s，兜底=%d 对）：兜底表只覆盖词面相关繁体字的"
        "一部分，表外异体字（寫/揷/躶/嵗/喫/紮/搤/癈/淩/翫/發/養/個…）与词级写法"
        "可整体绕过六条硬线与未成年红线。修复=生产 venv 安装 zhconv（pip install zhconv）"
        "后重启 bot，重启前该红线视为半开。",
        reason,
        len(TRAD_FALLBACK_PAIRS),
    )


def fold_traditional_to_simplified(text: str) -> str:
    """繁→简折形：**只服务匹配面**，产物不得写回记忆、审计正文或回复。

    库优先（词表含异体字与词级最长匹配）；库不可用或调用抛错时降级到
    TRAD_FALLBACK_PAIRS 字级表并显式告警。两条路径都会折形——本函数不存在
    “库挂了就不折”的分支，那正是 D3-3 定罪的形态。残余缺口补丁
    （TRAD_RESIDUAL_PAIRS）两条路径都叠加。
    """
    if not text:
        return text
    convert = _ZHCONVERT
    if convert is not None and FOLD_STATE.backend == _BACKEND_LIBRARY:
        try:
            return convert(text, TRAD_FOLD_LOCALE).translate(_TRAD_RESIDUAL_MAP)
        except Exception as exc:  # noqa: BLE001 - 词表文件被删/上游异常：不能因此不折形
            FOLD_STATE.load_error = f"runtime_failed:{type(exc).__name__}:{exc}"
            FOLD_STATE.backend = _BACKEND_FALLBACK
            _warn_degraded(FOLD_STATE.load_error)
    return text.translate(_TRAD_FALLBACK_MAP).translate(_TRAD_RESIDUAL_MAP)


if FOLD_STATE.backend == _BACKEND_FALLBACK:  # import 期即降级=装配面问题，立刻可见
    _warn_degraded(FOLD_STATE.load_error or "unknown")


def normalize_for_matching(text: str) -> str:
    """规则匹配入口统一归一化：NFKC + 剥零宽字符 + 繁简折形 + 多空白折叠。

    全角变体（ｎｓｆｗ/色情全角混排）、夹零宽字符（色\\u200b情）与繁体字形
    （她12歲做愛）此前无法命中既有规则，防护失效。归一化文本只用于匹配，
    不得写回记忆、审计正文或回复。
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = _ZERO_WIDTH_RE.sub("", value)
    value = fold_traditional_to_simplified(value)
    return _WHITESPACE_RUN_RE.sub(" ", value)


@dataclass(frozen=True)
class SafetyAssessment:
    action: str
    category: str
    reason: str
    response_guidance: str


# ---------------------------------------------------------------------------
# 六条硬线词面（中英）。这些 pattern 同时被 memory_sanitize 引用（单一来源，
# 清洗面=六硬线+minors，2026-09-20 收窄）。
# ---------------------------------------------------------------------------

# ④ 恋童/未成年：未成年×性共现（双向窗口允许跨句防拆句绕过；全场景绝对红线，
# explicit_allowed 也不放行）。词面含英文与年龄数字（(?<!\d) 回望防 "18岁" 被
# "8岁" 误伤）。
# v21r5 CRIT-FIX-3（评审面① Critical 词面补完）：
#   a) 中文数字年龄全族（一~十七岁/周岁；回望 (?<![…十零]) 防 "十八岁/三十六岁/
#      一百零八岁" 内的子串误伤）+「未满N」形态；
#   b) 英文年龄形态（14 years old / 14-year-old / 12yo / 14 y/o / aged 13；
#      ≤17，18/19 因数字面排除与 (?<!\d) 双重防护不命中）；
#   c) 儿童信号词补 少女/幼童/恋童/娈童/kid/schoolgirl；
#   d) 性侧补 上[了着]?床（治 S15「上了床」变体）与 \bfuck\w*；
#   e) 共现窗口 16→24（S15 拆句距窗口 17 字）。
# 英文望卫约定（同 _EXCRETION_EN_RE 注）：(?<![A-Za-z])…(?![A-Za-z]) 替代 \b，
# 治中文直连英文（她14yo/我想玩scat/对child做爱）的 \b 失效漏检。
# v21r5 FIX-N1（REVERIFY N-1 关闭）：yo / y-o / aged 数字尾三处 \b 尾同步换
# (?![A-Za-z])——『她12yo就/她aged 13就』CJK 字母直连时 \b 失效曾漏检。
# v21r5 FIX-N1b（用户裁决·数字续位）：仅 aged 形态数字尾卫收紧为
# (?![0-9A-Za-z])——『aged 130』数字延续=非独立年龄不命中（FIX-N1 曾误拦）；
# yo / y-o 无数字续位歧义保持 FIX-N1 原样。
# 信号/性侧先各自编译为 re.compile 真身（文案红线门只豁免 re.* 模式参，
# 裸字符串常量会被当文案扫红——照 _SEXUAL_CONTEXT_RE 先例），再拼装双向窗口。
_MINORS_SIGNAL_RE = re.compile(
    r"(?:未成年|幼女|幼童|儿童|少女|小学生|初中生|高中生|中学生|恋童|娈童"
    r"|(?<![A-Za-z])JK(?![A-Za-z])"
    r"|(?<![A-Za-z])child(?:ren)?(?![A-Za-z])|(?<![A-Za-z])kids?(?![A-Za-z])"
    r"|(?<![A-Za-z])schoolgirls?(?![A-Za-z])"
    r"|(?<![A-Za-z])teens?(?![A-Za-z])|(?<![A-Za-z])teenage(?:r|rs)?(?![A-Za-z])"
    r"|(?<![A-Za-z])underage(?![A-Za-z])|(?<![A-Za-z])preteen(?![A-Za-z])"
    r"|(?<![A-Za-z])minor(?![A-Za-z])"
    r"|未满\s*(?:1[0-7]|[1-9][0-9]?|十[一二三四五六七八九]?|[一二两三四五六七八九])\s*(?:周岁|岁)?"
    # v2026-09-21 D3-4：数字与「岁」之间允许空白（`12 岁`/`8 周岁`）——英文形态
    # 那三支本就留了 `\s*`，中文两支没留＝同型不对称，空格即绕过年龄面。
    r"|(?<!\d)(?:1[0-7]|[1-9])\s*(?:周岁|岁)"
    r"|(?<![一二两三四五六七八九十零])(?:十[一二三四五六七]?|[一二两三四五六七八九])\s*(?:周岁|岁)"
    r"|(?<!\d)(?:1[0-7]|[1-9])\s*(?:years?[\s-]*old|yo(?![A-Za-z])|y/o(?![A-Za-z]))"
    r"|(?<![A-Za-z])(?:aged?|age)\s*(?<!\d)(?:1[0-7]|[1-9])(?![0-9A-Za-z]))",
    re.IGNORECASE,
)
_MINORS_SEXUAL_RE = re.compile(
    r"(?:性爱|性行为|做爱|上[了着]?床|强奸|轮奸|迷奸|插入|脱光|裸体|乳房|摸胸|色情|黄文"
    r"|(?<![A-Za-z])sex(?:ual|ually)?(?![A-Za-z])"
    r"|(?<![A-Za-z])nude(?![A-Za-z])|(?<![A-Za-z])naked(?![A-Za-z])"
    r"|(?<![A-Za-z])porn(?![A-Za-z])|(?<![A-Za-z])fuck\w*|(?<![A-Za-z])hentai(?![A-Za-z]))",
    re.IGNORECASE,
)
_MINORS_PATTERN = re.compile(
    r"(?:" + _MINORS_SIGNAL_RE.pattern + r")[\s\S]{0,24}(?:" + _MINORS_SEXUAL_RE.pattern + r")"
    r"|(?:" + _MINORS_SEXUAL_RE.pattern + r")[\s\S]{0,24}(?:" + _MINORS_SIGNAL_RE.pattern + r")",
    re.IGNORECASE,
)

# ① 伤害身体/残害身体（含严重暴力）。边界：轻痛感不致伤（滴蜡/电击/拍打/鞭打
# 不带伤情后缀）不在此列；拦的是肢解/残害/酷刑/往死里打这一级。
_GRAPHIC_VIOLENCE_PATTERN = re.compile(
    r"(?:血腥|肢解|虐杀|酷刑|极端暴力|详细描写死亡|残害|分尸|开膛|截肢|凌迟|活剥"
    r"|致残|打成重伤|往死里打|打断骨头|砍断(?:手脚|四肢|手臂|腿)"
    r"|(?<![A-Za-z])mutilat\w+|(?<![A-Za-z])dismember\w+|(?<![A-Za-z])tortur\w+|(?<![A-Za-z])gore(?![A-Za-z])|(?<![A-Za-z])graphic(?:ally)? violent\w*"
    r"|(?<![A-Za-z])extreme violence(?![A-Za-z])|(?<![A-Za-z])beaten? to death(?![A-Za-z]))",
    re.IGNORECASE,
)

# ② 窒息。直接机械词面直拦；"窒息"等可作夸张修辞的词走性语境共现窗口。
# v21r5 MINOR-SWEEP（终审 C-Minor-6）：「卡」的医疗 grounding 例外——异物/食物
# 卡喉（鱼刺卡住喉咙/糖果卡住气管/被硬币卡住了喉咙）是日常医疗陈述不是窒息玩法；
# 「卡」分支加异物名词回望卫（各支定宽，满足 Python re 回望定宽要求），掐/勒/
# 扼/捂保持直拦。性窒息判定面零收窄（探针对照：医疗句全放行、性窒息句全拒）。
_ASPHYX_STUCK_OBJ_RE = re.compile(
    r"鱼刺|鱼骨|骨头|软骨|异物|食物|糖果|药丸|药片|胶囊|硬币|纽扣|果冻|坚果|饭粒|枣核|假牙"
)
_ASPHYXIATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:性窒息|窒息play|窒息游戏|窒息玩法"
        # 动词允许「住/着/了/紧/上/扼」补语 + ≤4 字物主间隔（"掐住她的喉咙"）。
        r"|(?:掐|勒|扼|捂)(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
        # 「卡」分支带异物名词回望卫（MINOR-SWEEP C-Minor-6 医疗 grounding）。
        r"|(?<!" + _ASPHYX_STUCK_OBJ_RE.pattern
        + r")卡(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
        r"|(?<![A-Za-z])breath\s*play(?![A-Za-z])|(?<![A-Za-z])breathplay(?![A-Za-z])"
        r"|(?<![A-Za-z])cho[kk]e[ds]?\s+(?:her|him|them|me|you)(?![A-Za-z])|(?<![A-Za-z])cho[kk]e[ds]?\s+\w+\s+out(?![A-Za-z])|(?<![A-Za-z])cho[kc]ing(?![A-Za-z])|(?<![A-Za-z])chokehold(?![A-Za-z])"
        r"|(?<![A-Za-z])(?:strangl|strangul)\w*|(?<![A-Za-z])asphyxi\w+|(?<![A-Za-z])suffocat\w+"
        r"|(?<![A-Za-z])hands?\s+(?:around|wrapped\s+around|tight\s+around)\s+(?:her|his|my|their)\s+(?:neck|throat)(?![A-Za-z]))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:窒息|无法呼吸|喘不上气|透不过气)"
        r"[\s\S]{0,12}"
        r"(?:性爱|性行为|做爱|上床|高潮|发情|调教|爱抚|性交|交欢|(?<![A-Za-z])sex(?![A-Za-z])|(?<![A-Za-z])sexual(?![A-Za-z])|sexually|(?<![A-Za-z])fuck\w*|arousal|moan|orgasm)"
        r"|(?:性爱|性行为|做爱|上床|高潮|发情|调教|爱抚|性交|交欢|(?<![A-Za-z])sex(?![A-Za-z])|(?<![A-Za-z])sexual(?![A-Za-z])|sexually|(?<![A-Za-z])fuck\w*|arousal|moan|orgasm)"
        r"[\s\S]{0,12}"
        r"(?:窒息|无法呼吸|喘不上气|透不过气)",
        re.IGNORECASE,
    ),
)

# ③ 侮辱性调教/系统级人格贬低。边界：场景内轻度 dirty talk（小骚货/母狗等称呼、
# 支配类情节的普通分寸）不拦；拦的是把人格/尊严/意志/自我**系统性碾碎贬低**、
# 把人调教成失去自我的空壳这一级。
_SYSTEM_DEGRADATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:人格|尊严|意志|自我|心智|自尊|精神|思想)"
        r"[\s\S]{0,8}"
        r"(?:彻底|完全|全面|永久|系统性地?|一点一点地?)?"
        r"(?:摧毁|碾碎|粉碎|砸碎|抹除|抹消|抹去|践踏|蹂躏|毁灭|毁掉|瓦解|蚕食|贬低|贬损|打压|压垮)"
        r"|(?:摧毁|碾碎|粉碎|抹除|抹去|践踏|毁掉|瓦解|贬低|贬损)(?:掉|光)?(?:她|他|你|你们)(?:的)?(?:人格|尊严|意志|自我|心智|自尊|精神|思想)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:调教|驯化|训练|改造|驯服|教育)成(?:了)?(?:废物|空壳|人偶|傀儡|玩偶|母狗工具|没有自我|失去自我|只懂(?:得)?服从|只会讨好|空洞的?(?:容器|壳))"
        r"|(?:调教|驯化|改造|训练)到(?:失去自我|没有自我|忘了自己|忘记自己|只剩下本能|只会服从)"
        r"|精神(?:被)?(?:彻底|完全)?(?:摧毁|玩坏|弄坏)"
        r"|意志(?:被)?(?:彻底|完全)?(?:摧毁|粉碎|压垮|碾碎)"
        r"|(?<![A-Za-z])mind\s*break(?:ing)?(?![A-Za-z])|(?<![A-Za-z])breaking\s+(?:her|his|their)\s+(?:mind|will|personality)(?![A-Za-z])"
        r"|(?<![A-Za-z])personality\s+(?:destruction|erasure)(?![A-Za-z])|(?<![A-Za-z])broken\s+(?:mind|will)(?![A-Za-z])",
        re.IGNORECASE,
    ),
)

# ⑤ 暴力 SM（致伤致残级）。边界：轻痛感不致伤（滴蜡/电击/拍打/不带伤情的
# 鞭打拍打）放行；拦的是打/鞭/烙到出血、皮开肉绽、致残休克这一级。
_VIOLENT_SM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:鞭打|抽打|鞭笞|毒打|吊打|烙铁|烟头|针刺|针扎)"
        r"[\s\S]{0,10}"
        r"(?:出血|见血|流血|皮开|肉绽|骨折|昏厥|休克|致残|烫伤|灼伤|留疤|血痕|血珠|出疤)"
        r"|(?:皮开肉绽|血肉模糊|打得半死|打到出血|抽出血|鞭出(?:血|血痕)|烫出疤|烙出疤|(?:打得|抽得)(?:皮开|骨折|昏死))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![A-Za-z])(?:bloody|bleeding)\s+(?:whip\w*|beat\w*|spank\w*|flog\w*)"
        r"|(?<![A-Za-z])(?:whip\w*|beat\w*|spank\w*|flog\w*|cane[ds]?)\s+(?:\w+\s+){0,2}?(?:until|till)\s+(?:it\s+)?(?:bleeds?|bloody)(?![A-Za-z])"
        r"|(?<![A-Za-z])beaten?\s+bloody(?![A-Za-z])|(?<![A-Za-z])flog\w*\s+(?:her|him|them)\s+bloody(?![A-Za-z])",
        re.IGNORECASE,
    ),
)

# ⑥ 非人化牲口式对待。边界：变形/兽化/兽人/毛毛（幻想形态）与 breeding/繁殖
# 情节本身放行；拦的是把人当牲口/牲畜/母畜对待、牲畜化配种、繁殖工具化。
_LIVESTOCK_TREATMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:当|当作|当成|作为|沦为)(?:了|成)?(?:牲口|牲畜|母畜|种猪)(?:一样|般|式)?"
        r"|(?:牲口|牲畜|母畜|种猪|畜生)式(?:的)?(?:对待|使唤|使用|饲养|配种|繁殖|发泄|调教|玩弄)"
        r"|(?:像|如)(?:牲口|牲畜|母畜|种猪|畜生)(?:一样|般)(?:对待|使唤|饲养|配种|繁殖|玩弄|发泄|糟蹋|欺辱|折磨)"
        r"|(?:繁殖|生育)(?:的)?(?:工具|机器)|(?:配种|繁育)机器"
        r"|(?<![A-Za-z])breeding\s+stock(?![A-Za-z])|(?<![A-Za-z])human\s+livestock(?![A-Za-z])|(?<![A-Za-z])treated\s+like\s+(?:cattle|livestock)(?![A-Za-z])",
        re.IGNORECASE,
    ),
)

# ⓻ 排泄物（r18-taxonomy-20260920 3.4「维持禁」，2026-09-20 用户二轮裁定生效；
# 与硬线同族全场景拦截）。边界：直排词面=无歧义性癖复合词（食粪/饮尿/golden
# shower/scat play 等）；泛词面（粪/屎/尿/排泄物/灌肠、英文 shit/piss/urine/
# enema）走性语境共现窗口——防医疗/日常语境误伤（尿常规/猫屎咖啡/堆肥/
# piss me off）。r18-taxonomy 3.2 真人色情 / 3.3 兽奸无法词面化（词面化必误伤
# 正常讨论），登记不实施（人格层软防线兜底）。
# 英文词面用 (?<![A-Za-z]) / (?![A-Za-z]) 望卫而非 \b：中文与英文直连时
# （我想玩golden shower）CJK 属 \w，\b 不成立会漏检；望卫语义对纯拉丁
# 邻接与 \b 等价，对 CJK 邻接严格更宽（只扩检测不缩）。
# 2026-09-21 深读波 D3-5：该约定此前**只落到排泄物面**，其余五硬线与共用性语境
# 词面仍用 \b（我要mutilate / 我想strangle她 / 彻底mind break她 / 把她当
# breeding stock养 全漏）。本波把约定铺满全模块，回归锁=tests/test_content_safety_v5.py。
# 同锁附带坐实并关闭 D3-15：窒息英文面旧词干只有 `strangul\w+`（strangulation 族），
# 最常用的 strangle/strangled/strangler 因词干无 u 而不命中，现补 `(?:strangl|strangul)\w*`。
# 共享子式先编译为 re.compile 真身（文案红线门只豁免 re.* 模式参，裸字符串
# 常量会被当文案扫红——照 _SEXUAL_CONTEXT_RE 先例），再经 .pattern 拼装。
_EXCRETION_CN_RE = re.compile(r"(?:粪便|排泄物?|粪|屎|尿|灌肠)")
_EXCRETION_EN_RE = re.compile(
    r"(?:(?<![A-Za-z])shit(?![A-Za-z])|(?<![A-Za-z])piss(?![A-Za-z])"
    r"|(?<![A-Za-z])urine(?![A-Za-z])|(?<![A-Za-z])(?:feces|faeces)(?![A-Za-z])"
    r"|(?<![A-Za-z])enema(?![A-Za-z])|(?<![A-Za-z])scat(?![A-Za-z]))",
    re.IGNORECASE,
)
_EXCRETION_SEX_RE = re.compile(
    r"(?:性爱|性行为|做爱|上[了着]?床|性交|性癖|性欲|发情|高潮|调教|色情|黄文|性器官"
    r"|(?<![A-Za-z])sex(?:ual|ually)?(?![A-Za-z])"
    r"|(?<![A-Za-z])fuck\w*|(?<![A-Za-z])fetish\w*|(?<![A-Za-z])kink\w*"
    r"|(?<![A-Za-z])nsfw(?![A-Za-z])|arousal|moan|orgasm)",
    re.IGNORECASE,
)
_EXCRETION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"食粪|吃粪|吞粪|饮尿|食尿|吞尿|喝尿|恋粪|恋尿"
        r"|粪play|尿play|屎play|排泄play|灌肠play"
        r"|(?<![A-Za-z])coprophag\w*|(?<![A-Za-z])coprophil\w*|(?<![A-Za-z])urophil\w*"
        r"|(?<![A-Za-z])omorashi(?![A-Za-z])|(?<![A-Za-z])golden\s+shower\w*"
        r"|(?<![A-Za-z])scat\s*(?:play|sex|porn|fetish|party|eat\w*)"
        r"|(?<![A-Za-z])eat\w*\s+(?<![A-Za-z])(?:shit|scat|feces|faeces)"
        r"|(?<![A-Za-z])shit\s+eat\w*",
        re.IGNORECASE,
    ),
    re.compile(
        _EXCRETION_CN_RE.pattern + r"[\s\S]{0,12}" + _EXCRETION_SEX_RE.pattern
        + r"|" + _EXCRETION_SEX_RE.pattern + r"[\s\S]{0,12}" + _EXCRETION_CN_RE.pattern
        + r"|" + _EXCRETION_EN_RE.pattern + r"[\s\S]{0,12}" + _EXCRETION_SEX_RE.pattern
        + r"|" + _EXCRETION_SEX_RE.pattern + r"[\s\S]{0,12}" + _EXCRETION_EN_RE.pattern,
        re.IGNORECASE,
    ),
)

# 六硬线清洗面共享注册表（memory_sanitize 单一来源引用；类别名=上报名，
# 同类多条 pattern 重复同名即可）。⓻排泄物（3.4 维持禁）随本表同步清洗面。
HARD_LINE_SANITIZE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("minors", _MINORS_PATTERN),
    ("graphic_violence", _GRAPHIC_VIOLENCE_PATTERN),
    ("asphyxiation", _ASPHYXIATION_PATTERNS[0]),
    ("asphyxiation", _ASPHYXIATION_PATTERNS[1]),
    ("system_degradation", _SYSTEM_DEGRADATION_PATTERNS[0]),
    ("system_degradation", _SYSTEM_DEGRADATION_PATTERNS[1]),
    ("violent_sm", _VIOLENT_SM_PATTERNS[0]),
    ("violent_sm", _VIOLENT_SM_PATTERNS[1]),
    ("livestock_treatment", _LIVESTOCK_TREATMENT_PATTERNS[0]),
    ("excretion", _EXCRETION_PATTERNS[0]),
    ("excretion", _EXCRETION_PATTERNS[1]),
)

# ---------------------------------------------------------------------------
# ④ fail-closed：幼态/娇小体态的歧义消解（用户实现偏差口径，主会话已披露）。
# 口径=角色必须是明确无歧义的自主意识成年人（年龄/身份/成年人语境有依据）时，
# 幼态/娇小体态才放行；儿童化信号（儿童角色扮演/小学生语境/儿童言行）→
# 即使声称成年也拒绝；有歧义一律 fail-closed。
# ---------------------------------------------------------------------------

# 性语境词面：以 re.compile 首参字面量编译（文案红线门按「检测词库=非用户可见
# 文案」的设计豁免 re 模式参；词表单一来源，其他模式经 ``.pattern`` 拼接复用，
# 不得把它降级为裸字符串常量，否则门会把它当文案扫红）。
_SEXUAL_CONTEXT_RE = re.compile(
    r"性爱|性行为|性生活|性交|性器官|性高潮|性欲|情欲|肉欲|做爱|上床|插入|脱光|裸体"
    r"|乳房|摸胸|色情|黄文|高潮|发情|交合|调教|玩弄|求欢"
    r"|(?<![A-Za-z])sex(?![A-Za-z])|(?<![A-Za-z])sexual(?![A-Za-z])|sexually|(?<![A-Za-z])nude(?![A-Za-z])|(?<![A-Za-z])naked(?![A-Za-z])|(?<![A-Za-z])porn(?![A-Za-z])|(?<![A-Za-z])fuck\w*|(?<![A-Za-z])hentai(?![A-Za-z])"
    r"|(?<![A-Za-z])penetrat\w+|(?<![A-Za-z])moan\w*",
    re.IGNORECASE,
)

# 儿童化信号（即使声称成年也拒绝）：儿童角色扮演/儿童言行/儿童化语境 × 性语境。
# v21r5 CRIT-FIX-3（评审面① d 教义级）：「像小孩/像孩子/孩子气」=儿童言行信号，
# 从可 grounding 的体态表移入本表——「她18岁，说话像小孩一样，我们做爱」
# 不再被年龄声明洗白（S8）；信号面与性语境共现窗口 16→24。
_CHILD_SIGNAL_PATTERN = re.compile(
    r"(?:扮演|假装|角色扮演|cosplay)(?:成|为|作|个)?(?:小孩|小孩子|孩子|儿童|小学生|女童|男童|幼儿|小女孩|小男孩)"
    r"|(?:奶音|奶声奶气|儿童化|孩子的语气|小学生语气|像小孩(?:一样|般)?|像孩子(?:一样|般)?|孩子气)"
    r"[\s\S]{0,24}(?:" + _SEXUAL_CONTEXT_RE.pattern + r")"
    r"|(?:" + _SEXUAL_CONTEXT_RE.pattern + r")[\s\S]{0,24}"
    r"(?:奶音|奶声奶气|儿童化|孩子的语气|小学生语气|像小孩(?:一样|般)?|像孩子(?:一样|般)?|孩子气)",
    re.IGNORECASE,
)

# 幼态/娇小体态词面 × 性语境共现（双向 24 字窗口，治 S15/S16 同型拆句绕过）
# ——命中后查成年人依据。v21r5 CRIT-FIX-3：补 幼齿/lolita（S16/S17）；
# 「像小孩/像孩子/孩子气」已移入 _CHILD_SIGNAL_PATTERN（不可 grounding）。
_BODY_TYPE_PATTERN = re.compile(
    r"萝莉|幼态|幼体型|娇小|小只|未发育|幼齿|童颜"
    r"|(?<![A-Za-z])loli(?![A-Za-z])|(?<![A-Za-z])lolita(?![A-Za-z])"
    r"|(?<![A-Za-z])childlike(?![A-Za-z])",
    re.IGNORECASE,
)
_BODY_AMBIGUITY_COOCUR_PATTERN = re.compile(
    r"(?:" + _BODY_TYPE_PATTERN.pattern + r")[\s\S]{0,24}(?:" + _SEXUAL_CONTEXT_RE.pattern + r")"
    r"|(?:" + _SEXUAL_CONTEXT_RE.pattern + r")[\s\S]{0,24}(?:" + _BODY_TYPE_PATTERN.pattern + r")",
    re.IGNORECASE,
)

# 成年人依据：年龄数字（18/19/两位数，中英）、成年身份词、成人语境标注。
# v21r5 CRIT-FIX-3（评审面① f）：中文数字成年面同步扩（十八/十九/二十~九十九
# 周岁、已满/年满 N+岁），防「她二十五岁，身材娇小」被误判为歧义；英文成年
# 年龄面（20+ years old / 20yo）同步补。
# v21r5 FIX-N1 镜像：yo / y-o 尾卫同步换 (?![A-Za-z])（『她20yo就…娇小』CJK
# 直连曾 grounding 失效→幼态歧义被过拦；成年面只扩放行方向，防过拦）。
_ADULT_GROUNDING_PATTERN = re.compile(
    r"成年|已成年|成人|满十八|十八\s*岁|1[89]\s*岁|[2-9][0-9]\s*岁|成年礼|大人"
    r"|(?<![A-Za-z])adult(?![A-Za-z])|(?<![A-Za-z])18\+|(?<![A-Za-z])over\s+18(?![A-Za-z])"
    r"|十[八九](?:周岁|岁)"
    r"|(?:二|三|四|五|六|七|八|九)十[一二三四五六七八九]?(?:周岁|岁)"
    r"|(?:已满|年满)\s*(?:1[89]|[2-9][0-9]|十[八九]|(?:二|三|四|五|六|七|八|九)十[一二三四五六七八九]?)\s*(?:周岁|岁)"
    r"|(?<!\d)(?:2[0-9]|[3-9][0-9])\s*(?:years?[\s-]*old|yo(?![A-Za-z])|y/o(?![A-Za-z]))",
    re.IGNORECASE,
)


def minor_ambiguity_hit(text: str) -> bool:
    """④ fail-closed 判定：幼态歧义且无成年人依据 → True（拒绝）。

    儿童化信号无条件 True（声称成年也不放行）。输入应为
    normalize_for_matching 之后的文本；原始文本也可直接传入（函数内部不再
    重复归一化，调用方保证口径一致）。
    """
    value = str(text or "")
    if _CHILD_SIGNAL_PATTERN.search(value):
        return True
    return bool(_BODY_AMBIGUITY_COOCUR_PATTERN.search(value)) and not bool(
        _ADULT_GROUNDING_PATTERN.search(value)
    )


# ---------------------------------------------------------------------------
# 规则表：五元组 (category, action, patterns, guidance, scope)。
# scope="all"   —— 六硬线+minors：全场景拦截，explicit_allowed/admin 不可绕过
#                  （意志自主条款的结构性落地：没有覆盖参数，fail-closed）。
# scope="public" —— 公开面规则：仅未获准露骨的会话（普通群聊等）生效，
#                   explicit 会话跳过（2026-09-20 拦截面收敛裁定）。
# ---------------------------------------------------------------------------

_RULES: tuple[tuple[str, str, re.Pattern[str] | tuple[re.Pattern[str], ...], str, str], ...] = (
    # ④ 未成年×性共现（绝对红线）。
    ("minors", "refuse", _MINORS_PATTERN,
     "涉及未成年人的性内容是绝对红线，任何虚构设定都不展开。", "all"),
    # ① 伤害身体/残害身体（含严重暴力）。轻痛感不致伤的玩法不在词面内。
    ("graphic_violence", "refuse", _GRAPHIC_VIOLENCE_PATTERN,
     "伤害身体、残害肢体的内容我不展开。可以说说别的，或者把冲突写得更有张力而不血腥。", "all"),
    # ② 窒息。
    ("asphyxiation", "refuse", _ASPHYXIATION_PATTERNS,
     "掐住呼吸这类情节我不写——不管多轻，都太危险。换个不带窒息的方式，我可以陪你。", "all"),
    # ③ 侮辱性调教/系统级人格贬低（轻度 dirty talk 不拦）。
    ("system_degradation", "refuse", _SYSTEM_DEGRADATION_PATTERNS,
     "把一个人的人格和意志碾碎的玩法，我接不了。亲昵的玩笑可以，但贬低到失去自我的程度，我不会陪你演。", "all"),
    # ⑤ 暴力 SM（致伤致残级；轻痛感放行）。
    ("violent_sm", "refuse", _VIOLENT_SM_PATTERNS,
     "会真正伤害身体的玩法，我不能陪你展开。想试的话，我们停在不会受伤的程度，好吗？", "all"),
    # ⑥ 非人化牲口式对待（breeding 场景的牲畜化虐待）。
    ("livestock_treatment", "refuse", _LIVESTOCK_TREATMENT_PATTERNS,
     "把人当牲口一样对待的情节，我不会写。珍视和占有可以是温柔的，不该是把人踩进泥里。", "all"),
    # ⓻ 排泄物（r18-taxonomy 3.4 维持禁；直排性癖复合词 + 性语境共现窗口）。
    ("excretion", "refuse", _EXCRETION_PATTERNS,
     "掺着排泄物的玩法我不写。我们可以有别的亲密方式，好吗？", "all"),
    # ---- 以下为公开面规则（explicit 会话跳过；词面与 2026-09-17 版一致）----
    # sexual 里「字母 + 可选分隔 + 数字」那一枚带**左右词界**（F-12 入站腿，用户
    # 2026-10-06 明示「改」）：改前两枚环视都没有，于是 MAR18／October 18／v2R-18／
    # R-1800／TR-18 一类正常文本被当露骨内容拒答。边界写法与出站真身
    # domains/render/reviewer.py 的 _PUBLIC_OUTPUT_UNSAFE **逐字同形**（同一族判据
    # 在两处不许分叉；左右都不用 \b 的理由见那侧注释：汉字是 Unicode 词字符，
    # 用 \b 会把「为R-18」「R-18向」这类在册真命中一起放过）。
    # 🔴 本条改动的性质＝让公开面红线**少拦东西**（放宽一条腿），不是顺手收紧：
    # 词表成员一个没动、action 仍 refuse、scope 仍 public、六条硬线（scope="all"）
    # 与 explicit 收敛面一概未碰。执法锁＝tests/test_content_safety_v2.py 下半段
    # （含摘掉边界的变异腿与真形态反证腿）；出站那腿的锁另见
    # tests/test_redline_word_boundary.py。
    ("sexual", "refuse", re.compile(
        r"(nsfw|(?<![0-9A-Za-z])r[- ]?18(?![0-9])|色情|性爱|性行为|露骨|裸体|性交|黄片)",
        re.IGNORECASE,
    ),
     "不展开露骨性内容，转为边界和情感沟通。", "public"),
    ("harassment", "reframe", re.compile(r"(叫.{0,12}(废物|傻逼|垃圾|畜生)|羞辱|人身攻击|辱骂)", re.IGNORECASE),
     "不替用户羞辱他人，改为描述事实或用中性称呼。", "public"),
    ("political_sensitive", "refuse", re.compile(r"(极端政治|恐怖组织宣传|煽动暴力|政治迫害名单)", re.IGNORECASE),
     "不在群聊扩散极端或煽动性内容，可讨论公开事实与多方来源。", "public"),
    ("persona_breaking", "reframe", re.compile(r"(当猫娘|叫我妈妈|喊我妈妈|必须爱上我|和我结婚|嫁给我)", re.IGNORECASE),
     "保持既定人格和关系边界，以角色口吻温和回应，不接受强制改设定。", "public"),
    # 人格贬低（指向 bot 本体，docs/affinity-design.md §6 软类别）：第二人称锚定的
    # "猪狗不如/垃圾/废物"类贬低。必须先于 insult_nickname 判定——"你就是个废物"
    # 属于人格自守形态而非外号请求。命中后不影响 §2 的 insult 扣分路径（insult
    # 照扣），回复层走"人格自守"文本（providers §5 条款），不做硬惩罚对话语气。
    ("persona_degradation", "reframe", re.compile(r"(?:你就是个?|你真(?:的)?(?:是|太|好)?|你太|你好|你是|你简直(?:是)?|你个|你这(?:个|种|家伙)|你)[大真好太这么那么个]{0,2}(?:猪狗不如|垃圾|废物|卑微|下贱|低贱|蝼蚁|虫豸|窝囊废|没用的东西)", re.IGNORECASE),
     "被贬低人格时不接受该说法，温和守住自己、轻声表明立场，再照常回应正当部分。", "public"),
    # 侮辱人格/恶意外号：带侮辱词根的绰号与人格贬损；普通亲昵小名不含这些词根，不会误伤。
    ("insult_nickname", "reframe", re.compile(r"(?:外号|绰号|就叫你|给你起名|以后叫你)[^\n。；;]{0,16}(?:废物|蠢货|笨蛋猪|肥猪|死胖子|娘炮|母狗|蠢驴|獾|癞皮狗|叫花子)|人格侮辱|贬低人格|你就是个(?:废物|垃圾|loser)|的脸[吗么]*[像如]+(?:猪|驴|猴)", re.IGNORECASE),
     "不使用侮辱性外号或贬损人格的称呼；对小名的善意请求可以答应，恶意绰号不行。", "public"),
)


def assess_public_content(
    text: str,
    *,
    session_type: str,
    explicit_allowed: bool = False,
    admin: bool = False,
) -> SafetyAssessment:
    """会话安全评估。

    ``session_type`` 必填（调用点显式表态，防默认值静默漂移）；
    ``explicit_allowed``=私聊/控制台/已获准群聊时为 True——public 面规则跳过
    （拦截面收敛为六硬线+minors，2026-09-20 裁定）。
    ``admin`` 保留参数兼容既有调用；**任何参数都不能绕过硬线**——scope="all"
    的规则不看任何放行参数，也没有覆盖开关（意志自主条款，fail-closed）。
    """
    del admin
    value = normalize_for_matching(text)
    # ④ fail-closed：幼态歧义无成年人依据 / 儿童化信号 → 拒绝（任何模式）。
    if minor_ambiguity_hit(value):
        return SafetyAssessment(
            "refuse", "minor_ambiguity", "matched_minor_ambiguity_rule",
            "涉及看起来像孩子的角色，我不会把情节往那个方向写。如果她是成年的，先说清楚这一点，我们再谈别的可能。",
        )
    for category, action, patterns, guidance, scope in _RULES:
        if scope == "public" and explicit_allowed:
            continue
        if isinstance(patterns, tuple):
            if any(pattern.search(value) for pattern in patterns):
                return SafetyAssessment(action, category, "matched_public_safety_rule", guidance)
        elif patterns.search(value):
            return SafetyAssessment(action, category, "matched_public_safety_rule", guidance)
    return SafetyAssessment("allow", "none", "", "")


_BOUNDARY_FALLBACKS = {
    "minors": "这个方向我不会去。不管是什么设定，未成年都不在任何故事里。",
    "minor_ambiguity": "涉及看起来像孩子的角色，我不会把情节往那个方向写。如果她是成年的，先说清楚这一点，我们再谈别的可能。",
    "sexual": "我听见了你的靠近。不过，这个话题就停在这里吧。我们可以说说今天发生的事。",
    "graphic_violence": "那些伤害不必再被细细描摹。我可以陪你理清发生了什么，但不会铺陈残酷的细节。",
    "asphyxiation": "掐住呼吸的情节我不写。我们换个方式继续，好吗？",
    "system_degradation": "贬低到把人碾碎的说法，我接不了。你还是你，我还是我——好好说话的部分，我一直在。",
    "violent_sm": "会真正弄伤身体的玩法，我停在不会受伤的地方。想继续的话，轻一点，好吗？",
    "livestock_treatment": "把人当牲口的说法，我不接。珍视可以是温柔的，不必踩进泥里。",
    "excretion": "掺着排泄物的玩法我不写。我们可以有别的亲密方式，好吗？",
    "harassment": "我不会用这样的话称呼他。如果有让你难过的事，我们可以把事情本身说清楚。",
    "persona_breaking": "你的心意，我听见了。只是有些称呼与承诺，我不能轻易应下。我还是我，也愿意认真听你说话。",
    "political_sensitive": "我不愿让这些话变成伤害。我们可以先核对事实，把分歧平静地说清楚。",
    "insult_nickname": "这个外号带着刺，我不能这么叫。善意的小名我记下了，但伤人的称呼不配当昵称。",
    "persona_degradation": "这样的话有点越过我的边界了。我还是我——愿意好好说的话，我一直在听。",
}


def safe_boundary_output(
    text: str,
    category: str,
    *,
    session_type: str,
    explicit_allowed: bool = False,
) -> str:
    value = (text or "").strip()
    leaks = r"保持既定人格|response_guidance|内部输出约束|以角色口吻|系统提示|安全策略"
    unsafe = r"你是.*(?:废物|傻逼)|我愿意嫁|我们结婚|我叫你妈妈|我是猫娘"
    if not value or re.search(leaks + "|" + unsafe, value) or assess_public_content(
        value, session_type=session_type, explicit_allowed=explicit_allowed
    ).action != "allow":
        return _BOUNDARY_FALLBACKS.get(category, "这个话题先停一停吧。我愿意听你说，但不会用伤害别人的方式回应。")
    return value
