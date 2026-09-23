// 「台账」视图 —— 房间台账（`rooms.json`）的只读一览。
//
// 路由（hash，零依赖，可分享）：
//     #/ledger            全库台账概览：哪几栋有台账、各多少间，点进一栋
//     #/ledger/c113       该栋房间台账：汇总 / 按层筛 / 按房号搜 / 点表头排序
//
// 这一层**只显示后端产物里的字段**，一个数都不自己算（除了"把 area_m2 相加"这种
// 纯合计，且口径必须写在旁边 —— 见下）。
//
// ★★ 本屏最容易出事的不是"接不上"，是**把两个面积口径混在一起用**。
//   本仓有「面积四口径绝不许混用」这条铁律（memory: lihua-standardization-done），
//   而 rooms.json 里就同时躺着两个长得几乎一样的字段：
//
//     · `area_m2` = **房间净面积（墙内皮）**。两处独立出处都这么写：
//         backend/db/serve_rooms.py:10   「房间净面积 = 墙内皮（rooms.area_m2）」
//         backend/db/load_rooms_db.py:121 建表注释「room_net_m2 ... rooms.area_m2 之和」
//       值本身是房间多边形的面积：backend/extract/extract_rooms_generic.py:779
//       `"area_m2": round(g.area, 2)`。
//
//     · `area` = **图纸上印的标注面积**，是个字符串（"17.20m"）。
//       backend/db/rooms_registry.py:66 `"area_label": "图纸标注面积"`。
//       跟上面那个**不是一个口径**：c113 同一间房实测 17.20 vs 15.61（净面积<标注）。
//
//   所以这一屏的规矩是硬的：**只有 area_m2 允许相加**，合计旁边永远跟着
//   「口径：房间净面积（墙内皮）」和「N 行计入」；标注面积单独成列、标明来源，
//   永不参与求和。宁可少给一个数，也不给一个会被拿去用的数却不告诉他这是什么面积。
//   万一将来字段名对不上（后端改了名），这里是**报"口径不明"**，不是猜一个。

import { el, add, mount, clear } from '../dom.js';
import { fmtInt } from '../fmt.js';
import { API, ApiError } from '../api.js';

export const label = '台账';

// ── 口径 ────────────────────────────────────────────────────────
// 这三个字符串是全屏说"这是什么面积"的唯一出处，别在别处再写一遍（写两遍就会有一遍是旧的）。
const NET_AREA = {
  field: 'area_m2',
  name: '房间净面积（墙内皮）',
  short: '净面积',
  source: 'backend/db/serve_rooms.py:10 与 load_rooms_db.py:121',
};
const LABEL_AREA = {
  field: 'area',
  name: '图纸标注面积',
  short: '图纸标注',
  source: 'backend/db/rooms_registry.py:66',
};

const API_ADDR = () => window.GYM3D_API_BASE || '同源（当前页所在主机）';

// 楼号与后端 BuildingName 同一条约束（^[A-Za-z0-9_-]{1,32}$）。
// 前端先拦一道，是为了不让带斜杠的串进 URL 拼路径。
const NAME_RE = /^[A-Za-z0-9_-]{1,32}$/;

// 缺值在密集表里必须**看得见**：写「—」而不是留白。
// 留白在扫表时读不出来，会被当成"这一格我漏看了"。
const DASH = '—';
const nil = (v) => v === null || v === undefined || v === '';

