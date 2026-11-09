// 本地壁纸渲染（UI3 追加一/二 → W12 A2 修复）。
//
// 用户原话：「现在无法导入使用动态壁纸，修复，直接选择 mp4 文件导入，再调整参数，而不是给地址」。
//
// 真因（代码级，不是猜）：
//   ① 主图层组件从未被挂载 —— AppShell 只挂 `AmbientBackdrop`（内置 bg-720p/1080p 或地址），
//      所以外观页写进 IndexedDB 的文件**没有任何消费者**：文件确实存进去了，画面上什么都不发生。
//   ② `.wp-layer` / `.wp-media` / `.wp-scrim` 在 index.css 里**从来没有规则**（合并期漏搬），
//      就算挂上去，img/video 也会以文档流尺寸铺在页面顶部、把 UI 整个盖住。
//   ③ `<video>` 缺显式 muted/autoPlay，刷新后靠 `video.play()` 兜——Chrome 的自动播放策略
//      会把非静音播放拦下，于是「刷新后黑屏」。
//   ④ 失败完全没有提示：解码失败/浏览器不支持时用户只看到黑底。
// 现在：图层有样式（fixed + 负 z + cover）、blob URL 每次挂载都从 IndexedDB 重建、
// video 显式 muted+playsInline+loop+autoPlay、失败有**看得见的一行中文**。
//
// 本地文件走 IndexedDB + `URL.createObjectURL`：零网络、永不上传。
// 卸载/换文件时 revoke，否则几十 MB 的视频会被页面一直攥着。
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useAppearance } from '@/lib/appearance/context';
import { getWallpaperBlob } from '@/lib/appearance/store';

/**
 * 壁纸层的状态提示（解码失败 / 文件丢失）。
 *
 * 🔴 必须 `createPortal` 到 `body`，**不能**留在图层树里：这两个提示由 `BackgroundStage`
 * 渲染，而它现在被包在 `.bg-stage`（`z-index:-1`）里——容器内任何元素都逃不出这一组
 * 的负 z 步，`z-10` 也一样被压在所有面板之下，用户永远看不见。
 * 挂到 `body` 后它落在根层叠上下文，`z-10` > `#root` 的 `z-1`，才真正浮在 UI 之上。
 * 契约见 `components/appearance/layering.test.ts`（提示类节点不许出现在背景图层组里）。
 */
function BackdropNotice({ children }: { children: ReactNode }) {
  return createPortal(
    <p
      role='status'
      className='glass-panel fixed bottom-4 left-4 right-4 z-10 rounded-lg border px-4 py-3 fs-caption text-tone-warn sm:right-auto sm:max-w-96'
    >
      {children}
    </p>,
    document.body
  );
}

/** 读 IndexedDB 里的 Blob → objectURL；`enabled` 为假时不碰库。 */
export function useWallpaperObjectUrl(enabled: boolean, blobId: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || !blobId) {
      setUrl(null);
      return;
    }
    let alive = true;
    let created: string | null = null;
    void getWallpaperBlob(blobId).then((blob) => {
      if (!alive || !blob) return;
      // 每次挂载都重建：blob URL 只活在这个页面进程里，刷新后必须重新 create。
      created = URL.createObjectURL(blob);
      setUrl(created);
    });
    return () => {
      alive = false;
      if (created) URL.revokeObjectURL(created);
      setUrl(null);
    };
  }, [enabled, blobId]);
  return url;
}

/**
 * 全站本地壁纸层：只在「图片/视频 + 已选文件」时渲染，其余情况返回 null
 * （纯色/场景着色仍由 AmbientBackdrop 那套内置背景负责，两者不叠）。
 *
 * 挂在 AppShell 根部、与 `<main>` 平级：fixed 层不进滚动容器（进去会每帧重绘整条滚动带）。
 */
