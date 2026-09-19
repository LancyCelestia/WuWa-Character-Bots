import { cn } from '@/lib/utils';

// 移植自 AxonHub frontend/src/components/ui/skeleton.tsx（Apache-2.0，已注明修改）。

function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot='skeleton' className={cn('bg-accent animate-pulse rounded-md', className)} {...props} />;
}

export { Skeleton };
