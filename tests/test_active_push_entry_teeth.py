"""S75：主动投递与回执两口的**活性**锁（全离线，绝不打网络、绝不写 plugins/**）。

一句话先说清楚（别把本件当"两口都已坐实"）：既有件 `test_five_entry_seam_lock.py`
用**静态 AST 可达性**证"某函数体里出现了 submit_active_push、且不含 call_api 直发"，
`test_progress_ack.py` 用**结构位置**证"回执投递口 await 了传输投递、校验了终态、有 raise"。
两者都停在"这段代码形状对不对"，**没有真的把这个函数跑一遍**去看它
——allow+在线 bot 时到底投没投？没投成功到底抛没抛回？

本件补的是**活性**那一半，判据全部"真调用、真投出、真抛回"：

1. `_ack_violations` 把根文件里的真 `_submit_progress_ack` **源码抽出来 exec**，用假
   闸 / 假 bot / 假投递灌四种场景，断言四条不变量。这条能杀两发注毒：
   - 注毒 A「就地送改回只入队」：把就地投递那段删掉 ⇒ 场景①当场报"allow+在线 bot 却没投"；
   - 注毒 B「去掉终态校验」：把 `if receipt.state not in {SENT,REDIRECTED}: raise` 删掉
     ⇒ 场景②当场报"回执没投出去却当成功返回"。
2. `scan_direct_send_bypasses` **全树扫** `bot.call_api("<mutating api>")` 直发。sink 名单 2026-09-24
   由「只认 send 族」扩成 **send 族 ∪ upload/delete 族**（裁定 R-5：`upload_group_file` /
   `upload_private_file` / `delete_msg`，口径取数口＝注册表 R1 自述的 QQ mutating 通道族），
   这条杀注毒 C「新增一处绕过中央出口的直发」：既有棘轮的名单是手写的**闭集**，名单外新长出的
   直发（如本席现算抓到、但 `_ACTIVE_PUSH_ROSTER` 没收录的入群欢迎 / cookie 二维码两枚）它看不见，
   本件看得见。
3. **判据形态随降账改版（S136 2026-09-24，与扩尺同批）**：那四枚 send 族直发已被裁定 R-4 收编，
   全树实测**归零** ⇒「只降不升棘轮」若留一份空基线就退化成「名册为空所以全绿」的空跑。
   本门因此转为**零容忍**：实测集合必须 ⊆ `_CHANNEL_BODY_SITES`（通道本体豁免册），多一枚即违反；
   同时豁免册自身受**活性反查**（在册却不真直发＝假豁免，当场红）。塌陷锁换法：不再要求
   「扫到 ≥4 枚旁路」（那已不可能成立），改为要求「扫描面仍现算得到豁免册那一枚，且它**只有靠
   upload/delete 族才可见**」——这条正是扩尺没瞎的证据。
4. **§四：撤回口 `delete_msg` 的活性 exec（S291C 2026-09-25，OI-196 核销）**——上面 1/2/3 与另两件
   （`test_five_entry_seam_lock.py` 枚五、`test_outbound_registry_coordinate_liveness.py` 坐标）
   关于 `delete_msg` 说的其实是**同一件事**：这枚三元组今天扫不扫得到、坐标对不对、名册等不等值。
   **没有一处把这个函数跑一遍**。§四补的就是这一半：只准删本次事件刚摄取的那条 `message_id`，
   其余一律拒——六条不变量逐条真跑（腿①顺带自证"本锁不是空跑"），再加一条耦合锁钉住
   "§四测的那枚＝豁免册发出豁免的那枚"，注毒六发逐发点名该负责的那一腿。旧尺对这六发的实测
   读数是**6/6 看不见**（`probes/s291c-oldvsnew.py` A 段），所以"存在性锁不算有牙"这句不是修辞。

诚实边界：exec 的是**盘上真源码**（AST get_source_segment 原样取出，仅注毒时喂**改过的
内存副本**，绝不回写文件）；全树扫描**只读**，注毒走 source= 内存串。**取数口 2026-09-24（S168）
已扩**（G1 / CM-P-69）：被调体认 `.call_api` 属性 / `getattr(x,"call_api")(…)` 直接调用 /
`c = getattr(x,"call_api")` 或 `c = x.call_api` 的**别名**三种形态；首参认字面量与**唯一字符串赋值**
可折常量名（`m="send_group_msg"; call_api(m,…)` 现在扫得到，旧尺对这条形态全瞎）。
`test_scan_surface_only_expands` 锁死「只扩不缩」（旧尺命中的每一枚，新尺必仍命中）。
**残余盲区（须与主代理同判，别把本件叙述成动态名已全视）**：首参是**不可折**的动态名——形参
（`group_info.call` 的 `action`）或计算值（`control_plane/dispatcher._execute` 的
`method = self._resolve_method(...)`）——api 身份判不出、尺诚实放过。今天这两枚非 excluded 非叶子的
动态直发都**不命中 sink**（折叠保守 ⇒ 保守不误报），故全树 measured 仍恰为豁免册那一枚 `delete_msg`。
要把这类也堵上须立「非叶子禁动态名 call_api」硬规则、并给两枚 bounded 通道体登记豁免——而那会牵动
`test_five_entry_seam_lock.py` 枚五③腿（它用自己的 literal-only `_has_bypass` 复核豁免，动态名复核不到），
属跨件协调、非本席独修（见席案 SEAT-S168 §3）。
既有件与本件是互补，不是互替——本件不改 `test_five_entry_seam_lock.py` 的判据；反过来那件的
枚五会**现算互认**两把尺的 sink 名单与豁免册（扩一侧不扩另一侧 ⇒ 它当场红）。

**第四态收口（S191 2026-09-24，与上面那段"残余盲区"同批读）**：折叠口原有三种结局，其中
「折出**空串/纯空白**」既不算"判定的非旁路"、也不算"不可判动态名"，旧判据让它**两桶都不进、
就地蒸发**——这是本件唯一一条没有任何名册认领的静默丢弃。现由 `_scan_channel_sites` 折成**两桶**
（旁路 ∪ 折叠失败），折叠失败那一桶**不立本件名册**，一律要求由五入口件那本唯一动态名册
`test_five_entry_seam_lock.py::_DYNAMIC_BOUNDED_SITES` 认领（枚六已证两尺共用 `_SCAN_EXCLUDE_PARTS`
＝同一张文件地；齿锁再立一本＝第二本动态名账，两本各说各话）。执法腿
`test_fold_failure_never_silently_drops`，注毒三发见席案 SEAT-S191 §2。
**同批更正上面那段盲区叙述的一处失实**：`control_plane/dispatcher.py::execute` 的首参 `method`
今天**不是**"折成 None 的计算值"，而是**折成了空串**——根因是 `_collect_bindings` 把类体字段默认
`method: str = ""`（`dispatcher.py:112`）当成模块级常量收下，内层函数里 `method = self._resolve_method(...)`
记为歧义后，解析沿栈外溢到模块层读到那枚 `""` ⇒ 判定"完成"且结论是垃圾。改前该站点两桶不进（静默），
改后落第二桶且被五入口件在册认领 ⇒ **旁路桶与全树 measured 集合逐字节未变**（只扩"可疑"一侧）。
类体默认值漏进模块常量这条**只报不修**（修它须同批复判本件全部折叠期望，且属取数口自身口径），
见 SEAT-S191 §3 同族清单第 1 条。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from types import SimpleNamespace
from typing import Any

from plugins.bot_unified_runtime.contracts import ReceiptState

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PLUGINS = _REPO_ROOT / "plugins" / "bot_unified_runtime"
_ROOT_INIT = _PLUGINS / "__init__.py"


# =========================================================================== 一、中央出口活性锚
def test_central_exit_really_enqueues_when_allowed() -> None:
    """`submit_active_push` 不是桩：闸放行时必须**真的**触达 `send_queue.submit` 并带回执。

    关态（现网缺省）走 passthrough：零 store、零审计，但**必须**调一次裸 submit，
    否则"接了中央出口"只是把消息从旧直发改成了"投进一个没人消费的口子"。
    """
    from plugins.bot_unified_runtime.contracts import DeliveryReceipt
    from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
        OutboundGate,
        OutboundGateSettings,
        submit_active_push,
    )

    submitted: list[Any] = []

    class _Queue:
        def submit(self, send_request: Any, **_kw: Any) -> Any:
            submitted.append(send_request)
            return DeliveryReceipt(
                request_id=send_request.request_id, state=ReceiptState.QUEUED, transport="test"
            )

    request = SimpleNamespace(
        request_id="ack-live-1",
        session_id="private_1",
        capability_id="bot.chat",
        target_scope=SimpleNamespace(value="private"),
        target_id="3865067623",
        dedupe_key="ack:live1",
        priority="normal",
        content=SimpleNamespace(risk_level=None),
        operational_issue=None,
    )
    gate = OutboundGate(OutboundGateSettings(enabled=False))
    outcome = submit_active_push(
        _Queue(), request, gate, dedupe_namespace="ack"
    )
    assert len(submitted) == 1, "闸放行却没触队列＝中央出口是空壳"
    assert outcome.verdict.action == "allow"
    assert outcome.receipt is not None


# =========================================================================== 二、回执投递口·活性 exec
def _ack_submitter_source() -> str:
    source = _ROOT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_submit_progress_ack"
        ),
        None,
    )
    assert node is not None, "根 __init__.py 找不到 _submit_progress_ack＝回执投递口搬家/改名，本锁须重判"
    segment = ast.get_source_segment(source, node)
    assert segment, "取不到 _submit_progress_ack 源码段"
    return segment


class _Receipt:
    def __init__(self, state: Any) -> None:
        self.state = state


class _Verdict:
    def __init__(self, action: str, deliver_after: Any) -> None:
        self.action = action
        self.deliver_after = deliver_after


class _Outcome:
    def __init__(self, verdict: _Verdict) -> None:
        self.verdict = verdict


def _run_ack_scenario(
    source: str,
    *,
    verdict_action: str,
    deliver_after: Any,
    bot_present: bool,
    receipt_state: Any,
) -> dict[str, Any]:
    """把注入件灌进真源码 exec 出来的闭包，跑一次回执投递，返回观测到的行为。"""
    calls: dict[str, int] = {"deliver": 0, "submit": 0}

    def _fake_submit_active_push(*_args: Any, **_kw: Any) -> _Outcome:
        calls["submit"] += 1
        return _Outcome(_Verdict(verdict_action, deliver_after))

    async def _fake_deliver(*_args: Any, **_kw: Any) -> _Receipt:
        calls["deliver"] += 1
        return _Receipt(receipt_state)

    def _fake_select(_provider: Any, _request: Any) -> Any:
        # 首参必须是"可调用对象"而非其返回值——本锁顺带复验这条真值不塌（同 test_progress_ack 的 provider 判据）。
        assert callable(_provider), "_select_queue_bot 首参不是可调用 provider＝回执在生产发不出去"
        return object() if bot_present else None

    namespace: dict[str, Any] = {
        "Any": Any,
        "submit_active_push": _fake_submit_active_push,
        "_select_queue_bot": _fake_select,
        "_all_online_bots": dict,
        "_deliver_transport_send_request": _fake_deliver,
        "ReceiptState": ReceiptState,
        "RuntimeError": RuntimeError,
        "send_queue": SimpleNamespace(),
        "outbound_gate": SimpleNamespace(),
        "audit_logger": SimpleNamespace(),
        "receipt_repository": SimpleNamespace(),
        "ACK_DEDUPE_NAMESPACE": "ack",
    }
    exec(compile(source, "<ack-poison-probe>", "exec"), namespace)  # noqa: S102 — 只 exec 本仓自己源码/内存注毒副本
    fn = namespace["_submit_progress_ack"]
    raised: str | None = None
    returned: bool = False
    try:
        result = asyncio.run(fn(SimpleNamespace()))
        returned = result is not None
    except RuntimeError as exc:
        raised = str(exc)
    return {
        "submit_calls": calls["submit"],
        "deliver_calls": calls["deliver"],
        "raised": raised,
        "returned": returned,
    }


def _ack_violations(source: str) -> list[str]:
    """四条活性不变量；返回违反清单（空＝这一版源码两口都真立）。"""
    violations: list[str] = []

    # ① 闸放行 + 有在线 bot + 真送出(SENT) ⇒ 必须就地投且只投一次、不抛、带回执。
    s1 = _run_ack_scenario(
        source,
        verdict_action="allow",
        deliver_after=None,
        bot_present=True,
        receipt_state=ReceiptState.SENT,
    )
    if s1["submit_calls"] != 1:
        violations.append(f"①中央出口未被真调（submit={s1['submit_calls']}）")
    if s1["deliver_calls"] != 1:
        violations.append(
            f"①放行且在线却没就地投（deliver={s1['deliver_calls']}）＝入队≠送出的老病"
        )
    if s1["raised"] is not None or not s1["returned"]:
        violations.append(f"①正常送达却被抛/没返回（raised={s1['raised']}）")

    # ② 闸放行 + 有 bot + 回执**没到** SENT/REDIRECTED（用 QUEUED 代表"只入队没送出"）⇒ 必须抛。
    s2 = _run_ack_scenario(
        source,
        verdict_action="allow",
        deliver_after=None,
        bot_present=True,
        receipt_state=ReceiptState.QUEUED,
    )
    if s2["deliver_calls"] != 1:
        violations.append("②未先就地投就判终态＝校验悬空")
    if s2["raised"] is None or s2["returned"]:
        violations.append("②回执没真投出去（QUEUED）却不当场抛＝冷却坑被白占、语义反转")

    # ③ 闸放行 + **无**在线 bot ⇒ 抛、且绝不空投。
    s3 = _run_ack_scenario(
        source,
        verdict_action="allow",
        deliver_after=None,
        bot_present=False,
        receipt_state=ReceiptState.SENT,
    )
    if s3["raised"] is None or s3["deliver_calls"] != 0:
        violations.append("③无在线 bot 时不该投出去，且必须抛回（不占冷却坑）")

    # ④ 闸拦下/顺延 ⇒ 直接交回队列：既不抛也不就地投（那是闸的职责）。
    s4 = _run_ack_scenario(
        source,
        verdict_action="defer",
        deliver_after=None,
        bot_present=True,
        receipt_state=ReceiptState.SENT,
    )
    if s4["raised"] is not None or s4["deliver_calls"] != 0:
        violations.append("④闸未放行时不该就地投、也不该抛（defer 交回队列）")

    return violations


def test_ack_submitter_is_live_not_just_shaped() -> None:
    """现役真源码：四条不变量全立（起点==实测，非"达标"）。"""
    violations = _ack_violations(_ack_submitter_source())
    assert violations == [], "回执投递口活性不成立：\n" + "\n".join(violations)


# -------------------------------------------------------------- 注毒（内存副本，绝不回写文件）
def _drop_inline_deliver(source: str) -> str:
    """注毒 A：把"就地投递"那段连同终态校验一起删掉，只留 submit + return（=改回只入队）。"""
    tree = ast.parse(source)
    fn = tree.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    kept: list[ast.stmt] = []
    for stmt in fn.body:
        text = ast.unparse(stmt)
        if "_deliver_transport_send_request" in text or "receipt.state" in text:
            continue
        kept.append(stmt)
    # 保留到最后一条 `return outcome`（guard 里那条也算）；显式补一条收尾 return。
    if not any(isinstance(s, ast.Return) for s in kept):
        kept.append(ast.Return(value=ast.Name(id="outcome", ctx=ast.Load())))
    fn.body = kept
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _drop_terminal_check(source: str) -> str:
    """注毒 B：只删"校验终态 ∈ {SENT,REDIRECTED} 否则抛"那一条 if（保留就地投）。"""
    tree = ast.parse(source)
    fn = tree.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    kept: list[ast.stmt] = []
    dropped = False
    for stmt in fn.body:
        text = ast.unparse(stmt)
        if (
            isinstance(stmt, ast.If)
            and "receipt" in text
            and "raise" in text
            and "_deliver_transport_send_request" not in text
        ):
            dropped = True
            continue
        kept.append(stmt)
    assert dropped, "注毒 B 没能定位到终态校验那条 if＝源码形状变了，本注毒要重判"
    fn.body = kept
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def test_ack_lock_kills_only_enqueue_poison() -> None:
    poisoned = _drop_inline_deliver(_ack_submitter_source())
    assert "_deliver_transport_send_request" not in poisoned.split('"""')[-1], (
        "注毒 A 没真删掉就地投递＝自证空跑"
    )
    violations = _ack_violations(poisoned)
    assert violations, "把就地送改回只入队，本锁却全绿＝假锁"


