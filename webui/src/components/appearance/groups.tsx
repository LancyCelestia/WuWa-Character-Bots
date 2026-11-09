// 外观工作室的分组渲染器（UI3 追加二）。
//
// **数据驱动**：17 个分组、每项的中文标题/说明/控件类型全部来自 `lib/appearance/schema-fields`
// 的 `APPEARANCE_FIELDS`，本文件不再手写第二份字段表——否则「设置里少了一项」永远只能靠肉眼。
// 三类锁（appearance.test.ts）读的是同一张表，所以表对页面就对。
//
// 控件与配置的对应：
//   switch → 布尔            slider → 数值（界值只从 RANGES 取）
//   radio  → 单值枚举        multi  → 字符串数组（勾选组）
//   number → 数值输入        select → 下拉枚举
//   color  → 只能从已登记 token 里挑（不许手输色值）
//   text   → 文本（`rules`/`bindings`/`blobId` 这类由下方专用表负责的只读行）
//
// 全部受控 + 即时 `setField`：拖滑块立刻重写 CSS 变量，不需要“保存”。
import { useState } from 'react';
import {
  Aperture,
  Blend,
  ChevronDown,
  Contrast,
  Gauge,
  Image,
  Keyboard,
  Palette,
  Plus,
  Rows3,
  ScrollText,
  Sparkles,
  SwatchBook,
  Table2,
  Trash2,
  Type,
  Upload,
  Zap,
} from 'lucide-react';
import type { AppearanceField, AppearanceGroup } from '@/lib/appearance/schema-fields';
import { getPath } from '@/lib/appearance/schema-fields';
import { useAppearance } from '@/lib/appearance/context';
import { PALETTES } from '@/lib/appearance/defaults';
import { RANGES } from '@/lib/appearance/schema';
import { deleteWallpaperBlob, putWallpaperBlob } from '@/lib/appearance/store';
import type { HighlightRule, KeyBinding, ToneName } from '@/lib/appearance/types';
import { WallpaperThumb } from './background-stage';
import { Checkbox, ChoiceGroup, Field, NumberInput, Segment, Select, Slider, Switch, TextInput } from './field';

/** 色票 token → 中文名（只覆盖已登记 token）。 */
const TOKEN_LABEL: Record<string, string> = {
  brand: '品牌主色',
  purple: '辅助紫',
  deep: '深色基底',
  danger: '危险红',
  success: '成功绿',
  warning: '警示橙',
  good: '正常绿',
  warn: '警告橙',
  bad: '错误红',
  info: '信息蓝',
  magenta: '品红',
};

const TONE_CHOICES: Array<{ value: ToneName; label: string }> = [
  { value: '', label: '不染色' },
  { value: 'good', label: '正常绿' },
  { value: 'warn', label: '警告橙' },
  { value: 'bad', label: '错误红' },
  { value: 'info', label: '信息蓝' },
  { value: 'purple', label: '辅助紫' },
  { value: 'magenta', label: '品红' },
];

/** 当前色板：`custom` 时沿用配置里已有的七枚色（用户之前挑过的）。 */
function paletteFor(preset: string, current: Record<string, string>): Record<string, string> {
  if (preset === 'star' || preset === 'deep') return PALETTES[preset];
  if (preset === 'custom') return current;
  return PALETTES.sea;
}

function toneColor(token: string): string {
  return token ? `var(--tone-${token})` : '';
}

