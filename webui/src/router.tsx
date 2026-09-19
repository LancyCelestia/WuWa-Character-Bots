import { createHashHistory, createRootRoute, createRoute, createRouter, Outlet, useRouterState } from '@tanstack/react-router';
import { AppShell } from '@/components/layout/app-shell';
import { RouteErrorBoundary } from '@/components/layout/error-boundary';
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
function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return (
    <AppShell>
      {/* key=pathname：换页重挂载即清错，避免一次抛错把后续所有页都锁在错误态。 */}
      <RouteErrorBoundary key={pathname}>
        <Outlet />
      </RouteErrorBoundary>
    </AppShell>
  );
}

const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: '/', component: DashboardPage });

const callsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/calls',
  component: CallsPage,
});

const tokensRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tokens',
  component: TokensPage,
});

const latencyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/latency',
  component: LatencyPage,
});

const affinityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/affinity',
  component: AffinityPage,
});

const logsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/logs',
  component: LogsPage,
});

const knowledgeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/knowledge',
  // 集合 id 走 search（侧栏子分组深链 /knowledge?collection=<id>）；非法值由页面按可用列表校正。
  validateSearch: (search: Record<string, unknown>): { collection?: string } => ({
    collection: typeof search.collection === 'string' && search.collection ? search.collection : undefined,
  }),
  component: KnowledgePage,
});

const pluginsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/plugins',
  component: PluginsPage,
});

const memoryGraphRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/memory-graph',
  component: MemoryGraphPage,
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
