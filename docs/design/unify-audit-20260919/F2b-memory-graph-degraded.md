# F2-b — 记忆图谱「降级来源当正常」修复记录（2026-09-19）

## 0. 状态（进行中/完成 + 时间戳）

- 状态：**完成**（2026-09-20；tsc/lint:layout/build 三门实跑 exit 0，输出贴 §5；未 commit——共享工作树，提交裁决权在用户）
- 开工时间戳：2026-09-20（本地会话）
- 本文件随做随写（前一席位阵亡丢整程的教训：先落盘再动手）。

## 1. 问题复现路径（数据从哪个端点来、降级标志位叫什么、在哪一层被丢掉）

**端点与真相源**（后端只读核证，2026-09-20 快照）：

- 记忆图谱页 → `GET /api/v1/memory/graph`（路由装配在 `plugins/bot_unified_runtime/control_plane/api/webui_ext.py`，实现 `plugins/bot_unified_runtime/control_plane/webui_memory_graph.py` `MemoryGraphService.graph/_assemble`）。
- 知识库页 → `GET /api/v1/knowledge/collections` 与 `GET /api/v1/knowledge/terms`（实现 `plugins/bot_unified_runtime/control_plane/webui_knowledge.py` `KnowledgeCatalogService`）。

**后端真实降级标志位（不发明，逐条核码）**：

1. `memory/graph` 信封层：`status:'source_unavailable'` + `reason ∈ {all_sources_missing, query_budget_exceeded}`（`graph()` 超预算分支与 `_assemble()` 全源缺失分支）。→ 前端 `resolveSemantic`（`webui/src/lib/api-client.ts`）已把它折叠为 phase `'unavailable'`，`SemanticState` 有诚实呈现。**这一层不是本缺陷。**
2. `memory/graph` payload 层（status:'ok' 内，**核心缺陷位**）：
   - `sources: {history|memory|quirks|affinity: 'ok'|'missing'|'unreadable'}` —— 任一源 ok 即整包 `status:'ok'`，其余源标 `missing/unreadable`；
   - `truncated: true` + `nodes_total`（节点按度数排序封顶 max_nodes 后截断，`stats` 恒为截断前总量）。
3. `knowledge/collections` payload 层：每个 item 带 `enabled: boolean` + `reason: string|null`，后端实发枚举（`collections()` 逐行核码）= `glossary_source_unavailable / missing_source / incomplete_schema / disabled_by_config / no_dedicated_store`。
4. `knowledge/terms` ok payload **没有任何** degraded/partial/truncated 字段；`meme_tags` 聚合对坏 JSON 行静默跳过（"聚合可得部分即报部分"）——**后端对此无指示位**，不为其造 UI，登记 §6。

**丢在哪一层**：

- `sources` 降级位：`webui/src/pages/memory-graph.tsx` 已算出 `degradedSources`，但**只在选中节点的详情侧栏内渲染**（"memoryGraph.sourceUnavailable" 段落，位于 `{selectedNode && ...}` 分支内）——未点节点的操作员看到的是与全源健康完全相同的页面。图谱为空 + 部分源缺失时，页面还宣称「该时间窗内无记忆关联数据」，把"源塌了"说成"没数据"。
- `truncated`：有 chip（SectionCard action 位），但文案「仅显示关联最多的 {{count}} 个节点」不报截断前总量 `nodes_total`，操作员无法知道图被剪掉了多少。
- collections `reason`：`webui/src/pages/knowledge.tsx` 对所有 disabled 集合一律显示笼统「未启用」（`knowledge.notEnabled`），把"库文件缺失/表结构不完整/项目内根本无独立存储/配置开关关闭"四种性质不同的状态混成一个词——前两种是数据质量降级，后两种不是；「未启用」还会误导操作员去拨开关。

## 2. 前端消费面（逐处 文件:行）

（锚点优先；下列为 2026-09-20 快照行号，改前已 re-grep）

- `webui/src/hooks/use-semantic-query.ts` `useSemanticQuery`：200 信封 → `resolveSemantic` → phase 四态；ok 时 `state.source`（信封 'memory_graph'/'knowledge_collections'/…）随带但两页均未消费。
- `webui/src/pages/memory-graph.tsx`：
  - `graph = useSemanticQuery<MemoryGraphData>(['memory-graph', window], …)`（数据入口）；
  - `degradedSources` useMemo（Object.entries(data.sources).filter(≠'ok')，**只喂侧栏**）；
  - SectionCard `action={data.truncated ? CategoryChip(t('memoryGraph.truncated',{count: data.nodes.length})) : undefined}`（缺 total、tone info）；
  - 空态分支 `data.nodes.length === 0 → memoryGraph.empty/emptyHint`（不区分源塌与真没数据）；
  - 侧栏 `degradedSources.map(… memoryGraph.sourceUnavailable …)`（name/state 均为裸英文码）。
