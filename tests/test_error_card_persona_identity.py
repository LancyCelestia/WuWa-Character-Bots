"""诊断卡署名跟人格外壳走（2026-09-28 用户裁定；台账 #60 人格热切换 mandate 的卡面腿）。

锁四件：
① 英文署名派生尺 ``brand_name_en_for``——slug 可用就派生，空/``default``/非 ASCII 回落品牌常量；
② 桥面把 ``bot_name`` / ``bot_name_en`` 真送进胶囊 DOM（不再只吃中文名）；
③ 卡面 payload 的署名来自人格单口，**不再写死「守岸人」**；
④ 单口取不到人格时整对交空串，由渲染侧统一回落品牌（卡面不许出现空署名）。
全部离线：人格册（personas/registry/）属另一波未入库件，本文件一律不依赖其内容。
"""

from __future__ import annotations

from pathlib import Path

import plugins.bot_unified_runtime.domains.ops.monitor.error_report as er
from plugins.bot_unified_runtime.domains.render.card_render import bridge
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_NAME_EN,
    BRAND_THEME,
    brand_name_en_for,
)


def test_english_signature_derives_from_persona_slug() -> None:
    assert brand_name_en_for("shorekeeper") == "Shorekeeper"
    assert brand_name_en_for("danya") == "Danya"
    assert brand_name_en_for("jinxi_devoraa") == "Jinxi Devoraa"
    # 拿不出可用 slug 的三态一律回落品牌，绝不渲染空署名。
    for unusable in ("", "   ", "default", "DEFAULT", "守岸人", "sh@nnon"):
        assert brand_name_en_for(unusable) == BRAND_NAME_EN, unusable


def test_capsule_renders_persona_chinese_and_english_names() -> None:
    html_text = bridge.render_error_card_html(
        {
            "human_text": "这条没走完。",
            "exc_type": "ValueError",
            "bot_name": "丹枫",
            "bot_name_en": "Danyfeng",
        }
    )
    assert "丹枫" in html_text and "Danyfeng" in html_text, "胶囊没吃到人格署名"
    assert BRAND_NAME_EN not in html_text, "人格已给英文名，仍打品牌常量＝回落吞掉了真值"


def test_capsule_without_persona_falls_back_to_brand() -> None:
    html_text = bridge.render_error_card_html({"human_text": "x", "exc_type": "E"})
    assert BRAND_THEME.display_name in html_text and BRAND_NAME_EN in html_text


def test_error_report_signature_comes_from_persona_accessor(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.character import persona_profile

    seen: dict[str, str] = {}

    def _fake(persona_id: str, *, registry: object = None, config: object = None) -> str:
        seen["persona_id"] = persona_id
        return "丹枫" if persona_id == "danyfeng" else ""

    monkeypatch.setattr(persona_profile, "current_bot_nickname", _fake)
    getter = {"bot_persona_profile_id": "danyfeng", "bot_persona_display_name": "备用名"}.get
    assert er._persona_signature(getter) == ("丹枫", "Danyfeng")
    assert seen["persona_id"] == "danyfeng"
    # 单口取不到名字时才用兼容显示名；册里没有的 persona_id 也要把英文名派生出来。
    monkeypatch.setattr(persona_profile, "current_bot_nickname", lambda *a, **k: "")
    assert er._persona_signature(getter) == ("备用名", "Danyfeng")
    # 两样都没有 ⇒ 整对交空串，回落规则留在渲染侧（不在这里抄第二份）。
    empty = {"bot_persona_profile_id": "", "bot_persona_display_name": ""}.get
    assert er._persona_signature(empty) == ("", BRAND_NAME_EN)


def test_payload_no_longer_hardcodes_the_brand_name() -> None:
    """静态腿：卡面 payload 里不许再出现写死的中文署名（人格切换即失效的形态）。"""
    src = Path(er.__file__).read_text(encoding="utf-8")
    assert '"bot_name": "守岸人"' not in src, "又有人把署名写回死字面量"
    assert src.count('"bot_name_en": signature[1]') == src.count('"bot_name": signature[0]') >= 2
