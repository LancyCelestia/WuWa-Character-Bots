"""五入口同缝同权：主动投递形 + 语音回执形的「多入口汇缝」活性锁（S16 立，S136 随降账改版，全离线 AST）。

一句话先说清楚（别把本件当"两形已同缝"的历史叙述）：**枚二与枚四今天都是零容忍门，不是棘轮**——
当年那批欠账（cookie 到期缺省直发、入群欢迎/cookie 二维码两枚事件旁路）已于 2026-09-24 裁定 R-4
全量收编进统一管线，两本基线现算降为空。账不存在了，判据就不许退回"名册为空所以全绿"那种空跑
（＝计数腿真空），所以两枚都改成扫真树的硬尺 + 合成注毒自证"尺没瞎"。
**枚二曾经红过的事实**（"这一形尚未全汇缝"的如实记账）留在 `_ACTIVE_PUSH_BYPASS_BASELINE` 的注释里，
别把它叙述成"一直如此"。既有锁（R-PREP/R-CHOKE 的 canary + descriptor 台账）只坐实命令/别名/
自然语言三形：`seam_registered_cids()` 证"声明了执行形"，多入口活性锁证"每条分发入口都汇到
`_run_capability_through_pipeline`"——主动投递与语音回执这两形的逐入口汇缝锁是本件补的。

本件补这两形的锁，并诚实区分"已成立"与"未成立"：

* **语音回执形**——今天确实汇到唯一出口：pipeline `_emit_progress_ack` 只调注入的 `progress_ack_submit`
  （不裸调 `send_queue.submit`、不 `call_api` 直发），根把它接成 `_submit_progress_ack`，
  后者只经 `submit_active_push`。⇒ 这一形写**诚实绿的收敛锁**（带牙）。
* **主动投递形**——2026-09-24 起全汇缝：`_cookie_expiry_reminder_job` 的 `via_queue` 缺省关分支
  已删，名单内每员都只经 `submit_active_push`。⇒ 枚二写零容忍硬尺（长出即红），不再写棘轮。

判据纪律（HARDEN-1 立的"期望值不得复用被审函数本身"）：
- 「是不是主动投递入口」用**独立判据**枚举——具名调度族清单（AGENTS #49 四族 + 回执 + 紧急域）
  经"该函数确能抵达某种出站 sink"这一**双 sink 口径**（`submit_active_push` **或** `call_api send_*_msg`）
  反幻影；**不**用 `submit_active_push` 的行为去反推谁是入口。
- 「是否汇缝」= 该入口的传递调用闭包能否抵达中央出口 `submit_active_push`（含 `_push_via_central_exit_now`
  这条同义跳），且它自己**不含**任何 `call_api send_*_msg` 旁路 sink。
- 全树只读：注毒一律走 `source=` 入参喂内存源码，**绝不写 `plugins/**`**。

**枚六（2026-09-24 S182 落 S168 §3 裁定）· 动态名硬禁**：直发尺的取数口从「只认
`.call_api("<字面量>")`」升级为「三被调体（属性/getattr直调/别名）× 首参（字面量/同帧唯一
字符串赋值折叠）」，且与齿锁不同——**折不出 api 的动态名不"保守放过"，而是点名入账**
`(file, func, 形态, 首参源码形)`。普查扫全生产树（排除面 AST 现读齿锁，不许两把尺分开），
零容忍：动态名普查 == `_DYNAMIC_BOUNDED_SITES`（恰三枚 by-design bounded 通道体：
`control_plane/dispatcher.py::execute` 的 `method`——唯一来源是 TransportRegistry 固定映射、
「绝不拼接合成 API 名」（`dispatcher.py:136`），且过 admission/lease 双门；
`domains/chat_reply/capabilities/group_info.py::call` 的 `action`——桥接器形参，能力入口只传
四枚字面 `get_*`（`group_info.py:298-313`）；
根 `__init__.py::_dispatch_persona_appearance_if_switched` 的 `action`（S-PERSONA-WIRE
2026-09-27 收编）——人格热切换外观下发唯一适配器（H-1 唯一下发口），`action` 唯一来源＝
`persona_profile.apply_persona_profile` 通道本体内两枚字面 `set_qq_profile`/`set_qq_avatar`，
跨函数静态折不出但枚举封闭在册，不许拼名）。第四枚动态名在任何非排除文件长出＝当场红。
**本批顺带钉死齿锁折叠的两处渗漏**（齿锁件禁动，渗漏在其件照旧存在，账记 SEAT-S182 §齿漏）：
① 其 `_resolve_api` 从不查各帧 `ambiguous` 集——函数内 `method=Call值` 被剔出 consts 后，
名字查找穿透到外层同名**类体**常量 `method: str = ""` 折成 `""`，既不算旁路也不算盲区＝静默丢弃
（dispatcher:202 失明的真实机理，比"保守放过"更糟）；② 其 `_collect_bindings` 把类体绑定并进
模块帧，而 Python 类作用域对方法不可见。本件取数口两条都修，并有注毒复现（牙3）。

**S189 再闭一枚同族第四态（本件尺，非齿锁）**：渗漏 ① 的通用形态是「折出一个**看起来像成功、
实则不可用**的 api 名后静默丢弃」。旧 `_visit` 判据 `if api is not None` 把**空串/纯空白**当成
"已判定的非旁路 api"就地放过（`''` 既不在 `_BYPASS_APIS`、又非 `None`，于是 resolved、dynamic
两头都不进＝第四态）。dispatcher 那枚今天已不触发此路径（`method` 是 Call→歧义→None→dynamic），
但这条判据对任何 `call_api('')`／`API=''; call_api(API)` 都漏。修法＝折叠成功仅当 api 名 strip 后
非空，否则计入 dynamic 点名入账（保守侧、宁滥勿漏，只准 dynamic 变大）。执法面＝本件 `_scan_call_api_sites`
尺 + `test_fold_failure_never_silently_drops`（注毒「折成空串」必红）；齿锁 `_resolve_api` 同型洞仍待其
owner 同批复判（本席禁动，账转 §3 交回主代理）。

复跑（席位纪律）见 SEAT-S16.md、SEAT-S182.md 与 SEAT-S189.md。
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections import deque
from collections.abc import Set as AbstractSet

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parents[0]
sys.path.insert(0, str(_REPO_ROOT))

_ROOT_INIT = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
_PUSH_PY = _REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "emergency_info" / "service" / "push.py"
_PIPELINE_PY = (
    _REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "pipeline.py"
)

# --------------------------------------------------------------------------- 事实常量
#: 主动投递唯一中央出口（真身住 outbound_gate.py:716，其内部才触达 `SendQueue.submit`）
#: 与其同义跳（根内联封装，返回"本轮可否就地投"）；二者都算"到达中央出口"。
_CENTRAL_TERMINALS = frozenset({"submit_active_push", "_push_via_central_exit_now"})
#: 中央出口的封装跳（根内），沿调用图走到 submit_active_push 的中转站。
_CENTRAL_HOPS = frozenset(
    {
        "_push_via_central_exit_now",
        "_deliver_cookie_expiry_report_via_queue",
    }
)
#: 直发旁路 sink（绕过闸＝绕过唯一出口）。**两族名单与 `test_active_push_entry_teeth.py`
#: 逐枚相等**（裁定 R-5 把 upload/delete 族扩进两把尺；枚五第五条腿现算比对，只扩一侧必红）。
#: 投递族（send 三枚）判"绕过唯一出口没投出去"；upload/delete 族判"绕过统一管线的第二条 mutating 路"。
_BYPASS_APIS_MESSAGE = frozenset({"send_private_msg", "send_group_msg", "send_msg"})
_BYPASS_APIS_FILE_MUTATION = frozenset({"upload_group_file", "upload_private_file", "delete_msg"})
_BYPASS_APIS = _BYPASS_APIS_MESSAGE | _BYPASS_APIS_FILE_MUTATION

#: 枚一/枚二共用的主动投递入口名单（独立于 `submit_active_push` 而按调度族点名，源自 AGENTS #49 四族 + 紧急域）。
#: 这一列是**作者手写的期望真值**，不是把被审函数跑一遍抄回来的——HARDEN-1 纪律的落点。
_ACTIVE_PUSH_ROSTER = frozenset(
    {
        "_deliver_due_reminders",  # 提醒族（scheduler bot_reminder_tick）
        "_deliver_cookie_expiry_report_via_queue",  # cookie 到期·via_queue 分支（收编态）
        "_push_daily_group_digests",  # 群摘要族（bot_group_digest_push_daily）
        "_push_daily_assist_private",  # 日常助理族（morning/evening/meal）
        "_cookie_expiry_reminder_job",  # cookie 到期调度入口：内含双分支，缺省走旁路
        "deliver_emergency",  # 紧急域投递（push.py，唯一出口现役 owner）
    }
)

#: 枚二的欠账基线：2026-09-24 现算**降账至零**——`_cookie_expiry_reminder_job` 的
#: `via_queue` 缺省关直发分支已随裁定 R-4 删除（`__init__.py:4817-4830` 注释即那次收编的落款），
#: 全树实测该族名单内**无一枚**含直发 sink。基线空了还留着"只降不升"的棘轮，
#: 就是 R-新1 点名不许的空跑（名册为空所以全绿）⇒ 本枚改判成**零容忍**：
#: 名单内任何一员长出 mutating 直发即违反；"尺没瞎"由 `test_active_push_zero_tolerance_lock_has_teeth`
#: 的合成直发注毒自证，不再靠"今天确实还有欠账"当证据。
_ACTIVE_PUSH_BYPASS_BASELINE: frozenset[str] = frozenset()

#: 枚四：**事件/命令驱动**的直发旁路名单（与上面那份主动投递名单**分册**，绝不并册）。
#: 为什么不并进 `_ACTIVE_PUSH_ROSTER`（本案最重要的一条口径，别顺手改成并册）：
#: ① 这两枚的开态分支走的是**中央管线汇口** `_run_capability_through_pipeline`
#:   （摄取 → `_prepare` 门禁+限流+幂等 → 能力 → 审核 → 渲染 → SendQueue → 内联投递），
#:   而不是主动投递唯一出口 `submit_active_push`。把它们写进 `_ACTIVE_PUSH_ROSTER`
#:   会撞上本件导入期的反幻影闸 `_reaches_central_any`（现算必 False）⇒
#:   **整件不可收集**（导入即 RuntimeError），不是「红一条」那么轻。
#: ② 反过来把两类终点并成一个集合，正是 CM-P-26 要消灭的口径糊位——
#:   「所有内容走中央调度层」≠「所有内容走出站防风暴闸」：闸只管**无入站事件**的
#:   主动投递，事件/命令回复的治理住在 `_prepare`。两册各判各的终点，谁也不替谁背书。
#: 本册只干一件事：**把这两枚既有旁路搬进门的视野**（登记面 ⊇ 执法面），零行为变更。
#: 基线＝今日现算实测（S84 于 2026-09-24 复算：两枚都在树里、都含 `call_api` 直发 sink）。
#: 方向锁同枚二：**只准降不准升**——它是「已扫到的既有旁路」名册，
#: **不是**「允许存在的旁路上限」；两者的区别见 `test_event_direct_bypass_roster_is_live`。
_EVENT_DIRECT_BYPASS_ROSTER: frozenset[str] = frozenset()  # 2026-09-24 裁定 R-4：两枚已收编，名册摘牌
#: 已登记为**欠账**的旁路（看得见、只能减）。往这里塞一枚树里其实不直发的名字，
#: 就是「把旁路数量抬进上限于是它不再是违反」那件事——本件的活性锁当场红。
_EVENT_DIRECT_BYPASS_BASELINE: frozenset[str] = frozenset()  # 欠账归零：由下面的零容忍门接管，不再棘轮
#: 事件/命令回复的合法终点（**只**服务本册，绝不回喂 `_CENTRAL_TERMINALS`）。
_LEGAL_FUNNEL_TERMINALS = frozenset({"_run_capability_through_pipeline"}) | _CENTRAL_TERMINALS

#: 全树扫描锁（S75 那把眼）的件与它的两本字面量账——枚五据此对账，零复制扫描器。
_TEETH_LOCK_PY = _TESTS_DIR / "test_active_push_entry_teeth.py"
#: 欠账册（"仍有旁路"的如实记账；今天已降为空，空册只允许是空册）。
_TEETH_BASELINE_NAME = "_DIRECT_SEND_BYPASS_BASELINE"
#: 通道本体豁免册（非投递、无排队通道的 mutating 直发；枚五据它反查"豁免没被用来藏旁路"）。
_TEETH_CHANNEL_BODY_NAME = "_CHANNEL_BODY_SITES"
#: 那把尺的分族名单名——枚五按名现读再并，防它哪天偷偷加第三族而不告诉本件。
_TEETH_API_FAMILY_NAMES = ("_BYPASS_APIS_MESSAGE", "_BYPASS_APIS_FILE_MUTATION")
#: 那把尺的扫描排除面（叶子发送器/冒烟/登记表）——枚六的动态名普查**复用地同一本**，
#: 按名 AST 现读；两把尺各用各的排除面＝盲区可以整片搬家不进门（CM-P-26 同族）。
_TEETH_EXCLUDE_PARTS_NAME = "_SCAN_EXCLUDE_PARTS"
_PLUGINS_DIR = _REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 枚六·动态名豁免册（**不是**欠账册，也不与齿锁 `_CHANNEL_BODY_SITES` 并册：那本记"字面可判、
#: 无排队通道的通道本体直发"，本册记"静态折不出 api 名的通道本体调用"——两册判的是两种形态）。
#: 键 =（相对路径, 函数名, 被调体形态, 首参源码形[:80]）。
#: 现算依据（2026-09-24T07:5xZ，尺身份：本件 `_scan_call_api_sites` 全生产树，排除面同齿锁）：
#: 全树动态名恰此两枚；在册却扫不到＝假豁免（活性反查），扫到而不在册＝违反（零容忍）。
_DYNAMIC_BOUNDED_SITES: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        (
            "plugins/bot_unified_runtime/control_plane/dispatcher.py",
            "execute",
            "attribute",
            "method",
        ),
        (
            "plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py",
            "call",
            "attribute",
            "action",
        ),
        (
            # 2026-09-27 S-PERSONA-WIRE 收编（人格热切换根装配腿）：适配器形参，
            # 唯一来源＝persona_profile.apply_persona_profile 通道本体内两枚字面
            # set_qq_profile/set_qq_avatar，枚举封闭在册、不许拼名（判据同上两枚）。
            "plugins/bot_unified_runtime/__init__.py",
            "_dispatch_persona_appearance_if_switched",
            "attribute",
            "action",
        ),
    }
)


def _teeth_literal_call(tree: ast.AST, var_name: str) -> ast.Call:
    """定位扫描尺件里某个模块级字面量绑定（`X = frozenset(...)` 或 `X: T = frozenset(...)`）。

    两种赋值形态都要认：那本账一旦加类型标注（`frozenset[str] = frozenset()`）仍是字面量绑定，
    只认 `ast.Assign` 会把取数口自己读瞎——本席实测踩过一次（三枚用例当场 RuntimeError）。
    """
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.expr):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == var_name for t in targets):
            continue
        assert (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"frozenset", "set"}
        ), (
            f"`{var_name}` 不再是 `frozenset(...)` 字面量＝取数口搬家"
            "（改成派生表达式＝那本账自己给自己抬上限），须重判本锁"
        )
        return value
    raise RuntimeError(f"在 `{_TEETH_LOCK_PY.name}` 里找不到 `{var_name}`＝取数口搬家，本锁须重判")


def _teeth_literal_string_set(tree: ast.AST, var_name: str) -> set[str]:
    """现读扫描尺件里的 `frozenset({...})` / `frozenset()` 字面量字符串集合（只读，不 import）。"""
    value = _teeth_literal_call(tree, var_name)
    if not value.args:
        return set()  # `frozenset()`：空册是合法值，但只允许"真空"，不允许派生
    (arg,) = value.args
    assert isinstance(arg, ast.Set), (
        f"`{var_name}` 的参数不是集合字面量（裸花括号会被读成空 dict＝账目失踪）：{ast.unparse(arg)}"
    )
    names: set[str] = set()
    for item in arg.elts:
        assert isinstance(item, ast.Constant) and isinstance(item.value, str), (
            f"`{var_name}` 出现非字符串量：{ast.unparse(item)}"
        )
        names.add(item.value)
    return names


def _teeth_literal_triples(tree: ast.AST, var_name: str) -> set[tuple[str, str, str]]:
    """现读扫描尺件里的 `frozenset({(file, func, api), ...})` / `frozenset()` 三元组账。"""
    value = _teeth_literal_call(tree, var_name)
    if not value.args:
        return set()
    (arg,) = value.args
    assert isinstance(arg, ast.Set), (
        f"`{var_name}` 的参数不是集合字面量：{ast.unparse(arg)}"
    )
    sites: set[tuple[str, str, str]] = set()
    for item in arg.elts:
        assert isinstance(item, ast.Tuple) and len(item.elts) == 3, (
            f"`{var_name}` 出现非三元组条目：{ast.unparse(item)}"
        )
        parts: list[str] = []
        for cell in item.elts:
            assert isinstance(cell, ast.Constant) and isinstance(cell.value, str), (
                f"`{var_name}` 条目含非字符串量：{ast.unparse(cell)}"
            )
            parts.append(cell.value)
        sites.add((parts[0], parts[1], parts[2]))
    return sites


# --------------------------------------------------------------------------- AST 工具
def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _own_nodes(scope: ast.AST):
    """函数**自己**的节点，不下钻进内层函数（canary 同款隔离：
    外层装配函数不得"看见"内层 handler 的 sink，否则整片假阳性）。"""
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _call_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _funcs(tree: ast.AST) -> dict[str, list[ast.AST]]:
    table: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            table.setdefault(node.name, []).append(node)
    return table


# --------------------------------------------------------------- 枚六·取数口（S182 扩，S168 §3 授权）
#: 一个作用域帧的静态可见绑定：(字符串常量表, call_api 通道别名, 形参名, 歧义/非字符串绑定名)。
_Bindings = tuple[dict[str, str], set[str], set[str], set[str]]
_ResolvedTriple = tuple[str, str, str]  # (相对路径, 函数名, api)
_DynamicQuad = tuple[str, str, str, str]  # (相对路径, 函数名, 被调体形态, 首参源码形)


def _is_api_channel_value(value: ast.expr) -> bool:
    """值本身是否「call_api 通道」：属性 `X.call_api` 或 `getattr(X, "call_api", …)`（同齿锁形态）。"""
    if isinstance(value, ast.Attribute) and value.attr == "call_api":
        return True
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "getattr"
        and len(value.args) >= 2
        and isinstance(value.args[1], ast.Constant)
        and value.args[1].value == "call_api"
    )


def _collect_scope_bindings(scope: ast.AST) -> _Bindings:
    """扫一个作用域**自身**（不下钻函数/lambda；类体另起弃帧）的四种可见性。

    与齿锁同名件的两处**判据差**（=齿锁现存渗漏，本批只在**本件**修，齿锁件禁动）：
    ① 类体绑定进弃帧——Python 里类作用域对方法不可见，齿锁把它并进模块帧导致
      「方法内歧义名 穿透折成类属性字面量」的错折（dispatcher `method: str = ""` 实证）；
    ② 折叠查找逐帧先查 consts、再查 params∪ambiguous——名字被形参或任何非字符串/歧义
      局部绑定遮蔽即**停折**，齿锁漏查 ambiguous 集才会穿透外帧。
    """
    consts: dict[str, str] = {}
    aliases: set[str] = set()
    params: set[str] = set()
    ambiguous: set[str] = set()

    def _bind(name: str, value: ast.expr) -> None:
        if _is_api_channel_value(value):
            aliases.add(name)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if name in consts or name in ambiguous:
                ambiguous.add(name)
                consts.pop(name, None)
            else:
                consts[name] = value.value
        else:
            ambiguous.add(name)
            consts.pop(name, None)

    def _walk(node: ast.AST, in_class_body: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue  # 嵌套作用域另算，不并入本级可见性
            if isinstance(child, ast.ClassDef):
                # 类体绑定只属于类体（方法装饰器/默认值可见），绝不进模块帧，也不进方法帧。
                _walk(child, True)
                continue
            if isinstance(child, ast.Assign) and not in_class_body:
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name):
                        _bind(tgt.id, child.value)
            elif (
                isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
                and child.value is not None
                and not in_class_body
            ):
                _bind(child.target.id, child.value)
            _walk(child, in_class_body)

    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        argz = scope.args
        params = {a.arg for a in [*argz.posonlyargs, *argz.args, *argz.kwonlyargs]}
        if argz.vararg:
            params.add(argz.vararg.arg)
        if argz.kwarg:
            params.add(argz.kwarg.arg)
    _walk(scope, False)
    return consts, aliases, params, ambiguous


def _scan_call_api_sites(source: str, relpath: str) -> tuple[set[_ResolvedTriple], set[_DynamicQuad]]:
    """静态解析单源里所有 call_api 通道调用 →（可判定的旁路三元组, 不可判定的动态名四元组）。

    三被调体：① `X.call_api(…)` ② `getattr(X,"call_api")(…)` ③ 别名 `c = X.call_api / getattr(…)` 后 `c(…)`。
    首参：字面量字符串直接判；Name 逐帧（内→外）折叠「同帧唯一字符串赋值」；形参/歧义/计算值/
    裸 `*args`/查无绑定 ⇒ **不猜值，点名入账**（这就是与齿锁「保守放过」的口径差——齿锁对动态名
    失明由它自己那本账负责，本件的投递域判据 fail-closed：折不出＝直发嫌疑）。
    **折叠失败＝折不出合法 api 名**（S189 补：形参/歧义/计算值/查无绑定，以及折成**空串/纯空白**——
    空串不是任何 OneBot 动作名）一律进 dynamic 点名，绝不静默丢弃；只有折出 strip 后非空的 api 名
    才算一次成功判定（详见 `_visit` 内折叠失败判据与 `test_fold_failure_never_silently_drops`）。
    无位置实参的调用（`bot.call_api(**kw)`）不计：没有 api 名位就不可能是一次投递。
    """
    tree = ast.parse(source)
    stack: list[_Bindings] = [_collect_scope_bindings(tree)]
    resolved: set[_ResolvedTriple] = set()
    dynamic: set[_DynamicQuad] = set()

    def _callee_form(call: ast.Call) -> str | None:
        fn = call.func
        if isinstance(fn, ast.Attribute) and fn.attr == "call_api":
            return "attribute"
        if _is_api_channel_value(fn):
            return "getattr"
        if isinstance(fn, ast.Name) and any(fn.id in aliases for (_c, aliases, _p, _a) in stack):
            return "alias"
        return None

    def _resolve_api(call: ast.Call) -> str | None:
        if not call.args:
            return None
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        if isinstance(first, ast.Name):
            for consts, _aliases, params, ambiguous in reversed(stack):  # 内层优先
                if first.id in consts:
                    return consts[first.id]
                if first.id in params or first.id in ambiguous:
                    return None  # 被形参/非字符串局部绑定遮蔽＝外帧同名常量不可代入
            return None  # 名字静态无绑定＝动态名
        return None  # 计算值 / Starred 等

    def _visit(node: ast.AST, func_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = func_name
            pushed = False
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                stack.append(_collect_scope_bindings(child))
                inner = child.name
                pushed = True
            if isinstance(child, ast.Call):
                form = _callee_form(child)
                if form is not None:
                    if not child.args:
                        pass  # 无 api 名位，不构成投递（判定边界，牙7 锁死）
                    else:
                        api = _resolve_api(child)
                        # 折叠失败判据（S189 补，闭「静默 `''` 丢弃」第四态，同 S182 §齿漏点名之洞）：
                        # 只有折出**合法 api 名**（非 None 且 strip 后非空）才算一次成功判定；
                        # 空串/纯空白不是任何 OneBot 动作名，把它当"可判定的非旁路 api"就地放过＝
                        # 既不进 resolved、也不进 dynamic＝第四态静默消失（"看起来管住了"实际是漏）。
                        # 保守方向锁死：折叠失败（含折成空串）一律按「可疑」点名入账（宁滥勿漏），
                        # 绝不放宽成"看着不像 send 就不算"；本改动只把 dynamic 变大、绝不让
                        # resolved 或 dynamic 缩小（只扩不缩，`test_scan_surface_only_grows_never_shrinks` 执法）。
                        if api is not None and api.strip():
                            if api in _BYPASS_APIS:
                                resolved.add((relpath, func_name, api))
                        else:
                            dynamic.add((relpath, func_name, form, ast.unparse(child.args[0])[:80]))
                _visit(child, inner)
            else:
                _visit(child, inner)
            if pushed:
                stack.pop()

    _visit(tree, "<module>")
    return resolved, dynamic


def _legacy_literal_triples(source: str, relpath: str) -> set[_ResolvedTriple]:
    """改造前旧取数口（只认 `.call_api("<字面量>")`，同齿锁 `_legacy_literal_scan`）——
    专供「只扩不缩」对照锁：真树上 旧 ⊆ 新 必须成立，合成源上新须为严格超集。"""
    tree = ast.parse(source)
    found: set[_ResolvedTriple] = set()

    def _visit(node: ast.AST, func_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = func_name
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "call_api"
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[0].value, str)
                and child.args[0].value in _BYPASS_APIS
            ):
                found.add((relpath, func_name, str(child.args[0].value)))
            _visit(child, inner)

    _visit(tree, "<module>")
    return found


def _names_with_bypass_or_dynamic(source: str, names: AbstractSet[str]) -> set[str]:
    """注毒公用口：喂合成/被注毒源码，返回 `names` 里**确有**直发 sink（字面/折叠/动态名任一）者。

    动态名也计＝投递域判据 fail-closed：折不出 api 名恰恰是「想躲开字面量尺」的形态。
    """
    resolved, dynamic = _scan_call_api_sites(source, "<synthetic>")
    hit = {func for (_f, func, _api) in resolved} | {func for (_f, func, _form, _arg) in dynamic}
    return {name for name in names if name in hit}


def _direct_callees(fn: ast.AST) -> set[str]:
    return {name for node in _own_nodes(fn) if isinstance(node, ast.Call) if (name := _call_name(node))}


def _build_call_edges(tree: ast.AST) -> dict[str, set[str]]:
    """函数名 → 其自身直接调用的名字集合（多定义并集；沿此图做传递可达）。"""
    edges: dict[str, set[str]] = {}
    for name, defs in _funcs(tree).items():
        acc = edges.setdefault(name, set())
        for node in defs:
            acc |= _direct_callees(node)
    return edges


def _reaches_central(
    fn_name: str, edges: dict[str, set[str]], guard: int = 100
) -> bool:
    """传递可达中央出口（`submit_active_push` / `_push_via_central_exit_now`）。"""
    seen: set[str] = set()
    queue = deque([fn_name])
    steps = 0
    while queue and steps < guard:
        steps += 1
        cur = queue.popleft()
        if cur in _CENTRAL_TERMINALS:
            return True
        for callee in edges.get(cur, set()):
            if callee in _CENTRAL_TERMINALS:
                return True
            if callee not in seen and callee in edges:
                seen.add(callee)
                queue.append(callee)
    return False


def _sink_reachable(fn_name: str, edges: dict[str, set[str]]) -> bool:
    """反幻影：该入口的传递闭包里确有**任一**中央出口（证它真的在投递，而非空函数名）。"""
    return _reaches_central(fn_name, edges)


# --------------------------------------------------------------------------- 现算（采集体）
_ROOT_TREE = ast.parse(_read(_ROOT_INIT))
_PUSH_TREE = ast.parse(_read(_PUSH_PY))
_PIPELINE_TREE = ast.parse(_read(_PIPELINE_PY))
_ROOT_EDGES = _build_call_edges(_ROOT_TREE)
_PUSH_EDGES = _build_call_edges(_PUSH_TREE)
_EDGE_TABLES = (_ROOT_EDGES, _PUSH_EDGES)
_ALL_FUNCS: dict[str, list[ast.AST]] = {}
for _t in (_ROOT_TREE, _PUSH_TREE):
    for _n, _defs in _funcs(_t).items():
        _ALL_FUNCS.setdefault(_n, []).extend(_defs)


def _build_site_index(paths: tuple[pathlib.Path, ...]) -> set[str]:
    """管辖件（根/紧急 push/pipeline 三件投递域）里含**直发 sink 或动态名调用**的函数名集。

    口径 = 枚六取数口全形态（字面 ∪ 折叠 ∪ 动态名）。动态名计入 ⇒ 枚二/枚四对「首参不是字面量」
    的 `call_api` 同样当场红——投递域 fail-closed，不猜值。今天真树上该集对动态名为**空**
    （全树动态名只有豁免册那两枚，都不在这三个文件），故两棘轮实测集合与改版前逐枚相等。
    """
    hit: set[str] = set()
    for path in paths:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        resolved, dynamic = _scan_call_api_sites(_read(path), rel)
        hit |= {func for (_f, func, _api) in resolved}
        hit |= {func for (_f, func, _form, _arg) in dynamic}
    return hit


_DELIVER_BYPASS_FUNCS: frozenset[str] = frozenset(_build_site_index((_ROOT_INIT, _PUSH_PY, _PIPELINE_PY)))


def _has_bypass(fn_name: str) -> bool:
    return fn_name in _DELIVER_BYPASS_FUNCS


def _reaches_central_any(fn_name: str) -> bool:
    return any(_reaches_central(fn_name, edges) for edges in _EDGE_TABLES)


def measured_active_push_bypass() -> set[str]:
    """枚二口径：主动投递入口名单里，含旁路直发 sink 的那些（今日未全汇缝者）。"""
    return {name for name in _ACTIVE_PUSH_ROSTER if _has_bypass(name)}


# 采集体非空转守卫：任一 roster 成员若在树里根本不存在或压根不投递 ⇒ 立即响亮炸。
_MISSING = [name for name in _ACTIVE_PUSH_ROSTER if name not in _ALL_FUNCS]
if _MISSING:
    raise RuntimeError(f"主动投递入口名单在册却找不到定义（改名/搬家）：{sorted(_MISSING)}")
_PHANTOM = [name for name in _ACTIVE_PUSH_ROSTER if not _reaches_central_any(name)]
if _PHANTOM:
    raise RuntimeError(
        f"这些主动投递入口在树里已不抵达任何出站出口＝判据对真树失明（假绿的根）：{sorted(_PHANTOM)}"
    )


def _reaches_any_legal_sink(fn_name: str) -> bool:
    """事件/命令回复的反幻影尺：抵达中央出口**或**管线汇口都算「真在投递」。

    与 `_reaches_central_any` 的分工是本波要害：管线汇口对主动投递族**不算**数
    （那正是「唯一出口」这句话的执法面），对事件回复族才算数（它本就不该走闸）。
    两把尺各自成立，才允许两份名册各自降账。
    """
    seen: set[str] = set()
    queue = deque([fn_name])
    steps = 0
    while queue and steps < 100:
        steps += 1
        cur = queue.popleft()
        if cur in _LEGAL_FUNNEL_TERMINALS:
            return True
        for edges in _EDGE_TABLES:
            for callee in edges.get(cur, set()):
                if callee in _LEGAL_FUNNEL_TERMINALS:
                    return True
                if callee not in seen and callee in edges:
                    seen.add(callee)
                    queue.append(callee)
    return False


_EVENT_MISSING = [name for name in _EVENT_DIRECT_BYPASS_ROSTER if name not in _ALL_FUNCS]
if _EVENT_MISSING:
    raise RuntimeError(f"事件/命令直发名单在册却找不到定义（改名/搬家）：{sorted(_EVENT_MISSING)}")
_EVENT_PHANTOM = [
    name for name in _EVENT_DIRECT_BYPASS_ROSTER if not _reaches_any_legal_sink(name)
]
if _EVENT_PHANTOM:
    raise RuntimeError(
        "这些事件/命令入口既不抵达中央出口、也不抵达管线汇口＝本册判据对真树失明："
        f"{sorted(_EVENT_PHANTOM)}"
    )
_EVENT_NO_BYPASS = [name for name in _EVENT_DIRECT_BYPASS_ROSTER if not _has_bypass(name)]
if _EVENT_NO_BYPASS:
    raise RuntimeError(
        "事件/命令名册里这些成员已**不含**直发 sink（大概率已被收编）："
        f"{sorted(_EVENT_NO_BYPASS)}＝请把名册与欠账基线**同时**摘牌降账。"
        "不许只删基线、留名册假空转；更不许反过来把新长出的旁路塞进基线。"
    )




def registered_bypass_functions() -> set[str]:
    """本件两份**欠账基线**承认的旁路函数名（现算并集；两册今天都已降为空）。"""
    return set(_ACTIVE_PUSH_BYPASS_BASELINE) | set(_EVENT_DIRECT_BYPASS_BASELINE)


def scanned_registered_names() -> set[str]:
    """扫描尺（R3）欠账名册的函数名投影（现算；枚五两半边共用同一把尺）。"""
    return {func for (_file, func, _api) in _teeth_registered_direct_send_sites()}


def _teeth_tree() -> ast.AST:
    return ast.parse(_read(_TEETH_LOCK_PY))


def _teeth_registered_direct_send_sites() -> set[tuple[str, str, str]]:
    """现读 S75 全树扫描锁**欠账名册**（AST 取字面量，零 import、零复制扫描器）。

    两把尺的连通件之一：那把扫全树、这把管名册，两边的欠账必须逐枚对得上——
    「登记面窄于执法面」（CM-P-26 的成因）因此不可能再静默发生。
    """
    return _teeth_literal_triples(_teeth_tree(), _TEETH_BASELINE_NAME)


def teeth_channel_body_sites() -> set[tuple[str, str, str]]:
    """现读扫描尺件的**通道本体豁免册**（upload/delete 族扩尺后唯一的"看得见但不算欠账"面）。"""
    return _teeth_literal_triples(_teeth_tree(), _TEETH_CHANNEL_BODY_NAME)


def teeth_api_families() -> dict[str, set[str]]:
    """现读扫描尺件的分族名单（按名逐族）。枚五按**族**比对，不只比并集——
    只扩并集不扩分族（或反之）都会在这里露馅。"""
    tree = _teeth_tree()
    families = {name: _teeth_literal_string_set(tree, name) for name in _TEETH_API_FAMILY_NAMES}
    assert all(families.values()), "扫描尺的分族名单里有空族＝那把尺的 sink 面塌了，本锁须重判"
    return families


def teeth_bypass_api_family() -> set[str]:
    """扫描尺完整 sink 名单（各族并集）。"""
    return set().union(*teeth_api_families().values())


def _teeth_exclude_parts() -> tuple[str, ...]:
    """AST 现读齿锁的扫描排除面 `_SCAN_EXCLUDE_PARTS`（枚六普查复用地面，两尺不许各扫各的）。

    取数口搬家（改名/换形态）⇒ 响亮报错，绝不静默回退到硬编码副本——排除面悄悄分家
    与「登记面窄于执法面」是同一种瞎。
    """
    tree = _teeth_tree()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.expr):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == _TEETH_EXCLUDE_PARTS_NAME for t in targets):
            continue
        assert isinstance(value, ast.Tuple), (
            f"`{_TEETH_EXCLUDE_PARTS_NAME}` 不再是元组字面量＝齿锁排除面搬家，枚六普查须同批复判"
        )
        parts: list[str] = []
        for item in value.elts:
            assert isinstance(item, ast.Constant) and isinstance(item.value, str), (
                f"`{_TEETH_EXCLUDE_PARTS_NAME}` 含非字符串条目：{ast.unparse(item)}"
            )
            parts.append(str(item.value))
        return tuple(parts)
    raise RuntimeError(f"在 `{_TEETH_LOCK_PY.name}` 里找不到 `{_TEETH_EXCLUDE_PARTS_NAME}`＝排除面搬家，本锁须重判")


_CENSUS_CACHE: tuple[set[_ResolvedTriple], set[_DynamicQuad], set[_ResolvedTriple]] | None = None


def _production_census() -> tuple[set[_ResolvedTriple], set[_DynamicQuad], set[_ResolvedTriple]]:
    """全生产树现算（惰性一次，排除面=齿锁同一本）：(枚六可判旁路, 动态名四元组, 旧尺三元组)。"""
    global _CENSUS_CACHE
    if _CENSUS_CACHE is None:
        excludes = _teeth_exclude_parts()
        resolved: set[_ResolvedTriple] = set()
        dynamic: set[_DynamicQuad] = set()
        legacy: set[_ResolvedTriple] = set()
        for path in sorted(_PLUGINS_DIR.rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if any(part in rel for part in excludes):
                continue
            source = path.read_text(encoding="utf-8")
            r, d = _scan_call_api_sites(source, rel)
            resolved |= r
            dynamic |= d
            legacy |= _legacy_literal_triples(source, rel)
        _CENSUS_CACHE = (resolved, dynamic, legacy)
    return _CENSUS_CACHE


def coverage_gaps(scanned: set[str], registered: set[str]) -> tuple[list[str], list[str]]:
    """纯函数形式的对账口（同一把尺喂真数据与喂合成数据，注毒才不测夹具）。"""
    return sorted(scanned - registered), sorted(registered - scanned)


def _check_ratchet(measured: AbstractSet[str], baseline: AbstractSet[str]) -> list[str]:
    """只准降不准升：新长出的旁路入口（measured − baseline）逐枚点名。
    措辞族中性：投递族＝绕过唯一出口；upload/delete 族＝绕过统一管线的第二条 mutating 路。"""
    return [
        f"{name} 长出/新增了绕过中央出口/统一管口的 mutating 直发 sink（send∪upload/delete 族）"
        "＝汇缝账回潮，须先收进唯一出口再谈降账"
        for name in sorted(measured - baseline)
    ]


# =========================================================================== 枚一：入口集合枚举锁（全绿，证扫描面）
def test_active_push_entry_set_is_scanned_not_phantom() -> None:
    """枚一（主动投递形）：名单每一员都在树里、且传递可达中央出口（反幻影）；
    且扫描面对得上当年那批双分支/多入口调度族（防"整片看不见"的粗判据）。"""
    must_watch = {
        "_deliver_due_reminders",
        "_push_daily_group_digests",
        "_push_daily_assist_private",
        "_cookie_expiry_reminder_job",
        "deliver_emergency",
    }
    assert must_watch <= set(_ACTIVE_PUSH_ROSTER), f"扫描面丢了当年调度族：{sorted(must_watch - set(_ACTIVE_PUSH_ROSTER))}"
    for name in _ACTIVE_PUSH_ROSTER:
        assert name in _ALL_FUNCS, f"{name} 不在册却列进名单＝本锁参数写歪"
        assert _reaches_central_any(name), f"{name} 未抵达任何中央出口＝幻影入口，名单须重判"
    # 塌陷锁（2026-09-24 改版）：名单非空 + 直发尺对**真树**仍可见。今天全树唯一那条 mutating
    # 直发＝扫描尺通道本体豁免册里的 `delete_msg`（`_handle_dirty_guard`），它只有靠 upload/delete
    # 族扩尺才扫得到 ⇒ 这条同时是"扩尺接上了真树"的证人。旧写法「实测必须还有欠账」已作废：
    # 欠账降为零之后再拿"还有欠账"当尺没瞎的证据，就是逼后人留一条真旁路来喂绿。
    assert len(_ACTIVE_PUSH_ROSTER) >= 4
    body_funcs = {func for (_f, func, _api) in teeth_channel_body_sites()}
    assert body_funcs, "扫描尺的通道本体豁免册为空＝upload/delete 族的可见性没了证人，本锁须重判"
    for name in sorted(body_funcs):
        assert name in _ALL_FUNCS, f"{name} 在豁免册却不在树里＝改名/搬家，两把尺都要重判"
        assert _has_bypass(name), f"{name} 今天已不直发＝豁免册过期（假豁免），与扫描尺同批复判"


def test_ack_entry_is_scanned_and_wired_to_the_central_exit() -> None:
    """枚一（语音回执形）：回执投递口 `_submit_progress_ack` 在册、且只经唯一出口；
    装配链（根把 `progress_ack_submit` 接到它、pipeline 用注入件而非裸 submit）逐项现读。"""
    # (1) 根装配：有 `progress_ack_submit = _submit_progress_ack` 这条赋值。
    wired = any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "progress_ack_submit" for t in node.targets
        )
        and isinstance(node.value, ast.Name)
        and node.value.id == "_submit_progress_ack"
        for node in ast.walk(_ROOT_TREE)
    )
    assert wired, "根没把 progress_ack_submit 接到 `_submit_progress_ack`＝回执投递口被换掉或摘掉"
    # (2) RuntimePipeline(...) 的 kwarg progress_ack_submit= 指向那个局部名。
    ctor_kwargs: dict[str, ast.expr] = {}
    for node in ast.walk(_ROOT_TREE):
        if isinstance(node, ast.Call) and _call_name(node) == "RuntimePipeline":
            for kw in node.keywords:
                if kw.arg:
                    ctor_kwargs[kw.arg] = kw.value
    given = ctor_kwargs.get("progress_ack_submit")
    assert isinstance(given, ast.Name) and given.id == "progress_ack_submit", (
        f"RuntimePipeline(progress_ack_submit=…) 不再交那个局部名：{ast.dump(given) if given else None}"
    )
    # (3) `_submit_progress_ack` 只经唯一出口、且无旁路直发。
    assert _reaches_central_any("_submit_progress_ack"), "回执投递口不抵达 submit_active_push＝回执绕闸"
    assert not _has_bypass("_submit_progress_ack"), "回执投递口长出 call_api 直发＝绕过唯一出口"


# =========================================================================== 枚二：主动投递形·零容忍门（2026-09-24 降账之后）
def test_active_push_convergence_ratchet() -> None:
    """枚二（主动投递形）：**零容忍**——名单内任何一员长出 `call_api` mutating 直发即违反。

    历史账（保留在此，别叙述成"一直如此"）：本枚 2026-09-21 立时是"只降不升"的棘轮，
    基线 `{_cookie_expiry_reminder_job}`＝当日实测未汇缝名单；2026-09-24 裁定 R-4 删掉那条
    `via_queue` 缺省关直发分支后，实测集合降为**空**。空基线继续当棘轮＝"名册为空所以全绿"的
    空跑（R-新1 点名禁止），故改判成硬尺：今天起长出任何一条主动投递直发，本门当场红。
    sink 名单 2026-09-24 起含 upload/delete 族 ⇒ 用文件上传/撤回绕唯一出口同样算违反。
    """
    measured = measured_active_push_bypass()
    assert measured == set(_ACTIVE_PUSH_BYPASS_BASELINE), (
        f"实测带直发的主动投递入口 {sorted(measured)} ≠ 在册基线 {sorted(_ACTIVE_PUSH_BYPASS_BASELINE)}。"
        "基线今天是空册：要么有人新造了旁路（须先收进唯一出口），要么名单成员本身变了（那要重判本枚）。"
    )
    violations = _check_ratchet(measured, _ACTIVE_PUSH_BYPASS_BASELINE)
    assert not violations, "；".join(violations)


def test_active_push_ratchet_has_teeth() -> None:
    """注毒（内存源码 + 合成入口，绝不碰真树）：
    (A) 新造一条绕过唯一出口的直发 ⇒ 零容忍门必报违反（send 族与 upload/delete 族各一发）；
    (B) 收编后的干净现状（measured 空）必须被放行——降账这条路不能被写反。"""
    for extra_api in ("send_private_msg", "upload_group_file", "delete_msg"):
        extra = f"""


