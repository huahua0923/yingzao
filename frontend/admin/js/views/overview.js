// 「总览」视图 —— 后台的门面。一屏看完 95 栋楼的状态，再决定去哪一屏深看。
//
// 路由： #/overview   （无子路由；楼栋明细在各自视图里）
//
// ★★ 这一屏**一个判断都不下**。所有数字都是从 `GET /api/buildings` 的那 95 行里
//   **数出来的**，这里没有阈值、没有"合格线"、没有状态词汇 —— 引擎在别处已经判过了，
//   前端复制一份判据，后端改口径时就会有一份悄悄错掉
//   （memory: criterion-invalidated-by-later-change）。
//
// ★★ 两条「不许静默」的规矩，与 checks.js 同一套：
//   1. 接口没起来 ⇒ **整屏画「接口不可用」，一个 KPI 都不画**。
//      画一排 0 是这一屏最坏的一种失败：它和"全库真的都是 0"在屏幕上长得一模一样
//      （memory: gauge-coverage-invisible-in-summary）。
//   2. 「0」与「没量到」必须长得不一样：0 是个**数**（琥珀字，且带说明），
//      字段缺失是「—」（灰斜体，title 说清"后端没给这个字段"）。
//      这个仓反复栽在这条上，所以下面 numCell() 把这两种情况分开画。
//      用琥珀不用红：红在这个色板里是"确定缺陷"（app.css 的注释），
//      rooms=0 是不是缺陷不归这一屏判 —— 它只是"需要人看"。
import { el, mount } from '../dom.js';
import { fmtInt } from '../fmt.js';
import { API, ApiError, get } from '../api.js';

export const label = '总览';

// 楼号与后端的 BuildingName 是同一条约束（^[A-Za-z0-9_-]{1,32}$）。
// 备注原文那条路要拿它拼 URL，所以先拦一道再拼。
const NAME_RE = /^[A-Za-z0-9_-]{1,32}$/;

// 侧栏/详情里要用的口径说明 —— 抄自 backend/api/services/artifacts.py 的注释，
// 逐字保留"这是哪个口径"，因为本仓面积有四个口径且**绝不许混用**。
const AREA_CAPTION = '各层 outline 面积之和（交付楼板面积）≠ 图纸面积表的口径';

const state = {
  rows: null,            // API.buildings() 的 data
  sortKey: 'outline_area_m2',
  sortDir: 'desc',
  q: '',
  zeroOnly: false,
  expanded: new Set(),   // 展开了备注原文的楼号
  notes: new Map(),      // 楼号 → [{key, text}] | {error}
  abort: null,
};

let disposed = false;

export function dispose() {
  disposed = true;
  state.abort?.abort();
  state.abort = null;
}

// ── 数的写法：0 / 缺失 / 数 ─────────────────────────────────────

/** 计数列。null/undefined = 后端没给这个字段 ⇒ 「—」，不是 0。 */
function numCell(value, cls = 'num') {
  if (value === null || value === undefined) {
    return el('td', { class: `${cls} ovw-missing`, text: '—',
                      title: '后端没给这个字段（它是"没量到"，不是 0）' });
  }
  const n = Number(value);
  if (Number.isNaN(n)) {
    return el('td', { class: `${cls} ovw-missing`, text: '—',
                      title: `后端给的不是数：${JSON.stringify(value)}` });
  }
  // ★ 0 要单独看得出来。45/95 栋房间数为 0，这个数值得被一眼看见，
  //   所以它不是普通的 0 —— 但也不上"错误色"：前端不判它是对是错。
  const zero = n === 0;
  return el('td', {
    class: `${cls}${zero ? ' ovw-zero' : ''}`,
    text: fmtInt(n),
    title: zero ? '这个数是 0（不是"没量到"—— 字段有值）' : null,
  });
}

/** 有/无 的写法：用字，不只靠颜色（色盲）。 */
function yesNoCell(has, onLabel, offLabel, extra = {}) {
  return el('td', { class: 'ovw-c-flag' },
    el('span', { class: `tag ${has ? 'good' : 'bad'}`, text: has ? onLabel : offLabel,
                 title: extra.title || null }));
}

