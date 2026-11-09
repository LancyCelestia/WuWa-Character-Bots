import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  DEFAULT_RETRY_AFTER_SECONDS,
  describeRateLimit,
  parseRetryAfter,
  retryAfterSeconds,
} from './rate-limit.ts';

// 429 限速的「说人话」与「读后端 Retry-After」纯函数锁（S 席执行任务 2）。
//
// 实测机制（用户亲跑，可复跑）：无令牌连发 7 次 /api/v1/stats/calls → 前 5 次 401、
// 第 6 次起 429；等 70 秒才恢复。根因链 = 首屏并行 7 个请求全 401（auth.py 把「没带
// 令牌」也算失败）→ 第 6 个 429 → 429 不在重试排除列表里 → 重试又产生新失败计数 →
// 越重试越锁死。所以 429 必须：① 不重试；② 有自己的语义态，绝不说「加载失败」。
//
// 运行方式：node --test src/lib/rate-limit.test.ts（Node ≥23 原生类型剥离，零新依赖）。

type Table = Record<string, unknown>;

function readLocale(dir: string): Table {
  return JSON.parse(readFileSync(new URL(`../locales/${dir}/common.json`, import.meta.url), 'utf-8')) as Table;
}

const zhLocale = readLocale('zh-CN');
const enLocale = readLocale('en');

function lookup(table: Table, key: string): string | undefined {
  let cursor: unknown = table;
  for (const part of key.split('.')) {
    if (typeof cursor !== 'object' || cursor === null || !(part in cursor)) return undefined;
    cursor = (cursor as Table)[part];
  }
  return typeof cursor === 'string' ? cursor : undefined;
}

/** i18next 缺省行为夹具：未命中回吐键本身（与真运行时同构，零依赖）。 */
function makeT(table: Table): (key: string) => string {
  return (key: string) => lookup(table, key) ?? key;
}

const tZh = makeT(zhLocale);
const tEn = makeT(enLocale);

test('parseRetryAfter：后端 Retry-After 秒数原样读出', () => {
  assert.equal(parseRetryAfter('42'), 42);
  assert.equal(parseRetryAfter(' 7 '), 7);
  assert.equal(parseRetryAfter('1'), 1);
});

test('parseRetryAfter：缺头 / 脏值 / 非正数一律放弃（不编造，回落缺省）', () => {
  for (const raw of [null, undefined, '', '   ', 'abc', '0', '-5', 'NaN']) {
    assert.equal(parseRetryAfter(raw as string | null | undefined), undefined, `不该接受 ${String(raw)}`);
  }
});

test('retryAfterSeconds：读不到就用 60 秒（与 auth.py 的 60 秒窗口同量级）', () => {
  assert.equal(DEFAULT_RETRY_AFTER_SECONDS, 60);
  assert.equal(retryAfterSeconds(null), 60);
  assert.equal(retryAfterSeconds('garbage'), 60);
  assert.equal(retryAfterSeconds('12'), 12);
});

test('describeRateLimit：说人话、带秒数、绝不出现「加载失败」', () => {
  const zh = describeRateLimit(tZh, 60);
  assert.equal(zh.title, lookup(zhLocale, 'state.rateLimited'));
  assert.match(zh.hint, /60/);
  assert.match(zh.hint, /限速/);
  assert.doesNotMatch(zh.title, /加载失败/);
  assert.doesNotMatch(zh.hint, /加载失败/);

  const en = describeRateLimit(tEn, 30);
  assert.equal(en.title, lookup(enLocale, 'state.rateLimited'));
  assert.match(en.hint, /30/);
  assert.doesNotMatch(en.title, /Failed to load/);
});

test('describeRateLimit：占位符被真秒数替换（不把 {{seconds}} 甩上屏）', () => {
  for (const [t, locale] of [
    [tZh, zhLocale],
    [tEn, enLocale],
  ] as const) {
    const { hint } = describeRateLimit(t, 45);
    assert.doesNotMatch(hint, /\{\{|\}\}/, '占位符没被替换');
    assert.match(hint, /45/);
    assert.ok(lookup(locale, 'state.rateLimitedHint'), 'locale 缺 rateLimitedHint');
  }
});

test('429 文案双语齐备：两份 locale 都有 rateLimited / rateLimitedHint 且互不相等（真译过）', () => {
  for (const key of ['state.rateLimited', 'state.rateLimitedHint']) {
    assert.ok(lookup(zhLocale, key), `zh 缺 ${key}`);
    assert.ok(lookup(enLocale, key), `en 缺 ${key}`);
  }
  assert.notEqual(lookup(zhLocale, 'state.rateLimited'), lookup(enLocale, 'state.rateLimited'));
});

// —— 静态锁：429 必须被三个面按「限速」处理，而不是被当抖动类 ——
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf-8');

test('静态锁：重试判据里 429 与鉴权类同级（触发即不再排）', () => {
  const src = read('./data-state.ts');
  assert.match(src, /status\s*===\s*429/, 'data-state.ts 没有把 429 判成不重试');
});

test('静态锁：429 → rate_limited 语义态，且带 Retry-After', () => {
  const hook = read('../hooks/use-semantic-query.ts');
  assert.match(hook, /429/, 'use-semantic-query 没识别 429');
  assert.match(hook, /rate_limited/, 'use-semantic-query 没把 429 映射成 rate_limited');
  assert.match(hook, /retryAfterSeconds/, 'rate_limited 态没带 retryAfterSeconds');
  const client = read('./api-client.ts');
  assert.match(client, /retry-after/i, 'api-client 没读后端 Retry-After 头');
});

test('静态锁：渲染面 429 走专门文案，绝不落到「加载失败」', () => {
  const view = read('../components/semantic/semantic-state.tsx');
  assert.match(view, /rate_limited/, 'SemanticState 没处理 rate_limited');
  // 取词只有一处（`@/lib/rate-limit` 的 describeRateLimit，本文件上方已逐字锁过它取
  // `state.rateLimited`）；这里锁的是渲染面**确实用了那一个取词口**，而不是自己拼一句。
  assert.match(view, /describeRateLimit\(/, 'SemanticState 没走 describeRateLimit 取词');
  assert.doesNotMatch(view, /state\.rateLimited/, 'SemanticState 又自取一次 key（第二份取词口）');
  const index = view.indexOf("phase === 'rate_limited'");
  assert.ok(index >= 0, '没找到 rate_limited 分支');
  const branch = view.slice(index, index + 900);
  assert.doesNotMatch(branch, /state\.loadFailed/, 'rate_limited 分支里出现了「加载失败」');
});
