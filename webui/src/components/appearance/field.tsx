// 外观工作室的控件原语（UI3 追加二，W12 A2 按用户参考截图重排）。
//
// 用户 2026-10-19 给的参考图结构：**左侧 label + 下方一行灰色说明 / 右侧控件 / 最右实时读数**，
// 组与组之间大留白、组内紧凑行、圆角大。所以：
//   · 每行两列（说明区 | 控件区），说明永远在标签正下方，不跟控件抢一行；
//   · 滑块**没有边框**、数值读数带单位，读数就是用户要的「自定义大小 px」；
//   · 选项 2–5 个时用**分段选择器**（一眼看全），选项多时才用下拉；
//   · 组标题带图标与一句话副题，组内第一行不加分隔线，组外用一个 24px 的缝。
//
// 无障碍：开关是 `role="switch"` + `aria-checked`；滑块/数字是原生 input（键盘可操作）；
// 分段选择器是原生 radio + `role="radiogroup"`（方向键切换）；多选是原生 checkbox。
// 不引第三方组件。样式全部走语义 token / 4px 栅格刻度，无裸色值、无任意值方括号。
import type { KeyboardEvent, ReactNode } from 'react';
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';
import {
  activeEdge,
  closeDropdown,
  commitActive,
  dropdownPlacement,
  initialDropdownState,
  listboxAria,
  moveActive,
  openDropdown,
  optionAria,
  optionDomId,
  selectedIndex,
  selectedLabel,
  toggleDropdown,
  triggerAria,
  type DropdownOption,
  type DropdownPlacement,
  type DropdownState,
} from '@/lib/dropdown';
import {
  planSegmentRows,
  SEGMENT_AVAILABLE_DEFAULT,
  SEGMENT_TIERS,
  segmentDensity,
  segmentOptionClass,
  segmentTrackClass,
} from '@/lib/segment-layout';
import { cn } from '@/lib/utils';

/** 一行参数的外壳：左（标题 + 说明）右（控件 + 读数）。 */
export function Field({
  title,
  hint,
  children,
  htmlFor,
}: {
  title: string;
  hint: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className='flex flex-col gap-2 border-b py-4 last:border-b-0 sm:flex-row sm:items-center sm:justify-between sm:gap-6'>
      <div className='flex min-w-0 flex-col gap-1'>
        <label htmlFor={htmlFor} className='fs-card'>
          {title}
        </label>
        <p className='fs-caption text-muted-foreground'>{hint}</p>
      </div>
      {/* 控件区：`min-w-0` + 可收缩 + flex-wrap 三者缺一不可。只写 shrink-0 时，
          多选组（如「侧栏隐藏的页面」16 个勾选）会撑到容器外，整页出现横向溢出
          ——实测 1920 视口下 documentElement.scrollWidth=2223（>1920）。

          `sm:min-w-56`（224px）是 G5 的补牙：只靠 min-w-0，左侧超长说明会把控件区压到
          一百来像素，分段选择器于是各自折行、选中胶囊压在邻项文字上（用户截图）。
          224 与 `SEGMENT_AVAILABLE_DEFAULT` 同源——改一处必须改另一处。 */}
      <div className='flex min-w-0 flex-wrap items-center gap-2 sm:min-w-56 sm:justify-end'>{children}</div>
    </div>
  );
}

/** 真开关（role=switch）。 */
export function Switch({
  id,
  checked,
  onChange,
  label,
}: {
  id: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
}) {
  return (
    <button
      id={id}
      type='button'
      role='switch'
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'inline-flex h-6 w-11 shrink-0 items-center rounded-full px-1 transition-colors',
        checked ? 'bg-primary' : 'bg-muted'
      )}
    >
      <span
        aria-hidden
        className={cn(
          'inline-block size-4 rounded-full bg-card shadow-sm transition-transform duration-200 motion-reduce:transition-none',
          checked ? 'translate-x-5' : 'translate-x-0'
        )}
      />
    </button>
  );
}

