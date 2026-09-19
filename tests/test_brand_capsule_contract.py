"""品牌胶囊契约锁（CAPFIX 2026-09-21，补评审 C-1「零契约覆盖」之 Critical）。

被锁对象（CAP1 唯一实现，用户裁定「所有图片加胶囊」）：
- ``domains/render/card_render/mica_shell.py`` 的 ``brand_capsule_css()`` /
  ``brand_capsule_html()``（:318/:345，2026-09-21 实核行号）；
- ``card_render/bridge.py:195 _capsule_context()`` 注入，7 张 Jinja 模板只留摆位。

承诺语义四态（每条都有对应断言，杀伤力经变异实证——评审席判 C-1 后补）：
① 有头像 → 胶囊内出 ``<img class="mc-avatar">``，圆点腿整体让位；
② 无头像 → 降级首字圆点 ``<span class="mc-dot">``，字取自品牌名单一来源；
③ 中文名 = ``theme_tokens.BRAND_THEME.display_name``、英文名 =
   ``theme_tokens.BRAND_NAME_EN``（写死第二处字面量 = 违约）；
④ 功能名为空 → ``mc-feature`` 段整段省略（不留「·」占位、不留空段）。

断言纪律（评审对旧门的批评，本文件不再犯）：全部落在**渲染产物**——
bridge/mica_shell 真函数的返回值与 7 张卡面的最终 HTML；不读模板源码字符串。
「模板里写着 ``{{ capsule_html }}``」不是契约，「产物里恰好一枚胶囊」才是。

杀伤力实证（变异只在 %TEMP% 副本上做，工作树实现零改动；逐条清单与复跑件
=docs/design/unify-audit-20260919/CAPFIX-impl.md §3；GREEN 基线 88 passed）：
- M1 组件返回空（=胶囊整枚被删）      → 62 红（面级 7 组锁 + 桥级 + 组件级全响）；
- M2 丢英文名腿（mc-en 不再产出）     → 25 红（含 7×名字单源、7×Shorekeeper 恰一次）；
- M3 丢头像腿（有头像也只剩圆点）     → 10 红（7×面级头像腿 + 组件态① + 顺序 + 转义）；
- M4a 组件内把中文名写死「守岸人」    → 2 红（组件单源回落锁 + 圆点同源锁）；
- M4b 桥层把中文名写死「守岸人」      → 8 红（7×面级单源 + 桥不硬编码锁）；
- M5 = 评审 sabotage2 原样复刻（英文名+头像腿+圆点三条腿全砍）→ 44 红。
对照：评审席做同类破坏时，旧门「好感度卡全绿」「四条腿砍三条全绿」。
"""

from __future__ import annotations

import copy
import html as _html
import re
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.render import bot_avatar as bot_avatar_mod
from plugins.bot_unified_runtime.domains.render.card_render import bridge, mica_shell
from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    BRAND_CAPSULE_CSS,
    brand_capsule_css,
    brand_capsule_html,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_NAME_EN,
    BRAND_THEME,
)

# ==================== 共享常量与取材工具 ====================

CAPSULE_OPEN = '<div class="mica-capsule">'
AVATAR_MARK = 'class="mc-avatar"'
DOT_MARK = 'class="mc-dot"'
NAME_MARK = 'class="mc-name"'
EN_MARK = 'class="mc-en"'
FEATURE_MARK = 'class="mc-feature"'

# 探针输入：刻意带 ASCII 首字母与需转义字符，专杀「写死守字/写死名字/漏转义」。
PROBE_CN = "Z测实例名"
PROBE_EN = "W哨兵EN"
PROBE_AVATAR = "file:///capsule-probe/avatar.png"
PROBE_FEATURE = "探针功能名"

# 7 张 Jinja 卡面（显式枚举，禁止 glob；新增模板入列时逐个登记）。
_PAYLOAD_FACES: dict[str, Any] = {
    "universal": bridge.render_universal_card_html,
    "market": bridge.render_market_card_html,
    "finance": bridge.render_finance_card_html,
    "song": bridge.render_song_candidates_html,
    "affinity": bridge.render_affinity_card_html,
    "error": bridge.render_error_card_html,
}
FACES: tuple[str, ...] = (*_PAYLOAD_FACES, "mermaid")

