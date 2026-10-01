"""称谓单一真身门（席 E2，P6.5，2026-10-02 立）。

量什么
------
`plugins/bot_unified_runtime/**` 的**用户可见字符串单元**里硬编码的称谓字面量：
`你 / 漂泊者 / 主人 / 创造者` 四套。它们过去散着各写各的——正身
`character/addressing.py` 把同一句指令抄成八份字面，`character/shared_group.py`
另留两份「群成员不是唯一主角、不得称漂泊者」的禁令副本（旧 :281 确定性摘要头、
旧 :372 LLM 压缩提示词：两样措辞、一条判据，改一处必漏一处）。

尺从哪来（禁第二把尺）
--------------------
字符串单元口径整体复用文案红线门的 AST 尺（`test_copy_redline_gate` 的
`_user_visible_units` / `_UnitCollector` / `_excluded_subtree_roots` /
`_docstring_node_ids`：合并隐式拼接与 f-string 字面块，跳注释、docstring、
日志调用与正则模式参）。本件只补两样：①「哪些字面算称谓」的词表
`TITLE_TOKENS`；②一本逐文件棘轮账。同一枚数不在两处各量一遍。

账与方向
--------
- **正身** `character/addressing.py`：每套称谓在该文件的字符串单元里**只许出现一次**，
  且那一次就是它自己的定义（`NEUTRAL_ADDRESS`/`WANDERER_TITLE`/`CREATOR_TITLE`），
  其余腿一律插值取词 ⇒ `test_canonical_module_holds_each_title_once`。
  `主人` 在正身现算 **0**：它作为**关系别名**的词表真身在
  `character/relationships.py::_RELATIONSHIP_ALIASES`（另一维，本件不并、只登记存量）。
- **已撤副本面** `character/shared_group.py`：现算 **0**、零容忍 ⇒
  `test_ex_copied_module_holds_zero_titles`。这里不许留空基线当棘轮——名册空则
  整枚判据退化，故按硬尺（==0）而非「只准降」计。
- **其余文件**：`ADDRESSING_LITERAL_BASELINE` 逐枚登记存量，**只降不升**；名册外的
  文件冒出称谓字面量＝新增即红 ⇒ `test_stock_ratchet_only_goes_down`。
- **名册恒等**：`test_ratchet_roster_matches_current_tree` 判「现算 == 名册」，
  谁清了存量不降账当场红，逼同批复录（#68★：地板/棘轮按现算复录）。
- **反空转**：扫描面地板 + 名册非空 + 上限是手写整数字面量，三枚各自红。

红线（AGENTS 第四部分「会话身份+称谓偏好」行；本件各有一腿）
----------------------------------------------------------
① 性别不推断；② 用户显式偏好最优先；③「漂泊者」是群聊保留字。

复跑
----
.. code-block:: bash

    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \\
      <Runtime venv>/Scripts/python.exe -m pytest \\
      -p no:cacheprovider --basetemp=$TEMP/qoder-E2/bt -q \\
      tests/test_addressing_single_source_gate.py
"""

from __future__ import annotations

import ast
import functools
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(REPO_ROOT))

import test_copy_redline_gate as crg  # 复用同一把 AST 尺，禁第二把

PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

CANONICAL_REL = "plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py"
#: 副本已撤、现算必须恒为 0 的面（零容忍，不进出账名册）。
EX_COPIED_RELS: frozenset[str] = frozenset(
    {"plugins/bot_unified_runtime/domains/chat_reply/character/shared_group.py"}
)

# ---------------------------------------------------------------------------
# 词表：四套称谓各一枚。口径写明，免得日后被人当"随手放宽"的把手。
#   · `主人(?!格)`——「主人格」是主人格档（persona A），不是称谓，不记这笔账；
#   · 中性缺省 `你` 只认**被引号包住的**或**整枚单元就是「你」**的形态：裸一个
#     「你」字在中文里无处不在，认下来这把尺就废了（诚实边界，见工单 §2）。
# ---------------------------------------------------------------------------
_NEUTRAL_QUOTE_CHARS = "“\"'`"
_NEUTRAL_CLASS = f"[{re.escape(_NEUTRAL_QUOTE_CHARS)}]"

