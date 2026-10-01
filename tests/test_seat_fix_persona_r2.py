"""S-FIX-PERSONA-R2：人格面四枚 MEDIUM（F-B/F-C/F-D/F-F）的修复锁。

逐票覆盖（全离线：tmp_path + fake transport + 注入式判定 policy，禁真机外发）：

- **F-D** 册子清单锚定：settings/knowledge 条目必须落在 ``personas/<id>/`` 子树
  （判定复用 ``domains/core/safety_exec/paths.py`` 唯一谓词，本域零抄尺）；
  越锚条目点名跳过（装载 warning 点名到文件名，绝不假成功）；
  docx 解压炸弹形态在 documents.py 侧加体积闸（无新配置键）。
- **F-C** 头像下发闸：装载时消毒（同一枚锚定口，URL 形态一律点名拒绝）＋
  ``apply_persona_profile`` 下发前 ``check_sendable`` 复核（装载时的放行态
  不作数：TOCTOU 锁）。
- **F-B** 回执打码：一切进 ``ItemReceipt.detail`` / ``summary()`` 的动态文本
  过 ``redact_local_secrets``（只 import 调用，绝不改咽喉真身）；
  缺文件异常只留文件名 + 缺失原因，不留全路径。
- **F-F** 重启静默回退：``refresh_from_qq`` 在回源 qlogo 前先经既有真身
  （InstanceSettingsManager 持久 override + 人格册）查在册本地头像，
  文件在 ⇒ 不覆盖卡片头像；禁读 ``get_login_info``（台账 #60 既有锁覆盖）。

触发词棘轮：本件不落 persona 语料，不触网。
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Self

import pytest

_ROOT = Path(__file__).resolve().parents[1]

from plugins.bot_unified_runtime.domains.chat_reply.character import documents
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)
from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
    PersonaProfileRecord,
    PersonaProfileRegistry,
    apply_persona_profile,
    main_persona_knowledge_files,
)
from plugins.bot_unified_runtime.domains.core.safety_exec import paths

DRIVE_FORM_RE = re.compile(r"[A-Za-z]:[\\/]")


def _write_profile(registry_dir: Path, persona_id: str, payload: dict) -> Path:
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"{persona_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _record(**kwargs: Any) -> PersonaProfileRecord:
    base = {
        "persona_id": "danya",
        "display_name": "达妮娅",
        # ②文本腿后补全在册形态：本件全部锁只考头像/打码面，文本腿按"在册带清单"
        # 给 ok 基线，不稀释各锁自身判据（显式传 settings_files=() 的锁另算）。
        "settings_files": ("personas/danya/identity.md",),
    }
    base.update(kwargs)
    return PersonaProfileRecord(**base)


class _FakeTransport:
    def __init__(self, *, fail_actions=(), raise_message: str | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail = set(fail_actions)
        self._raise_message = raise_message

    async def __call__(self, action: str, params: dict) -> dict:
        self.calls.append((action, params))
        if self._raise_message is not None:
            raise RuntimeError(self._raise_message)
        if action in self._fail:
            return {"retcode": 1001, "message": "风控拦截"}
        return {"retcode": 0, "data": {}}


class _FakeQrResponse:
    """假 qlogo 响应：PNG 头 + 填充字节（与 test_bot_avatar 既有形态同口径）。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _n: int) -> bytes:
        return self._payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


@pytest.fixture
def avatar_policy(tmp_path: Path) -> Path:
    """把路径域判定缺省策略注入到本测试的 tmp 根（既有测试注入口 set_default_policy）。

    工作区根＝tmp_path、运行数据根＝tmp_path/data：tmp 树内的头像可被判 allowed，
    tmp 树外（本机真实路径、URL 形态、禁触名册）一律拦。teardown 复位为惰性重建，
    不污染同进程其它测试。
    """
    policy = paths.build_policy(
        workspace_root=tmp_path, runtime_data_root=tmp_path / "data"
    )
    paths.set_default_policy(policy)
    try:
        yield tmp_path
    finally:
        paths.set_default_policy(None)


def _persona_avatar_file(root: Path) -> Path:
    avatar = root / "avatar" / "danya.jpg"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_bytes(b"\xff\xd8fake-jpg")
    return avatar


