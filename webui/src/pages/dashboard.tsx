import { useTranslation } from 'react-i18next';
import { Activity, Bot, Coins, Gauge, Inbox, Radio } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  CategoryChip,
  DataGrid,
  DataGridCell,
  DataGridRow,
  PageHeader,
  SectionCard,
  StatCard,
} from '@/components/patterns/patterns';
import { SemanticState, openSettings, reasonKey } from '@/components/semantic/semantic-state';
import { useSemanticQuery, type DataState } from '@/hooks/use-semantic-query';
import { controlApi, type CallsData, type HealthData, type BotStatusData, type LatencyData, type TokensData } from '@/lib/api-client';
import { formatDateTime, formatInt, formatUptime } from '@/lib/format';

// 总览页（Phase A 真数据）：全部由现有只读端点拼装——
// /admin/api/v1/health + /status/bot + /api/v1/stats/calls|tokens|latency。
// 发送队列/活动告警 Phase A 无只读端点 → 诚实标「未接入」，不造数。
// BACKEND3 消费（2026-09-18 FE3，§7 A4/A5）：「消息调用键值明细」卡——今日(24h)/近7天
// 两个窗口各取一次 stats/calls（跨窗不合并、不造全表 max），取 total_calls +
// active_users + last_message_at 做 label 左/value 右键值行（DataGrid 分隔线）；
// 字段缺省（旧控制面）如实显示 —，窗口无记录 last_message_at=null → —（不造时间）。

function withFallback(state: DataState<unknown>, node: React.ReactNode): React.ReactNode {
  return state.phase === 'ok' ? node : <SemanticState state={state} />;
}

/** 非 ok 语义态 → 一行人话（known reason 走 i18n，未知码/错误消息原样，绝不编语义）。 */
function fallbackLine(state: DataState<CallsData>, t: (key: string) => string): string {
  if (state.phase === 'unavailable') {
    const key = reasonKey(state.reason);
    if (key) {
      const translated = t(key);
      if (translated !== key) return `${t('state.noData')}：${translated}`;
    }
    return `${t('state.noData')}：${state.reason}`;
  }
  if (state.phase === 'error') return `${t('state.loadFailed')}：${state.message}`;
  return t('state.noData');
}

/** 键值行：label 左 / value 右 + 分隔线（DataGrid 全站行高）。 */
function KvRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <DataGridRow>
      <DataGridCell className='flex-1 fs-body text-muted-foreground'>
        <span title={hint}>{label}</span>
      </DataGridCell>
      <DataGridCell className='shrink-0 text-right fs-body tabular-nums'>{value}</DataGridCell>
    </DataGridRow>
  );
}

