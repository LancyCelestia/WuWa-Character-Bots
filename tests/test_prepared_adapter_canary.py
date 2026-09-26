"""prepared 执行形（B0 地基 + `bot.weather` 金丝雀）的登记与活性锁。

为什么单开一件（而不是塞进 `test_orchestration_callsite_single.py`）：那件是**直呼点唯一性**
门，owner 判据是"每个直呼点恰一处登记"；本件管的是"执行体由装配现场交来的那一族能力，
中央确实在管、且中央没有偷偷自己再造一条"。两件事失败方式不同，混在一起将来谁也不敢改。

prepared 形与命令形只差一句生死：命令形的 builder 只吃 config，拿不到成品时按
`implementation_ref` 自建是同构的；prepared 形的 builder 还要运行期件（本金丝雀是
`render_backend`），**自建＝丢注入**，会跑出一条与装配现场不同的第二通路——比"没走中央"
更坏，因为看起来走了中央，实际跑的是另一套引擎。所以本件的核心判据不是"能跑"，
而是"**跑的就是交来的那一个**"。
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from types import SimpleNamespace

import pytest

#: via 全身份等值判据真身（HARDEN-1 I-1）：期望值从注入成品现读、不走被审拼接函数；
#: 本件与矩阵件/batch3 共用同一支判据，不留第二份拼接逻辑。
from test_central_via_identity_and_entry_durability import expected_via

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

WEATHER_CID = "bot.weather"
REGISTRY_FILE = "domains/chat_reply/runtime/capability_registry.py"
#: 建请求一律走这个引用：下面有条用例会把 `cp.CapabilityRequest` 换成假构造器（模拟装配
#: 现场没交成品），若本件自己也按模块属性取类，就会套娃调用自己。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-w-1",
        capability_id=WEATHER_CID,
        kind="text",
        body=body,
        audit_tags=["weather", "prepared-canary"],
    )


def _assembled(body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是 `_build_weather_with_backend` 的产物）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(body)

    return _capability


def _request(capability: object | None) -> cp.CapabilityRequest:
    context: dict[str, object] = {"config": SimpleNamespace(), "decision": SimpleNamespace()}
    if capability is not None:
        context["capability"] = capability
    return _REAL_REQUEST(
        capability_id=WEATHER_CID,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-w-1")},
        principal="3865067623",
        roles=("user",),
        request_id="req-w-1",
        session_key="private:3865067623",
        context=context,
    )


def _message() -> SimpleNamespace:
    return SimpleNamespace(request_id="req-w-1", text="天气", session_key="private:9", sender_id="9")


# --------------------------------------------------------------------- 登记面
def test_weather_row_declares_prepared_shape() -> None:
    """金丝雀在册：`bot.weather` 的执行形必须是 prepared，名册里必须有这一形。"""
    adapters = cp._route_execution_adapters()
    assert adapters.get(WEATHER_CID) == "prepared", (
        f"bot.weather 执行形漂移为 {adapters.get(WEATHER_CID)!r}"
        "＝prepared 地基失去在册样本（本件与缺口账同时失效）"
    )
    assert "prepared" in cp._KNOWN_ADAPTERS, "壳侧适配器名册没有 prepared＝地基被拆"


def test_prepared_row_gets_a_handler_from_derivation() -> None:
    """派生同源：每个已知 adapter 的行都必须有 handler，**不许只放开登记不实现信封**。

    施工图点名的最坏失效模式：只把 `"prepared"` 加进 `_KNOWN_ADAPTERS`、没写
    `_make_prepared_handler` ⇒ 派生期 `ValueError` ⇒ 中央件 import 崩 ⇒ 依赖它的门
    `pytest.skip` 静默变哑（**不是红**）。本锁直接量 `handlers`，把这条变成响亮判定。
    """
    handlers = cp.default_invoker().handlers
    for cid, adapter in cp._route_execution_adapters().items():
        assert adapter in cp._KNOWN_ADAPTERS, f"{cid}: 在册 adapter {adapter!r} 不在名册里"
        assert handlers.get(cid) is not None, (
            f"{cid}: adapter={adapter} 已放开登记却没有派生出 handler"
            "＝半批施工，中央件会在 import 期炸、门会静默变哑"
        )


# --------------------------------------------------------------------- 活性面
def test_prepared_handler_runs_the_injected_capability_not_a_rebuild() -> None:
    """核心判据：中央跑的就是调用方交来那一个成品（注入件没被 `ref` 重建偷偷替换）。"""
    calls: list[str] = []
    fake = _assembled("装配现场那一个", calls)
    result = cp.default_invoker().invoke(_request(fake))

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], "成品没被执行＝中央自己另跑了一条"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "装配现场那一个", (
        f"信封里的呈现结果不是成品吐出的那份：{presented}"
    )
    # via 必须**逐字符**说得出跑的是谁（HARDEN-1 I-1）：旧尺 `"_capability" in via` 恒真
    # （前缀自带这五个字），评审席注毒"砍成常量前缀"全绿；等值尺下常量前缀/恒定占位都红
    # （两形态自证见 test_central_via_identity_and_entry_durability）。
    assert result.via == expected_via(fake), (
        f"via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


def test_prepared_handler_without_capability_is_unavailable_never_rebuilt() -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail；**绝不允许**退回去按 ref 自建。"""
    result = cp.default_invoker().invoke(_request(None))

    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"缺执行体却给出 {result.status}＝中央可能偷偷按 ref 自建了一条第二通路"
    )
    assert "prepared" in result.detail, result.detail
    assert "build_weather_capability" in result.detail, (
        f"detail 没带在册真身，事后无从判断本该由谁交成品：{result.detail}"
    )
    assert cp.PRESENTATION_DATA_KEY not in result.data