TITLE_TOKENS: dict[str, re.Pattern[str]] = {
    "wanderer": re.compile("漂泊者"),
    "creator": re.compile("创造者|創造者"),
    "master": re.compile("主人(?!格)"),
    "neutral": re.compile(f"{_NEUTRAL_CLASS}你{_NEUTRAL_CLASS}|^你$"),
}

#: 正身文件里每套称谓**允许的定义处单元数**（现算复录 2026-10-02 席 E2）。
#: 一枚字面＝一句「它就是这个名字」的定义；写成 2 就是又开了一份副本。
CANONICAL_TITLE_UNITS: dict[str, int] = {
    "wanderer": 1,
    "creator": 1,
    "neutral": 1,
    "master": 0,
}

# ---------------------------------------------------------------------------
# 存量棘轮账（2026-10-02 席 E2 现算复录，单位＝字符串单元里的称谓枚数）。
# 方向＝只准降。这些数是**账**不是"期望"：它们是别席的文案面（错误话术池、
# 同意卡、帮助册、巡检告警…），本席无权改，只登记并挡住继续长。
# 逐枚来历与归类见 patches/E2-ADDRESSING-20261002.md §1。
# ---------------------------------------------------------------------------
ADDRESSING_LITERAL_BASELINE: dict[str, int] = {
    "plugins/bot_unified_runtime/domains/assistant/daily/capabilities/daily_assist.py": 7,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py": 2,
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py": 6,
    "plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py": 1,
    "plugins/bot_unified_runtime/domains/chat_reply/character/relationships.py": 4,
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/question_intent.py": 1,
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py": 1,
    "plugins/bot_unified_runtime/domains/core/contracts/character.py": 1,
    "plugins/bot_unified_runtime/domains/core/safety_exec/attack_surface.py": 1,
    "plugins/bot_unified_runtime/domains/core/safety_exec/consent.py": 6,
    "plugins/bot_unified_runtime/domains/core/safety_exec/policy.py": 1,
    "plugins/bot_unified_runtime/domains/core/safety_exec/settings_gate.py": 2,
    "plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py": 1,
    "plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py": 1,
    "plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py": 2,
    "plugins/bot_unified_runtime/domains/ops/monitor/error_report.py": 2,
    "plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py": 1,
    "plugins/bot_unified_runtime/domains/render/card_render/bridge.py": 1,
    "plugins/bot_unified_runtime/domains/schedule/capabilities/schedule_board.py": 3,
}

#: 首届核账记录（(日期, 全树现算总数)）：上限只准 ≤ 首届值，记录只准降。
#: 44 ＝ 2026-10-02 席 E2 用 `crg` 那把尺现算复录（19 枚文件）。
AUDIT_HISTORY: tuple[tuple[str, int], ...] = (("2026-10-02", 44),)

#: 扫描面地板（现算 607 枚 py 件，2026-10-02）。留余量只为一件事：
#: glob 塌陷／根路径写错 ⇒ 判据空转，必须当场红，而不是"全绿"。
SCAN_FACE_PY_FLOOR: int = 560


# ---------------------------------------------------------------------------
# 取数口（唯一一把尺；文件形与内存源码形共用同一套排除口径）
# ---------------------------------------------------------------------------
def units_from_source(source: str, filename: str = "<memory>") -> list[crg._Unit]:
    """内存源码 → 用户可见字符串单元（与 `crg._user_visible_units` 同口径）。"""
    tree = ast.parse(source, filename=filename)
    collector = crg._UnitCollector(crg._excluded_subtree_roots(tree), crg._docstring_node_ids(tree))
    collector.visit(tree)
    return [u for u in collector.units if not u.text.lstrip().lower().startswith(crg._URL_PREFIXES)]


def count_titles(units) -> dict[str, int]:
    """字符串单元 → 各套称谓的枚数（按**出现次数**计，非单元数）。"""
    counts: Counter[str] = Counter()
    for unit in units:
        for token, pattern in TITLE_TOKENS.items():
            hit = len(pattern.findall(unit.text))
            if hit:
                counts[token] += hit
    return dict(counts)


def count_titles_in_source(source: str, filename: str = "<memory>") -> dict[str, int]:
    return count_titles(units_from_source(source, filename))


