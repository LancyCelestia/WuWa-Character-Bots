import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { ChevronDown, ChevronUp, Search } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { CategoryChip, PageHeader, Pager, SectionCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import {
  controlApi,
  type KnowledgeCollection,
  type KnowledgeCollectionsData,
  type KnowledgeTerm,
  type KnowledgeTermsData,
} from '@/lib/api-client';
import { formatInt } from '@/lib/format';
import { cn } from '@/lib/utils';

// 知识库页（spec webui-pages2 §1 + §7 C 系增补）：collections chips 行（not_available=灰态
// disabled）+ 居中宽搜索（右侧 total 计数，terms 端点实有 total）+ 等宽 3 列词条卡
// （术语/别名/line-clamp-4 释义/来源 Badge+scope meta）+ Pager（置于网格下方，§7 C9b 差异记录）。
// 搜索 300ms 防抖；切集合/改搜索词重置 page=1；q 变化不重置集合。

const SCOPE_KEYS = ['general', 'kb_doc', 'acg_source', 'emotion_tags', 'scene_tags'];

function isNotFound(message: string): boolean {
  return /HTTP 404/.test(message);
}

function scopeLabel(scope: string, t: (key: string) => string): string {
  return SCOPE_KEYS.includes(scope) ? t(`knowledge.scope.${scope}`) : scope;
}

function TermCard({ item }: { item: KnowledgeTerm }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const scopes = Array.isArray(item.scope) ? item.scope : [item.scope];
  const definition = typeof item.definition === 'string' && item.definition ? item.definition : null;

  return (
    <SectionCard title={<span className='break-words'>{item.term}</span>}>
      <div className='flex flex-col gap-2'>
        {item.aliases.length > 0 && (
          <p className='fs-body text-muted-foreground'>{t('knowledge.aliases', { list: item.aliases.join('、') })}</p>
        )}
        {definition && (
          <p className={cn('fs-body whitespace-pre-line break-words', !expanded && 'line-clamp-4')}>{definition}</p>
        )}
        {definition && definition.length > 96 && (
          <button
            type='button'
            onClick={() => setExpanded((value) => !value)}
            className='flex w-fit items-center gap-1 fs-caption text-primary hover:underline'
          >
            {expanded ? <ChevronUp className='size-3' /> : <ChevronDown className='size-3' />}
            {expanded ? t('knowledge.collapse') : t('knowledge.expand')}
          </button>
        )}
        <div className='flex flex-wrap items-center gap-2'>
          {scopes.map((scope) => (
            <CategoryChip key={scope} label={scopeLabel(scope, t)} tone='flat' />
          ))}
          <Badge variant='outline' className='font-mono'>
            {item.source}
          </Badge>
          {typeof item.chunk_count === 'number' && (
            <span className='fs-caption text-muted-foreground'>{t('knowledge.chunkCount', { count: formatInt(item.chunk_count) })}</span>
          )}
          {typeof item.count === 'number' && (
            <span className='fs-caption text-muted-foreground'>{t('knowledge.memeCount', { count: formatInt(item.count) })}</span>
          )}
          {typeof item.enabled === 'boolean' &&
            (item.enabled ? (
              <Badge variant='success'>{t('knowledge.sourceEnabled')}</Badge>
            ) : (
              <Badge variant='secondary'>{t('knowledge.sourceDisabled')}</Badge>
            ))}
        </div>
      </div>
    </SectionCard>
  );
}

export function KnowledgePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const search = useSearch({ from: '/knowledge' });

  const collections = useSemanticQuery<KnowledgeCollectionsData>(
    ['knowledge', 'collections'],
    () => controlApi.knowledgeCollections()
  );

  const available =
    collections.state.phase === 'ok' ? collections.state.data.items.filter((item) => item.enabled) : [];
  // 默认选中=第一个可用集合；URL 指向可用集合时优先（侧栏子分组深链）。
  const selected =
    search.collection && available.some((item) => item.id === search.collection)
      ? search.collection
      : (available[0]?.id ?? null);

  const [input, setInput] = useState('');
  const [appliedQ, setAppliedQ] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => setAppliedQ(input.trim()), 300);
    return () => clearTimeout(timer);
  }, [input]);

  useEffect(() => {
    setPage(1);
  }, [selected, appliedQ]);

  const terms = useSemanticQuery<KnowledgeTermsData>(
    ['knowledge', 'terms', selected ?? '', appliedQ, page],
    () => controlApi.knowledgeTerms({ collection: selected ?? '', q: appliedQ, page }),
    { enabled: selected !== null }
  );

  const selectCollection = (id: string) => {
    void navigate({ to: '/knowledge', search: { collection: id } });
  };

  // ---- 集合目录层状态（页面级诚实态优先） ----
  if (collections.state.phase === 'loading') {
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('knowledge.title')} subtitle={t('knowledge.subtitle')} />
        <div className='mx-auto flex w-full max-w-2xl items-center gap-3'>
          <Skeleton className='h-9 flex-1' />
        </div>
        <div className='flex flex-wrap gap-2'>
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className='h-8 w-32 rounded-full' />
          ))}
        </div>
        <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Skeleton key={index} className='h-44' />
          ))}
        </div>
      </div>
    );
  }

  if (collections.state.phase === 'error') {
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('knowledge.title')} subtitle={t('knowledge.subtitle')} />
        {isNotFound(collections.state.message) ? (
          <SectionCard title={t('knowledge.notDeployed')}>
            <p className='fs-body text-muted-foreground'>{t('knowledge.notDeployedHint')}</p>
          </SectionCard>
        ) : (
          <SemanticState state={collections.state} onRetry={collections.refetch} />
        )}
      </div>
    );
  }

  if (collections.state.phase === 'unavailable' || collections.state.phase === 'not_provisioned' || collections.state.phase === 'auth') {
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('knowledge.title')} subtitle={t('knowledge.subtitle')} />
        <SemanticState state={collections.state} onRetry={collections.refetch} />
      </div>
    );
  }

  // ---- 集合目录 ok：全部数据源未启用 → 页面级诚实态（说明启用方式一句话） ----
  if (available.length === 0) {
    return (
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
        <PageHeader title={t('knowledge.title')} subtitle={t('knowledge.subtitle')} />
        <SectionCard title={t('knowledge.allDisabled')} description={t('knowledge.allDisabledHint')}>
          <div className='flex flex-wrap gap-2'>
            {collections.state.data.items.map((item: KnowledgeCollection) => (
              <span key={item.id} className='inline-flex'>
                <CategoryChip label={`${item.name} · ${t('knowledge.notEnabled')}`} tone='flat' className='opacity-60' />
              </span>
            ))}
          </div>
        </SectionCard>
      </div>
    );
  }

  const termsData = terms.state.phase === 'ok' ? terms.state.data : null;

  return (
    <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
      <PageHeader title={t('knowledge.title')} subtitle={t('knowledge.subtitle')} />

      {/* 搜索框：居中宽（spec §1.1），右侧 total 计数（§7 C2，terms 实有 total） */}
      <div className='mx-auto flex w-full max-w-2xl items-center gap-3'>
        <div className='relative flex-1'>
          <Search className='pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground' />
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={t('knowledge.searchPlaceholder')}
            className='h-9 w-full rounded-md border bg-transparent pl-6 pr-2 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]'
            spellCheck={false}
          />
        </div>
        {termsData && (
          <span className='whitespace-nowrap fs-caption text-muted-foreground'>
            {t('knowledge.total', { count: formatInt(termsData.total) })}
          </span>
        )}
      </div>

      {/* 集合 chips 行：可用=可点（选中=品牌色），not_available=灰态 disabled（附「未启用」标） */}
      <div className='flex flex-wrap items-center gap-2'>
        {collections.state.data.items.map((item) => (
          <button
            key={item.id}
            type='button'
            disabled={!item.enabled}
            onClick={() => selectCollection(item.id)}
            className='rounded-full disabled:pointer-events-none disabled:opacity-50'
          >
            <CategoryChip
              label={item.enabled ? item.name : `${item.name} · ${t('knowledge.notEnabled')}`}
              tone={item.id === selected ? 'brand' : 'flat'}
            />
          </button>
        ))}
      </div>

      {/* 词条区状态 */}
      {terms.state.phase === 'loading' ? (
        <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <Skeleton key={index} className='h-44' />
          ))}
        </div>
      ) : terms.state.phase === 'error' ? (
        isNotFound(terms.state.message) ? (
          <SectionCard title={t('knowledge.notDeployed')}>
            <p className='fs-body text-muted-foreground'>{t('knowledge.notDeployedHint')}</p>
          </SectionCard>
        ) : (
          <SemanticState state={terms.state} onRetry={terms.refetch} />
        )
      ) : terms.state.phase === 'unavailable' ? (
        <SemanticState state={terms.state} onRetry={terms.refetch} />
      ) : termsData && termsData.items.length === 0 ? (
        <SectionCard
          title={appliedQ ? t('knowledge.emptySearch', { query: appliedQ }) : t('knowledge.emptyCollection')}
        >
          {appliedQ && (
            <div className='flex justify-center py-4'>
              <Button
                variant='outline'
                size='sm'
                onClick={() => {
                  setInput('');
                  setAppliedQ('');
                }}
              >
                {t('knowledge.clearSearch')}
              </Button>
            </div>
          )}
        </SectionCard>
      ) : (
        termsData && (
          <>
            <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
              {termsData.items.map((item) => (
                <TermCard key={`${item.term}:${item.source}`} item={item} />
              ))}
            </div>
            <Pager
              page={termsData.page}
              pageSize={termsData.page_size}
              total={termsData.total}
              onPageChange={setPage}
              labels={{
                prev: t('knowledge.prevPage'),
                next: t('knowledge.nextPage'),
                info: ([start, end], total) => t('knowledge.pageInfo', { start, end, total: formatInt(total) }),
              }}
            />
          </>
        )
      )}
    </div>
  );
}
