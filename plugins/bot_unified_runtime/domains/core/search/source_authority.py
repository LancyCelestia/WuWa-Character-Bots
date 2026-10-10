"""检索结果的来源权威分级（「最新、最权威来源」这条要求的判据真身）。

为什么单开一件：``web_search._domain_priority`` 此前只认识百科域名，科技/时政/
新闻/金融四类题里一手源（监管机构、交易所、通讯社、厂商官方发布）与内容农场
同权，模型先读到的就是抓取顺序里碰巧靠前的那一条。本件只回答「哪个域名更该
先看」，**不参与相关性判定**——相关性地板仍唯一住在
``web_search._filter_relevant``，权威永远不许把不相关的结果抬进块里。

为什么不按话题各建一棵词表：话题判定的真身已在
``domains/chat_reply/runtime/question_intent.py``（时效四域）与本包
``search_intent.py``（二次元域）。在 core 层再抄一份正则＝第二真身，两份必然
漂移。所以这里只做**跨话题成立**的通用阶梯（一手源在任何话题下都是一手源），
二次元/百科话题额外把百科域抬到 tier 1——抬的依据直接调用既有谓词
``detect_acg_intent``，不新建词表。

2026-10-11 出口标源（SRC=）：本件同时是「这条内容从谁的嘴里出来」的唯一判据
真身（主人裁定＝高管个人号**进正文，但只有官方消息才进，个人互动不得进**）。
挂在件上而不是挂在某个渲染口上的理由：档位（``authority_tier``）已经回答「哪个
域名更该先看」，SRC 回答的是同一条链上的下一问「这条能不能当口径」，两把尺同族、
同处判据层；渲染侧（``news_feeds`` / ``capabilities/news`` / ``plain_text``）只
**用**这两把尺，不再各自判一次。🔴 名册数据（主体白名单行、人-司绑定行）一律
不住本件：那是数据，走 Runtime 侧数据面（``news_feeds.load_account_roster``），
本件只定义行的**形状**与判据。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime

from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)

__all__ = [
    "ACCOUNT_KINDS",
    "ACCOUNT_KIND_OFFICE",
    "ACCOUNT_KIND_ORG",
    "ACCOUNT_KIND_PERSON",
    "BINDING_SOURCES",
    "P0_MIN_POST_COUNT",
    "SRC_EXEC_ON_NAMEROOM",
    "SRC_EXEC_PERSONAL",
    "SRC_LABELS",
    "SRC_LINE_RE",
    "SRC_ORG_PRIMARY",
    "SRC_UNVERIFIED",
    "TIER_AGGREGATOR",
    "TIER_FIRST_PARTY",
    "TIER_UNKNOWN",
    "AccountRow",
    "PostSignals",
    "authority_tier",
    "body_admits_src",
    "build_exec_signature",
    "is_exec_signature",
    "is_src_label",
    "is_valid_src_field",
    "judge_account_src",
    "normalize_domain",
    "order_key",
    "p0_attribution_holds",
    "p1_binding_holds",
    "p2_post_shape_holds",
    "p3_official_form_hits",
    "p4_personal_interaction_hits",
    "sanitize_src_markers",
    "src_marker",
]

# 数值越小越该先看。TIER_UNKNOWN 不是低质，只是「本件不认识」——绝不因不认识而丢弃。
TIER_FIRST_PARTY = 0  # 官方/监管/交易所/通讯社/厂商一手发布
TIER_MAJOR_MEDIA = 1  # 主流权威媒体（有采编与更正机制）
TIER_VERTICAL = 2  # 垂类可信（垂直数据站、官方社区、番剧资料站）
TIER_NEUTRAL = 3  # 通用百科（旧实现唯一认识的一档）
TIER_UNKNOWN = 4  # 未登记域名
TIER_AGGREGATOR = 5  # 明确的转载/聚合形态（不是垃圾，但不配占前排）

_FIRST_PARTY: tuple[str, ...] = (
    # 中国政务与监管
    "gov.cn",
    "xinhua.cn",
    "xinhuanet.com",
    "news.cn",
    "people.com.cn",
    "cctv.com",
    "chinacourt.org",
    # 金融基础设施与监管
    "sse.com.cn",
    "szse.cn",
    "cffex.com.cn",
    "shfe.com.cn",
    "dce.com.cn",
    "czce.com.cn",
    "chinabond.com.cn",
    "cninfo.com.cn",
    "sec.gov",
    "federalreserve.gov",
    "ecb.europa.eu",
    "imf.org",
    "worldbank.org",
    "opec.org",
    "eia.gov",
    # 国际通讯社
    "reuters.com",
    "apnews.com",
    "afp.com",
    # 科技一手发布
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "blog.google",
    "microsoft.com",
    "apple.com",
    "nvidia.com",
    "intel.com",
    "amd.com",
    "kernel.org",
    "arxiv.org",
    "github.blog",
    "huggingface.co",
    # 二游官方站（版本/卡池/公告的真相只在这里）
    "mihoyo.com",
    "hoyoverse.com",
    "hypgis.com",
    "kurogames.com",
    "biligame.com",
)

_MAJOR_MEDIA: tuple[str, ...] = (
    "thepaper.cn",
    "chinanews.com.cn",
    "chinanews.com",
    "caixin.com",
    "yicai.com",
    "stcn.com",
    "21jingji.com",
    "nbd.com.cn",
    "bloomberg.com",
    "ftchinese.com",
    "ft.com",
    "wsj.com",
    "nytimes.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "theverge.com",
    "arstechnica.com",
    "techcrunch.com",
    "engadget.com",
    "jiqizhixin.com",
    "qbitai.com",
    "infoq.cn",
    "ithome.com",
    "nature.com",
    "newscientist.com",
    # 🔴 2026-10-08 三批快报接线的前置件（不是顺手加词）：``news_feeds.NEWS_SOURCES``
    # 的准入门只认「主域名在本表 ≥ TIER_MAJOR_MEDIA，或恰为 TIER_VERTICAL 且行内写死
    # 例外理由」，这四处都是她点名的**报社/通讯社**（有采编与更正机制）、二批席位出口
    # 实测有当日条目，缺登记就是「已接线但无准入依据」⇒ 红的是接线本身。排序面效果＝
    # 这几家从「不认识」（TIER_UNKNOWN，仍不丢弃）抬到与 NYT/WSJ/BBC 同档。
    "time.com",  # 时代（TIME）——news_feeds key=time
    "newsweek.com",  # 新闻周刊——key=newsweek
    "asahi.com",  # 朝日新闻——key=asahi
    "ukrinform.net",  # 乌克兰国家通讯社（英文站＝feed 主机）——key=ukrinform
)

_VERTICAL: tuple[str, ...] = (
    "eastmoney.com",
    "wallstreetcn.com",
    "cls.cn",
    "globaltimes.cn",
    "36kr.com",
    "sspai.com",
    "v2ex.com",
    "oschina.net",
    "bgm.tv",
    "bangumi.tv",
    "fandom.com",
    "kurobbs.com",
    "bilibili.com",
)

_NEUTRAL: tuple[str, ...] = (
    "moegirl.org.cn",
    "moegirl.icu",
    "wikipedia.org",
    "baike.baidu.com",
    "britannica.com",
)

# 明确的转载/聚合形态。**故意只登记少数几枚**：误降权（把权威站打成聚合）比漏
# 降权坏得多——前者让模型看不到一手源，后者只是维持现状。
_AGGREGATOR: tuple[str, ...] = (
    "baijiahao.baidu.com",
    "mbd.baidu.com",
    "360kuai.com",
    "ixigua.com",
    "toutiao.com",
    "sohu.com",
)

_TIERS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (TIER_FIRST_PARTY, _FIRST_PARTY),
    (TIER_MAJOR_MEDIA, _MAJOR_MEDIA),
    (TIER_VERTICAL, _VERTICAL),
    (TIER_NEUTRAL, _NEUTRAL),
    (TIER_AGGREGATOR, _AGGREGATOR),
)


def normalize_domain(value: str) -> str:
    """把 ``https://X:8080/p``、``X.``、大小写混写统一成可比较的裸域名。"""
    domain = (value or "").strip().lower()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    domain = domain.split("/", 1)[0].split("?", 1)[0]
    return domain.split(":", 1)[0].strip(".")


