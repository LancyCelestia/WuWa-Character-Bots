import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, TriangleAlert } from 'lucide-react';
import { CategoryChip, DataGrid, DataGridCell, DataGridRow, PageHeader, SectionCard, StatCard } from '@/components/patterns/patterns';
import { MemoryCanvas } from '@/components/graph/memory-canvas';
import { SemanticState } from '@/components/semantic/semantic-state';
import { isNotFound } from '@/lib/semantics';
import { Skeleton } from '@/components/ui/skeleton';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import {
  controlApi,
  type GraphWindow,
  type MemoryGraphData,
  type MemoryGraphNodeType,
} from '@/lib/api-client';
import { computeDegrees } from '@/lib/graph-layout';
import { formatInt } from '@/lib/format';
import { cn } from '@/lib/utils';

// 记忆图谱页（spec webui-pages2 §3 + §7 B 系增补）：六枚 StatCard + 工具行（时间窗 chip 组/
// 五类型多选复色/label 本地过滤）+ d3-force 静态画布（300 tick 确定性布局）+ 图例 + 点击节点
// 详情侧栏（含「数据范围」静态说明，§7 B10b）。max_nodes 取后端上限 200。
// 全不选类型=自动回全选（不给空图死局）；truncated=画布顶部 info 条（如实带截断前总量 nodes_total）；
// sources 部分降级=页面级 warn 条（F2-02：降级来源绝不与全健康同相）；连线只读（§7 B9 提示吸收进 canvasHint）。

const WINDOWS: GraphWindow[] = ['24h', '7d', '30d', 'all'];
const TYPES: MemoryGraphNodeType[] = ['person', 'group', 'conversation', 'memory', 'rule'];
const TYPE_DOT: Record<MemoryGraphNodeType, string> = {
  person: 'bg-chart-1',
  group: 'bg-chart-2',
  memory: 'bg-chart-3',
  conversation: 'bg-chart-4',
  rule: 'bg-chart-5',
};

// 数据源名/态人话（真相源=webui_memory_graph：sources 键 history/memory/quirks/affinity，
// 值 ok/missing/unreadable）。表外取值回退裸码原文——绝不编语义，也绝不静默隐藏降级。
const SOURCE_NAMES = ['history', 'memory', 'quirks', 'affinity'];
const SOURCE_STATES = ['missing', 'unreadable'];

function sourceName(t: (key: string) => string, name: string): string {
  return SOURCE_NAMES.includes(name) ? t(`memoryGraph.sourceName.${name}`) : name;
}

function sourceState(t: (key: string) => string, state: string): string {
  return SOURCE_STATES.includes(state) ? t(`memoryGraph.sourceState.${state}`) : state;
}

