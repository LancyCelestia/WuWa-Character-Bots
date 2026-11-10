// 外观「写了必须有人读」棘轮（W13 执行席 L）。
//
// 这一族失效的共同形态：`lib/appearance/apply.ts` 把配置值写进 `<html>` 的自定义属性，
// 样式表里却**没有任何 `var(--x)` 读者** —— 于是滑块拖到底，画面一动不动，控制台也不报错。
// 用户看到的是「外观设置改了没反应」，代码看到的是「35 枚变量零消费」。
//
// 静态扫描能判它，所以把它做成机器门，而不是再写一遍「本波已接好」的散文：
//   ① 每一枚 apply.ts 写出的变量，要么有 var() 读者，要么在冗余账里写清由谁承担；
//   ② 接线账逐条断言「变量 → 具体声明」—— 删掉那条声明就红；
//   ③ 两条曾经零定义的 token（发丝描边 / 顶沿高光）必须真的有定义；
//   ④ 两个「类名不存在」的静默失效：已撤除的文字辉光仍被引用、发丝色从未注册。
//
// ⚠️ 本文件的写法受版式宪法 ⑩ 约束：源码里**不许出现 `--名:` 这种字面形态**
//    （会被判成「自定义属性写入」V1/V2）。所以期望声明一律用 decl() 在运行时拼。
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..');

const APPLY = join(SRC, 'lib', 'appearance', 'apply.ts');
const WIRING_CSS = join(SRC, 'components', 'appearance', 'appearance-wiring.css');
const PREVIEW = join(SRC, 'components', 'appearance', 'preview.tsx');
const PATTERNS = join(SRC, 'components', 'patterns', 'patterns.tsx');
const PAGE = join(SRC, 'pages', 'appearance.tsx');
const MAIN = join(SRC, 'main.tsx');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (['.ts', '.tsx', '.css'].includes(extname(path))) out.push(path);
  }
  return out;
}

const read = (path: string) => readFileSync(path, 'utf8');

/**
 * 整棵树，剔掉两类「假读者」：
 *   · apply.ts —— 它写变量，不算读者；
 *   · 全部 *.test.ts —— 测试自己写着期望片段；不剔掉的话 includes(...) 恒真，
 *     一整排断言会在实现一行未写时齐刷刷变绿（本文件第一版实测如此）。
 */
const TREE = walk(SRC)
  .filter((path) => path !== APPLY && !/\.test\.(ts|tsx)$/.test(path))
  .map(read)
  .join('\n');
/** 空白归一后的整棵树：断言「变量 → 声明」时不受换行/缩进影响。 */
const NORM = TREE.replace(/\s+/g, ' ');

/** 运行时拼一条声明片段（源码里不出现 `--名:` 字面形态，见文件头）。 */
const decl = (property: string, value: string): string => `${property}: ${value}`;