def _matches(domain: str, registered: str) -> bool:
    """整段相等或作为末段后缀命中。

    刻意不做任意子串匹配：一旦 ``fake-reuters.com`` 能被 ``reuters.com`` 命中，
    「抬升权威」就成了可抢注伪造的通道。
    """
    return domain == registered or domain.endswith("." + registered)


def authority_tier(source_domain: str, *, acg_topic: bool = False) -> int:
    """该来源域名的权威档（越小越该先看）；未登记一律 TIER_UNKNOWN，不丢弃。"""
    domain = normalize_domain(source_domain)
    if not domain:
        return TIER_UNKNOWN
    for tier, registered in _TIERS:
        if any(_matches(domain, item) for item in registered):
            # 百科域是 lore 题的正解来源，抬到与主流媒体同档；但不越过一手源。
            if acg_topic and tier == TIER_NEUTRAL:
                return TIER_MAJOR_MEDIA
            return tier
    return TIER_UNKNOWN


def order_key(source_domain: str, query: str = "") -> tuple[int, str]:
    """排序键，供 ``sorted`` 直接用；同档内按域名稳定排序，保证确定性可测。"""
    domain = normalize_domain(source_domain)
    return (
        authority_tier(domain, acg_topic=bool(detect_acg_intent(query or "").is_acg)),
        domain,
    )


