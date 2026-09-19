// ============================================================================
// 日志尾流缓冲的单一事实源（PERF1-fix1 2026-09-20，评审 I-1 路 A）
//
// 这里收拢 logs.tsx 的全部纯逻辑：合并窗去重、判重位随裁切释放、MAX_ROWS 上限
// 裁剪、丢弃计数、暂停积压封顶、恢复折叠、清空。页面侧只剩 React 接线（定时器、
// 快照 state、sessionStorage），行为与 PERF1 波（commit 9f139b2）逐语义保持。
//
// 本文件刻意**零 React 依赖**（纯类 + 纯函数 + 纯常量），所以能被 node --test 直接
// 加载——判据住在 .tsx 里就等于没有判据（同 search-params.ts 头注的口径：Node 的类型
// 剥离不吃 JSX，logs.tsx 的不变量在上一波只能靠 %TEMP% 一次性脚本作证，评审
// review-PERF1 I-1 判「证据会腐烂」，本文件即其整改）。
//
// PERF1-fix2（评审 review-PERF1-fix1 I-1 整改）：合并窗的**调度缝**也提纯到此文件
// （createFlushController + 可注入 FlushScheduler）。「一窗一次提交」的行为本体原先住在
// logs.tsx 的 flushTimerRef 闸门里，11 条常驻锁全不 import 页面——破坏它一行且门路全绿。
// 现在页面只剩 `flush.request(buffer.append(...))` 一行接线，闸门语义有假时钟锁实证覆盖
// （零墙钟断言，M-1 教训）；页面侧「不得再自设定时器冲刷」由源码文本锁看守。
//
// 三条常驻不变量（锁在 log-stream.test.ts，改坏任何一条测试必红）：
//   (a) 判重与登记同在到达瞬间；被裁出视图/积压的行其判重位同步释放（Set 有界，
//       上界 = maxRows + 单个未冲刷窗口）。
//   (b) 视图与暂停积压都恒 ≤ maxRows；dropped + rows.length === 唯一到达总数，
//       暂停积压被提前裁掉的枚数在恢复时并入 dropped（总量与「不暂停直灌」逐枚等值）。
//   (c) clear() 同帧归零四态（rows / seen / 待冲刷缓冲 / dropped）；
//       暂停积压 backlog/backlogDropped **不清**——与改造前语义逐字一致（review Q1-1c）。
// ============================================================================

/** 视图行数与暂停积压的同界上限（F8-L1：积压与视图同界）。 */
export const MAX_ROWS = 500;

/**
 * 视图合并窗口（F8-L3）：窗口内到达的行只做一次 state 更新。
 * 取 16ms ≈ 一帧：稳态单条事件（k=1）的可见延迟不超过一帧；后台标签页定时器被
 * 节流到 ≥1s 也照常触发，缓冲不随挂机时长增长（评审 review-PERF1 §Q1-1a 复核过
 * intensive throttling 档位，上界仍是 到达率×节流档，有界）。
 */
export const FLUSH_WINDOW_MS = 16;

/** 缓冲只需要 cursor 作为身份键（logs 页真身 LogEventRow 的第一字段）。 */
export interface CursorBearing {
  cursor: number;
}

/**
 * 尾流缓冲状态机。方法与 logs.tsx 原 ref 编排一一对应：
 * - append      ← 原 appendRows 的判重入缓冲段（:185-192，注释所述不变量原样）
 * - commit      ← 原 commitPending 的 setRows updater（:167-178，含溢出裁切与判重位释放）
 * - bufferWhilePaused / takeBacklog ← 原暂停分支（:219-226）与恢复 effect（:259-268）
 * - clear       ← 原 clearView（:281-286，四态归零、积压不清）
 *
 * M-2（评审 Minor）在此一并收口：dropped 计数不再是嵌在 setRows updater 里的
 * setDroppedCount 副作用，而是状态变换的一部分——StrictMode 下重复执行任意方法
 * 只依赖已入状态，不产生翻倍的外溢增量。
 */
export class LogsBuffer<T extends CursorBearing> {
  readonly maxRows: number;

