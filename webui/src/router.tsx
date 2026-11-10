import { useEffect } from 'react';
import {
  createBrowserHistory,
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Link,
  Outlet,
  useRouterState,
} from '@tanstack/react-router';
import { parseHref } from '@tanstack/history';
import { AppShell } from '@/components/layout/app-shell';
import { RootErrorComponent, RouteErrorBoundary } from '@/components/layout/error-boundary';
import { routePathFor, withBase } from '@/lib/route-path';
import { legacyHashPath } from '@/lib/console';
const DashboardPage = lazyRouteComponent(() => import('@/pages/dashboard'), 'DashboardPage');
const CallsPage = lazyRouteComponent(() => import('@/pages/calls'), 'CallsPage');
const TokensPage = lazyRouteComponent(() => import('@/pages/tokens'), 'TokensPage');
const LatencyPage = lazyRouteComponent(() => import('@/pages/latency'), 'LatencyPage');
const AffinityPage = lazyRouteComponent(() => import('@/pages/affinity'), 'AffinityPage');
// 会话身份（D1–D4）：平台 / 群或频道 / 用户ID / 昵称。只读消费 /stats/calls 的 identity 块。
const SessionsPage = lazyRouteComponent(() => import('@/pages/sessions'), 'SessionsPage');
const LogsPage = lazyRouteComponent(() => import('@/pages/logs'), 'LogsPage');
const KnowledgePage = lazyRouteComponent(() => import('@/pages/knowledge'), 'KnowledgePage');
const PluginsPage = lazyRouteComponent(() => import('@/pages/plugins'), 'PluginsPage');
const MemoryGraphPage = lazyRouteComponent(() => import('@/pages/memory-graph'), 'MemoryGraphPage');
// 参数页（合并席）：`/config` 指向新的全量参数页（807 键 + 三拍写入），
// 旧的控制台内嵌版仍留在 `pages/control-center`，但不再占这条路由。
const ConfigPage = lazyRouteComponent(() => import('@/pages/config'), 'ConfigPage');
// 人格页：runtime persona_override 的读写面（不是配置键；下一轮生效，不重启）。
const PersonaPage = lazyRouteComponent(() => import('@/pages/persona'), 'PersonaPage');
const ResourcesPage = lazyRouteComponent(() => import('@/pages/control-center'), 'ResourcesPage');
const ModelsPage = lazyRouteComponent(() => import('@/pages/control-center'), 'ModelsPage');
const VisualEditorPage = lazyRouteComponent(() => import('@/pages/visual-editor'), 'VisualEditorPage');
// 外观工作室（合并席）：视觉层全部可调参数，改完即时生效、落 IndexedDB。
const AppearancePage = lazyRouteComponent(() => import('@/pages/appearance'), 'AppearancePage');
const CredentialsPage = lazyRouteComponent(() => import('@/pages/credentials'), 'CredentialsPage');
const OperationsPage = lazyRouteComponent(() => import('@/pages/operations'), 'OperationsPage');
// 控制台总台（W12 W2-UI）。入口住在 `components/console/entry.tsx`，那里解释了
// 为什么它不走本文件的 `lazyRouteComponent` 直写形态（与 `scripts/webui_acceptance.py`
// 的 PAGE_SPECS 对表有关，而 scripts/ 不在本席文件域）——判据本身一字未改。
import { ConsoleRoute } from '@/components/console/entry';
import {
  asSearchInput,
  canonicalSearchStr,
  normalizeWith,
  searchSpecFor,
  validateSearchFor,
} from '@/lib/search-params';

// 路由骨架保留自 AxonHub（TanStack Router），改 code-based routeTree + hash history：
// /ui/ 静态挂载配 hash 路由免 SPA fallback；页面用原生动态 import 分包，不引入代码生成。

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

