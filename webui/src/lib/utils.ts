import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// 移植自 AxonHub frontend/src/lib/utils.ts（Apache-2.0，已注明修改；裁剪为本项目所需子集）。
//
// 【为什么必须自定义 merger——版式宪法缺陷根因】
// 五档字号用 Tailwind v4 的 @utility fs-* 定义，tailwind-merge 默认 class group 表里没有任何
// "fs-" 字面量，于是 cn() 从不折叠它们：组件基类的内建行高/字号类与调用方 fs-* 撞同一 CSS 属性时
// 两条都留在最终串里，胜负交给产物层叠顺序。实测五档全部早于内建 leading-*/font-*，
// 即「基类恒胜、调用方静默失效」——旧 P1-1 卡片标题行高塌陷就是这一族，靠手删一类只治了一处。
// 注册进内建组后：①同组冲突由「后者胜」=调用方胜（语义正确）；②借默认
// conflictingClassGroups['font-size'] = ['leading']，基类行高 + 调用方 fs-* 会被折叠删除；
// ③不误伤颜色（font-size 与 text-color 是两组）。
// 已知不覆盖：基类 fs-* + 调用方 leading-*（冲突表单向）。反向声明实测会把字号整条删掉、
// 元素退回继承字号，更坏——那一族只能靠「同元素禁双写」静态门守。
const TYPE_LADDER = ['fs-page', 'fs-card', 'fs-body', 'fs-caption', 'fs-num'];

// tone-face-* 与内建 bg-* 打同一个 background。注册后二者互删；不注册则恒由 tone-face-* 按
// 层叠取胜，导致同一族里「可覆盖」与「不可覆盖」并存（brand tone 走 bg-primary/15 能被压，
// 其余六枚压不动）——语义不一致。
const TONE_FACE = [
  'tone-face',
  'tone-face-good',
  'tone-face-warn',
  'tone-face-bad',
  'tone-face-info',
  'tone-face-purple',
  'tone-face-magenta',
  'tone-face-flat',
];

// tailwind-merge 3.x 必须写在 extend 里：顶层 classGroups 是 2.x 旧写法，3.7.0 会被
// mergeConfigs 静默丢弃（运行时完全不生效，只有 tsc 会报类型）。
const cnMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': TYPE_LADDER,
      'bg-color': TONE_FACE,
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return cnMerge(clsx(inputs));
}
