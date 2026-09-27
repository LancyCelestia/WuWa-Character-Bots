# 管理命令面 · 诊断与快照

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.admin-commands · 诊断与快照

- 层级：一级 B09 → 二级 admin-commands → 三级 `diagnostics`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/admin`、`plugins/bot_unified_runtime/domains/ops/incident`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

没有 WebUI 时管理员「问一句就看见内部状态」的读面：日志、审计、回执、队列、配置、
角色、人设、上下文组装、LLM 链路、就绪度，全在 QQ 私聊里用 `/bot …` 查到；外加结构化
事件载体（Incident）作为「查得出来」的数据腿。权限铁律：非管理员一律温和拒绝，
**且不透露任何内部状态**（拒绝文案不夹带诊断信息）。

## 怎么调用

- **查询构造器全家**：`domains/ops/admin/debug.py` 的 `build_*_query_result` 系列——
  `receipt`（发送回执）、`audit`（审计记录）、`recent`（最近消息）、`queue`（发送队列）、
  `roles`（角色表）、`persona`（人格快照）、`context`（人格 prompt 组装诊断，走
  `build_chat_prompt_with_diagnostics` 与 `build_safe_context_source_summary`）、
  `config`（配置读回）、`readiness`（重启/上线就绪）、`dialogue`（对话链路诊断）、
  `llm` / `llm_setup`（模型链与渠道配置卡，出图失败回退纯文本）。根 `__init__.py` 装配
  期统一 import 挂进命令面；命令逐参数口径以 `docs/command-catalog.md`（生成物）与
  `COMMANDS.md` 为准，本页不抄清单。
- **运行时控制**：`domains/ops/admin/runtime_admin.py` —— `/bot runtime set|get|list|
  reset|nickname|instance`，写路径只经 `SETTABLE_KEYS` 白名单与实例设置件
  （`--instance` 定位机器人实例，各实例设置/昵称/计数彼此隔离）；`/bot alert check
  [--probe]` 手动跑凭据健康检查，探针有非阻塞重入锁（进行中只回执提示、不叠探针）。
- **日志查询能力**：`domains/ops/admin/runtime_logs.py::build_logs_query_result` —— 按
  级别/条数取运行时事件日志（数据腿是 `domains/ops/monitor/runtime_event_log.py`），
  非管理员拒绝。
- **结构化事件载体**：`domains/ops/incident/service.py` —— 每条 Incident 固定
  时间/位置/解释/方法/trace/严重度六要素，与错误卡（B08 诊断卡）互补：卡面向人眼，
  Incident 面向查询与聚合。

## 开关与参数

声明源未给本入口登记专属配置前缀——它是命令面，生死随所属能力注册与角色门。
涉及的可数事实：`SETTABLE_KEYS` 名册（热更白名单）与 `RESTART_REQUIRED_KEYS`
（重启口径）都在 `domains/chat_reply/runtime/settings.py`，逐键以
`docs/config-catalog-full.md` 为准；凭据健康检查读 `domains/core/credentials/` 真身。
谁能改：admin/super_admin 角色（`domains/chat_reply/policy/roles.py` 口径）。

## 失败时看到什么

- 所有出站文本过统一脱敏（盘符路径、`BOT_XXX=`、sk-、Bearer 形态），诊断输出**先脱敏
  再组装**；Incident 侧零例外契约写在其 docstring：懒加载复用
  `domains/render/plain_text.py::redact_local_secrets`，导入失败降级本地最小正则而非
  放弃脱敏；用户派生文本必须走 `user_text` 参数，服务只保留「已隐去 N 字」痕迹。
- Incident 同因聚合：指纹=组件+归一化解释头部，窗内重复只累加计数、抑制 sink，每达
  `notify_stride` 倍数重发一次防完全静默；`explanation/method` 截断防日志膨胀；report
  全捕获不外抛，内存环有上限（数值以构造参数为准）。
- 读不到数据时诚实标注（如宿主机附块「这会儿拿不到读数——采集器没有可用数据源」），
  不返回编造的快照。

## 测试与验收

`tests/test_v21_s14_incident.py`（结构化事件与聚合/脱敏）、
`tests/test_admin_roster_and_roles.py`（管理档案与角色）、
`tests/test_runtime_feature_gate.py` 族（开关读面口径）。更宽的命令面回归由
`tests/test_capability_declaration_parity.py`、`tests/test_chat_and_sources_regressions.py`
等承载；用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准，逐命令真机条目见
`docs/acceptance-manual.md`。真机（重启后）：管理员私聊 `/bot status`、`/bot logs`、
`/bot runtime list` 各一次，确认输出无路径/密钥明文；非管理员成员试探同命令，确认
拒绝且不透状态。
