"""卡面样张脚本回归（scripts/render_card_samples.py，全离线不真开浏览器）。

覆盖：
- 18 张样张 payload 构造函数逐卡非空断言（HTML 体量/守岸人署名/视口键）；
- 关键卡面内容抽查（平台主题色、渠道子行、脏数据归一、非上市红线等）；
- --list 输出包含全部登记卡型（main(["--list"]) 返回 0，纯离线）；
- 渲染函数在假后端下的调用路径：payload 透传 / 文件名含卡型 / 单卡失败
  不中断其余卡 / 汇总表标注 FAIL 与原因 / 未知卡型退出码。
- --serve 只读预览面（工单 W-5）：零写自证（目录字节与文件集一字未动、绝不 mkdir）、
  返回值与对外文本零绝对路径（只给 RUNTIME_ROOT/TMP_ROOT/SAMPLES_ROOT 脱敏标记）、
  无产物时明说「还没有产物」且绝不产出「可用」这类词、判据分母与 --list 同源现算
  （非 HTTP 200）、逐图带文件名与所属卡型、目录穿越条目被拒收，
  以及「预览看过 ≠ 契约过」的三把视觉锁点名。

PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_render_card_samples.py \
    --basetemp="$TEMP/sample" -p no:cacheprovider
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.render.card_render import bridge
from scripts import render_card_samples as rcs

# ==================== 假后端 ====================


def _tiny_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (49, 140, 231)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeBackend:
    """记录 render_card 入参并返回固定 PNG 的假后端（契约同 Protocol）。"""

    name = "fake"
    available = True

    def __init__(self, *, png: bytes | None = None, fail_keys: set[str] | None = None):
        self.png = png if png is not None else _tiny_png()
        self.fail_keys = fail_keys or set()
        self.calls: list[dict[str, Any]] = []

    def render_card(self, payload: dict[str, Any]) -> bytes | None:
        self.calls.append(payload)
        html = str(payload.get("html", ""))
        for key in self.fail_keys:
            if key in html:
                return None
        return self.png


# ==================== 1. payload 构造逐卡非空 ====================


@pytest.mark.parametrize("card", rcs.CARDS, ids=[card.key for card in rcs.CARDS])
def test_payload_builder_renders_nonempty_html(card: rcs.SampleCard) -> None:
    payload = card.build()
    assert isinstance(payload, dict)
    html = payload.get("html")
    assert isinstance(html, str) and len(html) > 500, f"{card.key} HTML 过短"
    assert re.search(r'class="[^"]*\bcard\b[^"]*"', html), f"{card.key} 缺 .card 根"
    assert payload.get("device_scale_factor") == 2
    viewport = payload.get("viewport")
    if card.key != "media_archive":  # 媒体卡沿用后端缺省视口（同生产）。
        assert isinstance(viewport, dict) and viewport.get("width", 0) > 0


@pytest.mark.parametrize("card", rcs.CARDS, ids=[card.key for card in rcs.CARDS])
def test_payload_builder_has_shorekeeper_signature(card: rcs.SampleCard) -> None:
    html = str(card.build().get("html", ""))
    if card.key == "mermaid_flow":
        assert "守岸人" in html  # mermaid 卡 bot_name 直出。
    else:
        assert "守岸人" in html, f"{card.key} 缺守岸人署名"


# ==================== 2. 关键卡面内容抽查 ====================


def test_universal_bilibili_video_content() -> None:
    html = rcs.build_universal_bilibili_video()["html"]
    assert "#fb7299" in html  # bilibili accent。
    assert "AV 112874701" in html  # 页脚媒体 ID（av 优先）。
    assert "152\u2009万" in html  # fmt_count 数量级格式化（1520000 → 152 万）。
    assert "data:image/png;base64," in html  # 封面/头像离线 data URI。


def test_universal_bgv_has_music_credit() -> None:
    html = rcs.build_universal_bilibili_bgv()["html"]
    assert "Iris" in html
    assert "music-credit" in html


def test_universal_search_gallery_images_offline() -> None:
    html = rcs.build_universal_default_search()["html"]
    assert "image-gallery" in html
    assert html.count("data:image/png;base64,") >= 3


def test_universal_netease_music_uses_netease_accent() -> None:
    html = rcs.build_universal_netease_music()["html"]
    assert "#c20c0c" in html  # netease accent。
    assert "music-credit" in html


def test_market_index_has_groups_and_sparkline() -> None:
    html = rcs.build_market_index()["html"]
    assert "上证指数" in html and "莫斯科指数" in html
    assert "<polyline" in html  # trend 序列真折线。
    assert "暂无历史走势数据" in html  # 无走势行的 trend_note 分支。


def test_market_commodities_bond_northbound_titles() -> None:
    assert "大宗商品速览" in rcs.build_market_commodities()["html"]
    bond = rcs.build_market_bond()["html"]
    assert "中美国债收益率速览" in bond
    assert "10Y−2Y 期限利差" in bond
    assert "北向资金速览" in rcs.build_market_northbound()["html"]


def test_finance_stocks_unlisted_redline_and_trend_svg() -> None:
    html = rcs.build_finance_stocks()["html"]
    assert "非上市" in html  # OpenAI/字节非上市红线口径上卡。
    assert "<svg" in html  # line_chart_svg 折线（内部生成整段 svg 放行）。


def test_affinity_private_and_group_contents() -> None:
    private = rcs.build_affinity_private()["html"]
    assert "澜汐" in private and "亲近" in private
    group = rcs.build_affinity_group()["html"]
    assert "澜汐" in group and "霞月" in group


def test_affinity_dirty_normalized_no_none_leak() -> None:
    html = rcs.build_affinity_dirty()["html"]
    body = html.split("<body>", 1)[-1]
    assert "None" not in body  # vis5 归一：缺省分数按 0.0 渲染。
    assert "守岸人" in html


def test_song_candidates_content() -> None:
    html = rcs.build_song_candidates()["html"]
    assert "晴天" in html and "#c20c0c" in html


def test_mermaid_payload_matches_production_ready_gate() -> None:
    payload = rcs.build_mermaid()
    assert payload["wait_js"] == bridge_ready_js()
    assert "graph TD" in payload["html"]
    assert "cdn.jsdelivr.net/npm/mermaid@11" in payload["html"]  # 模板 URL（传输层拦截换血）。


def bridge_ready_js() -> str:
    from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
        _MERMAID_READY_JS,
    )

    return _MERMAID_READY_JS


def test_usage_report_has_channel_subrows() -> None:
    html = rcs.build_usage_report()["html"]
    assert '<div class="crow glass">' in html  # 渠道子行。
    assert "axonhub-main" in html and "axonhub-backup" in html
    assert "未计价" in html


def test_media_archive_card_content() -> None:
    html = rcs.build_media_archive()["html"]
    assert "媒体归档" in html and "cosplay" in html
    assert "原神" in html


def test_error_card_red_accent_and_full_sections() -> None:
    from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
        ERROR_ACCENT,
    )

    html = rcs.build_error_card()["html"]
    assert f"--accent:{ERROR_ACCENT}" in html  # 红强调（ERROR_THEME 注入，非平台色）。
    for marker in (
        "运行异常",
        bridge._CARD_TEXT["static_err_31"],  # goal-7 说人话波：旧手抄 "RUNTIME DIAGNOSTIC"（本文件自带教训：节题单一事实源=_CARD_TEXT）
        "触发回显",
        "栈摘录",
        # 分区标题的单一事实来源是 `_CARD_TEXT`（2026-09-25「触发方法」改名
        # 「定位与原因」时，手抄这张表的用例当场假红过一次）。
        bridge._CARD_TEXT["static_err_22"],
        "配置快照",
        "版本与构建",
        "平台与协议",
        bridge._CARD_TEXT["static_err_32"],  # 旧手抄 "IDs 与时间"，同指 _CARD_TEXT 单一源
        "TimeoutError",
        "weather.py:120",
        "bot_weather_api_key",
    ):
        assert marker in html, f"缺分区/内容: {marker}"
    assert re.search(r'class="shell card"', html)  # 元素截图契约根。
    payload = rcs.build_error_card()
    assert payload["viewport"] == {"width": 1160, "height": 1800}  # 同生产 render_error_card_png。


# ==================== 3. --list 模式 ====================


def test_list_mode_prints_all_registered_keys(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = rcs.main(["--list"])
    assert exit_code == 0
    out = capsys.readouterr().out
    for card in rcs.CARDS:
        assert card.key in out, f"--list 缺卡型 {card.key}"


def test_registry_has_no_duplicate_keys() -> None:
    keys = [card.key for card in rcs.CARDS]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 17


# ==================== 4. 假后端渲染路径（≥6 例） ====================


def _run(out_dir: Path, keys: list[str] | None = None, **fake_kwargs: Any):
    backend = FakeBackend(**fake_kwargs)
    results = rcs.render_samples(out_dir, keys=keys, backend=backend)
    return backend, results


def test_render_samples_all_cards_through_fake_backend(tmp_path: Path) -> None:
    backend, results = _run(tmp_path)
    assert len(results) == len(rcs.CARDS)
    assert len(backend.calls) == len(rcs.CARDS)
    assert all(result.ok for result in results)


def test_render_samples_writes_png_named_by_card_key(tmp_path: Path) -> None:
    keys = ["market_index", "affinity_group", "usage_report"]
    _backend, results = _run(tmp_path, keys=keys)
    assert [result.key for result in results] == keys
    for index, result in enumerate(results, start=1):
        assert result.path is not None
        assert result.path.parent == tmp_path
        assert result.key in result.path.name  # 文件名含卡型。
        assert result.path.name.startswith(f"{index:02d}_")
        assert result.path.read_bytes()  # PNG 落盘非空。
        assert result.dimensions == "4x4"
        assert result.elapsed_ms >= 0


def test_render_samples_single_failure_does_not_stop_others(tmp_path: Path) -> None:
    keys = ["market_index", "affinity_dirty", "song_candidates"]
    # affinity_dirty 的 HTML 落「脏」样张文本 → 该卡后端返回 None。
    backend, results = _run(tmp_path, keys=keys, fail_keys={"乙"})
    assert [result.ok for result in results] == [True, False, True]
    assert "RuntimeError" in results[1].error
    assert results[0].path is not None and results[2].path is not None
    assert len(backend.calls) == 3  # 失败卡也走过后端（不中断）。


def test_render_samples_empty_backend_result_recorded_as_failure(tmp_path: Path) -> None:
    class EmptyBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            super().render_card(payload)
            return None

    backend = EmptyBackend()
    results = rcs.render_samples(tmp_path, keys=["finance_stocks"], backend=backend)
    assert not results[0].ok
    assert "None" in results[0].error or "空" in results[0].error
    assert results[0].path is None


def test_render_samples_builder_exception_isolated(tmp_path: Path) -> None:
    class BoomBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            raise RuntimeError("boom")

    results = rcs.render_samples(tmp_path, keys=["usage_report"], backend=BoomBackend())
    assert not results[0].ok
    assert "boom" in results[0].error


def test_main_only_filter_and_unknown_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 全离线口径：注入假后端，防真开 Playwright 把 running loop 留在主线程
    # 毒化后续套件的 asyncio.run() 用例（A43 76 红根因）。
    monkeypatch.setattr(rcs, "build_render_backend", lambda name="": FakeBackend())
    exit_code = rcs.main(["--out", str(tmp_path), "--only", "market_bond,media_archive"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "market_bond" in out and "media_archive" in out
    assert "2/2 张成功" in out

    exit_code = rcs.main(["--out", str(tmp_path), "--only", "no_such_key"])
    assert exit_code == 2


def test_main_reports_failure_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailBackend(FakeBackend):
        def render_card(self, payload: dict[str, Any]) -> bytes | None:
            super().render_card(payload)
            return None

    monkeypatch.setattr(rcs, "build_render_backend", lambda name="": FailBackend())
    exit_code = rcs.main(["--out", str(tmp_path), "--only", "market_index"])
    assert exit_code == 1  # 有卡失败 → 退出码 1，但流程完整打印汇总。


# ==================== 5. --serve 只读预览（工单 W-5）====================
#
# 边界（D-2/Q-2 裁定）：--serve 只列**已经渲好**的产物、只绑 127.0.0.1、不落任何新
# 文件、不是可视化编辑器。本组用例逐条自证：零写、无产物不谎报、目录穿越拒收、
# 判据不靠「HTTP 200」、以及「预览看过 ≠ 契约过」的提醒真的在文案里。


def _make_samples(dir_path: Path, keys: list[str]) -> None:
    """在盘上造「已渲好」的样张（命名＝render_baseline 的 NN_<key>.png）。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    for index, key in enumerate(keys, start=1):
        (dir_path / f"{index:02d}_{key}.png").write_bytes(_tiny_png())


