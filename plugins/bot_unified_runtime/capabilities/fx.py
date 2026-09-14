"""汇率能力（bot.fx）：`汇率`/`美元兑人民币`/`USD/CNY`/`100日元换多少人民币` 触发。

数据来自 ``sources.fx_data``：东财快查主源（2026-09-12 实测 secid，60s 进程内
缓存）+ er-api 快照备选（文档化保留）。缺币/无源货币对显式展示「暂无数据」，
绝不补 0；汇率无可用日 K（实测 119/120/133 板块 kline 全空）→ 卡上诚实标注
「暂无历史走势数据」，不伪造走势。

表达方向（``parse_fx_query``）：「美元兑人民币」「USD/CNY」「100日元换多少
人民币」「日元汇率」（单查默认兑人民币）、「汇率/主要货币」面板。

路由接线说明（C 方向边界）：本模块只提供能力闭包与触发判定接口；
matcher/RouteKind 注册属 base_router 与命令域（B 方向文件），接线由主链路
按 bot.market 同构方式完成（``_build_fx_with_backend`` → ``bot.fx``）。
"""

from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.capabilities import user_copy
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.output.bot_avatar import bot_avatar_uri

_URL_HINT_RE = re.compile(r"https?://", re.IGNORECASE)
_MAX_TRIGGER_LEN = 48
# 「匯率/兌換/換匯」繁体与「fx/forex/exchange rate」英文为 2026-09-13
# 多语言触发覆盖（英文用词边界，防误伤普通英文聊天）。
# 全拼/缩写（T-Spec T1.5/T1.6 第三批）：huilv/duihuan/huanhui 同音覆盖简繁词，
# 双侧 ASCII 词边界防 duihuans 类胶合；hl（×忽略）/dh（×对话）真冲突缩写
# 不启用，hh（换汇）查重无冲突入表。
# 评审 P1-1：裸「换算」不触发（「单位换算」「长度换算」），须同句出现币名
# （huansuan 同受此条件语义门约束，拼音化顺延，与 music mode 先例同口径）。
_FX_HINT_RE = re.compile(
    r"(汇率|兑换|换汇|匯率|兌換|換匯)"
    r"|(?<![A-Za-z0-9])(?:huilv|duihuan|huanhui|hh)(?![A-Za-z0-9])"
)
_FX_CONVERT_RE = re.compile(r"换算|換算")
_FX_ENGLISH_RE = re.compile(r"\b(?:fx|forex|exchange rate)\b", re.IGNORECASE)
_FX_NON_HINT_RE = re.compile(r"(话术|积分|話術|積分)")
_STOCK_GUARD_RE = re.compile(r"(股价|股票|股價|股指|大盘|大盤|基金|房价)")


def is_fx_command(text: str) -> bool:
    """汇率触发判定：短文本、无链接、命中汇率意图且不撞股票语境。"""
    from plugins.bot_unified_runtime.sources.fx_data import (
        has_currency_term,
        parse_fx_query,
        wants_major_rates,
    )

    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_TRIGGER_LEN:
        return False
    if _URL_HINT_RE.search(stripped):
        return False
    if _FX_NON_HINT_RE.search(stripped):
        return False
    if parse_fx_query(stripped):
        return not _STOCK_GUARD_RE.search(stripped)
    if wants_major_rates(stripped):
        return not _STOCK_GUARD_RE.search(stripped)
    if _FX_ENGLISH_RE.search(stripped):
        return not _STOCK_GUARD_RE.search(stripped)
    if _FX_CONVERT_RE.search(stripped):
        # 「美元换算」可触发；「单位换算」「长度换算公式」不触发。
        return bool(has_currency_term(stripped)) and not _STOCK_GUARD_RE.search(
            stripped
        )
    return bool(_FX_HINT_RE.search(stripped))


