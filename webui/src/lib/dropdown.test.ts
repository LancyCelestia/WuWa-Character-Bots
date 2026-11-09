import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  activeDescendant,
  activeEdge,
  closeDropdown,
  commitActive,
  DROPDOWN_GAP,
  DROPDOWN_MARGIN,
  DROPDOWN_MAX_PANEL,
  DROPDOWN_MIN_PANEL,
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
} from './dropdown.ts';

/**
 * 自研下拉（替代原生 `<select>`）的行为锁。
 *
 * 判据住在 lib 而不是 .tsx：.tsx 在 node --test 里渲染不了（仓库没有 jsdom，
 * 也不许为此装包）。所以把「开合 / 方向键 / Enter / Esc / 点外部 / 回填 / ARIA」
 * 全部收进一个纯状态机，组件只负责把状态画出来。组件与这里的函数是**同一份实现**，
 * 不存在「测试测了一套、页面跑另一套」两张皮。
 *
 * 无障碍口径按 WAI-ARIA「select-only combobox」：触发键 role=combobox +
 * aria-haspopup=listbox + aria-expanded + aria-controls，弹层 role=listbox，
 * 每项 role=option + aria-selected，焦点不动、活动项靠 aria-activedescendant 指认。
 */

const OPTIONS: DropdownOption[] = [
  { value: 'auto', label: '自动（按屏幕宽度与网络选档）' },
  { value: '720p', label: '省流 720p' },
  { value: '1080p', label: '高清 1080p' },
  { value: 'custom', label: '自定义地址' },
];

const BASE = 'webui-wallpaper-tier';

// ---------- 开合 ----------

test('初始是合上的，活动项停在当前选中项上', () => {
  const state = initialDropdownState(OPTIONS, '1080p');
  assert.equal(state.open, false, '未交互前不得展开');
  assert.equal(state.activeIndex, 2, '活动项 = 当前值所在下标（1080p）');
});

test('点一下开、再点一下合（点击开合）', () => {
  const opened = toggleDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p');
  assert.equal(opened.open, true);
  assert.equal(opened.activeIndex, 1, '开时活动项落在已选项，不是第 0 项');
  const closed = toggleDropdown(opened, OPTIONS, '720p');
  assert.equal(closed.open, false);
});

test('打开时没有命中值（空串/脏值）就停在第一项，不产生 -1 下标', () => {
  assert.equal(selectedIndex(OPTIONS, ''), -1);
  const opened = openDropdown(initialDropdownState(OPTIONS, ''), OPTIONS, '');
  assert.equal(opened.open, true);
  assert.equal(opened.activeIndex, 0);
});

// ---------- 方向键 ----------

test('方向键上下移动活动项', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p');
  assert.equal(moveActive(opened, 1, OPTIONS).activeIndex, 2, '↓ 从 720p 到 1080p');
  assert.equal(moveActive(opened, -1, OPTIONS).activeIndex, 0, '↑ 从 720p 到 auto');
});

test('方向键在两端钳住，不绕回（APG：边界处停住）', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, 'custom'), OPTIONS, 'custom');
  assert.equal(moveActive(opened, 1, OPTIONS).activeIndex, 3, '最后一项再 ↓ 仍停最后一项');
  const first = openDropdown(initialDropdownState(OPTIONS, 'auto'), OPTIONS, 'auto');
  assert.equal(moveActive(first, -1, OPTIONS).activeIndex, 0, '第一项再 ↑ 仍停第一项');
});

test('Home / End 跳到首尾', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p');
  assert.equal(activeEdge(opened, 'first', OPTIONS).activeIndex, 0);
  assert.equal(activeEdge(opened, 'last', OPTIONS).activeIndex, 3);
});

// ---------- Enter / Esc / 点外部 ----------

test('Enter 选中活动项、回填值并合上', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, 'auto'), OPTIONS, 'auto');
  const moved = moveActive(opened, 2, OPTIONS);
  const result = commitActive(moved, OPTIONS);
  assert.equal(result.value, '1080p', '提交的是活动项而不是原选中项');
  assert.equal(result.state.open, false, '选完必须合上');
  assert.equal(result.state.activeIndex, 2, '活动项跟到刚选中的那项');
});

