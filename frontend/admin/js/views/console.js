// 「建模控制台」视图 —— 原 `backend/web/control.py`（8130）那一屏，2026-09-25 并进管理台。
//
// ★ 为什么是**原生视图**而不是 iframe（计划里复核过一次，推翻了初稿）：
//   `control.html` + `control.js` 一共只有 39 KB，而管理台的文档 URL **永远是 `/`**
//   （hash 路由）。于是 `control.js` 里那几处 `data/buildings/...` 相对引用
//   **一行都不用改**就指向了 `/data/buildings/...`。
//   ★ 是 iframe 自己制造了「基址」这个难题：塞进 `/console/` 之后要加
//     `<base href="/">`、要改十几处 URL、还要多挂一个 `/data`。
//     ⇒ 托管反而让改动更大。整栋三维（原 8123）是唯一例外，理由在 `building.js` 里。
//
// ★ 这一屏**不改任何数据模型**：取数、判过期、构造命令行全在 `services/console.py`
//   做完了，本文件一个字都不重算（memory: one-judgement-many-implementations）。
//
// ★★ 四条从原控制台**刻意保留**的规矩，都是本仓用血写下来的：
//
//   1. **轮询失败必须有个说法。** 原 `control.js:359` 是 `if (!j.success) return;`
//      —— 一次 `GET /api/jobs/<id>` 失败就让"运行中"永远为真、所有按钮永久禁用、
//      状态冻在「运行中…」，而且**再也不会排下一次轮询**。它当时被"手动重启的
//      stdlib 服务"掩盖着（作业表是内存字典，一重启就丢）。这里改成：
//      先退避重试（有次数上限），到顶就**把状态清干净并明说**「不知道那个作业
//      现在怎么样」。「不知道」「失败」「还在跑」是三种结局、三句不同的话。
//
//   2. **`glb_windows` 这个口径要跟着档案走**（原 `control.js:436-450`）：
//      `run_step` 的 `INCLUDE_SYNTHETIC_WINDOWS` 默认 False —— 也就是说
//      「生成 GLB」**不勾选就把窗户全剥掉，且没有任何报错**。
//      所以它记在档案里（而不是每次点按钮时重新猜），参数页那个复选框与流程页那个
//      开关是**同一个值**，两处联动。
//
//   3. **`_source` 要显示**（`live` / `frozen`）：`meta_source` 在实时求值失败时会
//      **静默回退**到冻结产物，而两份的 `pipeline` 形状一样、`runnable` 都可能为空。
//      「实时求值、但这台机器一条都不可跑」与「实时求值**失败**、回退到冻结产物」
//      在屏幕上同形 —— 前者是事实，后者是故障（铁律 18：自洽的数不是证据）。
//
//   4. **分母要点名**：楼列表的 `counts` / `registry.note` / `skipped_no_dxf` /
//      `shadowed_by_batch` / `broken_profiles` 五个一起读。本机 96 栋，
//      缺 recognizer 依赖或 `compute=0` 的机器上是 95 栋 ——
//      「少的那一栋是**拿不到**」与「它**不存在**」在屏幕上必须是两行不同的字。
//
// ★ 预览复用 `frontend/site/js/viewer.js` 的 `createViewer(canvas)` —— 这是**有意**
//   的跨目录复用：两边都零构建，而「GLB 该怎么摆、光怎么打」只该有一份实现。
//   代价是这一页需要一张 importmap（`/site/vendor/three/`，**仓内自带、不走公网**）。
//   ★ 三维是**懒加载**的：three 那 751 KB 只在第一次打开「预览」时才进解析路径，
//     其余十屏一点都不受影响。
//   ★ `dispose()` 里必须调 `viewer.dispose()`：每新建一个 WebGL 上下文占一份显存，
//     浏览器上限约 16 个，超了会**静默丢掉最老的** —— 症状是「点来点去三维就白了」，
//     不报错、不警告。不能指望 `dom.js` 的 `mount()` 顺手收走（那是"反正节点都没了"的赌）。
import { el, mount, rich, plain } from '../dom.js';
import { API } from '../api.js';

export const label = '建模控制台';

/** 首屏默认选它，与原控制台一致（它是注册表楼，只有本域这条列表里有）。 */
const PREFER_FIRST = 'lihua';
const POLL_MS = 700;
const POLL_BACKOFF_MS = 1600;
/** 连续失败到这个次数就停手并明说。见文件头第 1 条。 */
const POLL_MAX_FAILS = 5;

const TABS = [
  { id: 'params', text: '参数' },
  { id: 'flow', text: '流程' },
  { id: 'preview', text: '预览' },
];
// ★ 规格的两种看法（表单 / 原文）是**同一份数据**，原控制台就是这么摆的。
//   两页都留着不是冗余：表单管改，原文管粘贴与对拍。
const PARAM_SUBS = [
  { id: 'profile', text: '识别参数（档案 profile）' },
  { id: 'spec', text: '构件参数（规格 spec）' },
  { id: 'json', text: '规格 JSON（与左页同一份）' },
];
const PREVIEW_SUBS = [
  { id: 'model', text: '三维 GLB' },
  { id: 'plan', text: '识别平面图' },
];

const state = {
  caps: null, capsErr: null,
  meta: null, metaErr: null,
  rows: [], counts: null, registry: null, broken: [],
  name: null, title: '',
  profile: null, spec: null, status: null,
  // 「这一行改了生不生效」的徽章，按表单分两份（由后端 selfCheck 下发，见 paintSelfCheck）。
  selfFlags: { profile: new Map(), spec: new Map() },
  tab: 'params', psub: 'profile', pvsub: 'model',
  floor: 0,
  running: false, jobId: null, jobStage: null,
  pollFails: 0, timer: null,
  viewer: null, viewerMod: null, viewerUrl: null,
  planObjUrl: null,
  dxfBusy: false,
};
/** 常驻 DOM（面板不重建，只切 display —— 重建会把没保存的改动和画布一起丢掉）。 */
const ui = {};
let disposed = false;
let cleanups = [];

// ── 小工具 ───────────────────────────────────────────────────────

/** 一个量该怎么说：**量不到 ≠ 0**，两者的字面量必须不同。 */
function fmt(v, dash = '—') {
  return v === null || v === undefined ? dash : String(v);
}
function fmtSize(n) {
  if (n === null || n === undefined || !n) return '';
  if (n > 1048576) return (n / 1048576).toFixed(1) + 'MB';
  if (n > 1024) return (n / 1024).toFixed(0) + 'KB';
  return n + 'B';
}
/** 错误说人话：后端那句话就是最准的那句，别自己另编一句。 */
function msgOf(e) {
  if (!e) return '未知错误';
  const code = e.code ? `${e.code}：` : '';
  return code + (e.message || String(e));
}
function clearTimer() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
}
function revoke(key) {
  if (state[key]) { try { URL.revokeObjectURL(state[key]); } catch { /* 已失效 */ } }
  state[key] = null;
}

function chip(text, cls, title) {
  return el('span', { class: `csl-chip ${cls || ''}`.trim(), text, title: title || null });
}
function hint(node, text, kind) {
  node.className = `csl-hint ${kind || ''}`.trim();
  node.textContent = text || '';
}

// ── 表单引擎（照搬原 `control.js:39-174` 的语义，只把 innerHTML 换成 dom.el）──
//
// ★ 字段表**不在本文件里**：它由 `GET /api/console/meta` 下发（单一真源在
//   `backend/web/console_meta.py`）。加一个字段只改后端一处。

/** 逗号分隔的数字列表。空串 = null；有一个不是数字 ⇒ NaN（调用处据此标红并拦保存）。 */
function parseList(v, itype) {
  const s = String(v).trim();
  if (!s) return null;
  const nums = s.split(',').map((x) => x.trim()).filter((x) => x !== '')
    .map((x) => (itype === 'int' ? parseInt(x, 10) : parseFloat(x)));
  return nums.some((n) => Number.isNaN(n)) ? NaN : nums;
}

function applyField(obj, f, input) {
  const v = input.value;
  if (f.type === 'int') obj[f.k] = v === '' ? null : parseInt(v, 10);
  else if (f.type === 'num') obj[f.k] = v === '' ? null : parseFloat(v);
  else if (f.type === 'list') obj[f.k] = parseList(v, f.itype);
  else obj[f.k] = v;
}

/**
 * 一个字段。`obj` 被**就地改**（原控制台就是这么干的：表单直接写进待提交的对象）。
 *
 * ★ `json` 那支的"清空 = 显式传 null"是**有意的**，不是没写全：后端是**合并写**，
 *   删掉键会被旧值搬回来，所以要表达"我不要这个键"只能明着发 null。
 */