  private rowsValue: T[] = [];
  private seen: Set<number> = new Set();
  private pending: T[] = [];
  private droppedValue = 0;
  private backlog: T[] = [];
  private backlogDropped = 0;

  constructor(maxRows: number = MAX_ROWS) {
    this.maxRows = maxRows;
  }

  /** 当前视图行数组（引用只在 commit/clear 时更换，行对象引用透传——memo 浅比较的前提）。 */
  get rows(): readonly T[] {
    return this.rowsValue;
  }

  get dropped(): number {
    return this.droppedValue;
  }

  get hasPending(): boolean {
    return this.pending.length > 0;
  }

  /** 判重集规模（仅测试/观测用；不变量 (a) 的有界性判据）。 */
  get seenSize(): number {
    return this.seen.size;
  }

  /** 暂停积压当前枚数（页面恢复 effect 的门）。 */
  get backlogSize(): number {
    return this.backlog.length;
  }

  /**
   * 到达即同步判重登记、入待冲刷缓冲（不变量 (a)）。
   * 返回本批实际入缓冲枚数（0 = 全部重复，页面可据此不起定时器）。
   */
  append(incoming: readonly T[]): number {
    let buffered = 0;
    for (const row of incoming) {
      if (this.seen.has(row.cursor)) continue;
      this.seen.add(row.cursor);
      this.pending.push(row);
      buffered += 1;
    }
    return buffered;
  }

  /**
   * 合并窗到点：把待冲刷缓冲一次性并入视图。返回是否有实际变化（false=空缓冲，
   * 页面可据此跳过快照回写）。溢出时最旧行就地裁掉并当场释放判重位（不变量 (a)），
   * 裁掉枚数记入 dropped（不变量 (b)）。
   *
   * **判重位释放时点（M-2 披露，review-PERF1-fix1）**：提纯前 `seen.delete` 嵌在
   * setRows updater 里，实际执行于 React flush 时；现在随 commit() **同步**释放——
   * 时点前移。语义差窗口=「commit() 返回后、旧版 updater 执行前」，期间一条已裁
   * cursor 的重复投递旧版静默拒收、新版接受入库；新版方向恰更贴本文件自述不变量
   * (a)「被裁出视图的行其判重位同步释放」，不漏日志、无数据破坏。
   * **何时可再判同一游标 = commit() 返回 true 且该行确被裁出的那一瞬**（锁见
   * log-stream.test.ts「再判时点」条，反向断言「仍在窗内不得放行」同条看守）。
   */
  commit(): boolean {
    if (this.pending.length === 0) return false;
    const batch = this.pending;
    this.pending = [];
    const merged = [...this.rowsValue, ...batch];
    const overflow = merged.length - this.maxRows;
    if (overflow > 0) {
      for (let i = 0; i < overflow; i++) this.seen.delete(merged[i].cursor);
      this.droppedValue += overflow;
      this.rowsValue = merged.slice(overflow);
    } else {
      this.rowsValue = merged;
    }
    return true;
  }

  /**
   * 暂停期收单条：积压与视图同界（F8-L1）。超界最旧行注定在恢复时被 maxRows 裁掉，
   * 这里提前裁并把枚数暂存进 backlogDropped，恢复时并入 dropped——可见行集合与
   * dropped 总量都与「不暂停直灌」逐枚相同，只是不再无界堆积。
   */
  bufferWhilePaused(row: T): void {
    this.backlog.push(row);
    const overflow = this.backlog.length - this.maxRows;
    if (overflow > 0) {
      this.backlog.splice(0, overflow);
      this.backlogDropped += overflow;
    }
  }

  /**
   * 恢复：取走积压并清空积压两态，暂存枚数并入 dropped（不变量 (b) 的分段记账收口）。
   * droppedApplied = 本次并入的枚数（页面据此回写快照）。取走的积压由调用方喂 append()。
   */
  takeBacklog(): { backlog: T[]; droppedApplied: number } {
    const backlog = this.backlog;
    this.backlog = [];
    const droppedApplied = this.backlogDropped;
    this.backlogDropped = 0;
    if (droppedApplied > 0) this.droppedValue += droppedApplied;
    return { backlog, droppedApplied };
  }