/** 带数值读数的滑块（参考图那根灰轨 + 右侧读数；无边框、无输入框外观）。 */
export function Slider({
  id,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  ariaLabel,
}: {
  id: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (next: number) => void;
  ariaLabel: string;
}) {
  return (
    <span className='flex min-w-0 items-center gap-3'>
      <input
        id={id}
        type='range'
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className='h-4 w-36 cursor-pointer accent-primary sm:w-44'
      />
      <span className='w-16 shrink-0 text-right fs-card tabular-nums'>
        {formatValue(value, step)}
        <span className='fs-caption text-muted-foreground'>{unit ?? ''}</span>
      </span>
    </span>
  );
}

/** 数值输入（触屏与键盘都好用；输入非法时不清空，退回上一个合法值）。 */
export function NumberInput({
  id,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  ariaLabel,
}: {
  id: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (next: number) => void;
  ariaLabel: string;
}) {
  return (
    <span className='flex items-center gap-2'>
      <input
        id={id}
        type='number'
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (!Number.isFinite(next)) return;
          onChange(Math.min(max, Math.max(min, next)));
        }}
        className='h-8 w-20 rounded-md border bg-card px-2 text-right fs-body tabular-nums'
      />
      {unit && <span className='fs-caption text-muted-foreground'>{unit}</span>}
    </span>
  );
}

/**
 * 分段选择器（参考图那种「[默认][平台原生][衬线]」样式）。
 *
 * 与 `ChoiceGroup` 的区别只在**外观与语义**：整块一个凹槽、选中项是抬起的小胶囊，
 * 选项数 ≤5 时一眼看全，比下拉少一次点击。底层仍是原生 radio（方向键可切）。
 *
 * G5 版式（用户截图里的两处折行/压字）：
 *   · 宽度先算后画——`segmentDensity` 决定舒适档（fs-body/px-3）还是紧凑档
 *     （fs-caption/px-2），`planSegmentRows` 决定横排还是两列均分；
 *   · 每个选项 `shrink-0 + whitespace-nowrap`：label 内部永不折行，
 *     选中胶囊因此不可能压到下一行文字上；
 *   · 轨道 `shrink-0`：父级控件区放不下时整块换行，而不是把选项一个个挤扁。
 */
export function Segment({
  name,
  value,
  options,
  onChange,
  ariaLabel,
}: {
  name: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (next: string) => void;
  ariaLabel: string;
}) {
  const labels = options.map((option) => option.label);
  const density = segmentDensity(labels);
  const rows = planSegmentRows(labels, SEGMENT_AVAILABLE_DEFAULT, SEGMENT_TIERS[density]);
  return (
    <span role='radiogroup' aria-label={ariaLabel} className={segmentTrackClass(rows.length)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <label key={option.value} className={segmentOptionClass(density, active, rows.length)}>
            <input
              type='radio'
              name={name}
              value={option.value}
              checked={active}
              onChange={() => onChange(option.value)}
              className='sr-only'
            />
            {option.label}
          </label>
        );
      })}
    </span>
  );
}

/** 单选组（原生 radio，一行 chips；选项多、需要换行时用）。 */
export function ChoiceGroup({
  name,
  value,
  options,
  onChange,
  ariaLabel,
}: {
  name: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (next: string) => void;
  ariaLabel: string;
}) {
  return (
    <span role='radiogroup' aria-label={ariaLabel} className='flex max-w-full flex-wrap justify-end gap-1'>
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            // shrink-0 + nowrap：一键一 chip，换行只发生在 chip 之间，绝不把文字挤成两行。
            'shrink-0 cursor-pointer whitespace-nowrap rounded-full border px-3 py-1 fs-caption transition-colors',
            option.value === value
              ? 'border-primary bg-primary/15 text-foreground'
              : 'text-muted-foreground hover:bg-accent'
          )}
        >
          <input
            type='radio'
            name={name}
            value={option.value}
            checked={option.value === value}
            onChange={() => onChange(option.value)}
            className='sr-only'
          />
          {option.label}
        </label>
      ))}
    </span>
  );
}

