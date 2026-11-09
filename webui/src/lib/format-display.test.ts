// ============================================================================
// 展示格式化公共层的行为锁（W13-M 席，TDD：本文件先红后绿）
//
// 锁四种口径，全站唯一真值都落在 `format.ts`：
//   ① 数字三档单位（compact 1.2K / chinese 1.2万 / plain 1200），默认档由外观
//      「语言与格式」的 unitSystem 决定（接缝 setDefaultNumberFormat）；
//   ② token/计数明细：**3 位分隔**（千分位），全站不许出现 4 位分隔或裸数字；
//   ③ 时间/速率：时长单位写全（天/小时/分/秒）、速率必须带「次/单位」；
//   ④ 日期：年月日 + 时分秒；带偏移的 ISO **按字面量**取，不转本地时区。
//
// 时区纪律：本文件**不**依赖宿主时区——所有精确断言走 `formatIsoDateTime`
// （字面量口径，与 `formatTimeLabel` 同一时区语义）；`formatDateTime` 走 Date
// → 本地时区，用「与本地 getter 逐字段等值」断言，换机器也不红。
// ============================================================================
import assert from 'node:assert/strict';
import { after, test } from 'node:test';

import {
  formatBucket,
  formatCount,
  formatDateTime,
  formatDecimal,
  formatDuration,
  formatInt,
  formatIsoDateTime,
  formatIsoTimestamp,
  formatMs,
  formatNumber,
  formatRate,
  formatTime,
  formatUnixSeconds,
  formatUptime,
  getDefaultNumberFormat,
  setDefaultNumberFormat,
  UNKNOWN_VALUE,
} from './format.ts';

const U = UNKNOWN_VALUE;

// ---------------------------------------------------------------------------
// ① 三档单位：逐档独立断言，档间互不借用
// ---------------------------------------------------------------------------
test('三档单位 compact：1K/1M 档位在 1000 / 1e6 处翻档，小数位裁零', () => {
  const o = { unitSystem: 'compact' } as const;
  assert.equal(formatNumber(0, o), '0');
  assert.equal(formatNumber(999, o), '999', '不足 1000 不缩写');
  assert.equal(formatNumber(1000, o), '1K');
  assert.equal(formatNumber(1200, o), '1.2K');
  assert.equal(formatNumber(9999, o), '10K', '9999/1000=9.999 → 10.0 裁零成 10K');
  assert.equal(formatNumber(10000, o), '10K');
  assert.equal(formatNumber(12345, o), '12.3K');
  assert.equal(formatNumber(999999, o), '1M', '999999 四舍五入成 1000K 时必须进位到 M，不许出 1000K');
  assert.equal(formatNumber(1_000_000, o), '1M');
  assert.equal(formatNumber(1_200_000, o), '1.2M');
  assert.equal(formatNumber(100_000_000, o), '100M');
});

test('三档单位 chinese：万在 1e4 翻档、亿在 1e8 翻档，万位以下仍走 3 位分隔', () => {
  const o = { unitSystem: 'chinese' } as const;
  assert.equal(formatNumber(0, o), '0');
  assert.equal(formatNumber(999, o), '999');
  assert.equal(formatNumber(1000, o), '1,000', '未到万：完整数字 + 3 位分隔');
  assert.equal(formatNumber(9999, o), '9,999');
  assert.equal(formatNumber(10000, o), '1万');
  assert.equal(formatNumber(12345, o), '1.2万');
  assert.equal(formatNumber(150_000, o), '15万');
  assert.equal(formatNumber(99_999_999, o), '1亿', '万位四舍五入成 10000万 时必须进位到亿');
  assert.equal(formatNumber(100_000_000, o), '1亿');
  assert.equal(formatNumber(250_000_000, o), '2.5亿');
});

test('三档单位 plain：完整数字，3 位分隔可关', () => {
  assert.equal(formatNumber(999, { unitSystem: 'plain' }), '999');
  assert.equal(formatNumber(1200, { unitSystem: 'plain' }), '1,200');
  assert.equal(formatNumber(10_000, { unitSystem: 'plain' }), '10,000');
  assert.equal(formatNumber(100_000_000, { unitSystem: 'plain' }), '100,000,000');
  assert.equal(formatNumber(1200, { unitSystem: 'plain', thousands: false }), '1200', '关掉分隔只影响 plain 档');
});

