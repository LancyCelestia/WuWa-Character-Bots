// 日志尾流页：/api/v1/logs/stream fetch-SSE 实时尾流。
// - 读取器=lib/sse.ts（EventSource 无法带 Authorization 头，控制面禁 token 进 URL）。
// - 游标续传：id: 帧 → sessionStorage（webui:logsCursor，per-tab）→ 重连/重进页面 Last-Event-ID 回传。
// - 410 cursor_expired：后端明文约定「客户端不得静默重置游标，须由用户选择重新订阅」→
//   停止自动重连 + 顶部缺口横幅 + 显式「重新订阅」按钮（清游标回放保留窗口）。
// - 心跳保活：`: heartbeat` 注释帧 → 45s 内有心跳视为存活（服务端默认 15s 一拍）。
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CirclePause, CirclePlay, Eraser, Link2Off, RotateCcw, ArrowDownToLine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PageHeader, SectionCard, CategoryChip, type Tone } from '@/components/patterns/patterns';
import { LogsStreamClient, type StreamStatus } from '@/lib/sse';
import { controlApi, type LogEventRow, type LogsSourcesData } from '@/lib/api-client';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { formatTime } from '@/lib/format';

const CURSOR_KEY = 'webui:logsCursor';
const MAX_ROWS = 500;
const HEARTBEAT_STALE_MS = 45_000;

const CATEGORY_TONE: Record<string, Tone> = {
  debug: 'flat',
  info: 'info',
  success: 'good',
  warning: 'warn',
  error: 'bad',
  critical: 'bad',
  detail: 'flat',
};

function statusTone(status: StreamStatus): Tone {
  if (status === 'open') return 'good';
  if (status === 'connecting' || status === 'reconnecting') return 'warn';
  if (status === 'gap' || status === 'auth_error') return 'bad';
  return 'flat';
}

function detailsOneLine(details: unknown): string {
  if (details === null || details === undefined) return '';
  const text = typeof details === 'string' ? details : JSON.stringify(details);
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}