def test_prepared_seam_falls_back_to_honest_line_not_silence(monkeypatch) -> None:
    """缝侧两态：交得进成品⇒跑成品；交不进⇒温和短句 + 终态入审计，绝不静默丢回复。"""
    calls: list[str] = []
    step = cp.orchestrated_command(WEATHER_CID, _assembled("成品", calls), SimpleNamespace())

    ok = step(_message(), SimpleNamespace(actor_roles=("user",)))
    assert calls == ["成品"], "缝没把成品交给中央执行（或中央另跑了一条）"
    assert ok.body == "成品" and ok.capability_id == WEATHER_CID, ok

    # 抽掉 context 里的成品：构造请求那一步换成"没交成品"的形态，模拟装配现场漏交。
    monkeypatch.setattr(cp, "CapabilityRequest", lambda **kwargs: _request(None))
    blocked = step(_message(), SimpleNamespace(actor_roles=("user",)))
    body = str(getattr(blocked, "body", "") or "")
    assert body.strip(), "中央拦下后缝返回空体＝用户侧静默丢回复"
    tags = list(getattr(blocked, "audit_tags", ()) or ())
    assert any("unavailable" in tag for tag in tags), f"终态没进审计：{tags}"


# --------------------------------------------------------------------- 自证
def test_prepared_locks_have_teeth() -> None:
    """注毒：把名册里的 prepared 摘掉 ⇒ 派生必须**响亮**炸，而不是静默少一条。

    这是施工图那条最坏路径的正向自证：地基被拆时全树 import 期就红，
    绝不给"门 skip、缺口账变哑"留空间。
    """
    original = cp._KNOWN_ADAPTERS
    try:
        cp._KNOWN_ADAPTERS = frozenset({"command"})
        with pytest.raises(ValueError) as caught:
            cp._route_execution_rows()
        assert "prepared" in str(caught.value), (
            f"摘掉名册后派生没有点名 prepared，而是给了别的错：{caught.value}"
        )
    finally:
        cp._KNOWN_ADAPTERS = original
    # 还原后立刻可派生（证明上面那发毒没留下半坏状态）。
    assert any(adapter == "prepared" for _descriptor, adapter in cp._route_execution_rows())


# ------------------------------------------------ 多入口活性锁（R-PREP C-1 根修的常驻证据）
#
# 2026-09-24 S166 扩容（`SEAT-S161.md` 缺口卡 G2）：本锁旧形态**只扫 root 一个文件**、
# **只认 `x.capability_id == "<字面量>"`**。两个盲区今日都不是假想，而是盘上实况：
#   · 形态盲区（现算实证）——自然语言入口 root `_handle_natural` 先做
#     `capability_id = resolution.capability_id`，再用**裸名**比十余枚 id；旧锁要求左值是
#     `ast.Attribute`，于是整个函数在它眼里不存在。
#   · 文件盲区（判据）——别名/自然语言的分发闭包一旦搬到 root 之外的模块，旧锁连"有没有这个
#     文件"都无从回答。
# 扩容后：扫描面＝**生产包全体 `.py`**（逐文件现读，不预选子集 ⇒ 没有可缩的面）；
# 判据形态＝①属性等值 ②按名等值（名字由 `某对象.capability_id` 赋值而来）③容器成员
# （字面量集合 / 局部名绑定的字典）④按名查表（下标与 `.get/.pop/.setdefault`）。
# "入口分发函数"的结构尺＝同一函数里按 **≥2 枚在册能力 id** 分流。为什么要这把尺：呈现层
# `result.capability_id == "bot.chat"`、簿记层 `FACETS.get(cid)` 这类**读单枚 id** 的站点满树都是，
# 把它们当入口判"必须汇缝"会假阳一片——而假阳一片的下一步就是有人去缩面，那才是真造绿。
# 用"≥2 枚在册 id"切开后，判据既盖住别名/自然语言/未来按名与查表形，也不替读判站点编罪。

_ROOT_INIT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "__init__.py"
)
#: 扫描面根＝整个生产包（`plugins/bot_unified_runtime/**`），不再只有 root 一个文件。
_PRODUCTION_PACKAGE = _ROOT_INIT.parent
#: root 自身在扫描面里的名字（posix 相对路径）。
_ROOT_REL = "__init__.py"
#: 汇到层 2 主缝的两条生产通路（`_run_simple_capability` 内部亦经 `_run_capability_through_pipeline`）。
_SEAM_FUNNELS = frozenset({"_run_simple_capability", "_run_capability_through_pipeline"})
#: 入口分发的结构下限：只比一枚 id 的是"读判"，不是"分流"。
_ENTRY_DISPATCH_MIN_CIDS = 2
_CID_ATTR = "capability_id"