def count_titles_in_file(path: Path) -> dict[str, int]:
    return count_titles(crg._user_visible_units(path))


# ---------------------------------------------------------------------------
# 三枚判据（纯函数：真树与注毒样本走同一条腿，禁"测试里另写一遍判定"）
# ---------------------------------------------------------------------------
def ratchet_violations(current: dict[str, int]) -> dict[str, tuple[int, int | None]]:
    """存量账判定：返回 `{文件: (现算, 基线或 None)}`，非空即红。

    `None`＝名册外新面（新增即红）；现算 > 基线＝涨账（只降不升）。
    """
    out: dict[str, tuple[int, int | None]] = {}
    for rel, now in current.items():
        allowed = ADDRESSING_LITERAL_BASELINE.get(rel)
        if allowed is None:
            out[rel] = (now, None)
        elif now > allowed:
            out[rel] = (now, allowed)
    return out


def canonical_violations(counts: dict[str, int]) -> dict[str, tuple[int, int]]:
    """正身判定：每套称谓的字面枚数必须等于它在正身的**定义处配额**。"""
    return {
        token: (counts.get(token, 0), allowed)
        for token, allowed in CANONICAL_TITLE_UNITS.items()
        if counts.get(token, 0) != allowed
    }


def zero_tolerance_violations(counts: dict[str, int]) -> dict[str, int]:
    """已撤副本面判定：任何一枚称谓字面都是副本回潮。"""
    return {token: n for token, n in counts.items() if n}


@functools.lru_cache(maxsize=2)
def scan_package_with_surface(
    root: Path | None = None,
) -> tuple[dict[str, dict[str, int]], list[str]]:
    """全包现算 + 读不动的件点名：`{rel: 枚数}` 与 `[rel:行号]` 两份。

    读不动＝那一面等于没被扫过（同 `test_copy_redline_gate` 的
    `test_scan_surface_is_parseable` 纪律）：这里不静默跳过，交给
    `test_package_pieces_are_all_parseable` 点名，免得语法坏掉的件把账"扫没了"。
    """
    base = root or PKG_ROOT
    found: dict[str, dict[str, int]] = {}
    unreadable: list[str] = []
    prefix = REPO_ROOT.as_posix() + "/"
    for path in sorted(base.rglob("*.py")):
        rel = path.resolve().as_posix().removeprefix(prefix)
        try:
            counts = count_titles_in_file(path)
        except SyntaxError as exc:
            unreadable.append(f"{rel}:{exc.lineno}")
            continue
        if counts:
            found[rel] = counts
    return found, unreadable


def scan_package(root: Path | None = None) -> dict[str, dict[str, int]]:
    """全包现算：rel path → 称谓枚数（含正身与已撤副本面，名册判据各自筛）。"""
    return scan_package_with_surface(root)[0]


def stock_ledger(scanned: dict[str, dict[str, int]] | None = None) -> dict[str, int]:
    """剔掉正身与已撤副本面之后的存量名册（rel → 总数），与账名册同口径。"""
    out: dict[str, int] = {}
    for rel, counts in (scanned if scanned is not None else scan_package()).items():
        if rel == CANONICAL_REL or rel in EX_COPIED_RELS:
            continue
        total = sum(counts.values())
        if total:
            out[rel] = total
    return out


# ---------------------------------------------------------------------------
# 一、单一真身：正身只留定义，别处零副本
# ---------------------------------------------------------------------------
def test_canonical_module_holds_each_title_once() -> None:
    """正身文件：每套称谓只许在**自己的定义单元**里出现一次（`master`＝0）。

    注毒方向：在 `addressing.py` 里再手打一枚 `"漂泊者"` ⇒ 本锁当场红。
    反向不误伤：插值形 `f"…{WANDERER_TITLE}…"` 不产生含字面的常量，绿。
    """
    counts = count_titles_in_file(REPO_ROOT / CANONICAL_REL)
    offenders = canonical_violations(counts)
    assert not offenders, (
        f"称谓正身 {CANONICAL_REL} 的字面枚数与定义处不符：{offenders}"
        "（(现算, 允许)）——多出来的一份就是第二真身，改成引用 "
        "NEUTRAL_ADDRESS/WANDERER_TITLE/CREATOR_TITLE 或 group_cast_prohibition()"
    )