export function MemoryGraphPage() {
  const { t } = useTranslation();
  const [window, setWindow] = useState<GraphWindow>('24h');
  const [typesHidden, setTypesHidden] = useState<ReadonlySet<MemoryGraphNodeType>>(new Set());
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const graph = useSemanticQuery<MemoryGraphData>(['memory-graph', window], () => controlApi.memoryGraph({ window }));
  const data = graph.state.phase === 'ok' ? graph.state.data : null;

  // 数据/时间窗变化后：选中的节点仍在图内则保留，否则清空。
  useEffect(() => {
    setSelectedId((prev) => (prev && data?.nodes.some((node) => node.id === prev) ? prev : null));
  }, [data]);

  // 类型多选：全不选=自动回全选（不给空图死局）。
  const toggleType = (type: MemoryGraphNodeType) => {
    setTypesHidden((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next.size === TYPES.length ? new Set() : next;
    });
  };

  const visibleNodes = useMemo(
    () => (data ? data.nodes.filter((node) => !typesHidden.has(node.type)) : []),
    [data, typesHidden]
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => (data ? data.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)) : []),
    [data, visibleIds]
  );
  const degrees = useMemo(() => (data ? computeDegrees(data.nodes, data.edges) : new Map<string, number>()), [data]);
  const degradedSources = useMemo(
    () => (data ? Object.entries(data.sources).filter(([, state]) => state !== 'ok') : []),
    [data]
  );
  const selectedNode = data?.nodes.find((node) => node.id === selectedId) ?? null;

  const stats = data
    ? ([
        { label: t('memoryGraph.stats.persons'), value: data.stats.persons },
        { label: t('memoryGraph.stats.groups'), value: data.stats.groups },
        { label: t('memoryGraph.stats.conversations'), value: data.stats.conversations },
        { label: t('memoryGraph.stats.longTermMemories'), value: data.stats.long_term_memories },
        { label: t('memoryGraph.stats.learnedRules'), value: data.stats.learned_rules },
        { label: t('memoryGraph.stats.speakerCount'), value: data.stats.speaker_count },
      ] as const)
    : [];

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader title={t('memoryGraph.title')} subtitle={t('memoryGraph.subtitle')} />

      {/* 六枚统计卡（xl 6 列 / md 3 列 / 移动 2 列，顺序固定） */}
      {graph.state.phase === 'loading' ? (
        <div className='grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6'>
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Skeleton key={index} className='h-24' />
          ))}
        </div>
      ) : (
        data && (
          <div className='grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6'>
            {stats.map((item) => (
              <StatCard key={item.label} label={item.label} value={formatInt(item.value)} />
            ))}
          </div>
        )
      )}

      {/* 工具行：时间窗 + 节点类型多选（复色）+ label 本地过滤 */}
      <div className='flex flex-wrap items-center gap-3'>
        <div className='flex flex-wrap items-center gap-2'>
          <span className='fs-caption text-muted-foreground'>{t('memoryGraph.windowLabel')}</span>
          {WINDOWS.map((item) => (
            <button key={item} type='button' onClick={() => setWindow(item)} className='rounded-full'>
              <CategoryChip label={t(`memoryGraph.window.${item}`)} tone={window === item ? 'brand' : 'flat'} />
            </button>
          ))}
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <span className='fs-caption text-muted-foreground'>{t('memoryGraph.typesLabel')}</span>
          {TYPES.map((type) => (
            <button key={type} type='button' onClick={() => toggleType(type)} className='rounded-full'>
              <CategoryChip
                label={
                  <span className='flex items-center gap-1'>
                    <span className={cn('size-2 rounded-full', TYPE_DOT[type])} />
                    {t(`memoryGraph.type.${type}`)}
                  </span>
                }
                tone='flat'
                className={typesHidden.has(type) ? 'opacity-40' : undefined}
              />
            </button>
          ))}
        </div>
        <div className='relative w-48'>
          <Search className='pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('memoryGraph.filterPlaceholder')}
            className='h-9 w-full rounded-md border bg-transparent pl-6 pr-2 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]'
            spellCheck={false}
          />
        </div>
      </div>

      {/* F2-02 修复：ok 包内部分源缺失/不可读 = 页面级警示条（此前只藏在选中节点侧栏，
          不点节点的操作员看到的是与全源健康一模一样的图）。数据照常渲染，不遮挡不降级误报。 */}
      {data && degradedSources.length > 0 && (
        <div role='status' className='flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2'>
          <TriangleAlert className='size-4 shrink-0 text-tone-warn' />
          <span className='fs-caption font-medium text-tone-warn'>{t('memoryGraph.partialTitle')}</span>
          {degradedSources.map(([name, state]) => (
            <CategoryChip
              key={name}
              label={t('memoryGraph.sourceChip', { name: sourceName(t, name), state: sourceState(t, state) })}
              tone='warn'
            />
          ))}
        </div>
      )}

      {/* 主体状态 */}
      {graph.state.phase === 'loading' ? (
        <Skeleton className='h-96' />
      ) : graph.state.phase === 'error' ? (
        isNotFound(graph.state) ? (
          <SectionCard title={t('memoryGraph.notDeployed')}>
            <p className='fs-body text-muted-foreground'>{t('memoryGraph.notDeployedHint')}</p>
          </SectionCard>
        ) : (
          <SemanticState state={graph.state} onRetry={graph.refetch} />
        )
      ) : graph.state.phase !== 'ok' || !data ? (
        <SemanticState state={graph.state} onRetry={graph.refetch} />
      ) : data.nodes.length === 0 ? (
        <SectionCard title={t('memoryGraph.empty')}>
          <p className='fs-body text-muted-foreground'>{t('memoryGraph.emptyHint')}</p>
        </SectionCard>
      ) : (
        <div className='flex flex-col gap-4 xl:flex-row'>
          <div className='min-w-0 flex-1'>
            <SectionCard
              title={t('memoryGraph.canvas')}
              action={
                data.truncated ? (
                  <CategoryChip
                    label={t('memoryGraph.truncated', {
                      count: formatInt(data.nodes.length),
                      total: formatInt(data.nodes_total),
                    })}
                    tone='info'
                  />
                ) : undefined
              }
              contentClass='relative'
            >
              {/* 内联 style 白名单 #1：画布容器高度（规格 §5.2；侧栏宽度走 xl:w-80 类，未用内联） */}
              <div className='relative' style={{ height: 480 }}>
                <MemoryCanvas
                  nodes={visibleNodes}
                  edges={visibleEdges}
                  query={query}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
                <div className='pointer-events-none absolute bottom-2 left-2 rounded-md border bg-card/80 px-2 py-1 fs-caption text-muted-foreground'>
                  {t('memoryGraph.canvasHint')}
                </div>
              </div>
              <div className='mt-3 flex flex-wrap items-center gap-3'>
                <span className='fs-caption text-muted-foreground'>{t('memoryGraph.legend')}</span>
                {TYPES.map((type) => (
                  <span key={type} className='flex items-center gap-1 fs-caption text-muted-foreground'>
                    <span className={cn('size-2 rounded-full', TYPE_DOT[type])} />
                    {t(`memoryGraph.type.${type}`)}
                  </span>
                ))}
              </div>
            </SectionCard>
          </div>

          {selectedNode && (
            <div className='shrink-0 xl:w-80'>
              <SectionCard title={t('memoryGraph.detail')}>
                <div className='flex flex-col gap-3'>
                  <div className='flex items-center gap-2'>
                    <span className={cn('size-2 rounded-full', TYPE_DOT[selectedNode.type])} />
                    <span className='fs-caption text-muted-foreground'>{t(`memoryGraph.type.${selectedNode.type}`)}</span>
                  </div>
                  <p className='fs-card break-words'>{selectedNode.label}</p>
                  <DataGrid>
                    <DataGridRow>
                      <DataGridCell className='w-20 shrink-0 fs-caption text-muted-foreground'>
                        {t('memoryGraph.degree')}
                      </DataGridCell>
                      <DataGridCell className='fs-body tabular-nums'>
                        {formatInt(degrees.get(selectedNode.id) ?? 0)}
                      </DataGridCell>
                    </DataGridRow>
                    {selectedNode.weight !== null && (
                      <DataGridRow>
                        <DataGridCell className='w-20 shrink-0 fs-caption text-muted-foreground'>
                          {t('memoryGraph.weight')}
                        </DataGridCell>
                        <DataGridCell className='fs-body tabular-nums'>{selectedNode.weight}</DataGridCell>
                      </DataGridRow>
                    )}
                    <DataGridRow>
                      <DataGridCell className='w-20 shrink-0 fs-caption text-muted-foreground'>
                        {t('memoryGraph.nodeId')}
                      </DataGridCell>
                      <DataGridCell>
                        <span className='block truncate font-mono fs-caption' title={selectedNode.id}>
                          {selectedNode.id}
                        </span>
                      </DataGridCell>
                    </DataGridRow>
                  </DataGrid>
                  {/* 数据范围静态说明（§7 B10b）：按当前时间窗+各源真实状态生成，不造数 */}
                  <div className='rounded-md border bg-muted/40 p-3'>
                    <div className='fs-caption font-medium'>{t('memoryGraph.dataScope')}</div>
                    <p className='mt-1 fs-caption text-muted-foreground'>
                      {t('memoryGraph.dataScopeBody', { window: t(`memoryGraph.window.${window}`) })}
                    </p>
                    {degradedSources.map(([name, state]) => (
                      <p key={name} className='mt-1 fs-caption text-tone-warn'>
                        {t('memoryGraph.sourceUnavailable', {
                          name: sourceName(t, name),
                          state: sourceState(t, state),
                        })}
                      </p>
                    ))}
                  </div>
                </div>
              </SectionCard>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