function fieldRow(obj, f, flags) {
  const lbl = el('span', { class: 'csl-flabel', text: f.label });
  const wrap = el('label', { class: 'csl-field' }, lbl);
  // 这一行改了到底生不生效 —— 结论由后端下发（见 paintSelfCheck），这里只贴徽章。
  // ★ 没有徽章**不等于**「生效」：只有后端量过的键才有一枚；哪一栏没量到，
  //   顶上那段话会明说。少了这枚徽章不许被读成「没问题」（铁律 16）。
  const flag = flags && flags.get(f.k);
  if (flag) {
    const isErr = flag.kinds.includes('err');
    wrap.classList.add('flagged');
    if (!isErr) wrap.classList.add('warn');
    const b = el('span', { class: 'kflag ' + (isErr ? 'err' : 'warn'),
      text: isErr ? '改了不生效' : '注意' });
    b.title = flag.labels.join('\n');
    lbl.appendChild(b);
  }
  let input;
  if (f.type === 'bool') {
    input = el('input', { class: 'csl-cb', type: 'checkbox' });
    input.checked = !!obj[f.k];
    input.onchange = () => { obj[f.k] = input.checked; };
  } else if (f.type === 'select') {
    input = el('select', {},
      (f.options || []).map((o) => el('option', { text: o })));
    input.value = obj[f.k] ?? '';
    input.onchange = () => { obj[f.k] = input.value; };
  } else if (f.type === 'json') {
    input = el('textarea', { class: 'csl-json', spellcheck: 'false' });
    input.value = obj[f.k] === undefined || obj[f.k] === null
      ? '' : JSON.stringify(obj[f.k], null, 1);
    input.oninput = () => {
      const t = input.value.trim();
      if (t === '') { obj[f.k] = null; input.style.borderColor = ''; return; }
      try { obj[f.k] = JSON.parse(t); input.style.borderColor = ''; }
      catch { input.style.borderColor = 'var(--red)'; }
    };
  } else {
    input = el('input', { class: 'csl-in' });
    input.type = (f.type === 'int' || f.type === 'num') ? 'number' : 'text';
    if (f.step) input.step = f.step;
    if (f.type === 'list') {
      const cur = obj[f.k];
      input.value = Array.isArray(cur) ? cur.join(', ') : (cur ?? '');
      input.placeholder = '逗号分隔，留空=不启用';
    } else {
      input.value = obj[f.k] ?? '';
    }
    input.oninput = () => {
      applyField(obj, f, input);
      input.style.borderColor = Number.isNaN(obj[f.k]) ? 'var(--red)' : '';
    };
  }
  // 供跨面板联动（`glb_windows` ↔ 流程页那个开关），id 与原控制台同形。
  input.id = 'pf-' + f.k;
  wrap.appendChild(input);
  // 帮助文字来自后台（`config/branches.json` 的 `_字段/*help`）⇒ 走 rich，
  // 用户在后台写重点就真的加粗（见 dom.js 的 rich）。
  if (f.help) wrap.appendChild(el('span', { class: 'csl-fhelp' }, rich(f.help)));
  return wrap;
}

function renderGroups(container, groups, obj, flags) {
  mount(container, (groups || []).map((g) => {
    const rows = g.fields.filter((f) => f.type !== 'json');
    const jsons = g.fields.filter((f) => f.type === 'json');
    return el('section', { class: 'csl-fgroup' },
      el('h3', { class: 'csl-fgh' }, rich(g.group)),
      rows.length ? el('div', { class: 'csl-fgrid' }, rows.map((f) => fieldRow(obj, f, flags))) : null,
      // json 字段（结构化数组）单独占整行 —— 塞进两列网格里会窄到没法编辑。
      jsons.length ? el('div', { class: 'csl-fgrid csl-fgrid-1' },
        jsons.map((f) => fieldRow(obj, f, flags))) : null);
  }));
}

