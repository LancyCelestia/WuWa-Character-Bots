import { useEffect, useMemo, useRef, useState } from 'react';
import type { MemoryGraphEdge, MemoryGraphNode, MemoryGraphNodeType } from '@/lib/api-client';
import { computeDegrees, computeGraphLayout, nodeRadius } from '@/lib/graph-layout';

// 记忆图谱 canvas 渲染件（spec §3.4）：静态布局一帧绘制（布局=graph-layout 纯函数），
// 交互=拖拽平移/滚轮缩放/hover 高亮邻接/点击选中；高分屏按 devicePixelRatio 缩放。
// 取色一律 getComputedStyle 读语义 token（宪法③），透明度用 globalAlpha（不造新色值）。
// 性能口径（PERF1 2026-09-19，F8 补录）：绘制每帧都会整幅重画（拖拽/缩放/hover 各一次），
// 故「与交互态无关」的量一律提到渲染外——取色一次/主题、节点索引一次/nodes、
// 查询命中集一次/(nodes,query)，循环体内只做查表；位图尺寸只在真的变了才重设。

const TYPE_TOKEN: Record<MemoryGraphNodeType, string> = {
  person: '--chart-1',
  group: '--chart-2',
  memory: '--chart-3',
  conversation: '--chart-4',
  rule: '--chart-5',
};

const TYPE_KEYS = Object.keys(TYPE_TOKEN) as MemoryGraphNodeType[];

function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

interface Transform {
  x: number;
  y: number;
  k: number;
}

const ZOOM_MIN = 0.2;
const ZOOM_MAX = 4;