def test_ack_lock_kills_missing_terminal_check_poison() -> None:
    poisoned = _drop_terminal_check(_ack_submitter_source())
    violations = _ack_violations(poisoned)
    assert violations, "去掉终态校验，本锁却全绿＝假锁"


# =========================================================================== 三、全树直发旁路扫描棘轮
#: 投递族（走 SendQueue/中央出口的那三枚）。
_BYPASS_APIS_MESSAGE = frozenset({"send_private_msg", "send_group_msg", "send_msg"})
#: upload/delete 族（裁定 R-5，2026-09-24 扩进本尺；口径取数口＝注册表 R1 自述的 QQ mutating 通道：
#: `outbound_registry.py:197-210` 的 `SEND_FILE={upload_private_file,upload_group_file}` 与
#: `DELETE={delete_msg}`。扩尺前全树字面量现算：upload 族**零枚**非叶子直发（root 关态直传分支已随
#: 裁定 R-4 退役），delete 族**一枚**（`__init__.py:5371 _handle_dirty_guard`，见下方豁免册）。
_BYPASS_APIS_FILE_MUTATION = frozenset({"upload_group_file", "upload_private_file", "delete_msg"})
#: 本尺的完整 sink 名单。**`test_five_entry_seam_lock.py` 枚五会现算比对两把尺的名单逐枚相等**，
#: 只扩这一侧不扩那一侧＝连通锁当场红（防两把尺各说各话＝CM-P-26 的成因）。
_BYPASS_APIS = _BYPASS_APIS_MESSAGE | _BYPASS_APIS_FILE_MUTATION
#: 叶子发送器 / 冒烟 / 登记表 = 合法或纯数据，不计入"绕过中央出口的直发"。
_SCAN_EXCLUDE_PARTS = (
    "transport/sender/",
    "ops/smoke/",
    "decision/outbound_registry.py",
)

