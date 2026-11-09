// 展示格式化公共层（纯函数，无副作用）——**全站唯一**的数字/时间/日期口径。
//
// 为什么所有口径必须挤在这一个文件里：同一个 1234567 在收口前会写成 1,234,567 /
// 1234567 / 1.2M / 123.5万 四种，用户看到的是「同一个指标四个值」。口径分散时
// 改一处漏十处，且没有任何机器证据能说清「现在全站到底是几位分隔」。
//
// 四条已裁定口径（改它们＝改用户可见契约，须先改本注释与 format-display.test.ts）：
//   ① 数字三档单位：compact(1.2K/1.2M) · chinese(1.2万/1.2亿) · plain(完整数字)。
//      默认档由外观「语言与格式 → 数字单位」(`AppearanceConfig.locale.unitSystem`)
//      经 `setDefaultNumberFormat` 注入；`charts.unitSystem` 是历史遗留键，从未被
//      渲染层消费，不作为真身。
//   ② **3 位分隔**（千分位 1,234,567）。全站唯一口径，`formatCount` 恒 3 位；
//      `千分位分隔` 开关只作用于「完整数字」档的概览大数。
//   ③ 时间单位：时长一律把天/小时/分/秒写到秒；速率必须带「次/单位」；
//      **延迟恒为 ms 口径**（满 1 秒折成「秒」，绝不写成「每秒」）。
//   ④ 日期：年月日 + 时分秒。两条时区口径各自钉死——
//      `formatDateTime` 走 Date → 本地时区（沿用既有语义，构造期绑定，见 format.test.ts）；
//      `formatIsoDateTime` 直接切 ISO 字面量（后端 bucket_start 已带业务时区偏移，
//      再转一次本地时区会整体漂移，出现「14 点的调用画在 06 点」）。
import type { UnitSystem } from './appearance/types';
import type { BucketCode } from '@/lib/labels';

/**
 * 未知值符号（全库唯一真值，一枚 U+2014 长横）。
 *
 * 语义：**这个值不可知**（后端没上报、字段缺省、时间为 null）——与「查过了、结果为空」
 * （`state.noData`「暂无数据」）是两件事，绝互相顶替（F23 §一.3 事故原型：calls 页把空
 * 列表渲染成本符号）。下方各 format* 在值缺失时一律返回它，页面**不得再写字面量**——
 * 收口前同一个符号在 11 处各写各的，改一处漏十处。
 */
export const UNKNOWN_VALUE = '—';

/** 全站分组位数：3（千分位）。M2 裁定，唯一口径；不许出现 4 位分组。 */
export const GROUP_SIZE = 3;

// ============================================================================
// 数字：三档单位（M1）
// ============================================================================

/** 供调用方覆盖缺省档；缺省字段留空即跟随外观设置。 */
export interface NumberFormatOptions {
  /** 'compact' | 'chinese' | 'plain'；缺省=外观「语言与格式」的值。 */
  unitSystem?: UnitSystem;
  /** 缩写档小数位（0–3，缺省 1）。plain 档不吃这个参数（不丢精度）。 */
  decimals?: number;
  /** plain 档是否加 3 位分隔（缺省 true）。 */
  thousands?: boolean;
}

type ResolvedNumberFormat = Required<NumberFormatOptions>;

/** 缺省：与 `appearance/defaults.ts` 的 locale.unitSystem / charts.thousands 对齐。 */
const DEFAULTS: ResolvedNumberFormat = { unitSystem: 'compact', decimals: 1, thousands: true };

// 外观总线的注入点。`activeDefault` 是「当前外观设置」，不是缓存：外观页一改，
// context.tsx 立刻 setDefaultNumberFormat，下一次渲染取到的就是新档。
// 纯函数纪律不变——每个 format* 的产物只由 (value, options) 决定，options 缺省时
// 取 `activeDefault` 的快照。
let activeDefault: ResolvedNumberFormat = { ...DEFAULTS };

/** 外观总线调用（唯一调用方：`lib/appearance/context.tsx` 的 paint）。 */
export function setDefaultNumberFormat(patch: NumberFormatOptions): void {
  const next: ResolvedNumberFormat = { ...activeDefault };
  if (patch.unitSystem !== undefined) next.unitSystem = patch.unitSystem;
  if (patch.decimals !== undefined) next.decimals = patch.decimals;
  if (patch.thousands !== undefined) next.thousands = patch.thousands;
  activeDefault = next;
}

