# v21r2 R1 席 — LLM 路由族工作日志（重派二轮）

> 席位：R1（llm/model_router.py + llm/channel_health.py + runtime/alerts.py + 新测试）。
> 前任 15 分钟撞 1302 未落盘，本轮从头做。开工时间 2026-09-17 晚。
> 文件域铁律：content_route.py / providers.py / chat.py / __init__.py 只读。

## 一、根因清单（file:line，行号为开工时快照）

### (a) 链烧穿 8-17 跳
1. `model_router.py:1804-1813` — 串行故障转移循环对每个候选只检查「预算已耗尽（remaining<=0）」；
   剩余预算只剩残秒时仍发起新跳（timeout 被钳到残秒，注定超时），白烧一跳并制造噪声记号。
   `chain=16 failover:deadline` = 16 跳烧满 300s 预算的直接观测。
2. `channel_health.py:30-32` — 健康层只有「连续 2 次失败→unavailable（30 分钟重探）」一档；
   **首跳失败（consecutive_fails=1）后渠道仍留在队列头部**，下一轮请求同一条坏渠道继续当首发，
   每轮重新烧 20s 读超时。缺一档「近期失败短期冷却降级」。
3. `model_router.py:911-949`（channels_for_model）— 同名模型渠道聚合排序在
   `latency_first` 开启时按 EWMA 重排（现默认关，见 #35①/`channel_health.py:343-356`）；
   关闭时按 **价格均值优先、priority 次之**（:932/:940/:946）——价格序仍是低优先级渠道
   反超高优先级的残留通道（#36四段已把注册表瘦身为 17 条并修 priority，本席补排序语义）。

### (b) 优先级被违反（恒星纪元-Gemini 被浅夜抢流量）
4. 同上 #3：EWMA 重排（历史根因，#35①已对 content_route 头插改为注册表序、
   `channel_health_latency_first` 默认 False）+ 价格序残留。用户令「永远按注册表优先级处理」
   → 新增 `bot_chat_strict_priority`（默认 True）：同名模型聚合序 = (priority, [EWMA 同级
   tiebreak], 价格)；EWMA 降级为**同优先级内的 tiebreak**，永不跨优先级反超。

### (c) grok 20s 挂起被掐（axonhub 上游挂起）
5. providers.py connect 5s/read 20s 不改（用户令，axon-grok 健康 ema≈11.5s）。
   bot 侧补**逐跳失败日志**（model/kind/耗时/timeout/intimate 标记），超时被掐时日志可辨；
   配合冷却降级，挂起渠道下一轮不再首发。`_auto_route_ids` INTIMATE 头插已按注册表序
   （model_router.py:1393-1414，#35①成果），影子并发 INTIMATE 跳过已存在
   （model_router.py:1749-1771）。A1 裁定（拒绝模板句只记日志不重试）已在 #36①落实——
   本席核实 model_router 无升级重试残留，零改动。

### (e) INTIMATE grok 钉第一
6. 现状缺口：冷却/健康过滤可能把 grok 挤下第一而无任何日志。补：INTIMATE 态下若
   grok 家族渠道存在于候选但未排首（熔断冷却或健康不可用）→ warning 日志
   「grok 熔断中，临时回落」。重排保护：冷却降级只把**冷却中的渠道**移队尾，
   未冷却的 grok 渠道自然保持第一。

### 告警刷屏
7. 300s 抑制已接线：`__init__.py:3555`（持久 AdminAlertSuppression 实例）+
   `sender/worker.py:42`；抑制键=(stage, kind, source, target)（alerts.py:175-194）。
   缺口：stage=llm 的不同 kind（network/timeout/deadline）各自占抑制槽，故障期每窗口
   可出 4+ 条。补：llm 族 kind 折叠聚合（同窗口不同 kind 折进一条，kinds 清单随文本带出，
   信息不丢）+ chain detail 压缩。

## 二、改动清单

