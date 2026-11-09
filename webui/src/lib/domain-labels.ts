// 运行时领域词表：动作 ID / 通道状态 / 错误原文 / 渠道 / 模型 → 中文（W2 席）。
//
// 为什么不并进 `humanize.ts`：那边是**配置键**词典（`configTitleFor` / `fieldLabel` /
// `humanizeEnum`），服务 /config 页的 807 个配置键；这里是**运行时领域值**，覆盖控制面动作、
// channel_health 状态与错误、LLM 渠道与型号。两套语义不重叠，混在一起只会让那个 1235 行的
// 词典继续膨胀、职责错乱。这里只做纯映射，不 import 任何东西，也不碰任何 UI。

/** 兜底标记：无法翻译时返回值必须以它开头。 */
export const UNKNOWN_PREFIX = '未登记';

// ─────────────────────────── ① 动作 ID ───────────────────────────

/** 动作 ID → 中文名 + 一句话解释。 */
export interface ActionLabel {
  name: string;
  hint: string;
}

// 代码实读清单（plugins/bot_unified_runtime/control_plane/_app.py 的 `action_ids`，13 条）。
// 后端 `ControlActionDescriptor(action_id, action_id)` 的 label 直接等于 id，所以前端不加词表
// 就会露出 `adapter.reconnect` 这种原文——这正是用户抱怨「updeer.reconnect」的真因。
const CODE_ACTIONS: Record<string, ActionLabel> = {
  'runtime.reload': { name: '重载运行时', hint: '从磁盘重读运行时设置并重建生效面' },
  'runtime.safe_restart': { name: '安全重启运行时', hint: '先排空在飞任务再重启，避免丢消息' },
  'adapter.reconnect': { name: '重连适配器', hint: '断开后重新建立与聊天平台的连接' },
  'snowluma.status': { name: '查询连接状态', hint: '现查 SnowLuma 与 OneBot 三条腿的实时连通性' },
  'queue.pause': { name: '暂停发送队列', hint: '队列停止出队，已入队消息保留' },
  'queue.resume': { name: '恢复发送队列', hint: '队列继续出队，按原顺序发送' },
  'queue.drain': { name: '排空发送队列', hint: '把队列内待发消息全部发完再停' },
  'logging.level': { name: '调整日志级别', hint: '切换全局日志详细程度，立即生效' },
  'resources.refresh': { name: '刷新资源读数', hint: '重新采样 CPU、内存与磁盘占用' },
  'llm.routes.reload': { name: '重载模型路由', hint: '重读渠道与模型优先级表，不断路' },
  'knowledge.reindex': { name: '重建知识索引', hint: '重新切分并索引知识库，耗时较长' },
  'memory.maintenance': { name: '维护记忆库', hint: '清理过期记忆并压缩存储' },
  'diagnostics.snapshot': { name: '导出诊断快照', hint: '汇总控制面与运行时状态，便于排查' },
};

// 简报给出的另一组 13 条：代码里现在只剩 `adapter.reconnect` 重合，但历史上或别处可能在用。
// 留着不让它们退回英文裸奔；未出现也不妨碍——`actionLabel` 只按 id 查表。
const BRIEF_ACTIONS: Record<string, ActionLabel> = {
  'adapter.reconnect': CODE_ACTIONS['adapter.reconnect'],
  'adapter.reload': { name: '重载适配器', hint: '重新加载适配器配置，不断开连接' },
  'adapter.disable': { name: '停用适配器', hint: '该平台暂停收发，进程仍在' },
  'adapter.enable': { name: '启用适配器', hint: '恢复该平台的收发' },
  'bot.restart': { name: '重启机器人', hint: '结束当前进程并重新拉起' },
  'bot.stop': { name: '停止机器人', hint: '结束当前进程，不再自动拉起' },
  'bot.start': { name: '启动机器人', hint: '拉起已停止的进程' },
  'config.reload': { name: '重载配置', hint: '从磁盘重读配置，未保存的改动丢弃' },
  'config.apply': { name: '应用配置', hint: '把当前配置写入生效面' },
  'cache.clear': { name: '清理缓存', hint: '清空运行时缓存，下次访问重新计算' },
  'log.rotate': { name: '轮转日志', hint: '当前日志归档，新开一份' },
  'probe.run': { name: '执行探测', hint: '对所有通道各发一次最小真实调用' },
  'health.check': { name: '健康检查', hint: '汇总各子系统健康状态' },
};

