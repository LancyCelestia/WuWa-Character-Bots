import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { CallsData, LatencyData, TokensData } from './api-client.ts';
import {
  CHART_TOKENS,
  areaPath,
  arcPath,
  bandScale,
  barPath,
  barRect,
  chartColor,
  donutSegments,
  evenTickIndexes,
  formatTimeLabel,
  formatValue,
  gaugeArc,
  heatmapCells,
  indexFromPointer,
  latencyScatter,
  linePath,
  linearScale,
  measureLabelWidth,
  niceDomain,
  niceTickIndexes,
  niceTicks,
  seriesToken,
  smoothPath,
  stackPercent,
  stackSeries,
  stackTotals,
  timeTickIndexes,
  tokenSeries,
  trendByUserSeries,
  trendCoverageGap,
  trendPoints,
  wrapLabel,
} from './chart-model.ts';

/**
 * 图表纯函数锁。
 *
 * 为什么这些判定要住在 lib 而不是 .tsx：比例尺/路径算错一格，SVG 会**静默裁剪**——
 * 页面看起来只是"没数据"，没人会怀疑比例尺。判据住组件里=没有判据（同 console.test.ts 教训）。
 * 本文件零 React 依赖，node --test 直接加载。数据形状全部取 api-client.ts 的真类型。
 */

// ---------- 真实数据夹具（与 api-client.ts 契约同形） ----------

const CALLS: CallsData = {
  window: '24h',
  total_calls: 137,
  unknown_timestamp_calls: 2,
  unattributed_calls: 5,
  user_attribution: 'session_owner',
  active_users: 3,
  last_message_at: '2026-09-19T10:05:00Z',
  by_session: [
    { session: 'group:114514', calls: 90 },
    { session: null, calls: 5 },
  ],
  by_user: [{ user: 'u-1', calls: 60 }],
  by_capability: [
    { capability: 'chat', calls: 100 },
    { capability: null, calls: 37 },
  ],
  trend: {
    bucket: 'hour',
    timezone: 'Asia/Shanghai',
    items: [
      { bucket_start: '2026-09-19T00:00:00+08:00', calls: 0 },
      { bucket_start: '2026-09-19T01:00:00+08:00', calls: 3 },
      { bucket_start: '2026-09-19T02:00:00+08:00', calls: 12 },
      { bucket_start: '2026-09-19T03:00:00+08:00', calls: 7 },
      { bucket_start: '2026-09-19T04:00:00+08:00', calls: 41 },
    ],
  },
};

const LATENCY: LatencyData = {
  items: [
    { channel: 'primary', state: 'closed', consecutive_fails: 0, latency_ms: 412, ema_ms: 430.5, samples: 120, last_ok_at: '2026-09-19T10:00:00Z', last_error: null },
    { channel: 'fallback', state: 'half_open', consecutive_fails: 2, latency_ms: null, ema_ms: null, samples: 0, last_ok_at: '2026-09-18T10:00:00Z', last_error: 'timeout' },
    { channel: 'backup', state: 'closed', consecutive_fails: 0, latency_ms: 998, ema_ms: 1200, samples: 8, last_ok_at: '2026-09-19T09:00:00Z', last_error: null },
  ],
  history: { status: 'unavailable', reason: 'no_samples' },
};

/** 造一枚真身 TokenBlock（api-client.ts:287 的 { value, known_rows, unknown_rows, quality }）。 */
const block = (value: number | null): TokensData['totals']['tokens']['input'] => ({
  value,
  known_rows: value === null ? 0 : 1,
  unknown_rows: value === null ? 1 : 0,
  quality: value === null ? 'unknown' : 'complete',
});

