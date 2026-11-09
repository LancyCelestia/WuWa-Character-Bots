# 控制台系统性重构实施计划（W14）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把守岸人控制台从「12 个独立页面的堆叠」重构为「三栏主从布局 + 统一中文化层 + 全部可点可用」，并修掉 7 类用户可感知缺陷。

**Architecture:** 分五层收口——① 新增 `layout/three-pane` 壳（左导航 1/5 + 主区 3/5 + 详情 1/5，窄屏降级为抽屉）；② 新增 `lib/i18n-domain` 领域词表，把 6 类原始英文（动作 ID、渠道 ID、错误原文、状态枚举、模型 ID、配置键）统一译成中文；③ 逐页把「裸表格/裸列表」换成「主从可选中」；④ 无数据的模块如实标注「未采集/未接入」并给出补救入口；⑤ 全程 TDD + 四道门。

**Tech Stack:** React 19 + TanStack Router（browser history）+ Tailwind v4 + shadcn/ui + recharts（懒加载）+ three 0.186。Python 侧 FastAPI + sqlite3 只读服务。

**Spec:** 本文件即规格（用户 W14 原始需求见 §0）。

---

## §0 需求对照与事实基线

### 0.1 用户十一条验收标准 → 本计划的落点

| # | 验收标准 | 落点任务 |
|---|---|---|
| 1 | 全站无未翻译英文 | T2（词表）+ T3（逐页接线）+ T11（不变量测试） |
| 2 | 间距统一 / 边框半隐形 / 辉光阴影 / 层级清晰 | T4（视觉层） |
| 3 | 记忆图谱可点展开、关联完整、图形连接完整 | T7 |
| 4 | 插件与知识库可展开详情 | T8 |
| 5 | 三栏布局 + 右侧详情 + 窄屏响应式 | T1 |
| 6 | 用户列表信息完整 | T6 |
| 7 | 互动统计天/半小时 + 涨粉 | T6（涨粉见 §0.4 结构性缺口） |
| 8 | 调用统计真实渠道名 / 正式模型名 / 分列 / 筛选 / 列宽 / 报错与尝试时间 | T5 |
| 9 | 调用折线图天/周/月/年 + Token + 费用 | T5 |
| 10 | 控制面板可打开，令牌保存生效 | T9 |
| 11 | 运维清晰，资源与配置重构，无加载失败与密码未装配 | T10 |

### 0.2 我本人实测的事实（不是转述，可直接引用）

**账本库 `ChatBot_Runtime/data/llm_billing.sqlite3` → `llm_call_records`**

```
rows = 3397
span = 2026-09-25T04:57:22+08:00 → 2026-10-19T20:14:16+08:00
```

44 列，关键列全部存在：

| 语义 | 列名 | 实测取值 |
|---|---|---|
| 供应商 | `provider_id` | `axon-gemini-38-flash`(2856) / `axon-grok-46`(325) / `axon-qwen35-local`(93) / `default`(67) / `ollama-qwen35-direct`(56) |
| **渠道（中文实名）** | `gateway_channel` | **`恒星纪元 - Gemini`(2794)** / `''`(293) / **`恒星纪元 - Grok`(147)** / **`浅夜の梦 - 专属号池`(87)** / **`Ollama - Qwen`(76)** |
| 实际模型 | `actual_model` | `gemini-3.8-flash`(2923) / `grok-4.6`(325) / `qwen3.5:9b`(149) |
| 状态 | `status` | `success`(3107) / `provider_failed`(240) / `deadline`(50) |
| 错误类 | `error_kind` | `''`(3107) / `timeout`(234) / `server`(36) / `network`(9) / `empty_response`(5) / `bad_request`(3) / `auth`(2) / `invalid_request`(1) |
| Token | `prompt_tokens` / `cache_read_tokens` / `completion_tokens` / `total_tokens` | 18,910,860 / 85,566 / 881,640 / 19,792,489 |
| **费用** | `input_cost_milli` / `cache_read_cost_milli` / `output_cost_milli` / `total_cost_micro` | 合计 **7,113,530 micro = ¥7.1135** |
| 币种 | `currency` | `CNY` × 3397 |
| 定价来源 | `pricing_source` | `gateway_cost_items`(3104) / `channel_spec`(291) / `gateway_cost`(2) |
| 是否有价 | `unpriced` | `0` × **3397（全部有价）** |
| 重试次数 | `attempts_count` | `1`(3035) / `2`(233) / `3`(84) / `4`(45) |
| 归因 | `attribution_status` | `matched`(3104) / `''`(290) / `unavailable`(1) / `skipped`(1) / `miss`(1) |

**三条结论（推翻或修正用户体感）**

1. **「渠道名显示原始变量名」的根因不在数据**：数据里 `gateway_channel` **已经是中文实名**（恒星纪元 - Gemini 等）。真正 نمایش的是 `provider_id`（`axon-gemini-38-flash`）或 `actual_model`（`gemini-3.8-flash`）——前端把技术标识当渠道名显示。
2. **「Timeout 显示异常」的根因不在账本**：`status='success' AND error_kind<>''` = **0 行**。成功行错误字段恒空。所以「显示 Timeout 却能调用」来自**另一张表**（见下）或 `attempts_json` 的中间失败。
3. **费用完全可算**：`unpriced` 全 0、币种单一、单价三档齐全 ⇒ 「输入单价 / 缓存读取单价 / 总费用」**不是结构性缺口**。

**渠道健康 `ChatBot_Runtime/data/channel_health.sqlite3` → `channel_health`（83 行）**

列：`model_id, state, consecutive_fails, latency_ms, last_error, last_probe_at, last_ok_at, updated_at, ema_ms, samples, cooldown_until`

真实样本（**这就是用户说的「Timeout / temporary 异常状态」**）：

```
{'model_id': 'ollama-qwen35-direct', 'state': 'temporarily_unavailable',
 'consecutive_fails': 64, 'latency_ms': 405,
 'last_error': "HTTP 404: model 'qwen3.5:9b' not found", ...}

{'model_id': 'potccv-gpt-56-terra', 'state': 'temporarily_unavailable',
 'consecutive_fails': 3, 'latency_ms': 4000,
 'last_error': 'ConnectTimeout: _ssl.c:993: The handshake operation timed out', ...}

{'model_id': 'potccv-gpt-56-luna', 'state': 'temporarily_unavailable',
 'consecutive_fails': 6, 'latency_ms': 15157,
 'last_error': 'kind=timeout', ...}
```

