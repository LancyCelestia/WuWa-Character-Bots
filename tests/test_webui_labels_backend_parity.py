"""UNI1 fix1（评审 C-1 / I-1 / M-3）：前端 labels ↔ 后端 control_plane 的跨语言同值门（pytest 侧）。

为什么在 pytest 而不在 ``node --test``（C-1 裁定）：
  ``control_plane/metrics.py`` / ``webui_stats.py`` / ``webui_memory_graph.py`` 三件本波**未入库**
  （随控制面整波提交），JS 测试直读它们 = 干净克隆上 ENOENT **失败**而非 skip，并经
  ``test_webui_constitution.py::test_pure_function_tests`` 把整个前端门拖红；失败消息对改后端的
  Python 作者零可达。pytest 侧则：后端模块缺失 → **显式 skip 并点名路径**（控制面在本 checkout
  属可选特性），失败恰好落在改动字面量的一方。node 侧（``webui/src/lib/labels.test.ts``）
  保持密封：只读 webui/ 以内，锁 labels ↔ 枚举 ↔ 标签的纯前端三向自洽。

覆盖（全部**只读源码字面量**解析，不 import、不执行任何一侧代码）：
  1) stats 窗枚举：labels.ts ``STATS_WINDOWS`` == ``metrics._WINDOW_SECONDS`` == ``webui_stats._WINDOW_SECONDS`` 键集
  2) 跨度同值与图谱枚举：labels.ts ``WINDOW_SECONDS``/``GRAPH_WINDOWS`` == 后端三张闭集（含 ``all: None`` 无界）
  3) 桶闭集：labels.ts ``BUCKETS`` == ``webui_stats._BUCKETS``（顺序敏感）
  4) reason 白名单（M-3/I-1）：后端 ``_failure("source_unavailable", …)`` 产出的码 ⊆ semantics.ts
     ``KNOWN_REASONS``；动态点（第二参数为变量）按 ``(文件, 变量)`` 注册表治理，候选字面量同样验真
  5) 条目级 reason（知识库短标签族，UNI1 台账 §四-7 的两个不同码空间）：payload ``"reason"`` 字面量
     ⊆ ``KNOWN_REASONS`` ∪ ``knowledge.tsx DISABLED_REASON_LABEL_KEYS`` 键集 ∪ 带防腐检查的
     显式豁免表（``NON_RENDERED_PAYLOAD_REASONS``：嵌套诊断 reason，前端类型层零消费永不上屏）

测试缝（演示 skip 分支非死代码，评审要求双向证明）：环境变量 ``UNI1_CONTROL_PLANE_DIR`` 可把
后端真相源目录指到别处；指到不存在的路径实跑，本文件依赖后端的用例应全部 skip 而非 fail。
缺省 = 仓库内真实路径，正常 checkout 下这些用例必须真跑真绿。
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
    block = re.search(rf"^{name}\s*=\s*\{{([^}}]*)\}}", source, re.M)
    assert block, f"后端字面量 {name} 形态变了——同步本解析器与 labels.ts 的真相源锚点"
    out: dict[str, int | None] = {}
    for match in re.finditer(r'"([^"]+)"\s*:\s*([^,}]+)', block.group(1)):
        raw = match.group(2).strip()
        out[match.group(1)] = None if raw == "None" else _seconds_expr(raw, name)
    assert out, f"{name} 字面量解析为空（正则与后端写法不匹配？）"
    return out


def _py_tuple_literal(source: str, name: str) -> list[str]:
    block = re.search(rf"^{name}\s*=\s*\(([^)]*)\)", source, re.M)
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
    block = re.search(r"export const WINDOW_SECONDS[^\n]*=\s*\{(.*?)\};", source, re.S)
    assert block, "labels.ts WINDOW_SECONDS 形态变了——同步本解析器"
    out: dict[str, int | None] = {}
    for match in re.finditer(r"(?:'([^']+)'|([A-Za-z_]\w*))\s*:\s*([^,\n]+)", block.group(1)):
        raw = match.group(3).strip()
        key = match.group(1) or match.group(2)
        out[key] = None if raw == "null" else _seconds_expr(raw, "WINDOW_SECONDS")
    assert out, "labels.ts WINDOW_SECONDS 解析为空"
    return out


def _ts_known_reasons(source: str) -> list[str]:
    block = re.search(r"export const KNOWN_REASONS\s*=\s*\[(.*?)\]\s*as const", source, re.S)
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
        r"const DISABLED_REASON_LABEL_KEYS: Record<string, string> = \{(.*?)\};", source, re.S
    )
    assert block, "knowledge.tsx DISABLED_REASON_LABEL_KEYS 形态变了——同步本解析器"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s*:", block.group(1), re.M))


# ---- reason 族解析：reason 位置的字符串字面量 + 显式注册的动态点 ----

# _failure("source_unavailable", "码")：DataState.reason 的唯一封闭产出面（describeReason 消费）。
_FAILURE_LITERAL = re.compile(r'_failure\(\s*"source_unavailable"\s*,\s*"([^"]+)"')
# _failure("source_unavailable", 变量)：动态点，(文件名, 变量名) 必须在下表注册。
_FAILURE_DYNAMIC = re.compile(r'_failure\(\s*"source_unavailable"\s*,\s*(?!")([A-Za-z_]\w*)')
# 条目级/组级 payload 的 reason 字段（知识库短标签族等，见 UNI1 台账 §四-7：与 DataState 码空间不同源）。
_PAYLOAD_REASON_PATTERNS = (
    re.compile(r'\["reason"\]\s*=\s*"([^"]+)"'),
    re.compile(r'"reason":\s*(?:None if [^\n]+? else\s+)?"([^"]+)"'),
    re.compile(r"^_?[A-Z0-9_]*REASON[A-Z0-9_]*\s*=\s*\"([^\"]+)\"", re.M),
)
# 动态候选值的来源写法：`reason = "x" if … else "y"`（metrics）与 `return "x", None`（knowledge status）。
_REASON_VAR_LINE = re.compile(r"\breason\s*=\s*([^\n]+)")
_STATUS_RETURN_LINE = re.compile(r'return "([a-z_]+)",\s*(?:None|\[\]|\{\})')

# 显式豁免登记（评审 I-1：reason 走变量的动态点）。新增动态点不注册即红；注册了就要能溯源候选码。
DYNAMIC_REASON_SITES: dict[tuple[str, str], str] = {
    ("metrics.py", "reason"): "reason = \"query_budget_exceeded\" if budget_exceeded else \"read_failed\"",
    ("webui_knowledge.py", "status"): "status 来自 _kb_document_index/_meme_tag_counts 的 return \"码\", None",
}

# 嵌套诊断 reason（fix1 首跑实抓）：`metrics.py` 的 attempt_total / failover_calls 质量块带
# `"reason": "not_recorded_reliably"`——它不走 DataState/item reason 面，且前端类型层
# （api-client.ts 的 TokenBlock 无 reason 字段、全树零消费者）根本不读这些字段 → 永不上屏。
# 豁免与「前端确实不接」共存亡：该码一旦在 webui/src 任何 .ts/.tsx/.json 出现（前端开始消费）
# 或从登记的后端文件消失（后端挪了家），锁转红要求重审——防豁免腐烂。
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
    """BUCKETS == webui_stats._BUCKETS / metrics 桶集（表外值后端 422 invalid_bucket）。"""
    frontend = _ts_string_array(_read_frontend(LABELS_TS), "BUCKETS")
    backend = _py_tuple_literal(_read_backend("webui_stats.py"), "_BUCKETS")
    assert frontend == backend, f"桶闭集漂移（顺序敏感）：前端={frontend} 后端={backend}"


def test_backend_failure_reason_codes_are_whitelisted() -> None:
    """后端 _failure("source_unavailable", …) 可产出的每个码 ∈ KNOWN_REASONS（评审 I-1/M-3）。

    只读面失败链：后端加码不改白名单 → 管理端故障屏永远看见裸码。本锁即那台机器。
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
    """条目级 payload 的 reason 字面量 ⊆ 白名单 ∪ 知识库短标签码集 ∪ 防腐豁免（两码空间见台账 §四-7）。

    DataState.reason 走 describeReason（白名单）；知识库集合条目 reason 走
    DISABLED_REASON_LABEL_KEYS 短标签。两个面之外的字面量码 = 上屏裸码，本锁拦截；
    唯一允许的例外是显式豁免的嵌套诊断 reason，且豁免必须同时满足「前端零消费」。
    """
    whitelist = set(_ts_known_reasons(_read_frontend(SEMANTICS_TS)))
    short_labels = _ts_disabled_reason_codes(_read_frontend(KNOWLEDGE_TSX))
    handled = whitelist | short_labels
    assert handled, "前端两张 reason 码表都解析为空 = 锁失效"

    payload_codes: set[str] = set()
    for name in DATA_SURFACE_FILES:
        source = _read_backend(name)
        for pattern in _PAYLOAD_REASON_PATTERNS:
            payload_codes.update(pattern.findall(source))

    unknown = sorted(payload_codes - handled - set(NON_RENDERED_PAYLOAD_REASONS))
    assert not unknown, (
        "后端 payload reason 字面量无人接（既不在 KNOWN_REASONS 也不在 "
        f"knowledge.tsx 短标签表，上屏即裸码）：{unknown}"
    )

    # 豁免防腐：登记的码必须①在后端登记文件里仍在（挪家即失效）、②整个 webui/src 零出现
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