def _poison_active_push_entry():
    bot.call_api("{extra_api}", group_id=1, message=[])
"""
        poisoned_source = _read(_ROOT_INIT) + extra
        bypass = _names_with_bypass_or_dynamic(poisoned_source, _ACTIVE_PUSH_ROSTER | {"_poison_active_push_entry"})
        violations = _check_ratchet(bypass, _ACTIVE_PUSH_BYPASS_BASELINE)
        assert any("_poison_active_push_entry" in v for v in violations), (
            f"新造 {extra_api} 直发没被判为违反＝枚二零容忍门对这一族是空转：{violations}"
        )

    # —— (B) 干净现状（无 _poison）：measured ⊆ 空基线，且"未来摘基线"方向不被写反。
    clean_bypass = measured_active_push_bypass()
    assert not _check_ratchet(clean_bypass, _ACTIVE_PUSH_BYPASS_BASELINE), "干净现状本就该被零容忍门放行"
    shrunk = clean_bypass - {"_cookie_expiry_reminder_job"}
    assert not _check_ratchet(shrunk, _ACTIVE_PUSH_BYPASS_BASELINE), (
        "真正收编后（measured 变小）门反把降账判红＝方向写反，将来没人敢摘基线"
    )


# =========================================================================== 枚三：语音回执形·诚实绿收敛锁（带牙）
def test_ack_emits_only_through_injected_submit_not_direct_send() -> None:
    """回执形核心不变量：pipeline 的 `_emit_progress_ack` 只调**注入的** `submit(...)`，
    绝不裸调 `send_queue.submit` / 不 `call_api` 直发——投递治理唯一住在闸后。"""
    emit = next((n for n in _funcs(_PIPELINE_TREE).get("_emit_progress_ack", [])), None)
    assert emit is not None, "pipeline 里 `_emit_progress_ack` 不见了＝回执装配前提变了，须重判本锁"
    own = list(_own_nodes(emit))
    # 用了注入件（形如 `submit(request)`）。
    uses_injected = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "submit"
        for n in own
    )
    assert uses_injected, "回执落点不再调注入的 submit＝可能偷偷改成直发"
    # 没有裸 send_queue.submit / self.send_queue.submit。
    for n in own:
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "submit":
            base = n.func.value
            base_name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            assert base_name != "send_queue", "回执绕过注入件直调 send_queue.submit＝绕过唯一出口"
    # 没有 call_api 直发（字面/折叠/动态名任一形态都不许有——枚六 fail-closed 口径）。
    assert not _has_bypass("_emit_progress_ack"), "回执落点出现 call_api 通道调用（含折不出名的动态名）＝绕过闸"


def test_ack_convergence_lock_has_teeth() -> None:
    """注毒（合成，不碰真树）证明 `_reaches_central_any`/`_has_bypass` 这对尺真有牙：
    一个"只 submit_active_push、不直发"的合成件判为已汇缝；
    一个"只裸 send_queue.submit"的合成件判为未汇缝；一个"含 call_api 直发"的判为带旁路。"""
    good = """


