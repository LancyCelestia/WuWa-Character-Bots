import { useTranslation } from 'react-i18next';
import { Activity, Bot, Coins, Gauge, Inbox, Radio, ShieldCheck } from 'lucide-react';
import { BarChart, DonutChart, LineChart } from '@/components/charts';
import { Reveal } from '@/components/effects/reveal';
import { formatTimeLabel, trendByUserSeries, trendCoverageGap, trendPoints } from '@/lib/chart-model';
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
import { SemanticState, openSettings } from '@/components/semantic/semantic-state';
import { useSemanticQuery, type DataState } from '@/hooks/use-semantic-query';
import { shouldShowSkeleton } from '@/lib/data-state';
import { controlApi, type AffinityBoardData, type CallsData, type HealthData, type BotStatusData, type LatencyData, type TokensData } from '@/lib/api-client';
import { centerApi, type MetricsOverviewData } from '@/lib/control-center';
import { fieldDoc, fieldRow } from '@/lib/field-dict';
import { DEFAULT_WINDOW, windowLabel, type StatsWindowCode, type Translate } from '@/lib/labels';
import { formatCount, formatDateTime, formatDecimal, formatInt, formatNumber, formatRate, formatUptime } from '@/lib/format';
import { describeReason } from '@/lib/semantics';

// 总览页（Phase A 真数据）：全部由现有只读端点拼装——
// /admin/api/v1/health + /status/bot + /api/v1/stats/calls|tokens|latency。
// 发送队列/活动告警 Phase A 无只读端点 → 诚实标「未接入」，不造数。
// BACKEND3 消费（2026-09-18 FE3，§7 A4/A5）：「消息调用键值明细」卡——近 24 小时/近 7 天
// 两个**滚动**窗口各取一次 stats/calls（跨窗不合并、不造全表 max），取 total_calls +
// active_users + last_message_at 做 label 左/value 右键值行（DataGrid 分隔线）；
// 字段缺省（旧控制面）如实显示 UNKNOWN_VALUE，窗口无记录 last_message_at=null → 同（不造时间）。

/**
 * 明细卡的两档**滚动**窗（枚举与标签键的真相源在 `@/lib/labels`）：取数参数与卡标题
 * 各引同一变量，标签绝不与取数窗口脱钩；queryKey 用的也是这两个值（值不变，缓存键不变）。
 */
const DETAIL_WINDOW_24H: StatsWindowCode = DEFAULT_WINDOW;
const DETAIL_WINDOW_7D: StatsWindowCode = '7d';

function withFallback(state: DataState<unknown>, node: React.ReactNode): React.ReactNode {
  return state.phase === 'ok' ? node : <SemanticState state={state} />;
}

/** 非 ok 语义态 → 一行人话（known reason 走 i18n，未知码/错误消息原样，绝不编语义）。 */
function fallbackLine(state: DataState<CallsData>, t: Translate): string {
  if (state.phase === 'unavailable') return `${t('state.noData')}：${describeReason(state.reason, t)}`;
  if (state.phase === 'error') return `${t('state.loadFailed')}：${state.message}`;
  return t('state.noData');
}

/** 未采集字段在值位置的显式标注——与 `components/console/field-table.tsx` 同一句口径。 */
const ABSENT_TEXT = '尚未采集';

/**
 * 挂数据字典的统计卡（`lib/field-dict.ts` 是唯一真身，本组件不写指标名）。
 *
 * 四列里的名字/简介/说明全部取 `fieldRow()`：`label` 上主位、`summary` 做副题、
 * 卡片下方一行 `fs-caption` 承载键名与说明，`detail` 挂 `title`（悬停读全文）。
 *
 * 🔴 `availability === 'absent'` 时值位置**恒为「尚未采集」**，调用方传进来的值一律不吃：
 * 「库里没有」与「值是 0」是两件事，把前者画成 0 或 — 就是编数据。这道闸是硬判定，
 * 不靠调用方自觉（同 `field-table.tsx` 的 `ValueCell`）。
 */
