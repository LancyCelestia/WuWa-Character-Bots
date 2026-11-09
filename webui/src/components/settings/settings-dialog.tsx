// 轻量设置面板：baseURL + 三槽 token 本地录入。
// 控制面无登录端点（auth.py：Bearer 只认 Authorization 头，禁 URL/query 传递）——
// 令牌存 localStorage（`webui:token:admin` / `webui:token:ro` / `webui:token:super-admin`），
// 刷新后仍在；localStorage 不可用时 api-client 自动降级为纯内存态，本面板代码无需分支。
//
// 🔴 为什么要有第三槽（`superAdmin`）：后端所有**写腿**（配置 preview/set/reset、
// 动作 preview/execute、凭据整段路由、可视化 preview/save/theme）都挂
// `_super_admin_dependency`，只比对 `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256`。
// 只有 admin/ro 两槽时，用户点「保存」必然 403——正是「设置存不了」「凭据打不开」
// 「可视编辑器只能读」的同一条根因。
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, KeyRound, MonitorPlay, Settings, Trash2, Type, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/appearance/field';
import {
  getApiToken,
  getBaseUrl,
  setApiToken,
  setBaseUrl,
  validateBaseUrl,
  type TokenKind,
} from '@/lib/api-client';
import {
  BACKDROP_LABELS,
  normalizeWallpaperUrl,
  useInterfacePrefs,
  type BackdropStrength,
  type FontScale,
  type WallpaperTier,
} from '@/components/settings/interface-prefs';
import { useAppearance } from '@/lib/appearance/context';
import { wallpaperOwner } from '@/lib/wallpaper-owner';

function tokenField({
  label,
  kind,
  savedHint,
}: {
  label: string;
  kind: TokenKind;
  savedHint: string;
}) {
  return { label, kind, savedHint };
}