const ACTIONS: Record<string, ActionLabel> = { ...BRIEF_ACTIONS, ...CODE_ACTIONS };

/** 动作 ID → 中文名 + 一句话解释。未登记的 id 回退成可检索的占位。 */
export function actionLabel(id: string): ActionLabel {
  const hit = ACTIONS[id];
  if (hit) return hit;
  return { name: `${UNKNOWN_PREFIX}动作：${id}`, hint: '该动作尚未登记中文名' };
}

// ─────────────────────────── ② 通道状态 ───────────────────────────

const STATUS: Record<string, string> = {
  ok: '正常',
  closed: '正常',
  open: '熔断中',
  half_open: '恢复探测中',
  temporarily_unavailable: '暂时不可用',
};

/** 通道健康状态 → 中文。 */
export function statusLabel(state: string | null | undefined): string {
  if (!state) return '未知';
  return STATUS[state] ?? `${UNKNOWN_PREFIX}状态：${state}`;
}

// ─────────────────────────── ③ 三态机（借用语义） ───────────────────────────

/** 通道健康状态 → 三态机语义。 */
export type BreakerState = 'closed' | 'open' | 'half-open' | 'unknown';

/**
 * 把 `temporarily_unavailable` 映射成 open/half-open 是**借用语义**。
 *
 * 后端 `channel_health.py` 当前只有**两态**（`ok` / `temporarily_unavailable`），且状态由业务
 * 失败驱动（`record_failure` 连续失败达阈值才标记，另有 `cooldown_until` 一档降级冷却）——
 * **真正意义上的三态熔断状态机尚未建成**。所以这里：
 *   - 「冷却中」（`cooldown_until > now`）读作熔断，
 *   - 「冷却期满」读作放行探测，
 * 是对现有两态的**如实近似**，不是假装后端已经有三态。哪天后端真上了三态，直接读 `state` 即可，
 * 这段借用逻辑就该删掉，而不是继续叠加。
 */
export function breakerStateOf(
  state: string | null | undefined,
  cooldownUntil?: string | null,
  now?: number,
): BreakerState {
  if (state === 'open') return 'open';
  if (state === 'half_open') return 'half-open';
  if (state === 'closed' || state === 'ok') return 'closed';
  if (state === 'temporarily_unavailable') {
    const until = cooldownUntil ? Date.parse(cooldownUntil) : Number.NaN;
    // 解析失败／缺失一律保守判熔断：宁可多探一次，也不谎报健康。
    if (Number.isNaN(until)) return 'open';
    return until > (now ?? Date.now()) ? 'open' : 'half-open';
  }
  return 'unknown';
}

// ─────────────────────────── ④ 错误归类 ───────────────────────────

/** 错误原文 → 中文归类 + 保留原文。 */
export interface ErrorLabel {
  kind: string;
  detail: string;
}

