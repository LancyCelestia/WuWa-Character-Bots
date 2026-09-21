"""审查 Q 组文案统一负向扫描门（2026-09-15，Q-01/Q-02 审计固化）。

背景：A 方文案审计 Q-01（数据源失败 4 种句式散装：晚点再试试？/稍后再试试？/
稍后再试一次。/「，稍后再试。」）、Q-02（权限拒绝 6 种写法散装，含卖萌体），
违反用户铁律「所有文本统一口径/风格/话术，前后不矛盾」。真相源池 =
user_copy.py（RWC3 后真身=domains/chat_reply/capabilities/user_copy.py；
DATASOURCE_FAILURE_TEMPLATES / ADMIN_GATE_TEMPLATES，
首条即历史统一句，语气零漂移）。本门把「同类失败文案只从池里出」固化为常驻
pytest 门，防未来批次回潮。

扫描范围：plugins/bot_unified_runtime 全包 *.py（capabilities + sources +
character + runtime + llm 等；sources 层零依赖池跨层引用已随 Q-01 入池，
不在豁免面）。

扫描器：纯 AST 字符串字面量（普通串 + f-string 字面量块），零 import 被扫
模块；docstring、日志调用、正则模式参天然排除（纪律同 test_copy_redline_gate）。

白名单（豁免登记同步见 user_copy.py 模块头）：
- 文件级（禁碰域/池本体）：user_copy.py（池本体，变体即真相源）；
  __init__.py（绝对不碰）；subscribe.py / subscribe_v2.py（并行在飞禁碰域，
  含「没有权限操作该订阅」资源属主语义）；group_info.py（禁碰域卖萌体残留，
  待该文件域批次收口）。
- 单元级：echo.py help 文本对兜底行为的历史引用示例（「美股行情暂时拉不到，
  晚点再试试？」「汇率数据暂时拉不到，稍后再试。」）——help 口径变更牵动
  command-catalog 同步门（域外），按引用原文保留；豁免语义 = 命中单元含
  「{marker}」括注引用形态（help 引用带直角引号，输出本体不带），精确区分
  「引用示例」与「输出本体」，不整文件放行。

Q-03 扩展（2026-09-15 语气符统一批）：失败/权限/拒绝类用户可见文案禁拖尾
语气符「～」——守岸人语气 = 温和但不拖尾音，句号收尾（先例 meme_library
64efadf；对齐 user_copy.py 池内句式）。成功回执/正常对话类按令保留，须在
Q03_UNIT_WHITELIST 精确登记。Q-03 走独立作用域（Q03_SCOPE_FILES：6 能力
文件 + meme_library 防回潮），不受 Q01/Q02 文件级白名单影响（group_info
卖萌体残留另案，仅豁免 Q01/Q02，Q-03 照扫）。检测面 = 单元 strip 后以
「～/〜」结尾的拖尾形态；字符类/清洗集逻辑字面量（「～」居串中，如
_BOUNDARY_CHARS、regex 模式串）天然不命中，无需豁免。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.capabilities import user_copy

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PKG = REPO_ROOT / "plugins" / "bot_unified_runtime"

# ---------------------------------------------------------------------------
# 规则常量
# ---------------------------------------------------------------------------

# Q-01 数据源失败旧句式（4 种）：命中即红；新文案一律走
# user_copy.DATASOURCE_FAILURE_TEMPLATES。
Q01_PATTERNS: tuple[str, ...] = (
    "晚点再试试？",
    "稍后再试试？",
    "稍后再试一次。",
    "，稍后再试。",  # 锚定逗号，放行「请稍后再试。」等非池句式
)

# Q-02 权限拒绝旧写法标记：命中即红；新文案一律走
# user_copy.ADMIN_GATE_TEMPLATES（超管门槛等语义特殊处走豁免登记）。
Q02_PATTERNS: tuple[str, ...] = (
    "先收好这份心意",  # 卖萌体标记
    "先不给你翻",  # 卖萌体标记
    "没有权限操作",
    "只有管理员才能",
    "只有管理员能看",
)

# ---------------------------------------------------------------------------
# Q-03 语气符门（2026-09-15 扩展批）：失败/权限/拒绝类文案禁拖尾「～」，
# 成功保留处按单元子串精确豁免（机制说明见模块 docstring Q-03 段）。
# ---------------------------------------------------------------------------

# Q-03 作用域（仓库相对路径）：语气符收口涉及的 6 能力文件 + meme_library
# （64efadf 已收口，纳入扫描防回潮、并保护其成功保留句的保留裁定）。
# 独立于 Q01/Q02 的 FILE_WHITELIST——group_info 的卖萌体残留豁免只限
# Q01/Q02 模式，Q-03 照扫不豁免。
Q03_SCOPE_FILES: frozenset[str] = frozenset(
    {
        # v21r2 W11 media 重组：media_archive 真身迁 domains/media/capabilities/，
        # 门锚同波随迁指真身（旧路径已是 re-export 垫片，扫垫片=防回潮静默失效）。
        "plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py",
        # v21r2 RWC3 chat_reply/capabilities 重组：group_info 真身迁
        # domains/chat_reply/capabilities/，门锚同波随迁指真身（旧路径已是垫片）。
        "plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py",
        # reminder/weather/moegirl 旧路径锚=各自域重组波（W10/W3/W16）已登记遗留，
        # 非本波文件零触碰。
        *(
            f"plugins/bot_unified_runtime/capabilities/{name}.py"
            for name in (
                "reminder",
                "weather",
                "moegirl",
            )
        ),
        # v21r2 W6 meme 重组：randpic/meme_library 真身迁 domains/meme/capabilities/，
        # 门锚同波随迁指真身（旧路径已是 re-export 垫片，扫垫片=防回潮静默失效）。
        "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py",
        "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py",
    }
)

# Q-03 成功回执/正常对话类保留处（文件 → [(单元须含的子串, 理由)]；子串含
# 「～」本体、精确到句）。本批 6 文件零保留处；现网唯一保留 = meme_library
# 成功发送回执（正常对话类，64efadf 裁定保留）。
Q03_UNIT_WHITELIST: dict[str, list[tuple[str, str]]] = {
    "plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py": [
        ("给你偷来一张表情～", "成功发送回执（正常对话类），64efadf 裁定保留"),
    ],
}

# 文件级豁免（仓库相对路径 → 理由）。理由非空由门测试校验。
FILE_WHITELIST: dict[str, str] = {
    # v21r2 RWC3：user_copy 真身迁 domains/chat_reply/capabilities/，豁免锚随迁
    # （真身仍在 RUNTIME_PKG 扫描面内，锚不随迁=池体句式裸扫必红）。
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py": "池本体：变体句即真相源",
    "plugins/bot_unified_runtime/__init__.py": "禁碰域（绝对不碰），豁免登记见 user_copy.py 头注释",
    "plugins/bot_unified_runtime/domains/subscribe/capabilities/subscribe.py": "v21r2 W8 随迁指真身；「没有权限操作该订阅」为资源属主语义",
    "plugins/bot_unified_runtime/domains/subscribe/capabilities/subscribe_v2.py": "v21r2 W8 随迁指真身；群内订阅管理员语义 + 资源属主语义",
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py": "禁碰域（RWC3 随真身迁锚）；卖萌体残留待该文件域批次收口",
}

# 单元级豁免（文件 → [(命中单元须含的子串, 理由)]）。
UNIT_WHITELIST: dict[str, list[tuple[str, str]]] = {
    # v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/，单元豁免锚随迁。
    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py": [
        (
            "美股行情暂时拉不到，晚点再试试？",
            "help 文本对兜底行为的历史引用示例，非输出本体；口径变更牵动 command-catalog 同步门（域外）",
        ),
        (
            "汇率数据暂时拉不到，稍后再试。",
            "help 文本对兜底行为的历史引用示例，非输出本体；口径变更牵动 command-catalog 同步门（域外）",
        ),
    ],
}

_LOG_ATTRS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fatal"}
)


@dataclass(frozen=True)
class Finding:
    pattern_class: str  # "Q01" | "Q02"
    pattern: str
    rel_path: str
    lineno: int
    excerpt: str

    def render(self) -> str:
        return f"[{self.pattern_class}] {self.pattern!r} @ {self.rel_path}:{self.lineno}  {self.excerpt!r}"


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _logger_call_node_ids(tree: ast.AST) -> set[int]:
    """日志调用整棵跳过（纪律同 test_copy_redline_gate）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in _LOG_ATTRS:
                continue
            base = node.func.value
            if (
                (isinstance(base, ast.Name) and base.id in {"logger", "log", "logging"})
                or (isinstance(base, ast.Attribute) and base.attr in {"logger", "log"})
            ):
                ids.add(id(node))
    return ids