/** 一个字段 → 一行控件。 */
function FieldRow({ group, item }: { group: AppearanceGroup; item: AppearanceField }) {
  const { config, setField } = useAppearance();
  const section = item.section ?? group.section;
  const path = `${section}.${item.key}`;
  const raw = getPath(config as unknown as Record<string, unknown>, path);

  // 只读说明行（rules / bindings / blobId）：值由下方专用表维护，这里如实显示、不假装可编辑。
  if (item.key === 'rules') {
    const count = Array.isArray(raw) ? raw.length : 0;
    return (
      <Field title={item.label} hint={item.help}>
        <span className='fs-caption text-muted-foreground'>{count > 0 ? `已登记 ${count} 条` : '还没有规则'}</span>
      </Field>
    );
  }
  if (item.key === 'bindings') {
    const bound = Array.isArray(raw) ? (raw as KeyBinding[]).filter((row) => row.keys.trim()).length : 0;
    return (
      <Field title={item.label} hint={item.help}>
        <span className='fs-caption text-muted-foreground'>{bound > 0 ? `已绑定 ${bound} 个动作` : '全部用缺省键位'}</span>
      </Field>
    );
  }
  if (item.key === 'blobId') {
    return (
      <Field title={item.label} hint={item.help}>
        <span className='max-w-40 truncate fs-caption text-muted-foreground'>
          {typeof raw === 'string' && raw ? raw : item.placeholder}
        </span>
      </Field>
    );
  }

  switch (item.control) {
    case 'switch':
      return (
        <Field title={item.label} hint={item.help}>
          <Switch id={path} label={item.label} checked={Boolean(raw)} onChange={(next) => setField(path, next)} />
        </Field>
      );

    case 'slider': {
      const range =
        (RANGES as Record<string, Record<string, { min: number; max: number; step: number }>>)[section]?.[
          item.key.split('.').pop() ?? item.key
        ] ?? { min: 0, max: 100, step: 1 };
      const value = typeof raw === 'number' ? raw : range.min;
      return (
        <Field title={item.label} hint={item.help}>
          <Slider
            id={path}
            ariaLabel={item.label}
            value={value}
            min={range.min}
            max={range.max}
            step={range.step}
            unit={item.unit}
            onChange={(next) => setField(path, next)}
          />
        </Field>
      );
    }

    case 'number': {
      const range =
        (RANGES as Record<string, Record<string, { min: number; max: number; step: number }>>)[section]?.[
          item.key.split('.').pop() ?? item.key
        ] ?? { min: 0, max: 10000, step: 1 };
      return (
        <Field title={item.label} hint={item.help}>
          <NumberInput
            id={path}
            ariaLabel={item.label}
            value={typeof raw === 'number' ? raw : range.min}
            min={range.min}
            max={range.max}
            step={range.step}
            unit={item.unit}
            onChange={(next) => setField(path, next)}
          />
        </Field>
      );
    }

    case 'radio':
      return (
        <Field title={item.label} hint={item.help}>
          <ChoiceGroup
            name={path}
            ariaLabel={item.label}
            value={String(raw ?? '')}
            options={(item.choices ?? []).map((choice) => ({ value: String(choice.value), label: choice.label }))}
            onChange={(next) => {
              const match = (item.choices ?? []).find((choice) => String(choice.value) === next);
              setField(path, match ? match.value : next);
            }}
          />
        </Field>
      );

    case 'segment':
      return (
        <Field title={item.label} hint={item.help}>
          <Segment
            name={path}
            ariaLabel={item.label}
            value={String(raw ?? '')}
            options={(item.choices ?? []).map((choice) => ({ value: String(choice.value), label: choice.label }))}
            onChange={(next) => {
              const match = (item.choices ?? []).find((choice) => String(choice.value) === next);
              setField(path, match ? match.value : next);
            }}
          />
        </Field>
      );

    case 'multi': {
      const selected = Array.isArray(raw) ? (raw as unknown[]).map(String) : [];
      return (
        <Field title={item.label} hint={item.help}>
          <span className='flex min-w-0 flex-wrap justify-end gap-2'>
            {(item.choices ?? []).map((choice) => {
              const key = String(choice.value);
              const on = selected.includes(key);
              return (
                <Checkbox
                  key={key}
                  id={`${path}-${key}`}
                  label={choice.label}
                  checked={on}
                  onChange={(next) =>
                    setField(
                      path,
                      next
                        ? [...(raw as unknown[]), choice.value]
                        : (raw as unknown[]).filter((value) => String(value) !== key)
                    )
                  }
                />
              );
            })}
          </span>
        </Field>
      );
    }

    case 'select':
      return (
        <Field title={item.label} hint={item.help}>
          <Select
            id={path}
            ariaLabel={item.label}
            value={String(raw ?? '')}
            options={(item.choices ?? []).map((choice) => ({ value: String(choice.value), label: choice.label }))}
            onChange={(next) => {
              const match = (item.choices ?? []).find((choice) => String(choice.value) === next);
              setField(path, match ? match.value : next);
            }}
          />
        </Field>
      );

    case 'color': {
      const palette = paletteFor(config.palette.preset, config.palette as unknown as Record<string, string>);
      const tokens = item.tokens ?? [];
      // 数组色（customColors）= 勾选语义：勾上就把该 token 的色加进数组。
      if (Array.isArray(raw)) {
        const list = raw.map(String);
        return (
          <Field title={item.label} hint={item.help}>
            <span className='flex min-w-0 flex-wrap justify-end gap-2'>
              {tokens.map((token) => {
                const color = palette[token];
                const on = list.includes(color);
                return (
                  <Checkbox
                    key={token}
                    id={`${path}-${token}`}
                    label={TOKEN_LABEL[token] ?? token}
                    checked={on}
                    onChange={(next) =>
                      setField(path, next ? [...list, color] : list.filter((value) => value !== color))
                    }
                  />
                );
              })}
            </span>
          </Field>
        );
      }
      const current = typeof raw === 'string' ? raw : '';
      return (
        <Field title={item.label} hint={item.help}>
          <span className='flex min-w-0 flex-wrap justify-end gap-2'>
            {tokens.map((token) => {
              const color = palette[token];
              const tone = token in TOKEN_LABEL && !(token in palette) ? toneColor(token) : '';
              const value = color ?? tone;
              const active = current === value || (tone !== '' && current === tone);
              return (
                <button
                  key={token}
                  type='button'
                  aria-pressed={active}
                  onClick={() => setField(path, value)}
                  className={`flex items-center gap-2 rounded-full border px-3 py-1 fs-caption transition-colors ${
                    active ? 'border-primary bg-primary/15' : 'text-muted-foreground hover:bg-accent'
                  }`}
                >
                  <span
                    aria-hidden
                    className='inline-block size-3 rounded-full border border-border'
                    style={{ background: value }}
                  />
                  {TOKEN_LABEL[token] ?? token}
                </button>
              );
            })}
          </span>
        </Field>
      );
    }

    case 'text':
      return (
        <Field title={item.label} hint={item.help}>
          <TextInput
            id={path}
            ariaLabel={item.label}
            value={typeof raw === 'string' ? raw : ''}
            placeholder={item.placeholder}
            onChange={(next) => setField(path, next)}
          />
        </Field>
      );

    case 'file':
      return <WallpaperFileRow item={item} />;

    default:
      return null;
  }
}

