// 环境背景层（W12 UI2 → UI3 性能预算）：视频 → 洗色压暗 → 漂移釉瑚光斑 → 云母颗粒，
// 四条 `position: fixed` 姊妹层，全部 `pointer-events-none`、`aria-hidden`，只负责「底」。
//
// 🔴 排版纪律：固定层**不挂在滚动容器里**（贴滚动容器的 backdrop-filter/固定层会每帧重绘
//   整条滚动带）；本组件挂在 AppShell 根部，与 <main> 平级。
// 🔴 动效纪律：光斑只动 transform（见 index.css 的 aurora-drift-*）——动 top/left/
//    background-position 会触发 layout/paint，动画会卡顿。
//
// ── UI3 性能预算（2C2T / 2G RAM / 20GB 月流量，硬约束）─────────────────────
// 原素材 2560×1440 HEVC = 12.9 MB，`preload="auto"` + 每次进页面就下 ⇒ 20 GB 只够
// 1587 次播放。现在四条硬规则：
//   ① **按需**：`preload="none"` + 只有可见（IntersectionObserver）且页面在前台才
//      `load()`；滚走/切到后台即 `pause()`（不卸载——重下比暂停贵）。
//   ② **分档**：720p 1.80 MB / 1080p 4.92 MB，按视口宽度与网络档位选；窄屏不拉 1080p。
//   ③ **省流量**：`navigator.connection.saveData === true` 时**完全不加载**视频，
//      走纯 CSS 釉瑚底（整页仍是完整的，只是没有实拍动态）。
//   ④ **降级**：prefers-reduced-motion / 解码失败（onError）→ 不渲染/藏掉播放器，
//      露出下面的雾底，不出现黑块或残帧。
//
// 素材：`webui/public/assets/bg-720p.mp4` / `bg-1080p.mp4`（ffmpeg 从原片转出，无音轨、
// faststart）。原始 2560 版改名为 `bg-source-2560.mp4` 只留本机，不入库也不上线。
//
// ⚠️ 后端对 `/console/assets/*` 目前发 `cache-control: no-store`（backend 不在本席可改面）
//    ⇒ 刷新即重下。这是本波已点名的遗留项；前端这边只能保证「不刷新就不重复下载」。
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { readNetworkHints } from '@/lib/media-tier';
import { resolveWallpaper, useInterfacePrefs } from '@/components/settings/interface-prefs';
import { useAppearance } from '@/lib/appearance/context';
import { wallpaperOwner } from '@/lib/wallpaper-owner';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

function subscribeReducedMotion(onChange: () => void): () => void {
  const mql = window.matchMedia(REDUCED_MOTION_QUERY);
  mql.addEventListener('change', onChange);
  return () => mql.removeEventListener('change', onChange);
}

function readReducedMotion(): boolean {
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/** 首帧前 SSR/无 window 时的缺省：按「要动」算，但视频本身有 muted/playsInline 保护。 */
function readReducedMotionServer(): boolean {
  return false;
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, readReducedMotion, readReducedMotionServer);
}

/**
 * 背景视频：静音+循环+playsInline 才能在无交互时自动播。`aria-hidden` + 无 controls：
 * 它只是氛围，不是内容。
 *
 * 🔴 加载时机（性能预算的主战场）：`<video preload="none">` 本身不发起任何媒体请求，
 * 只有 `load()` 才下。所以首帧之后这里盯两件事：① IntersectionObserver 可见性；
 * ② document.visibilityState。两者都为真才 load()+play()，任一为假即 pause()。
 * 单次播放成本从「每次进页面 12.9 MB」降到「真看见才下 1.8 / 4.9 MB」。
 */