/** 单窗口键值组：ok → 三行键值；loading → 骨架；其余 → 一行人话（不炸整卡）。 */
function CallsDetailGroup({ label, state, data }: { label: string; state: DataState<CallsData>; data: CallsData | null }) {
  const { t } = useTranslation();
  return (
    <div className='flex flex-col gap-2'>
      <p className='fs-caption font-medium text-muted-foreground'>{label}</p>
      {state.phase === 'ok' && data ? (
        <DataGrid>
          <KvRow label={t('dashboard.overview.rowCalls')} value={formatInt(data.total_calls)} />
          <KvRow
            label={t('dashboard.overview.rowActiveUsers')}
            hint={t('dashboard.overview.activeUsersHint')}
            value={data.active_users != null ? formatInt(data.active_users) : '—'}
          />
          <KvRow
            label={t('dashboard.overview.rowLastMessage')}
            value={data.last_message_at ? formatDateTime(data.last_message_at) : '—'}
          />
        </DataGrid>
      ) : state.phase === 'loading' ? (
        <div className='flex flex-col gap-2'>
          <Skeleton className='h-4 w-full' />
          <Skeleton className='h-4 w-2/3' />
          <Skeleton className='h-4 w-1/2' />
        </div>
      ) : (
        <p className='fs-caption text-muted-foreground'>{fallbackLine(state, t)}</p>
      )}
    </div>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();

  const health = useSemanticQuery<HealthData>(['health'], () => controlApi.health(), { refetchInterval: 30_000 });
  const botStatus = useSemanticQuery<BotStatusData>(['status-bot'], () => controlApi.statusBot(), { refetchInterval: 30_000 });
  const calls = useSemanticQuery<CallsData>(['stats-calls', '24h', 'overview'], () => controlApi.statsCalls({ window: '24h', bucket: 'hour', limit: 5 }), { refetchInterval: 60_000 });
  // §7 A4/A5：近 7 天窗口独立取数（与 24h 各一次，不跨窗合并）；limit=1 最小化趋势/TopN 载荷。
  const calls7d = useSemanticQuery<CallsData>(['stats-calls', '7d', 'overview'], () => controlApi.statsCalls({ window: '7d', bucket: 'day', limit: 1 }), { refetchInterval: 60_000 });
  const tokens = useSemanticQuery<TokensData>(['stats-tokens', '24h', 'overview'], () => controlApi.statsTokens({ window: '24h', limit: 5 }), { refetchInterval: 60_000 });
  const latency = useSemanticQuery<LatencyData>(['stats-latency', 'overview'], () => controlApi.statsLatency(), { refetchInterval: 60_000 });

  const queries = [health, botStatus, calls, calls7d, tokens, latency];
  const blocking = queries.find(
    (query) => query.state.phase === 'not_provisioned' || query.state.phase === 'auth'
  );
  if (blocking) {
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('nav.overview')} />
        <SemanticState state={blocking.state} />
      </div>
    );
  }

  const healthData = health.state.phase === 'ok' ? health.state.data : null;
  const botData = botStatus.state.phase === 'ok' ? botStatus.state.data : null;
  const callsData = calls.state.phase === 'ok' ? calls.state.data : null;
  const calls7dData = calls7d.state.phase === 'ok' ? calls7d.state.data : null;
  const tokensData = tokens.state.phase === 'ok' ? tokens.state.data : null;
  const latencyData = latency.state.phase === 'ok' ? latency.state.data : null;

  const failingChannels = latencyData ? latencyData.items.filter((item) => item.consecutive_fails > 0).length : 0;
  const totalChannels = latencyData ? latencyData.items.length : 0;

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader title={t('nav.overview')} subtitle={t('dashboard.overview.aboutDesc')} />

      <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
        <StatCard
          icon={<Activity className='size-4 text-tone-good' />}
          label={t('dashboard.overview.health')}
          action={
            healthData ? (
              <Badge variant={healthData.ok ? 'default' : 'destructive'}>
                {healthData.ok ? t('dashboard.overview.online') : t('dashboard.overview.degraded')}
              </Badge>
            ) : undefined
          }
        >
          {withFallback(
            health.state,
            healthData ? (
              <div className='flex flex-wrap gap-2'>
                {Object.entries(healthData.checks).map(([name, status]) => (
                  <CategoryChip key={name} label={name} tone={status === 'ok' ? 'good' : 'bad'} />
                ))}
                <p className='w-full fs-caption text-muted-foreground'>{formatDateTime(healthData.generated_at)}</p>
              </div>
            ) : null
          )}
        </StatCard>

        <StatCard
          icon={<Bot className='size-4 text-primary' />}
          label={t('dashboard.overview.botProcess')}
          value={botData ? formatUptime(botData.uptime_seconds) : undefined}
          sub={
            botData
              ? `${t('dashboard.overview.startedAt')} ${formatDateTime(botData.started_at)}${botData.timezone ? ` · ${botData.timezone}` : ''}`
              : undefined
          }
        >
          {withFallback(botStatus.state, null)}
        </StatCard>

        <StatCard
          label={t('dashboard.overview.calls24h')}
          value={callsData ? formatInt(callsData.total_calls) : undefined}
          sub={
            callsData
              ? t('dashboard.overview.callsFootnote', {
                  unknown: callsData.unknown_timestamp_calls,
                  unattributed: callsData.unattributed_calls,
                })
              : undefined
          }
        >
          {withFallback(calls.state, null)}
        </StatCard>

        <StatCard
          icon={<Coins className='size-4 text-tone-purple' />}
          label={t('dashboard.overview.llm24h')}
          value={tokensData ? formatInt(tokensData.totals?.calls) : undefined}
          sub={
            tokensData
              ? `${t('tokens.input')} ${formatInt(tokensData.totals?.tokens.input.value)} · ${t('tokens.output')} ${formatInt(tokensData.totals?.tokens.output.value)}`
              : undefined
          }
        >
          {withFallback(tokens.state, null)}
        </StatCard>

        <StatCard
          icon={<Gauge className='size-4 text-tone-info' />}
          label={t('dashboard.overview.channels')}
          value={latencyData ? `${totalChannels - failingChannels}/${totalChannels}` : undefined}
          sub={latencyData ? t('dashboard.overview.channelsFootnote') : undefined}
        >
          {withFallback(latency.state, null)}
        </StatCard>

        <StatCard label={t('dashboard.overview.notWired')}>
          <div className='flex flex-col gap-2'>
            <p className='flex items-center gap-2 fs-caption text-muted-foreground'>
              <Inbox className='size-4' />
              {t('dashboard.overview.queue')}
            </p>
            <p className='flex items-center gap-2 fs-caption text-muted-foreground'>
              <Radio className='size-4' />
              {t('dashboard.overview.alerts')}
            </p>
          </div>
        </StatCard>
      </div>

      <SectionCard
        title={t('dashboard.overview.callsDetailTitle')}
        description={t('dashboard.overview.callsDetailDesc')}
      >
        <div className='flex flex-col gap-6'>
          <CallsDetailGroup label={t('dashboard.overview.windowToday')} state={calls.state} data={callsData} />
          <CallsDetailGroup label={t('dashboard.overview.window7d')} state={calls7d.state} data={calls7dData} />
        </div>
      </SectionCard>

      <SectionCard title={t('dashboard.overview.about')} description={t('dashboard.overview.aboutDesc')}>
        <div className='flex items-center justify-between gap-2'>
          <p className='flex items-center gap-2 fs-caption text-muted-foreground'>
            <Bot className='size-4' />
            <Coins className='size-4' />
            {t('dashboard.overview.aboutBody')}
          </p>
          <Button size='sm' variant='ghost' onClick={openSettings}>
            <Gauge className='size-4' />
            {t('settings.open')}
          </Button>
        </div>
      </SectionCard>
    </div>
  );
}
