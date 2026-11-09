// 配置展示层的**唯一聚合入口**（D 席：参数编辑）。
//
// 三件事，只做这三件：
//   ① 把「生成物」与「手写物」拼成一张 807 键的表（`CONFIG_FIELDS`）；
//   ② 给设置页提供分组、搜索、以及控件/档位的展示词；
//   ③ 把「静态说明」与「live catalog 的当前值/版本/可写性」合并成一行可渲染的数据。
//
// 🔴 边界：这里**不**判断某枚键能不能写。可写性唯一真身是后端 `catalog()` 现算的
// `can_write`（= 在 SETTABLE_KEYS 且角色够）。本文件的 `scope` 只是静态归属，用来解释
// 「为什么这个控件是灰的」，不构成授权。
import { CONFIG_GROUPS, type ConfigGroup } from './config-presentation/groups.ts';
import { GENERATED_FIELDS } from './config-presentation/catalog.ts';
import { displayTitle, configTitleFor } from './humanize.ts';
import { T1_GROUPS, T1_META } from './config-presentation/t1-meta.ts';
import { CHAT_HANDWRITTEN } from './config-presentation/handwritten/chat.ts';
import { SOCIAL_HANDWRITTEN } from './config-presentation/handwritten/social.ts';
import { CONTENT_HANDWRITTEN } from './config-presentation/handwritten/content.ts';
import { SERVICES_HANDWRITTEN } from './config-presentation/handwritten/services.ts';
import { OPS_HANDWRITTEN } from './config-presentation/handwritten/ops.ts';
import type { ChangeScope, ConfigField, ControlKind, HandwrittenEntry, Tier } from './config-presentation/types.ts';

export type { ChangeScope, ConfigField, ConfigOption, ControlKind, HandwrittenEntry, Tier } from './config-presentation/types.ts';
export type { ConfigGroup } from './config-presentation/groups.ts';
export { CONTROL_KIND_LABEL, TIER_LABEL } from './config-presentation/types.ts';
export { CONFIG_GROUPS } from './config-presentation/groups.ts';

/** 全部手写条目：分组文件各自维护，这里只按 key 摊平。 */
const HANDWRITTEN: Record<string, HandwrittenEntry> = {
  ...CHAT_HANDWRITTEN,
  ...SOCIAL_HANDWRITTEN,
  ...CONTENT_HANDWRITTEN,
  ...SERVICES_HANDWRITTEN,
  ...OPS_HANDWRITTEN,
};

/** 手写键清单（导出给覆盖率测试与报告用）。 */
export const HANDWRITTEN_KEYS: readonly string[] = Object.freeze(Object.keys(HANDWRITTEN).sort());

function materialize(key: string, entry: HandwrittenEntry): ConfigField {
  const meta = T1_META[key];
  return {
    key,
    title: entry.title,
    desc: entry.desc,
    group: T1_GROUPS[key] ?? 'misc',
    kind: entry.kind,
    tier: 'T1',
    scope: meta?.scope ?? 'env-only',
    type: meta?.type ?? 'str',
    default: meta?.default ?? '',
    ...(entry.min === undefined ? {} : { min: entry.min }),
    ...(entry.max === undefined ? {} : { max: entry.max }),
    ...(entry.step === undefined ? {} : { step: entry.step }),
    ...(entry.unit === undefined ? {} : { unit: entry.unit }),
    ...(entry.options === undefined ? {} : { options: entry.options }),
    ...(entry.secret === undefined ? {} : { secret: entry.secret }),
  };
}

/**
 * 全量配置表：生成物 + 手写物（手写覆盖同键的生成条目，档位升为 T1）。
 *
 * 为什么静态聚合而不是按分组懒加载：设置页的硬判据是「全局搜索能搜到每一枚键」，
 * 懒加载会让未展开分组的键搜不到。数据是纯字符串常量，gzip 后约 20KB，
 * 换来搜索一次命中——这是刻意的取舍。
 */
