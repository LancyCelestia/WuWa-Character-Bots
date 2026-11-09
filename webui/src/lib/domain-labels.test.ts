// 运行时领域词表：动作 ID / 通道状态 / 错误原文 / 渠道 / 模型 → 中文（W2 席）。
//
// 与 `humanize.ts` 的分工：那边是**配置键**词典（/config 页 807 个键），
// 这里是**运行时领域值**（控制面动作、channel_health、LLM 渠道与型号）。
// 两套语义不重叠，故意不复用同一张表——否则加个动作要动 1235 行的配置词典。
//
// 判据来自用户原话「所有英文变量名、英文参数名、英文枚举值，在界面上一律换成中文白话」，
// 落成可执行断言：每个中文出参的**首字符必须是 CJK**，英文只能出现在专有名词位（型号、渠道实名）。
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  UNKNOWN_PREFIX,
  actionLabel,
  breakerStateOf,
  channelLabel,
  errorLabel,
  modelLabel,
  statusLabel,
  vendorLabel,
} from './domain-labels.ts';

/** 首字符必须是中文——防「以后有人加了个英文词条」的铁律尺。 */
const CJK_START = /^[\u4e00-\u9fff]/;
const CJK = /[\u4e00-\u9fff]/;

// 代码实读清单：plugins/bot_unified_runtime/control_plane/_app.py 的 `action_ids`。
// 简报给的 13 条与此不符（只有 adapter.reconnect 重合），以代码为准。
const CODE_ACTION_IDS = [
  'runtime.reload',
  'runtime.safe_restart',
  'adapter.reconnect',
  'snowluma.status',
  'queue.pause',
  'queue.resume',
  'queue.drain',
  'logging.level',
  'resources.refresh',
  'llm.routes.reload',
  'knowledge.reindex',
  'memory.maintenance',
  'diagnostics.snapshot',
] as const;

// 简报那 13 条：代码里现在没有，但历史上/别处可能在用，同样给中文，不留英文裸奔。
const BRIEF_ACTION_IDS = [
  'adapter.reconnect',
  'adapter.reload',
  'adapter.disable',
  'adapter.enable',
  'bot.restart',
  'bot.stop',
  'bot.start',
  'config.reload',
  'config.apply',
  'cache.clear',
  'log.rotate',
  'probe.run',
  'health.check',
] as const;

const ALL_ACTION_IDS = [...new Set<string>([...CODE_ACTION_IDS, ...BRIEF_ACTION_IDS])];

// ─────────────────────────── ① 动作 ID ───────────────────────────

test('actionLabel：代码实读的 13 个动作 name 首字符都是中文', () => {
  for (const id of CODE_ACTION_IDS) {
    const { name } = actionLabel(id);
    assert.match(name, CJK_START, `${id} 的 name 不是中文开头：${name}`);
  }
});

test('actionLabel：简报那 13 个动作 name 首字符也都是中文（含 brief 独有条目）', () => {
  for (const id of BRIEF_ACTION_IDS) {
    const { name } = actionLabel(id);
    assert.match(name, CJK_START, `${id} 的 name 不是中文开头：${name}`);
  }
});

test('actionLabel：未登记动作回退到 UNKNOWN_PREFIX 开头，且不吞掉原 id', () => {
  const label = actionLabel('不存在的动作');
  assert.ok(label.name.startsWith(UNKNOWN_PREFIX), label.name);
  assert.ok(label.name.includes('不存在的动作'), '未知 id 要能被检索到');
  assert.match(label.hint, CJK);
});

test("actionLabel：adapter.reconnect 译成「重连适配器」（用户抱怨的 updeer.reconnect 真因）", () => {
  assert.equal(actionLabel('adapter.reconnect').name, '重连适配器');
});