/** 只读快照（测试与调试用；调用方改不动内部状态）。 */
export function getDefaultNumberFormat(): ResolvedNumberFormat {
  return { ...activeDefault };
}

function resolve(options?: NumberFormatOptions): ResolvedNumberFormat {
  if (!options) return activeDefault;
  return {
    unitSystem: options.unitSystem ?? activeDefault.unitSystem,
    decimals: options.decimals ?? activeDefault.decimals,
    thousands: options.thousands ?? activeDefault.thousands,
  };
}

const clampDecimals = (digits: number | undefined, fallback: number): number => {
  const n = Number.isFinite(digits as number) ? Math.trunc(digits as number) : fallback;
  return Math.min(Math.max(n, 0), 3);
};

/** 去掉缩写小数尾的零：1.0K → 1K、12.30K → 12.3K。 */
function trimZeros(text: string): string {
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
}

/** 整数部分按 GROUP_SIZE 分组：1234567 → 1,234,567。 */
function groupDigits(digits: string): string {
  let out = '';
  for (let i = 0; i < digits.length; i += 1) {
    if (i > 0 && (digits.length - i) % GROUP_SIZE === 0) out += ',';
    out += digits[i];
  }
  return out;
}

/** 完整数字（不缩写）：整段保留，小数不丢。 */
function formatPlain(value: number, thousands: boolean): string {
  const abs = Math.abs(value);
  const raw = String(abs);
  // 1e21 起 String() 走指数形；这种量级只可能来自病态输入，交给 Intl 保底。
  const text = raw.includes('e') || raw.includes('E')
    ? new Intl.NumberFormat('en-US', { useGrouping: thousands, maximumFractionDigits: 20 }).format(abs)
    : (() => {
        const [int, frac] = raw.split('.');
        const body = thousands ? groupDigits(int) : int;
        return frac ? `${body}.${frac}` : body;
      })();
  return value < 0 ? `-${text}` : text;
}

interface Tier {
  divisor: number;
  suffix: string;
}

/** compact 档位（降序；find 取第一个够得着的）。 */
const COMPACT_TIERS: readonly Tier[] = [
  { divisor: 1e9, suffix: 'B' },
  { divisor: 1e6, suffix: 'M' },
  { divisor: 1e3, suffix: 'K' },
];
/** chinese 档位（万/亿；「兆」不在用户口径内，亿以上继续用亿计）。 */
const CHINESE_TIERS: readonly Tier[] = [
  { divisor: 1e8, suffix: '亿' },
  { divisor: 1e4, suffix: '万' },
];

/**
 * 缩写一档。返回 null = 没够到最低档位（调用方补完整数字）。
 *
 * 进位是必须的：999999/1000=999.999 四舍五入成 1000.0 → 裁零成「1000」，
 * 若直接拼后缀就写出「1000K」——用户看到的是一个不存在的档位。故检出 ≥1000
 * 后升一档重算（1000K→1M、10000万→1亿）。
 */
function abbreviate(value: number, tiers: readonly Tier[], decimals: number): string | null {
  const abs = Math.abs(value);
  const index = tiers.findIndex((tier) => abs >= tier.divisor);
  if (index < 0) return null;
  const sign = value < 0 ? '-' : '';
  const text = trimZeros((abs / tiers[index].divisor).toFixed(decimals));
  // 进位阈值＝「下一档要多少本档」：K→M 是 1000，万→亿是 10000。
  // 用固定 1000 判万→亿会把 2500万 写成 0.3亿（量级没越界却降了精度）。
  if (index > 0) {
    const next = tiers[index - 1];
    const promoteAt = next.divisor / tiers[index].divisor;
    if (Number(text) >= promoteAt) {
      return `${sign}${trimZeros((abs / next.divisor).toFixed(decimals))}${next.suffix}`;
    }
  }
  return `${sign}${text}${tiers[index].suffix}`;
}

/**
 * 数字三档单位（M1）。非有限值/缺值 → UNKNOWN_VALUE（绝不渲染 NaN 或 0）。
 *
 * 未够到缩写档位时退回完整数字 + 3 位分隔（M2），所以 `formatNumber(999)` 恒为
 * 「999」、`formatNumber(9999, {unitSystem:'chinese'})` 为「9,999」。
 */
export function formatNumber(value: number | null | undefined, options?: NumberFormatOptions): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_VALUE;
  const cfg = resolve(options);
  if (cfg.unitSystem === 'plain') return formatPlain(value, cfg.thousands);
  const tiers = cfg.unitSystem === 'chinese' ? CHINESE_TIERS : COMPACT_TIERS;
  const short = abbreviate(value, tiers, clampDecimals(cfg.decimals, 1));
  return short ?? formatPlain(value, cfg.thousands);
}

