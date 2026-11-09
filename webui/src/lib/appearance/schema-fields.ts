// 外观工作室的**字段真身**（WAVE-ALL 第一部分 17 组）。
//
// 用户裁定：「所有 ui 特效全部赶进设置里，让用户全部自己调整，包括颜色、特效、效果等」
// 再加「所有参数设置必须给中文的详细标题和说明」。所以每一行都要有：
//   中文标题（label）+ 讲清「调大了会怎样」的中文说明（help）+ 一个控件（control）。
//
// 为什么是数据而不是写死的 JSX：三项判据都要能被机器核对——
//   ① 17 组、每组 ≥3 项（appearance.test.ts 锁）；
//   ② 每项都有中文标题与说明（同锁）；
//   ③ 配置树里没有「看不见的字段」（反向覆盖锁：flatSections ⊆ 本表）。
// 写成 JSX 的话这三条只能靠肉眼，而且组与组之间会漂移。
//
// 控件取值（control）：
//   switch  开关           slider 滑块（界值从 ./schema 的 RANGES 取，不在这里写第二份）
//   radio   单选（竖排）    multi  多选（勾选组，值存成数组）
//   number  数字输入       file   本地文件选择（只落 IndexedDB，永不上传）
//   color   色票（只从已登记 token 里选，不许手输色值）  select 下拉  text 文本
//
// `key` 支持一层嵌套（`targets.nav`）：取值/写入由 ./path 的 getPath/setPath 统一处理。

import type { AppearanceSection } from './types.ts';

export type AppearanceControl = 'switch' | 'slider' | 'radio' | 'segment' | 'multi' | 'number' | 'file' | 'color' | 'select' | 'text';

/** 一个可选值：`value` 是存进配置的原始值，`label` 是中文显示名。 */
export interface Choice {
  value: string | number | boolean;
  label: string;
}

export interface AppearanceField {
  /** 组内字段键（可一层嵌套，如 `targets.nav`）。 */
  key: string;
  /**
   * 项级分节覆盖：极少数项住在别的分节里但归本组管（例：统计图表组里的
   * 「3D 视图质量档」落在 `scene3d`）。缺省 = 用组自己的 section。
   */
  section?: AppearanceSection;
  /** 中文标题。 */
  label: string;
  /** 中文说明：讲清「调大了会怎样 / 关掉会怎样」。 */
  help: string;
  control: AppearanceControl;
  choices?: Choice[];
  /** 仅 color：可选 token 清单（值 = 色板里的字段名或已登记变量名）。 */
  tokens?: string[];
  /** 仅 text：占位提示。 */
  placeholder?: string;
  /** 仅 slider：只用于覆盖 ./schema 的显示单位后缀。 */
  unit?: string;
}

export interface AppearanceGroup {
  /** 分组 id（也用于锚点与搜索）。 */
  id: string;
  /** 配置树里的分组键。 */
  section: AppearanceSection;
  /** 中文组名。 */
  title: string;
  /** 中文组说明：这一组管什么。 */
  hint: string;
  items: AppearanceField[];
}

// —— 复用的中文选项表（写一次，到处引用，避免同义词漂移） ——

