// 折线 / 面积图（手写 SVG，零依赖）。
//
// 坐标策略：**实测容器像素**（useChartWidth），几何全部按 px 计算——
// 刻度字恒为 11px、网格恒为 1px，不随卡片宽度缩放。容器自身用 aspectRatio
// 锁定画布比例，SVG 的 viewBox 与它同比例，因此不会出现文字被横向拉扁。
//
// 一张"能上付费监控产品"的折线图要有四件：y 轴刻度 + 淡网格、x 轴时间标签、
// 鼠标十字准星 + tooltip、末端数值标注。四件都在这里，缺一件就退化成"断掉的斜线"。
import { useId, useMemo, useState } from 'react';

import {
  areaPath,
  chartColor,
  formatValue,
  indexFromPointer,
  linePath,
  linearScale,
  measureLabelWidth,
  niceDomain,
  niceTickIndexes,
  seriesToken,
  smoothPath,
  type ChartToken,
} from '@/lib/chart-model';
import { cn } from '@/lib/utils';

import {
  ChartEmpty,
  ChartLegend,
  ChartTooltip,
  TICK_FONT,
  TooltipRow,
  VALUE_FONT,
  useChartWidth,
} from './chart-primitives';

export interface LineSeries {
  key: string;
  label: string;
  values: readonly (number | null)[];
  /** 覆盖色档；缺省按序列下标取 --chart-N。 */
  token?: ChartToken;
}

export interface LineChartProps {
  series: readonly LineSeries[];
  /** x 轴标签（与 values 等长）。建议传 `formatTimeLabel(bucket_start)` 的结果。 */
  labels?: readonly string[];
  /** 面积渐变填充。 */
  area?: boolean;
  /** 平滑曲线（Catmull-Rom）。要看真实拐点时留 false。 */
  smooth?: boolean;
  /** 绘图区宽/高。 */
  aspect?: number;
  /** 可访问名（role=img 的 aria-label）。必须说清"这是什么图"。 */
  label: string;
  format?: (value: number) => string;
  showLegend?: boolean;
  showAxis?: boolean;
  /** 空态第二行：为什么没有数据（比一块白板诚实）。 */
  emptyHint?: string;
  /** 紧凑档（Sparkline 用）：更薄的留白、3 条 y 刻度。 */
  compact?: boolean;
  className?: string;
}

/** 有限值过滤：null/NaN 当 0（缺这一格不等于整条线断掉）。 */
const safe = (value: number | null | undefined): number => (Number.isFinite(value as number) ? (value as number) : 0);

/**
 * 折线 / 面积图。
 * · 动画：path 描边（stroke-dasharray），prefers-reduced-motion 由 index.tsx 的 CSS 关掉
 * · 可访问：role=img + 峰值/末值写进 aria-label + 图例 + 末端数值标注 + 键盘可读点
 * · 响应式：实测像素 + viewBox，宽度 100%
 */
