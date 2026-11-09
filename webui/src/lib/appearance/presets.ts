// 内置四套预设 + 导入校验（UI3 追加二「预设 + 导入导出」）。
//
// 预设是**数据**：每套就是一份完整 `AppearanceConfig`，切换即整份替换。
// 导入只认白名单字段 + 逐项钳制——坏 JSON、缺字段、超界值、乱塞的属性一律不炸，
// 未知字段直接丢弃（不透传 = 不给未来版本埋雷）。
//
// 第 9–17 组（WAVE-ALL 第一部分）走同一套 normalize：新组只加白名单行与钳制，
// 不另写第二个入口——「导入能绕过滑块」是这类配置最经典的事故。

import { cloneAppearance, DEFAULT_APPEARANCE, paletteOf, PALETTES } from './defaults.ts';
import { clampRange, RANGES } from './schema.ts';
import { setPath } from './path.ts';
import type {
  AlertLevel,
  AppearanceConfig,
  AuroraBlend,
  BodyWeight,
  CacheTtl,
  ChartKind,
  ChartWindow,
  CollapseMode,
  ColorBlindMode,
  ConfirmLevel,
  DateFormat,
  EntranceMode,
  HighlightRule,
  ImageQuality,
  KeyBinding,
  LogFontSize,
  PaletteCode,
  QualityTier,
  RefreshRate,
  SidebarSide,
  TableDensity,
  TimezoneMode,
  ToastCorner,
  ToneName,
  UiLanguage,
  UnitSystem,
  WallpaperMode,
} from './types.ts';

export interface AppearancePreset {
  id: string;
  /** 中文名（外观页预设卡片的标题）。 */
  name: string;
  /** 一句中文说明：这套预设适合谁。 */
  hint: string;
  config: AppearanceConfig;
}

function withPalette(base: AppearanceConfig, code: PaletteCode): AppearanceConfig {
  const next = cloneAppearance(base);
  // custom 时保留用户已挑的七枚色，只改 preset 标记；其余色板整份替换。
  const colors = code === 'custom' ? next.palette : paletteOf(code);
  next.palette = {
    preset: code,
    brand: colors.brand,
    purple: colors.purple,
    deep: colors.deep,
    danger: colors.danger,
    success: colors.success,
    warning: colors.warning,
  };
  next.aurora.palette = code === 'custom' ? 'sea' : code;
  return next;
}

/** 深海（当前默认形态）：四光斑 + 满虹彩 + 中等辉光。 */
const DEEP_SEA = withPalette(DEFAULT_APPEARANCE, 'sea');

/** 极简：关光斑、关虹彩、弱辉光、平玻璃——只留层次与可读性。 */
const MINIMAL = (() => {
  const next = withPalette(DEFAULT_APPEARANCE, 'sea');
  next.wallpaper = { ...next.wallpaper, mode: 'none', opacity: 0 };
  next.aurora = { ...next.aurora, enabled: false, count: 2, intensity: 22, speed: 0.6 };
  next.iridescence = { ...next.iridescence, enabled: false };
  next.glow = { ...next.glow, radius: 8, strength: 14 };
  next.glass = { ...next.glass, blur: 8, saturation: 120, opacity: 92, elevation: 4, grain: false };
  next.motion = { ...next.motion, entrance: 'fade' as EntranceMode };
  return next;
})();

/** 炫彩：全部拉满（6 光斑 / 满虹彩 / 强辉光 / 大颗粒）。 */
const VIVID = (() => {
  const next = withPalette(DEFAULT_APPEARANCE, 'star');
  next.wallpaper = { ...next.wallpaper, mode: 'shader', opacity: 92, blur: 8, saturation: 170, scale: 118 };
  next.aurora = { ...next.aurora, enabled: true, count: 6, intensity: 82, blur: 96, speed: 1.8, blend: 'plus-lighter' as AuroraBlend };
  next.iridescence = { ...next.iridescence, enabled: true, hueRange: 300, speed: 2.6, thickness: 3, opacity: 92 };
  next.glow = { ...next.glow, radius: 38, strength: 92 };
  next.glass = { ...next.glass, blur: 24, saturation: 180, opacity: 62, borderStrength: 92, elevation: 20, grain: true, grainOpacity: 6 };
  next.motion = { ...next.motion, speed: 1.4, entrance: 'scale' as EntranceMode };
  next.charts = { ...next.charts, quality: 'high' as QualityTier };
  return next;
})();

