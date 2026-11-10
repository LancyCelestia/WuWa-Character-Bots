// 施工中标注（用户验收硬要求）：确实不可用的功能必须在界面内出现
// 「暂时在施工中无法使用」原文，不得只写「未接入」或留空。
// 判据由各页从**真实后端字段**推导（错误码 / collector_status / measurement.reason），
// 不在这里硬编码「某页永远施工中」——后端接上线后标注会自己消失。
import { Hammer } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function UnderConstruction({ detail }: { detail?: string }) {
  const { t } = useTranslation();
  return (
    <div role='status' className='flex items-start gap-3 rounded-lg border border-dashed p-4'>
      <Hammer className='mt-1 size-4 shrink-0 text-muted-foreground' aria-hidden />
      <div className='min-w-0'>
        <p className='fs-card'>{t('state.underConstruction')}</p>
        {detail && <p className='mt-1 fs-caption text-muted-foreground'>{detail}</p>}
      </div>
    </div>
  );
}

export function UnderConstructionBadge({ detail }: { detail?: string }) {
  const { t } = useTranslation();
  return (
    <span
      title={detail}
      className='inline-block rounded-md border border-dashed px-2 py-1 fs-caption text-muted-foreground'
    >
      {t('state.underConstruction')}
    </span>
  );
}
