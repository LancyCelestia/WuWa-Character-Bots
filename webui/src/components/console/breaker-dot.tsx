// 通道三态点（W15 T5）：小圆点 + 中文状态文字。
//
// 「只有异常态呼吸」是硬要求——只有 open / half-open 挂 `console-pulse`。
// 满屏跳动的点是噪音不是信息；正常通道和「读不出来的状态」一律静止
// （与 `panel.tsx` 里 `StatusDot` 的同款裁定保持一致：warn/bad 才呼吸）。
import { breakerStateOf, statusLabel, type BreakerState } from '@/lib/domain-labels';
import { cn } from '@/lib/utils';

/**
 * 【借用语义，别当成已有三态】
 *
 * 把 `temporarily_unavailable` 读作 open / half-open 是**借用语义**——后端当前只有两态
 * （`ok` / `temporarily_unavailable`）且由业务失败驱动，**三态状态机尚未建成**。
 * 「冷却中＝等效熔断、冷却期满＝放行探测」是对现有两态的如实近似，不是假装后端已经有三态。
 * 这些判定全部在 `domain-labels.ts` 的 `breakerStateOf` 里（被 34 条测试锁死），
 * 本文件只负责把结果画出来，不再自带一份映射。
 */
const DOT: Record<BreakerState, string> = {
  closed: 'bg-tone-good',
  open: 'bg-tone-bad',
  'half-open': 'bg-tone-warn',
  unknown: 'bg-muted-foreground',
};

const TEXT: Record<BreakerState, string> = {
  closed: 'text-tone-good',
  open: 'text-tone-bad',
  'half-open': 'text-tone-warn',
  unknown: 'text-muted-foreground',
};

/** 只有异常态呼吸（正常/未知静止）。 */
const PULSING: Record<BreakerState, boolean> = {
  closed: false,
  open: true,
  'half-open': true,
  unknown: false,
};

/** 通道三态点：小圆点 + 中文状态文字。 */
export function BreakerDot({
  state,
  cooldownUntil,
  withLabel = true,
  className,
}: {
  /** `channel_health.state` 原值。 */
  state: string | null | undefined;
  /** `channel_health.cooldown_until`，ISO 串。 */
  cooldownUntil?: string | null;
  /** 是否显示文字（默认 true）。 */
  withLabel?: boolean;
  className?: string;
}) {
  const breaker = breakerStateOf(state, cooldownUntil);
  const text = statusLabel(state);

  // 圆点的无障碍名恒等于状态文字：`withLabel=false` 时文字退了场，但圆点自己仍可被读屏念出来。
  const dot = (
    <span
      role='img'
      aria-label={text}
      title={withLabel ? undefined : text}
      className={cn('size-2 shrink-0 rounded-full', DOT[breaker], PULSING[breaker] && 'console-pulse')}
    />
  );

  if (withLabel === false) return <span className={cn('inline-flex items-center', className)}>{dot}</span>;

  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      {dot}
      <span className={cn('fs-caption', TEXT[breaker])}>{text}</span>
    </span>
  );
}
