import { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { ThemeProvider } from '@/context/theme-context';
import { ApiError } from '@/lib/api-client';
import { router } from '@/router';
// Initialize i18n
import '@/lib/i18n';
import '@/index.css';

// 入口组织保留自 AxonHub frontend/src/main.tsx（Apache-2.0，已注明修改：
// 裁掉 authStore/handleServerError/sonner/SearchProvider/FontProvider 等本项目不需要的连带）。

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // 鉴权/不存在/后端故障不重试；网络类（status 0）与 5xx 抖动最多重试 2 次。
        if (error instanceof ApiError && [401, 403, 404, 500].includes(error.status)) return false;
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
      staleTime: 10 * 1000,
    },
  },
});

const rootElement = document.getElementById('root')!;
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <RouterProvider router={router} />
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>
  );
}