def test_canonical_definitions_are_the_only_title_constants() -> None:
    """结构锁：正身里含称谓的字符串单元**逐字等于**该称谓本身（＝它就是定义）。

    只数枚数不够——`"对方可视为漂泊者"` 也是一枚单元、也算一次。本锁钉住
    「那一次必须是定义本身」，把插值腿与定义腿分清。
    """
    units = [u for u in crg._user_visible_units(REPO_ROOT / CANONICAL_REL)]
    seen: list[tuple[int, str]] = []
    for unit in units:
        if any(pattern.search(unit.text) for pattern in TITLE_TOKENS.values()):
            seen.append((unit.lineno, unit.text))
    assert [text for _, text in seen] == ["你", "漂泊者", "创造者"], (
        f"正身里含称谓的字符串单元应当只有三枚定义常量，现算={seen}"
    )


def test_ex_copied_module_holds_zero_titles() -> None:
    """已撤副本面（`shared_group.py`）：称谓字面现算 **0**，零容忍、不进出账名册。

    留一份空基线当棘轮＝「名册为空所以全绿」的空跑（`test_active_push_entry_teeth`
    同纪律），故这里是硬尺 `== 0`：摘要头与 LLM 压缩提示词两处禁令都必须从
    `addressing.group_cast_prohibition()` 取句。
    """
    for rel in sorted(EX_COPIED_RELS):
        counts = zero_tolerance_violations(count_titles_in_file(REPO_ROOT / rel))
        assert not counts, (
            f"{rel} 又自己写了一份称谓禁令：{counts}——正身在 "
            "character/addressing.py:group_cast_prohibition，请把副本撤回并改走真身"
        )


# ---------------------------------------------------------------------------
# 二、接线证明：禁令真从真身流出，不是"删了副本就算完"
# ---------------------------------------------------------------------------
def _digest_summary(tmp_path: Path):
    import sqlite3

    from plugins.bot_unified_runtime.domains.chat_reply.character.shared_group import (
        SQLiteGroupDigestProvider,
    )

    db = tmp_path / "turns.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE conversation_turns"
            " (session_id TEXT, role TEXT, text TEXT, created_at TEXT, kind TEXT)"
        )
        connection.execute(
            "INSERT INTO conversation_turns VALUES"
            " ('group_9_u9', 'user', '今晚谁值班', '2026-10-02T20:00:00', 'chat')"
        )
    return SQLiteGroupDigestProvider(db).load("req-ex2", "9", "u9")


def _summarizer_prompt(tmp_path: Path) -> str:
    from plugins.bot_unified_runtime.domains.chat_reply.character.shared_group import (
        OpenAICompatibleGroupSummarizer,
    )

    captured: dict[str, object] = {}

    class _Capturing:
        def generate(self, messages, **kwargs):
            captured["messages"] = messages

            class _Reply:
                text = "1. 讨论值班"

            return _Reply()

    OpenAICompatibleGroupSummarizer(_Capturing()).summarize("今晚谁值班\n明天谁值班")
    return str(captured["messages"][1]["content"])


