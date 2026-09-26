"""诊断卡两栏键值行的「各自对齐」回归（goal-7 第 7 项，S-T-VISUAL-2 席，全离线）。

判据按她的验收原话钉死：「信息太多可用两栏布局，属性名、属性值必须各自对齐」。
四件缺一不可，缺任何一件两栏就是摆设：
- kv_section 宏 compact 分支（DOM 侧 ``.section.compact`` 与长值 ``.row.wide``）；
- ``.section.compact .grid`` 双列 CSS 消费者（宏声明了 compact，CSS 没接＝假两栏）；
- 属性名轨**全局恰一条** ``flex: 0 0 176px`` 且选择器不按列分域——两栏的
  属性名首字符才落在同一条竖直线上（旧写法双列下收 92px 轨、两套轨并排＝
  「不对齐」根因，2026-09-25 评审点名）；
- 值列唯一 ``.row .value`` 规则、无 text-align 改写＝值列同样各自成轴。
行格禁静默截断（AGENTS §45C 常驻口径）：``text-overflow`` /
``-webkit-line-clamp`` / ``white-space:nowrap`` 在 .label/.value 上零出现，
长串靠 word-break 折行完整显示——截断等于谎报。

注毒自证（test_guard_bites_on_*）：内存里剥掉双列 CSS 行 / 追加第二条列内
收轨声明，判据必须当场点名；真实文件注毒在交卷前另跑一次并还原（见席位日志）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.render.card_render import bridge

_TPL = (
    Path(__file__).resolve().parents[1]
    / "plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html"
)

_TWO_COL_CSS = ".section.compact .grid { grid-template-columns: 1fr 1fr; }"
_WIDE_CSS = ".row.wide { grid-column: 1 / -1; }"


def _tpl_text() -> str:
    return _TPL.read_text(encoding="utf-8")


def _strip_jinja_and_css_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _css_of(html_text: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html_text, re.DOTALL)
    assert match, "error_card 缺少 <style> 块"
    return match.group(1)


def _rule_bodies(css: str, selector: str) -> list[str]:
    """按选择器精确取规则体（行首锚定，避开带前缀的变体选择器）。"""
    return re.findall(
        r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", _css_of(css)
    )


def _dense_payload() -> dict[str, Any]:
    """五节 compact 全填 + 长/短值混合：短值并栏、长值整行都要被走到。"""
    return {
        "exc_type": "TimeoutError",
        "exc_message": "connect timeout after 6s",
        "method_pairs": [
            {"label": "能力", "value": "bot.weather"},
            {"label": "函数", "value": "fetch_city"},
        ],
        "config_pairs": [
            {"label": "bot_chat_failover_max_seconds", "value": "300"},
            {"label": "bot_market_retry_on_empty", "value": "true"},
            {
                "label": "bot_tts_ref_audios",
                # >20 字符＝长值，宏按长度自动 .wide 占整行。
                "value": "C:/Runtime/ref_audios/long-take-voice-reference.wav",
            },
        ],
        "version_pairs": [
            {"label": "NoneBot", "value": "2.x.y"},
            {"label": "构建", "value": "abc1234"},
        ],
        "env_pairs": [
            {"label": "平台", "value": "qq"},
            {"label": "协议", "value": "OneBot V11"},
        ],
        "id_pairs": [
            {"label": "message_id", "value": "m-9"},
            {"label": "bot_id", "value": "3958874605"},
        ],
        "self_review_pairs": [{"label": "大概原因", "value": "推测是对端回话太慢"}],
        "contact_pairs": [{"label": "管理员", "value": "QQ 10001"}],
    }


# ---------------------------------------------------------------- 活性面（真渲染）


def test_two_column_path_renders_on_real_payload() -> None:
    """宏 compact 分支 + 双列 CSS 消费者在真渲染路径上同批在场。"""
    html = bridge.render_error_card_html(_dense_payload())
    assert '<div class="section compact">' in html, "真渲染没有出现 .section.compact 节"
    assert _TWO_COL_CSS in html, "双列 CSS 消费者缺失（宏声明了 compact 但 CSS 没接）"
    assert _WIDE_CSS in html, ".row.wide 长值整行规则缺失"
    # 五节短值为主的密集节 = 双栏；自我审查/可以找两句长、保持单栏阅读节奏。
    assert html.count('<div class="section compact">') == 5, "compact 节数 ≠ 5"
    assert html.count('<div class="section">') >= 2, "非 compact 单栏节缺失"


def test_long_value_goes_wide_short_values_share_row() -> None:
    """长值行带 .wide（整行不被半格挤压），短值行不带（并栏成对）。"""
    html = bridge.render_error_card_html(_dense_payload())
    body = html.split("<body>", 1)[-1]
    long_row = re.search(r'<div class="row([^"]*)"><span class="label">'
                         r"bot_tts_ref_audios</span>", body)
    assert long_row, "长值行没渲染出来"
    assert "wide" in long_row.group(1), f"长值未整行：{long_row.group(0)}"
    short_row = re.search(r'<div class="row([^"]*)"><span class="label">平台</span>', body)
    assert short_row, "短值行没渲染出来"
    assert "wide" not in short_row.group(1), f"短值被误判整行：{short_row.group(0)}"


# ---------------------------------------------------------------- 对齐判据（核心）


def test_property_name_track_is_one_declaration_shared_by_both_columns() -> None:
    """属性名各自对齐＝全局恰一条定轨声明，且不分列作用域。

    两条轨（或列内收轨）并排时，两栏的属性名首字符落在不同竖线上——正是
    她点名要修的形态。列内覆盖选择器（``.section.compact … .label``）出现
    即判分轨。
    """
    css = _strip_jinja_and_css_comments(_tpl_text())
    assert css.count("flex: 0 0 176px") == 1, "属性名定轨声明不止一条（多轨=值不成轴）"
    tracks = _rule_bodies(css, ".row .label")
    assert len(tracks) == 1 and "flex: 0 0 176px" in tracks[0], "唯一 .row .label 轨缺失"
    assert not re.search(r"\.section\.compact[^{]*\.label", css), (
        "双列节出现列内 label 覆盖——两栏各起一条轨，属性名不再同线"
    )


def test_value_column_shares_one_alignment_declaration() -> None:
    """值列与属性名列各自成轴：唯一 ``.row .value`` 规则、无 text-align 改写。

    缺省左对齐 + 定轨标签 ⇒ 值首字符在全卡同一条竖线上；任何一处把值改
    right/center 都会当场红。
    """
    css = _strip_jinja_and_css_comments(_tpl_text())
    values = _rule_bodies(css, ".row .value")
    assert len(values) == 1, "`.row .value` 规则不止一条（值列规则分裂）"
    assert not re.search(r"text-align\s*:\s*(right|center)", values[0]), (
        f"值列被改对齐，两栏值不再同线：{values[0]}"
    )
    assert not re.search(r"\.value\s*\{[^}]*text-align\s*:\s*(right|center)", css), (
        "卡内出现任何右/中对齐的 .value 变体规则"
    )


def test_dense_rows_never_truncate_silently() -> None:
    """两栏行格禁静默截断（§45C 常驻口径）：截断＝谎报，长串一律折行。"""
    css = _strip_jinja_and_css_comments(_tpl_text())
    for selector in (".row .label", ".row .value"):
        (body,) = _rule_bodies(css, selector)
        for banned in ("text-overflow", "line-clamp", "white-space:nowrap"):
            assert banned not in body.replace(" ", ""), (
                f"{selector} 出现裁字声明 {banned}：{body}"
            )
        assert "word-break:break-all" in body.replace(" ", ""), (
            f"{selector} 缺折行手段（双列半格下长串会溢出）：{body}"
        )


def test_compact_call_sites_cover_dense_sections() -> None:
    """调用点账：宏定义外 compact=true 实参恰五处（定位/配置/版本/协议/标识）。

    少于五＝机制被架空（S-T-VISUAL-1 交割的半成品正是「宏写好没人接」）；
    多于五需逐节复核值长，不允许顺手扩挂。
    """
    src = _tpl_text()
    compact_calls = re.findall(r"\{\{\s*kv_section\(", src)
    true_calls = re.findall(r"\{\{\s*kv_section\([^)]*,\s*true\)", src)
    assert len(compact_calls) == 7, "kv_section 调用点数漂移（非七节）"
    assert len(true_calls) == 5, f"compact=true 调用点应为 5，实得 {len(true_calls)}"


# ---------------------------------------------------------------- 注毒自证


def test_guard_bites_on_poisoned_two_column_css_removal() -> None:
    """剥掉双列 CSS 行（真实交割半成品形态）→ 双列判据必须点名它。"""
    clean = _strip_jinja_and_css_comments(_tpl_text())
    poisoned = clean.replace(_TWO_COL_CSS, "")

    def _missing(text: str) -> list[str]:
        parts = []
        if "{% macro kv_section(title, pairs, compact=false)" not in text:
            parts.append("宏 compact 形参")
        if _TWO_COL_CSS not in text:
            parts.append("双列 CSS 消费者")
        if _WIDE_CSS not in text:
            parts.append("长值整行规则")
        if text.count("flex: 0 0 176px") != 1:
            parts.append("属性名单轨")
        return parts

    assert _missing(clean) == [], "干净面自证失败：判据在场面上就红（空跑判据）"
    assert _missing(poisoned) == ["双列 CSS 消费者"], "注毒未点名双列 CSS 缺失"


def test_guard_bites_on_second_track_poison() -> None:
    """追加一条列内收轨（92px 历史病灶复现）→ 单轨判据与覆盖判据都要咬住。"""
    clean = _strip_jinja_and_css_comments(_tpl_text())
    poisoned = clean + "\n.section.compact .row .label { flex: 0 0 92px; }\n"
    assert poisoned.count("flex: 0 0 176px") == clean.count("flex: 0 0 176px")
    assert re.search(r"\.section\.compact[^{]*\.label", poisoned), (
        "覆盖判据瞎了：列内收轨没被认出来"
    )
