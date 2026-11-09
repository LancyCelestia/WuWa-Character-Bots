import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  BUBBLE_COLORS,
  EMPTY_FIELD,
  type Bubble,
  type Pop,
  burstAt,
  fieldCount,
  respawn,
  spawnBubble,
  stepBubble,
  stepPops,
} from './bubble-field.ts';

/**
 * 气泡场（参考站 daniya.top `main.js` 第 219-352 行）。
 * 逐条对照它 `spawn` / `draw` / `burst` 三个函数的算法，但**抽成纯函数**：
 * 参考站把状态塞在闭包里靠 rAF 推进，这里只算「下一帧状态」，画由组件层做。
 * 这样算法的每一个常数都能被断言，而不是靠肉眼看截图。
 *
 * 参考站原常数（逐字）：
 *   r = 2 + rand*10；vy = -(0.16 + rand*0.55)；vx = (rand-0.5)*0.28
 *   wobA = 0.25 + rand*0.8；wobF = 0.4 + rand*0.9；a = 0.05 + rand*0.3
 *   收回条件：y + r < -30 或 life > 5200；爆点 r = 34 + rand*30、a = 0.5
 *   粒子数：min(74, max(26, W / 20))
 */

/** 常量伪随机：让「随机」可复现（参考站用 Math.random()，测试不能这么干）。 */
const fixed = (v: number) => () => v;

const EPS = 1e-9;

test('spawnBubble：半径 / 速度 / 摆动 / 透明度都落在参考站的取值带内', () => {
  const b = spawnBubble(fixed(0), 1440, 900, true);
  assert.equal(b.r, 2);
  assert.equal(b.vy, -0.16);
  assert.equal(b.vx, -0.14);
  assert.equal(b.a, 0.05);
  assert.equal(b.wobA, 0.25);
  assert.equal(b.wobF, 0.4);
  // initial=true 时 y 在视口内；false 时从底部之下 40px 进（参考站 `H + 40`）。
  assert.ok(b.y >= 0 && b.y <= 900);
  assert.equal(spawnBubble(fixed(0), 1440, 900, false).y, 940);
});

test('spawnBubble：颜色取自参考站四色盘（海蓝 / 紫 / 暖橙 / 冷白）', () => {
  assert.deepEqual(BUBBLE_COLORS, [
    [142, 217, 236],
    [185, 168, 255],
    [255, 185, 138],
    [210, 228, 245],
  ]);
  // 颜色下标 = floor(rand * 4)：0 / 0.25 / 0.5 / 0.75 各取一色，且不出盘外。
  for (let i = 0; i < 4; i += 1) {
    const b = spawnBubble(fixed(i / 4), 800, 600, true);
    assert.deepEqual(b.c, BUBBLE_COLORS[i]);
  }
});

test('stepBubble：纵向匀速上升、横向正弦摆动（参考站 draw 里的两条位移）', () => {
  const base: Bubble = {
    x: 100, y: 500, r: 6, vy: -0.5, vx: 0.1, seed: 0, wobA: 0.5, wobF: 1, a: 0.2, c: BUBBLE_COLORS[0], life: 0,
  };
  const next = stepBubble(base, 0);
  // y += vy；x += vx + sin(t*0.008*wobF + seed)*wobA*0.14，t=0 ⇒ sin(0)=0 ⇒ 只走 vx。
  assert.equal(next.y, 499.5);
  assert.ok(Math.abs(next.x - 100.1) < EPS);
  assert.equal(next.life, 1);
  // 推进 t 之后横向摆动才出现。
  const later = stepBubble(base, 200);
  assert.ok(later.x > 100.1);
});

test('stepBubble：底 90px / 顶 120px 内淡入淡出（参考站两条 alpha 衰减）', () => {
  const b: Bubble = {
    x: 0, y: 860, r: 4, vy: 0, vx: 0, seed: 0, wobA: 0, wobF: 1, a: 0.4, c: BUBBLE_COLORS[0], life: 0,
  };
  // 视口高 900，y=860 ⇒ (900-860)/90 ≈ 0.444。
  const nearBottom = stepBubble(b, 0, 900);
  assert.ok(Math.abs(nearBottom.alpha - 0.4 * (40 / 90)) < 1e-6);
  // y=60 ⇒ 60/120 = 0.5。
  assert.ok(Math.abs(stepBubble({ ...b, y: 60 }, 0, 900).alpha - 0.2) < 1e-6);
  // 中间区域原样；不给视口高时也不做衰减。
  assert.equal(stepBubble({ ...b, y: 500 }, 0, 900).alpha, 0.4);
  assert.equal(stepBubble({ ...b, y: 860 }, 0).alpha, 0.4);
});

test('respawn：出顶越过阈值或寿命超 5200 帧才重生（参考站两条回收条件）', () => {
  const dead: Bubble = {
    x: 10, y: -40, r: 3, vy: -1, vx: 0, seed: 0, wobA: 0, wobF: 1, a: 0.2, c: BUBBLE_COLORS[0], life: 5,
  };
  // y + r < -30 ⇒ -40 + 3 = -37 < -30 ⇒ 重生。
  assert.equal(respawn(dead), true);
  // 刚出顶但还没越过阈值 ⇒ 不重生。
  assert.equal(respawn({ ...dead, y: -20 }), false);
  // 寿命到顶 ⇒ 重生（无论位置）。
  assert.equal(respawn({ ...dead, y: 500, life: 5201 }), true);
  assert.equal(respawn({ ...dead, y: 500, life: 5200 }), false);
});

test('burstAt：点击爆点半径 34–64、初始半径即当前半径（参考站 burst 的常数）', () => {
  const burst = burstAt(300, 400, fixed(0.5));
  assert.equal(burst.x, 300);
  assert.equal(burst.y, 400);
  assert.equal(burst.r, 34 + 0.5 * 30);
  // 刚生成：当前半径 = 初始半径（参考站里 r 是常数，扩张量由 life 现算）。
  assert.equal(burst.radius, burst.r);
  assert.equal(burst.life, 0);
  // 环的透明度按 0.34 * (1 - life) 衰减（参考站 draw 里的 pops 臂）。
  assert.equal(burst.alpha, 0.34);
});

test('stepPops：爆环约 22 帧后消失，半径按 easeOutCubic 扩张', () => {
  let pops: Pop[] = [burstAt(0, 0, fixed(0))];
  const r0 = pops[0].r;
  pops = stepPops(pops);
  assert.equal(pops.length, 1);
  // 半径 = r * (1 + e * 1.7)，e = 1 - (1-life)^3；life 已推进到 0.045。
  assert.ok(pops[0].radius > r0);
  // 推进到寿终：life 每帧 +0.045，1/0.045 ≈ 22.2 帧。
  for (let i = 0; i < 30; i += 1) pops = stepPops(pops);
  assert.equal(pops.length, 0);
});

test('fieldCount：参考站 min(74,max(26,W/20))；宽度无效时退回下限', () => {
  assert.equal(fieldCount(1440), 72);
  assert.equal(fieldCount(520), 26);
  assert.equal(fieldCount(99999), 74);
  // NaN / 0 / 负值不该崩，也不该给出 0 颗。
  assert.equal(fieldCount(0), 26);
  assert.equal(fieldCount(Number.NaN), 26);
  assert.equal(fieldCount(-100), 26);
});

test('EMPTY_FIELD 是不可变的空场，避免每次渲染造新数组', () => {
  assert.ok(Array.isArray(EMPTY_FIELD.bubbles));
  assert.ok(Array.isArray(EMPTY_FIELD.pops));
  assert.equal(EMPTY_FIELD.bubbles.length, 0);
});
