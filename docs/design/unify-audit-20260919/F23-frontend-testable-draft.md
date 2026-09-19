# F23 · 前端可测性改造成品稿（纯函数 + node --test + 门棘轮）

> **快照声明**：`date` 实跑 = `Sat Sep 19 17:05:18 2026`；`node -v` 实跑 = `v26.7.0`（`C:\Software\nodejs\node.exe`）。
> 本席性质：**只读取证 + 可照抄成品稿**，工作树零修改（除本文件）。所有拟稿代码在 `%TEMP%/f23/`（= `C:\Users\LancyCelestia\AppData\Local\Temp\f23`）镜像 `src/lib` + `src/locales` 目录层级后**真跑过**，未向仓库拷贝任何一份。
> 基线对照实跑（只读，本席执行）：`node scripts/layout-constitution.mjs`（cwd=`webui/`）→ `版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）`，`exit=0`。
> 稿件基准 = 主会话最新态：`dashboard.tsx`（无 `?? 0`、`value={botData ? … : undefined}`、`fallbackLine`、`blocking` 相位等值判定）、`patterns.tsx`、`logs.tsx`、`ui/card.tsx`、`router.tsx`、**新件 `components/layout/error-boundary.tsx`**、`settings-dialog.tsx`、`tokens.tsx` 逐行读过后撰写（见 §二 的兼容性论证，其中 error-boundary.tsx:24 直接构造 error 相位，是本稿把新字段定为**可选**的决定性理由）。

---

## 〇、一句话总裁决

F9 点名的三族分叉，根因是**中央 error 相位把 `ApiError` 已有的 `status`/`code` 压成了字符串**；本稿给出让判定重新结构化的最小改动（2 行）+ 四个可直接落盘的纯函数模块与 37 个已在 `%TEMP%` 跑绿的用例，并给出与 F18 那条常驻门的**衔接与冲突预警**（一处现有断言会因本稿红，必须同批放宽）。

**本席新发现（比 F9 更重一档，铁证见 §一.1）**：三份 `isNotFound` 的正则**在今天的生产链路上就已经永不命中**——控制面把 404 包成 `{error:{code:"not_found",message:"请求的资源或操作不可用。"}}`，`api-client.ts:183-185` 用该 message 覆盖了 `HTTP 404:` 状态行，于是三页的「未部署」卡是**不可达代码**。这是已遂缺陷，不是未来风险。

---

## 一、现状取证：同一语义几套真值（坐标 + 摘录）

### 1.1 族一「404 → 未部署」判定：3 份同体正则

| # | 坐标 | 代码（逐字） | 判什么 | 调用点 |
|---|---|---|---|---|
| 1 | `webui/src/pages/knowledge.tsx:28-30` | `function isNotFound(message: string): boolean { return /HTTP 404/.test(message); }` | error 相位的**展示文案**里是否含 `HTTP 404` | `:153`（collections）、`:242`（terms） |
| 2 | `webui/src/pages/plugins.tsx:19-21` | 同上（逐字相同） | 同 | `:171` |
| 3 | `webui/src/pages/memory-graph.tsx:34-36` | 同上（逐字相同） | 同 | `:154` |

三处渲染形态也各异（同一语义三种壳）：knowledge 页 error 分支里三元式内联（`:153`）、memory-graph 在主体状态块内联（`:154`）、plugins 在长链三元式中段（`:171`）。

**中央断点**（根因，坐标精确）：
- `webui/src/lib/api-client.ts:129-146` — `ApiError` **本来就带** `status: number` 与 `code` getter（从 `response.error.code` 取）。
- `webui/src/hooks/use-semantic-query.ts:49` — `return { state: { phase: 'error', message: error.message }, … }`：**只有 message**，status/code 在此被丢弃。
- `webui/src/lib/api-client.ts:176-191` — 非 2xx 时先置 `HTTP ${status}: ${statusText}`，若错误体是 `ErrorResponseBody` 则**被 `errorData.message` / `errorData.error.message` 覆盖**。

**生产侧铁证（正则已死，非假设）**：
- `plugins/bot_unified_runtime/control_plane/_app.py:660-667`：`@app.exception_handler(HTTPException)` → `code = {404: "not_found", …}` → `error_response(request, 404, "not_found", "请求的资源或操作不可用。")`。
- `_app.py:635-642`：路径以 `/api/v1/` 开头时包成 `envelope(None, error=…)` → 体即 `{"data": null, "error": {"code": "not_found", "message": "请求的资源或操作不可用。", …}, "meta": {…}}`。
- 带外同款：`scripts/webui_mock_server.py:139-156`（`error_payload`）与 `:1382`/`:1516`（`_send_error_cp(404, "not_found", "请求的资源或操作不可用。")`）。
- 链上推演：`isErrorResponseBody` 通过 → `errorData.message` 缺席 → `errorMessage = errorData.error.message` = 「请求的资源或操作不可用。」 → `/HTTP 404/.test(…) === false`。
- 三页端点全在 `/api/v1/` 前缀下（`api-client.ts:467,474,477`），**无一例外**。

**对照表（族一）**：语义「端点未部署」 = **4 套真值**（3 份正则 + 1 处中央丢弃）。今日实际结果 = **0 处能判对**。

### 1.2 族二 reason → 人话：4 套实现（含 1 处绕行）

| # | 坐标 | 形态 | 是否过白名单 | 措辞外壳 |
|---|---|---|---|---|
| 1 | `components/semantic/semantic-state.tsx:16-39` `reasonKey(reason)` | 18 码数组 → `reason.<code>`，未命中返回 `''` | ✅ 唯一白名单点 | 消费处 `:95` `{key ? t(key) : state.reason}`（无前缀，独立一行） |
| 2 | `pages/dashboard.tsx:33-44` `fallbackLine` | 再调 `reasonKey` + 自己 `t(key)` + 与 key 比较回退 | ✅（借用 1） | `暂无数据：X`（`${t('state.noData')}：${…}`），error 相位另拼 `加载失败：message` |
| 3 | `pages/plugins.tsx:24-29` `reasonText` | **绕过白名单**，直查 `t('reason.'+reason)` | ❌ 绕行 | `：X`（前导冒号，跟在 `plugins.unavailable` 之后） |
| 4 | `locales/{zh-CN,en}/common.json` 的 `reason.*`（各 18 键，zh `:51-70`） | 文案本体 | — | 第三种镜像 |

同一 reason 码在三处渲染出三种句子（「数据表不存在…」／「暂无数据：数据表不存在…」／「该组清单暂不可用：missing_table」）。
绕行处的实际后果有限但方向错误：`plugins.tsx` 的组级码（`domains_dir_unavailable`/`cross_process_introspection_unavailable`/`disabled_by_config`/`features_store_unavailable`/`static_config_unavailable`）恰好都在白名单里（PAGES2 时补进去的），所以今天**侥幸等价**；一旦有人删白名单某项或加新码只改 locale，两套口径立刻分叉——本稿的 `reason.test.ts` 用「白名单 == zh 键集 == en 键集」三向对账把这件事变成机器红。

后端 reason 产出面（本席实跑 grep 取证，用于「前端白名单 ⊇ 后端产出」的判据）：`_failure(…)` 第二参数字面量集合 = `audit_source_not_configured, affinity_source_not_configured, missing_source, missing_table, incomplete_schema, query_budget_exceeded, read_failed, not_connected, all_sources_missing, collection_not_available`（+ `invalid_*` 系属 422 不走 reason）；另有 `webui_knowledge.py:133` `glossary_source_unavailable`、`:160` `disabled_by_config`、`webui_plugins.py:221/275/331/351/360` `features_store_unavailable`/`static_config_unavailable`/`cross_process_introspection_unavailable`/`domains_dir_unavailable`、`webui_memory_graph.py`（`unreadable` ×8 处）、`webui_stats.py:336` `not_persisted` —— **18/18 全部可溯源，白名单不掺水**。

**对照表（族二）**：语义「reason 码 → 人话」 = **4 套实现**（1 白名单 + 1 借用 + 1 绕行 + 1 文案镜像）。

### 1.3 族三：窗口切换器 3 形态 + 空态文案 4 形态

**窗口（3 形态 + 1 个名实问题）**

| # | 坐标 | DOM 形态 | 枚举源 | 标签命名空间 | 标签值（zh） |
|---|---|---|---|---|---|
| 1 | `pages/calls.tsx:23` + `:25-44` `WindowSwitch` | `div.flex.gap-1.rounded-lg.border.p-1` + `bg-primary` 选中 | 本地 `const WINDOWS: StatsWindow[] = ['24h','7d','30d']` | `calls.window.*` | 「24 小时」「7 天」「30 天」 |
| 2 | `pages/tokens.tsx:23` + `:91-106` | 同款按钮组但 className **手抄第二份**（选中态写三元串，不是 `cn()`） | 又一个本地 `WINDOWS` | **借用 `calls.window.*`**（跨命名空间，`tokens.tsx:103`） | 同 1 |
| 3 | `pages/memory-graph.tsx:24` + `:113-120` | `CategoryChip` 圆片（`tone` 分支），四档含 `all` | 第三个本地 `WINDOWS: GraphWindow[]` | `memoryGraph.window.*`（**第四真值**） | 「近 24 小时」「近 7 天」「近 30 天」「全部时间」 |
| 4 | `pages/dashboard.tsx:222-223` + `locales :91-92` | 无切换器（两窗并排展示） | 硬写两串 | `dashboard.overview.windowToday` / `window7d` | **「今日（24 小时）」**、「近 7 天」 |

名实问题**已有后端铁证**：`control_plane/metrics.py:89` `_WINDOW_SECONDS = {"24h": 86_400, …}` 与 `:296-300` `now - timedelta(seconds=_WINDOW_SECONDS[window])` —— 24h 是**从此刻回溯的滚动窗**，与自然日无关；界面写「今日」即名实不符（本稿把它做成可测语义 + 待裁文案项，见 §三.4、§六）。

