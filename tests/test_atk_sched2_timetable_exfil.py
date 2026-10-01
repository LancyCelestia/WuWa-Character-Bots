"""S-FIX-ATK-SCHED2 票2（ATK-SCHED 审计票5）：课表识图本地读字节外传链断。

病根：旧 ``timetable._image_to_data_url`` 对本地路径自己 ``Path.read_bytes()``
→ base64 整块进外部 VLM 载荷（段字段可指 ``.env`` 一类秘密），无大小上限、
无格式白名单、不经判定——AGENTS「文件出站」在册裁定点名的第二通路。

修法口径：收编到媒体域识图腿既有咽喉（chat 视觉面同一构造，零新机制）——
http(s) 走 ``prepare_vision_image_urls``（中央 ``check_download_url`` + 逐跳
SSRF 复查；明确拒绝=丢图不回透 F-2），本地走 ``_image_file_to_data_url``
（大小上限+格式白名单+像素预算），全过不了 ⇒ **绝不空手敲 provider**。

锁面：
- 结构锁：timetable 件本体再无 ``read_bytes``/``base64`` 字样（第二通路不得复活）；
- 本地路径⇒ 统一后缀白名单（chat 视觉腿同一判据，本件不另起魔数判据）：
  白名单外（.txt/.env/日志一类秘密文件）⇒ 空串、provider 零调用、诚实空草稿；
- http 咽喉拒绝（RejectedUrlError）⇒ 丢图不回透，provider 零调用；
- http 合法字节 ⇒ data URL 进载荷（正常面不回归）；
- 真 1x1 PNG 本地文件 ⇒ 白名单直编码放行。
"""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
)
from plugins.bot_unified_runtime.domains.media.ingest import vision_describe as vd
from plugins.bot_unified_runtime.domains.schedule import timetable as tt
from plugins.bot_unified_runtime.domains.schedule.timetable import (
    _image_to_data_url,
    recognize_timetable,
)

# 1x1 合法 PNG（公开测试常量，非业务数据）。
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

_SECRET_BODY = b"BOT_SECRET_TOKEN=do-not-exfiltrate-9000\n"


class FakeVision:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate(self, messages: list[dict[str, object]], **kwargs: object) -> object:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


def _payload_blob(call: dict[str, object]) -> str:
    return json.dumps(call["messages"], ensure_ascii=False, default=str)


# ===========================================================================
# 结构锁：第二取字节通路不得复活
# ===========================================================================


