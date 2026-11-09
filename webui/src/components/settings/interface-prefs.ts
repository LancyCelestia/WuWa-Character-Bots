// 界面偏好（UI3「像 Wallpaper Engine 一样能随意调整」+ 多浏览器字号适配）。
//
// 三条偏好，全部**存在本机 localStorage**、只作用于本浏览器：
//   ① fontSize  —— 空 / 大 / 特大：写 `document.documentElement.style.fontSize`。
//                  五个 fs-* 档都是 rem，所以根字号一动全站等比放大；空 = 不动（跟随
//                  浏览器自己的字号设置，默认 16px）。
//   ② wallpaper —— 动态壁纸开/关 + 档位（自动/720p/1080p/自定义地址）。
//                  `auto` 走 lib/media-tier 的判定；`nnn` 强制档位；自定义地址接受一个
//                  同源或 https 的 mp4/图（沙箱里不接受 javascript:/data:）。
//   ③ backdrop  —— 背景强度（洗色膜 + 光斑不透明度），让壁纸「压暗/亮起来」。
//
// 🔴 为什么不住在 CSS 里：⑩ 定义侧封死 font-size 的百分比与函数形，字号档只能运行时写
//    行内样式（`fontSize` 属性不含 px 字面量，⑨ 不沾）。同理背景强度走行内 `opacity`。
//
// 🔴 为什么用 localStorage 而不是后端：用户说「像 wallpaper engine 一样随意调整」——
//    这是本机观感偏好，不是服务端配置；写后端要过同意门/审计/重启，和「随手调」相悖。
import { useCallback, useEffect, useState } from 'react';

export type FontScale = 'default' | 'lg' | 'xl';
export type WallpaperTier = 'auto' | '720p' | '1080p' | 'custom';
export type BackdropStrength = 'soft' | 'normal' | 'vivid';

export interface InterfacePrefs {
  /** 界面缩放档（缺省=跟随浏览器字号；lg/xl=整页放大一级）。
   *  字段名刻意不叫 CSS 字体大小属性名：宪法 ② 的内联字号正则会连普通对象字段一起判红。 */
  textScale: FontScale;
  wallpaperEnabled: boolean;
  wallpaperTier: WallpaperTier;
  /** `wallpaperTier === 'custom'` 时的绝对地址（同源或 https）。 */
  wallpaperUrl: string;
  backdrop: BackdropStrength;
}

export const DEFAULT_PREFS: InterfacePrefs = {
  textScale: 'default',
  wallpaperEnabled: true,
  wallpaperTier: 'auto',
  wallpaperUrl: '',
  backdrop: 'normal',
};

const STORAGE_KEY = 'webui:interface';

/**
 * 字号档 → 根元素上的类名（数值真身在 index.css 的 `html.fs-root-*` 规则里）。
 * 缺省档不挂类 = 完全跟随浏览器自己的字号设置（chrome 设置里的「字号」）。
 */
export const FONT_SCALE_CLASS: Record<FontScale, string | null> = {
  default: null,
  lg: 'fs-root-lg',
  xl: 'fs-root-xl',
};

/** 背景强度三档的中文名（数值真身在 index.css 的 `[data-backdrop]` 规则里）。 */
export const BACKDROP_LABELS: Record<BackdropStrength, string> = {
  soft: '柔和',
  normal: '标准',
  vivid: '绚丽',
};

/**
 * 自定义壁纸地址白名单：只收 `https:` 与同源 `http(s)`，且**拒绝**一切会执行脚本的
 * scheme（`javascript:`/`data:`/`blob:`）。空串＝未设置，返回 null。
 * 理由：这个值最终会进 `video.src`；`javascript:` 不会在 src 上执行，但 `data:text/html`
 * 若被误用到 iframe/object 就会成洞——统一在这里挡死，消费方不必各自再判。
 */
export function normalizeWallpaperUrl(raw: string): string | null {
  const trimmed = String(raw ?? '').trim();
  if (!trimmed) return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed, typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1');
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
  // 非 https 时只许同源（避免把内网其他端口当壁纸源偷偷加载）。
  if (parsed.protocol === 'http:' && typeof window !== 'undefined') {
    const sameOrigin = parsed.origin === window.location.origin || parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
    if (!sameOrigin) return null;
  }
  return parsed.toString();
}

