"""F-01 作用域锁（SEAT-ATK-WEBUI 发现，SEAT-FIX-WEBUIMA 根修，2026-09-27）。

背景：``POST /api/v1/media/analyze`` 曾把 ``image_urls``/``audio_source``/
``video_source`` 以 ``str(payload…)`` 原样转发给 ingest 真身，而 ingest 的本地
支路（``_local_path_from_value``/ffmpeg 直喂）对路径零来源约束 ⇒ 持**只读令牌**
者可对本机任意媒体可读文件做"格式受限的任意读 + 文本回显"，整体旁路
``/files/read`` 的登记根白名单（SEAT-ATK-CP F-1/F-3 根修产物）。

修法（本件钉死）：三源本地形态改走 ``file_access.FileReadGateway`` 同一守卫
中央件的新口 ``admit_media_source``（登记根按段判成员 + 敏感子树/后缀/名字
禁区 + 媒体容器后缀许可集，两侧 resolve、禁 startswith）；远程/数据形态
(http/https/data:) 原样放行（SSRF 咽喉在 ingest 下游，F-03 另票不混修）；
未知 scheme 与越界路径一律 fail-closed。**HTTP 回执把全部本地拒因折叠为
单一码**——"存在但越界"与"不存在"逐字节同形，杜绝存在性探测。

判据纪律（在册教训）：8.3 短名与大小写变体在两侧 resolve 后折叠成同一真实
路径——登记根外的短名/变形形态必须仍拒，根内的短名必须仍可放（正面锁）；
守卫排在任何 stat/open/ingest 之前，拒绝路径零文件触达。全部离线：
``tmp_path`` + ``monkeypatch.chdir`` + ingest 真身打桩，不碰真实工作树。
"""

from __future__ import annotations

import ast
import ctypes
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.platform import build_platform_router
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.file_access import (
    FileGatewayError,
    FileReadGateway,
)
from plugins.bot_unified_runtime.control_plane.platform import PlatformStore

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_PY = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "control_plane" / "api" / "platform.py"
)
_VISION = "plugins.bot_unified_runtime.domains.media.ingest.vision_describe"
_TRANSCRIBE = "plugins.bot_unified_runtime.domains.media.ingest.transcribe"

_PNG = bytes.fromhex("89504e470d0a1a0a")  # PNG 魔数 + 填充，内容无意义
REJECT = (422, "media_source_rejected", "媒体来源未通过读取校验。")


async def _read_dep() -> Principal:
    return Principal("test-read", ("admin",))


async def _write_dep() -> Principal:
    return Principal("test-root", ("super_admin", "admin"))


def _harness(roots: Any) -> tuple[FastAPI, dict[str, Any]]:
    """真实 build_platform_router + ingest 真身打桩记录仪。"""
    recorder: dict[str, Any] = {}
    app = FastAPI()
    config = None if roots is None else SimpleNamespace(bot_control_plane_files_roots=roots)
    app.include_router(
        build_platform_router(
            store=PlatformStore(":memory:"),
            read_dependency=_read_dep,
            write_dependency=_write_dep,
            prefix="/api/v1",
            config=config,
        )
    )

    @app.exception_handler(ControlPlaneError)
    async def _handle(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app, recorder


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """私有哨兵树：srvroot 登记根产物、out 根外实体、敏感形态各就各位。"""
    (tmp_path / "srvroot").mkdir()
    (tmp_path / "srvroot" / "ok.png").write_bytes(_PNG)
    (tmp_path / "srvroot" / "nope.png")  # 故意不创建：根内不存在腿
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "secret.png").write_bytes(_PNG)
    (tmp_path / "srvroot_evil").mkdir()
    (tmp_path / "srvroot_evil" / "evil.png").write_bytes(_PNG)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("noisy", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "shot.png").write_bytes(_PNG)
    (tmp_path / "srvroot" / ".env.png").write_bytes(_PNG)
    (tmp_path / "srvroot" / "notes.txt").write_text("text", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _analyze(client: TestClient, payload: dict[str, Any]):
    return client.post("/api/v1/media/analyze", json=payload)


def _receipt(resp) -> tuple[int, dict[str, Any]]:
    return resp.status_code, resp.json()


def _short_abs(path: Path) -> str | None:
    """Windows 8.3 短名绝对形态；不可用或与长名同形返回 None。"""
    if os.name != "nt":
        return None
    buf = ctypes.create_unicode_buffer(260)
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 260)
    if not 0 < size < 260:
        return None
    short = "".join(ch for ch in buf if ch != "\0")
    return short if short.lower() != str(path).lower() else None


