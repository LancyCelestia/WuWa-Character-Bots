"""「管线管理形」（pipeline_managed）第三种执行形态的常驻门（2026-09-22 调度层本波）。

任务钉死（HANDOFF-FIXWAVE §10 / HANDOFF-UNIFY §1 处理顺序第 3 条）：给中央调度层新增一种
能包裹 `pipeline.handle_async` 的适配器，使 bot.chat 主链 / 订阅 outbox / campus 转发 /
运维告警这几条「层 1 直呼面」也能在中央描述符表 `CAPABILITY_DESCRIPTOR` 里**登记并有真实
execution、走 default_invoker().invoke**。做完 `/bot status` 显示它们「在册」的含义从
「只有声明没有执行体」升级为「经中央调度层」。

四条不变量（各自可单独归因，见注毒）：
- INV-REGISTER  四枚都在 CAPABILITY_DESCRIPTOR、family=PIPELINE、handler_ref 非空、
                default_invoker 挂了信封 handler（=有真实执行体），且**不进**
                `_route_execution_adapters()`（=缺口账对它们仍按 generic/not_wired 现算，
                诚实不记通电：能跑 ≠ 已接）。
- INV-EXECUTE   invoke 真的驱动**调用方交来的那一个** pipeline.handle_async（传对
                capability_id），回执投影进信封；缺 pipeline 句柄 ⇒ 诚实 UNAVAILABLE，
                **绝不自建 RuntimePipeline**（禁第二通路红线）。
- INV-FAMILY    COMMAND 族计数仍 == len(_route_execution_rows())（管线管理形不污染那条锁）。
- INV-STATUS    /bot status 有一行「管线管理形在册」，内容由中央件现算、fail-open。

全离线：真身 pipeline/RootRuntime 一律不触网、不发消息；用假 pipeline 句柄驱动 handler。
"""

from __future__ import annotations

import inspect

import pytest

from plugins.bot_unified_runtime.runtime import capability_protocols as cp

#: 任务点名的「层 1 直呼面」中，走 `pipeline.handle_async` 且未被禁改现状锁钉住的三条，
#: 本波登记为管线管理形。（运维告警 bot.alert 走同步 `pipeline.handle` 且被
#: `test_orchestration_callsite_wave3_c.py::DESCRIPTOR_SHELL_ONLY_IDS` 钉为「无编排事实」，
#: 本波不登记——见注册册表内联注记与 logs/WP3-IMPL-handoff.md「受阻项」。）
PIPELINE_MANAGED_IDS = ("bot.campus_forward", "bot.chat", "bot.subscribe")


# --------------------------------------------------------------------------- 夹具
class _FakeMessage:
    def __init__(self, text: str = "说一句") -> None:
        self.text = text
        self.request_id = "req-pm"


class _FakeReceipt:
    """替身 DeliveryReceipt：handler 只按属性投影，不需要它是真 pydantic 模型。"""

    def __init__(self) -> None:
        self.request_id = "req-pm"

        class _State:
            value = "sent"

        self.state = _State()
        self.transport = "onebot"
        self.provider_message_id = "pm-1"


