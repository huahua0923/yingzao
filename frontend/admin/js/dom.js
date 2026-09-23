// DOM 小工具 —— 建节点 / 填文本 / 清空 / 建表。就这四件事。
//
// ★ 一律不碰 innerHTML：这一屏上的字几乎全部来自产物 JSON（判据说明、阻塞原因、
//   房间号），拼 HTML 等于把产物内容当代码执行。所以文本只走 textContent，
//   而且连「设一个 html 属性」的入口都不留 —— el() 见到 html 直接抛，
//   免得以后有人图省事从那里开一个洞。
// ★ 不用框架：见 index.html 的注释。零构建是刻意选的，不再引入打包这一层失败面。

/**
 * 建节点。
 * @param {string} tag
 * @param {object} props  class / text / dataset / on* / 其余走 setAttribute
 * @param {...any} children  节点 | 字符串（走 textContent）| null/false（跳过）
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'html') {
      throw new Error('dom.el 不接受 html：产物内容只许走 text');
    }
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k === 'style') Object.assign(node.style, v);
    else if (k.startsWith('on') && typeof v === 'function') {
      node.addEventListener(k.slice(2), v);
    } else if (k === 'value' && 'value' in node) node.value = v;
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  add(node, children);
  return node;
}

/**
 * 追加子节点。**可变参数**：`add(root, a, b, c)` 与 `add(root, [a, b])`
 * 与 `add(root, node)` 三种写法都必须收。
 *
 * ★★ 这里必须是可变参数，不能是 `add(parent, children)` 两参形式：
 *   两参时 `add(root, h2, p, table)` 会把第 2 个之后的**全部静默丢掉** ——
 *   不报错、不警告，屏幕上就是"三个小标题下面什么都没有"。实测踩过：
 *   逐层验收单整张表不见了，而页面其余部分完全正常，看着像"这栋楼没有逐层结论"。
 *   这正是本项目最贵的一类失败（memory: silent-failure-needs-a-voice）：
 *   少画的东西不会喊，只会被读成"本来就没有"。
 *
 * 参数可以是数组（元素还能是嵌套数组）、单个节点、字符串，混着给也行。
 * 字符串 → 文本节点；null / undefined / false → 跳过（方便 `cond && node`）。
 */
export function add(parent, ...children) {
  for (const child of children) {
    const list = Array.isArray(child) ? child.flat(Infinity) : [child];
    for (const c of list) {
      if (c === null || c === undefined || c === false) continue;
      parent.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  }
  return parent;
}

/** 清空一个节点的子元素。 */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** 用新内容换掉一个节点的全部子元素。 */
export function mount(parent, ...children) {
  clear(parent);
  add(parent, children);
  return parent;
}

export function frag(...children) {
  return add(document.createDocumentFragment(), children);
}

/**
 * 表格。
 *
 * 一行的两种给法，都收：
 *   · 数组 = 每一格（节点或字符串，字符串走 textContent）—— 这时由本函数建 <tr>；
 *   · 一个**已经建好的 <tr> 节点** —— 这时直接进 tbody，不再包一层。
 * 第二种必须显式支持：调用方要按行加 class、要在单元格里挂事件时，
 * 它自己建 tr 最自然。若一律"把 cells 包进新 tr"，就会得到 <tr><tr>…，
 * 那是非法结构 —— 浏览器不报错，只渲染得莫名其妙（实测：整张表看着像没画）。
 *
 * @param {Array<{label:string, cls?:string}>} columns
 * @param {Array<Array<any>|Node>} rows
 * @param {{caption?:any, cls?:string, rowProps?:Function}} [opts]
 */
export function table(columns, rows, opts = {}) {
  const thead = el('thead', {}, el('tr', {},
    columns.map((c) => el('th', { class: c.cls || null, scope: 'col', text: c.label }))));
  const tbody = el('tbody', {});
  rows.forEach((row, i) => {
    if (row instanceof Node && row.tagName === 'TR') {
      tbody.appendChild(row);
      return;
    }
    const tr = el('tr', (opts.rowProps ? opts.rowProps(i) : {}) || {});
    add(tr, row.map((cell, j) =>
      cell instanceof Node ? cell : el('td', { class: columns[j]?.cls || null, text: String(cell ?? '') })));
    tbody.appendChild(tr);
  });
  return el('table', { class: opts.cls || null }, opts.caption && el('caption', { text: opts.caption }), thead, tbody);
}
