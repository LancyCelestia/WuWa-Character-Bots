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
import {
  asSearchInput,
  canonicalSearchStr,
  normalizeWith,
  searchSpecFor,
  validateSearchFor,
} from '@/lib/search-params';

// 路由骨架保留自 AxonHub（TanStack Router），改 code-based routeTree + hash history：
// 单文件构建 file:// 直开与静态挂载免 SPA fallback；不用上游 router-plugin（无代码生成、无分包）。

// ============================================================================
// 深链参数的单一口径**不住在这里**：纯类型 + 纯函数 + 参数表全部在 `@/lib/search-params`
// （零 React 依赖，才能被 node --test 直接加载并测到）。本文件只保留唯一执法点
// useCanonicalSearch——它必须握着 router 实例与 history，是纯函数之外唯一的 React 侧。
// 加参数：只往 SEARCH_SPECS 加一行，不要在这里再写第二份清洗。
// ============================================================================

/**
 * 地址栏可见改写（规则 ③ 的类型层唯一执法点）。
 * 只在「地址栏原文 ≠ 规范态」时动一次；改完两者相等 → 条件不再成立，天然收敛，无循环。
 * 注意：这条"天然收敛"成立的前提是 canonicalSearchStr 与 router 回填 searchStr 用**同一个
 * 序列化 primitive**（详见 search-params.ts 的函数注释）——编码器不同构时等式永不成立。
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