class _FakePipeline:
    """最小 RuntimePipeline 替身：记录 handle_async 被怎么调。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, str]] = []

    async def handle_async(self, message, capability, capability_id="bot.status"):
        self.calls.append((message, capability, capability_id))
        return _FakeReceipt()


class _NoHandleAsync:
    """交错对象：没有 handle_async ⇒ handler 必须 FAILED，不崩、不猜。"""

    def __init__(self) -> None:
        self.calls: list[object] = []


def _request(cid: str, *, pipeline: object = None, capability: object = None) -> cp.CapabilityRequest:
    context: dict[str, object] = {"config": None, "decision": None}
    if pipeline is not None:
        context["pipeline"] = pipeline
    if capability is not None:
        context["capability"] = capability
    return cp.CapabilityRequest(
        capability_id=cid,
        payload={"message": _FakeMessage()},
        principal="3865067623",
        roles=("user",),
        request_id="req-pm",
        session_key="private:3865067623",
        context=context,
    )


# --------------------------------------------------------------------------- INV-REGISTER
@pytest.mark.parametrize("cid", PIPELINE_MANAGED_IDS)
def test_pipeline_managed_capability_is_registered_with_real_execution(cid: str) -> None:
    """四枚都在册 + 有真实执行体（描述符 handler_ref 非空 + default_invoker 挂了 handler）。"""
    row = cp.CAPABILITY_DESCRIPTOR.get(cid)
    assert row is not None, f"{cid} 没进中央描述符表 CAPABILITY_DESCRIPTOR"
    assert row.handler_ref.endswith("#RuntimePipeline.handle_async"), row.handler_ref
    descriptor = cp.default_invoker().registry.get(cid)
    assert descriptor is not None, f"{cid} 有在册行却没派生描述符"
    assert descriptor.family is cp.CapabilityFamily.PIPELINE
    assert descriptor.title.strip()
    assert cp.default_invoker().handlers.get(cid) is not None, f"{cid} 没有信封 handler（在册 execution 是假的）"


@pytest.mark.parametrize("cid", PIPELINE_MANAGED_IDS)
def test_pipeline_managed_capability_is_not_counted_as_wired(cid: str) -> None:
    """诚实账：管线管理形**不进** `_route_execution_adapters()` ⇒ 不被 seam 认成通电、
    不被 ⑤入口耐久锁要求根汇缝站点 ⇒ 缺口账对它们仍按 generic/not_wired 现算（能跑≠已接）。"""
    assert cid not in cp._route_execution_adapters()
    assert cid not in cp._KNOWN_ADAPTERS  # adapter 名"pipeline_managed"不在两形集合里
    assert cid in cp.pipeline_managed_execution_cids()


# --------------------------------------------------------------------------- INV-EXECUTE
@pytest.mark.parametrize("cid", PIPELINE_MANAGED_IDS)
def test_invoke_drives_the_supplied_handle_async(cid: str) -> None:
    """走 default_invoker().invoke ⇒ 真的驱动**调用方交来的那一个** handle_async，
    并把 capability_id 传对、回执投影进信封（不重复其内部治理、不冒充呈现载荷）。"""
    pipeline = _FakePipeline()
    capability = object()
    request = _request(cid, pipeline=pipeline, capability=capability)
    result = cp.default_invoker().invoke(request)

    assert result.status is cp.InvocationStatus.OK, result.detail
    assert len(pipeline.calls) == 1, "handle_async 应被恰好驱动一次"
    called_msg, called_cap, called_cid = pipeline.calls[0]
    assert called_msg is request.payload["message"], "传进去的不是 payload.message"
    assert called_cap is capability, "跑的不是调用方交来的能力体"
    assert called_cid == cid, f"handle_async 的 capability_id 传错：{called_cid}"
    assert result.via.startswith("pipeline_managed:"), result.via
    assert result.data.get("delivery_receipt", {}).get("state") == "sent"
    # 信封不变量：管线管理形不写 PRESENTATION_DATA_KEY（它产投递回执、不产呈现契约载荷）
    assert cp.PRESENTATION_DATA_KEY not in result.data


@pytest.mark.parametrize("cid", PIPELINE_MANAGED_IDS)
def test_missing_pipeline_handle_is_honest_unavailable_never_self_builds(cid: str) -> None:
    """缺 pipeline 句柄 ⇒ 诚实 UNAVAILABLE（生产根未改道时的现网实况），绝不自建 RuntimePipeline、
    绝不回退直呼、绝不冒充投递成功。"""
    result = cp.default_invoker().invoke(_request(cid))  # 无 pipeline / capability
    assert result.status is cp.InvocationStatus.UNAVAILABLE
    assert "绝不自建" in result.detail and "第二通路" in result.detail
    assert result.via == "pipeline_managed_no_handle"
    assert cp.PRESENTATION_DATA_KEY not in result.data  # 未接线不得携带结果体


def test_pipeline_without_handle_async_is_failed_not_crash() -> None:
    """交错了没有 handle_async 的对象 ⇒ FAILED（诚实点名），不抛不猜。"""
    result = cp.default_invoker().invoke(
        _request("bot.chat", pipeline=_NoHandleAsync(), capability=object())
    )
    assert result.status is cp.InvocationStatus.FAILED
    assert "handle_async" in result.detail


def test_handler_never_imports_or_constructs_runtime_pipeline() -> None:
    """「禁第二通路」结构性自证：信封源码不 import/构造 RuntimePipeline（只会用调用方交来的句柄）。"""
    src = inspect.getsource(cp._make_pipeline_managed_handler)
    assert "RuntimePipeline(" not in src, "信封里出现了自建 RuntimePipeline＝第二通路"
    assert "importlib" not in src, "信封不得自行 import 层 1 管线（只能吃 context 交来的句柄）"
    assert "import " not in src, "信封内不得有任何 import 语句去取真身"


# --------------------------------------------------------------------------- INV-FAMILY
def test_command_family_count_is_not_polluted() -> None:
    """COMMAND 族计数锁（`test_v21_s10_protocols`）不被污染：管线管理形另立一族。"""
    invoker = cp.default_invoker()
    assert len(invoker.registry.iter(cp.CapabilityFamily.COMMAND)) == len(cp._route_execution_rows())
    assert len(invoker.registry.iter(cp.CapabilityFamily.PIPELINE)) == len(PIPELINE_MANAGED_IDS)


# --------------------------------------------------------------------------- INV-STATUS
def test_status_line_surfaces_pipeline_managed_registration() -> None:
    """/bot status 的管线管理形行由中央件现算、点名四枚（含义升级：有真实执行形在册）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    line = echo._orchestration_execution_line()
    assert "管线管理形" in line
    assert f"在册 {len(PIPELINE_MANAGED_IDS)} 枚" in line
    for cid in PIPELINE_MANAGED_IDS:
        assert cid in line
    # 诚实：bot.alert 未被登记 ⇒ 不出现在管线管理形在册面（不冒充"运维告警已接中央"）
    assert "bot.alert" not in line
    assert "待生产根改道通电" in line  # 诚实：不冒充已接线


