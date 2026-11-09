// 自动降级（UI3 追加二「性能联动」）：三路探测 → 一份「收窄后的生效配置」+ 人话提示条。
//
// 为什么是**派生**而不是改写存储：用户永远能看到自己保存的原始值，降级只是渲染态。
// 用户点「恢复默认强度」= `overridden=true` 存进 localStorage（连同探测指纹），
// 指纹变了才会重新征求——机器升级了不该把用户永久判成低配。
//
// 三路判据（用户裁定 + 服务器 2C2T/2G/20GB 月流量的硬约束）：
//   saveData          省流模式 → 壁纸只许 shader/none、光斑降到 1、关动效
//   窄屏 <768         手机 backdrop-filter 很贵 → 玻璃模糊 ≤12、光斑 ≤2、3D 降档
//   低核 ≤4 或内存≤4G 弱机 → 同窄屏，并关图表描边动画

import type { AppearanceConfig } from './types.ts';

/** 当前环境的硬件/网络特征（浏览器给多少就是多少；缺省一律当作「不降级」）。 */
export interface EnvironmentProbe {
  saveData: boolean;
  width: number;
  /** `navigator.hardwareConcurrency`；0 = 不可知。 */
  cores: number;
  /** `navigator.deviceMemory`（GB）；0 = 不可知。 */
  memoryGb: number;
  /** `matchMedia('(pointer: coarse)')`，触屏。 */
  coarsePointer: boolean;
}

export type DegradeReason = 'saveData' | 'narrow' | 'lowPower';

/** 降级结果：生效配置 + 触发了哪几条 + 给提示条用的中文说明。 */
export interface DegradedAppearance {
  config: AppearanceConfig;
  reasons: DegradeReason[];
  notes: string[];
}

export const DEGRADE_NOTE: Record<DegradeReason, string> = {
  saveData: '省流模式：壁纸只用程序化生成、光斑减到 1 个、动效已关',
  narrow: '窄屏设备：玻璃模糊与光斑个数已压低，3D 降为中低档',
  lowPower: '低配设备：额外关闭图表描边动画，避免掉帧',
};

/** 从 window 探测；非浏览器环境返回全零（不降级）。 */
export function probeEnvironment(): EnvironmentProbe {
  if (typeof window === 'undefined') {
    return { saveData: false, width: 0, cores: 0, memoryGb: 0, coarsePointer: false };
  }
  const conn = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  const dev = navigator as Navigator & { deviceMemory?: number };
  return {
    saveData: Boolean(conn?.saveData),
    width: window.innerWidth,
    cores: navigator.hardwareConcurrency || 0,
    memoryGb: typeof dev.deviceMemory === 'number' ? dev.deviceMemory : 0,
    coarsePointer: window.matchMedia?.('(pointer: coarse)')?.matches ?? false,
  };
}

/** 纯函数：探针 → 是否降级、降哪些。可单测（不碰浏览器）。 */
export function degradeReasons(probe: EnvironmentProbe): DegradeReason[] {
  const reasons: DegradeReason[] = [];
  if (probe.saveData) reasons.push('saveData');
  if (probe.width > 0 && probe.width < 768) reasons.push('narrow');
  if ((probe.cores > 0 && probe.cores <= 4) || (probe.memoryGb > 0 && probe.memoryGb <= 4)) {
    reasons.push('lowPower');
  }
  return reasons;
}

/** 探针指纹：用户覆盖只对「同一台机器 + 同一网络档」有效。 */
export function probeSignature(probe: EnvironmentProbe): string {
  return [probe.saveData ? 1 : 0, probe.width < 768 ? 1 : 0, probe.cores, probe.memoryGb].join('|');
}

/**
 * 应用降级：不修改入参（返回新对象），保证「用户保存的原始值」与「当前渲染值」两不相干。
 * `overridden` 为真时原样返回（用户已声明要满血）。
 */
export function applyDegrade(
  cfg: AppearanceConfig,
  probe: EnvironmentProbe,
  overridden: boolean
): DegradedAppearance {
  const reasons = degradeReasons(probe);
  if (overridden || reasons.length === 0) {
    return { config: cfg, reasons, notes: [] };
  }
  const next = structuredClone(cfg);
  if (reasons.includes('saveData')) {
    // 渲染侧：不加载本地图片/视频，光斑留一团，动效与虹彩全停。
    if (next.wallpaper.mode === 'video' || next.wallpaper.mode === 'image') next.wallpaper.mode = 'shader';
    next.aurora.count = 1;
    next.motion.enabled = false;
    next.motion.chartPath = false;
    next.iridescence.enabled = false;
    // 流量侧（第 17 组）：省流时把「会往服务器要字节」的开关全关掉。
    next.performance.prefetch = false;
    next.performance.imageQuality = 'off';
    next.charts.refresh = 'off';
    next.interaction.polling = false;
  }
  if (reasons.includes('narrow') || reasons.includes('lowPower')) {
    next.glass.blur = Math.min(next.glass.blur, 12);
    next.aurora.count = Math.min(next.aurora.count, 2);
    if (next.scene3d.quality === 'high') next.scene3d.quality = 'medium';
    // 3D 页回退的质量档也一并压住（第 10 组的 quality 是真 3D 的像素比/粒子数口径）。
    if (next.charts.quality === 'high') next.charts.quality = 'medium';
    // 窄屏没地方放两栏：布局列数收到 1，卡片最小宽度放宽让内容不挤。
    next.layout.gridColumns = Math.min(next.layout.gridColumns, 1);
  }
  if (reasons.includes('lowPower')) {
    next.motion.chartPath = false;
    next.glass.grain = false;
    if (next.scene3d.quality !== 'low') next.scene3d.quality = 'low';
    next.charts.quality = 'low';
    next.performance.prefetch = false;
  }
  return { config: next, reasons, notes: reasons.map((reason) => DEGRADE_NOTE[reason]) };
}