#: 例外名册（相对生产包的 posix 路径 + 函数名 ⇒ 理由）。**只准降不准升**：多一条就等于给一条
#: 绕过中央缝的入口发通行证，故本件配两把牙——①"幽灵豁免"锁：册里点名不到今值站点即红；
#: ②"豁免确有放行力"锁：证明往册里加一条真的会让旁路变绿，所以加册必须过人、不能顺手。
#: 今值＝**空册**（现算 2026-09-24：全生产包 566 个 .py 里被这条尺判为入口分发的只有
#: root 的 `_handle_alias` 与 `_handle_natural` 两处，两处都汇缝；曾疑似要豁免的
#: `domains/ops/smoke/console_chat.py::run_interactive` 现算不成立——它分流的两枚
#: `bot.help`/`bot.status` 不在 `ROUTE_CAPABILITY_DECLARATIONS` 的 34 枚在册 id 里）。
_EXEMPT_ENTRY_DISPATCHERS: dict[tuple[str, str], str] = {}


@dataclasses.dataclass(frozen=True)
class _DispatchSite:
    """扫描面内一个"按 capability_id 分流"的函数＝本锁的最小判据单元。"""

    path: str
    fn: str
    lineno: int
    forms: frozenset[str]
    cids: frozenset[str]
    funnels: frozenset[str]
    fixed_ids: tuple[str, ...]

    @property
    def reaches_seam(self) -> bool:
        return bool(self.funnels)

    @property
    def exempt(self) -> bool:
        return (self.path, self.fn) in _EXEMPT_ENTRY_DISPATCHERS