# ===========================================================================
# F-D ①：册子清单锚定 personas/<id>/ 子树，越锚点名跳过、绝不假成功
# ===========================================================================

def test_register_knowledge_kept_only_inside_persona_anchor(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    reg_dir = tmp_path / "registry"
    inside = tmp_path / "danya" / "knowledge" / "world.md"  # 锚＝registry 父目录/<persona_id>/
    inside.parent.mkdir(parents=True)
    inside.write_text("在册正文。\n", encoding="utf-8")
    outside = tmp_path / "stolen.md"
    outside.write_text("越锚正文。\n", encoding="utf-8")
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "qq": {"nickname": "达妮娅"},
            "files": {
                "settings": [],
                "knowledge": [str(inside), str(outside), "../escaped.md"],
            },
        },
    )
    registry = PersonaProfileRegistry(reg_dir)
    with caplog.at_level("WARNING"):
        record = registry.get("danya")
    assert record is not None
    # 在册条目被规范化为锚内绝对形态；越锚/穿越条目被点名跳过（不假成功、也不阻断）
    assert record.knowledge_files == (str(inside),)
    assert main_persona_knowledge_files("danya", registry=registry) == (str(inside),)
    text = caplog.text
    assert "stolen.md" in text and "escaped.md" in text  # 点名到文件名
    assert "outside persona anchor" in text


def test_register_knowledge_relative_entry_anchors_under_persona_dir(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    good = tmp_path / "danya" / "kb" / "x.md"
    good.parent.mkdir(parents=True)
    good.write_text("相对在册。\n", encoding="utf-8")
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "files": {"knowledge": ["kb/x.md"]}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.knowledge_files == (str(good),)


def test_register_settings_files_same_anchor_gate(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    outside = tmp_path / "envleak.txt"
    outside.write_text("x", encoding="utf-8")
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "files": {"settings": [str(outside)]}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.settings_files == ()


def test_unsafe_persona_id_drops_file_lists(tmp_path: Path) -> None:
    reg_dir = tmp_path / "registry"
    target = tmp_path / "else" / "x.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    _write_profile(
        reg_dir,
        "ghost",
        {
            "persona_id": "../else",  # persona_id 自带穿越段：锚不存在 ⇒ 清单全跳
            "files": {"knowledge": [str(target)]},
        },
    )
    record = PersonaProfileRegistry(reg_dir).get("../else")
    assert record is not None
    assert record.knowledge_files == ()


# ---------------------------------------------------------------------------
# F-D ②：docx 解压炸弹形态＝documents.py 侧体积闸（无新配置键）
# ---------------------------------------------------------------------------

def _mk_docx(path: Path, body: str) -> Path:
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    path.write_bytes(buffer.getvalue())
    return path


def test_docx_normal_file_still_parses(tmp_path: Path) -> None:
    docx = _mk_docx(tmp_path / "persona.docx", "正常正文")
    assert documents.load_character_document(docx) == "正常正文"


def test_docx_entry_decompressed_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents, "_DOCX_MAX_ENTRY_BYTES", 64)
    docx = _mk_docx(tmp_path / "bomb.docx", "字" * 400)  # document.xml 远超 64 字节
    with pytest.raises(ValueError) as exc:
        documents.load_character_document(docx)
    message = str(exc.value)
    assert "too large" in message
    assert "bomb.docx" in message
    assert str(tmp_path) not in message  # 消息只点名，不带全路径


def test_docx_declared_size_beyond_cap_rejected_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """声明尺寸超限 ⇒ 解压前即拒（中央目录声明腿是解压炸弹的第一形态）。

    构造注：`ZipFile.writestr` 会把传入 ZipInfo 的 file_size 覆写为真实长度
    （谎报声明手工造不出来），故这里用**经典真炸弹形态**：高可压巨型条目
    （20000 个 '0'，容器几十字节、声明解压尺寸 20000）＋ read 哨兵，
    锁「在 read 之前就被声明腿拦下」。
    """
    monkeypatch.setattr(documents, "_DOCX_MAX_ENTRY_BYTES", 64)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "0" * 20000)
    docx = tmp_path / "declared.docx"
    docx.write_bytes(buffer.getvalue())

    def _no_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("declared-size 腿必须在解压 read 之前拦截")

    monkeypatch.setattr(zipfile.ZipFile, "read", _no_read)
    with pytest.raises(ValueError) as exc:
        documents.load_character_document(docx)
    assert "too large" in str(exc.value)