#: **通道本体豁免册**（不是欠账册）：非「投递」、结构上也没有排队通道的 mutating 直发。
#: 每枚都带现算证据与复算时刻，且受**活性反查**（`test_channel_body_exemptions_are_live`）：
#: 在册却扫不到＝假豁免（豁免面被用来藏新旁路的唯一路径就是往这里塞名字，故反查必须存在）。
#: 往这里加名字**不会**让任何投递直发变绿——投递族（send 三枚）永不吃豁免。
_CHANNEL_BODY_SITES: frozenset[tuple[str, str, str]] = frozenset(
    {
        (
            "plugins/bot_unified_runtime/__init__.py",
            "_handle_dirty_guard",
            # 现算证据（2026-09-24T06:4xZ）：`await bot.call_api("delete_msg", message_id=…)`
            # 在 severe 判定 ∧ `dirty_guard.delete_enabled` 门内，是唯一一条撤回直发；
            # 注册表 R1 `outbound_registry.py:205-210` 自述「dirty guard 等 **by-design** 撤回面」
            # ＝QQ DELETE 通道的通道本体就在根里，SendQueue 没有删除通道可走 ⇒ 收编=行为变更，待裁。
            "delete_msg",
        ),
    }
)

#: 欠账基线：2026-09-24 现算**降账至零**（裁定 R-4 把当年四枚 send 族直发全收编进统一管线，
#: 实测集合已空）。本门因此由「只降不升棘轮」升级为**零容忍**——留一份空基线继续当棘轮，
#: 就是「名册为空所以全绿」那种空跑（口径同 five_entry_seam_lock 枚四）。
#: 名字与 `frozenset(...)` 字面量形态**保留**：枚五靠 AST 现读它，改成派生表达式＝那本账自己给自己抬上限。
_DIRECT_SEND_BYPASS_BASELINE: frozenset[tuple[str, str, str]] = frozenset()


def _is_call_api_channel(value: ast.expr) -> bool:
    """值本身是否「call_api 通道」：属性 `X.call_api`，或 `getattr(X, "call_api", …)`。"""
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


def _collect_bindings(scope: ast.AST) -> tuple[dict[str, str], set[str], set[str]]:
    """扫一个作用域**自身**（不下钻进嵌套函数/lambda）的三种可见性：

    - `consts`：名字 → 字符串字面量，**仅当该名字在本作用域被恰好一次赋成字符串字面量**；
      任何其它赋值（Call 值 / 参数默认以外 / 重赋值）都把它从 `consts` 剔除并记为歧义
      ⇒ 折叠保守，绝不为「判不出的动态名」瞎猜 api（否则会把合法动态直发误报成旁路）。
    - `aliases`：绑定为 call_api 通道的名字（`c = X.call_api` / `c = getattr(X,"call_api")`）。
    - `params`：函数形参名（module 作用域为空）——供解析时判「形参遮蔽」，不可折。
    """
    consts: dict[str, str] = {}
    ambiguous: set[str] = set()
    aliases: set[str] = set()
    params: set[str] = set()

    def _bind(name: str, value: ast.expr) -> None:
        if _is_call_api_channel(value):
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

    def _walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue  # 嵌套作用域另算，不并入本级可见性
            if isinstance(child, ast.Assign):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name):
                        _bind(tgt.id, child.value)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and child.value is not None:
                _bind(child.target.id, child.value)
            _walk(child)

    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        argz = scope.args
        params = {a.arg for a in [*argz.posonlyargs, *argz.args, *argz.kwonlyargs]}
        if argz.vararg:
            params.add(argz.vararg.arg)
        if argz.kwarg:
            params.add(argz.kwarg.arg)
    _walk(scope)
    return consts, aliases, params