def test_status_line_is_wired_into_the_body() -> None:
    """结构锁：这一行确实接进 `_build_status_body`（不是写了个孤儿函数）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    assert "_orchestration_execution_line()" in inspect.getsource(echo._build_status_body)


# --------------------------------------------------------------------------- 注毒自证（防空锁）
def test_status_line_failopen_when_central_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：中央件读不到 ⇒ 行诚实降级，绝不抛、绝不冒充"没问题"。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import echo

    def _boom() -> tuple[str, ...]:
        raise RuntimeError("中央面在飞不可读")

    monkeypatch.setattr(cp, "pipeline_managed_execution_cids", _boom)
    line = echo._orchestration_execution_line()
    assert "unavailable" in line and "不作判定" in line


def test_register_lock_has_teeth(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：若把某枚从管线管理形表里摘掉 ⇒ 该枚掉出在册执行体面，登记锁会红（证明锁真在测）。"""
    import plugins.bot_unified_runtime.domains.chat_reply.runtime.capability_registry as cr

    victim = "bot.chat"
    shrunk = tuple(
        d for d in cr.PIPELINE_MANAGED_CAPABILITY_DECLARATIONS if d.capability_id != victim
    )
    monkeypatch.setattr(cr, "PIPELINE_MANAGED_CAPABILITY_DECLARATIONS", shrunk)
    assert victim not in cp.pipeline_managed_execution_cids()
    # 摘掉后 handler 派生面少一枚 ⇒ 计数锁归位（证明这些计数真由这张表撑住，非硬编码）
    fresh = [d.capability_id for d in cp._pipeline_managed_descriptors()]
    assert victim not in fresh


def test_execute_lock_would_red_if_handle_not_called() -> None:
    """注毒（合成）：若 handler 其实没跑交来的 handle_async ⇒ 活性判据必红（非空转）。
    用一枚"从不记录调用"的假 pipeline 触发断言失败路径。"""
    class _NeverCalls:
        async def handle_async(self, message, capability, capability_id="x"):
            raise AssertionError("handle_async 被调用＝反证")

    result = cp.default_invoker().invoke(
        _request("bot.chat", pipeline=_NeverCalls(), capability=object())
    )
    # 交来的 handle_async 抛异常 ⇒ 主链异常走降级链（honest_degrade），绝不冒充投递成功
    assert result.status in (cp.InvocationStatus.DEGRADED, cp.InvocationStatus.FAILED)
    assert cp.PRESENTATION_DATA_KEY not in result.data
