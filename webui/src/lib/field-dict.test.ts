// 数据字典唯一真身的锁（W15 席 W1）。
//
// 面板要展示 35 条指标，每条都得说清「它是什么、单位、从哪来、库里到底有没有」。
// 以前这些说明散在各页的硬编码字符串里，且**从不区分「没数据」和「本身就是 0」**——
// `first_token_latency_ms` 全库 3397 行全 NULL，页面却画成 0 毫秒，读者只会以为
// 首 Token 是瞬时的。本文件的每一条断言都在守这份诚实性：
//   ① 结构完整（key 唯一、条数精确、四段文案都合规）；
//   ② 三个「未采集」字段必须被标成 absent，不能混进 measured；
//   ③ 派生/测量的可得性不能被悄悄改高。
//
// 运行方式：node --test "src/**/*.test.ts"（Node ≥23 原生类型剥离，零新依赖）。
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  absentFields,
  FIELD_DICT,
  fieldDoc,
  fieldRow,
  fieldsByModule,
  type FieldModule,
} from './field-dict.ts';

const HAN = /[\u4e00-\u9fff]/;

// 条数：简报正文写着「共 35 条」，但逐条明细表与测试第 10 条给的都是
// 9 + 6 + 10 + 7 + 6 = **38**，按表格逐行数也正好 38 条。若硬取 35 就要丢 3 条
// 用户逐条点名要的字段，与第 10 条直接冲突；故取**明细表**为准（38），
// 与下面 fieldsByModule 的分模块条数是同一把尺，两处必须同时改。
test('全量字典恰好 38 条，且键值全局唯一', () => {
  assert.equal(FIELD_DICT.length, 38);
  const keys = new Set(FIELD_DICT.map((doc) => doc.key));
  assert.equal(keys.size, FIELD_DICT.length);
});

/**
 * 允许以拉丁字母开头的键名——**只有这三个技术术语**。
 *
 * 简报正文给这三条的键名是 `Token 吞吐速率` / `Top 10% 请求集中度` / `Token 间延迟 P99`，
 * 而同一份简报的测试第 2 条又要求所有 label 以中文开头——两条直接相撞。
 * 「词元」虽是 Token 的正译，但对不上账单页与厂商文档里的原文，读者要再做一次换算；
 * 「Top 10%」改成「百分之十」也更难扫读。故这三条按原词保留，其余条款一律中文开头。
 *
 * 白名单是封闭的：往里加条目等于引入一个新的未翻译英文术语，须先确认它确实没有
 * 中文通行译法。纯英文（整条无一个汉字）无论是否在白名单都判红。
 */
const LATIN_HEAD_WHITELIST = new Set([
  'top_decile_request_share',
  'token_throughput',
  'inter_token_latency_p99',
]);

test('每个键名可读：白名单外的必须中文开头，且任何键名都不许是纯英文', () => {
  for (const doc of FIELD_DICT) {
    assert.match(doc.label, HAN, `${doc.key} 的键名里一个汉字都没有：${doc.label}`);
    if (!LATIN_HEAD_WHITELIST.has(doc.key)) {
      assert.match(doc.label, /^[\u4e00-\u9fff]/, `${doc.key} 的键名必须以中文开头`);
    }
  }
});

test('简介一句话说清，1~24 字且含中文', () => {
  for (const doc of FIELD_DICT) {
    assert.ok(doc.summary.length > 0, `${doc.key} 缺简介`);
    assert.ok(doc.summary.length <= 24, `${doc.key} 的简介超 24 字：${doc.summary.length}`);
    assert.match(doc.summary, HAN, `${doc.key} 的简介不含中文`);
  }
});

test('说明写清口径与边界，10~160 字且含中文', () => {
  for (const doc of FIELD_DICT) {
    assert.ok(doc.detail.length >= 10, `${doc.key} 的说明过短：${doc.detail.length}`);
    assert.ok(doc.detail.length <= 160, `${doc.key} 的说明超 160 字：${doc.detail.length}`);
    assert.match(doc.detail, HAN, `${doc.key} 的说明不含中文`);
  }
});

test('每条都点名来源列，不得留空', () => {
  for (const doc of FIELD_DICT) {
    assert.equal(typeof doc.source, 'string');
    assert.ok(doc.source.trim().length > 0, `${doc.key} 没写数据来源`);
  }
});

test('有数据的字段才是 measured：累计好感度可直接读', () => {
  const doc = fieldDoc('affinity_total');
  assert.ok(doc);
  assert.equal(doc.availability, 'measured');
});

test('首 Token 延迟全库为 NULL：判 absent 而不是 0 毫秒', () => {
  assert.equal(fieldDoc('ttft_p99')?.availability, 'absent');
});

test('不认识的键值返回 undefined，不造空白条目', () => {
  assert.equal(fieldDoc('根本不存在'), undefined);
});

test('未采集字段清单正好三条，UI 顶部提示用它', () => {
  const keys = absentFields()
    .map((doc) => doc.key)
    .sort();
  assert.deepEqual(keys, ['inter_token_latency_p99', 'ttft_p50', 'ttft_p99']);
});

test('五个模块的条数正好铺满全量，各自的条数锁死', () => {
  const modules: readonly FieldModule[] = ['affinity', 'users', 'calls', 'latency', 'channel'];
  const sum = modules.reduce((acc, module) => acc + fieldsByModule(module).length, 0);
  assert.equal(sum, FIELD_DICT.length);
  assert.equal(fieldsByModule('affinity').length, 9);
  assert.equal(fieldsByModule('users').length, 6);
  assert.equal(fieldsByModule('calls').length, 10);
  assert.equal(fieldsByModule('latency').length, 7);
  assert.equal(fieldsByModule('channel').length, 6);
});

test('渲染行只带四列，不带单位/模块/来源', () => {
  const row = fieldRow('affinity_total');
  assert.ok(row);
  assert.deepEqual(Object.keys(row).sort(), ['detail', 'key', 'label', 'summary']);
});

test('五档粒度在字典里都有人用，没有写了却不出现的死档', () => {
  const grains = new Set(FIELD_DICT.flatMap((doc) => doc.grains));
  for (const grain of ['daily', 'weekly', 'monthly', 'yearly', 'total'] as const) {
    assert.ok(grains.has(grain), `粒度 ${grain} 无人使用`);
  }
});
