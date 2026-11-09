import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type Box, indicatorBox } from './indicator-box.ts';

/**
 * 导航活跃指示器（参考站 daniya.top `main.js` 的 `movePill` / `activateForm`）。
 *
 * 参考站的做法（逐字）：
 *   `pill.style.left  = link.offsetLeft + 'px'`
 *   `pill.style.width = link.offsetWidth + 'px'`
 * 分段切换器则用 `transform: translateX(btn.offsetLeft - 4)`。
 *
 * 本仓的一处**有意改写**：参考站动 `left` / `width`，两者都触发 layout。
 * 这里统一成 `translateX/translateY` + `width/height`，由调用方决定写哪个属性；
 * 换算本身是纯函数，可断言。
 */

const CONTAINER: Box = { x: 0, y: 0, width: 260, height: 400 };
const box = (x: number, y: number, width: number, height: number): Box => ({ x, y, width, height });

test('贴住链接的 x / y / 宽 / 高', () => {
  assert.deepEqual(indicatorBox(box(120, 8, 64, 32), CONTAINER), {
    translateX: 120,
    translateY: 8,
    width: 64,
    height: 32,
  });
});

test('坐标是相对容器的偏移，容器自身位置不参与', () => {
  const offset: Box = { x: 500, y: 300, width: 260, height: 400 };
  // 链接与容器同原点 ⇒ 偏移 0，不是 500。
  assert.deepEqual(indicatorBox(box(500, 300, 260, 44), offset), {
    translateX: 0,
    translateY: 0,
    width: 260,
    height: 44,
  });
});

test('取整到整数 px：小数会让 1px 描边糊成两像素', () => {
  assert.deepEqual(indicatorBox(box(10.4, 20.6, 63.5, 31.5), CONTAINER), {
    translateX: 10,
    translateY: 21,
    width: 64,
    height: 32,
  });
});

test('链接尺寸为 0（aria-hidden 分隔件 / 未挂载）→ null，不接管指示器', () => {
  assert.equal(indicatorBox(box(0, 0, 0, 0), CONTAINER), null);
  assert.equal(indicatorBox(box(0, 0, 10, 0), CONTAINER), null);
});

test('容器尺寸为 0（display:none）→ null，不写 NaN', () => {
  assert.equal(indicatorBox(box(0, 0, 10, 10), box(0, 0, 0, 0)), null);
});

test('NaN 输入不被放过（布局未定案时 offsetWidth 可能读成 NaN）', () => {
  assert.equal(indicatorBox(box(Number.NaN, 0, 10, 10), CONTAINER), null);
  assert.equal(indicatorBox(box(0, 0, 10, 10), box(0, 0, Number.NaN, 10)), null);
});