# ==================== 出口标源（``SRC=``）：谁能当口径、谁只能进佐证 ====================
# 主人 2026-10-11 裁定＝高管个人号「**进正文，但只有官方消息才进，个人互动不得进**」。
# 判据形状＝名册席草案第三节：``进正文 ⇔ P0 ∧ P1 ∧ P2 ∧ P3 ∧ ¬P4``，每条必带一个
# ``SRC=`` 标，取不到标就降级。三条结构约束写死在本段（改任何一条都＝改判据，由她裁）：
#   ① **取值闭集**：``SRC`` 只有下面四枚合法值，自由文本一律回落 ``UNVERIFIED``（丢）；
#   ② **平台认证标永久不作证据**（D3：X 个体付费蓝标与机构官方标在 DOM 里同写
#      「认证账号」）——``AccountRow.verified_badge`` 只登记、任何谓词都不读它；
#   ③ **fail-closed**：判不出＝不进正文。本仓判出的最大噪声风险不是假账号，而是
#      「发的是真消息、只是不来自官方」的热心号，任何「内容像不像公告」的判据都
#      拦不住它，只能靠「主体白名单＋名录绑定行＋帖形」硬挡。
# 🔴 名册数据（账号行、人-司绑定行）不住本件：那是**数据**，走 Runtime 侧数据面
#    （真身读口＝``news_feeds.load_account_roster``）；本件只定义行的**形状**与判据，
#    所以既没有把任何一枚账号硬编进 .py，也没有第二份白名单。

#: 四枚合法取值（闭集；与判定行一一对应，多一枚少一枚都红）。
SRC_ORG_PRIMARY = "ORG-PRIMARY"  # 在册组织号首发 ⇒ 正文主语＝公司正式名
SRC_EXEC_ON_NAMEROOM = "EXEC-ON-NAMEROOM"  # 个人号首发＋官方名录/公告锚 ⇒ 可进正文（署名两件套）
SRC_EXEC_PERSONAL = "EXEC-PERSONAL"  # 个人号首发、无官方口径锚 ⇒ 🔴 不得进正文（只可佐证）
SRC_UNVERIFIED = "UNVERIFIED"  # 判不出／证据链不干净 ⇒ 丢，并记未核实

SRC_LABELS: frozenset[str] = frozenset(
    {SRC_ORG_PRIMARY, SRC_EXEC_ON_NAMEROOM, SRC_EXEC_PERSONAL, SRC_UNVERIFIED}
)
#: 进正文资格（唯一判据）：ORG 首发，或个人号经官方名录/公告锚点确认的那一枚。
BODY_SRC_LABELS: frozenset[str] = frozenset({SRC_ORG_PRIMARY, SRC_EXEC_ON_NAMEROOM})
#: 只有名录锚这一形允许把署名带上正文；``EXEC-PERSONAL`` 永远只进佐证位。
BODY_ANCHOR_LABELS: frozenset[str] = frozenset({SRC_EXEC_ON_NAMEROOM})

#: 号型闭集（P1）：机构号 / 职衔号（局长、新闻官一类）/ 个人号。
ACCOUNT_KIND_ORG = "ORG"
ACCOUNT_KIND_OFFICE = "OFFICE"
ACCOUNT_KIND_PERSON = "PERSON"
ACCOUNT_KINDS: frozenset[str] = frozenset({ACCOUNT_KIND_ORG, ACCOUNT_KIND_OFFICE, ACCOUNT_KIND_PERSON})
#: 绑定行来源闭集（P1）：①机构官网社媒名录 ②本人 bio 自述「公司＋职位＋自家域名」。
#: 名录之外的任何形（第三方数据库、维基、"看起来像官方"）都不算绑定行。
BINDING_SOURCE_NAMEROOM = "nameroom"
BINDING_SOURCE_BIO = "bio_self_report"
BINDING_SOURCES: frozenset[str] = frozenset({BINDING_SOURCE_NAMEROOM, BINDING_SOURCE_BIO})

