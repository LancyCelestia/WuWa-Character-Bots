"""席 G1 尺①：「帮助册宣称集合 ⊆ 实装集合」门（悬空子令 / 悬空动词 / 登记键≠支配键 / 缺席 patch 件）。

**为什么再立一把**（起点取证＝`patches/G1-CLAIMS-GATE-20261002.md` §1，全部现算复跑）：
既有门管的是**词级**双向缺口（`tests/test_trigger_bidirectional_gate.py`、
`tests/test_trigger_matcher_ratchet.py`）与**在册与否**（`tests/test_capability_single_registration.py`）。
**没人管的那一格**＝「册上宣称的这条入口，敲下去到底有没有落点」：
`/bot decision` 四层登记齐全（动词表 / 帮助主题 / `_HELP_ENTRIES` / 命令规格清单），
而根分发链 `_handle_status` 的 `command_text` 分支里逐字查无 `decision`（本席现算＝零命中）
⇒ 命令教自己、永远停在帮助页。同族病在配置键面也有一格：`capability_registry.py` 的 WEATHER 行
（本席开工时读在 :390）申报 `config_keys=("bot_weather_enabled", "bot_weather_cache_seconds",
"bot_weather_timeout_seconds")`，其中 `bot_weather_cache_seconds` 在 `domains/weather/**` 全域
**零真读点**，读点住在 `domains/chat_reply/character/temporal.py`（＝人格侧环境注入那份天气的缓存；
板块册 `docs/boards/B05-external-data-services/weather/weather.md` 自己写着「不是本查询入口的」）
⇒ **登记键 ≠ 实际支配键**。

**这把尺判什么**（四腿＋一变瞎地板；全静态读源、全离线、不触网、不发消息、不碰 Runtime、不写盘）：
- 腿 A「悬空子令」：帮助册 `capability` 列宣称的每个 `/bot <子令>` 必须在**实装落点集**里。
  落点集三条腿，逐枚带出处（`landing_evidence()`）：
  E1 根分发链 `_handle_status` 里对 `command_text` 的字面比较；
  E2 生产面里形如 `^/bot\\s+X` 的**判定用正则**（只认 `re.compile/match/search/fullmatch/
  finditer/findall` 的字面模式实参，或赋给 `*_RE`/`*_PATTERN` 的常量）；
  E3 别名字册：模块级 `*_ALIASES`/`*_COMMAND_WORDS` 字面序列，且同模块持有以 `/bot` 打头的
  `*_PREFIX` 常量（先例＝`domains/core/credentials/platform_credentials.py` 的
  `_COMMAND_PREFIX` + `_COMMAND_ALIASES`，`/bot cookie` 就走这条路）。
  ⚠ **宣称面自身不给自己作证**：`echo.py`（帮助册真身）、`capability_registry.py`（声明表）、
  `aliases.py`（动词表）与 docstring/注释一律**不算落点**——否则「册子说在册」就自动成立，
  这把尺会退化成一枚摆设（本席首版就栽过一次：`decision` 被 trace.py 的 docstring 洗白）。
- 腿 B「无落点的能力宣称」：帮助册宣称的干净 `bot.*` 能力 id 必须在册且有落点
  （RouteRule `has_rule=True` ∪ `CONTROLLED_INTERNAL_CAPABILITIES` ∪ 管线管理形）。
- 腿 C「登记键 ⊆ 支配键」：`ROUTE_CAPABILITY_DECLARATIONS[*].execution.config_keys` 每一枚
  必须在该能力 `implementation_ref` 所属**域根**（`domains/<域>`）里有真读点
  （属性式 `config.<键>` 或 `getattr/hasattr(…, "<键>", …)` 字面量）。
  读点只在别家域＝「登记≠支配」；全树零读点＝幽灵登记，单独一档零容忍。
- 腿 D「被引用而缺席的 patch 件」：登记面（`AGENTS.md`/`COMMANDS.md`/`docs/**`/`HANDOFF-*.md`）
  写出来的 `patches/<件>.md` 必须在盘上。

**判据方向**（AGENTS 规则 10 / 台账 #68★）：违规名册按**现算**录存量、**只降不升**，
台账外新增即红；修好一条＝递减放行（不做等值冻结）。每腿各配**注毒腿**（内存内造违规，
绝不写盘）与**反向不误伤腿**，另有一枚 `test_ruler_is_not_blind` 量尺子自己：
宣称面/落点面/健康面数到零就红，防止扫描器塌了却「零违规」地绿。

**本席只建尺、不改帮助册**：`echo.py` 属别席独占面，违规项逐枚差分列进工单，
那张表本身就是交付物；不为凑绿下调判据、不上调基线。
"""

from __future__ import annotations

import ast
import re
import sys
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "bot_unified_runtime"
REGISTRY_PY = PLUGIN / "domains/chat_reply/runtime/capability_registry.py"
ROOT_INIT_PY = PLUGIN / "__init__.py"
ALIASES_PY = PLUGIN / "domains/chat_reply/runtime/aliases.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ↓ 以下这一段 import 有意置于 sys.path.insert 之后（中段 import＝E402 场景，逐枚意图见各自注释）。
# 字段集与"接收者是否 configish"两条口径都 import 自普查真身（禁在本席文件里另写一份正则）。
import scripts.config_read_point_census as census

# 腿 A 的**归一口**＝生产那一只（`__init__.py:8627` 在 if/elif 分发段之前就是调它）。
# 主会话 2026-10-08 裁定（席 CB-CMDUNIFY 把口径留给本席）：E1 字面集天生看不见中文词头，
# 判落点前先把宣称子令交这只**当场折一遍**——🔴 不是把 `MODULE_ALIASES` 抄进本席文件：
# 抄表＝第二真身，别名一改这尺立刻骗人；执行原文＝别名册是唯一事实源，折不折得动由它说了算。
# `aliases.py` 仍在 `_CLAIM_SIDE`（不作取证出处），这里只借它的**函数**，不借它的**词表**。
from plugins.bot_unified_runtime.domains.chat_reply.runtime.aliases import (
    normalize_command_text as _production_normalize,
)

# 配置键申报的第二条通路＝真身册（S186 收编波定的单一真身）。只 import 求值，不抄清单。
from plugins.bot_unified_runtime.domains.core.capability_manifest import (
    FACETS,
    config_keys_for,
)

# 悬空动词的既有台账＝唯一真身，本席只 import、不复制（禁第二本账）。
# ⚠ 照实报备一条副作用：这次 import 会连带装配插件包——`capability_registry` 文件头注自陈
# 「经包路径 import 该叶子会执行父包 __init__.py（其顶层 import nonebot）」，先例＝
# `tests/test_trigger_matcher_ratchet.py` 本身。本尺四条判据腿全部静态读源，不依赖该装配。
from tests.test_trigger_matcher_ratchet import (
    DANGLING_VERB_CAPABILITIES_BASELINE,
    _dangling_verb_capabilities,
)

# ---------------------------------------------------------------------------
# 违规基线（席 G1 · 2026-10-02 现算复录；逐枚读数与出处见本席工单 §2）
# ---------------------------------------------------------------------------

