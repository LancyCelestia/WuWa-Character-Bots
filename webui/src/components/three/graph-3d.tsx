import { useEffect, useRef } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  NormalBlending,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Raycaster,
  Scene,
  SphereGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';
import type { MemoryGraphEdge, MemoryGraphNode, MemoryGraphNodeType } from '@/lib/api-client';
import { computeSphereLayout, geodesicPoints } from './force3d';
import { PROFILES, type Quality } from './quality';

// 记忆图谱「真 3D」渲染件（C 席）。全部 three 具名导入 —— 不许 `import * as THREE`：
// 具名导入 + three 的 sideEffects 白名单才让 rollup 只打进真用到的类。
//
// 生命周期纪律（硬要求 5—7，漏任何一条都会在来回切页时攒 WebGL context 直到页面崩）：
//   · 挂载建一次 renderer/场景/材质，卸载一次性全释放；
//   · 尺寸变化走 ResizeObserver + rAF 合帧，**不重建 renderer**；
//   · 动画循环收在单个 rafId 里，卸载先 cancelAnimationFrame 再拆场景；
//   · reduced-motion ⇒ 不跑循环，只画静态帧；交互时按需补一帧；
//   · 页签隐藏时停循环（后台不该烧 GPU）。

const TYPE_TOKEN: Record<MemoryGraphNodeType, string> = {
  person: '--chart-1',
  group: '--chart-2',
  memory: '--chart-3',
  conversation: '--chart-4',
  rule: '--chart-5',
};

const SPHERE_RADIUS = 90;
const CAMERA_DISTANCE = 250;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/**
 * 语义 token → three 的 Color。
 *
 * 🔴 不能用 `new Color(readToken(x))`：three 的样式解析器只认 hex / rgb() / hsl() / 颜色名，
 * **不认 oklch()** —— 而这块 UI 的值册大半是 oklch（--chart-2…5 / --foreground /
 * --muted-foreground 全是）。直接喂进去会**静默回落成白色**，五种节点类型糊成一片白。
 * 这里改走浏览器自己的颜色解析：先把 `var(--x)` 挂到一个探针元素上让 var/color-mix 链解析，
 * 再用 1×1 canvas 涂一格读回 sRGB 字节——凡浏览器能画的颜色它都能转，零依赖。
 */
function resolveTokenColor(name: string): Color {
  const probe = document.createElement('span');
  probe.style.color = `var(${name})`;
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const css = getComputedStyle(probe).color;
  probe.remove();
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return new Color(0, 0, 0);
  ctx.fillStyle = css;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return new Color().setRGB(r / 255, g / 255, b / 255);
}

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export interface Graph3DProps {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  quality: Quality;
}

