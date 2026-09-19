// 展示格式化小工具（纯函数，无副作用）。
import type { BucketCode } from '@/lib/labels';

/**
 * 未知值符号（全库唯一真值，一枚 U+2014 长横）。
 *
 * 语义：**这个值不可知**（后端没上报、字段缺省、时间为 null）——与「查过了、结果为空」
 * （`state.noData`「暂无数据」）是两件事，绝互相顶替（F23 §一.3 事故原型：calls 页把空
 * 列表渲染成本符号）。下方各 format* 在值缺失时一律返回它，页面**不得再写字面量**——
 * 收口前同一个符号在 11 处各写各的，改一处漏十处。
 */
export const UNKNOWN_VALUE = '—';

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNKNOWN_VALUE;
  return value.toLocaleString('zh-CN');
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return UNKNOWN_VALUE;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}s`;
  return `${Math.round(value)}ms`;
}

export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return UNKNOWN_VALUE;
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}天${hours}小时`;
  if (hours > 0) return `${hours}小时${minutes}分`;
  return `${minutes}分${total % 60}秒`;
}

/** ISO → 本地展示；空值返回 UNKNOWN_VALUE，畸形文本原样透出不猜。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso; // 畸形文本原样透出，不猜。
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

/** 趋势桶起点 → 坐标轴短标签。 */
export function formatBucket(bucketStart: string, bucket: BucketCode): string {
  const date = new Date(bucketStart);
  if (Number.isNaN(date.getTime())) return bucketStart;
  if (bucket === 'day') {
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  }
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function compactNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString('zh-CN');
}
