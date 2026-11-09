// 参数设置页（D 席）：807 枚配置键的**全量**中文说明 + 按类型自动选控件 + 三拍写入。
//
// 三条硬判据（用户原话拆出来的）：
//   ① 「彻底涵盖所有功能和插件」→ 表里必须是后端 `Config.model_fields` 的**每一枚**键，
//      不是挑出来的常用项。判据落在 `lib/config-presentation.test.ts`：逐个键名搜一遍全命中。
//   ② 「能自定义的全部开放参数设置」→ 能写的就给真控件；不能写的**必须说清为什么**
//      （热改 / 需重启 / 仅展示），而不是画一个假开关。
//   ③ 「所有参数设置必须给中文的详细标题和说明」→ T1 手写讲清「调大了会怎样、调小了会怎样」，
//      T2/T3 由键名词表 + 文档作用列推导，绝不回落到「运行时白名单参数」。
//
// 写面纪律：只有 `scope === 'hot'` 且后端 `can_write` 为真的键才可提交；提交必经
// preview → 确认 → set（见 `components/config/config-preview-dialog.tsx`）。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { ApiError } from '@/lib/api-client';
import { centerApi, pendingReceipt, type ConfigRow } from '@/lib/control-center';
import {
  CONFIG_FIELDS,
  GROUP_BUCKETS,
  KIND_COUNTS,
  SCOPE_COUNTS,
  SCOPE_HINT,
  TIER_COUNTS,
  resolveRows,
  searchFields,
  type ResolvedRow,
} from '@/lib/config-presentation';
import { ConfigFieldRow } from '@/components/config/config-field-row';
import { ConfigPreviewDialog, type PreviewPayload, type SubmitState } from '@/components/config/config-preview-dialog';

/** 一次渲染多少行（807 行全上 DOM 在 2C2G 机器与手机上都会卡；滚动到底再补一批）。 */
const PAGE_SIZE = 40;

type Drafts = Record<string, unknown>;