/** 保留两位的面积写法（千分位；缺值走 —，不是 0）。 */
function fmtM2(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return DASH;
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 层号写法。后端给的是整数，且**可能是负的**（c009 有 -1 层）。 */
const floorText = (f) => (f === null || f === undefined ? DASH : `F${f}`);

// ── 列定义 ──────────────────────────────────────────────────────
// 逐列对着 `/api/buildings/c113/rooms` 的**真实返回**定的，不是按猜的。
// cmp: 'num' 数值比较 / 'text' 中文串比较 / null 不可排序。
const COLUMNS = [
  { key: 'number', label: '房号', cls: 'room', cmp: 'text' },
  { key: 'floor', label: '层', cls: 'num', cmp: 'num' },
  { key: 'purpose', label: '用途', cls: 'wrap', cmp: 'text' },
  { key: 'name', label: '名称', cls: 'wrap', cmp: 'text' },
  { key: 'area_m2', label: '净面积 m²', cls: 'net num', cmp: 'num',
    title: `${NET_AREA.name}（后端字段 ${NET_AREA.field}）` },
  { key: 'area', label: '图纸标注', cls: 'num', cmp: 'text',
    title: `${LABEL_AREA.name}（后端字段 ${LABEL_AREA.field}）—— 与净面积不同口径，不参与合计` },
  { key: 'dept', label: '使用单位', cls: 'wrap', cmp: 'text' },
  { key: 'centroid', label: '质心 x,y', cls: 'cen', cmp: null, title: '房间多边形质心（模型坐标，米）' },
  { key: 'bnd', label: '边界点', cls: 'num', cmp: 'num', title: '房间多边形顶点数（边界几何的规模）' },
  { key: 'id', label: 'id', cls: 'num', cmp: 'num', title: '台账里的全局房间 id（后端字段 id）' },
];

/** 取一行的某个可排/可显示值。`bnd` 和 `centroid` 是派生显示，不是后端原字段。 */
function valueOf(r, key) {
  if (key === 'bnd') return (r.boundary || []).length;
  if (key === 'centroid') return null;
  return r[key];
}

/**
 * 排序比较器。
 * ★ 空值**永远排在最后**，不参与方向翻转 —— 空不是 0，也不该在降序时冒充"最大"。
 */
function cmpRows(a, b, key, dir) {
  const col = COLUMNS.find((c) => c.key === key);
  const av = valueOf(a, key);
  const bv = valueOf(b, key);
  const an = nil(av);
  const bn = nil(bv);
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  const r = col?.cmp === 'num'
    ? Number(av) - Number(bv)
    : String(av).localeCompare(String(bv), 'zh');
  return dir === 'desc' ? -r : r;
}

// ── 生命周期 ────────────────────────────────────────────────────
// 切视图时 app.js 调 dispose()。★ api.js 的 API.rooms()/API.artifacts() 不接受 signal
// （它们没把 opts 透传下去），所以这里**没有** AbortController 可收 —— 收尾只能靠
// disposed 标志在 await 之后挡住绘制，绝不让上一轮的结果写进已经不属于它的节点。
// 这个限制写在明处：有朝一日 api.js 支持 signal 了，这里就应该换成真取消。
let disposed = false;
const view = { name: null, floor: 'all', q: '', sortKey: 'number', sortDir: 'asc' };

export function dispose() {
  disposed = true;
}

// ── 公共小件 ────────────────────────────────────────────────────

function busy(text) {
  return el('div', { class: 'ldg-busy' }, el('span', { class: 'spin' }), text);
}

function backLink(text = '← 换一栋') {
  return el('a', { class: 'ldg-btn', href: '#/ledger', text });
}

/**
 * 「取不到」面板 —— 连不上 / 没有这栋楼 / 路由 404 全走这里。
 * ★ 它和「这栋真的没有房间」（emptyPanel）**必须长得不一样**：
 *   把"取不到"画成 0 是本仓反复栽过的一条（memory: gauge-coverage-invisible-in-summary）。
 */
function downPanel(err, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const net = e.code === 'network' || e.status === 0;
  const box = el('div', { class: 'ldg-panic down' },
    el('h2', { text: net ? '取不到：连不上后端' : `取不到：${e.code}` }),
    el('p', { class: 'msg', text: e.message || String(err) }),
    el('p', {}, el('b', { text: '这不是「这栋没有房间」。' }),
      '这一屏拿不到任何数据 —— 所以下面一条台账都不画。'),
    el('ul', {},
      el('li', {}, '取数地址：', el('code', { text: opts.path || '—' })),
      el('li', {}, '后端地址：', el('code', { text: API_ADDR() })),
      net ? el('li', {}, '启动命令：', el('code', { text: 'python -u backend/api/run_api.py' })) : null,
      e.status ? el('li', {}, `HTTP 状态：${e.status}`) : null),
    opts.note ? el('p', { text: opts.note }) : null,
    e.detail ? el('details', {},
      el('summary', { text: '后端给的原话（原样）' }),
      el('pre', { text: JSON.stringify(e.detail, null, 2) })) : null,
    opts.onRetry ? el('div', { class: 'ldg-toolbar' },
      el('button', { class: 'ldg-btn', type: 'button', text: '重试', onclick: opts.onRetry })) : null);
  return box;
}

/**
 * 「这栋台账里真的没有房间」面板。
 * ★ 后端**成功**回了信封、数组长度为 0 才走这里 —— 是"零"，不是"没读到"。
 *   而且这里还能说得更细一层：产物清单里的 rooms.json 是**不存在**还是**空的**，
 *   两者都是 0 间房，但原因不同（一个是没跑过提取，一个是跑了没产出）。
 */
function emptyPanel(name, art) {
  const row = findArtifact(art, 'rooms');
  let why;
  // ★ 一律不用 markdown 记号（** / 反引号）：这些字直接进 textContent，
  //   落在屏幕上就是字面的星号和反引号。要强调就用 <b>，要示码就用 el('code')。
  if (!row) {
    why = '产物清单这次没取到，所以「rooms.json 在不在」这一层量不到 —— 只能说这份台账里是 0 行。';
  } else if (!row.exists) {
    why = '产物清单说：这栋楼的 rooms.json 不存在 —— 房间提取这一步还没跑过。';
  } else if (!row.bytes) {
    why = '产物清单说：rooms.json 在，但是 0 字节 —— 文件存在却没内容。';
  } else {
    why = `产物清单说：rooms.json 在（${fmtInt(row.bytes)} 字节），`
      + '但里面的数组是空的 —— 提取跑过了，产出 0 间房。';
  }
  return el('div', { class: 'ldg-panic empty' },
    el('h2', { text: `${name} 的台账里没有房间` }),
    el('p', { class: 'msg' },
      '后端回的是一份成功的信封，房间数组长度是 0。'),
    el('p', {}, el('b', { text: '这是「真的没有」，不是「取不到」。' }),
      '接口是通的，只是这栋楼交付了 0 间房（本仓全库 95 栋里有 45 栋是这样，'
      + '见 backend/checks/builtin.py 的那条判据）。'),
    el('p', { class: 'dim', text: why }),
    el('ul', {},
      el('li', {}, '取数地址：', el('code', { text: `/api/buildings/${name}/rooms` })),
      el('li', {}, '后端地址：', el('code', { text: API_ADDR() }))));
}

/** 从产物清单里挑一行（清单取不到就回 null，调用方各自处理"量不到"）。 */
function findArtifact(art, key) {
  const rows = Array.isArray(art?.data) ? art.data : (Array.isArray(art) ? art : null);
  if (!rows) return null;
  return rows.find((r) => r && r.key === key) || null;
}

// ── 概览页（#/ledger）────────────────────────────────────────────
//
// 这一屏回答的是「95 栋里哪几栋有台账、各多少间」，顺带当选楼入口。
// 全部数字来自 GET /api/buildings 的 `rooms` 字段（和台账行数是**两个来源**，
// 所以如果它们不一致，这一屏会说出来，而不是挑一个信 —— 见下面的 crossNote）。

const idxState = { q: '', sortKey: 'rooms', sortDir: 'desc' };

async function paintIndex(root) {
  mount(root, busy('正在读全库楼栋清单…'));
  let rows;
  try {
    rows = await API.buildings();
  } catch (e) {
    if (!disposed) mount(root, el('div', {}, downPanel(e, { path: '/api/buildings' })));
    return;
  }
  if (disposed) return;
  if (!Array.isArray(rows)) {
    mount(root, downPanel(new ApiError('bad_response', '楼栋清单不是数组'), { path: '/api/buildings' }));
    return;
  }
  paintIndexBody(root, rows);
}

function paintIndexBody(root, rows) {
  const host = el('div', {});
  const withRooms = rows.filter((b) => (b.rooms || 0) > 0);
  const zero = rows.length - withRooms.length;

  const countBox = el('div', { class: 'ldg-count' });
  const tbody = el('tbody', {});
  const table = el('table', { class: 'ldg-table' },
    el('thead', {}, el('tr', {}, IDX_COLUMNS.map((c) => {
      const th = el('th', {
        class: c.cmp ? (c.cls || null) : `${c.cls || ''} nosort`.trim(),
        scope: 'col', text: c.label, title: c.title || null, dataset: { key: c.key },
      });
      th.addEventListener('click', () => {
        if (idxState.sortKey === c.key) idxState.sortDir = idxState.sortDir === 'asc' ? 'desc' : 'asc';
        else { idxState.sortKey = c.key; idxState.sortDir = c.cmp === 'num' ? 'desc' : 'asc'; }
        paintRows();
      });
      return th;
    }))),
    tbody);

  function paintRows() {
    const q = idxState.q.trim().toLowerCase();
    const list = rows.filter((b) => {
      if (!q) return true;
      return String(b.name || '').toLowerCase().includes(q)
        || String(b.title || '').toLowerCase().includes(q);
    }).slice().sort((a, b) => {
      const av = a[idxState.sortKey];
      const bv = b[idxState.sortKey];
      const r = typeof av === 'number' || typeof bv === 'number'
        ? Number(av ?? 0) - Number(bv ?? 0)
        : String(av ?? '').localeCompare(String(bv ?? ''), 'zh');
      return idxState.sortDir === 'desc' ? -r : r;
    });

    clear(tbody);
    for (const b of list) {
      const n = b.rooms || 0;
      const tr = el('tr', {
        class: `pick${n ? '' : ' no-rooms'}`,
        tabindex: '0',
        title: `打开 ${b.name} 的房间台账`,
        dataset: { name: b.name },
      }, [
        el('td', { class: 'room', text: b.name }),
        el('td', { class: 'wrap', text: nil(b.title) ? DASH : b.title }),
        el('td', { class: 'num', text: fmtInt(b.floor_count) }),
        el('td', { class: n ? 'net num' : 'num nil', text: fmtInt(n) }),
        el('td', { class: 'wrap', text: Array.isArray(b.floors) && b.floors.length
          ? b.floors.map(floorText).join(' ') : DASH }),
        el('td', { class: 'num', text: fmtInt(b.outline_area_m2) }),
        el('td', { class: 'num', text: b.has_model ? '有' : DASH }),
      ]);
      const open = () => { window.location.hash = `#/ledger/${b.name}`; };
      tr.addEventListener('click', open);
      tr.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); }
      });
      tbody.appendChild(tr);
    }
    mount(countBox,
      `筛选后 `, el('b', { text: fmtInt(list.length) }), ` / ${fmtInt(rows.length)} 栋 · `,
      `有台账 ${fmtInt(withRooms.length)} 栋 · 交付 0 间 ${fmtInt(zero)} 栋`);
    for (const th of table.querySelectorAll('thead th')) {
      if (th.dataset.key === idxState.sortKey) th.dataset.dir = idxState.sortDir;
      else delete th.dataset.dir;
    }
  }

  const search = el('input', {
    type: 'search', placeholder: '楼号 / 名称关键词…',
    value: idxState.q, 'aria-label': '搜索楼号或名称',
    oninput: (ev) => { idxState.q = ev.target.value; paintRows(); },
  });

  mount(host,
    el('h1', { text: '台账 · 全库房间台账概览' },
      el('span', { class: 'sub', text: ' 哪几栋交付了房间、各多少间' })),
    el('p', { class: 'lede' },
      '一行一栋。数字来自 ', el('code', { text: 'GET /api/buildings' }),
      ' 的 rooms 字段 —— ', el('b', { text: '不是' }),
      '这次去逐栋读台账数出来的：它回答的是"有没有台账"，点进去才是台账本身。'),
    el('div', { class: 'ldg-toolbar toolbar' },
      el('label', { text: '搜索' }), search, countBox),
    table,
    el('p', { class: 'dim' },
      '注：这里的「房间数」是楼栋清单自己报的数；台账页里那个数是把 rooms.json 逐行数出来的。',
      '两个来源偶尔会不一致（清单是某一刻的汇总），进栋后如果对不上，台账页会当场指出来。'));
  paintRows();
  mount(root, host);
}

