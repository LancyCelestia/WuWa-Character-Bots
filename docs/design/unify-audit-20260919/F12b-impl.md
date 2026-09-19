# F12b 实施台账：移动导航抽屉 + 深链参数单一口径（2026-09-19）

> **快照口径**：本席实跑时点 **2026-09-19 19:35 (+08)**（`date` 实测）。树在被多席并发写，本文所有行号/计数为该时点实盘，引用前请重读最新态。
> **施工范围**：审计席 F12 的两条 P1（F12-01 手机无导航、F12-02 深链缺位中「参数处理口径统一」这一半）。
> **实际改动文件（2 件，均在授权写域内）**：
> - `webui/src/components/layout/app-shell.tsx`（移动导航抽屉 + 集合深链数据侧校正 + 「更多…」高亮收口）
> - `webui/src/router.tsx`（深链参数单一口径：声明表 / 生成式 validateSearch / 唯一地址栏改写点）
> `webui/src/components/layout/error-boundary.tsx` **本席未改**（见 §六.1 为何不需要）；locales、index.css、宪法门、package.json、任何 .py 全程未触。无 git 写操作、无 build、无 typecheck 脚本（未产生 `.tsbuildinfo`）、无起服务。

---

## 一、F12b-01｜P1｜窄视口无导航（原 F12-01 / 复验 P2-12）

**before**：侧栏整条只在 ≥768px 渲染，顶栏在窄视口只有「logo+标题 / 主题 / 设置」三枚——手机上**没有任何页面切换入口**，九页只能手敲 hash。

**after**（坐标=19:35 实盘）：
- `app-shell.tsx:181-192` 顶栏窄视口分支最前新增导航抽屉触发钮：图标随状态在「菜单/关闭」两枚 lucide 间切换，带 `aria-expanded={navOpen}`、`aria-controls={MOBILE_NAV_ID}`、`aria-label={navLabel}`，`ref` 用于 Escape 后交还焦点。
- `app-shell.tsx:207-215` 顶栏与内容区之间新增抽屉面板：`id={MOBILE_NAV_ID}` 常驻（收起时靠 display 类不可见亦不可达焦，`aria-controls` 永远指得到实体）、`<nav aria-label={navLabel}>`、**复用侧栏同一份 `nav` 数组与同一个 `NavItem`**——不新建第二套导航数据、不复制集合子分组（知识库页内本就有集合 chips 行，双入口会分叉）。
- `app-shell.tsx:106-121` 行为：换页即收（`pathname` 变化）；Escape 收起并把焦点交还触发钮。只做「关」，**不移焦点进面板、不接管 Tab、不做焦点陷阱、不做模态遮罩**（APG disclosure 的最小可实施子集）。
- `app-shell.tsx:158` 顺带把侧栏 `<nav>` 也补上同一个 `aria-label`（此前两处导航都无可辨识名称，读屏器只报「navigation」）。

**可达性属性清单（新增/依赖）**：
| 性质 | 状态 |
|---|---|
| 触发钮可聚焦、原生 `button` 键盘激活（Enter/Space） | ✅ 复用 `Button`（原生 button，未自造 role） |
| `aria-expanded` 双向随状态 | ✅ |
| `aria-controls` 指向常驻节点 | ✅（节点不随展开态增删） |
| 触发钮有非纹理可达名称（`aria-label`） | ✅ 内联双语兜底，见 §五 |
| 面板是 `<nav>` 且有可辨识名称 | ✅ 抽屉与侧栏同一 `navLabel` |
| 当前页高亮带 `aria-current='page'` | ✅ **库自带**：实装版 `@tanstack/react-router` 1.170.38 在 `react-router/dist/esm/link.js:219-222` 对 active 链接自动写 `aria-current='page'`（本席核实后**未**再手加，避免重复声明） |
| Escape 关闭 | ✅ 并交还焦点 |
| 收起内容不可达焦 | ✅ display 级隐藏（非 `visibility`/`opacity`） |
| 换页自动收起 | ✅ |
| 焦点顺序 / 触摸目标实测 | ❌ **无浏览器不可验**，见 §四 |

## 二、F12b-02｜P1｜深链参数处理单一口径（原 F12-02 的「口径」半 + F12-09 + F12-10）

**before**：全站只有 `/knowledge?collection=<id>` 进 URL，且**唯一**的校验写在页面里；非法 id 时页面静默改用默认集合而不回写地址栏（F12-09），侧栏「更多…」写 `search={}` 又因 search 子集匹配恒高亮（F12-10）。此外其余八条路由对 URL 参数**没有任何声明**，地址栏里的垃圾键无人认领也无人清洗。

**after**：一条规则、一张表、一个改写点。

