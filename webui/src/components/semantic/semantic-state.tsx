// 统一数据态呈现：loading 骨架 / 暂无数据（source_unavailable 语义态，如实降级非报错）/
// 未配置令牌（503 control_plane_not_provisioned → 引导设置）/ 令牌无效（401/403）/ 加载失败。
// reason 码的人话**不在本文件判定**：白名单与取词收口于 `@/lib/semantics` 的 describeReason。
import { useTranslation } from 'react-i18next';
import { DatabaseZap, KeyRound, RotateCcw, ServerOff, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { DataState } from '@/hooks/use-semantic-query';
import { describeReason } from '@/lib/semantics';

/** 打开设置面板（AppShell 挂载的 SettingsDialog 监听同事件）。 */
export function openSettings(): void {
  window.dispatchEvent(new CustomEvent('webui:open-settings'));
}

export function SemanticState({ state, onRetry }: { state: DataState<unknown>; onRetry?: () => void }) {
  const { t } = useTranslation();

  if (state.phase === 'loading') {
    return (
      <Card>
        <CardContent className='flex flex-col gap-3'>
          <Skeleton className='h-4 w-1/3' />
          <Skeleton className='h-8 w-1/2' />
          <Skeleton className='h-4 w-2/3' />
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'not_provisioned') {
    return (
      <Card>
        <CardContent className='flex flex-col items-center gap-3 py-6 text-center'>
          <ServerOff className='size-8 text-muted-foreground' />
          <div className='fs-card'>{t('state.notProvisioned')}</div>
          <p className='max-w-md fs-caption text-muted-foreground'>{t('state.notProvisionedHint')}</p>
          <Button size='sm' variant='outline' onClick={openSettings}>
            <KeyRound className='size-4' />
            {t('settings.open')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'auth') {
    return (
      <Card>
        <CardContent className='flex flex-col items-center gap-3 py-6 text-center'>
          <KeyRound className='size-8 text-tone-warn' />
          <div className='fs-card'>{t('state.authFailed')}</div>
          <p className='max-w-md fs-caption text-muted-foreground'>{t('state.authFailedHint')}</p>
          <Button size='sm' variant='outline' onClick={openSettings}>
            <KeyRound className='size-4' />
            {t('settings.open')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'unavailable') {
    return (
      <Card>
        <CardContent className='flex flex-col items-center gap-2 py-6 text-center'>
          <DatabaseZap className='size-8 text-muted-foreground' />
          <div className='fs-card'>{t('state.noData')}</div>
          <p className='fs-caption text-muted-foreground'>{describeReason(state.reason, t)}</p>
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'error') {
    return (
      <Card>
        <CardContent className='flex flex-col items-center gap-3 py-6 text-center'>
          <TriangleAlert className='size-8 text-destructive' />
          <div className='fs-card'>{t('state.loadFailed')}</div>
          <p className='max-w-md fs-caption text-muted-foreground'>{state.message}</p>
          {onRetry && (
            <Button size='sm' variant='outline' onClick={onRetry}>
              <RotateCcw className='size-4' />
              {t('state.retry')}
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  // phase === 'ok'：有数据的正常渲染不经过本组件。
  return null;
}
