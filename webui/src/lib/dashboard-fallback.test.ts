import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// 总览首屏「六张卡到底走哪条路径」的注册锁（S 席执行任务「顺带修」）。
//
// 用户截图确认过的第二处真实缺陷：`dashboard.tsx` 的 `withFallback` 已经把非 ok 态
// 交给 `SemanticState`，但同一文件里 `CallsDetailGroup` 另有一条**直接写 `<Skeleton />`**
// 的分支。两条路径并存 ⇒ 「已 disabled / 未配置令牌 / 令牌无效 / 源不可用」时，
// 只要有一个消费方漏接 `withFallback`，骨架条就会永久静止——正是首屏六张卡的观感。
//
// 锁法：骨架只能出现在 `shouldShowSkeleton(...)` 的分支里，且整页只有这一处分支。
// 静态扫描而非渲染断言，是因为本仓 lib 测试要求零 React 运行时（node --test 直跑）。
// 运行方式：node --test src/lib/dashboard-fallback.test.ts

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf-8');
// 归一换行：仓里既有 CRLF 也有 LF（git autocrlf 的历史遗留），切片判据不该因此红/绿翻转。
const DASHBOARD = read('../pages/dashboard.tsx').replaceAll('\r\n', '\n');

/** 取一个具名函数的源码片段（从 `function 名(` 到下一个顶层 `\n}`）。 */
function fnSource(src: string, name: string): string {
  const start = src.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `dashboard.tsx 里找不到 ${name}`);
  const end = src.indexOf('\n}\n', start);
  assert.ok(end > start, `${name} 的片段不完整`);
  return src.slice(start, end + 3);
}

test('六张卡的数据面只走 withFallback：非 ok 一律交给 SemanticState（不得自己画骨架）', () => {
  const withFallback = fnSource(DASHBOARD, 'withFallback');
  assert.match(
    withFallback,
    /state\.phase === 'ok' \? node : <SemanticState state=\{state\}/,
    'withFallback 不是「ok 才给内容，其余交 SemanticState」'
  );
  assert.doesNotMatch(withFallback, /Skeleton/, 'withFallback 里又冒出了骨架条');
});

test('整页骨架只有一条路径：CallsDetailGroup 的 loading 分支，且由 shouldShowSkeleton 收口', () => {
  const group = fnSource(DASHBOARD, 'CallsDetailGroup');
  assert.match(group, /shouldShowSkeleton\(state\.phase\)/, 'CallsDetailGroup 的骨架闸没走 shouldShowSkeleton');
  assert.doesNotMatch(group, /phase === 'loading'/, 'CallsDetailGroup 仍有裸 phase === loading 判据');
  // 骨架条只许出现在该分支之后（`{shouldShowSkeleton(...) ? <div>…<Skeleton/>`）。
  const gate = group.indexOf('shouldShowSkeleton(');
  for (let index = group.indexOf('<Skeleton'); index >= 0; index = group.indexOf('<Skeleton', index + 1)) {
    assert.ok(index > gate, 'CallsDetailGroup 里有一根骨架条在骨架闸之外');
  }
});

test('全文件骨架条数量固定：3 根，全在 calls 明细卡里（别处新增骨架即红）', () => {
  const count = DASHBOARD.split('<Skeleton').length - 1;
  assert.equal(count, 3, `dashboard.tsx 的骨架条数量变成了 ${count}`);
  const group = fnSource(DASHBOARD, 'CallsDetailGroup');
  assert.equal(group.split('<Skeleton').length - 1, 3, '骨架条不在 CallsDetailGroup 里');
});

test('四态（disabled/not_provisioned/auth/unavailable）在六大卡路径上都不会落到骨架分支', () => {
  // 大卡的非 ok 态全部经 `withFallback` → `SemanticState`，而 SemanticState 只在
  // shouldShowSkeleton(phase) 为真时画骨架；两者合起来就是「四态零骨架」的证明链。
  const withFallback = fnSource(DASHBOARD, 'withFallback');
  const view = read('../components/semantic/semantic-state.tsx');
  assert.match(withFallback, /<SemanticState state=\{state\}/);
  assert.match(view, /shouldShowSkeleton\(state\.phase\)/, 'SemanticState 的骨架闸没走 shouldShowSkeleton');
  const gate = view.indexOf('shouldShowSkeleton(');
  for (let index = view.indexOf('<Skeleton'); index >= 0; index = view.indexOf('<Skeleton', index + 1)) {
    assert.ok(index > gate, 'SemanticState 里有一根骨架条在骨架闸之外');
  }
});

test('429 会顶掉整页：blocking 直接把 rate_limited 当页面级阻断（六张卡不各画一份限速文案）', () => {
  assert.match(DASHBOARD, /rate_limited/, 'dashboard 没把 rate_limited 纳入整页阻断判定');
  assert.match(DASHBOARD, /blocking\.refetch/, '整页阻断态没把 refetch 交给 SemanticState');
});
