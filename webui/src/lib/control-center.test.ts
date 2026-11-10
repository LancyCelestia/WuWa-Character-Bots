import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { formatCount, formatMs } from './format.ts';

// control-center.ts 的外部依赖只有 api-client 的 apiRequest/qs。这里把它接到**同一份
// 生产模块**的 data: URL（而非替身），因此 centerApi 的新增只读消费者也走真实 apiRequest
// 门：真实请求编码、外层信封解包后响应保留、错误码、空/分页，以及令牌不持久化。
// controlApi（logs 列表/详情）的同类断言在 api-client.test.ts。
const clientSource = readFileSync(new URL('./api-client.ts', import.meta.url), 'utf8');
const clientCompiled = ts.transpileModule(clientSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
});
const clientUrl = `data:text/javascript;base64,${Buffer.from(clientCompiled.outputText).toString('base64')}`;
const { resolveSemantic, setApiToken, getApiToken } = await import(clientUrl);

const ownerSource = readFileSync(new URL('./owner-consent.ts', import.meta.url), 'utf8');
const ownerCompiled = ts.transpileModule(ownerSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
});
const ownerUrl = `data:text/javascript;base64,${Buffer.from(ownerCompiled.outputText).toString('base64')}`;

const source = readFileSync(new URL('./control-center.ts', import.meta.url), 'utf8')
  .replace("'./api-client'", JSON.stringify(clientUrl))
  .replace("'./owner-consent'", JSON.stringify(ownerUrl));
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext } });
const { configValue, pendingReceipt, centerApi } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);

async function channelMarkup(health: Record<string, unknown>): Promise<string> {
  const target = new URL('../components/control-center/channel-health.tsx', import.meta.url);
  assert.ok(existsSync(target), 'The model monitor has no consumer for channel health');
  const source = readFileSync(target, 'utf8').replace(/^import .* from .*;\r?\n/gm, '');
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React } });
  // 组件自 W13-M 起走公共格式化层（`@/lib/format`）。import 行被剥掉是为了把组件当纯
  // 展示件渲染，故这里把**同一份真实实现**（不是替身）作为作用域参数注入——断言看到的
  // 仍是生产格式化输出，替身会把这个测试降级成「假函数渲染出假字符串」。
  const load = new Function(
    'React',
    'formatMs',
    'formatCount',
    `${compiled.outputText.replace(/export /g, '')}; return ChannelHealthView;`
  );
  return renderToStaticMarkup(React.createElement(load(React, formatMs, formatCount), { health }));
}

test('unknown channel health never renders null latency as zero or as healthy', async () => {
  const markup = await channelMarkup({ state: 'unknown', reason: 'source_unavailable', ema_ms: null, samples: 0, consecutive_fails: 0, cooldown_active: false, last_ok_at: null });
  assert.match(markup, /unknown/);
  assert.match(markup, /source_unavailable/);
  assert.match(markup, /—/);
  assert.doesNotMatch(markup, />0 ms</);
  const known = await channelMarkup({ state: 'healthy', ema_ms: 23.5, samples: 2, consecutive_fails: 0, cooldown_active: false, last_ok_at: '2026-10-15T00:00:00Z' });
  // formatMs 把亚毫秒小数收敛成整数 ms（与延迟页同一口径）：23.5 → 24ms。
  assert.match(known, /24ms/);
  assert.match(known, /样本 2/);
});