def test_both_group_legs_carry_the_canonical_sentence(tmp_path: Path, monkeypatch) -> None:
    """群摘要头与 LLM 压缩提示词都带**逐字同一句**真身禁令（不是各自复述）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character import addressing

    sentence = addressing.group_cast_prohibition()
    assert sentence in _digest_summary(tmp_path).summary
    assert sentence in _summarizer_prompt(tmp_path)
    # 真身自己也在句里带保留字——否则"同句"会退化成两句空壳。
    assert addressing.wanderer_title() in sentence


def test_group_cast_prohibition_has_no_second_producer(monkeypatch, tmp_path: Path) -> None:
    """改真身的保留字 ⇒ 四条腿（群友/私聊/master/other）与两条群腿一起变。

    这是"单一真身"的正证：任何一条腿还留着硬编码，它就不跟着变 ⇒ 本锁红。
    同时反证 `漂泊者` 没有第二处来源。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character import addressing

    monkeypatch.setattr(addressing, "WANDERER_TITLE", "行路人")
    monkeypatch.setattr(addressing, "NEUTRAL_ADDRESS", "台前人")
    sentence = addressing.group_cast_prohibition()
    assert "行路人" in sentence and "漂泊者" not in sentence

    digest = _digest_summary(tmp_path).summary
    assert sentence in digest, "群摘要头没跟着真身走＝还留着一份自写禁令"
    prompt = _summarizer_prompt(tmp_path)
    assert sentence in prompt, "LLM 压缩提示词没跟着真身走＝还留着一份自写禁令"

    member = addressing.build_addressing_context(
        session_type="group", sender_display_name="群友甲", sender_roles=["user"]
    )
    assert "行路人" in member.instruction and "漂泊者" not in member.instruction
    private = addressing.build_addressing_context(
        session_type="private", sender_display_name="小明"
    )
    assert private.preferred_name == "行路人"
    assert "台前人" in private.instruction
    other = addressing.build_addressing_context(session_type="")
    assert "台前人" in other.instruction and "行路人" in other.instruction
    master = addressing.build_addressing_context(
        session_type="group", sender_display_name="澜汐", sender_roles=["super_admin"]
    )
    assert "行路人" in master.instruction


# ---------------------------------------------------------------------------
# 三、棘轮账：存量只降、新增即红、名册恒等、反空转
# ---------------------------------------------------------------------------
def test_stock_ratchet_only_goes_down() -> None:
    """名册内文件：现算 ≤ 基线；名册外文件：现算必须为 0（新增即红）。"""
    violations = ratchet_violations(stock_ledger())
    assert not violations, (
        f"称谓字面量回潮（(现算, 基线)，基线 None＝名册外新面）：{violations}。"
        "正身＝character/addressing.py（称谓）/relationships.py（关系别名），"
        "别处一律插值取词，不许再手打一枚"
    )


def test_ratchet_roster_matches_current_tree() -> None:
    """名册恒等（零余量）：现算集合 == 账名册。清了存量不降账 ⇒ 当场红。"""
    current = stock_ledger()
    assert current == ADDRESSING_LITERAL_BASELINE, (
        f"账与现算脱钩——现算={current} 名册={ADDRESSING_LITERAL_BASELINE}。"
        "只降不升不是'降了不用记账'：同批复录本表与 AUDIT_HISTORY"
    )


def test_baseline_numbers_are_hand_written_literals() -> None:
    """反失明结构锁：基线与地板必须是手写整数字面量，不许 `= sum(现算)` 派生。"""
    assigned: dict[str, ast.expr] = {}
    for node in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned[node.target.id] = node.value

    table = assigned.get("ADDRESSING_LITERAL_BASELINE")
    assert isinstance(table, ast.Dict), "存量账必须是字面量 dict（派生＝跟着被检对象动）"
    for key, value in zip(table.keys, table.values, strict=True):
        assert isinstance(value, ast.Constant) and isinstance(value.value, int), (
            f"账名 {key.value!r} 的值不是整数字面量＝该枚账可被现算派生"
        )
    floor = assigned.get("SCAN_FACE_PY_FLOOR")
    assert isinstance(floor, ast.Constant) and isinstance(floor.value, int), (
        "SCAN_FACE_PY_FLOOR 必须是整数字面量"
    )
    canonical_units = assigned.get("CANONICAL_TITLE_UNITS")
    assert isinstance(canonical_units, ast.Dict) and all(
        isinstance(v, ast.Constant) and isinstance(v.value, int) for v in canonical_units.values
    ), "正身定义处配额必须是整数字面量"


def test_audit_history_direction_and_nonzero_ledger() -> None:
    """方向锁 + 非空自证：核账记录只准降、上限 ≤ 首届值；账本身是真实欠账（>0）。

    「名册为空所以全绿」＝判据空转，本锁与 `SCAN_FACE_PY_FLOOR` 各拦一半。
    """
    counts = [count for _, count in AUDIT_HISTORY]
    assert counts == sorted(counts, reverse=True), f"核账记录出现回升（方向锁）：{AUDIT_HISTORY}"
    current_total = sum(stock_ledger().values())
    assert current_total <= counts[0], (
        f"现算 {current_total} > 首届核账 {counts[0]}＝账在涨，不许用改历史换绿"
    )
    assert counts[0] > 0, "首届账为 0＝要么没回填、要么把欠账抹平了"
    assert len(ADDRESSING_LITERAL_BASELINE) > 0, "存量账名册被掏空＝判据空转"


