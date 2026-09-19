// 轻量设置面板：baseURL + 双 token 本地录入。
// 控制面无登录端点（auth.py：Bearer 只认 Authorization 头，禁 URL/query 传递）——
// 令牌由管理员生成后自行粘贴进本机 localStorage；明文不回显（保存后输入框清空占位「已保存」）。
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, KeyRound, Settings, Trash2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getApiToken, getBaseUrl, setApiToken, setBaseUrl, validateBaseUrl } from '@/lib/api-client';

function tokenField({
  label,
  kind,
  savedHint,
}: {
  label: string;
  kind: 'admin' | 'ro';
  savedHint: string;
}) {
  return { label, kind, savedHint };
}

export function SettingsDialog() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrlState] = useState('');
  const [adminToken, setAdminToken] = useState('');
  const [roToken, setRoToken] = useState('');
  const [showTokens, setShowTokens] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [baseUrlError, setBaseUrlError] = useState<string | null>(null);
  // 本机已存令牌的「有没有」快照：驱动占位符与清除按钮。读 localStorage 不是可观察状态，
  // 不进 state 的话清除后界面不会重绘（按钮还在、提示还写「已保存」）。
  const [hasStored, setHasStored] = useState({ admin: false, ro: false });

  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener('webui:open-settings', handler);
    return () => window.removeEventListener('webui:open-settings', handler);
  }, []);

  useEffect(() => {
    if (open) {
      setBaseUrlState(getBaseUrl());
      setAdminToken('');
      setRoToken('');
      setBaseUrlError(null);
      setHasStored({ admin: Boolean(getApiToken('admin')), ro: Boolean(getApiToken('ro')) });
    }
  }, [open]);

  // SECWEB Minor-2：保存前校验 baseUrl 白名单（同源 / 127.0.0.1 / localhost，任意端口）。
  // 非法 host 或解析失败 → 拒绝保存并红字提示，不落盘不刷新。
  // 文案内联双语硬编码：locales 文件不在本改动域（披露于 progress-HARDEN.md）。
  const baseUrlErrorText = (reason: 'invalid_url' | 'bad_scheme' | 'host_not_allowed'): string => {
    if (reason === 'invalid_url') return 'URL 无法解析，请检查格式 · Could not parse URL';
    if (reason === 'bad_scheme') return '仅支持 http(s):// 地址 · http(s) URLs only';
    return '仅允许本机地址：同源 / 127.0.0.1 / localhost（任意端口）· Loopback addresses only';
  };

  const save = () => {
    const verdict = validateBaseUrl(baseUrl);
    if (!verdict.ok) {
      setBaseUrlError(baseUrlErrorText(verdict.reason));
      return;
    }
    setBaseUrlError(null);
    setBaseUrl(verdict.value);
    // 令牌输入框打开时恒为空（占位符=「已保存」语义）：留空即保持原值，绝不把空串写回去清空凭据。
    if (adminToken.trim()) setApiToken(adminToken.trim(), 'admin');
    if (roToken.trim()) setApiToken(roToken.trim(), 'ro');
    setSavedFlash(true);
    setTimeout(() => window.location.reload(), 600); // baseURL/令牌生效最干净的方式：整页刷新。
  };

  // 保存时留空=保持原值（防静默清空凭据）；清除走显式按钮——两者不能混在一条路径上。
  const clearStoredToken = (kind: 'admin' | 'ro') => {
    setApiToken(null, kind);
    setHasStored((current) => ({ ...current, [kind]: false }));
    if (kind === 'admin') setAdminToken('');
    else setRoToken('');
  };

  const fields = [
    tokenField({ label: t('settings.adminToken'), kind: 'admin' as const, savedHint: t('settings.adminTokenHint') }),
    tokenField({ label: t('settings.roToken'), kind: 'ro' as const, savedHint: t('settings.roTokenHint') }),
  ];

  if (!open) return null;

  return (
    <div
      className='fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4'
      onClick={() => setOpen(false)}
    >
      <div
        className='max-h-[90svh] w-full max-w-lg overflow-y-auto rounded-xl border bg-background p-6 shadow-lg'
        onClick={(event) => event.stopPropagation()}
      >
        <div className='mb-4 flex items-center justify-between'>
          <h2 className='flex items-center gap-2 fs-page'>
            <Settings className='size-4' />
            {t('settings.title')}
          </h2>
          <Button variant='ghost' size='icon-sm' onClick={() => setOpen(false)} aria-label={t('settings.close')}>
            <X className='size-4' />
          </Button>
        </div>

        <div className='flex flex-col gap-4 fs-body'>
          <div className='flex flex-col gap-2'>
            <label htmlFor='webui-base-url' className='font-medium'>
              {t('settings.baseUrl')}
            </label>
            <input
              id='webui-base-url'
              value={baseUrl}
              onChange={(event) => setBaseUrlState(event.target.value)}
              placeholder={t('settings.baseUrlPlaceholder')}
              className='h-9 rounded-md border bg-transparent px-3 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]'
              spellCheck={false}
            />
            <p className='fs-caption text-muted-foreground'>{t('settings.baseUrlHint')}</p>
            {baseUrlError && <p className='fs-caption text-destructive'>{baseUrlError}</p>}
          </div>

          {fields.map((field) => (
            <div key={field.kind} className='flex flex-col gap-2'>
              <label htmlFor={`webui-token-${field.kind}`} className='font-medium'>
                {field.label}
              </label>
              <div className='flex gap-2'>
                <input
                  id={`webui-token-${field.kind}`}
                  type={showTokens ? 'text' : 'password'}
                  value={field.kind === 'admin' ? adminToken : roToken}
                  onChange={(event) =>
                    field.kind === 'admin' ? setAdminToken(event.target.value) : setRoToken(event.target.value)
                  }
                  placeholder={hasStored[field.kind] ? t('settings.tokenSavedPlaceholder') : t('settings.tokenPlaceholder')}
                  className='h-9 flex-1 rounded-md border bg-transparent px-3 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]'
                  spellCheck={false}
                  autoComplete='off'
                />
                <Button variant='outline' size='icon' onClick={() => setShowTokens((value) => !value)} aria-label={t('settings.toggleShow')}>
                  {showTokens ? <EyeOff className='size-4' /> : <Eye className='size-4' />}
                </Button>
                {hasStored[field.kind] && (
                  <Button variant='outline' size='icon' onClick={() => clearStoredToken(field.kind)} aria-label={t('settings.clearToken')}>
                    <Trash2 className='size-4' />
                  </Button>
                )}
              </div>
              <p className='fs-caption text-muted-foreground'>{field.savedHint}</p>
            </div>
          ))}

          <p className='rounded-md border bg-muted/40 p-3 fs-caption text-muted-foreground'>
            {t('settings.note')}
          </p>

          <div className='flex items-center justify-end gap-2'>
            {savedFlash && <span className='fs-caption text-muted-foreground'>{t('settings.savedReloading')}</span>}
            <Button variant='outline' onClick={() => setOpen(false)}>
              {t('settings.cancel')}
            </Button>
            <Button onClick={save}>
              <KeyRound className='size-4' />
              {t('settings.save')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
