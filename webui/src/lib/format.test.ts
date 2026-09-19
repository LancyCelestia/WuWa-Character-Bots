// ============================================================================
// format.ts Intl 缓存 formatter 常驻等值锁（review-PERF1-fix1 I-2 整改）
//
// 被审物：formatTime/formatDateTime 的「模块级缓存 formatter（新）」与补丁前的
// 「每次现场构造 toLocale*（旧）」必须逐枚等值。此等值此前只有台账文字 +
// %TEMP% 一次性脚本作证（评审原话：等值今日真、证据明日腐），本文件升为仓内锁。
// 参照系（旧口径原文，git show 9f139b2:webui/src/lib/format.ts 逐字抄录）：
//   formatDateTime → date.toLocaleString('zh-CN', { hour12: false })
//   formatTime     → date.toLocaleTimeString('zh-CN', { hour12: false })
// 注意这**不是**「同一份 options 换个写法」的恒等式——新旧两侧 options 形态不同
// （显式字段 vs zh-CN 默认字段集），等值本身是经验命题，所以才值得锁。
//
// 样本口径（取舍见 docs/design/unify-audit-20260919/PERF1-fix2.md §三）：
//   确定性算术级数（无 PRNG、无 Math.random、离线、总耗时 ~2s）——
//   基础扫面 2022-01-01→2026-01-01 每 541 分钟一枚（541 为素数、与一日 1440 分钟
//   互质，分钟位在四年内遍历漂移）≈3886 枚/时区；凡相邻两枚 UTC 偏移变化（=跨越
//   DST 切换）即在两点之间以 11 分钟步长加密扫面——不硬编码任何切换日期，
//   Lord_Howe 的 30 分钟跳变与 Chatham 的 45 分钟基偏移都被该探针自动捕获；
//   另加 10 枚固定边界（epoch/负时刻/闰日/2038/2100/两枚 NY DST 瞬间）。
//   评审席的 155,942 枚 × 6 时区是全量一次性核验口径，**不常驻进 CI 路径**
//   （本文件按任务书要求秒级跑完）；等值面以「覆盖形态」而非「枚数」为准，
//   枚数下界由各条测试自带 checked 断言把守。
//
// 时区坑（评审 M-3，本席亲测）：缓存 formatter **构造期绑定系统时区**——设
// process.env.TZ 必须发生在 formatter 构造**之前**，否则 100% 假 DRIFT。本文件
// 的做法=每个时区口径先设 TZ、再带查询串重新求值 format.ts（绕开 ESM 模块缓存，
// 拿到以该时区构造的模块级 formatter 实例）；该性质本身另有锁（末条测试）。
//
// 自闭包纪律（任务书硬约束 5）：本文件只读 webui/ 以内的 ./format.ts，零后端依赖。
// ============================================================================
import assert from 'node:assert/strict';
import { after, test } from 'node:test';

const FORMAT_URL = new URL('./format.ts', import.meta.url);
const ORIGINAL_TZ = process.env.TZ;

/** 六枚时区口径：本机实居（无 DST 的生产面）+ 零偏移 + 两种 1 小时 DST 方向 + 30 分钟 DST + 45 分钟基偏移。 */
const ZONES = [
  'Asia/Singapore',
  'UTC',
  'America/New_York',
  'Europe/Berlin',
  'Australia/Lord_Howe',
  'Pacific/Chatham',
] as const;

type FormatModule = {
  UNKNOWN_VALUE: string;
  formatTime: (iso: string | null | undefined) => string;
  formatDateTime: (iso: string | null | undefined) => string;
};

/** 先设 TZ 后求值模块（M-3 坑的规避形态，见文件头注）。 */
async function loadFormat(tz: string): Promise<FormatModule> {
  process.env.TZ = tz;
  return import(`${FORMAT_URL.href}?tz=${encodeURIComponent(tz)}`) as Promise<FormatModule>;
}

// ---- 旧口径参照（逐字抄录自 9f139b2 的 format.ts return 表达式） ----------------
function refTime(d: Date): string {
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}
function refDateTime(d: Date): string {
  return d.toLocaleString('zh-CN', { hour12: false });
}

// ---- 确定性样本生成 --------------------------------------------------------------
const START = Date.UTC(2022, 0, 1);
const END = Date.UTC(2026, 0, 1);
const BASE_STEP_MS = 541 * 60_000; // 素数分钟步长，与 1440 互质
const FINE_STEP_MS = 11 * 60_000; // DST 邻域加密扫面步长
const BOUNDARIES = [
  0, // epoch
  -1,
  -86_400_000, // 负时刻（epoch 前一天）
  Date.UTC(1900, 0, 1),
  Date.UTC(2024, 1, 29, 23, 59, 59), // 闰日末尾
  Date.UTC(2038, 0, 19, 3, 14, 7), // 32 位溢出前一秒
  Date.UTC(2038, 0, 19, 3, 14, 8),
  Date.UTC(2100, 0, 1),
  Date.UTC(2024, 2, 10, 7, 0, 0), // NY 春令时切换瞬间（UTC 口径）
  Date.UTC(2024, 10, 3, 6, 0, 0), // NY 冬令时切换瞬间（UTC 口径）
];

/**
 * 单时区等值核验：基础扫面 + 偏移变化处加密扫面 + 边界枚。
 * 返回（time 与 dateTime 合计）比对枚数与前若干条失配样本。
 */
