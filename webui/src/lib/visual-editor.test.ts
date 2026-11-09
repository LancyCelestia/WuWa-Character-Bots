import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('./visual-editor.ts', import.meta.url), 'utf8').replace("import { apiRequest } from './api-client';", 'const apiRequest = () => { throw new Error("no network in ordering test"); };');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext } });
const { moveElement, newElement, updateStyle, scopeKey, nextExpectedVersion } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);
test('drag ordering moves exactly one element without mutating the document', () => {
  const before = ['first', 'second', 'third'];
  assert.deepEqual(moveElement(before, 0, 2), ['second', 'third', 'first']);
  assert.deepEqual(before, ['first', 'second', 'third']);
  assert.deepEqual(moveElement(before, -1, 2), before);
  assert.deepEqual(moveElement(before, 0, 99), before);
});
test('chart.box has a nested raw numeric series default matching backend _series (list[list[float]])', () => {
  // 真身：visual_spec.py `_series()` 只收 list[list[float]]，非 list 的列整列丢弃 ⇒
  // 扁平 [1,2,3] 会被静默清空，图表无数据。
  const box = newElement('chart.box');
  assert.equal(box.kind, 'chart.box');
  const series = box.data.series;
  assert.ok(Array.isArray(series) && series.length > 0, 'series 必须非空');
  assert.ok(
    (series as unknown[]).every(
      (column) => Array.isArray(column) && column.length > 0 && column.every((n) => typeof n === 'number' && Number.isFinite(n)),
    ),
    'series 必须是 list[list[number]]',
  );
  // 柱图保留兼容 preset（父页面另标不可用），折线同形修正。
  assert.deepEqual(newElement('chart.bar').data.series, [[1, 2]]);
  assert.deepEqual(newElement('chart.line').data.series, [[1, 2, 3]]);
});
test('updateStyle removes a cleared property instead of storing Number("") === 0 and never mutates the input spec', () => {
  const spec = { version: 1, title: '标题', layout: 'single', elements: [], style: { size: 'md', spacing: 8, weight: 'medium', color: 'accent' } };
  const clearedSpacing = updateStyle(spec, 'spacing', '');
  assert.equal('spacing' in (clearedSpacing.style ?? {}), false);
  assert.equal(clearedSpacing.style?.spacing, undefined);
  const clearedSize = updateStyle(spec, 'size', '');
  assert.equal('size' in (clearedSize.style ?? {}), false);
  const clearedColor = updateStyle(spec, 'color', '');
  assert.equal('color' in (clearedColor.style ?? {}), false);
  const clearedWeight = updateStyle(spec, 'weight', '');
  assert.equal('weight' in (clearedWeight.style ?? {}), false);
  const set = updateStyle(spec, 'spacing', '12');
  assert.equal(set.style?.spacing, 12);
  assert.equal(set.style?.size, 'md', '未动的键必须保留');
  assert.equal(spec.style?.spacing, 8, '不得改原 spec');
});
test('nextExpectedVersion follows the real read/save/reset shapes and is never "current + 1"', () => {
  // 真身 visual_layouts.py read()：version=生效行版本, exact_version=本 scope 精确行版本, next_version=exact_version
  assert.equal(nextExpectedVersion({ version: 3, source: 'platform', exact_version: 0, next_version: 0, spec: null }), 0, '继承平台默认时必须用 exact_version，用 version 会 409');
  assert.equal(nextExpectedVersion({ version: 2, source: 'exact', exact_version: 2, next_version: 2, spec: null }), 2);
  assert.equal(nextExpectedVersion({ version: 4, source: 'none', exact_version: 4, next_version: 4, spec: null }), 4, 'tombstone 行同样取精确行版本');
  // save()/reset() 响应不含 exact_version；version === next_version === 新写的当前版本
  assert.equal(nextExpectedVersion({ version: 5, next_version: 5, spec: null, degraded: [] }), 5);
  assert.equal(nextExpectedVersion({ version: 6, next_version: 6, spec: null, tombstone: true }), 6);
  // 关键反证：next_version 从不是「当前+1」——它就是下次要带的 expected_version
  assert.equal(nextExpectedVersion({ version: 1, source: 'exact', exact_version: 1, next_version: 1, spec: null }), 1);
});
test('scopeKey is a pure, field-order-stable four-axis serialization for async scope association', () => {
  const scope = { platform: 'qq', instance: '', group: '', card: 'weather' };
  assert.equal(scopeKey(scope), 'platform=qq&instance=&group=&card=weather');
  assert.equal(scopeKey({ card: 'weather', group: '', instance: '', platform: 'qq' }), scopeKey(scope));
  assert.equal(scopeKey({ platform: 'tg', instance: 'i1', group: 'g2', card: 'c3' }), 'platform=tg&instance=i1&group=g2&card=c3');
});