const TOKENS: TokensData = {
  window: '24h',
  totals: {
    family: null,
    calls: 137,
    tokens: {
      input: block(5200),
      output: block(900),
      cache_read: block(100),
      cache_creation: block(40),
    },
  },
  families: [
    {
      family: 'gpt-x',
      calls: 100,
      tokens: {
        input: block(5000),
        output: block(800),
        cache_read: block(60),
        cache_creation: block(20),
      },
    },
    {
      family: null,
      calls: 37,
      tokens: {
        input: block(200),
        output: block(100),
        cache_read: block(40),
        cache_creation: block(20),
      },
    },
  ],
};

// ---------- 调色板：颜色只能走 CSS 变量 ----------

test('chartColor 只产出 var(--chart-N)，六档循环且不外泄 hex', () => {
  for (const token of CHART_TOKENS) {
    const color = chartColor(token);
    assert.equal(color, `var(--chart-${token})`);
    assert.doesNotMatch(color, /#|rgb|oklch/i, '禁字面色值');
  }
  assert.equal(seriesToken(0), 1);
  assert.equal(seriesToken(5), 6);
  assert.equal(seriesToken(6), 1, '第 7 条序列回到第 1 档');
  assert.equal(seriesToken(-1), 6, '负下标不得丢出 undefined');
});

// ---------- 线性比例尺 ----------

test('linearScale 把 domain 端点钉到 range 端点（折线不会画出画布）', () => {
  const y = linearScale({ min: 0, max: 100 }, [200, 0]);
  assert.equal(y(0), 200);
  assert.equal(y(100), 0);
  assert.equal(y(50), 100);
  assert.equal(y.invert(100), 50, 'invert 与正变换互逆（tooltip 用）');
});

test('linearScale 退化 domain 撑开 ±1，单值序列落在中线而非底边', () => {
  const y = linearScale({ min: 7, max: 7 }, [100, 0]);
  assert.equal(y(7), 50);
  assert.ok(Number.isFinite(y(7)));
  const z = linearScale({ min: 0, max: 0 }, [100, 0]);
  assert.equal(z(0), 50, '全零序列也不能被 0 除成 NaN');
});

test('linearScale 的 domain 是非有限数时退回 [0,1]（不产 NaN 坐标）', () => {
  const y = linearScale({ min: Number.NaN, max: 10 }, [0, 100]);
  const pixel = y(5);
  assert.ok(Number.isFinite(pixel));
});

// ---------- 数值带 ----------

test('bandScale 均分并按 innerPadding 留缝，at() 按下标定位', () => {
  const x = bandScale(['a', 'b', 'c', 'd'], [0, 400], 0.2);
  assert.equal(x.step, 100);
  assert.equal(x.bandwidth, 80);
  assert.equal(x.at(0), 10);
  assert.equal(x.at(3), 310);
  assert.equal(x('c'), 210);
  assert.equal(x('不存在'), x.at(0), '未知分类落到首格，不产 NaN');
});

test('bandScale 空 domain 不崩（step/bandwidth 归零）', () => {
  const x = bandScale([], [0, 400]);
  assert.equal(x.step, 0);
  assert.equal(x.bandwidth, 0);
  assert.ok(Number.isFinite(x.at(0)));
});

// ---------- 刻度 ----------

test('niceTicks 产出整齐步长且全部落在 domain 内', () => {
  const ticks = niceTicks(0, 137, 5);
  assert.ok(ticks.length >= 3 && ticks.length <= 8, `条数应接近 target，实见 ${ticks.length}`);
  assert.equal(ticks[0], 0);
  assert.ok(ticks[ticks.length - 1] <= 137);
  for (let i = 1; i < ticks.length; i += 1) {
    assert.ok(ticks[i] > ticks[i - 1], '严格升序');
  }
  // 步长必须一致（"好看"的定义就是我们统一间距）
  const gap = ticks[1] - ticks[0];
  for (let i = 1; i < ticks.length; i += 1) {
    assert.ok(Math.abs(ticks[i] - ticks[i - 1] - gap) < 1e-9);
  }
});

test('niceTicks 浮点不漂（步长 0.2 这类不出 0.30000000000000004）', () => {
  const ticks = niceTicks(0, 1, 5);
  for (const t of ticks) {
    assert.ok(String(t).length <= 6, `刻度 ${t} 带浮点噪声`);
  }
});

test('niceTicks 退化/反向/非有限输入不崩', () => {
  assert.deepEqual(niceTicks(5, 5), [5]);
  assert.deepEqual(niceTicks(10, 0), niceTicks(0, 10), '反向区间自动纠正');
  assert.deepEqual(niceTicks(Number.NaN, 10), []);
  assert.deepEqual(niceTicks(0, 10, 0), []);
});

test('timeTickIndexes 优先落自然整点，落不到就等距', () => {
  const times = CALLS.trend.items.map((i) => i.bucket_start);
  const idx = timeTickIndexes(times, 'hour', 6);
  assert.ok(idx.length >= 2);
  assert.ok(idx.every((i) => i >= 0 && i < times.length));
  // 全部是整点 → 允许等距退回，但不能空
  assert.equal(evenTickIndexes(5, 6).length, 5);
  assert.deepEqual(evenTickIndexes(1, 6), [0]);
  assert.deepEqual(timeTickIndexes(['坏时间', '也坏'], 'hour'), [0, 1], '时间不可解析时退回等距');
});

test('evenTickIndexes 首尾必出且不重复', () => {
  const idx = evenTickIndexes(24, 6);
  assert.equal(idx[0], 0);
  assert.equal(idx[idx.length - 1], 23);
  assert.equal(new Set(idx).size, idx.length);
});

// ---------- 路径 ----------

test('linePath 少于两点返回空串（单点请画圆，不画零长度线）', () => {
  assert.equal(linePath([]), '');
  assert.equal(linePath([{ x: 1, y: 2 }]), '');
  assert.equal(linePath([{ x: 0, y: 10 }, { x: 50, y: 0 }]), 'M0 10 L50 0');
});

test('linePath 逐点必达（不漏点、不四舍五入到错位）', () => {
  const points = [
    { x: 0, y: 100 },
    { x: 33.333, y: 66.667 },
    { x: 66.666, y: 12.345 },
    { x: 100, y: 0 },
  ];
  const d = linePath(points);
  assert.equal((d.match(/[ML]/g) || []).length, points.length);
  assert.match(d, /^M0 100/);
  assert.ok(d.includes('33.33 66.67'), `坐标保留两位，实得 ${d}`);
});

test('smoothPath 用三次贝塞尔，点数=段数；两点退化为直线', () => {
  const pts = [
    { x: 0, y: 10 },
    { x: 10, y: 0 },
    { x: 20, y: 10 },
    { x: 30, y: 0 },
  ];
  const d = smoothPath(pts);
  assert.match(d, /^M0 10/);
  assert.equal((d.match(/C/g) || []).length, pts.length - 1);
  assert.equal(smoothPath([{ x: 0, y: 0 }, { x: 10, y: 10 }]), 'M0 0 L10 10');
});

test('areaPath 首尾都落到 baseline 上并闭合（渐变填充不会漏底）', () => {
  const pts = [
    { x: 0, y: 10 },
    { x: 50, y: 0 },
    { x: 100, y: 20 },
  ];
  const d = areaPath(pts, 100);
  assert.ok(d.startsWith('M0 10'));
  assert.ok(d.includes('L100 100'), '末点先接到基线');
  assert.ok(d.includes('L0 100'), '首点回到基线');
  assert.ok(d.endsWith('Z'), '必须闭合');
  assert.equal(areaPath([{ x: 0, y: 0 }], 100), '');
});

test('barRect 高度兜底 1px（零值柱不整根消失）且宽度不为负', () => {
  const r = barRect(10, 50, 20, 0);
  assert.equal(r.height, 1);
  assert.equal(r.width, 20);
  assert.equal(barRect(0, 0, -5, 10).width, 0, '负宽收敛到 0，不产非法 SVG');
});

// ---------- 环形 / 仪表 ----------

test('arcPath 单扇区从 12 点起顺时针，弧长与角度成比例', () => {
  const quarter = arcPath(50, 50, 30, 40, 0, Math.PI / 2);
  assert.ok(quarter.d.startsWith('M50 10'), `应从顶点起笔，实得 ${quarter.d}`);
  assert.ok(quarter.d.endsWith('Z'));
  assert.ok(Math.abs(quarter.length - (Math.PI / 2) * 40) < 1e-6);
  assert.equal(arcPath(50, 50, 30, 40, 1, 1).d, '', '零角度不产路径');
});

test('arcPath 整圆拆两段（单条 A 首尾重合会被渲染成空）', () => {
  const full = arcPath(50, 50, 30, 40, 0, Math.PI * 2);
  assert.equal((full.d.match(/M/g) || []).length, 2);
});

test('gaugeArc 半圆：0=无路径，0.5=正上方，1=满弧', () => {
  assert.equal(gaugeArc(100, 100, 80, 0).d, '');
  const half = gaugeArc(100, 100, 80, 0.5);
  assert.ok(half.d.includes('100 20'), `半程应到顶点，实得 ${half.d}`);
  const full = gaugeArc(100, 100, 80, 1);
  assert.ok(Math.abs(full.length - Math.PI * 80) < 1e-6);
  assert.equal(gaugeArc(100, 100, 80, 2).length, full.length, 'fraction 超界钳到 1');
  assert.equal(gaugeArc(100, 100, 80, Number.NaN).d, '');
});

// ---------- 堆叠 ----------

test('stackSeries 逐列累加，null/NaN 当 0 不打断列', () => {
  const series = [
    { key: 'a', label: 'A', values: [1, null, 3] },
    { key: 'b', label: 'B', values: [2, 5, Number.NaN] },
  ];
  const columns = stackSeries(series);
  assert.equal(columns.length, 3);
  assert.deepEqual(
    columns[0].map((s) => [s.start, s.end]),
    [[0, 1], [1, 3]]
  );
  assert.deepEqual(
    columns[1].map((s) => [s.start, s.end]),
    [[0, 0], [0, 5]],
    'null 段占位但不贡献高度'
  );
  assert.deepEqual(
    columns[2].map((s) => [s.start, s.end]),
    [[0, 3], [3, 3]],
    'NaN 段落在顶但不加高'
  );
  assert.deepEqual(stackTotals(series), [3, 5, 3]);
});

test('stackSeries 空输入不崩', () => {
  assert.deepEqual(stackSeries([]), []);
  assert.deepEqual(stackTotals([]), []);
});

test('stackPercent 每列归一到 100，全零列留 0 不造假', () => {
  const pct = stackPercent([
    { key: 'a', label: 'A', values: [1, 0] },
    { key: 'b', label: 'B', values: [3, 0] },
  ]);
  assert.equal(pct[0].values[0], 25);
  assert.equal(pct[1].values[0], 75);
  assert.deepEqual(
    pct.map((s) => s.values[1]),
    [0, 0],
    '总量为 0 的列不许被归一成 100/0'
  );
});

test('stackSeries 段色走 seriesToken（堆叠各层不撞色）', () => {
  const columns = stackSeries([
    { key: 'a', label: 'A', values: [1] },
    { key: 'b', label: 'B', values: [1] },
    { key: 'c', label: 'C', values: [1] },
  ]);
  assert.deepEqual(
    columns[0].map((s) => s.token),
    [1, 2, 3]
  );
});

// ---------- 真实数据适配 ----------

test('trendPoints 吃 CallsData.trend 原形，坏值归零不产 NaN', () => {
  const { times, values } = trendPoints(CALLS.trend);
  assert.equal(times.length, 5);
  assert.deepEqual(values, [0, 3, 12, 7, 41]);
  const dirty = trendPoints({ items: [{ bucket_start: '2026-09-19T00:00:00Z', calls: Number.NaN }] });
  assert.deepEqual(dirty.values, [0]);
  assert.deepEqual(trendPoints({ items: [] }), { times: [], values: [] });
});

/**
 * `trend_by_user` 是**稀疏**交叉表（只吐有调用的格子）：横轴由 trend.items 给全，
 * 所以这里必须把它铺回整条轴——不铺就少画点，画错就整条线错位。
 */
const CROSS = {
  bucket: 'hour' as const,
  timezone: 'Asia/Shanghai',
  top_users: [
    { user: '20001', calls: 40 },
    { user: '20002', calls: 9 },
  ],
  other_label: '其他',
  items: [
    { bucket_start: '2026-09-19T01:00:00+08:00', user: '20001', calls: 3 },
    { bucket_start: '2026-09-19T04:00:00+08:00', user: '20001', calls: 37 },
    { bucket_start: '2026-09-19T02:00:00+08:00', user: '20002', calls: 9 },
    { bucket_start: '2026-09-19T03:00:00+08:00', user: '其他', calls: 7 },
  ],
};

test('trendUserSeries 把稀疏交叉表铺回横轴（缺格=0，不产 NaN）', () => {
  const times = CALLS.trend.items.map((i) => i.bucket_start);
  const series = trendByUserSeries(CROSS, times);
  assert.deepEqual(
    series.map((s) => s.label),
    ['20001', '20002', '其他'],
    '图例顺序＝top_users 顺序，「其他」永远最后'
  );
  assert.deepEqual(series[0].values, [0, 3, 0, 0, 37]);
  assert.deepEqual(series[1].values, [0, 0, 9, 0, 0]);
  assert.deepEqual(series[2].values, [0, 0, 0, 7, 0]);
  // 每列长度必须与横轴一致，否则折线会静默错位。
  assert.ok(series.every((s) => s.values.length === times.length));
});

test('trendUserSeries 缺席/空表返回空序列（前端据此走降级文案，不假装有）', () => {
  assert.deepEqual(trendByUserSeries(undefined, ['2026-09-19T00:00:00+08:00']), []);
  assert.deepEqual(trendByUserSeries(null, []), []);
  assert.deepEqual(trendByUserSeries({ top_users: [], items: [] }, ['a']), []);
});

test('trendUserSeries 全零/坏值的人不出列（不画一条贴地的假线）', () => {
  const series = trendByUserSeries(
    {
      top_users: [{ user: 'u1', calls: 1 }],
      items: [{ bucket_start: 'k', user: 'u1', calls: Number.NaN }],
    },
    ['k']
  );
  assert.deepEqual(series, []);
});

/**
 * 数据可用性：生产审计库只剩 48 分钟（2 个桶），24h 轴却有 25 个桶——
 * 这种「2 个点铺在 25 格轴上」必须被显式说出来，否则图看起来像一条完整趋势。
 */
test('trendCoverageGap 只在轴没被数据铺满时告警，跨度按真实数据点算', () => {
  // 生产实测形状：48 分钟、2 个桶、25 格轴。
  const gap = trendCoverageGap({
    available_buckets: 2,
    requested_buckets: 25,
    first_data_at: '2026-10-19T11:47:20+00:00',
    last_data_at: '2026-10-19T12:35:25+00:00',
  });
  assert.equal(gap.incomplete, true);
  assert.equal(gap.minutes, 48);
  // 轴铺满 → 不告警。
  assert.deepEqual(trendCoverageGap({ available_buckets: 25, requested_buckets: 25 }), {
    incomplete: false,
    minutes: null,
  });
  // 旧控制面没有 coverage 块 / 空轴：不告警，也不编跨度。
  assert.deepEqual(trendCoverageGap(undefined), { incomplete: false, minutes: null });
  assert.deepEqual(trendCoverageGap({ available_buckets: 0, requested_buckets: 0 }), {
    incomplete: false,
    minutes: null,
  });
});

// ---------- 时间轴刻度

test('24 个连续小时桶的刻度首末必出（能读出几点到几点）', () => {
  // 连续时间轴的前提：桶与下标一一对应，差 8 个下标＝差 8 小时。
  assert.deepEqual(niceTickIndexes(24, 4), [0, 8, 16, 23]);
  for (const max of [2, 3, 4, 6, 8]) {
    const idx = niceTickIndexes(24, max);
    assert.equal(idx[0], 0, `max=${max} 缺首桶`);
    assert.equal(idx[idx.length - 1], 23, `max=${max} 缺末桶`);
  }
});

test('latencyScatter 剔除无 EMA 的通道（缺数据不画成 0ms）', () => {
  const points = latencyScatter(LATENCY.items);
  assert.equal(points.length, 2, 'fallback 的 ema_ms=null 必须剔除');
  assert.deepEqual(points[0], { label: 'primary', x: 120, y: 430.5 });
  assert.deepEqual(points[1], { label: 'backup', x: 8, y: 1200 });
});

test('tokenSeries 读 TokenBlock.value 而不是 total（读错会让整图静默全零）', () => {
  const series = tokenSeries(TOKENS.families);
  assert.deepEqual(
    series.map((s) => s.key),
    ['input', 'output', 'cache_read', 'cache_creation']
  );
  assert.deepEqual(series[0].values, [5000, 200]);
  // 5000+800+60+20＝5880；200+100+40+20＝360（四段全上，不挑挑拣拣）
  assert.deepEqual(stackTotals(series), [5880, 360]);
});

test('tokenSeries 的 value=null 透传为 null（不编造 0 冒充"确实用了 0 个 token"）', () => {
  const series = tokenSeries([
    {
      family: 'x',
      tokens: { input: block(null), output: block(7), cache_read: block(null), cache_creation: block(null) },
    },
  ]);
  assert.deepEqual(series[0].values, [null], 'input 缺数必须是 null，不是 0');
  assert.deepEqual(series[1].values, [7]);
  // 堆叠时 null 当 0 占位（画面上"这段没高度"），合计仍是 7
  assert.deepEqual(stackTotals(series), [7]);
});

test('tokenSeries 对缺 tokens 分块的家族不崩（旧后端缺字段）', () => {
  const series = tokenSeries([
    { family: 'x', tokens: { input: block(5) } as unknown as TokensData['families'][number]['tokens'] },
  ]);
  assert.deepEqual(series[0].values, [5]);
  // 缺整块 → null（"后端没报"，不是"用了 0 个"）。堆叠时按 0 占位。
  assert.equal(series[1].values[0], null);
  assert.deepEqual(stackTotals(series), [5]);
});

test('donutSegments 归一角度、剔除 ≤0 项、角度累计闭合', () => {
  const segs = donutSegments([
    { label: '成功', value: 90 },
    { label: '失败', value: 10 },
    { label: '空', value: 0 },
    { label: '负', value: -3 },
  ]);
  assert.equal(segs.length, 2, '0 与负值不上环');
  assert.equal(segs[0].startAngle, 0);
  assert.ok(Math.abs(segs[0].share - 0.9) < 1e-9);
  assert.ok(Math.abs(segs[segs.length - 1].endAngle - Math.PI * 2) < 1e-9, '末段必须闭环');
  assert.deepEqual(donutSegments([{ label: '全零', value: 0 }]), [], '全零不产环');
});

test('heatmapCells 归一到最大值；全空矩阵强度保持 0', () => {
  const cells = heatmapCells(2, 3, (r, c) => r * 3 + c);
  assert.equal(cells.length, 6);
  const max = cells.find((c) => c.row === 1 && c.col === 2);
  assert.equal(max?.intensity, 1);
  assert.equal(cells.find((c) => c.row === 0 && c.col === 0)?.intensity, 0);
  const empty = heatmapCells(2, 2, () => 0);
  assert.ok(empty.every((c) => c.intensity === 0), '没有数据时不许画出"到处都有"的假热区');
});

test('heatmapCells 对负值与 NaN 收敛到 0', () => {
  const cells = heatmapCells(1, 3, (_r, c) => (c === 0 ? -5 : c === 1 ? Number.NaN : 4));
  assert.deepEqual(
    cells.map((c) => c.value),
    [0, 0, 4]
  );
});

// ---------- 数值标签 ----------

// ---------- 轴几何 / 标签（V 席重做新增） ----------

test('niceDomain 顶格：domain.max 必等于末条刻度，网格不会悬空', () => {
  const d = niceDomain(271, 4);
  assert.equal(d.max, d.ticks[d.ticks.length - 1]);
  assert.ok(d.max >= 271, 'domain 必须覆盖真实最大值');
  assert.equal(d.ticks[0], 0, '计数轴从 0 起');
  const flat = niceDomain(0);
  assert.deepEqual(flat.ticks, [0, 1], '全零给 0–1 两根线，不留空白画布');
});

test('niceDomain 对负值/NaN 收敛到 0 域（不同 -Infinity 画轴）', () => {
  assert.deepEqual(niceDomain(Number.NaN).ticks, [0, 1]);
  assert.deepEqual(niceDomain(-40).ticks, [0, 1]);
});

test('measureLabelWidth：CJK 比同字数 ASCII 宽，空串为 0，随字号线性缩放', () => {
  assert.equal(measureLabelWidth('', 12), 0);
  assert.ok(measureLabelWidth('调用次数', 11) > measureLabelWidth('calls', 11));
  const a = measureLabelWidth('gemini-3-flash', 11);
  assert.ok(Math.abs(measureLabelWidth('gemini-3-flash', 22) - a * 2) < 1e-6);
  assert.ok(a > 60 && a < 140, `11px 下 14 字符应在 60–140px，实得 ${a}`);
});

test('wrapLabel 放得下就一行；放不下按分隔符断成两行且不丢前缀', () => {
  assert.deepEqual(wrapLabel('grok-4.6', 200, 11), { lines: ['grok-4.6'], clipped: false });
  const wrapped = wrapLabel('gemini-3-flash-preview', 78, 11, 2);
  assert.equal(wrapped.lines.length, 2);
  assert.ok(wrapped.lines[0].startsWith('gemini'), `首行保留可辨识前缀，实得 ${wrapped.lines[0]}`);
  assert.ok(wrapped.lines.join('').replace(/…|-$/g, '').length >= 12, '两行合起来要保留大部分原名');
});

test('wrapLabel 超长且无分隔符时硬切并标 clipped（绝不原样溢出容器）', () => {
  const long = 'a'.repeat(80);
  const out = wrapLabel(long, 40, 11, 2);
  assert.equal(out.lines.length, 2);
  assert.ok(out.clipped);
  assert.ok(out.lines[1].endsWith('…'));
  for (const line of out.lines) assert.ok(measureLabelWidth(line, 11) <= 40 + 1e-6);
});

test('wrapLabel 空文本/零宽不崩（分类名缺省时不留幽灵行）', () => {
  assert.deepEqual(wrapLabel('   ', 80, 11), { lines: [], clipped: false });
  assert.equal(wrapLabel('abc', 0, 11).lines.length, 1);
});

test('barPath 只圆指定那一头；半径被短边钳住；零尺寸给空串', () => {
  const top = barPath(10, 20, 40, 100, 6, 'top');
  assert.match(top, /^M10 120/, '从柱底左角起笔');
  assert.match(top, /Q10 20 16 20/, '左上角倒角');
  assert.ok(!top.includes('Q50 120'), '柱底两角必须是直角');
  const right = barPath(10, 20, 100, 14, 6, 'right');
  assert.match(right, /Q110 20 110 26/);
  assert.equal(barPath(10, 20, 0, 30), '');
  const thin = barPath(0, 0, 4, 30, 40, 'top');
  assert.match(thin, /Q0 0 2 0/, '半径收敛到短边一半（≤2）');
});

test('indexFromPointer 四舍五入到最近点并夹在两端（不产 NaN）', () => {
  assert.equal(indexFromPointer(0, 0, 100, 5), 0);
  assert.equal(indexFromPointer(100, 0, 100, 5), 4);
  assert.equal(indexFromPointer(51, 0, 100, 5), 2);
  assert.equal(indexFromPointer(-999, 10, 200, 7), 0);
  assert.equal(indexFromPointer(999, 10, 200, 7), 6);
  assert.equal(indexFromPointer(Number.NaN, 0, 0, 3), 0);
  assert.equal(indexFromPointer(5, 0, 100, 1), 0);
  assert.equal(indexFromPointer(5, 0, 100, 0), 0);
});

test('niceTickIndexes 走整齐步长：24 个整点桶给 00/06/12/18，末尾补 23', () => {
  assert.deepEqual(niceTickIndexes(24, 6), [0, 6, 12, 18, 23]);
  assert.deepEqual(niceTickIndexes(24, 7), [0, 4, 8, 12, 16, 20, 23]);
  assert.deepEqual(niceTickIndexes(5, 6), [0, 1, 2, 3, 4], '点数少于上限时逐点标');
  assert.deepEqual(niceTickIndexes(1, 6), [0]);
  assert.deepEqual(niceTickIndexes(0, 6), []);
});

test('niceTickIndexes 首尾必出、升序、不超上限（含窄屏只给两条的极端）', () => {
  for (const count of [2, 7, 24, 30, 90, 365]) {
    const indexes = niceTickIndexes(count, 6);
    assert.equal(indexes[0], 0);
    assert.equal(indexes[indexes.length - 1], count - 1);
    assert.equal(new Set(indexes).size, indexes.length, '不重复');
    assert.deepEqual([...indexes].sort((a, b) => a - b), indexes, '升序');
    assert.ok(indexes.length <= 6, `count=${count} 实得 ${indexes.length} 条`);
  }
  assert.deepEqual(niceTickIndexes(24, 2), [0, 23], '窄屏只留首尾');
});

test('formatTimeLabel 直接切 ISO 字面量（不转本地时区导致整体漂移）', () => {
  assert.equal(formatTimeLabel('2026-10-18T14:00:00+08:00', 'hour'), '14:00');
  assert.equal(formatTimeLabel('2026-10-18T14:00:00Z', 'hour'), '14:00', 'Z 也按字面量显示，不做时区换算');
  assert.equal(formatTimeLabel('2026-10-18T14:00:00+08:00', 'day'), '10/18');
  assert.equal(formatTimeLabel('2026-10-18', 'hour'), '10/18', '只有日期时退回日标签');
  assert.equal(formatTimeLabel('坏时间', 'hour'), '坏时间', '不可解析原样返回，不编造');
  assert.equal(formatTimeLabel('', 'hour'), '');
});

test('formatValue 走统一数字层：三档各自可锁，非有限值给未知符', () => {
  // 档位显式传入＝把「图例/轴标签用哪一档」也钉死；缺省档跟随外观设置（由 format.ts 接缝管）。
  assert.equal(formatValue(999, 'compact'), '999');
  assert.equal(formatValue(1234, 'plain'), '1,234');
  assert.equal(formatValue(1234, 'compact'), '1.2K');
  assert.equal(formatValue(12345, 'chinese'), '1.2万');
  assert.equal(formatValue(150000, 'chinese'), '15万');
  assert.equal(formatValue(2.5e8, 'chinese'), '2.5亿');
  assert.equal(formatValue(2.5e8, 'compact'), '250M');
  assert.equal(formatValue(Number.NaN, 'chinese'), '—');
  assert.equal(formatValue(Number.POSITIVE_INFINITY, 'chinese'), '—');
});
