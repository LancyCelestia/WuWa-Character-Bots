// 语义查询钩子：react-query + 双层信封解析 → 统一四态（loading / ok / unavailable / error）。
// 控制面语义：200 信封内 source_unavailable =「暂无数据/未配置」（非报错）；
// 503 control_plane_not_provisioned = 未配置访问令牌（引导设置）；401/403 = 令牌无效。

import { useQuery, type UseQueryOptions } from '@tanstack/react-query';
import { ApiError, resolveSemantic } from '@/lib/api-client';

export type DataState<T> =
  | { phase: 'loading' }
  | { phase: 'unavailable'; reason: string; source?: string }
  | { phase: 'not_provisioned' }
  | { phase: 'auth' }
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
    queryFn: fetcher,
    refetchInterval: options?.refetchInterval,
    enabled: options?.enabled,
    // 5xx/429 交给 react-query 有限重试；鉴权/参数类错误不重试（main.tsx retry 已含，这里兜底 422/401/403）。
    retry: (failureCount, error) => {
      if (error instanceof ApiError && [401, 403, 404, 422].includes(error.status)) return false;
      return failureCount < 2;
    },
  });

  if (query.isPending) return { state: { phase: 'loading' }, refetch: () => void query.refetch() };

  if (query.isError) {
    const error = query.error;
    if (error instanceof ApiError) {
      if (error.status === 503 && error.code === 'control_plane_not_provisioned') {
        return { state: { phase: 'not_provisioned' }, refetch: () => void query.refetch() };
      }
      if (error.status === 401 || error.status === 403) {
        return { state: { phase: 'auth' }, refetch: () => void query.refetch() };
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
