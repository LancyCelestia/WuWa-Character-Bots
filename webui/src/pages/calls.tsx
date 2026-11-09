// 调用统计页：/api/v1/stats/calls。
// 四块：① 本页口径说明（回答「为什么这里看不到渠道」）② KPI 四卡（用户数与调用数分开）
// ③ 趋势 recharts 折线（含轴覆盖度告警）④ 三组 TopN（能力/会话/用户，人话标签，原值降级 title）
// ⑤ 最近调用明细（身份链六列）。
//
// 🔴 数据源真相（实测，改页面前先读这段）：
//   `/api/v1/stats/calls` 的后端是 `control_plane/webui_stats.py` 的 `AuditCallStatsService`，
//   SQL 从 **`audit_records`** 聚合。该表 14 列里**没有** channel / model / provider / cost /
//   token 任何一列，且受 `BOT_AUDIT_MAX_ITEMS`（默认 1000）硬顶——实测只覆盖约 52 分钟。
//   中文实名的 `gateway_channel` 列确实存在于**计费账本 `llm_call_records`**，但 `control_plane/`
//   下没有任何 SQL 或路由读它（`_GROUP_EXPRESSIONS` 只按 actual_model / provider_id / session_id
//   分组）→ **本页拿不到渠道名，硬造就是谎报**。渠道名去「延迟」页，模型族去「Token」页。
//
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
import { SectionCard, StatCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type CallsData, type CallsIdentitySession } from '@/lib/api-client';
import {
  bucketLabel,
  DEFAULT_BUCKET,
  DEFAULT_WINDOW,
  nextBucket,
  STATS_WINDOWS,
  windowLabel,
  type BucketCode,
  type StatsWindowCode,
} from '@/lib/labels';
import { formatBucket, formatCount, formatIsoDateTime, formatIsoTimestamp, formatNumber, UNKNOWN_VALUE } from '@/lib/format';
import { parseSession } from '@/lib/stat-rollup';
import { sessionKindLabel } from '@/lib/session-identity';
import { cn } from '@/lib/utils';

// 窗口枚举/标签键一律取 @/lib/labels（收口前三份 WINDOWS 手抄 + 四份标签真值表）。

// ───────────────────────── 能力 ID 中文化（就地词表，不进 lib/） ─────────────────────────
// `domain-labels.ts` 只覆盖动作 ID（`action.reconnect` 那种）与 LLM 渠道/模型，**没有能力词表**；
// 本页 by_capability 的 key 是 `bot.content` / `bot.chat` 这类**能力 ID**，直接上屏就是英文变量名。
// 词表收在本文件内（简报边界：不改 lib/）。键＝审计库 `audit_records.capability_id` 实测分布。
// ponytail: 只收了实测见过的两项 + 兄弟能力同族推名；后端新增能力会落到「未登记能力：xxx」
//           兜底（中文开头、可检索），届时把该 id 补进本表即可，不需要动别处。
const CAPABILITY_LABELS: Record<string, string> = {
  'bot.chat': '对话回复',
  'bot.content': '内容审核',
  'bot.content.safety': '内容安全',
  'bot.memory': '记忆检索',
  'bot.affinity': '好感度',
  'bot.schedule': '日程提醒',
  'bot.media': '媒体处理',
  'bot.render': '卡片渲染',
  'bot.tools': '工具调用',
  'bot.system': '系统内务',
};

/** 能力 ID → 中文名。未登记走 `未登记能力：<原值>` 兜底（**中文开头**，原值可检索）。 */
function capabilityLabel(raw: string | null | undefined): string {
  const id = (raw ?? '').trim();
  if (!id) return '能力未标注';
  return CAPABILITY_LABELS[id] ?? `未登记能力：${id}`;
}