export function ConfigPage() {
  const query = useSemanticQuery<{ items: ConfigRow[] }>(['center', 'config', 'catalog'], centerApi.catalog);
  const [search, setSearch] = useState('');
  const [groupId, setGroupId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [submit, setSubmit] = useState<SubmitState | null>(null);
  const [notice, setNotice] = useState('');
  const sentinel = useRef<HTMLDivElement>(null);

  const live = query.state.phase === 'ok' ? query.state.data.items : [];
  const rows = useMemo(() => resolveRows(live), [live]);
  const rowByKey = useMemo(() => new Map(rows.map((row) => [row.field.key, row])), [rows]);

  // 搜索永远跨全部分组（硬判据：任何一枚键都得搜得到）；选分组只在没搜索词时收窄。
  const matches = useMemo(() => {
    const found = searchFields(search, search.trim() ? undefined : groupId ?? undefined);
    // 静态表给「有哪些键」，live 行给「现在值多少、能不能写」——两者按 key 对齐。
    return found
      .map((field) => rowByKey.get(field.key))
      .filter((row): row is ResolvedRow => row !== undefined);
  }, [search, groupId, rowByKey]);

  useEffect(() => {
    setVisible(PAGE_SIZE);
  }, [search, groupId]);

  // 增量渲染：哨兵可见就补一批（IntersectionObserver，零依赖、不监听 scroll）。
  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setVisible((current) => (current >= matches.length ? current : current + PAGE_SIZE));
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [matches.length]);

  const setDraft = useCallback((key: string, value: unknown) => {
    setDrafts((current) => ({ ...current, [key]: value }));
    setErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  const clearDraft = useCallback((key: string) => {
    setDrafts((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }, []);

  /** 第一拍：预览。值类型不对会在这里被后端拒掉，不落库。 */
  const runPreview = useCallback(
    async (row: ResolvedRow) => {
      const key = row.field.key;
      const next = drafts[key];
      setBusyKey(key);
      setNotice('');
      setSubmit(null);
      try {
        const echoed = await centerApi.preview(key, next, row.version);
        setPreview({
          row,
          next,
          previewValue: echoed.value,
          version: echoed.version ?? row.version,
          sensitive: Boolean(echoed.sensitive) || row.sensitive,
          phase: 'ready',
        });
      } catch (error) {
        setErrors((current) => ({ ...current, [key]: describeError(error) }));
      } finally {
        setBusyKey(null);
      }
    },
    [drafts],
  );

  /** 第三拍：提交（带 Idempotency-Key，见 centerApi.set）。 */
  const runSubmit = useCallback(async () => {
    if (!preview) return;
    const key = preview.row.field.key;
    setSubmit({ phase: 'submitting', message: '正在提交…' });
    try {
      const receipt = await centerApi.set(key, preview.next, preview.version);
      setSubmit({ phase: 'done', message: pendingReceipt(receipt) });
      clearDraft(key);
      query.refetch();
    } catch (error) {
      setSubmit({ phase: 'failed', message: describeError(error) });
    }
  }, [preview, clearDraft, query]);

  /** 撤销覆盖：同样走 preview（reset 形态）再提交。 */
  const runReset = useCallback(
    async (row: ResolvedRow) => {
      const key = row.field.key;
      setBusyKey(key);
      setNotice('');
      try {
        await centerApi.reset(key, row.version);
        setNotice(`${row.field.title}：已撤销运行时覆盖，回落 .env / 代码默认值。`);
        clearDraft(key);
        query.refetch();
      } catch (error) {
        setErrors((current) => ({ ...current, [key]: describeError(error) }));
      } finally {
        setBusyKey(null);
      }
    },
    [clearDraft, query],
  );

  const shown = matches.slice(0, visible);

  return (
    <div className='flex flex-col gap-4'>
      <PageHeader
        title='参数设置'
        subtitle='后端声明的每一枚配置键都在这里：中文标题、详细说明、按类型自动选的控件。可见不等于可写——不能写的会说明原因。'
        actions={
          <Button variant='outline' disabled={busyKey !== null} onClick={() => query.refetch()}>
            <RefreshCw className='size-4' />
            刷新
          </Button>
        }
      />

      {/* 覆盖度与写面总览：数字全部现算，不手写（手写一次就过期一次）。 */}
      <div className='surface flex flex-wrap items-center gap-2 rounded-lg p-3'>
        <Badge variant='default'>
          <SlidersHorizontal className='size-4' />
          共 {CONFIG_FIELDS.length} 键
        </Badge>
        <Badge variant='success'>可热改 {SCOPE_COUNTS.hot}</Badge>
        <Badge variant='secondary'>需重启 {SCOPE_COUNTS.restart}</Badge>
        <Badge variant='outline'>仅展示 {SCOPE_COUNTS['env-only']}</Badge>
        <span className='fs-caption text-muted-foreground'>
          说明覆盖：手写 {TIER_COUNTS.T1} · 自动 {TIER_COUNTS.T2} · 仅展示 {TIER_COUNTS.T3} ·
          控件 {Object.values(KIND_COUNTS).filter((n) => n > 0).length} 种
        </span>
      </div>

      <div className='grid gap-4 lg:grid-cols-4'>
        {/* 分组导航 */}
        <nav aria-label='配置分组' className='surface flex flex-col gap-1 rounded-lg p-2 lg:col-span-1'>
          <button
            type='button'
            className={`flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left fs-body ${
              groupId === null && !search.trim() ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
            }`}
            onClick={() => setGroupId(null)}
          >
            <span>全部</span>
            <span className='fs-caption tabular-nums'>{CONFIG_FIELDS.length}</span>
          </button>
          {GROUP_BUCKETS.map((group) => (
            <button
              key={group.id}
              type='button'
              className={`flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left fs-body ${
                groupId === group.id && !search.trim() ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
              }`}
              onClick={() => setGroupId(group.id)}
              title={group.desc}
            >
              <span className='min-w-0 truncate'>{group.name}</span>
              <span className='fs-caption tabular-nums'>{group.count}</span>
            </button>
          ))}
        </nav>

        {/* 搜索 + 列表 */}
        <div className='surface flex min-w-0 flex-col gap-3 rounded-lg p-3 lg:col-span-3'>
          <label className='flex items-center gap-2 rounded-md border bg-background px-3 py-2'>
            <Search className='size-4 shrink-0 text-muted-foreground' />
            <span className='sr-only'>搜索参数</span>
            <input
              className='w-full min-w-0 bg-transparent fs-body outline-none'
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder='搜索键名 / 中文标题 / 说明 / 分组（全部 807 枚键都能搜到）'
            />
            {search && (
              <button type='button' className='fs-caption text-muted-foreground' onClick={() => setSearch('')}>
                清除
              </button>
            )}
          </label>

          <p className='fs-caption text-muted-foreground'>
            {search.trim()
              ? `全库搜索「${search.trim()}」命中 ${matches.length} 枚`
              : groupId
                ? `分组内 ${matches.length} 枚`
                : `共 ${matches.length} 枚（已渲染 ${shown.length}）`}
            {' · '}
            {SCOPE_HINT.hot}
          </p>

          {notice && (
            <p role='status' className='flex items-start gap-2 rounded-md border bg-accent p-3 fs-body'>
              <ShieldCheck className='mt-1 size-4 shrink-0 text-tone-good' />
              <span className='min-w-0 break-words'>{notice}</span>
            </p>
          )}

          <SemanticState state={query.state} onRetry={query.refetch}>
            <div className='surface-flat rounded-md'>
              {shown.map((row) => {
                const key = row.field.key;
                const dirty = key in drafts;
                return (
                  <ConfigFieldRow
                    key={key}
                    row={row}
                    draft={drafts[key]}
                    dirty={dirty}
                    expanded={expanded === key}
                    busy={busyKey === key}
                    error={errors[key]}
                    onToggleExpand={() => setExpanded((current) => (current === key ? null : key))}
                    onDraft={(next) => setDraft(key, next)}
                    onPreview={() => void runPreview(row)}
                    onReset={() => void runReset(row)}
                  />
                );
              })}
              {shown.length === 0 && (
                <p className='p-6 fs-body text-muted-foreground'>
                  没有匹配的键。搜索是跨全库的——如果这枚键确实存在，说明展示表漏了，那是缺陷不是筛选。
                </p>
              )}
              {visible < matches.length && (
                <div ref={sentinel} className='flex items-center justify-center p-4'>
                  <Button variant='outline' onClick={() => setVisible((current) => current + PAGE_SIZE)}>
                    继续加载（还有 {matches.length - shown.length} 枚）
                  </Button>
                </div>
              )}
            </div>
          </SemanticState>
        </div>
      </div>

      <ConfigPreviewDialog
        payload={preview}
        submit={submit}
        onConfirm={() => void runSubmit()}
        onCancel={() => {
          setPreview(null);
          setSubmit(null);
        }}
        onClose={() => {
          setPreview(null);
          setSubmit(null);
          void query.refetch();
        }}
      />
    </div>
  );
}

/** 错误人话：409 是版本冲突（要重新读），422 是值没过校验，403 是身份不够。 */
function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return `${error.message}（版本已变，请刷新后重试）`;
    if (error.status === 422) return `${error.message}（值没通过后端校验）`;
    if (error.status === 403) return `${error.message}（当前身份没有写权限）`;
    if (error.status === 503) return `${error.message}（配置服务或存储暂不可用）`;
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return '操作失败，未确认写入。';
}

/** 供路由与其它页面复用的键表（避免它们各自再抄一份 807 键）。 */
export { CONFIG_FIELDS as CONFIG_KEYS };
