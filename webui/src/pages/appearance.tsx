// 外观工作室（UI3 追加二）：`/console/appearance`。
//
// 形态（用户裁定参考 P4）：**左栏分组目录 + 右侧分组卡片**，每项「中文标题 + 中文说明 + 控件」。
// 底部一条常驻动作栏：重置默认 / 导出 JSON / 导入 JSON / 强制满效果。
//
// 保存是**不需要的**——每次改动都已走 `setField` 写进 IndexedDB（250 ms 静默后落盘），
// 所以这里没有「保存」按钮，只有「已自动保存」的状态字与导入结果的提示。
//
// 分组清单不在这里手写：`APPEARANCE_FIELDS` 就是唯一真身（17 组），页面只负责摆位置。
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, RotateCcw, Search, Sparkles, Upload } from 'lucide-react';
import { AppearanceGroups } from '@/components/appearance/groups';
import { AppearancePreview } from '@/components/appearance/preview';
import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/appearance/field';
import { useAppearance } from '@/lib/appearance/context';
import { cloneAppearance, DEFAULT_APPEARANCE } from '@/lib/appearance/defaults';
import { deserializeAppearance, PRESETS, serializeAppearance } from '@/lib/appearance/presets';
import { APPEARANCE_FIELDS } from '@/lib/appearance/schema-fields';
import {
  DEFAULT_OPEN_LIMIT,
  initialOpenGroups,
  openGroup,
  reconcileOpenGroups,
  toggleGroup,
} from '@/components/appearance/groups-collapse';
import { cn } from '@/lib/utils';

/** 高亮关键字：只在目录里标亮命中的组，不改列表顺序（顺序即「从视觉到功能」的叙事）。 */
function groupMatches(groupTitle: string, hint: string, query: string): boolean {
  if (!query.trim()) return false;
  const needle = query.trim().toLowerCase();
  return groupTitle.toLowerCase().includes(needle) || hint.toLowerCase().includes(needle);
}

/** 全部分组 id（顺序即字段表顺序），折叠状态的初始真身。 */
const ALL_GROUP_IDS = APPEARANCE_FIELDS.map((group) => group.id);

