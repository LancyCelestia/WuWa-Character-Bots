// 调用统计页：/api/v1/stats/calls。
// TopN 三组（能力/会话假名/用户）HTML 条形 + 趋势 recharts 折线；24h/7d/30d 切换。
// 口径脚注：unknown_timestamp_calls（时间戳畸形不入窗）与 unattributed_calls（会话约定外不归属用户）。
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type CallsData, type StatsWindow } from '@/lib/api-client';
import { formatBucket, formatInt } from '@/lib/format';
import { cn } from '@/lib/utils';

const WINDOWS: StatsWindow[] = ['24h', '7d', '30d'];

function WindowSwitch({ value, onChange }: { value: StatsWindow; onChange: (value: StatsWindow) => void }) {
  const { t } = useTranslation();
  return (
    <div className='flex gap-1 rounded-lg border p-1'>
      {WINDOWS.map((item) => (
        <button
          key={item}
          type='button'
          onClick={() => onChange(item)}
          className={cn(
            'rounded-md px-3 py-1 fs-caption font-medium transition-colors',
            value === item ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'
          )}
        >
          {t(`calls.window.${item}`)}
        </button>
      ))}
    </div>
  );
}

function TopList({
  title,
  description,
  entries,
  labelFor,
}: {
  title: string;
  description: string;
  entries: Array<{ key: string | null; calls: number }>;
  labelFor: (key: string | null) => string;
}) {
  const max = entries.length > 0 ? Math.max(...entries.map((entry) => entry.calls)) : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle className='fs-card'>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-2'>
        {entries.length === 0 && <p className='py-6 text-center fs-caption text-muted-foreground'>—</p>}
        {entries.map((entry) => (
          <div key={entry.key ?? '(none)'} className='flex flex-col gap-1'>
            <div className='flex items-baseline justify-between gap-2 fs-caption'>
              <span className='truncate font-mono' title={labelFor(entry.key)}>
                {labelFor(entry.key)}
              </span>
              <span className='tabular-nums text-muted-foreground'>{formatInt(entry.calls)}</span>
            </div>
            <div className='h-1.5 overflow-hidden rounded-full bg-accent'>
              <div
                className='h-full rounded-full bg-primary/70'
                style={{ width: max > 0 ? `${Math.max(2, (entry.calls / max) * 100)}%` : '0%' }}
              />
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function CallsPage() {
  const { t } = useTranslation();
  const [window, setWindow] = useState<StatsWindow>('24h');
  const [bucket, setBucket] = useState<'hour' | 'day'>('hour');

  const query = useSemanticQuery<CallsData>(
    ['stats-calls', window, bucket, 'page'],
    () => controlApi.statsCalls({ window, bucket, limit: 10 }),
    { refetchInterval: 60_000 }
  );

  const data = query.state.phase === 'ok' ? query.state.data : null;

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex items-center gap-3'>
          <h1 className='fs-page'>{t('calls.title')}</h1>
          <WindowSwitch value={window} onChange={setWindow} />
          <button
            type='button'
            onClick={() => setBucket(bucket === 'hour' ? 'day' : 'hour')}
            className='rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'
          >
            {bucket === 'hour' ? t('calls.bucket.hour') : t('calls.bucket.day')}
          </button>
        </div>
        {data && (
          <div className='flex items-center gap-2 fs-caption text-muted-foreground'>
            <span className='tabular-nums'>
              {t('calls.total')} <span className='fs-card text-foreground'>{formatInt(data.total_calls)}</span>
            </span>
            {data.unknown_timestamp_calls > 0 && (
              <Badge variant='outline' title={t('calls.unknownHint')}>
                {t('calls.unknown', { count: data.unknown_timestamp_calls })}
              </Badge>
            )}
            {data.unattributed_calls > 0 && (
              <Badge variant='outline' title={t('calls.unattributedHint')}>
                {t('calls.unattributed', { count: data.unattributed_calls })}
              </Badge>
            )}
          </div>
        )}
      </div>

      {query.state.phase === 'ok' ? (
        <CallsBody data={query.state.data} />
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}

function CallsBody({ data }: { data: CallsData }) {
  const { t } = useTranslation();
  const trendItems = [...data.trend.items].reverse(); // API 时间倒序 → 展示时间正序。

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className='fs-card'>{t('calls.trend')}</CardTitle>
          <CardDescription>
            {t('calls.trendDesc', { bucket: data.trend.bucket, timezone: data.trend.timezone })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {trendItems.length === 0 ? (
            <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
          ) : (
            <div className='h-64'>
              <ResponsiveContainer width='100%' height='100%'>
                <LineChart data={trendItems} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' />
                  <XAxis
                    dataKey='bucket_start'
                    tickFormatter={(value: string) => formatBucket(value, data.trend.bucket)}
                    tick={{ fill: 'var(--muted-foreground)' }}
                    stroke='var(--muted-foreground)'
                  />
                  <YAxis tick={{ fill: 'var(--muted-foreground)' }} stroke='var(--muted-foreground)' allowDecimals={false} width={36} />
                  <Tooltip
                    contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12, }}
                    labelFormatter={(value) => formatBucket(String(value), data.trend.bucket)}
                  />
                  <Line type='monotone' dataKey='calls' stroke='var(--primary)' strokeWidth={2} dot={false} name={t('calls.total')} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className='grid gap-4 lg:grid-cols-3'>
        <TopList
          title={t('calls.byCapability')}
          description={t('calls.topN', { limit: 10 })}
          entries={data.by_capability.map((entry) => ({ key: entry.capability, calls: entry.calls }))}
          labelFor={(key) => key ?? t('calls.unknownCapability')}
        />
        <TopList
          title={t('calls.bySession')}
          description={t('calls.sessionPseudonym')}
          entries={data.by_session.map((entry) => ({ key: entry.session, calls: entry.calls }))}
          labelFor={(key) => key ?? t('calls.unknownSession')}
        />
        <TopList
          title={t('calls.byUser')}
          description={t(`calls.attribution.${data.user_attribution === 'derived_from_session_id_onebot_convention' ? 'onebot' : 'other'}`)}
          entries={data.by_user.map((entry) => ({ key: entry.user, calls: entry.calls }))}
          labelFor={(key) => key ?? '—'}
        />
      </div>
    </>
  );
}
