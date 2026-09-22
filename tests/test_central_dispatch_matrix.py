"""中央调度层「逐 id 行为矩阵」（S-E2E-MATRIX）：对**每一个**在册执行形逐枚验五件事。

一句话——本件不新增任何机制，只把散在五处的证据**收成一张按 capability_id 参数化的矩阵**：
`test_prepared_adapter_canary.py` 只钉金丝雀 `bot.weather` 一枚（外加多入口活性锁），
`test_prepared_adapter_batch1/2.py` 只钉各批自己那几枚，`test_orchestration_callsite_single.py`
钉直呼点唯一性与 sink 形态，`test_descriptor_wiredness_ledger.py` 只算账面缺口数。
**没有一处**回答「对唯一表当前声明的**每一枚**能力：描述符在、handler 派生出来了、
角色下限真在执法（且拒的时候 handler 一次都没跑）、终态恰落一行审计、跑的就是交来那一个」。

本波三次对抗评审（REVIEW-RPREP C-1 / REVIEW-RCHOKE C-1 / R-CENTRAL C-1）反复踩的正是同一类
「声明即通电」假绿：每批测试证的是**handler 的行为**，而"该行是否真被中央治理"没人一次性量过。
所以本件的判据一律**从注册表派生**（`_route_execution_adapters()` 现算），一枚都不手抄：
枚数、id、adapter 形态全是从真身读出来的，改名字、加一批、删一批都会自动跟随，
而矩阵**静默缩成零**由文件末尾的非空转守卫当场红（规则 10：计数一律现算，绝不抄）。

刻意**不重复**已在他处执法的不变量（避免第二真身）：
- 多入口活性（凡按 capability_id 分流者必汇到中央缝）= canary 的
  `test_every_resolved_capability_entry_reaches_the_central_seam`；
- 直呼点唯一性 / 审计 sink 形态 = `test_orchestration_callsite_single.py`；
- 缺口账棘轮数 = `test_descriptor_wiredness_ledger.py`。

纪律（本仓已为此踩过两次假红）：**绝不往 `default_invoker()` 注册任何东西**。
默认 invoker 是单例，往里塞探针会让别的门（`registry_ids == …` 那类集合比对）当场假红。
本件对单例**只读**（取描述符、取派生 handler），一切需要写注册表的用例都走**私有 invoker**。
"""

from __future__ import annotations

import dataclasses
import sys
from types import ModuleType, SimpleNamespace

import pytest

#: via 全身份等值判据真身（HARDEN-1 I-1）：本件是"逐 id 归因"的共用落点，判据只此一支，
#: 批次件（canary/batch1/2/3）与中央门各自引用同一函数，不留第二份拼接逻辑。
from test_central_via_identity_and_entry_durability import expected_via

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: 建请求一律走这个引用：下面有注毒用例会把 `cp.CapabilityRequest` 换成假构造器，
#: 本件若按模块属性取类就会套娃调用自己（canary 同款教训）。
_REAL_REQUEST = cp.CapabilityRequest

#: 采集期快照＝参数化的唯一依据（现算，不手抄任何枚数）。
_COLLECTED: tuple[tuple[str, str], ...] = tuple(sorted(cp._route_execution_adapters().items()))

if not _COLLECTED:
    # 空矩阵必须**响亮**红：import 期炸掉＝collection error，比"0 条用例全绿"诚实得多。
    raise RuntimeError(
        "_route_execution_adapters() 一枚都没有＝唯一表执行形面消失或被改名，"
        "本矩阵与它要证明的整条接入面同时失效（不许靠 0 条用例通过）"
    )

IDS: tuple[str, ...] = tuple(cid for cid, _adapter in _COLLECTED)
ADAPTER_OF: dict[str, str] = dict(_COLLECTED)
_BY_ADAPTER: dict[str, tuple[str, ...]] = {}
for _adapter_name in sorted({adapter for _cid, adapter in _COLLECTED}):
    _BY_ADAPTER[_adapter_name] = tuple(
        cid for cid, adapter in _COLLECTED if adapter == _adapter_name
    )
PREPARED_IDS: tuple[str, ...] = _BY_ADAPTER.get("prepared", ())
COMMAND_IDS: tuple[str, ...] = _BY_ADAPTER.get("command", ())

_REAL = cp.default_invoker  # 只读取真身；本件绝不向它注册（见模块 docstring）