def _registered_capability_ids() -> frozenset[str]:
    """在册能力 id 全集：唯一在册表现读，**不手抄**（判据的分母必须来自真身）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    return frozenset(decl.capability_id for decl in reg.ROUTE_CAPABILITY_DECLARATIONS)


#: 盘上源码的一次性记忆（同一轮测试里生产包不重新读盘）。
_DISK_SOURCES: dict[str, str] | None = None


def _production_sources() -> dict[str, str]:
    """扫描面＝生产包全部 `.py` 的盘上源码（posix 相对路径 ⇒ 源码）。

    读不出/解析不了不兜：`ast.parse` 抛出的 SyntaxError 一路顶红＝"缺件即红"，
    绝不默认成"那个文件里没有分发"（那是把债变小）。
    盘上读取做**一次性记忆**（本件每发注毒都要重建扫描面，566 个文件重复读盘纯属白烧
    全量套件的时间）；注毒走 `_sources_with` 的浅拷贝，不写回这份记忆。
    """
    global _DISK_SOURCES
    if _DISK_SOURCES is None:
        sources: dict[str, str] = {}
        for path in sorted(_PRODUCTION_PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            sources[path.relative_to(_PRODUCTION_PACKAGE).as_posix()] = path.read_text(
                encoding="utf-8"
            )
        if not sources:
            raise RuntimeError(f"扫描面为空：{_PRODUCTION_PACKAGE} 一个 .py 都没读到＝判据失去分母")
        _DISK_SOURCES = sources
    return dict(_DISK_SOURCES)


#: 逐文件 AST 的"文本一致才复用"缓存（注毒只改一个文件，其余 565 份解析结果照用）。
_AST_CACHE: dict[str, tuple[str, ast.AST]] = {}


def _parsed_tree(rel: str, text: str) -> ast.AST:
    cached = _AST_CACHE.get(rel)
    if cached is not None and cached[0] == text:
        return cached[1]
    tree = ast.parse(text, filename=rel)
    _AST_CACHE[rel] = (text, tree)
    return tree


def _string_dict_keys(node: ast.expr | None) -> set[str]:
    """字典字面量的 str 键＝cid-keyed 容器的"在册 id"来源。"""
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _cid_carriers(nodes: list[ast.AST]) -> tuple[set[str], dict[str, set[str]]]:
    """按名取值的两条源头：①由 `某对象.capability_id` 赋来的名字；②函数内绑成字典字面量的名字。

    第②路是 G2 (i) 的真形态之一：`table = {"bot.weather": …}` + `table[cid]` / `cid in table`。
    只认内联字典字面量会漏掉"先把表赋给局部名"这种更常见的写法。
    """
    cid_names: set[str] = set()
    local_tables: dict[str, set[str]] = {}
    for node in nodes:
        if not isinstance(node, ast.Assign):
            continue
        keys = _string_dict_keys(node.value)
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(node.value, ast.Attribute) and node.value.attr == _CID_ATTR:
                cid_names.add(target.id)
            if keys:
                local_tables[target.id] = keys
    return cid_names, local_tables


def _cid_expr_kind(expr: ast.expr | None, cid_names: set[str]) -> str | None:
    """这个表达式是"拿到的 capability_id"吗？属性形记 attr、按名形记 name。"""
    if isinstance(expr, ast.Attribute) and expr.attr == _CID_ATTR:
        return "attr"
    if isinstance(expr, ast.Name) and expr.id in cid_names:
        return "name"
    return None


def _dispatch_forms_and_cids(
    fn: ast.AST,
    registered: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    """一个函数按 capability_id 分流的**形态集合**与**涉及的在册 id**（唯一取数口）。

    `eq-attr` 是旧锁唯一认得的那一种；其余各族（`eq-name` / `membership-*` /
    `in-container-*` / `lookup-*`）是本次扩容补的形。形态名一并交出去，是为了让注毒自证
    能断言"这发毒走的是新形、旧锁根本看不见"，而不是只看"红没红"。
    """
    nodes = list(_own_nodes(fn))
    cid_names, local_tables = _cid_carriers(nodes)
    forms: set[str] = set()
    cids: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Compare):
            kind = _cid_expr_kind(node.left, cid_names)
            if kind is None:
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if (
                    isinstance(op, ast.Eq)
                    and isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, str)
                ):
                    forms.add(f"eq-{kind}")
                    cids.add(comparator.value)
                elif isinstance(op, ast.In | ast.NotIn):
                    if isinstance(comparator, ast.Set | ast.List | ast.Tuple):
                        forms.add(f"membership-{kind}")
                        cids.update(
                            element.value
                            for element in comparator.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)
                        )
                    else:
                        forms.add(f"in-container-{kind}")
                        cids.update(_string_dict_keys(comparator))
                        if isinstance(comparator, ast.Name):
                            cids.update(local_tables.get(comparator.id, set()))
        elif isinstance(node, ast.Subscript):
            kind = _cid_expr_kind(node.slice, cid_names)
            if kind is None:
                continue
            forms.add(f"lookup-{kind}")
            cids.update(_string_dict_keys(node.value))
            if isinstance(node.value, ast.Name):
                cids.update(local_tables.get(node.value.id, set()))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop", "setdefault"}
            and node.args
        ):
            kind = _cid_expr_kind(node.args[0], cid_names)
            if kind is None:
                continue
            forms.add(f"lookup-{kind}")
            cids.update(_string_dict_keys(node.func.value))
            if isinstance(node.func.value, ast.Name):
                cids.update(local_tables.get(node.func.value.id, set()))
    return frozenset(forms), frozenset(cids & registered)


def _entry_dispatch_sites(
    sources: dict[str, str],
    registered: frozenset[str],
) -> list[_DispatchSite]:
    """扫描面内全部"入口分发函数"（按 ≥ `_ENTRY_DISPATCH_MIN_CIDS` 枚在册 id 分流）。

    ⚠ 这里**刻意不做站点缓存**：站点的形状由判据本身决定（`_dispatch_forms_and_cids`、
    `_funnel_calls_and_literal_ids`、`_ENTRY_DISPATCH_MIN_CIDS`），缓存键只装得下输入
    （路径+文本+在册集），装不下"判据是哪一版"。本席变异自证时真被咬过一次——
    在内存里把判据退回旧形态跑完用例后，同一段毒源码的**站点缓存仍然留着**，
    还原判据再扫同一份文本 ⇒ 违规数报 0＝假绿。24s 的套件时间换掉这个洞是便宜账。
    与判据无关的两处记忆（盘上文本 `_DISK_SOURCES`、`ast.parse` 结果 `_AST_CACHE`）保留。
    """
    sites: list[_DispatchSite] = []
    for rel, text in sorted(sources.items()):
        sites.extend(_file_dispatch_sites(rel, text, registered))
    return sites


def _file_dispatch_sites(
    rel: str,
    text: str,
    registered: frozenset[str],
) -> list[_DispatchSite]:
    tree = _parsed_tree(rel, text)
    found: list[_DispatchSite] = []
    for fn in (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ):
        forms, cids = _dispatch_forms_and_cids(fn, registered)
        if len(cids) < _ENTRY_DISPATCH_MIN_CIDS:
            continue
        funnels, fixed = _funnel_calls_and_literal_ids(fn)
        found.append(
            _DispatchSite(
                path=rel,
                fn=fn.name,
                lineno=fn.lineno,
                forms=forms,
                cids=cids,
                funnels=frozenset(funnels),
                fixed_ids=tuple(fixed),
            )
        )
    return found


#: 盘上扫描的一次性缓存（同一轮测试里判据输入不变；注毒一律走显式 `sources=`，不碰缓存）。
_DISK_SCAN: tuple[list[_DispatchSite], frozenset[str]] | None = None


def _scan_entry_universe(
    sources: dict[str, str] | None = None,
    registered: frozenset[str] | None = None,
) -> tuple[list[_DispatchSite], list[str], int]:
    """(今值站点, 违规清单, 参与判定的入口分发函数数)——判据唯一取数口。

    用例与全部注毒自证都走这里，不留第二份 AST 抽取：判据有副本时改一个忘一个，
    注毒就会去验一条已经没人走的路（本件注毒自证的立门理由，扩容后同样成立）。
    """
    global _DISK_SCAN
    if sources is None and registered is None:
        if _DISK_SCAN is None:
            ids_now = _registered_capability_ids()
            _DISK_SCAN = (_entry_dispatch_sites(_production_sources(), ids_now), ids_now)
        sites, ids = _DISK_SCAN
    else:
        text_map = _production_sources() if sources is None else sources
        ids = _registered_capability_ids() if registered is None else registered
        sites = _entry_dispatch_sites(text_map, ids) if ids else []
    if not ids:
        # 分母为空 ⇒ 判据什么都没看着却会"零违规"地绿。这一条就是"计数腿真空"形态，必须点名。
        return sites, ["在册能力 id 读空：判据没有分母，本锁不得绿"], 0
    violations = [
        f"{site.path}::{site.fn} 按 capability_id 分流 {sorted(site.cids)}"
        f"（形态 {sorted(site.forms)}）却不汇中央缝＝存在绕过层 2 的第二入口"
        for site in sites
        if not site.reaches_seam and not site.exempt
    ]
    # 第二腿（R-CHOKE I-1 的形态）：函数按多个 capability_id 分流，却把汇合点的
    # `capability_id` 交成一个**只被字面量赋过值**的变量（或直接字面量）⇒ 它报给层 2 的
    # 永远不是被解析出来的那个 id。`_handle_alias` 当年正是这样绕过全部三把锁的。
    violations.extend(
        f"{site.path}::{site.fn} 交固定 id {literal!r} 而非解析结果: {sorted(site.cids)}"
        for site in sites
        for literal in site.fixed_ids
        if not site.exempt
    )
    seen = {(site.path, site.fn) for site in sites}
    violations.extend(
        f"豁免名册幽灵：{list(key)} 今值不是入口分发站点＝册须由该站 Owner 删（不许留着等下一次巧合）"
        for key in sorted(_EXEMPT_ENTRY_DISPATCHERS)
        if key not in seen
    )
    return sites, violations, len(sites)


def _root_dispatch_comparisons(
    source: str | None = None,
) -> dict[str, set[str]]:
    """root 里"按 capability_id 分流"的函数 ⇒ 它解析过的在册 id。

    保留旧名与旧返回形，但**不再自带判据**：把 root 当扫描面里的一个文件喂给扩容后的
    唯一取数口。`source` 只为注毒自证留口：传入改写后的源码字符串就能在**内存里**验
    判据有无牙，不必也不许去改真树。
    """
    registered = _registered_capability_ids()
    if not registered:
        return {}
    text = _ROOT_INIT.read_text(encoding="utf-8") if source is None else source
    sites = _entry_dispatch_sites({_ROOT_REL: text}, registered)
    return {site.fn: set(site.cids) for site in sites}


def _root_resolved_cids(source: str | None = None) -> set[str]:
    return {cid for cids in _root_dispatch_comparisons(source).values() for cid in cids}


def _entry_resolved_cids(sites: list[_DispatchSite]) -> set[str]:
    return {cid for site in sites for cid in site.cids}


def _sources_with(rel: str, text: str) -> dict[str, str]:
    """把盘上扫描面取一份、替换（或新增）一个文件——注毒只在内存里发生。"""
    sources = dict(_production_sources())
    sources[rel] = text
    return sources


def _replace_function_source(source: str, fn_name: str, new_source: str) -> str:
    """按 AST 行界整段换掉一个函数的源码（注毒用；换完必再解析，语法塌了当场炸）。"""
    tree = ast.parse(source)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == fn_name
    )
    lines = source.splitlines(keepends=True)
    rebuilt = (
        "".join(lines[: fn.lineno - 1])
        + new_source
        + "".join(lines[fn.end_lineno or fn.lineno :])
    )
    ast.parse(rebuilt)
    return rebuilt


def _own_nodes(scope: ast.AST):
    """该函数**自己**的节点，不下钻进更内层的函数。

    根的装配全嵌套在 `_register_nonebot_handlers` 里：不做这层隔离，外层函数会
    "看见"所有内层 handler 的比较与字面量，判据立刻变成假阳性一片
    （与 `test_outbound_bypass_prohibition_gate._own_nodes` 同一条教训，两处各写一份
    是因为它属另一门 owner 的私有工具，跨测试件互相 import 会让两门耦合到谁也不敢改）。
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _funnel_calls_and_literal_ids(fn: ast.AST) -> tuple[set[str], list[str]]:
    """分发函数交给汇合点的形状：调了哪几条缝 + 交出去的 id 里"注定是字面量"的那些。"""
    nodes = list(_own_nodes(fn))
    # 变量都只被常量赋过值 ⇒ 交出去的 id 与解析结果无关
    assigned: dict[str, set[ast.expr]] = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith(_CID_ATTR):
                    assigned.setdefault(target.id, set()).add(node.value)
    funnels: set[str] = set()
    bad: list[str] = []
    for call in nodes:
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in _SEAM_FUNNELS
        ):
            continue
        funnels.add(call.func.id)
        given: ast.expr | None = None
        for keyword in call.keywords:
            if keyword.arg == _CID_ATTR:
                given = keyword.value
        if given is None and call.func.id == "_run_simple_capability" and len(call.args) > 3:
            given = call.args[3]
        if given is None:
            continue
        if isinstance(given, ast.Constant) and isinstance(given.value, str):
            bad.append(given.value)
            continue
        if isinstance(given, ast.Name):
            values = assigned.get(given.id)
            if values and all(
                isinstance(value, ast.Constant) for value in values
            ):
                literals = {
                    value.value
                    for value in values
                    if isinstance(value, ast.Constant) and isinstance(value.value, str)
                }
                bad.extend(sorted(literals))
    return funnels, sorted(set(bad))


