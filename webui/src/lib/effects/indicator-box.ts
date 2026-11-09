// 导航活跃指示器换算（参考站 daniya.top 的 `movePill` / `activateForm` 抽成纯函数）。
//
// 参考站逐字写的是：
//   `pill.style.left  = link.offsetLeft + 'px'`
//   `pill.style.width = link.offsetWidth + 'px'`
//   `formPill.style.transform = 'translateX(' + (btn.offsetLeft - 4) + 'px)'`
//
// 🔴 本仓的**有意改写**：`left` / `width` 都触发 layout（参考站靠浏览器每帧重算这一小块），
//    而本仓的导航项数量是 18（侧栏三簇），每帧重排整条侧栏的代价不能忽略。
//    所以这里只算数值，由调用方写成 `transform: translate3d(...)` + `inline-size`。
//    数学关系一字没变：偏移 = 链接相对容器的原点差，尺寸 = 链接自身尺寸。

/** 元素盒子（`getBoundingClientRect()` 的子集，也接受手工构造）。 */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 指示器要写进 CSS 的四个值。全部为整数 px。 */
export interface IndicatorBox {
  translateX: number;
  translateY: number;
  width: number;
  height: number;
}

/**
 * 算指示器该落在哪儿。
 *
 * 返回 `null` 的四种情况都是**真会发生**的：
 *   · 链接或容器尺寸为 0（`display:none` 的抽屉、`aria-hidden` 的分隔件）
 *   · 任一坐标为 NaN（布局未定案时 `offsetWidth` 可能读成 NaN）
 * 返回 `null` 时调用方应当**保持上一次的位置**（参考站的做法是直接不写样式，
 * 指示器就停在原地——比跳到 (0,0) 好）。
 */
export function indicatorBox(link: Box, container: Box): IndicatorBox | null {
  for (const n of [link.x, link.y, link.width, link.height, container.x, container.y, container.width, container.height]) {
    if (!Number.isFinite(n)) return null;
  }
  if (link.width <= 0 || link.height <= 0) return null;
  if (container.width <= 0 || container.height <= 0) return null;
  return {
    translateX: Math.round(link.x - container.x),
    translateY: Math.round(link.y - container.y),
    width: Math.round(link.width),
    height: Math.round(link.height),
  };
}
