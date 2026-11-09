// 外观配置 → CSS 自定义属性的**唯一通道**（UI3 追加二）。
//
// 渲染层只读这里写出去的变量，组件里不许再有写死的特效数值：
//   ① 类型树一一对应（`AppearanceSection` 改了这里必须跟着改，appearance.test.ts 锁覆盖）；
//   ② 颜色走 `--ap-*` / tone 变量，样式里只消费变量；
//   ③ 只在 `<html>` 上写自定义属性——写的是变量不是样式表，不会与 .css 的定义带冲突。
//
// 第 9–17 组（布局/日志/密度/无障碍/省流量）同样走这条通道：它们改的是
// 「侧栏多宽」「表格行高多少」「焦点环多粗」这类**可由 CSS 变量表达**的量。
// 不能由变量表达的（图表类型、落地页、快捷键、时区格式）走本文件末尾的派生函数，
// 其默认值仍然只有 ./defaults 一份。
//
// 本文件允许出现 `opacity: 0.x` 形态的数值换算——它正是「配置 → 变量」的落点，
// 门 `grep "opacity: 0\.[0-9]" src/components` 的判据也因此只允许本文件。

import { AURORA_PALETTES } from './defaults.ts';
import type { AppearanceConfig, ToneName } from './types.ts';

/** tone 名 → 已登记 CSS 变量（色盲友好映射在 index.css 的 [data-cb=*] 段里改这组变量）。 */
const TONE_VAR: Record<Exclude<ToneName, ''>, string> = {
  good: 'var(--tone-good)',
  warn: 'var(--tone-warn)',
  bad: 'var(--tone-bad)',
  info: 'var(--tone-info)',
  purple: 'var(--tone-purple)',
  magenta: 'var(--tone-magenta)',
};

export function toneVar(name: ToneName, fallback: string): string {
  return name === '' ? fallback : TONE_VAR[name];
}

/**
 * 取光斑三色：`custom` 且填了色就用自定义色，不够 3 个时循环补齐；
 * 否则走该色板的预设三色。色板真身在 `./defaults`（数据，不是样式常量）。
 */