#: 腿 A 存量：册上宣称、E1/E2/E3 皆无落点的 `/bot` 子令。
#: 2026-10-08 席 CB-CMDUNIFY 清账：`decision` 已随 G-2（乙）在 `_handle_status` 接上
#: 分发支（复用 logs 分支同构先例），本基线归零。
#: 2026-10-08 主会话裁定（席把口径留给本席）：`描写` 那枚**不是**册子骗人——链上 `narration`
#: 支真在，是 E1 看不见中文词头＝尺瞎。修法给判据补归一腿（`_landing_candidates`，执行生产
#: `normalize_command_text` 原文），**基线一字未动、仍为空**：没把任何真悬空项登记成豁免，
#: 今后新造一枚没牙的中文词头照样当场红（牙口锁＝`test_alias_fold_leg_never_launders_a_headless_subcommand`）。
DANGLING_SUBCOMMAND_BASELINE: frozenset[str] = frozenset()

#: 腿 B 存量：册上宣称却无在册落点的能力 id。现算起点＝0 枚 ⇒ 零档硬口径，新增即红。
UNLANDED_CAPABILITY_CLAIM_BASELINE: frozenset[str] = frozenset()

#: 腿 C 存量：申报了、但该能力自家域根内零真读点的键。现算起点＝13 枚（2026-10-02）。
#: 逐枚「真读点实际住在哪家」见工单 §2-C；其中 `bot.weather::bot_weather_cache_seconds`
#: ＝简报点名的 `capability_registry:390` 那一格（`domains/chat_reply/character/temporal.py:408`
#: 才支配它，而板块册自己写着这枚键"不是本查询入口的"）。
DECLARED_KEY_NOT_GOVERNED_BASELINE: frozenset[tuple[str, str]] = frozenset(
    {
        ("bot.bond", "bot_bond_enabled"),
        ("bot.commodities", "bot_commodities_enabled"),
        ("bot.daily_assist", "bot_daily_assist_enabled"),
        ("bot.divination", "bot_divination_enabled"),
        ("bot.eat", "bot_eat_enabled"),
        ("bot.epic", "bot_epic_enabled"),
        ("bot.fx", "bot_fx_enabled"),
        ("bot.market", "bot_market_enabled"),
        ("bot.northbound", "bot_northbound_enabled"),
        ("bot.reminder", "bot_reminder_enabled"),
        ("bot.stocks", "bot_stocks_enabled"),
        ("bot.weather", "bot_weather_cache_seconds"),
        ("bot.weather", "bot_weather_enabled"),
    }
)

#: 腿 C 更严一档：全树零读点的幽灵登记。现算起点＝0 枚 ⇒ 零档硬口径，新增即红。
#: （本席首版把 24 枚真读点误判成幽灵，根因是 `getattr` 直呼形漏认——见 `key_reads_in` 的盲区史注。）
GHOST_DECLARED_KEY_BASELINE: frozenset[tuple[str, str]] = frozenset()

#: 腿 G 存量：把 `config_keys` **字面抄进 registry**（绕过真身册 `config_keys_for`）的能力行。
#: 现算起点＝17 行（真身册覆盖者 0 行 ⇒ 今天还没有"同一枚能力两处声明"的实锤，
#: 但 17 行都属"册子之外的第二处声明"，按 #68★ 只降不升点名入账，本席不动 registry）。
DECLARED_KEYS_LITERAL_BYPASS_BASELINE: frozenset[str] = frozenset(
    {
        "bot.affinity", "bot.bond", "bot.commodities", "bot.divination", "bot.eat",
        "bot.emergency_info", "bot.epic", "bot.fx", "bot.ignore", "bot.market",
        "bot.meme", "bot.music_mode", "bot.news", "bot.northbound", "bot.stocks",
        "bot.weather", "bot.wiki",
    }
)


#: 腿 D 存量：登记面引用而 `patches/` 盘上缺席的件名。现算起点＝7 枚（逐枚见工单 §2-D）。
#: ⚠ 简报正文写的「19 枚」在本席两把尺下都没复现：登记面口径现算 7、全树（含 `.superpowers/`
#: 与 `pins/` 历史归档、允许同目录解析）现算 172。照实记两个读数——「我没数到」≠「它没有」
#: （台账 #51★），检索命令原文写在工单 §2-D。
MISSING_PATCH_REFERENCE_BASELINE: frozenset[str] = frozenset(
    {
        "G19R-T1-chat-wiring.patch.md",
        "S-RULING-LINT-TAIL3-20260929.md",
        "S-T8B2-RESTORE-DEFAULT-MERGE-20260929.md",
        "S-T8B3-IMAGERY-VARIETY-DIMENSION.md",
        "W2-PROXY-ABC-OPS-20260930.md",
        "s897-tamper-legs.md",
        "s900-name-lock.md",
    }
)

#: 变瞎地板：现算起点值（2026-10-02 席 G1 复录，尺＝本件 `current_readings()`）。
#: 低于它＝取数口塌陷/被掏空，此刻的「零违规」不作数。方向＝只准升；
#: 正当减少（撤了主题、退了能力）必须**同批把地板降到实况并留一行归属注**，
#: 口径照 `tests/test_config_key_registration_ledger.py::CORPUS_FLOOR_BASELINE` 的先例
#: （地板落后真值时，容差会把检测力吃掉——那门自己记过两回）。
RULER_FLOORS: tuple[tuple[str, int], ...] = (
    ("帮助主题行数", 83),
    ("E1 分发链字面数", 32),
    ("E2 判定正则词头数", 6),
    ("E3 别名字册词头数", 7),
    ("子令宣称枚数（去重）", 20),
    ("能力 id 宣称枚数", 46),
    ("execution 申报键枚数", 39),
    ("自家域有真读点的申报键枚数", 26),
    ("在册落点能力数", 78),
)


_CLAIM_SIDE = {
    REGISTRY_PY.relative_to(PLUGIN).as_posix(),
    "domains/chat_reply/capabilities/echo.py",
    "domains/chat_reply/runtime/aliases.py",
}
_NON_PRODUCTION = ("domains/ops/smoke/",)
_RE_FUNCS = frozenset({"compile", "match", "search", "fullmatch", "finditer", "findall"})
_ALIAS_TABLE = re.compile(r"_(?:COMMAND_)?ALIASES$|_COMMAND_WORDS$")
_PATTERN_TABLE = re.compile(r"_(?:RE|PATTERN)$")
_PREFIX_TABLE = re.compile(r"_PREFIX$")
_SUB_IN_TEXT = re.compile(r"/bot\s+([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff-]*)")
_CLEAN_CAP_RX = re.compile(r"^(?:bot|media|creation|search)\.[a-z0-9_.]+$")
_PATCH_REF_RX = re.compile(r"patches/([A-Za-z0-9_.\-]+\.md)")

# 正则字面 → 可读文本的机械归一（只做"把转义塌成空格、把分组外壳与交替符剥掉"，
# 不猜语义：归一后再用同一把 `/bot\s+X` 尺取词头，E1/E2/E3 与宣称面共用这一条通路）。
_NORMALIZE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\(\?:([^|)]*)\|[^)]*\)"), r"\1"),  # (?:a|b) → a（其余臂由 E3 别名字册另行取证）
    (re.compile(r"[\[\]\(\)]"), " "),
    (re.compile(r"\\[sSwWdDbB].?"), " "),
    (re.compile(r"[+*?^$]"), " "),
    (re.compile(r"\s+"), " "),
)


def normalize_pattern_text(text: str) -> str:
    out = text
    for rx, rep in _NORMALIZE:
        out = rx.sub(rep, out)
    return out


