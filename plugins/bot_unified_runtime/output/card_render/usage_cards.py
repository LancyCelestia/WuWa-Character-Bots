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

from plugins.bot_unified_runtime.output.card_render.theme_tokens import (
    BRAND_THEME,
    DIVIDER,
    FONT_FAMILY_STACK,
    GLOW_ACCENT,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
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
.crow .cname { font-family:Consolas,monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.crow .cmeta { flex-shrink:0; font-variant-numeric:tabular-nums; }
.crow .ccost { color:var(--accent-ink); font-weight:700; }
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
    bot_name: str = "守岸人",
    bot_avatar_url: str = "",
    feature_label: str = "模型用量",
) -> str:
    """渲染用量/账单报告卡 HTML。

    model_rows 每行：{"model", "prompt", "cache_read", "cache_write",
    "completion", "cost_text", "priced"}；totals 键同 aggregate_llm_usage_range。
    可选键 ``channels``（账本渠道聚合，build_model_rows 产出）：家族行下渲染
    渠道子行（└ 渠道 <id> · N 次 · 费 X 元，费用降序原样透传）。
    vis5（2026-09-13）：补齐 vis4 键（辉光/分隔线/三档表面，--pc 为 --accent
    的共享 token 别名）+ F11 bot 页脚胶囊（此前本卡是唯一无署名卡）。
    """
    import html as _html

    from plugins.bot_unified_runtime.output.card_render.bridge import (
        _derive_wash_tokens,
        payload_phase,
    )

    accent, accent_ink = usage_card_accent(config)
    wash = _derive_wash_tokens(accent)
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
        """渠道子行：└ 渠道 <id> + 次数 + 费用（胶囊样式沿用 .glass 行）。"""
        return "".join(
            '<div class="crow glass">'
            f'<span class="cname" title="{_html.escape(str(sub.get("channel") or ""))}">'
            f'└ 渠道 {_html.escape(str(sub.get("channel") or ""))}</span>'
            f'<span class="cmeta">{_fmt_int(sub.get("calls"))} 次 · '
            f'<span class="ccost">{_html.escape(str(sub.get("cost_text") or "0.00"))}</span> 元</span>'
            "</div>"
            for sub in (row.get("channels") or [])
        )

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
        }
    )
    unpriced_html = (
        f"<div class=\"unote\">{unpriced_note}</div>" if unpriced_note else ""
    )
    # F11 bot 页脚胶囊（与 templates.py card-footer-bot 同构；avatar 失败隐藏）。
    avatar_html = (
        f'<img class="bf-avatar" src="{_html.escape(bot_avatar_url)}" alt="" '
        'onerror="this.style.display=\'none\'"/>'
        if bot_avatar_url
        else f'<span class="bf-dot">{_html.escape((bot_name or "守")[:1])}</span>'
    )
    bot_footer_html = (
        f'<footer class="bot-foot">{avatar_html}'
        f'<span class="bf-name">{_html.escape(bot_name or "守岸人")}</span>'
        f'<span>· {_html.escape(feature_label)}</span></footer>'
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
:root {{ --phase:{phase}; --accent:{accent}; --accent-ink:{accent_ink};
  /* --pc = --accent 别名：GLOW_ACCENT 等 theme_tokens 共享 token 以 --pc 取色。 */
  --pc:{accent};
  /* 釉瑚云母底主题 token，全卡统一（bridge 按 --accent 派生；工艺出处=用户裁定）。 */
  --wash-1:{wash['wash_1']}; --wash-2:{wash['wash_2']}; --wash-3:{wash['wash_3']}; --wash-mist:{wash['wash_mist']};
  --wash-blob-1:color-mix(in srgb, var(--accent) 35%, var(--wash-1));
  --text-main:{BRAND_THEME.text_main}; --text-sub:{BRAND_THEME.text_sub};
  --ink:var(--text-main); --muted:var(--text-sub);
  --font-family:{FONT_FAMILY_STACK};
  --r-shell:{BRAND_THEME.shell_radius}px; --r-panel:{BRAND_THEME.panel_radius}px; --r-tile:{BRAND_THEME.tile_radius}px;
  --mica-shadow:{SHADOW_PRIMARY}; --mica-shadow-soft:{SHADOW_SECONDARY};
  /* vis4 辉光/分隔线/三档表面（theme_tokens 单一源，与六张 Jinja 卡同值）。 */
  --glow-accent:{GLOW_ACCENT}; --divider-line:{DIVIDER};
  --surface-a:{SURFACE_TINTS['tint_a']}; --surface-b:{SURFACE_TINTS['tint_b']}; --surface-neutral:{SURFACE_TINTS['tint_neutral']}; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:var(--font-family); background:transparent; color:var(--ink);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.stage {{ padding:0; width:fit-content; background:transparent; }}
/* 釉瑚云母外壳：雾底打底、wash-1/2 对角透色、wash-3 只作第三色透底（不透明基础层）
   + 1px 内高光渐变描边；色斑垫底、内容抬升。 */
.shell {{ position:relative; width:900px; overflow:hidden; border-radius:var(--r-shell); border:1px solid transparent;
  background:linear-gradient(145deg, var(--wash-mist) 0%, color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%,
    color-mix(in srgb, var(--wash-2) 48%, var(--wash-mist)) 64%, color-mix(in srgb, var(--wash-3) 40%, var(--wash-mist)) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  box-shadow:var(--mica-shadow); }}
.shell > :not(.drift-blobs) {{ position:relative; z-index:1; }}
/* 渐变漂移色斑（wash 三色半透明互相透过，46s/52s/58s 交错漂移+呼吸）。 */
.drift-blobs {{ position:absolute; inset:0; z-index:0; overflow:hidden; pointer-events:none; border-radius:inherit; }}
.drift-blob {{ position:absolute; display:block; border-radius:50%; will-change:transform; }}
.drift-blob.drift-a {{ width:58%; aspect-ratio:1; left:-14%; top:-22%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-blob-1) 50%, transparent) 0%,
    color-mix(in srgb, var(--wash-blob-1) 28%, transparent) 46%, color-mix(in srgb, var(--wash-blob-1) 6%, transparent) 70%, transparent 100%);
  animation:mica-drift-a 46s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -46s); }}
