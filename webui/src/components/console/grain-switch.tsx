// 五档时间粒度切换器（W15 T5）：日 / 周 / 月 / 年 / 累计。
//
// 语义是**分段单选**（`role="radiogroup"` + `role="radio"` + `aria-checked`），不是 tab：
// 五个档共享同一块内容区，切换只是换聚合口径，不换面板。
//
// 键盘按 radiogroup 的通行约定：左右方向键在档间移动并即时生效（`onChange`），
// Tab 键只落进组里当前选中的那一档（未选中档 `tabIndex=-1`）。
import type { KeyboardEvent } from 'react';
import type { RollupGrain } from '@/lib/stat-rollup';
import { cn } from '@/lib/utils';

// 顺序即 `RollupGrain` 类型定义顺序，别自己排。
const GRAINS: ReadonlyArray<readonly [RollupGrain, string]> = [
  ['daily', '日'],
  ['weekly', '周'],
  ['monthly', '月'],
  ['yearly', '年'],
  ['total', '累计'],
];

/** 五档时间粒度切换器（日 / 周 / 月 / 年 / 累计）。 */
export function GrainSwitch({
  value,
  onChange,
  className,
}: {
  value: RollupGrain;
  onChange: (next: RollupGrain) => void;
  className?: string;
}) {
  const index = GRAINS.findIndex(([grain]) => grain === value);

  function step(delta: number) {
    // 找不到当前档时从第一档起算，不做环形回绕（越界即不动）。
    const from = index < 0 ? 0 : index;
    const next = GRAINS[from + delta];
    if (next) onChange(next[0]);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      step(-1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      step(1);
    }
  }

  return (
    <div role='radiogroup' aria-label='时间粒度' className={cn('inline-flex items-center gap-1 rounded-full bg-muted p-1', className)}>
      {GRAINS.map(([grain, text]) => {
        const active = grain === value;
        return (
          <button
            key={grain}
            type='button'
            role='radio'
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(grain)}
            onKeyDown={onKeyDown}
            className={cn(
              'rounded-full px-3 py-1 fs-caption transition-colors',
              active ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}
