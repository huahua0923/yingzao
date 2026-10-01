// 「流程开关」视图 —— 回答用户那句「**哪些是单独的流程**」。
//
// ★ 这一屏的每一个字都来自**后台的文件**（`config/branches.json`），前端不算、不猜、
//   不缓存判断：54 行、每行的 `kind` 三档、以及「单独立项」到底指什么，全是那个文件
//   自己写的（它的 `_说明` / `_字段` 两节就是给人读的）。用户原话：
//   「这些你要写在后台，我后面能修改，能成图，不是写死再代码里面」——
//   所以这一屏只做三件事：把后台的表画出来、让那四列能在页面上改、把改动落到那个文件上。
//
// ★★ 三条从后端契约继承下来的规矩（改了前端就会与后端对不上）：
//
//   1. **`kind=单独` 就是「单独流程」**，不是「取值因楼而异」。后者是另一个量
//      （`branches.json` 自己实测两者不符 38/54 行）。所以本文件**不许**用
//      `c006` / `n_consumers` 去推断或纠正 `kind` —— 那两个是现量列，与语义无关。
//      判断只有一份实现：后端 `branch_table()` 给回来的 `note`，这里只负责印。
//
//   2. **人写四列可改，现量列只读。** 现量列（`c006` / `consumers` / `n_consumers` /
//      `loaders` …）由生成器 `_scratch/_gen_branches.py` **每次重跑重写** ⇒ 页面上改它们
//      会「看起来保存成功了、下次重跑就被冲掉」。所以这一屏把它们画成**灰的、没有输入框**，
//      并在列头写明为什么 —— 「改不了」与「忘了做输入框」在屏幕上必须不是同一行字。
//
//   3. **保存要带乐观锁（`expect_sha12`）。** 不带的话，页面开着的时候生成器重跑一遍，
//      用户在旧表上改的那一行会**盖在**新表上，而屏幕上写着「已保存」。
//      后端回 409 `branches_stale` 时，这里把那句话**原样**显示出来 + 提示重新载入，
//      不自己再编一句。
//
// ★ 布局上一处刻意：表格 `table-layout: fixed` + 单元格 `overflow-wrap: anywhere`
//   （见 branches.css）。本仓栽过一次（memory: value-column-pushed-offscreen）：
//   表写了 `width:100%` 却没写 `table-layout`，某列被最宽那行撑到 854px、横向溢出视口
//   ⇒ **14 行读数全画在屏幕外**，而 `textContent.includes(...)` 的判据**全绿**。
//   这一屏的 `why` 列必然长（那是一整句话），所以这条不是可选项。
import { el, mount, table, rich, plain } from '../dom.js';
import { API } from '../api.js';

export const label = '流程开关';

/** 有未保存改动的 key。★ 模块级：因为「重新载入」与「改完 kind 重排分组」这两条路
 *  都可能在用户正编着别的行时发生 —— 静默丢掉用户的输入是最坏的一种。 */
let dirtyKeys = new Set();
/** 跨一次重绘要带过去的一句话（改完 kind 要重排分组，重绘会把行尾提示冲掉）。 */
let flash = null;

export function dispose() {
  dirtyKeys = new Set();
  flash = null;
}

/** kind 的配色。**只用于显示**，不参与任何判断。三档之外原样落回中性色。 */
const KIND_CLS = { 公共: 'is-pub', 单独: 'is-solo', 死键: 'is-dead' };
/** 三档各自是什么意思。★ 这是**显示用的复述**，不是判据 ——
 *  判据在后端的 `note` 里（唯一一份实现），这里印的是它的同义中文。 */
const KIND_DESC = {
  公共: '全库走同一条规则 —— 改它等于改所有楼。',
  单独: '★ 这就是「单独流程」：必须逐栋决定的那一批。',
  死键: '载入后无人读 ⇒ 不属于任何一条流程（既不是「公共」也不是「单独」）。',
};

function kindCls(k) { return KIND_CLS[k] || 'is-other'; }

function shortName(p) {
  if (!p) return '（无）';
  return String(p).split(/[\\/]/).pop();
}

