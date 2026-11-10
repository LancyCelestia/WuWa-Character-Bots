import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { UserRoundCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PageHeader, SectionCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { ApiError } from '@/lib/api-client';
import { centerApi, type PersonaItem, type PersonaState } from '@/lib/control-center';

/**
 * 人格页：读取运行时切换态，并允许 super_admin 切换。
 *
 * 口径（与后端 /api/v1/persona 同源）：
 * - 切换写的是 runtime settings 的 persona_override，下一轮现读即生效，不重启；
 * - active_override 为空 = 跟随主人格（registry 里 is_main 的那一格）；
 * - 视觉主题不随人格变化：外观住在 appearance，本页只动人设内容。
 * 未在册的 id 后端 404；expected_current 不符 409，本页据此提示刷新，不静默覆盖。
 */
function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

export function PersonaPage() {
  const { t } = useTranslation();
  const query = useSemanticQuery<PersonaState>(['center', 'persona'], centerApi.persona);
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  const state = query.state.phase === 'ok' ? query.state.data : null;

  async function switchTo(profileId: string) {
    if (!state) return;
    setBusy(true);
    setNotice(null);
    try {
      await centerApi.setPersona(profileId, state.active_override);
      setPending(null);
      setNotice({ kind: 'ok', text: t('persona.switched') });
      await query.refetch();
    } catch (error) {
      setNotice({ kind: 'error', text: describeError(error) });
    } finally {
      setBusy(false);
    }
  }

  function renderCard(item: PersonaItem) {
    const isEffective = state?.effective === item.profile_id;
    const isPending = pending === item.profile_id;
    return (
      <SectionCard
        key={item.profile_id}
        title={
          <span className='flex min-w-0 flex-wrap items-center gap-2'>
            <span className='truncate'>{item.display_name}</span>
            <Badge variant='outline' className='font-mono'>{item.profile_id}</Badge>
            {item.is_main && <Badge variant='secondary'>{t('persona.main')}</Badge>}
            {isEffective && <Badge variant='success'>{t('persona.active')}</Badge>}
          </span>
        }
        action={
          isEffective ? null : isPending ? (
            <span className='flex items-center gap-2'>
              <Button size='sm' disabled={busy} onClick={() => void switchTo(item.profile_id)}>
                {busy ? t('persona.switching') : t('persona.confirm')}
              </Button>
              <Button size='sm' variant='ghost' disabled={busy} onClick={() => setPending(null)}>
                {t('persona.cancel')}
              </Button>
            </span>
          ) : (
            <Button size='sm' variant='outline' onClick={() => setPending(item.profile_id)}>
              {t('persona.switch')}
            </Button>
          )
        }
      >
        <p className='fs-body text-muted-foreground'>
          {item.is_main ? t('persona.mainHint') : t('persona.itemHint')}
        </p>
      </SectionCard>
    );
  }

  return (
    <div className='flex w-full flex-col gap-6'>
      <PageHeader title={t('persona.title')} subtitle={t('persona.subtitle')} />

      {notice && (
        <p
          role='status'
          className={notice.kind === 'error' ? 'fs-body text-danger' : 'fs-body text-muted-foreground'}
        >
          {notice.text}
        </p>
      )}

      {query.state.phase === 'loading' ? (
        <div className='surface flex flex-col gap-3 rounded-lg p-4'>
          <div className='h-6 w-40 animate-pulse rounded-lg bg-accent' />
          <div className='h-24 animate-pulse rounded-lg bg-accent' />
        </div>
      ) : query.state.phase !== 'ok' ? (
        <SemanticState state={query.state} onRetry={query.refetch} />
      ) : (
        <>
          <SectionCard
            title={
              <span className='flex items-center gap-2'>
                <UserRoundCheck className='size-4' aria-hidden />
                {t('persona.effective')}
              </span>
            }
            description={t('persona.hotHint')}
          >
            <div className='flex flex-wrap items-baseline gap-3'>
              <span className='fs-page'>{state?.effective}</span>
              {state?.active_override ? (
                <Badge variant='outline'>{t('persona.overrideOn')}</Badge>
              ) : (
                <Badge variant='secondary'>{t('persona.followMain')}</Badge>
              )}
            </div>
            <p className='mt-2 fs-caption text-muted-foreground'>{t('persona.visualUnchanged')}</p>
          </SectionCard>

          <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
            {state?.items.length ? (
              state.items.map(renderCard)
            ) : (
              <p className='fs-body text-muted-foreground'>{t('persona.empty')}</p>
            )}
          </div>

          {state?.active_override && (
            <div>
              <Button variant='outline' disabled={busy} onClick={() => void switchTo('')}>
                {t('persona.followMainAction')}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
