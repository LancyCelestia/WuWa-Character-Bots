// 语义查询钩子：react-query + 双层信封解析 → 统一语义态。
// 控制面语义：200 信封内 source_unavailable =「暂无数据/未配置」（非报错）；
// 503 control_plane_not_provisioned = 未配置访问令牌（引导设置）；401/403 = 令牌无效；
// 429 rate_limited = 被限速（**有自己的一档**：说「加载失败」会诱导用户重试，而重试正是
// 唯一会延长锁定的动作——控制面的失败计数按来源累计，五连败即锁 60 秒）。

import { useEffect } from 'react';
import { useQuery, type UseQueryOptions } from '@tanstack/react-query';
import { ApiError, resolveSemantic } from '@/lib/api-client';
import { beforeAuthRequest, noteAuthFailure } from '@/lib/auth-budget-store';
import { shouldRetryQuery } from '@/lib/data-state';
import { retryAfterSeconds } from '@/lib/rate-limit';

export type DataState<T> =
  | { phase: 'loading' }
  // 查询被 `enabled: false` 关掉：**永远不会**自己变成 ok/error。
  // 与 `loading` 分开的理由：骨架条的语义是「正在加载」，而这里根本没发请求——
  // 渲染骨架等于承诺一件不会发生的事（主代理 CDP 截图实测：总览无令牌时 27 根
  // 骨架条永久静止）。消费方按「没有数据」呈现，不是按「正在来数据」。
  | { phase: 'disabled' }
  | { phase: 'unavailable'; reason: string; source?: string }
  | { phase: 'not_provisioned' }
  | { phase: 'auth' }
  // 429 的专属档：waitSeconds 来自后端 `Retry-After`（后读不到就给 60）。
  // 单列一档而不是折进 `error`，是因为「等一会儿」与「坏了」该说两种话。
  | { phase: 'rate_limited'; retryAfterSeconds: number }
  // status/code 是可选补充：控制面把 HTTP 错误统一包成同一条 message，
  // 「这一页到底为什么红」（404=端点不在当前构建 / 422=参数被拒）只能靠结构化字段区分。
  | { phase: 'error'; message: string; status?: number; code?: string }
  | { phase: 'ok'; data: T; source?: string };

export interface SemanticQueryResult<T> {
  state: DataState<T>;
  refetch: () => void;
}

export function useSemanticQuery<T>(
  key: readonly unknown[],
  fetcher: () => Promise<unknown>,
  options?: Pick<UseQueryOptions, 'refetchInterval' | 'enabled'>
): SemanticQueryResult<T> {
  const query = useQuery({
    queryKey: key,
    // 预算闸（W18 R2）：**在这里而不是 api-client**。原因：`api-client.ts` 被两枚
    // 测试整体转译成 `data:` URL 加载（`api-client.test.ts` / `control-center.test.ts`），
    // 数据 URL 解析不了 `./xxx` 相对导入 —— 在那里加 import 会把两个测试一起打红。
    // 而所有控制面请求都从本 hook 出发（18 个页面），闸门放这里同样覆盖全部。
    //
    // 语义：一次并发加载打 7-8 发，服务端限速键是**来源**（`auth.py` 五连败锁 60 秒）。
    // 所以第一发 401 之后整页停发，后面 6 发直接拿本地 429（带 Retry-After 秒数），
    // 不再逐个端点撞墙，也不让用户在冷却期反复试对的令牌。
    queryFn: async () => {
      const gate = beforeAuthRequest();
      if (!gate.allowed) {
        throw new ApiError(
          `认证失败次数过多，请等待 ${Math.ceil(gate.waitMs / 1000)} 秒后重试`,
          429,
          { error: { code: 'rate_limited' } },
          String(Math.ceil(gate.waitMs / 1000))
        );
      }
      try {
        return await fetcher();
      } catch (error) {
        if (error instanceof ApiError) {
          const kind =
            error.status === 401 || error.status === 403
              ? 'unauthorized'
              : error.status === 429
                ? 'rate-limited'
                : error.status === 503 && error.code === 'control_plane_not_provisioned'
                  ? 'not-provisioned'
                  : 'transient';
          noteAuthFailure(kind);
        }
        throw error;
      }
    },
    refetchInterval: options?.refetchInterval,
    enabled: options?.enabled,
    // 重试规则**只有一份**（`@/lib/data-state` 的 shouldRetryQuery）：鉴权/参数/未装配/
    // 限速/超时一律不重试，其余抖动类最多两次。这里只做 ApiError → 判据字段的投影，
    // 不再抄第二份状态码黑名单。
    retry: (failureCount, error) =>
      shouldRetryQuery(
        error instanceof ApiError
          ? { status: error.status, code: error.code }
          : { status: undefined, code: null },
        failureCount
      ),
  });

  useEffect(() => {
    const refresh = () => { void query.refetch(); };
    window.addEventListener('webui:credentials-changed', refresh);
    return () => window.removeEventListener('webui:credentials-changed', refresh);
  }, [query.refetch]);

  if (query.isPending) {
    // `enabled: false` 时 react-query 停在 pending 且**永不**发起请求（`fetchStatus === 'idle'`）。
    // 这不是加载中，是「被关掉了」——如实报 `disabled`，别让消费方画一根不会动的骨架条。
    if (query.fetchStatus === 'idle') return { state: { phase: 'disabled' }, refetch: () => void query.refetch() };
    return { state: { phase: 'loading' }, refetch: () => void query.refetch() };
  }

  if (query.isError) {
    const error = query.error;
    if (error instanceof ApiError) {
      if (error.status === 503 && error.code === 'control_plane_not_provisioned') {
        return { state: { phase: 'not_provisioned' }, refetch: () => void query.refetch() };
      }
      if (error.status === 401 || error.status === 403) {
        return { state: { phase: 'auth' }, refetch: () => void query.refetch() };
      }
      if (error.status === 429) {
        // 后端 `_app.py` 三处鉴权依赖的 429 都带 `Retry-After`；读它，别让用户瞎猜。
        return {
          state: { phase: 'rate_limited', retryAfterSeconds: retryAfterSeconds(error.retryAfter) },
          refetch: () => void query.refetch(),
        };
      }
      return {
        state: { phase: 'error', message: error.message, status: error.status, code: error.code ?? undefined },
        refetch: () => void query.refetch(),
      };
    }
    return { state: { phase: 'error', message: String(error) }, refetch: () => void query.refetch() };
  }

  const semantic = resolveSemantic<T>(query.data);
  if (semantic.state === 'source_unavailable') {
    return { state: { phase: 'unavailable', reason: semantic.reason }, refetch: () => void query.refetch() };
  }
  return { state: { phase: 'ok', data: semantic.data, source: semantic.source }, refetch: () => void query.refetch() };
}