**空态（4 形态，同一「空」四种话术）**

| # | 坐标 | 渲染 | 语义 |
|---|---|---|---|
| A | `pages/calls.tsx:65` `{entries.length === 0 && <p …>—</p>}` | **裸破折号** | ❌ 把「空列表」说成「值未知」（P1，F9-P1-3） |
| B | `pages/calls.tsx:157`、`tokens.tsx:135/206`、`latency.tsx:73`、`affinity.tsx:97`、`components/semantic/semantic-state.tsx:94` | `t('state.noData')` = 「暂无数据」 | ✅ 正确形态（6 处手写 className 抄本） |
| C | `pages/memory-graph.tsx:164-166`（`memoryGraph.empty`+`emptyHint`）、`knowledge.tsx:251-269`（`emptySearch`/`emptyCollection`）、`plugins.tsx:133`（`plugins.emptyGroup`=「暂无条目」） | 专用 `SectionCard` | ✅ 域内文案（第三种措辞） |
| D | `pages/calls.tsx:199` `labelFor={(key) => key ?? '—'}`、`latency.tsx:25` `{item.channel \|\| '—'}`、`tokens.tsx:61/190`、`dashboard.tsx:70/74`、`logs.tsx:292`、`lib/format.ts:4/9/15/27/34` | `'—'` 字面量 **×11**（含 format.ts 内 5 处 return） | ✅ 用作「值未知」，但**无单一常量**（改符号要动 11 处） |

**对照表（族三）**：「时间窗」= 3 份枚举 + 4 套标签真值；「空」= 4 形态；「未知」= 1 符号 11 处字面量。

---

## 二、ApiError 契约修复：最小改动（2 行，0 个调用点必须改）

### 2.1 裁决：加**可选标量字段**，不加 `ApiError` 本体

| 方案 | 结论 | 理由 |
|---|---|---|
| A：`{phase:'error'; message; status?: number; code?: string \| null}` | ✅ **采用** | 可选 → 既有字面构造点零改动；标量 → `classifyError` 保持零依赖（§五探针证明「import 带参数属性的 api-client 直接 SyntaxError」）；状态可序列化，利于将来日志/快照 |
| B：`{phase:'error'; message; error?: ApiError}` | ❌ 否决 | 相位被类实例污染；页面必须 `instanceof`（把正则补丁换成 instanceof 补丁，语义没前进）；测试链必须加载 `api-client.ts`（本机 Node 26 下不可加载，见 §五） |

### 2.2 before → after（`webui/src/hooks/use-semantic-query.ts`）

**类型（`:8-14`）**

```ts
// before
export type DataState<T> =
  | { phase: 'loading' }
  | { phase: 'unavailable'; reason: string; source?: string }
  | { phase: 'not_provisioned' }
  | { phase: 'auth' }
  | { phase: 'error'; message: string }
  | { phase: 'ok'; data: T; source?: string };
```
```ts
// after（只动 1 行；三处注释保持）
export type DataState<T> =
  | { phase: 'loading' }
  | { phase: 'unavailable'; reason: string; source?: string }
  | { phase: 'not_provisioned' }
  | { phase: 'auth' }
  | { phase: 'error'; message: string; status?: number; code?: string | null }
  | { phase: 'ok'; data: T; source?: string };
```

**构造点（`:40-52`）**

```ts
// before
  if (query.isError) {
    const error = query.error;
    if (error instanceof ApiError) {
      if (error.status === 503 && error.code === 'control_plane_not_provisioned') {
        return { state: { phase: 'not_provisioned' }, refetch: () => void query.refetch() };
      }
      if (error.status === 401 || error.status === 403) {
        return { state: { phase: 'auth' }, refetch: () => void query.refetch() };
      }
      return { state: { phase: 'error', message: error.message }, refetch: () => void query.refetch() };
    }
    return { state: { phase: 'error', message: String(error) }, refetch: () => void query.refetch() };
  }
```
```ts
// after（只动 1 行：透传 status/code；503 码判定与 401/403 判定本就该由单源谓词承担，
// 但为把「零行为变化」守住，本稿**不**在这里重构那两个分支——留作步骤⑤可选收敛）
  if (query.isError) {
    const error = query.error;
    if (error instanceof ApiError) {
      if (error.status === 503 && error.code === 'control_plane_not_provisioned') {
        return { state: { phase: 'not_provisioned' }, refetch: () => void query.refetch() };
      }
      if (error.status === 401 || error.status === 403) {
        return { state: { phase: 'auth' }, refetch: () => void query.refetch() };
      }
      return {
        state: { phase: 'error', message: error.message, status: error.status, code: error.code },
        refetch: () => void query.refetch(),
      };
    }
    // 非 ApiError（抛出的字符串/TypeError）：无结构化信号，classifyError 自然判 unknown——诚实不猜。
    return { state: { phase: 'error', message: String(error) }, refetch: () => void query.refetch() };
  }
```

### 2.3 牵动点全清单（实测枚举，非估）

`useSemanticQuery` 调用点共 **16 处 / 10 文件**（app-shell 1、affinity 1、calls 1、dashboard 6、knowledge 2、latency 1、logs 1、memory-graph 1、plugins 1、tokens 1）。

| 类别 | 坐标 | 是否必须改 |
|---|---|---|
| 中央类型 + 构造 | `use-semantic-query.ts:13, :49` | 改（本稿 2 处） |
| 直接字面构造 error 相位 | `components/layout/error-boundary.tsx:24` | **不改**（字段可选，`{phase:'error', message}` 依旧合法；这正是选可选的代价收益比） |
| 读 `state.message` 的渲染面 | `semantic-state.tsx:107`、`dashboard.tsx:42` | 不改（文案照常透出；**可选增强**：`fallbackLine` 末尾追 `(${status})` 诊断串——属文案面，另批裁） |
| 相位等值判定 | `dashboard.tsx:102-104`（`blocking`）、`knowledge.tsx:164` | 不改；`blocking` 的语义来源（`not_provisioned`/`auth`）由中央分支产出，与本稿正交 |
| 三页降级判定 | `knowledge.tsx:28-30/153/242`、`plugins.tsx:19-21/171`、`memory-graph.tsx:34-36/154` | **必须同批改**（否则「一边结构判定一边字符串判定」并存，且**新逻辑永远不被执行**） |
| `unavailable`/`ok`/`loading` 消费 | 其余全部 | 零影响 |

净数：**5 个文件、约 12 处编辑、0 个取数调用点签名变更**。

### 2.4 收益（具体到渲染路径）

- 三页「未部署」卡从**不可达**恢复可达（§一.1 的 404 信封场景）。
- `dashboard.fallbackLine` 的 error 分支以后可按 `classifyError` 分流（未就绪 vs 真失败），不再只有 `加载失败：X` 一种口径。
- 后端改文案（`_app.py:666` 那句人话）不再有任何前端判定风险——**文案与判定解耦**，由 `not-found.test.ts` 第 10 例（`message` 写着 `HTTP 404` 但 status=200 → `unknown`）机器锁死。

---

## 三、纯函数成品稿（4 × `.ts` + 4 × `.test.ts`，全文可照抄）

落点：`webui/src/lib/`。四个模块**零 import**（只被测试引用 `node:test`/`node:assert`/`node:fs`），故满足 §五 的 strip-only 约束。
`graph-layout.test.ts:3` 的既有范式已确认：相对 + `.ts` 后缀导入（`allowImportingTsExtensions`），**不可用 `@/` 别名**（Node 不读 tsconfig paths）。

### 3.1 `webui/src/lib/not-found.ts`（新）

```ts
// 错误语义分类的单一事实源（F9-P1-1 收口件）。
//
// 背景：`ApiError` 本体携带 status/code，但中央 error 相位历史上只透 message，
// 于是页面只能 `/HTTP 404/.test(message)` 啃展示文案（3 份同体正则）。后端一旦回
// 带自有 message（api-client.ts:182-185 会覆盖状态行文案），正则即刻失明。
// 本文件把判定改为**只读结构化信号**，文案永不参与判定。
//
// 纪律：本模块零依赖（不 import api-client/react），故 `node --test` 直跑；
// 若 import 了含参数属性（constructor(public x: T)）的 api-client.ts，
// 原生类型剥离会语法报错——这是本席实测结论，见改造稿 §五。

/** 错误语义枚举：页面按此选降级形态，不再各自发明。 */
export type ErrorClass = 'not_found' | 'not_provisioned' | 'auth' | 'unavailable' | 'unknown';

/** 未配置访问令牌的错误码（真相源=control_plane/auth.py；503 携带）。 */
export const NOT_PROVISIONED_CODE = 'control_plane_not_provisioned';

/** 结构化错误信号：来自 error 相位（改造后）或 ApiError 本体。 */
export interface ErrorSignals {
  /** HTTP 状态码；网络层失败=0；缺失（旧相位/非 ApiError）=undefined/null。 */
  status?: number | null;
  /** 控制面错误码（ApiError.code getter 产物，可为 null）。 */
  code?: string | null;
  /** **仅供展示**：classifyError 绝不读取本字段，改文案不可能改变判定（测试锁死）。 */
  message?: string | null;
}

/** 有限数字归一：NaN/Infinity/非数字一律视为「无状态码」。 */
function normalizeStatus(status: number | null | undefined): number | null {
  return typeof status === 'number' && Number.isFinite(status) ? status : null;
}

/** 错误码归一：非字符串（含空串）一律视为「无码」。 */
function normalizeCode(code: string | null | undefined): string | null {
  return typeof code === 'string' && code.length > 0 ? code : null;
}

/**
 * 把结构化错误信号归为语义枚举。
 *
 * 判定序（有优先级，勿改）：404 → 未部署码 → 401/403 → 503/0 → 未知。
 * - `not_found`：仅凭 status===404。端点不存在=该面未部署（前端老系统/新控制面版本错位）。
 * - `not_provisioned`：仅凭错误码，**先于** 503 的泛化判定；码在场即算（后端若哪天换
 *   状态码仍诚实降级为引导设置，而不是掉进通用错误卡）。
 * - `auth`：401/403，令牌无效或无权限。
 * - `unavailable`：503（无未部署码，服务端未就绪）与 0（fetch 抛错=不可达，见
 *   api-client.ts:167-174）。
 * - `unknown`：其余一律未知，绝不猜。
 */
export function classifyError(signals: ErrorSignals): ErrorClass {
  const status = normalizeStatus(signals.status);
  const code = normalizeCode(signals.code);
  if (status === 404) return 'not_found';
  if (code === NOT_PROVISIONED_CODE) return 'not_provisioned';
  if (status === 401 || status === 403) return 'auth';
  if (status === 503 || status === 0) return 'unavailable';
  return 'unknown';
}

/** 页面用谓词：「该端点未部署」（knowledge/plugins/memory-graph 三页的未部署卡）。
 * 注：三页各自的 `*.notDeployed` 标题键是**域内文案**，不是重复逻辑，保持原样；
 * 本函数只统一「何时显示它」的判定。 */
export function isNotDeployed(signals: ErrorSignals): boolean {
  return classifyError(signals) === 'not_found';
}
```