/** 性能：给手机/弱机——关壁纸关光斑、薄玻璃、短动效、低质量 3D。 */
const PERFORMANCE = (() => {
  const next = withPalette(DEFAULT_APPEARANCE, 'sea');
  next.wallpaper = { ...next.wallpaper, mode: 'none', opacity: 0, blur: 0 };
  next.aurora = { ...next.aurora, enabled: false, count: 1, intensity: 18 };
  next.iridescence = { ...next.iridescence, enabled: true, speed: 0.5, opacity: 30, thickness: 1 };
  next.glow = { ...next.glow, radius: 6, strength: 10 };
  next.glass = { ...next.glass, blur: 4, saturation: 110, opacity: 96, borderStrength: 30, elevation: 2, grain: false };
  next.motion = { ...next.motion, enabled: false, speed: 1, entrance: 'none' as EntranceMode, chartPath: false };
  next.scene3d = { quality: 'low' as QualityTier };
  // 性能预设同时把「跑在服务器上的」那部分压下来：不自动刷新、不预加载、不加载图。
  next.charts = { ...next.charts, quality: 'low' as QualityTier, refresh: 'off' as RefreshRate };
  next.performance = { ...next.performance, prefetch: false, imageQuality: 'off' as ImageQuality, dataSaver: true };
  next.density = { ...next.density, tableDensity: 'compact' as TableDensity, pageSize: 10 };
  return next;
})();

export const PRESETS: AppearancePreset[] = [
  { id: 'deep-sea', name: '深海', hint: '默认形态：四颗釉瑚光斑缓慢漂移，玻璃层清晰透亮', config: DEEP_SEA },
  { id: 'minimal', name: '极简', hint: '关光斑关虹彩：只留层次与可读性，长时间看不累', config: MINIMAL },
  { id: 'vivid', name: '炫彩', hint: '光斑、虹彩、辉光全部拉满，适合大屏与展示', config: VIVID },
  { id: 'performance', name: '性能', hint: '手机与弱机专用：关壁纸关光斑，动画最短，3D 降为低档，不预加载不刷新', config: PERFORMANCE },
];

/** 白名单枚举值（导入校验用；不在表里的回落默认）。 */
const ONE_OF = {
  wallpaperMode: ['none', 'shader', 'image', 'video'] as WallpaperMode[],
  palette: ['sea', 'star', 'deep', 'custom'] as PaletteCode[],
  blend: ['screen', 'plus-lighter', 'overlay', 'normal'] as AuroraBlend[],
  entrance: ['none', 'rise', 'fade', 'scale', 'blur'] as EntranceMode[],
  weight: [400, 500, 600] as BodyWeight[],
  quality: ['low', 'medium', 'high'] as QualityTier[],
  glowColor: ['semantic', 'brand', 'custom'] as const,
  // —— 第 9–17 组 ——
  side: ['left', 'right'] as SidebarSide[],
  collapseMode: ['icon', 'hidden'] as CollapseMode[],
  chartKind: ['line', 'area', 'bar', 'scatter', 'donut'] as ChartKind[],
  chartWindow: ['24h', '7d', '30d'] as ChartWindow[],
  refresh: ['off', '5s', '15s', '60s'] as RefreshRate[],
  unitSystem: ['compact', 'plain', 'chinese'] as UnitSystem[],
  logFontSize: [12, 14, 16] as LogFontSize[],
  timestamp: ['absolute', 'relative', 'timeOnly'] as const,
  highlightScope: ['text', 'row'] as const,
  tone: ['', 'good', 'warn', 'bad', 'info', 'purple', 'magenta'] as ToneName[],
  confirm: ['normal', 'strict', 'extreme'] as ConfirmLevel[],
  corner: ['topLeft', 'topRight', 'bottomLeft', 'bottomRight'] as ToastCorner[],
  alertLevel: ['info', 'warn', 'bad'] as AlertLevel[],
  language: ['zh-CN', 'en'] as UiLanguage[],
  timezone: ['local', 'utc', 'fixed'] as TimezoneMode[],
  dateFormat: ['iso', 'slash', 'short', 'cn'] as DateFormat[],
  colorBlind: ['none', 'deuteranopia', 'protanopia', 'tritanopia'] as ColorBlindMode[],
  tableDensity: ['compact', 'comfortable'] as TableDensity[],
  imageQuality: ['original', 'compressed', 'off'] as ImageQuality[],
  cacheTtl: ['off', '30s', '60s', '300s'] as CacheTtl[],
};

function pick<T>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

function num(value: unknown, range: { min: number; max: number; step: number }, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? clampRange(value, range) : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function color(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^(rgb|#)/.test(value.trim()) ? value.trim() : fallback;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** 数组型字段：只留白名单成员并去重（顺序保持用户给的顺序）。 */
function pickList<T>(value: unknown, allowed: readonly T[]): T[] {
  if (!Array.isArray(value)) return [];
  const out: T[] = [];
  for (const item of value) {
    if (allowed.includes(item as T) && !out.includes(item as T)) out.push(item as T);
  }
  return out;
}

/** `HH:MM` 只收合法时刻；坏值回落默认（不猜、「23:70」不许透过）。 */
function clock(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value.trim());
  return m ? `${m[1]}:${m[2]}` : fallback;
}

/** 高亮规则：逐条白名单化，最多 20 条（再多就该用日志平台了）。 */
function rules(value: unknown): HighlightRule[] {
  if (!Array.isArray(value)) return [];
  return value
    .slice(0, 20)
    .map((raw, index): HighlightRule | null => {
      const r = record(raw);
      const pattern = typeof r.pattern === 'string' ? r.pattern.slice(0, 200) : '';
      if (!pattern) return null;
      return {
        id: typeof r.id === 'string' && r.id ? r.id.slice(0, 40) : `rule-${index}`,
        pattern,
        regex: bool(r.regex, false),
        fg: pick(r.fg, ONE_OF.tone, ''),
        bg: pick(r.bg, ONE_OF.tone, ''),
        scope: pick(r.scope, ONE_OF.highlightScope, 'text'),
        enabled: bool(r.enabled, true),
      };
    })
    .filter((rule): rule is HighlightRule => rule !== null);
}

/** 快捷键：动作名只收短标识，键串只收小写组合（不执行任何命令，只被页面读）。 */
function bindings(value: unknown): KeyBinding[] {
  if (!Array.isArray(value)) return DEFAULT_APPEARANCE.interaction.bindings;
  const out: KeyBinding[] = [];
  for (const raw of value.slice(0, 40)) {
    const b = record(raw);
    const action = typeof b.action === 'string' ? b.action.replace(/[^a-z0-9-]/gi, '').slice(0, 32) : '';
    const keys = typeof b.keys === 'string' ? b.keys.toLowerCase().replace(/[^a-z0-9+ /-]/g, '').slice(0, 40) : '';
    if (action) out.push({ action, keys });
  }
  return out.length > 0 ? out : DEFAULT_APPEARANCE.interaction.bindings;
}

/**
 * 导入校验：任何输入都返回一份**合法完整**配置。
 * 返回 `{ config, repaired }`：`repaired=true` 表示有字段被修正/丢弃（页面据此提示「已自动修正」）。
 */
export function normalizeAppearance(input: unknown): { config: AppearanceConfig; repaired: boolean } {
  const base = DEFAULT_APPEARANCE;
  const raw = record(input);
  const touched: string[] = [];
  const note = (key: string, before: unknown, after: unknown) => {
    if (JSON.stringify(before) !== JSON.stringify(after)) touched.push(key);
  };

  const wp = record(raw.wallpaper);
  const wallpaper = {
    mode: pick(wp.mode, ONE_OF.wallpaperMode, base.wallpaper.mode),
    blobId: typeof wp.blobId === 'string' && wp.blobId.length > 0 ? wp.blobId : null,
    opacity: num(wp.opacity, RANGES.wallpaper.opacity, base.wallpaper.opacity),
    blur: num(wp.blur, RANGES.wallpaper.blur, base.wallpaper.blur),
    brightness: num(wp.brightness, RANGES.wallpaper.brightness, base.wallpaper.brightness),
    contrast: num(wp.contrast, RANGES.wallpaper.contrast, base.wallpaper.contrast),
    saturation: num(wp.saturation, RANGES.wallpaper.saturation, base.wallpaper.saturation),
    scale: num(wp.scale, RANGES.wallpaper.scale, base.wallpaper.scale),
    playbackRate: num(wp.playbackRate, RANGES.wallpaper.playbackRate, base.wallpaper.playbackRate),
    muted: bool(wp.muted, base.wallpaper.muted),
    loop: bool(wp.loop, base.wallpaper.loop),
  };
  note('wallpaper', wp, wallpaper);

  const au = record(raw.aurora);
  const aurora = {
    enabled: bool(au.enabled, base.aurora.enabled),
    count: num(au.count, RANGES.aurora.count, base.aurora.count),
    palette: pick(au.palette, ONE_OF.palette, base.aurora.palette),
    customColors: Array.isArray(au.customColors)
      ? au.customColors.filter((c): c is string => typeof c === 'string' && /^(rgb|#)/.test(c)).slice(0, 6).map((c) => color(c, PALETTES.sea.brand))
      : [],
    speed: num(au.speed, RANGES.aurora.speed, base.aurora.speed),
    intensity: num(au.intensity, RANGES.aurora.intensity, base.aurora.intensity),
    blur: num(au.blur, RANGES.aurora.blur, base.aurora.blur),
    blend: pick(au.blend, ONE_OF.blend, base.aurora.blend),
  };
  note('aurora', au, aurora);

  const ir = record(raw.iridescence);
  const irTargets = record(ir.targets);
  const iridescence = {
    enabled: bool(ir.enabled, base.iridescence.enabled),
    targets: {
      nav: bool(irTargets.nav, base.iridescence.targets.nav),
      title: bool(irTargets.title, base.iridescence.targets.title),
      cardEdge: bool(irTargets.cardEdge, base.iridescence.targets.cardEdge),
      chartFill: bool(irTargets.chartFill, base.iridescence.targets.chartFill),
    },
    hueRange: num(ir.hueRange, RANGES.iridescence.hueRange, base.iridescence.hueRange),
    speed: num(ir.speed, RANGES.iridescence.speed, base.iridescence.speed),
    thickness: num(ir.thickness, RANGES.iridescence.thickness, base.iridescence.thickness),
    opacity: num(ir.opacity, RANGES.iridescence.opacity, base.iridescence.opacity),
  };
  note('iridescence', ir, iridescence);

  const gl = record(raw.glow);
  const glTargets = record(gl.targets);
  const glow = {
    enabled: bool(gl.enabled, base.glow.enabled),
    targets: {
      value: bool(glTargets.value, base.glow.targets.value),
      badge: bool(glTargets.badge, base.glow.targets.badge),
      button: bool(glTargets.button, base.glow.targets.button),
      chartPoint: bool(glTargets.chartPoint, base.glow.targets.chartPoint),
      cardHover: bool(glTargets.cardHover, base.glow.targets.cardHover),
    },
    radius: num(gl.radius, RANGES.glow.radius, base.glow.radius),
    strength: num(gl.strength, RANGES.glow.strength, base.glow.strength),
    color: pick(gl.color, ONE_OF.glowColor, base.glow.color),
    customColor: color(gl.customColor, base.glow.customColor),
  };
  note('glow', gl, glow);

  const gs = record(raw.glass);
  const glass = {
    blur: num(gs.blur, RANGES.glass.blur, base.glass.blur),
    saturation: num(gs.saturation, RANGES.glass.saturation, base.glass.saturation),
    opacity: num(gs.opacity, RANGES.glass.opacity, base.glass.opacity),
    borderStrength: num(gs.borderStrength, RANGES.glass.borderStrength, base.glass.borderStrength),
    elevation: num(gs.elevation, RANGES.glass.elevation, base.glass.elevation),
    grain: bool(gs.grain, base.glass.grain),
    grainOpacity: num(gs.grainOpacity, RANGES.glass.grainOpacity, base.glass.grainOpacity),
  };
  note('glass', gs, glass);

  const ty = record(raw.typography);
  const typography = {
    rootSize: num(ty.rootSize, RANGES.typography.rootSize, base.typography.rootSize),
    pageSize: num(ty.pageSize, RANGES.typography.pageSize, base.typography.pageSize),
    cardSize: num(ty.cardSize, RANGES.typography.cardSize, base.typography.cardSize),
    captionSize: num(ty.captionSize, RANGES.typography.captionSize, base.typography.captionSize),
    numSize: num(ty.numSize, RANGES.typography.numSize, base.typography.numSize),
    lineHeight: num(ty.lineHeight, RANGES.typography.lineHeight, base.typography.lineHeight),
    letterSpacing: num(ty.letterSpacing, RANGES.typography.letterSpacing, base.typography.letterSpacing),
    weightBody: pick(ty.weightBody, ONE_OF.weight, base.typography.weightBody),
  };
  note('typography', ty, typography);

  const mo = record(raw.motion);
  const motion = {
    enabled: bool(mo.enabled, base.motion.enabled),
    speed: num(mo.speed, RANGES.motion.speed, base.motion.speed),
    entrance: pick(mo.entrance, ONE_OF.entrance, base.motion.entrance),
    chartPath: bool(mo.chartPath, base.motion.chartPath),
    reduceMotionRespect: bool(mo.reduceMotionRespect, base.motion.reduceMotionRespect),
  };
  note('motion', mo, motion);

  const pa = record(raw.palette);
  const preset = pick(pa.preset, ONE_OF.palette, base.palette.preset);
  const paletteBase = preset === 'custom' ? base.palette : paletteOf(preset);
  const palette = {
    preset,
    brand: color(pa.brand, paletteBase.brand),
    purple: color(pa.purple, paletteBase.purple),
    deep: color(pa.deep, paletteBase.deep),
    danger: color(pa.danger, paletteBase.danger ?? PALETTES.sea.danger),
    success: color(pa.success, paletteBase.success ?? PALETTES.sea.success),
    warning: color(pa.warning, paletteBase.warning ?? PALETTES.sea.warning),
  };
  note('palette', pa, palette);

  const sc = record(raw.scene3d);
  const scene3d = { quality: pick(sc.quality, ONE_OF.quality, base.scene3d.quality) };
  note('scene3d', sc, scene3d);

  // —— 第 9–17 组 ——
  // 旧枚举值 → px（导入旧导出文件时用；新配置不写这两个键）
  const RADIUS_TIER_PX: Record<string, number> = { '30': 24, '18': 18, '14': 14 };
  const DENSITY_PX: Record<string, number> = { compact: 0.7, standard: 1, roomy: 1.35 };
  const ly = record(raw.layout);
  const layout = {
    side: pick(ly.side, ONE_OF.side, base.layout.side),
    sidebarWidth: num(ly.sidebarWidth, RANGES.layout.sidebarWidth, base.layout.sidebarWidth),
    collapsedByDefault: bool(ly.collapsedByDefault, base.layout.collapsedByDefault),
    collapseMode: pick(ly.collapseMode, ONE_OF.collapseMode, base.layout.collapseMode),
    headerHeight: num(ly.headerHeight, RANGES.layout.headerHeight, base.layout.headerHeight),
    headerFloating: bool(ly.headerFloating, base.layout.headerFloating),
    headerSticky: bool(ly.headerSticky, base.layout.headerSticky),
    // 用户 2026-10-19：「ui圆角、间距等全部改成自定义大小px」⇒ 从「三档枚举」改成「px 数值」。
    // 旧配置里的 '30' / '18' / '14' 与 'compact' / 'standard' / 'roomy' 是字符串，
    // `num()` 只认 number，会回落默认值而不是崩掉——下面 legacy 分支把它们翻译成对应 px，
    // 老导出文件因此不会「一导入圆角就没了」。
    radius: num(
      typeof ly.radiusTier === 'string' ? RADIUS_TIER_PX[ly.radiusTier] : ly.radius,
      RANGES.layout.radius,
      base.layout.radius
    ),
    spacing: num(
      typeof ly.density === 'string' ? DENSITY_PX[ly.density] : ly.spacing,
      RANGES.layout.spacing,
      base.layout.spacing
    ),
    gridColumns: num(ly.gridColumns, RANGES.layout.gridColumns, base.layout.gridColumns),
    cardMinWidth: num(ly.cardMinWidth, RANGES.layout.cardMinWidth, base.layout.cardMinWidth),
    showBreadcrumb: bool(ly.showBreadcrumb, base.layout.showBreadcrumb),
    showHealthLamp: bool(ly.showHealthLamp, base.layout.showHealthLamp),
    showFooter: bool(ly.showFooter, base.layout.showFooter),
    // 导航路由是短标识（'/'、'/calls'…），非字符串一律丢弃。
    hiddenNav: Array.isArray(ly.hiddenNav)
      ? [...new Set(ly.hiddenNav.filter((v): v is string => typeof v === 'string').slice(0, 40))]
      : [],
  };
  note('layout', ly, layout);

  const ch = record(raw.charts);
  const charts = {
    kind: pick(ch.kind, ONE_OF.chartKind, base.charts.kind),
    window: pick(ch.window, ONE_OF.chartWindow, base.charts.window),
    refresh: pick(ch.refresh, ONE_OF.refresh, base.charts.refresh),
    // 数字单位制只有一份，住在 locale（见 types.ts 的 ChartsSection 注释）。
    decimals: num(ch.decimals, RANGES.charts.decimals, base.charts.decimals),
    thousands: bool(ch.thousands, base.charts.thousands),
    trendArrow: bool(ch.trendArrow, base.charts.trendArrow),
    periodOverPeriod: bool(ch.periodOverPeriod, base.charts.periodOverPeriod),
    quality: pick(ch.quality, ONE_OF.quality, base.charts.quality),
  };
  note('charts', ch, charts);

  const lv = record(raw.logView);
  const logView = {
    lineHeight: num(lv.lineHeight, RANGES.logView.lineHeight, base.logView.lineHeight),
    textSize: pick(lv.textSize, ONE_OF.logFontSize, base.logView.textSize),
    mono: bool(lv.mono, base.logView.mono),
    wrap: bool(lv.wrap, base.logView.wrap),
    timestamp: pick(lv.timestamp, ONE_OF.timestamp, base.logView.timestamp),
    rules: rules(lv.rules),
    autoScroll: bool(lv.autoScroll, base.logView.autoScroll),
    maxLines: num(lv.maxLines, RANGES.logView.maxLines, base.logView.maxLines),
  };
  note('logView', lv, logView);

  const ix = record(raw.interaction);
  const interaction = {
    bindings: bindings(ix.bindings),
    landingPath: typeof ix.landingPath === 'string' && ix.landingPath.startsWith('/') ? ix.landingPath.slice(0, 60) : base.interaction.landingPath,
    polling: bool(ix.polling, base.interaction.polling),
    toastCorner: pick(ix.toastCorner, ONE_OF.corner, base.interaction.toastCorner),
    toastDismissMs: num(ix.toastDismissMs, RANGES.interaction.toastDismissMs, base.interaction.toastDismissMs),
    confirmLevel: pick(ix.confirmLevel, ONE_OF.confirm, base.interaction.confirmLevel),
  };
  note('interaction', ix, interaction);

  const nt = record(raw.notifications);
  const notifications = {
    browserEnabled: bool(nt.browserEnabled, base.notifications.browserEnabled),
    levels: pickList(nt.levels, ONE_OF.alertLevel),
    soundEnabled: bool(nt.soundEnabled, base.notifications.soundEnabled),
    soundVolume: num(nt.soundVolume, RANGES.notifications.soundVolume, base.notifications.soundVolume),
    dndEnabled: bool(nt.dndEnabled, base.notifications.dndEnabled),
    dndFrom: clock(nt.dndFrom, base.notifications.dndFrom),
    dndTo: clock(nt.dndTo, base.notifications.dndTo),
  };
  note('notifications', nt, notifications);

  const lo = record(raw.locale);
  const locale = {
    language: pick(lo.language, ONE_OF.language, base.locale.language),
    timezone: pick(lo.timezone, ONE_OF.timezone, base.locale.timezone),
    fixedOffset: num(lo.fixedOffset, RANGES.locale.fixedOffset, base.locale.fixedOffset),
    dateFormat: pick(lo.dateFormat, ONE_OF.dateFormat, base.locale.dateFormat),
    unitSystem: pick(lo.unitSystem, ONE_OF.unitSystem, base.locale.unitSystem),
  };
  note('locale', lo, locale);

  const ax = record(raw.a11y);
  const a11y = {
    highContrast: bool(ax.highContrast, base.a11y.highContrast),
    largeText: bool(ax.largeText, base.a11y.largeText),
    forceReduceMotion: bool(ax.forceReduceMotion, base.a11y.forceReduceMotion),
    focusRingWidth: num(ax.focusRingWidth, RANGES.a11y.focusRingWidth, base.a11y.focusRingWidth),
    focusRingColor: pick(ax.focusRingColor, ONE_OF.tone, base.a11y.focusRingColor),
    colorBlind: pick(ax.colorBlind, ONE_OF.colorBlind, base.a11y.colorBlind),
  };
  note('a11y', ax, a11y);

  const de = record(raw.density);
  const density = {
    tableDensity: pick(de.tableDensity, ONE_OF.tableDensity, base.density.tableDensity),
    pageSize: num(de.pageSize, RANGES.density.pageSize, base.density.pageSize),
    hideEmptyColumns: bool(de.hideEmptyColumns, base.density.hideEmptyColumns),
  };
  note('density', de, density);

  const pf = record(raw.performance);
  const performance = {
    dataSaver: bool(pf.dataSaver, base.performance.dataSaver),
    prefetch: bool(pf.prefetch, base.performance.prefetch),
    imageQuality: pick(pf.imageQuality, ONE_OF.imageQuality, base.performance.imageQuality),
    requestCache: pick(pf.requestCache, ONE_OF.cacheTtl, base.performance.requestCache),
  };
  note('performance', pf, performance);

  return {
    config: {
      wallpaper,
      aurora,
      iridescence,
      glow,
      glass,
      typography,
      motion,
      palette,
      scene3d,
      layout,
      charts,
      logView,
      interaction,
      notifications,
      locale,
      a11y,
      density,
      performance,
    },
    repaired: touched.length > 0,
  };
}

/** 导出：只写配置本体（不含 blobId 指向的文件——文件在 IndexedDB，不可序列化为 JSON）。 */
export function serializeAppearance(cfg: AppearanceConfig): string {
  return JSON.stringify({ kind: 'webui:appearance', version: 1, config: cfg }, null, 2);
}

/** 从导出文件文本还原（兼容「直接贴配置本体」与「带 kind/version 外壳」两种形态）。 */
export function deserializeAppearance(text: string): { config: AppearanceConfig; repaired: boolean } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { config: cloneAppearance(DEFAULT_APPEARANCE), repaired: true };
  }
  const shell = record(parsed);
  const body = 'config' in shell ? shell.config : parsed;
  return normalizeAppearance(body);
}

/** 供页面「单个字段改成某值」用：走 setPath，嵌套键（targets.nav）与数组键同一实现。 */
export function withField(cfg: AppearanceConfig, path: string, value: unknown): AppearanceConfig {
  const [section, ...rest] = path.split('.');
  const body = setPath(cfg[section as keyof AppearanceConfig] as unknown as Record<string, unknown>, rest.join('.'), value);
  return { ...cfg, [section]: body } as AppearanceConfig;
}
