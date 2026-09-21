# 路径重映射与树卫生 · 相对路径到 Runtime 的映射

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.workspace-hygiene · 相对路径到 Runtime 的映射

- 层级：一级 B10 → 二级 workspace-hygiene → 三级 `runtime-paths`
- 实现落点：`scripts/runtime_paths.py`、`docs/workspace-archive-policy.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把代码里所有 `data/...` 相对路径统一改写到外部运行数据目录，让源码树一个运行文件都不落。两条实现必须口径一致（否则同一配置在两处解析出两个结果）：

- 运行时侧：`plugins/bot_unified_runtime/config.py` 的 `Config`，路径类字段登记在 `path_fields`，装载期由 `_resolve_runtime_data_paths()` 按 `BOT_RUNTIME_DATA_DIR` 重映射。
- 工具侧：`scripts/runtime_paths.py`，给维护脚本与体检器用的同一套解析（只读路径类设置，绝不打印其内容）。

两边共同语义：剥 `./` 前缀、`data/` 前缀大小写不敏感重映射、绝对路径原样保留、其余相对路径落回项目根。第三方插件的状态目录（`nonebot-plugin-localstore`）另走 `.env.prod` 里的 `LOCALSTORE_CACHE_DIR` / `_CONFIG_DIR` / `_DATA_DIR`，并且 `LOCALSTORE_USE_CWD` 必须显式为假——否则它会按当前工作目录把数据写回源码区。

## 怎么调用

- `runtime_data_dir()`：读 `BOT_RUNTIME_DATA_DIR`（缺省 `data`），相对则接项目根，返回解析后的绝对路径。
- `runtime_path(value)`：把 `data/x` 之类的相对路径映射到运行数据根；绝对路径直接解析。
- `_dotenv_value(key)`：按 `.env` 再 `.env.prod` 的顺序取一个非秘密设置（后者覆盖前者），再用 `os.environ` 覆盖；配套 `_strip_inline_comment` 做**引号感知**的行内注释剥离（`data # 注释` 取 `data`，`"a # b"` 保留引号内容，`a#b` 不算注释）——与 python-dotenv 行为对齐，否则会出现「人眼看是对的、脚本读出来带注释」。
- 生产装载的唯一入口是 `scripts/load_runtime_config.py`（dotenv → environ 覆盖 → JSON 解码 → `translate_env_keys` → `Config.model_validate`），生产 driver、离线 smoke、体检器、重启预检四方共用。它存在的原因是一项 P1 事故定性：装载语义曾有多套不同构实现，导致好配置被体检器**假红**、`.env.prod` 覆盖被**假绿**。工具作者自搓 loader 即等于绕过这里。
- 库文件归属：每个 SQLite 的 owner、建表/迁移位置、清理策略登记在 `docs/db-owners.md`（**只登记不改迁移**；库数与条目数以该文件自身与常驻覆盖门为准）；`db_path` 配成空串的库是进程内实现，不产生文件。

## 开关与参数

影响解析结果的就三类：`BOT_RUNTIME_DATA_DIR`、各 `bot_*` 路径字段（`*.json` / `*.sqlite3` 之类，必须在 `path_fields` 登记才参与重映射）、`LOCALSTORE_*` 三件。全部改动需重启生效（铁律：改代码必须重启 bot；配置同理，且部分 SQLite 路径明确不支持热改）。

`runtime-layout` 体检器读的键清单：`BOT_RUNTIME_DATA_DIR`、`BOT_PERSONA_FILES`、`BOT_KNOWLEDGE_FILES`、`BOT_CARD_ASSET_DIR`、`LOCALSTORE_USE_CWD` 与三个 `LOCALSTORE_*_DIR`，并要求外置知识库文件（向量库 sqlite 与 FAISS 索引）真实存在。

## 失败时看到什么

`runtime-layout: FAIL` 加逐条原因，典型四类：

- `BOT_RUNTIME_DATA_DIR points inside the AI source workspace` / `runtime data directory missing` —— 配置把数据指回源码区，或目录没建。
- `source workspace contains generated/runtime files in ...\data`（`data`/`cache`/`config` 三处逐一查）—— 有代码或测试绕过重映射直接写相对路径。修法分两种：写方是生产代码 → 补 `path_fields` 登记；写方是测试 → `tmp_path` 化；临时处置是备份 `%TEMP%` 再清并复跑本门。
- `source workspace contains N Python cache path(s)` —— 直跑解释器没带 `PYTHONDONTWRITEBYTECODE=1`。
- `LOCALSTORE_USE_CWD=true would write third-party state into CWD` 或某个 `LOCALSTORE_*_DIR` 指回源码区。

`_dotenv_value` 侧的静默失败更要小心：值里带了未剥离的注释会让下游解析成空/畸形，表现是「配置看着对、行为不对」。判据是拿同一份 dotenv 走 `load_runtime_config` 与 `runtime_paths` 两路对比结果。

## 测试与验收

`dev.ps1 -Task runtime-layout`（结构体检，离线，不开库内容）；`tests/test_datafix_runtime_paths.py`（写入根治：全部相对路径统一经 runtime_paths 解析）；配置侧装载一致性由 `tests/test_runtime_config_loader.py` 一类件守（生产 Config 真身为判据）。

日常口径：**发现源码树出现 `data/`、`__pycache__`、`.pytest_cache`、`.ruff_cache`、`.mypy_cache` 任一，先备份到 `%TEMP%` 再清，然后复跑 `runtime-layout` 确认清零**；清理时严禁连坐删除 `domains/weather/assets/qx.json`（随包内置资产，见 `workspace-hygiene/README.md` 的例外条）。
