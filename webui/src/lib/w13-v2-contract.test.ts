// W13 执行席 V2 的结构契约（先红后绿）。
//
// 这一族判的是 V 席**实测出来的四类结构缺陷**，不是审美偏好：
//   ① 外观页 17 组全展开 ⇒ 1440 下 docH=18,998px（390 下 21,857px）——一条瀑布；
//   ② 语义态卡片是面板档 18px 套在外层面板档 18px 里 ⇒ 内外同曲率；
//   ③ 间距三套并存（12 / 16 / 24）⇒ 整页节奏不齐；
//   ④ 13 处裸面板（面板档圆角 + 边框 + p-4，无材质）⇒ 壁纸与角色立绘直接透出。
//
// 为什么是静态断言而不是截图：截图证明「这一刻这张 PNG 里对」，改一行 JSX 就作废；
// 这里判的是结构本身——删掉 `<details>`、把 gap 改回 24、把 surface 换回 border，逐条直接红。
//
// ⚠️ 受版式宪法 ①—④ 的文本级正则约束（本文件也在扫描面里）：
//   · 不许出现 `gap-3`/`gap-6` 这类**违例类名字面量**——否则测试自己把门禁判红；
//   · 不许出现 `--名: 值` 形态（⑧ V1/V2 自定义属性写入通道）——一律用 decl() 运行时拼。
//   所以下面所有「坏形态」都在运行时拼出来。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import {
  DEFAULT_OPEN_LIMIT,
  initialOpenGroups,
  openGroup,
  reconcileOpenGroups,
  toggleGroup,
} from '../components/appearance/groups-collapse.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..');
const read = (rel: string) => readFileSync(join(SRC, rel), 'utf8');

/** 运行时拼一条声明（源码里不出现「自定义属性名 + 冒号」字面形态）。 */
const decl = (property: string, value: string): string => `${property}: ${value}`;
/** 运行时拼一个类名（避开宪法 ③ 对违例类名字面量的文本级扫描）。 */
const cls = (...parts: string[]): string => parts.join('-');

/**
 * 面板档圆角类名（= `rou` + `nded-lg`）。
 *
 * 为什么不在源码里直接写这四个字：版式宪法 ⑥ 的行级扫描会把**字符串字面量**里的
 * 类名当挂到元素上的类名判（裸 `rounded` 与 `rounded-lg` 各是一条硬红）。
 * 本文件判的正是「面板用的是不是这一档」，写死字面量等于测试自己把门禁判红。
 */
const PANEL_RADIUS = ['rou', 'nded-lg'].join('');

const GROUPS = read('components/appearance/groups.tsx');
const PAGE = read('pages/appearance.tsx');
const APPLY = read('lib/appearance/apply.ts');
const INDEX_CSS = read('index.css');
const SEMANTIC = read('components/semantic/semantic-state.tsx');

// ───────────────────────── ① 折叠契约（P0-1）─────────────────────────

