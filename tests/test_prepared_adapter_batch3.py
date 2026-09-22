"""prepared 执行形 P8 批（S-PREP-B3）的登记与活性锁（逐枚参数化，全离线）。

为什么单开一件（而不是塞进 canary/batch1/batch2/缺口账）：canary 只管金丝雀 `bot.weather`
与「每一条生产入口都汇到缝」那条不变量，batch1 管 P1 十枚、batch2 管 P2 一枚，
`test_descriptor_wiredness_ledger` 只管"账面缺口 −N"这个数字。本件管的是**兜底引导席**这一枚：
它的执行体在根里是一条内联闭包、全树没有具名 config 形工厂，所以"命令形按 ref 自建"
在结构上就不成立；而它历史上被一把 `title` 判据挡在名册外（S-PREP-B2 实测），
那把判据今天已由 `title=decl.label or decl.value` 一行修解除（并由
`tests/test_prepared_adapter_canary.py::test_row_without_human_label_still_derives_a_title`
常驻钉住）。本件把"解除之后确实通电"钉成实账。

与 batch1/batch2 同一核心判据：不看"能不能跑"，看
"**跑的就是装配现场交来的那一个**"，且"没交来 ⇒ UNAVAILABLE，绝不偷偷按 ref 自建"。

真身生产可达性（证明登记不是假绿）：根 `__init__.py:8568-8578`
`_handle_ignore_guide` → `_run_simple_capability(bot, event, lambda cfg: lambda message,
_decision: build_ignore_guide_result(message.request_id), "bot.ignore", ignore_guide)`，
而 `_run_simple_capability`（:8432-8455）体内把
`orchestrated_command(capability_id, capability_factory(config), config)` 喂进
`pipeline.handle_async` ⇒ 成品在调用点就交进了中央缝。本件另有 (g) 节把**同批实测拒登**的
六枚（走根泛型执行器、不经缝）钉成"仍不得有执行面"，防后来者照抄本批手法造出假绿。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

#: via 全身份等值判据 + 根汇缝字面量抽取的唯一真身（HARDEN-1 I-1/I-2）：
#: 批次件只引用、不复制拼接/扫描逻辑（本件旧版内联 AST 判据已收编至中央门件）。
from test_central_via_identity_and_entry_durability import (
    expected_via,
    root_funnel_literal_cids,
)

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: P8 批本轮登记的 1 枚。implementation_ref 尾段=在册真身符号，
#: (d) 用它断言"缺成品时诚实点名本该由谁交成品"，(a′) 用它的活签名证 prepared 形唯一可选。
BATCH3: tuple[tuple[str, str], ...] = (
    ("bot.ignore", "build_ignore_guide_result"),
)
CIDS = tuple(cid for cid, _ in BATCH3)
_BUILDER = dict(BATCH3)

#: 同批**实测拒登**的六枚：生产走根泛型执行器 `pipeline.handle_async(capability_id=...)`、
#: 不经 `_run_simple_capability`/`orchestrated_command` ⇒ 给它们填 execution 只会把缺口账
#: 翻成 WIRED 而生产零变化（本波最该拦的假绿）。拒登判据与复跑见
#: `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-PREP-B3.md`。
REFUSED_THIS_BATCH = (
    "bot.meme_library",
    "bot.group_info",
    "bot.content",
    "bot.music",
    "bot.today_history",
    "bot.media_archive",
)

# 建请求走这个引用：下面有条用例会把 cp.CapabilityRequest 换成假构造器（模拟装配现场没交
# 成品），若本件自己也按模块属性取类，就会套娃调用自己（canary/batch1 同型教训）。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(cid: str, body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-pb3",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["prepared-batch3"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是根 :8573 那条内层 lambda）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(cid, body)

    return _capability


def _request(cid: str, capability: object | None) -> cp.CapabilityRequest:
    context: dict[str, object] = {"config": SimpleNamespace(), "decision": SimpleNamespace()}
    if capability is not None:
        context["capability"] = capability
    return _REAL_REQUEST(
        capability_id=cid,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-pb3")},
        principal="3865067623",
        roles=("user",),
        request_id="req-pb3",
        session_key="private:3865067623",
        context=context,
    )


def _message(cid: str) -> SimpleNamespace:
    return SimpleNamespace(request_id="req-pb3", text=cid, session_key="private:9", sender_id="9")


def _decl(cid: str) -> object:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    rows = [d for d in reg.ROUTE_CAPABILITY_DECLARATIONS if d.capability_id == cid]
    assert len(rows) == 1, f"{cid} 在册 {len(rows)} 行＝执行面归属会歧义"
    return rows[0]


def _import_ref_symbol(implementation_ref: str) -> object:
    module_path, _, symbol = implementation_ref.partition("#")
    assert symbol, f"implementation_ref 缺符号段：{implementation_ref}"
    import importlib

    package_path = module_path[: -len(".py")].replace("/", ".")
    assert package_path.startswith("plugins.bot_unified_runtime."), package_path
    return getattr(importlib.import_module(package_path), symbol)


# --------------------------------------------------------------------- (a) 登记面
@pytest.mark.parametrize("cid", CIDS)
def test_row_declares_prepared_shape(cid: str) -> None:
    """在册：执行形必须是 prepared（不是 command、不是没填），且名册里有 prepared。"""
    adapters = cp._route_execution_adapters()
    assert adapters.get(cid) == "prepared", (
        f"{cid} 执行形漂移为 {adapters.get(cid)!r}＝没登记成 prepared（登记假绿或被别的席改回）"
    )
    assert "prepared" in cp._KNOWN_ADAPTERS, "壳侧适配器名册没有 prepared＝地基被拆"


@pytest.mark.parametrize("cid", CIDS)
def test_internal_seat_derives_a_title_without_a_label(cid: str) -> None:
    """兜底席 label="" 仍能派生出非空 title——这正是本枚今天才可登记的前提。

    立门前因（S-PREP-B2 实测）：旧派生 `title=decl.label` 让空标签行撞
    `validate_registry`「bot.ignore: title 缺失」，**全表**跟着红。今天派生器走
    `label or value`。本锁同时钉住"不许反过来给内部席位手写 label"——那会顶漂
    `scripts/board_doc_sync.py` 的生成页（B2 实测 3 页 DRIFT），属越界改法。
    """
    decl = _decl(cid)
    assert decl.label == "", (
        f"{cid} 的 label 被填成了 {decl.label!r}＝用改在册事实绕派生判据，"
        "正解在壳侧兜底（canary::test_row_without_human_label_still_derives_a_title）"
    )
    descriptor = next(
        d for d, _adapter in cp._route_execution_rows() if d.capability_id == cid
    )
    assert descriptor.title.strip(), f"{cid}: 派生 title 仍为空＝validate_registry 会整表红"
    assert descriptor.title == decl.value, (
        f"{cid}: title 不再是空 label 的 value 兜底，而是 {descriptor.title!r}＝在册事实被改过"
    )


@pytest.mark.parametrize("cid", CIDS)
def test_registered_builder_is_not_command_shaped(cid: str) -> None:
    """证明①（prepared 而非 command）：在册真身的活签名首参**不是 config**。

    命令形的定义是「builder 吃 config、壳可自建」。本枚 ref 指向
    `build_ignore_guide_result(request_id: str, *, guidance: str | None = None)`——
    首参是运行期 request_id，壳拿不到它 ⇒ 按 ref 自建在结构上不成立，只能 prepared。
    全树亦不存在 `build_ignore_capability(config)` 这样的具名工厂（根 :8573 是内联闭包）。
    """
    execution = _decl(cid).execution
    assert execution is not None
    symbol = _import_ref_symbol(execution.implementation_ref)
    signature = inspect.signature(symbol)
    first = next(iter(signature.parameters.values()))
    assert first.name != "config", (
        f"{cid}: ref 真身首参变成 {first.name!r}＝它已可命令形重建，本锁与登记形需同步重判"
    )
    required = [
        p.name for p in signature.parameters.values() if p.default is inspect.Parameter.empty
    ]
    assert required, f"{cid}: ref 真身无必填运行期参数＝命令形可能成立"


@pytest.mark.parametrize("cid", CIDS)
def test_root_has_a_seam_site_naming_this_capability(cid: str) -> None:
    """证明②（生产可达，离线静态判据）：根里确有**字面点名把该枚交进汇缝函数**的站点。

    HARDEN-1 I-2：判据从"根文件里出现字面量"升为"汇缝函数调用点上字面点名"（弱尺在
    字面量被搬进注释/别的字符串时也放行）；抽取真身住中央门件，本锁与
    `test_descriptor_wiredness_ledger` 的常驻入口耐久锁同源同判据。
    "每一条入口都汇缝、无旁路"的活性由 canary 的多入口活性锁负责。
    """
    assert cid in root_funnel_literal_cids(), (
        f"根里已没有把 {cid} 字面点名交进汇缝的站点＝登记前提消失，先撤账再改根"
    )


@pytest.mark.parametrize("cid", CIDS)
def test_declared_config_keys_are_real_config_fields(cid: str) -> None:
    """证明③（零幽灵键）：config_keys 每一枚都在 `Config.model_fields` 里。"""
    from plugins.bot_unified_runtime.config import Config

    execution = _decl(cid).execution
    assert execution is not None
    fields = set(Config.model_fields)
    ghosts = [key for key in execution.config_keys if key not in fields]
    assert not ghosts, f"{cid}: config_keys 含幽灵键 {ghosts}"


@pytest.mark.parametrize("cid", CIDS)
def test_timeout_is_within_the_central_ceiling(cid: str) -> None:
    """证明④（超时的界内一侧）：0 < timeout ≤ `_MAX_TIMEOUT_SECONDS`，且明显高于纯内存内层。

    「严格高于内层预算」的算术与依据写在本行 `timeout_seconds` 上方的注册册注释里
    （内层≈0.01s：无网络/无 LLM/不出卡，只走进程内取句轮转）；本锁钉的是可机判的那半：
    不许越 600s 硬顶、不许 ≤0（越界会在 `validate_registry` 炸整表，这里提前点名到人）。
    """
    execution = _decl(cid).execution
    assert execution is not None
    ceiling = cp._MAX_TIMEOUT_SECONDS
    assert 0 < execution.timeout_seconds <= ceiling, (
        f"{cid}: timeout {execution.timeout_seconds} 越界（0, {ceiling}]＝描述符完整性校验会整表红"
    )


# --------------------------------------------------------------------- (b) 派生面
@pytest.mark.parametrize("cid", CIDS)
def test_prepared_row_gets_a_handler_from_derivation(cid: str) -> None:
    """派生同源：prepared 行必须真的派生出 handler，不许只登记不实现信封。"""
    handlers = cp.default_invoker().handlers
    assert handlers.get(cid) is not None, (
        f"{cid}: adapter=prepared 已登记却没派生出 handler＝半批施工，"
        "中央件会在 import 期炸、缺口账门会静默变哑"
    )


# --------------------------------------------------------------------- (c) 活性：跑的就是交来那一个
@pytest.mark.parametrize("cid", CIDS)
def test_seam_runs_the_injected_capability_not_a_rebuild(cid: str) -> None:
    """核心判据（缝侧）：中央跑的就是调用方交来那一个成品，没被 `ref` 自建偷偷替换。"""
    calls: list[str] = []
    fake = _assembled(cid, "装配现场那一个", calls)
    step = cp.orchestrated_command(cid, fake, SimpleNamespace())
    result = step(_message(cid), SimpleNamespace(actor_roles=("user",)))

    assert calls == ["装配现场那一个"], f"{cid}: 成品没被执行＝中央另跑了一条（丢注入的第二通路）"
    assert result.body == "装配现场那一个", f"{cid}: 返回的呈现不是成品吐出的那份：{result}"
    assert result.capability_id == cid, f"{cid}: 呈现结果串了能力 id：{result.capability_id}"


@pytest.mark.parametrize("cid", CIDS)
def test_invoker_runs_injected_capability_and_reports_via(cid: str) -> None:
    """活性（invoker 侧）：交进成品 ⇒ OK 且 via **逐字符**说得出跑的是谁（HARDEN-1 I-1）。"""
    calls: list[str] = []
    fake = _assembled(cid, "成品", calls)
    result = cp.default_invoker().invoke(_request(cid, fake))
    assert result.status is cp.InvocationStatus.OK, result.detail
    assert calls == ["成品"], f"{cid}: 成品没被执行"
    presented = result.data.get(cp.PRESENTATION_DATA_KEY)
    assert isinstance(presented, dict) and presented.get("body") == "成品", f"{cid}: {presented}"
    # 旧尺 `"_capability" in via` 恒真（前缀自带），常量前缀注毒实测全绿——改等值，
    # 判据真身与注毒自证见 test_central_via_identity_and_entry_durability。
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


# --------------------------------------------------------------------- (d) 缺成品 ⇒ UNAVAILABLE，绝不自建
@pytest.mark.parametrize("cid", CIDS)
def test_without_injected_capability_is_unavailable_never_rebuilt(cid: str) -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail（点名在册真身）；绝不允许退回按 ref 自建。"""
    result = cp.default_invoker().invoke(_request(cid, None))
    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"{cid}: 缺执行体却给出 {result.status}＝中央可能偷偷按 ref 自建了一条第二通路"
    )
    assert "prepared" in result.detail, result.detail
    assert _BUILDER[cid] in result.detail, (
        f"{cid}: detail 没带在册真身符号，事后无从判断本该由谁交成品：{result.detail}"
    )
    assert cp.PRESENTATION_DATA_KEY not in result.data


