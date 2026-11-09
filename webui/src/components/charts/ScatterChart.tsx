// 散点图（手写 SVG，零依赖）。数据点自带辉光。
import { useMemo, useState } from 'react';

import { chartColor, formatValue, linearScale, niceTicks, seriesToken, type ChartToken } from '@/lib/chart-model';
import { cn } from '@/lib/utils';

import { ChartEmpty, ChartLegend, ChartTooltip } from './chart-primitives';

const VIEW_W = 100;

export interface ScatterPoint {
  x: number;
  y: number;
  /** 点标签（tooltip / aria 用）。 */
  label: string;
}

export interface ScatterSeries {
  key: string;
  label: string;
  points: readonly ScatterPoint[];
  token?: ChartToken;
}

export interface ScatterChartProps {
  series: readonly ScatterSeries[];
  aspect?: number;
  label: string;
  formatX?: (value: number) => string;
  formatY?: (value: number) => string;
  showLegend?: boolean;
  className?: string;
}

/**
 * 散点图。
 * · 动画：点淡入（CSS .chart-point，只动 opacity）
 * · 可访问：role=img + aria-label + 图例 + tooltip 给出精确坐标
 * · 响应式：viewBox + w-full
 */
export function ScatterChart({
  series,
  aspect = 2,
  label,
  formatX = formatValue,
  formatY = formatValue,
  showLegend = true,
  className,
}: ScatterChartProps) {
  const [hover, setHover] = useState<{ series: string; point: ScatterPoint } | null>(null);
  const viewH = VIEW_W / aspect;
  const plotH = viewH * 0.86;
  const plotW = VIEW_W * 0.9;

  const all = series.flatMap((s) => s.points);
  const xs = all.map((p) => p.x).filter(Number.isFinite);
  const ys = all.map((p) => p.y).filter(Number.isFinite);
  // 依赖用长度+极值而不是数组字面量：数组每次渲染都是新引用，会让 memo 恒失效。
  const xKey = `${xs.length}:${Math.min(...xs)}:${Math.max(...xs)}`;
  const yKey = `${ys.length}:${Math.min(...ys)}:${Math.max(...ys)}`;
  const xTicks = useMemo(() => niceTicks(Math.min(0, ...xs), Math.max(1, ...xs), 4), [xKey]);
  const yTicks = useMemo(() => niceTicks(Math.min(0, ...ys), Math.max(1, ...ys), 4), [yKey]);

  const x = linearScale({ min: xTicks[0] ?? 0, max: xTicks.at(-1) ?? 1 }, [0, plotW]);
  const y = linearScale({ min: yTicks[0] ?? 0, max: yTicks.at(-1) ?? 1 }, [plotH, 0]);

  if (all.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        <ChartEmpty text='暂无数据' aspect={aspect} />
      </div>
    );
  }

  return (
    <div className={cn('relative w-full', className)} style={{ aspectRatio: String(aspect) }} onMouseLeave={() => setHover(null)}>
      <svg
        role='img'
        aria-label={label}
        viewBox={`0 0 ${VIEW_W} ${viewH}`}
        preserveAspectRatio='none'
        className='h-full w-full'
      >
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line x1={0} x2={plotW} y1={y(tick)} y2={y(tick)} stroke='var(--border)' strokeWidth={0.5} />
            <text x={VIEW_W} y={y(tick)} fontSize={3.2} fill='var(--muted-foreground)' textAnchor='end' dominantBaseline='middle'>
              {formatY(tick)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text
            key={`x-${tick}`}
            x={x(tick)}
            y={plotH + 1.6}
            fontSize={3.2}
            fill='var(--muted-foreground)'
            textAnchor='middle'
            dominantBaseline='hanging'
          >
            {formatX(tick)}
          </text>
        ))}

        {series.map((s, si) => {
          const color = chartColor(s.token ?? seriesToken(si));
          return s.points.map((point, pi) => (
            <g key={`${s.key}-${pi}`}>
              {/* 辉光：同色大圆低透明度，不用 filter（省 GPU，reduced-motion 也无需特殊处理） */}
              <circle cx={x(point.x)} cy={y(point.y)} r={2.6} fill={color} opacity={0.22} />
              <circle
                cx={x(point.x)}
                cy={y(point.y)}
                r={1.3}
                fill={color}
                className='chart-point'
                onMouseEnter={() => setHover({ series: s.label, point })}
              >
                <title>{`${point.label}：${formatX(point.x)} / ${formatY(point.y)}`}</title>
              </circle>
            </g>
          ));
        })}
        <line x1={0} x2={plotW} y1={plotH} y2={plotH} stroke='var(--border)' strokeWidth={0.6} />
      </svg>

      {hover ? (
        <ChartTooltip x={(x(hover.point.x) / VIEW_W) * 100}>
          <div className='font-medium'>{hover.point.label}</div>
          <div className='tabular-nums text-muted-foreground'>
            {hover.series} · {formatX(hover.point.x)} / {formatY(hover.point.y)}
          </div>
        </ChartTooltip>
      ) : null}

      {showLegend ? (
        <ChartLegend
          className='mt-1'
          items={series.map((s, si) => ({
            label: s.label,
            token: s.token ?? seriesToken(si),
            value: `${s.points.length} 点`,
          }))}
        />
      ) : null}
    </div>
  );
}