def build_fx_card_payload(
    rates: list[Any], missing_note: str, *, focus_label: str | None = None
) -> dict[str, Any]:
    """组装 finance_card（render_finance_card_html）payload（汇率面板块）。

    缺数据行明确展示「暂无数据」（含无源货币对），绝不伪造 0 汇率；
    汇率无可用日 K → 每行 trend_note 诚实标注，不伪造走势。

    ``focus_label``（定向换算查询，如「USD兑CNY」）：卡仍为主要货币面板，
    但副标题显式标注面板语义（换算结果在消息文字里），消除「问 A 答 B」
    的 body/card 错位（评审域 B 发现 6，2026-09-13）；面板查询不带标注。
    """
    rows: list[dict[str, Any]] = []
    for rate in rates:
        type_note = {
            "spot": "现货/参考价",
            "parity": "人民币中间价",
            "derived": "交叉换算",
        }.get(rate.rate_type, rate.rate_type)
        rows.append(
            {
                "label": f"{rate.base_currency}/{rate.quote_currency}",
                "value": f"{rate.rate:.4f}",
                "cls": "flat",
                "sub": type_note,
                # 东财外汇板块无日 K（实测）：诚实标注走势缺口。
                "trend_note": "暂无历史走势数据",
            }
        )
    if missing_note:
        rows.append(
            {
                "label": "暂无数据",
                "value": missing_note,
                "cls": "flat",
                "sub": "上游无该货币对行情",
            }
        )
    return {
        "title": "汇率速览",
        "subtitle": (
            f"主要货币面板 · {focus_label} 换算结果见消息文字"
            if focus_label
            else "中间价/参考价 · 延迟行情"
        ),
        "badge": "延迟行情",
        "sections": [{"name": "主要货币（USD 基准面板）", "rows": rows}],
        "source_note": "数据源：东方财富（er-api 备选）",
        "updated_at": rates[0].timestamp if rates else "",
        "delayed_note": "非实时报价，非可成交价",
        "feature_label": "汇率",
    }


