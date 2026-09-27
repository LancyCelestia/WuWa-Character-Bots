# 自动发送与主动搭话 · 表情回应的五层防刷屏门

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.auto-send · 表情回应的五层防刷屏门

- 层级：一级 B07 → 二级 auto-send → 三级 `sticker-reactions`
- 实现落点：—
<!-- BOARD-AUTO:END -->

## 这个入口做什么

表情贴纸回应机制件（不占路由席位）：一是**识别归一**——把 QQ(SnowLuma) 群消息贴纸回应等 notice 归一成统一事件、进会话级环形缓冲，供人格上下文注入【表情回应】分区（空则整块不出现）；二是**主动贴表情**——在合适时机替她给用户这条消息贴一个表情（`set_msg_emoji_like`）。核心是把"想贴就贴"关进五层防刷屏门。

## 怎么调用

真身 `domains/meme/reactions/engine.py`（贴纸回应入口模块 是再导出垫片）。编排入口 `maybe_react_on_message`（触发 `emotion_signal` 情绪命中 / `after_reply` 刚回复完），门控收敛在 `ProactiveGate.allow`。识别侧 `ReactionBuffer` 与 `describe_chat_reactions`（人格注入用）；聚合统计双写 `domains/meme/sources/reaction_store.py`。事件在根 `__init__.py` 摄取层归一后喂入。

## 开关与参数

**五层门（顺序）**：①总闸 `bot_reactions_enabled` → ②每消息去重（同一消息跨触发只骰一次）→ ③确定性概率 `bot_reactions_probability` → ④会话冷却 `bot_reactions_cooldown_seconds` → ⑤每小时滑窗限额 `bot_reactions_max_per_hour`。第二层"情绪命中发图"另有 `bot_reactions_meme_*` 四键 + 悲伤场景整条不贴。存储 `bot_reactions_db_path`、保留 `bot_reactions_store_days`。配置键逐键以 `docs/config-catalog-full.md` 为准。

关键红线：**主动贴表情只支持群消息，私聊一律不派发**。QQ 侧本就没有私聊表情回应通道（OIDB 0x9082 仅群消息形态），**非迁移退化**——SnowLuma 对非群消息直接抛 `emoji reactions are not supported on private messages`（实跑命中次数以该轮取证为准）。守卫落在 `maybe_react_on_message` 的 enabled/mid 判定之后、五层门之前，按 `_is_group_session`（委托 `domains/core/session_keys.py`，真实键 `group_<gid>_<uid>`）拒掉私聊，因此私聊既不派发、也不占每消息去重登记、不刷失败日志。

## 失败时看到什么

`set_msg_emoji_like` 抛错 → 只 `reaction failed` 一行 debug、静默，绝不影响正常回复；概率/冷却/限额任一没过 → 直接不贴、无日志。`emotion_signal` 触发要求 `bot_related=True`（群内仅在与她相关的对话贴），未判定（None）一律不介入第三方对话；`after_reply` 遇悲伤/低落词族整条不贴（防止安慰完转头贴笑脸）。

## 测试与验收

`tests/test_reactions.py`（五层门、私聊永不派发守卫 `test_private_session_never_calls_set_msg_emoji_like`、悲伤门）、`tests/test_reaction_store.py`（幂等合并与聚合统计）；真机验收见 `docs/acceptance-manual.md` §6.6.6。
