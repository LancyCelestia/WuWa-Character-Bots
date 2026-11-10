import { useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Eye, LayoutTemplate, Plus, Save, Sparkles, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/appearance/field';
import { PageHeader, SectionCard } from '@/components/patterns/patterns';
import { SemanticState } from '@/components/semantic/semantic-state';
import { useSemanticQuery } from '@/hooks/use-semantic-query';
import { fieldLabel, humanizeEnum } from '@/lib/humanize';
import {
  describeSource, fragmentsPayload, moveElement, newElement, nextExpectedVersion, numberOrClear, scopeKey, updateStyle, visualApi,
  type LayoutScope, type VisualDocument, type VisualFragments, type VisualTheme,
} from '@/lib/visual-editor';
import {
  DEFAULT_CARD_IDS,
  PREVIEW_SANDBOX,
  STYLE_LABELS,
  describeLayout,
  describeTheme,
  normalizeThemeColor,
  styleChoices,
  templateCandidates,
} from '@/lib/template-catalog';

const fieldClass = 'w-full rounded-md border bg-background px-3 py-2 fs-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
type Axis = 'platform' | 'instance' | 'group' | 'card';
const AXIS_LABELS: Record<Axis, string> = { platform: '平台', instance: '适配器实例', group: '会话', card: '能力 ID' };
/** 回退链四态的人话（`source` 真身见 `visual_layouts.py::_load`）。 */
function sourceLabel(source: string | undefined): string {
  if (source === 'exact') return '精确作用域行';
  if (source === 'platform') return '平台默认面';
  if (source === 'global') return '全局面（*）';
  return '未命中任何一层';
}
export function VisualEditorPage() {
  const catalog = useSemanticQuery(['visual', 'catalog'], visualApi.catalog);
  const data = catalog.state.phase === 'ok' ? catalog.state.data as Awaited<ReturnType<typeof visualApi.catalog>> : null;
  const theme = useSemanticQuery(['visual', 'theme'], visualApi.theme);
  const themeData = theme.state.phase === 'ok' ? theme.state.data as Awaited<ReturnType<typeof visualApi.theme>> : null;
  /**
   * W12 R3(a)：平台轴**必须**由用户显式选择，缺省空串。
   * 此前缺省写死 `'qq'`，而生产摄取层写的是 `onebot`（AST 可核：__init__.py）——
   * 两边永不相等，保存了却永不生效，且当时没有全局面可兜底。
   */
  const [scope, setScope] = useState<LayoutScope>({ platform: '', instance: '', group: '', card: '' });
  const scopeRef = useRef(scope);
  const [versionKnown, setVersionKnown] = useState(false);
  const [spec, setSpec] = useState<VisualDocument>({ version: 1, title: '卡片标题', layout: 'single', elements: [newElement('text')] });
  const [version, setVersion] = useState(0);
  const [provenance, setProvenance] = useState<{ source?: string; label: string; fallback: LayoutScope | null } | null>(null);
  const [fragments, setFragments] = useState<VisualFragments>({});
  const [overrides, setOverrides] = useState<VisualTheme>({});
  const [themeVersion, setThemeVersion] = useState<number | null>(null);
  const [selected, setSelected] = useState(0);
  const [dragging, setDragging] = useState<number | null>(null);
  const [html, setHtml] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const element = spec.elements[selected];
  function change(next: VisualDocument) { setSpec(next); setHtml(''); }
  function editFragments(key: keyof VisualFragments, value: string) {
    setFragments(current => ({ ...current, [key]: value })); setHtml('');
  }
  async function action(kind: 'read' | 'preview' | 'save' | 'reset') {
    if (busy || ((kind === 'save' || kind === 'reset') && !versionKnown)) return;
    const requestedScope = scopeKey(scope);
    setBusy(true); setNotice('');
    try {
      if (kind === 'read') {
        const result = await visualApi.read(scope);
        if (requestedScope !== scopeKey(scopeRef.current)) return;
        setVersion(nextExpectedVersion(result)); setVersionKnown(true);
        // 生效来源三跳 + 「是哪一层在生效」一次说清（否则用户看不出为什么没生效）。
        setProvenance({
          source: result.source,
          label: describeSource(result),
          fallback: result.fallback_scope ?? null,
        });
        setFragments(result.fragments ?? {});
        if (result.spec) { setSpec(result.spec); setSelected(0); }
        setNotice(`读取版本 ${result.version}，来源 ${result.source ?? '未知'}。`); setHtml('');
      } else if (kind === 'preview') {
        const result = await visualApi.preview(spec, fragmentsPayload(fragments));
        if (requestedScope !== scopeKey(scopeRef.current)) return;
        setHtml(result.html);
        setNotice(result.degraded.length ? `部分元素已安全降级：${result.degraded.join('、')}` : '预览来自生产同一 HTML 渲染函数，尚未发布。');
      } else {
        const payload = fragmentsPayload(fragments);
        const result = kind === 'save'
          ? await visualApi.save(scope, spec, version, payload)
          : await visualApi.reset(scope, version);
        if (requestedScope !== scopeKey(scopeRef.current)) return;
        setVersion(nextExpectedVersion(result)); setVersionKnown(true);
        setFragments(result.fragments ?? {});
        if (result.spec) { setSpec(result.spec); setSelected(0); }
        setHtml('');
        setNotice(`布局${kind === 'save' ? '已保存' : '已撤回'}，版本 ${result.version}。只更新排版与样式，不替换业务文案；实际 producer 包括 bot.weather、bot.market 与 bot.fx。`);
      }
    } catch (error) {
      setHtml('');
      if (kind !== 'preview') setVersionKnown(false);
      setNotice(error instanceof Error ? `${error.message} 请重新读取作用域后再提交。` : '操作失败，布局未确认保存。');
    } finally { setBusy(false); }
  }
  async function actionTheme(kind: 'save' | 'rollback') {
    const base = themeData?.version ?? themeVersion;
    if (busy || base === null) return;
    setBusy(true); setNotice('');
    try {
      const result = kind === 'save'
        ? await visualApi.saveTheme(overrides, base)
        : await visualApi.rollbackTheme(base);
      setThemeVersion(result.version);
      setOverrides(result.overrides);
      theme.refetch();
      setHtml('');
      setNotice(`全局视觉${kind === 'save' ? '已保存' : '已回滚'}，版本 ${result.version}${result.actor ? `，操作人 ${result.actor}` : ''}。主色/圆角/字体影响所有未单独覆盖的卡片，可随时回滚。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '全局视觉写入失败，未能确认生效。');
    } finally { setBusy(false); }
  }
  function reorder(from: number, to: number) {
    if (busy) return;
    change({ ...spec, elements: moveElement(spec.elements, from, to) }); setSelected(to);
  }
  return <div className='flex flex-col gap-6'>
    <PageHeader title='可视卡片编辑器' subtitle='编辑排版、受限文案与全局视觉 token；业务数值仍来自已审结果。拖动、键盘排序与预览使用同一声明式布局。' />
    <SemanticState state={catalog.state} onRetry={catalog.refetch}>
      <fieldset disabled={busy} className='flex min-w-0 flex-col gap-4'>
        <legend className='sr-only'>布局作用域与编辑</legend>
        <div className='grid gap-3 sm:grid-cols-4'>
          {(['platform', 'instance', 'group', 'card'] as const).map(axis => (
            <label key={axis} className='flex min-w-0 flex-col gap-1 fs-caption'>
              {AXIS_LABELS[axis]}
              {axis === 'platform' ? (
                <Select
                  block
                  ariaLabel={AXIS_LABELS[axis]}
                  value={scope[axis]}
                  onChange={next => {
                    const nextScope = { ...scope, [axis]: next };
                    scopeRef.current = nextScope; setScope(nextScope); setVersion(0); setVersionKnown(false); setHtml(''); setNotice('');
                  }}
                  options={[
                    { value: '', label: '请选择平台（不猜）' },
                    ...(data?.platforms ?? []).map(platform => ({
                      value: platform,
                      label: platform === '*' ? '全局面（*）' : platform,
                    })),
                  ]}
                />
              ) : (
                <input className={fieldClass} value={scope[axis]} onChange={event => {
                  const next = { ...scope, [axis]: event.target.value };
                  scopeRef.current = next; setScope(next); setVersion(0); setVersionKnown(false); setHtml(''); setNotice('');
                }} />
              )}
            </label>
          ))}
        </div>
        <p className='fs-caption text-muted-foreground'>回退链：精确作用域 → 平台默认面 → 全局面（*）→ 未命中。平台清单来自后端 catalog（生产摄取写 onebot/qq/nonebot/telegram/email）；填真实能力 ID（bot.weather、bot.market、bot.fx）才命中精确行。</p>
        <div className='flex flex-wrap items-center gap-2'>
          <Button variant='outline' disabled={busy || !scope.platform} onClick={() => void action('read')}>读取作用域</Button>
          <Button variant='outline' disabled={busy} onClick={() => void action('preview')}><Eye className='size-4' />真实预览</Button>
          <Button disabled={busy || !html || !versionKnown} onClick={() => void action('save')}><Save className='size-4' />保存整份布局</Button>
          <Button variant='outline' disabled={busy || !versionKnown || version === 0} onClick={() => void action('reset')}>撤回到默认</Button>
          <span className='fs-caption text-muted-foreground'>{versionKnown ? `精确版本 ${version}` : '请先读取当前作用域'} · 人格切换不另存布局</span>
        </div>
        {provenance && <p className='rounded-md border p-3 fs-caption text-muted-foreground'>
          生效来源：{sourceLabel(provenance.source)} · {provenance.label}
          {provenance.fallback && `（命中作用域 ${provenance.fallback.platform}${provenance.fallback.card ? ` / ${provenance.fallback.card}` : ''}）`}
        </p>}
        {notice && <p role='status' className='rounded-md border p-3 fs-body'>{notice}</p>}
        <div className='grid min-w-0 gap-4 xl:grid-cols-4'>
          <section className='surface flex min-w-0 flex-col gap-3 rounded-lg p-4'>
            <h2 className='fs-card'>元素与预设</h2>
            <label className='flex flex-col gap-1 fs-caption'>布局
              <Select
                block
                ariaLabel='布局'
                value={spec.layout}
                onChange={next => change({ ...spec, layout: next })}
                options={['single', 'double', 'grid'].map(value => ({ value, label: humanizeEnum(value) }))}
              />
            </label>
            <label className='flex flex-col gap-1 fs-caption'>预览标题
              <input className={fieldClass} value={spec.title} onChange={event => change({ ...spec, title: event.target.value })} />
            </label>
            <div className='grid grid-cols-2 gap-2'>
              {data?.kinds.map(kind => <Button key={kind} size='sm' variant='outline' disabled={spec.elements.length >= 60 || kind === 'chart.bar'} title={kind === 'chart.bar' ? '柱状图尚未接入，不以折线替代' : undefined} onClick={() => {
                change({ ...spec, elements: [...spec.elements, newElement(kind)] }); setSelected(spec.elements.length);
              }}><Plus className='size-3' />{humanizeEnum(kind)}</Button>)}
            </div>
            <Button variant='outline' onClick={() => { change({ ...spec, elements: [newElement('stat'), newElement('kv'), newElement('divider'), newElement('text')] }); setSelected(0); }}>应用指标说明预设</Button>
          </section>
          <section className='surface min-w-0 rounded-lg p-4 xl:col-span-2'>
            <h2 className='mb-3 fs-card'>元素顺序与画布</h2>
            <div className='flex flex-col gap-2'>
              {spec.elements.map((item, index) => (
                <div key={item.id ?? index} draggable={!busy} onDragStart={() => setDragging(index)} onDragEnd={() => setDragging(null)} onDragOver={event => event.preventDefault()} onDrop={() => {
                  if (dragging !== null) reorder(dragging, index); setDragging(null);
                }} className={`flex min-w-0 items-center gap-2 rounded-md border p-3 ${selected === index ? 'border-primary' : ''}`}>
                  <button className='min-w-0 flex-1 truncate text-left fs-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring' aria-pressed={selected === index} onClick={() => setSelected(index)}>{humanizeEnum(item.kind)} · {String(item.data.label ?? item.data.text ?? item.data.caption ?? '元素')}</button>
                  <Button size='icon-sm' variant='ghost' aria-label={`上移第 ${index + 1} 项`} disabled={index === 0} onClick={() => reorder(index, index - 1)}><ArrowUp className='size-4' /></Button>
                  <Button size='icon-sm' variant='ghost' aria-label={`下移第 ${index + 1} 项`} disabled={index === spec.elements.length - 1} onClick={() => reorder(index, index + 1)}><ArrowDown className='size-4' /></Button>
                  <Button size='icon-sm' variant='ghost' aria-label={`删除第 ${index + 1} 项`} onClick={() => { change({ ...spec, elements: spec.elements.filter((_, position) => position !== index) }); setSelected(0); }}><Trash2 className='size-4' /></Button>
                </div>
              ))}
              {!spec.elements.length && <p className='fs-body text-muted-foreground'>没有元素。可从左侧添加；业务安全提示不受编辑器控制。</p>}
            </div>
            {html && <iframe title='生产同源卡片预览' sandbox='' srcDoc={html} className='mt-4 min-h-96 w-full rounded-md border bg-card' />}
          </section>
          <section className='surface flex min-w-0 flex-col gap-3 rounded-lg p-4'>
            <h2 className='fs-card'>声明式属性</h2>
            {element && Object.entries(element.data).map(([key, value]) => (
              <label key={key} className='flex flex-col gap-1 fs-caption'>{fieldLabel(key)}
                <input className={fieldClass} value={typeof value === 'object' ? JSON.stringify(value) : String(value)} onChange={event => {
                  let parsed: unknown = event.target.value;
                  if (typeof value === 'object' || typeof value === 'number') { try { parsed = JSON.parse(event.target.value); } catch { setNotice('数组、对象和数值需要有效 JSON；未改变已验证数据。'); return; } }
                  change({ ...spec, elements: spec.elements.map((item, index) => index === selected ? { ...item, data: { ...item.data, [key]: parsed } } : item) });
                }} />
              </label>
            ))}
            {(['size', 'spacing', 'weight', 'color'] as const).map(key => (
              <label key={key} className='flex flex-col gap-1 fs-caption'>{fieldLabel(key)}
                <Select
                  block
                  ariaLabel={fieldLabel(key)}
                  value={String(spec.style?.[key] ?? '')}
                  onChange={next => change(updateStyle(spec, key, next))}
                  options={[
                    { value: '', label: '主题默认' },
                    ...((key === 'color' ? data?.style.colors : key === 'size' ? data?.style.sizes : key === 'weight' ? data?.style.weights : data?.style.spacing) ?? []).map(value => ({ value: String(value), label: humanizeEnum(String(value)) })),
                  ]}
                />
              </label>
            ))}
            <p className='fs-caption text-muted-foreground'>这里只发布布局与登记样式。标题和元素数据用于预览，不覆盖 Bot 已审业务文案；目前实际 producer 包括 bot.weather、bot.market 与 bot.fx。柱状图尚未接入。</p>
          </section>
        </div>
        {/* ── 卡片模板（UI3 需求 10 后半）─────────────────────────────────
            用户原话：「没办法调整 html 卡片渲染的模板」。这里给三件：
              ① 模板列表：平台 × 卡片 ID（与布局回退链同一套作用域，点一条就填好四轴）；
              ② 受控样式：颜色/字号档/字重/间距只从**后端登记值域**里选，禁自由 hex；
              ③ 实时预览：生产同源渲染函数的 HTML，装进 **sandbox 且不带 allow-same-origin**
                 的 iframe —— 预览内容拿不到本页的 localStorage/令牌，也导航不了父页面。 */}
        <SectionCard
          title='卡片模板'
          description='模板 = 平台 × 卡片能力的布局。选中一条即填好作用域，右侧是生产渲染函数的实时预览（沙箱隔离）。'
        >
          <div className='grid min-w-0 gap-4 xl:grid-cols-3'>
            <section className='flex min-w-0 flex-col gap-2' aria-label='模板列表'>
              <h3 className='flex items-center gap-2 fs-body'>
                <LayoutTemplate className='size-4 text-primary' />
                可用模板
              </h3>
              <ul className='flex flex-col gap-2'>
                {templateCandidates(data, [...DEFAULT_CARD_IDS]).map((template) => {
                  const active = scope.platform === template.platform && scope.card === template.card;
                  return (
                    <li key={template.platform + '|' + template.card}>
                      <button
                        type='button'
                        disabled={busy}
                        aria-pressed={active}
                        onClick={() => {
                          const next: LayoutScope = { ...scope, platform: template.platform, card: template.card };
                          scopeRef.current = next;
                          setScope(next);
                          setVersionKnown(false);
                          setHtml('');
                          setNotice('');
                        }}
                        className={[
                          'flex min-h-11 w-full flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors',
                          active ? 'border-primary bg-primary/10' : 'hover:bg-accent',
                        ].join(' ')}
                      >
                        <span className='truncate fs-body'>{template.label}</span>
                        <span className='fs-caption text-muted-foreground'>
                          {active ? describeLayout(spec) : template.global ? '全局面兜底' : '精确作用域'}
                        </span>
                      </button>
                    </li>
                  );
                })}
                {templateCandidates(data, [...DEFAULT_CARD_IDS]).length === 0 && (
                  <li className='fs-caption text-muted-foreground'>目录尚未装配：模板列表来自后端 visual catalog。</li>
                )}
              </ul>
            </section>

            <section className='flex min-w-0 flex-col gap-3' aria-label='受控样式'>
              <h3 className='flex items-center gap-2 fs-body'>
                <Sparkles className='size-4 text-tone-purple' />
                受控样式（只能选登记值）
              </h3>
              {(['size', 'weight', 'color', 'spacing'] as const).map((key) => {
                const choices = styleChoices(data, key);
                return (
                  <label key={key} className='flex flex-col gap-1 fs-caption'>
                    {STYLE_LABELS[key]}
                    <Select
                      block
                      ariaLabel={STYLE_LABELS[key]}
                      disabled={busy || choices.length === 0}
                      value={spec.style?.[key] === undefined ? '' : String(spec.style[key])}
                      onChange={(next) => change(updateStyle(spec, key, next))}
                      options={[
                        { value: '', label: '主题默认' },
                        ...choices.map((value) => ({ value: String(value), label: String(value) })),
                      ]}
                    />
                    {choices.length === 0 && (
                      <span className='fs-caption text-muted-foreground'>后端目录未登记这一轴的可选值</span>
                    )}
                  </label>
                );
              })}
              <div className='flex flex-wrap gap-2'>
                <Button size='sm' variant='outline' disabled={busy} onClick={() => void action('preview')}>
                  <Eye className='size-4' />
                  刷新预览
                </Button>
                <Button size='sm' disabled={busy || !html || !versionKnown} onClick={() => void action('save')}>
                  <Save className='size-4' />
                  保存模板
                </Button>
              </div>
            </section>

            <section className='flex min-w-0 flex-col gap-2' aria-label='模板预览'>
              <h3 className='fs-body'>实时预览</h3>
              {html ? (
                <iframe
                  title='卡片模板预览（沙箱隔离）'
                  sandbox={PREVIEW_SANDBOX}
                  referrerPolicy='no-referrer'
                  srcDoc={html}
                  className='min-h-96 w-full rounded-md border bg-card'
                />
              ) : (
                <div className='flex min-h-40 flex-col justify-center gap-2 rounded-md border border-dashed p-4'>
                  <p className='fs-caption text-muted-foreground'>
                    点「刷新预览」用生产渲染函数出图。预览 HTML 只来自后端渲染器，编辑区不接受任何手写 HTML/样式。
                  </p>
                  {notice && <p className='fs-caption text-tone-warn'>{notice}</p>}
                </div>
              )}
            </section>
          </div>
        </SectionCard>

        <div className='grid min-w-0 gap-4 xl:grid-cols-2'>
          <section className='surface flex min-w-0 flex-col gap-3 rounded-lg p-4'>
            <h2 className='fs-card'>受限文案片段</h2>
            <p className='fs-caption text-muted-foreground'>只改标题、副标题、页脚三处纯文本；不接受 HTML 或样式（含尖括号、url()、@import 的输入会被后端拒收）。</p>
            {(data?.fragments ?? ['title', 'subtitle', 'footer']).map(key => (
              <label key={key} className='flex flex-col gap-1 fs-caption'>{key}
                <input className={fieldClass} maxLength={data?.fragment_limits?.[key] ?? 200} value={fragments[key as keyof VisualFragments] ?? ''} onChange={event => editFragments(key as keyof VisualFragments, event.target.value)} />
              </label>
            ))}
          </section>
          <section className='surface flex min-w-0 flex-col gap-3 rounded-lg p-4'>
            <h2 className='fs-card'>全局视觉 token</h2>
            <p className='fs-caption text-muted-foreground'>主色 / 圆角 / 字体走同一条 visual 通道：CAS 版本 + 审计 + 可回滚。只收登记值域，wash 四色由值册按主色现算，不产生第二份颜色源。</p>
            <label className='flex flex-col gap-1 fs-caption'>品牌主色（#RRGGBB）
              <input
                className={fieldClass}
                placeholder={themeData?.overrides.brand_accent ?? '留空＝沿用值册品牌色'}
                value={overrides.brand_accent ?? ''}
                aria-invalid={Boolean(overrides.brand_accent) && normalizeThemeColor(overrides.brand_accent ?? '') === null}
                onChange={event => setOverrides(current => ({ ...current, brand_accent: event.target.value }))}
              />
              {overrides.brand_accent && normalizeThemeColor(overrides.brand_accent) === null && (
                <span className='fs-caption text-tone-bad'>只接受 6 位十六进制：井号加六位 0-9/A-F（例如井号 318CE7）</span>
              )}
              <span className='fs-caption text-muted-foreground'>当前生效覆盖：{describeTheme(themeData?.overrides)}</span>
            </label>

            <label className='flex flex-col gap-1 fs-caption'>卡片外壳圆角
              <Select
                block
                ariaLabel='卡片外壳圆角'
                value={String(overrides.shell_radius ?? '')}
                onChange={next => setOverrides(current => ({ ...current, shell_radius: numberOrClear(next) }))}
                options={[
                  { value: '', label: '默认 30px' },
                  ...(data?.theme_choices?.shell_radius ?? []).map(value => ({ value: String(value), label: `${value}px` })),
                ]}
              />
            </label>
            <label className='flex flex-col gap-1 fs-caption'>字体栈
              <Select
                block
                ariaLabel='字体栈'
                value={overrides.font_family ?? ''}
                onChange={next => setOverrides(current => ({ ...current, font_family: next === '' ? undefined : next }))}
                options={[
                  { value: '', label: '默认 sans' },
                  ...(data?.theme_choices?.font_family ?? []).map(value => ({ value, label: value })),
                ]}
              />
            </label>
            <div className='flex flex-wrap items-center gap-2'>
              <Button variant='outline' disabled={busy || (themeData?.version ?? null) === null} onClick={() => void actionTheme('save')}>保存全局视觉</Button>
              <Button variant='outline' disabled={busy || (themeData?.version ?? null) === null} onClick={() => void actionTheme('rollback')}>回滚上一版</Button>
              <span className='fs-caption text-muted-foreground'>
                {/* 读不到就如实说读不到：此处**不**假装默认值可写（否则保存打到不存在的
                    版本上，错误在用户看来是「点了没反应」）。 */}
                {themeData
                  ? `生效版本 ${themeData.version}`
                  : theme.state.phase === 'ok'
                    ? '全局视觉读取中'
                    : '全局视觉不可用（后端未提供 /visual/theme 或未授权）——布局与片段仍可正常编辑'}
              </span>
            </div>
          </section>
        </div>
      </fieldset>
    </SemanticState>
  </div>;
}
