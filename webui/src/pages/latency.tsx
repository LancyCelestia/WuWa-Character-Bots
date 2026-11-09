import { useState } from 'react';
import { ChevronRight, TriangleAlert } from 'lucide-react';
import {
  CategoryChip,
  DataGrid,
  DataGridCell,
  DataGridRow,
  PageHeader,
  SectionCard,
  StatCard,
} from '@/components/patterns/patterns';
import { BreakerDot } from '@/components/console/breaker-dot';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { controlApi, type LatencyData, type LatencyItem } from '@/lib/api-client';
import { breakerStateOf, channelLabel, errorLabel, statusLabel } from '@/lib/domain-labels';
import { absentFields, fieldDoc } from '@/lib/field-dict';
import { formatCount, formatDateTime, formatMs } from '@/lib/format';

// 延迟页：端到端百分位（实测快照）+ 未采集提示 + 通道健康（默认收起）。
//
// 三条诚实性红线，都是用户抱怨的源头：
//   ① 首 Token 延迟**尚未采集**——账本 first_token_latency_ms 3397 行全 NULL、全仓无
//      stream=True，客户端结构性测不到。不许写「0 毫秒」（会被读成瞬间返回），
//      也不许写「—」（会被读成加载中）。
//   ② `item.channel` 实为 `channel_health.model_id` 原值（`axon-gemini-38-flash`），
//      必须走 channelLabel() 出中文，不再 font-mono 直接上屏。
//   ③ `item.state` 只有 ok / temporarily_unavailable 两态，且 temporarily_unavailable
//      大多**最近仍成功过**（冷却期满仍会被路由到）——必须在句子里说出来，否则读者会
//      以为这些通道已经废了。
//
// 端到端百分位：/api/v1/stats/latency 不投影 llm_call_records 聚合，本页不伪造实时值；
// 卡上的是 `lib/field-dict.ts` 登记的实测快照，逐张标注口径与截止时间。
// 页面文案固定中文（与 i18n 无关）：本页新增文案未进语言表，避免半截翻译。
// ponytail: 这层内联文案的出口是补两处 locale 表后改回 t()；当前只有中文界面在用本页。

/** 端到端百分位实测快照的出处与截止时间（与 field-dict.ts 的三条 latency 条目同源）。 */
const MEASURED_NOTE = '最近一次实测，全库 3397 次调用，截至 2026-10-19';

/** 未采集提示条的数据面：只取 latency 模块，标签从字段字典读、不手抄。 */
const ABSENT_LATENCY = absentFields().filter((doc) => doc.module === 'latency');

/**
 * 未采集提示条的完整文案。
 * 「为什么测不到」取自字段字典的 detail（NO_STREAM 那段）：取含「原因」的那一句 + 最后一句
 * （要怎么办）。detail 里逐字有「行数/列名」，前面已经说清是哪几个指标，不再重复。
 */
function absentNotice(): string {
  if (ABSENT_LATENCY.length === 0) return '';
  const labels = ABSENT_LATENCY.map((doc) => doc.label).join('、');
  const sentences = (fieldDoc('ttft_p99')?.detail ?? '').split('。').filter(Boolean);
  const cause = sentences.find((line) => line.includes('原因')) ?? sentences[0] ?? '';
  const remedy = sentences.at(-1) ?? '';
  return `以下指标尚未采集：${labels} —— ${[cause, remedy].filter(Boolean).join('。')}。`;
}

const ABSENT_NOTICE = absentNotice();

/**
 * 「为什么它处于这个状态」——每通道一句中文自然语言：状态词 + 原因 +（可选）失败原因。
 *
 * ⚠️ 这里只调 `breakerStateOf(state)`：本端点（webui_stats.latency_view）**不投影
 * `cooldown_until`**，`breakerStateOf` 收到缺失冷却时间会保守判 open，所以 half-open 分支
 * 在现有数据下不可达，故不写死这一句——留着它只会是永远不会执行的谎话。后端哪天补投影了，
 * 把 cooldown 传进来、再补回 half-open 文案即可。
 */
function whySentence(item: LatencyItem): string {
  const head = `${statusLabel(item.state)} —— `;
  const failed = `${item.consecutive_fails} 次`;
  let reason: string;

  switch (breakerStateOf(item.state)) {
    case 'closed':
      reason = '最近一次探测成功，正常参与路由';
      break;
    case 'open':
      // 有 last_ok_at = 曾经连通、只是最近探测失败。必须点明：`_decide_available` 的判据是
      // 「last_probe_at 距现在 ≥ 1800 秒就放行」，所以这些通道实际仍会被路由到。
      reason = item.last_ok_at
        ? `最近仍成功过（最近一次成功在 ${formatDateTime(item.last_ok_at)}）；连续失败 ${failed}，冷却期满后仍会参与路由`
        : `从未探测成功过；连续失败 ${failed}，冷却期满后仍会参与路由`;
      break;
    default:
      reason = '状态未登记，无法判断';
  }

  // 英文原文不丢：归类进句子，原文进 title 属性供排查。
  return item.last_error ? `${head}${reason}；最近一次失败原因：${errorLabel(item.last_error).kind}` : `${head}${reason}`;
}

