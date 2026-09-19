import { useTranslation } from 'react-i18next';
import { History, TriangleAlert } from 'lucide-react';
import { PageHeader, SectionCard, DataGrid, DataGridRow, DataGridCell, CategoryChip, type Tone } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type LatencyData, type LatencyItem } from '@/lib/api-client';
import { formatDateTime, formatMs, formatInt, UNKNOWN_VALUE } from '@/lib/format';

// 渠道延迟面板：/api/v1/stats/latency（channel_health store 当前值投影）。
// 状态 tone：fail*/dead/error*=bad、degrade*/timeout*=warn、其余=good；EWMA/最近延迟/样本/连败。
// history 后端显式 {status:"unavailable",reason:"not_persisted"} → 「暂无历史」诚实呈现，不画假曲线。

function stateTone(state: string, consecutiveFails: number): Tone {
  const lowered = state.toLowerCase();
  if (consecutiveFails > 0 || lowered.includes('fail') || lowered.includes('dead') || lowered.includes('error')) return 'bad';
  if (lowered.includes('degrade') || lowered.includes('timeout') || lowered.includes('slow')) return 'warn';
  if (!state) return 'flat';
  return 'good';
}

function ChannelRow({ item }: { item: LatencyItem }) {
  const { t } = useTranslation();
  return (
    <DataGridRow>
      <DataGridCell className='w-56 shrink-0 font-mono fs-caption font-medium'>{item.channel || UNKNOWN_VALUE}</DataGridCell>
      <DataGridCell className='w-24 shrink-0'>
        <CategoryChip label={item.state || 'unknown'} tone={stateTone(item.state, item.consecutive_fails)} />
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums'>
        {formatMs(item.ema_ms)}
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums text-muted-foreground'>
        {formatMs(item.latency_ms)}
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums text-muted-foreground'>
        {t('latency.samplesCount', { count: formatInt(item.samples) })}
      </DataGridCell>
      <DataGridCell className='w-12 shrink-0'>
        {item.consecutive_fails > 0 && (
          <CategoryChip label={`×${item.consecutive_fails}`} tone='bad' />
        )}
      </DataGridCell>
      <DataGridCell className='flex-1 text-muted-foreground' >
        {item.last_error || formatDateTime(item.last_ok_at)}
      </DataGridCell>
    </DataGridRow>
  );
}

export function LatencyPage() {
  const { t } = useTranslation();

  const query = useSemanticQuery<LatencyData>(['stats-latency', 'page'], () => controlApi.statsLatency(), {
    refetchInterval: 30_000,
  });

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader
        title={t('latency.title')}
        subtitle={t('latency.source')}
        actions={
          <span className='fs-caption text-muted-foreground'>
            EWMA / {t('latency.last')} / {t('latency.samples')}
          </span>
        }
      />

      {query.state.phase === 'ok' ? (
        <>
          <SectionCard title={t('latency.channels', { count: query.state.data.items.length })}>
            {query.state.data.items.length === 0 ? (
              <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
            ) : (
              <DataGrid>
                {query.state.data.items.map((item) => (
                  <ChannelRow key={item.channel} item={item} />
                ))}
              </DataGrid>
            )}
          </SectionCard>

          <SectionCard
            title={
              <span className='flex items-center gap-2'>
                <History className='size-4' />
                {t('latency.history')}
              </span>
            }
            description={
              query.state.data.history?.status === 'unavailable'
                ? t('latency.historyUnavailable', { reason: query.state.data.history?.reason ?? '' })
                : undefined
            }
          >
            <div className='flex items-center gap-2 py-2'>
              {query.state.data.history?.status === 'unavailable' && (
                <TriangleAlert className='size-4 text-tone-warn' />
              )}
              <p className='fs-caption text-muted-foreground'>
                {query.state.data.history?.status === 'unavailable' ? t('latency.noHistory') : t('state.noData')}
              </p>
            </div>
          </SectionCard>
        </>
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}
