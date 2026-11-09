import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from '@tanstack/react-router';
import { RotateCcw } from 'lucide-react';
import { ConsoleBlock, KvRow, Toggle, ValueFlash } from '@/components/console/panel';
import { openSettings } from '@/components/semantic/semantic-state';
import { Button } from '@/components/ui/button';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { cn } from '@/lib/utils';
import {
  apiRequest,
  controlApi,
  getApiToken,
  type CallsData,
  type HealthData,
  type LatencyData,
  type LogEventRow,
  type LogsPageData,
} from '@/lib/api-client';
import {
  centerApi,
  type ConfigRow,
  type MetricsOverviewData,
  type RunReceipt,
} from '@/lib/control-center';
import {
  configSummary,
  errorRate,
  healthLine,
  queueLine,
  tailErrors,
  todoRollup,
  type ConsoleTone,
} from '@/lib/console';
import { formatDateTime, formatDecimal, formatInt, formatUptime, UNKNOWN_VALUE } from '@/lib/format';
import { describeReason } from '@/lib/semantics';

/**
 * 入场错峰档位（对应 index.css 的 enter-rise-2..5；index 0 用基类零延迟）。
 * 走类名不走行内自定义属性：宪法 ⑩ 封了「自定义属性写入通道」。
 */
const ENTER_STAGGER = ['', 'enter-rise-2', 'enter-rise-3', 'enter-rise-4', 'enter-rise-5'] as const;

// 控制台总台（W12 W2-UI，用户裁定「真正的面板」）。
//
// 一屏七块：进程健康 / 消息吞吐 / 错误率 / 最近 20 条错误 / 队列积压 /
// 当前生效配置摘要 / 待办动作。每块**只有一行摘要**，细节默认折叠；三个真开关
// （实时刷新 / 全部展开 / 只看异常）都是 `role="switch"` + `aria-checked`。
// 原第八块「LLM 通道健康」已收成一行链接指向 `/console/latency`（用户裁定它不该占主位）。
//
// 数据面只用**已存在**端点（不新增契约）：e 席实测「前端调了后端没有 = 0」，本页
// 保持该结论。判定全部走 `lib/console.ts` 的纯函数（有 node --test 锁），本文件只
// 取数 + 拼文案。

/** 最近错误条数（用户裁定「最近 20 条错误」）。 */
const RECENT_ERRORS = 20;
/** 实时刷新周期；开关关掉传 undefined = 不轮询。 */
const LIVE_INTERVAL_MS = 15_000;

interface BotStatus {
  started_at: string;
  uptime_seconds: number | null;
  timezone: string;
}