#: P0 的「发帖量与体量相称」机械下限（零发帖的冒名位＝F3 那一形，必须挡在 OUT）。
#: 这把尺的数值由她裁；改它同批改 ``tests/test_news_source_whitelist.py`` 的 P0 腿。
P0_MIN_POST_COUNT = 20
#: 「加入年份」缺失/占位的识别形（缺件＝P0 不成立；这里只认「没填」的两种写法）。
_MISSING_INTS: frozenset[int] = frozenset({0, -1})

#: 判定行上那枚标的**门票**（形状闸）。只准 ``SRC=<闭集取值>`` 整串相等；
#: 🔴 台账 #67★ 的旧病在这里防住：名册一旦混进空串，``|`` 就会拼出一个**空分支**，
#: 形状闸当场变成恒真（成本静默涨、测试仍绿）。装配期把这件事炸出来，不留到运行期。
def _build_src_line_re(labels: Iterable[str]) -> re.Pattern[str]:
    values = sorted(labels)
    if any(not value for value in values):
        raise ValueError("SRC_LABELS 不得含空值：空分支会把门票拼成恒真正则")
    return re.compile(r"^SRC=(?:" + "|".join(re.escape(value) for value in values) + r")$")


SRC_LINE_RE: re.Pattern[str] = _build_src_line_re(SRC_LABELS)
#: 行文里那枚标的取用形（左邻禁字母数字下划线连字符，防 ``XSRC=``/``-SRC=`` 造第二枚标；
#: 取值段只收 ASCII 标记字符——中文/空格/括号一律不进气，越界即不匹配、由消毒涂掉）。
SRC_TOKEN_RE: re.Pattern[str] = re.compile(r"(?<![A-Za-z0-9_-])SRC=([A-Za-z0-9._+\-/]{1,48})")


def is_src_label(value: object) -> bool:
    """该取值是否在闭集内（闭集外＝不是标，是脏数据）。"""
    return isinstance(value, str) and value in SRC_LABELS


def src_marker(value: object) -> str:
    """造一枚标；闭集外一律回落 ``SRC=UNVERIFIED``（fail-closed，绝不原样放行自由文本）。"""
    return f"SRC={value if is_src_label(value) else SRC_UNVERIFIED}"


def is_valid_src_field(field: object) -> bool:
    """门票：整枚判定行字段必须是 ``SRC=<闭集取值>``（自由文本、多余前后缀一律拒）。"""
    return bool(SRC_LINE_RE.match(str(field or "").strip()))


def body_admits_src(value: object) -> bool:
    """这条标准不准进正文（``EXEC-PERSONAL``/``UNVERIFIED`` 永远不准）。"""
    return is_src_label(value) and value in BODY_SRC_LABELS


def sanitize_src_markers(text: str) -> str:
    """消毒：行文里任何一枚 ``SRC=`` 取值不在闭集内 ⇒ 整枚涂成 ``SRC=UNVERIFIED``。

    存在理由＝判定行加字段必同批补消毒（台账 #67★）：上游任何一处把标写成自由文本
    （或被外部内容伪造出一枚 ``SRC=ORG-PRIMARY``）时，出站闸不认「像不像标」，只认闭集。
    幂等：产物永远是闭集值，二次调用逐字不变。
    """
    value = text or ""
    if "SRC=" not in value:
        return value

    def _clamp(match: re.Match[str]) -> str:
        captured = match.group(1)
        return f"SRC={captured if captured in SRC_LABELS else SRC_UNVERIFIED}"

    return SRC_TOKEN_RE.sub(_clamp, value)


# ==================== 名册行的形状（数据面的类型，不是数据本身）====================


@dataclass(frozen=True)
class AccountRow:
    """一行＝一个**在册账号**（值全部来自 Runtime 侧数据面，本件一个字都不写死）。

    P0 三件＝``subject_full_name`` + ``bio_domain``（指自家域名）+ 发帖量/加入年份/
    粉丝量与体量相称；P1 绑定行＝``binding_*`` 四件 + ``binding_source``。
    🔴 ``verified_badge`` 只作登记（她开页看到的标记），**永不进任何判据**（D3）。
    """

    handle: str = ""
    platform: str = ""
    kind: str = ACCOUNT_KIND_PERSON
    subject_full_name: str = ""
    display_name: str = ""
    bio_domain: str = ""
    profile_url: str = ""
    post_count: int = 0
    joined_year: int = 0
    follower_count: int = 0
    binding_company: str = ""
    binding_title: str = ""
    binding_valid_from: str = ""
    binding_valid_to: str = ""
    binding_source: str = ""
    verified_badge: bool = False

    @property
    def slot(self) -> str:
        """账号的唯一槽位＝``platform/handle``（认人不认昵称；昵称进 ``display_name`` 双查）。"""
        return f"{self.platform.strip().lower()}/{self.handle.strip().lower()}"


