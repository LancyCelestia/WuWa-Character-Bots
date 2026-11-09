// 控制面 REST 客户端。骨架采纳自 AxonHub frontend/src/lib/api-client.ts（Apache-2.0，已注明修改）。
// wave-2 对表（2026-09-18，DTO 真相源=control_plane/webui_stats.py + api/webui.py + api/events.py）：
// - baseURL 运行时可配（localStorage webui:baseUrl，缺省同源——挂 control_plane /ui 静态壳零配置）。
// - envelope 双层结构：HTTP 信封 {data, error, meta} → 内层语义包 {status, source|reason, data}。
//   apiRequest 解外层；resolveSemantic 解内层并区分 ok / source_unavailable（UI 呈现「暂无数据」）。
//   invalid_request 由后端映射为 HTTP 422 stats_invalid_query（走 ApiError，不在 200 语义态内）。
// - 端点路径对表：health/status/bot 在 /admin/api/v1/*（api/health.py prefix），统计四端点与
//   logs 在 /api/v1/*（api/webui.py、api/events.py prefix）——骨架旧路径 /api/v1/health 是错的。
// - Bearer 三槽令牌存于 localStorage（`webui:token:admin` / `webui:token:ro` /
//   `webui:token:super-admin`），刷新后仍在；内存里另留一份镜像，localStorage 不可用
//   （隐私模式/被禁）时静默降级为纯内存态。
//   令牌绝不进 URL／日志／DOM。写腿（配置/动作/凭据/可视化）只认超管令牌——后端
//   `_super_admin_dependency` 只比对 `BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256`；
//   主令牌管读面，只读令牌仅在读腿兜底。

const BASE_URL_KEY = 'webui:baseUrl';
/**
 * 令牌槽（三槽）。**固定字面量**：改名等于让所有已登录用户静默掉登录态。
 *
 * - ``admin``：主令牌（``BOT_CONTROL_PLANE_TOKEN_SHA256``），读面用；
 * - ``ro``：只读令牌，仅 GET 兜底；
 * - ``superAdmin``：超管令牌（``BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256``），
 *   **写腿唯一认的那把**（配置 preview/set/reset、动作 preview/execute、凭据整段
 *   路由、可视化 preview/save/theme 全挂 ``_super_admin_dependency``）。
 *   只填一次、仅存本机浏览器；绝不进 URL/日志。
 */
export type TokenKind = 'admin' | 'ro' | 'superAdmin';
const TOKEN_KEYS: Record<TokenKind, string> = {
  admin: 'webui:token:admin',
  ro: 'webui:token:ro',
  superAdmin: 'webui:token:super-admin',
};
/** 内存镜像：本页生命周期内先读它，省掉每次请求都摸一次 localStorage。 */
const sessionTokens: Record<TokenKind, string | null> = { admin: null, ro: null, superAdmin: null };

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // localStorage 不可用（file:// 极端隐私模式等）时静默：配置降级为内存态。
  }
}

/**
 * API 基址：'' = 同源（生产 /ui 挂载）；dev 下可指向 http://127.0.0.1:8742。
 *
 * 读路径与写路径**同过白名单**：持久化里的基址可能被 XSS／手工改 localStorage 写坏，
 * 只靠 ``setBaseUrl`` 的写入校验挡不住——``apiRequest`` 会按它拼 URL 并附上
 * ``Authorization: Bearer``，不校验就等于把令牌发往白名单外主机（正是 validateBaseUrl
 * 注释里声称要防的那件事）。非法/空值一律忽略，回落 env/同源。
 */
/**
 * env 基址解析（生产纯函数）：环境值是**另一个**可被部署/打包写坏的注入点，
 * 必须过与持久化值**同一把** `validateBaseUrl` 白名单尺，不能直接原样返回。
 * 导出以便测试对**真实生产逻辑**喂不同 env，而非替身函数。
 */
