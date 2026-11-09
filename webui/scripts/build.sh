#!/usr/bin/env bash
# WebUI 唯一可用的构建姿势（本机 esbuild 0.28.2 的 tmp 删除权限 bug 的唯一绕法）。
#
# 为什么不是 `npm run build` / `npx vite build`：两者都会让 esbuild 的 JS shim 把
# >1 MiB 的输入落到 os.tmpdir() 再被 Go 侧 remove，删除被拒 ⇒ 构建整批失败：
#   [vite:esbuild-transpile] remove C:\...\Temp\esbuild-<hex>: Access is denied.
# 把 TMPDIR/TMP/TEMP 指到工程内可写目录后，那条路径不再被拒，**minify 也可以开着**
# （见 vite.config.ts 里 minify 一段的实验记录）。
#
# ⚠️ rc 必须 `cmd; echo rc=$?` 单独取，不能接管道（管道吞 rc）。
set -u
cd "$(dirname "$0")/.." || exit 1
# 🔴 用**独立**的 tmp 目录（不是 `.vite-tmp`）：并发的截图席会在 `.vite-tmp` 里放
# 无头 Chrome 的 user-data-dir，那些 LevelDB 文件常驻句柄，esbuild 写同一个目录会被
# 「Device or resource busy」拖死（实测整批构建失败）。名字带 build 以示区分。
mkdir -p .vite-tmp-build
export TMPDIR="$PWD/.vite-tmp-build" TMP="$PWD/.vite-tmp-build" TEMP="$PWD/.vite-tmp-build"

echo "── ① 版式宪法门 ──"
node scripts/layout-constitution.mjs
GATE=$?
echo "gate rc=$GATE"
if [ "$GATE" -ne 0 ]; then
  rm -rf .vite-tmp-build
  exit "$GATE"
fi

echo "── ② 构建 ──"
./node_modules/.bin/vite build
BUILD=$?
echo "build rc=$BUILD"

echo "── ③ 首屏关键路径体积 ──"
node scripts/measure-first-load.mjs
MEASURE=$?

rm -rf .vite-tmp-build
echo "measure rc=$MEASURE"
exit "$BUILD"