test('三档单位：负数走绝对值判档、负号在最前；各自保留本位分隔', () => {
  assert.equal(formatNumber(-1200, { unitSystem: 'compact' }), '-1.2K');
  assert.equal(formatNumber(-1200, { unitSystem: 'chinese' }), '-1,200');
  assert.equal(formatNumber(-1200, { unitSystem: 'plain' }), '-1,200');
  // 缩写档内部不再插分隔符：后缀（K/M/万/亿）已经承担量级，2500万 比 2,500万 更像中文读数。
  assert.equal(formatNumber(-25_000_000, { unitSystem: 'chinese' }), '-2500万');
});

test('三档单位：NaN/Infinity/null/undefined 一律未知符号，绝不渲染 NaN 或 0', () => {
  for (const unitSystem of ['compact', 'chinese', 'plain'] as const) {
    assert.equal(formatNumber(Number.NaN, { unitSystem }), U, `${unitSystem} NaN`);
    assert.equal(formatNumber(Number.POSITIVE_INFINITY, { unitSystem }), U, `${unitSystem} +Inf`);
    assert.equal(formatNumber(Number.NEGATIVE_INFINITY, { unitSystem }), U, `${unitSystem} -Inf`);
    assert.equal(formatNumber(null, { unitSystem }), U, `${unitSystem} null`);
    assert.equal(formatNumber(undefined, { unitSystem }), U, `${unitSystem} undefined`);
  }
});

test('小数位可调：decimals 0–3 只在缩写档生效，超档输入被夹紧', () => {
  assert.equal(formatNumber(12_345, { unitSystem: 'compact', decimals: 0 }), '12K');
  assert.equal(formatNumber(12_345, { unitSystem: 'compact', decimals: 2 }), '12.35K');
  assert.equal(formatNumber(12_345, { unitSystem: 'compact', decimals: 9 }), '12.345K', '上限 3 位');
  assert.equal(formatNumber(12_345, { unitSystem: 'chinese', decimals: 2 }), '1.23万');
  assert.equal(formatNumber(12_345, { unitSystem: 'plain', decimals: 2 }), '12,345', 'plain 不吃 decimals，不丢精度');
});

// ---------------------------------------------------------------------------
// ② 3 位分隔（M2 裁定）：全站唯一口径，连同 formatInt 这枚历史入口
// ---------------------------------------------------------------------------
test('M2：计数一律 3 位分隔（千分位），四位数起每组三位、绝不 4 位分组', () => {
  assert.equal(formatCount(999), '999');
  assert.equal(formatCount(1000), '1,000');
  assert.equal(formatCount(9999), '9,999');
  assert.equal(formatCount(12_345), '12,345', '四位分组会写成 1,2345 —— 必须不出现');
  assert.equal(formatCount(1_234_567), '1,234,567');
  assert.equal(formatCount(1_234_567_890_123), '1,234,567,890,123');
  assert.equal(formatCount(-1_234_567), '-1,234,567');
  assert.equal(formatCount(0), '0');
  assert.equal(formatCount(Number.NaN), U);
  assert.equal(formatCount(null), U);
});

test('M2：formatInt 是 formatCount 的同一实现（历史入口不得留第二套）', () => {
  for (const value of [0, 999, 1000, 12_345, 1_234_567, -98_765, null, Number.NaN]) {
    assert.equal(formatInt(value), formatCount(value), `formatInt/${String(value)}`);
  }
});

test('M2：formatCount 不受 unitSystem 影响（明细数字永远完整 + 3 位分隔）', () => {
  setDefaultNumberFormat({ unitSystem: 'compact' });
  assert.equal(formatCount(1_234_567), '1,234,567', '概览缩写档不得把明细计数也缩掉');
  setDefaultNumberFormat({ unitSystem: 'compact' });
});

