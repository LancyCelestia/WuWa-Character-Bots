# 人格对话与回复 · 戳一戳互动五件套

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.chat-reply · 戳一戳互动五件套

- 层级：一级 B03 → 二级 chat-reply → 三级 `poke-interaction`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

被「戳一戳」时怎么回应。五件套（2026-09-16 用户裁定）：①是否回戳、②回什么话术、
③用什么形态回（固定话术 / LLM 现写 / 表情包，三选一）、④群里要不要 @ 回戳的人、
⑤好感度上的一记小额正向。它不占路由席位（是 B01 归一后的被动 notice 事件），
所有适配器先把各自的通知归一成 `PokeEvent` 再进同一个决策口，所以 Telegram/邮件
将来接 poke 不需要重写这套判断。

## 怎么调用

统一决策入口在 `capabilities/poke.py`（模块不导入 NoneBot，可离线单测）：

- `PokeEvent.from_notice(event, bot_id)` ——适配器事件归一；
- `PokeLimiter.accept(event, bot_id, enabled, cooldown, group_cooldown, probability)`
  ——五道门里的开关 + 单人冷却 + 群内冷却 + 确定性概率门（哈希分桶，同戳同果），
  决策表有容量上限防长跑泄漏；
- `resolve_poke_reply_mode(configured=..., group=..., sender=..., bucket=...)` ——
  形态决策：显式配置（`fixed`/`llm`/`meme`）直用，`mix` 走 SHA-256 哈希三选一；
- `resolve_poke_reply(mode, fixed_text=..., llm_text=..., meme_path=...)` ——回退链
  的唯一出口：LLM 失败或空 → fixed；表情库选不出 → fixed；meme 成功时只发图不叠字；
- `PokeDispatcher.build_poke_reaction(...)` ——产出 `PokeReaction`
  （`reply`/`poke_back`/`group`/`mode`/`audit_tags`），`reply` 恒为 fixed 文本供兜底，
  实际表达由调用方按 `mode` 组装；
- `build_poke_text(group=..., nickname=...)` ——内置默认话术（配置文本为空时用）。
- 群内 @ 戳者走呈现契约字段 `CapabilityResult.prefix_parts`
  （定义在 `domains/core/contracts/runtime.py`，由 B08 的 renderer/reviewer 前置消费），
  本域不自拼 @ 段、也不直调发送。
- 好感度正向经 `character/affinity.py` 的 observe 通道（`delta_override` 权威信号路径），
  喂给模型的态度说明只作定性描述，不在正文外显数值（展示纪律，见
  [态度文案与红线场景](../affinity-mood/affinity-copy.md)）。

## 开关与参数

`bot_poke_enabled`（总闸）、`bot_poke_private_cooldown_seconds`、
`bot_poke_group_cooldown_seconds`、`bot_poke_probability`（缺省 1.0=每次必应）、
`bot_poke_admin_bypass`（管理员是否绕过冷却/概率）、`bot_poke_reply_enabled`（是否回话术）、
`bot_poke_poke_back`（是否回戳，缺省开）、`bot_poke_group_text` / `bot_poke_private_text`
（自定义话术，空=内置默认）、`bot_poke_reply_mode`（缺省 `mix`）、
`bot_poke_affinity_enabled` / `bot_poke_affinity_delta` / `bot_poke_affinity_daily_max`
（好感正向与每人每日累计上限，缺省数值以 `config.py` 与 catalog 为准，不在本文复述）。
另有 B02 登记的同人点名最小间隔（R3，仅在她被 @ 的形态生效）与主动贴表情的独立门。
热改性：以上为装配期读取的 `bot_*` 字段，改 `.env` 后须重启（铁律）。

## 失败时看到什么

- LLM 话术失败/为空、表情包库选不出：**回退固定话术**，用户只会看到一条正常回复，
  不会有「半成品」（回复只回一个是硬约束）。
- 回戳 API 失败（平台不支持或私聊无该通道）：静默，只保留话术；不重试刷屏。
- 门未过（冷却/概率/总闸关）：什么都不发，也不留「我选择不回」的痕迹。
- 事件归一失败（未知适配器形态）：`from_notice` 返回 None，整条链路不启动。
- 分发器内部异常：fail-open，退回内置默认话术 + 审计标记，绝不抛出到消息链。

## 测试与验收

`tests/test_poke_v2.py`（五件套：形态决策确定性、回退链、@ 前置、好感正向与每日上限）、
`tests/test_poke_unified_reaction_b10.py`（适配器中立与统一分发）、
`tests/test_poke_notice_ingest.py`（B01 侧 notice 归一）。
真机：`docs/acceptance-manual.md` §6.6.7（戳一戳 v2 段）——群里被 @ 后连戳数下，
核对回戳与话术不同时刷屏、同一个人重复戳被冷却吃掉、表情形态命中时只发图。
