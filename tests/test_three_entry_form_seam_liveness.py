"""命令/别名/自然语言三形入口抵达中央汇口的 **exec 活性腿**（S167，补 SEAT-S161 §G3 缺口）。

先说清楚本件**不**是什么：既有件 `test_prepared_adapter_canary.py` 的
`test_every_resolved_capability_entry_reaches_the_central_seam` 用**静态 AST** 证"凡比较过某
capability_id 的分发函数，函数体里出现了汇口调用"。那把尺停在"这段代码形状对不对"——分发函数里
一条 `return`（先返回、后汇缝）或一条把能力交给 `pipeline` 的运行期旁路，**文本里汇口调用照样在场**，
静态尺照绿。只有 ack／主动投递两形拿到了 exec 活性锁（`test_active_push_entry_teeth.py`），
三形没有 ⇒ S161 记为 **G3（与 ack 不对称，P2）**。本件补的就是活性那一半。

两层各一条腿，判据都是"真调用、真抵达、真包缝"：

1. **入口层 Leg A**：把 root 里真 `_handle_alias` / `_handle_natural` / 命令形 `_handle_*` 的
   **盘上源码原样摘出来 exec**（`ast.get_source_segment(padded=True)` + `textwrap.dedent`），
   灌假 resolver / 假汇口 / 假构造器真跑一遍，断言①抵达派生出的那枚合法汇口、②汇口收到的
   `capability_id` 就是解析结果（不是入口名）、③交进汇口的那枚闭包**是活的**——调用它真的命中
   该分支的能力构造器并原样带回结果。
2. **汇口层 Leg B**：把真 `_run_capability_through_pipeline` 摘出来 exec，灌假 pipeline，断言它
   在运行期**确实**把裸能力过了一遍 `orchestrated_command`（层 2 治理），且已带
   `orchestrated_capability_id` 的能力不被二次包缝。"抵达汇口"与"汇口真包缝"是两件事，缺后半句
   就是"走进一个没有治理的口子"。

派生而非手抄：`(形, capability_id) → (handler, 汇口, 构造器名)` 这张表**从 root 现算**
（`dispatch_table()`），期望值不写死在测试里；真树把某形换汇口，表跟着换、判据仍自洽。注毒相反：
表读**盘上真源码**、跑**内存里改过的副本**，两侧一发散开＝判据有牙。

与静态尺的分工有**实证**（`test_poison_alias_early_return_goes_red_and_static_leg_stays_green`）：
同一份内存注毒副本回填整树后，静态判据**仍然看得见汇口调用**，而本件当场红 ⇒ 这条腿不是重复劳动。

诚实边界：①exec 的是盘上真源码，注毒一律喂改过的内存串，绝不回写文件、绝不改真树；②命令形走
`_run_simple_capability`、别名与自然语言形走 `_run_capability_through_pipeline`，两枚都是 canary
`_SEAM_FUNNELS` 在册的合法汇口，本件按派生值**逐形点名**、不混成一锅；③本件只证"抵达 + 包缝"，
**不证**出站闸在执法（`bot_outbound_gate_enabled` 缺省关＝#49「在册未执法」，ack/主动投递共享此坑）；
④分发形态整体换掉（不再有 `capability_id == "<字面量>"` 分支、或命令形不再用 5 位置参调
`_run_simple_capability`）时，`dispatch_table()` 的非空/唯一断言当场红，不会静默变哑。
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import pathlib
import textwrap
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

#: 静态尺的对照判据**在本地重写一份**（`_static_leg_still_sees_the_call`），刻意不 import
#: `test_prepared_adapter_canary` 的私有判据：本件开工期间（07:30Z）那件的 `_root_entry_violations`
#: 已被另一席改名，跨门借私有名会在十几分钟内把自己撞成 ImportError ⇒ 采集失败变成"门没跑"而不是
#: "门红了"。本件的对照只需要静态尺的**核心那一腿**（"函数自己的节点里有没有汇口调用"），
#: 五句可自证，不需要它的 elif 链第二腿。
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ROOT_INIT = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

#: canary `_SEAM_FUNNELS` 同一对合法汇口（不 import 其私有常量：两门 owner 不同，谁也不敢改对方）。
LEGAL_SEAMS = frozenset({"_run_simple_capability", "_run_capability_through_pipeline"})
PIPELINE_SEAM = "_run_capability_through_pipeline"
SIMPLE_SEAM = "_run_simple_capability"

#: R-PREP C-1 的当事五枚（静态尺点名的双入口能力）：本件对它们逐个跑三形。
MUST_WATCH = ("bot.weather", "bot.wiki", "bot.eat", "bot.news", "bot.epic")

#: 能力构造器的返回值哨兵——闭包必须把它**原样**带回，不许换成自造话术。
_RESULT = SimpleNamespace(sentinel="capability-result")


# ================================================================ 取源码（盘上真身）
def _root_source() -> str:
    return _ROOT_INIT.read_text(encoding="utf-8")


def _own_nodes(scope: ast.AST):
    """该函数**自己**的节点，不下钻进更内层的函数（与 canary 同一教训：外层会"看见"所有
    内层 handler 的比较与汇口调用，判据立刻变成假阳性一片）。"""
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _func_nodes(tree: ast.AST) -> dict[str, list[ast.AsyncFunctionDef | ast.FunctionDef]]:
    out: dict[str, list[ast.AsyncFunctionDef | ast.FunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            out.setdefault(node.name, []).append(node)
    return out


def _single_func(tree: ast.AST, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    nodes = _func_nodes(tree).get(name, [])
    assert len(nodes) == 1, f"root 里 {name} 命中 {len(nodes)} 处＝搬家/重名，活性腿须重判"
    return nodes[0]


def _raw_segment(name: str, source: str | None = None) -> str:
    """盘上**原样**（含原缩进）的那段源码——它是 root 的子串，故可回填整树做静态尺对照。"""
    text = source if source is not None else _root_source()
    node = _single_func(ast.parse(text), name)
    segment = ast.get_source_segment(text, node, padded=True)
    assert segment and segment in text, f"取不到 {name} 的盘上源码段"
    return segment


def _module_src(segment: str, name: str) -> str:
    """把（可能带缩进的）函数段归零缩进、补 `__future__`，使其可独立 compile。

    补 future 是必需的：root 第 1 行就是 `from __future__ import annotations`，摘出来单独
    exec 时若不带上，`async def h(bot: Bot, event: Event)` 的**注解会在 def 期求值**而 NameError
    ——那时红的是本件的取源码，而不是被测代码。
    """
    module_src = "from __future__ import annotations\n" + textwrap.dedent(segment)
    compile(module_src, f"<s167-extract {name}>", "exec")
    assert f"async def {name}(" in module_src, f"{name} 摘出来的不是那个 async def"
    return module_src


def _exec_func(name: str, source: str | None = None) -> Any:
    """exec 盘上真源码（或内存注毒副本）里的那枚函数，返回可调用对象 + 其命名空间。"""
    namespace: dict[str, Any] = {}
    exec(  # noqa: S102 — 只 exec 本仓自己的源码/内存注毒副本，绝不 exec 外部输入
        compile(_module_src(_raw_segment(name, source), name), f"<s167-{name}>", "exec"),
        namespace,
    )
    return namespace[name], namespace


def _string_set_literal(name: str) -> frozenset[str]:
    """读 root 模块级 `NAME = frozenset({...})` 的字面量（不 import 根包，避免插件装配副作用）。"""
    for node in ast.parse(_root_source()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            values = frozenset(
                item.value
                for item in ast.walk(node.value)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
            assert values, f"{name} 现算为空集＝活性前提（offload 名册）失效"
            return values
    raise AssertionError(f"root 里没有模块级 {name}＝生产名册搬家")


# ================================================================ 派生：(形, cid) → 坐标
class _Route:
    def __init__(self, form: str, cid: str, handler: str, seam: str, builder: str) -> None:
        self.form = form
        self.capability_id = cid
        self.handler = handler
        self.seam = seam
        self.builder = builder

    @property
    def key(self) -> tuple[str, str]:
        return (self.form, self.capability_id)

    def label(self) -> str:
        return (
            f"{self.form}/{self.capability_id}（handler={self.handler}→seam={self.seam}，"
            f"构造器={self.builder}）"
        )


def _compare_to_cid(test: ast.expr, cid: str) -> bool:
    """`capability_id == "<cid>"` 或 `resolution.capability_id == "<cid>"`。"""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == cid
        and (
            (isinstance(test.left, ast.Name) and test.left.id.endswith("capability_id"))
            or (isinstance(test.left, ast.Attribute) and test.left.attr.endswith("capability_id"))
        )
    )


def dispatch_table(source: str | None = None) -> dict[tuple[str, str], _Route]:
    """现算「哪一形、哪个 handler、经哪枚汇口、用哪个构造器」。

    比静态尺更窄：静态尺只问"函数体里有没有汇口"，本表还要问"这一形这一能力具体把哪个构造器
    交给哪枚汇口"。形状对不上（零/多构造器、多汇口、缺 handler）一律当场红，**绝不**降级成
    "少测几枚"（缩扫描面＝造绿）。
    """
    text = source if source is not None else _root_source()
    tree = ast.parse(text)
    funcs = _func_nodes(tree)
    routes: dict[tuple[str, str], _Route] = {}

    for form, handler in (("alias", "_handle_alias"), ("natural", "_handle_natural")):
        node = _single_func(tree, handler)
        seams = _seam_names(node)
        assert seams == {PIPELINE_SEAM}, f"{handler} 的合法汇口不是唯一一枚 {PIPELINE_SEAM}：{sorted(seams)}"
        for cid in MUST_WATCH:
            branches = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.If) and _compare_to_cid(child.test, cid)
            ]
            assert len(branches) == 1, f"{handler} 里 {cid} 命中 {len(branches)} 个分支＝无法定值"
            names = sorted(
                {
                    call.func.id
                    for stmt in branches[0].body  # 不含 orelse：elif 链的下游分支不算本支
                    for call in ast.walk(stmt)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and not hasattr(builtins, call.func.id)
                }
            )
            assert len(names) == 1, (
                f"{handler} 的 {cid} 分支里有 {len(names)} 个非内建被调名 {names}"
                "＝构造器判据失效，须改写本表（不许退回手抄期望值）"
            )
            routes[(form, cid)] = _Route(form, cid, handler, PIPELINE_SEAM, names[0])

    for nodes in funcs.values():
        for node in nodes:
            for call in _own_nodes(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == SIMPLE_SEAM
                    and len(call.args) == 5
                ):
                    continue
                cid_const, factory = call.args[3], call.args[2]
                if not (
                    isinstance(cid_const, ast.Constant)
                    and isinstance(cid_const.value, str)
                    and cid_const.value in MUST_WATCH
                    and isinstance(factory, ast.Name)
                ):
                    continue
                key = ("command", str(cid_const.value))
                assert key not in routes, f"命令形 {key[1]} 派出两枚 handler"
                routes[key] = _Route("command", key[1], node.name, SIMPLE_SEAM, factory.id)

    for form in ("command", "alias", "natural"):
        for cid in MUST_WATCH:
            assert (form, cid) in routes, f"派生不到 {form}/{cid}＝三形同权失去样本"
    return routes


def _routes() -> list[_Route]:
    table = dispatch_table()
    return [table[(form, cid)] for form in ("command", "alias", "natural") for cid in MUST_WATCH]


# ================================================================ 替身（只替被测之外的一切）
class _Recorder:
    def __init__(self) -> None:
        self.seam_hits: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.built: list[tuple[str, Any, Any]] = []
        self.bypass: list[str] = []


class _Message:
    """最小 `IncomingMessage`：只需要 `model_copy(update=…)` 与几个标量属性。"""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def model_copy(self, *, update: dict[str, Any] | None = None) -> _Message:
        clone = _Message(**self.__dict__)
        for key, value in (update or {}).items():
            setattr(clone, key, value)
        return clone


def _message() -> _Message:
    return _Message(
        request_id="req-s167",
        plain_text="天气 湘潭",
        sender_id="3865067623",
        session_id="private_3865067623",
        session_type="private",
    )


class _FakeBuilder:
    """能力构造器替身：`factory(config) -> capability(message, decision)`。"""

    def __init__(self, name: str, rec: _Recorder) -> None:
        self.name = name
        self.rec = rec
        self.calls = 0

    def __call__(self, config: Any) -> Callable[[Any, Any], Any]:
        self.calls += 1

        def _capability(message: Any, decision: Any) -> Any:
            self.rec.built.append((self.name, message, decision))
            return _RESULT

        return _capability


class _FakePipeline:
    """注毒"绕过汇口直喂 pipeline"时要有东西真能跑——否则红是**崩**出来的、不是**判**出来的。"""

    def __init__(self, rec: _Recorder) -> None:
        self.rec = rec

    def handle(self, message: Any, capability: Any, *, capability_id: str = "") -> Any:
        self.rec.bypass.append(f"handle:{capability_id}")
        return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="bypassed")

    async def handle_async(
        self, message: Any, capability: Any, *, capability_id: str = ""
    ) -> Any:
        self.rec.bypass.append(f"handle_async:{capability_id}")
        return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="bypassed")


class _Matcher:
    async def finish(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _seam_stub(rec: _Recorder, name: str) -> Callable[..., Any]:
    async def _seam(*args: Any, **kwargs: Any) -> Any:
        rec.seam_hits.append((name, args, kwargs))
        return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="已送达")

    return _seam


def _dead_stub_factory(rec: _Recorder) -> Callable[[Any], Callable[[Any, Any], Any]]:
    """注毒⑥用：形状与真构造器**完全相同**（`factory(config) -> capability`）、也照样返回哨兵结果，
    唯独不登记"命中了派生构造器"⇒ 红只能是"交进去的闭包不再指向那枚真构造器"这一条，
    不会被 TypeError 抢走归因（那等于用崩冒充判）。"""

    def _factory(_config: Any) -> Callable[[Any, Any], Any]:
        def _capability(message: Any, decision: Any) -> Any:
            rec.bypass.append("dead_stub")
            return _RESULT

        return _capability

    return _factory


class _LegacyDispatched:
    def __init__(self, rec: _Recorder) -> None:
        self.rec = rec

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        self.rec.bypass.append("legacy_direct_dispatch")
        return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="legacy")


# ================================================================ Leg A：入口 → 汇口
def _handler_namespace(route: _Route, rec: _Recorder) -> dict[str, Any]:
    resolution = SimpleNamespace(
        capability_id=route.capability_id,
        rest_text="雨湖",  # 与 normalized_text 刻意不同：查询词是否被分支自己重写进 plain_text 可判别
        normalized_text="天气 湘潭",
        verb="天气",
        ambiguous=False,
    )
    builders = {route.builder: _FakeBuilder(route.builder, rec)}
    namespace: dict[str, Any] = {
        "__builtins__": builtins,
        "Any": Any,
        "alias_resolver": SimpleNamespace(resolve=lambda _text: resolution),
        "detect_natural_command": lambda _text, _config: resolution,
        "alias": _Matcher(),
        "natural": _Matcher(),
        "weather": _Matcher(),
        "wiki": _Matcher(),
        "eat": _Matcher(),
        "news": _Matcher(),
        "epic": _Matcher(),
        "config": SimpleNamespace(bot_music_candidates_enabled=False),
        "pipeline": _FakePipeline(rec),
        "send_queue": SimpleNamespace(),
        "audit_logger": SimpleNamespace(),
        "diagnostics_store": SimpleNamespace(),
        "receipt_repository": SimpleNamespace(),
        "history_recorder": None,
        "runtime_settings": SimpleNamespace(get=lambda *_a, **_k: ""),
        "render_backend": SimpleNamespace(),
        "OFFLOADED_CAPABILITY_IDS": _string_set_literal("OFFLOADED_CAPABILITY_IDS"),
        "NO_RUNTIME_DIAGNOSTIC_CAPABILITY_IDS": frozenset(),
        "should_finish_nonebot_matcher": lambda _receipt: False,
        "_notify_operational_receipt": lambda *_a, **_k: None,
        "_resolve_bot_avatar_url": lambda *_a, **_k: "",
        "_legacy_direct_dispatch": _LegacyDispatched(rec),
        "_dead_stub_factory": _dead_stub_factory(rec),
        **builders,
    }
    namespace[PIPELINE_SEAM] = _seam_stub(rec, PIPELINE_SEAM)
    namespace[SIMPLE_SEAM] = _seam_stub(rec, SIMPLE_SEAM)
    return namespace


def _leg_a_violations(
    route: _Route,
    *,
    segment_override: str | None = None,
) -> list[str]:
    """把真 handler 跑一遍，返回运行期违反清单（空＝这一形这一能力确实抵达并被治理）。"""
    rec = _Recorder()
    segment = segment_override if segment_override is not None else _raw_segment(route.handler)
    try:
        namespace = _handler_namespace(route, rec)
        exec(  # noqa: S102 — 盘上真源码或内存注毒副本，绝不 exec 外部输入
            compile(_module_src(segment, route.handler), f"<s167-legA {route.handler}>", "exec"),
            namespace,
        )
        handler = namespace[route.handler]
        event = SimpleNamespace(get_plaintext=lambda: "天气 湘潭")
        asyncio.run(handler(SimpleNamespace(self_id="1"), event))
    except Exception as exc:  # noqa: BLE001 — 运行期炸＝活性腿不成立，须成为**判定**而非 error
        return [f"{route.label()}：分发抛出 {type(exc).__name__}: {exc}"]

    prefix = route.label()
    hits = [hit for hit in rec.seam_hits if hit[0] in LEGAL_SEAMS]
    if len(hits) != 1:
        return [
            f"{prefix}：抵达合法汇口 {len(hits)} 次（应为恰 1）；旁路记录={rec.bypass}；"
            "汇口记录=" + str([h[0] for h in rec.seam_hits])
        ]
    name, args, kwargs = hits[0]
    violations: list[str] = []
    if name != route.seam:
        violations.append(f"{prefix}：汇口漂移为 {name}，派生期望 {route.seam}")

    if route.seam == PIPELINE_SEAM:
        given_cid = kwargs.get("capability_id")
        if given_cid != route.capability_id:
            violations.append(
                f"{prefix}：交给层 2 的 capability_id={given_cid!r} 不是解析结果"
                "（R-CHOKE C-1 型：写入口名 ⇒ 整条绕开权限/健康/限额/审计）"
            )
        expect_offload = route.capability_id in _string_set_literal("OFFLOADED_CAPABILITY_IDS")
        if kwargs.get("offload_sync_capability") is not expect_offload:
            violations.append(
                f"{prefix}：offload_sync_capability={kwargs.get('offload_sync_capability')!r}"
                f" 与生产名册现算值 {expect_offload} 不符"
            )
        capability = kwargs.get("capability")
        if not callable(capability):
            violations.append(f"{prefix}：汇口没收到可调用闭包：{capability!r}")
            return violations
        result = capability(_message(), SimpleNamespace(actor_roles=("user",)))
        hit_names = [entry[0] for entry in rec.built]
        if hit_names != [route.builder]:
            violations.append(
                f"{prefix}：闭包被调用时没有命中派生构造器 {route.builder}（实得 {hit_names}）"
                "＝闭包是死码/被换成自造结果"
            )
        elif result is not _RESULT:
            violations.append(f"{prefix}：闭包没把构造器结果原样带回：{result!r}")
        else:
            recorded = rec.built[0][1]
            if getattr(recorded, "request_id", None) != "req-s167":
                violations.append(f"{prefix}：闭包没把管线传入的消息转交给构造器")
    else:
        if len(args) != 5:
            return [f"{prefix}：命令形汇口收到 {len(args)} 个位置参数，派生期望 5"]
        factory = args[2]
        if not isinstance(factory, _FakeBuilder) or factory.name != route.builder:
            violations.append(
                f"{prefix}：命令形交给汇口的执行体不是派生构造器 {route.builder}：{factory!r}"
            )
            return violations
        given_cid = args[3]
        if given_cid != route.capability_id:
            violations.append(f"{prefix}：命令形交出的 capability_id={given_cid!r} 不是 {route.capability_id}")
        built = factory(SimpleNamespace())
        rec.built.clear()
        built(_message(), SimpleNamespace(actor_roles=("user",)))
        if [entry[0] for entry in rec.built] != [route.builder]:
            violations.append(f"{prefix}：命令形执行体没被真构造器接住（rec.built={rec.built}）")
        elif rec.built[0][2] is None:
            violations.append(f"{prefix}：命令形闭包没收到管线的 decision")
    return violations


# ================================================================ Leg B：汇口 → 包缝
class _Governed:
    """`orchestrated_command` 替身的返回值：可识别、可调用、把调用转给裸能力。

    `wrapped=True` 复刻真身在 `_step` 上挂 `orchestrated_capability_id` 的事实
    （`capability_protocols.py:2287` 现算实证：那枚幂等守卫**不是**装饰，真会挂）——
    汇口的 `getattr(capability, "orchestrated_capability_id", None) is None` 判据才有意义。
    """

    def __init__(self, capability_id: str, inner: Any, *, wrapped: bool = True) -> None:
        self.orchestrated_by_spy = capability_id
        self.orchestrated_capability_id: str | None = capability_id if wrapped else None
        self.inner = inner
        self.ran: list[Any] = []

    def __call__(self, message: Any, decision: Any) -> Any:
        self.ran.append(message)
        return self.inner(message, decision)


def _run_pipeline_seam(
    monkeypatch: pytest.MonkeyPatch,
    *,
    segment: str | None = None,
    capability_id: str = "bot.weather",
    offload: bool = False,
    pre_orchestrated: bool = False,
) -> dict[str, Any]:
    """exec 真 `_run_capability_through_pipeline`，返回观测（spy 调用、pipeline 收到的步、回执）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        ingress as ingress_mod,
    )
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        pipeline as pipeline_mod,
    )
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    observed: dict[str, Any] = {"wrap_calls": [], "steps": [], "offload": []}

    def _spy(cid: str, cap: Any, cfg: Any) -> Any:
        governed = _Governed(cid, cap)
        observed["wrap_calls"].append((cid, cap, cfg, governed))
        return governed

    class _Gateway:
        def __init__(self, factory: Any) -> None:
            self.factory = factory

        def from_event(self, event: Any, *, bot_id: str = "unknown") -> Any:
            return _message()

    class _Pipeline:
        def handle(self, message: Any, step: Any, *, capability_id: str = "") -> Any:
            observed["steps"].append(("handle", step, capability_id))
            return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="ok")

        async def handle_async(self, message: Any, step: Any, *, capability_id: str = "") -> Any:
            observed["steps"].append(("handle_async", step, capability_id))
            return SimpleNamespace(state=SimpleNamespace(value="sent"), public_message="ok")

    # 汇口内部三处 `from .x import y` 都在**调用期**从模块对象取名 ⇒ 换模块属性即可命中。
    monkeypatch.setattr(cp, "orchestrated_command", _spy, raising=False)
    monkeypatch.setattr(ingress_mod, "IngressGateway", _Gateway, raising=False)
    monkeypatch.setattr(
        pipeline_mod,
        "offload_capability",
        lambda cap: (observed["offload"].append(cap), cap)[1],
        raising=False,
    )

    raw: Any
    if pre_orchestrated:
        raw = _Governed(capability_id, lambda message, decision: _RESULT)
    else:
        raw = lambda message, decision: _RESULT  # 裸能力替身，只需可调用

    namespace: dict[str, Any] = {
        "__builtins__": builtins,
        "__package__": "plugins.bot_unified_runtime",
        "Any": Any,
        "inspect": inspect,
        "_incoming_from_nonebot_event": lambda *_a, **_k: _message(),
        "_notify_operational_callback": _noop_callback(),
        "_find_sent_request": lambda *_a, **_k: None,
        "_deliver_transport_send_request": lambda *_a, **_k: None,
        "_record_chat_history_turn": lambda *_a, **_k: None,
        "_record_runtime_diagnostic": lambda *_a, **_k: None,
    }
    exec(  # noqa: S102 — 盘上真源码或内存注毒副本
        compile(
            _module_src(segment if segment is not None else _raw_segment(PIPELINE_SEAM), PIPELINE_SEAM),
            "<s167-legB>",
            "exec",
        ),
        namespace,
    )
    seam = namespace[PIPELINE_SEAM]
    receipt = asyncio.run(
        seam(
            bot=SimpleNamespace(self_id="1"),
            event=SimpleNamespace(),
            config=SimpleNamespace(),
            pipeline=_Pipeline(),
            send_queue=SimpleNamespace(),
            audit_logger=SimpleNamespace(),
            diagnostics_store=SimpleNamespace(),
            capability=raw,
            capability_id=capability_id,
            record_diagnostic=False,
            offload_sync_capability=offload,
            history_recorder=None,
        )
    )
    observed["receipt"] = receipt
    observed["raw"] = raw
    return observed


