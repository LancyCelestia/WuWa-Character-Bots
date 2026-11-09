// 热力图（手写 SVG，零依赖）：行（如小时 0-23）× 列（如星期 0-6）。
// 强度用同一个色档的透明度表达——不靠"换颜色"表意，颜色始终是 --chart-N。
import { useState } from 'react';

import { chartColor, formatValue, heatmapCells, type ChartToken } from '@/lib/chart-model';
import { cn } from '@/lib/utils';

import { ChartEmpty, ChartTooltip } from './chart-primitives';

export interface HeatmapProps {
  rows: readonly string[];
  cols: readonly string[];
  /** 取单元格数值。 */
  value: (row: number, col: number) => number;
  label: string;
  token?: ChartToken;
  format?: (value: number) => string;
  className?: string;
}

/** 强度 → 透明度（0 也留一丝底线，空格子要看得见但读得出"没有"）。 */
function intensityOpacity(intensity: number): number {
  if (!Number.isFinite(intensity) || intensity <= 0) return 0.04;
  return 0.12 + intensity * 0.88;
}

/**
 * 热力矩阵。
 * · 动画：格子淡入（CSS .chart-cell，只动 opacity）
 * · 可访问：role=img + aria-label 给出行列与峰值；每格 <title> 携带"行/列/值"文本，
 *   下方还有一条不依赖颜色的图例（低→高 + 峰值数值）
 * · 响应式：viewBox + w-full
 */
export function Heatmap({
  rows,
  cols,
  value,
  label,
  token = 1,
  format = formatValue,
  className,
}: HeatmapProps) {
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  if (rows.length === 0 || cols.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        <ChartEmpty text='暂无数据' aspect={2} />
      </div>
    );
  }

  const cells = heatmapCells(rows.length, cols.length, value);
  const maxValue = cells.reduce((max, cell) => Math.max(max, cell.value), 0);
  const color = chartColor(token);

  const cellW = 100 / cols.length;
  const cellH = 100 / rows.length;
  const gap = 0.6;
  const activeCell = hover ? cells.find((c) => c.row === hover.row && c.col === hover.col) : undefined;

  return (
    <div className={cn('relative w-full', className)} onMouseLeave={() => setHover(null)}>
      <svg
        role='img'
        aria-label={`${label}（峰值 ${format(maxValue)}）`}
        viewBox='0 0 100 100'
        preserveAspectRatio='none'
        className='w-full'
        style={{ aspectRatio: String(Math.max(cols.length / Math.max(rows.length, 1), 1.2)) }}
      >
        {cells.map((cell) => {
          const active = hover !== null && hover.row === cell.row && hover.col === cell.col;
          return (
            <rect
              key={`${cell.row}-${cell.col}`}
              x={cell.col * cellW + gap / 2}
              y={cell.row * cellH + gap / 2}
              width={Math.max(cellW - gap, 0.5)}
              height={Math.max(cellH - gap, 0.5)}
              rx={1}
              fill={color}
              fillOpacity={active ? 1 : intensityOpacity(cell.intensity)}
              stroke={active ? 'var(--foreground)' : 'none'}
              strokeWidth={0.5}
              className='chart-cell'
              onMouseEnter={() => setHover({ row: cell.row, col: cell.col })}
            >
              <title>{`${rows[cell.row]} / ${cols[cell.col]}：${format(cell.value)}`}</title>
            </rect>
          );
        })}
      </svg>

      {/* 不靠颜色的图例：文字 + 峰值数值 */}
      <div className='mt-1 flex flex-wrap items-center justify-between gap-2 fs-caption text-muted-foreground'>
        <span>{rows.length > 3 ? `${rows[0]} … ${rows[rows.length - 1]}` : rows.join(' · ')}</span>
        <span className='flex items-center gap-1'>
          <span>低</span>
          <span aria-hidden='true' className='inline-block size-3' style={{ backgroundColor: color, opacity: intensityOpacity(0.15) }} />
          <span aria-hidden='true' className='inline-block size-3' style={{ backgroundColor: color, opacity: intensityOpacity(0.5) }} />
          <span aria-hidden='true' className='inline-block size-3' style={{ backgroundColor: color, opacity: intensityOpacity(1) }} />
          <span>高（{format(maxValue)}）</span>
        </span>
      </div>

      {hover && activeCell ? (
        <ChartTooltip x={(hover.col + 0.5) * cellW}>
          <div className='font-medium'>
            {rows[hover.row]} / {cols[hover.col]}
          </div>
          <div className='tabular-nums text-muted-foreground'>{format(activeCell.value)}</div>
        </ChartTooltip>
      ) : null}
    </div>
  );
}