# ===========================================================================
# 夹具（沿用 canary/batch1 的形态：真呈现契约 + 计数成品 + 私有 invoker）
# ===========================================================================
def _presented(cid: str, body: str) -> object:
    """真·呈现契约（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-mtx",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["central-dispatch-matrix"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"，并把执行痕迹记进 `calls`（证"跑的就是这一个"）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(cid, body)

    return _capability


def _request(
    cid: str,
    *,
    capability: object | None = None,
    roles: tuple[str, ...] = ("user",),
    config: object | None = None,
) -> cp.CapabilityRequest:
    context: dict[str, object] = {
        "config": config if config is not None else SimpleNamespace(),
        "decision": SimpleNamespace(),
    }
    if capability is not None:
        context["capability"] = capability
    return _REAL_REQUEST(
        capability_id=cid,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-mtx")},
        principal="3865067623",
        roles=roles,
        request_id="req-mtx",
        session_key="private:3865067623",
        context=context,
    )


def _descriptor(cid: str) -> cp.CapabilityDescriptor:
    """从单例**读**描述符（读是安全的，写不是）。"""
    descriptor = _REAL().registry.get(cid)
    assert descriptor is not None, f"{cid} 在册却没有描述符（前提失效，下面的判据无从谈起）"
    return descriptor


def _derived_handler(cid: str) -> cp.HandlerFn:
    """从单例**读**派生 handler：矩阵验的就是"这一枚真身派生出的那段码"，不是自造替身。"""
    handler = _REAL().handlers.get(cid)
    assert handler is not None, f"{cid} 没派生出 handler"
    return handler


def _private_invoker(
    cid: str,
    handler: cp.HandlerFn,
    *,
    descriptor: cp.CapabilityDescriptor | None = None,
    hook: object | None = None,
) -> cp.CapabilityInvoker:
    """一枚**私有** invoker：需要注册探针（计数 handler、抬高下限的描述符副本）时一律用它。

    `audit_hooks` 缺省会新建一份注册表 ⇒ 钩子计数天然是本用例私有的，绝不与生产 sink 相互污染。
    """
    invoker = cp.CapabilityInvoker(
        registry=cp.CapabilityRegistry(), handlers=cp.HandlerRegistry()
    )
    invoker.registry.register(descriptor or _descriptor(cid))
    invoker.handlers.register(cid, handler)
    if hook is not None:
        invoker.audit_hooks.register(hook)  # type: ignore[arg-type]
    return invoker


def _counting_handler(log: list[str]) -> cp.HandlerFn:
    def _handler(request: cp.CapabilityRequest) -> cp.InvocationResult:
        log.append(request.capability_id)
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            via="matrix_probe",
            attempts=1,
        )

    return _handler


def _sub_floor_roles(required: tuple[str, ...]) -> str:
    """挑一个**低于该能力角色下限**的角色；下限已在最底（user）时退回 `blocked`。

    `blocked` 也是 DENIED，但它走的是 invoker 更早的无条件拒——所以本件另外用
    "把下限抬到 admin 的副本"（见 `_floor_probe_descriptor`）真正量一次层级比较那条腿，
    避免"角色门恒放行"时这条锁空转。
    """
    known = [
        role for role in required if role in cp.ROLE_ORDER and role != cp.ROLE_BLOCKED
    ]
    if not known:
        return cp.ROLE_BLOCKED
    floor = min(cp.ROLE_ORDER.index(role) for role in known)
    lower = [role for role in cp.ROLE_ORDER[:floor] if role != cp.ROLE_BLOCKED]
    return lower[0] if lower else cp.ROLE_BLOCKED


def _floor_probe_descriptor(cid: str) -> cp.CapabilityDescriptor:
    """同 id、下限抬到 `admin` 的**副本**（只进私有 invoker）：用来量层级比较那条腿。"""
    return dataclasses.replace(_descriptor(cid), required_roles=("admin",))


def _ref_parts(cid: str) -> tuple[str, str, str]:
    """(implementation_ref, 可 import 的模块名, 符号名)——command 形自建分支的三块料。"""
    ref = _descriptor(cid).implementation_ref
    module_part, _hash_mark, symbol = ref.partition("#")
    return ref, module_part.removesuffix(".py").replace("/", "."), symbol


def _raising_stub(dotted: str, symbol: str) -> ModuleType:
    """装在 `sys.modules` 里的"绝对不该被跑到"的替身：一旦被 prepared 形拿来自建就当场炸。"""
    stub = ModuleType(dotted)

    def _forbidden_builder(config: object) -> object:
        raise AssertionError(
            f"prepared 形按 ref 自建了（{dotted}#{symbol}）＝丢装配期注入的第二通路"
        )

    setattr(stub, symbol, _forbidden_builder)
    return stub


# ===========================================================================
# ① 登记面 + ② 描述符面 + ③ 派生面（逐 id）
# ===========================================================================
@pytest.mark.parametrize("cid", IDS)
def test_declared_adapter_is_in_the_known_roster(cid: str) -> None:
    """在册执行形必须在名册里：名册外的形态＝装配期炸 or 静默无人派生，两者都该红。"""
    adapter = cp._route_execution_adapters().get(cid)
    assert adapter in cp._KNOWN_ADAPTERS, (
        f"{cid}: 执行形 {adapter!r} 不在 _KNOWN_ADAPTERS={sorted(cp._KNOWN_ADAPTERS)}"
    )


@pytest.mark.parametrize("cid", IDS)
def test_descriptor_exists_and_admits_real_humans(cid: str) -> None:
    """描述符在、角色下限非空且含 `user`：真人桶与系统桶不得混用（D-4/R-CHOKE 权限面同口径）。"""
    descriptor = _descriptor(cid)
    assert descriptor.capability_id == cid
    assert descriptor.required_roles, f"{cid}: 角色下限为空＝任何主体都过"
    assert "user" in descriptor.required_roles, (
        f"{cid}: 角色下限 {descriptor.required_roles} 不含 user＝真人永远进不去"
    )
    assert "#" in descriptor.implementation_ref, f"{cid}: 没有在册真身指针，事后无从归因"


@pytest.mark.parametrize("cid", IDS)
def test_handler_is_derived_not_merely_declared(cid: str) -> None:
    """派生同源：登记了形态就必须派生出 handler，不许"只放开登记不实现信封"。"""
    assert _REAL().handlers.get(cid) is not None, (
        f"{cid}: adapter={ADAPTER_OF[cid]} 在册却没 handler＝半批施工"
        "（中央件 import 期会炸、依赖它的门会 skip 变哑——不是红）"
    )


# ===========================================================================
# ④ 角色门执法（拒 ⇒ handler 一次都没跑；到门 ⇒ 真跑；两腿互为非空转锚）
# ===========================================================================
@pytest.mark.parametrize("cid", IDS)
def test_role_floor_denies_without_running_the_handler(cid: str) -> None:
    """三条腿一起才叫证据：低于下限拒且**没跑**、抬高下限后 user 也拒、到门则真跑一次。

    只测"blocked 被拒"会空转（invoker 在更早处无条件拒 blocked，与角色下限无关）；
    只测"拒"不测"放"会把"角色门恒拒"当成通过。故本例同时钉反方向。
    """
    ran: list[str] = []
    invoker = _private_invoker(cid, _counting_handler(ran))

    denied = invoker.invoke(_request(cid, roles=(_sub_floor_roles(_descriptor(cid).required_roles),)))
    assert denied.status is cp.InvocationStatus.DENIED, f"{cid}: 低于下限却未被拒：{denied}"
    assert ran == [], f"{cid}: 被拒之后 handler 仍跑了＝权限门是装饰：{ran}"

    strict = _private_invoker(
        cid, _counting_handler(ran), descriptor=_floor_probe_descriptor(cid)
    )
    by_floor = strict.invoke(_request(cid, roles=("user",)))
    assert by_floor.status is cp.InvocationStatus.DENIED, (
        f"{cid}: 下限抬到 admin 后 user 仍被放行＝层级比较那条腿没在执法（上一步就是空转）"
    )
    assert ran == [], f"{cid}: 角色拒却仍执行 handler：{ran}"
    assert "admin" in by_floor.detail, by_floor.detail

    admitted = invoker.invoke(_request(cid, roles=_descriptor(cid).required_roles))
    assert admitted.status is not cp.InvocationStatus.DENIED, admitted.detail
    assert ran == [cid], f"{cid}: 到门的合法主体没被执行：{ran}"


# ===========================================================================
# ⑤ 终态恰落一行审计（私有钩子；多落一行＝将来双 emit 回归）
# ===========================================================================
@pytest.mark.parametrize("cid", IDS)
def test_terminal_state_is_audited_exactly_once(cid: str) -> None:
    """一次调用＝一行审计，成功与拒判两条早退路都要成立（含关联键归因）。"""
    records: list[cp.CapabilityAuditRecord] = []

    def _hook(record: cp.CapabilityAuditRecord) -> None:
        records.append(record)

    calls: list[str] = []
    invoker = _private_invoker(cid, _derived_handler(cid), hook=_hook)
    result = invoker.invoke(_request(cid, capability=_assembled(cid, "成品", calls)))

    assert len(records) == 1, f"{cid}: 一次调用落了 {len(records)} 行审计（双 emit＝用量与告警虚高）"
    record = records[0]
    assert record.capability_id == cid and record.status is result.status
    assert (record.request_id, record.session_key) == ("req-mtx", "private:3865067623"), (
        f"{cid}: 审计没带上关联键，事后无法归因到一条消息：{record}"
    )
    assert record.via == result.via, "审计里的 via 与实际终态不是同一条路"

    invoker.invoke(_request(cid, roles=(_sub_floor_roles(_descriptor(cid).required_roles),)))
    assert len(records) == 2, f"{cid}: 拒判态补落/漏落审计（实得 {len(records)}）"
    assert records[1].status is cp.InvocationStatus.DENIED


# ===========================================================================
# ⑥ prepared 形：跑的就是交来那一个；没交来 ⇒ UNAVAILABLE 且**绝不**按 ref 自建
# ===========================================================================
@pytest.mark.parametrize("cid", PREPARED_IDS)
def test_prepared_runs_the_injected_capability(cid: str) -> None:
    """注入件赢：中央跑的就是调用方交来的成品，且 via **逐字符**说得出跑了谁（HARDEN-1 I-1）。

    旧断言 `startswith("caller_capability:") and "_capability" in via` 第二把尺恒真
    （前缀自带 `_capability`），评审席注毒"via 砍成常量前缀"实测全绿。现改等值：
    期望值从注入的成品对象现读，判据真身住中央门件（本件只引用、不复制拼接逻辑）。
    """
    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    result = _private_invoker(cid, _derived_handler(cid)).invoke(
        _request(cid, capability=fake)
    )
    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], f"{cid}: 成品没被执行＝中央另跑了一条"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "装配现场那一个", (
        f"{cid}: 信封里的呈现不是成品吐出的那份：{presented}"
    )
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，"
        f"应为 {expected_via(fake)!r}"
    )


@pytest.mark.parametrize("cid", PREPARED_IDS)
def test_prepared_without_capability_is_unavailable_and_never_rebuilds(
    cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺成品 ⇒ UNAVAILABLE + 点名在册真身；并且**装一颗会炸的桩**证明它真没去 import 自建。

    与"detail 里有 builder 名"相比，桩才是活性证据：只查文案会放过"文案说没自建、实际自建了"。
    """
    _ref, dotted, symbol = _ref_parts(cid)
    monkeypatch.setitem(sys.modules, dotted, _raising_stub(dotted, symbol))

    calls: list[str] = []
    result = _private_invoker(cid, _derived_handler(cid)).invoke(
        # context 里刻意不放 capability（放一个也只用于计数：它不该被跑到，更不该被换成自建）
        _request(cid, capability=None)
    )
    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"{cid}: 缺执行体给出 {result.status}＝偷偷按 ref 自建了一条第二通路"
    )
    assert symbol in result.detail, f"{cid}: detail 没点名本该成交品的真身：{result.detail}"
    assert cp.PRESENTATION_DATA_KEY not in result.data
    assert calls == []


