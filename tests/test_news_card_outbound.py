"""快报卡（news_digest_card.html）接进 `/快报` 应答路径的活性锁（S-T-NEWS-2，2026-09-26）。

为什么单开一件：这张卡此前是**合规的死件**——契约面（test_news_digest_card_contract /
test_token_supply_chain / test_v21r3_visual_gates）全在直接调 `bridge.render_news_digest_card_html`，
生产链路里零调用点，她问「快报」仍然只拿纯文本。契约合规 ≠ 上线，所以本件的判据
**一律从能力入口进**（`build_news_capability`），不再只测渲染函数：

  ① 端到端：假 items + 假渲染后端 ⇒ `kind="mixed"`、卡 PNG 真落盘、`body` 仍是**完整**
     纯文本（卡+文同发，她要求「一次性讲清楚」）；
  ② fail-open 命门：渲染后端抛异常 ⇒ `kind="text"`、`body` 非空、审计带 `news_card_failed`；
  ③ 负样本：调度器推送路径永不出卡（AST 锁 + 缺省不注入后端的形态锁 + 唯一消费者锁）；
  ④ 注毒自证：把 `_render_card` 的兜底摘掉 ⇒ 失败态用例当场炸（证明②绿的是兜底，不是运气）。

另附载荷契约对照：卡上每个字段都按 `bridge.py:1879` 现读的键名构造，条目标题/摘要
逐条要求**真的出现在渲染产物里**（模板整块隐藏=静默丢信息，是本件要拦的东西）。

全部离线：假渲染后端返回常量字节、卡片落 `tmp_path`、`fetch_headlines` 打桩——
不触网、不起 Playwright、源码树零 `data/` 零缓存。
"""

from __future__ import annotations

