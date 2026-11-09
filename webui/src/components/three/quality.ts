// 3D 质量档（用户简报 C 席硬要求 8）：低/中/高，影响像素比、连线数上限、粒子数与后期。
// 默认按设备能力自动选：这里只放纯函数，不碰 DOM/WebGL——便于单测，也让页面在加载
// three 之前就能决定档位（首屏隔离靠这条：判定不需要 three）。

export type Quality = 'low' | 'medium' | 'high';

export interface QualityProfile {
  /** 渲染器像素比上限（永远与 devicePixelRatio 取 min，硬要求 5）。 */
  maxPixelRatio: number;
  /** 连线最多画多少条（按权重降序取前 N；超出的不画，不是丢弃数据）。 */
  maxEdges: number;
  /** 球面环境光点数量（纯装饰粒子）。 */
  particles: number;
  /** 是否开后期：halo 光晕精灵 + 节点辉光叠层。 */
  postFx: boolean;
  /** 力导向降温后是否继续跑 RAF 自转（reduced-motion 时全局关闭）。 */
  spin: boolean;
}

export const PROFILES: Record<Quality, QualityProfile> = {
  low: { maxPixelRatio: 1, maxEdges: 400, particles: 0, postFx: false, spin: true },
  medium: { maxPixelRatio: 1.5, maxEdges: 1200, particles: 600, postFx: true, spin: true },
  high: { maxPixelRatio: 2, maxEdges: 2500, particles: 1600, postFx: true, spin: true },
};

export interface DeviceFacts {
  width: number;
  hardwareConcurrency: number;
  devicePixelRatio: number;
  reducedMotion: boolean;
}

/** 设备能力 → 自动档。窄屏/低核根本进不到 3D（页面先回退 2D），这里是「够格进 3D」之后的定档。 */
export function autoQuality(facts: DeviceFacts): Quality {
  if (facts.reducedMotion) return 'low';
  if (facts.hardwareConcurrency >= 8 && facts.width >= 1280 && facts.devicePixelRatio >= 1) return 'high';
  return 'medium';
}

/** 硬要求 3：窗口 < 768 或核数 ≤ 4 不用 WebGL。 */
export function shouldUse3D(facts: Pick<DeviceFacts, 'width' | 'hardwareConcurrency'>): boolean {
  return facts.width >= 768 && facts.hardwareConcurrency > 4;
}