export function resolveEnvBaseUrl(rawEnv: string | undefined): string {
  if (!rawEnv) return '';
  const verdict = validateBaseUrl(rawEnv);
  return verdict.ok ? (verdict.value ?? '') : '';
}

export function getBaseUrl(): string {
  const stored = storageGet(BASE_URL_KEY);
  if (stored !== null) {
    const verdict = validateBaseUrl(stored);
    if (verdict.ok) return verdict.value ?? '';
  }
  // 回落 env：非 Vite 宿主（Node/测试/其它打包器）里 import.meta.env 可能不存在，
  // 读路径不得因此抛错；存在时也必须过白名单。
  let rawEnv: string | undefined;
  try {
    rawEnv = import.meta.env.VITE_API_BASE_URL as string | undefined;
  } catch {
    return '';
  }
  return resolveEnvBaseUrl(rawEnv);
}

export type BaseUrlVerdict =
  | { ok: true; value: string | null }
  | { ok: false; reason: 'invalid_url' | 'bad_scheme' | 'host_not_allowed' };

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost']);

/**
 * baseUrl 白名单校验（SECWEB Minor-2 纵深加固）：scheme 必须 http(s)，host 必须 ∈
 * {同源, 127.0.0.1, localhost}（任意端口）。空值=同源缺省，恒合法。
 * 动机：Bearer 令牌只允许发往本机控制面——白名单外的 host 拒绝保存，
 * 防误配把 Authorization 头带出本机。`http://127.0.0.1@evil.com` 类 userinfo 欺骗
 * 由 URL parser 正确归一 hostname 防住。
 */
export function validateBaseUrl(raw: string): BaseUrlVerdict {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: null };
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return { ok: false, reason: 'invalid_url' };
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { ok: false, reason: 'bad_scheme' };
  }
  const host = parsed.hostname.toLowerCase();
  const isLoopback = LOOPBACK_HOSTS.has(host);
  const isSameOrigin =
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:') &&
    parsed.origin === window.location.origin;
  if (!isLoopback && !isSameOrigin) return { ok: false, reason: 'host_not_allowed' };
  return { ok: true, value: trimmed.replace(/\/$/, '') };
}

export function setBaseUrl(value: string | null): void {
  if (value === null) {
    storageSet(BASE_URL_KEY, null);
    return;
  }
  // 纵深：非法值不落盘（UI 层保存前先 validateBaseUrl 校验并提示）。
  const verdict = validateBaseUrl(value);
  if (!verdict.ok) return;
  storageSet(BASE_URL_KEY, verdict.value);
}

/**
 * 读令牌：内存镜像优先，缺席才回落 localStorage（＝刷新后重新读回已保存的令牌）。
 *
 * 为什么读也要回落：刷新后内存是空的，不读持久化就等于「保存了但用不上」——正是用户
 * 说的「我填进去令牌了，但是无法保存」。读失败（隐私模式/被禁）时 storageGet 返回 null，
 * 表现为「没有已保存的令牌」，不抛错、不崩。
 */
export function getApiToken(kind: TokenKind = 'admin'): string | null {
  const cached = sessionTokens[kind];
  if (cached !== null) return cached;
  const persisted = storageGet(TOKEN_KEYS[kind]);
  const trimmed = persisted?.trim() || null;
  if (trimmed !== null) sessionTokens[kind] = trimmed;
  return trimmed;
}

/**
 * 写令牌：同时写内存镜像与 localStorage，并广播 `webui:credentials-changed`。
 *
 * 写前 trim（粘贴常带空格/换行）；空串或纯空白＝**删键**（不是存空串）——空串若真落盘，
 * 刷新后 getApiToken 会读回一个空令牌，界面又会说「已保存」。
 * localStorage 抛异常时 storageSet 内部静默，内存态照常可用。
 */
export function setApiToken(token: string | null, kind: TokenKind = 'admin'): void {
  const next = token?.trim() || null;
  sessionTokens[kind] = next;
  storageSet(TOKEN_KEYS[kind], next);
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('webui:credentials-changed'));
}

