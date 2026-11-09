import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DEFAULT_MIN_INTERVAL_MS,
  AUTH_LOCKOUT_BUDGET,
  AUTH_STATES,
  classifyAuthFailure,
  initialAuthBudget,
  spendAuthBudget,
  type AuthState,
} from './auth-budget.ts';

/**
 * 鉴权失败预算（W18 根因 #1 的守卫）。
 *
 * 现场证据（`scripts/request-audit.mjs` 实测，无令牌 /console/ 一次加载）：
 *   +209ms 401 health      +210ms 401 status/bot      +221ms 401 stats/calls
 *   +224ms 401 stats/calls(7d)  +228ms 401 stats/tokens
 *   +229ms 429 stats/latency    +238ms 429 affinity/board
 *   … 共 10 发：5 发 401 + 5 发 429
 * 后端 `_app.py:172` 是「先查冷却 → 再认证 → 失败 +1」，5 连败即锁 60 秒。
 * 也就是说**首屏一次乐观加载就把管理面锁死了**，而锁死期间用户即使粘贴正确令牌也会被 429 打回。
 *
 * 修法不是调后端常量（`FAILURE_MAX_COUNT=5` 是安全参数，不许动），而是在前端建一道
 * 「在没把握时不要发」的预算闸：只有真正持有令牌才发鉴权请求；一次失败后立刻收敛。
 */

const TOKEN = { hasToken: true } as const;

test('没有令牌时不发鉴权请求——这是首屏锁死的直接来源', () => {
  // 判定不看令牌内容，看的是「当前预算是否允许发一发」。
  const fresh = initialAuthBudget();
  assert.equal(spendAuthBudget(fresh, { hasToken: false }).allowed, false);
  assert.equal(spendAuthBudget(fresh, { hasToken: true }).allowed, true);
});

test('预算 5 发：第 6 发起拒绝（与后端 FAILURE_MAX_COUNT 对齐但不是同一个量）', () => {
  assert.equal(AUTH_LOCKOUT_BUDGET, 5);
  let budget = initialAuthBudget();
  for (let i = 0; i < 5; i += 1) {
    const next = spendAuthBudget(budget, TOKEN);
    assert.equal(next.allowed, true, `第 ${i + 1} 发应当放行`);
    budget = next.budget;
  }
  const blocked = spendAuthBudget(budget, TOKEN);
  assert.equal(blocked.allowed, false, '第 6 发必须拦住');
  assert.equal(blocked.budget.remaining, 0);
});

test('失败一次就立刻停：不等攒满 5 次（攒满时后端已经锁了）', () => {
  const first = spendAuthBudget(initialAuthBudget(), TOKEN);
  const afterFail = classifyAuthFailure(first.budget, 'unauthorized');
  assert.equal(afterFail, 'halt', '401 后必须整体停发，不再逐个端点撞');
  // 语义态要让消费方知道「别再重试了」。
  assert.equal(classifyAuthFailure(first.budget, 'rate-limited'), 'halt');
  assert.equal(classifyAuthFailure(first.budget, 'not-provisioned'), 'halt');
  // 非鉴权类错误（网络抖动 / 5xx）不消耗鉴权预算，也不触发全局停发。
  assert.equal(classifyAuthFailure(first.budget, 'transient'), 'continue');
});

test('冷却窗：拦下之后要能在一段时间后自愈，不是永久死锁', () => {
  const now = Date.now();
  const cooling: AuthState = { remaining: 0, haltedAt: now - 1_000, cooldownMs: 30_000 };
  assert.equal(spendAuthBudget(cooling, TOKEN).allowed, false, '冷却中不放行');
  const expired: AuthState = { remaining: 0, haltedAt: now - 31_000, cooldownMs: 30_000 };
  const r = spendAuthBudget(expired, TOKEN);
  assert.equal(r.allowed, true, '冷却过期后放行');
  assert.equal(r.budget.remaining, AUTH_LOCKOUT_BUDGET - 1, '复活后扣掉这一发，其余额度还回来');
});

test('拿不到令牌就不探测：空令牌不算「有一发」', () => {
  const emptied = { hasToken: false as const };
  const r = spendAuthBudget({ remaining: 5, haltedAt: null, cooldownMs: DEFAULT_MIN_INTERVAL_MS }, emptied);
  assert.equal(r.allowed, false);
  assert.equal(r.budget.remaining, 5, '不发就不该扣预算');
});

test('AUTH_STATES 覆盖 hook 里的每一档（漏一档就会静默走错分支）', () => {
  assert.deepEqual([...AUTH_STATES].sort(), ['credential-only', 'not-provisioned', 'rate-limited', 'transient', 'unauthorized']);
});
