# 模型路由与账本 · 调用记录与计价

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.model-control · 调用记录与计价

- 层级：一级 B09 → 二级 model-control → 三级 `billing-ledger`
- 实现落点：`plugins/bot_unified_runtime/llm`、`plugins/bot_unified_runtime/domains/chat_reply/llm_engine`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把每次模型调用记成结构化流水（谁、用哪个模型、走了哪条链、成没成、token 用量），落进本地 SQLite 账本，供 `/bot model usage` 一类查询和成本分析消费。核心立场是「记账绝不拖累聊天」：默认关闭，写入走后台线程，任何失败只打日志。规格见 `docs/design/llm-billing-ledger.md`（M1 范围）。

## 怎么调用

`ModelRouter` 通过 `domains/chat_reply/llm_engine/ledger.py::CallRecordSink` 协议注入 recorder，router 本身不依赖 DB。装配在 `ledger.py::LedgerService`：`generate()` 出口用 `build_call_draft` 组装一行 `LLMCallDraft`（成功或最终失败各一行；failover 中间尝试与影子落选者塞进 `attempts_json`，不单列），投递到内存队列，由单独写线程批量 flush（`DEFAULT_FLUSH_BATCH_SIZE` / `DEFAULT_FLUSH_INTERVAL_SECONDS`），队列满则丢最旧并计数。三张表 DDL（`llm_call_records`/`llm_usage_daily`/`balance_snapshots`）一次建齐，但本阶段只写 `llm_call_records`。`redact_error_summary` 保证错误摘要出站前打码。

## 开关与参数

总开关唯一解析源 `ledger.py::ledger_enabled(config)`：读 `bot_llm_billing_enabled`（Config 字段，防御式 `getattr`）→ `BOT_LLM_BILLING_ENABLED`（os.environ）→ 默认关。注意：`bot_llm_billing_enabled` 并非 `config.py` 里的 pydantic 字段（本会话核实 config.py 无此定义），因此常态是走环境变量；关时 router 出口不组装 draft、不导入任何 DB 路径。库路径 `ledger.py::resolve_default_db_path`，`data/` 前缀经 `scripts/runtime_paths.py` 重映射到 Runtime 数据根。

## 失败时看到什么

设计上无对外失败面：`submit()` 吞掉一切异常只打日志，聊天回复照常。开启后落库延迟表现为「最近几条稍后才出现在账单里」（后台批量 flush）。本阶段 cost 四列缺省 NULL、`pricing_source='unknown'`，有 token 消耗但未计价的行标 `unpriced=1`——「未知不是 0」。

未确认项：价目何时真正填进 `llm_call_records` 的 cost 列。`tests/test_llm_ledger.py::test_success_draft_roundtrip` 明确断言 M1 写出时 cost 为 NULL；仓内另有 `pricing.py`/`billing_pricing.py`/`billing_service.py` 与 `scripts/import_model_prices.py`，但它们是否已接进 ledger 写出、还是仅供查询侧读取，本会话未在 ledger 出口核实。要确认：查 `LedgerService` 写线程是否在落库前调用 PricingService，或跑一次开启账本的真实调用看 cost 列是否非 NULL。

## 测试与验收

`tests/test_llm_ledger.py`（建表幂等/WAL 先行/草稿往返/未知 token 保持 NULL/失败字段/错误摘要打码截断/队列溢出丢最旧/后台写线程 flush/开关缺省关与 Config→env 兜底），`tests/test_ledger_channel_breakdown.py`、`tests/test_ledger_range_query.py`。真机（重启后）：设 `BOT_LLM_BILLING_ENABLED=true` 重启，发一轮对话后查账本库确有 `llm_call_records` 行、错误摘要无路径与密钥外泄。
