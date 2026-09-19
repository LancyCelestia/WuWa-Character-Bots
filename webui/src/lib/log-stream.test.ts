// ============================================================================
// log-stream.ts 常驻回归锁（评审 review-PERF1 I-1 的整改主体）
//
// 上一波（PERF1，commit 9f139b2）这三条不变量只有 %TEMP% 里的一次性脚本作证，
// temp 一清就塌回「报告不是证据」。本文件把它们升为仓内常驻锁：改坏任何一条，
// `cd webui && npm test` 必红。断言全部走 LogsBuffer 公共口径（rows/dropped/
// hasPending/seenSize/backlogSize/返回值），不摸私有字段——等价重构（换内部
// 写法、换集合实现）不得变红，只有语义破坏才变红（双向自测对照见
// docs/design/unify-audit-20260919/PERF1-fix1.md §二）。
// ============================================================================
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { FLUSH_WINDOW_MS, LogsBuffer, MAX_ROWS, type CursorBearing } from './log-stream.ts';

type Row = CursorBearing & { id: number };

function row(cursor: number): Row {
  return { cursor, id: cursor };
}

function rowsOf(...cursors: number[]): Row[] {
  return cursors.map(row);
}

function cursors(buffer: LogsBuffer<Row>): number[] {
  return buffer.rows.map((r) => r.cursor);
}

/** 直灌（不暂停）：全部到达一次进缓冲、一次冲刷。等价于「不分段」的参照形态。 */
function directFeed(buffer: LogsBuffer<Row>, all: Row[]): void {
  buffer.append(all);
  buffer.commit();
}

// ---------------------------------------------------------------------------
// 不变量 (a)：去重
// ---------------------------------------------------------------------------

test('去重：同一 cursor 重复到达只留一行（含同批内重复）', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  assert.equal(buffer.append([...rowsOf(1, 1), row(2)]), 2, '同批内重复 cursor 必须当场折叠');
  assert.ok(buffer.commit());
  assert.deepEqual(cursors(buffer), [1, 2]);
  // 跨批重复（重放与实时尾包同事件两投的形态）
  assert.equal(buffer.append(rowsOf(1, 2)), 0, '已判重的行不得再次入缓冲');
  assert.equal(buffer.hasPending, false, '全重复批次不得留下待冲刷行');
  assert.equal(buffer.commit(), false, '空缓冲 commit 必须早退（clearView 后旧定时器依赖此早退）');
  assert.deepEqual(cursors(buffer), [1, 2]);
});

test('去重：被淘汰出窗的 cursor 其判重条目同步释放（否则 Set 单调涨）', () => {
  const buffer = new LogsBuffer<Row>(3);
  directFeed(buffer, rowsOf(1, 2, 3));
  assert.equal(buffer.seenSize, 3);
  // cursor 1 被裁出视图——判重位必须当场释放
  buffer.append(rowsOf(4));
  assert.ok(buffer.commit());
  assert.deepEqual(cursors(buffer), [2, 3, 4]);
  assert.equal(buffer.seenSize, 3, '裁一放一，Set 不随总到达数增长');
  assert.equal(buffer.append(rowsOf(1)), 1, '被裁出的 cursor 必须能被再次接受（判重位确已释放）');
  // 反向：仍在窗内的 cursor 不得被放行
  assert.equal(buffer.append(rowsOf(3)), 0, '未淘汰的 cursor 判重位必须保留');
});

test('去重：2 万条连续流下判重集有界（≤MAX_ROWS+单窗口缓冲，终态=MAX_ROWS）', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  let peakSeen = 0;
  for (let c = 1; c <= 20_000; c++) {
    buffer.append([row(c)]);
    peakSeen = Math.max(peakSeen, buffer.seenSize);
    buffer.commit();
  }
  assert.equal(cursors(buffer).length, MAX_ROWS);
  assert.equal(buffer.seenSize, MAX_ROWS, '逐条冲刷时终态判重集恰=MAX_ROWS');
  assert.ok(peakSeen <= MAX_ROWS + 1, `判重集峰值 ${peakSeen} 越过了「MAX_ROWS+单帧缓冲」上界`);
});