const IDX_COLUMNS = [
  { key: 'name', label: '楼号', cls: 'room', cmp: 'text' },
  { key: 'title', label: '名称', cls: 'wrap', cmp: 'text' },
  { key: 'floor_count', label: '层数', cls: 'num', cmp: 'num' },
  { key: 'rooms', label: '房间数', cls: 'num', cmp: 'num' },
  { key: 'floors', label: '层号', cls: 'wrap', cmp: null, title: '楼栋清单给的层号（F-1 表示地下一层）' },
  { key: 'outline_area_m2', label: '轮廓面积 m²', cls: 'num', cmp: 'num',
    title: '「外墙外围」口径（backend/api/services/artifacts.py 的 _shoelace(outline)）—— '
      + '与台账页的净面积不是一回事，别相加' },
  { key: 'has_model', label: '模型', cls: 'num', cmp: null },
];

// ── 栋内台账页（#/ledger/c113）──────────────────────────────────

async function paintLedger(root, name) {
  mount(root, busy(`正在读 ${name} 的房间台账…`));
  const path = `/api/buildings/${name}/rooms`;

  let env;
  try {
    env = await API.rooms(name);
  } catch (e) {
    if (disposed) return;
    mount(root, el('div', {}, el('div', { class: 'ldg-toolbar toolbar' }, backLink()),
      downPanel(e, { path, onRetry: () => paintLedger(root, name) })));
    return;
  }
  if (disposed) return;

  // 产物清单只为写清"这份台账是哪来的"（rooms.json 在不在 / 多大）。
  // ★ 取不到**不挡主数据** —— 但来源那一行会明说"量不到"，不会装了没看见。
  let art = null;
  try { art = await API.artifacts(name); } catch { art = null; }
  if (disposed) return;

  const rows = Array.isArray(env?.data) ? env.data : null;
  if (!rows) {
    mount(root, el('div', {}, el('div', { class: 'ldg-toolbar toolbar' }, backLink()),
      downPanel(new ApiError('bad_response', 'rooms 的 data 不是数组'), { path })));
    return;
  }
  if (!rows.length) {
    // 空台账也要写来源 —— "0 间"是从哪个文件读出来的，是这一屏最该说清的事之一。
    mount(root, el('div', {}, el('div', { class: 'ldg-toolbar toolbar' }, backLink()),
      emptyPanel(name, art), sourceLine(name, env, art)));
    return;
  }
  paintLedgerBody(root, name, env, art, rows);
}

