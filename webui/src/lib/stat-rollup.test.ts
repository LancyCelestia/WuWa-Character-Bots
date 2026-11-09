// 统计聚合纯函数的机器尺（W3 席）。
//
// 为什么这批函数值得单独锁：图表上最容易撒的谎不是「算错」，而是**形状看起来对**——
// 空桶补零让「没有数据」和「有数据但为零」长得一样；changeRate 分母忘了绝对值让负值
// 之间的一降被画成「涨 150%」而实际是「跌」；percentile 顺手 sort 了入参让调用方
// 随后读到一份被偷换的数组。这三类都不会抛错，只会安静地误导，所以每一条都要有
// 指名的测试盯着。
//
// 时区：全库一律**本地时区**（getFullYear/getMonth/getDate/getHours/getMinutes），
// 不用 getUTC*。本机实测 TZ=Asia/Singapore（UTC+8），但下面构造样本一律走
// `new Date(y, m, d, h).getTime()` 这种本地构造，所以断言在任何 TZ 下都成立。
//
// 运行：node --test src/lib/stat-rollup.test.ts（Node 原生类型剥离，零新依赖）。
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  UNKNOWN_KEY,
  attributionCoverage,
  changeRate,
  countBy,
  dailyBuckets,
  halfHourBuckets,
  latestPair,
  median,
  parseSession,
  percentile,
  recentDeltas,
  rollupAffinity,
  userStats,
  type AffinityDeltaRow,
  type RollupBucket,
} from './stat-rollup.ts';

// ---------------------------------------------------------------------------
// 夹具
// ---------------------------------------------------------------------------

/** 本地时刻 → unix 秒（带小数，与 affinity_delta_log.applied_at 同形态）。 */
const at = (y: number, m: number, d: number, h = 12, min = 0): number =>
  new Date(y, m - 1, d, h, min, 0, 0).getTime() / 1000;

const row = (applied_at: number, delta: number, sender_id: string): AffinityDeltaRow => ({
  applied_at,
  delta,
  sender_id,
});

/** 造一个只关心 delta 的桶序列。 */
const buckets = (...deltas: number[]): RollupBucket[] =>
  deltas.map((delta, i) => ({ key: `k${i}`, startMs: i * 86_400_000, delta, events: 1, users: 1 }));

// ---------------------------------------------------------------------------
// rollupAffinity：桶键与归段
// ---------------------------------------------------------------------------