import ast
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# monkeypatch 打真身模块（垫片壳 setattr 进不去真身全局——v21r2 W5 口径）。
import plugins.bot_unified_runtime.domains.subscribe.capabilities.news as news_module
import plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds as feeds_module
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.subscribe.capabilities.news import (
    _CARD_FOOT,
    build_news_capability,
    build_news_card_content,
    news_card_digest,
)
from plugins.bot_unified_runtime.domains.subscribe.feeds.news_feeds import (
    NewsFoldAccount,
    NewsItem,
    fold_account_for,
    fold_reading_sequence,
    fold_same_topic,
    format_news_brief,
    reset_fold_accounts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_UTC = timezone.utc


# ---------------------------------------------------------------------------
# 打桩件
# ---------------------------------------------------------------------------


class _FakeBackend:
    """假渲染后端：可配「返回字节 / 抛异常 / 不可用」三态。"""

    name = "fake"

    def __init__(
        self,
        *,
        png: bytes | None = b"fake-png-bytes",
        raises: BaseException | None = None,
        available: bool = True,
    ) -> None:
        self._png = png
        self._raises = raises
        self.available = available
        self.seen: list[dict[str, Any]] = []

    def render_card(self, spec: dict[str, Any]) -> bytes | None:
        self.seen.append(spec)
        if self._raises is not None:
            raise self._raises
        html = spec.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        return self._png


def _sample_items(count: int = 3) -> list[NewsItem]:
    """aware 时间的条目（真实 RSS 的 pubDate 都带时区，见 news_feeds._parse_datetime）。"""
    base = datetime(2026, 9, 26, 8, 30, tzinfo=_UTC)
    return [
        NewsItem(
            title=f"条目{index}：某公司发布新一代模型",
            url=f"https://example.com/news/{index}",
            source="IT之家" if index % 2 else "少数派",
            published_at=base + timedelta(minutes=index),
            category="tech",
            summary=f"这是第{index}条的真实内容摘要行。",
        )
        for index in range(1, count + 1)
    ]


def _message(text: str = "科技快报") -> IncomingMessage:
    return IncomingMessage(
        request_id="req-news-card",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _decision() -> BotDecision:
    return BotDecision(
        request_id="req-news-card",
        should_respond=True,
        mode="command",
        trigger="科技快报",
        capability_id="bot.news",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


def _patch_items(monkeypatch: pytest.MonkeyPatch, items: list[NewsItem]) -> None:
    monkeypatch.setattr(news_module, "fetch_headlines", lambda category, **kw: list(items))


# ---------------------------------------------------------------------------
# ① 端到端：卡 + 完整文本同发
# ---------------------------------------------------------------------------


def test_capability_emits_card_and_keeps_full_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """拿到假 items + 假后端 ⇒ mixed、卡真落盘、正文一条不少（卡是加法不是替换）。"""
    items = _sample_items(3)
    _patch_items(monkeypatch, items)
    backend = _FakeBackend()
    capability = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )

    result = capability(_message(), _decision())
    expected_body = format_news_brief(items, "科技")

    assert result.kind == "mixed"
    assert result.capability_id == "bot.news"
    assert result.body == expected_body, "卡不能替代文本：正文必须逐字是那份完整快报"
    for item in items:
        assert item.title in result.body
        assert item.summary in result.body
    assert len(result.images) == 1
    card_file = Path(str(result.images[0]["file"]))
    assert card_file.is_file(), "images 里的路径必须是真落盘的 PNG"
    assert card_file.parent == tmp_path
    assert card_file.name.startswith("news_")
    assert card_file.read_bytes() == b"fake-png-bytes"
    assert "news_card_rendered" in result.audit_tags
    assert "capability:news" in result.audit_tags
    assert result.audit_tags.count("news_card_failed") == 0
    assert backend.seen, "后端一次都没被调用＝卡没走渲染管线"


def test_rendered_html_carries_every_card_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """送进后端的那页 HTML 必须真的带着条目标题/来源/摘要/时间。

    只断言「payload 里有键」是不够的：键名与模板引用不一致时 bridge 会静默隐藏
    区块、卡照样出、内容却是空的——这正是「合规的死件」的下一形态。
    """
    items = _sample_items(4)
    _patch_items(monkeypatch, items)
    backend = _FakeBackend()
    build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )(_message(), _decision())

    html = str(backend.seen[0]["html"])
    body = html.split("<body>", 1)[1]
    for item in items:
        assert item.title in html
        assert item.summary in html
        assert item.source in html
    assert _CARD_FOOT in html
    assert "今日快报 · 科技" in html
    assert re.search(r"\d{2}-\d{2} \d{2}:\d{2}", html), "发布时间没上卡"
    assert "Undefined" not in body and "{{" not in body, "卡面漏出未渲染占位"


def test_repeat_request_rewrites_same_file_without_growth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同批条目重复请求 ⇒ 覆盖同一文件（内容摘要做文件名，卡片目录不喂爆）。"""
    items = _sample_items(2)
    _patch_items(monkeypatch, items)
    backend = _FakeBackend()
    capability = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )
    first = str(capability(_message(), _decision()).images[0]["file"])
    second = str(capability(_message(), _decision()).images[0]["file"])
    assert first == second
    assert len(list(tmp_path.glob("news_*.png"))) == 1


def test_news_card_quota_prunes_only_its_own_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """配额与 today_history/market 同口径（keep=120），且只裁 `news_` 前缀。"""
    # 桩必打：本件是全文件唯一走能力入口却不打桩的用例（2026-10-08 定案）——真实
    # `fetch_headlines` 取空时能力降级纯文本、`images` 为空，取 `images[0]` 那一行
    # 以 IndexError 崩相收场（配额三把断言一把都没跑到，红得没有信息量）。桩一钉死，
    # 本件回到文件头声明的「全部离线」口径，断言只判配额这一件事。
    _patch_items(monkeypatch, _sample_items(3))
    for index in range(125):
        stale = tmp_path / f"news_{index:03d}.png"
        stale.write_bytes(b"x")
        stamp = 1_700_000_000 + index
        os.utime(stale, (stamp, stamp))
    for index in range(3):
        other = tmp_path / f"host_{index:03d}.png"
        other.write_bytes(b"x")
        stamp = 1_700_000_000 + index
        os.utime(other, (stamp, stamp))

    backend = _FakeBackend()
    capability = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )
    result = capability(_message(), _decision())
    assert result.images, f"卡没出（audit={result.audit_tags}），配额这一把尺量不到东西"
    card = str(result.images[0]["file"])

    survivors = sorted(path.name for path in tmp_path.glob("news_*.png"))
    assert len(survivors) == 120, f"配额失效或裁过头：现存 {len(survivors)} 张"
    assert Path(card).name in survivors, "最新一张被自己裁掉了"
    assert len(list(tmp_path.glob("host_*.png"))) == 3, "越界裁了别的能力的卡"


# ---------------------------------------------------------------------------
# ② fail-open：渲染失败绝不整条不回
# ---------------------------------------------------------------------------


def test_backend_exception_degrades_to_full_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """命门：后端抛异常（Playwright 崩溃/超时都长这样）⇒ 纯文本照发 + 点名失败。"""
    items = _sample_items(3)
    _patch_items(monkeypatch, items)
    backend = _FakeBackend(raises=RuntimeError("browser has been closed"))
    capability = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )

    result = capability(_message(), _decision())
    assert result.kind == "text"
    assert result.body == format_news_brief(items, "科技")
    assert result.images == []
    assert "news_card_failed" in result.audit_tags
    assert list(tmp_path.glob("news_*.png")) == []


def test_unavailable_backend_degrades_to_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_items(monkeypatch, _sample_items(2))
    capability = build_news_capability(
        config=None,
        render_backend=_FakeBackend(available=False),
        card_dir=str(tmp_path),
    )
    result = capability(_message(), _decision())
    assert result.kind == "text"
    assert result.body
    assert "news_card_failed" in result.audit_tags


def test_empty_backend_output_degrades_to_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """后端「正常返回但没出图」（None / 空字节）同样回纯文本。"""
    _patch_items(monkeypatch, _sample_items(2))
    for png in (None, b""):
        capability = build_news_capability(
            config=None, render_backend=_FakeBackend(png=png), card_dir=str(tmp_path)
        )
        result = capability(_message(), _decision())
        assert result.kind == "text"
        assert result.body
        assert "news_card_failed" in result.audit_tags


def test_unwritable_card_dir_degrades_to_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """落盘口本身坏掉（目录位被文件占住）也不能带走这条回复。"""
    _patch_items(monkeypatch, _sample_items(2))
    blocked = tmp_path / "cards"
    blocked.write_text("不是目录", encoding="utf-8")
    capability = build_news_capability(
        config=None, render_backend=_FakeBackend(), card_dir=str(blocked)
    )
    result = capability(_message(), _decision())
    assert result.kind == "text"
    assert result.body
    assert "news_card_failed" in result.audit_tags


def test_fetch_failure_never_renders_a_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """取不到条目就不出卡：一张「暂无」卡比不出卡更像谎报。"""
    _patch_items(monkeypatch, [])
    backend = _FakeBackend()
    result = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )(_message(), _decision())
    assert result.kind == "text"
    assert backend.seen == []
    assert "news:fetch_failed" in result.audit_tags


# ---------------------------------------------------------------------------
# ③ 推送路径不出卡（既有设计裁定）+ 能力侧不自取后端
# ---------------------------------------------------------------------------


def test_scheduler_paths_never_build_the_news_capability() -> None:
    """根装配的每个调度器注册函数都不许碰快报能力（21:30 群摘要/早晚简报保持纯文本）。"""
    source = (REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("_register_"):
            continue
        referenced = {
            getattr(call.func, "name", "")
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        }
        if {"build_news_capability", "_render_card"} & referenced:
            offenders.append(node.name)
    assert not offenders, f"调度器里出现了快报出卡路径：{offenders}"


def test_news_digest_card_has_exactly_one_production_consumer() -> None:
    """生产侧引用这张卡模板的文件**只有一个**：快报能力本身。

    反向用途：将来谁把同一张卡塞进推送/别的入口，本锁当场点名（禁第二通路）。
    """
    consumers: set[str] = set()
    for folder in ("plugins", "scripts"):
        for path in (REPO_ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "render_news_digest_card_html" not in text:
                continue
            # 模板的产出方（bridge 与再导出垫片）不算消费者。
            if "card_render" in path.parts or path.parts[-3:] == (
                "plugins",
                "bot_unified_runtime",
                "output",
            ):
                continue
            consumers.add(path.relative_to(REPO_ROOT).as_posix())
    assert consumers == {
        "plugins/bot_unified_runtime/domains/subscribe/capabilities/news.py"
    }, f"卡面消费者不唯一：{sorted(consumers)}"


def test_capability_never_builds_or_fetches_its_own_backend() -> None:
    """缺省（未注入后端）＝逐字节维持接卡前形态：能力侧不自建、也不自取进程级后端。

    后端只能由装配层交进来（与 epic/weather/market/today_history 同一口径）。
    自取 `get_shared_render_backend` 会让「没注入」与「注入但不可用」两种态混成一团，
    测试序里还会变成按全局状态漂移的不确定行为。
    """
    source = Path(news_module.__file__).read_text(encoding="utf-8")
    for banned in ("build_render_backend", "get_shared_render_backend"):
        assert banned not in source, f"能力侧自取/自建渲染后端：{banned}"


def test_default_call_shape_stays_pure_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`build_news_capability(config)`（root 现行调用形态）⇒ 仍是 text，未注入=零变更。"""
    _patch_items(monkeypatch, _sample_items(2))
    result = build_news_capability(None)(_message(), _decision())
    assert result.kind == "text"
    assert result.images == []
    assert "news_card_disabled" in result.audit_tags
    assert "news_card_failed" not in result.audit_tags


# ---------------------------------------------------------------------------
# 载荷契约对照（键名现读自 bridge:1879 与 news_digest_card.html）
# ---------------------------------------------------------------------------


def test_payload_keys_are_the_ones_the_bridge_reads() -> None:
    """payload 顶层键 ⊆ bridge 实际取数键（自造键=静默丢内容，必须当场红）。"""
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    start = source.index("def render_news_digest_card_html(")
    body = source[start : source.index("\ndef ", start + 10)]
    read_keys = set(re.findall(r'data\.get\("([a-z_]+)"\)', body))
    row_keys = set(re.findall(r'item\.get\("([a-z_]+)"\)', body))
    assert read_keys, "没从 bridge 读到取数键（它改名了，本锁该跟着改）"

    payload = build_news_card_content(
        _sample_items(2), label="科技", date_text="2026-09-26", config=None
    )
    assert read_keys >= {"title", "sub", "foot", "items", "bot_name", "bot_avatar_url"}
    assert set(payload) <= read_keys, f"payload 有 bridge 不吃的键：{set(payload) - read_keys}"
    for row in payload["items"]:
        assert set(row) <= row_keys, f"条目行有模板不读的键：{set(row) - row_keys}"
        assert set(row) == {"source", "time", "name", "snip"}


def test_card_never_carries_urls_or_local_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """隐私/刷屏面：条目 URL 整段不上卡；卡面文本先过统一打码尺。"""
    leaky = [
        NewsItem(
            title="有人在 C:\\Users\\someone\\.env 里存了 sk-abcdefgh12345",
            url="https://secret-host.example.com/a/b?token=***",
            source="某源",
            published_at=None,
            category="tech",
            summary="正文里又写了一遍 C:/Users/somebody/secrets 这串路径。",
        )
    ]
    payload = build_news_card_content(leaky, label="科技", date_text="", config=None)
    row = payload["items"][0]
    joined = " ".join([row["name"], row["snip"], row["source"], payload["sub"]])
    assert "sk-abcdefgh12345" not in joined
    assert "Users" not in joined, "本机盘符路径泄漏到卡面"
    assert "token" not in joined
    assert "secret-host.example.com" not in joined, "条目 URL 上了卡"
    assert "<本机路径已隐藏>" in joined
    assert row["time"] == "", "时间未知的条目不许把猜测值标上卡"
    # 同一份条目走真模板，HTML 里同样不得出现这些形态。
    html = bridge.render_news_digest_card_html(payload)
    assert "Users" not in html and "secret-host.example.com" not in html


def test_card_foot_is_a_constant_never_built_from_items() -> None:
    """模板页脚是 `{{ foot | safe }}`（不转义）⇒ 只允许常量。

    把条目标题/来源拼进 foot 等于让外部 RSS 内容写 HTML：本锁钉死这条缝。
    """
    hostile = [
        NewsItem(
            title="<script>alert(1)</script>",
            url="https://x.example",
            source="<img src=x onerror=alert(2)>",
            published_at=None,
            category="tech",
            summary="<b>粗体摘要</b>",
        )
    ]
    payload = build_news_card_content(hostile, label="科技", config=None)
    assert payload["foot"] == _CARD_FOOT
    html = bridge.render_news_digest_card_html(payload)
    foot_block = re.search(r'<div class="foot glass">(.*?)</div>', html, re.DOTALL)
    assert foot_block is not None
    assert foot_block.group(1) == _CARD_FOOT
    # 条目字段必须被转义后呈现（不转义=卡面 HTML 由外部 RSS 决定）。
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_digest_is_stable_and_content_sensitive() -> None:
    items = _sample_items(2)
    first = build_news_card_content(items, label="科技", date_text="2026-09-26")
    same = build_news_card_content(list(items), label="科技", date_text="2026-09-26")
    changed = build_news_card_content(
        _sample_items(2)[:1], label="科技", date_text="2026-09-26"
    )
    other_label = build_news_card_content(items, label="综合", date_text="2026-09-26")
    assert news_card_digest(first) == news_card_digest(same)
    assert news_card_digest(first) != news_card_digest(changed)
    assert news_card_digest(first) != news_card_digest(other_label)


def test_card_title_and_date_share_the_text_one_time_source() -> None:
    """卡标题=正文同款「今日快报 · 类目」；日期取自正文首行，不在卡上另起一次时钟。"""
    items = _sample_items(2)
    body = format_news_brief(items, "科技")
    payload = build_news_card_content(
        items, label="科技", date_text=news_module._brief_date_text(body)
    )
    assert payload["title"] == "今日快报 · 科技"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["sub"].split(" · ")[0])
    # 行形不符（首行没有三段）⇒ 回空串，卡上整段省略而不是编一个日期。
    assert news_module._brief_date_text("今日快报 · 科技") == ""
    assert news_module._brief_date_text("") == ""


