// 动效环境事实的读取（DOM 侧）——判定本身在 `lib/effects/motion-tier.ts`（纯函数）。
//
// 参考站 daniya.top 在 `main.js` 顶部一次性读三个 MQL：
//   `reduce`      = matchMedia('(prefers-reduced-motion: reduce)').matches
//   `finePointer` = matchMedia('(hover: hover) and (pointer: fine)').matches
//   DPR           = Math.min(devicePixelRatio || 1, 2)
// 本仓多读三项业务约束（外观页动效开关 / 省流量 / 核数）。
//
// 🔴 全部在**挂载后**读：`matchMedia` 与 `navigator` 在 SSR / 首帧之前不可用。
import { useEffect, useState } from 'react';

import type { MotionFacts } from '@/lib/effects/motion-tier';
import { readNetworkHints } from '@/lib/media-tier';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';
const TOUCH_ONLY = '(hover: none) and (pointer: coarse)';

/** 探一次 WebGL2 就不留痕迹：建 1×1 canvas、取上下文、立刻丢弃。 */
function probeWebGL2(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return canvas.getContext('webgl2') !== null;
  } catch {
    return false;
  }
}

/** 立刻读一份事实（只在客户端调用）。 */
export function readMotionFacts(userDisabled: boolean): MotionFacts {
  const network = readNetworkHints();
  return {
    prefersReduced: typeof matchMedia === 'function' && matchMedia(REDUCED_MOTION).matches,
    userDisabled,
    saveData: Boolean(network.saveData),
    hardwareConcurrency:
      typeof navigator !== 'undefined' && navigator.hardwareConcurrency
        ? navigator.hardwareConcurrency
        : 4,
    isTouchOnly: typeof matchMedia === 'function' && matchMedia(TOUCH_ONLY).matches,
    hasWebGL2: probeWebGL2(),
    viewportWidth: typeof window === 'undefined' ? 0 : window.innerWidth,
  };
}

/**
 * 订阅环境变化：视口宽（resize）、系统减少动效、触屏与否。
 * 省流量 / 核数 / WebGL2 在一次会话里不会变，只在首次读。
 */
export function useMotionFacts(userDisabled: boolean): MotionFacts | null {
  const [facts, setFacts] = useState<MotionFacts | null>(null);

  useEffect(() => {
    const refresh = () => setFacts(readMotionFacts(userDisabled));
    refresh();

    const reduced = window.matchMedia(REDUCED_MOTION);
    const touch = window.matchMedia(TOUCH_ONLY);
    // resize 去抖：拖窗口时每像素触发一次 matchMedia + 重算档位没有意义。
    let timer = 0;
    const onResize = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, 200);
    };
    reduced.addEventListener('change', refresh);
    touch.addEventListener('change', refresh);
    window.addEventListener('resize', onResize, { passive: true });
    return () => {
      window.clearTimeout(timer);
      reduced.removeEventListener('change', refresh);
      touch.removeEventListener('change', refresh);
      window.removeEventListener('resize', onResize);
    };
  }, [userDisabled]);

  return facts;
}
