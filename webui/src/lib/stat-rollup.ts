// 统计聚合纯函数层（W3 席）——**没有 React、没有副作用、不改入参**。
//
// 为什么单独成层：同一份好感度增量日志要按日/周/月/年/累计五档画图，同一份调用账本
// 要算百分位、用户覆盖率、半小时热点。这些口径一旦散在组件里，就会出现「日图补零、
// 月图不补零」「这张卡用插值百分位、那张卡用最近秩」这种自相矛盾的画面，而且没有任何
// 机器证据能说清现在到底是哪一档。所以口径挤进这一个文件，逐条被
// stat-rollup.test.ts 锁住。
//
// 🔴 三条硬口径（改它们＝改用户可见契约，须先改本注释与测试）：
//   ① **空桶不补零**（见 rollupAffinity）。
//   ② **changeRate 分母恒为 Math.abs(previous)**（见 changeRate）。
//   ③ **percentile 用最近秩法、不做线性插值，且克隆后排序**（见 percentile）。
//
// 时间桶一律 **本地时区**：用 `getFullYear` / `getMonth` / `getDate` / `getHours` /
// `getMinutes`，**不用 `getUTC*`**。后端的 `applied_at` 是 unix 秒（与时区无关的真值），
// 落到哪一天读的人关心的是「我这边的这一天」，转 UTC 会让凌晨 0–8 点的事件整体漂到前一天。
// 唯一例外是入参本来就是带偏移的 ISO 串时（halfHourBuckets / dailyBuckets）：仍按本地
// 时区归桶，与上面同一把尺。

/** 时间粒度五档 + 累计。 */
export type RollupGrain = 'daily' | 'weekly' | 'monthly' | 'yearly' | 'total';

/** 好感度增量日志的一行（只取聚合要用的字段）。 */
export interface AffinityDeltaRow {
  /** unix 秒浮点。 */
  applied_at: number;
  /** 本行增减的分值（可为负）。 */
  delta: number;
  sender_id: string;
}

/** 一个时间桶。 */
export interface RollupBucket {
  /** 桶键：daily=`YYYY-MM-DD` / weekly=`YYYY-Www` / monthly=`YYYY-MM` / yearly=`YYYY` / total=`all`。 */
  key: string;
  /** 桶起始时刻（unix 毫秒），total 为 0。 */
  startMs: number;
  /** 桶内增量合计。 */
  delta: number;
  /** 桶内事件行数。 */
  events: number;
  /** 桶内去重用户数。 */
  users: number;
}

/** 半小时桶键的分钟档（只许这两档，否则轴刻度会漂）。 */
const HALF_HOUR_MINUTES = [0, 30] as const;

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** 本地日键 `YYYY-MM-DD`。 */
function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

/**
 * 本地时刻 → ISO 8601 周（周一为首日）。
 *
 * 按 ISO 8601 的判定：**周所属的年份是「这一周的周四」所在的年份**，不是周日所在年。
 * 所以 2027-01-01（周五）属 2026-W53、2021-01-01（周五）属 2020-W53、2020-12-28（周一）
 * 也属 2020-W53——拿「周日所在年 + 年内第几周」直接拼是最常见的错法。
 * 全部用本地日期字段，不用 getUTC*。
 */
function isoWeek(date: Date): { year: number; week: number } {
  // 先归到本周周一（getDay()：周日=0 → 减 6 天）。
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dow = monday.getDay();
  monday.setDate(monday.getDate() - (dow === 0 ? 6 : dow - 1));
  // 那一周的周四是归属年的锚。
  const thursday = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 3);
  const year = thursday.getFullYear();
  // 年内第几周：以归属年的 1 月 1 日起算的整天数 + 偏移，再除以 7。
  const jan1 = new Date(year, 0, 1);
  const dayOfYear = Math.round((thursday.getTime() - jan1.getTime()) / 86_400_000);
  return { year, week: Math.floor(dayOfYear / 7) + 1 };
}

/** 桶起点（本地时间 00:00:00.000）。 */
function bucketStart(date: Date, grain: RollupGrain): number {
  switch (grain) {
    case 'daily':
      return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    case 'weekly': {
      const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      const dow = monday.getDay();
      monday.setDate(monday.getDate() - (dow === 0 ? 6 : dow - 1));
      return monday.getTime();
    }
    case 'monthly':
      return new Date(date.getFullYear(), date.getMonth(), 1).getTime();
    case 'yearly':
      return new Date(date.getFullYear(), 0, 1).getTime();
    default:
      return 0;
  }
}

/** 桶键。 */
function bucketKey(date: Date, grain: RollupGrain): string {
  switch (grain) {
    case 'daily':
      return dayKey(date);
    case 'weekly': {
      const { year, week } = isoWeek(date);
      return `${year}-W${pad2(week)}`;
    }
    case 'monthly':
      return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
    case 'yearly':
      return String(date.getFullYear());
    default:
      return 'all';
  }
}