function colorRow(obj, key, text) {
  const wrap = el('label', { class: 'csl-field' },
    el('span', { class: 'csl-flabel', text }));
  const c = el('input', { class: 'csl-cpick', type: 'color' });
  const t = el('input', { class: 'csl-in csl-hex', type: 'text', spellcheck: 'false' });
  obj[key] = obj[key] || '#888888';
  c.value = obj[key]; t.value = obj[key];
  c.oninput = () => { t.value = c.value; obj[key] = c.value; };
  t.oninput = () => { if (/^#[0-9a-fA-F]{6}$/.test(t.value)) { c.value = t.value; obj[key] = t.value; } };
  wrap.appendChild(el('div', { class: 'csl-colorrow' }, c, t));
  return wrap;
}

/**
 * 哪些数字字段此刻是非法值（NaN）。
 *
 * ★ 这条判据原控制台**只有一半**：`btnSaveSpecForm` 验了，`saveProfile` 没验。
 *   后果不是报错 —— `JSON.stringify` 把 `NaN` 写成 `null`，而后端是**合并写**，
 *   `null` 的意思是**删掉这个键**。于是「框里有个红字」会变成「档案里少了一项」，
 *   而屏幕上一切正常（铁律 30：以为写进去的与被删掉的在屏幕上同形）。
 *   ⇒ 这里两处保存**共用**这一个判据。
 */
function badNumberKeys(obj, groups) {
  const bad = [];
  for (const g of groups || []) {
    for (const f of g.fields) {
      if (!['num', 'int', 'list'].includes(f.type)) continue;
      if (Number.isNaN(obj[f.k])) bad.push(f.k);
    }
  }
  return bad;
}

// ── 外壳 ─────────────────────────────────────────────────────────

function buildShell(root) {
  const search = el('input', { class: 'csl-search', type: 'search', placeholder: '搜楼名 / 中文名' });
  const list = el('div', { class: 'csl-list' });
  const tally = el('div', { class: 'csl-tally' });
  const regNote = el('div', { class: 'csl-regnote' });
  ui.search = search; ui.list = list; ui.tally = tally; ui.regNote = regNote;

  const head = el('div', { class: 'csl-head' });
  const metaLine = el('div', { class: 'csl-metainfo' });
  const badges = el('div', { class: 'csl-badges' });
  // 启动自检：哪些键改了不生效。内容由后端 `/api/console/meta` 的 `selfCheck` 下发，
  // 本页只负责显示（在这里再判一遍 = 第二份实现，同一屏会说两句不同的话）。
  const selfBox = el('div', { class: 'csl-selfcheck' });
  ui.head = head; ui.metaLine = metaLine; ui.badges = badges; ui.selfBox = selfBox;

  const tabbar = el('div', { class: 'csl-tabs', role: 'tablist' });
  const panels = {};
  for (const t of TABS) panels[t.id] = el('section', { class: 'csl-panel', 'data-tab': t.id });
  ui.tabbar = tabbar; ui.panels = panels;

  // 参数页：三个子页常驻（切子页只切 display —— 重建会丢掉没保存的改动）。
  const params = panels.params;
  const subbar = el('div', { class: 'csl-subtabs' });
  ui.psubbar = subbar;
  ui.panes = {};
  for (const s of PARAM_SUBS) ui.panes[s.id] = el('div', { class: 'csl-subpane', 'data-sub': s.id });
  ui.profilePane = ui.panes.profile;
  ui.specPane = ui.panes.spec;
  ui.jsonPane = ui.panes.json;
  ui.profileHint = el('div', { class: 'csl-hint' });
  ui.specHint = el('div', { class: 'csl-hint' });
  ui.jsonHint = el('div', { class: 'csl-hint' });
  ui.specJson = el('textarea', { class: 'csl-json csl-json-big', spellcheck: 'false' });
  ui.profileForm = el('div', { class: 'csl-form' });
  ui.specForm = el('div', { class: 'csl-form' });

  const btnSaveProfile = el('button', {
    class: 'csl-btn', type: 'button', text: '保存档案',
    onclick: () => saveProfile(),
  });
  const btnSaveSpec = el('button', {
    class: 'csl-btn', type: 'button', text: '保存构件参数（表单）',
    onclick: () => saveSpecForm(),
  });
  const btnFillDefault = el('button', {
    class: 'csl-btn csl-ghost', type: 'button', text: '按默认值补齐缺失项',
    onclick: () => fillSpecDefault(),
  });
  const btnSaveJson = el('button', {
    class: 'csl-btn', type: 'button', text: '保存这份 JSON',
    onclick: () => saveSpecJson(),
  });
  const btnFmtJson = el('button', {
    class: 'csl-btn csl-ghost', type: 'button', text: '格式化',
    onclick: () => {
      try { ui.specJson.value = JSON.stringify(JSON.parse(ui.specJson.value), null, 2); hint(ui.jsonHint, '', ''); }
      catch (e) { hint(ui.jsonHint, 'JSON 解析失败：' + e.message, 'err'); }
    },
  });
  ui.btnSaveProfile = btnSaveProfile;
  ui.btnSaveSpec = btnSaveSpec;
  ui.btnSaveJson = btnSaveJson;

  mount(ui.panes.profile);
  ui.panes.profile.appendChild(ui.profileForm);
  ui.panes.profile.appendChild(el('div', { class: 'csl-saverow' }, btnSaveProfile, ui.profileHint));

  ui.panes.spec.appendChild(ui.specForm);
  ui.panes.spec.appendChild(el('div', { class: 'csl-saverow' },
    btnSaveSpec, btnFillDefault, ui.specHint));

  ui.panes.json.appendChild(ui.specJson);
  ui.panes.json.appendChild(el('div', { class: 'csl-saverow' },
    btnSaveJson, btnFmtJson, ui.jsonHint));

  mount(params, subbar, ...PARAM_SUBS.map((s) => ui.panes[s.id]));

  // 流程页
  const flowTop = el('div', { class: 'csl-flowtop' });
  ui.flowTop = flowTop;
  ui.flow = el('div', { class: 'csl-flow' });
  ui.winToggle = el('input', { class: 'csl-cb', type: 'checkbox' });
  ui.winHint = el('span', { class: 'csl-hint' });
  ui.jobNote = el('div', { class: 'csl-hint' });
  ui.jobLog = el('pre', { class: 'csl-log' });
  ui.btnRefreshStatus = el('button', {
    class: 'csl-btn csl-ghost', type: 'button', text: '刷新现状',
    onclick: () => refreshStatus(),
  });
  ui.winToggle.onchange = () => onWinToggleChange();
  mount(panels.flow, flowTop, ui.flow, ui.jobNote, ui.jobLog);

  // 预览页
  const pvbar = el('div', { class: 'csl-subtabs' });
  ui.pvbar = pvbar;
  ui.viewbox = el('div', { class: 'csl-viewbox' });
  ui.planbox = el('div', { class: 'csl-planbox' });
  ui.pvStatus = el('div', { class: 'csl-hint' });
  ui.pvBox = el('div', { class: 'csl-pvbox' }, ui.viewbox, ui.planbox);

  const floorSel = el('select', { class: 'csl-floorsel' });
  const btnPlan = el('button', {
    class: 'csl-btn csl-ghost', type: 'button', text: '取这一层',
    onclick: () => loadPlan(),
  });
  const btnDxf = el('button', {
    class: 'csl-btn csl-ghost', type: 'button', text: '下载本层 DXF',
    onclick: () => downloadDxf(),
  });
  ui.floorSel = floorSel; ui.btnPlan = btnPlan; ui.btnDxf = btnDxf;
  floorSel.onchange = () => { state.floor = parseInt(floorSel.value, 10) || 0; loadPlan(); };

  const pvmodel = el('div', { class: 'csl-subpane', 'data-pv': 'model' },
    ui.pvBox,
    el('p', { class: 'csl-note' },
      '这一屏看的是交付件本身（`links.glb`，服务端按真实挂载算出来的地址）。',
      el('br'),
      '右上角那个三角面数不是「它回了 200」—— ',
      '「进程起来了」与「它在干活」不是一回事。'));
  const pvplan = el('div', { class: 'csl-subpane', 'data-pv': 'plan' },
    el('div', { class: 'csl-planbar' },
      el('span', { class: 'csl-flabel', text: '层号' }), floorSel, btnPlan, btnDxf),
    ui.planbox,
    el('p', { class: 'csl-note' },
      '识别平面图（墙黑 / 门红 / 柱蓝 / 梯绿）由服务端现算，所以比别的接口慢。',
      el('br'),
      '取不到时这里显示的是服务端自己那句话 —— 它分得清「这栋没有这一层」',
      '（404）与「这台机器没装 ezdxf」（503），两者补救办法相反。'));
  ui.panes.pvmodel = pvmodel; ui.panes.pvplan = pvplan;
  // ★ 状态行挂在**两个子页之外**（preview 这一层），不挂在三维那一半里。
  //   实测（2026-09-25）：它原来挂在 pvmodel 里面，于是切到「识别平面图」之后，
  //   取图的进度与失败原因全写进了一个**被 display:none 盖住**的节点
  //   —— 屏幕上只剩"这一层没有图可看"，而 404（换一层）与 503（装 ezdxf）
  //   本来就靠那句区分。状态是这一屏的**共用出口**，不该属于其中一半。
  mount(panels.preview, pvbar, ui.pvStatus, pvmodel, pvplan);

  const wrap = el('div', { class: 'csl-wrap' },
    el('aside', { class: 'csl-left' },
      el('h2', { class: 'csl-title', text: '建模控制台' }),
      search, tally, regNote, list),
    el('div', { class: 'csl-right' }, head, metaLine, selfBox, badges, tabbar, ...TABS.map((t) => panels[t.id])));
  mount(root, wrap);
}

/** 画两个 tab 条（两个方向的切换都要重画高亮）。 */
function paintTabs() {
  const mk = (items, active, key, onPick) => el('div', { class: 'csl-tabrow' },
    items.map((t) => el('button', {
      class: `csl-tab${t.id === active ? ' active' : ''}`,
      type: 'button', role: 'tab', text: t.text,
      'aria-selected': t.id === active ? 'true' : 'false',
      onclick: () => onPick(t.id),
    })));
  const tb = mk(TABS, state.tab, 'tab', (id) => { state.tab = id; paintLayout(); if (id === 'preview') onPreviewShown(); });
  const sb = mk(PARAM_SUBS, state.psub, 'sub', (id) => { state.psub = id; paintLayout(); });
  const pv = mk(PREVIEW_SUBS, state.pvsub, 'sub', (id) => { state.pvsub = id; paintLayout(); if (id === 'model') onPreviewShown(); });
  mount(ui.tabbar, tb);
  mount(ui.psubbar, sb);
  mount(ui.pvbar, pv);
}

function paintLayout() {
  paintTabs();
  for (const t of TABS) {
    ui.panels[t.id].style.display = state.tab === t.id ? '' : 'none';
  }
  for (const s of PARAM_SUBS) ui.panes[s.id].style.display = state.psub === s.id ? '' : 'none';
  for (const s of PREVIEW_SUBS) ui.panes['pv' + s.id].style.display = state.pvsub === s.id ? '' : 'none';
  // 切走预览就把渲染循环停下（rAF 还在跑的话，那一屏在后台一直占着 GPU）。
  if (state.viewer) {
    if (state.tab === 'preview' && state.pvsub === 'model') state.viewer.start();
    else state.viewer.stop();
  }
}

// ── 载入 ─────────────────────────────────────────────────────────

async function loadAll(sub) {
  // 三件事互不依赖 ⇒ 并发发出去（控制台首屏最怕串行等三趟）。
  const [capsR, metaR, rowsR] = await Promise.allSettled([
    API.capabilities(), API.consoleMeta(), API.consoleBuildings(),
  ]);
  if (disposed) return;

  if (capsR.status === 'fulfilled') { state.caps = capsR.value; state.capsErr = null; }
  else { state.caps = null; state.capsErr = capsR.reason; }

  if (metaR.status === 'fulfilled') { state.meta = metaR.value.data; state.metaErr = null; }
  else { state.meta = null; state.metaErr = metaR.reason; }

  if (rowsR.status === 'fulfilled') {
    const env = rowsR.value;
    state.rows = env.data.rows || [];
    state.counts = env.meta?.counts || null;
    state.registry = env.meta?.registry || null;
    state.broken = env.meta?.broken_profiles || [];
  } else {
    state.rows = []; state.counts = null; state.registry = null; state.broken = [];
    state.rowsErr = rowsR.reason;
  }

  paintMetaLine();
  // 自检要在表单之前画：`fieldRow` 的徽章读的是它填好的 `state.selfFlags`。
  paintSelfCheck();
  paintList();
  paintParams();
  paintCapabilities();

  const want = (sub || '').trim();
  const pick = state.rows.find((r) => r.name === want)
    || state.rows.find((r) => r.name === PREFER_FIRST)
    || state.rows[0];
  if (pick) await selectBuilding(pick.name);
  else if (state.rowsErr) hint(ui.regNote, `楼列表取不到：${msgOf(state.rowsErr)}`, 'err');
}

/**
 * 顶部那行「这批参数表是哪来的」。
 *
 * ★ `_source` 两态必须分开显示：`frozen` 是**回退**，不是常态。
 *   只写「参数表已载入」会把一次静默回退藏起来。
 */
function paintMetaLine() {
  const m = state.meta;
  if (!m) {
    hint(ui.metaLine, `参数表取不到：${msgOf(state.metaErr)}`
      + '（这一段不在本页重算 —— 它是 `meta_source` 从 `console_meta` 求值或读冻结产物）', 'err');
    return;
  }
  const live = m._source === 'live';
  const n = (m.pipeline || []).length;
  const runnable = (m.runnable || []).length;
  ui.metaLine.className = `csl-metainfo ${live ? '' : 'warn'}`.trim();
  ui.metaLine.textContent = '';
  ui.metaLine.appendChild(el('span', { class: 'csl-source ' + (live ? 'ok' : 'warn'),
    text: live ? '参数表：本机实时求值' : '参数表：冻结产物（实时求值失败的回退）' }));
  ui.metaLine.appendChild(document.createTextNode(
    `　${n} 个阶段，本机可跑 ${runnable} 个`));
  if (!live) {
    const fz = m._source === 'frozen';
    ui.metaLine.appendChild(el('span', { class: 'csl-warnnote',
      text: fz ? '　★ 回退不是常态：请查本机 `console_meta` / 建模层是否报错' : '' }));
  }
}

// ── 启动自检：哪些键改了不生效 ─────────────────────────────────────
//
// ★ 这一段**不在本页重算**。「哪些键改了不生效」由后端
//   `console_meta.self_check_report()` 求出来，随 `GET /api/console/meta`
//   的 `selfCheck` 一栏下发（单一真源在 `backend/web/console_meta.py`）。
//   在前端照抄一遍判据就是第二份实现 ⇒ 同一屏会说两句不同的话
//   （memory: one-judgement-many-implementations）。
// ★ 但它必须**显示**出来，不能只印在服务器 stderr 里：用户改一个死键、保存、
//   刷新，屏幕上毫无变化 —— 那与「改对了」同形（铁律 16）。
//
// 三种结局三句不同的话，不许共用一行字：
//   · 干净        → 「0 条告警」
//   · 这一份没带   → 「这份载荷没带 selfCheck」（compute=0 读老冻结产物就是这样）
//   · 自检没跑起来 → 后端那句原文 + 明说「不是「干净」」
// 同理每一栏都带「状态」：`读失败` / `未量` 与 `已读` 必须能分开。

/** 一栏的「状态」怎么说：**量不到 ≠ 合规**，两者的字面量必须不同。 */
function scState(sec) {
  const st = (sec || {})['状态'];
  if (st === '已读') return { ok: true, text: '已读' };
  if (st === '读失败') return { ok: false, text: '读失败 —— 这一栏没量到，不是「干净」' };
  if (st === '未量') return { ok: false, text: '未量 —— 这一栏没量到，不是「干净」' };
  return { ok: false,
    text: `没有可取的状态（${st === undefined ? '这一栏缺 状态' : JSON.stringify(st)}）` };
}

/** 一页上都有哪些键 —— 用来把「投递通道」那几条**按数据**落回具体表单，
 *  而不是在本文件里重抄一遍「谁是档案键、谁是规格键」（那又是第二份实现）。 */
function fieldKeysOf(groups) {
  const s = new Set();
  for (const g of groups || []) for (const f of g.fields || []) s.add(f.k);
  return s;
}

function paintSelfCheck() {
  const m = state.meta;
  const sc = m && m.selfCheck;
  state.selfFlags = { profile: new Map(), spec: new Map() };
  mount(ui.selfBox);
  ui.selfBox.className = 'csl-selfcheck';

  const head = (stamp) => el('div', { class: 'sc-head' },
    el('span', { class: 'sc-title', text: '启动自检：哪些键改了不生效' }),
    stamp ? el('span', { class: 'sc-stamp', text: stamp }) : null);

  // ① 这一份没带 —— 与「量到且干净」必须是两行不同的字
  if (!sc || typeof sc !== 'object') {
    ui.selfBox.className = 'csl-selfcheck err';
    mount(ui.selfBox, head(''),
      el('p', { class: 'sc-row err' }, rich(m
        ? '★ 这一份载荷没带 selfCheck。最可能是 compute=0 读了一份早于本栏上线的'
          + '冻结产物（`data/_meta/console_meta.json`）—— 「没带」与「没有告警」在屏幕上'
          + '必须是两行不同的字，所以这里明写。本机 compute=1 时这一栏应当由后端实时求出来。'
        : '参数表还没取到，自检这一栏无从显示。')));
    return;
  }

  // ② 后端自检自己没跑起来（`meta_source._self_check` 捕获后留下的痕）
  if (sc['错误'] || sc['状态'] === '读失败') {
    ui.selfBox.className = 'csl-selfcheck err';
    mount(ui.selfBox, head(''),
      el('p', { class: 'sc-row err' },
        rich(`★ 启动自检没跑起来：${fmt(sc['错误'])}　${fmt(sc['含义'])}`)));
    return;
  }

  const warns = Array.isArray(sc['告警']) ? sc['告警'] : null;
  const nHat = sc['告警条数'];
  const sSpec = scState(sc['规格键']);
  const sProf = scState(sc['档案键']);
  const sChan = scState(sc['投递通道']);
  const secSpec = sc['规格键'] || {};
  const secProf = sc['档案键'] || {};
  const secChan = sc['投递通道'] || {};
  const arr = (v) => (Array.isArray(v) ? v : []);

  // ── 徽章：把每个键落到它所在的那张表单上（哪张表里有这个键，由字段表说了算）
  const pk = fieldKeysOf(m.profile);
  const sk = fieldKeysOf(m.spec);
  const notOnAnyPage = new Set();
  const put = (key, kind, label) => {
    if (typeof key !== 'string' || !key) return;
    const where = pk.has(key) ? 'profile' : (sk.has(key) ? 'spec' : null);
    // 既不在档案页也不在规格页 ⇒ 记下来，别静默丢掉（改它得走 JSON 原文或直接改登记表）
    if (!where) { notOnAnyPage.add(key); return; }
    const map = state.selfFlags[where];
    const cur = map.get(key) || { kinds: [], labels: [] };
    if (!cur.kinds.includes(kind)) cur.kinds.push(kind);
    cur.labels.push(label);
    map.set(key, cur);
  };

  // 档案键（参数页「识别参数」那一页）
  for (const k of arr(secProf['死旋钮'])) put(k, 'err',
    '档案键：在参数页上可改，但载入后没有消费者（kind=死键）⇒ 改了不生效、且不报错');
  for (const k of arr(secProf['不在登记表里'])) put(k, 'warn',
    '档案键：不在 config/branches.json 的登记表里（这一路读不到它是不是真的被消费）');
  // 规格键（参数页「构件参数」那一页）
  for (const k of arr(secSpec['不在消费列表'])) put(k, 'err',
    '规格键：不在 build_standard_glb 的消费列表里 ⇒ 改了不生效');
  for (const k of arr(secSpec['批量识别不读'])) put(k, 'warn',
    '规格键：批量识别这条路不读它');
  // 投递通道（同一个档案键，每条通道读了哪几条）
  // ★ 通道名**从 payload 推出来**，不写死「三条通道 / GLB / 批量识别 / 控制台」：
  //   后端 2026-09-26 把通道表从 3 条补到 5 条（多了 SU 分层建模、楼层清单），
  //   而这里原样写着「三条通道一条都不读」—— 一个判断两份实现，模板串那一份不跟着规则走。
  //   现在名字与条数都由后端给，页面只负责显示。
  const chanNames = arr(secChan['通道']);
  const chanList = chanNames.length ? chanNames.join(' / ') : '（通道表读不到）';
  // 每个键**真正**由哪几条通道读（后端 `认它的通道`）。点名用这个，别让前端复述结论 ——
  // 前端复述过一次，那次它写的是「只有「生成 GLB」这条路读它」，而实测 SU 分层建模也读。
  const chansOfMap = secChan['认它的通道'] || {};
  const chansOf = (k) => {
    const v = chansOfMap[k];
    return Array.isArray(v) && v.length ? v.join(' / ') : '（读它的通道没量到）';
  };
  for (const k of arr(secChan['一条都不读'])) put(k, 'err',
    `投递通道：${chanList} —— 每条通道都不读（改了彻底不生效）`);
  // ★ 这里原来写的是「识别那**两条**路都不读」—— **条数是写死的**（识别通道现有 2 条）。
  //   通道表再补一条识别通道时，这句会静默说错，而屏幕上完全看不出来（条数是一次带时刻的
  //   测量，见后端那三条通道 → 五条的改动）。改成不提条数、也不列举通道名：
  //   「不是识别通道」这件事实由**桶名本身**承担，具体读它的名字由后端 `认它的通道` 给。
  for (const k of arr(secChan['识别通道不读'])) put(k, 'warn',
    `投递通道：读它的是「${chansOf(k)}」，都不是识别通道 ⇒ 改了不影响识别`);
  for (const k of arr(secChan['批量识别不读'])) put(k, 'warn',
    '投递通道：批量识别这条路不读它');
  for (const k of arr(secChan['控制台通道会丢'])) put(k, 'warn',
    '投递通道：控制台保存时会丢（只认批量识别那条路写进去的值）');

  // ── 每个键的名字列表（点名，不打数量就完）
  const names = (v, max = 12) => {
    const a = arr(v);
    if (!a.length) return '无';
    const s = a.slice(0, max).join('、');
    return a.length > max ? `${s} …（共 ${a.length} 个）` : s;
  };
  const rowOf = (title, st, parts) => el('p', { class: `sc-row${st.ok ? '' : ' err'}` },
    el('b', { text: title }), `　${st.text}`,
    ...parts.map((x) => el('span', { class: 'sc-names', text: `　${x}` })));

  const 分母 = secChan['分母'] || {};
  const 逐键 = 分母['逐键'] || {};
  const rows = [
    rowOf('规格键', sSpec, [
      `消费列表 ${fmt(secSpec['消费列表键数'])} 个键；不在消费列表 ${arr(secSpec['不在消费列表']).length} 个：` +
      names(secSpec['不在消费列表']),
    ]),
    rowOf('档案键', sProf, [
      `参数页上 ${fmt(secProf['在参数页上'])} 个 / 登记表 ${fmt(secProf['登记表条数'])} 条；` +
      `死旋钮 ${arr(secProf['死旋钮']).length} 个：${names(secProf['死旋钮'])}`,
      `不在登记表里 ${arr(secProf['不在登记表里']).length} 个：${names(secProf['不在登记表里'])}`,
    ]),
    rowOf('投递通道', sChan, [
      `${fmt(secChan['条数'])} 条通道（${chanList}）；一条都不读 ${arr(secChan['一条都不读']).length} 个：` +
      `${names(secChan['一条都不读'])}`,
      `识别通道不读 ${arr(secChan['识别通道不读']).length} 个：${names(secChan['识别通道不读'])}`,
      // ★ 光说「识别通道不读」只答了「哪条路不看」，要判「改了到底在哪生效」还得知道
      //   **读它的是哪几条**。这里逐键点名（名字从后端 `认它的通道` 来）。
      `　└ 读它的是：` +
      (arr(secChan['识别通道不读']).map((k) => `${k}←${chansOf(k)}`).join('、') || '无'),
      `批量识别不读 ${arr(secChan['批量识别不读']).length} 个：${names(secChan['批量识别不读'])}`,
      `控制台通道会丢 ${arr(secChan['控制台通道会丢']).length} 个：${names(secChan['控制台通道会丢'])}`,
      // 分母要点名：只有比例没有分母，读不出「一条都不读 0 个」是量过还是没量
      `分母：${fmt(分母['栋数'])} 栋（逐键 ` +
      `${Object.entries(逐键).map(([k, v]) => `${k} ${v}`).join('、') || '无'}）；` +
      `分母那一栏 ${scState(分母).text}`,
    ]),
    el('p', { class: 'sc-row' }, el('b', { text: '阶段' }),
      `　${fmt(sc['阶段'] && sc['阶段']['阶段数'])} 个阶段；` +
      `缺 args ${arr(sc['阶段'] && sc['阶段']['缺args']).length} 个；` +
      `upstream 未登记 ${arr(sc['阶段'] && sc['阶段']['upstream未登记']).length} 个`),
  ];
  // 两处各写一个数 ⇒ 会各自漂。对不上就明说，不许挑一个信（铁律 18/30）。
  if (warns && nHat !== warns.length) {
    rows.push(el('p', { class: 'sc-row err',
      text: `★ 告警条数 ${JSON.stringify(nHat)} 与告警列表长度 ${warns.length} 对不上 —— ` +
        '这两个数写在同一个对象里，也是各漂各的；本页两个都印出来，不挑一个信。' }));
  }
  if (notOnAnyPage.size) {
    rows.push(el('p', { class: 'sc-row warn',
      text: `另有 ${notOnAnyPage.size} 个键既不在档案页也不在规格页：` +
        `${[...notOnAnyPage].sort().join('、')}　—— 要改它们得走规格 JSON 原文或直接改 ` +
        '`config/branches.json`。' }));
  }

  // ── 判词由数推出来，不写死（铁律 44：写死的判词会替数字宣布一个它没说的结论）
  const flagged = [...state.selfFlags.profile.values(), ...state.selfFlags.spec.values()];
  const nErr = flagged.filter((f) => f.kinds.includes('err')).length;
  const nWarnFlag = flagged.length - nErr;
  const nWarn = warns ? warns.length : null;
  const badState = !(sSpec.ok && sProf.ok && sChan.ok);
  const cls = (badState || nErr) ? 'err' : ((nWarn > 0) ? 'warn' : 'ok');
  ui.selfBox.className = 'csl-selfcheck ' + cls;

  const verdict = badState
    ? '★ 有栏目没量到 —— 这几栏的空白不是「干净」，见上面那几行的状态。'
    : (nErr > 0)
      ? `★ ${nErr} 个键改了不生效（红徽章），另有 ${nWarnFlag} 个键要留意：` +
        '它们照收不误，只是不按你想的走。'
      : (nWarn > 0)
        ? `${nWarn} 条告警、${nWarnFlag} 个键要留意：没有一条是「改了完全不生效」，` +
          '都是「只在某一条通道上生效」。'
        : '0 条告警：参数页上的键都接上了消费者。';

  mount(ui.selfBox, head(
    `量于 ${fmt(sc['量于'])} · 第 ${fmt(sc['第几次算'])} 次算 · v${fmt(sc['版本'])}`),
    el('p', { class: `sc-row${cls === 'ok' ? '' : ' ' + cls}` }, rich(verdict)),
    ...rows,
    el('p', { class: 'sc-row', text: `缓存：${fmt(sc['缓存'])}` }),
    warns && warns.length
      ? el('details', {},
        el('summary', { text: `告警原文（${warns.length} 条，与上面同一份，逐条可读）` }),
        el('ul', {}, warns.map((w) => el('li', {}, rich(w)))))
      : null);
}

function paintCapabilities() {
  const caps = state.caps;
  let why;
  if (state.capsErr) why = `取不到 capabilities：${msgOf(state.capsErr)} —— 写操作先禁用（不知道就别放行）`;
  else if (!caps) why = '还没问到 capabilities —— 写操作先禁用';
  else if (!caps.write_enabled) why = `★ 后端说不能写：${caps.write_disabled_reason || caps.write_disabled_code || ''}`;
  else why = '可以写（本机回环，或后端 compute 开着且来源被允许）';

  ui.badges.textContent = '';
  const cn = state.counts;
  if (cn) {
    ui.badges.appendChild(chip(`批次 ${cn.batch} + 注册表 ${cn.registry} = ${cn.total} 栋`, ''));
  }
  if (caps) {
    ui.badges.appendChild(chip(caps.write_enabled ? '写：开' : '写：关',
      caps.write_enabled ? 'ok' : 'warn', why));
    ui.badges.appendChild(chip(`compute=${caps.compute ? 1 : 0}`,
      caps.compute ? '' : 'warn', why));
    if (caps.admin_token_configured) ui.badges.appendChild(chip('已配 admin_token', ''));
  } else {
    ui.badges.appendChild(chip('写：未知', 'warn', why));
  }
  if (caps?.write_disabled_reason) {
    ui.badges.appendChild(el('span', { class: 'csl-warnnote', text: caps.write_disabled_reason }));
  }
}

/**
 * 左栏楼列表 + **分母那一块**。
 *
 * ★ 五个数一起读，缺一个就会把「拿不到」读成「不存在」：
 *   `counts`（分母）、`registry.note`（注册表这一路通不通）、
 *   `skipped_no_dxf`（剔掉的：源图不在本机）、`shadowed_by_batch`（被同名批次盖住的）、
 *   `broken_profiles`（档案坏了的，逐栋）。
 */
function paintList() {
  const reg = state.registry;
  ui.regNote.textContent = '';
  ui.regNote.className = 'csl-regnote';
  if (reg) {
    const parts = [];
    parts.push(reg.available ? '注册表可用' : `注册表拿不到：${reg.note || '本机缺 recognizer 依赖'}`);
    if (reg.error) parts.push(`错误 ${reg.error}`);
    if ((reg.skipped_no_dxf || []).length) {
      parts.push(`剔掉（源图不在本机）${reg.skipped_no_dxf.length} 栋：${reg.skipped_no_dxf.join('、')}`);
    }
    if ((reg.shadowed_by_batch || []).length) {
      parts.push(`被同名批次目录盖住 ${reg.shadowed_by_batch.length} 栋：${reg.shadowed_by_batch.join('、')}`);
    }
    if (!reg.available) ui.regNote.classList.add('warn');
    ui.regNote.textContent = parts.join('　');
  } else if (state.rowsErr) {
    ui.regNote.classList.add('err');
    ui.regNote.textContent = `楼列表取不到：${msgOf(state.rowsErr)}`;
  }
  if (state.broken.length) {
    ui.regNote.appendChild(el('div', { class: 'csl-warnnote',
      text: `档案坏了的 ${state.broken.length} 栋（不影响别的楼）：`
        + state.broken.map((b) => `${b.name}(${b.error})`).join('、') }));
  }

  const q = (ui.search.value || '').trim().toLowerCase();
  const hit = state.rows.filter((r) =>
    !q || `${r.name} ${r.title}`.toLowerCase().includes(q));
  ui.tally.textContent = q
    ? `搜「${q}」命中 ${hit.length} / 共 ${state.rows.length} 栋`
    : (state.counts
      ? `分母：${state.counts.total} 栋（批次 ${state.counts.batch} + 注册表 ${state.counts.registry}）`
      : `${state.rows.length} 栋`);

  mount(ui.list, hit.map((r) => {
    const it = el('div', {
      class: `csl-bld${state.name === r.name ? ' active' : ''}`,
      onclick: () => selectBuilding(r.name),
      role: 'button', tabindex: '0',
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectBuilding(r.name); } },
    });
    it.appendChild(el('div', { class: 'csl-bldt' },
      el('b', { text: r.title || r.name }), el('span', { class: 'csl-bldn', text: r.name })));
    const meta = el('div', { class: 'csl-bldmeta' });
    meta.appendChild(chip(r.roofType === 'flat' ? '平顶' : '坡顶', ''));
    meta.appendChild(chip(r.classifier || '—', ''));
    // ★ 字段名是 floor_count —— 8140 的 `/api/buildings` 用 `floors` 装**数组**，
    //   原 `control.js:193` 把同一个词当数字拼「N 层」。一个词两个意思正是本轮要收的账。
    meta.appendChild(chip(`${fmt(r.floor_count)} 层`, ''));
    meta.appendChild(chip(r.source === 'registry' ? '注册表' : '批次', ''));
    if (r.glbStale) {
      meta.appendChild(chip('模型过期', 'warn',
        'GLB 早于最新楼层数据 —— 改过楼层但没重出模型（去「流程 → 生成 GLB」）。'
        + '注意：这条判据按文件时间比，拷贝/还原过的旧 GLB 会看起来是新鲜的'));
    }
    meta.appendChild(chip(r.glb ? 'GLB ✓' : 'GLB ✗', r.glb ? 'ok' : ''));
    it.appendChild(meta);
    return it;
  }));
}