def test_every_resolved_capability_entry_reaches_the_central_seam() -> None:
    """在册执行形的能力，别名/自然语言等**每一条**分发入口都必须汇到缝（不得有旁路入口）。

    立门前因（R-PREP C-1，本波第二个"全绿但没执法"）：`bot.weather`/`wiki`/`news`/`eat`/`epic`
    除命令入口外，还有别名与自然语言两条 `resolution.capability_id == "…"` 分支；那两条历史上
    把闭包直接交给 `_run_capability_through_pipeline` 而**不包缝** ⇒ 一个能力三条入口里两条
    不经层 2 治理，而缺口账按"唯一表声明了执行形"就记 WIRED 并降棘轮＝在记账面上作弊。
    修法是把"包缝"下沉到该汇合函数本体（一处覆盖全部入口），本锁把这个不变量钉成常驻判据：
    **凡按 capability_id 分流的入口函数，必须汇到两条缝之一**（S166 扩容后＝全生产包扫描面
    + 属性/按名/成员/查表四形态）。
    """
    sites, violations, judged = _scan_entry_universe()
    assert judged >= _ENTRY_DISPATCH_MIN_CIDS, (
        f"本锁只扫到 {judged} 个按 capability_id 分发的入口函数＝分发形态或扫描面已换，须改写本锁"
    )
    # 非空转的真正锚点不是"函数有几个"，而是"当年出事那批双入口能力确实被本锁看着"：
    # R-PREP 点名的就是这五枚（命令入口走缝、别名/自然语言入口历史上不走缝）。
    covered = _entry_resolved_cids(sites)
    must_watch = {"bot.weather", "bot.wiki", "bot.news", "bot.eat", "bot.epic"}
    blind = must_watch - covered
    assert not blind, f"这些双入口能力没被任何分发函数比较到＝本锁对它们失明：{sorted(blind)}"
    assert not violations, "入口活性锁红：" + "；".join(violations)