def build_fx_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any:
    """构建汇率能力闭包；快照/汇率获取可整体 monkeypatch，文本离线可测。"""

    def _render_card(
        payload: dict[str, Any], card_dir: str, *, semantic_key: str = "panel"
    ) -> str:
        if render_backend is None or not getattr(render_backend, "available", False):
            return ""
        try:
            from plugins.bot_unified_runtime.output.card_render.bridge import (
                render_finance_card_html,
            )
            from plugins.bot_unified_runtime.runtime.cache_policy import prune_prefixed

            payload = dict(payload)
            payload["bot_name"] = str(
                getattr(config, "bot_persona_display_name", "") or ""
            ).strip() or "守岸人"
            payload["bot_avatar_url"] = str(
                bot_avatar_uri(config)
            )
            png = render_backend.render_card(
                {
                    "html": render_finance_card_html(payload),
                    "viewport": {"width": 1160, "height": 1200},
                    "device_scale_factor": 2,
                    "wait_ms": 0,
                }
            )
            if not isinstance(png, bytes) or not png:
                return ""
            # 文件名 digest 纳入查询语义（评审域 B 发现 6，2026-09-13）：
            # 面板查询 → "panel"，同文件幂等（行情数值刷新覆写同一枚面板
            # 文件，prune keep=120 语义稳定）；定向换算 → "pair:{货币对方向}"，
            # 不同查询各占一枚文件，不再同名互覆。卡面不承载金额，同一
            # 货币对不同金额共用一枚文件。
            digest = hashlib.sha1(
                f"fx|{semantic_key}|{payload.get('subtitle', '')}|{len(payload.get('sections', []))}".encode()
            ).hexdigest()[:12]
            target = Path(card_dir or "data/cards")
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"fx_{digest}.png"
            path.write_bytes(png)
            try:
                prune_prefixed(target, "fx", keep=120)
            except Exception:  # noqa: S110, BLE001 - 配额清理失败不影响出图。
                pass
            return str(path)
        except Exception:  # noqa: BLE001 - 渲染失败回退纯文本。
            return ""

    def capability(message: IncomingMessage, decision: BotDecision) -> CapabilityResult:
        from plugins.bot_unified_runtime.sources.fx_data import (
            FX_UNAVAILABLE_PAIRS,
            fetch_fx_rates,
            format_fx_brief,
            format_fx_rate_line,
            parse_fx_query,
            resolve_fx_pair,
        )

        rates = fetch_fx_rates()
        if not rates:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.fx",
                kind="text",
                # 审查 Q-01：数据源失败池轮换取句（原固定 U12 单句）。
                body=random.choice(user_copy.DATASOURCE_FAILURE_TEMPLATES).format(
                    reason="汇率数据暂时拉不到"
                ),
                audit_tags=["capability:fx", "fx:fetch_failed"],
            )

        text = message.plain_text
        query = parse_fx_query(text)
        card_dir = str(
            getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
        )
        title = "汇率速览"
        audit_extra = "fx:major_panel"
        # 定向换算命中（正/反向均有报价）时记录货币对方向：卡副标题标注
        # 面板语义 + 文件名按查询语义分文件（评审域 B 发现 6）。
        focus_label = ""

        if query is not None:
            base, quote, amount = query
            resolved = resolve_fx_pair(base, quote)
            if resolved is None:
                body = (
                    f"{base}/{quote} 暂无数据（东财无该货币对行情），先不瞎猜数字。"
                )
                audit_extra = "fx:pair_unavailable"
            else:
                pair_key, inverted = resolved
                pair_base, pair_quote = pair_key.split("/", 1)
                rate = next(
                    (
                        item
                        for item in rates
                        if item.base_currency == pair_base
                        and item.quote_currency == pair_quote
                    ),
                    None,
                )
                if rate is None:
                    body = f"{base}/{quote} 暂无数据（上游缺该货币对报价）。"
                    audit_extra = "fx:pair_unavailable"
                elif inverted:
                    unit_rate = rate.unit_base / rate.rate
                    converted = amount * unit_rate
                    body = (
                        f"{amount:g} {base} ≈ {converted:,.2f} {quote}\n"
                        f"1 {base} = {unit_rate:,.4f} {quote}"
                        f"（由 {pair_key} 反向换算）"
                    )
                    title = f"{base}兑{quote}"
                    audit_extra = f"fx:pair:{pair_key}"
                    focus_label = f"{base}兑{quote}"
                else:
                    converted = amount / rate.unit_base * rate.rate
                    # 参考汇率按 unit_base 折算为「每 1 基准币」口径
                    # （JPY 中间价是每 100 日元口径，直接展示 rate 会差 100 倍——
                    # 评审 P0-1，2026-09-13）。
                    unit_rate = rate.rate / rate.unit_base
                    body = (
                        f"{format_fx_rate_line(rate, amount)}\n"
                        f"1 {base} = {unit_rate:g} {quote}"
                        f"（{rate.source} · {rate.rate_type}）"
                    )
                    title = f"{base}兑{quote}"
                    audit_extra = f"fx:pair:{pair_key}"
                    focus_label = f"{base}兑{quote}"
        else:
            body = format_fx_brief(rates)

        semantic_key = "panel"
        if focus_label:
            semantic_key = f"pair:{focus_label}"
        payload = build_fx_card_payload(
            rates, "、".join(FX_UNAVAILABLE_PAIRS), focus_label=focus_label or None
        )
        card = _render_card(payload, card_dir, semantic_key=semantic_key)
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.fx",
            kind="mixed" if card else "text",
            title=title,
            body=body,
            images=[{"file": card}] if card else [],
            risk_level=RiskLevel.LOW,
            privacy_level=PrivacyLevel.PUBLIC,
            audit_tags=[
                "capability:fx",
                audit_extra,
                f"fx:quotes:{len(rates)}",
                "card_rendered" if card else "text_only",
            ],
        )

    return capability
