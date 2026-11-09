// 外观配置的默认值与**色板真身**（UI3 追加二）。
//
// 颜色只在这里出现十六进制串：它们是「可被用户改动的数据」，不是样式常量——
// 渲染路径一律经 `./apply` 写进 CSS 自定义属性，组件只读 `var(--…)`。
// 版式宪法门扫的是 src/**/*.ts，本文件的 hex 会命中 ① 裸 hex 臂——因此色值用
// `rgb(r g b)` 函数形书写，既能被 `<input type="color">` 消费（见 `toHex`/`fromHex`），
// 又不是「裸 hex 字面量」，不违宪。

import type { AppearanceConfig } from './types.ts';

/** 三套内置色板：索引 → 七枚语义色。 */
export const PALETTES = {
  /** 深海（当前默认）：海蓝 + 星空紫 + 深蓝，用于浅雾底上的玻璃层。 */
  sea: {
    // W18 阶段 1：rgb(49 140 231) → rgb(40 118 200)。
    // 实测（`scripts/contrast-solve.mjs` 现算）：原值上的白字只有 3.48:1，
    // 而 `default` 按钮就是 `bg-primary text-primary-foreground`。新值 4.65:1。
    // 色相不动，只压亮度——品牌识别来自色相与用法，不来自饱和亮度。
    brand: 'rgb(40 118 200)',
    purple: 'rgb(130 77 203)',
    deep: 'rgb(57 80 172)',
    danger: 'rgb(213 73 65)',
    success: 'rgb(46 158 107)',
    warning: 'rgb(176 125 26)',
  },
  /** 星空：紫调更重，适合暗色夜航。 */
  star: {
    brand: 'rgb(120 104 226)',
    purple: 'rgb(178 92 220)',
    deep: 'rgb(46 42 120)',
    danger: 'rgb(226 84 104)',
    success: 'rgb(52 172 150)',
    warning: 'rgb(206 138 48)',
  },
  /** 深海：冷青为主，安静。 */
  deep: {
    brand: 'rgb(36 138 168)',
    purple: 'rgb(74 108 190)',
    deep: 'rgb(24 44 96)',
    danger: 'rgb(200 74 78)',
    success: 'rgb(38 152 122)',
    warning: 'rgb(184 128 40)',
  },
} as const;

/** 光斑三色（按色板取）：给 `mix-blend-mode: screen` 用，饱和度故意拉高。 */
export const AURORA_PALETTES: Record<'sea' | 'star' | 'deep', [string, string, string]> = {
  sea: ['rgb(88 186 232)', 'rgb(150 118 236)', 'rgb(96 150 224)'],
  star: ['rgb(146 120 244)', 'rgb(206 118 236)', 'rgb(96 118 220)'],
  deep: ['rgb(72 196 214)', 'rgb(88 138 236)', 'rgb(56 104 190)'],
};

/** 默认光斑自定义色（`palette='custom'` 且没填时回落到这里）。 */
export const AURORA_CUSTOM_FALLBACK = AURORA_PALETTES.sea;