# ===========================================================================
# ⑦ command 形：同样两件事，但**允许**按 ref 自建（与 prepared 的唯一文档差异）
# ===========================================================================
@pytest.mark.parametrize("cid", COMMAND_IDS)
def test_command_prefers_the_injected_capability_over_rebuild(
    cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注入优先：就算 ref 那边"能自建"，交来了就必须跑交来的那一个（自建是兜底不是首选）。"""
    _ref, dotted, symbol = _ref_parts(cid)
    # 桩会炸 ⇒ 一旦"在册说交成品、实跑自建"立刻红（比断言 via 更硬）。
    monkeypatch.setitem(sys.modules, dotted, _raising_stub(dotted, symbol))

    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    result = _private_invoker(cid, _derived_handler(cid)).invoke(
        _request(cid, capability=fake)
    )
    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["装配现场那一个"], f"{cid}: 交来的成品没被执行"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "装配现场那一个", presented
    # 同 I-1 口径：命令形注入分支的 via 也必须逐字符等于注入件全身份（常量前缀毒同红）。
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


@pytest.mark.parametrize("cid", COMMAND_IDS)
def test_command_rebuild_from_ref_is_allowed_and_threaded(
    cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没交成品 ⇒ 命令形**可以**按 `implementation_ref` 自建（这是它与 prepared 形的文档差异）。

    取简报给的 (a) 方案：不跑真 builder。真 builder 要吃真 config 并可能触网/触渲染引擎，
    离线单测里跑它既不确定也不安全。故把 ref 指向的模块换成 `sys.modules` 里的桩，
    只验三件事：①自建分支确实被走到（via == 在册符号名）；②`_config_of(request)` 把
    context 里那枚 config **原样**交给了 builder（对象同一性，不是新建第二份）；
    ③自建产物被照常执行并回填呈现载荷。桩只在本次 invoke 期间存在（monkeypatch 负责还原），
    对同名单例与其它测试件零残留。
    """
    _ref, dotted, symbol = _ref_parts(cid)
    seen_config: list[object] = []
    calls: list[str] = []

    stub = ModuleType(dotted)

    def _builder(config: object) -> object:
        seen_config.append(config)

        def _capability(message: object, decision: object) -> object:
            calls.append("自建那一个")
            return _presented(cid, "自建那一个")

        return _capability

    setattr(stub, symbol, _builder)
    monkeypatch.setitem(sys.modules, dotted, stub)

    sentinel = SimpleNamespace(marker="matrix-config")
    result = _private_invoker(cid, _derived_handler(cid)).invoke(
        _request(cid, capability=None, config=sentinel)
    )
    assert result.status is cp.InvocationStatus.OK, (
        f"{cid}: 命令形缺成品时未按 ref 自建（差异分支被削平＝与 prepared 混同）：{result.detail}"
    )
    assert result.via == symbol, f"{cid}: via 没说是按哪个符号自建：{result.via}"
    assert seen_config == [sentinel], f"{cid}: 自建时没把 context 的 config 交给 builder"
    assert calls == ["自建那一个"], f"{cid}: 自建产物没被执行：{calls}"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "自建那一个", presented


# ===========================================================================
# ⑧ 非空转守卫：矩阵不得静默缩小；判据本身要有牙
# ===========================================================================
def _coverage_violations(
    collected: dict[str, str], declared: dict[str, str]
) -> list[str]:
    """矩阵覆盖面判据（合成输入与真值共用同一份，杜绝"注毒验的是另一条没人走的路"）。"""
    violations: list[str] = []
    if len(declared) < len(collected):
        violations.append(
            f"取数口现算 {len(declared)} 枚 < 采集期参数化 {len(collected)} 枚＝源头被改名/删表"
        )
    uncollected = sorted(set(declared) - set(collected))
    if uncollected:
        violations.append(f"这些在册 id 没被矩阵收到（改名后留洞）：{uncollected}")
    drifted = sorted(cid for cid in collected if declared.get(cid) != collected[cid])
    if drifted:
        violations.append(f"执行形与采集期不一致（形态翻面须重采）：{drifted}")
    for adapter in sorted(cp._KNOWN_ADAPTERS):
        if not any(value == adapter for value in collected.values()):
            violations.append(f"名册里的 {adapter} 形没有任何用例覆盖＝对应判据在空转")
    return violations


def test_matrix_covers_every_declared_capability() -> None:
    """矩阵现在必须仍覆盖唯一表声明的**全部** id（枚数现算，与采集期比对）。"""
    declared = cp._route_execution_adapters()
    assert declared, "唯一表一枚执行形都没有＝整条接入面消失，本矩阵不得以'全绿'报太平"
    violations = _coverage_violations(ADAPTER_OF, declared)
    assert not violations, "；".join(violations)


def test_coverage_guard_is_not_toothless() -> None:
    """注毒：少一枚 / 多一枚（改名）/ 形态翻面 / 抽掉一种形态，四种世界都必须被点名。"""
    base = dict(ADAPTER_OF)
    one = next(iter(base))
    probe_adapter = base["bot.weather"]

    assert _coverage_violations(base, {k: v for k, v in base.items() if k != one}), "少一枚没红"
    renamed = dict(base)
    renamed.pop(one)
    renamed["bot.brand_new_row"] = probe_adapter
    assert _coverage_violations(base, renamed), "id 被改名没红（矩阵对新 id 失明）"
    flipped = dict(base)
    flipped[one] = "command" if probe_adapter == "prepared" else "prepared"
    assert _coverage_violations(base, flipped), "执行形翻面没红"
    only_one_shape = {k: v for k, v in base.items() if v == probe_adapter}
    assert _coverage_violations(only_one_shape, only_one_shape), "一种形态整批消失没红（判据空转）"
    assert _coverage_violations(base, base) == [], "干净现状被自己判红＝守卫不可信"