def test_timetable_has_no_local_read_or_base64_leg() -> None:
    """AST 锁（非文本 grep）：docstring 里「病根回顾」提得到 read_bytes/base64，
    执法的是**代码面**不得再出现属性调用 ``.read_bytes()`` 或 base64 导入。"""
    src = Path(tt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "read_bytes", "timetable 内不得再自取本机字节"
        if isinstance(node, ast.Import):
            assert not any(
                alias.name == "base64" or alias.name.startswith("base64.")
                for alias in node.names
            ), "timetable 内不得再起编码通路"
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "base64"
    # 收编的在册判定口必须在场（防止改回透传了事）。
    assert "prepare_vision_image_urls" in src
    assert "_image_file_to_data_url" in src


# ===========================================================================
# 本地路径腿：白名单外一律空手（不外传一字节）
# ===========================================================================


def test_local_secret_text_yields_empty(tmp_path: Path) -> None:
    secret = tmp_path / "env_like.txt"
    secret.write_bytes(_SECRET_BODY)
    assert _image_to_data_url(str(secret)) == ""


def test_nonexistent_local_path_yields_empty(tmp_path: Path) -> None:
    assert _image_to_data_url(str(tmp_path / "nope.png")) == ""


def test_suffix_whitelist_is_the_judgment_gate(tmp_path: Path) -> None:
    """在册判定口的判据=后缀白名单（chat 视觉面同一家，不另起魔数判据）：
    探针5 的真目标（.env/.txt 一类秘密文件）一律空手；白名单后缀按原样字节
    直编码——这是咽喉在册行为，本票不私加更严的第二判据（那是媒体域的事）。"""
    dotenv = tmp_path / ".env"
    dotenv.write_bytes(_SECRET_BODY)
    assert _image_to_data_url(str(dotenv)) == ""
    log = tmp_path / "bot.log"
    log.write_bytes(_SECRET_BODY)
    assert _image_to_data_url(str(log)) == ""
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not really a png at all")
    # 白名单后缀照放（与 chat 视觉腿同口径）：判据同源，不是本件再造一道。
    assert _image_to_data_url(str(fake)).startswith("data:image/png;base64,")


def test_real_png_passes_whitelist(tmp_path: Path) -> None:
    good = tmp_path / "good.png"
    good.write_bytes(_PNG_1PX)
    url = _image_to_data_url(str(good))
    assert url.startswith("data:image/")
    assert base64.b64encode(_PNG_1PX).decode("ascii") in url  # 在册格式直编码


def test_data_url_passthrough_without_disk_touch() -> None:
    assert _image_to_data_url("data:image/png;base64,QUJD") == "data:image/png;base64,QUJD"
    assert _image_to_data_url("") == ""


# ===========================================================================
# 端到端：过不了在册口的图，绝不空手敲 provider、绝不含秘密字节
# ===========================================================================


def test_recognize_local_secret_never_calls_provider(tmp_path: Path) -> None:
    secret = tmp_path / "exfil.txt"
    secret.write_bytes(_SECRET_BODY)
    provider = FakeVision(json.dumps({"courses": []}))
    draft = recognize_timetable(provider, [str(secret)])
    assert provider.calls == []  # 修复前：read_bytes→base64 整块进载荷
    assert draft.courses == []


def test_recognize_drops_unreadable_keeps_fingerprint(tmp_path: Path) -> None:
    secret = tmp_path / "exfil2.txt"
    secret.write_bytes(b"pretend image bytes")
    provider = FakeVision("{}")
    draft = recognize_timetable(provider, [str(secret)], image_bytes=b"pretend image bytes")
    assert provider.calls == []
    assert draft.image_fingerprint == tt.fingerprint_image_bytes(b"pretend image bytes")


# ===========================================================================
# http 腿：中央咽喉语义（拒绝丢图 / 瞬时保留原 URL / 成功转 data URL）
# ===========================================================================


def test_http_rejected_by_guard_dropped_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    def _reject(url: str, **kwargs: object) -> bytes:
        raise RejectedUrlError("内网/保留段：咽喉在册拒绝")

    monkeypatch.setattr(vd, "_download_image_bytes", _reject)
    url = "http://169.254.169.254/latest/meta-data/img.png"
    assert _image_to_data_url(url) == ""  # F-2 口径：拒绝=丢图，绝不回透
    provider = FakeVision("{}")
    draft = recognize_timetable(provider, [url])
    assert provider.calls == [] and draft.courses == []


def test_http_transient_failure_keeps_original_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # 既有语义如实锁：公网判定成立但瞬时下载失败 ⇒ 保留原 URL 兜底（不是拒绝）。
    monkeypatch.setattr(vd, "_download_image_bytes", lambda url, **kw: None)
    url = "https://img.example-unique-a.invalid/a.png"
    assert _image_to_data_url(url) == url


def test_http_leg_forwards_guarded_bytes_as_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = "https://img.example-unique-b.invalid/timetable.png"
    monkeypatch.setattr(vd, "_download_image_bytes", lambda url, **kw: _PNG_1PX)
    provider = FakeVision(json.dumps({"courses": []}))
    recognize_timetable(provider, [ok])
    assert len(provider.calls) == 1
    blob = _payload_blob(provider.calls[0])
    assert "data:image/" in blob
    # QQ 签名 URL 类老坑同治：进载荷的是 bot 侧取回的字节编码，不再是原 URL 透传。
    assert ok not in blob


def test_recognize_real_png_still_reaches_provider(tmp_path: Path) -> None:
    """正常面不回归：合法本地图照常进多模态载荷（判定口放行≠一刀切禁用）。"""
    good = tmp_path / "timetable.png"
    good.write_bytes(_PNG_1PX)
    ocr = json.dumps(
        {
            "semester_start": "2026-09-07",
            "courses": [
                {
                    "course_name": "高等数学",
                    "weekday": 0,
                    "start_time": "08:00",
                    "end_time": "09:40",
                    "confidence": 0.9,
                }
            ],
        },
        ensure_ascii=False,
    )
    provider = FakeVision(ocr)
    draft = recognize_timetable(provider, [str(good)])
    assert len(provider.calls) == 1
    assert "data:image/" in _payload_blob(provider.calls[0])
    assert [c.course_name for c in draft.courses] == ["高等数学"]
