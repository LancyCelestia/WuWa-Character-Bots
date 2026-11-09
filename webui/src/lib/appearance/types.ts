// 外观配置总线的**类型真身**（UI3 追加二：用户裁定「所有 ui 特效全部赶进设置里」）。
//
// 一条总线、七个分组，全部落 IndexedDB 键 `webui:appearance:v1`；渲染层只读它导出的
// CSS 自定义属性（见 `./apply`），组件源码里不再出现任何写死的特效数值。
//
// 颜色的取值形态：三组语义色板（sea/star/deep）是**索引**，色值真身在 `./defaults` 的
// PALETTES 里；`custom` 时读同分组下的自定义色。色板索引让「换主题」是一次赋值而不是
// 七个字段各自漂移，也让导入校验只需要认枚举。

/** 壁纸来源：纯色底 / 程序化 shader（0 字节）/ 本地图片 / 本地视频。 */
export type WallpaperMode = 'none' | 'shader' | 'image' | 'video';

/** 色板枚举（光斑与品牌色共用一套命名）。 */
export type PaletteCode = 'sea' | 'star' | 'deep' | 'custom';

/** 光斑与壁纸压暗罩的混合模式。 */
export type AuroraBlend = 'screen' | 'plus-lighter' | 'overlay' | 'normal';

/** 入场动效形态。 */
export type EntranceMode = 'none' | 'rise' | 'fade' | 'scale' | 'blur';

/** 正文基础字重（宪法门：≤700）。 */
export type BodyWeight = 400 | 500 | 600;

/** three.js 质量档（影响像素比 / 粒子数 / 后期）。 */
export type QualityTier = 'low' | 'medium' | 'high';

export interface WallpaperSection {
  mode: WallpaperMode;
  /** 用户本地文件的 IndexedDB 记录键；`null` = 没选过。文件永不上传。 */
  blobId: string | null;
  /** 0–100：壁纸层整体不透明度。 */
  opacity: number;
  /** 0–40 px：壁纸模糊。 */
  blur: number;
  /** 0–200 %：亮度。 */
  brightness: number;
  /** 0–200 %：对比度。 */
  contrast: number;
  /** 0–200 %：饱和度。 */
  saturation: number;
  /** 100–150 %：cover 微缩放。 */
  scale: number;
  /** 0.25–2.0：仅 video。 */
  playbackRate: number;
  muted: boolean;
  loop: boolean;
}

export interface AuroraSection {
  enabled: boolean;
  /** 1–6：光斑个数（mix-blend-mode 会强制合成层，3–4 个是甜点）。 */
  count: number;
  palette: PaletteCode;
  /** 自定义光斑色（色票选择器给的十六进制串，3 个一轮循环）；`null` = 用预设色板。 */
  customColors: string[];
  /** 0.1–3.0：漂移速度倍率。 */
  speed: number;
  /** 0–100：光斑浓淡。 */
  intensity: number;
  /** 20–120 px：光斑柔化半径。 */
  blur: number;
  blend: AuroraBlend;
}

export interface IridescenceSection {
  enabled: boolean;
  /** 虹彩落点：选中导航 / 页头标题 / 卡片描边 / 图表填充。 */
  targets: { nav: boolean; title: boolean; cardEdge: boolean; chartFill: boolean };
  /** 0–360：色相跨度。 */
  hueRange: number;
  /** 0.4–4：游走一圈的秒数倍率（越大越慢）。 */
  speed: number;
  /** 1–4 px：描边厚度。 */
  thickness: number;
  /** 0–100：虹彩强度。 */
  opacity: number;
}

export interface GlowSection {
  enabled: boolean;
  /** 辉光落点：关键数值 / 徽章 / 按钮 / 图表数据点 / 卡片悬停。 */
  targets: { value: boolean; badge: boolean; button: boolean; chartPoint: boolean; cardHover: boolean };
  /** 0–40 px：辉光扩散半径。 */
  radius: number;
  /** 0–100 %：辉光强度。 */
  strength: number;
  /** 取色：跟随语义色 / 品牌色 / 自定义。 */
  color: 'semantic' | 'brand' | 'custom';
  customColor: string;
}

export interface GlassSection {
  /** 0–40 px：云母模糊。 */
  blur: number;
  /** 100–200 %：背景饱和度提升。 */
  saturation: number;
  /** 40–100 %：面板底色不透明度。 */
  opacity: number;
  /** 0–100 %：描边强度。 */
  borderStrength: number;
  /** 0–24 px：外发光抬升。 */
  elevation: number;
  /** 颗粒层开关。 */
  grain: boolean;
  /** 0–10 %：颗粒浓度。 */
  grainOpacity: number;
}

export interface TypographySection {
  /** 页面标题字号 px（fs-page）。 */
  pageSize: number;
  /** 卡片标题字号 px（fs-card）。 */
  cardSize: number;
  /** 正文字号 px（fs-body）：改它影响面最大。 */
  rootSize: number;
  /** 说明字号 px（fs-caption）。 */
  captionSize: number;
  /** 数字大字号 px（fs-num）。 */
  numSize: number;
  /** 1.1–2.2：行高倍数。 */
  lineHeight: number;
  /** -2 – +4 %：字间距。 */
  letterSpacing: number;
  weightBody: BodyWeight;
}