### 3.2 `webui/src/lib/not-found.test.ts`（新，12 例）

```ts
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { classifyError, isNotDeployed, NOT_PROVISIONED_CODE } from './not-found.ts';

// 错误语义分类单测（F9-P1-1 收口锁）。跑法：node --test src/lib/not-found.test.ts。
// 核心命题：判定**只吃结构化信号**，后端改文案不可能改变分类（旧正则的失明面）。

test('404 → not_found（无 message 也能判，正则时代做不到）', () => {
  assert.equal(classifyError({ status: 404 }), 'not_found');
  assert.equal(isNotDeployed({ status: 404 }), true);
});

test('404 + 后端自有 message → 仍 not_found（旧 /HTTP 404/ 在此失明）', () => {
  const signals = { status: 404, message: '知识集合目录不可用，请检查配置' };
  assert.equal(classifyError(signals), 'not_found');
  assert.equal(isNotDeployed(signals), true);
});

test('503 + control_plane_not_provisioned → not_provisioned', () => {
  assert.equal(
    classifyError({ status: 503, code: NOT_PROVISIONED_CODE, message: 'HTTP 503: Service Unavailable' }),
    'not_provisioned'
  );
});

test('错误码优先于状态码：码在场而 status 缺席/为 0 仍判 not_provisioned', () => {
  assert.equal(classifyError({ code: NOT_PROVISIONED_CODE }), 'not_provisioned');
  assert.equal(classifyError({ status: 0, code: NOT_PROVISIONED_CODE }), 'not_provisioned');
  assert.equal(classifyError({ status: 400, code: NOT_PROVISIONED_CODE }), 'not_provisioned');
});

test('401 / 403 → auth', () => {
  assert.equal(classifyError({ status: 401 }), 'auth');
  assert.equal(classifyError({ status: 403 }), 'auth');
});

test('404 优先于鉴权：同为 404 时不吞成 auth', () => {
  assert.equal(classifyError({ status: 404, code: 'unknown_code' }), 'not_found');
});

test('503 无未部署码 → unavailable（服务端未就绪）', () => {
  assert.equal(classifyError({ status: 503 }), 'unavailable');
  assert.equal(classifyError({ status: 503, code: 'stats_invalid_query' }), 'unavailable');
});

test('status 0（fetch 抛错=网络不可达）→ unavailable', () => {
  assert.equal(classifyError({ status: 0, message: 'Failed to fetch' }), 'unavailable');
});

test('其余状态码一律 unknown，绝不猜语义', () => {
  for (const status of [200, 204, 400, 402, 422, 500, 502, 504, 418]) {
    assert.equal(classifyError({ status }), 'unknown', `status=${status} 应判 unknown`);
  }
});

test('文案不得参与判定：message 写着 HTTP 404 但 status=200 → unknown（反正则锁）', () => {
  assert.equal(classifyError({ status: 200, message: 'HTTP 404: Not Found' }), 'unknown');
  assert.equal(isNotDeployed({ message: 'HTTP 404: Not Found' }), false);
  assert.equal(isNotDeployed({ message: 'not found' }), false);
});

test('边界：null/undefined/NaN/空串一律降级为 unknown（不炸）', () => {
  assert.equal(classifyError({}), 'unknown');
  assert.equal(classifyError({ status: null, code: null }), 'unknown');
  assert.equal(classifyError({ status: Number.NaN }), 'unknown');
  assert.equal(classifyError({ status: Number.POSITIVE_INFINITY }), 'unknown');
  assert.equal(classifyError({ code: '' }), 'unknown');
  // 越界类型（后端信封漂移时 JS 层可能拿到）：非数字 status / 非字符串 code 不炸。
  assert.equal(classifyError({ status: '404' as unknown as number }), 'unknown');
  assert.equal(classifyError({ code: 404 as unknown as string }), 'unknown');
});

test('isNotDeployed 与 classifyError 严格同表（谓词不得各走各的）', () => {
  const cases = [
    { status: 404 },
    { status: 404, message: 'x' },
    { status: 503, code: NOT_PROVISIONED_CODE },
    { status: 401 },
    { status: 503 },
    { status: 0 },
    { status: 500 },
    {},
  ];
  for (const signals of cases) {
    assert.equal(isNotDeployed(signals), classifyError(signals) === 'not_found', JSON.stringify(signals));
  }
});
```

**建议追加的增量例（本席未实跑，落手时随门复跑）**——把 §一.1 的生产串钉进契约：

```ts
test('生产 404 信封实证：控制面人话 message 下仍判 not_found', () => {
  // 真相源 _app.py:660-667 + mock_server.py:1382（同 envelope）
  const prod = { status: 404, code: 'not_found', message: '请求的资源或操作不可用。' };
  assert.equal(classifyError(prod), 'not_found');
  assert.equal(/HTTP 404/.test(prod.message ?? ''), false, '旧正则在此必失明（对照证据）');
});
```

### 3.3 `webui/src/lib/reason.ts`（新）

```ts
// source_unavailable 的 reason 码 → 人话：白名单 + 措辞的单一事实源（F9 §四-4 三实现收口件）。
//
// 现状三套实现：① semantic-state.tsx:16 reasonKey（唯一白名单）
//              ② dashboard.tsx:33 fallbackLine（借白名单 + 自拼「暂无数据：X」）
//              ③ plugins.tsx:24 reasonText（**绕过白名单**直查 i18n，措辞「：X」）
// 本模块把「白名单」与「未知码原样透出」收成一处；前缀/排版留给各渲染面。
//
// 纪律：零依赖、纯函数、node --test 直跑。i18n 的 t 以最小签名注入（与 plugins.tsx:24 同形态）。

/**
 * 已知 reason 码白名单（真相源=control_plane 各失败面，18 码逐项可溯源，见改造稿 §一.2；
 * 与两份 locale 的 `reason.*` 键集由同名单测三向对账锁死——加码不改文案即红）。
 */
export const KNOWN_REASONS = [
  'audit_source_not_configured',
  'affinity_source_not_configured',
  'missing_source',
  'missing_table',
  'incomplete_schema',
  'query_budget_exceeded',
  'read_failed',
  'not_connected',
  'not_persisted',
  // PAGES2 增补（真相源=webui_knowledge / webui_plugins / webui_memory_graph 失败面）
  'collection_not_available',
  'all_sources_missing',
  'glossary_source_unavailable',
  'disabled_by_config',
  'features_store_unavailable',
  'static_config_unavailable',
  'cross_process_introspection_unavailable',
  'domains_dir_unavailable',
  'unreadable',
] as const;

export type KnownReason = (typeof KNOWN_REASONS)[number];

/** i18n 翻译函数的最小签名（返回未命中键本身是 i18next 缺省行为）。 */
export type Translate = (key: string) => string;

const KNOWN_SET: ReadonlySet<string> = new Set<string>(KNOWN_REASONS);

/** reason 码 → i18n 键；**未知码返回空串**（调用方据此回退原码，绝不编语义）。 */
export function reasonKey(reason: string): string {
  return KNOWN_SET.has(reason) ? `reason.${reason}` : '';
}

/**
 * reason 码 → 一行人话（无前缀，供各渲染面自行拼「暂无数据：」等外壳）。
 *
 * 约束：
 * - `reason` 为 null / undefined / 空串 → 返回 `''`（无话可说，调用方不渲染该行）。
 * - 已知码且文案在位 → 返回译文。
 * - 已知码但 locale 缺该键（`t` 回吐键本身）→ **回退原码**（诚实：不空显示、不假译）。
 * - 未知码（后端新增/漂移）→ **原样透出码字**（既有诚实语义，测试锁死不得改）。
 * - 永不返回 undefined、永不抛异常、永不做任何字符串猜测。
 */
export function describeReason(reason: string | null | undefined, t: Translate): string {
  if (typeof reason !== 'string' || reason.length === 0) return '';
  const key = reasonKey(reason);
  if (!key) return reason;
  const translated = t(key);
  return translated === key ? reason : translated;
}

/** 某 reason 码是否已登记（供跨语言对账与「后端产出 ⊆ 白名单」断言引用）。 */
export function isKnownReason(reason: string): boolean {
  return KNOWN_SET.has(reason);
}
```

### 3.4 `webui/src/lib/reason.test.ts`（新，8 例；含双语镜像机器锁）

