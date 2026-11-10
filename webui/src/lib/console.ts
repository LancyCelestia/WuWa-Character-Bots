// 控制台总台（W12 W2-UI，用户裁定「真正的面板」）的**纯函数口径**。
//
// 为什么判定住在这里而不是 `pages/console.tsx`：总台每一块都在**声称一个状态**
// （在线/降级/未接入/0%），判据写在组件里就等于没有判据——既测不到，也会随渲染
// 细节漂移。本文件零 React 依赖，`node --test` 可直接加载（同 labels.ts 先例）。
//
// 端点口径：本文件只做形状与阈值判定，不发请求；请求全在页面里经由既有端点
// （health / status/bot / stats/calls / metrics/overview / logs / metrics/resources /
// llm/channels / llm/health / config/catalog / config/commands / actions/runs）——
// 一律是后端**已经存在**的路由，不新增契约。

/** 窄档位：只表达「好/注意/坏/不可判」四态，映射到 `CategoryChip` 的 tone 子集。 */
export type ConsoleTone = 'good' | 'warn' | 'bad' | 'flat';

// ============================================================================
// 一、/console 路由族映射（单一真身）
// ============================================================================

/** 控制台挂载根：后端把 /console 与 /console/* 都交给同一份 index.html。 */
export const CONSOLE_ROOT = '/console';

export interface ConsolePageRow {
  /** 旧 hash 路由路径（`#/calls` 里的 `/calls`）。 */
  legacy: string;
  /** /console 族下的真路径。 */
  console: string;
  /** 导航短标题（沿用既有页面中文名，不新造一套叫法）。 */
  title: string;
}

/**
 * 18 条一页一行的映射表，条数由 `console.test.ts` 与 `pages/` 目录对表锁死。
 * `pages/` 现有 17 个 `.tsx`：其中 `control-center.tsx` 一份实现撑**两行**
 * （`/resources` + `/models`），故 17 个文件对应 18 条行。
 *
 * 两处路径要让出，都不是某页的 URL：
 *   - `/`（总览）让出 `/console/overview`——`/console` 本身是总台入口，不能被某一页占用
 *     （否则「总台」与「总览页」是两个东西却同一个 URL）；
 *   - 总台页让出 `/console/console`——`routePathFor()` 规定 `/console` 与
 *     `/console/overview` 都回总览，总台自己的真路径因此是 `/console/console`。
 *
 * `dashboard.tsx` 就是旧路由 `/` 那一行（展示名「总览」），不另占行。
 */
export const CONSOLE_PAGES: readonly ConsolePageRow[] = [
  // `dashboard` 只改展示名：它的旧路由就是 `/`，而 `/` 在表里已被总览占用（两者本就是同一页）。
  { legacy: '/', console: '/console/overview', title: '总览' },
  { legacy: '/console', console: '/console/console', title: '总台' },
  { legacy: '/calls', console: '/console/calls', title: '调用' },
  { legacy: '/tokens', console: '/console/tokens', title: 'Token' },
  { legacy: '/latency', console: '/console/latency', title: '延迟' },
  { legacy: '/affinity', console: '/console/affinity', title: '好感度' },
  { legacy: '/sessions', console: '/console/sessions', title: '会话' },
  { legacy: '/logs', console: '/console/logs', title: '日志' },
  { legacy: '/knowledge', console: '/console/knowledge', title: '知识库' },
  { legacy: '/plugins', console: '/console/plugins', title: '插件' },
  { legacy: '/memory-graph', console: '/console/memory-graph', title: '记忆图谱' },
  { legacy: '/config', console: '/console/config', title: '参数' },
  { legacy: '/persona', console: '/console/persona', title: '人格' },
  { legacy: '/resources', console: '/console/resources', title: '资源' },
  { legacy: '/models', console: '/console/models', title: '模型' },
  { legacy: '/visual-editor', console: '/console/visual-editor', title: '布局编辑' },
  { legacy: '/appearance', console: '/console/appearance', title: '外观' },
  { legacy: '/credentials', console: '/console/credentials', title: '凭据' },
  { legacy: '/operations', console: '/console/operations', title: '受控动作' },
] as const;

