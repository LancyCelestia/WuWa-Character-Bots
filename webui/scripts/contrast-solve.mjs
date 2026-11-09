// 对比度配平助手（一次性）：算出「要多少 L 才能过 4.5:1」，不猜。
//
// 为什么要算而不是调：oklch 的 L 不是线性亮度，肉眼看「差不多深」的两档可能差 1.5 倍
// 对比度。这里把 oklch→sRGB→WCAG 相对亮度走通，然后对每个候选值直接打印比值。
//
// 用法：node scripts/contrast-solve.mjs
const srgb = (c) => {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const lum = (r, g, b) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);

/** oklch → linear sRGB → 8-bit sRGB（Björn Ottosson 的标准矩阵）。 */
function oklchToRgb(L, C, hDeg) {
  const h = (hDeg * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  const lin = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return lin.map((v) => {
    const c = Math.max(0, Math.min(1, v));
    const s8 = c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055;
    return Math.round(s8 * 255);
  });
}

const WHITE = [255, 255, 255];
const show = (label, rgb) => {
  const L = lum(...rgb);
  console.log(`  ${label.padEnd(34)} rgb(${rgb.join(' ')})  L=${L.toFixed(4)}  对白 ${ratio(L, lum(...WHITE)).toFixed(2)}:1`);
  return L;
};

console.log('── 当前 --muted-foreground oklch(0.497 0.0441 273.4) ──');
const cur = oklchToRgb(0.497, 0.0441, 273.4);
show('现值', cur);

// 目标：与「面板提亮后的底色」对 4.5:1。
// 面板底 = color-mix(in srgb, --card 90%, transparent) 压在一张亮蓝壁纸上的结果。
// 实测壁纸透出的底色区间是 rgb(116~150, 120~162, 130~196)；取最坏（最亮）那一档
// rgb(150 162 196) 作为判据，因为最亮底色对浅字的对比度最低。
const WORST_BG = [150, 162, 196];
const PANEL_90 = [238, 240, 244]; // 90% card(oklch .988 .0017 247.8) 的近似合成值
console.log('\n── 候选 L（保 chroma/hue 不变）──');
for (const L of [0.50, 0.48, 0.46, 0.44, 0.42, 0.40, 0.38]) {
  const rgb = oklchToRgb(L, 0.0441, 273.4);
  const r1 = ratio(lum(...rgb), lum(...WORST_BG));
  const r2 = ratio(lum(...rgb), lum(...PANEL_90));
  console.log(`  L=${L.toFixed(2)}  rgb(${rgb.join(' ')})  最坏底色 ${r1.toFixed(2)}:1   面板底色 ${r2.toFixed(2)}:1`);
}

console.log('\n── 品牌蓝：白字要 4.5:1，需要多深 ──');
const candidates = [
  ['现 rgb(49 140 231)', [49, 140, 231]],
  ['rgb(40 118 200)', [40, 118, 200]],
  ['rgb(33 105 185)', [33, 105, 185]],
  ['rgb(28 94 168)', [28, 94, 168]],
  ['rgb(24 84 152)', [24, 84, 152]],
];
for (const [label, rgb] of candidates) show(label, rgb);

// 反解：白字 4.5:1 所需的最高亮度
console.log('\n── 反解：白字 4.5:1 允许的最亮背景 ──');
for (const target of [4.5, 4.6, 5.0]) {
  const L = 1.05 / target - 0.05;
  console.log(`  目标 ${target}:1 → 背景相对亮度上限 L=${L.toFixed(4)}（即 rgb 大约 ${Math.round(255 * Math.sqrt(L))} 灰阶）`);
}
