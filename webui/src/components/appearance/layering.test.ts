// 分层契约锁（Q3）：把「背景层永远在正文之下」这条从**约定**变成**机器判据**。
//
// 为什么不是一张截图说了算：截图证明的是「这一刻这张 PNG 里没糊」，改一行 CSS 就作废。
// 这里判的是**结构**——背景层必须全部落在 .bg-stage 容器里，容器必须落在负 z 步。
// 判据各自能被单独打断，任何一条被打断都直接红：
//   ① 容器（.bg-stage）必须 position:fixed + inset:0 + z-index<0 + isolation:isolate + pointer-events:none；
//   ② 六个背景层必须都渲染在容器内（读 app-shell.tsx 的真实挂载顺序）；
//   ③ 每个层的 z-index/position/pointer-events 组合经分层模型判定后必须是「正文之下」；
//   ④ 壁纸三条规则要铺满到视口之外（缩放/模糊不露白）。
//
// 另有一条棘轮：index.css 里**所有**负 z-index 抽取面必须都能被归类——要么是五个背景层，
// 要么是自带层叠上下文的父块里的装饰伪元素。冒出来第六处无人认领的负 z 层就红。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import { bandOf, isBehindContent, layerBand, stageBand } from './layering.ts';
import type { LayerLike, StackContextLike } from './layering.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEBUI = join(HERE, '..', '..', '..');
const CSS = readFileSync(join(WEBUI, 'src', 'index.css'), 'utf8');
const SHELL = readFileSync(join(WEBUI, 'src', 'components', 'layout', 'app-shell.tsx'), 'utf8');
const BACKDROP = readFileSync(join(HERE, 'background-stage.tsx'), 'utf8');

/** 背景层清单（与 index.css / app-shell.tsx 逐字对应）。 */
const BG_LAYERS = ['.ambient-video', '.ambient-glow', '.ambient-grain', '.wp-layer', '.wp-scrim', '.bubble-field'];
/** 背景容器本身（它自己就带 z-index:-1，是唯一允许的非图层负 z 顶层块）。 */
const STAGE = '.bg-stage';
/** 允许的「装饰性负 z」父块：它们自己就建立层叠上下文，伪元素沉不下去也浮不上来。 */
const DECOR_PARENTS_TOP = ['.ambient-video'];
const DECOR_PARENTS_BLOCK = ['@utility window', '@utility chart-frame', '@utility glaze-band'];

function isClaimed(chain: string[]): boolean {
  if (chain.length === 1) {
    return chain[0]
      .split(',')
      .map((s) => s.trim())
      .every(
        (sel) =>
          sel === STAGE ||
          BG_LAYERS.includes(sel) ||
          DECOR_PARENTS_TOP.some((base) => sel === base || sel === `${base}::before` || sel === `${base}::after`)
      );
  }
  return (
    chain.length === 2 &&
    DECOR_PARENTS_BLOCK.includes(chain[0]) &&
    /&::(before|after)$/.test(chain[chain.length - 1])
  );
}

interface Rule {
  /** 嵌套链：['.window', '&::before'] 表示 `.window { &::before { … } }`。 */
  chain: string[];
  decls: Record<string, string>;
}

/**
 * 逐字符解析（注释剥掉后）：用 '{' / ';' / '}' 三个记号增量收声明。
 * 不用正则配 [^{}]+ 的原因：@utility 里含嵌套块，正则会把「父块的声明」当成子块选择器，
 * 于是 ratchet 会读到一坨假选择器（首版就是这么红的）。
 */