export function BackgroundStage() {
  const { effective } = useAppearance();
  const { wallpaper } = effective;
  const videoRef = useRef<HTMLVideoElement>(null);
  const needsLocal = wallpaper.mode === 'image' || wallpaper.mode === 'video';
  const localUrl = useWallpaperObjectUrl(needsLocal, wallpaper.blobId);
  const [failed, setFailed] = useState<string | null>(null);

  // 播放参数不走 CSS：改一次就生效，不需要重建 <video>。
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = wallpaper.playbackRate;
    video.muted = wallpaper.muted;
    video.loop = wallpaper.loop;
    // 静音 + playsInline 是 Chrome 允许无交互自动播的两个前提；任一不满足就停在首帧，
    // 这里把失败原因说出来，而不是让用户对着一块黑屏猜。
    void video.play().catch(() => {
      setFailed('浏览器拦下了自动播放：把「视频静音」打开，或点一下页面任意处。');
    });
  }, [localUrl, wallpaper.playbackRate, wallpaper.muted, wallpaper.loop]);

  if (!needsLocal) return null;

  // 选了「本地图片/视频」但库里没有文件：这是最常见的「看起来没反应」，明确说一句。
  // ⚠️ 这条提示过去渲染在 `.wp-layer` 里（fixed + z-index:-40 + pointer-events:none）——
  // 文字会随整套背景沉到所有面板之下，**永远看不见**。改成与解码失败同一形制的气泡。
  if (!localUrl) {
    return (
      <BackdropNotice>
        这个壁纸文件在本机库里找不到了（可能被浏览器清理过）。回到外观页重新选一次文件。
      </BackdropNotice>
    );
  }

  return (
    <>
      <div className='wp-layer' aria-hidden>
        {wallpaper.mode === 'video' ? (
          <video
            ref={videoRef}
            className='wp-media'
            src={localUrl}
            muted
            loop
            autoPlay
            playsInline
            preload='auto'
            tabIndex={-1}
            disablePictureInPicture
            disableRemotePlayback
            onError={(e) => {
              const code = (e.currentTarget as HTMLVideoElement).error?.code;
              // code 4（SRC_NOT_SUPPORTED）在本部署里最常见的原因是**服务端 CSP 不含
              // media-src blob:**（见 A2 报告），不是编码问题——别再只怪格式，那样用户会
              // 一遍遍换文件却永远放不出来。
              setFailed(
                code === 4
                  ? '这段视频没能加载：浏览器的安全策略拒绝了这个地址，或容器/编码不被支持。换一个 H.264 的 mp4 试试；若换文件仍不行，是服务端 CSP 缺 media-src blob:，需要后端放行。'
                  : '这段视频没能播放，换一个 H.264/VP9 的 mp4 或 webm 试试。'
              );
            }}
          />
        ) : (
          <img
            className='wp-media'
            src={localUrl}
            alt=''
            onError={() => setFailed('这张图片解不开，换一张常见格式（jpg/png/webp）试试。')}
          />
        )}
      </div>
      <div className='wp-scrim' aria-hidden />
      {failed && <BackdropNotice>{failed}</BackdropNotice>}
    </>
  );
}

/** 外观页里的缩略预览：同一个 objectURL，不重复读库。 */
export function WallpaperThumb() {
  const { effective } = useAppearance();
  const { wallpaper } = effective;
  const needsLocal = wallpaper.mode === 'image' || wallpaper.mode === 'video';
  const localUrl = useWallpaperObjectUrl(needsLocal, wallpaper.blobId);
  if (!needsLocal || !localUrl) return null;
  return (
    <span className='relative block h-16 w-28 shrink-0 overflow-hidden rounded-md border bg-card'>
      {wallpaper.mode === 'video' ? (
        <video className='h-full w-full object-cover' src={localUrl} muted loop autoPlay playsInline tabIndex={-1} />
      ) : (
        <img className='h-full w-full object-cover' src={localUrl} alt='当前壁纸预览' />
      )}
    </span>
  );
}
