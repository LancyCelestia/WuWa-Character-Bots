# 全库代码重审计报告（2026-09-11）

> 执行：C 组执行会话（续），HEAD 基线 `6de4aa2`。方式：8 个只读审计子代理按文件域互斥通读
> （两个域因上游 1302 限流各重派一次）→ 主会话逐条实证（修前必读原码，出域 P1 亦抽查）
> → 域内修复 + 回归 → 本报告。
> 范围：当前工作树（含并行会话未提交改动）。**不含**：`video_understanding.py`/`transcribe.py`/
> `runtime/video_pipeline.py`（视频会话在途）与已知底册问题（管线检视 #1-#8/#10-#13、chat.py 三项延后、
> 审计 C1-C23/D1-D11/E1-E2/A1-A16/B1-B14 已修项、渠道凭据类运维问题）。
> 汇总：**58 条 = P1×5 + P2×13 + P3×40**；本轮修复 19 条（C 组继承域），出域报告 39 条。
> 台账：`.superpowers/sdd/full-reaudit-20260911/progress.md`。

## 结论一览

| 域 | findings | 本轮已修 | 出域（待域主认领） |
|---|---|---|---|
| 主装配 `__init__.py` | 8 | 6 | 2（parked，见 §9 裁决） |
| 人格/知识/安全 | 8 | 8 | 0 |
| 能力层 | 6 | 5 | 1（download.py SSRF 面，B/基建域） |
| 发送/渲染（B组域） | 7 | 0 | 7 |
| 运行时/配置（B组域） | 6 | 0 | 6 |
| LLM 路由（B组域） | 8 | 0 | 8 |
| 解析器（A组域） | 8 | 0 | 8 |
| 订阅/sources | 7 | 0（store 方法+投递过滤随能力层修） | 6 |

---

## 1. 本轮已修（C 组继承域，全部带回归或门禁验证）

### 人格 / 知识 / 安全（character/** + security/**）

| # | 级 | 位置 | 问题 → 修法 | 验证 |
|---|---|---|---|---|
| R1 | P1 | vector_knowledge.py `embed_pending`/`build_ann_index` | 分钟~小时级嵌入/ANN/FTS 重建全程持检索锁 `_lock`，期间所有会话 retrieve 停摆 → 新增 `_maintenance_lock`（维护互斥、绝不持检索锁）；`build_ann_index` 换锁 | 既有 32 用例 + 全量门禁 |
| R2 | P1 | vector_knowledge.py `sync_chunks` + providers.py `_build_knowledge_chunks` | 清单中知识文件缺失时 `load_character_document` 抛 FileNotFoundError：向量通道降级为空且静态兜底二次抛，`build_context` 直接失败 → sync_chunks 缺文件删旧块+跳过（瞬态占用仅跳过）；providers 逐文件 try 跳过 | `test_knowledge_mtime_cache` 系回归 |
| R3 | P1 | affinity.py `extract_learned_nickname`（本轮 C-1 新码，重审计抓出） | 「叫我就好/叫我就行」非贪婪回溯把语气词当名字学进库 → 捕获值 ∈ 后缀语气词集合即拒绝 | `test_nickname_learning` 扩展 3 断言 |
| R4 | P2 | vector_knowledge.py `_ensure_schema` | 知识库未开 WAL，与 kb-sync 独立进程并发读写成片 SQLITE_BUSY → `_ensure_schema` 设持久 WAL（失败降级） | 门禁 |
| R5 | P2 | vector_knowledge.py `_save_vectors` | 嵌入链回退可产出混合维度向量：numpy 路径静默退化成 zip 截断伪余弦 → 批内一致 + 与库内 `vector_dim`（knowledge_meta 持久，模型指纹重置时一并复位）一致才入库 | 门禁 |
| R6 | P3 | persona_set.py 概率切换 | 权重不按总和归一化，总权重>1 时后面人格永远抽不到 → `draw*total` 归一化抽样 | `test_reaudit_20260911` |
| R7 | P3 | shared_group.py LLM 摘要 LRU | OrderedDict get→move_to_end 跨线程可被并发驱逐 KeyError 穿透 load() → 类内 `_cache_lock` 包住全部缓存操作 | 门禁 |
| R8 | P3 | content_safety.py 零宽黑名单 | 缺 U+2060（WORD JOINER）/U+00AD（软连字符）/U+180E 等，「色\u2060情」绕过全部规则 → 剥离集合扩充 | `test_reaudit_20260911`（4 变体） |

