// 数据态判据的**单一事实源**：骨架闸 + 重试策略（S 席，抽自 dashboard/semantic-state/use-semantic-query）。
//
// 为什么必须抽出来：同一个判断（「这一态该不该画骨架条」「这条错误该不该再试一次」）
// 原先在三处各写一份，而三份的口径会各自漂移——2026-10-19 实测的形态就是
// 「骨架条挂了 3.00 秒」（1s+2s 两次重试），因为重试面把 503 当成抖动类。
//
// 判据只有一条：**骨架条描「正在来」**。`disabled`（查询被关掉）/ `not_provisioned`
// （控制面未装配）/ `auth`（令牌无效）/ `unavailable`（源不可用）四态永远不会自己
// 变成数据，画骨架就是承诺一件不会发生的事。
// 运行方式：node --test src/lib/data-state.test.ts（Node ≥23 原生类型剥离，零新依赖）。

/** 与 `DataState` 相位同名的窄类型（漂移由 data-state.test.ts 的静态锁守）。 */
export type DataPhase =
  | 'loading'
  | 'ok'
  | 'disabled'
  | 'unavailable'
  | 'not_provisioned'
  | 'auth'
  | 'rate_limited'
  | 'error';

/** 只有真正在飞的请求才画骨架条。 */
export function shouldShowSkeleton(phase: DataPhase): boolean {
  return phase === 'loading';
}

/** 重试策略的输入：只取判据用到的两个字段（`ApiError` 结构，不引 React）。 */
export interface RetryFacts {
  status?: number;
  code?: string | null;
}

/**
 * 一条失败该不该再排一次。
 *
 * @param error 失败事实（status / code）
 * @param failureCount 已经失败过的次数（react-query 口径，首次失败为 0）
 */
export function shouldRetryQuery(error: RetryFacts, failureCount: number): boolean {
  const status = error.status;
  // 429 = 「你被限速了，等一等」。控制面的失败计数**按来源累计**（auth.py 五连败即锁），
  // 每重试一次就多记一笔失败、把锁定窗口往后推——重试是唯一明确有害的动作。
  if (status === 401 || status === 403 || status === 404 || status === 422 || status === 429) return false;
  if (error.code === 'request_timeout') return false;
  // 503 = 「这一层没装配」（控制面未配置令牌 / 命令网关缺失）。它不会因为再问一次就装好，
  // 而重试两次 = 1s+2s 的骨架条（浏览器实测：27 根从 0.25s 挂到 3.00s）。
  if (status === 503) return false;
  return failureCount < 2;
}