/** 旧 hash 路由 → /console 族真路径；不认识返回空串（调用方据此报「不认识」）。 */
export function consolePathForLegacy(legacy: string): string {
  const row = CONSOLE_PAGES.find((item) => item.legacy === legacy);
  return row ? row.console : '';
}

/** /console 族真路径 → 旧 hash 路由；`/console` 本身与未知路径返回空串。 */
export function legacyPathForConsole(path: string): string {
  const row = CONSOLE_PAGES.find((item) => item.console === path);
  return row ? row.legacy : '';
}

/**
 * 旧 hash 深链认领：`#/plugins` → `/console/plugins`（W12 用户截图：地址栏带 `#/plugins`，
 * 侧栏高亮「插件」，正文却渲染总览）。
 *
 * 为什么需要：路由换成 browser history 后只读 `location.pathname`，而旧书签/缓存里的
 * `location.hash` 仍原样留在地址栏——两条信息源各说各话。入口拿本函数的返回值
 * `replaceState` 掉那个 `#`，地址栏与正文就一致了。
 *
 * 判据：
 *   ① 只认旧式 `#/…`（含裸 `#`，那是总览）。`#section` 这类页面内锚点一律不认领，
 *      返回空串＝调用方什么都不做；
 *   ② 映射表就是上面那张 `CONSOLE_PAGES`，**不另起第二份**；
 *   ③ 认不出的旧路径不猜、也不原样送回（送回则 `#` 永远清不掉），返回空串＝调用方
 *      整段去掉 hash，回默认页；
 *   ④ 查询串原样带过去，只换路径。
 */
export function legacyHashPath(hash: string): string {
  const raw = typeof hash === 'string' ? hash : '';
  if (raw === '') return '';
  if (!raw.startsWith('#')) return '';
  const body = raw.slice(1);
  // 裸 `#` 与 `#/...` 才算旧式路由；`#section-2` 是现代页面的锚点，不碰。
  if (body !== '' && !body.startsWith('/')) return '';
  const queryAt = body.indexOf('?');
  const legacyPath = queryAt === -1 ? body : body.slice(0, queryAt);
  const query = queryAt === -1 ? '' : body.slice(queryAt);
  const target = consolePathForLegacy(legacyPath === '' ? '/' : legacyPath);
  if (!target) return '';
  return `${target}${query}`;
}

// ============================================================================
// 二、真路径 → 路由路径（UI3 起在 lib/route-path.ts）
// ============================================================================
//
// UI2 的 `bootHashFor()`（真路径折成 hash）已整段删除：路由换成 browser history 后
// 不再有 hash 这一跳，`/console/calls` 直接就是 `/calls` 页面。映射逻辑活着，
// 但搬到 `@/lib/route-path`（它要能被 `node --test` 直接加载，不能 import 本文件）。
// 本文件上面那张 `CONSOLE_PAGES` 映射表仍然有效——它是「旧深链 `/ui/#/calls` 该去哪儿」
// 的登记面，也是 `lib/route-path.ts` 里 `/console/overview` 那条判据的出处。

// ============================================================================
// 三、日志页合并 / 尾窗
// ============================================================================

interface CursorRow {
  cursor: number;
  event_id: string;
}

/**
 * 多页日志合并：按 `event_id` 去重（跨页边界会重叠）、按 `cursor` 升序。
 * 升序是后端语义（`events.py query()` 升序游标页），降序找「最近」在调用方做。
 */
export function mergeLogPages<T extends CursorRow>(pages: ReadonlyArray<readonly T[]>): T[] {
  const seen = new Set<string>();
  const rows: T[] = [];
  for (const page of pages) {
    for (const row of page) {
      if (seen.has(row.event_id)) continue;
      seen.add(row.event_id);
      rows.push(row);
    }
  }
  return rows.sort((left, right) => left.cursor - right.cursor);
}

/** 取尾窗（最近 n 条），保持原顺序；`n<=0` → 空表。 */
export function tailErrors<T>(rows: readonly T[], n: number): T[] {
  if (!Number.isFinite(n) || n <= 0) return [];
  return rows.slice(Math.max(0, rows.length - Math.floor(n)));
}

