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
3. 根 ``__init__.py`` 四处 BYPASS_SUSPECT 坐标刷新至读时快照（含补登记的
   文档导出上传直连），旧陈旧坐标（4070/4878/5175-5182）清零；
   pending-on-RWC5-b 语义显式入注——根内四处**行为收编**归 RWC5-b 交付后的
   后续席，本文件只锁登记表与真值的对应关系，不宣称生产行为已收编。

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
    """登记坐标必须落在真身 ``_deliver_onebot`` 函数体内（自检型登记表）。

    防再次出现「坐标指到 compat shim / 别的函数」的陈旧漂移。
    """
    real_path, location = _file_gateway_entry_location()
    assert real_path.is_file(), f"登记真身不存在：{real_path}"
    source = real_path.read_text(encoding="utf-8")
    assert "async def _deliver_onebot" in source
    assert "upload_group_file" in source and "upload_private_file" in source

    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_deliver_onebot"
    )
    _relative, _, line_part = location.partition(":")
    start_s, _, end_s = line_part.partition("-")
    start = int(start_s)
    end = int(end_s) if end_s else start
    assert func.lineno <= start and end <= (func.end_lineno or func.lineno), (
        f"登记坐标 {location} 未落在 _deliver_onebot "
        f"（AST 实际跨度 {func.lineno}-{func.end_lineno}）内"
    )


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
    """四处根直连（WIRE-DIRECT 移交口径）全部在册、旧坐标清零、pending 入注。

    注意：本测试锁**登记表完整性**，不锁根文件行号（根正被 RWC5-b 在飞编辑，
    行号必漂——登记 note/evidence 带快照标记，实施席以符号 grep 复核）。
    """
    reg = build_default_takeover_registry()
    suspects = [
        e for e in reg.direct_sends if e.category is DirectSendCategory.BYPASS_SUSPECT
    ]
    # cookie 提醒 / 入群欢迎 / 二维码双通道 / 文档导出上传（原登记缺口，补齐）。
    assert len(suspects) == 4, (
        f"根直连嫌疑应四处全登记，现={[(e.location, e.api) for e in suspects]}"
    )
    joined = " | ".join(e.location for e in suspects)
    for stale in _STALE_ROOT_COORDINATES:
        assert stale not in joined, f"陈旧坐标 {stale} 仍在登记：{joined}"
    assert all(e.location.startswith("__init__.py:") for e in suspects)
    apis = sorted(e.api for e in suspects)
    assert apis == [
        "send_group_msg",
        "send_group_msg + send_private_msg",
        "send_private_msg",
        "upload_group_file + upload_private_file",
    ], f"api 面漂移：{apis}"
    for entry in suspects:
        assert "pending-on-RWC5-b" in entry.note, (
            f"根直连条目须带 pending-on-RWC5-b 注记（行为收编归后续席）：{entry.location}"
        )
        assert "v21r4-b S0-COLLECT" in entry.evidence, (
            f"证据串须带本席快照标记（行号会漂，实施席以符号 grep 复核）：{entry.location}"
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
