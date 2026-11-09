import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import {
  CONSOLE_PAGES,
  CONSOLE_ROOT,
  channelRollup,
  configSummary,
  consolePathForLegacy,
  errorRate,
  healthLine,
  legacyHashPath,
  legacyPathForConsole,
  mergeLogPages,
  queueLine,
  tailErrors,
  todoRollup,
} from './console.ts';

/** `pages/` 里实有的页面文件名（去 `.tsx`），按文件名排序。 */
async function pageFiles(): Promise<string[]> {
  const dir = fileURLToPath(new URL('../pages/', import.meta.url));
  const files = (await readdir(dir)).filter((name) => name.endsWith('.tsx')).map((name) => name.replace(/\.tsx$/, ''));
  return files.sort();
}

/** 文件名 → 映射表里的 `console` 段。只为「文件名与段名不同」的那条写明，其余同名。 */
const PAGE_ROW: Record<string, string | undefined> = {
  // `/` 那一行（旧路由 `/`、真路径 `/console/overview`）由 dashboard 渲染。
  // 文件名与段名不同是历史命名，不是两页——表里 `/` 只占一行。
  dashboard: 'overview',
};

/**
 * 一个共用实现文件同时撑起的映射表行。
 *
 * 🔴 这里是最容易算错的一处：`control-center.tsx` 只占一个**文件**，却撑两条**行**
 * （`router.tsx` 两次 `lazyRouteComponent(() => import('@/pages/control-center'), …)`
 * → `/resources` + `/models`）。所以条数恒等式是
 *   行数 = 文件数 − 共用实现文件数 + 其撑起的行数
 * 而不是「文件数 − 1」（差一条，会逼着人给共用实现硬塞一行假页面）。
 *
 * 另两处刻意**不**当作例外：
 *   - `console.tsx` 是真页面（517 行、一屏八块的总台），不是入口壳——壳是
 *     `components/console/entry.tsx::ConsoleRoute`。它挂 `/console` 路由，真路径
 *     `/console/console`（`/console` 与 `/console/overview` 都被 `routePathFor()` 判给总览）。
 *   - `dashboard.tsx` 就是 `/` 那一行，由上面的 `PAGE_ROW` 对表。
 */
const SHARED_IMPL_ROWS: Record<string, readonly string[]> = {
  'control-center': ['resources', 'models'],
};

/**
 * 控制台总台（W12 W2-UI）纯函数锁。
 *
 * 为什么这些判定要住在 lib 而不是 .tsx：判据住在组件里等于没有判据（同 labels.test.ts
 * 教训）——总台每个摘要行都在**声称**一个状态（在线/异常/未接入），错一个就是谎报。
 * 本文件零 React 依赖，可被 node --test 直接加载。
 */

// ---------- 路由族映射（/console/* 单一真身） ----------

/**
 * 由 `pages/` 目录推导出「映射表里应当出现的所有 `console` 段」。
 *
 * 判据取目录本身，不另抄一份清单——清单会跟着漂移，目录不会。三处例外都必须显式写出，
 * 否则就是靠巧合对齐（`PAGE_ROW` 的命名差、`SHARED_IMPL_ROWS` 的一文件两行）。
 */
async function expectedSegments(): Promise<string[]> {
  const segments: string[] = [];
  for (const file of await pageFiles()) {
    const shared = SHARED_IMPL_ROWS[file];
    if (shared) segments.push(...shared);
    else segments.push((file in PAGE_ROW ? PAGE_ROW[file] : file) ?? file);
  }
  return segments.sort();
}

/** 映射表里实际出现的所有 `console` 段。 */
function registeredSegments(): string[] {
  return CONSOLE_PAGES.map((row) => row.console.slice(`${CONSOLE_ROOT}/`.length)).sort();
}

