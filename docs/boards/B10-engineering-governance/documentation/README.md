# B10.documentation 文档体系与板块树

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.documentation 文档体系与板块树

> 十板块文档树、统一骨架、单一事实源与自动化同步契约。

- 归属板块：[B10](../README.md)
- 实现落点：`docs/boards`、`docs/README.md`、`docs/HANDBOOK.md`、`docs/CODE-MAP.md`

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [一/二/三级板块树本体](board-tree.md) | — | — | — | — |
| [板块树与代码的自动同步](doc-taxonomy-sync.md) | — | — | — | — |
| [旧汇总文档的归属与退役](legacy-doc-migration.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

这仓的文档曾经过量：同一件事在 HANDBOOK、AGENTS、若干 HANDOFF、design 目录与交接报告里各写一遍，每份都在几天内过期一份，而没人知道该信哪份。**新十板块文档树**是为此而立的结构性方案：把「项目由哪十大块构成」做成稳定骨架，把每块的功能与入口做成可自动派生的卡片，把会漂移的事实推给机器册。

本簇就是这套体系自身的说明书，三个三级入口分别管：**树长什么样**（`board-tree.md`）、**它怎么和代码保持同步**（`doc-taxonomy-sync.md`）、**旧文档怎么退役**（`legacy-doc-migration.md`）。规范条文（三层定义、三级入口判定规则、命名与结构、自动化契约、问题分级、质量红线）只有一处真身：`docs/boards/_conventions.md`。

## 处理流程

```mermaid
flowchart LR
  decl[声明源 board_taxonomy.py] --> gen[board_doc_sync --write]
  code[能力 keystone + RouteKind] --> gen
  gen -->|重写 AUTO 段| tree[docs/boards/**]
  tree -->|AUTO 段外| human[席位手写的正文]
  human --> gate[tests/test_board_taxonomy_gate.py]
  decl --> gate
  gate -->|漂移或缺认领| red[全量测试红]
```

三条不变量，整套体系靠它们成立：

1. **结构由代码决定**：板块数、二级功能、三级入口全部派生自声明源，手写文档改不动它。
2. **人工正文永不覆盖**：生成器只重写 `<!-- BOARD-AUTO:BEGIN -->…END` 之间；标记外是人和 AI 的写作面，重跑生成器不会冲掉。
3. **漂移即红**：改了代码没重算生成物，或文档认领了代码里不存在的席位，常驻门当场拦。

## 边界与降级

- 本树是**结构与机制**的说明书，不是运行手册：接入配置看 `docs/acceptance-manual.md` 与 `docs/config-catalog-full.md`，命令逐参数看 `docs/command-catalog.md`，数据库归属看 `docs/db-owners.md`，渲染契约看 `docs/rendering-contract.md`。板块页只准引用、不准复制这些生成物与清单。
- 波次过程件（席位日志、brief、报告、计划）留在 `.superpowers/`，**不进** `docs/boards/`；否则文档树会被一次性内容淹没。
- 并存期口径：`AGENTS.md`（接手规则 + 项目全貌）、`docs/HANDBOOK.md`（全史与总账）、`docs/CODE-MAP.md`（代码导航）仍是现役权威链；本树是新的结构化入口与规范本体。冲突时以 `_conventions.md` 为准，与代码冲突时以代码为准并立即改规范件。
- 计数一律不手写：板块/功能/入口/主题数量由 `python scripts/board_doc_sync.py --check` 从代码派生，叙述文档只写「以生成物为准」。这条对板块正文同样执法（见 `doc-taxonomy-sync.md`）。

## 测试与验收

`tests/test_board_taxonomy_gate.py`（结构自洽 + 活性覆盖 + 实现路径可解析 + 生成物同步 + 骨架完整 + 正文禁手写计数，含三发注毒自证）；`tests/test_documentation_consistency.py`（帮助注册表与路由、配置键、测试路径的一致性门族）；`tests/test_doc_link_integrity.py`（文档坐标与 markdown 链接的死活与棘轮）。

写一页板块正文的自检：不新建结构、不改 AUTO 段、不留「（待写」、小节标题齐全、不写会漂移的计数、引用只写 `路径` 或 `路径:函数名`（不写行号）、图只用 mermaid `flowchart` 或 `sequenceDiagram` 且只画自己那一段。

## 现行缺陷

- 板块树自身没有「内容正确性」门：机制只保证结构、认领与同步，页内描述失真只能靠评审发现。
- 旧文档物理退役未执行（分类账给的是处置建议），当前是「新树 + 旧权威件」并存状态；读者需要知道谁是最新口径，这本身是过渡期成本。
- 三级入口正文由各席位手写，风格与详略不齐；统一靠 `_conventions.md` 的骨架约定与评审，尚无自动的「正文完整度」判据（现有门只查正文非空与无「待写」的近似形态）。
