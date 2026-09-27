# 生成物与机器事实册 · 会漂移计数的唯一落点

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.generated-artifacts · 会漂移计数的唯一落点

- 层级：一级 B10 → 二级 generated-artifacts → 三级 `machine-ledger`
- 实现落点：`scripts/doc_sync.py`、`scripts/command_catalog.py`、`docs/auto-facts.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`scripts/doc_sync.py` 从代码整册重生成 `docs/auto-facts.md`（机器事实册）。它是全仓「会漂移计数」的唯一落点：模板清单、`RouteKind` 成员清单、帮助 topic 数（含重名数）、测试文件数、`config.py` 的 `bot_*` 字段数、哈希清单范围——六项全部机械推导，不写生成时间戳（保证字节确定性，避免无意义漂移）。

生效条件很简单：册子的当前字节等于「此刻从代码推导出的字节」。不等即漂移。

这条规矩本身有执法者：AGENTS 铁律第十条规定叙述文档禁手写会过期的计数，一律写「以机器册 `docs/auto-facts.md` 为准」或指向真身定义处；确需保留旧数字则同行标明「当时值」。历史上这类数字被手写过十四处，每一版都在几天内过期。

## 怎么调用

- 写盘：`python scripts/doc_sync.py --write`（集中面，主会话执行）。
- 体检：`python scripts/doc_sync.py --check`，缺省无参即 `--check`，漂移退出码一。
- 内部构件：`build_document()` 拼装整册文本；`check()` 做字节等值比对；取数函数 `build_document` 依赖 `_tpl_list()`（模板目录 glob）、`_route_kinds()`（`domains/chat_reply/runtime/base_router.py` 的枚举体正则）、`_help_topics()`（`domains/chat_reply/capabilities/echo.py` 的 topic 字面量正则）、`_test_file_count()`（`tests/test_*.py` glob）、`_config_key_count()`（`config.py` 字段行正则）、`_tracked_files()`（复用 `tests/verify_hashes.py:TRACKED_FILES`，不另建清单）。
- 跨件引用：`scripts/board_doc_sync.py` 与叙述文档门 `tests/test_documentation_consistency.py` 把「机器册」当作被指向的权威；`docs/config-catalog-full.md` 头部同样把字段计数让给本册。

静态解析而非导入，是本入口的硬约束：导入插件包会触发 NoneBot 装配，脚本必须能脱离 bot 独立运行。

## 开关与参数

没有配置键，也不读 `.env`。唯一影响行为的外部变量是 `BOT_AUTOSYNC`：置一时 `tests/conftest.py` 会在 session 开始静默重跑三件生成物的 `--write`（含本册），跑完打印改动汇总，人完全无感；显式置零（或未设且不在 `dev.ps1 -Task test` 下）则钩子整体跳过、绝不写盘。自动重录失败只 warning 不阻断——报红交给常驻 `--check` 门。

哈希清单范围（本册的最后一行）由 `tests/verify_hashes.py:TRACKED_FILES` 决定，要改范围改那一处，本册自动跟随。

## 失败时看到什么

stderr 一行：`doc_sync: docs/auto-facts.md 与代码推导结果不一致；跑 python scripts/doc_sync.py --write 重生成。`；退出码一。

pytest 侧的红消息由 `tests/test_cross_validation_gates.py` 包装，会把上面这段 stderr 原文附上，并提示重录命令。红不等于坏：新增能力、加模板、加配置键都会让它红，这是设计意图——逼一次「有意识的 `--write`」。

判据纪律：**红先归因再决定修不修**。若是本波改动引起，随批重录；若是他波在飞造成，只报备、不代录、不代降任何基线。

## 测试与验收

`tests/test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync`（册子与代码互证）、`tests/test_cross_validation_gates.py::test_verify_hashes_manifest_clean`（同族的哈希件，两门常一起红一起绿）、`tests/test_doc_sync_gates.py`（配置目录与路由矩阵对代码取集合比对）、`tests/test_documentation_consistency.py::test_narrative_docs_defer_volatile_counts_to_machine_ledger`（叙述文档让计数给本册，含「注毒必红、带指针放行」两条自证）、`tests/test_board_taxonomy_gate.py::test_board_docs_do_not_handwrite_volatile_counts`（板块正文同一口径）。

真机验收：无外部依赖项，属静态门；复跑命令见 `task-entry/README.md`。
