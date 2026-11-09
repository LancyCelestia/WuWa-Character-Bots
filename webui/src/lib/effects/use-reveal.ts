// 滚动揭示（参考站 daniya.top `main.js` 第 32-54 行）。
//
// 参考站逐字：
//   new IntersectionObserver(entries => …, { rootMargin: '0px 0px -12% 0px', threshold: 0.12 })
//   进入 → 加 `.is-in` 并 `unobserve(el)`（一次性，不来回闪）
//   同一容器内的兄弟按 `idx * 0.09` 秒递进（写内联 `--d`）
//   无 IntersectionObserver 或 reduce → 直接全部可见
//
// 🔴 本仓的三处改写，每条都对应一个真实的坑：
//   ① **逐个元素自己观察**，不搞「全局武装 + 一次扫全树」。本仓是 SPA：路由一换，
//      新页面节点是在壳层 effect 之后才挂的，扫全树那版会漏掉它们，而全局 armed
//      又让它们初始透明 ⇒ 整页空白。逐元素观察没有这个时序问题。
//   ② **递进不用 `--d`**：参考站写 `el.style.setProperty('--d', …)`，本仓门禁 V4 整族封死。
//      这里把序号写进 `data-reveal-step`，延迟由 CSS 的 `[data-reveal-step='n']` 承担。
//   ③ **已在视口内就不做入场**。参考站只处理「滚动进入」，而本仓的卡片是路由切过来就
//      已经在视口里的——照抄参考站会给首屏元素闪一帧空白。所以挂载时先量一次：
//      已经可见 ⇒ 直接 `in`（无动画）；在视口外 ⇒ `armed` 后等 IO。
//
// 三态：`idle`（未武装，**无条件可见**）→ `armed`（透明待入）→ `in`（已入）。
// 初值是 `idle`，所以 JS 没跑起来 / IO 不存在 / reduce 为真时，内容原样可见。
import { useEffect, useRef, useState } from 'react';

/** 与参考站同值：`rootMargin: '0px 0px -12% 0px'`、`threshold: 0.12`。 */
const ROOT_MARGIN = '0px 0px -12% 0px';
const THRESHOLD = 0.12;

export type RevealState = 'idle' | 'armed' | 'in';

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function useReveal<T extends HTMLElement = HTMLDivElement>(
  enabled = true
): { ref: React.RefObject<T | null>; state: RevealState } {
  const ref = useRef<T | null>(null);
  const [state, setState] = useState<RevealState>('idle');

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!enabled || prefersReducedMotion() || typeof IntersectionObserver !== 'function') return;

    // ① 已经在视口里：直接终态，不做入场（避免首屏闪一帧空白）。
    //    `getBoundingClientRect()` 在这里是同步量，挂载后首次 layout 已定案。
    const rect = el.getBoundingClientRect();
    const vh = window.innerHeight || 0;
    const vw = window.innerWidth || 0;
    const inView = rect.top < vh && rect.bottom > 0 && rect.left < vw && rect.right > 0;
    if (inView) {
      setState('in');
      return;
    }

    setState('armed');
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          setState('in');
          // 一次性：出场后不再观察（参考站同样 unobserve）。
          io.unobserve(entry.target);
        }
      },
      { rootMargin: ROOT_MARGIN, threshold: THRESHOLD }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [enabled]);

  return { ref, state };
}