### 前任成果（R1c 接手 git diff 取证实证，未重做）
- **model_router.py**（88148→98364B，mtime 23:56）：(a) `_strict_priority_enabled`（缺省开）+ `channels_for_model` 重写为注册表 priority 主键、EWMA/价格同级 tiebreak（false=旧行为逃生门）；(c) `_failover_min_hop_seconds`（缺省 3s）+ 串行循环/影子 worker（key_index>0）双止损；(d) INTIMATE grok 钉一守卫 + 熔断临时回落 warning（demoted/health_filtered 分开呈现）；逐跳失败日志 `llm route hop failed model= family= kind= elapsed_ms= timeout= intimate=`（两处失败路径）；冷却降级 `_demote_cooling_candidates` 接线 + demote 日志；影子 INTIMATE 跳过统一判定（`_intimate_session` 单次回调）。
- **channel_health.py**（25836→30195B，mtime 00:03）：`cooldown_until` 列自动迁移（SQLite 落盘重启不丢）+ `record_failure(cooldown_seconds)` + `cooling_ids()` + `demote_cooling_candidates()`（降级不剔除、全冷却原序放行）+ `resolve_channel_cooldown_seconds()`（缺省 90s）；`channel_health_latency_first` 缺省 True→False（2026-09-16 用户裁定）。
- **alerts.py**：(e) llm stage kind 折叠抑制（`fold_kind_stages={"llm"}`，同窗口跨 kind 共槽）+ `last_report_kinds_for_issue`（放行时 kinds 清单随行 `llm_kinds=[a|b|c]`，信息不丢）+ chain detail 压缩（`network chain=17 last=x` → `chain=17跳全败 last=x`，≤72 字）；非 llm stage 行为面不变。
- **config 三键三处同生全齐**：config.py:812-818 + docs/config-catalog-full.md:806 + .env.example:182-186。
- tests/test_llm_route_priority_v21r2.py 前任 19 例。

### R1c 续跑席补齐（2026-09-18 凌晨）
1. **f① 坐标 A**：chat.py `_apply_content_route_reply` 的 logger.info 加 `attempts=%s`（值 `reply.attempts`）——INTIMATE 会话 grok 超时后 failover 到 gemini 成功的无告警场景，一行即可看出 grok 死过。坐标 B 不另做：前任逐跳 warning 已带 family/intimate，再记 `intimate_route_failover` 属双写冗余。
2. **R7① 裁决=修复**：`_auto_route_ids` 组内 order 条目扩收**模型名/别名**（名称展开=该模型全部渠道，沿注册表 (priority, model_id) 序；渠道 id 条目照旧；混排去重）。R7 判断**属实**——生产 .env 写真模型名而注册表 id 形如 `axon-gemini-38f`，旧实现 `model_id in known` 恒不命中，BOT_MODEL_PRIORITY_GROUPS 自引入以来从未生效。修复后分组才真正可重排模型先后；生产现配置（单组 4 名）展开序与注册表 priority 序一致 → 重启后行为不变、零风险。parse_priority_groups docstring 同步。
3. **回归护栏修复①（自适应超时解耦）**：`_health_ema_latencies` 增 `require_latency_first` 形参（排序消费方缺省 True 保持门控；`_generate_impl` 自适应超时消费方传 False）。前任把 latency_first 缺省改关后，自适应超时（挂死渠道快失败）被连带静默关闭——test_channel_health_v2::test_adaptive_timeout_tightens_by_ema 抓到（captured=[] ≠ [8.0]）。排序裁定管「排序」不管「快失败」，解耦。
4. **回归护栏修复②（旧价格序期望更新）**：test_model_router_channel_failover::test_model_name_override_does_not_retry_sibling_in_tail 断言更新为 ch-a(prio2)→ch-b(prio5)→other——旧断言编码的正是用户裁掉的「价格均值优先」行为；被测性质「兄弟渠道只试一次」保留并加双 count 断言加固。
5. 测试补 4 例（分组 order 收模型名 / 照旧收渠道 id / 混排+同名展开去重 / 未知条目忽略）+ `_router` 夹具增 priority_groups 参数；清前任遗留未用变量 + import 排序（ruff --fix）。

