"""宿主机状态卡的**落图口**（需求 5 呈现腿；2026-09-26 二段收敛后不再是拼装器）。

只**落图**、不取数、不自拼 payload：

- 取数一律来自 ``host_status.collect_host_snapshot``（呈现适配器）或
  ``host_metrics.collect_host_metrics*``（真身，走能力入口那条缝）；
- 「读数→通用卡 payload」的拼装今天**只住一处**：
  ``host_metrics.assemble_card_payload``（2026-09-26 二段收敛——本文件旧版里
  那份同名后缀循环 + 「取样时刻」前缀的逐行同构副本已删，留两份必然漂两份）；
  本文件的 ``build_host_card_payload`` 降为**薄调用方**：只喂旧「缺行语义」
  分组形状与旧文案（标题「这台机器现在什么样」、旧分组导语），逐字节输出
  与收敛前一致（锁在 tests/test_host_status.py ⑦ 组 + 本席 tests/test_host_state_card.py 的等值锁）。
- 出图一律走 ``error_report.render_html_card``（与诊断卡同一条落盘路，不抄第二份），
  排版一律走通用卡 ``render_universal_card_html``——**零新模板**，因此
  渲染契约的模板清单与样张字节基线都不受影响（AGENTS 第三部分那条铁律）。

为什么走通用卡的 ``stats``：这张卡的内容本质就是「属性名 + 属性值」成对表，
通用卡的 stats 区正是这一形态——两侧各自对齐由模板负责，本模块负责
**把 payload 送进唯一的落图口**，不负责画格子。格子画第二份就是第二真身。
"""

from __future__ import annotations

import hashlib
from typing import Any

HOST_CARD_TITLE = "这台机器现在什么样"
HOST_CARD_BADGE = "超管视图"

# 分组标题→卡上小节的说明行：把「这组数是什么」写成人话，而不是留着
# 「硬件 / 占用 / 系统与运行时」三个光秃秃的分类名让人自己猜。
# 这是**旧 `/bot status` 卡面的文案**（与 host_metrics.GROUP_LEADS 是两套字面、
# 各自服务各自的卡面措辞）；拼装逻辑不再各抄一份，只喂给同一个拼装器。
GROUP_LEADS: dict[str, str] = {
    "硬件": "配置（开机时自检到的那套）",
    "占用": "此刻用量（现取，没有缓存）",
    "系统与运行时": "软件与版本",
}


def build_host_card_payload(
    groups: dict[str, list[tuple[str, str]]],
    *,
    taken_at: str = "",
) -> dict[str, Any]:
    """把分组读数拼成通用卡 payload；空组自动不出现在文案里。

    委托 :func:`host_metrics.assemble_card_payload`——全仓唯一那份「同名属性
    加序号后缀 + 取样时刻前缀」的拼装逻辑住在那里，本函数只负责把旧
    ``{分组: [(标签, 值)]}`` 形状摊平喂进去，并保留本卡面的标题与导语字面。
    """
    from plugins.bot_unified_runtime.domains.ops import host_metrics as _metrics

    rows = [
        (group, label, value)
        for group, items in groups.items()
        for label, value in items
    ]
    return _metrics.assemble_card_payload(
        rows,
        group_order=list(groups),
        group_leads=GROUP_LEADS,
        title=HOST_CARD_TITLE,
        badge=HOST_CARD_BADGE,
        feature_label="宿主机状态",
        taken_at=taken_at,
    )


def host_card_digest(payload: dict[str, Any]) -> str:
    """稳定文件名摘要：同一份读数重复出图覆盖同一文件，不喂爆卡片目录。"""
    material = "|".join(f"{k}={v}" for k, v in sorted((payload.get("stats") or {}).items()))
    material += f"||{payload.get('summary') or ''}"
    return hashlib.sha1(material.encode("utf-8", "ignore")).hexdigest()[:12]


def render_payload_png(
    payload: dict[str, Any],
    *,
    backend: Any = None,
    card_dir: str | None = None,
) -> str:
    """payload 级落图口：成功回 PNG 路径，任何一步不行就回空串（调用方降级纯文本）。

    宿主机卡的**每一条出图路**（旧 ``render_host_card_png`` 与能力入口
    ``capabilities/host_state.py``）都从这一个函数走——渲染链路上不许有第二份
    ``render_universal_card_html`` + ``render_html_card`` 的手抄。
    """
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor.error_report import (
            render_html_card,
        )
        from plugins.bot_unified_runtime.output.card_render.bridge import (
            render_universal_card_html,
        )

        return render_html_card(
            render_universal_card_html(payload),
            stem="host",
            digest=host_card_digest(payload),
            backend=backend,
            card_dir=card_dir,
            keep=60,
        )
    except Exception:  # noqa: BLE001 - 出图失败交回空串，由调用方走纯文本报数。
        return ""


def render_host_card_png(
    groups: dict[str, list[tuple[str, str]]],
    *,
    taken_at: str = "",
    backend: Any = None,
    card_dir: str | None = None,
) -> str:
    """旧分组形状的出图入口（echo ``/bot status`` 附块在吃，签名与行为原样保住）。

    读数全空时**不出图**——一张空白卡比不出卡更像谎报。
    """
    if not any(groups.values()):
        return ""
    try:
        payload = build_host_card_payload(groups, taken_at=taken_at)
    except Exception:  # noqa: BLE001 - 与收敛前同口径：任何一步不行都回空串。
        return ""
    return render_payload_png(
        payload,
        backend=backend,
        card_dir=card_dir,
    )


__all__ = [
    "GROUP_LEADS",
    "HOST_CARD_BADGE",
    "HOST_CARD_TITLE",
    "build_host_card_payload",
    "host_card_digest",
    "render_host_card_png",
    "render_payload_png",
]