def _good_exit():
    submit_active_push(send_queue, request, gate, dedupe_namespace="ack")


def _bad_direct():
    send_queue.submit(request)


def _bad_bypass():
    bot.call_api("send_private_msg", user_id=1, message=[])
"""
    tree = ast.parse(good)
    edges = _build_call_edges(tree)
    assert _reaches_central("_good_exit", edges) is True
    assert _reaches_central("_bad_direct", edges) is False, "裸 send_queue.submit 被误判为汇中央出口"
    assert _reaches_central("_bad_bypass", edges) is False
    assert "_bad_bypass" in _names_with_bypass_or_dynamic(good, {"_bad_bypass", "_good_exit"}), (
        "call_api 直发没被认成旁路 sink"
    )
    assert "_good_exit" not in _names_with_bypass_or_dynamic(good, {"_bad_bypass", "_good_exit"})
    # 与真实现对照：真正的回执投递口 `_submit_progress_ack` 落在"good"这一侧。
    assert _reaches_central_any("_submit_progress_ack") and not _has_bypass("_submit_progress_ack")


# =========================================================== 枚四：事件/命令直发·零容忍门（2026-09-24 裁定 R-4 之后）
def test_registered_bypass_ledgers_agree_across_the_two_locks() -> None:
    """枚五（两把尺的连通锁，2026-09-24 随降账 + 扩尺改版）：三腿全现算、零复制扫描器。

    ① **sink 名单逐枚相等**：那把尺认哪些 api 为直发，本件必须认同一批。只扩一侧＝
      一侧看得见、另一侧看不见，正是 CM-P-26「登记面窄于执法面」的成因，当场红。
    ② **欠账册双边同空**：扫描尺的欠账基线（AST 现读）与本件两份欠账基线必须同时对得上；
      今天两侧都是空册（真降账），谁单边塞名字进来即红。
    ③ **通道本体豁免册跨尺互认**：扫描尺豁免的每一枚（upload/delete 族的 by-design 直发），
      本件的尺必须也认它"今天真直发"，且它**既不是**主动投递名单成员、**也不抵达**任何合法汇口
      ——否则它就是"第二条路"，该收编而不是该豁免（豁免面不能变成藏旁路的抽屉）。
    """
    # ① sink 名单逐族、逐枚相等
    families = teeth_api_families()
    own = {
        "_BYPASS_APIS_MESSAGE": _BYPASS_APIS_MESSAGE,
        "_BYPASS_APIS_FILE_MUTATION": _BYPASS_APIS_FILE_MUTATION,
    }
    assert set(families) == set(own), (
        f"扫描尺的分族结构与本件不同构（{sorted(families)} vs {sorted(own)}）＝它加了/改了族名，"
        "本锁的取数口须重判，别让它静默少比对一族"
    )
    for name, ours in own.items():
        assert families[name] == ours, (
            f"sink 名单第 {name} 族漂移（扩了一侧没扩另一侧）："
            f"仅扫描尺认得={sorted(families[name] - ours)}；仅本件认得={sorted(ours - families[name])}"
        )
    assert teeth_bypass_api_family() == set(_BYPASS_APIS), "两把尺的 sink 并集漂移（分族都对上却并集不等＝写歪）"
    # ② 欠账册双边同空 + 逐枚互认（册若回潮，正/反向都要对得上）
    debt_scanned = _teeth_registered_direct_send_sites()
    assert not debt_scanned, (
        f"扫描尺的欠账册重新长出条目 {sorted(debt_scanned)}＝把旁路抬进上限；"
        "今天这一册的合法值是空集（新旁路要么收编、要么如实红）。"
    )
    assert not registered_bypass_functions(), (
        f"本件欠账基线重新长出条目 {sorted(registered_bypass_functions())}＝同上，不许单边塞账。"
    )
    blind, unmapped = coverage_gaps(
        {func for (_f, func, _a) in debt_scanned}, registered_bypass_functions()
    )
    assert not blind and not unmapped, (
        f"两本欠账账本漂移（正={blind} 反={unmapped}）：登记面窄于执法面＝门瞎，反之＝空记账。"
    )
    # ③ 通道本体豁免册跨尺互认
    for file_name, func_name, api in sorted(teeth_channel_body_sites()):
        assert api in _BYPASS_APIS, f"豁免册的 {api} 不在本件 sink 名单＝① 腿写漏，本锁须重判"
        assert func_name in _ALL_FUNCS, f"{func_name} 在豁免册却不在树里＝改名/搬家"
        assert _has_bypass(func_name), f"{func_name} 今天不直发＝假豁免，与扫描尺同批摘牌"
        assert func_name not in _ACTIVE_PUSH_ROSTER, (
            f"{func_name} 既是主动投递名单成员又被豁免＝两本账自相矛盾，须先收进唯一出口"
        )
        assert not _reaches_any_legal_sink(func_name), (
            f"{func_name} 既抵达统一管线/中央出口、又留着 mutating 直发＝第二条路（枚四口径），"
            "这种位置不配豁免，只配收编"
        )


def test_event_direct_bypass_locks_have_teeth() -> None:
    """注毒三发（全走内存串/合成集合，绝不碰真树与真件）：

    (A) 事件名单外新长一枚直发 ⇒ 枚四棘轮必判违反（拦「回潮」）；
    (B) 新旁路只被扫描尺登记、没进本件名册 ⇒ 连通锁必判门瞎；反向单边加账必红；
    (C) 把欠账名册抬成「允许」（塞一枚树里不直发的名字）⇒ 活性判据必拒（拦「抬基线造绿」）。
    """
    extra = """


