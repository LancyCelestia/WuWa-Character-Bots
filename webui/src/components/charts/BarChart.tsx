// 柱状 / 堆叠柱状 / 横向条形图（手写 SVG，零依赖）。
//
// 坐标策略与 LineChart 同：实测容器像素，刻度字恒为 11px。
//
// 四件"高端感"必备（旧版全缺，用户截图里一眼看出穷）：
//   ① 数值直接标在柱上（不让人去对右边的浮游刻度）；
//   ② 分类名给足左留白 + 两行换行 + `<title>` 全名（不再 `bot.conte...` 一刀切）；
//   ③ 网格退到背景、柱子只圆"该圆的那一头"；
//   ④ hover 高亮该分类、压暗其余，并给 tooltip。
import { useMemo, useState } from 'react';

import {
  bandScale,
  barPath,
  chartColor,
  formatValue,
  linearScale,
  measureLabelWidth,
  niceDomain,
  seriesToken,
  stackSeries,
  stackTotals,
  wrapLabel,
  type StackSeries,
} from '@/lib/chart-model';
import { cn } from '@/lib/utils';

import {
  ChartEmpty,
  ChartLegend,
  ChartTooltip,
  MultilineText,
  TICK_FONT,
  TooltipRow,
  VALUE_FONT,
  useChartWidth,
} from './chart-primitives';

const finite = (value: number | null | undefined): number => (Number.isFinite(value as number) ? (value as number) : 0);

/** 柱/条的最大厚度：再宽就不是"数据"而是"色块"了。 */
const MAX_BAR = 56;
const MAX_BAR_H = 20;
const MAX_LABEL_GUTTER = 190;

export interface BarChartProps {
  /** 每个分类一格；categories[i] 的第 j 条对应 series[j]。 */
  categories: readonly string[];
  series: readonly StackSeries[];
  /** 堆叠（默认）/ 分组并排。 */
  stacked?: boolean;
  /** 横向条形：分类在 y 轴、数值在 x 轴（分类名长时更好读）。 */
  horizontal?: boolean;
  /** 分类之间的间隙比例（0–0.9）。 */
  padding?: number;
  /** 绘图区宽/高。 */
  aspect?: number;
  label: string;
  format?: (value: number) => string;
  showLegend?: boolean;
  showAxis?: boolean;
  /** 柱上数值标注（默认开）。 */
  valueLabels?: boolean;
  /** 空态第二行：为什么没有数据。 */
  emptyHint?: string;
  className?: string;
}

/**
 * 柱状 / 堆叠柱状 / 横向条形。
 * · 动画：柱从基线长出来（CSS transform: scaleY/scaleX，只动 transform）
 * · 可访问：role=img（摘要含峰值分类）+ 图例 + 柱上数值 + tooltip + `<title>` 全名
 * · 响应式：viewBox + w-full，高度由 aspect 撑开
 */
