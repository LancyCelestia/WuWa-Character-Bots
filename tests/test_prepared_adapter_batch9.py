"""prepared 执行形 P9 批（bot.music_mode）的逐枚活性证与拒登现状锁（全离线）。

立件因由（S66，2026-09-24）：主代理 00:15Z 把 `bot.music_mode` 以 **prepared** 形登记进
`domains/chat_reply/runtime/capability_registry.py` 的 MUSIC_MODE 行（根零改动、净 0 行），
并在 `tests/test_descriptor_wiredness_ledger.py` 把该枚从 NOT_WIRED 移入 WIRED、
`GAP_CEILING 95→94`。该 WIRED 行自己的注记写明「本枚**暂无**逐枚活性证件（PARKED `CM-P-21`）」
——本件就是欠的那张证：把「跑的就是装配现场交来的那一个、缺成品 ⇒ UNAVAILABLE 绝不自建」
从**未执法**做成**在册已执法**。

判据结构照抄 batch3（同源纪律）：via 全身份等值 + 根汇缝字面量抽取走中央门件
`test_central_via_identity_and_entry_durability.expected_via / root_funnel_literal_cids`
——**本件只引用、不复制**拼接/扫描逻辑（HARDEN-1 I-1/I-2 立的规矩）。

真身生产可达性（证明登记不是账面假绿）：三条入口全部经根汇合函数
`_run_capability_through_pipeline`（`plugins/bot_unified_runtime/__init__.py:2568-2571`
在汇合点 `orchestrated_command(capability_id, capability, config)` 包缝）——
①命令 matcher `_handle_music_mode`（root :6985-7020，字面 `capability_id="bot.music_mode"` :7013）；
②别名链分支 root :6827-6843；③自然语言链分支 root :8978-8994。
执行体是内联闭包：吃装配期句柄 `runtime_settings` 与事件解析出的 `mode`、
决策期 `actor_roles` ⇒ 命令形「builder 只吃 config、壳可自建」在结构上不成立，prepared 唯一。

与 batch3 的一个诚实差异（(g) 节据此分两组写）：同批实测不该照抄本手法的八枚里，
六枚（content/music/today_history/media_archive/meme_library/group_info）走根泛型执行器、
**不在**根汇缝字面量集里；另两枚（`bot.mail.control`/`bot.auto_send.preview`）**已在**
汇缝字面量集（root :6479/:6491/:6511/:7861）却**没有 RouteKind 宿主行**＝注册册里
无处填 execution——它们的卡点不是「没汇缝」而是「没宿主行」，本件两组分开钉。
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:  # 只为 mypy 收紧 `_decl` 返回型（batch3 的 object 返回会撞 attr-defined）
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.capability_registry import (
        RouteCapabilityDecl,
    )

#: via 全身份等值判据 + 根汇缝字面量抽取的唯一真身（HARDEN-1 I-1/I-2）：
#: 批次件只引用、不复制拼接/扫描逻辑（与 canary/batch1/batch2/batch3 同一纪律）。
from test_central_via_identity_and_entry_durability import (
    expected_via,
    root_funnel_literal_cids,
)

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: P9 批本轮登记的 1 枚。implementation_ref 尾段=在册真身符号，
#: (d) 用它断言"缺成品时诚实点名本该由谁交成品"，(a′) 用它的活签名证 prepared 形唯一可选，
#: (d′) 用它钉"ref 指到的就是真身本人"（防"在册说 A、ref 写 B"的 provenance 漂移）。
BATCH9: tuple[tuple[str, str], ...] = (
    ("bot.music_mode", "build_music_mode_result"),
)
CIDS = tuple(cid for cid, _ in BATCH9)
_BUILDER = dict(BATCH9)

#: (g) 组一：S-SEAM-ROOT（批④）后**已汇缝但未登记执行形**的六枚——根经
#: `_run_capability_through_pipeline` 把成品交进 `orchestrated_command`，未在册 ⇒ 原样
#: 直呼、行为不变。给它们填 execution 而缺 (a)-(d) 四证＝账面 WIRED 而执行形无人验过
#: （batch3 同判据，名单为断言数据、非判据真身，允许与 batch3 各留一份；
#: 两处若漂移由本件 (f) 与 ledger §5 各自点名）。
REFUSED_ROOT_GENERIC = (
    "bot.meme_library",
    "bot.group_info",
    "bot.content",
    "bot.music",
    "bot.today_history",
    "bot.media_archive",
)

#: (g) 组二：已在根汇缝字面量集、却**没有 RouteKind 宿主行**的两枚——注册册路由表按行派生
#: execution，无行即无处可填；要「登记」必须先伪造宿主行＝双假账，故本件同时钉
#: 「无执行面」与「无宿主行」两条。
REFUSED_NO_HOST_ROW = ("bot.mail.control", "bot.auto_send.preview")

# 建请求走这个引用：下面有条用例会把 cp.CapabilityRequest 换成假构造器（模拟装配现场没交
# 成品），若本件自己也按模块属性取类，就会套娃调用自己（canary/batch1-3 同型教训）。
_REAL_REQUEST = cp.CapabilityRequest


def _presented(cid: str, body: str) -> object:
    """真·呈现契约对象（层 1 类型）——缝会 `model_validate` 信封里的 dict，替身骗不过去。"""
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id="req-pb9",
        capability_id=cid,
        kind="text",
        body=body,
        audit_tags=["prepared-batch9"],
    )


def _assembled(cid: str, body: str, calls: list[str]):
    """模拟"装配现场造出来的成品"（真身里是根 :6994/:6835/:8986 那三条内联闭包）。"""

    def _capability(message: object, decision: object) -> object:
        calls.append(body)
        return _presented(cid, body)

    return _capability


def _request(cid: str, capability: object | None) -> cp.CapabilityRequest:
    # context 与生产装配现场逐字同形：`capability_protocols.orchestrated_command` 汇缝交的是
    # config/decision/capability **三槽全集**（capability_protocols.py:2158），本件照抄该形态。
    # 缺成品时 capability 槽给 None——中央 `_make_prepared_handler` 用 `context.get("capability")`
    # + `callable()` 判定，None 与键缺失在两分支上逐字等价 ⇒ 行为零改变。
    # （S79）不再手抄 "config"/"decision" 双槽子集 dict：这两个键名与
    # domains/chat_reply/runtime/aliases.py `DEFAULT_VERB_MAP` 的词面同形，两键字面量整集
    # ⊆ 真身即触发词副本棘轮（test_trigger_word_copy_ratchet）的 ruleB 债——09-24 该门
    # 82>81 的恰一枚增量就是它；三槽全形含非词表键 "capability"，不构成子集，债归零。
    context: dict[str, object] = {
        "config": SimpleNamespace(),
        "decision": SimpleNamespace(),
        "capability": capability,
    }
    return _REAL_REQUEST(
        capability_id=cid,
        payload={"message": SimpleNamespace(sender_id="3865067623", request_id="req-pb9")},
        principal="3865067623",
        roles=("user",),
        request_id="req-pb9",
        session_key="private:3865067623",
        context=context,
    )


def _message(cid: str) -> SimpleNamespace:
    return SimpleNamespace(request_id="req-pb9", text=cid, session_key="private:9", sender_id="9")


def _decl(cid: str) -> RouteCapabilityDecl:
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    rows = [d for d in reg.ROUTE_CAPABILITY_DECLARATIONS if d.capability_id == cid]
    assert len(rows) == 1, f"{cid} 在册 {len(rows)} 行＝执行面归属会歧义"
    return rows[0]


def _import_ref_symbol(implementation_ref: str) -> object:
    module_path, _, symbol = implementation_ref.partition("#")
    assert symbol, f"implementation_ref 缺符号段：{implementation_ref}"
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
def test_registered_builder_is_not_command_shaped(cid: str) -> None:
    """证明①（prepared 而非 command）：在册真身的活签名证明"命令形重建"不成立。

    `build_music_mode_result(store, config, *, mode, actor_roles, request_id=None)`：
    首参是装配期句柄 `store`（生产传 `runtime_settings`，见根 :6996），不是 config；
    keyword-only 必填 `mode`（从 event 文本现解）与 `actor_roles`（决策期事实）
    ⇒ 壳按 ref 用 config 自建在结构上不成立（命令形 handler 会 `builder(config)(...)`，
    第一个位置参数就被绑错，产物也根本不是 `(message, decision)` 闭包）。
    判据取"名无关"的那两条（首参名≠config、必填参数存在），加一条本枚特有的
    "运行期必填件点名"——真身若将来重构成吃 config 的命令形工厂，本锁必红，逼着重判登记形。
    """
    execution = _decl(cid).execution
    assert execution is not None
    symbol = _import_ref_symbol(execution.implementation_ref)
    signature = inspect.signature(cast(Callable[..., Any], symbol))
    first = next(iter(signature.parameters.values()))
    assert first.name != "config", (
        f"{cid}: ref 真身首参变成 {first.name!r}＝它已可命令形重建，本锁与登记形需同步重判"
    )
    required = [
        p.name for p in signature.parameters.values() if p.default is inspect.Parameter.empty
    ]
    assert required, f"{cid}: ref 真身无必填运行期参数＝命令形可能成立"
    assert {"mode", "actor_roles"} <= set(required), (
        f"{cid}: ref 真身不再强制运行期 mode/actor_roles（现必填 {required}）"
        "＝装配现场交成品的必要性前提变了，重判 prepared 登记"
    )


@pytest.mark.parametrize("cid", CIDS)
def test_root_has_a_seam_site_naming_this_capability(cid: str) -> None:
    """证明②（生产可达，离线静态判据）：根确有**字面点名把该枚交进汇缝函数**的站点。

    判据真身住中央门件（与 `test_descriptor_wiredness_ledger` 的入口耐久锁同源同尺）；
    "每一条入口都汇缝、无旁路"的活性由 canary 的多入口活性锁负责。
    """
    assert cid in root_funnel_literal_cids(), (
        f"根里已没有把 {cid} 字面点名交进汇缝的站点＝登记前提消失，先撤账再改根"
    )


@pytest.mark.parametrize("cid", CIDS)
def test_declared_config_keys_are_real_config_fields(cid: str) -> None:
    """证明③（零幽灵键）：config_keys 每一枚都在 `Config.model_fields` 里（本枚＝空集，如实）。"""
    from plugins.bot_unified_runtime.config import Config

    execution = _decl(cid).execution
    assert execution is not None
    fields = set(Config.model_fields)
    ghosts = [key for key in execution.config_keys if key not in fields]
    assert not ghosts, f"{cid}: config_keys 含幽灵键 {ghosts}"


@pytest.mark.parametrize("cid", CIDS)
def test_timeout_is_within_the_central_ceiling(cid: str) -> None:
    """证明④（超时的界内一侧）：0 < timeout ≤ `_MAX_TIMEOUT_SECONDS`。

    内层串行之和的算术（S66 现算，写在此而非只留在注册册注释里）：
    读法 = `extract_music_mode`（正则，µs）+ `store.get`（本地设置快照：JSON mtime 短路或
    SQLite snapshot 读，ms）+ `normalize_music_mode`/文案拼装（µs）≈ 典型 <10ms；
    写法 = 再加一次 `store.set_override`（白名单校验 + converter + SQL CAS 写，ms；
    悲观按 SQLite 锁等待 0.5s 计）。真身零网络/零 LLM/零渲染/零 ffmpeg ⇒
    悲观上界 ≈ 0.5s，30s 留 ≥60 倍余量，同表 `bot.emergency_info` 行
    （同为"本地 sqlite 读写、无网络"，registry :706-708）取同一数值，口径一致。
    中央这层预算还含共享线程池排队时间（`_get_capability_executor`），"别吊死"的顶名副其实。
    """
    execution = _decl(cid).execution
    assert execution is not None
    ceiling = cp._MAX_TIMEOUT_SECONDS
    assert 0 < execution.timeout_seconds <= ceiling, (
        f"{cid}: timeout {execution.timeout_seconds} 越界（0, {ceiling}]＝描述符完整性校验会整表红"
    )


# --------------------------------------------------------------------- (a″) 角色等值锁（复核项①入册）
@pytest.mark.parametrize("cid", CIDS)
def test_roles_floor_never_tightens_beyond_the_domain_gate(cid: str) -> None:
    """roles=("user",) 是「层 2 不改变现网拒绝行为」的等值承诺，钉成常驻锁。

    权限真身在域内：`domains/music/capabilities/music.py:449` 对**读与写两分支**都先查
    `"admin" in actor_roles`，非管理员收到的是 ADMIN_GATE_TEMPLATES 的守岸人温和拒案
    （audit tag `music_mode_denied`）。层 2 若改登 ("admin",)，普通用户会在**进域之前**
    被中央 DENIED 成另一句温和短句（orchestrated_command :2171-2178），拒案文本与审计
    归因双双漂移＝凭空收紧＋换话术。本锁四断言：
    ①在册就是 ("user",)；②user/admin/super_admin/trusted 主体都过得了层 2 秩门
    （admin-only 主体无 "user" 字面量也放行——`roles_satisfy` 是层级地板不是求交）；
    ③blocked 主体永远过不去（地板判据本体自带否决，:549-552）；④空角色（系统主体）
    由 invoker 的"空 roles 豁免"放行、域内 admin 门兜底——这条不锁在本断言里，②③足够。
    """
    descriptor = cp.default_invoker().registry.get(cid)
    assert descriptor is not None
    assert descriptor.required_roles == ("user",), (
        f"{cid}: 层 2 角色门被改成 {descriptor.required_roles!r}＝现网拒案文本与审计归因会漂移，"
        "本等值承诺（主代理登记理由：权限真身在域内自判）被单方面撕毁；要改先在评审里点名行为差分"
    )
    floor = descriptor.required_roles
    for principal in (("user",), ("admin",), ("super_admin", "admin"), ("trusted",)):
        assert cp.roles_satisfy(principal, floor), f"{cid}: 主体 {principal} 被层 2 地板误拒"
    assert not cp.roles_satisfy(("blocked",), floor), f"{cid}: blocked 主体竟过了层 2 地板"


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
    assert result.via == expected_via(fake), (
        f"{cid}: via 不是注入件的完整身份：实得 {result.via!r}，应为 {expected_via(fake)!r}"
    )


# ------------------------------------------------------- (d) 缺成品 ⇒ UNAVAILABLE，绝不自建
@pytest.mark.parametrize("cid", CIDS)
def test_without_injected_capability_is_unavailable_never_rebuilt(cid: str) -> None:
    """拿不到成品 ⇒ UNAVAILABLE + 诚实 detail（点名在册真身）+ 诚实 via；绝不允许按 ref 自建。

    via 等值（"prepared_no_capability"）是 S66 在 batch3 判据之上补强的一牙：
    注毒把缺成品分支改成"按 ref 重建再跑"后，status/via/detail 三处同时漂移，
    本锁至少两处红（batch3 只测 status/detail 时"改 OK 不改 detail"的半吊子毒能溜过去）。
    """
    result = cp.default_invoker().invoke(_request(cid, None))
    assert result.status is cp.InvocationStatus.UNAVAILABLE, (
        f"{cid}: 缺执行体却给出 {result.status}＝中央可能偷偷按 ref 自建了一条第二通路"
    )
    assert result.via == "prepared_no_capability", f"{cid}: via 漂移为 {result.via!r}"
    assert "prepared" in result.detail, result.detail
    assert _BUILDER[cid] in result.detail, (
        f"{cid}: detail 没带在册真身符号，事后无从判断本该由谁交成品：{result.detail}"
    )
    assert cp.PRESENTATION_DATA_KEY not in result.data


@pytest.mark.parametrize("cid", CIDS)
def test_seam_without_capability_makes_no_direct_call(
    cid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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


# ------------------------------------------------------------- (d′) provenance 等值（复核项③入册）
@pytest.mark.parametrize("cid", CIDS)
def test_implementation_ref_resolves_to_the_declared_true_body(cid: str) -> None:
    """ref 尾段符号必须真解析到在册真身本人（`build_music_mode_result`），一字不差。

    prepared 形里 implementation_ref 不参与执行、只作 provenance（壳注 :2247）——
    provenance 件最容易悄悄烂掉（改名/搬文件后半截失效），所以给"它不执行"的字段
    单独上一道解析锁：(a′) 消费了解析结果但没钉"解析到的就是承诺的那枚符号"。
    """
    execution = _decl(cid).execution
    assert execution is not None
    assert execution.implementation_ref.endswith(f"#{_BUILDER[cid]}"), execution.implementation_ref
    from plugins.bot_unified_runtime.domains.music.capabilities import music

    assert _import_ref_symbol(execution.implementation_ref) is music.build_music_mode_result, (
        f"{cid}: ref 解析到的对象 ≠ 承诺真身＝provenance 漂移"
    )


# ------------------------------------------------------------------ (e) 未登记现状锁（g 两组）
def test_refused_root_generic_rows_still_declare_no_execution() -> None:
    """组一（已汇缝但未登记执行形的六枚）必须仍然没有执行面——这是判据，不是遗留。

    实况（S-SEAM-ROOT 批④）：根汇缝字面量站点已由本件 (g) 的汇缝断言钉住；
    直呼只余调度器自造文本腿（坐标注记见 batch3 (e)）。谁在补做 (a)-(d) 四证之前
    先给它们填 execution，账面翻 WIRED 而执行形无人验过＝本门最该拦的假绿。
    """
    adapters = cp._route_execution_adapters()
    for cid in REFUSED_ROOT_GENERIC:
        assert cid not in adapters, (
            f"{cid} 长出执行面（adapter={adapters.get(cid)!r}）但组一未过 (a)-(d) 四证＝假绿；"
            "请先补四证并同步缺口账，再连同 batch3/本件两把汇缝断言一起按实况改登记"
        )


def test_refused_no_host_row_cids_have_no_execution_and_no_route_row() -> None:
    """组二（已汇缝但无 RouteKind 宿主行的两枚）：无执行面 + 无宿主行，双钉。

    实况（S66 现算 2026-09-24，00:24Z 探针）：这两枚**在**根汇缝字面量集里
    （mail.control root :6479/:6491/:6511、auto_send.preview :7861）——卡点与组一不同：
    注册册 execution 只能挂在 RouteKind 声明行上，它们没有宿主行＝结构上无处可填。
    要「登记」必先伪造一条 RouteKind 行（把不存在的命令路由无中生有）＝双重假账，
    故本锁同时钉"无执行面"与"无宿主行"。哪天有人真补了宿主行＋根路由，本锁红＝信号，
    按 (a)-(d) 四证重判，不许顺手删锁。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
        capability_registry as reg,
    )

    adapters = cp._route_execution_adapters()
    route_rows = {d.capability_id for d in reg.ROUTE_CAPABILITY_DECLARATIONS}
    for cid in REFUSED_NO_HOST_ROW:
        assert cid not in adapters, (
            f"{cid} 长出 route 执行面（adapter={adapters.get(cid)!r}）＝先伪造宿主行再填 execution"
            "的假绿路径已被打开，停：按四证重判并同步缺口账"
        )
        assert cid not in route_rows, (
            f"{cid} 出现了 RouteKind 宿主行＝本锁前提（结构上无处填 execution）已被推翻；"
            "若确已补路由，请连根入口一起复核后改登记，不是只改本锁"
        )