export function Graph3D({ nodes, edges, selectedId, onSelect, quality }: Graph3DProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  // 交互态走 ref：场景只该因为「换数据/换质量档」重建，不该因为父组件换个闭包就拆掉 WebGL。
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  // 高亮句柄：挂载 effect 建，选中 effect 调（不重建场景）。
  const highlightRef = useRef<((id: string | null) => void) | null>(null);

  // ---- 场景：随 nodes/edges/quality 重建 ----
  useEffect(() => {
    const host = hostRef.current;
    if (!host || nodes.length === 0) return;

    const profile = PROFILES[quality];
    const reduced = prefersReducedMotion();
    const palette = new Map<MemoryGraphNodeType, Color>();
    for (const [type, token] of Object.entries(TYPE_TOKEN)) palette.set(type as MemoryGraphNodeType, resolveTokenColor(token));
    const fallbackColor = resolveTokenColor('--muted-foreground');
    const accent = resolveTokenColor('--primary');
    const background = resolveTokenColor('--background');
    const foreground = resolveTokenColor('--foreground');
    // 亮底上加法混合会把一切推到白（`--background` 浅雾底已经接近白），浅色节点会被糊掉；
    // 暗底则相反，加法混合才好看。所以星点混色方式跟着底色走。
    const lightBackground = background.getHSL({ h: 0, s: 0, l: 0 }).l > 0.5;
    // 节点色统一往前景色靠 12%：暗底上提亮、亮底上压深，两向都是「提高与背景的对比」，
    // 不引入任何新色值（宪法：色只从 token 派生）。
    for (const [type, color] of palette) palette.set(type, color.clone().lerp(foreground, 0.12));

    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: quality !== 'low', powerPreference: 'high-performance' });
    } catch {
      // 没有 WebGL（驱动黑名单 / 远程桌面 / 显存耗尽）：如实上报，页面据此回退 2D，不硬造。
      host.dispatchEvent(new CustomEvent('graph3d:unsupported', { bubbles: true }));
      return;
    }
    // 硬要求 5：不夹像素比 = 每帧把 dpr² 倍像素推给 GPU，高分屏风扇立刻起飞。
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, profile.maxPixelRatio));
    renderer.setSize(host.clientWidth || 1, host.clientHeight || 1, false);
    renderer.setClearColor(background, 1);
    const canvas = renderer.domElement;
    canvas.className = 'block h-full w-full touch-none select-none';
    canvas.style.cursor = 'grab';

    const scene = new Scene();
    const camera = new PerspectiveCamera(50, (host.clientWidth || 1) / (host.clientHeight || 1), 1, 2000);

    // ---- 布局 ----
    const valid = new Set(nodes.map((node) => node.id));
    const validEdges = edges.filter((edge) => valid.has(edge.source) && valid.has(edge.target) && edge.source !== edge.target);
    const layout = computeSphereLayout(nodes, validEdges, SPHERE_RADIUS);

    // ---- 节点：一份球几何 + 每类型一份材质（共享，避免 200 份 GPU 缓冲）----
    const sphereGeom = new SphereGeometry(1, 20, 14);
    const typeMats = new Map<MemoryGraphNodeType, MeshBasicMaterial>();
    for (const [type, color] of palette) typeMats.set(type, new MeshBasicMaterial({ color }));
    const fallbackMat = new MeshBasicMaterial({ color: fallbackColor });
    // 选中环：略大的线框球，只在选中那颗上开关可见性（开关不产生新材质）。
    const ringGeom = new SphereGeometry(1, 16, 12);
    const ringMat = new MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.5, wireframe: true });
    const ring = new Mesh(ringGeom, ringMat);
    ring.visible = false;
    scene.add(ring);

    const pickTargets: Mesh[] = [];
    const items: { id: string; mesh: Mesh; pos: Vector3; baseScale: number }[] = [];
    for (const node of nodes) {
      const sim = layout.get(node.id);
      if (!sim) continue;
      // 场坐标 = 单位球方向 × 球壳半径（节点贴在球面上）。
      const pos = new Vector3(sim.nx, sim.ny, sim.nz).normalize().multiplyScalar(SPHERE_RADIUS * 1.01);
      const mesh = new Mesh(sphereGeom, typeMats.get(node.type) ?? fallbackMat);
      // 半径：2D 的 7/10/14px 直接搬来在球面上偏大，按 0.34 缩（三档差别仍可辨）。
      const baseScale = sim.radius * 0.34;
      mesh.scale.setScalar(baseScale);
      mesh.position.copy(pos);
      mesh.userData.nodeId = node.id;
      scene.add(mesh);
      pickTargets.push(mesh);
      items.push({ id: node.id, mesh, pos, baseScale });
    }

    // ---- 连线：测地线弧（贴球面走，不穿球心），按权重降序取前 maxEdges 条 ----
    const sorted = [...validEdges].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, profile.maxEdges);
    const verts: number[] = [];
    for (const edge of sorted) {
      const from = layout.get(edge.source);
      const to = layout.get(edge.target);
      if (!from || !to) continue;
      const arc = geodesicPoints([from.nx, from.ny, from.nz], [to.nx, to.ny, to.nz], SPHERE_RADIUS * 1.005, 14);
      for (let i = 0; i + 5 < arc.length; i += 3) {
        verts.push(arc[i], arc[i + 1], arc[i + 2], arc[i + 3], arc[i + 4], arc[i + 5]);
      }
    }
    const edgeGeom = new BufferGeometry();
    edgeGeom.setAttribute('position', new BufferAttribute(new Float32Array(verts), 3));
    const edgeMat = new LineBasicMaterial({ color: accent, transparent: true, opacity: 0.26 });
    const edgeLines = new LineSegments(edgeGeom, edgeMat);
    scene.add(edgeLines);

    // ---- 粒子（质量档决定数量；低档 0 = 连几何都不建）----
    let stars: Points | null = null;
    let starGeom: BufferGeometry | null = null;
    let starMat: PointsMaterial | null = null;
    if (profile.particles > 0) {
      const starPos = new Float32Array(profile.particles * 3);
      for (let i = 0; i < profile.particles; i += 1) {
        const y = 1 - (i / Math.max(1, profile.particles - 1)) * 2;
        const ringR = Math.sqrt(Math.max(0, 1 - y * y));
        const theta = i * GOLDEN_ANGLE;
        const r = SPHERE_RADIUS * (1.55 + ((i * 37) % 100) / 100);
        starPos[i * 3] = Math.cos(theta) * ringR * r;
        starPos[i * 3 + 1] = y * r;
        starPos[i * 3 + 2] = Math.sin(theta) * ringR * r;
      }
      starGeom = new BufferGeometry();
      starGeom.setAttribute('position', new BufferAttribute(starPos, 3));
      starMat = new PointsMaterial({
        color: accent,
        // 亮底上星点必须够小够淡，否则白花花一片盖过节点（加法混合在浅雾底上直接过曝）。
        size: lightBackground ? 0.9 : 1.4,
        sizeAttenuation: true,
        transparent: true,
        opacity: lightBackground ? 0.3 : 0.5,
        blending: lightBackground ? NormalBlending : AdditiveBlending,
        depthWrite: false,
      });
      stars = new Points(starGeom, starMat);
      scene.add(stars);
    }

    host.appendChild(canvas);

    // ---- 相机球坐标：拖拽改 theta/phi，滚轮/捏合改 radius ----
    const spherical = { theta: 0, phi: Math.PI / 2, radius: CAMERA_DISTANCE };
    const applyCamera = () => {
      const sinPhi = Math.sin(spherical.phi);
      camera.position.set(
        spherical.radius * sinPhi * Math.sin(spherical.theta),
        spherical.radius * Math.cos(spherical.phi),
        spherical.radius * sinPhi * Math.cos(spherical.theta)
      );
      camera.lookAt(0, 0, 0);
    };
    applyCamera();

    let rafId = 0;
    let running = false;
    const render = () => renderer.render(scene, camera);
    const loop = () => {
      spherical.theta += 0.0012; // 缓慢自转，球看起来是立体的
      applyCamera();
      render();
      rafId = requestAnimationFrame(loop);
    };
    const ensureFrame = () => {
      if (!running) render();
    };
    const startLoop = () => {
      if (running || reduced) return; // reduced-motion：永不启动循环
      running = true;
      rafId = requestAnimationFrame(loop);
    };
    const stopLoop = () => {
      running = false;
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0;
    };

    // ---- 选中：放大这颗 + 套上环；只动 scale/可见性，不换材质（共享材质一换就是整类全变）----
    const applyHighlight = (id: string | null) => {
      for (const item of items) {
        item.mesh.scale.setScalar(item.id === id ? item.baseScale * 1.6 : item.baseScale);
      }
      const active = id ? items.find((item) => item.id === id) : undefined;
      if (active) {
        ring.visible = true;
        ring.position.copy(active.pos);
        ring.scale.setScalar(active.baseScale * 2.4);
      } else {
        ring.visible = false;
      }
      ensureFrame();
    };
    highlightRef.current = applyHighlight;
    applyHighlight(selectedRef.current);

    // ---- 指针：单指/鼠标拖拽旋转，双指捏合缩放，点击选中 ----
    let pointerDown: { id: number; x: number; y: number; moved: boolean } | null = null;
    const pointers = new Map<number, { x: number; y: number }>();
    let pinchDistance = 0;
    let wheelAccum = 0;
    const raycaster = new Raycaster();
    const ndc = new Vector2();

    const pickAt = (clientX: number, clientY: number): MemoryGraphNode | null => {
      const rect = canvas.getBoundingClientRect();
      ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      const first = raycaster.intersectObjects(pickTargets, false)[0];
      const id = (first?.object.userData as { nodeId?: string } | undefined)?.nodeId;
      return id ? (nodes.find((node) => node.id === id) ?? null) : null;
    };

    const zoomBy = (factor: number) => {
      // 夹在近/远平面内留余量：不夹会穿进球心或缩到看不见。
      spherical.radius = Math.min(700, Math.max(130, spherical.radius / factor));
      applyCamera();
      ensureFrame();
    };

    const onPointerDown = (event: PointerEvent) => {
      canvas.setPointerCapture?.(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
        pointerDown = null; // 双指期间不做点击判定
        return;
      }
      pointerDown = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    };

    const onPointerMove = (event: PointerEvent) => {
      const prev = pointers.get(event.pointerId);
      if (!prev) {
        if (!pointerDown) canvas.style.cursor = pickAt(event.clientX, event.clientY) ? 'pointer' : 'grab';
        return;
      }
      const dx = event.clientX - prev.x;
      const dy = event.clientY - prev.y;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size >= 2) {
        // 双指捏合：按两指间距比例直接缩放（不做惯性，手感更可控）。
        const [a, b] = [...pointers.values()];
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinchDistance > 0 && distance > 0) zoomBy(distance / pinchDistance);
        pinchDistance = distance;
        return;
      }
      if (!pointerDown) return;
      if (Math.abs(event.clientX - pointerDown.x) > 3 || Math.abs(event.clientY - pointerDown.y) > 3) {
        pointerDown.moved = true;
      }
      if (pointerDown.moved) {
        // 与地球仪同手感：水平绕极轴旋转，垂直夹在 ±0.12 防翻过头。
        spherical.theta -= dx * 0.006;
        spherical.phi = Math.min(Math.PI - 0.12, Math.max(0.12, spherical.phi - dy * 0.006));
        applyCamera();
        ensureFrame();
      }
    };

    const endPointer = (event: PointerEvent) => {
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinchDistance = 0;
      if (pointerDown && pointerDown.id === event.pointerId) {
        const wasClick = !pointerDown.moved;
        pointerDown = null;
        if (wasClick) onSelectRef.current(pickAt(event.clientX, event.clientY)?.id ?? null);
      }
      canvas.style.cursor = 'grab';
    };

    const onWheel = (event: WheelEvent) => {
      event.preventDefault(); // 3D 球在滚，页面不该跟着滚
      // 触控板一帧发几十个 wheel：先累积成比例再夹紧，避免一甩就到最近/最远。
      wheelAccum += event.deltaY * 0.0012;
      const step = Math.max(-0.2, Math.min(0.2, wheelAccum));
      wheelAccum -= step;
      zoomBy(Math.exp(-step));
    };

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', endPointer);
    canvas.addEventListener('pointercancel', endPointer);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    // ---- 尺寸：ResizeObserver 合帧（硬要求 7：每次 resize 事件重建 renderer 是致命写法）----
    let pending = false;
    const applySize = () => {
      pending = false;
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (w === 0 || h === 0) return;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, profile.maxPixelRatio));
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      ensureFrame();
    };
    const observer = new ResizeObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(applySize);
    });
    observer.observe(host);

    const onVisibility = () => {
      if (document.hidden) stopLoop();
      else startLoop();
    };
    document.addEventListener('visibilitychange', onVisibility);

    render();
    startLoop();

    // ---- 卸载：停循环 → 断监听 → 释放 GPU 资源 → 摘 canvas ----
    return () => {
      stopLoop();
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', endPointer);
      canvas.removeEventListener('pointercancel', endPointer);
      canvas.removeEventListener('wheel', onWheel);
      for (const item of items) scene.remove(item.mesh);
      scene.remove(ring);
      scene.remove(edgeLines);
      if (stars) scene.remove(stars);
      sphereGeom.dispose();
      ringGeom.dispose();
      for (const material of typeMats.values()) material.dispose();
      fallbackMat.dispose();
      ringMat.dispose();
      edgeGeom.dispose();
      edgeMat.dispose();
      starGeom?.dispose();
      starMat?.dispose();
      renderer.dispose();
      // dispose() 只释放 GPU 资源，**WebGL 上下文本身仍活着**等 GC —— 来回切十几趟就会撞上
      // 浏览器「Too many active WebGL contexts」上限，之后整页的 GL 一起失效。
      // forceContextLoss() 主动丢上下文，切页次数不再受上下文上限约束。
      renderer.forceContextLoss();
      // dispose() 只放 GPU 资源不摘 DOM；不摘的话容器里会叠一层层死 canvas。
      if (canvas.parentNode === host) host.removeChild(canvas);
      highlightRef.current = null;
    };
  }, [nodes, edges, quality]);

  // ---- 选中变化：不重建场景，只改高亮 ----
  useEffect(() => {
    highlightRef.current?.(selectedId);
  }, [selectedId]);

  return <div ref={hostRef} className='relative h-full w-full' />;
}