type ErrorResponseBody = {
  message?: string;
  error?: string | { message?: string; code?: string };
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

/**
 * 单次控制面请求上限（毫秒）。
 *
 * 🔴 为什么必须有：浏览器 fetch **没有**内建超时，react-query 也没有。后端一挂住
 * （重启中、事件循环被占、代理吞包），`query.isPending` 就永远为真，页面把那几张卡
 * 画成一排永久骨架条——既不是在加载，也永远等不到结果（主代理 CDP 截图实测：
 * 总览 27 根骨架条静止不动）。有界超时把「挂住」变成「失败」，`SemanticState` 才能
 * 如实说「加载失败」并给重试按钮。
 */
const REQUEST_TIMEOUT_MS = 15_000;

const isErrorResponseBody = (value: unknown): value is ErrorResponseBody => {
  if (!isRecord(value)) return false;
  const message = value.message;
  const error = value.error;
  const hasValidMessage = message === undefined || typeof message === 'string';
  const hasValidError =
    error === undefined ||
    typeof error === 'string' ||
    (isRecord(error) &&
      (error.message === undefined || typeof error.message === 'string') &&
      (error.code === undefined || typeof error.code === 'string'));
  return hasValidMessage && hasValidError;
};

/** /api/v1 envelope 宽容解包：信封含 data 字段即解，否则透传（避免与后端形态漂移耦合）。 */
function unwrapEnvelope<T>(payload: unknown): T {
  if (isRecord(payload) && 'data' in payload) return payload.data as T;
  return payload as T;
}

interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  headers?: Record<string, string>;
  body?: unknown;
  /**
   * 默认 'admin'（主槽）。语义：
   * - **写腿**（method !== 'GET'）：优先超管令牌，缺则回落主令牌——后端写端点只认
   *   ``BOT_CONTROL_PLANE_SUPER_ADMIN_TOKEN_SHA256``；
   * - **读腿**：主令牌优先，缺则回落超管令牌，再缺才回落只读令牌；
   * - 显式点槽（如凭据整段路由 ``auth: 'superAdmin'``）按点的那槽取，不在槽间串用。
   * 只读令牌**永不**用于写。
   */
  auth?: TokenKind | 'none';
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public response?: unknown,
    /**
     * 429 的 `Retry-After` 头原值（秒数字符串）。**原样保存**、不做解析：
     * 解析与「读不到就给 60 秒」的缺省归 `@/lib/rate-limit` 管，那里有单测。
     * 只在这一层抓头，是因为 `fetch` 的 Response 不跨越 throw 留在调用方手里。
     */
    public retryAfter?: string | null
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** 控制面错误码（error.code，如 control_plane_not_provisioned / stats_invalid_query）。 */
  get code(): string | null {
    if (isRecord(this.response) && isRecord(this.response.error) && typeof this.response.error.code === 'string') {
      return this.response.error.code;
    }
    return null;
  }
}

/**
 * 认证前的**最终目标**白名单纵深：不管基址来自哪里（localStorage/env/同源），
 * 也无论调用方传了什么 endpoint（相对、绝对、协议相对 `//host`），拼接后的**最终
 * 字符串**都必须按 URL 解析并落到同源或 loopback，否则拒绝整个请求。
 *
 * 动机：endpoint 可能在别处被拼上外部绝对 URL；只校验基址挡不住「基址合法但 endpoint
 * 越界」这条腿。返回 false 表示目标不可信，调用方必须在读取请求选项前拒发。
 */
