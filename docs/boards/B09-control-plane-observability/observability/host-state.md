# 日志·指标·Trace·审计 · 宿主机状态

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.observability · 宿主机状态

- 层级：一级 B09 → 二级 observability → 三级 `host-state`
- 路由席位：`HOST_STATE`（matcher `host_state`，command=True）
- 判定优先级：41
- 能力 id：`bot.host_state`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/audit`、`plugins/bot_unified_runtime/domains/ops/collectors`、`plugins/bot_unified_runtime/domains/ops/monitor/__init__.py`、`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`、`plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_service.py`、`plugins/bot_unified_runtime/domains/ops/monitor/event_store.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_card.py`、`plugins/bot_unified_runtime/domains/ops/monitor/host_status.py`、`plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py`、`plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py`、`plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py`、`plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py`、`plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py`、`plugins/bot_unified_runtime/domains/ops/host_snapshot.py`
- 帮助主题：宿主机状态
<!-- BOARD-AUTO:END -->

## 这个入口做什么

超管问一句「机器现在什么样」：一句话回**逐项读数 + 宿主机状态卡图**（硬件 / 占用 /
系统与运行时三组）。非超管触发**一个读数都不采**。同一份数据还有两条旁路消费：
`/bot status` 的超管宿主机附块（旧呈现面）与人格上下文【宿主机状态】分区
（TTL 缓存版，明写「取样 HH:MM」）。生效条件：根装配面接线重启生效。

## 怎么调用

- **触发**：整句等于触发词、或触发词后跟标点/空白边界——`is_host_state_command`
  （`domains/ops/capabilities/host_state.py`）。触发词表（简中/繁中/英文/拼音族）
  唯一真身是同文件 `DEFAULT_TRIGGER_WORDS`，本页不抄清单；帮助词表与它由
  `tests/test_trigger_bidirectional_gate.py` 按词级双向 diff 执法。
- **路由与承载**：`base_router.py` 的 `RouteRule(RouteKind.HOST_STATE, "bot.host_state",
  priority 41)`；根 `__init__.py` 的 `host_state_matcher`（`on_message`，block=True）
  经中央缝 `_run_capability_through_pipeline` 执行并 offload 进线程池——秒级采集与
  渲染绝不在事件循环线程上跑。
- **入口函数**：`build_host_state_capability(config)` 返回 `(message, decision) ->
  CapabilityResult`；角色判定只吃唯一角色源 `ROLE_SUPER_ADMIN`（`policy/roles.py`），
  零第二份名单。
- **三层数据腿**：取数唯一真身 `domains/ops/host_metrics.py`（`METRIC_SPECS` 在册
  指标、现取采样、逐项三态）；呈现适配器 `domains/ops/monitor/host_status.py`
  （旧三分组形状、缺行语义、`cached_host_snapshot` TTL 缓存）；落图唯一口
  `domains/ops/monitor/host_card.py::render_payload_png`（payload 由真身
  `assemble_card_payload` 拼装，走通用卡模板 `page_type=universal`，零新模板）。
  版本读数只调 `domains/ops/monitor/error_report.py::_version_pairs`，本族文件内
  没有任何版本号字面量。

## 开关与参数

本能力**无自有配置键**（`config` 是形参、今天不读任何键）。可数/易漂移的事实一律
指真身：在册指标清单以 `host_metrics.METRIC_SPECS` 为准；缓存 TTL 以
`cached_host_snapshot` 的构造参数为准；「这台机器有没有 psutil」由真身
`host_metrics.psutil_available()` 回答（呈现面只问不读）。卡面文案（标题、分组导语、
降级提示）逐字以 `host_card.py` / `host_state.py` 常量为准。

## 失败时看到什么

- **渲染后端不可用**：卡不出，但 body 恒为逐项读数行，再补一行「宿主机卡未出图
  （渲染后端不可用），以上读数即全部结果」——读数绝不静默消失。
- **事件循环线程被直调（未走线程池）**：降级为只读缓存 `LOOP_DEGRADE_NOTE`
  （如实说明本轮为什么没图）；冷缓存没有读数时回 `NO_DATA_LINE`。
- **psutil 缺席或真身整体炸**：呈现适配器整面交回空组——旧契约「缺数=缺行」，
  不写「未知」占位、不硬凑半份数据（三态语义只在直连真身的新消费面可见）。
- **非超管**：`ADMIN_GATE_TEMPLATES` 轮换池一句话，不透露任何读数。
- **读数全空时不出卡**：一张空白卡比不出卡更像谎报。

## 测试与验收

`tests/test_host_state_card.py`（触发矩阵/角色 tripwire/两本账 AST 锁）、
`tests/test_host_status.py`（旧契约锁：缺行语义、版本腿 getter、冷缓存绝不阻塞
loop）、`tests/test_host_metrics_single_source.py`（单一取数口 AST 门：呈现适配器
体内出现 `platform.`/`psutil.`/`winreg.` 直调即注毒必红）、
`tests/test_trigger_bidirectional_gate.py`。逐条真机步骤见
`docs/acceptance-manual.md` 组 B（需求 5），命令面口径见 `docs/command-catalog.md`。
真机（重启后）：超管发一次触发词，确认卡图与逐项读数同行、无盘符明文；
普通号发同句，确认被温和拒掉且未触发采集。