def _poison_event_direct_entry():
    await bot.call_api("send_group_msg", group_id=1, message=[])
"""
    poisoned_source = _read(_ROOT_INIT) + extra
    bypass = _names_with_bypass_or_dynamic(poisoned_source, _EVENT_DIRECT_BYPASS_ROSTER | {"_poison_event_direct_entry"})
    assert "_poison_event_direct_entry" in bypass, "同一把尺没认到合成直发＝判据本身失效"
    violations = _check_ratchet(bypass, _EVENT_DIRECT_BYPASS_BASELINE)
    assert any("_poison_event_direct_entry" in v for v in violations), (
        f"枚四对新增事件旁路放行＝棘轮空转：{violations}"
    )

    widened = registered_bypass_functions() | {"_sneaky_event_entry"}
    blind, _unmapped = coverage_gaps(widened, registered_bypass_functions())
    assert blind == ["_sneaky_event_entry"], (
        f"扫描侧新增已登记旁路没被判成门瞎＝连通锁空跑：{blind}"
    )
    _blind2, unmapped2 = coverage_gaps(
        scanned_registered_names(), registered_bypass_functions() | {"_phantom_debt_entry"}
    )
    assert unmapped2 == ["_phantom_debt_entry"], (
        f"本件名册单方面多欠账没被点名＝连通锁单边失效：{unmapped2}"
    )

    inflated = set(_EVENT_DIRECT_BYPASS_BASELINE) | {"_push_daily_group_digests"}
    fake = [name for name in sorted(inflated) if not _has_bypass(name)]
    assert fake == ["_push_daily_group_digests"], (
        f"塞进「允许直发」的名字没被现算尺拒掉＝抬基线这条路没被拦住：{fake}"
    )

def test_event_and_command_entries_have_no_direct_send_bypass() -> None:
    """枚四（退役后形态）：**零容忍门**——事件/命令入口一律不许留 `call_api` 直发。

    2026-09-24 用户裁定「走管线，全部统一」：入群欢迎与 cookie 登录二维码两族的
    `call_api` 直发分支已从生产根删除、四个 `*_via_queue` 开关一并退役 ⇒ 这本欠账
    **不存在了**。账不存在，判据就不能退回"名册为空所以全绿"那种空跑（＝计数腿真空），
    也不能只是删掉用例（＝把红搬到另一本账）。所以换成一条扫真树的硬尺：

    * 扫的对象＝全树里**能抵达管线汇口或中央出口**的那些函数（事件/命令回复族）；
    * 判据＝它们**一律不得**含 `_scan_call_api_sites` 认得的直发 sink（字面/折叠/动态名全形态，
      枚六口径——折不出 api 名同样当场红）；
    * 反向自证：往根文本注一条 `call_api("send_group_msg", ...)`，同一把尺必须点名。

    也就是说：今天起长出任何一条新的事件直发，本门当场红，而不是"先记进名册再说"。
    """
    violations = sorted(
        name
        for name in sorted(_ALL_FUNCS)
        if _has_bypass(name) and _reaches_any_legal_sink(name)
    )
    assert not violations, (
        "这些事件/命令入口既经统一管线、又留着 `call_api` 直发＝第二条路（裁定 R-4 之后"
        "这是违反，不是欠账）：" + repr(violations)
    )
    # 自证尺没瞎（两半）：
    # ① 同一把直发尺对合成入口必须认得——否则上面的"零违反"只是尺看不见东西；
    poison = """