# ---------------------------------------------------------------------------
# 主锁：登记根外的本地形态一律拒，且**不触达 ingest 真身**（守卫排前）
# ---------------------------------------------------------------------------
def test_outside_root_absolute_refused_before_ingest(tree: Path, monkeypatch) -> None:
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(
        client, {"kind": "image", "image_urls": [str(tree / "out" / "secret.png")]}
    )
    assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}})
    assert recorder == {}, f"越界源竟然触达了 ingest 真身：{recorder}"


def test_case_variant_outside_root_refused(tree: Path, monkeypatch) -> None:
    """大小写变体（盘符翻转）与正写形态同拒——resolve 折叠不许放过变形。"""
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    raw = str(tree / "out" / "secret.png")
    variant = (raw[0].swapcase() + raw[1:]) if raw[1] == ":" else raw.upper()
    resp = _analyze(client, {"kind": "image", "image_urls": [variant]})
    assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}})
    assert recorder == {}


def test_83_short_name_outside_root_refused(tree: Path, monkeypatch) -> None:
    """在册教训反例：8.3 短名形态的根外路径必拒（startswith 尺在此静默穿透）。"""
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    out_file = tree / "out" / "secret.png"
    probe = _short_abs(out_file)
    if probe is None:
        # 本机短名不可用/同形 ⇒ 喂合成短名形态（仍是根外路径，照样必拒）。
        probe = str(out_file.parent / "SECRE~1.PNG")
    resp = _analyze(client, {"kind": "image", "image_urls": [probe]})
    assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}})
    assert recorder == {}


def test_file_uri_and_unknown_scheme_refused_outside_root(tree: Path, monkeypatch) -> None:
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    out_file = tree / "out" / "secret.png"
    for source in (out_file.as_uri(), "ftp://example.invalid/secret.png"):
        resp = _analyze(client, {"kind": "audio", "audio_source": source})
        assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}}), source
    assert recorder == {}


def test_traversal_out_of_root_refused(tree: Path, monkeypatch) -> None:
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(
        client, {"kind": "image", "image_urls": ["srvroot/../out/secret.png"]}
    )
    assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}})
    assert recorder == {}


def test_sibling_prefix_collision_refused(tree: Path, monkeypatch) -> None:
    """startswith 形态会把 ``srvroot_evil`` 当 ``srvroot`` 子路放行——必拒。"""
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(
        client, {"kind": "video", "video_source": "srvroot_evil/evil.png"}
    )
    assert _receipt(resp) == (422, {"error": {"code": REJECT[1], "message": REJECT[2]}})
    assert recorder == {}


def test_empty_roots_refuses_local_paths_keeps_remote(tree: Path, monkeypatch) -> None:
    """缺省无根 ⇒ 本地腿整支 fail-closed（绝不回落 cwd），远程腿照常。"""
    app, recorder = _harness("")
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(
        client, {"kind": "image", "image_urls": [str(tree / "srvroot" / "ok.png")]}
    )
    assert resp.status_code == 422, resp.text
    assert recorder == {}


# ---------------------------------------------------------------------------
# 反存在性探测：所有本地拒因逐字节同形
# ---------------------------------------------------------------------------
def test_receipt_uniform_no_existence_oracle(tree: Path, monkeypatch) -> None:
    """"存在但越界" / "不存在" / "命中禁区" / "根内缺失" 回执必须逐字节一致。"""
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    probes = [
        str(tree / "out" / "secret.png"),          # 存在・越界
        str(tree / "out" / "ghost.png"),           # 不存在・越界
        (tree / "out" / "secret.png").as_uri(),    # 存在・越界（file:// 形）
        "srvroot/nope.png",                        # 不存在・根内
        "srvroot/.env.png",                        # 存在・根内禁区名
        "srvroot/notes.txt",                       # 存在・根内非媒体后缀
        "C:\\Windows\\win.ini",                    # 异机形态
        "ftp://example.invalid/x.mp4",             # 未知 scheme
    ]
    receipts = {
        (
            resp.status_code,
            json.dumps(resp.json(), sort_keys=True, ensure_ascii=False),
        )
        for resp in (
            _analyze(client, {"kind": "image", "image_urls": [probe]})
            for probe in probes
        )
    }
    assert receipts == {
        (422, json.dumps({"error": {"code": REJECT[1], "message": REJECT[2]}},
                         sort_keys=True, ensure_ascii=False))
    }, receipts
    assert recorder == {}
    # 拒绝零写面：目录树不新增任何东西。
    names = {p.name for p in tree.iterdir()}
    assert names == {
        "srvroot", "out", "srvroot_evil", "logs", "data",
    }, names


