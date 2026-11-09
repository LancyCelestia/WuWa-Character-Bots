// 图表共享原语（组件层唯一的"公共地基"）。
//
// 三条铁律的落点：
//   1. 响应式——宽度 100%（CSS `w-full`），几何按**实测像素**算（useChartWidth），
//      字号/线宽/留白因此不随画布缩放变糊；SVG viewBox 与容器同比例，不写死宽度。
//   2. reduced-motion——统一由 index.tsx 里的 CSS 媒体查询关掉（比 JS 判定更早生效，
//      也不会在首帧闪一下）；这里不重复一套 JS 开关。
//   3. 主题化——颜色只经 chartColor() 取 `var(--chart-N)`，本文件不出现任何色值。
//
// 为什么从「viewBox 固定 100 宽」改成「实测像素」：固定 100 宽时 1 用户单位 = 面板宽/100，
// 同一份 fontSize=3.6 在 470px 卡片里接近 17px、在 390px 手机里只剩 14px，
// 刻度字会跟卡片宽度一起跳舞。实测一次宽度后，刻度永远是 11px，图才像产品而不像缩略图。
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { chartColor, type ChartToken } from '@/lib/chart-model';
import { cn } from '@/lib/utils';

/** 图表刻度字号（px）。取五档阶梯的 caption 同值 12，只用于 SVG 内部（不走 CSS 字号门）。 */
export const TICK_FONT = 12;
/** 数值标注字号（px）：比刻度大半档，让"数据"压过"坐标"。 */
export const VALUE_FONT = 13;

/**
 * 容器实测宽度。首帧用 useLayoutEffect 同步量（避免先用 fallback 画一帧再跳），
 * 之后由 ResizeObserver 跟窗口/栅格变化。
 */
export function useChartWidth(fallback = 560) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const apply = (next: number) => {
      if (!(next > 0)) return;
      setWidth((prev) => (Math.abs(prev - next) < 0.5 ? prev : next));
    };
    apply(node.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      apply(entry?.contentRect.width ?? 0);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, width: width > 0 ? width : fallback };
}

/**
 * 图例：色块 + 文字 + 可选数值。
 * 文字是本体的可读源——色块只是辅助，色盲用户读文字照样拿得到全部信息。
 */
export function ChartLegend({
  items,
  className,
}: {
  items: readonly { label: string; token: ChartToken; value?: string }[];
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <ul className={cn('flex flex-wrap items-center gap-x-4 gap-y-1', className)}>
      {items.map((item) => (
        <li key={item.label} className='flex items-center gap-2 fs-caption text-muted-foreground'>
          <span
            aria-hidden='true'
            className='inline-block size-2 rounded-full'
            style={{ backgroundColor: chartColor(item.token) }}
          />
          <span>{item.label}</span>
          {item.value ? <span className='font-medium text-foreground tabular-nums'>{item.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/**
 * 空态：不画空坐标轴假装"有图但都是 0"。
 * 一句「暂无数据」+ 一句为什么（hint），比一块白板诚实，也比一条孤零零的线体面。
 */
export function ChartEmpty({
  text = '暂无数据',
  hint,
  aspect,
}: {
  text?: string;
  hint?: string;
  aspect: number;
}) {
  return (
    <div
      role='img'
      aria-label={hint ? `${text}：${hint}` : text}
      className='flex w-full flex-col items-center justify-center gap-2 rounded-lg bg-muted/40 p-4 fs-caption text-muted-foreground'
      style={{ aspectRatio: String(aspect) }}
    >
      <span className='fs-body text-foreground'>{text}</span>
      {hint ? <span className='max-w-3/4 text-center'>{hint}</span> : null}
    </div>
  );
}

/**
 * hover 浮层。两种定位：
 * · 传 `xPx` + `containerWidth`（新图表）：按真实像素定位并夹在容器内，不遮住指针；
 * · 只传 `x`（兼容旧图表）：百分比语义，夹在 [16, 84]。
 */
export function ChartTooltip({
  children,
  x,
  xPx,
  containerWidth,
}: {
  children: ReactNode;
  x?: number;
  xPx?: number;
  containerWidth?: number;
}) {
  let left: string;
  if (xPx !== undefined && containerWidth && containerWidth > 0) {
    const clamped = Math.min(Math.max(xPx, 88), containerWidth - 88);
    left = `${clamped}px`;
  } else if (x !== undefined) {
    left = `${Math.min(Math.max(x, 16), 84)}%`;
  } else {
    left = '50%';
  }
  return (
    <div
      role='tooltip'
      className='pointer-events-none absolute top-0 z-10 max-w-3/4 -translate-x-1/2 rounded-md border bg-popover px-2 py-1 fs-caption text-popover-foreground shadow-sm tabular-nums'
      style={{ left }}
    >
      {children}
    </div>
  );
}

/** tooltip 里的一行（色点 + 名称 + 数值）。 */
export function TooltipRow({ label, value, token }: { label: string; value: string; token: ChartToken }) {
  return (
    <li className='flex items-center gap-2 whitespace-nowrap'>
      <span
        aria-hidden='true'
        className='inline-block size-2 rounded-full'
        style={{ backgroundColor: chartColor(token) }}
      />
      <span className='text-muted-foreground'>{label}</span>
      <span className='ml-auto font-medium tabular-nums'>{value}</span>
    </li>
  );
}

/**
 * 单行截断（保留供旧图表使用）。新图表用 chart-model 的 `wrapLabel` +
 * `<title>` 全名：可视省略 ≠ 信息丢失，而且能显示两行可辨识前缀。
 */
export function clipLabel(label: string, max = 10): string {
  if (label.length <= max) return label;
  return `${label.slice(0, max - 1)}…`;
}

/** 多行 SVG 文本（分类标签换行用）。每行一个 tspan，行高 1.2em。 */
export function MultilineText({
  lines,
  x,
  y,
  fontPx,
  fill = 'var(--muted-foreground)',
  anchor = 'end',
}: {
  lines: readonly string[];
  x: number;
  y: number;
  fontPx: number;
  fill?: string;
  anchor?: 'start' | 'middle' | 'end';
}) {
  if (lines.length === 0) return null;
  const lineHeight = fontPx * 1.2;
  const start = y - ((lines.length - 1) * lineHeight) / 2;
  return (
    <text x={x} y={start} fontSize={fontPx} fill={fill} textAnchor={anchor} dominantBaseline='middle'>
      {lines.map((line, index) => (
        <tspan key={`${line}-${index}`} x={x} dy={index === 0 ? 0 : lineHeight}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

