# 好感度与心情 · 心情双轴与回归

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.affinity-mood · 心情双轴与回归

- 层级：一级 B03 → 二级 affinity-mood → 三级 `mood-axes`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/mood.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

她自己此刻的情绪，分钟到小时尺度，两个轴：**valence**（愉悦度，决定暖不暖）与
**arousal**（唤醒度，决定 lively 还是慵懒）。每次互动都会小幅推动，然后按半衰期
向基线自然回归——不靠「重置」，靠衰减，所以跨重启的表现也连续。产出两样东西：
一句纯自然语言的心情描述（进 prompt【当前心情】分区）和一个乘性意愿系数
（调她接话的概率与预算，**绝不做硬开关**）。

## 怎么调用

- 真身：`domains/chat_reply/character/mood.py:BotMoodStore`，
  方法 `snapshot(now=None)` → `BotMood`、`apply_event(...)`（钳位 + 速率帽）、
  `observe_interaction(...)`（把行为标签与情绪标签映射成小幅增量后交给 apply_event）、
  `describe(mood)`（**无数字**的自然语言描述）、`willingness_factor(mood)`（乘性系数）。
- 情绪标签来源：`domains/chat_reply/character/emotion.py:build_emotion_provider`（规则式
  `RuleBasedEmotionProvider`，识别 support_needed / lonely / frustrated /
  help_seeking / low_energy 等），与行为标签 `classify_behavior` 同池喂给心情。
- 消费方：`character/providers.py:build_character_context_provider` 把 `describe` 结果
  放进 `ContextBundle.mood_description`；主动搭话概率与表情档位读取
  `willingness_factor`（准入门与限流在 B02 的 `domains/chat_reply/policy/gate.py`，本层不做门）。
- 心情还反哺好感：`character/affinity.py:state_factor_from_valence` 读取当前 valence
  作为调制因子——是**乘性调制**，不是「心情差就扣分」。

## 开关与参数

`bot_mood_enabled`（缺省 True）、`bot_mood_db_path`（路径键，经 runtime_paths 重映射）、
`bot_mood_half_life_minutes`（回归速度）、`bot_mood_baseline_arousal`（基线）、
`bot_mood_rate_cap_per_hour`（任意一小时窗口内已施加的 valence 增量绝对值之和上限）。
缺省数值以 `config.py` 与 `docs/config-catalog-full.md` 为准，本文不复述（改一行配置
就会过期的数字不写进叙述文档，规则见 `AGENTS.md` 第一部分的计数指针条款）。
超帽的处理是**截断而不是整次拒绝**：本次实际施加量 = 剩余额度，只对 valence 记账
（arousal 单项增量本身很小，无围攻放大效应，不占额度）。

## 失败时看到什么

- 库不可用 / 读失败：按基线心情出（中性温和），消息链不受影响；写失败记一行日志。
- 长期无人读：下次读写会按持久化的 `updated_at` 重算衰减（write-back），
  所以「重启后心情突变」不属于本设计——观测到突变即为缺陷。
- 事件风暴（被连续辱骂、群内刷屏）：速率帽截断累计影响，她只会「明显低落但仍在」，
  不会掉进极端值，也不会因此不回复。
- 低落时的表现受红线约束：**任何档位都不攻击、不强硬**，心情差只会让她更安静、
  更省字，绝不变成冷暴力弃聊或回敬（与好感度红线同源，见
  [态度文案与红线场景](affinity-copy.md)）。
- 速率帽的窗口记账在进程内，重启即清零：重启后第一个窗口不受重启前事件约束，
  这是记录在案的折衷（衰减与钳位仍在兜底）。

## 测试与验收

`tests/test_mood.py`（半衰回归、钳位、速率帽截断与窗口、describe 无数字、
willingness_factor 值域、跨重启一致性）、`tests/test_forward_and_mood.py`
（转发/群聊事件对心情的影响口径）、`tests/test_rate_limit_silent_and_chat_forward.py`
（低落时的门与静默语义）。
真机：连续输入若干负面消息后查 `/bot status`（心情信息在 status 内，无顶层 health 子命令），
核对 valence 下探但被帽住、一段时间后自行回基线；同时确认回复语气变淡但**没有**攻击性。
