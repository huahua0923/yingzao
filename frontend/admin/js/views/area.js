// 「面积」视图 —— 把不同口径的面积并排摆出来。
//
// ★★ 本仓有一条铁律：面积四口径绝不许混用（建筑面积/外墙外围、房间净面积/墙内皮…）。
//   所以这一屏存在的意义不是给一个「这栋楼多大」的数，而是把每个数连着它的口径
//   摆在一起，让人自己看口径差在哪。任何把两个口径合成一个数的做法都是这一屏的反面。
//
// 口径不是前端猜的，是从对账脚本自己的口径说明里抄下来的（逐条列在 CALIBERS，
// 每条带来源）。抄不到来源的字段一律显示成「口径不明」—— 不替它认领一个口径。
//
// ★ 三条与 checks 视图同一个模子的规矩：
//   1. 「读不到」不许变成「0」或空白。快照读不到 / 接口挂了 ⇒ 明说，并说明这一屏没有数。
//   2. 「没量过」不许混进「对上了」。unauditable 的楼单独一栏，不参与任何计数分母。
//   3. 快照不是实时。这份表是某次全库对账跑完那一刻的 copy，页面上必须写清是哪一份。
import { el, add, mount, table } from '../dom.js';
import { API, ApiError, getEnv } from '../api.js';

export const label = '面积';

let disposed = false;
let inflight = null;

export function dispose() {
  disposed = true;
  inflight?.abort();
  inflight = null;
  // 重算的 POST 不挂 abort：它已经在后端起子进程了，中断请求不会杀掉它，
  // 只会让这一次的结果没人接。所以只把渲染停掉（disposed 标志），不做假装的中断。
}

// ── 口径字典（本屏的核心）───────────────────────────────────────
//
// 每一条都必须能说出来源。来源就是这三处，都是外部量具/引擎自己的话：
//   · _scratch/_area_audit.py 的模块 docstring（口径说明）
//   · _scratch/_area_audit.py:55  `d.get("建筑面积", "")`（读的是哪一栏）
//   · backend/api/services/artifacts.py:177（模型侧是「各层 outline 面积之和」）
//
// ★ 注意图纸那张表里还有「使用面积」，本对账没有用它 —— 所以本页出现的
//   数一个都不是「使用面积/房间净面积」那个口径。这一点要写出来，否则看的人会自己脑补。
const CALIBERS = {
  worst_drawing_m2: {
    key: 'draw', tag: '图纸', name: '建筑面积',
    src: 'DXF 的 ACAD_TABLE(0 图层)「建筑面积」栏 —— 画图人写在图里的数',
    caveat: '按层、不含屋面。表里还有「使用面积」，本对账没有用它。',
  },
  worst_model_m2: {
    key: 'model', tag: '模型', name: '楼板足迹',
    src: 'recognizer.outline.floor_outline() 的面积逐层相加 —— 我们算的',
    caveat: '含退台屋面/裙楼屋面这类「板上还要铺屋面」的块，所以顶层天然偏大。',
  },
  worst_m2: {
    key: 'delta', tag: '差', name: '模型 − 图纸',
    src: '_area_audit.py:112 `d = mod[i] - tab[k][0]`，取 |差| 最大的那层',
    caveat: '这是两个口径的差，不是任何一个口径的面积，不许当面积读。',
  },
  avg_m2: {
    key: 'delta', tag: '差', name: '逐层差的平均（模型 − 图纸）',
    src: '_area_audit.py:116 `avg = sum(ds) / len(ds)`',
    caveat: '同样是差值，不是面积。',
  },
  abs_m2: {
    key: 'delta', tag: '差', name: '|逐层差的平均|',
    src: '后端 `abs_m2 = abs(avg_m2)`（只有量级，没有方向）',
    caveat: '丢了正负号：+1000 和 −1000 在这一栏上一样。看方向要看 avg_m2。',
  },
  worst_floor: {
    key: 'basis', tag: '基准', name: '模型层号（F 0 基）',
    src: '_area_audit.py 打印 `F%d` 用的是 `w[0] - 1`，即图纸「楼层」(1 基) 换算成模型层号',
    caveat: '图纸的「楼层」是 1 基、模型是 F 0 基，差一层。这一栏是模型那一侧。',
  },
  pairs: {
    key: 'count', tag: '计数', name: '可比对的层数',
    src: '_area_audit.py:113 `if i not in mod: continue` 之后剩下的层数',
    caveat: '不是面积。图纸表有、模型没有的层不进来。',
  },
  verdict: {
    key: 'verdict', tag: '判定', name: '引擎按门槛给的结论',
    src: 'backend/api/services/area_audit.py:104，|平均偏差| ≤200 对得上 / ≤800 可疑 / >800 缺口',
    caveat: '门槛是逐项判据，不是「平均值小于阈值就整栋过」。',
  },
  name: { key: 'name', tag: '标识', name: '楼栋名', src: '对账行的第一栏', caveat: '不是面积。' },
};