def _scan_channel_sites(source: str, relpath: str) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """扫单文件的 mutating 直发 → **两桶**（可判定的旁路三元组, 折叠失败的空白名三元组）。

    认三种被调体（旧尺只认第①种）：
      ① `X.call_api(…)`；② `getattr(X,"call_api")(…)`；③ 别名 `c = X.call_api/getattr(X,"call_api")` 后 `c(…)`。
    首参认字面量字符串，以及「唯一字符串赋值」的可折常量名（歧义/形参/Call 值不折 ⇒ 保守不误报）。

    **折叠口的三种结局必须各有去处（S191 2026-09-24 收口第四态）**：
      - 折出**非空** api 名 ⇒ 判定完成：在 `_BYPASS_APIS` 里进旁路桶，不在就是「已判定的非旁路」，放过。
      - 折出 **None** ⇒ 真正的不可判动态名（形参遮蔽 / 计算值 / 歧义重赋值）。这类**不在本件入账**：
        动态名的唯一真身名册是 `test_five_entry_seam_lock.py::_DYNAMIC_BOUNDED_SITES`（零容忍普查），
        且枚六证明两把尺共用同一个排除面 `_SCAN_EXCLUDE_PARTS`＝同一张文件地。齿锁再立一本＝第二本
        动态名账，两本各说各话正是 S189 点名的新洞，故这里只**如实放过并留指针**，不建册。
      - 折出**空串/纯空白** ⇒ 既不是"判定的结论"（空串不是任何 OneBot 动作名），也不是"不可判的动态名"
        （折叠器确实给出了一个值，只是这个值是垃圾）。旧判据 `api is not None and api in _BYPASS_APIS`
        让这种站点**两桶都不进、就地蒸发**＝第四态，本件唯一一条没有任何一册认领的静默丢弃。
        现改为**显式落第二桶**，由 `test_fold_failure_never_silently_drops` 零容忍执法（账面为空 ⇒
        不需要名册，新增一枚即红；保守方向只让"可疑集合"变大，绝不让旁路桶或放过面变大）。
    """
    tree = ast.parse(source)
    found: set[tuple[str, str, str]] = set()
    blank: set[tuple[str, str, str]] = set()

    module_consts, module_aliases, module_params = _collect_bindings(tree)
    # 栈条目：(consts, aliases, params)
    stack: list[tuple[dict[str, str], set[str], set[str]]] = [(module_consts, module_aliases, module_params)]

    def _is_channel_callee(call: ast.Call) -> bool:
        fn = call.func
        if isinstance(fn, ast.Attribute) and fn.attr == "call_api":
            return True
        if _is_call_api_channel(fn):  # getattr(X,"call_api")(...) 直接调用
            return True
        if isinstance(fn, ast.Name):
            return any(fn.id in aliases for (_c, aliases, _p) in stack)
        return False

    def _resolve_api(call: ast.Call) -> str | None:
        if not call.args:
            return None
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        if isinstance(first, ast.Name):
            for consts, _aliases, params in reversed(stack):  # 内层优先
                if first.id in consts:
                    return consts[first.id]
                if first.id in params:
                    return None  # 被形参遮蔽＝动态名，判不出 api（唯一真身名册在五入口件，见函数 docstring）
        return None

    def _blank_note(call: ast.Call, api: str) -> str:
        """第二桶的第三列：折叠失败的可读指纹（原样首参 → 折出的垃圾值）。"""
        return f"{ast.unparse(call.args[0])}->{api!r}"[:120]

    def _visit(node: ast.AST, func_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = func_name
            pushed = False
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                c_consts, c_aliases, c_params = _collect_bindings(child)
                stack.append((c_consts, c_aliases, c_params))
                inner = child.name
                pushed = True
            if isinstance(child, ast.Call) and _is_channel_callee(child):
                api = _resolve_api(child)
                if api is None:
                    pass  # 不可判动态名：由五入口件那本唯一名册零容忍执法，本件不另立账
                elif not api.strip():
                    blank.add((relpath, func_name, _blank_note(child, api)))  # 折叠失败＝禁静默
                elif api in _BYPASS_APIS:
                    found.add((relpath, func_name, api))
            _visit(child, inner)
            if pushed:
                stack.pop()

    _visit(tree, "<module>")
    return found, blank


def _scan_direct_send_bypasses(source: str, relpath: str) -> set[tuple[str, str, str]]:
    """旁路侧投影（`_scan_channel_sites` 的第一桶）。

    折叠失败那一桶**不由本投影承担**——只取本函数＝看不见第四态，故全树零容忍执法一律走
    `measured_blank_fold_sites()`，两条桶都由 `_scan_channel_sites` 这一次遍历同时产出（单一实现，
    不存在"投影口径与真身漂移"的第二把尺）。
    """
    return _scan_channel_sites(source, relpath)[0]


def _legacy_literal_scan(source: str, relpath: str) -> set[tuple[str, str, str]]:
    """改造前的旧取数口（只认 `.call_api("<字面量>")`）——专用于「只扩不缩」对照锁。"""
    tree = ast.parse(source)
    found: set[tuple[str, str, str]] = set()

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
                and child.args[0].value in _BYPASS_APIS
            ):
                found.add((relpath, func_name, str(child.args[0].value)))
            _visit(child, inner)

    _visit(tree, "<module>")
    return found


def _iter_production_files() -> list[pathlib.Path]:
    return [
        p
        for p in sorted(_PLUGINS.rglob("*.py"))
        if not any(part in p.relative_to(_REPO_ROOT).as_posix() for part in _SCAN_EXCLUDE_PARTS)
    ]


def measured_direct_send_bypasses() -> set[tuple[str, str, str]]:
    measured: set[tuple[str, str, str]] = set()
    for path in _iter_production_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        measured |= _scan_direct_send_bypasses(path.read_text(encoding="utf-8"), rel)
    return measured


def measured_blank_fold_sites() -> set[tuple[str, str, str]]:
    """全树「折叠失败」站点（第二桶）。账面合法值＝**空集**，执法见 `test_fold_failure_never_silently_drops`。

    与 `measured_direct_send_bypasses()` 走同一个 `_scan_channel_sites`（同一次遍历、同一份折叠逻辑），
    故两桶不可能各说各话；本件因此不需要、也**不许**再立第三本名册。
    """
    blank: set[tuple[str, str, str]] = set()
    for path in _iter_production_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        blank |= _scan_channel_sites(path.read_text(encoding="utf-8"), rel)[1]
    return blank


def test_no_unregistered_direct_send_bypass() -> None:
    """全树直发旁路 == 通道本体豁免册（**零容忍**：欠账基线已现算降为零，见上）。

    三腿各管一件事，缺一腿本门就退化成空跑：
    ① 扫描面非空（塌陷锁改版——今天能扫到的那一枚**只有靠 upload/delete 族才可见**，故它同时是扩尺没瞎的证据）；
    ② 欠账基线必须仍为空（再往里塞名字＝把旁路抬进上限，正是 CM-P-26 那件事）；
    ③ 实测 ⊆ 豁免册（多一枚即违反），且豁免册不得有假名字（在册却不真直发）。
    """
    measured = measured_direct_send_bypasses()
    assert measured, (
        "全树扫不到任何 mutating 直发＝要么扫描面塌了（判据失明），要么通道本体也已收编。"
        "后者是真的降账，但必须**同批**把本门塌陷锁、豁免册与枚五连通锁一起复判，"
        "不许只删一侧留个永远全绿的空壳。"
    )
    assert not _DIRECT_SEND_BYPASS_BASELINE, (
        f"欠账基线重新长出了条目 {sorted(_DIRECT_SEND_BYPASS_BASELINE)}＝把旁路抬进上限；"
        "今天这一册的合法值是空集（新旁路要么收编、要么如实红，不许登记成'允许'）。"
    )
    stale = _CHANNEL_BODY_SITES - measured
    assert not stale, (
        f"通道本体豁免册里这些条目今天已不直发（{sorted(stale)}）＝假豁免："
        "要么它被搬走/收编了（同批摘牌），要么有人往豁免册塞了个不直发的名字来藏旁路。"
    )
    new_bypass = measured - _DIRECT_SEND_BYPASS_BASELINE - _CHANNEL_BODY_SITES
    assert not new_bypass, (
        "长出未登记的绕过中央出口的直发（含 upload/delete 族；须先收进唯一出口/统一管线，"
        f"或证明它是无排队通道的通道本体并附现算证据）：{sorted(new_bypass)}"
    )
    # 扩尺可见性自证：本门扫到的集合里必须确有 file-mutation 族的成员（否则"扩了尺"这句话无证据）。
    assert {api for (_f, _fn, api) in measured} & _BYPASS_APIS_FILE_MUTATION, (
        "扩了 upload/delete 族却一枚都扫不到＝取数口没接到真树，本门的'族已入视野'是散文。"
    )