// ───────────────────────── 会话 / 用户 ID 中文化 ─────────────────────────
// 形态真身＝后端 OneBot v11 约定（`webui_stats.py` 的 `_session_kind` / `_user_from_session`）：
//   纯数字        → 私聊用户
//   group_<gid>_<uid> → 群会话
//   其余（runtime / admin:onebot / email:noreply…）→ 不可归属到人
// 判定一律走 `lib/stat-rollup.ts` 的 `parseSession()`（唯一真值，不在此重写正则）。
function sessionLabel(raw: string | null | undefined): string {
  const owner = parseSession(raw);
  if (owner.kind === 'user') return `用户 ${owner.id}`;
  if (owner.kind === 'group') return `群 ${owner.groupId} 的用户 ${owner.userId}`;
  return '未登记会话';
}

/** 用户 ID → 人话。空值不说「用户 」而是「未登记用户」。 */
function userLabel(raw: string | null | undefined): string {
  const id = (raw ?? '').trim();
  return id ? `用户 ${id}` : '未登记用户';
}

/** 平台串 → 中文/统一写法（口径同 `lib/session-identity.ts`：认不出原样回显，不谎称未采集）。 */
function platformOf(raw: string | null | undefined): string {
  const text = (raw ?? '').trim();
  if (!text) return '平台未采集';
  const head = text.toLowerCase().split('.')[0] ?? text.toLowerCase();
  if (head === 'qq' || head === 'onebot' || head === 'nonebot') return 'QQ';
  if (head === 'telegram' || head === 'tg') return 'Telegram';
  return text;
}

/** 明细表六列表头（顺序即列序，与线下列格一一对应）。 */
const DETAIL_COLUMNS = ['平台', '会话类型', '群 / 频道', '用户', '调用次数', '最后活动'] as const;

/** 明细表网格（4 条 `A5` 式 minmax 轨道 + 两个定宽数字/时间列；手机端单列堆叠）。 */
const DETAIL_GRID = 'grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto]';