async function selectBuilding(name) {
  if (!name) return;
  state.name = name;
  const r = state.rows.find((x) => x.name === name);
  state.title = r?.title || name;
  state.floor = 0;
  clearTimer();
  state.running = false;
  state.jobId = null;
  state.pollFails = 0;
  hint(ui.jobNote, '', '');
  ui.jobLog.textContent = '';

  orderApply();
  paintList();
  paintHead();

  // 档案 / 规格 / 现状：三趟并发，互不依赖。
  await Promise.allSettled([
    loadProfile(name), loadSpec(name), refreshStatus(),
  ]);
  if (disposed || state.name !== name) return;
  paintParams();
  paintFlow();
  paintPreviewInfo();
  // 换了楼就把旧图作废（否则屏幕上留着上一栋的图，而它看起来完全正常）。
  revoke('planObjUrl');
  mount(ui.planbox);
  hint(ui.pvStatus, '', '');
  if (state.viewer && state.viewerUrl) state.viewerUrl = null;
}

function paintHead() {
  const r = state.rows.find((x) => x.name === state.name);
  mount(ui.head,
    el('h2', { class: 'csl-h2', text: state.title || state.name || '（没选楼）' }),
    r ? chip(r.name, '') : null,
    r?.links?.dxfPlan ? el('a', {
      class: 'csl-linkchip', href: r.links.dxfPlan, target: '_blank', rel: 'noopener',
      text: '每层源图纸 ↗',
    }) : null,
    r?.links?.compare ? el('a', {
      class: 'csl-linkchip', href: r.links.compare, target: '_blank', rel: 'noopener',
      text: '对比页 ↗',
    }) : null,
    r?.links?.note ? chip('产物在、这里没通路', 'warn', r.links.note) : null);
  // 开关的可用性跟着能力走（后端那句话就是理由）。
  const writeOn = !!state.caps?.write_enabled;
  const whyWrite = state.caps?.write_disabled_reason
    || (state.capsErr ? msgOf(state.capsErr) : '还没问到 capabilities');
  for (const b of [ui.btnSaveProfile, ui.btnSaveSpec, ui.btnSaveJson]) {
    b.disabled = !writeOn;
    b.title = writeOn ? '' : whyWrite;
  }
  ui.winToggle.disabled = !writeOn || !state.profile;
  ui.winToggle.title = !writeOn ? whyWrite
    : (!state.profile ? '档案还没读到 —— 开关不知道该反映哪个值，先禁用' : '');
}

