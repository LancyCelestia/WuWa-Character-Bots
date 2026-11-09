import { useState } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/appearance/field';
import { PageHeader } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { apiRequest } from '@/lib/api-client';

interface CredentialRef { ref_id: string; kind: string; source: string; version: number; expires_at: string; domain: string }
interface Change { action: 'replace' | 'delete'; value: string; kind: string; expected_version: number; domain: string; expires_at: string }
export function CredentialsPage() {
  // 凭据整段路由（含 GET）挂 `_super_admin_dependency`：显式点超管槽，别让读腿
  // 拿主令牌去撞 403（「凭据打不开」的根因之一）。
  const query = useSemanticQuery<{ items: CredentialRef[] }>(['credentials'], () => apiRequest('/api/v1/credentials', { auth: 'superAdmin' }));
  const [ref, setRef] = useState('');
  const [value, setValue] = useState('');
  const [kind, setKind] = useState('api_key');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState<{ change: Change; token: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const rows = query.state.phase === 'ok' ? query.state.data.items : [];
  const current = rows.find(item => item.ref_id === ref);
  const field = 'w-full rounded-md border bg-background px-3 py-2 fs-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  async function preview(action: 'replace' | 'delete') {
    setBusy(true); setPending(null); setNotice('');
    const change: Change = { action, value: action === 'delete' ? '' : value, kind, expected_version: current?.version ?? 0, domain: current?.domain ?? '', expires_at: current?.expires_at ?? '' };
    try {
      const result = await apiRequest<{ confirmation_token: string }>(`/api/v1/credentials/${encodeURIComponent(ref)}/preview`, { method: 'POST', auth: 'superAdmin', body: change });
      setPending({ change, token: result.confirmation_token });
      setValue(''); setNotice('预览已建立。秘密只在此页面内存，服务端不提供明文读取；确认后执行这笔绑定变更。');
    } catch (error) { setNotice(error instanceof Error ? error.message : '预览失败。'); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!pending) return;
    setBusy(true);
    try {
      await apiRequest(`/api/v1/credentials/${encodeURIComponent(ref)}/apply`, { method: 'POST', auth: 'superAdmin', body: { ...pending.change, confirmation_token: pending.token } });
      setNotice('凭据变更已落到加密存储；现有 transport 引用是否使用此存储请核接线。'); query.refetch();
    } catch (error) { setNotice(error instanceof Error ? error.message : '凭据未确认保存。'); }
    finally { setPending(null); setValue(''); setBusy(false); }
  }
  return <div className='flex flex-col gap-6'>
    <PageHeader title='加密凭据' subtitle='仅超管可管理。已有秘密永不回显；这里只列引用和版本，不列密钥前缀。' />
    <SemanticState state={query.state} onRetry={query.refetch}>
      <fieldset disabled={busy} className='grid min-w-0 gap-4 lg:grid-cols-2'>
        <legend className='sr-only'>凭据引用与本次变更</legend>
        <section className='surface min-w-0 rounded-lg p-4'>
          <h2 className='mb-3 fs-card'>已登记引用</h2>
          <div className='divide-y'>
            {rows.map(item => (
              <button key={item.ref_id} onClick={() => { setRef(item.ref_id); setKind(item.kind); setValue(''); setPending(null); }} className='flex w-full items-center justify-between gap-2 py-3 text-left fs-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
                <span className='break-words font-mono'>{item.ref_id}</span>
                <span className='text-muted-foreground'>{item.kind} · v{item.version} · 已加密</span>
              </button>
            ))}
            {!rows.length && <p className='fs-body text-muted-foreground'>尚无引用；不读取旧明文凭据来填列表。</p>}
          </div>
        </section>
        <section className='surface flex min-w-0 flex-col gap-4 rounded-lg p-4'>
          <h2 className='fs-card'>替换或创建</h2>
          <label className='flex flex-col gap-1 fs-caption'>引用 ID
            <input className={field} value={ref} onChange={event => { setRef(event.target.value); setPending(null); }} />
          </label>
          <label className='flex flex-col gap-1 fs-caption'>类型
            <Select
              block
              ariaLabel='类型'
              value={kind}
              onChange={next => { setKind(next); setPending(null); }}
              options={['api_key', 'cookie', 'oauth_token'].map(item => ({ value: item, label: item }))}
            />
          </label>
          <label className='flex flex-col gap-1 fs-caption'>新秘密
            <input type='password' autoComplete='off' className={field} value={value} onChange={event => { setValue(event.target.value); setPending(null); }} placeholder='不会回填已有值' />
          </label>
          <div className='flex flex-wrap gap-2'>
            <Button disabled={!ref || !value || busy} onClick={() => void preview('replace')}><KeyRound className='size-4' />预览替换</Button>
            <Button variant='outline' disabled={!current || busy} onClick={() => void preview('delete')}>预览删除</Button>
            {pending && <Button disabled={busy} onClick={() => void apply()}><ShieldCheck className='size-4' />确认这笔变更</Button>}
          </div>
          {pending && <Button variant='ghost' onClick={() => { setPending(null); setValue(''); }}>取消并清空暂存</Button>}
        </section>
      </fieldset>
    </SemanticState>
    {notice && <p role='status' className='rounded-md border p-3 fs-body'>{notice}</p>}
    <p className='fs-caption text-muted-foreground'>主密钥由服务器端注入，不在此页面或密文旁存储。此界面不会自行迁移 .env、轮换主密钥或更新生产配置；未注入服务时会明确显示不可用。</p>
  </div>;
}
