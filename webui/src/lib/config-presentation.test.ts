import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CONFIG_BY_KEY,
  CONFIG_FIELDS,
  GROUP_BUCKETS,
  HANDWRITTEN_KEYS,
  KIND_COUNTS,
  SCOPE_COUNTS,
  SECRET_KEYS,
  TIER_COUNTS,
  displayValue,
  resolveRows,
  searchFields,
} from './config-presentation.ts';

// 配置展示层的自洽锁（D 席：参数编辑）。
//
// 硬判据只有一条，但它是用户的原话：**设置页的全局搜索必须能搜到 806 个键里的每一个**。
// 这条锁把它变成可执行的断言——不是「我觉得覆盖全了」，而是「逐个键名搜一遍，全部命中」。
// 运行方式：node --test src/lib/config-presentation.test.ts（Node ≥23 原生类型剥离，零新依赖）。
//
// 本文件只读 webui/ 以内：`config.py` 的字段数不在这里抄死（那会随代码漂移），
// 而是断言「静态表 ≥ 806 且 = 生成物 ∪ 手写物」，跨语言同值对账留给 pytest 侧。

test('键表无重复，且 806 个后端键一个不少', () => {
  const keys = CONFIG_FIELDS.map((field) => field.key);
  assert.equal(new Set(keys).size, keys.length, '存在重复键');
  // 806 = Config.model_fields 的字段数（本仓机器册口径）；外加一枚纯运行时覆盖键。
  assert.ok(CONFIG_FIELDS.length >= 806, `键表只有 ${CONFIG_FIELDS.length} 枚，少于 806`);
  assert.equal(CONFIG_BY_KEY.size, CONFIG_FIELDS.length, 'key 索引与表长不一致');
});

test('每一个键都能被它自己的键名搜到（搜索无死角）', () => {
  const missed: string[] = [];
  for (const field of CONFIG_FIELDS) {
    const hits = searchFields(field.key);
    if (!hits.some((hit) => hit.key === field.key)) missed.push(field.key);
  }
  assert.deepEqual(missed, [], `以下键搜不到：${missed.slice(0, 10).join(', ')}`);
});

test('大小写不敏感：小写键名同样命中', () => {
  for (const field of CONFIG_FIELDS) {
    const hits = searchFields(field.key.toLowerCase());
    assert.ok(hits.some((hit) => hit.key === field.key), `${field.key} 小写搜不到`);
  }
});

test('按分组过滤时，组内键仍全部搜得到', () => {
  for (const group of GROUP_BUCKETS) {
    const hits = searchFields('', group.id);
    assert.equal(hits.length, group.count, `${group.id} 组内条数与桶计数不一致`);
  }
});

test('三档 / 写面 / 控件 的计数与表长一致', () => {
  assert.equal(TIER_COUNTS.T1 + TIER_COUNTS.T2 + TIER_COUNTS.T3, CONFIG_FIELDS.length);
  assert.equal(SCOPE_COUNTS.hot + SCOPE_COUNTS.restart + SCOPE_COUNTS['env-only'], CONFIG_FIELDS.length);
  const kindTotal = Object.values(KIND_COUNTS).reduce((sum, n) => sum + n, 0);
  assert.equal(kindTotal, CONFIG_FIELDS.length);
  // 用户简报点名的 806 键里，至少有一批是真能热改的；一枚都没有说明白名单读错了。
  assert.ok(SCOPE_COUNTS.hot > 0, '没有任何可热改键，SETTABLE_KEYS 大概率没读到');
});

test('手写键全部在表内、档位为 T1、且有像样的中文说明', () => {
  assert.ok(HANDWRITTEN_KEYS.length >= 180, `手写键只有 ${HANDWRITTEN_KEYS.length} 枚`);
  for (const key of HANDWRITTEN_KEYS) {
    const field = CONFIG_BY_KEY.get(key);
    assert.ok(field, `手写键 ${key} 不在表内（拼错或后端已删）`);
    assert.equal(field.tier, 'T1', `${key} 档位不是 T1`);
    assert.ok(field.title.length >= 2, `${key} 缺中文标题`);
    assert.ok(field.desc.length >= 30, `${key} 的说明太短（${field.desc.length} 字）`);
    assert.ok(!/[\u4e00-\u9fa5]/.test(field.key), `${key} 键名含中文`);
    assert.ok(/[\u4e00-\u9fa5]/.test(field.title), `${key} 标题不是中文`);
    assert.ok(/[\u4e00-\u9fa5]/.test(field.desc), `${key} 说明不是中文`);
  }
});