```ts
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { describeReason, isKnownReason, KNOWN_REASONS, reasonKey } from './reason.ts';

// reason 单源锁：白名单命中/未命中/回退原码 + 双语 locale 键集双向对账（F9-P1-5 无锁镜像的机器锁）。

const zh = JSON.parse(readFileSync(new URL('../locales/zh-CN/common.json', import.meta.url), 'utf-8')) as {
  reason: Record<string, string>;
  state: Record<string, string>;
};
const en = JSON.parse(readFileSync(new URL('../locales/en/common.json', import.meta.url), 'utf-8')) as {
  reason: Record<string, string>;
  state: Record<string, string>;
};

/** i18next 缺省行为夹具：未命中回吐键本身（禁用真 i18n 运行时，保持零依赖确定性）。 */
function makeT(table: Record<string, string>): (key: string) => string {
  return (key: string) => {
    const direct = table[key];
    if (direct !== undefined) return direct;
    const [ns, leaf] = key.split('.');
    const bucket = (table as unknown as Record<string, Record<string, string>>)[ns];
    return bucket && leaf ? (bucket[leaf] ?? key) : key;
  };
}

const reasonTable: Record<string, string> = Object.fromEntries(
  Object.entries(zh.reason).map(([code, text]) => [`reason.${code}`, text])
);
const tZh = makeT(reasonTable);

test('已知码 → 译文（白名单命中）', () => {
  assert.equal(describeReason('missing_table', tZh), '数据表不存在（该能力尚未产生过记录）');
  assert.equal(reasonKey('missing_table'), 'reason.missing_table');
});

test('未知码 → 原码透出（既有诚实语义，不得改成空串/不得编译）', () => {
  assert.equal(describeReason('brand_new_backend_reason', tZh), 'brand_new_backend_reason');
  assert.equal(reasonKey('brand_new_backend_reason'), '');
  assert.equal(isKnownReason('brand_new_backend_reason'), false);
});

test('已知码但 locale 缺键 → 回退原码（t 回吐键本身的场景）', () => {
  const emptyT = (key: string) => key;
  assert.equal(describeReason('missing_source', emptyT), 'missing_source');
});

test('边界：null / undefined / 空串 → 空字符串（无话可说不渲染该行）', () => {
  assert.equal(describeReason(null, tZh), '');
  assert.equal(describeReason(undefined, tZh), '');
  assert.equal(describeReason('', tZh), '');
});

test('plugins 页绕白名单场景收口：组级码走同一函数（含 domains_dir_unavailable）', () => {
  for (const code of ['domains_dir_unavailable', 'cross_process_introspection_unavailable', 'disabled_by_config']) {
    assert.equal(isKnownReason(code), true, `${code} 必须在白名单内`);
    assert.notEqual(describeReason(code, tZh), code, `${code} 应有 zh 译文`);
  }
});

test('白名单无重复且全部有 zh 键（加码必须同批改文案）', () => {
  assert.equal(new Set(KNOWN_REASONS).size, KNOWN_REASONS.length);
  for (const code of KNOWN_REASONS) {
    assert.ok(Object.prototype.hasOwnProperty.call(zh.reason, code), `zh 缺 reason.${code}`);
  }
});

test('双语对账：白名单 == zh 键集 == en 键集（三份镜像单向漂移即红）', () => {
  const whitelist = new Set<string>(KNOWN_REASONS);
  const zhKeys = new Set(Object.keys(zh.reason));
  const enKeys = new Set(Object.keys(en.reason));
  assert.deepEqual([...zhKeys].sort(), [...whitelist].sort(), 'zh reason 键集与白名单不等');
  assert.deepEqual([...enKeys].sort(), [...zhKeys].sort(), 'en reason 键集与 zh 不等');
});

test('降级四态主文案双语齐备（acceptance 判据串的键位锁）', () => {
  for (const key of ['noData', 'loadFailed', 'notProvisioned', 'authFailed']) {
    assert.ok(zh.state[key] && en.state[key], `state.${key} 双语缺键`);
  }
  assert.equal(zh.state.noData, '暂无数据');
  assert.equal(zh.state.loadFailed, '加载失败');
});
```

> 最后一例把 `scripts/webui_acceptance.py:91` 的 `COMMON_GRACEFUL` 四串钉进单测：文案一旦被改词，`node --test` 先红，不必等到跑 Playwright。

### 3.5 `webui/src/lib/empty-state.ts`（新）

```ts
// 「空」与「未知」的单一判定与单一符号（F9-P1-3 收口件）。
//
// 两语义必须永久分离：
//   UNKNOWN_VALUE '—'      = 这个**值**未知/不可得（后端「不造数」文化的界面投影）
//   state.noData '暂无数据' = 这次查询结构成功但**集合为空**
// 事故原型：calls.tsx:65 把空列表渲染成 '—'（把空当未知），同文件 trend 空态却用 noData。

/** 未知值符号（全库唯一真值；恰为一枚 U+2014 破折号）。 */
export const UNKNOWN_VALUE = '—';

/** 「空集合」文案的 i18n 键（单源；值与未知符号不同串，测试锁死不得混同）。 */
export const EMPTY_LIST_KEY = 'state.noData';

/**
 * 是否「确知的空列表」。
 * 契约：**只有长度为 0 的真数组**算空。null/undefined/非数组一律 false——
 * 它们表示「还没有值/形状未知」，属**未知**语义，不得冒充「空」（否则又是把未知当空）。
 */
export function isEmptyList(value: unknown): boolean {
  return Array.isArray(value) && value.length === 0;
}

/** 是否有可渲染行（非数组或空数组都 false）。 */
export function isNonEmptyList(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

/** 空列表的统一人话（调用方不再各写各的 '—' / '暂无数据' / '暂无条目'）。 */
export function emptyListText(t: (key: string) => string): string {
  return t(EMPTY_LIST_KEY);
}
```

### 3.6 `webui/src/lib/empty-state.test.ts`（新，7 例）

```ts
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { EMPTY_LIST_KEY, emptyListText, isEmptyList, isNonEmptyList, UNKNOWN_VALUE } from './empty-state.ts';

// 空 vs 未知的语义分离锁（calls 页 P1 的常驻回归面）。

const zh = JSON.parse(readFileSync(new URL('../locales/zh-CN/common.json', import.meta.url), 'utf-8')) as {
  state: Record<string, string>;
  reason: Record<string, string>;
};
const en = JSON.parse(readFileSync(new URL('../locales/en/common.json', import.meta.url), 'utf-8')) as {
  state: Record<string, string>;
  reason: Record<string, string>;
};

test('UNKNOWN_VALUE 恰为一枚 U+2014（不是两个连字符、不是全角破折号）', () => {
  assert.equal(UNKNOWN_VALUE.length, 1);
  assert.equal(UNKNOWN_VALUE.codePointAt(0), 0x2014);
});

test('空态文案键在双语在位，且值不等于未知符号（两语义永不混同）', () => {
  const zhText = zh.state.noData;
  const enText = en.state.noData;
  assert.ok(zhText && enText, 'state.noData 双语缺键');
  assert.notEqual(zhText, UNKNOWN_VALUE, '空态文案不得等于未知符号（P1 复发即红）');
  assert.notEqual(enText, UNKNOWN_VALUE);
  assert.equal(EMPTY_LIST_KEY, 'state.noData');
});

test('isEmptyList：只有长度为 0 的真数组算空', () => {
  assert.equal(isEmptyList([]), true);
  assert.equal(isEmptyList([1]), false);
  assert.equal(isEmptyList(['x']), false);
});

test('isEmptyList：未知形状不算空（null/undefined/空串/对象/0/NaN 一律 false）', () => {
  for (const value of [null, undefined, '', {}, 0, Number.NaN, false, '[]', new Map()]) {
    assert.equal(isEmptyList(value), false, '未知形状不得判为空列表');
  }
});

test('isNonEmptyList 与 isEmptyList 在数组上严格互斥、在非数组上为 false', () => {
  for (const value of [[], [1], null, undefined, 'x', 3]) {
    if (Array.isArray(value)) assert.equal(isEmptyList(value), !isNonEmptyList(value));
    else assert.equal(isNonEmptyList(value), false);
  }
});

test('emptyListText 走单源键：夹具回吐键时得到键本身', () => {
  assert.equal(emptyListText((key) => key), 'state.noData');
  assert.equal(emptyListText(() => zh.state.noData), '暂无数据');
});

test('calls 页 P1 回归：空 TopList 必须走空态文案，绝不落到未知符号', () => {
  const emptyEntries: Array<{ key: string | null; calls: number }> = [];
  assert.equal(isEmptyList(emptyEntries), true);
  const rendered = emptyListText((key) => (key === EMPTY_LIST_KEY ? zh.state.noData : key));
  assert.equal(rendered, '暂无数据');
  assert.notEqual(rendered, UNKNOWN_VALUE);
});
```

### 3.7 `webui/src/lib/window-switcher.ts`（新）

