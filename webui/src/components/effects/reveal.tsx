// 滚动揭示的渲染件（判定逻辑在 `lib/effects/use-reveal.ts`）。
//
// 参考站 daniya.top 给每个要揭示的块加 `class="reveal"`，本仓改成 `data-reveal` 属性：
//   · 属性不参与 Tailwind 候选扫描，产物里不会留没人用的类名；
//   · 三态（idle/armed/in）由 hook 打，CSS 只认 `[data-reveal-state]`。
//
// 用法：
//   <Reveal><SectionCard …/></Reveal>
//   <Reveal as='li' step={2}>…</Reveal>
//
// 🔴 `step` 只接受 0—5：CSS 的递进规则只有 5 档（见 index.css），
//    传更大的值没有对应规则、会静默不生效——这里直接夹紧而不是放任。
import type { ReactNode } from 'react';

import { useReveal } from '@/lib/effects/use-reveal';
import { cn } from '@/lib/utils';

export interface RevealProps {
  children: ReactNode;
  /** 递进档位 0—5（每档 0.09s）。默认 0 = 不额外延迟。 */
  step?: number;
  className?: string;
  /** 语义标签，默认 div。 */
  as?: 'div' | 'section' | 'li' | 'article';
}

export function Reveal({ children, step = 0, className, as = 'div' }: RevealProps) {
  const Tag = as;
  const { ref, state } = useReveal<HTMLDivElement>(true);
  const clamped = Math.max(0, Math.min(5, Math.trunc(step)));
  return (
    <Tag
      ref={ref as never}
      className={cn(className)}
      data-reveal
      data-reveal-step={clamped}
      data-reveal-state={state}
    >
      {children}
    </Tag>
  );
}