### 能力层（capabilities/** C 组清单内）

| # | 级 | 位置 | 问题 → 修法 | 验证 |
|---|---|---|---|---|
| R9 | P1 | subscribe_v2.py add | 群内添加订阅无管理员校验，任意成员可持续向全群推送外部内容（v1 有、v2 丢） → 群作用域 add 前置 `_is_admin` | `test_reaudit_20260911` |
| R10 | P2 | subscribe_v2.py pause/resume/remove | 操作作用于整条 target：一个目的地的管理员影响其他群/私聊（v1 目的地粒度未移植） → 新增 store `delete_destination`/`set_destination_enabled`，能力层只动本会话目的地行，最后一个目的地移除才删 target；投递侧 `_deliver_v2_event` 跳过 `enabled=False` 目的地不计失败 | `test_reaudit_20260911`（双群隔离用例） |
| R11 | P2 | echo.py `build_status_result` | `/bot status` 无管理员门，任意用户可拉运行时姿态（软暂停原因/角色计数/provider/api_key set-missing/bypass 角色）→ 加 `actor_roles` 门（未传=拒绝，防漏传绕过），两处调用点传 `_decision.actor_roles` | `test_reaudit_20260911` |
| R12 | P3 | debug.py LLM 接入卡 | 文件摘要含 request_id，每调用新增 PNG 永不清理 → 摘要去 request_id + `prune_prefixed(keep=50)` | 门禁 |
| R13 | P3 | today_history.py 推送表 | 读-改-写无锁（offload 并发整表覆写丢订阅）+ 群键任意成员可改 → `_push_table_lock` 包 RMW；群键设置/取消要求 `decision.actor_roles` 含 admin | 门禁 |
| R14 | P3 | meme_library.py 冷却表 | 会话键 OrderedDict 无界增长 → 超 512 先清过期再裁最旧（poke.py 同型问题由并行会话先行修复，本会话未重复动） | 门禁 |

### 主装配（`__init__.py`）

| # | 级 | 位置 | 问题 → 修法 | 验证 |
|---|---|---|---|---|
| R15 | P1 | `bot.alert` 能力 | `--probe` 同步 urllib 凭据巡检（串行多平台数十秒）直接跑在事件循环（调度器路径早已 to_thread，命令路径漏了）→ 加入 `OFFLOADED_CAPABILITY_IDS` | 门禁 |
| R16 | P2 | `_deliver_v2_event` vision | 同步 `describe_subscription_item` HTTP 在协程内直调，每条无文本订阅条目阻塞事件循环数秒 → `asyncio.to_thread` | 门禁 |
| R17 | P2 | today_ctx 装配 | `_register_today_history_scheduler` 抛异常（如 apscheduler 缺失）时 `today_ctx` 未绑定，后续命令 NameError → try/except 置 None 走直查路径 | 门禁 |
| R18 | P2 | group_file_stats matcher | priority 45 被 `/bot` 命令 matcher（11, block）完全遮蔽，`/bot 群文件` 死代码 → 降为 8（与 cookie/nickname 同档） | 门禁 |
| R19 | P3 | `_handle_natural` 点歌分支 | 漏传 `candidate_providers`：自然语言点歌静默丢失 cookie 候选搜索（命令/别名路径有） → 补同款条件传参 | 门禁 |
| R20 | P3 | `_refresh_affinity_nicknames` | 失败路径不推进 `_AFFINITY_NICKNAMES_LOADED_AT`，持续失败时每条群消息重试同步 sqlite → 移入 finally | 门禁 |

## 2. 出域 findings（待域主认领；P1 已主会话实证，其余为子代理报告+方法学可信）

### 发送/渲染域（sender/** + output/**，B组）

| 级 | 位置 | 问题（一句话） | 主会话验证 |
|---|---|---|---|
| **P1** | sender/queue.py `_entry_from_row`(:807) | 单条损坏/跨版本不兼容队列行让整个发送队列永久卡死：`model_validate_json`/`ReceiptState()` 无异常隔离，毒行恒在 `claim_due` 第一批且 `_finalize_expired_lease` 同样在事务内再抛，永远无法终态化 | ✅ 实证（读原码确认无隔离） |
| P2 | sender/onebot.py:340 | mixed 内容含 file 时图片/语音/视频部件被静默丢弃（`upload_parts` 只筛 file） | 抽查 |
| P2 | sender/onebot.py:674 | forward API 被实现端拒绝时异常穿透重试循环，text_fallback 降级不生效 | 抽查 |
| P2 | output/plain_text.py:245 | 「总之…」剥离正则吞掉尾部最多 60 字实质内容（锚 `$` 无句界限定） | 抽查 |
| P3 | sender/nonebot.py:287/433 | 发送前可判定的永久失败（缺地址/媒体不可发）被归类 FAILED_RETRYABLE 白白重试 | 报告 |
| P3 | output/card_render/usage_cards.py:196 | 用量卡 PNG 无界落盘无清理 | 报告 |
| P3 | sender/receipts.py:318 | 回执 operational_issue_json 损坏使 find/latest 持续抛（同毒行同型） | 报告 |

