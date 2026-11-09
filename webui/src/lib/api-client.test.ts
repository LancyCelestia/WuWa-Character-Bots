import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('./api-client.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext } });
const { getApiToken, setApiToken, getBaseUrl, validateBaseUrl, resolveEnvBaseUrl, apiRequest, controlApi } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);

const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
after(() => {
  if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
  else Reflect.deleteProperty(globalThis, 'localStorage');
});

test('两把令牌各管各的：admin 与 ro 不串用，清除即 null', () => {
  installStorage();
  setApiToken(null, 'admin');
  setApiToken(null, 'ro');
  assert.equal(getApiToken(), null);
  setApiToken(' fake-session-token ', 'admin');
  assert.equal(getApiToken(), 'fake-session-token');
  assert.equal(getApiToken('ro'), null);
  setApiToken('fake-read-token', 'ro');
  assert.equal(getApiToken('ro'), 'fake-read-token');
  setApiToken(null);
  assert.equal(getApiToken(), null);
  setApiToken(null, 'ro');
});

test('persisted base URL is re-validated on read so a poisoned value cannot carry the bearer token off-host', () => {
  const store: Record<string, string> = {};
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem(key: string) { return store[key] ?? null; },
      setItem(key: string, value: string) { store[key] = value; },
      removeItem(key: string) { delete store[key]; },
    },
  });
  // 直接注入（模拟 XSS／手工改 localStorage）：写入侧 setBaseUrl 会拒，但读侧必须自己再校验。
  store['webui:baseUrl'] = 'http://evil.example.com';
  assert.equal(getBaseUrl(), '');
  // 白名单内（loopback 任意端口）照常生效。
  store['webui:baseUrl'] = 'http://127.0.0.1:8742';
  assert.equal(getBaseUrl(), 'http://127.0.0.1:8742');
});

// ===========================================================================
// 令牌持久化（用户原话：「我填进去令牌了，但是无法保存」）
//
// 旧行为：令牌只落 `sessionTokens` 内存对象，刷新即丢；而界面文案承诺「仅存本机浏览器」，
// 于是用户看到「已保存」却刷新后全没 = 假保存。现在改为真落 localStorage。
// 安全面：键名固定；写前 trim；空串=删键（不存空串）；读/写失败静默降级为内存态；
// 令牌不得出现在 URL／异常文本里。
// ===========================================================================

const TOKEN_KEYS = { admin: 'webui:token:admin', ro: 'webui:token:ro' };

function installStorage(initial: Record<string, string> = {}) {
  const store: Record<string, string> = { ...initial };
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem(key: string) { return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null; },
      setItem(key: string, value: string) { store[key] = String(value); },
      removeItem(key: string) { delete store[key]; },
    },
  });
  return store;
}

test('令牌写入后落 localStorage 且能读回（刷新后仍在）', () => {
  const store = installStorage();
  setApiToken('  fake-admin-token  ', 'admin');
  assert.equal(getApiToken('admin'), 'fake-admin-token', '内存态读回（已 trim）');
  assert.equal(store[TOKEN_KEYS.admin], 'fake-admin-token', '持久化键名固定，值为 trim 后的令牌');
  setApiToken('fake-ro-token', 'ro');
  assert.equal(store[TOKEN_KEYS.ro], 'fake-ro-token');
  assert.equal(getApiToken('admin'), 'fake-admin-token', '两把令牌互不覆盖');
  setApiToken(null, 'admin');
  setApiToken(null, 'ro');
});

test('刷新后仍在：新模块实例（内存镜像为空）从 localStorage 读回令牌', async () => {
  const store = installStorage();
  setApiToken('survives-refresh', 'admin');
  // 新实例＝新页面加载：模块级 sessionTokens 是空的，只能靠持久化读回。
  const source = readFileSync(new URL('./api-client.ts', import.meta.url), 'utf8');
  const compiledFresh = ts.transpileModule(`${source}\n// fresh-instance`, {
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
  });
  const fresh = await import(
    `data:text/javascript;base64,${Buffer.from(compiledFresh.outputText).toString('base64')}`
  );
  assert.equal(fresh.getApiToken('admin'), 'survives-refresh', '刷新后必须读回已保存的令牌');
  assert.equal(store[TOKEN_KEYS.admin], 'survives-refresh');
  // 反向：清空后新实例同样读不到（不是「永远有值」的假绿）。
  setApiToken(null, 'admin');
  const source2 = readFileSync(new URL('./api-client.ts', import.meta.url), 'utf8');
  const compiledFresh2 = ts.transpileModule(`${source2}\n// fresh-instance-2`, {
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
  });
  const fresh2 = await import(
    `data:text/javascript;base64,${Buffer.from(compiledFresh2.outputText).toString('base64')}`
  );
  assert.equal(fresh2.getApiToken('admin'), null, '清除后刷新不得再读回旧令牌');
});

