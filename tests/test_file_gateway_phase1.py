"""B3 阶段 1（FileTransferGateway sender 层内收敛，零行为变化）回归测试。

规格：docs/design/file-transfer-gateway.md 阶段 1。验收要点：golden 锁定
既有行为（上传参数、caption 时序、副作用熔断、2MB 拒绝）；网关单测覆盖
三来源 stage / 两通道 deliver / 失败分类 / part_index 传递。
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.sender import send_onebot_v11
from plugins.bot_unified_runtime.sender.file_gateway import (
    FileSource,
    FileTicket,
    FileTransferError,
    FileTransferGateway,
    FileTransferReceipt,
    FinalTransferError,
    build_file_dedupe_key,
    get_default_file_gateway,
    sanitize_file_name,
    set_default_file_gateway,
)
from plugins.bot_unified_runtime.sender.nonebot import send_nonebot_message


@pytest.fixture(autouse=True)
def _isolated_gateway(tmp_path):
    gateway = FileTransferGateway(staging_dir=tmp_path / "staging")
    set_default_file_gateway(gateway)
    yield gateway
    set_default_file_gateway(None)


def _send_request(
    parts: list[dict],
    *,
    scope: SessionType = SessionType.GROUP,
    text: str = "附件在此",
    target_id: str = "12",
) -> SendRequest:
    return SendRequest(
        request_id="req_file",
        session_id=f"{scope.value}:{target_id}",
        target_scope=scope,
        target_id=target_id,
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id="req_file",
            content_type="mixed",
            content_ref={"parts": parts},
            text_fallback=text,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=0,
        dedupe_key="k",
        cooldown_key="c",
        privacy_level=PrivacyLevel.GROUP,
        persona_profile_id="shorekeeper",
    )


def _make_file(tmp_path: Path, name: str = "report.txt", body: bytes = b"hello file") -> Path:
    path = tmp_path / name
    path.write_bytes(body)
    return path


class _RecordingOneBotBot:
    def __init__(self, *, retcode: int = 0, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.retcode = retcode
        self.fail_with = fail_with

    async def call_api(self, api: str, **params):
        self.calls.append((api, params))
        if self.fail_with is not None:
            raise self.fail_with
        return {"status": "async ok", "retcode": self.retcode}

    async def send_group_msg(self, **params):
        self.calls.append(("send_group_msg", params))
        return {"message_id": 7}

    async def send_private_msg(self, **params):
        self.calls.append(("send_private_msg", params))
        return {"message_id": 8}


# -------------------- 文件名与来源声明 --------------------


def test_sanitize_file_name_is_identity_for_plain_names() -> None:
    assert sanitize_file_name("report.txt") == "report.txt"
    assert sanitize_file_name("守岸人报告.pdf") == "守岸人报告.pdf"
    assert sanitize_file_name("a/b/c.txt") == "c.txt"
    assert sanitize_file_name("..\\evil.exe") == "evil.exe"
    assert sanitize_file_name("bad\x01name.txt") == "badname.txt"
    assert sanitize_file_name("") == ""


def test_file_source_validates_single_source() -> None:
    with pytest.raises(FileTransferError) as empty:
        FileSource(source_kind="path", path="")
    assert empty.value.kind == "invalid_source"
    with pytest.raises(FileTransferError):
        FileSource(source_kind="bytes", data=None)
    assert FileSource(source_kind="path", path="x.txt", name="../weird/name").name == "name"


# -------------------- stage：三来源 --------------------


def test_stage_path_source_hashes_and_resolves(tmp_path: Path) -> None:
    path = _make_file(tmp_path, body=b"payload")
    ticket = get_default_file_gateway().stage(
        FileSource(source_kind="path", path=str(path), name="named.txt"),
        request_id="req1",
    )
    assert isinstance(ticket, FileTicket)
    assert ticket.ticket_id.startswith("ft_")
    assert ticket.local_path == path.resolve()
    assert ticket.name == "named.txt"
    assert ticket.size == 7
    assert ticket.sha256 == hashlib.sha256(b"payload").hexdigest()
    assert ticket.source == "path"


def test_stage_path_missing_file_is_classified(tmp_path: Path) -> None:
    with pytest.raises(FileTransferError) as caught:
        get_default_file_gateway().stage(
            FileSource(source_kind="path", path=str(tmp_path / "nope.bin")),
            request_id="req1",
        )
    assert caught.value.kind == "missing_file"


def test_stage_bytes_source_writes_staging(tmp_path: Path) -> None:
    gateway = get_default_file_gateway()
    ticket = gateway.stage(
        FileSource(source_kind="bytes", data=b"\x00\x01\x02", name="blob.bin"),
        request_id="req1",
    )
    assert ticket.local_path is not None
    assert ticket.local_path.parent == gateway.staging_dir
    assert ticket.local_path.read_bytes() == b"\x00\x01\x02"
    assert ticket.sha256 == hashlib.sha256(b"\x00\x01\x02").hexdigest()
    assert ticket.size == 3


def test_stage_url_requires_ssrf_gate_and_downloader() -> None:
    gateway = get_default_file_gateway()
    with pytest.raises(FileTransferError) as private:
        gateway.stage(
            FileSource(source_kind="url", url="http://127.0.0.1:9000/x.bin"), request_id="r"
        )
    assert private.value.kind == "url_rejected"  # SSRF 护栏拒绝私网地址
    with pytest.raises(FileTransferError) as unavailable:
        gateway.stage(
            FileSource(source_kind="url", url="https://example.com/pub.bin"), request_id="r"
        )
    assert unavailable.value.kind == "url_download_unavailable"  # 生产下载接线归阶段 3


def test_stage_url_with_injected_downloader_stages_content(tmp_path: Path) -> None:
    def _fake_downloader(url: str, target: Path) -> Path:
        target.write_bytes(b"downloaded")
        return target

    gateway = FileTransferGateway(
        staging_dir=tmp_path / "staging", url_downloader=_fake_downloader
    )
    ticket = gateway.stage(
        FileSource(source_kind="url", url="https://example.com/pub.bin"), request_id="r"
    )
    assert ticket.local_path is not None and ticket.local_path.read_bytes() == b"downloaded"
    assert ticket.sha256 == hashlib.sha256(b"downloaded").hexdigest()


def test_declare_only_param_is_removed_entirely() -> None:
    # 审查 J-14：declare_only（FileSource 字段 + _stage_url 分支）全仓零生产
    # 调用点，判定死代码整体移除（FileSource→Ticket→deliver 主链语义零变化）。
    # 本测试锁死「参数不复存在」：字段一回归即在此失败，防静默回潮。
    assert "declare_only" not in [f.name for f in dataclasses.fields(FileSource)]
    # 字段既删，任何 _stage_url 里的 src.declare_only 引用都会 AttributeError——
    # 用 getattr 探测真实实例做双保险。
    probe = FileSource(source_kind="path", path="x.txt")
    assert not hasattr(probe, "declare_only")


def test_file_dedupe_key_format() -> None:
    assert (
        build_file_dedupe_key(
            sha256="abc", target_scope=SessionType.GROUP, target_id="12", part_index=2
        )
        == "abc:group:12:2"
    )


# -------------------- deliver：OneBot 通道 --------------------


def _ticket(tmp_path: Path, name: str = "report.txt", body: bytes = b"data") -> FileTicket:
    path = _make_file(tmp_path, name, body)
    return get_default_file_gateway().stage(
        FileSource(source_kind="path", path=str(path), name=name), request_id="req_file"
    )


def test_deliver_onebot_group_uses_upload_group_file(tmp_path: Path) -> None:
    bot = _RecordingOneBotBot()
    receipt = asyncio.run(
        get_default_file_gateway().deliver(
            bot, _ticket(tmp_path), target=_send_request([]), part_index=3
        )
    )
    assert isinstance(receipt, FileTransferReceipt)
    api, params = bot.calls[0]
    assert api == "upload_group_file"
    assert params["group_id"] == 12  # 数字 id 强转 int（既有 _coerce_onebot_id 语义）
    assert params["file"] == str(Path(params["file"]).resolve())
    assert Path(params["file"]).is_file()
    assert params["name"] == "report.txt"
    assert receipt.state.value == "sent"
    assert receipt.transport == "onebot.file"
    assert receipt.part_index == 3
    assert receipt.provider_result == {"status": "async ok", "retcode": 0}


def test_deliver_onebot_private_falls_back_to_call_api(tmp_path: Path) -> None:
    class _CallApiOnlyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def call_api(self, api: str, **params):
            self.calls.append((api, params))
            return {"retcode": 0}

    bot = _CallApiOnlyBot()
    receipt = asyncio.run(
        get_default_file_gateway().deliver(
            bot,
            _ticket(tmp_path),
            target=_send_request([], scope=SessionType.PRIVATE, target_id="55"),
        )
    )
    assert bot.calls[0][0] == "upload_private_file"
    assert bot.calls[0][1]["user_id"] == 55
    assert receipt.state.value == "sent"


def test_deliver_onebot_failure_classification(tmp_path: Path) -> None:
    gateway = get_default_file_gateway()
    target = _send_request([])

    rejected = _RecordingOneBotBot(retcode=1)
    with pytest.raises(FileTransferError) as caught:
        asyncio.run(gateway.deliver(rejected, _ticket(tmp_path), target=target))
    assert caught.value.kind == "upload_rejected"

    failing = _RecordingOneBotBot(fail_with=ConnectionError("napcat gone"))
    with pytest.raises(FileTransferError) as caught:
        asyncio.run(gateway.deliver(failing, _ticket(tmp_path), target=target))
    assert caught.value.kind == "upload_failed_or_unknown"

    class _NoApiBot:
        pass

    with pytest.raises(FileTransferError) as caught:
        asyncio.run(gateway.deliver(_NoApiBot(), _ticket(tmp_path), target=target))
    assert caught.value.kind == "upload_api_unavailable"

    channel_target = _send_request([], scope=SessionType.CHANNEL)
    with pytest.raises(FileTransferError) as caught:
        asyncio.run(gateway.deliver(_RecordingOneBotBot(), _ticket(tmp_path), target=channel_target))
    assert caught.value.kind == "unsupported_file_target"

    vanished = _ticket(tmp_path)
    vanished.local_path.unlink()
    with pytest.raises(FileTransferError) as caught:
        asyncio.run(gateway.deliver(_RecordingOneBotBot(), vanished, target=target))
    assert caught.value.kind == "missing_file"


def test_deliver_onebot_honors_timeout_budget_slice(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.sender.onebot import _TimeoutBudget

    slices: list[float] = []

    class _SpyBudget:
        def slice_for(self, calls: int) -> float:
            slices.append(float(calls))
            return 5.0

    bot = _RecordingOneBotBot()
    asyncio.run(
        get_default_file_gateway().deliver(
            bot, _ticket(tmp_path), target=_send_request([]), budget=_SpyBudget()
        )
    )
    assert slices == [1.0]  # 单调用 deliver 按 1 段切片
    # 既有 _TimeoutBudget 传秒数值时直接生效（编排层已切片）。
    budget = _TimeoutBudget(15.0)
    assert 0 < budget.slice_for(2) <= 15.0


# -------------------- deliver：Telegram 文档通道 --------------------


class _FakeTelegramBot:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result if result is not None else {"message_id": 99}
        self.adapter = type("Adapter", (), {"get_name": staticmethod(lambda: "Telegram")})()

    async def send_document(self, **params):
        self.calls.append(params)
        return self.result


def test_deliver_telegram_document_params_and_caption_truncation(tmp_path: Path) -> None:
    bot = _FakeTelegramBot()
    body = b"tg doc"
    ticket = _ticket(tmp_path, name="doc.txt", body=body)
    receipt = asyncio.run(
        get_default_file_gateway().deliver(
            bot,
            ticket,
            target=_send_request([], scope=SessionType.PRIVATE, target_id="100"),
            transport="telegram",
            caption="长" * 1500,
        )
    )
    params = bot.calls[0]
    assert params["chat_id"] == "100"
    name, payload = params["document"]
    assert name == "doc.txt"
    assert payload == body  # 读全量字节的既有行为
    assert params["caption"] == "长" * 1000  # caption 截 1000 字
    assert receipt.provider_file_id == "99"
    assert receipt.transport == "telegram.document"


def test_deliver_telegram_rejects_oversize_before_send(tmp_path: Path) -> None:
    big = _ticket(tmp_path, name="big.bin", body=b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(FinalTransferError) as caught:
        asyncio.run(
            get_default_file_gateway().deliver(
                _FakeTelegramBot(),
                big,
                target=_send_request([], scope=SessionType.PRIVATE),
                transport="telegram",
            )
        )
    assert str(caught.value) == "invalid generated attachment"


# -------------------- golden：既有行为逐字锁定 --------------------


def test_golden_onebot_upload_then_caption_with_identical_params(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "generated.txt", "潮水平静\n".encode())
    request = _send_request(
        [{"type": "file", "file": str(path.resolve()), "name": "generated.txt"}]
    )
    bot = _RecordingOneBotBot()
    receipt = asyncio.run(send_onebot_v11(bot, request))
    assert receipt.state.value == "sent"
    # 时序：先上传、后文案（文案在全部上传成功之后补发）。
    assert [name for name, _ in bot.calls] == ["upload_group_file", "send_group_msg"]
    upload_params = bot.calls[0][1]
    assert upload_params["group_id"] == 12
    assert upload_params["file"] == str(path.resolve())
    assert upload_params["name"] == "generated.txt"
    assert bot.calls[1][1]["message"] == [{"type": "text", "data": {"text": "附件在此"}}]
    # 上传结果透传：终态回执仍由最后一次 API 结果决定。
    assert receipt.provider_message_id == "7"


def test_golden_missing_file_after_upload_never_resends(tmp_path: Path) -> None:
    first = _make_file(tmp_path, "first.bin", b"1")
    request = _send_request(
        [
            {"type": "file", "file": str(first.resolve()), "name": "first.bin"},
            {"type": "file", "file": str(tmp_path / "ghost.bin"), "name": "ghost.bin"},
        ],
        text="",
    )
    bot = _RecordingOneBotBot()
    receipt = asyncio.run(send_onebot_v11(bot, request))
    # 有副作用后绝不整体重投：终态 FAILED_FINAL，缺失文件按既有分类上报。
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "missing_file"
    # 第一次上传只有一次调用，且不补文案（上传未全部成功）。
    assert [name for name, _ in bot.calls] == ["upload_group_file"]


def test_golden_caption_failure_after_upload_is_result_unknown(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "ok.bin", b"x")

    class _CaptionFailsBot(_RecordingOneBotBot):
        async def send_group_msg(self, **params):
            self.calls.append(("send_group_msg", params))
            raise ConnectionError("caption lost")

    bot = _CaptionFailsBot()
    receipt = asyncio.run(
        send_onebot_v11(
            bot,
            _send_request([{"type": "file", "file": str(path.resolve()), "name": "ok.bin"}]),
        )
    )
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "caption_failed_after_upload"


def test_golden_retcode_rejected_upload_stops_delivery(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "rejected.bin", b"x")
    bot = _RecordingOneBotBot(retcode=1200)
    receipt = asyncio.run(
        send_onebot_v11(
            bot,
            _send_request([{"type": "file", "file": str(path.resolve()), "name": "rejected.bin"}]),
        )
    )
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "upload_rejected"


def test_golden_telegram_document_flow_through_gateway(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "tg.txt", b"tg body")
    bot = _FakeTelegramBot()
    receipt = asyncio.run(
        send_nonebot_message(
            bot,
            None,
            _send_request(
                [{"type": "file", "file": str(path.resolve()), "name": "tg.txt"}],
                scope=SessionType.PRIVATE,
                target_id="100",
                text="见附件",
            ),
        )
    )
    assert receipt.state.value == "sent"
    assert receipt.provider_message_id == "99"
    params = bot.calls[0]
    assert params["document"][0] == "tg.txt"
    assert params["document"][1] == b"tg body"
    assert params["caption"] == "见附件"


def test_golden_telegram_missing_attachment_is_final_before_send(tmp_path: Path) -> None:
    bot = _FakeTelegramBot()
    receipt = asyncio.run(
        send_nonebot_message(
            bot,
            None,
            _send_request(
                [{"type": "file", "file": str(tmp_path / "missing.txt"), "name": "missing.txt"}],
                scope=SessionType.PRIVATE,
                target_id="100",
            ),
        )
    )
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "invalid generated attachment"
    assert bot.calls == []  # 发送前即判定，绝不发出


def test_golden_telegram_oversize_attachment_is_final(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "big.bin", b"y" * (2 * 1024 * 1024 + 1))
    bot = _FakeTelegramBot()
    receipt = asyncio.run(
        send_nonebot_message(
            bot,
            None,
            _send_request(
                [{"type": "file", "file": str(path.resolve()), "name": "big.bin"}],
                scope=SessionType.PRIVATE,
                target_id="100",
            ),
        )
    )
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "invalid generated attachment"
    assert bot.calls == []


def test_golden_telegram_missing_receipt_id_escalates_to_result_unknown(tmp_path: Path) -> None:
    path = _make_file(tmp_path, "noid.txt", b"z")
    bot = _FakeTelegramBot(result={})  # send_document 回执缺 message_id
    receipt = asyncio.run(
        send_nonebot_message(
            bot,
            None,
            _send_request(
                [{"type": "file", "file": str(path.resolve()), "name": "noid.txt"}],
                scope=SessionType.PRIVATE,
                target_id="100",
            ),
        )
    )
    # 已送达部件后回执缺失 → 结果未知终态，上游不整体重投。
    assert receipt.state.value == "failed_final"
    assert receipt.operational_issue is not None
    assert receipt.operational_issue.kind == "result_unknown"
