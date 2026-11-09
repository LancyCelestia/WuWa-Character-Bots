// 外观工作室的**右侧预览栏**（W13 执行席 L）。
//
// 用户原话（需求 G6）：「左分组、中调整、右侧全空白，补齐右侧」。空白真因不是内边距，
// 是这一页原本只有两栏：`max-w-6xl` 的分组卡左对齐，宽屏右边就空着。补的不是一块
// 好看的图，而是**同一批 CSS 变量的第二个观察窗**——它读 `apply.ts` 写在 <html> 上的
// 那些变量，而不是复制一份配置再画一遍（复制出来的必然与真实渲染漂移）。
//
// 因此这个组件里**没有任何一处写死的视觉数值**：壁纸滤镜读 --wp-*、玻璃读 --glass-*、
// 圆角读 --r-*、字号读 --fs-*、配色读 --ap-*、虹彩读 --ir-*、辉光读 --glow-*。
// 「预览是不是真的反映设置」由此变成结构事实：改不动预览 ⇔ 对应变量没有消费端，
// 而后者由 src/lib/appearance-consumption.test.ts 逐枚锁住。
//
// 壁纸预览用的是**真文件**：与全站壁纸同一份 IndexedDB blob（useWallpaperObjectUrl），
// 不是缩略图占位。所以「我选的这段 mp4 到底长什么样」在这里就能确认。
import type { CSSProperties } from 'react';
import { useAppearance } from '@/lib/appearance/context';
import { useInterfacePrefs } from '@/components/settings/interface-prefs';
import { wallpaperOwner } from '@/lib/wallpaper-owner';
import { cn } from '@/lib/utils';
import { useWallpaperObjectUrl } from './background-stage';

/** 六枚品牌色票：名字 + 它对应的变量（不写色值，色值只在用户配置里）。 */
const SWATCHES: Array<{ label: string; token: string }> = [
  { label: '品牌', token: '--ap-brand' },
  { label: '辅助紫', token: '--ap-purple' },
  { label: '深基底', token: '--ap-deep' },
  { label: '危险', token: '--ap-danger' },
  { label: '成功', token: '--ap-success' },
  { label: '警示', token: '--ap-warning' },
];

const WALLPAPER_LABEL: Record<string, string> = {
  none: '无（露出雾底）',
  shader: '着色器（3D 粒子）',
  image: '本地图片',
  video: '本地视频',
};

/**
 * 右侧预览栏。`xl` 以下整块收起——三栏在 1024–1279 会把分组卡挤到 400px 以下，
 * 那是本波不该制造的第二个问题。
 */
export function AppearancePreview() {
  const { effective } = useAppearance();
  const { prefs } = useInterfacePrefs();
  const { wallpaper } = effective;
  const needsLocal = wallpaper.mode === 'image' || wallpaper.mode === 'video';
  const localUrl = useWallpaperObjectUrl(needsLocal, wallpaper.blobId);
  const owner = wallpaperOwner(wallpaper, prefs.wallpaperEnabled);

  return (
    <aside
      className='hidden w-80 shrink-0 flex-col gap-3 xl:sticky xl:top-20 xl:flex'
      aria-label='外观实时预览'
    >
      <section className='glass-panel rounded-lg border px-3 py-3'>
        <h2 className='mb-2 fs-card'>实时预览</h2>
        <p className='mb-2 fs-caption text-muted-foreground'>
          这一块读的就是全站正在用的那批 CSS 变量。它不变，说明对应设置没有接管画面。
        </p>

        {/* 壁纸 + 玻璃 + 圆角 + 虹彩 + 配色，一次看全 */}
        <div className='relative mb-3 flex h-44 w-full items-center justify-center overflow-hidden rounded-md border'>
          {localUrl ? (
            wallpaper.mode === 'video' ? (
              <video
                className='ap-preview-wall'
                src={localUrl}
                muted
                loop
                autoPlay
                playsInline
                tabIndex={-1}
                aria-hidden
              />
            ) : (
              <img className='ap-preview-wall' src={localUrl} alt='' aria-hidden />
            )
          ) : (
            <span className='ap-preview-wall-missing' aria-hidden />
          )}

          {/* 玻璃卡：--glass-alpha / --glass-border / --glass-elev / --r-panel 全在这块上 */}
          <div className='glass-panel relative z-10 flex flex-col gap-1 rounded-lg border px-3 py-2'>
            <span className='iridescent-line fs-caption'>虹彩釉线</span>
            <span className='fs-page'>标题 18</span>
            <span className='fs-body text-muted-foreground'>正文 14 字重</span>
            <span className='fs-num num-iris'>128</span>
          </div>
        </div>

        {/* 配色：六枚色票，每枚靠内联转发把 --ap-* 接到 .ap-swatch 的底色上 */}
        <div className='mb-3 flex flex-wrap gap-1'>
          {SWATCHES.map((swatch) => (
            <span key={swatch.token} className='flex items-center gap-1 fs-caption text-muted-foreground'>
              <span
                aria-hidden
                className='ap-swatch size-3 shrink-0 rounded-full border'
                style={{ ['--ap-swatch' as string]: `var(${swatch.token})` } as CSSProperties}
              />
              {swatch.label}
            </span>
          ))}
        </div>

        {/* 辉光：--glow-color / --glow-r / --glow-alpha（同一组变量驱动全站按钮 hover） */}
        <div className='flex flex-wrap items-center gap-2'>
          <span className='ap-glow-sample inline-flex items-center rounded-full border px-2 py-1 fs-caption'>
            辉光
          </span>
          <span className='fs-caption text-muted-foreground'>
            圆角 {effective.layout.radius}px · 间距 {effective.layout.spacing}×
          </span>
        </div>
      </section>

      {/* 壁纸归属：两套入口的互斥在这里对用户说清楚（判据与全站同一个函数） */}
      <section className='glass-panel rounded-lg border px-3 py-3'>
        <h2 className='mb-1 fs-card'>壁纸归属</h2>
        <p className={cn('fs-caption', owner === 'appearance' ? 'text-primary' : 'text-muted-foreground')}>
          当前生效：{WALLPAPER_LABEL[wallpaper.mode] ?? wallpaper.mode}
        </p>
        <p className='fs-caption text-muted-foreground'>
          {owner === 'appearance'
            ? '内置/地址壁纸已让路——同一屏只播一层。'
            : owner === 'interface'
              ? '外观页没选本地文件，这里播的是设置里的内置/地址壁纸。'
              : '两边都没开，露出的是雾底。'}
        </p>
        {needsLocal && !localUrl && (
          <p className='mt-1 fs-caption text-tone-warn'>
            选的是本地文件，但本机库里找不到它（浏览器可能清过数据）。回上面重新选一次。
          </p>
        )}
      </section>

      {/* 字重不走类（body 的字重无法在样式表里跨文件读变量），这里直接把同一枚变量挂上 */}
      <p className='fs-caption text-muted-foreground' style={{ fontWeight: 'var(--ty-weight)' }}>
        这一行跟着「正文字重」与「字距」变。
      </p>
    </aside>
  );
}
