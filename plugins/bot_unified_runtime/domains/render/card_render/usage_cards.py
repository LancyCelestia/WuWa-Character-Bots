"""模型用量/账单报告卡：釉瑚云母 + 液态玻璃 + 渐变漂移（mica-glass v1 2026-09-12）。

规范要点（与 parse 卡/帮助卡一致）：
- 底色/色斑用 bridge._derive_wash_tokens 按 --accent（bot_help_card_color 派生）
  生成的釉瑚洗（邻近色 pastel，工艺出处=用户裁定），经 ``--wash-*`` 消费；
  --accent 退为状态/费用等 accent，语义状态色（红绿黄）置于玻璃层之上。
- 颜色换算/加深一律消费 theme_tokens 单一来源（Task3 收尾统一：本模块不再
  持有私有 hex 助手副本，数学与旧实现逐位一致，输出零变化）。
- 液态玻璃 = 半透明白 + 1px 内高光渐变描边，无 backdrop-filter（透明截图无物可糊）。
- 三枚柔光色斑缓慢漂移（E01 二批：相位由内容 digest 钉帧，bridge.payload_phase
  单一事实源，页面零 JS）；动画元素全部在 .shell（即截图
  .card 内层）中；阴影只允许两枚 token（--mica-shadow/--mica-shadow-soft）。
- 字重最大 700；body 透明背景 + antialiased（截图 omit_background 依赖）。
- 纯 HTML+CSS+一段内联脚本，无外链字体/图片，单页单图，渲染开销最小化。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.render.card_render.mica_shell import (
    BRAND_CAPSULE_CSS,
    brand_capsule_html,
    drift_blobs_html,
    mica_decor_css,
    render_root_tokens,
    shell_base_css,
)
from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BRAND_THEME,
    DIVIDER,
    GLOW_ACCENT,
    SURFACE_TINTS,
    _darken_hex,
    _hex_to_rgb,
    _rgb_to_hex,
)


def usage_card_accent(config: object) -> tuple[str, str]:
    """主色（accent）与深墨色（accent-ink）：来自 bot_help_card_color 派生。

    hex 换算与加深消费 theme_tokens 单一来源（math 与旧私有副本逐位一致）。
    """
    color = str(getattr(config, "bot_help_card_color", "") or "")
    return _rgb_to_hex(_hex_to_rgb(color)), _darken_hex(color)


# 渠道子行样式（账单席 2026-09-13）：沿用行胶囊写法（.crow 挂 .glass），
# token 只准 var() 引用（半径/色/字重全部走 :root 既有 token）。
# 仅在 model_rows 携带渠道数据时注入 <style>——账本关/无渠道数据时本段
# 不出现，卡面 HTML 与旧版字节级一致（零回归）。
_CHANNEL_SUBROW_CSS = """
/* 渠道子行（家族行下拆渠道消耗；费用降序由 build_model_rows 排好）。 */
.crow { margin-left:26px; display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding:5px 12px; border-radius:var(--r-tile); font-size:12px; color:var(--muted); }
.crow .cname { font-family:var(--font-mono); min-width:0; line-height:1.4; overflow-wrap:anywhere; }
.crow .cmeta { flex-shrink:0; font-variant-numeric:tabular-nums; }
.crow .ccost { color:var(--accent-dark); font-weight:700; }
"""


def _fmt_int(value: object) -> str:
    try:
        if not isinstance(value, (str, bytes, int, float)):
            return "0"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def usage_report_mica_html(
    config: object,
    *,
    kicker: str,
    title: str,
    status_label: str,
    status_kind: str = "ok",
    window_label: str,
    generated_at: str,
    totals: dict[str, Any],
    model_rows: list[dict[str, Any]],
    note: str = "",
    bot_name: str = "",
    bot_avatar_url: str = "",
    feature_label: str = "模型用量",
) -> str:
    """渲染用量/账单报告卡 HTML。

    model_rows 每行：{"model", "prompt", "cache_read", "cache_write",
    "completion", "cost_text", "priced"}；totals 键同 aggregate_llm_usage_range。
    可选键 ``channels``（账本渠道聚合，build_model_rows 产出）：家族行下渲染
    渠道子行（└ 渠道 <id> · N 次 · 费 X 元，费用降序原样透传）。
    vis5（2026-09-13）：补齐 vis4 键（辉光/分隔线/三档表面）+ F11 bot 页脚胶囊
    （此前本卡是唯一无署名卡）。
    2026-09-18：--pc 家族退役，主色 token 统一为 --accent（原别名双写已删）。
    2026-09-20 CAP2：页脚署名改为 **全站统一品牌胶囊**（mica_shell 单一产出，
    本卡手抄 DOM/CSS 退役）；``bot_name`` 空回落 ``BRAND_THEME.display_name``、
    ``bot_avatar_url`` 空回落 ``bot_avatar_uri(config)`` 既有头像口径、英文名取
    ``theme_tokens.BRAND_NAME_EN``（由组件生成器内部取值，本模块零字面量）。
    """
    import html as _html

    from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
        BRAND_WASH_TOKENS,
        payload_phase,
    )

    accent, accent_dark = usage_card_accent(config)
    # 底色锚点=本命蓝（与 7 张模板同一条规则，见 _card_root_tokens 注释）：
    # 本卡 accent 可由 bot_help_card_color 配成任意色，跟着它派生会把整张
    # 账单卡染成该色的深浅，而不是守岸人的釉瑚渐变。
    wash = BRAND_WASH_TOKENS
    kind = status_kind if status_kind in {"ok", "warn", "bad"} else "ok"

    def _model_cell(row: dict[str, Any]) -> str:
        """模型名 + 价格注记（免费/未配置价格/历史未计价，不静默 0.00）。

        合并进来的原始写法清单只在 title 悬浮提示里给（外层 span 已带）。
        """
        name = _html.escape(str(row["model"]))
        note = str(row.get("pricing_note") or "")
        if not note:
            return name
        return f"{name}<span class=\"mnote\">（{_html.escape(note)}）</span>"

    def _channel_subrows_html(row: dict[str, Any]) -> str:
        """渠道子行：└ 渠道 <id> + 次数 + 缓存（有值才显）+ 费用（胶囊样式沿用 .glass 行）。"""
        def _one(sub: dict[str, Any]) -> str:
            parts = [f"{_fmt_int(sub.get('calls'))} 次"]
            cache_read = int(sub.get("cache_read", 0) or 0)
            cache_write = int(sub.get("cache_write", 0) or 0)
            if cache_read:
                parts.append(f"缓存读 {_fmt_int(cache_read)}")
            if cache_write:
                parts.append(f"缓存建 {_fmt_int(cache_write)}")
            meta = " · ".join(parts)
            return (
                '<div class="crow glass">'
                f'<span class="cname" title="{_html.escape(str(sub.get("channel") or ""))}">'
                f'└ 渠道 {_html.escape(str(sub.get("channel") or ""))}</span>'
                f'<span class="cmeta">{meta} · '
                f'<span class="ccost">{_html.escape(str(sub.get("cost_text") or "0.00"))}</span> 元</span>'
                "</div>"
            )

        return "".join(_one(sub) for sub in (row.get("channels") or []))

    rows_html = "".join(
        "<div class=\"mrow glass\">"
        f"<span class=\"mcell model\" title=\"{_html.escape(', '.join(str(item) for item in (row.get('variants') or [row['model']])))}\">{_model_cell(row)}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('prompt'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('cache_read'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('cache_write'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('completion'))}</span>"
        f"<span class=\"mcell num cost{' unpriced' if not row.get('priced') else ''}\">"
        f"{_html.escape(str(row.get('cost_text') or '未计价'))}</span>"
        "</div>"
        + _channel_subrows_html(row)
        for row in model_rows
    )
    # 渠道子行样式只在真有渠道数据时注入（账本关/无渠道 → 字节级旧版）。
    channel_css = _CHANNEL_SUBROW_CSS if any(
        row.get("channels") for row in model_rows
    ) else ""
    totals_cost = str(totals.get("cost_text", "0.00"))
    # 2026-09-18 缓存完善：命中率此前卡片上无处可见，只有裸 token 数看不出缓存起没起作用。
    _prompt_total = int(totals.get("prompt_tokens", 0) or 0)
    _cache_read_total = int(totals.get("cache_read_tokens", 0) or 0)
    cache_rate_text = (
        f"占输入 {_cache_read_total / _prompt_total * 100:.1f}%"
        if _prompt_total > 0
        else "占输入 —"
    )
    unpriced_note = (
        f"{int(totals.get('unpriced_calls', 0) or 0)} 次调用未计价：价格未配置，未计入账单"
        if int(totals.get("unpriced_calls", 0) or 0) > 0
        else ""
    )
    note_html = (
        f"<div class=\"unote\">{_html.escape(note)}</div>"
        if note
        else ""
    )
    # E01 二批：漂移相位 = 内容 digest 钉帧；config 为运行时对象、generated_at
    # 为易变字段（同 bridge._PHASE_VOLATILE_KEYS 口径），均不进 digest。
    # 渠道子行相位归一：空 channels 列表与无键同摘要（渲染零差异，相位不抖）。
    digest_rows = [
        {
            key: value
            for key, value in row.items()
            if key != "channels" or row.get("channels")
        }
        for row in model_rows
    ]
    phase = payload_phase(
        {
            "kicker": kicker,
            "title": title,
            "status_label": status_label,
            "status_kind": status_kind,
            "window_label": window_label,
            "totals": totals,
            "model_rows": digest_rows,
            "note": note,
        },
        # goal-7（2026-09-25）：卡面身份做盐，保证与其它卡面构图不雷同。
        face="usage",
    )
    unpriced_html = (
        f"<div class=\"unote\">{unpriced_note}</div>" if unpriced_note else ""
    )
    # CAP2 统一品牌胶囊（2026-09-20 用户裁定「所有图片加胶囊」）：组件 DOM 与
    # CSS 一律取 mica_shell 单一产出，本卡自写的 .bot-foot 玻璃底 + .bf-avatar/
    # .bf-dot/.bf-name 手抄副本全部退役。三枚输入走既有单一口径：中文名=入参
    # 空则 BRAND_THEME.display_name（与 bridge._capsule_context 同法）、
    # 头像=入参空则 bot_avatar_uri(config)（显式配置 > 进程内登记 > 磁盘兜底，
    # 与 mermaid 卡同源直调，本卡不新建第二份头像逻辑）、英文名由组件内部读
    # theme_tokens.BRAND_NAME_EN（本模块零英文字面量）。
    # 外层 <footer class="bot-foot"> 仅作**摆位宿主**（类名是既有契约锁的
    # 取材锚点，同 universal_card 保留 footer-bot-pill 的手法），
    # 内部不含任何手写署名 DOM/文案。
    from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

    avatar_url = (bot_avatar_url or "").strip() or str(bot_avatar_uri(config) or "")
    bot_footer_html = (
        '<footer class="bot-foot">'
        + brand_capsule_html(
            bot_name=(bot_name or BRAND_THEME.display_name),
            avatar_url=avatar_url,
            feature_label=feature_label,
        )
        + "</footer>"
    )
    # :root 单一产出（v21r3 渲染统一步 4）；本卡特有 vis4 六键经 extras 追加，
    # 取值来源（theme_tokens 单一源）不变。
    root_tokens = render_root_tokens(
        accent=accent,
        accent_dark=accent_dark,
        phase=phase,
        wash=wash,
        extras={
            "--glow-accent": GLOW_ACCENT,
            "--divider-line": DIVIDER,
            "--surface-a": SURFACE_TINTS["tint_a"],
            "--surface-b": SURFACE_TINTS["tint_b"],
            "--surface-neutral": SURFACE_TINTS["tint_neutral"],
        },
    )
    # 通水切换（v21r3 统一收尾波 C2/C3）：壳层+玻璃两档+色斑层由 mica_shell
    # 生成器单一产出拼入（宽度 900=CARD_SHELL_WIDTHS["usage"]；DOM 同源），
    # 手抄副本退役；缺省输出与历史 CSS 逐字节等价（CORE 席实弹断言）。
    shell_css = shell_base_css("shell", width_px=900)
    decor_css = mica_decor_css()
    blobs_html = drift_blobs_html()
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
:root {{ {root_tokens} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:var(--font-family); background:transparent; color:var(--ink);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.stage {{ padding:0; width:fit-content; background:transparent; }}
/* 釉瑚云母外壳+玻璃两档+漂移色斑层：mica_shell 生成器单一产出（v21r3 通水
   切换，2026-09-19）：shell_base_css("shell", width_px=900) + glass 两档
   + mica_decor_css()（三枚 46/52/58s 交错漂移；reduced-motion 关停内建）；
   色斑垫底、内容抬升；阴影只经两枚 token。 */
{shell_css}
{decor_css}
.head {{ padding:20px 26px 16px; border-bottom:var(--divider-line); }}
.kicker {{ color:var(--accent-dark); font-size:12px; font-weight:700; letter-spacing:.06em; }}
.title {{ margin-top:8px; font-size:26px; font-weight:700; }}
/* 语义状态色（红绿黄）置于玻璃层之上，不随釉瑚洗派生。
   渲染统一波（2026-10-03，D-3 了结）：直写登记 hex 退役，改 var() 消费
   :root 公共段语义 token（--semantic-*，值册 theme_tokens.SEMANTIC_* 单源）。 */
.status {{ display:inline-flex; align-items:center; gap:8px; margin-top:12px; padding:6px 14px; border-radius:999px;
  font-size:14px; font-weight:700; border:1px solid #fff; }}
.status.ok {{ color:var(--semantic-success); background:color-mix(in srgb, var(--semantic-success) 8%, #fff); }}
.status.warn {{ color:var(--semantic-warning); background:color-mix(in srgb, var(--semantic-warning) 10%, #fff); }}
.status.bad {{ color:var(--semantic-danger); background:color-mix(in srgb, var(--semantic-danger) 8%, #fff); }}
.window {{ margin-top:10px; color:var(--muted); font-size:13px; }}
.totals {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; padding:14px 14px 4px; }}
.tile {{ border-radius:var(--r-panel); padding:10px 14px; }}
.tile .k {{ font-size:12px; color:var(--muted); font-weight:600; letter-spacing:.06em; }}
.tile .v {{ margin-top:4px; font-size:17px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile .v .sub {{ margin-left:6px; font-size:12px; font-weight:400; color:var(--muted); }}
.tile.cost .v {{ color:var(--accent-dark); }}
.body {{ padding:10px 14px 14px; display:grid; gap:6px; }}
.mhead, .mrow {{ display:grid; grid-template-columns:minmax(150px,1.6fr) repeat(4,1fr) 1.1fr; gap:6px;
  padding:8px 12px; border-radius:var(--r-tile); align-items:center; }}
.mhead {{ font-size:12px; color:var(--muted); font-weight:700; letter-spacing:.02em; padding-bottom:2px; }}
.mrow {{ font-size:12px; font-variant-numeric:tabular-nums; }}
.mcell {{ line-height:1.4; overflow-wrap:anywhere; }}
.mcell.model {{ font-family:var(--font-mono); font-weight:600; }}
.mcell.model .mnote {{ font-family:var(--font-family); font-weight:400; color:var(--muted); font-size:12px; margin-left:4px; }}
.mcell.num {{ text-align:right; }}
.mcell.cost {{ font-weight:700; color:var(--accent-dark); }}
.mcell.cost.unpriced {{ color:var(--muted); font-weight:400; }}
.unote {{ padding:2px 12px 8px; color:var(--muted); font-size:12px; }}
.foot {{ padding:12px 26px 16px; border-top:var(--divider-line);
  background:rgba(255,255,255,.46); font-size:12px; color:var(--muted); }}
/* CAP2（2026-09-20）：.bot-foot 只留**摆位**（外边距宿主），署名件本体见下方
   mica_shell 单一产出的品牌胶囊样式；旧 .bot-foot 玻璃底与 .bf-avatar/.bf-dot/
   .bf-name 手抄副本（含 rgba 字面量）随本次收口退役。 */
.bot-foot {{ margin:0 14px 14px; }}
{BRAND_CAPSULE_CSS}
{channel_css}</style></head><body><div class="stage card"><section class="shell">
{blobs_html}
<header class="head glass">
<div class="kicker">{_html.escape(kicker)}</div>
<div class="title">{_html.escape(title)}</div>
<div class="status {kind}">{_html.escape(status_label)}</div>
<div class="window">{_html.escape(window_label)} · 生成于 {_html.escape(generated_at)}</div>
</header>
<div class="totals">
<div class="tile glass"><div class="k">输入 Token</div><div class="v">{_fmt_int(totals.get("prompt_tokens"))}</div></div>
<div class="tile glass"><div class="k">缓存命中</div><div class="v">{_fmt_int(totals.get("cache_read_tokens"))}<span class="sub">{cache_rate_text}</span></div></div>
<div class="tile glass"><div class="k">缓存创建</div><div class="v">{_fmt_int(totals.get("cache_write_tokens"))}</div></div>
<div class="tile glass"><div class="k">输出 Token</div><div class="v">{_fmt_int(totals.get("completion_tokens"))}</div></div>
<div class="tile cost glass"><div class="k">总 Token</div><div class="v">{_fmt_int(totals.get("total_tokens"))}</div></div>
<div class="tile cost glass"><div class="k">账单（元）</div><div class="v">{_html.escape(totals_cost)}</div></div>
<div class="tile glass"><div class="k">调用次数</div><div class="v">{_fmt_int(totals.get("calls", 0))}</div></div>
<div class="tile glass"><div class="k">统计口径</div><div class="v" style="font-size:13px;">按调用时价格</div></div>
</div>
<main class="body">
<div class="mhead"><span>模型</span><span class="mcell num">输入</span><span class="mcell num">缓存命中</span><span class="mcell num">缓存创建</span><span class="mcell num">输出</span><span class="mcell num">费用（元）</span></div>
{rows_html}
</main>
{unpriced_html}
{note_html}
<footer class="foot">账单 = Σ(输入×输入价 + 输出×输出价)，按每次调用时刻的价格表记账；价格用 /bot model price 维护。</footer>
{bot_footer_html}
</section></div>
</body></html>"""


def render_usage_card_png(
    render_backend: Any | None,
    html_text: str,
    *,
    card_dir: str,
    request_id: str,
    prefix: str = "usage",
) -> str:
    """渲染用量卡为 PNG 并落盘；任何失败返回空串（调用方回退文本）。"""
    if render_backend is None or not getattr(render_backend, "available", False):
        return ""
    if not html_text:
        return ""
    try:
        png = render_backend.render_card(
            {
                "html": html_text,
                "viewport": {"width": 950, "height": 1000},
                "device_scale_factor": 2,
                "wait_ms": 0,
            }
        )
        if not isinstance(png, bytes) or not png:
            return ""
        target = Path(card_dir or "data/cards")
        target.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(f"{request_id}:{prefix}".encode()).hexdigest()[:12]
        path = target / f"{prefix}_{digest}.png"
        path.write_bytes(png)
        return str(path)
    except Exception:  # noqa: BLE001 - 卡片失败回退文本。
        return ""


__all__ = [
    "render_usage_card_png",
    "usage_card_accent",
    "usage_report_mica_html",
]
