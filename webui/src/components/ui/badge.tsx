import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// 移植自 AxonHub frontend/src/components/ui/badge.tsx（Apache-2.0，已注明修改）。
//
// UI2 辉光：徽章是「辉光三类」之一。glow-badge 用 currentColor 派生一圈内描边 +
// 极淡外发光——色随语义走，不另起色值；只在有色的实心档挂，outline 档不挂（它没有底色）。

const badgeVariants = cva(
  'inline-flex items-center justify-center rounded-full border px-2 py-1 fs-caption font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden',
  {
    variants: {
      variant: {
        default: 'glow-badge border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90',
        secondary: 'glow-badge border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90',
        destructive:
          'glow-badge border-transparent bg-destructive text-destructive-foreground [a&]:hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60',
        success: 'glow-badge border-transparent bg-success text-success-foreground [a&]:hover:bg-success/90',
        outline: 'text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'span';

  return <Comp data-slot='badge' className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