function WindowSwitch({ value, onChange }: { value: StatsWindowCode; onChange: (value: StatsWindowCode) => void }) {
  const { t } = useTranslation();
  return (
    <div className='flex gap-1 rounded-lg border p-1'>
      {STATS_WINDOWS.map((item) => (
        <button
          key={item}
          type='button'
          onClick={() => onChange(item)}
          className={cn(
            'rounded-md px-3 py-1 fs-caption font-medium transition-colors',
            value === item ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'
          )}
        >
          {windowLabel(t, item)}
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
        {/* 空列表在此显「未知符号」而非「暂无数据」= 已登记的语义混用（UNI1 台账 §四-2）：
            改文案属用户可见变更，本席不改，只把符号收进单一真值 UNKNOWN_VALUE。 */}
        {entries.length === 0 && <p className='py-6 text-center fs-caption text-muted-foreground'>{UNKNOWN_VALUE}</p>}
        {entries.map((entry) => (
          <div key={entry.key ?? '(none)'} className='flex flex-col gap-1'>
            <div className='flex items-baseline justify-between gap-2 fs-caption'>
              {/* 人话标签上屏；**原始 ID 一律降级到 title**（排查/对账还要用它，不许丢）。 */}
              <span className='truncate' title={entry.key ?? labelFor(entry.key)}>
                {labelFor(entry.key)}
              </span>
              <span className='tabular-nums text-muted-foreground'>{formatCount(entry.calls)}</span>
            </div>
            <div className='h-1 flex overflow-hidden rounded-full bg-accent'>
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
  const [window, setWindow] = useState<StatsWindowCode>(DEFAULT_WINDOW);
  const [bucket, setBucket] = useState<BucketCode>(DEFAULT_BUCKET);

  const query = useSemanticQuery<CallsData>(
    ['stats-calls', window, bucket, 'page'],
    () => controlApi.statsCalls({ window, bucket, limit: 10 }),
    { refetchInterval: 60_000 }
  );

  const data = query.state.phase === 'ok' ? query.state.data : null;

  return (
    <div className='flex w-full flex-col gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex items-center gap-3'>
          <h1 className='fs-page'>{t('calls.title')}</h1>
          <WindowSwitch value={window} onChange={setWindow} />
          <button
            type='button'
            onClick={() => setBucket(nextBucket(bucket))}
            className='rounded-md border px-3 py-1 fs-caption font-medium text-muted-foreground hover:bg-accent'
          >
            {bucketLabel(t, bucket)}
          </button>
        </div>
        {data && (
          <div className='flex items-center gap-2 fs-caption text-muted-foreground'>
            <span className='tabular-nums'>
              {t('calls.total')} <span className='fs-card text-foreground'>{formatNumber(data.total_calls)}</span>
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

      {/* ① 本页口径：用户「为什么这里看不到渠道」的**根源级回答**，不是装饰。 */}
      <p className='fs-caption text-muted-foreground'>
        本页数据来自审计库 `audit_records`（保留最近 1000 条，实测仅覆盖约 52 分钟）。该表不含渠道、模型、Token、费用字段——那些数据在计费账本
        `llm_call_records` 里，经「Token」页与「模型」页查看。要看真实渠道名请到「延迟」页（那里的渠道名已中文化）。
      </p>

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
  // 后端已改时间升序（且窗口内空桶补 0）：这里**不许再 reverse**，否则整体左右颠倒。
  const trendItems = data.trend.items;
  // 轴覆盖度：只在后端给了 coverage 且确有缺口时才喊，正常满窗不制造噪音。
  const coverageGap =
    data.coverage && data.coverage.available_buckets < data.coverage.requested_buckets ? data.coverage : null;
  // 「最后活动」的单一时间源：优先 coverage 里的真实末数据时刻，退回窗口内最新审计时间。
  // 两者都没有 → formatIsoDateTime 给空串，UI 换 UNKNOWN_VALUE（不造时间）。
  const lastActivityAt = data.coverage?.last_data_at ?? data.last_message_at ?? null;
  const identity = data.identity;

  return (
    <>
      {/* ② 四项 KPI：**用户数与调用数是两个量**（口径不同就别塞进一张卡）。 */}
      <div className='grid grid-cols-2 gap-4 lg:grid-cols-4'>
        <StatCard label='总请求数' value={formatNumber(data.total_calls)} sub='审计库窗口内的调用行数' />
        <StatCard
          label='活跃用户数'
          value={data.active_users === undefined ? '尚未采集' : formatNumber(data.active_users)}
          sub='窗口内可归属用户去重；会话约定外的行不计入'
        />
        <StatCard
          label='不可归属调用'
          value={formatNumber(data.unattributed_calls)}
          sub='会话标识不符合 OneBot 约定，未计入用户'
        />
        <StatCard
          label='时间戳异常'
          value={formatNumber(data.unknown_timestamp_calls)}
          sub='created_at 无法解析，不进入任何时间桶'
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className='fs-card'>{t('calls.trend')}</CardTitle>
          <CardDescription>
            {t('calls.trendDesc', { bucket: data.trend.bucket, timezone: data.trend.timezone })}
          </CardDescription>
        </CardHeader>
        <CardContent className='flex flex-col gap-2'>
          {/* 轴覆盖度告警必须在图上方：读图前先知道这条线是「数据缺口」还是「真的掉到 0」。 */}
          {coverageGap && (
            <p className='fs-caption text-tone-warn'>
              窗口内只有 {formatCount(coverageGap.available_buckets)}/{formatCount(coverageGap.requested_buckets)}{' '}
              个时间桶有真实调用，其余为数据缺口而非零流量
            </p>
          )}
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
                    labelFormatter={(value) => formatIsoDateTime(String(value))}
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
          labelFor={capabilityLabel}
        />
        <TopList
          title={t('calls.bySession')}
          description='会话标识按 OneBot 约定解析（原始标识见悬停提示）'
          entries={data.by_session.map((entry) => ({ key: entry.session, calls: entry.calls }))}
          labelFor={sessionLabel}
        />
        <TopList
          title={t('calls.byUser')}
          description={t(`calls.attribution.${data.user_attribution === 'derived_from_session_id_onebot_convention' ? 'onebot' : 'other'}`)}
          entries={data.by_user.map((entry) => ({ key: entry.user, calls: entry.calls }))}
          labelFor={userLabel}
        />
      </div>

      {/* ⑤ 最近调用明细：身份链六列。列宽靠 minmax 轨道 + truncate 扛中文全名，不靠缩字号。 */}
      <SectionCard
        title='最近调用明细'
        description='按会话身份聚合（群合一行、私聊/系统各自一行）；「最后活动」取窗口内真实末数据时刻，无数据如实显示 —'
      >
        <div className='flex flex-col gap-2'>
          {identity?.available ? (
            identity.sessions.length === 0 ? (
              <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
            ) : (
              <>
                <div className={`${DETAIL_GRID} border-b pb-2 fs-caption text-muted-foreground`}>
                  {DETAIL_COLUMNS.map((column) => (
                    <span key={column} className='truncate'>
                      {column}
                    </span>
                  ))}
                </div>
                {identity.sessions.map((session) => (
                  <IdentityRow key={identityRowKey(session)} session={session} lastActivityAt={lastActivityAt} />
                ))}
              </>
            )
          ) : (
            // 🔴 explicit 降级：没有 identity 块 / available=false 时**不能当 0 行数据**——那是谎报。
            <p className='fs-caption text-tone-warn'>
              身份链字段尚未采集（审计库缺 platform / group_id / group_title / sender_nickname 四列），需重启 bot
              后首次写入才补列
            </p>
          )}
        </div>
      </SectionCard>
    </>
  );
}

/** 明细行稳定键：会话种类 + 平台 + 群号/用户号（与后端聚合键同构）。 */
function identityRowKey(session: CallsIdentitySession): string {
  return [session.kind, session.platform ?? '', session.group_id ?? session.user_id ?? ''].join('|');
}

function IdentityRow({ session, lastActivityAt }: { session: CallsIdentitySession; lastActivityAt: string | null }) {
  const groupId = (session.group_id ?? '').trim();
  const kind = (session.kind ?? '').trim();
  const title = (session.group_title ?? '').trim();
  // 群 → 群名优先、群号兜底；私聊/邮件/系统没有「群 / 频道」，说清它是什么而不是留空。
  const channelText = kind === 'group' ? title || (groupId ? `群 ${groupId}` : '未采集') : sessionKindLabel(kind);
  const userId = (session.user_id ?? '').trim();
  const nicknames = session.users.map((user) => (user.sender_nickname ?? '').trim()).filter(Boolean);
  // 群行可能有多位发言人：昵称列表太长就只给前几位 + 总数（明细在 title 里全给）。
  const nicknameText =
    nicknames.length === 0 ? '' : nicknames.length > 3 ? `${nicknames.slice(0, 3).join('、')} 等 ${nicknames.length} 人` : nicknames.join('、');
  const userText = [userId ? `用户 ${userId}` : '', nicknameText].filter(Boolean).join(' · ') || '未采集';
  // 「最后活动」用 ASCII 短形（`YYYY-MM-DD HH:mm:ss`）——用户 2026-10-20 点名要这个形态：
  // 表格列里中文长形会撑宽列，且复制去 grep 日志永远 grep 不到（日志写的是 ISO）。
  const timeText = formatIsoTimestamp(lastActivityAt) || UNKNOWN_VALUE;

  return (
    <div className={`${DETAIL_GRID} border-b py-2 last:border-b-0 fs-caption`}>
      <span className='truncate' title={session.platform ?? ''}>
        {platformOf(session.platform)}
      </span>
      <span className='truncate' title={kind}>
        {sessionKindLabel(kind)}
      </span>
      <span className='truncate' title={title || groupId}>
        {channelText}
      </span>
      <span className='truncate' title={[userId, ...nicknames].filter(Boolean).join(' / ')}>
        {userText}
      </span>
      <span className='tabular-nums text-right'>{formatCount(session.calls)}</span>
      <span className='tabular-nums text-muted-foreground' title={lastActivityAt ?? ''}>
        {timeText}
      </span>
    </div>
  );
}
