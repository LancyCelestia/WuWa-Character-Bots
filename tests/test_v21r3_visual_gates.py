"""v21r3 渲染统一「机器门」补课（TDD RED 锚点，2026-09-18）。

对全部 **11 个渲染面** 逐面编码裁决基线（v21r3 渲染统一裁决）九门：

  面 = 7 张 Jinja 模板（domains/render/card_render/templates/*.html，读源文件
       全分支文本）+ 4 张直拼卡（import 构建函数取最终 HTML，离线零渲染）：
       echo_help（domains/chat_reply/capabilities/echo.py::_help_mica_html）、
       debug_llm（domains/ops/admin/debug.py::_llm_setup_mica_html）、
       usage_report（domains/render/card_render/usage_cards.py）、
       media_card（domains/render/templates.py）。

  门（断言消息一律标注「裁决基线第 X 条」）：
    第1条 border-radius：外壳只允许 var(--r-shell)；内径字面量 ⊆ {4,6,8,12,16}
         + pill 999px + 圆 50%（0/inherit/var() 复位或 token 引用放行）；
         禁私设 --radius-lg/md/sm 圆角 token（并入 --r-shell/--r-panel/--r-tile）。
    第2条 色斑恒 3 枚、动画时长集合恰 {46,52,58}s。
    第4条 行高全集 ⊆ {1.0,1.1,1.15,1.2,1.4,1.5,1.6}。
    第5条 字号 ≥ 12px。
    第6条 gap ∈ GAP_SCALE_PX（theme_tokens 审计刻度）。
    第7条 外壳宽度 ∈ theme_tokens.CARD_SHELL_WIDTHS 登记表（运行时动态读表：
         CORE 席并行新增 help/usage/debug/media 宽度后自动转绿，无需改本文件）。
    第8条 font-family 字面量只允许 FONT_FAMILY_STACK / MONO_FONT_STACK 逐字一致
         （var() token 消费放行；MONO_FONT_STACK 尚未登记时按缺失记红）。
    第9条 禁表外 hex（黑名单制，豁免白名单见 _HEX_WHITELIST，做法参照
         test_template_visual_audit 既有豁免注释）。

  TDD 锚点：本文件**预期 RED**——生产文件由 wave-2 席修复，本席禁改生产代码；
  个别门因并行席位已落地而直接 GREEN 属正常，如实记录于 progress-GATES.md。
  （裁决基线第 3 条「玻璃两档」原归 token/视觉席契约；GLASS2 席已以门 9 补设，
  见 test_gate09_glass_tiers——白玻璃填充两档 + 描边三档，11 面生效。）
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.debug import _llm_setup_mica_html
from plugins.bot_unified_runtime.capabilities.echo import _help_mica_html
from plugins.bot_unified_runtime.domains.render.card_render import (
    bridge,
    mica_shell,
    theme_tokens,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    CARD_SHELL_WIDTHS,
    FONT_FAMILY_STACK,
    GAP_SCALE_PX,
)
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import (
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.output.templates import render_media_card_html

# MONO_FONT_STACK 由 wave-2 席登记进 theme_tokens；缺席=尚无合法 mono 字面量。
MONO_FONT_STACK: str | None = getattr(theme_tokens, "MONO_FONT_STACK", None)

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# ==================== 11 面（7 模板 + 4 直拼卡） ====================
_TEMPLATE_SURFACES: dict[str, str] = {
    # 面 id → 模板文件名（与 test_rendering_contract / test_e03 显式枚举同口径）
    "universal": "universal_card.html",
    "market": "market_card.html",
    "affinity": "affinity_card.html",
    "mermaid": "mermaid_card.html",
    "song": "song_candidates.html",
    "finance": "finance_card.html",
    "error": "error_card.html",
}
_BUILTIN_SURFACES: tuple[str, ...] = (
    "echo_help",
    "debug_llm",
    "usage_report",
    "media_card",
)
ALL_SURFACES: tuple[str, ...] = (*_TEMPLATE_SURFACES, *_BUILTIN_SURFACES)


class _HelpColorStubConfig:
    """debug/usage builder 只读 bot_help_card_color 一个属性。"""

    bot_help_card_color = ""


def _universal_payload(i: int) -> dict[str, Any]:
    return {
        "platform": "bilibili",
        "item_id": f"BV1xx{i}",
        "title": f"视频{i}",
        "summary": f"正文{i}",
        "stats": {"views": 1000 + i},
    }


def _market_payload(i: int) -> dict[str, Any]:
    return {
        "subtitle": f"全球股指{i}",
        "groups": [
            {
                "name": "美股",
                "rows": [
                    {"name": "标普500", "price": str(5000 + i), "pct": "+0.5%",
                     "trend": [1.0, 2.0, 3.0, float(i)]},
                ],
            },
        ],
        "updated_at": "2026-09-13 08:00:00",
    }


def _finance_payload(i: int) -> dict[str, Any]:
    return {
        "title": f"金融速览{i}",
        "sections": [
            {"name": "巨头", "rows": [{"label": "NVDA", "value": str(100 + i)}]},
        ],
    }


def _song_payload(i: int) -> dict[str, Any]:
    return {
        "query": f"关键词{i}",
        "platform": "netease_music",
        "candidates": [{"index": 1, "name": f"歌曲{i}", "artist": "歌手"}],
    }


def _affinity_payload(i: int) -> dict[str, Any]:
    return {
        "mode": "private",
        "bot_to_user": {"score": float(i), "tier": "友善", "bar": float(i)},
    }


def _error_payload(i: int) -> dict[str, Any]:
    return {
        "human_text": f"能力执行遇到异常，已留档{i}",
        "exc_type": f"RuntimeError{i}",
        "exc_message": f"模拟异常{i}",
        "trigger_echo": f"/bot status {i}",
        "help_text": "稍后再试",
    }


def _build_builtin(sid: str) -> str:
    """四张直拼卡：import 构建函数直接取最终 HTML（离线零渲染）。"""
    if sid == "echo_help":
        return _help_mica_html(
            "测试正文",
            is_admin=False,
            sections=[("测试模块", [("/bot help", "测试说明")])],
        )
    if sid == "debug_llm":
        payload: dict[str, Any] = {
            "config": _HelpColorStubConfig(),
            "status_label": "检查完成",
            "status_kind": "ok",
            "message": "全部通过",
            "rows": [
                {
                    "key": "BOT_CHAT_PROVIDER",
                    "desc": "模型供应商",
                    "range": "openai 兼容",
                    "value": "axonhub",
                    "ok": "1",
                },
            ],
            "next_step": "无",
        }
        return _llm_setup_mica_html(payload)
    if sid == "usage_report":
        return usage_report_mica_html(
            _HelpColorStubConfig(),
            kicker="测试 · 模型用量",
            title="模型用量账单报告",
            status_label="账单 0.00 元",
            status_kind="ok",
            window_label="09-18 00:00 至 09-18 23:59",
            generated_at="2026-09-18 23:59:00",
            totals={
                "prompt_tokens": 100,
                "cache_read_tokens": 10,
                "cache_write_tokens": 20,
                "completion_tokens": 30,
                "total_tokens": 160,
                "calls": 3,
                "cost_text": "0.00",
                "unpriced_calls": 0,
            },
            model_rows=[
                {
                    "model": "model-alpha",
                    "prompt": 100,
                    "cache_read": 10,
                    "cache_write": 20,
                    "completion": 30,
                    "cost_text": "0.00",
                    "priced": True,
                }
            ],
        )
    if sid == "media_card":
        return render_media_card_html(
            {
                "title": "测试标题",
                "platform": "bilibili",
                "author": "UP 主",
                "stats": {"播放": "1 万"},
                "summary": "测试摘要",
                "footer": "https://example.invalid/watch/1",
                "bot_name": "守岸人",
                "feature_label": "解析",
            }
        )
    raise AssertionError(f"未知直拼卡面: {sid}")


def _build_template(sid: str) -> str:
    """七张 Jinja 模板：走 bridge 渲染入口取最终 HTML（宽度门消费注入值）。"""
    if sid == "universal":
        return bridge.render_universal_card_html(_universal_payload(1))
    if sid == "market":
        return bridge.render_market_card_html(_market_payload(1))
    if sid == "finance":
        return bridge.render_finance_card_html(_finance_payload(1))
    if sid == "song":
        return bridge.render_song_candidates_html(_song_payload(1))
    if sid == "affinity":
        return bridge.render_affinity_card_html(_affinity_payload(1))
    if sid == "mermaid":
        return bridge.render_mermaid_html("graph TD; A1-->B1")
    if sid == "error":
        return bridge.render_error_card_html(_error_payload(1))
    raise AssertionError(f"未知模板面: {sid}")


def _strip_comments(text: str) -> str:
    """Jinja/HTML/CSS 注释全剥——注释里允许出现任意字样。"""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


@cache
def _surface_texts(sid: str) -> tuple[str, ...]:
    """面扫描语料：模板 =（剥注释源文件全分支文本, 渲染后 HTML）；直拼卡 = 渲染 HTML。"""
    if sid in _TEMPLATE_SURFACES:
        raw = (_TEMPLATES_DIR / _TEMPLATE_SURFACES[sid]).read_text(encoding="utf-8")
        return (_strip_comments(raw), _strip_comments(_build_template(sid)))
    return (_strip_comments(_build_builtin(sid)),)


# ==================== 门 1：border-radius 字面量登记制 ====================
# 裁决基线第 1 条：外壳圆角只允许 var(--r-shell)(30)；内径合法集
# {4,6,8,12,16} + pill 999px + 圆 50%；0/inherit 复位与 var() token 消费放行。
_RADIUS_INNER_PX = {4, 6, 8, 12, 16, 999}
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;{}]+)")
_SHELL_RADIUS_RE = re.compile(r"border-radius\s*:\s*var\(--r-shell\)")
# 私设圆角 token（universal 遗留）：一律并入 --r-shell/--r-panel/--r-tile 三 token。
_PRIVATE_RADIUS_TOKEN_RE = re.compile(r"--radius-(?:lg|md|sm)\s*:")


def _radius_literal_violations(value: str) -> list[str]:
    text = value.strip()
    if not text or "var(" in text or text in {"inherit", "0"}:
        return []
    bad: list[str] = []
    for token in text.split():
        if token == "50%":
            continue
        if token.endswith("%"):
            bad.append(token)
        elif token.endswith("px"):
            try:
                number = float(token[:-2])
            except ValueError:
                bad.append(token)
                continue
            if number not in _RADIUS_INNER_PX:
                bad.append(token)
        else:
            bad.append(token)
    return bad


# ==================== 门 2：色斑三枚 + 时长 {46,52,58}s ====================
_DRIFT_ANIM_RE = re.compile(r"animation\s*:\s*mica-drift-([\w-]+)\s+([0-9.]+)s")
_BLOB_KEYFRAMES = {"a", "b", "c"}
_BLOB_DURATIONS_S = {46.0, 52.0, 58.0}


# ==================== 门 4：行高统一刻度 ====================
_LINE_HEIGHT_SCALE = {1.0, 1.1, 1.15, 1.2, 1.4, 1.5, 1.6}
_LINE_HEIGHT_RE = re.compile(r"line-height\s*:\s*([0-9.]+)\s*[;}]?")


# ==================== 门 6：gap 审计刻度 ====================
_GAP_RE = re.compile(r"\bgap\s*:\s*(\d+)px")


# ==================== 门 7：外壳宽度登记表（动态读 CARD_SHELL_WIDTHS） ==========
# 只扫壳尺度宽度（≥500px）：图标/胶囊等内部元素宽度不属外壳登记范畴。
# @media 块整体跳过（协调裁定 2026-09-18）：块内断点条件（max-width:559px/720px）
# 与响应式覆盖均为媒体查询语境，不是壳宽登记对象；宽度断言只认
# CARD_SHELL_WIDTHS 登记值（动态读表）。
_WIDTH_FLOOR_PX = 500.0
_WIDTH_RE = re.compile(r"(?<![-\w])(?:max-width|width)\s*:\s*(\d+(?:\.\d+)?)px")


def _strip_media_blocks(text: str) -> str:
    """整体剥离 @media …{ … } 块（花括号配平；Jinja {{ }} 成对出现不破坏配平）。"""
    out: list[str] = []
    index = 0
    while True:
        start = text.find("@media", index)
        if start == -1:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:start])
        open_brace = text.find("{", start)
        if open_brace == -1:
            return "".join(out)
        depth = 1
        cursor = open_brace + 1
        while cursor < len(text) and depth:
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
            cursor += 1
        index = cursor


# ==================== 门 8：font-family 两栈逐字制 ====================
# 值捕获含引号（mermaid JS 的 fontFamily: "..." 无分号，靠行尾截断）。
_FONT_FAMILY_RE = re.compile(
    r"(?:(?<![\w-])font-family|--font-family|--mono-family|fontFamily)"
    r"\s*:\s*([^;{}\n]+)"
)


def _norm_font_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('"', "").replace("'", "")).strip()


_ALLOWED_FONT_LITERALS = {_norm_font_value(FONT_FAMILY_STACK)}
if MONO_FONT_STACK is not None:
    _ALLOWED_FONT_LITERALS.add(_norm_font_value(MONO_FONT_STACK))


# ==================== 门 9：禁表外 hex（黑名单 + 登记表正门） ====================
# 黑名单=裁决基线点名的 legacy/旧状态散值。白名单机制（test_template_visual_audit
# 既有先例）=「登记表即正门」：值一旦登记进 theme_tokens 常量（SCORE_HOT/
# SCORE_COLD/SEMANTIC_* 等语义色单一来源）即为表内，动态派生豁免；未登记值
# （旧 #d64545/#1a9e6c、legacy 灰 #555/#444/#999）在面文本内一律记红，wave-2
# 须改为消费 theme_tokens 常量 / var(--token)，禁直写散值。
_FORBIDDEN_HEX: dict[str, str] = {
    "#d64545": "旧状态红散值（theme_tokens 登记值为 SEMANTIC_DANGER=#d54941）",
    "#1a9e6c": "旧状态绿散值（theme_tokens 登记值为 SEMANTIC_SUCCESS=#2e9e6b）",
    "#b07d1a": "旧状态琥珀散值",
    "#b42334": "旧红散值",
    "#157347": "旧绿散值",
    "#555": "legacy 中灰",
    "#444": "legacy 深灰",
    "#999": "legacy 浅灰",
}
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


def _norm_hex(raw: str) -> str:
    text = raw.lower()
    body = text[1:]
    if len(body) == 3:  # 3 位缩写展开
        body = "".join(ch * 2 for ch in body)
    return "#" + body[:6]


def _theme_registered_hexes() -> frozenset[str]:
    """token 登记模块（theme_tokens + mica_shell）公开常量里登记过的全部 hex。

    白名单=登记值集合动态派生（协调裁定 2026-09-18，与阴影门同思路）：
    render_root_tokens 经 --semantic-*/--score-hot/--score-cold 注入的 registry
    hex（#d54941/#2e9e6b/#b07d1a/#157347/#b42334）一律豁免；扫描覆盖 str 与
    dict/tuple/list/set 容器，登记结构重组不破门。旧散值（#d64545/#1a9e6c、
    #555/#444/#999）不在册，面上直写仍记红。
    """
    registered: set[str] = set()
    modules = (theme_tokens, mica_shell)
    for module in modules:
        for name in dir(module):
            if name.startswith("_"):
                continue
            value = getattr(module, name)
            if isinstance(value, str):
                candidates: tuple[Any, ...] = (value,)
            elif isinstance(value, dict):
                candidates = tuple(value.values())
            elif isinstance(value, (tuple, list, set, frozenset)):
                candidates = tuple(value)
            else:
                candidates = ()
            for candidate in candidates:
                if isinstance(candidate, str) and re.fullmatch(
                    r"#[0-9a-fA-F]{3,8}", candidate
                ):
                    registered.add(_norm_hex(candidate))
    return frozenset(registered)


_REGISTRY_HEXES = _theme_registered_hexes()


# ==================== 八门 × 11 面 ====================
@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate01_border_radius_registry(sid: str) -> None:
    """裁决基线第 1 条：圆角字面量登记制 + 外壳 var(--r-shell) + 禁私设 token。"""
    texts = _surface_texts(sid)
    literal_bad: list[str] = []
    for text in texts:
        for match in _RADIUS_RE.finditer(text):
            literal_bad.extend(
                f"{match.group(1).strip()!r} → {tok}"
                for tok in _radius_literal_violations(match.group(1))
            )
    assert not literal_bad, (
        f"[{sid}] 裁决基线第1条：border-radius 字面量出表 "
        f"(合法内径={sorted(_RADIUS_INNER_PX)}+999px pill+50% 圆): {literal_bad}"
    )
    shell_hits = sum(
        len(_SHELL_RADIUS_RE.findall(text)) for text in texts
    )
    assert shell_hits >= 1, (
        f"[{sid}] 裁决基线第1条：外壳圆角必须消费 var(--r-shell)，未找到声明"
    )
    private = [m.group(0) for text in texts for m in _PRIVATE_RADIUS_TOKEN_RE.finditer(text)]
    assert not private, (
        f"[{sid}] 裁决基线第1条：私设圆角 token 出表 {sorted(set(private))}"
        "（须并入 --r-shell/--r-panel/--r-tile 单一来源）"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate02_drift_blob_triad(sid: str) -> None:
    """裁决基线第 2 条：色斑恒 3 枚（a/b/c 三相），动画时长集合恰 {46,52,58}s。"""
    matches = [
        (name, float(dur))
        for text in _surface_texts(sid)
        for name, dur in _DRIFT_ANIM_RE.findall(text)
    ]
    names = {name for name, _ in matches}
    durations = {dur for _, dur in matches}
    assert names == _BLOB_KEYFRAMES, (
        f"[{sid}] 裁决基线第2条：色斑数量={len(names)}/3（相 {sorted(names)}≠"
        f"{sorted(_BLOB_KEYFRAMES)}）——缺位面须补齐三枚漂移色斑"
    )
    assert durations == _BLOB_DURATIONS_S, (
        f"[{sid}] 裁决基线第2条：色斑时长集合 {sorted(durations)}≠"
        f"{sorted(_BLOB_DURATIONS_S)}s（46/52/58 三档缺一不可）"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate03_line_height_scale(sid: str) -> None:
    """裁决基线第 4 条：行高全集 ⊆ 统一刻度 {1.0,1.1,1.15,1.2,1.4,1.5,1.6}。"""
    off_scale = sorted(
        {
            float(v)
            for text in _surface_texts(sid)
            for v in _LINE_HEIGHT_RE.findall(text)
            if float(v) not in _LINE_HEIGHT_SCALE
        }
    )
    assert not off_scale, (
        f"[{sid}] 裁决基线第4条：line-height 脱离统一刻度 "
        f"{sorted(_LINE_HEIGHT_SCALE)}: {off_scale}"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate04_font_size_floor(sid: str) -> None:
    """裁决基线第 5 条：字号 ≥ 12px（AGENTS.md UI 铁律）。"""
    below = sorted(
        {
            float(v)
            for text in _surface_texts(sid)
            for v in re.findall(r"font-size\s*:\s*([\d.]+)px", text)
            if float(v) < 12
        }
    )
    assert not below, f"[{sid}] 裁决基线第5条：字号低于 12px 下限: {below}"


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate05_gap_scale(sid: str) -> None:
    """裁决基线第 6 条：gap ∈ theme_tokens.GAP_SCALE_PX 审计刻度。"""
    bad = sorted(
        {
            int(v)
            for text in _surface_texts(sid)
            for v in _GAP_RE.findall(text)
            if int(v) not in GAP_SCALE_PX
        }
    )
    assert not bad, (
        f"[{sid}] 裁决基线第6条：间距 {bad}px 不在审计 gap 刻度 "
        f"{sorted(GAP_SCALE_PX)} 内"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate06_shell_width_registry(sid: str) -> None:
    """裁决基线第 7 条：外壳宽度 ∈ CARD_SHELL_WIDTHS（运行时动态读登记表）。"""
    widths = sorted(
        {
            float(v)
            for text in _surface_texts(sid)
            for v in _WIDTH_RE.findall(_strip_media_blocks(text))
            if float(v) >= _WIDTH_FLOOR_PX
        }
    )
    registered = sorted({float(v) for v in CARD_SHELL_WIDTHS.values()})
    off_table = [w for w in widths if w not in registered]
    assert not off_table, (
        f"[{sid}] 裁决基线第7条：外壳宽度 {off_table}px 不在 "
        f"CARD_SHELL_WIDTHS 登记表（当前登记 {registered}）——"
        "须改用登记值或在登记表新增条目"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate07_font_family_stacks(sid: str) -> None:
    """裁决基线第 8 条：font-family 字面量 ⊆ {FONT_FAMILY_STACK, MONO_FONT_STACK}
    逐字一致（var() token 消费放行）。"""
    offenders: list[str] = []
    for text in _surface_texts(sid):
        for match in _FONT_FAMILY_RE.finditer(text):
            raw = match.group(1).strip()
            if raw.startswith("var("):
                continue
            if _norm_font_value(raw) not in _ALLOWED_FONT_LITERALS:
                offenders.append(raw)
    mono_note = (
        "/MONO_FONT_STACK"
        if MONO_FONT_STACK is not None
        else "；MONO_FONT_STACK 尚未在 theme_tokens 登记，等宽字面量一律出表"
    )
    assert not offenders, (
        f"[{sid}] 裁决基线第8条：font-family 字面量出两栈白名单: {sorted(set(offenders))}"
        f"（允许=FONT_FAMILY_STACK{mono_note}）"
    )


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate08_forbidden_hex(sid: str) -> None:
    """裁决基线第 9 条：禁表外 hex（黑名单 + theme_tokens 登记表正门豁免）。"""
    hits: list[str] = []
    for text in _surface_texts(sid):
        for raw in _HEX_RE.findall(text):
            normalized = _norm_hex(raw)
            reason = _FORBIDDEN_HEX.get(normalized)
            if reason and normalized not in _REGISTRY_HEXES:
                hits.append(f"{raw}({reason})")
    assert not hits, (
        f"[{sid}] 裁决基线第9条：表外 hex 黑名单命中: {sorted(set(hits))}"
        "（豁免唯一途径=在 theme_tokens 登记为语义色常量，禁面上直写散值）"
    )


# ==================== 门 9：白玻璃档位（裁决基线第 3 条，GLASS2 席追加） ====================
# 两档填充 + 三档描边（theme_tokens GLASS_MAIN/GLASS_FOOT/GLASS_EDGE 登记值的
# alpha 面）：padding-box 填充渐变首尾 alpha 只允许 (0.66,0.44)=主档 /
# (0.66,0.46)=页脚档；border-box 描边 alpha ⊆ {0.95,0.35,0.72}=canonical 边缘三档。
# 判层规则——只认「白玻璃层」：linear-gradient 顶层色标全部为 rgba(255,255,255,a)
# 的纯白层；含 color-mix()/var() 色标的染色层（双色交融 .mica-surface、
# --surface-* 瓦片、.footer-colored 变体、徽章 tint 填充）属 token/语义治理家族，
# 不在本门两档范畴；var(--mica-glass-*) token 消费同此理放行（登记表即正门，
# 值归 theme_tokens 单一来源）。attach 前非 linear-gradient（如 var(--surface-a)
# padding-box）不构成白玻璃层。括号配平回溯兼容单行紧凑与 .glass 多行两种写法。
# 【裁定登记（GLASS3 席 2026-09-19，主会话裁定）】.footer-colored（universal_card
# 染色页脚变体）的 border-box 描边白 alpha 0.98/0.88 = sanctioned 变体：染色描边
# 语义（color-mix 交融色标），保留现值不强行归一 EDGE 三档；本门按染色层放行属
# 预期行为，非漂移——未来改动请勿把该两值「修正」进 {0.95,0.35,0.72}。
_GLASS_FILL_TIERS: tuple[tuple[float, float], ...] = ((0.66, 0.44), (0.66, 0.46))
_GLASS_EDGE_ALPHAS = frozenset({0.95, 0.35, 0.72})
_WHITE_RGBA_RE = re.compile(
    r"^rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*([0-9.]+)\s*\)(?:\s+[\d.]+%?)?$"
)
_TINTED_STOP_RE = re.compile(r"color-mix\(|var\(")
_GLASS_ATTACH_RE = re.compile(r"(padding-box|border-box)\b")
# 渐变方向参数（150deg / to bottom right 等）不是色标。
_GRADIENT_DIRECTION_RE = re.compile(
    r"(?:to\s+\w+(?:\s+\w+)?|[-\d.]+\s*(?:deg|turn|rad|grad))"
)


def _top_level_stops(body: str) -> list[str]:
    """按顶层逗号切渐变体（括号内逗号不切）。"""
    stops: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            stops.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        stops.append(tail)
    return stops


def _attached_white_glass_layers(text: str) -> list[tuple[str, list[float]]]:
    """(attach, 白 alpha 序列)：紧跟 padding-box/border-box 的 linear-gradient 白玻璃层。"""
    layers: list[tuple[str, list[float]]] = []
    for match in _GLASS_ATTACH_RE.finditer(text):
        cursor = match.start() - 1
        while cursor >= 0 and text[cursor] in " \t\r\n":
            cursor -= 1
        if cursor < 0 or text[cursor] != ")":
            continue  # attach 前不是渐变（box-sizing: border-box / var(--surface-a) 等）
        depth = 0
        opener = cursor
        while opener >= 0:
            if text[opener] == ")":
                depth += 1
            elif text[opener] == "(":
                depth -= 1
                if depth == 0:
                    break
            opener -= 1
        if opener < 0 or not text[max(0, opener - 15):opener].endswith("linear-gradient"):
            continue
        stops = _top_level_stops(text[opener + 1:cursor])
        if any(_TINTED_STOP_RE.search(stop) for stop in stops):
            continue  # 染色层：token/语义治理家族，非白玻璃两档范畴
        alphas: list[float] = []
        for index, stop in enumerate(stops):
            if index == 0 and _GRADIENT_DIRECTION_RE.fullmatch(stop):
                continue  # 渐变方向参数，非色标
            white = _WHITE_RGBA_RE.match(stop)
            if white is None:
                break
            alphas.append(float(white.group(1)))
        else:
            if alphas:
                layers.append((match.group(1), alphas))
    return layers


@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_gate09_glass_tiers(sid: str) -> None:
    """裁决基线第 3 条：白玻璃填充两档 + 描边三档（GLASS_MAIN/GLASS_FOOT/GLASS_EDGE）。"""
    offenders: list[str] = []
    for text in _surface_texts(sid):
        for attach, alphas in _attached_white_glass_layers(text):
            if attach == "padding-box":
                pair = (alphas[0], alphas[-1])
                if pair not in _GLASS_FILL_TIERS:
                    offenders.append(
                        f"padding-box 填充首尾 {pair} ∉ {{(0.66,0.44), (0.66,0.46)}}"
                    )
            else:
                off = [a for a in alphas if a not in _GLASS_EDGE_ALPHAS]
                if off:
                    offenders.append(f"border-box 描边 alpha {off} ⊄ {{0.95,0.35,0.72}}")
    assert not offenders, (
        f"[{sid}] 裁决基线第3条：白玻璃档位出表: {sorted(set(offenders))}"
        "（唯一正门=theme_tokens GLASS_MAIN/GLASS_FOOT/GLASS_EDGE 登记值）"
    )