```ts
// 时间窗 / 桶枚举的单一事实源（F9 §六-F3「三种形态」的语义半件）。
//
// DOM 形态（三套按钮组/chips）属组件收敛，不在本文件；本文件管的是**语义**：
// 有哪些窗、各自多长、是否滚动窗、默认窗、以及后端会拒绝哪些值。
// 真相源锚点：control_plane/metrics.py:89 `_WINDOW_SECONDS = {"24h":86_400,"7d":7*86_400,"30d":30*86_400}`
//           与 metrics.py:296-300 `now - timedelta(seconds=…)`（**滚动窗，不是自然日**）。

/** stats 端点（/api/v1/stats/calls|tokens）接受的三档窗。 */
export const STATS_WINDOWS = ['24h', '7d', '30d'] as const;
export type StatsWindowCode = (typeof STATS_WINDOWS)[number];

/** 记忆图谱端点额外接受 all（四档）。 */
export const GRAPH_WINDOWS = ['24h', '7d', '30d', 'all'] as const;
export type GraphWindowCode = (typeof GRAPH_WINDOWS)[number];

/** 趋势桶（后端 invalid_bucket 只认这两个值）。 */
export const BUCKETS = ['hour', 'day'] as const;
export type BucketCode = (typeof BUCKETS)[number];

/** 缺省窗：与 controlApi 的 `?? '24h'` 及后端 signature 缺省一致。 */
export const DEFAULT_WINDOW: StatsWindowCode = '24h';

/** 缺省桶：与 controlApi.statsCalls 的 `?? 'hour'` 一致。 */
export const DEFAULT_BUCKET: BucketCode = 'hour';

/** 窗口秒数；all=无界（null，不造上界）。与后端逐项同值，测试锁死。 */
export const WINDOW_SECONDS: Record<GraphWindowCode, number | null> = {
  '24h': 86_400,
  '7d': 7 * 86_400,
  '30d': 30 * 86_400,
  all: null,
};

/**
 * 窗口语义标记。`rolling=true` 表示「从此刻回溯」，`calendarAligned=false` 表示
 * **不与自然日/周对齐**——界面若把 24h 写成「今日」即名实不符（待裁文案项，本表是判定依据）。
 */
export const WINDOW_SEMANTICS: Record<GraphWindowCode, { rolling: boolean; calendarAligned: boolean }> = {
  '24h': { rolling: true, calendarAligned: false },
  '7d': { rolling: true, calendarAligned: false },
  '30d': { rolling: true, calendarAligned: false },
  all: { rolling: false, calendarAligned: false },
};

/** 运行时值 → stats 窗（URL 深链/持久态读回的窄化；非白名单一律 false，绝不猜）。 */
export function isStatsWindow(value: unknown): value is StatsWindowCode {
  return typeof value === 'string' && (STATS_WINDOWS as readonly string[]).includes(value);
}

/** 运行时值 → 图谱窗。 */
export function isGraphWindow(value: unknown): value is GraphWindowCode {
  return typeof value === 'string' && (GRAPH_WINDOWS as readonly string[]).includes(value);
}

/** 桶切换（calls 页 hour/day 单按钮）：未知值回缺省，不抛不猜。 */
export function nextBucket(current: unknown): BucketCode {
  return current === 'hour' ? 'day' : DEFAULT_BUCKET;
}

/** 读回安全值：非法/缺席一律回缺省窗（配合 sessionStorage/URL 深链）。 */
export function safeStatsWindow(value: unknown): StatsWindowCode {
  return isStatsWindow(value) ? value : DEFAULT_WINDOW;
}
```

### 3.8 `webui/src/lib/window-switcher.test.ts`（新，10 例）

```ts
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  BUCKETS,
  DEFAULT_BUCKET,
  DEFAULT_WINDOW,
  GRAPH_WINDOWS,
  isGraphWindow,
  isStatsWindow,
  nextBucket,
  safeStatsWindow,
  STATS_WINDOWS,
  WINDOW_SECONDS,
  WINDOW_SEMANTICS,
} from './window-switcher.ts';

// 时间窗语义单源锁：与后端 _WINDOW_SECONDS 同值、滚动窗名实、枚举窄化不猜。

const zh = JSON.parse(readFileSync(new URL('../locales/zh-CN/common.json', import.meta.url), 'utf-8')) as {
  calls: { window: Record<string, string> };
  memoryGraph: { window: Record<string, string> };
  dashboard: { overview: Record<string, string> };
};
const en = JSON.parse(readFileSync(new URL('../locales/en/common.json', import.meta.url), 'utf-8')) as typeof zh;

test('枚举与次序：stats 三档、graph = stats + all（顺序即界面顺序，不得随意重排）', () => {
  assert.deepEqual([...STATS_WINDOWS], ['24h', '7d', '30d']);
  assert.deepEqual([...GRAPH_WINDOWS], ['24h', '7d', '30d', 'all']);
  assert.deepEqual([...BUCKETS], ['hour', 'day']);
});

test('窗口秒数与后端 metrics.py:89 逐项同值（后端改界面前端不漂）', () => {
  assert.equal(WINDOW_SECONDS['24h'], 86_400);
  assert.equal(WINDOW_SECONDS['7d'], 604_800);
  assert.equal(WINDOW_SECONDS['30d'], 2_592_000);
  assert.equal(WINDOW_SECONDS.all, null, 'all 无界：不得造上界秒数');
});

test('名实：有限窗全为滚动窗且不与自然日对齐（后端 now - timedelta 实证）', () => {
  for (const code of GRAPH_WINDOWS) {
    assert.equal(WINDOW_SEMANTICS[code].calendarAligned, false, `${code} 声称与自然日对齐=名实不符`);
  }
  assert.equal(WINDOW_SEMANTICS['24h'].rolling, true);
  assert.equal(WINDOW_SEMANTICS.all.rolling, false);
  // 现行界面把 24h 标成「今日（24 小时）」：数值必须仍然显式带 24，防只留「今日」二字。
  assert.ok(zh.dashboard.overview.windowToday.includes('24'), 'windowToday 文案丢失 24 小时口径');
});

test('缺省值三处对齐（前端 ?? 24h / 后端 signature 缺省 / 页面 useState 初值）', () => {
  assert.equal(DEFAULT_WINDOW, '24h');
  assert.equal(DEFAULT_BUCKET, 'hour');
  assert.ok(STATS_WINDOWS.includes(DEFAULT_WINDOW));
  assert.ok(GRAPH_WINDOWS.includes(DEFAULT_WINDOW));
});

test('isStatsWindow：all 不是 stats 窗（后端 invalid_window → 422）', () => {
  for (const code of STATS_WINDOWS) assert.equal(isStatsWindow(code), true);
  assert.equal(isStatsWindow('all'), false);
  assert.equal(isStatsWindow('today'), false);
  assert.equal(isStatsWindow(''), false);
});

test('isGraphWindow 四档收全；非法值窄化失败而非抛异常', () => {
  for (const code of GRAPH_WINDOWS) assert.equal(isGraphWindow(code), true);
  for (const value of [null, undefined, 0, 24, {}, ['24h'], '24H', ' 24h']) {
    assert.equal(isGraphWindow(value), false, `${String(value)} 不得被接受`);
    assert.equal(isStatsWindow(value), false);
  }
});

test('safeStatsWindow：脏值回缺省窗（URL/sessionStorage 读回防御）', () => {
  assert.equal(safeStatsWindow('7d'), '7d');
  for (const value of [null, undefined, 'all', 'bogus', 7]) {
    assert.equal(safeStatsWindow(value), DEFAULT_WINDOW);
  }
});

test('nextBucket：hour/day 两态闭环，未知值回缺省不猜', () => {
  assert.equal(nextBucket('hour'), 'day');
  assert.equal(nextBucket('day'), 'hour');
  assert.equal(nextBucket(undefined), DEFAULT_BUCKET);
  assert.equal(nextBucket('week'), DEFAULT_BUCKET);
});

test('双语窗口文案键集齐备（zh/en 各自的 calls.window 与 memoryGraph.window 覆盖枚举）', () => {
  for (const locale of [zh, en]) {
    for (const code of STATS_WINDOWS) assert.ok(locale.calls.window[code], `calls.window.${code} 缺键`);
    for (const code of GRAPH_WINDOWS) assert.ok(locale.memoryGraph.window[code], `memoryGraph.window.${code} 缺键`);
  }
});

test('已知的第二真值：同一码两套标签（收口前如实记录，收口后此例改等值断言）', () => {
  // 现状 calls.window.7d=「7 天」而 memoryGraph.window.7d=「近 7 天」；
  // 统一到单一命名空间后，把本例改成 assert.equal(zh.calls.window['7d'], zh.memoryGraph.window['7d'])。
  const diverging = STATS_WINDOWS.filter((code) => zh.memoryGraph.window[code] !== zh.calls.window[code]);
  assert.deepEqual(diverging, ['24h', '7d', '30d'], '标签分叉数量变化——收口进度需同步本锁');
});
```

### 3.9 接入改动清单（逐处 before → after）

> 约定：`lib` 指 `@/lib`。以下坐标为 17:05 快照实测行号，锚点字符串不受行号漂移影响。

**（a）三页 404 判定退役（与 §二.2 同批，不可拆）**

| 文件 | before | after |
|---|---|---|
| `knowledge.tsx:28-30` | `function isNotFound(message: string): boolean { return /HTTP 404/.test(message); }` | **整块删除**；`import { isNotDeployed } from '@/lib/not-found';` |
| `knowledge.tsx:153` | `{isNotFound(collections.state.message) ? (` | `{isNotDeployed(collections.state) ? (` |
| `knowledge.tsx:242` | `isNotFound(terms.state.message) ? (` | `isNotDeployed(terms.state) ? (` |
| `plugins.tsx:19-21` | 同体 `isNotFound` | 删除 + 同上 import |
| `plugins.tsx:171` | `isNotFound(query.state.message) ? (` | `isNotDeployed(query.state) ? (` |
| `memory-graph.tsx:34-36` | 同体 `isNotFound` | 删除 + 同上 import |
| `memory-graph.tsx:154` | `isNotFound(graph.state.message) ? (` | `isNotDeployed(graph.state) ? (` |

类型可过性说明：三处均在 `state.phase === 'error'` 判定内，`state` 已窄化为 error 变体，其形状 `{phase, message, status?, code?}` 结构上满足 `ErrorSignals`（多出的 `phase` 属性不触发 excess-property 检查，因为传的是变量而非对象字面量）。`isNotDeployed(state)` 合法。

**（b）reason 单源**