/** 壁纸本机文件选择：只落 IndexedDB，永不上传。文件本体是二进制，不进配置树。 */
function WallpaperFileRow({ item }: { item: AppearanceField }) {
  const { config, setField } = useAppearance();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async (file: File) => {
    setBusy(true);
    setError(null);
    const id = `wp-${Date.now().toString(36)}`;
    const stored = await putWallpaperBlob(id, file);
    setBusy(false);
    if (!stored) {
      setError('这个文件没能存进本机存储（可能太大，或浏览器禁用了本地存储）。换个小一点的文件，或在浏览器设置里允许本站保存数据。');
      return;
    }
    if (config.wallpaper.blobId) void deleteWallpaperBlob(config.wallpaper.blobId);
    // 顺序有意：先写文件、再切类型，避免出现「类型已是视频但 blob 还没就绪」的一帧。
    setField('wallpaper.blobId', id);
    setField('wallpaper.mode', file.type.startsWith('video/') ? 'video' : 'image');
  };

  return (
    <Field title={item.label} hint={item.help}>
      <span className='flex flex-wrap items-center gap-2'>
        <WallpaperThumb />
        <label className='inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border bg-card px-3 fs-body hover:bg-accent'>
          <Upload className='size-4' />
          {busy ? '正在保存…' : '选择文件'}
          <input
            type='file'
            accept='video/*,image/*'
            className='sr-only'
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) void pick(file);
            }}
          />
        </label>
        {config.wallpaper.blobId && (
          <button
            type='button'
            className='inline-flex h-8 items-center gap-2 rounded-md border bg-card px-3 fs-body text-muted-foreground hover:bg-accent'
            onClick={() => {
              if (config.wallpaper.blobId) void deleteWallpaperBlob(config.wallpaper.blobId);
              setField('wallpaper.blobId', null);
              setField('wallpaper.mode', 'shader');
            }}
          >
            <Trash2 className='size-4' />
            清除
          </button>
        )}
      </span>
      {error && <p className='w-full fs-caption text-tone-warn'>{error}</p>}
    </Field>
  );
}