.drift-blob.drift-b {{ width:52%; aspect-ratio:1; right:-16%; bottom:-24%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-2) 30%, transparent) 0%,
    color-mix(in srgb, var(--wash-2) 16%, transparent) 48%, color-mix(in srgb, var(--wash-2) 5%, transparent) 72%, transparent 100%);
  animation:mica-drift-b 58s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -58s - 9s); }}
.drift-blob.drift-c {{ width:64%; aspect-ratio:1; left:22%; top:34%;
  background:radial-gradient(closest-side, color-mix(in srgb, var(--wash-3) 26%, transparent) 0%,
    color-mix(in srgb, var(--wash-3) 14%, transparent) 48%, color-mix(in srgb, var(--wash-3) 5%, transparent) 72%, transparent 100%);
  animation:mica-drift-c 52s ease-in-out infinite alternate; animation-delay:calc(var(--phase, 0.2) * -52s - 21s); }}
@keyframes mica-drift-a {{ 0% {{ transform:translate3d(-4%,-2%,0) scale(1); }} 50% {{ transform:translate3d(7%,9%,0) scale(1.18); }} 100% {{ transform:translate3d(-3%,14%,0) scale(.92); }} }}
@keyframes mica-drift-b {{ 0% {{ transform:translate3d(3%,4%,0) scale(1.05); }} 50% {{ transform:translate3d(-8%,-6%,0) scale(.9); }} 100% {{ transform:translate3d(-2%,-12%,0) scale(1.2); }} }}
@keyframes mica-drift-c {{ 0% {{ transform:translate3d(-5%,4%,0) scale(1.1); }} 50% {{ transform:translate3d(9%,-7%,0) scale(.88); }} 100% {{ transform:translate3d(2%,-3%,0) scale(1.16); }} }}
@media (prefers-reduced-motion: reduce) {{ .drift-blob.drift-a, .drift-blob.drift-b, .drift-blob.drift-c {{ animation:none; }} }}
/* 液态玻璃面板：半透明白 + 1px 内高光渐变描边（无 backdrop-filter）。 */
.glass {{ background:linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.44) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  border:1px solid transparent; box-shadow:var(--mica-shadow-soft); }}
.head {{ padding:20px 26px 16px; border-bottom:var(--divider-line); }}
.kicker {{ color:var(--accent-ink); font-size:12px; font-weight:700; letter-spacing:.06em; }}
.title {{ margin-top:8px; font-size:26px; font-weight:700; }}
/* 语义状态色（红绿黄）置于玻璃层之上，不随釉瑚洗派生。 */
.status {{ display:inline-flex; align-items:center; gap:8px; margin-top:12px; padding:6px 14px; border-radius:999px;
  font-size:14px; font-weight:700; border:1px solid #fff; }}
.status.ok {{ color:#1a9e6c; background:color-mix(in srgb, #1a9e6c 8%, #fff); }}
.status.warn {{ color:#b07d1a; background:color-mix(in srgb, #b07d1a 10%, #fff); }}
.status.bad {{ color:#d64545; background:color-mix(in srgb, #d64545 8%, #fff); }}
.window {{ margin-top:10px; color:var(--muted); font-size:13px; }}
.totals {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; padding:14px 14px 4px; }}
.tile {{ border-radius:var(--r-panel); padding:10px 14px; }}
.tile .k {{ font-size:12px; color:var(--muted); font-weight:600; letter-spacing:.06em; }}
.tile .v {{ margin-top:4px; font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile.cost .v {{ color:var(--accent-ink); }}
.body {{ padding:10px 14px 14px; display:grid; gap:6px; }}
.mhead, .mrow {{ display:grid; grid-template-columns:minmax(150px,1.6fr) repeat(4,1fr) 1.1fr; gap:6px;
  padding:8px 12px; border-radius:var(--r-tile); align-items:center; }}
.mhead {{ font-size:12px; color:var(--muted); font-weight:700; letter-spacing:.02em; padding-bottom:2px; }}
.mrow {{ font-size:12.5px; font-variant-numeric:tabular-nums; }}
.mcell {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.mcell.model {{ font-family:Consolas,monospace; font-weight:650; }}
.mcell.model .mnote {{ font-family:var(--font-family); font-weight:400; color:var(--muted); font-size:12px; margin-left:4px; }}
.mcell.num {{ text-align:right; }}
.mcell.cost {{ font-weight:700; color:var(--accent-ink); }}
.mcell.cost.unpriced {{ color:var(--muted); font-weight:400; }}
.unote {{ padding:2px 12px 8px; color:var(--muted); font-size:12px; }}
.foot {{ padding:12px 26px 16px; border-top:var(--divider-line);
  background:rgba(255,255,255,.42); font-size:12px; color:var(--muted); }}
/* F11 bot 页脚胶囊（vis5 补齐：此前本卡是唯一无署名卡）。 */
.bot-foot {{ margin:0 14px 14px; padding:9px 14px; border-radius:var(--r-tile);
  display:flex; align-items:center; gap:7px; font-size:12px; color:var(--muted);
  background:
    var(--glow-accent) right center / 62% 190% no-repeat,
    linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.46) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  border:1px solid transparent; box-shadow:var(--mica-shadow-soft); }}
.bot-foot .bf-dot {{ width:22px; height:22px; border-radius:50%; flex-shrink:0;
  display:inline-flex; align-items:center; justify-content:center;
  font-size:12px; font-weight:650; color:var(--accent-ink);
  background:color-mix(in srgb, var(--accent) 14%, #fff); }}
.bot-foot .bf-avatar {{ width:22px; height:22px; border-radius:50%; object-fit:cover;
  border:1px solid #fff; box-shadow:var(--mica-shadow-soft); }}
.bot-foot .bf-name {{ font-weight:650; color:var(--text-main); }}
{channel_css}</style></head><body><div class="stage card"><section class="shell">
<div class="drift-blobs" aria-hidden="true"><span class="drift-blob drift-a"></span><span class="drift-blob drift-b"></span><span class="drift-blob drift-c"></span></div>
<header class="head glass">
<div class="kicker">{_html.escape(kicker)}</div>
<div class="title">{_html.escape(title)}</div>
<div class="status {kind}">{_html.escape(status_label)}</div>
<div class="window">{_html.escape(window_label)} · 生成于 {_html.escape(generated_at)}</div>
</header>
<div class="totals">
<div class="tile glass"><div class="k">输入 Token</div><div class="v">{_fmt_int(totals.get("prompt_tokens"))}</div></div>
<div class="tile glass"><div class="k">缓存命中</div><div class="v">{_fmt_int(totals.get("cache_read_tokens"))}</div></div>
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