→ **`state` 是英文枚举（`temporarily_unavailable`/`ok`），`last_error` 是英文原文**。用户「temporary 等异常状态展示」与「Timeout 显示异常」指的就是这两处，不是账本。

**其他生产库实况**

| 库 / 表 | 行数 | 含义 |
|---|---|---|
| `control_plane_events.runtime_log_events` | **10,000** | 日志**有数据** |
| `control_plane_actions.sqlite3` | **0（无表）** | **运维记录空 + 「一览风险与版本」无内容的根因** |
| `knowledge_embeddings.knowledge_chunks` | 35,325 | 知识库正文在 |
| `knowledge_embeddings.knowledge_chunks_fts` | 35,324 | **差 1 = `kb_drift` 红** |
| `control_plane_config.config_overrides` | 9 | 配置覆盖仅 9 条 |
| `control_plane_config.visual_theme` | 1 | 外观主题 1 条 |

**记忆图谱上限（后端硬编码）**

```
webui_memory_graph.py:84  _DEFAULT_MAX_NODES = 120
webui_memory_graph.py:85  _MAX_NODES_CAP = 200     ← 用户说的「只显示 200 个关联」
webui_memory_graph.py:575 truncated = nodes_total > max_nodes
```

**记忆图谱交互（`webui/src/components/three/graph-3d.tsx`）**

```ts
// :281-291
const raycaster = new Raycaster();
const pickAt = (clientX, clientY) => {
  raycaster.setFromCamera(ndc, camera);
  const first = raycaster.intersectObjects(pickTargets, false)[0];   // 只命中可见网格本体
  ...
};
```

→ **无隐形拾取球、无命中容差**。节点半径 7/10/14px（`layering.ts` 侧另有三档），实际可点区域 ≈ 直径 14–28px 且在自转。这就是「点击非常困难」的机制。

**运维动作标签（`control_plane/_app.py:557-575`）**

```python
action_ids = (
    "runtime.reload", "runtime.safe_restart", "adapter.reconnect",
    "snowluma.status", "queue.pause", "queue.resume", "queue.drain",
    "logging.level", "resources.refresh", "llm.routes.reload",
    "knowledge.reindex", "memory.maintenance", "diagnostics.snapshot",
)
action_service = ControlActionService(action_path, registrations=tuple(
    (ControlActionDescriptor(action_id, action_id), _handler_for(action_id))
    for action_id in action_ids
))
```

→ **`label` 直接等于 `action_id`**。前端 `operations.tsx:66` 又把这个 id 用 `font-mono` 渲染出来 ⇒ 屏幕上就是 `adapter.reconnect`。用户说的「`updeer.reconnect` 等内部信息」精确对应 `adapter.reconnect`（他记错了首字母）。

**插件条目的英文残留（`control_plane/webui_plugins.py`）**

```python
"name": "内置功能", "description": "能力树/features store 聚合视图",   # 中文，但含 features
"name": "协议适配器", "description": "pyproject [tool.nonebot.adapters] 静态声明",
"description": f"{package_key} ({module})" if module else package_key,   # ← 纯英文包名
```

→ 适配器组的 `description` 是 `package_key (module_name)` 拼出来的英文。这是「插件名称只显示原始变量名」的实际来源。

### 0.3 已确认的前端基线（我实跑）

```
node scripts/layout-constitution.mjs   rc=0（自测 196/196）
npx tsc --noEmit                       rc=0
node --test src/lib/*.test.ts          359 pass / 0 fail
node --test src/components/appearance/*.test.ts   8 pass / 0 fail
npm run build                          rc=0
```

### 0.4 结构性缺口清单（现有数据做不到，不许编造）

| 需求 | 现状 | 结论 | 最小补救 |
|---|---|---|---|
| **涨粉数（每天/周/月/年、总涨粉）** | 全库无群成员数快照表；`get_chat_member_count` 只在 `group_info.py:807` 单次调用不落库 | **结构性不存在** | 新增 `member_snapshots(ts, platform, chat_id, member_count)` + 每日定时任务；`get_group_info`/`get_chat_member_count` 已有调用面可复用 |
| **用户头像** | 全仓无 avatar 字段；OneBot `sender` 无 avatar | **结构性不存在（需网络调用）** | `get_stranger_info` 逐用户取，必须加缓存表 + 限速，不能列表页直连 |
| **用户签名 / 主页标签** | 同头像，`get_stranger_info` 才有 | **结构性不存在** | 同上，且需用户明确「哪些人的资料值得缓存」 |
| **每半小时互动回数** | `created_at` 是 ISO 带偏移，精度足够 | **可行（纯聚合）** | 只需把 `bucket` 从 `hour|day` 扩到 `half_hour` |
| **完整关联图（>200 节点）** | `_MAX_NODES_CAP = 200` 硬编码 | **需改后端** | 加 `cursor` 分页 + 前端懒加载邻居；不能只调大上限（会卡死浏览器） |
| **配置可写面 49/807** | `SETTABLE_KEYS=49` | **不是缺陷，是安全设计** | 界面必须说清「为什么这个改不了」并给 `RESTART_REQUIRED_KEYS` 提示 |

### 0.5 待用户确认（先问，不猜）

1. **「绘画几」是什么字段？** 全库、全前端 grep `绘画/绘图/绘几` **零命中**。疑似是 `chart` 的音译听错，或某张卡片里的序号。需要用户给截图或指的是哪一列。
2. **「承诺健康」是什么？** grep `承诺/commitment/promise` **零命中**。疑似是「通道健康」的误读。若指 `channel_health`，本计划已按「改小、不喧宾夺主」处理（T5）。
3. **「涨粉」的计量口径**：粉丝数（好友列表）还是群成员数？两者采集方式与语义完全不同。
4. **头像/签名的采集范围**：全量用户（可能几万次 API 调用）还是仅 TopN 活跃用户？
5. **YDY / 「输出文档」/「标签阅读」**：全树零命中，需用户点明。

---

## §1 重构后的信息架构与页面布局方案

### 1.1 现状诊断

| 问题 | 证据 |
|---|---|
| 导航表与真实路由漂 | `lib/console.ts` 的 `CONSOLE_PAGES` 登记 15 页，`pages/` 实际 17 个（`sessions.tsx`、`appearance.tsx` 未登记） |
| 页面各自为政 | 17 个 page 文件共用一个 `AppShell`，无统一「主从」范式：`calls.tsx`(217行) 是纯卡片堆叠、`operations.tsx`(约150行) 是列表、`knowledge.tsx`(318行) 是网格 |
| 无详情栏 | 全站只有 `ops`（`RunInspector`）与 `config`（内联）有「点开看详情」，其余全是「一屏到底」 |
| 信息密度失衡 | 外观页曾 18,998px 高；总览页 6 卡 + 3 图 + 2 TopN 全挤一屏 |

