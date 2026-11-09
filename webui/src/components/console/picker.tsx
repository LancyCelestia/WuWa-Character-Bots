// 控制台可复用件（W15 T5）：标签 Chip / 标签组 ChipGroup / 开关行 ToggleRow。
//
// 三条用户原话在这里兑现：
//   ① 「说明文字不得省略」→ ChipGroup.hint 与 ToggleRow.hint 是**必填** prop（不是 `?`），
//      类型层就写不出一个没有说明的筛选组/开关行；
//   ② 「不使用厚重阴影或多层描边」→ Chip 只一层 `border-hairline` + 语义面色，无 shadow-*；
//   ③ 「不要恐吓性红」→ sensitive 档走**独立的 `surface` 卡片 + eyebrow 标题「数据采集」**，
//      文字色一律 `text-muted-foreground`，最多给图标一枚 `text-tone-warn`。
//
// 版式只走既有尺子：字号五档 fs-*、间距 4px 栅格、圆角 md/lg/xl/full、语义色 / tone-*。
import { type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Toggle } from './panel';

/**
 * 标签（Chip）。给了 `onToggle` 就是可点的筛选片（`<button aria-pressed>`），
 * 否则是纯展示片（`<span>`）。`onRemove` 只在 hover / 键盘聚焦时露出小 X。
 */
export function Chip({
  label,
  selected = false,
  onToggle,
  onRemove,
  className,
}: {
  label: string;
  selected?: boolean;
  onToggle?: () => void;
  /** 给了才在 hover 时显示关闭按钮。 */
  onRemove?: () => void;
  className?: string;
}) {
  const face = cn(
    'inline-flex items-center gap-1 rounded-full border-hairline px-3 py-1 fs-caption transition-colors',
    selected ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'
  );

  // 关闭钮是 Chip **内部**的兄弟节点（不是外层套壳），所以 `group` 挂在外层：
  // hover / 键盘聚焦任一命中，X 才显形——只挂 hover 会把键盘用户挡在门外。
  const body = (
    <>
      {onToggle ? (
        <button type='button' aria-pressed={selected} onClick={onToggle} className={face}>
          {label}
        </button>
      ) : (
        <span className={face}>{label}</span>
      )}
      {onRemove && (
        <button
          type='button'
          aria-label={`移除 ${label}`}
          onClick={(event) => {
            // 可点片：移除这一下不该顺带触发筛选切换。
            event.stopPropagation();
            onRemove();
          }}
          className='inline-flex size-4 items-center justify-center rounded-full text-muted-foreground opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100'
        >
          <X aria-hidden className='size-3' />
        </button>
      )}
    </>
  );

  return <span className={cn('group inline-flex items-center gap-1', className)}>{body}</span>;
}

/**
 * 标签组：可选 eyebrow 标题 + 一排 wrap 的 Chip + **底部必填说明**。
 *
 * `children` 为空时不渲染一排空壳（那就是「乱堆砌文字」的另一种形态），
 * 改渲染一行 `当前没有可筛选的标签`。
 */
export function ChipGroup({
  children,
  hint,
  label,
  className,
}: {
  children: ReactNode;
  /** 必填：≤ 40 字，说清「这组标签筛选的是什么」。 */
  hint: string;
  label?: string;
  className?: string;
}) {
  const empty = isEmptyChildren(children);
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      {label && <span className='eyebrow fs-caption text-muted-foreground'>{label}</span>}
      {empty ? (
        <span className='fs-caption text-muted-foreground'>当前没有可筛选的标签</span>
      ) : (
        <div className='flex flex-wrap items-center gap-1'>{children}</div>
      )}
      <span className='fs-caption text-muted-foreground'>{hint}</span>
    </div>
  );
}

/** 空 children 判定：null / undefined / false / '' / 空数组 / 只含这些的嵌套数组。 */
function isEmptyChildren(node: ReactNode): boolean {
  if (node === null || node === undefined || node === false || node === true || node === '') return true;
  if (Array.isArray(node)) return node.every(isEmptyChildren);
  return false;
}

/**
 * 开关行：标签左、开关右、说明在下。
 *
 * 开关本体**复用 `panel.tsx` 的 `Toggle`**（真 `role="switch"` + `aria-checked`），
 * 这里只负责版式与说明文字；`disabled` 由外层 `inert` 兜住焦点与点击（Toggle 自身无该 prop）。
 *
 * `sensitive` 档不是「红色警告」，而是**归类**：整行套独立 `surface` 卡片，
 * 顶部 eyebrow「数据采集」说明这是隐私相关项，说明文字仍是 `text-muted-foreground`。
 */
export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
  sensitive,
  disabled,
  className,
}: {
  label: string;
  /** 必填：≤ 40 字，说清「开启/关闭会影响什么」。 */
  hint: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  /** 隐私敏感项：整行换成独立的「数据采集」卡片样式。 */
  sensitive?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const body = (
    <>
      <div className='flex items-center justify-between gap-3'>
        <span className='min-w-0 flex-1 truncate fs-body'>{label}</span>
        <span className={cn('shrink-0', disabled && 'opacity-50')} inert={disabled}>
          <Toggle label={label} checked={checked} onChange={onChange} />
        </span>
      </div>
      <p className='fs-caption text-muted-foreground'>{disabled ? `${hint}（当前不可改）` : hint}</p>
    </>
  );

  if (sensitive) {
    return (
      <section
        aria-disabled={disabled}
        className={cn('surface flex min-w-0 flex-col gap-2 rounded-lg p-3', disabled && 'opacity-60', className)}
      >
        <span className='eyebrow fs-caption text-muted-foreground'>数据采集</span>
        {body}
      </section>
    );
  }

  return (
    <div aria-disabled={disabled} className={cn('flex min-w-0 flex-col gap-1', disabled && 'opacity-60', className)}>
      {body}
    </div>
  );
}
