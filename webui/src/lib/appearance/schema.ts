// 外观配置的**范围真身**：每个可调数值的上下界与步长（UI3 追加二）。
//
// 单一出处：外观页的滑块、导入时的钳制、单测的极值覆盖全部从这里读——
// 界值写两遍必漂（一处改成 0–50、另一处还是 0–40，导入就能绕过滑块）。
// 键形与配置树同构：`RANGES.glass.blur` 对应 `AppearanceConfig['glass']['blur']`。

export const RANGES = {
  wallpaper: {
    opacity: { min: 0, max: 100, step: 1 },
    blur: { min: 0, max: 40, step: 1 },
    brightness: { min: 40, max: 160, step: 1 },
    contrast: { min: 40, max: 160, step: 1 },
    saturation: { min: 0, max: 200, step: 1 },
    scale: { min: 100, max: 150, step: 1 },
    playbackRate: { min: 0.25, max: 2, step: 0.05 },
  },
  aurora: {
    count: { min: 1, max: 6, step: 1 },
    speed: { min: 0.1, max: 3, step: 0.1 },
    intensity: { min: 0, max: 100, step: 1 },
    blur: { min: 20, max: 120, step: 2 },
  },
  iridescence: {
    hueRange: { min: 0, max: 360, step: 5 },
    speed: { min: 0.4, max: 4, step: 0.1 },
    thickness: { min: 1, max: 4, step: 1 },
    opacity: { min: 0, max: 100, step: 1 },
  },
  glow: {
    radius: { min: 0, max: 40, step: 1 },
    strength: { min: 0, max: 100, step: 1 },
  },
  glass: {
    blur: { min: 0, max: 40, step: 1 },
    saturation: { min: 100, max: 200, step: 1 },
    opacity: { min: 40, max: 100, step: 1 },
    borderStrength: { min: 0, max: 100, step: 1 },
    elevation: { min: 0, max: 24, step: 1 },
    grainOpacity: { min: 0, max: 10, step: 0.5 },
  },
  typography: {
    // 五档字号各自可调（用户原话：「字体大小…全部改成自定义大小px」）。
    pageSize: { min: 12, max: 40, step: 1 },
    cardSize: { min: 10, max: 32, step: 1 },
    rootSize: { min: 10, max: 32, step: 1 },
    captionSize: { min: 9, max: 24, step: 1 },
    numSize: { min: 16, max: 72, step: 1 },
    lineHeight: { min: 1.1, max: 2.2, step: 0.05 },
    letterSpacing: { min: -2, max: 4, step: 0.5 },
  },
  motion: {
    speed: { min: 0.5, max: 2, step: 0.1 },
  },
  layout: {
    sidebarWidth: { min: 200, max: 400, step: 4 },
    headerHeight: { min: 44, max: 96, step: 4 },
    gridColumns: { min: 1, max: 6, step: 1 },
    cardMinWidth: { min: 200, max: 480, step: 8 },
    // 用户 2026-10-19：「ui圆角、间距等全部改成自定义大小px」——滑块就是 px 读数。
    radius: { min: 0, max: 40, step: 1 },
    spacing: { min: 0.5, max: 2, step: 0.05 },
  },
  charts: {
    decimals: { min: 0, max: 3, step: 1 },
  },
  logView: {
    lineHeight: { min: 1.2, max: 2, step: 0.05 },
    maxLines: { min: 100, max: 5000, step: 100 },
  },
  interaction: {
    toastDismissMs: { min: 1500, max: 8000, step: 250 },
  },
  notifications: {
    soundVolume: { min: 0, max: 100, step: 1 },
  },
  locale: {
    fixedOffset: { min: -12, max: 14, step: 1 },
  },
  a11y: {
    focusRingWidth: { min: 1, max: 6, step: 1 },
  },
  density: {
    pageSize: { min: 10, max: 200, step: 10 },
  },
} as const;

export type RangeGroups = typeof RANGES;

/** 把数值钳进界内并落到步长栅格（防 0.30000000000000004 这类浮点毛刺）。 */
export function clampRange(value: number, range: { min: number; max: number; step: number }): number {
  if (!Number.isFinite(value)) return range.min;
  const decimals = String(range.step).split('.')[1]?.length ?? 0;
  // 先按步长的十进制位数收一次再栅格化：0.30000000000000004 与 0.3 必须落到同一格，
  // 否则浮点毛刺会被 round 判成「差一格」。
  const clean = Number(value.toFixed(decimals + 1));
  const stepped = Math.round((clean - range.min) / range.step) * range.step + range.min;
  const bounded = Math.min(range.max, Math.max(range.min, stepped));
  return Number(bounded.toFixed(decimals + 1));
}
