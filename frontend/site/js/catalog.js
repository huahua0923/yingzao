// 楼栋索引页 —— 前台的正门。
//
// 形态选的是**图册索引**（左列清单 + 右列常驻预览），不是一排卡片：
// 95 栋铺成等距卡片墙就是本仓禁止的那个"模板感"形态，而且扫不动。
// 索引 + 悬停预览既好扫，又能把"这栋楼长什么样"直接摆在旁边。
import { el, add, mount } from './dom.js';
import { API, ApiError } from './api.js';

const state = { all: [], shown: [], picked: null, q: '', styleTally: new Map() };

/* ── 配色是真信息还是通用默认 ─────────────────────────────────
 * ★ `style` 是**建模用的通用配色**，不是"这栋楼实测是什么颜色"。
 *   本仓实测：95 栋里 93 栋逐字段同值（都是老校区红砖那一套），
 *   例外只有 c103（浅灰）和 c104（因"外墙看不出颜色"被折回砖红）。
 *   把 93 栋共用的默认值印成「外墙 #a4533d」当这栋楼的属性，就是**把默认值当事实卖**。
 *   这里不写死 93 —— 从当前这份清单现算，清单变了标签跟着变，也不会过期。
 */
const styleKey = (st) => JSON.stringify(
  [st.facade, st.roof, st.inner, st.parapet, st.glass, st.door].map((x) => x ?? null));

function tallyStyles(rows) {
  const t = new Map();
  for (const b of rows) t.set(styleKey(b.style ?? {}), (t.get(styleKey(b.style ?? {})) ?? 0) + 1);
  state.styleTally = t;
}

/* 悬停预览会反复换图：已经载好的 <img> 留着复用。
 * 不复用的话每次经过一行都新建一个 img 重新请求（命中缓存也要发一次重验证请求），
 * 屏幕上是"图闪一下"。 */
const imgCache = new Map();

/** 这栋楼有没有可当缩略图的图。★ 靠 `plan_source` 先判，**不要靠请求去试**：
 *  95 栋里只有 50 栋有识别结果图，盲发会把 45 次 404 打进 console，
 *  而 404 在屏幕上和"我拼错了路径"长得一样 —— 本仓记过这笔账。 */
const hasPlan = (b) => !!b.plan_source;

/* ── 汇总条 ────────────────────────────────────────────────────
 * ★ 分母必须写出来。只印「合计 12.3 万㎡」而 95 栋里有 8 栋没数，
 *   屏幕上看不出这是"全库合计"还是"能算的那几栋合计" —— 本仓记过这笔账
 *   （memory: gauge-coverage-invisible-in-summary：「没量过」和「全对」不能长得一样）。
 *   所以每一格都带 `有数/总数`。
 */
function tally(rows) {
  const n = rows.length;
  const floors = rows.reduce((s, b) => s + (b.floor_count ?? (b.floors?.length ?? 0)), 0);
  const withArea = rows.filter((b) => Number.isFinite(b.outline_area_m2));
  const area = withArea.reduce((s, b) => s + b.outline_area_m2, 0);
  const withModel = rows.filter((b) => b.has_model).length;

  const cell = (label, value, denom) => el('div', { class: 'tally-cell' },
    el('span', { class: 'tally-v num', text: value }),
    el('span', { class: 'tally-k', text: label }),
    // 分母只在**不足总数**时印出来：全都齐的时候加一句"95/95"是噪音，
    // 但不齐的时候不印就是骗人。反过来写会两边都错。
    denom === n ? null : el('span', { class: 'tally-d', text: `（${denom}/${n} 栋有数）` }));

  return el('div', { class: 'tally' },
    cell('栋', String(n), n),
    cell('层', floors.toLocaleString('en-US'), n),
    cell('㎡', Math.round(area).toLocaleString('en-US'), withArea.length),
    cell('可三维查看', String(withModel), n));
}

