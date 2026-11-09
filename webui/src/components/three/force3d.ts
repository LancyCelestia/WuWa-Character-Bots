// 三维力导向（简报 C 席：现有 d3-force 只有二维）。这里不引 d3-force-3d（多一个依赖、且它的
// 三维实现与二维版本 API 分叉），直接用同一支 d3-force 的 forceSimulation 在**三轴**上跑：
// 斥力=平方反比（Coulomb），另加一个**向心球壳**力把结果收成球——这就是「球」而不是「云」的成因。
// 纯度口径沿用 lib/graph-layout.ts：固定种子 LCG、phyllotaxis 初始排布、固定 tick 数、输入不被变异。
import { forceLink, forceManyBody, forceSimulation } from 'd3-force';
import type { SimulationNodeDatum } from 'd3-force';

export interface Sim3DNode extends SimulationNodeDatum {
  id: string;
  /// 三维坐标与速度（d3-force 的 SimulationNodeDatum 只有 x/y 两轴，三维要自己补）。
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  /// 归一化后（-1..1）的坐标，渲染层乘半径用。
  nx: number;
  ny: number;
  nz: number;
  /// 节点显示半径（度数三档，与 2D 同口径）。
  radius: number;
}

interface Sim3DLink {
  source: string | Sim3DNode;
  target: string | Sim3DNode;
}

const LCG_SEED = 20260919;
const TICKS = 240;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5)); // 与 2D 同一枚黄金角

function lcg(seed: number): () => number {
  let state = seed % 2147483647;
  if (state <= 0) state += 2147483646;
  return () => {
    state = (state * 16807) % 2147483647;
    return (state - 1) / 2147483646;
  };
}

function nodeRadius(degree: number): number {
  if (degree >= 8) return 14;
  if (degree >= 3) return 10;
  return 7;
}

/**
 * @param nodes 节点（需要 id）
 * @param edges 边（端点必须都在 nodes 内；调用方已过滤）
 * @param shellRadius 场景坐标下的球壳半径（渲染层相机距离同数量级）
 */
export function computeSphereLayout(
  nodes: readonly { id: string }[],
  edges: readonly { source: string; target: string }[],
  shellRadius: number
): Map<string, Sim3DNode> {
  const out = new Map<string, Sim3DNode>();
  if (nodes.length === 0) return out;

  const degrees = new Map<string, number>();
  for (const node of nodes) degrees.set(node.id, 0);
  for (const edge of edges) {
    if (degrees.has(edge.source)) degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    if (degrees.has(edge.target)) degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }

  // 斐波那契球面初始排布：起点就均匀铺在球面上，力只做微调（比三维随机云收敛稳定得多）。
  const count = nodes.length;
  const spread = shellRadius * 0.6;
  const simNodes: Sim3DNode[] = nodes.map((node, index) => {
    const y = 1 - (index / Math.max(1, count - 1)) * 2;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = index * GOLDEN_ANGLE;
    const degree = degrees.get(node.id) ?? 0;
    return {
      id: node.id,
      radius: nodeRadius(degree),
      x: spread * Math.cos(theta) * ring,
      y: spread * y,
      z: spread * Math.sin(theta) * ring,
      vx: 0,
      vy: 0,
      vz: 0,
      nx: 0,
      ny: 0,
      nz: 0,
    };
  });
  const simLinks: Sim3DLink[] = edges.map((edge) => ({ source: edge.source, target: edge.target }));

  const simulation = forceSimulation<Sim3DNode>(simNodes)
    // 连线：把直接相连的节点拉近（距离按 shellRadius 缩放，图规模变大时布局仍居中）。
    .force('link', forceLink<Sim3DNode, Sim3DLink>(simLinks).id((node) => node.id).distance(shellRadius * 0.42).strength(0.35))
    // 斥力：d3-force 的 forceManyBody 在三维下也按三轴距离算，负值=斥力。
    .force('charge', forceManyBody().strength(-shellRadius * 0.55))
    // 向心球壳：每个 tick 沿径向把节点拉回球面（本文件自定义，见下）。这是「球」的来源。
    .force('shell', shellForce(shellRadius, 0.22))
    .randomSource(lcg(LCG_SEED))
    .stop();
  for (let tick = 0; tick < TICKS; tick += 1) simulation.tick();

  // 归一化到单位球：渲染层只关心方向与相对大小，半径交给渲染层统一缩放。
  let maxLen = 0.0001;
  for (const node of simNodes) maxLen = Math.max(maxLen, Math.hypot(node.x, node.y, node.z));
  for (const node of simNodes) {
    // 落在原点的节点（数值退化）给个固定方向，避免除零后看不见。
    const len = Math.hypot(node.x, node.y, node.z);
    const k = len > 0.0001 ? 1 / maxLen : 0;
    node.nx = k ? node.x * k : 1;
    node.ny = node.y * k;
    node.nz = node.z * k;
    out.set(node.id, node);
  }
  return out;
}

/**
 * 自定义向心球壳力：把 |p| 拉向 shellRadius，且**保留方向**——节点只在径向内外浮动，
 * 所以最终形状是球面而不是一团。这是「球」的来源（d3 的三个内置力都不做这件事）。
 */
function shellForce(shellRadius: number, strength: number) {
  let nodes: Sim3DNode[] = [];
  const force = () => {
    for (const node of nodes) {
      const len = Math.hypot(node.x, node.y, node.z);
      if (len < 0.0001) continue;
      // 径向误差（正值=在球外、要往里），乘 strength 得到本 tick 的速度修正。
      const pull = ((shellRadius - len) / len) * strength * 0.5;
      node.vx += node.x * pull;
      node.vy += node.y * pull;
      node.vz += node.z * pull;
    }
  };
  force.initialize = (list: Sim3DNode[]) => {
    nodes = list;
  };
  return force;
}

/**
 * 三维版本的地球式测地线边：两点间插值后再归一化回球面，避免连线穿透球体内部——从外面看
 * 是贴着球面走的弧，这是「球」之所以成立的一半（另一半是节点本身贴面）。
 * 返回顶点数组（x,y,z 平铺），供 LineSegments/BufferGeometry 直接吃。
 */
export function geodesicPoints(
  from: readonly [number, number, number],
  to: readonly [number, number, number],
  radius: number,
  segments = 12
): number[] {
  const [ax, ay, az] = from;
  const [bx, by, bz] = to;
  const points: number[] = [];
  for (let i = 0; i <= segments; i += 1) {
    const t = i / segments;
    const x = ax + (bx - ax) * t;
    const y = ay + (by - ay) * t;
    const z = az + (bz - az) * t;
    const len = Math.hypot(x, y, z);
    if (len < 0.0001) {
      // 对径点中段会穿过原点：直接取球面上任意一个可行方向（数值退化，视觉上无差别）。
      points.push(radius, 0, 0);
      continue;
    }
    const k = radius / len;
    points.push(x * k, y * k, z * k);
  }
  return points;
}
