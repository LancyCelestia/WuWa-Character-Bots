import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  describeReason,
  isKnownReason,
  isNotFound,
  KNOWN_REASONS,
  pickEnabledCollections,
  reasonKey,
  toStackRows,
} from './semantics.ts';
import type { KnowledgeCollection, TokenFamilyRow } from '@/lib/api-client';

// 三条「不说谎判据」+ reason 单源与双语镜像的确定性单测（审计 F17 P1-⑦ / F21 / F23-② / UNI1）。
// 运行方式：node --test src/lib/semantics.test.ts（Node ≥23 原生类型剥离，零新依赖）。

type Table = Record<string, unknown>;

function readLocale(dir: string): Table {
  return JSON.parse(readFileSync(new URL(`../locales/${dir}/common.json`, import.meta.url), 'utf-8')) as Table;
}

const zhLocale = readLocale('zh-CN');
const enLocale = readLocale('en');

/** 点号路径取值（i18next 的 keySeparator 默认 '.'，与真运行时同构）。 */
function lookup(table: Table, key: string): string | undefined {
  let cursor: unknown = table;
  for (const part of key.split('.')) {
    if (typeof cursor !== 'object' || cursor === null || !(part in cursor)) return undefined;
    cursor = (cursor as Table)[part];
  }
  return typeof cursor === 'string' ? cursor : undefined;
}

/** i18next 缺省行为夹具：未命中回吐键本身（禁引真 i18n 运行时，保持零依赖确定性）。 */
function makeT(table: Table): (key: string) => string {
  return (key: string) => lookup(table, key) ?? key;
}

const tZh = makeT(zhLocale);

/** 递归收集嵌套键集（叶子记作点号路径），供双语全量对账。 */
function keySet(table: Table, prefix = ''): string[] {
  return Object.entries(table).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) return keySet(value as Table, path);
    return [path];
  });
}

function block(value: number | null) {
  return { value, known_rows: value === null ? 0 : 1, unknown_rows: value === null ? 1 : 0, quality: value === null ? ('unknown' as const) : ('complete' as const) };
}

function family(input: number | null, output: number | null, cacheRead: number | null, cacheCreation: number | null): TokenFamilyRow {
  return {
    family: 'model-x',
    calls: 1,
    tokens: { input: block(input), output: block(output), cache_read: block(cacheRead), cache_creation: block(cacheCreation) },
  };
}

function collection(enabled: boolean): KnowledgeCollection {
  return { id: 'c', name: 'n', description: '', enabled, source: 's', count: null, reason: null };
}

test('isNotFound：404 状态码判为「端点未部署」，且必须在控制面统一文案下仍然成立', () => {
  // 控制面把 404 包成统一 message（_app.py），旧实现按 /HTTP 404/ 匹配文案 → 恒不命中。
  assert.equal(isNotFound({ phase: 'error', message: '请求的资源或操作不可用。', status: 404 }), true);
  assert.equal(isNotFound({ phase: 'error', message: 'HTTP 404: Not Found' }), false); // 只有文案不算
  assert.equal(isNotFound({ phase: 'error', message: 'x', status: 500 }), false);
  assert.equal(isNotFound({ phase: 'error', message: 'x', status: 422 }), false);
  assert.equal(isNotFound({ phase: 'loading' }), false);
  assert.equal(isNotFound({ phase: 'ok', data: {} }), false);
});

test('pickEnabledCollections：只留启用项，异常输入降级为空而不抛错', () => {
  assert.deepEqual(pickEnabledCollections([collection(true), collection(false)]).length, 1);
  assert.deepEqual(pickEnabledCollections([]), []);
  assert.deepEqual(pickEnabledCollections(null), []);
  assert.deepEqual(pickEnabledCollections(undefined), []);
  // 后端字段漂移出 null 元素时不得炸整棵布局（AppShell 在错误边界之外）。
  assert.deepEqual(pickEnabledCollections([null] as unknown as KnowledgeCollection[]), []);
});

test('toStackRows：缓存是输入的子集，堆叠段和恒等于输入+输出（不双计）', () => {
  const [row] = toStackRows([family(100, 20, 30, 10)]);
  assert.equal(row.uncached, 60);
  assert.equal(row.cache_read, 30);
  assert.equal(row.cache_creation, 10);
  assert.equal(row.output, 20);
  const sum = (row.uncached ?? 0) + (row.cache_read ?? 0) + (row.cache_creation ?? 0) + (row.output ?? 0);
  assert.equal(sum, 120); // 100 + 20，而非旧写法的 160
});

test('toStackRows：缓存未上报按 0 处理，输入原样保留', () => {
  const [row] = toStackRows([family(100, 20, null, null)]);
  assert.equal(row.uncached, 100);
  assert.equal(row.cache_read, null);
  assert.equal(row.cache_creation, null);
});

test('toStackRows：输入未知则各段未知（绝不拿 0 冒充 0 个 token）', () => {
  const [row] = toStackRows([family(null, null, null, null)]);
  assert.equal(row.uncached, null);
  assert.equal(row.output, null);
});

test('toStackRows：缓存之和反超输入（数据自相矛盾）时不拆段，宁少一层信息也不画不成立的柱', () => {
  const [row] = toStackRows([family(50, 20, 60, 10)]);
  assert.equal(row.uncached, 50);
  assert.equal(row.cache_read, null);
  assert.equal(row.cache_creation, null);
  assert.equal(row.output, 20);
});

test('toStackRows：族顺序与 family 原样透传（含无名族 null）', () => {
  const rows = toStackRows([family(10, 1, 0, 0), { ...family(1, 1, 0, 0), family: null }]);
  assert.deepEqual(rows.map((row) => row.family), ['model-x', null]);
});

