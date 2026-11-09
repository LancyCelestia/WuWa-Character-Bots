// 配置树的「按下标路径读写」两个纯函数（UI3 追加二）。
//
// 为什么单独一个文件：`schema-fields.ts` 里住着 17 组的**中文文案**（约 28 KB），
// 而首屏的 `context.tsx` / `presets.ts` 只需要这两个工具函数。放在一起会让
// 整个字段表被静态拽进首屏主包（实测 +7 处文案泄漏、主包 gzip 多出数十 KB），
// 而字段表本该只活在外观页那个按需 chunk 里。
//
// 本文件零依赖、零 React，可被 node --test 直接加载。

export function getPath(source: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => {
    if (node && typeof node === 'object') return (node as Record<string, unknown>)[key];
    return undefined;
  }, source);
}

/** 返回新对象（不改入参）：配置是不可变数据，React 靠引用变化才重渲染。 */
export function setPath<T extends Record<string, unknown>>(source: T, path: string, value: unknown): T {
  const [head, ...rest] = path.split('.');
  if (rest.length === 0) return { ...source, [head]: value };
  const child = (source[head] && typeof source[head] === 'object' ? source[head] : {}) as Record<string, unknown>;
  return { ...source, [head]: setPath(child, rest.join('.'), value) };
}
