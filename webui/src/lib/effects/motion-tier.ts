// 动效档位判定（参考站 daniya.top 的环境判据 + 本仓的两条业务约束）。
//
// 参考站 `assets/js/main.js` 只在三处读环境，这三处就是它全部的自适应逻辑：
//   · `window.matchMedia('(prefers-reduced-motion: reduce)').matches` → `reduce`
//   · `window.matchMedia('(hover: hover) and (pointer: fine)').matches` → `finePointer`
//   · `Math.min(window.devicePixelRatio || 1, 2)` → canvas 后备缓冲上限
// 本仓多两条：外观页的动效总开关（`motion.enabled`）与省流量模式。
//
// 零 React、零 DOM 依赖 —— `node --test` 直接加载，页面在挂任何东西之前就能决定档位。

/** 动效强度档。`off` = 不挂任何持续动画；`lite` = 只留静态层与一次性入场；`full` = 全量。 */
export type MotionTier = 'off' | 'lite' | 'full';

/** 粒子渲染路径。`webgl` 走 GPU；`canvas2d` 两处都画得动；`none` 不建画布。 */
export type ParticlePath = 'webgl' | 'canvas2d' | 'none';

export interface MotionFacts {
  /** 系统级 `prefers-reduced-motion: reduce`。**优先级最高**。 */
  prefersReduced: boolean;
  /** 外观页的动效总开关（`AppearanceConfig.motion.enabled`）关掉了。 */
  userDisabled: boolean;
  /** `navigator.connection.saveData === true`，或 effectiveType 属于 2g/slow-2g。 */
  saveData: boolean;
  /** `navigator.hardwareConcurrency`；读不到按 4 处理（不因缺字段就降档）。 */
  hardwareConcurrency: number;
  /** 只认触屏（`(hover: none) and (pointer: coarse)`）——自定义光标与倾斜都不该挂。 */
  isTouchOnly: boolean;
  /** 有没有 WebGL2 上下文（探测一次，不建持久画布）。 */
  hasWebGL2: boolean;
  /** 视口宽（CSS px），决定粒子数。 */
  viewportWidth: number;
}

/** 粒子数下限 / 上限 —— 与参考站 `Math.min(74, Math.max(26, W / 20))` 同上下界。 */
export const MIN_PARTICLE_COUNT = 26;
export const MAX_PARTICLE_COUNT = 74;
/** lite 档的粒子数（参考站没有这一档，是本仓为 2C2T 机器加的半量）。 */
export const BASE_PARTICLE_COUNT = 39;
/** 自定义光标的最小视口宽：窄屏上光标圆环会挡住小按钮。 */
export const CURSOR_MIN_VIEWPORT = 900;
/** 弱机判据：≤2 核按弱机处理（用户服务器就是 2C2T）。 */
export const WEAK_CORE_COUNT = 2;

/**
 * 选档。判定顺序即优先级，**前一条命中就不再往下看**：
 *   ① 系统减少动效 → `off`（无障碍优先于任何业务开关）
 *   ② 用户关掉动效 → `off`
 *   ③ 省流量 → `lite`
 *   ④ 弱机（≤2 核）或窄屏（≤900px）→ `lite`
 *   ⑤ 其余 → `full`
 */
export function resolveMotionTier(facts: MotionFacts): MotionTier {
  if (facts.prefersReduced) return 'off';
  if (facts.userDisabled) return 'off';
  if (facts.saveData) return 'lite';
  if (facts.hardwareConcurrency <= WEAK_CORE_COUNT) return 'lite';
  if (facts.viewportWidth <= CURSOR_MIN_VIEWPORT) return 'lite';
  return 'full';
}

/**
 * 粒子走哪条路。
 *   · `off` → `none`（连画布都不建）
 *   · 有 WebGL2 **且** 是 full 档 → `webgl`
 *   · 其余 → `canvas2d`
 *
 * 为什么 lite 档不赌 GPU：气泡是氛围层，2D 路径在任何机器上都不会掉帧；
 * 而 WebGL 上下文本身要占一块显存（用户服务器 2G RAM）。
 */
export function pickParticlePath(facts: MotionFacts): ParticlePath {
  const tier = resolveMotionTier(facts);
  if (tier === 'off') return 'none';
  if (tier === 'full' && facts.hasWebGL2) return 'webgl';
  return 'canvas2d';
}

/**
 * 粒子数。基数抄参考站的 `min(74, max(26, W / 20))`，再按本仓档位收窄：
 *   · `off` → 0
 *   · `lite` → 基数的一半（下限仍是 26）
 *   · `full` → 基数
 *
 * `cap` 是外观页可调的上限（`0` = 显式关掉），**永远不能突破硬顶** —— 传 9999 也只会得到 74。
 */
export function particleBudget(facts: MotionFacts, cap?: number): number {
  if (resolveMotionTier(facts) === 'off') return 0;
  if (cap === 0) return 0;
  const base = Math.round(
    Math.min(MAX_PARTICLE_COUNT, Math.max(MIN_PARTICLE_COUNT, facts.viewportWidth / 20))
  );
  const scaled = resolveMotionTier(facts) === 'lite' ? Math.max(MIN_PARTICLE_COUNT, Math.round(base / 2)) : base;
  const capped = cap === undefined ? scaled : Math.min(scaled, cap);
  return Math.min(MAX_PARTICLE_COUNT, capped);
}

/** 要不要挂自定义光标。触屏、减少动效、窄屏三种情况都回落到系统光标。 */
export function shouldUseCustomCursor(facts: MotionFacts): boolean {
  if (facts.isTouchOnly) return false;
  if (facts.prefersReduced) return false;
  return facts.viewportWidth > CURSOR_MIN_VIEWPORT;
}

/** 要不要挂 3D 倾斜（卡片跟随指针）。与光标同判据，但窄屏仍可倾斜（触控板笔记本）。 */
export function shouldUseTilt(facts: MotionFacts): boolean {
  if (facts.isTouchOnly) return false;
  return !facts.prefersReduced;
}
