/** DOM 约定：固定节点集中映射，动态节点在对应组件根内查询。 */

/** 数组按 ID 返回；对象按语义名称返回，HTML 改 ID 时仅调整映射值。 */
export function cacheIds(ids, root = document) {
  const entries = Array.isArray(ids) ? ids.map(id => [id, id]) : Object.entries(ids);
  return Object.fromEntries(entries.map(([name, id]) => [name, root.getElementById(id)]));
}

/** root 用于限定动态组件的查找范围。 */
export function $(selector, root = document) {
  return root.querySelector(selector);
}

/** 返回普通数组，便于过滤、映射和迭代动态节点。 */
export function $$(selector, root = document) {
  return [...root.querySelectorAll(selector)];
}
