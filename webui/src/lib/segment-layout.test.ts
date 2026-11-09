import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  labelWidth,
  planSegmentRows,
  SEGMENT_AVAILABLE_DEFAULT,
  SEGMENT_SLACK_PX,
  SEGMENT_TIERS,
  segmentDensity,
  segmentLayoutClass,
  segmentOptionClass,
  segmentRowWidth,
} from './segment-layout.ts';

/**
 * 分段选择器 / 单选组的版式锁（G5）。
 *
 * 用户截图里的两处缺陷（「图表绘制质量 低/中/高」「取色来源 跟随语义色/品牌色/自定义」）
 * 都不是配色问题，是**宽度算术**问题：控件区被压到比选项组内在宽度还窄，
 * 每个 label 于是各自折行、选中胶囊压在邻项文字上。
 *
 * 仓库没有 jsdom / playwright，也不许为此装包；所以把「给定宽度下 N 个选项排几行、
 * 每项占哪一段 x、相邻是否重叠」抽成纯函数，组件与测试**共用同一份算术**：
 *   · 够宽 → 单行；
 *   · 不够 → 整体换行（每项 shrink-0、不断词），绝不允许两项在 x 轴上相交；
 *   · 连紧凑档都放不下一行 → 两列均分（grid），仍然不重叠。
 *
 * 下面的期望值全部由「字号 × 字数 + 内边距 + 间隙」手算得出（见各断言旁注释），
 * 不是拿实现回算一遍——否则测试只会跟着实现一起错。
 */

// comfort：fs-body 13px + px-3（左右各 12）= 每项 字数×13 + 24
// compact：fs-caption 12px + px-2（左右各 8）= 每项 字数×12 + 16
// 轨道内边距 p-1 = 4，项间隙 gap-1 = 4

test('三个短选项在 224px 控件区里必须单行（截图缺陷①）', () => {
  const labels = ['低', '中', '高'];
  // 每项 13 + 24 = 37；轨道 4×2 + 项 37×3 + 间隙 4×2 = 127
  assert.equal(segmentRowWidth(labels, SEGMENT_TIERS.comfortable), 127);
  assert.equal(segmentDensity(labels, SEGMENT_AVAILABLE_DEFAULT), 'comfortable');
  const rows = planSegmentRows(labels, SEGMENT_AVAILABLE_DEFAULT, SEGMENT_TIERS.comfortable);
  assert.equal(rows.length, 1, '「低/中/高」被挤成两行就是用户截图那个缺陷');
});

test('「跟随语义色 / 品牌色 / 自定义」在 224px 里必须单行（截图缺陷②）', () => {
  const labels = ['跟随语义色', '品牌色', '自定义'];
  // comfort：8 + (5×13+24) + 4 + (3×13+24) + 4 + (3×13+24) = 231 > 224-8 → 降档
  assert.equal(segmentRowWidth(labels, SEGMENT_TIERS.comfortable), 231);
  assert.equal(segmentDensity(labels, SEGMENT_AVAILABLE_DEFAULT), 'compact');
  // compact：8 + (5×12+16) + 4 + (3×12+16) + 4 + (3×12+16) = 196 ≤ 216 → 单行
  const rows = planSegmentRows(labels, SEGMENT_AVAILABLE_DEFAULT, SEGMENT_TIERS.compact);
  assert.equal(rows.length, 1, '降一档字号/内边距之后仍然要保住单行');
  assert.equal(segmentLayoutClass(rows.length), 'inline-flex flex-nowrap');
});

test('三项长标签降档后仍单行（真实条目：3D 视图质量档）', () => {
  const labels = ['低（最流畅）', '中', '高（最清晰）'];
  // compact：8 + (6×12+16) + 4 + (1×12+16) + 4 + (6×12+16) = 220 ≤ 224
  assert.equal(segmentDensity(labels, SEGMENT_AVAILABLE_DEFAULT), 'compact');
  assert.equal(
    planSegmentRows(labels, SEGMENT_AVAILABLE_DEFAULT, SEGMENT_TIERS.compact).length,
    1,
  );
});

test('真的放不下时整体换行，且相邻两项的 x 区间绝不相交', () => {
  const labels = ['跟随语义色', '品牌色', '自定义'];
  const rows = planSegmentRows(labels, 120, SEGMENT_TIERS.compact);
  assert.ok(rows.length > 1, '120px 放不下三项，必须换行而不是把每项压扁');
  assert.deepEqual(
    rows.flatMap((row) => row.boxes.map((box) => box.label)),
    labels,
    '换行不得丢项、不得改序、不得把一项拆成两半',
  );
  for (const row of rows) {
    for (let i = 1; i < row.boxes.length; i += 1) {
      const prev = row.boxes[i - 1];
      const next = row.boxes[i];
      assert.ok(
        prev.x + prev.width <= next.x,
        `同一行里「${prev.label}」右沿 ${prev.x + prev.width} 压到了「${next.label}」左沿 ${next.x}`,
      );
    }
    assert.ok(row.width <= 120, `单行宽度 ${row.width} 冲出了 120px 容器`);
  }
  assert.equal(segmentLayoutClass(rows.length), 'grid grid-cols-2');
});

test('连紧凑档都放不下一行 → 两列均分（grid），不是继续挤', () => {
  const labels = ['跟随语义色', '品牌色', '自定义', '禁用'];
  // compact 单行：8 + 76+4+52+4+52+4+40 = 240 > 224
  assert.equal(segmentRowWidth(labels, SEGMENT_TIERS.compact), 240);
  const rows = planSegmentRows(labels, SEGMENT_AVAILABLE_DEFAULT, SEGMENT_TIERS.compact);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => row.boxes.length), [3, 1]);
});

test('单项比容器还宽时单独占一行并标 overflow（不靠压扁文字解决）', () => {
  const rows = planSegmentRows(['跟随语义色', '自定义'], 48, SEGMENT_TIERS.compact);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].overflow, true, '单个 label 超宽要如实标记，由外层 max-w-full 裁切');
  assert.equal(rows[1].overflow, true);
  assert.equal(rows[0].boxes.length, 1);
});

test('ASCII 比汉字窄（否则「720p」会被算成 4 个整字宽，白白降档）', () => {
  const compact = SEGMENT_TIERS.compact;
  assert.ok(labelWidth('720p', compact) < labelWidth('自定义', compact));
  assert.equal(labelWidth('自定义', compact), 36);
  assert.equal(labelWidth('720p', compact), 29);
});

test('档位常量与类名一一对应（算术与 CSS 不得两张皮）', () => {
  assert.equal(SEGMENT_TIERS.comfortable.charPx, 13);
  assert.equal(SEGMENT_TIERS.comfortable.optionPadX, 12);
  assert.equal(SEGMENT_TIERS.compact.charPx, 12);
  assert.equal(SEGMENT_TIERS.compact.optionPadX, 8);

  for (const density of ['comfortable', 'compact'] as const) {
    const idle = segmentOptionClass(density, false);
    assert.match(idle, /shrink-0/, '选项一经压缩就会压字：必须 shrink-0');
    assert.match(idle, /whitespace-nowrap/, 'label 内部折行=选中胶囊与文字重叠的直接原因');
  }
  assert.match(segmentOptionClass('comfortable', false), /px-3/);
  assert.match(segmentOptionClass('comfortable', true), /fs-body/);
  assert.match(segmentOptionClass('compact', false), /px-2/);
  assert.match(segmentOptionClass('compact', true), /fs-caption/);
  assert.ok(SEGMENT_SLACK_PX > 0, '降档判定要留余量，否则「刚好够」会被字体差异挤爆');
});