function parseRules(css: string): Rule[] {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules: Rule[] = [];
  const frames: { chain: string[]; decls: Record<string, string> }[] = [{ chain: [], decls: {} }];
  let buf = '';
  const flushDecl = () => {
    const text = buf.trim();
    buf = '';
    if (!text) return;
    const i = text.indexOf(':');
    if (i <= 0) return;
    const key = text.slice(0, i).trim().toLowerCase();
    const value = text.slice(i + 1).trim();
    if (key) frames[frames.length - 1].decls[key] = value;
  };
  for (const ch of src) {
    if (ch === '{') {
      const sel = buf.trim().replace(/\s+/g, ' ');
      buf = '';
      frames.push({ chain: [...frames[frames.length - 1].chain, sel], decls: {} });
    } else if (ch === ';') {
      flushDecl();
    } else if (ch === '}') {
      flushDecl();
      const frame = frames.pop();
      if (frame && frame.chain.length > 0 && Object.keys(frame.decls).length > 0) {
        rules.push({ chain: frame.chain, decls: frame.decls });
      }
      buf = '';
    } else {
      buf += ch;
    }
  }
  return rules;
}

const RULES = parseRules(CSS);
const keyOf = (chain: string[]) => chain.join(' |> ');

/** 规则顶层选择器列表（含逗号并写：`.a, .b { … }` 要算两条）。 */
function topSelectors(rule: Rule): string[] {
  if (rule.chain.length !== 1) return [];
  return rule.chain[0]
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 合并某个顶层选择器的全部声明（后写覆盖先写，与层叠次序一致）。 */
function declsOf(selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of RULES) if (topSelectors(r).includes(selector)) Object.assign(out, r.decls);
  return out;
}

