import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force';
import type { SimulationNodeDatum } from 'd3-force';

// 记忆图谱确定性布局纯函数（spec webui-pages2 §3.4/§5.3）：
// 输入 nodes/edges/画布尺寸 → 输出 id→坐标 Map。
// 确定性三要素：①固定种子 LCG（Lehmer 16807，种子 20260919）供 d3-force 全部抖动取随机；
// ②phyllotaxis（黄金角）显式初始排布；③固定 300 tick 同步跑完，无动画循环。
// 纯度：内部深拷贝，入参不被变异；同输入两次运行坐标全等（容差 0，单测锁死）。

export interface LayoutInputNode {
  id: string;
}

export interface LayoutInputEdge {
  source: string;
  target: string;
}

export interface LayoutPoint {
  x: number;
  y: number;
}

const LCG_SEED = 20260919;
const TICKS = 300;
const PAD = 24; // 画布内边距（=栅格最大刻度 24px）
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/** 固定种子 Lehmer LCG（16807 乘子，模 2147483647）：与 d3-force 内置 lcg 同构但种子显式。 */
function lcg(seed: number): () => number {
  let state = seed % 2147483647;
  if (state <= 0) state += 2147483646;
  return () => {
    state = (state * 16807) % 2147483647;
    return (state - 1) / 2147483646;
  };
}

/** 节点显示半径三档（按度数）：布局 collide 与 canvas 绘制共用同一口径。 */
export function nodeRadius(degree: number): number {
  if (degree >= 8) return 14;
  if (degree >= 3) return 10;
  return 7;
}

/** 度数表（关联度）：仅统计节点集内端点（缺失端点的边不计）。 */
export function computeDegrees(nodes: readonly LayoutInputNode[], edges: readonly LayoutInputEdge[]): Map<string, number> {
  const degrees = new Map<string, number>();
  for (const node of nodes) degrees.set(node.id, 0);
  for (const edge of edges) {
    if (degrees.has(edge.source)) degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    if (degrees.has(edge.target)) degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }
  return degrees;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  degree: number;
}

interface SimLink {
  source: string | SimNode;
  target: string | SimNode;
}

export function computeGraphLayout(
  nodes: readonly LayoutInputNode[],
  edges: readonly LayoutInputEdge[],
  width: number,
  height: number
): Map<string, LayoutPoint> {
  const points = new Map<string, LayoutPoint>();
  if (nodes.length === 0 || width <= 0 || height <= 0) return points;

  const degrees = computeDegrees(nodes, edges);
  const ids = new Set(nodes.map((node) => node.id));
  // 防御性过滤：端点不在节点集内的边不进力模型（后端截断已保证，此处不改变有效输入行为）。
  const validEdges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));

  // phyllotaxis 初始排布（黄金角），围绕画布中心。
  const spread = 10 * Math.sqrt(nodes.length);
  const simNodes: SimNode[] = nodes.map((node, index) => ({
    id: node.id,
    degree: degrees.get(node.id) ?? 0,
    x: width / 2 + spread * Math.sqrt(index) * Math.cos(index * GOLDEN_ANGLE),
    y: height / 2 + spread * Math.sqrt(index) * Math.sin(index * GOLDEN_ANGLE),
  }));
  const simLinks: SimLink[] = validEdges.map((edge) => ({ source: edge.source, target: edge.target }));

  const simulation = forceSimulation(simNodes)
    .force('link', forceLink<SimNode, SimLink>(simLinks).id((node) => node.id).distance(60).strength(0.5))
    .force('charge', forceManyBody().strength(-120))
    .force('collide', forceCollide<SimNode>((node) => nodeRadius(node.degree) + 4))
    .force('x', forceX(width / 2).strength(0.05))
    .force('y', forceY(height / 2).strength(0.05))
    .randomSource(lcg(LCG_SEED))
    .stop();
  for (let tick = 0; tick < TICKS; tick += 1) simulation.tick();

  // 归一化到画布：保纵横比居中，只缩不放（span 异常时退化为原坐标），pad 内收。
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const node of simNodes) {
    minX = Math.min(minX, node.x ?? 0);
    maxX = Math.max(maxX, node.x ?? 0);
    minY = Math.min(minY, node.y ?? 0);
    maxY = Math.max(maxY, node.y ?? 0);
  }
  const spanX = maxX - minX;
  const spanY = maxY - minY;
  const scale = Math.min(
    spanX > 0.001 ? (width - PAD * 2) / spanX : 1,
    spanY > 0.001 ? (height - PAD * 2) / spanY : 1,
    1
  );
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  for (const node of simNodes) {
    points.set(node.id, {
      x: ((node.x ?? 0) - centerX) * scale + width / 2,
      y: ((node.y ?? 0) - centerY) * scale + height / 2,
    });
  }
  return points;
}
