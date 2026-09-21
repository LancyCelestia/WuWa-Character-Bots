# v21r4-B 重启真机验收清单（ACCEPT-PREP 席，2026-09-19）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> **性质：验收预案，不是生效证据。** 本清单供用户提权重启后**照单验收** v21r4-B 波各席改动；全部波内证据为离线（pytest/ruff/mypy/catalog/doc_sync），**在逐项实跑验收通过前，任何一项不得宣称「已生效」**（见 §五诚实声明）。
> 数据源：各席日志 `docs/design/v21r4-b-*-log.md`、`v21r4-b-wave-snapshot.md`（INTEGRATE）、`v21r4-b2-direct-collect-plan.md`（DIRECT-PLAN）、`v21r4-b6-ledger-memo.md`（LEDGER-b）；条目格式参照 `docs/acceptance-manual.md` §6.6 族（本文件不改该手册）。
> 在飞席位（RWC5-b / RWC6-b / S0-COLLECT / RET3 / DOC-SYNC）相关项一律占位，标「**以其日志终态为准**」，本清单不代写结论。
> 本席零代码、零 git 写操作、零子代理、零真实 LLM 调用/真实发送、未重启。

---

## ① 重启前置（全部满足才动手重启）

| # | 前置项 | 操作 | 预期 | 异常时看哪 |
|---|---|---|---|---|
| P1 | 一键预检 | `ChatBot_Runtime\venv\Scripts\python.exe scripts\pre_restart_check.py`（或加 `--json`） | 7 项全 PASS：env_paths / persona_sync / hash_ledger / doc_sync / kb_drift / ruff / napcat（SKIP 项按脚本口径放行，exit 0=可动手） | 脚本自带 FAIL 修复指引；其中 hash_ledger 若因前端波在飞文件（theme_tokens/domains/render 等）报漂移，按总纲「合流时前端统一重录」处理，勿盲目 `--write`；kb_drift 项即快照 §2.9 复查方式（`ANN == chunks` 变绿=知识库收拾干净） |
| P2 | 重启顺序 | 管理员提权，**先 SnowLuma 后 bot.py**（生产进程常驻且管理员权限启动，杀旧进程需提权） | SnowLuma 先起（WS 127.0.0.1:3001）；bot.py 后起自动重连。预检 napcat 项 SKIP（端口不可达）=尚未启动属预期 | docs/snowluma-setup.md |
| P3 | 门缺省关确认 | 检查 `.env`：不含 `BOT_V21_SERVICE_WIRING_ENABLED` / `BOT_WORLDBOOK_ENABLED` / `BOT_KNOWLEDGE_SERVICE_ENABLED` 三行，或显式 `=false` | 重启后启动日志**不出现** `v21 services wired:` 字样 = 零装配零副作用，**现网行为零改变**（config.py 三键缺省 False，源码已核） | 装配点=根 `__init__.py` `_register_nonebot_handlers` 内（WIRE-SVC 席插入段）；意外出现该行→查 .env 是否误填 true |
| P4 | 重启后首验 | 重启完成、bot 在线后先发 `/bot status` | SnowLuma WS 重连正常、无装配报错（任何异常先取证再动手，禁症状性补丁） | `data/runtime_events.log` + 启动控制台输出 |

### P3 附：想启用哪个门（WIRE-SVC 四服务装配组，键名与生效条件）

> 全部为**缺省关**的可选启用项；生效门=**主门 ∧ 对应分门**。改 `.env` 后须**再次重启**（装配期读取 config 快照，同台账 #3 调度器族口径）。

| 服务 | .env 键（config 字段） | 缺省 | 生效条件 | 开启后预期 |
|---|---|---|---|---|
| 主门（总闸） | `BOT_V21_SERVICE_WIRING_ENABLED`（bot_v21_service_wiring_enabled） | False | —— | False 时四服务链路整体短路，怎么配分门都不装配 |
| L39 世界书 | `BOT_WORLDBOOK_ENABLED`（bot_worldbook_enabled） | False | 主门 ∧ 本门 | 装配日志出现且 ids 含 worldbook |
| L40 知识检索 | `BOT_KNOWLEDGE_SERVICE_ENABLED`（bot_knowledge_service_enabled） | False | 主门 ∧ 本门 | ids 含 knowledge |
| L42 DB 代理 | `BOT_DATABASE_BROKER_ENABLED`（既有键） | **True** | 主门 ∧ 本门 | **只开主门即随之装配**（分门缺省已开）；想只开 WORLD 就必须显式把本键与 teaching 键设 false |
| L43 教导库 | `BOT_TEACHING_ENABLED`（既有键） | **True** | 主门 ∧ 本门 | 同上；且 TeachingService 构造急切建库（mkdir+schema）——开启后启动即产生教导库文件**属预期**（文件属运行数据，回退后留存不按事故处理） |