export interface MotionSection {
  enabled: boolean;
  /** 0.5–2.0：全局动画倍速（>1 更快）。 */
  speed: number;
  entrance: EntranceMode;
  /** 图表路径描边动画。 */
  chartPath: boolean;
  /** 尊重系统 `prefers-reduced-motion`（默认开）。 */
  reduceMotionRespect: boolean;
}

export interface PaletteSection {
  preset: PaletteCode;
  /** 七个语义色；色板切换时整体改写，也可单独改。 */
  brand: string;
  purple: string;
  deep: string;
  danger: string;
  success: string;
  warning: string;
}

export interface Scene3DSection {
  /** low / medium / high：像素比、粒子数、是否开后期。 */
  quality: QualityTier;
}

// ============================================================================
// 第 9–17 组（WAVE-ALL 第一部分）：布局 / 图表 / 日志 / 交互 / 通知 /
// 语言格式 / 无障碍 / 数据密度 / 性能省流量。
//
// 这一批**全在前端生效**，一条都不碰后端：它们改的是「同一个数字怎么显示成文字」
// 「哪一页是落地页」「表格一页几条」这类呈现口径，不新增任何后端契约。
// ============================================================================

/** 侧栏停靠边。 */
export type SidebarSide = 'left' | 'right';
/** 折叠后的呈现：只留图标 / 整条隐藏。 */
export type CollapseMode = 'icon' | 'hidden';
/** 面板圆角（px 自由值，0–40）。曾是三档枚举 '30'|'18'|'14'，用户 2026-10-19 裁定改为自定义 px。 */
export type RadiusTier = '30' | '18' | '14';
/** 面板间距（px 自由值，4–32，4px 栅格）。曾是 compact/standard/roomy 三档。 */
export type Density = 'compact' | 'standard' | 'roomy';

export interface LayoutSection {
  side: SidebarSide;
  /** 200–400 px。 */
  sidebarWidth: number;
  /** 首屏是否默认收起侧栏（只影响初始态，不改路由）。 */
  collapsedByDefault: boolean;
  collapseMode: CollapseMode;
  /** 44–96 px。 */
  headerHeight: number;
  /** 顶栏悬浮在内容之上（毛玻璃）。 */
  headerFloating: boolean;
  /** 顶栏吸顶跟随滚动。 */
  headerSticky: boolean;
  radiusTier?: RadiusTier;
  density?: Density;
  /** 面板圆角 px（0–40）。写进 --r-panel / --r-tile / --r-shell，全站 rounded-* 跟着变。 */
  radius: number;
  /** 面板间距倍率（0.5–2）。apply.ts 用它缩放 --shell-gap / --shell-inset / --cfg-gap。 */
  spacing: number;
  /** 1–6：总览栅格列数。 */
  gridColumns: number;
  /** 200–480 px：卡片最小宽度（窄于此自动换行）。 */
  cardMinWidth: number;
  showBreadcrumb: boolean;
  showHealthLamp: boolean;
  showFooter: boolean;
  /** 侧栏里不显示的导航项（路由仍可达）。 */
  hiddenNav: string[];
}

/** 图表类型（手写 SVG 的几种，不引图表库）。 */
export type ChartKind = 'line' | 'area' | 'bar' | 'scatter' | 'donut';
/** 图表默认时间窗。 */
export type ChartWindow = '24h' | '7d' | '30d';
/** 自动刷新档（off=不自动刷新，省流量）。 */
export type RefreshRate = 'off' | '5s' | '15s' | '60s';
/** 数字单位制：英文 K/M · 纯数字 · 中文万/亿。 */
export type UnitSystem = 'compact' | 'plain' | 'chinese';

export interface ChartsSection {
  kind: ChartKind;
  window: ChartWindow;
  refresh: RefreshRate;
  // 数字单位制**不在这里**：它只属于 `locale.unitSystem`（`context.tsx` 把那份交给 format 接缝）。
  // 曾在这里也留了一份 `charts.unitSystem`，全仓零消费方，于是那个控件「调了没反应」——已删。
  /** 0–3：小数位。 */
  decimals: number;
  thousands: boolean;
  trendArrow: boolean;
  periodOverPeriod: boolean;
  quality: QualityTier;
}

/** 时间戳显示口径。 */
export type TimestampFormat = 'absolute' | 'relative' | 'timeOnly';
/** 日志字号（宪法门三档内）。 */
export type LogFontSize = 12 | 14 | 16;
/** 高亮规则命中后作用范围。 */
export type HighlightScope = 'text' | 'row';
/** tone 名（高亮规则与焦点环共用；空串 = 不指定）。 */
export type ToneName = '' | 'good' | 'warn' | 'bad' | 'info' | 'purple' | 'magenta';

