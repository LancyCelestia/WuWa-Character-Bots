# QQ 协议端接入（SnowLuma / OneBot V11） · 群信息

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B01.qq-snowluma · 群信息

- 层级：一级 B01 → 二级 qq-snowluma → 三级 `group-info`
- 路由席位：`GROUP_INFO`（matcher `group_info`，command=True）
- 判定优先级：41
- 能力 id：`bot.group_info`
- 实现落点：`plugins/bot_unified_runtime/domains/transport/sender/onebot.py`、`plugins/bot_unified_runtime/domains/transport/sender/nonebot.py`、`plugins/bot_unified_runtime/message_context.py`
- 帮助主题：群信息
<!-- BOARD-AUTO:END -->

## 这个入口做什么

在群里问一句「群主是谁 / 本群多少人 / 群公告 / 群精华 / 群资料 / 本群多大了」，直接把答案回出来。它的由来是一次实测缺陷：协议端明明支持这些群 API，全仓却零调用，于是问得到却答不上。现在是这条链路的唯一入口。

生效条件：消息在群里（私聊不受理，回一句去群里问）、命中触发词、能力已注册（需重启生效）。

## 怎么调用

已登记能力（席位 `GROUP_INFO`，`capability_id=bot.group_info`，matcher `group_info`，command=True）。真身 `domains/chat_reply/capabilities/group_info.py`：

- `is_group_info_command(text)`：触发词判定（整句等于触发词，或触发词后紧跟标点/语气边界）。
- `build_group_info_capability(api, config, ...)`：装配能力入口；`api` 是 `build_onebot_api_bridge(...)` 产出的协程桥，传 None 时全部查询诚实降级。
- 触发词表常量 `GROUP_INFO_TRIGGER_WORDS`（词→意图映射 `_INTENT_OF_WORD`，最长词优先消歧）。

判定不自己写正则：触发边界走中央件 `domains/core/text_boundary.py:is_trigger` / `matched_trigger_word`，虚词集取 `PARTICLE_BOUNDARY_CHARS`。

## 开关与参数

- 无独立开关，随能力注册；改了要重启才生效（本仓铁律）。
- 权限分级：群名/群主/人数/上限/管理员数全员可问；公告首段与精华条数**仅管理员**（bot 侧角色门 + 协议侧失败即如实降级）。
- 隐私红线：成员名单不整列，只给统计数与群主/管理员数。
- 缓存 TTL 在 `domains/chat_reply/runtime/group_cache.py`（只缓存成功载荷），取值以该文件为准；本卡不复述秒数。
- 帮助主题：`/bot help 群信息`；逐参数口径以 `docs/command-catalog.md`（由 `scripts/command_catalog.py` 生成）为准。

## 失败时看到什么

- 私聊问：`_PRIVATE_HINT`——「群信息要在群里问才行哦」，不硬答也不拒人。
- 接口没回应 / 未接线 / 无权限：`_UNAVAILABLE_LINE`——明说这部分先不答、不瞎猜。
- 协议端没有对应能力（群链接、群相册、群等级/标签）：直说查不了。
- 「本群多大了」缺建群时间字段：字段在就算天数，不在就说拿不到。
- 任何一路都出文本结论，不因协程桥缺失抛异常打断会话。

## 测试与验收

`tests/test_group_info.py`（触发、意图分派、权限分级、诚实降级、缓存）。相关一致性门：`tests/test_capability_registry.py`（席位三元组）、`tests/test_doc_sync_gates.py`（路由矩阵与配置登记）。
真机：`docs/acceptance-manual.md` §6.4 逐能力清单中的群信息条目；重启前置见 §6.5。
