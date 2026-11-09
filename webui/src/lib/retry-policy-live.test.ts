import assert from 'node:assert/strict';
import { test } from 'node:test';
import { QueryClient } from '@tanstack/react-query';
import { shouldRetryQuery } from './data-state.ts';

// 真跑 react-query 的「429 雪崩」对照实验（S 席执行任务 1 的运行时证据）。
//
// 为什么不能只做单测：`shouldRetryQuery` 是判据，但雪崩是 **react-query 调它几次** 造成的。
// 这里把真的 QueryClient 拉起来，让 queryFn 每次调用都记一笔，然后数它到底跑了几次：
//   旧策略（429 落进 `failureCount < 2`）→ 跑 3 次 = 首发 + 1s + 2s 两次重试，
//   而控制面按来源累计失败计数 ⇒ 这 3 次一起把用户钉在 60 秒锁定里。
//   新策略（429 与 401/403 同级，触发即不排）→ 跑 1 次，锁定窗口只吃第一次。
//
// 全程本地内存，不发真实请求：不消耗用户那条 60 秒限速配额。
// 运行方式：node --test src/lib/retry-policy-live.test.ts

/** 与 `ApiError` 同形的替身（只带判据要读的字段，不引 api-client 的 fetch 面）。 */
class FakeApiError extends Error {
  status: number;
  code: string | null;

  constructor(status: number, code: string | null = null) {
    super(`HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** 用真 QueryClient 跑一次查询，返回 queryFn 被调用的次数。 */
async function countAttempts(retry: (failureCount: number, error: unknown) => boolean, status: number): Promise<number> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry, retryDelay: 0, staleTime: 0 } },
  });
  let attempts = 0;
  await client
    .fetchQuery({
      queryKey: ['probe', status],
      queryFn: async () => {
        attempts += 1;
        throw new FakeApiError(status);
      },
    })
    .catch(() => undefined);
  client.clear();
  return attempts;
}

/** 旧策略：main.tsx 里原来那份 `[401,403,404,500]` 排除列表 + `failureCount < 2`。 */
const legacyRetry = (failureCount: number, error: unknown): boolean => {
  if (error instanceof FakeApiError && [401, 403, 404, 500].includes(error.status)) return false;
  return failureCount < 2;
};

const policyRetry = (failureCount: number, error: unknown): boolean =>
  error instanceof FakeApiError
    ? shouldRetryQuery({ status: error.status, code: error.code }, failureCount)
    : failureCount < 2;

test('旧策略在 429 上跑 3 次（首发 + 1s + 2s 两次重试）——这就是雪崩', async () => {
  assert.equal(await countAttempts(legacyRetry, 429), 3);
});

test('新策略在 429 上只跑 1 次：不再多记两笔失败、不再把锁定窗口往后推', async () => {
  assert.equal(await countAttempts(policyRetry, 429), 1);
});

test('新策略没有把抖动类一起冻死：500 仍然重试两次（3 次尝试）', async () => {
  assert.equal(await countAttempts(policyRetry, 500), 3);
});

test('新策略对 401 与旧策略同效（鉴权类一次即停，不是「一律不重试」的误伤）', async () => {
  assert.equal(await countAttempts(policyRetry, 401), 1);
  assert.equal(await countAttempts(legacyRetry, 401), 1);
});
