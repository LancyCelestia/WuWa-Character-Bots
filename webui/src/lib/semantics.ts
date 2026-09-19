// 数据态 → 判定/派生的纯函数（只有 type-only import，运行时零依赖、零 JSX，可被 `node --test` 直跑）。
// 为什么单独立模块：这三条判据各管一个"说谎面"——把降级说成正常、把未部署说成加载失败、
// 把整段布局说成某个页面坏了。判据一旦只写在 .tsx 里就无法上锁，回归只能靠人眼。
import type { KnowledgeCollection, TokenFamilyRow } from '@/lib/api-client';
import type { DataState } from '@/hooks/use-semantic-query';

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