/** apply.ts 真正写出的变量名册（只认 `set('--x'` 形态；改写法扫描自然失效=红）。 */
const WRITTEN = [...new Set([...read(APPLY).matchAll(/set\('(--[a-z0-9-]+)'/g)].map((m) => m[1]))].sort();

/**
 * 登记为「不需要 var() 读者」的变量：每一条都必须说清**谁来承担同一语义**。
 * 空理由、「以后再接」一律不算 —— 那正是本波要根除的形态。
 */
const REDUNDANT: Array<[string, string]> = [
  ['--wp-opacity', '同值孪生：--wp-scrim 承担同一语义，压暗罩读后者'],
  ['--ir-speed', '派生输入：--ir-dur = 9/speed，虹彩时长读 --ir-dur'],
  ['--mo-alpha', '同值孪生：--mo-play 承担同一语义，动画层读后者'],
  ['--wp-playback', '非 CSS 语义：BackgroundStage 直接赋 video.playbackRate'],
  ['--au-count', '纯 CSS 表达不了节点数（apply.ts 自注）：消费者是 AmbientGlow 依配置渲染的光斑个数'],
  ['--cfg-contrast-boost', '同一语义由 <html data-contrast="high"> 承载（apply.ts 落属性）'],
  ['--cfg-force-reduce', '同一语义由 <html data-motion="off"> 承载（apply.ts 落属性）'],
  ['--cfg-saver', '同一语义由 <html data-saver="1"> 承载（apply.ts 落属性）'],
  ['--ir-hue-range', '色相跨度要重写虹彩渐变配方（在 index.css 值册），列需 index.css 独占席'],
  ['--cfg-side', '侧栏左右侧要靠布局逻辑，不是一枚 CSS 值'],
  ['--cfg-header-glass', '顶栏玻璃由 window 毯子的云母模糊承担，列需 index.css 独占席'],
  ['--cfg-radius', '历史别名：真正生效的是圆角三档 --r-panel/--r-shell/--r-tile'],
];
const REDUNDANT_NAMES = new Set(REDUNDANT.map(([name]) => name));

test('apply.ts 写出的每一枚变量都有人读（或登记了由谁承担同一语义）', () => {
  const dead = WRITTEN.filter((name) => !TREE.includes(`var(${name})`) && !REDUNDANT_NAMES.has(name));
  assert.deepEqual(
    dead,
    [],
    `以下变量被 apply.ts 写出但全树没有 var() 读者 ⇒ 对应滑块是死的：${dead.join(' ')}\n` +
      '接上消费端，或在冗余账里写清「谁承担同一语义」。'
  );
});

test('冗余账里不许留「其实已经接了」的变量（登记行必须随实现一起删）', () => {
  const stale = REDUNDANT.filter(([name]) => TREE.includes(`var(${name})`)).map(([name]) => name);
  assert.deepEqual(stale, [], `以下变量已经有 var() 读者，登记行应删除：${stale.join(' ')}`);
});

/**
 * 接线账：变量 → 它真正驱动的那条声明（空白已归一）。
 * 每一条都能被单独打断：删/改那条声明，本用例当场红。
 */
const WIRING: Array<[string, string]> = [
  // 品牌六色 → 语义面（「配色切换」曾经 100% 不生效）
  ['--ap-brand', decl('--brand-accent', 'var(--ap-brand)')],
  ['--ap-purple', decl('--sk-purple', 'var(--ap-purple)')],
  ['--ap-deep', decl('--sk-deep', 'var(--ap-deep)')],
  ['--ap-success', decl('--tone-good', 'var(--ap-success)')],
  ['--ap-warning', decl('--tone-warn', 'var(--ap-warning)')],
  ['--ap-danger', decl('--tone-bad', 'var(--ap-danger)')],
  // 光斑：自定义三色 / 开关 / 混合 / 速度
  [
    '--au-a',
    decl('background', 'radial-gradient(circle, color-mix(in srgb, var(--au-a) 30%, transparent) 0%, transparent 68%)'),
  ],
  [
    '--au-b',
    decl('background', 'radial-gradient(circle, color-mix(in srgb, var(--au-b) 26%, transparent) 0%, transparent 66%)'),
  ],
  [
    '--au-c',
    decl('background', 'radial-gradient(circle, color-mix(in srgb, var(--au-c) 24%, transparent) 0%, transparent 70%)'),
  ],
  ['--au-display', decl('display', 'var(--au-display)')],
  ['--au-blend', decl('mix-blend-mode', 'var(--au-blend)')],
  ['--au-speed', decl('animation-duration', 'calc(28s / var(--au-speed))')],
  // 虹彩：时长 / 线宽 / 透明度
  ['--ir-dur', decl('animation-duration', 'var(--ir-dur)')],
  ['--ir-width', decl('height', 'var(--ir-width)')],
  ['--ir-alpha', 'color-mix(in srgb, var(--brand-accent) calc(var(--ir-alpha) * 100%), transparent)'],
  // 辉光：颜色 / 半径 / 强度
  ['--glow-color', 'color-mix(in srgb, var(--glow-color) calc(var(--glow-alpha) * 100%), transparent)'],
  ['--glow-r', '0 0 var(--glow-r)'],
  ['--glow-alpha', '0 0 var(--glow-r) color-mix(in srgb, var(--glow-color) calc(var(--glow-alpha) * 100%), transparent)'],
  // 玻璃：不透明度 / 描边强度 / 抬升
  ['--glass-alpha', 'calc(var(--glass-alpha) * 100%)'],
  ['--glass-border', 'calc(var(--glass-border) * 32%)'],
  ['--glass-elev', 'calc(var(--glass-elev) * 1.8) calc(var(--glass-elev) * 4)'],
  // 排版 / 动效
  ['--ty-track', decl('letter-spacing', 'var(--ty-track)')],
  ['--ty-weight', 'var(--ty-weight)'],
  ['--mo-play', decl('animation-play-state', 'var(--mo-play)')],
];

for (const [name, drives] of WIRING) {
  test(`${name} 已接到消费端`, () => {
    assert.ok(TREE.includes(`var(${name})`), `${name} 全树零读者`);
    assert.ok(NORM.includes(drives.replace(/\s+/g, ' ')), `找不到「${drives}」⇒ ${name} 只是被写着，没有真正驱动画面`);
  });
}

test('--au-count 的消费方是 ambient-backdrop 的渲染数量（节点数 CSS 表达不了）', () => {
  const src = read(join(SRC, 'components', 'backdrop', 'ambient-backdrop.tsx'));
  assert.match(src, /effective\.aurora\.count/, 'AmbientGlow 没按配置决定光斑个数 ⇒ 个数滑块是死的');
  assert.match(src, /BLOB_LAYOUTS\.slice\(0, count\)/, '光斑节点没有按 count 裁剪');
});

test('发丝描边与顶沿高光必须有定义（曾全树零定义 ⇒ 描边与品牌标呼吸静默失效）', () => {
  for (const name of ['--hairline', '--inner-top']) {
    assert.match(TREE, new RegExp(`${name}\\s*:`, 'm'), `${name} 被消费却零定义 ⇒ 整条声明失效`);
  }
});

test('发丝色必须真的产出两条工具类与一个色 token', () => {
  const css = read(WIRING_CSS);
  // 跨文件 @theme **不生成工具类**（本波 build 实测）⇒ 必须显式补两条类；
  // 只注册 --color-hairline 是「看起来接了、实际仍是空的」。
  assert.ok(css.includes('--color-hairline'), '发丝色未注册成 Tailwind 色');
  assert.match(css, /\.border-hairline\s*\{[^}]*border-color:[^}]*var\(--hairline\)/, '没有补 border-hairline 类');
  assert.match(css, /\.ring-hairline\s*\{[^}]*--tw-ring-color:[^}]*var\(--hairline\)/, '没有补 ring-hairline 类');
});

