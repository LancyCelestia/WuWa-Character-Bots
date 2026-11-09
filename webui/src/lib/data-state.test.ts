import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { shouldRetryQuery, shouldShowSkeleton, type DataPhase } from './data-state.ts';

// 总览首屏「六张卡全挂骨架条」两条判据（S 席，Playwright 实测：27 根骨架条从
// 0.25s 一直挂到 2.75s，3.00s 才被「未配置令牌」卡替换——3.00s 正是 1s+2s 两次重试之和）。
//   ① 骨架条只能描「正在来」。`disabled` / `not_provisioned` / `auth` / `unavailable`
//      四态永远不会自己变成数据——画骨架就是承诺一件不会发生的事。
//   ② 503（含 `control_plane_not_provisioned`）必须不重试。它是「这一层没装配」的
//      终局态，重试两次只把骨架条钉在屏上 3 秒。
// 运行方式：node --test src/lib/data-state.test.ts（Node ≥23 原生类型剥离，零新依赖）。

const ALL_PHASES: DataPhase[] = [
  'loading',
  'ok',
  'disabled',
  'unavailable',
  'not_provisioned',
  'auth',
  'rate_limited',
  'error',
];
// 429 也在「永远不会自己来数据」这一侧：它要等冷却窗口过去，骨架条描不出「等」。
const NEVER_COMING: DataPhase[] = ['disabled', 'not_provisioned', 'auth', 'unavailable', 'rate_limited'];

test('shouldShowSkeleton：只有 loading 画骨架条', () => {
  for (const phase of ALL_PHASES) {
    assert.equal(shouldShowSkeleton(phase), phase === 'loading', `${phase} 的骨架判定不对`);
  }
});

test('shouldShowSkeleton：disabled/not_provisioned/auth/unavailable 一根都不出', () => {
  for (const phase of NEVER_COMING) {
    assert.equal(shouldShowSkeleton(phase), false, `${phase} 不该画骨架条`);
  }
});

test('shouldRetryQuery：503（含 control_plane_not_provisioned）不重试', () => {
  assert.equal(shouldRetryQuery({ status: 503 }, 0), false, '裸 503 不该重试');
  assert.equal(
    shouldRetryQuery({ status: 503, code: 'control_plane_not_provisioned' }, 0),
    false,
    '未装配控制面是终局态'
  );
  assert.equal(shouldRetryQuery({ status: 503, code: 'config_command_gateway_unavailable' }, 0), false);
  assert.equal(shouldRetryQuery({ status: 503 }, 1), false, '第二次也不许再排');
});

test('shouldRetryQuery：鉴权/参数类与超时一并不重试', () => {
  for (const status of [401, 403, 404, 422]) {
    assert.equal(shouldRetryQuery({ status }, 0), false, `${status} 不该重试`);
  }
  assert.equal(shouldRetryQuery({ status: 0, code: 'request_timeout' }, 0), false, '超时不该再排两次');
});

test('shouldRetryQuery：抖动类仍有限重试两次', () => {
  assert.equal(shouldRetryQuery({ status: 500 }, 0), true);
  assert.equal(shouldRetryQuery({ status: 500 }, 1), true);
  assert.equal(shouldRetryQuery({ status: 500 }, 2), false, '第三次必须交给人话');
  assert.equal(shouldRetryQuery({ status: 0 }, 0), true, '网络类（status 0）允许重试');
});

test('shouldRetryQuery：429（限速）一次都不许再排 —— 重试就是往枪口上撞', () => {
  // 用户实测：无令牌连发 7 次 → 前 5 次 401、第 6 次起 429、等 70 秒才恢复。
  // auth.py 的失败计数是**按来源**的：每重试一次就多记一笔失败，锁定窗口越拖越久。
  // 旧实现把 429 当「抖动类」加进 `failureCount < 2`，1s+2s 两次重试 = 两次新失败。
  for (const failureCount of [0, 1, 2]) {
    assert.equal(shouldRetryQuery({ status: 429 }, failureCount), false, `第 ${failureCount} 次失败后仍想重试 429`);
  }
  assert.equal(
    shouldRetryQuery({ status: 429, code: 'rate_limited' }, 0),
    false,
    '控制面 429 rate_limited 更不能重试'
  );
});

// —— 静态锁：渲染面与重试面必须真的走上面那把尺，而不是各自再抄一份 ——
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf-8');

test('静态锁：两个渲染面的骨架闸走 shouldShowSkeleton（禁止第二份 phase === loading）', () => {
  for (const rel of ['../pages/dashboard.tsx', '../components/semantic/semantic-state.tsx']) {
    const src = read(rel);
    assert.match(src, /shouldShowSkeleton\(/, `${rel} 没用 shouldShowSkeleton 收口骨架闸`);
    assert.doesNotMatch(src, /phase\s*===\s*'loading'/, `${rel} 仍有裸 phase === 'loading' 判据`);
  }
});

test('静态锁：重试规则只在 data-state.ts 一份（use-semantic-query 走 shouldRetryQuery）', () => {
  const hook = read('../hooks/use-semantic-query.ts');
  assert.match(hook, /shouldRetryQuery\(/, 'use-semantic-query 没走 shouldRetryQuery');
  const rule = hook.match(/\[\s*401\s*,[^\]]*\]/);
  assert.equal(rule, null, 'use-semantic-query 里仍有第二份状态码黑名单');
});

test('静态锁：DataPhase 与 hook 的 DataState 相位不漂移', () => {
  const hook = read('../hooks/use-semantic-query.ts');
  for (const phase of ALL_PHASES) {
    assert.ok(hook.includes(`'${phase}'`), `use-semantic-query 里没有 ${phase} 相位`);
  }
});
