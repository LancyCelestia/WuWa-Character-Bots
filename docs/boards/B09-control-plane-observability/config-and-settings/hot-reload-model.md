# 配置与运行时设置 · 热更、drain 与回滚

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.config-and-settings · 热更、drain 与回滚

- 层级：一级 B09 → 二级 config-and-settings → 三级 `hot-reload-model`
- 实现落点：`plugins/bot_unified_runtime/config.py`、`plugins/bot_unified_runtime/domains/core/config`、`plugins/bot_unified_runtime/runtime/settings.py`、`docs/config-catalog-full.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

回答一个非常具体的问题：**改了之后要不要重启**。答案只有两种，而且必须是真的两种
——能热改的键，改完下一次消费就用新值；不能热改的键，写它就会被明确拒绝并告诉你
为什么（点名哪个消费点在装配期把值烘死了）。绝不允许出现"写入成功、返回 200、
行为一点没变"的死开关，那是本仓历史上被审计专门点名治理过的一类缺陷（审查 C-09）。

## 怎么调用

两张登记表是真身，都在 `domains/chat_reply/runtime/settings.py`
（`runtime/settings.py` 是 PEP 562 再导出垫片，不是第二处定义）：

- `SETTABLE_KEYS: dict[env名, converter]` —— 可写白名单，每个键配一个类型转换/域校验器
  （`_temperature_converter`、`_max_tokens_converter`（0=不设上限）等校验器、域值区间以该文件转换器真身为准、
  `_clock_converter`、`_timezone_converter`、`_session_types_converter`、
  `_role_list_converter`、`_group_list_converter`、`_model_priority_groups_converter` 等）。
- `RESTART_REQUIRED_KEYS: dict[env名, 原因说明]` —— 只读冻结表，值是"为什么改不了"的人话。
- 交集为空是设计前提；一张键只能在一处。两表的具体条目数以该文件为准，不在文档手写。

三条写入路径共用同一判定：

1. `POST /api/v1/config/{key}/preview|set|reset`（+ `GET /config`、`/config/schema`、
   `/config/{key}`、`/config/changes`）→ `plugins/bot_unified_runtime/control_plane/config_service.py:ConfigControlService`；
2. `/bot runtime set|get|list|reset`（管理员）→ `_handle_runtime_command`，
   **当 store 已 attach SQLite backend 时同样构造 `ConfigControlService`**，
   即两条路口径同源；
3. 内部 `RuntimeSettingsStore.set_override`（JSON 域，昵称/人格/模型注册表等非覆盖域仍走它）。

覆盖生效链：`SQLiteConfigStateStore`（`revision` 全局 CAS + `config_overrides` +
`config_audit` 三表，短连接、无缓存）→ `RuntimeSettingsStore.attach_config_backend`
一次性导入 legacy 后切换覆盖源（**不可运行中换库换实例**，重复 attach 幂等）→
根 `__init__.py:_config_with_runtime_overrides` 按 `_RUNTIME_HOT_OVERRIDE_FIELDS`
做浅合并产出"判定用合并视图"，无任何覆盖时直接返回原 config 对象（零额外开销）。

## 开关与参数

- DTO 里三个字段就是热更性的诚实表达：`hot_reload = key in SETTABLE_KEYS and
  key not in RESTART_REQUIRED_KEYS`、`restart_required = key in RESTART_REQUIRED_KEYS`、
  `source ∈ {config, runtime_override}`。**冻结键即便留有历史覆盖，也不会被报成已生效**
  （`_row` 里显式把 `RESTART_REQUIRED_KEYS` 的覆盖判回 config 值）。
- 写三要件：`super_admin` 角色、非负整数 `expected_version`、有效 `request_id`
  + 非空 subject。缺一即 403/422。
- 值语义：`null` 不作为写值（清除覆盖请用 `reset`）；列表型 legacy converter 收
  分隔文本而非 JSON 数组串（`BOT_QUIET_HOURS_SESSION_TYPES` / `_BYPASS_ROLES` 两处例外，
  代码里显式登记）；转换结果必须可 JSON 序列化（`allow_nan=False`），NaN/Infinity 拒。
- 审计：每次 set/reset/import 在**同一事务**里写 `config_audit`（before/after 快照、
  actor、request_id、单调 version）；`reset_all` 一次 CAS 清空、count 取同一版本快照，
  不逐键提交。
- 敏感值：审计与 DTO 都过 `config_store.public_value` / `redact_public_data`，
  凭证类（`_KEY/_TOKEN/_SECRET/_COOKIE/_CREDENTIALS/_AUTHORIZATION` 等后缀，
  先剥 `_SHA256/_HASH/_DIGEST` 再判）只出 `configured` + fingerprint；
  converter 抛出的异常文本可能含原始密钥，因此**不带 cause 出 DTO**。

## 失败时看到什么

| 情况 | 结果 |
|---|---|
| 未登记的键 | 404 `config_not_found` |
| 冻结键被写 | 409 `config_not_hot_reloadable`，文案「该配置尚无安全热更新路径，请修改 .env 并重启。」 |
| 值不过 converter | 422 `config_invalid`「配置值未通过校验。」（不回显原值） |
| 版本过期 | 409 `version_conflict`（要求重读再写，不自动重放过期写） |
| 存储故障 | 503 `config_store_unavailable`，明确「配置未保存」 |
| 参数没进白名单 | `/bot runtime get` 直接列出可用键，不猜 |

诚实边界一句：**CAS 成功 ≠ 资源已安全 reload**。`config_store.py` 的头注就写着
"无资源 reload"；控制面 protocol 自报 `features.reload_drain=false`。也就是说
现役实现的是"值的一致性与可追溯"，不是"运行中资源的排空与热替换"。

## 测试与验收

`tests/test_runtime_settings_restart_required.py`（冻结键拒绝 + 文案点名消费点 +
两表互斥）、`test_config_control_service.py`（CAS/preview 不落盘/审计/redact/
reset_all 单次提交）、`test_settings_hot_audit.py`、`test_control_plane_v1.py`
（config 端点族）、`test_phase0_3_features.py`。
真机：管理员 `/bot runtime get BOT_CHAT_TEMPERATURE` → set 一个新值 → 立即发一条消息
观察是否用新值；再挑一个 `RESTART_REQUIRED_KEYS` 里的键（如
`BOT_RENDER_FORWARD_MIN_CHARS`）写一次，**预期被明确拒绝而不是"写入成功"**。