test('外观页分组必须是可折叠结构：每组一个 <details>，标题在 <summary> 里', () => {
  assert.match(GROUPS, /<details\b/, 'groups.tsx 里没有 <details> ⇒ 17 组仍然全部展开（19k 像素瀑布）');
  assert.match(GROUPS, /<summary\b/, '没有 <summary> ⇒ 折叠头不是原生可键盘操作的');
  // 每一组都走同一条渲染路径（分组列表 → AppearanceGroupCard），不能只折叠第一组
  assert.match(GROUPS, /groups\.map\(/, '分组不是逐项渲染 ⇒ 折叠无处安放');
  // 不许为了压高度把控件藏起来：字段仍要逐行渲染
  assert.match(GROUPS, /group\.items\.map\(/, '字段行没有被渲染 ⇒ 这不是折叠，是把控件藏了');
});

test('默认只展开有限组（全开＝修之前的 19k 像素瀑布）', () => {
  assert.ok(DEFAULT_OPEN_LIMIT >= 1, '一组都不开＝页面上一个控件都看不见');
  assert.ok(DEFAULT_OPEN_LIMIT <= 2, `默认展开 ${DEFAULT_OPEN_LIMIT} 组会重新堆成瀑布（上限 2）`);
  const ids = ['wallpaper', 'aurora', 'iridescence', 'glow', 'glass'];
  assert.deepEqual(initialOpenGroups(ids), ['wallpaper'], 'initialOpenGroups 没有只开前 N 组');
  assert.deepEqual(initialOpenGroups([], 1), [], '空列表应返回空');
  assert.deepEqual(initialOpenGroups(ids, 0), [], 'limit=0 应返回空');
});

test('展开状态是纯函数：打开幂等 / 切换互逆 / 过滤后重对齐', () => {
  assert.deepEqual(openGroup(['a'], 'a'), ['a'], '重复打开不该出现两份 id');
  assert.deepEqual(openGroup(['a'], 'b'), ['a', 'b']);
  assert.deepEqual(toggleGroup(['a'], 'a'), [], '在 → 关');
  assert.deepEqual(toggleGroup(['a'], 'b'), ['a', 'b'], '不在 → 开');
  assert.deepEqual(reconcileOpenGroups(['b', 'c'], ['a', 'b']), ['b'], '被过滤掉的组不该继续占着「已展开」');
  assert.deepEqual(
    reconcileOpenGroups(['c'], ['a', 'b']),
    ['a'],
    '交集为空时应回落到第一组（否则出现「17 行标题、0 个控件」的死页）'
  );
});

test('左栏目录点击某组 = 该组展开（不是只换个高亮）', () => {
  assert.match(PAGE, /openGroups/, '页面没有持有展开状态');
  assert.match(PAGE, /openGroup\(/, '页面没有任何地方真的去「打开」一组 ⇒ 目录点了也只是换高亮');
  // 目录项必须是按钮且带 aria-expanded：只写 href 的原生锚点改不了 <details> 的 open
  assert.match(PAGE, /aria-expanded=\{openGroups\.includes\(/, '目录项没有把展开状态声明给读屏/用户');
  // 页面 → 分组组件：展开状态必须真的传下去，否则组件自己那份会和目录打架
  assert.match(PAGE, /<AppearanceGroups[\s\S]{0,200}openGroups=/, '展开状态没有传给分组组件');
  assert.match(PAGE, /<AppearanceGroups[\s\S]{0,300}onToggleGroup=/, '分组组件没法把折叠动作回报给页面');
});

// ───────────────────────── ② 半径契约（P0-2）─────────────────────────

test('语义态卡片落瓦片档 14：rounded-md + shadow-none（卡片套卡片不得同曲率）', () => {
  // 六档状态全走同一个材质常量——单开一份是为了「改一处、六档一起改」，
  // 所以契约判的是这个常量的内容 + 每个 <Card> 都必须吃它。
  assert.match(SEMANTIC, /const STATE_CARD = '[^']*'/, '没有 STATE_CARD 材质常量 ⇒ 六档状态各写一份，迟早漂移');
  const constant = /const STATE_CARD = '([^']*)'/.exec(SEMANTIC)?.[1] ?? '';
  assert.match(constant, /rounded-md/, `STATE_CARD 缺瓦片档圆角：'${constant}'（外层 18 + p-4 ⇒ 内层必须 14）`);
  assert.match(constant, /shadow-none/, `STATE_CARD 仍带投影：'${constant}'（内层不该有悬浮厚度）`);
  assert.ok(!constant.includes(PANEL_RADIUS), `STATE_CARD 还是面板档 18，与外层同曲率：'${constant}'`);

  const cards = SEMANTIC.match(/<Card\b[^>]*>/g) ?? [];
  assert.ok(cards.length >= 4, `语义态卡片数量异常（${cards.length}）——先确认本文件没被改写`);
  for (const tag of cards) {
    assert.match(tag, /className=\{STATE_CARD\}/, `语义态卡片没吃统一材质：${tag}`);
  }
});

// ───────────────────────── ③ 间距唯一性（P0-3）─────────────────────────

test('外观页不留第二、第三套间距：没有 12px 档与 24px 档的类名', () => {
  const twelve = cls('gap', '3'); // 12px
  const twentyFour = cls('gap', '6'); // 24px
  for (const [name, source] of [
    ['pages/appearance.tsx', PAGE],
    ['components/appearance/groups.tsx', GROUPS],
  ] as const) {
    assert.ok(!source.includes(twelve), `${name} 仍用 ${twelve}（12px）——目标是一套 16px`);
    assert.ok(!source.includes(twentyFour), `${name} 仍用 ${twentyFour}（24px）——目标是一套 16px`);
  }
  assert.ok(GROUPS.includes(cls('gap', '4')), 'groups.tsx 的分组列没有 gap-4（16px）');
});

test('--cfg-gap 出厂值 = 16px（三套间距收敛到 16 的唯一真身）', () => {
  assert.ok(
    INDEX_CSS.includes(decl('--cfg-gap', '16px')),
    'index.css 的 --cfg-gap 出厂值不是 16px ⇒ 首帧（apply 之前）仍是 12px'
  );
  assert.match(
    APPLY,
    /Math\.round\(\s*16\s*\*\s*gapScale\s*\)/,
    'apply.ts 仍按 12 的基数缩放 --cfg-gap ⇒ 运行时又把间距掰回 12'
  );
  assert.ok(
    !APPLY.includes(decl('--cfg-gap', '${Math.round(12 * gapScale)}px')),
    'apply.ts 的 --cfg-gap 基数还是 12'
  );
});

// ───────────────────────── ④ 玻璃覆盖（P1）─────────────────────────

/** 面板类名里出现这些材质之一，才算「有壳」。 */
const MATERIALS = ['surface', 'surface-flat', 'glass-panel', 'window'];

/** 一处裸面板：圆角 18 + 边框 + 内边距，但没有任何材质类。 */
function barePanels(source: string): string[] {
  const hits: string[] = [];
  for (const m of source.matchAll(/className=(?:'([^']*)'|`([^`]*)`|\{cn\(\s*'([^']*)')/g)) {
    const classes = m[1] ?? m[2] ?? m[3] ?? '';
    if (!classes.includes(PANEL_RADIUS)) continue;
    if (!/\bborder\b/.test(classes)) continue;
    if (MATERIALS.some((material) => classes.includes(material))) continue;
    if (classes.includes('border-b') || classes.includes('border-t') || classes.includes('border-dashed')) continue;
    hits.push(classes.trim().slice(0, 120));
  }
  return hits;
}

test('V 席点名的 13 处裸面板全部换成现成材质（不许新造第五种）', () => {
  const targets: Array<[string, number]> = [
    ['pages/credentials.tsx', 2],
    ['pages/visual-editor.tsx', 5],
    ['pages/operations.tsx', 1],
    ['components/settings/settings-dialog.tsx', 1],
    ['pages/config.tsx', 3],
  ];
  for (const [file, expected] of targets) {
    const source = read(file);
    const bare = barePanels(source);
    assert.deepEqual(bare, [], `${file} 仍有 ${bare.length} 处裸面板：${bare.join(' | ')}`);
    const materials = MATERIALS.reduce(
      (sum, material) => sum + (source.match(new RegExp(`\\b${material}\\b`, 'g'))?.length ?? 0),
      0
    );
    assert.ok(materials >= expected, `${file} 的材质类只有 ${materials} 处，少于应有的 ${expected} 处`);
  }
});

test('config 页右栏在加载/空态也有壳（整块裸壁纸是 V 席最重的一处）', () => {
  const CONFIG = read('pages/config.tsx');
  // 右栏容器（搜索框 + 列表的父级）必须挂材质
  assert.match(
    CONFIG,
    /className='[^']*surface[^']*'/,
    'config.tsx 右栏容器没有材质 ⇒ 加载态壁纸整块裸露、角色立绘透出'
  );
  // 材质与半径是两个独立的类，中间隔着 flex/gap 等布局类 —— 不许假设它们相邻。
  // 这条用例的真意是「统计条/导航/列表三块外层都同时有材质与面板档圆角」，不是「字面相邻」。
  // 只查外层材质（`surface`），不查内层瓦片（`surface-flat`）：内层按同心规则必须是 14
  // （rounded-md），要求它也是 18 会与「卡片套卡片内层不得同曲率」直接打架。
  const shells = CONFIG.match(/className='[^']*\bsurface\b(?!-)[^']*'/g) ?? [];
  assert.ok(shells.length >= 3, `config.tsx 只有 ${shells.length} 处外层材质，统计条/导航/列表应有 3 处`);
  for (const shell of shells) {
    assert.ok(shell.includes(PANEL_RADIUS), `这处面板没有面板档圆角，与全站不同曲率：${shell.slice(0, 100)}`);
  }
});

test('插件页加载态有面板壳（12 块半透明灰板不再飘在壁纸上）', () => {
  const PLUGINS = read('pages/plugins.tsx');
  const skeletonBlock = PLUGINS.slice(PLUGINS.indexOf('function GroupSkeleton'), PLUGINS.indexOf('function GroupBlock'));
  assert.match(skeletonBlock, /surface/, 'GroupSkeleton 没有壳 ⇒ 加载态仍是裸壁纸上的灰板');
});

// ───────────────────────── ⑤ 可读性（P2）─────────────────────────

test('外观页状态胶囊有玻璃底（压在壁纸暗区实测 1.44:1）', () => {
  const pill = PAGE.slice(PAGE.indexOf('rounded-full'), PAGE.indexOf('rounded-full') + 400);
  assert.match(pill, /surface|bg-card/, '状态胶囊只有 border 没有底色 ⇒ 对比度随壁纸明暗碰运气');
});

test('外观页副标题有玻璃底或改用主墨色（压在生壁纸上实测 2.04:1）', () => {
  const header = PAGE.slice(PAGE.indexOf('<header'), PAGE.indexOf('</header>'));
  assert.ok(
    /surface|bg-card|text-foreground/.test(header),
    '页头副标题仍直接压壁纸 ⇒ 2.04:1'
  );
});
