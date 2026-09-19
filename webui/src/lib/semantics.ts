// 数据态 → 判定/派生/措辞的纯函数（只有 type-only import，运行时零依赖、零 JSX，可被 `node --test` 直跑）。
// 为什么单独立模块：这些判据各管一个"说谎面"——把降级说成正常、把未部署说成加载失败、
// 把后端码字直接甩给用户、把整段布局说成某个页面坏了。判据一旦只写在 .tsx 里就无法上锁，
// 回归只能靠人眼；写进本文件即由 `semantics.test.ts` 常驻钉死。
import type { KnowledgeCollection, TokenFamilyRow } from '@/lib/api-client';
import type { DataState } from '@/hooks/use-semantic-query';
import type { Translate } from '@/lib/labels';

/**
 * 404 =「该端点不在当前运行的构建里」（能力未部署 / 代码未重启），必须与「加载失败」分开说。
 * 判据走结构化状态码：控制面 `_app.py` 的 HTTPException 处理器把 404 也包成统一 message
 * （「请求的资源或操作不可用。」），早先按 `/HTTP 404/` 匹配文案的写法自那以后恒不命中——
 * 三张「未部署」卡就此成了不可达代码（F23 实证，此处收口为单一事实源）。
 */
export function isNotFound(state: DataState<unknown>): boolean {
  return state.phase === 'error' && state.status === 404;
}

/**
 * `source_unavailable` 的 reason 码 → 人话：**白名单 + 取词**的单一事实源
 * （审计 F23 §一.2 收口件）。
 *
 * 收口前四套实现：① `semantic-state.tsx` 的 `reasonKey`（唯一白名单，但住在组件里）
 * ② `dashboard.tsx` 的 `fallbackLine`（借 ① 再自己拼一次回退）
 * ③ `plugins.tsx` 的 `reasonText`（**绕过白名单**直查 `reason.<码>`）
 * ④ 两份 locale 的 `reason.*`（文案镜像）。
 * 后果：后端加一个码只改 locale，①③ 两套口径立刻分叉（①显原码、③显译文）；
 * 反之只改白名单则 locale 缺键，i18next 把键本身 `reason.xxx` 甩到屏幕上。
 * 现在：白名单只此一份，取词只此一处，三份镜像的等值由 `semantics.test.ts` 双向对账钉死。
 *
 * 真相源 = 控制面各失败面（逐项可溯源，F23 §一.2 已 grep 实证 18/18）：
 * `_stats`/`metrics` 的 `_failure('source_unavailable', …)`、`webui_knowledge.py`、
 * `webui_plugins.py`、`webui_memory_graph.py`。
 */
export const KNOWN_REASONS = [
  'audit_source_not_configured',
  'affinity_source_not_configured',
  'missing_source',
  'missing_table',
  'incomplete_schema',
  'query_budget_exceeded',
  'read_failed',
  'not_connected',
  'not_persisted',
  // PAGES2 增补（真相源=webui_knowledge/webui_plugins/webui_memory_graph 失败面）
  'collection_not_available',
  'all_sources_missing',
  'glossary_source_unavailable',
  'disabled_by_config',
  'features_store_unavailable',
  'static_config_unavailable',
  'cross_process_introspection_unavailable',
  'domains_dir_unavailable',
  'unreadable',
] as const;

export type KnownReason = (typeof KNOWN_REASONS)[number];

const KNOWN_REASON_SET: ReadonlySet<string> = new Set<string>(KNOWN_REASONS);

/** reason 码 → i18n 键；**未知码返回空串**（调用方据此回退原码，绝不编语义）。 */
export function reasonKey(reason: string): string {
  return KNOWN_REASON_SET.has(reason) ? `reason.${reason}` : '';
}

/** 某 reason 码是否已登记（供「后端产出 ⊆ 白名单」「白名单 == locale 键集」两类断言引用）。 */
export function isKnownReason(reason: string): boolean {
  return KNOWN_REASON_SET.has(reason);
}

/**
 * reason 码 → 一行人话（**无前缀**：「暂无数据：」「：」这类外壳由渲染面自拼）。
 *
 * - null / undefined / 空串 → `''`（无话可说，调用方不渲染该行）。
 * - 已知码且文案在位 → 译文。
 * - 已知码但 locale 缺该键（`t` 回吐键本身）→ 回退原码：诚实，绝不把 `reason.xxx` 甩上屏。
 * - 未知码（后端新增/漂移）→ 原样透出码字：既有语义，测试锁死不得改。
 * - 永不抛异常、永不做字符串猜测。
 */
export function describeReason(reason: string | null | undefined, t: Translate): string {
  if (typeof reason !== 'string' || reason.length === 0) return '';
  const key = reasonKey(reason);
  if (!key) return reason;
  const translated = t(key);
  return translated === key ? reason : translated;
}

/**
 * 侧栏知识库子分组的取数后派生。items 缺失/非数组按「不渲染子分组」降级，
 * 绝不在这里抛——AppShell 位于 RouteErrorBoundary **之外**（它是边界的主人），
 * 此处抛错会把整棵布局连带已加载的页一起卸载（F17 P1-⑦）。
 */
export function pickEnabledCollections(
  items: KnowledgeCollection[] | null | undefined
): KnowledgeCollection[] {
  if (!Array.isArray(items)) return [];
  return items.filter((item) => item?.enabled);
}

/**
 * Token 堆叠段换算（F21 双计根修）。
 * 账本 prompt_tokens 恒含缓存子集——结算就是 `billed_input = prompt − cache_read − cache_write`
 * （`llm_engine/ledger.py`），所以四项直接堆叠会把缓存算两遍、柱长虚高。
 * 堆叠段改成「非缓存输入 / 读缓存 / 建缓存 / 输出」后，段和 = 输入 + 输出，
 * 缓存退为输入的一段而非额外一项。
 * 缓存行未上报按 0 处理（少算好过虚增）；缓存之和反超输入（数据自相矛盾）则不拆段、
 * 原样显示输入——宁可少一层信息，也不画一根数学上不成立的柱。
 */
export interface TokenStackRow {
  family: string | null;
  uncached: number | null;
  cache_read: number | null;
  cache_creation: number | null;
  output: number | null;
}

export function toStackRows(families: TokenFamilyRow[]): TokenStackRow[] {
  return families.map((row) => {
    const input = row.tokens.input.value;
    const cacheRead = row.tokens.cache_read.value ?? 0;
    const cacheWrite = row.tokens.cache_creation.value ?? 0;
    const consistent = input === null || cacheRead + cacheWrite <= input;
    return {
      family: row.family,
      uncached: input === null || !consistent ? input : input - cacheRead - cacheWrite,
      cache_read: consistent ? row.tokens.cache_read.value : null,
      cache_creation: consistent ? row.tokens.cache_creation.value : null,
      output: row.tokens.output.value,
    };
  });
}
