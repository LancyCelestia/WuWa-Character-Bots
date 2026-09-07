"""模型用量/账单报告卡：Mica 云母质感（Windows 11 规范）。

规范要点（与 parse 卡/帮助卡一致）：
- 底色渐变只从平台色派生；无平台语境的用量卡主色来自
  ``bot_help_card_color``（留空回退中性灰），经 ``--accent`` 用
  ``color-mix(in srgb, ... #fff)`` 掺白派生，不写死品牌色。
- 阴影只允许两枚 token（外壳大柔光 + 面板微光）；圆角走 --r-shell/--r-panel。
- 字重最大 700；body 透明背景 + antialiased（截图 omit_background 依赖）。
- 纯 HTML+CSS，无外链字体/图片，单页单图，渲染开销最小化。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return (96, 112, 128)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (96, 112, 128)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _darken(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = (max(0, min(255, int(channel * 0.8))) for channel in rgb)
    return red, green, blue


def usage_card_accent(config: object) -> tuple[str, str]:
    """主色（accent）与深墨色（accent-ink）：来自 bot_help_card_color 派生。"""
    rgb = _hex_to_rgb(str(getattr(config, "bot_help_card_color", "") or ""))
    return _rgb_to_hex(rgb), _rgb_to_hex(_darken(rgb))


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
) -> str:
    """渲染用量/账单报告卡 HTML。

    model_rows 每行：{"model", "prompt", "cache_read", "cache_write",
    "completion", "cost_text", "priced"}；totals 键同 aggregate_llm_usage_range。
    """
    import html as _html

    accent, accent_ink = usage_card_accent(config)
    kind = status_kind if status_kind in {"ok", "warn", "bad"} else "ok"
    rows_html = "".join(
        "<div class=\"mrow\">"
        f"<span class=\"mcell model\" title=\"{_html.escape(str(row['model']))}\">{_html.escape(str(row['model']))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('prompt'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('cache_read'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('cache_write'))}</span>"
        f"<span class=\"mcell num\">{_fmt_int(row.get('completion'))}</span>"
        f"<span class=\"mcell num cost{' unpriced' if not row.get('priced') else ''}\">"
        f"{_html.escape(str(row.get('cost_text') or '未计价'))}</span>"
        "</div>"
        for row in model_rows
    )
    totals_cost = str(totals.get("cost_text", "0.00"))
    unpriced_note = (
        f"{int(totals.get('unpriced_calls', 0) or 0)} 次调用未配置价格，未计入账单"
        if int(totals.get("unpriced_calls", 0) or 0) > 0
        else ""
    )
    note_html = (
        f"<div class=\"unote\">{_html.escape(note)}</div>"
        if note
        else ""
    )
    unpriced_html = (
        f"<div class=\"unote\">{unpriced_note}</div>" if unpriced_note else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
:root {{ --accent:{accent}; --accent-ink:{accent_ink}; --ink:#27232a; --muted:#6f646c;
  --r-shell:24px; --r-panel:12px; --mica-shadow:0 12px 32px rgba(31,35,41,.10); --mica-shadow-soft:0 3px 10px rgba(31,35,41,.05); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:transparent; color:var(--ink);
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }}
.stage {{ padding:26px; background:transparent; }}
.shell {{ width:900px; overflow:hidden; border-radius:var(--r-shell); border:1px solid rgba(255,255,255,.9);
  background:linear-gradient(165deg, color-mix(in srgb, var(--accent) 3%, #fff) 0%, color-mix(in srgb, var(--accent) 8%, #fff) 100%);
  box-shadow:var(--mica-shadow); }}
.head {{ padding:20px 26px 16px; background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 2%, #fff), color-mix(in srgb, var(--accent) 6%, #fff));
  border-bottom:1px solid color-mix(in srgb, var(--accent) 16%, #fff); }}
.kicker {{ color:var(--accent-ink); font-size:11px; font-weight:700; letter-spacing:.14em; }}
.title {{ margin-top:8px; font-size:26px; font-weight:700; }}
.status {{ display:inline-flex; align-items:center; gap:8px; margin-top:12px; padding:6px 14px; border-radius:999px;
  font-size:14px; font-weight:700; border:1px solid #fff; }}
.status.ok {{ color:#1a9e6c; background:color-mix(in srgb, #1a9e6c 8%, #fff); }}
.status.warn {{ color:#b07d1a; background:color-mix(in srgb, #b07d1a 10%, #fff); }}
.status.bad {{ color:#d64545; background:color-mix(in srgb, #d64545 8%, #fff); }}
.window {{ margin-top:10px; color:var(--muted); font-size:13px; }}
.totals {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; padding:14px 14px 4px; }}
.tile {{ border-radius:var(--r-panel); padding:10px 14px; background:color-mix(in srgb, var(--accent) 4%, #ffffff);
  border:1px solid rgba(255,255,255,.95); box-shadow:var(--mica-shadow-soft); }}
.tile .k {{ font-size:11px; color:var(--muted); font-weight:600; letter-spacing:.04em; }}
.tile .v {{ margin-top:4px; font-size:18px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile.cost .v {{ color:var(--accent-ink); }}
.body {{ padding:10px 14px 14px; display:grid; gap:5px; }}
.mhead, .mrow {{ display:grid; grid-template-columns:minmax(150px,1.6fr) repeat(4,1fr) 1.1fr; gap:6px;
  padding:8px 12px; border-radius:10px; align-items:center; }}
.mhead {{ font-size:11px; color:var(--muted); font-weight:700; letter-spacing:.03em; padding-bottom:2px; }}
.mrow {{ background:color-mix(in srgb, var(--accent) 4%, #ffffff); border:1px solid rgba(255,255,255,.95);
  font-size:12.5px; font-variant-numeric:tabular-nums; }}
.mcell {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.mcell.model {{ font-family:Consolas,monospace; font-weight:650; }}
.mcell.num {{ text-align:right; }}
.mcell.cost {{ font-weight:700; color:var(--accent-ink); }}
.mcell.cost.unpriced {{ color:var(--muted); font-weight:400; }}
.unote {{ padding:2px 12px 8px; color:var(--muted); font-size:12px; }}
.foot {{ padding:12px 26px 16px; border-top:1px solid color-mix(in srgb, var(--accent) 16%, #fff);
  background:color-mix(in srgb, var(--accent) 10%, #fff); font-size:12px; color:var(--muted); }}
</style></head><body><div class="stage card"><section class="shell">
<header class="head">
<div class="kicker">{_html.escape(kicker)}</div>
<div class="title">{_html.escape(title)}</div>
<div class="status {kind}">{_html.escape(status_label)}</div>
<div class="window">{_html.escape(window_label)} · 生成于 {_html.escape(generated_at)}</div>
</header>
<div class="totals">
<div class="tile"><div class="k">输入 Token</div><div class="v">{_fmt_int(totals.get("prompt_tokens"))}</div></div>
<div class="tile"><div class="k">缓存命中</div><div class="v">{_fmt_int(totals.get("cache_read_tokens"))}</div></div>
<div class="tile"><div class="k">缓存创建</div><div class="v">{_fmt_int(totals.get("cache_write_tokens"))}</div></div>
<div class="tile"><div class="k">输出 Token</div><div class="v">{_fmt_int(totals.get("completion_tokens"))}</div></div>
<div class="tile cost"><div class="k">总 Token</div><div class="v">{_fmt_int(totals.get("total_tokens"))}</div></div>
<div class="tile cost"><div class="k">账单（元）</div><div class="v">{_html.escape(totals_cost)}</div></div>
<div class="tile"><div class="k">调用次数</div><div class="v">{_fmt_int(totals.get("calls", 0))}</div></div>
<div class="tile"><div class="k">统计口径</div><div class="v" style="font-size:13px;">按调用时价格</div></div>
</div>
<main class="body">
<div class="mhead"><span>模型</span><span class="mcell num">输入</span><span class="mcell num">缓存命中</span><span class="mcell num">缓存创建</span><span class="mcell num">输出</span><span class="mcell num">费用（元）</span></div>
{rows_html}
</main>
{unpriced_html}
{note_html}
<footer class="foot">账单 = Σ(输入×输入价 + 输出×输出价)，按每次调用时刻的价格表记账；价格用 /bot model price 维护。</footer>
</section></div></body></html>"""


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
