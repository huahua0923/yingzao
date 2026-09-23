// 单栋呈现页 —— 三维 + 逐层图纸 + 数字，三样同时在场上。
//
// 布局取舍：不做"三维/平面图"的模式切换。切模式会让人每次想看另一面就丢一次上下文，
// 而这两样本来就该互相印证（模型对不对，一眼扫旁边的图）。所以是**并排**：
// 左边三维舞台，右边楼层表，下面图纸带 —— 点楼层，图跟着换。
//
// ★ 三维**不随楼层切片**，这里明说：要从 GLB 里切出"第 N 层"得知道
//   导出时 CAD 标高到模型 Y 的变换，而那个变换我手上没有。用包围盒按层数等分去猜
//   会得到一栋"看着挺像"的楼 —— 本仓在自洽的错数上栽过（memory:
//   per-item-count-not-max-threshold 那一族）。所以三维只显示整栋，并把它写在屏幕上。
import { el, add, mount } from './dom.js';
import { API, ApiError } from './api.js';

const state = {
  name: '', detail: null, floors: [], floor: 0,
  tab: 'plan',                       // 'plan' 识别结果图 | 'cad' CAD 原图
  viewer: null,
};

const fmt = (n, unit = '') =>
  (Number.isFinite(n) ? `${Math.round(n).toLocaleString('en-US')}${unit}` : '—');

/** 产物条目。★ artifacts 是**列表**（[{key,label,exists,bytes,url}]），不是字典 ——
 *  按下标取会静默拿到 undefined，然后屏幕上显示成"这栋楼没有模型"。
 *  只有 exists 为真才算有：缺的产物后端也会给一条（exists:false）。 */
const art = (key) => state.detail?.artifacts?.find((a) => a.key === key) || null;
const hasArt = (key) => !!art(key)?.exists;

/* ── 楼层表 ─────────────────────────────────────────────────── */
function floorRow(f) {
  const on = f.floor === state.floor;
  const btn = el('button', {
    type: 'button', class: 'flr', 'aria-pressed': on ? 'true' : 'false',
    onclick: () => selectFloor(f.floor),
  },
    el('span', { class: 'flr-tag num', text: `F${f.floor}` }),
    el('span', { class: 'flr-mid' },
      el('span', { class: 'num', text: fmt(f.outline_area_m2, ' ㎡') }),
      el('span', { class: 'dim', text: `${f.rooms ?? '—'} 间` })),
    el('span', { class: 'flr-cnt dim num', text:
      f.counts ? `墙 ${f.counts.walls ?? '—'} · 窗 ${f.counts.windows ?? '—'}` : '' }));
  return el('li', {}, btn);
}

function paintFloors() {
  const box = document.getElementById('floors');
  if (!box) return;
  mount(box, state.floors.map(floorRow));
}

function selectFloor(f) {
  state.floor = f;
  paintFloors();
  paintDrawing();
}

/* ── 图纸带 ─────────────────────────────────────────────────── */
function paintDrawing() {
  const box = document.getElementById('drawing');
  if (!box) return;
  const f = state.floors.find((x) => x.floor === state.floor);
  const entry = f ? f[state.tab] : null;

  const tabs = el('div', { class: 'tabs' },
    [['plan', '识别结果图'], ['cad', 'CAD 原图']].map(([k, label]) => el('button', {
      type: 'button', class: 'tab', 'aria-pressed': state.tab === k ? 'true' : 'false',
      // 哪套图没有就置灰，而不是让人点进去看一个破图标
      disabled: !f?.[k]?.exists,
      title: f?.[k]?.exists ? '' : `这栋楼没有「${label}」`,
      text: label,
      onclick: () => { state.tab = k; paintDrawing(); },
    })));

  const body = el('div', { class: 'draw-body' });
  if (!f) {
    add(body, el('p', { class: 'draw-miss', text: '这栋楼没有逐层数据。' }));
  } else if (!entry || !entry.exists) {
    add(body, el('p', { class: 'draw-miss',
      text: `F${state.floor} 没有「${state.tab === 'plan' ? '识别结果图' : 'CAD 原图'}」。` }));
  } else {
    const img = el('img', {
      class: 'draw-img', alt: `${state.detail?.profile?.title || state.name} F${state.floor} ${entry.label || ''}`,
      src: entry.url, loading: 'eager',
    });
    img.addEventListener('error', () => {
      // 图片挂了也要说话：这里的 URL 是后端给的，它挂说明接口和产物对不上，
      // 不该表现成"这层没图"。
      mount(body, el('p', { class: 'draw-miss',
        text: `图取不到（后端给的地址是 ${entry.url}）。这不是"这层没有图"，是那份图读不出来。` }));
    });
    add(body, el('figure', { class: 'draw-fig' }, img,
      el('figcaption', {},
        el('span', { text: `${entry.label || state.tab} · F${state.floor}` }),
        el('span', { class: 'dim num', text: entry.bytes ? `${Math.round(entry.bytes / 1024)} KB` : '' }),
        el('span', { class: 'dim', text: entry.source ? `来源 ${entry.source}` : '' }))));
  }

  mount(box,
    el('div', { class: 'draw-head' },
      el('h2', { class: 'sec-h', text: '图纸' }), tabs),
    body);
}