@dataclass(frozen=True)
class PostSignals:
    """一条帖的**结构读数**（P2/P3/P4 的输入；取不到的字段留 ``None``＝判不出）。

    🔴 「判不出」永远不等于「算过」：``is_root is None``（出口没给根帖判定）在 P2 里
    直接落回 ``EXEC-PERSONAL``，绝不默认「那就当它是根帖」。这是本段唯一允许的
    保守方向。
    """

    text: str = ""
    handle: str = ""
    display_name: str = ""
    self_domain: str = ""
    link_urls: tuple[str, ...] = ()
    is_root: bool | None = None
    is_reply: bool = False
    in_reply_to_handle: str = ""
    quote_depth: int | None = None
    quote_target_handle: str = ""
    is_pure_retweet: bool = False
    org_repost_confirmed: bool = False
    org_repost_handle: str = ""
    org_repost_within_seconds: float | None = None


#: 公告语形（P3③）＋名录/新闻室路径（P3①）＋联署公开信（P3④）。
_NEWSROOM_PATH_RE = re.compile(
    r"^/(?:[a-z0-9][a-z0-9\-_]*/){0,3}"
    r"(?:newsroom|news|press|press-releases?|releases?|announcements?|blog|company|products?)/?",
    re.IGNORECASE,
)
_ANNOUNCE_FORM_RE = re.compile(
    r"(announc(?:ing|ed)|now available|officially|introducing|we[’']?ve launched"
    r"|正式発表|正式发表|正式发布|即日起|将于.{0,16}(?:上线|发布|推出)|上线公告|维护公告"
    r"|发布公告|发布通知|现已被批准|已获得)",
    re.IGNORECASE,
)
#: 「产品名/政策名」的**严格**形状：《》「」【】包裹的专名、全大写缩写（可带版本号）、
#: 驼峰形、``v1.2`` 形。刻意不含普通首字母大写的英文词——宽松的专名判定会让推测语
#: 躲过 P4（＝把该拦的放进正文），fail-closed 只能往严的方向走。
_NAMED_THING_RE = re.compile(
    r"(《[^》]{2,40}》|「[^」]{2,40}」|【[^】]{2,40}】"
    r"|[A-Z]{2,12}[-.]?\d+(?:\.\d+){0,3}|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*"
    r"|v\d+(?:\.\d+){1,3})",
    re.UNICODE,
)
_JOINT_LETTER_RE = re.compile(r"(联署|公开信|共同签署|joint\s+letter|open\s+letter)", re.IGNORECASE)
#: 个人互动形（P4）逐条：@开头 / 回复链 / 点赞·关注列表截图 / 转述他人且无自域链接 /
#: 无条件推测语 / 未锚定的「额度·灰度·补偿」。
_MENTION_LEAD_RE = re.compile(r"^\s*@[\w.\-]{1,60}")
_REPLY_FORM_RE = re.compile(
    r"^\s*(?:re\s*:|回复\s*@?|转发自?\s*@|in\s+reply\s+to\b)",
    re.IGNORECASE,
)
_LIKES_CAPTURE_RE = re.compile(
    r"(点赞列表|关注列表|粉丝列表|被.{0,12}点赞|收到.{0,6}个赞|赞了|liked\s+by|followed\s+by)",
    re.IGNORECASE,
)
_HEARSAY_RE = re.compile(
    r"(转述|他[说称]|她[说称]|他说|她说|回应称|据他|据她|受访|采访|interview|according\s+to)",
    re.IGNORECASE,
)
_SPECULATION_RE = re.compile(
    r"(\bmaybe\b|\bperhaps\b|\bhopefully\b|\bsoon\b|I\s+think|I\s+hope|\bguess\b|\bprobabl(y|e)\b"
    r"|大概率|估计|应该快|可能会|或许|不好说|我觉得|我猜|大概)",
    re.IGNORECASE,
)
_QUOTA_ROLLOUT_RE = re.compile(
    r"(额度|配额|限额|灰度|内测|临时补偿|补偿|封禁解除|quota|rate.?limit|rollout|waitlist)",
    re.IGNORECASE,
)
_EMOJI_CATEGORIES: frozenset[str] = frozenset({"So", "Sc", "Sk", "Sm", "Cn"})
#: 纯玩梗/图片梗的形状：剥掉 emoji 与标点后，剩下的可读字符少于这么多 ⇒ 没有可当口径的信息。
_MEME_RESIDUE_MAX_CHARS = 6