async function loadProfile(name) {
  try {
    state.profile = await API.consoleProfile(name);
  } catch (e) {
    state.profile = null;
    state.profileErr = e;
  }
}
async function loadSpec(name) {
  try {
    const env = await API.consoleSpec(name);
    state.spec = env.data || {};
    state.specMeta = env.meta || null;
  } catch (e) {
    state.spec = {}; state.specMeta = null; state.specErr = e;
  }
}

// ── 参数页 ───────────────────────────────────────────────────────

function paintParams() {
  const m = state.meta;
  // ① 识别参数（档案）
  if (!m) {
    mount(ui.profileForm,
      el('div', { class: 'csl-empty', text: '参数表还没取到 —— 表单是后端下发的，没有它画不出来。' }));
    hint(ui.profileHint, state.metaErr ? msgOf(state.metaErr) : '', 'err');
  } else if (!state.profile) {
    mount(ui.profileForm);
    hint(ui.profileHint, `档案取不到：${msgOf(state.profileErr)}` +
      '（可能是"这栋楼没有档案"，也可能是"读注册表时本机缺依赖" —— 这两件事补救办法相反，' +
      '看后端那句话里的 code：`not_found` vs `upstream`）', 'err');
  } else {
    state.profile.style = state.profile.style || {};
    renderGroups(ui.profileForm, m.profile, state.profile, state.selfFlags.profile);
    ui.profileForm.appendChild(styleSection(state.profile, m));
    hint(ui.profileHint, '', '');
  }

  // ② 构件参数（规格）
  if (m && state.spec) {
    renderGroups(ui.specForm, m.spec, state.spec, state.selfFlags.spec);
  } else {
    mount(ui.specForm, el('div', { class: 'csl-empty',
      text: m ? '规格还没取到。' : '参数表还没取到。' }));
  }
  // ③ 规格原文
  ui.specJson.value = JSON.stringify(state.spec || {}, null, 2);
  applyWinToggle(!!(state.profile && state.profile.glb_windows));
}

