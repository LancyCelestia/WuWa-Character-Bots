// 自动降级提示条（UI3 追加二「降级要让用户看见并可以覆盖」）。
//
// 只在**真的降了**且**用户还没覆盖**时出现；一行中文说明 + 两个动作：
//   「恢复默认强度」→ 本机记住「我不要降级」（指纹随机器/网络档变化，换环境会重新征求）
//   「去调外观」→ 跳到外观工作室
// 不抢焦点、不遮内容（就是内容区上方的一条普通行），关掉后不再出现。
import { useTranslation } from 'react-i18next';
import { Link } from '@tanstack/react-router';
import { AlertTriangle, X } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useAppearance } from '@/lib/appearance/context';

export function AppearanceBanner() {
  const { t } = useTranslation();
  const { degraded, overridden, setOverridden } = useAppearance();
  const [dismissed, setDismissed] = useState(false);

  if (overridden || degraded.notes.length === 0 || dismissed) return null;

  return (
    <div
      role='status'
      className='flex flex-wrap items-center gap-3 rounded-lg border border-tone-warn/40 bg-card px-4 py-2'
    >
      <AlertTriangle aria-hidden className='size-4 shrink-0 text-tone-warn' />
      <p className='min-w-0 flex-1 fs-caption text-muted-foreground'>{degraded.notes.join('；')}</p>
      <div className='flex shrink-0 items-center gap-2'>
        <Button size='sm' variant='outline' onClick={() => setOverridden(true)}>
          {t('appearance.banner.restore')}
        </Button>
        <Link to='/appearance' className='fs-caption text-primary underline-offset-4 hover:underline'>
          {t('appearance.banner.open')}
        </Link>
        <Button
          size='icon-sm'
          variant='ghost'
          aria-label={t('appearance.banner.dismiss')}
          onClick={() => setDismissed(true)}
        >
          <X className='size-4' />
        </Button>
      </div>
    </div>
  );
}