def test_scan_face_did_not_collapse() -> None:
    """扫描面地板：包内 py 件数 ≥ 地板，且扫到的文件确实来自包根（glob 没塌）。"""
    files = list(PKG_ROOT.rglob("*.py"))
    assert len(files) >= SCAN_FACE_PY_FLOOR, (
        f"扫描面只剩 {len(files)} 枚 py 件（地板 {SCAN_FACE_PY_FLOOR}）："
        "根路径/glob 被动过＝本门在空跑，先修尺再谈绿"
    )
    assert all(str(path).startswith(str(PKG_ROOT)) for path in files)
    scanned = scan_package()
    assert scanned, "全包现算为空＝尺读不到东西，不是'干净'"


def test_package_pieces_are_all_parseable() -> None:
    """读不动的件必须点名：语法坏掉的件＝那一面从账上消失（假绿）。

    本席踩过一次：别席在飞的 `character/quirks.py` 一瞬间残缺，直接把整条棘轮腿
    打成 traceback——那比红更难读。改成本锁：现算跳过并**列出**件名与行号，
    红得有名有姓，谁在飞一眼可见（同 `test_copy_redline_gate::test_scan_surface_is_parseable`）。
    """
    _, unreadable = scan_package_with_surface()
    assert not unreadable, (
        f"包内有件读不动（AST 解析失败），本门的账看不见这些面：{unreadable}"
        "——先让该件 owner 修语法，别把'扫不到'当成'没有'"
    )


# ---------------------------------------------------------------------------
# 四、注毒腿与反向不误伤腿（都走同一个取数口，不另起尺）
# ---------------------------------------------------------------------------
def test_poison_new_prompt_leg_is_caught(tmp_path: Path) -> None:
    """注毒：包外新写一枚硬编码称谓（群聊禁令副本形态）⇒ 现算在册、账判红。"""
    fake = tmp_path / "domains" / "chat_reply" / "character" / "_poison_leg.py"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        '"""毒样本：正身之外手打称谓。"""\n'
        'PROHIBITION = "不要称任何成员为漂泊者"\n'
        'DEFAULT = "你"\n'
        'CREATOR = "她是创造者"\n'
        'MASTER = "优先称呼主人"\n',
        encoding="utf-8",
    )
    counts = scan_package(root=tmp_path)
    assert counts, "注毒样本没被扫出来＝尺本身失效"
    (only_rel,) = tuple(counts)
    hit = counts[only_rel]
    assert hit.get("wanderer") == 1 and hit.get("neutral") == 1, hit
    assert hit.get("creator") == 1 and hit.get("master") == 1, hit
    # 账判据：这枚新面不在名册里 ⇒ 与 `test_stock_ratchet_only_goes_down` 同一红法。
    assert only_rel not in ADDRESSING_LITERAL_BASELINE


def test_poison_second_copy_in_group_leg_is_caught(tmp_path: Path) -> None:
    """注毒：在"已撤副本面"位置上重留一份禁令 ⇒ 零容忍腿必须抓到。"""
    src = (
        '"""群摘要（毒样本）。"""\n'
        'SUMMARY = "发言成员均为群友，不要称任何成员为漂泊者"\n'
    )
    assert count_titles_in_source(src).get("wanderer") == 1, "零容忍腿抓不到＝那枚 ==0 是空判"


def test_poison_canonical_duplicate_definition_is_caught(tmp_path: Path) -> None:
    """注毒：正身里再打第二枚同名定义 ⇒ 正身配额腿必须红。"""
    src = (
        '"""正身（毒样本）。"""\n'
        'WANDERER_TITLE = "漂泊者"\n'
        'ALSO = "对方可视为漂泊者"\n'
    )
    counts = count_titles_in_source(src)
    assert counts.get("wanderer") == 2, (
        f"第二枚定义没数出来（现算={counts}）＝配额腿只能靠运气"
    )
    assert 2 != CANONICAL_TITLE_UNITS["wanderer"]


