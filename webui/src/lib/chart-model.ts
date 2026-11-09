// 图表纯函数模型（零依赖，零 React）。所有手写 SVG 图表的几何/刻度都从这里取，
// 组件只负责把数字贴到 SVG 上。
//
// 为什么判据住在 lib 而不是 .tsx：比例尺算错一格，折线就画到画布外面，
// 而 svg 会**静默裁剪**——页面看起来"就是没数据"，谁也不会怀疑比例尺。
// 本文件可被 `node --test` 直接加载（同 console.test.ts / route-path.test.ts 约定）。
import { formatNumber } from './format.ts';
import type { UnitSystem } from './appearance/types';

/** 图表调色板档位：对应 index.css 的 --chart-1 … --chart-6（主题化唯一入口）。 */export const CHART_TOKENS = [1, 2, 3, 4, 5, 6] as const;
export type ChartToken = (typeof CHART_TOKENS)[number];

/** 档位 → CSS 变量表达式。组件里**只许**经此函数取色，禁写 hex/oklch 字面量。 */
export function chartColor(token: ChartToken): string {
  return `var(--chart-${token})`;
}

/** 第 i 条序列的档位（循环复用六档；序列数 ≤ 6 时各不相同）。 */
export function seriesToken(index: number): ChartToken {
  return CHART_TOKENS[((index % CHART_TOKENS.length) + CHART_TOKENS.length) % CHART_TOKENS.length];
}

// ============================================================================
// 比例尺
// ============================================================================

export interface LinearScale {
  (value: number): number;
  domain: readonly [number, number];
  range: readonly [number, number];
  invert(pixel: number): number;
}

export interface BandScale {
  (value: string | number): number;
  readonly step: number;
  readonly bandwidth: number;
  /** 第 i 个元素的左上角像素（与输入值无关的下标定位，供柱/热力格用）。 */
  at(index: number): number;
  domain: readonly (string | number)[];
}

export interface Domain {
  min: number;
  max: number;
}

/**
 * 线性比例尺。domain 退化（min===max）时向两侧各撑开 1，
 * 否则 range 会被 0 除成 ±Infinity 或 NaN，整条路径静默消失。
 */
export function linearScale(domain: Domain, range: readonly [number, number]): LinearScale {
  let { min, max } = domain;
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    min = 0;
    max = 1;
  }
  if (min === max) {
    // 单值序列画在中间线：撑开 ±1 比画在底边更诚实（底边看起来像"归零"）。
    const pad = Math.abs(min) || 1;
    min -= pad;
    max += pad;
  }
  const [r0, r1] = range;
  const span = max - min;
  const scale = ((value: number) => r0 + ((value - min) / span) * (r1 - r0)) as LinearScale;
  scale.domain = Object.freeze([min, max] as const) as unknown as readonly [number, number];
  scale.range = Object.freeze([r0, r1] as const) as unknown as readonly [number, number];
  scale.invert = (pixel: number) => min + ((pixel - r0) / (r1 - r0)) * span;
  return scale;
}

/** 数值带（分类轴）：总宽均分，留 innerPadding 比例作间隙，余下即 bandwidth。 */
export function bandScale(
  domain: readonly (string | number)[],
  range: readonly [number, number],
  innerPadding = 0.2
): BandScale {
  const [r0, r1] = range;
  const count = domain.length;
  const total = r1 - r0;
  const step = count > 0 ? total / count : 0;
  const pad = Math.min(Math.max(innerPadding, 0), 0.9);
  const bandwidth = step * (1 - pad);
  const index = new Map<string, number>();
  domain.forEach((value, i) => index.set(String(value), i));
  const at = (i: number) => r0 + step * i + (step - bandwidth) / 2;
  const scale = ((value: string | number) => {
    const i = index.get(String(value));
    return at(i ?? 0);
  }) as BandScale;
  Object.defineProperty(scale, 'step', { value: step, enumerable: true });
  Object.defineProperty(scale, 'bandwidth', { value: bandwidth, enumerable: true });
  Object.defineProperty(scale, 'at', { value: at, enumerable: true });
  Object.defineProperty(scale, 'domain', { value: Object.freeze([...domain]), enumerable: true });
  return scale;
}

