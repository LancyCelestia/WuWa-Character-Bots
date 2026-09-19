// Token 面板页：/api/v1/stats/tokens（账本 llm_call_records 按模型族聚合）。
// 明细四项 = input / output / cache_read / cache_creation，每项带 quality（complete/partial/unknown）
// 与 unknown_rows —— 模型未上报该 token 项的行数，如实提示不冒充全量。
// 堆叠图不直接用这四项（会双计缓存），见 toStackRows。
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type TokenBlock, type TokenFamilyRow, type TokensData } from '@/lib/api-client';
import { formatInt } from '@/lib/format';
import { DEFAULT_WINDOW, STATS_WINDOWS, windowLabel, type StatsWindowCode } from '@/lib/labels';
import { toStackRows, type TokenStackRow } from '@/lib/semantics';

// 窗口枚举/缺省/取词一律走 @/lib/labels（UNI1 fix1 迁本页：本文件的 WINDOWS 枚举手抄与
// 借 calls.window.* 表取词已退役）。文案逐字不变：迁移时点 calls.window.* 与 window.* 的
// 值双语全等（等值由 labels.test.ts 镜像锁钉死，取证见 docs/design/unify-audit-20260919/UNI1-fix1.md）。

const TOKEN_KEYS = ['input', 'output', 'cache_read', 'cache_creation'] as const;

/**
 * 堆叠段（顺序=从基线向外）：非缓存输入 + 读缓存 + 建缓存 = 输入，再加输出。
 * 配色沿用 index.css chart token（暗色自适应）：非缓存输入=品牌淡蓝（与原「输入」同色，
 * 因为它就是输入去掉缓存的余下部分）、输出=星空紫、读缓存=深蓝、建缓存=淡蓝中段。
 */
const STACK_KEYS: { key: keyof Omit<TokenStackRow, 'family'>; labelKey: string; color: string }[] = [
  { key: 'uncached', labelKey: 'tokens.uncachedInput', color: 'chart-1' },
  { key: 'cache_read', labelKey: 'tokens.cache_read', color: 'chart-3' },
  { key: 'cache_creation', labelKey: 'tokens.cache_creation', color: 'chart-4' },
  { key: 'output', labelKey: 'tokens.output', color: 'chart-2' },
];

/** 族行四项是否存在未上报行（unknown_rows>0），决定是否挂 quality 提示。 */
function qualityBadge(block: TokenBlock) {
  if (block.quality === 'complete') return null;
  if (block.quality === 'unknown') {
    return (
      <Badge variant='outline' className='font-normal text-muted-foreground'>
        {`?${block.unknown_rows}`}
      </Badge>
    );
  }
  return (
    <Badge variant='outline' className='font-normal text-tone-warn'>
      {`~${block.unknown_rows}`}
    </Badge>
  );
}