function fmtVal(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** 「载入它的通道」这一列。
 *  ★ `loaders` 的形状是**从一条真实记录里读出来的**，不是推的（铁律 93）：
 *    实测 `/api/console/branches` 回的是 **dict** —— atrium_from 那只为
 *    {'批': true, '台': false, 'GLB档': false}，既不是 list 也不是字符串。
 *    （`批` 与行里的 in_batch_loader、`台` 与 in_console_loader 各自对得上。）
 *  ⇒ 取**为真**的那些通道名；一个都不为真 ⇒ `（无）`。
 *     `（无）` 与 `—` 必须分开写：前者是「哪个通道都不载入它」，后者是「没有这个字段」。
 *  ★ 旧版落到 `String(l)` ⇒ 字典被印成字面量 `[object Object]`，
 *    而那行字**看起来就像「这个字段本来就这样」**，不会有人去查（铁律 16 的同族）。 */
function loadersOf(row) {
  const l = row.loaders;
  if (l === null || l === undefined) return '—';
  if (Array.isArray(l)) return l.join('、') || '—';
  if (typeof l === 'object') {
    const on = Object.keys(l).filter((k) => l[k]);
    return on.length ? on.join('、') : '（无）';
  }
  return String(l);
}

// ── 顶部：这一屏是什么 ────────────────────────────────────────────

function paintHead(meta, onReload) {
  const counts = meta.counts || {};
  const kinds = meta.kinds || [];
  const total = meta.total || 0;

  const card = (t, n, cls, hint) => el('div', { class: 'br-card ' + cls },
    el('b', { class: 'br-card-n', text: String(n) }),
    el('span', { class: 'br-card-l', text: t }),
    el('span', { class: 'br-card-h', text: hint }));

  // 成图（一）：三档占比的横条。`flexGrow` 用**条数**，所以宽度就是占比；
  // 分母 `total` 印在紧挨着的卡片上 —— 「29 单独」与「29 单独、共 54」不是同一件事。
  const bar = el('div', {
    class: 'br-bar',
    role: 'img',
    'aria-label': kinds.map((k) => `${k} ${counts[k] || 0} 条`).join('，'),
  }, kinds.map((k) => {
    const n = counts[k] || 0;
    if (!n) return null;
    return el('div', {
      class: 'br-bar-seg ' + kindCls(k),
      style: { flexGrow: String(n) },
      title: plain(`${k} ${n} / ${total}`),
    }, el('span', { text: String(n) }));
  }));

  return el('header', { class: 'br-head' },
    el('div', { class: 'br-title' },
      el('h2', { text: '流程开关' }),
      el('p', { class: 'br-sub' },
        '这一屏画的是 ', el('code', { text: meta.path || 'config/branches.json' }),
        ' —— 仓库里的那份登记表，不是代码里的表；里面的字是你自己写的，可以直接改。')),
    el('div', { class: 'br-cards' },
      card('单独流程', counts['单独'] || 0, 'is-solo', '必须逐栋决定的那一批'),
      card('公共流程', counts['公共'] || 0, 'is-pub', '全库同一条规则'),
      card('死键', counts['死键'] || 0, 'is-dead', '载入后无人读'),
      card('合计', total, '', '本文件 `开关` 数组的长度')),
    bar,
    // 后端那句 note 走 rich()：它是用户写在后台的，`**` 在页面上要**真加粗**
    // （dom.js 的 rich() 就是为这件事加的）。自己把星号剥掉或原样印出来都不对。
    el('p', { class: 'br-note' }, rich(meta.note || '')),
    el('div', { class: 'br-meta' },
      el('span', {}, el('b', { text: '指纹 ' }), el('code', { text: meta.sha12 || '—' })),
      el('span', {}, el('b', { text: '字节 ' }), el('code', { text: String(meta.bytes ?? '—') })),
      el('span', {}, el('b', { text: '来源 ' }), el('code', { text: meta.source || '—' })),
      // confirm() 只有纯文本、渲染不了加粗 ⇒ 那句话走 plain()（见 dom.js 的 plain 注释）。
      el('button', {
        class: 'br-btn', type: 'button', text: '重新载入', onclick: onReload,
        title: plain('重新读一遍那个文件；页面上没保存的输入会丢掉'),
      })));
}

// ── 一行 ────────────────────────────────────────────────────────

/** 一个可改的格子。★ **常驻**，不做「点一下变成输入框」：
 *  条件渲染出来的输入框带着「值在不在 DOM 里」这一类状态，而那一类状态出错时不报错。 */
function editCell(row, field, orig, saver, opts = {}) {
  const tag = opts.tag || 'input';
  const props = {
    class: 'br-in' + (opts.wide ? ' br-in-wide' : ''),
    value: orig ?? '',
    'aria-label': `${row.key} 的 ${field}`,
    title: String(orig ?? ''),
  };
  if (tag === 'textarea') props.rows = opts.rows || 2;
  const node = el(tag, props);
  const mark = () => {
    node.classList.toggle('is-dirty', node.value !== (orig ?? ''));
    saver.update();
  };
  node.addEventListener('input', mark);
  node.addEventListener('change', mark);
  row._inputs[field] = node;
  return node;
}

/** 行尾的保存 / 撤销。两个按钮常驻，用 `disabled` 表达「现在用不上」 ——
 *  「按不动」与「这个按钮不存在」在屏幕上必须分得开。 */
function makeSaver(state, key) {
  const btn = el('button', { class: 'br-btn br-btn-save', type: 'button', text: '保存' });
  const undo = el('button', { class: 'br-btn br-btn-undo', type: 'button', text: '撤销' });
  const msg = el('span', { class: 'br-rowmsg' });

  const api = {
    btn, undo, msg,
    /** 只在**人写四列**里比现值与起手值。`kind` 用的就是真的 `<select>`，
     *  `.value` 一样读得到 —— 所以这里不需要任何替身对象。 */
    dirty() {
      const row = state.byKey.get(key);
      if (!row) return null;
      const out = {};
      for (const f of state.authored) {
        const inp = row._inputs[f];
        if (!inp) continue;
        if (inp.value !== (row[f] ?? '')) out[f] = inp.value;
      }
      return Object.keys(out).length ? out : null;
    },
    update() {
      const d = api.dirty();
      const n = d ? Object.keys(d).length : 0;
      btn.disabled = n === 0;
      undo.disabled = n === 0;
      if (n) dirtyKeys.add(key); else dirtyKeys.delete(key);
      msg.textContent = n ? `${n} 处未保存` : '';
      msg.className = 'br-rowmsg' + (n ? ' is-dirty' : '');
      if (state.dirtyBox) markDirty(state);
    },
    reset() {
      const row = state.byKey.get(key);
      for (const f of state.authored) {
        const inp = row._inputs[f];
        if (inp) inp.value = row[f] ?? '';
      }
      api.update();
    },
    say(text, cls) { msg.textContent = text; msg.className = 'br-rowmsg ' + cls; },
  };
  return api;
}

function buildRow(state, row) {
  const saver = makeSaver(state, row.key);
  row._inputs = {};
  row._saver = saver;

  const consumers = Array.isArray(row.consumers) ? row.consumers : [];
  const n = typeof row.n_consumers === 'number' ? row.n_consumers : null;
  // 成图（二）：消费方条数的小横条。分母 `state.maxN` **从数据来**，不写死 ——
  // 写死的最大值在表变长之后会静默画错，而屏幕上只是「条短了一点」。
  const ratio = (n !== null && state.maxN > 0)
    ? Math.max(2, Math.round(100 * n / state.maxN)) : 0;

  const kindSel = el('select', {
    class: 'br-sel ' + kindCls(row.kind),
    'aria-label': `${row.key} 的 kind`,
    title: plain('三档：公共 / 单独 / 死键。改它只改这一行的语义标签，不改任何取值。'),
  }, (state.kinds || []).map((k) => {
    const o = el('option', { value: k, text: k });
    if (k === row.kind) o.selected = true;
    return o;
  }));
  row._inputs.kind = kindSel;
  kindSel.addEventListener('change', () => {
    kindSel.className = 'br-sel ' + kindCls(kindSel.value);
    row._pendingKind = kindSel.value !== row.kind;
    saver.update();
  });

  saver.btn.addEventListener('click', () => saveRow(state, row, saver));
  saver.undo.addEventListener('click', () => { row._pendingKind = false; saver.reset(); });

  const tr = el('tr', { class: 'br-tr ' + kindCls(row.kind), 'data-key': row.key },
    // `step` = 这条开关在流程的哪一步被读 —— 用户要看的正是这个，所以它挨着 key 放。
    // 它可改，因此是输入框，不是文本。
    el('td', { class: 'br-td-key' },
      el('code', { text: row.key }),
      editCell(row, 'step', row.step, saver)),
    el('td', {}, editCell(row, 'label', row.label, saver)),
    el('td', { class: 'br-td-kind' }, kindSel),
    el('td', { class: 'br-td-why' },
      editCell(row, 'why', row.why, saver, { tag: 'textarea', wide: true, rows: 2 })),
    el('td', { class: 'br-td-n' },
      n === null ? el('span', { class: 'br-none', text: '—' })
                 : el('span', { class: 'br-nwrap' },
                     el('b', { class: 'br-n', text: String(n) }),
                     el('span', { class: 'br-mini', 'aria-hidden': 'true' },
                        el('i', { style: { width: ratio + '%' } }))),
      el('span', { class: 'br-consumers', text: consumers.join('、') || '（无）' })),
    el('td', { class: 'br-td-c006' },
      el('code', { class: 'br-v', text: fmtVal(row.c006),
                   title: plain('c006 这一栋的取值（现量列，只读）') })),
    el('td', { class: 'br-td-loaders' },
      el('span', { class: 'br-loaders', text: loadersOf(row) })),
    el('td', { class: 'br-td-do' },
      el('div', { class: 'br-do' }, saver.btn, saver.undo), saver.msg));

  row._tr = tr;
  row._kindSel = kindSel;
  return tr;
}

// ── 保存 ────────────────────────────────────────────────────────

async function saveRow(state, row, saver) {
  const patch = saver.dirty();
  if (!patch) return;
  saver.btn.disabled = true;
  saver.undo.disabled = true;
  saver.say('保存中…', 'is-busy');

  let env;
  try {
    env = await API.consolePutBranch(row.key, patch, state.sha12);
  } catch (e) {
    // 两类必须分开说：
    //   · 409 = **文件在我读它之后被动了**（不是我错了）⇒ 原样显示服务端那句，提示重新载入；
    //   · 其余（400 非人写列 / 404 键不存在 / 500 写完自验失败）也一律显示服务端原话 ——
    //     前端自己编一句「保存失败」会把「是**哪一列**不合法」这个信息丢掉。
    const stale = e.status === 409 || e.code === 'branches_stale';
    saver.say((stale ? '表变了，这次没写：' : '没写成功：') + e.message,
              stale ? 'is-stale' : 'is-err');
    if (stale) saver.msg.title = plain('点顶部「重新载入」拿到最新一版，再改一遍');
    saver.btn.disabled = false;
    saver.undo.disabled = false;
    return;
  }

  const d = env.data || {};
  // ★ 指纹必须跟着更新：不更新的话，**第二次**保存会拿一个过期指纹去比，
  //   后端回 409 —— 而屏幕上看着像「文件被别人动了」，其实是我自己刚动的。
  if (d.sha_after) state.sha12 = d.sha_after;

  if (d.written === false) {
    saver.say('没有变化 ⇒ 没有写盘', 'is-warn');
    saver.update();
    return;
  }

  for (const [f, pair] of Object.entries(d.changed || {})) {
    row[f] = pair[1];
    const inp = row._inputs[f];
    if (inp) inp.value = pair[1];
  }
  const kindChanged = Object.prototype.hasOwnProperty.call(patch, 'kind');
  if (kindChanged) row.kind = patch.kind;
  row._pendingKind = false;
  row._tr.className = 'br-tr ' + kindCls(row.kind);
  saver.say(`已写盘 · ${state.sha12} · 留档 ${shortName(d.backup)}`, 'is-ok');
  saver.update();

  // 改过 kind ⇒ 这一行该归到**另一组**去了。分组是真的变了，所以要么重绘、
  // 要么说清「它暂时还在旧组里」。★ 只有在**没有别的行正编着**时才重绘 ——
  // 否则重绘会把别人没保存的输入一起冲掉（那正是 dirtyKeys 存在的理由）。
  if (kindChanged) {
    const others = [...dirtyKeys].filter((k) => k !== row.key);
    if (others.length === 0) {
      flash = { text: `${row.key} 的 kind 改成「${row.kind}」并已写盘；分组按新 kind 重排。`,
                cls: 'is-ok' };
      await state.rerender();
    } else {
      saver.say(`已写盘；kind=${row.kind}。还有 ${others.length} 行在编，`
                + '所以这一行暂时留在旧组，重新载入后归位。', 'is-warn');
    }
  }
}

function markDirty(state) {
  const box = state.dirtyBox;
  if (!box) return;
  const n = dirtyKeys.size;
  box.textContent = n ? `${n} 行有未保存的改动（切走这一屏就会丢）` : '';
  box.className = 'br-dirty' + (n ? ' is-on' : '');
}

// ── 主体 ────────────────────────────────────────────────────────

export async function render(root, sub) {
  dirtyKeys = new Set();
  let env;
  try {
    env = await API.consoleBranches();
  } catch (e) {
    // 读不到**要吵**：后端那边分得出「文件不在 / 读不了 / 版式不对」三句不同的话，
    // 原样透出来。空白页面与「这一屏本来就没做」在屏幕上是同一个样子（铁律 16）。
    mount(root, el('div', { class: 'br-panic' },
      el('h2', { text: '读不到开关登记表' }),
      el('p', { text: e.message || String(e) }),
      el('p', { class: 'br-panic-hint' },
        '这一屏的事实源是 ', el('code', { text: 'config/branches.json' }),
        '。它读不到 ⇒ 这一屏不作数 —— 这跟「一条开关都没有」不是同一件事。')));
    return;
  }

  const meta = env.meta || {};
  const rows = (env.data && env.data.rows) || [];
  const state = {
    authored: meta.authored_fields || ['label', 'kind', 'step', 'why'],
    kinds: meta.kinds || ['公共', '单独', '死键'],
    sha12: meta.sha12 || '',
    rows,
    byKey: new Map(),
    maxN: rows.reduce((m, r) => Math.max(m, Number(r.n_consumers) || 0), 0),
    dirtyBox: null,
    rerender: () => render(root, sub),
  };
  for (const r of rows) if (r && r.key) state.byKey.set(r.key, r);

  const head = paintHead(meta, () => {
    if (dirtyKeys.size && !window.confirm(
      plain(`有 ${dirtyKeys.size} 行改动没保存，重新载入会丢掉。继续？`))) return;
    render(root, sub);
  });
  const dirty = el('div', { class: 'br-dirty' });
  state.dirtyBox = dirty;
  const body = el('div', { class: 'br-body' });

  // 分组：`kind` 的语义在后台，但**哪一组先摆**是显示决定。把「单独」放最前 ——
  // 用户问的就是这一句（「再看看哪些是单独的流程」），不该让他在 54 行里找。
  // 其余各组按后端给的 `kinds` 顺序，前端不另排一套。
  const order = state.kinds.slice();
  const solo = order.indexOf('单独');
  if (solo > 0) order.unshift(order.splice(solo, 1)[0]);
  const buckets = new Map(order.map((k) => [k, []]));
  const other = [];
  for (const r of rows) {
    if (buckets.has(r.kind)) buckets.get(r.kind).push(r);
    else other.push(r);
  }
  if (other.length) buckets.set('（kind 不在这三档里）', other);

  const columns = [
    { label: '开关 / 步骤', cls: 'br-th-key' },
    { label: '名称（可改）', cls: '' },
    { label: '类别（可改）', cls: 'br-th-kind' },
    { label: '为什么（可改）', cls: 'br-th-why' },
    { label: '消费方（只读）', cls: 'br-th-n' },
    { label: 'c006（只读）', cls: 'br-th-c006' },
    { label: '载入它的通道（只读）', cls: 'br-th-loaders' },
    { label: '', cls: 'br-th-do' },
  ];

  for (const [kind, list] of buckets) {
    if (!list.length) continue;
    // ★ caption 必须是**字符串**：dom.js 的 table() 把它交给 `el('caption',{text})`
    //   ⇒ 传一个节点进去会被 textContent 串成 `"[object HTMLTableCaptionElement]"`，
    //   而那在屏幕上只是一行看着有点怪的标题，不报错。
    const cap = `${kind} 共 ${list.length} 条 / 全表 ${rows.length} 条`;
    const tbl = table(columns, list.map((r) => buildRow(state, r)),
                      { cls: 'br-table', caption: cap });
    body.appendChild(el('section', { class: 'br-sec' + (kind === '单独' ? ' is-solo' : '') },
      el('h3', { class: 'br-sec-h ' + kindCls(kind) },
        el('span', { class: 'br-sec-k', text: kind }),
        el('span', { class: 'br-sec-n', text: `${list.length} 条` }),
        el('span', { class: 'br-sec-d', text: KIND_DESC[kind] || '' })),
      tbl));
  }
  if (!rows.length) {
    body.appendChild(el('p', { class: 'br-empty' },
      '表里 0 行。★ 这一行与「读不到表」不是同一件事：读不到时出现的是上面那段红字。'));
  }

  const legend = el('p', { class: 'br-legend' },
    el('b', { text: '只读那三列为什么改不了：' }),
    '它们由 ', el('code', { text: '_scratch/_gen_branches.py' }),
    ' 每次重跑重新测量后重写 —— 在页面上改会「看起来保存成功了、下次重跑被冲掉」。',
    '所以后端直接 400 并**点名**是哪个键，不静默丢弃。现量列：',
    el('code', { text: (meta.measured_fields || []).join(' ') }), '。');

  mount(root, head, dirty, body, legend);
  markDirty(state);
  if (flash) {
    dirty.textContent = flash.text;
    dirty.className = 'br-dirty is-on ' + flash.cls;
    flash = null;
  }
}
