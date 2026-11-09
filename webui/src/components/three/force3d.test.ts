import assert from 'node:assert/strict';
import { test } from 'node:test';
import { computeSphereLayout, geodesicPoints } from './force3d.ts';
import { autoQuality, shouldUse3D, PROFILES } from './quality.ts';

// 记忆图谱「真 3D」的纯函数面单测（C 席，UI3 追加一）。
// 运行方式：node --test src/components/three/force3d.test.ts（Node ≥23 原生 TS 类型剥离）。
// 渲染件（graph-3d.tsx）依赖 WebGL，不在单测面；这里锁的是它唯一的输入：布局与定档。

const NODES = [
  { id: 'person:a' },
  { id: 'person:b' },
  { id: 'group:g1' },
  { id: 'conv:g1:a' },
  { id: 'conv:g1:b' },
  { id: 'memory:m1' },
  { id: 'rule:q1' },
];

const EDGES = [
  { source: 'person:a', target: 'conv:g1:a' },
  { source: 'person:b', target: 'conv:g1:a' },
  { source: 'group:g1', target: 'conv:g1:a' },
  { source: 'conv:g1:a', target: 'conv:g1:b' },
  { source: 'person:a', target: 'memory:m1' },
  { source: 'person:a', target: 'rule:q1' },
];

const R = 90;

test('确定性：同输入两次运行坐标全等（容差 0）', () => {
  const first = computeSphereLayout(NODES, EDGES, R);
  const second = computeSphereLayout(NODES, EDGES, R);
  assert.equal(first.size, NODES.length);
  for (const [id, node] of first) {
    const again = second.get(id);
    assert.ok(again);
    assert.equal(node.nx, again.nx);
    assert.equal(node.ny, again.ny);
    assert.equal(node.nz, again.nz);
  }
});

test('真三维：坐标不是零平面——z 轴确有分布（否则就是伪 3D）', () => {
  const layout = computeSphereLayout(NODES, EDGES, R);
  const zs = [...layout.values()].map((node) => node.nz);
  assert.ok(Math.max(...zs) - Math.min(...zs) > 0.2, `z 跨度过小：${Math.max(...zs) - Math.min(...zs)}`);
  const ys = [...layout.values()].map((node) => node.ny);
  assert.ok(Math.max(...ys) - Math.min(...ys) > 0.2, 'y 跨度过小');
});

test('球壳：归一化后所有节点落在单位球面上（|p| ≤ 1 且不塌缩到原点）', () => {
  const layout = computeSphereLayout(NODES, EDGES, R);
  for (const node of layout.values()) {
    const len = Math.hypot(node.nx, node.ny, node.nz);
    assert.ok(len <= 1.0001, `半径越界 ${len}`);
    assert.ok(len > 0.05, `节点塌缩到原点 ${len}`);
  }
});

test('纯度：入参不被变异', () => {
  const nodes = NODES.map((node) => ({ ...node }));
  const edges = EDGES.map((edge) => ({ ...edge }));
  computeSphereLayout(nodes, edges, R);
  assert.deepEqual(nodes, NODES);
  assert.deepEqual(edges, EDGES);
});

test('边界：空节点 → 空 Map（不炸）', () => {
  assert.equal(computeSphereLayout([], EDGES, R).size, 0);
});

test('测地线：每条弧上的点都贴球面（不穿球心）', () => {
  const layout = computeSphereLayout(NODES, EDGES, R);
  const a = layout.get('person:a');
  const b = layout.get('conv:g1:a');
  assert.ok(a && b);
  const points = geodesicPoints([a.nx, a.ny, a.nz], [b.nx, b.ny, b.nz], R, 8);
  // 每 3 个浮点为一个顶点，每个顶点的模长都必须等于半径。
  assert.equal(points.length % 3, 0);
  for (let i = 0; i < points.length; i += 3) {
    const len = Math.hypot(points[i], points[i + 1], points[i + 2]);
    assert.ok(Math.abs(len - R) < 0.001, `顶点不贴球面 ${len} ≠ ${R}`);
  }
});

test('降级判据：窄屏 <768 或核数 ≤4 不上 WebGL，边界值明确', () => {
  assert.equal(shouldUse3D({ width: 767, hardwareConcurrency: 16 }), false);
  assert.equal(shouldUse3D({ width: 768, hardwareConcurrency: 16 }), true);
  assert.equal(shouldUse3D({ width: 1920, hardwareConcurrency: 4 }), false);
  assert.equal(shouldUse3D({ width: 1920, hardwareConcurrency: 5 }), true);
});

test('定档：reduced-motion 一律低档（静态帧），高分高核高档，其余中档', () => {
  const base = { width: 1920, hardwareConcurrency: 16, devicePixelRatio: 2, reducedMotion: false };
  assert.equal(autoQuality(base), 'high');
  assert.equal(autoQuality({ ...base, width: 1024 }), 'medium');
  assert.equal(autoQuality({ ...base, hardwareConcurrency: 6 }), 'medium');
  assert.equal(autoQuality({ ...base, reducedMotion: true }), 'low');
});

test('三档都在：像素比夹紧上限与粒子数递减，低档无粒子且比值 1', () => {
  assert.deepEqual(Object.keys(PROFILES).sort(), ['high', 'low', 'medium']);
  assert.equal(PROFILES.low.maxPixelRatio, 1);
  assert.equal(PROFILES.low.particles, 0);
  assert.ok(PROFILES.medium.particles < PROFILES.high.particles);
  assert.ok(PROFILES.low.maxEdges < PROFILES.high.maxEdges);
  assert.ok(PROFILES.high.maxPixelRatio <= 2, '像素比上限不得高于 2（高分屏烧 GPU 红线）');
});