export function AppearancePage() {
  const { t } = useTranslation();
  const { config, replace, setOverridden, overridden, lastNotice, setLastNotice, loading } = useAppearance();
  const [query, setQuery] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  /**
   * 折叠状态（W13-V2）。改之前 17 组全展开 ⇒ 1440 下整页 18,998px（390 下 21,857px）。
   * 默认只开前 DEFAULT_OPEN_LIMIT 组：首屏立刻能改一项，其余收起成标题行。
   * 左栏目录点击会 openGroup + 滚过去——「点目录跳过去却发现是收着的」不算跳转。
   */
  const [openGroups, setOpenGroups] = useState<string[]>(() => initialOpenGroups(ALL_GROUP_IDS));

  const exportJson = () => {
    const blob = new Blob([serializeAppearance(config)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'shorekeeper-appearance.json';
    anchor.click();
    URL.revokeObjectURL(url);
    setLastNotice(t('appearance.action.exported'));
  };

  const importJson = async (file: File) => {
    const text = await file.text();
    const { config: next, repaired } = deserializeAppearance(text);
    replace(next);
    setLastNotice(repaired ? t('appearance.action.importedRepaired') : t('appearance.action.imported'));
  };

  const groups = APPEARANCE_FIELDS.filter((group) => !query.trim() || groupMatches(group.title, group.hint, query));

  // 搜索把某组滤掉后，它的 id 不该继续占着「已展开」；交集为空时回落到第一组，
  // 免得出现「一排标题、一个控件都看不见」的死页。判据是纯函数（groups-collapse.ts）。
  useEffect(() => {
    const ids = groups.map((group) => group.id);
    setOpenGroups((current) => reconcileOpenGroups(current, ids));
  }, [query]);

  /** 左栏目录点击：先把该组打开，再滚过去（原生锚点跳转不会改 <details> 的 open）。 */
  const jumpToGroup = (id: string) => {
    setOpenGroups((current) => openGroup(current, id));
    // 展开是 React 状态，等一帧再滚，否则滚到的是收起时的高度。
    requestAnimationFrame(() => {
      document.getElementById(`group-${id}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
  };

  const onToggleGroup = (id: string, next: boolean) => {
    // <details> 自己会改 DOM 的 open；这里只把 React 状态对齐（受控字段的来源必须是它）。
    setOpenGroups((current) => (next ? openGroup(current, id) : toggleGroup(current, id)));
  };

  return (
    <div className='flex w-full flex-col gap-4'>
      {/* 页头整块落在玻璃上：V 席实测副标题 12px 直接压生壁纸只有 2.04:1（WCAG 要 4.5），
          标题 18px 压壁纸 3.32:1 余量也薄。不去调字号（五档受门禁锁），只补底。 */}
      <header className='surface flex flex-wrap items-center gap-4 rounded-lg px-4 py-3'>
        <div className='flex flex-col gap-1'>
          <h1 className='fs-page'>{t('appearance.title')}</h1>
          <p className='fs-caption text-muted-foreground'>{t('appearance.subtitle')}</p>
        </div>
        {/* 状态胶囊：原来只有 border 没有底色，压在壁纸暗区实测 1.44:1 ——
            同一枚胶囊在 390 宽下因为那块壁纸亮而「看起来正常」，即它在随壁纸明暗碰运气。 */}
        <span className='ml-auto inline-flex items-center gap-2 rounded-full border surface-flat px-3 py-1 fs-caption text-muted-foreground'>
          <span aria-hidden className='inline-block size-2 rounded-full bg-tone-good' />
          {loading ? t('appearance.live.loading') : t('appearance.live.saved')}
        </span>
      </header>

      <div className='flex w-full flex-col gap-4 lg:flex-row lg:items-start'>
        {/* 左栏：搜索 + 分组目录 + 预设 */}
        <div className='flex w-full shrink-0 flex-col gap-4 lg:sticky lg:top-20 lg:w-72'>
          <nav className='glass-panel rounded-lg border px-3 py-3' aria-label={t('appearance.title')}>
            <label className='mb-2 flex items-center gap-2 rounded-md border px-2 py-1' htmlFor='appearance-search'>
              <Search aria-hidden className='size-4 shrink-0 text-muted-foreground' />
              <TextInput
                id='appearance-search'
                ariaLabel={t('appearance.search')}
                value={query}
                placeholder={t('appearance.search')}
                onChange={setQuery}
              />
            </label>
            <ul className='flex max-h-[46dvh] flex-wrap gap-1 overflow-y-auto lg:flex-col'>
              {APPEARANCE_FIELDS.map((group) => (
                <li key={group.id}>
                  <button
                    type='button'
                    onClick={() => jumpToGroup(group.id)}
                    aria-expanded={openGroups.includes(group.id)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 rounded-md px-3 py-1 text-left fs-caption transition-colors',
                      groupMatches(group.title, group.hint, query)
                        ? 'bg-primary/15 text-foreground'
                        : 'text-muted-foreground hover:bg-accent'
                    )}
                  >
                    <span>{group.title}</span>
                    <span className='tabular-nums opacity-60'>{group.items.length}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <section className='glass-panel rounded-lg border px-3 py-3'>
            <h2 className='fs-card'>{t('appearance.preset.title')}</h2>
            <p className='mb-2 fs-caption text-muted-foreground'>{t('appearance.preset.hint')}</p>
            <div className='flex flex-col gap-1'>
              {PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  type='button'
                  onClick={() => {
                    replace(cloneAppearance(preset.config));
                    setLastNotice(t('appearance.preset.applied', { name: preset.name }));
                  }}
                  className='flex flex-col items-start rounded-md border px-3 py-2 text-left transition-colors hover:bg-accent'
                >
                  <span className='flex items-center gap-2 fs-card'>
                    <Sparkles aria-hidden className='size-4 text-primary' />
                    {preset.name}
                  </span>
                  <span className='fs-caption text-muted-foreground'>{preset.hint}</span>
                </button>
              ))}
            </div>
          </section>
        </div>

        {/* 右栏：分组卡片（搜索时只显示命中的组）+ 底部动作栏 */}
        <div className='flex min-w-0 flex-1 flex-col gap-4'>
          {groups.length === 0 ? (
            <p className='glass-panel rounded-lg border px-4 py-6 fs-body text-muted-foreground'>
              {t('appearance.searchEmpty')}
            </p>
          ) : (
            // 🔴 传的是**过滤结果**，不是「全部 17 组」：组件自己曾经无参渲染全表，
            //    于是搜索只换左栏高亮、右侧照旧全画出来（「搜索只过滤左栏」的真因）。
            //    展开状态同理交给页面：组件自己再存一份，点目录那一半就联动不起来。
            <AppearanceGroups groups={groups} openGroups={openGroups} onToggleGroup={onToggleGroup} />
          )}

          {/* 动作栏（吸附在**右栏内**的底部）。
              旧版它是两栏之外的兄弟节点、`sticky bottom-3` 横跨整页宽；sticky 不占位，
              而左栏是 `lg:sticky lg:top-20`，于是这条栏在 1920 下压住「预设」卡片下半，
              四套预设只露两套半、字叠字（主代理 CDP 截图实测）。
              搬进右栏后只有两个变化：① 宽度被右栏夹住，几何上碰不到左栏；② sticky 的
              包含块变成右栏，滚到右栏末尾前它一直贴在视口底部 —— 既看得见，也不遮内容。
              移动端两栏堆叠，右栏仍是文档末尾，行为与普通页脚一致。 */}
          <footer className='glass-panel sticky bottom-3 z-10 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2'>
            <Button variant='outline' size='sm' onClick={() => replace(cloneAppearance(DEFAULT_APPEARANCE))}>
              <RotateCcw className='size-4' />
              {t('appearance.action.reset')}
            </Button>
            <Button variant='outline' size='sm' onClick={exportJson}>
              <Download className='size-4' />
              {t('appearance.action.export')}
            </Button>
            <Button variant='outline' size='sm' onClick={() => fileRef.current?.click()}>
              <Upload className='size-4' />
              {t('appearance.action.import')}
            </Button>
            <input
              ref={fileRef}
              type='file'
              accept='application/json,.json'
              className='sr-only'
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void importJson(file);
              }}
            />
            {overridden ? (
              <Button variant='ghost' size='sm' onClick={() => setOverridden(false)}>
                {t('appearance.action.followDevice')}
              </Button>
            ) : (
              <Button variant='ghost' size='sm' onClick={() => setOverridden(true)}>
                {t('appearance.action.forceFull')}
              </Button>
            )}
            {lastNotice && <p className='fs-caption text-muted-foreground'>{lastNotice}</p>}
          </footer>
        </div>

        {/* 右栏（第三栏）：实时预览（需求 G6「右侧全空白，补齐右侧」）。
            放在分组卡之后、`xl` 起显形：1280 以下三栏会把分组卡挤到 400px 以下，
            那时预览收起、页面回到「目录 + 调整」两栏，不制造第二个布局问题。 */}
        <AppearancePreview />
      </div>
    </div>
  );
}
