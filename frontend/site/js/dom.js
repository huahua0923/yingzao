// 建 DOM 的小工具 —— 前台自己的一份。
//
// ★ 为什么不和后台共用（frontend/admin/js/dom.js）：两个页面是**分开部署的两个根**
//   （nginx 里 / 是前台、/admin 是后台）。前台去 import 后台的文件，等于把
//   "前台能不能独立上线"绑在后台目录的存在上。共用要等根挂载重排之后再统一，
//   不是现在顺手跨目录 import 一下。
//
// ★ el() 见到 `html` 属性直接抛：产物 JSON 里的字（楼名、房号、备注）
//   一律走 textContent。本仓记过「往 innerHTML 注字符串」这类账，
//   与其靠人记得，不如让入口不存在。

/** 建一个元素。props: class / text / dataset / style / value / aria-* / on* */
export function el(tag, props = {}, ...children) {
  if ('html' in props || 'innerHTML' in props) {
    throw new Error('el() 不收 html：产物里的字一律走 textContent');
  }
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'text') { node.textContent = String(v); continue; }
    if (k === 'class') { node.className = v; continue; }
    if (k === 'style' && typeof v === 'object') { Object.assign(node.style, v); continue; }
    if (k === 'dataset') { Object.assign(node.dataset, v); continue; }
    if (k.startsWith('on') && typeof v === 'function') {
      node.addEventListener(k.slice(2).toLowerCase(), v);
      continue;
    }
    node.setAttribute(k, v === true ? '' : String(v));
  }
  add(node, ...children);
  return node;
}

/** 追加子节点。数组会被展平，null/false 跳过（便于 `cond && el(...)`）。 */
export function add(parent, ...children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) { add(parent, ...c); continue; }
    parent.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return parent;
}

/** 换掉父节点的全部子节点。 */
export function mount(parent, ...children) {
  parent.replaceChildren();
  return add(parent, ...children);
}

export function clear(parent) { parent.replaceChildren(); return parent; }