def _readable_residue(text: str) -> str:
    """剥 emoji / 符号 / 空白，只留「可读的字」（玩梗判据的输入，不参与别的尺）。"""
    chars: list[str] = []
    for char in text or "":
        if ord(char) >= 0x1F000:
            continue
        if char.isspace() or unicodedata.category(char) in _EMOJI_CATEGORIES:
            continue
        chars.append(char)
    return "".join(chars).strip()


def _has_named_thing(text: str) -> bool:
    """「同帖含产品名或政策名」的唯一形状尺（P3③ 要它、P4⑦ 也问它，禁两处各写一份）。"""
    return bool(_NAMED_THING_RE.search(text or ""))


def _fold_name(value: str) -> str:
    """显示名比对用的归一（NFKC + casefold）：全角/大小写差异不算「换了人」。"""
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _link_on_domain(url: str, domain_text: str) -> bool:
    """这条链接是否落在给定域名（末段后缀口径走真身 ``_matches``，不另写一把尺）。"""
    domain = normalize_domain(url)
    binding = normalize_domain(domain_text)
    return bool(domain and binding) and _matches(domain, binding)


def _url_path(url: str) -> str:
    raw = str(url or "").strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return "/" + raw.partition("/")[2]


# ==================== P0–P4（逐条可断言的谓词）====================


def p0_attribution_holds(row: AccountRow | None, *, subject_admitted: Callable[[str], bool]) -> bool:
    """P0 归属三件同在场：主体全名 ∧ bio 指自家域名（且该域名在册）∧ 体量相称。

    🔴 「认证账号」标记不在场＝本谓词从不读 ``verified_badge``（锁在测试里逐字翻它，
    翻 True 翻 False 结果必须一样）。「查无此主体」「新注册＋涨粉热潮」都落在这里。
    """
    if row is None:
        return False
    if not (row.subject_full_name or "").strip():
        return False
    if not (row.bio_domain or "").strip():
        return False
    if not subject_admitted(row.bio_domain):
        return False
    if int(row.post_count) < P0_MIN_POST_COUNT:
        return False
    if int(row.joined_year) in _MISSING_INTS or not (1990 <= int(row.joined_year) <= 2100):
        return False
    return int(row.follower_count) > 0