function FamilyRow({ row }: { row: TokenFamilyRow }) {
  const { t } = useTranslation();
  return (
    <div className='flex flex-col gap-2 border-b py-2 last:border-b-0'>
      <div className='flex items-baseline justify-between gap-2'>
        <span className='truncate font-mono fs-caption font-medium' title={row.family ?? t('tokens.noFamily')}>
          {row.family ?? t('tokens.noFamily')}
        </span>
        <span className='shrink-0 fs-caption tabular-nums text-muted-foreground'>{t('tokens.calls', { count: row.calls })}</span>
      </div>
      <div className='grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4'>
        {TOKEN_KEYS.map((key) => {
          const block = row.tokens[key];
          return (
            <div key={key} className='flex items-center gap-2 fs-caption'>
              <span className='text-muted-foreground'>{t(`tokens.${key}`)}</span>
              <span className='tabular-nums'>{formatInt(block.value)}</span>
              {qualityBadge(block)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TokensPage() {
  const { t } = useTranslation();
  const [window, setWindow] = useState<StatsWindowCode>(DEFAULT_WINDOW);

  const query = useSemanticQuery<TokensData>(
    ['stats-tokens', window, 'page'],
    () => controlApi.statsTokens({ window, limit: 20 }),
    { refetchInterval: 60_000 }
  );

  const data = query.state.phase === 'ok' ? query.state.data : null;

  const anyUnknown = data
    ? data.families.some((row) => TOKEN_KEYS.some((key) => row.tokens[key].quality !== 'complete'))
    : false;

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h1 className='fs-page'>{t('tokens.title')}</h1>
        <div className='flex gap-1 rounded-lg border p-1'>
          {STATS_WINDOWS.map((item) => (
            <button
              key={item}
              type='button'
              onClick={() => setWindow(item)}
              className={
                window === item
                  ? 'rounded-md bg-primary px-3 py-1 fs-caption font-medium text-primary-foreground'
                  : 'rounded-md px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'
              }
            >
              {windowLabel(t, item)}
            </button>
          ))}
        </div>
      </div>

      {query.state.phase === 'ok' ? (
        <TokensBody data={query.state.data} anyUnknown={anyUnknown} />
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}

function TokensBody({ data, anyUnknown }: { data: TokensData; anyUnknown: boolean }) {
  const { t } = useTranslation();
  // API calls 倒序 → 图表底部为最大族；堆叠段经 toStackRows 去双计。
  const stackRows = toStackRows([...data.families].reverse());
  const totals = data.totals;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className='fs-card'>{t('tokens.stackTitle')}</CardTitle>
          <CardDescription>
            {t('tokens.stackDesc')}
            {anyUnknown && ` · ${t('tokens.qualityHint')}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {stackRows.length === 0 ? (
            <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
          ) : (
            <div className='h-72'>
              <ResponsiveContainer width='100%' height='100%'>
                <BarChart data={stackRows} layout='vertical' margin={{ top: 4, right: 16, bottom: 0, left: 8 }} barSize={14}>
                  <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' horizontal={false} />
                  <XAxis
                    type='number'
                    tick={{ fill: 'var(--muted-foreground)' }}
                    stroke='var(--muted-foreground)'
                    tickFormatter={(value: number) => formatInt(value)}
                  />
                  <YAxis
                    type='category'
                    dataKey='family'
                    width={150}
                    tick={{ fill: 'var(--muted-foreground)', fontFamily: 'monospace' }}
                    stroke='var(--muted-foreground)'
                    tickFormatter={(value: string) => value ?? t('tokens.noFamily')}
                  />
                  <Tooltip
                    contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 12, }}
                    formatter={(value, name) => [formatInt(typeof value === 'number' ? value : null), String(name)] as [string, string]}
                  />
                  <Legend />
                  {STACK_KEYS.map((segment) => (
                    <Bar
                      key={segment.key}
                      dataKey={segment.key}
                      stackId='tokens'
                      name={t(segment.labelKey)}
                      fill={`var(--${segment.color})`}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className='fs-card'>{t('tokens.totals')}</CardTitle>
          <CardDescription>{t('tokens.totalsDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className='grid grid-cols-2 gap-3 sm:grid-cols-5'>
            <div>
              <div className='fs-caption text-muted-foreground'>{t('tokens.callsLabel')}</div>
              <div className='fs-num'>{formatInt(totals.calls)}</div>
            </div>
            {TOKEN_KEYS.map((key) => {
              const block = totals.tokens[key];
              return (
                <div key={key}>
                  <div className='flex items-center gap-1 fs-caption text-muted-foreground'>
                    {t(`tokens.${key}`)}
                    {qualityBadge(block)}
                  </div>
                  <div className='fs-num'>
                    {formatInt(block.value)}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className='fs-card'>{t('tokens.families')}</CardTitle>
          <CardDescription>{t('tokens.familiesDesc', { count: data.families.length })}</CardDescription>
        </CardHeader>
        <CardContent className='pt-0'>
          {data.families.length === 0 ? (
            <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
          ) : (
            data.families.map((row, index) => <FamilyRow key={row.family ?? `(none-${index})`} row={row} />)
          )}
        </CardContent>
      </Card>
    </>
  );
}

