// 外观字段表的**去重闸**（F 席）。
//
// 病：`unitSystem` 在 `schema-fields.ts` 里被登记了两份——「数据与图表」与「语言与格式」各一条。
// 配置树里确实有两个同名字段（`charts.unitSystem` / `locale.unitSystem`），但**只有
// `locale` 那份被消费**（`lib/appearance/context.tsx` 把 `config.locale.unitSystem` 交给
// `lib/format.ts` 的数字格式接缝）。于是「数据与图表」那条控件调了看不出任何变化——
// 用户会以为设置坏了。本闸钉两件事：
//   ① 同一条 `分节.字段` 不许被两组各登记一次（重复控件＝第二真身）；
//   ② 数字单位只由「语言与格式」一组承担。
import test from 'node:test';
import assert from 'node:assert/strict';
import { APPEARANCE_FIELDS } from './appearance/schema-fields.ts';
import { DEFAULT_APPEARANCE } from './appearance/defaults.ts';

test('外观字段表：同一条「分节.字段」不许被登记两次', () => {
  const seen = new Set<string>();
  const duplicates: string[] = [];
  for (const group of APPEARANCE_FIELDS) {
    for (const item of group.items) {
      const id = `${item.section ?? group.section}.${item.key}`;
      if (seen.has(id)) duplicates.push(`${id}（组 ${group.id} 重复登记）`);
      else seen.add(id);
    }
  }
  assert.deepEqual(duplicates, []);
});

test('外观字段表：数字单位只由「语言与格式」承担，配置树里也只留一份', () => {
  const owners = APPEARANCE_FIELDS.filter((group) => group.items.some((item) => item.key === 'unitSystem')).map(
    (group) => group.section,
  );
  assert.deepEqual(owners, ['locale'], '数字单位只能有一处控件，且必须是被真正消费的那一处');

  const charts = DEFAULT_APPEARANCE.charts as unknown as Record<string, unknown>;
  assert.equal('unitSystem' in charts, false, 'charts.unitSystem 没有任何消费方，留着就是「调了没反应」的死控件');
  assert.equal(DEFAULT_APPEARANCE.locale.unitSystem, 'compact', '语言与格式那份才是真身');
});