// ---------------------------------------------------------------------------
// ③ 时间单位：时长写全到秒；速率必须带分母单位；延迟留 ms
// ---------------------------------------------------------------------------
test('时长把天/小时/分/秒写全，不丢秒，也不给裸数字', () => {
  assert.equal(formatDuration(0), '0秒');
  assert.equal(formatDuration(45), '45秒');
  assert.equal(formatDuration(90), '1分30秒');
  assert.equal(formatDuration(3725), '1小时2分5秒');
  assert.equal(formatDuration(90_061), '1天1小时1分1秒');
  assert.equal(formatDuration(86_400), '1天0小时0分0秒', '进位边界：整一天也要把时分秒写到');
  assert.equal(formatDuration(null), U);
  assert.equal(formatDuration(undefined), U);
  assert.equal(formatDuration(Number.NaN), U);
  assert.equal(formatDuration(-5), U, '负时长不可能存在，不许静默当 0');
});

test('formatUptime 与 formatDuration 同一实现（旧入口不另立一套）', () => {
  for (const seconds of [0, 59, 60, 3600, 90_061]) {
    assert.equal(formatUptime(seconds), formatDuration(seconds), `uptime/${seconds}`);
  }
});

test('延迟口径固定 ms：不足 1 秒给整数 ms，满 1 秒折成「秒」，绝不写成「每秒」', () => {
  assert.equal(formatMs(0), '0ms');
  assert.equal(formatMs(350), '350ms');
  assert.equal(formatMs(999), '999ms');
  assert.equal(formatMs(1500), '1.5秒');
  assert.equal(formatMs(12_000), '12秒');
  assert.equal(formatMs(null), U);
  assert.equal(formatMs(Number.NaN), U);
});

test('速率必须写明分母单位（次/小时、次/秒），不许只给裸比值', () => {
  assert.equal(formatRate(142.25, '次', '小时'), '142.3 次/小时');
  assert.equal(formatRate(0, '次', '秒'), '0 次/秒');
  assert.equal(formatRate(12, '次', '秒', { decimals: 0 }), '12 次/秒');
  assert.equal(formatRate(Number.NaN, '次', '秒'), U);
  assert.equal(formatRate(null, '次', '秒'), U);
});

test('小数（好感度分等）统一一位、符号由调用方给，NaN 未知', () => {
  assert.equal(formatDecimal(25), '25.0');
  assert.equal(formatDecimal(1.04), '1.0');
  assert.equal(formatDecimal(-3.26), '-3.3');
  assert.equal(formatDecimal(Number.NaN), U);
  assert.equal(formatDecimal(null), U);
});

// ---------------------------------------------------------------------------
// ④ 日期：年月日 + 时分秒；两条时区口径各自钉死
// ---------------------------------------------------------------------------
test('M4 字面量口径：带偏移的 ISO 按字面量取（不转本地时区，避免整体漂移）', () => {
  assert.equal(formatIsoDateTime('2026-10-18T14:00:00+08:00'), '2026年10月18日 14时00分00秒');
  assert.equal(formatIsoDateTime('2026-10-18T14:00:00Z'), '2026年10月18日 14时00分00秒', 'Z 也按字面量');
  assert.equal(formatIsoDateTime('2026-10-18 14:00:07.123+08:00'), '2026年10月18日 14时00分07秒', '毫秒截断不四舍五入');
  assert.equal(formatIsoDateTime('2026-10-18T14:00+08:00'), '2026年10月18日 14时00分00秒', '缺秒按 0 秒写全');
  assert.equal(formatIsoDateTime('2026-10-18'), '2026年10月18日', '只有日期就不编造时刻');
  assert.equal(formatIsoDateTime('坏时间'), '坏时间', '不可解析原样透出，不猜');
  assert.equal(formatIsoDateTime(''), '');
  assert.equal(formatIsoDateTime(null), '');
});

test('M4 ASCII 口径：同一把尺的短形，列值与日志原文可直接对照', () => {
  // 用户 2026-10-20 点名「最后消息时间需 YYYY-MM-DD HH:mm:ss」。这枚与上一条是**同一把尺的
  // 两种形态**：中文长形给正文，ASCII 短形给表格列（撑不宽列、可复制去 grep 日志）。
  // 时区语义必须完全一致——按字面量取，不换算。两条断言并排写，改任何一边就会看见另一边。
  assert.equal(formatIsoTimestamp('2026-10-18T14:00:00+08:00'), '2026-10-18 14:00:00');
  assert.equal(formatIsoTimestamp('2026-10-18T14:00:00Z'), '2026-10-18 14:00:00', 'Z 也按字面量');
  assert.equal(
    formatIsoTimestamp('2026-10-18 14:00:07.123+08:00'),
    '2026-10-18 14:00:07',
    '毫秒截断不四舍五入',
  );
  assert.equal(formatIsoTimestamp('2026-10-18T14:00+08:00'), '2026-10-18 14:00:00', '缺秒按 00 补全');
  assert.equal(formatIsoTimestamp('2026-10-18'), '2026-10-18', '只有日期就不编造时刻');
  assert.equal(formatIsoTimestamp('坏时间'), '坏时间', '不可解析原样透出，不猜');
  assert.equal(formatIsoTimestamp(''), '');
  assert.equal(formatIsoTimestamp(null), '');
  // 定宽：秒位恒两位，时段 0-9 时补零（否则列会随小时位移位）。
  assert.equal(formatIsoTimestamp('2026-01-02T03:04:05+08:00'), '2026-01-02 03:04:05');
});

