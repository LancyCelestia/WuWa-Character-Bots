import { apiRequest, qs } from './api-client';
import { ownerConsentHeaders } from './owner-consent';

/**
 * 配置目录／单键行。真身＝`control_plane/config_service.py` 的 `catalog()` / `_row()` /
 * `preview()`（preview 返回同一行 + `preview: true`）。
 * 风险档唯一字段是 `tier`（另有 `risk_source`）；后端**不发** `risk_tier`（已按父确认清除）。
 */
export interface ConfigRow {
  key: string; value?: unknown; type?: string; description?: string; summary?: string;
  version?: number; writable?: boolean; can_write?: boolean; tier?: string; hot_reload?: boolean; restart_required?: boolean;
  sensitive?: boolean; source?: string; state?: string;
}
export interface Measurement { value: number | null; status: string; reason: string | null; unit: string }
export interface Resources { pid: number; process_role: string; captured_at: string; measurements: Record<string, Measurement> }
/**
 * 白名单动作目录条目。真身＝`control_plane/actions.py` 的
 * `ControlActionDescriptor.to_dict()`（`detail()` 再补 `version`/`available`）。
 * 🔴 后端发的是 `action_id`（**不是** `id`），且没有 `description`/`risk_tier`——权限只由
 * `required_roles` 表达。本接口当前无消费方（`operations.tsx` 自带 `Action` 接口）。
 */
export interface ActionItem {
  action_id: string; label: string; required_roles?: string[]; confirmation_required?: boolean;
  timeout_seconds?: number; cancel_supported?: boolean; rollback_supported?: boolean;
  version?: number; available?: boolean;
}
/**
 * 三类回执的并集。真身＝`config_commands.py` 的 `public_command()`（配置命令）、
 * `actions.py` 的 `_public()`（动作运行）、`actions.py` 的 `preview()`（动作预览）：
 * - 配置命令：`command_id` + `status` + `result`；
 * - 动作运行：`run_id` + `state` + `result` + `error_code`；
 * - 动作预览：`confirmation_token`（+ expected_version），无状态字段。
 * 结果字段唯一名是 `result`（后端从不发 `details`，已按父确认清除）。
 */
export interface RunReceipt {
  status?: string; state?: string; command_id?: string; run_id?: string; version?: number;
  confirmation_token?: string; result?: unknown; error_code?: string | null;
}
/**
 * 动作执行记录详情。真身＝`control_plane/actions.py` `ControlActionService._public()`
 * （HTTP 面 `api/actions.py:37` GET `/api/v1/actions/runs/{run_id}`）。
 * `created_at`/`updated_at` 是 `time.time()` 的 **Unix 秒浮点**（不是 ISO 字符串）。
 * `result` 为 handler 返回的原始对象（可能含 `status: ok|degraded|failed` 与
 * `details.execution`，交 `pendingReceipt` 判读）。404 action_run_not_found。
 */
export interface ActionRunDetail {
  run_id: string; action_id: string; actor: string; request_id: string; version: number;
  state: string; error_code: string | null; created_at: number; updated_at: number; result: unknown;
}
export interface ModelRows { items?: Array<Record<string, unknown>>; status?: string; reason?: string }

/**
 * `snowluma.status` 动作的 details（真身＝`control_plane/_app.py`
 * `_normalise_probe_legs()`）。W12 起三条腿分开报，**不要**再合并成一个 bool：
 * - `connected`：**历史字段，语义是 OneBot 连接**（不是 SnowLuma 好没好）；
 * - `onebot_connected`：NoneBot 里有没有 online 的 OneBot bot（收/发得动）；
 * - `snowluma_process`：端口腿——`true` 至少一个节点在听，`false` 全死，
 *   `null` 没配端口（不知道，**不是**"坏了"）；
 * - `snowluma_ports`：逐节点 `{"3011": true, "3014": false}`（键是**字符串**）；
 *   `source: probe_error` 时为空对象。
 *
 * ⚠️ `snowluma_process` 只证明"进程在听端口"，不证明 QQ 账号登录态。
 */
export interface SnowlumaStatusDetails {
  connected: boolean; onebot_connected: boolean;
  snowluma_process: boolean | null; snowluma_ports: Record<string, boolean>;
  source: 'runtime_probe' | 'probe_not_configured' | 'probe_error' | string;
  probed_at?: string;
}