def test_channel_body_exemptions_are_live() -> None:
    """豁免册的**反抬上限**自证：拿一个今天不直发的真函数名塞进豁免册，活性判据必拒。

    这条与枚四/`test_event_direct_bypass_locks_have_teeth`(C) 同型：豁免面只能由"今天确实在直发"
    的事实换来，不能由"写进名单"换来。注毒全走合成集合，绝不碰真树与本册。
    """
    inflated = set(_CHANNEL_BODY_SITES) | {
        ("plugins/bot_unified_runtime/__init__.py", "_push_daily_group_digests", "upload_group_file")
    }
    measured = measured_direct_send_bypasses()
    fake = sorted(inflated - measured)
    assert fake == [
        ("plugins/bot_unified_runtime/__init__.py", "_push_daily_group_digests", "upload_group_file")
    ], f"往豁免册塞不直发的名字没被现算尺拒掉＝豁免面可以被用来藏旁路：{fake}"
    # 反向对照：在册的真名字不得被判成假豁免（否则上一条会退化成"随便报个名字都红"）。
    assert not (_CHANNEL_BODY_SITES - measured), "本册自家条目被判成假豁免＝本门起手就红，须重判"


def test_direct_send_scan_kills_new_bypass_poison() -> None:
    """注毒 C（三发）：名单外、绕过中央出口的直发，send 族与 upload/delete 族各一发必被抓，
    且第三发证明「干净现状不被误判」。"""
    for api, kind in (
        ("send_group_msg", "投递族"),
        ("upload_group_file", "upload 族"),
        ("delete_msg", "delete 族"),
    ):
        poison_source = (
            "async def _sneaky_active_push_job():\n"
            f"    await bot.call_api('{api}', group_id=1, message=[])\n"
        )
        hits = _scan_direct_send_bypasses(poison_source, "plugins/bot_unified_runtime/sneaky.py")
        assert hits == {("plugins/bot_unified_runtime/sneaky.py", "_sneaky_active_push_job", api)}, (
            f"{kind}的直发没被扫到＝扩尺后的 sink 名单没接上扫描器"
        )
        # 用同一把尺复算：塞进实测集 ⇒ 必被判为基线外违反（拦"回潮"）。
        assert hits - _DIRECT_SEND_BYPASS_BASELINE - _CHANNEL_BODY_SITES == hits, (
            f"{kind}新直发被判为已登记＝棘轮是空转"
        )
    # 反向：干净现状不得被误判为新增。
    assert not (measured_direct_send_bypasses() - _DIRECT_SEND_BYPASS_BASELINE - _CHANNEL_BODY_SITES)


def test_dynamic_send_forms_are_recognized() -> None:
    """取数口扩形态（G1/CM-P-69）注毒（全合成源、绝不碰真树）：三种被调体 × 可折首参各杀一发。

    每发都断言「新尺抓到、旧尺抓不到」⇒ 既证新形态有牙、又证这确是**新能力**而非旧尺本就能做。
    """
    cases = {
        # 折叠：`m="…"; bot.call_api(m,…)`（旧尺首参非 Constant ⇒ 全瞎）
        "折叠-投递族": (
            "async def _sneak():\n    m = 'send_group_msg'\n    await bot.call_api(m, group_id=1)\n",
            "_sneak",
            "send_group_msg",
        ),
        # 别名被调体：`c = getattr(bot,"call_api"); c("upload_group_file", …)`（旧尺 callee 非 Attribute）
        "别名-upload族": (
            (
                "async def _sneak2():\n    c = getattr(bot, 'call_api', None)\n"
                "    await c('upload_group_file', group_id=1)\n"
            ),
            "_sneak2",
            "upload_group_file",
        ),
        # getattr 直接调用被调体（旧尺同样全瞎）
        "getattr直调-delete族": (
            "async def _sneak3():\n    await getattr(bot, 'call_api')('delete_msg', message_id=1)\n",
            "_sneak3",
            "delete_msg",
        ),
        # 别名 + 折叠 双管齐下
        "别名且折叠": (
            "async def _sneak4():\n    c = bot.call_api\n    api = 'upload_private_file'\n    await c(api)\n",
            "_sneak4",
            "upload_private_file",
        ),
    }
    rel = "plugins/bot_unified_runtime/sneaky_dyn.py"
    for name, (src, fn, api) in cases.items():
        new_hits = _scan_direct_send_bypasses(src, rel)
        old_hits = _legacy_literal_scan(src, rel)
        assert new_hits == {(rel, fn, api)}, f"{name}：新尺没抓到动态直发（{new_hits}）"
        assert old_hits == set(), f"{name}：旧尺竟也抓到了＝这条不算新能力，注毒空跑"


def test_fold_is_conservative_no_false_positive() -> None:
    """折叠保守三发（防误报）：形参、计算值、歧义重赋值这三种**不可折**动态名一律放过。

    这正是「dispatcher._execute 的 method / group_info.call 的 action」不被误判成旁路的机理；
    若哪天尺改成对它们瞎猜 api，就会在真树上凭空造出旁路、或误伤合法 bounded 通道体。

    **S191 复判（旧值→新值）**：本用例原只断言 `_scan_direct_send_bypasses(...) == set()`（单桶投影，
    看不见第二桶）。取数口折成两桶后，光断言旁路桶为空**不再足够**——它无法区分"折成 None 放过"与
    "折成空串落进第二桶"。现改为直接调 `_scan_channel_sites` 并**同时**断言两桶皆空：这三形态折出的
    是 None（不可判，唯一真身名册在五入口件），**不是**折叠失败。这条即"只扩不缩"的反向腿：
    收口把第二桶从无到有，但不许它把保守放过的形态也吞进去（吞进去＝可疑集合无端变大＝假阳的另一张脸）。
    """
    rel = "plugins/bot_unified_runtime/conservative.py"
    cases = {
        # ① 形参遮蔽（即便模块级有同名常量也不折）
        "形参遮蔽": (
            "action = 'send_group_msg'\n\n\nasync def call(action):\n    await bot.call_api(action)\n"
        ),
        # ② 值是函数调用（非字符串字面量）
        "计算值": "async def _x(self):\n    m = self._resolve_method()\n    await bot.call_api(m)\n",
        # ③ 歧义重赋值（先字面量后被非字面量覆盖）
        "歧义重赋值": (
            "async def _y(user_input):\n    api = 'send_msg'\n    api = user_input\n"
            "    await bot.call_api(api)\n"
        ),
    }
    for name, src in cases.items():
        bypass, blank = _scan_channel_sites(src, rel)
        assert bypass == set(), f"{name}：不可折动态名被误折成旁路＝假阳"
        assert blank == set(), f"{name}：不可折动态名被记进折叠失败桶＝把'判不出'说成'折坏了'（{sorted(blank)}）"