test('actionLabel：全部动作的 hint 非空且含中文', () => {
  for (const id of ALL_ACTION_IDS) {
    const { hint } = actionLabel(id);
    assert.ok(hint.length > 0, `${id} 的 hint 为空`);
    assert.match(hint, CJK, `${id} 的 hint 没有中文：${hint}`);
  }
});

test('actionLabel：name 里不许出现裸动作 ID（英文点号标识符）', () => {
  for (const id of ALL_ACTION_IDS) {
    assert.equal(actionLabel(id).name.includes(id), false, `${id} 的 name 里还带着 id 原文`);
  }
});

// ─────────────────────────── ② 通道状态 ───────────────────────────

test('statusLabel：五态逐条对中文', () => {
  assert.equal(statusLabel('ok'), '正常');
  assert.equal(statusLabel('closed'), '正常');
  assert.equal(statusLabel('open'), '熔断中');
  assert.equal(statusLabel('half_open'), '恢复探测中');
  assert.equal(statusLabel('temporarily_unavailable'), '暂时不可用');
});

test('statusLabel：空值 → 未知；表外英文值不吞掉，落到未登记', () => {
  assert.equal(statusLabel(null), '未知');
  assert.equal(statusLabel(undefined), '未知');
  assert.equal(statusLabel(''), '未知');
  assert.ok(statusLabel('weird').startsWith('未登记'), statusLabel('weird'));
  assert.ok(statusLabel('weird').includes('weird'), '未登记状态要保留原值便于排查');
});

// ─────────────────────────── ③ 三态机（借用语义） ───────────────────────────

test('breakerStateOf：后端已有的三个真值直通', () => {
  assert.equal(breakerStateOf('ok'), 'closed');
  assert.equal(breakerStateOf('closed'), 'closed');
  assert.equal(breakerStateOf('open'), 'open');
  assert.equal(breakerStateOf('half_open'), 'half-open');
});

test('breakerStateOf：temporarily_unavailable + 未来冷却 → open（冷却中＝等效熔断）', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  const future = new Date(now + 60_000).toISOString();
  assert.equal(breakerStateOf('temporarily_unavailable', future, now), 'open');
});

test('breakerStateOf：temporarily_unavailable + 过去冷却 → half-open（冷却期满＝放行探测）', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  const past = new Date(now - 60_000).toISOString();
  assert.equal(breakerStateOf('temporarily_unavailable', past, now), 'half-open');
});

test('breakerStateOf：temporarily_unavailable 无冷却时间 → 保守判 open，不谎报健康', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  assert.equal(breakerStateOf('temporarily_unavailable', null, now), 'open');
  assert.equal(breakerStateOf('temporarily_unavailable', undefined, now), 'open');
  assert.equal(breakerStateOf('temporarily_unavailable', '', now), 'open');
});

test('breakerStateOf：冷却时间解析失败 → 保守判 open', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  assert.equal(breakerStateOf('temporarily_unavailable', '不是日期', now), 'open');
});

test('breakerStateOf：冷却正好到期边界（=== now）算期满，放行探测', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  assert.equal(breakerStateOf('temporarily_unavailable', new Date(now).toISOString(), now), 'half-open');
});

test('breakerStateOf：表外值 / 空值 → unknown', () => {
  assert.equal(breakerStateOf('weird'), 'unknown');
  assert.equal(breakerStateOf(null), 'unknown');
  assert.equal(breakerStateOf(undefined), 'unknown');
  assert.equal(breakerStateOf(''), 'unknown');
});

test('breakerStateOf：纯函数——同样入参跑两次同结果，且不改动入参', () => {
  const now = Date.parse('2026-01-01T00:00:00.000Z');
  const cooldown = new Date(now + 1000).toISOString();
  const first = breakerStateOf('temporarily_unavailable', cooldown, now);
  const second = breakerStateOf('temporarily_unavailable', cooldown, now);
  assert.equal(first, second);
  assert.equal(cooldown, new Date(now + 1000).toISOString(), '入参被改写了');
});