// ============ DTO（对表 control_plane/llm_admin.py，2026-10-15 client 席增补）============

/** `/api/v1/llm/providers`（`LLMControlService.providers()`）：按 origin 聚合；provider_id＝`prov-`+sha256(origin)[:10]。 */
export interface LLMProviderRow {
  provider_id: string; label: string; origin: string; channel_ids: string[]; models: string[];
  credentials_configured: number; channels: number;
}
export interface LLMProvidersData { items: LLMProviderRow[] }
/** 渠道健康行（`_channel_health_row()`）：健康层未接线时 state=unknown、reason=source_unavailable/no_sample。 */
export interface LLMChannelHealth {
  state: string; reason?: string; ema_ms: number | null; samples: number;
  consecutive_fails: number; cooldown_active: boolean; last_ok_at: string | null;
}
/** `/api/v1/llm/channels`（`channels()`）：一注册条目＝一渠道；凭证只暴露指纹与数量，绝不回明文。 */
export interface LLMChannelRow {
  channel_id: string; model: string; model_family: string; provider_id: string; origin: string | null;
  priority: number; tags: string[]; routing_group: string | null; effort_override: string;
  auto_routable: boolean; health: LLMChannelHealth;
  credential: { state: 'configured' | 'missing'; fingerprint: string | null; key_count: number };
  price_per_m: Record<string, number> | null; price_per_call: number | null;
}
export interface LLMChannelsData { items: LLMChannelRow[] }
/** `/api/v1/llm/health`（`health_view()`）：disabled＝健康层未启用；totals 只含出现过的状态键。 */
export interface LLMHealthData {
  status: 'ok' | 'degraded' | 'disabled' | string; health_layer_enabled: boolean; latency_first: boolean;
  totals: Record<string, number>; cooling_ids: string[]; unavailable_ids: string[]; source: string; generated_at: string;
}
/** `/api/v1/llm/routes`（`routes_view()`）：只列 auto_routable 模型的候选序与生效策略。 */
export interface LLMRoutesData {
  policy: {
    strict_priority: boolean; latency_first: boolean; health_layer_enabled: boolean;
    failover_max_seconds: number; failover_min_hop_seconds: number; timeout_seconds: number;
    max_input_tokens: number; max_output_tokens: number;
    priority_groups: { count: number; active_name: string; active_order: string[] };
  };
  routes: Array<{ model: string; channels: Array<Record<string, unknown>> }>;
}

// ============ DTO（对表 control_plane/metrics.py，2026-10-15 client 席增补）============

/** 账本聚合块（`metrics.py` `_aggregate()`）：provider 归因本轮未验证；attempt/failover 未可靠记录 ⇒ value 恒 null。 */
export interface MetricsAggregate {
  provider_identity_quality: string; provider_identity_source_code: string;
  recorded_calls: number; successful_calls: number; failed_calls: number;
  unknown_status_calls: number; unknown_timestamp_calls: number;
  tokens: Record<string, { value: number | null; known_rows: number; unknown_rows: number; quality: 'complete' | 'partial' | 'unknown' }>;
  attempt_total: { value: null; quality: string; reason: string };
  failover_calls: { value: null; quality: string; reason: string };
}
/** 账本语义包（`metrics.py` `_read()`）：服务未接线＝200 + source_unavailable + data:null（非 HTTP 错误）。 */
export type MetricsUsage<T> =
  | { status: 'ok'; source: string; data: T }
  | { status: 'source_unavailable'; reason: string; data: null };
/** `/api/v1/metrics/overview`（`v1.py:278`）：资源快照 + 账本 overview 语义包并排返回。 */
export interface MetricsOverviewData {
  resources: {
    pid: number; process_role: string; captured_at: string;
    measurements: Record<string, { value: number | null; status: string; reason: string | null; unit: string }>;
  };
  usage: MetricsUsage<MetricsAggregate>;
}
/** 分组行＝`{<label>: key}` 叠在聚合块上（label ∈ model/provider/session/bucket_start）。 */
export type MetricsGroupedRow<T extends string> = Record<T, string> & MetricsAggregate;
/** `/api/v1/metrics/sessions`：聚合块 + sessions 分组。 */
export interface MetricsSessionsData extends MetricsAggregate { sessions: Array<MetricsGroupedRow<'session'>> }
/** `/api/v1/metrics/trends`：聚合块 + bucket 元信息 + items 分组（时桶倒序）。 */
export interface MetricsTrendsData extends MetricsAggregate {
  bucket: 'hour' | 'day'; timezone: string; items: Array<MetricsGroupedRow<'bucket_start'>>;
}

