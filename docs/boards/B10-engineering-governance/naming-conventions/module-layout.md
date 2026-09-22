# 命名与结构规范 · 模块与目录归属规则

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.naming-conventions · 模块与目录归属规则

- 层级：一级 B10 → 二级 naming-conventions → 三级 `module-layout`
- 实现落点：`docs/boards/_conventions.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

管「东西放哪」。规范条款在 `docs/boards/_conventions.md` 第一节（含层名白名单，本页不复制清单）；本页给的是落点判据、垫片规则，以及**已经发生过的失控形态**——它们解释了为什么这些条款是硬门而不是倡议。

一句话判据：**一个二级功能一个目录，一个逻辑一个真身，共用的东西必须升级成中央件，不许就地复制。**

## 怎么调用

新增代码时的决策顺序（照做即可，别跳步）：

1. 先在板块树里找这个功能有没有三级入口（`docs/boards/BNN-*/<feature>/<l3>.md`）。找到 → 调它的公开函数；找不到 → 它是没登记，先登记再写，不许复制一份近似的。
2. 落点固定 `plugins/bot_unified_runtime/domains/<域>/<层>/<file>.py`，层名只能取白名单里的现役集合；要加新层名，先回规范件登记一行并说明为什么。
3. 需要跨功能共用 → 提到 `domains/core/`（全仓唯一口径件）或该板块的 `_common/`。已存在的中央件即范式：会话键 `domains/core/session_keys.py`、文本边界 `domains/core/text_boundary.py`、契约件 `domains/core/contracts/`、板块声明源 `domains/core/board_taxonomy.py`。
4. 改名或搬家 → 旧路径只留再导出垫片（`Compat shim` 头注 + PEP 562 `__getattr__`），垫片不算实现；文档、生成器与哈希清单同批改指真身。

文档侧同构：板块根目录只放 `README.md`，功能文档只能出现在自己那个二级目录里；`docs/` 与根目录只留现役权威件与生成物，波次过程件（席位日志、brief、report）留在 `.superpowers/`。

## 开关与参数

无配置键。执法形态是「结构锁 + AST 扫」两类：

- 结构门：`tests/test_board_taxonomy_gate.py`（板块 slug kebab、二级 id 前缀、`impl_paths` 指向的路径必须真实存在、空壳功能不许存在）、`tests/test_capability_registry.py`（能力注册快照）。
- AST 残骸扫：垫片退役各波用 AST 核对「旧路径直连残余归零」，退役清单与预研在 `docs/design/v21r2-shim-retirement-inventory.md` 与统一波台账；`tests/test_v21_wiredirect_unified_path.py` 锁存量旁路族「只登记不迁移」（此口径自 2026-09-22 WAVE42 起对群摘要 / 日常助理两族放开，它们改道中央出口 `submit_active_push`，族数以 `tests/test_outbound_gate.py` 的 T6 锁与 `tests/test_outbound_bypass_prohibition_gate.py` 豁免表为准，见 `.superpowers/sdd/2026-09-21-unify-wave/decisions/WAVE42-active-push-central-exit.md`），`tests/test_capability_result_unique.py` 锁同名类型的分层归并结果。
- 路径写法面：`tests/test_doc_link_integrity.py` 把「坐标指向垫片」「旧路径字面不存在」计入棘轮，所以搬家不收敛文档会被追账。

## 失败时看到什么

- 门红：消息直接给「哪个功能、哪条路径不存在、哪个席位无人认领」。
- 更常见的是**当下全绿、日后打架**——历史样本值得逐条留着当反面教材：触发词字符集曾经六份副本并存；`pick_variant` 有四套互斥实现；占卜有两套牌算与两颗 `DrawError`（已合并为 `domains/divination/data/deck_math.py` 作算法真身 + `store/draw_store.py` 作存储真身，旧件降为垫片并加 AST 锁）；同名 `CapabilityResult` 两个（已分层归并：契约版留原名做呈现契约，壳版改名 `InvocationResult` 做执行信封）；渲染顶层 `output/card_render/` 与 `domains/render/card_render/` 双址（后者真身、前者再导出垫片）。
- 判据：**两处实现互相打架的那次，才是它真正的报错**。所以合并动作必须配一条「只此一处」的机器锁，否则等于没合。

## 测试与验收

改动落点后自检：`tests/test_board_taxonomy_gate.py` + 该域回归 + `dev.ps1 -Task runtime-layout`（防把生成物写进源码树）。真身搬过一次就要顺手确认三件事：垫片还能 import、文档坐标改指真身、哈希清单在册件若改名要重录（`tests/verify_hashes.py:TRACKED_FILES`）。

要留意的现存结构缺口：根 `__init__.py` 与 `domains/chat_reply/capabilities/echo.py` 是多波共享文件，改动互相顶漂坐标棘轮与哈希；施工顺序上排在最后，改完立即复跑生成物 `--check`。
