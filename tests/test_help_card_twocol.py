"""帮助卡 topic 目录两栏排版回归（台账 #13 残余收口，全离线）。

契约：
- 总览页（sections 路径，grid=masonry）：分区内 ``.command-list`` 走两栏
  CSS columns（栏距取 GAP_SCALE_PX 刻度），行 ``break-inside:avoid`` 防腰斩，
  72 topic 高分区（管理员/子功能 ~35 行）卡高约减半；
- <560px 窄卡媒体查询退回单栏（无 <meta viewport> 铁律不受影响）；
- 详情页（grid=single）保持单列，不受两栏规则影响；
- topic 行样式不变：药丸名（.pill）+ 一句摘要（.desc）。
"""

from __future__ import annotations

import re

from plugins.bot_unified_runtime.capabilities.echo import (
    _help_index_body,
    _help_index_sections,
    _help_mica_html,
)
from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    GAP_SCALE_PX,
)


def _index_html() -> str:
    is_admin = True
    return _help_mica_html(
        _help_index_body(page=1, is_admin=is_admin),
        is_admin=is_admin,
        sections=_help_index_sections(is_admin),
    )


def _css_of(html_text: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html_text, re.DOTALL)
    assert match, "帮助卡缺少 <style> 块"
    return match.group(1)


def test_index_fixture_is_real_directory_payload() -> None:
    """夹具必须吃真实链路数据（_help_index_sections），防测试空转。"""
    sections = _help_index_sections(is_admin=True)
    row_count = sum(len(rows) for _, rows in sections)
    assert len(sections) >= 3, f"管理员总览应至少 3 个分区，实得 {len(sections)}"
    assert row_count >= 60, f"管理员总览 topic 数异常：{row_count}"


def test_masonry_command_list_two_columns() -> None:
    css = _css_of(_index_html())
    rule = re.search(r"\.help-grid\.masonry \.command-list\s*\{([^}]*)\}", css)
    assert rule, "缺 masonry 目录两栏规则"
    body = rule.group(1)
    assert re.search(r"columns\s*:\s*2", body), f"目录未走两栏：{body}"
    gap = re.search(r"column-gap\s*:\s*(\d+)px", body)
    assert gap, f"缺栏距声明：{body}"
    assert int(gap.group(1)) in GAP_SCALE_PX, (
        f"栏距 {gap.group(1)}px 不在 GAP_SCALE_PX 刻度内"
    )


def test_masonry_rows_break_inside_avoid() -> None:
    css = _css_of(_index_html())
    assert re.search(
        r"\.help-grid\.masonry \.command-row\s*\{[^}]*break-inside\s*:\s*avoid",
        css,
    ), "topic 行缺 break-inside:avoid（两栏下会被腰斩）"


def test_masonry_desc_clamped_two_lines() -> None:
    """窄栏防溢出：目录摘要钳两行（-webkit-line-clamp），防 211px 栏宽下
    长摘要多行折叠吃掉两栏收益；详情页 desc 不受影响。"""
    css = _css_of(_index_html())
    rule = re.search(
        r"\.help-grid\.masonry \.command-row \.desc\s*\{([^}]*)\}", css
    )
    assert rule, "缺目录摘要两行钳制规则"
    body = rule.group(1)
    assert re.search(r"-webkit-line-clamp\s*:\s*2", body), body
    assert re.search(r"overflow\s*:\s*hidden", body), body
    # 基线 .command-row .desc（行首锚定，避开 .help-grid.masonry 前缀变体）不得被钳。
    base = re.search(r"(?m)^\s*\.command-row \.desc\s*\{([^}]*)\}", css)
    assert base, "缺基线 .command-row .desc 规则"
    assert "-webkit-line-clamp" not in base.group(1), "详情页基线 desc 不得被钳制"


def test_narrow_card_media_query_falls_back_single_column() -> None:
    html_text = _index_html()
    match = re.search(
        r"@media \(max-width:559px\)\s*\{(?P<body>.*?)\}\s*\}",
        html_text,
        re.DOTALL,
    )
    assert match, "缺 <560px 窄卡媒体查询"
    body = match.group("body")
    assert ".help-grid.masonry" in body, "媒体查询未覆盖外层 masonry 栏"
    assert re.search(r"column-count\s*:\s*1", body), body
    assert re.search(r"\.command-list\s*\{[^}]*columns\s*:\s*1", body), body
    # 媒体查询必须声明在基线两栏规则之后（覆盖才生效；此处校验源序）。
    base = re.search(
        r"\.help-grid\.masonry \.command-list\s*\{[^}]*columns\s*:\s*2",
        _css_of(html_text),
    )
    assert base and base.start() < match.start(), "窄卡回退必须晚于基线两栏规则"


def test_no_meta_viewport_on_real_index_payload() -> None:
    assert not re.search(r"<meta[^>]*viewport", _index_html()), (
        "违反无 <meta viewport> 铁律"
    )


def test_detail_page_stays_single_column() -> None:
    html_text = _help_mica_html(
        "点歌 · 命令手册\n【用法】点歌 歌名：点播歌曲，同名多源先出候选卡",
        is_admin=False,
    )
    assert "help-grid single" in html_text, "详情页应保持单列网格"
    assert "help-grid masonry" not in html_text, "详情页不得误入 masonry 两栏"


def test_index_rows_keep_pill_and_desc_style() -> None:
    """topic 行样式不变：药丸名 + 一句摘要。"""
    html_text = _index_html()
    grid = re.search(r'<div class="help-grid masonry">(.*)</main>', html_text, re.DOTALL)
    assert grid, "总览页缺 masonry 网格"
    rows = re.findall(r'<div class="command-row">.*?</div>', grid.group(1))
    assert len(rows) >= 60, f"目录行数异常：{len(rows)}"
    for row in (rows[0], rows[-1]):
        assert 'class="pill"' in row, f"缺药丸名：{row[:80]}"
        assert 'class="desc"' in row, f"缺一句摘要：{row[:80]}"
