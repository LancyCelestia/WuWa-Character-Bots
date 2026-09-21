# 路由表与判定序 · 昵称命令

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.route-table · 昵称命令

- 层级：一级 B02 → 二级 route-table → 三级 `alias`
- 路由席位：`ALIAS`（matcher `alias`，command=True）
- 判定优先级：10
- 能力 id：`bot.alias`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「/岸宝帮助」「守岸人为什么」「/小岸同学状态」这类**昵称 + 动词**的输入解析成一个能力 id，让它和 `/bot help` 走同一个执行入口。格式固定为 `/<昵称><动词>[ 剩余文本]`；标准 `/bot …` 前缀不受它影响。它是路由表里优先级最高的一席（10），因为「用户在叫 bot」这件事必须先于其它判定被认出来。

## 怎么调用

已登记席位 `ALIAS`（matcher `alias`，command=True，`capability_id=bot.alias`）。判定与解析真身：

- `domains/chat_reply/runtime/aliases.py:build_command_alias_resolver(config, extra_nicknames=()) -> CommandAliasResolver`
- `CommandAliasResolver.resolve(text) -> AliasResolution | None`（字段 `capability_id / verb / rest_text`）
- 路由侧接线：`domains/chat_reply/runtime/base_router.py` 的 `_resolve_alias(text, alias_resolver)` → `alias_match`；解析器为 None 时昵称命令落到后续规则，不报错。
- 群门禁也用它：`policy/gate.py` 的 `extra_command_check` 与 `base_router.py:looks_like_command_text` 都先问解析器一次，命中即视为命令。

## 开关与参数

- 昵称来源优先级：`bot_persona_nicknames`（人格级）→ `bot_runtime_persona_nickname`（旧字段兼容）→ `bot_runtime_persona_nicknames` → 实例设置 store 里的动态昵称 → 官方策展兜底 `DEFAULT_PERSONA_NICKNAMES`。全部为空也**必须**能被叫应——「昵称无响应」就是这么根治的。
- 人格档案目录下的 `personas/<profile>/aliases.txt`（竖线分隔）由 `_load_persona_alias_file` 真读；文件缺失或不可读静默跳过并回落兜底。历史上这个文件长期无人消费，是一类典型「资产在、链路断」。
- 动词表 `DEFAULT_VERB_MAP`（帮助/状态/为什么/记忆/配置/就绪/人格/对话验收/角色/历史/暂停·继续 → 对应 `bot.*`）；长动词优先编译，避免「清理历史」被「历史」抢先。
- 大小写不敏感（`re.IGNORECASE`）。逐键热更性以 `docs/config-catalog-full.md` 为准；改昵称配置后最迟 10 秒生效（路由判定缓存 TTL），或调 `clear_route_decision_cache()` 立即生效。

## 失败时看到什么

- 没命中任何昵称+动词：返回 None，继续走后面的规则（通常落 `CHAT` 或 `IGNORE`），不会报错也不会半路截断。
- 昵称没配：走策展兜底，绝不出现「叫破喉咙没人应」。
- 动词对不上：解析失败同 None 处理；用户若写的是 `/岸宝` 光杆，会由后续席位决定回不回。
- 人格文件读不到：静默跳过（有兜底），日志不刷屏。

## 测试与验收

`tests/test_runtime_aliases*.py` 与 mentions 族（昵称解析、多昵称、长动词优先、兜底生效），以及 `tests/test_capability_registry.py`（席位三元组一致）。
真机：`docs/acceptance-manual.md` §6.6.1 触发形态里的昵称项；帮助主题 `/bot help 昵称`。