// ─────────────────────────── ④ 错误归类（顺序是硬性要求） ───────────────────────────

test('errorLabel：ConnectTimeout 判「连接超时」而不是「无法连接」——connecttimeout 必须排在 connect 之前', () => {
  const raw = 'ConnectTimeout: _ssl.c:993: The handshake operation timed out';
  const out = errorLabel(raw);
  assert.equal(out.kind, '连接超时');
  assert.equal(out.detail, raw, 'detail 必须是完整原文，排查全靠它');
});

test('errorLabel：404 model not found → 模型不存在', () => {
  assert.equal(errorLabel("HTTP 404: model 'qwen3.5:9b' not found").kind, '模型不存在');
});

test('errorLabel：kind=timeout → 连接超时', () => {
  assert.equal(errorLabel('kind=timeout').kind, '连接超时');
});

test('errorLabel：其它归类逐条落地', () => {
  assert.equal(errorLabel('HTTP 401 Unauthorized').kind, '凭据无效');
  assert.equal(errorLabel('invalid api key provided').kind, '凭据无效');
  assert.equal(errorLabel('HTTP 403 Forbidden').kind, '权限不足');
  assert.equal(errorLabel('HTTP 429 Too Many Requests').kind, '触发限流');
  assert.equal(errorLabel('HTTP 503 Service Unavailable at upstream').kind, '暂时不可用');
  assert.equal(errorLabel('certificate verify failed').kind, '证书错误');
  assert.equal(errorLabel('connect ECONNREFUSED 127.0.0.1:11434').kind, '无法连接');
});

test('errorLabel：500/502/504 归「上游服务错误」（不被 503 的 unavailable 抢走）', () => {
  assert.equal(errorLabel('HTTP 500 Internal Server Error').kind, '上游服务错误');
  assert.equal(errorLabel('HTTP 502 Bad Gateway').kind, '上游服务错误');
  assert.equal(errorLabel('HTTP 504 Gateway Timeout').kind, '连接超时');
});

test('errorLabel：空值 → detail 为空串，kind 首字符是中文', () => {
  for (const empty of [null, undefined, '']) {
    const out = errorLabel(empty);
    assert.equal(out.detail, '');
    assert.match(out.kind, CJK_START, `空值 kind 不是中文开头：${out.kind}`);
  }
});

test('errorLabel：无法归类的原文也绝不丢，detail 原样保留', () => {
  const raw = 'some brand new failure XYZ-123';
  const out = errorLabel(raw);
  assert.equal(out.detail, raw);
  assert.match(out.kind, CJK_START);
});

// ─────────────────────────── ⑤ 渠道 ───────────────────────────

test('channelLabel：gateway_channel 已是中文实名 → 原样返回', () => {
  assert.equal(channelLabel('axon-gemini-38-flash', '恒星纪元 - Gemini'), '恒星纪元 - Gemini');
  assert.equal(channelLabel(null, '浅夜の梦 - 专属号池'), '浅夜の梦 - 专属号池');
});

test('channelLabel：无 gateway_channel 时按 provider_id 规则化，保留型号可检索', () => {
  const out = channelLabel('axon-gemini-38-flash');
  assert.ok(out.includes('AxonHub'), out);
  assert.ok(out.includes('gemini'), '型号被翻译掉就搜不到了');
  assert.equal(out.includes('-'), false, '剩余部分的连字符要换成空格');
});

test('channelLabel：provider_id 前缀规则逐条落地', () => {
  assert.ok(channelLabel('qian-night-grok').includes('浅夜号池'));
  assert.ok(channelLabel('aiprc-gpt-5').includes('AI 价格池'));
  assert.ok(channelLabel('potccv-claude').includes('PotCCV'));
  assert.ok(channelLabel('ollama-qwen2.5').includes('Ollama'));
});

