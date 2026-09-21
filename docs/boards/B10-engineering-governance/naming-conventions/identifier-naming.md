# 命名与结构规范 · 标识符与参数命名规则

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.naming-conventions · 标识符与参数命名规则

- 层级：一级 B10 → 二级 naming-conventions → 三级 `identifier-naming`
- 实现落点：`docs/boards/_conventions.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

管「符号的名字」这一层：模块文件、公开与私有函数、参数、常量表、配置键、稳定 id、文档目录名。规则表本体在 `docs/boards/_conventions.md` 第二节（含正反例），本页不复制第二份；本页写的是**为什么这么定**和**违例在哪被拦**。

命名不是美观问题，是寻址问题。本仓有二十来个域、上千个文件、多波并发作业，任何「同义词改名」「顺手起个 `tools` 这类万能名」都会让下一个人找不到真身，进而复制出第二真身。所以规则的核心只有一句：**名字要能反查唯一真身**。

## 怎么调用

不需要调用，需要遵守。三条最常撞的：

- **动词前缀即语义**：`build_*` 构造装配、`get_*` 取值、`is_*` / `has_*` 谓词、`resolve_*` 归一、`load_*` / `save_*` 存储、`handle_*` 能力入口、`check_*` 门禁与体检、`normalize_*` / `sanitize_*` 文本整形。看到 `check_` 就该知道它可能把流程拦停；看到 `resolve_` 就知道它是归一点而非取值点。混用会让调用方猜错失败语义。
- **布尔参数以 `enabled` / `_only` / `_once` 结尾；判定上下文用 `*for_session`**：因为「这个开关到底是全局的还是这个会话的」是本仓最常见的语义事故源（同一函数被路由门与注入门两处调用、判定口径必须同源，例：`explicit_allowed_for_session` 与 `resolve_intimate_context` 双门同源）。名字后缀就是给调用方看的口径声明。
- **配置键三段式** `bot_<域>_<项>`，pydantic 字段 `bot_*`、`.env` 名 `BOT_*`，一一对应由 `translate_env_keys()` 幂等转写；路径类字段必须进 `path_fields` 参与重映射，否则会把库写到源码树。

稳定 id 族（能力 `bot.<域概念>`、路由 `RouteKind.<UPPER>`、板块 `BNN`、功能 `BNN.<slug>`、帮助主题中文名）是**跨文档与生成器的连接键**：板块树靠 RouteKind 与 `capability_id` 认领能力，控制面与帮助注册表靠 `capability_id` 对齐，改名即断链。禁止拿中文名当 id。

## 开关与参数

无配置键。执法点分布（这是本页存在的理由）：

| 违例 | 谁拦 |
|---|---|
| 板块/功能/入口 slug 非 kebab、二级 id 前缀错、板块编号断号 | `tests/test_board_taxonomy_gate.py`（多条结构自洽门） |
| 帮助主题重复、别名互相冲突、`config_vars` 指向不存在的键、`tests` 路径不存在 | `tests/test_documentation_consistency.py` 一致性门族 |
| `RouteKind` 值形态不完整、路由席位与声明源分叉 | `tests/test_documentation_consistency.py::test_route_kind_values_complete` + `tests/test_doc_sync_gates.py` |
| 配置键加了没进目录 | `tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields` |
| 私有函数被跨模块调用、常量表命名不统一、docstring 缺失 | **无静态门**，靠评审（`REVIEW-WORKFLOW.md` §4） |

## 失败时看到什么

有门的违例：红消息直接点名符号与规则（例「二级 slug 非 kebab」「帮助主题未归档到任何二级功能」）。没门的违例：当下全绿，代价延后出现——最常见形态是「找不到真身 → 复制一份 → 两份开始互相打架」，届时以 P1 记账（`docs/issue-ledger-p2-p3.md`），修法是先归一再命名，别把第二份留下当垫片了事。

改名动作本身有一条硬要求：**旧名只能留再导出垫片**（`Compat shim` 头注 + PEP 562 `__getattr__`），且文档与生成物要同批收敛，否则 `tests/test_doc_link_integrity.py` 的旧路径与「被指到垫片」两条棘轮会上跳——那是门在替你还账，不是它坏了。

## 测试与验收

自检顺序：改完跑 `tests/test_board_taxonomy_gate.py`、`tests/test_documentation_consistency.py`、`tests/test_doc_sync_gates.py` 三件，再跑 `dev.ps1 -Task lint` 与 `typecheck`；生成物由主会话统一 `--write`，本席只 `--check`。

新增符号的验收判据一句话：**从名字能一次跳到真身，从真身能反查它被谁调用**。做不到就改名或补登记，不要补注释。
