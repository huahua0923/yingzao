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

/**
 * 把带 `**强调**` 的**服务端串**渲染成 `<b>` 节点。
 *
 * ★ 为什么要有这一个函数：服务端几处判词里写着 markdown 强调记号
 *   （`annotations.why_not_merged`、`sitecheck.caveat` / `why_no_iou`），
 *   而页面用 `textContent` 落字 ⇒ **屏幕上会出现字面的两个星号**。
 *   2026-10-02 的冒烟就是这样：汇总页最显眼那一段印成
 *   「两个轴不许相加：**两个轴不许相加**：annotations 的 box 是…」，
 *   而**当时所有判据全绿** —— 判据查的是"那句不许相加在不在"，
 *   星号不在任何一条判据的分辨范围里（铁律 176：眼睛抓到的那处要补成判据）。
 *
 * ★ **不解析 HTML**：切分出来的每一段一律走 `createTextNode`。
 *   串里若还有别的记号，它只会原样显示成字，不会变成标签。
 *   （本仓另一处记过：往 innerHTML 注字符串这类口子，与其靠人记得，不如让入口不存在。）
 *
 * ★ 用它的地方有个前提：那个串**确实**按 `**` 成对写。落单的星号会原样留着 ——
 *   这是有意的，宁可印出来也不要悄悄吃掉（铁律 109：判词要能让读的人看出出处）。
 */
export function rich(s) {
  const frag = document.createDocumentFragment();
  String(s ?? '').split('**').forEach((part, i) => {
    if (part === '') return;
    if (i % 2 === 1) frag.append(el('b', { text: part }));
    else frag.append(document.createTextNode(part));
  });
  return frag;
}

export function clear(parent) { parent.replaceChildren(); return parent; }