### 1.2 目标信息架构（三栏主从）

```
┌──────────────────────────────────────────────────────────────────────┐
│ 顶栏（sticky, h-16, window 材质）                                     │
│ 面包屑 · 全局搜索 · 系统状态灯 · 主题 · 设置                          │
├──────────┬────────────────────────────────────┬──────────────────────┤
│ 左导航    │ 主显示区                             │ 详情栏                │
│ 20%      │ 60%                                 │ 20%                  │
│          │                                     │                      │
│ 观测      │ ┌ 筛选条（可折叠）────────────────┐  │ ┌ 选中项标题 ──────┐  │
│ · 总览    │ │ 时间窗 模型 渠道 平台 状态       │  │ │ 中文名 + 原始ID   │  │
│ · 调用    │ └────────────────────────────────┘  │ │ （折叠显示）      │  │
│ · Token   │                                     │ ├ 关键指标 ────────┤  │
│ · 延迟    │ ┌ 主列表 / 图表 ─────────────────┐  │ │ 调用次数 成功率   │  │
│ · 好感度  │ │ 行可选中（整行 hover+click）    │  │ │ 平均/中位延迟     │  │
│          │ │ 选中行左侧 3px 主色条          │  │ │ Token 三档        │  │
│ 内容      │ └────────────────────────────────┘  │ │ 费用四档          │  │
│ · 知识库  │                                     │ ├ 明细 ────────────┤  │
│ · 插件    │ ┌ 分页 / 加载更多 ───────────────┐  │ │ 逐次尝试时间线    │  │
│ · 记忆图谱│ └────────────────────────────────┘  │ │ 原始错误（可折叠）│  │
│          │                                     │ └ 操作（重试/跳转）┘  │
│ 管理      │                                     │                      │
│ · 参数    │                                     │  ← sticky, 自身可滚   │
│ · 资源    │                                     │                      │
│ · 模型    │                                     │                      │
│ · 凭据    │                                     │                      │
│ · 受控操作│                                     │                      │
│ · 布局编辑│                                     │                      │
│ · 外观    │                                     │                      │
│ · 会话身份│                                     │                      │
└──────────┴────────────────────────────────────┴──────────────────────┘
```

**栅格实现**（Tailwind v4，不写死 px）：

```tsx
// 三栏：左 1/5 中 3/5 右 1/5；>=1536px 才显右栏
<div className='grid min-w-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[minmax(180px,1fr)_minmax(0,3fr)] 2xl:grid-cols-[minmax(180px,1fr)_minmax(0,3fr)_minmax(240px,1fr)]'>
  <nav aria-label='一级板块'>…</nav>
  <main className='min-w-0'>…</main>
  <aside className='hidden 2xl:block' aria-label='详情'>…</aside>
</div>
```

**窄屏降级**（`< 768px`）：

- 左导航 → 顶栏汉堡打开的全屏抽屉（复用现有 `MOBILE_NAV_ID` 逻辑）
- 右详情栏 → 主区内的 `Sheet`（从底部推出），点条目时打开
- `< 1536px 且 >= 768px`：右详情栏**不常驻**，改为点击后行内展开（`<details>` 或行下插入面板）

### 1.3 中文化层的单点收口

现状：`lib/humanize.ts`（1235 行）已存在，覆盖配置键标题；但**动作 ID、渠道名、状态枚举、错误原文、模型名**各自散落。

目标：新增 `lib/domain-labels.ts`，**五个纯函数**，全站唯一出口：

```ts
// webui/src/lib/domain-labels.ts（新文件）
export function actionLabel(actionId: string): { title: string; hint: string };
export function channelLabel(gatewayChannel: string, providerId: string): string;
export function statusLabel(status: string): string;
export function errorKindLabel(kind: string): { label: string; severity: 'good'|'warn'|'bad' };
export function modelLabel(actualModel: string, modelId: string): string;
```

规则：
- 能查到映射 → 中文
- 查不到 → **中文主语 + 括号原值**（`未知动作（foo.bar）`），**绝不裸露裸英文**
- 未知枚举 → `未知状态（raw_value）`，且该行标 warn 色

### 1.4 视觉层规格（对应用户「边框半隐形 + 辉光阴影」）

现有 `index.css` 已有 `.surface` / `.surface-flat` / `.window` / `.glass-panel` 四件套，且已由 V 席把描边抬到 2.13–2.23:1。本波只补三点：

1. **辉光阴影恢复**：四件套统一加 `box-shadow` 第二层彩色辉光（用 `--glass-glow` token，由品牌色派生），不新增 hex
2. **间距归一**：全站间距刻度收敛到 `16px`（V2 席已把 `--cfg-gap` 改 16，但 `gap-3`/`gap-6` 仍有残留，需扫）
3. **信息层级**：主区「区块标题 fs-page」> 「卡片标题 fs-card」> 「正文 fs-body」> 「辅助 fs-caption」，四档不跳级

---

## §2 各模块组件清单与数据字段映射表

### 2.1 新增组件清单（全部放 `webui/src/components/console/`）

| 组件 | 文件 | 职责 | 关键 props |
|---|---|---|---|
| `ThreePane` | `three-pane.tsx` | 三栏壳 | `nav`, `main`, `detail`, `detailOpen`, `onCloseDetail` |
| `MasterList` | `master-list.tsx` | 可选中的行列表（统一 hover/选中/键盘） | `rows`, `selectedKey`, `onSelect`, `renderRow`, `emptyState` |
| `DetailPane` | `detail-pane.tsx` | 右侧详情容器（sticky + 自身滚动） | `title`, `subtitle`, `rawId`, `children`, `actions` |
| `FilterBar` | `filter-bar.tsx` | 可折叠筛选条（时段/枚举多选/搜索） | `filters`, `value`, `onChange`, `collapsed` |
| `StatGrid` | `stat-grid.tsx` | 等宽等高指标格（`items-stretch` + `flex-1`） | `items` |
| `TimeGrainSwitch` | `time-grain-switch.tsx` | 天/周/月/年 粒度切换（复用 `Segment`） | `value`, `onChange` |
| `RawFold` | `raw-fold.tsx` | 「原始值」折叠区（详情里看英文原文的唯一入口） | `label`, `value` |