def heads_from_text(text: str) -> set[str]:
    """从（正则或散文）文本里取 `/bot <词头>` 词头，统一小写。"""
    found: set[str] = set()
    for source in (text, normalize_pattern_text(text)):
        for match in _SUB_IN_TEXT.finditer(source):
            token = match.group(1).strip().lower()
            if token and not token.startswith(("\\", "/", "|")):
                found.add(token)
    return found


def subcommand_head(full: str) -> str:
    return full.strip().lower().split(" ")[0]


# ---------------------------------------------------------------------------
# 取数（全部只读；每棵子树 parse 一次，进程内缓存）
# ---------------------------------------------------------------------------
def _parse(path: Path) -> ast.Module:
    """静默 parse：被扫源文件里的 `\\S` 一类转义会吐 SyntaxWarning，本尺不替别人修文案。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(path.read_text(encoding="utf-8-sig"))


def _assign_view(node: ast.AST) -> tuple[str | None, ast.expr | None]:
    """把 `x = …` 与 `x: T = …` 折成 (名字, 值表达式)。"""
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id, node.value
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    return None, None


def _table(tree: ast.Module, name: str) -> list[ast.Call]:
    for node in ast.walk(tree):
        target, value = _assign_view(node)
        if target == name and isinstance(value, (ast.Tuple, ast.List)):
            return [element for element in value.elts if isinstance(element, ast.Call)]
    return []


def _kw(call: ast.Call, key: str) -> Any:
    for item in call.keywords:
        if item.arg == key:
            try:
                return ast.literal_eval(item.value)
            except (ValueError, TypeError):
                return ast.unparse(item.value)
    return None


def _docstring_lines(tree: ast.Module) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            out.add(body[0].value.lineno)
    return out


def startswith_head_literals(node: ast.AST) -> list[str]:
    """E1 取数口：`command_text.startswith(…)` 的**字面量**，单串形与元组/列表/集合形都逐个交出。

    ⚠ 口径＝逐个比字面量，不是「见到 startswith 就算落点」：元组里每一枚都单独进集，
    摘掉或改掉任一枚 ⇒ 那枚词头当场从 E1 消失（注毒腿
    `test_poison_tuple_form_head_literals_are_compared_individually` 执法）。
    先例同尺＝`tests/test_trigger_bidirectional_gate.py::command_text_literal_heads`（已认元组形）。
    非字面量（变量、`f-string`、函数调用）一律不交——否则一句 `startswith(prefixes)` 就能替悬空命令作证。
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return []
    if node.func.attr != "startswith" or not isinstance(node.func.value, ast.Name):
        return []
    if node.func.value.id != "command_text" or not node.args:
        return []
    first = node.args[0]
    if isinstance(first, ast.Constant):
        return [first.value] if isinstance(first.value, str) else []
    if isinstance(first, (ast.Tuple, ast.List, ast.Set)):
        return [
            element.value for element in first.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


@lru_cache(maxsize=1)
def dispatch_literals() -> tuple[frozenset[str], frozenset[str]]:
    """E1：根 `_handle_status` 里对 `command_text` 的字面比较 → (整串字面, 词头)。"""
    tree = _parse(ROOT_INIT_PY)
    handler = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_status"),
        None,
    )
    if handler is None:  # 装配函数改名＝本腿失去对象，由变瞎地板打红，不留"零违规"
        return frozenset(), frozenset()
    full: set[str] = set()
    heads: set[str] = set()
    for node in ast.walk(handler):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "command_text":
            for op, comp in zip(node.ops, node.comparators, strict=False):
                if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant) \
                        and isinstance(comp.value, str):
                    literal = comp.value.strip().lower()
                    full.add(literal)
                    heads.add(subcommand_head(literal))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "startswith" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "command_text":
            for literal in startswith_head_literals(node):
                heads.add(subcommand_head(literal))
    return frozenset(full), frozenset(heads)


def pattern_landing(tree: ast.Module, rel: str) -> tuple[dict[str, set[str]], set[str], bool]:
    """一棵树里的判定用落点：返回 (词头→出处, 别名字册词头, 是否持有 /bot 前缀常量)。

    排除口径写死在这里（宣称面/冒烟面在调用处再排）：
    docstring 行、`config.py` 一律不认——否则「trace.py 的 docstring 写着 /bot decision」
    就能给一条没有分支的命令自己作证（本席首版实栽过，见工单 §4）。
    """
    found: dict[str, set[str]] = {}
    alias_bucket: set[str] = set()
    has_prefix_constant = False

    def add(token: str, site: str) -> None:
        found.setdefault(token, set()).add(site)

    docstrings = _docstring_lines(tree)
    for node in ast.walk(tree):
        name, value = _assign_view(node)
        if name is None or value is None:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if value.value.strip().lower().startswith("/bot"):
                has_prefix_constant = True
            if (_PATTERN_TABLE.search(name) or _PREFIX_TABLE.search(name)) \
                    and value.lineno not in docstrings:
                for token in heads_from_text(value.value):
                    add(token, f"{rel}::{name}")
        elif _PATTERN_TABLE.search(name) and isinstance(value, ast.Call):
            first = value.args[0] if value.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                for token in heads_from_text(first.value):
                    add(token, f"{rel}::{name}")
        if _ALIAS_TABLE.search(name) and isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    alias_bucket.add(element.value.strip().lower())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _RE_FUNCS or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        if first.lineno in docstrings or "/bot" not in first.value:
            continue
        for token in heads_from_text(first.value):
            add(token, f"{rel}:{first.lineno}")
    return found, alias_bucket, has_prefix_constant


@lru_cache(maxsize=1)
def landing_evidence() -> dict[str, tuple[str, ...]]:
    """E2/E3：生产面里**判定用**的 `/bot X` 落点，逐枚词头带出处。

    排除面（防"册子给自己作证"）：宣称面三件（echo / registry / aliases）、
    冒烟脚本面 `domains/ops/smoke/`、docstring 与 `config.py`；`tests/`、`scripts/`
    根本不在 `PLUGIN` 子树下，天然不进。
    """
    evidence: dict[str, set[str]] = {}
    for path in sorted(PLUGIN.rglob("*.py")):
        rel = path.relative_to(PLUGIN).as_posix()
        if rel in _CLAIM_SIDE or rel.startswith(_NON_PRODUCTION) or path.name == "config.py":
            continue
        try:
            tree = _parse(path)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        found, alias_bucket, has_prefix_constant = pattern_landing(tree, rel)
        for token, sites in found.items():
            evidence.setdefault(token, set()).update(sites)
        if has_prefix_constant:
            for token in alias_bucket:
                evidence.setdefault(token, set()).add(f"{rel}::_ALIAS_TABLE")
    return {token: tuple(sorted(sites)) for token, sites in sorted(evidence.items())}



@lru_cache(maxsize=1)
def pattern_heads() -> frozenset[str]:
    """E2 词头：出处不带 `_ALIAS_TABLE` 后缀的那些（正则/常量取证）。"""
    return frozenset(
        token for token, sites in landing_evidence().items()
        if any("_ALIAS_TABLE" not in site for site in sites)
    )


@lru_cache(maxsize=1)
def alias_heads() -> frozenset[str]:
    """E3 词头：由别名字册取证的那些。"""
    return frozenset(
        token for token, sites in landing_evidence().items()
        if any("_ALIAS_TABLE" in site for site in sites)
    )