def test_both_entry_files_are_seen_by_name_not_only_by_attribute() -> None:
    """别名与自然语言两条入口**各自**都必须被看着（不是"任一函数覆盖到就算"）。

    这是 G2 形态盲区的直接判据：自然语言入口 `_handle_natural` 先
    `capability_id = resolution.capability_id` 再用裸名比较，旧锁（左值须为 `ast.Attribute`）
    对该函数**零看见**；而旧锁又只看 root 一个文件，"两条入口各自被看着"这件事从未被量过。
    """
    sites, _violations, _judged = _scan_entry_universe()
    for entry in ("_handle_alias", "_handle_natural"):
        seen = [site for site in sites if site.fn == entry]
        assert seen, f"入口函数 {entry} 不在本锁今值站点里＝本锁对它失明（形态或文件面变了）"
        for site in seen:
            assert site.cids, f"{entry}@{site.path}:{site.lineno} 被看着却没解析到在册 id"
    natural = next(site for site in sites if site.fn == "_handle_natural")
    assert "eq-name" in natural.forms and "eq-attr" not in natural.forms, (
        f"自然语言入口的形态标签与本席扩容理由不符：{sorted(natural.forms)}"
        "（若真树已改回属性形，请连同本断言与 G2 记账一并更正，别只改判据凑绿）"
    )


def test_multi_entry_liveness_lock_has_teeth() -> None:
    """注毒：抹掉汇合点调用 ⇒ 同一判据必须点名那些只分流不汇缝的函数。

    刻意复用 `_scan_entry_universe(sources=…)` 而不是在这里再写一遍 AST 抽取：
    判据有两个副本时，将来改一个忘一个，注毒自证就会验一条已经没人走的路。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    sites, clean_violations, judged = _scan_entry_universe()
    assert not clean_violations and judged >= 1, "基线不干净，本自证失去意义"

    poisoned = source.replace("_run_capability_through_pipeline(", "_legacy_direct_dispatch(")
    assert poisoned != source, "注毒点消失（汇合函数被改名/搬走），须同步本自证"
    poison_sites, violations, _ = _scan_entry_universe(_sources_with(_ROOT_REL, poisoned))
    assert violations, "抹掉全部汇合点调用后仍无违规＝上面那条锁是空转判据"
    assert _entry_resolved_cids(poison_sites) == _entry_resolved_cids(sites), (
        "注毒把判据覆盖面也改了＝抽取出问题的不是汇合点，本自证没验到点上"
    )


#: 注毒替身共用的两枚在册 id（替身只活在内存里的源码副本里，盘上从不落地）。
_POISON_TWO_IDS = frozenset({"bot.weather", "bot.music"})

_BY_NAME_POISON = """    async def _handle_alias(bot: Bot, event: Event) -> None:
        resolution = resolve_alias_command(event)
        alias_cid = resolution.capability_id
        if alias_cid == "bot.weather":
            await bot.send("天气")
        elif alias_cid == "bot.music":
            await bot.send("点歌")

