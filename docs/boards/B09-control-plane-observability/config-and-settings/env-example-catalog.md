# 配置与运行时设置 · 示例与目录三处同源

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.config-and-settings · 示例与目录三处同源

- 层级：一级 B09 → 二级 config-and-settings → 三级 `env-example-catalog`
- 实现落点：`plugins/bot_unified_runtime/config.py`、`plugins/bot_unified_runtime/domains/core/config`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py`、`docs/config-catalog-full.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

配置面的"给人看的那一层"：`.env.example` 是**可抄的模板**，
`docs/config-catalog-full.md` 是**逐键说明目录**，两者必须和 `config.py` 的字段
一起长。它们解决的是同一个老问题——键在代码里加了，示例没写、目录没登记，
于是下一个人（或下一个 AI）照 `.env.example` 配不出完整环境，或者配了个已废弃的键
还以为是生效的。

本卡不规定怎么读配置（那是 [config-declaration](config-declaration.md)），
它规定**怎么把配置面告诉别人**以及谁来执法。

## 怎么调用

三处同生，缺任一处即红（不是倡议，是门）：

1. `plugins/bot_unified_runtime/config.py` 的 `Config` 加字段（类型 + 默认值 + 校验器，
   路径类字段务必进 `path_fields`）；
2. `docs/config-catalog-full.md` 对应节登记一行（键名、类型、缺省、语义、热更性、
   消费方）；
3. `.env.example` 补同名条目（**密钥一律占位或 `env:` 引用形态**，绝不写真值）。

若该键要允许在对话里改，还要第四处：`domains/chat_reply/runtime/settings.py` 的
`SETTABLE_KEYS`（带 converter）或 `RESTART_REQUIRED_KEYS`（带原因说明）二选一登记
——不登记就意味着控制面与 `/bot runtime` 都看不见它，这是"未登记即不可写"的默认姿态。
`.env`（生产真值文件）被 gitignore，不进仓库、不进聊天、不进日志。

执法门：
- `tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields`
  ——Catalog 与 `Config` 字段双向覆盖（有键无登记、有登记无键都红）；
- `test_config_catalog_registers_new_batch_keys` —— 新增批次键必须显式登记，
  防止整批漏网；
- `test_config_catalog_registers_all_tts_keys` —— TTS 契约族单独一把锁（历史上
  这一族截断失实过一次，改为专项门）；
- `scripts/doc_sync.py --check` —— 机器册 `docs/auto-facts.md` 的字段计数与真身同步，
  叙述文档只准写"以机器册为准"。

## 开关与参数

- 目录的编排单位是"功能批次节"（一个能力/一波改动一节），不是字母编号；
  新增节时同步在 `docs/README.md` 索引留指针。
- 每行的必备字段：键名（`BOT_*`）、对应 `Config` 字段（`bot_*`）、类型、缺省值、
  语义一句话、**热更性**（可热改 / 需重启 / 装配期冻结）、消费点（写到函数或模块名，
  不写行号——行号是本项目最容易腐烂的引用形态）。
- 密钥类条目在目录里也只写口径与形态（"值走 `env:BOT_XXX_API_KEY`，真值只在 `.env`"），
  绝不摘录真实值或 fingerprint 之外的任何身份信息。

## 失败时看到什么

- 加了字段没进目录 → `test_config_catalog_covers_config_fields` 直接红，报缺登记的键名。
- 加了字段没进 `.env.example` → **没有机器门**（`.env.example` 不是可解析契约面），
  只能靠评审发现；这是当前的执法缺口，别假设"门会替我记住"。
- 目录里写了过期值（例如把已接线键标成"死键"）→ 门只查**覆盖率**不查**准确性**，
  所以事实性漂移会静默存在；历史上真发生过两处（一处截断失实、一处"死键"旧判定
  被后续接线推翻），都是靠人工复核纠正的。改配置语义时，目录那行要一起改，
  不要只改代码。
- `.env` 缺键 → 生产按 `Config` 默认值装载（除严格模式的离线入口会拒绝），
  所以"没配"和"配了默认值"在运行上不可区分；判别看
  `python scripts/verify_chatbot_env.py` 与 `/bot status`，别看 `.env` 猜。

## 测试与验收

门本体：`tests/test_doc_sync_gates.py`（上述三把 catalog 锁）、
`tests/test_documentation_consistency.py`（叙述文档禁手写漂移计数）、
`tests/test_datafix_runtime_paths.py`（相对路径必须经 runtime_paths 解析——
目录里凡写运行数据相对路径的前提就是它会被重映射）。
复跑：`powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"`
与 `python scripts/doc_sync.py --check`。
人工验收：任选一个近期新增键，确认 `Config` 字段、目录行、`.env.example` 条目三处
同义同缺省，且热更性标注与 `SETTABLE_KEYS`/`RESTART_REQUIRED_KEYS` 实况一致。