/** 外观样式那一组（在 spec 里，但识别时按档案 style 重写，所以也放参数页）。 */
function styleSection(profile, m) {
  const grid = el('div', { class: 'csl-fgrid' },
    (m.styleKeys || []).map((sk) => colorRow(profile.style, sk.k, sk.label)));
  const sel = el('select', {},
    el('option', { text: 'flat — 平顶' }), el('option', { text: 'gable — 坡顶' }));
  sel.value = profile.style.roofType || 'gable';
  sel.onchange = () => { profile.style.roofType = sel.value; };
  grid.appendChild(el('label', { class: 'csl-field' },
    el('span', { class: 'csl-flabel', text: '屋顶形式 roofType' }), sel,
    el('span', { class: 'csl-fhelp' },
      rich('坡顶 = 沿长轴设脊的双坡屋面；平顶 = 屋面板 + 一圈女儿墙'))));
  return el('section', { class: 'csl-fgroup' },
    el('h3', { class: 'csl-fgh', text: '外观样式 style（识别时写进 spec）' }), grid);
}

async function saveProfile() {
  const bad = badNumberKeys(state.profile, state.meta?.profile);
  if (bad.length) {
    hint(ui.profileHint, `有字段不是合法数字：${bad.join('、')}（红框处）。`
      + '先改对再存 —— 直接存会把它们变成 `null`，而在合并写里 null 是"删掉这个键"。', 'err');
    return;
  }
  try {
    const env = await API.consolePutProfile(state.name, state.profile);
    hint(ui.profileHint, `已保存 ✓（下次「识别」生效）　写到 ${env.data.written}`, 'ok');
    await refreshRows();
  } catch (e) {
    hint(ui.profileHint, `保存失败：${msgOf(e)}`, 'err');
  }
}

/** 按默认值补齐**缺失**的项（不覆盖已有值 —— 那是"补齐"不是"重置"）。 */
function fillSpecDefault() {
  const d = state.meta?.specDefaults || {};
  let n = 0;
  for (const k of Object.keys(d)) {
    if (state.spec[k] === undefined || state.spec[k] === null) { state.spec[k] = d[k]; n++; }
  }
  paintParams();
  hint(ui.specHint, n ? `已按默认值补齐 ${n} 项，记得保存` : '没有缺失项', n ? 'ok' : '');
}

async function saveSpecForm() {
  const bad = badNumberKeys(state.spec, state.meta?.spec);
  if (bad.length) {
    hint(ui.specHint, `有字段不是合法数字：${bad.join('、')}（红框处）`, 'err');
    return;
  }
  await saveSpecObj(state.spec, ui.specHint);
  ui.specJson.value = JSON.stringify(state.spec || {}, null, 2);
}

async function saveSpecJson() {
  let obj;
  try {
    obj = JSON.parse(ui.specJson.value);
  } catch (e) {
    hint(ui.jsonHint, 'JSON 解析失败：' + e.message, 'err');
    return;
  }
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    hint(ui.jsonHint, '规格得是一个 JSON 对象（`{...}`）—— 数组或标量会被后端挡成 422。', 'err');
    return;
  }
  state.spec = obj;
  await saveSpecObj(obj, ui.jsonHint);
  paintParams();
}

async function saveSpecObj(obj, node) {
  try {
    const env = await API.consolePutSpec(state.name, obj);
    hint(node, `已保存 ✓（下次「生成 GLB」生效）　${env.meta?.keys ?? '—'} 个键`, 'ok');
  } catch (e) {
    hint(node, `保存失败：${msgOf(e)}`, 'err');
  }
}

// ── 流程页 ───────────────────────────────────────────────────────

/** 阶段现状：**`inplace` 的 done/stale 是 `null` 而不是 `false`**，要分开说。 */
function stageState(s) {
  if (s.inplace) {
    return { text: '就地改写', cls: 'manual',
      why: '这一步就地改楼层数据，没有独立产物 —— 所以 `done`/`stale` 是 `null`（不是 false）。'
        + '报"已完成"会是假信号（`floor0.json` 在「识别出图」时就存在了）' };
  }
  if (!(s.artifacts || []).length) return { text: '无产物', cls: '', why: '这一步不产文件' };
  if (s.stale) return { text: '过期 ⚠', cls: 'warn', why: '产物比它的上游旧' };
  if (s.done) return { text: '完成 ✓', cls: 'ok', why: '' };
  return { text: '未做', cls: '', why: '' };
}

function paintFlow() {
  const st = state.status;
  const writeOn = !!state.caps?.write_enabled;
  const whyWrite = state.caps?.write_disabled_reason || (state.capsErr ? msgOf(state.capsErr) : '还没问到 capabilities');

  mount(ui.flowTop,
    el('label', { class: 'csl-winrow' },
      ui.winToggle,
      el('span', { text: '生成 GLB 时带上合成窗（`glb_windows`）' }),
      ui.winHint),
    el('span', { class: 'csl-sp' }),
    ui.btnRefreshStatus,
    st ? chip(`F 层 ${fmt(st.nFloors)}`, '') : null,
    st?.glbStale ? chip('GLB 过期', 'warn') : null);

  if (!st) {
    mount(ui.flow, el('div', { class: 'csl-empty',
      text: '还没读到这栋楼的现状（或者这栋楼没有楼层数据）。' }));
    return;
  }
  mount(ui.flow, st.stages.map((s) => {
    const ss = stageState(s);
    const row = el('div', { class: `csl-stage ${s.stale ? 'stale' : (s.done ? 'done' : '')}` });
    row.appendChild(el('div', { class: 'csl-no', text: String(s.no) }));
    const body = el('div', { class: 'csl-stagebody' });
    body.appendChild(el('div', { class: 'csl-stagetitle' },
      el('b', { text: s.label }),
      el('span', { class: `csl-status ${ss.cls}`, text: ss.text, title: ss.why || null }),
      chip(s.scope === 'single' ? '单栋' : (s.scope === 'all' ? '全仓' : '图纸源'), '',
        '作用范围：' + s.scope),
      s.writes ? chip('写盘', '', '这一步会改盘上的文件') : null,
      s.slow ? chip('慢', '') : null,
      s.danger === 'high' ? chip('⚠ 改数据', 'warn', s.whyManual || '') : null));
    if (s.desc) body.appendChild(el('div', { class: 'csl-stagedesc' }, rich(s.desc)));
    const arts = (s.artifacts || []);
    if (arts.length) {
      body.appendChild(el('div', { class: 'csl-arts', text: arts.map((a) => a.exists
        ? `${a.rel} ${fmtSize(a.size)}${a.stale ? ' ← 过期' : ''}`
        : `${a.rel} 缺`).join('　|　') }));
    }
    if (!s.runnable && s.whyManual) {
      body.appendChild(el('div', { class: 'csl-why' }, rich('需命令行：' + s.whyManual)));
    }
    row.appendChild(body);

    const acts = el('div', { class: 'csl-acts' });
    if (s.runnable) {
      const btn = el('button', {
        class: `csl-btn${s.danger === 'high' ? ' danger' : ''}`,
        type: 'button',
        text: s.scope === 'single' ? '运行' : '跑全仓',
        onclick: () => runStage(s),
      });
      btn.disabled = state.running || !writeOn;
      btn.title = !writeOn ? whyWrite : (state.running ? '有作业在跑' : '');
      acts.appendChild(btn);
    } else {
      // 不可跑**不是**"按钮没了"：要说出为什么（原控制台这里也是一句话）。
      acts.appendChild(el('span', { class: 'csl-status manual', text: '手动' }));
    }
    row.appendChild(acts);
    return row;
  }));
}