def _full_samples(dir_path: Path) -> list[str]:
    keys = [card.key for card in rcs.CARDS]
    _make_samples(dir_path, keys)
    return keys


def _snapshot(dir_path: Path) -> dict[str, tuple[int, int, int]]:
    """目录指纹：文件名 → (字节数, mtime_ns, 内容 sha 前 16)。只读，不改任何东西。"""
    import hashlib

    return {
        path.name: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            int.from_bytes(hashlib.sha256(path.read_bytes()).digest()[:8], "big"),
        )
        for path in sorted(dir_path.iterdir())
    }


def _forbid_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    """把渲染与后端装配三腿全换成炸弹：--serve 敢碰任何一条就当场红。"""

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("--serve 不得渲染/不得起后端（只读预览入口）")

    monkeypatch.setattr(rcs, "render_samples", _boom)
    monkeypatch.setattr(rcs, "render_baseline", _boom)
    monkeypatch.setattr(rcs, "build_render_backend", _boom)


def test_serve_shape_is_loopback_only_and_port_is_free() -> None:
    # 只绑回环是代码事实（无 --host 开关），端口避开既有服务占用的那几枚。
    assert rcs._SERVE_HOST == "127.0.0.1"
    assert rcs._SERVE_DEFAULT_PORT not in {5174, 8080, 8090, 3001, 8742, 8743, 8744}