/** 「这份台账是哪来的」那一行。★ 时间取不到就**明说取不到**，不留空也不编。 */
function sourceLine(name, env, art) {
  const row = findArtifact(art, 'rooms');
  const box = el('div', { class: 'ldg-src' });
  add(box, el('b', { text: '来源' }));
  add(box, el('code', { text: `data/${name}/rooms.json` }),
    el('span', { text: '· 路由 ' }), el('code', { text: `GET /api/buildings/${name}/rooms` }));
  if (row) {
    add(box, el('span', { text: '· 产物清单：' }),
      el('span', { text: row.exists ? `在，${fmtInt(row.bytes)} 字节` : '不存在' }));
  } else {
    add(box, el('span', { class: 'miss', text: '· 产物清单取不到，所以"文件在不在/多大"这一层量不到' }));
  }
  // meta 只有 count 与 per_floor（实测），没有文件名也没有时间戳 —— 所以这里不装。
  add(box, el('span', { text: '· 生成时间：' }),
    el('span', { class: 'miss', text: '后端未提供（meta 里只有 count / per_floor，没有时间戳）' }));
  return box;
}

function paintLedgerBody(root, name, env, art, rows) {
  // meta.per_floor 是后端给的**权威分层计数**，本屏的层筛选按它出选项。
  const perFloor = (env?.meta && env.meta.per_floor) || null;
  const floors = perFloor
    ? Object.keys(perFloor).map(Number).sort((a, b) => a - b)
    : Array.from(new Set(rows.map((r) => r.floor))).filter((f) => f !== null && f !== undefined)
      .sort((a, b) => a - b);

  // ★ 两个来源对不上时要说出来。meta.count 是后端数的行数，rows.length 是收到的行数；
  //   正常情况下恒等，不等就说明中间有东西掉了（分页/截断/信封坏了）。
  const metaCount = env?.meta?.count;
  const mismatch = typeof metaCount === 'number' && metaCount !== rows.length;

  const rowsHost = el('tbody', {});
  const countBox = el('div', { class: 'ldg-count' });
  const table = el('table', { class: 'ldg-table' },
    el('thead', {}, el('tr', {}, COLUMNS.map((c) => {
      const th = el('th', {
        class: c.cmp ? c.cls : `${c.cls || ''} nosort`.trim(),
        scope: 'col', text: c.label, title: c.title || null, dataset: { key: c.key },
      });
      if (c.cmp) {
        th.addEventListener('click', () => {
          if (view.sortKey === c.key) view.sortDir = view.sortDir === 'asc' ? 'desc' : 'asc';
          else { view.sortKey = c.key; view.sortDir = 'asc'; }
          paintRows();
        });
      }
      return th;
    }))),
    rowsHost);

  function filtered() {
    const q = view.q.trim().toLowerCase();
    return rows.filter((r) => {
      if (view.floor !== 'all' && String(r.floor) !== view.floor) return false;
      if (!q) return true;
      // 搜房号是主用途，但顺带扫用途/名称/单位 —— 都是同一批产物里的字，不额外查一次后端。
      return [r.number, r.purpose, r.name, r.dept]
        .some((v) => v && String(v).toLowerCase().includes(q));
    }).sort((a, b) => cmpRows(a, b, view.sortKey, view.sortDir));
  }

  function paintRows() {
    const list = filtered();
    clear(rowsHost);
    for (const r of list) {
      const c = Array.isArray(r.centroid) ? r.centroid : null;
      rowsHost.appendChild(el('tr', {}, [
        el('td', { class: 'room', text: nil(r.number) ? DASH : r.number }),
        el('td', { class: 'num', text: floorText(r.floor) }),
        el('td', { class: nil(r.purpose) ? 'wrap nil' : 'wrap', text: nil(r.purpose) ? DASH : r.purpose,
          title: r.purpose || null }),
        el('td', { class: nil(r.name) ? 'wrap nil' : 'wrap', text: nil(r.name) ? DASH : r.name }),
        el('td', { class: nil(r.area_m2) ? 'net num nil' : 'net num', text: fmtM2(r.area_m2),
          title: NET_AREA.name }),
        el('td', { class: nil(r.area) ? 'num nil' : 'num', text: nil(r.area) ? DASH : r.area,
          title: `${LABEL_AREA.name}（不参与合计）` }),
        el('td', { class: nil(r.dept) ? 'wrap nil' : 'wrap', text: nil(r.dept) ? DASH : r.dept,
          title: r.dept || null }),
        el('td', { class: 'cen', text: c && c.length === 2
          ? `${c[0]}, ${c[1]}` : DASH }),
        el('td', { class: 'num', text: fmtInt((r.boundary || []).length) }),
        el('td', { class: 'num', text: fmtInt(r.id) }),
      ]));
    }
    if (!list.length) {
      rowsHost.appendChild(el('tr', {},
        el('td', { class: 'nil', colspan: String(COLUMNS.length), text: '没有符合当前筛选条件的房间' })));
    }

    // ★ 合计**永远带分母和口径**。只写一个 9,902.86 会让人以为它代表这栋楼的全部面积。
    const netSum = list.reduce((a, r) => a + (Number(r.area_m2) || 0), 0);
    const netN = list.reduce((a, r) => a + (nil(r.area_m2) ? 0 : 1), 0);
    mount(countBox,
      `当前筛选 `, el('b', { text: fmtInt(list.length) }), ` / ${fmtInt(rows.length)} 间 · `,
      `${NET_AREA.short}合计 `, el('b', { text: fmtM2(netSum) }), ' m² ',
      el('span', { class: 'dim', text: `（口径：${NET_AREA.name}，${fmtInt(netN)} 行计入）` }));
    if (netN !== list.length) {
      add(countBox, el('span', { class: 'miss', text: ` ⚠ 有 ${fmtInt(list.length - netN)} 行没有净面积，未计入合计` }));
    }

    for (const th of table.querySelectorAll('thead th')) {
      if (th.dataset.key === view.sortKey) th.dataset.dir = view.sortDir;
      else delete th.dataset.dir;
    }
  }

  const floorSel = el('select', {
    'aria-label': '按层筛选',
    onchange: (ev) => { view.floor = ev.target.value; paintRows(); },
  }, [
    el('option', { value: 'all', text: `全部（${fmtInt(rows.length)} 间）` }),
    ...floors.map((f) => el('option', { value: String(f),
      text: `${floorText(f)}（${fmtInt(perFloor ? perFloor[String(f)] : rows.filter((r) => r.floor === f).length)} 间）` })),
  ]);
  floorSel.value = view.floor;

  const search = el('input', {
    type: 'search', placeholder: '房号 / 用途 / 名称 / 单位…',
    value: view.q, 'aria-label': '搜索房号关键词',
    oninput: (ev) => { view.q = ev.target.value; paintRows(); },
  });

  // 顶部汇总 —— 只给三个数，面积那个**写明口径**。
  const netTotal = rows.reduce((a, r) => a + (Number(r.area_m2) || 0), 0);
  const netTotalRows = rows.reduce((a, r) => a + (nil(r.area_m2) ? 0 : 1), 0);
  const kpi = el('div', { class: 'kpis' },
    el('div', { class: 'kpi' }, el('div', { class: 'k' }, '房间总数'),
      el('div', { class: 'v', text: fmtInt(rows.length) }),
      el('div', { class: 'n', text: metaCount === undefined ? 'meta 没给 count'
        : (mismatch ? `meta.count=${metaCount}，与收到的行数不符` : '与 meta.count 一致') })),
    el('div', { class: 'kpi' }, el('div', { class: 'k' }, '层数'),
      el('div', { class: 'v', text: fmtInt(floors.length) }),
      el('div', { class: 'n', text: floors.map(floorText).join(' ') || DASH })),
    el('div', { class: 'kpi' }, el('div', { class: 'k' }, `${NET_AREA.short}合计 m²`),
      el('div', { class: 'v', text: fmtM2(netTotal) }),
      el('div', { class: 'n', text: `口径：${NET_AREA.name} · ${fmtInt(netTotalRows)}/${fmtInt(rows.length)} 行计入` })));

  // 字段填充率：rooms.json 里这几个可选字段**可能整列为空**，
  // 而"整列为空"和"这栋没房间"是两件事 —— 分母写出来才分得清。
  const fill = el('div', { class: 'ldg-fill' }, FILL_FIELDS.map((f) => {
    const n = rows.reduce((a, r) => a + (nil(r[f.key]) ? 0 : 1), 0);
    return el('span', { class: `f${n ? '' : ' zero'}`, title: f.title || null },
      f.label, el('i', { text: `${fmtInt(n)}/${fmtInt(rows.length)}` }));
  }));

  mount(root, el('div', {},
    el('div', { class: 'ldg-toolbar toolbar' },
      backLink(),
      el('a', { class: 'ldg-btn', href: `#/drawings/${name}`, text: '看图纸' }),
      el('a', { class: 'ldg-btn', href: `#/checks/${name}`, text: '看检查单' })),
    el('h1', { text: `${name} · 房间台账` },
      el('span', { class: 'sub', text: ' 一行一间房，字段原样来自 rooms.json' })),
    sourceLine(name, env, art),
    caliberNote(),
    kpi,
    fill,
    mismatch ? el('div', { class: 'note bad' },
      el('strong', { text: '来源对不上：' }),
      `后端在 meta.count 里报 ${fmtInt(metaCount)} 行，但这次只收到 ${fmtInt(rows.length)} 行。`,
      '两个数都是后端给的，这里不替它选一个 —— 上面所有汇总按收到的行算。') : null,
    el('div', { class: 'ldg-floors' }, floors.map((f) => el('span', { class: 'fc' },
      el('b', { text: floorText(f) }),
      el('i', { text: `${fmtInt(perFloor ? perFloor[String(f)] : rows.filter((r) => r.floor === f).length)} 间` })))),
    el('div', { class: 'ldg-toolbar toolbar ldg-toolbar' },
      el('label', { text: '层' }), floorSel,
      el('label', { text: '搜索' }), search,
      countBox),
    table,
    el('p', { class: 'dim' },
      '点表头排序（空值恒排在最后，不参与升降序翻转）。',
      '「质心」「边界点」两列是从 centroid / boundary 两个字段派生的显示，不是后端原字段名。')));

  paintRows();
}

