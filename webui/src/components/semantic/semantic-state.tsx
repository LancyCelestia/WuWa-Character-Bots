// 统一数据态呈现：loading 骨架 / 暂无数据（source_unavailable 语义态，如实降级非报错）/
// 未配置令牌（503 control_plane_not_provisioned → 引导设置）/ 令牌无效（401/403）/
// 被限速（429 → 有自己的一档，绝不冒充「加载失败」）/ 加载失败。
// reason 码的人话**不在本文件判定**：白名单与取词收口于 `@/lib/semantics` 的 describeReason；
// 骨架闸收口于 `@/lib/data-state` 的 shouldShowSkeleton；429 措辞收口于 `@/lib/rate-limit`。
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { DatabaseZap, Hourglass, KeyRound, RotateCcw, ServerOff, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { DataState } from '@/hooks/use-semantic-query';
import { shouldShowSkeleton } from '@/lib/data-state';
import { describeRateLimit } from '@/lib/rate-limit';
import { describeReason } from '@/lib/semantics';

/**
 * 数据态卡片的材质与圆角（W13-V2）。
 *
 * 这些卡片**永远嵌在别人的卡片/面板里**（总览的统计卡、插件页的 SectionCard…），
 * 外层是 `rounded-lg`=18px + `p-4`=16px。卡片套卡片时内层必须落瓦片档 14：
 * 严格同心式会算出 2px，那是三档之外的第四值（门禁只认 14/18/30），
 * 所以 P1 设计席与 V 席都点名「卡片内部一律 14」。改之前内外同为 18，
 * 实测 DOM：外层 354×197 r=18 p=16 → 内层 320×122 r=18，看着像两个圆角矩形贴合。
 *
 * `shadow-none`：内层不该有悬浮厚度——两层投影叠起来，加载态比数据态还「重」。
 */
const STATE_CARD = 'rounded-md shadow-none';

/** 打开设置面板（AppShell 挂载的 SettingsDialog 监听同事件）。 */
export function openSettings(): void {
  window.dispatchEvent(new CustomEvent('webui:open-settings'));
}

export function SemanticState({ state, onRetry, children }: { state: DataState<unknown>; onRetry?: () => void; children?: ReactNode }) {
  const { t } = useTranslation();

  if (shouldShowSkeleton(state.phase)) {
    return (
      <Card className={STATE_CARD}>
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
      <Card className={STATE_CARD}>
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
      <Card className={STATE_CARD}>
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

  if (state.phase === 'rate_limited') {
    // 429 单列一档：这是「等一下就好」，不是「坏了」。文案里**绝不出现「加载失败」**——
    // 那四个字会诱导用户点重试，而重试是唯一会延长锁定的动作（控制面按来源累计失败）。
    // 这里**不放重试按钮**：冷却期内它是死控件，而各查询都带 refetchInterval（30/60 秒），
    // 到点会自己再来——按钮只会诱使用户在窗口内戳它。
    const copy = describeRateLimit(t, state.retryAfterSeconds);
    return (
      <Card className={STATE_CARD}>
        <CardContent className='flex flex-col items-center gap-3 py-6 text-center'>
          <Hourglass className='size-8 text-tone-warn' />
          <div className='fs-card'>{copy.title}</div>
          <p className='max-w-md fs-caption text-muted-foreground'>{copy.hint}</p>
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'unavailable' || state.phase === 'disabled') {
    // `disabled` = 查询被 `enabled: false` 关掉，永远不会自己来数据。骨架条描的是
    // 「正在来」，这里要描「没有」——两者共用「暂无数据」这一档，不新增词条。
    const reason = state.phase === 'unavailable' ? state.reason : null;
    return (
      <Card className={STATE_CARD}>
        <CardContent className='flex flex-col items-center gap-2 py-6 text-center'>
          <DatabaseZap className='size-8 text-muted-foreground' />
          <div className='fs-card'>{t('state.noData')}</div>
          {reason && <p className='fs-caption text-muted-foreground'>{describeReason(reason, t)}</p>}
        </CardContent>
      </Card>
    );
  }

  if (state.phase === 'error') {
    return (
      <Card className={STATE_CARD}>
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

  // Existing consumers render successful content themselves; wrappers may pass it.
  return children ?? null;
}
