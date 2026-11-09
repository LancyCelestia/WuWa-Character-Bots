// 自研下拉的状态机（G1：替代 WebUI 里全部原生 `<select>`）。
//
// 为什么判据住在 lib 而不是 .tsx：仓库没有 jsdom / @testing-library，也不许为了测试装包。
// 于是「开合 / 方向键 / Enter / Esc / 点外部 / 回填 / ARIA」全部收进纯函数，组件只负责
// 把状态画成 DOM。组件与测试吃的是同一份实现，不存在「测试测了一套、页面跑另一套」。
//
// 无障碍口径 = WAI-ARIA「select-only combobox」：
//   · 触发键 role=combobox + aria-haspopup=listbox + aria-expanded + aria-controls；
//   · 弹层 role=listbox，每项 role=option + aria-selected；
//   · 焦点始终留在触发键上，活动项靠 aria-activedescendant 指认（读屏跟着念）；
//   · 方向键在两端钳住（不绕回），Home/End 跳首尾，Esc / 点击外部只合上、不改值。
//
// 约定：`selected` = 已提交的值（value 所在下标），`active` = 键盘/鼠标悬停的高亮项。
// 移动活动项**不能**改 aria-selected——只有 Enter/点击才提交。

export interface DropdownOption {
  readonly value: string;
  readonly label: string;
}

export interface DropdownState {
  readonly open: boolean;
  readonly activeIndex: number;
}

/** 值在选项里的下标；没有则 -1（空串、脏值都走这条）。 */
export function selectedIndex(options: readonly DropdownOption[], value: string): number {
  return options.findIndex((option) => option.value === value);
}

/** 触发键上显示的文字；值不在选项里时回空串，由调用方决定占位文案。 */
export function selectedLabel(options: readonly DropdownOption[], value: string): string {
  const index = selectedIndex(options, value);
  return index < 0 ? '' : options[index].label;
}

function clamp(index: number, count: number): number {
  if (count <= 0) return 0;
  if (!Number.isFinite(index)) return 0;
  return Math.min(Math.max(Math.trunc(index), 0), count - 1);
}

function atSelection(options: readonly DropdownOption[], value: string): number {
  return clamp(selectedIndex(options, value), options.length);
}

export function initialDropdownState(
  options: readonly DropdownOption[],
  value: string,
): DropdownState {
  return { open: false, activeIndex: atSelection(options, value) };
}

/** 打开时活动项落在已选项上（不是第 0 项）——键盘用户开手就能看到当前值。 */
export function openDropdown(
  _state: DropdownState,
  options: readonly DropdownOption[],
  value: string,
): DropdownState {
  return { open: true, activeIndex: atSelection(options, value) };
}

/** 合上并把活动项退回已选项，下一次打开不残留上次的高亮。 */
export function closeDropdown(
  _state: DropdownState,
  options: readonly DropdownOption[],
  value: string,
): DropdownState {
  return { open: false, activeIndex: atSelection(options, value) };
}

export function toggleDropdown(
  state: DropdownState,
  options: readonly DropdownOption[],
  value: string,
): DropdownState {
  return state.open ? closeDropdown(state, options, value) : openDropdown(state, options, value);
}

/**
 * 上下移动活动项。合着的时候只展开、不移动（APG：第一次按键打开，第二次才走）。
 * 两端钳住，不绕回：绕回会让「按到底了」这件事对读屏用户不可见。
 */
export function moveActive(
  state: DropdownState,
  delta: number,
  options: readonly DropdownOption[],
): DropdownState {
  if (!state.open) return { open: true, activeIndex: clamp(state.activeIndex, options.length) };
  return { open: true, activeIndex: clamp(state.activeIndex + delta, options.length) };
}

export function activeEdge(
  state: DropdownState,
  edge: 'first' | 'last',
  options: readonly DropdownOption[],
): DropdownState {
  return { open: true, activeIndex: clamp(edge === 'last' ? options.length - 1 : 0, options.length) };
}

/**
 * Enter / 空格：展开时提交活动项并合上；合着时只展开（不顺手改值）。
 * 返回值里的 value=null 表示「这一下没有提交任何值」。
 */
export function commitActive(
  state: DropdownState,
  options: readonly DropdownOption[],
): { state: DropdownState; value: string | null } {
  const activeIndex = clamp(state.activeIndex, options.length);
  if (!state.open) {
    return { state: { open: true, activeIndex }, value: null };
  }
  const option = options[activeIndex];
  return { state: { open: false, activeIndex }, value: option ? option.value : null };
}

