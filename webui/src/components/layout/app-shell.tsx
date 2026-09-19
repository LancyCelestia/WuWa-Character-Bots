import { Blocks, Gauge, Heart, LayoutDashboard, Library, Network, ScrollText, BarChart3, Coins, Waves, Settings } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from '@tanstack/react-router';
import { ThemeSwitch } from '@/components/theme-switch';
import { SettingsDialog } from '@/components/settings/settings-dialog';
import { Button } from '@/components/ui/button';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type KnowledgeCollectionsData } from '@/lib/api-client';
import { pickEnabledCollections } from '@/lib/semantics';
import { cn } from '@/lib/utils';

// 布局壳：侧边栏 + 顶栏 + 内容区。模式保留自 AxonHub authenticated-layout（精简：
// 上游 shadcn sidebar 全家桶/权限守卫/搜索上下文裁掉，导航 Link 直连 hash 路由）。

// 知识库侧栏子分组（spec §4）：只列前 8 个可用集合 + 溢出「更多…」；
// collections 端点不可用/加载中 → 整组不渲染（不放假子项）。
function NavSubItem({ label, collection }: { label: string; collection?: string }) {
  return (
    <Link
      to='/knowledge'
      search={collection ? { collection } : {}}
      className='block truncate rounded-md py-1 pl-6 pr-2 fs-caption text-muted-foreground transition-colors hover:text-foreground [&.active]:text-primary [&.active]:font-medium'
      activeProps={{ className: 'active' }}
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
  const enabledCollections =
    collectionsQuery.state.phase === 'ok'
      ? pickEnabledCollections(collectionsQuery.state.data.items)
      : [];
  const subCollections = enabledCollections.slice(0, 8);
  const hasMoreCollections = enabledCollections.length > 8;

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
        <nav className='flex flex-1 flex-col gap-1 px-3 py-2'>
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
        <main className='flex-1 px-4 py-6 md:px-6'>{children}</main>
      </div>
      <SettingsDialog />
    </div>
  );
}
