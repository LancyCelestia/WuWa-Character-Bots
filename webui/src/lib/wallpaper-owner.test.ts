// 壁纸「两套入口」互斥的纯口径（W13 执行席 L）。
//
// 背景壁纸今天有两条完全独立的入口，各存各的：
//   ① 外观工作室（`/appearance`）：IndexedDB 里的本地图片/视频 → `BackgroundStage`；
//   ② 设置弹窗：localStorage 的内置/地址壁纸 → `AmbientVideo`（`resolveWallpaper`）。
// 两边都只判自己那份配置，于是**两层可以同时播**——同一屏两块动态底叠着跑，
// 既费 GPU 又让「我到底在看哪张图」无法回答。旧代码把「互斥」写在注释里，代码上没有。
//
// 这里只做一件事：给定两份配置，回答「这一屏的壁纸归谁」。只有一个答案，
// 两条入口的组件都读它，才不会各判各的。
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { localWallpaperSelected, wallpaperOwner } from './wallpaper-owner.ts';

test('本地图片壁纸优先：与内置壁纸同时开着也只播一个', () => {
  assert.equal(wallpaperOwner({ mode: 'image', blobId: 'blob-1' }, true), 'appearance');
});

test('本地视频壁纸同样优先', () => {
  assert.equal(wallpaperOwner({ mode: 'video', blobId: 'blob-2' }, true), 'appearance');
});

test('没选本地文件时，内置壁纸照常生效', () => {
  assert.equal(wallpaperOwner({ mode: 'color', blobId: null }, true), 'interface');
});

test('选了「本地图片」但库里没有文件：不抢所有权，内置壁纸兜底（外观页另出提示）', () => {
  assert.equal(wallpaperOwner({ mode: 'image', blobId: null }, true), 'interface');
  assert.equal(localWallpaperSelected({ mode: 'image', blobId: null }), false);
});

test('两边都关着 = 没有壁纸（不假装有一层在画）', () => {
  assert.equal(wallpaperOwner({ mode: 'color', blobId: null }, false), 'none');
});

test('同一份输入永远只给出一个所有者（互斥的机器判据）', () => {
  const cases = [
    { mode: 'image', blobId: 'a' },
    { mode: 'video', blobId: 'b' },
    { mode: 'color', blobId: null },
  ];
  for (const local of cases) {
    for (const enabled of [true, false]) {
      const owner = wallpaperOwner(local, enabled);
      assert.ok(['appearance', 'interface', 'none'].includes(owner));
      // 选择了本地文件时，内置那一路必须让路 —— 这正是本波之前缺的那条
      if (localWallpaperSelected(local)) assert.notEqual(owner, 'interface');
    }
  }
});
