// i18n 齐备性锁：全站每个 t('ns.key') 都必须在 zh 与 en 两份 locale 里**同时**有值，
// 且 `{{占位符}}` 两边一致。缺键的后果不是报错，而是页面上直接显示 `console.block.health`
// 这种原始键名——用户验收第一条「全站无未翻译英文」就是被这条漏穿的。
//
// 为什么是静态扫源码而不是跑 react-i18next：仓库测试走 `node --test`，没有 jsdom，
// 挂不了 React。扫源码是这里唯一零依赖且真能拦住的口径。
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const ROOT = new URL('../', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const zh = JSON.parse(readFileSync(join(ROOT, 'locales/zh-CN/common.json'), 'utf8'));
const en = JSON.parse(readFileSync(join(ROOT, 'locales/en/common.json'), 'utf8'));

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !name.includes('.test.')) out.push(p);
  }
  return out;
}

/** 点号取值；任一段缺失返回 undefined（"有键但值为空串" 也算缺失）。 */
function lookup(doc: unknown, dotted: string): unknown {
  let cur: unknown = doc;
  for (const part of dotted.split('.')) {
    if (cur && typeof cur === 'object' && part in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return cur;
}

/** 源码里所有 `t('ns.key')` 的字面量键（动态拼接的键扫不到，故一律用字面量写，见本文件末条）。 */
function usageKeys(): { key: string; where: string }[] {
  const hits: { key: string; where: string }[] = [];
  for (const file of walk(join(ROOT, '..').replace(/[\\/]src[\\/]?$/, '') + '/src')) {
    const rel = file.split('\\').join('/').split('/src/')[1] ?? file;
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        for (const m of line.matchAll(/t\(\s*'([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9._]+)+)'/g)) {
          hits.push({ key: m[1], where: `${rel}:${i + 1}` });
        }
      });
  }
  return hits;
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g)].map((m) => m[1]).sort();
}

const HITS = usageKeys();

test('扫到了足够的 t() 用量（防止本锁因正则失配而假绿）', () => {
  // 实测当前 323 处字面量键；下界取 300，只为拦住「正则失配导致零命中仍报绿」这一种假绿。
  // 调这个数字＝承认扫面变了，先看是哪边变了。
  assert.ok(HITS.length >= 300, `只扫到 ${HITS.length} 处 t() 调用，扫面可能已失效`);
});

test('每个 t() 键在 zh 与 en 里都有值（缺一个就是页面上露原始键名）', () => {
  const missing: string[] = [];
  for (const { key, where } of HITS) {
    const zhVal = lookup(zh, key);
    const enVal = lookup(en, key);
    if (typeof zhVal !== 'string' || !zhVal.trim()) missing.push(`zh 缺 ${key}（${where}）`);
    if (typeof enVal !== 'string' || !enVal.trim()) missing.push(`en 缺 ${key}（${where}）`);
  }
  assert.deepEqual(missing, [], `以下键会让页面显示原始键名：\n${missing.join('\n')}`);
});

test('同一键的 {{占位符}} 在 zh 与 en 里完全一致', () => {
  const drift: string[] = [];
  for (const { key } of HITS) {
    const zhVal = lookup(zh, key);
    const enVal = lookup(en, key);
    if (typeof zhVal !== 'string' || typeof enVal !== 'string') continue;
    const a = placeholders(zhVal);
    const b = placeholders(enVal);
    if (a.join(',') !== b.join(',')) {
      drift.push(`${key}: zh=${JSON.stringify(a)} en=${JSON.stringify(b)}`);
    }
  }
  assert.deepEqual(drift, [], `占位符不一致（另一端会显示花括号原文）：\n${drift.join('\n')}`);
});

test('中文段的值不是从英文抄来的空壳（真译过的粗筛）', () => {
  // 只拦「中文值与英文值一字不差」这一种明确的未翻译情形；
  // 专有名词型键（如 Token 面板）两边本就可能同形，故按「含汉字」放行。
  const same: string[] = [];
  for (const { key } of HITS) {
    const zhVal = lookup(zh, key);
    const enVal = lookup(en, key);
    if (typeof zhVal !== 'string' || typeof enVal !== 'string') continue;
    if (zhVal === enVal && /[\u4e00-\u9fff]/.test(zhVal) === false) same.push(key);
  }
  assert.deepEqual(same, [], `这些键两边同形且无汉字，疑似没译：\n${same.join('\n')}`);
});