export function LogsPage() {
  const { t } = useTranslation();

  const [rows, setRows] = useState<LogEventRow[]>([]);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [statusInfo, setStatusInfo] = useState<{ attempt?: number; code?: string; message?: string }>({});
  const [gapMessage, setGapMessage] = useState<string | null>(null);
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(Date.now());
  const [paused, setPaused] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);
  const [droppedCount, setDroppedCount] = useState(0);
  const [sourceFilter, setSourceFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');

  const clientRef = useRef<LogsStreamClient | null>(null);
  const pausedRef = useRef(false);
  const backlogRef = useRef<LogEventRow[]>([]);
  const autoscrollRef = useRef(true);
  const listEndRef = useRef<HTMLDivElement | null>(null);

  pausedRef.current = paused;
  autoscrollRef.current = autoscroll;

  const sources = useSemanticQuery<LogsSourcesData>(['logs-sources'], () => controlApi.logsSources());

  const ensureClient = (): LogsStreamClient => {
    if (!clientRef.current) {
      clientRef.current = new LogsStreamClient();
    }
    return clientRef.current;
  };

  const seenRef = useRef<Set<number>>(new Set());

  const appendRows = (incoming: LogEventRow[]) => {
    // 按 cursor 去重：重放（无游标订阅）与实时尾包会送来同一批事件，不去重即界面重复行 + React key 撞车。
    // 判重与登记必须同步完成——若延后到 effect 再重建集合，集合恒为「可见行子集」，
    // 未渲染的那批就漏判（F17 复核 2026-09-19 实测：延迟重建形态同批帧出 2 组重复 key）。
    const fresh = incoming.filter((row) => !seenRef.current.has(row.cursor));
    if (fresh.length === 0) return;
    for (const row of fresh) seenRef.current.add(row.cursor);
    setRows((current) => {
      const merged = [...current, ...fresh];
      const overflow = merged.length - MAX_ROWS;
      if (overflow > 0) {
        // 与视图同步收缩：被裁出行立即释放判重位，Set 上限恒 ≤ MAX_ROWS。delete 幂等，
        // StrictMode 下 updater 双跑不会失真。
        for (let i = 0; i < overflow; i++) seenRef.current.delete(merged[i].cursor);
        setDroppedCount((count) => count + overflow);
        return merged.slice(overflow);
      }
      return merged;
    });
  };

  const startStream = (after: string | null) => {
    setGapMessage(null);
    ensureClient().start({
      after,
      source: sourceFilter || undefined,
      category: categoryFilter || undefined,
      callbacks: {
        onStatus: (next, info) => {
          setStatus(next);
          setStatusInfo(info ?? {});
        },
        onEvent: (row) => {
          if (pausedRef.current) {
            backlogRef.current.push(row);
            return;
          }
          appendRows([row]);
        },
        onHeartbeat: () => setLastHeartbeatAt(Date.now()),
        onGap: (message) => setGapMessage(message),
      },
    });
  };

  // 进页自动续传：游标取 sessionStorage（无则 null=回放当前保留窗口）。
  useEffect(() => {
    const stored = sessionStorage.getItem(CURSOR_KEY);
    startStream(stored);
    return () => {
      clientRef.current?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 心跳存活指示的秒表。
  useEffect(() => {
    const timer = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // 游标持久化（每行都带 cursor；写 sessionStorage 高频但轻量）。
  useEffect(() => {
    if (rows.length === 0) return;
    const last = rows[rows.length - 1];
    if (last?.cursor !== undefined) sessionStorage.setItem(CURSOR_KEY, String(last.cursor));
  }, [rows]);

  // 恢复暂停时冲积压。
  useEffect(() => {
    if (!paused && backlogRef.current.length > 0) {
      const backlog = backlogRef.current;
      backlogRef.current = [];
      appendRows(backlog);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused]);

  // 自动滚底。
  useEffect(() => {
    if (autoscroll) listEndRef.current?.scrollIntoView({ block: 'end' });
  }, [rows, autoscroll]);

  const heartbeatAge = lastHeartbeatAt === null ? null : nowTick - lastHeartbeatAt;
  const heartbeatAlive = status === 'open' && heartbeatAge !== null && heartbeatAge < HEARTBEAT_STALE_MS;
  const connected = status === 'open' || status === 'connecting' || status === 'reconnecting';

  const stopStream = () => {
    clientRef.current?.stop();
  };

  const clearView = () => {
    seenRef.current.clear();
    setRows([]);
    setDroppedCount(0);
  };

  const resubscribe = () => {
    sessionStorage.removeItem(CURSOR_KEY);
    clearView(); // 重放语义=替换视图；不清行会让同一批事件二次追加成重复行。
    startStream(null); // 用户显式选择：清游标回放当前保留窗口。
  };

  const applyFilters = () => {
    sessionStorage.removeItem(CURSOR_KEY);
    clearView(); // 过滤变更语义=新订阅：从保留窗口回放，避免旧游标与过滤组合误判缺口。
    startStream(null);
  };

  const sourceItems = sources.state.phase === 'ok' ? sources.state.data.items : [];
  const categoryItems = sources.state.phase === 'ok' ? sources.state.data.categories : [];

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader
        title={t('logs.title')}
        actions={
          <>
            <CategoryChip
              label={
                <>
                  {t(`logs.status.${status}`, { attempt: statusInfo.attempt ?? 0 })}
                  {status === 'open' && heartbeatAge !== null && (
                    <span className='ml-1 font-normal opacity-80'>
                      {heartbeatAlive
                        ? t('logs.heartbeatAlive', { seconds: Math.floor(heartbeatAge / 1000) })
                        : t('logs.heartbeatStale')}
                    </span>
                  )}
                </>
              }
              tone={statusTone(status)}
            />
            {connected ? (
              <Button size='sm' variant='outline' onClick={stopStream}>
                <Link2Off className='size-4' />
                {t('logs.disconnect')}
              </Button>
            ) : (
              <Button size='sm' variant='outline' onClick={() => startStream(sessionStorage.getItem(CURSOR_KEY))}>
                <CirclePlay className='size-4' />
                {t('logs.connect')}
              </Button>
            )}
            <Button size='sm' variant='outline' onClick={() => setPaused(!paused)} disabled={!connected}>
              <CirclePause className='size-4' />
              {paused ? t('logs.resume') : t('logs.pause')}
            </Button>
            <Button size='sm' variant='outline' onClick={clearView}>
              <Eraser className='size-4' />
              {t('logs.clear')}
            </Button>
            <Button size='sm' variant={autoscroll ? 'default' : 'outline'} onClick={() => setAutoscroll(!autoscroll)}>
              <ArrowDownToLine className='size-4' />
              {t('logs.autoscroll')}
            </Button>
          </>
        }
      />

      {gapMessage && (
        <div className='flex flex-wrap items-center gap-3 rounded-lg border border-tone-warn tone-face-warn px-4 py-3'>
          <RotateCcw className='size-4 shrink-0 text-tone-warn' />
          <span className='min-w-0 flex-1 fs-body'>{t('logs.gapBanner', { message: gapMessage })}</span>
          <Button size='sm' variant='outline' onClick={resubscribe}>
            {t('logs.resubscribe')}
          </Button>
        </div>
      )}

      {status === 'auth_error' && (
        <div className='flex flex-wrap items-center gap-3 rounded-lg border border-tone-bad tone-face-bad px-4 py-3'>
          <span className='min-w-0 flex-1 fs-body'>
            {t('logs.streamError', { code: statusInfo.code ?? '', message: statusInfo.message ?? '' })}
          </span>
        </div>
      )}

      <div className='flex flex-wrap items-center gap-2'>
        <span className='fs-caption text-muted-foreground'>{t('logs.filters')}</span>
        <select
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value)}
          className='h-8 rounded-md border bg-background px-2 fs-caption'
        >
          <option value=''>{t('logs.allSources')}</option>
          {sourceItems.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <select
          value={categoryFilter}
          onChange={(event) => setCategoryFilter(event.target.value)}
          className='h-8 rounded-md border bg-background px-2 fs-caption'
        >
          <option value=''>{t('logs.allCategories')}</option>
          {categoryItems.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <Button size='sm' variant='secondary' onClick={applyFilters}>
          {t('logs.applyFilters')}
        </Button>
        <span className='ml-auto fs-caption text-muted-foreground'>
          {t('logs.rows', { shown: rows.length, dropped: droppedCount })}
        </span>
      </div>

      <SectionCard
        title={t('logs.streamTitle')}
        description={`${t('logs.cursorLabel', { cursor: clientRef.current?.lastCursor ?? '—' })} · ${t('logs.playbackHint')}`}
      >
        {rows.length === 0 ? (
          <p className='py-6 text-center fs-caption text-muted-foreground'>
            {connected ? t('logs.waiting') : t('logs.idle')}
          </p>
        ) : (
          <div className='flex max-h-[60vh] flex-col overflow-y-auto font-mono fs-caption' aria-live='polite'>
            {rows.map((row) => (
              <div key={row.cursor} className='flex items-start gap-2 border-b py-2 last:border-b-0'>
                <span className='shrink-0 tabular-nums text-muted-foreground'>{formatTime(row.created_at)}</span>
                <CategoryChip label={row.category} tone={CATEGORY_TONE[row.category] ?? 'flat'} className='font-mono' />
                <span className='w-24 shrink-0 truncate text-muted-foreground' title={row.source}>
                  {row.source}
                </span>
                <span className='min-w-0 flex-1 break-words'>
                  {row.message}
                  {row.details !== null && row.details !== undefined && (
                    <span className='text-muted-foreground'> {detailsOneLine(row.details)}</span>
                  )}
                </span>
              </div>
            ))}
            <div ref={listEndRef} />
          </div>
        )}
      </SectionCard>

      <p className='fs-caption leading-relaxed text-muted-foreground'>{t('logs.transportNote')}</p>
    </div>
  );
}
