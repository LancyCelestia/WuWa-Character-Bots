// 分段选择器 / 单选组的宽度算术（G5：折行与压字）。
//
// 用户截图里的「图表绘制质量 低/中/高」「取色来源 跟随语义色/品牌色/自定义」两处缺陷，
// 根因不是配色也不是阴影，是**宽度算术**：控件区被压得比选项组内在宽度还窄，于是每个
// label 各自折行，选中胶囊就压在邻项文字上。
//
// 仓库没有 jsdom / playwright，也不许为此装包；所以把「给定宽度下排几行、每项占哪段 x、
// 相邻是否相交」抽成纯函数，组件与测试共用同一份算术：
//   · 够宽（含余量）→ 舒适档单行；
//   · 略窄 → 降一档（fs-caption + px-2）仍保单行；
//   · 连紧凑档都放不下一行 → 两列均分（grid），每项 shrink-0 + nowrap，绝不断词、绝不互压。
//
// 字宽模型：汉字/全角标点按 1 个字宽，ASCII 按 0.6 个字宽。这是估算而非测量，
// 所以降档判定留 SEGMENT_SLACK_PX 余量；真实宽度由浏览器再算一遍，但「每项不收缩、
// label 内部不折行」是 CSS 层的硬保证，与估算无关。
//
// ponytail: 不做运行期文本测量（getBoundingClientRect / ResizeObserver 都要 DOM，
// 本仓测试跑不了）。上限：字体替换或用户自定义字号（外观页可改 --fs-*）可能让估算偏小，
// 那时靠 CSS 的 shrink-0 + nowrap 兜底（换行不压字），不会退回截图那种重叠。
// 升级路径=把 labelWidth 换成 canvas measureText 探针，并用 ResizeObserver 触发重排。

export interface SegmentMetrics {
  /** 单字宽（px）：fs-body=13 / fs-caption=12，与五档阶梯同源。 */
  readonly charPx: number;
  /** 每项左右内边距之和：px-3=24 / px-2=16。 */
  readonly optionPadX: number;
  /** 项间隙：gap-1=4。 */
  readonly gap: number;
  /** 轨道内边距：p-1=4。 */
  readonly trackPad: number;
}

export type SegmentDensity = 'comfortable' | 'compact';

export const SEGMENT_TIERS: Record<SegmentDensity, SegmentMetrics> = {
  comfortable: { charPx: 13, optionPadX: 12, gap: 4, trackPad: 4 },
  compact: { charPx: 12, optionPadX: 8, gap: 4, trackPad: 4 },
};

/**
 * 外观页 Field 控件区在 sm 断点上的最小可用宽度（224px = `sm:min-w-56`）。
 * 与 field.tsx 里那个类**同源**：改一处必须改另一处，否则这套算术就是纸面数字。
 */
export const SEGMENT_AVAILABLE_DEFAULT = 224;

/** 降档判定余量：字体差异 / 浏览器取整都可能吃掉几个像素，别让「刚好够」变成「刚好溢」。 */
export const SEGMENT_SLACK_PX = 8;

const ASCII_RATIO = 0.6;

/** 全角字符（CJK、全角标点、谚文、假名、兼容区）占一个字宽。 */
function isFullWidth(code: number): boolean {
  return (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6)
  );
}

export function labelWidth(label: string, metrics: SegmentMetrics): number {
  let units = 0;
  for (const char of label) units += isFullWidth(char.codePointAt(0) ?? 0) ? 1 : ASCII_RATIO;
  return Math.ceil(units * metrics.charPx);
}

export function optionWidth(label: string, metrics: SegmentMetrics): number {
  return labelWidth(label, metrics) + metrics.optionPadX * 2;
}

/** 全部选项挤在一行时需要的宽度（含轨道内边距与项间隙）。 */
export function segmentRowWidth(labels: readonly string[], metrics: SegmentMetrics): number {
  if (labels.length === 0) return 0;
  const items = labels.reduce((sum, label) => sum + optionWidth(label, metrics), 0);
  return metrics.trackPad * 2 + items + metrics.gap * (labels.length - 1);
}