/* ── 左列一行 ──────────────────────────────────────────────── */
function row(b, i) {
  const label = b.title || b.name;
  const a = el('a', {
    class: 'row',
    href: `building.html?b=${encodeURIComponent(b.name)}`,
    dataset: { name: b.name },
  },
    el('span', { class: 'row-i num', text: String(i + 1).padStart(2, '0') }),
    el('span', { class: 'row-main' },
      el('span', { class: 'row-name', text: label }),
      el('span', { class: 'row-meta' },
        el('span', { class: 'row-code', text: b.name }),
        b.has_model ? el('span', { class: 'dot dot-3d', title: '有交付三维模型', text: '3D' }) : null,
        // 角标要说的是"有没有走出图"，不是"有没有 CAD 原图" ——
        // has_cad 全库 95 栋都是真，拿它做角标等于这个角标永远不出现。
        hasPlan(b) ? null
          : el('span', { class: 'dot dot-no', title: '还没出识别结果图', text: '未出图' }))),
    el('span', { class: 'row-nums' },
      el('span', { class: 'num', text: `${b.floor_count ?? b.floors?.length ?? '—'} 层` }),
      el('span', { class: 'num dim',
        text: Number.isFinite(b.outline_area_m2)
          ? `${Math.round(b.outline_area_m2).toLocaleString('en-US')} ㎡`
          : '面积 —' })));
  a.addEventListener('mouseenter', () => preview(b));
  a.addEventListener('focus', () => preview(b));
  if (state.picked === b.name) a.setAttribute('aria-current', 'true');
  return a;
}

/* ── 右列常驻预览 ──────────────────────────────────────────── */
function preview(b) {
  state.picked = b.name;
  // 高亮跟着预览走，不只是鼠标经过：键盘 Tab 到的行也要有同样的反馈，
  // 而且筛掉之后残留的 aria-current 要清掉（否则"选中态"会指向看不见的行）。
  const list = document.getElementById('list');
  if (list) {
    for (const a of list.querySelectorAll('.row[aria-current]')) a.removeAttribute('aria-current');
    const me = list.querySelector(`.row[data-name="${CSS.escape(b.name)}"]`);
    if (me) me.setAttribute('aria-current', 'true');
  }
  const box = document.getElementById('preview');
  if (!box) return;
  const label = b.title || b.name;

  // 首层识别结果图。没有就**明说没有** —— 既不盲发请求，也不留一个破图标装死。
  // ★ 这一步也是这栋楼"跑没跑过全流程"的可见信号：全库 95 栋里只有 50 栋出了图。
  const thumb = el('div', { class: 'pv-thumb' });
  if (!hasPlan(b)) {
    add(thumb, el('p', { class: 'pv-noimg' },
      el('b', { text: '没有识别结果图' }),
      el('span', { text: '这栋楼的图纸还没走过识别 —— 不是图丢了。' })));
  } else {
    let img = imgCache.get(b.name);
    if (!img) {
      img = el('img', {
        alt: `${label} 首层识别结果图`, loading: 'lazy',
        src: API.url.plan(b.name, 0),
      });
      img.addEventListener('error', () => {
        // 有 plan_source 却取不到图 ⇒ 接口说的和产物对不上，跟"这栋没图"是两件事。
        imgCache.delete(b.name);
        mount(thumb, el('p', { class: 'pv-noimg' },
          el('b', { text: '图取不到' }),
          el('span', { text: `接口说这栋有识别结果图，但地址取不回来：${img.src}` })));
      });
      imgCache.set(b.name, img);
    }
    add(thumb, img);
  }

  const st = b.style ?? {};
  const swatch = (hex, name) => (hex
    ? el('span', { class: 'sw' }, el('i', { style: { background: hex }, 'aria-hidden': 'true' }), name)
    : null);

  // 这一栋的配色是不是全库通用的那一套？过半同值就按"通用"说。
  // ★ 第三态：清单还没算过 tally 时**不能说"本楼专用"** —— 那是对具体事实的断言，
  //   而"没量过"和"量出来是本楼专用"在屏幕上会长得一样（本仓栽过好几次）。
  const tallied = state.styleTally.size > 0;
  const same = state.styleTally.get(styleKey(st)) ?? 0;
  const common = tallied && same >= 2 && same * 2 > state.all.length;
  const styleBlock = (st.facade || st.roof)
    ? el('div', { class: 'pv-style' },
      el('div', { class: 'pv-sw-row' },
        swatch(st.facade, '外墙'), swatch(st.roof, '屋面'), swatch(st.door, '门')),
      el('p', { class: 'pv-style-note', text: !tallied
        ? '配色来源未判定 —— 楼栋清单还没算完，这里不猜。'
        : common
          ? `建模通用配色（全库 ${same}/${state.all.length} 栋同值）—— 这是模型用的色，不是本楼实测外观。`
          : '本楼专用配色（取自本楼 profile）。'}))
    : null;

  mount(box,
    el('p', { class: 'pv-eyebrow', text: b.name }),
    el('h2', { class: 'pv-title', text: label }),
    thumb,
    el('dl', { class: 'pv-facts' },
      fact('层数', b.floor_count ?? b.floors?.length ?? '—', true),
      fact('外轮廓面积', Number.isFinite(b.outline_area_m2)
        ? `${Math.round(b.outline_area_m2).toLocaleString('en-US')} ㎡` : '—', true),
      fact('层高', Number.isFinite(b.layer_height) ? `${b.layer_height} m` : '—', true),
      fact('识别器', b.classifier || '—'),
      fact('图源', b.plan_source || '—')),
    styleBlock,
    b.notes?.length
      ? el('div', { class: 'pv-notes' },
        el('h3', { text: '备注' }), el('ul', {}, b.notes.map((t) => el('li', { text: t }))))
      : null,
    el('div', { class: 'pv-actions' },
      b.has_model
        ? el('a', { class: 'btn btn-1', href: `building.html?b=${encodeURIComponent(b.name)}`, text: '打开三维' })
        : el('span', { class: 'btn btn-off', title: '这栋楼没有交付三维模型', text: '无三维模型' })));
}

