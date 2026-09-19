import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// 守岸人 WebUI：构建产物单文件化（vite-plugin-singlefile）——
// 产出唯一自包含 dist/index.html，离线可开、零外部 CDN，挂 control_plane 静态目录。
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
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
});
