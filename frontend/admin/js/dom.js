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
    else if (k === 'title') node.setAttribute('title', plain(v));
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

/**
 * 把重点标记渲染成**真加粗** —— 仍然只建元素，不碰 innerHTML。
 *
 * 为什么要有这一支（实测 2026-09-26，控制台首屏第一行就看得见）：
 *   帮助文字（`.csl-fhelp`）、阶段说明（`.csl-stagedesc`）、阻塞原因（`.csl-why`）、
 *   自检告警原文（`<li>`）这几处的内容**来自后台** ——
 *   `config/branches.json` 的 `_说明` / `_字段` / `开关[n].why`，以及管道定义。
 *   那些字符串是用 markdown 星号标重点的，而它们走 `el(..., {text})`
 *   ⇒ `textContent` ⇒ 页面上**原样印出星号**（`.sc-row b` 那条 CSS 说明
 *   设计上本来是要真加粗的，只是没有一条通道把标记变成元素）。
 *
 * ★ 为什么是「渲染」而不是「把星号从后台删掉」：
 *   那几处文字是**用户自己在后台写、自己改**的（用户原话：写在后台、我后面能修改、
 *   不是写死再代码里面）。把标记从用户的内容里删掉＝擅自改写用户的数据；
 *   渲染出来则相反 —— 用户以后在后台写「重点」，页面上就真的加粗。
 *
 * ★ 渲染不了的通道：`setAttribute('title')` 与 `window.confirm()` 只有纯文本，
 *   没有加粗这回事 —— 走那两个通道的字符串要过 `plain()`（下面那支）把标记去掉。
 *   `el()` 的 `title` 分支已经统一走 `plain()`；`confirm()` 不在 `el()` 里，调用点自己写。
 *
 * 落单的标记（只有一个）**原样印出来**，不吞掉：后台少打一个星号是真错误，
 * 把它变成一次看不见的删除，比印出来更坏。
 * @param {string} text
 * @returns {DocumentFragment}
 */
export function rich(text) {
  const out = document.createDocumentFragment();
  const s = text === null || text === undefined ? '' : String(text);
  const M = '**';
  let i = 0;
  for (;;) {
    const a = s.indexOf(M, i);
    if (a < 0) break;
    const b = s.indexOf(M, a + M.length);
    if (b < 0) break;                        // 落单 ⇒ 余下的按普通文字收尾
    const inner = s.slice(a + M.length, b);
    // 空标记、跨行标记都不当强调（跨行多半是前后两句各自落了单）
    if (inner === '' || inner.indexOf('\n') >= 0) { i = a + M.length; continue; }
    if (a > i) out.appendChild(document.createTextNode(s.slice(i, a)));
    out.appendChild(el('b', { text: inner }));
    i = b + M.length;
  }
  out.appendChild(document.createTextNode(s.slice(i)));
  return out;
}

/**
 * 把重点标记**去掉**，只留文字 —— 给**渲染不了加粗**的通道用。
 *
 * 为什么要有这一支（实测 2026-09-26，`rooms` 那一步的 ⚠ 徽章）：
 *   `setAttribute('title')`（悬停提示）与 `window.confirm()`（确认框）都只有纯文本，
 *   没有「加粗」这回事。同一条后台字符串走 `rich()` 的通道是真加粗，
 *   走这两个通道时若不处理，屏幕上/悬停里就是原样的 `**不在 git**` ——
 *   星号被当成正文印出来。实测抓到 1 条：悬停 `★ 覆盖即不可回滚：rooms.json 是交付件，**不在 git**，…`
 *
 * ★ 这不是「把用户的内容改掉」：内容一个字没动（`plain` 只在这两个通道上
 *   把标记降级成纯文本），后台里那对星号该怎么写还怎么写。
 *   `el()` 的 `title` 分支**统一**走这里，所以以后新加的 title 自动被覆盖 ——
 *   判据跟着通道走，不靠在每个调用点记得写一遍（铁律 29：一个判断不许两份实现）。
 *
 * 配对规则**必须与 `rich()` 逐字一致**：空标记、跨行标记都不当强调，
 * 落单的标记**原样留着**（后台少打一个星号是真错误，吞掉比印出来更坏）。
 * @param {string} text
 * @returns {string}
 */
export function plain(text) {
  const s = text === null || text === undefined ? '' : String(text);
  const M = '**';
  let out = '', i = 0;
  for (;;) {
    const a = s.indexOf(M, i);
    if (a < 0) break;
    const b = s.indexOf(M, a + M.length);
    if (b < 0) break;                        // 落单 ⇒ 余下的按普通文字收尾
    const inner = s.slice(a + M.length, b);
    if (inner === '' || inner.indexOf('\n') >= 0) { i = a + M.length; continue; }
    out += s.slice(i, a) + inner;
    i = b + M.length;
  }
  return out + s.slice(i);
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