test('合着的时候按 Enter 只会展开，不会顺手改值', () => {
  const closed = initialDropdownState(OPTIONS, '720p');
  const result = commitActive(closed, OPTIONS);
  assert.equal(result.state.open, true);
  assert.equal(result.value, null, '未展开时按 Enter 不得提交任何值');
});

test('Esc 合上并把活动项退回当前选中项', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p');
  const moved = moveActive(opened, 2, OPTIONS);
  const closed = closeDropdown(moved, OPTIONS, '720p');
  assert.equal(closed.open, false);
  assert.equal(closed.activeIndex, 1, '取消后活动项回到已选项，下次打开不残留');
});

test('点击外部 = Esc（同一个收口，不掉值）', () => {
  const opened = openDropdown(initialDropdownState(OPTIONS, 'custom'), OPTIONS, 'custom');
  const outside = closeDropdown(moveActive(opened, -1, OPTIONS), OPTIONS, 'custom');
  assert.deepEqual(outside, { open: false, activeIndex: 3 });
});

// ---------- 回填 ----------

test('选中项回填成触发键上的文字', () => {
  assert.equal(selectedLabel(OPTIONS, '1080p'), '高清 1080p');
  assert.equal(selectedLabel(OPTIONS, 'custom'), '自定义地址');
});

test('值不在选项里时回填空串（由调用方决定占位文案，不编一个假标签）', () => {
  assert.equal(selectedLabel(OPTIONS, 'nope'), '');
});

// ---------- 无障碍 ----------

test('触发键暴露 combobox + listbox 的 ARIA，展开时带 aria-activedescendant', () => {
  const opened = moveActive(
    openDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p'),
    1,
    OPTIONS,
  );
  const aria = triggerAria(BASE, opened, OPTIONS.length);
  assert.equal(aria.role, 'combobox');
  assert.equal(aria['aria-haspopup'], 'listbox');
  assert.equal(aria['aria-expanded'], 'true');
  assert.equal(aria['aria-controls'], `${BASE}-listbox`);
  assert.equal(aria['aria-activedescendant'], `${BASE}-option-2`);

  const closedAria = triggerAria(BASE, closeDropdown(opened, OPTIONS, '720p'), OPTIONS.length);
  assert.equal(closedAria['aria-expanded'], 'false');
  assert.equal(closedAria['aria-activedescendant'], undefined, '合上时不得指认看不到的选项');
});

test('弹层是 listbox，每项是 option，且 id 稳定可被 activedescendant 指到', () => {
  const listbox = listboxAria(BASE);
  assert.equal(listbox.role, 'listbox');
  assert.equal(listbox.id, `${BASE}-listbox`);
  assert.equal(optionDomId(BASE, 3), `${BASE}-option-3`);

  const opened = openDropdown(initialDropdownState(OPTIONS, '720p'), OPTIONS, '720p');
  const selected = selectedIndex(OPTIONS, '720p');
  const activeItem = optionAria(BASE, 1, selected);
  assert.equal(activeItem.role, 'option');
  assert.equal(activeItem.id, `${BASE}-option-1`);
  assert.equal(activeItem['aria-selected'], 'true', '当前值那项 aria-selected=true');

  const other = optionAria(BASE, 2, selected);
  assert.equal(other['aria-selected'], 'false', '仅移动活动项不算选中');
  assert.equal(
    activeDescendant(opened, BASE, OPTIONS.length),
    activeItem.id,
    'aria-activedescendant 必须等于活动项的 id（否则读屏念不到）',
  );
});

test('空选项列表不会造出 -1 的 id', () => {
  const state = openDropdown(initialDropdownState([], ''), [], '');
  assert.equal(state.activeIndex, 0);
  assert.equal(activeDescendant(state, BASE, 0), undefined);
  assert.equal(commitActive(state, []).value, null);
});

// ---------- 弹层定位（视口碰撞检测） ----------
//
// 缺陷现场：弹层原来是 `absolute`，会被**最近的有 overflow 的祖先**裁掉。
// `settings-dialog.tsx` 的弹窗是 `max-h-[90svh] overflow-y-auto`，里面放了字号档与壁纸档
// 两个 Select——靠下那个一展开就被裁，用户看到的是「点了没反应」。
//
// 修法把「算位置」抽成纯函数（这里测），组件只负责把结果摊到 style 上：
//   · 下方够 → 向下；下方不够、上方够 → 翻面向上；
//   · 上下都不够 → 取空间大的一侧，并把 maxHeight 收进视口；
//   · 任何输入都不许产 NaN（NaN 摊到 CSS 上 = 弹层消失或贴在 0 点）。

