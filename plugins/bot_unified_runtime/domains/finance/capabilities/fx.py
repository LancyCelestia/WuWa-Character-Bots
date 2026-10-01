"""汇率能力（bot.fx）：`汇率`/`美元兑人民币`/`USD/CNY`/`100日元换多少人民币` 触发。

数据来自 ``domains.finance.data.fx_data``：东财快查主源（2026-09-12 实测 secid，60s 进程内
缓存）+ er-api 快照备选（文档化保留）。缺币/无源货币对显式展示「暂无数据」，
绝不补 0；汇率无可用日 K（实测 119/120/133 板块 kline 全空）→ 卡上诚实标注
「暂无历史走势数据」，不伪造走势。

回答顺序（定向换算）：实测直盘 → 反向命中（取倒数并标注）→ USD 三角换算
（``fx_derived_quote``，只用本轮在盘的两条现货腿，产出 ``derived`` 口径并在
正文点名两条腿）→ 全部落空时按三态名册给不同的拒答话（``fx_no_quote_reason``：
实测查无 / 候选源待真机核实 / 未登记源），**待验币绝不被说成「东财无行情」，
也绝不被估算值顶替**。面板卡只列实测源行（``derived`` 不进面板），换算结果在
消息文字里；缺席清单（含 RUB/CHF/CAD/AUD 四枚待验）在卡面与纯文本同读
``fx_missing_note``，不从任何一个面静默消失。

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

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    CapabilityResult,
    IncomingMessage,
    PrivacyLevel,
    RiskLevel,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy
from plugins.bot_unified_runtime.domains.render.bot_avatar import bot_avatar_uri

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
# 席位 F1（2026-10-02）补 ``(增|追)加元素``：新收币名「加元」是「增加元素」的
# 子串，「把间距增加元素换算一下」会因此被劫持成汇率面板。沿用既有 话术/积分
# 的整句让路形态（同一条腿，不起第二把尺）。
_FX_NON_HINT_RE = re.compile(r"(话术|积分|話術|積分)|(?:增加|追加)元素")
_STOCK_GUARD_RE = re.compile(r"(股价|股票|股價|股指|大盘|大盤|基金|房价)")


def is_fx_command(text: str) -> bool:
    """汇率触发判定：短文本、无链接、命中汇率意图且不撞股票语境。"""
    from plugins.bot_unified_runtime.domains.finance.data.fx_data import (
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
    rates: list[Any],
    missing_note: str,
    *,
    focus_label: str | None = None,
    missing_sub: str = "上游无该货币对行情",
) -> dict[str, Any]:
    """组装 finance_card（render_finance_card_html）payload（汇率面板块）。

    缺数据行明确展示「暂无数据」（含无源货币对与待验候选币），绝不伪造 0 汇率；
    汇率无可用日 K → 每行 trend_note 诚实标注，不伪造走势。

    ``missing_sub``（2026-10-02 席位 F1）：那行的口径副标题。缺席原因现在分三类
    （实测查无 / 候选待验 / 本轮缺行），副标题不许再一口咬定「上游无该货币对行情」
    ——把没探过的说成查无＝另一种编数。缺省值保持旧文案，既有调用方零改动。

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
                "sub": missing_sub,
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
            from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
                prune_prefixed,
            )
            from plugins.bot_unified_runtime.domains.render.card_render.bridge import (
                render_finance_card_html,
            )

            payload = dict(payload)
            # P-G3 第二波（2026-09-29）：卡面署名走自称唯一读法（人格册→兼容显示名），
            # 不再自取配置名并手抄品牌字面量；空串交胶囊统一回落（契约锁
            # tests/test_rendering_contract.py：RenderPayload().bot_name == ""）。
            from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
                active_persona_id,
                current_bot_nickname,
            )

            payload["bot_name"] = current_bot_nickname(
                active_persona_id(config), config=config
            )
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
        from plugins.bot_unified_runtime.domains.finance.data.fx_data import (
            fetch_fx_rates,
            format_fx_brief,
            format_fx_rate_line,
            fx_derived_quote,
            fx_missing_note,
            fx_missing_sub,
            fx_no_quote_reason,
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
        # 缺席说明算一次给文本面板与卡面共用（三态名册 + 本轮缺行）。
        missing_note = fx_missing_note(rates)
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
                # 直盘/反向都没有 → 先试 USD 三角换算（两条实测现货腿都在本轮里
                # 才算数，缺任一腿即 None）。这条通路是 fx_data 头注从一开始就
                # 承诺、2026-10-02 之前从未接进能力层的交叉价，接通后
                # 「英镑汇率/韩元汇率/新加坡元汇率」不再答非所问。
                derived = fx_derived_quote(rates, base, quote)
                if derived is None:
                    # 换不出来就明写换不出来，并点名「为什么」：实测查无 /
                    # 候选源待真机核实 / 未登记源，三种话各不相同。
                    body = (
                        f"{base}/{quote} 暂无数据（{fx_no_quote_reason(base, quote)}），"
                        "先不瞎猜数字。"
                    )
                    audit_extra = "fx:pair_unavailable"
                else:
                    derived_rate, derivation_note = derived
                    body = (
                        f"{format_fx_rate_line(derived_rate, amount)}\n"
                        f"1 {base} = {derived_rate.rate:.6g} {quote}\n"
                        f"{derivation_note}"
                    )
                    title = f"{base}兑{quote}"
                    audit_extra = f"fx:cross:{base}/{quote}"
                    focus_label = f"{base}兑{quote}"
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
            body = format_fx_brief(rates, missing_note)

        semantic_key = "panel"
        if focus_label:
            semantic_key = f"pair:{focus_label}"
        payload = build_fx_card_payload(
            rates,
            missing_note,
            focus_label=focus_label or None,
            missing_sub=fx_missing_sub(rates),
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
