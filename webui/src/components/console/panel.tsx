// 控制台总台的可复用件（W12 W2-UI）：状态点 / 真开关 / 折叠块 / 数值过渡。
//
// 三条硬约束（用户裁定「面板不能乱堆砌文字」）在这里兑现，页面只负责拼数据：
//   ① 每块默认折叠成**一行**摘要（标题 + 一句 ≤24 字的现状），点开才展开细节；
//   ② 开关是真 `role="switch"` + `aria-checked`（不是 checkbox 裸摆）；
//   ③ 四类动效各写在一处，全部在 `prefers-reduced-motion: reduce` 下退化为无动画
//      （退化规则在 `index.css` 的 `console-*` 段，不散在组件里）。
//
// 版式只走既有尺子：字号五档 fs-*、间距 4px 栅格、语义色 / tone-*，无第三方组件。
import { useId, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import type { ConsoleTone } from '@/lib/console';
import { cn } from '@/lib/utils';

const TONE_TEXT: Record<ConsoleTone, string> = {
  good: 'text-tone-good',
  warn: 'text-tone-warn',
  bad: 'text-tone-bad',
  flat: 'text-muted-foreground',
};

const TONE_DOT: Record<ConsoleTone, string> = {
  good: 'bg-tone-good',
  warn: 'bg-tone-warn',
  bad: 'bg-tone-bad',
  flat: 'bg-muted-foreground',
};

/**
 * 状态点：**只有异常态呼吸**（warn/bad 才挂 `console-pulse`），正常/不可判静止——
 * 满屏跳动的点是噪音，不是信息。
 */
export function StatusDot({ tone }: { tone: ConsoleTone }) {
  const pulsing = tone === 'bad' || tone === 'warn';
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2 shrink-0 rounded-full', TONE_DOT[tone], pulsing && 'console-pulse')}
    />
  );
}

/** 数值/文案变化时重挂一次 → `console-flash` 动画重播（无定时器、无 JS 插值）。
 *  `block truncate`：让摘要能在 flex 行里被压成单行（父级已给 min-w-0 flex-1 + title）。 */
export function ValueFlash({ text, tone }: { text: string; tone: ConsoleTone }) {
  return (
    <span key={text} className={cn('console-flash block truncate tabular-nums fs-body', TONE_TEXT[tone])}>
      {text}
    </span>
  );
}

/**
 * 真开关：`role="switch"` + `aria-checked`，视觉上是滑块轨道 + 圆钮（位移走 CSS transition）。
 * 不引第三方组件（Radix switch 未安装，也不为此装包）。
 */
export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type='button'
      role='switch'
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'inline-flex items-center gap-2 rounded-md border px-3 py-1 fs-caption transition-colors',
        checked ? 'bg-primary/15 text-foreground' : 'text-muted-foreground'
      )}
    >
      <span
        aria-hidden
        className={cn(
          'inline-flex h-4 w-8 shrink-0 items-center rounded-full px-1 transition-colors',
          checked ? 'bg-primary' : 'bg-muted'
        )}
      >
        <span
          aria-hidden
          className={cn(
            'inline-block size-2 rounded-full bg-card transition-transform duration-200 motion-reduce:transition-none',
            checked ? 'translate-x-4' : 'translate-x-0'
          )}
        />
      </span>
      {label}
    </button>
  );
}

/** 键值行（展开区用）：label 左 / value 右，行底分隔线。 */
export function KvRow({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className='flex min-w-0 items-center gap-3 border-b py-2 last:border-b-0'>
      <span title={hint} className='min-w-0 flex-1 truncate fs-caption text-muted-foreground'>
        {label}
      </span>
      <span className='shrink-0 text-right fs-body tabular-nums'>{value}</span>
    </div>
  );
}

/**
 * 折叠块：**一行摘要恒在**，细节挂在高 0fr → 1fr 的 grid 过渡里。
 * 收起时 `inert` + `aria-hidden`：不可见也不进 Tab 序（不发散焦点）。
 *
 * 视觉层：左侧一条 2px 状态色竖条（`tone-edge-*`），比「一个小圆点」在缩略图里也能
 * 一眼看出哪块异常；单块自身用 `surface` 材质，与卡片同一套语言。
 */
export function ConsoleBlock({
  title,
  summary,
  tone,
  detail,
  defaultOpen = false,
  forceOpen,
}: {
  title: string;
  summary: string;
  tone: ConsoleTone;
  detail: ReactNode;
  defaultOpen?: boolean;
  /** 全局「全部展开」开关：给定即覆盖本地开合（只覆盖显示，不改本地状态）。 */
  forceOpen?: boolean;
}) {
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const open = forceOpen ?? localOpen;
  const bodyId = `console-block-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  return (
    <section className={cn('surface relative overflow-hidden rounded-lg transition-shadow duration-300', open && 'shadow-md')}>
      <div
        aria-hidden
        className={cn(
          'absolute inset-y-0 left-0 w-1',
          tone === 'bad' ? 'bg-tone-bad' : tone === 'warn' ? 'bg-tone-warn' : tone === 'good' ? 'bg-tone-good' : 'bg-muted-foreground/40'
        )}
      />
      <div className='flex min-w-0 items-center gap-3 py-3 pl-4 pr-2'>
        <StatusDot tone={tone} />
        <h2 className='shrink-0 fs-card'>{title}</h2>
        {/* 摘要恒一行：`min-w-0 flex-1 truncate` + title 挂全文。不让它换行撑高块高
            （双列下邻块会被拉齐，空档肉眼可见），也不裁掉信息——悬停仍可读全句。 */}
        <span className='min-w-0 flex-1' title={summary}>
          <ValueFlash text={summary} tone={tone} />
        </span>
        <button
          type='button'
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setLocalOpen((value) => !value)}
          className='ml-auto inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 fs-caption text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground'
        >
          <span aria-hidden className='hidden sm:inline'>
            {open ? '收起' : '展开'}
          </span>
          <ChevronDown aria-hidden className={cn('size-4 transition-transform duration-300 motion-reduce:transition-none', open && 'rotate-180')} />
        </button>
      </div>
      <div
        className={cn(
          'grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none',
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        )}
      >
        <div className='overflow-hidden' aria-hidden={!open} inert={!open}>
          <div id={bodyId} className='border-t border-hairline py-3 pl-4 pr-3'>
            {detail}
          </div>
        </div>
      </div>
    </section>
  );
}
