import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownWideNarrow, ArrowUpNarrowWide } from 'lucide-react';
import { PageHeader, SectionCard, DataGrid, DataGridRow, DataGridCell, CategoryChip, type Tone } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type AffinityBoardData, type AffinityItem } from '@/lib/api-client';
import { formatDateTime, formatInt } from '@/lib/format';
import { cn } from '@/lib/utils';

// 好感度榜：/api/v1/affinity/board（user_affinity 只读，显数值口径——
// 2026-09-15 用户裁定 WebUI 面板直显数值；聊天内侧定性口径不受影响，两处不同源）。
// 档位色阶：独一份=品红紫、挚友=紫、亲近=品牌蓝、友善=info、稍淡=warn、生疏/初识=bad（负值红阶）。

function tierTone(tier: number): Tone {
  if (tier >= 3) return 'magenta';
  if (tier === 2) return 'purple';
  if (tier === 1) return 'brand';
  if (tier === 0) return 'info';
  if (tier === -1 || tier === -2) return 'warn';
  return 'bad';
}

function scoreClass(score: number): string {
  if (score >= 25) return 'text-primary';
  if (score > 0) return 'text-tone-info';
  if (score === 0) return 'text-muted-foreground';
  if (score >= -50) return 'text-tone-warn';
  return 'text-tone-bad';
}

function BoardRow({ item, rank }: { item: AffinityItem; rank: number }) {
  const { t } = useTranslation();
  return (
    <DataGridRow>
      <DataGridCell className='w-8 shrink-0 text-right tabular-nums text-muted-foreground'>{rank}</DataGridCell>
      <DataGridCell className='flex-1'>
        <div className='truncate fs-body font-medium' title={item.nickname || item.sender_id}>
          {item.nickname || item.sender_id}
        </div>
        <div className='truncate font-mono fs-caption text-muted-foreground'>
          {item.sender_id}
          {item.nickname ? ` · ${t('affinity.interactions', { count: formatInt(item.interaction_count) })}` : ''}
        </div>
      </DataGridCell>
      <DataGridCell className='w-24 shrink-0 text-right'>
        <span className={cn('fs-card tabular-nums', scoreClass(item.score))}>
          {item.score > 0 ? '+' : ''}
          {item.score.toFixed(1)}
        </span>
      </DataGridCell>
      <DataGridCell className='w-24 shrink-0'>
        <CategoryChip label={item.tier_name} tone={tierTone(item.tier)} />
      </DataGridCell>
      <DataGridCell className='w-36 shrink-0 text-right fs-caption text-muted-foreground'>
        {formatDateTime(item.updated_at)}
      </DataGridCell>
    </DataGridRow>
  );
}

export function AffinityPage() {
  const { t } = useTranslation();
  const [order, setOrder] = useState<'desc' | 'asc'>('desc');

  const query = useSemanticQuery<AffinityBoardData>(
    ['affinity-board', order],
    () => controlApi.affinityBoard({ limit: 100, order }),
    { refetchInterval: 120_000 }
  );

  const data = query.state.phase === 'ok' ? query.state.data : null;

  return (
    <div className='mx-auto flex w-full max-w-4xl flex-col gap-4'>
      <PageHeader
        title={t('affinity.title')}
        subtitle={t('affinity.boardDesc')}
        actions={
          <>
            {data && <span className='fs-caption text-muted-foreground'>{t('affinity.total', { count: data.total })}</span>}
            <button
              type='button'
              onClick={() => setOrder(order === 'desc' ? 'asc' : 'desc')}
              className='flex items-center gap-2 rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'
            >
              {order === 'desc' ? <ArrowDownWideNarrow className='size-4' /> : <ArrowUpNarrowWide className='size-4' />}
              {order === 'desc' ? t('affinity.orderDesc') : t('affinity.orderAsc')}
            </button>
          </>
        }
      />

      {query.state.phase === 'ok' && data ? (
        <SectionCard title={t('affinity.boardTitle')}>
          {data.items.length === 0 ? (
            <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
          ) : (
            <DataGrid>
              {data.items.map((item, index) => (
                <BoardRow key={item.sender_id} item={item} rank={index + 1} />
              ))}
            </DataGrid>
          )}
        </SectionCard>
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}
