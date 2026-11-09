import { Button } from '@/components/ui/button';
import { PageHeader, SectionCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { centerApi, safeText, type LLMProvidersData, type LLMChannelsData, type LLMHealthData, type LLMRoutesData } from '@/lib/control-center';
import { formatCount, UNKNOWN_VALUE } from '@/lib/format';
import { fieldLabel, humanizeEnum } from '@/lib/humanize';
import { ChannelHealthView } from '@/components/control-center/channel-health';

export function ResourcesPage() {
  const query = useSemanticQuery(['center', 'resources'], centerApi.resources, { refetchInterval: 5000 });
  const snapshot = query.state.phase === 'ok' ? query.state.data as Awaited<ReturnType<typeof centerApi.resources>> : null;
  return <div className='flex flex-col gap-6'><PageHeader title='实时资源' subtitle='当前采样每五秒刷新；未知、预热与未连接保持独立，不填成零。' actions={<Button variant='outline' onClick={query.refetch}>刷新</Button>} />
    <SemanticState state={query.state} onRetry={query.refetch}><SectionCard title={snapshot ? `${snapshot.process_role} · PID ${snapshot.pid}` : '进程采样'} description={snapshot?.captured_at}>
      <div className='overflow-x-auto'><table className='w-full fs-body'><thead><tr className='border-b text-left'><th className='p-3'>指标</th><th className='p-3'>读数</th><th className='p-3'>状态</th></tr></thead><tbody>{Object.entries(snapshot?.measurements ?? {}).map(([key, measurement]) => <tr key={key} className='border-b last:border-0'><td className='p-3'>{fieldLabel(key)}</td><td className='p-3 tabular-nums'>{measurement.value === null ? UNKNOWN_VALUE : formatCount(measurement.value)} <span className='text-muted-foreground'>{measurement.unit}</span></td><td className='p-3'>{measurement.status === 'ok' ? '可用' : humanizeEnum(measurement.reason ?? 'unknown')}</td></tr>)}</tbody></table></div>
    </SectionCard></SemanticState><p className='fs-caption text-muted-foreground'>此页仅显示已装配进程。没有 Bot／渲染器／网关来源时不会伪造它们的占用。</p>
  </div>;
}

export function ModelsPage() {
  const providers = useSemanticQuery<LLMProvidersData>(['center', 'providers'], centerApi.llmProviders);
  const channels = useSemanticQuery<LLMChannelsData>(['center', 'channels'], centerApi.llmChannels);
  const health = useSemanticQuery<LLMHealthData>(['center', 'health'], centerApi.llmHealth);
  const routes = useSemanticQuery<LLMRoutesData>(['center', 'routes'], centerApi.llmRoutes);
  const query = useSemanticQuery(['center', 'models'], centerApi.models);
  const data = query.state.phase === 'ok' ? query.state.data as Awaited<ReturnType<typeof centerApi.models>> : null;
  return <div className='flex flex-col gap-6'>
    <PageHeader title='模型与渠道' subtitle='来自现有模型登记服务；厂商挂牌价、中转报价、账本估算与实付不能混为一项。' actions={<Button variant='outline' onClick={() => { query.refetch(); providers.refetch(); channels.refetch(); health.refetch(); routes.refetch(); }}>刷新</Button>} />
    <SemanticState state={query.state} onRetry={query.refetch}>
      <div className='divide-y rounded-lg border'>
        {(data?.items ?? []).map((row, index) => (
          <section key={String(row.id ?? row.model_id ?? index)} className='p-4'>
            <h2 className='font-mono fs-body'>{String(row.id ?? row.model_id ?? row.name ?? '未命名模型')}</h2>
            <dl className='mt-3 grid gap-2 sm:grid-cols-2'>
              {Object.entries(row).map(([key, value]) => (
                <div key={key} className='min-w-0'>
                  <dt className='fs-caption text-muted-foreground'>{fieldLabel(key)}</dt>
                  <dd className='break-words fs-body'>{safeText(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {!data?.items?.length && <p className='p-6 fs-body text-muted-foreground'>模型来源未接通或暂无登记，未用估算填补。</p>}
      </div>
    </SemanticState>
    <SectionCard title='供应商来源' description='按后端登记的来源聚合，只读；不展示密钥。'>
      <SemanticState state={providers.state} onRetry={providers.refetch}>
        {providers.state.phase === 'ok' && <div className='divide-y'>
          {providers.state.data.items.map(row => <div key={row.provider_id} className='grid min-w-0 gap-1 py-3 sm:grid-cols-2'>
            <p className='break-words fs-body'>{row.label}</p>
            <p className='break-words fs-caption text-muted-foreground'>{row.channels} 个渠道 · {row.credentials_configured} 份已配凭据 · {row.models.join('、')}</p>
          </div>)}
          {!providers.state.data.items.length && <p className='fs-body text-muted-foreground'>暂无登记来源。</p>}
        </div>}
      </SemanticState>
    </SectionCard>
    <SectionCard title='渠道采样' description='未知延迟不填零；健康状态不代表此刻一定可达。'>
      <SemanticState state={channels.state} onRetry={channels.refetch}>
        {channels.state.phase === 'ok' && <div className='overflow-x-auto'><table className='w-full fs-body'><thead><tr className='border-b text-left'><th className='p-3'>渠道 / 模型</th><th className='p-3'>优先级</th><th className='p-3'>健康采样</th><th className='p-3'>凭据状态</th></tr></thead><tbody>
          {channels.state.data.items.map(row => <tr key={row.channel_id} className='border-b last:border-0'>
            <td className='break-words p-3'>{row.channel_id}<span className='block fs-caption text-muted-foreground'>{row.model}</span></td>
            <td className='p-3 tabular-nums'>{row.priority}</td><td className='p-3'><ChannelHealthView health={row.health} /></td>
            <td className='p-3'>{humanizeEnum(row.credential.state)}</td>
          </tr>)}
        </tbody></table>{!channels.state.data.items.length && <p className='py-3 fs-body text-muted-foreground'>暂无登记渠道。</p>}</div>}
      </SemanticState>
    </SectionCard>
    <SectionCard title='健康层与路由策略' description='只读有效策略与候选顺序；此页不发模型探针、不重载路由。'>
      <SemanticState state={health.state} onRetry={health.refetch}>
        {health.state.phase === 'ok' && <p className='fs-body'>健康层 {health.state.data.health_layer_enabled ? '启用' : '未启用'} · {humanizeEnum(health.state.data.status)} · 冷却渠道 {health.state.data.cooling_ids.length} · 不可用渠道 {health.state.data.unavailable_ids.length}</p>}
      </SemanticState>
      <SemanticState state={routes.state} onRetry={routes.refetch}>
        {routes.state.phase === 'ok' && <div className='mt-3 flex flex-col gap-3'>
          <p className='fs-caption text-muted-foreground'>严格优先级 {routes.state.data.policy.strict_priority ? '是' : '否'} · 单跳超时 {routes.state.data.policy.timeout_seconds} 秒 · 当前组 {routes.state.data.policy.priority_groups.active_name || '未指定'}</p>
          {routes.state.data.routes.map(row => <div key={row.model} className='min-w-0 border-t pt-3'>
            <h3 className='break-words font-mono fs-body'>{row.model}</h3>
            <ol className='mt-2 list-inside list-decimal fs-caption text-muted-foreground'>{row.channels.map((channel, index) => <li key={String(channel.channel_id ?? index)} className='break-words'>{String(channel.channel_id ?? '未知')} · {humanizeEnum(channel.health_state ?? 'unknown')}</li>)}</ol>
          </div>)}
          {!routes.state.data.routes.length && <p className='fs-body text-muted-foreground'>没有可自动路由的模型。</p>}
        </div>}
      </SemanticState>
    </SectionCard>
  </div>;
}
