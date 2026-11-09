// 界面文案的「英文 → 中文白话」唯一出口（F 席）。
//
// 判据全部来自用户原话：「所有英文变量名、英文参数名、英文枚举值，在界面上一律换成中文白话」。
// 这里把「换成中文白话」落成四条可执行断言：
//   ① 键名推导出的标题里不再有**小写英文标识符**（`aiprc` / `safetyexec` / `probe_urls` 一律不许出现）；
//   ② 枚举值（true/false、hour/day、compact/chinese/full…）出中文；
//   ③ 已经是中文的标题**不许被二次拼**（中文再拼一遍就是新的假中文）；
//   ④ 真·业务专名（Gemini / Tavily / 守岸人）不许硬编错译——保留原名，但中文主语必须在。
import test from 'node:test';
import assert from 'node:assert/strict';
import { configTitleFor, displayTitle, fieldLabel, humanizeEnum } from './humanize.ts';
import { CONFIG_FIELDS } from './config-presentation.ts';
import { GENERATED_FIELDS } from './config-presentation/catalog.ts';

const CJK = /[\u4e00-\u9fff]/;
const HAS_LATIN = /[A-Za-z]/;
/** 小写起头的英文串＝原始标识符残留（`aiprc`、`probe_urls`）。首字母大写的专名与被括住的单位不算。 */
const RAW_IDENTIFIER = /(^|[^A-Za-z])[a-z][A-Za-z0-9]*/;

// ─────────────────────────── ① 键名 → 标题 ───────────────────────────

test('configTitleFor：全词可译的键 → 标题里没有任何英文标识符', () => {
  const title = configTitleFor('BOT_CHAT_MEMORY_ENABLED');
  assert.equal(RAW_IDENTIFIER.test(title), false, `仍有英文标识符：${title}`);
  assert.equal(HAS_LATIN.test(title), false, `应为纯中文：${title}`);
  assert.ok(CJK.test(title));
});

test('configTitleFor：简报点名的 aiprc 键 → 译成「AI 优先级」而不是拼音假中文', () => {
  const title = configTitleFor('BOT_LLM_AIPRC_ENABLED');
  assert.ok(title.includes('优先级'), `没译出「优先级」：${title}`);
  assert.equal(RAW_IDENTIFIER.test(title), false, `仍有英文标识符：${title}`);
  assert.equal(title.includes('Aiprc'), false, `仍是机械拼词：${title}`);
});

test('configTitleFor：简报点名的 probe / urls / safetyexec → 探测 / 地址 / 安全执行', () => {
  const probe = configTitleFor('BOT_CREDENTIAL_PROBE_URLS');
  assert.ok(probe.includes('探测'), probe);
  assert.ok(probe.includes('地址'), probe);
  assert.equal(RAW_IDENTIFIER.test(probe), false, probe);

  const safety = configTitleFor('BOT_SAFETY_EXEC_ENABLED');
  assert.ok(safety.includes('安全'), safety);
  assert.ok(safety.includes('执行'), safety);
  assert.equal(HAS_LATIN.test(safety), false, safety);
});

test('configTitleFor：业务专名保留原名，但中文主语不得缺席（N2 形态而非硬编错词）', () => {
  const title = configTitleFor('BOT_SEARCH_TAVILY_SEARCH_DEPTH');
  assert.ok(title.includes('Tavily'), `专名不该被硬译：${title}`);
  assert.ok(CJK.test(title), title);
  assert.equal(RAW_IDENTIFIER.test(title), false, `专名之外不许有原始标识符：${title}`);
});

test('configTitleFor：数字段与缩写不被吞掉', () => {
  const title = configTitleFor('BOT_AFFINITY_V8_ENABLED');
  assert.ok(/v8|V8/.test(title), `版本号丢了：${title}`);
  assert.ok(title.includes('好感度'), title);
});

// ─────────────────────────── ② 枚举 → 中文 ───────────────────────────

test('humanizeEnum：布尔枚举 → 中文', () => {
  assert.equal(humanizeEnum(true), '开启');
  assert.equal(humanizeEnum(false), '关闭');
  assert.equal(humanizeEnum('true'), '开启');
  assert.equal(humanizeEnum('false'), '关闭');
});

test('humanizeEnum：简报点名的档位枚举 → 中文', () => {
  assert.equal(humanizeEnum('hour'), '小时');
  assert.equal(humanizeEnum('day'), '天');
  assert.equal(humanizeEnum('compact'), '简写');
  assert.equal(humanizeEnum('chinese'), '中文');
  assert.equal(humanizeEnum('full'), '完整');
});

test('humanizeEnum：状态枚举 → 中文（模型页渠道健康状态用同一张表）', () => {
  assert.equal(humanizeEnum('available'), '可用');
  assert.equal(humanizeEnum('unavailable'), '不可用');
  assert.equal(humanizeEnum('cooling'), '冷却中');
  assert.equal(humanizeEnum('unknown'), '未知');
});