export function BarChart({
  categories,
  series,
  stacked = true,
  horizontal = false,
  padding = 0.42,
  aspect = 2.4,
  label,
  format = formatValue,
  showLegend = true,
  showAxis = true,
  valueLabels = true,
  emptyHint,
  className,
}: BarChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const { ref, width } = useChartWidth(560);

  const columns = useMemo(() => stackSeries(series), [series]);
  const columnTotals = useMemo(() => stackTotals(series), [series]);
  // 每列的"代表值"：堆叠=合计，分组=该列最高的一根。数值标注与摘要都用它。
  const magnitude = stacked
    ? columnTotals
    : categories.map((_category, ci) => Math.max(0, ...series.map((s) => finite(s.values[ci]))));
  const maxValue = Math.max(0, ...magnitude);
  const peakIndex = magnitude.indexOf(maxValue);
  const domain = useMemo(() => niceDomain(maxValue, 4), [maxValue]);
  const tickWidth = Math.max(...domain.ticks.map((tick) => measureLabelWidth(format(tick), TICK_FONT)), TICK_FONT);

  const legend = series.map((s, si) => ({
    label: s.label,
    token: s.token ?? seriesToken(si),
    total: s.values.reduce<number>((sum, v) => sum + finite(v), 0),
  }));

  // 窄屏自动改横向：5 个长模型名塞进 340px 竖向柱，物理上不可能两行读完。
  // 横向条形把分类名放左侧、给足两行宽度，是唯一不靠省略号还能读全的排法。
  const approxStep = (width - 64) / Math.max(categories.length, 1);
  const longestLabel = Math.max(0, ...categories.map((category) => measureLabelWidth(category, TICK_FONT)));
  const useHorizontal =
    horizontal || (width < 480 && longestLabel > approxStep * 1.6 && categories.length <= 12);

  if (categories.length === 0 || series.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        <ChartEmpty text='暂无数据' hint={emptyHint ?? '窗口内没有可归属的记录。'} aspect={aspect} />
      </div>
    );
  }

  const summary = `${label}；${categories.length} 个分类；最高 ${format(maxValue)}${
    categories[peakIndex] ? `（${categories[peakIndex]}）` : ''
  }`;

  const tooltipFor = (index: number) => {
    // 堆叠看各段，分组看各序列——两种模式的"这一格是什么"不是同一件事。
    const rows = stacked
      ? (columns[index] ?? []).filter((seg) => seg.value > 0)
      : series.map((s, si) => ({
          key: s.key,
          label: s.label,
          token: s.token ?? seriesToken(si),
          value: finite(s.values[index]),
        }));
    return (
      <>
        <div className='mb-1 max-w-3/4 font-medium'>{categories[index]}</div>
        <ul className='flex flex-col gap-1'>
          {rows.map((seg) => (
            <TooltipRow key={seg.key} label={seg.label} value={format(seg.value)} token={seg.token} />
          ))}
          {stacked && rows.length > 1 ? (
            <li className='flex items-center gap-2 border-t pt-1 text-muted-foreground'>
              <span>合计</span>
              <span className='ml-auto font-medium text-foreground tabular-nums'>{format(columnTotals[index])}</span>
            </li>
          ) : null}
        </ul>
      </>
    );
  };

  // ── 横向条形 ───────────────────────────────────────────────────────────────
  if (useHorizontal) {
    const maxLabelWidth = Math.max(0, ...categories.map((c) => measureLabelWidth(c, TICK_FONT)));
    // 行高下限 32px：两行分类名（11px×1.2×2≈27px）加呼吸位，多行时画布跟着长高。
    const height = Math.max(
      Math.round(width / Math.max(aspect, 0.5)),
      16 + categories.length * 32
    );
    const labelGutter = Math.ceil(Math.min(Math.max(maxLabelWidth + 12, 56), Math.min(MAX_LABEL_GUTTER, width * 0.42)) / 4) * 4;
    const marginTop = 8;
    const marginBottom = showAxis ? 24 : 8;
    const marginRight = 52;
    const plotLeft = labelGutter;
    const plotRight = Math.max(plotLeft + 12, width - marginRight);
    const plotTop = marginTop;
    const plotBottom = Math.max(plotTop + 12, height - marginBottom);
    const plotWidth = plotRight - plotLeft;
    const plotHeight = plotBottom - plotTop;

    const catScale = bandScale(categories, [0, plotHeight], 0.48);
    const valueScale = linearScale({ min: 0, max: domain.max }, [0, plotWidth]);
    const barHeight = Math.max(6, Math.min(catScale.bandwidth, MAX_BAR_H));
    const labelWidth = labelGutter - 12;

    const wrapped = categories.map((category) => wrapLabel(category, labelWidth, TICK_FONT, 2));
    const barRows = categories.map((category, ci) => {
      const segments = stacked ? columns[ci] ?? [] : series.map((s, si) => ({
        key: s.key,
        label: s.label,
        token: s.token ?? seriesToken(si),
        start: 0,
        end: finite(s.values[ci]),
        value: finite(s.values[ci]),
      }));
      const top = plotTop + catScale.at(ci) + (catScale.bandwidth - (stacked ? barHeight : barHeight * Math.min(series.length, 3))) / 2;
      return { category, ci, segments, top };
    });

    const tickIndexes = domain.ticks;

    return (
      <div ref={ref} data-chart className={cn('w-full', className)}>
        <div className='relative w-full' style={{ height }}>
        <svg
          role='img'
          aria-label={summary}
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio='none'
          className='absolute inset-0 h-full w-full'
          onPointerLeave={() => setHover(null)}
        >
          {/* 竖向网格 + 数值刻度（刻度在底部，柱子右边留白给数值标注） */}
          {showAxis
            ? tickIndexes.map((tick) => {
                const px = plotLeft + valueScale(tick);
                const isZero = tick === 0;
                return (
                  <g key={`tick-${tick}`}>
                    <line
                      x1={px}
                      x2={px}
                      y1={plotTop}
                      y2={plotBottom}
                      stroke='var(--border)'
                      strokeWidth={1}
                      opacity={isZero ? 0.9 : 0.45}
                      shapeRendering='crispEdges'
                    />
                    <text
                      x={px}
                      y={plotBottom + TICK_FONT + 5}
                      textAnchor={tick === 0 ? 'start' : 'middle'}
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

          {barRows.map((row) => {
            const dim = hover !== null && hover !== row.ci;
            return (
              <g key={`row-${row.ci}`} opacity={dim ? 0.55 : 1}>
                {row.segments.map((seg, si) => {
                  if (!(seg.value > 0)) return null;
                  const startX = plotLeft + valueScale(seg.start);
                  const endX = plotLeft + valueScale(seg.end);
                  const w = Math.max(endX - startX, 1);
                  const y = row.top + (stacked ? 0 : si * (barHeight + 3));
                  return (
                    <path
                      key={`bar-${row.ci}-${seg.key}`}
                      d={barPath(startX, y, w, barHeight, 4, 'right')}
                      fill={chartColor(seg.token)}
                      className='chart-grow-x'
                    />
                  );
                })}
                {valueLabels && (stacked || series.length === 1) && magnitude[row.ci] > 0 ? (
                  <text
                    x={plotLeft + valueScale(magnitude[row.ci]) + 6}
                    y={row.top + barHeight / 2}
                    dominantBaseline='middle'
                    fontSize={VALUE_FONT}
                    fontWeight={600}
                    fill='var(--foreground)'
                    className='tabular-nums'
                  >
                    {format(magnitude[row.ci])}
                  </text>
                ) : null}
                {/* 分组多序列：数值标在各自条尾（标"合计"会读成该序列的值，是假账） */}
                {valueLabels && !stacked && series.length > 1
                  ? row.segments.map((seg, si) =>
                      seg.value > 0 ? (
                        <text
                          key={`v-${row.ci}-${seg.key}`}
                          x={plotLeft + valueScale(seg.end) + 6}
                          y={row.top + si * (barHeight + 3) + barHeight / 2}
                          dominantBaseline='middle'
                          fontSize={VALUE_FONT}
                          fontWeight={600}
                          fill='var(--foreground)'
                          className='tabular-nums'
                        >
                          {format(seg.value)}
                        </text>
                      ) : null
                    )
                  : null}
              </g>
            );
          })}

          {/* 分类名：两行换行 + 全名进 <title>，可视部分保留可辨识前缀 */}
          {wrapped.map((entry, ci) => (
            <MultilineText
              key={`label-${ci}`}
              lines={entry.lines}
              x={labelGutter - 10}
              y={plotTop + catScale.at(ci) + catScale.bandwidth / 2}
              fontPx={TICK_FONT}
              anchor='end'
            />
          ))}

          {/* 命中层：整行（比逐条命中更宽容，指针扫过空白也出 tooltip） */}
          {categories.map((category, ci) => (
            <rect
              key={`hit-${ci}`}
              data-hit=''
              x={0}
              y={plotTop + catScale.at(ci)}
              width={width}
              height={Math.max(catScale.bandwidth, 4)}
              fill='transparent'
              onPointerEnter={() => setHover(ci)}
            >
              <title>{category}</title>
            </rect>
          ))}
        </svg>

        {hover !== null ? (
          <ChartTooltip xPx={plotLeft + plotWidth * 0.5} containerWidth={width}>
            {tooltipFor(hover)}
          </ChartTooltip>
        ) : null}
        </div>

        {showLegend ? (
          <ChartLegend
            className='mt-2'
            items={legend.map((item) => ({ label: item.label, token: item.token, value: format(item.total) }))}
          />
        ) : null}
      </div>
    );
  }

  // ── 竖向柱 ────────────────────────────────────────────────────────────────
  const marginTop = 24;
  const marginRight = 12;
  const marginLeft = showAxis ? Math.ceil((tickWidth + 8) / 4) * 4 : 8;
  const plotLeft = marginLeft;
  const plotRight = Math.max(plotLeft + 12, width - marginRight);
  const plotWidth = plotRight - plotLeft;

  const catScale = bandScale(categories, [0, plotWidth], padding);
  const barWidth = Math.max(6, Math.min(catScale.bandwidth, MAX_BAR));
  // 窄柱给三行：宁可竖着写完整，也不出现 `flash-previ…`（用户点名的丑）。
  const labelMaxLines = catScale.step >= 120 ? 2 : 3;
  const wrapped = categories.map((category) => wrapLabel(category, Math.max(catScale.step - 8, 44), TICK_FONT, labelMaxLines));
  const labelLines = Math.max(1, ...wrapped.map((entry) => entry.lines.length));
  const marginBottom = Math.ceil((labelLines * TICK_FONT * 1.2 + 8) / 4) * 4;
  // 高度取"比例给的高度"和"标签装得下"的较大者：矮画布不会把两行分类名压进柱子里。
  const height = Math.max(Math.round(width / Math.max(aspect, 0.5)), 130 + Math.round(marginBottom));
  const plotTop = marginTop;
  const plotBottom = Math.max(plotTop + 12, height - marginBottom);
  const plotHeight = plotBottom - plotTop;
  const valueScale = linearScale({ min: 0, max: domain.max }, [0, plotHeight]);

  return (
    <div ref={ref} data-chart className={cn('w-full', className)}>
      <div className='relative w-full' style={{ height }}>
      <svg
        role='img'
        aria-label={summary}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio='none'
        className='absolute inset-0 h-full w-full'
        onPointerLeave={() => setHover(null)}
      >
        {showAxis
          ? domain.ticks.map((tick) => {
              const py = plotBottom - valueScale(tick);
              const isZero = tick === 0;
              return (
                <g key={`tick-${tick}`}>
                  <line
                    x1={plotLeft}
                    x2={plotRight}
                    y1={py}
                    y2={py}
                    stroke='var(--border)'
                    strokeWidth={1}
                    opacity={isZero ? 0.9 : 0.45}
                    shapeRendering='crispEdges'
                  />
                  <text
                    x={plotLeft - 8}
                    y={py}
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

        {categories.map((category, ci) => {
          const dim = hover !== null && hover !== ci;
          const segments = stacked
            ? columns[ci] ?? []
            : series.map((s, si) => ({
                key: s.key,
                label: s.label,
                token: s.token ?? seriesToken(si),
                start: 0,
                end: finite(s.values[ci]),
                value: finite(s.values[ci]),
              }));
          const groupWidth = stacked ? barWidth : barWidth / Math.max(series.length, 1);
          const left = plotLeft + catScale.at(ci) + (catScale.bandwidth - barWidth) / 2;
          const columnValue = magnitude[ci];
          const topY = plotBottom - valueScale(columnValue);
          const labelInside = topY - plotTop < 18;
          return (
            <g key={`col-${ci}`} opacity={dim ? 0.55 : 1}>
              {segments.map((seg, si) => {
                if (!(seg.value > 0)) return null;
                const segTop = plotBottom - valueScale(seg.end);
                const segBottom = plotBottom - valueScale(seg.start);
                const h = Math.max(segBottom - segTop, 1);
                const x = stacked ? left : left + si * groupWidth + 1;
                const w = Math.max(groupWidth - (stacked ? 0 : 2), 1);
                const isTop = stacked ? seg.end >= columnValue - 1e-9 : true;
                return (
                  <path
                    key={`seg-${ci}-${seg.key}`}
                    d={barPath(x, segTop, w, h, isTop ? 4 : 0, isTop ? 'top' : 'none')}
                    fill={chartColor(seg.token)}
                    className='chart-grow-y'
                  />
                );
              })}
              {valueLabels && (stacked || series.length === 1) && columnValue > 0 ? (
                <text
                  x={left + barWidth / 2}
                  y={labelInside ? topY + 16 : topY - 7}
                  textAnchor='middle'
                  fontSize={VALUE_FONT}
                  fontWeight={600}
                  fill={labelInside ? 'var(--background)' : 'var(--foreground)'}
                  stroke={labelInside ? 'none' : 'var(--background)'}
                  strokeWidth={labelInside ? 0 : 3}
                  paintOrder='stroke'
                  strokeLinejoin='round'
                  className='tabular-nums'
                >
                  {format(columnValue)}
                </text>
              ) : null}
              {/* 分组多序列：每根柱各自标值（顶上一根"合计"会把序列值冒充成合计） */}
              {valueLabels && !stacked && series.length > 1
                ? series.map((s, si) => {
                    const value = finite(s.values[ci]);
                    if (!(value > 0)) return null;
                    const segTop = plotBottom - valueScale(value);
                    return (
                      <text
                        key={`grp-${ci}-${s.key}`}
                        x={left + si * groupWidth + groupWidth / 2}
                        y={segTop - 6}
                        textAnchor='middle'
                        fontSize={VALUE_FONT}
                        fontWeight={600}
                        fill='var(--foreground)'
                        stroke='var(--background)'
                        strokeWidth={3}
                        paintOrder='stroke'
                        strokeLinejoin='round'
                        className='tabular-nums'
                      >
                        {format(value)}
                      </text>
                    );
                  })
                : null}
              <rect
                data-hit=''
                x={plotLeft + catScale.at(ci)}
                y={plotTop}
                width={Math.max(catScale.bandwidth, 4)}
                height={Math.max(plotHeight, 1)}
                fill='transparent'
                onPointerEnter={() => setHover(ci)}
              >
                <title>{category}</title>
              </rect>
            </g>
          );
        })}

        {wrapped.map((entry, ci) => (
          <MultilineText
            key={`xlabel-${ci}`}
            lines={entry.lines}
            x={plotLeft + catScale.at(ci) + catScale.bandwidth / 2}
            y={plotBottom + 10 + (labelLines * TICK_FONT * 1.2) / 2}
            fontPx={TICK_FONT}
            anchor='middle'
          />
        ))}
      </svg>

      {hover !== null ? (
        <ChartTooltip xPx={plotLeft + catScale.at(hover) + catScale.bandwidth / 2} containerWidth={width}>
          {tooltipFor(hover)}
        </ChartTooltip>
      ) : null}
      </div>

      {showLegend ? (
        <ChartLegend
          className='mt-2'
          items={legend.map((item) => ({ label: item.label, token: item.token, value: format(item.total) }))}
        />
      ) : null}
    </div>
  );
}