def _noop_callback() -> Any:
    async def _cb(*_args: Any, **_kwargs: Any) -> None:
        return None

    return _cb


def _leg_b_violations(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> list[str]:
    observed = _run_pipeline_seam(monkeypatch, **kwargs)
    cid = str(kwargs.get("capability_id", "bot.weather"))
    offload = bool(kwargs.get("offload", False))
    violations: list[str] = []
    wraps = observed["wrap_calls"]
    if kwargs.get("pre_orchestrated"):
        if wraps:
            violations.append(f"已带 orchestrated_capability_id 的能力被二次包缝（{len(wraps)} 次）")
        step = observed["steps"][0][1] if observed["steps"] else None
        if step is not observed["raw"]:
            violations.append("幂等守卫失效：汇口交给 pipeline 的不是原能力")
    else:
        if len(wraps) != 1:
            return [f"汇口没有恰好包一次缝（orchestrated_command 被调 {len(wraps)} 次）"]
        got_cid, got_cap, _cfg, governed = wraps[0]
        if got_cid != cid or got_cap is not observed["raw"]:
            violations.append(f"包缝参数不对：cid={got_cid!r} 能力同源={got_cap is observed['raw']}")
        want_entry = "handle_async" if offload else "handle"
        if len(observed["steps"]) != 1 or observed["steps"][0][0] != want_entry:
            violations.append(f"pipeline 入口不对：{observed['steps']}（期望 {want_entry}）")
            return violations
        step = observed["steps"][0][1]
        if step is not governed:
            violations.append(
                "pipeline 收到的不是包缝后的执行体＝层 2 治理被绕过（走进了没治理的口子）"
            )
        if observed["offload"] and observed["offload"][0] is not governed and offload:
            violations.append("offload 包的不是治理后的执行体")
        if not offload and observed["offload"]:
            violations.append(f"未开 offload 却调了 offload_capability：{observed['offload']}")
    return violations


# ================================================================ 注毒（内存串，绝不回写文件）
def _static_leg_still_sees_the_call(handler_name: str, segment: str) -> bool:
    """静态判据那一腿的形状复现：把注毒段回填进整树后，"该 handler 自己的节点里有没有汇口调用"。

    只用于对照——本件不宣称自己是那把静态尺的 owner，也不替它改判据。
    """
    whole = _root_source().replace(_raw_segment(handler_name), segment, 1)
    assert whole != _root_source(), "注毒没落进整树，静态尺对照无意义"
    node = _single_func(ast.parse(whole), handler_name)
    return bool(_seam_names(node))


def _seam_names(scope: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in _own_nodes(scope)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in LEGAL_SEAMS
    }


def _poison_early_return(segment: str, seam_call: str) -> str:
    """G3 点名的失效形态：汇口调用**照样在场**，但前面多一条 `return` ⇒ 运行期永远不抵达。"""
    lines = segment.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if seam_call + "(" in line:
            indent = line[: len(line) - len(line.lstrip())]
            poisoned = "".join(
                [*lines[:index], f"{indent}return  # 注毒：先返回、后汇缝（静态尺照绿）\n", *lines[index:]]
            )
            assert poisoned != segment
            return poisoned
    raise AssertionError(f"注毒点消失：段里找不到 {seam_call} 调用")


def _poison_drop_seam(segment: str, seam_call: str) -> str:
    """把该形的汇口整条换成"另一条不在名册里的路"。"""
    assert seam_call + "(" in segment, "注毒点消失（汇口被改名/搬走），须同步本自证"
    return segment.replace(seam_call + "(", "_legacy_direct_dispatch(", 1)


def _poison_stub_closure(segment: str, builder: str) -> str:
    """把分支闭包里的构造器调用换成"同形但无迹"的替身 ⇒ 抵达汇口、结果照样返回，
    只是交进去的闭包不再指向那枚在册构造器。"""
    needle = f"{builder}(config)"
    assert needle in segment, f"注毒点消失：找不到 {needle}"
    return segment.replace(needle, "_dead_stub_factory(config)", 1)


def _poison_force_entry_name(segment: str) -> str:
    """别名形把交给层 2 的 id 写死成入口名（R-CHOKE C-1 的历史绕过路）。"""
    needle = 'capability_id = resolution.capability_id or "bot.alias"'
    assert needle in segment, "注毒点消失：别名入口的 cid 取数写法变了，须同步本自证"
    return segment.replace(needle, 'capability_id = "bot.alias"', 1)


def _poison_drop_wrapping(segment: str) -> str:
    """摘掉汇口里的 `orchestrated_command` 包缝 ⇒ "抵达汇口"变回一句空话。"""
    tree = ast.parse(textwrap.dedent(segment))
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    kept = [
        stmt
        for stmt in func.body
        if not (isinstance(stmt, ast.If) and "orchestrated_capability_id" in ast.unparse(stmt))
    ]
    assert len(kept) == len(func.body) - 1, "注毒没正好摘掉那条包缝 if＝汇口形状变了，须重判"
    func.body = kept
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


# ================================================================ 基线：三形 × 五能力全跑
def test_dispatch_table_is_derived_and_complete() -> None:
    """表从真树现算、覆盖 3 形 × 5 能力，且逐形点名其汇口（不许把两枚汇口混成一锅）。"""
    table = dispatch_table()
    assert len(table) == 15, f"派生出 {len(table)} 条，期望 15＝覆盖面漂了"
    for route in _routes():
        assert route.seam in LEGAL_SEAMS, route.label()
    seams_by_form = {
        form: {route.seam for key, route in table.items() if key[0] == form}
        for form in ("command", "alias", "natural")
    }
    assert seams_by_form == {
        "command": {SIMPLE_SEAM},
        "alias": {PIPELINE_SEAM},
        "natural": {PIPELINE_SEAM},
    }, f"逐形汇口派生异常：{seams_by_form}"
    # 反真空：命令形是"一能力一 handler"，五枚必须落在五枚不同 handler 上。
    command_handlers = {route.handler for key, route in table.items() if key[0] == "command"}
    assert len(command_handlers) == 5, f"命令形 handler 只有 {sorted(command_handlers)}"


@pytest.mark.parametrize("route", _routes(), ids=lambda r: r.label())
def test_three_entry_forms_reach_the_central_seam_when_executed(route: _Route) -> None:
    """活性腿主判据：盘上真源码跑一遍，这一形这一能力确实抵达汇口并交出活闭包。"""
    violations = _leg_a_violations(route)
    assert violations == [], "三形入口活性不成立：\n" + "\n".join(violations)


def test_alias_form_rewrites_query_into_plain_text() -> None:
    """别名形把 rest_text 重新拼进 plain_text（「天气 雨湖」），自然语言形交归一文本。

    这条与活性腿同批立：只断"抵达汇口"不足以证明交出去的能力**带对了查询**——两形的期望值
    在此天然可判别（`rest_text` 与 `normalized_text` 刻意取不同值）。
    """
    table = dispatch_table()
    alias = table[("alias", "bot.weather")]
    natural = table[("natural", "bot.weather")]
    for route, want in ((alias, "天气 雨湖"), (natural, "天气 湘潭")):
        rec = _Recorder()
        namespace = _handler_namespace(route, rec)
        exec(  # noqa: S102
            compile(_module_src(_raw_segment(route.handler), route.handler), "<s167-q>", "exec"),
            namespace,
        )
        asyncio.run(namespace[route.handler](SimpleNamespace(self_id="1"), SimpleNamespace(
            get_plaintext=lambda: "天气 湘潭")))
        capability = rec.seam_hits[0][2]["capability"]
        capability(_message(), SimpleNamespace(actor_roles=("user",)))
        assert rec.built[0][1].plain_text == want, f"{route.label()} 的查询词没落进 plain_text"


# ================================================================ Leg B 基线
def test_pipeline_seam_wraps_capability_with_central_governance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真汇口在运行期确实过 `orchestrated_command`，且 pipeline 收到的就是包缝后的那一步。"""
    assert _leg_b_violations(monkeypatch) == []


@pytest.mark.parametrize("capability_id", sorted(MUST_WATCH))
def test_pipeline_seam_wraps_offloaded_capabilities(
    monkeypatch: pytest.MonkeyPatch, capability_id: str
) -> None:
    """offload 分支（线程池下放）同样在包缝之后：别只证同步那条路。"""
    offloaded = _string_set_literal("OFFLOADED_CAPABILITY_IDS")
    violations = _leg_b_violations(
        monkeypatch, capability_id=capability_id, offload=capability_id in offloaded
    )
    assert violations == [], f"{capability_id}（offload={capability_id in offloaded}）：{violations}"


def test_pipeline_seam_never_double_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    """幂等守卫：已带 `orchestrated_capability_id` 的能力不再包第二次（双重治理=双重记账）。"""
    assert _leg_b_violations(monkeypatch, pre_orchestrated=True) == []


# ================================================================ 注毒自证
def test_poison_alias_early_return_goes_red_and_static_leg_stays_green() -> None:
    """注毒①（G3 的正面）：别名形汇口前插一条 `return` ⇒ 活性腿红，而**静态尺照绿**。

    两条断言缺一条本件就没有存在理由：只红不证静态尺失明＝重复劳动；
    只证静态尺失明不红＝散文。
    """
    route = dispatch_table()[("alias", "bot.weather")]
    segment = _raw_segment(route.handler)
    poisoned = _poison_early_return(segment, PIPELINE_SEAM)

    assert PIPELINE_SEAM + "(" in poisoned, "注毒把汇口调用抹掉了＝验的不是运行期早退"
    assert _static_leg_still_sees_the_call(route.handler, poisoned), (
        "注毒段里静态判据已经看不见汇口调用＝对照失效，本腿的必要性叙述过期，须复判"
    )
    assert _leg_a_violations(route, segment_override=poisoned), "运行期早退摘掉了汇口，活性腿却全绿＝假锁"


def test_poison_alias_bypass_pipeline_directly() -> None:
    """注毒②：别名形把能力直接交给 `pipeline`（绕过汇口）⇒ 活性腿红。"""
    route = dispatch_table()[("alias", "bot.wiki")]
    poisoned = _poison_drop_seam(_raw_segment(route.handler), PIPELINE_SEAM)
    violations = _leg_a_violations(route, segment_override=poisoned)
    assert violations, "绕开汇口直喂 pipeline，活性腿却全绿＝假锁"
    assert "抵达合法汇口 0 次" in violations[0], violations


def test_poison_natural_bypass_pipeline_directly() -> None:
    """注毒③：自然语言形同样摘掉汇口 ⇒ 活性腿红（三形各自有腿，不是一腿护三形）。"""
    route = dispatch_table()[("natural", "bot.eat")]
    poisoned = _poison_drop_seam(_raw_segment(route.handler), PIPELINE_SEAM)
    assert _leg_a_violations(route, segment_override=poisoned), "自然语言形摘掉汇口未被抓到"


def test_poison_command_form_bypass_simple_seam() -> None:
    """注毒④：命令形把 `_run_simple_capability` 换成名册外的路 ⇒ 活性腿红。"""
    route = dispatch_table()[("command", "bot.news")]
    poisoned = _poison_drop_seam(_raw_segment(route.handler), SIMPLE_SEAM)
    violations = _leg_a_violations(route, segment_override=poisoned)
    assert violations, "命令形摘掉汇口，活性腿却全绿＝假锁"
    assert "抵达合法汇口 0 次" in violations[0], violations


def test_poison_alias_reports_entry_name_not_resolved_id() -> None:
    """注毒⑤（R-CHOKE C-1 复现）：别名形把层 2 的 id 写死成入口名 ⇒ 活性腿点名。"""
    route = dispatch_table()[("alias", "bot.epic")]
    poisoned = _poison_force_entry_name(_raw_segment(route.handler))
    violations = _leg_a_violations(route, segment_override=poisoned)
    assert any("capability_id='bot.alias'" in item for item in violations), violations


def test_poison_dead_closure_still_reaches_the_seam() -> None:
    """注毒⑥：闭包里的构造器换成同形替身 ⇒ **仍然抵达汇口**、结果照样返回，
    活性腿仍判"交进去的闭包不再指向在册构造器"红。

    这条把"抵达"与"交进去的东西是活的"分开钉：只断前者会放过"汇口收到一枚空转闭包"。
    替身刻意不抛异常——红必须来自判据，不能来自崩。
    """
    route = dispatch_table()[("alias", "bot.epic")]
    poisoned = _poison_stub_closure(_raw_segment(route.handler), route.builder)
    assert "_dead_stub_factory(config)" in poisoned, "注毒没落进闭包＝自证空跑"
    violations = _leg_a_violations(route, segment_override=poisoned)
    assert any("没有命中派生构造器" in item for item in violations), violations
    assert not any("抛出" in item for item in violations), f"红来自崩而不是判据：{violations}"


def test_poison_seam_without_wrapping_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒⑦：汇口里不包缝 ⇒ Leg B 红（否则"抵达汇口"只是走进一个没治理的口子）。"""
    segment = _raw_segment(PIPELINE_SEAM)
    poisoned = _poison_drop_wrapping(segment)
    assert "orchestrated_capability_id" not in poisoned.split("async def")[1], "注毒没摘掉包缝判据"
    violations = _leg_b_violations(monkeypatch, segment=poisoned)
    assert violations, "摘掉 orchestrated_command 包缝，汇口腿却全绿＝假锁"