/** 把 placement 还原成「弹层顶边的视口坐标」——向下看 top，向上由 bottom 反推。 */
function panelTop(placement: DropdownPlacement, viewport: { height: number }): number {
  if (!placement.openUp) return placement.top ?? 0;
  return viewport.height - (placement.bottom ?? 0) - placement.maxHeight;
}

test('下方空间够：向下展开，top = 触发键下沿 + gap', () => {
  const vp = { width: 1200, height: 800 };
  const rect = { top: 100, bottom: 136, left: 200, width: 240 };
  const p = dropdownPlacement(rect, vp);

  assert.equal(p.openUp, false);
  assert.equal(p.top, rect.bottom + DROPDOWN_GAP, '向下展开时弹层顶边 = 触发键下沿 + gap');
  assert.equal(p.bottom, null, '向下时不该给 bottom（两条定位线同时写会打架）');
  assert.equal(p.left, rect.left, '宽度对齐触发键时左边也对齐');
  assert.equal(p.width, rect.width, '默认沿用触发键宽度');
  assert.equal(p.maxHeight, DROPDOWN_MAX_PANEL, '空间充足时封顶 = 原来的 max-h-60');
});

test('下方不够、上方够：向上翻面，bottom = 视口高 - 触发键上沿 + gap', () => {
  const vp = { width: 1200, height: 800 };
  const rect = { top: 700, bottom: 736, left: 200, width: 240 };
  const p = dropdownPlacement(rect, vp);

  assert.equal(p.openUp, true, '贴底时必须翻到触发键上方');
  assert.equal(p.bottom, vp.height - rect.top + DROPDOWN_GAP, 'bottom 是「离视口下沿多远」');
  assert.equal(p.top, null, '翻面时不该给 top');
  assert.equal(p.maxHeight, DROPDOWN_MAX_PANEL);
  assert.ok(
    panelTop(p, vp) >= DROPDOWN_MARGIN,
    `翻面后弹层顶边 ${panelTop(p, vp)} 不能顶出视口（留 ${DROPDOWN_MARGIN}px 边距）`,
  );
});

test('上下都不够：取空间大的一侧，maxHeight 收进视口', () => {
  // 矮视口 260：下方 78 / 上方 48，两边都小于下限 → 选下方 78。
  const shortVp = { width: 1200, height: 260 };
  const down = dropdownPlacement({ top: 60, bottom: 170, left: 40, width: 200 }, shortVp);
  assert.equal(down.openUp, false, '两边都不够时取空间大的那侧（这里是下方）');
  assert.equal(down.maxHeight, 78, 'maxHeight = 该侧可用空间，不再写死 240');
  assert.ok(panelTop(down, shortVp) + down.maxHeight <= shortVp.height, '弹层不得越过视口下沿');

  // 矮视口 200：下方 58 / 上方 88 → 选上方 88。
  const vp = { width: 1200, height: 200 };
  const up = dropdownPlacement({ top: 100, bottom: 130, left: 40, width: 200 }, vp);
  assert.equal(up.openUp, true, '上方空间更大时必须向上翻');
  assert.equal(up.maxHeight, 88);
  assert.ok(panelTop(up, vp) >= DROPDOWN_MARGIN);
  assert.ok(panelTop(up, vp) + up.maxHeight <= vp.height);
});

test('宽度对齐触发键但不许顶出视口右边界', () => {
  const rect = { top: 100, bottom: 136, left: 350, width: 240 };
  const p = dropdownPlacement(rect, { width: 400, height: 800 });
  assert.ok(p.left >= 0);
  assert.ok(p.left + p.width <= 400, '弹层右边缘必须收进视口（触发键贴右墙时左移而不是溢出）');
  assert.equal(p.left, 400 - DROPDOWN_MARGIN - 240);

  // 比触发键还窄的视口：宽度得跟着收，不能整块溢出。
  const narrow = dropdownPlacement(rect, { width: 100, height: 800 });
  assert.ok(narrow.width > 0, '再窄也要留下能看的宽度');
  assert.ok(narrow.left >= 0 && narrow.left + narrow.width <= 100);
});

