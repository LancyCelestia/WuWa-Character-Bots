import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computeDegrees, computeGraphLayout, nodeRadius } from './graph-layout.ts';

// 记忆图谱布局确定性单测（spec webui-pages2 §5.3）：同输入两次运行坐标全等（容差 0）。
// 运行方式：node --test src/lib/graph-layout.test.ts（Node ≥23 原生 TS 类型剥离，零新依赖）。

const NODES = [
  { id: 'person:a' },
  { id: 'person:b' },
  { id: 'person:c' },
  { id: 'group:g1' },
  { id: 'conv:g1:a' },
  { id: 'conv:g1:b' },
  { id: 'memory:m1' },
  { id: 'memory:m2' },
  { id: 'rule:q1' },
  { id: 'rule:nick:a' },
  { id: 'person:hub' },
  { id: 'conv:g1:hub' },
];

const EDGES = [
  { source: 'person:a', target: 'conv:g1:a', kind: 'speaks_in', weight: 3 },
  { source: 'person:b', target: 'conv:g1:a', kind: 'speaks_in', weight: 1 },
  { source: 'person:a', target: 'conv:g1:b', kind: 'speaks_in', weight: 2 },
  { source: 'group:g1', target: 'conv:g1:a', kind: 'hosts', weight: 4 },
  { source: 'group:g1', target: 'conv:g1:b', kind: 'hosts', weight: 2 },
  { source: 'person:a', target: 'memory:m1', kind: 'about', weight: 1 },
  { source: 'person:c', target: 'memory:m2', kind: 'about', weight: 1 },
  { source: 'person:a', target: 'rule:q1', kind: 'learned_rule', weight: 1 },
  { source: 'person:a', target: 'rule:nick:a', kind: 'nickname', weight: 1 },
  { source: 'person:hub', target: 'conv:g1:hub', kind: 'speaks_in', weight: 9 },
  // 端点缺失的边：布局必须防御性忽略，不得炸。
  { source: 'person:ghost', target: 'conv:g1:a', kind: 'speaks_in', weight: 1 },
];

const W = 800;
const H = 600;

test('确定性：同输入两次运行坐标全等（容差 0）', () => {
  const first = computeGraphLayout(NODES, EDGES, W, H);
  const second = computeGraphLayout(NODES, EDGES, W, H);
  assert.equal(first.size, NODES.length);
  assert.equal(second.size, NODES.length);
  assert.deepEqual([...first.entries()], [...second.entries()]);
});

test('确定性：不同随机种子次序无关——先跑大图再跑小图，小图结果不变', () => {
  const small = [{ id: 'x1' }, { id: 'x2' }, { id: 'x3' }];
  const edges = [{ source: 'x1', target: 'x2' }, { source: 'x2', target: 'x3' }];
  const lone = computeGraphLayout(small, edges, W, H);
  computeGraphLayout(NODES, EDGES, W, H); // 大图先跑，污染全局状态也不得影响后续
  const again = computeGraphLayout(small, edges, W, H);
  assert.deepEqual([...lone.entries()], [...again.entries()]);
});

test('纯度：入节数组/边数组不被变异', () => {
  const nodes = NODES.map((node) => ({ ...node }));
  const edges = EDGES.map((edge) => ({ ...edge }));
  computeGraphLayout(nodes, edges, W, H);
  assert.deepEqual(nodes, NODES);
  assert.deepEqual(edges, EDGES);
});

test('边界：全部坐标落在画布内（pad=24）且恰好覆盖全部节点', () => {
  const points = computeGraphLayout(NODES, EDGES, W, H);
  assert.equal(points.size, NODES.length);
  for (const point of points.values()) {
    assert.ok(point.x >= 0 && point.x <= W, `x=${point.x} 越界`);
    assert.ok(point.y >= 0 && point.y <= H, `y=${point.y} 越界`);
  }
});

test('边界：空节点 / 零尺寸画布 → 空 Map（不炸）', () => {
  assert.equal(computeGraphLayout([], EDGES, W, H).size, 0);
  assert.equal(computeGraphLayout(NODES, EDGES, 0, H).size, 0);
  assert.equal(computeGraphLayout(NODES, EDGES, W, -1).size, 0);
});

test('半径三档：度数 0-2→7、3-7→10、≥8→14', () => {
  assert.equal(nodeRadius(0), 7);
  assert.equal(nodeRadius(2), 7);
  assert.equal(nodeRadius(3), 10);
  assert.equal(nodeRadius(7), 10);
  assert.equal(nodeRadius(8), 14);
  assert.equal(nodeRadius(40), 14);
});

test('度数表：出现过的端点计数正确，缺失端点不出现在表内', () => {
  const degrees = computeDegrees(NODES, EDGES);
  assert.equal(degrees.get('person:a'), 5);
  assert.equal(degrees.get('group:g1'), 2);
  assert.equal(degrees.get('person:ghost'), undefined);
});