/** 多选（原生 checkbox，一行 chips）。 */
export function Checkbox({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label
      htmlFor={id}
      className={cn(
        // shrink-0 + nowrap：勾选项之间换行，绝不把 chip 内文字挤成两行。
        'flex shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap rounded-full border px-3 py-1 fs-caption transition-colors',
        checked ? 'border-primary bg-primary/15 text-foreground' : 'text-muted-foreground hover:bg-accent'
      )}
    >
      <input
        id={id}
        type='checkbox'
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className='size-3 accent-primary'
      />
      {label}
    </label>
  );
}

/**
 * 触发键的两档尺寸。**必须一行一档**：版式宪法门是行级判定，同一行出现两个 fs-*
 * （哪怕只是三元的两个分支）会被当成「同元素字号双写」判红。
 */
const SELECT_SIZE_CLASS = {
  default: 'h-9 px-3 fs-body',
  compact: 'h-8 px-2 fs-caption',
} as const;

/**
 * 下拉选择（**全站唯一下拉原语**，G1：原生 `<select>` 全部收编到这里）。
 *
 * 为什么自己写：浏览器默认外观与玻璃语言完全不是一套材质（圆角、阴影、底色、边框
 * 都由 UA 定），且 `option` 在 Windows 上不可样式化。这里用 button + listbox 重建，
 * 行为与无障碍按 WAI-ARIA「select-only combobox」：焦点留在触发键、活动项靠
 * `aria-activedescendant` 指认，所以读屏用户听到的是「下拉框，当前值 X，已展开」。
 *
 * 键盘：↑/↓ 移动（两端钳住）、Home/End 跳首尾、Enter/空格 展开或提交、Esc 合上、
 * Tab 合上；点击外部与 Esc 同一个收口——只合上、绝不顺手改值。
 * 状态机在 `src/lib/dropdown.ts`，本组件只负责把状态画出来。
 */