def test_reverse_legs_are_not_counted(tmp_path: Path) -> None:
    """反向不误伤：注释、docstring、日志调用、正则模式参、「主人格」都不算称谓字面。

    摘掉尺的排除腿（比如把 docstring 也计入）会顶红本锁 ⇒ 四类的账都点到了。
    落盘一份同样形态的样本走 `scan_package` 的路径口径（不碰真树）。
    """
    src = '''"""模块说明：群聊里不得称漂泊者，主人格另说。"""


def f(logger):
    """函数说明：创造者与唤醒者是同一人。"""
    logger.info("已按漂泊者称呼处理")
    return re.compile("主人|创造者", re.IGNORECASE)
'''
    assert count_titles_in_source(src) == {}, "文档/日志/正则被计进了账"
    # 「主人格」是档位名，不是称谓：单看一枚也必须为 0。
    assert count_titles_in_source('X = "主人格在册项"\n') == {}
    # 插值形不产生含字面的常量（正身全靠这种写法把账压到定义处各一枚）。
    assert count_titles_in_source('X = f"当前是私聊；对方可视为{WANDERER_TITLE}。"\n') == {}


def test_all_three_predicates_bite_poison_and_spare_the_clean_tree() -> None:
    """三枚判据各跑一遍双向（同一把尺，不在测试里另写判定）。

    注毒侧：涨账 / 名册外新面 / 正身第二枚定义 / 副本面回潮，四种都必须红。
    反向侧：真树现算过同一组判据必须全空——否则前面那些绿是假绿。
    """
    victim = next(iter(ADDRESSING_LITERAL_BASELINE))
    poisoned_stock = dict(stock_ledger())
    poisoned_stock[victim] = poisoned_stock[victim] + 1
    rose = ratchet_violations(poisoned_stock)
    assert rose.get(victim) == (ADDRESSING_LITERAL_BASELINE[victim] + 1, ADDRESSING_LITERAL_BASELINE[victim]), rose

    new_face = f"{CANONICAL_REL.rsplit('/', 1)[0]}/_another_copy.py"
    caught = ratchet_violations({**stock_ledger(), new_face: 2})
    assert caught.get(new_face) == (2, None), f"名册外新面没被抓住：{caught}"

    assert not ratchet_violations(stock_ledger()), "真树过账判据不为空＝上面的绿是假绿"
    assert not canonical_violations(count_titles_in_file(REPO_ROOT / CANONICAL_REL))
    assert canonical_violations({"wanderer": 2, "creator": 1, "neutral": 1, "master": 0}) == {
        "wanderer": (2, 1)
    }, "正身配额腿抓不到第二枚定义＝那枚配额是空判"
    assert zero_tolerance_violations({"wanderer": 1}) == {"wanderer": 1}
    for rel in EX_COPIED_RELS:
        assert not zero_tolerance_violations(count_titles_in_file(REPO_ROOT / rel))


def test_master_token_is_not_counted_in_the_canonical_module() -> None:
    """`主人` 这整套称谓的真身在关系别名词表（另一维），正身现算必须为 0。

    正身哪天手写一枚「主人」，就是把两套体系又并成一个新副本 ⇒ 配额腿已含此判，
    本锁单独点名，免得读账的人以为 `master` 从没被管过。
    """
    counts = count_titles_in_file(REPO_ROOT / CANONICAL_REL)
    assert counts.get("master", 0) == 0, f"正身里出现了「主人」称谓：{counts}"