export const APPEARANCE_FIELDS: AppearanceGroup[] = [
  // ======================= 1. 壁纸 =======================
  {
    id: 'wallpaper',
    section: 'wallpaper',
    title: '壁纸',
    hint: '背景层。图片与视频都是你自己电脑上的文件，存在浏览器本地（IndexedDB），永不上传、永不下载——服务器一份字节都不发。',
    items: [
      {
        key: 'mode',
        label: '壁纸类型',
        help: '纯色底最省；场景着色由显卡现画，零流量、永远不糊，是缺省值；本地图片与本地视频要从下面「选择壁纸文件」挑你自己电脑上的文件。调成视频会让滚动时更吃显卡，手机建议用场景着色。',
        control: 'segment',
        choices: [
          { value: 'none', label: '纯色' },
          { value: 'shader', label: '场景着色' },
          { value: 'image', label: '本地图片' },
          { value: 'video', label: '本地视频' },
        ],
      },
      {
        // 这一项不是配置字段，是**动作**（选文件 → 写 blobId + 存 IndexedDB）。
        // 按用户原话「直接选择 mp4 文件导入，再调整参数」放在紧挨类型选择的位置。
        key: 'file',
        label: '选择壁纸文件',
        help: '点「选择文件」挑一张图片或一个 mp4，只读你本机文件、存进浏览器数据库（IndexedDB），服务器一份字节都收不到。选完立刻生效，不必再填地址；超过约 30 MB 的视频会明显卡一下，建议先压一压。',
        control: 'file',
      },
      {
        key: 'opacity',
        label: '壁纸不透明度',
        help: '调低→壁纸更淡，文字更清楚，但背景会显得平；调高→壁纸更实，正文对比度下降，长时间看眼睛累。60–80 是观感与可读性的平衡点。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'blur',
        label: '壁纸模糊',
        help: '调大→壁纸化成色块，文字最清楚，代价是细节全丢；调小→保留原图细节，但背景越花越抢正文。每加 1px 都会让合成器多算一次，低配机别超过 20。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'brightness',
        label: '亮度',
        help: '调高→壁纸更亮更「通透」，但浅底上白字会看不清；调低→更暗更沉，深色主题下正文反而更好读。低于 60 基本就看不见壁纸了。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'contrast',
        label: '对比度',
        help: '调高→明暗差变大，画面锐利但脏点与噪点也被放大；调低→整体发灰，长时间看更柔和。跟亮度配合，一般不动。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'saturation',
        label: '饱和度',
        help: '调高→颜色更艳，适合展示，但会盖住光斑与虹彩的颜色；调到 0 是黑白照片，最不抢眼。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'scale',
        label: '缩放',
        help: '调大→画面被推进去一点，能看到更多中间细节、裁掉四边；调小→退远一点，边缘可能露出底色。只微调，不用来替代分辨率。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'playbackRate',
        label: '播放速度',
        help: '只在视频模式下生效。调快→循环更短、画面更跳；调慢→更平静，但更费电（同一段画面要播更久）。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'blobId',
        label: '已选本地文件',
        help: '显示当前壁纸绑定的本地文件标识；留空表示还没选过文件（或已清除）。由上面的「选择壁纸文件」写入，清除后下一次刷新就回到程序化背景。这个值只在本机，服务器看不到。',
        control: 'text',
        placeholder: '尚未选择本地文件',
      },
      {
        key: 'muted',
        label: '视频静音',
        help: '关掉静音→浏览器会拦住自动播放并等你点一下，同时可能突然出声。建议保持静音。',
        control: 'switch',
      },
      {
        key: 'loop',
        label: '循环播放',
        help: '关掉→视频播完就停在最后一帧，背景变成一张静图；开着才会一直动。',
        control: 'switch',
      },
    ],
  },

  // ======================= 2. 光斑 =======================
  {
    id: 'aurora',
    section: 'aurora',
    hint: '釉瑚光斑：几团缓慢漂移的柔光，用「相加」的方式叠在壁纸上——它只让画面更亮，不会把壁纸遮掉。',
    title: '光斑',
    items: [
      {
        key: 'enabled',
        label: '启用光斑',
        help: '关掉→背景彻底安静，最省电；开着→画面有呼吸感。手机或省流模式下会被自动关小。',
        control: 'switch',
      },
      {
        key: 'count',
        label: '光斑数量',
        help: '每多一团就多一层混合运算。超过 4 团在集显上开始掉帧，6 团是上限；手机上会被自动压到 2 团。',
        control: 'slider',
        unit: '团',
      },
      {
        key: 'palette',
        label: '配色',
        help: '深海偏冷蓝、星空偏紫、深潭偏青，色相越往后越暖。「自定义」可以自己挑三团光的颜色；选错成跟壁纸接近的一套，光斑就会几乎看不见。',
        control: 'segment',
        choices: [
          { value: 'sea', label: '深海蓝' },
          { value: 'star', label: '星空紫' },
          { value: 'deep', label: '深潭青' },
          { value: 'custom', label: '自定义' },
        ],
      },
      {
        key: 'customColors',
        label: '自定义光斑颜色',
        help: '只有在配色选「自定义」时生效。挑的 token 越多，光斑的层次越丰富；只选一枚则三团同色、画面最平；选到 4 枚以上不再增加变化（三团按前三枚循环）。',
        control: 'color',
        tokens: ['brand', 'purple', 'deep', 'danger', 'success', 'warning'],
      },
      {
        key: 'speed',
        label: '漂移速度',
        help: '调快→光斑走得更急，存在感强，但也更容易让人分神；调慢→几乎静止，像块柔光。1 倍是缺省节奏。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'intensity',
        label: '光斑浓度',
        help: '调高→光更亮、更抢眼，太亮会盖住正文的层次；调低→只留一点氛围。叠加在亮壁纸上时建议调低。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'blur',
        label: '柔化半径',
        help: '调大→边缘更散、更像雾，但每个光斑的绘制面积也更大，更吃显卡；调小→变成一团团明显的圆斑。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'blend',
        label: '叠加方式',
        help: '「滤色 / 相加」是加光，壁纸越暗光越明显；「叠加」会同时影响明暗，颜色更浓但容易脏；「正常」是直接盖住——会遮挡壁纸。',
        control: 'select',
        choices: [
          { value: 'screen', label: '滤色（加光，推荐）' },
          { value: 'plus-lighter', label: '相加更亮' },
          { value: 'overlay', label: '叠加（浓）' },
          { value: 'normal', label: '正常（会遮挡）' },
        ],
      },
    ],
  },

  // ======================= 3. 虹彩 =======================
  {
    id: 'iridescence',
    section: 'iridescence',
    title: '虹彩',
    hint: '旋转的七彩反光，可以长在导航、标题、卡片描边上。它比光斑更「锋利」，是画面里最容易过火的一层。',
    items: [
      {
        key: 'enabled',
        label: '启用虹彩',
        help: '关掉→只剩柔光，整体更稳；开着→界面有金属反光感，但和正文抢注意力。',
        control: 'switch',
      },
      {
        key: 'targets.nav',
        label: '落在侧栏导航',
        help: '开→导航条上有一圈流动的彩色描边，能立刻抓住视线；关→导航保持素净，更适合长时间工作。',
        control: 'switch',
      },
      {
        key: 'targets.title',
        label: '落在页面标题',
        help: '开→标题文字带虹彩，适合展示与截图；关→标题纯色，读起来更快。',
        control: 'switch',
      },
      {
        key: 'targets.cardEdge',
        label: '落在卡片描边',
        help: '开→每块面板边缘有一圈很细的彩色光边，层次感最强，也是全站最耗合成的一处；弱机建议关。',
        control: 'switch',
      },
      {
        key: 'targets.chartFill',
        label: '落在图表填充',
        help: '开→图表面积区带虹彩渐变，好看但会降低数据本身的辨识度；只读数字的人建议关。',
        control: 'switch',
      },
      {
        key: 'hueRange',
        label: '色相跨度',
        help: '调大→一圈里扫过更多颜色，最花；调小→接近单色渐变，最克制。90 左右是「有点彩但不吵」。',
        control: 'slider',
        unit: '°',
      },
      {
        key: 'speed',
        label: '流转速度',
        help: '调快→颜色流动明显，容易分心；调慢→几乎看不出在动，只当静态渐变用。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'thickness',
        label: '描边厚度',
        help: '调粗→光边更显眼，但会吃掉面板的留白，密集界面里显得拥挤；1px 最干净。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'opacity',
        label: '虹彩强度',
        help: '调高→彩色层更实，可能盖住底下的壁纸纹理；调低→只当一层淡淡的金属光泽。',
        control: 'slider',
        unit: '%',
      },
    ],
  },

  // ======================= 4. 辉光 =======================
  {
    id: 'glow',
    section: 'glow',
    title: '辉光',
    hint: '让关键数值、按钮、徽章「亮起来」的一圈外发光。它是最便宜的高亮手段，也是最容易滥用的一层。',
    items: [
      {
        key: 'enabled',
        label: '启用辉光',
        help: '关掉→所有发光收起，界面变素；开着→重要信息自带光环。',
        control: 'switch',
      },
      {
        key: 'targets.value',
        label: '落在关键数值',
        help: '开→统计卡里的大数字带光晕，最容易被看到；关→数字回归平面。',
        control: 'switch',
      },
      {
        key: 'targets.badge',
        label: '落在状态徽章',
        help: '开→「正常 / 注意 / 异常」这类小胶囊发光，扫一眼就能定位；关→靠颜色区分。',
        control: 'switch',
      },
      {
        key: 'targets.button',
        label: '落在按钮',
        help: '开→主要动作有呼唤感；全站按钮都发光会显得浮夸，建议只保留主按钮。',
        control: 'switch',
      },
      {
        key: 'targets.chartPoint',
        label: '落在图表数据点',
        help: '开→折线拐点带光点，能突出极值；点多时（大于 60 个）会变成一串亮片，建议关。',
        control: 'switch',
      },
      {
        key: 'targets.cardHover',
        label: '落在卡片悬停',
        help: '开→鼠标移上去面板浮起并发光，反馈明确；关→只靠边框变化，更安静。',
        control: 'switch',
      },
      {
        key: 'radius',
        label: '辉光半径',
        help: '调大→光的扩散范围更广，像霓虹；超过 30 会糊到相邻元素上，让版面显得脏。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'strength',
        label: '辉光强度',
        help: '调高→光更亮更实，白底上会泛白；调低→只留一丝轮廓光。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'color',
        label: '取色来源',
        help: '「跟随语义」→好是绿、警告是黄，辉光本身就在传递状态，扫一眼就知道有没有事；「品牌色」→全站统一一种光，最克制但丢掉了状态信息；「自定义」→你自己挑，挑得越亮越容易盖住徽章本身的颜色。',
        control: 'segment',
        choices: [
          { value: 'semantic', label: '跟随语义色' },
          { value: 'brand', label: '品牌色' },
          { value: 'custom', label: '自定义' },
        ],
      },
      {
        key: 'customColor',
        label: '自定义辉光色',
        help: '只有取色来源选「自定义」时生效。只能从已登记的品牌 token 里挑，避免出现「代码外的第五种颜色」；挑得越接近白，辉光越泛白、越容易盖住徽章本身的文字。',
        control: 'color',
        tokens: ['brand', 'purple', 'deep', 'danger', 'success', 'warning'],
      },
    ],
  },

  // ======================= 5. 玻璃 =======================
  {
    id: 'glass',
    section: 'glass',
    title: '玻璃 / 云母',
    hint: '侧栏与顶栏那层「磨砂玻璃」：模糊、饱和度、底色透明度、描边与外发光。它直接决定界面是轻还是厚。',
    items: [
      {
        key: 'blur',
        label: '玻璃模糊',
        help: '调大→背后内容化成一团颜色，面板最「厚实」，但这是最贵的一档特效（每帧都要重采样），手机上会被自动压到 12px 以内。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'saturation',
        label: '背景饱和度',
        help: '调高→透过玻璃看到的颜色更艳，像彩色玻璃；太高会显得假。玻璃没有背后内容时这档看不出效果。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'opacity',
        label: '底色不透明度',
        help: '调高→面板更实、文字最清楚，但玻璃感消失；调低→更通透，壁纸直接透上来，正文对比度变差。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'borderStrength',
        label: '描边强度',
        help: '调高→边界更清晰，面板「立」起来；调低→边界融化，容易分不清哪块是面板。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'elevation',
        label: '悬浮高度',
        help: '调大→投影更远，像浮在壁纸上；太大会显得整页在飘。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'grain',
        label: '颗粒层',
        help: '开→铺一层极细的噪点，消除大面积渐变的「塑料感」；关→更干净，但渐变带纹会更明显。',
        control: 'switch',
      },
      {
        key: 'grainOpacity',
        label: '颗粒浓度',
        help: '调高→噪点可见，像纸；超过 6% 就开始像信号不好，也会拖慢渲染。',
        control: 'slider',
        unit: '%',
      },
    ],
  },

  // ======================= 6. 字体 =======================
  {
    id: 'typography',
    section: 'typography',
    title: '字体与排版',
    hint: '五档字号各自一个 px 滑块——页面标题 / 卡片标题 / 正文 / 说明 / 数字大字，全部按你给的值渲染。改完立刻生效，不需要保存。',
    items: [
      {
        key: 'pageSize',
        label: '页面标题字号',
        help: '单位 px。每个页面最上面那行大标题。调大→更有层级感，但窄屏上一行长标题会折行；调小→省地方，跟正文拉不开差距就失去「这是标题」的暗示。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'cardSize',
        label: '卡片标题字号',
        help: '单位 px。分组卡片、面板小标题。调大→分组更醒目，但一屏能看到的字段变少；调到比正文还小会让标题看起来像注释。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'rootSize',
        label: '正文字号',
        help: '单位 px。正文与按钮标签的基准，改动影响面最大：调大→所有页面更好读，小屏一屏内容变少；调小→密度高，低于 12 会明显费眼。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'captionSize',
        label: '说明字号',
        help: '单位 px。每个参数下面那行灰色说明。调大→说明更好读，但字段行会变得很高；调小→更紧凑，低于 11 就只剩「看不清」一条。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'numSize',
        label: '数字大字字号',
        help: '单位 px。总览页的关键数值（带虹彩描边那种）。调大→数字更有冲击力，但一个数字能占半屏；调小→跟正文混在一起，失去重点。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'lineHeight',
        label: '行高',
        help: '倍率（不是 px）。调大→行距松、长段落好读，但一屏行数变少；调小→更紧凑，多行中文容易粘连。正文建议 1.5 左右。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'letterSpacing',
        label: '字间距',
        help: '调大→字之间更疏，适合标题，正文会散；调小（负值）→更紧，中文挤在一起会难认。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'weightBody',
        label: '正文字重',
        help: '常规最省眼；越往加粗走越醒目，但小字号加粗会糊成一团、笔画粘连，长文阅读反而更累。',
        control: 'segment',
        choices: [
          { value: 400, label: '常规 400' },
          { value: 500, label: '中等 500' },
          { value: 600, label: '加粗 600' },
        ],
      },
    ],
  },

  // ======================= 7. 动效 =======================
  {
    id: 'motion',
    section: 'motion',
    title: '动效',
    hint: '入场动画、图表描边、全局速度。动效是「好用」与「闹」之间最敏感的一根线，也最容易让人晕。',
    items: [
      {
        key: 'enabled',
        label: '启用动效',
        help: '关掉→所有动画停格，最稳最省电，也适合专注；开着→页面切换有过渡。',
        control: 'switch',
      },
      {
        key: 'speed',
        label: '动效速度',
        help: '调快→动画更利落，但太快会看不出过程；调慢→更轻柔，操作反馈会显得迟钝。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'entrance',
        label: '入场方式',
        help: '上浮 / 淡入最不打扰；缩放有一点弹跳感；模糊入场最华丽也最吃显卡（整层模糊要重新采样）。',
        control: 'select',
        choices: [
          { value: 'none', label: '不动' },
          { value: 'rise', label: '上浮' },
          { value: 'fade', label: '淡入' },
          { value: 'scale', label: '缩放' },
          { value: 'blur', label: '模糊' },
        ],
      },
      {
        key: 'chartPath',
        label: '图表描边动画',
        help: '开→折线会「画」出来，展示好看；关→直接出现，刷新频繁时不会一直闪。',
        control: 'switch',
      },
      {
        key: 'reduceMotionRespect',
        label: '尊重系统「减少动态效果」',
        help: '开着→系统里开了减少动效，这里就自动停，是最稳妥的默认；关掉→无论系统怎么设置都按你的来——前庭功能敏感的人请保持开启。',
        control: 'switch',
      },
    ],
  },

  // ======================= 8. 配色 =======================
  {
    id: 'palette',
    section: 'palette',
    title: '品牌配色',
    hint: '六个语义色。它们喂给按钮、链接、图表、状态徽章——换一套等于换整个界面的气质。',
    items: [
      {
        key: 'preset',
        label: '配色方案',
        help: '选一套现成的（深海 / 星空 / 深潭）；选「自定义」后，下面六个色票才会真正影响界面。标签带括号说明，用可换行的 chips 而不是分段条，窄屏不会挤成两行半。',
        control: 'radio',
        choices: [
          { value: 'sea', label: '深海（缺省）' },
          { value: 'star', label: '星空' },
          { value: 'deep', label: '深潭' },
          { value: 'custom', label: '自定义' },
        ],
      },
      {
        key: 'brand',
        label: '品牌主色',
        help: '最主要的那个色：主按钮、链接、选中态、图表第一条线。换它，全站最显眼的地方一起换。',
        control: 'color',
        tokens: ['brand', 'purple', 'deep'],
      },
      {
        key: 'purple',
        label: '辅助紫',
        help: '用于次级强调与渐变里的过渡色。跟主色太接近就分不出层次，太远又会散。',
        control: 'color',
        tokens: ['purple', 'brand', 'deep'],
      },
      {
        key: 'deep',
        label: '深色基底',
        help: '投影、深色面、文字的沉稳色。调得太浅会让整个界面「浮起来」，失去重量感。',
        control: 'color',
        tokens: ['deep', 'brand', 'purple'],
      },
      {
        key: 'danger',
        label: '危险色',
        help: '失败、删除、错误。请保持偏红——用户对红色的反应是肌肉记忆，换成暖橙会读成「注意」而不是「出错」。',
        control: 'color',
        tokens: ['danger', 'warning', 'brand'],
      },
      {
        key: 'success',
        label: '成功色',
        help: '正常、通过、健康。偏绿最不易误读；色盲友好模式下会被替换成安全的蓝。',
        control: 'color',
        tokens: ['success', 'brand', 'warning'],
      },
      {
        key: 'warning',
        label: '警告色',
        help: '降级、待确认、接近阈值。跟危险色区分越明显越好，否则「要注意」和「出事了」会分不清。',
        control: 'color',
        tokens: ['warning', 'danger', 'success'],
      },
    ],
  },

  // ======================= 9. 布局 =======================
  {
    id: 'layout',
    section: 'layout',
    title: '布局',
    hint: '侧栏停在哪边、多宽、顶栏多高、面板圆角与密度、总览几列。这一组决定「第一眼看到多少信息」。',
    items: [
      {
        key: 'side',
        label: '侧栏位置',
        help: '放右边→阅读路径从左上开始，正文更靠左，适合宽屏；放左边→导航离鼠标更近。切换后立即生效。',
        control: 'segment',
        choices: [
          { value: 'left', label: '靠左' },
          { value: 'right', label: '靠右' },
        ],
      },
      {
        key: 'sidebarWidth',
        label: '侧栏宽度',
        help: '调宽→导航文字不容易折行，但正文区被压缩，宽表会横向滚动；调窄→内容区更大，长页面名会被截断。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'collapsedByDefault',
        label: '默认收起侧栏',
        help: '开→每次打开都在窄栏状态，内容区最大化；关→保持完整导航。',
        control: 'switch',
      },
      {
        key: 'collapseMode',
        label: '收起后',
        help: '「只留图标」→还能一眼看全页面入口；「完全隐藏」→最干净，但换页要先点一下展开。',
        control: 'segment',
        choices: [
          { value: 'icon', label: '只留图标' },
          { value: 'hidden', label: '完全隐藏' },
        ],
      },
      {
        key: 'headerHeight',
        label: '顶栏高度',
        help: '调高→触屏更好点，但占掉一屏的行数；调低→更紧凑，图标容易显得挤。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'headerFloating',
        label: '悬浮顶栏',
        help: '开→顶栏浮在内容之上带玻璃效果，滚动时内容从它下面穿过去；关→顶栏占一条固定位置。悬浮会多一层合成。',
        control: 'switch',
      },
      {
        key: 'headerSticky',
        label: '顶栏吸顶',
        help: '开→滚动时顶栏一直跟着，随时能点设置；关→顶栏跟着页面滚走，视野更大但操作要滚回顶部。',
        control: 'switch',
      },
      {
        key: 'radius',
        label: '界面圆角',
        help: '单位 px。调大→卡片与面板的角更圆、更像悬浮玻璃块，太大会把密集界面的边角挤掉；调小→更利落、信息更密，0 是完全直角。面板=本值，大窗=+12，瓦片=-4。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'spacing',
        label: '面板间距',
        help: '倍率。调大→面板之间与屏幕边缘的缝一起变宽（1.5 倍就是原来的 1.5 倍），呼吸感强但一屏内容变少；调小→更紧凑，低于 0.6 面板会贴在一起。缺省 1 倍。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'gridColumns',
        label: '总览列数',
        help: '列数多→一屏塞下更多卡，单卡变窄，长标题会折行；列数少→每张卡信息更舒展，但要往下滚。只能填 1–6 的整数。',
        control: 'number',
        unit: '列',
      },
      {
        key: 'cardMinWidth',
        label: '卡片最小宽度',
        help: '调大→窄屏上会自动减少列数，避免卡被挤扁；调小→能塞更多列，但卡片内容会挤到换行。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'showBreadcrumb',
        label: '显示面包屑',
        help: '开→能看到「总台 / 当前页」的位置，页数多时更好认路；关→顶栏更清爽。',
        control: 'switch',
      },
      {
        key: 'showHealthLamp',
        label: '显示健康灯',
        help: '开→顶栏有一枚绿点表示服务在线，出问题时会变黄变红；关→少一个会闪的点。',
        control: 'switch',
      },
      {
        key: 'showFooter',
        label: '显示侧栏页脚',
        help: '关→侧栏底部留白收起，导航能多放一项；开→显示版本与阶段信息。',
        control: 'switch',
      },
      {
        key: 'hiddenNav',
        label: '在侧栏隐藏的页面',
        help: '勾上的页面不会出现在侧栏，但地址栏直接访问仍然可以打开——是「不看」不是「关掉」。勾太多会失去导航的意义。',
        control: 'multi',
        choices: [
          { value: '/console', label: '控制台' },
          { value: '/', label: '总览' },
          { value: '/calls', label: '调用统计' },
          { value: '/tokens', label: 'Token 面板' },
          { value: '/latency', label: '延迟' },
          { value: '/affinity', label: '好感度榜' },
          { value: '/logs', label: '日志尾流' },
          { value: '/knowledge', label: '知识库' },
          { value: '/plugins', label: '插件' },
          { value: '/memory-graph', label: '记忆图谱' },
          { value: '/config', label: '参数与配置' },
          { value: '/resources', label: '实时资源' },
          { value: '/models', label: '模型与渠道' },
          { value: '/visual-editor', label: '卡片编辑器' },
          { value: '/credentials', label: '加密凭据' },
          { value: '/operations', label: '受控操作' },
        ],
      },
    ],
  },

  // ======================= 10. 数据与图表 =======================
  {
    id: 'charts',
    section: 'charts',
    title: '数据与图表',
    hint: '同一个数字可以画成折线、面积、柱状，也可以写成 1.2K 或 1.2 万。这一组决定「数据长什么样」。',
    items: [
      {
        key: 'kind',
        label: '默认图表类型',
        help: '折线看趋势、面积看体量、柱状看对比、散点看分布、环形看占比。选错类型会让数据读起来更费劲，不是「换个皮」。',
        control: 'select',
        choices: [
          { value: 'line', label: '折线' },
          { value: 'area', label: '面积' },
          { value: 'bar', label: '柱状' },
          { value: 'scatter', label: '散点' },
          { value: 'donut', label: '环形' },
        ],
      },
      {
        key: 'window',
        label: '默认时间窗',
        help: '24h 看当下、7d 看节奏、30d 看趋势。窗口越大，请求的数据越多、越慢、越费流量。',
        control: 'segment',
        choices: [
          { value: '24h', label: '24 小时' },
          { value: '7d', label: '7 天' },
          { value: '30d', label: '30 天' },
        ],
      },
      {
        key: 'refresh',
        label: '自动刷新',
        help: '关→不自动拉数，最省流量，需要手动刷新；每 5 秒→实时感最强，但一天能拉上万次请求，服务器只是 2C2G。',
        control: 'select',
        choices: [
          { value: 'off', label: '不自动刷新' },
          { value: '5s', label: '每 5 秒' },
          { value: '15s', label: '每 15 秒' },
          { value: '60s', label: '每 60 秒' },
        ],
      },
      {
        // 数字单位制**只有一份**，住在下面第 14 组「语言与格式」（`locale.unitSystem`）。
        // 这里曾重复登记一条 `charts.unitSystem`：配置树里那个字段全仓零消费方
        // （`context.tsx` 只把 `locale.unitSystem` 交给 format 接缝），于是这条控件
        // 「调了看不出任何变化」。去重后由 `lib/appearance-schema.test.ts` 钉住。
        key: 'decimals',
        label: '小数位',
        help: '0 位→整数，扫读最快；2–3 位→更精确，但数字变长、噪声变多。超过 2 位在卡片里通常没有意义。',
        control: 'number',
        unit: '位',
      },
      {
        key: 'thousands',
        label: '千分位分隔',
        help: '全站统一 3 位分隔（千分位：1,234,567），不会出现 4 位一组。开→带逗号，一眼能数位；关→只影响「完整数字」档的概览大数，token/样本这类明细计数始终带 3 位分隔（对账要用完整数字）。',
        control: 'switch',
      },
      {
        key: 'trendArrow',
        label: '显示趋势箭头',
        help: '开→数字旁有 ↑↓，能立刻看出涨跌；关→只留数字，界面更净。',
        control: 'switch',
      },
      {
        key: 'periodOverPeriod',
        label: '显示环比同比',
        help: '开→多一行「较上期 +12%」，信息更多也更密；关→只看当前值。注意：分母缺失时不会硬编一个百分比。',
        control: 'switch',
      },
      {
        key: 'quality',
        label: '图表绘制质量',
        help: '高档→曲线更平滑、拐点更多，但每次重绘的元素也更多；低档→抽稀采样，趋势仍看得对，弱机不卡。它与下面「3D 视图质量档」是两件事：一个管 2D 图表，一个管记忆图谱那种真 3D。',
        control: 'segment',
        choices: [
          { value: 'low', label: '低' },
          { value: 'medium', label: '中' },
          { value: 'high', label: '高' },
        ],
      },
      {
        // 用户的第 10 组清单里这一项叫「3D 视图质量档」——它落在 scene3d 分节，
        // 但归这一组管（真 3D 只在 3D 页动态加载，与图表同为「看数据的方式」）。
        key: 'quality',
        section: 'scene3d',
        label: '3D 视图质量档',
        help: '高档→像素比拉满、粒子更多、开后期，最清楚也最烧显卡；低档→关后期、降像素比，优先流畅。手机与低配机会被自动降档。',
        control: 'segment',
        choices: [
          { value: 'low', label: '低（最流畅）' },
          { value: 'medium', label: '中' },
          { value: 'high', label: '高（最清晰）' },
        ],
      },
    ],
  },

  // ======================= 11. 日志视图 =======================
  {
    id: 'logView',
    section: 'logView',
    title: '日志视图',
    hint: '事件流的密度、时间戳口径、以及「哪些行该被标红」的高亮规则。',
    items: [
      {
        key: 'lineHeight',
        label: '行高',
        help: '调大→行距松，长时间扫日志不串行；调小→一屏能看更多行，但密集文本更容易看错行。',
        control: 'slider',
        unit: '×',
      },
      {
        key: 'textSize',
        label: '日志字号',
        help: '12px 最紧、一屏最多；14px 平衡；16px 最舒服但屏上行数明显变少。',
        control: 'segment',
        choices: [
          { value: 12, label: '12px' },
          { value: 14, label: '14px' },
          { value: 16, label: '16px' },
        ],
      },
      {
        key: 'mono',
        label: '等宽字体',
        help: '开→字段对齐、时间戳等宽，扫列非常快；关→跟正文一致，读长句更自然。',
        control: 'switch',
      },
      {
        key: 'wrap',
        label: '自动换行',
        help: '关→一行一条，横向可扫但长文本要点开看；开→完整显示，但一条长错误会占掉半屏。',
        control: 'switch',
      },
      {
        key: 'timestamp',
        label: '时间戳格式',
        help: '绝对→能对账；相对（3 分钟前）→看新鲜度最快，但过一会就变了；仅时间→当天日志最省地方。',
        control: 'segment',
        choices: [
          { value: 'absolute', label: '绝对时间' },
          { value: 'relative', label: '相对时间' },
          { value: 'timeOnly', label: '仅时分秒' },
        ],
      },
      {
        key: 'rules',
        label: '高亮规则',
        help: '自己写关键字或正则，命中就把那一行的文字或整行染色。规则越多每条日志要过的检查越多，超过 10 条在高速日志下会掉帧。',
        control: 'text',
        placeholder: '在下方规则表里增删',
      },
      {
        key: 'autoScroll',
        label: '自动滚到底',
        help: '开→总是跟到最新一条，看实时流方便；关→固定在当前位置，适合边看边查，不会被新日志顶走。',
        control: 'switch',
      },
      {
        key: 'maxLines',
        label: '最多保留行数',
        help: '调大→能往回翻更久，但一直占内存，长时间开着会越来越卡；调小→更省内存，但一刷新记录就没了。',
        control: 'slider',
        unit: '行',
      },
    ],
  },

  // ======================= 12. 交互 =======================
  {
    id: 'interaction',
    section: 'interaction',
    title: '交互',
    hint: '快捷键、落地页、轮询、提示条位置、危险操作要确认几次。',
    items: [
      {
        key: 'bindings',
        label: '快捷键绑定',
        help: '每个动作一个组合键。冲突时同一组合键只会触发排在前面那个，后面的会被静默吃掉——这里会提前告诉你。',
        control: 'text',
        placeholder: '在下方绑定表里逐条改',
      },
      {
        key: 'landingPath',
        label: '默认落地页',
        help: '决定你打开控制台第一眼看到哪一页。设成你最常盯的那一页，每天少点一次导航；设成不常看的页，每次都要先跳走。',
        control: 'select',
        choices: [
          { value: '/console', label: '控制台总台' },
          { value: '/', label: '总览' },
          { value: '/calls', label: '调用统计' },
          { value: '/tokens', label: 'Token 面板' },
          { value: '/latency', label: '延迟' },
          { value: '/logs', label: '日志尾流' },
          { value: '/memory-graph', label: '记忆图谱' },
        ],
      },
      {
        key: 'polling',
        label: '全局轮询',
        help: '开→页面按各页节奏自动拉数据；关→全部变成手动刷新，流量最省，但数字会停在打开那一刻。',
        control: 'switch',
      },
      {
        key: 'toastCorner',
        label: '提示条位置',
        help: '选一个不挡视线的角。右下角最不碍事；左上角最容易被忽略。',
        control: 'select',
        choices: [
          { value: 'topLeft', label: '左上' },
          { value: 'topRight', label: '右上' },
          { value: 'bottomLeft', label: '左下' },
          { value: 'bottomRight', label: '右下' },
        ],
      },
      {
        key: 'toastDismissMs',
        label: '提示条停留时长',
        help: '调长→够看完一整句；调短→不挡操作，但容易错过。超过 8 秒会被当成「关不掉」的干扰。',
        control: 'slider',
        unit: 'ms',
      },
      {
        key: 'confirmLevel',
        label: '危险操作确认',
        help: '普通→点一次就执行；严格→要再确认一次并描述后果；极严→还要手打确认文字。「极严」会明显变慢，只在你真的很怕误点时选。',
        control: 'segment',
        choices: [
          { value: 'normal', label: '普通' },
          { value: 'strict', label: '严格' },
          { value: 'extreme', label: '极严' },
        ],
      },
    ],
  },

  // ======================= 13. 通知 =======================
  {
    id: 'notifications',
    section: 'notifications',
    title: '通知',
    hint: '浏览器通知与提示音，全部在本地完成——没有推送服务器，也不上传任何东西。',
    items: [
      {
        key: 'browserEnabled',
        label: '浏览器通知',
        help: '开→出严重告警时弹系统通知，切到别的窗口也不会错过；关→只在页面内提示。开启时浏览器会再问你一次授权。',
        control: 'switch',
      },
      {
        key: 'levels',
        label: '哪些级别触发通知',
        help: '全部勾上→任何一条都会弹，久了就麻木了（「狼来了」）；只留「严重」→每次响都值得看。',
        control: 'multi',
        choices: [
          { value: 'info', label: '提示' },
          { value: 'warn', label: '注意' },
          { value: 'bad', label: '严重' },
        ],
      },
      {
        key: 'soundEnabled',
        label: '提示音',
        help: '开启后用浏览器现场合成一声短音——不下载任何音频文件，0 字节流量；关掉则完全安静。',
        control: 'switch',
      },
      {
        key: 'soundVolume',
        label: '提示音音量',
        help: '调大→一定能听见，也一定会吵到旁边的人；调小→只在自己戴耳机时听得到。',
        control: 'slider',
        unit: '%',
      },
      {
        key: 'dndEnabled',
        label: '免打扰时段',
        help: '开→在下面的时间段里不弹通知、不响铃（页面内照常显示）。夜班或开会时很实用。',
        control: 'switch',
      },
      {
        key: 'dndFrom',
        label: '免打扰开始',
        help: '按你电脑的本地时间算。开始晚于结束会自动当作跨零点，比如 23:00 → 08:00。',
        control: 'text',
        placeholder: '23:00',
      },
      {
        key: 'dndTo',
        label: '免打扰结束',
        help: '到这里恢复通知。起止相同等于没有免打扰，建议至少间隔 1 小时。',
        control: 'text',
        placeholder: '08:00',
      },
    ],
  },

  // ======================= 14. 语言与格式 =======================
  {
    id: 'locale',
    section: 'locale',
    title: '语言与格式',
    hint: '界面语言、时间按哪个时区显示、日期怎么写、大数字怎么缩写。',
    items: [
      {
        key: 'language',
        label: '界面语言',
        help: '切换后整个控制台的按钮与标签跟着换。换成英文会让中文项目名与日志正文中英混排，读起来更慢；这个页面本身的设置项说明始终是中文。',
        control: 'segment',
        choices: [
          { value: 'zh-CN', label: '简体中文' },
          { value: 'en', label: 'English' },
        ],
      },
      {
        key: 'timezone',
        label: '时区显示',
        help: '本地→按你电脑的时区，最直观；UTC→排除时区歧义，对日志对账最准；固定偏移→盯某个机房的时刻表时用。',
        control: 'segment',
        choices: [
          { value: 'local', label: '跟随本机' },
          { value: 'utc', label: 'UTC' },
          { value: 'fixed', label: '固定偏移' },
        ],
      },
      {
        key: 'fixedOffset',
        label: '固定偏移',
        help: '只在时区选「固定偏移」时生效。范围 -12 到 +14 小时；填错会整片时间显示都偏。',
        control: 'slider',
        unit: 'h',
      },
      {
        key: 'dateFormat',
        label: '日期格式',
        help: '年-月-日最不容易读错；月-日最省地方，但跨年时会歧义；中文格式最自然，占位更长。',
        control: 'select',
        choices: [
          { value: 'iso', label: '2026-01-31' },
          { value: 'slash', label: '2026/01/31' },
          { value: 'short', label: '01-31' },
          { value: 'cn', label: '2026 年 1 月 31 日' },
        ],
      },
      {
        key: 'unitSystem',
        label: '数字单位',
        help: '「1.2K」偏技术；「1.2 万」符合中文习惯；「1200」最精确但更占位。这一档是**全站**口径（卡片、图例、明细都跟随）；明细计数与 token 数无论选哪档都按 3 位分隔给完整数字。',
        control: 'segment',
        choices: [
          { value: 'compact', label: '简写 1.2K / 1.2M' },
          { value: 'chinese', label: '中文 1.2 万 / 1.2 亿' },
          { value: 'plain', label: '完整数字' },
        ],
      },
    ],
  },

  // ======================= 15. 无障碍 =======================
  {
    id: 'a11y',
    section: 'a11y',
    title: '无障碍',
    hint: '对比度、字号、动效停止、焦点环、色盲配色。这些开关不是「锦上添花」——它们是能不能用的问题。',
    items: [
      {
        key: 'highContrast',
        label: '高对比模式',
        help: '开→边框更黑、文字与背景反差更大，弱视与强光环境下能看清；关→更柔和。开启会覆盖部分玻璃与低透明设置。',
        control: 'switch',
      },
      {
        key: 'largeText',
        label: '大字号模式',
        help: '开→在「基准字号」之上再放大一档正文，等于双重放大；关→只按基准值。都开时注意一屏能放下的内容会明显变少。',
        control: 'switch',
      },
      {
        key: 'forceReduceMotion',
        label: '强制减少动效',
        help: '开→不管系统怎么设置都停掉动画，对前庭敏感的人最安全；关→跟随系统与「动效」分组。',
        control: 'switch',
      },
      {
        key: 'focusRingWidth',
        label: '焦点环宽度',
        help: '调宽→键盘操作时一眼看到焦点在哪；太宽会挤掉元素间距。1–3px 是常规范围。',
        control: 'slider',
        unit: 'px',
      },
      {
        key: 'focusRingColor',
        label: '焦点环颜色',
        help: '留空→跟随品牌色；选一个状态色→让焦点和告警色区分开。只能从已登记的状态色里挑。',
        control: 'color',
        tokens: ['good', 'warn', 'bad', 'info', 'purple', 'magenta'],
      },
      {
        key: 'colorBlind',
        label: '色盲友好配色',
        help: '选一种后，红绿系会被替换成能分辨的蓝橙系。红绿色盲最常见，选中后「成功 / 失败」不再靠红绿区分。',
        control: 'segment',
        choices: [
          { value: 'none', label: '不调整' },
          { value: 'deuteranopia', label: '红绿色弱（最常见）' },
          { value: 'protanopia', label: '红色盲' },
          { value: 'tritanopia', label: '蓝黄色盲' },
        ],
      },
    ],
  },

  // ======================= 16. 数据密度 =======================
  {
    id: 'density',
    section: 'density',
    title: '数据密度',
    hint: '表格的行高、每页几条、空列要不要留。这一组决定「一屏能读多少行」。',
    items: [
      {
        key: 'tableDensity',
        label: '表格行密度',
        help: '紧凑→一屏多读一倍的行，适合扫异常；舒适→更好点、更不容易点错行。',
        control: 'segment',
        choices: [
          { value: 'compact', label: '紧凑' },
          { value: 'comfortable', label: '舒适' },
        ],
      },
      {
        key: 'pageSize',
        label: '每页条数',
        help: '调大→一页看完，少翻页，但首次加载更慢、更费流量；调小→加载快，但要不停翻页。',
        control: 'slider',
        unit: '条',
      },
      {
        key: 'hideEmptyColumns',
        label: '隐藏空列',
        help: '开→整列全是空值的列自动收起，表格更窄更聚焦；关→列位置固定，跨页对比时不会跳。',
        control: 'switch',
      },
    ],
  },

  // ======================= 17. 性能 / 省流量 =======================
  {
    id: 'performance',
    section: 'performance',
    title: '性能与省流量',
    hint: '服务器只有 2 核 2G、每月 20GB 流量。这一组是你能亲手把流量摁下去的地方——比任何自动优化都管用。',
    items: [
      {
        key: 'dataSaver',
        label: '省流模式',
        help: '开→不等系统提示，立刻压低特效与请求：关壁纸、减光斑、关动效。最省，也最朴素。',
        control: 'switch',
      },
      {
        key: 'prefetch',
        label: '预加载下个页面',
        help: '开→鼠标悬停时提前把下一页的代码下好，点击几乎瞬间打开，代价是可能白下一份；关→点哪下哪，最省流量。',
        control: 'switch',
      },
      {
        key: 'imageQuality',
        label: '图片清晰度',
        help: '原图最清楚也最费流量；压缩是缺省；不加载最省，但页面会缺少图片信息。手机上建议压缩或不加载。',
        control: 'segment',
        choices: [
          { value: 'original', label: '原图' },
          { value: 'compressed', label: '压缩' },
          { value: 'off', label: '不加载' },
        ],
      },
      {
        key: 'requestCache',
        label: '缓存接口响应',
        help: '选一段时间→这段时间内重复打开同一页不重复请求，最省流量；关→每次都要最新数据，请求最多。',
        control: 'select',
        choices: [
          { value: 'off', label: '不缓存' },
          { value: '30s', label: '30 秒' },
          { value: '60s', label: '60 秒' },
          { value: '300s', label: '5 分钟' },
        ],
      },
    ],
  },
];

/** 按 section 取组（页面渲染与取值共用；未知 section 返回 null）。 */
export function groupFor(section: string): AppearanceGroup | null {
  return APPEARANCE_FIELDS.find((group) => group.section === section) ?? null;
}

/** 扁平化成「section.key」清单（覆盖锁与搜索共用）。 */
export function fieldIndex(): Array<{ group: AppearanceGroup; field: AppearanceField; path: string }> {
  return APPEARANCE_FIELDS.flatMap((group) =>
    group.items.map((field) => ({ group, field, path: `${field.section ?? group.section}.${field.key}` }))
  );
}

// —— 取值 / 写入：实现在 `./path`（纯工具、零依赖）——
// 这里只做再导出，让「字段表」与「路径工具」各自可被单独引用：
// 首屏的 context/presets 只需要 path（几百字节），不该把 28 KB 文案一起拽进主包。
export { getPath, setPath } from './path.ts';
