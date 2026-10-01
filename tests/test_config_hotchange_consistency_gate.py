"""配置面「四处同生」两条缺失边的常驻门（席 W24，2026-09-24）.

本窗被同一件事咬过两次：某席新增两枚行为键时**只生了三处**（字段 + `.env.example` +
catalog），主代理又把两枚**登错进 `RESTART_REQUIRED_KEYS`**（其实有合并层实时读点、该进
`SETTABLE_KEYS`），而四把在册门**一律没红**。席 W21 的普查把原因算清楚了：已有门管
①↔②、①→③、读点→① 三条边，**缺的正是本文件这两条**——

- **①→④**：`config.py` 字段与 `domains/chat_reply/runtime/settings.py` 的两张热改名单
  （`SETTABLE_KEYS` / `RESTART_REQUIRED_KEYS`）之间没有任何比对；
- **③↔④**：`docs/config-catalog-full.md` 的「热更」列与那两张名单互不校验。

## 腿 A（①→④）＝「决策必须留痕」，不是「必须二选一」

两名单皆不登记是**合法档**、不是缺陷：`config.py:536-539` 成文「紧急信息十键两者皆不登记」、
`config.py:575-576` 成文「sync_drift 七键与十键同口径」。未在册键由 `settings.py:907` 对
`set()` **fail-closed 拒绝** ⇒ 「不在名单」= 管理员根本改不了它，而不是「漏登记」。
⇒ 门只要求每枚字段对热改面有**一个可查的表态**：进某张名单，或写进
`DELIBERATELY_UNLISTED`（键 + 成文出处）。存量无表态字段走 `UNACCOUNTED_BASELINE`
精确棘轮（等于实况、只降不升；枚数不写在散文里，以该常量的最近一次现算注释为准）⇒ **新字段既不入名单又不点名 = 红**，而把门写成
「每个字段必须二选一」会当场假红一批正当设计（本席禁这么做）。

反向同样不能写死：`BOT_MUSIC_MODE` 在 `SETTABLE_KEYS` 却**没有**同名 Config 字段（运行时设置
覆盖键，W21 §0③ 实证）。⇒ 本门绝不写「名单里的键必须都是 Config 字段」，只要求这类键出现在
`OVERRIDE_ONLY_LISTED_KEYS` 台账里（今天恰好 1 枚）。

## 腿 B（③↔④）＝只判「有标注的行」的矛盾，不背空白债

catalog 现算（四维＝键行数／带正写三档标注的键数／字段数／两表合计，**现值一律以
`BASELINE_CORPUS_SIZES` 与其上方现算注释为准，本文不手写**；席 W24 首算当时值＝
693/51/697/109，席 S157 复录＝693/52/696/112）：标注面只覆盖极小一部分键行，其余
要么空白、要么所在表根本没有该列（脏树在动）。一上来要求全表标注 = 把门写成永久红 = 没人修 =
门作废（W21 §4.1 的「红被红海淹」正是既有门族的死法）。所以只立三条**今天现算 0 枚**的矛盾：

- B1 文档标「可热更」档而该键**不在** `SETTABLE_KEYS` ⇒ 红（最贵的假宣传）；
- B2 文档标「需重启」档而该键**在** `SETTABLE_KEYS` ⇒ 红（名单已放宽、文档还在劝重启）；
- B3 文档标「无热改面」档而该键**在任一张名单** ⇒ 红。

空白率与异形写法＝**只报告不判红**（`test_hot_change_label_coverage_is_reported` 里写了为什么）。
另注：W21 §1.3 那 6 枚「文档说需重启却没进名单」用的是异形词（`否（需重启）`），不在三档词表内
⇒ 本门按「未标注」处理，既不误伤也不代它背，统一写法属 `docs/**`（主会话），见本席报告 §BLOCKED。

## 禁第二真身（硬规）

三档词表唯一真身＝`scripts/config_catalog_generator_pilot.py` 的 `HOT_TEXT`。本文件**只 import、
不复制**，并由 `test_no_second_hot_tier_vocabulary_in_this_file` 用 AST 自锁：① `HOT_TEXT` 必须
来自 pilot；② 本文件任何非 docstring 字符串常量不得含三档任一原文。注毒两发证明它不是摆设：
切断 import 改硬编码的**源码形态**喂自锁 ⇒ 必须被点名；进程内换掉 pilot 的原文 ⇒ 判据结果必须
跟着变（若本文件私藏副本，注毒必然无感）。

## 诚实边界（这把门抓不了什么）

1. 抓得了「标错」，**抓不了「名单本身填错、文档跟着一起错」的双人同错形**——两边一致就绿。
   本窗那两枚键被登错名单而 catalog 也写「需重启」，正是这一形：本门今天仍然不会为它红。
2. 抓不了「字段有人读、装配函数不搬值」的半程键（`build_rate_limit_settings` 型，W21 §2）；
   那是热改面的第五枚读数，得另立门，别让本门冒充兜住它。
3. 抓不了 `SETTABLE_KEYS` 的转换器是否真被某个消费点读到（存在性 ≠ 活性）。
4. 异形写法按「未标注」处理 ⇒ 有人改用异形就能整体躲开 B1/B2/B3。解法是统一 catalog 三档原文，
   **不是**往本门塞第二份词表（那会同时踩掉硬规与门的公信力）。
5. 台账是地板不是进度：`UNACCOUNTED_BASELINE` 只保证不涨，不保证有人去补那批无表态字段。
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.board_doc_sync import load_config_fields  # 字段全集唯一取数口
from scripts.config_catalog_generator_pilot import (  # 三档词表唯一真身
    HOT_TEXT,
    load_hot_tiers,
    parse_catalog_rows,
)

SETTINGS_PY = (
    ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "settings.py"
)
CATALOG_MD = ROOT / "docs" / "config-catalog-full.md"
THIS_FILE = Path(__file__).resolve()

# 三档的**档位键名**（pilot HOT_TEXT 的键），词表原文一个字都不在本文件出现
TIER_HOT = "settable"
TIER_RESTART = "restart"
TIER_NONE = "none"

# ---------------------------------------------------------------------------
# 腿 A 台账 1：成文「两名单皆不登记」的字段（键 → 成文出处）
# ---------------------------------------------------------------------------
# 出处锚在 config.py 行号（行号会漂，所以活性自检只看「确为字段且两张名单皆无」）。
DELIBERATELY_UNLISTED: dict[str, str] = {
    "bot_emergency_info_enabled": "config.py:536-537 十键成文两表皆不登记（装配门与快照）",
    "bot_emergency_info_sources": "config.py:536-537 同上（装配门第二腿，注册期定）",
    "bot_emergency_info_auto_approve_sources": "config.py:536-537 同上（D-8(a) 权威源白名单）",
    "bot_emergency_info_poll_interval_seconds": "config.py:538 装配期钉进 APScheduler interval job",
    "bot_emergency_info_min_level": "config.py:539 注册期一次解算成闭包常量",
    "bot_emergency_info_push_group_whitelist": "config.py:536-537 十键成文（可选硬推腿）",
    "bot_emergency_info_push_user_ids": "config.py:536-537 同上（可选硬推腿）",
    "bot_emergency_info_reviewer_ids": "config.py:536-537 同上（人工审核面）",
    "bot_emergency_info_keep_days": "config.py:536-537 同上（prune keep_days 烘进快照）",
    "bot_emergency_info_db_path": "config.py:536-537 同上（path_fields 重映射）",
    "bot_sync_drift_alert_enabled": "config.py:575-576 七键与十键同口径（闸不过连 job 都不注册）",
    "bot_sync_drift_surfaces": "config.py:575-576 同上（巡检面清单）",
    "bot_sync_drift_interval_minutes": "config.py:575-576 同上（调度间隔）",
    "bot_sync_drift_startup_delay_seconds": "config.py:575-576 同上（起延迟）",
    "bot_sync_drift_suppression_seconds": "config.py:575-576 同上（同严重度抑制窗）",
    "bot_sync_drift_qq_bot_id": "config.py:575-576 同上（内容 sink 目标，装配期定）",
    "bot_sync_drift_max_evidence_lines": "config.py:575-576 同上（告警证据行数）",
}
DELIBERATELY_UNLISTED_BASELINE = 17

# ---------------------------------------------------------------------------
# 腿 A 台账 2：存量「无表态」字段的精确棘轮（席 W24 现算，2026-09-24；席 S157 复录）
# ---------------------------------------------------------------------------
# 语义：`两名单皆无 且 未写进上表` 的字段数**必须等于**这个数。新增即 > ⇒ 红；
# 有人补登记则 < ⇒ 也红（要求把基线降到实况）——棘轮必须等于真值，否则它只是装饰。
# 尺身份（现算用哪把量出来的）：`find_unaccounted_fields(_config_fields(), *_hot_lists(),
# DELIBERATELY_UNLISTED)`——字段尺＝`scripts/board_doc_sync.py:160 load_config_fields()`（本件 `_config_fields`）、两表尺＝`scripts/config_catalog_generator_pilot.py:254 load_hot_tiers`
# （本件 `_hot_lists`，读 settings.py 全文）。复跑：
#   cd <ROOT> && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
#     PYTHONPYCACHEPREFIX="$TEMP/s157-pyc" ../ChatBot_Runtime/venv/Scripts/python.exe \
#     -m pytest tests/test_config_hotchange_consistency_gate.py \
#     -p no:cacheprovider --basetemp=$TEMP/s157-w24 -q
# 历史：W24 于 03:4x 现算 572；S157 于 2026-09-24T07:24Z 现算 568（差 4 ＝ 裁定 R-4 退役的
# 四枚 `*_via_queue`，出册即出账，不是"在册但不读"）。
# 2026-09-26 席 S-ACG-SWITCH 现算复录 568 → 562：六枚 `bot_search_acg_*` 补登记
# SETTABLE_KEYS（ACG 竖源开关腿根修——chat.py 每消息 get_or 现读，覆盖面此前无入口；
# 归属本波逐枚点名见 tests/test_search_acg_switch_leg.py 锁②与本文件腿 A 现算）。
# 2026-09-27 席 S-SWITCH-REG-IMPL（批⑦b 存量开关归册）现算复录 562 → 554：八枚运行开关
# （TTS 双闸/表情库双闸/记忆总线/好感度 v7/维基知识库/控制面）补登 RESTART_REQUIRED_KEYS，
# 未表态 8 枚出账（判据与逐枚点名见 reports/SWITCH-REG-PREP.md §3.1；ledger 门同批对钉）。
# 2026-09-30 席 人格分册收尾 现算复录 554 → 553：六枚补登 RESTART_REQUIRED_KEYS
# （sticker_private 双键 / network_patrol 三键 / reactions_meme_enabled，逐枚点名与
# 读形判据见 tests/test_config_key_registration_ledger.py 同日块），未表态 4 枚出账
# 净 −1；ledger 门同批对钉（两门读同一群键，指纹 df029f79b20e229d）。
UNACCOUNTED_BASELINE = 549

# ---------------------------------------------------------------------------
# 腿 A 台账 3：在名单里但**没有**同名 Config 字段的正当形态（override-only）
# ---------------------------------------------------------------------------
# 这张表的存在就是本门不写「名单键必须都是字段」的理由。
OVERRIDE_ONLY_LISTED_KEYS: dict[str, str] = {
    "BOT_MUSIC_MODE": "点歌播放模式走运行时设置覆盖，无同名 Config 字段（席 W21 §0③ 实证）",
}
OVERRIDE_ONLY_BASELINE = 1

# 地板：**由基线派生**，不是另写一组凭记忆的数（基线＝席 W24 于 2026-09-24 03:4x 现算钉死，
# 席 S157 于 2026-09-24T07:24Z 按**新字段集**现算复录：R-4 退役四枚 `*_via_queue` ⇒ 字段 697→696；
# 同刻另三维亦复算＝键行 693→693、正写标注 51→52、两表合计 109→112（他波在飞件，按实况收紧）。
# 尺身份＝本件 `_corpus_sizes()`＝`catalog_row_stats()`＋`_config_fields()`＋`_hot_lists()`，
# 复跑命令见 `UNACCOUNTED_BASELINE` 上方注释块。
# 四维依次＝(catalog 键行数, 有正写三档标注的键数, config.py 字段数, 两张热改名单合计)。
# 2026-09-25 席 MAIN-B1 现算复录（尺身份同上，仍用本件 `_corpus_sizes()`）：
#   本波八枚键四面同生 ⇒ 键行 +8、正写标注 +8（全按 `🟡需重启` 档写，与热改名单一致）、
#   字段 +8、热改名单 +8（八枚全进 RESTART_REQUIRED_KEYS，无一进 SETTABLE）。
#   四维另各多出 1/0/2/2：键行 +1、字段 +2、名单 +2 属**他波在飞件**，按实况一并计入真值、
#   归属照实标在这里——本波不冒领，也不替他波把地板压回去。
BASELINE_CORPUS_SIZES: tuple[int, int, int, int] = (704, 61, 708, 124)
# 容差：允许脏树小幅波动，但不许整面塌（键行 −30、标注 −10、字段 0、名单 −5）。
# 地板只准这样**收紧**，不准放宽——放宽等于把「门变瞎」提前写进合同。
FLOOR_SLACK: tuple[int, int, int, int] = (30, 10, 0, 5)

_STAR_STRIP = re.compile(r"^[*\s]+|[*\s]+$")
_HOT_HEADER_HINT = "热"  # 只用来定位列，不是档位词表


# ---------------------------------------------------------------------------
# 取数口（全部现读既有真身，零复制、零写盘）
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _config_fields() -> frozenset[str]:
    """字段全集：`scripts/board_doc_sync.load_config_fields()`（与门族同口径；枚数以
    `BASELINE_CORPUS_SIZES` 第三维的最近一次现算注释为准，本行不手写）。"""
    return frozenset(load_config_fields())


@lru_cache(maxsize=1)
def _hot_lists() -> tuple[frozenset[str], frozenset[str]]:
    """两张热改名单（小写）：pilot 的 `load_hot_tiers`（它自身执法「两表不得同现」）。"""
    tiers = load_hot_tiers(SETTINGS_PY.read_text(encoding="utf-8"))
    return (
        frozenset(k for k, v in tiers.items() if v == TIER_HOT),
        frozenset(k for k, v in tiers.items() if v == TIER_RESTART),
    )


@lru_cache(maxsize=1)
def _catalog_text() -> str:
    return CATALOG_MD.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def _hot_column_by_line(text: str) -> dict[int, int | None]:
    """每枚表格行适用的「热更」列下标（按**表头文字**定位）。

    pilot 的 `COLUMNS` 只认七列表的列序，而 catalog 有 10 张表根本没有该列、另有非七列形态
    ⇒ 定位必须由表头决定。这里只用「列名含'热'字」一条，不碰档位词表（禁第二真身）。
    """
    col_by_line: dict[int, int | None] = {}
    active: int | None = None
    pending_header: tuple[str, ...] | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("|"):
            pending_header = None
            continue
        cells = tuple(c.strip() for c in line.strip().strip("|").split("|"))
        if not cells:
            continue
        if set(cells[0]) <= set("-: "):
            if pending_header is not None:
                active = next((i for i, c in enumerate(pending_header) if _HOT_HEADER_HINT in c), None)
            pending_header = None
            continue
        col_by_line[line_no] = active
        pending_header = cells
    return col_by_line


def _tier_of_cell(cell: str, vocabulary: Mapping[str, str]) -> str | None:
    """单元格 → 档位。只认 `vocabulary`（pilot 真身）的原文前缀，异形写法一律「未标注」。"""
    if not cell:
        return None
    bare = _STAR_STRIP.sub("", cell)
    return next((tier for tier, marker in vocabulary.items() if bare.startswith(marker)), None)


def catalog_claims(
    text: str, vocabulary: Mapping[str, str] = HOT_TEXT
) -> dict[str, frozenset[str]]:
    """键 → 该键在 catalog 里出现过的档位集合（多表重复登记时取并集）。

    `vocabulary` 收成**参数**且缺省即 pilot 那个 dict 对象，注毒可以 `monkeypatch.setitem`
    改它来证明判据真读 pilot——本文件若私藏一份词表，那发注毒必然无感。
    """
    col_by_line = _hot_column_by_line(text)
    claims: dict[str, set[str]] = {}
    for row in parse_catalog_rows(text):
        col = col_by_line.get(row.line_no)
        if col is None or col >= len(row.cells):
            continue
        tier = _tier_of_cell(row.cells[col], vocabulary)
        if tier is None:
            continue
        for key in row.keys:
            claims.setdefault(key, set()).add(tier)
    return {k: frozenset(v) for k, v in claims.items()}


def catalog_row_stats(text: str, vocabulary: Mapping[str, str] = HOT_TEXT) -> tuple[int, int, int]:
    """(键行总数, 无有效标注行数, 异形标注行数)——第二腿只报告用，不判红。"""
    col_by_line = _hot_column_by_line(text)
    total = unannotated = odd = 0
    for row in parse_catalog_rows(text):
        total += 1
        col = col_by_line.get(row.line_no)
        cell = "" if col is None or col >= len(row.cells) else row.cells[col]
        if not cell:
            unannotated += 1
            continue
        if _tier_of_cell(cell, vocabulary) is None:
            odd += 1
    return total, unannotated, odd


# ---------------------------------------------------------------------------
# 判据本体：三条纯函数（喂假数据即可测杀伤力，不必碰磁盘）
# ---------------------------------------------------------------------------
def find_hot_claims_without_hot_list(
    claims: Mapping[str, Iterable[str]], settable: Iterable[str]
) -> list[str]:
    """B1：文档说可热更、代码侧却不在 `SETTABLE_KEYS` ⇒ 假宣传。"""
    hot = frozenset(settable)
    return sorted(k for k, tiers in claims.items() if TIER_HOT in tiers and k not in hot)


def find_restart_claims_already_hot(
    claims: Mapping[str, Iterable[str]], settable: Iterable[str]
) -> list[str]:
    """B2：文档说需重启、键却已进 `SETTABLE_KEYS` ⇒ 文档落后于名单。"""
    hot = frozenset(settable)
    return sorted(k for k, tiers in claims.items() if TIER_RESTART in tiers and k in hot)


def find_no_surface_claims_already_listed(
    claims: Mapping[str, Iterable[str]], settable: Iterable[str], restart: Iterable[str]
) -> list[str]:
    """B3：文档说无热改面、键却登记在某张名单里 ⇒ 定性与名单互相打脸。"""
    listed = frozenset(settable) | frozenset(restart)
    return sorted(k for k, tiers in claims.items() if tiers == frozenset({TIER_NONE}) and k in listed)


def find_unaccounted_fields(
    fields: Iterable[str], settable: Iterable[str], restart: Iterable[str], declared: Iterable[str]
) -> frozenset[str]:
    """腿 A 的核心集合：既不在两张名单、也没写进「故意不登记」台账的字段。"""
    return frozenset(fields) - frozenset(settable) - frozenset(restart) - frozenset(declared)


# ---------------------------------------------------------------------------
# 地板与活性（防「恒空即恒绿」）
# ---------------------------------------------------------------------------
def _corpus_sizes() -> tuple[int, int, int, int]:
    """(catalog 键行数, 有正写标注的键数, 字段数, 两张名单合计)——地板与注毒共用这一把尺。"""
    text = _catalog_text()
    settable, restart = _hot_lists()
    return (
        catalog_row_stats(text)[0],
        len(catalog_claims(text)),
        len(_config_fields()),
        len(settable) + len(restart),
    )


def assert_corpus_is_readable(
    sizes: Sequence[int],
    reference: Sequence[int] = BASELINE_CORPUS_SIZES,
    slack: Sequence[int] = FLOOR_SLACK,
) -> None:
    """四道地板：**地板由基线派生**，不是另写一组凭记忆的数。

    取数口是**参数**——地板用例喂现算值，注毒用例喂合成值，同一把尺两次用；
    而基线 `BASELINE_CORPUS_SIZES` 是席 W24 于 03:4x、席 S157 于 07:24Z 先后现算钉死的，
    改它必须连同实况（哪一维、为什么动）一起交代。
    """
    names = ("catalog 键行", "有正写标注的键", "config.py 字段", "两张热改名单合计")
    hints = (
        "⇒ 表格形态已变、门正在变瞎",
        "⇒ 标注面在缩水，B1/B2/B3 将无物可判",
        "⇒ 字段提取面塌了",
        "⇒ 热改名单提取面塌了",
    )
    for index, (got, base, give, name, hint) in enumerate(zip(sizes, reference, slack, names, hints)):
        floor = base - give
        assert got >= floor, (
            f"{name} 现算 {got} 枚，低于地板 {floor}（基线 {base} − 容差 {give}）{hint}"
        )
        assert 0 <= give <= base, f"地板容差本身不合法（第 {index} 维）：{give} / {base}"


def test_parsers_are_not_blind() -> None:
    """地板用例：解析器一瞎，下面所有判据都会「恒绿」。"""
    assert_corpus_is_readable(_corpus_sizes())


def test_degenerate_corpus_is_named_not_green() -> None:
    """反向地板（毒发 0）：退化输入必须被地板点名，否则「恒空即恒绿」。"""
    assert catalog_claims("") == {}, "空 catalog 竟解析出标注 ⇒ 解析器在编造"
    with pytest.raises(AssertionError) as excinfo:
        assert_corpus_is_readable((0, 0, 0, 0))
    assert "变瞎" in str(excinfo.value), f"退化输入没被地板接住：{excinfo.value}"


def test_floor_is_a_ratchet_not_a_decorative_number() -> None:
    """地板的杀伤力：每一维**恰好踩线**通过、**再多掉一枚**必红（4 维 × 2 发＝8 组判定）。

    这一用例是防「地板写成比实况低一大截的死数」——那种地板缩水面照样放行，
    而它自己永远是绿的。基线只能靠人下调，但至少下调的这一步会被现算当场抓到。
    """

    def _sizes(dimension: int, delta: int) -> tuple[int, int, int, int]:
        values = list(BASELINE_CORPUS_SIZES)
        values[dimension] = BASELINE_CORPUS_SIZES[dimension] - FLOOR_SLACK[dimension] + delta
        return (values[0], values[1], values[2], values[3])

    for dimension in range(4):
        assert_corpus_is_readable(_sizes(dimension, 0))
        with pytest.raises(AssertionError):
            assert_corpus_is_readable(_sizes(dimension, -1))


# ---------------------------------------------------------------------------
# 腿 A（①→④）
# ---------------------------------------------------------------------------
def test_hot_change_lists_are_disjoint() -> None:
    """一枚键不能同时「可热更」又「需重启」——真值档必须唯一。"""
    settable, restart = _hot_lists()
    both = sorted(settable & restart)
    assert not both, f"同时在两张名单里的键（档位无唯一真值）：{both}"


def test_every_config_field_takes_a_hot_change_position() -> None:
    """①→④：每枚字段要么进名单，要么在本文件点名「故意不登记」（存量走精确棘轮）。"""
    fields = _config_fields()
    settable, restart = _hot_lists()
    unaccounted = find_unaccounted_fields(fields, settable, restart, DELIBERATELY_UNLISTED)
    assert len(DELIBERATELY_UNLISTED) == DELIBERATELY_UNLISTED_BASELINE, (
        f"『两表皆不登记』台账实际 {len(DELIBERATELY_UNLISTED)} 条 ≠ 基线 "
        f"{DELIBERATELY_UNLISTED_BASELINE}（摘账后同步下调，只减不增）"
    )
    assert len(unaccounted) == UNACCOUNTED_BASELINE, (
        f"对热改面「无表态」的字段现算 {len(unaccounted)} 枚，基线 {UNACCOUNTED_BASELINE}。"
        f"变多 ⇒ 新增字段既没进 SETTABLE_KEYS/RESTART_REQUIRED_KEYS、也没写进 "
        f"DELIBERATELY_UNLISTED：三条合法出路 ①有合并层实时读点→进 SETTABLE "
        f"②装配期冻结→进 RESTART ③确属故意不开放→写进本文件台账并在 config.py 补成文，"
        f"然后把基线降到实况。"
        f"变少 ⇒ 有人补了登记，请把 UNACCOUNTED_BASELINE 下调到实况（棘轮必须等于真值）。"
        f"当前无表态样例（名字序前 8 枚）：{sorted(unaccounted)[:8]}"
    )


def test_deliberate_unlisted_ledger_is_not_self_satisfying() -> None:
    """台账不得变坟场：每条都必须真为字段、且真「两表皆无」、理由够长。"""
    fields = _config_fields()
    settable, restart = _hot_lists()
    stale_field = sorted(k for k in DELIBERATELY_UNLISTED if k not in fields)
    assert not stale_field, f"台账里的键已不是 config.py 字段（写法漂移）：{stale_field}"
    now_listed = sorted(k for k in DELIBERATELY_UNLISTED if k in settable or k in restart)
    assert not now_listed, f"这些键已登记进热改名单，台账必须摘账（否则基线在骗人）：{now_listed}"
    thin_reason = sorted(k for k, v in DELIBERATELY_UNLISTED.items() if len(v.strip()) < 12)
    assert not thin_reason, f"理由短到撑不起一个『不登记』决定：{thin_reason}"


def test_listed_keys_without_config_field_are_declared_override_only() -> None:
    """④→① 反向**不做强相等**（override-only 是正当形态），只要求点名。"""
    fields = _config_fields()
    settable, restart = _hot_lists()
    listed = settable | restart
    undeclared = sorted(
        k for k in listed if k not in fields and k.upper() not in OVERRIDE_ONLY_LISTED_KEYS
    )
    assert not undeclared, (
        "名单里有键，但既无同名 Config 字段、也没写进 OVERRIDE_ONLY_LISTED_KEYS ⇒ "
        f"要么补字段、要么点名并写理由（拼错的 env 名会被 translate_env_keys 静默丢弃）：{undeclared}"
    )
    assert len(OVERRIDE_ONLY_LISTED_KEYS) == OVERRIDE_ONLY_BASELINE, (
        f"override-only 台账实际 {len(OVERRIDE_ONLY_LISTED_KEYS)} 条 ≠ 基线 "
        f"{OVERRIDE_ONLY_BASELINE}"
    )
    stale = sorted(k for k in OVERRIDE_ONLY_LISTED_KEYS if k.lower() in fields)
    assert not stale, f"这些 override-only 条目如今已有同名 Config 字段，请摘账：{stale}"


# ---------------------------------------------------------------------------
# 腿 B（③↔④）——三条判据今天现算各 0 枚
# ---------------------------------------------------------------------------
def test_catalog_hot_claims_are_backed_by_settable_list() -> None:
    """B1：文档声称能热更、代码却拒写 ⇒ 管理员照文档做就吃亏。"""
    settable, _ = _hot_lists()
    bad = find_hot_claims_without_hot_list(catalog_claims(_catalog_text()), settable)
    assert not bad, f"文档标『可热更』但不在 SETTABLE_KEYS（假宣传）：{bad}"


def test_catalog_restart_claims_are_not_already_hot() -> None:
    """B2：文档劝人重启、键其实已可热更 ⇒ 名单放宽而文档没跟随。"""
    settable, _ = _hot_lists()
    bad = find_restart_claims_already_hot(catalog_claims(_catalog_text()), settable)
    assert not bad, f"文档标『需重启』但已在 SETTABLE_KEYS（文档落后于名单）：{bad}"


def test_catalog_no_surface_claims_are_not_listed() -> None:
    """B3：文档说没有热改面、键却登记在名单里 ⇒ 两边互相打脸。"""
    settable, restart = _hot_lists()
    bad = find_no_surface_claims_already_listed(catalog_claims(_catalog_text()), settable, restart)
    assert not bad, f"文档标『无热改面』但已在名单里（定性打脸）：{bad}"


def test_hot_change_label_coverage_is_reported() -> None:
    """空白率与异形写法：**只报告、不判红**（第二腿）。

    为什么不判红：catalog 695 枚键行里 633 行没有有效标注（空白，或所在表根本没有该列），
    占九成。要求全表标注 = 门永久红 = 所有人绕过它——那是把「抓未来的错」写成「背存量债」，
    本仓既有门族就是死于「红被红海淹」（W21 §4.1）。异形写法同理：把它收进判据之前必须先统一
    catalog 三档原文（要动 `docs/**`，不在本席独占面）。本腿只钉**标注数不得低于今天**，
    并把实况打印出来，让缺口可见、不挡路。
    """
    rows, unannotated, odd = catalog_row_stats(_catalog_text())
    annotated_rows = rows - unannotated - odd
    floor = BASELINE_CORPUS_SIZES[1] - FLOOR_SLACK[1]
    assert annotated_rows >= floor, (
        f"带三档标注的行降到 {annotated_rows} 行（地板 {floor}＝基线 {BASELINE_CORPUS_SIZES[1]}"
        f" − 容差 {FLOOR_SLACK[1]}）：标注面在缩水"
    )
    assert len(catalog_claims(_catalog_text())) <= annotated_rows, "标注键数不可能超过标注行数"
    print(
        f"[config 热改标注覆盖实况] 键行 {rows}｜有标注行 {annotated_rows}｜"
        f"空白或该表无列 {unannotated}｜异形写法 {odd}｜"
        f"无有效语义占比 {(unannotated + odd) * 100 // max(rows, 1)}%"
    )


# ---------------------------------------------------------------------------
# 禁第二真身自锁（判「码 + 可导入的 import 形态」，不判注释）
# ---------------------------------------------------------------------------
def vocabulary_violations(source: str) -> list[str]:
    """这份源码是否私藏了一份档位词表？（AST 判定；本模块与任何被审源码都可喂进来）"""
    problems: list[str] = []
    tree = ast.parse(source)
    imports_pilot = any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("config_catalog_generator_pilot")
        and any(alias.name == "HOT_TEXT" for alias in node.names)
        for node in ast.walk(tree)
    )
    if not imports_pilot:
        problems.append("词表真身易主：没有 from scripts.config_catalog_generator_pilot import HOT_TEXT")
    markers = tuple(HOT_TEXT.values())
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstring_nodes.add(id(body[0].value))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_nodes
            and any(marker in node.value for marker in markers)
        ):
            problems.append(f"第 {node.lineno} 行字符串常量含档位词原文（第二真身）")
    return problems


def test_no_second_hot_tier_vocabulary_in_this_file() -> None:
    """硬规：三档词表只有一个真身。本文件一个字都不抄，且被 AST 自锁。"""
    problems = vocabulary_violations(THIS_FILE.read_text(encoding="utf-8"))
    assert not problems, "禁第二真身自锁点名：" + "；".join(problems)


# ---------------------------------------------------------------------------
# 注毒自证（全部进程内：monkeypatch 取数口 / 改内存 dict / 造源码字符串；磁盘注毒零次）
#
# 形状：每发毒都**去调用真身用例**，断言它转红（或断言它不红，用来量「漏放」那一侧）。
# 这样报出来的「变红用例数」是真判据的杀伤力，而不是另写一套影子判据的自我表扬——
# 影子判据这套东西本席上一版写过，改完判据形状后它会悄悄失去杀伤力，已废弃。
# 外部还有一枚 `%TEMP%\seat-w24-plugin\poison_w24.py` 用同样八发毒复算一遍（见报告 §3.2）。
# ---------------------------------------------------------------------------
_FAKE_UNLISTED = "bot_poison_w24_not_in_lists"
_FAKE_NEW_FIELD = "bot_poison_w24_new_field"
_RESTART_VICTIM = "bot_quiet_hours_enabled"  # 真在 SETTABLE_KEYS 里的键（W24 现算 43 枚之一）


def fake_catalog_row(key: str, tier: str, vocabulary: Mapping[str, str] = HOT_TEXT) -> str:
    """造一张三行小表（表头/分隔/数据），热更列写 `vocabulary` 里该档原文 + 括注（顺带测前缀匹配）。"""
    return "\n".join(
        (
            "| 键名 | 类型 | 默认值 | 合法值 | 热更 | 作用 | 关系 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            f"| `{key.upper()}` | bool | `False` | 0/1 | {vocabulary[tier]}（席 W24 注毒夹具） | 注毒 | 注毒 |",
        )
    )


def _self() -> ModuleType:
    """本模块自身——注毒要改的就是「自己读的取数口」，不是别人的（也绝不落磁盘）。"""
    return sys.modules[__name__]


def _poison_catalog(monkeypatch: pytest.MonkeyPatch, *rows: str) -> None:
    """把假标注行**追加**到真 catalog 之后（只增不改，逐发可归因）。"""
    module = _self()
    original = module._catalog_text
    monkeypatch.setattr(module, "_catalog_text", lambda: original() + "\n" + "\n".join(rows))


def test_poison_fake_hot_claim_reds_the_real_b1_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 1（假「可热改」标注）：真身 B1 用例转红 1 条，B2 用例保持绿。"""
    assert _FAKE_UNLISTED not in _hot_lists()[0], "夹具已变：这枚假键竟已在名单里，本毒在空跑"
    _poison_catalog(monkeypatch, fake_catalog_row(_FAKE_UNLISTED, TIER_HOT))
    with pytest.raises(AssertionError):
        _self().test_catalog_hot_claims_are_backed_by_settable_list()
    _self().test_catalog_restart_claims_are_not_already_hot()


