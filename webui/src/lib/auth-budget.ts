// 鉴权失败预算（W18）。**先落测试再落实现**：见 `auth-budget.test.ts`。
//
// 为什么需要这个东西（一手证据）：
//   `scripts/request-audit.mjs` 打无令牌的 `/console/`，7 秒窗内共 10 发请求：
//     401 ×5（health / status.bot / stats.calls / stats.calls-7d / stats.tokens）
//     429 ×5（stats.latency / affinity.board / metrics.overview / knowledge.collections / health 重试）
//   后端 `control_plane/_app.py:172-183` 的顺序是「查冷却 → 认证 → 失败登记」，
//   `auth.py` 的 `FAILURE_MAX_COUNT = 5` ⇒ **首屏一次加载就把管理面锁 60 秒**。
//   锁死期间用户粘上正确令牌也会被 429 打回，只能干等——这就是「网站无法正常使用」。
//
// 修法边界（🔴 不许碰的东西）：
//   · 不动后端 `FAILURE_MAX_COUNT` / `FAILURE_WINDOW_SECONDS`——那是安全参数（防暴力枚举）；
//   · 不改 `_app.py` 的判定顺序——先查冷却是对的，令牌错时它才是唯一止损点。
// 所以修在前端：**没有令牌就根本不发**，一次失败立刻整体收敛。

/** 与后端 `FAILURE_MAX_COUNT` 同值，但语义不同：这里数的是「本页此刻还敢发几发」。 */
export const AUTH_LOCKOUT_BUDGET = 5;

/** 冷却窗。后端是 60s；前端取一半——比后端先放行，让用户在锁还没到期时就能重试一次。 */
export const DEFAULT_MIN_INTERVAL_MS = 30_000;

export interface AuthBudget {
  /** 还允许发几发。 */
  remaining: number;
  /** 进入整体停发的时刻（ms epoch）；`null` = 没停。 */
  haltedAt: number | null;
  /** 停发多久（ms）。 */
  cooldownMs: number;
}

export type AuthFailureKind = 'unauthorized' | 'rate-limited' | 'not-provisioned' | 'transient';

/** 全部鉴权语义档（测试锁死覆盖度：漏一档 = 静默走错分支）。 */
export const AUTH_STATES = ['credential-only', 'unauthorized', 'rate-limited', 'not-provisioned', 'transient'] as const;

export interface AuthState {
  remaining: number;
  haltedAt: number | null;
  cooldownMs: number;
}

export type Decision = 'halt' | 'continue';

export function initialAuthBudget(): AuthBudget {
  return { remaining: AUTH_LOCKOUT_BUDGET, haltedAt: null, cooldownMs: DEFAULT_MIN_INTERVAL_MS };
}

export interface SpendInput {
  hasToken: boolean;
}

export interface SpendResult {
  allowed: boolean;
  budget: AuthBudget;
}

/**
 * 决定这一发能不能发。
 *
 * 四道拒绝（顺序即优先级）：
 *   ① 没有令牌：不发。**这是收益最大的一条**——它单独消掉了首屏那 10 发里的全部 10 发。
 *   ② 预算耗尽：不发。
 *   ③ 冷却未过期：不发。
 *   ④ 冷却已过期：重新给满额度（用户可能换了令牌，必须能重试）。
 */
export function spendAuthBudget(budget: AuthBudget, input: SpendInput): SpendResult {
  if (!input.hasToken) return { allowed: false, budget };
  const now = Date.now();
  if (budget.haltedAt !== null) {
    if (now - budget.haltedAt < budget.cooldownMs) return { allowed: false, budget };
    // 冷却过期：恢复额度（不清空 haltedAt 的语义，只把它挪到"已过"）。
    const revived: AuthBudget = { ...budget, remaining: AUTH_LOCKOUT_BUDGET, haltedAt: null };
    return { allowed: true, budget: { ...revived, remaining: revived.remaining - 1 } };
  }
  if (budget.remaining <= 0) return { allowed: false, budget: { ...budget, haltedAt: now } };
  return { allowed: true, budget: { ...budget, remaining: budget.remaining - 1 } };
}

/**
 * 一次失败之后怎么办。
 *
 * 🔴 关键判据：`unauthorized` **一次就 halt**，不是攒满 5 次。
 * 理由：后端在攒满的那一刻锁 60 秒，等到我们数到 5，用户已经被锁了；
 * 攒的过程本身就是把锁推到满格的动作。
 */
export function classifyAuthFailure(budget: AuthBudget, kind: AuthFailureKind): Decision {
  void budget;
  switch (kind) {
    case 'unauthorized':
    case 'rate-limited':
    case 'not-provisioned':
      return 'halt';
    case 'transient':
      // 网络抖动 / 5xx / 超时：不消耗鉴权预算、不停发（它跟凭据对错无关）。
      return 'continue';
  }
}
