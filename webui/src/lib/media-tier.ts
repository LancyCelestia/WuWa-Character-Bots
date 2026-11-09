// 背景视频档位判定（UI3 性能预算的纯函数面）。零 React 依赖，`node --test` 直接加载。
//
// 用户服务器 2C2T / 2G RAM / 20GB 月流量：视频是最贵的资源，档位判定必须可测，
// 不能散在组件的 if 里（散进去就等于没有判据）。

export type VideoTier = '720p' | '1080p' | null;

export interface NetworkHints {
  /** `navigator.connection.saveData`：用户开了省流量模式。 */
  saveData?: boolean;
  /** `navigator.connection.effectiveType`：'slow-2g' | '2g' | '3g' | '4g'。 */
  effectiveType?: string;
  /** 用户在设置面板里关掉了动态壁纸（缺省＝开）。 */
  wallpaperEnabled?: boolean;
}

/** 顺带读一下 `navigator.connection`（Chromium 有，Safari/Firefox 没有 ⇒ 缺省不省流量）。 */
export function readNetworkHints(): NetworkHints {
  if (typeof navigator === 'undefined') return {};
  const nav = navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } };
  return {
    saveData: Boolean(nav.connection?.saveData),
    effectiveType: nav.connection?.effectiveType,
  };
}

/**
 * 选档。判定顺序即优先级：
 *   ① 用户关掉了壁纸 → 不加载（`null`，不是「加载一个更小的」）；
 *   ② 省流量模式 → 不加载；
 *   ③ 2g/3g → 720p（4.9 MB 在 3G 上要十几秒，观感不如不看）；
 *   ④ 视口 ≥ 900px → 1080p，否则 720p。
 *
 * 🔴 不按 devicePixelRatio 选：壁纸是氛围，2 倍屏拉 1080p 只会多烧带宽、看不出差别。
 */
export function pickVideoTier(width: number, network: NetworkHints): VideoTier {
  if (network.wallpaperEnabled === false) return null;
  if (network.saveData) return null;
  const slow =
    network.effectiveType === 'slow-2g' ||
    network.effectiveType === '2g' ||
    network.effectiveType === '3g';
  if (slow) return '720p';
  return width >= 900 ? '1080p' : '720p';
}

/** 档位 → 资源路径（与 public/assets 下的文件名一一对应）。 */
export function videoSrcFor(tier: VideoTier): string | null {
  return tier === null ? null : `/console/assets/bg-${tier}.mp4`;
}