test('空串（含纯空白）＝删键，绝不存空串', () => {
  const store = installStorage({ [TOKEN_KEYS.admin]: 'stale', [TOKEN_KEYS.ro]: 'stale-ro' });
  setApiToken('', 'admin');
  assert.equal(Object.prototype.hasOwnProperty.call(store, TOKEN_KEYS.admin), false, '空串必须删键');
  assert.equal(store[TOKEN_KEYS.admin], undefined);
  assert.equal(getApiToken('admin'), null);
  setApiToken('   ', 'ro');
  assert.equal(Object.prototype.hasOwnProperty.call(store, TOKEN_KEYS.ro), false, '纯空白同样删键');
  assert.equal(store[TOKEN_KEYS.ro], undefined);
});

test('localStorage 抛异常（隐私模式/被禁）时静默降级为内存态，不崩', () => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() { throw new Error('SecurityError: localStorage is disabled'); },
  });
  assert.doesNotThrow(() => setApiToken('degraded-token', 'admin'), '写失败不得抛出');
  assert.equal(getApiToken('admin'), 'degraded-token', '内存态仍然拿得到');
  assert.doesNotThrow(() => setApiToken(null, 'admin'), '清空同样不得抛出');
  assert.equal(getApiToken('admin'), null);
});

test('凭据变更事件保留：每次 setApiToken 都派发 webui:credentials-changed', () => {
  installStorage();
  const events: string[] = [];
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const descriptorWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  try {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        location: { origin: 'http://127.0.0.1:8742', protocol: 'http:', hostname: '127.0.0.1' },
        dispatchEvent(event: Event) { events.push(event.type); },
      },
    });
    setApiToken('fake-token', 'admin');
    setApiToken(null, 'admin');
    assert.deepEqual(events, ['webui:credentials-changed', 'webui:credentials-changed']);
  } finally {
    setApiToken(null, 'ro');
    if (hadWindow && descriptorWindow) Object.defineProperty(globalThis, 'window', descriptorWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

test('令牌不进 URL：请求地址与异常文本都不得含令牌原文', async () => {
  installStorage();
  const fetches: string[] = [];
  const hadFetch = Object.prototype.hasOwnProperty.call(globalThis, 'fetch');
  const descriptorFetch = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
  try {
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: async (url: string) => {
        fetches.push(String(url));
        return new Response(JSON.stringify({ error: { code: 'boom', message: 'server said no' } }), {
          status: 500,
          headers: { 'content-type': 'application/json' },
        });
      },
    });
    setApiToken('fake-secret-token', 'admin');
    let caught: Error | null = null;
    await apiRequest('/api/v1/stats/calls?window=24h').catch((error: Error) => { caught = error; });
    assert.ok(caught, '错误响应必须抛出');
    assert.ok(!String((caught as Error).message).includes('fake-secret-token'), '异常文本不得带令牌');
    assert.ok(fetches.every((url) => !url.includes('fake-secret-token')), '令牌绝不出现在 URL');
  } finally {
    setApiToken(null, 'admin');
    if (hadFetch && descriptorFetch) Object.defineProperty(globalThis, 'fetch', descriptorFetch);
    else Reflect.deleteProperty(globalThis, 'fetch');
  }
});

// ===========================================================================
// build-seal（GPT Important-2）：env 基址同样过白名单；认证前对最终目标纵深校验。
// 纯 resolver（`validateBaseUrl`）走生产调用链；Node 宿主无浏览器 fetch 时只用 fake。
// ===========================================================================

test('env-supplied VITE_API_BASE_URL must pass the same allowlist as persisted values', () => {
  // 走**生产导出**的 env 解析逻辑（真实调用链，非替身）：环境值必须过同一把白名单尺。
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
  try {
    Reflect.deleteProperty(globalThis, 'window');
    assert.equal(resolveEnvBaseUrl('http://evil.example.com'), '', 'env 恶意基址不得返回');
    assert.equal(resolveEnvBaseUrl('http://127.0.0.1:8742'), 'http://127.0.0.1:8742', 'env loopback 放行');
    assert.equal(resolveEnvBaseUrl('ftp://127.0.0.1'), '', 'env 非 http(s) 拒');
    assert.equal(resolveEnvBaseUrl(undefined), '', 'env 缺席=同源缺省');
    assert.deepEqual(validateBaseUrl('http://127.0.0.1@evil.example.com'), {
      ok: false,
      reason: 'host_not_allowed',
    });
  } finally {
    if (hadWindow && descriptor) Object.defineProperty(globalThis, 'window', descriptor);
  }
  // 非 Vite 宿主（import.meta.env 不存在）下读路径不抛，回落同源。
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem() { return null; }, setItem() {}, removeItem() {} },
  });
  assert.equal(getBaseUrl(), '');
});