def _iso_date(value: str) -> date | None:
    """绑定行生效期的唯一解析口：认不了＝判不出＝按过期处理（fail-closed）。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def p1_binding_holds(row: AccountRow | None, *, now: date | None = None) -> bool:
    """P1 号型 + 人-司绑定行：``ORG`` 免绑定；``OFFICE``/``PERSON`` 必须有一条绑定行。

    三件牙：① ``kind`` 必在闭集内；② 绑定行四件齐（公司＝主体全名、职位、生效起、
    来源在闭集内）；③ 职位过期（离职/换岗）⇒ 整条不成立（D1，转「只作关注」，
    在本出口等价于「不进正文」）。
    """
    if row is None or row.kind not in ACCOUNT_KINDS:
        return False
    if row.kind == ACCOUNT_KIND_ORG:
        return True
    if not (row.binding_title or "").strip():
        return False
    if row.binding_source not in BINDING_SOURCES:
        return False
    company = (row.binding_company or "").strip().casefold()
    subject = (row.subject_full_name or "").strip().casefold()
    if not company or company != subject:
        return False
    effective_from = _iso_date(row.binding_valid_from)
    if effective_from is None:
        return False
    # 本地时区取今日（astimezone 使 aware，规避 DTZ005/DTZ011；与 news_feeds 同一口径）。
    today = now or datetime.now().astimezone().date()
    if effective_from > today:
        return False
    expiry_text = (row.binding_valid_to or "").strip()
    if expiry_text:
        expiry = _iso_date(expiry_text)
        if expiry is None or expiry < today:
            return False
    return True


def p2_post_shape_holds(
    post: PostSignals | None,
    row: AccountRow | None,
    *,
    outlet_kind_of_handle: Callable[[str], str] | None = None,
) -> bool:
    """P2 帖形：根帖 ∧ 引用目标只在 {自己, 在册 ORG, 在册 OFFICE} ∧ 纯转发永不单独成条。

    ``is_root`` 为 ``None``（出口没给判定）＝不成立；🔴 不许默认当真。引用深度 ≥2 属
    个人互动形（在 P4 里一票否决），这里只拦「引用目标不在册」这一半。
    """
    if post is None or row is None:
        return False
    if post.is_root is not True:
        return False
    if post.is_pure_retweet:
        return False
    if post.in_reply_to_handle:
        return False
    target = (post.quote_target_handle or "").strip().lower()
    if not target:
        return True
    if target == (row.handle or "").strip().lower():
        return True
    kind_of = outlet_kind_of_handle or (lambda _handle: "")
    return kind_of(target) in {ACCOUNT_KIND_ORG, ACCOUNT_KIND_OFFICE}


def p3_official_form_hits(
    post: PostSignals | None,
    row: AccountRow | None,
    *,
    subject_admitted: Callable[[str], bool],
    outlet_kind_of_handle: Callable[[str], str] | None = None,
) -> tuple[str, ...]:
    """P3 官方消息形（任一命中即算）：返回命中的**编号名**，空元组＝没有官方口径锚。

    ① 帖内链接落在绑定行域名的 newsroom/blog/press/release/product 路径；
    ② 在册 ORG 号 ≤60 秒原样重发；③ 公告语形 **且** 同帖含产品名或政策名；
    ④ 联署/公开信类，原文链接落在在册 ORG 域名上。
    """
    if post is None or row is None:
        return ()
    hits: list[str] = []
    links = tuple(str(url) for url in (post.link_urls or ()) if str(url or "").strip())
    if any(
        _link_on_domain(url, row.bio_domain) and _NEWSROOM_PATH_RE.match(_url_path(url))
        for url in links
    ):
        hits.append("P3-NEWSROOM-LINK")
    mirror_handle = (post.org_repost_handle or "").strip().lower()
    kind_of = outlet_kind_of_handle or (lambda _handle: "")
    if (
        post.org_repost_confirmed
        and mirror_handle
        and kind_of(mirror_handle) == ACCOUNT_KIND_ORG
        and post.org_repost_within_seconds is not None
        and float(post.org_repost_within_seconds) <= 60.0
    ):
        hits.append("P3-ORG-MIRROR")
    text = post.text or ""
    if _ANNOUNCE_FORM_RE.search(text) and _has_named_thing(text):
        hits.append("P3-ANNOUNCE-FORM")
    if _JOINT_LETTER_RE.search(text) and any(
        subject_admitted(url) for url in links
    ):
        hits.append("P3-JOINT-LETTER")
    return tuple(hits)


def p4_personal_interaction_hits(
    post: PostSignals | None,
    *,
    anchored: bool = False,
) -> tuple[str, ...]:
    """P4 个人互动形（任一命中＝🔴 一票否决，不得进正文）：返回命中编号，空元组＝不是个人互动。

    回复链 / 以 ``@他人`` 开头 / 纯玩梗·emoji·图片梗 / 点赞或关注列表截图 / 引用链深度
    ≥2 / 无自域链接的转述他人观点 / 无条件推测语（与产品名不共现）/ 未同时命中
    P3①② 的「额度·灰度·补偿」类。``anchored`` 由调用方从 P3①② 的结果传入。
    """
    if post is None:
        return ()
    text = post.text or ""
    hits: list[str] = []

    def add(code: str) -> None:
        if code not in hits:
            hits.append(code)

    if post.is_reply:
        add("P4-REPLY")
    if post.quote_depth is not None and int(post.quote_depth) >= 2:
        add("P4-QUOTE-DEPTH")
    # 🔴 逐**段**判（F1 双面样本的形状＝同一条里公告段与玩梗/回复段各一段）：
    # 行首形（@他人开头、re:、回复 @x）只在段首认得到，整串一次扫会把夹在后面的
    # 个人互动段静默吃掉＝一票否决变成没票。任何一段命中即整条不进正文。
    lines = [line for line in text.splitlines() if line.strip()] or [text]
    for line in lines:
        if _REPLY_FORM_RE.search(line):
            add("P4-REPLY")
        if _MENTION_LEAD_RE.match(line):
            add("P4-MENTION-LEAD")
        residue = _readable_residue(line)
        if not residue or len(residue) < _MEME_RESIDUE_MAX_CHARS:
            add("P4-MEME-OR-IMAGE-ONLY")
        if _LIKES_CAPTURE_RE.search(line):
            add("P4-LIKES-FOLLOW-CAPTURE")
        if _SPECULATION_RE.search(line) and not _has_named_thing(line):
            add("P4-SPECULATION")
    if _HEARSAY_RE.search(text) and not any(
        _link_on_domain(url, post.self_domain) for url in (post.link_urls or ())
    ):
        add("P4-HEARSAY-NO-SELF-DOMAIN")
    if _QUOTA_ROLLOUT_RE.search(text) and not anchored:
        add("P4-QUOTA-ROLLOUT-UNANCHORED")
    return tuple(hits)


def judge_account_src(
    row: AccountRow | None,
    post: PostSignals | None,
    *,
    subject_admitted: Callable[[str], bool],
    outlet_kind_of_handle: Callable[[str], str] | None = None,
    now: date | None = None,
) -> str:
    """出口判定：四枚标里取一枚（🔴 判不出＝``UNVERIFIED``，绝不默认进正文）。

    ``进正文 ⇔ P0 ∧ P1 ∧ P2 ∧ P3 ∧ ¬P4``（出口式在 ``BODY_SRC_LABELS`` 一处定义）。
    草案的 ``OUT ⇔ ¬P0 ∨ ¬P1 ∨ (P4 ∧ ¬P3)`` 在闭集里落成 ``UNVERIFIED``（丢弃）；
    ``只关注`` 不是出口取值（它不进这一条链的正文，也不进佐证位），所以职位过期、
    无绑定行、非根帖这一类一律拿不到 ``EXEC-ON-NAMEROOM``。
    """
    if row is None or post is None:
        return SRC_UNVERIFIED
    if row.kind not in ACCOUNT_KINDS:
        return SRC_UNVERIFIED
    if not p0_attribution_holds(row, subject_admitted=subject_admitted):
        return SRC_UNVERIFIED
    if not p1_binding_holds(row, now=now):
        return SRC_UNVERIFIED
    # D2：句柄与显示名**双查**，任一变化即回炉 P0（本仓实锤过一例改名）。
    if (post.handle or "").strip().lower() != (row.handle or "").strip().lower():
        return SRC_UNVERIFIED
    if _fold_name(post.display_name) != _fold_name(row.display_name):
        return SRC_UNVERIFIED
    if row.kind == ACCOUNT_KIND_ORG:
        return SRC_ORG_PRIMARY
    hits = p3_official_form_hits(
        post,
        row,
        subject_admitted=subject_admitted,
        outlet_kind_of_handle=outlet_kind_of_handle,
    )
    anchored = any(hit in {"P3-NEWSROOM-LINK", "P3-ORG-MIRROR"} for hit in hits)
    veto = p4_personal_interaction_hits(post, anchored=anchored)
    if veto and not hits:
        return SRC_UNVERIFIED
    if veto:
        return SRC_EXEC_PERSONAL
    if not p2_post_shape_holds(post, row, outlet_kind_of_handle=outlet_kind_of_handle):
        return SRC_EXEC_PERSONAL
    if not hits:
        return SRC_EXEC_PERSONAL
    return SRC_EXEC_ON_NAMEROOM


def build_exec_signature(row: AccountRow) -> str:
    """署名两件套（固定形）：主体正式名（平台 个人号 @句柄，本人显示名；经官方名录/公告锚点确认）。

    🔴 这是**出处署名**，不是把个人表态改写成公司主语：正文里的句子仍是原句、主语不变
    （改主语＝把个人口径洗成官方口径，本口径唯一红线级错误，锁在测试的「标题逐字不变」腿）。
    """
    return (
        f"{row.subject_full_name.strip()}（{row.platform.strip() or 'x'} 个人号 @{row.handle.strip()}，"
        f"{row.display_name.strip()}；经官方名录/公告锚点确认）"
    )


_EXEC_SIGNATURE_RE = re.compile(
    r"\A(?P<subject>[^（）]{1,80})（(?P<platform>[^（）@，,]{1,24}) 个人号 @(?P<handle>[\w.\-]{1,60})，"
    r"(?P<display>.{1,80})；经官方名录/公告锚点确认）\Z"
)


def is_exec_signature(text: str) -> bool:
    """署名的形状闸（门票的另一半）：只能由 ``build_exec_signature`` 造得出这一形。"""
    return bool(_EXEC_SIGNATURE_RE.match(text or ""))

