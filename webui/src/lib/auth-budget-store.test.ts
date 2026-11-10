// 单飞探测的出口：一发 2xx 之后必须放开并发，否则首屏 7 个查询只有第一发能出去，
// 其余全部被本地闸判成 429（"服务端正在限速"，但其实一个 429 都没发生）。
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  __resetAuthBudgetForTest,
  acquireAuthSlot,
  beforeAuthRequest,
  noteAuthFailure,
  noteAuthSuccess,
} from './auth-budget-store.ts';

test('探针在飞时，后续请求标记为 probing 而不是限流', () => {
  __resetAuthBudgetForTest();
  assert.equal(beforeAuthRequest().allowed, true, '未证明的凭据允许第一发探测');
  const second = beforeAuthRequest();
  assert.equal(second.allowed, false);
  assert.equal(second.reason, 'probing');
  assert.equal(second.waitMs, 0);
});

test('2xx 之后并发请求不再互相挤占预算', () => {
  __resetAuthBudgetForTest();
  assert.equal(beforeAuthRequest().allowed, true);
  noteAuthSuccess();
  for (let i = 0; i < 10; i += 1) {
    assert.equal(beforeAuthRequest().allowed, true, `第 ${i + 1} 发并发请求应放行`);
  }
});

test('并发的第二个查询排队等探针，2xx 后一起放行', async () => {
  __resetAuthBudgetForTest();
  const first = await acquireAuthSlot();
  assert.equal(first.allowed, true, '第一发当探针');

  const pending = acquireAuthSlot();
  setTimeout(() => noteAuthSuccess(), 5);
  const second = await pending;

  assert.equal(second.allowed, true, '探针 2xx 后排队请求必须放行，不能伪造 429');
  assert.equal(second.waitMs, 0);
});

test('探针失败时排队请求拿到真实冷却，不重复撞墙', async () => {
  __resetAuthBudgetForTest();
  const first = await acquireAuthSlot();
  assert.equal(first.allowed, true);

  const pending = acquireAuthSlot();
  setTimeout(() => noteAuthFailure('unauthorized'), 5);
  const second = await pending;

  assert.equal(second.allowed, false);
  assert.equal(second.reason, 'cooldown');
  assert.ok(second.waitMs > 0, '必须给真实等待时间，不能是 0 秒');
});