// ---------------------------------------------------------------------------
// 不变量 (b)：上限裁剪 + 丢弃记账
// ---------------------------------------------------------------------------

test('上限：暂停灌入 N≫MAX_ROWS，rows≤MAX_ROWS 且 dropped+rows==总到达数', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  const N = MAX_ROWS * 10; // 5000 ≫ 500
  for (let c = 1; c <= N; c++) buffer.bufferWhilePaused(row(c));
  assert.ok(buffer.backlogSize <= MAX_ROWS, `暂停积压越界：${buffer.backlogSize}`);
  const { backlog, droppedApplied } = buffer.takeBacklog();
  assert.equal(droppedApplied, N - MAX_ROWS);
  buffer.append(backlog);
  assert.ok(buffer.commit());
  assert.equal(cursors(buffer).length, MAX_ROWS);
  assert.equal(buffer.dropped + cursors(buffer).length, N, '丢弃记账必须与到达总数账面闭合');
  assert.deepEqual(cursors(buffer), [...Array(MAX_ROWS)].map((_, i) => N - MAX_ROWS + i + 1), '留下的必须是最新一批');
});

test('上限：视图未满时暂停积压不产生任何 dropped', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  for (let c = 1; c <= 10; c++) buffer.bufferWhilePaused(row(c));
  const { backlog, droppedApplied } = buffer.takeBacklog();
  assert.equal(droppedApplied, 0);
  buffer.append(backlog);
  buffer.commit();
  assert.equal(buffer.dropped, 0);
  assert.deepEqual(cursors(buffer), [...Array(10)].map((_, i) => i + 1));
});

// ---------------------------------------------------------------------------
// 不变量 (b)续：恢复等值（评审 §四-3 的常驻化）
// ---------------------------------------------------------------------------

test('恢复：暂停冲刷后的可见游标序列与不分段直灌逐元素相同（视图已满场景）', () => {
  // 复刻 review-PERF1/PERF1-impl §三-测1 段 3b：视图满 500 + 暂停 1200 → dropped 必须 1200
  const pausedBuffer = new LogsBuffer<Row>(MAX_ROWS);
  directFeed(pausedBuffer, rowsOf(...[...Array(MAX_ROWS)].map((_, i) => i + 1))); // 视图满
  for (let c = MAX_ROWS + 1; c <= MAX_ROWS + 1200; c++) pausedBuffer.bufferWhilePaused(row(c));
  const { backlog, droppedApplied } = pausedBuffer.takeBacklog();
  assert.equal(droppedApplied, 700, '暂停期预裁的 700 枚必须在恢复时并入 dropped');
  pausedBuffer.append(backlog);
  pausedBuffer.commit();

  const directBuffer = new LogsBuffer<Row>(MAX_ROWS);
  directFeed(directBuffer, rowsOf(...[...Array(MAX_ROWS + 1200)].map((_, i) => i + 1)));

  assert.deepEqual(cursors(pausedBuffer), cursors(directBuffer), '两种形态的可见游标序列必须逐枚相同');
  assert.equal(pausedBuffer.dropped, directBuffer.dropped);
  assert.equal(pausedBuffer.dropped, 1200, '分段记账合并后总量=一次性裁剪枚数');
  assert.equal(pausedBuffer.seenSize, directBuffer.seenSize, '判重集终态也必须相等');
});

// ---------------------------------------------------------------------------
// 不变量 (c)：清空
// ---------------------------------------------------------------------------

test('清空：rows/seen/待冲刷缓冲/dropped 四态同帧归零（含第四态 pending 漏清探针）', () => {
  const buffer = new LogsBuffer<Row>(3);
  directFeed(buffer, rowsOf(1, 2, 3));
  for (let c = 4; c <= 5; c++) {
    buffer.append([row(c)]);
    buffer.commit(); // 制造 overflow → dropped>0
  }
  buffer.append(rowsOf(9)); // 已判重入 pending、未 commit
  assert.ok(buffer.dropped > 0 && buffer.hasPending);

  buffer.clear();
  assert.deepEqual(cursors(buffer), [], 'rows 必须归零');
  assert.equal(buffer.dropped, 0, 'dropped 必须归零');
  assert.equal(buffer.hasPending, false, 'pending 必须归零');
  // 第四态探针：若 clear 漏清 pending，下面这次 commit 会让 r9 越过「清空」重新现身
  assert.equal(buffer.commit(), false, '清空后旧定时器到点必须空冲刷（不得吐出清空前的行）');
  assert.deepEqual(cursors(buffer), []);
  // seen 归零的判据：清空时**仍在窗内**的 cursor 必须可被重新接受
  assert.equal(buffer.append(rowsOf(3, 4, 5)), 3, 'clear 后判重集必须为空');
});

