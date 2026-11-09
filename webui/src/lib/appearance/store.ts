// 外观配置的持久化（UI3 追加二）：IndexedDB 键 `webui:appearance:v1`。
//
// 为什么不用 localStorage：用户选本地壁纸后要把**文件本体**留在本机，localStorage
// 只能放字符串（base64 让 12 MB 视频膨胀到 16 MB 且撞 5 MB 配额）。IndexedDB 能直接
// 存 Blob，下次打开 `URL.createObjectURL` 即可，零网络、永不上传。
//
// 两件事都在同一个库里：`config` 存配置树，`wallpaper` 存文件。降级/覆盖标记这类
// 「本机一次性」开关走 localStorage（它们不是外观数据，也不该被导出分享）。

import { DEFAULT_APPEARANCE } from './defaults.ts';
import { normalizeAppearance } from './presets.ts';
import type { AppearanceConfig } from './types.ts';

export const DB_NAME = 'webui:appearance';
export const DB_VERSION = 1;
export const STORE_CONFIG = 'config';
export const STORE_WALLPAPER = 'wallpaper';
/** 配置记录的键（用户裁定：`webui:appearance:v1`）。 */
export const CONFIG_KEY = 'webui:appearance:v1';
/** 「用户已声明要满血」的覆盖标记（localStorage）。 */
const OVERRIDE_KEY = 'webui:appearance:override';

function hasIndexedDb(): boolean {
  return typeof indexedDB !== 'undefined';
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_CONFIG)) db.createObjectStore(STORE_CONFIG);
      if (!db.objectStoreNames.contains(STORE_WALLPAPER)) db.createObjectStore(STORE_WALLPAPER);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function tx<T>(store: string, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const transaction = db.transaction(store, mode);
        const request = run(transaction.objectStore(store));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
      })
  );
}

/** 读配置：没有记录 / 读失败 / 数据坏了 → 一律回落默认值（宁可丢设置，不可白屏）。 */
export async function loadAppearance(): Promise<{ config: AppearanceConfig; repaired: boolean }> {
  if (!hasIndexedDb()) return { config: structuredClone(DEFAULT_APPEARANCE), repaired: false };
  try {
    const raw = await tx<unknown>(STORE_CONFIG, 'readonly', (store) => store.get(CONFIG_KEY));
    if (!raw) return { config: structuredClone(DEFAULT_APPEARANCE), repaired: false };
    return normalizeAppearance(raw);
  } catch {
    return { config: structuredClone(DEFAULT_APPEARANCE), repaired: true };
  }
}

/** 写配置（失败不抛：持久化失败只影响「刷新后还在」，不该阻断实时预览）。 */
export async function saveAppearance(config: AppearanceConfig): Promise<boolean> {
  if (!hasIndexedDb()) return false;
  try {
    await tx(STORE_CONFIG, 'readwrite', (store) => store.put(config, CONFIG_KEY));
    return true;
  } catch {
    return false;
  }
}

/** 存用户本地壁纸文件（IndexedDB 里只留 Blob，不给 service worker、不出网络）。 */
export async function putWallpaperBlob(id: string, file: Blob): Promise<boolean> {
  if (!hasIndexedDb()) return false;
  try {
    await tx(STORE_WALLPAPER, 'readwrite', (store) => store.put(file, id));
    return true;
  } catch {
    return false;
  }
}

export async function getWallpaperBlob(id: string): Promise<Blob | null> {
  if (!hasIndexedDb()) return null;
  try {
    const blob = await tx<Blob | undefined>(STORE_WALLPAPER, 'readonly', (store) => store.get(id));
    return blob ?? null;
  } catch {
    return null;
  }
}

export async function deleteWallpaperBlob(id: string): Promise<void> {
  if (!hasIndexedDb()) return;
  try {
    await tx(STORE_WALLPAPER, 'readwrite', (store) => store.delete(id));
  } catch {
    // 清不掉只是占一点本机空间，不阻断换壁纸。
  }
}

/** 用户是否已声明「不要降级」。 */
export function readOverride(signature: string): boolean {
  try {
    return localStorage.getItem(OVERRIDE_KEY) === signature;
  } catch {
    return false;
  }
}

export function writeOverride(signature: string | null): void {
  try {
    if (signature) localStorage.setItem(OVERRIDE_KEY, signature);
    else localStorage.removeItem(OVERRIDE_KEY);
  } catch {
    // 隐私模式下 localStorage 可能拒绝写，当作没覆盖。
  }
}