/** 日志高亮规则表：关键字/正则 → 前景/背景 tone。 */
function HighlightRulesEditor() {
  const { config, setField } = useAppearance();
  const rules = config.logView.rules;
  const patch = (index: number, next: Partial<HighlightRule>) =>
    setField(
      'logView.rules',
      rules.map((rule, position) => (position === index ? { ...rule, ...next } : rule))
    );
  return (
    <div className='flex flex-col gap-2 border-t py-3'>
      <div className='flex items-center justify-between gap-2'>
        <p className='fs-caption text-muted-foreground'>
          规则越多每条日志要过的检查越多，超过 10 条在高速日志下会掉帧。
        </p>
        <button
          type='button'
          className='inline-flex h-8 shrink-0 items-center gap-2 rounded-md border px-3 fs-caption hover:bg-accent'
          onClick={() =>
            setField('logView.rules', [
              ...rules,
              { id: `rule-${Date.now().toString(36)}`, pattern: '', regex: false, fg: '', bg: '', scope: 'text', enabled: true },
            ])
          }
        >
          <Plus className='size-4' />
          加一条
        </button>
      </div>
      {rules.map((rule, index) => (
        <div key={rule.id} className='flex flex-wrap items-end gap-2 rounded-md border px-3 py-2'>
          <TextInput
            id={`rule-${index}-pattern`}
            ariaLabel='关键字或正则'
            value={rule.pattern}
            placeholder='关键字或正则'
            onChange={(pattern) => patch(index, { pattern })}
          />
          <Checkbox id={`rule-${index}-regex`} label='按正则' checked={rule.regex} onChange={(regex) => patch(index, { regex })} />
          <Select
            id={`rule-${index}-fg`}
            ariaLabel='文字色'
            value={rule.fg}
            options={TONE_CHOICES.map((tone) => ({ value: tone.value, label: `文字 ${tone.label}` }))}
            onChange={(fg) => patch(index, { fg: fg as ToneName })}
          />
          <Select
            id={`rule-${index}-bg`}
            ariaLabel='底色'
            value={rule.bg}
            options={TONE_CHOICES.map((tone) => ({ value: tone.value, label: `底色 ${tone.label}` }))}
            onChange={(bg) => patch(index, { bg: bg as ToneName })}
          />
          <Select
            id={`rule-${index}-scope`}
            ariaLabel='作用范围'
            value={rule.scope}
            options={[
              { value: 'text', label: '只染文字' },
              { value: 'row', label: '整行染色' },
            ]}
            onChange={(scope) => patch(index, { scope: scope as HighlightRule['scope'] })}
          />
          <Checkbox id={`rule-${index}-on`} label='启用' checked={rule.enabled} onChange={(enabled) => patch(index, { enabled })} />
          <button
            type='button'
            aria-label='删除这条规则'
            className='inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent'
            onClick={() => setField('logView.rules', rules.filter((_rule, position) => position !== index))}
          >
            <Trash2 className='size-4' />
          </button>
        </div>
      ))}
    </div>
  );
}

