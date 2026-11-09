// 外观配置的 React 侧总线（UI3 追加二）：读 IndexedDB → 降级 → 写 CSS 变量 → 广播。
//
// 三件在这里一次办成，别处不再重复：
//   ① **首帧前**就把存储里的配置应用到 `<html>`（`index.css` 里有同名的默认值兜底，
//      所以「还没读完」= 呈现默认皮肤，不闪白）；
//   ② 任何改配置的入口（外观页、导入、预设、提示条）都走这里的 `setField` / `replace`，
//      改完立刻 `applyAppearance` —— 拖滑块即时生效，不需要保存/刷新；
//   ③ 持久化 fire-and-forget（写失败只影响刷新后是否保留，不阻断实时预览）。
//
// 写入按**路径**（`glass.blur` / `iridescence.targets.nav`），不再逐个分组手写合并：
// 17 个分组 × 每个字段各写一遍合并代码，漏一组就是「这一组调了没反应」，而路径写法
// 与 `schema-fields.ts` 的字段表、`presets.ts` 的校验共用同一套 get/set。
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { setDefaultNumberFormat } from '../format.ts';
import { applyAppearance } from './apply';
import { DEFAULT_APPEARANCE } from './defaults';
import {
  applyDegrade,
  probeEnvironment,
  probeSignature,
  type DegradedAppearance,
  type EnvironmentProbe,
} from './degrade';
import { setPath } from './path.ts';
import { readOverride, saveAppearance, writeOverride, loadAppearance } from './store';
import type { AppearanceConfig } from './types';

export interface AppearanceContextValue {
  /** 用户保存的原始配置（未经降级）。 */
  config: AppearanceConfig;
  /** 真正在渲染的配置（降级后）；拖滑块时两者通常相同。 */
  effective: AppearanceConfig;
  probe: EnvironmentProbe;
  degraded: DegradedAppearance;
  /** 用户已点「恢复默认强度」。 */
  overridden: boolean;
  /** 配置还在从 IndexedDB 读取。 */
  loading: boolean;
  /** 按路径写一个字段（`glass.blur`、`iridescence.targets.nav`）；立即生效并自动落盘。 */
  setField: (path: string, value: unknown) => void;
  /** 整份替换（预设 / 导入 / 重置）。 */
  replace: (next: AppearanceConfig) => void;
  /** 用户声明要满血（或撤销该声明）。 */
  setOverridden: (value: boolean) => void;
  /** 导入结果提示（页面读它显示一行「已自动修正」）。 */
  lastNotice: string | null;
  setLastNotice: (value: string | null) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | undefined>(undefined);

/** 应用配置到根元素（唯一出口；组件不许自己 setProperty）。 */
function paint(config: AppearanceConfig): void {
  // 数字/日期的展示口径也在这里注入——「全站只有一处默认档」的代价是必须有一个
  // 唯一的写入口，paint 就是它（首帧前跑一次、每次改配置再跑一次）。放在 document
  // 判空之前：格式化与 DOM 无关，SSR/测试环境同样要拿到正确口径。
  setDefaultNumberFormat({
    unitSystem: config.locale.unitSystem,
    decimals: config.charts.decimals,
    thousands: config.charts.thousands,
  });
  if (typeof document === 'undefined') return;
  applyAppearance(config, document.documentElement);
}

/** 首帧前用默认值铺一遍，避免「刚刷新时一片无色」。 */
paint(DEFAULT_APPEARANCE);

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppearanceConfig>(() => structuredClone(DEFAULT_APPEARANCE));
  const [loading, setLoading] = useState(true);
  const [probe, setProbe] = useState<EnvironmentProbe>(() => probeEnvironment());
  const [overridden, setOverriddenState] = useState(() => readOverride(probeSignature(probeEnvironment())));
  const [lastNotice, setLastNotice] = useState<string | null>(null);
  // 写盘去抖：拖滑块时每帧一次 put 会打爆 IndexedDB，250 ms 静默后落一次。
  const timer = useRef<number | null>(null);

  // 首次装载：读 IndexedDB，读到的立刻上屏。
  useEffect(() => {
    let alive = true;
    void loadAppearance().then(({ config: stored, repaired }) => {
      if (!alive) return;
      setConfig(stored);
      paint(stored);
      setLoading(false);
      if (repaired) setLastNotice('存储里的外观配置有损坏字段，已按默认值修正。');
    });
    return () => {
      alive = false;
    };
  }, []);

  // 窗口尺寸/省流档变化 → 重新探测（旋转手机、开省流都会走到这里）。
  useEffect(() => {
    const resync = () => setProbe(probeEnvironment());
    window.addEventListener('resize', resync);
    const conn = (navigator as Navigator & { connection?: EventTarget }).connection;
    conn?.addEventListener?.('change', resync);
    return () => {
      window.removeEventListener('resize', resync);
      conn?.removeEventListener?.('change', resync);
    };
  }, []);

  const degraded = useMemo(() => applyDegrade(config, probe, overridden), [config, probe, overridden]);

  // 生效配置变了就重写变量（拖动滑块 → 这里 → CSS 立刻变）。
  useEffect(() => {
    paint(degraded.config);
  }, [degraded.config]);

  const persist = useCallback((next: AppearanceConfig) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void saveAppearance(next);
    }, 250);
  }, []);

  const replace = useCallback(
    (next: AppearanceConfig) => {
      setConfig(next);
      paint(next);
      persist(next);
    },
    [persist]
  );

  const setField = useCallback(
    (path: string, value: unknown) => {
      setConfig((current) => {
        // 数组字段（如高亮规则、快捷键、自定义光斑色）整份替换语义：调用方给新数组。
        const next = setPath(current as unknown as Record<string, unknown>, path, value) as unknown as AppearanceConfig;
        persist(next);
        return next;
      });
    },
    [persist]
  );

  const setOverridden = useCallback(
    (value: boolean) => {
      const signature = probeSignature(probe);
      writeOverride(value ? signature : null);
      setOverriddenState(value);
    },
    [probe]
  );

  const value = useMemo<AppearanceContextValue>(
    () => ({
      config,
      effective: degraded.config,
      probe,
      degraded,
      overridden,
      loading,
      setField,
      replace,
      setOverridden,
      lastNotice,
      setLastNotice,
    }),
    [config, degraded, probe, overridden, loading, setField, replace, setOverridden, lastNotice]
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance(): AppearanceContextValue {
  const ctx = useContext(AppearanceContext);
  if (!ctx) throw new Error('useAppearance must be used within AppearanceProvider');
  return ctx;
}