### 2.2 逐模块：数据 → 显示字段映射

#### 2.2.1 调用统计（`calls.tsx` 重构）

**数据源**：`GET /api/v1/metrics/overview?window=&group_by=model|provider|session|bucket_start`（后端 `LedgerMetricsService`，读 `llm_billing.sqlite3`）

| 界面列（中文） | 数据字段 | 中文化处理 |
|---|---|---|
| 渠道 | `gateway_channel` | 已是中文实名；空值 → `未标注渠道` |
| 供应商 | `provider_id` | `domain-labels.channelLabel` 的词表：`axon-gemini-38-flash` → 「Axon · Gemini 3.8 Flash」 |
| 模型 | `actual_model` | `modelLabel()`：`gemini-3.8-flash` → 「Gemini 3.8 Flash」 |
| 平台 | 新增派生列 | 见 §2.2.6，需后端加 `platform` |
| 调用次数 | `recorded_calls` | 直接显示 |
| 成功 / 失败 | `status` 聚合 | `statusLabel()`：`success`→成功、`provider_failed`→供应商失败、`deadline`→超时截止 |
| 输入 Token | `prompt_tokens_value` | 千分位（3 位） |
| 缓存读取 Token | `cache_read_tokens_value` | 同上 |
| 输出 Token | `completion_tokens_value` | 同上 |
| 输入单价 | `input_cost_milli / prompt_tokens` | 派生，标注「元/百万 Token」 |
| 缓存读取单价 | `cache_read_cost_milli / cache_read_tokens` | 同上 |
| 费用 | `total_cost_micro / 1e6` | 显示 `¥7.11`，币种取 `currency` |
| 有价/无价 | `unpriced` | `unpriced=1` 时该行费用显示「未定价」而非 `0` |
| 定价来源 | `pricing_source` | `gateway_cost_items`→「网关账单明细」、`channel_spec`→「渠道价目表」、`gateway_cost`→「网关总额」 |
| 尝试次数 | `attempts_count` | `>1` 时行尾加「重试 N 次」徽章 |
| 尝试时间线 | `attempts_json` | 详情栏展开，逐次时间 + 错误类 |
| 报错摘要 | `error_summary` | 中文映射；`RawFold` 里保留原文 |
| 延迟 | `duration_ms` / `gateway_latency_ms` | 毫秒口径，表头写明 |

**筛选**：时段（24h/7d/30d）、模型（多选）、渠道（多选）、供应商（多选）、状态（成功/失败）、有无报错。现有端点支持 `window`；**模型/渠道/供应商筛选需前端在全量结果上过滤**（数据 3397 行，可全量拉取后前端筛，不必改后端）——但 `limit` 默认 10 会截断，必须先确认端点是否支持大 `limit`，否则需后端加 `limit=1000` 上限。

**折线图**：`TimeGrainSwitch` 天/周/月/年 → 直接对 `created_at` 前端分桶（3397 行足够）。每点标注：输入/输出/总 Token（有则显示）、费用合计。

#### 2.2.2 渠道健康（合并进 `latency.tsx`，改小不喧宾夺主）

**数据源**：`GET /api/v1/health` 已含 `channel_health`，或新增只读端点读 `channel_health.sqlite3`

| 界面（中文） | 字段 | 中文化 |
|---|---|---|
| 模型 | `model_id` | `modelLabel()` |
| 状态 | `state` | **`ok`→正常 / `temporarily_unavailable`→暂时不可用 / 其余→未知状态（原值）** |
| 连续失败 | `consecutive_fails` | 「连续失败 N 次」 |
| 最近延迟 | `latency_ms` / `ema_ms` | 「当前 405ms · 平滑 1386ms」 |
| 最近错误 | `last_error` | **关键词映射**：`ConnectTimeout`/`handshake operation timed out`→「连接超时」；`HTTP 404: model ... not found`→「模型不存在」；`kind=timeout`→「超时」；其余原文进 `RawFold` |
| 最近探测 / 最近成功 | `last_probe_at` / `last_ok_at` | `YYYY-MM-DD HH:mm:ss` |
| 冷却至 | `cooldown_until` | 空 → 「无冷却」 |

**「Timeout 显示异常」的正确修法**：`state='temporarily_unavailable'` 且 `last_ok_at` 在最近 N 分钟内有成功 → 显示 **「暂时不可用（最近仍成功过）」** 而不是单说 Timeout。这是「实际可调用但显示 Timeout」的根因。

**「承诺健康改小」**：把该区块从总览页移除，只留在 `/console/latency` 的折叠区（`<details>` 默认收起）。

#### 2.2.3 用户 / 会话（`sessions.tsx` 重构，对应验收 6、7）

**数据源**：`GET /api/v1/sessions`（D 席新建，读 `audit_records` 加列后的 `platform/group_id/group_title/sender_nickname`）

| 界面列（中文） | 字段 | 可得性 |
|---|---|---|
| 头像 | — | **结构性不可得** → 首字圆形占位 + 「未采集」tooltip |
| 昵称 | `sender_nickname` | 重启后有（存量 1000 行为空）→ 空则显示 `用户 <uid>` |
| 用户 ID | `user` | 明文 uid |
| 平台 | `platform` | `qq`→QQ、`telegram`→Telegram、空→「未采集」 |
| 群 / 频道 | `group_title` + `group_id` | `group_id` 可从 session 键派生；`group_title` 重启后有 |
| 群聊 / 私聊 | 派生自 `group_id` 有无 | `group_id` 空 → 「私聊」 |
| 互动次数 | 聚合 `COUNT(*)` | 直接算 |
| 最后消息时间 | `MAX(created_at)` | `YYYY-MM-DD HH:mm:ss` |
| 签名 | — | **结构性不可得** |
| 标签 | — | **需用户定义**（§0.5 第 3、4 条） |

**详情栏内容**：该用户的互动时间线（按天/半小时分桶）、每次交互的能力与结果、好感度当前档位（从 `AffinityBoardService` 取）。

**半小时分桶**：纯前端对 `created_at` 切片，无需改后端。

#### 2.2.4 记忆图谱（`memory-graph.tsx` + `three/graph-3d.tsx`，对应验收 3）