test('边界输入不产 NaN：视口高 0 / rect 越界 / NaN 一律退回向下并保住下限', () => {
  const cases = [
    ['视口高 0', { top: 100, bottom: 136, left: 200, width: 240 }, { width: 1200, height: 0 }],
    ['rect 掉到视口下方', { top: 900, bottom: 936, left: 200, width: 240 }, { width: 1200, height: 800 }],
    ['全 NaN', { top: NaN, bottom: NaN, left: NaN, width: NaN }, { width: NaN, height: NaN }],
  ] as const;

  for (const [label, rect, vp] of cases) {
    const p = dropdownPlacement(rect, vp);
    for (const [name, value] of [
      ['top', p.top],
      ['left', p.left],
      ['width', p.width],
      ['maxHeight', p.maxHeight],
    ] as const) {
      assert.ok(Number.isFinite(value), `${label}：${name} 不得是 ${String(value)}（NaN 摊到 CSS = 弹层消失）`);
    }
    assert.equal(p.openUp, false, `${label}：退化输入退回向下`);
    assert.equal(p.bottom, null, `${label}：退回向下时不再给 bottom`);
    assert.ok(
      p.maxHeight >= DROPDOWN_MIN_PANEL,
      `${label}：maxHeight 要有合理下限（实得 ${p.maxHeight}，下限 ${DROPDOWN_MIN_PANEL}）`,
    );
    assert.ok(p.width >= 0 && p.left >= 0, `${label}：宽度/左边不得为负`);
  }
});

test('扫掠：可用视口下算出的弹层四边都落在视口内', () => {
  let checked = 0;
  for (const height of [200, 360, 480, 800, 1080]) {
    for (const width of [320, 800, 1200]) {
      for (const top of [-20, 0, 24, 200, 430, 700, 760]) {
        for (const anchorWidth of [80, 240, 400]) {
          const vp = { width, height };
          const rect = { top, bottom: top + 36, left: 350, width: anchorWidth };
          const p = dropdownPlacement(rect, vp);
          const topEdge = panelTop(p, vp);
          const where = `${JSON.stringify(rect)} @ ${JSON.stringify(vp)} → ${JSON.stringify(p)}`;

          assert.ok(Number.isFinite(topEdge), `顶边不是有限数：${where}`);
          assert.ok(p.left >= 0, `左边越界：${where}`);
          assert.ok(p.left + p.width <= vp.width, `右边越界：${where}`);
          assert.ok(topEdge >= 0, `顶边越界：${where}`);
          assert.ok(topEdge + p.maxHeight <= vp.height, `下边越界：${where}`);
          checked += 1;
        }
      }
    }
  }
  assert.ok(checked >= 300, `扫掠样本只有 ${checked} 组，覆盖不够`);
});

// ---------- 组件侧契约（静态读源码） ----------
//
// .tsx 在 node --test 里渲染不了（仓库没有 jsdom，也不许为此装包），所以「卸载要清理」
// 这条用**读源码的结构断言**锁：监听挂了几处、移除几处、是否只在展开时挂。
// 同一手法在 `components/appearance/layering.test.ts` 已有先例（portal 契约）。

const HERE = dirname(fileURLToPath(import.meta.url));
const WEBUI = join(HERE, '..', '..');
const FIELD = readFileSync(join(WEBUI, 'src', 'components', 'appearance', 'field.tsx'), 'utf8');

interface ListenerCall {
  readonly type: string;
  readonly handler: string;
  readonly flags: string;
}

/** 抽 `window.add/removeEventListener('type', handler[, flags])` 三元组。 */
function listenerCalls(source: string, kind: 'add' | 'remove'): ListenerCall[] {
  const pattern = new RegExp(
    `window\\.${kind}EventListener\\(\\s*(['"])([a-zA-Z]+)\\1\\s*,\\s*([A-Za-z0-9_$]+)\\s*(?:,\\s*([^)]*?))?\\s*\\)`,
    'g',
  );
  return [...source.matchAll(pattern)].map((m) => ({
    type: m[2],
    handler: m[3],
    flags: (m[4] ?? '').trim(),
  }));
}

const listenerKey = (call: ListenerCall): string =>
  `${call.type}|${call.handler}|${call.flags}`;

