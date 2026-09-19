import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  asSearchInput,
  canonicalSearchStr,
  freeText,
  normalizeWith,
  searchSpecFor,
  validateSearchFor,
  SEARCH_SPECS,
  ROUTE_PATHS,
} from './search-params.ts';

/**
 * 与 @tanstack/router-core 的 qss `encode()` 同构的参照实现：router 回填
 * location.searchStr 用的就是这个 primitive（qss.js 里 `new URLSearchParams()` + `.toString()`）。
 * 本文件最重要的判据是"规范串 === router 自己会产生的串"，所以这里必须用**同一 primitive**
 * 当参照，而不是把期望值抄成字面量（抄字面量的话，两侧一起错就测不出来）。
 */
function routerSideSearchStr(search: Record<string, string>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) params.set(key, value);
  const query = params.toString();
  return query ? `?${query}` : '';
}

test('规范串与 router 自身序列化逐字节同构（幂等闸唯一正确的判据来源）', () => {
  const nasty = ['a b', "o'brien", 'a!b', 'a(b)c', 'a~b', 'a+b', 'a=b&c', '上海 徐汇', '100%', '中文 与 emoji 🎐'];
  for (const value of nasty) {
    const canonical = canonicalSearchStr({ collection: value });
    assert.equal(canonical, routerSideSearchStr({ collection: value }), `值 ${JSON.stringify(value)} 两侧不同构 → 改写条件恒成立`);
    const back = new URLSearchParams(canonical.slice(1)).get('collection');
    assert.equal(back, value, `值 ${JSON.stringify(value)} 过一轮地址栏取不回来`);
  }
});

test('反证：encodeURIComponent 口径与 router 口径对含空格值就是不等（旧版缺陷的成因锁）', () => {
  const viaRouter = routerSideSearchStr({ collection: 'a b' });
  const legacy = `?collection=${encodeURIComponent('a b')}`;
  assert.notEqual(legacy, viaRouter, '若这条也相等，说明上一版的"字符串相等幂等闸"本来就安全，缺陷定级要下调');
  assert.equal(legacy, '?collection=a%20b');
  assert.equal(viaRouter, '?collection=a+b');
  assert.equal(canonicalSearchStr({ collection: 'a b' }), viaRouter);
});

test('改写幂等：对已规范串再归一一次，逐字节不变（不来回震荡）', () => {
  for (const value of ['a b', "it's (fine)~", 'plain', '中文 混排']) {
    const once = canonicalSearchStr({ collection: value });
    const reparsed = Object.fromEntries(new URLSearchParams(once.slice(1)));
    assert.equal(canonicalSearchStr(normalizeWith(SEARCH_SPECS['/knowledge'], reparsed)), once);
  }
});

test('键序=参数表声明序，与输入对象键序无关（确定性输出，样张可比）', () => {
  const spec = { alpha: freeText, beta: freeText };
  assert.equal(canonicalSearchStr(normalizeWith(spec, { beta: '2', alpha: '1' })), '?alpha=1&beta=2');
});

test('未声明参数一律丢弃：/logs 不消费任何参数，?window=7d 被洗成缺省态', () => {
  assert.deepEqual(normalizeWith(SEARCH_SPECS['/logs'], { window: '7d', q: 'x' }), {});
  assert.equal(canonicalSearchStr(normalizeWith(SEARCH_SPECS['/logs'], { window: '7d' })), '');
});

test('声明了但值为空串/纯空白/非字符串 → 按缺省省略，绝不产生 ?collection= 这种半态', () => {
  for (const raw of ['', '   ', undefined, null, 7, {}, ['a']]) {
    assert.equal(freeText(raw), undefined, `raw=${JSON.stringify(raw)} 不该成立`);
  }
  assert.equal(canonicalSearchStr(normalizeWith(SEARCH_SPECS['/knowledge'], { collection: '  ' })), '');
});

test('searchSpecFor：未知路径（404 面）返回 undefined，规则不接管', () => {
  assert.equal(searchSpecFor('/nope'), undefined);
  assert.equal(searchSpecFor(''), undefined);
  assert.deepEqual(Object.keys(searchSpecFor('/knowledge') ?? {}), ['collection']);
  for (const path of ROUTE_PATHS) {
    assert.notEqual(searchSpecFor(path), undefined, `${path} 必须在表里表态`);
  }
});

test('validateSearchFor 工厂九条路由共用实现，且返回值就是规范态（页面只能读到它）', () => {
  const validate = validateSearchFor('/knowledge');
  assert.deepEqual(validate({ collection: '库街区百科', window: '7d', junk: 'x' }), { collection: '库街区百科' });
  assert.deepEqual(validate({}), {});
  for (const path of ROUTE_PATHS) assert.equal(typeof validateSearchFor(path), 'function');
});

test('asSearchInput 只做类型放宽不改值（防它哪天被塞进逻辑）', () => {
  const input = { collection: 'a b' };
  assert.equal(asSearchInput(input), input);
});