function targetIsAllowed(url: string): boolean {
  // Parse every target as the browser does, including whitespace and backslashes.
  let parsed: URL;
  try {
    const base =
      typeof window !== 'undefined' && window.location
        ? window.location.origin
        : 'https://api-client.invalid';
    parsed = new URL(url, base);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
  const host = parsed.hostname.toLowerCase();
  if (LOOPBACK_HOSTS.has(host)) return true;
  return (
    typeof window !== 'undefined' &&
    (window.location.protocol === 'http:' || window.location.protocol === 'https:') &&
    parsed.origin === window.location.origin
  ) || (typeof window === 'undefined' && parsed.origin === 'https://api-client.invalid');
}

export async function apiRequest<T>(endpoint: string, options: ApiRequestOptions = {}): Promise<T> {
  const url = `${getBaseUrl()}${endpoint}`;
  if (!targetIsAllowed(url)) {
    throw new ApiError('API target is not allowed', 0, { error: { code: 'api_target_not_allowed' } });
  }
  const { method = 'GET', headers = {}, body, auth = 'admin', signal } = options;
  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  if (auth !== 'none') {
    // 槽位选择（见 ApiRequestOptions.auth 的注释）：写腿优先超管，读腿主→超管→只读；
    // 显式点槽就用点的那一槽。**只读令牌永不用于写**。
    const superAdmin = getApiToken('superAdmin');
    const token =
      auth === 'superAdmin'
        ? superAdmin
        : auth === 'ro'
          ? getApiToken('ro')
          : method !== 'GET'
            ? superAdmin ?? getApiToken('admin')
            : getApiToken('admin') ?? superAdmin ?? getApiToken('ro');
    // 一个令牌都没有 ⇒ 根本不发请求。原因（首屏 7 个并发查询同时 401 ⇒ 后端
    // 60s 内 5 次失败即限速 429 ⇒ 六张卡全显示「认证失败次数过多」）：无凭据的
    // 请求必然 401，发出去只会烧掉限速配额。这里直接抛与后端同语义的 503
    // not_provisioned，让 use-semantic-query 走「未配置令牌 → 去设置」引导。
    // ponytail: 只是省掉一次注定失败的往返，不是鉴权面——真 token 与否仍由后端判。
    if (!token) {
      throw new ApiError('Control plane is not provisioned (no access token)', 503, {
        error: { code: 'control_plane_not_provisioned' },
      });
    }
    // 附凭据前先对**最终目标**过白名单：越界目标一律不带 Bearer，绝不外送令牌。
    // （预算闸不在这里：本模块必须保持**零相对 import**——`api-client.test.ts` 与
    //  `control-center.test.ts` 都把它整体转译成 `data:` URL 加载，数据 URL 里
    //  解析不了 `./xxx`。闸门住在 `hooks/use-semantic-query.ts`。）
    requestHeaders['Authorization'] = `Bearer ${token}`;
  }

  // 有界超时：调用方自带 signal 时两者取先到（AbortSignal.any）；没带就只挂超时。
  // 分开持有 timeoutSignal，是为了在 catch 里分辨「超时」与「调用方主动取消」。
  const timeoutSignal = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  const effectiveSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;
  const requestOptions: RequestInit = { method, headers: requestHeaders, signal: effectiveSignal };
  if (body !== undefined && method !== 'GET') {
    requestOptions.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, requestOptions);
  } catch (error) {
    // 先判 abort 语义：`AbortSignal.timeout()` 的拒绝名是 **`TimeoutError`**，不是
    // `AbortError`（实测 `s.reason.name === 'TimeoutError'`）。旧实现只认 `AbortError`，
    // 于是 15 秒有界超时**从未生效**：超时被当成普通网络错（status 0）→ 又被重试两次
    // → 骨架条挂到 45 秒才说人话。现在两条都认，且以 `timeoutSignal.aborted` 为准分流。
    if (timeoutSignal.aborted) {
      throw new ApiError(`控制面 ${REQUEST_TIMEOUT_MS / 1000} 秒内没有响应`, 0, {
        error: { code: 'request_timeout' },
      });
    }
    if (error instanceof DOMException && (error.name === 'AbortError' || error.name === 'TimeoutError')) {
      // 走到这里说明是调用方主动取消（自带 signal 触发），不是超时：原样抛出，交给上层。
      throw error;
    }
    const message = error instanceof Error ? error.message : 'Network error occurred';
    throw new ApiError(message, 0);
  }

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
    let errorData: unknown = null;
    try {
      errorData = await response.json();
      if (isErrorResponseBody(errorData)) {
        if (errorData.message) errorMessage = errorData.message;
        else if (errorData.error) {
          errorMessage =
            typeof errorData.error === 'string' ? errorData.error : errorData.error.message || errorMessage;
        }
      }
    } catch {
      // 非 JSON 错误体：保留状态行
    }
    // 429 的 Retry-After 只在**这里是 Reader**：一进 catch/throw 就跟 Response 失联了。
    // 原样存（不解析），解析与缺省归 @/lib/rate-limit。
    throw new ApiError(errorMessage, response.status, errorData, response.headers.get('retry-after'));
  }

  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return unwrapEnvelope<T>(await response.json());
  }
  return undefined as T;
}

