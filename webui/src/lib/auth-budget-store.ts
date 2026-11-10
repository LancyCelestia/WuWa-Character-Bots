// 鉴权失败预算的**模块级单例**（W18 R2 接线面）。
//
// 为什么是单例而不是每查询一份：后端限速键是**来源**（本机 /32），不区分是哪个
// 端点、哪个组件发的。所以前端也必须按「整页」记账——7 个查询各自持一份预算，
// 等于 7 × 5 = 35 发配额，一次加载照样锁死。
//
// 三个入口：
//   `beforeAuthRequest()`  —— 每个带凭据的请求发出**之前**问一次「还能发吗」
//   `noteAuthFailure()`    —— 收到 401/403/429/503 之后报一次事实
//   `noteAuthSuccess()`    —— 收到 2xx 时把预算恢复（服务端没记账就该还额度）
//
// 🔴 不改后端 `FAILURE_MAX_COUNT` / `FAILURE_WINDOW_SECONDS`：那是防暴力枚举的
//    安全参数。前端只做「不主动撞墙」。
import {
  type AuthBudget,
  type AuthFailureKind,
  classifyAuthFailure,
  initialAuthBudget,
  spendAuthBudget,
} from './auth-budget.ts';

let budget: AuthBudget = initialAuthBudget();
/** 停发期间的重试时刻（ms epoch）；null = 未停发。 */
let resumeAt: number | null = null;
/**
 * 本次会话是否**已证明**凭据可用（至少一发 2xx）。
 *
 * 为什么需要它（实测驱动的修正）：预算闸上线后错令牌仍是 5 发并发 401
 * （`request-audit.mjs`：total=5, statuses={"401":5}）。5 恰好等于后端
 * `FAILURE_MAX_COUNT` —— 不锁，但是**临界点**：用户这时换成对的令牌，第 6 发
 * 必然撞 429。所以未证明的凭据只许**单飞探测**：第一发回来是 2xx 才放开并发。
 */
let proven = false;

/**
 * 单飞探测是否正在进行；以及等它出结果的并发请求。
 *
 * 为什么需要等待而不是直接拒绝：首屏 7 个查询同时出发，只有一个能当探针，
 * 其余若立刻抛 429，就会在**一个 429 都没发生**的情况下把整页画成「服务端正在限速」。
 * 正确语义是「排队等探针结果」，探针 2xx 后一起放行。
 */
let probing = false;
let probeWaiters: Array<(provenNow: boolean) => void> = [];

function settleProbeWaiters(provenNow: boolean): void {
  const waiters = probeWaiters;
  probeWaiters = [];
  for (const resolve of waiters) resolve(provenNow);
}

/** 仅供测试：把单例恢复到出厂态。 */
export function __resetAuthBudgetForTest(): void {
  budget = initialAuthBudget();
  resumeAt = null;
  proven = false;
  probing = false;
  settleProbeWaiters(false);
}

/** 仅供测试：标记凭据已证明可用（模拟一发 2xx 之后的状态）。 */
export function __markAuthProvenForTest(): void {
  proven = true;
}

export interface AllowResult {
  allowed: boolean;
  /** 被拦时的剩余等待毫秒；0 = 没拦。 */
  waitMs: number;
  /** 被拦原因；`probing` 表示不是限流，只是在等单飞探针。 */
  reason?: 'probing' | 'cooldown';
}

/**
 * 这一发能不能发。
 *
 * 与 `spendAuthBudget` 的差别只有一处：**这里把「无令牌」判定留给调用方**——
 * `api-client` 已经在附凭据前抛 503 了，重复判会白扣额度。所以传 `hasToken: true`。
 */
