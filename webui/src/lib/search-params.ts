// ============================================================================
// 深链参数单一口径（F12b；台账 docs/design/unify-audit-20260919/F12b-impl.md）
//
// 全站只有一条规则：**地址栏里看到的参数，就是页面真正在用的参数**。三条不变量：
//   ① 每条路由在 SEARCH_SPECS 里显式声明它消费的查询参数（键名与后端 REST query 同名）。
//      未声明的键（拼错的、过期深链里的、别人手敲的）不进规范态，页面永远读不到它们。
//   ② 非法值归一为「缺省」= 从地址栏省略；归一函数是纯函数、绝不抛错——参数再怎么离谱
//      也只能让页面回到缺省视图，不可能白屏（页面不消费地址栏原文，只消费规范态）。
//   ③ 归一之后地址栏**可见地**改写（以 replace 方式：不留后退足迹、不重置滚动位置），
//      类型层的改写点唯一（router.tsx 的 useCanonicalSearch）。任何席再加参数，只往表里
//      加一行 spec，不必也不该再写第二份清洗/回写逻辑。
//
// 本文件刻意**零 React 依赖**（纯类型 + 纯函数），所以能被 node --test 直接加载：
// 判据住在 .tsx 里就等于没有判据（上一批 labels.test.ts 读后端 .py 也是同一类错）。
//
// 与 F12-routing-ia.md §三 草案的差集（有意不做，避免「声明了却没人消费」的新谎言）：
// 枚举参数（window/bucket/order/types…）与 q/page 等只有在其消费页把 useState 换成
// useSearch 之后才进本表（F12-02 施工面，页面文件归他席）。在那之前这些路由的契约就是
// 「不消费任何查询参数」，于是地址栏里的 window=7d 会被洗掉——诚实：**页面确实没在用它**。
// ============================================================================

export type SearchParamValue = string | undefined;
export type SearchParamParser = (raw: unknown) => SearchParamValue;
/** 一条路由的参数表：键=URL 参数名，值=该参数的归一函数。 */
export type SearchSpec = Record<string, SearchParamParser>;

/** 路由路径清单：与 router.tsx 里 createRoute 的 path 一一对应（九条，含 index）。 */
export const ROUTE_PATHS = ['/', '/calls', '/tokens', '/latency', '/affinity', '/logs', '/knowledge', '/plugins', '/memory-graph'] as const;
export type RoutePath = (typeof ROUTE_PATHS)[number];

/** 自由文本参数（集合 id / 过滤词一类）：非空字符串才成立，其余一律按缺省省略。 */
export const freeText: SearchParamParser = (raw) => (typeof raw === 'string' && raw.trim() !== '' ? raw : undefined);

export const SEARCH_SPECS: Record<RoutePath, SearchSpec> = {
  '/': {},
  '/calls': {},
  '/tokens': {},
  '/latency': {},
  '/affinity': {},
  '/logs': {},
  // 集合 id 走 search（侧栏子分组深链 /knowledge?collection=<id>）；
  // id 是否**存在且启用**只有取到集合目录才知道，那一步的可见校正在侧栏（app-shell.tsx）。
  '/knowledge': { collection: freeText },
  '/plugins': {},
  '/memory-graph': {},
};

/** 未知路径（未匹配路由=404 面）返回 undefined：本规则不接管，避免在壳层替 404 改写地址栏。 */
export function searchSpecFor(pathname: string): SearchSpec | undefined {
  return (ROUTE_PATHS as readonly string[]).includes(pathname) ? SEARCH_SPECS[pathname as RoutePath] : undefined;
}

export function normalizeWith(spec: SearchSpec, search: Record<string, unknown>): Record<string, SearchParamValue> {
  const canonical: Record<string, SearchParamValue> = {};
  for (const [key, parse] of Object.entries(spec)) {
    const value = parse(search[key]);
    if (value !== undefined) canonical[key] = value;
  }
  return canonical;
}

/** 路由级 validateSearch 工厂：九条路由共用同一实现，只有参数表不同。 */
export function validateSearchFor<T extends Record<string, SearchParamValue> = Record<string, SearchParamValue>>(pathname: RoutePath) {
  const spec = SEARCH_SPECS[pathname];
  return (search: Record<string, unknown>): T => normalizeWith(spec, search) as T;
}

/**
 * 规范态 → 地址栏串：键序=参数表声明序（确定性输出）。
 *
 * 序列化**必须**用 `URLSearchParams`，不能用 `encodeURIComponent`：router 自己回填
 * `location.searchStr` 走的是 @tanstack/router-core 的 qss `encode()`，其真身就是
 * `new URLSearchParams().toString()`（空格→`+`，`!'()~`→百分号转义）。而 `encodeURIComponent`
 * 把空格留成 `%20`、把 `!'()~*-._` 一律留成原文。上一版用后者拼串、却拿**字符串相等**当
 * "是否已规范"的幂等闸，于是含空格/`!`/`'`/`(`/`)`/`~`/`+` 的集合 id 两侧永不相等——
 * 改写条件恒成立。同一个 primitive 是这条闸唯一正确的判据来源，不是风格问题。
 */
export function canonicalSearchStr(search: Record<string, SearchParamValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === 'string' && value !== '') params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

/** location.search 的类型随路由而变（可能是空对象），统一按未知键读取。 */
export function asSearchInput(search: object): Record<string, unknown> {
  return search as Record<string, unknown>;
}