test('channelLabel：表外前缀 → 未登记渠道 + 原值', () => {
  const out = channelLabel('mystery-provider');
  assert.ok(out.startsWith('未登记渠道'), out);
  assert.ok(out.includes('mystery-provider'), '未登记要保留原值便于排查');
});

test('channelLabel：两者都空 → 「未登记渠道」；gateway_channel 纯空白按空处理', () => {
  assert.equal(channelLabel(null), '未登记渠道');
  assert.equal(channelLabel(undefined), '未登记渠道');
  assert.equal(channelLabel(''), '未登记渠道');
  assert.equal(channelLabel(null, '  '), '未登记渠道');
  assert.equal(channelLabel(null, ''), '未登记渠道');
});

test('channelLabel：gateway_channel 两侧空白 trim 后返回，不留尾随空格', () => {
  assert.equal(channelLabel(null, '  恒星纪元 - Gemini  '), '恒星纪元 - Gemini');
});

// ─────────────────────────── ⑥ 厂商 / 模型 ───────────────────────────

test('vendorLabel：厂商判定的顺序（gpt/luna 同一家、ollama 在最后）', () => {
  assert.equal(vendorLabel('gemini-3.8-flash'), '谷歌');
  assert.equal(vendorLabel('grok-4'), 'xAI');
  assert.equal(vendorLabel('gpt-5'), 'OpenAI');
  assert.equal(vendorLabel('luna-pro'), 'OpenAI');
  assert.equal(vendorLabel('deepseek-v4'), '深度求索');
  assert.equal(vendorLabel('qwen3.5:9b'), '阿里通义');
  assert.equal(vendorLabel('claude-sonnet-4'), 'Anthropic');
  assert.equal(vendorLabel('llama-4'), 'Meta');
  assert.equal(vendorLabel('ollama-qwen2.5'), '阿里通义');
  assert.equal(vendorLabel('nope'), '未登记厂商');
  assert.equal(vendorLabel(null), '未登记厂商');
  assert.equal(vendorLabel(''), '未登记厂商');
});

test('vendorLabel：大小写不敏感', () => {
  assert.equal(vendorLabel('GEMINI-3.8-FLASH'), '谷歌');
  assert.equal(vendorLabel('Qwen3.5'), '阿里通义');
});

test('modelLabel：厂商中文名 + 原型号，两者都在', () => {
  const out = modelLabel('gemini-3.8-flash');
  assert.ok(out.includes('谷歌'), out);
  assert.ok(out.includes('gemini-3.8-flash'), '原型号必须保留，否则不可检索');
});

test('modelLabel：空值 → 未登记模型', () => {
  assert.equal(modelLabel(null), '未登记模型');
  assert.equal(modelLabel(undefined), '未登记模型');
  assert.equal(modelLabel(''), '未登记模型');
});

// ─────────────────────────── ⑦ 中文首字符铁律（总闸） ───────────────────────────

test('铁律：13 条动作 name + 5 条状态 + 10 条错误 kind + 2 条厂商兜底，首字符全部是 CJK', () => {
  const values: string[] = [
    ...CODE_ACTION_IDS.map((id) => actionLabel(id).name),
    ...BRIEF_ACTION_IDS.map((id) => actionLabel(id).name),
    ...['ok', 'temporarily_unavailable', 'closed', 'open', 'half_open'].map((s) => statusLabel(s)),
    ...[
      'ConnectTimeout: handshake timed out',
      'HTTP 401 Unauthorized',
      'HTTP 403 Forbidden',
      'HTTP 404 not found',
      'HTTP 429 rate limit',
      'HTTP 500 server error',
      'certificate verify failed',
      'connect ECONNREFUSED',
      'temporarily unavailable',
      'brand new failure',
    ].map((raw) => errorLabel(raw).kind),
    vendorLabel('nope'),
    vendorLabel(null),
  ];
  for (const value of values) {
    assert.match(value, CJK_START, `不是中文开头：${value}`);
  }
  assert.ok(values.length > 0);
});
