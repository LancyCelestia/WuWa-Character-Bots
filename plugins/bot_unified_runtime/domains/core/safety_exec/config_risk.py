"""参数风险分级表（SAFE-EXEC 规格 §4 的真身）：哪些参数能自动改、哪些要书面同意。

定位与哲学
----
- 本文件是**声明数据 + 纯判定**：不 import 包内业务件，只借两处既有真身
  （``control_plane.config_store`` 的凭证识别与打码出口），避免第二套「什么算密钥」表。
  与 ``domains/core/board_taxonomy.py``、``domains/core/session_keys.py`` 同哲学。
- 规格 §4 明令「分级元数据与字段同源才不会漂移」⇒ 判定门（``tests/test_safety_exec_consent.py``）
  拿 ``scripts/board_doc_sync.load_config_fields`` 的字段全集逐枚过一遍，
  并要求**在册条目全部是真字段**（幻影条目＝某条模式已经悄悄落空）。

四档语义（她 2026-09-25 裁定 P-4＝按推荐）
----
- **R0 自由改**：bot 可以不问就改，但**必须**回显改了什么 **+** 给一条一键回退；
  没有回退口就不许自动改（回退口的执法在 ``consent.py``，不在本文件）。
- **R1 需确认**：回显 diff + 一次性确认号（管理员及以上、请求所在会话）。
- **R2 需书面同意**：**只有超管（T0）能从入站消息批**，bot 不得代批。
- **R3 永不自动**：只允许产出待审补丁（``RepairService`` 那一档就是天花板）。

缺省档是 **R2（fail-closed）**，不是 R0
----
理由：R0 的含义是「可以不问人就改」，那它必须是**被明确登记过**的自由改面；
让一个没登记过的键默认落进 R0，等于「谁忘了写表 ⇒ 那个键变成自动可改」，
方向正好反了。所以本表的结构是：

    R3 显式 → R2 显式 → R1 显式 → R0 显式 → R3 模式 → R2 模式 → R1 模式 → R0 模式 → 缺省 R2

模式检查里 R2 排在 R1/R0 **之前**，因为 ``bot_rate_limit_*_min_interval_seconds``
既像「限流速率」（R1）又像「间隔」（R0），而 ``bot_*_db_path`` 既是路径又常被当成
普通字符串键——冲突时一律取更严的那一档。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# 档位
# ---------------------------------------------------------------------------


class RiskTier(str, Enum):
    """参数风险档（字符串值即规格里的 R0/R1/R2/R3，便于直接进审计与卡片）。"""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


#: 缺省档：未登记的键一律按「要书面同意」处理（见模块 docstring 的 fail-closed 论证）。
DEFAULT_TIER = RiskTier.R2

#: 允许不问就改的档（唯一一枚；放宽它必须同时放宽「无回退口不许自动改」那条硬门）。
UNATTENDED_CHANGE_TIERS = frozenset({RiskTier.R0})

#: 需要一次性确认号的档（R1 与 R2 都走同意账，差别在「谁能批、从哪儿批」）。
CONSENT_REQUIRED_TIERS = frozenset({RiskTier.R1, RiskTier.R2})

#: 需要**超管书面同意**的档。
WRITTEN_CONSENT_TIERS = frozenset({RiskTier.R2})

#: 永不自动执行的档：只产待审补丁。
NEVER_AUTO_TIERS = frozenset({RiskTier.R3})


def describe_tier(tier: RiskTier) -> str:
    """档位的一行人话（回显文案与诊断卡共用，禁在别处再抄一份）。"""
    if not isinstance(tier, RiskTier):
        raise TypeError(f"tier 必须是 RiskTier，收到 {type(tier).__name__}")
    return {
        RiskTier.R0: "R0 自由改：可不问就改，但必须回显改了什么并给一键回退",
        RiskTier.R1: "R1 需确认：要一次性确认号，管理员及以上在本会话内确认",
        RiskTier.R2: "R2 需书面同意：只有超级管理员亲手从消息里批，bot 不得代批",
        RiskTier.R3: "R3 永不自动：只允许产出待审补丁，部署由人执行",
    }[tier]


# ---------------------------------------------------------------------------
# 元目标（不是 bot_* 键、但同样是「改设置」的目标：规格 §4 的 R3 名单）
# ---------------------------------------------------------------------------

META_PREFIX = "meta:"

#: 规格 §4 R3 条里的「非键」目标。判定要求它们**永远**解到 R3。
#:
#: 存的是 `normalize_target` 的**规范形**（`meta:` 之后一律小写）。`risk_tier_for_target`
#: 先把目标折成规范形再查这张表，所以登记侧写原名（`meta:settings.SETTABLE_KEYS`）
#: 会当场查不到集合 ⇒ 护栏复算门一跑就 ``KeyError``，当天那道门等于不存在
#: ——本席实跑撞到的就是这一枚。`META_R3_TARGET_SPEC_NAMES` 保留规格原文供人读追溯，
#: 测试 `test_registered_targets_are_all_in_canonical_form` 逐枚钉「规格原名折成
#: 规范形之后恰好等于这张表」，防止下一个原名混进判定用的集合里。
META_R3_TARGETS: frozenset[str] = frozenset(
    {
        "meta:settings.restart_required_keys",  # 热改名单的成员资格本身
        "meta:settings.settable_keys",
        "meta:runtime_hot_override_fields",  # 真正的热改硬约束表（根 __init__.py）
        "meta:file.env",  # .env 本体
        "meta:file.model_registry",  # 模型注册表文件本体
        "meta:persona.four_red_lines",  # 人格四红线
        "meta:safety.red_line_words",  # 安全红线词表
        "meta:safety.six_hard_lines",  # 六硬线
        "meta:safety.config_risk_table",  # 本表自己（禁止 bot 给自己降档）
        "meta:safety.consent_ledger",  # 同意账自己（禁止 bot 销毁/伪造批语）
    }
)

#: 规格原文的字面写法（只做人读追溯，不参与判定；判定一律走上表的规范形）。
META_R3_TARGET_SPEC_NAMES: tuple[str, ...] = (
    "meta:settings.RESTART_REQUIRED_KEYS",
    "meta:settings.SETTABLE_KEYS",
    "meta:runtime_hot_override_fields",
    "meta:file.env",
    "meta:file.model_registry",
    "meta:persona.four_red_lines",
    "meta:safety.red_line_words",
    "meta:safety.six_hard_lines",
    "meta:safety.config_risk_table",
    "meta:safety.consent_ledger",
)

#: 规格 §4 R3 条里**确实是配置键**的条目（全部为 config.py 真字段，由门锁死）。
#: R3 的语义是「bot 永不得自动改，连书面同意都不接」⇒ 这里只放**观测面与护栏本体**：
#: 让 bot 能自动关掉审计流水，等于让它自己决定「这次改动留不留痕」。
EXPLICIT_R3_KEYS = frozenset(
    {
        "BOT_AUDIT_ENABLED",  # 运行审计总开关
        "BOT_PROMPT_AUDIT_ENABLED",  # 进模型前后的取证流水
        "BOT_PROMPT_AUDIT_INCLUDE_UNTRUSTED_CONTEXT",  # 不可信上下文是否入册
        # 注：内容安全与六硬线**不是配置键**（是代码与词表），因此落在 META_R3_TARGETS，
        # 不在这里放一枚不存在的键名——幻影条目会让「按键名兜」的判据悄悄落空。
    }
)

#: 规格 §4 R2 条逐枚落名（全部经测试断言「确为 config.py 真字段」，防幻影条目）。
EXPLICIT_R2_KEYS = frozenset(
    {
        # 角色名单
        "BOT_ADMIN_USER_IDS",
        "BOT_SUPER_ADMIN_USER_IDS",
        "BOT_TELEGRAM_ADMIN_USER_IDS",
        "BOT_TRUSTED_USER_IDS",
        "BOT_ENTERPRISE_USER_IDS",
        "BOT_BLOCKED_USER_IDS",
        # 豁免族
        "BOT_RATE_LIMIT_BYPASS_ROLES",
        "BOT_QUIET_HOURS_BYPASS_ROLES",
        # 出站闸与验证（BOT_OUTBOUND_* 另有模式兜）
        "BOT_OUTBOUND_GATE_ENABLED",
        "BOT_OUTBOUND_VERIFY_ENABLED",
        # 控制面与令牌
        "BOT_CONTROL_PLANE_ENABLED",
        "BOT_CONTROL_PLANE_TOKEN_SHA256",
        "BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256",
        # 内容路由名单与档位（BOT_CONTENT_ROUTE_* 另有模式兜）
        "BOT_CONTENT_ROUTE_ENABLED",
        "BOT_CONTENT_ROUTE_WORDS",
        # 归档最小角色
        "BOT_MEDIA_ARCHIVE_MIN_ROLE",
        # 记忆与百科总闸
        "BOT_MEMORY_ENABLED",
        "BOT_MEMORY_BUS_ENABLED",
        "BOT_MEMORY_SEMANTIC_RECALL_ENABLED",
        "BOT_KB_WIKI_ENABLED",
        # TTS 引擎地址与音频目录
        "BOT_TTS_API_URL",
        "BOT_TTS_REF_AUDIOS",
        # 脏话守卫与删消息
        "BOT_DIRTY_GUARD_ENABLED",
        "BOT_DIRTY_GUARD_DELETE",
        # 执行模式与数据库代理
        "BOT_PROMPT_EXECUTION_MODE",
        "BOT_DATABASE_BROKER_ENABLED",
        # 本引擎自己的开关（不许 bot 给自己松绑）
        "BOT_SAFETYEXEC_ENABLED",
        "BOT_SAFETYEXEC_CONSENT_TTL_MINUTES",
        "BOT_SAFETYEXEC_AUTO_R0_ENABLED",
        # 规格 §4 未逐枚点名、但同族同性的两枚（隐私外发与自动删除，判据同「护栏」）
        "BOT_SHARED_EXPORT_INCLUDE_PRIVATE",
        "BOT_MEME_LIBRARY_NSFW_DELETE",
        # 文件写盘口六键（需求 16(2)，2026-09-26 S-FILES-LAND 落 config.py 时点名）：
        # 容器判据本身＝护栏面——白名单根/总闸被放宽意味着 bot 能往哪写、能不能写
        # 都变了，放宽必须超管亲批；限额与日配额同理（调大＝松闸），模式族
        # （_DIRS$/_MAX_BYTES 等）都盖不住这些词尾，故逐枚落名，不留缺省池
        # （test_tier_coverage_ratchet_only_goes_down 的地板因此不涨）。
        "BOT_FILES_WRITE_ENABLED",
        "BOT_FILES_WRITE_ALLOWED_DIRS",
        "BOT_FILES_WRITE_MAX_BYTES",
        "BOT_FILES_WRITE_DAILY_CREATE",
        "BOT_FILES_WRITE_DAILY_REPLACE",
        "BOT_FILES_READ_CONFINED_MAX_BYTES",
    }
)

#: 规格 §4 R1 条里逐枚落名的键（今天只有个别键名无法用模式表达）。
EXPLICIT_R1_KEYS: frozenset[str] = frozenset()

#: 上表里**尚未**在 `config.py` 落地的键（本引擎剩下的两枚开关）。
#: `BOT_SAFETYEXEC_ENABLED` 已于 2026-09-26 咽喉执法波（S-T-CONSENT1）登记为真字段
#: （缺省 True＝执法开），按家规从本表摘除——待登记表只准减不准混。
#: 它们照样有档（fail-closed 的 R2），所以「登记面」与「字段面」的差集必须显式
#: 记在这里，而不是让判据把它当成幻影条目一并放行；两枚键落 `config.py` 后本集合清空。
PENDING_CONFIG_KEY_PROPOSALS: frozenset[str] = frozenset(
    {
        "BOT_SAFETYEXEC_AUTO_R0_ENABLED",
        "BOT_SAFETYEXEC_CONSENT_TTL_MINUTES",
    }
)

#: 规格 §4 R0 条里逐枚落名的键（同上；R0 主要靠模式族登记）。
EXPLICIT_R0_KEYS: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# 模式族（只在显式名单之后参与判定；冲突时更严的一档先赢）
# ---------------------------------------------------------------------------

_TIER_PATTERNS: dict[RiskTier, tuple[str, ...]] = {
    RiskTier.R3: (
        # 人格与红线词表所在的键面（措辞面属人，不由 bot 自改）。
        r"^BOT_PERSONA_.*RED_LINE",
        r"^BOT_.*_FORBIDDEN_WORDS$",
        # 审计/取证流水的开关面：留不留痕不由 bot 自己决定（规格 §4 R3 + 台账 #54 的账本教训）。
        r"^BOT_AUDIT_ENABLED$",
        r"^BOT_PROMPT_AUDIT_(ENABLED|INCLUDE_UNTRUSTED_CONTEXT)$",
        r"^BOT_.*_SANITIZE_ENABLED$",
    ),
    RiskTier.R2: (
        r"^BOT_CONTROL_PLANE_",
        r"^BOT_OUTBOUND_",
        r"^BOT_CONTENT_ROUTE_",
        r"^BOT_SAFETYEXEC_",
        r"^BOT_SECURITY_",
        r"^BOT_INJECTION_",
        r"^BOT_COOKIE_.*_SEND$",  # 跨 host 送 cookie 的策略面（凭证外泄咽喉）
        r"_BYPASS_ROLES$",
        r"_MIN_ROLE$",
        r"_ROLES$",
        r"_USER_IDS$",
        r"_USER_ID$",
        r"_TOKEN(_SHA256)?$",
        r"_SHA256$",
        r"_API_KEYS?$",
        r"_KEY$",
        r"(_SECRET|_PASSWORD|_PASSPHRASE|_CREDENTIALS?)$",
        r"(_DB_PATH|_PATH|_DIR|_ROOT|_FILE)$",
        r"(_URL|_URI)$",
        r"^BOT_TTS_(API_URL|REF_AUDIOS|VOICES?)$",
        r"^BOT_(KB_WIKI|MEMORY)_(.*_)?(ENABLED|TOPICS)$",
        r"^BOT_RUNTIME_SETTINGS_",  # 设置落盘位置本身
        r"^BOT_DATA_.*ENABLED$",
    ),
    RiskTier.R1: (
        r"^BOT_GROUP_(BLACK|WHITE)\d$",
        r"^BOT_RATE_LIMIT_",
        r"^BOT_QUIET_HOURS_",
        r"^BOT_.*_DAILY_(LIMIT|MAX|CAP|MAX_\w+)$",
        r"^BOT_.*_PER_(MESSAGE|DAY|HOUR)$",
        r"^BOT_.*_(THRESHOLD|GATE|GATE_ENABLED|CAP|BOUND|MIN_TIER)$",
        r"^BOT_.*SUBSCR.*(TARGET|WHITELIST|BLACKLIST)",
        r"^BOT_.*_WHITELIST$",  # 投递/准入白名单（未落 R2 模式的那些）
        # 审计流水的**容量**旋钮：不是开关（开关是 R3），改小顶多少留证据，要确认不要书面。
        r"^BOT_(AUDIT|PROMPT_AUDIT|WEB_INTENT_TELEMETRY)_(MAX_ITEMS|MAX_BYTES|MAX_CHARS|RETENTION_DAYS)$",
    ),
    RiskTier.R0: (
        # 超时 / 重试 / 预算 / 概率 / 日志级别 / 保留数 / 刷新频率：规格点名的自由改面。
        r"^BOT_.*_TIMEOUT_(SECONDS|MS|SEC)$",
        r"^BOT_.*_(MAX_)?RETR(Y|IES)$",
        r"^BOT_.*_RETRY_DELAY_SECONDS$",
        r"^BOT_.*_PROBABILITY$",
        r"^BOT_.*_LOG_LEVEL$",
        r"^BOT_.*_KEEP_DAYS$",
        r"^BOT_.*_INTERVAL_(SECONDS|MINUTES|MILLISECONDS)$",
        r"^BOT_.*_(WAIT_)?BUDGET_(MS|SECONDS|TOKENS)$",
        r"^BOT_.*_MAX_CHARS_PER_MESSAGE$",
        r"^BOT_.*_REFRESH_(SECONDS|MINUTES|HOURS)$",
    ),
}

_COMPILED_TIER_PATTERNS: dict[RiskTier, tuple[re.Pattern[str], ...]] = {
    tier: tuple(re.compile(pattern) for pattern in patterns)
    for tier, patterns in _TIER_PATTERNS.items()
}

#: 判定顺序（更严的先判）；这条元组本身被测试锁死，防止有人重排成「R0 先赢」。
TIER_CHECK_ORDER: tuple[RiskTier, ...] = (
    RiskTier.R3,
    RiskTier.R2,
    RiskTier.R1,
    RiskTier.R0,
)

#: 「今天还兜不到任何真字段」的模式——**显式报备**的前瞻网，不是漏网。
#: 每枚的理由写在这里；测试只准「死模式 ⊆ 本集合」，新加的哑模式当场红。
#: （哑模式本身不危险：缺省档就是 R2；危险的是它让人以为「这一族已经有人看着」。）
FORWARD_LOOKING_PATTERNS: frozenset[str] = frozenset(
    {
        # R3：红线词表/消毒开关将来若升成配置键，必须先过 R3（这三枚是占位）。
        r"^BOT_PERSONA_.*RED_LINE",
        r"^BOT_.*_FORBIDDEN_WORDS$",
        r"^BOT_.*_SANITIZE_ENABLED$",
        # 本引擎剩下两枚待登记键走 PENDING_CONFIG_KEY_PROPOSALS 点名；
        # `^BOT_SAFETYEXEC_` 已于 2026-09-26 被真字段 BOT_SAFETYEXEC_ENABLED 点亮，
        # 不再是哑模式（登记即出册，别让它冒充「还没人看着」）。
        # 将来可能出现的安全/注入面配置键。
        r"^BOT_SECURITY_",
        r"^BOT_INJECTION_",
        r"^BOT_COOKIE_.*_SEND$",
        r"^BOT_DATA_.*ENABLED$",
        r"_USER_ID$",  # 单数形态（今天的名单键都是复数）
        r"^BOT_.*SUBSCR.*(TARGET|WHITELIST|BLACKLIST)",
        r"^BOT_.*_RETRY_DELAY_SECONDS$",
        r"^BOT_.*_REFRESH_(SECONDS|MINUTES|HOURS)$",
    }
)

_EXPLICIT_REGISTRIES: tuple[tuple[RiskTier, frozenset[str]], ...] = (
    (RiskTier.R3, EXPLICIT_R3_KEYS),
    (RiskTier.R2, EXPLICIT_R2_KEYS),
    (RiskTier.R1, EXPLICIT_R1_KEYS),
    (RiskTier.R0, EXPLICIT_R0_KEYS),
)

#: **必须**解到 R2/R3 的目标全集（护栏与授权面）。分级表被改动后由
#: ``tests/test_safety_exec_consent.py`` 逐枚复算；任何一枚掉到 R0/R1 ⇒ 红。
#: 这枚清单是「表被人改松」的唯一结构性探测器——判据本身写在代码里，
#: 但「哪些键属于护栏」这件事只能靠登记，所以登记处必须被锁住。
SAFETY_CRITICAL_TARGETS: frozenset[str] = frozenset(
    {
        *META_R3_TARGETS,
        *EXPLICIT_R3_KEYS,
        *EXPLICIT_R2_KEYS,
        # 模式族兜的代表名（规格 §4 R2 条点名但没逐枚落名的族，各挑一枚真键代表）
        "BOT_CONTROL_PLANE_HOST",
        "BOT_CONTROL_PLANE_PORT",
        "BOT_OUTBOUND_GATE_MAX_PER_TARGET_PER_HOUR",
        "BOT_CONTENT_ROUTE_PRIVATE_WHITELIST",
        "BOT_CONTENT_ROUTE_GROUP_BLACKLIST",
        "BOT_SUPER_ADMIN_USER_IDS",
        "BOT_PROMPT_EXECUTION_MODE",
        "BOT_TTS_API_URL",
        "BOT_RUNTIME_SETTINGS_DIR",
        "BOT_EMBEDDING_LOCAL_BASE_URL",
    }
)


def safety_critical_tier_violations(
    targets: Iterable[object] | None = None,
) -> dict[str, str]:
    """返回「护栏目标却解到 R0/R1」的 ``{目标: 实际档}``；空字典＝表没被改松。

    `targets` 省略＝复算 `SAFETY_CRITICAL_TARGETS` 全集；传入可迭代对象只用于
    注毒自证（喂一枚故意降档的目标，断言本函数真能打红）。非字符串元素在
    `risk_tier_for_target` 处按 ``TypeError`` 炸出来，不静默跳过——静默跳过会让
    「名单里混进一个拼错的键」看起来像「全部合规」。
    """
    names: tuple[object, ...] = (
        tuple(SAFETY_CRITICAL_TARGETS) if targets is None else tuple(targets)
    )
    bad: dict[str, str] = {}
    for name in names:
        tier = risk_tier_for_target(name)
        if tier not in WRITTEN_CONSENT_TIERS and tier not in NEVER_AUTO_TIERS:
            bad[str(name)] = tier.value
    return bad



# ---------------------------------------------------------------------------
# 判定入口
# ---------------------------------------------------------------------------


def normalize_target(target: object) -> str:
    """目标名规范形：去空白、大写；``meta:`` 目标保留前缀且大小写不敏感。

    抛 ``ValueError`` 的两种形态都是攻击面：空目标、含分隔符的目标
    （``"BOT_A\\nBOT_B"`` 这种多行输入一旦被当成一枚键匹配，就能拿一条同意改一串）。
    """
    if not isinstance(target, str):
        raise TypeError(f"目标名必须是字符串，收到 {type(target).__name__}")
    text = target.strip()
    if not text:
        raise ValueError("目标名不能为空")
    if re.search(r"[\r\n\t]", text):
        raise ValueError("目标名不得含换行或制表符")
    if text.startswith(META_PREFIX):
        inner = text[len(META_PREFIX) :].strip()
        if not inner or ":" in inner:
            raise ValueError(f"meta 目标形不正确：{text!r}")
        return f"{META_PREFIX}{inner.lower()}"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text):
        raise ValueError(f"配置键名形不正确：{text!r}")
    return text.upper()


def risk_tier_for_target(target: object) -> RiskTier:
    """解一枚目标的缺省风险档（纯函数、不读配置、不碰磁盘）。"""
    name = normalize_target(target)
    if name.startswith(META_PREFIX):
        # meta 目标是「改规则的规则」：本表只认 R3，没有例外通道。
        if name not in META_R3_TARGETS:
            raise KeyError(f"未登记的 meta 目标：{name}（新增请先入 META_R3_TARGETS）")
        return RiskTier.R3
    for tier, registry in _EXPLICIT_REGISTRIES:
        if name in registry:
            return tier
    for tier in TIER_CHECK_ORDER:
        for pattern in _COMPILED_TIER_PATTERNS[tier]:
            # `search` 而不是 `match`：表里一半的模式是**后缀形**（`_USER_IDS$`、
            # `(_DB_PATH|_PATH|_DIR|_ROOT|_FILE)$`），`re.match` 从头锚定 ⇒ 这些
            # 模式永远不命中 ⇒ 整族护栏键静默落进缺省档。本席实跑现算抓到过：
            # 739 枚真字段里 578 枚报 `default:R2`，其中一大半本该被后缀模式接住。
            # 带 `^` 的模式在 `search` 下语义不变，`$` 仍由模式自己负责。
            if pattern.search(name):
                return tier
    return DEFAULT_TIER


def registry_source_for_target(target: object) -> str:
    """这枚键的档是从哪儿来的（``explicit:R2`` / ``pattern:R1`` / ``default:R2``）。

    回显与审计要能点名「按什么登记的」，否则一张「R2」的卡什么都解释不了。
    """
    name = normalize_target(target)
    if name.startswith(META_PREFIX):
        return "explicit:R3(meta)"
    for tier, registry in _EXPLICIT_REGISTRIES:
        if name in registry:
            return f"explicit:{tier.value}"
    for tier in TIER_CHECK_ORDER:
        for pattern in _COMPILED_TIER_PATTERNS[tier]:
            if pattern.search(name):  # 同上：后缀形模式在 `match` 下是死码
                return f"pattern:{tier.value}"
    return f"default:{DEFAULT_TIER.value}"


def is_explicitly_registered(target: object) -> bool:
    """是否被显式名单或模式族命中（缺省落档的不算）。覆盖率体检用。"""
    return not registry_source_for_target(target).startswith("default:")


def allows_unattended_change(target_or_tier: object) -> bool:
    """该目标（或该档）能否不问就改。**只有 R0 能**，且调用方还必须出示回退口。"""
    return _as_tier(target_or_tier) in UNATTENDED_CHANGE_TIERS


def requires_consent(target_or_tier: object) -> bool:
    """该目标（或该档）是否需要一次性同意/确认号。"""
    return _as_tier(target_or_tier) in CONSENT_REQUIRED_TIERS


def requires_written_consent(target_or_tier: object) -> bool:
    """是否需要**超管书面同意**（R2）。"""
    return _as_tier(target_or_tier) in WRITTEN_CONSENT_TIERS


def is_never_auto(target_or_tier: object) -> bool:
    """是否属于「永不自动」（R3，只出待审补丁）。"""
    return _as_tier(target_or_tier) in NEVER_AUTO_TIERS


def _as_tier(value: object) -> RiskTier:
    if isinstance(value, RiskTier):
        return value
    if isinstance(value, str):
        text = value.strip().upper()
        if text in {tier.value for tier in RiskTier}:
            return RiskTier(text)
        return risk_tier_for_target(text)
    raise TypeError(f"需要 RiskTier 或目标名，收到 {type(value).__name__}")


# ---------------------------------------------------------------------------
# 取值指纹与人话值（审计只存 sha256[:16]，明文密钥形态绝不上账）
# ---------------------------------------------------------------------------

FINGERPRINT_LENGTH = 16

#: 「把覆盖撤掉、回到 .env/代码缺省值」这一动作的**哨兵指纹**。
#:
#: 它必须与**任何真值的指纹都不相同**，否则「撤覆盖」与「把值改成某样东西」会撞成
#: 同一张同意卡。做法不是挑一个看起来没人用的字符串（那只是概率），而是
#: **域分隔**：`fingerprint_value` 只对 `canonical_json` 的产物取哈希，而 JSON 文本
#: 永远不可能以 `\x00` 开头 ⇒ 这一串前缀在值域之外，结构上不可能相撞。
#: 测试 `test_restore_default_sentinel_never_collides_with_a_real_value` 逐枚复算这条。
RESTORE_DEFAULT_SENTINEL = "__safetyexec_restore_default__"
RESTORE_DEFAULT_FINGERPRINT = hashlib.sha256(
    b"\x00" + RESTORE_DEFAULT_SENTINEL.encode("utf-8")
).hexdigest()[:FINGERPRINT_LENGTH]


def canonical_json(value: Any) -> str:
    """稳定序规范化：同一语义值在任何顺序/缩写下同一串字节，指纹才可复跑比对。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)