/* ── 三维舞台 ───────────────────────────────────────────────── */
async function paintStage() {
  const stage = document.getElementById('stage');
  if (!stage) return;
  const hud = el('div', { class: 'hud', id: 'hud' });

  const modelArt = art('model');
  if (!modelArt?.exists || !modelArt.url) {
    mount(stage, el('p', { class: 'stage-miss',
      text: '这栋楼还没有交付三维模型。下面的图纸和数字仍然有效 —— '
          + '缺的是模型，不是这栋楼的资料。' }));
    return;
  }

  const canvas = el('canvas', { id: 'gl', 'aria-label': '这栋楼的三维模型' });
  mount(stage, canvas, hud,
    // ★ 两条提示装进**同一个**定位容器。定位（absolute + right/top）由容器负责，
    //   条目只管排版 —— 否则两条各按同一组坐标落进同一格，两行汉字互相压掉，
    //   屏幕上是一团糊字，看着像渲染坏了（见 site.css .stage-notes 注释）。
    el('div', { class: 'stage-notes' },
      el('p', { class: 'stage-note',
        text: '三维显示整栋，不随楼层切换 —— 要逐层看请对照下方图纸。' }),
      el('p', { class: 'stage-note dim',
        // ★ 模型是砖红的，实景是米白的 —— 这件事必须写在屏幕上。
        //   模型里的颜色是**建模通用配色**（全库 94/95 栋同一套老校区红砖），
        //   不是"这栋楼长这样"。不说的话，看的人会以为这栋楼真是砖红的。
        text: '模型配色为建模通用配色，不是本楼实测外观；本楼实景见页末「实景」。' })),
    el('div', { class: 'stage-tools' }, el('button', {
      type: 'button', class: 'btn btn-ghost', text: '复位视角',
      onclick: () => state.viewer?.refit(),
    })));

  let mod;
  try {
    mod = await import('./viewer.js');
  } catch (e) {
    mount(hud, el('b', { text: '三维模块加载失败' }), el('span', { text: String(e.message || e) }));
    return;
  }

  const total = modelArt.bytes ?? null;
  state.viewer = mod.createViewer(canvas);
  try {
    const info = await state.viewer.load(modelArt.url, (loaded, t) => {
      const pct = t ? Math.round((loaded / t) * 100) : null;
      hud.textContent = pct === null
        ? `载入中 ${Math.round(loaded / 1048576)} MB`
        : `载入中 ${pct}%（${Math.round(loaded / 1048576)}/${Math.round(t / 1048576)} MB）`;
    });
    state.viewer.start();
    hud.replaceChildren(
      el('span', { class: 'num', text: `${(info.triangles / 1000).toFixed(0)}k 三角面` }),
      el('span', { class: 'num',
        text: `${info.size.x.toFixed(0)} × ${info.size.z.toFixed(0)} × ${info.size.y.toFixed(0)} m` }),
      total ? el('span', { class: 'num dim', text: `GLB ${(total / 1048576).toFixed(1)} MB` }) : null,
      el('span', { class: 'dim', text: '左键转 · 滚轮缩放 · 右键平移' }));
  } catch (e) {
    // 模型挂掉不该带走图纸和数字 —— 它们跟模型是两条独立的产物。
    mount(hud, el('b', { text: '模型载入失败' }), el('span', { text: String(e.message || e) }));
  }
}

/* ── 页首与构件合计 ─────────────────────────────────────────── */
function paintHead(p) {
  return el('header', { class: 'b-head' },
    el('p', { class: 'eyebrow', text: state.name }),
    el('h1', { class: 'b-title', text: p?.title || state.name }),
    el('p', { class: 'b-sub' },
      el('span', { class: 'num', text: `${state.floors.length} 层` }),
      el('span', { class: 'b-sep', text: '·' }),
      el('span', { class: 'num', text: `层高 ${p?.layer_height ?? '—'} m` }),
      el('span', { class: 'b-sep', text: '·' }),
      el('span', { text: `识别器 ${p?.classifier || '—'}` }),
      p?.dxf_name ? el('span', { class: 'b-sep', text: '·' }) : null,
      p?.dxf_name ? el('span', { class: 'num dim', text: p.dxf_name }) : null));
}