// ============================================================================
// 四、错误率（账本真值，不造分母）
// ============================================================================

export interface ErrorRate {
  /** 失败率 0..1；分母未知/为 0 时 **null**（不得把 0/0 说成 0%）。 */
  ratio: number | null;
  tone: ConsoleTone;
}

/** 2% 以下 good、20% 以下 warn、其余 bad（阈值住在纯函数里，页面只消费）。 */
export function errorRate(
  failed: number | null | undefined,
  total: number | null | undefined
): ErrorRate {
  const hasFailed = typeof failed === 'number' && Number.isFinite(failed);
  const hasTotal = typeof total === 'number' && Number.isFinite(total);
  if (!hasFailed || !hasTotal || (total as number) <= 0) return { ratio: null, tone: 'flat' };
  const ratio = Math.max(0, failed as number) / (total as number);
  if (ratio >= 0.2) return { ratio, tone: 'bad' };
  if (ratio >= 0.02) return { ratio, tone: 'warn' };
  return { ratio, tone: 'good' };
}

// ============================================================================
// 五、进程健康
// ============================================================================

export interface HealthLine {
  ok: number;
  total: number;
  tone: ConsoleTone;
}

/**
 * `/admin/api/v1/health` 的 `ok` + `checks` → 一行摘要。
 * `checks` 缺席/空表不得算「全绿」（0 项检查不等于健康），判 warn 让用户知道没验到。
 */
export function healthLine(
  ok: boolean | null | undefined,
  checks: Record<string, string> | null | undefined
): HealthLine {
  const entries = checks && typeof checks === 'object' ? Object.values(checks) : [];
  const total = entries.length;
  const okCount = entries.filter((value) => value === 'ok').length;
  if (ok === false) return { ok: okCount, total, tone: 'bad' };
  if (total === 0) return { ok: 0, total: 0, tone: 'warn' };
  return { ok: okCount, total, tone: okCount === total ? 'good' : 'warn' };
}

// ============================================================================
// 六、LLM 通道
// ============================================================================

interface ChannelHealthRow {
  health?: {
    state?: string;
    consecutive_fails?: number;
    cooldown_active?: boolean;
  } | null;
}

export interface ChannelRollup {
  ok: number;
  degraded: number;
  unavailable: number;
  unknown: number;
  cooling: number;
  tone: ConsoleTone;
}

/**
 * `/api/v1/llm/channels` → 一行摘要。
 * 判据顺序：冷却/不可用压过一切（bad）＞ 降级（warn）＞ 有 ok（good）＞ 其余 flat。
 * `unknown` **不计入 ok**——健康层未接线时全是 unknown，谎报成正常是最坏的假绿。
 */
export function channelRollup(rows: readonly ChannelHealthRow[]): ChannelRollup {
  let ok = 0;
  let degraded = 0;
  let unavailable = 0;
  let unknown = 0;
  let cooling = 0;
  for (const row of rows) {
    const health = row?.health ?? {};
    if (health.cooldown_active === true) cooling += 1;
    switch (health.state) {
      case 'ok':
        ok += 1;
        break;
      case 'degraded':
        degraded += 1;
        break;
      case 'unavailable':
        unavailable += 1;
        break;
      default:
        unknown += 1;
    }
  }
  let tone: ConsoleTone = 'flat';
  if (cooling > 0 || unavailable > 0) tone = 'bad';
  else if (degraded > 0) tone = 'warn';
  else if (ok > 0) tone = 'good';
  return { ok, degraded, unavailable, unknown, cooling, tone };
}

// ============================================================================
// 七、待办（配置命令 + 动作回执）
// ============================================================================

interface CommandRow {
  status?: string;
}

interface RunRow {
  state?: string;
  result?: unknown;
}

export interface TodoRollup {
  pending: number;
  consent: number;
  conflict: number;
  failed: number;
  running: number;
  degraded: number;
  total: number;
  tone: ConsoleTone;
}

