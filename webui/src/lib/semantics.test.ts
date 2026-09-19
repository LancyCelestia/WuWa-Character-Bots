import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isNotFound, pickEnabledCollections, toStackRows } from './semantics.ts';
import type { KnowledgeCollection, TokenFamilyRow } from '@/lib/api-client';

// 三条「不说谎判据」的确定性单测（审计 F17 P1-⑦ / F21 / F23-②）。
// 运行方式：node --test src/lib/semantics.test.ts（Node ≥23 原生类型剥离，零新依赖）。

function block(value: number | null) {
  return { value, known_rows: value === null ? 0 : 1, unknown_rows: value === null ? 1 : 0, quality: value === null ? ('unknown' as const) : ('complete' as const) };
}

function family(input: number | null, output: number | null, cacheRead: number | null, cacheCreation: number | null): TokenFamilyRow {
  return {
    family: 'model-x',
    calls: 1,
    tokens: { input: block(input), output: block(output), cache_read: block(cacheRead), cache_creation: block(cacheCreation) },
  };
}

function collection(enabled: boolean): KnowledgeCollection {
  return { id: 'c', name: 'n', description: '', enabled, source: 's', count: null, reason: null };
}

test('isNotFound：404 状态码判为「端点未部署」，且必须在控制面统一文案下仍然成立', () => {
  // 控制面把 404 包成统一 message（_app.py），旧实现按 /HTTP 404/ 匹配文案 → 恒不命中。
  assert.equal(isNotFound({ phase: 'error', message: '请求的资源或操作不可用。', status: 404 }), true);
  assert.equal(isNotFound({ phase: 'error', message: 'HTTP 404: Not Found' }), false); // 只有文案不算
  assert.equal(isNotFound({ phase: 'error', message: 'x', status: 500 }), false);
  assert.equal(isNotFound({ phase: 'error', message: 'x', status: 422 }), false);
  assert.equal(isNotFound({ phase: 'loading' }), false);
  assert.equal(isNotFound({ phase: 'ok', data: {} }), false);
});

test('pickEnabledCollections：只留启用项，异常输入降级为空而不抛错', () => {
  assert.deepEqual(pickEnabledCollections([collection(true), collection(false)]).length, 1);
  assert.deepEqual(pickEnabledCollections([]), []);
  assert.deepEqual(pickEnabledCollections(null), []);
  assert.deepEqual(pickEnabledCollections(undefined), []);
  // 后端字段漂移出 null 元素时不得炸整棵布局（AppShell 在错误边界之外）。
  assert.deepEqual(pickEnabledCollections([null] as unknown as KnowledgeCollection[]), []);
});

test('toStackRows：缓存是输入的子集，堆叠段和恒等于输入+输出（不双计）', () => {
  const [row] = toStackRows([family(100, 20, 30, 10)]);
  assert.equal(row.uncached, 60);
  assert.equal(row.cache_read, 30);
  assert.equal(row.cache_creation, 10);
  assert.equal(row.output, 20);
  const sum = (row.uncached ?? 0) + (row.cache_read ?? 0) + (row.cache_creation ?? 0) + (row.output ?? 0);
  assert.equal(sum, 120); // 100 + 20，而非旧写法的 160
});

test('toStackRows：缓存未上报按 0 处理，输入原样保留', () => {
  const [row] = toStackRows([family(100, 20, null, null)]);
  assert.equal(row.uncached, 100);
  assert.equal(row.cache_read, null);
  assert.equal(row.cache_creation, null);
});

test('toStackRows：输入未知则各段未知（绝不拿 0 冒充 0 个 token）', () => {
  const [row] = toStackRows([family(null, null, null, null)]);
  assert.equal(row.uncached, null);
  assert.equal(row.output, null);
});

test('toStackRows：缓存之和反超输入（数据自相矛盾）时不拆段，宁少一层信息也不画不成立的柱', () => {
  const [row] = toStackRows([family(50, 20, 60, 10)]);
  assert.equal(row.uncached, 50);
  assert.equal(row.cache_read, null);
  assert.equal(row.cache_creation, null);
  assert.equal(row.output, 20);
});

test('toStackRows：族顺序与 family 原样透传（含无名族 null）', () => {
  const rows = toStackRows([family(10, 1, 0, 0), { ...family(1, 1, 0, 0), family: null }]);
  assert.deepEqual(rows.map((row) => row.family), ['model-x', null]);
});
