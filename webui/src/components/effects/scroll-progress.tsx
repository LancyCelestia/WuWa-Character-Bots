// 滚动进度条 + 顶栏「已滚动」联动 + hero 视差（参考站 daniya.top `main.js` 62-76 行）。
//
// 参考站把三件事写在一个 `onScroll` 里：进度条宽度、顶栏类名、hero 的 `--hp`。
// 本仓拆成「纯公式（use-scroll-state.ts）+ 两个渲染件」：
//   · `ScrollProgress` 只画那条 2px 虹彩带
//   · `useScrollState()` 的数据另供顶栏与 hero 用（它们各自消费，不互相知道）
//
// 🔴 进度条宽度走 `transform: scaleX()`：参考站每帧写 `style.width` 会重排，
//    而这条带 z-index:90 常驻在视口顶，重排代价直接落在每一帧上。
import { useScrollState } from '@/lib/effects/use-scroll-state';

export function ScrollProgress() {
  const { progress } = useScrollState();
  return (
    <div className='scroll-progress' aria-hidden>
      <i style={{ transform: `scaleX(${progress})` }} />
    </div>
  );
}