def test_docx_source_file_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents, "_DOCX_MAX_SOURCE_BYTES", 16)
    docx = tmp_path / "fat.docx"
    docx.write_bytes(b"0" * 4096)
    with pytest.raises(ValueError) as exc:
        documents.load_character_document(docx)
    assert "too large" in str(exc.value)
    assert "fat.docx" in str(exc.value)


def test_character_document_error_messages_name_only(tmp_path: Path) -> None:
    """F-B 同口径：读文档的异常消息只留文件名，不留全路径。"""
    missing = tmp_path / "deep" / "nest" / "gone.md"
    with pytest.raises(FileNotFoundError) as exc:
        documents.load_character_document(missing)
    message = str(exc.value)
    assert "gone.md" in message
    assert str(tmp_path) not in message
    assert not DRIVE_FORM_RE.search(message), message


# ===========================================================================
# F-C：头像装载消毒 + 下发前复核 + URL 形态一律点名拒绝
# ===========================================================================

def test_avatar_url_form_named_and_dropped_at_load(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """URL 形态一律拒（取舍＝不接 check_download_url：册子头像无远程合法形态）。"""
    reg_dir = tmp_path / "registry"
    for index, form in enumerate(
        (
            "http://127.0.0.1:3001/x.jpg",
            "https://169.254.169.254/latest/meta-data",
            "file:///C:/Windows/win.ini",
        )
    ):
        persona_id = f"danya{index}"
        _write_profile(
            reg_dir, persona_id, {"persona_id": persona_id, "qq": {"avatar_path": form}}
        )
        with caplog.at_level("WARNING"):
            record = PersonaProfileRegistry(reg_dir).get(persona_id)
        assert record is not None
        assert record.qq_avatar_path == "", form
        assert record.avatar_rejected_reason != "", form
        # 理由必须诚实点名 URL 形态（摘掉 scheme 腿的毒件会借 ADS 腿"歪打正着"，
        # 但理由会说谎——这条断言钉住「形态判定在前」的口径）。
        assert "URL" in record.avatar_rejected_reason, form
    assert "avatar" in caplog.text


def test_avatar_outside_allowed_roots_dropped_at_load(tmp_path: Path, avatar_policy: Path) -> None:
    reg_dir = tmp_path / "registry"
    outside = avatar_policy.parent / "definitely" / "outside" / "secret.jpg"
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "qq": {"avatar_path": str(outside)}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.qq_avatar_path == ""
    assert record.avatar_rejected_reason != ""


def test_avatar_inside_allowed_roots_kept_verbatim(tmp_path: Path, avatar_policy: Path) -> None:
    """语义不减弱：允许根内的既有在册头像原样保留（danya 现网形态）。"""
    reg_dir = tmp_path / "registry"
    avatar = _persona_avatar_file(avatar_policy)
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "qq": {"avatar_path": str(avatar)}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.qq_avatar_path == str(avatar)
    assert record.avatar_rejected_reason == ""
    assert record.resolved_avatar == str(avatar)


def test_windows_drive_form_is_path_not_url(tmp_path: Path, avatar_policy: Path) -> None:
    """盘符形态不许被当成 URL scheme 误杀（8.3/盘符陷阱同族教训）。"""
    reg_dir = tmp_path / "registry"
    avatar = avatar_policy / "drive" / "x.jpg"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"\xff\xd8")
    _write_profile(
        reg_dir, "danya", {"persona_id": "danya", "qq": {"avatar_path": str(avatar)}}
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.qq_avatar_path == str(avatar)


def test_data_relative_avatar_kept_under_runtime_root(tmp_path: Path, avatar_policy: Path) -> None:
    """现网登记口径 ``data/avatar/…``：相对形态经判定件自己的 data 锚仍放行。"""
    reg_dir = tmp_path / "registry"
    avatar = avatar_policy / "data" / "avatar" / "p.jpg"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"\xff\xd8")
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "qq": {"avatar_path": "data/avatar/p.jpg"}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    assert record.qq_avatar_path == "data/avatar/p.jpg"
    assert record.avatar_rejected_reason == ""