// ============ 语义包（内层 {status, source|reason, data}）============

export type SemanticResult<T> =
  | { state: 'ok'; data: T; source?: string }
  | { state: 'source_unavailable'; reason: string };

/** 内层语义包解析：status=ok → 数据；source_unavailable → 优雅降级态（UI 显示「暂无数据/未配置」）。 */
export function resolveSemantic<T>(payload: unknown): SemanticResult<T> {
  if (isRecord(payload) && payload.status === 'ok') {
    return { state: 'ok', data: (payload.data ?? null) as T, source: typeof payload.source === 'string' ? payload.source : undefined };
  }
  // 非 ok 但带 reason 的语义包一律降级（PAGES2 修正：memory/graph 全源缺失时 data 非空
  // {…stats 全 0}，旧条件 data==null 会把它误当裸数据透传）。
  if (isRecord(payload) && typeof payload.reason === 'string' && payload.status !== 'ok') {
    return { state: 'source_unavailable', reason: payload.reason };
  }
  // 兜底：非语义包形态（裸数据端点如 /admin/api/v1/health）直接当数据。
  return { state: 'ok', data: payload as T };
}

// ============ DTO（对表 webui_stats.py / metrics.py token_families / events.py）============

export interface TokenBlock {
  value: number | null;
  known_rows: number;
  unknown_rows: number;
  quality: 'complete' | 'partial' | 'unknown';
}

export interface TokenFamilyRow {
  family: string | null;
  calls: number;
  tokens: {
    input: TokenBlock;
    output: TokenBlock;
    cache_read: TokenBlock;
    cache_creation: TokenBlock;
  };
}

export interface CallsIdentityUser {
  user_id: string | null;
  sender_nickname: string | null;
  calls: number;
}

/** 一个"会话身份"聚合行（群合一行、私聊/系统按用户各自一行）。 */
export interface CallsIdentitySession {
  kind: 'group' | 'private' | 'email' | 'system' | string;
  platform: string | null;
  group_id: string | null;
  /** 群号出处：审计列 / 从 `group_<gid>_<uid>` 键派生（存量行没有列）。 */
  group_id_source?: 'audit_column' | 'session_id' | null;
  group_title: string | null;
  user_id: string | null;
  calls: number;
  users: CallsIdentityUser[];
}

export interface CallsIdentityBlock {
  /** 四列是否已在审计库里（存量库要等 bot 重启后的首次写入才补列）。 */
  available: boolean;
  fields: { collected: string[]; uncollected: string[] };
  sessions: CallsIdentitySession[];
}