export function AmbientVideo() {
  const reduced = usePrefersReducedMotion();
  const { prefs } = useInterfacePrefs();
  const { effective } = useAppearance();
  // 🔴 两套壁纸入口的互斥（W13-L）：外观页选了本地图片/视频时，这一路**必须让路**。
  // 以前两边各判各的配置，于是本地文件与内置视频可以同时铺满整屏——两层动态底叠着跑，
  // 既费 GPU，用户也说不清自己在看哪一张。判据只有一处：lib/wallpaper-owner。
  const appearanceOwnsWallpaper = wallpaperOwner(effective.wallpaper, prefs.wallpaperEnabled) === 'appearance';
  const hostRef = useRef<HTMLDivElement>(null);
  // 壁纸地址 = 档位判定（auto/强制/自定义）× 偏好 × 网络。null ⇒ 不加载。
  const computeSrc = () =>
    typeof window === 'undefined'
      ? null
      : resolveWallpaper({ prefs, viewportWidth: window.innerWidth, network: readNetworkHints() });
  const [src, setSrc] = useState<string | null>(computeSrc);
  const [visible, setVisible] = useState(false);
  const [failed, setFailed] = useState(false);

  // 偏好 / 视口 / 网络变化时重算（旋转屏幕、切省流量模式、在设置里换壁纸）；
  // 只在真变化时写 state，避免无谓重挂 <video>。
  useEffect(() => {
    const sync = () => {
      const next = resolveWallpaper({ prefs, viewportWidth: window.innerWidth, network: readNetworkHints() });
      setSrc((current) => (current === next ? current : next));
    };
    sync();
    window.addEventListener('resize', sync, { passive: true });
    window.addEventListener('webui:interface-changed', sync);
    return () => {
      window.removeEventListener('resize', sync);
      window.removeEventListener('webui:interface-changed', sync);
    };
  }, [prefs]);

  // 可见性：进视口才算「真被看见」。阈值 0 即可——它铺满视口，不存在「部分可见」。
  useEffect(() => {
    const host = hostRef.current;
    if (!host || reduced) return;
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((entry) => entry.isIntersecting)),
      { threshold: 0 }
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, [reduced]);

  // 可见 + 前台 + 有档位 → load 并播；否则暂停。
  useEffect(() => {
    const video = hostRef.current?.querySelector('video');
    if (!video) return;
    const canPlay = () => visible && src !== null && !failed && document.visibilityState === 'visible';
    const attempt = () => {
      if (!canPlay()) {
        video.pause();
        return;
      }
      // readyState 0 = 还没 load；重复调 load() 会取消当前下载，故只在真没加载时调。
      if (video.readyState === 0 && !video.currentSrc) video.load();
      void video.play().catch(() => {
        /* 自动播放被策略拒：保持静帧，不往控制台抛噪音 */
      });
    };
    attempt();
    document.addEventListener('visibilitychange', attempt);
    return () => document.removeEventListener('visibilitychange', attempt);
  }, [visible, src, failed]);

  if (reduced || src === null || appearanceOwnsWallpaper) {
    // 省流量/关壁纸/降级动效/**本地壁纸在播**：不渲染 <video> 元素本身（连解码器都不占）；
    // .ambient-video 的 ::after 兜一层雾底，页面仍然完整。
    return <div className='ambient-video' aria-hidden='true' />;
  }

  return (
    <div ref={hostRef} className={`ambient-video${failed ? ' is-dead' : ''}`} aria-hidden='true'>
      <video
        muted
        loop
        playsInline
        preload='none'
        tabIndex={-1}
        disablePictureInPicture
        disableRemotePlayback
        onError={() => setFailed(true)}
      >
        <source src={src} type='video/mp4' />
      </video>
    </div>
  );
}

/** 洗色压暗 + 漂移釉瑚光斑（颜色全走 token）。
 *
 * 光斑个数由配置决定（`aurora.count`）：apply.ts 把同一个数写成 `--au-count`，
 * 但**节点数不是 CSS 能表达的**（apply.ts 自注同此），真正的消费者是这里。
 * ponytail: 只有三套落点配方（`.aurora-blob-a/b/c` 各自的位置与周期在 index.css），
 * 所以有效个数封顶 3：count 4–6 与 3 同观感。要真加落点得在 index.css 补配方
 * （那是独占写面），不是在这里复制节点。 */
const BLOB_LAYOUTS = ['aurora-blob-a', 'aurora-blob-b', 'aurora-blob-c'] as const;

export function AmbientGlow() {
  const { effective } = useAppearance();
  const count = Math.min(BLOB_LAYOUTS.length, Math.max(1, Math.round(effective.aurora.count)));
  return (
    <div className='ambient-glow' aria-hidden='true'>
      {BLOB_LAYOUTS.slice(0, count).map((layout) => (
        <span key={layout} className={`aurora-blob ${layout}`} />
      ))}
    </div>
  );
}

/** WinUI 云母颗粒：极淡的 SVG 噪点，固定铺满，`pointer-events: none`。 */
export function AmbientGrain() {
  return <div className='ambient-grain' aria-hidden='true' />;
}

/** 一次性挂齐三层的门面组件（AppShell 只认这一个）。 */
export function AmbientBackdrop() {
  return (
    <>
      <AmbientVideo />
      <AmbientGlow />
      <AmbientGrain />
    </>
  );
}