/**
 * 待办只算「还没定论」的行：`applied`/`succeeded` 不进待办（已经落地）。
 * `result.status === 'degraded'` 是 handler 的最终判定——即便 `state=succeeded`
 * 也照实进待办（真身语义见 `lib/control-center.ts` 的 `pendingReceipt`）。
 */
export function todoRollup(
  commands: readonly CommandRow[],
  runs: readonly RunRow[]
): TodoRollup {
  const rollup: TodoRollup = {
    pending: 0,
    consent: 0,
    conflict: 0,
    failed: 0,
    running: 0,
    degraded: 0,
    total: 0,
    tone: 'flat',
  };
  for (const command of commands) {
    switch (command?.status) {
      case 'pending':
      case 'leased':
        rollup.pending += 1;
        break;
      case 'needs_consent':
        rollup.consent += 1;
        break;
      case 'conflict':
        rollup.conflict += 1;
        break;
      case 'failed':
        rollup.failed += 1;
        break;
      case 'unknown':
        rollup.running += 1;
        break;
      default:
        break;
    }
  }
  for (const run of runs) {
    if (run?.state === 'failed') {
      rollup.failed += 1;
      continue;
    }
    if (run?.state === 'running') {
      rollup.running += 1;
      continue;
    }
    const result = run?.result;
    const status =
      result !== null && typeof result === 'object'
        ? (result as Record<string, unknown>).status
        : undefined;
    if (status === 'degraded' || status === 'unavailable' || status === 'unknown') {
      rollup.degraded += 1;
    }
  }
  rollup.total =
    rollup.pending + rollup.consent + rollup.conflict + rollup.failed + rollup.running + rollup.degraded;
  rollup.tone = rollup.failed > 0 ? 'bad' : rollup.total > 0 ? 'warn' : 'flat';
  return rollup;
}

// ============================================================================
// 八、队列积压
// ============================================================================

interface Measurement {
  value?: number | null;
  status?: string;
  reason?: string | null;
}

export interface QueueLine {
  text: string;
  tone: ConsoleTone;
}

/**
 * 只把**真身确实发过的** reason 翻成人话（`resources.py` 的 `not_connected` /
 * `not_supported`），其余码原样透出——未知码不猜语义（同 `describeReason` 口径）。
 */
const QUEUE_REASON_TEXT: Record<string, string> = {
  not_connected: '未接入',
  not_supported: '不提供',
};

/**
 * `/api/v1/metrics/resources` 的 `measurements.queue_depth`。
 * 未接入就写「未接入」，**绝不写 0**——0 与「不知道」是两件事（format.ts 同款口径）。
 */
export function queueLine(measurement: Measurement | null | undefined): QueueLine {
  if (!measurement || typeof measurement !== 'object') return { text: '不可知', tone: 'flat' };
  const value = measurement.value;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    const reason = typeof measurement.reason === 'string' ? measurement.reason : '';
    return { text: QUEUE_REASON_TEXT[reason] ?? (reason || '未接入'), tone: 'flat' };
  }
  if (value <= 0) return { text: String(value), tone: 'good' };
  if (value < 100) return { text: String(value), tone: 'warn' };
  return { text: String(value), tone: 'bad' };
}

// ============================================================================
// 九、配置摘要
// ============================================================================

interface ConfigRowShape {
  writable?: boolean;
  can_write?: boolean;
  restart_required?: boolean;
  sensitive?: boolean;
}

export interface ConfigSummary {
  total: number;
  writable: number;
  restartRequired: number;
  sensitive: number;
}

/** 三轴分开计数（可写 / 重启生效 / 敏感），**不合并**成一个数——三件事三种后果。 */
export function configSummary(rows: readonly ConfigRowShape[]): ConfigSummary {
  const summary: ConfigSummary = { total: 0, writable: 0, restartRequired: 0, sensitive: 0 };
  for (const row of rows) {
    if (!row) continue;
    summary.total += 1;
    if (row.writable === true || row.can_write === true) summary.writable += 1;
    if (row.restart_required === true) summary.restartRequired += 1;
    if (row.sensitive === true) summary.sensitive += 1;
  }
  return summary;
}
