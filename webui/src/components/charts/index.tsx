// 图表组件库总出口。
//
// 🔴 全部组件手写 SVG，**零第三方图表依赖**（不引 recharts / d3-shape / chart.js）。
// 整个目录（9 个组件）实测 19.5 KB gzip（esbuild --minify，React 外置），
// 按页面动态 import 后单页只付自己那几块；recharts 仍走页面级动态 import。
//
// 颜色只经 lib/chart-model 的 chartColor() 取 `var(--chart-N)`，主题切换自动跟随。
// 动效与 reduced-motion 降级由 <ChartStyles /> 注入一次（不碰 index.css，那是 A 席的面）。
import type { ReactNode } from 'react';

export { BarChart, type BarChartProps } from './BarChart';
export { DonutChart, type DonutChartProps, type DonutEntry } from './DonutChart';
export { GaugeArc, type GaugeArcProps } from './GaugeArc';
export { Heatmap, type HeatmapProps } from './Heatmap';
export { LineChart, type LineChartProps, type LineSeries } from './LineChart';
export { ScatterChart, type ScatterChartProps, type ScatterPoint, type ScatterSeries } from './ScatterChart';
export { Sparkline, type SparklineProps } from './Sparkline';
export { ChartEmpty, ChartLegend, ChartTooltip, TooltipRow, clipLabel } from './chart-primitives';

/**
 * 图表动效样式（必须挂一次，通常放 app-shell 顶部或页面根节点）。
 *
 * 为什么用 <style> 而不是 index.css：index.css 属于 A 席，本席写入面禁止碰；
 * 且这几条规则是"组件自带"，放在组件库里才能保证被 import 就生效。
 * 全部只动 stroke-dashoffset / opacity / transform，不动 width/height/top/left。
 */
const CSS = `
@keyframes chart-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes chart-grow-y { from { opacity: 0; transform: scaleY(0); } to { opacity: 1; transform: scaleY(1); } }
@keyframes chart-grow-x { from { opacity: 0; transform: scaleX(0); } to { opacity: 1; transform: scaleX(1); } }
@keyframes chart-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes chart-arc-in { from { opacity: 0; transform: scale(0.96); } to { opacity: 1; transform: scale(1); } }
.chart-draw { animation: chart-draw calc(900ms * var(--mo-dur, 1)) ease-out both; }
.chart-area-fill { animation: chart-fade calc(700ms * var(--mo-dur, 1)) ease-out both; }
.chart-draw-arc { animation: chart-draw calc(700ms * var(--mo-dur, 1)) ease-out both; }
.chart-arc { transform-box: fill-box; transform-origin: center; animation: chart-arc-in calc(520ms * var(--mo-dur, 1)) ease-out both; }
.chart-grow-y { transform-box: fill-box; transform-origin: 50% 100%; animation: chart-grow-y calc(600ms * var(--mo-dur, 1)) cubic-bezier(0.22, 1, 0.36, 1) both; }
.chart-grow-x { transform-box: fill-box; transform-origin: 0% 50%; animation: chart-grow-x calc(600ms * var(--mo-dur, 1)) cubic-bezier(0.22, 1, 0.36, 1) both; }
.chart-point { animation: chart-fade calc(400ms * var(--mo-dur, 1)) ease-out both; }
.chart-cell { animation: chart-fade calc(360ms * var(--mo-dur, 1)) ease-out both; }
@media (prefers-reduced-motion: reduce) {
  .chart-draw, .chart-draw-arc, .chart-arc, .chart-area-fill, .chart-grow-y, .chart-grow-x, .chart-point, .chart-cell {
    animation: none;
    stroke-dashoffset: 0;
    opacity: 1;
    transform: none;
  }
}
`;

/**
 * 幂等注入（模块导入即生效）。
 *
 * 为什么不是"等页面挂 <ChartStyles/>"：实际上全仓没有任何页面挂过它，
 * 于是 chart-draw / chart-grow / reduced-motion 三条规则在真实页面里**从未生效**——
 * 动画不播还能忍，`prefers-reduced-motion` 不生效是可达性问题。
 * 图表样式属于组件自带资产，import 到图表模块就应当生效，不能依赖调用方记得挂。
 */
function ensureChartStyles(): void {
  if (typeof document === 'undefined') return;
  if (document.querySelector('style[data-chart-styles]')) return;
  const element = document.createElement('style');
  element.setAttribute('data-chart-styles', '');
  element.textContent = CSS;
  document.head.appendChild(element);
}

ensureChartStyles();

/**
 * 显式挂载入口（保留给需要把样式放在特定 DOM 位置的宿主）。
 * 模块导入时已经注入过一份，重复挂无害（规则幂等），因此返回 null 不再重复写。
 */
export function ChartStyles(): ReactNode {
  ensureChartStyles();
  return null;
}