/**
 * 按粒度卷成时间序列。桶按 startMs 升序，**空桶不补零**。
 *
 * 空桶不补零是硬要求，理由：补零会让「无数据」与「有数据但为零」在图上长得一样——一条
 * 落在 0 上的线断口被填平后，看的人无法区分「机器人那三天没运行」和「那三天跑了但好感度
 * 净变化恰好为 0」。前者是数据缺口，后者是真实观测；把缺口画成观测，是**谎报**。
 * 真有零净变化的那一天，因为确实有事件行，它自己会出桶（delta=0、events>0），不需要谁去补。
 */
export function rollupAffinity(rows: readonly AffinityDeltaRow[], grain: RollupGrain): RollupBucket[] {
  if (rows.length === 0) return [];

  if (grain === 'total') {
    const senders = new Set<string>();
    let delta = 0;
    for (const r of rows) {
      delta += r.delta;
      senders.add(r.sender_id);
    }
    return [{ key: 'all', startMs: 0, delta, events: rows.length, users: senders.size }];
  }

  const acc = new Map<string, { startMs: number; delta: number; events: number; senders: Set<string> }>();
  for (const r of rows) {
    const date = new Date(r.applied_at * 1000);
    const key = bucketKey(date, grain);
    let slot = acc.get(key);
    if (!slot) {
      slot = { startMs: bucketStart(date, grain), delta: 0, events: 0, senders: new Set<string>() };
      acc.set(key, slot);
    }
    slot.delta += r.delta;
    slot.events += 1;
    slot.senders.add(r.sender_id);
  }

  return [...acc.entries()]
    .map(([key, s]) => ({ key, startMs: s.startMs, delta: s.delta, events: s.events, users: s.senders.size }))
    .sort((a, b) => a.startMs - b.startMs);
}

/**
 * 变化率（百分比）。上一桶缺失或为 0 时返回 null（不是 0、不是 Infinity）。
 *
 * 🔴 分母必须是 `Math.abs(previous)`：previous 为负时用裸 previous 会让符号整体翻转——
 * `changeRate(50, -100)` 会被算成 **-150%（跌）**，而事实是从 -100 涨到 50，是 **+150%（涨）**。
 * 这个错不会抛异常，只会让图上唯一一次反弹被画成最大跌幅。
 * 上一桶为 0 时返回 null 而不是 Infinity：0 分母除出来的「增长无穷倍」不是信息，
 * 而且 JSON 序列化会把 Infinity 变成 null 之外的怪值。
 */
export function changeRate(current: number, previous: number | null | undefined): number | null {
  if (previous === null || previous === undefined || previous === 0) return null;
  return Math.round(((current - previous) / Math.abs(previous)) * 100 * 10) / 10;
}

/** 取「当前桶 / 上一桶」这对值。序列不足两个桶时当前=最后一个、上一=null。 */
export function latestPair(buckets: readonly RollupBucket[]): { current: number; previous: number | null } {
  if (buckets.length === 0) return { current: 0, previous: null };
  const current = buckets[buckets.length - 1].delta;
  const previous = buckets.length >= 2 ? buckets[buckets.length - 2].delta : null;
  return { current, previous };
}

/** 最近 N 个桶的增量数组。不足 N 就返回实际长度，不补零。 */
export function recentDeltas(buckets: readonly RollupBucket[], n: number): number[] {
  const take = Math.max(0, Math.trunc(n));
  if (take === 0) return [];
  return buckets.slice(Math.max(0, buckets.length - take)).map((b) => b.delta);
}

// ============================================================================
// 调用账本聚合
// ============================================================================

/**
 * 百分位（最近秩法）。values 为空返回 null。p 取 0~100。
 *
 * 🔴 最近秩法、不做线性插值，且**克隆后排序**：
 *   - 不插值：样本是有界的小整数（延迟 ms、每用户调用次数），插值会造出一个从没被观测到的
 *     值（[1,2,3,4] 的 P50 插成 2.5，而「2.5 次调用」不存在）。最近秩法给出的落点恒是真实
 *     观测之一，与仓库既有 format.ts / 页面既有口径一致。
 *   - 克隆：`values.slice()` 再 sort。直接 `values.sort()` 会按引用把调用方的数组就地重排——
 *     调用方随后读到一份被偷换的数组却以为是原样，这是最难查的那类 bug。
 */
export function percentile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const idx = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.min(Math.max(idx, 0), sorted.length - 1)];
}

/** 中位数 = percentile(values, 50)。 */
export function median(values: readonly number[]): number | null {
  return percentile(values, 50);
}

/** `session_id` 的归属判定。 */
export type SessionOwner =
  | { kind: 'user'; id: string }
  | { kind: 'group'; groupId: string; userId: string }
  | { kind: 'unknown' };
