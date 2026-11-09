// 环形 / 饼图（手写 SVG，零依赖）。支持中心数值与多环。
//
// 旧版的两个毛病：环太粗（厚度≈半径的一半，像甜甜圈咬掉中间）、色块之间没有
// 呼吸位。现在：内径占外径 66%，扇区之间留 1.2° 缝，底下垫一圈极淡的轨道——
// 空态和低占比都能看出"这是个环"，而不是一块紫色饼。
import { useState } from 'react';

import { arcPath, chartColor, donutSegments, formatValue, type ChartToken } from '@/lib/chart-model';
import { formatDecimal } from '@/lib/format';
import { cn } from '@/lib/utils';

import { ChartEmpty, ChartLegend, useChartWidth } from './chart-primitives';

export interface DonutEntry {
  label: string;
  value: number;
  /** 覆盖色档；缺省按条目下标取 --chart-N。 */
  token?: ChartToken;
}

export interface DonutChartProps {
  /** 主环（最外层）数据。 */
  entries: readonly DonutEntry[];
  /** 额外内环；从内到外排列，主环永远在最外。 */
  rings?: readonly (readonly DonutEntry[])[];
  /** 中心数值（大号）。 */
  centerValue?: string;
  centerLabel?: string;
  /** 中心第三行（如「共 83 条通道」）。 */
  centerCaption?: string;
  /** 内径 / 外径。0.66 是"甜甜圈"的甜点区；>0.8 变细圈，<0.5 变饼。 */
  innerRatio?: number;
  aspect?: number;
  label: string;
  format?: (value: number) => string;
  showLegend?: boolean;
  /** 空态第二行：为什么没有数据。 */
  emptyHint?: string;
  className?: string;
}

/** 扇区之间留的角缝（弧度）；细扇区减半，免得把小占比切成一条线。 */
const GAP = 0.012;

/**
 * 环形图。
 * · 动画：扇区淡入 + 轻微放大（CSS .chart-arc，reduced-motion 由样式表关掉）
 * · 可访问：role=img + aria-label + 图例（含数值与占比）+ 中心数值即数值标签
 * · 响应式：实测像素 + viewBox，宽度 100%
 */