const VERDICT_UI = {
  reconciled: { cn: '对得上', cls: 'ok' },
  watch: { cn: '可疑', cls: 'warn' },
  gap: { cn: '缺口', cls: 'bad' },
};

/** 一个数的口径标签。查不到就返回 null —— 调用方要显示「口径不明」。 */
function caliberOf(field) { return CALIBERS[field] || null; }

/** 口径的样式类：用 ASCII 键，不用中文当 class 名。 */
function calClass(c) { return c ? `ar-cal ar-cal-${c.key}` : null; }

function unknownChip() {
  return el('span', { class: 'ar-unknown',
    title: '后端给了这个字段，但这一屏找不到它的口径来源 —— 不替它认领一个口径',
    text: '口径不明' });
}

/** 通用的「带口径的数字格」。口径不明时把话说在屏幕上，不只挂在 title 里。 */
function numCell(field, value, fmt = fmtM2) {
  const c = caliberOf(field);
  return el('td', { class: 'num ar-num' },
    el('span', { text: fmt(value) }),
    c ? null : unknownChip());
}

/**
 * 带正负号的数字格（差这一类）。正负号本身有信息量，所以不能走 fmtM2。
 *
 * ★ 为什么要单独一个函数，而不是就地在 td 里写 span：
 *   就地写的那两栏（worst_m2 / avg_m2）**漏掉了口径标记** —— 同一个表里
 *   有的数带口径、有的不带，读的人会以为不带的那几个是"不需要口径"。
 *   数是要紧的，所以这一格也走同一条「查不到口径就当场说」的路。
 */
function signedCell(field, value) {
  const c = caliberOf(field);
  return el('td', { class: 'num ar-num' },
    el('span', { class: value > 0 ? 'pos' : value < 0 ? 'neg' : '',
      text: fmtSigned(value) }),
    c ? null : unknownChip());
}

