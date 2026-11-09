import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownWideNarrow, ArrowUpNarrowWide } from 'lucide-react';
import { PageHeader, SectionCard, DataGrid, DataGridRow, DataGridCell, CategoryChip, StatCard, type Tone } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type AffinityBoardData, type AffinityItem } from '@/lib/api-client';
import { fieldDoc, fieldRow } from '@/lib/field-dict';
import { formatCount, formatDateTime, formatDecimal } from '@/lib/format';
import { cn } from '@/lib/utils';

// 好感度榜：/api/v1/affinity/board（user_affinity 只读，显数值口径——
// 2026-09-15 用户裁定 WebUI 面板直显数值；聊天内侧定性口径不受影响，两处不同源）。
// 档位色阶：独一份=品红紫、挚友=紫、亲近=品牌蓝、友善=info、稍淡=warn、生疏/初识=bad（负值红阶）。
//
// 本页最要紧的一件事实（W15 T7，实测于 2026-10-19 全库只读快照）：
// **后端没有暴露好感度增量时间序列。** `affinity_delta_log` 表客观存在（1914 行，
// 2026-10-18 01:28 → 2026-10-20 01:27，跨度仅 2.0 天），但 control_plane/ 目录下
// grep 该表名零命中——没有任何端点把它读出来；唯一的好感度端点只返回当前快照。
// 所以五档粒度里只有「累计」有真数据，其余四档必须说出「为什么没有」，不许画假线、
// 不许把累计档的数据复用过去、更不许把按钮灰掉装作不存在（灰掉会让用户以为坏了）。

/** 榜单取多少条：页面上的「合计」只覆盖这前 N 名，不是全库合计。 */
const BOARD_LIMIT = 100;

/** 全库实测常数（只读，截至 2026-10-19）——非本端点返回，属「诚实标注过的外部实测」。 */
const MEASURED = {
  users: 562,
  meanAffinity: 0.209,
  maxAffinity: 0.763,
  asOf: '2026-10-19',
} as const;

/** 增量日志实测边界（同上，2026-10-19）。 */
const DELTA_LOG = '1914 行数据（2026-10-18 起，跨 2.0 天）';

type Grain = 'daily' | 'weekly' | 'monthly' | 'yearly' | 'total';

const GRAINS: readonly { code: Grain; label: string }[] = [
  { code: 'daily', label: '每日' },
  { code: 'weekly', label: '每周' },
  { code: 'monthly', label: '每月' },
  { code: 'yearly', label: '每年' },
  { code: 'total', label: '累计' },
];

/** 该档位在这个后端契约下有没有真数据；没有的档位统一走诚实占位，不复用累计档。 */
const GRAIN_HAS_DATA: Record<Grain, boolean> = {
  total: true,
  daily: false,
  weekly: false,
  monthly: false,
  yearly: false,
};

/** 详情栏四列字典的字段顺序：好感度模块 9 条里的 5 条用户级字段（另有 4 条周期增量在档位区单独说）。 */
const DETAIL_KEYS = ['affinity_total', 'interaction_count', 'positive_count', 'negative_count', 'affinity_change_rate'] as const;

/** 四档增量字段，键名按档位取。 */
const DELTA_KEY: Record<Exclude<Grain, 'total'>, string> = {
  daily: 'affinity_delta_daily',
  weekly: 'affinity_delta_weekly',
  monthly: 'affinity_delta_monthly',
  yearly: 'affinity_delta_yearly',
};

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

/** 选中/未选中两态的按钮外观（五档切换器与排序键共用一套，避免两套选中风格）。 */
const SEG_BASE = 'rounded-md px-3 py-1 fs-caption transition-colors';
const SEG_ON = 'border border-primary bg-primary/15 text-primary';
const SEG_OFF = 'border border-transparent text-muted-foreground hover:bg-accent';

/** 该用户的某个字段当前值；字典里没有这条或没有值一律 null（交给四列渲染判「尚未采集」）。 */
function fieldValue(item: AffinityItem, key: string): string | null {
  switch (key) {
    case 'affinity_total':
      return formatDecimal(item.score);
    case 'interaction_count':
      return formatCount(item.interaction_count);
    default:
      // positive_count / negative_count / affinity_change_rate：端点不返回这些列，
      // 页面拿不到就当拿不到，绝不拿别的列顶替。
      return null;
  }
}