export function Select({
  id,
  value,
  options,
  onChange,
  ariaLabel,
  disabled = false,
  size = 'default',
  block = false,
  title,
}: {
  id?: string;
  value: string;
  options: ReadonlyArray<DropdownOption>;
  onChange: (next: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  /** `compact` = h-8 + fs-caption（日志筛选条这类密集行） */
  size?: 'default' | 'compact';
  /** 撑满父容器（配置页/设置页的表单控件） */
  block?: boolean;
  title?: string;
}) {
  const autoId = useId();
  const baseId = id ?? `select-${autoId.replace(/:/g, '')}`;
  const [state, setState] = useState<DropdownState>(() => initialDropdownState(options, value));
  const rootRef = useRef<HTMLSpanElement>(null);
  /** 触发键：弹层定位只认它的 `getBoundingClientRect()`。 */
  const triggerRef = useRef<HTMLButtonElement>(null);
  /** 弹层被 portal 到 body 了，不再是 rootRef 的后代——点外部判定要单独认它。 */
  const panelRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<DropdownPlacement | null>(null);
  const selected = selectedIndex(options, value);

  // 外部改值（catalog 晚到 / 重置 / 撤销）时把活动项拉回已选项，别留上次的高亮。
  useEffect(() => {
    setState({ open: false, activeIndex: selected < 0 ? 0 : selected });
  }, [selected, value]);

  // 展开时按视口算落点：下方够就向下，下方不够就翻面向上。
  // useLayoutEffect（不是 useEffect）：要在**绘制前**算好，否则会先闪一帧「无处安放」的弹层。
  useLayoutEffect(() => {
    if (!state.open) {
      setPlacement(null);
      return;
    }
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    setPlacement(
      dropdownPlacement(
        { top: rect.top, bottom: rect.bottom, left: rect.left, width: rect.width },
        { width: window.innerWidth, height: window.innerHeight },
      ),
    );
  }, [state.open]);

  // 点击外部关闭：与 Esc 同一个收口，不改值。
  useEffect(() => {
    if (!state.open) return;
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      // 弹层 portal 出去了，判「外部」得同时看触发键与面板两块。
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setState((current) => closeDropdown(current, options, value));
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [state.open, options, value]);

  // 滚动 / 改窗口尺寸 = 弹层落点立刻作废。**直接收起，不追位置**：追位置要 rAF 逐帧重算，
  // 是性能坑，且滚到一半的中间态还会让人误点。scroll 必须 capture——内层滚动容器
  // （例如设置弹窗的 overflow-y-auto）的 scroll 不冒泡，冒泡阶段收不到。
  // 唯一的例外是**面板自己内部滚动**（选项超过 maxHeight 时），那不算漂移，否则长列表滚不动。
  useEffect(() => {
    if (!state.open) return;
    function closeOnAway() {
      setState((current) => closeDropdown(current, options, value));
    }
    function onScrollAway(event: Event) {
      if (panelRef.current?.contains(event.target as Node)) return;
      closeOnAway();
    }
    window.addEventListener('scroll', onScrollAway, true);
    window.addEventListener('resize', closeOnAway);
    return () => {
      window.removeEventListener('scroll', onScrollAway, true);
      window.removeEventListener('resize', closeOnAway);
    };
  }, [state.open, options, value]);

  // 长列表用键盘走位时，活动项必须在可视区内（否则看不见走到哪一项）。
  useEffect(() => {
    if (!state.open) return;
    document.getElementById(optionDomId(baseId, state.activeIndex))?.scrollIntoView({
      block: 'nearest',
    });
  }, [state.open, state.activeIndex, baseId]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setState((current) => moveActive(current, 1, options));
        break;
      case 'ArrowUp':
        event.preventDefault();
        setState((current) => moveActive(current, -1, options));
        break;
      case 'Home':
        event.preventDefault();
        setState((current) =>
          current.open ? activeEdge(current, 'first', options) : openDropdown(current, options, value)
        );
        break;
      case 'End':
        event.preventDefault();
        setState((current) =>
          current.open ? activeEdge(current, 'last', options) : openDropdown(current, options, value)
        );
        break;
      case 'Enter':
      case ' ': {
        event.preventDefault();
        const result = commitActive(state, options);
        setState(result.state);
        if (result.value !== null) onChange(result.value);
        break;
      }
      case 'Escape':
        if (state.open) {
          event.preventDefault();
          setState(closeDropdown(state, options, value));
        }
        break;
      case 'Tab':
        if (state.open) setState(closeDropdown(state, options, value));
        break;
      default:
        break;
    }
  }

  return (
    <span ref={rootRef} className={cn('relative', block ? 'w-full' : 'inline-block max-w-full')}>
      <button
        ref={triggerRef}
        id={id}
        type='button'
        title={title}
        disabled={disabled}
        {...triggerAria(baseId, state, options.length)}
        aria-label={ariaLabel}
        onClick={() => setState((current) => toggleDropdown(current, options, value))}
        onKeyDown={onKeyDown}
        className={cn(
          'inline-flex items-center justify-between gap-2 rounded-md border bg-background text-left outline-none transition-colors focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
          SELECT_SIZE_CLASS[size],
          block ? 'w-full' : 'min-w-40'
        )}
      >
        <span className='min-w-0 truncate'>{selectedLabel(options, value)}</span>
        <ChevronDown
          aria-hidden
          className={cn(
            'size-4 shrink-0 transition-transform motion-reduce:transition-none',
            state.open && 'rotate-180'
          )}
        />
      </button>
      {state.open &&
        placement &&
        // 为什么还要 portal：`position: fixed` 本身**不足以逃生**——`transform` / `filter` /
        // `backdrop-filter` 的祖先会成为 fixed 的包含块，于是 fixed 又退回「相对那块玻璃定位」，
        // 继续被它的 overflow 裁。本仓 `.glass-panel`（分组卡片）与 `@utility window`（主窗口）
        // 两族材质都带 backdrop-filter，弹层挂在组件树里就一定会撞上。
        // portal 到 body 之后，`getBoundingClientRect()` 的视口坐标与 fixed 的参照系才一致。
        createPortal(
          <div
            ref={panelRef}
            className='fixed z-50'
            style={{
              left: placement.left,
              width: placement.width,
              ...(placement.openUp
                ? { bottom: placement.bottom ?? 0 }
                : { top: placement.top ?? 0 }),
            }}
          >
            {/* 玻璃材质单独挂里层 ul：`.glass-panel` 是**无 layer 的普通 CSS 类**（index.css），
                无 layer 的声明在层叠里压过 Tailwind 的 `@layer utilities`，所以定位必须在外层
                div 上（inline style 更高一筹），材质留在 ul。
                maxHeight 走内联（`max-h-60` 留作未测量时的兜底，两者同为 240px）。 */}
            <ul
              {...listboxAria(baseId)}
              aria-label={ariaLabel}
              style={{ maxHeight: placement.maxHeight }}
              className='max-h-60 overflow-y-auto rounded-lg border glass-panel p-1'
            >
              {options.map((option, index) => (
                <li
                  key={option.value}
                  {...optionAria(baseId, index, selected)}
                  className={cn(
                    'flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1 fs-body',
                    index === state.activeIndex ? 'bg-accent' : '',
                    index === selected ? 'text-foreground' : 'text-muted-foreground'
                  )}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() =>
                    setState((current) => (current.open ? { ...current, activeIndex: index } : current))
                  }
                  onClick={(event) => {
                    // 这三行缺一不可：本组件常被包在 `<label>` 里（可视编辑器/设置页/凭据页），
                    // 而 label 对「非交互后代的点击」会**转发一次 click 给里面那个 button**
                    // ——不 preventDefault，选完一项会立刻又弹开；不 stopPropagation，外层
                    // 表单的行点击/拖拽也会被顺带触发。
                    event.preventDefault();
                    event.stopPropagation();
                    onChange(option.value);
                    setState(closeDropdown(state, options, option.value));
                  }}
                >
                  <span className='min-w-0 truncate'>{option.label}</span>
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )}
    </span>
  );
}

/** 文本输入。 */
export function TextInput({
  id,
  value,
  placeholder,
  onChange,
  ariaLabel,
  invalid = false,
}: {
  id: string;
  value: string;
  placeholder?: string;
  onChange: (next: string) => void;
  ariaLabel: string;
  /** 校验未通过（如快捷键冲突）：描边转警示色，不只靠颜色——旁边另有文字。 */
  invalid?: boolean;
}) {
  return (
    <input
      id={id}
      type='text'
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className={cn('h-8 w-40 rounded-md border bg-card px-2 fs-body', invalid && 'border-tone-warn')}
    />
  );
}

/** 分组卡片：图标 + 标题 + 一句副题，下面是若干 Field。 */
export function GroupCard({
  id,
  icon,
  title,
  subtitle,
  children,
  action,
}: {
  id: string;
  icon?: ReactNode;
  title: string;
  subtitle: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section id={id} className='glass-panel scroll-mt-24 rounded-lg border px-4 py-3'>
      <header className='flex flex-wrap items-start justify-between gap-2 border-b pb-3'>
        <div className='flex min-w-0 items-start gap-3'>
          {icon && (
            <span
              aria-hidden
              className='flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary'
            >
              {icon}
            </span>
          )}
          <div className='flex min-w-0 flex-col gap-1'>
            <h2 className='fs-card'>{title}</h2>
            <p className='fs-caption text-muted-foreground'>{subtitle}</p>
          </div>
        </div>
        {action}
      </header>
      <div className='flex flex-col'>{children}</div>
    </section>
  );
}

/** 数值读数：按步长的小数位数收，避免 0.30000000000000004 这种毛刺。 */
function formatValue(value: number, step: number): string {
  const decimals = String(step).split('.')[1]?.length ?? 0;
  return decimals > 0 ? value.toFixed(decimals) : String(value);
}
