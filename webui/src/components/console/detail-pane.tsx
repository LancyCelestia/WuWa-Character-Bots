// 详情栏（W15 T4）：标题 + 副题 + 四列字典 + 可选下钻区。
//
// 三件事是本文件的存在理由：
//   ① 顶部「未采集指标」提示条——数据源自 `absentFields()`，文案是一句平述：
//      不阻塞、不高红、不上插画（用户明确说不要恐吓性的红）。缺数据要说，但不必吓人。
//   ② 空态 `DetailEmpty`——一行字，不留空白面板。
//   ③ 关闭按钮只在给了 `onClose` 时出现。
//
// 材质：整块挂 `window`（大窗层级）+ `rounded-lg`；内部独立滚动（`overflow-y-auto` +
// `overscroll-contain`），免得滚详情栏把旁边的列表一起顶飞。
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { absentFields } from '@/lib/field-dict';
import { cn } from '@/lib/utils';
import { FieldTable } from '@/components/console/field-table';

/** 空态默认提示（`hint` 可覆盖）。 */
const EMPTY_HINT = '从左侧选一项查看它的完整字段说明';

/**
 * 空态：没有选中项时详情栏显示这个，不显示空白面板。
 * `role='status'`：它是告知「还没选」，不是可操作控件。
 */
export function DetailEmpty({ hint }: { hint?: string }) {
  return (
    <div className='flex items-start gap-2 p-4 fs-caption text-muted-foreground' role='status'>
      <span aria-hidden className='mt-1 size-1 shrink-0 rounded-full bg-muted-foreground/60' />
      <span className='min-w-0'>{hint ?? EMPTY_HINT}</span>
    </div>
  );
}

/**
 * 详情栏容器。
 *
 * 没选中项时调用方应渲染 `DetailEmpty`（而不是整块不渲染）——那样主区宽度会在
 * 「选 / 不选」之间跳一格。
 */
export function DetailPane({
  title,
  subtitle,
  fieldKeys,
  values,
  children,
  onClose,
  className,
}: {
  title: string;
  subtitle?: string;
  /** 要渲染的字段键值。 */
  fieldKeys: readonly string[];
  values?: Record<string, ReactNode>;
  /** 时序下钻图等挂在字典下方。 */
  children?: ReactNode;
  /** 关闭按钮；给了才渲染。 */
  onClose?: () => void;
  className?: string;
}) {
  const absent = absentFields();
  return (
    <section className={cn('window rounded-lg', className)} aria-label={title}>
      {/* 头部：标题 + 副题 + 关闭。`pr-2` 让关闭钮不顶到内沿。 */}
      <header className='flex min-w-0 items-start gap-2 border-b px-4 py-3 pr-2'>
        <div className='flex min-w-0 flex-1 flex-col'>
          <h2 className='truncate fs-card text-foreground' title={title}>
            {title}
          </h2>
          {subtitle && (
            <p className='truncate fs-caption text-muted-foreground' title={subtitle}>
              {subtitle}
            </p>
          )}
        </div>
        {onClose && (
          <button
            type='button'
            onClick={onClose}
            aria-label='关闭详情栏'
            className='flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground'
          >
            <X aria-hidden className='size-4' />
          </button>
        )}
      </header>

      {/* 滚动体：`overscroll-contain` 把滚动链断在这里，滚到底不会把外层带着滚。 */}
      <div className='flex flex-col gap-3 overflow-y-auto overscroll-contain p-4 no-scrollbar'>
        {absent.length > 0 && (
          // 提示条：一行平述 + `fs-caption` + warn 档。不挂 console-pulse、不铺底色。
          <p className='fs-caption text-tone-warn'>
            以下指标尚未采集：{absent.map((doc) => doc.label).join('、')}
          </p>
        )}
        <FieldTable keys={fieldKeys} values={values} />
        {children}
      </div>
    </section>
  );
}
