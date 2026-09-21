# 文档体系与板块树 · 板块树与代码的自动同步

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.documentation · 板块树与代码的自动同步

- 层级：一级 B10 → 二级 documentation → 三级 `doc-taxonomy-sync`
- 实现落点：`docs/boards`、`docs/README.md`、`docs/HANDBOOK.md`、`docs/CODE-MAP.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`scripts/board_doc_sync.py` 是十板块树唯一的投影口：把三份声明源机械推导成 `docs/boards/**` 的自动生成段，并用 `--check` 充当门禁。它的存在让「一处变更、处处跟随」成立——加一个能力，文档树自动多一张卡；改 label、优先级、帮助主题，所有投影自动跟随；删能力而文档还认领，直接红。

三份声明源（全部静态解析，**不 import 插件包**，因为插件根 `__init__.py` 是重件、导入会触发 NoneBot 装配）：

- `plugins/bot_unified_runtime/domains/core/board_taxonomy.py`：板块树本体（`BoardNode` 与其内嵌 feature 声明，含 `bid` / `slug` / `label` / `summary` / `fid` / `route_kinds` / `help_topics` / `impl_paths` / `extra_l3`）。
- `plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py`：能力 keystone（`RouteCapabilityDecl` 给 `capability_id`/priority/label，`HelpTopicDecl` 给帮助主题）。
- `plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py`：`RouteKind` 枚举的字面成员。

## 怎么调用

```
python scripts/board_doc_sync.py --write   # 生成/就地更新 docs/boards/**（集中面）
python scripts/board_doc_sync.py --check   # 只体检（缺省），漂移即退出码非零
python scripts/board_doc_sync.py --dump    # 打派生清单，排障用，不落盘
```

代码入口：`load_taxonomy()`（板块树）、`load_route_index()`（RouteKind → 能力 id/优先级/标签）、`load_route_kind_members()`（枚举成员名）、`build_tree()`（返回树 + 问题清单，体检与断言共用一处实现）。

AUTO 标记契约（人和机器分界线的全部）：常量 `AUTO_BEGIN = "<!-- BOARD-AUTO:BEGIN -->"`、`AUTO_END = "<!-- BOARD-AUTO:END -->"`，中间段每次 `--write` 整体重写，并在开头嵌一行 `AUTO_NOTE` 提示「请勿手改；正文写在标记外」；**标记之外的一切（含首次生成的骨架正文）原样保留**，所以席位正文写在标记之后不会被冲掉。AUTO 段里放的是可以被派生的东西：层级路径、实现落点、二级功能表、三级入口表（路由席位 / 能力 id / 别名与帮助页 / 优先级）。

**席位只准跑只读 `--check`，不准跑 `--write`**：`--write` 会把别席正在改的中间态固化成基线，等于替别人认账。

## 开关与参数

无配置键。影响门的外部变量只有 `BOT_AUTOSYNC`——板块生成器**不在** conftest 的自动重录清单里（那份清单是 command-catalog / auto-facts / render_hashes 三件），所以板块树的漂移不会被自动洗绿，必须人跑 `--write`。

常驻门 `tests/test_board_taxonomy_gate.py` 的四件事：结构自洽（板块数、id 唯一、编号连续、slug kebab、label/summary 非空、空壳功能不许存在）、活性覆盖（每个 RouteKind 席位与每个帮助主题恰好被一个二级功能认领，多认与漏认都红）、实现路径可解析（`impl_paths` 全指向真实仓库路径）、生成物同步（`--check` 退出码必须为零）。

另两把正文门：`test_generated_pages_have_full_skeleton`（每页同时有 AUTO 标记与足够正文，缺标记的页根本没法被自动同步）、`test_board_docs_do_not_handwrite_volatile_counts`（标记外正文同样禁手写会漂移的计数；放行词是「以生成物为准 / 以机器册 / 当时值」，正则点名的是字段、主题、板块、入口、能力、模板、别名、路由席位这类词）。

## 失败时看到什么

`--check` 的问题清单是逐条中文（例：「板块树认领了代码里不存在的 RouteKind：[…]」「代码里有 RouteKind 但无人认领（新增能力漏登板块树）：[…]」「实现路径不存在」「帮助主题被两处认领」），`--write` 之后应全数消失。pytest 侧红消息会把 stdout/stderr 尾部各两千字符贴出来，不必另跑脚本。

典型误判：正文写得很短会让 skeleton 门红（它按标记外正文字符量判存在），这通常意味着该页还没填；板块 slug 用了下划线或大写会被 kebab 门红；把 `impl_paths` 写成旧路径（域重组前的位置）会被路径可解析门红——这条是好事，它在替你追文档死坐标。

## 测试与验收

本入口自身配三发注毒自证（`_tamper` 把声明源改坏到 `tmp_path` 后 monkeypatch，断言体检必报对应问题）：漏认领一个席位、把一个帮助主题被两处认领、实现路径写成不存在的文件。三发各杀一锁，还原后逐字节核对。

写作验收（席位视角）：填完正文跑 `python scripts/board_doc_sync.py --check` 与 `tests/test_board_taxonomy_gate.py -k "skeleton or volatile or in_sync"`，两者绿即可交；若红在自己刚写的页（正文空、手写了计数），按消息改正文，不动声明源、不跑 `--write`。