| 缺陷 | 根因（已定位） | 修法 |
|---|---|---|
| 点击困难 | `graph-3d.tsx:281-291` 直接 raycast 可见网格，无容差 | **加隐形拾取球**：每个节点加一个 `MeshBasicMaterial({visible:false})` 的球，半径 = 节点半径 × 2.5（至少 18px），只对它 raycast |
| 只显示 200 | `webui_memory_graph.py:85 _MAX_NODES_CAP = 200` | 后端加 `cursor` 分页，前端「加载更多关联」；**不调大上限**（会卡死渲染） |
| 只显示半圆 / 连接缺失 | 待复核（需读 `_assemble` 的球面投影与边生成）；`truncated=true` 时前端未提示 | ① 前端读 `truncated` 并在图上打「当前显示 N/M 个关联」；② 边生成逻辑需逐行读 `webui_memory_graph.py:405-575` 确认 |
| 无展开邻居 | 无该逻辑 | 点节点 → `GET /api/v1/memory/graph?seed=<node_id>&depth=1` 取邻居并增量并入 |
| 自转干扰点击 | `rotation.y` 持续增长 | 指针按下即暂停自转，抬起 1.5s 后恢复 |

#### 2.2.5 插件（`plugins.tsx`，对应验收 4）

| 界面 | 字段 | 中文化 |
|---|---|---|
| 组名 | 硬编码中文 | 已中文（内置功能 / 协议适配器 / 事件匹配器 / 迁移模块） |
| 插件名 | `name` | 已中文；适配器组的 `package_key` → `domain-labels` 映射表补中文名 |
| 简介 | `description` | `pyproject [tool.nonebot.adapters] 静态声明` → 「在 pyproject 中静态声明的 NoneBot 适配器」 |
| 来源 | `source` | 直接显示 |
| 热重载 | `hot_reload` | `true`→「支持热重载」、`false`→「需重启」、`null`→「未知」 |
| 参数 / 键值说明 | **缺** | 需「插件 → 配置键」映射；后端 `webui_plugins.py` 目前无此字段 |
| 可改配置 | `SETTABLE_KEYS=49` | 详情栏给「本插件可改 N 个键」+ 跳转 `/console/config?group=<插件>` |

#### 2.2.6 知识库（`knowledge.tsx`，对应验收 4）

| 界面 | 字段 | 中文化 |
|---|---|---|
| 集合名 | `collection.name` | 已是中文（23 个 meta） |
| 词条名 | `term` | 直接显示 |
| 别名 | `aliases` | 逗号分隔 |
| 定义 | `definition` | 直接显示 |
| 范围 | `scope` | 直接显示 |
| 来源 | `source` | `domain-labels` 映射 |
| 全文 | `knowledge_chunks.title`（注意：`_KB_CHUNK_COLUMNS` 只有 `chunk_id/source_id/title`，**没有正文字段**） | **结构性缺口**：正文列名未核验，A 席拒绝猜。需先 `PRAGMA table_info(knowledge_chunks)` 对生产库核对 |

#### 2.2.7 运维（`operations.tsx`，对应验收 11）

| 界面 | 现状 | 修法 |
|---|---|---|
| 动作名 | `action_id` 直出（`adapter.reconnect`） | **13 个动作逐个给中文名 + 一句话说明**（见 §3.2 词表） |
| 「一览风险与版本」无内容 | `/api/v1/actions` 读 `control_plane_actions.sqlite3`，该库**无表** | ① 后端 `ControlActionService` 首次访问时建表（幂等）；② 前端空态说清「动作目录尚未初始化，首次预览会自动建表」 |
| 配置命令状态「加载失败」 | `/api/v1/config/commands` 在宿主内无 gateway | A 席已补 `HostConfigCommandGateway`，**需重启生效** |
| 「密码未装配」 | 令牌缺失时的文案 | 改为「未配置访问令牌 → 点此设置」并直开设置面板 |
| 资源模块 | 待重构 | 见 §2.2.8 |

#### 2.2.8 资源（`/console/resources` → 需确认是否存在对应页）

前端 `pages/` 无 `resources.tsx`；`CONSOLE_PAGES` 登记了 `/resources` 但 `router.tsx` 需核对。后端 `api/v1.py:62` 有 `ResourceMetricsService(runtime_attached=...)`，`/api/v1/metrics/resources` 端点存在。**需先确认前端是否有页**，无则本波新建。

---

## §3 中文化映射方案

### 3.1 六类英文来源 → 处理策略

| # | 来源 | 典型样本 | 策略 |
|---|---|---|---|
| 1 | 配置键 | `bot_llm_aiprc_enabled` | `lib/humanize.ts` **已覆盖 415→74**，本波只补剩余 N2 专名 |
| 2 | 动作 ID | `adapter.reconnect` | 新增 13 条映射表（§3.2） |
| 3 | 渠道 / 供应商 / 模型标识 | `axon-gemini-38-flash`、`gemini-3.8-flash` | 新增前缀规则 + 已知表（§3.3） |
| 4 | 状态枚举 | `temporarily_unavailable`、`provider_failed`、`deadline` | 新增映射表（§3.4） |
| 5 | 错误原文 | `ConnectTimeout: _ssl.c:993: The handshake operation timed out` | 关键词匹配 → 中文类目；原文进 `RawFold`（§3.5） |
| 6 | 日志正文 | `runtime_log_events` 10000 行原文 | **不逐行翻译**（那是数据不是界面）；只在列表列头与筛选器用中文，正文保留原文并在标题标「原始日志」 |

### 3.2 动作 ID → 中文（13 条，逐条给 title + hint）

```ts
// webui/src/lib/domain-labels.ts
const ACTIONS: Record<string, { title: string; hint: string }> = {
  'runtime.reload':        { title: '重新加载运行时',   hint: '重读配置与插件模块，不断开连接' },
  'runtime.safe_restart':  { title: '安全重启',         hint: '先停收新消息、等队列排空再重启进程' },
  'adapter.reconnect':     { title: '重连协议适配器',   hint: '断开后重新连接 QQ / Telegram 适配器' },
  'snowluma.status':       { title: '查看 SnowLuma 状态', hint: '读取 QQ 框架连接与登录状态' },
  'queue.pause':           { title: '暂停发送队列',     hint: '停止投递新消息，已在途的不受影响' },
  'queue.resume':          { title: '恢复发送队列',     hint: '继续投递暂停期间积压的消息' },
  'queue.drain':           { title: '清空发送队列',     hint: '丢弃全部待发消息，不可撤销' },
  'logging.level':         { title: '调整日志级别',     hint: '改变运行日志的详细程度' },
  'resources.refresh':     { title: '刷新资源指标',     hint: '重新采集 CPU / 内存 / 磁盘读数' },
  'llm.routes.reload':     { title: '重载模型路由',     hint: '重新读取模型优先组与渠道表' },
  'knowledge.reindex':     { title: '重建知识库索引',   hint: '重新嵌入全部词条，耗时较长' },
  'memory.maintenance':    { title: '记忆库维护',       hint: '清理过期记忆与孤立索引' },
  'diagnostics.snapshot':  { title: '生成诊断快照',     hint: '打包当前运行状态供排查' },
};

export function actionLabel(id: string) {
  return ACTIONS[id] ?? { title: `未登记动作（${id}）`, hint: '该动作未在界面词表中登记，请联系维护者补充说明' };
}
```

