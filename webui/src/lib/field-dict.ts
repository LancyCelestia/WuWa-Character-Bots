// 数据字典唯一真身（W15 席 W1）。
//
// 全站 35 条指标的名称、单位、来源列、可得性——只此一份。页面/图表/导出都从这里取，
// 不得再手抄文案。
//
// 本字典最要紧的事是 `availability`：**「库里没有」和「值是 0」必须能分开**。
// 生产库实测（只读，2026-10-19 快照）：
//   - `llm_call_records.first_token_latency_ms` 3397 行全为 NULL ⇒ 首 Token 延迟判 absent；
//   - `status='success' AND error_kind<>''` = 0 行 ⇒ 账本里没有「成功却带错误」的矛盾行；
//   - 调用账本没有独立用户列，用户只能从 `session_id` 反推，可归属 1569 / 3397 行。
// 数字与口径写在各自的 `detail` 里，改字典即改口径，请同步核实库再动。
//
// 纪律：零运行时依赖（只 `import type` 语义上是纯数据），无 enum/参数属性，故 `node --test` 直跑。

/** 时间粒度：五档 + 累计。 */
export type Grain = 'daily' | 'weekly' | 'monthly' | 'yearly' | 'total';

/** 字段可得性——本模块诚实性的核心。 */
export type Availability =
  | 'measured' // 该列在库里真有非空数据，可直接读
  | 'derived' // 由已有列聚合/换算得出，口径写在 detail 里
  | 'absent'; // 库里结构性没有（含列存在但全为 NULL），UI 必须显式标注未采集

/** 业务模块归属。 */
export type FieldModule = 'affinity' | 'users' | 'calls' | 'latency' | 'channel';

export interface FieldDoc {
  /** 键值：契约字段名，全小写下划线。 */
  key: string;
  /** 自然语言键名：中文，不含英文单词。 */
  label: string;
  /** 简介：≤ 24 字，一句话说清这是什么。 */
  summary: string;
  /** 说明：口径、来源列、已知边界。10~160 字。 */
  detail: string;
  /** 单位（无量纲写空串）。 */
  unit: string;
  /** 业务模块。 */
  module: FieldModule;
  /** 数据来源，形如 'llm_call_records.duration_ms'。 */
  source: string;
  /** 可得性。 */
  availability: Availability;
  /** 有意义的粒度；不适用就空数组。 */
  grains: readonly Grain[];
}

/** 五档粒度全用（周/月/年等长窗一律全档）。 */
const ALL_GRAINS: readonly Grain[] = ['daily', 'weekly', 'monthly', 'yearly', 'total'];

/**
 * 好感度增量日志的历史边界。三个周期增量的 detail 都要点名它：
 * 只有 2 天历史 ⇒ 周及以上只有 1 个桶，是「不足以判断趋势」而非「零值」。
 */
const DELTA_SPAN = 'affinity_delta_log 当前只有 2.0 天历史（2026-10-18 起），周及以上粒度目前只有 1 个桶，属「数据不足以判断趋势」而非零值。';

/** 用户归属边界：账本无用户列，只能从 session_id 反推，故一切按用户切的指标都是下限。 */
const ATTRIBUTION = 'llm_call_records 无独立用户列，用户从 session_id 反推（纯数字=QQ 号，group_<群号>_<QQ号>=群会话）。实测 3397 行中可归属 1569 行（46.2%），其余 1828 行为空。所以这些数字是下限，不是全量。';

/** 首 Token / Token 间隔三兄弟的共同边界：列在但全 NULL，根因是链路非流式。 */
const NO_STREAM = '该列存在但 3397 行全为 NULL；原因是本机器人的大模型调用链路未启用流式传输（全仓无 stream=True），首 Token 与增量间隔在客户端无从测得。要采集必须先改造调用层为流式，属独立工程，不在本面板范围。';

