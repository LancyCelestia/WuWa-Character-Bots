"""token 供给链常驻门（SUPPLY 席，2026-09-18 v21r3 统一收尾波）。

背景（PRECHECK 席预警）：7 张 Jinja 模板引用 50 个 ``var(--*)``（2026-09-18 当时值，
面数与变量数一律以本文件两张登记表与语料现算为准），而
mica_shell 单文件只产出 33 个定义——其余由 bridge 注入键 /
theme_tokens.theme_to_css_vars() / 各模板自有 :root / 直拼卡自带 CSS 供给。
当前供给链通但无共享锁：任一席单边增删 token，渲染面即出现未定义变量
（浏览器静默回退 = 视觉静默漂移）。本文件把该缺口变成常驻回归锁。

语料（面清单以 `_TEMPLATE_SURFACES` / `_BUILTIN_SURFACES` 现算为准，本册不抄总数；
取串方式与 test_v21r3_visual_gates 同口径）：
  - Jinja 模板全家（domains/render/card_render/templates/*.html，逐张显式登记）：
    剥注释源文件全分支文本 + bridge 渲染后 HTML 双语料；
  - 4 张直拼卡（echo_help / debug_llm / usage_report / media_card）：
    import 构建函数离线取最终 HTML（零网络零渲染后端）。

定义并集（四路供给通道）：
  S1 语料文内 ``--x:`` 定义（模板自有 :root / 直拼卡 extras /
     内联 style="--phase:…" 等全部在文形态）；
  S2 mica_shell.render_root_tokens() 产出键（直接调用解析）；
  S3 theme_tokens.theme_to_css_vars() 产出键（BRAND/ERROR/DEFAULT 三主题并集）；
  S4 bridge 注入上下文键（_VIS4_KEYS / _CORE_TOKEN_KEYS，动态 import 读取）。
     口径注明：注入键是 Jinja **值载体**，不是 CSS 变量名——落地路径只有两条：
     (a) 模板自有 ``--x:{{ key }}`` 定义（已被 S1 覆盖）；
     (b) mica_shell.render_root_tokens 公共段（已被 S2 覆盖）。
     故 S4 进硬门的形态是「逐键落地核对」：kebab 投影 ∈ 并集 ∨ 键值被某并集
     变量原值携带 ∨ 片段豁免（decor_css/blobs_html 是 CSS/DOM 片段非变量）。
     未落地键 = 注入管道漂移，记红。

门：
  S-A（逐面硬门）：每面 var() 引用集 ⊆ 定义并集；失败消息列出
    「面 → 缺失变量 → 建议供给处」。
  S-B：bridge 注入键逐键落地核对（见 S4 口径）。
  S-C：供给保证变量（--phase / --wash-* 等「由注入供给」者）必须 ∈ 并集——
    白名单只豁免「引用侧」，永不豁免「定义侧」缺失。
  S-D：templates/*.html 每一张都必须显式登记进 _TEMPLATE_SURFACES
    （未登记新模板 = 脱离供给管辖，记红；反向防登记悬空）。
  S-E：引用白名单防陈腐——白名单条目必须仍被至少一面引用（退役即清）。
  信息性反检（只 warn 不 fail）：定义并集中未被任何面 var() 消费的保留
    token，warn 打印避免误伤登记保留。

预期当前全 GREEN（供给链现通）——这是回归锁，不是 RED 锚点；若某面真缺
定义，如实报红，修复在生产侧补供给（本席禁改生产文件）。
"""

from __future__ import annotations

import re
import warnings
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
    _help_mica_html,
)
from plugins.bot_unified_runtime.domains.ops.admin.debug import _llm_setup_mica_html
from plugins.bot_unified_runtime.domains.render.card_render import (
    bridge,
    mica_shell,
    theme_tokens,
)
from plugins.bot_unified_runtime.domains.render.card_render.usage_cards import (
    usage_report_mica_html,
)
from plugins.bot_unified_runtime.output.templates import render_media_card_html

_TEMPLATES_DIR = Path(bridge.__file__).resolve().parent / "templates"