// ---------------------------------------------------------------------------
// reason 码 → 人话的单源锁（UNI1 收口：白名单 + 取词从 semantic-state.tsx 上收，
// 并消灭 plugins.tsx 绕过白名单的第三套实现）。
// ---------------------------------------------------------------------------

test('reason 白名单：无重复、逐项在双语 locale 有值（加码不改文案即红）', () => {
  assert.equal(new Set(KNOWN_REASONS).size, KNOWN_REASONS.length, '白名单有重复码');
  for (const code of KNOWN_REASONS) {
    assert.ok(lookup(zhLocale, `reason.${code}`), `zh 缺 reason.${code}`);
    assert.ok(lookup(enLocale, `reason.${code}`), `en 缺 reason.${code}`);
    assert.equal(reasonKey(code), `reason.${code}`);
    assert.equal(isKnownReason(code), true);
  }
});

test('reason 三向对账：白名单 == zh 键集 == en 键集（三份镜像单向漂移即红）', () => {
  const zhKeys = Object.keys((zhLocale as { reason: Table }).reason).sort();
  const enKeys = Object.keys((enLocale as { reason: Table }).reason).sort();
  const whitelist = [...KNOWN_REASONS].sort();
  assert.deepEqual(zhKeys, whitelist, 'zh reason 键集与白名单不等');
  assert.deepEqual(enKeys, zhKeys, 'en reason 键集与 zh 不等');
});

test('describeReason：已知码译成人话、未知码原样透出、空值空串（绝不编语义）', () => {
  assert.equal(describeReason('missing_table', tZh), '数据表不存在（该能力尚未产生过记录）');
  assert.equal(describeReason('brand_new_backend_reason', tZh), 'brand_new_backend_reason');
  assert.equal(describeReason('domains_dir_unavailable', tZh), 'domains 目录不可用'); // plugins 页组级码同表
  assert.equal(describeReason(null, tZh), '');
  assert.equal(describeReason(undefined, tZh), '');
  assert.equal(describeReason('', tZh), '');
});

test('describeReason：locale 缺键时回退原码，绝不把 i18n 键本身甩上屏（收口前 SemanticState 会）', () => {
  const passthroughT = (key: string) => key; // t 回吐键本身 = locale 缺该键
  assert.equal(describeReason('missing_source', passthroughT), 'missing_source');
  // 收口前的渲染面写法（`key ? t(key) : reason`）在此会把 "reason.missing_source" 显示给用户。
  const legacy = (reason: string): string => (reasonKey(reason) ? passthroughT(reasonKey(reason)) : reason);
  assert.equal(legacy('missing_source'), 'reason.missing_source');
});

test('收口前后逐码等输出：dashboard 一行式与 plugins 绕行实现的新旧口径完全一致', () => {
  const cases: Array<string | null> = [...KNOWN_REASONS, 'not_a_real_code', ''];
  for (const reason of cases) {
    // 旧 dashboard.fallbackLine 的 unavailable 分支。
    const legacyDashboard = (value: string | null): string => {
      const key = value ? reasonKey(value) : '';
      if (key) {
        const translated = tZh(key);
        if (translated !== key) return `暂无数据：${translated}`;
      }
      return `暂无数据：${value ?? ''}`;
    };
    // 旧 plugins.reasonText（绕过白名单直查 i18n）。
    const legacyPlugins = (value: string | null): string => {
      if (!value) return '';
      const key = `reason.${value}`;
      const translated = tZh(key);
      return translated === key ? `：${value}` : `：${translated}`;
    };
    assert.equal(
      `暂无数据：${describeReason(reason, tZh)}`,
      legacyDashboard(reason),
      `dashboard 口径漂移：${reason}`
    );
    const suffix = describeReason(reason, tZh);
    assert.equal(suffix ? `：${suffix}` : '', legacyPlugins(reason), `plugins 口径漂移：${reason}`);
  }
});

test('降级四态主文案双语齐备且逐字不动（webui_acceptance.py COMMON_GRACEFUL 判据串键位锁）', () => {
  for (const key of ['noData', 'loadFailed', 'notProvisioned', 'authFailed']) {
    assert.ok(lookup(zhLocale, `state.${key}`) && lookup(enLocale, `state.${key}`), `state.${key} 双语缺键`);
  }
  // 验收脚本按渲染后的中文文本判「优雅降级」，这四串逐字不可改（改词必须同步脚本）。
  assert.equal(lookup(zhLocale, 'state.noData'), '暂无数据');
  assert.equal(lookup(zhLocale, 'state.loadFailed'), '加载失败');
  assert.equal(lookup(zhLocale, 'state.notProvisioned'), '控制面未配置访问令牌');
  assert.equal(lookup(zhLocale, 'state.authFailed'), '令牌无效或无权限');
});

test('双语全键集对账：zh-CN 与 en 的嵌套键集双向零缺漏（加/删键必须同批改两份）', () => {
  const zhKeys = keySet(zhLocale);
  const enKeys = keySet(enLocale);
  const zhOnly = zhKeys.filter((key) => !enKeys.includes(key));
  const enOnly = enKeys.filter((key) => !zhKeys.includes(key));
  assert.deepEqual(zhOnly, [], `zh 独有键（en 未同步）：${zhOnly.join(', ')}`);
  assert.deepEqual(enOnly, [], `en 独有键（zh 未同步）：${enOnly.join(', ')}`);
  assert.ok(zhKeys.length > 0, '键集为空 = locale 文件被清空，对账失去意义');
});