interface EffectBlock {
  readonly body: string;
  readonly deps: string;
}

/** 抽出所有 `useEffect(() => { ... }, [...])` 块（花括号配平）。 */
function effectBlocks(source: string): EffectBlock[] {
  const marker = 'useEffect(() => {';
  const blocks: EffectBlock[] = [];
  let from = 0;
  for (;;) {
    const start = source.indexOf(marker, from);
    if (start < 0) return blocks;
    let depth = 0;
    let end = -1;
    for (let i = start + marker.length - 1; i < source.length; i += 1) {
      if (source[i] === '{') depth += 1;
      else if (source[i] === '}') {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    assert.ok(end > start, 'useEffect 花括号不配平——静态契约无从判起');
    const deps = /^\s*,\s*\[([^\]]*)\]/.exec(source.slice(end + 1));
    blocks.push({ body: source.slice(start, end + 1), deps: deps ? deps[1] : '' });
    from = end + 1;
  }
}

test('field.tsx：scroll / resize 监听必须成对移除（同一 handler、同一 capture 标志）', () => {
  const adds = listenerCalls(FIELD, 'add');
  const removes = listenerCalls(FIELD, 'remove');
  const addKeys = adds.map(listenerKey).sort();
  const removeKeys = removes.map(listenerKey).sort();

  for (const type of ['scroll', 'resize']) {
    assert.ok(
      adds.some((call) => call.type === type),
      `field.tsx 里没有 window 的 ${type} 监听——弹层漂移时不会自己收起来`,
    );
  }
  assert.deepEqual(
    removeKeys,
    addKeys,
    `监听与移除必须一一对应（add=${JSON.stringify(addKeys)} / remove=${JSON.stringify(removeKeys)}）。` +
      '对不上 = 卸载后还留着监听，卸载的组件被回调 setState。',
  );

  const scrollAdd = adds.find((call) => call.type === 'scroll');
  assert.ok(scrollAdd, '找不到 scroll 监听');
  assert.equal(scrollAdd.flags, 'true', 'scroll 必须 capture: true，否则内层滚动容器的事件根本不上浮到 window');
  const scrollRemove = removes.find((call) => call.type === 'scroll');
  assert.equal(scrollRemove?.flags, 'true', '移除时的 capture 标志必须与注册时一致，否则摘不掉');
});

test('field.tsx：两组监听只在 state.open 为真时挂（guard + deps 双证）', () => {
  const block = effectBlocks(FIELD).find((candidate) =>
    listenerCalls(candidate.body, 'add').some((call) => call.type === 'scroll'),
  );
  assert.ok(block, 'scroll / resize 监听必须写在某个 useEffect 里，否则无法随开合挂/卸');

  assert.match(
    block.body,
    /if \(!state\.open\) return;/,
    `挂监听的同一个 effect 必须先判 state.open：\n${block.body.slice(0, 400)}`,
  );
  for (const type of ['scroll', 'resize']) {
    assert.ok(
      listenerCalls(block.body, 'add').some((call) => call.type === type),
      `同一个 effect 里要有 ${type}（两组合一份 cleanup，不许各挂各的）`,
    );
  }
  assert.match(block.deps, /state\.open/, `effect 依赖必须含 state.open（实得 [${block.deps}]）`);
});

test('field.tsx：弹层 portal 到 body 并用视口坐标定位（fixed 会被玻璃祖先吃掉）', () => {
  assert.match(
    FIELD,
    /createPortal\(/,
    '弹层必须 portal 到 body：`.glass-panel` / `window` 两族材质带 backdrop-filter，' +
      '它们会成为 fixed 的包含块，弹层会退回「相对那块玻璃定位」并继续被 overflow 裁',
  );
  assert.match(FIELD, /document\.body/, 'portal 的目标必须是 body（放在玻璃容器里等于没 portal）');
  assert.match(FIELD, /className='fixed z-50'/, '弹层外层要用 fixed 定位（配合 portal 才是视口坐标）');
  assert.doesNotMatch(
    FIELD,
    /absolute left-0 right-0/,
    '旧的 absolute 定位必须撤掉——它就是被 overflow 祖先裁掉的那一版',
  );
  assert.match(FIELD, /maxHeight: placement\.maxHeight/, '算出来的 maxHeight 要真的落到 ul 上');
});