/** 一条高亮规则：关键字或正则 → 前景/背景（都取 tone token，不许手输色值）。 */
export interface HighlightRule {
  id: string;
  /** 关键字或正则原文（空串规则不生效，不编译空正则）。 */
  pattern: string;
  regex: boolean;
  fg: ToneName;
  bg: ToneName;
  scope: HighlightScope;
  enabled: boolean;
}

export interface LogViewSection {
  /** 1.2–2.0：行高倍数。 */
  lineHeight: number;
  textSize: LogFontSize;
  mono: boolean;
  wrap: boolean;
  timestamp: TimestampFormat;
  rules: HighlightRule[];
  autoScroll: boolean;
  /** 100–5000：最多保留行数。 */
  maxLines: number;
}

/** 危险操作二次确认的严格度。 */
export type ConfirmLevel = 'normal' | 'strict' | 'extreme';
/** toast 落点四角。 */
export type ToastCorner = 'topLeft' | 'topRight' | 'bottomLeft' | 'bottomRight';

/** 一个可绑定快捷键的动作（id 稳定，显示名在页面的动作清单里给中文）。 */
export interface KeyBinding {
  action: string;
  /** 形如 'g o' / 'shift+/' / 'ctrl+k'；空串 = 不绑定。 */
  keys: string;
}

export interface InteractionSection {
  bindings: KeyBinding[];
  /** 落地页路由（空串 = 缺省总览）。 */
  landingPath: string;
  /** 全局轮询总开关（关掉 = 页面不自动拉数，人工刷新）。 */
  polling: boolean;
  toastCorner: ToastCorner;
  /** 1500–8000 ms。 */
  toastDismissMs: number;
  confirmLevel: ConfirmLevel;
}

/** 告警级别（通知触发面）。 */
export type AlertLevel = 'info' | 'warn' | 'bad';

export interface NotificationsSection {
  browserEnabled: boolean;
  levels: AlertLevel[];
  /** Web Audio 合成的短音——0 字节，不引音频文件。 */
  soundEnabled: boolean;
  /** 0–100：合成音量。 */
  soundVolume: number;
  dndEnabled: boolean;
  /** 免打扰起止（本地时分 'HH:MM'；跨零点由判定函数处理）。 */
  dndFrom: string;
  dndTo: string;
}

/** 界面语言。 */
export type UiLanguage = 'zh-CN' | 'en';
/** 时区显示口径。 */
export type TimezoneMode = 'local' | 'utc' | 'fixed';
/** 日期格式。 */
export type DateFormat = 'iso' | 'slash' | 'short' | 'cn';

export interface LocaleSection {
  language: UiLanguage;
  timezone: TimezoneMode;
  /** -12 – 14：仅 `timezone='fixed'` 时生效。 */
  fixedOffset: number;
  dateFormat: DateFormat;
  unitSystem: UnitSystem;
}

/** 色盲友好映射。 */
export type ColorBlindMode = 'none' | 'deuteranopia' | 'protanopia' | 'tritanopia';

export interface A11ySection {
  highContrast: boolean;
  /** 大字号（独立于字体根字号，只放大正文档位）。 */
  largeText: boolean;
  /** 强制减少动效（不等系统设置，用户自己说了算）。 */
  forceReduceMotion: boolean;
  /** 1–6 px：焦点环宽度。 */
  focusRingWidth: number;
  /** 焦点环色 tone 名（空串 = 跟随 --ring）。 */
  focusRingColor: ToneName;
  colorBlind: ColorBlindMode;
}

/** 表格行密度。 */
export type TableDensity = 'compact' | 'comfortable';

export interface DensitySection {
  tableDensity: TableDensity;
  /** 10–200：每页条数。 */
  pageSize: number;
  hideEmptyColumns: boolean;
}

/** 图片加载策略。 */
export type ImageQuality = 'original' | 'compressed' | 'off';
/** API 响应缓存 TTL。 */
export type CacheTtl = 'off' | '30s' | '60s' | '300s';

export interface PerformanceSection {
  /** 手动省流（不等系统 saveData）。 */
  dataSaver: boolean;
  prefetch: boolean;
  imageQuality: ImageQuality;
  requestCache: CacheTtl;
}

/** 外观配置总线（17 组）。 */
export interface AppearanceConfig {
  wallpaper: WallpaperSection;
  aurora: AuroraSection;
  iridescence: IridescenceSection;
  glow: GlowSection;
  glass: GlassSection;
  typography: TypographySection;
  motion: MotionSection;
  palette: PaletteSection;
  scene3d: Scene3DSection;
  layout: LayoutSection;
  charts: ChartsSection;
  logView: LogViewSection;
  interaction: InteractionSection;
  notifications: NotificationsSection;
  locale: LocaleSection;
  a11y: A11ySection;
  density: DensitySection;
  performance: PerformanceSection;
}

/** 分组键（页面左栏导航据此生成）。 */
export type AppearanceSection = keyof AppearanceConfig;
