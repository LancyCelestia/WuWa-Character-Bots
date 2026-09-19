import { useEffect } from 'react';
import { createHashHistory, createRootRoute, createRoute, createRouter, Outlet, useRouterState } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/app-shell';
import { RootErrorComponent, RouteErrorBoundary } from '@/components/layout/error-boundary';
import { DashboardPage } from '@/pages/dashboard';
import { CallsPage } from '@/pages/calls';
import { TokensPage } from '@/pages/tokens';
import { LatencyPage } from '@/pages/latency';
import { AffinityPage } from '@/pages/affinity';
import { LogsPage } from '@/pages/logs';
import { KnowledgePage } from '@/pages/knowledge';
import { PluginsPage } from '@/pages/plugins';
import { MemoryGraphPage } from '@/pages/memory-graph';

// 路由骨架保留自 AxonHub（TanStack Router），改 code-based routeTree + hash history：
// 单文件构建 file:// 直开与静态挂载免 SPA fallback；不用上游 router-plugin（无代码生成、无分包）。

// ============================================================================
// 深链参数单一口径（F12b；台账 docs/design/unify-audit-20260919/F12b-impl.md）
//
// 全站只有一条规则：**地址栏里看到的参数，就是页面真正在用的参数**。三条不变量：
//   ① 每条路由在 SEARCH_SPECS 里显式声明它消费的查询参数（键名与后端 REST query 同名）。
//      未声明的键（拼错的、过期深链里的、别人手敲的）不进规范态，页面永远读不到它们。
//   ② 非法值归一为「缺省」= 从地址栏省略；归一函数是纯函数、绝不抛错——参数再怎么离谱
//      也只能让页面回到缺省视图，不可能白屏（页面不消费地址栏原文，只消费规范态）。
//   ③ 归一之后地址栏**可见地**改写（以 replace 方式：不留后退足迹、不重置滚动位置），
//      改写点全站唯一（useCanonicalSearch）。任何席再加参数，只往表里加一行 spec，
//      不必也不该再写第二份清洗/回写逻辑。
//
// 与 F12-routing-ia.md §三 草案的差集（有意不做，避免「声明了却没人消费」的新谎言）：
// 枚举参数（window/bucket/order/types…）与 q/page 等只有在其消费页把 useState 换成
// useSearch 之后才进本表（F12-02 施工面，页面文件归他席）。在那之前这些路由的契约就是
// 「不消费任何查询参数」，于是地址栏里的 window=7d 会被洗掉——诚实：**页面确实没在用它**。
// ============================================================================

type SearchParamValue = string | undefined;
type SearchParamParser = (raw: unknown) => SearchParamValue;
/** 一条路由的参数表：键=URL 参数名，值=该参数的归一函数。 */
type SearchSpec = Record<string, SearchParamParser>;

/** 路由路径清单：与下方 createRoute 的 path 一一对应（九条，含 index）。 */
const ROUTE_PATHS = ['/', '/calls', '/tokens', '/latency', '/affinity', '/logs', '/knowledge', '/plugins', '/memory-graph'] as const;
type RoutePath = (typeof ROUTE_PATHS)[number];

/** 自由文本参数（集合 id / 过滤词一类）：非空字符串才成立，其余一律按缺省省略。 */
const freeText: SearchParamParser = (raw) => (typeof raw === 'string' && raw.trim() !== '' ? raw : undefined);

const SEARCH_SPECS: Record<RoutePath, SearchSpec> = {
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
function searchSpecFor(pathname: string): SearchSpec | undefined {
  return (ROUTE_PATHS as readonly string[]).includes(pathname) ? SEARCH_SPECS[pathname as RoutePath] : undefined;
}

function normalizeWith(spec: SearchSpec, search: Record<string, unknown>): Record<string, SearchParamValue> {
  const canonical: Record<string, SearchParamValue> = {};
  for (const [key, parse] of Object.entries(spec)) {
    const value = parse(search[key]);
    if (value !== undefined) canonical[key] = value;
  }
  return canonical;
}

/** 路由级 validateSearch 工厂：九条路由共用同一实现，只有参数表不同。 */
function validateSearchFor<T extends Record<string, SearchParamValue> = Record<string, SearchParamValue>>(pathname: RoutePath) {
  const spec = SEARCH_SPECS[pathname];
  return (search: Record<string, unknown>): T => normalizeWith(spec, search) as T;
}

/** 规范态 → 地址栏串：键序=参数表声明序（确定性输出，改写幂等，不会来回震荡）。 */
function canonicalSearchStr(search: Record<string, SearchParamValue>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === 'string' && value !== '') parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  }
  return parts.length > 0 ? `?${parts.join('&')}` : '';
}