test('humanizeEnum：已是中文的值原样返回，不二次拼', () => {
  assert.equal(humanizeEnum('已配置'), '已配置');
  assert.equal(humanizeEnum('未启用'), '未启用');
});

test('humanizeEnum：空值与对象不乱码，降级成可读文本', () => {
  assert.equal(humanizeEnum(null), '—');
  assert.equal(humanizeEnum(undefined), '—');
  assert.equal(humanizeEnum(0), '0');
  assert.equal(humanizeEnum(''), '—');
});

test('humanizeEnum：表外英文值不吞掉，保持可读（N3 降级）', () => {
  const out = humanizeEnum('quuxmorphism');
  assert.equal(typeof out, 'string');
  assert.ok(out.length > 0);
  assert.ok(out.toLowerCase().includes('quuxmorphism'), `未知枚举不该被抹掉：${out}`);
});

// ─────────────────────────── ③ 中文不被破坏 ───────────────────────────

test('displayTitle：人写的中文标题原样保留（不许把中文再拼一遍）', () => {
  const curated = '好感度：亲密度衰减';
  assert.equal(displayTitle('BOT_AFFINITY_DECAY', curated, true), curated);
})

test('displayTitle：人写的「中文主语 + 技术术语」也原样保留', () => {
  const curated = '输入上下文上限（Token）';
  assert.equal(displayTitle('BOT_CHAT_MAX_INPUT_TOKENS', curated, true), curated);
});

test('displayTitle：没有英文的标题无论哪一档都不动', () => {
  assert.equal(displayTitle('BOT_X_Y', '纯中文标题', false), '纯中文标题');
});

test('displayTitle：T2/T3 的机械拼词标题按键重推', () => {
  const out = displayTitle('BOT_SAFETY_EXEC_ENABLED', 'Safetyexec·开关', false);
  assert.ok(out.includes('安全'), out);
  assert.equal(RAW_IDENTIFIER.test(out), false, out);
});

// ─────────────────────────── ④ 字段名 → 中文（模型页 / 布局编辑器） ───────────────────────────

test('fieldLabel：JSON 字段名译成中文，snake_case 不再直出', () => {
  for (const raw of ['model_id', 'context_window', 'priority_groups', 'health_state']) {
    const out = fieldLabel(raw);
    assert.ok(CJK.test(out), `${raw} → ${out} 没中文`);
    assert.equal(out.includes('_'), false, `${raw} → ${out} 仍有下划线`);
    assert.equal(RAW_IDENTIFIER.test(out), false, `${raw} → ${out} 仍有原始标识符`);
  }
});

test('fieldLabel：完全是中文的字段名原样返回', () => {
  assert.equal(fieldLabel('标题'), '标题');
});

// ─────────────────────────── ⑤ 真实目录的回归闸（前后数字就靠这几条） ───────────────────────────

/** 自动推导的两档（T2/T3）＝机器产物；T1 是人手写的，标题不改。 */
const GENERATED = CONFIG_FIELDS.filter((field) => field.tier !== 'T1');
/** 接线前的原始生成物：`键·Aiprc`、`Safetyexec·开关` 那一批。 */
const RAW_GENERATED = GENERATED_FIELDS.filter((field) => field.tier !== 'T1');

test('接线闸：原始生成标题里确实有机械英文（否则这条闸是空的）', () => {
  const raw = RAW_GENERATED.filter((field) => HAS_LATIN.test(field.title));
  assert.ok(raw.length > 0, '原始数据里应当有带英文的机械拼词标题');
});

test('接线闸：接线后的 T2/T3 标题里不许出现小写英文标识符', () => {
  const bad = GENERATED.filter((field) => RAW_IDENTIFIER.test(field.title));
  assert.deepEqual(bad.map((field) => `${field.key} → ${field.title}`).slice(0, 10), []);
});

test('接线闸：T2/T3 标题不许带下划线、不许等于键名本身', () => {
  const bad = GENERATED.filter(
    (field) => field.title.includes('_') || field.title.toUpperCase() === field.key.toUpperCase(),
  );
  assert.deepEqual(bad.map((field) => field.key).slice(0, 10), []);
});

test('接线闸：T2/T3 标题必须含中文（英文专名单独成题不算通过）', () => {
  const bad = GENERATED.filter((field) => !CJK.test(field.title));
  assert.deepEqual(bad.map((field) => field.key).slice(0, 10), []);
});

test('接线闸：人写的 T1 标题一个字都不动', () => {
  const changed = CONFIG_FIELDS.filter(
    (field) => field.tier === 'T1' && displayTitle(field.key, field.title, true) !== field.title,
  );
  assert.deepEqual(changed.map((field) => field.key).slice(0, 10), []);
});