test('CONSOLE_PAGES 一页一条，旧路径全部影射到 /console/*，根路径落到总台', async () => {
  assert.equal(CONSOLE_ROOT, '/console');
  // 条数不写死：由 pages/ 目录算出。写死 15 曾让 console/sessions/appearance 三个页面
  // 白挂很久都没人发现——漏登记不报错，旧深链只是悄悄认不回来。
  assert.equal(CONSOLE_PAGES.length, (await expectedSegments()).length, '每条 pages/ 独立页都必须一页一行地进映射表');
  const legacy = CONSOLE_PAGES.map((row) => row.legacy);
  assert.equal(new Set(legacy).size, legacy.length, '旧路径不得重复');
  const paths = CONSOLE_PAGES.map((row) => row.console);
  assert.equal(new Set(paths).size, paths.length, '控制台路径不得重复');
  for (const row of CONSOLE_PAGES) {
    assert.ok(row.console.startsWith(`${CONSOLE_ROOT}/`), `${row.console} 必须在 /console/ 族下`);
    assert.equal(consolePathForLegacy(row.legacy), row.console);
    assert.equal(legacyPathForConsole(row.console), row.legacy);
  }
  // 总览（旧 /）不叫 /console/（那是总台），必须让出一个独立子路径。
  assert.equal(consolePathForLegacy('/'), '/console/overview');
  assert.ok(!paths.includes(CONSOLE_ROOT), '/console 本身是总台入口，不得被某页占用');
});

test('CONSOLE_PAGES 与 pages/ 实有文件一一对应，不漏不重', async () => {
  // 为什么要这条门：漏登记的页面**不会报错**——路由照样能进、也渲染得出来，只是
  // 旧深链（`#/sessions`）认不回来、`legacyPathForConsole` 反查为空。仓库里已经有
  // 三条这样白挂过的页面（console / sessions / appearance），靠人眼对表就是会漏。
  // 判据取 `pages/` 目录本身，而不是再抄一份清单——清单会一起漂移，目录不会。
  const expected = await expectedSegments();
  const registered = registeredSegments();
  assert.deepEqual(
    registered,
    expected,
    'CONSOLE_PAGES 与 pages/ 目录不一致——要么补登记，要么删掉不存在的条目',
  );
});

test('未知路径不给猜测值：映射表查不到就回空串（调用方据此报「不认识」）', () => {
  assert.equal(consolePathForLegacy('/nope'), '');
  assert.equal(consolePathForLegacy(''), '');
  assert.equal(legacyPathForConsole('/console/nope'), '');
  assert.equal(legacyPathForConsole(CONSOLE_ROOT), '');
});

// ---------- 真路径 → 路由路径（UI3：browser history，判据搬去 route-path.test.ts） ----------
//
// UI2 的 `bootHashFor()` 一组已随 hash 路由一起删除。映射逻辑仍在，宿主换成
// `lib/route-path.ts::routePathFor`，判据在 `lib/route-path.test.ts`（那份文件同样
// 零 React 依赖、可被 node --test 直接加载）。本文件只保留「映射表本身完好」一条，
// 防止删代码时连登记面一起删掉。

test('CONSOLE_PAGES 仍是旧深链的登记面：每条 /console/<页> 都能反查回旧路由', () => {
  for (const row of CONSOLE_PAGES) {
    assert.equal(legacyPathForConsole(row.console), row.legacy);
    assert.ok(row.title.length > 0, `${row.console} 必须有中文标题`);
  }
});

// ---------- 旧 `#/xxx` 深链认领（用户截图：地址栏 `#/plugins`、侧栏「插件」、正文「总览」） ----------
//
// 旧书签/缓存里的 `#/plugins` 被 browser history 原样留在地址栏，而路由只读 pathname，
// 于是地址栏说 plugins、正文渲染总览。认领函数只做「旧 hash → 真路径」这一跳，映射表
// 就是上面那张 CONSOLE_PAGES（不另起第二份），入口拿结果 replaceState 掉 `#`。

test('legacyHashPath：`#/plugins` 认领成真路径（用户截图那条）', () => {
  assert.equal(legacyHashPath('#/plugins'), '/console/plugins');
});

test('legacyHashPath：全部旧 deep link 逐行认领，与 CONSOLE_PAGES 同表', () => {
  for (const row of CONSOLE_PAGES) {
    assert.equal(legacyHashPath(`#${row.legacy}`), row.console, `#${row.legacy}`);
  }
  // 总览旧 hash 是 `/`：`#/` 与裸 `#` 都算。
  assert.equal(legacyHashPath('#/'), '/console/overview');
  assert.equal(legacyHashPath('#'), '/console/overview');
});