# ---------------------------------------------------------------------------
# ③′ 多源同日呈现（2026-10-08）：按域分组、出处并列、诚实折叠
# ---------------------------------------------------------------------------


def _mixed_items(per_cat: dict[str, int]) -> list[NewsItem]:
    """按域造条目（aware 时间；标题带域前缀保证互不同题，折叠账可精确预期）。"""
    base = datetime(2026, 10, 8, 8, 0, tzinfo=_UTC)
    items: list[NewsItem] = []
    seq = 0
    for category, count in per_cat.items():
        for index in range(count):
            seq += 1
            items.append(
                NewsItem(
                    title=f"{category}事件{index}",
                    url=f"https://example.invalid/{seq}",
                    source="某源",
                    published_at=base + timedelta(minutes=seq),
                    category=category,
                    summary=f"{category}摘要{index}",
                )
            )
    return items


def _conservation_report(payload: dict[str, Any], received: int) -> list[str]:
    """守恒判据的**唯一谓词**：卡上「铺开+注明」必须恰等于交给卡的全部条数。

    真值腿与注毒腿共用这一把尺（判据只写一遍，两腿各证一次，不造第二形）。
    返回违规点名列表；空表=守恒成立。折了不报（hidden>0 而注脚缺位）与报了没折
    （hidden=0 却带注脚）都在此现形——「缺牙未修」同型的构造入口被这条封死。
    """
    groups = payload.get("groups") or []
    shown = sum(len(group.get("rows") or ()) for group in groups)
    hidden = sum(int(group.get("hidden") or 0) for group in groups)
    problems: list[str] = []
    if shown + hidden != received:
        problems.append(f"铺开{shown}+折掉{hidden} != 应收{received}（有条目没进任何一本账）")
    if shown != len(payload.get("items") or ()):
        problems.append("扁平 items 与分组铺开数不等（同一批条目出现两本账）")
    for group in groups:
        group_hidden = int(group.get("hidden") or 0)
        if group_hidden > 0 and not str(group.get("more") or ""):
            problems.append(f"域「{group.get('label')}」折了 {group_hidden} 枚却没注脚＝缺牙同型")
        if group_hidden == 0 and str(group.get("more") or ""):
            problems.append(f"域「{group.get('label')}」没折却带注脚＝虚报")
    return problems