# ---------------------------------------------------------------------------
# 活性正面：登记根内媒体可分析；远程/数据形态原样透传；短名折叠
# ---------------------------------------------------------------------------
def test_inside_root_media_flows_guarded(tree: Path, monkeypatch) -> None:
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(client, {"kind": "image", "image_urls": ["srvroot/ok.png"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["text"] == "vision-text"
    got = recorder["image_urls"][-1]
    assert got == [str((tree / "srvroot" / "ok.png").resolve())], got


def test_traversal_back_into_root_accepted(tree: Path, monkeypatch) -> None:
    """`..` 折回登记根内按实况放行——与 /files/read 同一把尺的两面。"""
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(client, {"kind": "image", "image_urls": ["out/../srvroot/ok.png"]})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("source", ["https://example.com/a.png", "http://example.com/b.mp3"])
def test_remote_sources_pass_through_untouched(
    tree: Path, monkeypatch, source: str
) -> None:
    app, recorder = _harness("")  # 无根也要放行远程（SSRF 咽喉在 ingest 下游）
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    assert _analyze(client, {"kind": "image", "image_urls": [source]}).status_code == 200
    assert recorder["image_urls"][-1] == [source]


def test_data_url_and_empty_source_keep_status_quo(tree: Path, monkeypatch) -> None:
    """data: 与空源＝既有契约位（v21-risk4 用 data: 断言 200），本修不许动形状。"""
    app, recorder = _harness("")
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(
        client, {"kind": "image", "image_urls": ["data:image/png;base64,AAAA"]}
    )
    assert resp.status_code == 200, resp.text
    assert recorder["image_urls"][-1] == ["data:image/png;base64,AAAA"]
    assert _analyze(client, {"kind": "audio", "audio_source": ""}).status_code == 200


def test_83_short_name_inside_root_resolves_to_long(tree: Path, monkeypatch) -> None:
    """正面折叠：根内文件的短名绝对形态必须仍能过守卫（resolve 折回长名）。"""
    long_path = (tree / "srvroot" / "ok.png").resolve()
    short = _short_abs(long_path)
    if short is None:
        pytest.skip("本机 8.3 短名不可用或与长名同形，注入不了这一族正例")
    app, recorder = _harness(str(tree / "srvroot"))
    _install_mocks(monkeypatch, recorder)
    client = TestClient(app)
    resp = _analyze(client, {"kind": "image", "image_urls": [short]})
    assert resp.status_code == 200, resp.text
    assert recorder["image_urls"][-1] == [str(long_path)]


# ---------------------------------------------------------------------------
# 网关单元锁：内部归因可查（HTTP 折叠前），判据与 authorize 同族
# ---------------------------------------------------------------------------
def test_gateway_admit_media_source_unit(tree: Path) -> None:
    gateway = FileReadGateway((tree / "srvroot",))
    assert gateway.admit_media_source("https://x/y.png") == "https://x/y.png"
    assert gateway.admit_media_source("data:image/png;base64,AA") == (
        "data:image/png;base64,AA"
    )
    assert gateway.admit_media_source("") == ""
    assert gateway.admit_media_source("srvroot/ok.png") == (
        (tree / "srvroot" / "ok.png").resolve()
    )
    with pytest.raises(FileGatewayError, match="path_not_allowed"):
        gateway.admit_media_source(str(tree / "out" / "secret.png"))
    with pytest.raises(FileGatewayError, match="path_not_allowed"):
        gateway.admit_media_source("srvroot_evil/evil.png")
    with pytest.raises(FileGatewayError, match="file_unavailable"):
        gateway.admit_media_source("srvroot/nope.png")
    with pytest.raises(FileGatewayError, match="format_not_supported"):
        gateway.admit_media_source("srvroot/notes.txt")
    with pytest.raises(FileGatewayError, match="source_denied"):
        gateway.admit_media_source("ftp://example.invalid/x.mp4")
    # 误配大盘根 ⇒ 禁区三族仍在守（与 /files/read 同一 denylist）
    wide = FileReadGateway((tree,))
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.admit_media_source("logs/a.log")
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.admit_media_source("data/shot.png")
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.admit_media_source("srvroot/.env.png")


def _install_mocks(monkeypatch: pytest.MonkeyPatch, recorder: dict[str, Any]) -> None:
    def _fake_builder(cfg: object, **_: object) -> object:
        return object()

    def _fake_describe(
        provider: object, *, image_urls: list[str], query_text: str = "", **_: object
    ) -> str:
        recorder.setdefault("image_urls", []).append(list(image_urls))
        return "vision-text"

    def _fake_video(
        provider: object, *, video_source: str, query_text: str = "", **_: object
    ) -> str:
        recorder.setdefault("video_source", []).append(video_source)
        return "video-text"

    def _fake_transcribe(provider: object, *, audio_source: str, **_: object) -> str:
        recorder.setdefault("audio_source", []).append(audio_source)
        return "audio-text"

    monkeypatch.setattr(f"{_VISION}.build_vision_provider", _fake_builder)
    monkeypatch.setattr(f"{_VISION}.describe_images", _fake_describe)
    monkeypatch.setattr(f"{_VISION}.describe_video", _fake_video)
    monkeypatch.setattr(f"{_TRANSCRIBE}.build_asr_provider", _fake_builder)
    monkeypatch.setattr(f"{_TRANSCRIBE}.transcribe_audio", _fake_transcribe)


# ---------------------------------------------------------------------------
# 结构锁（AST）：处理器路径内 ①无直接 open() ②三源必须先行过守卫
# ③payload 原始源不得直连 ingest 真身。纯谓词——注毒打同一靶。
# ---------------------------------------------------------------------------
_GUARD = "_admit"
_INGEST_ARGS = {
    "describe_images": "image_urls",
    "transcribe_audio": "audio_source",
    "describe_video": "video_source",
}


def _is_guard_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == _GUARD
    )


def _is_payload_get(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "payload"
    )


def analyze_media_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "analyze_media"
        ),
        None,
    )
    if fn is None:
        return ["找不到 analyze_media 处理器（尺失明）"]
    violations: list[str] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
        ):
            violations.append(f"L{node.lineno}: 处理器体内直接 open()（绕过守卫触文件）")
    guarded: dict[str, int] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
            _is_guard_call(child) for child in ast.walk(node.value)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    guarded[target.id] = node.lineno
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _INGEST_ARGS
        ):
            kwname = _INGEST_ARGS[node.func.id]
            kw = next((k for k in node.keywords if k.arg == kwname), None)
            if kw is None:
                violations.append(
                    f"L{node.lineno}: {node.func.id} 缺 {kwname} 关键词参数（锁需复核）"
                )
                continue
            ok = (
                isinstance(kw.value, ast.Name)
                and kw.value.id in guarded
                and guarded[kw.value.id] < node.lineno
            )
            if ok:
                continue
            if any(_is_payload_get(child) for child in ast.walk(kw.value)):
                violations.append(
                    f"L{node.lineno}: payload 原始源直连 ingest 真身（F-01 旁路形态）"
                )
            else:
                violations.append(
                    f"L{node.lineno}: {node.func.id} 的 {kwname} 未经 {_GUARD} 或守卫未排前"
                )
    return violations