  /**
   * 清空视图：四态同帧归零（不变量 (c)）。待冲刷缓冲必须与判重集同帧作废——
   * 已判重但未入库的行不得越过「清空」重新现身。
   * backlog/backlogDropped 有意不清：改造前 clearView 同样不碰积压（review Q1-1c
   * 已核「暂停中清空再恢复」路径代数和恒等），清了反而是行为改动。
   */
  clear(): void {
    this.seen.clear();
    this.pending = [];
    this.rowsValue = [];
    this.droppedValue = 0;
  }

  /** 卸载路径专用：只丢弃待冲刷缓冲（防卸载后回写），判重与视图不动。 */
  discardPending(): void {
    this.pending = [];
  }
}

// ----------------------------------------------------------------------------
// 合并窗调度缝（PERF1-fix2，review-PERF1-fix1 I-1 整改）
//
// 「一窗一次提交」的行为本体=下面的 request() 闸门：窗内已有在飞定时器时后来的
// 到达被合批吸收（不再另起），到点触发恰好一次 commit 并当场开闸迎接下一窗。
// 提纯前这段住在 logs.tsx（flushTimerRef 三行闸门），页面 .tsx 不可被 node --test
// 加载 → 行为零锁。现在生产注入 defaultFlushScheduler（与提纯前逐字等价的
// setTimeout/clearTimeout），测试注入假时钟手工 tick——判据零墙钟（M-1 教训：
// 计时断言跨机必抖，同一条测量出现过 1.2×/0.8× 双向漂移）。
// ----------------------------------------------------------------------------

/** 可注入定时器缝：handle 对实现不透明（生产=Timeout 对象，假时钟=自增 id）。 */
export interface FlushScheduler {
  schedule(task: () => void, delayMs: number): unknown;
  cancel(handle: unknown): void;
}

/** 生产实现：与提纯前 logs.tsx 直接调用 setTimeout/clearTimeout 的形态逐字等价。 */
export const defaultFlushScheduler: FlushScheduler = {
  schedule: (task, delayMs) => setTimeout(task, delayMs),
  cancel: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface FlushController {
  /**
   * 到达入口：仅当本次有新鲜行入缓冲（buffered>0，页面上屏即 buffer.append 的返回值）
   * 且当前无在飞窗口时武装定时器——「一窗一次提交」由此闸门保证；全重复批
   * （buffered=0）不起定时器（提纯前页面 `append()===0 即 return` 的形态，现在升为
   * 被锁行为）。
   */
  request(buffered: number): void;
  /**
   * 卸载清理入口：只取消在飞定时器（防卸载后回写），**不永久封口**——下一次
   * request 可重新武装。与提纯前 cleanup「clearTimeout + flushTimerRef 置 null」逐字
   * 一致，StrictMode 模拟重挂载后必须还能起新窗口（封口会把 dev 页面冻死）。
   */
  dispose(): void;
  /** 是否有已武装未触发的窗口（观测/测试用）。 */
  readonly isArmed: boolean;
}

export function createFlushController(input: {
  /** 到点提交的正文（页面注入=「buffer.commit() 变化则回写快照」，即原 commitPending）。 */
  commit: () => void;
  scheduler?: FlushScheduler;
  windowMs?: number;
}): FlushController {
  const scheduler = input.scheduler ?? defaultFlushScheduler;
  const windowMs = input.windowMs ?? FLUSH_WINDOW_MS;
  let handle: unknown = null;
  return {
    request(buffered: number): void {
      if (buffered <= 0 || handle !== null) return;
      handle = scheduler.schedule(() => {
        // 先开闸再提交：提交正文内若再到达（同 tick 连发），走下一窗——与提纯前
        // 定时器回调「flushTimerRef.current = null; commitPending();」的次序逐字一致。
        handle = null;
        input.commit();
      }, windowMs);
    },
    dispose(): void {
      if (handle !== null) {
        scheduler.cancel(handle);
        handle = null;
      }
    },
    get isArmed(): boolean {
      return handle !== null;
    },
  };
}