- `webui/src/pages/knowledge.tsx`：
  - 集合 chip 行与 allDisabled 区块两处 `${item.name} · ${t('knowledge.notEnabled')}`（reason 全被抹平）；
  - `TermCard` 的 enabled/disabled Badge（acg 源逐行态，本身如实，不动）。
- 可复用件：`webui/src/components/semantic/semantic-state.tsx`（`reason.*` 人话映射先例）、`patterns.tsx` `CategoryChip`（tone 枚举 good/warn/bad/info/purple/magenta/brand/flat）。
- i18n：`webui/src/locales/{zh-CN,en}/common.json` 顶层 `reason.*` 块已有 17 码人话（含 `missing_source/incomplete_schema/glossary_source_unavailable/disabled_by_config`），无 `no_dedicated_store`。

## 3. 修改清单（before → after）

**`webui/src/pages/memory-graph.tsx`**（锚点：`isNotFound` 函数、`{/* 主体状态 */}` 注释、SectionCard `action=`、侧栏 `sourceUnavailable`）

1. `import { Search }` → `import { Search, TriangleAlert }`（警示图标复用 semantic-state 同款 lucide 件）。
2. 新增模块级 `SOURCE_NAMES/SOURCE_STATES` 白名单 + `sourceName()/sourceState()` 人话映射（表外值回退裸码原文，绝不编语义）——与 `knowledge.tsx` 既有 `scopeLabel` 白名单同规。
3. 工具行之后、主体状态分支之前新增**页面级降级警示条**：`data && degradedSources.length > 0` 时渲染（`data` 仅在 phase ok 非空 → 全源缺失/超预算走既有 unavailable 态，不误加警示；loading/error 不渲染）。内容 = TriangleAlert + `memoryGraph.partialTitle` + 每个非 ok 源一枚 warn `CategoryChip`（本地化名+态）。位置在空态/画布两条分支的公共上游：源塌 + 窗口空时，「无记忆关联数据」不再单独误导。
4. truncated chip：`t('memoryGraph.truncated', {count})` → `{count, total}`，文案改「节点集已截断：共 {{total}} 个，仅显示关联最多的 {{count}} 个」（total=`data.nodes_total`，后端契约字段）。tone 保持 info（max_nodes 封顶是文档化预期行为，非数据质量异常；与 warn 级源塌分层）。
5. 侧栏 `sourceUnavailable` 行：`{name, state}` 裸码 → 本地化 `sourceName(t,name)/sourceState(t,state)`。
6. 文件头注释同步（truncated 带总量 / F2-02 warn 条）。

**`webui/src/pages/knowledge.tsx`**（锚点：`SCOPE_KEYS`、`selectCollection`、两处 CategoryChip label、头注释）

1. 新增 `DISABLED_REASON_LABEL_KEYS`（覆盖后端 collections 实发全部 5 码）。
2. 组件内 `disabledSuffix(item)`：enabled → 空；reason 命中映射 → 短标签；reason 非 null 未命中 → `knowledge.disabledWithCode`（裸码如实展示）；reason null → 原 `notEnabled` 回退。
3. 集合 chips 行与 allDisabled 区块两处 `${item.name} · ${t('knowledge.notEnabled')}` → `${item.name} · ${disabledSuffix(item)}`。tone 一律不动（不加 warn——`missing_source` 对新装库是中性事实，涂色会把正常态误报成告警，违反"不降级正常响应"）。
4. 头注释同步。

**locale 两文件成对新增/改值**（键集合完全一致）：

- `memoryGraph.truncated`（改文案，+`{{total}}`）；新增 `memoryGraph.partialTitle` / `sourceChip` / `sourceName.{history,memory,quirks,affinity}` / `sourceState.{missing,unreadable}`。
- `knowledge.disabledReason.{noDedicatedStore,sourceUnavailable,schemaIncomplete,offByConfig}`、`knowledge.disabledWithCode`。
- 未动任何既有键的语义；`reason.*` 顶层块复用不动。

