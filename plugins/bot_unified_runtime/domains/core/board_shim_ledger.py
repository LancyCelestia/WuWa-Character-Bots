"""垫片「待退役」第二本账（声明源 · 与 `G_P2_EXEMPT` 并列 · 解 P-16 A 案）。

本文件由 `scripts/shim_retirement_census.py --write-ledger` 现算生成，**请勿手改**：
- 每枚 `path` 是域外垫片，`canonical`（真身）与 `refs`（引用方数上限）均由 AST/grep 现算，
  **禁手抄真身路径**（改指针 = 让 `--check` 与门的 ③④⑤ 当场红）。
- 退役一枚垫片（迁完调用方后删除）⇒ 重跑 `--write-ledger`，`SHIM_RETIRE_BASELINE` 只准降。
- 逐枚 `refs` 上限同样**只准降**（`--write-ledger` 默认 `min(既有, 现算)`，抬不动它）：
  想上调某枚上限，唯一通道是 `scripts/shim_refs_approvals.json` 里的显式审批
  （`{path, approved_by, reason, expiry}`，过期自动失效）；无审批 ⇒ 上限不动、`refs_over_ceiling` 继续红。
  这把「删滞后行（正当进展）」与「抬上限（糊红）」拆开，见 S147 机制缺口 / S155。
- `SHIM_ROWS` 必须是纯字面量元组（取数口用 `ast.literal_eval` 读，任何计算/调用都拒读）。
- 方向锁是**加数不是加项**（P-22）：硬锁 = `UNLANDED_SUM_BASELINE`（待搬迁＋待退役）与
  `OUTSIDE_BASELINE`（三态之和）；单态基线只作耦合算术参照，某态上升须另一态等额或更多下降。
  四枚基线一律只准降，`--write-ledger` 也抬不动它们。

口径、判据、三态定义全在算口 `scripts/shim_retirement_census.py` 顶注与 `PARKED.md` P-16/P-22。
"""

from __future__ import annotations

#: 每条 = (垫片 path, 真身 path, 引用方数上限)。字段顺序即契约，勿加派生表达式。
SHIM_ROWS: tuple[tuple[str, str, int], ...] = (
    ("plugins/bot_unified_runtime/capabilities/auto_send/__init__.py",
     "plugins/bot_unified_runtime/domains/schedule/auto_send/__init__.py",
     0),
    ("plugins/bot_unified_runtime/capabilities/chat.py",
     "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
     0),
    ("plugins/bot_unified_runtime/capabilities/content_parser.py",
     "plugins/bot_unified_runtime/domains/link_parse/capabilities/content_parser.py",
     1),
    ("plugins/bot_unified_runtime/capabilities/market.py",
     "plugins/bot_unified_runtime/domains/finance/capabilities/market.py",
     0),
    ("plugins/bot_unified_runtime/character/providers.py",
     "plugins/bot_unified_runtime/domains/chat_reply/character/providers.py",
     4),
    ("plugins/bot_unified_runtime/llm/model_router.py",
     "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py",
     5),
    ("plugins/bot_unified_runtime/message_context.py",
     "plugins/bot_unified_runtime/domains/chat_reply/ingest/message_context.py",
     6),
    ("plugins/bot_unified_runtime/output/plain_text.py",
     "plugins/bot_unified_runtime/domains/render/plain_text.py",
     7),
    ("plugins/bot_unified_runtime/output/renderer.py",
     "plugins/bot_unified_runtime/domains/render/renderer.py",
     6),
    ("plugins/bot_unified_runtime/output/reviewer.py",
     "plugins/bot_unified_runtime/domains/render/reviewer.py",
     2),
    ("plugins/bot_unified_runtime/output/roleplay.py",
     "plugins/bot_unified_runtime/domains/render/roleplay.py",
     3),
    ("plugins/bot_unified_runtime/policy/__init__.py",
     "plugins/bot_unified_runtime/domains/chat_reply/policy/__init__.py",
     1),
    ("plugins/bot_unified_runtime/runtime/content_route.py",
     "plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py",
     1),
    ("plugins/bot_unified_runtime/runtime/pipeline.py",
     "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py",
     2),
    ("plugins/bot_unified_runtime/runtime/pricing.py",
     "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/pricing.py",
     2),
    ("plugins/bot_unified_runtime/runtime/settings.py",
     "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py",
     0),
    ("plugins/bot_unified_runtime/security/memory_sanitize.py",
     "plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py",
     0),
    ("plugins/bot_unified_runtime/sender/__init__.py",
     "plugins/bot_unified_runtime/domains/transport/sender/__init__.py",
     0),
    ("plugins/bot_unified_runtime/sender/onebot.py",
     "plugins/bot_unified_runtime/domains/transport/sender/onebot.py",
     0),
    ("plugins/bot_unified_runtime/sources/fetchers/__init__.py",
     "plugins/bot_unified_runtime/domains/link_parse/fetchers/__init__.py",
     0),
    ("plugins/bot_unified_runtime/sources/parsers/__init__.py",
     "plugins/bot_unified_runtime/domains/link_parse/parsers/__init__.py",
     1),
    ("plugins/bot_unified_runtime/sources/registry.py",
     "plugins/bot_unified_runtime/domains/link_parse/support/registry.py",
     4),
    ("plugins/bot_unified_runtime/sources/subscriptions/__init__.py",
     "plugins/bot_unified_runtime/domains/subscribe/adapters/__init__.py",
     0),
)

#: 待退役(垫片) 现算快照参照点（手写字面量 · 只准降；上升仅在待搬迁等额或更多下降时可放行）。
SHIM_RETIRE_BASELINE = 23
#: 待搬迁 现算快照参照点（手写字面量 · 只准降；上升仅在待退役等额或更多下降时可放行）。
RELOCATE_BASELINE = 45
#: 【硬锁】域外未落地总量 = 待搬迁＋待退役 之和（手写字面量 · 单调下降，锁加数不锁加项）。
UNLANDED_SUM_BASELINE = 68
#: 【硬锁】三态之和 = 域外全量（手写字面量 · 单调下降；正当认领只改分配不改全量）。
OUTSIDE_BASELINE = 74