export function parseSession(sessionId: string | null | undefined): SessionOwner {
  const text = String(sessionId ?? '').trim();
  if (text === '') return { kind: 'unknown' };
  if (/^\d+$/.test(text)) return { kind: 'user', id: text };
  const parts = text.split('_');
  if (parts.length === 3 && parts[0] === 'group' && parts[1] !== '' && parts[2] !== '') {
    return { kind: 'group', groupId: parts[1], userId: parts[2] };
  }
  // 实测里的其余形态（`runtime` / `admin:onebot` / `email:noreply…`）都不可归属到人。
  return { kind: 'unknown' };
}

/** 用户归属覆盖率（0~1）。总行数 0 返回 null。 */
export function attributionCoverage(rows: readonly { session_id: string }[]): number | null {
  if (rows.length === 0) return null;
  let attributed = 0;
  for (const r of rows) if (parseSession(r.session_id).kind !== 'unknown') attributed += 1;
  return attributed / rows.length;
}

/** 用户维度统计。 */
export interface UserStats {
  activeUsers: number;
  /** Top 10% 用户贡献的请求占比（0~1）。用户数不足 10 时取 Top 1。无数据为 null。 */
  topDecileShare: number | null;
  /** 人均调用次数的中位数。 */
  callsPerUserMedian: number | null;
  /** 人均调用次数的 P90。 */
  callsPerUserP90: number | null;
}
export function userStats(rows: readonly { session_id: string }[]): UserStats {
  const perUser = new Map<string, number>();
  for (const r of rows) {
    const owner = parseSession(r.session_id);
    // 群会话里的 userId 与私聊同一 QQ 号合并：同一个人换个入口说话不该被算成两个人。
    const id = owner.kind === 'user' ? owner.id : owner.kind === 'group' ? owner.userId : null;
    if (id === null) continue;
    perUser.set(id, (perUser.get(id) ?? 0) + 1);
  }
  const activeUsers = perUser.size;
  if (activeUsers === 0) {
    return { activeUsers: 0, topDecileShare: null, callsPerUserMedian: null, callsPerUserP90: null };
  }
  const counts = [...perUser.values()].sort((a, b) => b - a);
  const total = counts.reduce((sum, c) => sum + c, 0);
  const head = Math.max(1, Math.ceil(activeUsers * 0.1));
  const topSum = counts.slice(0, head).reduce((sum, c) => sum + c, 0);
  return {
    activeUsers,
    topDecileShare: topSum / total,
    callsPerUserMedian: median(counts),
    callsPerUserP90: percentile(counts, 90),
  };
}

/** ISO 串 → Date；解析失败返回 null（不抛错）。 */
function parseStamp(stamp: string): Date | null {
  const ms = Date.parse(stamp);
  return Number.isNaN(ms) ? null : new Date(ms);
}

/** 计数聚合的公共尾部：Map<key, count> → 按 key 升序数组。 */
function sortedCounts(counts: Map<string, number>): Array<{ key: string; count: number }> {
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

/** 半小时分桶。输入 ISO 串，输出桶键 `YYYY-MM-DDTHH:mm`（mm ∈ {00,30}）。解析失败的行跳过。 */
export function halfHourBuckets(stamps: readonly string[]): Array<{ key: string; count: number }> {
  const counts = new Map<string, number>();
  for (const stamp of stamps) {
    const date = parseStamp(stamp);
    if (!date) continue; // 畸形的行跳过，不抛错：一条坏行不该让整张热点图白屏。
    const minute = date.getMinutes() < 30 ? HALF_HOUR_MINUTES[0] : HALF_HOUR_MINUTES[1];
    const key = `${dayKey(date)}T${pad2(date.getHours())}:${pad2(minute)}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return sortedCounts(counts);
}

/** 按自然日分桶计数。输入 ISO 串，输出 `YYYY-MM-DD` 升序。 */
export function dailyBuckets(stamps: readonly string[]): Array<{ key: string; count: number }> {
  const counts = new Map<string, number>();
  for (const stamp of stamps) {
    const date = parseStamp(stamp);
    if (!date) continue;
    const key = dayKey(date);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return sortedCounts(counts);
}

/** 空键归入本常量，且恒排最后。 */
export const UNKNOWN_KEY = '未登记';

/** 按任意取键函数分组计数，降序；空键归 `UNKNOWN_KEY` 且排最后。 */
export function countBy<T>(
  rows: readonly T[],
  pick: (row: T) => string | null | undefined
): Array<{ key: string; count: number }> {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const raw = pick(row);
    const text = text2key(raw);
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    // 「未登记」恒排最后：它是缺口的汇总量，不该因为数大就坐到榜首冒充一个真实分类。
    .sort((a, b) => {
      const aUnknown = a.key === UNKNOWN_KEY ? 1 : 0;
      const bUnknown = b.key === UNKNOWN_KEY ? 1 : 0;
      if (aUnknown !== bUnknown) return aUnknown - bUnknown;
      if (b.count !== a.count) return b.count - a.count;
      return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
    });
}

/** 取键函数结果 → 桶键（空白与 null/undefined 都算空键）。 */
function text2key(raw: string | null | undefined): string {
  const text = String(raw ?? '').trim();
  return text === '' ? UNKNOWN_KEY : text;
}