def test_fold_failure_never_silently_drops() -> None:
    """折叠失败的**第四态**必须可见（S191 收口，判据口径同 `test_five_entry_seam_lock` 同名锁）。

    被禁的形态＝折出空串/纯空白的站点既不进旁路桶、也没有任何一册认领它（旧判据
    `if api is not None and api in _BYPASS_APIS` 下它就地蒸发，"看起来管住了"实际是漏）。
    现行三结局：非空名⇒判定完成；None⇒不可判动态名，由**五入口件那本唯一名册**零容忍执法
    （枚六证明两尺共用 `_SCAN_EXCLUDE_PARTS`＝同一张文件地，齿锁不另立第二本账）；
    空/纯空白⇒落第二桶，由本锁第五腿在真树上零容忍。保守方向只让"可疑集合"变大。
    """
    rel = "plugins/bot_unified_runtime/blankfold.py"
    # (A) 三形态折叠失败：字面空串 / 折叠空串 / 折叠纯空白 —— 全落第二桶，旁路桶一枚都不许多出来。
    # 每形态 (源, 期望归属函数, 期望折出的垃圾值 repr) —— 第三列必须留可复算指纹。
    forms: dict[str, tuple[str, str, str]] = {
        "字面空串": ("async def _b1():\n    await bot.call_api('', group_id=1)\n", "_b1", repr("")),
        "折叠空串": ("async def _b2():\n    m = ''\n    await bot.call_api(m, group_id=1)\n", "_b2", repr("")),
        "折叠纯空白": ("async def _b3():\n    m = '   '\n    await bot.call_api(m, group_id=1)\n", "_b3", repr("   ")),
        "别名且空白": ("async def _b4():\n    c = bot.call_api\n    m = '\\t'\n    await c(m)\n", "_b4", repr("\t")),
    }
    blank_all: set[tuple[str, str, str]] = set()
    for name, (src, expect_fn, expect_folded) in forms.items():
        bypass, blank = _scan_channel_sites(src, rel)
        assert bypass == set(), f"{name}：空串被折成合法旁路名＝凭空造阳（把不可判硬说成旁路）：{sorted(bypass)}"
        assert len(blank) == 1, f"{name}：折叠失败没被记进第二桶＝第四态仍然静默丢弃（blank={sorted(blank)}）"
        rec_rel, rec_fn, rec_note = next(iter(blank))
        assert (rec_rel, rec_fn) == (rel, expect_fn), f"{name}：第二桶归属错了站点（{rec_rel},{rec_fn}）"
        assert "->" in rec_note and expect_folded in rec_note, (
            f"{name}：第二桶没留下可复算的折叠指纹（{rec_note}，应含 {expect_folded}）"
            "＝只记'有洞'不记'洞在哪'"
        )
        blank_all |= blank
    assert len(blank_all) == 4, f"四形态折叠失败应各记一枚（现算 {len(blank_all)} 枚）＝合并时互相吞了"
    # (B) 合成空白站点不得被豁免册吞掉（豁免册第三列是 api 名，本桶第三列是 `表达式->值` 指纹，
    #     结构上不同域；这条把"豁免面成了藏人抽屉"的路径当场堵死）。
    assert blank_all - _CHANNEL_BODY_SITES == blank_all, "合成折叠失败被豁免册吞了＝豁免面成了藏人抽屉"

    # (C) 反向对照：合法非空折叠照旧进旁路桶（本改动只让第二桶变大，绝不误伤折叠能力）。
    good_src = "async def _ok():\n    m = 'send_group_msg'\n    await bot.call_api(m, user_id=1)\n"
    good_bypass, good_blank = _scan_channel_sites(good_src, rel)
    assert good_bypass == {(rel, "_ok", "send_group_msg")}, f"合法折叠被误判为折叠失败：{sorted(good_bypass)}"
    assert good_blank == set(), f"合法站点被记进第二桶＝可疑集合无端变大：{sorted(good_blank)}"
    # 已判定的非旁路名（get_msg）两桶都不进，且这是**判定出来的结论**、不是折不出。
    decided_src = "async def _safe():\n    await bot.call_api('get_group_member_list', group_id=1)\n"
    decided_bypass, decided_blank = _scan_channel_sites(decided_src, rel)
    assert decided_bypass == set() and decided_blank == set(), "已判定非旁路被误记账＝尺开始凭空造案"

    # (D) 不可判动态名（形参/计算值/歧义）在本件两桶都不进，**这是设计语义**：唯一真身名册在五入口件。
    #     这条断言的意义是"归属可指认"——一旦有人以为齿锁也管动态名（或反过来把这条改成入账＝立第二本账），
    #     此处与五入口件的 `_DYNAMIC_BOUNDED_SITES` 零容忍普查必有一边先红。
    undec_src = "action = 'send_group_msg'\n\n\nasync def _dyn(action):\n    await bot.call_api(action)\n"
    undec_bypass, undec_blank = _scan_channel_sites(undec_src, rel)
    assert undec_bypass == set() and undec_blank == set(), (
        f"不可判动态名的归属变了（bypass={sorted(undec_bypass)} blank={sorted(undec_blank)}）："
        "要么齿锁偷偷折了它（假阳），要么齿锁新建了第二本动态名账（两本各说各话＝新洞）"
    )
    from tests.test_five_entry_seam_lock import (
        _DYNAMIC_BOUNDED_SITES as _SEAM_ROSTER,  # 归属指针：动态名的唯一真身名册
    )

    assert isinstance(_SEAM_ROSTER, frozenset), "五入口件那本动态名册不在了＝本腿指针失效，两账须同批复判"

    # (E) 真树：第二桶每一枚都**必须由五入口件那本唯一动态名册认领**（交回 seam 册，齿锁不另立账）。
    #     现算实测（2026-09-24T08:42Z，尺身份：本件 `_scan_channel_sites` 全生产树）真树恰一枚：
    #     `control_plane/dispatcher.py::execute` 的 `method->''` —— 根因见本席报告 §2（类体字段默认
    #     `method: str = ""` 漏进模块常量 ⇒ 折叠器"判"出了空串）。这枚站点五入口件也判动态名并在册，
    #     两把尺对它的结论一致；换成子集判据而不是"∅ 判据"，是因为 **∅ 与本树不符＝凭记忆写数**。
    #     新长出一枚册外空白折叠 ⇒ 当场红；名册搬家 ⇒ 由五入口件那条零容忍普查先红。
    real_blank = measured_blank_fold_sites()
    seam_booked = {(site[0], site[1]) for site in _SEAM_ROSTER}
    unbooked = {tri for tri in real_blank if (tri[0], tri[1]) not in seam_booked}
    assert not unbooked, (
        f"真树出现折叠失败站点且唯一名册不认领（{sorted(unbooked)}）：空串不是任何 OneBot 动作名，"
        "这条判定既不是'非旁路'也不是'不可判'，就是第四态静默丢——"
        "要么把它按实收进五入口件的动态名册（附现算证据），要么把源站点的 api 名改成可判定形态，"
        "绝不允许在齿锁这边新立一本豁免（两本各说各话＝新洞）。"
    )
    assert real_blank, (
        f"真树连一枚空白折叠都扫不到（{sorted(real_blank)}）＝第二桶没接到真树，"
        "(A) 那四发合成注毒就成了测夹具不测代码；本锁的'已入账'是散文。"
    )
    legacy_real: set[tuple[str, str, str]] = set()
    for path in _iter_production_files():
        legacy_real |= _legacy_literal_scan(path.read_text(encoding="utf-8"), path.relative_to(_REPO_ROOT).as_posix())
    bypass_now = measured_direct_send_bypasses()
    assert legacy_real <= bypass_now, f"收口把旁路桶缩了（丢了 {sorted(legacy_real - bypass_now)}）＝假绿"
    assert bypass_now == set(_CHANNEL_BODY_SITES), (
        f"旁路桶今天不再恰等豁免册（{sorted(bypass_now)}）＝本改动动了判定结果，须同批复判枚四/枚五"
    )


def test_folded_dynamic_variant_of_exempt_delete_is_not_double_counted() -> None:
    """`_handle_dirty_guard` 那枚 delete_msg 的归属锁：把字面量改成折叠形态，**仍是同一枚三元组**
    （既不多算一枚、也不因折叠而漏算）⇒ 扩尺不会把在册豁免误变成 measured−exempt 的新旁路。"""
    literal = (
        "async def _handle_dirty_guard():\n    await bot.call_api('delete_msg', message_id=1)\n"
    )
    folded = (
        "async def _handle_dirty_guard():\n    api = 'delete_msg'\n"
        "    await bot.call_api(api, message_id=1)\n"
    )
    rel = "plugins/bot_unified_runtime/__init__.py"
    triple = (rel, "_handle_dirty_guard", "delete_msg")
    assert _scan_direct_send_bypasses(literal, rel) == {triple}
    assert _scan_direct_send_bypasses(folded, rel) == {triple}, (
        "折叠版 delete_msg 归属变了＝要么漏算（豁免反查会红），要么多算（凭空造新旁路）"
    )


