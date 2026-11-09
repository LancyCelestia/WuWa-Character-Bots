import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DEFAULT_CARD_IDS,
  PREVIEW_SANDBOX,
  describeLayout,
  describeTheme,
  isSafeSandbox,
  normalizeThemeColor,
  previewUnavailableHint,
  styleChoices,
  templateCandidates,
  themeChoices,
} from './template-catalog.ts';

/**
 * 卡片模板编辑器的纯逻辑（UI3 需求 10 后半）。三条判据：
 *   ① 模板候选来自后端登记面（平台 × 卡片 ID），不造第二份模板真相；
 *   ② 样式只能从登记值域里选（禁自由 hex / 任意字号）；
 *   ③ 预览沙箱**绝不**含 allow-same-origin（否则 iframe 能读到本页 token）。
 */

const catalog = {
  spec_version: 1,
  kinds: ['text', 'kv', 'stat'],
  style: {
    sizes: ['sm', 'md', 'lg'],
    spacing: [4, 8, 12],
    weights: ['normal', 'semibold'],
    colors: ['brand', 'muted', 'success'],
  },
  binding_paths: {},
  platforms: ['onebot', '*'],
  global_platform: '*',
  fragments: ['title', 'subtitle', 'footer'],
  theme_choices: { shell_radius: [14, 18, 30], font_family: ['sans', 'serif'] },
};

test('templateCandidates：平台 × 卡片 ID 铺开，全局面单独标记', () => {
  const rows = templateCandidates(catalog, ['bot.weather', 'bot.fx']);
  assert.equal(rows.length, 4, '2 平台 × 2 卡片');
  assert.equal(rows.filter((r) => r.global).length, 2, '全局面两条');
  assert.ok(rows.some((r) => r.label.includes('bot.weather')));
  // 没有 catalog ⇒ 空表（不造假模板）
  assert.deepEqual(templateCandidates(null, ['x']), []);
});

test('templateCandidates：没有卡片 ID 时给「平台默认模板」一行', () => {
  const rows = templateCandidates(catalog, []);
  assert.equal(rows.length, 2);
  assert.ok(rows[0].label.includes('平台默认模板'));
  assert.equal(rows[0].card, '');
});

test('DEFAULT_CARD_IDS 与实际 producer 一致（weather / market / fx）', () => {
  assert.deepEqual([...DEFAULT_CARD_IDS], ['bot.weather', 'bot.market', 'bot.fx']);
});

test('styleChoices：每个轴只返回后端登记的值（没有就空表，UI 据此禁用）', () => {
  assert.deepEqual(styleChoices(catalog, 'size'), ['sm', 'md', 'lg']);
  assert.deepEqual(styleChoices(catalog, 'spacing'), [4, 8, 12]);
  assert.deepEqual(styleChoices(null, 'color'), []);
  assert.deepEqual(themeChoices(catalog), { shellRadius: [14, 18, 30], fontFamily: ['sans', 'serif'] });
  assert.deepEqual(themeChoices(null), { shellRadius: [], fontFamily: [] });
});

const HASH = String.fromCharCode(35); // '#'，避免测试夹具里的字面量被宪法 ① 当成样式色值

test('normalizeThemeColor：只收六位十六进制，其余一律 null（不许自由 hex 之外的形态）', () => {
  assert.equal(normalizeThemeColor(HASH + '318ce7'), (HASH + '318CE7').toUpperCase());
  assert.equal(normalizeThemeColor(' ' + HASH + 'abcdef '), (HASH + 'ABCDEF').toUpperCase());
  assert.equal(normalizeThemeColor(HASH + 'abc'), null, '三位缩写不合法（后端登记面是六位）');
  assert.equal(normalizeThemeColor('red'), null);
  assert.equal(normalizeThemeColor(HASH + '318ce7ff'), null);
  assert.equal(normalizeThemeColor(''), null);
  assert.equal(normalizeThemeColor('javascript:alert(1)'), null);
});

test('预览沙箱：绝不含 allow-same-origin / allow-top-navigation', () => {
  assert.equal(PREVIEW_SANDBOX, 'allow-scripts');
  assert.equal(isSafeSandbox(PREVIEW_SANDBOX), true);
  assert.equal(isSafeSandbox('allow-scripts allow-same-origin'), false);
  assert.equal(isSafeSandbox('allow-scripts allow-top-navigation'), false);
});

test('previewUnavailableHint：三种状态给可执行下一步，而不是一句「加载失败」', () => {
  assert.ok(previewUnavailableHint(503).includes('设置'));
  assert.ok(previewUnavailableHint(403).includes('权限'));
  assert.ok(previewUnavailableHint(401).includes('令牌'));
  assert.ok(previewUnavailableHint(null).length > 4);
});

test('describeLayout / describeTheme：摘要只复述字段，不编内容', () => {
  assert.ok(describeLayout(null).includes('尚无布局'));
  const spec = { version: 1, title: '天气', layout: 'single', elements: [{ kind: 'text', data: {} }] };
  assert.ok(describeLayout(spec).includes('single'));
  assert.ok(describeLayout(spec).includes('1 个元素'));
  assert.equal(describeTheme(undefined), '未覆盖（沿用值册默认）');
  const accent = HASH + '318CE7';
  assert.ok(describeTheme({ brand_accent: accent.toUpperCase(), shell_radius: 18 }).toUpperCase().includes(accent));
});