def test_grouped_payload_conserves_and_bounds_every_item() -> None:
    """30 条四域：逐条要么上卡、要么计入折叠账；单域与全卡各有铺开上限；
    域序＝CATEGORY_LABELS 登记序（科技→财经→国际→时政，本件不抄第二份表）。"""
    items = _mixed_items({"tech": 12, "finance": 8, "world": 6, "politics": 4})
    payload = build_news_card_content(items, label="综合", date_text="2026-10-08", config=None)
    assert _conservation_report(payload, len(items)) == []
    cap_group = news_module._CARD_GROUP_CAP
    cap_total = news_module._CARD_TOTAL_CAP
    for group in payload["groups"]:
        assert len(group["rows"]) <= cap_group, f"域「{group['label']}」铺开破单域上限"
    assert len(payload["items"]) <= cap_total, "全卡铺开破总量上限（一屏平铺的老形态回潮）"
    labels = [group["label"] for group in payload["groups"]]
    assert labels == ["科技", "财经", "国际", "时政"], f"域序脱离登记册: {labels}"
    hidden = {group["label"]: group["hidden"] for group in payload["groups"]}
    assert hidden["科技"] == 12 - cap_group and hidden["财经"] == 8 - cap_group


def test_total_cap_still_raises_bare_band_with_full_note() -> None:
    """总量闸切到的域：域带仍在场、全量计入注脚——整域静默消失比切条更恶。"""
    per_cat = 5
    items = _mixed_items(
        {"tech": per_cat, "finance": per_cat, "world": per_cat, "politics": per_cat}
    )
    payload = build_news_card_content(items, label="综合", config=None)
    assert _conservation_report(payload, len(items)) == []
    bands = {group["label"]: group for group in payload["groups"]}
    assert len(bands) == 4, "四个域都在册，一个都不许缺席"
    tail = [g for g in payload["groups"] if not g["rows"]]
    assert tail and all(g["hidden"] > 0 and g["more"] for g in tail), (
        "被总量闸清零的域必须带全量折叠注脚在场"
    )
    assert str(bands["时政"]["hidden"]) in bands["时政"]["more"]