### 运行时/配置域（runtime/** + policy/** + bot.py + config.py，B组）

| 级 | 位置 | 问题 | 验证 |
|---|---|---|---|
| P2 | runtime/pipeline.py:832 + policy/rate_limit.py | `handle_async` 在事件循环线程同步跑 SQLite 限流/幂等事务（busy 5s），DB 竞争时全 bot 停摆 | 报告 |
| P2 | runtime/settings.py:395 | `_load` 对 overrides 只增不删：其他进程 reset 的覆盖项本进程复活且会被写回盘 | 报告 |
| P2 | runtime/model_schedule.py:120 | `last_applied` 仅内存，重启后窗口外不清已落盘的 BOT_CHAT_MODEL 覆盖，错误模型可卡数小时 | 报告 |
| P3 | runtime/settings.py:493 | 固定名 `.tmp` 临时文件，多进程并发 `_save` 互相踩踏静默丢失 | 报告 |
| P3 | runtime/event_idempotency.py:58 | 进程内幂等表每 key 单 capability_id，违背自身「不同能力互不影响」契约（SQLite 端是对的） | 报告 |
| P3 | runtime/settings.py:611 | 互动计数全量落盘持锁 30s 一次，与热路径 get() 共锁，interactions 无界 | 报告 |

### LLM 路由域（llm/**，B组）

| 级 | 位置 | 问题 | 验证 |
|---|---|---|---|
| P2 | providers.py:557 + model_router.py:1406 | 预算钳制靠单次操作超时：慢滴流响应可无限突破 120s 总预算（iter_bytes 每 chunk 重置 read 计时） | 报告 |
| P2 | model_router.py:1420 | 串行路径「去参重试成功」漏记 `_health_record_success`：恒拒 reasoning_effort 的渠道 EWMA 永久饿死 → 假超时 → 误拉黑 | 报告 |
| P3 | model_router.py:1106 | 影子 worker 去参重试无 except 保护，线程死亡可致 `_generate_hedged` 永久 wait | 报告 |
| P3 | model_router.py:924/1319 | `max(2,…)` 钳位使 hedge_max_candidates≥2 守卫死代码，无法按候选数关影子并发 | 报告 |
| P3 | model_router.py:1347 | 预算耗尽误报 `provider_not_configured`（真实原因 timeout 丢失） | 报告 |
| P3 | model_router.py:775 | 未知 override id 合成 spec 的 provider 带 key 永久入缓存，`_providers` 无界增长 | 报告 |
| P3 | model_router.py:1402 | `failover:deadline` 内外层重复入 attempts | 报告 |
| P3 | model_router.py:519 | `_priority_value` 把显式 priority 0 当未配置垫底，与「越小越先」语义冲突 | 报告 |

### 解析器域（sources/parsers/**，A组）

| 级 | 位置 | 问题 | 验证 |
|---|---|---|---|
| P2 | platforms_zhihu.py:96 | 回答卡 canonical_url 硬编码 `question/0/`（API 有 question.id 不用） | 报告 |
| P2 | platforms_community.py:130 | wmpvp getAppNewsById 不带 news_id 且不匹配静默回退第一条，卡片与链接不符 | 报告 |
| P2 | platforms_generic.py:337 | xhs noteDetailMap 首值非 dict 时 AttributeError 穿透 og 兜底契约（消费方只捕 ParseHttpError/ValueError/ParseFailure）；同型：bilibili.py:1000、music.py:466 | 报告 |
| P3 | platforms_bilibili.py:1139 | 番剧集时长 ms/秒启发式阈值 3600 判错 1000 倍（pgc 恒毫秒） | 报告 |
| P3 | platforms_media_share.py:54 | 汽水封面只替换 `\u002F`，其余 JS 转义残留裂图 | 报告 |
| P3 | platforms_kurobbs.py:202 | DOM 兜底每次新起完整 Chromium，无视注入的共享 playwright_backend | 报告 |
| P3 | image_stitch.py:119 | 拼接产物 `media_stitch/` 无淘汰配额无界增长 | 报告 |
| P3 | wbi.py:76 | single-flight 等待方无限循环：leader 被硬杀后 inflight future 永不落定 | 报告 |