### 3.3 渠道 / 供应商 / 模型

**原则：优先用数据里已有的中文 `gateway_channel`，不自己造。**

```ts
// 渠道：数据已有中文名，只处理空值
export function channelLabel(gatewayChannel: string, providerId: string): string {
  if (gatewayChannel.trim()) return gatewayChannel;              // 「恒星纪元 - Gemini」
  if (providerId.trim()) return `未标注渠道（供应商：${providerLabel(providerId)}）`;
  return '未标注渠道';
}

// 供应商：前缀规则 + 已知表
const PROVIDER_PREFIX: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^axon-(.+)$/,      (m) => `Axon · ${titleize(m[1])}`],       // axon-gemini-38-flash → Axon · Gemini 38 Flash
  [/^ollama-(.+?)-direct$/, (m) => `本地 Ollama · ${titleize(m[1])}`],
  [/^potccv-(.+)$/,    (m) => `Potccv · ${titleize(m[1])}`],
];

// 模型：直接 titleize，保留版本号
export function modelLabel(actualModel: string, modelId: string): string {
  const raw = actualModel.trim() || modelId.trim();
  if (!raw) return '未记录模型';
  return titleize(raw)   // gemini-3.8-flash → Gemini 3.8 Flash
    .replace(/\bQwen(\d)/, 'Qwen $1');
}
```

### 3.4 状态枚举

```ts
// llm_call_records.status
const CALL_STATUS: Record<string, string> = {
  success: '成功',
  provider_failed: '供应商失败',
  deadline: '超时截止',
};

// channel_health.state
const CHANNEL_STATE: Record<string, string> = {
  ok: '正常',
  temporarily_unavailable: '暂时不可用',
  unavailable: '不可用',
  degraded: '降级',
};

// audit_records.severity（日志页）
const SEVERITY: Record<string, string> = {
  info: '提示', warning: '警告', error: '错误', critical: '严重',
};

export function statusLabel(raw: string): string {
  const key = raw.trim().toLowerCase();
  return CALL_STATUS[key] ?? CHANNEL_STATE[key] ?? SEVERITY[key] ?? `未知状态（${raw || '空'}）`;
}
```

### 3.5 错误原文 → 中文类目（关键词匹配，原文保留在 `RawFold`）

```ts
const ERROR_RULES: Array<[RegExp, string]> = [
  [/timed? ?out|timeout|ConnectTimeout|handshake operation timed out/i, '连接超时'],
  [/HTTP 404|not found/i,                    '资源不存在'],
  [/HTTP 40[13]|unauthori[sz]ed|forbidden/i, '鉴权失败'],
  [/HTTP 429|rate.?limit/i,                  '被限速'],
  [/HTTP 5\d\d|internal server/i,            '服务端错误'],
  [/ConnectError|Connection refused|ECONNREFUSED/i, '连不上服务'],
  [/empty.?response|no content/i,            '模型返回空内容'],
  [/bad.?request|invalid.?request/i,         '请求参数不合法'],
];

export function errorKindLabel(kind: string, summary = '') {
  const text = `${kind} ${summary}`;
  for (const [re, label] of ERROR_RULES) {
    if (re.test(text)) return { label, severity: 'bad' as const };
  }
  if (!text.trim()) return { label: '无错误', severity: 'good' as const };
  return { label: `未归类错误（${kind || '未知'}）`, severity: 'warn' as const };
}
```

### 3.6 兜底铁律（写成测试锁死）

```
凡 statusLabel / actionLabel / channelLabel / modelLabel / errorKindLabel 的返回值，
首字符必须是中文或全角标点；否则测试红。
```

这条用一个正则断言落到 `domain-labels.test.ts`，覆盖全部已知枚举 + 20 个随机畸形输入。

---

## §4 分阶段实施计划（P0 / P1 / P2）

### P0 —— 阻断与"看起来坏了"（必须第一批，任何一条不修则整波不算完成）

| 任务 | 内容 | 依赖 | 预估 |
|---|---|---|---|
| **T1** | 重启 bot 使后端改动生效（`_app.py`/`v1.py`/`config_service.py`/`webui_stats.py` 全部晚于 18:45:20 进程启动） | 用户点头 | 10 分钟 + 60 秒观察 |
| **T2** | 新建 `lib/domain-labels.ts` + 测试（五函数 + 兜底铁律） | 无 | 1 席 × 1 轮 |
| **T3** | `operations.tsx` 用 `actionLabel()` 替换裸 ID；空态说清"未初始化" | T2 | 1 席 |
| **T4** | `channel` 健康区块：`state` 中文化 + `last_error` 关键词映射 + `last_ok_at` 近况提示 | T2 | 1 席 |
| **T5** | `calls.tsx` 重构：表列中文化 + 筛选条 + 详情栏 + 折线图粒度切换 | T2, T6(壳) | 2 席 |
| **T6** | `ThreePane` + `MasterList` + `DetailPane` + `FilterBar` 壳 | 无 | 2 席 |
| **T7** | `sessions.tsx` 重构：完整列 + 详情栏 + 半小时分桶 + 缺字段如实标注 | T2, T6 | 1 席 |
| **T8** | 记忆图谱拾取球 + 自转暂停 + `truncated` 提示 + 加载更多 | 后端分页 | 2 席 |
| **T9** | 令牌链路：`auth.py` 判定顺序（冷却期内正确令牌应放行）+ 前端文案说清"填明文不是哈希" | 需用户裁 | 1 席 |
| **T10** | `plugins.tsx` / `knowledge.tsx` 详情展开 + 描述中文化 | T2, T6 | 1 席 |
| **T11** | 不变量测试：全站 grep 裸英文断言（除 `RawFold` 内） | T2..T10 | 1 席 |