1. **单一口径三条不变量**（`router.tsx:18-34` 注释即规范正文）：
   - ① 每条路由在 `SEARCH_SPECS`（`router.tsx:48-60`）显式声明它消费的查询参数；未声明的键不进规范态，页面永远读不到（这是 TanStack 给任何 `validateSearch` 的固有语义，本席把它收成一表而非散落九处）。
   - ② 非法值归一为「缺省」= 从地址栏省略；归一函数是纯函数、**绝不抛错** → 参数再怎么离谱也只能让页面回到缺省视图，**不可能因此白屏**。
   - ③ 归一之后地址栏**可见地**改写（replace 语义：不留后退足迹、不重置滚动）；改写点全站唯一 = `useCanonicalSearch`（`router.tsx:98-110`，挂在 `RootLayout`）。
2. **生成式校验**：`validateSearchFor(pathname)`（`router.tsx:77-80`）由同表产出九条路由的 `validateSearch`（`router.tsx:138-195`）；`/knowledge` 保留显式返回类型 `{ collection?: string }`，页面 `useSearch` 读感零变化。`ROUTE_PATHS`（`router.tsx:42`）是九条路径的穷举常量，`Record<RoutePath, SearchSpec>` 令编译期强制「每条路由都要表态」。
3. **数据侧校正**（类型层判不了的这一半）：`app-shell.tsx:123-140`。「id 是否存在且启用」只有取到集合目录才知道，故住在唯一同时握着目录与路由的本壳；非法（拼错/已停用/集合被关）→ 把参数从地址栏洗掉 = 回到「缺省=默认集合」规范形态，页面与地址栏**同一步收敛**；目录取到之前不动地址栏（不拿 loading 态猜服务端真相），取数失败也不动（不借口「未知」改用户的 URL）。
4. **F12-10 收口**：`NavSubItem` 加 `activeOptions={{ exact: true }}`（`app-shell.tsx:53`），关掉 search 子集匹配 → 「更多…」只在「地址栏确无集合参数」时高亮（它本就是「回默认集合」），不再与选中集合项双高亮；它仍是真链接（可中键开、可复制），没有退化成裸 button。
5. **收敛性**：改写后 `canonicalSearchStr === location.searchStr` 条件不再成立；序列化是自身不动点（键序=声明序，`encodeURIComponent` 稳定），无震荡、无循环。StrictMode 双跑效应同值幂等。

**行为矩阵（改前→改后，全 hash 路由）**：
| 地址栏 | 改前 | 改后 |
|---|---|---|
| `#/knowledge?collection=<合法>` | 页面选中该集合，URL 保持 | 不变（合法深链一律原样保留） |
| `#/knowledge?collection=<非法/已停用>` | 页面显示默认集合，**URL 仍写非法值** | 页面显示默认集合，URL 清洗为 `#/knowledge` |
| `#/knowledge?collection=`（空值） | 缺省 | 缺省（空值不成立，参数消失） |
| `#/calls?window=7d` 等未声明键 | 垃圾恒留在地址栏、无人认领 | 清洗掉（**诚实**：今日确无页面消费它），并在代码注释写明「页面搬进 URL 时才进表」 |
| 九页任意非法参数 | 视实现而定，可能静默 | 一律「回缺省 + 改写地址栏」，无白屏路径 |

## 三、复跑取证（三条命令；19:35 首跑与 19:38 收工复跑**同值**，下为收工实跑原样）

```
cd webui && npx tsc --noEmit -p tsconfig.app.json   → EXIT=0（零输出）
cd webui && npm run lint:layout                     → EXIT=0
  版式宪法机器门：全部通过（自测 58/58；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值方括号（盒子/环/色影，var+视口+规范环 3px 白名单）/ canvas 字体字面量；行级豁免 0/0 基线，棘轮只减不增；权重双写白名单 16 处存量在册；脱栅棘轮 1 处存量在册（只减不增））
cd webui && npm test                                → EXIT=0
  ℹ tests 29  ℹ pass 29  ℹ fail 0  ℹ cancelled 0  ℹ skipped 0
```

**基线归属（施工前 19:12 同三条实跑，防误记账）**：`tsc` 当时红 1 条在 `pages/dashboard.tsx`（TS6133 未读变量，他席在飞），`lint:layout` 当时红 1 条在 `components/graph/memory-canvas.tsx`（canvas 字体字面量，他席在飞），`npm test` 当时 14/0。两处在本席收工前已由他席自行转绿（19:35 与 19:38 两度三命令全 0），**本席未代修也未碰其文件**。测试数 14→29 为他席新增（含 `lib/labels.test.ts`、双语键集对账）。收工后 `git status` 复核：本席在 `webui/` 下零新增文件、零缓存产物（`npx tsc` 走 `--noEmit -p`，未用会往树里写 `.tsbuildinfo` 的 `typecheck` 脚本；全程未跑 `npm run build`、未起服务、无 git 写操作、未读 `.env`）。

## 四、三条命令看不见、且无浏览器本席不可验（不暗示已查）