async def _poison_event_direct_entry_bypass():
    await bot.call_api("send_group_msg", group_id=1, message=[])
"""
    poisoned_source = _read(_ROOT_INIT) + poison
    name = "_poison_event_direct_entry_bypass"
    assert name in _funcs(ast.parse(poisoned_source)), "合成入口没进函数表＝夹具与尺脱节"
    assert name in _names_with_bypass_or_dynamic(poisoned_source, {name}), (
        "同一把尺认不到合成直发＝判据本身失效（上面那条'零违反'不作数）"
    )
    # ② 被收编的两枚今天仍必须**抵达管线汇口**——退役判据不许顺手把它们变成幻影。
    for retired in ("_handle_group_increase", "_handle_admin_cookie"):
        assert retired in _ALL_FUNCS, f"{retired} 不在树里＝收编把它删没了，须重判"
        assert not _has_bypass(retired), f"{retired} 仍含直发 sink＝上面的零违反判据漏了它"
        assert _reaches_any_legal_sink(retired), (
            f"{retired} 既不直发也不抵达任何合法汇口＝它已不再投递（收编做成了摘除，判据须重判）"
        )


# ========================================== 枚五（改版）自证：取数口与豁免面都有牙（S136，全合成）
def test_connectivity_and_exemption_legs_have_teeth() -> None:
    """(A) 取数口按**手写期望真值**钉死分族内容——它若搬家或被改成派生表达式，这里当场红；
    (B) 假豁免必被现算尺拒：拿一枚"在册但不直发"的合成条目验 ③ 腿的两个判据都成立（放行不了）；
    (C) "抵达合法汇口就不配豁免"这一半同样有牙：拿一枚确实抵达汇口的函数验它进不了豁免面；
    (D) 读数口对不存在的账名必须**响亮报错**，不许静默返回空集（空集＝"两侧都空所以相等"的假绿）。
    """
    # (A)
    families = teeth_api_families()
    assert families["_BYPASS_APIS_MESSAGE"] == {
        "send_private_msg",
        "send_group_msg",
        "send_msg",
    }, "扫描尺投递族名单漂移（本锁的期望真值须与两把尺同批复判）"
    assert families["_BYPASS_APIS_FILE_MUTATION"] == {
        "upload_group_file",
        "upload_private_file",
        "delete_msg",
    }, "扫描尺 upload/delete 族名单漂移（裁定 R-5 的口径被改，须同批改本锁与枚二期望值）"

    # (B) 假豁免：今天不直发的名字，两把尺都不认它是直发 ⇒ 塞进豁免册必被 ③ 腿点破。
    phantom_func = "_push_daily_group_digests"
    assert phantom_func in _ALL_FUNCS and not _has_bypass(phantom_func), (
        "假豁免样本自己变了形态＝本注毒空跑，须重挑样本"
    )
    assert all(func != phantom_func for (_f, func, _a) in teeth_channel_body_sites()), (
        "不直发的名字已在豁免册里＝③ 腿起手即假"
    )

    # (C) 抵达汇口的函数不配豁免：它抵达管线/中央出口，若被豁免就正好是"第二条路"那件事。
    funnel_func = "_submit_progress_ack"
    assert _reaches_any_legal_sink(funnel_func) and not _has_bypass(funnel_func), (
        "汇口样本形态变了＝本注毒空跑，须重挑样本"
    )

    # (D) 取数口不许静默失明。
    try:
        _teeth_literal_triples(_teeth_tree(), "_NO_SUCH_LEDGER_AT_ALL")
    except RuntimeError:
        pass
    else:  # pragma: no cover — 走不到就是失明
        raise AssertionError("读不到账名却静默返回空集＝取数口会失明，两侧都空就能互相糊成相等")


# ========================================== 枚六：动态名硬禁（S168 §3 裁定 → S182 落码，2026-09-24）
_DYNAMIC_DISPATCHER = (
    "plugins/bot_unified_runtime/control_plane/dispatcher.py",
    "execute",
    "attribute",
    "method",
)


def test_dynamic_name_census_is_zero_tolerance_outside_bounded_register() -> None:
    """全生产树动态名（call_api 通道调用而 api 名折不出）普查 **恰等于**豁免册，双向集合等式：

    * 册外新长一枚（任何非排除文件，含根/push/pipeline 自己）＝违反，零容忍、不棘轮——
      「首参非字面量即点名入账，不猜值」这条硬禁的执法面；
    * 在册却扫不到＝假豁免（通道搬家/收编没摘牌），同一判据当场点名。
    """
    _resolved, dynamic, _legacy = _production_census()
    assert dynamic == set(_DYNAMIC_BOUNDED_SITES), (
        "动态名普查漂移：少=豁免册过期（假豁免），多=新动态直发（须收编或重判，不许静默入账）。"
        f" 扫到未在册={sorted(dynamic - set(_DYNAMIC_BOUNDED_SITES))}；"
        f"在册未扫到={sorted(set(_DYNAMIC_BOUNDED_SITES) - dynamic)}"
    )


def test_dynamic_bounded_register_liveness_rejects_unmeasured_names() -> None:
    """注毒·反抬豁免（牙4）：拿"在册那枚今天其实不动态"的假想态复算活性判据 ⇒ 必被点名；
    再用「同名文件同名函数但函数体干净」的合成源证 判据原料（扫不到）真实可达。"""
    _resolved, dynamic, _legacy = _production_census()
    assert _DYNAMIC_DISPATCHER in dynamic, "在册豁免今天扫不到＝普查对真树失明或通道搬家，两账同批复判"
    without = dynamic - {_DYNAMIC_DISPATCHER}
    unbacked = set(_DYNAMIC_BOUNDED_SITES) - without
    assert unbacked == {_DYNAMIC_DISPATCHER}, (
        "豁免成员从真树消失没被活性判据点名＝假豁免可以永远挂着藏新旁路"
    )
    fake_src = (
        "class OutboundSideEffectExecutor:\n"
        "    method: str = ''\n\n"
        "    async def execute(self, intent):\n"
        "        return None\n"
    )
    _r, d = _scan_call_api_sites(fake_src, _DYNAMIC_DISPATCHER[0])
    assert d == set(), "「其实不动态」的合成样本自己没扫空＝本发注毒空跑"


def test_resolved_bypass_agrees_with_teeth_lock_across_rulers() -> None:
    """两把尺的**结论级**互认（枚五比的是账，这条比实测）：本件全树可判旁路 ==
    齿锁欠账册 ∪ 通道本体册 == 手写期望真值 {`_handle_dirty_guard`/`delete_msg`}。

    任何一侧取数口漂移（齿锁改族/改豁免、本件改折叠判据/改排除面）都会在这里露馅。
    期望真值手写（HARDEN-1 口径）：不许"现算抄回来的值"当基线。
    """
    resolved, _dynamic, _legacy = _production_census()
    truth = {("plugins/bot_unified_runtime/__init__.py", "_handle_dirty_guard", "delete_msg")}
    assert resolved == truth, (
        f"本件尺全树可判旁路偏离手写真值（多出={sorted(resolved - truth)} 缺失={sorted(truth - resolved)}）"
        "＝两把尺或真树之一变了，须同批复判两册与本锁"
    )
    assert resolved == _teeth_registered_direct_send_sites() | teeth_channel_body_sites(), (
        "本件全树实测 ≠ 齿锁两册之并＝两把尺各说各话（CM-P-26 同族，登记面与执法面分家）"
    )


def test_scan_surface_only_grows_never_shrinks() -> None:
    """只扩不缩硬锁两半：① 真树全生产文件 旧⊆新；② 合成混形态源 新为**严格**超集。"""
    resolved, dynamic, legacy = _production_census()
    assert legacy <= resolved, f"旧尺命中在新尺里丢了（缩面＝造绿）：{sorted(legacy - resolved)}"
    assert dynamic, "全树动态名一枚都扫不到＝新取数口没接上真树，『盲区已入账』是散文"
    mixed = (
        "API = 'send_msg'\n\n\n"
        "async def a():\n    await bot.call_api('send_group_msg', group_id=1)\n"
        "async def b():\n    m = 'upload_group_file'\n    await bot.call_api(m, group_id=2)\n"
        "async def c(u):\n    k = bot.call_api\n    await k('upload_private_file', user_id=u)\n"
        "async def d(nm):\n    await getattr(bot, 'call_api')(nm, x=1)\n"
        "async def e(nm2):\n    await bot.call_api(nm2, x=2)\n"
    )
    rel = "plugins/bot_unified_runtime/mixed_s182.py"
    r, dyn = _scan_call_api_sites(mixed, rel)
    l = _legacy_literal_triples(mixed, rel)
    assert l == {(rel, "a", "send_group_msg")}, "旧尺在合成源上的基线形态不对＝差分锁空跑"
    assert r == {
        (rel, "a", "send_group_msg"),
        (rel, "b", "upload_group_file"),
        (rel, "c", "upload_private_file"),
    }, f"字面/折叠/别名三形态未全认：{sorted(r)}"
    assert dyn == {(rel, "d", "getattr", "nm"), (rel, "e", "attribute", "nm2")}, (
        f"getattr直调/属性两枚动态名未入账：{sorted(dyn)}"
    )
    assert l <= r and (len(r) + len(dyn)) > len(l), "合成源上新尺不是严格超集＝扩尺没落地"


def test_dynamic_hard_ban_scan_has_teeth() -> None:
    """注毒多发达人（全合成源/内存，绝不碰真树）：

    牙1 折叠直发抓到且旧尺全瞎（差分=新能力）；牙2 别名动态名**入账不猜值**；
    牙3 齿锁渗漏复现——类体同名常量不得被穿透折叠（防"静默丢弃"与"凭空假阳"两个方向）；
    牙3b 外帧合法常量未被遮蔽时照常折（扩尺不误杀）；牙6 合成第三枚动态名必落**册外**；
    牙7 无位置实参不误报。
    """
    rel = "plugins/bot_unified_runtime/poison_s182.py"
    # 牙1 折叠
    fold_src = (
        "async def _sneak():\n"
        "    m = 'send_group_msg'\n"
        "    await bot.call_api(m, group_id=1, message=[])\n"
    )
    r1, d1 = _scan_call_api_sites(fold_src, rel)
    assert r1 == {(rel, "_sneak", "send_group_msg")} and d1 == set()
    assert _legacy_literal_triples(fold_src, rel) == set(), "旧尺也能抓折叠＝牙1 空跑"
    # 牙2 别名动态名：不猜值、点名入账
    alias_src = (
        "async def _sneak2(api_name, uid):\n"
        "    c = getattr(bot, 'call_api', None)\n"
        "    await c(api_name, user_id=uid)\n"
    )
    r2, d2 = _scan_call_api_sites(alias_src, rel)
    assert r2 == set(), "对动态名猜了值＝违『不猜值』教义"
    assert d2 == {(rel, "_sneak2", "alias", "api_name")}
    # 牙3 渗漏复现（dispatcher 形态）：类体 `method: str = ''` + 方法内歧义绑定。
    # 齿锁现判据会把 method 穿透折成 ''（非旁路 ⇒ 静默丢弃=盲区）；本尺必须点名入账。
    leak_src = (
        "class OutboundSideEffectExecutor:\n"
        "    method: str = ''\n\n"
        "    async def execute(self, intent):\n"
        "        method = self._resolve_method(intent)\n"
        "        await self.bot.call_api(method, x=1)\n"
    )
    r3, d3 = _scan_call_api_sites(leak_src, rel)
    assert r3 == set() and d3 == {(rel, "execute", "attribute", "method")}, (
        f"类作用域渗漏未修好：resolved={sorted(r3)} dynamic={sorted(d3)}"
    )
    # 牙3 渗漏危害面反向（group_info 形参形态的更险版本）：类体常量若恰是旁路名，
    # 穿透折叠会**凭空造阳**——把合法动态桥误判成旁路。本尺两条路都不走。
    leak2_src = (
        "class C:\n"
        "    action: str = 'send_group_msg'\n\n"
        "    async def run(self, dyn):\n"
        "        action = compute(dyn)\n"
        "        await bot.call_api(action, group_id=1)\n"
    )
    r3b, d3b = _scan_call_api_sites(leak2_src, rel)
    assert r3b == set(), "局部歧义名被穿透折成类体 'send_group_msg'＝凭空假阳（齿锁渗漏的另一半）"
    assert d3b == {(rel, "run", "attribute", "action")}
    # 牙3b 合法外帧折叠不误杀
    outer_src = (
        "API = 'upload_group_file'\n\n\nasync def _ok():\n    await bot.call_api(API, group_id=1)\n"
    )
    r4, d4 = _scan_call_api_sites(outer_src, rel)
    assert r4 == {(rel, "_ok", "upload_group_file")} and d4 == set(), "外帧唯一字符串常量不许折＝误杀折叠能力"
    # 牙6 第三枚动态名落册外＝普查门必红
    third_src = "async def _sneak3(api_name):\n    await bot.call_api(api_name, group_id=1)\n"
    _r6, d6 = _scan_call_api_sites(third_src, rel)
    assert d6 and d6 - set(_DYNAMIC_BOUNDED_SITES) == d6, "合成动态名被豁免册吞了＝豁免面成了藏人抽屉"
    # 牙7 无位置实参边界：没有 api 名位就不算投递
    noargs_src = "async def _kw(params):\n    await bot.call_api(**params)\n"
    r7, d7 = _scan_call_api_sites(noargs_src, rel)
    assert r7 == set() and d7 == set(), "call_api(**kw) 被算成直发＝误报扩面"


def test_fold_failure_never_silently_drops() -> None:
    """枚六折叠失败的第四态闭锁（S189）：折不出**合法 api 名**（形参/歧义/计算值/查无绑定，
    以及折成空串/纯空白）一律点名进 `dynamic`，绝不静默丢弃；保守方向不松、也不凭空造阳。
    全走内存合成源，绝不碰真树。

    三态归位（简报口径）：折出恰等 `_BYPASS_APIS` 者→①直发命中册（红）；折不出但落在
    `_DYNAMIC_BOUNDED_SITES`→②带理由+活性反查豁免；折不出且册外→③普查零容忍当场红。
    禁止的第四态＝既不进 resolved 也不进 dynamic（旧 `_visit` 判据 `if api is not None`
    会把 `''`／`API=''; call_api(API)` 当"已判定的非旁路 api"就地放走＝S182 §齿漏同族洞）。
    """
    rel = "plugins/bot_unified_runtime/poison_s189.py"
    # (A) 字面空串 + 折叠空串 + 折叠纯空白三形态，都必须落 dynamic（旧尺：两头不进＝静默消失）。
    blank_src = (
        "BLANK = ''\n"
        "PAD = '   '\n\n\n"
        "async def lit():\n    await bot.call_api('', group_id=1)\n\n\n"
        "async def fold_blank():\n    await bot.call_api(BLANK, group_id=2)\n\n\n"
        "async def fold_pad():\n    await bot.call_api(PAD, group_id=3)\n"
    )
    r, d = _scan_call_api_sites(blank_src, rel)
    assert r == set(), f"空串被折成合法旁路名＝凭空造阳（把不可判硬说成旁路）：{sorted(r)}"
    blank_funcs = {"lit", "fold_blank", "fold_pad"}
    assert {func for (_f, func, _form, _arg) in d} == blank_funcs, (
        f"折叠失败未全部点名入账（静默丢弃＝被禁止的第四态）：{sorted(d)}"
    )
    # (B) 保守侧不松：册外空串动态名绝不被豁免册吞（宁滥勿漏＝仍判可疑，交 ③ 零容忍）。
    assert d - set(_DYNAMIC_BOUNDED_SITES) == d, "合成空串动态名被豁免册吞了＝豁免面成了藏人抽屉"
    # (C) 反向对照：合法非空 api 名照常折进 resolved（本改动只让 dynamic 变大，绝不误伤折叠能力）。
    ok_src = (
        "API = 'upload_group_file'\n\n\n"
        "async def legit():\n    await bot.call_api(API, group_id=1)\n"
    )
    r2, d2 = _scan_call_api_sites(ok_src, rel)
    assert r2 == {(rel, "legit", "upload_group_file")} and d2 == set(), (
        f"非空合法折叠被误判为折叠失败＝扩尺伤及既有能力：resolved={sorted(r2)} dynamic={sorted(d2)}"
    )
    # (D) 投递域 fail-closed：折成空串的 call_api 也计直发嫌疑（与 None 同权，堵动态名躲字面量尺）。
    dirty = _names_with_bypass_or_dynamic(blank_src, blank_funcs)
    assert dirty == blank_funcs, f"空串折叠未进投递域 fail-closed（该形仍是盲区）：{sorted(dirty)}"
    # (E) 真树未被本改动凭空扩账 + 只扩不缩：普查 dynamic 仍恰等豁免册，旧尺命中不丢。
    resolved_now, dynamic_now, legacy_now = _production_census()
    assert dynamic_now == set(_DYNAMIC_BOUNDED_SITES), (
        "闭第四态后真树普查动态名偏离豁免册（真树有空白折叠、或改动误伤既有豁免）："
        f" 多={sorted(dynamic_now - set(_DYNAMIC_BOUNDED_SITES))}"
        f" 少={sorted(set(_DYNAMIC_BOUNDED_SITES) - dynamic_now)}"
    )
    assert legacy_now <= resolved_now, "只扩不缩被破坏：旧尺命中在新尺里丢了（缩面＝造绿）"


def test_active_push_roster_fails_closed_on_dynamic_names() -> None:
    """枚二 fail-closed 补牙（注毒，内存源）：名单成员长出**折不出名**的 call_api ⇒
    零容忍门必报违反（旧尺对此全瞎——这正是 S168 §3 点名要堵的洞）；不注入时名单照旧干净。"""
    extra = """


