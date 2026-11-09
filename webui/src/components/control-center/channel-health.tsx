import { formatCount, formatMs } from '@/lib/format';
import type { LLMChannelHealth } from '@/lib/control-center';

/** Null is unknown; never turn an unsampled channel into a zero-latency winner. */
export function ChannelHealthView({ health }: { health: LLMChannelHealth }) {
  return <div className='flex flex-col gap-1 fs-caption'>
    <span>{health.state}{health.reason ? ` · ${health.reason}` : ''}</span>
    <span className='tabular-nums text-muted-foreground'>{formatMs(health.ema_ms)} · 样本 {formatCount(health.samples)}</span>
    {health.cooldown_active && <span className='text-tone-warn'>冷却中</span>}
  </div>;
}