export const CONFIG_FIELDS: readonly ConfigField[] = Object.freeze(
  (() => {
    const out: ConfigField[] = [];
    const seen = new Set<string>();
    for (const key of Object.keys(HANDWRITTEN).sort()) {
      out.push(materialize(key, HANDWRITTEN[key]));
      seen.add(key);
    }
    for (const field of GENERATED_FIELDS) {
      if (seen.has(field.key)) continue;
      // T2/T3 的标题是生成器「切词 + 首字母大写」拼出来的假中文（`键·Aiprc`、`Safetyexec·开关`）。
      // 呈现前统一按键名重推一次；T1 是人手写的，displayTitle 一个字都不动。
      out.push({ ...field, title: displayTitle(field.key, field.title, field.tier === 'T1') });
      seen.add(field.key);
    }
    return out;
  })(),
);

/** key → 静态规格。搜索与渲染都走这一张。 */
export const CONFIG_BY_KEY: ReadonlyMap<string, ConfigField> = new Map(
  CONFIG_FIELDS.map((field) => [field.key, field]),
);

export interface GroupBucket extends ConfigGroup {
  count: number;
  hotCount: number;
}

/** 侧栏用的分组桶（计数现算，不抄生成期快照）。 */
export const GROUP_BUCKETS: readonly GroupBucket[] = Object.freeze(
  (() => {
    const counts = new Map<string, { count: number; hot: number }>();
    for (const field of CONFIG_FIELDS) {
      const bucket = counts.get(field.group) ?? { count: 0, hot: 0 };
      bucket.count += 1;
      if (field.scope === 'hot') bucket.hot += 1;
      counts.set(field.group, bucket);
    }
    return CONFIG_GROUPS.filter((group) => counts.has(group.id)).map((group) => ({
      ...group,
      count: counts.get(group.id)?.count ?? 0,
      hotCount: counts.get(group.id)?.hot ?? 0,
    }));
  })(),
);

/** 三档覆盖度现算（报告与页面角标共用；不手写数字，避免漂移）。 */
export const TIER_COUNTS: Readonly<Record<Tier, number>> = Object.freeze(
  CONFIG_FIELDS.reduce<Record<Tier, number>>(
    (acc, field) => {
      acc[field.tier] += 1;
      return acc;
    },
    { T1: 0, T2: 0, T3: 0 },
  ),
);

/** 写面归属现算。 */
export const SCOPE_COUNTS: Readonly<Record<ChangeScope, number>> = Object.freeze(
  CONFIG_FIELDS.reduce<Record<ChangeScope, number>>(
    (acc, field) => {
      acc[field.scope] += 1;
      return acc;
    },
    { hot: 0, restart: 0, 'env-only': 0 },
  ),
);

/** 控件形态现算（报告里「N 种控件」就是这张表的非零项）。 */
export const KIND_COUNTS: Readonly<Record<ControlKind, number>> = Object.freeze(
  CONFIG_FIELDS.reduce<Record<ControlKind, number>>(
    (acc, field) => {
      acc[field.kind] += 1;
      return acc;
    },
    { switch: 0, number: 0, select: 0, multiselect: 0, text: 0, code: 0, readonly: 0 },
  ),
);

/** 安全键清单（脱敏 + 只读）。 */
export const SECRET_KEYS: readonly string[] = Object.freeze(
  CONFIG_FIELDS.filter((field) => field.secret).map((field) => field.key).sort(),
);

/**
 * 搜索：键名 / 中文标题 / 中文说明 / 分组名，全部大小写不敏感。
 *
 * 判据是「806 个键里的每一个都搜得到」——所以键名匹配**必须**是前缀优先的全串包含，
 * 且中文说明也进面（用户常常只记得「那个控制概率的」）。
 */
export function searchFields(query: string, groupId?: string): readonly ConfigField[] {
  const needle = query.trim().toLowerCase();
  const pool = groupId ? CONFIG_FIELDS.filter((field) => field.group === groupId) : CONFIG_FIELDS;
  if (!needle) return pool;
  const groupName = new Map(CONFIG_GROUPS.map((group) => [group.id, group.name]));
  return pool.filter((field) => {
    const haystack = `${field.key}\n${field.title}\n${field.desc}\n${groupName.get(field.group) ?? ''}`.toLowerCase();
    return haystack.includes(needle);
  });
}