# 注：**不**在此登记各面功能名缺省字符串。评审 I-4 指出那是 bridge 六处硬编码
# （无中央来源），FIX-CAP-B 席正在收编（2026-09-21 在飞：`feature_label =
# _as_str(data.get("feature_label"))`，卡面缺省段陆续移除）。本锁因此只锁
# 「态④省略语义 + 显式功能名必落到产物」两条版本无关的契约，
# 缺省字符串本身归 I-4 施工席与其配套 catalog 门。


def _render_face(
    name: str,
    *,
    bot_name: str | None = None,
    avatar_url: str | None = None,
    feature_label: str | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> str:
    """按卡面真渲染（走 bridge 真函数）。mermaid 无 payload 通道，头像走
    ``bot_avatar_uri`` 单一入口，须以 monkeypatch 注入。None=不传该键。"""
    if name == "mermaid":
        if monkeypatch is not None and avatar_url is not None:
            monkeypatch.setattr(bot_avatar_mod, "bot_avatar_uri", lambda *a: avatar_url)
        return bridge.render_mermaid_html("graph TD;A-->B;")
    payload: dict[str, Any] = {}
    if bot_name is not None:
        payload["bot_name"] = bot_name
    if avatar_url is not None:
        payload["bot_avatar_url"] = avatar_url
    if feature_label is not None:
        payload["feature_label"] = feature_label
    return _PAYLOAD_FACES[name](payload)


def _patch_brand(
    monkeypatch: pytest.MonkeyPatch,
    *,
    display_name: str | None = None,
    name_en: str | None = None,
) -> None:
    """把品牌两枚单一来源换成哨兵值（frozen dataclass → copy + 模块属性替换；
    bridge 与 mica_shell 两侧同名引用都要换，缺一侧=测试假绿）。"""
    if display_name is not None:
        themed = copy.copy(BRAND_THEME)
        object.__setattr__(themed, "display_name", display_name)
        monkeypatch.setattr(bridge, "BRAND_THEME", themed)
        monkeypatch.setattr(mica_shell, "BRAND_THEME", themed)
    if name_en is not None:
        monkeypatch.setattr(mica_shell, "BRAND_NAME_EN", name_en)


# ==================== 态① / 态②：组件两腿 ====================


def test_component_with_avatar_emits_img_leg_and_no_dot() -> None:
    html = brand_capsule_html(
        bot_name=PROBE_CN, bot_name_en=PROBE_EN, avatar_url=PROBE_AVATAR
    )
    assert f'<img {AVATAR_MARK} src="{PROBE_AVATAR}"' in html
    assert DOT_MARK not in html, "有头像时圆点腿必须整体让位，不许 img/dot 并存"
    assert html.count(CAPSULE_OPEN) == 1


def test_component_without_avatar_degrades_to_first_char_dot() -> None:
    html = brand_capsule_html(bot_name=PROBE_CN)
    assert f'<span {DOT_MARK}>Z</span>' in html, "降级圆点取中文名首字（同源，非写死守字）"
    assert AVATAR_MARK not in html
    assert html.count(CAPSULE_OPEN) == 1


def test_component_empty_inputs_never_raise_and_never_collapse() -> None:
    """铁律：渲染面不因署名件炸整卡；无头像输入也不许把整枚胶囊省略。"""
    html = brand_capsule_html()
    assert html.startswith(CAPSULE_OPEN) and html.endswith("</div>")
    assert DOT_MARK in html and NAME_MARK in html and EN_MARK in html


# ==================== 态③：中英文名单一来源（杀 M4 / M2） ====================


def test_brand_name_en_constant_is_shorekeeper() -> None:
    assert BRAND_NAME_EN == "Shorekeeper"


def test_component_english_name_defaults_to_brand_name_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_brand(monkeypatch, name_en=PROBE_EN)
    html = brand_capsule_html()
    assert f'<span {EN_MARK}>{PROBE_EN}</span>' in html, (
        "英文名必须读 theme_tokens.BRAND_NAME_EN 单一来源（M2 探针）"
    )
    assert "Shorekeeper" not in html


def test_component_chinese_name_defaults_to_brand_theme_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_brand(monkeypatch, display_name=PROBE_CN)
    html = brand_capsule_html()
    assert f'<span {NAME_MARK}>{PROBE_CN}</span>' in html, (
        "中文名必须回落 BRAND_THEME.display_name 单一来源——写死「守岸人」即违约（M4）"
    )
    assert "守岸人" not in html


def test_degraded_dot_glyph_shares_brand_name_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """圆点字与品牌名同源（不许新写死第二处「守」）。"""
    _patch_brand(monkeypatch, display_name=PROBE_CN)
    html = brand_capsule_html()
    assert f'<span {DOT_MARK}>Z</span>' in html
    assert '<span class="mc-dot">守</span>' not in html


def test_explicit_bot_name_wins_over_single_source() -> None:
    html = brand_capsule_html(bot_name="实例自称", avatar_url=PROBE_AVATAR)
    assert f'<span {NAME_MARK}>实例自称</span>' in html


# ==================== 态④：功能名空 → 整段省略 ====================


@pytest.mark.parametrize("feature", ["", "   ", "\n"])
def test_component_empty_feature_omits_whole_segment(feature: str) -> None:
    html = brand_capsule_html(bot_name=PROBE_CN, feature_label=feature)
    assert FEATURE_MARK not in html, "功能名为空必须整段省略（不留空段、不留占位）"
    assert "·" not in html, "省略后不得残留分隔点占位"


def test_component_feature_segment_renders_after_names() -> None:
    html = brand_capsule_html(
        bot_name=PROBE_CN,
        bot_name_en=PROBE_EN,
        avatar_url=PROBE_AVATAR,
        feature_label=PROBE_FEATURE,
    )
    order = [html.index(m) for m in (AVATAR_MARK, NAME_MARK, EN_MARK, FEATURE_MARK)]
    assert order == sorted(order), "DOM 顺序承诺=头像→中文名→英文名→功能名"
    assert f'<span {FEATURE_MARK}>· {PROBE_FEATURE}</span>' in html


# ==================== 转义锁（动态文本一把锁，属性位/文本位同规） ====================


def test_component_escapes_all_dynamic_slots() -> None:
    evil = '"><script>alert(1)</script>'
    escaped = _html.escape(evil)
    html = brand_capsule_html(
        bot_name=evil, bot_name_en=evil, avatar_url=evil, feature_label=evil
    )
    assert "<script>alert(1)</script>" not in html
    assert f'src="{escaped}"' in html, "头像 URL 必须按属性位转义（防逃逸）"
    assert f'>{escaped}<' in html, "文本位与属性位同一把锁"
    assert "&quot;" in html


def test_component_extra_class_is_layout_only() -> None:
    html = brand_capsule_html(bot_name=PROBE_CN, extra_class="host-margin")
    assert html.startswith('<div class="mica-capsule host-margin">')
    assert html.count(CAPSULE_OPEN) == 0, "摆位附加类不改组件基础形态"
    assert html.count(NAME_MARK) == 1


# ==================== CSS 单一产出 ====================


def test_capsule_css_single_source_and_class_family() -> None:
    assert BRAND_CAPSULE_CSS == brand_capsule_css(), "CSS 必须单一产出（常量=函数）"
    for selector in (
        ".mica-capsule {",
        ".mica-capsule .mc-avatar {",
        ".mica-capsule .mc-dot {",
        ".mica-capsule .mc-name {",
        ".mica-capsule .mc-en {",
        ".mica-capsule .mc-feature {",
    ):
        assert selector in BRAND_CAPSULE_CSS, f"组件 CSS 缺成员规则 {selector}"


# ==================== 桥：_capsule_context 只转发不手写 ====================


def test_capsule_context_delegates_to_component() -> None:
    ctx = bridge._capsule_context(PROBE_CN, PROBE_AVATAR, PROBE_FEATURE)
    assert ctx["capsule_css"] == BRAND_CAPSULE_CSS
    assert ctx["capsule_html"] == brand_capsule_html(
        bot_name=PROBE_CN, avatar_url=PROBE_AVATAR, feature_label=PROBE_FEATURE
    )


def test_capsule_context_empty_inputs_keep_all_legs() -> None:
    ctx = bridge._capsule_context("", "", "")
    html = ctx["capsule_html"]
    assert html and html.count(CAPSULE_OPEN) == 1
    assert DOT_MARK in html and AVATAR_MARK not in html
    assert FEATURE_MARK not in html, "桥侧空功能名同样整段省略"


def test_capsule_context_does_not_hardcode_brand_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_brand(monkeypatch, display_name=PROBE_CN, name_en=PROBE_EN)
    ctx = bridge._capsule_context("", "", "")
    assert PROBE_CN in ctx["capsule_html"]
    assert PROBE_EN in ctx["capsule_html"]
    assert "守岸人" not in ctx["capsule_html"]
    assert "Shorekeeper" not in ctx["capsule_html"]


# ==================== 面级：7 张卡各自恰好一枚胶囊（杀 M1） ====================


@pytest.mark.parametrize("face", FACES)
def test_face_has_exactly_one_capsule(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, monkeypatch=monkeypatch)
    assert html.count(CAPSULE_OPEN) == 1, (
        f"{face} 卡面胶囊必须恰好一枚（多=重复注入，零=被删）"
    )
    assert html.count(NAME_MARK) == 1 and html.count(EN_MARK) == 1
    assert html.count(DOT_MARK) + html.count(AVATAR_MARK) == 1


@pytest.mark.parametrize("face", FACES)
def test_face_injects_capsule_css_exactly_once(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, monkeypatch=monkeypatch)
    assert html.count(BRAND_CAPSULE_CSS) == 1, f"{face} 组件 CSS 应随卡恰好注入一次"


@pytest.mark.parametrize("face", FACES)
def test_face_capsule_dom_equals_component_output(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产物里的胶囊逐字节 == 组件对**同一显式输入**的产出（模板/桥不许另抄 DOM）。

    输入全部显式传入（不依赖各面功能名缺省值——那属评审 I-4 在飞收编面）。
    """
    if face == "mermaid":
        # mermaid 无 payload 通道，功能名由桥侧常量给；本锁只校名字+两腿，
        # 功能名段单列在 test_face_feature_segment_when_present_is_wellformed。
        html = _render_face(face, avatar_url=PROBE_AVATAR, monkeypatch=monkeypatch)
        expected = brand_capsule_html(
            bot_name=BRAND_THEME.display_name, avatar_url=PROBE_AVATAR
        )
        # 功能名段由桥侧追加在闭合 </div> 之前 → 去尾比较，锁不依赖缺省字符串。
        expected = expected[: -len("</div>")]
    else:
        html = _render_face(
            face,
            bot_name=PROBE_CN,
            avatar_url=PROBE_AVATAR,
            feature_label=PROBE_FEATURE,
            monkeypatch=monkeypatch,
        )
        expected = brand_capsule_html(
            bot_name=PROBE_CN, avatar_url=PROBE_AVATAR, feature_label=PROBE_FEATURE
        )
    assert expected != "", "组件产出为空=胶囊整枚消失（M1），面级一致性断言失去意义"
    assert expected in html, f"{face} 产物胶囊与组件产出不一致"


@pytest.mark.parametrize("face", FACES)
def test_face_empty_payload_never_raise_keeps_capsule(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, monkeypatch=monkeypatch)
    assert html.strip() and CAPSULE_OPEN in html


# ==================== 面级：两腿随载荷切换（杀 M3 / M1） ====================


@pytest.mark.parametrize("face", FACES)
def test_face_avatar_leg_when_url_present(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, avatar_url=PROBE_AVATAR, monkeypatch=monkeypatch)
    assert f'<img {AVATAR_MARK} src="{PROBE_AVATAR}"' in html, (
        f"{face}：有头像载荷必须出 img 腿（M3=砍头像腿探针）"
    )
    assert DOT_MARK not in html


@pytest.mark.parametrize("face", FACES)
def test_face_dot_leg_when_avatar_absent(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, avatar_url="", monkeypatch=monkeypatch)
    assert DOT_MARK in html and AVATAR_MARK not in html


# ==================== 面级：名字/功能名单一来源与摆位纪律 ====================


@pytest.mark.parametrize("face", FACES)
def test_face_names_follow_single_source_tokens(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中文名读 BRAND_THEME.display_name、英文名读 BRAND_NAME_EN：
    两枚 token 换哨兵，产物必须整体跟随，旧值必须整页消失。

    universal 一列原以 xfail(strict) 挂账（评审 I-3：``models.py:150`` 硬默认
    「守岸人」经 ``_DEFAULT_CONTEXT`` 恒注入）；本席在飞期间 CAPFIX-B 席把
    默认值改为留空回落（工作树实况），故并入正向锁——若该修复被回退，
    本锁对 universal 变红即如实报警。
    """
    _patch_brand(monkeypatch, display_name=PROBE_CN, name_en=PROBE_EN)
    html = _render_face(face, monkeypatch=monkeypatch)
    assert f'<span {NAME_MARK}>{PROBE_CN}</span>' in html, f"{face} 中文名未读单一来源"
    assert f'<span {EN_MARK}>{PROBE_EN}</span>' in html, (
        f"{face} 英文名未读 BRAND_NAME_EN（M2 探针）"
    )
    assert "守岸人" not in html and "Shorekeeper" not in html, (
        f"{face} 出现写死的第二处品牌名（或模板另有署名副本）"
    )
    assert html.count(PROBE_EN) == 1, f"{face} 英文名应只在胶囊出现一次"


@pytest.mark.parametrize("face", FACES)
def test_face_english_name_appears_exactly_once(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(face, monkeypatch=monkeypatch)
    assert html.count(BRAND_NAME_EN) == 1, (
        f"{face} Shorekeeper 出现 {html.count(BRAND_NAME_EN)} 次（应恰 1=胶囊内）"
    )


@pytest.mark.parametrize("face", FACES)
def test_face_feature_segment_omitted_or_wellformed(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """态④面级锁（版本无关）：空载荷出卡时，功能名段要么整段不存在，
    要么必须是「· 非空文本」——绝不允许空段/裸「·」占位上卡。"""
    html = _render_face(face, monkeypatch=monkeypatch)
    if FEATURE_MARK not in html:
        assert "· </" not in html and "·</" not in html, f"{face} 残留裸分隔点占位"
        return
    assert re.search(
        r'<span class="mc-feature">· [^<]+</span>', html
    ), f"{face} 功能名段形态违约（空段或占位）"


def test_universal_face_empty_payload_omits_feature_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """universal 无能力语境 → 空载荷下 mc-feature 段必须整段不产（态④硬实例）。"""
    html = _render_face("universal", monkeypatch=monkeypatch)
    assert FEATURE_MARK not in html
    assert "·" not in html[html.index(CAPSULE_OPEN):][:200]


@pytest.mark.parametrize("face", [f for f in FACES if f != "mermaid"])
def test_face_explicit_inputs_take_effect(
    face: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _render_face(
        face,
        bot_name=PROBE_CN,
        avatar_url=PROBE_AVATAR,
        feature_label=PROBE_FEATURE,
        monkeypatch=monkeypatch,
    )
    expected = brand_capsule_html(
        bot_name=PROBE_CN, avatar_url=PROBE_AVATAR, feature_label=PROBE_FEATURE
    )
    assert expected in html, f"{face} 显式载荷未原样进胶囊"
