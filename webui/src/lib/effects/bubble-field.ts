// 气泡场（算法逐字移植自参考站 daniya.top 的 `assets/js/main.js` 第 219-352 行）。
//
// 为什么是纯函数：参考站把整场状态关在 IIFE 闭包里、靠 `requestAnimationFrame` 推进，
// 于是每个常数（重力、摆动幅度、淡出距离、回收阈值）都无法被断言，只能靠肉眼看截图。
// 这里把「算下一帧」与「画这一帧」拆开——本文件只算，画在 `components/effects/bubble-field.tsx`。
//
// 参考站原常数（逐字摘录，改动必须在此处注明理由）：
//   r    = 2 + rand * 10
//   vy   = -(0.16 + rand * 0.55)          ← 全是负数，气泡一律上升
//   vx   = (rand - 0.5) * 0.28
//   seed = rand * Math.PI * 2
//   wobA = 0.25 + rand * 0.8              ← 横向摆动幅度
//   wobF = 0.4 + rand * 0.9               ← 横向摆动频率
//   a    = 0.05 + rand * 0.3              ← 基准透明度（很低，靠叠加出「釉」）
//   收回 = y + r < -30 || life > 5200
//   爆点 r = 34 + rand * 30、a = 0.5、环透明度 0.34 * (1 - life)、life 每帧 +0.045
//   粒子数 = Math.round(Math.min(74, Math.max(26, W / 20)))

/** 参考站的四色盘：海蓝 / 星空紫 / 热熔暖橙 / 冷白。**顺序即下标语义**，别重排。 */
export const BUBBLE_COLORS: ReadonlyArray<readonly [number, number, number]> = [
  [142, 217, 236],
  [185, 168, 255],
  [255, 185, 138],
  [210, 228, 245],
];

/** 粒子数上下界（与参考站 `Math.min(74, Math.max(26, W / 20))` 同值）。 */
export const MIN_BUBBLES = 26;
export const MAX_BUBBLES = 74;

/** 一颗气泡的静态属性（每帧不变的部分）。 */
export interface Bubble {
  x: number;
  y: number;
  /** 半径（CSS px） */
  r: number;
  /** 纵向速度（负 = 上升） */
  vy: number;
  /** 横向基准速度 */
  vx: number;
  /** 正弦摆动的相位种子 */
  seed: number;
  /** 摆动幅度 */
  wobA: number;
  /** 摆动频率 */
  wobF: number;
  /** 基准透明度 */
  a: number;
  c: readonly [number, number, number];
  /** 已存活帧数 */
  life: number;
}

/** 一颗气泡在某一帧的完整状态（静态属性 + 现算的透明度）。 */
export interface BubbleFrame extends Bubble {
  alpha: number;
}

/** 点击爆点的环。`r` 是初始半径，`radius` / `alpha` 按 `life` 现算。 */
export interface Pop {
  x: number;
  y: number;
  /** 初始半径 */
  r: number;
  /** 当前半径（`r * (1 + e * 1.7)`，e 为 easeOutCubic） */
  radius: number;
  /** 当前环透明度（`0.34 * (1 - life)`） */
  alpha: number;
  c: readonly [number, number, number];
  life: number;
}

/** 一整场的状态。 */
export interface Field {
  bubbles: readonly Bubble[];
  pops: readonly Pop[];
}

/** 空场常量：`off` 档 / 首帧之前复用同一份，避免每次渲染造新数组。 */
export const EMPTY_FIELD: Field = { bubbles: [], pops: [] };

/**
 * 粒子数。参考站公式原样保留，但**先判有限性**：
 * `viewportWidth` 在 SSR / 隐藏容器里可能是 NaN 或 0，原式会算出 NaN 颗。
 */
export function fieldCount(viewportWidth: number): number {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return MIN_BUBBLES;
  return Math.round(Math.min(MAX_BUBBLES, Math.max(MIN_BUBBLES, viewportWidth / 20)));
}

