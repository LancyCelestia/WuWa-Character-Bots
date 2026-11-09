import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { applyAppearance, collectAppearanceVars } from './apply.ts';
import { cloneAppearance, DEFAULT_APPEARANCE, PALETTES, toHex, fromHex } from './defaults.ts';
import { applyDegrade, degradeReasons, probeSignature, type EnvironmentProbe } from './degrade.ts';
import { deserializeAppearance, normalizeAppearance, PRESETS, serializeAppearance } from './presets.ts';
import { clampRange, RANGES } from './schema.ts';
import { APPEARANCE_FIELDS } from './schema-fields.ts';
import type { AppearanceConfig } from './types.ts';

/**
 * 外观配置总线锁（UI3 追加二）。
 *
 * 判据住在 lib 而不是 .tsx：外观页每一行都在**声称**「这个滑块的数值会变成渲染结果」，
 * 断在组件里就等于没有判据。本文件零 DOM 依赖（假 root / 纯函数），node --test 直接加载。
 *
 * 三组硬锁：
 *   ① 17 组的字段清单与配置树同构（漏一组就是「设置里看不见」）；
 *   ② 每个字段都真的被 applyAppearance 写成 CSS 变量（否则滑块只动数字不动画面）；
 *   ③ 越界值必须被钳进界内（导入/降级/手改 JSON 三条路都要经过同一把尺）。
 */

// ---------- ① 17 组的形状 ----------

test('APPEARANCE_FIELDS 覆盖 17 组，每组 ≥3 项，且与配置树逐字段同构', () => {
  assert.equal(APPEARANCE_FIELDS.length, 17, '用户裁定：17 个分组一个都不能少');
  const ids = APPEARANCE_FIELDS.map((group) => group.id);
  assert.equal(new Set(ids).size, ids.length, '分组 id 不得重复');

  // 不由配置树承载的控件：file 的读/删由 provider 直接调 store；rules/bindings 是数组表，
  // 各有一块专用编辑区。它们仍然必须有中文标题与说明，只是不做反方向覆盖。
  const NON_TREE = new Set(['wallpaper.file', 'logView.rules', 'interaction.bindings']);

  for (const group of APPEARANCE_FIELDS) {
    assert.ok(group.title.trim().length > 0, `${group.id} 缺中文标题`);
    assert.ok(group.hint.trim().length > 0, `${group.id} 缺中文说明`);
    assert.ok(group.items.length >= 3, `${group.id} 只有 ${group.items.length} 项，用户要求每组至少 3 项`);

    const section = (DEFAULT_APPEARANCE as unknown as Record<string, unknown>)[group.section];
    assert.ok(section && typeof section === 'object', `${group.id} 的 section=${group.section} 不在配置树里`);

    // 组内每一项的 key 必须是它所在分节真实拥有的字段（含 targets.* 这种一层嵌套）。
    // 项级 section 覆盖：极少数项住在别的分节里但归本组管。
    for (const item of group.items) {
      const owner = item.section ?? group.section;
      const body = (DEFAULT_APPEARANCE as unknown as Record<string, unknown>)[owner] as Record<string, unknown>;
      assert.ok(body && typeof body === 'object', `${group.id}.${item.key} 的 section=${owner} 不在配置树里`);
      const known = new Set(flatKeys(body));
      if (NON_TREE.has(`${owner}.${item.key}`)) continue;
      assert.ok(known.has(item.key), `${owner}.${item.key} 不是配置字段（来自组 ${group.id}）`);
    }
  }

  // 反方向：配置树里的每个标量字段都必须能在某组里被找到（不许有「看不见的字段」）。
  const listed = new Set(
    APPEARANCE_FIELDS.flatMap((group) => group.items.map((item) => `${item.section ?? group.section}.${item.key}`))
  );
  const tree = new Set(flatSections(DEFAULT_APPEARANCE));
  const missing = [...tree].filter((key) => !listed.has(key));
  assert.deepEqual(missing, [], `配置树里有字段没进设置页：${missing.join(', ')}`);
});

