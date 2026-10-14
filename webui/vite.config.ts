import { randomBytes } from 'node:crypto';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
// React Refresh 注入 inline preamble；仅 dev HTML 每次转换授权随机 nonce。
// 不使用固定 html.cspNonce 占位值，也不放宽生产 index 的 script-src。
function devCsp(): Plugin {
  return {
    name: 'webui:dev-csp',
    apply: 'serve',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        const nonce = randomBytes(18).toString('base64');
        return html
          .replace("script-src 'self';", `script-src 'self' 'nonce-${nonce}';`)
          .replace(/<script\b([^>]*)>/gi, (_tag, attrs: string) => `<script${attrs} nonce="${nonce}">`);
      },
    },
  };
}

// 守岸人 WebUI：本地多文件产物，按 /ui/ 挂载；不依赖外部 CDN。
export default defineConfig(({ command }) => ({
  base: '/ui/',
  plugins: [react(), tailwindcss(), ...(command === 'serve' ? [devCsp()] : [])],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api/v1': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8742',
        changeOrigin: true,
      },
      '/admin/api/v1': {
        target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8742',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
}));
