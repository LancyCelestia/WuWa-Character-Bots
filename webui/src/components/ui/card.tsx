import * as React from 'react';
import { cn } from '@/lib/utils';

// 移植自 AxonHub frontend/src/components/ui/card.tsx（Apache-2.0，已注明修改）。
// rounded-xl 已在 token 层钉为卡片值册 --r-shell:30px。
//
// 视觉层：卡片不再「一块纯色 + 一条灰边」，而是取 index.css 的 `surface` 毯子
// （纸面渐变 + 顶沿内高光 + 细描边 + 值册投影）。间距从 gap-6/py-6 收到 gap-4/py-4：
// 旧值在 22px 标题行高处让卡片显得松垮，收紧后信息密度才配得上「控制台」。
// 圆角从 30px 降为面板档 18px（rounded-lg）——30px 只留给侧栏/抽屉这类大容器，
// 内容卡用 18 才是同一套同心圆语言（外壳半径 > 内核半径）。

function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card'
      // UI3：p-4（内外一致的四边留白）+ gap-3 —— 悬浮卡片要「有厚度」，内边距不能再只有
      // 上下、左右靠 Header/Content 各自 px-6（那会让边框到内容的距离左右 ≠ 上下）。
      className={cn('surface text-card-foreground flex flex-col gap-3 rounded-lg p-4', className)}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card-header'
      className={cn(
        '@container/card-header grid auto-rows-min grid-rows-[auto_auto] items-start gap-2 has-data-[slot=card-action]:grid-cols-[1fr_auto] [.border-b]:pb-6',
        className
      )}
      {...props}
    />
  );
}

// 基类不得带行高类：twMerge 识别不了自定义 @utility fs-*，内建行高工具类会在
// 产物层叠中恒压过调用方传入的 fs-card（行高塌陷为 1，多行标题粘连）。行高单一来源=fs-* 阶梯。
// 注：此处不写该类名字面量——Tailwind v4 扫描器会连注释里的候选类一起生成进产物。
function CardTitle({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot='card-title' className={cn('font-semibold', className)} {...props} />;
}

function CardDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot='card-description' className={cn('text-muted-foreground fs-caption', className)} {...props} />;
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot='card-action'
      className={cn('col-start-2 row-span-2 row-start-1 self-start justify-self-end', className)}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot='card-content' className={cn('min-w-0', className)} {...props} />;
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot='card-footer' className={cn('flex items-center [.border-t]:pt-4', className)} {...props} />;
}

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent };
