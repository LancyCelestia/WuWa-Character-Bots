// `/console/*` 真路径 → 路由路径（W12 UI3）。**纯函数，零 React 依赖**，`node --test` 可直接加载。
//
// 为什么住在这里：后端把 `/console` 与 `/console/<任意子路径>` 都回同一份 index.html
// （`control_plane/api/webui.py` 的 `/console/{sub_path:path}`），所以浏览器地址栏里的
// 真路径必须由前端**自己**读。UI2 时代靠 `createHashHistory()` + boot-hash 把真路径折成
// hash（`/console/calls` → `#/calls`），用户看到的就是 `/console/#/console` 这种叠叠乐。
// UI3 改 browser history 后不再折：路由表直接认 `/console/<页>`。
//
// 三条判据：
//   ① 只认 `/console` 前缀，`/consolex`、`/api/…` 一律不动（前缀碰撞不得误收）；
//   ② `/console` 与 `/console/` 都落到**总览**（dashboard，`/`）——用户裁定「默认打开总览」；
//   ③ 未入册子路径原样映射成 `/console/<它>`，由路由表的 notFound 出友好提示，不静默改成总览。

// 常量内联而不 import：本文件要能被 `node --test` 直接加载（同 labels.ts / console.ts 先例），
// 而 node 的 ESM 解析不认 `@/` 别名也不补 `.ts` 扩展名——跨文件 import 会让测试加载失败。
// 值仍与 `console.ts::CONSOLE_ROOT` 一致，判据在 `route-path.test.ts` 里对表。
const CONSOLE_ROOT = '/console';

/**
 * 路由路径 → 完整 href（含 `/console` 挂载前缀）。
 *
 * `base` 取 `import.meta.env.BASE_URL`（vite `base: '/console/'`），但行内 link 在测试
 * 与旧挂载面下要能用，所以允许调用方显式传入。空 base 时退化成裸路径。
 */
export function withBase(routePath: string, base: string): string {
  const trimmed = base.replace(/\/+$/, '');
  const path = routePath.startsWith('/') ? routePath : `/${routePath}`;
  // 总览路由在 base 根下：`/console/` 而不是 `/console//`
  return path === '/' ? `${trimmed}/` : `${trimmed}${path}`;
}

/** 地址栏路径 → 路由表认的路径。非 `/console` 族原样返回。 */
export function routePathFor(pathname: string): string {
  const raw = typeof pathname === 'string' ? pathname : '';
  // 去掉 base 前缀（BASE_URL 形如 `/console/`）后再判定，兼容 base='/' 的旧挂载。
  const bare = raw.length > 1 ? raw.replace(/\/+$/, '') : raw;
  // 前缀碰撞守卫：只认 `/console` 本身或 `/console/…`，`/consolex` 不是我们的子树。
  const inConsole = bare === CONSOLE_ROOT || bare.startsWith(`${CONSOLE_ROOT}/`);
  if (!inConsole) return bare || '/';

  // `/console` 与 `/console/` → 总览（不是总台；总台自己的路径是 `/console/console`）。
  if (bare === CONSOLE_ROOT) return '/';

  const rest = bare.slice(CONSOLE_ROOT.length + 1);
  if (!rest) return '/';

  // 总览的规范真路径 `/console/overview` 也回总览（旧映射表里的那一行仍然有效）。
  if (rest === 'overview') return '/';

  // 其余原样进路由表：已入册的页面正常命中，未入册的交给 notFound 组件。
  return `/${rest}`;
}

/** 路由路径 → 地址栏路径（导航 Link 用不到，深链与跨页跳转用得上）。 */
export function consolePathFor(routePath: string): string {
  const path = routePath.startsWith('/') ? routePath : `/${routePath}`;
  return path === '/' ? `${CONSOLE_ROOT}/` : `${CONSOLE_ROOT}${path}`;
}
