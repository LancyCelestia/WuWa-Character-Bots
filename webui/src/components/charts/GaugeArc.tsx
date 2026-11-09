// 半圆仪表盘（手写 SVG，零依赖）：成功率、健康度这类"一个数配一个刻度"的场景。
import { chartColor, formatValue, gaugeArc, seriesToken, type ChartToken } from '@/lib/chart-model';
import { cn } from '@/lib/utils';

export interface GaugeArcProps {
  /** 当前值（0–max）。 */
  value: number;
  max?: number;
  label: string;
  /** 中心主文字（缺省为百分比）。 */
  display?: string;
  /** 副标题（如"近 24 小时"）。 */
  caption?: string;
  token?: ChartToken;
  aspect?: number;
  format?: (value: number) => string;
  className?: string;
}

const CX = 50;
const CY = 46;
const RADIUS = 38;

/**
 * 半圆仪表盘。
 * · 动画：弧长描边生长（CSS .chart-draw，reduced-motion 关）
 * · 可访问：role=img + aria-label（含精确值、满值、进度）+ 中心数值即数值标签
 * · 响应式：viewBox 100×56 + w-full
 */
export function GaugeArc({
  value,
  max = 100,
  label,
  display,
  caption,
  token,
  aspect = 1.8,
  format = formatValue,
  className,
}: GaugeArcProps) {
  const safeMax = Number.isFinite(max) && max > 0 ? max : 100;
  const ratio = Math.min(Math.max(Number.isFinite(value) ? value / safeMax : 0, 0), 1);
  const color = chartColor(token ?? seriesToken(0));

  const track = gaugeArc(CX, CY, RADIUS, 1);
  const fill = gaugeArc(CX, CY, RADIUS, ratio);
  const percent = Math.round(ratio * 1000) / 10;

  return (
    <div className={cn('relative w-full', className)} style={{ aspectRatio: String(aspect) }}>
      <svg
        role='img'
        aria-label={`${label}：${format(value)}，满值 ${format(safeMax)}，进度 ${percent}%`}
        viewBox='0 0 100 56'
        preserveAspectRatio='xMidYMid meet'
        className='h-full w-full'
      >
        <path d={track.d} fill='none' stroke='var(--border)' strokeWidth={7} strokeLinecap='round' />
        {fill.d ? (
          <path
            d={fill.d}
            fill='none'
            stroke={color}
            strokeWidth={7}
            strokeLinecap='round'
            pathLength={1}
            strokeDasharray={1}
            className='chart-draw'
          />
        ) : null}
        <text x={CX} y={CY - 2} textAnchor='middle' dominantBaseline='middle' fontSize={14} fill='var(--foreground)' className='tabular-nums'>
          {display ?? `${percent}%`}
        </text>
        {caption ? (
          <text x={CX} y={CY + 9} textAnchor='middle' dominantBaseline='middle' fontSize={5} fill='var(--muted-foreground)'>
            {caption}
          </text>
        ) : null}
      </svg>
    </div>
  );
}