def test_collect_samples_writes_nothing_and_returns_no_absolute_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _full_samples(tmp_path)
    _forbid_rendering(monkeypatch)
    before = _snapshot(tmp_path)

    listing = rcs.collect_samples(tmp_path)
    stdout_text = rcs.format_listing(listing)
    page_text = rcs.preview_page_html(listing)

    # 零写自证：文件集与逐文件字节/时间戳一字未动，也没多出文件。
    assert _snapshot(tmp_path) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(before)
    # 不存在产物根 ⇒ 只报空，绝不 mkdir。
    ghost = tmp_path / "ghost-root"
    ghost_listing = rcs.collect_samples(ghost)
    assert not ghost.exists() and not ghost_listing.artifacts and not ghost_listing.dir_exists

    # 返回值与对外文本里都不该出现绝对路径（Windows 盘符 / POSIX 绝对都扫）。
    for value in [item.rel_name for item in listing.artifacts] + [listing.root_mark]:
        assert value and not Path(value).is_absolute(), value
        assert ":" not in value and "\\" not in value and not value.startswith("/"), value
    assert listing.root_mark.split("/")[0] in {"RUNTIME_ROOT", "TMP_ROOT", "SAMPLES_ROOT"}
    for text in (stdout_text, page_text):
        assert str(tmp_path) not in text and str(ghost) not in text