test('legacyHashPath：查询串保留，只换路径', () => {
  assert.equal(legacyHashPath('#/logs?cursor=42'), '/console/logs?cursor=42');
  assert.equal(legacyHashPath('#/knowledge?collection=kb_docs'), '/console/knowledge?collection=kb_docs');
});

test('legacyHashPath：不是旧式 `#/…` 的一律不认领（现代页面自带的 hash 锚不得被吃掉）', () => {
  assert.equal(legacyHashPath(''), '');
  assert.equal(legacyHashPath('#section-2'), '');
  assert.equal(legacyHashPath('#top'), '');
});

test('legacyHashPath：认不出的旧路径不猜，清成默认页（空串=调用方据此把 # 整段去掉）', () => {
  assert.equal(legacyHashPath('#/nope'), '');
  // `#/console` 不再是「认不出」——总台页已入册（真路径 /console/console），
  // 见上面逐行认领那条。这里只留真·未知路径。
  assert.equal(legacyHashPath('#/console/plugins'), '');
  assert.equal(legacyHashPath('#/console/nope'), '');
});

// ---------- 日志页合并 / 尾窗 ----------

const ev = (cursor: number, event_id = `e${cursor}`) => ({ cursor, event_id });

test('mergeLogPages 按 event_id 去重、按 cursor 升序（跨页边界重叠不得重复上屏）', () => {
  const merged = mergeLogPages([
    [ev(1), ev(2), ev(3)],
    [ev(3), ev(4)],
  ]);
  assert.deepEqual(merged.map((row) => row.cursor), [1, 2, 3, 4]);
  assert.equal(merged.length, 4);
});

test('tailErrors 取尾窗且保序；n<=0 空表；不足 n 有多少给多少', () => {
  const rows = [ev(1), ev(2), ev(3), ev(4)];
  assert.deepEqual(tailErrors(rows, 2).map((r) => r.cursor), [3, 4]);
  assert.deepEqual(tailErrors(rows, 0), []);
  assert.deepEqual(tailErrors(rows, 99).map((r) => r.cursor), [1, 2, 3, 4]);
  assert.deepEqual(tailErrors([], 5), []);
});

// ---------- 错误率（账本真值，不造分母） ----------

test('errorRate：分母未知/为 0 时不报率（不得把 0/0 说成 0%）', () => {
  assert.equal(errorRate(0, 0).ratio, null);
  assert.equal(errorRate(3, 0).ratio, null);
  assert.equal(errorRate(null, 100).ratio, null);
  assert.equal(errorRate(3, null).ratio, null);
  assert.equal(errorRate(undefined, undefined).ratio, null);
  assert.equal(errorRate(3, 0).tone, 'flat');
});

test('errorRate：有分母才出率，档位按 2% / 20% 两刀', () => {
  const clean = errorRate(0, 100);
  assert.equal(clean.ratio, 0);
  assert.equal(clean.tone, 'good');
  assert.equal(errorRate(1, 100).tone, 'good');
  assert.equal(errorRate(3, 100).tone, 'warn');
  assert.equal(errorRate(21, 100).tone, 'bad');
  assert.ok(Math.abs((errorRate(1, 3).ratio ?? 0) - 1 / 3) < 1e-12);
});

// ---------- 进程健康 ----------

test('healthLine：全 ok 才是 good，任一非 ok 即 warn，整体 not ok 即 bad', () => {
  assert.deepEqual(healthLine(true, { db: 'ok', ws: 'ok' }), { ok: 2, total: 2, tone: 'good' });
  assert.deepEqual(healthLine(true, { db: 'ok', ws: 'degraded' }), { ok: 1, total: 2, tone: 'warn' });
  assert.deepEqual(healthLine(false, { db: 'ok' }), { ok: 1, total: 1, tone: 'bad' });
  // checks 缺席（旧控制面/夹具缺字段）不得当成「全绿」，也不得炸。
  assert.deepEqual(healthLine(true, null), { ok: 0, total: 0, tone: 'warn' });
  assert.deepEqual(healthLine(true, {}), { ok: 0, total: 0, tone: 'warn' });
});

// ---------- LLM 通道 ----------