def _deliver_due_reminders():
    api_name = _pick_api_for_the_round()
    bot.call_api(api_name, group_id=1)
"""
    poisoned = _read(_ROOT_INIT) + extra
    dirty = _names_with_bypass_or_dynamic(poisoned, _ACTIVE_PUSH_ROSTER)
    assert "_deliver_due_reminders" in dirty, "名单成员动态直发没被抓＝枚二对动态名仍是盲区"
    assert _check_ratchet(dirty, _ACTIVE_PUSH_BYPASS_BASELINE), "零容忍门对动态名没报违反＝牙空"
    assert not measured_active_push_bypass(), "扩尺在真树名单上凭空造红＝折叠/别名识别有误报"


def test_teeth_exclude_parts_reader_is_pinned_and_applied() -> None:
    """排除面两头锁：① 现读值与手写期望真值逐枚相等（齿锁改排除面⇒本锁同批复判，
    普查扫描面不许跟着它悄悄搬家）；② 排除真生效——拿被排除的叶子发送器单扫有命中、
    全树普查里却没有，证排除面不是一本挂名册。"""
    parts = _teeth_exclude_parts()
    assert parts == ("transport/sender/", "ops/smoke/", "decision/outbound_registry.py"), (
        f"齿锁排除面漂移（现读={parts}）：census 扫描面随它变了，须同批复判本件与那把尺"
    )
    _resolved, dynamic, _legacy = _production_census()
    candidates = [
        p
        for p in sorted(_PLUGINS_DIR.rglob("*.py"))
        if any(part in p.relative_to(_REPO_ROOT).as_posix() for part in parts)
    ]
    assert candidates, "排除面下没有文件＝排除册是空的，② 半边空跑"
    seen_any = False
    for path in candidates:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        r, d = _scan_call_api_sites(path.read_text(encoding="utf-8"), rel)
        if r or d:
            seen_any = True
            assert not (r & _resolved) and not (d & dynamic), (
                f"被排除文件 {rel} 的命中混进了普查＝排除面没生效，两尺扫描面分了家"
            )
    assert seen_any, (
        "排除面下所有文件连一枚 call_api 通道调用都没有＝『排除真生效』没证到，本发空跑（须重挑样本）"
    )