def test_scan_surface_only_expands() -> None:
    """「只扩不缩扫描面」硬证：旧尺命中的每一枚，新尺必仍命中（真树 + 全形态合成双验）。"""
    # (1) 真树：legacy ⊆ new（新尺永远不比旧尺瞎）。今天二者应相等（无真实动态-mutating 直发）。
    legacy_real: set[tuple[str, str, str]] = set()
    for path in _iter_production_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        legacy_real |= _legacy_literal_scan(path.read_text(encoding="utf-8"), rel)
    new_real = measured_direct_send_bypasses()
    assert legacy_real <= new_real, (
        f"扩尺反而丢了旧尺命中的旁路（只扩不缩被违反）：{sorted(legacy_real - new_real)}"
    )
    # (2) 全形态合成源：新尺严格是旧尺的超集（至少多抓折叠/别名两枚）。
    mixed = (
        "async def _lit():\n    await bot.call_api('send_group_msg', group_id=1)\n\n\n"
        "async def _dyn():\n    m = 'send_private_msg'\n    await bot.call_api(m, user_id=1)\n\n\n"
        "async def _alias():\n    c = getattr(bot, 'call_api', None)\n"
        "    await c('delete_msg', message_id=1)\n"
    )
    rel = "plugins/bot_unified_runtime/mixed.py"
    old = _legacy_literal_scan(mixed, rel)
    new = _scan_direct_send_bypasses(mixed, rel)
    assert old < new, (
        f"合成全形态源上新尺未严格扩大（old={sorted(old)} new={sorted(new)}）＝取数口没真接到动态形态"
    )
    assert new == {
        (rel, "_lit", "send_group_msg"),
        (rel, "_dyn", "send_private_msg"),
        (rel, "_alias", "delete_msg"),
    }


def test_scan_excludes_legitimate_leaf_sender() -> None:
    """扫描面对叶子发送器（transport/sender 里真正 call_api 的那层）保持排除，
    否则把"唯一合法的出口实现"也判成旁路＝假红。这里只验排除逻辑本身。"""
    from pathlib import Path

    leaf = Path("plugins/bot_unified_runtime/domains/transport/sender/onebot.py")
    assert any(part in leaf.as_posix() for part in _SCAN_EXCLUDE_PARTS), (
        "叶子发送器未被排除名单覆盖＝扫描面会把合法出口判成旁路"
    )
    rels = {p.relative_to(_REPO_ROOT).as_posix() for p in _iter_production_files()}
    assert leaf.as_posix() not in rels, "onebot.py 混进了扫描面"


# =========================================================================== 四、撤回口 delete_msg·活性 exec
# （S291C 2026-09-25，OI-196／CM-P-69 推荐 A 的核销）
#
# 上面三节关于 `delete_msg` 说的其实是**同一件事**：全树 AST 扫描今天能不能扫到这枚三元组
# （豁免册活性反查、两把尺名单互认、折叠归属、登记坐标等值）。**没有一节把这个函数真跑一遍**，
# 去看它在"不该删"的时候到底删不删、在"该删"的时候删的是**哪一条**。CM-P-69 推荐 A 点的正是
# 这一半：豁免只写到「允许调 delete_msg」这一层＝给「用撤回之名发任何东西」开门。
# 本节的判据是**行为**——只准删本次事件刚摄取的那条 `message_id`，其余一律拒，六条不变量逐条真跑。
#
# 手法与 §二 同一条、诚实边界也同一条：`ast.get_source_segment` 取**盘上真源码** → `exec` →
# 假 bot 记账；注毒一律喂**改过的内存副本**，绝不回写生产件。判词用**真身** `DirtyGuard`
# （不 fake 词表——fake 了就把「severe 判定」那条腿测成夹具），样本词由真身词表派生，
# 本件因此不落任何违禁字面量。

#: 删除口的身份（与豁免册同一坐标轴；`test_delete_port_lock_is_the_roster_own_site` 把两者钉在一起）。
_DELETE_PORT_FILE = "plugins/bot_unified_runtime/__init__.py"
_DELETE_PORT_FUNCTION = "_handle_dirty_guard"
_DELETE_PORT_API = "delete_msg"

#: 事件"不带 message_id"这一形态的哨兵（不能用 None——None 恰是生产代码自己兜的底）。
_MISSING_ID = object()


def _delete_port_source() -> str:
    """原样取出根 `__init__.py` 里真身 `_handle_dirty_guard` 的源码段。

    不 import 根包、不起 NoneBot：本节的靶子是**这段代码的行为**，取源码段就够。
    找不到函数＝撤回口搬家/改名，豁免册那条 `delete_msg` 与下面六条不变量都须重判（断言点名）。
    """
    source = _ROOT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == _DELETE_PORT_FUNCTION
        ),
        None,
    )
    assert node is not None, (
        f"根 __init__.py 找不到 {_DELETE_PORT_FUNCTION}＝撤回口搬家/改名，"
        "_CHANNEL_BODY_SITES 那条 delete_msg 豁免须重判"
    )
    segment = ast.get_source_segment(source, node)
    assert segment, f"取不到 {_DELETE_PORT_FUNCTION} 源码段"
    return segment