export function SettingsDialog() {
  const { t } = useTranslation();
  // 界面偏好（UI3）：字号档 / 动态壁纸 / 背景强度。存 localStorage，只影响本浏览器。
  const { prefs, set: setPref, reset: resetPrefs } = useInterfacePrefs();
  // 壁纸互斥（W13-L）：判据只有 lib/wallpaper-owner 一处，这里只用来「说清楚」。
  // 外观页选了本地文件时，下面的内置/地址壁纸其实不播——不写一句，用户会以为开关坏了。
  const { effective } = useAppearance();
  const appearanceOwnsWallpaper = wallpaperOwner(effective.wallpaper, prefs.wallpaperEnabled) === 'appearance';
  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrlState] = useState('');
  const [adminToken, setAdminToken] = useState('');
  const [roToken, setRoToken] = useState('');
  const [superAdminToken, setSuperAdminToken] = useState('');
  const [showTokens, setShowTokens] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [baseUrlError, setBaseUrlError] = useState<string | null>(null);
  // 本机已存令牌的「有没有」快照：驱动占位符与清除按钮。读 localStorage 不是可观察状态，
  // 不进 state 的话清除后界面不会重绘（按钮还在、提示还写「已保存」）。
  // 令牌现在真落 localStorage，这个快照刷新后照样为 true——界面承诺与持久化行为一致。
  const [hasStored, setHasStored] = useState<Record<TokenKind, boolean>>({ admin: false, ro: false, superAdmin: false });

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
      setSuperAdminToken('');
      setBaseUrlError(null);
      setHasStored({
        admin: Boolean(getApiToken('admin')),
        ro: Boolean(getApiToken('ro')),
        superAdmin: Boolean(getApiToken('superAdmin')),
      });
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
    if (superAdminToken.trim()) setApiToken(superAdminToken.trim(), 'superAdmin');
    setAdminToken('');
    setRoToken('');
    setSuperAdminToken('');
    setHasStored({
      admin: Boolean(getApiToken('admin')),
      ro: Boolean(getApiToken('ro')),
      superAdmin: Boolean(getApiToken('superAdmin')),
    });
    setSavedFlash(true);
    window.dispatchEvent(new Event('webui:credentials-changed'));
  };

  // 保存时留空=保持原值（防静默清空凭据）；清除走显式按钮——两者不能混在一条路径上。
  // 清除必须同时抹掉 localStorage 与内存：setApiToken(null) 内部两处一起清（见 api-client），
  // 所以这里不用、也不许再单独摸一次 localStorage——两份真相迟早不一样。
  const clearStoredToken = (kind: TokenKind) => {
    setApiToken(null, kind);
    setHasStored((current) => ({ ...current, [kind]: false }));
    if (kind === 'admin') setAdminToken('');
    else if (kind === 'ro') setRoToken('');
    else setSuperAdminToken('');
  };

  const fields = [
    tokenField({ label: t('settings.adminToken'), kind: 'admin' as const, savedHint: t('settings.adminTokenHint') }),
    tokenField({ label: t('settings.roToken'), kind: 'ro' as const, savedHint: t('settings.roTokenHint') }),
    tokenField({
      label: t('settings.superAdminToken'),
      kind: 'superAdmin' as const,
      savedHint: t('settings.superAdminTokenHint'),
    }),
  ];

  // 三槽输入值/写回器按槽索引：渲染层不再写 `kind === 'admin' ? … : …` 二元分支
  // （第三槽进来时那种分支正是漏改的地方）。
  const tokenValues: Record<TokenKind, string> = {
    admin: adminToken,
    ro: roToken,
    superAdmin: superAdminToken,
  };
  const tokenSetters: Record<TokenKind, (value: string) => void> = {
    admin: setAdminToken,
    ro: setRoToken,
    superAdmin: setSuperAdminToken,
  };

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

          {/* ── 界面观感（UI3）：只影响本浏览器，存 localStorage ───────────────
              用户原话：「像 wallpaper engine 一样能随意调整」。三件：
                ① 字号档：Chrome 里字偏小的反馈，标准/大/特大（整页 zoom，不动 fs-* 五档）；
                ② 动态壁纸：开关 + 档位（自动/720p/1080p/自定义地址，省流量时自动不加载）；
                ③ 背景强度：柔和/标准/绚丽（只改洗色膜与光斑不透明度）。 */}
          <section className='surface flex flex-col gap-3 rounded-lg p-4' aria-label='界面观感'>
            <h3 className='flex items-center gap-2 fs-card'>
              <MonitorPlay className='size-4 text-primary' />
              界面观感
            </h3>

            <div className='flex flex-col gap-2'>
              <label htmlFor='webui-font-scale' className='flex items-center gap-2 font-medium'>
                <Type className='size-4' />
                字号大小
              </label>
              <Select
                id='webui-font-scale'
                ariaLabel='字号大小'
                block
                value={prefs.textScale}
                onChange={(next) => setPref('textScale', next as FontScale)}
                options={[
                  { value: 'default', label: '标准（跟随浏览器字号设置）' },
                  { value: 'lg', label: '大一号' },
                  { value: 'xl', label: '特大' },
                ]}
              />
              <p className='fs-caption text-muted-foreground'>
                标准档跟随 Chrome 自己的字号设置；大/特大把整页等比放大（含间距）。
              </p>
            </div>

            <div className='flex flex-col gap-2'>
              <div className='flex items-center justify-between gap-2'>
                <span className='font-medium'>动态壁纸</span>
                <button
                  type='button'
                  role='switch'
                  aria-checked={prefs.wallpaperEnabled}
                  aria-label='动态壁纸开关'
                  onClick={() => setPref('wallpaperEnabled', !prefs.wallpaperEnabled)}
                  className={[
                    'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors',
                    prefs.wallpaperEnabled ? 'border-primary/40 bg-primary/80' : 'border-hairline bg-muted',
                  ].join(' ')}
                >
                  <span
                    className={[
                      'absolute left-0.5 size-5 rounded-full bg-card shadow-sm transition-transform',
                      prefs.wallpaperEnabled ? 'translate-x-5' : 'translate-x-0',
                    ].join(' ')}
                  />
                </button>
              </div>
              <Select
                ariaLabel='壁纸档位'
                block
                disabled={!prefs.wallpaperEnabled}
                value={prefs.wallpaperTier}
                onChange={(next) => setPref('wallpaperTier', next as WallpaperTier)}
                options={[
                  { value: 'auto', label: '自动（按屏幕宽度与网络选档）' },
                  { value: '720p', label: '省流 720p（约 1.8 MB）' },
                  { value: '1080p', label: '高清 1080p（约 4.9 MB）' },
                  { value: 'custom', label: '自定义地址' },
                ]}
              />
              {prefs.wallpaperTier === 'custom' && (
                <input
                  className='h-11 rounded-md border bg-background px-3 fs-body outline-none focus-visible:ring-2 focus-visible:ring-ring'
                  aria-label='自定义壁纸地址'
                  placeholder='同源或 https 的 mp4/图片地址'
                  value={prefs.wallpaperUrl}
                  spellCheck={false}
                  onChange={(event) => setPref('wallpaperUrl', event.target.value)}
                />
              )}
              {prefs.wallpaperTier === 'custom' && prefs.wallpaperUrl.trim() !== '' && normalizeWallpaperUrl(prefs.wallpaperUrl) === null && (
                <p className='fs-caption text-destructive'>这个地址不被接受：只允许同源 http(s) 或 https 地址。</p>
              )}
              <p className='fs-caption text-muted-foreground'>
                只在壁纸真正可见时才下载；浏览器开着「省流量」时完全不加载。
              </p>
              {/* 互斥的**说清**：这里原先是两套入口各播各的，谁也拦不住谁。 */}
              {appearanceOwnsWallpaper && (
                <p className='fs-caption text-tone-warn'>
                  外观工作室已经选了本地壁纸文件，这一屏播的是它——这里的开关此刻不起作用。
                  要换回内置/地址壁纸，去「外观工作室 → 壁纸」把模式改成「无」或「着色器」。
                </p>
              )}
            </div>

            <div className='flex flex-col gap-2'>
              <span className='font-medium'>背景强度</span>
              <div className='flex flex-wrap gap-2'>
                {(['soft', 'normal', 'vivid'] as const).map((strength) => (
                  <Button
                    key={strength}
                    size='sm'
                    variant={prefs.backdrop === strength ? 'default' : 'outline'}
                    onClick={() => setPref('backdrop', strength as BackdropStrength)}
                  >
                    {BACKDROP_LABELS[strength]}
                  </Button>
                ))}
              </div>
              <p className='fs-caption text-muted-foreground'>
                「绚丽」让釉瑚光斑更亮、洗色膜更淡；「柔和」反过来，适合文字为主时用。
              </p>
            </div>

            <div>
              <Button size='sm' variant='ghost' onClick={resetPrefs}>
                恢复默认观感
              </Button>
            </div>
          </section>

          {fields.map((field) => (
            <div key={field.kind} className='flex flex-col gap-2'>
              <label htmlFor={`webui-token-${field.kind}`} className='font-medium'>
                {field.label}
              </label>
              <div className='flex gap-2'>
                <input
                  id={`webui-token-${field.kind}`}
                  type={showTokens ? 'text' : 'password'}
                  value={tokenValues[field.kind]}
                  onChange={(event) => tokenSetters[field.kind](event.target.value)}
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
