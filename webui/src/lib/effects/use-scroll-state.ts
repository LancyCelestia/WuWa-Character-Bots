// 滚动进度条（参考站 daniya.top `main.js` 第 62-76 行，逐字移植判定）。
//
// 参考站逐字：
//   var max = doc.documentElement.scrollHeight - window.innerHeight;
//   bar.style.width = (max > 0 ? Math.min(1, y / max) * 100 : 0) + '%';
//   nav.classList.toggle('is-scrolled', y > 24);          ← 24px 后顶栏上玻璃
//   hero.style.setProperty('--hp', Math.min(1, y / (innerHeight * 0.9)))  ← 视差淡出
//   rAF 节流用 `ticking` 布尔 + { passive: true }
//
// 🔴 本仓改写：宽度改 `transform: scaleX()`（参考站每帧写 width = 每帧重排一条 2px 条），
//    视差 `--hp` 改为返回数值由调用方消费（`setProperty` 是门禁 V4 封死通道）。
import { useEffect, useRef, useState } from 'react';

/** 顶栏「已滚动」阈值 —— 参考站原文 `y > 24`。 */
export const NAV_SCROLLED_AT = 24;
/** 视差归一化分母 —— 参考站原文 `innerHeight * 0.9`。 */
export const HERO_PARALLAX_SPAN = 0.9;

/** 0..1 的滚动进度。参考站同式：`min(1, y / max)`，max ≤ 0 时归零。 */
export function scrollProgress(scrollY: number, scrollHeight: number, innerHeight: number): number {
  const max = scrollHeight - innerHeight;
  if (!(max > 0)) return 0;
  return Math.min(1, Math.max(0, scrollY / max));
}

/** 0..1 的 hero 视差量。参考站同式：`min(1, y / (innerHeight * 0.9))`。 */
export function heroParallax(scrollY: number, innerHeight: number): number {
  const span = innerHeight * HERO_PARALLAX_SPAN;
  if (!(span > 0)) return 0;
  return Math.min(1, Math.max(0, scrollY / span));
}

export interface ScrollState {
  /** 0..1 进度 */
  progress: number;
  /** 是否已越过 `NAV_SCROLLED_AT` */
  scrolled: boolean;
  /** 0..1 hero 视差量 */
  hero: number;
}

/**
 * 订阅滚动。**每帧只算三个数**，重绘由调用方决定（进度条走 CSS transform，顶栏走 data 属性）。
 *
 * 参考站用 `ticking` 布尔做 rAF 节流，`{ passive: true }` —— 两条都照抄。
 */
export function useScrollState(): ScrollState {
  const [state, setState] = useState<ScrollState>({ progress: 0, scrolled: false, hero: 0 });
  const ticking = useRef(false);

  useEffect(() => {
    const measure = () => {
      const y = window.scrollY || window.pageYOffset;
      const next: ScrollState = {
        progress: scrollProgress(y, document.documentElement.scrollHeight, window.innerHeight),
        scrolled: y > NAV_SCROLLED_AT,
        hero: heroParallax(y, window.innerHeight),
      };
      // 三个值都没变就不 setState（参考站没有这一层，它每次都写 DOM）。
      setState((prev) =>
        prev.progress === next.progress && prev.scrolled === next.scrolled && prev.hero === next.hero
          ? prev
          : next
      );
      ticking.current = false;
    };
    const onScroll = () => {
      if (ticking.current) return;
      ticking.current = true;
      window.requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  return state;
}