# ---------------------------------------------------------------------------
# 五、三条红线（改动本文件者须同批过这三关）
# ---------------------------------------------------------------------------
def test_reserved_wanderer_title_never_addresses_a_group_member() -> None:
    """红线③：群聊非 master 一律不称「漂泊者」——**偏好腿与展示名腿都要挡**。

    旧写法只挡 `addressing_preference == "漂泊者"`，群名片腿漏了：QQ 名片本就能填
    「漂泊者」，于是产出「优先称呼“漂泊者”，禁止称其为漂泊者」的自斥指令，
    与偏好腿同形事故（席 E2 补齐，见 addressing.py 的保留字兜底）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        build_addressing_context,
        wanderer_title,
    )

    title = wanderer_title()
    cases = [
        {"sender_display_name": title},
        {"sender_display_name": f" {title} "},
        {"addressing_preference": title},
        {"sender_display_name": title, "addressing_preference": title},
        {"sender_display_name": "群友乙", "addressing_preference": f"“{title}”"},
    ]
    for extra in cases:
        ctx = build_addressing_context(
            session_type="group", sender_roles=["user"], **extra
        )
        assert ctx.preferred_name != title, extra
        assert ctx.can_use_wanderer_title is False, extra
        assert f"优先称呼“{title}”" not in ctx.instruction, (extra, ctx.instruction)


def test_master_and_private_keep_the_reserved_title_available() -> None:
    """红线③的另一半（反向不误伤）：私聊与群内 master 仍可称「漂泊者」。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        build_addressing_context,
        wanderer_title,
    )

    title = wanderer_title()
    private = build_addressing_context(
        session_type="private", sender_display_name="小明", sender_roles=["user"]
    )
    assert private.preferred_name == title and private.can_use_wanderer_title is True
    master = build_addressing_context(
        session_type="group", sender_display_name="澜汐", sender_roles=["super_admin"]
    )
    assert master.is_master is True and master.can_use_wanderer_title is True
    assert title in master.instruction


def test_explicit_preference_beats_display_name() -> None:
    """红线②：用户显式偏好最优先（群友/私聊/master 三态同一口径）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        build_addressing_context,
    )

    for scope, roles in (("group", ["user"]), ("private", ["user"]), ("group", ["super_admin"])):
        ctx = build_addressing_context(
            session_type=scope,
            sender_display_name="QQ名片很尴尬",
            sender_roles=roles,
            addressing_preference="阿澜",
        )
        assert ctx.preferred_name == "阿澜", (scope, roles, ctx.preferred_name)
        if scope == "group" and "super_admin" not in roles:
            assert "优先称呼“阿澜”" in ctx.instruction


def test_gender_is_never_inferred() -> None:
    """红线①：性别只认显式声明；未知即 unknown，指令句带「不要猜测」的唯一句式。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        build_addressing_context,
        gender_neutrality_clause,
    )

    clause = gender_neutrality_clause()
    for scope, roles in (
        ("private", ["user"]),
        ("group", ["user"]),
        ("group", ["super_admin"]),
        ("", []),
    ):
        ctx = build_addressing_context(
            session_type=scope, sender_display_name="小林", sender_roles=roles
        )
        assert ctx.gender_identity == "unknown" and ctx.gender_confidence == "unknown"
        assert "先生" not in ctx.instruction and "女士" not in ctx.instruction
    explicit = build_addressing_context(
        session_type="private", sender_display_name="小林", gender_identity="nonbinary"
    )
    assert explicit.gender_identity == "nonbinary"
    assert explicit.gender_confidence == "explicit"
    # 唯一句式：私聊与身份未知两腿都插同一句，不许各写一份措辞。
    private = build_addressing_context(session_type="private", sender_display_name="小林")
    unknown = build_addressing_context(session_type="")
    assert clause in private.instruction and clause in unknown.instruction


@pytest.mark.parametrize(
    ("session_type", "roles"),
    [("private", ["user"]), ("group", ["user"]), ("group", ["super_admin"]), ("", [])],
    ids=["private", "group-member", "group-master", "unknown"],
)
def test_every_branch_is_produced_by_the_canonical_module(session_type, roles) -> None:
    """四个分支的指令句都由正身产出，且都落在登记的称谓集合内（无第五套）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.character.addressing import (
        NEUTRAL_ADDRESS,
        WANDERER_TITLE,
        build_addressing_context,
    )

    ctx = build_addressing_context(
        session_type=session_type, sender_display_name="小舟", sender_roles=roles
    )
    assert ctx.instruction.strip()
    assert ctx.preferred_name not in {"", "None"}
    # 兜底的兜底：分支里出现的称谓只有 `漂泊者`（保留字档）——`主人`/`创造者`
    # 不进指令句（它们各自住在关系词表与创造者事实里）。
    assert "主人" not in ctx.instruction.replace("主人格", "")
    assert "创造者" not in ctx.instruction or ctx.is_master
    assert NEUTRAL_ADDRESS or WANDERER_TITLE