class _UnitCollector(ast.NodeVisitor):
    """收集用户可见字符串单元；日志调用整棵剪枝（ast.walk 不剪枝，须用访问器）。"""

    def __init__(self, excluded: set[int], docstrings: set[int]) -> None:
        self._excluded = excluded
        self._docstrings = docstrings
        self.units: list[tuple[str, int]] = []

    def generic_visit(self, node: ast.AST) -> None:
        if id(node) in self._excluded:
            return
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if id(node) in self._excluded:
            return
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self._docstrings:
            self.units.append((node.value, node.lineno))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        chunks = [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and id(value) not in self._docstrings
        ]
        if chunks:
            self.units.append(("".join(chunks), node.lineno))
        # FormattedValue 内嵌表达式继续下探。
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                self.visit(value.value)


def _user_visible_units(path: Path) -> list[tuple[str, int]]:
    """收集 (文本, 行号)：字符串常量 + f-string 字面量块；docstring/日志排除。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _UnitCollector(_logger_call_node_ids(tree), _docstring_node_ids(tree))
    collector.visit(tree)
    return collector.units


def scan_file(path: Path, *, rel_path: str | None = None) -> list[Finding]:
    """扫描单文件，返回未豁免的命中。"""
    if rel_path is None:
        rel_path = path.resolve().relative_to(REPO_ROOT).as_posix()
    if rel_path in FILE_WHITELIST:
        return []
    unit_exemptions = UNIT_WHITELIST.get(rel_path, [])
    findings: list[Finding] = []
    for text, lineno in _user_visible_units(path):
        for pattern_class, patterns in (("Q01", Q01_PATTERNS), ("Q02", Q02_PATTERNS)):
            for pattern in patterns:
                if pattern not in text:
                    continue
                # 单元级豁免：help 引用以「{marker}」直角引号括注形态出现才算
                # 引用示例；输出本体（裸串）不豁免。
                if any(f"「{marker}」" in text for marker, _reason in unit_exemptions):
                    continue
                excerpt = " ".join(text.split())[:48]
                findings.append(
                    Finding(pattern_class, pattern, rel_path, lineno, excerpt)
                )
    return findings


def scan_package() -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(RUNTIME_PKG.rglob("*.py")):
        findings.extend(scan_file(path))
    return findings


def scan_q03_file(path: Path, *, rel_path: str | None = None) -> list[Finding]:
    """Q-03 门：作用域文件内，拖尾语气符「～」的用户可见单元即命中。

    只认「strip 后以『～/〜』结尾」的拖尾形态（失败/权限/拒绝类文案的确诊
    形态）；字符类/清洗集等逻辑字面量「～」居串中，天然不命中，无需豁免。
    保留处按单元子串精确豁免（Q03_UNIT_WHITELIST），不做文件级放行；本扫描
    不受 Q01/Q02 的 FILE_WHITELIST 影响（group_info 照扫）。
    """
    if rel_path is None:
        rel_path = path.resolve().relative_to(REPO_ROOT).as_posix()
    if rel_path not in Q03_SCOPE_FILES:
        return []
    markers = [marker for marker, _reason in Q03_UNIT_WHITELIST.get(rel_path, [])]
    findings: list[Finding] = []
    for text, lineno in _user_visible_units(path):
        stripped = text.rstrip()
        if not stripped.endswith(("～", "〜")):
            continue
        if any(marker in text for marker in markers):
            continue
        excerpt = " ".join(text.split())[:48]
        findings.append(
            Finding("Q03", "拖尾语气符「～」（失败/权限/拒绝类）", rel_path, lineno, excerpt)
        )
    return findings


def scan_q03_scope() -> list[Finding]:
    """扫全部 Q-03 作用域文件（meme_library 含内，防回潮）。"""
    findings: list[Finding] = []
    for rel in sorted(Q03_SCOPE_FILES):
        findings.extend(scan_q03_file(REPO_ROOT / rel, rel_path=rel))
    return findings


# ---------------------------------------------------------------------------
# 门测试：现网必须全绿
# ---------------------------------------------------------------------------


def test_scope_covers_sources_layer() -> None:
    """扫描面自证：capabilities 与 sources 都在面内（Q-01 主战场在 sources）。"""
    for rel in (
        "plugins/bot_unified_runtime/capabilities/market.py",
        # v21r4-B RET3：sources/market_data 垫片已退役，代表件改钉 canonical 真身。
        "plugins/bot_unified_runtime/domains/finance/data/market_data.py",
        "plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py",
    ):
        assert (REPO_ROOT / rel).exists(), rel
    assert len(list(RUNTIME_PKG.rglob("*.py"))) >= 100, "扫描面异常收缩"


def test_current_tree_no_scattered_failure_copy() -> None:
    """主门：现网树数据源失败/权限拒绝旧句式必须零池外硬编码（豁免后）。"""
    findings = scan_package()
    assert not findings, (
        "池外硬编码旧句式命中（逐条核实：真违例改入 user_copy 池 / 误报修白名单并登记理由）：\n"
        + "\n".join(f.render() for f in findings)
    )


def test_whitelist_integrity() -> None:
    """白名单不腐化：文件存在、理由非空、单元级登记含可匹配子串。"""
    for rel, reason in FILE_WHITELIST.items():
        assert (REPO_ROOT / rel).exists(), f"白名单指向不存在的文件：{rel}"
        assert str(reason).strip(), f"白名单缺豁免理由：{rel}"
    for rel, entries in UNIT_WHITELIST.items():
        assert (REPO_ROOT / rel).exists(), f"单元白名单指向不存在的文件：{rel}"
        for marker, reason in entries:
            assert marker.strip(), f"单元白名单子串为空：{rel}"
            assert str(reason).strip(), f"单元白名单缺豁免理由：{rel}"


def test_gate_detects_regression(tmp_path: Path) -> None:
    """真红：往能力目录语义下塞旧句式必须命中；豁免登记后转绿（防门空转）。"""
    dirty = tmp_path / "dirty_sample.py"
    dirty.write_text(
        'MSG = "行情数据暂时拉不到，晚点再试试？"\n'
        'DENIED = "只有管理员才能做这件事。"\n',
        encoding="utf-8",
    )
    findings = scan_file(dirty, rel_path="plugins/bot_unified_runtime/capabilities/fake_new.py")
    classes = {f.pattern_class for f in findings}
    assert classes == {"Q01", "Q02"}
    # 文件级豁免生效：同内容挂池本体语义路径 → 零命中。
    assert not scan_file(dirty, rel_path="plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py")
    # 单元级豁免生效：echo.py 语义路径下，含登记子串的单元豁免、其余仍红。
    echo_dirty = tmp_path / "echo_dirty.py"
    echo_dirty.write_text(
        'HELP = "行情拉不到回「美股行情暂时拉不到，晚点再试试？」"\n'
        'BODY = "美股行情暂时拉不到，晚点再试试？"\n',
        encoding="utf-8",
    )
    echo_findings = scan_file(
        echo_dirty, rel_path="plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
    )
    # HELP 行命中登记子串被豁免；BODY 行（输出本体）仍红。
    assert len(echo_findings) == 1
    assert echo_findings[0].lineno == 2


def test_gate_excludes_docstring_and_logging(tmp_path: Path) -> None:
    """真绿：docstring/注释/日志中的旧句式不算用户可见面（不误报）。"""
    clean = tmp_path / "clean_sample.py"
    clean.write_text(
        '"""docstring 提到 晚点再试试？ 不算用户可见文案。\n"""\n'
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def go():\n"
        '    logger.warning("稍后再试一次。（日志面不入门）")\n'
        '    MSG = "行情数据暂时拉不到，请稍后再试。"  # 请字开头非池句式\n'
        "    return MSG\n",
        encoding="utf-8",
    )
    assert not scan_file(clean, rel_path="plugins/bot_unified_runtime/capabilities/fake_clean.py")


def test_q03_scope_no_trailing_tilde_in_failure_copy() -> None:
    """Q-03 扩展主门：作用域内失败/权限/拒绝类文案禁拖尾语气符「～」。"""
    findings = scan_q03_scope()
    assert not findings, (
        "失败/权限/拒绝类文案拖尾语气符「～」命中（真违例去「～」句号收尾 / "
        "成功保留处登记 Q03_UNIT_WHITELIST 并写明理由）：\n"
        + "\n".join(f.render() for f in findings)
    )


def test_q03_whitelist_integrity() -> None:
    """Q-03 白名单不腐化：作用域文件存在；保留登记须含「～」子串且理由非空。"""
    for rel in Q03_SCOPE_FILES:
        assert (REPO_ROOT / rel).exists(), f"Q-03 作用域指向不存在的文件：{rel}"
    for rel, entries in Q03_UNIT_WHITELIST.items():
        assert rel in Q03_SCOPE_FILES, f"Q-03 白名单文件不在作用域内：{rel}"
        for marker, reason in entries:
            assert ("～" in marker) or ("〜" in marker), f"Q-03 保留登记子串缺语气符本体：{rel}"
            assert str(reason).strip(), f"Q-03 白名单缺豁免理由：{rel}"


def test_q03_gate_detects_regression_and_spares_logic_literals(tmp_path: Path) -> None:
    """Q-03 真红/真绿：拖尾「～」失败句必红；成功保留处豁免；字符类逻辑字面量不误报。"""
    dirty = tmp_path / "dirty_q03.py"
    dirty.write_text('MSG = "额度用完啦，明天再来吧～"\n', encoding="utf-8")
    findings = scan_q03_file(
        dirty,
        rel_path="plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py",
    )
    assert len(findings) == 1
    assert findings[0].pattern_class == "Q03"
    assert findings[0].lineno == 1

    # 作用域外文件不扫（并行在飞域零打扰）。
    assert not scan_q03_file(
        dirty, rel_path="plugins/bot_unified_runtime/capabilities/chat.py"
    )

    # 成功回执保留处：单元含登记子串即豁免转绿。
    keep = tmp_path / "keep_q03.py"
    keep.write_text('OK = "给你偷来一张表情～"\n', encoding="utf-8")
    assert not scan_q03_file(
        keep, rel_path="plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py"
    )

    # 字符类/清洗集逻辑字面量（「～」居串中）非用户文案，天然不命中、无需豁免。
    logic = tmp_path / "logic_q03.py"
    logic.write_text(
        'BOUNDARY = "，,。！？!?：:、 的了呢吗呀啊哈～~哦嘛咯哇"\n'
        'PATTERN = r"^[，,。．.!！?？~～、\\s]+|[，,。．.!！?？~～、\\s]+$"\n',
        encoding="utf-8",
    )
    assert not scan_q03_file(
        logic, rel_path="plugins/bot_unified_runtime/capabilities/group_info.py"
    )


# ---------------------------------------------------------------------------
# 池引用行为抽查（零网络：直接调各 sources 纯格式化函数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("formatter", "reason"),
    [
        ("format_market_brief", "行情数据暂时拉不到"),
        ("format_northbound_brief", "北向资金数据暂时拉不到"),
    ],
)
def test_pool_output_membership_market(formatter: str, reason: str) -> None:
    """池引用处输出 ∈ 池集合（market / northbound 快查链路）。"""
    from plugins.bot_unified_runtime.domains.finance.data import market_data

    fn = getattr(market_data, formatter)
    renders = {template.format(reason=reason) for template in user_copy.DATASOURCE_FAILURE_TEMPLATES}
    assert fn([]) in renders


def test_pool_output_membership_fx_and_news() -> None:
    """池引用处输出 ∈ 池集合（fx / news 快查链路）。"""
    from plugins.bot_unified_runtime.domains.finance.data import fx_data
    from plugins.bot_unified_runtime.domains.subscribe.feeds import news_feeds

    fx_renders = {
        template.format(reason="汇率数据暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
    assert fx_data.format_fx_brief([]) in fx_renders
    news_renders = {
        template.format(reason="快报暂时拉不到")
        for template in user_copy.DATASOURCE_FAILURE_TEMPLATES
    }
    assert news_feeds.format_news_brief([], "综合") in news_renders


def test_q04_self_reference_unified() -> None:
    """Q-04：三处自称统一第三人称「守岸人」，旧第一人称混用句不得回潮。"""
    # v21r2 RWC3：chat/echo 真身迁 domains/chat_reply/capabilities/，文本锚随真身
    # （旧路径为 re-export 垫片，无表体）。
    chat_src = (
        RUNTIME_PKG / "domains" / "chat_reply" / "capabilities" / "chat.py"
    ).read_text(encoding="utf-8")
    # P2-4 用户裁定二改（2026-09-15，不泄露>威慑+守岸人语气≥10 变体）：
    # 拦截回复走 _INJECTION_GUARD_TEMPLATES 池+同会话轮换；零防御焦点
    # 泄露红线不变（不提系统提示/密钥/本机文件）；旧威慑句与第一人称
    # 混用句一并锁死不得回潮。
    assert "_INJECTION_GUARD_TEMPLATES" in chat_src
    assert "injection_guard_message(" in chat_src
    assert "泄露系统提示" not in chat_src
    assert "本机文件" not in chat_src
    assert "我不能泄露系统提示" not in chat_src
    assert "我会继续按守岸人的设定" not in chat_src
    import plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat as _chat_mod

    assert len(_chat_mod._INJECTION_GUARD_TEMPLATES) >= 10
    assert len(set(_chat_mod._INJECTION_GUARD_TEMPLATES)) == len(
        _chat_mod._INJECTION_GUARD_TEMPLATES
    )
    # 池内禁词：防御焦点词零出现（P2-4 红线的池级锁）。
    for _variant in _chat_mod._INJECTION_GUARD_TEMPLATES:
        assert "系统提示" not in _variant
        assert "密钥" not in _variant
        assert "本机" not in _variant
        assert "脚本" not in _variant
        assert "注入" not in _variant
    # v21r2 W6 meme 重组：真身迁 domains/meme/，文本锚同波随迁（旧路径为垫片）。
    meme_src = (
        RUNTIME_PKG / "domains" / "meme" / "capabilities" / "meme_library.py"
    ).read_text(encoding="utf-8")
    # 审查 Q-03：失败/限流类文案统一去语气符「～」，旧拖尾音句不得回潮。
    assert "多发点图给守岸人收藏吧。" in meme_src
    assert "多发点图给守岸人收藏吧～" not in meme_src
    assert "秒后再来偷。" in meme_src
    assert "让我收藏" not in meme_src
    echo_src = (
        RUNTIME_PKG / "domains" / "chat_reply" / "capabilities" / "echo.py"
    ).read_text(encoding="utf-8")
    assert "守岸人这边记称谓的小本本暂时打不开" in echo_src
    assert "是我这边要修的" not in echo_src
    # media_archive 卖萌体（Q-02）与第一人称混用同步收口。
    media_src = (
        RUNTIME_PKG / "domains" / "media" / "capabilities" / "media_archive.py"
    ).read_text(encoding="utf-8")
    assert "这份心意守岸人先记下了" in media_src
    assert "先收好这份心意" not in media_src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