test('清空：暂停积压两态有意不清（与改造前语义逐字一致，review Q1-1c）', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  buffer.bufferWhilePaused(row(7));
  buffer.bufferWhilePaused(row(8));
  buffer.clear();
  const { backlog, droppedApplied } = buffer.takeBacklog();
  assert.deepEqual(backlog.map((r) => r.cursor), [7, 8], 'clear 不得吞掉暂停期积压（那是行为改动）');
  assert.equal(droppedApplied, 0);
  buffer.append(backlog);
  buffer.commit();
  assert.deepEqual(cursors(buffer), [7, 8]);
});

test('卸载：discardPending 只弃待冲刷缓冲，视图与判重不动', () => {
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  directFeed(buffer, rowsOf(1, 2));
  buffer.append(rowsOf(3));
  buffer.discardPending();
  assert.equal(buffer.commit(), false);
  assert.deepEqual(cursors(buffer), [1, 2]);
  assert.equal(buffer.append(rowsOf(2)), 0, '判重集不受卸载影响');
});

// ---------------------------------------------------------------------------
// 合并窗：分批/冲刷节奏不改变最终序列（「窗内乱序到达不得改变最终顺序」）
// ---------------------------------------------------------------------------

test('合并窗：同一到达序列按三种分批节奏冲刷，最终游标序列与 dropped 逐元素相同', () => {
  const arrivals = rowsOf(...[...Array(300)].map((_, i) => i + 1));
  const maxRows = 50; // 带 overflow 的场景同样必须等值

  const runOne = (flushEvery: number | 'all'): { cursors: number[]; dropped: number } => {
    const buffer = new LogsBuffer<Row>(maxRows);
    if (flushEvery === 'all') {
      buffer.append(arrivals);
      buffer.commit();
    } else {
      for (let i = 0; i < arrivals.length; i += flushEvery) {
        buffer.append(arrivals.slice(i, i + flushEvery));
        buffer.commit();
      }
    }
    return { cursors: cursors(buffer), dropped: buffer.dropped };
  };

  const perRow = runOne(1); // k=1 逐条冲刷（改造前节奏）
  const batched = runOne(7); // 不规则分批
  const oneShot = runOne('all'); // 一整窗
  assert.deepEqual(batched.cursors, perRow.cursors, '分批节奏不得改变可见序列');
  assert.deepEqual(oneShot.cursors, perRow.cursors);
  assert.equal(batched.dropped, perRow.dropped);
  assert.equal(oneShot.dropped, perRow.dropped);
  assert.deepEqual(perRow.cursors, [...Array(maxRows)].map((_, i) => 300 - maxRows + i + 1), '留下的必须是最新的 MAX_ROWS 枚');
});

test('合并窗：可见延迟预算——单条到达至多等一个 FLUSH_WINDOW_MS（k=1 无回归的常驻口径）', () => {
  // 计时断言跨机必抖（review M-1），常驻锁只钉「预算常量」本身：
  // 16ms=一帧，这是 §五-1 判定「行入库最迟晚一帧、肉眼无从分辨」的量化依据。
  assert.equal(FLUSH_WINDOW_MS, 16, '合并窗预算漂移需显式评审（改大=可见延迟超一帧，改小=合批失效）');
  assert.equal(MAX_ROWS, 500, '视图/积压同界上限漂移需显式评审（L-1 封顶与 3c 有界性都钉在此值）');
  const buffer = new LogsBuffer<Row>(MAX_ROWS);
  assert.equal(buffer.append([row(1)]), 1); // k=1：单条即刻入缓冲，窗口只推迟合并、不吞并不改序
  assert.ok(buffer.commit());
  assert.deepEqual(cursors(buffer), [1]);
});