// ---------- ARIA ----------
// 全部返回「要摊到 DOM 上的属性表」，组件直接 spread；测试据同一张表锁无障碍契约。

export function optionDomId(baseId: string, index: number): string {
  return `${baseId}-option-${index}`;
}

export function listboxDomId(baseId: string): string {
  return `${baseId}-listbox`;
}

/** 只有展开且真有选项时才指认活动项——合上时指一个看不见的 id 会让读屏念空。 */
export function activeDescendant(
  state: DropdownState,
  baseId: string,
  count: number,
): string | undefined {
  if (!state.open || count <= 0 || state.activeIndex < 0 || state.activeIndex >= count) return undefined;
  return optionDomId(baseId, state.activeIndex);
}

export function triggerAria(
  baseId: string,
  state: DropdownState,
  count: number,
): {
  role: 'combobox';
  'aria-haspopup': 'listbox';
  'aria-expanded': 'true' | 'false';
  'aria-controls': string;
  'aria-activedescendant': string | undefined;
} {
  return {
    role: 'combobox',
    'aria-haspopup': 'listbox',
    'aria-expanded': state.open ? 'true' : 'false',
    'aria-controls': listboxDomId(baseId),
    'aria-activedescendant': activeDescendant(state, baseId, count),
  };
}

export function listboxAria(baseId: string): { role: 'listbox'; id: string } {
  return { role: 'listbox', id: listboxDomId(baseId) };
}

// ---------- 弹层定位（视口碰撞检测） ----------
//
// 缺陷现场：弹层原来是 `absolute`，**被最近的有 overflow 的祖先裁掉**。
// `settings-dialog.tsx` 的弹窗是 `max-h-[90svh] overflow-y-auto`，里面放了字号档与壁纸档
// 两个 Select——靠下那个一展开就被裁，用户看到的是「点了没反应」。
//
// 只靠 `position: fixed` 还不够：`transform` / `filter` / `backdrop-filter` 的祖先会成为
// fixed 的**包含块**，于是 fixed 又变回「相对那块玻璃定位」。本仓 `.glass-panel` 与
// `@utility window` 两族材质都带 `backdrop-filter`，所以弹层由组件 portal 到 body 再定位
// ——下面这个纯函数拿到的 rect 与 viewport 都按视口坐标算，两边口径必须一致。
//
// 数值全走 4px 栅格；`DROPDOWN_MAX_PANEL = 240` 就是原来写死的 `max-h-60`，不新增任意值方括号。

/** 触发键与弹层之间的缝（4px 栅格）。 */
export const DROPDOWN_GAP = 4;
/** 弹层与视口边缘至少留这么多，别贴死墙。 */
export const DROPDOWN_MARGIN = 8;
/** 下方/上方都挤时的最小面板高度——再矮就什么都看不见了（三行）。 */
export const DROPDOWN_MIN_PANEL = 96;
/** 面板高度上限，等价于原 `max-h-60`（240px）。 */
export const DROPDOWN_MAX_PANEL = 240;

/** 触发键的视口坐标（`getBoundingClientRect()` 的四项）。 */
export interface DropdownAnchor {
  readonly top: number;
  readonly bottom: number;
  readonly left: number;
  readonly width: number;
}

export interface DropdownViewport {
  readonly width: number;
  readonly height: number;
}

/**
 * 摊到 `style` 上的定位结果：**视口坐标**（配合 portal + `position: fixed`）。
 *
 * `top` 与 `bottom` 互斥且必有一个是 null——两条定位线同时写会打架（谁赢由高度决定，
 * 面板矮时看不出、长时突然跳）。
 */
export interface DropdownPlacement {
  /** true = 翻到触发键上方（此时用 `bottom`，`top` 为 null）。 */
  readonly openUp: boolean;
  readonly top: number | null;
  readonly bottom: number | null;
  readonly left: number;
  readonly width: number;
  readonly maxHeight: number;
}

