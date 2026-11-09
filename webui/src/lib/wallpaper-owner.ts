// 壁纸「两套入口」互斥的唯一口径（W13 执行席 L）。
//
// 背景壁纸有两条完全独立的入口，各存各的：
//   ① 外观工作室（`/appearance`）：IndexedDB 里的本地图片/视频 → `BackgroundStage`；
//   ② 设置弹窗：localStorage 的内置/地址壁纸 → `AmbientVideo`（`resolveWallpaper`）。
// 两边原本都只判自己那份配置 ⇒ **两层可以同时播**，同一屏两块动态底叠着跑：
// 既费 GPU，又让「我现在看的到底是哪一张」无法回答。旧代码把「互斥」写在注释里，
// 代码上一条都没有。
//
// 这里只回答一个问题：这一屏的壁纸归谁。两个组件都读同一个答案，才不会各判各的。

/** 壁纸的所有者。`none` = 两边都没要求，露出雾底。 */
export type WallpaperOwner = 'appearance' | 'interface' | 'none';

/** 外观配置里与本地壁纸相关的两个字段（只取判定要用的部分，避免把整棵树拖进来）。 */
export interface LocalWallpaperLike {
  mode: string;
  blobId: string | null;
}

/**
 * 外观页是否真的选了一个**能播**的本地文件。
 * 选了「本地图片」但库里没有 blob（浏览器清过 IndexedDB / 换设备）不算——
 * 那时让它去抢所有权，用户会得到一块黑屏；交给内置壁纸兜底 + 外观页另出提示
 * 更有用，也不会让人误以为「我选的那张正在播」。
 */
export function localWallpaperSelected(local: LocalWallpaperLike): boolean {
  return (local.mode === 'image' || local.mode === 'video') && local.blobId !== null && local.blobId !== '';
}

/**
 * 这一屏的壁纸归谁。本地文件优先：外观页选的文件是用户**刚刚亲手挑的那一张**，
 * 设置里的内置/地址壁纸是更早、更泛的偏好，冲突时后者让路。
 */
export function wallpaperOwner(local: LocalWallpaperLike, ambientEnabled: boolean): WallpaperOwner {
  if (localWallpaperSelected(local)) return 'appearance';
  return ambientEnabled ? 'interface' : 'none';
}