@lru_cache(maxsize=1)
def help_claims() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """宣称面：(topic → `/bot` 子令整串, topic → 干净能力 id)。"""
    tree = _parse(REGISTRY_PY)
    subs: dict[str, list[str]] = {}
    caps: dict[str, list[str]] = {}
    for call in _table(tree, "HELP_TOPIC_DECLARATIONS"):
        topic = str(_kw(call, "topic") or "")
        capability = str(_kw(call, "capability") or "").strip()
        if _CLEAN_CAP_RX.fullmatch(capability):
            caps.setdefault(topic, []).append(capability)
            continue
        heads = [m.group(1).strip().lower() for m in _SUB_IN_TEXT.finditer(capability)]
        if heads:
            subs.setdefault(topic, []).extend(heads)
    return subs, caps


@lru_cache(maxsize=1)
def registered_landing() -> frozenset[str]:
    """在册落点集：RouteRule(has_rule) ∪ 受控内部能力 ∪ 管线管理形。"""
    tree = _parse(REGISTRY_PY)
    caps = {
        str(_kw(call, "capability_id"))
        for call in _table(tree, "ROUTE_CAPABILITY_DECLARATIONS")
        if _kw(call, "has_rule") is True
    }
    for node in ast.walk(tree):
        name, value = _assign_view(node)
        if not isinstance(value, (ast.Tuple, ast.List)):
            continue
        if name == "CONTROLLED_INTERNAL_CAPABILITIES":
            caps |= {str(ast.literal_eval(element)) for element in value.elts}
        if name == "PIPELINE_MANAGED_CAPABILITY_DECLARATIONS":
            for element in value.elts:
                if isinstance(element, ast.Call):
                    caps.add(str(_kw(element, "capability_id")))
    return frozenset(caps)


@lru_cache(maxsize=1)
def config_field_names() -> frozenset[str]:
    """Config 字段真身＝`scripts.config_read_point_census.config_fields()`（AST 静态、零副作用）。"""
    return frozenset(census.config_fields())


