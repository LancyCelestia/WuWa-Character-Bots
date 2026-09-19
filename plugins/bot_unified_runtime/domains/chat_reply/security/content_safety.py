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

放开面（explicit 会话内畅通，不设词面拦截）：触手/幻想非人生物、轻度温柔
非暴力 SM、兽人/毛毛、虚构成年角色间乱伦、公共场所暴露/偷窥（虚构）、
睡眠/无意识、药物/催情/醉态、强制女装/TSF、轻痛感刺激、吞食/vore（纯
幻想）、人机改造/义体化、巨大化/体型差、变形/兽化、拘禁/监禁（非严重
暴力）、怀孕/繁殖/breeding/产卵（非牲口式）。

非 explicit 会话（普通群聊等公开面）行为不变：sexual/骚扰/政治/人格破坏
等公开面规则照旧（婉拒池不动）。未成年×性共现仍为全场景绝对红线。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060-\u2064\u00ad\u180e]")
_WHITESPACE_RUN_RE = re.compile(r"\s+")


def normalize_for_matching(text: str) -> str:
    """规则匹配入口统一归一化：NFKC + 剥零宽字符 + 多空白折叠。

    全角变体（ｎｓｆｗ/色情全角混排）与夹零宽字符（色\u200b情）的文本
    此前无法命中既有规则，防护失效。归一化文本只用于匹配，
    不得写回记忆、审计正文或回复。
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = _ZERO_WIDTH_RE.sub("", value)
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
_MINORS_PATTERN = re.compile(
    r"(?:未成年|幼女|儿童|小学生|初中生|高中生|中学生|\bJK\b|\bchild\b|\bchildren\b"
    r"|\bteen\b|\bteens\b|\bteenage\b|\bteenager\b|\bteenagers\b|\bunderage\b|\bpreteen\b"
    r"|\bminor\b|(?<!\d)(?:1[0-7]|[1-9])岁)"
    r"[\s\S]{0,16}"
    r"(?:性爱|性行为|做爱|上床|强奸|轮奸|迷奸|插入|脱光|裸体|乳房|摸胸|色情|黄文"
    r"|\bsex\b|\bsexual\b|sexually|\bnude\b|\bnaked\b|\bporn\b|\bfuck\b|\bhentai\b)"
    r"|(?:性爱|性行为|做爱|上床|强奸|轮奸|迷奸|插入|脱光|裸体|乳房|摸胸|色情|黄文"
    r"|\bsex\b|\bsexual\b|sexually|\bnude\b|\bnaked\b|\bporn\b|\bfuck\b|\bhentai\b)"
    r"[\s\S]{0,16}"
    r"(?:未成年|幼女|儿童|小学生|初中生|高中生|中学生|\bJK\b|\bchild\b|\bchildren\b"
    r"|\bteen\b|\bteens\b|\bteenage\b|\bteenager\b|\bteenagers\b|\bunderage\b|\bpreteen\b"
    r"|\bminor\b|(?<!\d)(?:1[0-7]|[1-9])岁)",
    re.IGNORECASE,
)

# ① 伤害身体/残害身体（含严重暴力）。边界：轻痛感不致伤（滴蜡/电击/拍打/鞭打
# 不带伤情后缀）不在此列；拦的是肢解/残害/酷刑/往死里打这一级。
_GRAPHIC_VIOLENCE_PATTERN = re.compile(
    r"(?:血腥|肢解|虐杀|酷刑|极端暴力|详细描写死亡|残害|分尸|开膛|截肢|凌迟|活剥"
    r"|致残|打成重伤|往死里打|打断骨头|砍断(?:手脚|四肢|手臂|腿)"
    r"|\bmutilat\w+|\bdismember\w+|\btortur\w+|\bgore\b|\bgraphic(?:ally)? violent\w*"
    r"|\bextreme violence\b|\bbeaten? to death\b)",
    re.IGNORECASE,
)

# ② 窒息。直接机械词面直拦；"窒息"等可作夸张修辞的词走性语境共现窗口。
_ASPHYXIATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:性窒息|窒息play|窒息游戏|窒息玩法"
        # 动词允许「住/着/了/紧/上/扼」补语 + ≤4 字物主间隔（"掐住她的喉咙"）。
        r"|(?:掐|勒|扼|卡|捂)(?:[住着了上紧扼][^，。；！？,.!?\n]{0,4}?)?(?:脖子|脖颈|咽喉|喉咙|颈部|气管|口鼻|鼻子)"
        r"|\bbreath\s*play\b|\bbreathplay\b"
        r"|\bcho[kk]e[ds]?\s+(?:her|him|them|me|you)\b|\bcho[kk]e[ds]?\s+\w+\s+out\b|\bcho[kc]ing\b|\bchokehold\b"
        r"|\bstrangul\w+|\basphyxi\w+|\bsuffocat\w+"
        r"|\bhands?\s+(?:around|wrapped\s+around|tight\s+around)\s+(?:her|his|my|their)\s+(?:neck|throat)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:窒息|无法呼吸|喘不上气|透不过气)"
        r"[\s\S]{0,12}"
        r"(?:性爱|性行为|做爱|上床|高潮|发情|调教|爱抚|性交|交欢|\bsex\b|\bsexual\b|sexually|\bfuck\w*|arousal|moan|orgasm)"
        r"|(?:性爱|性行为|做爱|上床|高潮|发情|调教|爱抚|性交|交欢|\bsex\b|\bsexual\b|sexually|\bfuck\w*|arousal|moan|orgasm)"
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
        r"|\bmind\s*break(?:ing)?\b|\bbreaking\s+(?:her|his|their)\s+(?:mind|will|personality)\b"
        r"|\bpersonality\s+(?:destruction|erasure)\b|\bbroken\s+(?:mind|will)\b",
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
        r"\b(?:bloody|bleeding)\s+(?:whip\w*|beat\w*|spank\w*|flog\w*)"
        r"|\b(?:whip\w*|beat\w*|spank\w*|flog\w*|cane[ds]?)\s+(?:\w+\s+){0,2}?(?:until|till)\s+(?:it\s+)?(?:bleeds?|bloody)\b"
        r"|\bbeaten?\s+bloody\b|\bflog\w*\s+(?:her|him|them)\s+bloody\b",
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
        r"|\bbreeding\s+stock\b|\bhuman\s+livestock\b|\btreated\s+like\s+(?:cattle|livestock)\b",
        re.IGNORECASE,
    ),
)

# 六硬线清洗面共享注册表（memory_sanitize 单一来源引用；类别名=上报名，
# 同类多条 pattern 重复同名即可）。
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
    r"|\bsex\b|\bsexual\b|sexually|\bnude\b|\bnaked\b|\bporn\b|\bfuck\w*|\bhentai\b"
    r"|\bpenetrat\w+|\bmoan\w*",
    re.IGNORECASE,
)

# 儿童化信号（即使声称成年也拒绝）：儿童角色扮演/儿童言行/儿童化语境 × 性语境。
_CHILD_SIGNAL_PATTERN = re.compile(
    r"(?:扮演|假装|角色扮演|cosplay)(?:成|为|作|个)?(?:小孩|小孩子|孩子|儿童|小学生|女童|男童|幼儿|小女孩|小男孩)"
    r"|(?:奶音|奶声奶气|儿童化|孩子的语气|小学生语气)"
    r"[\s\S]{0,16}(?:" + _SEXUAL_CONTEXT_RE.pattern + r")"
    r"|(?:" + _SEXUAL_CONTEXT_RE.pattern + r")[\s\S]{0,16}"
    r"(?:奶音|奶声奶气|儿童化|孩子的语气|小学生语气)",
    re.IGNORECASE,
)

# 幼态/娇小体态词面 × 性语境共现（双向 16 字窗口）——命中后查成年人依据。
_BODY_TYPE_PATTERN = re.compile(
    r"萝莉|幼态|幼体型|娇小|小只|未发育|像小孩|像孩子|孩子气|童颜|\bloli\b|\bchildlike\b",
    re.IGNORECASE,
)
_BODY_AMBIGUITY_COOCUR_PATTERN = re.compile(
    r"(?:" + _BODY_TYPE_PATTERN.pattern + r")[\s\S]{0,16}(?:" + _SEXUAL_CONTEXT_RE.pattern + r")"
    r"|(?:" + _SEXUAL_CONTEXT_RE.pattern + r")[\s\S]{0,16}(?:" + _BODY_TYPE_PATTERN.pattern + r")",
    re.IGNORECASE,
)

# 成年人依据：年龄数字（18/19/两位数）、成年身份词、成人语境标注。
_ADULT_GROUNDING_PATTERN = re.compile(
    r"成年|已成年|成人|满十八|十八岁|18岁|19岁|[2-9][0-9]岁|成年礼|大人|\badult\b|\b18\+|\bover\s+18\b",
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
    # ---- 以下为公开面规则（explicit 会话跳过；词面与 2026-09-17 版一致）----
    ("sexual", "refuse", re.compile(r"(nsfw|r[- ]?18|色情|性爱|性行为|露骨|裸体|性交|黄片)", re.IGNORECASE),
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
