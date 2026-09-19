// 时间窗 / 趋势桶的**枚举 + 标签 + 跨度语义**的单一事实源（审计 F23 §一.3 收口件）。
//
// 收口前现状（19:14 快照口径，实测 grep）：三份枚举 `const WINDOWS`（calls.tsx:23 /
// tokens.tsx:25 / memory-graph.tsx:26）+ 四份标签真值表（`calls.window.*`、
// `memoryGraph.window.*`、`dashboard.overview.windowToday`、`dashboard.overview.window7d`）。
// 同一次「切到 7 天」在四处各有说法，改一处即分叉。
//
// 本模块管语义与取键，**不管 DOM**：按钮组/chips 的三套外观属组件收敛（另批）。
// 页面只许写 `t(WINDOW_LABEL_KEYS[code])`（或 `windowLabel(t, code)`），不得再手抄枚举。
//
// 名实纪律：后端窗口是**从此刻回溯的滚动窗**（`metrics.py:89 _WINDOW_SECONDS` 配
// `now - timedelta(seconds=…)`），与自然日无关——标签里出现「今日/当天/Today」即名实不符。
// 该纪律双向钉死：双语标签文案门在 `labels.test.ts`（密封，只读 webui/），后端源码字面量
// 对账在 `tests/test_webui_labels_backend_parity.py`（pytest，缺模块显式 skip——C-1 裁定）。
//
// 纪律：零运行时依赖（只 `import type`）、无 enum/参数属性/namespace，故 `node --test` 直跑。

/** stats 端点（/api/v1/stats/calls|tokens）接受的三档窗。顺序即界面顺序。 */
export const STATS_WINDOWS = ['24h', '7d', '30d'] as const;
export type StatsWindowCode = (typeof STATS_WINDOWS)[number];

/** 记忆图谱端点额外接受 `all`（四档）。真相源 webui_memory_graph.py:43 `_WINDOWS`。 */
export const GRAPH_WINDOWS = ['24h', '7d', '30d', 'all'] as const;
export type GraphWindowCode = (typeof GRAPH_WINDOWS)[number];

/** 趋势桶（真相源 webui_stats.py:47 `_BUCKETS`，表外值后端 422 invalid_bucket）。 */
export const BUCKETS = ['hour', 'day'] as const;
export type BucketCode = (typeof BUCKETS)[number];

/** 缺省窗：与后端 signature 缺省（`window: str = "24h"`）及 api-client 的 `?? '24h'` 同值。 */
export const DEFAULT_WINDOW: StatsWindowCode = '24h';

/** 缺省桶：与 api-client `bucket?: 'hour' | 'day'` 的调用缺省一致。 */
export const DEFAULT_BUCKET: BucketCode = 'hour';

/**
 * 窗口跨度（秒）；`all` 为无界（null，不造上界）。
 * 逐字对齐后端闭集，跨语言同值由 `tests/test_webui_labels_backend_parity.py` 解析后端源码对账
 * （改一侧必红；node 侧只锁 labels ↔ 枚举 ↔ 标签，见该文件 docstring 的 C-1 裁定）：
 * `control_plane/metrics.py:89`、`webui_stats.py:46`、`control_plane/webui_memory_graph.py:43`。
 */
export const WINDOW_SECONDS: Record<GraphWindowCode, number | null> = {
  '24h': 86_400,
  '7d': 7 * 86_400,
  '30d': 30 * 86_400,
  all: null,
};

/** 是否滚动窗（从此刻回溯）。有限窗一律 true；`all` 无回溯起点，故 false。 */
export const WINDOW_IS_ROLLING: Record<GraphWindowCode, boolean> = {
  '24h': true,
  '7d': true,
  '30d': true,
  all: false,
};

/** 窗口标签的 i18n 键（单一命名空间 `window.*`，双语各一枚，缺键即测试红）。 */
export const WINDOW_LABEL_KEYS: Record<GraphWindowCode, string> = {
  '24h': 'window.24h',
  '7d': 'window.7d',
  '30d': 'window.30d',
  all: 'window.all',
};

/** 桶标签的 i18n 键前缀（现存 `calls.bucket.*`：两页共用，是唯一一份桶标签表）。 */
export const BUCKET_LABEL_KEYS: Record<BucketCode, string> = {
  hour: 'calls.bucket.hour',
  day: 'calls.bucket.day',
};

/** i18next `t` 的最小签名（各取词函数共用；禁再各处手写）。 */
export type Translate = (key: string) => string;

/** 窗口 → 人话标签（唯一取词口）。 */
export function windowLabel(t: Translate, code: GraphWindowCode): string {
  return t(WINDOW_LABEL_KEYS[code]);
}

/** 桶 → 人话标签。 */
export function bucketLabel(t: Translate, code: BucketCode): string {
  return t(BUCKET_LABEL_KEYS[code]);
}

/**
 * 桶翻转（calls 页单按钮两态）：hour ↔ day。
 * 表外值一律回缺省桶——不抛、不猜（后端只认这两个值，认别的等于把 422 送上生产）。
 */
export function nextBucket(current: BucketCode): BucketCode {
  return current === 'hour' ? 'day' : DEFAULT_BUCKET;
}