def test_poison_fake_restart_claim_reds_the_real_b2_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 2（假「需重启」标注）：给真可热更的键写「需重启」⇒ 真身 B2 用例红，B1 保持绿。"""
    settable, _ = _hot_lists()
    assert _RESTART_VICTIM in settable, "夹具前提已变：该键不再可热更，本毒此刻是在空跑"
    _poison_catalog(monkeypatch, fake_catalog_row(_RESTART_VICTIM, TIER_RESTART))
    with pytest.raises(AssertionError):
        _self().test_catalog_restart_claims_are_not_already_hot()
    _self().test_catalog_hot_claims_are_backed_by_settable_list()


def test_poison_swapping_the_two_legs_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 3（两腿判据互换）：正解「B1 红 / B2 绿」，互换后变「B1 漏放 / B2 错抓」⇒ 现形。

    专防「两条写成同一个式子」或「档位键名抄反」——那两种写法在今天的数据上都绿。
    """
    module = _self()
    original_b1 = module.find_hot_claims_without_hot_list
    original_b2 = module.find_restart_claims_already_hot
    _poison_catalog(monkeypatch, fake_catalog_row(_FAKE_UNLISTED, TIER_HOT))
    with pytest.raises(AssertionError):
        module.test_catalog_hot_claims_are_backed_by_settable_list()
    module.test_catalog_restart_claims_are_not_already_hot()
    monkeypatch.setattr(module, "find_hot_claims_without_hot_list", original_b2)
    monkeypatch.setattr(module, "find_restart_claims_already_hot", original_b1)
    module.test_catalog_hot_claims_are_backed_by_settable_list()  # 漏放：不再红，正是毒的表征
    with pytest.raises(AssertionError):
        module.test_catalog_restart_claims_are_not_already_hot()  # 错抓到另一条上