/** ㎡，一位小数，带千分位；null/undefined → 「—」（不是 0）。 */
function fmtM2(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${Number(v).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
}

/** 带正负号的差值 —— 差值的正负号是有信息量的，不能省。 */
function fmtSigned(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  // −0.0 不是"朝下的零"，它是四舍五入的产物（c117 逐层差就是这么来的）。
  // 写成「-0.0」会让人以为方向朝下，所以先把它夹成 0。
  const r = Math.abs(n) < 0.05 ? 0 : n;
  return `${r > 0 ? '+' : ''}${fmtM2(r)}`;
}

function verdictTag(v) {
  const ui = VERDICT_UI[v];
  if (!ui) return el('span', { class: 'tag dim', text: v ? String(v) : '未给判定' });
  return el('span', { class: `tag ${ui.cls}`, text: `${v}（${ui.cn}）` });
}

// ── 公用小件 ───────────────────────────────────────────────────

function panic(err, opts = {}) {
  const e = err instanceof ApiError ? err : new ApiError('unknown', String(err));
  const down = e.code === 'network' || e.status === 0;
  const box = el('div', { class: `ar-panic${down ? ' down' : ''}` },
    el('h2', { class: 'ar-panic-h', text: down ? '接口不可用' : `取数失败：${e.code}` }),
    el('p', { class: 'ar-panic-msg', text: e.message || String(err) }));
  add(box, el('div', { class: 'ar-panic-body' },
    el('p', {}, down
      ? '这一屏现在一个数都没有 —— 所以这里不画表、也不显示 0。'
        + '「没读到」和「面积是 0」在屏幕上必须是两件事。'
      : '后端回了错误信封，下面是它给的原话。'),
    el('p', { class: 'dim' },
      '取的是 ', el('code', { text: opts.endpoint || '/api/analysis/area' }),
      '；后端地址：', el('code', { text: window.GYM3D_API_BASE || '同源（当前页所在主机）' })),
    e.detail ? el('details', { class: 'ar-details' },
      el('summary', { text: '后端给的细节（原样）' }),
      el('pre', { class: 'ar-ev', text: JSON.stringify(e.detail, null, 2) })) : null,
    opts.onRetry ? el('div', { class: 'ar-toolbar' },
      el('button', { class: 'ar-btn primary', type: 'button', text: '重试', onclick: opts.onRetry })) : null));
  return box;
}

function busy(text) {
  return el('div', { class: 'ar-busy' }, el('span', { class: 'spin' }), text);
}

/** 「这份东西不存在/没量到」的写法：虚线框，与「0」在形状上就不同。 */
function absent(what) {
  return el('p', { class: 'ar-absent', text: what });
}

// ── 快照条：这些数是从哪来的 ────────────────────────────────────

/**
 * @param {object|null} src   data.source（file/mtime_iso/bytes）
 * @param {object|null} caps  /api/capabilities（问不到就是 null）
 */
function snapshotBar(src, caps, meta) {
  const bits = [];
  if (!src) {
    bits.push(el('div', { class: 'ar-snap-line' },
      el('b', { class: 'miss', text: '这份响应里没有 source —— 不知道这些数是哪份快照、什么时候跑的。' })));
  } else {
    bits.push(el('div', { class: 'ar-snap-line' },
      el('span', { class: 'ar-snap-k', text: '快照文件' }),
      el('code', { text: src.file || '—' }),
      el('span', { class: 'ar-snap-k', text: '跑于' }),
      el('b', { class: 'num', text: src.mtime_iso || '（没给时间）' }),
      el('span', { class: 'ar-snap-k', text: '大小' }),
      el('span', { class: 'num', text: src.bytes === undefined ? '—' : `${src.bytes} B` })));
    bits.push(el('p', { class: 'ar-snap-note' },
      '★ 这是快照不是实时：读路径只解析已落盘的日志，绝不现算。'
      + '所以这一屏反映的是那次全库对账跑完那一刻，不是此刻的真实。'));
  }

  // 能力接口报的那份快照，与这一屏读到的对不上 ⇒ 必须喊出来。
  const claimed = caps?.area_audit_snapshot;
  if (!caps) {
    bits.push(el('p', { class: 'ar-snap-warn' },
      '取不到 /api/capabilities，所以无法核对「能力接口报的快照」和这一屏读到的'
      + '是不是同一份 —— 这个核对没做成，不等于核对通过。'));
  } else if (!claimed) {
    bits.push(el('p', { class: 'ar-snap-note dim' },
      '/api/capabilities 里没有 area_audit_snapshot 字段 —— 这一屏也就无从核对快照来源。'));
  } else if (src?.file && claimed !== src.file) {
    bits.push(el('p', { class: 'ar-snap-warn' },
      `★ 两份不是同一份：capabilities().area_audit_snapshot = ${claimed}，`
      + `而这一屏读到的是 ${src.file}。别把它们当同一批数用。`));
  } else {
    bits.push(el('p', { class: 'ar-snap-ok' },
      `能力接口报的快照与本页读到的一致：`, el('code', { text: claimed })));
  }
  if (meta?.hint) bits.push(el('p', { class: 'ar-snap-note dim', text: meta.hint }));
  return el('div', { class: 'ar-snap' }, bits);
}

// ── 口径图例：这一屏的说明书 ────────────────────────────────────

function caliberLegend() {
  const rows = [
    ['draw', '图纸', '建筑面积', '图纸自带面积表（DXF ACAD_TABLE）里画图人写的「建筑面积」',
      '按层、不含屋面。表里另有「使用面积」，本对账没用它。'],
    ['model', '模型', '楼板足迹', '我们算的：recognizer.outline.floor_outline() 的面积逐层相加',
      '含退台/裙楼屋面那些「板上还要铺屋面」的块。'],
    ['delta', '差', '模型 − 图纸', '两个口径之差，带正负号',
      '不是面积。本屏所有「差」栏都不许当面积读。'],
  ];
  return el('div', { class: 'ar-legend' },
    el('table', { class: 'ar-legend-t' },
      el('thead', {}, el('tr', {},
        el('th', { text: '侧' }), el('th', { text: '口径名' }),
        el('th', { text: '这个数是怎么来的' }), el('th', { text: '要怎么读' }))),
      el('tbody', {}, rows.map((r) => el('tr', {},
        el('td', {}, el('span', { class: `ar-cal ar-cal-${r[0]}`, text: r[1] })),
        el('td', { class: 'ar-legend-name', text: r[2] }),
        el('td', { class: 'dim', text: r[3] }),
        el('td', { class: 'dim', text: r[4] }))))),
    el('p', { class: 'ar-legend-note' },
      '★ 本屏只有这两个面积口径。四口径里的「房间净面积 / 墙内皮」不在这条接口上'
      + '（那要看 ', el('code', { text: '/api/buildings/{楼}/rooms' }), '）——'
      + '不要拿这里的数当净面积用。全屏不提供任何「把两个口径合成一个数」的写法。'));
}

// ── 全库 ───────────────────────────────────────────────────────

function fleetKpis(counts, totalBuildings) {
  const items = [
    ['对账过的楼', counts.audited, 'ok', '快照里有对账行的栋数（= 下面的表长）'],
    ['对得上', counts.reconciled, 'ok', '|平均偏差| ≤ 200㎡'],
    ['可疑', counts.watch, 'warn', '200 < |平均偏差| ≤ 800㎡'],
    ['缺口', counts.gap, 'bad', '|平均偏差| > 800㎡'],
    ['无法对账', counts.unauditable, 'dim2', '图纸里没有面积表 —— 这不是「对上了」'],
  ];
  return el('div', {},
    el('div', { class: 'ar-kpis' }, items.map(([k, v, cls, n]) =>
      el('div', { class: `ar-kpi ${cls}` },
        el('span', { class: 'k', text: k }),
        el('span', { class: 'v', text: v === undefined || v === null ? '—' : String(v) }),
        el('span', { class: 'n', text: n })))),
    el('p', { class: 'ar-denom' },
      '分母写在这：全库在册 ', el('b', { text: String(totalBuildings ?? '—') }), ' 栋，'
      + '快照里对账过 ', el('b', { text: String(counts.audited ?? '—') }), ' 栋，'
      + '另有 ', el('b', { text: String(counts.unauditable ?? '—') }), ' 栋',
      el('b', { text: '无法对账' }),
      '（图纸里没有面积表）。「无法对账」和「对得上」不是一回事 —— '
      + '把它们混起来，就是「没量过」被读成「全对」。'));
}

function fleetTable(rows, filter, query) {
  if (!Array.isArray(rows)) return absent('响应里没有 rows 数组 —— 读不到对账行。');
  if (!rows.length) {
    return el('div', { class: 'ar-none' },
      el('b', { text: '这个快照里一条对账行都没有。' }),
      '这是「没有」，不是「全部对上了」—— 空表会被读成「零问题」。');
  }
  const q = (query || '').trim().toLowerCase();
  const shown = rows.filter((r) => {
    if (filter === 'problem' && r.verdict === 'reconciled') return false;
    if (q && !String(r.name).toLowerCase().includes(q)) return false;
    return true;
  });
  return el('div', {},
    el('p', { class: 'ar-count',
      text: `下面这张表：${shown.length} 行 / 快照里共 ${rows.length} 行`
        + (filter === 'problem' ? '（只看可疑与缺口）' : '')
        + (q ? `（名字含 ${JSON.stringify(q)}）` : '') }),
    table([
      { label: '楼栋' },
      { label: '图纸 · 建筑面积', cls: 'num' },
      { label: '模型 · 楼板足迹', cls: 'num' },
      { label: '差（模型−图纸）※不是面积', cls: 'num' },
      { label: '最差那层（模型层号）', cls: 'num' },
      { label: '对数（可比层的层数）', cls: 'num' },
      { label: '平均偏差（差）', cls: 'num' },
      { label: '|平均偏差|（丢了正负）', cls: 'num' },
      { label: '判定（引擎门槛）' },
    ], shown.map((r) => el('tr', { class: `ar-row v-${r.verdict}` },
      el('td', { class: 'name' }, el('a', {
        class: 'lnk', href: `#/area/${encodeURIComponent(r.name)}`, text: r.name })),
      numCell('worst_drawing_m2', r.worst_drawing_m2),
      numCell('worst_model_m2', r.worst_model_m2),
      signedCell('worst_m2', r.worst_m2),
      el('td', { class: 'num ar-num' },
        el('span', { text: `F${r.worst_floor}` }),
        el('span', { class: 'ar-basis', title: '层号基准：模型层号（F 0 基）。'
          + '图纸的「楼层」是 1 基，脚本做了 k−1 换算。', text: '模型层' })),
      numCell('pairs', r.pairs, (v) => (v === null || v === undefined ? '—' : String(v))),
      signedCell('avg_m2', r.avg_m2),
      numCell('abs_m2', r.abs_m2),
      el('td', {}, verdictTag(r.verdict)))), { cls: 'ar-table' }));
}

function unauditableBlock(list) {
  if (!Array.isArray(list)) return absent('响应里没有 unauditable 数组 —— 读不到「无法对账」的名单。');
  if (!list.length) {
    return el('p', { class: 'ar-okline',
      text: '这个快照里没有「无法对账」的楼 —— 每一栋都在表里。' });
  }
  return el('div', { class: 'ar-unaud' },
    el('p', { class: 'ar-unaud-h' },
      el('b', { text: `${list.length} 栋无法对账。` }),
      '这几栋一个数都没有，不是「对上了」、也不是「偏差为 0」 —— 它们在表里不占行，'
      + '在这里单列，就是为了不让它们消失。'),
    el('ul', { class: 'ar-ul' }, list.map((u) =>
      el('li', {}, el('b', { class: 'mono', text: u.name }), ' — ', u.why || '（没给原因）'))));
}

function perFloorBlock(perFloor, nameFilter) {
  const keys = Object.keys(perFloor || {});
  if (!keys.length) {
    return absent('这份快照里没有逐层明细（per_floor 为空）—— '
      + '全库脚本只出排名，不确定单栋的逐层对照。'
      + '要看逐层，对某一栋跑一次「重算」（下面单栋页有按钮），或在命令行跑 '
      + '`python -u _scratch/_area_audit.py <楼号>`。');
  }
  const pend = keys.filter((k) => !nameFilter || k === nameFilter);
  if (!pend.length) return absent(`快照里有逐层明细，但没有 ${nameFilter} 的。`);
  return el('div', {}, pend.map((k) => el('div', {},
    el('h3', { class: 'ar-h3', text: `${k} 逐层（${(perFloor[k] || []).length} 层）` }),
    (perFloor[k] || []).length
      ? table([
        { label: '图纸楼层（1 基）', cls: 'num' },
        { label: '模型层号（0 基）', cls: 'num' },
        { label: '图纸·建筑面积', cls: 'num' },
        { label: '模型·楼板足迹', cls: 'num' },
        { label: '差（模型−图纸）', cls: 'num' },
        { label: '图纸里的房间数' },
      ], (perFloor[k] || []).map((f) => [String(f.drawing_floor), `F${f.model_floor}`,
        fmtM2(f.drawing_m2), fmtM2(f.model_m2),
        el('span', { class: f.delta_m2 > 0 ? 'pos' : f.delta_m2 < 0 ? 'neg' : '',
          text: fmtSigned(f.delta_m2) }),
        f.drawing_rooms === null || f.drawing_rooms === undefined
          ? '—' : String(f.drawing_rooms)]), { cls: 'ar-table' })
      : absent('这一栋有明细条目，但里面一层都没有。'))));
}

async function paintFleet(root) {
  mount(root, busy('正在读面积对账快照…'));
  const state = { filter: 'all', query: '' };
  inflight = new AbortController();
  try {
    // 能力接口只用来核对「这份快照是哪份」 + 写权限；取不到不该挡住看数。
    const [env, caps] = await Promise.all([
      getEnv('/api/analysis/area', { signal: inflight.signal }),
      API.capabilities().catch(() => null),
    ]);
    if (disposed) return;
    const d = env?.data || {};
    const counts = d.counts || {};
    const body = el('div', {});
    const rerender = () => {
      mount(body, fleetKpis(counts, caps?.buildings),
        controls(state, rerender),
        fleetTable(d.rows, state.filter, state.query),
        // ★ 下面两块是这一屏最容易缺的：无法对账的楼（没量过）与逐层明细（可能没有）。
        //   少了它们，"没量过"就只剩表里"没有那一行"，读起来跟"全对"一模一样。
        el('h2', {}, '无法对账（没量过 —— 不等于对上了）'),
        unauditableBlock(d.unauditable),
        el('h2', {}, '逐层明细'),
        perFloorBlock(d.per_floor, null),
        el('p', { class: 'dim cmp-src',
          text: '本页不提供"全库重算"的入口：全库重算是另一件事，不该藏在一个顺手点的按钮里。'
            + '单栋重算在每栋的详情页（点楼号进去）。' }));
    };
    mount(root,
      el('h1', {}, '面积 · 口径并排',
        el('span', { class: 'ar-sub', text: ' 两个口径并排摆着，不合成一个数' })),
      el('p', { class: 'lede' },
        '这一屏的全部意义是', el('b', { text: '把不同口径并排' }),
        '：图纸自带面积表给的是建筑面积，我们的模型给的是楼板足迹 —— '
        + '两者天然不等（差在墙厚外皮与屋面块），所以判据是「同量级 + 逐层趋势」而不是「相等」。'
        + '任何把两个口径合成一个数的写法都是这一屏的反面。'),
      el('h2', {}, '这些数是从哪来的'),
      snapshotBar(d.source, caps, env?.meta),
      el('h2', {}, '口径对照（每个数都带口径）'),
      caliberLegend(),
      el('h2', {}, '全库'),
      body);
    rerender();
  } catch (e) {
    if (disposed) return;
    mount(root, panic(e, { endpoint: '/api/analysis/area', onRetry: () => paintFleet(root) }));
  }
}

function controls(state, rerender) {
  const search = el('input', { type: 'search', value: state.query,
    placeholder: '按楼号过滤', 'aria-label': '按楼号过滤',
    oninput: (e) => { state.query = e.target.value; rerender(); } });
  return el('div', { class: 'ar-toolbar' },
    el('label', { class: 'ar-check' },
      el('input', { type: 'checkbox', checked: state.filter === 'problem',
        onchange: (e) => { state.filter = e.target.checked ? 'problem' : 'all'; rerender(); } }),
      '只看可疑与缺口'),
    search,
    el('span', { class: 'dim', text: '（按 |平均偏差| 从大到小，后端排好的）' }));
}

// ── 单栋 ───────────────────────────────────────────────────────

/** 一栋的两个口径并排 —— 这一屏的核心版式。 */
function caliberPair(d) {
  const one = (field, big) => {
    const c = caliberOf(field);
    return el('div', { class: `ar-pair-side t-${c ? c.key : 'unknown'}` },
      el('div', { class: 'ar-pair-head' },
        c ? el('span', { class: calClass(c), text: c.tag }) : unknownChip(),
        el('span', { class: 'ar-pair-name', text: c ? c.name : '口径不明' })),
      el('div', { class: 'ar-pair-v num', text: fmtM2(d[field]) }),
      el('div', { class: 'ar-pair-src dim', text: c ? c.src : '—— 找不到这个字段的口径来源，不替它认领。' }),
      c ? el('div', { class: 'ar-pair-cav dim', text: c.caveat }) : null);
  };
  return el('div', { class: 'ar-pairs' },
    one('worst_drawing_m2'), one('worst_model_m2'),
    el('div', { class: 'ar-pair-side t-差' },
      el('div', { class: 'ar-pair-head' },
        el('span', { class: 'ar-cal ar-cal-delta', text: '差' }),
        el('span', { class: 'ar-pair-name', text: '模型 − 图纸' })),
      el('div', { class: 'ar-pair-v num',
        text: fmtSigned(d.worst_m2) }),
      el('div', { class: 'ar-pair-src dim',
        text: '两个口径之差 —— 不是面积。上面两块才是面积。' }),
      el('div', { class: 'ar-pair-cav dim',
        text: `取的是最差那一层；该层 = ${d.worst_floor === undefined ? '—' : `F${d.worst_floor}`}`
          + '（模型层号，F 0 基）' })));
}

/** 重算面板（写操作）。分级：不可用就禁用并说明原因；可用就要确认 + 明确反馈。 */
function refreshPanel(name, caps) {
  const box = el('div', { class: 'ar-refresh' });
  const enabled = !!caps?.write_enabled;
  const mkBtn = () => el('button', {
    class: 'ar-btn primary', type: 'button', text: `重算 ${name} 的面积`,
    disabled: !enabled, title: enabled ? '' : (caps?.write_disabled_reason || '写权限未知'),
    onclick: async () => {
      // ★ 单栋、且要确认。这一屏不提供全库批量入口 —— 全库重算是另一件事，
      //   不该藏在一个顺手点的按钮里。
      const okGo = window.confirm(
        `对 ${name} 重跑一次面积对账？\n\n`
        + '· 会在后端起一个子进程读 DXF（几秒到几分钟）\n'
        + '· 结果只回给这一屏，不会写进全库快照\n'
        + '· 期间这一屏会等着，别重复点');
      // 取消也要出声：什么都不发生 + 什么都不说 = 让人以为按钮坏了（本仓老毛病）。
      if (!okGo) {
        mount(box, el('div', { class: 'ar-toolbar' }, mkBtn()),
          el('p', { class: 'ar-okline',
            text: '已取消：没有发请求，也没有算任何东西 —— 上面的数还是快照里那份。' }));
        return;
      }
      mount(box, busy(`正在对 ${name} 重跑面积对账（后端起子进程读 DXF，可能要几分钟）…`));
      try {
        const env = await API.areaRefresh(name);
        if (disposed) return;
        const r = env?.data || {};
        mount(box, resultPanel(name, r, env?.meta));
      } catch (e) {
        if (disposed) return;
        mount(box, el('div', { class: 'ar-refresh-fail' },
          el('b', { text: '重算失败。' }),
          el('span', { text: e.message || String(e) }),
          e.code ? el('span', { class: 'dim', text: `（${e.code}）` }) : null,
          e.detail ? el('details', { class: 'ar-details' },
            el('summary', { text: '后端给的细节（原样）' }),
            el('pre', { class: 'ar-ev', text: JSON.stringify(e.detail, null, 2) })) : null),
        el('p', { class: 'ar-snap-note',
          text: '★ 失败就是失败：上面的表还是快照里的旧值，没有因为这次失败而变成 0。' }));
      }
      onDone();
    },
  });
  // 点过之后面板会被 busy/结果面板整个替换掉，所以结果里要自带"再来一次"的入口
  // （按钮本体已经随 mount 被拆掉了，不重建的话这一屏就再也不能重算了）。
  const onDone = () => add(box, el('div', { class: 'ar-toolbar' }, mkBtn()));
  add(box, el('div', { class: 'ar-toolbar' }, mkBtn()),
    el('p', { class: 'ar-write' },
      '写权限：', enabled
        ? el('b', { class: 'ok-t', text: '开' })
        : el('b', { class: 'miss', text: '关' }),
      enabled ? '（本进程 compute=1，可以起子进程现算）'
        : ` —— 按钮已禁用。原因：${caps?.write_disabled_reason || '取不到 /api/capabilities，无法确认写权限'}`,
      enabled ? null : el('br'),
      enabled ? null : el('span', { class: 'dim',
        text: '（写权限问的是 GET /api/capabilities 的 write_enabled；问不到时按「不可用」处理，不猜。）' })),
    el('p', { class: 'dim', text: '本页只提供单栋重算，没有全库批量入口 —— 要更新全库表，自己在命令行跑 `python -u _scratch/_area_audit.py`（不带参数=全库）。' }));
  return box;
}

function resultPanel(name, r, meta) {
  if (r.audited === false) {
    return el('div', { class: 'ar-refresh-res' },
      el('h3', { class: 'ar-h3', text: `${name}：重算跑完了，但没量成` }),
      el('p', { class: 'ar-warnline', text: `原因：${r.why || '（后端没给原因）'}` }),
      el('p', { class: 'dim',
        text: '这是「没量成」，不是「对上了」，也不是「偏差 0」。' }),
      r.floors?.length ? perFloorBlock({ [name]: r.floors }) : null,
      r.stdout_tail ? el('details', { class: 'ar-details' },
        el('summary', { text: '脚本原样输出（尾部）' }),
        el('pre', { class: 'ar-ev', text: r.stdout_tail })) : null);
  }
  return el('div', { class: 'ar-refresh-res' },
    el('h3', { class: 'ar-h3', text: `${name}：重算完成（本次现算，${meta?.mode || 'live'}）` }),
    caliberPair(r),
    el('p', { class: 'ar-snap-note' },
      '★ 这次的结果', el('b', { text: '只回给这一屏' }),
      '，没有写进全库快照 —— 上面的全库表还是快照里的旧值。'
      + '要更新全库表得跑全库脚本。'),
    r.floors?.length
      ? perFloorBlock({ [name]: r.floors })
      : absent('这次现算连逐层明细也没回（floors 为空）—— 不是「逐层都对上了」。'));
}

async function paintOne(root, name) {
  mount(root, busy(`正在读 ${name} 的面积对账…`));
  inflight = new AbortController();
  const back = el('a', { class: 'lnk', href: '#/area', text: '← 回全库' });
  try {
    const [env, caps] = await Promise.all([
      getEnv(`/api/analysis/area/${name}`, { signal: inflight.signal }),
      API.capabilities().catch(() => null),
    ]);
    if (disposed) return;
    const d = env?.data || {};
    const refreshBox = el('div', {});
    const body = el('div', {},
      el('h2', {}, '快照来源'), snapshotBar(env?.meta?.source, caps, env?.meta),
      el('h2', {}, '两个口径并排'));
    if (d.audited === false) {
      // 快照里没有这栋 ⇒ 明说，绝不回一个 0 差值的行（后者会被读成「这栋完美」）。
      add(body, el('div', { class: 'ar-none' },
        el('b', { text: `${name} 在这份快照里没有对账行。` }),
        el('br'),
        `后端给的原因：${d.why || '（没给原因）'}`,
        el('br'),
        '这是「没量过」，不是「对上了」，更不是「偏差为 0」。'));
    } else {
      add(body, caliberPair(d),
        el('div', { class: 'ar-more' },
          el('span', { class: 'ar-more-k', text: '判定' }), verdictTag(d.verdict),
          el('span', { class: 'ar-more-k', text: '可比对层数' }),
          el('span', { class: 'num', text: d.pairs === undefined ? '—' : String(d.pairs) }),
          el('span', { class: 'ar-more-k', text: '平均偏差（模型−图纸）' }),
          el('span', { class: 'num', text: fmtSigned(d.avg_m2) }),
          el('span', { class: 'ar-more-k', text: '|平均偏差|' }),
          el('span', { class: 'num', text: fmtM2(d.abs_m2) }),
          el('span', { class: 'ar-more-k', text: '最差那层' }),
          el('span', { class: 'num', text: d.worst_floor === undefined ? '—' : `F${d.worst_floor}` }),
          el('span', { class: 'ar-basis', title: '层号基准：模型层号（F 0 基）', text: '模型层' })),
        el('h2', {}, '逐层明细'),
        perFloorBlock({ [name]: d.floors }));
    }
    mount(root,
      el('div', { class: 'ar-toolbar' }, back),
      el('h1', {}, `${name} · 面积`,
        el('span', { class: 'ar-sub', text: ' 两个口径并排，差是差、面积是面积' })),
      body,
      el('h2', {}, '重算这一栋（写操作）'),
      refreshBox);
    // 重算的落地面板，就长在按钮下面（refreshPanel 自己 mount 进去）。
    // 重算不改全库快照，所以这里**没有**"顺带刷新别处"的动作 —— 那会是假的。
    mount(refreshBox, refreshPanel(name, caps));
  } catch (e) {
    if (disposed) return;
    // 404 有两种：这栋楼不在快照里（上面 handled 的是 200 + audited:false），
    // 与快照里既没行也没 in unauditable（后端 404 not_found）。
    mount(root, el('div', {}, el('div', { class: 'ar-toolbar' }, back),
      panic(e, { endpoint: `/api/analysis/area/${name}`, onRetry: () => paintOne(root, name) })));
  }
}

// ── 视图入口 ───────────────────────────────────────────────────

export async function render(root, sub) {
  disposed = false;
  ensureStylesheet();
  const name = (sub || '').trim();
  if (!name) return paintFleet(root);
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) {
    mount(root, el('div', { class: 'ar-panic' },
      el('h2', { class: 'ar-panic-h', text: '楼号不合法' }),
      el('p', { class: 'ar-panic-msg',
        text: `只接受字母数字与 -_（最多 32 位）：${JSON.stringify(name)}` }),
      el('div', { class: 'ar-toolbar' },
        el('a', { class: 'lnk', href: '#/area', text: '← 回全库' }))));
    return;
  }
  return paintOne(root, name);
}

/**
 * 兜底的样式表挂载。
 *
 * ★ 为什么 JS 里还要管样式表：本视图交付时 `index.html` 漏了 area.css 那一行
 *   （其余视图的 `<link rel=「stylesheet」 href=「js/views/<名字>.css」>` 都在），
 *   而当时不许改 index.html，所以这里幂等地补一个 <link>。
 *   **2026-09-23 已把那一行补进 index.html** —— 现在这段是无害的空转
 *   （href 相同，检测到就不再插）。留着是防它哪天又被漏掉，不是它还在干活。
 */
function ensureStylesheet() {
  const href = 'js/views/area.css';
  const has = [...document.querySelectorAll('link[rel="stylesheet"]')]
    .some((l) => (l.getAttribute('href') || '').endsWith('/area.css') || l.getAttribute('href') === href);
  if (has) return;
  document.head.appendChild(el('link', { rel: 'stylesheet', href }));
}