test('pending and disconnected receipts never claim successful application', () => {
  assert.match(pendingReceipt({ status: 'pending' }), /等待/);
  assert.match(pendingReceipt({ status: 'needs_consent' }), /尚未落库/);
  assert.match(pendingReceipt({ status: 'registered' }), /未连接/);
  assert.match(pendingReceipt({ status: 'unknown' }), /勿盲目/);
  assert.equal(configValue('false'), false);
  assert.equal(configValue('0.7'), 0.7);
  assert.equal(configValue('plain text'), 'plain text');
});
test('receipt labels cover the real backend status/state vocabulary without claiming success', () => {
  // 真身：config_commands.py status ∈ pending/leased/applied/failed/conflict
  for (const status of ['pending', 'leased', 'applied', 'failed', 'conflict']) {
    assert.ok(pendingReceipt({ status }).length > 0);
  }
  // 真身：actions.py state ∈ running/succeeded/failed/unknown/timed_out/cancelled
  for (const state of ['running', 'succeeded', 'failed', 'unknown', 'timed_out', 'cancelled']) {
    assert.ok(pendingReceipt({ state }).length > 0);
  }
  assert.match(pendingReceipt({ state: 'unknown' }), /勿盲目/);
  assert.doesNotMatch(pendingReceipt({ state: 'running' }), /成功/);
  assert.doesNotMatch(pendingReceipt({ status: 'pending' }), /成功/);
});
test('a degraded/unavailable/unknown result or adapter_not_connected never reads as success, even when state is succeeded', () => {
  // 真身：_app.py 动作 handler 的 result.status ∈ ok|degraded|failed；
  //      未实现动作 = {"status":"degraded","details":{"state":"registered","execution":"adapter_not_connected"}}。
  for (const status of ['degraded', 'unavailable', 'unknown']) {
    const text = pendingReceipt({ state: 'succeeded', result: { status } });
    assert.doesNotMatch(text, /执行成功/);
    assert.match(text, /未|勿|请/);
  }
  // 🔴 真身：_app.py:545 `logging.level` 档位非法 → {"status":"failed","details":{"error":"invalid_level"}}。
  // 顶层 state=succeeded 只表示运行生命周期走完；handler 的最终判定 failed 绝不能被读成「执行成功」。
  const handlerFailed = pendingReceipt({ state: 'succeeded', result: { status: 'failed', details: { error: 'invalid_level' } } });
  assert.doesNotMatch(handlerFailed, /执行成功/);
  assert.match(handlerFailed, /失败/);
  const nested = pendingReceipt({ state: 'succeeded', result: { status: 'degraded', details: { execution: 'adapter_not_connected' } } });
  assert.doesNotMatch(nested, /执行成功/);
  assert.match(nested, /适配/);
  const topLevel = pendingReceipt({ state: 'succeeded', result: { execution: 'adapter_not_connected' } });
  assert.doesNotMatch(topLevel, /执行成功/);
  assert.match(topLevel, /适配/);
  // 真·成功与无 result 的两条腿不得被误伤。
  assert.match(pendingReceipt({ state: 'succeeded', result: { status: 'ok' } }), /执行成功/);
  assert.match(pendingReceipt({ state: 'succeeded' }), /执行成功/);
});
test('operable statuses read as actionable Chinese and applied keeps its exact meaning', () => {
  // 真身词表：config_commands.py _STATUS_* = pending/leased/applied/needs_consent/conflict/failed/expired/unknown
  assert.match(pendingReceipt({ status: 'conflict' }), /冲突/);
  assert.match(pendingReceipt({ status: 'leased' }), /勿重复|执行中/);
  assert.match(pendingReceipt({ status: 'needs_consent' }), /批准/);
  // 动作 state 侧：actions.py = running/succeeded/failed/unknown/timed_out/cancelled
  assert.match(pendingReceipt({ state: 'timed_out' }), /超时/);
  assert.match(pendingReceipt({ state: 'cancelled' }), /取消/);
  assert.match(pendingReceipt({ state: 'running' }), /执行中/);
  assert.equal(pendingReceipt({ status: 'applied' }), '配置已落库；运行时生效请核实际状态');
});

// ===========================================================================
// 增量（client 席）：已存在但无消费者的只读控制面端点消费者（centerApi）。
// 真身：api/actions.py:37（run 详情）、api/llm.py:71-110（providers/channels/health/routes）、
// api/v1.py:278-296（metrics 只读）。断言走**生产** apiRequest 门。
// ===========================================================================

