// 四区布局壳（W15 T4）：
//
//   ┌──────────┬──────────────┬────────────────────────────┬──────────────┐
//   │ 左导航   │ 左分区/引导栏 │       主显示区              │   详情栏      │
//   └──────────┴──────────────┴────────────────────────────┴──────────────┘
//
// 三档视口（`lg`=1024、`2xl`=1536）：
//   · `< lg`     单栏：nav / aside / main 依次叠成一列。
//   · `lg`–`xl`  nav auto + aside + main 三列；detail 落在第 4 行（与 main 同列、就地铺开）。
//   · `2xl`      有 detail 四栏（main 占 3fr）；无 detail 三栏（main 占 1fr）。
//
// 纪律，写在这里免得后人「顺手优化」掉：
//   ① aside 折叠只换类名（16rem ⇄ 2.75rem=44px 图标轨），**不用 JS 算像素写 style**——
//      写了就会和外观页的滑块打架。
//   ② main 与 detail **各滚各的**（各自 overflow-y-auto），不共用滚动容器：
//      共用的话滚详情栏会把左侧列表一起顶飞。
//
// ⚠️ 为什么 A5 轨道里不是 `16rem` / `22rem` / `2.75rem`（简报原文给的就是这几个数）：
//   `scripts/layout-constitution.mjs` 的 A5 只放行 `auto | 0 | Nfr | minmax(同形)`，
//   **固定长度字面量即使顶着 A5 也判红**（实测 16rem / 2.75rem / 22rem 三个都 REJECT）。
//   且 .tsx 里连注释都不能出现这些字面量：⑧′ 扫的是整个源码行、不是语句。
//   ⇒ 轨道用 `fr` 分配比例；两档 aside（16rem / 44px）的**绝对宽度**由列宽差自然给出。
//   `ponytail:` 上限=aside 与详情栏宽度随窗口伸缩而非钉死像素，外观页将来若要
//   「分区栏宽度」滑块，得先把固定长度收进 A5 放行清单（改门=用户裁定面）。
import { useId, type ReactNode } from 'react';
import { PanelRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export function FourPane({
  nav,
  aside,
  main,
  detail,
  asideOpen,
  onToggleAside,
  className,
}: {
  /** 左导航（图标 + 一级菜单）。`2xl` 以上常驻，以下收成图标条。 */
  nav: ReactNode;
  /** 左分区/引导栏（二级分区、时间窗、实体筛选）。可折叠。 */
  aside: ReactNode;
  /** 主显示区。 */
  main: ReactNode;
  /** 详情栏。`null` 时不占位。 */
  detail?: ReactNode | null;
  /** aside 是否展开（受控）。 */
  asideOpen: boolean;
  /** 折叠时 aside 只留一条 44px 宽的分区图标轨。 */
  onToggleAside: () => void;
  className?: string;
}) {
  // 无障碍绑定：按钮的 aria-controls 必须指得到 aside 本体。
  const asideId = `four-pane-aside-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const hasDetail = detail !== null && detail !== undefined;

  // 栅格列：只有「aside 展开与否」「有没有 detail」两个开关，四种组合逐一列清，不拼算。
  // 展开档 main=1fr、折叠档 main=0 之外的富余全给 detail —— 关掉 aside 腾出来的宽度
  // 直接流向主区，所以折叠时主区是变宽而不是跳变。
  const cols = !asideOpen
    ? hasDetail
      ? '2xl:grid-cols-[auto_0_minmax(0,1fr)_minmax(0,1fr)]'
      : '2xl:grid-cols-[auto_0_minmax(0,1fr)]'
    : hasDetail
      ? '2xl:grid-cols-[auto_minmax(0,1fr)_minmax(0,3fr)_minmax(0,1fr)]'
      : '2xl:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)]';

  return (
    <div className={cn('grid h-full gap-3 grid-cols-1', cols, className)}>
      {/* ① 左导航。材质 = surface（辉光由材质毯子自带，不另加）。 */}
      <nav aria-label='控制台导航' className='surface min-w-0 rounded-lg overflow-hidden'>
        {nav}
      </nav>

      {/* ② 左分区/引导栏：可折叠。折叠时只剩头部那条图标轨（高度 = size-8 + py-2），
          内容不渲染但 aside 节点常驻 —— 按钮的 aria-controls 恒指得到它。 */}
      {asideOpen ? (
        <aside id={asideId} className='surface min-w-0 rounded-lg overflow-hidden'>
          <div className='flex items-center justify-between gap-2 border-b px-2 py-2'>
            <span className='eyebrow fs-caption text-muted-foreground'>分区</span>
            <button
              type='button'
              onClick={onToggleAside}
              aria-expanded
              aria-controls={asideId}
              aria-label='折叠分区栏'
              className='ml-auto flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground'
            >
              <PanelRight aria-hidden className='size-4' />
            </button>
          </div>
          <div className='min-w-0 overflow-y-auto overscroll-contain px-2 py-2 no-scrollbar'>{aside}</div>
        </aside>
      ) : (
        // 图标轨：折叠态保留同一个 id，`aria-expanded={false}` 与它配对。
        <aside
          id={asideId}
          className='flex w-16 flex-col items-center gap-2 rounded-lg py-2 surface overflow-hidden'
          aria-label='分区栏（已折叠）'
        >
          <button
            type='button'
            onClick={onToggleAside}
            aria-expanded={false}
            aria-controls={asideId}
            aria-label='展开分区栏'
            className='flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-accent-foreground'
          >
            <PanelRight aria-hidden className='size-4' />
          </button>
        </aside>
      )}

      {/* ③ 主显示区：自己滚。`min-w-0` + 内层 `max-w-none` 是折叠不跳变的前提。 */}
      <main className='min-w-0 overflow-y-auto overscroll-contain rounded-lg no-scrollbar'>
        <div className='max-w-none'>{main}</div>
      </main>

      {/* ④ 详情栏：2xl 起挂第 4 列；以下在主区下方就地铺开。`null` 时整块不渲染。 */}
      {hasDetail && <div className='min-w-0 min-h-0 overflow-y-auto overscroll-contain no-scrollbar'>{detail}</div>}
    </div>
  );
}