def test_all_folded_outlets_reach_the_card() -> None:
    """跨源同题折叠的出处**全部**上卡（旧 payload 只上 sources 首枚＝折叠在卡面
    退化成单源，出处被静默吃掉）。"""
    folded = NewsItem(
        title="多方会谈进入第二天",
        url="https://example.invalid/a",
        source="BBC中文",
        sources=("BBC中文", "纽约时报", "时代"),
        published_at=datetime(2026, 10, 8, 8, 0, tzinfo=_UTC),
        category="world",
        summary="会谈继续。",
    )
    payload = build_news_card_content([folded], label="综合", config=None)
    row = payload["items"][0]
    for outlet in ("BBC中文", "纽约时报", "时代"):
        assert outlet in row["source"], f"出处「{outlet}」没上卡"
    html = bridge.render_news_digest_card_html(payload)
    assert "纽约时报" in html and "时代" in html


def test_capability_audit_tags_count_the_fold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """折叠账同录入审读面：卡出了几组、折了几枚，机器侧与卡面同一本账。"""
    items = _mixed_items({"tech": 15})
    _patch_items(monkeypatch, items)
    backend = _FakeBackend()
    result = build_news_capability(
        config=None, render_backend=backend, card_dir=str(tmp_path)
    )(_message("快报"), _decision())
    assert "news_card_groups:1" in result.audit_tags
    assert f"news_card_hidden:{15 - news_module._CARD_GROUP_CAP}" in result.audit_tags


