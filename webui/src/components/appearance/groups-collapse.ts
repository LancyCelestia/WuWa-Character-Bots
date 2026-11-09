// 分组折叠的**纯逻辑**（W13 执行席 V2）。
//
// 为什么单开一个 .ts：`groups.tsx` 是 JSX，`node --test` 解析不了；而「默认展开几组、
// 目录点击后哪几组是开的」正是整页高度（1440 下曾 18,998px）的唯一决定因素。
// 判据落在这里，才能被 `w13-v2-contract.test.ts` 直接调用，而不是靠 grep 源码猜。
// 同目录的 `layering.ts` + `layering.test.ts` 是同一形制。
//
// 约定：
//   · 状态是一串 group id（数组而非 Set：顺序稳定、可序列化、逐字比对）；
//   · 默认只开前 DEFAULT_OPEN_LIMIT 组——全开就是修之前那个 1.9 万像素瀑布；
//   · 「打开」幂等（重复点同一组不会出现两份 id），「切换」可逆，允许一组都不开。

/** 默认展开前几组。改这个数＝改首屏高度，改完必须重量 docH。 */
export const DEFAULT_OPEN_LIMIT = 1;

/** 首屏默认展开的分组 id（取传入顺序的前 limit 个）。 */
export function initialOpenGroups(ids: readonly string[], limit: number = DEFAULT_OPEN_LIMIT): string[] {
  return ids.slice(0, Math.max(0, limit));
}

/** 打开一组（幂等）。 */
export function openGroup(open: readonly string[], id: string): string[] {
  return open.includes(id) ? [...open] : [...open, id];
}

/** 切换一组（在 → 去掉；不在 → 追加）。 */
export function toggleGroup(open: readonly string[], id: string): string[] {
  return open.includes(id) ? open.filter((item) => item !== id) : [...open, id];
}

/**
 * 过滤后重新对齐：搜索把某一组滤掉时，它的 id 不该继续占着「已展开」——
 * 否则清空搜索回来的那一组是开的，而用户从没点过它。
 * 交集为空时回落到新的第一组：页面上永远有一组展开，不会出现「17 行标题、0 个控件」的死页。
 */
export function reconcileOpenGroups(open: readonly string[], ids: readonly string[]): string[] {
  const kept = open.filter((id) => ids.includes(id));
  return kept.length > 0 ? kept : initialOpenGroups(ids);
}
