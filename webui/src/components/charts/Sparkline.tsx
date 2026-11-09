// 迷你趋势线（卡片内嵌，高密度）。**不是**一条断掉的斜线：
// 它是 LineChart 的紧凑档——y 刻度、淡网格、x 轴标签（给 labels 时）、
// hover 十字准星与末端数值都保留，只是留白更薄、默认不出图例。
//
// 为什么复用同一渲染器而不是再写一份 path：sparkline 与折线图各写一套比例尺，
// 两边迟早会对不上（一边修好坐标轴、另一边还是裸线）。同一个渲染器只有一种真相。
import { formatValue } from '@/lib/chart-model';
import { cn } from '@/lib/utils';

import { LineChart } from './LineChart';

export interface SparklineProps {
  values: readonly number[];
  /** 面积填充（默认开）。 */
  area?: boolean;
  /** 宽/高比例；迷你图通常扁平。 */
  aspect?: number;
  /** 可访问名；读屏会听到峰值/末值。 */
  label: string;
  format?: (value: number) => string;
  /** x 轴标签（与 values 等长）。传 `formatTimeLabel(bucket_start)` 就能得到时间轴。 */
  labels?: readonly string[];
  /** 空态第二行：为什么没有数据。 */
  emptyHint?: string;
  className?: string;
}

/**
 * 迷你趋势线。
 * · 动画：path 描边（CSS .chart-draw）
 * · 可访问：role=img + aria-label（含峰值/末值）+ tooltip + 末端数值
 * · 响应式：实测像素 + viewBox
 */
export function Sparkline({
  values,
  area = true,
  aspect = 3,
  label,
  format = formatValue,
  labels,
  emptyHint,
  className,
}: SparklineProps) {
  return (
    <div className={cn('w-full', className)}>
      <LineChart
        compact
        area={area}
        aspect={aspect}
        label={label}
        format={format}
        labels={labels}
        emptyHint={emptyHint}
        showLegend={false}
        series={[{ key: 'sparkline', label, values }]}
      />
    </div>
  );
}