export function configValue(text: string): unknown {
  try { return JSON.parse(text); } catch { return text; }
}
export function safeText(value: unknown): string {
  if (value === null || value === undefined) return '—';
  return typeof value === 'string' ? value : JSON.stringify(value);
}
/**
 * 回执行人话词表。handler 判定（`result.status`）与顶层生命周期（`state`/`status`）
 * **共用同一份**，避免同义两种文案分叉。真身词源见 `pendingReceipt` 注释。
 */
const RECEIPT_LABELS: Record<string, string> = {
  pending: '已提交，等待 Bot 消费', queued: '已排队，尚未执行',
  leased: 'Bot 已取走执行中；勿重复提交，等回执',
  needs_consent: '需要超管批准；此笔尚未落库', consent_required: '需要超管批准；此笔尚未落库',
  applied: '配置已落库；运行时生效请核实际状态', completed: '执行器已完成',
  running: '执行中；结果未知前勿重复提交',
  succeeded: '执行成功，请核回执', failed: '执行失败，未确认生效',
  conflict: '版本冲突，本笔未生效；请重新读取后再提交',
  timed_out: '已超时，结果未知；勿盲目重复提交', cancelled: '已取消，未执行',
  expired: '请求已过期，请重新预览',
  registered: '动作已登记，但执行适配未连接', unknown: '执行状态未知，勿盲目重复提交',
};
/**
 * 回执行人话。**优先级**：先看 `result` 里的 handler 最终判定（降级/未接/失败——即使
 * `state === 'succeeded'` 也绝不报「执行成功」），再看顶层 `state ?? status`。
 * 冲突口径：`state`/`status` 只描述运行生命周期，**失败/取消/超时优先**，绝不因
 * `result.status === 'ok'` 被翻成成功。
 *
 * 真身：
 * - `result.status`：`_app.py` 动作 handler 的 `ok|degraded|failed`；`degraded` 覆盖
 *   `send_queue_not_connected`、snowluma 探针失败、以及未实现动作的
 *   `{"status":"degraded","details":{"state":"registered","execution":"adapter_not_connected"}}`；
 *   `failed` 见 `_app.py:545` `{"status":"failed","details":{"error":"invalid_level"}}`。
 * - `result.execution` / `result.details.execution`：执行适配名册（`adapter_not_connected`）。
 * - 顶层命令 `status` ∈ pending/leased/applied/needs_consent/conflict/failed/expired/unknown
 *   （`config_commands.py` `_STATUS_*`）；动作 `state` ∈ running/succeeded/failed/unknown/timed_out/cancelled。
 */
export function pendingReceipt(receipt: RunReceipt): string {
  const result = receipt.result;
  if (result !== null && typeof result === 'object') {
    const record = result as Record<string, unknown>;
    const status = typeof record.status === 'string' ? record.status : '';
    if (status === 'degraded') return '执行降级，未完全生效；请核回执与执行适配状态';
    if (status === 'unavailable') return '执行源不可用，未生效；请稍后重试或查适配';
    if (status === 'unknown') return '执行结果未知；勿盲目重复提交';
    // 🔴 handler 的最终判定 `failed` 优先于顶层 `state`：`state=succeeded` 只说明运行
    // 生命周期走完，不代表动作生效。文案与顶层 `failed` 同词条（`RECEIPT_LABELS.failed`）。
    if (status === 'failed') return RECEIPT_LABELS.failed;
    const details = record.details;
    const nested = details !== null && typeof details === 'object' ? (details as Record<string, unknown>) : {};
    const execution = typeof record.execution === 'string' ? record.execution : typeof nested.execution === 'string' ? nested.execution : '';
    if (execution === 'adapter_not_connected') return '执行适配未连接；动作未生效，请先接适配';
  }
  const state = receipt.state ?? receipt.status ?? 'unknown';
  return RECEIPT_LABELS[state] ?? `执行状态：${state}`;
}

export interface PersonaItem { profile_id: string; display_name: string; is_main: boolean }
export interface PersonaState {
  active_override: string; effective: string; main: string;
  items: PersonaItem[]; apply: string; restart_required: boolean;
}