def test_poisoning_the_fold_account_turns_conservation_red() -> None:
    """注毒自证：把「折了多少」从账上抹掉（hidden 恒 0），守恒尺必须点名——
    否则上面的绿可能只是尺子瞎（本仓「生成了没发出」病的判据有牙证明）。"""
    source = Path(news_module.__file__).read_text(encoding="utf-8")
    anchor = "hidden = len(rows) - shown_count"
    assert source.count(anchor) == 1, "注毒锚点失配（构造口改样了，先修本锁）"
    mutated = source.replace(anchor, "hidden = 0  # 注毒：折而不报")
    namespace: dict[str, Any] = {
        "__name__": "news_poisoned_fold_account",
        "__file__": str(news_module.__file__),
    }
    exec(  # noqa: S102 - 注毒台：内存里跑一份改账的副本，不落盘、不改真文件
        compile(mutated, "<poison:news-fold>", "exec"), namespace
    )
    items = _mixed_items({"tech": 15})
    poisoned = namespace["build_news_card_content"](items, label="综合", config=None)
    assert _conservation_report(poisoned, len(items)), "注毒未被守恒尺抓住＝判据是装饰"
    calm = build_news_card_content(items, label="综合", config=None)
    assert _conservation_report(calm, len(items)) == [], "对照态不红，红才归因于注毒"


# ---------------------------------------------------------------------------
# ④ 注毒自证：兜底一摘，失败态当场炸
# ---------------------------------------------------------------------------
_POISON_ANCHOR = (
    "    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本快报，契约零破坏。\n"
    "        return \"\"\n"
)
_POISON_REPLACEMENT = (
    "    except ZeroDivisionError:  # 注毒：兜底被摘掉（本锁要求失败态必炸）\n"
    "        return \"\"\n"
)


def test_poisoning_the_render_guard_turns_the_failure_case_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """判据有牙证明：只把 `_render_card` 的兜底换掉，其余一字不动 ⇒ 异常上抛。

    与 `test_backend_exception_degrades_to_text` 成对：那枚绿是本枚红换来的。
    """
    source = Path(news_module.__file__).read_text(encoding="utf-8")
    assert source.count(_POISON_ANCHOR) == 1, "注毒锚点失配（news.py 改样了，先修本锁）"
    mutated = source.replace(_POISON_ANCHOR, _POISON_REPLACEMENT)
    namespace: dict[str, Any] = {
        "__name__": "news_poisoned_for_proof",
        "__file__": str(news_module.__file__),
    }
    exec(  # noqa: S102 - 注毒台：内存里跑一份摘掉兜底的副本，不落盘、不改真文件
        compile(mutated, "<poison:news.py>", "exec"), namespace
    )
    _patch_items(monkeypatch, _sample_items(2))
    # 同一把桩也要钉进注毒副本的全局命名空间：exec 出来的那份自己 import 了真
    # `fetch_headlines`，真实取数一空（RSS 抖动）能力就在出卡前早退，RuntimeError
    # 根本轮不到抛 ⇒ 本锁会以「DID NOT RAISE」随机假红。
    namespace["fetch_headlines"] = lambda category, **kw: _sample_items(2)
    poisoned = namespace["build_news_capability"](
        config=None,
        render_backend=_FakeBackend(raises=RuntimeError("boom")),
        card_dir=str(tmp_path),
    )
    with pytest.raises(RuntimeError):
        poisoned(_message(), _decision())
    # 反向自检：兜底在位时同一发调用不炸（否则上面的红是环境造成的，不是注毒造成的）。
    calm = build_news_capability(
        config=None,
        render_backend=_FakeBackend(raises=RuntimeError("boom")),
        card_dir=str(tmp_path),
    )(_message(), _decision())
    assert calm.kind == "text"


# ---------------------------------------------------------------------------
# 待主代理落地的装配接线（在册的接缝锁：接线后删标记转正）
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "接缝锁·装配层尚未把渲染后端交给快报：根 __init__.py 的 "
        "_build_news_with_backend 仍是 build_news_capability(config_)，"
        "且 @news.handle() 直调 build_news_capability（绕过那个 wrapper）。"
        "两行落地即转绿。〔expiry=2026-10-31 owner=SEAT-MAIN 摘牌=后端注入落地后删本标记〕"
    ),
)
def test_assembly_hands_the_render_backend_to_news() -> None:
    """生产活性判据：三个入口（matcher / 别名链 / 自然语言链）都拿到渲染后端。

    未落地前本件 xfail＝诚实挂账，不许当作已上线。
    """
    source = (REPO_ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    wrapper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_news_with_backend"
    )
    kwargs = {
        keyword.arg
        for call in ast.walk(wrapper)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
    }
    assert "render_backend" in kwargs, "wrapper 没把后端交给能力"

    # 裸命令 matcher 必须走 wrapper，而不是直调 build_news_capability（否则该入口永不出卡）。
    matcher_calls = re.findall(
        r"_run_simple_capability\(\s*bot,\s*event,\s*([A-Za-z_]+),\s*\"bot\.news\"",
        source,
    )
    assert matcher_calls == ["_build_news_with_backend"], f"matcher 仍直调：{matcher_calls}"


