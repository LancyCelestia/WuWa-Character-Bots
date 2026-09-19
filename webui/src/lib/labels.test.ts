import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  BUCKETS,
  BUCKET_LABEL_KEYS,
  bucketLabel,
  DEFAULT_BUCKET,
  DEFAULT_WINDOW,
  GRAPH_WINDOWS,
  nextBucket,
  STATS_WINDOWS,
  WINDOW_IS_ROLLING,
  WINDOW_LABEL_KEYS,
  WINDOW_SECONDS,
  windowLabel,
} from './labels.ts';

// 时间窗/桶的语义与标签单源锁（UNI1 收口：三份枚举手抄 + 四份标签真值表 → labels.ts + window.*）。
// 运行方式：node --test src/lib/labels.test.ts（Node ≥23 原生类型剥离，零新依赖）。

type Table = Record<string, unknown>;

function readText(url: URL): string {
  return readFileSync(url, 'utf-8');
}

const zhLocale = JSON.parse(readText(new URL('../locales/zh-CN/common.json', import.meta.url))) as Table;
const enLocale = JSON.parse(readText(new URL('../locales/en/common.json', import.meta.url))) as Table;

// 后端真相源（前端跨语言的“同值”不许靠人眼盯，此处直读源码字面量对账）。
const CONTROL_PLANE = '../../../plugins/bot_unified_runtime/control_plane/';

function lookup(table: Table, key: string): string | undefined {
  let cursor: unknown = table;
  for (const part of key.split('.')) {
    if (typeof cursor !== 'object' || cursor === null || !(part in cursor)) return undefined;
    cursor = (cursor as Table)[part];
  }
  return typeof cursor === 'string' ? cursor : undefined;
}

function makeT(table: Table): (key: string) => string {
  return (key: string) => lookup(table, key) ?? key;
}

const tZh = makeT(zhLocale);
const tEn = makeT(enLocale);

/** 解析 Python 闭集字典字面量（`{"24h": 86_400, "7d": 7 * 86_400, "all": None}`）。 */
function pyWindowLiterals(source: string, name: string): Map<string, number | null> {
  const match = new RegExp(`${name}\\s*=\\s*\\{([^}]*)\\}`).exec(source);
  assert.ok(match, `后端源码里找不到 ${name}——改名/挪文件必须同步 labels.ts 的真相源锚点`);
  const entries = [...match[1].matchAll(/"([^"]+)"\s*:\s*([^,}]+?)\s*(?:,|$)/g)];
  assert.ok(entries.length > 0, `${name} 字面量解析为空（正则与后端写法不匹配？）`);
  return new Map(
    entries.map(([, code, raw]) => {
      if (raw === 'None') return [code, null] as const;
      const factors = raw.split('*').map((part) => part.trim().replace(/_/g, ''));
      assert.ok(
        factors.every((part) => /^\d+$/.test(part)),
        `无法解析后端跨度字面量 ${name} 的 ${raw}（后端改成表达式请同步本解析器）`
      );
      return [code, factors.reduce((acc, part) => acc * Number(part), 1)] as const;
    })
  );
}

test('枚举与次序：stats 三档、graph = stats + all、桶两档（顺序即界面顺序，重排需改本锁）', () => {
  assert.deepEqual([...STATS_WINDOWS], ['24h', '7d', '30d']);
  assert.deepEqual([...GRAPH_WINDOWS], ['24h', '7d', '30d', 'all']);
  assert.deepEqual([...BUCKETS], ['hour', 'day']);
  assert.ok(STATS_WINDOWS.includes(DEFAULT_WINDOW), '缺省窗必须在自家枚举内');
  assert.equal(DEFAULT_BUCKET, 'hour');
});