/** 全量字典（唯一真身）。 */
export const FIELD_DICT: readonly FieldDoc[] = [
  // ── 好感度 ────────────────────────────────────────────────
  {
    key: 'affinity_delta_daily',
    label: '每日好感度增量',
    summary: '当日新增好感度净值',
    detail: `当日好感度增量的净值（正向减负向）。applied_at 为 unix 秒浮点，按自然日切桶求和。${DELTA_SPAN}`,
    unit: '分',
    module: 'affinity',
    source: 'affinity_delta_log.delta 按自然日聚合',
    availability: 'derived',
    grains: ['daily'],
  },
  {
    key: 'affinity_delta_weekly',
    label: '每周好感度增量',
    summary: '本周新增好感度净值',
    detail: `本周好感度增量的净值。按 ISO 周切桶求和。${DELTA_SPAN}`,
    unit: '分',
    module: 'affinity',
    source: 'affinity_delta_log.delta 按 ISO 周聚合',
    availability: 'derived',
    grains: ['weekly'],
  },
  {
    key: 'affinity_delta_monthly',
    label: '每月好感度增量',
    summary: '本月新增好感度净值',
    detail: `本月好感度增量的净值。按自然月切桶求和。${DELTA_SPAN}`,
    unit: '分',
    module: 'affinity',
    source: 'affinity_delta_log.delta 按自然月聚合',
    availability: 'derived',
    grains: ['monthly'],
  },
  {
    key: 'affinity_delta_yearly',
    label: '每年好感度增量',
    summary: '本年新增好感度净值',
    detail: `本年好感度增量的净值。按自然年切桶求和。${DELTA_SPAN}`,
    unit: '分',
    module: 'affinity',
    source: 'affinity_delta_log.delta 按自然年聚合',
    availability: 'derived',
    grains: ['yearly'],
  },
  {
    key: 'affinity_total',
    label: '累计总好感度',
    summary: '自统计开启以来的好感度累计值',
    detail: 'user_affinity.affinity 求和。实测 562 行合计 117.229，均值 0.209，最大 0.763；单用户数值随互动累积，不回溯改写。',
    unit: '分',
    module: 'affinity',
    source: 'user_affinity.affinity 求和',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'affinity_change_rate',
    label: '好感度变化率',
    summary: '当前窗口相对上一窗口的百分比变化',
    detail: '由相邻两窗口的增量相除得出。上一窗口为 0 时不给百分比，标注无可比基数，避免除零得出无穷大。',
    unit: '%',
    module: 'affinity',
    source: '由相邻两窗口增量算出',
    availability: 'derived',
    grains: ['daily', 'weekly', 'monthly', 'yearly'],
  },
  {
    key: 'interaction_count',
    label: '互动次数',
    summary: '该用户与机器人累计互动轮次',
    detail: 'user_affinity.interaction_count 可直接读，按用户累计，不随时间窗变化；跨会话累计。',
    unit: '次',
    module: 'affinity',
    source: 'user_affinity.interaction_count',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'positive_count',
    label: '正向信号数',
    summary: '累计正向互动次数',
    detail: 'user_affinity.positive_count 可直接读，是判定正向信号的计数器，与互动次数同源同期累计。',
    unit: '次',
    module: 'affinity',
    source: 'user_affinity.positive_count',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'negative_count',
    label: '负向信号数',
    summary: '累计负向互动次数',
    detail: 'user_affinity.negative_count 可直接读。与正向信号同口径计数，净值即两者之差。',
    unit: '次',
    module: 'affinity',
    source: 'user_affinity.negative_count',
    availability: 'measured',
    grains: ['total'],
  },

  // ── 用户 ─────────────────────────────────────────────────
  {
    key: 'active_users',
    label: '活跃用户数',
    summary: '窗口内至少发起过一次调用的去重用户数',
    detail: ATTRIBUTION,
    unit: '人',
    module: 'users',
    source: 'llm_call_records.session_id 去重',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'new_users',
    label: '新增用户数',
    summary: '首次发起调用的用户数',
    detail: ATTRIBUTION,
    unit: '人',
    module: 'users',
    source: 'llm_call_records.session_id 去重后取首次出现',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'returning_users',
    label: '回访用户数',
    summary: '窗口前已有调用、窗口内再次调用的用户数',
    detail: ATTRIBUTION,
    unit: '人',
    module: 'users',
    source: 'llm_call_records.session_id 去重后比对窗口前记录',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'calls_per_active_user',
    label: '人均调用次数',
    summary: '活跃用户平均发起的调用次数',
    detail: ATTRIBUTION,
    unit: '次/人',
    module: 'users',
    source: '调用行数 ÷ 活跃用户数',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'top_decile_request_share',
    label: 'Top 10% 请求集中度',
    summary: '请求量最高的 10% 用户贡献的请求占比',
    detail: '按 session_id 分组计数后取头部十分之一求和再除总量。分母只含可归属行，比例偏高，属结构性偏差。',
    unit: '%',
    module: 'users',
    source: '按 session_id 分组计数取头部',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'user_attribution_coverage',
    label: '用户归属覆盖率',
    summary: '能反查出用户的调用占总调用的比例',
    detail: 'session_id 可解析行数 ÷ 总行数。实测 1569 / 3397 = 46.2%。该值决定上面几个用户指标的可信上限。',
    unit: '%',
    module: 'users',
    source: 'llm_call_records.session_id 可解析行数 ÷ 总行数',
    availability: 'derived',
    grains: ['total'],
  },

  // ── 调用 ─────────────────────────────────────────────────
  {
    key: 'requests_total',
    label: '总请求数',
    summary: '窗口内网关收到的调用请求总数',
    detail: 'llm_call_records 行数。全库实测 3397 行，时间跨度 2026-09-25 至 2026-10-19。',
    unit: '次',
    module: 'calls',
    source: 'llm_call_records 行数',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'request_success_rate',
    label: '请求成功率',
    summary: '业务成功的请求占比',
    detail: 'status 为 success 的行数 ÷ 总行数。status 是闭集字段，未知取值不计入成功，故不会虚高。',
    unit: '%',
    module: 'calls',
    source: 'llm_call_records.status',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'error_rate',
    label: '错误率',
    summary: '服务端错误占请求总数的比例',
    detail: "按 status 判失败并以 error_kind 归类。实测 status='success' AND error_kind<>'' = 0 行：账本里没有「成功却带错误」的矛盾行。",
    unit: '%',
    module: 'calls',
    source: 'llm_call_records.status 与 error_kind',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'qps',
    label: '每秒请求数',
    summary: '每秒请求数',
    detail: '窗口请求数 ÷ 窗口秒数。按整窗平均，不反映瞬时峰值；窗口越短越接近真实并发。',
    unit: '次/秒',
    module: 'calls',
    source: '窗口请求数 ÷ 窗口秒数',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'prompt_tokens_total',
    label: '输入 Token 总量',
    summary: '窗口内所有请求的提示 Token 累计数',
    detail: 'llm_call_records.prompt_tokens 求和。含系统提示与人设注入部分，不代表用户实际输入长度。',
    unit: 'Token',
    module: 'calls',
    source: 'llm_call_records.prompt_tokens',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'completion_tokens_total',
    label: '输出 Token 总量',
    summary: '窗口内所有请求的生成 Token 累计数',
    detail: 'llm_call_records.completion_tokens 求和。与输入 Token 合计即 total_tokens，供成本与吞吐复用。',
    unit: 'Token',
    module: 'calls',
    source: 'llm_call_records.completion_tokens',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'tokens_per_active_user_median',
    label: '每用户 Token 中位数',
    summary: '活跃用户人均消耗 Token 的中位数',
    detail: 'total_tokens 按 session_id 分组求和后取中位数。中位数抗头部用户拉高；空 session 行不计入，故样本少于总行数。',
    unit: 'Token/人',
    module: 'calls',
    source: 'total_tokens 按 session_id 分组取中位',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'token_throughput',
    label: 'Token 吞吐速率',
    summary: '每秒处理的输入加输出 Token 数',
    detail: 'total_tokens 求和 ÷ 窗口秒数。是整窗平均吞吐，非流式实时速率，短窗下才有参考价值。',
    unit: 'Token/秒',
    module: 'calls',
    source: 'total_tokens 求和 ÷ 窗口秒数',
    availability: 'derived',
    grains: ALL_GRAINS,
  },
  {
    key: 'total_cost',
    label: '累计费用',
    summary: '窗口内全部调用折算的金额',
    detail: 'total_cost_micro ÷ 1e6。全库合计 7,113,530，即 ¥7.1135；currency 全部 CNY；unpriced=0（3397 行全部有价）。',
    unit: '元',
    module: 'calls',
    source: 'llm_call_records.total_cost_micro ÷ 1e6',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'unpriced_calls',
    label: '未定价调用数',
    summary: '缺少单价的调用数',
    detail: 'llm_call_records.unpriced 求和。实测为 0：3397 行全部有价，费用字段没有漏算的空白调用。',
    unit: '次',
    module: 'calls',
    source: 'llm_call_records.unpriced',
    availability: 'measured',
    grains: ALL_GRAINS,
  },

  // ── 延迟 ─────────────────────────────────────────────────
  {
    key: 'e2e_latency_p99',
    label: '端到端延迟 P99',
    summary: '从请求发出到返回的 P99 耗时',
    detail: 'duration_ms 的第 99 百分位。实测 P99 = 60077 毫秒（n=3397，无 NULL）；尾部含重试与排队等待。',
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.duration_ms',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'e2e_latency_p90',
    label: '端到端延迟 P90',
    summary: '端到端延迟的第 90 百分位',
    detail: 'duration_ms 的第 90 百分位。实测 P90 = 17360 毫秒（n=3397，无 NULL）；较中位数高出约 2.6 倍。',
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.duration_ms',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'e2e_latency_p50',
    label: '端到端延迟 P50',
    summary: '端到端延迟的中位数',
    detail: 'duration_ms 的中位数。实测 P50 = 6733 毫秒（n=3397，无 NULL）；一半请求在此以内完成。',
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.duration_ms',
    availability: 'measured',
    grains: ALL_GRAINS,
  },
  {
    key: 'ttft_p99',
    label: '首 Token 延迟 P99',
    summary: '首 Token 延迟的第 99 百分位',
    detail: NO_STREAM,
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.first_token_latency_ms（全 NULL）',
    availability: 'absent',
    grains: ALL_GRAINS,
  },
  {
    key: 'ttft_p50',
    label: '首 Token 延迟 P50',
    summary: '首 Token 延迟的中位数',
    detail: NO_STREAM,
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.first_token_latency_ms（全 NULL）',
    availability: 'absent',
    grains: ALL_GRAINS,
  },
  {
    key: 'inter_token_latency_p99',
    label: 'Token 间延迟 P99',
    summary: '相邻输出 Token 之间的间隔 P99',
    detail: `账本无逐 Token 时间戳列，相邻输出 Token 的间隔无从推算。${NO_STREAM}`,
    unit: '毫秒',
    module: 'latency',
    source: '无此列',
    availability: 'absent',
    grains: ALL_GRAINS,
  },
  {
    key: 'gateway_latency',
    label: '网关延迟',
    summary: '网关自身处理耗时',
    detail: 'gateway_latency_ms 是网关侧处理耗时，不含上游生成。3104 / 3397 行非空，空白段应跳过而非按 0 算。',
    unit: '毫秒',
    module: 'latency',
    source: 'llm_call_records.gateway_latency_ms',
    availability: 'measured',
    grains: ALL_GRAINS,
  },

  // ── 通道 ─────────────────────────────────────────────────
  {
    key: 'channel_state',
    label: '通道健康状态',
    summary: '通道当前所处的健康状态',
    detail: '当前库只有 ok (17) 与 temporarily_unavailable (66) 两态，没有半开态。三态（关闭 / 熔断 / 恢复探测）需后端新增独立探测状态机，属待建能力。',
    unit: '',
    module: 'channel',
    source: 'channel_health.state',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'consecutive_fails',
    label: '连续失败次数',
    summary: '连续失败累计，达 2 次判暂不可用',
    detail: 'channel_health.consecutive_fails 可直接读。成功一次即清零，故它是当前连败长度，不是累计历史失败数。',
    unit: '次',
    module: 'channel',
    source: 'channel_health.consecutive_fails',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'last_probe_at',
    label: '最近探测时间',
    summary: '上一次健康探测的时间',
    detail: 'channel_health.last_probe_at 可直接读。写入格式为本地时区串，跨时区比对前须先归一。',
    unit: '',
    module: 'channel',
    source: 'channel_health.last_probe_at',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'last_ok_at',
    label: '最近成功时间',
    summary: '上一次探测成功的时间',
    detail: 'channel_health.last_ok_at 可直接读。与最近探测时间一起看，可判断通道是多久没成功过。',
    unit: '',
    module: 'channel',
    source: 'channel_health.last_ok_at',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'ema_ms',
    label: '平滑延迟',
    summary: '指数加权平滑后的响应耗时',
    detail: 'channel_health.ema_ms 是探测用的平滑耗时，与账本 duration_ms 不同源，两者不应互相比对。',
    unit: '毫秒',
    module: 'channel',
    source: 'channel_health.ema_ms',
    availability: 'measured',
    grains: ['total'],
  },
  {
    key: 'channel_cooldown_until',
    label: '冷却截止时间',
    summary: '冷却期结束前该通道被排到候选队尾',
    detail: 'channel_health.cooldown_until 可直接读。为空的通道未处于冷却；非空且已过期视为冷却自然结束。',
    unit: '',
    module: 'channel',
    source: 'channel_health.cooldown_until',
    availability: 'measured',
    grains: ['total'],
  },
];

const BY_KEY = new Map<string, FieldDoc>(FIELD_DICT.map((doc) => [doc.key, doc]));

/** 按键值取一条；不认识返回 undefined。 */
export function fieldDoc(key: string): FieldDoc | undefined {
  return BY_KEY.get(key);
}

/** 按模块取（保持 FIELD_DICT 原序）。 */
export function fieldsByModule(module: FieldModule): readonly FieldDoc[] {
  return FIELD_DICT.filter((doc) => doc.module === module);
}

/** 渲染用四列行。 */
export interface FieldRow {
  label: string;
  key: string;
  summary: string;
  detail: string;
}

export function fieldRow(key: string): FieldRow | undefined {
  const doc = BY_KEY.get(key);
  if (!doc) return undefined;
  return { label: doc.label, key: doc.key, summary: doc.summary, detail: doc.detail };
}

/** 未采集字段清单（UI 用来在顶部挂「以下指标尚未采集」提示）。 */
export function absentFields(): readonly FieldDoc[] {
  return FIELD_DICT.filter((doc) => doc.availability === 'absent');
}