function numberOrNull(value: string | undefined): number | null {
  if (value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function stageFromCss(): StackContextLike {
  const d = declsOf('.bg-stage');
  return {
    selector: '.bg-stage',
    zIndex: numberOrNull(d['z-index']),
    position: d.position ?? 'static',
    isolation: d.isolation ?? 'auto',
  };
}

function layerFromCss(selector: string): LayerLike {
  const d = declsOf(selector);
  return {
    selector,
    zIndex: numberOrNull(d['z-index']) ?? 0,
    position: d.position ?? 'static',
    pointerEvents: d['pointer-events'] ?? 'auto',
    insideStage: true,
  };
}

// ── ① 容器规则本身 ──────────────────────────────────────────────────────
test('背景容器 .bg-stage：fixed 铺满视口 + 负 z 步 + 自成层叠上下文 + 不吞点击', () => {
  const d = declsOf('.bg-stage');
  assert.ok(Object.keys(d).length > 0, 'index.css 里没有 .bg-stage 规则⇒背景层没有专属层叠上下文容器');
  assert.equal(d.position, 'fixed', '.bg-stage 必须 position:fixed（铺满视口、不随滚动重绘）');
  assert.equal(d.inset, '0', '.bg-stage 必须 inset:0 才能盖住含超出视口在内的整块画布');
  assert.equal(d.isolation, 'isolate', '.bg-stage 必须 isolation:isolate，负 z 子层才只能在这个组里下沉');
  assert.equal(d['pointer-events'], 'none', '.bg-stage 必须 pointer-events:none，否则整块背景抢走鼠标事件');
  const z = numberOrNull(d['z-index']);
  assert.ok(
    z !== null && z < 0,
    `.bg-stage 的 z-index 必须是负值（现在是 ${d['z-index'] ?? 'auto'}）；取 0 会把整组背景抬到 static 正文之上`
  );
});

// ── ② 五个背景层都挂在容器里 ────────────────────────────────────────────
test('六个背景层全部渲染在 .bg-stage 里面（读 app-shell.tsx 真实挂载顺序）', () => {
  const occurrences = SHELL.match(/className='bg-stage'/g) ?? [];
  assert.equal(occurrences.length, 1, `app-shell.tsx 里应当恰有一个背景容器，实际 ${occurrences.length} 个`);
  const open = SHELL.indexOf("className='bg-stage'");
  const ambient = SHELL.indexOf('<AmbientBackdrop');
  const wall = SHELL.indexOf('<BackgroundStage');
  const bubbles = SHELL.indexOf('<MotionBubbles');
  const aside = SHELL.indexOf('<aside');
  assert.ok(ambient > open, 'AmbientBackdrop 必须排在 .bg-stage 开标签之后（＝在容器内）');
  assert.ok(
    wall > ambient,
    'BackgroundStage 必须与 AmbientBackdrop 同在容器内、且顺序在后（本地壁纸压在内置背景之上）'
  );
  assert.ok(
    bubbles > wall,
    'MotionBubbles 必须与另两层同在容器内、且排在最后（气泡是最上一层氛围，压不到壁纸上但顺序必须确定）'
  );
  assert.ok(aside > bubbles, '<aside> 必须排在容器之后：背景组是正文区的兄弟，不能塞进正文或侧栏');
  assert.equal(SHELL.match(/<AmbientBackdrop\s*\/>/g)?.length, 1, 'AmbientBackdrop 只许挂一次');
  assert.equal(SHELL.match(/<BackgroundStage\s*\/>/g)?.length, 1, 'BackgroundStage 只许挂一次');
  assert.equal(SHELL.match(/<MotionBubbles\s*\/>/g)?.length, 1, 'MotionBubbles 只许挂一次');
});

// ── ③ 分层模型对真实样式的判定 ──────────────────────────────────────────
test('每个背景层经分层模型判定都严格排在正文之下', () => {
  const stage = stageFromCss();
  assert.equal(stageBand(stage).band, -1, `容器带位不对：${stageBand(stage).reason}`);
  for (const sel of BG_LAYERS) {
    const layer = layerFromCss(sel);
    const verdict = layerBand(layer, stage);
    assert.equal(
      verdict.band,
      -1,
      `${sel} 未被判定在正文之下：${verdict.reason}（z-index=${layer.zIndex} position=${layer.position} pointer-events=${layer.pointerEvents}）`
    );
    assert.equal(isBehindContent(layer, stage), true, `${sel} 不在正文之下`);
  }
});

test('背景层规格：都铺满视口（fixed+inset:0）且不抢事件', () => {
  for (const sel of BG_LAYERS) {
    const d = declsOf(sel);
    assert.equal(d.position, 'fixed', `${sel} 必须 position:fixed`);
    assert.equal(d['pointer-events'], 'none', `${sel} 必须 pointer-events:none`);
    assert.equal(d.inset, '0', `${sel} 必须 inset:0 铺满视口`);
  }
});

// ── ④ 壁纸三条规则的覆盖性（偏移/模糊不露白）────────────────────────────
test('壁纸层：.wp-media 过扫描到视口之外，缩放/模糊都不会露出未铺满的边', () => {
  const media = declsOf('.wp-media');
  assert.equal(media['object-fit'], 'cover', '.wp-media 必须 object-fit:cover');
  const width = parseFloat(media.width ?? '0');
  const height = parseFloat(media.height ?? '0');
  const left = media.left !== undefined ? parseFloat(media.left) : 0;
  const top = media.top !== undefined ? parseFloat(media.top) : 0;
  assert.ok(width >= 108, `.wp-media 宽度至少 108%（现 ${media.width ?? '未写'}）：模糊/缩放要在视口外衰减`);
  assert.ok(height >= 108, `.wp-media 高度至少 108%（现 ${media.height ?? '未写'}）`);
  assert.ok(
    left <= -4 && top <= -4,
    `.wp-media 必须向四周外扩（left/top≤-4%，现 left=${media.left} top=${media.top}），否则 blur 边缘会露白`
  );
  assert.equal(declsOf('.wp-layer').overflow, 'hidden', '.wp-layer 必须 overflow:hidden，过扫描部分要裁掉而不是溢出成滚动条');
  assert.equal(declsOf('.wp-scrim').inset, '0', '.wp-scrim 必须 inset:0，否则壁纸压暗罩会露出未压暗的边');
});

// ── ⑤ 棘轮：负 z 层不得在清单外新增 ─────────────────────────────────────
test('背景层的状态提示必须 createPortal 到 body，不许留在负 z 图层里', () => {
  const statusCount = (BACKDROP.match(/role='status'/g) ?? []).length;
  const portalCount = (BACKDROP.match(/createPortal\(/g) ?? []).length;
  assert.ok(statusCount >= 1, 'background-stage.tsx 里找不到 role=status 提示——测试已空转，先确认文案还在');
  assert.equal(
    statusCount,
    portalCount,
    `每条状态提示都要各自包在 createPortal(...) 里（status=${statusCount} portal=${portalCount}）：` +
      '它们由 .bg-stage 内的组件渲染，留在原地就落进 z-index:-1 的那一组，z-10 也浮不出面板'
  );
  assert.ok(
    !/className='wp-layer'[\s\S]{0,300}?role='status'/.test(BACKDROP),
    '状态提示被塞回 .wp-layer 了：那层是 fixed + z-index:-40 + pointer-events:none，文字永远看不见'
  );
});
test('棘轮：index.css 里的负 z-index 抽取面全部被归类，无清单外新增', () => {
  const found = RULES.filter((r) => {
    const z = numberOrNull(r.decls['z-index']);
    return z !== null && z < 0;
  }).map((r) => r.chain);
  const unclaimed = found.filter((chain) => !isClaimed(chain));
  assert.deepEqual(
    unclaimed.map(keyOf),
    [],
    `出现清单外的负 z-index 抽取面：${unclaimed.map(keyOf).join(' , ')}（要么并进 .bg-stage 并登记，要么改掉）`
  );
  for (const sel of BG_LAYERS) {
    assert.ok(
      found.some((chain) => chain.length === 1 && chain[0].split(',').map((s) => s.trim()).includes(sel)),
      `背景层 ${sel} 在 CSS 里找不到负 z-index（契约失效，先确认它还在画）`
    );
  }
});

// ── ⑥ 负样本：模型必须能判红「上一轮那条建议」 ──────────────────────────
test('负样本：容器取 z-index:0 会被判成正文之上（这正是不能照抄那条建议的原因）', () => {
  const z0: StackContextLike = { selector: '.bg-stage', zIndex: 0, position: 'fixed', isolation: 'isolate' };
  assert.notEqual(stageBand(z0).band, -1, 'z-index:0 的容器被判成负 z 步＝模型失效');
  assert.equal(stageBand(z0).band, 1, 'z-index:0 的定位元素应落在「定位 z:auto/0」带（高于 in-flow 正文）');
  const layer = layerFromCss('.ambient-glow');
  assert.equal(isBehindContent(layer, z0), false, '容器抬到 z:0 时，背景层必须被判成盖住正文');

  const auto: StackContextLike = { selector: '.bg-stage', zIndex: null, position: 'fixed', isolation: 'isolate' };
  assert.equal(stageBand(auto).band, 1, 'z-index:auto 的固定容器同样在 in-flow 正文之上');

  const isolated: StackContextLike = { selector: '.bg-stage', zIndex: -1, position: 'fixed', isolation: 'auto' };
  assert.equal(stageBand(isolated).band, 'uncontrolled', '缺 isolation 的容器必须判「不可控」而不是放过');

  const loose: LayerLike = { ...layer, insideStage: false };
  assert.equal(layerBand(loose, stageFromCss()).band, 'uncontrolled', '不在容器里的负层必须判「不可控」');

  const grabby: LayerLike = { ...layer, pointerEvents: 'auto' };
  assert.equal(layerBand(grabby, stageFromCss()).band, 'uncontrolled', '会抢事件的背景层必须判「不可控」');

  assert.equal(bandOf(0, 'static'), 0, '非定位元素在 in-flow 块带');
  assert.equal(bandOf(-1, 'fixed'), -1, '负 z 的定位元素在负 z 步');
  assert.equal(bandOf(10, 'sticky'), 2, '正 z 在正文之上');
});
