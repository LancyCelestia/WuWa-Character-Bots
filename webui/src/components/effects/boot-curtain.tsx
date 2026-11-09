// 首帧幕布（参考站 daniya.top `.preloader` + `main.js` 第 14-30 行）。
//
// 参考站逐字：
//   `delay = reduce ? 0 : 520`；`pre.classList.add('is-done')`；`root.classList.add('is-loaded')`
//   1100ms 后 `pre.remove()`
//   兜底：2600ms 后无论如何强制收掉（「never trap the page behind the preloader」）
//
// 本仓的两处改写：
//   ① **只在首次会话播一次**（`sessionStorage`）：参考站是 MPA，每次文档加载播一次合理；
//      本仓是 SPA，路由切换不重挂，天然只播一次——sessionStorage 只是防「刷新又盖一遍」。
//   ② 不 `remove()` 节点：卸载由 React 状态驱动，退出过渡（0.9s opacity）才走得完。
import { useEffect, useState } from 'react';

const SEEN_KEY = 'webui:boot-curtain-seen';
/** 参考站同值：淡出前等 520ms（reduce 时 0）。 */
const HOLD_MS = 520;
/** 参考站同值：淡出过渡 0.9s，留 1.1s 再摘节点。 */
const LINGER_MS = 1100;
/** 参考站同值：兜底强收时限。 */
const SAFETY_MS = 2600;

function prefersReducedMotion(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** 本次会话是否已经播过幕布。读不到 sessionStorage（隐私模式）时按「播过」处理——宁可不播。 */
function alreadySeen(): boolean {
  try {
    return window.sessionStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return true;
  }
}

function markSeen(): void {
  try {
    window.sessionStorage.setItem(SEEN_KEY, '1');
  } catch {
    /* 隐私模式禁写：下次刷新再播一次，不算错误 */
  }
}

export function BootCurtain() {
  const [mounted, setMounted] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (alreadySeen()) return;
    markSeen();
    setMounted(true);

    const hold = prefersReducedMotion() ? 0 : HOLD_MS;
    const fade = window.setTimeout(() => setDone(true), hold);
    const drop = window.setTimeout(() => setMounted(false), hold + LINGER_MS);
    // 兜底：任何情况下都不许把页面永远挡在幕布后（参考站 2600ms 同款保险）。
    const safety = window.setTimeout(() => {
      setDone(true);
      setMounted(false);
    }, SAFETY_MS);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(drop);
      window.clearTimeout(safety);
    };
  }, []);

  // 幕布不拦截读屏（参考站 `aria-hidden="true"` 同款）：它只是视觉过渡。
  if (!mounted) return null;
  return (
    <div className='boot-curtain' data-done={done ? '1' : '0'} aria-hidden>
      <div className='flex flex-col items-center'>
        <span className='boot-curtain__mark'>
          <svg viewBox='0 0 44 44' width='44' height='44' fill='none' aria-hidden>
            <circle cx='22' cy='22' r='15' stroke='currentColor' strokeWidth='1' />
            <circle cx='22' cy='22' r='6.5' fill='currentColor' opacity='.55' />
            <circle cx='16.5' cy='16' r='2.6' fill='currentColor' opacity='.85' />
          </svg>
        </span>
        <p className='boot-curtain__word fs-caption eyebrow'>SHOREKEEPER</p>
        <span className='boot-curtain__bar'>
          <i />
        </span>
      </div>
    </div>
  );
}