export const centerApi = {
  persona: () => apiRequest<PersonaState>('/api/v1/persona'),
  setPersona: (profileId: string, expectedCurrent: string) =>
    apiRequest<PersonaState>('/api/v1/persona/active', {
      method: 'POST',
      body: { profile_id: profileId, expected_current: expectedCurrent },
    }),
  catalog: () => apiRequest<{ items: ConfigRow[] }>('/api/v1/config/catalog'),
  config: () => apiRequest<{ items: ConfigRow[] }>('/api/v1/config'),
  preview: (key: string, value: unknown, version: number) => apiRequest<ConfigRow>(`/api/v1/config/${encodeURIComponent(key)}/preview`, { method: 'POST', body: { value, expected_version: version } }),
  set: (key: string, value: unknown, version: number) => apiRequest<RunReceipt>(`/api/v1/config/${encodeURIComponent(key)}/set`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID(), ...ownerConsentHeaders() }, body: { value, expected_version: version } }),
  reset: (key: string, version: number) => apiRequest<RunReceipt>(`/api/v1/config/${encodeURIComponent(key)}/reset`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID(), ...ownerConsentHeaders() }, body: { expected_version: version } }),
  resources: () => apiRequest<Resources>('/api/v1/metrics/resources'),
  models: () => apiRequest<ModelRows>('/api/v1/llm/models'),
  metrics: () => apiRequest<unknown>('/api/v1/metrics/models'),
  actions: () => apiRequest<{ items: ActionItem[] }>('/api/v1/actions'),
  runs: () => apiRequest<{ items: RunReceipt[] }>('/api/v1/actions/runs'),
  /** 单条执行记录详情（只读；`api/actions.py:37`）。cancel 是写面（write_dependency），本席不做。 */
  runDetail: (runId: string) => apiRequest<ActionRunDetail>(`/api/v1/actions/runs/${encodeURIComponent(runId)}`),
  /** /api/v1/llm/providers（信封裸数据；llm.py:71 只读；503 llm_control_unavailable＝服务未装配）。 */
  llmProviders: () => apiRequest<LLMProvidersData>('/api/v1/llm/providers'),
  /** /api/v1/llm/channels（信封裸数据；llm.py:82）。 */
  llmChannels: () => apiRequest<LLMChannelsData>('/api/v1/llm/channels'),
  /** /api/v1/llm/health（信封裸数据；llm.py:104）。 */
  llmHealth: () => apiRequest<LLMHealthData>('/api/v1/llm/health'),
  /** /api/v1/llm/routes（信封裸数据；llm.py:108）。 */
  llmRoutes: () => apiRequest<LLMRoutesData>('/api/v1/llm/routes'),
  /** /api/v1/metrics/overview（信封裸数据：resources 快照 + usage 语义包；v1.py:278）。 */
  metricsOverview: () => apiRequest<MetricsOverviewData>('/api/v1/metrics/overview'),
  /** /api/v1/metrics/sessions（信封裸数据：账本语义包；v1.py:286，limit≤100）。 */
  metricsSessions: (query: { limit?: number } = {}) =>
    apiRequest<MetricsUsage<MetricsSessionsData>>(`/api/v1/metrics/sessions${qs({ limit: query.limit ?? 100 })}`),
  /** /api/v1/metrics/trends（信封裸数据：账本语义包；v1.py:294，bucket∈hour|day，limit≤100）。 */
  metricsTrends: (query: { bucket?: 'hour' | 'day'; limit?: number } = {}) =>
    apiRequest<MetricsUsage<MetricsTrendsData>>(`/api/v1/metrics/trends${qs({ bucket: query.bucket ?? 'hour', limit: query.limit ?? 100 })}`),
  /** /api/v1/metrics/tokens（真身＝overview 语义包，**非** stats/tokens 的模型族表；v1.py:290）。 */
  metricsTokens: () => apiRequest<MetricsUsage<MetricsAggregate>>('/api/v1/metrics/tokens'),
  actionPreview: (id: string, version: number) => apiRequest<RunReceipt>(`/api/v1/actions/${encodeURIComponent(id)}/preview`, { method: 'POST', body: { parameters: {}, expected_version: version } }),
  execute: (id: string, version: number, token?: string) => apiRequest<RunReceipt>(`/api/v1/actions/${encodeURIComponent(id)}/execute`, { method: 'POST', body: { parameters: {}, expected_version: version, confirmation_token: token, idempotency_key: crypto.randomUUID() } }),
};