## 三、R7 移交三项裁决
1. **BOT_MODEL_PRIORITY_GROUPS 疑似恒 no-op** —— **属实，已修复**（见改动清单 2，4 例回归锁）。
2. **gemini -high/c-caps 变体不进 intimate 精确名匹配** —— **裁决：维持精确名匹配，不扩**。理由：①变体计价与推理档不同，自动并入头部即绕开「成本三刀」，且 INTIMATE 本就抑制 effort 升档、再自动引 -high 变体自相矛盾；②grok 组整体在前+主 gemini 渠道紧随，变体垫底仅影响极深 hop；③用户真需变体上车时在 `bot_content_route_order` 显式写变体名即可——head 匹配本就支持任何精确模型名/别名，零改码。
3. **store 残留 gpt-5.6-luna 渠道行** —— **裁决：保留不清理（无害残留）**。理由：路由候选只从当前注册表 specs 生成，stale id 永不入候选，cooling/unavailable/EMA 表对不存在 id 零命中，清库收益为零反增 Runtime 写入风险。default 兜底 spec 以非 manual 参与自动路由属设计内行为，不动。

## 四、实跑证据（全部直跑，解释器=Runtime venv，PYTHONDONTWRITEBYTECODE=1，--basetemp=$TEMP/v21r2-r1c*）
- 接手取证：前任 19 例 `19 passed in 2.72s`。
- 收口后本文件：`23 passed in 3.37s`。
- 回归 16 文件（channel_health/v2/probe_config、llm_error_classification/httpx_client/ledger/route_priority、model_admin_and_schedule/context_caps/effort_groups_and_pricing/family_pricing/router_channel_failover/router_failover、a20/f03/operational_failures/subscription_outbox）：`253 passed, 1 failed`——唯一失败 `test_operational_failures.py::test_queue_worker_notifies_typed_failure_without_blocking_state_update`，根因=**R2 席在飞 WIP**（sender/worker.py `_notify_operational_issue_safely` 新增 kind=bot_unavailable 静默跳过，112 行未提交 diff；sender/* 本席禁触），该测试期望未同步，**与本席改动面零交集**，移交 R2 收口。
- test_doc_sync_gates.py：`4 passed`（catalog 三键登记一致）。
- ruff：全部触达文件（model_router/channel_health/alerts/chat/两测试文件）`All checks passed`。
- mypy（dev.ps1 同参 --explicit-package-bases --ignore-missing-imports）：model_router/channel_health/alerts/chat **本体零错误**；依赖链带出 5 错全在 timesync×2（他席在飞）/kb_wiki×1/control_plane platform×2（既有基线）。
- 超时值零改动：providers connect 5s/read 20s 未触（只读）；预算 300s 在 .env（gitignored，未动）；止损 3s 为新增键非改值。

## 五、遗留
- R2 席收口 1 例测试期望（sender/worker.py 域，见 §四）。
- BOT_MODEL_PRIORITY_GROUPS 修复使分组配置真正生效：生产现配置与注册表序同序、重启零行为差；用户未来改分组序时段重排即真生效（建议真机观察路由日志）。
- alerts kind 折叠（`llm_kinds=[...]`）与 INTIMATE 回落日志真机形态待重启观察。
- 未 commit（共享工作树，提交裁决权在用户）。

## 六、FIX2 收口记录（2026-09-18，小债清收席）

- **债**：简报移交 `test_auditfix_llm_route` 价格聚合断言 1 红（疑本席 channel_health/model_router 改动交互）。
- **取证与裁决**：`channels_for_model` 现行缺省=严格注册表优先级（`bot_chat_strict_priority` 缺省开，用户令「永远按注册表优先级处理」，价格仅同级 tiebreak）；红点断言 `ids[0]=="cheap"`（价格升序）编码的正是被用户裁掉的旧「价格均值优先」行为——与 §三回归护栏修复②（test_model_router_channel_failover 同款更新）同一裁决。**聚合逻辑零缺陷，`model_router.py`/`channel_health.py` 零改动**。
- **修**：测试改名 `test_route_ids_unknown_model_name_aggregates_by_strict_priority`，断言更新为 expensive(prio1)→cheap(prio5) + `other` 兜底（聚合性质=按模型名聚合同模型全部渠道+其余模型接自动队列，保留），注释记录裁决依据与先例。
- **实跑**：`test_auditfix_llm_route.py` **15 passed**；router/llm 回归 10 文件（model_router_channel_failover/model_router_failover/channel_health/channel_health_v2/channel_probe_config/llm_route_priority_v21r2/bgroup_llm_route/llm_ledger/ledger_channel_breakdown/llm_error_classification）并入 FIX2 回归批 207 passed 全绿；ruff All checks passed。未 commit。