function fact(k, v, mono) {
  return el('div', { class: 'pv-fact' },
    el('dt', { text: k }),
    el('dd', { class: mono ? 'num' : null, text: String(v) }));
}

/* ── 搜索 / 渲染 ───────────────────────────────────────────── */
function applyFilter() {
  const q = state.q.trim().toLowerCase();
  state.shown = q
    ? state.all.filter((b) =>
      `${b.name} ${b.title ?? ''}`.toLowerCase().includes(q))
    : state.all;
  const list = document.getElementById('list');
  if (!list) return;
  if (!state.shown.length) {
    mount(list, el('li', { class: 'empty', text: `没有匹配「${state.q}」的楼栋` }));
    return;
  }
  mount(list, state.shown.map(row));
}

/** 后端连不上 / 路由不存在 —— 都要说清楚，不能白屏也不能显示 0。 */
function panic(err) {
  const main = document.getElementById('catalog');
  if (!main) return;
  const isNet = err instanceof ApiError && err.code === 'network';
  mount(main, el('div', { class: 'panic' },
    el('h2', { text: isNet ? '连不上后端' : '读楼栋清单失败' }),
    el('p', { text: err.message }),
    isNet
      ? el('p', { class: 'panic-hint', text:
          '前台的数据全部来自建模后台（默认 8140）。后端没起时这里读不到任何一栋楼 —— '
          + '这跟"库里一栋楼都没有"是两件事，所以这里明说是连不上。' })
      : el('p', { class: 'panic-hint', text: String(err.detail ?? '') })));
}

async function boot() {
  const main = document.getElementById('catalog');
  mount(main, el('p', { class: 'loading', text: '正在读楼栋清单…' }));

  let rows;
  try {
    rows = await API.buildings();
  } catch (e) { panic(e); return; }

  if (!Array.isArray(rows) || !rows.length) {
    mount(main, el('div', { class: 'panic' },
      el('h2', { text: '楼栋清单是空的' }),
      el('p', { text: '后端答了，但一栋楼都没有。这不是连接问题，是库里确实没有。' })));
    return;
  }

  state.all = rows;
  tallyStyles(rows);                       // ★ 必须在 applyFilter/preview 之前算完
  const withPlan = rows.filter(hasPlan).length;

  mount(main,
    el('section', { class: 'lede-block' },
      el('p', { class: 'eyebrow', text: '成都理工大学 · 校园建筑数字档案' }),
      el('h1', { class: 'wordmark', text: '营造' }),
      el('p', { class: 'lede', text:
        '从 CAD 图纸读出每栋楼的外轮廓、房间与构件，逐层重建成可浏览的数字孪生。'
        + '这里按楼栋陈列 —— 左边是索引，右边是它长什么样。' }),
      tally(rows)),
    el('section', { class: 'index' },
      el('div', { class: 'index-head' },
        el('label', { class: 'search' },
          el('span', { class: 'search-k', text: '检索' }),
          el('input', {
            type: 'search', id: 'q', placeholder: '楼名或代号，如 艺术楼 / c113',
            autocomplete: 'off',
            oninput: (e) => { state.q = e.target.value; applyFilter(); },
          })),
        el('p', { class: 'index-count', id: 'count' })),
      el('div', { class: 'index-body' },
        el('ol', { class: 'list', id: 'list' }),
        el('aside', { class: 'preview', id: 'preview' },
          el('p', { class: 'pv-hint', text: '把鼠标放到左边任意一栋上 —— 这里会显示它。' })))),
  );

  applyFilter();
  const c = document.getElementById('count');
  // 分母写出来：不写"50/95"的话，"95 栋都有图"和"只有 50 栋有"长得一样。
  if (c) c.textContent = `共 ${rows.length} 栋 · 其中 ${withPlan} 栋已出识别结果图`;
  if (rows.length) preview(rows[0]);
}

boot();