// ── 列定义 ─────────────────────────────────────────────────────
//
// 排序只给"数得清、比得了"的列（app.css 的 thead th 默认 cursor:pointer，
// 不可排的列由 .ovw-nosort 把它按回去，不然会假装能点）。
const COLUMNS = [
  {
    key: 'title', label: '名称', cls: 'ovw-c-name', sortable: true, type: 'text',
    cell: (r) => el('td', { class: 'name ovw-c-name' },
      // 真链接放在名称格：行点击是给鼠标的便利，键盘/读屏走的是这个 <a>。
      el('a', { class: 'lnk', href: `#/ledger/${r.name}`, text: r.title || r.name,
                title: `打开台账 #/ledger/${r.name}` })),
  },
  {
    key: 'name', label: '代号', cls: 'ovw-c-code mono', sortable: true, type: 'text',
    cell: (r) => el('td', { class: 'mono ovw-c-code', text: r.name }),
  },
  {
    key: 'floor_count', label: '层数', cls: 'num ovw-c-sm', sortable: true, type: 'num',
    cell: (r) => numCell(r.floor_count, 'num ovw-c-sm'),
  },
  {
    key: 'rooms', label: '房间数', cls: 'num', sortable: true, type: 'num',
    cell: (r) => {
      const td = numCell(r.rooms);
      // 房间数为 0 时补一句"这不是没读"，免得它被当成缺失。
      if (Number(r.rooms) === 0) td.title = '后端报的 rooms = 0（是 0，不是缺失）';
      return td;
    },
  },
  {
    key: 'outline_area_m2', label: '轮廓面积 ㎡', cls: 'num ovw-c-area', sortable: true, type: 'num',
    cell: (r) => {
      const td = numCell(r.outline_area_m2, 'num ovw-c-area');
      td.title = `${AREA_CAPTION}${Number(r.outline_area_m2) === 0 ? '；本栋这个数是 0' : ''}`;
      return td;
    },
  },
  {
    key: 'has_model', label: '模型', cls: 'ovw-c-flag', sortable: false,
    cell: (r) => (r.has_model
      // 模型那一格给真链接，新窗口打开 —— 点它不该把这一屏弄丢。
      ? el('td', { class: 'ovw-c-flag' },
        el('a', { class: 'lnk', href: API.url.model(r.name), target: '_blank',
                  rel: 'noopener', text: 'GLB', title: `新窗口打开 ${API.url.model(r.name)}`,
                  onclick: (e) => e.stopPropagation() }))
      : el('td', { class: 'ovw-c-flag' },
        el('span', { class: 'tag bad', text: '无', title: '后端报 has_model = false' }))),
  },
  {
    key: 'has_cad', label: '图纸', cls: 'ovw-c-flag', sortable: false,
    cell: (r) => yesNoCell(r.has_cad, '有', '无',
      { title: 'has_cad = 该栋的图纸目录在后端存不存在' }),
  },
  {
    key: 'classifier', label: '分类器', cls: 'ovw-c-cls mono', sortable: false,
    cell: (r) => el('td', { class: 'mono ovw-c-cls' },
      el('span', { text: r.classifier || '—',
                   // 「(默认 lwpolyline)」不是一个识别出来的类别，是"配置里没写"。
                   // 这两件事在这一屏必须分开：48 栋走的是默认值，不是识别结果。
                   title: r.classifier ? null : '后端没给 classifier' }),
      (r.classifier || '').startsWith('(')
        ? el('span', { class: 'ovw-sub', text: '配置未写', title: '配置里没写 classifier，用的是默认值 —— 不是识别出来的类别' })
        : null),
  },
  {
    key: 'notes', label: '备注', cls: 'ovw-c-notes', sortable: false,
    cell: (r) => notesCell(r),
  },
];

/** 备注列：`_note*` 只是**键名**（后端只给键，原文在 `/api/buildings/{n}` 的 profile 里）。 */
function notesCell(r) {
  const keys = Array.isArray(r.notes) ? r.notes : [];
  if (!keys.length) {
    return el('td', { class: 'ovw-c-notes dim', text: '—',
                      title: '这栋楼的配置里没有 _note* 标记' });
  }
  const open = state.expanded.has(r.name);
  return el('td', { class: 'ovw-c-notes' }, keys.map((k) => el('button', {
    class: `ovw-tag${open ? ' open' : ''}`,
    type: 'button',
    text: String(k).replace(/^_note_?/, '') || String(k),
    title: `${k}　·　点开看原文（从 /api/buildings/${r.name} 现取）`,
    'aria-expanded': open ? 'true' : 'false',
    onclick: (e) => { e.stopPropagation(); toggleNote(r.name); },
  })));
}

