"""文档一致性门禁（全离线）：帮助注册表 ⇄ 命令目录 ⇄ 路由 manifest ⇄ 人读文档同源校验。

- 注册表/文档层：经 scripts/command_catalog.py 的 AST 静态提取（不 import 插件包，
  与脚本运行环境保持同一口径）。
- 运行时行为层：直接 import 插件（与 tests/test_help_entries_coverage.py 同实践），
  证明「运行时注册表 == 静态提取合并结果」，防止两条合并路径漂移。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.command_catalog import (
    DOC,
    _alias_capability_ids,
    _entries,
    _entry_meta,
    _internal_capability_notes,
    _manifest_entries,
    _route_capability_ids,
    _route_kind_values,
    merged_entries,
    render,
)

ROOT = PROJECT_ROOT
COMMANDS_MD = ROOT / "COMMANDS.md"
README_MD = ROOT / "docs" / "README.md"
ROUTE_MATRIX_MD = ROOT / "docs" / "route-matrix.md"
CONFIG_PY = ROOT / "plugins" / "bot_unified_runtime" / "config.py"
SETTINGS_PY = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "settings.py"

# 结构化元数据字段（HelpEntry 扩展）；运行时与静态合并必须逐字段相等。
_META_KEYS = (
    "capability",
    "network",
    "chat_scope",
    "triggers_nl",
    "triggers_nickname",
    "config_vars",
    "examples",
    "tests",
    "outputs",
    "html_image",
    "fallback",
)

# .env 专用键：帮助文本引用、但 config.py 无同名字段、代码经 os.getenv 读取。
# 每个键必须能给出读取点证据后才能登记到这里。
ENV_ONLY_KEYS: frozenset[str] = frozenset()


def _merged() -> list[dict[str, object]]:
    return merged_entries()


# --------------------------------------------------------------------------
# 注册表层：字段完整性 / 唯一性 / 引用可解析
# --------------------------------------------------------------------------


def test_entry_core_fields_readable() -> None:
    assert len(_entries()) > 0
    for entry in _merged():
        topic = entry.get("topic")
        assert isinstance(topic, str) and topic.strip(), entry
        assert isinstance(entry.get("admin_only"), bool), topic
        aliases = entry.get("aliases")
        assert isinstance(aliases, tuple) and aliases, topic
        assert all(isinstance(a, str) and a.strip() for a in aliases), topic
        assert isinstance(entry.get("index"), str) and entry["index"].strip(), topic
        assert isinstance(entry.get("title_line"), str) and entry["title_line"].strip(), topic
        lines = entry.get("lines")
        assert isinstance(lines, list) and lines, topic
        assert all(isinstance(ln, str) and ln.strip() for ln in lines), topic
        detail = entry.get("detail")
        assert isinstance(detail, str) and detail.strip(), topic


def test_entry_topics_unique() -> None:
    topics = [entry["topic"] for entry in _merged()]
    assert len(topics) == len(set(topics)), "帮助主题出现重复"


def _alias_key(alias: object) -> str:
    """别名归一键：大小写不敏感、去全部空白（计划 B.5「别名无重复冲突」口径）。"""
    return re.sub(r"\s+", "", str(alias)).lower()


def test_entry_aliases_collision_free() -> None:
    seen: dict[str, str] = {}
    conflicts: list[str] = []
    for entry in _merged():
        for alias in entry["aliases"]:
            key = _alias_key(alias)
            assert key, f"{entry['topic']} 存在空白别名"
            if key in seen and seen[key] != entry["topic"]:
                conflicts.append(f"别名 {alias!r} 在 {seen[key]} 与 {entry['topic']} 间冲突")
            seen[key] = entry["topic"]
    assert not conflicts, "；".join(conflicts)
    # 运行时别名映射必须与注册表等势：任何被静默覆盖的键都意味着冲突漏网。
    # T5 结构修复（fix-trae2）后映射口径=aliases ∪ META 触发词（aliases 优先）。
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _HELP_ALIAS_MAP,
    )

    expected_keys: set[str] = set()
    for entry in _merged():
        for alias in entry["aliases"]:
            expected_keys.add(str(alias).lower())
        for field in ("triggers_nickname", "triggers_nl"):
            for word in entry.get(field) or ():
                expected_keys.add(str(word).strip().lower())
    assert set(_HELP_ALIAS_MAP) == expected_keys, (
        f"运行时别名映射与注册表（aliases ∪ META 触发词）键集不等势："
        f"映射多 {sorted(set(_HELP_ALIAS_MAP) - expected_keys)[:5]}，"
        f"注册表多 {sorted(expected_keys - set(_HELP_ALIAS_MAP))[:5]}"
    )


def test_entry_meta_registered_for_every_topic() -> None:
    topics = {entry["topic"] for entry in _entries()}
    assert topics <= set(_entry_meta()), (
        f"缺结构化元数据的模块：{sorted(topics - set(_entry_meta()))}"
    )


def test_entry_capability_declared_and_known() -> None:
    known = _route_capability_ids() | _alias_capability_ids()
    assert known, "路由/别名能力 id 提取为空"
    for entry in _merged():
        cap = entry.get("capability")
        assert isinstance(cap, str) and cap.strip(), f"{entry['topic']} 缺 capability"
        for cid in re.findall(r"bot\.[a-z_]+", cap):
            assert cid in known, f"{entry['topic']} 引用未知能力 id：{cid}"


def test_finance_help_topics_registered() -> None:
    """防脱册门禁（F3）：bot.stocks / bot.fx 路由上线后，帮助注册表必须有对应主题。

    评审发现 B1 的最后缺口：路由/分发先落地、echo.py 帮助条目漏配，导致
    `/bot help` 总览与 docs/command-catalog.md 双双缺模块。此断言保证两个
    topic（含公开可见性与能力归属）不再脱册。
    """
    entries = _merged()
    topics = {str(entry["topic"]) for entry in entries}
    assert {"个股行情", "汇率"} <= topics, "个股行情/汇率 帮助主题缺失（bot.stocks/bot.fx 脱册）"
    capability_by_topic = {
        str(entry["topic"]): str(entry.get("capability", "")) for entry in entries
    }
    assert "bot.stocks" in capability_by_topic["个股行情"]
    assert "bot.fx" in capability_by_topic["汇率"]
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _PUBLIC_HELP_TOPICS,
    )

    assert {"个股行情", "汇率"} <= set(_PUBLIC_HELP_TOPICS), (
        "个股行情/汇率 必须对普通用户可见（admin_only=False 且登记进公开主题集）"
    )


def test_route_rules_covered_by_help_or_internal() -> None:
    covered = set(_internal_capability_notes())
    for entry in _merged():
        covered |= set(re.findall(r"bot\.[a-z_]+", str(entry.get("capability", ""))))
    missing = sorted(set(_route_capability_ids()) - covered)
    assert not missing, f"路由能力没有帮助模块也没有内部登记：{missing}"


# 路由层代码事实（不含 echo.py 自身）：帮助主题的落点必须能在这里找到。
_DISPATCH_SOURCES = "".join(
    (ROOT / rel).read_text(encoding="utf-8")
    for rel in (
        "plugins/bot_unified_runtime/__init__.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py",
    )
)


def test_help_topics_have_route_layer_landing() -> None:
    """「路由主题无孤儿」正向：每个帮助 topic 都能在路由层找到落点。

    落点四选一（全部是可审计的代码事实）：
    1. capability 引用了路由表/昵称动词表里的 bot.* 能力 id；
    2. 接口 manifest 以 help_topic 指向该主题；
    3. capability 入口（去前缀后的核心词或其命令头）出现在分发代码中；
    4. 纯配置文档模块（capability 以 .env 开头显式声明无命令入口）。
    """
    known = _route_capability_ids() | _alias_capability_ids()
    manifest_topics = {
        str(item.get("help_topic")) for item in _manifest_entries() if item.get("help_topic")
    }
    orphans: list[str] = []
    for entry in _merged():
        topic = str(entry["topic"])
        cap = str(entry.get("capability", "")).strip()
        if set(re.findall(r"bot\.[a-z_]+", cap)) & known:
            continue
        if topic in manifest_topics:
            continue
        if cap.startswith(".env"):
            continue
        core = cap.split("（")[0].split("(")[0].strip()
        for prefix in ("/bot ", "on_command:", "on_notice:", "on_message:", "matcher:"):
            if core.startswith(prefix):
                core = core[len(prefix):]
                break
        core = core.split("｜")[0].split("/")[0].strip()
        head = core.split()[0] if core.split() else ""
        if (core and core in _DISPATCH_SOURCES) or (head and head in _DISPATCH_SOURCES):
            continue
        orphans.append(f"{topic}（capability={cap!r}）")
    assert not orphans, f"帮助主题在路由层找不到落点：{orphans}"


def test_route_kind_values_complete() -> None:
    values = _route_kind_values()
    assert len(values) == len(set(values)), "RouteKind 出现重复取值"
    assert len(values) >= 20, f"RouteKind 数量异常：{len(values)}"


def test_manifest_active_has_help_topic_or_internal_note() -> None:
    topics = {entry["topic"] for entry in _merged()}
    assert len(_manifest_entries()) >= 15
    for item in _manifest_entries():
        label = item.get("interface_id", "?")
        help_topic = item.get("help_topic") or ""
        note = item.get("internal_note") or ""
        if item.get("status") == "active":
            assert help_topic in topics or note, f"{label} 缺 help_topic/internal_note 登记"
        else:
            assert note, f"{label}（{item.get('status')}）缺 internal_note"
        if help_topic:
            assert help_topic in topics, f"{label} 指向不存在的帮助主题：{help_topic}"


def test_meta_test_paths_exist() -> None:
    for entry in _merged():
        for rel in entry.get("tests", ()):
            assert isinstance(rel, str) and rel.startswith("tests/"), (entry["topic"], rel)
            assert (ROOT / rel).exists(), f"{entry['topic']} 关联测试文件不存在：{rel}"


def test_runtime_help_entries_match_static_merge() -> None:
    """运行时注册表（echo 导入后合并完成）必须与静态提取合并逐字段一致。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        HELP_ENTRIES,
    )

    static = {entry["topic"]: entry for entry in _merged()}
    for entry in HELP_ENTRIES:
        peer = static[entry["topic"]]
        assert list(entry["lines"]) == list(peer["lines"]), entry["topic"]
        assert entry["detail"] == peer["detail"], entry["topic"]
        for key in _META_KEYS:
            if key in peer:
                assert entry.get(key) == peer[key], (entry["topic"], key)


