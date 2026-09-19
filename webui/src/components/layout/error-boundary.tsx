// 页面级渲染异常边界：路由内组件抛错时不再整树卸载（白屏），而是复用统一数据态卡呈现错误，
// 并把「重试」接回边界复位。调用方需以 key={pathname} 挂载，换页即自动清错。
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { SemanticState } from '@/components/semantic/semantic-state';

export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error | null } {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 只本机留痕：控制面没有前端错误上报端点，绝不外发任何数据。
    console.error('[webui] route render failed', error, info.componentStack);
  }

  private readonly reset = () => this.setState({ error: null });

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className='mx-auto w-full max-w-6xl'>
          <SemanticState state={{ phase: 'error', message: this.state.error.message }} onRetry={this.reset} />
        </div>
      );
    }
    return this.props.children;
  }
}