// ── 备注原文（按需取，不在进屏时就打 95 次）──────────────────────

async function toggleNote(name) {
  if (state.expanded.has(name)) { state.expanded.delete(name); repaint(); return; }
  state.expanded.add(name);
  repaint();
  if (state.notes.has(name)) return;
  if (!NAME_RE.test(name)) {
    state.notes.set(name, { error: `楼号不合法，不拼 URL：${JSON.stringify(name)}` });
    repaint();
    return;
  }
  try {
    // ★ 走 get() 而不是 API.building()：只有 get() 收得下 signal，
    //   切走视图时这一条得能停掉（API.building 的签名里没有 signal）。
    const data = await get(`/api/buildings/${name}`, { signal: state.abort?.signal });
    if (disposed) return;
    const profile = (data && typeof data.profile === 'object' && data.profile) || {};
    const items = Object.entries(profile)
      .filter(([k]) => k.startsWith('_note'))
      .map(([k, v]) => ({ key: k, text: typeof v === 'string' ? v : JSON.stringify(v, null, 2) }));
    state.notes.set(name, items.length ? items : { empty: true });
  } catch (e) {
    if (disposed) return;
    state.notes.set(name, { error: e instanceof ApiError ? e.message : String(e) });
  }
  repaint();
}

/** 展开了就在那一行底下插一条整宽行 —— 原文是长文，塞进格子里没法读。 */
function noteDetailRow(r) {
  const got = state.notes.get(r.name);
  let body;
  if (!got) {
    body = el('p', { class: 'dim', text: `正在取 ${r.name} 的配置…` });
  } else if (got.error) {
    body = el('p', { class: 'miss', text: `备注原文没取到：${got.error}` });
  } else if (got.empty) {
    body = el('p', { class: 'dim', text: '配置里没有 _note* 字段（列表上那一列可能是别的来源）' });
  } else {
    body = el('div', {}, got.map((it) => el('div', { class: 'ovw-noteblock' },
      el('code', { class: 'ovw-notekey', text: it.key }),
      el('p', { class: 'ovw-notetext', text: it.text }))));
  }
  return el('tr', { class: 'ovw-detailrow' },
    el('td', { colspan: String(COLUMNS.length) },
      el('div', { class: 'ovw-detail' },
        el('div', { class: 'ovw-detail-h' },
          el('b', { text: r.title || r.name }),
          el('span', { class: 'dim', text: ` ${r.name} · 楼配置里的 _note* 原文（原样，未改一个字）` })),
        body)));
}

// ── 过滤与排序 ─────────────────────────────────────────────────

function visibleRows() {
  const q = state.q.trim().toLowerCase();
  let rows = state.rows;
  if (q) {
    rows = rows.filter((r) => String(r.name || '').toLowerCase().includes(q)
      || String(r.title || '').toLowerCase().includes(q));
  }
  if (state.zeroOnly) rows = rows.filter((r) => Number(r.rooms) === 0);
  const col = COLUMNS.find((c) => c.key === state.sortKey) || COLUMNS[0];
  const dir = state.sortDir === 'asc' ? 1 : -1;
  // 稳定排序：把原索引当兜底键，否则同值的行会在每次重画时换位置。
  const withIdx = rows.map((r, i) => ({ r, i }));
  withIdx.sort((a, b) => {
    const va = a.r[col.key];
    const vb = b.r[col.key];
    // 缺字段一律沉底，**不参与方向翻转** —— 缺失不是"最小的值"。
    const ma = va === null || va === undefined;
    const mb = vb === null || vb === undefined;
    if (ma || mb) return ma && mb ? a.i - b.i : (ma ? 1 : -1);
    let c;
    if (col.type === 'num') c = Number(va) - Number(vb);
    else c = String(va).localeCompare(String(vb), 'zh-Hans-CN');
    if (Number.isNaN(c)) c = 0;
    return c !== 0 ? c * dir : a.i - b.i;
  });
  return withIdx.map((x) => x.r);
}