export interface CallsData {
  window: string;
  total_calls: number;
  unknown_timestamp_calls: number;
  unattributed_calls: number;
  user_attribution: string;
  /** BACKEND3 增补：窗口内可归属用户去重数（unattributed 不计入，已单列）；旧控制面缺字段 → optional。 */
  active_users?: number;
  /** BACKEND3 增补：窗口内最新审计时间（UTC ISO；窗口内无记录=null，不造时间）。 */
  last_message_at?: string | null;
  /**
   * 身份链（D1–D4）：平台 / 群或频道 / 用户ID / 昵称。旧后端没有这块 → optional，
   * 页面按「未采集」整体降级（不许当 0 行数据）。
   */
  identity?: CallsIdentityBlock;
  by_session: Array<{ session: string | null; calls: number }>;
  by_user: Array<{ user: string; calls: number }>;
  by_capability: Array<{ capability: string | null; calls: number }>;
  trend: {
    bucket: 'hour' | 'day';
    timezone: string;
    /** 升序、窗口内每桶都在（空桶 calls=0）；旧控制面是倒序且只含非空桶。 */
    items: Array<{ bucket_start: string; calls: number }>;
    /** 轴超上限（200）按窗口右侧对齐裁掉的桶数；0=没裁。旧控制面缺字段。 */
    truncated_buckets?: number;
  };
  /**
   * 人 × 时段交叉表（稀疏：只含有调用的格子，横轴看 `trend.items`）。
   * 旧控制面**没有**这个字段；新控制面在归因率过低时**显式给 null** 并说明原因。
   * 缺字段与 null 都必须走降级文案，不许假装有。
   */
  trend_by_user?: {
    bucket: 'hour' | 'day';
    timezone: string;
    top_users: Array<{ user: string; calls: number }>;
    other_label: string;
    items: Array<{ bucket_start: string; user: string; calls: number }>;
  } | null;
  /** `trend_by_user` 为 null 时的固定原因码；非 null 时为 null。 */
  trend_by_user_reason?: 'insufficient_attribution' | string | null;
  /**
   * 轴覆盖度（旧控制面缺字段 → optional）：`available_buckets` 是**真有调用**的桶数，
   * 与 `requested_buckets` 的差距＝审计源撑不满这条轴；`first_data_at`/`last_data_at`
   * 是窗口内真实数据的最早/最晚时刻，用来算真实覆盖跨度（分钟）。
   * 消费方必须据此显式说明「历史数据不足」，不许把 2 个点画成一整天的趋势。
   */
  coverage?: {
    first_bucket: string | null;
    last_bucket: string | null;
    available_buckets: number;
    requested_buckets: number;
    truncated_by_source: boolean;
    first_data_at?: string | null;
    last_data_at?: string | null;
  };
}

export interface TokensData {
  window: string;
  totals: TokenFamilyRow;
  families: TokenFamilyRow[];
}

export interface LatencyItem {
  channel: string;
  state: string;
  consecutive_fails: number;
  latency_ms: number | null;
  ema_ms: number | null;
  samples: number;
  last_ok_at: string;
  last_error: string | null;
}

export interface LatencyData {
  items: LatencyItem[];
  history: { status: string; reason: string };
}

export interface AffinityItem {
  sender_id: string;
  nickname: string;
  affinity: number;
  score: number;
  tier: number;
  tier_name: string;
  interaction_count: number;
  updated_at: string;
}

export interface AffinityBoardData {
  order: 'desc' | 'asc';
  total: number;
  items: AffinityItem[];
}

export interface HealthData {
  ok: boolean;
  checks: Record<string, string>;
  generated_at: string;
}

export interface BotStatusData {
  started_at: string;
  uptime_seconds: number | null;
  timezone: string;
}

/** 日志事件行（events.py RuntimeEvent.to_dict）。 */
export interface LogEventRow {
  cursor: number;
  event_id: string;
  created_at: string;
  source: string;
  category: string;
  message: string;
  details: unknown;
}

export interface LogsSourcesData {
  items: string[];
  categories: string[];
  collector_status: string;
  collectors: unknown;
}

/**
 * `/api/v1/logs` 列表页（真身＝`control_plane/events.py` `RuntimeEventService.query()`）。
 * 升序游标页：`next_cursor` 在 `has_more` 时＝末行 cursor，否则＝当前高水位；`high_cursor`
 * 恒为高水位。410=cursor 已超出保留窗口（UI 必须提示缺口并让用户选择重新订阅，
 * 不得静默重置游标）。信封裸数据（非语义包）。
 */
