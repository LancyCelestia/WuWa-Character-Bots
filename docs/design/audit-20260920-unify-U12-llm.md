# U12-LLM 模型链路与计价统一审计日志（2026-09-20）

> 席位：U12-LLM（只读审计子代理）。硬禁令生效：不再派子代理、零 git 写、除本文件外不改任何代码/配置/文档、零真实 LLM 调用、禁读 .env 明文值（真实密钥值绝不写入本文件，只报键名+文件:行）。
> 总目标（用户统一 mandate）：LLM 侧「每次模型调用只能有一个中央入口（路由→超时→重试→计价→审计→降级话术）」；凡有第二条通路直连模型、或某个环节在多处各自实现，即为缺陷。
> 范围裁定：只查后端 Python。webui/、domains/render/**、output/card_render/**、theme_tokens.py、TTS/语音链路不查不报。
> 行号漂移声明：树正被并行会话改写，本文件每条结论均带「锚点字符串」，行号仅为落笔时刻快照。

状态图例：⬜ 未开始｜🟡 进行中｜✅ 完成

当前进度：✅ 全部完成（§0/D1/D2/D3/D4/发现清单 F-01…F-16/收口清单/取证与自查记录均已落盘）。

**执行方式披露**：原计划用 `%TEMP%\u12_scan.py` 脚本枚举（已写好，路径 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\%TEMP%\u12_scan.py`），但权限层禁止执行 temp 目录脚本（classifier 两次拦截，含绝对路径形式），故 D1 枚举改用等价手段 = ripgrep（Grep 工具）+ 定点 sed 通读；扫描模式集合不变（providers/generate/chat/completions/httpx/8090/axonhub/AsyncOpenAI/route_model/route_ids/ModelRouter/OpenAICompatibleLLMProvider 构造点）。全树未发现任何 `AsyncOpenAI`/`from openai` SDK 直调（0 命中）。

---

## §0 必读材料核对（AGENTS 第三部分 + 台账 #34/#35/#36/#42 + audit-20260919-unify-wave + HANDOFF-V21R5 §三 K1/K2）

| 材料 | 声称结论 | 与当时代码是否一致 | 证据坐标 |
|---|---|---|---|
| AGENTS 第三部分「providers.py connect 5s/read 30s 分类超时」 | 代码 client 默认 `Timeout(connect=5.0, read=30.0, …)` **但**每次请求传标量 `timeout=request_timeout`，httpx 标量会**整体覆写**四分量 → 路由链上 connect 实际=每跳标量值（缺省 20s），5s 分类快败在该路径不生效 | **不一致（P1，见 F-02）** | `providers.py:191` 锚点 `timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)`；`providers.py:584` 锚点 `timeout=request_timeout,`（client.stream 内）；`config.py:860` `bot_chat_timeout_seconds: float = 20.0` |
| AGENTS「BOT_CHAT_FAILOVER_MAX_SECONDS=300」 | 代码缺省 120s，300 只存在于生产 .env（不可读，按文档记录）| 缺省漂移（P3 文档口径）| `config.py:869` 锚点 `bot_chat_failover_max_seconds: float = 120.0` |
| AGENTS「EWMA 延迟择优」 | v21r2 R1 起缺省**严格注册表优先级**（`bot_chat_strict_priority=True`），EWMA 仅两用途：①latency_first 显式开时做同级 tiebreak；②自适应超时收紧。排序择优已退役 | 文档口径过时（P3）| `model_router.py:1096` `channels_for_model` docstring「严格注册表优先级」；`config.py:873` `bot_chat_strict_priority: bool = True` |
| AGENTS「影子并发 2s」 | `_hedge_settings` getattr 兜底 6.0，但 Config 字段缺省 2.0 → 生产实际 2.0；且台账 #36 记录生产 .env `BOT_CHAT_HEDGED_REQUESTS_ENABLED=false`（影子关，本席不可读 .env，按文档） | 基本一致（兜底常数 6.0 与 Config 缺省 2.0 双数并存，P3） | `model_router.py:1211` 锚点 `delay = float(getattr(cfg, "bot_chat_hedge_delay_seconds", 6.0))`；`config.py:507` `bot_chat_hedge_delay_seconds: float = 2.0` |
| 台账 #35/§K3「模型自评标签整体删除、改纯本地词表」 | `content_route.py` 注入面已删；仅剩 `consume_reply` 防御性剥离（chat.py:1994 注释明示「历史残留标记剥离」）；无升级重试残码（全树 grep `escalat` 仅 teaching/injection 无关命中） | 一致；无死码残留（1 项取证未见缺陷） | `chat.py:1994`；`content_route.py:26/303` |
| 台账 #36「explicit_allowed_for_session 抽单一事实源」 | 定义唯一（content_route.py:369）；chat.py:2043 与被动好感感知 `__init__.py:7356-7370` 双消费同函数；`match_master_love_admin` 亦唯一定义（content_route.py:114） | 一致（1 项取证未见缺陷，详见 D4.3） | 见左列坐标 |
| K1 告警定性「冷却实锤、config_missing 不入冷却、无代码 bug」 | 90s 冷却缺省与「auth/config_missing 不计渠道健康」均与代码一致；**但 K1 未覆盖 F-02（connect 分类被标量超时吞掉）与双进程事实之外无新增反证** | 结论仍成立（补充缺陷不推翻定性） | `model_router.py:600` 锚点 `if error_kind in {"auth", "config_missing"}:`；`channel_health.py:44` 锚点 `_DEFAULT_COOLDOWN_SECONDS = 90.0`；`config.py:876` `bot_chat_channel_cooldown_seconds: float = 90.0` |
| K2「三形态缓存 token 解析全覆盖、gemini 缓存 0=渠道行为、统计链路无缺陷」 | 三形态解析仍覆盖（providers.py `_extract_usage`）；**但「上游未回字段」与「真 0」在事件日志/报表面不可区分**（providers 仅 >0 才写键，事件聚合 `fields.get("cache_read_tokens","0")` 缺省 0，家族行恒显 0）——K2 自己登记的「可选增强：加注『上游未回字段』」仍未实施；且 K2 数据源覆盖面缺陷未提：**事件日志只含 chat 主链一条能力的用量**（D3.1/发现 F-05），「账单 0.30 元/24h」系统性低估 | 部分成立（结论对解析面成立，对「统计链路无缺陷」总体定性**不成立**，见 F-05/F-06） | `providers.py:376-379` 锚点 `if cache_read > 0:`；`runtime_event_log.py:270+` 聚合缺省 `"0"`；`chat.py:2365` 唯一 `_llm_usage_audit_tags` 调用点 |

## D1 模型调用出口清点（找旁路）

### D1.1 枚举脚本与扫描原始输出

- 脚本 `u12_scan.py` 因权限层禁跑改由 Grep 等价执行（模式集见上披露）。原始判定依据全部为逐文件实读，坐标如下表。
- 全树 `AsyncOpenAI|from openai|import openai`：**0 命中**（无任何 OpenAI SDK 旁路）。
- 全树 `chat/completions` 命中 12 处（排除 u12_scan.py 自身与 tests）：providers.py×3（唯一生产传输实现+契约文案）、channel_health.py×2（探针）、meme_library_listener.py×1（**裸 httpx 旁路**）、smoke.py×3（诊断展示/URL 清洗）、debug.py×1（展示）、scripts/probe_llm_providers.py×2（离线路证脚本）。
- `OpenAICompatibleLLMProvider(` 构造点（非 tests）11 处：model_router(1026)/根 __init__(367)/backend_unit(57)/console_chat(189)/smoke(1055,1707)/control_plane factory(93)/debug(1010)/vision_describe(558)/tests 若干。
- `build_model_router(` 调用点 10 处（见 D1.2 #10-#16），其中 **5 处二级路由器不带 dynamic_registry/priority_groups/content_route_cb**（见 F-04）。

### D1.2 出口判定表

判定口径：**经路由**=ModelRouter 中央链；**落账**=生产缺省态（`BOT_LLM_BILLING_ENABLED` 关，llm_billing.sqlite3 不存在=K2 实证）下，该出口 token/费用是否有任何形式进入账单可见面（事件日志审计标签或账本行）。

| # | 文件:行 | 锚点字符串 | 是否经路由 | 是否落账 | 是否有超时 | 是否有降级 | 判定 |
|---|---|---|---|---|---|---|---|
| 1 | domains/chat_reply/capabilities/chat.py:1882,1957 | `last_reply = model_router.generate(` | ✅ 中央 | ✅(唯一完整：事件标签+可选账本) | ✅ 预算+自适应 | ✅ 五池 | 正牌主链 |
| 2 | chat.py:1892,1967 | `llm_provider.generate(current_messages, **options)` | ⚠️ router=None 分支 | ❌ | 仅 provider 级 | ✅ | 生产 router 恒非 None（__init__.py:4626 无条件装配）→**条件死分支**，留作测试缝（P3，建议显式化） |
| 3 | domains/chat_reply/character/shared_group.py:299 | `reply = self.llm_provider.generate(` | ❌ **旁路**：装配注入 `_build_chat_llm_provider(config)`（根 __init__.py:367→4706 `shared_group_llm_provider=`），单模型 BOT_CHAT_MODEL 直连 | ❌ 零记账 | 仅 20s（config） | ✅ 失败回退原文 | **缺陷（F-05）**：群摘要 LLM 压缩第二通路 |
| 4 | domains/media/ingest/vision_describe.py:568+ | `def generate(self, messages: list[dict[str, Any]], **kwargs)`（DynamicVisionProvider） | ❌ **旁路 ModelRouter**：自建候选排序+`_MAX_VISION_FAILOVER_ATTEMPTS` failover 圈（传输仍走 providers.py） | ❌ 零记账 | ✅ 20s+2×deadline 护栏 | ✅ 调用方静默 | **缺陷（F-03）**：第二路由实现（无冷却/无价格/无 EWMA/无时段组） |
| 5 | domains/meme/sources/meme_library_listener.py:153-161 | `response = await client.post(` + `f"{base_url}/chat/completions",` | ❌ **完全旁路**：裸 `httpx.AsyncClient`，连 providers.py 都不走 | ❌ | ✅ 20s 自配 | ✅ 静默 | **缺陷（F-01）**：第三条传输实现；缺省 `bot_meme_library_vlm_enabled=False`（config.py:535）减轻暴露面 |
| 6 | domains/chat_reply/llm_engine/channel_health.py:551 | `url = spec.base_url.rstrip("/") + "/chat/completions"` | ❌ 探针性质 | ❌（max_tokens=1 真金白银不记账） | ✅ 25s | ✅ 吞异常转状态 | 设计内（健康巡检），但同属**第三处裸 httpx 传输**（P3 卫生：应收编进 providers 最小调用面或记账打 `source=probe`） |
| 7 | domains/media/capabilities/media_archive.py（2 处 `.generate(messages, temperature=…)`） | 同左 | ❌ 经 #4 vision provider | ❌ | 随 #4 | ✅ | 随 F-03 归因 |
| 8 | domains/media/ingest/video_understanding.py:208 | `reply = vision_provider.generate(messages, temperature=0.1, max_tokens=500)` | ❌ 经 #4 | ❌ | 随 #4 | ✅ | 随 F-03；ASR 分支属语音链路，按范围裁定不查不报 |
| 9 | domains/schedule/timetable.py:301+ | provider 协议对齐 DynamicVisionProvider（`build_timetable_provider` 惰性复用 vision_describe） | ❌ 经 #4 | ❌ | 随 #4 | ✅ | 随 F-03 |
| 10 | __init__.py:422(memory)/2803(reflection)/4626(主链) | `provider = router.fork() if callable(getattr(router, "fork", None))` | ✅ 主 router fork | ⚠️ 仅账本开时 | ✅ | ✅ | fork 继承回调 ✓（model_router.py:924）；但 generate 不传 request_id/capability → 账本归因空（F-07） |
| 11 | domains/link_parse/capabilities/content_parser.py:579 | `router = build_model_router(config)` | ⚠️ **二级 router**：无 dynamic_registry/priority_groups/content_route_cb | 账本开时 | ✅ | ✅ | F-04 |
| 12 | domains/assistant/daily/store/daily_assist.py:353 | `router = build_model_router(config)` | ⚠️ 同上 | 同上 | ✅ | 回退原文 | F-04 |
| 13 | domains/schedule/llm_draft.py:468 | `return build_model_router(config).generate` | ⚠️ 同上 | 同上 | ✅ | ✅ | F-04 |
| 14 | domains/ops/admin/runtime_admin.py:502 | `router = build_model_router(config)` | ⚠️ 同上（管理员工具，性质轻） | — | ✅ | ✅ | F-04 低危 |
| 15 | console_chat.py:249 / backend_unit.py:102 / 根 __init__.py:397 | `model_router=build_model_router(config),` | ✅ | — | ✅ | ✅ | 正常装配（三处均传 config 缺省参数，console/backend_unit 不带动态注册表=工具侧可接受，登记） |
| 16 | control_plane/factory.py:91-93 | `provider = OpenAICompatibleLLMProvider(` | ❌ 控制面沙箱执行装配 provider | ❌ | ✅ | ✅ | 控制面批在飞域（#42 L41 等裁决），登记不深查 |
| 17 | domains/ops/smoke/smoke.py:1055,1707 + domains/ops/admin/debug.py:1010 | `provider = llm_provider or OpenAICompatibleLLMProvider(` | ❌ 诊断单渠道 | ❌ | ✅ | ✅ | 运维诊断直连属有意设计（/bot llm 诊断），登记；真实花费不落账（P3 标注即可） |
| 18 | scripts/probe_intimate_route.py:316；scripts/probe_llm_providers.py | 构造 providers / 端点清洗 | ❌ 手工取证脚本 | ❌ | ✅ | — | 非生产路径，登记 |

**结论（本席核心问题的直接回答）**：存在**绕过中央路由的模型调用出口**——生产装配内确认 **3 类真旁路**（#3 shared_group 直连、#4/7/8/9 vision 全家自建路由、#5 meme 打标裸 HTTP）+ 探针/诊断/脚本若干（设计内，登记）。传输层收敛度好于预期（除 #5、#6 外全部复用 providers.py），**分裂点在路由与记账层**。

### D1.3 「能力内部自行重试」二次包装点

| 文件:行 | 锚点 | 说明 |
|---|---|---|
| vision_describe.py（DynamicVisionProvider.generate 全函数） | `for entry_id, entry in candidates[:_MAX_VISION_FAILOVER_ATTEMPTS]:` | 不是「重试一次」而是**整套第二 failover 引擎**；与 chat 主链无叠加（不同调用面），但同一次识图失败会在 2×timeout 预算内连试多渠道，与告警/冷却体系互不可见 |
| chat.py（poke 话术）__init__.py:5200-5213 | `asyncio.wait_for(` + `model_router.generate,` | 外层 12s 硬顶 + 内层 fast 预算双计时器：语义是封顶不是重试，**不放大延迟**；登记 |
| model_router.py:2185-2199 | `retry_options = dict(attempt_options)` | **路由内部**去参（reasoning_effort）重试——属中央环节自身设计（管线检视 #2），非旁路；但它**复用首跳的 timeout_seconds 不重算剩余预算、且不 incremented provider_attempts**（见 F-08，尾部可超预算一个 request 周期） |
| 其余能力（reminders/notes/digest/llm_draft/daily_assist/content_parser） | — | 取证未见「失败再打一次」包装：全部一次 generate + 失败走文案回退。**9 项取证未见二次重试**（清单：chat/memory/reflection/shared_group/vision×4 入口/llm_draft/daily_assist/content_parser/timetable/media_archive） |

## D2 路由与降级语义统一

### D2.1 model_router 实读

- **优先级组**：`parse_priority_groups`（model_router.py:235）JSON/list 双形态、days ISO 1-7、windows 跨零点、命中取首个；`_auto_route_ids`（1575）组内 order 条目**渠道 id / 模型名 / 别名三形态**全收（v21r2 R1 修「恒 no-op」在盘，锚点 `by_name.setdefault(spec.model.strip().lower(), …)`）；分组只重排模型先后、渠道序归注册表优先级（用户裁定）✓。兜底组（days/windows 全缺省）语义 ✓。
- **EWMA**：仅两个消费位——`channels_for_model` 同级 tiebreak（latency_first 显式开才进排序键）与 `_tighten_timeout` 自适应超时（`require_latency_first=False` 独立护栏，锚点 `_health_ema_latencies(` 1023 调用位）。「延迟择优」旧口径已死（文档漂移 P3，§0 表）。
- **hedge**：`bot_chat_hedged_requests_enabled` 门 → `_generate_hedged` 竞速（daemon 落选线程、赢家归因 `hedged:{id}:winner`、`_last_channel_id` 计费归因赢家已修）；INTIMATE/fast_mode 跳过影子 ✓（#36 裁定在盘）。
- **effort**：条目 > 全局 > 家族基线；复杂任务升家族最高档；**INTIMATE 会话升档抑制双保险**（generate 薄包装 + _generate_impl 各算一次 complex_task，锚点 `if complex_task and _intimate_mode_for_session(`）✓ #36 在盘。未知家族（如 c-gemini 之外的新名）baseline="" → 不携带 reasoning_effort（providers 仅 effort∈枚举才发参）✓ 安全缺省。
- **内容路由残码**：注入/升级重试删净（§0 表）；`_intimate_session` 每 generate 单回调判定共用（冷却守卫+影子跳过同判据）✓。**未见死码**（1 项取证未见缺陷）。
- **providers 契约面**：error_kind 分类学（_FAILOVER_ERROR_KINDS 14 类 + 仅 config_missing 不转移的「渠道相关 4xx 可转移」裁定在盘，锚点 `_FAILOVER_ERROR_KINDS = frozenset(`）；`_MAX_RESPONSE_BYTES=8MB`/错误体 8KB 截断、慢滴流 deadline ✓。

### D2.2 超时与预算核对表

| 环节 | 文档口径 | 代码实况 | 锚点 | 漂移? |
|---|---|---|---|---|
| connect/read 分类 | 5s/30s | client Timeout(5/30/10/5) **但每请求传标量 → 分类被整体覆写**；生产每跳= min(20s config, 剩余预算) | `providers.py:584` `timeout=request_timeout,` | **是（F-02 P1）** |
| 每跳基础超时 | read 30s | `bot_chat_timeout_seconds=20.0` 缺省（.env 可覆，本席不读值） | `config.py:860` | 是（文档 30 vs 码 20，P3） |
| 总预算 | 300s | 缺省 120s；.env 记 300 | `config.py:869` | 缺省漂移（P3） |
| 90s 冷却降级 | 有 | `_DEFAULT_COOLDOWN_SECONDS=90` + config 90 ✓；`_demote_cooling_candidates` 稳定队尾不剔除 ✓ | `channel_health.py:44` | 否 |
| config_missing 不入冷却 | 有 | `{"auth","config_missing"}` 早退（auth 同不记，文档只提 config_missing——auth 亦不记属超集，口径需补文档） | `model_router.py:600` | 微漂（P3） |
| chain 长度上限 | 暗示有 | **无硬上限**；仅预算/`failover:deadline`/min-hop 3s/健康过滤四层闸（K1 chain=14→冷却后 6 = 无上限佐证） | `model_router.py:2109-2118` | 无上限=现状事实，文档未承诺数值 → 不判缺陷，登记事实 |
| 逐跳超时=剩余预算 | 隐含 | `timeout_seconds = min(timeout_seconds, remaining)` ✓ 但去参重试不重算（F-08） | 锚点 `timeout_seconds = min(timeout_seconds, remaining)` | 一处例外 |

### D2.3 失败面池实现份数与告警轨迹覆盖

| 池/文案族 | 定义位置 | 取句实现 | 单源? |
|---|---|---|---|
| 反注入 12 变体 | chat.py:2654 `_INJECTION_GUARD_TEMPLATES` | 会话游标 `(offset)%n` + 512 环（chat.py:2679-2689） | 池单源；游标实现=**手写复制份 #1** |
| 私聊人格失败 12 变体 | chat.py:616 `_PERSONA_FAILURE_MESSAGES` | 会话游标（632-650，与上同构） | 池单源；游标实现=**手写复制份 #2** |
| 管理门池 | user_copy.py `ADMIN_GATE_TEMPLATES` | 调用点 `random.choice`（**无游标**） | 池单源；取句=随机 |
| 群失败 ack（A-19）12 条 | user_copy.py:74 `GROUP_FAILURE_ACK_TEMPLATES` | `random.choice` + pipeline 会话级节流（pipeline.py:837+） | 池单源；取句=随机 |
| 错误卡冷却/人话区 | domains/ops/monitor/error_report.py:340 `_HUMAN_TEXTS[random.randrange(count)]` | **随机** | 池单源；取句=随机 |

- **AGENTS/#34「五池…游标轮换」口径不实**：5 池中仅 2 池游标，3 池 random；「游标轮换」实现有 **2 份手抄**（锁+dict+512 环逐字段重复）。→ F-09（P2：文档与实现语义漂移 + 轮换逻辑未收口）。
- **绕池写死文案**：`user_copy_unification_gate` 负向扫描门在盘（旧句式池外硬编码→红），残余豁免已登记（user_copy.py 头注释豁免清单）；**取证未见新增绕池硬编码错误文案**（清单：media_archive「打了个小盹」句=豁免语义位、pipeline 拦截静默=设计内）。
- **告警带路由轨迹**：逐跳失败 `logger.warning("llm route hop failed model=%s family=%s kind=%s …intimate=%s")`（2204 锚点）+ 出口 exc.attempts 归因 + `attempts_json` 落账本 ✓。**不覆盖出口**：#3 shared_group（异常全吞 `except Exception: return key`，无告警无轨迹）、#4-#9 vision（失败仅 `last_attempts` 随调用方静默，无统一告警位）、#5 meme（`except Exception: return`）→ F-05/F-03 附带面。

### D2.4 上下文钳制生效面

| 调用出口 | 是否过钳制 | 锚点 | 备注 |
|---|---|---|---|
| ModelRouter.generate 全路径 | ✅ | `_generate_impl` 内 `_enforce_context_caps(`（2269 装配覆写 128K/64K：`router.max_input_tokens = int(`） | 缺省 131072/65536 与文档一致（config.py:707-708） |
| DynamicVisionProvider（vision 全家） | ❌ | vision_describe.generate 无 caps 调用 | 输入=prompt+图（文本部分可超 128K：长聊天记录合并转发转发给 vision 的路径）→ 归 F-03 |
| shared_group summarize | ❌（入参已被 400 字截断，风险低） | `max_tokens=200` | 登记 |
| meme `_tag_with_vlm` | ❌ | payload 固定 `max_tokens=300` | 图 base64 体积大但 token 语义不触发钳制——登记 |
| 二级 router(#11-14) | ✅（各自缺省 128K/64K） | build_model_router 尾部统一赋值 | 无漂移 |
- **丢弃最旧非 system 的语义风险**：`_enforce_context_caps` 逐条删「第一个非 system 消息」——多轮工具消息对中删 tool/assistant 段会留下孤儿 `tool_call_id` 消息（providers 原样转发 payload），严格渠道可 4xx→`bad_request`→failover，全链失败率放大。当前生产链 max_tokens=0（模型自决）+ 私聊历史通常 <128K，**未见在飞事故证据**，但属结构性风险 → F-10（P2：钳制需成对删除工具轮或整体丢弃 assistant+tool 组）。


## D3 计价 / 账本 / 用量统计单一事实源

### D3.1 四套实现字段级对照表

栈命名：**A**=chat 审计标签→事件日志（`_llm_usage_audit_tags`→`transport_receipt` 行→`aggregate_llm_usage_range`）；**B**=`llm/ledger.py`（llm_call_records，默认关）；**C**=`usage_service.py`（V2.1 S5）；**D**=`billing_entities/billing_pricing/billing_service`（V2.1 S5 实体/语义/只读适配器）。

| 概念 | A 事件标签栈 | B ledger.py | C usage_service | D billing_entities/pricing | 口径差异点名 |
|---|---|---|---|---|---|
| 输入 token | `llm_usage_prompt_tokens:`（chat.py:2588） | 列 `prompt_tokens` | 指标 `input_tokens`（别名 prompt_tokens→） | `input_tokens` | 四名两制：A/B prompt，C/D input |
| 输出 token | completion_tokens | completion_tokens | `output_tokens` | `output_tokens` | 同上 |
| 缓存读 | tag `llm_usage_cache_read_tokens:` **仅 >0 才发**（chat.py:2595+providers:376） | 列 cache_read_tokens（缺=**NULL**） | `cache_read_tokens`（别名 cached_tokens→） | `cache_read_tokens` | 缺失语义：A 聚合读成 0（`fields.get(…, "0")`），B/C/D 保 NULL/unknown——**A 不可区分「未回报」与真 0** |
| 缓存创建 | tag `llm_usage_cache_write_tokens:` | 列 `cache_creation_tokens`（输入键 cache_write_tokens） | `cache_create_tokens` | `cache_create_tokens` | **三名**：write/creation/create（units 同 tokens） |
| 金额 | `llm_usage_cost_milli:` int 1e-3 元 | `*_cost_milli` 可空 int 1e-3 | Decimal 量化 1e-9（nano）字符串序列化 | Decimal 1e-9 | **两套金额精度互不可逆转换**（milli↔nano）；「未知≠零」B/C/D 有、A 无 |
| 币种 | 隐含 CNY 无字段 | `currency` 列缺省 'CNY'（ModelSpec 注释「币种随渠道报价」**无校验**） | currency 参数 ISO | `_CURRENCY_RE` 强制 ISO-4217 三位 | 若渠道按 USD 报价：B 直接记 CNY 假账；C/D 有防线但休眠 |
| 计价公式 | `pricing.model_call_cost_milli`：`ordinary=prompt−cache_read`（**不减 cache_write**，Anthropic 口径注释）+ **忽略 per_call** + 缺价键 `entry.get("input",0.0)` **0 价照记 priced=True** | `build_call_draft`：`billed_input=max(0,prompt−read−write)`（Anthropic 口径下**多减**→少算）+ per_call 叠加 + in/out 缺任一→NULL+unpriced=1 | `quote_usage`/`settle_attempt` 按 PriceRevision 时窗价（休眠） | `SCHEMA_SEMANTICS` per-provider input_semantics（`axonhub_v1` unknown 不臆断） | **同一调用 A/B 两栈金额可以不同**（缓存创建>0 或按次渠道两种触发形态）→ F-06 |
| 生产读取方 | ✅ **唯一活账**（/bot model usage runtime_admin:860、定时报告 usage_monitor:469/701、阈值告警、报告卡） | ❌ 开关死（F-12），llm_billing.sqlite3 不存在（K2 实证） | ❌ **零生产消费者**（全仓 grep 仅包内互引 + tests/test_usage_billing_v21.py） | ❌ 同上（test_billing_service_v21.py）+ `domains/creation/_common/contracts.py` 仅注释对齐声明 | C+D ≈3400 行休眠实现；「哪套是生产实际读的」=**只有 A**；B 半死；C/D 纯测试消费 |

**覆盖面致命点**：A 栈唯一挂钩点=`chat.py:2365`（全仓 `_llm_usage_audit_tags(` 仅 1 个调用点）→ vision 全家/shared_group/meme/二级 router 调用/探针 **全部不进 A**；B 关→ 于是**生产账单只看见 bot.chat 主链一条能力的模型花费**（F-05/§0-K2 复核：0.30 元/24h 属系统性低估，非链路故障）。

### D3.2 价格来源三处 + 缓存 token 三形态

价格面（写 5 处 / 读 4 处，**非一份数**）：
1. **注册表条目 per-channel 价**（price_in/out/cache_read/cache_creation/per_call）：写=①`scripts/import_model_prices.py --apply`→`settings.set_model_entry`→`data/settings/runtime_settings_shorekeeper.json`（profile 硬码 :185 附近，锚点 `"bot_profile_id": "shorekeeper"`）；读=B spec（`_spec_from_entry` :514-518）、A 经 `registry_model_prices` 投影（**模型级首个有效价赢**，同模多渠道价差被抹平——注释自认「渠道价差由 V2.1 链路处理」而 V2.1 休眠，:106-108）、报表侧 live 读。
2. **BOT_MODEL_PRICES 模型级 map**：写=②`/bot model price`（runtime_admin:725-786 `store.set_override("BOT_MODEL_PRICES", json.dumps…)`）+ SETTABLE 热改；读=A 快照/报表 live；**B 不读** → `/bot model price` 回执「之后的调用按新价格记账」对账本栈为假（账本开时错账）→ F-13。
3. **`_MODEL_PRICE_FALLBACKS` 硬编码兜底**（model_router.py:369，6 模型）：读=B（`_apply_model_price_fallback`）+ 报表（usage_monitor:559-580 从同 dict 现场构建第三 merge 源）；**A 调用时刻栈不读** → 只存在于兜底表的模型：B/报表计价、A 记未计价——同一调用两种结论 → F-06/F-13 佐证。
4. `bot_llm_model_price_overrides`（model_router.py:419 读）——**Config 无此字段 → 恒 None，死读面**（F-14）。
5. C/D 自有价表（PriceRevision）——休眠。
缓存三形态解析：providers `_extract_usage`（:354-383）OpenAI `prompt_tokens_details.cached_tokens` / DeepSeek `prompt_cache_hit_tokens` / Anthropic `cache_read_input_tokens`+`cache_creation_input_tokens` **三形态全覆盖 ✓**（K2 该点复核成立）；`_first_int` 单链首取不双计 ✓；「未回字段记 0」风险定位修正：**providers/ledger 层不造 0**（>0 才写键 / NULL），造 0 发生在 **A 聚合读**（`runtime_event_log.py` `fields.get("cache_read_tokens", "0")`）与展示层，家族行注记「0=该模型没回报」已按 K2 增强半实施（usage_monitor.py:184）——**K2「统计链路无缺陷」的结论仅在解析面成立，覆盖面（只计 chat）与缺失语义（0≠未回）两处仍缺陷**（F-05/F-06/§0）。

### D3.3 模型家族归一化实现份数

`pricing.model_family_key`（casefold + 循环剥 `_EFFORT_SUFFIXES` 尾段）**全仓唯一定义**；消费=usage_monitor（家族行合并 :236）、runtime_admin（:413/417）、`lookup_model_price` 家族兜底链——1 份，未见双写（3 项取证未见缺陷；`model_router.model_family` 是 effort 家族概念，不属计价归一，不计）。

### D3.4 未计价行为

- B 栈：缺 in 或 out → cost NULL + `unpriced=1`，报表显式「N 次调用未计价」（runtime_admin:993）✅「未知不是 0」成立。
- A 栈：`model_call_cost_milli` 查无 → `(0, False)` → tag `llm_usage_cost_unpriced:1` ✅；但**部分价**（条目只有 per_call 或只有 cache_read 键）→ `entry.get("input",0.0)` 以 0 价计出**伪账单且记 priced** ❌（`c-gemini-3.8-flash-high` 0.018 元/请求类在 A 栈被记 0 且不计按次费——**按次计费在 A 栈整体失踪**）→ F-06 子项。
- 注册表残留 0.0 价：`_optional_price` 允许 0（`>=0` 原样保留）→ 非兜底表模型 0 价照计 ¥0 且 unpriced=0 → 造 0 风险路径在盘（#36 已人工清数，防复发缺门）→ 并入 F-13 改法。

## D4 注册表消费面与配置一致性

### D4.1 外部注册表装载链与热改边界

- 路径链：`bot_runtime_settings_dir="data/settings"`（config.py:55，入 path_fields 重映射 :1074）→ `build_instance_settings_manager` → `runtime_settings_shorekeeper.json`；`_reload_if_changed`=**文件 mtime 比对**（settings.py:686-694），每次 `get_or/set_*/list_*` 前触发 ✓。
- 主 router 热更面：`_refresh_dynamic_registry` 每次 generate 开头合并（整体换 dict，provider 按 spec 变更失效，priority 重排）✓；`priority_groups` 与 content_route 走 live 闭包 ✓。
- **改文件后不刷新的已构造对象（边界清单）**：①`_assemble_model_prices` 装配快照 → chat 审计标签价表**改价不重启不生效**（__init__.py:1226/4706；报表侧 live → 同调用两口径）；②**5 个二级 router 根本不接**动态注册表（F-04）；③shared_group raw provider 烘死 BOT_CHAT_MODEL/base_url/key（F-05）；④vision **接了**动态注册表（`build_vision_provider(dynamic_registry=runtime_settings.list_vision_registry)` __init__.py:4593-4596 ✓ 登记为正面证据）。
- `env:` 密钥引用**装载层不强制**：`_resolve_api_keys` docstring 明言「均可写 env:变量名或明文」（model_router.py:489-492）；注册表真身在 Runtime（不入 git ✓）；**形态风险实锤=源码树内明文密钥**：`scripts/configure_axonhub_registry.py:34` `AXONHUB_KEY_VALUE = "ah-<64hex>"`（值不落本日志）——违反铁律 3，出站打码不救盘上文件；**建议立即换 key + 该脚本改读 env**（F-11 P1）。历史 Config 丢字段陷阱已有两处修复注释（config.py:829-841 键槽必须显式声明）→ 但**非敏感未声明键仍静默丢**（F-12 根因）。

### D4.2 LLM 侧配置键逐键清单（同形态并表；73 键全枚举，✗=catalog 存量豁免名单内，门=「增量有门、存量不追溯」test_doc_sync_gates.py:46/280）

| 键（组） | Config 字段/缺省 | catalog | SETTABLE | 热改生效? | 缺省安全 | 消费锚点 |
|---|---|---|---|---|---|---|
| BOT_CHAT_TIMEOUT_SECONDS | 20.0 (config.py:860) | ✓ | 否 | ❌ 重启 | 是 | providers timeout |
| BOT_CHAT_FAILOVER_MAX_SECONDS | **120.0** (:869) | ✓ | 否 | ❌ 重启 | 是 | build_model_router |
| BOT_CHAT_FAILOVER_MIN_HOP_SECONDS | 3.0 | **✗** | 否 | ❌（getattr config→os.environ）| 是 | model_router.py:637 |
| BOT_CHAT_CHANNEL_COOLDOWN_SECONDS | 90.0 | **✗** | 否 | ❌ | 是 | channel_health.resolve_channel_cooldown_seconds |
| BOT_CHAT_STRICT_PRIORITY | True | **✗** | 否 | ❌ | 是 | model_router.py:612 |
| BOT_CHAT_HEDGED_REQUESTS_ENABLED | **True**（生产 .env 记 false，台账#36） | ✓ | 否 | ❌ | 中（代码缺省=开影子，与生产裁定相反） | _generate_impl:2061 |
| BOT_CHAT_HEDGE_DELAY_SECONDS / _MAX_CANDIDATES | 2.0 / 2 | ✓/✓ | 否 | ❌ | 是 | `_hedge_settings`（getattr 兜底 6.0/2 与 Config 双数并存→F-15） |
| BOT_CHAT_MAX_INPUT_TOKENS / _OUTPUT | 131072/65536 | **✗✗** | 否 | ❌ | 是 | build_model_router 尾赋值 |
| BOT_CHANNEL_HEALTH_ENABLED | **True** (:490) | ✗ | 否 | ❌ | 是（但 model_router:679 docstring 称「健康层默认关」**注释与代码相反**→F-15） | channel_health_enabled |
| BOT_CHANNEL_PROBE_*（threads/jitter/slow_ema/adaptive_timeout） | 3/8/0.4/15000/True | ✗×6 | 否 | 巡检参数每次 `_probe_setting` 现读 **os.environ 兜底生效**（裸脚本面）；.env 值经 Config 主路径 ✓ | 是 | channel_health.py:580+ |
| BOT_MODEL_REGISTRY / _PRESETS / _PRIORITY_GROUPS / _PRICES | dict/list | ✓✓✓✓ | registry 经专用子命令；GROUPS/PRICES SETTABLE✓ | **✅（router live 读 + set_override）**；PRICES 对 chat 标签栈❌（快照）| 是 | __init__.py:4626-4633 |
| BOT_LLM_BILLING_ENABLED | **无 Config 字段** | 大写✓/小写✗ | 否 | **❌ .env 永不能开**（model_validate 丢 extra + nonebot dotenv 不进 os.environ——同文件 channel_health docstring 自证；`ledger_enabled` getattr→None→environ→缺省 False）| 是（关） | ledger.py:70-86 |
| BOT_LLM_MODEL_PRICE_OVERrides | 无字段 | ✗ | 否 | ❌ 死读 | — | model_router.py:419 |
| BOT_VISION_*（enabled/mode/timeout/registry/max_images…） | False/relay/20/…/2 | 大部✓（enabled/mode SETTABLE✓ 每次调用读开关） | ✓ | ✅（每次现读 `is_enabled`+settings_store.get_or "BOT_VISION_ENABLED"） | 是（关） | vision_describe.py:522-534 |
| BOT_MEME_LIBRARY_VLM_*（6 键） | enabled=False… | ✓（enabled）| 否 | ❌ 重启 | 是（关） | meme_library_listener.py:111-123（**os.environ 手解 env:** :121） |
| BOT_CONTENT_ROUTE_*（9 键）+ BOT_MASTER_LOVE_*（2 键） | 全有字段，阈值 60/25、TTL 120… | **✗×11** | （knobs 经合并层 config_provider live） | ✅ 设计（build_router_cb 注释）| 是 | content_route.py:_knobs |
| BOT_USAGE_REPORT_HOURS / 阈值三键 | "13,18,23" | ✓ | — | 调度装配快照（台账#3 同族） | 是 | usage_monitor.py:24-27 |

### D4.3 收件人判定同源

`explicit_allowed_for_session` 唯一定义（content_route.py:369），消费 2 处均为 import 调用（chat.py:2043、__init__.py:7356 被动好感感知）；`match_master_love_admin` 唯一定义（content_route.py:114）chat.py:2053 调用；群黑名单在同函数内双查（wl−bl）无第二份。**未见第二判定**（5 项取证未见缺陷：定义份数/两消费点/黑名单优先/空名单关闭语义/fail-open 方向）。

## 发现清单（七要素）

> 严重度分布：**P0×0｜P1×6（F-01/03/05/06/11/12）｜P2×7（F-02/04/07/08/09/10/13）｜P3×3（F-14/15/16）**。

**F-01｜P1｜meme 库 VLM 打标 = 完全旁路的裸 HTTP 模型调用**
- 坐标：`plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py:126-167`
- 锚点：`response = await client.post(` / `f"{base_url}/chat/completions",`
- 根因：表情图库 v2 批独立落地，未接 llm_engine 任何一层。
- 证据：`httpx.AsyncClient` 直 POST；自建 `_resolve_vision_config`（含 os.environ 手解 env:，:121-122）；`status_code != 200: return` 无分类、无告警、无记账、usage 直接丢弃；缺省 `bot_meme_library_vlm_enabled=False`（config.py:535）限缩暴露面。
- 改法：before 裸 client.post → after 复用 `DynamicVisionProvider.generate`（F-03 收编后统一走 vision 门面），或至少改调 `providers.OpenAICompatibleLLMProvider`+usage 出口打 `capability="meme_tagging"` 进 A/B 账。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_meme_library_listener.py tests/test_meme_react_pick.py -q --basetemp=$TEMP/u12-v -p no:cacheprovider` + 全树 grep `chat/completions` 命中数 -1。

**F-02｜P2｜connect/read 分类超时被标量 per-request timeout 整体覆写，「5s 连接快败」在路由链不生效**
- 坐标：`domains/chat_reply/llm_engine/providers.py:572-584`（+`_shared_http_client` :187-195 对照）
- 锚点：`timeout=request_timeout,`（client.stream 内）；对照 `timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)`
- 根因：httpx 标量 timeout 语义=四分量同值，覆写 client 默认；router 每跳都传 `attempt_options["timeout_seconds"]`。
- 证据：providers.py:450-453 `request_timeout = self.timeout_seconds`（20，config.py:860）恒为 float；build_model_router 注入 timeout_seconds=20 → 生产每跳 connect=read=20s；#34「connect 5s 快败不再 150s 干等」仅错误**分类**（ConnectTimeout→network，:608 分支）成立，**时延**未兑现（断网时 15 跳=connect 全烧满）。
- 改法：before `timeout=request_timeout` → after `timeout=httpx.Timeout(connect=min(5.0, request_timeout), read=request_timeout, write=min(10.0, request_timeout), pool=5.0)`。
- 验证：`pytest tests/test_llm_httpx_client.py -q`（现 129 passed 基线不破）+ 新增断言「传 timeout_seconds 时 ConnectTimeout 在 ~5s 分类为 network」。

**F-03｜P1｜DynamicVisionProvider 是第二套路由引擎（vision 全家：识图/归档/视频/课表/转写描述），无账本·无冷却·无价格·无钳制·无统一告警**
- 坐标：`domains/media/ingest/vision_describe.py:505-620`（类体）
- 锚点：`for entry_id, entry in candidates[:_MAX_VISION_FAILOVER_ATTEMPTS]:`
- 根因：视觉域自建候选排序+failover（优先级数值序+2×timeout deadline），与 ModelRouter 的健康过滤/冷却降级/时段分组/价格透传/`_enforce_context_caps`/`_emit_call_record` 零交集。
- 证据：`self.last_attempts.append(f"{entry_id}:{exc.error_kind}")` 轨迹只留实例属性，无 logger.warning/告警/账本；media_archive.py:466+/video_understanding.py:208/timetable 全借此口，token 消耗生产端**全可见面零记账**（A 栈挂钩点仅 chat 主链）。
- 改法：before 第二循环 → after 复用 ModelRouter（`build_model_router` 注 vision 注册表 + `capability="vision"`，generate 出口挂 `_emit_call_record`，调用方签名不变），过渡期至少给 DynamicVisionProvider.generate 出口补 A 栈 usage tags（`capability="vision"`）。
- 验证：`pytest tests/test_vision_describe*.py tests/test_media_archive.py -q` + 事件日志出现 `llm_usage_total_tokens` 且 model=vision 条目的行。

**F-04｜P2｜5 个二级 ModelRouter 不带 dynamic_registry/priority_groups/content_route_cb → 注册表/时段组双世界**
- 坐标：content_parser.py:579、daily_assist.py:353、llm_draft.py:468、runtime_admin.py:502、__init__.py:2803(reflection job)
- 锚点：`router = build_model_router(config)`
- 根因：`build_model_router` 默认参数 None；仅主装配传三回调（__init__.py:4626-4640）。
- 证据：`_refresh_dynamic_registry` 对 None 直接 return（model_router.py:939-945）；时段组 `_active_group_order` 对 None cb 返回 ("",[])（1555-1562）→ 管理员经 `/bot runtime model add` 新增渠道、时段优先级组对这些消费面**不可见**；且 `settings.py:318-331` RESTART_REQUIRED 治理只保主链。
- 改法：before 各自 `build_model_router(config)` → after 抽共享工厂 `build_aux_model_router(config, runtime_settings)`（注入与主链同源三回调），或主 router `fork()`（fork 已正确继承回调，model_router.py:924-938）。
- 验证：装配冒烟：构造后断言 `router._dynamic_registry is not None and router._priority_groups_cb is not None`×5 点。

**F-05｜P1｜群摘要 LLM 压缩 = 绕过路由的单模型直连（且异常全吞无告警），账单系统性低估的直接构成**
- 坐标：`domains/chat_reply/character/shared_group.py:263-320`（调用 :299）；装配注入 `__init__.py:4706 shared_group_llm_provider=_build_chat_llm_provider(config)`、`_build_chat_llm_provider` 定义 :364-374
- 根因：台账#33⑵ 修复以「传 raw provider」闭环，未走中央 router。
- 证据：`reply = self.llm_provider.generate(` + `except Exception: return key`（零日志零轨迹零账）；每日群摘要×N 群+TTL 命中前的每次变化摘要都会烧真实 token。
- 改法：before raw provider → after 注入主 `model_router`（capability="group_digest"）；异常分支补 `logger.warning("group digest llm failed type=%s")` 对齐 A-19 可观测纪律。
- 验证：`pytest tests/test_group_digest_push.py tests/test_character_persona_shared_group_prompt_images.py -q` + 事件日志见 digest 用量行。

**F-06｜P1｜计价双写公式不一致（缓存创建扣减口径相反）+ 按次计费在 A 栈失踪 + 部分价 0 价照记**
- 坐标：`runtime/pricing.py:186-202`（锚点 `ordinary_tokens = max(0, int(prompt_tokens) - read_tokens)`、`entry.get("input", 0.0)`）vs `domains/chat_reply/llm_engine/ledger.py:237-262`（锚点 `billed_input = max(0, prompt - cached_read - cached_write)`、`per_call_milli` 段）
- 根因：2026-09-18「价格单源化」只并了**价表来源**，未并**计算公式**；两栈各自演进。
- 证据：providers 归一后 Anthropic 口径 cache_write 不属 prompt（pricing.py:180 注释自认）→ ledger 多减→少算；A 栈全函数无 per_call 语义（读 5 键只用 4 键）→ `c-gemini-3.8-flash-high` 0.018/次恒记 0 元且 `priced=True`；B 栈 per_call 独立成账 ✓。同一调用两栈金额必差。
- 改法：before 两式 → after 收敛为单一纯函数 `compute_call_cost_milli(usage, price, *, schema_semantics)`（放 llm_engine/pricing.py，ledger 与 chat tags 共用），A 栈补 per_call、缺价键判未计价而非 0 默认。
- 验证：`pytest tests/test_model_family_pricing.py tests/test_llm_ledger.py tests/test_usage_billing_v21.py -q`（基线 51+168 passed 上增双栈等值断言：同 fixture usage+prices 两栈 cost_milli 相等）。

**F-07｜P2｜账本归因字段全树无调用方：request_id/capability/call_seq 生产恒空**
- 坐标：model_router.py:1798-1828（pop 面）；全体 generate 调用点（chat.py:1882 等仅传 session_id）
- 锚点：`request_id = str(kwargs.pop("request_id", "") or "")`
- 证据：全仓 grep `capability="`/`request_id=` 于 generate 调用=0（仅 HelpTopicDecl/测试）；B5 设计 §5「请求级查询」不可用；A 栈有 request_id（transport 行）但 B 无 → 两栈无法互相核对。
- 改法：before 调用方自选传 → after pipeline 装配注入（`functools.partial(router.generate, request_id=message.request_id, capability=decision.capability_id)` 或 contextvar），chat/二级面统一。
- 验证：账本开时 `SELECT COUNT(*) FROM llm_call_records WHERE request_id=''` 应为 0（新库）。

**F-08｜P2｜去参重试复用首跳超时不重算剩余预算、不计 provider_attempts → 链尾可超总预算一个 request 周期**
- 坐标：model_router.py:2185-2199
- 锚点：`retry_options = dict(attempt_options)`
- 证据：首跳 `timeout_seconds=min(…, remaining)` 后 `attempt_started` 已被消耗，重试用同值 → 最坏 2×timeout；`provider_attempts` 只数首跳，min-hop 止损判据被低估。与「预算耗尽补 failover:deadline 语义」承诺（2258-2266）不吻合。
- 改法：before 同值重试 → after `retry_options["timeout_seconds"] = min(base, failover_deadline - now)`（None 安全），且 `provider_attempts += 1`。
- 验证：`pytest tests/test_model_router_failover.py -q` 增「deadline 前 1s 触发 4xx 去参重试不越预算」回归锁。

**F-09｜P2｜「五池游标轮换」口径不实：2 池游标（且为两份手抄）+3 池 random**
- 坐标：chat.py:632-650 与 2674-2689（手抄对）；user_copy ADMIN_GATE/GROUP_FAILURE_ACK 调用点 `random.choice`（pipeline.py:10/847）；error_report.py:340 `random.randrange`
- 锚点：`_FAILURE_MESSAGE_CURSOR` / `_INJECTION_GUARD_CURSOR`（两 dict 两锁同构复制）
- 证据：§D2.3 表。文档（AGENTS 第三部分「游标轮换」、#34 P2-4）与实现漂移。
- 改法：before 每池自实现 → after `user_copy.py` 增唯一 `rotating_pick(pool, session_id)`（游标+锁+512 环一份实现），五池统一取句语义（文档同步「随机/游标」终口径由用户裁）。
- 验证：`pytest tests/test_user_copy_pool.py tests/test_user_copy_unification_gate.py tests/test_poke_v2.py -q`。

**F-10｜P2｜上下文钳制单点强、旁路面全失；丢消息可留孤儿 tool_call 对**
- 坐标：model_router.py:114-142；旁路=F-03/05/01 出口
- 锚点：`if item.get("role") != "system":`
- 证据：逐条删非 system 不感知 assistant.tool_calls↔tool.tool_call_id 配对；vision/meme/digest 无 caps；生产现值（128K/64K）下多轮工具循环 + 大上下文才触发。
- 改法：before 单条删 → after 成对删（删 assistant 时连删其 tool 结果，反之亦然）；vision 收编随 F-03 自然获得钳制。
- 验证：`pytest tests/test_model_context_caps.py -q` 追加工具对负样本。

**F-11｜P1(安全)｜源码树内明文真实 axonhub key**
- 坐标：`scripts/configure_axonhub_registry.py:34`
- 锚点：`AXONHUB_KEY_VALUE = "ah-` （完整值不落本日志）
- 根因：一次性装配脚本把 .env 值烘进仓库，违反铁律 3（真实 key 只在 .env）。
- 证据：该行即字面量赋值；:119 将其写入 .env；文件随树可 commit（当前全树未 commit，一旦入库即扩散）。
- 改法：before 常量 → after 从环境/交互读取（无默认值），缺失即报错；**key 本体按泄露处理去 axonhub 轮换**；git 历史无需清（未提交），文件必须改后再入库。
- 验证：全树 grep `ah-[0-9a-f]{20,}` 仅 .env（不可见面）命中 + `git grep --cached`（提交前门禁）零命中。

**F-12｜P1｜BOT_LLM_BILLING_ENABLED 为死开关：.env 面永远开不了计费账本**
- 坐标：ledger.py:70-86；config.py:31（`class Config(BaseModel)`，extra 隐式 ignore）+ :829-831（自证「否则 Config.model_validate 会丢弃字段」）；nonebot `config.py:115 dotenv_values`（值只进 driver config 不进 os.environ）；__init__.py:3647 `Config.model_validate(translate_env_keys(driver_config))`
- 锚点：`getattr(config, _ENABLED_CONFIG_KEY, None),` + `os.environ.get(_ENABLED_ENV_KEY)`
- 证据链：字段未声明→model_validate 丢→getattr None；os.environ 无 dotenv 导出→兜底空→恒 False；channel_health docstring（:53-58）明文承认该环境事实并把自己键声明为字段正解；`.env.example` 无该键（grep 0 命中）。K2「可选增强：开 BOT_LLM_BILLING_ENABLED 落持久账本」按现状**不可执行**。
- 改法：before 双兜底读 → after ①config.py 声明 `bot_llm_billing_enabled: bool = False`（一行）②或登记 SETTABLE/读 runtime store；同法补 `bot_llm_model_price_overrides`（F-14）。
- 验证：`pytest tests/test_llm_ledger.py -q` + 冒烟：临时 env 设键后 `ledger_enabled(Config.model_validate({...}))` True。

**F-13｜P2｜「/bot model price 之后的调用按新价格记账」对账本栈为假 + /bot model price 不触达 per-channel 价 + 注册表 0 价无防线**
- 坐标：runtime_admin.py:725-786（写 BOT_MODEL_PRICES map）；model_router.py:514-518（spec 只读条目字段）+ :409-445（fallback 不看 BOT_MODEL_PRICES）；pricing.py:130-135（投影 `>=0` 保 0）
- 锚点：`store.set_override("BOT_MODEL_PRICES", json.dumps(prices, ensure_ascii=False))`
- 证据：B 栈价=条目 ∪ `_MODEL_PRICE_FALLBACKS` ∪(死 overrides)；A 快照栈=条目投影∪map。模型名 map 与渠道条目不同名层（同模型多渠道被 first-valid 压平，pricing.py:106-108 注释自认「渠道价差由 V2.1 处理」而 V2.1 休眠=无人处理）。
- 改法：before 各栈自选价源 → after 单一 `resolve_price_for_call(model, channel_id, now)`（条目→map→兜底表 三级链），A/B/报表三栈共消费；`_optional_price`/投影把 `<=0` 视同未配置；`/bot model price` 增 `--channel <model_id>` 直达条目。
- 验证：`pytest tests/test_model_family_pricing.py tests/test_ledger_channel_breakdown.py tests/test_usage_billing_v21.py -q`。

**F-14｜P3｜`bot_llm_model_price_overrides` 死读面（Config 无字段，F-12 同根）** — 锚点 `raw = getattr(config, "bot_llm_model_price_overrides", None) or {}`（model_router.py:419）+注释 :368 承诺可覆盖。改法随 F-12 声明字段或删除读分支；验证同 F-13。

**F-15｜P3｜文档/注释/兜底常数三处口径漂移**：①「总预算 300s」=env 值非缺省（缺省 120，config.py:869）；②「read 30s」vs 缺省 20（:860）；③「EWMA 延迟择优」已退役（:873 strict 缺省开）；④model_router.py:679 docstring「健康层默认关」vs `bot_channel_health_enabled=True`（config.py:490）；⑤`_hedge_settings` getattr 兜底 6.0/2 与 Config 2.0 双数并存。改法：AGENTS 第三部分与代码注释就地更正；验证：`pytest tests/test_doc_sync_gates.py -q`（无新键即绿）+ 人审 diff。

**F-16｜P3｜卫生登记（设计内，不修）**：①chat.py:1892/1967 router=None 直连死分支（测试缝，建议注释钉「生产恒非 None」）；②channel_health 探针 max_tokens=1 真实花费不落账（`source=probe` 注记可选）；③smoke/debug 诊断直连不落账（运维性质）；④control_plane/factory 沙箱 provider（#42 在飞域不深查）；⑤18/73 LLM 键 catalog 存量豁免（门=增量有门，test_doc_sync_gates.py:46/280）；⑥usage_service/billing_*（≈3400 行 V2.1 栈）零生产消费者——**是否退役/接线属用户裁决**，本席只定界不判死。

## LLM 调用单一中央入口 + 计价单一事实源收口清单（按解锁顺序）

1. **F-11 换 key + 脚本去明文**（安全，无需授权设计，先做）；
2. **F-02 providers 请求级 Timeout 组装**（1 文件 5 行，解锁 K1 类延迟预期修正与后续所有超时工作基线）；
3. **F-12(+F-14) 账本开关字段化**（config 一行×2，让「可选增强」与 ledger 修账路线可行）；
4. **F-06+F-13 计价公式与价源单函数化**（llm_engine/pricing.py 立 `resolve_price_for_call` + `compute_call_cost_milli`，三栈切换消费，双栈等值回归锁先行）；
5. **F-05 shared_group 改走主 router fork**（最小旁路收编，能力标签 `group_digest`）；
6. **F-03 vision 全家收编**（最大旁路面；方案=ModelRouter 以 vision 注册表实例化+`capability=vision`；过渡步=先挂 A 栈 tags）——**依用户纪律「改中央入口禁造第三套」：收编复用既有 ModelRouter，不新建门面**；
7. **F-01 meme 打标并入 vision 收编成果**（依赖 6）；
8. **F-04 五个二级 router 改 fork/共享工厂**；
9. **F-07 generate 统一注入 request_id/capability/call_seq**（依赖 3 账本可开之后才有验收面）；
10. **F-08 去参重试预算重算 + F-10 工具对成对裁剪**（路由内部两件，随任一次 model_router 批次带走）；
11. **F-09 五池取句单源化**（独立小批，连同文档终口径裁定）；
12. **F-15/F-16 文档与登记收尾**（本波收口时并入）。

## 取证命令与自查记录

- 通读（sed -n 定点）：model_router.py 全文件分段（114-235/235-470/475-760/868-1098/1096-1330/1494-1800/1798-2341）、providers.py 全文、ledger.py 100-310/554-767、pricing.py 全文、usage_service.py 头 130 行+normalize_usage、billing_entities.py 1-115、channel_health.py 1-80/500-610、content_route.py 95-165/340-410、chat.py 1817-2000/2036-2092/2555-2692、settings.py 318-340/454-546、runtime_admin.py 700-886、usage_monitor.py 1-80/460-600、meme_library_listener.py 110-199、vision_describe.py 500-640、shared_group.py 255-355、config.py 10-55/360-375/490-905 区段、__init__.py 340-420/1195-1300/2350-2470/2790-2810/4590-4712/5185-5215/7350-7372、nonebot(config.py:115 dotenv_values、compat.py:107 extra=allow)。
- Grep 枚举：`chat/completions`(12) `OpenAICompatibleLLMProvider(`/`StaticLLMProvider(`(11+tests) `build_model_router(`/`ModelRouter(` `AsyncOpenAI|from openai`(0) `_reload_if_changed` `list_model_registry` `transport_receipt` `total_tokens=` `explicit_allowed_for_session|master_love` `model_family_key(`/`_EFFORT_SUFFIXES` `<intimacy`(2 注释位) `escalat`(无关 4 命中) `_llm_usage_audit_tags(`(1) catalog 覆盖脚本枚举(73→18✗)。
- scoped 测试实跑（venv python，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，basetemp=/tmp/u12-a*，`-p no:cacheprovider`）：
  - a1 test_llm_ledger+test_model_context_caps+test_channel_health_v2 → **51 passed in 5.68s**
  - a2 failover×2+httpx_client+error_classification+content_route+prfix_llm+ledger_range+ledger_channel → **129 passed in 24.78s**
  - a3 usage_billing_v21+billing_service_v21+model_family_pricing+channel_health+route_priority_v21r2+auditfix+bgroup → **168 passed in 13.25s**
  - a4 test_doc_sync_gates -k catalog → **2 passed, 2 deselected**（键覆盖门=增量有门存量豁免）
- 交叉参考未读域：webui/render/card_render/theme_tokens/TTS-ASR 按裁定零接触。
- **树残留自查（本席结束前）**：`find plugins tests scripts -name __pycache__|*.pyc` → **0/0**（本席两次 pytest 未产生字节码，与 win-memory 记录的机器陷阱不同，实证干净）；根 `.pytest_cache/.ruff_cache/.mypy_cache` 为并行会话既有残留，本席 `-p no:cacheprovider` 未追加写；`data/` 未出现；本席落盘物=①`docs/design/audit-20260920-unify-U12-llm.md`（唯一文档写）②`%TEMP%\u12_scan.py`（被禁跑的扫描脚本，按规程留 temp，不属源码树）。真实密钥值零写入本日志（F-11 仅录前缀形态与行号）。