def test_load_rejected_avatar_receipt_fails_not_fakes(
    tmp_path: Path, avatar_policy: Path
) -> None:
    """装载被拦的头像 ⇒ 下发回执必须 failed 点名（不是 skipped 假成功）。"""
    record = _record(qq_nickname="达妮娅", avatar_rejected_reason="url_form_rejected")
    transport = _FakeTransport()
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=lambda _p: None)
    )
    assert [name for name, _ in transport.calls] == ["set_qq_profile"]
    statuses = {item.item: item.status for item in receipt.items}
    assert statuses["qq_avatar"] == "failed"
    assert statuses["card_avatar"] == "skipped"
    assert receipt.fully_applied is False
    assert "未完全切换" in receipt.summary()


def test_dispatch_rechecks_sendability_even_after_clean_load(
    tmp_path: Path, avatar_policy: Path
) -> None:
    """TOCTOU 锁：装载时合法的头像，下发瞬间允许根换掉 ⇒ 下发前复核必须拦。"""
    reg_dir = tmp_path / "registry"
    avatar = _persona_avatar_file(avatar_policy)
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "qq": {"avatar_path": str(avatar)}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None and record.qq_avatar_path == str(avatar)

    other_root = avatar_policy / "elsewhere"
    paths.set_default_policy(
        paths.build_policy(
            workspace_root=other_root, runtime_data_root=other_root / "data"
        )
    )
    try:
        transport = _FakeTransport()
        receipt = asyncio.run(
            apply_persona_profile(
                record, call_api=transport, card_avatar_hook=lambda _p: None
            )
        )
    finally:
        paths.set_default_policy(None)
    assert [name for name, _ in transport.calls] == []
    statuses = {item.item: item.status for item in receipt.items}
    assert statuses["qq_avatar"] == "failed"


def test_allowed_avatar_dispatches_file_param_verbatim(tmp_path: Path, avatar_policy: Path) -> None:
    """功能不减弱：过闸头像照常把解析后的路径交给唯一出站通道。"""
    avatar = _persona_avatar_file(avatar_policy)
    record = _record(qq_avatar_path=str(avatar))
    transport = _FakeTransport()
    cards: list[str] = []
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=cards.append)
    )
    assert transport.calls and transport.calls[0][0] == "set_qq_avatar"
    assert transport.calls[0][1]["file"] == str(avatar)
    assert receipt.fully_applied is True
    assert cards == [str(avatar)]


def test_register_avatar_gate_never_reaches_transport_on_url(
    tmp_path: Path, avatar_policy: Path
) -> None:
    """装载被拦（URL 形态）的册子头像 ⇒ apply 后 set_qq_avatar 一发都不许出门。"""
    reg_dir = tmp_path / "registry"
    _write_profile(
        reg_dir,
        "danya",
        {"persona_id": "danya", "qq": {"avatar_path": "http://127.0.0.1:3001/a.jpg"}},
    )
    record = PersonaProfileRegistry(reg_dir).get("danya")
    assert record is not None
    transport = _FakeTransport()
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=lambda _p: None)
    )
    assert all(name != "set_qq_avatar" for name, _ in transport.calls)
    failed = {item.item for item in receipt.items if item.is_failed}
    assert "qq_avatar" in failed


# ===========================================================================
# F-B：回执文本过中央打码件；缺文件异常只留文件名
# ===========================================================================

def test_receipt_details_redacted_for_exception_with_paths(
    tmp_path: Path, avatar_policy: Path
) -> None:
    avatar = _persona_avatar_file(avatar_policy)
    record = _record(qq_nickname="达妮娅", qq_avatar_path=str(avatar))
    leaky = (
        "upload failed for C:/Users/Someone/Desktop/persona.jpg "
        "BOT_API_KEY=sk-abcdef1234567890"
    )
    transport = _FakeTransport(raise_message=leaky)
    receipt = asyncio.run(
        apply_persona_profile(record, call_api=transport, card_avatar_hook=lambda _p: None)
    )
    summary = receipt.summary()
    assert "sk-abcdef1234567890" not in summary
    assert not DRIVE_FORM_RE.search(summary), summary
    assert "RuntimeError" in summary  # 类型名与「未完全切换」点名仍在（诊断不塌）
    for item in receipt.items:
        assert "sk-abcdef1234567890" not in item.detail
        assert not DRIVE_FORM_RE.search(item.detail), item.detail


