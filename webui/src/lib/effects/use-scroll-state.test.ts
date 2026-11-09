import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  HERO_PARALLAX_SPAN,
  NAV_SCROLLED_AT,
  heroParallax,
  scrollProgress,
} from './use-scroll-state.ts';

/**
 * 滚动进度与 hero 视差（参考站 daniya.top `main.js` 第 62-76 行的两条公式，逐字）。
 *
 *   `bar.style.width = (max > 0 ? Math.min(1, y / max) * 100 : 0) + '%'`
 *     max = documentElement.scrollHeight - window.innerHeight
 *   `hero.style.setProperty('--hp', Math.min(1, y / (innerHeight * 0.9)))`
 *   `nav.classList.toggle('is-scrolled', y > 24)`
 *
 * 这里把三条公式抽成纯函数，边界（max ≤ 0、innerHeight 为 0、y 为负）都能被断言。
 */

test('scrollProgress：短页面（无需滚动）恒为 0，不是 NaN', () => {
  // max = 500 - 800 = -300 ≤ 0
  assert.equal(scrollProgress(0, 500, 800), 0);
  assert.equal(scrollProgress(120, 500, 800), 0);
  // 恰好等高的页面同样为 0（max = 0）。
  assert.equal(scrollProgress(0, 800, 800), 0);
});

test('scrollProgress：中段线性、两端夹紧到 [0,1]', () => {
  // max = 2000 - 800 = 1200
  assert.equal(scrollProgress(0, 2000, 800), 0);
  assert.equal(scrollProgress(600, 2000, 800), 0.5);
  assert.equal(scrollProgress(1200, 2000, 800), 1);
  // 越界（回弹滚动会给出负数 / 超出）都夹紧。
  assert.equal(scrollProgress(-50, 2000, 800), 0);
  assert.equal(scrollProgress(9999, 2000, 800), 1);
});

test('heroParallax：分母是 innerHeight × 0.9（参考站原文）', () => {
  assert.equal(HERO_PARALLAX_SPAN, 0.9);
  // 分母 = 1000 × 0.9 = 900
  assert.equal(heroParallax(0, 1000), 0);
  assert.equal(heroParallax(450, 1000), 0.5);
  assert.equal(heroParallax(900, 1000), 1);
  assert.equal(heroParallax(1800, 1000), 1);
});

test('heroParallax：innerHeight 为 0（打印 / 隐藏容器）时不除零', () => {
  assert.equal(heroParallax(100, 0), 0);
});

test('NAV_SCROLLED_AT 是 24（参考站原文 y > 24）', () => {
  assert.equal(NAV_SCROLLED_AT, 24);
});
