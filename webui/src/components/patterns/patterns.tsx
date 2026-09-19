// 版式宪法可复用组件（2026-09-18 用户裁定③）：
// StatCard / PageHeader / SectionCard / DataGrid / CategoryChip / Pager。
// 后继「知识库/插件/记忆图谱」三页由这些组件拼装——改这里即全站生效。
// 字号只用五档阶梯（fs-*），间距只用 4px 栅格 {4,8,12,16,24}，色只用语义 token。
import type { ReactNode } from 'react';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/** 统计卡：图标 + 标签 + 数字大字（+ 脚注）。总览/后续页的指标卡唯一形态。 */
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
        <div>
          <div className='flex items-center gap-2'>
            {icon}
            <span className='fs-num'>{value}</span>
          </div>
          {sub && <p className='mt-1 fs-caption text-muted-foreground'>{sub}</p>}
        </div>
      ) : null}
      {children}
    </SectionCard>
  );
}

/** 页头：页面标题（fs-page）+ 副题（fs-caption）+ 右侧动作区。 */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className='flex flex-wrap items-center justify-between gap-4'>
      <div className='flex flex-col gap-1'>
        <h1 className='fs-page'>{title}</h1>
        {subtitle && <p className='fs-caption text-muted-foreground'>{subtitle}</p>}
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
        'inline-flex shrink-0 items-center rounded-full px-2 py-1 fs-caption font-medium',
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