test('每一项都有中文标题 + 讲清「调大了会怎样」的中文说明，控件类型齐备', () => {
  const kindsNeeded = new Set(['switch', 'slider', 'radio', 'segment', 'multi', 'number', 'file', 'color', 'select', 'text']);
  const seen = new Set<string>();
  for (const group of APPEARANCE_FIELDS) {
    for (const item of group.items) {
      assert.match(item.label, /[\u4e00-\u9fa5]/, `${group.id}.${item.key} 标题不是中文：${item.label}`);
      assert.match(item.help, /[\u4e00-\u9fa5]{6,}/, `${group.id}.${item.key} 说明太短或不是中文：${item.help}`);
      // 说明要讲清「调大了会怎样」——判据是**有后果描述**，不是必须出现「调大」二字：
      // 滑块类用「调大/调高/调小/调低…」，开关类用「开→/关掉/开启…」，
      // 选项类（单选/下拉）用「选错/太接近/太远/最省/会折行/掉帧…」表达后果，
      // 区间类用「超过/低于/至少/建议/范围」。四类都算数。
      assert.match(
        item.help,
        /→|调大|调高|调小|调低|调宽|调粗|调快|调慢|关掉|开启|留空|勾上|选错|超过|低于|至少|范围|建议|越大|越|太接近|太远|最|更|会|就|吃|变|丢|撑宽|折行|掉帧|卡|换它/,
        `${group.id}.${item.key} 的说明没有讲清「这样调会有什么后果」：${item.help}`
      );
      seen.add(item.control);
    }
  }
  for (const kind of kindsNeeded) {
    assert.ok(seen.has(kind), `用户点名的控件类型 ${kind} 没有一个字段在用`);
  }
});