- 装配成功判定：启动日志一行 `v21 services wired: <ids>`（ids 按实际所开门）；单服务装配失败 fail-open 只记 warning 跳过、不崩装配。
- **诚实预期**：本批四服务只做「装配+进程内注册表」，消费方（能力/控制面）**尚未接线**（后续席位）——门开后**没有任何用户可见功能变化**，可观测面仅装配日志与注册表。
- L41 memory：**不在启用清单**（blocked=用户未裁决「独立新库 vs 同源同库」）；即便主门+全分门打开，memory 也不装配（测试常驻锁）。启用前提=先裁 `docs/design/v21r4-L41-decision-memo.md` §⑤。

---

## ② 分功能验收项（操作→预期→观测点/日志关键字）

### A. 提醒双修（REM-DAWN「明早」+ REM-EVE「明晚」，本波唯一代码生效面）

> 真身 `plugins/bot_unified_runtime/domains/schedule/store/reminders.py`；重启后生效。时间基线=配置时区+timesync 校正（既有口径）。

| # | 操作 | 预期 | 观测点/异常时看哪 |
|---|---|---|---|
| A1 | 私聊真聊一句「**明早8点提醒我吃药**」（上午场景发，如当天早上） | 建条成功；`提醒列表` 显示**明天 08:00**——不再错记「今天 08:00」（修复前 06:30 发→label=今天 08:00 实锤） | 提醒列表 label；不符→`domains/schedule/store/reminders.py` 日词表三处（`_DAY_OFFSETS`/`_ABS_TIME_RE`/`_PERIOD_ONLY_RE` 含「明早」）+ 离线 `tests/test_reminder.py::test_parse_mingzao_day_word_tomorrow_morning` |
| A2 | 私聊发「**明晚8点提醒我…**」 | 建条成功，显示**明天 20:00**（本波裁定：口语晚间语义；REM-DAWN 旧口径 08:00 已被 REM-EVE 取代，冲突裁决记录见 REM-EVE 日志 §④）；对照句「明天晚上8点」同为明天 20:00（两路同构） | 同上，离线锁 `test_parse_mingwan_evening_semantics` / `test_parse_evening_day_word_consistency` |
| A3 | 私聊发「今晚8点提醒我…」（20:00 前发） | 显示**今天 20:00**；同时修复修复前 now>08:00 时静默建不成条的问题。当天已过 20:00 → 既有顺延语义接管 | `提醒列表`；不符→REM-EVE 日志 §③ 分支（`not period and day_word in {"今晚","明晚"}` 时 hour<12 → +12） |
| A4 | 保守边界：「明晚20点」「明晚12点」 | 维持字面小时不改、不发明半夜语义（任务④保守边界） | 离线锁 `test_parse_evening_boundary_explicit_ge12_unchanged` |
| A5 | 「提醒列表」通览 | 上述新条目日期/时间与 A1-A3 一致；既有列表不丢不重 | bot 回执；存量行为回归=REM-EVE 日志提醒族 7 文件 125 passed（离线） |
| A6 | 到点投递冒烟 | 「2分钟后提醒我XX」到点收到投递（投递链既有行为不受双修影响） | 投递回执；异常看 `_deliver_due_reminders` 统一路径日志 |

### B. REM 系回归对照（广告句不进提醒）

| # | 操作 | 预期 | 观测点 |
|---|---|---|---|
| B1 | 粘贴一条 AI 生成的长广告正文末尾加「提醒我」发送 | 广告闸拒绝入库（超长/广告痕迹/多句正文），**不进提醒列表** | `domains/schedule/capabilities/reminder.py` 广告闸（:76-89）+ 24h 同文去重（:92-111）；预期来源=LEDGER memo §③（2026-09-18 实弹五条齐炸已治，本项验证双修未破坏它） |
| B2 | 列表已满 20 条时再建；制造一条过期提醒 | 满 20 如实拒绝不挤旧；过期治理照常（迟到>30 分钟不原样补投、gov- 回执） | reminder.py :672-680 / reminders.py :58-60+:160-257（回归对照面） |