export interface LogsPageData {
  items: LogEventRow[];
  next_cursor: number;
  has_more: boolean;
  high_cursor: number;
}

// ============ DTO（对表 control_plane/webui_knowledge.py / webui_plugins.py / webui_memory_graph.py，2026-09-19 PAGES2 增补）============

export interface KnowledgeCollection {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  source: string;
  count: number | null;
  reason: string | null;
}

export interface KnowledgeCollectionsData {
  items: KnowledgeCollection[];
}

/** 词条条目：字段随集合类型增减（meme_tags 有 count、kb_docs 有 chunk_count/updated_at、acg_sources 有 enabled），缺字段一律省略渲染。 */
export interface KnowledgeTerm {
  term: string;
  aliases: string[];
  definition: string | null;
  scope: string | string[];
  source: string;
  chunk_count?: number;
  updated_at?: string | null;
  count?: number;
  enabled?: boolean;
}

export interface KnowledgeTermsData {
  collection: string;
  page: number;
  page_size: number;
  total: number;
  items: KnowledgeTerm[];
}

/** 插件条目：builtins 含 id/kind；migrated_modules 含 module_count/entry_file_exists；hot_reload 三态严格（true/false/null）。
 * BACKEND3 增补（真相源=webui_plugins.py）：version（adapters=发行版链、migrated=域 __init__ 字面量、builtins 恒 null）；
 * trigger_hints（builtins=features descriptor aliases=能力别名，非聊天触发词全量；其余组 null）；
 * config_actions（/actions 注册表命名空间映射 [{action_id,name}]；空表=无）。旧控制面缺字段 → 一律 optional。 */
export interface PluginItem {
  name: string;
  description?: string;
  source: string;
  hot_reload: boolean | null;
  id?: string;
  kind?: string;
  enabled?: boolean | null;
  module_count?: number;
  entry_file_exists?: boolean;
  version?: string | null;
  trigger_hints?: string[] | null;
  config_actions?: Array<{ action_id: string; name: string }> | null;
}

export interface PluginGroup {
  id: 'builtins' | 'adapters' | 'event_matchers' | 'migrated_modules' | string;
  name: string;
  description: string;
  source: string;
  enabled: boolean;
  reason: string | null;
  items: PluginItem[];
}

export interface PluginsCatalogData {
  groups: PluginGroup[];
}

export type GraphWindow = '24h' | '7d' | '30d' | 'all';

export type MemoryGraphNodeType = 'person' | 'group' | 'conversation' | 'memory' | 'rule';

export interface MemoryGraphNode {
  id: string;
  type: MemoryGraphNodeType;
  label: string;
  weight: number | null;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  kind: string;
  weight: number;
}

export interface MemoryGraphStats {
  persons: number;
  groups: number;
  conversations: number;
  long_term_memories: number;
  learned_rules: number;
  speaker_count: number;
}

export interface MemoryGraphData {
  window: string;
  max_nodes: number;
  truncated: boolean;
  nodes_total: number;
  stats: MemoryGraphStats;
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  /** 各数据源状态：history/memory/quirks/affinity ∈ ok/missing/unreadable。 */
  sources: Record<string, string>;
}

// ============ 端点登记（路径对表 _app.py 装配）============

export type StatsWindow = '24h' | '7d' | '30d';

/**
 * 查询串构造（导出以便 control-center.ts 复用同一把 URL 门：只序列化显式给出的
 * 非空参数，绝不把 `undefined`/空串写进 query）。
 */
export const qs = (query: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : '';
};