function installHarness() {
  const fetches: string[] = [];
  const auth: string[] = [];
  const storageWrites: string[] = [];
  let next: { body: unknown; status: number } = { body: {}, status: 200 };
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const windowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const hadFetch = Object.prototype.hasOwnProperty.call(globalThis, 'fetch');
  const fetchDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
  const hadStorage = Object.prototype.hasOwnProperty.call(globalThis, 'localStorage');
  const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');

  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      location: { origin: 'http://127.0.0.1:8742', protocol: 'http:', hostname: '127.0.0.1' },
      dispatchEvent() {},
    },
  });
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem() { return null; },
      setItem(key: string) { storageWrites.push(`set:${key}`); },
      removeItem(key: string) { storageWrites.push(`remove:${key}`); },
    },
  });
  Object.defineProperty(globalThis, 'fetch', {
    configurable: true,
    value: async (url: string, init: RequestInit) => {
      fetches.push(String(url));
      auth.push(String((init.headers as Record<string, string>).Authorization ?? ''));
      return new Response(JSON.stringify(next.body), {
        status: next.status,
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  return {
    fetches,
    auth,
    storageWrites,
    respond(body: unknown, status = 200) { next = { body, status }; },
    restore() {
      if (hadFetch && fetchDescriptor) Object.defineProperty(globalThis, 'fetch', fetchDescriptor);
      else Reflect.deleteProperty(globalThis, 'fetch');
      if (hadWindow && windowDescriptor) Object.defineProperty(globalThis, 'window', windowDescriptor);
      else Reflect.deleteProperty(globalThis, 'window');
      if (hadStorage && storageDescriptor) Object.defineProperty(globalThis, 'localStorage', storageDescriptor);
      else Reflect.deleteProperty(globalThis, 'localStorage');
    },
  };
}

/** 后端错误体 {error:{code,message}} → ApiError(name=ApiError,status,code)。 */
function expectApiError(status: number, code: string) {
  return (error: unknown): boolean => {
    const e = error as { name?: string; status?: number; code?: string | null };
    return e.name === 'ApiError' && e.status === status && e.code === code;
  };
}

test('action run detail reads the exact encoded path, preserves the stored receipt and feeds the receipt reader', async () => {
  const harness = installHarness();
  try {
    setApiToken('fake-session-token', 'admin');
    const detail = {
      run_id: 'run 1/2', action_id: 'logging.level', actor: 'admin', request_id: 'req-1', version: 3,
      state: 'succeeded', error_code: null, created_at: 1760000000.5, updated_at: 1760000001.25,
      result: { status: 'degraded', details: { state: 'registered', execution: 'adapter_not_connected' } },
    };
    harness.respond({ data: detail, error: null, meta: { request_id: 'r1' } });
    const got = await centerApi.runDetail('run 1/2');
    assert.deepEqual(got, detail, '外层信封解包后原样返回内层详情');
    assert.equal(harness.fetches.at(-1), '/api/v1/actions/runs/run%201%2F2');
    assert.equal(harness.auth.at(-1), 'Bearer fake-session-token', 'GET 读路径带内存令牌');
    // 详情是 pendingReceipt 的直接输入：degraded/adapter_not_connected 绝不读成「执行成功」。
    assert.doesNotMatch(pendingReceipt(got), /执行成功/);
    assert.match(pendingReceipt(got), /适配/);

    // 未登记/不存在：后端 404 action_run_not_found。
    harness.respond({ error: { code: 'action_run_not_found', message: 'x' } }, 404);
    await assert.rejects(centerApi.runDetail('missing'), expectApiError(404, 'action_run_not_found'));

    // 令牌只在 setApiToken 里落盘（上面那句显式写入），apiRequest/centerApi 读路径一个字都不写。
    assert.deepEqual(harness.storageWrites, ['set:webui:token:admin'], '读路径绝不重写令牌');
    assert.equal(getApiToken(), 'fake-session-token');
  } finally {
    harness.restore();
    setApiToken(null, 'admin');
  }
});

test('llm read-only consumers hit the real control-plane paths and preserve the projection', async () => {
  const harness = installHarness();
  try {
    setApiToken('fake-session-token', 'admin');

    const providers = {
      items: [{
        provider_id: 'prov-0123456789', label: 'https://api.example.com', origin: 'https://api.example.com',
        channel_ids: ['c1'], models: ['m1'], credentials_configured: 1, channels: 1,
      }],
    };
    harness.respond({ data: providers });
    assert.deepEqual(await centerApi.llmProviders(), providers);
    assert.equal(harness.fetches.at(-1), '/api/v1/llm/providers');

    const channels = {
      items: [{
        channel_id: 'c1', model: 'm1', model_family: 'm', provider_id: 'prov-0123456789',
        origin: 'https://api.example.com', priority: 100, tags: [], routing_group: null,
        effort_override: '', auto_routable: true,
        health: { state: 'unknown', reason: 'no_sample', ema_ms: null, samples: 0, consecutive_fails: 0, cooldown_active: false, last_ok_at: null },
        credential: { state: 'configured', fingerprint: 'abcd1234', key_count: 1 },
        price_per_m: null, price_per_call: null,
      }],
    };
    harness.respond({ data: channels });
    assert.deepEqual(await centerApi.llmChannels(), channels);
    assert.equal(harness.fetches.at(-1), '/api/v1/llm/channels');

    const health = {
      status: 'disabled', health_layer_enabled: false, latency_first: false, totals: {},
      cooling_ids: [], unavailable_ids: [], source: 'disabled', generated_at: '2026-10-15T00:00:00+00:00',
    };
    harness.respond({ data: health });
    assert.deepEqual(await centerApi.llmHealth(), health);
    assert.equal(harness.fetches.at(-1), '/api/v1/llm/health');

    const routes = {
      policy: {
        strict_priority: true, latency_first: false, health_layer_enabled: false,
        failover_max_seconds: 0, failover_min_hop_seconds: 3, timeout_seconds: 30,
        max_input_tokens: 0, max_output_tokens: 0,
        priority_groups: { count: 0, active_name: '', active_order: [] },
      },
      routes: [],
    };
    harness.respond({ data: routes });
    assert.deepEqual(await centerApi.llmRoutes(), routes);
    assert.equal(harness.fetches.at(-1), '/api/v1/llm/routes');

    // 缺服务：后端诚实 503 llm_control_unavailable（不伪装空表）。
    harness.respond({ error: { code: 'llm_control_unavailable', message: 'x' } }, 503);
    await assert.rejects(centerApi.llmHealth(), expectApiError(503, 'llm_control_unavailable'));

    // 令牌只在 setApiToken 里落盘（上面那句显式写入），读路径一个字都不写。
    assert.deepEqual(harness.storageWrites, ['set:webui:token:admin'], '读路径绝不重写令牌');
  } finally {
    harness.restore();
    setApiToken(null, 'admin');
  }
});

test('metrics read-only consumers keep the semantic packet so the UI can degrade honestly', async () => {
  const harness = installHarness();
  try {
    setApiToken('fake-session-token', 'admin');

    const aggregate = {
      provider_identity_quality: 'legacy_unverified',
      provider_identity_source_code: 'schema1_provider_id_from_registry_route_id',
      recorded_calls: 3, successful_calls: 2, failed_calls: 0, unknown_status_calls: 1,
      unknown_timestamp_calls: 0,
      tokens: { input: { value: 10, known_rows: 1, unknown_rows: 0, quality: 'complete' } },
      attempt_total: { value: null, quality: 'unknown', reason: 'not_recorded_reliably' },
      failover_calls: { value: null, quality: 'unknown', reason: 'not_recorded_reliably' },
    };
    const snapshot = { pid: 1, process_role: 'control_plane', captured_at: '2026-10-15T00:00:00+00:00', measurements: {} };

    // overview = {resources, usage}（v1.py:280 把资源快照与账本语义包并排返回）。
    harness.respond({ data: { resources: snapshot, usage: { status: 'ok', source: 'llm_call_records', data: aggregate } } });
    const overview = await centerApi.metricsOverview();
    assert.equal(harness.fetches.at(-1), '/api/v1/metrics/overview');
    assert.deepEqual(overview.resources, snapshot);
    assert.deepEqual(resolveSemantic(overview.usage), { state: 'ok', data: aggregate, source: 'llm_call_records' });

    const sessions = { status: 'ok', source: 'llm_call_records', data: { ...aggregate, sessions: [{ session: 's1', ...aggregate }] } };
    harness.respond({ data: sessions });
    assert.deepEqual(await centerApi.metricsSessions({ limit: 100 }), sessions);
    assert.equal(harness.fetches.at(-1), '/api/v1/metrics/sessions?limit=100');

    const trends = { status: 'ok', source: 'llm_call_records', data: { ...aggregate, bucket: 'day', timezone: 'UTC', items: [{ bucket_start: '2026-10-14T00:00:00+00:00', ...aggregate }] } };
    harness.respond({ data: trends });
    assert.deepEqual(await centerApi.metricsTrends({ bucket: 'day', limit: 50 }), trends);
    assert.equal(harness.fetches.at(-1), '/api/v1/metrics/trends?bucket=day&limit=50');

    // /metrics/tokens 真身返回 overview 语义包（v1.py:290），**不是** stats/tokens 的模型族表。
    harness.respond({ data: { status: 'ok', source: 'llm_call_records', data: aggregate } });
    assert.deepEqual(await centerApi.metricsTokens(), { status: 'ok', source: 'llm_call_records', data: aggregate });
    assert.equal(harness.fetches.at(-1), '/api/v1/metrics/tokens');

    // 服务未接线：200 + source_unavailable 语义包（不抛错），UI 自行呈现「暂无数据」。
    harness.respond({ data: { status: 'source_unavailable', reason: 'not_connected', data: null } });
    assert.deepEqual(resolveSemantic(await centerApi.metricsSessions()), { state: 'source_unavailable', reason: 'not_connected' });
    assert.equal(harness.fetches.at(-1), '/api/v1/metrics/sessions?limit=100');

    // 非法查询参数：后端 422 metrics_invalid_query 走 ApiError。
    harness.respond({ error: { code: 'metrics_invalid_query', message: 'x' } }, 422);
    await assert.rejects(
      centerApi.metricsTrends({ bucket: 'minute' as unknown as 'day' }),
      expectApiError(422, 'metrics_invalid_query')
    );

    // 令牌只在 setApiToken 里落盘（上面那句显式写入），读路径一个字都不写。
    assert.deepEqual(harness.storageWrites, ['set:webui:token:admin'], '读路径绝不重写令牌');
  } finally {
    harness.restore();
    setApiToken(null, 'admin');
  }
});

test('an upper-level cancelled/failed state is never overridden by a result that reads ok', () => {
  // 字面边界：顶层 `state`/`status` 是运行生命周期，`result.status` 是 handler 的最终判定。
  // 两者冲突时**生命周期失败/取消优先**——绝不允许 result.status='ok' 把它翻成「执行成功」。
  assert.equal(pendingReceipt({ state: 'cancelled', result: { status: 'ok' } }), '已取消，未执行');
  assert.equal(pendingReceipt({ state: 'failed', result: { status: 'ok' } }), '执行失败，未确认生效');
  assert.equal(pendingReceipt({ state: 'timed_out', result: { status: 'ok' } }), '已超时，结果未知；勿盲目重复提交');
  assert.equal(pendingReceipt({ status: 'failed', result: { status: 'ok' } }), '执行失败，未确认生效');
  assert.equal(pendingReceipt({ status: 'conflict', result: { status: 'ok' } }), '版本冲突，本笔未生效；请重新读取后再提交');
  for (const state of ['cancelled', 'failed', 'timed_out']) {
    assert.doesNotMatch(pendingReceipt({ state, result: { status: 'ok' } }), /执行成功/);
  }
  // handler 判定 failed 与顶层 state=failed 共用同一词条同一文案（一处真源，勿分叉）。
  assert.equal(pendingReceipt({ state: 'succeeded', result: { status: 'failed' } }), '执行失败，未确认生效');
  // 反向腿：只有「生命周期 succeeded + handler ok」才允许读成成功，两条都不得被误伤。
  assert.equal(pendingReceipt({ state: 'succeeded', result: { status: 'ok' } }), '执行成功，请核回执');
  assert.equal(pendingReceipt({ state: 'succeeded' }), '执行成功，请核回执');
});