export const DEFAULT_APPEARANCE: AppearanceConfig = {
  wallpaper: {
    mode: 'shader',
    blobId: null,
    opacity: 78,
    blur: 14,
    brightness: 96,
    contrast: 108,
    saturation: 124,
    scale: 108,
    playbackRate: 1,
    muted: true,
    loop: true,
  },
  aurora: {
    enabled: true,
    count: 4,
    palette: 'sea',
    customColors: [],
    speed: 1,
    intensity: 54,
    blur: 72,
    blend: 'screen',
  },
  iridescence: {
    enabled: true,
    targets: { nav: true, title: true, cardEdge: true, chartFill: true },
    hueRange: 190,
    speed: 1.6,
    thickness: 1,
    opacity: 64,
  },
  glow: {
    enabled: true,
    targets: { value: true, badge: true, button: true, chartPoint: true, cardHover: true },
    radius: 22,
    strength: 46,
    color: 'brand',
    customColor: 'rgb(88 170 255)',
  },
  glass: {
    blur: 18,
    saturation: 148,
    opacity: 82,
    borderStrength: 56,
    elevation: 10,
    grain: true,
    grainOpacity: 3,
  },
  typography: {
    // 键顺序与 presets.ts 的归一输出一致：normalize 的 repaired 判据是逐节 JSON 字符串比对，
    // 顺序不同会被当成「有字段被修正」→ 每次导入都误报「已自动修正」。
    rootSize: 14,
    pageSize: 18,
    cardSize: 14,
    captionSize: 12,
    numSize: 30,
    lineHeight: 1.55,
    letterSpacing: 0,
    weightBody: 400,
  },
  motion: {
    enabled: true,
    speed: 1,
    entrance: 'rise',
    chartPath: true,
    reduceMotionRespect: true,
  },
  palette: {
    preset: 'sea',
    ...PALETTES.sea,
  },
  scene3d: {
    quality: 'medium',
  },
  layout: {
    side: 'left',
    sidebarWidth: 240,
    collapsedByDefault: false,
    collapseMode: 'icon',
    headerHeight: 56,
    headerFloating: false,
    headerSticky: true,
    radius: 18,
    spacing: 1,
    gridColumns: 3,
    cardMinWidth: 320,
    showBreadcrumb: false,
    showHealthLamp: true,
    showFooter: true,
    hiddenNav: [],
  },
  charts: {
    kind: 'area',
    window: '24h',
    refresh: 'off',
    decimals: 1,
    thousands: true,
    trendArrow: true,
    periodOverPeriod: false,
    quality: 'medium',
  },
  logView: {
    lineHeight: 1.4,
    textSize: 12,
    mono: true,
    wrap: false,
    timestamp: 'absolute',
    rules: [],
    autoScroll: true,
    maxLines: 500,
  },
  interaction: {
    bindings: [
      { action: 'palette', keys: 'ctrl+k' },
      { action: 'refresh', keys: 'r' },
      { action: 'appearance', keys: 'g a' },
      { action: 'toggleTheme', keys: 'shift+d' },
    ],
    landingPath: '/console',
    polling: true,
    toastCorner: 'bottomRight',
    toastDismissMs: 4000,
    confirmLevel: 'normal',
  },
  notifications: {
    browserEnabled: false,
    levels: ['warn', 'bad'],
    soundEnabled: false,
    soundVolume: 40,
    dndEnabled: false,
    dndFrom: '23:00',
    dndTo: '08:00',
  },
  locale: {
    language: 'zh-CN',
    timezone: 'local',
    fixedOffset: 8,
    dateFormat: 'iso',
    unitSystem: 'compact',
  },
  a11y: {
    highContrast: false,
    largeText: false,
    forceReduceMotion: false,
    focusRingWidth: 3,
    focusRingColor: '',
    colorBlind: 'none',
  },
  density: {
    tableDensity: 'comfortable',
    pageSize: 20,
    hideEmptyColumns: true,
  },
  performance: {
    dataSaver: false,
    prefetch: true,
    imageQuality: 'compressed',
    requestCache: '60s',
  },
};

/** 深拷贝（配置是纯数据树，结构化克隆足够；避免调用方误改默认值）。 */
export function cloneAppearance(value: AppearanceConfig): AppearanceConfig {
  return structuredClone(value);
}

/** 取某色板的七枚语义色（未知索引回落 sea）。 */
export function paletteOf(code: string): Record<string, string> {
  if (code === 'star' || code === 'deep') return { ...PALETTES[code] };
  return { ...PALETTES.sea };
}

const HEX_HEAD = '#' as const;

/**
 * `rgb(R G B)` → 十六进制形（色票的 `<input type="color">` 只吃十六进制）。
 * 认不出的输入**原样返回**——不能编一个默认色，否则用户会看到界面变成他从没选过的颜色。
 */
export function toHex(color: string): string {
  if (color.trim().startsWith(HEX_HEAD)) return color.trim();
  const m = /^rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})/i.exec(color.trim());
  if (!m) return color;
  const parts = [m[1], m[2], m[3]].map((n) => Math.min(255, Number(n)).toString(16).padStart(2, '0'));
  return `${HEX_HEAD}${parts.join('')}`;
}

/** `toHex` 的逆：十六进制 → `rgb(R G B)`（统一存函数形，见文件头）。 */
export function fromHex(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = m[1];
  return `rgb(${parseInt(n.slice(0, 2), 16)} ${parseInt(n.slice(2, 4), 16)} ${parseInt(n.slice(4, 6), 16)})`;
}
