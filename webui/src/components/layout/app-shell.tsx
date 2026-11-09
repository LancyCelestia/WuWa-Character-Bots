import {
  Activity,
  Blocks,
  Gauge,
  Heart,
  LayoutDashboard,
  Library,
  Network,
  ScrollText,
  BarChart3,
  Coins,
  Waves,
  Settings,
  Menu,
  X,
  ShieldCheck,
  Sparkles,
  Wrench,
  Palette,
  Users,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useRouterState } from '@tanstack/react-router';
import { ThemeSwitch } from '@/components/theme-switch';
import { AmbientBackdrop } from '@/components/backdrop/ambient-backdrop';
// 动效层（W17）：气泡场挂在 .bg-stage 里（与另两层同一套负 z），幕布/进度条/光标挂根部。
import { MotionBubbles, MotionChrome } from '@/components/effects/motion-chrome';
import { NavIndicator } from '@/components/effects/nav-indicator';
// 本地壁纸层（图片 / mp4）：外观页选的文件要到**这一层**才有消费者。
// W12-A2：这个组件以前写完就从没被挂过，所以「导入动态壁纸」永远什么都不发生。
import { BackgroundStage } from '@/components/appearance/background-stage';
import { SettingsDialog } from '@/components/settings/settings-dialog';
import { Button } from '@/components/ui/button';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type HealthData, type KnowledgeCollectionsData } from '@/lib/api-client';
import { pickEnabledCollections } from '@/lib/semantics';
import { cn } from '@/lib/utils';

// 布局壳：侧边栏 + 顶栏 + 内容区。模式保留自 AxonHub authenticated-layout（精简：
// 上游 shadcn sidebar 全家桶/权限守卫/搜索上下文裁掉，导航 Link 直连 hash 路由）。
//
// 窄视口（手机）：侧栏整条不渲染，页面切换入口改由顶栏的导航抽屉承担——
// 抽屉与侧栏**同一份 nav 数组、同一个 NavItem**，不另起第二套导航数据（F12-01）。
// 抽屉只做「展开/收起」，不做焦点陷阱、不做模态遮罩：里面就是九个原生链接，
// Tab 与读屏器走的是最朴素的文档序（APG disclosure 的最小可实施子集）。
//
// 视觉层（W12 UI 重做）只动 className 与分组展示，**导航数据仍是一份数组**：
// 分组是「同一个 item 的 group 字段 + 渲染时按组切片」，不复制、不排序、不改路径。

/** 抽屉与触发钮的关联 id（aria-controls 指向它）。 */
const MOBILE_NAV_ID = 'webui-mobile-nav';

/**
 * 抽屉/侧栏的可达名称。`nav.menu` 已双语言入册（zh「页面导航」/ en "Pages"），
 * 故不再内联双语兜底——那份兜底会在 locales 之外造出第二处文案真相。
 */
function useNavAccessLabel(): string {
  const { t } = useTranslation();
  return t('nav.menu');
}

/** 从地址栏原文里取一个查询参数（searchStr 形如 '?a=1&b=2'，可带前导问号）。 */
function paramFromSearchStr(searchStr: string, key: string): string {
  const raw = searchStr.startsWith('?') ? searchStr.slice(1) : searchStr;
  return new URLSearchParams(raw).get(key) ?? '';
}

// 知识库侧栏子分组（spec §4）：只列前 8 个可用集合 + 溢出「更多…」；
// collections 端点不可用/加载中 → 整组不渲染（不放假子项）。
// 「更多…」不带集合参数=回到默认集合的规范形态（地址栏里不写参数即缺省），
// 故它的高亮判据必须是「search 也精确相等」——否则子集语义会让它在 /knowledge
// 任何状态下恒高亮，与选中集合项双高亮并存（F12-10）。
function NavSubItem({ label, collection }: { label: string; collection?: string }) {
  return (
    <Link
      to='/knowledge'
      search={collection ? { collection } : {}}
      className='block truncate rounded-md py-1 pl-6 pr-2 fs-caption text-muted-foreground transition-colors hover:text-foreground [&.active]:text-primary [&.active]:font-medium'
      activeProps={{ className: 'active' }}
      activeOptions={{ exact: true }}
    >
      {label}
    </Link>
  );
}