/**
 * 生成一颗气泡。
 *
 * `rand` 由调用方注入（参考站用 `Math.random`）——测试给固定序列，生产给真随机。
 * **取值顺序与参考站逐字一致**：x → y → r → vy → vx → seed → wobA → wobF → a → c。
 * 顺序一变，「r 恒等于 2」这类断言就全部作废。
 */
export function spawnBubble(
  rand: () => number,
  width: number,
  height: number,
  initial: boolean
): Bubble {
  return {
    x: rand() * width,
    // initial：散布在视口内（首屏就不空）；否则从底部之下 40px 排队进场。
    y: initial ? rand() * height : height + 40,
    r: 2 + rand() * 10,
    vy: -(0.16 + rand() * 0.55),
    vx: (rand() - 0.5) * 0.28,
    seed: rand() * Math.PI * 2,
    wobA: 0.25 + rand() * 0.8,
    wobF: 0.4 + rand() * 0.9,
    a: 0.05 + rand() * 0.3,
    c: BUBBLE_COLORS[Math.floor(rand() * BUBBLE_COLORS.length)] ?? BUBBLE_COLORS[0],
    life: 0,
  };
}

/**
 * 推进一帧。`t` 是字段级帧计数器（参考站的 `t`，每帧 +1）。
 *
 * 位移两条：
 *   y += vy                                  ← 匀速上升
 *   x += vx + sin(t * 0.008 * wobF + seed) * wobA * 0.14   ← 正弦摆动
 *
 * 透明度两条（只在给了 `viewportHeight` 时才衰减，未知高度时保持基准值）：
 *   进入底部 90px 内 → 按距离淡入
 *   进入顶部 120px 内 → 按距离淡出
 */
export function stepBubble(b: Bubble, t: number, viewportHeight?: number): BubbleFrame {
  const y = b.y + b.vy;
  const x = b.x + b.vx + Math.sin(t * 0.008 * b.wobF + b.seed) * b.wobA * 0.14;
  let alpha = b.a;
  if (viewportHeight !== undefined) {
    if (y > viewportHeight - 90) alpha *= Math.max(0, (viewportHeight - y) / 90);
    if (y < 120) alpha *= Math.max(0, y / 120);
  }
  return { ...b, x, y, life: b.life + 1, alpha };
}

/** 这颗气泡该不该重生：越过顶部回收线（`y + r < -30`）或活满 5200 帧。 */
export function respawn(b: Bubble): boolean {
  return b.y + b.r < -30 || b.life > 5200;
}

/**
 * 在 (x, y) 生成一个点击爆点。半径 34–64，环透明度从 0.34 线性衰减到 0。
 *
 * 与参考站的一处**有意的差异**：它先 `spawn(true)` 再覆盖坐标与半径，白烧掉 10 次随机数；
 * 这里直接取色，不再生成一颗随后被丢弃的气泡。
 */
export function burstAt(x: number, y: number, rand: () => number): Pop {
  const r = 34 + rand() * 30;
  return {
    x,
    y,
    r,
    radius: r,
    alpha: 0.34,
    c: BUBBLE_COLORS[Math.floor(rand() * BUBBLE_COLORS.length)] ?? BUBBLE_COLORS[0],
    life: 0,
  };
}

/** 推进所有爆点一帧：`life += 0.045`，到 1 即淘汰；半径按 easeOutCubic 扩张 1.7 倍。 */
export function stepPops(pops: readonly Pop[]): Pop[] {
  const out: Pop[] = [];
  for (const p of pops) {
    const life = p.life + 0.045;
    if (life >= 1) continue;
    const e = 1 - Math.pow(1 - life, 3);
    out.push({
      ...p,
      life,
      radius: p.r * (1 + e * 1.7),
      alpha: 0.34 * (1 - life),
    });
  }
  return out;
}
