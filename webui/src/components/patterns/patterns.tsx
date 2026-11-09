// 版式宪法可复用组件（2026-09-18 用户裁定③）：
// StatCard / PageHeader / SectionCard / DataGrid / CategoryChip / Pager。
// 后继「知识库/插件/记忆图谱」三页由这些组件拼装——改这里即全站生效。
// 字号只用五档阶梯（fs-*），间距只用 4px 栅格 {4,8,12,16,24}，色只用语义 token。
import type { ReactNode } from 'react';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useReveal } from '@/lib/effects/use-reveal';
import { cn } from '@/lib/utils';

/** 统计卡：图标 + 标签 + 数字大字（+ 脚注）。总览/后续页的指标卡唯一形态。
 *
 * 视觉层：数字不再裸摆在卡片里，而是「图标徽 + 标签」在上、`fs-num` 压在下，
 * 脚注贴底。图标给一个圆形 tone 底（继承调用方传进来的 text-tone-* 色），
 * 让六张卡在缩略时也能靠颜色一秒分栏。 */
export function StatCard({
  icon,
  label,
  value,
  sub,
  action,
  children,
}: {
  icon?: ReactNode;
  label: string;
  value?: string;
  sub?: string;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <SectionCard title={label} action={action} titleClass='text-muted-foreground'>
      {value !== undefined ? (
        <div className='flex flex-col gap-1'>
          <div className='flex items-end gap-2'>
            {icon && (
              <span
                aria-hidden
                className='mb-1 flex size-10 shrink-0 items-center justify-center rounded-full bg-muted/60 ring-1 ring-hairline [&_svg]:size-4'
              >
                {icon}
              </span>
            )}
            {/* 文字辉光已按用户裁定整族撤除（index.css「辉光」段），对应的 utility 也随之
                删除 —— 类名留在这里不会报错，只会让人以为有辉光。 */}
            <span className='fs-num num-iris'>{value}</span>
          </div>
          {sub && <p className='fs-caption text-muted-foreground'>{sub}</p>}
        </div>
      ) : null}
      {children}
    </SectionCard>
  );
}

/** 页头：页面标题（fs-page）+ 副题（fs-caption）+ 右侧动作区。
 *  视觉层：标题前加一枚 2px 品牌色竖条，左侧锚定视线——所有页面共用同一种「页首招牌」；
 *  UI2 在标题下压一道 conic 虹彩釉线（iridescent-line，全站炫彩只用两处，这是其一）。 */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  // 标题遮罩揭示（W17，参考站 daniya.top `.hero__mask > span`）：
  //   文字从下方 114% 处「揭开」而不是淡入——淡入看不出层次，遮罩上推才有。
  //   外层 overflow:hidden 裁掉露头；两行（标题/副题）错峰 0.12s，与参考站一致。
  //   🔴 三态由 useReveal 打：已在视口内直接 in（首屏不闪），DOM 没 JS 时是 idle=可见。
  const titleMask = useReveal<HTMLDivElement>(true);
  const subMask = useReveal<HTMLParagraphElement>(true);
  return (
    // glaze-band：页首背后一道极淡的釉瑚光带（UI3「关键位置都要有釉」），标题本身压
    // iridescent-line（虹彩釉线）。两者都只动 opacity/transform，reduced-motion 下静止。
    <div className='glaze-band flex flex-wrap items-end justify-between gap-4'>
      <div className='flex min-w-0 flex-col gap-1'>
        <div className='flex items-center gap-3'>
          <span aria-hidden className='h-6 w-1 shrink-0 rounded-full bg-primary' />
          <h1 className='iridescent-line title-mask truncate fs-page pb-1' data-reveal-state={titleMask.state} ref={titleMask.ref}>
            <span>{title}</span>
          </h1>
        </div>
        {subtitle && (
          <p className='title-mask fs-caption text-muted-foreground' data-reveal-state={subMask.state} ref={subMask.ref}>
            <span>{subtitle}</span>
          </p>
        )}
      </div>
      {actions && <div className='flex flex-wrap items-center gap-2'>{actions}</div>}
    </div>
  );
}

/** 区块卡：标题（fs-card）+ 描述（fs-caption）+ 动作角 + 内容，全站卡片唯一外壳。 */
export function SectionCard({
  title,
  description,
  action,
  children,
  contentClass,
  titleClass,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  contentClass?: string;
  titleClass?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className={cn('fs-card', titleClass)}>{title}</CardTitle>
        {description && <CardDescription className='fs-caption'>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className={contentClass}>{children}</CardContent>
    </Card>
  );
}

/** 数据网格：行高与分隔线全站一致（min-h-12 + py-3 + 分隔线）；单元格 flex 对齐。 */
export function DataGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-col', className)}>{children}</div>;
}

export function DataGridRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 items-center gap-3 border-b py-3 last:border-b-0', className)}>{children}</div>
  );
}

export function DataGridCell({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('min-w-0 truncate', className)}>{children}</div>;
}

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'purple' | 'magenta' | 'brand' | 'flat';

const TONE_TEXT: Record<Tone, string> = {
  good: 'text-tone-good tone-face-good',
  warn: 'text-tone-warn tone-face-warn',
  bad: 'text-tone-bad tone-face-bad',
  info: 'text-tone-info tone-face-info',
  purple: 'text-tone-purple tone-face-purple',
  magenta: 'text-tone-magenta tone-face-magenta',
  brand: 'text-primary bg-primary/15',
  flat: 'text-muted-foreground tone-face-flat',
};

/** 类别章：语义 tone 色小胶囊（日志级别/渠道状态/档位/健康检查唯一形态）。 */
export function CategoryChip({ label, tone = 'flat', className }: { label: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-2 py-1 fs-caption font-medium glow-badge',
        TONE_TEXT[tone],
        className
      )}
    >
      {label}
    </span>
  );
}

/** 分页器：后继页（知识库/插件/记忆图谱）通用；受控组件，标签由调用方注入。 */
export function Pager({
  page,
  pageSize,
  total,
  onPageChange,
  labels,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  labels?: { prev?: string; next?: string; info?: (range: [number, number], total: number) => string };
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  return (
    <div className='flex items-center justify-end gap-2'>
      <span className='fs-caption text-muted-foreground'>
        {labels?.info ? labels.info([start, end], total) : `${start}-${end} / ${total}`}
      </span>
      <button
        type='button'
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        className='rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-50'
      >
        {labels?.prev ?? '‹'}
      </button>
      <span className='fs-caption tabular-nums text-muted-foreground'>
        {page}/{totalPages}
      </span>
      <button
        type='button'
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        className='rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent disabled:pointer-events-none disabled:opacity-50'
      >
        {labels?.next ?? '›'}
      </button>
    </div>
  );
}
