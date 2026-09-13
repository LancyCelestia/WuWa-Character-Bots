"""吃什么封面图质量校验回归：像素质检 + 候选按序遍历 + 来源记录落盘。

网络层（urllib.urlopen）整体替换为本地字节表，零真实请求；
图片字节用 PIL 现场生成（高熵噪声，保证过 1KB 字节下限）。
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from urllib.parse import quote_plus

import pytest

from plugins.bot_unified_runtime.capabilities.eat import _fetch_dish_image
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage

DISH = "宫保鸡丁"
# 公网字面量 IP：过 SSRF 护栏（http + 非保留网段），字面量不做 DNS → 零网络。
_HOST = "93.184.216.34"

TINY_SIZE = (80, 60)  # min 边 60 < 300 → 拒
NORMAL_SIZE = (640, 480)  # 正常菜品图 → 过
EXTREME_SIZE = (1200, 100)  # 宽高比 12 > 3 → 拒


def _png_bytes(size: tuple[int, int]) -> bytes:
    """现场生成高熵噪声 PNG（随机像素压不小，确保字节数 ≥ 1KB 下限）。"""
    from PIL import Image

    noise = Image.frombytes("L", size, os.urandom(size[0] * size[1]))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    return buffer.getvalue()


def _bing_page(urls: list[str]) -> bytes:
    """拼一个能被 eat._BING_RESULT_RE 命中的最小 Bing 结果页。"""
    return "".join(f'murl&quot;:&quot;{u}&quot;' for u in urls).encode("utf-8")


def _search_url() -> str:
    query = quote_plus(f"{DISH} 菜品 实拍")
    return f"https://cn.bing.com/images/search?q={query}&first=1&count=8"


class _FakeResp:
    """带上下文管理器的假响应（eat 用 with + read(n) 消费）。"""

    def __init__(self, payload: bytes, url: str = "") -> None:
        self._payload = payload
        self._url = url

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._payload
        return self._payload[:size]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _install_fake_net(
    monkeypatch: pytest.MonkeyPatch, images: dict[str, bytes | Exception]
) -> list[str]:
    """把 urllib.urlopen 换成本地字节表；按序记录被请求的 URL。"""
    requested: list[str] = []
    search = _search_url()

    def fake_urlopen(req: object, timeout: object = None) -> _FakeResp:
        url = str(getattr(req, "full_url", req))
        requested.append(url)
        if url == search:
            return _FakeResp(_bing_page(list(images)))
        payload = images[url]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResp(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return requested


def _message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="private:u1",
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def test_tiny_image_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"http://{_HOST}/tiny.png"
    _install_fake_net(monkeypatch, {url: _png_bytes(TINY_SIZE)})
    assert _fetch_dish_image(tmp_path, DISH) == ""
    assert list(tmp_path.iterdir()) == []  # 不合格候选不落盘


def test_extreme_aspect_image_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://{_HOST}/wide.png"
    _install_fake_net(monkeypatch, {url: _png_bytes(EXTREME_SIZE)})
    assert _fetch_dish_image(tmp_path, DISH) == ""
    assert list(tmp_path.iterdir()) == []


def test_normal_image_is_saved_and_source_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://{_HOST}/ok.png"
    payload = _png_bytes(NORMAL_SIZE)
    _install_fake_net(monkeypatch, {url: payload})
    saved = _fetch_dish_image(tmp_path, DISH)
    assert saved != ""
    image_file = Path(saved)
    assert image_file.parent == tmp_path
    assert image_file.read_bytes() == payload
    source = tmp_path / f"{DISH}.source.txt"
    assert source.is_file()
    lines = source.read_text(encoding="utf-8").splitlines()
    assert lines[0] == url  # 第一行：图片来源 URL
    datetime.fromisoformat(lines[1])  # 第二行：必须可解析的 ISO 时间戳


def test_candidates_walk_past_rejected_to_first_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiny_url = f"http://{_HOST}/a.png"
    ok_url = f"http://{_HOST}/b.png"
    tiny = _png_bytes(TINY_SIZE)
    good = _png_bytes(NORMAL_SIZE)
    _install_fake_net(monkeypatch, {tiny_url: tiny, ok_url: good})
    saved = _fetch_dish_image(tmp_path, DISH)
    assert saved != ""
    # 落盘的必须是第二个（合格）候选的字节，而不是第一个（过小）候选。
    assert Path(saved).read_bytes() == good
    assert Path(saved).suffix == ".png"


def test_all_candidates_failed_returns_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://{_HOST}/boom.png"
    _install_fake_net(monkeypatch, {url: OSError("网络失败")})
    assert _fetch_dish_image(tmp_path, DISH) == ""
    assert list(tmp_path.iterdir()) == []


def test_pixel_check_skipped_without_pil(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://{_HOST}/tiny.png"
    _install_fake_net(monkeypatch, {url: _png_bytes(TINY_SIZE)})
    monkeypatch.setitem(sys.modules, "PIL", None)  # 模拟 PIL 缺席
    # PIL 缺席时像素质检跳过、不阻断（退回字节级行为）。
    assert _fetch_dish_image(tmp_path, DISH) != ""


def test_blocked_domain_candidate_skipped_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """来源域命中防污染黑名单 → 不下载不落盘（2026-09-13 图库污染加固）。"""
    url = "http://www.boredpanda.com/x.png"
    # 候选本身完全合格（字节数/magic/像素质检全能过）：唯一拦截手段是黑名单。
    _install_fake_net(monkeypatch, {url: _png_bytes(NORMAL_SIZE)})
    assert _fetch_dish_image(tmp_path, DISH) == ""
    assert list(tmp_path.iterdir()) == []


def test_capability_text_fallback_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """封面候选全部失败 → 封面空串，菜谱文字照常输出（兜底链路零破坏）。"""
    from plugins.bot_unified_runtime.capabilities.eat import build_eat_capability

    url = f"http://{_HOST}/boom.png"
    _install_fake_net(monkeypatch, {url: OSError("网络失败")})
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.content_parser.render_card_png",
        lambda *_args, **_kwargs: {"file": ""},
    )
    config = SimpleNamespace(bot_food_image_dir=str(tmp_path))
    capability = build_eat_capability(config, render_backend=SimpleNamespace(available=True))
    result = capability(_message("菜谱 番茄炒蛋"), None)
    assert result.kind == "text"
    assert "番茄炒蛋" in result.body
    assert list(tmp_path.iterdir()) == []  # 失败候选不落盘


# ==================== Tavily 图搜兜底通道（用户裁定 2026-09-14） ====================


def _patch_tavily_candidates(
    monkeypatch: pytest.MonkeyPatch, urls: list[str]
) -> None:
    monkeypatch.setattr(
        "plugins.bot_unified_runtime.capabilities.eat._tavily_image_candidates",
        lambda name, config=None: list(urls),
    )


def test_bing_empty_page_falls_back_to_tavily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bing 页零候选（或搜索失败）→ Tavily 兜底，同一质检闸放行落盘。"""
    url = f"http://{_HOST}/tavily.png"
    payload = _png_bytes(NORMAL_SIZE)

    _patch_tavily_candidates(monkeypatch, [url])
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (
            _FakeResp(b"<html>no result</html>")
            if str(getattr(req, "full_url", req)).startswith("https://cn.bing.com")
            else _FakeResp(payload)
        ),
    )
    saved = _fetch_dish_image(tmp_path, DISH)
    assert saved != ""
    assert Path(saved).read_bytes() == payload
    lines = (tmp_path / f"{DISH}.source.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert lines[0] == url  # 来源记录首行 = Tavily 候选 URL


def test_bing_all_rejected_still_reaches_tavily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bing 候选全被质检拒绝（过小）→ 同样落到 Tavily 兜底候选。"""
    tiny_url = f"http://{_HOST}/tiny.png"
    ok_url = f"http://{_HOST}/tavily-ok.png"
    good = _png_bytes(NORMAL_SIZE)

    def fake_urlopen(req: object, timeout: object = None) -> _FakeResp:
        url_req = str(getattr(req, "full_url", req))
        if url_req == tiny_url:
            return _FakeResp(_png_bytes(TINY_SIZE))
        if url_req == ok_url:
            return _FakeResp(good)
        return _FakeResp(_bing_page([tiny_url]))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _patch_tavily_candidates(monkeypatch, [ok_url])
    saved = _fetch_dish_image(tmp_path, DISH)
    assert saved != ""
    assert Path(saved).read_bytes() == good


def test_tavily_candidates_respect_domain_blocklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tavily 兜底候选同样过来源域黑名单，防兜底通道引入污染源。"""
    blocked_url = "https://img.sinaimg.cn/pollution.jpg"
    ok_url = f"http://{_HOST}/clean.png"
    good = _png_bytes(NORMAL_SIZE)

    def fake_urlopen(req: object, timeout: object = None) -> _FakeResp:
        url_req = str(getattr(req, "full_url", req))
        if url_req == ok_url:
            return _FakeResp(good)
        return _FakeResp(b"<html>no result</html>")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _patch_tavily_candidates(monkeypatch, [blocked_url, ok_url])
    saved = _fetch_dish_image(tmp_path, DISH)
    assert saved != ""
    assert Path(saved).read_bytes() == good
    requested_lines = (tmp_path / f"{DISH}.source.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    assert requested_lines[0] == ok_url  # 黑名单域没被下载


def test_tavily_candidates_without_key_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配 key（且 CLI 态取不到 env）→ 兜底通道静默返回空表，零网络。"""
    from plugins.bot_unified_runtime.capabilities.eat import (
        _tavily_image_candidates,
    )

    monkeypatch.delenv("BOT_SEARCH_TAVILY_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    assert _tavily_image_candidates(DISH, None) == []


def test_redirect_to_internal_host_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """安全审计 I-1：公网候选 302 跳内网 = 拒绝，不落盘零数据残留。"""
    url = f"http://{_HOST}/redirect.png"
    internal_url = "http://169.254.169.254/latest/meta.png"
    payload = _png_bytes(NORMAL_SIZE)

    def fake_urlopen(req: object, timeout: object = None) -> _FakeResp:
        url_req = str(getattr(req, "full_url", req))
        if url_req == url:
            return _FakeResp(payload, url=internal_url)  # 302 已跟到内网
        return _FakeResp(_bing_page([url]))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert _fetch_dish_image(tmp_path, DISH) == ""
    assert list(tmp_path.iterdir()) == []