# --------------------------------------------------------------------------
# 运行时行为层：公开帮助不泄露管理员模块
# --------------------------------------------------------------------------


def test_public_help_never_leaks_admin_topics() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        _PUBLIC_HELP_TOPICS,
        _visible_help_entries,
        build_commands_catalog_body,
        build_help_result,
    )

    entries = _merged()
    open_topics = {entry["topic"] for entry in entries if not entry["admin_only"]}
    admin_topics = {entry["topic"] for entry in entries if entry["admin_only"]}
    assert set(_PUBLIC_HELP_TOPICS) == open_topics
    assert {entry["topic"] for entry in _visible_help_entries(False)} == open_topics
    for topic in sorted(admin_topics):
        page = build_help_result(request_id=f"leak-{topic}", query=topic, is_admin=False)
        assert "没有找到" in page.body, f"非管理员可访问管理员模块 {topic}"
    catalog = build_commands_catalog_body(is_admin=False)
    for topic in sorted(admin_topics):
        assert f"\n{topic} | " not in catalog, f"公开命令目录泄露管理员模块 {topic}"


def test_public_overview_body_excludes_admin_rows() -> None:
    """/bot help 总览（真实生成函数产物）不得出现管理员条目的行级内容。

    按行断言而非全文子串：公开模块的说明文字里合法含有「状态/历史」等
    管理员主题同名词，只有「以【管理员主题】开头的行 / 管理员条目原文
    index 行」才算泄露。同时反向守卫：公开条目不得被连带隐藏。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        build_help_result,
    )

    result = build_help_result(request_id="leak-overview", query="", is_admin=False)
    assert result.kind == "text"
    lines = [line.strip() for line in str(result.body).splitlines()]
    for entry in _merged():
        topic = str(entry["topic"])
        marker = f"【{topic}】"
        if entry["admin_only"]:
            leaked = [
                line
                for line in lines
                if line.startswith(marker) or line == str(entry["index"])
            ]
            assert not leaked, f"非管理员总览泄露管理员模块 {topic}：{leaked[:1]}"
        else:
            assert any(line.startswith(marker) for line in lines), (
                f"公开模块 {topic} 未出现在非管理员总览中（疑似被连带隐藏）"
            )


# --------------------------------------------------------------------------
# 配置键与命令入口引用可解析
# --------------------------------------------------------------------------


def _pydantic_field_names() -> set[str]:
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _settable_keys() -> set[str]:
    tree = ast.parse(SETTINGS_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "SETTABLE_KEYS":
            assert isinstance(node.value, ast.Dict), "SETTABLE_KEYS 不是字典字面量"
            return {str(ast.literal_eval(key)) for key in node.value.keys}
    raise AssertionError("SETTABLE_KEYS 定义未找到")


def test_help_config_keys_resolve() -> None:
    fields = _pydantic_field_names()
    settable = _settable_keys()
    blob = repr(_merged()) + repr(_entry_meta())
    unknown: list[str] = []
    for key in sorted(set(re.findall(r"BOT_[A-Z0-9_]+", blob))):
        if len(key) <= 4 or key.endswith("_"):
            continue
        if key in settable or key in ENV_ONLY_KEYS:
            continue
        # config.py 字段本就带 bot_ 前缀（如 BOT_MEMORY_ENABLED -> bot_memory_enabled）。
        if key.lower() in fields:
            continue
        unknown.append(key)
    assert not unknown, f"帮助引用了未知配置键（不在 config.py / SETTABLE_KEYS / 白名单）：{unknown}"


def test_help_entry_points_findable_in_code() -> None:
    sources = "".join(
        (ROOT / rel).read_text(encoding="utf-8")
        for rel in (
            "plugins/bot_unified_runtime/__init__.py",
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py",
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py",
            # v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/。
            "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py",
        )
    )
    for entry in _merged():
        cap = str(entry.get("capability", "")).strip()
        assert cap, f"{entry['topic']} 缺 capability"
        if re.search(r"bot\.[a-z_]+", cap):
            continue  # bot.* id 已由 capability_known 规则校验
        core = cap.split("（")[0].split("(")[0].strip()
        for prefix in ("/bot ", "on_command:", "on_notice:", "on_message:", "matcher:"):
            if core.startswith(prefix):
                core = core[len(prefix):]
                break
        core = core.split("｜")[0].split("/")[0].strip()
        assert core and core in sources, f"{entry['topic']} 的入口在代码中找不到：{cap!r}"


# --------------------------------------------------------------------------
# 文档层：目录重生成一致 + 人读文档去硬编码 + 路由矩阵全覆盖
# --------------------------------------------------------------------------


def test_catalog_document_matches_registry() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert doc == render(_merged()), (
        "docs/command-catalog.md 与注册表不一致；跑 python scripts/command_catalog.py --write 重新生成"
    )


def test_catalog_tutorial_covers_user_journeys() -> None:
    text = DOC.read_text(encoding="utf-8")
    markers = (
        "/bot help",
        "/bot commands",
        "/bot runtime get",
        "/bot runtime set",
        "/bot runtime reset",
        "/bot identity",
        "管理员",
        "私聊",
        "群聊",
        "网络",
        "失败",
    )
    missing = [m for m in markers if m not in text]
    assert not missing, f"教程缺关键内容：{missing}"


def test_commands_md_defers_counts_to_generated_catalog() -> None:
    text = COMMANDS_MD.read_text(encoding="utf-8")
    assert "docs/command-catalog.md" in text, "COMMANDS.md 应指向自动生成目录"
    hardcoded = re.findall(r"\d+\s*(?:个)?(?:模块|别名)", text)
    assert not hardcoded, f"COMMANDS.md 手写了会过期的总数：{hardcoded}（以 command-catalog.md 实时统计为准）"
    assert "好感度 v4" not in text, "好感度已升 v5，禁止回退旧口径"


def test_readme_md_indexes_catalog_without_hardcoded_counts() -> None:
    text = README_MD.read_text(encoding="utf-8")
    assert "command-catalog.md" in text
    hardcoded = re.findall(r"\d+\s*(?:个)?(?:模块|别名)", text)
    assert not hardcoded, f"docs/README.md 手写了会过期的总数：{hardcoded}"


def test_route_matrix_covers_every_route_kind() -> None:
    text = ROUTE_MATRIX_MD.read_text(encoding="utf-8")
    # 词边界匹配（M-2 收口，2026-09-13）：纯子串会让 MARKET 撞上 STOCK_MARKET
    # 类前缀命中（\b 在下划线处不成立，_MARKET 后缀与 MARKETX 前缀均不再误判）。
    missing = [
        kind
        for kind in _route_kind_values()
        if re.search(rf"\b{re.escape(kind)}\b", text) is None
    ]
    assert not missing, f"route-matrix 缺少路由 kind：{missing}"
    assert "好感度 v4" not in text, "route-matrix 好感度口径过期（现为 v5 多因素线性步长）"


# --------------------------------------------------------------------------
# 帮助文案腔调门禁：四要素句式（作用=/参数=/内容=/意义=）
# --------------------------------------------------------------------------

# TRG-AUDIT 盘点（trg-inventory §5 #10）点名的 3 条配置键说明式条目：
# 参数行此前只有「取值=/内容=/意义=」，缺 作用=/参数=。
_TONE4_TOPICS: frozenset[str] = frozenset({"限流", "群摘要", "视频理解"})
_TONE4_FACETS = ("作用=", "参数=", "内容=", "意义=")


def _detail_facet_section_lines(detail: str) -> list[str]:
    """取 detail【指令与参数】小节的顶层行（缩进行=接续/备注，豁免）。"""
    picked: list[str] = []
    inside = False
    for line in detail.splitlines():
        if line.startswith("【"):
            inside = line.startswith("【指令与参数】")
            continue
        if inside and line.strip() and not line.startswith(" "):
            picked.append(line)
    return picked


# FIX-1（2026-09-20，spec-audit P1）：四要素豁免收口为单一事实源 _facet_exempt，
# lines 与 detail 两条路径共用。根因不是文案写漏，是门设计缺陷——同一份数据两套
# 标准：lines 环带两条豁免（「示例：」行、不含 BOT_ 配置键的指引行），detail 环
# 对 _detail_facet_section_lines 的输出零豁免；HELP-1 单源重构（_compose_help_detail
# 把 lines 注入 detail 的【指令与参数】小节）使 detail 行即 lines 行后，同一条行
# 先被一环放过、再被另一环判红（确定性红：「修改方式：…」/「示例：…」/
# 「识别模型管理：…」行）。防回归守卫见 test_facet_rule_paths_must_agree_on_same_line。
_TONE4_EXEMPT_KEY_RE = re.compile(r"BOT_[A-Z0-9_]{4,}")


def _facet_exempt(line: str) -> bool:
    """四要素约束的唯一豁免源（lines 与 detail 两条路径共用）：
    示例行与不含配置键的指引行不在此约束内（与合并转发/点歌同口径）。"""
    return line.startswith("示例：") or _TONE4_EXEMPT_KEY_RE.search(line) is None


def _lines_facet_missing(line: str) -> tuple[str, ...]:
    """lines 路径（摘要行）对单行的四要素判定：缺失要素列表，豁免行恒为空。"""
    if _facet_exempt(line):
        return ()
    return tuple(facet for facet in _TONE4_FACETS if facet not in line)


def _detail_facet_missing(line: str) -> tuple[str, ...]:
    """detail 路径（【指令与参数】顶层行）对单行的四要素判定：
    与 lines 路径共用 _facet_exempt 单一豁免源，判据完全等价（不得再各持一套标准）。"""
    if _facet_exempt(line):
        return ()
    return tuple(facet for facet in _TONE4_FACETS if facet not in line)


def test_tone3_config_lines_carry_four_facets() -> None:
    """限流/群摘要/视频理解：参数行必须四要素齐全，不得退回配置键说明式。

    lines 与 detail 两条路径经 _facet_exempt 共享同一豁免（FIX-1）：
    detail 的【指令与参数】小节由 lines 派生（HELP-1 单源），两套判据必须等价。
    """
    failures: list[str] = []
    for entry in _merged():
        topic = str(entry["topic"])
        if topic not in _TONE4_TOPICS:
            continue
        missing: list[str] = []
        for line in entry["lines"]:
            missing += [
                f"lines 缺 {facet}：{line[:40]}…"
                for facet in _lines_facet_missing(line)
            ]
        for line in _detail_facet_section_lines(str(entry["detail"])):
            missing += [
                f"detail 缺 {facet}：{line[:40]}…"
                for facet in _detail_facet_missing(line)
            ]
        if missing:
            failures.append(f"{topic} 四要素缺失：{missing}")
    assert not failures, "；".join(failures)


def test_facet_rule_paths_must_agree_on_same_line() -> None:
    """防回归守卫（FIX-1）：同一行经 lines 与 detail 两条路径必须得到相同判定。

    三层钉死，任何一层破防都会红：
    ① _facet_exempt 与豁免规格（「示例：」前缀行、无 BOT_ 配置键行两条规则）在
       真实数据全集上逐行一致——守卫内独立内联重述规格，防止豁免源被单边改写；
    ② 真实数据行全集（三 topic 的 lines ∪ detail【指令与参数】顶层行）上，
       lines 路径判定与 detail 路径判定逐一相等——若再现「一环有豁免、一环零豁免」
       的双标准结构（本缺陷的修复前形态），这里直接红；
    ③ detail 由 lines 派生（HELP-1）：detail 每条顶层行必须能在 lines 全集找到
       同文行，找不到即派生关系又变（加前缀/改写），等价性失去前提，同样红。
    """
    summary_lines: set[str] = set()
    detail_lines: set[str] = set()
    for entry in _merged():
        if str(entry["topic"]) not in _TONE4_TOPICS:
            continue
        summary_lines.update(str(line) for line in entry["lines"])
        detail_lines.update(_detail_facet_section_lines(str(entry["detail"])))
    universe = sorted(summary_lines | detail_lines)
    assert universe, "守卫数据为空=门在空转"
    for line in universe:
        spec_exempt = line.startswith("示例：") or re.search(r"BOT_[A-Z0-9_]{4,}", line) is None
        assert _facet_exempt(line) == spec_exempt, f"豁免源与规格漂移：{line[:40]}…"
        assert _lines_facet_missing(line) == _detail_facet_missing(line), (
            f"lines/detail 判据再度分叉：{line[:40]}… → "
            f"lines={_lines_facet_missing(line)} detail={_detail_facet_missing(line)}"
        )
    orphan_detail = sorted(detail_lines - summary_lines)
    assert not orphan_detail, (
        "detail【指令与参数】出现 lines 之外的孤行（HELP-1 派生关系已变，"
        f"两路径等价性失去前提）：{[ln[:40] for ln in orphan_detail]}"
    )


# ---------------------------------------------------------------------------
# 叙述文档手写计数门（2026-09-21 全面统一性审计 V2-1 根修）
# ---------------------------------------------------------------------------
# 旧面只有两条（test_commands_md_defers_counts_to_generated_catalog /
# test_readme_md_indexes_catalog_without_hardcoded_counts），各扫一个文件、
# 词表只有「模块|别名」⇒ AGENTS/HANDBOOK/CODE-MAP/config-catalog/HANDOFF
# 里的「529 字段 / 77 topics / 501 别名 / 6 模板 / 20 域 / 33 路由 / 库 26」
# 一类"会随代码漂移的手写总数"**全无人管**（实测 14 处已漂移）。
# 本门把「叙述文档不手写可过期计数」立法到全量叙述面：要么指向真身/机器册，
# 要么显式标注为历史当时值；两者都没有即红。生成物（docs/auto-facts.md、
# docs/command-catalog.md）是权威本体，不在扫描面内。

_NARRATIVE_DOCS: tuple[str, ...] = (
    "AGENTS.md",
    "HANDOFF-NEXT.md",
    "HANDOFF-V21R6-TESTING.md",
    "docs/README.md",
    "docs/HANDBOOK.md",
    "docs/CODE-MAP.md",
    "docs/config-catalog-full.md",
    "docs/acceptance-manual.md",
    "docs/design/backend-protocol-plan.md",
)

# 形如「633 个 bot_* 字段」「77 topics」「501 别名」「20 域」「26 库」的手写总数。
_VOLATILE_COUNT_RE = re.compile(
    r"(?<![\w./-])\d{1,5}\s*(?:个|条|枚|张|项|余)?\s*"
    r"(?:bot_\*\s*)?(?:字段|topics?|主题数|别名|模板|域|路由|交付物|库)(?!\w)"
)
# 放行条件＝同行给了权威指针，或明说是历史/当时值。
_AUTHORITY_MARKER_RE = re.compile(
    r"auto-facts|机器册|为准|当时|历史|曾核|实测|以目录|不手写|勿手写|数量不在此|现值|真身"
)


def _volatile_count_findings(
    root: Path, files: tuple[str, ...] = _NARRATIVE_DOCS
) -> list[str]:
    """叙述文档里「手写可过期计数且无权威指针/历史限定」的行，逐条 `文件:行号 片段`。"""
    findings: list[str] = []
    for rel in files:
        path = root / rel
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _VOLATILE_COUNT_RE.search(line) and not _AUTHORITY_MARKER_RE.search(line):
                findings.append(f"{rel}:{number} -> {line.strip()[:90]}")
    return findings


def test_narrative_docs_defer_volatile_counts_to_machine_ledger() -> None:
    """叙述文档不许手写会随代码漂移的总数；要写就得指向机器册/真身或标明是历史当时值。"""
    findings = _volatile_count_findings(ROOT)
    assert not findings, (
        "以下叙述文档写了会过期的手写计数，且没有权威指针/历史限定"
        "（改法：指向 docs/auto-facts.md 或真身定义处，或在同行标明「当时值」）：\n"
        + "\n".join(findings)
    )


def test_volatile_count_gate_detects_planted_line(tmp_path: Path) -> None:
    bad_file = tmp_path / "docs" / "CODE-MAP.md"
    bad_file.parent.mkdir(parents=True)
    bad_file.write_text("这里写了 529 字段 和 20 域。\n", encoding="utf-8")
    planted = _volatile_count_findings(tmp_path, ("docs/CODE-MAP.md",))
    assert planted, "注毒的裸计数未被抓到＝门没牙"

    good_file = tmp_path / "docs" / "CODE-MAP.md"
    good_file.write_text(
        "字段数以机器册 docs/auto-facts.md 为准，此处不手写。\n"
        "该席当时值为 529 字段（现值以机器册为准）。\n",
        encoding="utf-8",
    )
    assert not _volatile_count_findings(tmp_path, ("docs/CODE-MAP.md",)), "带权威指针的行被误拦"