### 订阅/sources 域（sources/**，待认领）

| 级 | 位置 | 问题 | 验证 |
|---|---|---|---|
| **P1** | social_v2.py:507 | 订阅轮询 async job 直调同步 fetch（Twitter 客户端整体同步 `def fetch_incremental`:265，最坏串行 15 个请求×10s timeout），阻塞事件循环数分钟 | ✅ 实证（:507 同步调用+:265 def、:535/:616 async 对照） |
| P2 | web_search.py:695 | DDG 命中提取正则匹配不到真实结果链接（实测返回 `//duckduckgo.com/l/?uddg=<编码>` 重定向），DDG 兜底腿恒空 | 子代理实测 curl |
| P2 | meme_search.py:191 | 同型：重定向域名不在白名单，梗搜索开启后恒空 | 报告 |
| P2 | bilibili_adapter.py:265 | V2 bilibili `live_room` 订阅恒返回空永不推送（有直播逻辑的 `fetch_live_statuses` 只被未注册的 V1 watcher 引用） | 报告 |
| P3 | subscription_scheduler.py:51 | PlatformThrottle 最小间隔 sleep 持全局锁 → 实际全平台串行 1req/s，global_limit 架空 | 报告 |
| P3 | music_v2.py:108 | netease public_user 把歌单对象当曲目，推 `song?id=<歌单id>` 错链接 | 报告 |
| P3 | meme_search.py:122 | `_cache` 无上限无清扫 | 报告 |

### 其他

| 级 | 位置 | 问题 | 验证 |
|---|---|---|---|
| P3 | capabilities/download.py | `/bot download` 对任意用户开放任意 URL（SSRF 探测面+1GB 落盘+占线程池），无角色/内网过滤 | 报告（B/基建域） |

## 3. 主会话裁决记录（Rulings）

1. **域路由**：本轮只修 C 组继承域（character/security + `__init__.py` 主装配 + capabilities C 组清单 + subscription_store_v2/投递点联动）；sender/output、runtime/policy/config、llm、parsers、sources/subscriptions 其余项按 §11.3 归属报告不修——B组尚未认领，其域 P1（queue 毒行）建议下一认领会话优先。代价：P1 毒行在脏数据出现前不发作（当前队列无毒行），风险可控。
2. **poke.py 不重复修**：并行会话已落地等价有界化（`_POKE_LAST_CAP`），本会话放弃同型改动避免裹挟；meme_library 由本会话修。代价：无（等价实现）。
3. **content_safety 空白折叠不加码**：子代理建议「CJK 匹配前去全部空白」——否决，全剥空白会制造「三色情节→色情」型误报，只扩零宽集合。代价：插空格变体（「色 情」）仍不命中，接受。
4. **transport 穿透 P3（`_run_simple_capability` 双通知 / today_history、meme_library transport_receipt 不通知）parked**：需按 `_handle_content` 模式逐 handler 复制 transport 分支，改动面大且 C12 语义刚定去重方向，随 `__init__.py` 域提交队列一并评估。代价：极端路径重复诊断通知（无害）或个别 transport 失败缺通知（台账可查）。
5. **文件段同步解析 P2 parked**：`_incoming_from_nonebot_event` 的文件解析在事件循环上，但受 120k 字符上限约束且仅在消息含文件段时触发；结构性 to_thread 改造牵动 sync 函数签名，随 B 组管线工作一并。代价：大文档消息瞬间（非持续）阻塞循环。

## 4. 验证证据

- 新增回归：`tests/test_reaudit_20260911.py` 6 用例（小名语气词/人格归一化/零宽/status 门/订阅 add 门/目的地粒度）+ `test_nickname_learning.py` 扩展 → 本域定向 31 passed。
- 全量门禁：pytest / ruff / mypy 结果见交付说明（多会话共享树，红项按 §11.3 归属）。
- 出域 P1×2 均经主会话读原码实证后才标 ✅；其余出域项为子代理原码级报告（方法：证据引用+禁臆测契约），未逐条复跑。