async function refreshRows() {
  try {
    const env = await API.consoleBuildings();
    state.rows = env.data.rows || [];
    state.counts = env.meta?.counts || null;
    state.registry = env.meta?.registry || null;
    state.broken = env.meta?.broken_profiles || [];
    paintList();
  } catch { /* 列表刷不动不该挡住别的（保存已经成功了） */ }
}

async function refreshStatus() {
  if (!state.name) return;
  try {
    state.status = await API.consoleStatus(state.name);
  } catch (e) {
    state.status = null;
    state.statusErr = e;
  }
  if (disposed) return;
  paintFlow();
  paintFloorSelect();
  paintHead();
}

function paintFloorSelect() {
  const n = state.status?.nFloors ?? null;
  const opts = n === null ? [] : Array.from({ length: n }, (_, i) => i);
  mount(ui.floorSel, opts.map((f) => el('option', { value: String(f), text: `F${f}` })));
  if (opts.length) {
    if (!opts.includes(state.floor)) state.floor = opts[0];
    ui.floorSel.value = String(state.floor);
  }
  const ok = opts.length > 0;
  ui.btnPlan.disabled = !ok;
  ui.btnDxf.disabled = !ok;
  ui.btnPlan.title = ok ? '' : '这栋楼没有楼层数据（`nFloors` 是 0 或没读到）';
  ui.btnDxf.title = ui.btnPlan.title;
}

// ── 跑阶段 + 轮询 ────────────────────────────────────────────────

function windowsOn() {
  return !!(ui.winToggle && ui.winToggle.checked);
}

function setRunning(on) {
  state.running = on;
  paintFlow();
  paintHead();
}

function appendLog(text) {
  ui.jobLog.textContent += text;
  ui.jobLog.scrollTop = ui.jobLog.scrollHeight;
}

async function runStage(s) {
  if (s.danger === 'high') {
    // ★ confirm 是**渲染不了加粗**的通道之一（dom.js 的 plain 那支）：只有纯文本。
    //   同一条 whyManual 走 `<div class="csl-why">` 时是 rich()（真加粗），
    //   走这里时不过 plain() 就会把 `**不在 git**` 原样念给用户。
    //   —— 也正因为它在 confirm 里、不在 DOM 里，探针**量不到**它（见下面那条注释）。
    const warn = s.whyManual ? '\n\n' + plain(s.whyManual) : '';
    if (!window.confirm(`即将运行「${s.label}」：会改写本楼楼层数据（逐层 .orig 备份 + 自动回滚）。\n`
      + `确认继续？${warn}`)) return;
  }
  if (s.scope === 'all' && !window.confirm(`「${s.label}」作用于全部楼，确认运行？`)) return;

  setRunning(true);
  state.jobStage = s.id;
  state.pollFails = 0;
  hint(ui.jobNote, '', '');
  ui.jobLog.textContent = `启动「${s.label}」（合成窗 ${windowsOn() ? '带' : '不带'}）…\n`;
  try {
    const env = await API.consoleRun(state.name, s.id, windowsOn());
    const job = env.data || {};
    state.jobId = job.id;
    appendLog(`作业 ${fmt(job.id)}　超时 ${fmt(env.meta?.timeout_s)} 秒\n`);
    // ★ `cli` 是后端给的那串复现命令。写成 `env.meta.cli.join(' ')` 的话，
    //   后端哪天改成给字符串，屏幕上就是 `a,b,c` 或者 TypeError（模板串印 undefined 那条）。
    const cli = env.meta?.cli;
    if (cli) appendLog(`argv: ${Array.isArray(cli) ? cli.join(' ') : String(cli)}\n\n`);
  } catch (e) {
    setRunning(false);
    hint(ui.jobNote, `无法启动：${msgOf(e)}`
      + (e?.code === 'local_only' || e?.code === 'compute_disabled'
        ? '　—— 这是执行面的闸门，不是这个阶段本身不能跑。' : ''), 'err');
    return;
  }
  pollJob(s);
}

/**
 * 轮询一条作业。
 *
 * ★★ 这个函数就是原 `control.js:359` 那个 bug 的修复点，两条都要：
 *   · **失败要重排**（有上限），不然一次网络抖动就再也不会问第二次；
 *   · 到上限要**把状态清干净并明说**，不然 `state.running` 永远为真、
 *     按钮永久禁用、状态冻在「运行中…」—— 而屏幕上它和"正在跑"一模一样。
 *   ⇒ 「还在跑」「跑完了」「不知道」三种结局，必须给三句不同的话。
 */
async function pollJob(s) {
  if (disposed || !state.jobId) return;
  let env;
  try {
    env = await API.consoleJobs(state.jobId);
  } catch (e) {
    state.pollFails += 1;
    if (state.pollFails < POLL_MAX_FAILS) {
      hint(ui.jobNote, `轮询失败第 ${state.pollFails} 次：${msgOf(e)}`
        + `　—— 还在重试（最多 ${POLL_MAX_FAILS} 次）`, 'warn');
      if (!disposed) state.timer = setTimeout(() => pollJob(s), POLL_BACKOFF_MS);
      return;
    }
    setRunning(false);
    hint(ui.jobNote, `轮询中断（连续 ${state.pollFails} 次失败）：${msgOf(e)}。`
      + `按钮已恢复可用，但这个作业现在怎么样我们不知道 —— `
      + `它唯一的记录是盘上 \`data/_jobs/${state.jobId}.json\` 与它的日志文件。`, 'err');
    return;
  }
  state.pollFails = 0;
  const d = env.data || {};
  renderJobLog(d, env.meta);

  if (d.state === 'running') {
    hint(ui.jobNote, `运行中…（已 ${fmt(d.elapsed_s)} 秒${d.timeout_s ? ` / 上限 ${d.timeout_s}` : ''}）`, 'run');
    if (!disposed) state.timer = setTimeout(() => pollJob(s), POLL_MS);
    return;
  }

  setRunning(false);
  // ★ 五种终态分开说：`lost` 是"记录在、读不动"，不是"失败"。
  const T = {
    ok: ['完成 ✓（进程退出码 0）', 'ok'],
    failed: [`失败 ✗（退出码 ${fmt(d.exit_code)}）`, 'err'],
    timeout: [`超时（上限 ${fmt(d.timeout_s)} 秒，进程已被终止）`, 'err'],
    lost: ['这个作业的记录读不动了（state=lost）—— 盘上那份 JSON 坏了', 'err'],
  };
  const [text, cls] = T[d.state] || [`状态是 ${fmt(d.state)}（未知的一种）`, 'err'];
  hint(ui.jobNote, `${text}${d.note ? `　${d.note}` : ''}`, cls);
  // ★ 这段是"进程怎么样"，**不是**"这一步产出了东西"。产出看下面刷新出来的 artifacts。
  if (d.state === 'ok') {
    appendLog('\n—— 作业结束。★ 退出码 0 只说明进程正常退出；'
      + '这一步到底产出了什么，看上面阶段行里那份 `artifacts`（本仓铁律 20）。\n');
  }
  await refreshStatus();
  if ((d.state === 'ok') && ['glb', 'recognize', 'full'].includes(s.id)) {
    await loadSpec(state.name);
    paintParams();
    loadModel();          // 重出过模型就顺手刷新预览
  }
}

function renderJobLog(d, meta) {
  // ★ 回的是日志**文本**，不是盘上那条路径（`routers/console.py` 那一档）。
  //   截断了要说：`log_truncated_bytes` 不是 null 就意味着开头被切掉了。
  const tail = d.log_tail;
  const shown = fmt(meta?.lines_shown, '?');
  const lines = fmt(d.log_lines, '?');
  const cut = d.log_truncated_bytes;
  ui.jobLog.textContent = (cut === null || cut === undefined)
    ? (tail || '（这个作业还没有日志）')
    : `（★ 日志开头被截掉了 ${cut} 字节；下面是最后 ${shown} 行，共 ${lines} 行）\n`
      + (tail || '');
  ui.jobLog.scrollTop = ui.jobLog.scrollHeight;
}

// ── 合成窗口径联动（见文件头第 2 条）──────────────────────────────

function refreshWinHint() {
  if (state.profile === null) { hint(ui.winHint, '', ''); return; }
  const rec = !!state.profile.glb_windows;
  const cur = windowsOn();
  hint(ui.winHint,
    rec ? (cur ? '本楼档案口径：带合成窗 ✓'
      : '本楼档案口径：带合成窗，当前开关未勾选 —— 重出会剥掉窗户')
      : (cur ? '本楼档案口径：不带窗，当前开关已勾选 —— 重出会加上窗户'
        : '本楼档案口径：不带窗'),
    rec === cur ? '' : 'err');
}