def fingerprint_value(value: Any) -> str:
    """值的指纹＝sha256(规范化 JSON)[:16]。**不落明文**——配置值里可能是 API key。

    ``allow_nan=False`` 是刻意的：``float('nan')`` 规范化出来的串不稳定，
    拿它算指纹会把「同一个值」判成两个值（同意绑定校验必假红）。
    """
    try:
        payload = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        payload = repr(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:FINGERPRINT_LENGTH]


def value_view(key: object, value: Any) -> dict[str, Any]:
    """审计/回显用的一枚值视图：``{display, sensitive, configured, fingerprint}``。

    凭证识别与打码**复用** ``control_plane.config_store`` 的既有真身（``is_sensitive`` /
    ``public_value``），本文件不另立第二套「什么算密钥」表。

    但**指纹只从本文件的 `fingerprint_value` 出**：`public_value` 自己那枚用的是
    `separators=(",", ":")` 的紧凑 JSON，与本件的 `canonical_json` 算出来是**两个
    不同的串**。曾经直接取它的那枚，后果是「同意卡上记的指纹」与「落地前复算的
    指纹」永不相等 ⇒ 所有敏感键的书面同意都在 `BINDING_MISMATCH` 上假红、改不下去。
    口径只准有一处，故这里显式覆盖，并在测试里钉死这条等式。
    """
    from plugins.bot_unified_runtime.control_plane.config_store import (  # 局部导入：避开 control_plane 的重依赖
        public_value,
    )

    name = key if isinstance(key, str) else str(key)
    view = public_value(name, value)
    return {
        "display": view["value"],
        "sensitive": bool(view["sensitive"]),
        "configured": bool(view["configured"]),
        "fingerprint": fingerprint_value(value),
    }


