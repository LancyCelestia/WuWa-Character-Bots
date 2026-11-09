// 429 限速（rate limited）的措辞与 Retry-After 解析——**纯函数**，可被 `node --test` 直跑。
//
// 为什么单独一份：429 在旧实现里是「加载失败」的一个变种（`phase: 'error'`），于是
// 用户看到的是红色三角 +「加载失败」——但事实上什么也没坏：后端只是说「你问得太快了，
// 等一会儿」。把「被限速」说成「失败」，会让人去重试（正好是唯一有害的动作）。
//
// 实测机制（用户亲跑，可复跑）：无令牌连发 7 次 /api/v1/stats/calls → 前 5 次 401、
// 第 6 次起 429，等 70 秒才恢复。`control_plane/auth.py` 的失败计数按来源累计，
// **重试一次就多记一笔失败**，所以 429 之后每重试一次都把锁定窗口往后推。
//
// 后端的 429 响应带 `Retry-After`（_app.py 三处 dependency 都写了），读它就不必猜；
// 读不到（旧控制面/被代理吞头）就给 60 秒——与 `FAILURE_WINDOW_SECONDS = 60.0` 同量级。

import type { Translate } from '@/lib/labels';

/** 读不到 Retry-After 时的缺省等待秒数（＝auth.py 的失败窗口长度）。 */
export const DEFAULT_RETRY_AFTER_SECONDS = 60;

/**
 * `Retry-After` 头 → 秒数。
 *
 * 只接受**正整数秒**（RFC 9110 允许的两种形态之一；HTTP-date 形态本控制面从不发，
 * 遇到就当读不到）。脏值/0/负数一律返回 undefined：宁可回落到 60 秒缺省，
 * 也不把 `NaN` 或 `0` 渲染成「请等 0 秒」。
 */
export function parseRetryAfter(raw: string | null | undefined): number | undefined {
  if (typeof raw !== 'string') return undefined;
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) return undefined;
  const seconds = Number.parseInt(trimmed, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined;
}

/** 实际要展示的等待秒数：后端说了就听后端，没说/说脏了给 60。 */
export function retryAfterSeconds(raw: string | null | undefined): number {
  return parseRetryAfter(raw) ?? DEFAULT_RETRY_AFTER_SECONDS;
}

/** 429 卡片的两段文案（标题 + 说人话的提示，提示里带真实秒数）。 */
export interface RateLimitCopy {
  title: string;
  hint: string;
}

/**
 * 429 → 人话。**绝不出现「加载失败」**：这四个字会把「等一下就好」误报成系统故障，
 * 而故障的直觉反应就是重试——正好延长锁定。
 *
 * 占位符 `{{seconds}}` 在这里就地替换（不依赖 i18next 的 interpolation），
 * 因为 `Translate` 是单参类型，把插值塞进它会让所有调用方跟着改。
 */
export function describeRateLimit(t: Translate, seconds: number): RateLimitCopy {
  const safe = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : DEFAULT_RETRY_AFTER_SECONDS;
  return {
    title: t('state.rateLimited'),
    hint: t('state.rateLimitedHint').replaceAll('{{seconds}}', String(safe)),
  };
}