test('M4 本地口径：formatDateTime = 年月日 + 时分秒，字段与本地 getter 逐枚等值', () => {
  const iso = '2026-01-31T14:05:09Z';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  const want = `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日 ${pad(d.getHours())}时${pad(d.getMinutes())}分${pad(d.getSeconds())}秒`;
  assert.equal(formatDateTime(iso), want);
  assert.match(formatDateTime(iso) as string, /^\d{4}年\d{2}月\d{2}日 \d{2}时\d{2}分\d{2}秒$/, '年月日时分秒一个都不许缺');
  assert.equal(formatDateTime(null), U);
  assert.equal(formatDateTime(undefined), U);
  assert.equal(formatDateTime(''), U);
  assert.equal(formatDateTime('2024-13-45T99:99:99Z'), '2024-13-45T99:99:99Z', '畸形文本原样透出');
});

test('M4：Unix 秒（后端 time.time() 浮点）也走同一日期口径', () => {
  const seconds = 1_769_000_000; // 2026-01-27T06:13:20Z
  const d = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  assert.equal(
    formatUnixSeconds(seconds),
    `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日 ${pad(d.getHours())}时${pad(d.getMinutes())}分${pad(d.getSeconds())}秒`
  );
  assert.equal(formatUnixSeconds(1_769_000_000.75), formatUnixSeconds(seconds), '浮点秒截断');
  assert.equal(formatUnixSeconds(null), U);
  assert.equal(formatUnixSeconds(Number.NaN), U);
});

test('时钟口径：时分秒三个字段齐全（冒号分隔，日志列宽不变）', () => {
  const iso = '2026-01-31T14:05:09Z';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  assert.equal(formatTime(iso), `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);
  assert.match(formatTime(iso) as string, /^\d{2}:\d{2}:\d{2}$/);
  assert.equal(formatTime(null), U);
  assert.equal(formatTime('not-a-date'), 'not-a-date');
});

test('坐标轴标签仍是短标签（轴不是正文，不许塞年月日时分秒）', () => {
  assert.match(formatBucket('2026-10-18T14:00:00+08:00', 'hour') as string, /^\d{2}:\d{2}$/);
  assert.match(formatBucket('2026-10-18T14:00:00+08:00', 'day') as string, /^\d{2}[/-]\d{2}$/, '沿用既有分隔符，不改语义');
  assert.equal(formatBucket('坏时间', 'day'), '坏时间');
});

// ---------------------------------------------------------------------------
// 默认档接缝：外观「语言与格式」unitSystem 是唯一真身
// ---------------------------------------------------------------------------
test('默认档接缝：setDefaultNumberFormat 改的是全站缺省，显式 options 永远优先', () => {
  const original = getDefaultNumberFormat();
  after(() => setDefaultNumberFormat(original));

  setDefaultNumberFormat({ unitSystem: 'chinese' });
  assert.equal(getDefaultNumberFormat().unitSystem, 'chinese');
  assert.equal(formatNumber(12_345), '1.2万', '不传 options = 走外观设置');
  assert.equal(formatNumber(12_345, { unitSystem: 'compact' }), '12.3K', '显式参数压过默认档');

  setDefaultNumberFormat({ unitSystem: 'compact' });
  assert.equal(formatNumber(12_345), '12.3K');

  setDefaultNumberFormat({ unitSystem: 'plain' });
  assert.equal(formatNumber(12_345), '12,345');

  setDefaultNumberFormat({ unitSystem: 'chinese' });
});
