import { Blocks, Gauge, Heart, LayoutDashboard, Library, Network, ScrollText, BarChart3, Coins, Waves, Settings, Menu, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useRouterState } from '@tanstack/react-router';
import { ThemeSwitch } from '@/components/theme-switch';
import { SettingsDialog } from '@/components/settings/settings-dialog';
import { Button } from '@/components/ui/button';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type KnowledgeCollectionsData } from '@/lib/api-client';
import { pickEnabledCollections } from '@/lib/semantics';
import { cn } from '@/lib/utils';

// 布局壳：侧边栏 + 顶栏 + 内容区。模式保留自 AxonHub authenticated-layout（精简：
// 上游 shadcn sidebar 全家桶/权限守卫/搜索上下文裁掉，导航 Link 直连 hash 路由）。
//
// 窄视口（手机）：侧栏整条不渲染，页面切换入口改由顶栏的导航抽屉承担——
// 抽屉与侧栏**同一份 nav 数组、同一个 NavItem**，不另起第二套导航数据（F12-01）。
// 抽屉只做「展开/收起」，不做焦点陷阱、不做模态遮罩：里面就是九个原生链接，
// Tab 与读屏器走的是最朴素的文档序（APG disclosure 的最小可实施子集）。

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

function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <Link
      to={to}
      className='flex items-center gap-3 rounded-md px-3 py-2 fs-body text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground [&.active]:bg-primary [&.active]:text-primary-foreground [&.active]:font-medium'
      activeProps={{ className: 'active' }}
    >
      {icon}
      <span>{label}</span>
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

  const nav = [
    { to: '/', icon: <LayoutDashboard className='size-4' />, label: t('nav.overview') },
    { to: '/calls', icon: <BarChart3 className='size-4' />, label: t('nav.calls') },
    { to: '/tokens', icon: <Coins className='size-4' />, label: t('nav.tokens') },
    { to: '/latency', icon: <Gauge className='size-4' />, label: t('nav.latency') },
    { to: '/affinity', icon: <Heart className='size-4' />, label: t('nav.affinity') },
    { to: '/logs', icon: <ScrollText className='size-4' />, label: t('nav.logs') },
    { to: '/knowledge', icon: <Library className='size-4' />, label: t('nav.knowledge') },
    { to: '/plugins', icon: <Blocks className='size-4' />, label: t('nav.plugins') },
    { to: '/memory-graph', icon: <Network className='size-4' />, label: t('nav.memoryGraph') },
  ];

  const collectionsQuery = useSemanticQuery<KnowledgeCollectionsData>(
    ['knowledge', 'collections'],
    () => controlApi.knowledgeCollections()
  );
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
    <div className='flex min-h-svh w-full'>
      <aside
        className={cn(
          'sticky top-0 hidden h-svh w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:flex'
        )}
      >
        <div className='flex items-center gap-3 px-4 py-4'>
          <span className='flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground'>
            <Waves className='size-5' />
          </span>
          <div className='leading-tight'>
            <div className='fs-card'>{t('app.title')}</div>
            <div className='fs-caption text-muted-foreground'>{t('app.subtitle')}</div>
          </div>
        </div>
        <nav className='flex flex-1 flex-col gap-1 px-3 py-2' aria-label={navLabel}>
          {nav.map((item) => (
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
        </nav>
        <div className='px-4 py-4 fs-caption text-muted-foreground'>
          {t('app.footer')}
        </div>
      </aside>

      <div className='flex min-w-0 flex-1 flex-col'>
        <header className='sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/80 px-4 backdrop-blur md:px-6'>
          <div className='flex items-center gap-2 md:hidden'>
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
            <span className='flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground'>
              <Waves className='size-4' />
            </span>
            <span className='fs-card'>{t('app.title')}</span>
          </div>
          <div className='hidden fs-body text-muted-foreground md:block'>{t('app.subtitle')}</div>
          <div className='flex items-center gap-1'>
            <ThemeSwitch />
            <Button variant='ghost' size='icon' onClick={() => window.dispatchEvent(new CustomEvent('webui:open-settings'))} aria-label={t('settings.open')}>
              <Settings className='size-4' />
            </Button>
          </div>
        </header>

        {/* 移动导航抽屉：与侧栏同一份 nav 数组、同一个 NavItem；集合子分组不复制
            （知识库页内本就有集合 chips 行，双入口反而分叉）。收起时整块不可见也不可达焦，
            但节点常驻——aria-controls 必须始终指得到它。 */}
        <nav
          id={MOBILE_NAV_ID}
          className={cn('flex-col gap-1 border-b px-3 py-3', navOpen ? 'flex md:hidden' : 'hidden')}
          aria-label={navLabel}
        >
          {nav.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>

        <main className='flex-1 px-4 py-6 md:px-6'>{children}</main>
      </div>
      <SettingsDialog />
    </div>
  );
}