### C. WIRE-SVC 四服务门开装配冒烟（可选；缺省关下本节整节跳过）

| # | 操作 | 预期 | 观测点/日志关键字 |
|---|---|---|---|
| C1 | 按 §①P3 附表在 `.env` 开主门+想开的分门 → 重启 | 启动日志出现 `v21 services wired: <ids>`，ids 与所开门一致 | 关键字 `v21 services wired`；管理员 `/bot status` 或控制面观测无装配报错 |
| C2 | 只开主门（不动 teaching/broker 既有键） | 四服务全装配（teaching/broker 分门缺省 True）——若非本意，回滚按 §④ | ids 应含 worldbook/knowledge/database_broker/teaching 全部 |
| C3 | 开门状态下查 Runtime data | 仅 TEACH 分门开时新建教导库文件（急切建库属预期）；其余服务懒打开不触库文件 | `ChatBot_Runtime/data/teaching_knowledge.sqlite3`；WIRE-SVC 曾有测试 stub 笔误致一过性空库文件（已备份 %TEMP% 后清除）——真机上门开后的新文件属预期、门关后出现才属异常 |

### D. RK5 控制面三债

> 前置：控制面进程已启动（默认关，按既有控制面规程 loopback 8742 + Bearer 启动）。

| # | 操作 | 预期 | 观测点 |
|---|---|---|---|
| D1 | 经控制面触发一个动作（napcat.status / queue.* / diagnostics.snapshot 任一） | 响应 `details` 字段**非空**：含 `connected`/`source` 等布尔与标识字段（修复前被事件白名单消毒成 `{}`）；凭证形键名仍整键丢弃（`token` 类不出现在响应） | 控制面动作 API 响应体；离线锚=转正回归 `test_risk4_action_details_survive_to_client`（RK5 日志交付 1） |
| D2 | 拉控制面 `/openapi.json`（或构造 app 时看告警） | traces 路径 schema 存在且唯一；全 schema operationId 无重复；**无** `UserWarning: Duplicate Operation ID traces_api_v1_traces_get` | `/api/v1/traces` GET 段；离线锁 `test_openapi_operation_ids_are_unique`（RK5 日志交付 2） |
| D3 | mypy 两错清零 | **静态门项，不涉真机**——RK5 已离线 scoped mypy 实证 `platform.py` 0 error；真机无观测面，列此仅备查 | 复跑口径：`-m mypy --explicit-package-bases --ignore-missing-imports`（与 dev.ps1 typecheck 同参）；根 `__init__.py` 另 2 处 attr-defined 既有错归 WIRE-SVC 域 |

### E. S0-COLLECT（在飞，占位）

- **以其日志终态为准**（`docs/design/v21r4-b-S0-COLLECT-log.md`，本席落稿时未在盘）。
- 方案面参照 `v21r4-b2-direct-collect-plan.md` §三：四处收编（cookie 到期提醒/入群欢迎/二维码图片/文档导出）均为「**配置门缺省关**」设计（`*_via_queue` 提案键名，实施席可议），未实施前真机零行为变化；其 §五第 5 行「真机验收：四处各触发一次+回执仓/审计/日志三面取证」**待实施后启用**，本清单暂不列操作行。
- ⑤ 登记表刷新（outbound_registry）落地后属纯数据面、无行为变化；观测面=离线结构锁 `tests/test_v21_wiredirect_unified_path.py`，真机无新增项。

### F. 在飞其余三席（占位）

| 席位 | 改动面 | 真机观测面（占位） | 终态 |
|---|---|---|---|
| RWC5-b | 根 `__init__.py` 惰性导入续切收尾 | 启动成功 + `/bot status`/功能抽测无回归；以其日志终态为准 | **以其日志终态为准** |
| RWC6-b | policy/security 8 件真身迁 `domains/chat_reply/{policy,security}/`（旧路径 PEP 562 垫片保活） | 门禁行为无回归抽测：群黑白名单/安静时间/限流、`/bot` 管理员门、内容安全（content_safety）照常；以其日志终态为准 | **以其日志终态为准**（本席落稿时批次 1 进行中） |
| RET3 | 垫片退役第三梯队（epic/steam 2 张+仅测试消费 44 张；已完成批 1=11 张、批 2=13 张） | 启动零 ImportError、零旧路径回退日志；其余为离线测试面（动态 import 前缀已改指 canonical）；以其日志终态为准 | **以其日志终态为准** |
| DOC-SYNC | 波末文档草案（纯文档） | 无真机验收面 | **以其日志终态为准** |