// ── 未命中（UI3）：`/console/<不认识的东西>` 出**友好提示**，不是白屏也不是静默改总览。
// 旧 hash 路由时代，未入册路径由 hash 路由自己 404；browser history 下 `routePathFor()`
// 把它原样送进来，必须有人接住。文案走中文（用户界面语言），不用 i18n 键：这一页只出现
// 在打错地址时，多一份词条反而多一处要维护的真相。
function NotFoundPage() {
  const { location } = useRouterState();
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <span aria-hidden className='h-5 w-1 shrink-0 rounded-full bg-primary' />
        <h1 className='fs-page'>页面不存在</h1>
      </div>
      <div className='surface flex flex-col gap-3 rounded-lg p-6'>
        <p className='fs-body'>
          地址 <span className='font-mono text-primary'>{location.pathname}</span> 没有对应的页面。
        </p>
        <p className='fs-caption text-muted-foreground'>
          可能是链接写错了，或这一页还没有上线。控制台的所有页面都挂在 <span className='font-mono'>/console/</span> 下。
        </p>
        <div className='flex flex-wrap gap-2'>
          <Link
            to='/'
            className='inline-flex min-h-11 items-center rounded-md bg-primary px-4 fs-body text-primary-foreground transition-opacity hover:opacity-90'
          >
            回到总览
          </Link>
        </div>
      </div>
    </div>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
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

const sessionsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/sessions', component: SessionsPage });

const configRoute = createRoute({ getParentRoute: () => rootRoute, path: '/config', component: ConfigPage });
const personaRoute = createRoute({ getParentRoute: () => rootRoute, path: '/persona', component: PersonaPage });
const resourcesRoute = createRoute({ getParentRoute: () => rootRoute, path: '/resources', component: ResourcesPage });
const modelsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/models', component: ModelsPage });

const visualRoute = createRoute({ getParentRoute: () => rootRoute, path: '/visual-editor', component: VisualEditorPage });

const appearanceRoute = createRoute({ getParentRoute: () => rootRoute, path: '/appearance', component: AppearancePage });

const credentialsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/credentials', component: CredentialsPage });

const operationsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/operations', component: OperationsPage });

// 总台入口（W12 W2-UI）。`/console/console`（真路径派生）落到总台页；
// `/console` 与 `/console/` 本身落到**总览**（用户裁定「默认打开总览」），由 history 层
// 的 `routePathFor()` 完成映射——见本文件末尾 createBrowserHistory 一段。
const consoleRoute = createRoute({ getParentRoute: () => rootRoute, path: '/console', component: ConsoleRoute });

const routeTree = rootRoute.addChildren([
  indexRoute,
  callsRoute,
  tokensRoute,
  latencyRoute,
  affinityRoute,
  sessionsRoute,
  logsRoute,
  // PAGES2 三路由（spec §4：排在 /logs 之后，第 7/8/9 项）
  knowledgeRoute,
  pluginsRoute,
  memoryGraphRoute,
  configRoute,
  personaRoute,
  resourcesRoute,
  modelsRoute,
  visualRoute,
  appearanceRoute,
  credentialsRoute,
  operationsRoute,
  consoleRoute,
]);

// ============================================================================
// history（W12 UI3）：browser history，不再折 hash
// ============================================================================
//
// 🔴 这是「叠叠乐 URL」的根因所在。UI2 用 `createHashHistory()`，于是真路径
//    `/console/calls` 被 boot-hash 折成 `/console/#/calls`，用户看到 `/console/#/console`。
//    UI3 换成 browser history：地址栏永远是**真路径**，路由直接认 `/console/<页>`。
//
// 前置条件（已核实，后端不在本席可动范围）：`api/webui.py` 的 `/console/{sub_path:path}`
// 对**任意**子路径都回同一份 index.html，所以直接打开 `/console/calls` 也是 200。
//
// 两件事必须在 history 层做，而不是散到各页：
//   ① **剥 base**：vite `base: '/console/'`，地址栏是 `/console/calls`，而路由表里的路径
//      是 `/calls`。`parseLocation` 把 href 交给 `routePathFor()` 换成路由路径。
//   ② **拼 base**：`createHref` 反着来，`Link`/`navigate` 产出的 href 带 `/console` 前缀。
//      不做这一步，点导航会跳到站根 `/calls`（后端那里没有页面，404）。
//
// ⚠️ `scripts/webui_acceptance.py` 仍是按 `#{route}` 驱动的旧契约——改 browser history 后
//    它会红，需要把驱动改成真路径。该脚本不在本席文件域，已在本席报告里点名。

type BrowserHistory = ReturnType<typeof createBrowserHistory>;

/**
 * 旧 hash 深链迁移（用户截图：地址栏 `#/plugins`、侧栏高亮「插件」、正文却是「总览」）。
 *
 * 旧书签/缓存里带着 `#/plugins`，而 browser history 只读 pathname——两条信息源各说各话。
 * 这里在**路由实例建立之前**把 `#` 认领成真路径并用 `replaceState` 写回地址栏：
 *   - `replace` 而非 `push`：不新增后退足迹，用户按一次后退就回到来处；
 *   - 认得出的旧路由 → 对应的 `/console/<页>`；认不出的 → 清掉 `#`，落到当前真路径
 *     （`/console` 自己会成总览）。两条都必须让地址栏**没有 `#`**；
 *   - 不是旧式 `#/…` 的 hash（现代页面的锚点）一律不碰。
 *
 * 值域判据在 `lib/console.ts::legacyHashPath`（纯函数、有测试），这里只做 DOM 侧一次改写。
 */
function migrateLegacyHash(): void {
  const current = window.location.hash;
  if (!current) return;
  const target = legacyHashPath(current);
  if (!target && !current.startsWith('#/')) return; // `#section` 之类：页面锚点，不是旧路由
  const next = target
    ? withBase(routePathFor(target), import.meta.env.BASE_URL || '/console/')
    : `${window.location.pathname}${window.location.search}`;
  // 恒能生效：当前 URL 带非空 hash，而 `next` 一定不带——两者不可能相等，
  // 所以不会落进「replaceState 到同一 URL 静默 no-op」那个坑。
  window.history.replaceState(window.history.state, '', next);
}

function consoleHistory(base: string): BrowserHistory {
  return createBrowserHistory({
    // 地址栏真路径 → 路由路径（剥 `/console` base，`/console/calls` → `/calls`）。
    // TanStack 的 push/replace 也走同一个 parseHref，所以导航后 router 读到的仍是路由路径。
    parseLocation: () =>
      parseHref(
        `${routePathFor(window.location.pathname)}${window.location.search}${window.location.hash}`,
        window.history.state
      ),
    // 路由路径 → href（拼回 `/console` base）。`<Link href>` 与 navigate 都经这里，
    // 不拼就会出现「点导航跳到站根 /calls」= 后端 404。
    createHref: (path) => withBase(path || '/', base),
  });
}

// 迁移必须在 createRouter 之前跑：router 建立时就按 `parseLocation` 读了一次地址栏，
// 先改地址栏再建实例，首帧渲染的正文与地址栏才是同一页（否则会先画总览再跳）。
migrateLegacyHash();

export const router = createRouter({
  routeTree,
  history: consoleHistory(import.meta.env.BASE_URL || '/console/'),
  defaultPreload: 'intent',
  // 未命中不是异常：`/console/随便什么` 应当出 NotFoundPage，而不是被错误边界吞成报错卡。
  defaultNotFoundComponent: NotFoundPage,
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