/**
 * 明细计数（token 数、样本数、行数…）：**永远完整数字 + 3 位分隔**，不缩档。
 *
 * 与 `formatNumber` 的关系是「同一实现的固定档」而不是第二套实现：记账类数字
 * 缩成 1.2M 就没法对账，故这里钉死 plain 且强制 3 位分隔（M2 全局统一）。
 */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_VALUE;
  return formatPlain(value, true);
}

/** 历史入口（48 处调用）：与 `formatCount` 同一实现，禁止另写一份。 */
export function formatInt(value: number | null | undefined): string {
  return formatCount(value);
}

/** 定点小数（好感度分、比值等）：缺省 1 位，NaN/缺值 → UNKNOWN_VALUE。 */
export function formatDecimal(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_VALUE;
  return value.toFixed(clampDecimals(decimals, 1));
}

/**
 * 速率（M3）：**必须带分母单位**，不许只给裸比值。
 * `formatRate(142.25, '次', '小时')` → `142.3 次/小时`。
 */
export function formatRate(
  value: number | null | undefined,
  unit: string,
  per: string,
  options?: Pick<NumberFormatOptions, 'decimals'>
): string {
  const text = formatDecimal(value, options?.decimals ?? 1);
  if (text === UNKNOWN_VALUE) return UNKNOWN_VALUE;
  return `${trimZeros(text)} ${unit}/${per}`;
}

/** 历史入口：等价于 compact 档（保留名字，内部不再自算一套）。 */
export function compactNumber(value: number): string {
  return formatNumber(value, { unitSystem: 'compact' });
}

// ============================================================================
// 时间：时长写全、延迟留 ms（M3）
// ============================================================================

/**
 * 时长 → 天/小时/分/秒，**一律写到秒**。
 *
 * 旧实现在 days>0 时只给「X天Y小时」——「运行了 3 天 2 小时」到底是 2 小时 0 分
 * 还是 2 小时 59 分，读的人无法判断。负时长不可能存在（uptime 逆流＝上游算错），
 * 返回 UNKNOWN_VALUE 而不是静默当 0。
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return UNKNOWN_VALUE;
  }
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (days > 0) return `${days}天${hours}小时${minutes}分${secs}秒`;
  if (hours > 0) return `${hours}小时${minutes}分${secs}秒`;
  if (minutes > 0) return `${minutes}分${secs}秒`;
  return `${secs}秒`;
}

/** 历史入口（uptime）：与 `formatDuration` 同一实现。 */
export function formatUptime(seconds: number | null | undefined): string {
  return formatDuration(seconds);
}

/**
 * 延迟（ms 口径）：不足 1 秒给整数 ms，满 1 秒折成「秒」。
 * 🔴 这里**不许**出现「每秒」——延迟是一个耗时量，不是速率。
 */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_VALUE;
  if (value >= 1000) return `${trimZeros((value / 1000).toFixed(value >= 10000 ? 0 : 1))}秒`;
  return `${Math.round(value)}ms`;
}

// ============================================================================
// 日期：年月日 + 时分秒（M4）
// ============================================================================

// zh-CN 时间/日期时间两枚常驻 formatter（现场构造 Intl formatter 是本库最大的单项开销：
// PERF1 席实测单枚 29.6µs → 复用 0.80µs；等值性由 PERF1-fix1 席在本机全量样本自造复跑核清，
// 见 docs/design/unify-audit-20260919/PERF1-fix1.md §三——含 DST 时区补验，原台账未覆盖面已闭合；
// 证据已由 %TEMP% 脚本升为仓内常驻等值锁 lib/format.test.ts，PERF1-fix2/评审 I-2 收口）。
// 注：本库口径写死 zh-CN（与 i18next 语言无关），故 formatter 无需按 locale 建 key；
//     若将来改成跟随 UI 语言，必须换 Map<locale, formatter>，否则会串语言。
// 注2（评审 review-PERF1-fix1 M-3，下个跨时区核验的席必读）：**缓存 formatter 在构造期
//     绑定系统时区**，不随之后的 process.env.TZ / 系统时区改动而改口——跨时区核验脚本必须
//     在**构造之前**设好 TZ（本仓库 Node 侧的做法=设 TZ 后带查询串重新求值本模块），
//     否则 100% 假 DRIFT（评审席首轮亲测全红即栽在此）。运行期 OS 改时区后已加载页面
//     不重载则不跟随——旧逐次构造口径会跟随，该差异正是缓存优化本意，浏览器场景判可接受；
//     性质常驻锁见 format.test.ts「构造期绑定时区」条。
//
// hourCycle 用 'h23' 而不是 hour12:false：后者在 zh-CN 下可能落到 h24（午夜渲染成 24 时），
// 而「24时05分」不是任何排班表里的写法。字段全用 2-digit 让时分秒定宽（tabular-nums 对齐）。
const ZH_TIME = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
const ZH_DATE_TIME = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