function setSort(key) {
  if (state.sortKey === key) {
    state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    state.sortKey = key;
    // 换列时给一个"看得出毛病"的默认方向：数从大到小、名从 A 到 Z。
    state.sortDir = (COLUMNS.find((c) => c.key === key)?.type === 'num') ? 'desc' : 'asc';
  }
  repaint();
}

// ── 画面 ───────────────────────────────────────────────────────

/** 接口不可用 / 取数失败：说得比空表多，**且不画任何数**。 */
function panicPanel(err, onRetry, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const down = e.code === 'network' || e.status === 0;
  return el('div', { class: 'ovw-panic' },
    el('h2', { class: 'ovw-panic-h', text: down ? '接口不可用' : `取数失败：${e.code}` }),
    el('p', { class: 'ovw-panic-msg', text: e.message || String(err) }),
    el('div', { class: 'ovw-panic-body' },
      down
        ? el('div', {},
          el('p', {}, el('b', { text: '这一屏现在没有数可看 —— 所以这里一个数字都不画。' }),
            '画一排 0 是最坏的一种：它和"全库真的都是 0"在屏幕上长得一模一样。'),
          el('p', { class: 'dim' },
            '后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' }),
            '；启动命令：', el('code', { text: 'python -u backend/api/run_api.py' })))
        : el('p', { class: 'dim', text: '后端回了错误信封，下面是它给的原话。' }),
      opts.note ? el('p', { class: 'dim', text: opts.note }) : null,
      e.detail ? el('details', { class: 'ovw-details' },
        el('summary', { text: '后端给的细节（原样）' }),
        el('pre', { class: 'ovw-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
      onRetry ? el('div', { class: 'ovw-toolbar' },
        el('button', { class: 'ovw-btn primary', type: 'button', text: '重试', onclick: onRetry })) : null));
}

/** 顶部汇总。**每一个数都是从 state.rows 里加出来的**，没有一个来自常量。 */
function kpiStrip(rows) {
  const n = rows.length;
  const hasModel = rows.filter((r) => r.has_model).length;
  const hasCad = rows.filter((r) => r.has_cad).length;
  const zeroRooms = rows.filter((r) => Number(r.rooms) === 0).length;
  const zeroRoomsKnown = rows.filter((r) => r.rooms !== null && r.rooms !== undefined).length;
  const area = rows.reduce((a, r) => a + (Number(r.outline_area_m2) || 0), 0);
  const pct = (x) => (n ? Math.round((x / n) * 100) : 0);

  return el('div', { class: 'kpis ovw-kpis' },
    kpi('总栋数', fmtInt(n), '从 /api/buildings 的行数数出来的', null),
    kpi('有模型', fmtInt(hasModel), `${pct(hasModel)}% · has_model=true`, hasModel === n ? 'good' : null),
    kpi('有图纸', fmtInt(hasCad), `${pct(hasCad)}% · has_cad=true`, hasCad === n ? 'good' : null),
    kpi('轮廓面积合计', fmtInt(Math.round(area * 10) / 10), '㎡ · 各层 outline 之和（非图纸面积表）', null),
    // ★ 这一格是本屏的重点：rooms=0 不是个别现象，得让人一眼看见。
    kpi('房间数为 0', fmtInt(zeroRooms),
      zeroRoomsKnown === n ? `占 ${pct(zeroRooms)}% · 全库 ${n} 栋` : `只在 ${zeroRoomsKnown} 栋有 rooms 字段`,
      zeroRooms === 0 ? 'good' : (zeroRooms > n / 2 ? 'bad' : 'warn')));
}

function kpi(k, v, note, tone) {
  return el('div', { class: `kpi${tone ? ` ${tone}` : ''}` },
    el('span', { class: 'k', text: k }),
    el('span', { class: 'v', text: v }),
    el('span', { class: 'n', text: note }));
}

function toolbar(view) {
  const box = el('div', { class: 'toolbar ovw-toolbar' });
  box.appendChild(el('input', {
    type: 'search', value: state.q, placeholder: '搜名称 / 代号…',
    'aria-label': '按名称或代号过滤',
    oninput: (e) => { state.q = e.target.value; repaint({ keepFocus: 'q' }); },
  }));
  box.appendChild(el('label', { class: 'ovw-check' },
    el('input', {
      type: 'checkbox', checked: state.zeroOnly,
      onchange: (e) => { state.zeroOnly = e.target.checked; repaint(); },
    }),
    el('span', { text: `只看房间数 = 0（${state.rows.filter((r) => Number(r.rooms) === 0).length} 栋）` })));
  box.appendChild(el('span', { class: 'spacer' }));
  box.appendChild(el('span', { class: 'dim ovw-count',
    text: `显示 ${view.length} / ${state.rows.length} 行` }));
  return box;
}

function mainTable(view) {
  const cols = COLUMNS;
  const thead = el('thead', {}, el('tr', {}, cols.map((c) => {
    if (!c.sortable) {
      // app.css 把 thead th 的 cursor 定成 pointer（它的表都可排），
      // 这里得把不可排的列按回默认，不然它会假装能点。
      return el('th', { class: `ovw-nosort ${c.cls || ''}`, scope: 'col', text: c.label });
    }
    const active = state.sortKey === c.key;
    return el('th', {
      class: `ovw-sortable ${c.cls || ''}`,
      scope: 'col',
      'aria-sort': active ? (state.sortDir === 'asc' ? 'ascending' : 'descending') : 'none',
      // app.css 已有 th[data-dir] 的 ▲/▼ 规则，沿用它，别再画一个箭头。
      'data-dir': active ? state.sortDir : null,
      title: `按「${c.label}」排序${active ? '（再点一次反向）' : ''}`,
      onclick: () => setSort(c.key),
    }, c.label);
  })));

  const tbody = el('tbody', {});
  if (!view.length) {
    // 空表要说清是"筛掉了"还是"真没有" —— 这两种都不是"全都没问题"。
    const why = state.rows.length === 0
      ? '后端回了 0 栋楼 —— 是它那边真的没有，不是这一屏没读到。'
      : '这一屏的行都被过滤掉了（搜索词或"只看房间数=0"）。清掉过滤条件就都回来了。';
    tbody.appendChild(el('tr', {}, el('td', { colspan: String(cols.length), class: 'ovw-empty' },
      el('b', { text: '没有可显示的行。' }), why)));
  } else {
    for (const r of view) {
      const tr = el('tr', {
        class: 'ovw-row',
        title: `点这行打开台账 #/ledger/${r.name}`,
        onclick: (ev) => {
          // 格子里已有真链接时让它自己走，别再抢一次。
          if (ev.target.closest && ev.target.closest('a')) return;
          window.location.hash = `#/ledger/${r.name}`;
        },
      }, cols.map((c) => c.cell(r)));
      tbody.appendChild(tr);
      if (state.expanded.has(r.name)) tbody.appendChild(noteDetailRow(r));
    }
  }
  return el('table', { class: 'ovw-table' }, thead, tbody);
}

function paintBody(root) {
  const rows = state.rows;
  const view = visibleRows();
  const zeroRooms = rows.filter((r) => Number(r.rooms) === 0).length;

  mount(root, el('div', { class: 'ovw' },
    el('h1', { text: '总览 · 全库楼栋' },
      el('span', { class: 'sub', text: ' 后台的门面：一眼看完全库，再决定去哪一屏深看' })),

    el('p', { class: 'lede' },
      '这一屏的每个数都是从 ', el('code', { text: 'GET /api/buildings' }),
      ` 的 ${rows.length} 行里`, el('em', { text: '数出来的' }),
      '，前端一个判据都不算（结论在「检查」那一屏，由引擎给）。'),

    kpiStrip(rows),

    // ★ rooms=0 是这一屏最该被看见的信号，单独说一段，不只靠一个红数字。
    zeroRooms ? el('div', { class: 'note bad ovw-signal' },
      el('strong', { text: `⚠ ${zeroRooms} / ${rows.length} 栋的房间数是 0` }),
      el('span', { text: ' —— 这不是个别现象，是三分之一半的库。' }),
      el('br'),
      el('span', { class: 'dim' },
        '这里只说"后端报的 rooms 是 0"。至于为什么是 0（没抽到 / 图纸里本来没有房号 / '
        + '这栋楼的房间写在别处），不在这屏回答 —— 那是各栋检查产物与台账的事。'),
      el('div', { class: 'ovw-actions' },
        el('button', { class: 'ovw-btn', type: 'button',
          text: '只看这些栋',
          onclick: () => { state.zeroOnly = true; repaint(); } }),
        el('button', { class: 'ovw-btn', type: 'button',
          text: '去检查视图看结论',
          onclick: () => { window.location.hash = '#/checks'; } }))) : null,

    toolbar(view),

    el('div', { class: 'ovw-tablewrap' }, mainTable(view)),

    el('p', { class: 'dim ovw-foot' },
      '面积口径：', el('b', { text: AREA_CAPTION }),
      ' —— 本仓面积有多个口径，绝不许混用（图纸面积表是另一个数）。',
      el('br'),
      '「有模型 / 有图纸」是后端两个布尔字段的原值，不是这一屏的推断；',
      '「分类器」里的', el('code', { text: '(默认 …)' }), '表示那栋楼的配置没写分类器、走的是默认值，不是识别出来的类别。',
      el('br'),
      '点行 → 台账；「模型」那格的 GLB 是新窗口直连后端二进制路由（', el('code', { text: 'GET /api/buildings/{楼}/model.glb' }), '）。')));
}

function repaint(opts = {}) {
  if (disposed) return;
  const root = document.getElementById('main');
  if (!root) return;
  const q = state.q;
  paintBody(root);
  if (opts.keepFocus === 'q') {
    // 重画会换掉输入框 —— 光标得回到原处，否则打一个字就跳出搜索框。
    const input = root.querySelector('input[type=search]');
    if (input) { input.focus(); input.setSelectionRange(q.length, q.length); }
  }
}

// ── 视图入口 ────────────────────────────────────────────────────

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 总览没有子路由，给了也只是被忽略
 */
export async function render(root, sub) {
  disposed = false;
  state.abort = new AbortController();
  state.expanded = new Set();
  state.notes = new Map();
  if (sub) {
    // 不静默吞掉：有人手敲 #/overview/xxx 时要看得出来这个子路由不被使用。
    mount(root, el('div', { class: 'ovw-panic' },
      el('h2', { class: 'ovw-panic-h', text: '总览没有子路由' }),
      el('p', { class: 'ovw-panic-msg', text: `#/overview/${sub} 里的 "${sub}" 不会被用到 —— 总览是一屏表，没有下一层。` }),
      el('div', { class: 'ovw-toolbar' },
        el('button', { class: 'ovw-btn', type: 'button', text: '回总览',
          onclick: () => { window.location.hash = '#/overview'; } }))));
    return;
  }

  mount(root, el('div', { class: 'loading', text: '正在读楼栋清单…' }));
  try {
    // ★ 用 API.buildings() 而不是手拼 get()：契约在 api.js 一处，别在这边复制路径。
    //   代价是它收不下 signal，所以切走视图只能靠 disposed 兜住（下面每次都查）。
    // ★ API.buildings() 走的是 get()，**返回的就是 data 本身（数组）**，
    //   不是信封（信封是 getEnv 那条路）。这里第一次就写错过：把返回当信封取 .data，
    //   于是拿到 undefined，屏幕上跳的是自己画的 bad_shape 面板
    //   —— 面板救了这一次，但这正是"形状变了要喊出来"那条规矩的价值。
    const data = await API.buildings();
    if (disposed) return;
    if (!Array.isArray(data)) {
      // 后端回了 200 但形状不对 —— 这个也要说，不能当成"0 栋"。
      mount(root, panicPanel(new ApiError('bad_shape',
        `GET /api/buildings 该回一个数组，收到 ${data === null ? 'null' : typeof data}`),
      () => render(root, ''),
      { note: '这是我们这边的取数写法对不上后端的返回形状 —— 不是"全库 0 栋"。' }));
      return;
    }
    state.rows = data;
    paintBody(root);
  } catch (e) {
    if (disposed) return;
    mount(root, panicPanel(e, () => render(root, '')));
  }
}
