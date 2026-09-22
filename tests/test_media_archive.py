"""媒体归档能力回归锁（bot.media_archive，2026-09-13 新能力）。

覆盖：触发判定（含胶合拒绝）、路由判定、角色门（默认仅超管）、本地媒体归档
（VLM 判 类别×IP）、指令覆盖参数、VLM 失败降级、sha256 去重、路径穿越消毒、
聊天记录 Markdown 归档、每日额度、data/ 路径重映射、SSRF 拒绝不中断整批
（审查 F-06）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
)
from plugins.bot_unified_runtime.domains.media.archive.media_archive import (
    UNKNOWN_IP,
    MediaArchiveStore,
    sanitize_dirname,
)
from plugins.bot_unified_runtime.domains.media.capabilities import (
    media_archive as media_archive_module,
)
from plugins.bot_unified_runtime.domains.media.capabilities.media_archive import (
    build_media_archive_capability,
    is_media_archive_command,
    parse_archive_args,
)
from plugins.bot_unified_runtime.runtime.base_router import (
    RouteKind,
    classify_message_route,
    clear_route_decision_cache,
)

# ---------------------------------------------------------------------------
# 触发判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "收藏",
        "归档",
        "存图",
        "收图",
        "存聊天记录",
        "存记录",
        "archive",
        "shoucang",
        "guidang",
        "收藏 分类=cosplay IP=鸣潮",
        "归档，帮我收一下",
    ],
)
def test_trigger_hits(text: str) -> None:
    assert is_media_archive_command(text) is True


@pytest.mark.parametrize(
    "text",
    ["", "收藏夹整理好了", "归档表在哪里", "shoucangqq", "archiveqq", "随口聊聊收藏的事"],
)
def test_trigger_glued_or_unrelated_misses(text: str) -> None:
    assert is_media_archive_command(text) is False


def test_parse_args() -> None:
    args = parse_archive_args("收藏 分类=cosplay IP=鸣潮 角色=桃祈 子路径=我的收藏")
    assert args["category"] == "cosplay"
    assert args["ip"] == "鸣潮"
    assert args["character"] == "桃祈"
    assert args["subpath"] == "我的收藏"


# ---------------------------------------------------------------------------
# 路由判定
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_route_cache() -> None:
    clear_route_decision_cache()


@pytest.mark.parametrize("text", ["收藏", "归档", "archive"])
def test_routes_to_media_archive(text: str) -> None:
    decision = classify_message_route(text, config=object(), alias_resolver=None)
    assert decision.kind is RouteKind.MEDIA_ARCHIVE
    assert decision.capability_id == "bot.media_archive"


# ---------------------------------------------------------------------------
# 能力行为（tmp store + 假 VLM）
# ---------------------------------------------------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
FAKE_VLM_JSON = json.dumps(
    {
        "category": "cosplay",
        "ip_source": "鸣潮",
        "character": "桃祈",
        "description": "桃祈的cosplay照",
        "tags": ["cosplay", "鸣潮"],
        "nsfw_score": 0.0,
    },
    ensure_ascii=False,
)


class _FakeProvider:
    def __init__(self, text: str = FAKE_VLM_JSON, fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    def generate(self, messages, temperature=0.1, max_tokens=300):
        if self.fail:
            raise RuntimeError("vlm down")
        return SimpleNamespace(text=self.text)


def _config(tmp_path: Path, **overrides):
    base = {
        "bot_media_archive_enabled": True,
        "bot_media_archive_min_role": "super_admin",
        "bot_media_archive_max_file_mb": 20,
        "bot_media_archive_daily_limit": 50,
        "bot_media_archive_per_message_limit": 4,
        "bot_media_archive_summary_enabled": False,
        "bot_media_archive_video_frames": 5,
        "bot_vision_timeout_seconds": 5.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(**overrides) -> IncomingMessage:
    fields = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "bot",
        "session_id": "session_1",
        "session_type": SessionType.PRIVATE,
        "sender_id": "10000",
        "sender_roles": ["super_admin"],
        "plain_text": "收藏",
        "raw_segments": [],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)


def _store(tmp_path: Path) -> MediaArchiveStore:
    return MediaArchiveStore(tmp_path / "db.sqlite3", tmp_path / "archive")


def _capability(tmp_path: Path, provider=None, store=None, **cfg):
    return build_media_archive_capability(
        _config(tmp_path, **cfg),
        vision_provider=provider,
        store=store or _store(tmp_path),
    )


def _image_file(tmp_path: Path) -> str:
    """生成一张真实的 4x4 红 PNG（PIL 可解码，走完整 VLM 链路）。"""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buffer, format="PNG")
    image = tmp_path / "sample.png"
    image.write_bytes(buffer.getvalue())
    return str(image)


def test_role_gate_denies_non_super_admin(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    result = capability(_message(sender_roles=["user"], raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "超管" in result.body
    assert "denied_role" in result.audit_tags


def test_admin_role_passes_gate(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider(), bot_media_archive_min_role="admin")
    result = capability(_message(sender_roles=["admin"], raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "✔" in result.body


def test_vlm_classification_and_layout(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    result = capability(_message(raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "cosplay/鸣潮" in result.body
    saved = list((tmp_path / "archive").rglob("*.png"))
    assert len(saved) == 1
    assert saved[0].parent.parent.name == "cosplay"
    assert saved[0].with_suffix(".json").exists()
    sidecar = json.loads(saved[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["ip_source"] == "鸣潮"
    assert sidecar["character"] == "桃祈"


def test_args_override_vlm(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    result = capability(_message(plain_text="收藏 分类=二次元插图 IP=碧蓝航线", raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "二次元插图/碧蓝航线" in result.body


def test_vlm_failure_degrades_by_type(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider(fail=True))
    result = capability(_message(raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "照片" in result.body
    assert "未分析" in result.body


def test_no_provider_degrades(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=None)
    result = capability(_message(raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert "未分析" in result.body


def test_sha256_dedup(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    segments = [{"type": "image", "data": {"path": _image_file(tmp_path)}}]
    first = capability(_message(raw_segments=segments), None)
    second = capability(_message(raw_segments=segments), None)
    assert "✔" in first.body
    assert "↺" in second.body
    assert len(list((tmp_path / "archive").rglob("*.png"))) == 1


def test_path_traversal_sanitized(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    result = capability(_message(plain_text="收藏 IP=../../Windows", raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    root = (tmp_path / "archive").resolve()
    saved_files = [p for p in root.rglob("*") if p.is_file()]
    assert saved_files, "至少归档一件"
    for saved in saved_files:
        resolved = saved.resolve()
        assert root == resolved or root in resolved.parents
        assert ".." not in saved.relative_to(root).as_posix()
    assert "../" not in result.body


def test_no_media_hint(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider())
    result = capability(_message(plain_text="收藏"), None)
    assert "同一条消息" in result.body
    assert "no_media" in result.audit_tags


def test_chat_record_markdown(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=None)
    message = _message(
        plain_text="存聊天记录",
        chat_record_text="Alice：今晚吃什么\nBob：随便",
    )
    result = capability(message, None)
    assert "聊天记录" in result.body
    saved = list((tmp_path / "archive").rglob("*.md"))
    assert len(saved) == 1
    content = saved[0].read_text(encoding="utf-8")
    assert "Alice：今晚吃什么" in content


def test_daily_quota(tmp_path: Path) -> None:
    store = _store(tmp_path)
    capability = _capability(tmp_path, provider=_FakeProvider(), store=store, bot_media_archive_daily_limit=1)
    image = _image_file(tmp_path)
    capability(_message(raw_segments=[{"type": "image", "data": {"path": image}}]), None)
    other = tmp_path / "second.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 64)
    blocked = capability(_message(raw_segments=[{"type": "image", "data": {"path": str(other)}}]), None)
    assert "额度用完" in blocked.body


def test_disabled_capability_skips(tmp_path: Path) -> None:
    capability = _capability(tmp_path, provider=_FakeProvider(), bot_media_archive_enabled=False)
    result = capability(_message(raw_segments=[
        {"type": "image", "data": {"path": _image_file(tmp_path)}}
    ]), None)
    assert result.body == ""
    assert "skip_no_trigger" in result.audit_tags


def test_config_paths_resolve_to_runtime() -> None:
    config = Config()
    archive_dir = Path(str(config.bot_media_archive_dir))
    db_path = Path(str(config.bot_media_archive_db_path))
    assert archive_dir.is_absolute()
    assert db_path.is_absolute()
    assert archive_dir.name == "media_archive"


def test_unknown_ip_fallback_constant() -> None:
    assert UNKNOWN_IP == "未识别"


# ---------------------------------------------------------------------------
# 评审修复回归锁（2026-09-13 终审 I-2/I-3/M-4）
# ---------------------------------------------------------------------------


def test_newline_boundary_triggers() -> None:
    """I-3：换行归一为空格——多行输入（收藏\n分类=x）必须照常触发。"""
    assert is_media_archive_command("收藏\n分类=cosplay") is True
    assert is_media_archive_command("归档\r\nIP=鸣潮") is True


def test_guidance_replies_are_sendable(tmp_path: Path) -> None:
    """I-2：引导/拒绝文案必须 IMMEDIATE（SILENT_AUDIT 会整体静默）。"""
    capability = _capability(tmp_path, provider=_FakeProvider())
    denied = capability(_message(sender_roles=["user"]), None)
    assert denied.send_policy == SendPolicy.IMMEDIATE
    hint = capability(_message(plain_text="收藏"), None)
    assert hint.send_policy == SendPolicy.IMMEDIATE
    assert "同一条消息" in hint.body


def test_store_subpath_boundary() -> None:
    """M-4：subpath 消毒收敛在 store 边界，给什么都逃不出归档根。"""
    import tempfile
    from pathlib import Path as _Path

    root = _Path(tempfile.mkdtemp())
    store = MediaArchiveStore(root / "db.sqlite3", root / "archive")
    _record, target, _dup = store.save(
        PNG_BYTES.replace(b"\x00" * 64, b"\x02" * 64),
        media_type="image",
        category="照片",
        ip_source="测试",
        subpath="../evil",
    )
    resolved = target.resolve()
    assert (root / "archive").resolve() in resolved.parents
    assert "evil" in resolved.parts[-2].lower() or "evil" not in str(target)


def test_reserved_windows_names_prefixed() -> None:
    """M-4：CON/NUL 等保留设备名加下划线前缀，mkdir 不再抛 OSError。"""
    assert sanitize_dirname("CON") == "_CON"
    assert sanitize_dirname("nul") == "_nul"


# ---------------------------------------------------------------------------
# 审查 F-06 回归锁：SSRF 拒绝信号（RejectedUrlError）不得逃逸中断整批
# ---------------------------------------------------------------------------

# 公网字面量 IP（example.com 历史 A 记录）：check_download_url 对字面量
# IP 不做 DNS，离线确定性放行；随后由假 opener 模拟重定向逐跳护栏
# （_GuardedRedirectHandler 在 open() 内部）抛 RejectedUrlError。
_PUBLIC_LITERAL_URL = "http://93.184.216.34/pic.png"

_ARCHIVE_LOGGER = "plugins.bot_unified_runtime.domains.media.capabilities.media_archive"


class _RedirectGuardFakeOpener:
    """模拟真实传播形态：_GuardedRedirectHandler 先 WARNING 留痕再抛出，
    open() 内部冒出 RejectedUrlError（字面 IP 127.0.0.1 命中内网网段分支）。"""

    def open(self, request, timeout=20.0):
        logging.getLogger(_ARCHIVE_LOGGER).warning(
            "media archive SSRF guard rejected redirect: 该地址属于内网/保留网段，已拒绝"
            " (url=http://127.0.0.1:9/evil.png)"
        )
        raise RejectedUrlError("该地址属于内网/保留网段，已拒绝")


def test_rejected_url_does_not_abort_batch(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """F-06：一件坏 URL 被拒后记 WARNING 并跳过，后续正常条目照常归档。"""
    capability = _capability(tmp_path, provider=_FakeProvider())
    image = _image_file(tmp_path)
    with (
        caplog.at_level(logging.WARNING, logger=_ARCHIVE_LOGGER),
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(media_archive_module, "_OPENER", _RedirectGuardFakeOpener())
        result = capability(_message(raw_segments=[
            {"type": "image", "data": {"url": _PUBLIC_LITERAL_URL}},
            {"type": "image", "data": {"path": image}},
        ]), None)
    assert "✔" in result.body, "坏 URL 之后的好条目必须照常归档（F-06 主断言）"
    assert "skip_image" in result.audit_tags
    saved = list((tmp_path / "archive").rglob("*.png"))
    assert len(saved) == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("SSRF guard rejected" in r.getMessage() for r in warnings), "拒绝必须 WARNING 留痕"


def test_entry_rejection_logged_with_redacted_url(caplog: pytest.LogCaptureFixture) -> None:
    """F-06：入口拒绝 WARNING 留痕，URL 形态过既有脱敏（userinfo 打码）。"""
    with caplog.at_level(logging.WARNING, logger=_ARCHIVE_LOGGER):
        assert media_archive_module._fetch_url_media(
            "http://user:supersecret@127.0.0.1:9/pic.png", 1000
        ) is None
    assert not any(r.levelno == logging.ERROR for r in caplog.records)
    text = "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "该地址属于内网/保留网段" in text, "字面 IP 命中内网网段分支，拒绝原因必须留痕"
    assert "supersecret" not in text, "脱敏后的 URL 才允许进日志"
    assert "已隐藏" in text


def test_redirect_rejection_raises_after_logging(caplog: pytest.LogCaptureFixture) -> None:
    """F-06：重定向护栏拒绝时先 WARNING 留痕再上抛，由捕获点收口跳过。"""
    handler = media_archive_module._GuardedRedirectHandler()
    with (
        caplog.at_level(logging.WARNING, logger=_ARCHIVE_LOGGER),
        pytest.raises(RejectedUrlError),
    ):
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:9/x")
    text = "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "rejected redirect" in text
    assert "该地址属于内网/保留网段" in text
