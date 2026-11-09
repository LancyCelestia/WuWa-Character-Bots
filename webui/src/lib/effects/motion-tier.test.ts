import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  MAX_PARTICLE_COUNT,
  MIN_PARTICLE_COUNT,
  type MotionFacts,
  particleBudget,
  pickParticlePath,
  resolveMotionTier,
  shouldUseCustomCursor,
} from './motion-tier.ts';

const BASE: MotionFacts = {
  prefersReduced: false,
  userDisabled: false,
  saveData: false,
  hardwareConcurrency: 16,
  isTouchOnly: false,
  hasWebGL2: true,
  viewportWidth: 1440,
};

/**
 * 动效档位（参考站 daniya.top 的判据）：它的 `main.js` 只在三处读环境——
 * `prefers-reduced-motion`、`(hover: hover) and (pointer: fine)`、`devicePixelRatio`。
 * 我们多两条业务约束：外观页的动效总开关、以及省流量模式（2C2T / 2G RAM / 20GB 月流量）。
 */

test('resolveMotionTier：系统减少动效 → off（压过一切业务开关）', () => {
  assert.equal(resolveMotionTier({ ...BASE, prefersReduced: true }), 'off');
  // 即使用户自己把动效打开，系统级偏好仍然赢——这是无障碍，不是偏好。
  assert.equal(resolveMotionTier({ ...BASE, prefersReduced: true, userDisabled: false }), 'off');
});

test('resolveMotionTier：用户关掉动效 → off；省流量 → lite', () => {
  assert.equal(resolveMotionTier({ ...BASE, userDisabled: true }), 'off');
  assert.equal(resolveMotionTier({ ...BASE, saveData: true }), 'lite');
});

test('resolveMotionTier：弱机 / 窄屏降 lite（≤2 核或 <900px）', () => {
  assert.equal(resolveMotionTier({ ...BASE, hardwareConcurrency: 2 }), 'lite');
  assert.equal(resolveMotionTier({ ...BASE, hardwareConcurrency: 1 }), 'lite');
  assert.equal(resolveMotionTier({ ...BASE, viewportWidth: 900 }), 'lite');
  // 边界：901px 且 3 核 → full。
  assert.equal(resolveMotionTier({ ...BASE, viewportWidth: 901, hardwareConcurrency: 3 }), 'full');
});

test('resolveMotionTier：正常机器 → full', () => {
  assert.equal(resolveMotionTier(BASE), 'full');
  // 触屏不影响档位——只影响自定义光标与 3D 倾斜。
  assert.equal(resolveMotionTier({ ...BASE, isTouchOnly: true }), 'full');
});

test('pickParticlePath：全档有 WebGL2 走 webgl，否则 canvas2d，off 一律不画', () => {
  assert.equal(pickParticlePath(BASE), 'webgl');
  assert.equal(pickParticlePath({ ...BASE, hasWebGL2: false }), 'canvas2d');
  // lite 档不赌 GPU：气泡是氛围，2D 更稳。
  assert.equal(pickParticlePath({ ...BASE, saveData: true }), 'canvas2d');
  assert.equal(pickParticlePath({ ...BASE, prefersReduced: true }), 'none');
  assert.equal(pickParticlePath({ ...BASE, userDisabled: true }), 'none');
});

test('particleBudget：参考站公式 min(74,max(26,W/20))，lite 减半、off 归零', () => {
  // 参考站实测：1440 宽 → 72。
  assert.equal(particleBudget(BASE), 72);
  assert.equal(particleBudget({ ...BASE, viewportWidth: 360 }), MIN_PARTICLE_COUNT);
  assert.equal(particleBudget({ ...BASE, viewportWidth: 99999 }), MAX_PARTICLE_COUNT);
  // lite 档 = 基数一半（1440 宽基数 72 → 36），但下限仍是 26。
  assert.equal(particleBudget({ ...BASE, saveData: true }), 36);
  assert.equal(particleBudget({ ...BASE, saveData: true, viewportWidth: 400 }), MIN_PARTICLE_COUNT);
  assert.equal(particleBudget({ ...BASE, prefersReduced: true }), 0);
});

test('particleBudget 上界可被外观页调低，但绝不越过硬顶', () => {
  assert.equal(particleBudget({ ...BASE, viewportWidth: 1920 }, 40), 40);
  // 传入比硬顶还大 → 夹到硬顶，不是照抄。
  assert.equal(particleBudget({ ...BASE, viewportWidth: 1920 }, 9999), MAX_PARTICLE_COUNT);
  // 0 = 显式关闭。
  assert.equal(particleBudget({ ...BASE, viewportWidth: 1920 }, 0), 0);
});

test('shouldUseCustomCursor：触屏 / 减少动效 / 窄屏都不换光标', () => {
  assert.equal(shouldUseCustomCursor(BASE), true);
  assert.equal(shouldUseCustomCursor({ ...BASE, isTouchOnly: true }), false);
  assert.equal(shouldUseCustomCursor({ ...BASE, prefersReduced: true }), false);
  assert.equal(shouldUseCustomCursor({ ...BASE, viewportWidth: 700 }), false);
});