/**
 * 地址栏可见改写（规则 ③ 的唯一执法点）。
 * 只在「地址栏原文 ≠ 规范态」时动一次；改完两者相等 → 条件不再成立，天然收敛，无循环。
 * 走 router.history.replace：与 router 内部 commitLocation 提交 replace 导航用的是同一个 primitive
 * （react-router 的 Transitioner 订阅 history 通知 → 照常 parseLocation/validateSearch/匹配路由），
 * 好处是不新增后退足迹、不重置滚动、也不碰 navigate 的 search 类型（无 to 时它退化成 never）。
 */
function useCanonicalSearch(): void {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const searchStr = useRouterState({ select: (state) => state.location.searchStr });
  useEffect(() => {
    const spec = searchSpecFor(pathname);
    if (!spec) return;
    const location = router.state.location;
    const canonical = normalizeWith(spec, asSearchInput(location.search));
    const canonicalStr = canonicalSearchStr(canonical);
    if (canonicalStr === (location.searchStr ?? '')) return;
    router.history.replace(`${location.pathname}${canonicalStr}${location.hash ? `#${location.hash}` : ''}`);
  }, [pathname, searchStr]);
}

/** location.search 的类型随路由而变（可能是空对象），统一按未知键读取。 */
function asSearchInput(search: object): Record<string, unknown> {
  return search as Record<string, unknown>;
}

function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  useCanonicalSearch();
  return (
    <AppShell>
      {/* key=pathname：换页重挂载即清错，避免一次抛错把后续所有页都锁在错误态。 */}
      <RouteErrorBoundary key={pathname}>
        <Outlet />
      </RouteErrorBoundary>
    </AppShell>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
  // 根级兜底只接「RouteErrorBoundary 之上」的抛错（布局壳自身、根路由框架）——
  // 页面内抛错先被边界拦下并保住侧栏。用 defaultErrorComponent 会被每个子路由继承，
  // 语义变成「替换子路由出口」，与边界的分工混淆，故不用。
  errorComponent: RootErrorComponent,
});

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: DashboardPage, validateSearch: validateSearchFor('/') });

const callsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/calls',
  component: CallsPage,
  validateSearch: validateSearchFor('/calls'),
});

const tokensRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tokens',
  component: TokensPage,
  validateSearch: validateSearchFor('/tokens'),
});

const latencyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/latency',
  component: LatencyPage,
  validateSearch: validateSearchFor('/latency'),
});

const affinityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/affinity',
  component: AffinityPage,
  validateSearch: validateSearchFor('/affinity'),
});

const logsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/logs',
  component: LogsPage,
  // 游标不进 URL 是设计裁定（sessionStorage per-tab，分享游标无意义）：
  // 因此 /logs 的参数表为空——日志页目前也不消费任何查询参数，地址栏里的 cursor 会被洗掉。
  validateSearch: validateSearchFor('/logs'),
});

const knowledgeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/knowledge',
  validateSearch: validateSearchFor<{ collection?: string }>('/knowledge'),
  component: KnowledgePage,
});

const pluginsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/plugins',
  component: PluginsPage,
  validateSearch: validateSearchFor('/plugins'),
});

const memoryGraphRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/memory-graph',
  component: MemoryGraphPage,
  validateSearch: validateSearchFor('/memory-graph'),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  callsRoute,
  tokensRoute,
  latencyRoute,
  affinityRoute,
  logsRoute,
  // PAGES2 三路由（spec §4：排在 /logs 之后，第 7/8/9 项）
  knowledgeRoute,
  pluginsRoute,
  memoryGraphRoute,
]);

export const router = createRouter({
  routeTree,
  history: createHashHistory(),
  defaultPreload: 'intent',
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