/** formatToParts → 字段表（丢掉 literal 分隔符，由我们自己排中文单位）。 */
function partMap(formatter: Intl.DateTimeFormat, date: Date): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== 'literal') out[part.type] = part.value;
  }
  return out;
}

/** ISO → 本地展示（年月日 + 时分秒）；空值返回 UNKNOWN_VALUE，畸形文本原样透出不猜。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso; // 畸形文本原样透出，不猜。
  const p = partMap(ZH_DATE_TIME, date);
  return `${p.year}年${p.month}月${p.day}日 ${p.hour}时${p.minute}分${p.second}秒`;
}

/** 本地时钟（时分秒三字段齐全；冒号分隔以保日志列宽）。 */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN_VALUE;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const p = partMap(ZH_TIME, date);
  return `${p.hour}:${p.minute}:${p.second}`;
}

/** 后端 Unix 秒浮点（`time.time()`）→ 与 `formatDateTime` 同一口径。 */
export function formatUnixSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN_VALUE;
  return formatDateTime(new Date(Math.trunc(value) * 1000).toISOString());
}

const ISO_LITERAL = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/;

/**
 * 带时区偏移的 ISO → **按字面量**取年月日时分秒，不做任何时区换算。
 *
 * 与 `formatTimeLabel`（chart-model.ts）同一时区语义：后端 bucket_start 的偏移就是
 * 业务时区，转成本地时区会让「14 点的桶」显示在 06 点，且没人能看出这是时区错。
 * 缺秒按 0 秒写全（桶起点本就是整分）；只有日期时不编造时刻。
 */
export function formatIsoDateTime(iso: string | null | undefined): string {
  const text = String(iso ?? '').trim();
  if (!text) return '';
  const m = ISO_LITERAL.exec(text);
  if (!m) return text;
  const [, year, month, day, hour, minute, second] = m;
  const datePart = `${year}年${month}月${day}日`;
  if (hour === undefined) return datePart;
  return `${datePart} ${hour}时${minute}分${second ?? '00'}秒`;
}

/**
 * 带时区偏移的 ISO → **ASCII 时间戳** `YYYY-MM-DD HH:mm:ss`，按字面量取，不做时区换算。
 *
 * 为什么要这一个（用户 2026-10-20 点名「最后消息时间需 YYYY-MM-DD HH:mm:ss」）：
 * `formatDateTime` / 上面那版 `formatIsoDateTime` 走的是中文长形（`2026年10月18日 14时00分00秒`），
 * 它适合正文，但**作为表格列值会撑宽列、且无法直接与日志原文对照**——排查时复制一个中文时刻
 * 去 grep 日志永远 grep 不到，因为日志里写的是 ISO。两种形态服务两个场景，都留着。
 *
 * 时区语义与上面同一条：按字面量取，不换算。后端写的是带偏移的业务时区串，转本地会把
 * 「14 点的桶」显示在 06 点且没人看得出这是时区错（review M-3 同款坑）。
 * 缺秒按 0 秒补全；只有日期时不编造时刻；不可解析原样透出，不猜。
 */
export function formatIsoTimestamp(iso: string | null | undefined): string {
  const text = String(iso ?? '').trim();
  if (!text) return '';
  const m = ISO_LITERAL.exec(text);
  if (!m) return text;
  const [, year, month, day, hour, minute, second] = m;
  if (hour === undefined) return `${year}-${month}-${day}`;
  return `${year}-${month}-${day} ${hour}:${minute}:${second ?? '00'}`;
}

/** 趋势桶起点 → 坐标轴短标签（**轴不是正文**：轴标签保持短形，全字段走 tooltip）。 */
export function formatBucket(bucketStart: string, bucket: BucketCode): string {
  const date = new Date(bucketStart);
  if (Number.isNaN(date.getTime())) return bucketStart;
  if (bucket === 'day') {
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  }
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}