export function ConsolePage() {
  const { t } = useTranslation();
  const [live, setLive] = useState(true);
  const [expandAll, setExpandAll] = useState(false);
  const [onlyIssues, setOnlyIssues] = useState(false);
  const interval = live ? LIVE_INTERVAL_MS : undefined;

  // 🔴 没令牌就**一个请求都不发**（浏览器实测抓到的真缺口）。
  // 本页 11 条查询会同时起飞；控制面失败限速是「同源 60 秒内 5 次失败 → 429」，
  // 于是未配置令牌的用户看到的是 401 风暴接 60 秒 429 锁死，而不是「去填令牌」。
  // 令牌住在 `api-client` 的模块内存里（刷新即失，刻意不落盘），所以这里用
  // 事件监听把它变成可观察状态——与 `use-semantic-query` 的刷新事件同一条通道。
  // 三槽任一在场就算「有令牌」：只填了超管令牌的用户同样要能进控制台
  // （读端点 `_v1_read_dependency` 接受超管令牌），否则会被误引去「没配令牌」。
  const hasAnyToken = () => Boolean(getApiToken('admin') || getApiToken('ro') || getApiToken('superAdmin'));
  const [hasToken, setHasToken] = useState(hasAnyToken);
  useEffect(() => {
    const sync = () => setHasToken(hasAnyToken());
    window.addEventListener('webui:credentials-changed', sync);
    return () => window.removeEventListener('webui:credentials-changed', sync);
  }, []);
  const gate = hasToken ? undefined : false;

  const health = useSemanticQuery<HealthData>(['console', 'health'], () => controlApi.health(), {
    refetchInterval: interval,
    enabled: gate,
  });
  const bot = useSemanticQuery<BotStatus>(['console', 'bot'], () => controlApi.statusBot(), {
    refetchInterval: interval,
    enabled: gate,
  });
  const calls = useSemanticQuery<CallsData>(
    ['console', 'calls'],
    () => controlApi.statsCalls({ window: '24h', bucket: 'hour', limit: 1 }),
    { refetchInterval: interval, enabled: gate }
  );
  const latency = useSemanticQuery<LatencyData>(['console', 'latency'], () => controlApi.statsLatency(), {
    refetchInterval: interval,
    enabled: gate,
  });
  const overview = useSemanticQuery<MetricsOverviewData>(
    ['console', 'overview'],
    () => centerApi.metricsOverview(),
    { refetchInterval: interval, enabled: gate }
  );
  const recent = useSemanticQuery<LogsPageData>(
    ['console', 'recent-errors'],
    () => controlApi.logs({ category: 'error', limit: RECENT_ERRORS }),
    { refetchInterval: interval, enabled: gate }
  );
  const catalog = useSemanticQuery<{ items: ConfigRow[] }>(['console', 'catalog'], () => centerApi.catalog(), {
    refetchInterval: interval,
    enabled: gate,
  });
  const commands = useSemanticQuery<{ items: RunReceipt[] }>(
    ['console', 'commands'],
    () => apiRequest<{ items: RunReceipt[] }>('/api/v1/config/commands'),
    { refetchInterval: interval, enabled: gate }
  );
  const runs = useSemanticQuery<{ items: RunReceipt[] }>(['console', 'runs'], () => centerApi.runs(), {
    refetchInterval: interval,
    enabled: gate,
  });

  // 没令牌 → 直说「去填」；令牌无效/未配置（后端判定）→ 同一句。
  const blocking = hasToken
    ? [health, calls, overview, catalog].find(
        (query) => query.state.phase === 'not_provisioned' || query.state.phase === 'auth'
      )
    : true;

  const healthData = health.state.phase === 'ok' ? health.state.data : null;
  const healthScore = healthLine(healthData?.ok, healthData?.checks);
  const botData = bot.state.phase === 'ok' ? bot.state.data : null;

  const callsData = calls.state.phase === 'ok' ? calls.state.data : null;
  const latencyData = latency.state.phase === 'ok' ? latency.state.data : null;
  const failingChannels = latencyData ? latencyData.items.filter((item) => item.consecutive_fails > 0).length : 0;
  const totalChannels = latencyData ? latencyData.items.length : 0;

  const usageData =
    overview.state.phase === 'ok' && overview.state.data.usage.status === 'ok'
      ? overview.state.data.usage.data
      : null;
  const rate = errorRate(usageData?.failed_calls, usageData?.recorded_calls);
  const measurements =
    overview.state.phase === 'ok' ? overview.state.data.resources.measurements : null;
  const queue = queueLine(measurements?.queue_depth);
  const measurementsText = (key: string) => queueLine(measurements?.[key]).text;

  const recentRows: LogEventRow[] =
    recent.state.phase === 'ok' ? tailErrors(recent.state.data.items, RECENT_ERRORS) : [];

  // 通道健康不再在本页展开：用户裁定「承诺健康改小」——完整三态区（中文渠道名 + 三态点 +
  // 「为什么是这个状态」自然语言）在 `/console/latency`，本页只留一行链接（见下方 blocks 之上）。
  // 故本页不再取 /llm/channels 与 /llm/health，也不再消费 `channelRollup`
  // （函数本身留在 `lib/console.ts`，另有消费者与 node --test）。

  const catalogData = catalog.state.phase === 'ok' ? catalog.state.data.items : [];
  const configScore = configSummary(catalogData);
  const restartKeys = catalogData.filter((row) => row.restart_required === true).map((row) => row.key);

  const commandsData = commands.state.phase === 'ok' ? commands.state.data.items : [];
  const runsData = runs.state.phase === 'ok' ? runs.state.data.items : [];
  const todoScore = todoRollup(commandsData, runsData);
  const degradedRuns = runsData.filter((run) => {
    const result = run.result;
    return (
      result !== null &&
      typeof result === 'object' &&
      (result as Record<string, unknown>).status === 'degraded'
    );
  });

  if (blocking) {
    return (
      <div className='flex w-full flex-col gap-3'>
        <h1 className='fs-page'>{t('nav.console')}</h1>
        <p className='fs-body text-muted-foreground'>{t('console.needToken')}</p>
        <div>
          <Button size='sm' variant='outline' onClick={openSettings}>
            {t('settings.open')}
          </Button>
        </div>
      </div>
    );
  }

  const throughputTone: ConsoleTone = failingChannels > 0 ? 'warn' : callsData ? 'good' : 'flat';
  const configTone: ConsoleTone =
    configScore.restartRequired > 0 ? 'warn' : configScore.total > 0 ? 'good' : 'flat';

  const blocks: Array<{ key: string; tone: ConsoleTone; node: React.ReactNode }> = [
    {
      key: 'health',
      tone: healthScore.tone,
      node: (
        <ConsoleBlock
          title={t('console.block.health')}
          summary={t('console.summary.health', { ok: healthScore.ok, total: healthScore.total })}
          tone={healthScore.tone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              {Object.entries(healthData?.checks ?? {}).map(([name, status]) => (
                <KvRow key={name} label={name} value={status === 'ok' ? t('console.ok') : status} />
              ))}
              <KvRow label={t('console.row.uptime')} value={formatUptime(botData?.uptime_seconds)} />
              <KvRow label={t('console.row.startedAt')} value={formatDateTime(botData?.started_at)} />
              <KvRow label={t('console.row.probeAt')} value={formatDateTime(healthData?.generated_at)} />
            </div>
          }
        />
      ),
    },
    {
      key: 'throughput',
      tone: throughputTone,
      node: (
        <ConsoleBlock
          title={t('console.block.throughput')}
          summary={t('console.summary.throughput', { calls: formatInt(callsData?.total_calls) })}
          tone={throughputTone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              <KvRow label={t('console.row.totalCalls')} value={formatInt(callsData?.total_calls)} />
              <KvRow label={t('console.row.activeUsers')} value={formatInt(callsData?.active_users)} />
              <KvRow label={t('console.row.lastMessage')} value={formatDateTime(callsData?.last_message_at)} />
              <KvRow label={t('console.row.failingChannels')} value={formatInt(failingChannels)} />
              <KvRow
                label={t('console.row.unknownTimestamp')}
                value={formatInt(callsData?.unknown_timestamp_calls)}
              />
            </div>
          }
        />
      ),
    },
    {
      key: 'errors',
      tone: rate.tone,
      node: (
        <ConsoleBlock
          title={t('console.block.errorRate')}
          summary={
            rate.ratio === null
              ? t('console.summary.errorRateUnknown')
              : t('console.summary.errorRate', { percent: formatDecimal(rate.ratio * 100, 1) })
          }
          tone={rate.tone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              <KvRow label={t('console.row.recordedCalls')} value={formatInt(usageData?.recorded_calls)} />
              <KvRow label={t('console.row.failedCalls')} value={formatInt(usageData?.failed_calls)} />
              <KvRow label={t('console.row.unknownStatus')} value={formatInt(usageData?.unknown_status_calls)} />
              <p className='pt-2 fs-caption text-muted-foreground'>{t('console.footnote.errorRate')}</p>
            </div>
          }
        />
      ),
    },
    {
      key: 'recent',
      tone: recentRows.length > 0 ? 'bad' : 'good',
      node: (
        <ConsoleBlock
          title={t('console.block.recentErrors')}
          summary={t('console.summary.recentErrors', { count: recentRows.length })}
          tone={recentRows.length > 0 ? 'bad' : 'good'}
          forceOpen={expandAll ? true : undefined}
          detail={
            recentRows.length === 0 ? (
              <p className='fs-caption text-muted-foreground'>{t('console.empty.recentErrors')}</p>
            ) : (
              <ul className='flex flex-col gap-2'>
                {recentRows
                  .slice()
                  .reverse()
                  .map((row) => (
                    <li key={row.event_id} className='console-slide-in rounded-md border px-3 py-2'>
                      <div className='flex flex-wrap items-center gap-2'>
                        <span className='rounded-full bg-destructive/15 px-2 py-1 fs-caption text-destructive'>
                          {row.category}
                        </span>
                        <span className='fs-caption text-muted-foreground'>{row.source}</span>
                        <span className='ml-auto fs-caption tabular-nums text-muted-foreground'>
                          {formatDateTime(row.created_at)}
                        </span>
                      </div>
                      <p className='mt-1 break-words fs-body'>{row.message}</p>
                      <p className='break-words fs-caption text-muted-foreground'>{row.event_id}</p>
                    </li>
                  ))}
              </ul>
            )
          }
        />
      ),
    },
    {
      key: 'queue',
      tone: queue.tone,
      node: (
        <ConsoleBlock
          title={t('console.block.queue')}
          summary={t('console.summary.queue', { value: queue.text })}
          tone={queue.tone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              <KvRow label='queue_depth' value={queue.text} />
              <KvRow label={t('console.row.taskCount')} value={measurementsText('task_count')} />
              <KvRow label={t('console.row.llmConcurrency')} value={measurementsText('llm_concurrency')} />
              <p className='pt-2 fs-caption text-muted-foreground'>{t('console.footnote.queue')}</p>
            </div>
          }
        />
      ),
    },
    {
      key: 'config',
      tone: configTone,
      node: (
        <ConsoleBlock
          title={t('console.block.config')}
          summary={t('console.summary.config', {
            total: configScore.total,
            writable: configScore.writable,
            restart: configScore.restartRequired,
          })}
          tone={configTone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              <KvRow label={t('console.row.configTotal')} value={formatInt(configScore.total)} />
              <KvRow label={t('console.row.configWritable')} value={formatInt(configScore.writable)} />
              <KvRow label={t('console.row.configSensitive')} value={formatInt(configScore.sensitive)} />
              {restartKeys.length > 0 && (
                <div className='pt-2'>
                  <p className='fs-caption text-muted-foreground'>{t('console.row.restartKeys')}</p>
                  <p className='break-words font-mono fs-caption'>{restartKeys.slice(0, 12).join(' · ')}</p>
                </div>
              )}
            </div>
          }
        />
      ),
    },
    {
      key: 'todos',
      tone: todoScore.tone,
      node: (
        <ConsoleBlock
          title={t('console.block.todos')}
          summary={t('console.summary.todos', {
            consent: todoScore.consent,
            failed: todoScore.failed,
            total: todoScore.total,
          })}
          tone={todoScore.tone}
          forceOpen={expandAll ? true : undefined}
          detail={
            <div className='flex flex-col'>
              <KvRow label={t('console.row.consent')} value={formatInt(todoScore.consent)} />
              <KvRow label={t('console.row.pending')} value={formatInt(todoScore.pending)} />
              <KvRow label={t('console.row.conflict')} value={formatInt(todoScore.conflict)} />
              <KvRow label={t('console.row.failed')} value={formatInt(todoScore.failed)} />
              <KvRow label={t('console.row.running')} value={formatInt(todoScore.running)} />
              <KvRow label={t('console.row.degradedActions')} value={formatInt(todoScore.degraded)} />
              {degradedRuns.length > 0 && (
                <div className='pt-2'>
                  {degradedRuns.slice(0, 5).map((run, index) => (
                    <p key={run.run_id ?? index} className='break-words fs-caption text-muted-foreground'>
                      {run.run_id ?? UNKNOWN_VALUE} · {describeReason('not_connected', t)}
                    </p>
                  ))}
                </div>
              )}
              <p className='pt-2 fs-caption text-muted-foreground'>{t('console.footnote.todos')}</p>
            </div>
          }
        />
      ),
    },
  ];

  const visible = onlyIssues ? blocks.filter((block) => block.tone !== 'good') : blocks;
  const worst = blocks.reduce<ConsoleTone>(
    (acc, block) => (rankTone(block.tone) > rankTone(acc) ? block.tone : acc),
    'good'
  );

  const refreshAll = () => {
    void Promise.all([
      health.refetch(),
      bot.refetch(),
      calls.refetch(),
      latency.refetch(),
      overview.refetch(),
      recent.refetch(),
      catalog.refetch(),
      commands.refetch(),
      runs.refetch(),
    ]);
  };

  return (
    <div className='flex w-full flex-col gap-4'>
      {/* 页首：标题 + 全局最坏档（一行状态）+ 三个开关 + 刷新。 */}
      <header className='flex flex-wrap items-center gap-3'>
        <div className='flex min-w-0 items-center gap-2'>
          <span aria-hidden className='h-5 w-1 shrink-0 rounded-full bg-primary' />
          <h1 className='fs-page'>{t('nav.console')}</h1>
        </div>
        <ValueFlash text={t(`console.worst.${worst}`)} tone={worst} />
        <div className='ml-auto flex flex-wrap items-center gap-2'>
          <Toggle label={t('console.toggle.live')} checked={live} onChange={setLive} />
          <Toggle label={t('console.toggle.expandAll')} checked={expandAll} onChange={setExpandAll} />
          <Toggle label={t('console.toggle.onlyIssues')} checked={onlyIssues} onChange={setOnlyIssues} />
          <Button variant='outline' size='sm' onClick={refreshAll} aria-label={t('console.refresh')}>
            <RotateCcw className='size-4' />
            {t('console.refresh')}
          </Button>
        </div>
      </header>

      {/* 通道健康：本页只留一行链接。完整三态区（中文渠道名 + 三态点 + 为什么是这个状态）
          在延迟页——用户裁定它不该占总台主位（原话「承诺健康」＝「通道健康」的语音误读）。 */}
      <p className='fs-caption text-muted-foreground'>
        通道健康 {formatInt(failingChannels)} / {formatInt(totalChannels)} 个渠道存在连败 · 详情见
        <Link to='/latency' className='ml-1 text-primary hover:underline'>延迟页</Link>
      </p>

      {/* 自动流双列。⚠ 窄行块（一行摘要）与当前窄列不配：摘要一长就换行把块撑到 2–3 行高，
          同一行的邻块被拉齐后留下大块空白（浏览器实测：摘要 8 块里 7 块换行，右列空出半屏）。
          max-h-14 + overflow-hidden 把摘要压成单行（完整文本仍在 DOM，靠 title 取全文），
          行高重新对齐；最近错误是列表型内容，照旧占整行。 */}
      <div className='grid grid-cols-1 gap-3 lg:grid-cols-2'>
        {visible.length === 0 ? (
          <p className='surface rounded-lg p-4 fs-body text-muted-foreground lg:col-span-2'>
            {t('console.empty.allGood')}
          </p>
        ) : (
          visible.map((block, index) => (
            <div
              key={block.key}
              className={cn(
                'enter-rise min-w-0',
                block.key === 'recent' && 'lg:col-span-2',
                // 错峰延迟走固定档类名（行内自定义属性被宪法 ⑩ 封死，见 index.css）。
                ENTER_STAGGER[index % ENTER_STAGGER.length]
              )}
            >
              {block.node}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/** 档位排序（只看异常过滤 + 全局最坏档用）；数字越大越坏。 */
function rankTone(tone: ConsoleTone): number {
  if (tone === 'bad') return 3;
  if (tone === 'warn') return 2;
  if (tone === 'flat') return 1;
  return 0;
}