/** NaN/Infinity 一律退回兜底值：这些数摊进 CSS 等于「弹层消失或贴到 0 点」。 */
function finite(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

/**
 * 按触发键与视口算弹层位置。
 *
 * 三种分支（按优先级）：
 *   ① 下方放得下（≥ 最小面板高）→ 向下，`top = rect.bottom + gap`；
 *   ② 下方放不下、上方放得下 → **翻面向上**，`bottom = viewportH - rect.top + gap`
 *      （CSS `bottom` 是「离视口下沿多远」，不是面板自己的顶边）；
 *   ③ 上下都放不下（或触发键比视口还高）→ 取空间大的一侧，`maxHeight` = 那一侧的空间。
 *
 * 退化输入（视口高 0 / rect 在视口外 / NaN）没有可靠锚点：**退回向下**并给最小面板高度，
 * 绝不返回 NaN。`maxHeight` 被视口钳住（`viewportH - 2*margin`），下面的测试扫掠断言
 * 「算出来的四边都落在视口内」。
 */
export function dropdownPlacement(
  anchor: DropdownAnchor,
  viewport: DropdownViewport,
): DropdownPlacement {
  const viewportH = Math.max(0, finite(viewport.height, 0));
  const viewportW = Math.max(0, finite(viewport.width, 0));
  const left0 = finite(anchor.left, 0);
  const width0 = Math.max(0, finite(anchor.width, 0));
  const top0 = finite(anchor.top, 0);
  const bottom0 = finite(anchor.bottom, top0);

  // 宽度沿用触发键宽度，但不许顶出视口右边界：贴右墙时整块左移，而不是一半在屏幕外。
  const width = Math.min(width0, Math.max(0, viewportW - 2 * DROPDOWN_MARGIN));
  const left = Math.min(
    Math.max(left0, DROPDOWN_MARGIN),
    Math.max(0, viewportW - DROPDOWN_MARGIN - width),
  );

  const below = viewportH - bottom0 - DROPDOWN_GAP - DROPDOWN_MARGIN;
  const above = top0 - DROPDOWN_GAP - DROPDOWN_MARGIN;
  const panelCap = Math.max(0, viewportH - 2 * DROPDOWN_MARGIN);
  // 下限本身也要装得进视口：装不下就退回「没有可用视口」的兜底高度。
  const floor = panelCap > 0 ? Math.min(DROPDOWN_MIN_PANEL, panelCap) : DROPDOWN_MIN_PANEL;

  const anchored = viewportH > 0 && bottom0 > 0 && top0 < viewportH;
  if (!anchored) {
    // 触发键整块在视口外（含拿不到视口高）：没有可靠锚点，贴一个最小面板向下展开。
    const top = Math.min(Math.max(bottom0 + DROPDOWN_GAP, 0), Math.max(0, viewportH - floor));
    return { openUp: false, top, bottom: null, left, width, maxHeight: floor };
  }

  if (below >= DROPDOWN_MIN_PANEL) {
    return {
      openUp: false,
      top: bottom0 + DROPDOWN_GAP,
      bottom: null,
      left,
      width,
      maxHeight: Math.min(below, DROPDOWN_MAX_PANEL),
    };
  }

  if (above >= DROPDOWN_MIN_PANEL) {
    return {
      openUp: true,
      top: null,
      bottom: viewportH - top0 + DROPDOWN_GAP,
      left,
      width,
      maxHeight: Math.min(above, DROPDOWN_MAX_PANEL),
    };
  }

  // 上下都挤：这一侧的空间已经含边距，直接当 maxHeight 用 → 天然不越视口。
  const space = Math.max(below, above);
  if (space <= 0) {
    // 触发键比视口还高：两侧都被挤穿，同「无锚点」兜底（仍不越视口下沿）。
    const top = Math.min(Math.max(bottom0 + DROPDOWN_GAP, 0), Math.max(0, viewportH - floor));
    return { openUp: false, top, bottom: null, left, width, maxHeight: floor };
  }
  const maxHeight = Math.min(space, DROPDOWN_MAX_PANEL);
  if (below >= above) {
    return { openUp: false, top: bottom0 + DROPDOWN_GAP, bottom: null, left, width, maxHeight };
  }
  return {
    openUp: true,
    top: null,
    bottom: viewportH - top0 + DROPDOWN_GAP,
    left,
    width,
    maxHeight,
  };
}

/** aria-selected 看**已提交的值**，不看活动项（移动高亮 ≠ 选中）。 */
export function optionAria(
  baseId: string,
  index: number,
  selected: number,
): { role: 'option'; id: string; 'aria-selected': 'true' | 'false' } {
  return {
    role: 'option',
    id: optionDomId(baseId, index),
    'aria-selected': index === selected && selected >= 0 ? 'true' : 'false',
  };
}
