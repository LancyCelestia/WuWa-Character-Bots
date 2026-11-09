// 自定义光标（逐条移植自参考站 daniya.top 的 `.cursor-dot` / `.cursor-ring` 与
// `main.js` 第 168-202 行）。
//
// 参考站的做法（逐字）：
//   · 建两个 div 挂到 body：`cursor-dot`（4px 实心点，跟手立即）与 `cursor-ring`（34px 圆环，lerp 缓动）
//   · `dot.style.transform = translate(mx-2, my-2)`
//   · `rx += (mx - rx) * 0.16` 一阶低通，rAF 里推进，**永不停止**
//   · hover 可点元素时给 ring 加 `.is-hover`（34→56px、暖橙描边、6% 填充）
//   · `mouseleave` 时摘掉 `body.cursor-on`（两个都淡出）
//
// 本仓的四处改写，各有理由：
//   ① **不新增 DOM 节点**：参考站往 body 里 append 两坨；本仓渲染成 React 节点，
//      卸载时随组件一起走（参考站那几个 div 永不离场）。
//   ② **rAF 会停**：参考站哪怕鼠标不动也一直跑；本仓在 `|Δ| < 0.1px` 时停表。
//   ③ **原生光标不隐藏**：与参考站一致（它也没写 `cursor: none`），但本仓额外在
//      触屏 / 减少动效 / 窄屏时**整个不挂**（见 `shouldUseCustomCursor`）。
//   ④ 位移走 `translate3d` 而非 `translate`（多一个 z 分量强制上合成层）。
import { useEffect, useRef } from 'react';

const HOVER_SELECTOR = 'a, button, input, select, textarea, [role="button"], [data-cursor-hover]';
/** 参考站的一阶低通系数：0.16。改这个就是改「环跟手的黏滞感」，别随手动。 */
const LERP = 0.16;
/** 低于这个距离（CSS px）就认为已经贴合，停 rAF。参考站没有这个出口。 */
const EPSILON = 0.1;

export function CustomCursor() {
  const dotRef = useRef<HTMLDivElement | null>(null);
  const ringRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const dot = dotRef.current;
    const ring = ringRef.current;
    if (!dot || !ring) return;

    let mx = window.innerWidth / 2;
    let my = window.innerHeight / 2;
    let rx = mx;
    let ry = my;
    let raf = 0;

    const step = () => {
      rx += (mx - rx) * LERP;
      ry += (my - ry) * LERP;
      // `offsetWidth/2` 让环以自身中心对齐指针（参考站同款）。
      const half = ring.offsetWidth / 2;
      ring.style.transform = `translate3d(${rx - half}px, ${ry - half}px, 0)`;
      if (Math.abs(mx - rx) < EPSILON && Math.abs(my - ry) < EPSILON) {
        raf = 0;
        return;
      }
      raf = window.requestAnimationFrame(step);
    };

    const onMove = (e: MouseEvent) => {
      mx = e.clientX;
      my = e.clientY;
      dot.style.transform = `translate3d(${mx - 2}px, ${my - 2}px, 0)`;
      document.documentElement.dataset.cursor = 'on';
      if (!raf) raf = window.requestAnimationFrame(step);
    };

    const onOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      ring.dataset.hover = target?.closest(HOVER_SELECTOR) ? '1' : '0';
    };

    const onLeave = () => {
      delete document.documentElement.dataset.cursor;
    };

    window.addEventListener('mousemove', onMove, { passive: true });
    document.addEventListener('mouseover', onOver, { passive: true });
    document.addEventListener('mouseleave', onLeave);

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseover', onOver);
      document.removeEventListener('mouseleave', onLeave);
      delete document.documentElement.dataset.cursor;
    };
  }, []);

  return (
    <>
      <div ref={dotRef} className='cursor-dot' aria-hidden />
      <div ref={ringRef} className='cursor-ring' aria-hidden data-hover='0' />
    </>
  );
}