def key_reads_in(tree: ast.Module, wanted: set[str], rel: str = "") -> set[str]:


    """本文件里以**值路径**碰过这些键（三形皆认，见下方形状口径）。

    形状口径**刻意比 `scripts.config_read_point_census` 的直读尺更宽**，且这只回答一个问题：
    「本能力自家域碰没碰过这枚键」。真身的直读账在
    `tests/test_config_key_registration_ledger.py`（五桶 + 硬死名册），本席不另立一本、
    也不替它改桶基线；这里只需要一枚"有没有人真读过"的宽尺——窄了会把真读点判成幽灵。
    - 属性式 `cfg.bot_x`（含 `self.config.bot_x`）；
    - `getattr/hasattr(<任意接收者>, "bot_x", …)` 字面量形（直呼形是 `ast.Name`，
      不是 `ast.Attribute`——本席首版只认后者，把 26 枚真读点全判成零读点，注毒腿与
      现算复跑推翻后才改对；这条留在代码里当**这把尺的盲区史**）；
    - 任意调用里「configish 接收者 + 该键名字面量」成对出现（转名形态，先例
      `domains/schedule/capabilities/schedule_board.py:250` 的 `_flag(config, "bot_schedule_enabled", False)`）。
    键名**只在名单/表里字面在场**（热改台账、文档串、注释）不算——那是"不静默"，不是"值被消费"。
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in wanted:
            found.add(node.attr)
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        direct = isinstance(func, ast.Name) and func.id in {"getattr", "hasattr"}
        dotted = isinstance(func, ast.Attribute) and func.attr in {"getattr", "hasattr"}
        if (direct or dotted) and len(node.args) >= 2 \
                and isinstance(node.args[1], ast.Constant) and node.args[1].value in wanted:
            found.add(str(node.args[1].value))
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value in wanted and census._is_configish(node.args[0], rel):
            found.add(str(node.args[1].value))
    return found




@lru_cache(maxsize=1)
def domain_root_reads() -> dict[str, dict[str, list[str]]]:
    """域根（`domains/<域>`；非 domains 顶层取一段）→ 该域内每枚键的真读点出处。"""
    wanted = set(config_field_names())
    per_domain: dict[str, dict[str, list[str]]] = {}
    for path in sorted(PLUGIN.rglob("*.py")):
        if path.name == "config.py":
            continue
        rel = path.relative_to(PLUGIN).as_posix()
        parts = rel.split("/")
        domain = "/".join(parts[:2]) if parts[0] == "domains" else parts[0]
        try:
            tree = _parse(path)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for key in key_reads_in(tree, wanted, rel):
            per_domain.setdefault(domain, {}).setdefault(key, []).append(rel)
    return per_domain


def read_anywhere_keys() -> set[str]:
    """「这枚键在 plugins 面被人真读过没有」——本席宽尺的并集（比 census 直读尺更宽，
    故只会**少**判幽灵、不会多判）。全树直读账的真身仍在
    `tests/test_config_key_registration_ledger.py`，本腿不替它改桶基线。
    """
    return {key for per_key in domain_root_reads().values() for key in per_key}



@lru_cache(maxsize=1)
def execution_rows() -> tuple[tuple[str, str, tuple[str, ...], bool], ...]:
    """逐枚执行面行：(能力 id, 自家域根, 申报键, 是否走真身册 config_keys_for)。

    两条申报通路都收：
    - 字面元组 `config_keys=("bot_x", ...)`——本席静态读出；
    - 真身册 `config_keys=config_keys_for("bot.x")`——按册求值（`capability_manifest` 是
      S186 收编波定的**单一真身**，本席不另抄一份键清单）。
    """
    tree = _parse(REGISTRY_PY)
    rows: list[tuple[str, str, tuple[str, ...], bool]] = []
    for call in _table(tree, "ROUTE_CAPABILITY_DECLARATIONS"):
        capability = str(_kw(call, "capability_id"))
        execution = next((k.value for k in call.keywords if k.arg == "execution"), None)
        if execution is None:
            continue
        raw = _kw(execution, "config_keys")
        via_manifest = isinstance(raw, str) and raw.startswith("config_keys_for(")
        if via_manifest:
            keys = tuple(config_keys_for(capability))
        elif isinstance(raw, (list, tuple)):
            keys = tuple(str(item) for item in raw)
        else:
            continue
        ref = str(_kw(execution, "implementation_ref") or "")
        rel = ref.split("#")[0].strip().removeprefix("plugins/bot_unified_runtime/")
        parts = rel.split("/")
        domain = "/".join(parts[:2]) if parts[0] == "domains" else (parts[0] if parts else "")
        rows.append((capability, domain, keys, via_manifest))
    return tuple(rows)


def declared_keys() -> tuple[tuple[str, str, str], ...]:
    """(能力 id, 申报键, 该能力 execution 真身所属域根)——两条申报通路都算宣称。"""
    return tuple(
        (capability, key, domain)
        for capability, domain, keys, _via in execution_rows()
        for key in keys
    )


def literal_bypass_rows() -> frozenset[str]:
    """绕过真身册、把键清单**字面抄在 registry 里**的能力（第二真身存量）。"""
    return frozenset(capability for capability, _d, _k, via in execution_rows() if not via)


def manifest_covered_ids() -> frozenset[str]:
    return frozenset(FACETS)



@lru_cache(maxsize=1)
def verb_capability_ids() -> frozenset[str]:
    """动词轴宣称面：`aliases.DEFAULT_VERB_MAP` 的值集（静态读，不依赖插件装配）。"""
    tree = _parse(ALIASES_PY)
    for node in ast.walk(tree):
        name, value = _assign_view(node)
        if name == "DEFAULT_VERB_MAP" and isinstance(value, ast.Dict):
            return frozenset(
                str(ast.literal_eval(v))
                for k, v in zip(value.keys, value.values, strict=True)
                if isinstance(v, ast.Constant)
            )
    return frozenset()


# ---------------------------------------------------------------------------
# 判据本体（纯函数：喂合成集即可测牙口，不碰磁盘）
# ---------------------------------------------------------------------------
def landed_subcommand_set() -> dict[str, set[str]]:
    full, heads = dispatch_literals()
    return {"full": set(full), "heads": set(heads) | set(landing_evidence())}


def _landing_candidates(sub: str) -> tuple[str, ...]:
    """宣称子令在 root 链上**真会被拿去比对的形**：原文一枚 ＋ 经生产归一口折过的一枚。

    2026-10-08 的假红本体：`描写` 在册上教用户敲（topic＝亲密模式），链上 `narration` 支
    也真在（`__init__.py:8983`），但 E1 只收 `command_text` 的字面比较 ⇒ 中文词头永远
    比不中 ⇒ 判成"册子教了一枚没牙的命令"。根链实际比对的是**归一后**的 `command_text`
    （`:8627`），所以本腿也照这条走：折得动且折后的形有落点 ⇒ 有牙。
    🔴 折不动的（`描写zzz`）照旧悬空——归一口不认它，就没有"顺手放宽"这回事。
    """
    raw = str(sub or "").strip().lower()
    folded = _production_normalize(raw)
    return (raw,) if folded == raw else (raw, folded)


def is_landed(full: str, landed: dict[str, set[str]] | None = None) -> bool:
    pool = landed or landed_subcommand_set()
    for candidate in _landing_candidates(full):
        if candidate in pool["full"] or subcommand_head(candidate) in pool["heads"]:
            return True
    return False


def dangling_subcommands(claims: dict[str, list[str]]) -> dict[str, list[str]]:
    """腿 A：topic → 无落点子令整串。"""
    pool = landed_subcommand_set()
    return {
        topic: sorted({sub for sub in subs if not is_landed(sub, pool)})
        for topic, subs in claims.items()
        if any(not is_landed(sub, pool) for sub in subs)
    }


def unlanded_capability_claims(caps: dict[str, list[str]], registered: set[str]) -> set[str]:
    """腿 B：册上宣称的干净能力 id 里，在册落点集合之外的。"""
    return {cap for group in caps.values() for cap in group if cap not in registered}


def ungoverned_declared_keys(
    rows: list[tuple[str, str, str]],
    reads: dict[str, dict[str, list[str]]],
    read_anywhere: set[str] | None = None,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """腿 C 判据本体：返回 (自家域零读点但**别处**有读点, 全树零读点＝幽灵档)。

    `read_anywhere` 缺省时按 `reads` 的并集算（喂合成集时即自洽）；真树调用一律传
    `census_direct_reads()` 的键集——**全树有没有人读这枚键**只认普查直读尺那一条边，
    不在本席文件里另立第二把（`scripts/` 与 `bot.py` 面上的读点由它罩着）。
    """
    not_governed: set[tuple[str, str]] = set()
    ghost: set[tuple[str, str]] = set()
    anywhere = read_anywhere if read_anywhere is not None else {
        key for per_key in reads.values() for key in per_key
    }
    for capability, key, domain in rows:
        if reads.get(domain, {}).get(key):
            continue
        (not_governed if key in anywhere else ghost).add((capability, key))
    return not_governed, ghost



def missing_patch_references(register_paths: list[Path]) -> set[str]:
    """腿 D：登记面写出来、盘上却缺席的 patch 件名。"""
    patch_dir = ROOT / "patches"
    present = {p.name for p in patch_dir.glob("*.md")} if patch_dir.is_dir() else set()
    missing: set[str] = set()
    for path in register_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _PATCH_REF_RX.finditer(text):
            if match.group(1) not in present:
                missing.add(match.group(1))
    return missing


def register_surface() -> list[Path]:
    out = [ROOT / "AGENTS.md", ROOT / "COMMANDS.md"]
    out += sorted((ROOT / "docs").rglob("*.md"))
    out += sorted(ROOT.glob("HANDOFF-*.md"))
    return [p for p in out if p.exists()]


def ratchet_report(current: set, ceiling: frozenset) -> tuple[list, int]:
    """棘轮判定：(台账/基线外新增项, 规模超出量)。两者皆空/非正即绿。"""
    return sorted(current - set(ceiling)), len(current) - len(ceiling)


def current_readings() -> dict[str, object]:
    """现算读数（工单 §2 差分表与本门复跑读数都读这里，别让散文各自抄一份）。"""
    subs, caps = help_claims()
    gaps = dangling_subcommands(subs)
    rows = list(declared_keys())
    reads = domain_root_reads()
    anywhere = read_anywhere_keys()
    not_governed, ghost = ungoverned_declared_keys(rows, reads, anywhere)
    full, heads = dispatch_literals()
    bypass = literal_bypass_rows()

    return {
        "help_topic_rows": len(_table(_parse(REGISTRY_PY), "HELP_TOPIC_DECLARATIONS")),
        "e1_full": len(full),
        "e1_heads": len(heads),
        "e2_heads": len(pattern_heads()),
        "e3_heads": len(alias_heads()),
        "subcommand_claims": len({s for group in subs.values() for s in group}),
        "capability_claims": sum(len(v) for v in caps.values()),
        "declared_key_rows": len(rows),
        "governed_key_rows": len({(c, k) for c, k, d in rows if reads.get(d, {}).get(k)}),
        "registered_landing": len(registered_landing()),
        "dangling_subcommands": sorted(s for group in gaps.values() for s in group),
        "dangling_detail": {t: v for t, v in sorted(gaps.items())},
        "unlanded_capability_claims": sorted(unlanded_capability_claims(caps, set(registered_landing()))),
        "declared_not_governed": sorted(f"{c}::{k}" for c, k in not_governed),
        "ghost_declared_keys": sorted(f"{c}::{k}" for c, k in ghost),
        "missing_patch_references": sorted(missing_patch_references(register_surface())),
        "literal_bypass_rows": sorted(bypass),
        "literal_row_covered_by_manifest": sorted(
            c for c, _d, _k, via in execution_rows() if not via and c in manifest_covered_ids()
        ),
    }



# ---------------------------------------------------------------------------
# 常驻判据
# ---------------------------------------------------------------------------
def test_ruler_is_not_blind() -> None:
    """先量尺子自己：宣称面/落点面/健康面数到零＝扫描塌了，此刻的"零违规"不作数。"""
    readings = current_readings()
    counters = dict(readings)
    for label, floor in RULER_FLOORS:
        key = {
            "帮助主题行数": "help_topic_rows",
            "E1 分发链字面数": "e1_full",
            "E2 判定正则词头数": "e2_heads",
            "E3 别名字册词头数": "e3_heads",
            "子令宣称枚数（去重）": "subcommand_claims",
            "能力 id 宣称枚数": "capability_claims",
            "execution 申报键枚数": "declared_key_rows",
            "自家域有真读点的申报键枚数": "governed_key_rows",
            "在册落点能力数": "registered_landing",
        }[label]
        got = int(counters[key])
        assert got >= floor, (
            f"{label} 现算 {got} < 地板 {floor} ⇒ 取数口塌陷/被掏空，本门『零违规』读数不成立"
        )


def test_dangling_subcommands_decreasing_ratchet() -> None:
    """腿 A：悬空 `/bot` 子令只准减；台账外新增即红（多一条＝册上又多一枚教自己回帮助页的命令）。"""
    subs, _caps = help_claims()
    gaps = dangling_subcommands(subs)
    current = {sub for group in gaps.values() for sub in group}
    new_items, delta = ratchet_report(current, DANGLING_SUBCOMMAND_BASELINE)
    assert not new_items, (
        f"新增悬空 `/bot` 子令（E1 分发链/E2 判定正则/E3 别名字册皆无落点）：{new_items}"
        f"｜现算全量：{gaps}"
    )
    assert delta <= 0, (
        f"悬空子令规模越界（现算 {len(current)} > 基线 {len(DANGLING_SUBCOMMAND_BASELINE)}）"
    )


def test_decision_is_wired_and_must_not_return_to_dangling() -> None:
    """实证锁（G-2 乙接线后的翻正版，原条文自述"届时翻正成活性锁"）：
    `decision` 必须**有** E1 落点，且不得再回到悬空集——撤了接线这枚就红。"""
    subs, _caps = help_claims()
    gaps = dangling_subcommands(subs)
    current = {sub for group in gaps.values() for sub in group}
    assert "decision" not in current, (
        "`decision` 又悬空了＝分发支被摘掉 ⇒ /bot decision 重新变成手册骗人"
    )
    full, heads = dispatch_literals()
    assert "decision" in full and "decision" in heads, (
        f"E1 不再认 decision（full={sorted(full)[:0]}…）⇒ 接线缺席"
    )
    assert "决策" in full or "决策" in heads, "中文词头那支不见了＝/bot 决策 重新坠兜底"


def test_alias_fold_leg_never_launders_a_headless_subcommand() -> None:
    """腿 A 的牙口（归一腿两向自证；合成落点面，不碰磁盘、不靠"全绿"自证）。

    给判据补一条腿＝必须同时证明它**咬得住**，否则今天消掉的这枚红只是把尺子磨钝：

    - 正向不误伤：`描写` 折成 `narration`、链上支真在 ⇒ 不许判悬空。
    - 折不动的假词头（`描写zzz`）照旧悬空——归一口不认它就没有"顺手放宽"。
    - 🔴 真格子：把 `narration` 从落点面抽掉（＝哪天那支被摘），`描写` **必须立刻**
      回到悬空集。这条才是"归一腿只借真落点、不自我发证"的证明。
    """
    pool = landed_subcommand_set()
    assert "narration" in pool["heads"], "E1 的 narration 支不见了＝本腿前提失效（先去查接线）"
    assert not dangling_subcommands({"归一腿": ["描写", "描写 speech"]}), "真接上的中文词头被误判悬空"

    assert not is_landed("描写zzz speech", pool), "折不动的词头被判有牙＝归一腿在自我发证"
    assert not is_landed("zzzfabricated", pool), "假词头池子塌了，本腿其实什么都没比"

    hollowed = {
        "full": set(pool["full"]) - {"narration"},
        "heads": set(pool["heads"]) - {"narration"},
    }
    assert not is_landed("描写", hollowed), (
        "把 narration 分支抽掉后 `描写` 仍判有牙 ⇒ 归一腿绕过了真落点面，这尺已经瞎了"
    )
    assert is_landed("描写", pool), "同一枚词头在真落点面下必须有牙（两向只差在落点面本身）"


def test_unlanded_capability_claims_are_zero_tolerance() -> None:
    """腿 B：册上宣称的 `bot.*` 能力必须全部在册有落点。起点 0 枚 ⇒ 新增即红，无豁免档。"""
    _subs, caps = help_claims()
    current = unlanded_capability_claims(caps, set(registered_landing()))
    new_items, _delta = ratchet_report(current, UNLANDED_CAPABILITY_CLAIM_BASELINE)
    assert not new_items, (
        f"帮助册宣称了却无在册落点的能力 id：{new_items}"
        "｜处置＝接 RouteRule / 登记 CONTROLLED_INTERNAL_CAPABILITIES / 撤册，三选一，"
        "不许留悬空宣称（fail-closed 先例见 capability_registry F3 注：未登记即被『暂时不可用』吞掉）"
    )


def test_declared_config_keys_are_governed_in_own_domain() -> None:
    """腿 C：`execution.config_keys` 申报的键必须由该能力**自家域**真读。

    读点只在别家域＝「登记键 ≠ 实际支配键」（简报点名的 `capability_registry:390` 那一格）；
    全树零读点＝幽灵登记，单独一档零容忍。存量 13 枚按现算录基线、只降不升。
    """
    rows = list(declared_keys())
    reads = domain_root_reads()
    anywhere = read_anywhere_keys()
    not_governed, ghost = ungoverned_declared_keys(rows, reads, anywhere)
    new_items, delta = ratchet_report(not_governed, DECLARED_KEY_NOT_GOVERNED_BASELINE)

    assert not new_items, (
        f"新出现「申报键不在自家域读」的 (能力, 键)：{new_items}"
        "｜处置＝把真读点接进本域，或把这枚键从 execution.config_keys 撤下——"
        "别拿别人家的键冒充本能力的执行面（键名清单会进 feature gate 绑定与同意卡的风险档）"
    )
    assert delta <= 0, (
        f"登记≠支配规模越界（现算 {len(not_governed)} > 基线 "
        f"{len(DECLARED_KEY_NOT_GOVERNED_BASELINE)}）"
    )
    ghost_new, ghost_delta = ratchet_report(ghost, GHOST_DECLARED_KEY_BASELINE)
    assert not ghost_new and ghost_delta <= 0, (
        f"幽灵登记的配置键（在册却全树零读点＝账面假账）：{ghost_new or sorted(ghost)}"
    )


def test_config_key_declaration_has_one_authority() -> None:
    """腿 G（单一真身并锁）：执行面的键清单只准住在 `capability_manifest.FACETS` 一處。

    S186 收编波已定：`execution.config_keys` / `PipelineManagedExecution.config_keys`
    两处**改由 `config_keys_for(id)` 现读**（真身＝`domains/core/capability_manifest.py::FACETS`）。
    本席现算：registry 里仍有 17 行把键清单**字面抄在表里**＝册子之外的第二处声明，
    其中 `capability_registry.py:390`（WEATHER 行）正是简报点名的那一格。
    判据两条：
    ① 硬口径——凡 `FACETS` 已覆盖的能力，registry 行**必须**走 `config_keys_for()`，
       字面抄写＝当场红（今天 0 枚，属真牙不是摆设：见注毒 G2 腿）；
    ② 棘轮——字面抄写的行数（现算 17）只准降；把这枚能力补进 `FACETS` 再改走册＝合法递减。
    ⚠ 本席不改 `capability_registry.py`（那是别席/主会话的面），只把这 17 行点名入账。
    """
    rows = execution_rows()
    bypass = literal_bypass_rows()
    covered_but_literal = sorted(
        {c for c, _d, _k, via in rows if not via and c in manifest_covered_ids()}
    )
    assert not covered_but_literal, (
        f"这些能力已在 `FACETS` 真身册里、registry 行却仍字面抄一份键清单＝第二真身："
        f"{covered_but_literal}｜处置＝该行改 `config_keys=config_keys_for(id)`"
    )
    new_items, delta = ratchet_report(bypass, DECLARED_KEYS_LITERAL_BYPASS_BASELINE)
    assert not new_items, (
        f"新增「绕过真身册、把 config_keys 字面抄进 registry」的能力：{new_items}"
        "｜处置＝先把它登记进 `capability_manifest.FACETS`（含 config_keys 列），"
        "registry 行改走 `config_keys_for(id)`；不许在第二处另写一份键"
    )
    assert delta <= 0, (
        f"字面抄写行数越界（现算 {len(bypass)} > 基线 "
        f"{len(DECLARED_KEYS_LITERAL_BYPASS_BASELINE)}）"
    )



def test_missing_patch_references_ratchet() -> None:
    """腿 D：登记面写出来的 patch 件必须在盘上。起点 7 枚现算录账、只降不升。"""
    current = missing_patch_references(register_surface())
    new_items, delta = ratchet_report(current, MISSING_PATCH_REFERENCE_BASELINE)
    assert not new_items, (
        f"登记面新增被引用而缺席的 patch 件：{new_items}｜处置＝补件或改指针，别留死引用"
    )
    assert delta <= 0, (
        f"缺席 patch 件越界（现算 {len(current)} > 基线 {len(MISSING_PATCH_REFERENCE_BASELINE)}）"
    )


def test_dangling_verb_ledger_still_matches_existing_authority() -> None:
    """腿 E（引用不复述）：动词轴的悬空账仍等于既有真身基线，本席不另立一本。

    判据本体 `_dangling_verb_capabilities` 直接 import 自 `tests/test_trigger_matcher_ratchet.py`
    （禁第二真身）；这一发证的是**子令轴与动词轴指向同一枚缺陷**（`bot.decision` ⇄ `/bot decision`），
    两轴互为旁证——任何一把被放宽，这里就现形。
    """
    dangling = _dangling_verb_capabilities(set(verb_capability_ids()))
    assert dangling == set(DANGLING_VERB_CAPABILITIES_BASELINE), (
        f"动词轴悬空集与既有真身基线漂移：现算 {sorted(dangling)}"
        f"｜基线 {sorted(DANGLING_VERB_CAPABILITIES_BASELINE)}"
    )
    assert "decision" in landed_subcommand_set()["heads"], (
        "读数矛盾：动词轴已无悬空、子令轴却查不到 decision 落点 ⇒ 接线或尺被摘掉一边"
    )


def test_readings_are_reproducible_and_match_ledger() -> None:
    """读数复跑自证（AGENTS 规则 5）：各腿现算值必须逐条等于本文件顶部录的基线。

    起点值 == 本轮值**不算**判据有牙（牙口在注毒腿那边）；这条只钉"账没飘"，
    并把 `-- -s` 可抄的读数打在 stdout，工单 §2 差分表与此同源。
    """
    readings = current_readings()
    keys = (
        "dangling_subcommands", "unlanded_capability_claims", "declared_not_governed",
        "ghost_declared_keys", "missing_patch_references", "literal_bypass_rows",
        "literal_row_covered_by_manifest",
        "e1_full", "e2_heads", "e3_heads", "subcommand_claims", "capability_claims",
        "declared_key_rows", "governed_key_rows", "registered_landing",
    )
    print("\n[G1 尺① 现算读数] " + str({k: readings[k] for k in keys}))
    assert readings["dangling_subcommands"] == sorted(DANGLING_SUBCOMMAND_BASELINE)
    assert readings["unlanded_capability_claims"] == sorted(UNLANDED_CAPABILITY_CLAIM_BASELINE)
    assert readings["declared_not_governed"] == sorted(
        f"{c}::{k}" for c, k in DECLARED_KEY_NOT_GOVERNED_BASELINE
    )
    assert readings["ghost_declared_keys"] == sorted(
        f"{c}::{k}" for c, k in GHOST_DECLARED_KEY_BASELINE
    )
    assert readings["missing_patch_references"] == sorted(MISSING_PATCH_REFERENCE_BASELINE)
    assert readings["literal_bypass_rows"] == sorted(DECLARED_KEYS_LITERAL_BYPASS_BASELINE)
    assert readings["literal_row_covered_by_manifest"] == []


def test_poison_second_source_declaration_is_named() -> None:
    """注毒 G：`FACETS` 已覆盖的能力又在 registry 里字面抄一份键清单 ⇒ 第二真身，必须红。

    今天现算这一档是 0 枚（真身册覆盖的 5 行全部走 `config_keys_for()`）——所以这条判据
    必须靠合成形状试牙，否则它就是一枚"永远绿"的摆设（AGENTS 规则 11 之外的同型病：
    门不咬人时没人知道它没牙）。手法＝纯函数入参喂合成行，不改盘、不碰 registry。
    """
    covered = sorted(manifest_covered_ids())
    assert covered, "FACETS 空了 ⇒ 真身册塌了，先修册再谈本腿"
    victim = covered[0]
    synthetic = [(victim, "domains/x", ("bot_whatever_key",), False)]
    literals = frozenset(c for c, _d, _k, via in synthetic if not via)
    assert victim in literals, "合成行未被认成字面抄写 ⇒ bypass 判定本体在空跑"
    assert victim in manifest_covered_ids(), "受害枚不在真身册 ⇒ 本毒打的是空气"
    # 反向不误伤：同一枚能力改走册之后，不该再被认成第二真身
    delegated = frozenset(c for c, _d, _k, via in [(victim, "domains/x", (), True)] if not via)
    assert delegated == set(), "走了 config_keys_for 的行仍被判第二真身 ⇒ 正向腿会误伤"



# ---------------------------------------------------------------------------
# 注毒腿（内存内造违规 / tmp 副本，绝不写源码树）＋ 反向不误伤腿
# ---------------------------------------------------------------------------
def test_poison_new_dangling_subcommand_is_named() -> None:
    """注毒 A：册上多宣称一条 `/bot g1zombiecmd` ⇒ 腿 A 必须点名它；真落点不得被误伤。"""
    gaps = dangling_subcommands({"注毒": ["g1zombiecmd", "queue", "setup llm"]})
    assert "g1zombiecmd" in gaps["注毒"], "新增悬空子令未被抓到 ⇒ 本腿是永真摆设"
    assert "queue" not in gaps["注毒"] and "setup llm" not in gaps["注毒"], (
        "有落点的子令被判悬空 ⇒ 误伤，常驻判据迟早被人调松"
    )


def test_poison_new_unlanded_capability_claim_is_named() -> None:
    """注毒 B：册上宣称一枚不存在的能力 id ⇒ 零档判据必须点名（不许变软成"记一下"）。"""
    registered = set(registered_landing())
    assert unlanded_capability_claims({"注毒": ["bot.g1_nonexistent"]}, registered) == {
        "bot.g1_nonexistent"
    }
    # 反向不误伤：一枚真在册能力不该进违规集
    real = min(registered)
    assert unlanded_capability_claims({"x": [real]}, registered) == set()


def test_poison_declared_key_outside_own_domain_is_named() -> None:
    """注毒 C：自家域零读点而别处在读＝登记≠支配；全树零读点＝幽灵档；自家域有读点＝放行。"""
    reads = {"domains/foo": {"bot_foo_enabled": ["domains/foo/capabilities/foo.py"]},
             "domains/bar": {"bot_quux": ["domains/bar/capabilities/bar.py"]}}
    rows = [
        ("bot.foo", "bot_foo_enabled", "domains/foo"),  # 健康
        ("bot.foo", "bot_quux", "domains/foo"),  # 别家域在读 → 登记≠支配
        ("bot.foo", "bot_none_read", "domains/foo"),  # 全树零读点 → 幽灵
    ]
    not_governed, ghost = ungoverned_declared_keys(rows, reads)
    assert not_governed == {("bot.foo", "bot_quux")}, f"登记≠支配档点名错位：{not_governed}"
    assert ghost == {("bot.foo", "bot_none_read")}, f"幽灵档点名错位：{ghost}"
    assert ("bot.foo", "bot_foo_enabled") not in not_governed | ghost, (
        "自家域有真读点却被判违规 ⇒ 误伤"
    )


def test_poison_ghost_key_is_not_rescued_by_hot_tier_lists() -> None:
    """注毒 C2：一枚键只在**台账名单**里出现（热改登记/文档）不算真读点。

    这一发钉的是形状：本尺只认 `config.<键>` 与 `getattr(config, "<键>", …)` 两类**值路径**，
    键名字面住在表里只证明"不静默"，不证明"值被消费"（同 `test_config_key_registration_ledger`
    桶 3 的诚实边界，本席不另立一套桶）。
    """
    tree = ast.parse(
        "TABLE = ('bot_only_in_table',)\n"
        "def read(config):\n"
        "    return config.bot_real_key\n"
    )
    found = key_reads_in(tree, {"bot_only_in_table", "bot_real_key"})
    assert found == {"bot_real_key"}, f"名单字面被当成读点了：{sorted(found)}"
    direct = ast.parse('def read(store):\n    return getattr(store, "bot_real_key", None)\n')
    assert key_reads_in(direct, {"bot_real_key"}) == {"bot_real_key"}, (
        "直呼形 getattr 未被认成读点 ⇒ 本席首版那个 26 枚假阳的坑又回来了"
    )


def test_poison_missing_patch_reference_is_named(tmp_path: Path) -> None:
    """注毒 D：登记面引一枚盘上没有的 patch 件 ⇒ 腿 D 必须点名；现存件不得误伤。"""
    fake = tmp_path / "G1-FAKE-REGISTER.md"
    fake.write_text("全账见 `patches/G1-ZOMBIE-PATCH-20261002.md`。\n", encoding="utf-8")
    missing = missing_patch_references([fake])
    assert "G1-ZOMBIE-PATCH-20261002.md" in missing, "缺席 patch 引用未被抓到 ⇒ 本腿空跑"
    real_names = sorted(p.name for p in (ROOT / "patches").glob("*.md"))[:3]
    assert real_names, "patches/ 空了 ⇒ 反向腿无可测对象"
    real = tmp_path / "G1-REAL-REGISTER.md"
    real.write_text("".join(f"见 `patches/{name}`。\n" for name in real_names), encoding="utf-8")
    assert missing_patch_references([real]) == set(), "在册件被判缺席 ⇒ 误伤"


def test_ratchet_allows_monotonic_decrease() -> None:
    """递减放行自证：把在册的登记≠支配修好两枚 ⇒ 棘轮仍绿（修复不受罚，不是等值冻结）。"""
    shrunk = set(DECLARED_KEY_NOT_GOVERNED_BASELINE) - {
        ("bot.weather", "bot_weather_cache_seconds"),
        ("bot.fx", "bot_fx_enabled"),
    }
    new_items, delta = ratchet_report(shrunk, DECLARED_KEY_NOT_GOVERNED_BASELINE)
    assert not new_items and delta < 0, "存量递减被判红 ⇒ 这扇门会逼人留着病不走"


def test_poison_docstring_is_not_a_landing_but_a_probe_pattern_is() -> None:
    """注毒 E（本席首版实栽那发）：docstring 里的 `/bot X` 不许算落点；判定用正则必须算。

    真树取证：`domains/core/decision/trace.py:8` 的 docstring 逐字写着
    「供 ``/bot decision`` 管理员查询跨重启读取」——首版尺子把它认成落点，
    悬空集当场空掉，`/bot decision` 无分支这笔账就被一句**注释**洗白了。
    """
    doc_only = ast.parse('"""供 ``/bot decision`` 管理员查询。"""\nimport re\n')
    found, aliases, has_prefix = pattern_landing(doc_only, "g1_fake_doc.py")
    assert "decision" not in found, "docstring 被当成落点 ⇒ 册子/注释能给自己作证，本尺作废"
    assert not has_prefix and not aliases

    probe = ast.parse('import re\n\n_PAT = re.compile(r"^/bot\\s+decision")\n')
    found_probe, _, _ = pattern_landing(probe, "g1_fake_probe.py")
    assert "decision" in found_probe, (
        "判定用正则取不出词头 ⇒ E2 已瞎：真接上的分支也会被误判成悬空"
    )

    alias_src = ast.parse('_COMMAND_PREFIX = "/bot "\n_COMMAND_ALIASES = ("cookie", "凭据")\n')
    _, alias_bucket, has_prefix_alias = pattern_landing(alias_src, "g1_fake_alias.py")
    assert has_prefix_alias and "cookie" in alias_bucket, "E3 别名字册腿空转 ⇒ /bot cookie 会被误判悬空"

    bare_alias = ast.parse('MODULE_ALIASES = ("decision",)\n')
    _, _, has_prefix2 = pattern_landing(bare_alias, "g1_fake_bare.py")
    assert not has_prefix2, (
        "没有 /bot 前缀常量的模块也放行别名字册 ⇒ 任何一枚同名 alias 都能替悬空命令作证"
    )


def test_poison_tuple_form_head_literals_are_compared_individually() -> None:
    """注毒 F（元组形扩口时补的牙）：E1 认 `startswith((a, b))` ＝**逐个取字面量**，不是「见到 startswith 就算」。

    三面都判：
    - 改掉元组里任一枚字面 ⇒ 那枚词头当场从 E1 消失（若仍「有落点」＝门被锯成摆设）；
    - 单串形口径一字不变（扩口不得回头吃掉旧判据）；
    - 非字面量实参（变量表）与认错接收者/方法名都不许作证——否则一句 `startswith(常量表)`
      就能替一条没有分支的命令作证，与 docstring 洗白同病。
    全内存造树，绝不写盘。
    """

    def heads_of(src: str) -> set[str]:
        return {
            subcommand_head(literal)
            for node in ast.walk(ast.parse(src))
            for literal in startswith_head_literals(node)
        }

    assert heads_of('if command_text.startswith("queue "):\n    pass\n') == {"queue"}, (
        "单串形回归判据变了 ⇒ 扩元组形时把旧口径也动了"
    )
    assert heads_of('if command_text.startswith(("decision ", "决策 ")):\n    pass\n') == {
        "decision", "决策"
    }, "元组形取数错位 ⇒ 新腿没真读出两枚词头（会误伤健康接线）"

    assert "decision" not in heads_of(
        'if command_text.startswith(("desicion ", "决策 ")):\n    pass\n'
    ), "改掉元组里一枚字面后 decision 仍被判有落点 ⇒ 本腿退化成「见到 startswith 就算」"
    assert "decision" not in heads_of('if command_text.startswith(("决策 ",)):\n    pass\n'), (
        "摘掉一枚字面后那枚词头未被摘掉 ⇒ 同上"
    )

    assert heads_of('_H = ("decision",)\nif command_text.startswith(_H):\n    pass\n') == set(), (
        "变量实参被当成落点 ⇒ 任何一张常量表都能替悬空命令作证"
    )
    assert heads_of(
        'if other_text.startswith(("decision",)):\n    pass\n'
        'if command_text.endswith(("decision",)):\n    pass\n'
    ) == set(), "认错接收者/认错方法名也作证 ⇒ 落点集被稀释"