### P1 —— 视觉与结构完备

| 任务 | 内容 |
|---|---|
| **T12** | `index.css` 视觉参数段：四件套统一加辉光阴影（`--glass-glow` token）+ 间距残留清扫（`gap-3`/`gap-6`） |
| **T13** | 三栏布局在全部 17 页接线（逐页判断主从是否有意义，无意义的页保持单栏并在报告说明） |
| **T14** | 总览页重排：把「通道健康」移出、6 卡改 3×2 等高、趋势图占满一行 |

### P2 —— 结构性缺口（需用户决策后另开波）

| 任务 | 前置 |
|---|---|
| **T15** | 涨粉：`member_snapshots` 表 + 每日采集任务 | 用户定义「涨粉」口径 |
| **T16** | 头像/签名/标签：`get_stranger_info` 缓存表 + 限速 | 用户定采集范围 |
| **T17** | 知识库词条全文：先 `PRAGMA table_info(knowledge_chunks)` 核列名 | 用户确认"文档"指什么 |
| **T18** | 插件→配置键映射 | 需后端加字段 |
| **T19** | 平台维度入账本（Qt/TG 分列） | 需 `platform` 列落库（D 席已加，待重启验证） |

---

## §5 具体改动清单与关键代码

### 5.1 新增文件

```
webui/src/lib/domain-labels.ts               ← T2（约 220 行）
webui/src/lib/domain-labels.test.ts          ← T2（约 120 行，60+ 断言）
webui/src/components/console/three-pane.tsx  ← T6
webui/src/components/console/master-list.tsx ← T6
webui/src/components/console/detail-pane.tsx ← T6
webui/src/components/console/filter-bar.tsx  ← T6
webui/src/components/console/stat-grid.tsx   ← T6
webui/src/components/console/time-grain-switch.tsx ← T6
webui/src/components/console/raw-fold.tsx    ← T6
webui/src/lib/time-bucket.ts                 ← T7（半小时/天/周/月/年分桶纯函数）
webui/src/lib/time-bucket.test.ts            ← T7
webui/src/lib/graph-picking.ts               ← T8（拾取半径纯函数）
webui/src/lib/graph-picking.test.ts          ← T8
```

### 5.2 关键伪代码

#### 5.2.1 `ThreePane`（T6）

```tsx
export function ThreePane({ nav, main, detail, detailTitle, onCloseDetail }: ThreePaneProps) {
  return (
    <div className='grid min-w-0 grid-cols-1 gap-4
                    md:grid-cols-[minmax(180px,1fr)_minmax(0,3fr)]
                    2xl:grid-cols-[minmax(180px,1fr)_minmax(0,3fr)_minmax(240px,1fr)]'>
      <nav aria-label='一级板块' className='surface hidden flex-col gap-1 rounded-lg p-2 md:flex'>{nav}</nav>
      <main className='flex min-w-0 flex-col gap-4'>{main}</main>
      {/* >=2xl 常驻；<2xl 用 Sheet 由页面自己控制 */}
      <aside aria-label='详情' className='surface sticky top-20 hidden max-h-[calc(100dvh-96px)] overflow-y-auto rounded-lg p-4 2xl:block'>
        {detailTitle && <h2 className='mb-2 fs-card'>{detailTitle}</h2>}
        {detail}
        {onCloseDetail && <Button variant='ghost' size='sm' onClick={onCloseDetail}>关闭详情</Button>}
      </aside>
    </div>
  );
}
```

#### 5.2.2 `MasterList` 行选中（T6）

```tsx
export function MasterList<T>({ rows, selectedKey, onSelect, renderRow, keyOf }: MasterListProps<T>) {
  return (
    <ul role='listbox' aria-label='条目列表' className='surface divide-y rounded-lg'>
      {rows.map((row) => {
        const key = keyOf(row);
        const active = key === selectedKey;
        return (
          <li key={key} role='option' aria-selected={active}>
            <button
              type='button'
              onClick={() => onSelect(key)}
              className={cn(
                'flex w-full items-center gap-3 border-l-2 px-4 py-3 text-left transition-colors',
                'hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                active ? 'border-l-primary bg-accent/60' : 'border-l-transparent'
              )}
            >
              {renderRow(row)}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
```

#### 5.2.3 记忆图谱拾取球（T8）

```ts
// graph-picking.ts —— 纯函数，可测
export const PICK_RADIUS_FACTOR = 2.5;
export const PICK_RADIUS_MIN_PX = 18;

/** 给定节点视觉半径与相机距离，返回拾取球半径（世界单位）。 */
export function pickRadius(visualRadius: number): number {
  return Math.max(visualRadius * PICK_RADIUS_FACTOR, PICK_RADIUS_MIN_PX / 2);
}
```

```ts
// graph-3d.tsx 内：为每个节点加隐形拾取球，只对它 raycast
const picker = new Mesh(
  new SphereGeometry(pickRadius(node.radius), 10, 10),
  new MeshBasicMaterial({ visible: false })
);
picker.userData = { nodeId: node.id };
pickTargets.push(picker);   // pickTargets 只放 picker，不放可见网格

// 自转：指针按下即暂停
const onPointerDown = (e) => { spinPaused = true; /* … */ };
const endPointer   = (e) => { setTimeout(() => { spinPaused = false; }, 1500); /* … */ };
```

#### 5.2.4 半小时/多粒度分桶（T7）

```ts
// time-bucket.ts —— 纯函数
export type Grain = 'half_hour' | 'day' | 'week' | 'month' | 'year';

export function bucketKey(iso: string, grain: Grain): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'unknown';
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  switch (grain) {
    case 'half_hour': {
      const h = String(d.getHours()).padStart(2, '0');
      const half = d.getMinutes() < 30 ? '00' : '30';
      return `${y}-${m}-${day} ${h}:${half}`;
    }
    case 'day':   return `${y}-${m}-${day}`;
    case 'week':  { const w = isoWeek(d); return `${y}-W${String(w).padStart(2,'0')}`; }
    case 'month': return `${y}-${m}`;
    case 'year':  return `${y}`;
  }
}

export function countsByBucket(isos: string[], grain: Grain): Array<{ key: string; count: number }> {
  const map = new Map<string, number>();
  for (const iso of isos) map.set(bucketKey(iso, grain), (map.get(bucketKey(iso, grain)) ?? 0) + 1);
  // 空桶补零由调用方给轴；本函数只保证「有数据的桶按 key 升序」
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, count]) => ({ key, count }));
}
```