function paintTotals() {
  const keys = ['walls', 'windows', 'columns', 'doors', 'elevators', 'stairs', 'stairwells'];
  const label = { walls: '墙', windows: '窗', columns: '柱', doors: '门',
                  elevators: '电梯', stairs: '楼梯', stairwells: '梯井' };
  const sum = {};
  for (const f of state.floors) for (const k of keys) sum[k] = (sum[k] ?? 0) + (f.counts?.[k] ?? 0);
  const has = state.floors.some((f) => f.counts);
  return el('section', { class: 'b-totals' },
    el('h2', { class: 'sec-h', text: '构件合计' }),
    has
      ? el('div', { class: 'tot-row' }, keys.map((k) => el('div', { class: 'tot' },
          el('span', { class: 'tot-v num', text: String(sum[k]) }),
          el('span', { class: 'tot-k', text: label[k] }))))
      : el('p', { class: 'draw-miss', text: '逐层数据里没有构件计数，不知道是没识别还是没落盘。' }),
    el('p', { class: 'b-note dim',
      text: `以上为 ${state.floors.length} 层逐层计数之和（不是全库统计）。` +
            '房间面积合计为 0 表示这栋楼的房间没有量到面积，不是"面积为零"。' }));
}

/* ── 错误 ───────────────────────────────────────────────────── */
function panic(title, msg, hint) {
  mount(document.getElementById('building'), el('div', { class: 'panic' },
    el('h2', { text: title }), el('p', { text: msg }),
    hint ? el('p', { class: 'panic-hint', text: hint }) : null,
    el('p', {}, el('a', { class: 'btn btn-1', href: 'index.html', text: '回楼栋索引' }))));
}

/* ── 入口 ───────────────────────────────────────────────────── */
async function boot() {
  const name = new URLSearchParams(location.search).get('b') || '';
  const main = document.getElementById('building');
  if (!name) {
    panic('地址里没有楼号', '这个页面要知道看哪一栋 —— 例如 building.html?b=c113。');
    return;
  }
  state.name = name;
  document.title = `${name} · 营造`;

  let detail, floors;
  try {
    [detail, floors] = await Promise.all([API.building(name), API.floors(name)]);
  } catch (e) {
    if (e instanceof ApiError && e.code === 'network') {
      panic('连不上后端', e.message,
        '这一页的三维、图纸、数字全都来自建模后台。连不上就是一样都取不到 —— '
        + '这跟"没有这栋楼"不是一回事。');
    } else if (e instanceof ApiError && e.status === 404) {
      panic(`没有「${name}」这栋楼`, e.message, '楼号写错了，或者这栋楼还没进库。');
    } else {
      panic('读这栋楼失败', e.message, String(e.detail ?? ''));
    }
    return;
  }

  state.detail = detail;
  state.floors = Array.isArray(floors) ? floors : [];
  state.floor = state.floors.length ? state.floors[0].floor : 0;

  document.title = `${detail?.profile?.title || name} · 营造`;

  mount(main,
    paintHead(detail?.profile),
    el('section', { class: 'b-grid' },
      el('div', { class: 'stage', id: 'stage' }),
      el('aside', { class: 'b-side' },
        el('h2', { class: 'sec-h', text: '楼层' }),
        el('ol', { class: 'flr-list', id: 'floors' }))),
    el('section', { class: 'b-draw', id: 'drawing' }),
    paintTotals(),
    photos(state.name));

  paintFloors();
  paintDrawing();
  await paintStage();
}

/* ── 实景照片（有就显示，没有就不显示这一块）──────────────────
 * 照片不是识别产物，也不在 data/buildings/ 里（那是流水线的地盘，
 * 一个目录一个所有者）—— 它们是**前台自己的呈现素材**，随前台一起部署。
 * 清单是本目录的 photos/index.json，内容取自用户机器上的人工挑选。
 */
function photos(name) {
  const holder = el('section', { class: 'b-photos', id: 'photos' });
  fetch('photos/index.json', { cache: 'no-cache' })
    .then((r) => (r.ok ? r.json() : null))
    .then((man) => {
      const list = man?.[name];
      if (!Array.isArray(list) || !list.length) return;   // 没照片就不占版面
      mount(holder,
        el('h2', { class: 'sec-h', text: '实景' }),
        el('div', { class: 'ph-grid' }, list.map((p) => el('figure', { class: 'ph' },
          el('img', { src: `photos/${name}/${p.src}`, alt: p.caption || `${name} 实景`, loading: 'lazy' }),
          el('figcaption', {},
            el('span', { text: p.caption || '' }),
            p.credit ? el('span', { class: 'dim', text: p.credit }) : null)))));
    })
    .catch(() => { /* 没有照片清单不算错：这一块本来就可以不存在 */ });
  return holder;
}

// 离开页面时把 WebGL 上下文收掉（rAF 不停会一直占着）。
addEventListener('pagehide', () => state.viewer?.dispose());

boot();
