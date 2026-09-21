# 好感度与心情 · 分数模型与档位

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.affinity-mood · 分数模型与档位

- 层级：一级 B03 → 二级 affinity-mood → 三级 `affinity-model`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py`、`plugins/bot_unified_runtime/domains/chat_reply/character/mood.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

印象的更新机制（无用户直接入口，被消息链与其他能力调用）。当前代码里并存三层：
v4/v5 的线性多因素步长、v6 的平滑层（饱和带 + 同日边际递减 + 滚动预算帽）、
v7 的潜变量层（无界 `z`，展示值 `a = tanh(z)`，因此**结构上永远到不了头**，
高处自然放缓）。三层共用同一套八档口径、同一条红线、同一套护栏。
**灰度现状：`bot_affinity_v7_enabled` 缺省 False ⇒ 线上生效的是 v4/v5/v6 路径，
v7 代码与行为锁都已在但未启用，开启属用户裁决 + 重启。**
具体步长/权重数值不在本文复述：算法说明只定性是用户裁定的展示纪律，
数值规范唯一权威是 `docs/design/affinity-v7-design.md`（v7）与
`docs/affinity-design.md`（v4/v5/v6 历史与回退态）。

## 怎么调用

真身 `domains/chat_reply/character/affinity.py`：

- 写侧：`DynamicAffinityStore.observe(...)` / `observe_points(...)` ——
  收行为标签或权威 `delta_override`，内部完成幂等（`source_event_id`）、
  交互级冷却、每日上限、滚动预算与钳制；
- 归类：`classify_behavior(text, safety_category=..., safety_action=...)` ——
  与内容安全同源（被守界/拒答不判负面），`score_relationship_signal` 是它的记分上游；
- v5/v6 因子：`pleasantness_factor`、`companionship_factor`、`first_impression_factor`、
  `state_factor_from_valence`、`per_user_factor`（个人系数，确定性恒定）、
  `saturation_factor`、`repeat_decay_factor`、`effective_delta`（合成出口）；
- v7 因子：`v7_quality_score`（主动/延展/情绪/尊重/回应五子信号）、`v7_novelty_factor`
  （跨日不重置的新鲜度，按 τ 半衰回升）、`v7_rhythm_factor`（按本人活跃水位归一）、
  `v7_raw_delta_z`、`v7_z_to_display_fraction` / `v7_display_fraction_to_z`、
  `resolve_v7_settings(config)` → `V7Settings`（**逐调用现读**，非法值回退代码缺省
  并每键每进程点名一次）；
- 读侧：`snapshot`、`factor_profile`、`sentiment_for`、`leaderboard`、
  `learn_profile`、`set_nickname`；
- 档位与红线：`tier_for_affinity`、`tier_name_for_affinity`、
  `linear_transition_for_affinity`（八档**连续过渡、门槛不生硬跳变**）、
  `attitude_for_affinity`（注入用全文，含 `_TIER_RED_LINES` 四条款）；
- 存量：`normalize_legacy_points`（旧内部值口径换算）、`z_latent`/`v7_state` 列走
  ALTER-if-missing 自动迁移，首次 v7 写入时由现有分惰性推导，**绝不重置任何人**；
  未触及行逐字不动，`source='v7'` 行以 z 记账并被 v5 分口径的预算查询排除；
  账本重放与补偿在 `affinity_replay.py`（`run_replay`、`build_compensation_proposals`）。
- 会话/用户键一律经 `domains/core/session_keys.py`；预算不变式由
  `ensure_budget_invariants` 守住。

## 开关与参数

总闸 `bot_affinity_enabled`；库位 `bot_affinity_db_path`。
v7 十二枚键（`bot_affinity_v7_enabled` + `bot_affinity_base_step`、`_novelty_ratio`、
`_novelty_halo_days`、`_rhythm_reference_turns`、`_negative_event_cap_z`、
`_daily_move_cap_z`、`_fuse_daily_events`、`_repair_gain`、`_z_hard_bound`、
`_quality_weights`、`_decay_tau_days`）：缺省值以 `config.py` 与
`docs/config-catalog-full.md` 为准，**本轮刻意未进 `SETTABLE_KEYS`**（热改口径待裁决），
改 `.env` 需重启。
v5/v6 路径无独立键，靠模块常量表（单一事实源在 affinity.py 顶部，注释指向设计文档）。
被动回归（闲置衰减）由政策常量 `_PASSIVE_DECAY_ENABLED=False` 关闭——
**缺席不扣分**是策略不是 bug。

## 失败时看到什么

- 库不可用 / 行损坏：读侧退到基准印象，写侧记一行日志并跳过本次计分
  （宁可漏记一次，不可写坏存量）。
- 坏 `v7_state`（新鲜度计数/EMA 不可解析）：fail-open 重置该字段，分数与档位不受影响。
- 越界值：一律钳到值域与硬护栏内；v7 下展示分**永远到不了极值**，
  不会出现「刷满」形态。
- 熔断触发（单日累计位移超上限、同类事件超数）：本次记 0 分，标签与计数器照常累计，
  不报错、不提示用户（用户侧「为什么没涨」只有算法页的定性解释）。
- 迁移异常：宁可红在启动期，也不静默改运行数据（运行数据不可删是铁律）。

## 测试与验收

`tests/test_affinity.py`、`tests/test_affinity_numerical.py`（八档边界、线性/饱和口径）、
`tests/test_affinity_v6_smoothing.py`（曲线单调、带外恒等、递减与重置、帽不互挤、
**算法文案无数字**）、`tests/test_affinity_v7.py`（潜变量行为锁、「滚」字变体族）、
`tests/test_affinity_tag_fade.py`（淡出）、`tests/test_affinity_v21_budget.py` /
`tests/test_affinity_v21_signal.py` / `tests/test_affinity_v21.py`（预算、幂等、信号）、
`tests/test_v21_affinity_replay.py`（账本重放与补偿指纹）、
`tests/test_soak_growth.py`（长期增长不击穿）。
真机核对口径：开关两态各查一次「好感度」，分值与档位应当一致（存量不重置），
只有算法页文案随版本变化。