/** 快捷键绑定表：动作 → 组合键（冲突由下方文字说明，不静默吞）。 */
function KeyBindingsEditor() {
  const { config, setField } = useAppearance();
  const bindings = config.interaction.bindings;
  const patch = (index: number, next: Partial<KeyBinding>) =>
    setField(
      'interaction.bindings',
      bindings.map((row, position) => (position === index ? { ...row, ...next } : row))
    );
  // 组合键去重：同一个 keys 出现在多个动作里 = 后者会被静默吃掉，这里提前点名。
  const seen = new Map<string, number>();
  const conflicts = new Set<string>();
  for (const row of bindings) {
    const key = row.keys.trim().toLowerCase();
    if (!key) continue;
    if (seen.has(key)) conflicts.add(key);
    seen.set(key, (seen.get(key) ?? 0) + 1);
  }
  return (
    <div className='flex flex-col gap-2 border-t py-3'>
      <div className='flex items-center justify-between gap-2'>
        <p className='fs-caption text-muted-foreground'>
          {conflicts.size > 0
            ? `有 ${conflicts.size} 组组合键重复：${[...conflicts].join(' / ')}——同一组合键只会触发排在前面的动作。`
            : '每个动作一个组合键；留空 = 不绑定。'}
        </p>
        <button
          type='button'
          className='inline-flex h-8 shrink-0 items-center gap-2 rounded-md border px-3 fs-caption hover:bg-accent'
          onClick={() => setField('interaction.bindings', [...bindings, { action: '', keys: '' }])}
        >
          <Plus className='size-4' />
          加一条
        </button>
      </div>
      {bindings.map((row, index) => {
        const conflict = row.keys.trim() !== '' && (seen.get(row.keys.trim().toLowerCase()) ?? 0) > 1;
        return (
          <div key={`${row.action}-${index}`} className='flex flex-wrap items-center gap-2 rounded-md border px-3 py-2'>
            <TextInput
              id={`binding-${index}-action`}
              ariaLabel='动作'
              value={row.action}
              placeholder='动作（如 open-logs）'
              onChange={(action) => patch(index, { action })}
            />
            <TextInput
              id={`binding-${index}-keys`}
              ariaLabel='组合键'
              value={row.keys}
              placeholder='如 g o / ctrl+k'
              invalid={conflict}
              onChange={(keys) => patch(index, { keys })}
            />
            {conflict && <span className='fs-caption text-tone-warn'>重复</span>}
            <button
              type='button'
              aria-label='删除这条绑定'
              className='ml-auto inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent'
              onClick={() => setField('interaction.bindings', bindings.filter((_row, position) => position !== index))}
            >
              <Trash2 className='size-4' />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/** 组 id → 图标（参考图每组有一个小图标块；缺省不给图标，不编）。 */
const GROUP_ICON: Record<string, typeof Sparkles> = {
  wallpaper: Image,
  aurora: Aperture,
  iridescence: Sparkles,
  glow: Zap,
  glass: Contrast,
  typography: Type,
  motion: Blend,
  palette: Palette,
  layout: Rows3,
  charts: Gauge,
  logView: ScrollText,
  interaction: Keyboard,
  notifications: Sparkles,
  locale: Type,
  a11y: SwatchBook,
  density: Table2,
  performance: Zap,
};

/** 一组卡片（组标题/说明来自字段表，字段逐行渲染，两个特殊组补专用表）。
 *
 * 🔴 W13-V2：**分组必须是可折叠的**。改之前 17 组全部展开，1440 视口下
 * `documentElement.scrollHeight` 实测 18,998px（390 宽 21,857px ≈ 26 屏）——
 * 用户原话「面板不能乱堆砌文字，应该用多层、多开关、展开等」，而这一页就是一条
 * 一万九千像素的纵向表单。现在用原生 `<details>/<summary>`：
 *   · 零依赖、自带键盘操作与无障碍语义（Tab 到 summary、Enter/Space 展开）；
 *   · 展开状态由页面持有（左栏目录点击要能把对应组打开并滚过去）；
 *   · 收起只藏内容，**不删控件**——字段仍逐行渲染在 DOM 里，只是不可见，
 *     所以「能改」这件事没有为了缩高度打折。
 */
function AppearanceGroupCard({
  group,
  open,
  onToggle,
}: {
  group: AppearanceGroup;
  open: boolean;
  onToggle: (next: boolean) => void;
}) {
  const Icon = GROUP_ICON[group.id];
  return (
    <details
      id={`group-${group.id}`}
      open={open}
      onToggle={(event) => onToggle(event.currentTarget.open)}
      className='glass-panel scroll-mt-24 rounded-lg border px-4 py-3'
    >
      <summary className='group flex cursor-pointer list-none flex-wrap items-center gap-4 [&::-webkit-details-marker]:hidden'>
        {Icon && (
          <span
            aria-hidden
            className='flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary'
          >
            <Icon className='size-4' />
          </span>
        )}
        <span className='flex min-w-0 flex-1 flex-col gap-1'>
          <span className='fs-card'>{group.title}</span>
          <span className='fs-caption text-muted-foreground'>{group.hint}</span>
        </span>
        <span className='shrink-0 rounded-full border px-2 py-1 fs-caption tabular-nums text-muted-foreground'>
          {group.items.length}
        </span>
        <ChevronDown
          aria-hidden
          className='size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none'
        />
      </summary>
      <div className='flex flex-col border-t pt-3'>
        {group.items.map((item) => (
          <FieldRow key={`${group.id}.${item.key}`} group={group} item={item} />
        ))}
        {group.id === 'logView' && <HighlightRulesEditor />}
        {group.id === 'interaction' && <KeyBindingsEditor />}
      </div>
    </details>
  );
}

/**
 * 分组卡片列（顺序即字段表顺序）。
 *
 * `groups` 是**必填**而不是可选：这个组件曾经无参渲染全部 17 组，于是页面上的搜索
 * 只换了左栏目录的高亮、右侧照旧把 17 组全画出来 —— 「搜索没反应」的一半就出在这里。
 * 现在调用方必须把过滤结果传进来，没有「默认全量」这条后路。
 *
 * `openGroups` / `onToggleGroup` 同理必填：展开状态归页面（左栏目录点击要联动展开），
 * 组件自己再存一份就会两份真相打架。
 *
 * 密度：`max-w-6xl` 把每行夹在 1152px 内，屏幕上再宽也不会出现「标签在最左、
 * 滑动条在最右、中间一大片空」的散架感。**不居中**：卡片与页面标题左对齐
 * （居中会让标题孤零零挂在左上、卡片浮在中间）；右栏那一片由预览栏占位。
 * 组间距 `gap-4`（16px）：V 席实测改前三套间距并存（12 / 16 / 24），全站收敛到 16。
 */
export function AppearanceGroups({
  groups,
  openGroups,
  onToggleGroup,
}: {
  groups: AppearanceGroup[];
  openGroups: readonly string[];
  onToggleGroup: (id: string, next: boolean) => void;
}) {
  return (
    <div className='flex w-full max-w-6xl flex-col gap-4'>
      {groups.map((group) => (
        <AppearanceGroupCard
          key={group.id}
          group={group}
          open={openGroups.includes(group.id)}
          onToggle={(next) => onToggleGroup(group.id, next)}
        />
      ))}
    </div>
  );
}