| 文件 | before | after |
|---|---|---|
| `semantic-state.tsx:15-39` | `export function reasonKey(reason) { const known = […18…]; return known.includes(reason) ? \`reason.${reason}\` : ''; }` | **整块删除**；文件头 `import { describeReason, reasonKey } from '@/lib/reason';`（`reasonKey` 若本文件不再用则只 import `describeReason`） |
| `semantic-state.tsx:89,95` | `const key = reasonKey(state.reason);` … `{key ? t(key) : state.reason}` | 删 `key` 行；`{describeReason(state.reason, t)}`（渲染字节等价：已知码译文、未知码原码） |
| `dashboard.tsx:15` | `import { SemanticState, openSettings, reasonKey } from '@/components/semantic/semantic-state';` | `import { SemanticState, openSettings } from '@/components/semantic/semantic-state';` + `import { describeReason } from '@/lib/reason';` |
| `dashboard.tsx:34-41` | `const key = reasonKey(state.reason); if (key) { const translated = t(key); if (translated !== key) return \`${t('state.noData')}：${translated}\`; } return \`${t('state.noData')}：${state.reason}\`;` | `return \`${t('state.noData')}：${describeReason(state.reason, t)}\`;`（`describeReason` 空串只在 reason 为空时出现，而该相位 `reason: string` 恒有值，语义等价） |
| `plugins.tsx:23-29` | `function reasonText(reason, t) { if (!reason) return ''; const key = \`reason.${reason}\`; const translated = t(key); return translated === key ? \`：${reason}\` : \`：${translated}\`; }` | `import { describeReason } from '@/lib/reason';` + `const reasonSuffix = (reason: string \| null): string => { const text = describeReason(reason, t); return text ? \`：${text}\` : ''; };`（`:121` 的 `{reasonText(group.reason, t)}` → `{reasonSuffix(group.reason)}`） |

行为等价性的**唯一前提**是「白名单 == locale 键集」，该前提由 `reason.test.ts` 第 7 例钉死——这是本稿敢删绕行实现的理由。

**（c）空态 / 未知（calls 页 P1）**

| 文件 | before | after |
|---|---|---|
| `calls.tsx:65` | `{entries.length === 0 && <p className='py-6 text-center fs-caption text-muted-foreground'>—</p>}` | `{isEmptyList(entries) && <p className='py-6 text-center fs-caption text-muted-foreground'>{emptyListText(t)}</p>}` |
| `calls.tsx:199` | `labelFor={(key) => key ?? '—'}` | `labelFor={(key) => key ?? UNKNOWN_VALUE}` |
| `lib/format.ts:4,9,15,27,34` | 5 处 `return '—';` | `import { UNKNOWN_VALUE } from './empty-state';` + `return UNKNOWN_VALUE;`（返回值逐字节不变，消掉 5 处字面量） |
| 其余 6 处 `t('state.noData')`（`calls:157`/`tokens:135,206`/`latency:73`/`affinity:97`/`semantic-state:94`） | 保持 | **可选**统一为 `emptyListText(t)`；不改也已被 `EMPTY_LIST_KEY` 键位锁定，不阻塞 |
| `plugins.tsx:133`（「暂无条目」）/ `memory-graph.tsx:164`（专用空态卡） | 保持 | **不改**——域内措辞且是验收判据（见 §七） |

**（d）窗口语义单源（不动 DOM、不动文案）**

| 文件 | before | after |
|---|---|---|
| `api-client.ts:396,437` | `export type GraphWindow = '24h' \| '7d' \| '30d' \| 'all';` / `export type StatsWindow = '24h' \| '7d' \| '30d';` | `import type { GraphWindowCode, StatsWindowCode } from './window-switcher.ts';` + `export type { GraphWindowCode as GraphWindow, StatsWindowCode as StatsWindow };`（再导出保持页面 import 面零改动；纯类型语句，被 Vite 与 strip-types 双向剥离） |
| `calls.tsx:23` | `const WINDOWS: StatsWindow[] = ['24h', '7d', '30d'];` | 删除，`WindowSwitch` 直接用 `STATS_WINDOWS`（`import { STATS_WINDOWS, type StatsWindowCode } from '@/lib/window-switcher';`） |
| `calls.tsx:89-90` | `useState<StatsWindow>('24h')` / `useState<'hour' \| 'day'>('hour')` | `useState<StatsWindowCode>(DEFAULT_WINDOW)` / `useState<BucketCode>(DEFAULT_BUCKET)`；`:108` 的三元翻转 → `onClick={() => setBucket(nextBucket(bucket))}` |
| `tokens.tsx:23,73` | 本地 `const WINDOWS` + `useState<StatsWindow>('24h')` | `STATS_WINDOWS` + `useState<StatsWindowCode>(DEFAULT_WINDOW)`（枚举不再第三写） |
| `memory-graph.tsx:24,40` | `const WINDOWS: GraphWindow[] = ['24h','7d','30d','all']` + `useState<GraphWindow>('24h')` | `GRAPH_WINDOWS` + `useState<GraphWindowCode>(DEFAULT_WINDOW)` |
| `dashboard.tsx:95,97` | 字面 `'24h'` / `'7d'` | `DEFAULT_WINDOW` / `STATS_WINDOWS[1]`（可选，纯一致性；不动渲染） |

DOM 三形态合一（`patterns.ToggleChipGroup`）与标签命名空间合一（`window.*` 单点）是**动版式/动文案**的后续批，本稿只做语义层，理由见 §七。

---

## 四、测试可跑性核验（本席 `%TEMP%` 实跑输出）

拟稿镜像仓库层级：`%TEMP%/f23/lib/*.ts|*.test.ts` + `%TEMP%/f23/locales/{zh-CN,en}/common.json`（两份 locale 为**只读拷贝**，故 `new URL('../locales/…', import.meta.url)` 与仓库内路径解析完全同构）。

```
$ node -v
v26.7.0
$ date
Sat Sep 19 17:05:18     2026
```

四种命令形态实跑（cwd=`%TEMP%/f23`，`--test-reporter=tap`）：

| 形态 | 命令 | 结果 |
|---|---|---|
| A 显式文件列表 | `node --test --test-reporter=tap lib/not-found.test.ts lib/reason.test.ts lib/empty-state.test.ts lib/window-switcher.test.ts` | `# tests 37  # pass 37  # fail 0  # cancelled 0` |
| B shell 展开通配 | `node --test --test-reporter=tap lib/*.test.ts` | `# tests 37  # pass 37  # fail 0` |
| C **加引号交给 Node 自己展开通配** | `node --test --test-reporter=tap "lib/*.test.ts"` | `# tests 37  # pass 37  # fail 0` |
| D 零参数自动发现 | `node --test --test-reporter=tap` | `# tests 37  # pass 37  # fail 0` |
| 单文件（空态族） | `node --test --test-reporter=tap lib/empty-state.test.ts` | `# tests 7  # pass 7  # fail 0  # cancelled 0`（`duration_ms 117.3975`） |

**结论 1（通配写法）**：`node --test src/lib/*.test.ts` **可用**，且**不依赖 shell 是否展开**——形态 C 证明 Node 自身接受 glob（含 Windows 路径下的正斜杠）。npm script 在 Windows 走 cmd.exe（不展开通配）也成立。形态 D（零参数发现）同样能发现 `.ts` 用例，但仓库内会连带扫描 `webui/` 全树，**建议固定用带引号的 `src/lib/*.test.ts`**，作用域可预测。

**结论 2（无需 `--experimental-strip-types`）**：复核 F18 的实测结论成立——Node 26 的 TS 类型剥离**默认开启**（`node --help` 实跑只剩 `--experimental-strip-types, --no-strip-types  Type-stripping for TypeScript files.` 一行），本席 37 例全程未加任何标志。

**结论 3（一次真实缺陷被抓到）**：首轮合跑输出 `# tests 31 / # pass 30 / # fail 1`，失败原因不是语义断言，而是 `empty-state.test.ts` 用例标题里嵌了未转义的 `''`，把单引号字符串字面量截断（文件按「集合」计 1 fail、7 例全丢）。修正标题文案后单文件复跑 7/7 全绿，四文件合跑 37/37。**这条要写进规矩**：用例名禁用 ASCII 单引号（本仓库用例名一律中文括号，正是这个原因）。

**结论 4（门禁耗时）**：37 例单文件级 ≈ 0.12–0.23s（实测 `duration_ms 117–226`），与 F18 记录的 `node --test ≈0.3s` 同量级，常驻化成本可忽略。

---

## 五、强制前置约束：strip-only 不认「非可擦除语法」（本席探针实跑）

| 探针 | 命令 | 实跑结果 |
|---|---|---|
| 参数属性 | `node --test probe/pp.test.ts`（类构造器写 `constructor(m: string, public status: number)`） | `SyntaxError [ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX]: TypeScript parameter property is not supported in strip-only mode`，`# pass 0 / # fail 1` |
| `enum` | `node --test probe/enum.test.ts`（`export enum E { A = 1 }`） | `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX: TypeScript enum is not supported in strip-only mode` |
| 逃生标志是否存在 | `node --experimental-transform-types -e "…"` | `C:\Software\nodejs\node.exe: bad option: --experimental-transform-types`（**Node 26 已移除该标志**） |

三条合起来的硬含义，主会话落手时必须遵守：

1. **任何被 `node --test` 触达的模块，禁止 `enum`、禁止参数属性、禁止 `namespace`**；枚举一律 `as const` 数组 + 联合类型（本稿四件全部照此写）。
2. **`lib/api-client.ts` 目前不可被单测导入**：`ApiError` 构造器 `constructor(message: string, public status: number, public response?: unknown)`（`api-client.ts:130-134`）正是参数属性——本席对该文件副本的导入探针因权限层拦截未跑完，但语法形态与探针 1 **逐字同构**，结论按同构推定（诚实标注：此条为推定，非实跑）。
   - 因此本稿的 `classifyError` 刻意**只吃 POJO 信号**，`describeReason` 只吃注入的 `t`，四件模块零 import。这是设计约束，不是风格选择。
   - 若将来要单测 `ApiError` 本体，先做 3 行等价改写（行为不变）：
     ```ts
     // before（api-client.ts:129-137）
     export class ApiError extends Error {
       constructor(message: string, public status: number, public response?: unknown) {
         super(message);
         this.name = 'ApiError';
       }
     // after（可擦除，strip-only 可加载）
     export class ApiError extends Error {
       readonly status: number;
       readonly response?: unknown;
       constructor(message: string, status: number, response?: unknown) {
         super(message);
         this.name = 'ApiError';
         this.status = status;
         this.response = response;
       }
     ```
     牵动点：`ApiError` 的 `new` 点 2 处（`api-client.ts:173, :191`，签名不变）+ 消费方 `instanceof` 3 处（`use-semantic-query.ts:33,42`、`main.tsx:20`）全部零改动。**独立小批**，与本稿四件无依赖关系。