const ch = (state: string, consecutive_fails = 0, cooldown_active = false) => ({
  health: { state, consecutive_fails, cooldown_active },
});

test('channelRollup：不可用/冷却压过降级；unknown 不得被算成 ok', () => {
  assert.deepEqual(channelRollup([ch('ok'), ch('ok')]), {
    ok: 2,
    degraded: 0,
    unavailable: 0,
    unknown: 0,
    cooling: 0,
    tone: 'good',
  });
  const degraded = channelRollup([ch('ok'), ch('degraded', 2)]);
  assert.equal(degraded.degraded, 1);
  assert.equal(degraded.tone, 'warn');
  const cooling = channelRollup([ch('ok'), ch('ok', 3, true)]);
  assert.equal(cooling.cooling, 1);
  assert.equal(cooling.tone, 'bad', '冷却中的通道必须最高档告警，不能被 ok 稀释');
  const unavailable = channelRollup([ch('unavailable')]);
  assert.equal(unavailable.tone, 'bad');
  const unknown = channelRollup([ch('unknown')]);
  assert.equal(unknown.unknown, 1);
  assert.equal(unknown.ok, 0, 'unknown 不得计入 ok');
  assert.equal(unknown.tone, 'flat', '全是 unknown 时不能声称正常，也不能谎报故障');
  assert.equal(channelRollup([]).tone, 'flat');
});

// ---------- 待办 ----------

test('todoRollup：配置命令与动作回执分桶计数，档位按「失败 > 待批/冲突 > 降级」', () => {
  const empty = todoRollup([], []);
  assert.equal(empty.total, 0);
  assert.equal(empty.tone, 'flat');

  const busy = todoRollup(
    [{ status: 'pending' }, { status: 'needs_consent' }, { status: 'conflict' }, { status: 'applied' }],
    [{ state: 'failed' }, { state: 'running' }, { state: 'succeeded', result: { status: 'degraded' } }]
  );
  assert.equal(busy.pending, 1);
  assert.equal(busy.consent, 1);
  assert.equal(busy.conflict, 1);
  assert.equal(busy.failed, 1);
  assert.equal(busy.running, 1);
  assert.equal(busy.degraded, 1);
  assert.equal(busy.total, 6, 'applied/succeeded 不进待办');
  assert.equal(busy.tone, 'bad', '有失败即最高档');

  assert.equal(todoRollup([{ status: 'pending' }], []).tone, 'warn');
  assert.equal(todoRollup([], [{ state: 'succeeded', result: { status: 'degraded' } }]).tone, 'warn');
  assert.equal(todoRollup([{ status: 'applied' }], [{ state: 'succeeded', result: { status: 'ok' } }]).tone, 'flat');
});

// ---------- 队列积压 ----------

test('queueLine：未接入如实说未接入，不写 0（0 与「不知道」是两件事）', () => {
  assert.deepEqual(queueLine({ value: null, status: 'unknown', reason: 'not_connected' }), {
    text: '未接入',
    tone: 'flat',
  });
  assert.deepEqual(queueLine({ value: null, status: 'unknown', reason: 'source_unavailable' }), {
    text: 'source_unavailable',
    tone: 'flat',
  });
  assert.deepEqual(queueLine(null), { text: '不可知', tone: 'flat' });
  assert.deepEqual(queueLine({ value: 0, status: 'ok', reason: null }), { text: '0', tone: 'good' });
  assert.deepEqual(queueLine({ value: 12, status: 'ok', reason: null }), { text: '12', tone: 'warn' });
  assert.deepEqual(queueLine({ value: 512, status: 'ok', reason: null }), { text: '512', tone: 'bad' });
});

// ---------- 配置摘要 ----------

test('configSummary：可写/重启生效/敏感三轴分别计数，不合并成一个数', () => {
  const summary = configSummary([
    { writable: true, can_write: true, restart_required: true, sensitive: true },
    { can_write: false, restart_required: false, sensitive: false },
    { writable: true, restart_required: true },
  ]);
  assert.deepEqual(summary, { total: 3, writable: 2, restartRequired: 2, sensitive: 1 });
  assert.deepEqual(configSummary([]), { total: 0, writable: 0, restartRequired: 0, sensitive: 0 });
});
