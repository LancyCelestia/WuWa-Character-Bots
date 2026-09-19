import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
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
//
// 密封纪律（UNI1 fix1 · 评审 C-1 裁定）：本文件**只读 webui/ 以内**（labels / locale / 页面源码），
// 「前端声明 == 后端源码」的跨语言同值**不再由 node --test 锁定**——control_plane 三件 .py
// （metrics / webui_stats / webui_memory_graph）本波未入库，干净克隆上缺文件是 ENOENT **失败**
// 而非 skip，会经 tests/test_webui_constitution.py::test_pure_function_tests 把整个前端门拖红，
// 且失败消息对改后端的 Python 作者零可达（他跑 pytest，不跑 npm test）。
// 该职责移交 `tests/test_webui_labels_backend_parity.py`（pytest 侧：后端模块缺失即显式 skip 并
// 点名路径、失败落在改动的一方，并兼锁 M-3/I-1「后端产出 reason 码 ⊆ 前端白名单」）。
// node 侧保留 labels ↔ 枚举 ↔ 标签 的纯前端三向自洽锁，任何克隆上都恒可跑。

type Table = Record<string, unknown>;

function readText(url: URL): string {
  return readFileSync(url, 'utf-8');
}

const zhLocale = JSON.parse(readText(new URL('../locales/zh-CN/common.json', import.meta.url))) as Table;
const enLocale = JSON.parse(readText(new URL('../locales/en/common.json', import.meta.url))) as Table;

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

test('枚举与次序：stats 三档、graph = stats + all、桶两档（顺序即界面顺序，重排需改本锁）', () => {
  assert.deepEqual([...STATS_WINDOWS], ['24h', '7d', '30d']);
  assert.deepEqual([...GRAPH_WINDOWS], ['24h', '7d', '30d', 'all']);
  assert.deepEqual([...BUCKETS], ['hour', 'day']);
  assert.ok(STATS_WINDOWS.includes(DEFAULT_WINDOW), '缺省窗必须在自家枚举内');
  assert.equal(DEFAULT_BUCKET, 'hour');
});

test('窗口跨度内部自洽：键集=图谱枚举、all 无界、有限档=1/7/30 天整（跨语言同值改由 pytest 锁定）', () => {
  assert.deepEqual(
    Object.keys(WINDOW_SECONDS).sort(),
    [...GRAPH_WINDOWS].sort(),
    '跨度表与图谱枚举键集分叉'
  );
  assert.equal(WINDOW_SECONDS.all, null, 'all 无界：不得造上界秒数');
  assert.deepEqual(
    STATS_WINDOWS.map((code) => WINDOW_SECONDS[code]),
    [86_400, 7 * 86_400, 30 * 86_400],
    '有限窗跨度应恰为 1/7/30 天（此处钉死即防漂，后端同值验证在 pytest 侧 parity 门）'
  );
  // 后端 metrics.py / webui_stats.py / webui_memory_graph.py 的字面量同值与桶闭集对账：
  // tests/test_webui_labels_backend_parity.py（文件缺失→显式 skip，绝不 ENOENT 红）。
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

test('第三/四份标签真值表已删除；两份遗留镜像表（calls.window/memoryGraph.window）值不得与单源分叉', () => {
  // 本席收口：dashboard.overview.windowToday / window7d 退役（只有 dashboard 消费，已改走 window.*）。
  assert.equal(lookup(zhLocale, 'dashboard.overview.windowToday'), undefined, 'windowToday 未删除（第 3 份表还在）');
  assert.equal(lookup(zhLocale, 'dashboard.overview.window7d'), undefined, 'window7d 未删除（第 4 份表还在）');
  assert.equal(lookup(enLocale, 'dashboard.overview.windowToday'), undefined);
  // 遗留镜像表的消费者（fix1 更新）：memoryGraph.window.* 仍被 memory-graph.tsx:128/278 消费（只读面，
  // 台账 §四-2）；calls.window.* 自 fix1 迁走 tokens 后已**零生产消费者**——locale 对本波只读，
  // 删表另行批（台账 §四-11），删前由本锁钉住值与单源相等，漂一字即红。
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

test('负断言：已收口页面（含 fix1 迁完的 tokens）不再手抄枚举、不再写死未知符号字面量', () => {
  const owned = [
    '../pages/calls.tsx',
    '../pages/dashboard.tsx',
    '../pages/latency.tsx',
    '../pages/affinity.tsx',
    '../pages/plugins.tsx',
    '../pages/tokens.tsx',
    '../components/semantic/semantic-state.tsx',
  ];
  for (const path of owned) {
    const text = readText(new URL(path, import.meta.url));
    assert.ok(!/const\s+WINDOWS\b/.test(text), `${path} 又手抄了一份窗口枚举（真相源=labels.ts）`);
    assert.ok(!/['"]—['"]/.test(text), `${path} 又写了未知符号字面量（真相源=format.ts UNKNOWN_VALUE）`);
    assert.ok(!/>—</.test(text), `${path} 又内联了未知符号（真相源=format.ts UNKNOWN_VALUE）`);
    assert.ok(!/t\(`calls\.window\./.test(text), `${path} 又绕过 windowLabel 直取窗口标签`);
  }
});

test('残余棘轮（shrink-only 下限）：枚举手抄面只许减少，还债不得砸门（评审 I-2）', () => {
  // 在册未迁残余（UNI1 台账 §四-2；tokens 已于 fix1 迁完并升级进上例严检）。
  // 深比较「精确等值」会在后续席完成迁移时反而红（进度=砸门），故这里只断：
  //   ①数量 ≤ 在册基线（只减不增）；②每个命中页必须仍在册（新抄一枚即红）。
  // memory-graph 迁完后命中数归 0，本例依旧绿；届时请把清单清空并保留本框架防新页手抄。
  const trackedUnmigrated = ['../pages/memory-graph.tsx'];
  const pagePaths = readdirSync(new URL('../pages/', import.meta.url))
    .filter((name) => name.endsWith('.tsx'))
    .sort()
    .map((name) => `../pages/${name}`);
  const stillEnumerating = pagePaths.filter((path) =>
    /const\s+WINDOWS\b/.test(readText(new URL(path, import.meta.url)))
  );
  assert.ok(
    stillEnumerating.length <= trackedUnmigrated.length,
    `枚举残余 ${stillEnumerating.length} 处超过下限 ${trackedUnmigrated.length}（棘轮只减不增）：${stillEnumerating.join(', ')}`
  );
  for (const path of stillEnumerating) {
    assert.ok(
      trackedUnmigrated.includes(path),
      `新的未登记枚举手抄面 ${path}——迁 labels.ts，或先登记 UNI1 台账 §四 再入本清单`
    );
  }
});