"""

_CONTAINER_POISON = """    async def _handle_alias(bot: Bot, event: Event) -> None:
        resolution = resolve_alias_command(event)
        alias_cid = resolution.capability_id
        table = {"bot.weather": _weather_reply, "bot.music": _music_reply}
        if alias_cid in table:
            await bot.send(table[alias_cid](event))
        elif alias_cid in {"bot.weather", "bot.music"}:
            await bot.send("候选")

"""


def test_by_name_dispatch_poison_is_caught() -> None:
    """注毒一（G2 形态盲区）：把 `capability_id` 换成变量后，锁**还得红**。

    替身里一条 `x.capability_id ==` 都没有（全是 `alias_cid ==`）⇒ 旧判据的
    `isinstance(cmp.left, ast.Attribute)` 会把它筛成"这里没有分发函数"，于是
    "分流却不汇缝"在旧锁下**静默绿**。本用例断言两件事：①违规点名到它；②形态标签只有
    `eq-name`、没有 `eq-attr`（这就是"旧锁看不见"的可核对写法，比再造一份旧判据副本诚实）。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    poisoned = _replace_function_source(source, "_handle_alias", _BY_NAME_POISON)
    sites, violations, judged = _scan_entry_universe(_sources_with(_ROOT_REL, poisoned))
    assert judged >= 1, "注毒后判据面塌成空＝本用例失去意义"
    site = next(
        (item for item in sites if item.fn == "_handle_alias" and item.path == _ROOT_REL), None
    )
    assert site is not None, "按名分发的别名入口没进今值站点＝本锁仍对按名形态失明"
    assert "eq-name" in site.forms and "eq-attr" not in site.forms, (
        f"替身形态漂移（出现 eq-attr 就说明毒没换成变量）：{sorted(site.forms)}"
    )
    assert site.cids == _POISON_TWO_IDS, f"替身没被按在册 id 认出：{sorted(site.cids)}"
    assert not site.reaches_seam
    assert any("_handle_alias" in line and "不汇中央缝" in line for line in violations), (
        f"注毒未被点名：{violations}"
    )


