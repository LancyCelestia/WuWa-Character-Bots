// 控制面 REST 客户端。骨架采纳自 AxonHub frontend/src/lib/api-client.ts（Apache-2.0，已注明修改）。
// wave-2 对表（2026-09-18，DTO 真相源=control_plane/webui_stats.py + api/webui.py + api/events.py）：
// - baseURL 运行时可配（localStorage webui:baseUrl，缺省同源——挂 control_plane /ui 静态壳零配置）。
// - envelope 双层结构：HTTP 信封 {data, error, meta} → 内层语义包 {status, source|reason, data}。
//   apiRequest 解外层；resolveSemantic 解内层并区分 ok / source_unavailable（UI 呈现「暂无数据」）。
//   invalid_request 由后端映射为 HTTP 422 stats_invalid_query（走 ApiError，不在 200 语义态内）。
// - 端点路径对表：health/status/bot 在 /admin/api/v1/*（api/health.py prefix），统计四端点与
//   logs 在 /api/v1/*（api/webui.py、api/events.py prefix）——骨架旧路径 /api/v1/health 是错的。
// - Bearer 双 token（webui:bearer 主令牌 / webui:bearer:ro 只读令牌）；控制面禁 token 进 URL/query。
//   Phase A 全部端点为只读：主令牌缺席时回退只读令牌（读依赖两者皆收，auth.py _v1_read_dependency）。

const BASE_URL_KEY = 'webui:baseUrl';
const ADMIN_TOKEN_KEY = 'webui:bearer';
const READONLY_TOKEN_KEY = 'webui:bearer:ro';

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

/** API 基址：'' = 同源（生产 /ui 挂载）；dev 下可指向 http://127.0.0.1:8742。 */
export function getBaseUrl(): string {
  return storageGet(BASE_URL_KEY) ?? (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '';
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
    host === window.location.hostname.toLowerCase();
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

export function getApiToken(kind: 'admin' | 'ro' = 'admin'): string | null {
  return storageGet(kind === 'admin' ? ADMIN_TOKEN_KEY : READONLY_TOKEN_KEY);
}

export function setApiToken(token: string | null, kind: 'admin' | 'ro' = 'admin'): void {
  storageSet(kind === 'admin' ? ADMIN_TOKEN_KEY : READONLY_TOKEN_KEY, token && token.trim() ? token.trim() : null);
}

type ErrorResponseBody = {
  message?: string;
  error?: string | { message?: string; code?: string };
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

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
  /** 默认 'admin'（缺主令牌时回退 'ro'）；'ro' 强制只读令牌；'none' 不带鉴权头。 */
  auth?: 'admin' | 'ro' | 'none';
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public response?: unknown
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

export async function apiRequest<T>(endpoint: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = 'GET', headers = {}, body, auth = 'admin', signal } = options;

  const url = `${getBaseUrl()}${endpoint}`;
  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  };

  if (auth !== 'none') {
    const token = getApiToken(auth) ?? (auth === 'admin' ? getApiToken('ro') : null);
    if (token) requestHeaders['Authorization'] = `Bearer ${token}`;
  }

  const requestOptions: RequestInit = { method, headers: requestHeaders, signal };
  if (body !== undefined && method !== 'GET') {
    requestOptions.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, requestOptions);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
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
    throw new ApiError(errorMessage, response.status, errorData);
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
  by_session: Array<{ session: string | null; calls: number }>;
  by_user: Array<{ user: string; calls: number }>;
  by_capability: Array<{ capability: string | null; calls: number }>;
  trend: { bucket: 'hour' | 'day'; timezone: string; items: Array<{ bucket_start: string; calls: number }> };
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

const qs = (query: Record<string, string | number | undefined>) => {
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