test('rollupAffinity daily：跨两天 3 行 → 2 个桶，delta 各自正确，键形 YYYY-MM-DD', () => {
  const out = rollupAffinity(
    [
      row(at(2026, 10, 18, 1, 28), 3, 'u1'),
      row(at(2026, 10, 18, 23, 59), -1, 'u2'),
      row(at(2026, 10, 19, 9, 15), 5, 'u1'),
    ],
    'daily'
  );
  assert.equal(out.length, 2);
  for (const b of out) assert.match(b.key, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(out[0].key, '2026-10-18');
  assert.equal(out[0].delta, 2);
  assert.equal(out[0].events, 2);
  assert.equal(out[0].users, 2);
  assert.equal(out[1].key, '2026-10-19');
  assert.equal(out[1].delta, 5);
  assert.equal(out[1].users, 1);
});

test('rollupAffinity daily：startMs 归到本地当天 00:00:00.000', () => {
  const [b] = rollupAffinity([row(at(2026, 10, 19, 9, 15), 5, 'u1')], 'daily');
  const midnight = new Date(2026, 9, 19, 0, 0, 0, 0).getTime();
  assert.equal(b.startMs, midnight);
});

test('rollupAffinity：空输入 → []', () => {
  assert.deepEqual(rollupAffinity([], 'daily'), []);
  assert.deepEqual(rollupAffinity([], 'total'), []);
});

test('rollupAffinity：不改入参', () => {
  const rows = [row(at(2026, 10, 19, 9), 1, 'u1'), row(at(2026, 10, 18, 9), 2, 'u2')];
  const snapshot = rows.map((r) => ({ ...r }));
  rollupAffinity(rows, 'daily');
  assert.deepEqual(rows, snapshot);
});

test('rollupAffinity weekly：跨周边界 → 2 个桶，键形 YYYY-Www', () => {
  // 2026-10-18 周日属 2026-W42（周一起算），2026-10-19 周一进 W43。
  const out = rollupAffinity(
    [row(at(2026, 10, 18, 23), 1, 'u1'), row(at(2026, 10, 19, 0, 1), 2, 'u1')],
    'weekly'
  );
  assert.equal(out.length, 2);
  for (const b of out) assert.match(b.key, /^\d{4}-W\d{2}$/);
  assert.notEqual(out[0].key, out[1].key);
});

test('rollupAffinity weekly：startMs 落在本地周一 00:00:00.000', () => {
  const [b] = rollupAffinity([row(at(2026, 10, 17, 9), 1, 'u1')], 'weekly'); // 周六
  assert.equal(new Date(b.startMs).getDay(), 1);
  assert.equal(new Date(b.startMs).getHours(), 0);
  assert.equal(new Date(b.startMs).getDate(), 12); // 2026-10-12 是周一
});

test('rollupAffinity weekly：ISO 跨年归属（2027-01-01 属 2026-W53，不是 2027-W01）', () => {
  // 2026-12-28 起的那一周延伸到 2027-01-03；ISO 8601 规定这一周归它的年份 = 2026。
  assert.equal(rollupAffinity([row(at(2027, 1, 1, 9), 1, 'u1')], 'weekly')[0].key, '2026-W53');
  // 2027-01-04 是周一，才进入 2027-W01。
  assert.equal(rollupAffinity([row(at(2027, 1, 4, 9), 1, 'u1')], 'weekly')[0].key, '2027-W01');
});

test('rollupAffinity weekly：ISO 跨年另一侧（2021-01-01 属 2020-W53）', () => {
  assert.equal(rollupAffinity([row(at(2021, 1, 1, 9), 1, 'u1')], 'weekly')[0].key, '2020-W53');
  // 反向：2020-12-28（周一）就已是 2020-W53，与上面同桶。
  assert.equal(rollupAffinity([row(at(2020, 12, 28, 9), 1, 'u1')], 'weekly')[0].key, '2020-W53');
});

test('rollupAffinity monthly：键形 YYYY-MM，同月合并', () => {
  const out = rollupAffinity(
    [row(at(2026, 9, 30, 23), 4, 'u1'), row(at(2026, 10, 1, 0, 5), 6, 'u2'), row(at(2026, 10, 19, 9), -2, 'u1')],
    'monthly'
  );
  assert.equal(out.length, 2);
  for (const b of out) assert.match(b.key, /^\d{4}-\d{2}$/);
  assert.equal(out[0].key, '2026-09');
  assert.equal(out[1].key, '2026-10');
  assert.equal(out[1].delta, 4);
  assert.equal(out[1].events, 2);
  assert.equal(out[1].users, 2);
});

test('rollupAffinity monthly：startMs 归到本地当月 1 日 00:00:00.000', () => {
  const [b] = rollupAffinity([row(at(2026, 10, 19, 9), 1, 'u1')], 'monthly');
  assert.equal(b.startMs, new Date(2026, 9, 1, 0, 0, 0, 0).getTime());
});

test('rollupAffinity yearly：键形 YYYY', () => {
  const out = rollupAffinity([row(at(2025, 12, 31, 23), 1, 'u1'), row(at(2026, 1, 1, 0, 1), 2, 'u1')], 'yearly');
  assert.equal(out.length, 2);
  for (const b of out) assert.match(b.key, /^\d{4}$/);
  assert.deepEqual(out.map((b) => b.key), ['2025', '2026']);
});

test('rollupAffinity yearly：startMs 归到本地 1 月 1 日 00:00:00.000', () => {
  const [b] = rollupAffinity([row(at(2026, 10, 19, 9), 1, 'u1')], 'yearly');
  assert.equal(b.startMs, new Date(2026, 0, 1, 0, 0, 0, 0).getTime());
});

test('rollupAffinity total：单桶 key=all / startMs=0 / 合计·行数·去重用户', () => {
  const out = rollupAffinity(
    [
      row(at(2026, 10, 18, 1), 3, 'u1'),
      row(at(2026, 10, 19, 2), -1, 'u2'),
      row(at(2026, 10, 20, 3), 5, 'u1'),
    ],
    'total'
  );
  assert.equal(out.length, 1);
  assert.equal(out[0].key, 'all');
  assert.equal(out[0].startMs, 0);
  assert.equal(out[0].delta, 7);
  assert.equal(out[0].events, 3);
  assert.equal(out[0].users, 2);
});

test('rollupAffinity：空桶不补零 —— 「今天」与「三天后」只出 2 个桶', () => {
  const today = at(2026, 10, 19, 9);
  const out = rollupAffinity([row(today, 1, 'u1'), row(today + 3 * 86_400, 2, 'u1')], 'daily');
  assert.equal(out.length, 2, '中间两天没有事件，就不许出现这两个桶');
  assert.equal(out[1].startMs - out[0].startMs, 3 * 86_400_000);
});

test('rollupAffinity：乱序输入 → 输出按 startMs 升序', () => {
  const out = rollupAffinity(
    [
      row(at(2026, 10, 20, 9), 3, 'u1'),
      row(at(2026, 10, 18, 9), 1, 'u1'),
      row(at(2026, 10, 19, 9), 2, 'u1'),
    ],
    'daily'
  );
  assert.deepEqual(out.map((b) => b.key), ['2026-10-18', '2026-10-19', '2026-10-20']);
  for (let i = 1; i < out.length; i += 1) assert.ok(out[i].startMs > out[i - 1].startMs);
});

// ---------------------------------------------------------------------------
// changeRate / latestPair / recentDeltas
// ---------------------------------------------------------------------------

test('changeRate：120 对 100 → 20', () => {
  assert.equal(changeRate(120, 100), 20);
});

test('changeRate：80 对 100 → -20', () => {
  assert.equal(changeRate(80, 100), -20);
});

test('changeRate：50 对 -100 → 150（分母必须 Math.abs，否则得 -150）', () => {
  assert.equal(changeRate(50, -100), 150);
  assert.equal(changeRate(-50, -100), 50, '负数继续变负也是「涨 50%」');
});

test('changeRate：上一桶为 0 / null / undefined → null（不是 0 也不是 Infinity）', () => {
  assert.equal(changeRate(100, 0), null);
  assert.equal(changeRate(100, null), null);
  assert.equal(changeRate(100, undefined), null);
});

test('changeRate：保留一位小数（四舍五入）', () => {
  assert.equal(changeRate(100, 3), 3233.3);
});

test('latestPair：空序列 → { current: 0, previous: null }', () => {
  assert.deepEqual(latestPair([]), { current: 0, previous: null });
});

test('latestPair：单桶 → 上一为 null；两桶 → 取最后两个 delta', () => {
  assert.deepEqual(latestPair(buckets(7)), { current: 7, previous: null });
  assert.deepEqual(latestPair(buckets(1, 2, 3)), { current: 3, previous: 2 });
});

test('recentDeltas：取最后 N 个；N 大于长度返回全部且不补零', () => {
  const b = buckets(1, 2, 3, 4);
  assert.deepEqual(recentDeltas(b, 2), [3, 4]);
  assert.deepEqual(recentDeltas(b, 10), [1, 2, 3, 4]);
  assert.deepEqual(recentDeltas([], 3), []);
  assert.deepEqual(recentDeltas(b, 0), []);
});

// ---------------------------------------------------------------------------
// percentile / median
// ---------------------------------------------------------------------------

test('percentile：空数组 → null', () => {
  assert.equal(percentile([], 50), null);
});

test('percentile：最近秩法 —— P50=3 / P100=5 / P0=1', () => {
  assert.equal(percentile([1, 2, 3, 4, 5], 50), 3);
  assert.equal(percentile([1, 2, 3, 4, 5], 100), 5);
  assert.equal(percentile([1, 2, 3, 4, 5], 0), 1);
});

test('percentile：不做线性插值（[1,2,3,4] 的 P50 是 2，不是 2.5）', () => {
  assert.equal(percentile([1, 2, 3, 4], 50), 2);
  assert.equal(percentile([1, 2, 3, 4], 90), 4);
});

test('percentile：不改入参顺序（[5,1,3] 排完仍原样）', () => {
  const values = [5, 1, 3];
  assert.equal(percentile(values, 50), 3);
  assert.deepEqual(values, [5, 1, 3]);
});

test('median：中位数走 percentile(50)，偶数取最近秩下位', () => {
  assert.equal(median([4, 1, 3]), 3);
  assert.equal(median([4, 1, 3, 2]), 2);
  assert.equal(median([]), null);
});

// ---------------------------------------------------------------------------
// parseSession / attributionCoverage / userStats
// ---------------------------------------------------------------------------

test("parseSession：纯数字 → 用户", () => {
  assert.deepEqual(parseSession('3865067623'), { kind: 'user', id: '3865067623' });
});

test('parseSession：group_<群号>_<QQ号> → 群会话', () => {
  assert.deepEqual(parseSession('group_11088380_1250727173'), {
    kind: 'group',
    groupId: '11088380',
    userId: '1250727173',
  });
});

test('parseSession：空串 / null / undefined / 非数字非群 / 段不足 → unknown', () => {
  for (const input of ['', null, undefined, 'admin:onebot', 'runtime', 'email:noreply@example.com', 'group_', 'group_1', 'group__2']) {
    assert.deepEqual(parseSession(input), { kind: 'unknown' }, `输入 ${JSON.stringify(input)} 应判 unknown`);
  }
});

test('attributionCoverage：4 行 2 行可归属 → 0.5；空数组 → null', () => {
  const rows = [
    { session_id: '3865067623' },
    { session_id: 'group_11088380_1250727173' },
    { session_id: '' },
    { session_id: 'runtime' },
  ];
  assert.equal(attributionCoverage(rows), 0.5);
  assert.equal(attributionCoverage([]), null);
});

test('userStats：2 用户（2 次+1 次）→ activeUsers=2、topDecileShare≈2/3', () => {
  const rows = [
    { session_id: '111' },
    { session_id: '111' },
    { session_id: 'group_900_222' },
  ];
  const s = userStats(rows);
  assert.equal(s.activeUsers, 2);
  assert.ok(s.topDecileShare !== null && Math.abs(s.topDecileShare - 2 / 3) < 1e-9);
  // 每用户计数 [1,2]：最近秩法 P50 落在秩 1（=1），P90 落在秩 2（=2）——不是插值的 1.5。
  assert.equal(s.callsPerUserMedian, 1);
  assert.equal(s.callsPerUserP90, 2);
});

test('userStats：同一 QQ 号的私聊与群会话合并成一个用户', () => {
  const s = userStats([{ session_id: '111' }, { session_id: 'group_900_111' }, { session_id: 'group_900_222' }]);
  assert.equal(s.activeUsers, 2, 'group_900_111 与 111 是同一人，合并后只剩 2 个用户');
  assert.equal(s.callsPerUserMedian, 1);
  assert.equal(s.callsPerUserP90, 2);
});


test('userStats：不可归属行不进分母', () => {
  const s = userStats([{ session_id: '111' }, { session_id: 'admin:onebot' }, { session_id: '' }]);
  assert.equal(s.activeUsers, 1);
  assert.equal(s.topDecileShare, 1);
});

test('userStats：空数组 → activeUsers=0，其余三个 null', () => {
  assert.deepEqual(userStats([]), {
    activeUsers: 0,
    topDecileShare: null,
    callsPerUserMedian: null,
    callsPerUserP90: null,
  });
});

test('userStats：用户数过 10 才真的取 Top 10%（不足 10 人取 Top 1）', () => {
  // 12 个用户，各 1 次 → ceil(12*0.1)=2 个头部用户 → 2/12。
  const rows = Array.from({ length: 12 }, (_, i) => ({ session_id: String(1000 + i) }));
  const s = userStats(rows);
  assert.equal(s.activeUsers, 12);
  assert.ok(s.topDecileShare !== null && Math.abs(s.topDecileShare - 2 / 12) < 1e-9);
});

// ---------------------------------------------------------------------------
// halfHourBuckets / dailyBuckets / countBy
// ---------------------------------------------------------------------------

test('halfHourBuckets：:00 与 :30 各一桶（本地时区）', () => {
  const out = halfHourBuckets(['2026-10-19T20:13:16.780+08:00', '2026-10-19T20:45:00.000+08:00']);
  assert.equal(out.length, 2);
  const d = new Date('2026-10-19T20:13:16.780+08:00');
  const pad = (n: number) => String(n).padStart(2, '0');
  const head = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
  assert.deepEqual(out.map((b) => b.key), [`${head}:00`, `${head}:30`]);
  assert.deepEqual(out.map((b) => b.count), [1, 1]);
});

test('halfHourBuckets：解析失败的行跳过、不抛错', () => {
  const out = halfHourBuckets(['not-a-date', '', '2026-10-19T20:13:16.780+08:00']);
  assert.equal(out.length, 1);
  assert.equal(out[0].count, 1);
  assert.deepEqual(halfHourBuckets(['not-a-date']), []);
});

test('halfHourBuckets：同桶累加且按 key 升序', () => {
  const out = halfHourBuckets([
    '2026-10-19T20:45:00.000+08:00',
    '2026-10-19T20:13:16.780+08:00',
    '2026-10-19T20:31:00.000+08:00',
  ]);
  assert.equal(out.length, 2);
  assert.deepEqual(out.map((b) => b.count), [1, 2]);
  for (let i = 1; i < out.length; i += 1) assert.ok(out[i].key > out[i - 1].key);
});

test('dailyBuckets：两日各 1 → 2 桶升序', () => {
  const out = dailyBuckets(['2026-10-19T20:13:16.780+08:00', '2026-09-25T00:00:00.000+08:00']);
  assert.equal(out.length, 2);
  for (const b of out) assert.match(b.key, /^\d{4}-\d{2}-\d{2}$/);
  assert.deepEqual(out.map((b) => b.count), [1, 1]);
  assert.ok(out[0].key < out[1].key);
});

test('countBy：降序，空键归 UNKNOWN_KEY 且排在最后（即使计数最大）', () => {
  const rows = [
    { v: 'b' },
    { v: null },
    { v: '' },
    { v: 'a' },
    { v: 'a' },
    { v: undefined },
    { v: 'a' },
  ];
  const out = countBy(rows, (r) => r.v);
  assert.equal(out[0].key, 'a');
  assert.equal(out[0].count, 3);
  assert.equal(out[out.length - 1].key, UNKNOWN_KEY);
  assert.equal(out[out.length - 1].count, 3, '空键计数最大也必须排最后');
});

test('countBy：同计数按 key 字典序，顺序可重复', () => {
  const rows = [{ v: 'c' }, { v: 'b' }, { v: 'a' }];
  const first = countBy(rows, (r) => r.v).map((x) => x.key);
  assert.deepEqual(first, ['a', 'b', 'c']);
  assert.deepEqual(countBy([...rows].reverse(), (r) => r.v).map((x) => x.key), first);
});

test('countBy：空输入 → []；不改入参', () => {
  assert.deepEqual(countBy([], (r: string) => r), []);
  const rows = [{ v: 'x' }, { v: 'y' }];
  const snapshot = rows.map((r) => ({ ...r }));
  countBy(rows, (r) => r.v);
  assert.deepEqual(rows, snapshot);
});
