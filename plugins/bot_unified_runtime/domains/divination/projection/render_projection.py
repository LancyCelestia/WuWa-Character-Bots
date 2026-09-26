"""V2.1 S12 占卜结果 → 既有渲染管线投影（卡片模板零改动）。

合同来源：backend-v2-product-extensions.md §3（「卡片渲染 8s 预算，失败保留
牌面纯文本」）+ 验收矩阵 V21-DIVINATION-002（渲染回退）。

- 消费面完全复用既有链：``capabilities/divination.build_divination_card_content``
  （通用卡 payload 纯构造）→ ``capabilities.content_parser.render_card_png``
  （playwright 渲染后端）。本模块**不改任何模板/bridge/token**，只做结果→
  (标题, 正文, payload) 的形状翻译。
- 回退契约：渲染后端缺失/不可用/任何异常 → ``(空串, 纯文本)``——调用方拿
  空串就走纯文本路径（与聊天面 ``_render_card`` 失败回退同一契约）。
- 守岸人语气：解读未接线的提示走话术池（3 变体，draw_id 确定性轮换），
  娱乐口径照抄服务层 ``DISCLAIMER_TEXT``，不另造第二套声明。
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    DISCLAIMER_TEXT,
    DrawResult,
)

__all__ = [
    "INTERPRETATION_PENDING_LINES",
    "DrawRenderProjection",
    "build_draw_projection",
    "build_tarot_title",
    "pick_pending_line",
    "render_draw_card",
]

# 话术池形态（参照五池话术惯例：多变体 + 稳定轮换，不僵硬复读）。
INTERPRETATION_PENDING_LINES: tuple[str, ...] = (
    "牌面信息先放在这里啦——人格化的解读还没接上模型线，等接好了我用我自己的话讲给你听。",
    "本地解读就是从牌面直接来的，不会骗你；人格化解读那边还没接线，我不替模型编话。",
    "牌面已经摆好了，人格化解读的线还没牵过来——先看牌面本身，也够品一会儿的。",
)


def pick_pending_line(draw_id: str) -> str:
    """话术池确定性轮换：同 draw_id 恒同变体（无随机、无状态）。"""
    if not INTERPRETATION_PENDING_LINES:  # pragma: no cover - 常量非空
        return ""
    digest = hashlib.sha256(str(draw_id).encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(INTERPRETATION_PENDING_LINES)
    return INTERPRETATION_PENDING_LINES[index]


_SPREAD_TITLES: dict[str, str] = {
    "single": "塔罗 · 单牌",
    "past_present_future": "塔罗 · 过去现在未来",
    "celtic_cross": "塔罗 · 凯尔特十字",
}


def build_tarot_title(spread_id: str) -> str:
    """阵型 → 卡标题；未知阵型不猜，回退通用标题。"""
    return _SPREAD_TITLES.get(str(spread_id or ""), "塔罗")


@dataclass(frozen=True)
class DrawRenderProjection:
    """一次抽取的渲染投影（卡片与纯文本共用同一正文，不造两套事实）。"""

    kind: str
    title: str
    body_text: str
    plain_text: str
    card_payload: Any
    disclaimer_text: str

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.body_text.splitlines())


def build_draw_projection(result: DrawResult) -> DrawRenderProjection:
    """DrawResult → 渲染投影：标题按类别/阵型，正文=服务层解读行原文。

    正文只承载服务层 ``interpretation_lines``（本地确定性解读 + 娱乐声明），
    不在投影层追加任何"预测性"文案；空解读行（理论不可达）回退牌面清单。
    """
    kind = str(result.kind)
    lines = [str(line) for line in result.interpretation_lines if str(line)]
    if not lines:  # pragma: no cover - 服务层恒附带解读行与声明
        if kind == "fortune":
            lines = [f"今日运势：{result.fortune_grade}。"]
        else:
            lines = [
                f"{card.get('card_id', '?')}（{card.get('orientation', 'upright')}）"
                for card in result.cards
            ]
        lines.append(DISCLAIMER_TEXT)
    title = (
        "今日运势" if kind == "fortune" else build_tarot_title(_spread_of(result))
    )
    body_text = "\n".join(lines)
    card_kind = "tarot" if kind == "tarot" else kind
    return DrawRenderProjection(
        kind=kind,
        title=title,
        body_text=body_text,
        plain_text=body_text,
        card_payload=_build_card_payload(card_kind, title, body_text),
        disclaimer_text=DISCLAIMER_TEXT,
    )


def _spread_of(result: DrawResult) -> str:
    """从牌面位置反推阵型（DrawResult 未直排 spread_id；位置序唯一对应）。"""
    if not result.cards:
        return ""
    positions = tuple(card.get("position_id", "") for card in result.cards)
    from plugins.bot_unified_runtime.domains.divination.service.tarot_draw import (
        SPREADS,
    )

    for spread_id, (_count, positions_of) in SPREADS.items():
        if positions == positions_of[: len(positions)]:
            return spread_id
    return ""


def _build_card_payload(kind: str, title: str, body: str) -> Any:
    """通用卡 payload（纯构造，无 IO）；构造失败不阻塞纯文本路径。"""
    try:
        from plugins.bot_unified_runtime.domains.divination.capabilities.divination import (
            build_divination_card_content,
        )

        return build_divination_card_content(kind, title, body)
    except Exception:  # noqa: BLE001 - payload 缺失时走纯文本，不冒充出图。
        return None


def _card_dir_token(raw: str) -> str:
    """去重键 → 安全目录名（与聊天面 _card_dir_token 同一消毒口径）。"""
    token = re.sub(r"[^0-9A-Za-z_-]", "", str(raw or ""))[:64]
    return token or uuid.uuid4().hex[:12]


def _default_card_renderer(
    render_backend: Any, item: Any, *, config: Any, card_dir: str
) -> dict[str, Any] | None:
    """既有 renderer 消费面（惰性导入，控制面无需常驻渲染依赖）。"""
    from plugins.bot_unified_runtime.domains.link_parse.capabilities.content_parser import (
        render_card_png,
    )

    payload = render_card_png(
        render_backend,
        item,
        config=config,
        card_dir=card_dir,
        feature_label="占卜",
    )
    return payload if isinstance(payload, dict) else None


def render_draw_card(
    projection: DrawRenderProjection,
    render_backend: Any | None,
    config: Any | None,
    *,
    dedupe_key: str,
    card_renderer: Any | None = None,
) -> tuple[str, str]:
    """占卜投影 → 卡图；返回 ``(卡文件路径, 纯文本)``。

    - 后端缺失/不可用/任何异常 → ``("", 纯文本)``：既有"渲染失败保留牌面
      纯文本"契约，绝不抛出阻断响应。
    - ``dedupe_key``（draw_id）只进落盘子目录（每抽唯一），与聊天面
      ``_render_card`` 口径一致，不进 canonical_url。
    - ``card_renderer`` 注入点：测试用假后端直验消费面，无需 playwright。
    """
    plain_text = projection.plain_text
    if render_backend is None or not getattr(render_backend, "available", False):
        return "", plain_text
    if projection.card_payload is None:
        return "", plain_text
    renderer = card_renderer or _default_card_renderer
    try:
        base_dir = str(
            getattr(config, "bot_card_render_dir", "data/cards") or "data/cards"
        )
        card_dir = str(
            Path(base_dir) / "divination" / _card_dir_token(dedupe_key)
        )
        payload = renderer(
            render_backend,
            projection.card_payload,
            config=config,
            card_dir=card_dir,
        )
        file_path = str(payload.get("file") or "") if payload else ""
        return file_path, plain_text
    except Exception:  # noqa: BLE001 - 渲染失败回退纯文本（既有契约）。
        return "", plain_text