async function verifyZoneEquality(tz: string): Promise<{ checked: number; transitions: number; mismatches: string[] }> {
  const mod = await loadFormat(tz);
  let checked = 0;
  let transitions = 0;
  const mismatches: string[] = [];
  const cmp = (t: number): void => {
    const d = new Date(t);
    const iso = d.toISOString();
    checked += 2;
    const gotTime = mod.formatTime(iso);
    const wantTime = refTime(d);
    if (gotTime !== wantTime) mismatches.push(`${iso} time: got=${gotTime} want=${wantTime}`);
    const gotDt = mod.formatDateTime(iso);
    const wantDt = refDateTime(d);
    if (gotDt !== wantDt) mismatches.push(`${iso} datetime: got=${gotDt} want=${wantDt}`);
  };
  let prev: number | null = null;
  let prevOff: number | null = null;
  for (let t = START; t < END; t += BASE_STEP_MS) {
    const off = new Date(t).getTimezoneOffset();
    if (prevOff !== null && off !== prevOff) {
      transitions += 1;
      for (let x = prev! + FINE_STEP_MS; x < t; x += FINE_STEP_MS) cmp(x); // 切换邻域加密
    }
    prevOff = off;
    prev = t;
    cmp(t);
  }
  for (const t of BOUNDARIES) cmp(t);
  return { checked, transitions, mismatches };
}

after(() => {
  process.env.TZ = ORIGINAL_TZ; // 卫生：本文件跑完把宿主时区还回去（node --test 每文件独立进程，此为双保险）
});

// ---------------------------------------------------------------------------
// 逐时区等值（每枚样本 time+dateTime 双比对，mismatch 必须为 0）
// ---------------------------------------------------------------------------
for (const tz of ZONES) {
  test(`等值[${tz}]：缓存 formatter vs 旧现场构造口径逐枚全等（含 DST 邻域加密+边界枚）`, async () => {
    const { checked, transitions, mismatches } = await verifyZoneEquality(tz);
    assert.ok(checked >= 7_600, `${tz} 比对面不足：仅 ${checked} 枚`);
    assert.ok(mismatches.length === 0, `${tz} 出现 ${mismatches.length} 枚失配，前 5 枚：\n${mismatches.slice(0, 5).join('\n')}`);
    // DST 覆盖自检：四个含 DST 时区四年应有 8 次切换被加密扫面捕获；无 DST 时区为 0。
    const expectedTransitions = tz === 'America/New_York' || tz === 'Europe/Berlin' || tz === 'Australia/Lord_Howe' || tz === 'Pacific/Chatham' ? 8 : 0;
    assert.equal(transitions, expectedTransitions, `${tz} 偏移变化探针捕获数异常（样本面或时区装载失效）`);
  });
}

// ---------------------------------------------------------------------------
// 阴性对照：比对器必须有牙（评审方法照抄——「缺 second」变体必须全红）
// ---------------------------------------------------------------------------
test('阴性对照：缺 second 的近似实现必须被同一比对器全量抓获（比对器有牙证明）', async () => {
  const mod = await loadFormat('America/New_York');
  let caught = 0;
  let total = 0;
  for (let t = START; t < START + 300 * BASE_STEP_MS; t += BASE_STEP_MS) {
    const d = new Date(t);
    total += 1;
    const buggyCached = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }); // 故意缺 second
    if (buggyCached !== mod.formatTime(d.toISOString())) caught += 1;
  }
  assert.equal(total, 300);
  assert.equal(caught, total, '阴性对照必须 100% 抓获；若有漏网=比对器形同虚设');
});

// ---------------------------------------------------------------------------
// 守卫行：补丁只动 formatter，空值/畸形文本守卫不得被后续重构顺手改坏
// ---------------------------------------------------------------------------
test('守卫：null/undefined/空串→UNKNOWN_VALUE，畸形文本原样透出（两函数，守卫两行与 9f139b2 逐字未动）', async () => {
  const mod = await loadFormat('UTC');
  const U = mod.UNKNOWN_VALUE;
  assert.equal(mod.formatTime(null), U);
  assert.equal(mod.formatTime(undefined), U);
  assert.equal(mod.formatTime(''), U);
  assert.equal(mod.formatDateTime(null), U);
  assert.equal(mod.formatDateTime(undefined), U);
  assert.equal(mod.formatDateTime(''), U);
  assert.equal(mod.formatTime('not-a-date'), 'not-a-date', '畸形文本原样透出不猜');
  assert.equal(mod.formatDateTime('2024-13-45T99:99:99Z'), '2024-13-45T99:99:99Z');
});

// ---------------------------------------------------------------------------
// 构造期绑定时区（评审 M-3 性质锁）：缓存 formatter 不随构造后的 TZ 改动改口；
// 旧现场构造口径会随。差值本身就是「缓存优化改变了时区跟随语义」的实证。
// ---------------------------------------------------------------------------
test('构造期绑定时区（M-3）：env 后改不跟随=缓存性质；现场构造仍跟随=旧口径性质', async () => {
  const mod = await loadFormat('UTC');
  const iso = '2024-03-09T06:30:00Z';
  const before = mod.formatTime(iso);
  assert.equal(before, '06:30:00', '前置：UTC 口径快照');
  process.env.TZ = 'Pacific/Chatham';
  const afterFlip = mod.formatTime(iso); // 同一模块实例（formatter 已在 UTC 下构造）
  const freshConstruction = new Date(iso).toLocaleTimeString('zh-CN', { hour12: false }); // 现构造
  assert.equal(afterFlip, before, '缓存 formatter 必须无视构造后的 env 时区改动（构造期绑定）');
  assert.notEqual(freshConstruction, before, '现场构造旧口径应随 env 改动改口——两性质同时成立才构成「构造期绑定」实证');
  assert.equal(freshConstruction, '20:15:00', 'Chatham(+13:45 夏令时)对时快照');
});