### 5.3 改动文件清单（按任务）

| 任务 | 改 | 新增 |
|---|---|---|
| T2 | — | `lib/domain-labels.ts` + `.test.ts` |
| T3 | `pages/operations.tsx` | — |
| T4 | `pages/latency.tsx`（或新建 `channel-health` 区块组件） | `components/console/channel-health-card.tsx` |
| T5 | `pages/calls.tsx` | `components/console/attempt-timeline.tsx` |
| T6 | `components/layout/app-shell.tsx`（三栏壳接线） | 7 个 `console/*` 组件 |
| T7 | `pages/sessions.tsx` | `lib/time-bucket.ts` + `.test.ts` |
| T8 | `components/three/graph-3d.tsx`、`pages/memory-graph.tsx`、`control_plane/webui_memory_graph.py`（加 cursor） | `lib/graph-picking.ts` + `.test.ts` |
| T9 | `control_plane/_app.py`（三处依赖的判定顺序）、`components/settings/settings-dialog.tsx`（文案） | — |
| T10 | `pages/plugins.tsx`、`pages/knowledge.tsx` | — |
| T11 | — | `lib/no-raw-english.test.ts`（静态扫描） |
| T12 | `index.css`（视觉参数段） | — |
| T13 | 17 个 page 逐一接 `ThreePane` | — |
| T14 | `pages/dashboard.tsx` | — |

### 5.4 不动清单（硬约束）

- `webui/scripts/layout-constitution.mjs`（门禁本体）
- `plugins/bot_unified_runtime/config.py`（双向漂移风险）
- `control_plane/auth.py` 的限流常量（`FAILURE_WINDOW_SECONDS=60.0` / `FAILURE_MAX_COUNT=5`）
- `webui/src/components/ui/*` 的 `/ui/` import 路径（27 处不变量）
- `_app.py` 路由顺序：`mount_webui_assets` 必须仍在 `include_router(build_ui_router)` 之前

---

## §6 验收测试清单

### 6.1 机器门（每席收工必跑，`cmd; echo rc=$?` 独立语句，禁管道）

```
node scripts/layout-constitution.mjs ; echo rc=$?
npx tsc --noEmit                     ; echo rc=$?
node --test src/lib/*.test.ts        ; echo rc=$?
npm run build                        ; echo rc=$?
```

后端（动过 Python 的席）：

```
PYTHONDONTWRITEBYTECODE=1 <venv>/python.exe -m pytest <目标测试> -p no:cacheprovider --basetemp=<仓外预建目录> ; echo rc=$?
```

### 6.2 新增不变量测试（T11）

| 测试 | 断言 |
|---|---|
| `domain-labels.test.ts` | 五函数 × 全部已知枚举 + 20 个畸形输入；返回值首字符必为中文 |
| `no-raw-english.test.ts` | 扫 `pages/*.tsx` 与 `components/console/*.tsx`，除 `<RawFold>` 内容外**不得**出现 `[a-z]+_[a-z]+`、`[a-z]+\.[a-z]+` 形态的裸标识符字面量 |
| `time-bucket.test.ts` | 五档粒度、空输入、跨年、跨月、跨周、DST 邻域、非法 ISO |
| `graph-picking.test.ts` | 拾取半径恒 ≥ 18px；节点半径 0/负/NaN 不产 NaN |
| `three-pane.test.ts` | 三栏 class 串含三段栅格；窄屏断点类存在 |

### 6.3 人工验收（用户十一条逐条）

| # | 验收动作 | 期望 |
|---|---|---|
| 1 | 打开全部 17 页，肉眼扫 | 无裸露英文标识符（除「原始日志」「原始值」折叠区） |
| 2 | 任取三页截图对比间距 | 间距一致、边框可见但轻、卡片有辉光、层级分明 |
| 3 | 记忆图谱点 10 个节点 | 每次都能选中；「加载更多」能取到超 200 的邻居 |
| 4 | 插件页点展开 → 看简介/参数；知识库点词条 → 看全文 | 都有内容，无空白 |
| 5 | 1440 宽看三栏；768 看两栏；390 看单栏+抽屉 | 无横向溢出，右详情在窄屏可由点击唤出 |
| 6 | 会话页看一行 | 有昵称/ID/平台/群/私聊/互动次数/`YYYY-MM-DD HH:mm:ss`；无头像处显示首字占位而非破图 |
| 7 | 会话详情切「半小时 / 天 / 周 / 月 / 年」 | 桶数与时间跨度自洽；涨粉显示「未采集」并给采集入口 |
| 8 | 调用页看列 | 渠道显示「恒星纪元 - Gemini」；模型显示「Gemini 3.8 Flash」；渠道/供应商/模型三列分开；可筛选；列宽够；有报错与尝试时间 |
| 9 | 调用页切粒度 | 图随粒度变化；点有输入 Token 的点显示输入/输出/总 Token；费用显示 `¥x.xx` |
| 10 | 设置里填明文令牌 → 保存 → 刷新 | 控制台可打开；填错令牌时有明确中文提示「令牌无效」而非「加载失败」 |
| 11 | 运维页 | 13 个动作都有中文名+说明；无 `adapter.reconnect` 裸 ID；「预览风险与版本」能出内容或明确说「未初始化」；无「加载失败」「密码未装配」 |

### 6.4 回归红线（不许退）

| 项 | 基线 |
|---|---|
| `layout-constitution` 自测 | 196/196 |
| `src/lib/*.test.ts` | ≥ 359 pass / 0 fail |
| `src/components/appearance/*.test.ts` | 8 pass |
| 外观页 `docH` | 1440 ≤ 4500 / 390 ≤ 6000 |
| 429 不重试 | `shouldRetryQuery({status:429}, 0) === false` |
| 503 不重试 | `shouldRetryQuery({status:503}, 0) === false` |
| 无令牌首屏骨架 | 0 根 |

---

## §7 执行方式建议

**推荐 Subagent-driven**：任务之间接口耦合强（T6 组件壳被 T5/T7/T10 同时依赖），但每个任务有独立可测交付物，适合「一个实现席 + 一个复核席」的成对推进。参考成本：P0 共 11 个任务，约 14 席次。

**关键顺序**：T1（重启）→ T2（词表）→ T6（壳）→ 其余并行。T1 必须最先，否则 T3/T4/T9 的后端依赖无法验证。

**并发上限**：本会话子代理硬上限 8 席。建议同时最多 6 席（留 2 席给复核）。
