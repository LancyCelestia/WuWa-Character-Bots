import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHeader, SectionCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type PluginGroup, type PluginItem, type PluginsCatalogData } from '@/lib/api-client';

// 插件页（spec webui-pages2 §2 + §7 D 系增补）：四组固定顺序（builtins/adapters/
// event_matchers/migrated_modules），组头=组名+数量徽章+组描述；组内等宽 3 列卡。
// hot_reload 三态严格：true=success 徽章（值册 SEMANTIC_SUCCESS 投影，主会话裁决）/false=secondary/null 不渲染。
// BACKEND3 字段消费（2026-09-18 FE3，真相源=control_plane/webui_plugins.py）：
// version!=null → 名称旁 mono 版本徽章（v 前缀）；trigger_hints!=null → 卡内「别名」行
//（能力别名口径，措辞降为「别名」，§7 D6 对表说明）；config_actions 非空才渲染配置入口
// 提示（只读文本不放假按钮，§2.4）；三者缺省/null 一律不渲染（旧控制面兼容，不猜）。

const GROUP_ORDER = ['builtins', 'adapters', 'event_matchers', 'migrated_modules'];

function isNotFound(message: string): boolean {
  return /HTTP 404/.test(message);
}

/** 组级 reason → 人话（已知码走 i18n，未知码回退原码，绝不编语义）。 */
function reasonText(reason: string | null, t: (key: string) => string): string {
  if (!reason) return '';
  const key = `reason.${reason}`;
  const translated = t(key);
  return translated === key ? `：${reason}` : `：${translated}`;
}

function HotReloadBadge({ value }: { value: boolean | null | undefined }) {
  const { t } = useTranslation();
  if (value === true) return <Badge variant='success'>{t('plugins.hotReload')}</Badge>;
  if (value === false) return <Badge variant='secondary'>{t('plugins.needsRestart')}</Badge>;
  return null; // null/缺字段：三态严格，不猜。
}

function PluginCard({ item }: { item: PluginItem }) {
  const { t } = useTranslation();
  const description = typeof item.description === 'string' && item.description ? item.description : null;
  // BACKEND3 三字段全条件渲染：null/空表/缺字段即省略（旧控制面兼容，禁造数）。
  const version = typeof item.version === 'string' && item.version ? item.version : null;
  const aliases = Array.isArray(item.trigger_hints) && item.trigger_hints.length > 0 ? item.trigger_hints : null;
  const configActions =
    Array.isArray(item.config_actions) && item.config_actions.length > 0 ? item.config_actions : null;
  return (
    <SectionCard
      title={
        <span className='flex min-w-0 flex-wrap items-center gap-2'>
          <span className='min-w-0 truncate'>{item.name}</span>
          {version && (
            <Badge variant='outline' className='font-mono'>
              v{version}
            </Badge>
          )}
        </span>
      }
      action={<HotReloadBadge value={item.hot_reload} />}
    >
      <div className='flex flex-col gap-2'>
        <p className='fs-body text-muted-foreground'>{description ?? t('plugins.noDescription')}</p>
        {aliases && (
          <div className='flex flex-wrap items-center gap-2'>
            <span className='shrink-0 fs-caption text-muted-foreground'>{t('plugins.aliases')}</span>
            <span className='flex min-w-0 flex-wrap gap-1'>
              {aliases.map((alias) => (
                <Badge key={alias} variant='secondary'>
                  {alias}
                </Badge>
              ))}
            </span>
          </div>
        )}
        {configActions && (
          <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
            <span className='shrink-0 fs-caption text-muted-foreground'>{t('plugins.configActions')}</span>
            {configActions.map((action) => (
              <span key={action.action_id} className='flex min-w-0 items-center gap-1 fs-caption'>
                <span>{action.name}</span>
                <span className='font-mono text-muted-foreground' title={action.action_id}>
                  {action.action_id}
                </span>
              </span>
            ))}
          </div>
        )}
        <div className='flex items-center gap-2'>
          <Badge variant='outline' className='font-mono'>
            {item.source}
          </Badge>
          {item.id && (
            <span className='min-w-0 truncate font-mono fs-caption text-muted-foreground' title={item.id}>
              {item.id}
            </span>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function GroupSkeleton() {
  return (
    <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
      {[0, 1, 2].map((index) => (
        <Skeleton key={index} className='h-32' />
      ))}
    </div>
  );
}

function GroupBlock({ group }: { group: PluginGroup }) {
  const { t } = useTranslation();
  // 组级不可用（event_matchers 恒定如此；其余组单源故障降级同形）→ 整组一张诚实空态卡，不渲染空网格。
  if (!group.enabled) {
    return (
      <SectionCard title={group.name} description={group.description}>
        <p className='py-4 text-center fs-body text-muted-foreground'>
          {t('plugins.unavailable')}
          {reasonText(group.reason, t)}
        </p>
      </SectionCard>
    );
  }
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <h2 className='fs-page'>{group.name}</h2>
        <Badge variant='secondary'>{t('plugins.items', { count: group.items.length })}</Badge>
        {group.description && <span className='fs-caption text-muted-foreground'>{group.description}</span>}
      </div>
      {group.items.length === 0 ? (
        <p className='fs-body text-muted-foreground'>{t('plugins.emptyGroup')}</p>
      ) : (
        <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
          {group.items.map((item, index) => (
            <PluginCard key={`${item.name}:${index}`} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

export function PluginsPage() {
  const { t } = useTranslation();
  const query = useSemanticQuery<PluginsCatalogData>(['plugins'], () => controlApi.pluginsCatalog());

  // 四组固定顺序渲染（后端顺序不作依赖）。
  const groups =
    query.state.phase === 'ok'
      ? [...query.state.data.groups].sort(
          (a, b) => GROUP_ORDER.indexOf(a.id) - GROUP_ORDER.indexOf(b.id)
        )
      : null;

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-6'>
      <PageHeader title={t('plugins.title')} subtitle={t('plugins.subtitle')} />

      {query.state.phase === 'loading' ? (
        <>
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className='flex flex-col gap-4'>
              <Skeleton className='h-8 w-48' />
              <GroupSkeleton />
            </div>
          ))}
        </>
      ) : query.state.phase === 'error' ? (
        isNotFound(query.state.message) ? (
          <SectionCard title={t('plugins.notDeployed')}>
            <p className='fs-body text-muted-foreground'>{t('plugins.notDeployedHint')}</p>
          </SectionCard>
        ) : (
          <SemanticState state={query.state} onRetry={query.refetch} />
        )
      ) : query.state.phase === 'ok' && groups ? (
        groups.map((group) => <GroupBlock key={group.id} group={group} />)
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}