`tsc` 只做类型、宪法门只扫类名写法、`node --test` 只跑零依赖纯函数——**以下全未验证**：
1. 真机窄视口（390/768px 断点）下抽屉是否真的可见、不溢出、不遮挡内容；顶栏加一枚按钮后 logo/标题是否被挤掉。
2. 键盘实际焦点顺序（触发钮 → 主题 → 设置 → 抽屉九链接 → 内容区，按文档序推算而非实测）与读屏器朗读文案。
3. 触摸目标尺寸：触发钮继承 `Button` 的 icon 档 36px；抽屉链接按 CSS 定义为 36px 高（正文档行高 20px + 上下内边距各 8px，`index.css` 值册静态推算，非实测）——据此满足 WCAG 2.2 AA 2.5.8（≥24px），**未达** 44px 的 AAA 指引。
4. 换页收起后的焦点落点：面板隐藏后焦点会退回 `body`（下一次 Tab 从文档开头重来）。要修需给内容区加可聚焦容器并在换页后聚焦——属浏览器才能验的行为，本席**有意不做**（见 §六.2）。
5. hash 路由下地址栏改写的肉眼效果（前进/后退是否仍回到用户真正去过的页、改写是否被浏览器地址栏实时刷新）。
6. 抽屉展开时窗口拉宽到桌面断点：按类名推断为「抽屉隐藏、侧栏接管」，未实测。
7. 展开后一次挂着九枚链接，与 `defaultPreload='intent'` 的交互（hover/focus/touchstart 才预取；收起态 display 级隐藏不会被 hover）实际网络行为未实测。

## 五、待主会话落键（本席无权改 locales）

只需一枚键，双语同批改两份（常驻门 `semantics.test.ts` 的「双语全键集对账」会拦单侧缺键）：

| 键 | zh-CN | en |
|---|---|---|
| `nav.menu` | 页面导航 | Pages |

消费点 3 处（抽屉触发钮 `aria-label`、抽屉 `<nav>` 名称、侧栏 `<nav>` 名称）。键未落地期间由 `useNavAccessLabel`（`app-shell.tsx:24-33`）的 `t(键, { defaultValue })` 按界面语言内联兜底，**不会**把裸键名甩给读屏器；落地后兜底自动让位，无需回改代码。先例=设置面板 SECWEB 的内联双语兜底。

## 六、交接与登记未修

1. **404（原 F12-03）本席未动**：未匹配 hash 仍渲染库内置裸英文行——那是**路径**面而非**参数**面，且落地需要新增 `state.notFound*` 文案键（locales 归他席）。`error-boundary.tsx` 在写域内但无需改的实证：本席的参数规则保证「参数非法不改渲染路径、不抛错」，壳层与页面抛错仍由既有边界与根兜底接住。修法稿已在 `F12-routing-ia.md` F12-03，只差文案键。
2. **换页后焦点管理**（§四.4）：留待有浏览器验证的席做，配 `tabIndex=-1` 的内容区容器即可，别在无验证下落码。
3. **F12-10 文案裁定留给本地化席**：「更多集合…」实际语义是「回到默认集合」（点它不会展开第 9+ 个集合，集合 chips 在页内）。高亮已修，名实仍需裁一次文案或改造成真的溢出展开。
4. **给 F12-02 后续施工席的硬提醒**：页面把 `useState` 搬进 URL 时，**必须往 `router.tsx` 的 `SEARCH_SPECS` 加一行**（本席文件），不要再手写第二份 `validateSearch`——否则未声明键会被本席的口径洗掉，深链发出去就蒸发。值域单一事实源他席已备好：`webui/src/lib/labels.ts`（`STATS_WINDOWS`/`GRAPH_WINDOWS`/`BUCKETS`/缺省窗）。样板（枚举参数一行，含非法值可见改写）：
   ```ts
   // router.tsx：import { BUCKETS, STATS_WINDOWS } from '@/lib/labels';
   const oneOf = (allowed: readonly string[]): SearchParamParser =>
     (raw) => (typeof raw === 'string' && allowed.includes(raw) ? raw : undefined);
   // '/calls': { window: oneOf(STATS_WINDOWS), bucket: oneOf(BUCKETS) },
   ```
   页面侧照 `/knowledge` 既有形状读 `useSearch` + 写 `navigate({ search })` 即可，清洗/改写/回退不用再写一遍。游标仍**明确不进 URL**（logs 的 per-tab sessionStorage 语义正确，注释已钉在 `router.tsx` 的 `/logs` 行上，防后人「顺手统一」）。
5. **IA 锁的可读性顺带变好**（原 F12-13）：路由清单现在有 `ROUTE_PATHS` 常量与 `SEARCH_SPECS` 表两处单一事实源，常驻锁脚本可直接正则提 `path: '...'` 与本表键集做恒等（本席不越权改 tests/）。
6. **严格清洗未知键的将来开关**：实装版 `createRouter` 提供 `search.strict`（默认 false）。本席不依赖它——因为任何 `validateSearch` 本就整体替换 search 对象；把它写在这儿只为防止后来席以为「改成 true 就能省掉 spec 表」。