def test_root_seam_cid_set_matches_this_batches_claim() -> None:
    """汇缝字面量集的三方对账（只扫字面量，动态 cid 交 canary 多入口锁管）。

    ①本枚 bot.music_mode 在集里（登记前提）；②组一六枚**在**集里（S-SEAM-ROOT 批④
    实况——旧断言"不在集里"的当时前提已被根改动推翻，翻面后钉住新实况：谁把它们
    挪回裸直呼而账面仍称汇缝，本锁当场红；与 batch3 (g) 同判据同源尺）；
    ③组二两枚**在**集里——把它们钉成"在"，是防两头的漂移：
    哪天根把它们挪出汇缝（本锁红＝实况变了），或哪天有人拿"它已汇缝"当借口绕过宿主行
    判据硬塞执行面（上一条锁接住）。三组断言各点各的名，归因不混。
    """
    seam_cids = root_funnel_literal_cids()
    assert "bot.music_mode" in seam_cids, (
        "根已不再把 bot.music_mode 交进汇缝＝本批登记的前提没了，先撤账再改根"
    )
    off_seam = sorted(set(REFUSED_ROOT_GENERIC) - seam_cids)
    assert not off_seam, (
        f"组一六枚里有 {off_seam} 离开了根汇缝字面量站点：S-SEAM-ROOT 前提被挪回直呼＝漂移，"
        "要么恢复汇缝站点，要么连同 batch3/本件 (e) 与缺口账按实况改登记，不许只留注释"
    )
    on_seam = sorted(set(REFUSED_NO_HOST_ROW) - seam_cids)
    assert not on_seam, (
        f"组二两枚里有 {on_seam} 离开了根汇缝字面量站点：本件 (e)/(g) 两锁的实况注记需同步改写"
    )