def test_analyze_media_structure_clean_on_disk() -> None:
    assert analyze_media_violations(PLATFORM_PY.read_text(encoding="utf-8")) == []


def test_structure_lock_has_teeth() -> None:
    """注毒自证（AST 尺）：摘守卫/守卫排后/直连 open 三毒必须全咬，干净合成体必须放。"""
    clean = (
        "def build():\n"
        "    def analyze_media(payload):\n"
        '        guarded_images = [_admit(x) for x in payload.get("image_urls", [])]\n'
        "        guarded_audio = _admit(str(payload.get('audio_source') or ''))\n"
        "        return describe_images(p, image_urls=guarded_images)\n"
    )
    assert analyze_media_violations(clean) == []
    no_guard = (
        "def build():\n"
        "    def analyze_media(payload):\n"
        "        return describe_images(\n"
        "            p, image_urls=[str(x) for x in payload.get('image_urls', [])]\n"
        "        )\n"
    )
    assert any("直连" in v for v in analyze_media_violations(no_guard)), no_guard
    late_guard = (
        "def build():\n"
        "    def analyze_media(payload):\n"
        "        text = describe_images(p, image_urls=guarded_images)\n"
        '        guarded_images = [_admit(x) for x in payload.get("image_urls", [])]\n'
        "        return text\n"
    )
    assert any("未经" in v for v in analyze_media_violations(late_guard)), late_guard
    with_open = (
        "def build():\n"
        "    def analyze_media(payload):\n"
        "        guarded_audio = _admit('x')\n"
        "        data = open(guarded_audio, 'rb').read()\n"
        "        return transcribe_audio(p, audio_source=guarded_audio)\n"
    )
    assert any("open()" in v for v in analyze_media_violations(with_open)), with_open