function DictStatCard({
  icon,
  fieldKey,
  value,
  sub,
  action,
  children,
}: {
  icon?: React.ReactNode;
  fieldKey: string;
  /** 值位置的实际读数；absent 字段下**不会被读取**。 */
  value?: React.ReactNode;
  /** 额外脚注（如时间窗、口径补充）；字典 `summary` 恒排在最前。 */
  sub?: string;
  action?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const row = fieldRow(fieldKey);
  const doc = fieldDoc(fieldKey);
  const absent = doc?.availability === 'absent';
  const shown = absent ? (
    <span className='fs-body text-tone-warn'>{ABSENT_TEXT}</span>
  ) : (
    value
  );
  return (
    <SectionCard
      title={row?.label ?? fieldKey}
      action={action}
      titleClass='text-muted-foreground'
      description={row?.summary}
    >
      <div className='flex flex-col gap-1'>
        <div className='flex items-end gap-2'>
          {icon && (
            <span
              aria-hidden
              className='mb-1 flex size-10 shrink-0 items-center justify-center rounded-full bg-muted/60 ring-1 ring-hairline [&_svg]:size-4'
            >
              {icon}
            </span>
          )}
          <span className='fs-num num-iris'>{shown}</span>
        </div>
        {sub && <p className='fs-caption text-muted-foreground'>{sub}</p>}
        {/* 键名 + 说明：说明折进 title，键名始终可见（它就是字典键，排查与对表用）。 */}
        <p className='truncate fs-caption text-muted-foreground' title={row?.detail}>
          {row?.key ?? fieldKey}
        </p>
      </div>
      {children}
    </SectionCard>
  );
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

/** 单窗口键值组：ok → 三行键值；loading → 骨架；其余（含 disabled）→ 一行人话（不炸整卡）。 */
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
            value={formatInt(data.active_users)}
          />
          <KvRow
            label={t('dashboard.overview.rowLastMessage')}
            value={formatDateTime(data.last_message_at)}
          />
        </DataGrid>
      ) : shouldShowSkeleton(state.phase) ? (
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

/**
 * 趋势卡：**每桶增量**的波形（不是累计），升序桶、空桶补 0 由后端保证。
 *
 * 后端 `trend_by_user` 存在 → 按人分多线（TopN + 「其他」，图例顺序＝top_users 顺序）；
 * 不存在（旧控制面）→ 只画总计，并在图上**明说**没有按用户分桶——不许假装有。
 * 横轴刻度由 LineChart 的 niceTickIndexes 挑，首末桶必出，因此能读出「几点到几点」。
 */
function CallsTrendChart({ data }: { data: CallsData }) {
  const { times, values } = trendPoints(data.trend);
  const labels = times.map((stamp) => formatTimeLabel(stamp, data.trend.bucket));
  const perUser = trendByUserSeries(data.trend_by_user, times);
  const notes: string[] = [];
  // 先说实话：轴铺满 25 格≠数据够。审计库按行数剪枝，生产实测只剩 2 个桶、48 分钟——
  // 不把这句放在最前面，一张「2 个点 + 23 个零」的图会被读成完整的一天。
  const gap = trendCoverageGap(data.coverage);
  if (gap.incomplete) {
    const covered = data.coverage?.available_buckets ?? 0;
    const buckets = data.coverage?.requested_buckets ?? times.length;
    notes.push(
      gap.minutes !== null
        ? `历史数据不足（当前仅覆盖 ${gap.minutes} 分钟，${covered}/${buckets} 个时段有调用）`
        : `历史数据不足（只有 ${covered}/${buckets} 个时段有调用）`
    );
  }
  if (data.trend_by_user) {
    if (perUser.length === 0) {
      notes.push('窗口内没有可归属到用户的调用，未画按人分线');
    }
  } else if (data.trend_by_user_reason === 'insufficient_attribution') {
    // 后端明确说了原因：不是"没这个能力"，是"多数调用归不到人"。别把原因说错。
    notes.push('本窗口多数调用的会话标识不合约定、归不到具体用户，未画按人分线');
  } else {
    notes.push('当前数据源只提供总计，未提供按用户分桶');
  }
  if (data.trend.truncated_buckets) {
    notes.push(`横轴已裁掉最早的 ${formatInt(data.trend.truncated_buckets)} 个桶（超出显示上限）`);
  }
  return (
    <>
      <LineChart
        label='近 24 小时调用量趋势（每个桶的增量）'
        aspect={1.2}
        area={perUser.length === 0}
        labels={labels}
        series={perUser.length > 0 ? perUser : [{ key: 'calls', label: '调用次数', values }]}
      />
      {notes.map((note) => (
        <p key={note} className='mt-2 fs-caption text-muted-foreground'>
          {note}
        </p>
      ))}
    </>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();

  const health = useSemanticQuery<HealthData>(['health'], () => controlApi.health(), { refetchInterval: 30_000 });
  const botStatus = useSemanticQuery<BotStatusData>(['status-bot'], () => controlApi.statusBot(), { refetchInterval: 30_000 });
  // limit=10：TopN 三组都画成图，不再只取 5 条。
  const calls = useSemanticQuery<CallsData>(['stats-calls', DETAIL_WINDOW_24H, 'overview'], () => controlApi.statsCalls({ window: DETAIL_WINDOW_24H, bucket: 'hour', limit: 10 }), { refetchInterval: 60_000 });
  // §7 A4/A5：近 7 天窗口独立取数（与 24h 各一次，不跨窗合并）；limit=1 最小化趋势/TopN 载荷。
  const calls7d = useSemanticQuery<CallsData>(['stats-calls', DETAIL_WINDOW_7D, 'overview'], () => controlApi.statsCalls({ window: DETAIL_WINDOW_7D, bucket: 'day', limit: 1 }), { refetchInterval: 60_000 });
  const tokens = useSemanticQuery<TokensData>(['stats-tokens', DEFAULT_WINDOW, 'overview'], () => controlApi.statsTokens({ window: DEFAULT_WINDOW, limit: 5 }), { refetchInterval: 60_000 });
  const latency = useSemanticQuery<LatencyData>(['stats-latency', 'overview'], () => controlApi.statsLatency(), { refetchInterval: 60_000 });
  // 字典卡新增的两条读数（都是**已存在**的只读端点，不新增契约）：
  //   - 累计总好感度取好感度榜 `total`（后端已对 user_affinity.affinity 求和，前端不重算）；
  //   - 成功率取 metrics/overview 的账本聚合（successful_calls ÷ recorded_calls）。
  const affinity = useSemanticQuery<AffinityBoardData>(['affinity', 'overview'], () => controlApi.affinityBoard({ limit: 1 }), { refetchInterval: 60_000 });
  const overview = useSemanticQuery<MetricsOverviewData>(['overview', 'dashboard'], () => centerApi.metricsOverview(), { refetchInterval: 60_000 });

  const queries = [health, botStatus, calls, calls7d, tokens, latency, affinity, overview];
  // 页面级阻断三态：未配置令牌 / 令牌无效 / 被限速。三者都是「整页都取不到数」，
  // 各卡再画一遍只会变成六份同样的提示。`rate_limited` 尤其必须在这里拦下：
  // 它是全局的（控制面按来源计数），不是某一张卡的数据坏了。
  const blocking = queries.find(
    (query) =>
      query.state.phase === 'not_provisioned' ||
      query.state.phase === 'auth' ||
      query.state.phase === 'rate_limited'
  );
  if (blocking) {
    return (
      <div className='flex w-full flex-col gap-4'>
        <PageHeader title={t('nav.overview')} />
        <SemanticState state={blocking.state} onRetry={blocking.refetch} />
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

  // 字典卡读数（null＝这条链路这次没取到，卡内如实走 fallback，不补 0）。
  const affinityData = affinity.state.phase === 'ok' ? affinity.state.data : null;
  const overviewData = overview.state.phase === 'ok' ? overview.state.data : null;
  const usageData = overviewData?.usage.status === 'ok' ? overviewData.usage.data : null;
  // 成功率分母为 0／未知 ⇒ null（不把 0/0 说成 0%）；口径写在字典 `request_success_rate.detail`。
  const successRate =
    usageData && usageData.recorded_calls > 0
      ? usageData.successful_calls / usageData.recorded_calls
      : null;

  return (
    <div className='flex w-full flex-col gap-4'>
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

        <DictStatCard
          fieldKey='active_users'
          value={callsData ? formatNumber(callsData.active_users) : undefined}
          sub={
            callsData
              ? `${t('dashboard.overview.callsFootnote', {
                  unknown: formatInt(callsData.unknown_timestamp_calls),
                  unattributed: formatInt(callsData.unattributed_calls),
                })} · ${formatRate(callsData.total_calls / 24, '次', '小时')}`
              : undefined
          }
        >
          {withFallback(calls.state, null)}
        </DictStatCard>

        <DictStatCard
          icon={<ShieldCheck className='size-4 text-tone-good' />}
          fieldKey='request_success_rate'
          value={successRate !== null ? `${formatDecimal(successRate * 100, 1)} %` : undefined}
          sub={
            usageData
              ? `成功 ${formatInt(usageData.successful_calls)} / 记录 ${formatInt(usageData.recorded_calls)} 次调用`
              : undefined
          }
        >
          {withFallback(overview.state, null)}
        </DictStatCard>

        <DictStatCard
          icon={<Coins className='size-4 text-tone-purple' />}
          fieldKey='total_cost'
          value={undefined}
          sub='总览现有端点未投影费用字段；累计费用见「调用」页账本口径'
        >
          {withFallback(overview.state, null)}
        </DictStatCard>

        <DictStatCard
          icon={<Gauge className='size-4 text-tone-info' />}
          fieldKey='affinity_total'
          value={affinityData ? formatDecimal(affinityData.total, 3) : undefined}
          sub={affinityData ? `好感度库 ${formatInt(affinityData.items.length)} 条在册记录之和` : undefined}
        >
          {withFallback(affinity.state, null)}
        </DictStatCard>

        <StatCard
          icon={<Coins className='size-4 text-tone-purple' />}
          label={t('dashboard.overview.llm24h')}
          value={tokensData ? formatNumber(tokensData.totals?.calls) : undefined}
          sub={
            tokensData
              ? `${t('tokens.input')} ${formatCount(tokensData.totals?.tokens.input.value)} · ${t('tokens.output')} ${formatCount(tokensData.totals?.tokens.output.value)}`
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

      {/* ── 可视化区（UI3）：趋势折线 / 环形成功率 / 模型家族柱状 / TopN 条形 ──────
          全部走 `@/components/charts` 的**手写 SVG**（零第三方依赖，整目录 ~16 KB gzip），
          不进图表库——总览是首屏页，recharts 那 344 KB 只留给 /calls 与 /tokens 的详情图。
          数据仍只来自既有只读端点；缺数据时组件自己出「暂无数据」，不造数。 */}
      {/* 等高：三张图 aspect 各 1.2/1/2.2，items-start 会让同行卡片高度差 170–200px；
          stretch 把三张卡拉到同一行高，图在自己的卡里居中留白。 */}
      {/* 首屏之下的两块网格才挂揭示（W17）：首屏卡片挂载时就在视口内，
          useReveal 会直接给终态，包上去只是白加 DOM。step 递进让三张图先后浮起。 */}
      <Reveal as='section' step={1} className='grid items-stretch gap-4 xl:grid-cols-3'>
        <SectionCard
          title={t('dashboard.overview.calls24h')}
          description='按小时聚合的调用量，近 24 小时'
          titleClass='text-muted-foreground'
        >
          {callsData && callsData.trend.items.length > 1 ? (
            <CallsTrendChart data={callsData} />
          ) : (
            <SemanticState state={calls.state} onRetry={calls.refetch} />
          )}
        </SectionCard>

        <SectionCard title='通道健康' description='健康采样的通道比例；分母未知时如实标「不可判」' titleClass='text-muted-foreground'>
          {latencyData && totalChannels > 0 ? (
            <DonutChart
              label='健康通道占比'
              entries={[
                { label: '健康', value: totalChannels - failingChannels },
                { label: '异常', value: failingChannels },
              ]}
              centerValue={`${totalChannels - failingChannels}/${totalChannels}`}
              centerLabel='健康通道'
            />
          ) : (
            <SemanticState state={latency.state} onRetry={latency.refetch} />
          )}
        </SectionCard>

        <SectionCard
          title='LLM 调用结构'
          description='近 24 小时按模型家族的调用次数'
          titleClass='text-muted-foreground'
        >
          {tokensData && tokensData.families.length > 0 ? (
            <BarChart
              label='各模型家族的调用次数'
              categories={tokensData.families.slice(0, 5).map((family) => family.family ?? '未知')}
              series={[
                {
                  key: 'calls',
                  label: '调用次数',
                  values: tokensData.families.slice(0, 5).map((family) => family.calls),
                },
              ]}
              stacked={false}
              aspect={2.2}
            />
          ) : (
            <p className='fs-caption text-muted-foreground'>账本未接入或窗口内没有调用。</p>
          )}
        </SectionCard>
      </Reveal>

      <div className='grid gap-4 xl:grid-cols-2'>
        <SectionCard title='调用 TopN · 能力' description='近 24 小时调用最多的能力' titleClass='text-muted-foreground'>
          {callsData && callsData.by_capability.length > 0 ? (
            <BarChart
              label='按能力分布（横向条形）'
              horizontal
              categories={callsData.by_capability.slice(0, 8).map((row) => row.capability ?? '未标注')}
              series={[
                {
                  key: 'calls',
                  label: '调用次数',
                  values: callsData.by_capability.slice(0, 8).map((row) => row.calls),
                },
              ]}
              stacked={false}
              aspect={2.6}
            />
          ) : (
            <p className='fs-caption text-muted-foreground'>窗口内没有可归属的调用。</p>
          )}
        </SectionCard>

        <SectionCard title='调用 TopN · 会话' description='按会话假名聚合（不还原真人身份）' titleClass='text-muted-foreground'>
          {callsData && callsData.by_session.length > 0 ? (
            <BarChart
              label='按会话分布（横向条形）'
              horizontal
              categories={callsData.by_session.slice(0, 8).map((row) => row.session ?? '未知会话')}
              series={[
                {
                  key: 'calls',
                  label: '调用次数',
                  values: callsData.by_session.slice(0, 8).map((row) => row.calls),
                },
              ]}
              stacked={false}
              aspect={2.6}
            />
          ) : (
            <p className='fs-caption text-muted-foreground'>窗口内没有可归属的会话。</p>
          )}
        </SectionCard>
      </div>

      <SectionCard
        title={t('dashboard.overview.callsDetailTitle')}
        description={t('dashboard.overview.callsDetailDesc')}
      >
        <div className='flex flex-col gap-6'>
          <CallsDetailGroup label={windowLabel(t, DETAIL_WINDOW_24H)} state={calls.state} data={callsData} />
          <CallsDetailGroup label={windowLabel(t, DETAIL_WINDOW_7D)} state={calls7d.state} data={calls7dData} />
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