def short_fingerprint_or_none(value: Any) -> str:
    """给「未设置」留空形，其余一律出指纹（回显里 ``∅`` 由调用方决定怎么画）。"""
    if value is None:
        return ""
    return fingerprint_value(value)


__all__ = [
    "DEFAULT_TIER",
    "EXPLICIT_R0_KEYS",
    "EXPLICIT_R1_KEYS",
    "EXPLICIT_R2_KEYS",
    "EXPLICIT_R3_KEYS",
    "FINGERPRINT_LENGTH",
    "FORWARD_LOOKING_PATTERNS",
    "META_PREFIX",
    "META_R3_TARGETS",
    "META_R3_TARGET_SPEC_NAMES",
    "NEVER_AUTO_TIERS",
    "PENDING_CONFIG_KEY_PROPOSALS",
    "RESTORE_DEFAULT_FINGERPRINT",
    "RESTORE_DEFAULT_SENTINEL",
    "SAFETY_CRITICAL_TARGETS",
    "TIER_CHECK_ORDER",
    "UNATTENDED_CHANGE_TIERS",
    "WRITTEN_CONSENT_TIERS",
    "RiskTier",
    "allows_unattended_change",
    "canonical_json",
    "describe_tier",
    "fingerprint_value",
    "is_explicitly_registered",
    "is_never_auto",
    "normalize_target",
    "registry_source_for_target",
    "requires_consent",
    "requires_written_consent",
    "risk_tier_for_target",
    "safety_critical_tier_violations",
    "short_fingerprint_or_none",
    "value_view",
]
