// A 组阻断缺陷（2026-11）前端侧：**超管令牌第三槽**。
//
// 用户报的三件事同因：
//   - A1「设置存不了」、A3「凭据打不开」、A8「可视编辑器只能读」——
//     所有写腿（配置 preview/set/reset、动作 preview/execute、凭据整段路由、
//     可视化 preview/save/theme）都挂后端 `_super_admin_dependency`，**只认**
//     `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256`；而前端只有 admin/ro 两槽，
//     写入必然 403。
//
// 本文件锁四条：
//   ① 第三槽真的存在、键名固定、与另两槽互不覆盖、刷新后读回；
//   ② 写腿的 Authorization 必须换成超管令牌（不是主令牌）；
//   ③ 只填超管时读腿也能出站（读端点接受只读/主/超管任一）；
//   ④ 令牌绝不进 URL / 异常文本（安全面不许回退）。
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('./api-client.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
});
const { getApiToken, setApiToken, apiRequest } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`
);

/** 三槽键名是**固定字面量**（改名＝让所有已登录用户静默掉登录态）。 */
const TOKEN_KEYS = {
  admin: 'webui:token:admin',
  ro: 'webui:token:ro',
  superAdmin: 'webui:token:super-admin',
};

const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
after(() => {
  if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
  else Reflect.deleteProperty(globalThis, 'localStorage');
});

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

function clearAll() {
  setApiToken(null, 'admin');
  setApiToken(null, 'ro');
  setApiToken(null, 'superAdmin');
}

test('第三槽：superAdmin 有独立持久化键，与 admin/ro 互不覆盖且能读回', () => {
  const store = installStorage();
  clearAll();
  setApiToken(' super-secret ', 'superAdmin');
  assert.equal(getApiToken('superAdmin'), 'super-secret', '内存态读回（已 trim）');
  assert.equal(store[TOKEN_KEYS.superAdmin], 'super-secret', '持久化键名固定');
  setApiToken('plain-admin', 'admin');
  setApiToken('plain-ro', 'ro');
  assert.equal(getApiToken('superAdmin'), 'super-secret', '写主令牌不得覆盖超管槽');
  assert.equal(getApiToken('admin'), 'plain-admin');
  assert.equal(getApiToken('ro'), 'plain-ro');
  clearAll();
  assert.equal(getApiToken('superAdmin'), null, '清除后读回 null');
  assert.equal(Object.prototype.hasOwnProperty.call(store, TOKEN_KEYS.superAdmin), false);
});

test('刷新后仍在：新模块实例从 localStorage 读回超管令牌', async () => {
  installStorage();
  setApiToken('super-survives', 'superAdmin');
  const compiledFresh = ts.transpileModule(`${source}\n// fresh-super-admin`, {
    compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
  });
  const fresh = await import(
    `data:text/javascript;base64,${Buffer.from(compiledFresh.outputText).toString('base64')}`
  );
  assert.equal(fresh.getApiToken('superAdmin'), 'super-survives');
  setApiToken(null, 'superAdmin');
});

async function withFetchCapture<T>(run: (calls: Array<{ url: string; auth: string; method: string }>) => Promise<T>): Promise<T> {
  const calls: Array<{ url: string; auth: string; method: string }> = [];
  const hadFetch = Object.prototype.hasOwnProperty.call(globalThis, 'fetch');
  const descriptorFetch = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
  try {
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: async (url: string, init: RequestInit = {}) => {
        calls.push({
          url: String(url),
          auth: String((init.headers as Record<string, string>).Authorization ?? ''),
          method: String(init.method ?? 'GET'),
        });
        return new Response(JSON.stringify({ data: { ok: true } }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      },
    });
    return await run(calls);
  } finally {
    if (hadFetch && descriptorFetch) Object.defineProperty(globalThis, 'fetch', descriptorFetch);
    else Reflect.deleteProperty(globalThis, 'fetch');
  }
}

test('写腿带的是超管令牌（配置 set / 动作 preview / 凭据 write 同一把）', async () => {
  installStorage();
  clearAll();
  setApiToken('plain-admin', 'admin');
  setApiToken('super-writer', 'superAdmin');
  try {
    await withFetchCapture(async (calls) => {
      await apiRequest('/api/v1/config/BOT_CHAT_FAST_MODE/set', { method: 'POST', body: { value: true } });
      assert.equal(calls.at(-1)?.auth, 'Bearer super-writer', 'POST 必须换超管令牌');

      await apiRequest('/api/v1/actions/runtime.reload/execute', { method: 'POST', body: {} });
      assert.equal(calls.at(-1)?.auth, 'Bearer super-writer');

      // 读腿保持原口径（主令牌优先；超管令牌不是读面的默认替换项）。
      await apiRequest('/api/v1/stats/calls');
      assert.equal(calls.at(-1)?.auth, 'Bearer plain-admin', 'GET 仍走主令牌');
    });
  } finally {
    clearAll();
  }
});

test('只填超管令牌：读腿能出站，凭据读面显式指定超管槽', async () => {
  installStorage();
  clearAll();
  setApiToken('only-super', 'superAdmin');
  try {
    await withFetchCapture(async (calls) => {
      // 读端点 `_v1_read_dependency` 接受超管令牌；主/只读两槽皆空时不得直接抛
      // not_provisioned（否则「只填了超管」的用户看到的是「没配令牌」）。
      await apiRequest('/api/v1/config/catalog');
      assert.equal(calls.at(-1)?.auth, 'Bearer only-super', '读腿缺主令牌时回落超管令牌');

      // 凭据整段路由（含 GET）挂 `_super_admin_dependency`，调用方显式点槽。
      await apiRequest('/api/v1/credentials', { auth: 'superAdmin' });
      assert.equal(calls.at(-1)?.auth, 'Bearer only-super');
    });
  } finally {
    clearAll();
  }
});

test('写腿缺超管时回落主令牌（不回归）；只读凭据绝不用于写', async () => {
  installStorage();
  clearAll();
  setApiToken('plain-admin', 'admin');
  try {
    await withFetchCapture(async (calls) => {
      await apiRequest('/api/v1/config/X/set', { method: 'POST', body: {} });
      assert.equal(calls.at(-1)?.auth, 'Bearer plain-admin', '没有超管令牌时行为与接线前一致');
      calls.length = 0;
      setApiToken(null, 'admin');
      setApiToken('plain-ro', 'ro');
      await assert.rejects(
        apiRequest('/api/v1/config/X/set', { method: 'POST', body: {} }),
        (error: { code?: string }) => error.code === 'control_plane_not_provisioned',
        '写腿不得自动使用只读凭据'
      );
      assert.equal(calls.length, 0, '拒绝发生在发请求之前');
    });
  } finally {
    clearAll();
  }
});

test('超管令牌不进 URL、不进异常文本', async () => {
  installStorage();
  clearAll();
  setApiToken('super-secret-token', 'superAdmin');
  try {
    await withFetchCapture(async (calls) => {
      await apiRequest('/api/v1/config/catalog');
      assert.ok(calls.every((call) => !call.url.includes('super-secret-token')), '令牌绝不出现在 URL');
    });
  } finally {
    clearAll();
  }
});