---

## ③ live 观察项（引用，不展开）

1. **LLM 故障转移九项 live 证据清单**：直接按 `docs/design/v21r4-b6-ledger-memo.md` §四表格逐项采集（served_by 轨迹 / 逐跳失败日志 / chain=N 跳全败分布 / 90s 渠道冷却 / INTIMATE grok 钉一回落 / 严格优先级 / 分组配置真生效 / axonhub 控制台对照 / 告警折叠防刷屏）。采集纪律同 memo：**不主动制造故障**，等自然故障窗口采样；任何一项不符另立 systematic-debugging，不在验收单内顺手修。
2. **合并转发三条 live 观察点**（前置批次已闭环、待重启生效，memo §②）：三层嵌套转发深层正文不再只剩 `[合并转发:id]` 占位；>20MB 原图识别不再「大图读不了」；`forward message fetch timed out` warning 频率（频繁可把 `bot_forward_fetch_timeout_seconds` 调 8-10，纯配置改动非代码）。

---

## ④ 回滚方式

| 项 | 回滚方式 | 指针 |
|---|---|---|
| WIRE-SVC 四服务门 | `.env` 主门（及按需分门）拨回 `false` 或删行 → 重启 → 零装配零副作用；误开产生的教导库文件属运行数据留存即可 | WIRE-SVC 日志「终稿·交付物与装配坐标」表 |
| REM-DAWN「明早」 | 撤销 `reminders.py` 三处「明早」新增（`_DAY_OFFSETS`/`_ABS_TIME_RE`/`_PERIOD_ONLY_RE`）；**注意 REM-EVE 已改写同一文件**，回滚前必读最新文件态 | REM-DAWN 日志「修复内容（最小改动面）」节 |
| REM-EVE「明晚/今晚」 | 撤销该席两处改动（logging 引入 + 今晚/明晚 hour<12 加 12 分支）；若用户裁定恢复 REM-DAWN「明晚8点=08:00」旧口径，按其冲突裁决记录执行 | REM-EVE 日志 §③（回滚点）+ §④（冲突裁决） |
| RK5 三债 | 三交付各单点回退：actions.py `_sanitize_action_details` 替换回借道调用 / v1.py traces stub `operation_id` 一行 / platform.py 两处返回标注 | RK5 日志「终稿」交付 1/2/3 各节 |
| RET3 垫片退役 | 已删垫片全部备份于 `%TEMP%/v21r4-ret3-backup/<相对路径>`（字节级核验），按原路径恢复；批 1（11 张）/批 2（13 张）清单 | RET3 日志「批次台账」批 1/批 2 表 |
| RWC6-b 迁移 | 垫片保旧路径，真身移回旧路径或恢复垫片即可，旧消费方不受影响 | **以其日志终态为准** |
| S0-COLLECT | ——（在飞，无已落盘行为改动） | **以其日志终态为准** |
| 文档类交付（MAT/PORT-PLAN/DIRECT-PLAN/CHARTER/DOCS/LEDGER/INTEGRATE/MEM-DEC/DOC-SYNC） | 零行为改动，无回滚需要 | —— |

---

## ⑤ 诚实声明

1. **本清单是验收预案，不是生效记录。** 全波未 commit / 未重启 / 未部署（INTEGRATE 快照 §四状态红线口径）；本清单所列「预期」全部来自**离线证据**（pytest/ruff/mypy/catalog/doc_sync/源码直读），离线绿不升 live passed、不升 wired。
2. **验收完成前，任何一项不得写成「已生效/已修复（生产）」**；矩阵行 production_wiring 是否升 wired 只能由重启后 live 证据决定（WIRE-SVC 席同口径）。
3. 在飞五席（RWC5-b/RWC6-b/S0-COLLECT/RET3/DOC-SYNC）相关项为**占位**，以其日志终态为准；本清单不代写其结论、不替其宣称完成。
4. 本席（ACCEPT-PREP）自身零代码、零 git 写操作、零子代理、零真实 LLM 调用/真实发送、未重启；只新建本清单与席位日志，未改任何既有文件。

**收尾纪律**：逐项验收不符 → 先取证（触发原文/时间点/runtime_events.log 对应行）再按 systematic-debugging 定位根因，禁症状性补丁；全部通过后按台账规矩在 HANDBOOK/AGENTS.md 记「重启生效」，并回写本清单勾选状态。