export function LineChart({
  series,
  labels,
  area = false,
  smooth = false,
  aspect = 2.4,
  label,
  format = formatValue,
  showLegend = true,
  showAxis = true,
  emptyHint,
  compact = false,
  className,
}: LineChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const { ref, width } = useChartWidth(compact ? 420 : 560);
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  // 高度有下限：再扁的卡片也不能把刻度与时间标签压成一条缝。
  const height = Math.max(
    compact ? 132 : 168,
    Math.round(width / Math.max(aspect, 0.5))
  );

  const count = useMemo(() => Math.max(0, ...series.map((s) => s.values.length)), [series]);
  const peak = useMemo(() => {
    let max = 0;
    for (const s of series) for (const value of s.values) if (Number.isFinite(value as number)) max = Math.max(max, value as number);
    return max;
  }, [series]);

  const domain = useMemo(() => niceDomain(peak, compact ? 3 : 4), [peak, compact]);
  // 四边留白全落 4px 栅格：视觉节奏可预测，也不会出现 13/17px 这种"差一点"的边距。
  const marginTop = compact ? 12 : 16;
  const marginRight = 16;
  const hasXLabels = Boolean(labels && labels.length > 0);
  const marginBottom = !showAxis ? 8 : hasXLabels ? 24 : 12;

  // y 刻度文字宽度决定左留白：宁可多留 6px，也不让 "1,200" 被裁成 "200"。
  const tickTextWidth = Math.max(
    ...domain.ticks.map((tick) => measureLabelWidth(format(tick), TICK_FONT)),
    TICK_FONT
  );
  const marginLeft = showAxis ? Math.ceil((tickTextWidth + 8) / 4) * 4 : 8;

  const plotLeft = marginLeft;
  const plotRight = Math.max(plotLeft + 10, width - marginRight);
  const plotTop = marginTop;
  const plotBottom = Math.max(plotTop + 10, height - marginBottom);
  const plotWidth = plotRight - plotLeft;
  const plotHeight = plotBottom - plotTop;

  const x = (index: number) => (count <= 1 ? plotLeft + plotWidth / 2 : plotLeft + (index / (count - 1)) * plotWidth);
  const yScale = useMemo(
    () => linearScale({ min: 0, max: domain.max }, [plotBottom, plotTop]),
    [domain.max, plotBottom, plotTop]
  );
  const y = (value: number | null | undefined) => yScale(safe(value));

  const lines = series.map((s, si) => {
    const token = s.token ?? seriesToken(si);
    const points = s.values.map((value, i) => ({ x: x(i), y: y(value) }));
    return { series: s, token, points, path: smooth ? smoothPath(points) : linePath(points) };
  });

  if (count === 0 || series.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        <ChartEmpty text='暂无数据' hint={emptyHint ?? '这个窗口还没有产生记录，换一个时间范围再试。'} aspect={aspect} />
      </div>
    );
  }

  const lastIndex = count - 1;
  const xLabelIndexes = (() => {
    if (!hasXLabels) return [];
    const perLabel = compact ? 56 : 68;
    const maxLabels = Math.max(2, Math.floor(plotWidth / perLabel));
    // 整齐步长（6 小时一跳），不是把 24 个桶机械均分成 05:00/09:00 这种怪刻度。
    return niceTickIndexes(count, maxLabels);
  })();

  const lastValues = lines.map((line) => line.series.values[lastIndex]);

  const summary = (() => {
    const parts = series.map((s) => {
      const finiteValues = s.values.filter((value): value is number => Number.isFinite(value as number));
      const max = finiteValues.length ? Math.max(...finiteValues) : 0;
      const last = safe(s.values[lastIndex]);
      return `${s.label} 峰值 ${format(max)}、当前 ${format(last)}`;
    });
    return `${label}；共 ${count} 个数据点；${parts.join('；')}`;
  })();

  const pointerIndex = (clientX: number, target: SVGSVGElement): number => {
    const rect = target.getBoundingClientRect();
    if (!rect.width) return 0;
    const px = ((clientX - rect.left) / rect.width) * width;
    return indexFromPointer(px, plotLeft, plotWidth, count);
  };

  return (
    <div ref={ref} data-chart className={cn('w-full', className)}>
      <div className='relative w-full' style={{ height }}>
      <svg
        role='img'
        tabIndex={0}
        aria-label={summary}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio='none'
        className='absolute inset-0 h-full w-full outline-none'
        onPointerMove={(event) => setHover(pointerIndex(event.clientX, event.currentTarget))}
        onPointerLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            const step = event.key === 'ArrowLeft' ? -1 : 1;
            setHover((current) => {
              const base = current ?? lastIndex;
              return Math.min(lastIndex, Math.max(0, base + step));
            });
          } else if (event.key === 'Home') {
            setHover(0);
          } else if (event.key === 'End') {
            setHover(lastIndex);
          } else if (event.key === 'Escape') {
            setHover(null);
          }
        }}
      >
        <defs>
          {lines.map((line) => (
            <linearGradient key={line.series.key} id={`${uid}-${line.series.key}`} x1='0' y1='0' x2='0' y2='1'>
              <stop offset='0%' stopColor={chartColor(line.token)} stopOpacity={0.28} />
              <stop offset='100%' stopColor={chartColor(line.token)} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>

        {/* 网格：比 --border 更淡一档，退到背景里；0 线单独加强一格 */}
        {showAxis
          ? domain.ticks.map((tick) => {
              const tickY = y(tick);
              const isZero = tick === 0;
              return (
                <g key={`grid-${tick}`}>
                  <line
                    x1={plotLeft}
                    x2={plotRight}
                    y1={tickY}
                    y2={tickY}
                    stroke='var(--border)'
                    strokeWidth={isZero ? 1 : 1}
                    opacity={isZero ? 0.9 : 0.45}
                    shapeRendering='crispEdges'
                  />
                  <text
                    x={plotLeft - 8}
                    y={tickY}
                    textAnchor='end'
                    dominantBaseline='middle'
                    fontSize={TICK_FONT}
                    fill='var(--muted-foreground)'
                    className='tabular-nums'
                  >
                    {format(tick)}
                  </text>
                </g>
              );
            })
          : null}

        {area
          ? lines.map((line) => (
              <path
                key={`area-${line.series.key}`}
                d={areaPath(line.points, plotBottom, smooth)}
                fill={`url(#${uid}-${line.series.key})`}
                stroke='none'
                className='chart-area-fill'
              />
            ))
          : null}

        {lines.map((line) => (
          <path
            key={`line-${line.series.key}`}
            d={line.path}
            fill='none'
            stroke={chartColor(line.token)}
            strokeWidth={2}
            strokeLinecap='round'
            strokeLinejoin='round'
            pathLength={1}
            strokeDasharray={1}
            className='chart-draw'
          />
        ))}

        {showAxis
          ? xLabelIndexes.map((index) => {
              const text = labels?.[index];
              // labels 比 values 短时不留空白刻度（宁缺毋滥，也不画空气泡）
              if (!text) return null;
              const anchor = index === 0 ? 'start' : index === lastIndex ? 'end' : 'middle';
              return (
                <text
                  key={`xlabel-${index}`}
                  x={x(index)}
                  y={plotBottom + TICK_FONT + 6}
                  textAnchor={anchor}
                  fontSize={TICK_FONT}
                  fill='var(--muted-foreground)'
                  className='tabular-nums'
                >
                  {text}
                </text>
              );
            })
          : null}

        {/* 末端数值：直接标在线上，省掉"去对刻度"的脑力；描边底色把网格压住 */}
        {lines.map((line) => {
          const last = line.points[lastIndex];
          if (!last) return null;
          const above = last.y - 10 > plotTop + 4;
          const anchor = last.x > plotRight - 24 ? 'end' : 'start';
          const dx = anchor === 'end' ? -8 : 8;
          return (
            <text
              key={`last-${line.series.key}`}
              x={last.x + dx}
              y={above ? last.y - 8 : last.y + 14}
              textAnchor={anchor}
              fontSize={VALUE_FONT}
              fontWeight={600}
              fill='var(--foreground)'
              stroke='var(--background)'
              strokeWidth={3}
              paintOrder='stroke'
              strokeLinejoin='round'
              className='tabular-nums'
            >
              {format(safe(line.series.values[lastIndex]))}
            </text>
          );
        })}

        {lines.map((line) => {
          const last = line.points[lastIndex];
          if (!last) return null;
          return (
            <circle
              key={`endpoint-${line.series.key}`}
              cx={last.x}
              cy={last.y}
              r={3}
              fill={chartColor(line.token)}
              stroke='var(--background)'
              strokeWidth={2}
              className='chart-point'
            />
          );
        })}

        {/* 十字准星：竖线 + 每序列一个高亮点 */}
        {hover !== null ? (
          <g pointerEvents='none'>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={plotTop}
              y2={plotBottom}
              stroke='var(--foreground)'
              strokeWidth={1}
              strokeDasharray='3 3'
              opacity={0.28}
            />
            {lines.map((line) => {
              const value = line.series.values[hover];
              if (!Number.isFinite(value as number)) return null;
              return (
                <circle
                  key={`hoverdot-${line.series.key}`}
                  cx={x(hover)}
                  cy={y(value)}
                  r={4}
                  fill={chartColor(line.token)}
                  stroke='var(--background)'
                  strokeWidth={2}
                />
              );
            })}
          </g>
        ) : null}

        {/* 命中层：整块绘图区（下标由指针 x 现算，比逐列透明竖带稳） */}
        <rect
          data-hit=''
          x={plotLeft}
          y={plotTop}
          width={Math.max(plotWidth, 1)}
          height={Math.max(plotHeight, 1)}
          fill='transparent'
        />
      </svg>

      {hover !== null ? (
        <ChartTooltip xPx={x(hover)} containerWidth={width}>
          <div className='mb-1 font-medium'>{labels?.[hover] ?? `#${hover + 1}`}</div>
          <ul className='flex flex-col gap-1'>
            {lines.map((line) => {
              const raw = line.series.values[hover];
              return (
                <TooltipRow
                  key={line.series.key}
                  label={line.series.label}
                  value={Number.isFinite(raw as number) ? format(raw as number) : '—'}
                  token={line.token}
                />
              );
            })}
          </ul>
        </ChartTooltip>
      ) : null}
      </div>

      {showLegend ? (
        <ChartLegend
          className='mt-2'
          items={lines.map((line, index) => ({
            label: line.series.label,
            token: line.token,
            value: Number.isFinite(lastValues[index] as number) ? format(lastValues[index] as number) : '—',
          }))}
        />
      ) : null}
    </div>
  );
}