def test_receipt_details_redacted_for_platform_message(
    tmp_path: Path, avatar_policy: Path
) -> None:
    avatar = _persona_avatar_file(avatar_policy)
    record = _record(qq_avatar_path=str(avatar))

    class _MsgTransport:
        async def __call__(self, action: str, params: dict) -> dict:
            return {"retcode": 2000, "message": "bad file C:/Temp/x.png sk-9988776655"}

    receipt = asyncio.run(
        apply_persona_profile(record, call_api=_MsgTransport(), card_avatar_hook=lambda _p: None)
    )
    summary = receipt.summary()
    assert "sk-9988776655" not in summary
    assert not DRIVE_FORM_RE.search(summary), summary


def test_default_card_avatar_hook_missing_names_filename_only(tmp_path: Path) -> None:
    missing = tmp_path / "deep" / "nest" / "avatar.png"
    with pytest.raises(FileNotFoundError) as exc:
        pp._default_card_avatar_hook(str(missing))
    message = str(exc.value)
    assert "avatar.png" in message
    assert str(tmp_path) not in message
    assert not DRIVE_FORM_RE.search(message), message


def test_ok_card_receipt_detail_has_no_local_path(
    tmp_path: Path, avatar_policy: Path
) -> None:
    avatar = _persona_avatar_file(avatar_policy)
    record = _record(qq_avatar_path=str(avatar))
    receipt = asyncio.run(
        apply_persona_profile(
            record, call_api=_FakeTransport(), card_avatar_hook=lambda _p: None
        )
    )
    card = next(item for item in receipt.items if item.item == "card_avatar")
    assert card.status == "ok"
    assert str(avatar) not in card.detail
    assert not DRIVE_FORM_RE.search(card.detail), card.detail


# ===========================================================================
# F-F：connect 腿回源 qlogo 前先读在册本地头像（经既有真身）
# ===========================================================================

@pytest.fixture
def bot_avatar_state():
    from plugins.bot_unified_runtime.domains.render import bot_avatar

    original = bot_avatar._LOCAL_AVATAR_URI
    yield bot_avatar
    bot_avatar._LOCAL_AVATAR_URI = original


def _wire_override_and_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, override: str
) -> tuple[Path, Path]:
    """铺 data/settings/runtime_settings_default.json 的持久 override + tmp 人格册。

    返回 (Runtime 数据根, 在册头像文件)。人格册指到 tmp（DEFAULT_REGISTRY_DIR
    注入），teardown 必须 ``pp.reset_shared_registry_for_tests()`` 复位共享单例。
    """
    data_dir = tmp_path / "rt" / "data"
    settings_dir = data_dir / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "runtime_settings_default.json").write_text(
        json.dumps({"persona_override": override}), encoding="utf-8"
    )
    reg_dir = tmp_path / "personas" / "registry"
    avatar = _persona_avatar_file(tmp_path)
    _write_profile(
        reg_dir,
        "danya",
        {
            "persona_id": "danya",
            "qq": {"nickname": "达妮娅", "avatar_path": str(avatar)},
        },
    )
    monkeypatch.setattr(pp, "DEFAULT_REGISTRY_DIR", reg_dir)
    pp.reset_shared_registry_for_tests()
    return data_dir, avatar


