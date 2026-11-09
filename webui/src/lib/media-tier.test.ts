import assert from 'node:assert/strict';
import { test } from 'node:test';

import { pickVideoTier, videoSrcFor } from './media-tier.ts';

/**
 * 背景视频档位（UI3 性能预算）。判据是「带宽花在哪」：
 * 12.9 MB × 1587 次 = 20 GB ⇒ 原片必须永远不能被自动拉下来。
 */

test('pickVideoTier：关掉壁纸或省流量模式时一个字节都不拉', () => {
  assert.equal(pickVideoTier(2560, { wallpaperEnabled: false }), null);
  assert.equal(pickVideoTier(2560, { wallpaperEnabled: false, saveData: false }), null);
  assert.equal(pickVideoTier(2560, { saveData: true }), null);
  // 省流量优先于一切宽度：宽屏也得让路。
  assert.equal(pickVideoTier(3840, { saveData: true }), null);
});

test('pickVideoTier：2g/3g 一律 720p（4.9 MB 在 3G 上要十几秒）', () => {
  assert.equal(pickVideoTier(2560, { effectiveType: 'slow-2g' }), '720p');
  assert.equal(pickVideoTier(2560, { effectiveType: '2g' }), '720p');
  assert.equal(pickVideoTier(2560, { effectiveType: '3g' }), '720p');
  // 4g / 没有 connection API（Safari/Firefox）= 不降档。
  assert.equal(pickVideoTier(2560, { effectiveType: '4g' }), '1080p');
  assert.equal(pickVideoTier(2560, {}), '1080p');
});

test('pickVideoTier：按**视口宽度**分档，边界值 900 走 1080p', () => {
  assert.equal(pickVideoTier(899, {}), '720p');
  assert.equal(pickVideoTier(900, {}), '1080p');
  assert.equal(pickVideoTier(1920, {}), '1080p');
  // 手机竖屏（390）永远 720p。
  assert.equal(pickVideoTier(390, {}), '720p');
});

test('videoSrcFor：档位与文件名一一对应，null 不产路径', () => {
  assert.equal(videoSrcFor('720p'), '/console/assets/bg-720p.mp4');
  assert.equal(videoSrcFor('1080p'), '/console/assets/bg-1080p.mp4');
  assert.equal(videoSrcFor(null), null);
});
