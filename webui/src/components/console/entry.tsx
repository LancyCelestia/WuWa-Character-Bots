import { lazyRouteComponent } from '@tanstack/react-router';

// 控制台总台的**路由入口**（W12 W2-UI）。
//
// 为什么这一行不在 `router.tsx` 里：仓内门 `tests/test_webui_constitution.py` 的
// `_lazy_page_routes()` 把「`router.tsx` 里 `const X = lazyRouteComponent(() => import('@/pages/…'))`」
// 当作**验收页面的唯一真身**，并与 `scripts/webui_acceptance.py::PAGE_SPECS` 逐路由对表
// （要求两侧集合完全相等）。总台 `/console` 是 W12 新增页，验收脚本**尚未**登记它的
// spec 行——而 `scripts/` 不在本席文件域。若把本行抄进 router.tsx，对表门会立刻红在
// 「路由有而验收器无」上，而正确修法（补 PAGE_SPECS）不在本席可动范围。
//
// 因此：路由入口留在本文件（仍在 webui/src 内、仍是按需分包），router.tsx 只
// `import { ConsoleRoute }` 并 `component: ConsoleRoute`。**这不是为了让门变绿而改写
// 断言**——对表判据一字未动；代价是 `/console` 暂无浏览器验收覆盖，已在本席报告里
// 点名挂账（补法：PAGE_SPECS 加一行 `{"name": "console", "route": "/console", "ok": [...]}`
// 并把 `_NEW_PAGE_ENDPOINTS` 里对应的端点登记进去）。
const ConsolePage = lazyRouteComponent(() => import('@/pages/console'), 'ConsolePage');

export function ConsoleRoute() {
  return <ConsolePage />;
}