3. **类型-only 导入/再导出必须写 `import type` / `export type`**（`isolatedModules` 已在 `tsconfig.app.json:13`）；`window-switcher.ts` 拥有 `StatsWindow/GraphWindow`、`api-client.ts` 以 `export type { … }` 再导出的形态，本席写了 `probe2` 复验但**执行被权限层拦下，未实跑**（缓解事实：该写法只出现在 `api-client.ts`，而 `api-client.ts` 从不在测试链上；测试链只有零 import 的四个纯模块）。若主会话想彻底安心，把 `api-client.ts` 的再导出改为**页面直接从 `@/lib/window-switcher` 引类型**（4 个文件 import 行），零残余风险。
4. 新文件会进版式宪法扫描（`webui/scripts/layout-constitution.mjs` 的 `walk()` 收 `.ts|.tsx`）。本席逐条比对四条正则：无 hex（`0x2014` 不带 `#`）、无 `text-*` 字号档、无 `p-*/gap-*` 越刻度、无调色板类名（大写 `F9-P1-1` 不匹配无前缀 `i` 的 `\bp-` 族）→ 不触发。**基线复跑为绿**：见 §八 收尾（同命令实跑 `exit=0`）。

---

## 六、与 F18 常驻门的衔接（含一处**必须同批改**的冲突）

现状门（已落盘）：`tests/test_webui_constitution.py:99-114` 跑 `node --test --test-reporter=tap src/lib/graph-layout.test.ts` 并断言 `# fail 0` / `# cancelled 0` / `# pass N`（`re.search(r"^# pass (\d+)$", …)`）+ `passed >= 7`。

### 6.1 ⚠️ 冲突预警：`package.json` 断言会红

`tests/test_webui_constitution.py:124-127`：

```python
test_entry = scripts.get("test", "")
assert "node --test" in test_entry and "graph-layout.test.ts" in test_entry, (...)
```

若按本稿把 `webui/package.json:11` 的 `"test": "node --test src/lib/graph-layout.test.ts"` 升级为通配全量，**这条断言立即红**。两种收法，取其一、**同一批**：
- （推荐）放宽为 `assert "node --test" in test_entry`，另断言 `assert "src/lib" in test_entry`（锁作用域而非锁单文件名）；
- 或保持脚本只跑 graph-layout、另立 `npm run test:all`——不推荐（两条入口必有一条被遗忘，正是 F9-P1-2「写了没接线」的形态）。

### 6.2 棘轮断言写法（可直接替换 §6.1 那条函数的姊妹件）

语义要求：**加用例不砸门；删/改名用例必红；数字下限只增不减**。

```python
# ---- 追加到 tests/test_webui_constitution.py ----
# 纯函数用例基线（2026-09-19 F23 收口波）：file → 必须在场的关键用例名锚点（子集即可）。
# 只增不减：新增用例无需改门；删掉或改名下列任一锚点 → 红。
WEBUI_PURE_ANCHORS: dict[str, tuple[str, ...]] = {
    "not-found.test.ts": (
        "404 → not_found（无 message 也能判，正则时代做不到）",
        "文案不得参与判定：message 写着 HTTP 404 但 status=200 → unknown（反正则锁）",
        "isNotDeployed 与 classifyError 严格同表（谓词不得各走各的）",
    ),
    "reason.test.ts": (
        "未知码 → 原码透出（既有诚实语义，不得改成空串/不得编译）",
        "双语对账：白名单 == zh 键集 == en 键集（三份镜像单向漂移即红）",
        "降级四态主文案双语齐备（acceptance 判据串的键位锁）",
    ),
    "empty-state.test.ts": (
        "UNKNOWN_VALUE 恰为一枚 U+2014（不是两个连字符、不是全角破折号）",
        "空态文案键在双语在位，且值不等于未知符号（两语义永不混同）",
        "calls 页 P1 回归：空 TopList 必须走空态文案，绝不落到未知符号",
    ),
    "window-switcher.test.ts": (
        "窗口秒数与后端 metrics.py:89 逐项同值（后端改界面前端不漂）",
        "名实：有限窗全为滚动窗且不与自然日对齐（后端 now - timedelta 实证）",
        "isStatsWindow：all 不是 stats 窗（后端 invalid_window → 422）",
    ),
}

# 用例总数下限 = graph-layout 7 + not-found 12 + reason 8 + empty-state 7 + window-switcher 10。
# 加用例时**不必**动这里；只有把用例删到基线以下才红（与既有 pass>=7 同一取向）。
WEBUI_TEST_MIN_PASS = 44


def test_webui_pure_lib_tests() -> None:
    """src/lib 全量纯函数单测常驻门（本文件 graph-layout 那条的推广，二者并存不冲突）。"""
    node = _require_node()
    proc = _run([node, "--test", "--test-reporter=tap", "src/lib/*.test.ts"], 120)
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, f"node --test 红：exit={proc.returncode}\n{stdout}\n{stderr}"
    assert "# fail 0" in stdout, stdout
    assert "# cancelled 0" in stdout, stdout
    match = re.search(r"^# pass (\d+)$", stdout, re.MULTILINE)
    assert match is not None, f"TAP 摘要行缺失（reporter 形态漂移？）：\n{stdout}"
    assert int(match.group(1)) >= WEBUI_TEST_MIN_PASS, (
        f"pass {match.group(1)} < 基线 {WEBUI_TEST_MIN_PASS}（2026-09-19 F23 收口波）"
    )
    # 锚点锁：允许任意缩进形态（多文件 TAP 可能整体缩进两格）。
    names = set(re.findall(r"^\s*ok \d+ - (.+)$", stdout, re.MULTILINE))
    for fname, anchors in WEBUI_PURE_ANCHORS.items():
        for anchor in anchors:
            assert anchor in names, f"{fname} 的语义锚点用例消失：{anchor}\n实际用例名：{sorted(names)}"


def test_webui_no_string_sniffing_gates() -> None:
    """负断言门：错误判定不得再回到啃文案（F9-P1-1 收口后的常驻护栏）。"""
    roots = [WEBUI / "src"]
    banned = ("isNotFound", "/HTTP 404/", "HTTP 404")
    hits: list[str] = []
    for root in roots:
        for path in root.rglob("*.ts*"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for needle in banned:
                if needle in text:
                    hits.append(f"{path.relative_to(WEBUI)}: {needle}")
    assert not hits, "啃文案的 404 判定复现（应改用 @/lib/not-found.classifyError）：\n" + "\n".join(hits)
```

要点说明：
- **数字下限只做粗闸**（防整文件被误删），**锚点集合做精确棘轮**（改名/删除即红，新增自由）——两者互补，都是「只增不减」。
- 负断言门里的 `"HTTP 404"` 串**只在 §二/§三 落地后加**（否则今天必红：`api-client.ts:177` 自己就在拼 `HTTP ${status}`）。注意 `api-client.ts:177` 是**生产者**、不是判定者，若要放行可把 banned 限定为 `isNotFound` 与 `/HTTP 404/`（推荐这个更窄的形态）。本席建议：**先窄后宽**——先钉 `isNotFound` + `/HTTP 404/` 两项，确认稳定后再考虑扩到 `"HTTP 404"`。
- 门的调用形态选**加引号的 glob**（§四 形态 C 实跑证明参数原样交给 Node 时 Node 自己展开），比零参数发现的作用域可控。
- 门的 `pass>=44` 与既有 `pass>=7` 并存会重复跑一次 graph-layout（+≈0.15s），可接受；若嫌重复，把旧那条改为只跑 `src/lib/graph-layout.test.ts` 并在锚点表里补 graph-layout 的 3 个锚点名，`WEBUI_TEST_MIN_PASS` 不变。

---

## 七、回归风险清单与**不可动文案清单**

### 7.1 被牵动的渲染路径

| 改动 | 牵动路径 | 风险 | 缓解 |
|---|---|---|---|
| error 相位 +2 可选字段 | `SemanticState` 错误卡、`dashboard.fallbackLine`、`error-boundary`、三页未部署卡 | 低（纯增量，无字段被读旧） | 三页**必须**同批替换，否则新字段无人消费=第二条「写了没接线」 |
| 三页 → `isNotDeployed` | knowledge/plugins/memory-graph 的 error 分支 | **行为会变**：不可达的「未部署」卡恢复可达 | 真机验收前不可宣称「无视觉变化」；`pre_restart_check`/`webui_acceptance` 的 MOCKUI 模式下三页端点恒 200，**不会触发该分支**，验收不红也不代表对——需 `webui_mock_server.py` 走未知路径（`:1378` 已具备 404 通道）人工目验 |
| `describeReason` 收口 | `semantic-state` 降级行、dashboard 一行式、plugins 组级行 | 中（plugins 若 locale 有键但白名单没有 → 译文会由「有」变「无」） | 白名单==双语键集由 `reason.test.ts` 先锁，再删绕行 |
| calls:65 `'—'` → `暂无数据` | calls 页三张 TopList 空态 | 低（`暂无数据` ∈ `COMMON_GRACEFUL`） | 见 §7.2 |
| `format.ts` 引 `UNKNOWN_VALUE` | 全站数值/时间/时长显示 | 极低（同字节） | `format.test.ts`（F9 §七清单里的伴生件，本稿未含） |
| 窗口枚举上收 | 三页切换器 + 两 dashboard queryKey | 低（值集合完全一致） | queryKey 字面量与 `DEFAULT_WINDOW` 同值，缓存键不变（`'stats-calls','24h'…`） |
| **标签命名空间合一 / 「今日」改名**（本稿**不做**） | 界面文案 + 验收脚本 | **高**：验收读的是 **dist**，改 src 不立刻红，一旦 `npm run build` 就可能红 | 单独文案批 + 重建 dist + 复跑 `scripts/webui_acceptance.py`（§7.2 判据表） |

