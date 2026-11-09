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

// 守岸人控制台：本地多文件产物，按 /console/ 挂载；不依赖外部 CDN。
export default defineConfig(({ command }) => ({
  base: '/console/',
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
    // 本机产物只服务回环面（控制面 /ui、/console），不走公网 CDN 分发。
    //
    // ── esbuild tmp 删除失败（UI2 记录的坑，UI3 已解）────────────────────────
    // 旧记录：本机 esbuild 0.28.2 的 JS shim 把 >1 MiB 的输入落到 `os.tmpdir()` 再让
    // Go 侧 `remove`，而该删除被拒 ⇒ 构建在 `vite:esbuild-transpile` 阶段整批失败：
    //   [vite:esbuild-transpile] remove C:\...\Temp\esbuild-<hex>: Access is denied.
    // 旧解法是 `minify: false` + `target: 'esnext'`（两行缺一不可），代价＝产物不压缩：
    // index ≈1.31 MB 明文、gzip 272 KB。
    //
    // 🔴 UI3 实测：只要 **TMPDIR/TMP/TEMP 指向工程内可写目录**（scripts/build.sh 干这事），
    //    那条删除路径就不再被拒 ⇒ `minify: true` + `target: 'esnext'` 构建 rc=0，
    //    index 1,328,658 B → 497,225 B（gzip 162,970 B）。所以 minify 开回来。
    //    绕过 build.sh 直跑 `npx vite build` 仍会撞旧坑——这是有意的：让唯一的构建
    //    姿势成立，而不是让每个构建姿势各自妥协。
    target: 'esnext',
    minify: true,
    cssMinify: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // 拆包理由（不是审美）：
        //  · react/react-dom/tanstack 这类**永远要拉**的挤在一个 vendor chunk 里 →
        //    业务页改动不会让它的 hash 变，浏览器缓存命中率高；
        //  · recharts 已由 `lazyRouteComponent` 天然隔离在 CartesianChart-*.js（只在
        //    /calls 与 /tokens 拉）。这里**不**再手动归组：再插一刀就把它的 hash 绑到
        //    vendor 上，等于让「改一行路由」也失效那张 ~340 KB 的缓存。
        //  · lucide-react 是逐枚具名导入，tree-shake 后随页面走，不单独成包。
        //  · three（C 席 3D 记忆球）必须单独成包：它只被 `/memory-graph` 的 lazy chunk 引用，
        //    拆出来后首屏入口的静态 import 图里根本走不到它 —— grep 首屏 JS 不应出现 three。
        //    单独成包还让它自带可复用 hash：改业务代码不会让这 ~470 KB 的缓存作废。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          if (/node_modules[\\/]three[\\/]/.test(id)) return 'vendor-three';
          if (id.includes('recharts') || id.includes('d3-')) return undefined;
          if (
            /node_modules[\\/](react|react-dom|scheduler|@tanstack|use-sync-external-store)[\\/]/.test(id)
          ) {
            return 'vendor-react';
          }
          if (
            /node_modules[\\/](i18next|react-i18next|clsx|tailwind-merge|class-variance-authority|lucide-react)[\\/]/.test(id)
          ) {
            return 'vendor-ui';
          }
          return undefined;
        },
      },
    },
  },
}));
