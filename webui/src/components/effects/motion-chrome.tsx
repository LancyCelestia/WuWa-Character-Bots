// 动效层的总装配（W17）。参考站 daniya.top 是 MPA，所有动效脚本摊在 `main.js` 一个 IIFE 里；
// 本仓是 React SPA，必须让每个动效**各自**管生命周期，且共用同一份环境判据。
//
// 这个文件只做三件事：
//   ① 读一次环境事实（`useMotionFacts`）并算档位；
//   ② 按档位决定挂哪些件（气泡场要路径、光标要判据、揭示要武装）；
//   ③ 把 `data-*` 开关写到 `<html>` 供 CSS 侧消费。
//
// 消费方：`AppShell` 挂在 `.bg-stage` 里（气泡场）+ 根部（幕布/光标/进度条）。
import { useEffect } from 'react';

import { BubbleField } from '@/components/effects/bubble-field';
import { BootCurtain } from '@/components/effects/boot-curtain';
import { CustomCursor } from '@/components/effects/custom-cursor';
import { ScrollProgress } from '@/components/effects/scroll-progress';
import { resolveMotionTier, shouldUseCustomCursor } from '@/lib/effects/motion-tier';
import { useMotionFacts } from '@/lib/effects/use-motion-facts';
import { useAppearance } from '@/lib/appearance/context';

/** 气泡场：唯一需要读档位与上限的件。`AppShell` 把它挂进 `.bg-stage`。 */
export function MotionBubbles() {
  const { config } = useAppearance();
  const facts = useMotionFacts(!config.motion.enabled);
  if (!facts) return null;
  return <BubbleField facts={facts} />;
}

/**
 * 根部动效件：幕布 + 进度条 + 光标 + `<html>` 的 data 开关。
 *
 * 为什么 `<html>` 上写 `data-cursor` 而不直接给节点加类：光标那两个 div 是 fixed 的，
 * 但它们的**可见性**要能被「减少动效」与「动效关闭」两条 CSS 规则同时关掉，
 * 而这两条规则都写在 `:root[…]` 上。挂类名到 body 会让选择器分叉（body vs html）。
 */
export function MotionChrome() {
  const { config } = useAppearance();
  const facts = useMotionFacts(!config.motion.enabled);
  const tier = facts ? resolveMotionTier(facts) : 'lite';
  const showCursor = facts ? shouldUseCustomCursor(facts) && tier !== 'off' : false;

  // 把档位写到 <html>，供 CSS 侧的 `[data-motion-tier]` 消费（例如 lite 档降级某些装饰）。
  useEffect(() => {
    document.documentElement.dataset.motionTier = tier;
    return () => {
      delete document.documentElement.dataset.motionTier;
    };
  }, [tier]);

  return (
    <>
      <BootCurtain />
      <ScrollProgress />
      {showCursor ? <CustomCursor /> : null}
    </>
  );
}