def test_container_table_dispatch_poison_is_caught() -> None:
    """注毒二（G2 (i)）：按名取值 + 容器成员/查表分流 ⇒ 不汇缝必须被点名。

    刻意**全程不出现** `x.capability_id ==`：分流靠局部名 `alias_cid`，容器既有
    "赋给名字的字典表"（`in table` / `table[alias_cid]`）也有"字面量集合"（`in {...}`）。
    旧锁三种形一个都不认（左值非 Attribute、且压根不看容器）。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    poisoned = _replace_function_source(source, "_handle_alias", _CONTAINER_POISON)
    sites, violations, _judged = _scan_entry_universe(_sources_with(_ROOT_REL, poisoned))
    site = next(item for item in sites if item.fn == "_handle_alias" and item.path == _ROOT_REL)
    assert {"in-container-name", "membership-name", "lookup-name"} <= site.forms, (
        f"容器/查表形态没被识别出来：{sorted(site.forms)}"
    )
    assert not (site.forms & {"eq-attr", "membership-attr", "in-container-attr", "lookup-attr"}), (
        f"替身里不该再有属性形（有就说明毒没换成变量）：{sorted(site.forms)}"
    )
    assert site.cids == _POISON_TWO_IDS, f"局部表里的 id 没被算进分母：{sorted(site.cids)}"
    assert any("_handle_alias" in line and "不汇中央缝" in line for line in violations), (
        f"注毒未被点名：{violations}"
    )


_OUT_OF_ROOT_POISON = '''"""S166 注毒替身：住在 root 之外的别名分发闭包（只在内存里，盘上无此文件）。"""

from __future__ import annotations

from typing import Any


async def dispatch_alias_entry(bot: Any, event: Any, resolution: Any) -> None:
    capability_id = resolution.capability_id
    if capability_id == "bot.weather":
        await bot.send("天气")
    elif capability_id == "bot.music":
        await bot.send("点歌")

'''


def test_out_of_root_entry_dispatch_is_in_the_scan_universe() -> None:
    """注毒三（G2 (ii) 文件盲区）：分发闭包搬到 root 之外 ⇒ 仍要被看着并点名。

    旧锁 `ast.parse(_ROOT_INIT.read_text())` 只看一个文件，这种入口在旧锁下**不存在**。
    本替身经 `sources=` 注入内存扫描面（盘上从不落地），断言违规点名到那条非 root 路径。
    """
    rel = "domains/chat_reply/runtime/alias_entry_poison.py"
    sites, violations, judged = _scan_entry_universe(_sources_with(rel, _OUT_OF_ROOT_POISON))
    assert judged >= 1
    site = next((item for item in sites if item.path == rel), None)
    assert site is not None and site.fn == "dispatch_alias_entry", (
        f"非 root 的入口分发没进扫描面＝文件面仍是只扫 root：{[(s.path, s.fn) for s in sites]}"
    )
    assert any(rel in line and "不汇中央缝" in line for line in violations), (
        f"注毒未被点名：{violations}"
    )


def test_no_vacuum_green_and_exemption_roster_has_teeth(monkeypatch) -> None:
    """注毒四、五：分母读空不得绿；豁免名册既不能凭空存在、也不是摆设。

    ①在册表换成空 ⇒ 判据"零违规"却什么都没看着，正是"计数腿真空"形态 ⇒ 必须点名。
    ②豁免册今值必须是**空册**（棘轮零位）：加一条就得改这里并留下理由，不许顺手。
    ③幽灵锁：册里点名不到今值站点 ⇒ 红（不许留着等下一次巧合把它"撞绿"）。
    ④放行力：把注毒一的旁路站写进册 ⇒ 违规**确实消失**——这条自证说明"加册"不是
      纸面动作，因此新增例外必须过该面 Owner 的手，不能由改测试的人自己批。
    """
    _sites, violations, judged = _scan_entry_universe(
        _sources_with(_ROOT_REL, _ROOT_INIT.read_text(encoding="utf-8")),
        registered=frozenset(),
    )
    assert violations and judged == 0, f"分母读空却判成绿：violations={violations} judged={judged}"

    _real_sites, real_violations, _ = _scan_entry_universe()
    assert not _EXEMPT_ENTRY_DISPATCHERS, (
        f"豁免册非空＝有人给某条入口发了通行证，须由该面 Owner 裁定并补理由：{sorted(_EXEMPT_ENTRY_DISPATCHERS)}"
    )
    assert not real_violations, f"今值基线本应干净：{real_violations}"

    monkeypatch.setitem(_EXEMPT_ENTRY_DISPATCHERS, ("no/such_file.py", "no_such_fn"), "注毒：幽灵豁免")
    _sites, violations, _judged = _scan_entry_universe()
    assert any("豁免名册幽灵" in line for line in violations), (
        f"册里凭空多一条却无人点名＝豁免可以静默存在：{violations}"
    )

    monkeypatch.delitem(_EXEMPT_ENTRY_DISPATCHERS, ("no/such_file.py", "no_such_fn"))
    source = _ROOT_INIT.read_text(encoding="utf-8")
    poison_sources = _sources_with(
        _ROOT_REL, _replace_function_source(source, "_handle_alias", _BY_NAME_POISON)
    )
    alias_site = next(
        site
        for site in _entry_dispatch_sites(poison_sources, _registered_capability_ids())
        if site.fn == "_handle_alias" and site.path == _ROOT_REL
    )
    assert alias_site.cids and not alias_site.reaches_seam
    _sites, violations, _judged = _scan_entry_universe(poison_sources)
    assert any("_handle_alias" in line for line in violations), f"注毒基线未红：{violations}"
    monkeypatch.setitem(
        _EXEMPT_ENTRY_DISPATCHERS, (_ROOT_REL, "_handle_alias"), "注毒：证明豁免确有放行力"
    )
    _sites, exempted, _judged = _scan_entry_universe(poison_sources)
    assert not any("_handle_alias" in line and "不汇中央缝" in line for line in exempted), (
        f"写进名册仍拦不住＝这条腿是装饰，豁免的实际代价没被量过：{exempted}"
    )


def test_row_without_human_label_still_derives_a_title(monkeypatch) -> None:
    """内部席位在册 `label=""` 是诚实形态，派生器不得因此把整表判炸。

    立门前因（S-PREP-B2 实测）：想给 `bot.ignore` 登记执行形时，壳按 `title=decl.label`
    派生 ⇒ 空标签行让 `validate_registry` 报 `title 缺失`，**全表**跟着红。
    那是派生器把"这行没有人类可读标签"错当成"这行坏"。修法用 `label or value`，
    本锁钉住这条兜底仍然成立（不许再用"给内部席位补个标签"绕过去——那是为了让测试变绿
    而改在册事实）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    template = next(
        decl for decl in reg.ROUTE_CAPABILITY_DECLARATIONS if getattr(decl, "execution", None)
    )
    assert template.execution is not None  # mypy 收窄：上面 next() 的谓词就是它非空
    blank = dataclasses.replace(
        template,
        capability_id="bot.probe.no_label",
        label="",
        value="no_label",
        execution=dataclasses.replace(
            template.execution,
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
                "#build_echo_capability"
            ),
        ),
    )
    monkeypatch.setattr(reg, "ROUTE_CAPABILITY_DECLARATIONS", (blank,))

    rows = cp._route_execution_rows()
    assert [descriptor.capability_id for descriptor, _adapter in rows] == ["bot.probe.no_label"]
    assert rows[0][0].title == "no_label", (
        f"空标签行没兜到 value，而是给出 {rows[0][0].title!r}＝内部席位永远接不进中央"
    )