const FILL_FIELDS = [
  { key: 'purpose', label: '用途', title: '用途（后端字段 purpose）' },
  { key: 'dept', label: '使用单位', title: '使用单位（后端字段 dept）' },
  { key: 'name', label: '名称', title: '名称（后端字段 name）' },
  { key: 'area', label: LABEL_AREA.short, title: `${LABEL_AREA.name}（后端字段 area，字符串）` },
  { key: 'area_m2', label: NET_AREA.short, title: `${NET_AREA.name}（后端字段 area_m2，数值）` },
];

/** 口径说明带 —— 常驻，不是脚注。 */
function caliberNote() {
  return el('div', { class: 'ldg-caliber' },
    el('b', { text: '面积口径' }),
    el('span', {}, '本页', el('b', { text: '所有合计' }), '只用 ',
      el('code', { text: NET_AREA.field }),
      `＝${NET_AREA.name}（出处：${NET_AREA.source}）。`),
    el('span', { class: 'warn' },
      `「${LABEL_AREA.short}」列（${LABEL_AREA.field}，来源：${LABEL_AREA.source}）是另一个口径`
      + ' —— 图纸上印的数，本页永不把它加进合计，两列也不许相加。'),
    el('span', { class: 'dim', text: '注：本页没有「建筑面积／外墙外围」这个口径的数，要看它请去面积视图。' }));
}

// ── 视图入口 ────────────────────────────────────────────────────

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 形如 '' 或 'c113'
 */
export async function render(root, sub) {
  disposed = false;
  const name = (sub || '').trim();
  if (!name) return paintIndex(root);
  if (!NAME_RE.test(name)) {
    mount(root, el('div', {}, el('div', { class: 'ldg-toolbar toolbar' }, backLink()),
      downPanel(new ApiError('bad_request',
        `楼号只接受字母数字与 -_（最多 32 位）：${JSON.stringify(name)}`),
      { path: '（没发出去：楼号不合法，前端先拦下了）' })));
    return;
  }
  // 换了栋就把筛选/排序复位 —— 上一栋的层号留在下拉里，下一栋很可能没有那一层，
  // 会变成"打开就是一屏空表"，看着像这栋没房间。
  if (view.name !== name) {
    view.name = name; view.floor = 'all'; view.q = ''; view.sortKey = 'number'; view.sortDir = 'asc';
  }
  return paintLedger(root, name);
}
