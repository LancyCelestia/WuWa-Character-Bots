"""`/bot why` 的 LLM 归因回归锁（2026-09-24 W22）。

锁的是**一句话**：本轮没有模型服务证据，就不许渲染出任何具体模型名。

缺陷形态（修前）：`diagnostics.py` 里
`llm_model = infer_text_tag(audit_tags, "model") or config.bot_chat_model`
——链还没起跑就耗尽的消息（`chat.py` 的 `deadline_exceeded:before_llm` 那一路
根本不打 `model:` 标签）也会印出**缺省模型名**，读起来像"那个模型炸了"，
而它一次都没被调用过。同型问题：配置探针态（`not_configured`/`ok`）被写进
逐消息列 `llm_status`，"配置是好的"于是被渲染成"这条消息跑通了"。

离线运行（无网络、无 LLM、SQLite 走 tmp_path）：

    PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 python -m pytest \
        tests/test_diagnostic_llm_attribution.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    PrivacyLevel,
    ReceiptState,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.ops.smoke import diagnostics
from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (
    LLM_MODEL_NO_EVIDENCE_TEXT,
    SQLiteDiagnosticsRepository,
    _format_why_body,
    build_runtime_diagnostic,
)

DEFAULT_MODEL = "gemini-3.8-flash"
#: 渲染面上绝不该出现的"顶替值"（缺省模型名）在无证据行里的全部出现形态。
FORBIDDEN_MODEL_RENDERINGS = (DEFAULT_MODEL, f"model={DEFAULT_MODEL}")


def _config(**overrides: object) -> Config:
    base: dict[str, object] = {
        "bot_chat_provider": "openai_compatible",
        # 一个显眼的假缺省值：任何一次"拿缺省顶替实测"都会让它出现在渲染面上。
        "bot_chat_model": DEFAULT_MODEL,
        "bot_chat_api_key": "not-a-real-offline-test-key",
        "bot_runtime_enabled": True,
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


def _message(*, private: bool = True):
    from plugins.bot_unified_runtime.contracts import IncomingMessage

    return IncomingMessage(
        platform="onebot_v11",
        adapter="onebot",
        bot_id="qq-bot",
        session_id="private:user-1" if private else "group:g-1:u-1",
        session_type=SessionType.PRIVATE if private else SessionType.GROUP,
        sender_id="user-1",
        message_id="m-1",
        request_id="req-1",
        plain_text="今天有什么新闻",
    )


def _rendered() -> RenderedOutput:
    return RenderedOutput(
        request_id="req-1",
        content_type="text",
        content_ref={"text": "我在。"},
        text_fallback="我在。",
        privacy_level=PrivacyLevel.PERSONAL,
    )


def _send_request(*, audit_tags: list[str]) -> SendRequest:
    return SendRequest(
        request_id="req-1",
        session_id="private:user-1",
        target_scope=SessionType.PRIVATE,
        target_id="user-1",
        capability_id="bot.chat",
        content=_rendered(),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key="dedupe-req-1",
        cooldown_key="bot.chat:private:user-1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
        audit_tags=audit_tags,
    )


def _diagnostic(
    *,
    audit_tags: list[str],
    config: Config | None = None,
    with_send_request: bool = True,
):
    return build_runtime_diagnostic(
        config or _config(),
        message=_message(),
        capability_id="bot.chat",
        receipt=DeliveryReceipt(
            request_id="req-1",
            state=ReceiptState.SENT,
            transport="onebot",
            debug_id="dbg-1",
        ),
        send_request=_send_request(audit_tags=audit_tags) if with_send_request else None,
        audit_records=[],
    )


LLM_ERROR_TAGS = ["llm_error", "llm_error:deadline_exceeded"]
SERVED_TAGS = [
    f"model:{DEFAULT_MODEL}",
    "llm_usage_prompt_tokens:120",
    "llm_usage_completion_tokens:64",
    "llm_usage_total_tokens:184",
]


# --------------------------------------------------------------- 锁①
def test_no_evidence_never_renders_the_default_model() -> None:
    """无 `model:` 服务标签 ⇒ 渲染"未参与／未知"，且缺省模型名一个字都不出现。"""
    diagnostic = _diagnostic(audit_tags=[*LLM_ERROR_TAGS, "deadline_exceeded:before_llm"])
    body = _format_why_body(diagnostic)

    assert diagnostic.llm_model == "", "无证据却读出了模型名"
    assert LLM_MODEL_NO_EVIDENCE_TEXT in body
    for forbidden in FORBIDDEN_MODEL_RENDERINGS:
        assert forbidden not in body, f"缺省模型名顶替了证据：{forbidden}"


# --------------------------------------------------------------- 锁②
def test_served_model_tag_renders_the_real_value() -> None:
    """有服务标签 ⇒ 照原值渲染（点号/连字符形态的真实模型名不许被安全尺误杀）。"""
    diagnostic = _diagnostic(audit_tags=SERVED_TAGS)
    body = _format_why_body(diagnostic)

    assert diagnostic.llm_model == DEFAULT_MODEL
    assert f"model={DEFAULT_MODEL}" in body
    assert LLM_MODEL_NO_EVIDENCE_TEXT not in body
    assert diagnostic.llm_status == "ok"


def test_served_model_reader_accepts_dotted_names() -> None:
    """`_is_safe_reason`（原因码字符集）当模型名字符集用会把真实模型名全判不安全——
    旧写法正因如此而**每次**都落到缺省值。本锁钉住模型名自己的字符集。"""
    assert diagnostics._is_safe_reason(DEFAULT_MODEL) is False
    assert diagnostics.infer_llm_served_model([f"model:{DEFAULT_MODEL}"]) == DEFAULT_MODEL
    assert diagnostics.infer_llm_served_model(["model:gpt-5.6-terra"]) == "gpt-5.6-terra"
    # 垃圾与注入内容不进渲染面。
    assert diagnostics.infer_llm_served_model(["model:bad model\nwith newline"]) == ""
    assert diagnostics.infer_llm_served_model(["model:../../etc/passwd"]) == ""
    assert diagnostics.infer_llm_served_model(["model:"]) == ""
    # 多条时取末条（本轮最后真服务者）。
    assert (
        diagnostics.infer_llm_served_model(["model:a-1", "model:b-2"]) == "b-2"
    )


# --------------------------------------------------------------- 锁③
def test_before_and_during_llm_are_distinguishable_and_unattributed() -> None:
    """两态可区分；且两态都不许被顶替成某个具体模型。"""
    before = _diagnostic(audit_tags=[*LLM_ERROR_TAGS, "deadline_exceeded:before_llm"])
    during = _diagnostic(
        audit_tags=[
            *LLM_ERROR_TAGS,
            "deadline_exceeded:during_llm",
            "llm_route_attempt:grok-4.6:axon:timeout",
            "llm_route_attempt:gemini-3.8-flash:potccv:network",
        ]
    )
    before_body = _format_why_body(before)
    during_body = _format_why_body(during)

    assert diagnostics.infer_llm_break_stage(before.audit_tags) == "before_llm"
    assert diagnostics.infer_llm_break_stage(during.audit_tags) == "during_llm"
    assert "before_llm" in before_body and "during_llm" not in before_body
    assert "during_llm" in during_body and "before_llm" not in during_body
    for body in (before_body, during_body):
        assert LLM_MODEL_NO_EVIDENCE_TEXT in body
        # model= 那一格永不顶替成缺省值（缺省值只当"被顶替"的探针，绝不当答案）。
        assert f"model={DEFAULT_MODEL}" not in body
    # 断链前无跳序证据 ⇒ 整页不得出现任何具体模型名（旧缺陷正是印出缺省名）。
    assert DEFAULT_MODEL not in before_body
    # 有跳序时，跳里出现的名字是"真被试过"的服务者，属诚实带出，不在禁止之列。
    assert "LLM断点：during_llm" in during_body
    # 走过的跳序来自真身标签（chat.py 的 llm_route_attempt），逐跳带出来。
    assert "LLM跳序：n=0" in before_body
    assert "LLM跳序：n=2" in during_body
    assert "grok-4.6:axon:timeout" in during_body


# --------------------------------------------------------------- 锁④
def test_probe_status_and_per_message_status_are_different_columns() -> None:
    """探针态（配置的事实）与逐消息态（这条消息的事实）分名分列，互不顶替。"""
    ok_config_but_idle = _diagnostic(audit_tags=["some_unrelated_tag"])
    static_config = _diagnostic(audit_tags=["some_unrelated_tag"], config=_config(bot_chat_provider="static", bot_chat_model="static"))

    # 配置能真调 LLM（探针 ok），但这条消息压根没到 LLM ⇒ 逐消息 not_run。
    assert ok_config_but_idle.llm_probe_status == "ok"
    assert ok_config_but_idle.llm_status == "not_run"
    # 配置侧没接真 provider ⇒ 探针说 not_configured，逐消息列不再携带该词。
    assert static_config.llm_probe_status == "not_configured"
    assert static_config.llm_status == "not_run"
    assert "not_configured" not in {ok_config_but_idle.llm_status, static_config.llm_status}
    # 逐消息态词表封闭：只剩证据派生的三态。
    assert ok_config_but_idle.llm_status in {"ok", "error", "not_run"}

    body = _format_why_body(ok_config_but_idle)
    assert "LLM：not_run，" in body
    assert "LLM配置探针：ok" in body


def test_probe_status_survives_sqlite_round_trip(tmp_path: Path) -> None:
    """两列各自落库、各自读回（同名同列＝第二真身，故必须分列持久化）。"""
    store = SQLiteDiagnosticsRepository(tmp_path / "diag.sqlite3")
    diagnostic = _diagnostic(audit_tags=[*LLM_ERROR_TAGS, "deadline_exceeded:before_llm"])
    store.record(diagnostic)
    loaded = store.find("req-1")

    assert loaded is not None
    assert loaded.llm_status == diagnostic.llm_status == "error"
    assert loaded.llm_probe_status == diagnostic.llm_probe_status == "ok"
    assert loaded.llm_model == ""
    columns = {
        str(row[1])  # PRAGMA table_info 第 2 列是列名（此连接无 row_factory ⇒ 元组）
        for row in _table_columns(tmp_path / "diag.sqlite3")
    }
    assert {"llm_status", "llm_probe_status"} <= columns


def _table_columns(db_path: Path):
    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("PRAGMA table_info(runtime_diagnostics)").fetchall()
    finally:
        connection.close()


# --------------------------------------------------------------- 锁⑤（反向锁）
def test_served_path_render_is_untouched() -> None:
    """有服务证据时渲染**逐字节不变**：LLM 行原样、且一行新增都不许出现。"""
    diagnostic = _diagnostic(audit_tags=SERVED_TAGS)
    lines = _format_why_body(diagnostic).split("\n")

    assert (
        f"LLM：ok，provider=openai_compatible，model={DEFAULT_MODEL}" in lines
    ), "成功路径的 LLM 行被改写了"
    index = lines.index(f"LLM：ok，provider=openai_compatible，model={DEFAULT_MODEL}")
    assert lines[index + 1].startswith("LLM就绪：")
    assert lines[index + 2].startswith("LLM原因：")
    for marker in ("LLM配置探针：", "LLM断点：", "LLM跳序：", "LLM归因："):
        assert not any(line.startswith(marker) for line in lines), f"成功路径多出归因行 {marker}"


# --------------------------------------------------------------- 行为面补充
def test_error_path_still_flips_per_message_status() -> None:
    """既有语义不回退：本轮带 llm_error ⇒ 逐消息态仍是 error（错误优先于其它判据）。"""
    diagnostic = _diagnostic(audit_tags=[*LLM_ERROR_TAGS, f"model:{DEFAULT_MODEL}"])
    assert diagnostic.llm_status == "error"
    # 错误路径即便带了模型名（真服务过后才炸）也照原值报，不抹平。
    assert diagnostic.llm_model == DEFAULT_MODEL


def test_policy_blocked_message_has_no_send_request_probe() -> None:
    """没建发送请求（策略挡下）⇒ 探针无从谈起，逐消息 not_run，模型未参与。"""
    diagnostic = _diagnostic(audit_tags=["runtime_paused"], with_send_request=False)
    assert diagnostic.llm_probe_status == ""
    assert diagnostic.llm_status == "not_run"
    assert diagnostic.llm_model == ""
    assert "LLM配置探针：-" in _format_why_body(diagnostic)


# --------------------------------------------------------------- 注毒自证用固定夹具
@pytest.fixture(autouse=True)
def _no_network() -> None:
    """本件全程离线：任何真 provider 都不被构造（build_runtime_diagnostic 只读配置）。"""
    assert Config().bot_chat_provider == "static"


# ============================ 2026-09-24 PX-15 B：跳序与两处 CLI 面归因锁 ============================ #
# W22 只修了诊断库那一面。同日现算发现同型缺陷还在两处：`run_why_smoke` 与 chat smoke
# 的返回字典里 `llm_model` 直接取配置缺省（或取**首**个 model: 标签），
# 而链耗尽时配置里那台**从未被调用**——于是 CLI 验收面印出一个不存在的关系。
# 本段把"永不拿配置顶替实测"从"诊断库专用"升成"三处同锁"，并把审计标签里已有的
# 跳序证据（`llm_route_attempt:`）在渲染面显式出来（`/bot dialogue` 与诊断行）。

import ast as _ast
from pathlib import Path as _Path

from plugins.bot_unified_runtime.domains.ops.admin.debug import (
    _format_route_chain,
    _result_audit_tags,
)
from plugins.bot_unified_runtime.domains.ops.smoke.diagnostics import (
    LLM_MAX_RENDERED_HOPS,
    infer_llm_break_stage,
    infer_llm_route_hops,
)

_SMOKE_PY = _Path(
    "plugins/bot_unified_runtime/domains/ops/smoke/smoke.py"
).resolve()


def test_route_chain_renders_count_and_every_hop_in_order() -> None:
    tags = [
        "llm_route_attempt:axon-gemini:timeout",
        "llm_route_attempt:axon-grok:network",
        "llm_route_attempt:potccv-terra:rate_limited",
    ]
    rendered = _format_route_chain(infer_llm_route_hops(tags))
    assert rendered.startswith("n=3 ")
    assert "axon-gemini:timeout <- axon-grok:network <- potccv-terra:rate_limited" in rendered
    # 末站必须是最后一次尝试——她要回答的是"最后卡在谁身上"。
    assert rendered.rstrip().endswith("potccv-terra:rate_limited")


def test_route_chain_caps_display_but_reports_true_width() -> None:
    tags = [f"llm_route_attempt:hop-{index}" for index in range(LLM_MAX_RENDERED_HOPS + 2)]
    rendered = _format_route_chain(infer_llm_route_hops(tags))
    assert f"n={LLM_MAX_RENDERED_HOPS + 2}" in rendered
    assert "(+2跳未列)" in rendered
    assert rendered.count("hop-") == LLM_MAX_RENDERED_HOPS


def test_route_chain_says_no_evidence_instead_of_guessing() -> None:
    for empty in ([], ["llm_error"], ["model:gemini-3.8-flash"]):
        hops = infer_llm_route_hops(empty)
        assert not hops
        assert _format_route_chain(hops) == "n=0（无跳序证据标签）"
        assert _format_route_chain(None) == "n=0（无跳序证据标签）"
    # 断点同理：没有 deadline 标签就报 '-'，不许从"失败了"推断断在哪一段。
    assert infer_llm_break_stage(["llm_error"]) == ""
    assert infer_llm_break_stage(["deadline_exceeded:before_llm"]) == "before_llm"
    assert infer_llm_break_stage(["deadline_exceeded:during_llm"]) == "during_llm"


def test_result_audit_tags_tolerates_missing_and_non_list() -> None:
    assert _result_audit_tags({}) == []
    assert _result_audit_tags({"audit_tags": "model:x"}) == []
    assert _result_audit_tags({"audit_tags": ["a", "", 3]}) == ["a", "3"]


def _llm_model_values_in_smoke() -> list[str]:
    tree = _ast.parse(_SMOKE_PY.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, _ast.Constant) and key.value == "llm_model":
                    found.append(_ast.unparse(value))
    return found


def test_smoke_surfaces_derive_llm_model_from_evidence_only() -> None:
    """CLI 面的 `llm_model` 只许两种形：走唯一证据推导口，或明写空串（本轮没跑）。

    空串只允许出现在"chat 从未被调用"那一枚合成结果里——它由 `llm_status`
    自证，所以这里数一次并把次数钉死；`chat_result[...]` 是透传（真值已由上游
    推导口算过），同样放行。多一处空串或出现配置顶替即判红。
    """
    allowed = {"infer_llm_served_model(audit_tags)", "''", "chat_result['llm_model']"}
    values = _llm_model_values_in_smoke()
    assert values, "smoke.py 里找不到 llm_model 字段，本锁失效（改形了要同步）"
    literal_empty = [value for value in values if value == "''"]
    assert len(literal_empty) <= 1, f"空串归因不止一处：{values}"
    for value in values:
        assert "config.bot_chat_model" not in value, f"配置缺省顶替实测：{value}"
        assert " or " not in value, f"空值被兜成配置名＝同一形态：{value}"
        assert value in allowed, f"未走唯一推导口：{value}"


def test_the_smoke_lock_actually_bites_the_old_forms() -> None:
    """杀伤力自证：把修前三形态喂给同一条判据，必须逐条被点名。

    没有这一条，上面那把 AST 锁就可能是一条只读真身、永远只绿的空枪
    （本仓反复踩过的"存在性冒充活性"）。
    """
    banned = [
        "config.bot_chat_model",
        "routed_model or config.bot_chat_model",
        'next((t for t in audit_tags if t.startswith("model:")), config.bot_chat_model)',
    ]
    allowed = {"infer_llm_served_model(audit_tags)", "''", "chat_result['llm_model']"}

    def _value_of(source: str) -> str:
        node = next(
            item
            for item in _ast.walk(_ast.parse(source))
            if isinstance(item, _ast.Dict)
            and any(
                isinstance(k, _ast.Constant) and k.value == "llm_model"
                for k in item.keys
            )
        )
        return _ast.unparse(
            next(
                v
                for k, v in zip(node.keys, node.values)
                if isinstance(k, _ast.Constant) and k.value == "llm_model"
            )
        )

    for source in banned:
        value = _value_of(f"payload = {{'llm_model': {source}}}")
        assert value not in allowed, f"这形态本该判红却放行：{value}"
        assert "config.bot_chat_model" in value or " or " in value
    assert _value_of("payload = {'llm_model': infer_llm_served_model(audit_tags)}") in allowed