export function auroraColors(cfg: AppearanceConfig): [string, string, string] {
  const custom = cfg.aurora.customColors.filter((color) => /^rgb/.test(color) || /^#/.test(color));
  if (cfg.aurora.palette === 'custom' && custom.length > 0) {
    return [custom[0], custom[1 % custom.length], custom[2 % custom.length]];
  }
  const code = cfg.aurora.palette === 'star' || cfg.aurora.palette === 'deep' ? cfg.aurora.palette : 'sea';
  return [...AURORA_PALETTES[code]] as [string, string, string];
}

/**
 * 把配置写进根元素的 CSS 自定义属性。
 * 纯函数式（只依赖入参）→ 可在单测里用假 root 断言全部字段都落了变量。
 */
export function applyAppearance(cfg: AppearanceConfig, root: HTMLElement): void {
  const set = (name: string, value: string) => root.style.setProperty(name, value);

  // —— 壁纸 ——
  set('--wp-opacity', String(cfg.wallpaper.opacity / 100));
  set('--wp-blur', `${cfg.wallpaper.blur}px`);
  set('--wp-brightness', `${cfg.wallpaper.brightness / 100}`);
  set('--wp-contrast', `${cfg.wallpaper.contrast / 100}`);
  set('--wp-saturate', `${cfg.wallpaper.saturation / 100}`);
  set('--wp-scale', String(cfg.wallpaper.scale / 100));
  set('--wp-scrim', String(cfg.wallpaper.opacity / 100));
  set('--wp-playback', String(cfg.wallpaper.playbackRate));

  // —— 光斑 ——
  const [a, b, c] = auroraColors(cfg);
  set('--au-a', a);
  set('--au-b', b);
  set('--au-c', c);
  set('--au-speed', String(cfg.aurora.speed));
  set('--au-alpha', String(cfg.aurora.intensity / 100));
  set('--au-blur', `${cfg.aurora.blur}px`);
  set('--au-blend', cfg.aurora.blend === 'normal' ? 'normal' : cfg.aurora.blend);
  // 光斑个数没有纯 CSS 表达（节点数由组件决定），但层开关与相位要跟着走。
  set('--au-count', String(cfg.aurora.count));
  set('--au-display', cfg.aurora.enabled ? 'block' : 'none');

  // —— 虹彩 ——
  set('--ir-hue-range', `${cfg.iridescence.hueRange}deg`);
  set('--ir-dur', `${Math.max(0.4, 9 / Math.max(0.1, cfg.iridescence.speed))}s`);
  set('--ir-speed', String(cfg.iridescence.speed));
  set('--ir-width', `${cfg.iridescence.thickness}px`);
  set('--ir-alpha', String(cfg.iridescence.opacity / 100));

  // —— 辉光 ——
  set('--glow-r', `${cfg.glow.radius}px`);
  set('--glow-alpha', String(cfg.glow.strength / 100));
  set(
    '--glow-color',
    cfg.glow.color === 'custom' ? cfg.glow.customColor : cfg.glow.color === 'semantic' ? 'var(--tone-good)' : 'var(--primary)'
  );

  // —— 玻璃 ——
  set('--glass-blur', `${cfg.glass.blur}px`);
  set('--glass-saturate', `${cfg.glass.saturation}%`);
  set('--glass-alpha', String(cfg.glass.opacity / 100));
  set('--glass-border', String(cfg.glass.borderStrength / 100));
  set('--glass-elev', `${cfg.glass.elevation}px`);
  set('--grain-alpha', cfg.glass.grain ? String(cfg.glass.grainOpacity / 100) : '0');

  // —— 字体 ——
  // ✅ 字号走**合法通道**：五档阶梯（fs-page/card/body/caption/num）的 font-size 在 index.css 里
  //    写成 `var(--fs-*)`，这里只改那五枚变量的值。⑩ 的 font-size 声明带对 var() 形豁免
  //    （cssBandLadderValue 对含 var( 的值恒 false），而 --fs-* 不在受管变量名册里。
  //    这就是「字号自定义 px」真正生效的那根线；缺口已登记，待用户裁定是否收编进宪法。
  set('--fs-page', `${cfg.typography.pageSize}px`);
  set('--fs-card', `${cfg.typography.cardSize}px`);
  set('--fs-body', `${cfg.typography.rootSize}px`);
  set('--fs-caption', `${cfg.typography.captionSize}px`);
  set('--fs-num', `${cfg.typography.numSize}px`);
  // --ty-root 是历史别名（旧设置面板读它），跟着正文字号走。
  set('--ty-root', `${cfg.typography.rootSize}px`);
  set('--ty-leading', String(cfg.typography.lineHeight));
  set('--ty-track', `${cfg.typography.letterSpacing / 100}em`);
  set('--ty-weight', String(cfg.typography.weightBody));

  // —— 动效 ——
  // 速度倍率 → 时长倍率：>1 更快 = 时长为 1/速度。动画全部读 var(--mo-dur)，开启时按档缩放。
  set('--mo-dur', String(1 / Math.max(0.1, cfg.motion.speed)));
  set('--mo-play', cfg.motion.enabled ? 'running' : 'paused');
  set('--mo-alpha', cfg.motion.enabled ? '1' : '0');

  // —— 配色 ——
  set('--ap-brand', cfg.palette.brand);
  set('--ap-purple', cfg.palette.purple);
  set('--ap-deep', cfg.palette.deep);
  set('--ap-danger', cfg.palette.danger);
  set('--ap-success', cfg.palette.success);
  set('--ap-warning', cfg.palette.warning);

  // —— 布局（第 9 组）——
  // ⚠️ 侧栏宽 / 顶栏高这两枚仍然只写变量：app-shell 用的是 Tailwind 静态类
  //    （w-56 xl:w-64 / h-14 sm:h-16），没有消费 `--cfg-sidebar-w` / `--cfg-header-h`，
  //    所以这两个滑块目前**不动画面**（已在 A2 报告里点名，属遗留，不是本波修的范围）。
  set('--cfg-side', cfg.layout.side);
  set('--cfg-sidebar-w', `${cfg.layout.sidebarWidth}px`);
  set('--cfg-header-h', `${cfg.layout.headerHeight}px`);
  // ✅ 圆角：写 Tailwind 真正消费的三枚值册变量（index.css 的 --radius-md/lg/xl 指向它们，
  //    全站 rounded-md/lg/xl 直接跟着变）。旧版写的 `--cfg-radius` 没有任何消费方 = 死变量，
  //    所以「面板圆角」滑块以前怎么拖界面都不动。
  const radius = cfg.layout.radius;
  set('--r-panel', `${radius}px`);
  set('--r-shell', `${radius + 12}px`);
  set('--r-tile', `${Math.max(0, radius - 4)}px`);
  set('--cfg-radius', `${radius}px`); // 历史别名，保留给尚未迁移的消费方
  // ✅ 间距：一个倍率同时缩放三枚真实消费的变量——
  //    --shell-gap（外壳里面板之间的缝）/ --shell-inset（面板与屏幕边缘）/ --cfg-gap（页内面板缝）。
  //    三者的消费点在 app-shell 的行内 style 与 index.css 的 shell-* 工具类里；
  //    旧版写的 --cfg-gap 只有在 shell-* 工具类被用到时才生效，等于一直没生效。
  const gapScale = cfg.layout.spacing;
  // W13-V2 间距归一：出厂基数从 12 抬到 16。V 席实测改前全站三套间距并存
  // （12 = 这一枚 / 16 = 卡片网格的 16px 缝 / 24 = 外观页分组列），同一页三种节奏。
  // 现在统一 16；本枚是「页内面板缝」的唯一真身，index.css 的出厂值同步改成 16px
  // （首帧在 apply 之前渲染，两处不一致就会看到 12→16 的一次跳动）。
  set('--cfg-gap', `${Math.round(16 * gapScale)}px`);
  set('--shell-gap', `${Math.round(16 * gapScale)}px`);
  set('--shell-inset', `${Math.round(12 * gapScale)}px`);
  set('--cfg-cols', String(cfg.layout.gridColumns));
  set('--cfg-card-min', `${cfg.layout.cardMinWidth}px`);
  set('--cfg-header-pos', cfg.layout.headerSticky ? 'sticky' : 'static');
  set('--cfg-header-glass', cfg.layout.headerFloating ? `${cfg.glass.blur}px` : '0px');

  // —— 日志视图（第 11 组）——
  set('--cfg-log-leading', String(cfg.logView.lineHeight));
  set('--cfg-log-size', `${cfg.logView.textSize}px`);
  set('--cfg-log-family', cfg.logView.mono ? 'var(--font-mono)' : 'var(--font-sans)');
  set('--cfg-log-wrap', cfg.logView.wrap ? 'pre-wrap' : 'pre');

  // —— 数据密度（第 16 组）——
  set('--cfg-row-pad', cfg.density.tableDensity === 'compact' ? '4px' : '12px');

  // —— 无障碍（第 15 组）——
  set('--cfg-contrast-boost', cfg.a11y.highContrast ? '1' : '0');
  set('--cfg-text-boost', cfg.a11y.largeText ? '1.125' : '1');
  set('--cfg-force-reduce', cfg.a11y.forceReduceMotion ? 'reduce' : 'no-preference');
  set('--cfg-focus-w', `${cfg.a11y.focusRingWidth}px`);
  set('--cfg-focus-color', toneVar(cfg.a11y.focusRingColor, 'var(--ring)'));

  // —— 省流量（第 17 组）：CSS 侧据此停动画/停媒体 ——
  set('--cfg-saver', cfg.performance.dataSaver ? '1' : '0');

  // —— 同一批开关的**属性面**（W13-L 补）——
  // index.css 里「高对比 / 色盲友好 / 强制减动效 / 省流量」四条规则一直挂在
  // `<html data-contrast|data-cb|data-motion|data-saver>` 上，但全树**没有任何地方
  // 写过这四个属性**（此前只有 --cfg-* 三枚变量，而它们没有读者）。于是那四个开关
  // 从上线起就是空转：变量写进 <html>，属性永远不出现，规则永远不匹配。
  // 这里把属性与变量在同一处落下 —— 属性面才是那四条规则的真正入口。
  // 桩 root（单测/SSR）没有 dataset，按可选处理，不为此改变 applyAppearance 的签名。
  const el = root as HTMLElement;
  if (el.dataset) {
    // 只在「真的有话要说」时挂属性：留着 data-cb="none" / data-motion="" 这种空值，
    // 会让 index.css 里 `:not([data-cb])` 一类的让路判据永远为假（等价于开关卡住）。
    const setAttr = (name: string, value: string) => {
      if (value) el.dataset[name] = value;
      else delete el.dataset[name];
    };
    setAttr('contrast', cfg.a11y.highContrast ? 'high' : '');
    setAttr('cb', cfg.a11y.colorBlind === 'none' ? '' : cfg.a11y.colorBlind);
    setAttr('motion', cfg.motion.enabled ? '' : 'off');
    setAttr('saver', cfg.performance.dataSaver ? '1' : '');
  }
}

/** 试算用：桩 root（单测与 SSR 兜底），不需要 DOM。 */
export function collectAppearanceVars(cfg: AppearanceConfig): Record<string, string> {
  const bag: Record<string, string> = {};
  const fake = {
    style: {
      setProperty(name: string, value: string) {
        bag[name] = value;
      },
    },
  } as unknown as HTMLElement;
  applyAppearance(cfg, fake);
  return bag;
}

// ============================================================================
// 写不进 CSS 变量、只能由组件读的那部分配置的**派生口径**。
// 页面与图表组件用这些函数，避免各自写一份「60s 是多少毫秒」「动效到底开不开」。
// ============================================================================

export function refreshMs(cfg: AppearanceConfig): number {
  switch (cfg.charts.refresh) {
    case '5s':
      return 5000;
    case '15s':
      return 15000;
    case '60s':
      return 60000;
    default:
      return 0;
  }
}

export function cacheTtlMs(cfg: AppearanceConfig): number {
  switch (cfg.performance.requestCache) {
    case '30s':
      return 30000;
    case '60s':
      return 60000;
    case '300s':
      return 300000;
    default:
      return 0;
  }
}

/** 自动刷新是否生效：全局轮询关了，单页节奏一律失效。 */
export function pollingActive(cfg: AppearanceConfig): boolean {
  return cfg.interaction.polling && !cfg.performance.dataSaver && refreshMs(cfg) > 0;
}

/** 统一的动效开关：动效总开关、无障碍强制、省流三者任一要求停，就停。 */
export function motionAllowed(cfg: AppearanceConfig): boolean {
  if (cfg.a11y.forceReduceMotion || cfg.performance.dataSaver) return false;
  return cfg.motion.enabled;
}

/** 时区偏置（分钟），供日期/时间格式化用；'local' = 跟随本机。 */
export function timezoneOffsetMinutes(cfg: AppearanceConfig): number | 'local' {
  if (cfg.locale.timezone === 'utc') return 0;
  if (cfg.locale.timezone === 'fixed') return cfg.locale.fixedOffset * 60;
  return 'local';
}