test('窗口跨度与后端逐项同值（直读 metrics.py 的 _WINDOW_SECONDS 与 memory_graph 的 _WINDOWS）', () => {
  const stats = pyWindowLiterals(readText(new URL(`${CONTROL_PLANE}metrics.py`, import.meta.url)), '_WINDOW_SECONDS');
  const graph = pyWindowLiterals(readText(new URL(`${CONTROL_PLANE}webui_memory_graph.py`, import.meta.url)), '_WINDOWS');
  for (const code of STATS_WINDOWS) {
    assert.ok(stats.has(code), `后端 stats 侧不再接受 ${code}——前端枚举该收缩，别把 422 送上生产`);
    assert.equal(WINDOW_SECONDS[code], stats.get(code), `${code} 跨度与后端 stats 不等`);
  }
  for (const code of GRAPH_WINDOWS) {
    assert.ok(graph.has(code), `后端图谱侧不再接受 ${code}`);
    assert.equal(WINDOW_SECONDS[code], graph.get(code), `${code} 跨度与后端图谱不等`);
  }
  assert.equal(WINDOW_SECONDS.all, null, 'all 无界：不得造上界秒数');
});

test('桶闭集与后端同值（webui_stats.py _BUCKETS，表外值后端 422 invalid_bucket）', () => {
  const source = readText(new URL(`${CONTROL_PLANE}webui_stats.py`, import.meta.url));
  const match = /_BUCKETS\s*=\s*\(([^)]*)\)/.exec(source);
  assert.ok(match, '后端 _BUCKETS 字面量形态变了——同步本解析器与 labels.ts 锚点注释');
  const backend = [...match[1].matchAll(/"([^"]+)"/g)].map((entry) => entry[1]);
  assert.deepEqual([...BUCKETS], backend);
});

test('名实：有限窗全为滚动窗（后端 now - timedelta 口径），标签不得出现自然日用语', () => {
  for (const code of GRAPH_WINDOWS) {
    assert.equal(WINDOW_IS_ROLLING[code], WINDOW_SECONDS[code] !== null, `${code} 滚动标记与跨度不自洽`);
  }
  const calendarWords = ['今日', '当天', '本周', '本月', '今天'];
  for (const code of STATS_WINDOWS) {
    assert.equal(WINDOW_IS_ROLLING[code], true, `${code} 是滚动窗，标 false 即名实不符`);
    const zh = lookup(zhLocale, WINDOW_LABEL_KEYS[code]);
    const en = lookup(enLocale, WINDOW_LABEL_KEYS[code]);
    assert.ok(zh && en, `window.${code} 双语缺键`);
    for (const word of calendarWords) {
      assert.ok(!zh.includes(word), `zh 标签「${zh}」含自然日用语「${word}」——窗口是滚动的`);
    }
    assert.ok(!/today|this (?:day|week|month)/i.test(en), `en 标签「${en}」暗示自然日`);
    assert.ok(zh.startsWith('近'), `zh 标签「${zh}」未标明「近 …」（滚动窗口径）`);
    assert.match(en, /^Last /, `en 标签「${en}」未标明 Last …`);
  }
  assert.equal(WINDOW_IS_ROLLING.all, false, 'all 无回溯起点，不该标滚动');
  assert.equal(lookup(zhLocale, WINDOW_LABEL_KEYS.all), '全部时间');
  assert.equal(lookup(enLocale, WINDOW_LABEL_KEYS.all), 'All time');
});

test('标签键覆盖枚举且双语在位（含桶标签；windowLabel/bucketLabel 是唯一取词口）', () => {
  assert.deepEqual(Object.keys(WINDOW_LABEL_KEYS).sort(), [...GRAPH_WINDOWS].sort());
  assert.deepEqual(Object.keys(BUCKET_LABEL_KEYS).sort(), [...BUCKETS].sort());
  for (const code of GRAPH_WINDOWS) {
    assert.ok(lookup(zhLocale, WINDOW_LABEL_KEYS[code]), `zh 缺 ${WINDOW_LABEL_KEYS[code]}`);
    assert.ok(lookup(enLocale, WINDOW_LABEL_KEYS[code]), `en 缺 ${WINDOW_LABEL_KEYS[code]}`);
    assert.equal(windowLabel(tZh, code), lookup(zhLocale, WINDOW_LABEL_KEYS[code]));
    assert.equal(windowLabel(tEn, code), lookup(enLocale, WINDOW_LABEL_KEYS[code]));
  }
  for (const code of BUCKETS) {
    assert.ok(lookup(zhLocale, BUCKET_LABEL_KEYS[code]), `zh 缺 ${BUCKET_LABEL_KEYS[code]}`);
    assert.equal(bucketLabel(tZh, code), lookup(zhLocale, BUCKET_LABEL_KEYS[code]));
  }
});

