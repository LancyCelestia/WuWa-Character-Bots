# 文档体系与板块树 · 一/二/三级板块树本体

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.documentation · 一/二/三级板块树本体

- 层级：一级 B10 → 二级 documentation → 三级 `board-tree`
- 实现落点：`docs/README.md`、`docs/HANDBOOK.md`、`docs/CODE-MAP.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

说明这棵树本身的形状：三个层级是什么、怎么判定、落在磁盘哪里。定义真身在 `docs/boards/_conventions.md` 第〇节，本页是给接手者看的展开版与读法。

- **一级 板块 `BNN`**：回答「实现这个 bot 需要哪十大块」。十块是上限，不得随意增删，编号连续不许断号（由 `tests/test_board_taxonomy_gate.py` 的结构门执法）。磁盘形态 `docs/boards/BNN-<slug>/`，目录内只准放一个 `README.md`。名单的真身＝声明源 `plugins/bot_unified_runtime/domains/core/board_taxonomy.py` 各板块条目的 `label`（生成物 `docs/boards/README.md` 是它的投影），改名以声明源为准；下面这串是**开窗当时值**：B01 接入与协议、B02 路由与中央调度、B03 人格·对话·内容安全、B04 记忆·知识·笔记、B05 外部资讯与数据服务、B06 多媒体与娱乐、B07 日程·自动化·助理、B08 渲染与出站统一、B09 控制面·配置·可观测、B10 工程基座与治理。
- **二级 功能 `BNN.<slug>`**：一组同源实现、同一门禁口径的功能簇，一个功能一个目录，文档只出现在自己目录内。本板块的七个二级功能就是本页所在树的上七级目录（`task-entry` / `generated-artifacts` / `test-gates` / `naming-conventions` / `security-guardrails` / `workspace-hygiene` / `documentation`），逐条以声明源 `fid="B10.*"` 为准。
- **三级 入口 `BNN.<slug>.<l3-slug>`**：一个可独立调用、可独立开关的功能入口，形态是一张卡（`<二级目录>/<l3-slug>.md`）。

## 怎么调用

判定「算不算一个三级入口」是写死的五条，不接受「感觉这算一个功能」：

1. 代码里占一个 `RouteKind` 席位 ⇒ 一个三级入口（一个能力一张卡）。
2. 不占路由席位但有 `capability_id`（内部能力、旁路监听、调度器）⇒ 一个三级入口。
3. 纯机制件（契约、护栏、生成物、规范）由所属二级功能用 `extra_l3` **显式声明** ⇒ 一个三级入口。本板块绝大多数页属这类（例如 `machine-ledger`、`credential-scrub`），所以它的存在本身就在告诉读者「这是个机制件，不是个命令」。
4. 帮助主题**不**生成三级入口，它挂到对应入口卡片的「别名与帮助页」列。
5. 更细的粒度（一个函数、一个参数、一个模板）都不是入口，写进所属卡片正文。

读法约定：一级页看职责与边界；二级页按「这个功能解决什么 → 处理流程 → 边界与降级 → 测试与验收 → 现行缺陷」五节读；三级页按「这个入口做什么 → 怎么调用 → 开关与参数 → 失败时看到什么 → 测试与验收」五节读。小节标题是骨架约定，`tests/test_board_taxonomy_gate.py:test_generated_pages_have_full_skeleton` 两条腿并立：一条管骨架没被动过（AUTO 双标记 + 标记外正文非空），一条管人写区小节**集合与顺序**同类一致（G-T2 同类骨架由 `scripts/board_doc_sync.py` 的骨架常量派生，与页同一支取形，不是长度近似）。

## 开关与参数

树的结构参数只有两个：**声明源**与**生成器**，见 `doc-taxonomy-sync.md`。没有配置键、没有运行期开关，文档树不参与装配。

绘图与引用口径（统一约定，违反不会立刻红，但评审按契约漂移记）：图只用 mermaid 的 `flowchart LR/TD` 与 `sequenceDiagram` 两种；节点名用稳定 id（如 `B03.affinity-mood`）不用中文长句；一条主链路一张图，功能卡内只画自己那一段——每张卡各自重绘全链路正是漂移之源。引用代码只写 `路径` 或 `路径:函数名`，不写行号（域重组后旧路径多是活转发垫片，行号不可信）。

## 失败时看到什么

树长歪的四种报错形态（都来自 `tests/test_board_taxonomy_gate.py`）：板块数不是十或编号断号；二级 id 前缀与所属板块不符、slug 非 kebab；代码里有席位/帮助主题无人认领，或文档认领了代码里不存在的席位（**存在性锁不算数**，这是活性覆盖门）；`impl_paths` 指向不存在的路径（文档指空位）。

反向情形也要认得：**新增一个能力，板块树会自动多出一张卡**；改一个 label、优先级或帮助主题，所有投影自动跟随；删一个能力而文档还认领它，直接红。所以「我改了代码但没动文档」通常不会失守，失守的是「我改了文档想糊弄代码」。

## 测试与验收

结构门全族 + 三发注毒自证见 `doc-taxonomy-sync.md`；本层的验收动作是复跑 `python scripts/board_doc_sync.py --check`（只读）与 `tests/test_board_taxonomy_gate.py`。人工侧另查两件事：正文有没有留生成器骨架的占位句、有没有手写会漂移的计数——**两件事今天都有自动账**：前者＝`scripts/spec_gates_census.py:board_body_completeness`（逐页分档，占位判定与 `scripts/board_doc_sync.py` 的骨架常量逐字比对）＋ `tests/test_body_completeness_synonym_shell.py`（同义措辞空壳），后者＝G-T3 `scripts/doc_fact_discipline.py`。机器管到形态，措辞是否说人话、内容对不对仍归评审。