def test_serve_without_artifacts_says_so_and_never_renders(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_rendering(monkeypatch)
    empty = tmp_path / "empty"
    empty.mkdir()

    exit_code = rcs.main(["--serve", "--out", str(empty)])
    captured = capsys.readouterr()
    report = captured.out + captured.err

    assert exit_code == 2
    assert "没有产物" in report  # 明说没有产物 + 该跑什么命令
    assert "--only" in report and "--out" in report
    assert "可用" not in report  # 空目录绝不产「可用」这个词
    assert list(empty.iterdir()) == []  # 没有「顺手渲一份」
    assert not (tmp_path / "ghost").exists()
    assert rcs.main(["--serve", "--out", str(tmp_path / "ghost")]) == 2
    assert not (tmp_path / "ghost").exists()


def test_serve_cli_routes_to_preview_and_binds_nothing_on_bad_port(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 端口非法 ⇒ 在绑 socket 之前就退出；全套渲染腿是炸弹（_forbid_rendering）也没炸。
    _full_samples(tmp_path)
    _forbid_rendering(monkeypatch)
    assert rcs.main(["--serve", "--out", str(tmp_path), "--serve-port", "0"]) == 2
    assert "端口" in capsys.readouterr().err


def test_listing_verdict_is_the_full_set_ruler_not_http_status(tmp_path: Path) -> None:
    total = len(rcs.CARDS)  # 同一把尺：与 --list 现算值同源，禁写死枚数
    _make_samples(tmp_path, ["market_index", "affinity_group"])
    subset = rcs.collect_samples(tmp_path)
    assert len(subset.present_keys) == 2 and not subset.complete
    assert len(subset.missing_keys) == total - 2
    verdict = rcs.listing_summary(subset)
    assert "预览不成立" in verdict and "缺卡型" in verdict
    assert f"/{total}" in verdict

    # 形态在册但卡型不存在 ⇒ 归属报不出 ⇒ 同样不成立（缺图/缺归属都按不成立报）。
    partial = tmp_path / "unattributed"
    keys = _full_samples(partial)
    (partial / f"01_{keys[0]}.png").unlink()
    (partial / "01_no_such_key.png").write_bytes(_tiny_png())
    stray = rcs.collect_samples(partial)
    assert not stray.complete and not any(item.card_key for item in stray.artifacts[:1])
    assert "报不出" in rcs.listing_summary(stray)

    # 形态不在命名册内（目录穿越产物）⇒ 拒收并计数，绝不进列表。
    illegal = tmp_path / "illegal"
    _full_samples(illegal)
    (illegal / "poster.png").write_bytes(_tiny_png())
    listing = rcs.collect_samples(illegal)
    assert listing.illegal_count == 1 and not listing.complete
    assert all("poster" not in item.rel_name for item in listing.artifacts)
    assert "条条目形态不在产物命名册内" in rcs.listing_summary(listing)


def test_preview_page_pairs_every_shot_with_name_and_card_key(tmp_path: Path) -> None:
    keys = _full_samples(tmp_path)
    listing = rcs.collect_samples(tmp_path)
    assert listing.complete
    page = rcs.preview_page_html(listing)
    assert page.count("<img src=") == len(rcs.CARDS)
    for index, key in enumerate(keys, start=1):
        rel = f"{index:02d}_{key}.png"
        blocks = [block for block in page.split("</figure>") if f"<b>{rel}</b>" in block]
        assert len(blocks) == 1, f"文件名没出现在唯一图格: {rel}"
        assert f"卡型 {key}" in blocks[0], f"{rel} 缺所属卡型标注"
    assert str(tmp_path) not in page
    # 视觉门没被绕过去：三把锁 + 哈希册判据点名在页里。
    for lock in (
        "tests/test_rendering_contract.py",
        "tests/test_mica_builders_contract.py",
        "tests/test_template_visual_audit.py",
        "tests/verify_hashes.py --check",
    ):
        assert lock in page, f"预览页未点名判据: {lock}"
    assert "预览看过 ≠ 渲染契约通过" in page
    assert "也不把任何一张卡说成「改好了」" in page
    assert "也不把任何一张卡说成「改好了」" in rcs._CONTRACT_NOTE
    assert "也不把任何一张卡说成「改好了」" in rcs.format_listing(listing)


def test_directory_traversal_entries_are_rejected(tmp_path: Path) -> None:
    _full_samples(tmp_path)
    legit = rcs.resolve_sample_file(tmp_path, "01_universal_bilibili_video.png")
    assert legit is not None and legit.parent == tmp_path.resolve() and legit.is_file()

    outside = tmp_path.parent / "01_market_index.png"
    outside.write_bytes(_tiny_png())  # 目录外真存在一张同名形态的 PNG
    poisons = [
        "../01_market_index.png",
        "../../01_market_index.png",
        "..\\01_market_index.png",
        str(outside),  # 绝对路径（Windows 带盘符冒号）
        "/" + outside.name,
        "01_market_index.png\x00.png",
        "./01_market_index.png",
        "sub/01_market_index.png",
        "01_market_index/../01_market_index.png",
        "",
        "..",
        ".",
        "01_MARKET_INDEX.png",
        "%2e%2e%2f01_market_index.png",
    ]
    for poison in poisons:
        assert rcs.resolve_sample_file(tmp_path, poison) is None, f"越界条目未拒收: {poison!r}"
    assert rcs.resolve_sample_file(tmp_path, "C:/Windows/win.ini") is None

    # 有人绕过 collect_samples 直接把越界条目塞进列表 ⇒ 页面与 URL 双双换不出图。
    listing = rcs.collect_samples(tmp_path)
    poisoned = rcs.SampleListing(
        root_mark=listing.root_mark,
        dir_exists=True,
        artifacts=(rcs.SampleArtifact(rel_name="../../../../Windows/win.ini", card_key="error_card", size_bytes=1),),
        present_keys=("error_card",),
        missing_keys=(),
        expected_keys=listing.expected_keys,
        illegal_count=0,
    )
    page = rcs.preview_page_html(poisoned)
    assert "<img src=" not in page and "win.ini" not in page
    assert not poisoned.complete  # 形态不合法 ⇒ 判据不成立（列表非空也不给过）