test('第三/四份标签真值表已删除；两份遗留表（tokens/memory-graph 占用）值不得与单源分叉', () => {
  // 本席收口：dashboard.overview.windowToday / window7d 退役（只有 dashboard 消费，已改走 window.*）。
  assert.equal(lookup(zhLocale, 'dashboard.overview.windowToday'), undefined, 'windowToday 未删除（第 3 份表还在）');
  assert.equal(lookup(zhLocale, 'dashboard.overview.window7d'), undefined, 'window7d 未删除（第 4 份表还在）');
  assert.equal(lookup(enLocale, 'dashboard.overview.windowToday'), undefined);
  // 遗留表由只读页消费（tokens.tsx:117 借 calls.window.*；memory-graph.tsx:128/278 用 memoryGraph.window.*）。
  // 迁移前按值对账锁死：三处同一码必须同一说法，谁改一处即刻红。
  const legacyNamespaces = ['calls.window', 'memoryGraph.window'];
  for (const namespace of legacyNamespaces) {
    for (const code of GRAPH_WINDOWS) {
      const legacy = lookup(zhLocale, `${namespace}.${code}`);
      if (legacy === undefined) continue; // 该表不含 all 之类，缺项交由上一条枚举覆盖锁管
      assert.equal(legacy, lookup(zhLocale, WINDOW_LABEL_KEYS[code]), `zh ${namespace}.${code} 与单源分叉`);
      const legacyEn = lookup(enLocale, `${namespace}.${code}`);
      assert.equal(legacyEn, lookup(enLocale, WINDOW_LABEL_KEYS[code]), `en ${namespace}.${code} 与单源分叉`);
    }
  }
});

test('nextBucket：hour/day 两态闭环，表外值回缺省桶不猜（后端只认这两个值）', () => {
  assert.equal(nextBucket('hour'), 'day');
  assert.equal(nextBucket('day'), 'hour');
  assert.equal(nextBucket('week' as unknown as typeof DEFAULT_BUCKET), DEFAULT_BUCKET);
  assert.equal(nextBucket(undefined as unknown as typeof DEFAULT_BUCKET), DEFAULT_BUCKET);
  for (const code of BUCKETS) assert.ok(BUCKETS.includes(nextBucket(code)), `${code} 的后继出表`);
});

test('负断言棘轮：本席所辖页面不再手抄枚举、不再写死未知符号字面量', () => {
  const owned = [
    '../pages/calls.tsx',
    '../pages/dashboard.tsx',
    '../pages/latency.tsx',
    '../pages/affinity.tsx',
    '../pages/plugins.tsx',
    '../components/semantic/semantic-state.tsx',
  ];
  for (const path of owned) {
    const text = readText(new URL(path, import.meta.url));
    assert.ok(!/const\s+WINDOWS\b/.test(text), `${path} 又手抄了一份窗口枚举（真相源=labels.ts）`);
    assert.ok(!/['"]—['"]/.test(text), `${path} 又写了未知符号字面量（真相源=format.ts UNKNOWN_VALUE）`);
    assert.ok(!/>—</.test(text), `${path} 又内联了未知符号（真相源=format.ts UNKNOWN_VALUE）`);
    assert.ok(!/t\(`calls\.window\./.test(text), `${path} 又绕过 windowLabel 直取窗口标签`);
  }
  // 未迁移的注册残余（只读面，见 UNI1 台账 §四）：数量只减不增，清零后请删掉本断言的白名单。
  const stillEnumerating = ['../pages/tokens.tsx', '../pages/memory-graph.tsx'].filter((path) =>
    /const\s+WINDOWS\b/.test(readText(new URL(path, import.meta.url)))
  );
  assert.deepEqual(stillEnumerating, ['../pages/tokens.tsx', '../pages/memory-graph.tsx'], '枚举残余清单变化：同步 UNI1 台账 §四');
});