# ---------------------------------------------------------------------------
# ⑤ 席 W-8（2026-10-12）：跨源同题折叠的**两栏读数尺**（去重前／去重后／按源折叠）
# ---------------------------------------------------------------------------
# 补的是「NO_RULER_ON_CALL:去重前后条数」这一格：这条链此前只有「出了快报」一个读数，
# 重复率与「某源静音」外部一律读不出（主人第 ⑤ 条常令要「抓→洗→归类」可核对、
# 第 ④ 条要故障能定位，这一格是那两条的公共底座）。
# 🔴 判据一律**派生式**：恒等式现算、不写死任何条数；账本由折叠真身同一趟循环记下，
# 本件不重算第二遍（第二套去重逻辑＝本仓最贵的一族错误）。
# 🔴 全程离线：折叠真身是纯函数；端到端那条只 patch 本域声明的唯一出口
# ``news_feeds._fetch_feed_text``（假 RSS 字符串），不触网、不出卡、不起浏览器。

_SAME_TITLE_A = "央行宣布下调存款准备金率 0.5 个百分点"
_SAME_TITLE_B = "  央行宣布下调存款准备金率0.5个百分点  "  # 归一后与上枚同题（空白形差）
_OTHER_TITLE = "沿江高铁新建区间今日开通试运营"


def _ruler_items() -> list[NewsItem]:
    """含重复的样本：同题三枚（三家各报一次）＋一枚异题。"""
    return [
        NewsItem(title=_SAME_TITLE_A, url="https://www.ithome.com/1", source="IT之家"),
        NewsItem(title=_SAME_TITLE_B, url="https://www.wallstreetcn.com/2", source="华尔街见闻"),
        NewsItem(title=_OTHER_TITLE, url="https://feeds.bbci.co.uk/3", source="BBC中文"),
        NewsItem(title=_SAME_TITLE_A, url="https://www.chinanews.com.cn/4", source="中国新闻网"),
    ]


def _fold_identity_problems(before: int, after: int, folded: int) -> list[str]:
    """恒等式的尺（现算，不写死条数）：``去重前 == 去重后 + 折叠``。"""
    problems: list[str] = []
    if before != after + folded:
        problems.append(f"恒等式不成立：去重前 {before} ≠ 去重后 {after} + 折叠 {folded}")
    return problems


def test_fold_account_identity_holds_and_tally_adds_up() -> None:
    """判据①：恒等式＋两本分列账各自都对得上总数（吃一笔不记账即红）。"""
    sink: list[NewsFoldAccount] = []
    folded = fold_same_topic(_ruler_items(), account_out=sink)
    assert len(sink) == 1, "折叠真身没把账带出来＝读数尺在这一条路上是装饰"
    account = sink[0]
    assert _fold_identity_problems(account.before, account.after, account.folded) == []
    assert account.after == len(folded)
    assert account.before == len(_ruler_items())
    # 喂进去的样本含重复 ⇒ 折叠栏必非零（写死成 0 的那一发注毒咬的就是这里）。
    assert account.folded > 0, "样本里明明有同题，折叠栏却报零"
    assert sum(account.folded_by_source.values()) == account.folded
    assert sum(account.seen_by_source.values()) == account.before
    assert account.body_dropped == 0  # 本组样本没过正文门，不该凭空冒出去重外的少条


def test_fold_ruler_shape_lock_collapses_same_title_not_different_one() -> None:
    """判据②：最小形状锁——同题（含同源、含空白形差）必折叠，异题一枚都不许误折。"""
    sink: list[NewsFoldAccount] = []
    folded = fold_same_topic(_ruler_items(), account_out=sink)
    account = sink[0]
    assert [row.title for row in folded] == [_SAME_TITLE_A, _OTHER_TITLE]
    assert folded[0].sources == ("IT之家", "华尔街见闻", "中国新闻网"), folded[0].sources
    # 被折掉的枚数按**它自己的出处**分列：主位那枚不算吃掉。
    assert account.folded_by_source == {"华尔街见闻": 1, "中国新闻网": 1}
    assert account.seen_by_source["IT之家"] == 1

    distinct = [
        NewsItem(title="甲计划今日公布", url="https://www.ithome.com/a", source="IT之家"),
        NewsItem(title="乙计划今日公布", url="https://www.wallstreetcn.com/b", source="华尔街见闻"),
    ]
    second: list[NewsFoldAccount] = []
    assert len(fold_same_topic(distinct, account_out=second)) == 2
    assert second[0].folded == 0
    assert second[0].folded_by_source == {}

    same_outlet = [
        NewsItem(title="丙芯片发布新一代架构", url="https://www.ithome.com/c1", source="IT之家"),
        NewsItem(title="丙芯片发布新一代架构", url="https://www.ithome.com/c2", source="IT之家"),
    ]
    third: list[NewsFoldAccount] = []
    assert len(fold_same_topic(same_outlet, account_out=third)) == 1
    assert third[0].folded_by_source == {"IT之家": 1}
    assert _fold_identity_problems(third[0].before, third[0].after, third[0].folded) == []