/** 四列字典的一行。键值列：字典判 absent 或页面无值 → 「尚未采集」，不显 0、不显未知符号。 */
function DictRow({
  rowKey,
  value,
  trailing,
}: {
  rowKey: string;
  value: string | null;
  trailing?: string;
}) {
  const row = fieldRow(rowKey);
  if (!row) return null;
  const doc = fieldDoc(rowKey);
  const absent = doc?.availability === 'absent' || value === null;
  return (
    <div className='grid grid-cols-2 gap-2 border-b py-3 last:border-b-0 lg:grid-cols-4'>
      <div className='fs-body text-foreground'>{row.label}</div>
      <div className={cn('font-mono fs-caption', absent ? 'text-tone-warn' : 'text-muted-foreground')}>
        {absent ? '尚未采集' : row.key}
        {trailing && !absent && <span className='text-muted-foreground'> · {trailing}</span>}
      </div>
      <div className='fs-caption text-muted-foreground'>{row.summary}</div>
      <div className='fs-caption text-muted-foreground'>{row.detail}</div>
    </div>
  );
}

/** 「值」这一格：与键名放在同一块，四列布局里第二列只放键值，值另起一行给读者。 */
function ValueCell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className='flex min-w-0 items-baseline justify-between gap-2'>
      <span className='truncate fs-body text-foreground'>{label}</span>
      <span className={cn('shrink-0 fs-num', tone ?? 'text-foreground')}>{value}</span>
    </div>
  );
}

function BoardRow({ item, rank, active, onSelect }: { item: AffinityItem; rank: number; active: boolean; onSelect: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type='button'
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        'w-full rounded-md px-2 text-left transition-colors',
        active ? 'bg-primary/15 ring-1 ring-ring' : 'hover:bg-accent'
      )}
    >
      <DataGridRow>
        {/* 选中态的左竖条：未选中时留空占位，避免整行左右跳动。 */}
        <span aria-hidden className={cn('h-6 w-1 shrink-0 rounded-full', active ? 'bg-primary' : 'bg-transparent')} />
        <DataGridCell className='w-8 shrink-0 text-right tabular-nums text-muted-foreground'>{rank}</DataGridCell>
        <DataGridCell className='flex-1'>
          <div className='truncate fs-body font-medium' title={item.nickname || item.sender_id}>
            {item.nickname || item.sender_id}
          </div>
          <div className='truncate font-mono fs-caption text-muted-foreground'>
            {item.sender_id}
            {item.nickname ? ` · ${t('affinity.interactions', { count: formatCount(item.interaction_count) })}` : ''}
          </div>
        </DataGridCell>
        <DataGridCell className='w-24 shrink-0 text-right'>
          <span className={cn('fs-card tabular-nums', scoreClass(item.score))}>
            {item.score > 0 ? '+' : ''}
            {formatDecimal(item.score)}
          </span>
        </DataGridCell>
        <DataGridCell className='w-24 shrink-0'>
          <CategoryChip label={item.tier_name} tone={tierTone(item.tier)} />
        </DataGridCell>
        <DataGridCell className='w-36 shrink-0 text-right fs-caption text-muted-foreground'>
          {formatDateTime(item.updated_at)}
        </DataGridCell>
      </DataGridRow>
    </button>
  );
}