export function DonutChart({
  entries,
  rings,
  centerValue,
  centerLabel,
  centerCaption,
  innerRatio = 0.76,
  aspect = 1,
  label,
  format = formatValue,
  showLegend = true,
  emptyHint,
  className,
}: DonutChartProps) {
  const [hover, setHover] = useState<string | null>(null);
  const { ref, width } = useChartWidth(360);
  const height = Math.max(160, Math.round(width / Math.max(aspect, 0.4)));

  // 内环在前、主环在后（主环画在最外层半径）。
  const layers = (rings && rings.length > 0 ? [...rings, entries] : [entries]).map((layer) => donutSegments(layer));
  const primary = layers[layers.length - 1] ?? [];

  if (primary.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        <ChartEmpty text='暂无数据' hint={emptyHint ?? '这个窗口还没有采样到通道数据。'} aspect={aspect} />
      </div>
    );
  }

  const cx = width / 2;
  const cy = height / 2;
  const outerEdge = Math.max(24, Math.floor((Math.min(width, height) / 2 - 12) / 4) * 4);
  const safeRatio = Math.min(Math.max(innerRatio, 0.35), 0.86);
  const thickness = outerEdge * (1 - safeRatio);

  /** 第 index 层（0=最外）的半径带；多环向内收，环间留 8px。 */
  const slot = (index: number) => {
    const outer = outerEdge - index * (thickness * 0.72 + 8);
    return { outer: Math.max(outer, 8), inner: Math.max(outer * safeRatio, 4) };
  };

  const primaryHovered = primary.find((seg) => seg.label === hover);

  const ariaEntries = primary.map((seg) => `${seg.label} ${format(seg.value)}（${formatDecimal(seg.share * 100, 1)}%）`);
  const ariaLabel = `${label}：${ariaEntries.join('，')}`;

  return (
    <div ref={ref} data-chart className={cn('w-full', className)}>
      <div
        className='relative w-full'
        style={{ aspectRatio: String(aspect) }}
        onPointerLeave={() => setHover(null)}
      >
      <svg
        role='img'
        aria-label={ariaLabel}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio='xMidYMid meet'
        className='absolute inset-0 h-full w-full'
      >
        {/* 轨道：低占比/空槽也能看出环的存在，比纯白底体面 */}
        <circle
          cx={cx}
          cy={cy}
          r={(slot(0).outer + slot(0).inner) / 2}
          fill='none'
          stroke='var(--border)'
          strokeWidth={Math.max(slot(0).outer - slot(0).inner, 1)}
          opacity={0.35}
        />

        {layers.map((segments, li) => {
          const { inner, outer } = slot(layers.length - 1 - li);
          return segments.map((seg) => {
            const span = seg.endAngle - seg.startAngle;
            const pad = Math.min(GAP, span / 6);
            const arc = arcPath(cx, cy, inner, outer, seg.startAngle + pad, seg.endAngle - pad);
            if (!arc.d) return null;
            const dim = hover !== null && hover !== seg.label;
            return (
              <path
                key={`${li}-${seg.label}`}
                d={arc.d}
                fill={chartColor(seg.token)}
                opacity={dim ? 0.45 : 1}
                className='chart-arc'
                onPointerEnter={() => setHover(seg.label)}
              >
                <title>{`${seg.label}：${format(seg.value)}（${formatDecimal(seg.share * 100, 1)}%）`}</title>
              </path>
            );
          });
        })}

        {/* 中心：默认显示总量；hover 时切成该扇区的读数（不用移开视线去对照图例） */}
        {primaryHovered ? (
          <g pointerEvents='none'>
            <text
              x={cx}
              y={cy - 4}
              textAnchor='middle'
              dominantBaseline='middle'
              fontSize={Math.min(54, Math.max(24, outerEdge * 0.32))}
              fontWeight={600}
              fill='var(--foreground)'
              className='tabular-nums'
            >
              {formatDecimal(primaryHovered.share * 100, 1)}%
            </text>
            <text x={cx} y={cy + 20} textAnchor='middle' dominantBaseline='middle' fontSize={12} fill='var(--muted-foreground)'>
              {primaryHovered.label}
            </text>
            <text x={cx} y={cy + 36} textAnchor='middle' dominantBaseline='middle' fontSize={12} fill='var(--foreground)' className='tabular-nums'>
              {format(primaryHovered.value)}
            </text>
          </g>
        ) : (
          <g pointerEvents='none'>
            {centerValue ? (
              <text
                x={cx}
                y={centerLabel ? cy - 8 : cy}
                textAnchor='middle'
                dominantBaseline='middle'
                fontSize={Math.min(54, Math.max(26, outerEdge * 0.32))}
                fontWeight={600}
                fill='var(--foreground)'
                className='tabular-nums'
              >
                {centerValue}
              </text>
            ) : null}
            {centerLabel ? (
              <text
                x={cx}
                y={centerValue ? cy + 18 : cy}
                textAnchor='middle'
                dominantBaseline='middle'
                fontSize={12}
                fill='var(--muted-foreground)'
              >
                {centerLabel}
              </text>
            ) : null}
            {centerCaption ? (
              <text
                x={cx}
                y={cy + 34}
                textAnchor='middle'
                dominantBaseline='middle'
                fontSize={12}
                fill='var(--muted-foreground)'
              >
                {centerCaption}
              </text>
            ) : null}
          </g>
        )}
      </svg>
      </div>

      {showLegend ? (
        <ChartLegend
          className='mt-2'
          items={primary.map((seg) => ({
            label: seg.label,
            token: seg.token,
            value: `${format(seg.value)} · ${formatDecimal(seg.share * 100, 1)}%`,
          }))}
        />
      ) : null}
    </div>
  );
}
