// 卡片模板编辑器的**纯逻辑面**（UI3 需求 10 后半）：
//   ① 模板列表 —— 从 visual catalog 的 `platforms` × 卡片能力 ID 拼出「模板」候选；
//   ② 受控样式 —— 颜色/字号档/字重/间距/圆角**只许从登记值域里选**，不许自由输入 hex；
//   ③ 预览沙箱属性 —— 给 `iframe sandbox` 用，铁律是不许 `allow-same-origin`。
//
// 零 React 依赖，`node --test` 直接加载。组件只负责画。
import type { VisualCatalog, VisualDocument, VisualTheme } from './visual-editor';

/** 后端 catalog 的 `style.colors` 是**登记色名**（token 名），不是 hex；这里做展示名。 */
export const STYLE_LABELS = {
  size: '字号档',
  weight: '字重',
  color: '配色',
  spacing: '间距档',
} as const;

export interface TemplateCandidate {
  /** 作用域四轴（`card` 为空 = 平台默认模板）。 */
  platform: string;
  card: string;
  /** 界面上显示的名字（真实取值，不编）。 */
  label: string;
  /** 是否全局面（platform = '*'）。 */
  global: boolean;
}

/**
 * 从 catalog 拼模板候选：每个平台 × 每个能出卡的卡片能力 ID。
 *
 * 🔴 为什么「模板」不是从后端拉一个 `templates[]` 数组：后端 `visual_layouts.py` 的目录
 *    只有 `platforms` / `kinds` / `style` / `fragments` 这些**登记面**，没有「模板清单」
 *    这个概念——布局本来就是按 `(platform, instance, group, card)` 四轴取回退链的。
 *    所以这里的「模板列表」= 平台 × 卡片 ID 的组合，点一条就把作用域填好，再走既有的
 *    `read` 拿那一层实际生效的布局。**不造第二份模板真相**。
 */
export function templateCandidates(catalog: VisualCatalog | null, cardIds: readonly string[]): TemplateCandidate[] {
  if (!catalog) return [];
  const platforms = catalog.platforms?.length ? catalog.platforms : [catalog.global_platform ?? '*'];
  const cards = cardIds.length ? cardIds : [''];
  const out: TemplateCandidate[] = [];
  for (const platform of platforms) {
    for (const card of cards) {
      out.push({
        platform,
        card,
        global: platform === '*' || platform === (catalog.global_platform ?? '*'),
        label: `${platform === '*' ? '全局面' : platform}${card ? ` · ${card}` : ' · 平台默认模板'}`,
      });
    }
  }
  return out;
}

/** 默认的卡片能力 ID 清单（生产 producer；与 visual-editor 页面注释一致）。 */
export const DEFAULT_CARD_IDS = ['bot.weather', 'bot.market', 'bot.fx'] as const;

/** 受控样式键的两档：布局内样式（VisualDocument.style）与全局 token（VisualTheme）。 */
export type LayoutStyleKey = 'size' | 'spacing' | 'weight' | 'color';

/** 一个下拉该有哪些选项（全部来自后端登记值域；空数组 ⇒ 该轴没有可选项，UI 要禁用）。 */
export function styleChoices(catalog: VisualCatalog | null, key: LayoutStyleKey): Array<string | number> {
  if (!catalog) return [];
  switch (key) {
    case 'size':
      return catalog.style.sizes;
    case 'weight':
      return catalog.style.weights;
    case 'color':
      return catalog.style.colors;
    case 'spacing':
      return catalog.style.spacing;
    default:
      return [];
  }
}

/** 全局视觉 token 的可选值（圆角 / 字体栈；主色是受控输入框，见下）。 */
export function themeChoices(catalog: VisualCatalog | null): { shellRadius: number[]; fontFamily: string[] } {
  return {
    shellRadius: catalog?.theme_choices?.shell_radius ?? [],
    fontFamily: catalog?.theme_choices?.font_family ?? [],
  };
}

/**
 * 主色的**受控输入**校验：只收 `#RRGGBB`（后端 `theme_choices` 也只登记这一种形态）。
 * 返回规范化后的值或 null（null = 非法，界面要就地提示，不许悄悄提交）。
 */
export function normalizeThemeColor(raw: string): string | null {
  const text = String(raw ?? '').trim();
  if (!text) return null;
  return /^#[0-9a-fA-F]{6}$/.test(text) ? text.toUpperCase() : null;
}

/**
 * 预览 iframe 的 sandbox 属性。**铁律：不含 `allow-same-origin`。**
 *
 * 为什么：预览 HTML 来自生产渲染函数（后端只回显自己渲染的结果，不回显用户 HTML），
 * 但它是**不可信内容面**——一旦加上 `allow-same-origin`，iframe 里的脚本就能拿到本页
 * 的 localStorage（那里有 Bearer token 的会话态）并同源发请求。只给 `allow-scripts`
 * 让卡片里的脚本能跑（图表动画等），但拿不到任何父页面能力。
 */
export const PREVIEW_SANDBOX = 'allow-scripts';

/** 校验 sandbox 串没被改成危险形态（测试锁）。 */
export function isSafeSandbox(sandbox: string): boolean {
  return !sandbox.split(/\s+/).includes('allow-same-origin') && !sandbox.split(/\s+/).includes('allow-top-navigation');
}

/**
 * 预览空态说明：没有 API token 时 `/visual/preview` 会 503，这里给出**可执行**的下一步，
 * 而不是一句「加载失败」。
 */
export function previewUnavailableHint(status: number | null): string {
  if (status === 503) return '控制面未配置访问令牌：请先在右上角「设置」里填入令牌，预览需要调用后端渲染函数。';
  if (status === 403) return '当前身份没有预览权限（渲染函数只对管理员开放）。';
  if (status === 401) return '令牌已失效：请重新在「设置」里填入。';
  return '预览暂不可用；布局编辑与保存不受影响。';
}

/** 布局 → 一句话摘要（模板列表右侧的副标题用；不造字段）。 */
export function describeLayout(spec: VisualDocument | null): string {
  if (!spec) return '该作用域尚无布局（会继承上一层或走默认模板）';
  const elements = spec.elements.length;
  return `${spec.layout} 布局 · ${elements} 个元素${spec.title ? ` · 标题「${spec.title}」` : ''}`;
}

/** 全局视觉覆盖 → 一句话摘要。 */
export function describeTheme(overrides: VisualTheme | undefined): string {
  if (!overrides) return '未覆盖（沿用值册默认）';
  const parts: string[] = [];
  if (overrides.brand_accent) parts.push(`主色 ${overrides.brand_accent}`);
  if (overrides.shell_radius !== undefined) parts.push(`圆角 ${overrides.shell_radius}px`);
  if (overrides.font_family) parts.push(`字体 ${overrides.font_family}`);
  return parts.length ? parts.join(' · ') : '未覆盖（沿用值册默认）';
}