test('色票只收已登记 token：每个 color 字段的 tokens 都在 defaults 的色板里', () => {
  const registered = new Set<string>();
  for (const palette of Object.values(PALETTES)) {
    for (const key of Object.keys(palette)) registered.add(key);
  }
  for (const tone of ['good', 'warn', 'bad', 'info', 'purple', 'magenta']) registered.add(tone);
  for (const group of APPEARANCE_FIELDS) {
    for (const item of group.items) {
      if (item.control !== 'color') continue;
      assert.ok(Array.isArray(item.tokens) && item.tokens.length > 0, `${group.id}.${item.key} 是色票但没有登记 token`);
      for (const token of item.tokens ?? []) {
        assert.ok(registered.has(token), `${group.id}.${item.key} 引用了未登记的 token：${token}`);
      }
      // 色票不许出现十六进制/任意色值——只能给 token 名。
      assert.doesNotMatch(JSON.stringify(item.tokens), /#[0-9a-f]{3}/i, `${group.id}.${item.key} 让用户手输了色值`);
    }
  }
});

// ---------- ② 每个字段都落到 CSS 变量 ----------

test('applyAppearance 把每个数值字段都写成 CSS 变量（滑块动 → 变量动）', () => {
  const vars = collectAppearanceVars(DEFAULT_APPEARANCE);
  const names = Object.keys(vars);
  assert.ok(names.length >= 60, `只写出 ${names.length} 个变量，覆盖不足`);
  for (const name of names) {
    assert.match(name, /^--(wp|au|ir|glow|glass|grain|mo|ty|fs|cfg|fx|ap|r|shell)-/, `${name} 不合命名约定`);
    const value = vars[name];
    assert.equal(typeof value, 'string');
    assert.ok(value.length > 0, `${name} 写成了空串`);
    assert.doesNotMatch(value, /\bNaN\b|\bInfinity\b|\bundefined\b/, `${name} 写出非法值 ${value}`);
  }

  // 相同输入 → 相同输出；改一个字段 → 恰好相关的变量变（不许有 stale 变量）。
  const tuned = cloneAppearance(DEFAULT_APPEARANCE);
  tuned.glass.blur = 4;
  tuned.typography.rootSize = 18;
  const after = collectAppearanceVars(tuned);
  assert.notEqual(after['--glass-blur'], vars['--glass-blur']);
  assert.notEqual(after['--ty-root'], vars['--ty-root']);
  assert.notEqual(after['--fs-body'], vars['--fs-body'], '正文字号必须真的改到消费变量');
  assert.equal(after['--au-speed'], vars['--au-speed'], '改玻璃不该动光斑');
});

test('「字体大小 / 圆角 / 间距」三轴都是运行时可写的 px，且各自落在被消费的变量上', () => {
  // 用户 2026-10-19：「字体大小、ui圆角、间距等全部改成自定义大小px」。
  // 这条锁判的是**链路**而不是数字：三轴的每一档都必须有对应的 CSS 变量被写出去，
  // 且那枚变量必须是样式表里真正消费的那个名字（不是历史死变量）。
  const tuned = cloneAppearance(DEFAULT_APPEARANCE);
  tuned.typography.pageSize = 21;
  tuned.typography.cardSize = 16;
  tuned.typography.rootSize = 15;
  tuned.typography.captionSize = 13;
  tuned.typography.numSize = 34;
  tuned.layout.radius = 26;
  tuned.layout.spacing = 1.5;
  const vars = collectAppearanceVars(tuned);

  // —— 字号：五档各一枚 ——
  assert.equal(vars['--fs-page'], '21px');
  assert.equal(vars['--fs-card'], '16px');
  assert.equal(vars['--fs-body'], '15px');
  assert.equal(vars['--fs-caption'], '13px');
  assert.equal(vars['--fs-num'], '34px');

  // —— 圆角：Tailwind 三档真身（--radius-md/lg/xl 指向它们）——
  assert.equal(vars['--r-panel'], '26px');
  assert.equal(vars['--r-shell'], '38px', '大窗 = 面板 + 12');
  assert.equal(vars['--r-tile'], '22px', '瓦片 = 面板 - 4');

  // —— 间距：三枚真实消费点一起缩放（缺省 1 倍 = 16/12/16）——
  // `--cfg-gap` 的出厂基数在 W13-V2 间距归一里从 12 抬到 16（见 apply.ts 该段注释与
  // index.css 的 `--cfg-gap: 16px`），所以 1.5 倍是 24px 而不是 18px。
  assert.equal(vars['--shell-gap'], '24px', '16 × 1.5');
  assert.equal(vars['--shell-inset'], '18px', '12 × 1.5');
  assert.equal(vars['--cfg-gap'], '24px', '16 × 1.5');

  // 样式表必须**真的消费**这些变量，否则滑块又变回「只动数字不动画面」。
  const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
  for (const name of ['--fs-page', '--fs-card', '--fs-body', '--fs-caption', '--fs-num']) {
    assert.ok(css.includes(`font-size: var(${name})`), `${name} 没有被 font-size 消费（字号滑块会空转）`);
  }
  for (const name of ['--r-panel', '--r-shell', '--r-tile']) {
    assert.ok(css.includes(`var(${name})`), `${name} 没有被消费（圆角滑块会空转）`);
  }
  for (const name of ['--shell-gap', '--shell-inset', '--cfg-gap']) {
    assert.ok(css.includes(name) || readFileSync(new URL('../../components/layout/app-shell.tsx', import.meta.url), 'utf8').includes(`var(${name})`), `${name} 没有任何消费方（间距滑块会空转）`);
  }
});

test('文本辉光已撤除：样式表里 text-shadow 归零，虹彩描边保留', () => {
  // 用户 2026-10-19：「文本不需要辉光」。虹彩**描边**是先前点名要的，必须还在。
  const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
  assert.equal((css.match(/text-shadow/g) ?? []).length, 0, '样式表里仍有 text-shadow（文字辉光）');
  assert.ok(css.includes('background-clip: text'), '关键数值的虹彩描边被误删了');
});

test('applyAppearance 对任何字段都是「只写属性、不抛错」的纯写入（可跑在假 root 上）', () => {
  const wrote: Array<[string, string]> = [];
  const root = {
    style: { setProperty: (name: string, value: string) => wrote.push([name, value]) },
  } as unknown as HTMLElement;
  applyAppearance(DEFAULT_APPEARANCE, root);
  assert.ok(wrote.length > 0);
  for (const [name, value] of wrote) {
    assert.equal(typeof name, 'string');
    assert.equal(typeof value, 'string');
  }
});

// ---------- ③ 界值钳制 ----------

test('clampRange 把越界值钳进界内并落到步长栅格', () => {
  assert.equal(clampRange(999, RANGES.glass.blur), RANGES.glass.blur.max);
  assert.equal(clampRange(-999, RANGES.glass.blur), RANGES.glass.blur.min);
  assert.equal(clampRange(Number.NaN, RANGES.glass.blur), RANGES.glass.blur.min);
  // 浮点毛刺必须落到同一格（0.30000000000000004 与 0.3 是同一个值）；
  // 它低于 aurora.speed 的下界 0.1 吗？不，但低于 motion.speed 的下界 0.5 → 钳到 0.5。
  assert.equal(clampRange(0.30000000000000004, RANGES.aurora.speed), 0.3);
  assert.equal(clampRange(0.30000000000000004, RANGES.motion.speed), RANGES.motion.speed.min);
  assert.equal(clampRange(1.15, RANGES.motion.speed), 1.1, '1.15 落在 1.1 与 1.2 之间，按就近落栅格');
  for (const value of [0, 12, 24, 36, 48]) {
    const clamped = clampRange(value, RANGES.glass.blur);
    assert.ok(clamped >= RANGES.glass.blur.min && clamped <= RANGES.glass.blur.max);
  }
});

// ---------- ④ 预设与导入导出 ----------

test('四套预设齐全、彼此视觉明显不同、且都是合法配置', () => {
  assert.deepEqual(PRESETS.map((preset) => preset.name), ['深海', '极简', '炫彩', '性能']);
  for (const preset of PRESETS) {
    assert.ok(preset.hint.trim().length > 0, `${preset.name} 缺中文说明`);
    const round = normalizeAppearance(preset.config);
    assert.equal(round.repaired, false, `${preset.name} 自己就不是合法配置：${JSON.stringify(round.config).slice(0, 80)}`);
  }
  const byName = new Map(PRESETS.map((preset) => [preset.name, preset.config]));
  const minimal = byName.get('极简')!;
  const vivid = byName.get('炫彩')!;
  const performance = byName.get('性能')!;
  assert.equal(minimal.aurora.enabled, false, '极简必须关光斑');
  assert.equal(minimal.iridescence.enabled, false, '极简必须关虹彩');
  assert.equal(vivid.aurora.count, 6, '炫彩必须把光斑拉满');
  assert.ok(vivid.glow.strength > minimal.glow.strength, '炫彩的辉光必须强于极简');
  assert.equal(performance.wallpaper.mode, 'none', '性能预设不许加载壁纸');
  assert.equal(performance.motion.enabled, false, '性能预设必须关动效');
  assert.equal(performance.scene3d.quality, 'low');
});

test('导入导出往返一致：导出 → 破坏 → 导入复原', () => {
  const tuned = cloneAppearance(DEFAULT_APPEARANCE);
  tuned.glass.blur = 6;
  tuned.layout.gridColumns = 3;
  tuned.logView.maxLines = 2000;
  tuned.notifications.soundEnabled = true;
  tuned.a11y.colorBlind = 'protanopia';
  const text = serializeAppearance(tuned);
  const back = deserializeAppearance(text);
  assert.equal(back.repaired, false);
  assert.deepEqual(back.config, tuned);
});

test('导入坏数据不炸：未知字段丢弃、越界钳住、类型错回落默认', () => {
  const dirty = {
    glass: { blur: 999, opacity: '很透明', extra: 1 },
    aurora: { count: -3, palette: '不存在的色板' },
    layout: { gridColumns: 99 },
    不该有的分组: { 随便: true },
    scene3d: { quality: '超高' },
  };
  const { config, repaired } = normalizeAppearance(dirty);
  assert.equal(repaired, true);
  assert.equal(config.glass.blur, RANGES.glass.blur.max);
  assert.equal(config.glass.opacity, DEFAULT_APPEARANCE.glass.opacity);
  assert.equal(config.aurora.count, RANGES.aurora.count.min);
  assert.equal(config.aurora.palette, DEFAULT_APPEARANCE.aurora.palette);
  assert.equal(config.layout.gridColumns, RANGES.layout.gridColumns.max);
  assert.equal(config.scene3d.quality, DEFAULT_APPEARANCE.scene3d.quality);
  assert.equal((config as unknown as Record<string, unknown>)['不该有的分组'], undefined);

  // 完全非对象 / 空串 / null 一律回落默认配置，且不抛。
  for (const junk of [null, undefined, 0, 'nope', [], true]) {
    const result = normalizeAppearance(junk);
    assert.ok(result.config.glass && result.config.layout, `junk=${String(junk)} 未回落默认`);
  }
  const brokenText = deserializeAppearance('{不是 JSON');
  assert.equal(brokenText.repaired, true);
  assert.deepEqual(brokenText.config, DEFAULT_APPEARANCE);
});

test('色票只收白名单 token：toHex/fromHex 往返，非法色不进来', () => {
  for (const palette of Object.values(PALETTES)) {
    for (const color of Object.values(palette)) {
      const hex = toHex(color);
      assert.match(hex, /^#[0-9a-f]{6}$/i, `${color} → ${hex} 不是十六进制`);
      assert.match(fromHex(hex), /^rgb\(\d+ \d+ \d+\)$/, 'fromHex 必须回到函数形');
    }
  }
  assert.equal(toHex('not-a-color'), 'not-a-color', '认不出的输入原样返回，不编造色值');
});

// ---------- ⑤ 三种自动降级 ----------

const CLEAN: EnvironmentProbe = { saveData: false, width: 1440, cores: 16, memoryGb: 16, coarsePointer: false };

test('降级三路各自可判：saveData / 窄屏 / 低核', () => {
  assert.deepEqual(degradeReasons(CLEAN), []);
  assert.deepEqual(degradeReasons({ ...CLEAN, saveData: true }), ['saveData']);
  assert.deepEqual(degradeReasons({ ...CLEAN, width: 390 }), ['narrow']);
  assert.deepEqual(degradeReasons({ ...CLEAN, cores: 2 }), ['lowPower']);
  assert.deepEqual(degradeReasons({ ...CLEAN, memoryGb: 4 }), ['lowPower']);
  assert.deepEqual(degradeReasons({ ...CLEAN, saveData: true, width: 390, cores: 2 }), ['saveData', 'narrow', 'lowPower']);
  // 探针全零 = 不可知 = 不降级（不许把「测不到」当成「很弱」）
  assert.deepEqual(degradeReasons({ saveData: false, width: 0, cores: 0, memoryGb: 0, coarsePointer: false }), []);
});

test('降级真的收窄数值，且不修改入参；用户覆盖后原样返回', () => {
  const original = cloneAppearance(DEFAULT_APPEARANCE);
  original.wallpaper.mode = 'video';
  const snapshot = JSON.stringify(original);

  const saveData = applyDegrade(original, { ...CLEAN, saveData: true }, false);
  assert.equal(saveData.config.wallpaper.mode, 'shader', '省流不许加载本地视频');
  assert.equal(saveData.config.aurora.count, 1);
  assert.equal(saveData.config.motion.enabled, false);
  assert.ok(saveData.notes.length > 0, '降级必须给人话提示');
  assert.equal(JSON.stringify(original), snapshot, 'applyDegrade 不得修改入参');

  const narrow = applyDegrade(original, { ...CLEAN, width: 390 }, false);
  assert.ok(narrow.config.glass.blur <= 12, '窄屏玻璃模糊必须压到 12px 以内');
  assert.ok(narrow.config.aurora.count <= 2);

  const lowPower = applyDegrade(original, { ...CLEAN, cores: 2 }, false);
  assert.equal(lowPower.config.motion.chartPath, false);
  assert.equal(lowPower.config.scene3d.quality, 'low');

  const overridden = applyDegrade(original, { ...CLEAN, saveData: true, width: 390 }, true);
  assert.equal(overridden.config.wallpaper.mode, 'video', '用户覆盖后必须满血');
  assert.equal(overridden.notes.length, 0);
});

test('降级指纹：同机同档才算覆盖，换环境重新征求', () => {
  assert.equal(probeSignature(CLEAN), probeSignature({ ...CLEAN }));
  assert.notEqual(probeSignature(CLEAN), probeSignature({ ...CLEAN, width: 390 }));
  assert.notEqual(probeSignature(CLEAN), probeSignature({ ...CLEAN, saveData: true }));
});

// ---------- ⑥ 样式表兜底值与配置默认值同值 ----------

test('index.css 的首帧兜底与 DEFAULT_APPEARANCE 同值（否则刷新瞬间皮肤会跳一下）', () => {
  const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
  const vars = collectAppearanceVars(DEFAULT_APPEARANCE);
  // 只认「裸 :root 块」里的定义：`[data-contrast]` / `[data-cb]` / `[data-motion]` 这类
  // **用户触发的覆盖段**本来就会改同一批变量（高对比态当然不该等于默认态），
  // 把它们算进来等于要求「覆盖态必须退回默认」，是错的。
  //
  // 解析必须是**选择器感知 + 花括号配平**的：早先那版用
  // `/^:root\s*\{([\s\S]*?)^\}/gm` 懒匹配，只要某个 `:root` 块以缩进收尾，
  // 捕获就会一路吞到后面 `:root[data-contrast='high']` 的 `--glass-alpha: 0.96`，
  // 把高对比覆盖误判成首帧兜底（红的是解析器，不是样式表）。
  const rootBlocks = bareRootBlocks(css).join('\n');
  const readVar = (name: string): string | null => {
    const all = [...rootBlocks.matchAll(new RegExp(`^\\s*${name}:\\s*([^;]+);`, 'gm'))];
    return all.length ? all[all.length - 1][1].trim() : null;
  };
  const numeric = Object.keys(vars).filter((name) => /^-?[\d.]+(px|deg|s|%)?$/.test(vars[name]));
  assert.ok(numeric.length > 40, '可比的数值变量太少，锁没有意义');
  for (const name of numeric) {
    const cssValue = readVar(name);
    if (cssValue === null) continue; // 只在运行时存在的变量（如派生量）不参与本锁
    assert.equal(
      cssValue.replace(/\s+/g, ''),
      vars[name].replace(/\s+/g, ''),
      `${name} 兜底 ${cssValue} ≠ 默认 ${vars[name]}`
    );
  }
});

test('index.css 不留写死的特效数值：模糊/透明度/时长全部走变量', () => {
  const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
  const lines = css.split('\n');
  // 允许的三类例外（都不是「用户想调的那类值」）：
  //   ① @keyframes 体内的端点值——动画的起止定义，不是可调参数；
  //   ② @media / @layer 包裹与 prefers-* 查询；
  //   ③ 变量定义行本身就是值册（--x: 0.78 是兜底值，不是硬编码）。
  const offenders: string[] = [];
  let depth = 0;
  let inKeyframes = false;
  for (const [index, line] of lines.entries()) {
    if (/@keyframes/.test(line)) {
      inKeyframes = true;
      depth = 0;
    }
    if (inKeyframes) {
      // 括号深度归零即 keyframes 块结束（内层 from/to 的 `}` 有缩进，不能靠行首判）。
      depth += (line.match(/\{/g) ?? []).length - (line.match(/\}/g) ?? []).length;
      if (depth <= 0 && /\}/.test(line) && !/@keyframes/.test(line)) {
        inKeyframes = false;
      }
      continue;
    }
    if (/^\s*(\/\*|\*)/.test(line)) continue;
    if (/@media/.test(line)) continue;
    // ④ 能力检测查询：`@supports not (backdrop-filter: blur(1px))` 里的 1px
    //    按定义就是**任意非零探针**（换成 2px 语义完全一样），它不是用户想调的
    //    模糊半径。判它在场等于要求「给特性检测也建一个可调 token」，那是假的严格。
    //    实际消费的模糊半径仍全部走 --glass-blur / --mica-blur / --glow-blur，未放松。
    if (/@supports/.test(line)) continue;
    if (/--[\w-]+\s*:/.test(line)) continue;
    for (const match of line.matchAll(/\bblur\((\d+(?:\.\d+)?)px\)/g)) {
      if (match[1] !== '0') offenders.push(`${index + 1}: ${line.trim()}`);
    }
    for (const match of line.matchAll(/\bopacity:\s*0\.\d+/g)) {
      offenders.push(`${index + 1}: ${match[0]} @ ${line.trim()}`);
    }
  }
  assert.deepEqual(offenders, [], `样式表里仍有写死的特效数值：\n${offenders.join('\n')}`);
});

// ---------- 工具 ----------

/**
 * 取出样式表里所有**裸 `:root` 块**的块体（不含选择器）。
 *
 * 判据两条，缺一不可：
 *   ① 选择器必须恰好是 `:root`——`:root[data-contrast='high']` 这类带条件的是覆盖段，不算兜底；
 *   ② 块体按**花括号配平**截取，绝不靠「下一行行首的 `}`」猜边界。
 *
 * 第 ② 条是这一版修的精度 bug：旧实现用懒匹配 `^\}` 收尾，只要块尾缩进就吞掉后续规则，
 * 把高对比覆盖里的 `--glass-alpha: 0.96` 当成 `:root` 兜底，误报「兜底 ≠ 默认」。
 */
function bareRootBlocks(css: string): string[] {
  const out: string[] = [];
  const header = /:root\s*\{/g;
  for (const match of css.matchAll(header)) {
    const selectorStart = css.lastIndexOf('\n', match.index) + 1;
    const selector = css.slice(selectorStart, match.index).trim();
    if (selector !== '') continue; // 行首还挂着别的东西 = 不是裸 :root
    // 配平取块体
    const open = match.index + match[0].length - 1;
    let depth = 0;
    let end = -1;
    for (let i = open; i < css.length; i++) {
      if (css[i] === '{') depth++;
      else if (css[i] === '}') {
        depth--;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    if (end > open) out.push(css.slice(open + 1, end));
  }
  return out;
}

function flatKeys(value: Record<string, unknown>, prefix = ''): string[] {
  const out: string[] = [];
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) out.push(...flatKeys(child as Record<string, unknown>, path));
    else out.push(path);
  }
  return out;
}

function flatSections(config: AppearanceConfig): string[] {
  const out: string[] = [];
  for (const [section, body] of Object.entries(config)) {
    for (const key of flatKeys(body as Record<string, unknown>)) out.push(`${section}.${key}`);
  }
  return out;
}