## 4. 为什么这样修（契约依据）

- **后端已如实、前端再丢弃**：`webui_memory_graph.py` 模块 docstring 钉死「库缺失 = 该源标记 missing…一律 200 信封内如实降级，不崩、不造数」「截断如实 truncated:true + nodes_total（stats 恒为截断前总量，不因截断撒谎）」。payload 层 `sources`/`truncated`/`nodes_total` 就是降级指示位的合同字段；F2-02 的根因全在消费端把合同字段折叠进了侧栏。本修只是把既有合同数据呈现回页面级，**零新造语义**。
- **collections reason 是合同字段**：`webui_knowledge.py` docstring「collections 里如实 not_available（enabled:false + 固定 reason），绝不假造条目」；`api-client.ts` 的 `KnowledgeCollection.reason: string | null` 本就是可选性正确的类型（未加 `!`/`as`，未改型）。
- **不降级正常响应**：警示条严格键控 `sources[x] !== 'ok'`；全源缺失/超预算走信封 phase `unavailable`（既有 `SemanticState` 呈现），不叠加第二重警示；truncated 保持 info 档（预期行为）与源塌 warn 档分层；knowledge 集合 chip 不加 warn 色（新装库 `missing_source` 是中性事实）。
- **降级不遮数据**：警示条在画布上游共存渲染，部分图照常可看可点可筛。
- **未知值诚实回退**：源名/态/reason 三个映射全部白名单制，表外值回显裸码原文（同 `scopeLabel`/`reasonKey` 既有先例「未知码回退原码，绝不编语义」）。

## 5. 验收命令与实跑输出

（2026-09-20 实跑，webui/ 目录）

```
$ node -e "<locale 键集对账脚本>"        # zh/en 平铺键集互比
onlyZh: none | onlyEn: none

$ npx tsc --noEmit -p tsconfig.app.json
（无输出）exit=0

$ npm run lint:layout
版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）
exit=0

$ npm run build
版式宪法机器门：全部通过（…）
✓ 2448 modules transformed.
[plugin vite:singlefile] Inlining: index-KNo0IdmE.js / style-CkSB_y6b.css
dist/index.html  979.73 kB │ gzip: 298.56 kB
✓ built in 5.38s
build exit=0
```

未用 `tsc -b`（防 .tsbuildinfo 入树）；未直跑 python（零缓存面为零风险）。

## 6. 未修与遗留（登记，不越域修）

1. **meme_tags 部分聚合无指示位（后端缺口，不造 UI）**：`webui_knowledge.py::_meme_tag_counts` 对坏 JSON 标签行 `continue` 静默跳过（「聚合可得部分即报部分」），terms ok payload（`collection/page/page_size/total/items`）**无任何** partial/skipped 字段——前端无法诚实地标注「本目录基于部分聚合」。若后端要补，施工坐标（**属其它域文件，本席未动**）：
   - `webui_knowledge.py`：`_meme_tag_counts` 返回 `(status, tags, skipped_rows)`，`skipped += 1` 于 `except (json.JSONDecodeError, TypeError)` 分支；`terms()` 的 `collection == "meme_tags"` 分支把 `skipped_rows` 放进 data（`"aggregation_skipped_rows": skipped_rows`）。
   - `webui/src/lib/api-client.ts`：`KnowledgeTermsData` 增可选 `aggregation_skipped_rows?: number`。
   - `knowledge.tsx`：`typeof termsData.aggregation_skipped_rows === 'number' && > 0` 时页级 info 条（本席域内，等上游字段落地即接）。
2. **glossary 多文件部分读失败同样无指示位**：`_load_glossary_entries` 对单文件 `OSError/UnicodeError` 静默 `continue`，任一文件成功即 `enabled:true`——「6 个术语表只读到 5 个」与全量健康不可分。后端同样缺字段（可并案：collections item 增 `sources_loaded/sources_total`）。仅登记。
3. **信封 `state.source`**（`useSemanticQuery` ok 相携带 'memory_graph'/'knowledge_terms:<coll>'）两页均未消费——非缺陷（payload 内已有 collection/window），留作后续页脚数据源徽章素材。
4. knowledge 集合 chip 的 tone 分层（哪些 reason 该 warn 色）已按「中性事实不涂警示色」裁定为不改色只改词；若审计复议需要色分层，属视觉裁定不属本缺陷。
