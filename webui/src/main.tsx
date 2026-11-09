import { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { ThemeProvider } from '@/context/theme-context';
import { AppearanceProvider } from '@/lib/appearance/context';
import { ApiError } from '@/lib/api-client';
import { shouldRetryQuery } from '@/lib/data-state';
// UI3：`@/boot-hash` 已删除（browser history 不再折 hash，见 router.tsx 末尾一段）。
// 顺序约束仍在：router 实例在模块求值时就读地址栏，所以它必须早于第一次渲染。
import { applyPrefsEarly } from '@/components/settings/interface-prefs';
import { router } from '@/router';
// Initialize i18n
import '@/lib/i18n';
import '@/index.css';
// 外观配置的消费端（W13-L）：必须排在 index.css **之后** —— 同名选择器靠后写 +
// `:root` 前缀双重稳压。为什么单独一份、以及退役条件，见文件头。
import '@/components/appearance/appearance-wiring.css';

// 入口组织保留自 AxonHub frontend/src/main.tsx（Apache-2.0，已注明修改：
// 裁掉 authStore/handleServerError/sonner/SearchProvider/FontProvider 等本项目不需要的连带）。

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // 鉴权/不存在/后端故障/限速不重试；网络类（status 0）与 5xx 抖动最多重试 2 次。
        // 429 必须在这份名单里：控制面的失败计数**按来源累计**（auth.py：60 秒内 5 次失败
        // 即锁），重试每多一次就把锁定窗口往后推一次——用户实测「第 6 次起 429，等 70 秒
        // 才恢复」，而 1s+2s 的两次重试正好是把它钉住的那两颗钉子。
        // 判据的单一事实源是 `@/lib/data-state` 的 shouldRetryQuery（本文件与 use-semantic-query
        // 各自只做 ApiError → 判据字段的投影，不再各抄一份状态码黑名单）。
        if (error instanceof ApiError) {
          return shouldRetryQuery({ status: error.status, code: error.code }, failureCount);
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
      staleTime: 10 * 1000,
    },
  },
});

// 界面偏好（字号档/背景强度）在首帧前落地，避免「先画默认再跳」。
applyPrefsEarly();

const rootElement = document.getElementById('root')!;
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          {/* 外观总线在最外层：一挂载就把 CSS 变量写进 <html>，全站（含登录态外壳）一起变。 */}
          <AppearanceProvider>
            <RouterProvider router={router} />
          </AppearanceProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>
  );
}