@pytest.mark.parametrize("cid", CIDS)
def test_seam_without_capability_makes_no_direct_call(cid: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """缝侧两态：交不进成品 ⇒ 温和短句 + 终态入审计，且**绝不解封直调成品**（不越过中央）。"""
    calls: list[str] = []
    fake = _assembled(cid, "成品", calls)
    step = cp.orchestrated_command(cid, fake, SimpleNamespace())
    monkeypatch.setattr(cp, "CapabilityRequest", lambda **_kw: _request(cid, None))
    blocked = step(_message(cid), SimpleNamespace(actor_roles=("user",)))

    assert calls == [], f"{cid}: 拿不到 context 成品却直接解封调用＝绕过中央 invoker"
    assert str(getattr(blocked, "body", "")).strip(), f"{cid}: 中央拦下后返回空体＝用户侧静默丢回复"
    tags = list(getattr(blocked, "audit_tags", ()) or ())
    assert any("unavailable" in tag for tag in tags), f"{cid}: 终态没进审计：{tags}"


# ------------------------------------------------------------------ (e) 拒登现状锁
def test_refused_rows_still_declare_no_execution() -> None:
    """本批实测拒登的六枚必须仍然没有执行面——这是判据，不是遗留。

    判据（可复跑）：AST 扫根，`_run_simple_capability` / `_run_capability_through_pipeline`
    的字面 cid 集里**没有**这六枚；它们的 `pipeline.handle_async(..., capability_id=…)`
    直呼站点分别在 content :8278 / music :8336 / today_history :1862+:8400 /
    media_archive :8662 / meme_library :8733 / group_info :8507（S-PREP §3.2 早先记的
    :8719/:8494 已被后续波次顶漂，本锁按现树实况写）。谁在改根之前先给它们填 execution，
    `seam_registered_cids()` 就会把账面翻成 WIRED 而生产零变化＝本门最该拦的假绿。
    """
    adapters = cp._route_execution_adapters()
    for cid in REFUSED_THIS_BATCH:
        assert cid not in adapters, (
            f"{cid} 长出执行面（adapter={adapters.get(cid)!r}）但生产仍走根泛型执行器＝假绿；"
            "请先在根里把成品包进 orchestrated_command，再按本批 (a)-(d) 四证重登记"
        )


def test_root_seam_cid_set_matches_this_batches_claim() -> None:
    """拒登判据的机判那一半：这六枚确实不在根的汇缝 cid 集里，而 bot.ignore 在。

    只扫字面量：动态 cid（别名/自然语言那几条把解析结果交进来的站点）本就不该进这个判据，
    它的活性由 canary 那条常驻锁负责。HARDEN-1 I-2：本判定原先自带一份内联 AST 扫描
    （全树第二支同型扫描器），现收编为中央门件 `root_funnel_literal_cids` 的再导出委托；
    "全部在册执行形都必须有此站点"的常驻执法已上提
    `test_descriptor_wiredness_ledger.py`，本件从此退役也不会带走这条判据。
    """
    seam_cids = root_funnel_literal_cids()
    assert "bot.ignore" in seam_cids, "根已不再把 bot.ignore 交进缝＝本批登记的前提没了，先撤账再改根"
    bypassing = sorted(set(REFUSED_THIS_BATCH) & seam_cids)
    assert not bypassing, f"这六枚已汇进缝（{bypassing}）：本锁前提变了，按四证重判是否登记"