/** 写面归属的**短**标签（行头徽标用；长解释见 SCOPE_HINT）。 */
export const SCOPE_LABEL: Record<ChangeScope, string> = {
  hot: '可热改',
  restart: '需重启',
  'env-only': '仅展示',
};

/** 写面归属的中文解释（控件为什么是灰的，就靠这一句）。 */
export const SCOPE_HINT: Record<ChangeScope, string> = {
  hot: '可热改：提交后下一轮立即生效',
  restart: '需改 .env 并重启：运行中热改不会被读取',
  'env-only': '仅展示：未登记写面，改 .env 后重启也不保证生效',
};

/**
 * live catalog 的一行（后端 `catalog()` 的 DTO 子集）。字段名与 `lib/control-center.ts`
 * 的 `ConfigRow` 对齐——那边是 HTTP DTO 的真身，这里只取本页用得到的几枚。
 */
export interface LiveRow {
  key: string;
  value?: unknown;
  type?: string;
  version?: number;
  can_write?: boolean;
  writable?: boolean;
  sensitive?: boolean;
  tier?: string;
  hot_reload?: boolean;
  restart_required?: boolean;
  state?: string;
  source?: string;
  default_source?: unknown;
}

/** 一行最终可渲染的数据：静态说明 + live 现值。 */
export interface ResolvedRow {
  field: ConfigField;
  /** 静态表里没有这枚键（后端新增、前端还没跟上）——仍然展示，不隐藏。 */
  unknownToCatalog: boolean;
  value: unknown;
  version: number;
  /** 后端现算的可写性；缺 live 行时一律 false（不猜）。 */
  canWrite: boolean;
  sensitive: boolean;
  source: string;
  state: string;
  /** 值是否与默认不同（覆盖态）。 */
  overridden: boolean;
}

export function resolveRows(live: readonly LiveRow[]): ResolvedRow[] {
  const liveByKey = new Map(live.map((row) => [row.key.toUpperCase(), row]));
  const rows: ResolvedRow[] = [];
  for (const field of CONFIG_FIELDS) {
    const hit = liveByKey.get(field.key);
    rows.push({
      field,
      unknownToCatalog: false,
      value: hit?.value,
      version: hit?.version ?? 0,
      canWrite: Boolean(hit?.can_write),
      sensitive: Boolean(hit?.sensitive) || Boolean(field.secret),
      source: hit?.source ?? 'config',
      state: hit?.state ?? 'default',
      overridden: hit?.state === 'override',
    });
  }
  // 后端有、静态表没有：照样列出来（否则就是「看不见的键」）。
  for (const row of live) {
    const key = row.key.toUpperCase();
    if (CONFIG_BY_KEY.has(key)) continue;
    rows.push({
      field: {
        key,
        // 后端新增、前端还没登记中文说明：标题仍要按键名推一次中文，不能把键名直接当标题。
        title: configTitleFor(key),
        desc: '这枚键后端已经声明，但前端展示表还没有登记中文说明。它仍然可以被搜索到。',
        group: 'misc',
        kind: 'readonly',
        tier: 'T3',
        scope: 'env-only',
        type: row.type ?? 'str',
        default: '',
      },
      unknownToCatalog: true,
      value: row.value,
      version: row.version ?? 0,
      canWrite: Boolean(row.can_write),
      sensitive: Boolean(row.sensitive),
      source: row.source ?? 'config',
      state: row.state ?? 'default',
      overridden: row.state === 'override',
    });
  }
  return rows;
}

/** 值的人话呈现（不引入新格式，只做「null/undefined/对象」三态收敛）。 */
export function displayValue(value: unknown, sensitive: boolean): string {
  if (sensitive) return '••••••（已脱敏）';
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value === '' ? '（空）' : value;
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
