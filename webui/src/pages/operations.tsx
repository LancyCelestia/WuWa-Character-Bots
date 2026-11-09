import { useState } from 'react';
import { Play, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { apiRequest } from '@/lib/api-client';
import { actionLabel } from '@/lib/domain-labels';
import { formatUnixSeconds } from '@/lib/format';
import { centerApi, pendingReceipt, safeText, type RunReceipt, type ActionRunDetail } from '@/lib/control-center';
interface Action { action_id: string; label: string; confirmation_required: boolean; parameter_schema: unknown }
interface Preview extends RunReceipt { expected_version?: number; action_id?: string }

function RunInspector({ runId }: { runId: string }) {
  const detail = useSemanticQuery<ActionRunDetail>(['operations', 'run', runId], () => centerApi.runDetail(runId));
  return <section className='mt-3 min-w-0 border-t pt-3' aria-label='执行记录详情'>
    <h3 className='mb-2 fs-card'>执行记录详情</h3>
    <SemanticState state={detail.state} onRetry={detail.refetch}>
      {detail.state.phase === 'ok' && <>
        <p className='fs-body'>{pendingReceipt(detail.state.data)}</p>
        <p className='fs-caption text-muted-foreground'>
          执行于 {formatUnixSeconds(detail.state.data.created_at)} · 更新于 {formatUnixSeconds(detail.state.data.updated_at)}
        </p>
        <pre className='mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words fs-caption'>{safeText(detail.state.data)}</pre>
      </>}
    </SemanticState>
  </section>;
}

export function OperationsPage() {
  const query = useSemanticQuery<{ items: Action[] }>(['operations', 'actions'], () => apiRequest('/api/v1/actions'));
  const runs = useSemanticQuery<{ items: RunReceipt[] }>(['operations', 'runs'], () => apiRequest('/api/v1/actions/runs'), { refetchInterval: 5000 });
  const commands = useSemanticQuery<{ items: RunReceipt[] }>(['operations', 'commands'], () => apiRequest('/api/v1/config/commands'), { refetchInterval: 5000 });
  const [preview, setPreview] = useState<{ action: Action; data: Preview } | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedRun, setSelectedRun] = useState('');
  async function prepare(action: Action) {
    setBusy(true); setPreview(null);
    try {
      const detail = await apiRequest<{ version: number }>(`/api/v1/actions/${encodeURIComponent(action.action_id)}`);
      const data = await apiRequest<Preview>(`/api/v1/actions/${encodeURIComponent(action.action_id)}/preview`, { method: 'POST', body: { parameters: {}, expected_version: detail.version } });
      setPreview({ action, data }); setNotice('风险预览完成，尚未执行。确认只对本动作、参数和版本有效。');
    } catch (error) { setNotice(error instanceof Error ? error.message : '预览失败。'); }
    finally { setBusy(false); }
  }
  async function execute() {
    if (!preview) return;
    setBusy(true);
    try {
      const receipt = await apiRequest<RunReceipt>(`/api/v1/actions/${encodeURIComponent(preview.action.action_id)}/execute`, { method: 'POST', body: { parameters: {}, expected_version: preview.data.version ?? preview.data.expected_version, confirmation_token: preview.data.confirmation_token, idempotency_key: crypto.randomUUID() } });
      setNotice(pendingReceipt(receipt)); runs.refetch();
    } catch (error) { setNotice(error instanceof Error ? error.message : '执行失败，未确认成功。'); }
    finally { setPreview(null); setBusy(false); }
  }
  const actions = query.state.phase === 'ok' ? query.state.data.items : [];
  return <div className='flex flex-col gap-6'>
    <PageHeader title='受控操作与回执' subtitle='动作目录只表示已登记，不保证执行适配已连接。回执分别显示降级、待批、冲突与成功；不是通用终端。' />
    <SemanticState state={query.state} onRetry={query.refetch}>
      <div className='surface divide-y rounded-lg'>
        {actions.map(action => {
          // 后端 `ControlActionDescriptor(action_id, action_id)` 把 label 直接等于 id，
          // 于是 `adapter.reconnect` 这种英文原文会裸上屏（用户抱怨的「updeer.reconnect」就是它）。
          // 中文名上主位、hint 做副标题，原始 id 降级到 title——排查全靠它，不许丢。
          const { name, hint } = actionLabel(action.action_id);
          return (
            <section key={action.action_id} className='flex flex-wrap items-center justify-between gap-3 p-4'>
              <div>
                <h2 className='fs-body'>{name}</h2>
                <p className='fs-caption text-muted-foreground' title={action.action_id}>{hint}</p>
              </div>
              <Button variant='outline' disabled={busy} onClick={() => void prepare(action)}><ShieldCheck className='size-4' />预览风险与版本</Button>
            </section>
          );
        })}
        {!actions.length && <p className='p-4 fs-body text-muted-foreground'>当前身份没有可受理动作；不提供任意命令执行。</p>}
      </div>
    </SemanticState>
    {preview && (
      <section className='surface flex flex-col gap-3 rounded-lg p-4' role='region' aria-label='动作确认'>
        <h2 className='fs-card'>确认：{actionLabel(preview.action.action_id).name}</h2>
        <p className='fs-body'>
          动作 <span title={preview.action.action_id}>{actionLabel(preview.action.action_id).name}</span> · 版本 {preview.data.version ?? preview.data.expected_version ?? '未知'}
        </p>
        <div className='flex gap-2'>
          <Button disabled={busy} onClick={() => void execute()}><Play className='size-4' />确认执行本动作</Button>
          <Button variant='outline' disabled={busy} onClick={() => setPreview(null)}>取消</Button>
        </div>
      </section>
    )}
    {notice && <p role='status' className='rounded-md border p-3 fs-body'>{notice}</p>}
    <section>
      <h2 className='mb-3 fs-page'>配置命令状态</h2>
      {/* 根因级说明（用户原话「配置命令状态显示『加载失败』」）：后端 `control_plane_actions`
          库实测没有建表，该端点因此恒返回空表——不是前端加载失败，是这条链路还没接通。
          逻辑一行未动，只在标题下说清楚它本来就没有数据。 */}
      <p className='mb-3 fs-caption text-muted-foreground'>
        该区块读的是配置命令执行记录。当前后端 control_plane_actions 库没有建表，所以恒为空——不是「加载失败」，是这条链路还没接通。
      </p>
      <SemanticState state={commands.state} onRetry={commands.refetch}>
        {commands.state.phase === 'ok' && <div className='surface divide-y rounded-lg'>
          {commands.state.data.items.map((item, index) => (
            <div key={item.command_id ?? index} className='flex flex-col gap-1 p-3'>
              <p className='break-words fs-body'>{item.command_id} · {pendingReceipt(item)}</p>
              <p className='break-words fs-caption text-muted-foreground'>{safeText(item.result)}</p>
            </div>
          ))}
          {!commands.state.data.items.length && <p className='p-4 fs-body text-muted-foreground'>无本身份命令。机器人宿主内写配置是当场执行的，不排队、也不会在这里留命令记录。</p>}
        </div>}
      </SemanticState>
    </section>
    <section>
      <h2 className='mb-3 fs-page'>运维执行记录</h2>
      <SemanticState state={runs.state} onRetry={runs.refetch}>
        {runs.state.phase === 'ok' && <div className='surface divide-y rounded-lg'>
          {runs.state.data.items.map((item, index) => <div key={item.run_id ?? index} className='flex flex-wrap items-center justify-between gap-2 p-3'>
            <p className='min-w-0 break-words fs-body'>{item.run_id} · {pendingReceipt(item)}</p>
            {item.run_id && <Button size='sm' variant='outline' aria-pressed={selectedRun === item.run_id} onClick={() => setSelectedRun(current => current === item.run_id ? '' : item.run_id ?? '')}>查看回执详情</Button>}
          </div>)}
          {!runs.state.data.items.length && <p className='p-4 fs-body text-muted-foreground'>暂无记录。这里只如实列已发生的受控操作：先「预览」再「确认执行」一次，回执就会出现在这里。</p>}
        </div>}
      </SemanticState>
      {selectedRun && <RunInspector key={selectedRun} runId={selectedRun} />}
    </section>
  </div>;
}
