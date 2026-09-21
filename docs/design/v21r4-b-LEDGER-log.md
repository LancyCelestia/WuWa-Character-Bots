# v21r4-B LEDGER 席位日志（B6 只读调研）

> 断点续跑依据。每 15–20 分钟追加。

## 2026-09-18 开工

- 已登记协调表 v21r4-b-coordination.md（LEDGER | B6 行）。
- 已读 HANDOFF-V21R4-B-20260918.md §四 B6 + backend-protocol-plan.md B6 节。
- 坐标初探完成：
  - ① 搜索：sources/web_search.py、acg_search.py、search_service.py、search_intent.py、search_api.py、mcp_web_search_server.py、meme_search.py、sauce_search.py。
  - ② 合并转发：__init__.py:1007 `_forward_message_text`（门 863-889 区域）；vision_describe.py 上限实为 **25MB/25s**（2026-09-18 用户裁定 8→20→25），任务书所写 20MB 为旧口径，memo 中修正。
  - ③ 提醒：character/memory_extract.py + domains/schedule/capabilities/reminder.py。
  - ④ LLM：v21r2-r1-llmroute-log.md（R1 席）+ llm/model_router.py 待核。
  - ⑤ 亲密话术：v21r2-rp-style-log.md（RP 席）为指针候选。
- 进行中：逐项取证。

## 2026-09-18 LEDGER-b 续跑

> LEDGER 席因网络瞬断阵亡，LEDGER-b 接手，从逐项取证续跑，未重做初探。

### ② 合并转发 — 取证完成（已闭环，待重启生效 + live 观察）

- **递归展开三闸**（真身 `plugins/bot_unified_runtime/__init__.py`，行号为 2026-09-18 快照）：
  - 常量 `__init__.py:874-875`：`_FORWARD_NESTED_MAX_DEPTH = 3`、`_FORWARD_NESTED_MAX_TOTAL = 12`；
  - 总超时预算 `__init__.py:1031-1033`：deadline = `bot_forward_fetch_timeout_seconds × (深度+1)`，子反查 `_fetch` 取「单次上限与剩余预算」较小值（`__init__.py:1037-1043`）；
  - 环引用：`seen` 集合同 id 只取一次（`__init__.py:1034`、`:1054-1055`）；
  - 递归展开主体 `_expand`（`__init__.py:1045-1071`），失败路径 warning 可观测（`:1060-1067`、`:1075-1085`、`:1087-1092`）。
- **配置注入**：`config.py:725` `bot_forward_fetch_timeout_seconds: float = 5.0`（注意：`__init__.py:864` 模块级回退常量仍写 10.0，但实际消费点 `__init__.py:7245`/`:7786` 均以 config 值 + 5.0 兜底，模块常量仅在 config 属性缺失时生效——已核实非缺口，属回退语义）；消费点 `__init__.py:7245`、`:7786`。
- **大图 25MB/25s**（真身 `domains/media/ingest/vision_describe.py`）：
  - 远程：`_MAX_REMOTE_IMAGE_BYTES = 25_000_000`（`:239`）+ `_REMOTE_DOWNLOAD_TIMEOUT = 25.0`（`:240`）；注释 `:241-244` 记录 8MB→20MB→25MB 三段放宽史（25MB=2026-09-18 用户裁定）；
  - 本地：`_MAX_LOCAL_IMAGE_INPUT_BYTES = 25_000_000`（`:78`）；进 VLM 前先 PIL 缩边 2048（`:79`、`:139-140`），data URL 实际 <5MB（`:71-72` `_MAX_DIRECT_IMAGE_BYTES = 3_500_000`）。
- **测试**：`tests/test_forward_message_ingest.py`、`tests/test_perf_forward.py` 存在（文件级证据；用例数未逐一清点）。
- **结论**：无余量缺口。状态=**已闭环待重启生效 + live 观察**（观察点见 memo：嵌套转发实聊、>20MB 图识别、5s 超时预算下三层嵌套是否够用）。

### ⑤ 亲密话术 — 边界说明定稿（本波不动）