# ============ 面登记表（Jinja 模板全家 + 直拼卡；枚数以两张表现算为准） ============
# **文件名的账本住派生源** `bridge.card_template_names()`（S-T-VISUAL-1 归一，
# 与 scripts/doc_sync.py::_tpl_list 同判据）；面 id→文件名属显式登记，完备性
# 由下方 S-D 门对派生清单双向执法（新模板不登记即红）。
_TEMPLATE_SURFACES: dict[str, str] = {
    "universal": "universal_card.html",
    "market": "market_card.html",
    "affinity": "affinity_card.html",
    "mermaid": "mermaid_card.html",
    "song": "song_candidates.html",
    "finance": "finance_card.html",
    "error": "error_card.html",
    "news_digest": "news_digest_card.html",
}
_BUILTIN_SURFACES: tuple[str, ...] = (
    "echo_help",
    "debug_llm",
    "usage_report",
    "media_card",
)
ALL_SURFACES: tuple[str, ...] = (*_TEMPLATE_SURFACES, *_BUILTIN_SURFACES)


# ==================== 语料构建（离线，与 visual gates 同法） ====================
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


def _news_digest_payload(i: int) -> dict[str, Any]:
    return {
        "title": f"今日快讯{i}",
        "sub": f"来源聚合{i}",
        "foot": f"数据口径 {i}",
        "items": [
            {"source": "V2EX", "time": "09:00", "name": f"条目{i}", "snip": f"摘要{i}"},
        ],
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
    """登记的 Jinja 模板：走 bridge 渲染入口取最终 HTML（:root 注入值进入语料）。"""
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
    if sid == "news_digest":
        return bridge.render_news_digest_card_html(_news_digest_payload(1))
    raise AssertionError(f"未知模板面: {sid}")


def _strip_comments(text: str) -> str:
    """Jinja/HTML/CSS 注释全剥——注释里允许出现任意字样（mica_shell 的
    _TOKENS_COMMENT 亦刻意不带 --token: 形态，双保险）。"""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


@cache
def _surface_texts(sid: str) -> tuple[str, ...]:
    """面语料：模板 =（剥注释源文件全分支文本, 渲染后 HTML）；直拼卡 = 渲染 HTML。"""
    if sid in _TEMPLATE_SURFACES:
        raw = (_TEMPLATES_DIR / _TEMPLATE_SURFACES[sid]).read_text(encoding="utf-8")
        return (_strip_comments(raw), _strip_comments(_build_template(sid)))
    return (_strip_comments(_build_builtin(sid)),)


# ==================== 抽取器 ====================
# 引用：var(--x) 与 var(--x, fallback) 都只取 --x（fallback 不入引用集）。
_VAR_REF_RE = re.compile(r"var\(\s*(--[A-Za-z][A-Za-z0-9_-]*)")
# 定义：--x: 形态（冒号后即值）；lookbehind 防止 var(--x) 的括号内误配。
_VAR_DEF_RE = re.compile(r"(?<![\w-])(--[A-Za-z][A-Za-z0-9_-]*)\s*:")
# 定义带值（S4 落地核对用；值在 ; { } 处截断，CSS 值形态足够）。
_VAR_DEF_VALUE_RE = re.compile(
    r"(?<![\w-])(--[A-Za-z][A-Za-z0-9_-]*)\s*:\s*([^;{}]*)"
)


def _surface_refs(sid: str) -> frozenset[str]:
    return frozenset(
        name for text in _surface_texts(sid) for name in _VAR_REF_RE.findall(text)
    )


def _corpus_definitions() -> frozenset[str]:
    """S1：全部面语料文内 ``--x:`` 定义并集。"""
    return frozenset(
        name
        for sid in ALL_SURFACES
        for text in _surface_texts(sid)
        for name in _VAR_DEF_RE.findall(text)
    )


def _render_root_tokens_supply() -> dict[str, str]:
    """S2：mica_shell.render_root_tokens() 直接调用 → {变量: 值}。

    用守岸人品牌 accent 走全参通道（wash 由 theme_tokens 单一派生），解析
    其产出的 :root 块；解析失败视为供给管道断裂，测试显式报错。
    """
    accent = theme_tokens.BRAND_THEME.accent
    rendered = mica_shell.render_root_tokens(
        accent=accent,
        accent_dark=theme_tokens.BRAND_THEME.accent_dark,
        wash=theme_tokens.derive_wash_tokens(accent),
    )
    pairs = _VAR_DEF_VALUE_RE.findall(rendered)
    assert pairs, "mica_shell.render_root_tokens 产出为空/不可解析——供给管道断裂"
    return dict(pairs)


def _theme_to_css_vars_supply() -> dict[str, str]:
    """S3：theme_to_css_vars() 三主题（BRAND/ERROR/DEFAULT）并集 → {变量: 值}。"""
    supply: dict[str, str] = {}
    for theme in (theme_tokens.BRAND_THEME, theme_tokens.ERROR_THEME,
                  theme_tokens.DEFAULT_THEME):
        supply.update(theme_tokens.theme_to_css_vars(theme))
    return supply


# ==================== S4：bridge 注入键（动态读取，取不到静态兜底） ====================
# 口径：_VIS4_KEYS/_CORE_TOKEN_KEYS 是 Jinja 渲染上下文的值注入键（snake_case），
# 经模板自有 ``--x:{{ key }}`` 定义或 mica_shell 公共段落地为 CSS 变量。
# decor_css/blobs_html 是 mica_shell 生成的 CSS/DOM 片段（{{ | safe }} 整块
# 注入），不是变量载体，豁免落地核对。
_BRIDGE_FRAGMENT_KEYS: frozenset[str] = frozenset({"decor_css", "blobs_html"})


def _bridge_injected_keys() -> dict[str, str]:
    """动态读取 bridge 注入管道键值；读不到 = 管道被改名，S-B 显式报红。"""
    vis4 = getattr(bridge, "_VIS4_KEYS", None)
    core = getattr(bridge, "_CORE_TOKEN_KEYS", None)
    if vis4 is None or core is None:
        pytest.fail(
            "bridge._VIS4_KEYS/_CORE_TOKEN_KEYS 注入管道键缺席（被改名/迁移）——"
            "本门的 S4 口径需随新管道同步更新，不得静默跳过"
        )
    merged: dict[str, str] = dict(vis4)
    merged.update(core)
    return merged


def _kebab(key: str) -> str:
    return "--" + key.replace("_", "-")


@cache
def _supply_union() -> dict[str, str]:
    """定义并集（S1 ∪ S2 ∪ S3）→ {变量: 值}（值仅供 S4 落地核对）。"""
    union: dict[str, str] = dict(_render_root_tokens_supply())
    union.update(_theme_to_css_vars_supply())
    for sid in ALL_SURFACES:
        for text in _surface_texts(sid):
            for name, value in _VAR_DEF_VALUE_RE.findall(text):
                union.setdefault(name, value.strip())
    return union


def _suggest_supply(name: str) -> str:
    """失败消息第三段：缺失变量的建议供给处（按 token 家族路由）。"""
    if name.startswith(("--wash", "--phase")) or name in {
        "--accent", "--accent-dark", "--accent-rgb", "--accent-light",
    }:
        return (
            "mica_shell.render_root_tokens（phase/wash/accent 家族；"
            "wash 由 bridge._derive_wash_tokens 按 accent 派生）"
        )
    if name.startswith(("--mica-", "--semantic-", "--score-", "--r-")) or name in {
        "--text-main", "--text-sub", "--ink", "--muted",
        "--font-family", "--font-mono",
    }:
        return (
            "mica_shell._PUBLIC_TOKEN_ORDER / theme_tokens.theme_to_css_vars"
            "（CORE 值册单一登记，改一处全卡生效）"
        )
    return "面自有 :root 块（模板/直拼卡文内定义，仅该面可消费）"


# ==================== 引用白名单（浏览器原生/第三方供给） ====================
# 机制：_REFERENCE_WHITELIST 登记「允许无静态定义」的 var() 引用，每条必须
# 注明真实供给方；且 S-C 保证白名单永不豁免定义侧缺失。当前为空——
# --phase（mica_shell.render_root_tokens include_phase 注入 + drift_blobs_html
# 内联 style 通道 + var(--phase, 0.2) 防御兜底）与 --wash-1/2/3、--wash-mist、
# --wash-blob-1（bridge 按 accent 派生 → render_root_tokens 注入）已核实全部
# 在定义并集内（S-C 锁定），无需豁免；浏览器原生/第三方变量若未来出现
# （如第三方库注入的自有变量），在此登记并注明供给方。
_REFERENCE_WHITELIST: dict[str, str] = {}


# ==================== 门 S-A：逐面 引用 ⊆ 定义并集 ====================
@pytest.mark.parametrize("sid", ALL_SURFACES)
def test_sa_surface_references_fully_supplied(sid: str) -> None:
    """每面 var() 引用集 ⊆ 定义并集（S1∪S2∪S3）∪ 白名单。"""
    refs = _surface_refs(sid)
    assert refs, f"[{sid}] 语料抽取到 0 个 var() 引用——语料构建器失效，门失真"
    union = _supply_union()
    missing = sorted(refs - union.keys() - _REFERENCE_WHITELIST.keys())
    assert not missing, (
        f"[{sid}] 供给链断裂：{len(missing)} 个变量被引用但无任何供给\n"
        + "\n".join(
            f"  {sid} → {name} → 建议供给处: {_suggest_supply(name)}"
            for name in missing
        )
        + "\n（修复=在生产侧补供给（登记 token 或补 :root 定义），禁改本门凑绿）"
    )


# ==================== 门 S-B：bridge 注入键逐键落地 ====================
def test_sb_bridge_injected_keys_land() -> None:
    """每个 bridge 注入键必须有落地：kebab 投影 ∈ 并集 ∨ 键值被并集变量携带
    ∨ 片段豁免（decor_css/blobs_html）。未落地 = 注入管道漂移。"""
    union = _supply_union()
    union_values = {value for value in union.values() if value}
    unlanded: list[str] = []
    for key, value in _bridge_injected_keys().items():
        if key in _BRIDGE_FRAGMENT_KEYS:
            continue
        if _kebab(key) in union or value in union_values:
            continue
        unlanded.append(f"{key}(kebab={_kebab(key)}) 值也无并集变量携带")
    assert not unlanded, (
        f"bridge 注入键 {len(unlanded)} 个未落地（S4 口径见模块头）: {unlanded}"
    )


# ==================== 门 S-C：供给保证变量必须在定义并集内 ====================
@pytest.mark.parametrize(
    ("name", "channel"),
    [
        (
            "--phase",
            (
                "mica_shell.render_root_tokens(include_phase) + "
                "drift_blobs_html 内联 style 通道（var(--phase, 0.2) 为防御兜底）"
            ),
        ),
        ("--accent", "mica_shell.render_root_tokens / theme_to_css_vars"),
        ("--accent-dark", "mica_shell.render_root_tokens（_darken 派生）"),
        ("--wash-1", "bridge._derive_wash_tokens(accent) → render_root_tokens"),
        ("--wash-2", "bridge._derive_wash_tokens(accent) → render_root_tokens"),
        ("--wash-3", "bridge._derive_wash_tokens(accent) → render_root_tokens"),
        ("--wash-mist", "bridge._derive_wash_tokens(accent) → render_root_tokens"),
        ("--wash-blob-1", "render_root_tokens（--accent 18% color-mix 入 --wash-1）"),
    ],
)
def test_sc_injection_supplied_vars_defined(name: str, channel: str) -> None:
    """--phase/--wash-* 等「由注入供给」的变量核实 ∈ 定义并集——白名单机制
    只作用于引用侧，定义侧缺失一律红（防白名单反向掩护供给断裂）。"""
    assert name in _supply_union(), (
        f"供给保证变量 {name} 脱离定义并集（注入通道: {channel}）——"
        "注入管道回归，禁止靠加白名单掩盖"
    )


# ==================== 门 S-D：模板登记完备 ====================
def test_sd_template_registry_covers_directory() -> None:
    """派生清单每一张都必须登记进 _TEMPLATE_SURFACES（双向）。"""
    actual = set(bridge.card_template_names())  # 单一取数口，不再各自 glob
    registered = set(_TEMPLATE_SURFACES.values())
    unregistered = sorted(actual - registered)
    assert not unregistered, (
        f"模板目录存在未登记面: {unregistered}——新模板必须显式入"
        "_TEMPLATE_SURFACES 接受供给链管辖（否则渲染未定义变量无人拦截）"
    )
    dangling = sorted(registered - actual)
    assert not dangling, f"登记表指向不存在的模板文件: {dangling}"


# ==================== 门 S-E：白名单防陈腐 ====================
def test_se_whitelist_entries_still_referenced() -> None:
    """白名单条目必须仍被至少一面引用；退役即清，白名单只减不增。"""
    all_refs: set[str] = set()
    for sid in ALL_SURFACES:
        all_refs |= _surface_refs(sid)
    stale = sorted(set(_REFERENCE_WHITELIST) - all_refs)
    assert not stale, (
        f"白名单陈腐条目（已无任何面引用，须删除）: {stale}"
    )


# ==================== 信息性反检：定义未消费（只 warn 不 fail） ====================
def test_informational_definitions_unconsumed() -> None:
    """定义并集中未被任何面 var() 消费的保留 token → warn 打印（不 fail，
    避免误伤登记保留 token，如 --r-inner-* / --semantic-warning 等备用供给）。"""
    all_refs: set[str] = set()
    for sid in ALL_SURFACES:
        all_refs |= _surface_refs(sid)
    union = _supply_union()
    unconsumed = sorted(set(union) - all_refs)
    if unconsumed:
        warnings.warn(
            f"[SUPPLY 信息性反检] {len(unconsumed)} 个已定义未消费 token（保留不拦）: "
            f"{unconsumed}",
            stacklevel=2,
        )
