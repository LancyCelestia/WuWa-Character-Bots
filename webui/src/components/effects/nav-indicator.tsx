// 导航活跃指示器（参考站 daniya.top `main.js` 的 `movePill`，见 `lib/effects/indicator-box.ts`）。
//
// 参考站逐字：
//   const link = nav.querySelector('.nav__link.is-active')
//   pill.style.left  = link.offsetLeft + 'px'
//   pill.style.width = link.offsetWidth + 'px'
//   CSS: transition: left .6s var(--ease-out), width .6s var(--ease-out)
//
// 本仓的两处改写：
//   ① 写 `transform: translate3d()` + `inline-size`，不写 left/width
//      （left 每帧重排；transform 只走合成层。视觉结果一致，代价低一个量级）。
//   ② 指示器**同一条组件同时服务两处**（用户明确「垂直侧栏 + 顶置横向栏都要」）：
//      侧栏由 NavIndicator 包住 `<nav>` 竖排；顶栏由 NavStrip 横排。
//
// 观察方式：ResizeObserver + MutationObserver（属性变化监听 `class`），
// 因为 TanStack Router 给 `<Link>` 打的 `active` 类是运行时加的，React 不重渲染本组件。
import { useCallback, useEffect, useRef, useState } from 'react';

import { type Box, indicatorBox } from '@/lib/effects/indicator-box';
import { cn } from '@/lib/utils';

/** 读一个 HTMLAnchorElement 的盒子（相对视口）。 */
function readBox(el: HTMLElement): Box {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, width: r.width, height: r.height };
}

export interface NavIndicatorProps {
  /** 承载 `<a>` 的容器；指示器绝对定位在其中。 */
  children: React.ReactNode;
  className?: string;
  /** `vertical` 铺满宽（侧栏）、`horizontal` 铺满高（顶栏）。 */
  orientation?: 'vertical' | 'horizontal';
}

/**
 * 活跃项背后的那块玻璃。
 *
 * 三层退化都成立：
 *   · 没有活跃项（首页之外的未知路由）→ 指示器 `opacity:0`，不跳到 (0,0)；
 *   · 容器 `display:none`（移动端抽屉收起）→ `indicatorBox` 返回 null，保持原位；
 *   · 完全不支持 ResizeObserver → 只算一次，不跟窗口变。
 */
export function NavIndicator({ children, className, orientation = 'vertical' }: NavIndicatorProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  const measure = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const active = host.querySelector<HTMLElement>('a.active, [aria-current="page"]');
    if (!active) {
      setBox(null);
      return;
    }
    const next = indicatorBox(readBox(active), readBox(host));
    setBox(next ? { x: next.translateX, y: next.translateY, w: next.width, h: next.height } : null);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    measure();

    // 活跃项是路由切换时由 TanStack Router 改 class 的，React 侧不会重渲染这里；
    // MutationObserver 盯 `class` 与 `aria-current` 两条（Link 两种都写）。
    const mo =
      typeof MutationObserver === 'function'
        ? new MutationObserver(() => measure())
        : null;
    mo?.observe(host, { subtree: true, attributes: true, attributeFilter: ['class', 'aria-current'] });

    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => measure()) : null;
    ro?.observe(host);

    window.addEventListener('resize', measure, { passive: true });
    return () => {
      mo?.disconnect();
      ro?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [measure]);

  return (
    <div ref={hostRef} className={cn('nav-indicator-host', className)} data-orientation={orientation}>
      <span
        aria-hidden
        className='nav-indicator'
        data-orientation={orientation}
        data-visible={box ? '1' : '0'}
        style={
          box
            ? {
                transform: `translate3d(${box.x}px, ${box.y}px, 0)`,
                inlineSize: `${box.w}px`,
                blockSize: `${box.h}px`,
              }
            : undefined
        }
      />
      {children}
    </div>
  );
}