- 指针：`docs/design/v21r2-rp-style-log.md`（v21r2 RP 席，2026-09-18 实施完毕：复读三连根因+文风池化轮换+INTIMATE/normal 动作描写条件开关+persona 源四处改写，7 例测试+回归 190 passed）。
- 遗留三项全在 RP 日志 §七：输出侧硬保证（normal 态 strip_action_brackets，涉 bot_persona_action_brackets 默认语义，待用户裁决）、核心知识.md 战斗语音负向示例（实测仍复读才加）、INTIMATE 判定代理「会话态」非逐句分类（既有裁定语义）。
- B6 口径：亲密话术属人格域资产（personas/ + chat.py 提示词），按波次分工需与人格域协同，**本波不动**；B6 只留指针不提方案。

### ① 搜索时效 — 取证完成（三方案提案，待用户裁定）

- 缓存现状五处：web 链同步 600s（`domains/core/search/web_search.py:460`，异步不缓存）、SearchService 300s/热点 60s（`search_service.py:128-130`）、meme 600s 可配（`meme_search.py:340`）、萌百 300s（`domains/location/data/moegirl.py:36`）、Bangumi/B站无缓存。
- 时效机制已在位（v21r2 SEARCH 席）：意图档 latest/background（`sources/search_intent.py:218-225`）、时效加权融合 `fuse_into_web_hits`（`sources/acg_search.py:424-462`）、诚实标注三件（条目日期注 :413-421 / 检索截至 :96-98 / 免责句 :79-82，注入 chat.py:1225-1226）、Tavily time_range 钩子已存在但闲置（`config.py:425` 缺省空 + `search_api.py:448-459`）。
- 四缺口：检索截至标注用 now() 但数据可能是 10 分钟内缓存（口径矛盾）；web 命中 latest 档无日期恒 0.7 垫底；缓存键不含时效档；time_range 无人按档填+web 命中无日期回流。
- 方案 A 缓存分档 / B 标注层修正（推荐，成本≈0）/ C 时效加权补全（挂起等 Tavily publishedDate 契约确认+用户计费裁定）。详见 memo §1.2。

### ③ 提醒系统 — 取证完成（残余五项，建议只排 #1）

- 已落确认：广告闸（`domains/schedule/capabilities/reminder.py:76-89`）+24h 去重、勾选消歧 A-10/A-11、满 20 如实拒绝、过期治理（`store/reminders.py:58-60`+gov- 回执）、时区统一。
- 残余：**#1「明早」不在日词表会错记**（`store/reminders.py:46-51` 交替表无「明早」，上午场景「明早8点」错记今天——唯一错记型缺口）；#2 星期几不支持（诚实拒绝）；#3 具体日期不支持；#4「一会儿/待会儿」不支持（需用户定默认值）；#5 X点一刻不支持（低频）。详见 memo §三。

### ④ LLM 故障转移 — 取证完成（live 证据清单九项）

- R1 席修复符号本席已在**真身**逐一验证在位：`domains/chat_reply/llm_engine/model_router.py`（_strict_priority_enabled:611/_failover_min_hop_seconds:636/_demote_cooling_candidates:655/grok 回落日志:1972-1999）、`channel_health.py`（cooldown_until 迁移:98-100/90s 冷却 :457）、`domains/ops/monitor/alerts.py`（fold_kind_stages:161/chain=N跳全败 :312-343）。
- 注意 `llm/`、`runtime/alerts.py` 全是垫片，全库 grep 必须到 domains/ 真身。
- 九项 live 证据清单（served_by/逐跳/chain 分布/90s 冷却/INTIMATE 钉一/严格优先级/分组真生效/axonhub 对照/告警折叠）逐条带日志关键字，见 memo §四。本席零真实 LLM 调用。

### 交付（2026-09-18 LEDGER-b 收口）

- ✅ memo 成稿：`docs/design/v21r4-b6-ledger-memo.md`（五项齐，全结论带 file:line；①三方案与③#4 标注待用户裁定；全部为调研结论未实装）。
- ✅ 本日志：五项取证摘要+交付清单在案。
- 硬约束遵守确认：零 git 写操作、零子代理、零 .py/渲染域/验收矩阵改动、零真实 LLM 调用/发送/重启、直跑仅 grep/find/read 无 python 执行。
- 接手提示：memo 附录有真身符号坐标表，后续席位免检索；行号是 2026-09-18 快照，符号名优先。