// ============================================================================
// 刻度
// ============================================================================

/**
 * "好看"的刻度：步长取 {1,2,2.5,5,10}×10^n。
 * 目标约 target 条（含首尾），返回值严格落在 [min,max] 内并按升序。
 */
export function niceTicks(min: number, max: number, target = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || target < 1) return [];
  if (min > max) [min, max] = [max, min];
  if (min === max) return [min];
  const rough = (max - min) / target;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  const niceStep = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const first = Math.ceil(min / niceStep) * niceStep;
  const out: number[] = [];
  // 浮点累加会漂（0.30000000000000004），用乘法定位并按步长取整。
  for (let k = 0; ; k += 1) {
    const value = first + k * niceStep;
    if (value > max + niceStep * 1e-9) break;
    out.push(Number(value.toFixed(10)));
    if (out.length > 1000) break; // 病态输入兜底，不成环
  }
  return out;
}

/** 时间轴刻度：给定 ISO 时间序列，按 bucket 粒度挑出"整点/整日"位置（返回下标）。 */
export function timeTickIndexes(times: readonly string[], bucket: 'hour' | 'day', max = 6): number[] {
  const count = times.length;
  if (count === 0) return [];
  const stamps = times.map((t) => Date.parse(t));
  if (stamps.some((s) => Number.isNaN(s))) return evenTickIndexes(count, max);
  // 优先取自然边界（整点=分钟为 0；整日=当地 0 点），落不到足够多时退回等距。
  const isEdge = (ms: number) => {
    const d = new Date(ms);
    return bucket === 'day' ? d.getHours() === 0 : d.getMinutes() === 0;
  };
  const edges = stamps.map((s, i) => (isEdge(s) ? i : -1)).filter((i) => i >= 0);
  if (edges.length >= 2) return thin(edges, max);
  return evenTickIndexes(count, max);
}

/**
 * 时间轴下标：优先用**整齐的步长**（1/2/3/4/6/8/12/24/48/72/168 个桶一跳），
 * 而不是把 (count-1) 机械均分。24 个整点桶均分 6 条会得到 00:00/05:00/09:00/14:00…
 * 这种读不出规律的刻度；按 6 桶一跳则是 00:00/06:00/12:00/18:00，最后补一个 23:00。
 * 条数上限 max；首尾必出，返回值升序去重。
 */
export function niceTickIndexes(count: number, max = 6): number[] {
  if (count <= 0) return [];
  if (count === 1) return [0];
  const limit = Math.max(2, Math.floor(max));
  const steps = [1, 2, 3, 4, 6, 8, 12, 16, 24, 48, 72, 168];
  const last = count - 1;
  let step = steps[steps.length - 1];
  for (const candidate of steps) {
    // 末位单独补一条，因此内部刻度数按 floor(last/step)+1 计，再加首尾的 1 条。
    const inner = Math.floor(last / candidate) + 1;
    if (inner + (last % candidate === 0 ? 0 : 1) <= limit) {
      step = candidate;
      break;
    }
  }
  const out: number[] = [];
  for (let index = 0; index <= last; index += step) out.push(index);
  if (out[out.length - 1] !== last) out.push(last);
  return out.slice(0, Math.max(limit, 2));
}

/** 等距下标（首尾必出，最多 max 条）。 */
export function evenTickIndexes(count: number, max = 6): number[] {
  if (count <= 0) return [];
  if (count === 1) return [0];
  const n = Math.min(Math.max(Math.floor(max), 2), count);
  const out: number[] = [];
  for (let i = 0; i < n; i += 1) out.push(Math.round((i * (count - 1)) / (n - 1)));
  return [...new Set(out)];
}