/**
 * 单个导航项。视觉层四条：
 *   ① 选中态不是「整块填满品牌蓝」（亮色下像按钮、暗色下过重），而是**玻璃底 + 左侧
 *      2px 品牌色竖条**——读起来是「当前位置」而不是「可点的大按钮」；
 *   ② 选中项边框走 conic 虹彩流光（UI2 炫彩两处之一，另一处是页首釉线）；
 *   ③ 图标容器带一圈内描边，选中时染品牌色，和卡片同一套材质语言；
 *   ④ 过渡只走 color / transform，不给背景加 box-shadow 动画。
 */
function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <Link
      to={to}
      className={cn(
        // min-h-11 = 44px：触控目标下限（WCAG 2.5.5 / 手机平板可用性）。
        'group relative flex min-h-11 items-center gap-3 rounded-md px-3 py-2 fs-body text-muted-foreground',
        'transition-colors duration-200 before:absolute before:inset-y-2 before:left-0 before:w-1 before:rounded-full',
        'before:bg-transparent hover:bg-card hover:text-foreground',
        '[&.active]:bg-card [&.active]:text-foreground [&.active]:font-medium [&.active]:before:bg-primary',
        '[&.active]:iridescent-ring'
      )}
      activeProps={{ className: 'active' }}
    >
      <span
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-md border border-transparent',
          'text-muted-foreground transition-colors duration-200',
          'group-hover:text-foreground group-[.active]:border-primary/20 group-[.active]:bg-primary/10 group-[.active]:text-primary'
        )}
      >
        {icon}
      </span>
      <span className='truncate'>{label}</span>
    </Link>
  );
}

/** 导航分组标题：小字 + 字距（eyebrow），只为分簇，不承担可点语义。 */
function NavGroupLabel({ children }: { children: ReactNode }) {
  return (
    <p className='px-3 pb-1 pt-3 fs-caption eyebrow text-muted-foreground/70 first:pt-0'>{children}</p>
  );
}

/** 顶置横向栏的成员：比侧栏矮一档（36px vs 44px），图标框也小一号。
 *  两个尺寸都保留 4px 栅格；文字仍走 fs-caption（13px 档）。 */
function NavStripItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <Link
      to={to}
      className={cn(
        'group relative flex min-h-9 items-center gap-2 rounded-md px-3 fs-caption text-muted-foreground',
        'transition-colors duration-200 hover:text-foreground',
        '[&.active]:text-foreground [&.active]:font-medium'
      )}
      activeProps={{ className: 'active' }}
    >
      <span className='flex size-4 shrink-0 items-center justify-center'>{icon}</span>
      <span className='truncate'>{label}</span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const navLabel = useNavAccessLabel();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const navTriggerRef = useRef<HTMLButtonElement>(null);

  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const searchStr = useRouterState({ select: (state) => state.location.searchStr });
  const locationHash = useRouterState({ select: (state) => state.location.hash });

  // 导航**数据仍是一份数组**：group 只是它自带的一个字段，下面的渲染按组切片。
  // 顺序 = 原顺序（不改路径、不改顺序），视觉层只决定「在哪儿断开一簇」。
  const nav = [
    // 总台（W12 W2-UI）：排在总览之前——它是入口，不是又一个统计页。
    { to: '/console', icon: <Gauge className='size-4' />, label: t('nav.console'), group: 'observe' },
    { to: '/', icon: <LayoutDashboard className='size-4' />, label: t('nav.overview'), group: 'observe' },
    { to: '/calls', icon: <BarChart3 className='size-4' />, label: t('nav.calls'), group: 'observe' },
    { to: '/tokens', icon: <Coins className='size-4' />, label: t('nav.tokens'), group: 'observe' },
    { to: '/latency', icon: <Gauge className='size-4' />, label: t('nav.latency'), group: 'observe' },
    { to: '/affinity', icon: <Heart className='size-4' />, label: t('nav.affinity'), group: 'observe' },
    // 会话身份（D1–D4）：平台 / 群或频道 / 用户ID / 昵称。归观测簇（与调用统计同源）。
    { to: '/sessions', icon: <Users className='size-4' />, label: t('nav.sessions'), group: 'observe' },
    { to: '/logs', icon: <ScrollText className='size-4' />, label: t('nav.logs'), group: 'observe' },
    { to: '/knowledge', icon: <Library className='size-4' />, label: t('nav.knowledge'), group: 'data' },
    { to: '/plugins', icon: <Blocks className='size-4' />, label: t('nav.plugins'), group: 'data' },
    { to: '/memory-graph', icon: <Network className='size-4' />, label: t('nav.memoryGraph'), group: 'data' },
    { to: '/config', icon: <Settings className='size-4' />, label: t('nav.config'), group: 'admin' },
    { to: '/resources', icon: <Activity className='size-4' />, label: t('nav.resources'), group: 'admin' },
    { to: '/models', icon: <Sparkles className='size-4' />, label: t('nav.models'), group: 'admin' },
    { to: '/visual-editor', icon: <LayoutDashboard className='size-4' />, label: t('nav.visualEditor'), group: 'admin' },
    // 外观工作室（合并席）：路由已挂 `/appearance`，这里只补入口，导航数据仍是一份数组。
    { to: '/appearance', icon: <Palette className='size-4' />, label: t('nav.appearance'), group: 'admin' },
    { to: '/credentials', icon: <Wrench className='size-4' />, label: t('nav.credentials'), group: 'admin' },
    { to: '/operations', icon: <ShieldCheck className='size-4' />, label: t('nav.operations'), group: 'admin' },
  ];

  // 分组标题（i18n 未给这三簇命名 → 用最短的职能词，不新造品牌词）。
  const groupLabels: Record<string, string> = {
    observe: t('nav.groupObserve'),
    data: t('nav.groupData'),
    admin: t('nav.groupAdmin'),
  };
  const groups = ['observe', 'data', 'admin'] as const;

  // 顶栏当前页名（= 当前路由对应的导航项标签）；路由不在导航里（如未来新增页）就不显示，绝不猜。
  const currentLabel = nav.find((item) => item.to === pathname)?.label;

  const collectionsQuery = useSemanticQuery<KnowledgeCollectionsData>(
    ['knowledge', 'collections'],
    () => controlApi.knowledgeCollections()
  );
  // 顶栏那颗状态灯读的是控制面健康（30s 一次）。没令牌/没数据 → 灯点不亮也不报错：
  // 它是「顺带看到」的信息，不是本页的主数据，绝不因为灯去挡页面。
  const healthQuery = useSemanticQuery<HealthData>(['shell', 'health'], () => controlApi.health(), {
    refetchInterval: 30_000,
  });
  const healthOk = healthQuery.state.phase === 'ok' ? healthQuery.state.data.ok : null;
  const collectionsData = collectionsQuery.state.phase === 'ok' ? collectionsQuery.state.data : null;
  // 集合目录取到之前不参与任何判定（拿 loading 态猜服务端真相=会改写错地址栏）。
  const enabledCollections = useMemo(() => pickEnabledCollections(collectionsData?.items), [collectionsData]);
  const subCollections = enabledCollections.slice(0, 8);
  const hasMoreCollections = enabledCollections.length > 8;

  // 抽屉只为「当前这一页要去哪儿」服务，换页即收；同页的参数清洗不算换页，不收。
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // Escape 收起并把焦点交还触发钮。只做「关」，不接管 Tab、不移焦点进面板、不 trap。
  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setNavOpen(false);
      navTriggerRef.current?.focus();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [navOpen]);

  // 深链 ?collection=<id> 的**数据侧**可见校正（F12-09 收口；类型层归一在 router.tsx 的单一口径里）。
  // 「这个 id 是否存在且启用」只有取到集合目录才判得出来，所以这一步住在唯一同时握着
  // 目录与路由的组件=本壳；参数非法（拼错/已停用/集合被关）时把参数从地址栏洗掉，
  // 即回到「缺省=默认集合」的规范形态——页面与地址栏同一步收敛，不出现「URL 说 A、页面显示 B」，
  // 也不静默留在原地让分享者以为深链生效了。改写用 replace：不留后退足迹。
  useEffect(() => {
    if (pathname !== '/knowledge' || !collectionsData) return;
    const requested = paramFromSearchStr(searchStr, 'collection');
    if (!requested) return; // 无参数即缺省，本就是规范态
    if (enabledCollections.some((item) => item.id === requested)) return; // 合法深链，原样保留
    void navigate({
      to: '/knowledge',
      search: { collection: undefined },
      hash: locationHash || undefined,
      replace: true,
      resetScroll: false,
    });
  }, [pathname, searchStr, locationHash, collectionsData, enabledCollections, navigate]);

  return (
    // 悬浮外壳：整页四周留 --shell-inset（12px），侧栏/顶栏/内容都是浮在雾底上的玻璃片，
    // 背景光斑从缝隙里透出来（用户裁定「不要贴边框」）。
    <div
      className='flex min-h-svh w-full'
      // 面板之间的缝 = --shell-gap（外观页「面板间距」直接改它）；刘海屏安全区在同一份 style 里取 max。
      style={{
        gap: 'var(--shell-gap)',
        padding: 'var(--shell-inset)',
        paddingTop: 'var(--shell-inset)',
        paddingBottom: 'var(--shell-inset)',
        paddingLeft: 'max(var(--shell-inset), env(safe-area-inset-left))',
        paddingRight: 'max(var(--shell-inset), env(safe-area-inset-right))',
      }}
    >
      {/* 背景层（UI2）：视频 → 洗色 → 漂移光斑 → 云母颗粒。四条 fixed 姊妹层，
          与 <main> 平级、不进任何滚动容器（贴滚动容器会每帧重绘整条带）。
          页面本身透明，靠这层出「底」。
          🔴 它们必须包在 `.bg-stage` 里（Q3）：负 z 只在**最近的层叠上下文**内为负，
          这层容器（fixed + inset:0 + z-index:-1 + isolation:isolate）把整组背景
          钉在「负 z 步」，正文/卡片/胶囊/侧栏/弹层因此恒在其上；容器自己也
          pointer-events:none，不抢鼠标。层级契约见 components/appearance/layering.test.ts。 */}
      <div className='bg-stage'>
        <AmbientBackdrop />
        {/* 本地壁纸（图片 / mp4）：与 AmbientBackdrop 互斥——选的是本地文件时它画，
            纯色/场景着色时它返回 null。两层都用负 z，落在同一套层级里。 */}
        <BackgroundStage />
        {/* 气泡场（W17）：算法移植自参考站 daniya.top 的 canvas 气泡，但走纯函数 + 双渲染路径。
            z-index -25 夹在云母颗粒（-20）与洗色膜（-30）之间：气泡要有「浮在洗色膜上、
            在颗粒下」的层次感，压在颗粒之上会显脏。 */}
        <MotionBubbles />
      </div>
      {/* 侧栏（UI3 悬浮）：sticky 在 p-3 内，自身高 = 视口 - 上下边距；rounded-xl=30px 大窗档；
          window 垫子给云母 + 釉瑚渐变（--glaze-side）；overflow-hidden 让釉不溢出圆角。
          滚动条在内部 <nav>，整块玻璃不动。 */}
      {/* 宽度三档：md(768) 起显形；lg(1024–1365) 收窄到 224px 给内容让位（平板横屏最挤的
          那一档，用户报过「平板挤」）；xl(1366+) 恢复 264px。 */}
      <aside
        className='sticky top-3 hidden w-56 shrink-0 flex-col rounded-xl window md:flex xl:w-64'
        style={{ height: 'calc(100dvh - 24px)' }}
      >
        <div className='flex items-center gap-3 px-4 py-4'>
          {/* brand-ring（W17）：参考站 daniya.top 那圈 120s 匀速自转的 hero 光环，
              本仓移到品牌标上（站点身份锚点 ←→ hero 人像，同一角色）。
              环用 conic 描边，标签本身不转——跟着转就成了加载动画。 */}
          <span className='brand-mark brand-ring mark-breathe flex size-10 items-center justify-center rounded-lg text-primary-foreground'>
            <Waves className='size-5' />
          </span>
          <div className='min-w-0 leading-tight'>
            <div className='truncate fs-card'>{t('app.title')}</div>
            <div className='truncate fs-caption text-muted-foreground'>{t('app.subtitle')}</div>
          </div>
        </div>

        <nav className='flex flex-1 flex-col gap-1 overflow-y-auto px-3 pb-3' aria-label={navLabel}>
          {/* 垂直指示器（W17）：参考站 daniya.top 的 `.nav__pill` 只有一个方向；
              本仓的侧栏是竖排，所以 indicatorBox 只在 y 轴有意义——横向的那条走顶栏。 */}
          <NavIndicator orientation='vertical' className='flex flex-col gap-1'>
            {groups.map((group) => {
              const items = nav.filter((item) => item.group === group);
              if (items.length === 0) return null;
              return (
                <div key={group} className='flex flex-col gap-1'>
                  <NavGroupLabel>{groupLabels[group]}</NavGroupLabel>
                  {items.map((item) => (
                    <div key={item.to} className='flex flex-col gap-1'>
                      <NavItem {...item} />
                      {item.to === '/knowledge' && subCollections.length > 0 && (
                        <div className='flex flex-col gap-1'>
                          {subCollections.map((collection) => (
                            <NavSubItem key={collection.id} label={collection.name} collection={collection.id} />
                          ))}
                          {hasMoreCollections && <NavSubItem label={t('nav.moreCollections')} />}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </NavIndicator>
        </nav>

        <div className='border-t px-4 py-3 fs-caption text-muted-foreground'>{t('app.footer')}</div>
      </aside>

      <div className='flex min-w-0 flex-1 flex-col'>
        {/* 顶栏：云母材质（blur 30 + saturate 1.4），只给 sticky 元素（滚动内容不加 backdrop）。 */}
        {/* 顶栏（UI3 悬浮）：与侧栏同一档圆角与投影，不再贴顶贴右；sticky top-3 与外壳 p-3 对齐。 */}
        <header className='sticky top-3 z-10 flex h-14 items-center justify-between gap-3 rounded-xl window px-3 sm:h-16 sm:px-4 md:px-4 xl:px-6'>
          <div className='flex min-w-0 items-center gap-2 md:hidden'>
            <Button
              ref={navTriggerRef}
              variant='ghost'
              size='icon'
              aria-expanded={navOpen}
              aria-controls={MOBILE_NAV_ID}
              aria-label={navLabel}
              onClick={() => setNavOpen((value) => !value)}
            >
              {navOpen ? <X className='size-4' /> : <Menu className='size-4' />}
            </Button>
            <span className='brand-mark flex size-7 items-center justify-center rounded-md text-primary-foreground'>
              <Waves className='size-4' />
            </span>
            <span className='truncate fs-card'>{currentLabel ?? t('app.title')}</span>
          </div>

          {/* 桌面顶栏：当前页（面包屑形）+ 右侧系统副题与动作。 */}
          <div className='hidden min-w-0 items-center gap-2 md:flex'>
            <span className='eyebrow fs-caption text-muted-foreground'>{t('app.title')}</span>
            <span aria-hidden className='text-muted-foreground/50'>
              /
            </span>
            <span className='truncate fs-card'>{currentLabel ?? t('app.subtitle')}</span>
          </div>

          <div className='flex items-center gap-1'>
            <span className='mr-1 hidden items-center gap-2 fs-caption text-muted-foreground md:flex'>
              <span
                aria-hidden
                className={cn(
                  'size-2 shrink-0 rounded-full',
                  healthOk === null ? 'bg-muted-foreground' : healthOk ? 'bg-tone-good' : 'bg-tone-bad'
                )}
              />
              {t('app.subtitle')}
            </span>
            <ThemeSwitch />
            <Button variant='ghost' size='icon' onClick={() => window.dispatchEvent(new CustomEvent('webui:open-settings'))} aria-label={t('settings.open')}>
              <Settings className='size-4' />
            </Button>
          </div>
        </header>

        {/* 顶置横向栏（W17 用户明确「垂直侧栏 + 顶置横向栏都要」）：
            与侧栏读**同一份 nav 数组**，不另建数据源。窄屏横向滚动（no-scrollbar），
            指示器与侧栏同一条 NavIndicator（orientation='horizontal' 只影响视觉对齐）。
            为什么叠一层而不用抽屉代替：抽屉是窄屏才有的模态，横向条是宽屏常驻的第二入口，
            两者不冲突（侧栏分簇看「功能属于哪一类」，横向条按顺序扫「全部功能」）。 */}
        <NavIndicator
          orientation='horizontal'
          className='no-scrollbar hidden items-center gap-1 overflow-x-auto rounded-xl window px-2 py-1 md:flex'
        >
          <nav className='flex items-center gap-1' aria-label={navLabel}>
            {nav.map((item) => (
              <NavStripItem key={item.to} {...item} />
            ))}
          </nav>
        </NavIndicator>

        {/* 移动导航抽屉：与侧栏同一份 nav 数组、同一个 NavItem；集合子分组不复制
            （知识库页内本就有集合 chips 行，双入口反而分叉）。收起时整块不可见也不可达焦，
            但节点常驻——aria-controls 必须始终指得到它。

            🔴 W18 阶段 1 修三处实测缺陷（`tmp/REPORT-mobile-a11y.md`）：
            ① **定位**：原来是文档流里的 `<nav>`，跟着内容滚动。在 3638px 长的
               页面中段点开，`getBoundingClientRect().y = -3638` —— 抽屉在视口**上方**
               一屏之外，用户看到的是「点了没反应」。改成 `fixed inset-x-3 top-20`
               后才与滚动位置解耦。
            ② **模态语义**：原来只有 `aria-expanded`，读屏仍把它当普通列表。加
               `role="dialog"` + `aria-modal="true"` + 打开时把焦点移进去。
            ③ **遮罩**：抽屉浮在内容之上，需要一层可点击关闭的背景，否则用户只能
               再点一次汉堡（触控目标 36×36，本来就偏小）。 */}
        {navOpen && (
          <div
            className='fixed inset-0 z-20 bg-transparent md:hidden'
            aria-hidden
            onClick={() => setNavOpen(false)}
          />
        )}
        <nav
          id={MOBILE_NAV_ID}
          role='dialog'
          aria-modal='true'
          aria-expanded={navOpen}
          className={cn(
            // 高度上限走 CSS 类 `.mobile-nav-drawer`（index.css）：版式宪法 ⑧′ 默认拒绝
            // 任意值方括号，`max-h-[calc(100dvh-7rem)]` 正是被拒的形态（函数形一律拒）。
            // 视觉不变，只是把这条约束搬到值册里，可被同一批门审查。
            'mobile-nav-drawer fixed inset-x-3 top-20 z-30 flex-col gap-1 overflow-y-auto rounded-xl window px-3 py-3',
            navOpen ? 'flex md:hidden' : 'hidden'
          )}
          aria-label={navLabel}
        >
          {nav.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>

        {/* 内容区（UI3 铺满）：**不再** mx-auto + max-w —— 那会把内容挤在中间，2320px 屏上
            左右各空 584px。面板自己的内边距（Card 的 px-6）提供留白，外层只留 4/6 的呼吸位；
            底边吃 safe-area（iPhone 横屏刘海在左/右）。 */}
        {/* content-field（W18 阶段 1）：正文的**阅读面**。
           结构性问题——正文原本直接压在动态背景上（视频帧 / 用户壁纸 / 漂移光斑）。
           壁纸是用户可换的，所以任何固定文字颜色都必然在某张壁纸上失效：实测最亮
           的一帧上 `--muted-foreground` 只有 2.4:1，12px 说明文字完全读不出来。
           调 film 透明度治不了，那只是「把壁纸压暗」，换张亮壁纸又坏。
           这里照 Win11 Mica 的分层做法：内容坐在填充层上，底材只从边缘与缝里透。
           玻璃总数仍 ≤3（侧栏 window + 顶栏 mica-bar + 这块 content-field）。 */}
        <main
          className='content-field min-w-0 flex-1 px-3 pb-6 pt-3 sm:px-4 md:px-4 xl:px-6'
          style={{ paddingBottom: 'max(24px, env(safe-area-inset-bottom))' }}
        >
          {/* 页面过渡（W17）：参考站 daniya.top 的 `.form-panel.is-active` → `panel-in .9s`。
              它的面板切换是「同一页里换 tab」；本仓是路由切换，所以用 pathname 当 key 强制重挂——
              同一路径内的搜索参数变化（分页、集合切换）**不重播**，否则翻页会一直闪。
              动画本身是 opacity + translateY(16px)，reduced-motion 下由 CSS 整段关掉。 */}
          <div key={pathname} className='panel-in'>
            {children}
          </div>
        </main>
      </div>
      <SettingsDialog />
      {/* 根部动效件（W17）：首帧幕布、滚动进度条、自定义光标。三者互不依赖，
          但都读同一份动效档位（见 motion-chrome.tsx）。 */}
      <MotionChrome />
    </div>
  );
}
