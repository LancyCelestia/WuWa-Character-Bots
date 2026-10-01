# QQ 协议端接入（SnowLuma / OneBot V11） · 群信息与平台能力边界

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.qq-snowluma · 群信息与平台能力边界

- 层级：一级 B01 → 二级 qq-snowluma → 三级 `platform-capabilities`
- 实现落点：`plugins/bot_unified_runtime/domains/transport/sender/onebot.py`、`plugins/bot_unified_runtime/domains/transport/sender/nonebot.py`、`plugins/bot_unified_runtime/message_context.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

登记「QQ 协议端到底能干什么、不能干什么」的边界，并对能查的部分给出出口。它不是一条命令，而是 QQ 侧所有平台调用的许可面与降级面清单：群资料类 API、贴纸回应、入站信号识别（真 @ / 软点名 / 文本 @）、以及一份「查不了就直说」的诚实清单。

## 怎么调用

- 群信息能力（已登记，席位 `GROUP_INFO`、能力 id `bot.group_info`）：`domains/chat_reply/capabilities/group_info.py:is_group_info_command(text)` 判定、`build_group_info_capability(...)` 装配；意图词表常量 `GROUP_INFO_TRIGGER_WORDS`。
- 协程桥（内部件，同文件）：`build_onebot_api_bridge(...)` 提供 `run_coroutine_threadsafe` 包装——能力跑在管线 offload 线程池里，而 `bot.call_api` 是协程，必须经这座桥；工厂构建时以 `api=` 注入，`api=None` 时所有查询走诚实降级（不炸、不装）。
- 缓存（内部件）：`domains/chat_reply/runtime/group_cache.py:GroupInfoCache`，只缓存成功载荷（旧路径 `runtime/group_cache.py` 已退役删除）。
- 贴纸回应（内部件）：贴纸回应入口的 `maybe_react_on_message` 一族（模块落点见本页上方生成段），出站调 `set_msg_emoji_like`。
- 入站信号（内部件）：`domains/chat_reply/runtime/mentions.py` 的 `looks_like_direct_question` / `starts_with_name_mention`，根 `__init__.py:_detect_onebot_direct_mention`、`_detect_text_at_mention`。

## 开关与参数

- 群信息无独立开关，随能力注册生效；缓存 TTL 在 `domains/chat_reply/runtime/group_cache.py`（资料/公告/精华十分钟档、成员列表一刻钟档，取值以该文件为准）。
- 贴纸回应键族：`bot_reactions_enabled`、`bot_reactions_probability`、`bot_reactions_cooldown_seconds`、`bot_reactions_max_per_hour`（下方括号内缺省值为当时值）；第二层图表情 `bot_reactions_meme_*`；聚合库 `bot_reactions_db_path`。逐键语义、缺省值与热更性以 `docs/config-catalog-full.md` 为准。
- 权限：公告与精华走 bot 侧角色门（管理员及以上），协议侧再失败就如实降级；成员名单不整列，只给统计数与群主/管理员数——这是隐私红线，不是待办优化。
- 平台角色：入站 `sender.role` 由根文件摄取层填进 `IncomingMessage.sender_platform_role`，群主判定（如紧急信息订阅）只认这个字段，且仅 `scope=group` 生效。

## 失败时看到什么

- API 失败 / 未接线 / 无权限：一句守岸人口吻的如实降级（如「群资料接口这会儿没回应，这部分先不答啦——不瞎猜」），不编数据、不静默吞。
- 群链接、群相册、群等级/标签：协议端无标准 API，直说查不了。
- 「本群多大了」：依赖协议端返回的建群时间字段（非 V11 标准扩展），字段在就算天数，不在就说拿不到。
- `set_msg_emoji_like` 失败：一律静默（贴不上当没贴，不打扰用户）；私聊请求在派发前就被拦下，根本不发。

## 测试与验收

`tests/test_group_info.py`、`tests/test_reactions.py`、`tests/test_reaction_store.py`、`tests/test_poke_unified_reaction_b10.py`、`tests/test_text_at_mention.py`、`tests/test_policy_soft_mention_gate.py`。
真机：`docs/acceptance-manual.md` §6.6.6（表情贴纸回应）、§6.6.7（戳一戳与贴纸 v2）。
