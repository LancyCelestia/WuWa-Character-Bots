"""UNI1 fix1/fix2（评审 C-1 / M-3 / fix2 I-1 / I-2 / I-3 / Minor M-a / M-b）：
前端 labels ↔ 后端 control_plane 的跨语言同值门（pytest 侧）。

为什么在 pytest 而不在 ``node --test``（C-1 裁定，fix1）：
  ``control_plane/metrics.py`` / ``webui_stats.py`` / ``webui_memory_graph.py`` 三件本波**未入库**
  （随控制面整波提交），JS 测试直读它们 = 干净克隆上 ENOENT **失败**而非 skip，并经
  ``test_webui_constitution.py::test_pure_function_tests`` 把整个前端门拖红；失败消息对改后端的
  Python 作者零可达。pytest 侧则：后端模块缺失 → **显式 skip 并点名路径**（控制面在本 checkout
  属可选特性），失败恰好落在改动字面量的一方。node 侧（``webui/src/lib/labels.test.ts``）
  保持密封：只读 webui/ 以内，锁 labels ↔ 枚举 ↔ 标签的纯前端三向自洽。

覆盖（全部**只读源码字面量**解析，不 import、不执行任何一侧代码）：
  1) stats 窗枚举：labels.ts ``STATS_WINDOWS`` == ``metrics._WINDOW_SECONDS`` == ``webui_stats._WINDOW_SECONDS`` 键集
  2) 跨度同值与图谱枚举：labels.ts ``WINDOW_SECONDS``/``GRAPH_WINDOWS`` == 后端三张闭集（含 ``all: None`` 无界）
  3) 桶闭集（fix2 I-3 补齐宣称面）：labels.ts ``BUCKETS`` == ``webui_stats._BUCKETS``（顺序敏感）
     == ``metrics.py`` trends 两张**内联**桶组（``bucket not in (`` 准入门 / ``view in (`` 分派门，集合比较）
  4) DataState reason 白名单（fix1 M-3/I-1）：后端 ``_failure("source_unavailable", …)`` 可产出的码
     ⊆ semantics.ts ``KNOWN_REASONS``（**严判，不被任何并集稀释**）；动态点按 ``(文件, 变量)`` 注册表治理
  5) payload reason **按文件分面判定**（fix2 I-1/I-2，替换 fix1 的全局并集松判据）：
     消费链决定判据——plugins/stats/metrics/memory_graph 的 payload reason 终走 describeReason →
     只认 ``KNOWN_REASONS``（加本文件登记的豁免）；knowledge.tsx 条目短标签表只有
     ``webui_knowledge.py`` 一块面可用（评审 M13：裸码 ``no_dedicated_store`` 上组级面曾门绿上屏）。
     静态不可判定点（f-string/``.format``/变量赋值）必须登记 ``PAYLOAD_DYNAMIC_REASON_SITES``
     并给溯源规则——不注册即红、注册了候选码仍须过本面判据，**不许静默跳过**（评审 M6 实证的洞）。
  6) 前端未知符号棘轮（fix2 收编 Minor M-a）：``pages/*.tsx`` **全部页面**的 `'—'` 字面量/内联
     命中数 ≤ 在册基线（旧 node 锁只判 owned 页，未登记页新抄门绿——评审探针 B3）。
  7) 枚举手抄棘轮基线自锁（fix2 收编 Minor M-b）：labels.test.ts 的 ``trackedUnmigrated`` 清单
     本身被机器核验——基线条目必须指向真实存在的页面、实际扫到的 ``const WINDOWS`` 页必须仍在册
     （改名/换页躲锁从门绿变门红——评审探针 C3）；还债（命中只减）恒绿不砸门。

测试缝（演示 skip 分支非死代码，评审要求双向证明）：环境变量 ``UNI1_CONTROL_PLANE_DIR`` 可把
后端真相源目录指到别处；指到不存在的路径实跑，本文件依赖后端的用例应全部 skip 而非 fail
（例 6/7 纯前端件不依赖后端，恒真跑）。缺省 = 仓库内真实路径，正常 checkout 下必须真跑真绿。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LABELS_TS = REPO / "webui" / "src" / "lib" / "labels.ts"
SEMANTICS_TS = REPO / "webui" / "src" / "lib" / "semantics.ts"
KNOWLEDGE_TSX = REPO / "webui" / "src" / "pages" / "knowledge.tsx"
LABELS_TEST_TS = REPO / "webui" / "src" / "lib" / "labels.test.ts"
PAGES_DIR = REPO / "webui" / "src" / "pages"

# 测试缝：见模块 docstring——只为把 skip 分支跑给人看，缺省走真实路径。
CONTROL_PLANE = Path(
    os.environ.get("UNI1_CONTROL_PLANE_DIR")
    or (REPO / "plugins" / "bot_unified_runtime" / "control_plane")
)

# reason 族的真相源闭包（与 semantics.ts KNOWN_REASONS 注释里的溯源面一致）。
DATA_SURFACE_FILES = (
    "metrics.py",
    "webui_stats.py",
    "webui_knowledge.py",
    "webui_plugins.py",
    "webui_memory_graph.py",
)

# ---- 后端字面量解析（`{"24h": 86_400, "7d": 7 * 86_400, "all": None}` / `("hour", "day")` ----


def _seconds_expr(raw: str, owner: str) -> int:
    factors = [part.strip().replace("_", "") for part in raw.split("*")]
    assert all(
        re.fullmatch(r"\d+", part) for part in factors if part
    ), f"无法解析 {owner} 的跨度字面量 {raw!r}（后端改成表达式请同步本解析器与 labels.ts）"
    value = 1
    for part in factors:
        if part:
            value *= int(part)
    return value


def _py_dict_literal(source: str, name: str) -> dict[str, int | None]:
    block = re.search(rf"^{name}\s*=\s*\{{([^}}]*)\}}", source, re.MULTILINE)
    assert block, f"后端字面量 {name} 形态变了——同步本解析器与 labels.ts 的真相源锚点"
    out: dict[str, int | None] = {}
    for match in re.finditer(r'"([^"]+)"\s*:\s*([^,}]+)', block.group(1)):
        raw = match.group(2).strip()
        out[match.group(1)] = None if raw == "None" else _seconds_expr(raw, name)
    assert out, f"{name} 字面量解析为空（正则与后端写法不匹配？）"
    return out


def _py_tuple_literal(source: str, name: str) -> list[str]:
    block = re.search(rf"^{name}\s*=\s*\(([^)]*)\)", source, re.MULTILINE)
    assert block, f"后端 {name} 字面量形态变了——同步本解析器与 labels.ts 锚点注释"
    return re.findall(r'"([^"]+)"', block.group(1))


# ---- 前端字面量解析（labels.ts / semantics.ts / knowledge.tsx 均为入库件，缺了必须 fail）----


def _read_frontend(path: Path) -> str:
    assert path.is_file(), f"前端源缺失（本仓入库件，不该 skip）：{path}"
    return path.read_text(encoding="utf-8")


def _read_backend(name: str) -> str:
    path = CONTROL_PLANE / name
    if not path.is_file():
        pytest.skip(f"后端模块缺失：{path}（控制面在本 checkout 属可选特性，随控制面整波入库）")
    return path.read_text(encoding="utf-8")


def _frontend_corpus() -> str:
    """webui/src 全部前端源（含 locale json）——供「豁免码确实无人消费」的防腐检查。"""
    parts: list[str] = []
    for path in (REPO / "webui" / "src").rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx", ".json"}:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _ts_string_array(source: str, name: str) -> list[str]:
    block = re.search(rf"export const {name}[^\n]*=\s*\[([^\]]*)\]", source)
    assert block, f"labels.ts {name} 形态变了——同步本解析器"
    codes = re.findall(r"'([^']+)'", block.group(1))
    assert codes, f"labels.ts {name} 解析为空"
    return codes


def _ts_window_seconds(source: str) -> dict[str, int | None]:
    block = re.search(r"export const WINDOW_SECONDS[^\n]*=\s*\{(.*?)\};", source, re.DOTALL)
    assert block, "labels.ts WINDOW_SECONDS 形态变了——同步本解析器"
    out: dict[str, int | None] = {}
    for match in re.finditer(r"(?:'([^']+)'|([A-Za-z_]\w*))\s*:\s*([^,\n]+)", block.group(1)):
        raw = match.group(3).strip()
        key = match.group(1) or match.group(2)
        out[key] = None if raw == "null" else _seconds_expr(raw, "WINDOW_SECONDS")
    assert out, "labels.ts WINDOW_SECONDS 解析为空"
    return out


def _ts_known_reasons(source: str) -> list[str]:
    block = re.search(r"export const KNOWN_REASONS\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL)
    assert block, "semantics.ts KNOWN_REASONS 形态变了——同步本解析器"
    codes: list[str] = []
    for line in block.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):  # 名单内注释行（PAGES2 增补溯源）不计码
            continue
        codes.extend(re.findall(r"'([^']+)'", stripped))
    assert codes, "KNOWN_REASONS 解析为空"
    return codes


def _ts_disabled_reason_codes(source: str) -> set[str]:
    block = re.search(
        r"const DISABLED_REASON_LABEL_KEYS: Record<string, string> = \{(.*?)\};", source, re.DOTALL
    )
    assert block, "knowledge.tsx DISABLED_REASON_LABEL_KEYS 形态变了——同步本解析器"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s*:", block.group(1), re.MULTILINE))


# ---- reason 族解析：DataState 面（严判）+ payload 面（按文件分面，fix2 I-2）----

# _failure("source_unavailable", "码")：DataState.reason 的唯一封闭产出面（describeReason 消费）。
_FAILURE_LITERAL = re.compile(r'_failure\(\s*"source_unavailable"\s*,\s*"([^"]+)"')
# _failure("source_unavailable", 变量)：动态点，(文件名, 变量名) 必须在下表注册。
_FAILURE_DYNAMIC = re.compile(r'_failure\(\s*"source_unavailable"\s*,\s*(?!")([A-Za-z_]\w*)')
# 动态候选值的来源写法：`reason = "x" if … else "y"`（metrics）与 `return "x", None`（knowledge status）。
_REASON_VAR_LINE = re.compile(r"\breason\s*=\s*([^\n]+)")
_STATUS_RETURN_LINE = re.compile(r'return "([a-z_]+)",\s*(?:None|\[\]|\{\})')

# 显式豁免登记（fix1 评审 I-1：_failure 面 reason 走变量的动态点）。新增动态点不注册即红；注册了就要能溯源候选码。
DYNAMIC_REASON_SITES: dict[tuple[str, str], str] = {
    ("metrics.py", "reason"): "reason = \"query_budget_exceeded\" if budget_exceeded else \"read_failed\"",
    ("webui_knowledge.py", "status"): "status 来自 _kb_document_index/_meme_tag_counts 的 return \"码\", None",
}

# payload 赋值点扫描（fix2 I-1）：抓「值表达式」而不是只抓字面量——静态不可判定的形态
# （f"…"/.format(/变量/函数调用）classify 返回 None，进动态点注册表，不注册即红。
# 键=表达式原文 strip 后整串（行尾注释/多行折行会改变键 → 触发重审，属预期严格性；评审 M6 的
# `x["reason"] = f"generated_{code}"` 变异在旧实现里静默滑过，本实现必须报警）。
_PAYLOAD_CONSTANT_DEF = re.compile(r"^_?[A-Z0-9_]*REASON[A-Z0-9_]*\s*=\s*\"([^\"]+)\"", re.MULTILINE)
_PAYLOAD_SITE_PATTERNS = (
    re.compile(r'"reason"\s*:\s*([^,}\n]+)'),  # dict 条目（组级/payload/嵌套诊断共用一形）
    re.compile(r'\["reason"\]\s*=\s*([^\n]+)'),  # 下标赋值（组级 dict 后置覆写）
)
_STATIC_REASON_EXPR_PATTERNS = (
    re.compile(r'\A"([^"]*)"\Z'),  # 纯字面量
    re.compile(r'\ANone if .+ else "([^"]*)"\Z'),  # knowledge/webui_stats 现行两态
    re.compile(r'\A"([^"]*)" if .+ else "([^"]*)"\Z'),  # 双分支皆字面量
    re.compile(r'\A"([^"]*)" if .+ else None\Z'),
)


def _classify_reason_expr(expr: str) -> set[str] | None:
    """reason 值表达式 → 静态可判定的候选码集；不可判定（f-string/.format/变量/调用）→ None。"""
    if expr == "None":
        return set()
    for pattern in _STATIC_REASON_EXPR_PATTERNS:
        match = pattern.fullmatch(expr)
        if match:
            return {group for group in match.groups() if group is not None}
    return None


def _scan_payload_reason_sites(source: str) -> tuple[set[str], set[str]]:
    """返回（静态字面量码集，动态点表达式键集）。常量定义面（*_REASON* = "码"）保守计入码集。"""
    literals: set[str] = {m.group(1) for m in _PAYLOAD_CONSTANT_DEF.finditer(source)}
    dynamic: set[str] = set()
    for pattern in _PAYLOAD_SITE_PATTERNS:
        for raw in pattern.findall(source):
            expr = raw.strip().rstrip(",").strip()
            codes = _classify_reason_expr(expr)
            if codes is None:
                dynamic.add(expr)
            else:
                literals.update(codes)
    return literals, dynamic


# payload 动态点注册表（fix2 I-1）：键=(文件, 值表达式原文 strip)。新增动态点不注册即红；
# 注册必须带溯源规则，解出的候选码继续过**该文件所属面**的判据（见 PAYLOAD_DYNAMIC_REASON_SITES 用法）。
PAYLOAD_DYNAMIC_REASON_SITES: dict[tuple[str, str], tuple[str, str]] = {
    # _failure(status, reason) 助手本体 `{"reason": reason}`：码从调用点流入，调用点已由
    # test_backend_failure_reason_codes_are_whitelisted 严判 ⊆ KNOWN_REASONS，本体零候选。
    ("metrics.py", "reason"): ("failure_helper_forward", "_failure 助手体透传；调用点已严判"),
    ("webui_stats.py", "reason"): ("failure_helper_forward", "_failure 助手体透传；调用点已严判"),
    ("webui_knowledge.py", "reason"): ("failure_helper_forward", "_failure 助手体透传；调用点已严判"),
    ("webui_plugins.py", "reason"): ("failure_helper_forward", "_failure 助手体透传；调用点已严判"),
    ("webui_memory_graph.py", "reason"): ("failure_helper_forward", "_failure 助手体透传；调用点已严判"),
    (
        "webui_knowledge.py",
        'None if kb_status == "ok" else kb_status',
    ): ("status_return_codes", "kb_status 取 _kb_document_index/_document_index_from 的 status 返回值"),
    (
        "webui_knowledge.py",
        'None if meme_status == "ok" else meme_status',
    ): ("status_return_codes", "meme_status 取 _meme_tag_counts 的 status 返回值"),
    (
        "webui_knowledge.py",
        "_NOT_AVAILABLE_REASON",
    ): ("reason_constant", "模块级常量的字面量定义在同文件内"),
}


def _resolve_payload_dynamic_site(resolver: str, expr: str, name: str, source: str) -> set[str]:
    """按注册表声明的溯源规则解动态点候选码。解不动=断言红（注册腐烂当场可见），绝不静默放行。"""
    if resolver == "failure_helper_forward":
        assert re.search(r"^def _failure\(", source, re.MULTILINE), (
            f"{name} 登记了 failure_helper_forward 但文件里已无 _failure 助手——注册腐烂，删除登记或改溯源规则"
        )
        return set()
    if resolver == "status_return_codes":
        codes = {code for code in _STATUS_RETURN_LINE.findall(source) if code != "ok"}
        assert codes, (
            f"{name} 的 status_return_codes 溯源解析为空——return 写法变了，同步 _STATUS_RETURN_LINE 或重审登记"
        )
        return codes
    if resolver == "reason_constant":
        match = re.search(rf"^{re.escape(expr)}\s*=\s*\"([^\"]+)\"", source, re.MULTILINE)
        assert match, (
            f"{name} 常量 {expr!r} 找不到字面量定义（改名/挪家？）——重审本登记：删掉或换成新的溯源规则"
        )
        return {match.group(1)}
    pytest.fail(f"未知 payload 动态溯源规则 {resolver!r}——扩展 _resolve_payload_dynamic_site 或删除登记")


# 短标签面归属（fix2 I-2）：DISABLED_REASON_LABEL_KEYS 只被 knowledge.tsx 消费——
# 该并集**只许**放进 webui_knowledge.py 这块面的判据；其余四件（含组级 reason 的 webui_plugins.py，
# 经 plugins.tsx describeReason 消费）一律白名单严判。评审 M13 的裸码上屏路正是被旧全局并集放过的。
SHORT_LABEL_FACET_FILES = frozenset({"webui_knowledge.py"})

# 嵌套诊断 reason（fix1 首跑实抓）：`metrics.py` 的 attempt_total / failover_calls 质量块带
# `"reason": "not_recorded_reliably"`——它不走 DataState/item reason 面，且前端类型层
# （api-client.ts 的 TokenBlock 无 reason 字段、全树零消费者）根本不读这些字段 → 永不上屏。
# 豁免与「前端确实不接」共存亡：该码一旦在 webui/src 任何 .ts/.tsx/.json 出现（前端开始消费）
# 或从登记的后端文件消失（后端挪了家），锁转红要求重审——防豁免腐烂。
# fix2 I-2 收严：豁免按 (码 → 登记文件) 记账，**只在登记的那块面上生效**——同码出现在别的面不再被稀释放过。
NON_RENDERED_PAYLOAD_REASONS: dict[str, str] = {
    "not_recorded_reliably": "metrics.py",
}


def _dynamic_candidate_codes(var: str, source: str) -> set[str]:
    if var == "reason":
        out: set[str] = set()
        for line in _REASON_VAR_LINE.findall(source):
            out.update(re.findall(r'"([a-z_]+)"', line))
        return out
    if var == "status":
        return {code for code in _STATUS_RETURN_LINE.findall(source) if code != "ok"}
    pytest.fail(f"动态点变量 {var!r} 无候选值溯源规则——扩展本函数或删除注册")


# ---- 用例 ----


def test_stats_window_enum_matches_backend() -> None:
    """STATS_WINDOWS == metrics._WINDOW_SECONDS == webui_stats._WINDOW_SECONDS 键集（422 防线）。"""
    frontend = _ts_string_array(_read_frontend(LABELS_TS), "STATS_WINDOWS")
    metrics = _py_dict_literal(_read_backend("metrics.py"), "_WINDOW_SECONDS")
    stats = _py_dict_literal(_read_backend("webui_stats.py"), "_WINDOW_SECONDS")
    assert len(frontend) == len(set(frontend)), "前端枚举有重复码"
    assert set(frontend) == set(metrics), f"stats 窗枚举漂移：前端={frontend} metrics={sorted(metrics)}"
    assert set(frontend) == set(stats), f"stats 窗枚举漂移：前端={frontend} webui_stats={sorted(stats)}"


def test_graph_windows_and_seconds_match_backend() -> None:
    """WINDOW_SECONDS/GRAPH_WINDOWS 与后端三张闭集逐项同值（含 all→None 无界）。"""
    labels_source = _read_frontend(LABELS_TS)
    frontend_spans = _ts_window_seconds(labels_source)
    frontend_graph = _ts_string_array(labels_source, "GRAPH_WINDOWS")
    metrics = _py_dict_literal(_read_backend("metrics.py"), "_WINDOW_SECONDS")
    stats = _py_dict_literal(_read_backend("webui_stats.py"), "_WINDOW_SECONDS")
    graph = _py_dict_literal(_read_backend("webui_memory_graph.py"), "_WINDOWS")

    assert set(frontend_graph) == set(graph), f"图谱窗枚举漂移：前端={frontend_graph} 后端={sorted(graph)}"
    assert set(frontend_spans) == set(frontend_graph), "前端跨度表键集与图谱枚举不闭合"
    for code, backend_span in metrics.items():
        assert frontend_spans.get(code) == backend_span, (
            f"{code} 跨度漂：前端={frontend_spans.get(code)} metrics={backend_span}"
        )
    for code, backend_span in stats.items():
        assert frontend_spans.get(code) == backend_span, (
            f"{code} 跨度漂：前端={frontend_spans.get(code)} webui_stats={backend_span}"
        )
    for code, backend_span in graph.items():
        assert frontend_spans.get(code) == backend_span, (
            f"{code} 跨度漂：前端={frontend_spans.get(code)} memory_graph={backend_span}"
        )
    assert frontend_spans["all"] is None and graph["all"] is None, "all 必须双侧同为无界（不造上界秒数）"


def test_buckets_match_backend() -> None:
    """BUCKETS == webui_stats._BUCKETS（顺序敏感）== metrics.py trends 的两张**内联**桶组（集合比较）。

    fix2 I-3：本锁 docstring 曾宣称覆盖 metrics 桶集而实现只读 `_BUCKETS`（评审 M12 实证：
    删 metrics.py 内联组到只剩 ("hour",) 门全绿）。现实现追上宣称——metrics 侧锚点为
    `bucket not in (…)`（trends 表外值 422 invalid_bucket 的准入门）与 `view in (…)`
    （_read 的分派门）。`_GROUP_EXPRESSIONS` 的 hour/day 键是内部 SQL 分组映射、非前端可达
    面，不在本锁宣称范围（诚实划界）。锚点解析不到=形态变了，断言点名同步，不静默跳过。
    """
    frontend = _ts_string_array(_read_frontend(LABELS_TS), "BUCKETS")
    backend = _py_tuple_literal(_read_backend("webui_stats.py"), "_BUCKETS")
    assert frontend == backend, f"桶闭集漂移（顺序敏感）：前端={frontend} 后端={backend}"

    metrics_source = _read_backend("metrics.py")
    for anchor, pattern in (
        ("trends 准入门", r"bucket not in \(([^)]*)\)"),
        ("_read 分派门", r"view in \(([^)]*)\)"),
    ):
        block = re.search(pattern, metrics_source)
        assert block, (
            f"metrics.py 的{anchor}（内联桶组 {pattern!r}）形态变了——"
            "本锁 docstring 宣称锁 metrics 桶集，实现与宣称必须一致：同步解析器或整条重审（评审 I-3）"
        )
        inline = re.findall(r'"([^"]+)"', block.group(1))
        assert set(inline) == set(frontend), (
            f"metrics {anchor} 桶集漂移（membership）：metrics={inline} 前端={frontend}"
        )


def test_backend_failure_reason_codes_are_whitelisted() -> None:
    """后端 _failure("source_unavailable", …) 可产出的每个码 ∈ KNOWN_REASONS（评审 I-1/M-3）。

    只读面失败链：后端加码不改白名单 → 管理端故障屏永远看见裸码。本锁即那台机器。
    这是 DataState 面的**严判**，独立于 payload 面判据（fix2 I-2：并集只出现在 payload 侧的
    knowledge 一块面上，永不稀释本例；评审 M9 实证本例第一面判据本就严）。
    """
    whitelist = set(_ts_known_reasons(_read_frontend(SEMANTICS_TS)))
    emitted: set[str] = set()
    dynamic_sites: set[tuple[str, str]] = set()
    for name in DATA_SURFACE_FILES:
        source = _read_backend(name)
        emitted.update(_FAILURE_LITERAL.findall(source))
        for var in _FAILURE_DYNAMIC.findall(source):
            dynamic_sites.add((name, var))

    unregistered = sorted(dynamic_sites - set(DYNAMIC_REASON_SITES))
    assert not unregistered, (
        "新的 reason 动态点（_failure 第二参数为变量）未注册，逐项核实其可产出码后登记 "
        f"DYNAMIC_REASON_SITES 并补候选值溯源：{unregistered}"
    )
    for file_name, var in sorted(dynamic_sites):
        candidates = _dynamic_candidate_codes(var, _read_backend(file_name))
        assert candidates, f"{file_name} 的动态点 {var} 候选值解析为空（写法变了？同步溯源规则）"
        emitted.update(candidates)

    unknown = sorted(emitted - whitelist)
    assert not unknown, (
        "后端可产出的 reason 码不在前端白名单（加码必须同步 semantics.ts KNOWN_REASONS "
        f"与双语 locale reason.*，否则管理端故障屏只见裸码）：{unknown}"
    )


def test_backend_payload_reasons_are_handled_by_frontend() -> None:
    """payload reason **按文件分面**判定（fix2 I-2，替换 fix1 的全局并集松判据）。

    分面规则（消费链决定判据，评审 M13=组级裸码门绿上屏是该松判据的存活路径）：
      - webui_plugins.py 组级 reason → plugins.tsx describeReason（只认白名单）→ ⊆ KNOWN_REASONS；
      - metrics/webui_stats/webui_memory_graph payload 码 → 同走 describeReason/无消费（豁免）→
        ⊆ KNOWN_REASONS ∪ **本文件登记的**豁免；
      - webui_knowledge.py 集合条目 reason → knowledge.tsx 短标签表 → ⊆ KNOWN_REASONS ∪ 短标签集。
    动态赋值点（fix2 I-1）：值静态不可判定（f"…"/.format(/变量）→ 必须注册 PAYLOAD_DYNAMIC_REASON_SITES，
    不注册即红；注册的候选码继续过本面判据。豁免只在登记文件的面生效，别处冒出同码即红。
    """
    whitelist = set(_ts_known_reasons(_read_frontend(SEMANTICS_TS)))
    short_labels = _ts_disabled_reason_codes(_read_frontend(KNOWLEDGE_TSX))
    assert whitelist or short_labels, "前端两张 reason 码表都解析为空 = 锁失效"

    for name in DATA_SURFACE_FILES:
        facet = set(whitelist)
        facet_kind = "白名单 KNOWN_REASONS"
        if name in SHORT_LABEL_FACET_FILES:
            facet |= short_labels
            facet_kind = "白名单 ∪ knowledge.tsx 短标签表"
        source = _read_backend(name)
        exempt = {code for code, owner in NON_RENDERED_PAYLOAD_REASONS.items() if owner == name}
        handled = facet | exempt

        literals, dynamic_sites = _scan_payload_reason_sites(source)

        unknown = sorted(literals - handled)
        assert not unknown, (
            f"{name} 的 payload reason 字面量无人接——本面判据={facet_kind}（按文件分面，评审 I-2），"
            f"表外码上管理员屏即裸码：{unknown}"
        )

        registered = {key for (file_name, key) in PAYLOAD_DYNAMIC_REASON_SITES if file_name == name}
        unregistered = sorted(dynamic_sites - registered)
        assert not unregistered, (
            f"{name} 出现静态不可判定的 payload reason 赋值点（f-string/.format/变量，评审 I-1 实证的 "
            "M6 型漏网点）未注册——逐项核实它可产出的码后登记 PAYLOAD_DYNAMIC_REASON_SITES 并给溯源规则，"
            f"不许静默跳过：{unregistered}"
        )
        for expr in sorted(dynamic_sites):
            resolver, _rationale = PAYLOAD_DYNAMIC_REASON_SITES[(name, expr)]
            candidates = _resolve_payload_dynamic_site(resolver, expr, name, source)
            bad = sorted(candidates - handled)
            assert not bad, (
                f"{name} 动态点 {expr!r}（溯源规则 {resolver}）可产出的码无人接（本面判据={facet_kind}）：{bad}"
            )

    # 豁免防腐（fix1 遗产，保留）：登记的码必须①在后端登记文件里仍在（挪家即失效）、②整个 webui/src 零出现
    # （前端一旦开始消费该字段，豁免立即转红，逼登记进真码表）。
    if NON_RENDERED_PAYLOAD_REASONS:
        corpus = _frontend_corpus()
        for code, backend_file in sorted(NON_RENDERED_PAYLOAD_REASONS.items()):
            assert code in _read_backend(backend_file), (
                f"豁免过期：{code!r} 已不在 {backend_file}——移除或改登记豁免"
            )
            assert code not in corpus, (
                f"豁免码 {code!r} 已出现在 webui/src（前端开始消费它）——"
                "必须登记进 KNOWN_REASONS 或 knowledge.tsx 短标签表，再删豁免"
            )


# ---- 前端侧棘轮两例（fix2 收编评审 Minor M-a/M-b；node 侧 labels.test.ts 非本席写权，机器锁立在 pytest）----

# 未登记页 `'—'` 字面量在册基线（台账 §四-3 的 logs.tsx cursor 占位；棘轮只减不增——
# 还债清零恒绿，新页/新枚一律红，封堵评审探针 B3「未登记页新抄不红」）。
UNKNOWN_SYMBOL_DASH_DEBT: dict[str, int] = {
    "logs.tsx": 1,
}


def test_page_unknown_symbol_literals_are_ratcheted() -> None:
    """M-a：`pages/*.tsx` **全部页面**的未知符号字面量（`'—'`/`>—<`）必须 ≤ 在册基线。

    旧 node 锁的该负断言只判 owned 清单内页面，未登记页新写 `'—'` 门绿（评审探针 B3）。
    真相源=format.ts UNKNOWN_VALUE——要未知符号就 import，不手抄；确要保留字面量先登台账再入本基线。
    """
    pages = sorted(PAGES_DIR.glob("*.tsx"))
    assert pages, f"pages 目录没有 .tsx（目录搬家？同步本锁）：{PAGES_DIR}"
    for path in pages:
        text = path.read_text(encoding="utf-8")
        hits = len(re.findall(r"['\"]—['\"]", text)) + len(re.findall(r">—<", text))
        allowed = UNKNOWN_SYMBOL_DASH_DEBT.get(path.name, 0)
        assert hits <= allowed, (
            f"{path.name} 出现 {hits} 处手抄未知符号 '—'（在册 {allowed}）——真相源=format.ts UNKNOWN_VALUE；"
            "确需保留先登记 UNI1 台账 §四 再抬 UNKNOWN_SYMBOL_DASH_DEBT（棘轮只减不增，新抄即红）"
        )


def test_enum_ratchet_baseline_is_honest() -> None:
    """M-b：labels.test.ts 枚举手抄棘轮的基线清单本身被机器核验（探针 C3「改名换页即绿」收口）。

    两判：①基线每个条目必须指向**真实存在**的 pages 文件（改名换成假页=红）；
    ②实际扫到的 `const WINDOWS` 页必须仍在基线内（把真债页从清单摘掉=红）。
    还债不砸门：命中减少（迁移完成）仍绿——与 fix1 M-2 的 shrink-only 语义同规。
    形态锚点解析不到（清单改名）同样红：重命名躲锁不是还债。
    """
    source = _read_frontend(LABELS_TEST_TS)
    block = re.search(r"const trackedUnmigrated = \[([^\]]*)\]", source)
    assert block, (
        "labels.test.ts 枚举棘轮基线形态变了（改名/删除？）——同步本锁（评审 M-b）；"
        "重命名清单不是还债"
    )
    listed = {Path(item).name for item in re.findall(r"'([^']+)'", block.group(1))}
    for file_name in sorted(listed):
        assert (PAGES_DIR / file_name).is_file(), (
            f"棘轮基线条目 {file_name} 在 pages/ 下不存在——改名换页躲锁被拦（评审 M-b）"
        )
    hits = {
        path.name
        for path in sorted(PAGES_DIR.glob("*.tsx"))
        if re.search(r"\bconst\s+WINDOWS\b", path.read_text(encoding="utf-8"))
    }
    assert hits <= listed, (
        f"枚举手抄页 {sorted(hits - listed)} 不在 labels.test.ts 基线在册清单——迁 labels.ts 单源，"
        "或先登记 UNI1 台账 §四 再入两处清单（棘轮只减不增）"
    )
