import { apiRequest } from './api-client';
export interface VisualElement { id?: string; kind: string; data: Record<string, unknown>; binding?: Record<string, string> }
export interface VisualDocument { version: number; id?: string; title: string; subtitle?: string; footer?: string; layout: string; elements: VisualElement[]; bindings?: Array<{ path: string; value: string }>; style?: { size?: string; spacing?: number; weight?: string; color?: string } }
/**
 * 目录（登记面只读投影，真身 `VisualLayoutService.catalog()`）。
 * `platforms`/`global_platform`（W12 R3(a)）：平台轴清单**从后端拉**——此前页面写死
 * `'qq'`，而生产摄取写的是 `onebot`，两边永不相等 ⇒ 保存了却永不生效。
 * `fragments`/`fragment_limits`（W12 R4）：受限模板片段的白名单与字数上限。
 * `theme_keys`/`theme_choices`（W12 R4）：全局 token 可改面与登记值域。
 */
export interface VisualCatalog { spec_version: number; kinds: string[]; style: { sizes: string[]; spacing: number[]; weights: string[]; colors: string[] }; binding_paths: Record<string, string>; platforms?: string[]; global_platform?: string; fragments?: string[]; fragment_limits?: Record<string, number>; theme_keys?: string[]; theme_choices?: { shell_radius?: number[]; font_family?: string[] } }
export interface LayoutScope { platform: string; instance: string; group: string; card: string }
/** 受限模板片段：**只有**这三键纯文本（no HTML/CSS injection）。 */
export type VisualFragments = Partial<Record<'title' | 'subtitle' | 'footer', string>>;
/**
 * 布局响应并集。真身＝`visual_layouts.py`：
 * - `read()` → `{scope, source, version, spec, fragments, exact_version, inherited_version, next_version, fallback_scope}`
 *   · `version`＝**生效行**版本（可能是继承来的平台默认行或全局面）；
 *   · `exact_version`＝**本 scope 精确行**版本（从未写过＝0）；
 *   · `next_version`＝`exact_version`（**不是**当前+1）；
 *   · `source ∈ exact|platform|global|none`（`global` 是 W12 R3 新增的最后一跳）；
 *   · `fallback_scope`＝命中的那一跳的 scope（`source==='none'` 时为 null）；
 *   · `inherited_version` 仅 source∈{platform,global} 时非空。
 * - `save()` → `{scope, version, next_version, spec, fragments, degraded, actor}`（**无** `source`/`exact_version`），
 *   `version`＝`next_version`＝刚写入的新版本（旧+1）。
 * - `reset()` → `{scope, version, next_version, spec:null, fragments:{}, tombstone:true, actor}`（同上）。
 * 故 `source` 必须可选：save/reset 不发它。
 */
export interface LayoutResult { version: number; source?: string; exact_version?: number; next_version?: number; inherited_version?: number | null; spec: VisualDocument | null; fragments?: VisualFragments; degraded?: string[]; tombstone?: boolean; actor?: string; fallback_scope?: LayoutScope | null }
/** 全局视觉覆盖（W12 R4）：主色 / 圆角 / 字体，只收登记值域。 */
export interface VisualTheme { brand_accent?: string; shell_radius?: number; font_family?: string }
export interface VisualThemeResult { version: number; next_version?: number; overrides: VisualTheme; action?: string; actor?: string; history?: Array<{ version: number; action: string; overrides: VisualTheme; actor: string; created_at: string }> }
/**
 * 下一次写（save/reset）应带的 `expected_version`。真身 CAS：`_write()` 只与本 scope
 * **精确行**版本比（`current = 精确行 version or 0`），不等即 409。
 * - `read`：用 `exact_version`（**不能**用 `version`——`source==='platform'` 时 version 是继承来的
 *   平台默认行版本，拿去写必 409；`next_version` 恰等于 `exact_version`，等价可用）；
 * - `save`/`reset`：`exact_version` 缺席 ⇒ 落 `next_version`＝`version`（新写的当前版本）。
 * 单槽表达式同时覆盖两形：`exact_version ?? next_version ?? version`。
 */