// 顺序是硬性要求，不是风格偏好：
//   - `connecttimeout` 必须在 `connect` 之前，否则 `ConnectTimeout` 会被判成「无法连接」；
//   - `timeout`（连接超时）必须在 `403`/`404` 之前的更早位置，才能抢在数字判据前面；
//   - `503 service unavailable` 里的 `unavailable` 要能落到「暂时不可用」。
// 每条 = [kind, 命中即返回的子串]。改动顺序请先看对应测试。
const ERROR_RULES: ReadonlyArray<readonly [string, readonly string[]]> = [
  ['连接超时', ['connecttimeout', 'handshake', 'timed out', 'timeout']],
  ['凭据无效', ['401', 'unauthorized', 'invalid api key']],
  ['权限不足', ['403', 'forbidden']],
  ['模型不存在', ['404', 'not found']],
  ['触发限流', ['429', 'rate limit', 'too many requests']],
  ['暂时不可用', ['unavailable', 'temporarily']],
  ['上游服务错误', ['500', '502', '503', '504', 'server error']],
  ['证书错误', ['ssl', 'certificate']],
  ['无法连接', ['connect', 'connection', 'refused', 'unreachable']],
];

/** 错误原文 → 中文归类 + 保留原文。`detail` 永不丢原文，排查全靠它。 */
export function errorLabel(raw: string | null | undefined): ErrorLabel {
  const detail = raw ?? '';
  const text = detail.toLowerCase();
  for (const [kind, needles] of ERROR_RULES) {
    if (needles.some((needle) => text.includes(needle))) return { kind, detail };
  }
  return { kind: `${UNKNOWN_PREFIX}原因`, detail };
}

// ─────────────────────────── ⑤ 渠道 ───────────────────────────

// 用户抱怨「渠道名显示原始变量名」的真因：前端显示的是 `provider_id` / `actual_model`，
// 而该显示的是 `gateway_channel`（已是中文实名）。所以优先用后者，前者只在缺的时候规则化。
const PROVIDER_PREFIXES: ReadonlyArray<readonly [string, string]> = [
  ['axon-', 'AxonHub 网关'],
  ['qian-night-', '浅夜号池'],
  ['aiprc-', 'AI 价格池'],
  ['potccv-', 'PotCCV 号池'],
  ['ollama-', '本地 Ollama'],
];

/** 通道显示名。优先 gateway_channel（已是中文实名），退回 provider_id 的规则化中文。 */
export function channelLabel(providerId: string | null | undefined, gatewayChannel?: string | null): string {
  const named = gatewayChannel?.trim();
  if (named) return named;

  const id = providerId?.trim();
  if (!id) return `${UNKNOWN_PREFIX}渠道`;

  for (const [prefix, label] of PROVIDER_PREFIXES) {
    if (id.startsWith(prefix)) {
      // 只把连字符换成空格，**不改大小写**——型号是专有名词，翻译成中文就失去可检索性。
      return `${label} / ${id.slice(prefix.length).replaceAll('-', ' ')}`;
    }
  }
  return `${UNKNOWN_PREFIX}渠道：${id}`;
}

// ─────────────────────────── ⑥ 厂商 / 模型 ───────────────────────────

// 顺序即优先级：`ollama-qwen2.5` 应判成阿里通义（`qwen` 先命中），只有裸 `ollama-` 才落到本地部署。
const VENDORS: ReadonlyArray<readonly [string, string]> = [
  ['gemini', '谷歌'],
  ['grok', 'xAI'],
  ['gpt', 'OpenAI'],
  ['luna', 'OpenAI'],
  ['deepseek', '深度求索'],
  ['qwen', '阿里通义'],
  ['claude', 'Anthropic'],
  ['llama', 'Meta'],
  ['ollama', '本地部署'],
];

/** 模型 ID → 厂商中文名。 */
export function vendorLabel(modelId: string | null | undefined): string {
  const text = modelId?.toLowerCase();
  if (!text) return `${UNKNOWN_PREFIX}厂商`;
  for (const [needle, vendor] of VENDORS) {
    if (text.includes(needle)) return vendor;
  }
  return `${UNKNOWN_PREFIX}厂商`;
}

/** 模型 ID → 中文显示名（厂商中文名 + 原型号，两者都在）。 */
export function modelLabel(modelId: string | null | undefined): string {
  if (!modelId) return `${UNKNOWN_PREFIX}模型`;
  return `${vendorLabel(modelId)} / ${modelId}`;
}