class _RecordingBot:
    """假 bot：逐笔记下 `call_api(api, **kwargs)`，供"删了谁、带没带别的参数"这种判据取用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_api(self, api: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((api, kwargs))
        return {}


def _event_of(text: str, message_id: Any = _MISSING_ID, **extra: Any) -> SimpleNamespace:
    event = SimpleNamespace(get_plaintext=lambda: text)
    if message_id is not _MISSING_ID:
        event.message_id = message_id
    for name, value in extra.items():
        setattr(event, name, value)
    return event


def _delete_calls(
    source: str,
    *,
    text: str,
    delete_enabled: bool,
    message_id: Any = _MISSING_ID,
    **extra: Any,
) -> list[tuple[str, dict[str, Any]]]:
    """把一份（可能是注毒副本的）源码 exec 出来，跑一次撤回口，返回它实际打出去的直发。"""
    from plugins.bot_unified_runtime.domains.files.capabilities.group_files import (
        DirtyGuard,
    )

    namespace: dict[str, Any] = {
        # 形参注解 Bot / Event 在 exec 的独立模块里必须可解析，否则 def 当场 NameError。
        "Bot": object,
        "Event": object,
        "dirty_guard": DirtyGuard(delete_enabled=delete_enabled),
    }
    exec(compile(source, "<delete-port-probe>", "exec"), namespace)  # noqa: S102 — 只 exec 本仓自己源码/内存注毒副本
    handler = namespace[_DELETE_PORT_FUNCTION]
    bot = _RecordingBot()
    asyncio.run(handler(bot, _event_of(text, message_id, **extra)))
    return bot.calls


def _delete_port_violations(source: str) -> list[str]:
    """六条活性不变量（腿①–⑥，违反清单为空＝这一版源码真的"只删刚摄取那条"）。

    每条违反都带腿号，注毒用例据此断言"被抓到的正是该它抓的那一发"，而不只是"随便红了"。
    """
    from plugins.bot_unified_runtime.domains.files.capabilities.group_files import (
        DirtyGuard,
    )

    own_id = "msg-ingested-42"
    foreign_id = "msg-elsewhere-7"
    # 样本词由**真身词表运行时派生**：本件因此不抄第二套词表，也不落下违禁字面量。
    severe_text = f"转发：{DirtyGuard._SEVERE[0]} 教程"
    warn_text = f"你个{DirtyGuard._WARN[0]}"
    clean_text = "今晚有人一起打本吗"
    violations: list[str] = []

    # ⓪ 样本自证：三条样本在真身词表下的级别必须如本席设定，否则下面每一发都在追一个不存在的场景。
    probe = DirtyGuard(delete_enabled=False)
    for label, text, want in (
        ("severe", severe_text, "severe"),
        ("warn", warn_text, "warn"),
        ("clean", clean_text, "clean"),
    ):
        got = probe.assess(text)
        if got != want:
            violations.append(
                f"[腿⓪] 样本失义：{label} 样本被真身判成 {got}——本锁的场景前提塌了，须换样本，不许放宽判据"
            )

    # ① 该删时确实删了：恰好一次、只带 message_id、值就是本次事件刚摄取那条。
    hits = _delete_calls(source, text=severe_text, delete_enabled=True, message_id=own_id)
    if len(hits) != 1:
        violations.append(
            f"[腿①] severe＋开撤回应当**恰好**撤回一次，实得 {len(hits)} 次＝这把锁没有靶子（空跑）"
        )
    else:
        api, kwargs = hits[0]
        if api != _DELETE_PORT_API:
            violations.append(f"[腿①] 撤回口打的是 {api} 而非 {_DELETE_PORT_API}＝豁免册那条名不副实")
        if set(kwargs) != {"message_id"}:
            violations.append(
                f"[腿②] 撤回只准带 message_id，实带 {sorted(kwargs)}＝用撤回之名发别的东西"
            )
        elif kwargs["message_id"] != own_id:
            violations.append(
                f"[腿①] 撤回的 id 不是本次事件刚摄取那条（期望 {own_id}，实得 {kwargs['message_id']!r}）"
            )

    # ③ 事件上另摆一条别的 id 时，也绝不许删那一头——「只准删刚摄取的」这句的全部含量。
    hits_alt = _delete_calls(
        source,
        text=severe_text,
        delete_enabled=True,
        message_id=own_id,
        forward_message_id=foreign_id,
    )
    if len(hits_alt) != 1:
        violations.append(f"[腿③] 带旁证 id 的场景撤回次数异常（实得 {len(hits_alt)} 次）")
    elif hits_alt[0][1].get("message_id") != own_id:
        violations.append(
            f"[腿③] 事件上多一条 id 就改删那一头（实得 {hits_alt[0][1].get('message_id')!r}）＝越权撤回"
        )

    # ④ 判词不到 severe（warn / clean）一律拒撤。
    for label, text in (("warn", warn_text), ("clean", clean_text)):
        loose = _delete_calls(source, text=text, delete_enabled=True, message_id=own_id)
        if loose:
            violations.append(f"[腿④] {label} 消息被撤回了（{loose}）＝severe 判定这一腿被放宽")

    # ⑤ 撤回开关关着（BOT_DIRTY_GUARD_DELETE=false）就不许删。
    off = _delete_calls(source, text=severe_text, delete_enabled=False, message_id=own_id)
    if off:
        violations.append(f"[腿⑤] delete_enabled=False 仍然撤回（{off}）＝那道开关门没执法")

    # ⑥ 事件不带 message_id 就不许删（绝不许兜底"随便挑一条"）。
    noid = _delete_calls(source, text=severe_text, delete_enabled=True)
    if noid:
        violations.append(f"[腿⑥] 事件不带 message_id 仍撤回（{noid}）＝兜底删了来源不明的 id")

    return violations


def test_delete_port_really_goes_through_and_refuses() -> None:
    """OI-196 的主证据：**这条用例真的经过删除口**，并逐条断言了拒权行为。

    腿①顺带是"本锁不是空跑"的自证：severe＋开撤回必须真撤一次，撤不出去整把锁当场红。
    """
    violations = _delete_port_violations(_delete_port_source())
    assert not violations, "撤回口不守「只删刚摄取那条」：" + "；".join(violations)


def test_delete_port_lock_is_the_roster_own_site() -> None:
    """耦合锁：本活性锁测的那一枚**必须就是**豁免册发出去的那一枚（名册指 A、行为测 B＝两本各说各话）。

    这条同时锁死"豁免册被拿去豁免另一处撤回"的漂移：册里 delete_msg 那一枚换文件、换函数，本节即红。
    """
    assert _ROOT_INIT.relative_to(_REPO_ROOT).as_posix() == _DELETE_PORT_FILE, (
        "本节的靶子文件与 _ROOT_INIT 不再是同一个＝耦合锁失效"
    )
    roster_delete = {site for site in _CHANNEL_BODY_SITES if site[2] == _DELETE_PORT_API}
    assert roster_delete == {(_DELETE_PORT_FILE, _DELETE_PORT_FUNCTION, _DELETE_PORT_API)}, (
        f"豁免册里 delete_msg 的身份变了（{sorted(roster_delete)}）＝本节六条不变量测的已不是发豁免那一枚，须同批复判"
    )


#: 六发注毒：全部内存副本（本席禁写生产件，绝不回写 `plugins/**`），逐发必须被**点名那一腿**抓到。
#: 每发都先自证"确实改动了源码串"——注毒改成空操作＝假红（同 §二 注毒台的前置纪律）。
_DELETE_PORT_POISONS: tuple[tuple[str, str, str, str], ...] = (
    ("越权删常量 id", "message_id=message_id", "message_id=999999", "[腿①]"),
    (
        "借撤回之名发消息",
        'await bot.call_api("delete_msg", message_id=message_id)',
        'await bot.call_api("delete_msg", message_id=message_id, group_id=7, message=[{"type": "text"}])',
        "[腿②]",
    ),
    (
        "放宽词表门（warn/clean 也撤）",
        'if verdict != "severe" or not dirty_guard.delete_enabled:',
        "if not dirty_guard.delete_enabled:",
        "[腿④]",
    ),
    (
        "放宽撤回开关门（关态也撤）",
        'if verdict != "severe" or not dirty_guard.delete_enabled:',
        'if verdict != "severe":',
        "[腿⑤]",
    ),
    (
        "无 id 时兜底删一条",
        'message_id = getattr(event, "message_id", None)',
        'message_id = getattr(event, "message_id", None) or 999999',
        "[腿⑥]",
    ),
    (
        "改删事件上另一条 id",
        "message_id=message_id",
        "message_id=getattr(event, 'forward_message_id', message_id)",
        "[腿③]",
    ),
)


def test_delete_port_locks_have_teeth() -> None:
    """存在性锁不算有牙——**注毒自证**：六发越权形态逐发必被抓，且抓它的正是该负责的那一腿。"""
    real = _delete_port_source()
    assert not _delete_port_violations(real), "起手真源码就有违反＝本门开局即红，须先重判场景前提"
    for label, old, new, leg in _DELETE_PORT_POISONS:
        assert real.count(old) >= 1, (
            f"注毒「{label}」的受害点不在真源码里（{old!r}）＝靶子搬家，本发会退化成空跑，须换锚"
        )
        poisoned = real.replace(old, new)
        assert poisoned != real, f"注毒「{label}」没改动源码＝假毒（测夹具不测代码）"
        ast.parse(poisoned)  # 注毒必须是合法源码，否则红在语法上、说明不了判据抓到了越权
        violations = _delete_port_violations(poisoned)
        assert violations, f"注毒「{label}」没被抓到＝那一腿是散文不是锁"
        assert any(leg in v for v in violations), (
            f"注毒「{label}」虽红但红因不对（{violations}）：期望 {leg} 负责，实际没有＝判据在互相顶包"
        )
