import assert from 'node:assert/strict';
import { test } from 'node:test';

import { routePathFor, withBase } from './route-path.ts';

/**
 * `/console/*` 真路径 → 路由路径（W12 UI3，browser history 版）。
 *
 * 这张表就是「叠叠乐 URL」的判据：UI2 把真路径折成 hash，地址栏于是出现
 * `/console/#/console`；UI3 起地址栏里**不许再出现 `#`**，路由直接认真路径。
 */

test('routePathFor：/console 与 /console/ 都落到总览（用户裁定「默认打开总览」）', () => {
  assert.equal(routePathFor('/console'), '/');
  assert.equal(routePathFor('/console/'), '/');
  assert.equal(routePathFor('/console//'), '/');
});

test('routePathFor：已入册子路径原样成路由路径（不再折 hash）', () => {
  assert.equal(routePathFor('/console/calls'), '/calls');
  assert.equal(routePathFor('/console/logs'), '/logs');
  assert.equal(routePathFor('/console/config'), '/config');
  assert.equal(routePathFor('/console/knowledge/'), '/knowledge');
  assert.equal(routePathFor('/console/console'), '/console');
  // 总览的规范真路径也回总览（旧映射表那一行不失效）。
  assert.equal(routePathFor('/console/overview'), '/');
});

test('routePathFor：未入册子路径原样交给路由表（由 notFound 出友好提示，不静默改总览）', () => {
  assert.equal(routePathFor('/console/随便什么'), '/随便什么');
  assert.equal(routePathFor('/console/nope'), '/nope');
});

test('routePathFor：非 /console 族一律不动（前缀碰撞不得误收）', () => {
  assert.equal(routePathFor('/'), '/');
  assert.equal(routePathFor('/calls'), '/calls');
  assert.equal(routePathFor('/consolex'), '/consolex');
  assert.equal(routePathFor('/api/v1/console'), '/api/v1/console');
  assert.equal(routePathFor(''), '/');
});

test('withBase：总览在 base 根下，其余拼到 base 后', () => {
  assert.equal(withBase('/', '/console/'), '/console/');
  assert.equal(withBase('/calls', '/console/'), '/console/calls');
  assert.equal(withBase('calls', '/console/'), '/console/calls');
  assert.equal(withBase('/calls', '/'), '/calls');
});
