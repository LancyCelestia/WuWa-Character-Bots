"""S0-COLLECT 席（v21r4-B）：S0 直连点收编·非 root 件契约锁。

取证权威=``docs/design/v21r4-b2-direct-collect-plan.md``（DIRECT-PLAN 席）+
本席日志 ``docs/design/v21r4-b-S0-COLLECT-log.md``（坐标=2026-09-18 读时快照）。

锁三件事（数据面登记表 ↔ 统一出站路径真值一致性）：

1. file_gateway 直连登记项对齐统一文件出站路径真值——reorg 后真身
   ``domains/transport/sender/file_gateway.py`` ``FileTransferGateway._deliver_onebot``
   （旧路径 ``sender/file_gateway.py`` 已是 3 行 compat shim），类别 CHANNEL_BODY
   （统一路径自身通道本体，非绕行；PENDING_RULING 对本项退役）；
2. 「走统一路径」链路锁：transport 文件部件分支经
   ``get_default_file_gateway().stage → deliver``（onebot.py B3 阶段 1 既有链），
   上游 renderer ``CapabilityResult.files`` → media_parts 映射在位；
3. 根 ``__init__.py`` 原四处 BYPASS_SUSPECT 已于 ed802d3（2026-09-26，裁定 R-4
   + S174 现算）整批改判 ABSORBED——本锁判据随之改为**显式名册 ↔ registry
   点名对账**（棘轮：嫌疑只降不升；现算在册嫌疑唯一在岗＝``_deliver_v2_event``，
   SEAT-ATK-SUB 评审 F-2 补登，F-1 根修落地后随迁改判、名册归零）；
   陈旧坐标（4070/4878/5175）与历史死号（4440/5378/5730/5526）在 location
   清零（note/evidence 散文留痕合法）。原「pending-on-RWC5-b」注记语义已随
   行为收编兑现而退役（盘上 registry 该字面量零命中），不再作判据。

全离线：零网络、零 NoneBot 启动、零真实发送、零根 ``__init__.py`` 改动。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.core.decision.outbound import (
    DirectSendCategory,
    TransportChannel,
    build_default_takeover_registry,
    build_default_transport_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "bot_unified_runtime"

# WIRE-DIRECT 移交、经本席 grep 复核已陈旧的根坐标字面量（登记表中必须清零）。
_STALE_ROOT_COORDINATES = ("4070", "4878", "5175")

# ed802d3（2026-09-26）改判后的 BYPASS_SUSPECT 显式名册（棘轮：只降不升；
# F-1 根修落地后本条随迁改判 ABSORBED、名册归零——届时同步本常量，禁抬棘轮）。
# 2026-09-28 S-FIX-COORD-REANCHOR（主任务板 #33 诚实路径①）：登记式统一为
# `file::symbol` 符号派生式，名册语法随批。
_BYPASS_SUSPECT_ROSTER = ("__init__.py::_deliver_v2_event",)

# 原四处根直连改判 ABSORBED 后的名册：api 锚名=在岗后继统一管线函数
# （行号随根在飞编辑必漂，本件先例纪律=不钉根文件行号、按符号名点名）。
_ABSORBED_API_ROSTER = frozenset(
    {
        "send_private_msg → _deliver_cookie_expiry_report_via_queue",
        "send_group_msg → _send_text_through_unified_pipeline",
        "send_group_msg + send_private_msg → _send_parts_through_unified_pipeline",
        "upload_group_file + upload_private_file → _send_files_through_unified_pipeline",
    }
)


def _file_gateway_entry_location() -> tuple[Path, str]:
    reg = build_default_takeover_registry()
    entries = [e for e in reg.direct_sends if "file_gateway" in e.location]
    assert len(entries) == 1, f"file_gateway 登记项应恰一条，现={len(entries)}"
    entry = entries[0]
    relative, _, _line_part = entry.location.partition(":")
    return _PLUGIN_ROOT.joinpath(*relative.split("/")), entry.location


# ---------------------------------------------------------------------------
# 1. file_gateway 直连登记项 → 统一路径通道本体（PENDING_RULING 退役）
# ---------------------------------------------------------------------------


def test_file_gateway_entry_reclassified_channel_body_at_real_path() -> None:
    """DIRECT-PLAN §二④/§3.5：file_gateway 内环=统一文件出站路径通道本体。

    旧登记（sender/file_gateway.py:382 + PENDING_RULING）基于 reorg 前路径与
    未裁决状态；真值=domains/transport/sender/file_gateway.py 的
    ``_deliver_onebot`` 上传内环，CHANNEL_BODY（与 sender/onebot.py 通道本体同口径）。
    """
    reg = build_default_takeover_registry()
    entries = [e for e in reg.direct_sends if "file_gateway" in e.location]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.category is DirectSendCategory.CHANNEL_BODY, (
        "file_gateway 内环应登记为 CHANNEL_BODY（统一路径通道本体）；"
        "若回退 PENDING_RULING 须先过 DELIVERY-001 裁决并同步本锁"
    )
    assert entry.location.startswith("domains/transport/sender/file_gateway.py"), (
        f"登记路径应对齐 reorg 后真身，现={entry.location}"
    )
    # PENDING_RULING 对该直连项退役（登记表中不应再有待裁决直发项）。
    pending = [
        e for e in reg.direct_sends if e.category is DirectSendCategory.PENDING_RULING
    ]
    assert not pending, f"PENDING_RULING 应清零，现={[e.location for e in pending]}"


def test_file_gateway_entry_resolves_to_deliver_onebot_inner_loop() -> None:
    """登记锚必须符号解析到真身 ``_deliver_onebot`` 且含 call_api 调用腿。

    防再次出现「锚指到 compat shim / 别的函数」的陈旧漂移。
    2026-09-28 S-FIX-COORD-REANCHOR：判据由「行号区间落在 def 跨度内」改为
    符号派生式——登记式恰等于锚串、按 AST 唯一命中、callee 腿在体内 ≥1 命中
    （行号随插删必漂，退出判据）。
    """
    real_path, location = _file_gateway_entry_location()
    assert real_path.is_file(), f"登记真身不存在：{real_path}"
    assert location == (
        "domains/transport/sender/file_gateway.py::_deliver_onebot:call_api"
    ), f"登记式必须是符号派生式，现={location}"
    source = real_path.read_text(encoding="utf-8")
    assert "async def _deliver_onebot" in source
    assert "upload_group_file" in source and "upload_private_file" in source

    tree = ast.parse(source)
    defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_deliver_onebot"
    ]
    assert len(defs) == 1, f"_deliver_onebot 应按符号名唯一命中，现={len(defs)} 处"
    func = defs[0]
    callee_hits = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "call_api")
            or (isinstance(node.func, ast.Name) and node.func.id == "call_api")
        )
    ]
    assert callee_hits, "登记 callee 腿 call_api 在 _deliver_onebot 体内零命中＝锚已漂"


# ---------------------------------------------------------------------------
# 2. 「走统一路径」链路锁（renderer files → transport FileTransferGateway）
# ---------------------------------------------------------------------------


def test_unified_file_outbound_chain_consumes_file_gateway() -> None:
    """文档导出收编的目标链在位：files→media_parts→file 部件→网关 stage/deliver。

    DIRECT-PLAN §3.4 形态 D 的技术依据（renderer.py:214-216 +
    onebot.py:439-462 + file_gateway._deliver_onebot）——根内 ④ 收编
    （pending-on-RWC5-b）落地时走的正是这条链，此处锁链路不被悄悄改道。
    """
    onebot_source = (
        (_PLUGIN_ROOT / "domains" / "transport" / "sender" / "onebot.py")
        .read_text(encoding="utf-8")
    )
    # 文件部件分支统一经 FileTransferGateway（B3 阶段 1 契约）。
    assert "get_default_file_gateway()" in onebot_source
    assert "gateway.stage(" in onebot_source and "gateway.deliver(" in onebot_source
    # 网关来源=登记项指向的同一模块（登记表↔链路同源）。
    assert (
        "from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import"
        in onebot_source
    )
    # 上游：CapabilityResult.files → media_parts 映射在位。
    renderer_source = (
        (_PLUGIN_ROOT / "domains" / "render" / "renderer.py").read_text(encoding="utf-8")
    )
    assert "for file_item in result.files or []:" in renderer_source


# ---------------------------------------------------------------------------
# 3. 根 __init__.py 直发嫌疑登记：坐标刷新 + 缺口补登 + pending 注记
# ---------------------------------------------------------------------------


def test_root_bypass_suspects_refreshed_and_doc_export_registered() -> None:
    """四处根直连（WIRE-DIRECT 移交口径）全部在册、在册嫌疑按名册、旧坐标清零。

    注意：本测试锁**登记表完整性**，不锁根文件行号（根正被多席在飞编辑，
    行号必漂——登记 note/evidence 带快照标记，实施席以符号 grep 复核）。
    判据形态＝显式名册 ↔ registry 点名对账：原四处 BYPASS_SUSPECT 已于
    ed802d3（2026-09-26，R-4 裁定 + S174 现算）整批改判 ABSORBED；现算在册
    嫌疑唯一在岗＝_deliver_v2_event（SEAT-ATK-SUB F-2 补登，F-1 落地后随迁
    改判、届时名册归零）。旧「计数==4 + pending-on-RWC5-b」判据随收编兑现
    退役（盘上 registry 该字面量零命中，留判据＝永久红＝无咬合力的摆设）。
    """
    reg = build_default_takeover_registry()
    suspects = [
        e for e in reg.direct_sends if e.category is DirectSendCategory.BYPASS_SUSPECT
    ]
    absorbed = [
        e for e in reg.direct_sends if e.category is DirectSendCategory.ABSORBED
    ]
    # 名册对账（棘轮只降不升）：少一枚＝静默退役嫌疑、多一枚＝未裁决新绕行。
    assert tuple(e.location for e in suspects) == _BYPASS_SUSPECT_ROSTER, (
        f"BYPASS_SUSPECT 名册漂移，现={[(e.location, e.api) for e in suspects]}"
    )
    # cookie 提醒 / 入群欢迎 / 二维码双通道 / 文档导出上传——改判后仍逐一在册。
    assert {e.api for e in absorbed} == _ABSORBED_API_ROSTER, (
        f"改判四枚应逐一点名在岗后继符号，现={sorted(e.api for e in absorbed)}"
    )
    joined = " | ".join(e.location for e in suspects + absorbed)
    for stale in _STALE_ROOT_COORDINATES:
        assert stale not in joined, f"陈旧坐标 {stale} 仍在登记：{joined}"
    assert all(e.location.startswith("__init__.py:") for e in suspects + absorbed)
    for entry in absorbed:
        # 收编证据链：已收编状态 + via_queue 后继门 + R-4 改判来源。
        assert "已收编" in entry.note and "via_queue" in entry.note and "R-4" in entry.note, (
            f"ABSORBED 条目 note 缺收编证据链：{entry.location}"
        )
        assert "v21r4-b S0-COLLECT" in entry.evidence, (
            f"证据串须带本席快照标记（行号会漂，实施席以符号 grep 复核）：{entry.location}"
        )
    for entry in suspects:
        # 在册嫌疑不得静默常置：note 须带 F-1 随迁改判承诺；证据带评审来源。
        assert "随迁" in entry.note, (
            f"嫌疑条目须带随迁改判承诺（F-1 落地后改 ABSORBED）：{entry.location}"
        )
        assert "SEAT-ATK-SUB" in entry.evidence, (
            f"嫌疑条目证据须带评审快照标记：{entry.location}"
        )


def test_transport_registry_evidence_no_longer_cites_stale_coordinates() -> None:
    """transport 登记表 evidence 串与直发登记表同批对齐（内部一致性）。"""
    reg = build_default_transport_registry()
    qq_entries = [e for e in reg.entries() if e.platform.value == "qq"]
    send_message = next(
        e for e in qq_entries if e.channel is TransportChannel.SEND_MESSAGE
    )
    for stale in ("4071", "4879", "5175"):
        assert stale not in send_message.evidence, (
            f"SEND_MESSAGE evidence 仍引用陈旧坐标 {stale}：{send_message.evidence}"
        )
    send_file = next(
        e
        for e in reg.entries()
        if e.channel is TransportChannel.SEND_FILE and e.platform.value == "qq"
    )
    assert "sender/file_gateway.py:382" not in send_file.evidence, (
        f"SEND_FILE evidence 仍引用 shim 旧路径：{send_file.evidence}"
    )
    assert "domains/transport/sender/file_gateway.py" in send_file.evidence