def test_poison_new_unlisted_field_breaks_the_ratchet(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 4（新字段不表态）：既不进两张名单、也不写进台账 ⇒ 腿 A 真身用例红。"""
    module = _self()
    settable, restart = _hot_lists()
    original = module._config_fields
    live = len(find_unaccounted_fields(original(), settable, restart, DELIBERATELY_UNLISTED))
    monkeypatch.setattr(module, "_config_fields", lambda: frozenset(original() | {_FAKE_NEW_FIELD}))
    with pytest.raises(AssertionError):
        module.test_every_config_field_takes_a_hot_change_position()
    # 毒性算术也现算：不锁常量具体值，锁「注入一枚无表态 ⇒ 恰好 +1」这件事。
    bumped = find_unaccounted_fields(
        frozenset(original() | {_FAKE_NEW_FIELD}), settable, restart, DELIBERATELY_UNLISTED
    )
    assert len(bumped) == live + 1, f"注入一枚后应 +1，实得 {live}→{len(bumped)} ⇒ 棘轮是装饰"


def test_poison_stale_ledger_entry_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 5（假摘账）：台账活性用例红；同发实证**数量棘轮对这一形天生瞎**。

    两把判据各管一头，这正是 §「诚实边界」那条「抓得了标错、抓不了双人同错」的机制来源。
    """
    module = _self()
    settable, restart = _hot_lists()
    victim = min(DELIBERATELY_UNLISTED)
    assert victim not in settable and victim not in restart, "夹具前提已变：该键早已登记，本毒在空跑"
    live = find_unaccounted_fields(_config_fields(), settable, restart, DELIBERATELY_UNLISTED)
    monkeypatch.setattr(module, "_hot_lists", lambda: (frozenset(settable | {victim}), restart))
    with pytest.raises(AssertionError):
        module.test_deliberate_unlisted_ledger_is_not_self_satisfying()
    after = find_unaccounted_fields(
        _config_fields(), frozenset(settable | {victim}), restart, DELIBERATELY_UNLISTED
    )
    assert len(after) == len(live), (
        f"无表态数从 {len(live)} 变成 {len(after)} ⇒ 本毒的「棘轮天生瞎」分工假设已不成立，重看判据"
    )


def test_poison_ghost_key_in_list_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 6（名单里的幽灵键）：凭空一枚既无字段也未点名的 env 名 ⇒ ④→① 台账用例红。"""
    module = _self()
    settable, restart = _hot_lists()
    assert _FAKE_UNLISTED not in _config_fields()
    monkeypatch.setattr(module, "_hot_lists", lambda: (frozenset(settable | {_FAKE_UNLISTED}), restart))
    with pytest.raises(AssertionError):
        module.test_listed_keys_without_config_field_are_declared_override_only()


def test_poison_blind_parser_is_named_by_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """毒发 7（解析器变瞎）：catalog 读成空表 ⇒ 地板两条用例红，否则三条判据「恒空即恒绿」。"""
    module = _self()
    monkeypatch.setattr(module, "_catalog_text", lambda: "")
    with pytest.raises(AssertionError):
        module.test_parsers_are_not_blind()
    with pytest.raises(AssertionError):
        module.test_hot_change_label_coverage_is_reported()


def test_poison_cutting_the_pilot_import_is_named_by_the_self_lock() -> None:
    """毒发 8（切断 pilot import 改硬编码）：AST 自锁须同时点名「真身易主」与「第二真身」。"""
    real = THIS_FILE.read_text(encoding="utf-8")
    shim = "HOT_TEXT = " + repr({tier: marker for tier, marker in HOT_TEXT.items()}) + "\n"
    poisoned = shim + real.replace("    HOT_TEXT,\n", "", 1)
    assert poisoned != real, "注毒替换未生效（本文件 import 形态已变）⇒ 本毒此刻是在空跑"
    assert vocabulary_violations(real) == [], "真实本文件竟已被自锁点名：先修门再谈注毒"
    problems = vocabulary_violations(poisoned)
    kinds = {"真身易主" if "真身易主" in p else "第二真身" for p in problems}
    assert kinds == {"真身易主", "第二真身"}, f"自锁应同时点名两笔，实得：{problems}"


def test_poison_moving_the_pilot_vocabulary_moves_the_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """毒发 9（词表被换）：进程内改掉 pilot 的档位原文 ⇒ 判据必须跟着走（证明没藏副本）。"""
    module = _self()
    source = fake_catalog_row(_FAKE_UNLISTED, TIER_HOT)
    assert catalog_claims(source, vocabulary=HOT_TEXT).get(_FAKE_UNLISTED) == frozenset({TIER_HOT})
    monkeypatch.setattr(module, "_catalog_text", lambda: source)
    with pytest.raises(AssertionError):
        module.test_catalog_hot_claims_are_backed_by_settable_list()
    monkeypatch.setitem(HOT_TEXT, TIER_HOT, "⚑W24-MOVED-MARKER")
    assert catalog_claims(source, vocabulary=HOT_TEXT) == {}, (
        "换了 pilot 的词表而判据仍认旧串 ⇒ 本文件私藏了第二份词表"
    )
    # 同发反向自证：pilot 词表被换 ⇒ B1 用例不再红（换的是空表，等于没标注可判）。
    module.test_catalog_hot_claims_are_backed_by_settable_list()
    moved = fake_catalog_row(_FAKE_UNLISTED, TIER_HOT, vocabulary=HOT_TEXT)
    assert catalog_claims(moved, vocabulary=HOT_TEXT).get(_FAKE_UNLISTED) == frozenset({TIER_HOT})