test('每一枚非只读键都带中文标题与说明（T2 也不例外）', () => {
  for (const field of CONFIG_FIELDS) {
    assert.ok(field.title.trim().length > 0, `${field.key} 无标题`);
    assert.ok(field.desc.trim().length > 0, `${field.key} 无说明`);
    assert.ok(/[\u4e00-\u9fa5]/.test(field.desc), `${field.key} 说明不含中文`);
  }
});

test('安全键：只读、脱敏、且覆盖用户简报点名的四枚', () => {
  const required = [
    'BOT_CONTROL_PLANE_TOKEN_SHA256',
    'BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256',
    'BOT_SUPER_ADMIN_USER_IDS',
    'BOT_ADMIN_PROFILES',
  ];
  for (const key of required) {
    const field = CONFIG_BY_KEY.get(key);
    assert.ok(field, `${key} 不在表内`);
    assert.equal(field.kind, 'readonly', `${key} 必须是只读控件`);
    assert.equal(field.secret, true, `${key} 必须标记为脱敏`);
    assert.ok(SECRET_KEYS.includes(key), `${key} 不在安全键清单里`);
  }
  for (const key of SECRET_KEYS) {
    const field = CONFIG_BY_KEY.get(key);
    assert.ok(field, `${key} 不在表内`);
    assert.equal(field.kind, 'readonly', `安全键 ${key} 不能有编辑控件`);
    assert.equal(displayValue('真实值', true).includes('真实值'), false, '脱敏失效');
  }
});

test('可热改键一律不是只读控件（除非是安全键）', () => {
  for (const field of CONFIG_FIELDS) {
    if (field.scope !== 'hot') continue;
    if (field.secret) continue;
    assert.notEqual(field.kind, 'readonly', `可热改键 ${field.key} 却是只读控件`);
  }
});

test('数值控件带边界时 min < max，且 step 为正', () => {
  for (const field of CONFIG_FIELDS) {
    if (field.kind !== 'number') continue;
    if (field.min !== undefined && field.max !== undefined) {
      assert.ok(field.min < field.max, `${field.key} 的 min 不小于 max`);
    }
    if (field.step !== undefined) assert.ok(field.step > 0, `${field.key} 的 step 非正`);
  }
});

test('枚举控件至少两个选项，且值不重复', () => {
  for (const field of CONFIG_FIELDS) {
    if (field.kind !== 'select' && field.kind !== 'multiselect') continue;
    assert.ok(field.options && field.options.length >= 2, `${field.key} 枚举选项不足`);
    const values = field.options?.map((option) => option.value) ?? [];
    assert.equal(new Set(values).size, values.length, `${field.key} 枚举值重复`);
  }
});

test('分组桶覆盖所有键，且每桶计数与实算一致', () => {
  const total = GROUP_BUCKETS.reduce((sum, group) => sum + group.count, 0);
  assert.equal(total, CONFIG_FIELDS.length);
  for (const field of CONFIG_FIELDS) {
    assert.ok(GROUP_BUCKETS.some((group) => group.id === field.group), `${field.key} 的分组 ${field.group} 不在桶里`);
  }
});

test('resolveRows：后端有而静态表没有的键也照样列出来（不许有看不见的键）', () => {
  const rows = resolveRows([
    { key: 'BOT_CHAT_MODEL', value: 'demo-model', version: 3, can_write: true, state: 'override' },
    { key: 'BOT_FUTURE_UNKNOWN_KEY', value: 1, version: 3, can_write: false },
  ]);
  const chat = rows.find((row) => row.field.key === 'BOT_CHAT_MODEL');
  assert.ok(chat);
  assert.equal(chat.canWrite, true);
  assert.equal(chat.overridden, true);
  assert.equal(chat.version, 3);
  const unknown = rows.find((row) => row.field.key === 'BOT_FUTURE_UNKNOWN_KEY');
  assert.ok(unknown, '后端新增键被丢掉了');
  assert.equal(unknown.unknownToCatalog, true);
  assert.equal(unknown.canWrite, false);
});

test('resolveRows：缺 live 行时不猜可写性（一律 false）', () => {
  const rows = resolveRows([]);
  assert.equal(rows.length, CONFIG_FIELDS.length);
  assert.ok(rows.every((row) => row.canWrite === false));
});
