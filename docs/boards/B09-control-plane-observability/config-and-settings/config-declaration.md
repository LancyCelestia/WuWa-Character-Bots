# 配置与运行时设置 · 字段声明与校验器

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.config-and-settings · 字段声明与校验器

- 层级：一级 B09 → 二级 config-and-settings → 三级 `config-declaration`
- 实现落点：`plugins/bot_unified_runtime/config.py`、`plugins/bot_unified_runtime/domains/core/config`、`plugins/bot_unified_runtime/runtime/settings.py`、`docs/config-catalog-full.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

配置面的**唯一声明源**：所有 `bot_*` 参数在 `plugins/bot_unified_runtime/config.py`
的单个 pydantic `Config` 类里声明类型、默认值与校验器。没有第二份配置表，也没有
"某能力自己偷偷读 os.environ"的余地——要新参数就在这个类加字段，加完生成物与门
会自动追着改。

它承担三件事：① 类型与取值域（非法值在**装载期**就炸，不留到运行时某条消息上炸）；
② 形态归一（同一含义的多种写法收成一个形态，例如 QQ 号既可能是 int 也可能是 str）；
③ 相对路径统一重映射到 Runtime 数据根（铁律 6：源码树零运行数据落盘）。

## 怎么调用

- 生产装载：`bot.py` 的 `nonebot.init(_env_file=(".env", ".env.prod"))` 是真身入口，
  NoneBot 把 `BOT_*` 小写映射进 `Config` 字段。业务代码取配置一律经注入的
  `config` 对象或 `getattr(config, "...")` 读字段，不自己碰 `os.environ`。
- 离线装载唯一入口：`scripts/load_runtime_config.py:load_runtime_config`
  （2026-09-21 修复波闭合 M-68，此前四套解析器并存）；只要值层用
  `load_runtime_env_values`，只要 JSON 解码层用 `json_decode_env_values`，
  要 Config 对象用 `config_from_env_values`。四个现役消费方（重启门
  `scripts/pre_restart_check.py`、快查 `scripts/verify_chatbot_env.py`、
  冒烟 `domains/ops/smoke/smoke.py:load_smoke_config`、巡检
  `domains/ops/sync_drift/service.py`）全部走它，禁止再造第五套。
- 键名翻译：`config.py:translate_env_keys`（env 名 → 字段名）。
- 校验器家族（都在 `Config` 内，按职责分族）：`_parse_id_list`（含
  `_coerce_scalar_id_to_str` 治 pydantic 标量 QQ 号键崩启动的老坑）、
  `_parse_file_list`、`_decode_json_collection_strings`、`_parse_web_search_provider_list`
  / `_parse_model_dicts` / `_parse_model_priority_groups`（集合类字符串 JSON 化）、
  `_validate_chat_output_tokens`、`_positive_memory_duration`、`_validate_digest_push_clock`
  、`_normalize_decision_engine_mode`，以及 TTS 一族契约枚举校验
  （`_validate_tts_preset/_text_lang/_text_split_method/_auto_reply_scope/_api_url`——
  其中 api_url 走 loopback 白名单 fail-closed，SSRF 闸在字段层而非调用点）。
- 路径重映射：`_resolve_runtime_data_paths`（`model_validator(mode="after")`）遍历
  `path_fields` 元组，把运行数据相对路径改写为 Runtime 数据根下的绝对路径（相对前缀以 `scripts/runtime_paths.py` 为准），
  实际解析走 `scripts/runtime_paths.py`。**新增任何 `*_db_path`/`*_file` 类字段必须
  同时进 `path_fields`**，漏了就等于往源码树写数据。

## 开关与参数

本卡没有"自己的开关"，它规定的就是别人的开关长什么样。三条硬约定：

- 命名：字段 `bot_<域>_<项>`，env 名 `BOT_<域>_<项>`；布尔项以 `_enabled` 收尾，
  路径项以 `_db_path` / `_file` / `_dir` 收尾。
- 密钥：字段默认值写 `"env:变量名"` 引用，真值只在 `.env`；登记字段的存在、
  不登记真值。控制面/审计出口只出 fingerprint（见 [hot-reload-model](hot-reload-model.md)）。
- 字段数量、路径字段数量、各家族键数**一律指 `docs/auto-facts.md`**
  （由 `scripts/doc_sync.py` 从 `Config` 派生），叙述文档不手写——
  `tests/test_documentation_consistency.py::test_narrative_docs_defer_volatile_counts_to_machine_ledger`
  执法，写过一次就过期一次的东西不再进文档。

## 失败时看到什么

- 非法值在装载期失败，报错里带字段名与原因；离线侧由 `load_runtime_config` 抛
  `RuntimeEnvError` / `RuntimeEnvNotFoundError`（严格模式下 env 全缺）——
  **不会**静默退化成"全用代码默认值然后跑起来一切看起来正常"。
- 损坏的类型宽容：集合类字符串解析失败按既有语义回退原串或空集合，并留 warning；
  id 列表遇到 pydantic 标量形态走 `_coerce_scalar_id_to_str` 宽容装载。
- 校验器抛错就是抛错，不吞。配置面没有"降级继续跑"这条路——带着坏配置跑起来
  比启动失败更贵（历史上一次垫片覆写就是坏配置的代价）。

## 测试与验收

`tests/test_runtime_config_loader.py`（与 nonebot DotEnvSettingsSource 逐键对拍、
行内注释、`.env.prod` 覆盖序、environ 优先）、`test_config_json_validators.py`
（集合类 JSON 解码族）、`test_config_id_list_scalar.py`（标量 QQ 号键宽容装载 +
校园六键实弹回归）、`test_tts_config_gates.py`（TTS 枚举与 loopback SSRF 字段闸）、
`test_config_control_service.py`。
真机：`python scripts/verify_chatbot_env.py`（配置面真验证，判据是生产 Config 真身，
`-O` 下锁双向有效）与 `python scripts/pre_restart_check.py`（重启门前置项）。