export interface SegmentBox {
  readonly label: string;
  readonly x: number;
  readonly width: number;
}

export interface SegmentRow {
  readonly boxes: SegmentBox[];
  /** 该行占宽（含轨道内边距）；> available 时行内必定只剩一个超宽项。 */
  readonly width: number;
  readonly overflow: boolean;
}

/**
 * 按可用宽度把选项排成若干行。行内保证 `box[i].x + box[i].width <= box[i+1].x`
 * ——这项不变量就是「相邻选项绝不互相覆盖」的机器表达。
 */
export function planSegmentRows(
  labels: readonly string[],
  available: number,
  metrics: SegmentMetrics,
): SegmentRow[] {
  if (labels.length === 0) return [];
  const content = Math.max(0, available - metrics.trackPad * 2);
  const rows: Array<{ boxes: SegmentBox[]; used: number }> = [];
  let row = { boxes: [] as SegmentBox[], used: 0 };

  for (const label of labels) {
    const width = optionWidth(label, metrics);
    const extra = row.boxes.length === 0 ? width : width + metrics.gap;
    if (row.boxes.length > 0 && row.used + extra > content) {
      rows.push(row);
      row = { boxes: [], used: 0 };
    }
    const gap = row.boxes.length === 0 ? 0 : metrics.gap;
    const x = metrics.trackPad + row.used + gap;
    row.boxes.push({ label, x, width });
    row.used += row.boxes.length === 1 ? width : width + metrics.gap;
  }
  rows.push(row);

  return rows.map(({ boxes, used }) => ({
    boxes,
    width: metrics.trackPad * 2 + used,
    overflow: metrics.trackPad * 2 + used > available,
  }));
}

/** 舒适档放不下（含余量）就降紧凑档；降档仍是单行的，视觉上只差一档字。 */
export function segmentDensity(
  labels: readonly string[],
  available: number = SEGMENT_AVAILABLE_DEFAULT,
): SegmentDensity {
  return segmentRowWidth(labels, SEGMENT_TIERS.comfortable) + SEGMENT_SLACK_PX <= available
    ? 'comfortable'
    : 'compact';
}

/** 一行 → 横排不换行；多行 → grid 两列均分（绝不靠压扁文字硬塞一行）。 */
export function segmentLayoutClass(rowCount: number): string {
  return rowCount > 1 ? 'grid grid-cols-2' : 'inline-flex flex-nowrap';
}

/** 轨道外壳：材质与圆角统一走语义 token（门禁禁裸色值/任意值）。 */
export function segmentTrackClass(rowCount: number): string {
  return [
    'max-w-full shrink-0 items-center gap-1 rounded-lg border bg-muted/60 p-1',
    segmentLayoutClass(rowCount),
  ].join(' ');
}

/**
 * 单个选项：**shrink-0 + whitespace-nowrap 两条是硬保证**——label 内部一旦折行，
 * 选中胶囊的底色就会盖到下一行文字上（用户截图那个「压字」）。
 */
/**
 * 档位 → 具名类。**必须一行一档**：版式宪法门 ⑦ 是行级判定，同一行里出现两个
 * fs-*（哪怕是三元的两个分支）会被当成「同元素双写」判红。
 */
const TIER_CLASS: Record<SegmentDensity, string> = {
  comfortable: 'px-3 fs-body',
  compact: 'px-2 fs-caption',
};

export function segmentOptionClass(
  density: SegmentDensity,
  active: boolean,
  rowCount = 1,
): string {
  return [
    'shrink-0 cursor-pointer whitespace-nowrap rounded-md py-1 transition-colors motion-reduce:transition-none',
    TIER_CLASS[density],
    rowCount > 1 && 'text-center',
    active ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
  ]
    .filter(Boolean)
    .join(' ');
}
