// 分层模型（纯函数，零 DOM 依赖）：把「CSS 绘制序」折成可断言的带位（band）。
//
// 为什么要有这个文件：背景层用负 z-index 躺在正文下方，这件事**没有任何 CSS 门禁在守**——
// 版式宪法只管色值/字号/圆角/栅格，管不到层叠。负 z 层的实际落点完全由「最近的层叠上下文」
// 决定，而那个上下文今天离它们隔了两层祖先（#root）。一旦中间任何一层拿到 transform /
// filter / opacity < 1 / backdrop-filter，负层就换上下文；反过来说，只要给它们包一层容器，
// 容器自己的 z-index 就决定了整组的上下——**容器取 0 就等于把背景抬到 static 正文之上**
// （position 非 static + z-index:0 画在 in-flow 非定位块之后，见 CSS2.1 附录 E 的第 8 步）。
//
// 所以这里的判据只有一个：容器必须落在「负 z 步」，层必须在容器里。
//
// 带位（band）约定 = CSS2.1 附录 E 里与本缺陷相关的四步：
//   -1 负 z 步      ← 背景层该在这
//    0 in-flow 块   ← 正文/卡片/静态列在这
//    1 定位 z:auto/0 ← 弹层/粘顶栏等在这
//    2 正 z          ← 顶栏 z-10 之类

export type Band = -1 | 0 | 1 | 2;

/** 一个层叠上下文容器的样式投影（只取判带位用得上的三个属性）。 */
export interface StackContextLike {
  selector: string;
  /** 计算值语义：null = auto。 */
  zIndex: number | null;
  position: string;
  isolation: string;
}

/** 一个背景图层的样式投影。 */
export interface LayerLike {
  selector: string;
  zIndex: number;
  position: string;
  pointerEvents: string;
  /** 是否渲染在背景容器里面。 */
  insideStage: boolean;
}

export interface Judgement {
  band: Band | 'uncontrolled';
  /** 一行可复核的理由（打红时直接进测试输出）。 */
  reason: string;
}

/** 定位元素按 z 值折算带位；非定位元素一律 in-flow 块带。 */
export function bandOf(zIndex: number | null, position: string): Band {
  if (position === 'static') return 0;
  if (zIndex === null) return 1;
  if (zIndex < 0) return -1;
  if (zIndex === 0) return 1;
  return 2;
}

/**
 * 背景容器自己的带位。
 * 判红面：z-index 缺失/0/正数 ⇒ 整组背景会被抬到 in-flow 正文之上（这正是「糊住正文」的成因）。
 */
export function stageBand(stage: StackContextLike): Judgement {
  if (stage.position === 'static') {
    return { band: 'uncontrolled', reason: `${stage.selector} 未定位（position:static）⇒ 不是层叠上下文，负 z 层会外溢到更外层` };
  }
  if (stage.isolation !== 'isolate') {
    return { band: 'uncontrolled', reason: `${stage.selector} 缺 isolation:isolate ⇒ 不能保证自成层叠上下文组` };
  }
  const band = bandOf(stage.zIndex, stage.position);
  if (band !== -1) {
    return {
      band,
      reason: `${stage.selector} z-index=${stage.zIndex ?? 'auto'} ⇒ 带位 ${band}，不在负 z 步；整组背景会画在 in-flow 正文之上`,
    };
  }
  return { band, reason: `${stage.selector} 落在负 z 步（z-index:${stage.zIndex}）` };
}

/**
 * 单个背景层落点。
 * 只有「层在容器内 + 层自己 z<0 + 容器在负 z 步」三条同真，才判它排在正文之下。
 */
export function layerBand(layer: LayerLike, stage: StackContextLike): Judgement {
  if (!layer.insideStage) {
    return {
      band: 'uncontrolled',
      reason: `${layer.selector} 不在背景容器里 ⇒ 落点取决于更远祖先（今天恰好靠 #root 的 isolation 兜住，任何中间层加 transform/filter/opacity 就换上下文）`,
    };
  }
  if (layer.pointerEvents !== 'none') {
    return { band: 'uncontrolled', reason: `${layer.selector} pointer-events=${layer.pointerEvents} ⇒ 会抢正文的鼠标事件` };
  }
  if (layer.position === 'static') {
    return { band: 'uncontrolled', reason: `${layer.selector} position:static ⇒ 不按视口铺满` };
  }
  if (!(layer.zIndex < 0)) {
    return { band: bandOf(layer.zIndex, layer.position), reason: `${layer.selector} z-index=${layer.zIndex} 非负 ⇒ 会盖住容器内其它内容` };
  }
  const s = stageBand(stage);
  if (s.band !== -1) return { band: s.band, reason: `${layer.selector} 被容器带位带偏：${s.reason}` };
  return { band: -1, reason: `${layer.selector} z-index=${layer.zIndex} 在 ${stage.selector} 内 ⇒ 负 z 步` };
}

/** 背景层是否严格排在任何正文（in-flow 块带 0 及以上）之下。 */
export function isBehindContent(layer: LayerLike, stage: StackContextLike): boolean {
  return layerBand(layer, stage).band === -1;
}