/** 累计档的真数据：当前榜单按展示分排横向条（宽度是相对百分点，非时间序列）。 */
function BoardDistribution({ items }: { items: readonly AffinityItem[] }) {
  const sorted = [...items].sort((a, b) => b.score - a.score);
  const maxAbs = sorted.reduce((acc, item) => Math.max(acc, Math.abs(item.score)), 0);
  if (!sorted.length) return <p className='py-6 text-center fs-caption text-muted-foreground'>暂无数据</p>;
  return (
    <div className='flex flex-col gap-2'>
      <p className='fs-caption text-muted-foreground'>
        横轴是展示分（内部值 × 100），只此一列是快照，不是时间序列。
      </p>
      {sorted.map((item) => (
        <div key={item.sender_id} className='flex flex-col gap-1'>
          <div className='flex items-baseline justify-between gap-2 fs-caption'>
            <span className='truncate' title={item.nickname || item.sender_id}>
              {item.nickname || item.sender_id}
            </span>
            <span className='shrink-0 tabular-nums text-muted-foreground'>{formatDecimal(item.score)}</span>
          </div>
          <div className='h-1.5 overflow-hidden rounded-full bg-accent'>
            <div
              className={cn('h-full rounded-full', item.score >= 0 ? 'bg-primary/70' : 'bg-tone-bad')}
              style={{ width: maxAbs > 0 ? `${Math.max(2, (Math.abs(item.score) / maxAbs) * 100)}%` : '0%' }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 没有数据的四档：说出为什么没有，绝不画线。 */
function AbsentGrainNotice({ grain }: { grain: Exclude<Grain, 'total'> }) {
  const label = GRAINS.find((g) => g.code === grain)?.label ?? '';
  return (
    <div className='flex flex-col gap-2 rounded-md bg-muted p-3'>
      <p className='fs-caption text-tone-warn'>
        后端未暴露好感度增量时间序列。`affinity_delta_log` 表有 {DELTA_LOG}，但 `/api/v1/affinity/board`
        只返回当前快照。要画{label}趋势需新增只读端点。
      </p>
      {grain !== 'daily' && (
        <p className='fs-caption text-tone-warn'>
          该粒度目前只有 1 个数据桶（增量日志仅 2.0 天历史），不足以判断趋势。
        </p>
      )}
      <p className='fs-caption text-muted-foreground'>
        这里不画线：没有时间序列却画出走势，等于把「不知道」写成「知道」。
      </p>
    </div>
  );
}

/** 三级下钻的终点：单个用户的四列字典 + 四档增量。 */
function DetailPane({ item }: { item: AffinityItem }) {
  return (
    <SectionCard
      title={item.nickname || item.sender_id}
      description={`已下钻到单个用户 · 字典取 field-dict.ts，键值区标「尚未采集」的列本端点不返回`}
      action={<CategoryChip label={item.tier_name} tone={tierTone(item.tier)} />}
    >
      <div className='flex flex-col gap-2'>
        <ValueCell label='展示分' value={`${item.score > 0 ? '+' : ''}${formatDecimal(item.score)}`} tone={scoreClass(item.score)} />
        <ValueCell label='内部值（-1..1）' value={formatDecimal(item.affinity, 3)} />
        <ValueCell label='内部累计计数' value={tierLabel(item.tier)} />
        <p className='fs-caption text-muted-foreground'>
          {`互动 ${formatCount(item.interaction_count)} 次 · 快照时间 ${formatDateTime(item.updated_at)}`}
        </p>
      </div>

      <div className='mt-4 border-t pt-3'>
        <div className='grid grid-cols-2 gap-2 border-b py-2 lg:grid-cols-4'>
          <span className='fs-caption text-muted-foreground'>自然语言键名</span>
          <span className='fs-caption text-muted-foreground'>键值</span>
          <span className='fs-caption text-muted-foreground'>简介</span>
          <span className='fs-caption text-muted-foreground'>说明</span>
        </div>
        {DETAIL_KEYS.map((key) => (
          <DictRow key={key} rowKey={key} value={fieldValue(item, key)} />
        ))}
      </div>

      <div className='mt-4 border-t pt-3'>
        <p className='fs-body text-foreground'>各档位增量</p>
        <p className='fs-caption text-tone-warn'>四档增量全部未接入：端点只回当前快照，没有该用户在窗口内的增量。</p>
        {(Object.keys(DELTA_KEY) as Exclude<Grain, 'total'>[]).map((grain) => (
          <DictRow key={grain} rowKey={DELTA_KEY[grain]} value={null} trailing='未接入' />
        ))}
      </div>
    </SectionCard>
  );
}

/** 档位名（后端给中文串，缺失时回落到数字）。 */
function tierLabel(tier: number): string {
  return `档位 ${tier}`;
}

export function AffinityPage() {
  const { t } = useTranslation();
  const [order, setOrder] = useState<'desc' | 'asc'>('desc');
  const [grain, setGrain] = useState<Grain>('total');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useSemanticQuery<AffinityBoardData>(
    ['affinity-board', order],
    () => controlApi.affinityBoard({ limit: BOARD_LIMIT, order }),
    { refetchInterval: 120_000 }
  );

  const data = query.state.phase === 'ok' ? query.state.data : null;
  const items = data?.items ?? [];
  const selected = items.find((item) => item.sender_id === selectedId) ?? null;

  // 卡 1 的合计只覆盖本端点返回的前 N 名：**不是**全库累计总好感度。
  const pageSum = items.reduce((acc, item) => acc + item.score, 0);
  const topScore = items.reduce((acc, item) => Math.max(acc, item.score), 0);

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader
        title={t('affinity.title')}
        subtitle={t('affinity.boardDesc')}
        actions={
          <>
            {data && <span className='fs-caption text-muted-foreground'>{t('affinity.total', { count: formatCount(data.total) })}</span>}
            <button
              type='button'
              onClick={() => setOrder(order === 'desc' ? 'asc' : 'desc')}
              className={cn('flex items-center gap-2', SEG_BASE, 'border text-muted-foreground hover:bg-accent')}
            >
              {order === 'desc' ? <ArrowDownWideNarrow className='size-4' /> : <ArrowUpNarrowWide className='size-4' />}
              {order === 'desc' ? t('affinity.orderDesc') : t('affinity.orderAsc')}
            </button>
          </>
        }
      />

      {query.state.phase === 'ok' && data ? (
        <>
          {/* ① 四张 KPI 卡：每一项都标清它算的是「前 N 名」还是「全库实测常数」。 */}
          <div className='grid grid-cols-2 gap-4 lg:grid-cols-4'>
            <StatCard
              label='前 N 名好感度合计'
              value={formatDecimal(pageSum)}
              sub={`分 · 共 ${formatCount(data.total)} 名用户，此处合计前 ${formatCount(items.length)} 名`}
            />
            <StatCard
              label='平均好感度'
              value={formatDecimal(MEASURED.meanAffinity, 3)}
              sub={`全库 ${formatCount(MEASURED.users)} 名用户，展示分 ${formatDecimal(MEASURED.meanAffinity * 100, 1)}（全库实测，截至 ${MEASURED.asOf}）`}
            />
            <StatCard
              label='最高好感度'
              value={formatDecimal(MEASURED.maxAffinity, 3)}
              sub={`展示分 ${formatDecimal(MEASURED.maxAffinity * 100, 1)}（全库实测，截至 ${MEASURED.asOf}）；本页榜首 ${formatDecimal(topScore)}`}
            />
            <StatCard
              label='今日好感度增量'
              value='尚未接入'
              sub='后端未暴露增量时间序列'
            />
          </div>

          {/* ② 五粒度切换：五档全渲染、全可点，没数据的四档说清为什么。 */}
          <SectionCard
            title='好感度粒度'
            description='五档全部可切换；只有「累计」在后端有快照数据'
            action={
              <div className='flex flex-wrap items-center gap-1' role='tablist' aria-label='好感度粒度'>
                {GRAINS.map((option) => (
                  <button
                    key={option.code}
                    type='button'
                    role='tab'
                    aria-selected={grain === option.code}
                    onClick={() => setGrain(option.code)}
                    className={cn(SEG_BASE, grain === option.code ? SEG_ON : SEG_OFF)}
                  >
                    {option.label}
                    {!GRAIN_HAS_DATA[option.code] && <span className='ml-1 text-tone-warn'>·</span>}
                  </button>
                ))}
              </div>
            }
          >
            {grain === 'total' ? (
              <BoardDistribution items={items} />
            ) : (
              <AbsentGrainNotice grain={grain} />
            )}
          </SectionCard>

          {/* ③ 三级下钻：榜单 → 点用户 → 右侧详情；窄屏详情就地铺在下方。 */}
          <div className='grid grid-cols-1 gap-4 lg:grid-cols-3'>
            <div className={cn(selected ? 'lg:col-span-2' : 'lg:col-span-3')}>
              <SectionCard title={t('affinity.boardTitle')} description={`前 ${formatCount(items.length)} 名 · 点一行看详情`}>
                {items.length === 0 ? (
                  <p className='py-6 text-center fs-caption text-muted-foreground'>{t('state.noData')}</p>
                ) : (
                  <DataGrid>
                    {items.map((item, index) => (
                      <BoardRow
                        key={item.sender_id}
                        item={item}
                        rank={index + 1}
                        active={item.sender_id === selectedId}
                        onSelect={() => setSelectedId(item.sender_id === selectedId ? null : item.sender_id)}
                      />
                    ))}
                  </DataGrid>
                )}
              </SectionCard>
            </div>
            {selected && (
              <aside className='lg:col-span-1'>
                <DetailPane item={selected} />
              </aside>
            )}
          </div>
          {!selected && (
            <p className='fs-caption text-muted-foreground'>点榜单里的任一行，右侧（窄屏为下方）展开该用户的字段字典。</p>
          )}
        </>
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}