/** 只把档案值映到开关上，不写盘（选中楼栋时用）。 */
function applyWinToggle(on) {
  if (ui.winToggle) ui.winToggle.checked = !!on;
  const cb = document.getElementById('pf-glb_windows');
  if (cb) cb.checked = !!on;
  refreshWinHint();
}

/** 用户改了开关 ⇒ 记进档案（不记的话，下次点按钮就得重新猜这个口径）。 */
async function onWinToggleChange() {
  refreshWinHint();
  if (!state.profile) return;
  const on = windowsOn();
  state.profile.glb_windows = on;
  const cb = document.getElementById('pf-glb_windows');
  if (cb) cb.checked = on;
  if (!state.caps?.write_enabled) {
    hint(ui.winHint, '开关改了，但没能记进档案：' + (state.caps?.write_disabled_reason || '没有写权限')
      + '　⇒ 下次点「生成 GLB」用的还是档案里那个旧口径。', 'err');
    return;
  }
  try {
    await API.consolePutProfile(state.name, state.profile);
    refreshWinHint();
  } catch (e) {
    hint(ui.winHint, `口径未能记入档案：${msgOf(e)}　⇒ 下次点「生成 GLB」用的还是档案里那个旧口径。`, 'err');
  }
}

// ── 预览：三维 ───────────────────────────────────────────────────

/** 切到预览页时的懒动作：**只在可见时**建渲染器（隐藏时盒子是 0 尺寸，建了也白建）。 */
function onPreviewShown() {
  if (state.tab !== 'preview' || state.pvsub !== 'model') return;
  if (!state.viewer) { ensureViewer().then(() => { loadModel(); }).catch(() => {}); return; }
  state.viewer.resize();
  state.viewer.start();
}

async function ensureViewer() {
  if (state.viewer || disposed) return;
  const mod = state.viewerMod || await import('/site/js/viewer.js');
  if (disposed) return;
  state.viewerMod = mod;
  // ★ 画布就这么一块，而且**只建一次**：每建一次就多一个 WebGL 上下文，
  //   浏览器上限约 16 个，超了静默丢掉最老的（见文件头）。
  const canvas = el('canvas', { class: 'csl-canvas' });
  mount(ui.viewbox, canvas);
  state.viewer = mod.createViewer(canvas);
  state.viewer.start();
}

function paintPreviewInfo() {
  const r = state.rows.find((x) => x.name === state.name);
  if (!r) { hint(ui.pvStatus, '没选楼。', ''); return; }
  if (!r.links || !r.links.glb) {
    hint(ui.pvStatus, r.glb
      ? '模型文件在盘上，但本服务没为它开通路（服务端没给出 URL）。'
      : '这栋还没有 GLB —— 去「流程」跑「生成 GLB」。', r.glb ? 'warn' : '');
    return;
  }
  hint(ui.pvStatus, `模型：${r.links.glb}`, '');
}

async function loadModel() {
  const r = state.rows.find((x) => x.name === state.name);
  const url = r?.links?.glb;
  if (!url) { paintPreviewInfo(); return; }
  if (!state.viewer) return;
  // 换了楼（或重出过）就清掉上一个模型 —— `viewer.load` 自己也会 clearModel，
  // 但**换楼**这一趟可能走的是"URL 相同但内容变了"，所以带一个缓存破除参数。
  const bust = url + (url.includes('?') ? '&' : '?') + 't=' + Date.now();
  state.viewerUrl = url;
  hint(ui.pvStatus, `载入中… ${url}`, 'run');
  try {
    const info = await state.viewer.load(bust, (loaded, total) => {
      hint(ui.pvStatus, total
        ? `载入中… ${(loaded / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB`
        : `载入中… ${(loaded / 1048576).toFixed(1)} MB`, 'run');
    });
    if (disposed) return;
    // ★ 报的是**几何量**，不是"HTTP 200"：三角面数为 0 就是真没东西。
    hint(ui.pvStatus, `${url}　三角面 ${fmt(info.triangles)}　`
      + `尺寸 ${info.size.x.toFixed(1)} × ${info.size.y.toFixed(1)} × ${info.size.z.toFixed(1)} m`
      + (r.glbStale ? '　★ 这个模型可能过期（GLB 早于最新楼层数据）' : ''),
      info.triangles > 0 ? 'ok' : 'err');
  } catch (e) {
    if (disposed) return;
    hint(ui.pvStatus, `载入失败：${msgOf(e)}`, 'err');
  }
}

// ── 预览：识别平面图 ─────────────────────────────────────────────

/**
 * 取一层识别平面图。
 *
 * ★ 用 `fetch` 而不是直接 `<img src>`：`<img>` 的 onerror 分不清 404 与 503，
 *   而这两条路的补救办法**相反**（换一层 vs 装 ezdxf）。这里的 404/503 都回
 *   **信封**（`routers/console.py`），所以能把服务端那句话原样端到屏幕上。
 */
async function loadPlan() {
  if (!state.name) return;
  const n = state.name;
  const F = state.floor;
  revoke('planObjUrl');
  hint(ui.pvStatus, `取 F${F} 层…`, 'run');
  mount(ui.planbox, el('div', { class: 'csl-empty', text: '读取中…（现算，比别的慢）' }));
  try {
    const res = await fetch(API.url.consoleFloorPng(n, F), { cache: 'no-store' });
    if (disposed) return;
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      let code = '';
      try {
        const j = await res.json();
        code = j?.error?.code || (j?.detail ? 'fastapi_422' : '');
        msg = j?.error?.message || (j?.detail ? JSON.stringify(j.detail).slice(0, 200) : msg);
      } catch { /* 不是 JSON（真出了张图以外的什么）—— 就用状态码说 */ }
      hint(ui.pvStatus, `取不到：${msg}${code ? `　（${code}）` : ''}`, 'err');
      mount(ui.planbox, el('div', { class: 'csl-empty', text: '这一层没有图可看。' }));
      return;
    }
    const blob = await res.blob();
    if (disposed) return;
    state.planObjUrl = URL.createObjectURL(blob);
    mount(ui.planbox, el('img', {
      class: 'csl-plan', src: state.planObjUrl,
      alt: `${n} F${F} 层识别平面图（墙黑/门红/柱蓝/梯绿）`,
    }));
    hint(ui.pvStatus, `${n} F${F}　${(blob.size / 1024).toFixed(0)} KB`, 'ok');
  } catch (e) {
    if (disposed) return;
    hint(ui.pvStatus, `连不上：${msgOf(e)}`, 'err');
    mount(ui.planbox, el('div', { class: 'csl-empty', text: '没取到。' }));
  }
}

/** 下载本层 DXF。**0 字节也要说** —— 它回的是 404「这一层没有实体」，不是空文件。 */
async function downloadDxf() {
  if (!state.name || state.dxfBusy) return;
  state.dxfBusy = true;
  const n = state.name;
  const F = state.floor;
  hint(ui.pvStatus, `取 F${F} 层 DXF…`, 'run');
  try {
    const res = await fetch(API.url.consoleFloorDxf(n, F), { cache: 'no-store' });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const j = await res.json(); msg = j?.error?.message || msg; } catch { /* 用状态码说 */ }
      hint(ui.pvStatus, `取不到 DXF：${msg}`, 'err');
      return;
    }
    const blob = await res.blob();
    const a = el('a', { href: URL.createObjectURL(blob), download: `${n}-F${F}.dxf` });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => { try { URL.revokeObjectURL(a.href); } catch { /* 已失效 */ } }, 4000);
    hint(ui.pvStatus, `已下载 ${n}-F${F}.dxf　${(blob.size / 1024).toFixed(0)} KB`, 'ok');
  } catch (e) {
    hint(ui.pvStatus, `连不上：${msgOf(e)}`, 'err');
  } finally {
    state.dxfBusy = false;
  }
}

// ── 装配 ─────────────────────────────────────────────────────────

function orderApply() {
  ui.search.oninput = () => paintList();
}

/**
 * @param {HTMLElement} root 挂载点（app.js 给的是 #main）
 * @param {string} sub 形如 '' 或 'c113'（楼号）
 */
export function render(root, sub) {
  disposed = false;
  cleanups = [];
  buildShell(root);
  orderApply();
  paintLayout();
  loadAll(sub);
  // 兜底：切走这一屏时如果还有作业在轮询，`dispose()` 会把它停掉（见下）。
}

export function dispose() {
  disposed = true;
  clearTimer();
  // ★ 三维那一路必须显式收（见文件头）：只让 `mount()` 把节点清掉是不够的 ——
  //   渲染循环还在跑、WebGL 上下文还占着，切够十几次就会静默丢最老的上下文。
  try { state.viewer?.dispose(); } catch { /* 收尾失败不该挡住切换 */ }
  state.viewer = null;
  state.viewerMod = null;
  state.viewerUrl = null;
  revoke('planObjUrl');
  for (const f of cleanups.splice(0)) {
    try { f(); } catch { /* 同上 */ }
  }
  state.rows = []; state.counts = null; state.registry = null; state.broken = [];
  state.meta = null; state.profile = null; state.spec = null; state.status = null;
  state.caps = null; state.capsErr = null; state.rowsErr = null;
  state.running = false; state.jobId = null; state.pollFails = 0;
  state.name = null;
}