test('已撤除的文字辉光 utility 不许再出现在调用方', () => {
  assert.ok(!/glow-value/.test(read(PATTERNS)), '文字辉光已撤除，类名留在 JSX 里＝一句谎');
});

test('接线样式表必须被入口真正引入（否则整份规则不参与构建）', () => {
  assert.ok(read(MAIN).includes('appearance-wiring.css'), 'main.tsx 没有 import appearance-wiring.css');
});

test('外观页把**过滤后**的分组交给右侧（搜索曾只过滤左栏）', () => {
  assert.ok(
    /<AppearanceGroups\s+groups=/.test(read(PAGE)),
    '右侧渲染的是全量分组而非过滤结果 ⇒ 搜索只影响左栏目录'
  );
});

test('右侧预览栏真的挂在页面上，且吃的是同一批变量', () => {
  assert.match(read(PAGE), /<AppearancePreview\s*\/>/, '外观页没有挂预览栏 ⇒ 右侧仍是空白');
  const src = read(PREVIEW);
  for (const probe of ['ap-preview-wall', 'var(--ty-weight)', 'useWallpaperObjectUrl', 'wallpaperOwner']) {
    assert.ok(src.includes(probe), `预览栏没有读取 ${probe} ⇒ 它是假图，不是同一批变量的第二个观察窗`);
  }
  const css = read(WIRING_CSS);
  for (const probe of ['scale(var(--wp-scale))', 'blur(var(--wp-blur))', 'var(--ap-brand)']) {
    assert.ok(css.includes(probe), `预览框样式没有消费 ${probe} ⇒ 壁纸滤镜与配色不会跟着滑块变`);
  }
});

test('接线样式表不写受管声明带（字号/圆角/间距一律用具名类）', () => {
  const css = read(WIRING_CSS);
  const forbidden = [/font-size\s*:/, /font-weight\s*:/, /border-radius\s*:/, /(^|\W)(padding|margin|gap)\s*:/];
  for (const pattern of forbidden) {
    assert.ok(!pattern.test(css), `接线样式表出现受管声明带：${pattern} —— 请改用字号档 / 圆角档 / 4px 栅格类`);
  }
  assert.ok(read(join(SRC, 'index.css')).length > 0);
});