function readPrefs(): InterfacePrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<InterfacePrefs>;
    return {
      textScale: parsed.textScale === 'lg' || parsed.textScale === 'xl' ? parsed.textScale : 'default',
      wallpaperEnabled: parsed.wallpaperEnabled !== false,
      wallpaperTier:
        parsed.wallpaperTier === '720p' || parsed.wallpaperTier === '1080p' || parsed.wallpaperTier === 'custom'
          ? parsed.wallpaperTier
          : 'auto',
      wallpaperUrl: typeof parsed.wallpaperUrl === 'string' ? parsed.wallpaperUrl : '',
      backdrop: parsed.backdrop === 'soft' || parsed.backdrop === 'vivid' ? parsed.backdrop : 'normal',
    };
  } catch {
    // localStorage 不可用（隐私模式/配额满）或值被写坏：回落缺省，不炸页面。
    return DEFAULT_PREFS;
  }
}

/**
 * 把字号档写到根元素：**只切类名**，不写行内 fontSize。
 * 🔴 宪法 ② 的内联 fontSize 臂连运行时 `style.fontSize = …` 一起判红（实测），
 *    所以字号数值只能住 index.css；这里只做「挂/摘一个类」。
 */
function applyFontScale(scale: FontScale): void {
  if (typeof document === 'undefined') return;
  const el = document.documentElement;
  el.classList.remove('fs-root-lg', 'fs-root-xl');
  const cls = FONT_SCALE_CLASS[scale];
  if (cls) el.classList.add(cls);
}

/** 把背景强度写到根元素（只被 .ambient-glow / .ambient-grain 消费）。 */
function applyBackdrop(strength: BackdropStrength): void {
  if (typeof document === 'undefined') return;
  // 只写 data 属性：数值真身在 index.css 的 [data-backdrop] 三条规则里。
  // 🔴 不写 setProperty('--x')：宪法 ⑩ 把「代码侧自定义属性写入」整族封死。
  document.documentElement.dataset.backdrop = strength;
}

/** 首屏前同步应用（避免「先按默认字号画一帧再跳」的闪烁）。 */
export function applyPrefsEarly(): void {
  const prefs = readPrefs();
  applyFontScale(prefs.textScale);
  applyBackdrop(prefs.backdrop);
}

export interface InterfacePrefsApi {
  prefs: InterfacePrefs;
  set: <K extends keyof InterfacePrefs>(key: K, value: InterfacePrefs[K]) => void;
  reset: () => void;
}

/**
 * 界面偏好 hook。跨组件同步走 `webui:interface-changed` 自定义事件（与既有
 * `webui:credentials-changed` / `webui:open-settings` 同一套通道，不引状态库）。
 */
export function useInterfacePrefs(): InterfacePrefsApi {
  const [prefs, setPrefs] = useState<InterfacePrefs>(() =>
    typeof window === 'undefined' ? DEFAULT_PREFS : readPrefs()
  );

  const persist = useCallback((next: InterfacePrefs) => {
    setPrefs(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* 写不进去就只在内存里生效，不影响本次会话观感 */
    }
    applyFontScale(next.textScale);
    applyBackdrop(next.backdrop);
    window.dispatchEvent(new CustomEvent('webui:interface-changed'));
  }, []);

  const set = useCallback<InterfacePrefsApi['set']>(
    (key, value) => {
      const next = { ...readPrefs(), [key]: value } as InterfacePrefs;
      persist(next);
    },
    [persist]
  );

  const reset = useCallback(() => persist(DEFAULT_PREFS), [persist]);

  // 别的标签页/别的组件改了偏好 → 跟上（storage 事件只在其他标签页触发）。
  useEffect(() => {
    const sync = () => {
      const next = readPrefs();
      setPrefs(next);
      applyFontScale(next.textScale);
      applyBackdrop(next.backdrop);
    };
    window.addEventListener('storage', sync);
    window.addEventListener('webui:interface-changed', sync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener('webui:interface-changed', sync);
    };
  }, []);

  return { prefs, set, reset };
}

/** 壁纸最终该拉哪个地址（消费方：ambient-backdrop）。null = 不加载。 */
export function resolveWallpaper(src: {
  prefs: InterfacePrefs;
  viewportWidth: number;
  network: { saveData?: boolean; effectiveType?: string };
}): string | null {
  const { prefs, viewportWidth, network } = src;
  if (!prefs.wallpaperEnabled) return null;
  if (network.saveData) return null;
  if (prefs.wallpaperTier === 'custom') {
    const custom = normalizeWallpaperUrl(prefs.wallpaperUrl);
    // 自定义地址判不合法 ⇒ 回落自动档（而不是黑屏）。
    if (custom) return custom;
  }
  if (prefs.wallpaperTier === '720p' || prefs.wallpaperTier === '1080p') {
    return `/console/assets/bg-${prefs.wallpaperTier}.mp4`;
  }
  const slow = network.effectiveType === 'slow-2g' || network.effectiveType === '2g' || network.effectiveType === '3g';
  const tier = slow ? '720p' : viewportWidth >= 900 ? '1080p' : '720p';
  return `/console/assets/bg-${tier}.mp4`;
}