test('validateBaseUrl is a pure allowlist resolver: same-origin, loopback ok; absolute/protocol-relative/other hosts rejected', () => {
  // 同源（Node 无 window 时不冒充同源；给了 window.location 才认）。
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'window');
  try {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { location: { origin: 'http://panel.example.com:8742', protocol: 'http:', hostname: 'panel.example.com' } },
    });
    assert.equal(validateBaseUrl('http://panel.example.com:8742').ok, true, '同源应通过');
    assert.equal(validateBaseUrl('http://panel.example.com:8743').ok, false, '异端口不是同源');
    assert.equal(validateBaseUrl('https://panel.example.com:8742').ok, false, '异协议不是同源');
    assert.equal(validateBaseUrl('http://127.0.0.1:8742').ok, true, 'loopback 应通过');
    assert.equal(validateBaseUrl('http://localhost:8742').ok, true, 'localhost 应通过');
    assert.equal(validateBaseUrl('').ok, true, '空值=同源缺省应通过');
    assert.deepEqual(validateBaseUrl('ftp://127.0.0.1'), { ok: false, reason: 'bad_scheme' });
    assert.deepEqual(validateBaseUrl('http://evil.example.com'), { ok: false, reason: 'host_not_allowed' });
    assert.deepEqual(validateBaseUrl('http://127.0.0.1@evil.example.com'), { ok: false, reason: 'host_not_allowed' });
    assert.deepEqual(validateBaseUrl('not a url'), { ok: false, reason: 'invalid_url' });
  } finally {
    if (hadWindow && descriptor) Object.defineProperty(globalThis, 'window', descriptor);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

test('apiRequest refuses to attach the bearer token when the final target escapes the allowlist', async () => {
  const calls: string[] = [];
  const fetches: string[] = [];
  const hadWindow = Object.prototype.hasOwnProperty.call(globalThis, 'window');
  const descriptorWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const hadFetch = Object.prototype.hasOwnProperty.call(globalThis, 'fetch');
  const descriptorFetch = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
  try {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { location: { origin: 'http://127.0.0.1:8742', protocol: 'http:', hostname: '127.0.0.1' }, dispatchEvent() {} },
    });
    // 显式清掉基址持久化（前序用例可能留下 loopback 基址，会掩盖 endpoint 越界这条腿）。
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem() { return null; },
        setItem() {},
        removeItem() {},
      },
    });
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: async (url: string, init: RequestInit) => {
        fetches.push(String(url));
        calls.push(String((init.headers as Record<string, string>).Authorization ?? ''));
        return new Response(JSON.stringify({ data: { ok: true } }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      },
    });
    setApiToken('fake-session-token', 'admin');

    // Invalid targets must stop before touching headers/body or invoking fetch.
    for (const endpoint of [
      'http://evil.example.com/steal', ' https://evil.example.com/steal',
      '//evil.example.com/steal', '\\\\evil.example.com/steal',
      '/\\evil.example.com/steal', 'javascript:alert(1)', 'data:text/plain,secret',
      'http://127.0.0.1@evil.example.com', 'http://localhost:99999/',
    ]) {
      let touched = false;
      await assert.rejects(apiRequest(endpoint, {
        method: 'POST',
        get headers() { touched = true; return { Authorization: 'private-header' }; },
        body: { toJSON() { touched = true; return 'private-body'; } },
      }), (error: { code: string }) => error.code === 'api_target_not_allowed');
      assert.equal(touched, false, endpoint);
      assert.equal(fetches.length, 0, endpoint);
    }
    assert.deepEqual(
      calls.filter((c) => c.length > 0),
      [],
      '白名单外绝对 endpoint 不得携带 Bearer'
    );

    // 2) 协议相对 endpoint（//evil.example.com/...）同样不得带 token。
    await apiRequest('//evil.example.com/steal').catch(() => undefined);
    assert.deepEqual(calls.filter((c) => c.length > 0), [], '协议相对 endpoint 不得携带 Bearer');

    // 3) 合法同源/相对 endpoint 照常带 token。
    await apiRequest('/api/v1/stats/calls');
    assert.equal(calls.at(-1), 'Bearer fake-session-token', '合法同源路径仍须带 token');
    assert.ok(fetches.at(-1)?.startsWith('/api/v1/stats/calls'), '合法路径原样发出');

    // 4) 只读凭据仅用于 GET（写请求不自动回落 readonly）。
    setApiToken(null, 'admin');
    setApiToken('fake-read-token', 'ro');
    calls.length = 0;
    await apiRequest('/api/v1/stats/calls');
    assert.equal(calls.at(-1), 'Bearer fake-read-token', 'GET 缺主令牌可回退 readonly');
    // 写请求不自动回落 readonly：既不带 ro 令牌出站，也不发注定 401 的无凭据请求
    // （无令牌 ⇒ fetch 前直接抛 503 not_provisioned，见 apiRequest 内注释）。
    const before = calls.length;
    await assert.rejects(
      apiRequest('/api/v1/config/X/set', { method: 'POST', body: {} }),
      (error: { code?: string }) => error.code === 'control_plane_not_provisioned',
      '写请求缺主令牌必须拒绝，不得自动使用 readonly 凭据'
    );
    assert.equal(calls.length, before, '拒绝发生在发请求之前，绝不带 readonly 令牌出站');
  } finally {
    setApiToken(null, 'admin');
    setApiToken(null, 'ro');
    if (hadFetch && descriptorFetch) Object.defineProperty(globalThis, 'fetch', descriptorFetch);
    else Reflect.deleteProperty(globalThis, 'fetch');
    if (hadWindow && descriptorWindow) Object.defineProperty(globalThis, 'window', descriptorWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

// ===========================================================================
// 增量（client 席）：已存在但无消费者的只读控制面端点消费者。
// 真身：control_plane/api/events.py（logs 列表 :90 / 详情 :237）、api/actions.py
// （run 详情 :37）、api/llm.py（providers/channels/health/routes 只读 :71-110）、
// api/v1.py（metrics 只读 :278-296）。断言全部走**生产** apiRequest 门：真实请求
// 编码、外层信封解包后响应保留、错误码、空页、分页，以及凭据不持久化。
// ===========================================================================

function installReadHarness() {
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

test('logs list/detail consumers encode the real query, preserve the cursor page and surface backend error codes', async () => {
  const harness = installReadHarness();
  try {
    setApiToken('fake-session-token', 'admin');

    // 列表：升序游标页（events.py:365 返回 items/next_cursor/has_more/high_cursor）。
    const page = {
      items: [{
        cursor: 42, event_id: 'evt-42', created_at: '2026-10-15T00:00:00+00:00', source: 'bot',
        category: 'pipeline', message: '结构化摘要', details: { capability: 'bot.weather' },
      }],
      next_cursor: 42, has_more: false, high_cursor: 42,
    };
    harness.respond({ data: page, error: null, meta: { request_id: 'r1' } });
    assert.deepEqual(await controlApi.logs({ after: 7, limit: 25, source: 'bot', category: 'pipeline' }), page);
    assert.equal(harness.fetches.at(-1), '/api/v1/logs?after=7&limit=25&source=bot&category=pipeline');
    assert.equal(harness.auth.at(-1), 'Bearer fake-session-token', 'GET 读路径带内存令牌');

    // 空页 + has_more 保留（分页语义不得被前端吃掉）。
    const empty = { items: [], next_cursor: 9, has_more: true, high_cursor: 12 };
    harness.respond({ data: empty });
    assert.deepEqual(await controlApi.logs({ after: 3 }), empty);
    assert.equal(harness.fetches.at(-1), '/api/v1/logs?after=3&limit=50', 'limit 缺省 50，after 显式');

    // 无参：仍显式带 limit（与既有 affinityBoard/knowledgeTerms 同款缺省口径）。
    harness.respond({ data: page });
    await controlApi.logs();
    assert.equal(harness.fetches.at(-1), '/api/v1/logs?limit=50');

    // 详情：event_id 必须编码，响应原样保留。
    const row = {
      cursor: 1, event_id: 'evt 1/2', created_at: '2026-10-15T00:00:00+00:00', source: 'llm',
      category: 'llm', message: '摘要', details: null,
    };
    harness.respond({ data: row });
    assert.deepEqual(await controlApi.logDetail('evt 1/2'), row);
    assert.equal(harness.fetches.at(-1), '/api/v1/logs/evt%201%2F2');

    // 诚实错误面：410 cursor_expired / 404 event_not_found / 503 events_unavailable。
    harness.respond({ error: { code: 'cursor_expired', message: 'x' } }, 410);
    await assert.rejects(controlApi.logs({ after: 1 }), expectApiError(410, 'cursor_expired'));
    harness.respond({ error: { code: 'event_not_found', message: 'x' } }, 404);
    await assert.rejects(controlApi.logDetail('missing'), expectApiError(404, 'event_not_found'));
    harness.respond({ error: { code: 'events_unavailable', message: 'x' } }, 503);
    await assert.rejects(controlApi.logs(), expectApiError(503, 'events_unavailable'));

    // 令牌只在 setApiToken 里落盘；apiRequest 读路径一个字都不写。
    // （前一次写＝上面那句显式 setApiToken，故只允许恰好那一次。）
    assert.deepEqual(harness.storageWrites, ['set:webui:token:admin'], '读路径绝不重写令牌');
    assert.equal(getApiToken(), 'fake-session-token');
  } finally {
    harness.restore();
    setApiToken(null, 'admin');
  }
});