function thin(indexes: readonly number[], max: number): number[] {
  const n = Math.min(Math.max(Math.floor(max), 2), indexes.length);
  if (indexes.length <= n) return [...indexes];
  const out: number[] = [];
  for (let i = 0; i < n; i += 1) {
    out.push(indexes[Math.round((i * (indexes.length - 1)) / (n - 1))]);
  }
  return [...new Set(out)];
}

// ============================================================================
// 路径生成
// ============================================================================

export interface Point {
  x: number;
  y: number;
}

const fmt = (n: number): string => (Number.isFinite(n) ? String(Math.round(n * 100) / 100) : '0');

/** 折线路径；points 不足 2 点时返回空串（单点请用散点/圆点，别画一条零长度线）。 */
export function linePath(points: readonly Point[]): string {
  if (points.length < 2) return '';
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${fmt(p.x)} ${fmt(p.y)}`).join(' ');
}

/**
 * 平滑曲线：Catmull-Rom → 三次贝塞尔（张力 1/6，与 d3.curveCatmullRom 同款）。
 * 单调性不保证是刻意的——折线图要看真实拐点，平滑只服务观感；
 * 需要"不越界"的场合请用 linePath。
 */
export function smoothPath(points: readonly Point[]): string {
  if (points.length < 2) return '';
  if (points.length === 2) return linePath(points);
  const d: string[] = [`M${fmt(points[0].x)} ${fmt(points[0].y)}`];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d.push(`C${fmt(c1x)} ${fmt(c1y)} ${fmt(c2x)} ${fmt(c2y)} ${fmt(p2.x)} ${fmt(p2.y)}`);
  }
  return d.join(' ');
}

/** 面积闭合：折线（或平滑线）首尾接到 baselineY 上闭合成可填充的多边形。 */
export function areaPath(points: readonly Point[], baselineY: number, smooth = false): string {
  if (points.length < 2) return '';
  const top = smooth ? smoothPath(points) : linePath(points);
  const last = points[points.length - 1];
  const first = points[0];
  return `${top} L${fmt(last.x)} ${fmt(baselineY)} L${fmt(first.x)} ${fmt(baselineY)} Z`;
}

/** 柱形矩形（y 向下增长，负值/0 高度给 1px 兜底，免得整根消失）。 */
export function barRect(x: number, y: number, width: number, height: number): { x: number; y: number; width: number; height: number } {
  const w = Math.max(width, 0);
  const h = Math.max(height, 1);
  return { x, y, width: w, height: h };
}

export interface Arc {
  /** SVG path 的 d 属性。 */
  d: string;
  /** 弧长（供 stroke-dasharray 动画用；刻度 = 半径角 arc）。 */
  length: number;
}

/**
 * 环形扇区。角度从 12 点方向起顺时针（SVG 里 y 向下，故 sin 取 -）。
 * startAngle/endAngle 单位是**弧度**，调用方先做比例换算。
 */
export function arcPath(cx: number, cy: number, rInner: number, rOuter: number, startAngle: number, endAngle: number): Arc {
  const sweep = endAngle - startAngle;
  const length = Math.abs(sweep) * rOuter;
  if (Math.abs(sweep) < 1e-9) return { d: '', length: 0 };
  // 整圆拆两段画：单条 A 指令首尾重合会被渲染成空路径。
  const full = Math.abs(sweep) >= Math.PI * 2 - 1e-9;
  const end = full ? startAngle + Math.PI : endAngle;
  const largeArc = Math.abs(end - startAngle) > Math.PI ? 1 : 0;
  const dir = sweep > 0 ? 1 : 0;
  const pt = (radius: number, angle: number) => `${fmt(cx + radius * Math.sin(angle))} ${fmt(cy - radius * Math.cos(angle))}`;
  const d = [
    `M${pt(rOuter, startAngle)}`,
    `A${fmt(rOuter)} ${fmt(rOuter)} 0 ${largeArc} ${dir} ${pt(rOuter, end)}`,
    `L${pt(rInner, end)}`,
    `A${fmt(rInner)} ${fmt(rInner)} 0 ${largeArc} ${dir === 1 ? 0 : 1} ${pt(rInner, startAngle)}`,
    'Z',
  ].join(' ');
  if (!full) return { d, length };
  // 剩下那半圈补上，形成真正闭合的双半圆环。
  const mid = startAngle + Math.PI;
  const d2 = [
    `M${pt(rOuter, mid)}`,
    `A${fmt(rOuter)} ${fmt(rOuter)} 0 0 ${dir} ${pt(rOuter, startAngle)}`,
    `L${pt(rInner, startAngle)}`,
    `A${fmt(rInner)} ${fmt(rInner)} 0 0 ${dir === 1 ? 0 : 1} ${pt(rInner, mid)}`,
    'Z',
  ].join(' ');
  return { d: `${d} ${d2}`, length: Math.abs(sweep) * rOuter };
}

/** 半圆弧（仪表盘用）：从 9 点方向扫到 3 点方向，fraction∈[0,1]。 */
export function gaugeArc(cx: number, cy: number, radius: number, fraction: number): Arc {
  const clamped = Math.min(Math.max(Number.isFinite(fraction) ? fraction : 0, 0), 1);
  const end = -Math.PI / 2 + Math.PI * clamped;
  const len = Math.PI * radius * clamped;
  if (clamped <= 0) return { d: '', length: 0 };
  const start = -Math.PI / 2;
  const pt = (angle: number) => `${fmt(cx + radius * Math.sin(angle))} ${fmt(cy - radius * Math.cos(angle))}`;
  return {
    d: `M${pt(start)} A${fmt(radius)} ${fmt(radius)} 0 ${clamped > 0.5 ? 1 : 0} 1 ${pt(end)}`,
    length: len,
  };
}

// ============================================================================
// 堆叠累积
// ============================================================================

export interface StackSeries {
  key: string;
  label: string;
  values: readonly (number | null)[];
  /** 覆盖色档；缺省按序列下标取 --chart-N。 */
  token?: ChartToken;
}

export interface StackSegment {
  key: string;
  label: string;
  token: ChartToken;
  /** 该段在堆叠轴上的起点与终点（同一坐标系，已累加）。 */
  start: number;
  end: number;
  value: number;
}

/**
 * 堆叠累积。null/NaN 视为 0（缺数据不当作负值，也不把整列打断）。
 * 返回逐列逐序列的段清单，顺序与输入序列一致（画的时候后画的在上方）。
 */
export function stackSeries(series: readonly StackSeries[]): StackSegment[][] {
  if (series.length === 0) return [];
  const length = Math.max(...series.map((s) => s.values.length));
  const columns: StackSegment[][] = [];
  for (let i = 0; i < length; i += 1) {
    const column: StackSegment[] = [];
    let acc = 0;
    series.forEach((s, si) => {
      const raw = s.values[i];
      const value = raw === null || raw === undefined || !Number.isFinite(raw) ? 0 : raw;
      column.push({
        key: s.key,
        label: s.label,
        token: s.token ?? seriesToken(si),
        start: acc,
        end: acc + value,
        value,
      });
      acc += value;
    });
    columns.push(column);
  }
  return columns;
}

/** 堆叠后的列合计（给 y 轴定 domain 用）。 */
export function stackTotals(series: readonly StackSeries[]): number[] {
  return stackSeries(series).map((column) => column.reduce((sum, seg) => sum + seg.value, 0));
}

/** 百分比堆叠：每列归一到 100（全零列原样留零，不造假）。 */
export function stackPercent(series: readonly StackSeries[]): StackSeries[] {
  const totals = stackTotals(series);
  return series.map((s) => ({
    ...s,
    values: s.values.map((v, i) => {
      const total = totals[i];
      const base = v === null || v === undefined || !Number.isFinite(v) ? 0 : v;
      return total > 0 ? (base / total) * 100 : 0;
    }),
  }));
}

// ============================================================================
// 数据适配（后端真实形状 → 图表输入）
// ============================================================================

/** CallsData['trend'] 的 items → 折线点（时间是字符串，数值是 calls）。 */
export function trendPoints(trend: { items: Array<{ bucket_start: string; calls: number }> }): {
  times: string[];
  values: number[];
} {
  const times: string[] = [];
  const values: number[] = [];
  for (const item of trend.items) {
    times.push(item.bucket_start);
    values.push(Number.isFinite(item.calls) ? item.calls : 0);
  }
  return { times, values };
}

/** `CallsData['trend_by_user']` 的形状：**稀疏**交叉表（只含有调用的格子）。 */
export interface TrendByUser {
  top_users: ReadonlyArray<{ user: string; calls: number }>;
  other_label?: string;
  items: ReadonlyArray<{ bucket_start: string; user: string; calls: number }>;
}

/**
 * 人 × 时段交叉表 → 多条折线，**每条都对齐整条横轴**。
 *
 * 后端只吐有调用的格子（稀疏），横轴由 `trend.items` 给全——所以这里必须把稀疏表
 * 铺回 `times`：不铺就少画点，铺错就整条线静默错位（同 `tokenSeries` 的教训）。
 * 图例顺序＝`top_users` 顺序（后端已按次数降序），「其他」永远排最后。
 * 窗口内一次都没调用的人不出列——一条贴地的假线比不画更容易被误读。
 * 交叉表里冒出来但 `top_users` 没列的 id 一并归「其他」，绝不为陌生 id 另起一列。
 */
export function trendByUserSeries(
  trendByUser: TrendByUser | null | undefined,
  times: readonly string[]
): Array<{ key: string; label: string; values: number[] }> {
  const axis = times ?? [];
  if (!trendByUser || axis.length === 0) return [];
  const other = String(trendByUser.other_label ?? '其他');
  const named: string[] = [];
  for (const row of trendByUser.top_users ?? []) {
    const user = String(row.user ?? '');
    if (user && user !== other && !named.includes(user)) named.push(user);
  }
  const at = new Map<string, number>();
  axis.forEach((stamp, index) => {
    if (!at.has(stamp)) at.set(stamp, index);
  });
  const cells = new Map<string, number[]>();
  for (const item of trendByUser.items ?? []) {
    const user = String(item.user ?? '');
    const index = at.get(String(item.bucket_start ?? ''));
    if (index === undefined || !user) continue;
    const series = named.includes(user) ? user : other;
    let values = cells.get(series);
    if (!values) {
      values = new Array<number>(axis.length).fill(0);
      cells.set(series, values);
    }
    const calls = Number(item.calls);
    values[index] += Number.isFinite(calls) ? calls : 0;
  }
  const hasData = (user: string) => (cells.get(user) ?? []).some((value) => value > 0);
  const order = named.filter(hasData);
  if (hasData(other)) order.push(other);
  return order.map((user) => ({ key: user, label: user, values: cells.get(user) as number[] }));
}

/** `CallsData['coverage']` 的形状：轴多长、几个桶真有数据、真实数据跨度。 */
export interface TrendCoverage {
  available_buckets?: number;
  requested_buckets?: number;
  first_data_at?: string | null;
  last_data_at?: string | null;
}

/**
 * 数据可用性缺口 → 一句必须说的话（不负责文案，只给事实）。
 *
 * 为什么要它：审计库按行数剪枝，生产实测 1000 行只剩 48 分钟、2 个桶；而 24h 轴铺满
 * 25 格。**轴铺满不等于数据够**——不显式说明，这张图会被读成「一整天的完整趋势」。
 * `minutes` 是两个真实数据点之间的跨度（不是轴宽），缺任一端就是 null（不编）。
 */
export function trendCoverageGap(coverage?: TrendCoverage | null): {
  incomplete: boolean;
  minutes: number | null;
} {
  if (!coverage) return { incomplete: false, minutes: null };
  const requested = Number(coverage.requested_buckets);
  const available = Number(coverage.available_buckets);
  const incomplete =
    Number.isFinite(requested) && requested > 0 && Number.isFinite(available) && available < requested;
  const start = Date.parse(String(coverage.first_data_at ?? ''));
  const end = Date.parse(String(coverage.last_data_at ?? ''));
  const minutes =
    Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? Math.round((end - start) / 60_000)
      : null;
  return { incomplete, minutes };
}

/** LatencyData['items'] → 散点（横轴=样本数，纵轴=EMA 延迟），缺延迟的通道剔除。 */
export function latencyScatter(items: readonly { channel: string; ema_ms: number | null; samples: number }[]): Array<{
  label: string;
  x: number;
  y: number;
}> {
  return items
    .filter((item) => item.ema_ms !== null && Number.isFinite(item.ema_ms))
    .map((item) => ({ label: item.channel, x: item.samples, y: item.ema_ms as number }));
}

/**
 * TokensData.families → 堆叠序列（input/output/cache_read/cache_creation 四段）。
 *
 * 口径取自 api-client.ts 的真身 `TokenBlock`：`{ value, known_rows, unknown_rows, quality }`，
 * 其中 `value` 可以是 **null**（后端没报数）。null 直接透传给 stackSeries 当 0 处理——
 * 图上表现为"这一段没有高度"，而不是编一个 0 去冒充"确实用了 0 个 token"。
 * 🔴 别把 `value` 读成 `total`：TokenBlock 没有 total 字段，读错会让整图静默全零。
 */
export function tokenSeries(families: readonly {
  family: string | null;
  tokens: {
    input: { value: number | null };
    output: { value: number | null };
    cache_read: { value: number | null };
    cache_creation: { value: number | null };
  };
}[]): StackSeries[] {
  const pick = (key: 'input' | 'output' | 'cache_read' | 'cache_creation', label: string): StackSeries => ({
    key,
    label,
    values: families.map((f) => (f.tokens?.[key] ? f.tokens[key].value : null)),
  });
  return [pick('input', '输入'), pick('output', '输出'), pick('cache_read', '缓存读'), pick('cache_creation', '缓存写')];
}

/** 环形图分段：把 {label,value} 列表归一成累计角度（弧度），值 ≤0 的项剔除。 */
export function donutSegments(entries: readonly { label: string; value: number }[]): Array<{
  label: string;
  value: number;
  share: number;
  startAngle: number;
  endAngle: number;
  token: ChartToken;
}> {
  const usable = entries.filter((e) => Number.isFinite(e.value) && e.value > 0);
  const total = usable.reduce((sum, e) => sum + e.value, 0);
  if (total <= 0) return [];
  let angle = 0;
  return usable.map((entry, i) => {
    const share = entry.value / total;
    const startAngle = angle;
    angle += share * Math.PI * 2;
    return { label: entry.label, value: entry.value, share, startAngle, endAngle: angle, token: seriesToken(i) };
  });
}

/** 热力图矩阵：行（如小时 0-23）× 列（如星期 0-6）→ 单元格强度 [0,1]。 */
export function heatmapCells(
  rows: number,
  cols: number,
  value: (row: number, col: number) => number
): { row: number; col: number; value: number; intensity: number }[] {
  const cells: { row: number; col: number; value: number; intensity: number }[] = [];
  let max = 0;
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      const v = value(r, c);
      const safe = Number.isFinite(v) && v > 0 ? v : 0;
      if (safe > max) max = safe;
      cells.push({ row: r, col: c, value: safe, intensity: 0 });
    }
  }
  // 归一到全矩阵最大值；全空矩阵强度保持 0（不编造"到处都是浅色"）。
  if (max > 0) for (const cell of cells) cell.intensity = cell.value / max;
  return cells;
}

// ============================================================================
// 坐标轴 / 标签几何（手写 SVG 的"高端感"全在这几件上）
// ============================================================================

/**
 * y 轴 domain：从 0 撑到"好看的"最大刻度。返回的 max 一定等于末条刻度，
 * 这样网格线顶格、柱顶有呼吸位，不会出现"最高柱贴着画布上沿"的穷酸相。
 * 全零序列给 0–1 两根线（不编造数据，但也不留一张空白画布）。
 */
export function niceDomain(max: number, target = 4): { max: number; ticks: number[] } {
  const safe = Number.isFinite(max) && max > 0 ? max : 0;
  if (safe === 0) return { max: 1, ticks: [0, 1] };
  const ticks = niceTicks(0, safe, target);
  if (ticks.length < 2) return { max: safe, ticks: [0, safe] };
  // niceTicks 只回 ≤ max 的刻度（271 → 0/100/200），末刻度并不覆盖真实峰值。
  // 往上补一整格再重算，否则最高柱会顶出画布上沿（旧实现的实际病）。
  const step = ticks[1] - ticks[0];
  const extended = Math.ceil(safe / step) * step;
  const full = niceTicks(0, extended, target);
  if (full.length < 2) return { max: extended, ticks: [0, extended] };
  return { max: full[full.length - 1], ticks: full };
}

/**
 * 文本宽度估算（px）。**不量真实像素**——SVG 里没有 canvas 也能算，
 * 且首帧就能算出左侧标签栏宽度（量真实像素要等一帧，会看到标签跳一下）。
 * 系数按常见无衬线字体标定：CJK/全角=1em，窄字符≈0.32em，大写/宽字符≈0.72em。
 * 只用于**留白与换行决策**，差一两个像素不影响正确性。
 */
export function measureLabelWidth(text: string, fontPx: number): number {
  let units = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    if (code > 0x2e80) units += 1;
    else if (ch === ' ') units += 0.3;
    else if (/[iIl1.,:;'|!]/.test(ch)) units += 0.32;
    else if (/[A-Z@%&#MWmw]/.test(ch)) units += 0.72;
    else units += 0.58;
  }
  return units * fontPx;
}

/** 把一行文字截到宽度内（留一个省略号的位置）。 */
function clipLine(text: string, maxWidth: number, fontPx: number): string {
  if (measureLabelWidth(text, fontPx) <= maxWidth) return text;
  const chars = [...text];
  while (chars.length > 1 && measureLabelWidth(`${chars.join('')}…`, fontPx) > maxWidth) chars.pop();
  return `${chars.join('')}…`;
}

/**
 * 分类名换行：优先在 `- _ . / : · 空格` 后断，断不下才硬切。
 * 最多 maxLines 行；仍放不下的尾巴进最后一行并带省略号。
 * 调用方必须把**全名**同时写进 `<title>`（可视省略不等于信息丢失）。
 */
export function wrapLabel(
  text: string,
  maxWidth: number,
  fontPx: number,
  maxLines = 2
): { lines: string[]; clipped: boolean } {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return { lines: [], clipped: false };
  if (!(maxWidth > 0) || measureLabelWidth(clean, fontPx) <= maxWidth) {
    return { lines: [clean], clipped: false };
  }
  const limit = Math.max(1, Math.floor(maxLines));
  // 分隔符保留在前一段末尾：`gemini-3-` / `flash-preview` 比 `gemini-3` / `-flash` 好读。
  const segments = clean.match(/[^-_./:·\s]+[-_./:·\s]*/g) ?? [clean];
  const lines: string[] = [];
  let current = '';
  const flush = () => {
    if (current) lines.push(current.trim());
    current = '';
  };
  for (const segment of segments) {
    const candidate = current + segment;
    if (measureLabelWidth(candidate, fontPx) <= maxWidth) {
      current = candidate;
      continue;
    }
    flush();
    if (measureLabelWidth(segment, fontPx) <= maxWidth) {
      current = segment;
      continue;
    }
    // 单个片段超宽：按字符硬切（长 hash / 无分隔符的标识符）。
    let chunk = '';
    for (const ch of segment) {
      if (measureLabelWidth(chunk + ch, fontPx) > maxWidth && chunk) {
        lines.push(chunk);
        chunk = ch;
      } else {
        chunk += ch;
      }
    }
    current = chunk;
  }
  flush();
  if (lines.length <= limit) return { lines, clipped: false };
  const head = lines.slice(0, limit - 1);
  const tail = clipLine(lines.slice(limit - 1).join(''), maxWidth, fontPx);
  return { lines: [...head, tail], clipped: true };
}

/**
 * 指针 → 最近的数据点下标（折线图的十字准星用）。
 * plotWidth ≤ 0 或单点时返回 0，绝不返回 NaN（NaN 会让整块 hover 层消失）。
 */
export function indexFromPointer(pointerX: number, plotLeft: number, plotWidth: number, count: number): number {
  if (!(count > 0)) return 0;
  if (count === 1 || !(plotWidth > 0)) return 0;
  const ratio = (pointerX - plotLeft) / plotWidth;
  const index = Math.round(ratio * (count - 1));
  return Math.min(count - 1, Math.max(0, index));
}

/**
 * 时间标签：**直接从 ISO 字面量切片**，不经过 `new Date()` 转本地时区。
 * 后端 bucket_start 已带业务时区偏移（如 +08:00），再转一次本地时区会整体漂移，
 * 出现"14 点的调用画在 06 点"这种没人能看出来源的时间错位。
 */
export function formatTimeLabel(value: string, bucket: 'hour' | 'day' | 'auto' = 'auto'): string {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const hour = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(text);
  if (bucket !== 'day' && hour) return `${hour[4]}:${hour[5]}`;
  const day = /^(\d{4})-(\d{2})-(\d{2})/.exec(text);
  if (day) return `${day[2]}/${day[3]}`;
  return text;
}

/**
 * 柱形路径：只给**该圆的那一头**倒角（竖向柱圆顶、横向条圆右端），
 * 堆叠时只有最顶上一段是圆的——全段倒角会看出"一串香肠"。
 * 半径自动收敛到短边的一半，极细柱不会画成畸形。
 */
export function barPath(
  x: number,
  y: number,
  width: number,
  height: number,
  radius = 4,
  side: 'top' | 'right' | 'none' = 'top'
): string {
  const w = Math.max(width, 0);
  const h = Math.max(height, 0);
  const r = Math.max(0, Math.min(radius, w / 2, h / 2));
  if (w <= 0 || h <= 0) return '';
  if (side === 'none' || r < 0.5) return `M${fmt(x)} ${fmt(y)}h${fmt(w)}v${fmt(h)}h${fmt(-w)}Z`;
  if (side === 'top') {
    return [
      `M${fmt(x)} ${fmt(y + h)}`,
      `L${fmt(x)} ${fmt(y + r)}`,
      `Q${fmt(x)} ${fmt(y)} ${fmt(x + r)} ${fmt(y)}`,
      `L${fmt(x + w - r)} ${fmt(y)}`,
      `Q${fmt(x + w)} ${fmt(y)} ${fmt(x + w)} ${fmt(y + r)}`,
      `L${fmt(x + w)} ${fmt(y + h)}`,
      'Z',
    ].join(' ');
  }
  return [
    `M${fmt(x)} ${fmt(y)}`,
    `L${fmt(x + w - r)} ${fmt(y)}`,
    `Q${fmt(x + w)} ${fmt(y)} ${fmt(x + w)} ${fmt(y + r)}`,
    `L${fmt(x + w)} ${fmt(y + h - r)}`,
    `Q${fmt(x + w)} ${fmt(y + h)} ${fmt(x + w - r)} ${fmt(y + h)}`,
    `L${fmt(x)} ${fmt(y + h)}`,
    'Z',
  ].join(' ');
}

/**
 * 数值标签（图例/数值标注用；不靠颜色表意）。
 *
 * 🔴 这里**不再自算一套**：单位档统一由 `format.ts` 的 `formatNumber` 裁决
 * （compact 1.2K / chinese 1.2万 / plain 1,234），缺省跟随外观「语言与格式」。
 * 收口前本函数把 1234 写成 `1,234`、12345 写成 `1.2万`——同一张图上两种口径混排。
 * `unitSystem` 只在需要固定档位时显式传（图表轴线可用 compact，卡片可用 chinese）。
 */
export function formatValue(value: number, unitSystem?: UnitSystem): string {
  return formatNumber(value, unitSystem ? { unitSystem } : undefined);
}