function ChannelRow({ item }: { item: LatencyItem }) {
  return (
    <DataGridRow className='items-start'>
      <DataGridCell className='flex-1'>
        <div className='flex flex-wrap items-center gap-2'>
          <BreakerDot state={item.state} />
          <span className='fs-body'>{channelLabel(item.channel)}</span>
          {item.consecutive_fails > 0 && <CategoryChip label={`×${item.consecutive_fails}`} tone='bad' />}
        </div>
        <p className='fs-caption text-muted-foreground' title={item.last_error ?? undefined}>
          {whySentence(item)}
        </p>
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums'>
        <span className='fs-caption text-muted-foreground'>平滑延迟</span>
        <div className='fs-body'>{formatMs(item.ema_ms)}</div>
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums'>
        <span className='fs-caption text-muted-foreground'>最近延迟</span>
        <div className='fs-body'>{formatMs(item.latency_ms)}</div>
      </DataGridCell>
      <DataGridCell className='w-20 shrink-0 text-right tabular-nums'>
        <span className='fs-caption text-muted-foreground'>样本</span>
        <div className='fs-body'>{formatCount(item.samples)}</div>
      </DataGridCell>
    </DataGridRow>
  );
}

export function LatencyPage() {
  // 用户裁定「承诺健康改小」⇒ 默认收起。用 state 而不是 <details>：展开态要对齐整页的
  // 间距/字号 token，原生 summary 的标记在深色壁纸下不受控。
  const [channelsOpen, setChannelsOpen] = useState(false);

  const query = useSemanticQuery<LatencyData>(['stats-latency', 'page'], () => controlApi.statsLatency(), {
    refetchInterval: 30_000,
  });

  return (
    <div className='flex w-full flex-col gap-4'>
      <PageHeader
        title='延迟'
        subtitle='端到端百分位为实测快照；通道健康取 channel_health 当前值 · 30 秒自动刷新'
        actions={<span className='fs-caption text-muted-foreground'>{MEASURED_NOTE}</span>}
      />

      {/* ② 未采集提示条：警示色，不用红色、无插画、不阻塞交互。 */}
      {ABSENT_NOTICE && (
        <p className='flex items-start gap-2 fs-caption text-tone-warn'>
          <TriangleAlert aria-hidden className='mt-1 size-4 shrink-0' />
          <span>{ABSENT_NOTICE}</span>
        </p>
      )}

      {/* ① KPI 行：三个实测端到端 + 一个结构性未采集。 */}
      <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
        <StatCard label='端到端延迟 P50' value='6733 毫秒' sub={`中位数，代表典型体验 · ${MEASURED_NOTE}`} />
        <StatCard label='端到端延迟 P90' value='17360 毫秒' sub={`第 90 百分位 · ${MEASURED_NOTE}`} />
        <StatCard label='端到端延迟 P99' value='60077 毫秒' sub={`第 99 百分位，尾部体验 · ${MEASURED_NOTE}`} />
        <SectionCard title='首 Token 延迟 P99' titleClass='text-muted-foreground'>
          <div className='flex flex-col gap-1'>
            <span className='fs-num text-tone-warn'>尚未采集</span>
            <p className='fs-caption text-muted-foreground'>调用链路未启用流式传输，客户端无从测得首 Token 时刻</p>
          </div>
        </SectionCard>
      </div>

      {query.state.phase === 'ok' ? (
        <>
          {/* ③ 通道健康区：默认收起。 */}
          <SectionCard
            title={
              <button
                type='button'
                onClick={() => setChannelsOpen((open) => !open)}
                aria-expanded={channelsOpen}
                className='flex items-center gap-2'
              >
                <ChevronRight
                  aria-hidden
                  className={`size-4 shrink-0 transition-transform ${channelsOpen ? 'rotate-90' : ''}`}
                />
                通道健康（{formatCount(query.state.data.items.length)}）
              </button>
            }
            description='「暂时不可用」不等于通道已废弃——冷却期满仍会被路由到'
          >
            {channelsOpen &&
              (query.state.data.items.length === 0 ? (
                <p className='py-6 text-center fs-caption text-muted-foreground'>暂无数据</p>
              ) : (
                <DataGrid>
                  {query.state.data.items.map((item) => (
                    <ChannelRow key={item.channel} item={item} />
                  ))}
                </DataGrid>
              ))}
          </SectionCard>

          <SectionCard
            title='延迟历史'
            description={
              query.state.data.history?.status === 'unavailable'
                ? `后端显式标记不可用（${query.state.data.history.reason}）——无持久化存储，不画假曲线`
                : undefined
            }
          >
            <p className='py-2 fs-caption text-muted-foreground'>
              {query.state.data.history?.status === 'unavailable' ? '暂无历史' : '暂无数据'}
            </p>
          </SectionCard>
        </>
      ) : (
        <SemanticState state={query.state} onRetry={query.refetch} />
      )}
    </div>
  );
}