#: 唯一出口打桩用的假 RSS：同题两枚（同一家重列）＋一枚异题，全离线常量。
_RULER_RSS = (
    '<rss version="2.0"><channel><title>IT之家</title>'
    "<item><title>甲线路今日开通试运营</title>"
    "<link>https://www.ithome.com/1/001/001.htm</link>"
    "<description>第一条真实内容行，供摘要呈现核对。</description></item>"
    "<item><title>甲线路今日开通试运营</title>"
    "<link>https://www.ithome.com/1/001/002.htm</link>"
    "<description>同题的第二枚，按判据应与上枚折成一格。</description></item>"
    "<item><title>乙芯片发布新一代架构</title>"
    "<link>https://www.ithome.com/1/001/003.htm</link>"
    "<description>异题的一枚，不该被并到别处去。</description></item>"
    "</channel></rss>"
)


def test_capability_reports_fold_ruler_on_the_brief_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """端到端：快报末尾与审读标签带得出「去重前／去重后／按源折叠」，且三栏自洽。

    走的是真链路（真 ``fetch_headlines`` → 真合并 → 真折叠），只有本域声明的唯一
    出口被打桩；类目取 tech（名册派生后该类恰好一枚实装源 ⇒ 零补投、零网络）。
    """
    feeds_module.reset_news_cache()
    feeds_module.reset_news_fetch_state()
    reset_fold_accounts()
    monkeypatch.setattr(
        feeds_module, "_fetch_feed_text", lambda url, timeout_seconds: _RULER_RSS
    )
    seq_before = fold_reading_sequence()
    try:
        result = build_news_capability(
            config=None, render_backend=None, card_dir=str(tmp_path)
        )(_message("科技快报"), _decision())
        assert result.kind == "text", "没给后端就该是纯文本，读数尺不该把契约带歪"
        entry = fold_account_for("tech")
        assert entry is not None and entry[0] > seq_before, "本轮没算出账＝这一条链上仍然无尺"
        account = entry[1]
        assert account.folded > 0, "假 RSS 里就写着同题，折叠栏却读不出"
        assert _fold_identity_problems(account.before, account.after, account.folded) == []

        tail = result.body.splitlines()[-1]
        numbers = [int(raw) for raw in re.findall(r"\d+", tail)]
        assert len(numbers) == 3, f"末行读数不是三栏：{tail!r}"
        before_text, after_text, folded_text = numbers
        assert (before_text, after_text, folded_text) == (
            account.before,
            account.after,
            account.folded,
        ), "末尾与账本两个口径＝两本账，正是要防的漂移"
        assert _fold_identity_problems(before_text, after_text, folded_text) == []
        # 折叠后同题只占一格（正文真少了一条，不只是账上说说）。
        assert result.body.count("甲线路今日开通试运营") == 1

        for expected in (
            f"news_fold_before:{account.before}",
            f"news_fold_after:{account.after}",
            f"news_fold_dropped:{account.folded}",
        ):
            assert expected in result.audit_tags, f"机器侧缺读数标签 {expected}"
        assert f"news_fold_outlet:IT之家:{account.folded_by_source['IT之家']}" in result.audit_tags
        assert "news_fold_unread" not in result.audit_tags
    finally:
        assert feeds_module.wait_for_outstanding_fetches(
            20.0
        ), "补投那批没收干＝还原后会打到真网络"
        feeds_module.reset_news_cache()
        feeds_module.reset_news_fetch_state()
        reset_fold_accounts()


def test_fold_ruler_is_not_carried_over_from_a_round_that_did_not_compute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """陈账不许串台：本轮的 fetch 被替掉（没算过）⇒ 末尾不加读数、只记 ``unread``。

    这条同时是「读数尺不把既有正文弄脏」的锁：``body`` 仍逐字＝``format_news_brief``。
    """
    items = _sample_items(2)
    reset_fold_accounts()
    # 先造一枚**别的轮次**的账（进程级读数册里躺着东西），再跑本轮被替掉 fetch 的能力。
    stale_sink: list[NewsFoldAccount] = []
    fold_same_topic(_ruler_items(), account_out=stale_sink)
    assert stale_sink[0].folded > 0
    _patch_items(monkeypatch, items)
    result = build_news_capability(
        config=None, render_backend=None, card_dir=str(tmp_path)
    )(_message("科技快报"), _decision())
    assert result.body == format_news_brief(items, "科技"), "没算过却把上一轮的账贴到本轮正文上"
    assert "news_fold_unread" in result.audit_tags
    assert not [tag for tag in result.audit_tags if tag.startswith("news_fold_before")]