export function nextExpectedVersion(result: LayoutResult): number {
  return result.exact_version ?? result.next_version ?? result.version;
}
/** 生效来源的人话（三跳 + 未命中；`fallback_scope` 用来点名是哪一层在生效）。 */
export function describeSource(result: LayoutResult): string {
  const scope = result.fallback_scope;
  const where = scope ? `（平台 ${scope.platform}${scope.instance ? ` / 实例 ${scope.instance}` : ''}${scope.group ? ` / 会话 ${scope.group}` : ''}${scope.card ? ` / 卡片 ${scope.card}` : ''}）` : '';
  if (result.source === 'exact') return `精确作用域行${where}`;
  if (result.source === 'platform') return `继承平台默认面${where}`;
  if (result.source === 'global') return `继承全局面 *${where}`;
  return '没有任何一层布局生效（全局面也未设置）';
}
export function moveElement<T>(values: readonly T[], from: number, to: number): T[] {
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= values.length || to >= values.length) return [...values];
  const result = [...values]; const [value] = result.splice(from, 1); result.splice(to, 0, value); return result;
}
export function newElement(kind: string): VisualElement {
  // 图表 `series` 真身＝`visual_spec.py` `_series()` 的 `list[list[float]]`（非 list 的列整列丢弃）
  // ⇒ 必须给**嵌套**数值序列，扁平 [1,2,3] 会被后端静默清空。
  const content: Record<string, Record<string, unknown>> = {
    text: { text: '新的段落' }, kv: { label: '指标', value: '—' }, stat: { label: '统计', value: '—', unit: '' },
    list: { items: ['项目一', '项目二'] }, table: { columns: ['名称', '数值'], rows: [['示例', '—']] },
    badge: { text: '状态', tone: 'info' }, progress: { label: '进度', value: 0, max: 100 }, divider: {},
    'chart.line': { labels: ['一', '二', '三'], series: [[1, 2, 3]] },
    'chart.box': { labels: ['一', '二', '三'], series: [[1, 2, 3]] },
    'chart.bar': { labels: ['一', '二'], series: [[1, 2]] },
  };
  return { kind, data: content[kind] ?? {} };
}
export type VisualStyleKey = 'size' | 'spacing' | 'weight' | 'color';
/**
 * 改一维样式并**去掉清空的键**（`value === ''` ⇒ 删键，绝不写空串或 `Number('') === 0`）。
 * 后端 `_normalize_style` 把 `''`/`0` 读作「不覆盖」，但前端若留下 `spacing: 0` 就与
 * 「未设置」不可区分，且 `Number('') === 0` 是假值陷阱。返回新 spec，不改入参；四键严格类型。
 */
export function updateStyle(spec: VisualDocument, key: VisualStyleKey, value: string): VisualDocument {
  const style: NonNullable<VisualDocument['style']> = { ...(spec.style ?? {}) };
  const cleared = value === '';
  if (key === 'spacing') {
    if (cleared) delete style.spacing;
    else {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) style.spacing = parsed;
    }
  } else if (key === 'size') {
    if (cleared) delete style.size;
    else style.size = value;
  } else if (key === 'weight') {
    if (cleared) delete style.weight;
    else style.weight = value;
  } else if (cleared) {
    delete style.color;
  } else {
    style.color = value;
  }
  return { ...spec, style };
}
/**
 * 受限片段 → 请求体：**空串删键**（与样式同口径：空 ≠ 想写空标题，是不覆盖）。
 * 纯函数，不改入参。
 */
export function fragmentsPayload(fragments: VisualFragments): VisualFragments {
  const out: VisualFragments = {};
  for (const [key, value] of Object.entries(fragments)) {
    const text = (value ?? '').trim();
    if (text) out[key as keyof VisualFragments] = text;
  }
  return out;
}
/**
 * 下拉空值 → `undefined`（＝清空），非空 → 数字。**不做** `Number('')===0` 假值陷阱：
 * 空串代表「不覆盖」，与 `updateStyle` 同口径。纯函数。
 */
export function numberOrClear(value: string): number | undefined {
  if (value.trim() === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
/**
 * 四轴作用域 → 稳定串（与 `/layout` 读请求查询串同源，字段序固定）。纯函数、无 token/env；
 * 供 async 结果与「发起时的作用域」关联，防旧响应覆盖新作用域。
 */
export function scopeKey(scope: LayoutScope): string {
  return new URLSearchParams([['platform', scope.platform], ['instance', scope.instance], ['group', scope.group], ['card', scope.card]]).toString();
}
export const visualApi = {
  catalog: () => apiRequest<VisualCatalog>('/api/v1/visual/catalog'),
  read: (scope: LayoutScope) => apiRequest<LayoutResult>(`/api/v1/visual/layout?${scopeKey(scope)}`),
  save: (scope: LayoutScope, spec: VisualDocument, version: number, fragments?: VisualFragments) => apiRequest<LayoutResult>('/api/v1/visual/layout', { method: 'POST', body: { scope, spec, expected_version: version, fragments } }),
  reset: (scope: LayoutScope, version: number) => apiRequest<LayoutResult>('/api/v1/visual/layout/reset', { method: 'POST', body: { scope, expected_version: version } }),
  preview: (spec: VisualDocument, fragments?: VisualFragments) => apiRequest<{ html: string; degraded: string[]; fragments?: VisualFragments }>('/api/v1/visual/preview', { method: 'POST', body: { spec, fragments } }),
  theme: () => apiRequest<VisualThemeResult>('/api/v1/visual/theme'),
  saveTheme: (overrides: VisualTheme, version: number) => apiRequest<VisualThemeResult>('/api/v1/visual/theme', { method: 'POST', body: { overrides, expected_version: version } }),
  rollbackTheme: (version: number) => apiRequest<VisualThemeResult>('/api/v1/visual/theme/rollback', { method: 'POST', body: { expected_version: version } }),
};
