// 一点点 DOM 工具。
//
// ★ 全部走 `createElement` + `textContent`，**这个文件里没有 `innerHTML`**。
//   这一页要显示的东西里，房屋名称、用途、使用单位都是**别人填进来的文本**
//   （来自盘上的 rooms.json），拼 HTML 就等于把 XSS 的口子留在了自己家。
//   所以这里**刻意不提供** `html:` 这个属性 —— 留一个逃生口，迟早有人图省事用它，
//   而用它的那一处不会报错、只会在屏幕上正常显示。
//   要强调就加 `<b>`/`<em>` 节点，要换行就用两个节点。

/** 建元素。`attrs` 里 `class`/`text` 特别处理，其余走 setAttribute（再不行走 on*）。 */
export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = String(v);
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return n;
}

/** 清空一个节点。 */
export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/** 换掉一个节点的全部内容。 */
export function fill(node, ...children) {
  clear(node);
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

/** `dt/dd` 两栏表。`v === null/undefined/''` ⇒ 印"未填"而不是空白。 */
export function kv(pairs) {
  const dl = el('dl', { class: 'kv' });
  for (const [k, v] of pairs) {
    if (v === undefined) continue;                     // 整条不适用 ⇒ 不占行
    const empty = v === null || v === '' || v === '—';
    dl.appendChild(el('dt', { text: k }));
    dl.appendChild(el('dd', { class: empty ? 'na' : '', text: empty ? '未填' : String(v) }));
  }
  return dl;
}

/** 一个带标题的区块。`tag` 是右上角那枚小字（比如"实测"/"模拟"）。 */
export function block(title, tag, ...body) {
  const h = el('h4', {}, el('span', { text: title }));
  if (tag) h.appendChild(el('em', { text: tag }));
  return el('section', { class: 'block' }, h, ...body);
}

/** 章。`kind` ∈ live | mock | off —— 颜色是语义的，不是装饰的。 */
export const chip = (text, kind = 'off') => el('span', { class: `chip ${kind}`, text });

/**
 * 两种标记转成真节点：`**强调**` → `<b>`，`` `标识符` `` → `<code>`。
 * 返回一个 **DocumentFragment**。
 *
 * ★ 只有**作者写的说明文字**该用它（判词、注释的上屏版）。数据 —— 楼名、用途、
 *   使用单位，都是别人填进来的 —— 走 `el({text})` 或当字符串子节点塞，
 *   那里的 `**` 是数据里的星号、反引号是数据里的反引号，都不是标记。
 * ★ 实现是**建 `<b>` 节点 + `textContent`**，不是 `innerHTML` ⇒ 就算哪天在说明里
 *   插了数据，它也变不成标记（本文件顶上那条"没有 innerHTML"的规矩照旧）。
 *
 * ★★ 为什么把它单独抽出来（而不是留在 `note()` 里）：原来**只有 `note()` 认它**，
 *   而作者写的说明文字还有别的落点（页面导语 `lede2`、`kvList` 的值…）。
 *   那些地方的 `**` 会**原样上屏**——屏幕上出现两个星号，读的人以为是我写错了，
 *   而代码、控制台、判据**全都不出声**（铁律 015：源码里的标记被当成屏幕上的字）。
 *   抽出来是为了让"作者文字"只有一个加粗入口；真正兜底的那一条是屏幕级判据 ——
 *   验收脚本会断言**整块渲染出来的文字里一个 `**` 都没有**（见 `_cockpit_shot.py` ⑪）。
 */
export function rich(text) {
  const frag = document.createDocumentFragment();
  const s = String(text ?? '');
  // ★ 标记**成对**才算标记。数是奇数说明我少写了一个 —— 那时**整段按纯文本走**，
  //   于是那两个裸星号/裸反引号会**留在屏幕上**，被 `_portal_verify.py` 的逐屏扫描
  //   当场抓红。反过来（"奇数也硬当标记"）会把后半段整段吃成加粗、屏幕上什么都看不出来。
  //   ⇒ 一个坏标记必须是**响**的。这里选的是让它响。
  const parts = ((s.match(/\*\*/g) || []).length % 2 === 1) ? [s] : s.split('**');
  for (let i = 0; i < parts.length; i++) {
    if (!parts[i]) continue;
    const bold = i % 2 === 1;
    const nT = (parts[i].match(/`/g) || []).length;
    const segs = (nT > 0 && nT % 2 === 1) ? [parts[i]] : parts[i].split('`');
    for (let j = 0; j < segs.length; j++) {
      if (!segs[j]) continue;
      // 粗体里的代码（`` **`x`** ``）只取**代码**那一个形态 —— 不值得为它再嵌一层。
      let node;
      if (j % 2 === 1) node = el('code', { text: segs[j] });
      else if (bold) node = el('b', { text: segs[j] });
      else node = document.createTextNode(segs[j]);
      frag.appendChild(node);
    }
  }
  return frag;
}

/**
 * 一段说明。`kind` ∈ '' | ok | err。
 *
 * ★ 认 `**强调**`（走 `rich()`）；不认的落点是 `el({text})`，理由见 `rich()` 的注释。
 */
export const note = (text, kind = '') => el('p', { class: `note ${kind}` }, rich(text));

/**
 * 口径抽屉 —— 「会改变判断、但不该压在画面上」的那几句说明。
 *
 * ★ 用户 2026-10-01：「现在每个页面有很多解释，这些没有啥用吧，只要功能」。
 *   可这些**不是**装饰性解释：比如「轮廓只覆盖图中间那一片」—— 不知道它，
 *   「图上没有轮廓」会被读成「那里没有房子」，那是**另一个结论**。
 *   两难的出路是**默认收起**：屏幕上只剩一行可点的小字，点开才是全文。
 *   ⇒ 验收脚本 `_p2_shots.py` 的 B 腿据此分档：屏上的成段文字必须是**数据读数**，
 *     说明文字只允许出现在 `<details class="caliber">` 里面。
 *   ★ 抽屉里的字照样要进「对比度」那一趟（它展开后仍压在世界上）。
 */
export function caliber(title, ...body) {
  return el('details', { class: 'caliber' },
    el('summary', {}, el('span', { text: title })), ...body);
}

/** 数字格式化（不许出现 `NaN`／`undefined` 这种字面量上屏）。 */
export function num(v, digits = 1, unit = '') {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits) + unit;
}

/** 千分位整数。 */
export function int(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return Math.round(n).toLocaleString('zh-CN');
}

/**
 * 一排 KPI 卡。**列数由条数算出来**，不是 CSS 里写死的 —— 写死 4 列时，
 * 纵览驾驶舱那 6 张会剩两格空着（用户 2026-10-01 一眼看出来的那条）。
 *
 * 规则：`n ≤ 4` 排一行；多于 4 张就拆两行，每行 `ceil(n/2)` 张
 * （6 ⇒ 3×2 排满；5 ⇒ 3+2；8 ⇒ 4×2 排满）。两行以上时列数必须是
 * 「能整除或只差一格」，否则右下角又会空出来。
 */
export function statBox(pairs) {
  const n = pairs.length;
  const cols = n <= 4 ? n : Math.ceil(n / 2);
  const s = el('div', { class: 'stats' });
  s.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  for (const [v, k] of pairs) {
    s.appendChild(el('div', {}, el('b', { text: v }), el('small', { text: k })));
  }
  return s;
}