def test_connect_leg_keeps_persona_avatar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    avatar_policy: Path,
    bot_avatar_state,
) -> None:
    """重启语义：override=danya 且在册头像文件在 ⇒ 不回源不覆盖，卡片头像是册子图。"""
    data_dir, avatar = _wire_override_and_registry(tmp_path, monkeypatch, override="danya")

    def _no_network(*args: Any, **kwargs: Any):
        raise AssertionError("persona 在册头像在场时禁止回源 qlogo")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    try:
        uri = bot_avatar_state.refresh_from_qq("8887340775", data_dir)
        assert uri == Path(avatar).as_uri()
        assert bot_avatar_state._LOCAL_AVATAR_URI == Path(avatar).as_uri()
        # qlogo 落盘件不许被创建（没下载就没落盘）
        assert not (data_dir / "avatar" / "bot_8887340775.png").exists()
    finally:
        pp.reset_shared_registry_for_tests()


def test_no_override_still_refreshes_qq(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    avatar_policy: Path,
    bot_avatar_state,
) -> None:
    """无覆盖（主人格）⇒ 今天那条 qlogo 腿行为不变。"""
    data_dir, _avatar = _wire_override_and_registry(tmp_path, monkeypatch, override="")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeQrResponse(b"\x89PNG" + b"0" * 100)
    )
    try:
        uri = bot_avatar_state.refresh_from_qq("123", data_dir)
        assert uri == (data_dir / "avatar" / "bot_123.png").as_uri()
    finally:
        pp.reset_shared_registry_for_tests()


def test_divergent_overrides_fall_back_to_qq(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    avatar_policy: Path,
    bot_avatar_state,
) -> None:
    """多实例覆盖不一致 ⇒ 不表态（维持今天的 qlogo 腿，不乱钉图）。"""
    data_dir, _avatar = _wire_override_and_registry(tmp_path, monkeypatch, override="danya")
    (data_dir / "settings" / "runtime_settings_other.json").write_text(
        json.dumps({"persona_override": "legacy"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeQrResponse(b"\x89PNG" + b"0" * 100)
    )
    try:
        uri = bot_avatar_state.refresh_from_qq("999", data_dir)
        assert uri == (data_dir / "avatar" / "bot_999.png").as_uri()
    finally:
        pp.reset_shared_registry_for_tests()


def test_registered_avatar_missing_file_falls_back_to_qq(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    avatar_policy: Path,
    bot_avatar_state,
) -> None:
    """在册头像文件缺失 ⇒ 回源 qlogo 既有兜底腿照常（不钉一枚读不到的图）。"""
    data_dir, avatar = _wire_override_and_registry(tmp_path, monkeypatch, override="danya")
    Path(avatar).unlink()
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeQrResponse(b"\x89PNG" + b"0" * 50)
    )
    try:
        uri = bot_avatar_state.refresh_from_qq("555", data_dir)
        assert uri == (data_dir / "avatar" / "bot_555.png").as_uri()
    finally:
        pp.reset_shared_registry_for_tests()


# ===========================================================================
# 结构锁：判定零抄尺 + 现网 danya 在册头像不回归
# ===========================================================================

def test_fix_code_does_not_reimplement_containment() -> None:
    """F-D/F-C 的锚定与出站判定必须全部问 paths.py，本域不许自拼包含判据。"""
    source = (
        _ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/character/persona_profile.py"
    ).read_text(encoding="utf-8")
    import ast as _ast

    tree = _ast.parse(source)
    violations: list[str] = []
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Attribute)
            and node.func.attr in ("relative_to", "commonpath")
        ):
            violations.append(node.func.attr)
    assert not violations, f"出现第二把锚定尺（自己算包含）：{violations}"


@pytest.mark.skipif(
    not (Path(pp.DEFAULT_REGISTRY_DIR) / "danya.json").is_file()
    or not (
        Path(__file__).resolve().parents[2]
        / "ChatBot_Runtime"
        / "data"
        / "avatar"
        / "persona_avatar_danya_1080.jpg"
    ).is_file(),
    reason="现网人格册或 danya 头像不在本机（开发机现算执法）",
)
def test_live_danya_avatar_survives_new_gates() -> None:
    """现网在册 danya 头像（data/avatar/…）必须同时过装载闸与下发闸（功能不减弱）。"""
    paths.set_default_policy(None)  # 用真实根判定
    record = PersonaProfileRegistry().get("danya")
    assert record is not None
    assert record.qq_avatar_path != "" and record.avatar_rejected_reason == ""
    ok, reason = pp._avatar_sendable(record.resolved_avatar)
    assert ok, reason