export function MemoryCanvas({
  nodes,
  edges,
  query,
  selectedId,
  onSelect,
}: {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  query: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, k: 1 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [themeTick, setThemeTick] = useState(0);
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number; moved: boolean } | null>(null);

  const layout = useMemo(() => computeGraphLayout(nodes, edges, size.w, size.h), [nodes, edges, size.w, size.h]);
  const degrees = useMemo(() => computeDegrees(nodes, edges), [nodes, edges]);
  // 绘制期用 id 查节点：一次建表（O(n)/(nodes) 变化），不再每帧 new Map(nodes.map(...))。
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  // 取色：与交互态无关，只随主题切换重读（每帧 8 次 getComputedStyle 会强制样式重算）。
  const palette = useMemo(
    () => ({
      colors: new Map<MemoryGraphNodeType, string>(TYPE_KEYS.map((type) => [type, readToken(TYPE_TOKEN[type])])),
      fallback: readToken('--muted-foreground'),
      primary: readToken('--primary'),
      foreground: readToken('--foreground'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [themeTick]
  );
  // 查询命中集：小写+子串匹配每节点一次/(nodes,query) 变化，不再每帧做 3 次/边 + 1 次/节点。
  // null=无过滤词（与改造前 `needle === ''` 分支同语义：一律不淡化）。
  const matchedIds = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return null;
    const hit = new Set<string>();
    for (const node of nodes) {
      if (node.label.toLowerCase().includes(needle)) hit.add(node.id);
    }
    return hit;
  }, [nodes, query]);

  // 容器尺寸自适应（ResizeObserver；初始挂载即测一次）。
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const measure = () =>
      setSize((prev) => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        // 同尺寸不回写：挂载时「立即测一次」与 ResizeObserver 的强制首报必然同值，
        // 各自产出一个新对象会让整幅绘制 effect 白跑一遍。
        if (prev.w === w && prev.h === h) return prev;
        return { w, h };
      });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  // 主题切换（亮/暗 class）→ 重取 token 重绘。
  useEffect(() => {
    const observer = new MutationObserver(() => setThemeTick((value) => value + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // 滚轮缩放（pointer 固定）：React 合成 wheel 被动化，原生监听 passive:false 才能 preventDefault。
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      setTransform((prev) => {
        const k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, prev.k * Math.exp(-event.deltaY * 0.0015)));
        const ratio = k / prev.k;
        return { k, x: px - (px - prev.x) * ratio, y: py - (py - prev.y) * ratio };
      });
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, []);

  const toWorld = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return { x: (clientX - rect.left - transform.x) / transform.k, y: (clientY - rect.top - transform.y) / transform.k };
  };

  const pick = (clientX: number, clientY: number): MemoryGraphNode | null => {
    const world = toWorld(clientX, clientY);
    let best: MemoryGraphNode | null = null;
    let bestDist = Infinity;
    for (const node of nodes) {
      const point = layout.get(node.id);
      if (!point) continue;
      const dist = Math.hypot(point.x - world.x, point.y - world.y);
      const threshold = nodeRadius(degrees.get(node.id) ?? 0) + 4 / transform.k;
      if (dist <= threshold && dist < bestDist) {
        best = node;
        bestDist = dist;
      }
    }
    return best;
  };

  // 一帧绘制：布局静态，仅交互态变化触发重绘（无动画循环，省 CPU）。
  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || size.w === 0 || size.h === 0) return;
    const dpr = window.devicePixelRatio || 1;
    const pixelW = Math.round(size.w * dpr);
    const pixelH = Math.round(size.h * dpr);
    // 赋值 width/height 会让浏览器丢弃并重建 backing store（本页容器 1100×480@2x ≈ 8.1 MiB/次，
    // 静态推断未跑浏览器），而平移/缩放/hover 每帧都走到这里——尺寸没变就只清画布，不重新分配。
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, size.w, size.h);
    context.translate(transform.x, transform.y);
    context.scale(transform.k, transform.k);

    const { colors, fallback, primary, foreground } = palette;
    const filtering = matchedIds !== null;

    for (const edge of edges) {
      const from = layout.get(edge.source);
      const to = layout.get(edge.target);
      if (!from || !to) continue;
      const sourceType = nodeById.get(edge.source)?.type;
      context.strokeStyle = (sourceType && colors.get(sourceType)) || fallback;
      const incident = hoverId !== null && (edge.source === hoverId || edge.target === hoverId);
      const bothDim = filtering && !matchedIds.has(edge.source) && !matchedIds.has(edge.target);
      context.globalAlpha = bothDim ? 0.06 : incident ? 0.7 : 0.22;
      context.lineWidth = incident ? 1.5 : 1;
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
      context.stroke();
    }

    // 标签字体/基线是常量和，逐节点重复赋值没有意义（赋值次数：节点数 → 每帧一次）。
    context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif';
    context.textBaseline = 'middle';
    for (const node of nodes) {
      const point = layout.get(node.id);
      if (!point) continue;
      const radius = nodeRadius(degrees.get(node.id) ?? 0);
      const dimmed = filtering && !matchedIds.has(node.id);
      context.globalAlpha = dimmed ? 0.15 : 1;
      context.fillStyle = colors.get(node.type) ?? fallback;
      context.beginPath();
      context.arc(point.x, point.y, radius, 0, Math.PI * 2);
      context.fill();
      if (node.id === selectedId || node.id === hoverId) {
        context.globalAlpha = 1;
        context.strokeStyle = primary;
        context.lineWidth = 2;
        context.beginPath();
        context.arc(point.x, point.y, radius + 3, 0, Math.PI * 2);
        context.stroke();
      }
      // 标签：hover/选中恒显；放大到 1.6 倍以上全量显示（memory 节点=整句长标签）。
      if (node.id === selectedId || node.id === hoverId || transform.k >= 1.6) {
        context.globalAlpha = dimmed ? 0.3 : 1;
        context.fillStyle = foreground;
        const text = node.label.length > 18 ? `${node.label.slice(0, 17)}…` : node.label;
        context.fillText(text, point.x + radius + 4, point.y);
      }
    }
    context.globalAlpha = 1;
  }, [nodes, edges, layout, degrees, nodeById, palette, matchedIds, query, selectedId, hoverId, transform, size, themeTick]);

  return (
    <div ref={containerRef} className='relative h-full w-full'>
      <canvas
        ref={canvasRef}
        className='block h-full w-full cursor-grab touch-none select-none active:cursor-grabbing'
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          dragRef.current = { startX: event.clientX, startY: event.clientY, baseX: transform.x, baseY: transform.y, moved: false };
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (drag) {
            const dx = event.clientX - drag.startX;
            const dy = event.clientY - drag.startY;
            if (Math.abs(dx) > 4 || Math.abs(dy) > 4) drag.moved = true;
            if (drag.moved) setTransform((prev) => ({ ...prev, x: drag.baseX + dx, y: drag.baseY + dy }));
            return;
          }
          const hit = pick(event.clientX, event.clientY);
          const hitId = hit?.id ?? null;
          if (hitId !== hoverId) setHoverId(hitId);
        }}
        onPointerUp={(event) => {
          const drag = dragRef.current;
          dragRef.current = null;
          if (drag && !drag.moved) {
            const hit = pick(event.clientX, event.clientY);
            onSelect(hit?.id ?? null);
          }
        }}
        onPointerLeave={() => {
          dragRef.current = null;
          setHoverId(null);
        }}
      />
    </div>
  );
}
