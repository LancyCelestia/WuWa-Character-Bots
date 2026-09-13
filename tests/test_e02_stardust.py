"""E02 星尘上升定格（庆祝粒子·静版）回归（docs/design/visual-effects-catalog.md §E02）。

全离线：Jinja2 渲染 + 字符串断言，不依赖 playwright、不联网。约束：
- 纯 CSS 静态星点层：零 animation、零 JS、零新增 box-shadow、零新增 keyframes；
- 星点仅用 background 径向渐变（不触两枚阴影 token 铁律）；
- 位置/粒径/透明度由 --phase（payload digest，E01 已钉帧）确定性派生，
  同 payload 永远同构图（D0）；
- 好感卡：私聊且 bot_to_user 印象好感 ≥ 50（挚友/独一份高阶档）常显微版；
  群排行/算法说明卡不显示（payload 无升档标记，按任务书做高阶档常显版）；
- 占卜结果卡（universal 载体，platform="divination"）常显微版；
  其他 universal 卡零影响；
- 密度护栏：≤24 枚、粒径 2–5px、透明度 0.06–0.35。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from plugins.bot_unified_runtime.output.card_render import bridge

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# 占卜结果卡经 build_parsed_content(item_kind="article") → page_type="article"，
# 落在 universal 模板 mica-stage/video-card-shell 分支；platform 直达模板上下文。
_DIVINATION_PAYLOAD = {
    "platform": "divination",
    "page_type": "article",
    "title": "塔罗指引",
    "summary": "星星正位：希望与疗愈。",
}

_AFFINITY_HIGH_TIER_PAYLOAD = {
    "pc": "#607080",
    "mode": "private",
    "bot_to_user": {"score": 82.0, "tier": "独一份", "bar": 82.0},
    "user_to_bot": {"score": 60.0, "tier": "挚友", "bar": 60.0},
    "rules": [],
}

_MOTE_SPAN_RE = re.compile(r'<span class="star-mote ([^"]+)" style="([^"]+)">')
_STYLE_FIELD_RE = {
    key: re.compile(rf"{key}:([0-9.]+)(px|%)?")
    for key in ("left", "bottom", "width", "height", "opacity")
}


def _motes(html_text: str) -> list[tuple[str, str]]:
    return _MOTE_SPAN_RE.findall(html_text)


def _style_value(style: str, key: str) -> float:
    match = _STYLE_FIELD_RE[key].search(style)
    assert match, f"星点缺 {key}: {style!r}"
    return float(match.group(1))


def _star_css(name: str) -> str:
    """模板 <style> 内 E02 星尘层 CSS 块（按注释围栏提取）。"""
    css = re.search(
        r"<style>(.*)</style>",
        (_TEMPLATES_DIR / name).read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert css, f"{name} 缺 <style>"
    match = re.search(
        r"\.star-motes \{.*?\.star-mote\.sm-l \{[^}]*\}",
        css.group(1),
        re.DOTALL,
    )
    assert match, f"{name} 缺 E02 星尘层 CSS 块"
    return match.group(0)


# ==================== 1. 星尘层 CSS 存在且纯静态 ====================
def test_affinity_template_has_static_stardust_layer() -> None:
    css = _star_css("affinity_card.html")
    assert ".star-motes" in css and ".star-mote" in css
    # 三通道：wash-2 星空紫 / 白 / --pc-light。
    for token in ("var(--wash-2)", "#ffffff", "var(--pc-light)"):
        assert token in css, f"affinity 星尘缺色通道 {token}"
    # 纯静态：零 animation / 零 transition / 零 box-shadow / 零 keyframes。
    assert "animation" not in css
    assert "transition" not in css
    assert "box-shadow" not in css
    assert "keyframes" not in css
    # 星点只走 background（E02 约定：不触两枚阴影 token 铁律）。
    assert "background: radial-gradient(circle" in css


def test_universal_template_has_static_stardust_layer() -> None:
    css = _star_css("universal_card.html")
    assert ".star-motes" in css and ".star-mote" in css
    for token in ("var(--wash-2)", "#ffffff", "var(--pc-light)"):
        assert token in css, f"universal 星尘缺色通道 {token}"
    assert "animation" not in css
    assert "transition" not in css
    assert "box-shadow" not in css
    assert "keyframes" not in css


# ==================== 2. 触发条件 ====================
def test_affinity_high_tier_private_shows_motes() -> None:
    html_text = bridge.render_affinity_card_html(_AFFINITY_HIGH_TIER_PAYLOAD)
    motes = _motes(html_text)
    assert 10 <= len(motes) <= 24, f"好感高阶档星尘枚数异常: {len(motes)}"


def test_affinity_low_tier_no_motes() -> None:
    payload = dict(_AFFINITY_HIGH_TIER_PAYLOAD)
    payload["bot_to_user"] = {"score": 12.0, "tier": "友善（基准）", "bar": 12.0}
    assert not _motes(bridge.render_affinity_card_html(payload))


def test_affinity_group_and_algorithm_modes_no_motes() -> None:
    group = bridge.render_affinity_card_html(
        {
            "mode": "group",
            "me_id": "u1",
            "rows": [{"sender_id": "u1", "display_name": "群友", "score": 99.0}],
        }
    )
    algorithm = bridge.render_affinity_card_html({"mode": "algorithm"})
    assert not _motes(group)
    assert not _motes(algorithm)


def test_divination_card_shows_micro_motes() -> None:
    html_text = bridge.render_universal_card_html(dict(_DIVINATION_PAYLOAD))
    motes = _motes(html_text)
    assert 8 <= len(motes) <= 12, f"占卜微版星尘枚数异常: {len(motes)}"


def test_other_universal_cards_and_empty_payload_unaffected() -> None:
    bilibili = bridge.render_universal_card_html(
        {"platform": "bilibili", "page_type": "video", "title": "标题", "name": "UP"}
    )
    generic = bridge.render_universal_card_html(
        {"platform": "weibo", "title": "普通解析卡"}
    )
    empty = bridge.render_universal_card_html({})
    assert not _motes(bilibili)
    assert not _motes(generic)
    assert not _motes(empty)


# ==================== 3. 构图确定性（D0：同 payload 同星图） ====================
def test_affinity_motes_deterministic_per_payload() -> None:
    a = _motes(bridge.render_affinity_card_html(_AFFINITY_HIGH_TIER_PAYLOAD))
    b = _motes(bridge.render_affinity_card_html(dict(_AFFINITY_HIGH_TIER_PAYLOAD)))
    assert a and a == b, "同 payload 两次渲染星图必须逐点一致"


def test_affinity_motes_differ_across_payloads() -> None:
    a = _motes(bridge.render_affinity_card_html(_AFFINITY_HIGH_TIER_PAYLOAD))
    other = dict(_AFFINITY_HIGH_TIER_PAYLOAD)
    other["user_to_bot"] = {"score": 61.0, "tier": "挚友", "bar": 61.0}
    b = _motes(bridge.render_affinity_card_html(other))
    assert a != b, "不同 payload 星图应有差异（digest 派生）"


def test_divination_motes_deterministic_per_payload() -> None:
    a = _motes(bridge.render_universal_card_html(dict(_DIVINATION_PAYLOAD)))
    b = _motes(bridge.render_universal_card_html(dict(_DIVINATION_PAYLOAD)))
    assert a and a == b


# ==================== 4. 密度/粒径/透明度护栏 ====================
def test_mote_guardrails_affinity_and_divination() -> None:
    for html_text in (
        bridge.render_affinity_card_html(_AFFINITY_HIGH_TIER_PAYLOAD),
        bridge.render_universal_card_html(dict(_DIVINATION_PAYLOAD)),
    ):
        motes = _motes(html_text)
        assert 1 <= len(motes) <= 24
        for channel, style in motes:
            assert channel in {"sm-v", "sm-w", "sm-l"}, f"未知色通道 {channel}"
            width = _style_value(style, "width")
            height = _style_value(style, "height")
            assert 2.0 <= width <= 5.0 and width == height, f"粒径越界: {style!r}"
            alpha = _style_value(style, "opacity")
            assert 0.06 <= alpha <= 0.35, f"透明度越界: {style!r}"
            left = _style_value(style, "left")
            bottom = _style_value(style, "bottom")
            assert 55.0 <= left <= 100.0, f"星尘应聚在卡面右侧: {style!r}"
            assert 0.0 <= bottom <= 90.0, f"纵向铺程越界: {style!r}"


# ==================== 5. 层在 .card 子树内（截图契约） ====================
class _CardScopeParser(HTMLParser):
    """检查 star-motes 容器落在根 .card 子树内。"""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.card_depth: int | None = None
        self.motes_depth: list[int] = []
        self.root_has_card = False

    @staticmethod
    def _classes(attrs) -> set[str]:  # type: ignore[no-untyped-def]
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        classes = self._classes(attrs)
        if tag == "div" and self.card_depth is None:
            self.root_has_card = "card" in classes
            self.card_depth = self.depth
        if "star-motes" in classes:
            self.motes_depth.append(self.depth)
        if tag not in ("img", "br", "meta", "link", "input", "hr"):
            self.depth += 1

    def handle_endtag(self, tag) -> None:  # type: ignore[no-untyped-def]
        if tag not in ("img", "br", "meta", "link", "input", "hr") and self.depth > 0:
            self.depth -= 1


def test_star_motes_inside_card_subtree() -> None:
    for html_text in (
        bridge.render_affinity_card_html(_AFFINITY_HIGH_TIER_PAYLOAD),
        bridge.render_universal_card_html(dict(_DIVINATION_PAYLOAD)),
    ):
        parser = _CardScopeParser()
        parser.feed(html_text)
        assert parser.root_has_card, "根元素必须带 card 类"
        assert parser.motes_depth, "缺 star-motes 容器"
        assert all(d > parser.card_depth for d in parser.motes_depth), (
            "star-motes 必须在 .card 子树内（截图目标契约）"
        )


# ==================== 6. 无低透明度越界（铁律 5 同源） ====================
def test_star_css_no_subfloor_alpha() -> None:
    for name in ("affinity_card.html", "universal_card.html"):
        css = _star_css(name)
        for value in re.findall(r"rgba\([^)]*?,\s*(0?\.\d+)\s*\)", css):
            assert float(value) >= 0.05, f"{name} 星尘 rgba alpha {value} < 0.05"