export const controlApi = {
  /** /admin/api/v1/health（api/health.py，裸 dict 非语义包）。 */
  health: () => apiRequest<HealthData>('/admin/api/v1/health'),
  /** /admin/api/v1/status/bot（裸 dict）。 */
  statusBot: () => apiRequest<BotStatusData>('/admin/api/v1/status/bot'),
  /** /api/v1/stats/calls（语义包）。 */
  statsCalls: (query: { window?: StatsWindow; bucket?: 'hour' | 'day'; limit?: number } = {}) =>
    apiRequest<CallsData>(`/api/v1/stats/calls${qs({ window: query.window ?? '24h', bucket: query.bucket ?? 'hour', limit: query.limit })}`),
  /** /api/v1/stats/tokens（语义包；metrics_service 未接线时后端直接回 source_unavailable）。 */
  statsTokens: (query: { window?: StatsWindow; limit?: number } = {}) =>
    apiRequest<TokensData>(`/api/v1/stats/tokens${qs({ window: query.window ?? '24h', limit: query.limit })}`),
  /** /api/v1/stats/latency（语义包；无 query 参数）。 */
  statsLatency: () => apiRequest<LatencyData>('/api/v1/stats/latency'),
  /** /api/v1/affinity/board（语义包）。 */
  affinityBoard: (query: { limit?: number; order?: 'desc' | 'asc' } = {}) =>
    apiRequest<AffinityBoardData>(`/api/v1/affinity/board${qs({ limit: query.limit ?? 50, order: query.order ?? 'desc' })}`),
  /** /api/v1/logs/sources（信封裸数据，非语义包）。 */
  logsSources: () => apiRequest<LogsSourcesData>('/api/v1/logs/sources'),
  /**
   * /api/v1/logs 列表（信封裸数据；events.py:90 升序游标页）。
   * `after` 缺省＝从当前保留窗口最旧事件起读；`limit` 缺省 50（后端 1..500）。
   * 410 cursor_expired＝游标出窗（诚实报错，UI 提示缺口）。
   */
  logs: (query: { after?: number; limit?: number; source?: string; category?: string } = {}) =>
    apiRequest<LogsPageData>(
      `/api/v1/logs${qs({ after: query.after, limit: query.limit ?? 50, source: query.source, category: query.category })}`
    ),
  /**
   * /api/v1/logs/{event_id} 事件详情（信封裸数据；events.py:237）。
   * 404 event_not_found＝不存在或已出保留窗口；422 invalid_event_id＝标识非法。
   */
  logDetail: (eventId: string) => apiRequest<LogEventRow>(`/api/v1/logs/${encodeURIComponent(eventId)}`),
  /** /api/v1/knowledge/collections（语义包；知识目录）。 */
  knowledgeCollections: () => apiRequest<KnowledgeCollectionsData>('/api/v1/knowledge/collections'),
  /** /api/v1/knowledge/terms（语义包；page_size≤100，q≤200 字符，非法参数 → 422 knowledge_invalid_query）。 */
  knowledgeTerms: (query: { collection: string; q?: string; page?: number; pageSize?: number }) =>
    apiRequest<KnowledgeTermsData>(
      `/api/v1/knowledge/terms${qs({ collection: query.collection, q: query.q, page: query.page ?? 1, page_size: query.pageSize ?? 20 })}`
    ),
  /** /api/v1/plugins（语义包；四组固定顺序=builtins/adapters/event_matchers/migrated_modules）。 */
  pluginsCatalog: () => apiRequest<PluginsCatalogData>('/api/v1/plugins'),
  /** /api/v1/memory/graph（语义包；window 枚举四档，max_nodes≤200 缺省 120；前端取上限 200）。 */
  memoryGraph: (query: { window?: GraphWindow; maxNodes?: number } = {}) =>
    apiRequest<MemoryGraphData>(`/api/v1/memory/graph${qs({ window: query.window ?? '24h', max_nodes: query.maxNodes ?? 200 })}`),
};

/** SSE 日志尾流端点（fetch 流式读取；EventSource 无法带 Authorization 头，见 lib/sse.ts）。 */
export function logsStreamUrl(query: { after?: string; source?: string; category?: string; heartbeat?: string } = {}): string {
  return `${getBaseUrl()}/api/v1/logs/stream${qs(query)}`;
}