### 7.2 不可动文案清单（动一条 = 真机验收变红，`scripts/webui_acceptance.py:48-92`）

验收逻辑：每页先找 `ok` 串（任一命中 → `mode="data"`），否则找 `COMMON_GRACEFUL + graceful_extra`（命中 → `mode="graceful"`）；两者皆无 = FAIL（白屏判据）。**判定的是渲染后中文文本**，因此以下串**逐字不可改、不可删**：

1. **壳层**：`守岸人控制台`（`SHELL_MARKER`，`:92`）—— 页面标题/侧栏任何一处洗掉即全页 FAIL。
2. **通用降级四串**（`COMMON_GRACEFUL`，`:91`）：`加载失败`、`暂无数据`、`控制面未配置访问令牌`、`令牌无效或无权限`。
   → 本稿把 calls 空列表改成 `暂无数据` 之所以**安全**，正是因为该串在判据白名单内；反过来，**把 `state.noData` 改词（例如「暂无记录」）会同时击落 6 处空态 + 全站 graceful 判定**，属最高危文案。
3. **各页数据态标志（`ok`）**：`在线`/`降级`（dashboard）、`窗口内调用`（calls）、`窗口总量`（tokens）、`渠道（`（latency，含左括号）、`好感度排行`（affinity）、`心跳`（logs）、`别名：`/`个文本块`/`条表情`/`启用中`（knowledge）、`热更新即可`/`暂无条目`/`该组清单暂不可用`（plugins）、`关联图谱`/`图例`（memory-graph）。
   → 特别注意 **`暂无条目`（`plugins.emptyGroup`）出现在 `ok` 列表里**：若把它统一成 `暂无数据`，plugins 页在「有组但组内空」的夹具下会从 `data` 掉到 `graceful`（判定仍 PASS 但**模式变了**，基线核图/双轮对比会显示差异）。
4. **各页特有降级（`graceful_extra`）**：`未连接`/`连接中`/`重连中`/`已连接，等待事件`/`连接被拒`（logs）、`知识库目录未部署`/`知识库数据源均未启用`/`该集合暂无词条`/`没有匹配`（knowledge）、`插件目录未部署`（plugins）、`记忆图谱未部署`/`该时间窗内无记忆关联数据`（memory-graph）。
   → 三张「未部署」卡恢复可达后，这三串**首次真正被渲染**：改它们的措辞 = 改判据，必须同步 `webui_acceptance.py`（**该文件本席不动**）。
5. **DOM 判据**：logs/memory-graph 的 `ok_dom`（`[aria-live='polite'] div`、`canvas`）—— 空态改造**不得**把 canvas 或 aria-live 容器在数据态下换成别的元素。
6. **噪声白名单**：`NOISE_RE`（`:94`，`Failed to load resource|net::ERR_|favicon`）—— 若 signal/超时接线把 `AbortError: signal is aborted without reason` 之类新控制台错误暴露出来，会在验收里变成非白噪声 → **本稿不含超时/abort 接线**（属 F9-P2-7 步骤⑤），提示那一批要连带核 `NOISE_RE`。

**本稿四件与 locales 的关系**：`not-found.ts`/`window-switcher.ts` 不新增/不改任何 locale 键；`reason.ts` 与 `empty-state.ts` 只**引用**既有键；两份 locale JSON 在实跑里是被**读**来做镜像对账的。→ 落本稿步骤①-③，**验收文案零变化**（唯一例外：calls:65 的 `—`→`暂无数据`，在白名单内）。

### 7.3 其它门

- `tests/verify_hashes.py`：`grep -n "webui\|dist"` → **0 命中**（本席实跑），四件新文件与 error 相位改动**不触发哈希册重录**（本席也禁 `--write`）。F9-P2-13 的「dist 入册」另批裁决。
- `dev.ps1 -Task runtime-layout` / `lint` / `typecheck`（mypy）：纯前端 .ts 文件不进 Python 静态门；`typecheck`=mypy 与 tsc 无关，**前端类型错误目前只有 `npm run typecheck` 能抓** → F18 的 `test_tsc_typecheck_all_projects`（已落盘 `:87-96`）是本稿最大的安全网：`DataState` 加字段、三页 `state` 传参、`api-client.ts` 类型再导出，**全靠它红**。
- 全量 pytest：新增门函数会让 `tests/test_webui_constitution.py` 从 4 例变 5-6 例（用例数增量属预期，勿按「基线漂移」误判为红）。

---

## 八、落手顺序建议（每批都可独立复跑、不留中间态红）

| 批 | 内容 | 为什么必须同批 | 复跑判据 |
|---|---|---|---|
| **①（纯增量，零行为变化）** | 落 8 个文件（`not-found`/`reason`/`empty-state`/`window-switcher` 各 `.ts`+`.test.ts`）；`package.json` `test` → `node --test src/lib/*.test.ts`；F18 门加 `test_webui_pure_lib_tests` 并把 `:125` 的 `"graph-layout.test.ts" in test_entry` 放宽（§6.1） | 门的 package.json 断言与脚本改造**必须同批**，否则门红 | `node --test --test-reporter=tap "src/lib/*.test.ts"` → `# pass 44 / # fail 0`；`tests/test_webui_constitution.py` 全绿；宪法门 `exit=0` |
| **②（原子：错误接口）** | §二.2 的 2 行 + §三.9(a) 的 7 处；**同批**加 `test_webui_no_string_sniffing_gates`（窄形态：禁 `isNotFound` 与 `/HTTP 404/`） | 字段与消费点拆开留 = 新逻辑无人消费；门早加 = 立刻红 | `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json` 零错误；`grep -rn "isNotFound\|HTTP 404" webui/src/pages` 0 命中 |
| **③（原子：reason 单源）** | §三.9(b)：先确认 `reason.test.ts` 的双语对账已绿（①里已绿），再删 `semantic-state.tsx:15-39`、改 3 处消费 | 白名单==locale 键集是删绕行的**前提**，前提不锁就删 = 静默丢译文 | `node --test src/lib/reason.test.ts`；tsc；`grep -n "reason\." webui/src/pages/plugins.tsx` 仅剩 `describeReason` 间接引用 |
| **④（语义两小刀）** | §三.9(c) 空态/未知 + §三.9(d) 窗口枚举上收（**不动标签文案、不动 DOM**） | 可拆；两半各自 tsc + 门 | `grep -n ">—<" webui/src/pages/calls.tsx` 0 命中；`grep -c "const WINDOWS" webui/src/pages/*.tsx` 0 命中；门 44 例绿 |
| **⑤（文案/版式批，需用户裁定）** | `calls.window.*` 与 `memoryGraph.window.*` 合一（建议统一到 `window.*`，值取「近 24 小时/近 7 天/近 30 天/全部时间」）；`dashboard.overview.windowToday` 「今日（24 小时）」→「近 24 小时（滚动窗）」；`patterns.ToggleChipGroup` 三形态合一；`window` 变量遮蔽改名 ×3 | 全部**动用户可见文案/DOM**：必须同批 `npm run build` 重建 dist + `python scripts/webui_acceptance.py`（MOCKUI）9 页 + 双轮基线核图 | 验收 9 页全 PASS 且 mode 与本轮前一致；`window-switcher.test.ts` 最后一例改等值断言 |
| **⑥（产物锁，另批）** | dist 入 `verify_hashes.py --write`（**主会话执行，本席禁**）+ `pre_restart_check` 新鲜度 WARN | 牵哈希册重录，独立批 | `python tests/verify_hashes.py --check` |

**明确不要做的两件事**：①把 `error` 相位字段做成**必填**（会砸 `error-boundary.tsx:24` 与任何未读快照）；②在本波顺手做 F9-P1-2 重试单源/超时接线（§7.2-6 的控制台噪声风险，独立小批更干净）。

---

## 九、本席边界与诚实披露

1. **零修改**：除本文件外未新建/编辑/删除仓库任何文件；`%TEMP%/f23/` 下为拟稿与探针（含两份 locale 只读拷贝、一份 `api-client.ts` 只读拷贝），**未拷回仓库**，可随时删。
2. **实跑覆盖**：37 个拟稿用例（A/B/C/D 四种命令形态 + 单文件形态）、版式宪法门、`node -v`/`date`、三个 strip-only 探针、`--experimental-transform-types` 合法性、reason/窗口秒数的后端溯源 grep、`verify_hashes` 覆盖度 grep → 全部已贴输出。
3. **未实跑（权限层拦截，非缺漏）**：(a) `api-client.ts` 副本被 `node --test` 导入的失败复现（§五.2，按语法同构推定）；(b) `probe2` 的 type-only 再导出剥离（§五.3，附了替代方案）；(c) `node --test <目录>` 形态；(d) §3.2 末尾「生产 404 串」增量例。四条均已就地标注，主会话落手时由门复跑即可。
4. **未做**：`webui_acceptance.py` 判据改造、locale 文案统一、DOM 形态合一、重试/超时接线、哈希册登记、dist 重建——全部按「只设计不落手」交付。
5. 行号为 17:05 快照；主会话并发编辑会使行号漂移，**锚点字符串不受影响**。