export function beforeAuthRequest(): AllowResult {
  // 未证明的凭据只放一发（单飞探测）。这一发回来若是 2xx，`noteAuthSuccess`
  // 会把 proven 置真，后续并发全部放行；若是 401，`noteAuthFailure` 立刻停发。
  // 效果：错令牌的总请求数是 **1** 而不是 5，永远不贴近后端阈值。
  // 并发请求不在这里抛 429：返回 reason='probing'，由 acquireAuthSlot 排队等待。
  if (!proven && probing) {
    return { allowed: false, waitMs: 0, reason: 'probing' };
  }
  const now = Date.now();
  if (resumeAt !== null) {
    if (now < resumeAt) return { allowed: false, waitMs: resumeAt - now, reason: 'cooldown' };
    // 冷却到期：恢复额度并放行（用户可能已经换了正确令牌）。
    // `proven` 一并复位 —— 新令牌同样要先单飞探一次。
    budget = initialAuthBudget();
    resumeAt = null;
    proven = false;
  }
  // 凭据已证明可用时不再按发数扣预算：后端只按**失败次数**锁来源，成功的并发
  // 请求不该互相挤占额度（否则首屏 7 发里最后两发会被本地闸伪判成 429）。
  // 真出现 401/429 时 noteAuthFailure 会立刻停发，安全边界仍在。
  if (proven) return { allowed: true, waitMs: 0 };
  const result = spendAuthBudget(budget, { hasToken: true });
  budget = result.budget;
  if (!result.allowed) {
    // spendAuthBudget 在额度耗尽时会把 haltedAt 写上；把冷却窗同步过来。
    resumeAt = (result.budget.haltedAt ?? now) + result.budget.cooldownMs;
    return { allowed: false, waitMs: Math.max(0, resumeAt - now), reason: 'cooldown' };
  }
  // 未证明时，这一发就是单飞探针；等它回来再放行其它并发。
  if (!proven) probing = true;
  return { allowed: true, waitMs: 0 };
}

/** 等当前单飞探针出结果；没有探针在飞时立即返回 proven。 */
export function waitForAuthProbe(): Promise<boolean> {
  if (proven) return Promise.resolve(true);
  if (!probing) return Promise.resolve(false);
  return new Promise<boolean>((resolve) => {
    probeWaiters.push(resolve);
  });
}

/**
 * 查询入口：拿一个可发请求的槽位；未证明时排队等探针，而不是伪造成 429。
 *
 * 这是首屏并发的正确语义：7 个查询同时进来 → 1 个当探针，6 个等待；
 * 探针 2xx → 6 个一起放行；探针 401 → 6 个按真实冷却返回，不重复撞墙。
 */
export async function acquireAuthSlot(): Promise<AllowResult> {
  for (;;) {
    const gate = beforeAuthRequest();
    if (gate.allowed || gate.reason !== 'probing') return gate;
    const provenNow = await waitForAuthProbe();
    if (!provenNow && resumeAt !== null) {
      return { allowed: false, waitMs: Math.max(0, resumeAt - Date.now()), reason: 'cooldown' };
    }
    // 探针遇到瞬时错误时只是重排：下一轮会再选一个探针，不会把整页判成限流。
  }
}

/**
 * 报一次鉴权失败。
 *
 * `kind` 由调用方从 HTTP 状态投影：401/403 → `unauthorized`，429 → `rate-limited`，
 * 503 `control_plane_not_provisioned` → `not-provisioned`，其余 → `transient`。
 */
export function noteAuthFailure(kind: AuthFailureKind): { halted: boolean; waitMs: number } {
  const decision = classifyAuthFailure(budget, kind);
  probing = false;
  settleProbeWaiters(false);
  if (decision === 'halt') {
    // 立刻进入停发：不等额度耗尽（耗尽那一刻后端已经锁了）。
    resumeAt = Date.now() + budget.cooldownMs;
    budget = { ...budget, haltedAt: Date.now() };
    return { halted: true, waitMs: budget.cooldownMs };
  }
  return { halted: false, waitMs: 0 };
}

/** 收到 2xx：服务端没记失败，把额度还回来（只还额度，不解停发）。 */
export function noteAuthSuccess(): void {
  // 一发 2xx 即证明凭据可用：放开并发（这是单飞探测的出口）。
  proven = true;
  probing = false;
  settleProbeWaiters(true);
  if (resumeAt !== null) return; // 停发期间成功一次不解封，等冷却走完
  budget = { ...budget, remaining: Math.min(initialAuthBudget().remaining, budget.remaining + 1) };
}

/** 当前是否处于停发（供 UI 显示「等 N 秒」）。 */
export function authHaltedWaitMs(): number {
  if (resumeAt === null) return 0;
  const left = resumeAt - Date.now();
  if (left <= 0) {
    resumeAt = null;
    budget = initialAuthBudget();
    return 0;
  }
  return left;
}
